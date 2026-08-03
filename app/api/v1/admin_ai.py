"""
Admin AI API Endpoints
Provides AI-powered administration capabilities via LLM function calling.

The LLM agent handles all intent detection, entity extraction, and tool
orchestration — no regex, no manual routing, no separate orchestrator.
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text

from app.db.session import get_tenant_session
from app.models.user import User
from app.api.v1.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Request/Response Models ==============

class AdminAIChatRequest(BaseModel):
    """Request model for admin AI chat"""
    message: str = Field(..., min_length=1, max_length=4000, description="Admin message")
    session_id: Optional[str] = Field(None, description="Chat session ID")
    context: Optional[Dict[str, Any]] = Field(None, description="Enriched context (page, selection, filters, previous messages)")


class AdminAIExecuteRequest(BaseModel):
    """Request model for executing a confirmed action"""
    action_id: str = Field(..., description="ID of the pending action to execute")


class QueryResultItem(BaseModel):
    """A single query result item"""
    data: Dict[str, Any]


class PendingActionModel(BaseModel):
    """A pending action awaiting confirmation"""
    action_id: str
    action_type: str
    description: str
    params: Dict[str, Any]


class ActionResultModel(BaseModel):
    """Result of an executed action"""
    action_id: str
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class ChartData(BaseModel):
    """Chart.js-compatible chart data for frontend rendering"""
    chart_type: str  # line, bar, pie, doughnut
    title: str
    labels: List[str]
    datasets: List[Dict[str, Any]]


class AdminAIChatResponse(BaseModel):
    """Response model for admin AI chat"""
    message: str
    intent: str
    confidence: float
    session_id: str
    query_results: Optional[List[Dict[str, Any]]] = None
    query_metadata: Optional[Dict[str, Any]] = None
    pending_action: Optional[PendingActionModel] = None
    action_result: Optional[ActionResultModel] = None
    suggestions: Optional[List[str]] = None
    audit_id: Optional[int] = None
    error: Optional[str] = None
    chart_data: Optional[ChartData] = None  # Chart visualization data
    # Multi-agent architecture fields
    intents_detected: Optional[List[str]] = None
    auto_filled_params: Optional[List[str]] = None
    context_entities: Optional[Dict[str, Any]] = None


class AuditLogEntry(BaseModel):
    """Audit log entry"""
    id: int
    session_id: str
    user_id: int
    action_type: str
    input_message: str
    detected_intent: str
    confidence: float
    success: bool
    error_message: Optional[str] = None
    execution_time_ms: int
    injection_detected: bool
    blocked: bool
    created_at: str


class AuditLogResponse(BaseModel):
    """Response for audit log query"""
    entries: List[AuditLogEntry]
    total_count: int
    page: int
    page_size: int


class CapabilitiesResponse(BaseModel):
    """Response for capabilities query"""
    version: str
    capabilities: List[Dict[str, Any]]
    intents: List[str]


# ============== Helper Functions ==============

def require_admin(current_user: User) -> User:
    """Verify the user has admin access"""
    admin_roles = ["admin", "manager", "owner"]
    if current_user.role not in admin_roles and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def _get_llm_agent(session: AsyncSession):
    """Create the LLM-first admin AI agent."""
    from app.services.admin_ai.llm_agent import AdminAILLMAgent
    return AdminAILLMAgent(session)


# ============== API Endpoints ==============

@router.post("/chat", response_model=AdminAIChatResponse)
async def chat_with_admin_ai(
    payload: AdminAIChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Chat with the Admin AI assistant.

    Features:
    - Natural language understanding via LLM
    - Bookings, guests, rooms, revenue, occupancy queries
    - Create housekeeping and maintenance tasks
    - Update booking and room statuses
    - Payment status and revenue analytics
    - Multi-step conversation support
    """
    try:
        # Generate session ID if not provided
        session_id = payload.session_id or f"admin_ai_{current_user.id}_{int(datetime.utcnow().timestamp() * 1000)}"

        # Get LLM agent
        agent = _get_llm_agent(session)

        # Process message through the LLM agent
        response = await agent.process_message(
            message=payload.message,
            user_id=current_user.id,
            session_id=session_id,
            context=payload.context
        )

        logger.info(
            f"Admin AI Chat - User: {current_user.id}, Intent: {response.get('intent', 'unknown')}, "
            f"Confidence: {response.get('confidence', 0):.2f}"
        )

        # Build response from the LLM agent's dict
        result = AdminAIChatResponse(
            message=response.get("message", "I couldn't process that request."),
            intent=response.get("intent", "general"),
            confidence=response.get("confidence", 0.0),
            session_id=session_id,
            query_results=response.get("query_results"),
            query_metadata=response.get("query_metadata"),
            suggestions=response.get("suggestions"),
            audit_id=response.get("audit_id"),
            error=response.get("error"),
        )

        # Add chart data if present
        chart = response.get("chart_data")
        if chart and isinstance(chart, dict):
            try:
                result.chart_data = ChartData(**chart)
            except Exception:
                pass  # Skip malformed chart data

        # Add pending action if present
        pending = response.get("pending_action")
        if pending and isinstance(pending, dict):
            result.pending_action = PendingActionModel(
                action_id=pending.get("action_id", ""),
                action_type=pending.get("action_type", ""),
                description=pending.get("description", ""),
                params=pending.get("params", {}),
            )

        # Add action result if present
        action_res = response.get("action_result")
        if action_res and isinstance(action_res, dict):
            result.action_result = ActionResultModel(
                action_id=action_res.get("action_id", ""),
                success=action_res.get("success", False),
                message=action_res.get("message", ""),
                data=action_res.get("data"),
            )

        return result

    except Exception as e:
        logger.error(f"Error in admin AI chat: {e}", exc_info=True)
        return AdminAIChatResponse(
            message="I apologize, but I encountered an error. Please try again.",
            intent="error",
            confidence=0.0,
            session_id=payload.session_id or "error",
            error=str(e)
        )


@router.post("/execute", response_model=AdminAIChatResponse)
async def execute_admin_action(
    payload: AdminAIExecuteRequest,
    request: Request,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Execute a previously prepared action after user confirmation.

    With the LLM-first approach, confirmations are handled in the
    conversation flow. This endpoint provides backward compatibility
    by forwarding the confirmation to the LLM agent as a "yes, execute" message.
    """
    try:
        agent = _get_llm_agent(session)
        session_id = f"admin_ai_{current_user.id}"

        # Forward as a confirmation message to the LLM
        response = await agent.process_message(
            message=f"Yes, please execute the pending action (action_id: {payload.action_id})",
            user_id=current_user.id,
            session_id=session_id,
            context=None,
        )

        result = AdminAIChatResponse(
            message=response.get("message", "Action processed."),
            intent=response.get("intent", "general"),
            confidence=response.get("confidence", 0.0),
            session_id=session_id,
            error=response.get("error"),
        )

        action_res = response.get("action_result")
        if action_res and isinstance(action_res, dict):
            result.action_result = ActionResultModel(
                action_id=action_res.get("action_id", payload.action_id),
                success=action_res.get("success", False),
                message=action_res.get("message", response.get("message", "")),
                data=action_res.get("data"),
            )

        return result

    except Exception as e:
        logger.error(f"Error executing admin action: {e}", exc_info=True)
        return AdminAIChatResponse(
            message=f"Failed to execute action: {str(e)}",
            intent="error",
            confidence=0.0,
            session_id="error",
            error=str(e)
        )


@router.get("/history/{session_id}")
async def get_conversation_history(
    session_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get conversation history for a session"""
    try:
        query = text("""
            SELECT id, session_id, role, content, intent, has_query_results,
                   has_pending_action, action_id, created_at
            FROM admin_ai_messages
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            LIMIT :limit
        """)

        result = await session.execute(query, {
            "session_id": session_id,
            "limit": limit
        })

        messages = []
        for row in result.fetchall():
            messages.append({
                "id": row[0],
                "session_id": row[1],
                "role": row[2],
                "content": row[3],
                "intent": row[4],
                "has_query_results": row[5],
                "has_pending_action": row[6],
                "action_id": row[7],
                "created_at": row[8]
            })

        return {"messages": messages[::-1], "session_id": session_id}

    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return {"messages": [], "session_id": session_id, "error": str(e)}


@router.get("/audit", response_model=AuditLogResponse)
async def get_audit_log(
    page: int = 1,
    page_size: int = 50,
    user_id: Optional[int] = None,
    action_type: Optional[str] = None,
    success_only: bool = False,
    blocked_only: bool = False,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get audit log of AI operations.

    Only accessible by admin users. Shows all AI operations including:
    - Queries executed
    - Actions taken
    - Blocked requests
    - Errors
    """
    require_admin(current_user)

    # Only superusers can view all users' audit logs
    if user_id and user_id != current_user.id and not current_user.is_superuser:
        user_id = current_user.id

    try:
        # Build query
        conditions = []
        params = {
            "limit": page_size,
            "offset": (page - 1) * page_size
        }

        if user_id:
            conditions.append("user_id = :user_id")
            params["user_id"] = user_id

        if action_type:
            conditions.append("action_type = :action_type")
            params["action_type"] = action_type

        if success_only:
            conditions.append("success = true")

        if blocked_only:
            conditions.append("blocked = true")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Get total count
        count_query = text(f"SELECT COUNT(*) FROM admin_ai_audit {where_clause}")
        count_result = await session.execute(count_query, params)
        total_count = count_result.scalar() or 0

        # Get entries
        query = text(f"""
            SELECT id, session_id, user_id, action_type, input_message,
                   detected_intent, confidence, success, error_message,
                   execution_time_ms, injection_detected, blocked, created_at
            FROM admin_ai_audit
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)

        result = await session.execute(query, params)

        entries = []
        for row in result.fetchall():
            entries.append(AuditLogEntry(
                id=row[0],
                session_id=row[1],
                user_id=row[2],
                action_type=row[3],
                input_message=row[4][:200] + "..." if len(row[4]) > 200 else row[4],
                detected_intent=row[5],
                confidence=row[6] or 0.0,
                success=row[7],
                error_message=row[8],
                execution_time_ms=row[9] or 0,
                injection_detected=row[10] or False,
                blocked=row[11] or False,
                created_at=str(row[12])
            ))

        return AuditLogResponse(
            entries=entries,
            total_count=total_count,
            page=page,
            page_size=page_size
        )

    except Exception as e:
        logger.error(f"Error fetching audit log: {e}", exc_info=True)
        return AuditLogResponse(
            entries=[],
            total_count=0,
            page=page,
            page_size=page_size
        )


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(
    current_user: User = Depends(get_current_user)
):
    """Get list of Admin AI capabilities and supported intents"""
    return CapabilitiesResponse(
        version="2.0",
        capabilities=[
            {
                "category": "Queries",
                "items": [
                    {"name": "Bookings", "examples": ["How many bookings today?", "Show arrivals tomorrow", "Find booking GLM-XXXXXX"]},
                    {"name": "Guests", "examples": ["Show VIP guests", "How many guests?", "Search guest Ishan"]},
                    {"name": "Revenue", "examples": ["Revenue today", "This month's revenue", "Future revenue forecast"]},
                    {"name": "Occupancy", "examples": ["Current occupancy rate", "Available rooms"]},
                    {"name": "Payments", "examples": ["Payment status for booking #199", "Show balance due"]},
                    {"name": "Tasks", "examples": ["Pending housekeeping tasks", "Open maintenance requests"]},
                    {"name": "Dashboard", "examples": ["Today's summary", "Give me an overview"]},
                ]
            },
            {
                "category": "Actions",
                "items": [
                    {"name": "Create Booking", "examples": ["Book a deluxe room for Ishan from Dec 15 to 18"]},
                    {"name": "Check In/Out", "examples": ["Check in booking #199", "Check out booking #200"]},
                    {"name": "Create Task", "examples": ["Create housekeeping task for room 501"]},
                    {"name": "Create Maintenance", "examples": ["Report AC issue in room 302"]},
                    {"name": "Update Room", "examples": ["Mark room 501 as clean"]},
                    {"name": "Update Guest", "examples": ["Make guest #15 VIP", "Add note to guest profile"]},
                ]
            },
            {
                "category": "Analytics",
                "items": [
                    {"name": "Revenue by Room Type", "examples": ["Which room type earns most?"]},
                    {"name": "Future Revenue", "examples": ["Projected revenue next 30 days"]},
                    {"name": "Occupancy Trends", "examples": ["Show occupancy for next week"]},
                ]
            }
        ],
        intents=[
            "search_bookings", "get_booking_details", "create_booking",
            "check_in_booking", "check_out_booking", "cancel_booking",
            "list_rooms", "check_room_availability", "update_room_status",
            "create_housekeeping_task", "get_housekeeping_tasks",
            "create_maintenance_request", "get_maintenance_requests",
            "search_guests", "update_guest",
            "get_payment_status", "query_revenue", "get_future_revenue",
            "get_revenue_by_room_type", "query_occupancy",
            "query_checkouts_today", "get_today_summary",
            "general", "help",
        ]
    )


@router.post("/feedback")
async def submit_feedback(
    session_id: str,
    rating: int,
    feedback: Optional[str] = None,
    message_id: Optional[int] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Submit feedback about an AI response"""
    try:
        logger.info(
            f"Admin AI Feedback - User: {current_user.id}, Session: {session_id}, "
            f"Rating: {rating}, Feedback: {feedback}"
        )

        return {
            "success": True,
            "message": "Thank you for your feedback!"
        }

    except Exception as e:
        logger.error(f"Error submitting feedback: {e}")
        return {"success": False, "message": "Failed to submit feedback"}
