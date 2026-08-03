"""
Guest Assistant Chatbot API endpoints
Unified chatbot for guest assistance with intelligent staff scheduling
Separate from AGI guest_ai which handles booking creation
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.db.session import get_tenant_session
from app.models.user import User
from app.models.guest_chat import GuestChatSession, GuestChatConversation, StaffTask
from app.api.v1.auth import get_current_user
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from app.core.config import settings
from sqlmodel import select
import logging

from app.services.unified_guest_chatbot import get_chatbot_service, UnifiedGuestChatbot

security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
router = APIRouter()


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_tenant_session)
) -> Optional[User]:
    """Get current user if authenticated, otherwise return None"""
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=["HS256"])
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            return None
        result = await session.exec(select(User).where(User.id == int(user_id)))
        user = result.first()
        return user
    except (JWTError, ValueError):
        return None


# ============== Request/Response Models ==============

class ChatMessageRequest(BaseModel):
    """Request model for chat messages"""
    message: str = Field(..., min_length=1, max_length=2000, description="Guest message")
    session_id: Optional[str] = Field(None, description="Chat session ID")
    room_number: Optional[str] = Field(None, description="Guest's room number")
    booking_number: Optional[str] = Field(None, description="Booking confirmation number")


class QuickAction(BaseModel):
    """Quick action button for chat responses"""
    label: str
    action: str


class FlowStateInfo(BaseModel):
    """Flow state information for multi-step conversations"""
    flow_type: Optional[str] = None
    current_step: int = 0
    total_steps: int = 0
    step_label: str = "Ready"
    progress: int = 0
    can_go_back: bool = False
    can_cancel: bool = True


class ChatMessageResponse(BaseModel):
    """Response model for chat messages"""
    response: str
    intent: str
    confidence: float
    requires_staff_action: bool = False
    session_id: str
    faq_id: Optional[str] = None
    staff_task_id: Optional[int] = None
    task_type: Optional[str] = None
    assigned_staff_name: Optional[str] = None
    estimated_response_time: Optional[int] = None
    # Enhanced task details
    task_priority: Optional[str] = None
    task_title: Optional[str] = None
    task_description: Optional[str] = None
    task_category: Optional[str] = None
    detected_issue: Optional[str] = None
    required_skills: Optional[List[str]] = None
    assigned_staff_role: Optional[str] = None
    booking_info: Optional[Dict[str, Any]] = None
    quick_actions: Optional[List[QuickAction]] = None
    needs_booking: Optional[bool] = None
    # New comprehensive AGI fields
    room_search_results: Optional[List[Dict[str, Any]]] = None
    profile_info: Optional[Dict[str, Any]] = None
    bookings_list: Optional[List[Dict[str, Any]]] = None
    precheckin_info: Optional[Dict[str, Any]] = None
    flow_state: Optional[FlowStateInfo] = None
    requires_auth: bool = False
    auth_error: Optional[str] = None
    action_result: Optional[Dict[str, Any]] = None


class BookingLookupRequest(BaseModel):
    """Request model for booking lookup"""
    booking_number: str = Field(..., min_length=4, max_length=20, description="Booking confirmation code")


class BookingLookupResponse(BaseModel):
    """Response model for booking lookup"""
    found: bool
    booking_info: Optional[Dict[str, Any]] = None
    message: str


class ConversationHistoryItem(BaseModel):
    """Individual conversation entry"""
    id: int
    conversation_id: str
    user_query: str
    bot_response: str
    classification: str
    room_number: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationHistoryResponse(BaseModel):
    """Response model for conversation history"""
    conversations: List[ConversationHistoryItem]
    total: int


class TaskStatusResponse(BaseModel):
    """Response model for task status"""
    id: int
    task_type: str
    title: str
    description: str
    status: str
    priority: str
    room_number: Optional[str] = None
    assigned_to: Optional[int] = None
    assigned_staff_name: Optional[str] = None
    scheduled_for: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    estimated_duration: Optional[int] = None
    created_at: str


# ============== API Endpoints ==============

@router.post("/chat", response_model=ChatMessageResponse)
async def chat_with_assistant(
    payload: ChatMessageRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Chat with the guest assistant chatbot

    Features:
    - FAQ handling with semantic search
    - Service request routing (housekeeping, maintenance, etc.)
    - Intelligent staff scheduling
    - Booking verification
    - Complaint escalation
    """
    try:
        # Generate or use provided session_id
        session_id = payload.session_id or f"session_{current_user.id if current_user else 'guest'}_{int(datetime.utcnow().timestamp() * 1000)}"

        # Get user/guest info
        user_id = current_user.id if current_user else None
        guest_id = None

        # Try to find guest_id from user if authenticated
        if current_user:
            from app.models.reservations import Guest
            guest_result = await session.exec(
                select(Guest).where(Guest.user_id == current_user.id)
            )
            guest = guest_result.first()
            if guest:
                guest_id = guest.id

        # Initialize chatbot service with current user for authorization
        chatbot = get_chatbot_service(session, current_user)

        # Process message
        chat_response = await chatbot.process_message(
            message=payload.message,
            session_id=session_id,
            user_id=user_id,
            guest_id=guest_id,
            room_number=payload.room_number,
            booking_number=payload.booking_number
        )

        logger.info(
            f"Chat processed - Intent: {chat_response.intent}, "
            f"Confidence: {chat_response.confidence:.2f}, "
            f"StaffAction: {chat_response.requires_staff_action}"
        )

        # Build flow state info if present
        flow_state_info = None
        if chat_response.flow_state:
            flow_state_info = FlowStateInfo(
                flow_type=chat_response.flow_state.get("flow_type"),
                current_step=chat_response.flow_state.get("current_step", 0),
                total_steps=chat_response.flow_state.get("total_steps", 0),
                step_label=chat_response.flow_state.get("step_label", "Ready"),
                progress=chat_response.flow_state.get("progress", 0),
                can_go_back=chat_response.flow_state.get("can_go_back", False),
                can_cancel=chat_response.flow_state.get("can_cancel", True)
            )

        # Build response
        return ChatMessageResponse(
            response=chat_response.response,
            intent=chat_response.intent,
            confidence=chat_response.confidence,
            requires_staff_action=chat_response.requires_staff_action,
            session_id=session_id,
            faq_id=chat_response.faq_id,
            staff_task_id=chat_response.staff_task_id,
            task_type=chat_response.task_type,
            assigned_staff_name=chat_response.assigned_staff_name,
            estimated_response_time=chat_response.estimated_response_time,
            # Enhanced task details
            task_priority=chat_response.task_priority,
            task_title=chat_response.task_title,
            task_description=chat_response.task_description,
            task_category=chat_response.task_category,
            detected_issue=chat_response.detected_issue,
            required_skills=chat_response.required_skills,
            assigned_staff_role=chat_response.assigned_staff_role,
            booking_info=chat_response.booking_info,
            quick_actions=[
                QuickAction(label=qa["label"], action=qa["action"])
                for qa in (chat_response.quick_actions or [])
            ] if chat_response.quick_actions else None,
            needs_booking=not chat_response.booking_info and chat_response.intent in ["housekeeping", "maintenance", "room_service"],
            # New comprehensive AGI fields
            room_search_results=chat_response.room_search_results,
            profile_info=chat_response.profile_info,
            bookings_list=chat_response.bookings_list,
            precheckin_info=chat_response.precheckin_info,
            flow_state=flow_state_info,
            requires_auth=chat_response.requires_auth,
            auth_error=chat_response.auth_error,
            action_result=chat_response.action_result
        )

    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        return ChatMessageResponse(
            response="I apologize, but I'm experiencing technical difficulties. Please try again or contact our front desk for immediate assistance.",
            intent="error",
            confidence=0.0,
            requires_staff_action=False,
            session_id=payload.session_id or f"session_error_{int(datetime.utcnow().timestamp() * 1000)}"
        )


@router.post("/lookup-booking", response_model=BookingLookupResponse)
async def lookup_booking(
    payload: BookingLookupRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Look up booking by confirmation number

    Used when guest needs to verify their booking for service requests
    """
    try:
        chatbot = get_chatbot_service(session, current_user)
        booking_info = await chatbot.lookup_booking(payload.booking_number)

        if booking_info:
            return BookingLookupResponse(
                found=True,
                booking_info=booking_info,
                message=f"Booking found! Room {booking_info.get('room_number', 'not assigned')} - Status: {booking_info.get('status', 'unknown')}"
            )
        else:
            return BookingLookupResponse(
                found=False,
                booking_info=None,
                message="We couldn't find a booking with that confirmation number. Please check the number and try again, or contact the front desk for assistance."
            )

    except Exception as e:
        logger.error(f"Error in booking lookup: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error looking up booking"
        )


@router.get("/history/{session_id}", response_model=ConversationHistoryResponse)
async def get_conversation_history(
    session_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Get conversation history for a session"""
    try:
        # Verify session exists
        result = await session.exec(
            select(GuestChatSession).where(GuestChatSession.session_id == session_id)
        )
        chat_session = result.first()

        if not chat_session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Verify access (user owns the session or is admin)
        if current_user:
            if chat_session.user_id and chat_session.user_id != current_user.id:
                if current_user.role not in ["admin", "superuser"]:
                    raise HTTPException(status_code=403, detail="Access denied")

        # Get conversations
        result = await session.exec(
            select(GuestChatConversation)
            .where(GuestChatConversation.session_id == session_id)
            .order_by(GuestChatConversation.created_at.desc())
            .limit(limit)
        )
        conversations = result.all()

        return ConversationHistoryResponse(
            conversations=[
                ConversationHistoryItem(
                    id=conv.id,
                    conversation_id=conv.conversation_id,
                    user_query=conv.user_query,
                    bot_response=conv.bot_response,
                    classification=conv.classification,
                    room_number=conv.room_number,
                    created_at=conv.created_at
                )
                for conv in conversations
            ],
            total=len(conversations)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving history: {str(e)}"
        )


@router.get("/sessions", response_model=List[dict])
async def get_user_sessions(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all chat sessions for current user"""
    try:
        result = await session.exec(
            select(GuestChatSession)
            .where(GuestChatSession.user_id == current_user.id)
            .order_by(GuestChatSession.last_activity.desc())
            .limit(20)
        )
        sessions = result.all()

        return [
            {
                "session_id": s.session_id,
                "room_number": s.room_number,
                "status": s.status,
                "created_at": s.created_at.isoformat(),
                "last_activity": s.last_activity.isoformat()
            }
            for s in sessions
        ]

    except Exception as e:
        logger.error(f"Error getting user sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving sessions: {str(e)}"
        )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Get detailed status of a staff task"""
    try:
        result = await session.exec(
            select(StaffTask).where(StaffTask.id == task_id)
        )
        task = result.first()

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Get assigned staff name if available
        assigned_staff_name = None
        if task.assigned_to:
            staff_result = await session.exec(
                select(User).where(User.id == task.assigned_to)
            )
            staff = staff_result.first()
            if staff:
                assigned_staff_name = staff.full_name or f"{staff.first_name} {staff.last_name}" if hasattr(staff, 'first_name') else staff.email

        # Verify access
        if current_user:
            is_assigned_staff = task.assigned_to == current_user.id
            is_guest = task.guest_id and hasattr(current_user, 'guest_id') and current_user.guest_id == task.guest_id
            is_admin = current_user.role in ["admin", "superuser", "front_desk", "operations"]

            if not (is_assigned_staff or is_guest or is_admin):
                raise HTTPException(status_code=403, detail="Access denied")

        return TaskStatusResponse(
            id=task.id,
            task_type=task.task_type,
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            room_number=task.room_number,
            assigned_to=task.assigned_to,
            assigned_staff_name=assigned_staff_name,
            scheduled_for=task.scheduled_for.isoformat() if task.scheduled_for else None,
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            estimated_duration=task.estimated_duration,
            created_at=task.created_at.isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving task: {str(e)}"
        )


@router.patch("/tasks/{task_id}/status")
async def update_task_status(
    task_id: int,
    new_status: str,
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update task status (for staff use)

    Valid statuses: pending, assigned, in_progress, completed, cancelled
    """
    valid_statuses = ["pending", "assigned", "in_progress", "completed", "cancelled"]
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )

    try:
        result = await session.exec(
            select(StaffTask).where(StaffTask.id == task_id)
        )
        task = result.first()

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Verify user is assigned or is admin
        if task.assigned_to != current_user.id and current_user.role not in ["admin", "superuser"]:
            raise HTTPException(status_code=403, detail="Only assigned staff can update this task")

        # Update status
        old_status = task.status
        task.status = new_status
        task.updated_at = datetime.utcnow()

        if notes:
            task.notes = (task.notes or "") + f"\n[{datetime.utcnow().isoformat()}] {notes}"

        # Set timestamps based on status
        if new_status == "in_progress" and not task.started_at:
            task.started_at = datetime.utcnow()
        elif new_status == "completed":
            task.completed_at = datetime.utcnow()
            if task.started_at:
                # Calculate actual duration in minutes
                duration = (task.completed_at - task.started_at).total_seconds() / 60
                task.actual_duration = int(duration)

        await session.commit()

        logger.info(f"Task {task_id} status updated from {old_status} to {new_status} by user {current_user.id}")

        return {
            "success": True,
            "task_id": task_id,
            "old_status": old_status,
            "new_status": new_status,
            "updated_at": task.updated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating task status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating task: {str(e)}"
        )


@router.get("/pending-tasks")
async def get_pending_tasks(
    department: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get pending/assigned tasks (for staff dashboard)

    Only accessible by staff members
    """
    if current_user.role not in ["admin", "superuser", "front_desk", "operations", "housekeeping", "maintenance"]:
        raise HTTPException(status_code=403, detail="Staff access required")

    try:
        from sqlalchemy import and_

        # Build query
        query = select(StaffTask).where(
            StaffTask.status.in_(["pending", "assigned"])
        )

        if priority:
            query = query.where(StaffTask.priority == priority)

        # Filter by department if specified and user is not admin
        if department and current_user.role not in ["admin", "superuser"]:
            query = query.where(StaffTask.task_type == department)

        query = query.order_by(
            StaffTask.priority.desc(),  # urgent first
            StaffTask.created_at.asc()  # oldest first
        ).limit(limit)

        result = await session.exec(query)
        tasks = result.all()

        return [
            {
                "id": t.id,
                "task_type": t.task_type,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "room_number": t.room_number,
                "assigned_to": t.assigned_to,
                "scheduled_for": t.scheduled_for.isoformat() if t.scheduled_for else None,
                "created_at": t.created_at.isoformat()
            }
            for t in tasks
        ]

    except Exception as e:
        logger.error(f"Error getting pending tasks: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving tasks: {str(e)}"
        )
