"""
Context Agent for Admin AI Multi-Agent Architecture.
Manages sliding window memory, conversation summarization,
and active entity tracking for pronoun resolution.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.services.admin_ai.protocol import ActiveEntities, SessionContext
from app.services.admin_ai.prompts import CONTEXT_SUMMARIZER_PROMPT

logger = logging.getLogger(__name__)

# LangChain imports with fallback
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


class ContextAgent:
    """Memory manager for admin AI conversations.

    Responsibilities:
    - Sliding window: keep last N messages verbatim
    - When exceeding window, summarize oldest messages via LLM
    - Track active entities (last mentioned room, guest, booking)
      for pronoun resolution ("check them in", "clean it")
    - Merge session context from frontend (current page, selection)
    """

    WINDOW_SIZE = 10  # Keep last 10 messages verbatim
    SUMMARIZE_BATCH = 5  # When window exceeded, summarize oldest 5

    def __init__(self):
        self._llm: Optional[Any] = None
        self._init_llm()

    def _init_llm(self):
        """Initialize LLM for conversation summarization."""
        if not LLM_AVAILABLE:
            return

        try:
            from dotenv import dotenv_values
            from pathlib import Path

            env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
            env_vars = dotenv_values(str(env_path))
            api_key = env_vars.get("OPENAI_API_KEY") or settings.openai_api_key

            if not api_key:
                return

            model = env_vars.get("OPENAI_MODEL", settings.openai_model) or "gpt-4"
            self._llm = ChatOpenAI(
                model=model,
                temperature=0,
                api_key=api_key,
                max_tokens=200,
            )
        except Exception as e:
            logger.error(f"Failed to initialize context summarizer LLM: {e}")

    def build_context_summary(
        self,
        previous_messages: Optional[List[Dict[str, str]]] = None,
        existing_summary: str = "",
    ) -> str:
        """Build a context summary from previous messages.

        Uses a sliding window: if we have more than WINDOW_SIZE messages,
        the oldest SUMMARIZE_BATCH are compressed into a summary paragraph.
        The remaining recent messages are kept verbatim.

        For Sprint 1 (sync-only), we do simple text summarization without LLM.
        LLM summarization is added in Sprint 4.
        """
        if not previous_messages:
            return existing_summary

        # If within window, just format recent messages as context
        if len(previous_messages) <= self.WINDOW_SIZE:
            parts = []
            if existing_summary:
                parts.append(f"Earlier: {existing_summary}")
            for msg in previous_messages[-5:]:  # Use last 5 for context
                role = msg.get("role", "user")
                content = msg.get("content", "")[:150]
                if content:
                    parts.append(f"{role}: {content}")
            return " | ".join(parts) if parts else ""

        # Window exceeded — summarize oldest batch
        old_messages = previous_messages[:-self.WINDOW_SIZE]
        recent_messages = previous_messages[-self.WINDOW_SIZE:]

        # Simple text-based summary (no LLM call in sync path)
        old_summary = self._simple_summarize(old_messages)

        combined_summary = existing_summary
        if old_summary:
            combined_summary = f"{existing_summary} {old_summary}".strip() if existing_summary else old_summary

        # Format recent messages
        parts = []
        if combined_summary:
            parts.append(f"Earlier: {combined_summary}")
        for msg in recent_messages[-5:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:150]
            if content:
                parts.append(f"{role}: {content}")

        return " | ".join(parts) if parts else ""

    async def summarize_conversation(
        self,
        messages: List[Dict[str, str]],
    ) -> str:
        """LLM-powered conversation summarization (for Sprint 4).

        Summarizes a batch of messages into a brief paragraph.
        Falls back to simple summarization if LLM is unavailable.
        """
        if not messages:
            return ""

        if not self._llm:
            return self._simple_summarize(messages)

        try:
            formatted = "\n".join(
                f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                for msg in messages
            )
            response = await self._llm.ainvoke([
                SystemMessage(content=CONTEXT_SUMMARIZER_PROMPT),
                HumanMessage(content=formatted),
            ])
            return response.content.strip()
        except Exception as e:
            logger.error(f"LLM summarization failed: {e}")
            return self._simple_summarize(messages)

    def _simple_summarize(self, messages: List[Dict[str, str]]) -> str:
        """Simple text-based summarization (no LLM)."""
        if not messages:
            return ""

        # Extract key nouns/topics from messages
        topics = set()
        for msg in messages:
            content = msg.get("content", "").lower()
            for keyword in ["booking", "guest", "room", "revenue", "occupancy",
                            "housekeeping", "maintenance", "staff", "check-in",
                            "checkout", "task", "email", "report", "vip"]:
                if keyword in content:
                    topics.add(keyword)

        if topics:
            return f"Previously discussed: {', '.join(sorted(topics))}."
        return f"Previous conversation ({len(messages)} messages)."

    def update_active_entities(
        self,
        current: ActiveEntities,
        new_entities: Dict[str, Any],
    ) -> ActiveEntities:
        """Update active entities from newly extracted entities.

        New entities override old ones. Entities are used for pronoun resolution:
        "check them in" → uses last_guest_id/last_booking_id.
        """
        updated = current.model_copy()

        if "room_id" in new_entities:
            updated.last_room_id = new_entities["room_id"]
            updated.last_room_number = str(new_entities["room_id"])
        if "guest_id" in new_entities:
            updated.last_guest_id = new_entities["guest_id"]
        if "guest_name" in new_entities:
            updated.last_guest_name = new_entities["guest_name"]
        if "booking_id" in new_entities:
            updated.last_booking_id = new_entities["booking_id"]
        if "staff_id" in new_entities:
            updated.last_staff_id = new_entities["staff_id"]
        if "staff_name" in new_entities:
            updated.last_staff_name = new_entities["staff_name"]
        if "task_id" in new_entities:
            updated.last_task_id = new_entities["task_id"]

        return updated

    def resolve_pronouns(
        self,
        entities: Dict[str, Any],
        active: ActiveEntities,
        intent: str,
    ) -> Dict[str, Any]:
        """Resolve pronoun references using active entities.

        E.g., "check them in" with no booking_id → uses active.last_booking_id.
        """
        resolved = entities.copy()

        # Intent-specific pronoun resolution
        if intent in ("update_booking", "create_task", "assign_room"):
            if "room_id" not in resolved and active.last_room_id:
                resolved["room_id"] = active.last_room_id

        if intent in ("update_booking",):
            if "booking_id" not in resolved and active.last_booking_id:
                resolved["booking_id"] = active.last_booking_id

        if intent in ("update_guest", "create_guest_note"):
            if "guest_id" not in resolved and active.last_guest_id:
                resolved["guest_id"] = active.last_guest_id
            if "guest_name" not in resolved and active.last_guest_name:
                resolved["guest_name"] = active.last_guest_name

        if intent in ("assign_task",):
            if "task_id" not in resolved and active.last_task_id:
                resolved["task_id"] = active.last_task_id
            if "staff_name" not in resolved and active.last_staff_name:
                resolved["staff_name"] = active.last_staff_name

        return resolved

    def merge_session_context(
        self,
        entities: Dict[str, Any],
        session_ctx: SessionContext,
        intent: str,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Auto-fill parameters from session context (frontend page/selection).

        Returns (merged_entities, list_of_auto_filled_field_names).
        """
        merged = entities.copy()
        auto_filled: List[str] = []

        # Auto-fill from current page selection
        if "room_id" not in merged and session_ctx.selected_room_id:
            # Only auto-fill room if intent is room-related
            if intent in ("create_task", "update_room", "query_room_occupant",
                          "create_maintenance", "assign_room"):
                merged["room_id"] = session_ctx.selected_room_id
                auto_filled.append("room_id")

        if "booking_id" not in merged and session_ctx.selected_booking_id:
            if intent in ("update_booking", "assign_room"):
                merged["booking_id"] = session_ctx.selected_booking_id
                auto_filled.append("booking_id")

        if "guest_id" not in merged and session_ctx.selected_guest_id:
            if intent in ("update_guest", "create_guest_note", "query_room_occupant"):
                merged["guest_id"] = session_ctx.selected_guest_id
                auto_filled.append("guest_id")

        if "staff_id" not in merged and session_ctx.selected_staff_id:
            if intent in ("assign_task",):
                merged["staff_id"] = session_ctx.selected_staff_id
                auto_filled.append("staff_id")

        # Auto-fill date from business date
        if "target_date" not in merged and session_ctx.business_date:
            if intent in ("query_bookings", "query_revenue", "query_occupancy"):
                merged["target_date"] = session_ctx.business_date
                auto_filled.append("target_date")

        return merged, auto_filled
