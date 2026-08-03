"""
Guest AI Chat API Endpoints

This module provides the main chat API for the Guest AI Assistant.
Features:
- Authentication required (logged-in users only)
- Session persistence
- Conversation history
- Admin visibility endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Optional, List, Dict, Any
import logging

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user, get_current_active_superuser
from app.models.user import User
from app.services.guest_ai_orchestrator import create_guest_ai_orchestrator
from app.services.chat_session_manager import get_chat_session_manager
from app.config import get_hotel_config

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class ChatMessageRequest(BaseModel):
    """Request model for chat messages."""
    message: str = Field(..., min_length=1, max_length=2000, description="The user's message")
    session_id: Optional[str] = Field(None, description="Existing session ID to continue conversation")


class ChatActionData(BaseModel):
    """Action data for frontend UI rendering."""
    type: str = Field(..., description="Action type (e.g., show_room_selection, show_payment)")
    data: Dict[str, Any] = Field(default_factory=dict, description="Action-specific data")
    await_selection: Optional[bool] = Field(None, description="Whether to wait for user selection")
    await_completion: Optional[bool] = Field(None, description="Whether to wait for completion")


class ChatMessageResponse(BaseModel):
    """Response model for chat messages."""
    response: str = Field(..., description="The AI assistant's response")
    session_id: str = Field(..., description="The session ID for this conversation")
    conversation_id: str = Field(None, description="The conversation turn ID")
    intent: str = Field(None, description="Detected user intent")
    requires_staff_action: bool = Field(False, description="Whether this needs staff attention")
    action: Optional[ChatActionData] = Field(None, description="Optional action data for frontend UI rendering")
    error: Optional[str] = Field(None, description="Error message if any")


class SessionInfoResponse(BaseModel):
    """Response model for session info."""
    session_id: str
    status: str
    created_at: str
    last_activity: str
    conversation_count: int


class ConversationHistoryResponse(BaseModel):
    """Response model for conversation history."""
    session_id: str
    messages: List[Dict[str, Any]]


class AdminSessionsResponse(BaseModel):
    """Response model for admin sessions list."""
    sessions: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class AdminConversationResponse(BaseModel):
    """Response model for admin conversation view."""
    session: Dict[str, Any]


class HotelInfoResponse(BaseModel):
    """Response model for hotel configuration (public info)."""
    hotel_name: str
    ai_assistant_name: str
    greeting: str
    support_phone: str
    support_email: str


# ============================================================================
# Guest Chat Endpoints
# ============================================================================

@router.post("/chat", response_model=ChatMessageResponse)
async def chat_with_assistant(
    payload: ChatMessageRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)  # REQUIRED - must be logged in
):
    """
    Chat with the Guest AI Assistant.

    **Authentication Required**: User must be logged in.

    The assistant can help with:
    - Viewing and managing bookings
    - Pre-check-in process
    - Service requests (housekeeping, maintenance, etc.)
    - Hotel information and FAQs
    - Profile updates
    """
    try:
        # Verify user is authenticated
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Please log in to use the AI assistant."
            )

        logger.info(f"Chat request from user {current_user.id}: {payload.message[:50]}...")

        # Create orchestrator
        orchestrator = await create_guest_ai_orchestrator(db, current_user)

        # Process message
        result = await orchestrator.process_message(
            message=payload.message,
            session_id=payload.session_id
        )

        # Build response
        response_data = {
            "response": result.get("response", ""),
            "session_id": result.get("session_id", ""),
            "conversation_id": result.get("conversation_id"),
            "intent": result.get("intent"),
            "requires_staff_action": result.get("requires_staff_action", False),
            "error": result.get("error")
        }

        # Include action data if present
        if result.get("action"):
            response_data["action"] = ChatActionData(**result["action"])

        return ChatMessageResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing message: {str(e)}"
        )


@router.get("/session", response_model=SessionInfoResponse)
async def get_current_session(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get the current user's active chat session info.

    Returns session details if an active session exists.
    """
    try:
        session_manager = get_chat_session_manager(db)

        # Get or create session
        session, is_new = await session_manager.get_or_create_session(current_user.id)

        # Get conversation count
        history = await session_manager.get_conversation_history(session.session_id)
        conv_count = len(history) // 2  # Each turn has 2 messages

        await db.commit()

        return SessionInfoResponse(
            session_id=session.session_id,
            status=session.status,
            created_at=session.created_at.isoformat(),
            last_activity=session.last_activity.isoformat(),
            conversation_count=conv_count
        )

    except Exception as e:
        logger.error(f"Get session error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting session: {str(e)}"
        )


@router.get("/history", response_model=ConversationHistoryResponse)
async def get_conversation_history(
    session_id: Optional[str] = Query(None, description="Session ID to get history for"),
    limit: int = Query(20, ge=1, le=100, description="Maximum messages to return"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get conversation history for a session.

    If no session_id is provided, returns history for the user's active session.
    """
    try:
        session_manager = get_chat_session_manager(db)

        # Get session
        if session_id:
            session = await session_manager.get_session_by_id(session_id)
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Session not found"
                )
            # Verify ownership
            if session.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this session"
                )
        else:
            session, _ = await session_manager.get_or_create_session(current_user.id)

        # Get history
        history = await session_manager.get_conversation_history(session.session_id, limit)

        await db.commit()

        return ConversationHistoryResponse(
            session_id=session.session_id,
            messages=history
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get history error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting history: {str(e)}"
        )


@router.post("/session/close")
async def close_current_session(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Close the current user's active chat session.

    This ends the conversation context. A new session will be created
    on the next chat message.
    """
    try:
        session_manager = get_chat_session_manager(db)

        # Find active session
        session, _ = await session_manager.get_or_create_session(current_user.id)

        # Close it
        await session_manager.close_session(session.session_id)

        await db.commit()

        return {"message": "Session closed successfully", "session_id": session.session_id}

    except Exception as e:
        logger.error(f"Close session error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error closing session: {str(e)}"
        )


@router.get("/info", response_model=HotelInfoResponse)
async def get_hotel_info():
    """
    Get public hotel information for the chat interface.

    This endpoint is public and returns basic hotel info and AI assistant details.
    """
    try:
        config = get_hotel_config()

        return HotelInfoResponse(
            hotel_name=config.hotel.name,
            ai_assistant_name=config.ai_assistant.name,
            greeting=config.get_formatted_greeting(),
            support_phone=config.contact.phone.main,
            support_email=config.contact.email.support
        )

    except Exception as e:
        logger.error(f"Get hotel info error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting hotel info: {str(e)}"
        )


# ============================================================================
# Admin Endpoints
# ============================================================================

@router.get("/admin/sessions", response_model=AdminSessionsResponse)
async def admin_get_all_sessions(
    status: Optional[str] = Query(None, description="Filter by status (active, closed)"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_tenant_session),
    admin_user: User = Depends(get_current_active_superuser)
):
    """
    **Admin Only**: Get all chat sessions.

    Returns a paginated list of all chat sessions with user info.
    """
    try:
        session_manager = get_chat_session_manager(db)

        sessions, total = await session_manager.get_all_sessions(
            status=status,
            limit=limit,
            offset=offset
        )

        return AdminSessionsResponse(
            sessions=sessions,
            total=total,
            limit=limit,
            offset=offset
        )

    except Exception as e:
        logger.error(f"Admin get sessions error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting sessions: {str(e)}"
        )


@router.get("/admin/sessions/{session_id}", response_model=AdminConversationResponse)
async def admin_get_session_conversation(
    session_id: str,
    db: AsyncSession = Depends(get_tenant_session),
    admin_user: User = Depends(get_current_active_superuser)
):
    """
    **Admin Only**: Get full conversation for a session.

    Returns session info with all conversation turns.
    """
    try:
        session_manager = get_chat_session_manager(db)

        session_data = await session_manager.get_session_full_conversation(session_id)

        if not session_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )

        return AdminConversationResponse(session=session_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin get conversation error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting conversation: {str(e)}"
        )


@router.get("/admin/pending-actions")
async def admin_get_pending_actions(
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    db: AsyncSession = Depends(get_tenant_session),
    admin_user: User = Depends(get_current_active_superuser)
):
    """
    **Admin Only**: Get conversations requiring staff action.

    Returns conversations where the AI flagged the need for human attention.
    """
    try:
        session_manager = get_chat_session_manager(db)

        conversations = await session_manager.get_conversations_requiring_action(limit)

        return {
            "conversations": conversations,
            "count": len(conversations)
        }

    except Exception as e:
        logger.error(f"Admin get pending actions error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting pending actions: {str(e)}"
        )
