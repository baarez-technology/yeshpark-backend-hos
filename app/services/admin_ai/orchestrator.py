"""
LangGraph StateGraph Orchestrator for Admin AI Multi-Agent Architecture.

Coordinates specialized agents through a defined workflow:
  security_gate → context_load → comprehension → route_execution → response_format → context_update

Follows the same pattern as the existing guest_agi_v2.py StateGraph.
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.admin_ai.protocol import (
    OrchestratorState,
    OrchestratorResponse,
    SessionContext,
    ComprehensionResult,
    DetectedIntent,
    IntentCategory,
    ActiveEntities,
    DataResult,
    ActionConfirmation,
    ActionOutcome,
)
from app.services.admin_ai.agents.comprehension import ComprehensionAgent
from app.services.admin_ai.agents.context import ContextAgent
from app.services.admin_ai.security import SecurityValidator
from app.services.admin_ai.sql_executor import SQLExecutor, QUERY_TEMPLATES
from app.services.admin_ai.action_executor import (
    ActionExecutor, EmailActionExecutor, ActionRequest, ActionType, PendingAction
)
from app.services.admin_ai.schema_provider import get_schema_provider
from app.models.admin_ai_audit import AdminAIAudit, AdminAISession, AdminAIMessage

logger = logging.getLogger(__name__)

# LangChain LLM for response formatting
try:
    from langchain_openai import ChatOpenAI
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


# ─────────────────────── Intent → Legacy Handler Mapping ───────────────────────

# Maps new multi-agent intents to the legacy AdminAIAssistant handler method names.
# In Sprint 1, the orchestrator delegates to the monolith's handlers for actual execution.
# In Sprint 2+, these are replaced by registered tools.

_INTENT_CATEGORIES = {
    # Query intents
    "query_bookings": IntentCategory.QUERY,
    "query_bookings_today": IntentCategory.QUERY,
    "query_checkouts_today": IntentCategory.QUERY,
    "query_guests": IntentCategory.QUERY,
    "query_vip_guests": IntentCategory.QUERY,
    "query_revenue": IntentCategory.QUERY,
    "query_occupancy": IntentCategory.QUERY,
    "query_rooms": IntentCategory.QUERY,
    "query_staff": IntentCategory.QUERY,
    "query_housekeeping": IntentCategory.QUERY,
    "query_maintenance": IntentCategory.QUERY,
    "query_room_occupant": IntentCategory.QUERY,
    # Action intents
    "create_booking": IntentCategory.ACTION,
    "create_task": IntentCategory.ACTION,
    "create_maintenance": IntentCategory.ACTION,
    "create_guest_note": IntentCategory.ACTION,
    "update_booking": IntentCategory.ACTION,
    "update_room": IntentCategory.ACTION,
    "update_guest": IntentCategory.ACTION,
    "assign_task": IntentCategory.ACTION,
    "assign_room": IntentCategory.ACTION,
    "transfer_room": IntentCategory.ACTION,
    "send_email": IntentCategory.ACTION,
    "draft_email": IntentCategory.ACTION,
    # Report intents
    "analyze_trends": IntentCategory.REPORT,
    "generate_report": IntentCategory.REPORT,
    "forecast": IntentCategory.REPORT,
    # General
    "general": IntentCategory.GENERAL,
    "help": IntentCategory.GENERAL,
    "follow_up": IntentCategory.GENERAL,
    "unknown": IntentCategory.UNKNOWN,
}


class AdminAIOrchestrator:
    """LangGraph-based orchestrator for the Admin AI multi-agent system.

    In Sprint 1, this orchestrator:
    - Replaces regex IntentClassifier with LLM-backed ComprehensionAgent
    - Adds context tracking (active entities, sliding window memory)
    - Delegates actual execution to the existing monolith's handlers
    - Supports multi-intent decomposition
    - Has feature flag for instant rollback

    In Sprint 2+, execution is delegated to registered tools instead of monolith.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._comprehension = ComprehensionAgent()
        self._context = ContextAgent()
        self._security = SecurityValidator()

        # These will be used for delegation to monolith in Sprint 1
        self._sql_executor = SQLExecutor(session)
        self._action_executor = ActionExecutor(session)
        self._email_executor = EmailActionExecutor(session)

        # Response formatter LLM
        self._response_llm: Optional[Any] = None
        self._init_response_llm()

        # Build the StateGraph
        self._graph = self._build_graph()

    def _init_response_llm(self):
        """Initialize LLM for natural language response generation."""
        if not LLM_AVAILABLE:
            return
        try:
            from dotenv import dotenv_values
            from pathlib import Path

            env_path = Path(__file__).resolve().parent.parent.parent / ".env"
            env_vars = dotenv_values(str(env_path))
            api_key = env_vars.get("OPENAI_API_KEY") or settings.openai_api_key
            if not api_key:
                return

            model = env_vars.get("OPENAI_MODEL", settings.openai_model) or "gpt-4"
            self._response_llm = ChatOpenAI(
                model=model, temperature=0.3, api_key=api_key, max_tokens=500,
            )
        except Exception as e:
            logger.error(f"Failed to init response LLM: {e}")

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph with all agent nodes."""
        graph = StateGraph(OrchestratorState)

        # Add nodes
        graph.add_node("security_gate", self._node_security_gate)
        graph.add_node("context_load", self._node_context_load)
        graph.add_node("comprehension", self._node_comprehension)
        graph.add_node("route_execution", self._node_route_execution)
        graph.add_node("response_format", self._node_response_format)
        graph.add_node("context_update", self._node_context_update)

        # Set entry point
        graph.set_entry_point("security_gate")

        # Add edges
        graph.add_conditional_edges(
            "security_gate",
            self._should_continue_after_security,
            {
                "blocked": "response_format",
                "continue": "context_load",
            }
        )
        graph.add_edge("context_load", "comprehension")
        graph.add_conditional_edges(
            "comprehension",
            self._should_continue_after_comprehension,
            {
                "confirmation": "route_execution",
                "cancellation": "response_format",
                "clarification": "response_format",
                "execute": "route_execution",
                "general": "response_format",
            }
        )
        graph.add_edge("route_execution", "response_format")
        graph.add_edge("response_format", "context_update")
        graph.add_edge("context_update", END)

        return graph.compile()

    # ─────────────────────── Graph Nodes ───────────────────────

    async def _node_security_gate(self, state: OrchestratorState) -> dict:
        """Security validation node — checks for prompt injection."""
        message = state["user_message"]
        check = self._security.validate_user_input(message)

        if not check.is_safe:
            logger.warning(f"Security blocked: {check.block_reason}")
            return {
                "security_passed": False,
                "security_block_reason": check.block_reason or "Request blocked",
                "response_message": "I apologize, but I cannot process that request. Please rephrase your question.",
                "response_intent": "blocked",
                "response_confidence": 0.0,
                "response_error": "Request blocked for security reasons",
            }

        return {
            "security_passed": True,
            "security_block_reason": "",
        }

    async def _node_context_load(self, state: OrchestratorState) -> dict:
        """Load context — build summary from previous messages and active entities."""
        session_ctx_raw = state.get("session_context", {})

        # Parse session context
        previous_messages = session_ctx_raw.get("previous_messages") or session_ctx_raw.get("previousMessages") or []
        existing_summary = state.get("context_summary", "")

        # Build context summary
        context_summary = self._context.build_context_summary(
            previous_messages=previous_messages,
            existing_summary=existing_summary,
        )

        # Load active entities from state (persisted across turns)
        active_raw = state.get("active_entities", {})
        active_entities = active_raw if active_raw else {}

        return {
            "context_summary": context_summary,
            "active_entities": active_entities,
        }

    async def _node_comprehension(self, state: OrchestratorState) -> dict:
        """Comprehension node — LLM intent classification + entity extraction."""
        message = state["user_message"]
        context_summary = state.get("context_summary", "")
        active_entities = state.get("active_entities", {})

        result = await self._comprehension.classify(
            message=message,
            context_summary=context_summary,
            active_entities=active_entities,
        )

        # ── Pending intent carry-over ──────────────────────────────
        # If the previous turn asked for missing params (e.g., "I still need: Guest name"),
        # and the current message has no strong intent but contains entities that fill the
        # gap, re-inject the pending intent so the flow continues.
        result = self._apply_pending_intent(result, state)

        return {
            "comprehension": result.model_dump(),
        }

    def _apply_pending_intent(
        self, result: ComprehensionResult, state: OrchestratorState
    ) -> ComprehensionResult:
        """Carry over a pending action intent when the user provides missing data.

        Examines previous messages to detect if the AI just asked for missing booking/action
        params. If so, and the current message has no strong action intent but does have
        relevant entities, re-inject the original intent.
        """
        # Only apply if no strong action/query intent was detected
        has_strong_intent = any(
            i.category in (IntentCategory.ACTION, IntentCategory.QUERY, IntentCategory.REPORT)
            and i.confidence >= 0.6
            for i in result.intents
        )
        if has_strong_intent:
            return result

        # Look at previous messages for a pending intent
        session_ctx = state.get("session_context", {})
        prev_messages = (
            session_ctx.get("previous_messages")
            or session_ctx.get("previousMessages")
            or []
        )
        if not prev_messages:
            return result

        # Find the last assistant message that looks like a "missing params" prompt
        pending_intent = self._detect_pending_intent(prev_messages)
        if not pending_intent:
            return result

        # Extract entities from the current message (regex)
        from app.services.admin_ai.agents.comprehension import EntityExtractor
        entities = EntityExtractor.extract(state["user_message"])

        # Check if the entities fill the gap for the pending intent
        if pending_intent == "create_booking":
            has_booking_data = (
                entities.get("booking_guest_name") or entities.get("guest_name")
                or entities.get("checkin_date") or entities.get("checkout_date")
                or entities.get("room_type")
            )
            if has_booking_data:
                logger.info(f"Pending intent carry-over: create_booking (entities: {list(entities.keys())})")
                result.intents = [DetectedIntent(
                    intent="create_booking",
                    category=IntentCategory.ACTION,
                    confidence=0.9,
                    entities=entities,
                )]
                result.is_follow_up = True
                return result

        elif pending_intent == "create_task":
            if entities.get("room_id"):
                result.intents = [DetectedIntent(
                    intent="create_task",
                    category=IntentCategory.ACTION,
                    confidence=0.9,
                    entities=entities,
                )]
                result.is_follow_up = True
                return result

        elif pending_intent == "update_booking":
            if entities.get("booking_id"):
                result.intents = [DetectedIntent(
                    intent="update_booking",
                    category=IntentCategory.ACTION,
                    confidence=0.9,
                    entities=entities,
                )]
                result.is_follow_up = True
                return result

        # Also handle the case where a user provides a bare name (no "Book" prefix)
        # after the AI asked for booking details — e.g., "Ishan Kumar"
        if pending_intent == "create_booking" and not entities:
            msg = state["user_message"].strip()
            # Check if message looks like raw booking data (name + dates)
            import re
            name_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', msg)
            if name_match:
                entities["booking_guest_name"] = name_match.group(1)
                # Re-extract other entities (dates, room type) with broader patterns
                full_entities = EntityExtractor.extract(msg)
                entities.update(full_entities)
                if entities.get("booking_guest_name"):
                    logger.info(f"Pending intent carry-over (bare name): create_booking")
                    result.intents = [DetectedIntent(
                        intent="create_booking",
                        category=IntentCategory.ACTION,
                        confidence=0.85,
                        entities=entities,
                    )]
                    result.is_follow_up = True
                    return result

        return result

    def _detect_pending_intent(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """Detect if the last assistant message was asking for missing params.

        Returns the pending intent name if found, None otherwise.
        """
        # Scan last 2 assistant messages (in reverse)
        for msg in reversed(messages[-4:]):
            role = msg.get("role", "")
            content = (msg.get("content") or "").lower()
            if role != "assistant":
                continue

            # Booking creation prompts
            if any(phrase in content for phrase in [
                "i still need",
                "i'd be happy to create a booking",
                "guest name, check-in date",
                "provide all details",
            ]):
                return "create_booking"

            # Housekeeping task prompts
            if "specify a room number for the housekeeping" in content:
                return "create_task"
            if "which room should i" in content:
                return "create_task"

            # Booking update prompts
            if "which booking would you like to update" in content:
                return "update_booking"
            if "provide a booking id" in content:
                return "update_booking"

            # Room update prompts
            if "which room should i update" in content:
                return "update_room"

            break  # Only check the most recent assistant message

        return None

    async def _node_route_execution(self, state: OrchestratorState) -> dict:
        """Route and execute intents — delegates to monolith handlers in Sprint 1.

        For multi-intent messages, executes each intent sequentially and
        collects results.
        """
        comp = ComprehensionResult(**state["comprehension"])
        session_ctx_raw = state.get("session_context", {})
        active_raw = state.get("active_entities", {})
        active_entities = ActiveEntities(**active_raw) if active_raw else ActiveEntities()

        # Handle confirmation of pending action
        if comp.is_confirmation:
            return await self._handle_confirmation(state)

        # Execute each detected intent
        all_results = []
        all_query_results = []
        all_query_metadata = {}
        pending_action = {}
        primary_intent = "general"
        primary_confidence = 0.3

        for detected in comp.intents:
            primary_intent = detected.intent
            primary_confidence = detected.confidence

            # Resolve pronouns from active entities
            resolved_entities = self._context.resolve_pronouns(
                entities=detected.entities,
                active=active_entities,
                intent=detected.intent,
            )

            # Auto-fill from session context
            try:
                session_ctx = SessionContext(**session_ctx_raw) if session_ctx_raw else SessionContext()
                resolved_entities, auto_filled = self._context.merge_session_context(
                    entities=resolved_entities,
                    session_ctx=session_ctx,
                    intent=detected.intent,
                )
            except Exception:
                auto_filled = []

            # Update active entities with new ones
            active_entities = self._context.update_active_entities(
                current=active_entities,
                new_entities=resolved_entities,
            )

            # Execute via monolith delegation
            result = await self._execute_intent(
                intent=detected.intent,
                category=detected.category,
                entities=resolved_entities,
                user_id=state["user_id"],
                session_id=state["session_id"],
            )

            all_results.append(result)

            if result.get("query_results"):
                all_query_results.extend(result["query_results"])
            if result.get("query_metadata"):
                all_query_metadata.update(result["query_metadata"])
            if result.get("pending_action"):
                pending_action = result["pending_action"]

        return {
            "execution_results": all_results,
            "response_query_results": all_query_results,
            "response_query_metadata": all_query_metadata,
            "pending_action": pending_action,
            "active_entities": active_entities.model_dump(),
            "response_intent": primary_intent,
            "response_confidence": primary_confidence,
        }

    async def _node_response_format(self, state: OrchestratorState) -> dict:
        """Format the final response — LLM generates natural language from raw data."""
        # If already have a response message (from security block or simple cases)
        if state.get("response_message") and not state.get("execution_results"):
            return {}

        comp_raw = state.get("comprehension", {})
        comp = ComprehensionResult(**comp_raw) if comp_raw else None
        results = state.get("execution_results", [])
        query_results = state.get("response_query_results", [])
        pending = state.get("pending_action", {})

        # Handle cancellation
        if comp and comp.is_cancellation:
            return {
                "response_message": "Action cancelled. Is there anything else I can help you with?",
                "response_intent": "cancelled",
                "response_confidence": 1.0,
                "response_suggestions": [],
            }

        # Handle clarification needed
        if comp and comp.requires_clarification:
            return {
                "response_message": comp.clarification_question or "Could you please provide more details?",
                "response_intent": "clarification",
                "response_confidence": 0.5,
                "response_suggestions": [],
            }

        # Collect response parts from execution results
        response_parts = []
        suggestions = []

        for result in results:
            if isinstance(result, dict):
                if result.get("message"):
                    response_parts.append(result["message"])
                if result.get("suggestions"):
                    suggestions.extend(result["suggestions"])

        # Generate final message
        if response_parts:
            message = "\n\n---\n\n".join(response_parts) if len(response_parts) > 1 else response_parts[0]
        else:
            message = state.get("response_message", "I'm here to help! What would you like to know?")

        # Generate suggestions if not already present
        if not suggestions:
            intent = state.get("response_intent", "general")
            suggestions = self._generate_suggestions(intent)

        return {
            "response_message": message,
            "response_suggestions": suggestions,
        }

    async def _node_context_update(self, state: OrchestratorState) -> dict:
        """Update context — persist active entities and log audit."""
        # Log the message to DB
        try:
            await self._log_messages(state)
        except Exception as e:
            logger.error(f"Failed to log messages: {e}")

        # Log audit
        try:
            audit_id = await self._log_audit(state)
            return {"audit_id": audit_id}
        except Exception as e:
            logger.error(f"Failed to log audit: {e}")
            return {}

    # ─────────────────────── Conditional Edges ───────────────────────

    def _should_continue_after_security(self, state: OrchestratorState) -> str:
        if state.get("security_passed"):
            return "continue"
        return "blocked"

    def _should_continue_after_comprehension(self, state: OrchestratorState) -> str:
        comp_raw = state.get("comprehension", {})
        if not comp_raw:
            return "general"

        comp = ComprehensionResult(**comp_raw)

        if comp.is_confirmation:
            return "confirmation"
        if comp.is_cancellation:
            return "cancellation"
        if comp.intents:
            first_cat = comp.intents[0].category
            if first_cat in (IntentCategory.QUERY, IntentCategory.ACTION, IntentCategory.REPORT):
                # Route through execution even if clarification is needed —
                # _check_missing_params produces structured prompts the carry-over can detect
                return "execute"
        if comp.requires_clarification:
            return "clarification"
        return "general"

    # ─────────────────────── Execution Helpers ───────────────────────

    async def _execute_intent(
        self,
        intent: str,
        category: IntentCategory,
        entities: Dict[str, Any],
        user_id: int,
        session_id: str,
    ) -> Dict[str, Any]:
        """Execute a single intent by delegating to existing monolith handlers.

        In Sprint 1, this is a bridge — it calls the same SQL/action executors
        that the monolith uses. In Sprint 2+, this delegates to registered tools.
        """
        try:
            if category == IntentCategory.QUERY:
                return await self._execute_query(intent, entities)
            elif category == IntentCategory.ACTION:
                return await self._execute_action(intent, entities, user_id)
            elif category == IntentCategory.REPORT:
                return {
                    "message": "Report generation is coming in Sprint 4. For now, I can show you the data directly.",
                    "suggestions": ["Show revenue data", "Show occupancy data"],
                }
            else:
                return await self._handle_general(intent, entities)
        except Exception as e:
            logger.error(f"Intent execution error ({intent}): {e}", exc_info=True)
            return {"message": f"Error processing request: {str(e)}", "error": str(e)}

    # ─────────────────── Rich Query Formatters ───────────────────

    def _format_bookings(self, data: List[Dict], label: str = "booking") -> str:
        """Format bookings data into a rich message like the monolith."""
        count = len(data)
        if count == 0:
            return f"No {label}s found."
        message = f"You have **{count} {label}{'s' if count != 1 else ''}**.\n\n"
        for i, b in enumerate(data[:5], 1):
            guest = f"{b.get('first_name', '')} {b.get('last_name', '')}".strip() or "Unknown"
            room_type = b.get("room_type_name", "N/A")
            status = (b.get("status", "pending") or "pending").replace("_", " ").title()
            arr = b.get("arrival_date", "N/A")
            if isinstance(arr, str):
                try:
                    from datetime import date as _d
                    arr = _d.fromisoformat(arr).strftime("%b %d")
                except Exception:
                    pass
            message += f"{i}. **{guest}** - {room_type} ({status}) - {arr}\n"
        if count > 5:
            message += f"\n...and **{count - 5} more**."
        return message

    def _format_revenue(self, data: List[Dict]) -> str:
        """Format revenue data into a rich message."""
        d = data[0] if data else {}
        total = d.get("total_revenue", 0) or 0
        bookings = d.get("booking_count", 0) or 0
        avg = d.get("avg_booking_value", 0) or 0
        message = "**Revenue today:**\n\n"
        message += f"- Total Revenue: **${total:,.2f}**\n"
        message += f"- Bookings: **{bookings}**\n"
        message += f"- Average Booking: **${avg:,.2f}**"
        return message

    def _format_occupancy(self, data: List[Dict]) -> str:
        """Format occupancy data into a rich message."""
        d = data[0] if data else {}
        occupied = d.get("occupied_rooms", 0) or 0
        total = d.get("total_rooms", 0) or 0
        rate = d.get("occupancy_rate", 0) or 0
        available = total - occupied
        return (
            f"Your current occupancy is **{rate:.1f}%** with **{occupied}** rooms occupied "
            f"out of {total} total rooms. You have **{available}** rooms available."
        )

    def _format_staff(self, data: List[Dict]) -> str:
        """Format staff list into a rich message."""
        count = len(data)
        if count == 0:
            return "No staff records found."
        message = f"**{count} staff member{'s' if count != 1 else ''}:**\n\n"
        for i, s in enumerate(data[:8], 1):
            name = f"{s.get('first_name', '')} {s.get('last_name', '')}".strip() or "Unknown"
            role = (s.get("role", "staff") or "staff").replace("_", " ").title()
            dept = s.get("department", "")
            message += f"{i}. **{name}** - {role}"
            if dept:
                message += f" ({dept})"
            message += "\n"
        if count > 8:
            message += f"\n...and {count - 8} more."
        return message

    def _format_housekeeping(self, data: List[Dict]) -> str:
        """Format housekeeping tasks into a rich message."""
        count = len(data)
        if count == 0:
            return "No pending housekeeping tasks. All rooms are clean!"
        message = f"**{count} pending housekeeping task{'s' if count != 1 else ''}:**\n\n"
        for i, t in enumerate(data[:5], 1):
            room = t.get("room_number", t.get("room_id", "N/A"))
            task_type = (t.get("task_type", "cleaning") or "cleaning").replace("_", " ").title()
            priority = (t.get("priority", "medium") or "medium").title()
            message += f"{i}. Room **{room}** - {task_type} (Priority: {priority})\n"
        if count > 5:
            message += f"\n...and {count - 5} more."
        return message

    def _format_maintenance(self, data: List[Dict]) -> str:
        """Format maintenance requests into a rich message."""
        count = len(data)
        if count == 0:
            return "No open maintenance requests."
        message = f"**{count} open maintenance request{'s' if count != 1 else ''}:**\n\n"
        for i, m in enumerate(data[:5], 1):
            room = m.get("room_number", m.get("room_id", "N/A"))
            desc = m.get("description", m.get("title", "Maintenance issue"))
            priority = (m.get("priority", "medium") or "medium").title()
            message += f"{i}. Room **{room}** - {desc[:60]} (Priority: {priority})\n"
        if count > 5:
            message += f"\n...and {count - 5} more."
        return message

    def _format_vip_guests(self, data: List[Dict]) -> str:
        """Format VIP guests list."""
        count = len(data)
        if count == 0:
            return "No VIP guests found."
        message = f"**{count} VIP guest{'s' if count != 1 else ''}:**\n\n"
        for i, g in enumerate(data[:5], 1):
            name = f"{g.get('first_name', '')} {g.get('last_name', '')}".strip() or "Unknown"
            vip = g.get("vip_status", "VIP")
            email = g.get("email", "")
            message += f"{i}. **{name}** ({vip})"
            if email:
                message += f" - {email}"
            message += "\n"
        if count > 5:
            message += f"\n...and {count - 5} more."
        return message

    def _format_guests(self, data: List[Dict]) -> str:
        """Format guest list."""
        count = len(data)
        if count == 0:
            return "No guests found."
        message = f"You have **{count} guest{'s' if count != 1 else ''}** on record.\n\n"
        for i, g in enumerate(data[:5], 1):
            name = f"{g.get('first_name', '')} {g.get('last_name', '')}".strip() or "Unknown"
            email = g.get("email", "N/A")
            vip = g.get("vip_status", "")
            badge = f" ({vip})" if vip and vip != "0" and vip != "none" else ""
            message += f"{i}. **{name}**{badge} - {email}\n"
        if count > 5:
            message += f"\n...and **{count - 5} more** guests."
        return message

    def _format_rooms(self, data: List[Dict]) -> str:
        """Format room list."""
        count = len(data)
        if count == 0:
            return "No rooms found."
        message = f"**{count} room{'s' if count != 1 else ''}:**\n\n"
        for i, r in enumerate(data[:8], 1):
            num = r.get("number", "N/A")
            status = (r.get("status", "available") or "available").replace("_", " ").title()
            rtype = r.get("room_type_name", "")
            message += f"- Room **{num}** - {status}"
            if rtype:
                message += f" ({rtype})"
            message += "\n"
        if count > 8:
            message += f"\n...and {count - 8} more rooms."
        return message

    def _format_room_occupant(self, data: List[Dict], room_id: int) -> str:
        """Format room occupant info."""
        if not data:
            return f"Room **{room_id}** is currently vacant — no checked-in guest found."
        g = data[0]
        name = f"{g.get('first_name', '')} {g.get('last_name', '')}".strip() or "Unknown"
        booking_id = g.get("booking_id", "N/A")
        arr = g.get("arrival_date", "N/A")
        dep = g.get("departure_date", "N/A")
        return (
            f"Room **{room_id}** is occupied by **{name}**.\n\n"
            f"- Booking ID: {booking_id}\n"
            f"- Arrival: {arr}\n"
            f"- Departure: {dep}"
        )

    # ─────────────────── Query Execution ───────────────────

    async def _execute_query(self, intent: str, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a query intent using the existing SQLExecutor + QUERY_TEMPLATES.
        Returns richly formatted messages matching the monolith's per-intent handlers.
        """
        # Map intent names to QUERY_TEMPLATES keys (lowercase, matching sql_executor.py)
        template_map = {
            "query_bookings": "bookings_all",
            "query_bookings_today": "bookings_today",
            "query_checkouts_today": "checkouts_today",
            "query_vip_guests": "vip_guests",
            "query_revenue": "revenue_today",
            "query_occupancy": "occupancy_current",
            "query_staff": "staff_all",
            "query_housekeeping": "pending_housekeeping",
            "query_maintenance": "open_maintenance",
        }

        template_key = template_map.get(intent)

        # Handle intents without pre-built templates via inline SQL
        if not template_key or template_key not in QUERY_TEMPLATES:
            return await self._execute_inline_query(intent, entities)

        try:
            template = QUERY_TEMPLATES[template_key]
            query_sql = template["query"]
            params = template["params"]() if callable(template.get("params")) else {}

            # Override params with extracted entities
            if "target_date" in entities:
                params["today_start"] = entities["target_date"]
                params["today_end"] = entities["target_date"]
            if "room_id" in entities:
                params["room_number"] = str(entities["room_id"])

            result = await self._sql_executor.execute_raw(query_sql, params)

            if not result.success:
                return {"message": f"Error fetching data: {result.error}", "error": result.error}

            data = result.data
            count = len(data)

            # Rich per-intent formatting (matches monolith behavior)
            if intent == "query_bookings_today":
                message = self._format_bookings(data, "arrival today")
            elif intent == "query_checkouts_today":
                message = self._format_bookings(data, "checkout today")
            elif intent == "query_bookings":
                message = self._format_bookings(data, "booking")
            elif intent == "query_revenue":
                message = self._format_revenue(data)
            elif intent == "query_occupancy":
                message = self._format_occupancy(data)
            elif intent == "query_vip_guests":
                message = self._format_vip_guests(data)
            elif intent == "query_staff":
                message = self._format_staff(data)
            elif intent == "query_housekeeping":
                message = self._format_housekeeping(data)
            elif intent == "query_maintenance":
                message = self._format_maintenance(data)
            else:
                message = f"Found **{count}** results."

            return {
                "message": message,
                "query_results": data,
                "query_metadata": {"total_count": count, "query": template_key},
                "suggestions": self._generate_suggestions(intent),
            }
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            return {"message": f"Error querying data: {str(e)}", "error": str(e)}

    async def _execute_inline_query(self, intent: str, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Handle query intents that don't have pre-built QUERY_TEMPLATES."""
        try:
            if intent == "query_guests":
                result = await self._sql_executor.execute_raw(
                    "SELECT id, first_name, last_name, email, phone, vip_status, "
                    "loyalty_points, nationality FROM guests ORDER BY id DESC LIMIT 100", {}
                )
                if result.success:
                    return {
                        "message": self._format_guests(result.data),
                        "query_results": result.data,
                        "query_metadata": {"total_count": len(result.data)},
                        "suggestions": self._generate_suggestions(intent),
                    }

            elif intent == "query_rooms":
                result = await self._sql_executor.execute_raw(
                    "SELECT r.id, r.number, r.floor, r.status, rt.name as room_type_name, "
                    "rt.base_price FROM rooms r LEFT JOIN room_types rt ON r.room_type_id = rt.id "
                    "ORDER BY r.number", {}
                )
                if result.success:
                    return {
                        "message": self._format_rooms(result.data),
                        "query_results": result.data,
                        "query_metadata": {"total_count": len(result.data)},
                        "suggestions": self._generate_suggestions(intent),
                    }

            elif intent == "query_room_occupant":
                room_id = entities.get("room_id")
                if not room_id:
                    return {
                        "message": "Which room would you like to check? Please provide a room number.",
                        "query_results": [],
                    }
                result = await self._sql_executor.execute_raw(
                    "SELECT g.first_name, g.last_name, g.email, g.phone, g.vip_status, "
                    "b.id as booking_id, b.arrival_date, b.departure_date, b.status, "
                    "r.number as room_number "
                    "FROM bookings b "
                    "JOIN guests g ON b.guest_id = g.id "
                    "JOIN rooms r ON b.room_id = r.id "
                    "WHERE r.number = :room_number AND b.status = 'checked_in' "
                    "LIMIT 1",
                    {"room_number": str(room_id)}
                )
                if result.success:
                    return {
                        "message": self._format_room_occupant(result.data, room_id),
                        "query_results": result.data,
                        "query_metadata": {"total_count": len(result.data)},
                        "suggestions": self._generate_suggestions(intent),
                    }
            else:
                return {"message": f"I can look that up, but '{intent}' isn't configured yet.", "query_results": []}

            return {"message": result.message or "Query failed.", "error": result.error}
        except Exception as e:
            logger.error(f"Inline query error ({intent}): {e}")
            return {"message": f"Error: {str(e)}", "error": str(e)}

    # ─────────────────── Action Execution ───────────────────

    async def _execute_action(
        self,
        intent: str,
        entities: Dict[str, Any],
        user_id: int,
    ) -> Dict[str, Any]:
        """Execute an action intent — validates required params first,
        then creates a pending action with rich preview for confirmation.
        """
        # ── Check required parameters BEFORE creating pending action ──
        missing = self._check_missing_params(intent, entities)
        if missing:
            return missing

        # Map intent to ActionType
        action_type_map = {
            "create_task": ActionType.CREATE_TASK,
            "create_maintenance": ActionType.CREATE_MAINTENANCE,
            "create_booking": ActionType.CREATE_BOOKING,
            "create_guest_note": ActionType.CREATE_GUEST_NOTE,
            "update_booking": ActionType.UPDATE_BOOKING_STATUS,
            "update_room": ActionType.UPDATE_ROOM_STATUS,
            "update_guest": ActionType.UPDATE_GUEST,
            "assign_task": ActionType.ASSIGN_TASK,
            "assign_room": ActionType.ASSIGN_ROOM,
            "transfer_room": ActionType.TRANSFER_ROOM,
            "send_email": ActionType.SEND_EMAIL,
            "draft_email": ActionType.DRAFT_EMAIL,
        }

        action_type = action_type_map.get(intent)
        if not action_type:
            return {"message": f"Action '{intent}' is not yet supported."}

        try:
            action_request = ActionRequest(
                action_type=action_type,
                params=entities,
                requires_confirmation=True,
            )
            # prepare_action is sync
            pending = self._action_executor.prepare_action(action_request, user_id)

            # Build rich confirmation message per intent
            message = self._build_action_confirmation(intent, entities, pending)

            return {
                "message": message,
                "pending_action": {
                    "action_id": pending.action_id,
                    "action_type": action_type.value,
                    "description": pending.description,
                    "params": pending.params,
                },
            }
        except Exception as e:
            logger.error(f"Action preparation error: {e}")
            return {"message": f"Error preparing action: {str(e)}", "error": str(e)}

    def _check_missing_params(self, intent: str, entities: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check required parameters for an intent. Returns error dict if missing, None if OK."""
        if intent == "create_task":
            if "room_id" not in entities:
                return {
                    "message": (
                        "Please specify a room number for the housekeeping task.\n\n"
                        "For example: *Create housekeeping task for room 501*"
                    ),
                    "suggestions": ["Create task for room 501", "Create deep clean for room 302"],
                }

        elif intent == "create_maintenance":
            if "room_id" not in entities:
                return {
                    "message": (
                        "Please specify a room number and the issue.\n\n"
                        "For example: *Report AC issue in room 302*"
                    ),
                    "suggestions": ["AC not working room 302", "Leak in room 405"],
                }

        elif intent == "create_booking":
            missing = []
            if not entities.get("booking_guest_name") and not entities.get("guest_name"):
                missing.append("**Guest name**")
            if not entities.get("checkin_date") and not entities.get("target_date"):
                missing.append("**Check-in date**")
            if not entities.get("checkout_date"):
                missing.append("**Check-out date**")
            if missing:
                return {
                    "message": (
                        f"I'd be happy to create a booking! I still need:\n"
                        f"{', '.join(missing)}\n\n"
                        f"You can provide all details in one message like:\n"
                        f"**Book John Smith, check-in Dec 15, check-out Dec 18, Deluxe Suite**"
                    ),
                    "suggestions": ["Show room types", "Check availability"],
                }

        elif intent == "update_booking":
            if "booking_id" not in entities:
                return {
                    "message": (
                        "Which booking would you like to update?\n\n"
                        "Please provide a booking ID or guest name.\n"
                        "Example: *Check in booking 1234*"
                    ),
                    "suggestions": ["Show today's bookings", "Search by guest name"],
                }

        elif intent == "update_room":
            if "room_id" not in entities:
                return {
                    "message": "Which room should I update? Please provide a room number.",
                    "suggestions": ["Mark room 305 as clean", "Room 401 out of order"],
                }

        elif intent == "assign_task":
            if "task_id" not in entities:
                return {
                    "message": "Which task should I assign? Please provide a task ID.",
                    "suggestions": ["Show pending tasks", "Housekeeping tasks"],
                }

        elif intent == "create_guest_note":
            if "guest_id" not in entities and "guest_name" not in entities:
                return {
                    "message": "Which guest should I add the note to? Please provide a guest name or ID.",
                    "suggestions": ["Show all guests", "Search guest by name"],
                }

        return None

    def _build_action_confirmation(self, intent: str, entities: Dict[str, Any], pending) -> str:
        """Build a rich confirmation message for an action."""
        if intent == "create_task":
            room = entities.get("room_id", "N/A")
            task_type = (entities.get("task_type", "daily_cleaning") or "daily_cleaning").replace("_", " ").title()
            priority = (entities.get("priority", "medium") or "medium").title()
            return (
                f"I'll create a housekeeping task:\n\n"
                f"- **Room:** {room}\n"
                f"- **Type:** {task_type}\n"
                f"- **Priority:** {priority}\n\n"
                f"Should I proceed?"
            )

        elif intent == "create_maintenance":
            room = entities.get("room_id", "N/A")
            desc = entities.get("description", entities.get("note_text", "Maintenance issue"))
            priority = (entities.get("priority", "medium") or "medium").title()
            return (
                f"I'll create a maintenance request:\n\n"
                f"- **Room:** {room}\n"
                f"- **Issue:** {desc}\n"
                f"- **Priority:** {priority}\n\n"
                f"Should I proceed?"
            )

        elif intent == "create_booking":
            guest = entities.get("booking_guest_name") or entities.get("guest_name", "N/A")
            checkin = entities.get("checkin_date") or entities.get("target_date", "N/A")
            checkout = entities.get("checkout_date", "N/A")
            rt_raw = entities.get("room_type", "")

            # If no room type provided, ask for it
            if not rt_raw:
                return (
                    f"Please specify the room type for this booking.\n\n"
                    f"Example: *Book {guest}, Dec 15-18, Deluxe Room*\n\n"
                    f"You can ask me 'What room types are available?' to see options."
                )

            rt = rt_raw.replace("_", " ").title()

            # Calculate price estimate (room type validation happens in action_executor)
            price_info = ""
            try:
                from datetime import date as _d
                from sqlalchemy import text
                checkin_fmt = _d.fromisoformat(checkin).strftime("%B %d, %Y") if checkin != "N/A" else "N/A"
                checkout_fmt = _d.fromisoformat(checkout).strftime("%B %d, %Y") if checkout != "N/A" else "N/A"

                # Calculate nights and fetch room price (sync-compatible using run_sync)
                if checkin != "N/A" and checkout != "N/A":
                    ci = _d.fromisoformat(checkin)
                    co = _d.fromisoformat(checkout)
                    nights = (co - ci).days
                    if nights > 0:
                        # Note: Price shown here is an estimate. Actual price verified in action_executor
                        price_info = f"- **Nights:** {nights}\n"
            except (ValueError, TypeError) as e:
                logger.warning(f"Price calculation error: {e}")
                checkin_fmt, checkout_fmt = checkin, checkout

            return (
                f"I'll create this booking:\n\n"
                f"- **Guest:** {guest}\n"
                f"- **Check-in:** {checkin_fmt}\n"
                f"- **Check-out:** {checkout_fmt}\n"
                f"- **Room Type:** {rt}\n"
                f"{price_info}"
                f"Should I proceed?"
            )

        elif intent == "update_booking":
            booking_id = entities.get("booking_id", "N/A")
            status = entities.get("status", "updated")
            return f"I'll update booking **#{booking_id}** to **{status}**. Should I proceed?"

        elif intent == "update_room":
            room = entities.get("room_id", "N/A")
            status = (entities.get("status", "clean") or "clean").replace("_", " ").title()
            return f"I'll mark room **{room}** as **{status}**. Should I proceed?"

        # Default
        return f"{pending.description}\n\nShould I proceed?"

    async def _handle_confirmation(self, state: OrchestratorState) -> dict:
        """Handle user confirming a pending action."""
        session_ctx = state.get("session_context", {})
        pending_raw = session_ctx.get("pending_action") or session_ctx.get("pendingAction") or {}

        if not pending_raw or not pending_raw.get("action_id"):
            return {
                "response_message": "There's no pending action to confirm. What would you like me to do?",
                "response_intent": "general",
                "response_confidence": 1.0,
                "execution_results": [],
            }

        action_id = pending_raw["action_id"]
        user_id = state["user_id"]

        try:
            result = await self._action_executor.execute_confirmed(action_id, user_id)
            return {
                "response_message": f"Done! {result.message}",
                "response_intent": result.action_type.value if hasattr(result, 'action_type') else "action",
                "response_confidence": 1.0,
                "execution_results": [{
                    "message": result.message,
                    "action_result": {
                        "action_id": result.action_id,
                        "success": result.success,
                        "message": result.message,
                        "data": result.data,
                    },
                }],
            }
        except Exception as e:
            logger.error(f"Action execution error: {e}")
            return {
                "response_message": f"Failed to execute action: {str(e)}",
                "response_intent": "error",
                "response_confidence": 0.0,
                "response_error": str(e),
                "execution_results": [],
            }

    async def _handle_general(self, intent: str, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Handle general/help/unknown intents."""
        if intent == "help":
            return {
                "message": (
                    "I can help you with:\n\n"
                    "**Queries:** Bookings, guests, rooms, revenue, occupancy, staff, tasks\n"
                    "**Actions:** Create tasks, maintenance requests, check in/out, room assignments\n"
                    "**Communication:** Send emails, draft messages\n"
                    "**Reports:** Daily ops, revenue analysis, trend reports\n\n"
                    "Try asking something like 'Show today's bookings' or 'Clean room 305'."
                ),
                "suggestions": [
                    "Show today's bookings",
                    "What's the occupancy rate?",
                    "Pending maintenance requests",
                ],
            }
        return {
            "message": "I'm here to help with hotel operations. You can ask me about bookings, rooms, guests, or create tasks.",
            "suggestions": [
                "Show today's arrivals",
                "Revenue this month",
                "Pending housekeeping tasks",
            ],
        }

    def _generate_suggestions(self, intent: str) -> List[str]:
        """Generate contextual follow-up suggestions based on intent."""
        suggestion_map = {
            "query_bookings": ["Show VIP guests", "Today's checkouts", "Revenue summary"],
            "query_bookings_today": ["Show checkouts today", "Room availability", "VIP arrivals"],
            "query_checkouts_today": ["Today's bookings", "Revenue today", "Pending tasks"],
            "query_guests": ["Show VIP guests", "Guest count by room type", "Recent check-ins"],
            "query_vip_guests": ["All guests", "VIP arrivals today", "Loyalty stats"],
            "query_revenue": ["Occupancy rate", "Compare with last month", "Revenue by room type"],
            "query_occupancy": ["Available rooms", "Revenue", "Expected checkouts"],
            "query_rooms": ["Room occupancy", "Dirty rooms", "Out of order rooms"],
            "query_staff": ["Staff on shift", "Pending tasks", "Housekeeping staff"],
            "query_housekeeping": ["Assign tasks", "Room status", "Staff availability"],
            "query_maintenance": ["Create maintenance request", "Staff on duty", "Room status"],
            "create_task": ["Show pending tasks", "Room status", "Staff on shift"],
            "create_maintenance": ["Pending maintenance", "Room status", "Staff availability"],
        }
        return suggestion_map.get(intent, ["Show today's bookings", "Revenue summary", "Pending tasks"])

    # ─────────────────────── Audit & Logging ───────────────────────

    async def _log_messages(self, state: OrchestratorState):
        """Log user and assistant messages to DB."""
        try:
            from sqlalchemy import text as sql_text

            session_id = state["session_id"]
            user_message = state["user_message"]
            response_message = state.get("response_message", "")
            intent = state.get("response_intent", "general")
            has_results = bool(state.get("response_query_results"))
            has_pending = bool(state.get("pending_action"))
            pending_id = state.get("pending_action", {}).get("action_id")

            # Log user message
            await self.session.execute(sql_text(
                "INSERT INTO admin_ai_messages "
                "(session_id, role, content, intent, has_query_results, has_pending_action, action_id, created_at) "
                "VALUES (:sid, 'user', :content, :intent, 0, 0, NULL, datetime('now'))"
            ), {"sid": session_id, "content": user_message, "intent": intent})

            # Log assistant message
            await self.session.execute(sql_text(
                "INSERT INTO admin_ai_messages "
                "(session_id, role, content, intent, has_query_results, has_pending_action, action_id, created_at) "
                "VALUES (:sid, 'assistant', :content, :intent, :has_results, :has_pending, :action_id, datetime('now'))"
            ), {
                "sid": session_id,
                "content": response_message,
                "intent": intent,
                "has_results": 1 if has_results else 0,
                "has_pending": 1 if has_pending else 0,
                "action_id": pending_id,
            })

            await self.session.commit()
        except Exception as e:
            logger.error(f"Message logging failed: {e}")

    async def _log_audit(self, state: OrchestratorState) -> Optional[int]:
        """Log audit entry."""
        try:
            from sqlalchemy import text as sql_text

            execution_time = int((time.time() - state.get("request_start_time", time.time())) * 1000)
            security_blocked = not state.get("security_passed", True)

            await self.session.execute(sql_text(
                "INSERT INTO admin_ai_audit "
                "(session_id, user_id, action_type, input_message, detected_intent, confidence, "
                "success, error_message, response_message, execution_time_ms, "
                "injection_detected, blocked, block_reason, created_at) "
                "VALUES (:sid, :uid, :action_type, :input, :intent, :confidence, "
                ":success, :error, :response, :exec_time, "
                ":injection, :blocked, :block_reason, datetime('now'))"
            ), {
                "sid": state["session_id"],
                "uid": state["user_id"],
                "action_type": "query" if state.get("response_intent", "").startswith("query") else "action",
                "input": state["user_message"],
                "intent": state.get("response_intent", "unknown"),
                "confidence": state.get("response_confidence", 0.0),
                "success": not bool(state.get("response_error")),
                "error": state.get("response_error"),
                "response": state.get("response_message", "")[:500],
                "exec_time": execution_time,
                "injection": security_blocked,
                "blocked": security_blocked,
                "block_reason": state.get("security_block_reason"),
            })

            await self.session.commit()

            # Get the inserted ID
            result = await self.session.execute(sql_text(
                "SELECT last_insert_rowid()"
            ))
            row = result.fetchone()
            return row[0] if row else None

        except Exception as e:
            logger.error(f"Audit logging failed: {e}")
            return None

    # ─────────────────────── Public API ───────────────────────

    async def process_message(
        self,
        message: str,
        user_id: int,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> OrchestratorResponse:
        """Process a user message through the multi-agent pipeline.

        Primary path: LLM agent with tool calling (no regex, no manual routing).
        Fallback: Legacy StateGraph pipeline (regex + raw SQL).
        """
        start_time = time.time()

        # ── Primary path: LLM Agent ──────────────────────────────
        try:
            from app.services.admin_ai.llm_agent import AdminAILLMAgent
            llm_agent = AdminAILLMAgent(self.session)
            if llm_agent._llm:  # LLM is available
                result = await llm_agent.process_message(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                    context=context,
                )
                return OrchestratorResponse(
                    message=result.get("message", ""),
                    intent=result.get("intent", "general"),
                    confidence=result.get("confidence", 0.95),
                    session_id=session_id,
                    query_results=result.get("query_results"),
                    query_metadata=result.get("query_metadata"),
                    pending_action=result.get("pending_action"),
                    suggestions=result.get("suggestions", []),
                    error=result.get("error"),
                )
        except Exception as e:
            logger.warning(f"LLM agent failed, falling back to legacy pipeline: {e}")

        # ── Fallback: Legacy StateGraph pipeline ─────────────────
        start_time = time.time()

        # Build initial state
        initial_state: OrchestratorState = {
            "messages": [HumanMessage(content=message)],
            "user_message": message,
            "user_id": user_id,
            "session_id": session_id,
            "request_start_time": start_time,
            "session_context": context or {},
            "security_passed": True,
            "security_block_reason": "",
            "comprehension": {},
            "parameters": [],
            "execution_results": [],
            "pending_action": {},
            "active_entities": {},
            "context_summary": "",
            "response_message": "",
            "response_intent": "general",
            "response_confidence": 0.0,
            "response_suggestions": [],
            "response_query_results": [],
            "response_query_metadata": {},
            "response_error": "",
            "audit_id": 0,
        }

        try:
            # Run the graph
            final_state = await self._graph.ainvoke(initial_state)

            # Build response
            comp_raw = final_state.get("comprehension", {})
            intents_detected = None
            if comp_raw and comp_raw.get("intents"):
                intents_detected = [i["intent"] for i in comp_raw["intents"]]

            return OrchestratorResponse(
                message=final_state.get("response_message", "I'm here to help!"),
                intent=final_state.get("response_intent", "general"),
                confidence=final_state.get("response_confidence", 0.0),
                session_id=session_id,
                query_results=final_state.get("response_query_results") or None,
                query_metadata=final_state.get("response_query_metadata") or None,
                pending_action=final_state.get("pending_action") or None,
                suggestions=final_state.get("response_suggestions", []),
                audit_id=final_state.get("audit_id"),
                error=final_state.get("response_error") or None,
                intents_detected=intents_detected,
                context_entities=final_state.get("active_entities"),
            )

        except Exception as e:
            logger.error(f"Orchestrator error: {e}", exc_info=True)
            execution_time = int((time.time() - start_time) * 1000)

            return OrchestratorResponse(
                message="I encountered an error processing your request. Please try again.",
                intent="error",
                confidence=0.0,
                session_id=session_id,
                error=str(e),
            )


# ─────────────────────── Factory ───────────────────────

_orchestrator_instance: Optional[AdminAIOrchestrator] = None


def get_orchestrator(session: AsyncSession) -> AdminAIOrchestrator:
    """Get or create the orchestrator instance.

    Note: Creates a new instance per session since the session is request-scoped.
    The agents inside (ComprehensionAgent, ContextAgent) are lightweight and
    share LLM connections.
    """
    return AdminAIOrchestrator(session)
