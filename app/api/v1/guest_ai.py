"""
Guest AI Assistant API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Optional, List
from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.services.guest_ai_assistant import process_guest_message, create_booking_from_state
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatMessage(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    state: dict
    booking_ready: bool = False
    error: Optional[str] = None


class CreateBookingRequest(BaseModel):
    state: dict


@router.post("/chat", response_model=ChatResponse)
async def chat_with_assistant(
    payload: ChatMessage,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user)
):
    """
    Chat with the guest AI assistant
    The assistant will help create bookings by asking questions
    """
    try:
        user_id = current_user.id if current_user else None
        
        # TODO: Load conversation history from database if conversation_id provided
        conversation_history = []
        
        result = await process_guest_message(
            user_message=payload.message,
            user_id=user_id,
            conversation_history=conversation_history,
            session=session
        )
        
        return ChatResponse(
            response=result["response"],
            state=result.get("state", {}),
            booking_ready=result.get("state", {}).get("booking_ready", False),
            error=result.get("error")
        )
    
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing message: {str(e)}"
        )


@router.post("/create-booking")
async def create_booking_from_ai(
    payload: CreateBookingRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Create a booking from the AI assistant's collected state
    """
    try:
        result = await create_booking_from_state(
            state=payload.state,
            user_id=current_user.id,
            session=session
        )
        
        if result.get("error"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating booking: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating booking: {str(e)}"
        )

