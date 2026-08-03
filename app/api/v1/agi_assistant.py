"""
AGI Guest Assistant API Endpoints
Advanced AI-powered guest assistant with voice support
"""

import base64
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_tenant_session
from app.models.user import User
from app.api.v1.auth import get_current_user
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from app.core.config import settings
from sqlmodel import select

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


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

class AGIChatRequest(BaseModel):
    """Request model for AGI chat"""
    message: str = Field(..., min_length=1, max_length=4000, description="Guest message")
    session_id: Optional[str] = Field(None, description="Chat session ID")
    room_number: Optional[str] = Field(None, description="Guest's room number")
    booking_number: Optional[str] = Field(None, description="Booking confirmation number")
    voice_input: bool = Field(default=False, description="Whether this is from voice input")


class AGIVoiceRequest(BaseModel):
    """Request model for voice input"""
    audio_base64: str = Field(..., description="Base64 encoded audio data")
    audio_format: str = Field(default="webm", description="Audio format")
    session_id: Optional[str] = Field(None, description="Chat session ID")
    room_number: Optional[str] = Field(None, description="Guest's room number")
    booking_number: Optional[str] = Field(None, description="Booking confirmation number")


class QuickAction(BaseModel):
    """Quick action button"""
    label: str
    action: str


class AGIChatResponse(BaseModel):
    """Response model for AGI chat"""
    message: str
    intent: str
    confidence: float
    session_id: str
    action_taken: bool = False
    action_result: Optional[Dict[str, Any]] = None
    task_id: Optional[int] = None
    task_type: Optional[str] = None
    quick_actions: Optional[List[QuickAction]] = None
    guest_context: Optional[Dict[str, Any]] = None
    voice_response_available: bool = False
    follow_up_needed: bool = False
    # V2 AGI fields
    requires_otp: bool = False
    otp_email: Optional[str] = None
    show_login_prompt: bool = False
    booking_created: Optional[int] = None
    guest_status: Optional[str] = None
    loyalty_points: Optional[int] = None
    loyalty_tier: Optional[str] = None


class VoiceResponse(BaseModel):
    """Response with voice audio"""
    text: str
    audio_base64: Optional[str] = None
    audio_format: str = "mp3"
    content_type: str = "audio/mp3"


class TranscriptionResponse(BaseModel):
    """Response for voice transcription"""
    success: bool
    text: Optional[str] = None
    language: Optional[str] = None
    confidence: float = 0.0
    error: Optional[str] = None


class TTSRequest(BaseModel):
    """Request for text-to-speech"""
    text: str = Field(..., max_length=4096, description="Text to convert to speech")
    voice: str = Field(default="nova", description="Voice: alloy, echo, fable, onyx, nova, shimmer")
    speed: float = Field(default=1.0, ge=0.25, le=4.0, description="Speech speed")


class ContextResponse(BaseModel):
    """Response with guest context"""
    success: bool
    context: Dict[str, Any]


# ============== API Endpoints ==============

@router.post("/chat", response_model=AGIChatResponse)
async def chat_with_agi(
    payload: AGIChatRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Chat with the AGI guest assistant.

    Features:
    - Multi-tool orchestration for all hotel services
    - Context-aware conversations
    - Intelligent intent routing
    - Memory management across sessions
    - Proactive suggestions
    """
    from app.services.agi import get_agi_agent

    try:
        # Generate session ID if not provided
        session_id = payload.session_id or f"agi_session_{current_user.id if current_user else 'guest'}_{int(datetime.utcnow().timestamp() * 1000)}"

        # Get user/guest info
        user_id = current_user.id if current_user else None
        guest_id = None
        booking_id = None

        # Try to find guest_id from user
        if current_user:
            from app.models.reservations import Guest
            guest_result = await session.exec(
                select(Guest).where(Guest.user_id == current_user.id)
            )
            guest = guest_result.first()
            if guest:
                guest_id = guest.id

        # If booking number provided, look it up
        if payload.booking_number:
            from app.models.reservations import Booking
            booking_result = await session.exec(
                select(Booking).where(
                    Booking.confirmation_code == payload.booking_number.upper()
                )
            )
            booking = booking_result.first()
            if booking:
                booking_id = booking.id
                if booking.guest_id:
                    guest_id = booking.guest_id

        # Initialize AGI agent
        agi_agent = get_agi_agent(session)

        # Process message
        response = await agi_agent.process_message(
            message=payload.message,
            session_id=session_id,
            user_id=user_id,
            guest_id=guest_id,
            booking_id=booking_id,
            room_number=payload.room_number,
            voice_input=payload.voice_input
        )

        logger.info(
            f"AGI Chat - Intent: {response.intent}, "
            f"Confidence: {response.confidence:.2f}, "
            f"Action: {response.action_taken}"
        )

        return AGIChatResponse(
            message=response.message,
            intent=response.intent,
            confidence=response.confidence,
            session_id=session_id,
            action_taken=response.action_taken,
            action_result=response.action_result,
            task_id=response.task_id,
            task_type=response.task_type,
            quick_actions=[
                QuickAction(label=qa["label"], action=qa["action"])
                for qa in (response.quick_actions or [])
            ] if response.quick_actions else None,
            guest_context=response.guest_context,
            voice_response_available=True,
            follow_up_needed=response.follow_up_needed,
            # V2 AGI fields
            requires_otp=getattr(response, 'requires_otp', False),
            otp_email=getattr(response, 'otp_email', None),
            show_login_prompt=getattr(response, 'show_login_prompt', False),
            booking_created=getattr(response, 'booking_created', None),
            guest_status=getattr(response, 'guest_status', None),
            loyalty_points=getattr(response, 'loyalty_points', None),
            loyalty_tier=getattr(response, 'loyalty_tier', None),
        )

    except Exception as e:
        logger.error(f"Error in AGI chat: {e}", exc_info=True)
        return AGIChatResponse(
            message="I apologize, but I'm experiencing technical difficulties. Please try again or contact our front desk for immediate assistance.",
            intent="error",
            confidence=0.0,
            session_id=payload.session_id or f"error_{int(datetime.utcnow().timestamp() * 1000)}",
            quick_actions=[
                QuickAction(label="Try Again", action="retry"),
                QuickAction(label="Contact Front Desk", action="front_desk")
            ]
        )


@router.post("/voice/transcribe", response_model=TranscriptionResponse)
async def transcribe_voice(
    payload: AGIVoiceRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Transcribe voice input to text.

    Accepts base64-encoded audio and returns transcribed text.
    Supported formats: webm, mp3, wav, m4a, ogg
    """
    from app.services.agi.voice_processor import get_voice_processor

    try:
        voice_processor = get_voice_processor()

        if not voice_processor.is_available:
            return TranscriptionResponse(
                success=False,
                error="Voice processing not available. Please type your message."
            )

        result = await voice_processor.transcribe_base64_audio(
            base64_audio=payload.audio_base64,
            audio_format=payload.audio_format
        )

        if result.get("success"):
            return TranscriptionResponse(
                success=True,
                text=result["text"],
                language=result.get("language", "en"),
                confidence=result.get("confidence", 0.95)
            )
        else:
            return TranscriptionResponse(
                success=False,
                error=result.get("error", "Transcription failed")
            )

    except Exception as e:
        logger.error(f"Error transcribing voice: {e}", exc_info=True)
        return TranscriptionResponse(
            success=False,
            error="Failed to transcribe audio. Please try again."
        )


@router.post("/voice/chat", response_model=AGIChatResponse)
async def voice_chat_with_agi(
    payload: AGIVoiceRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Full voice chat - transcribe audio and get AGI response.

    Combines transcription and chat into a single request.
    """
    from app.services.agi import get_agi_agent
    from app.services.agi.voice_processor import get_voice_processor

    try:
        voice_processor = get_voice_processor()

        # First transcribe
        transcription = await voice_processor.transcribe_base64_audio(
            base64_audio=payload.audio_base64,
            audio_format=payload.audio_format
        )

        if not transcription.get("success"):
            return AGIChatResponse(
                message="I couldn't understand the audio. Please try again or type your message.",
                intent="error",
                confidence=0.0,
                session_id=payload.session_id or f"error_{int(datetime.utcnow().timestamp() * 1000)}",
                quick_actions=[
                    QuickAction(label="Try Again", action="retry"),
                    QuickAction(label="Type Message", action="type")
                ]
            )

        # Now process the transcribed text
        session_id = payload.session_id or f"voice_session_{current_user.id if current_user else 'guest'}_{int(datetime.utcnow().timestamp() * 1000)}"

        user_id = current_user.id if current_user else None
        guest_id = None
        booking_id = None

        if current_user:
            from app.models.reservations import Guest
            guest_result = await session.exec(
                select(Guest).where(Guest.user_id == current_user.id)
            )
            guest = guest_result.first()
            if guest:
                guest_id = guest.id

        if payload.booking_number:
            from app.models.reservations import Booking
            booking_result = await session.exec(
                select(Booking).where(
                    Booking.confirmation_code == payload.booking_number.upper()
                )
            )
            booking = booking_result.first()
            if booking:
                booking_id = booking.id
                if booking.guest_id:
                    guest_id = booking.guest_id

        agi_agent = get_agi_agent(session)

        response = await agi_agent.process_message(
            message=transcription["text"],
            session_id=session_id,
            user_id=user_id,
            guest_id=guest_id,
            booking_id=booking_id,
            room_number=payload.room_number,
            voice_input=True
        )

        return AGIChatResponse(
            message=response.message,
            intent=response.intent,
            confidence=response.confidence,
            session_id=session_id,
            action_taken=response.action_taken,
            action_result=response.action_result,
            task_id=response.task_id,
            task_type=response.task_type,
            quick_actions=[
                QuickAction(label=qa["label"], action=qa["action"])
                for qa in (response.quick_actions or [])
            ] if response.quick_actions else None,
            guest_context=response.guest_context,
            voice_response_available=True,
            follow_up_needed=response.follow_up_needed,
            # V2 AGI fields
            requires_otp=getattr(response, 'requires_otp', False),
            otp_email=getattr(response, 'otp_email', None),
            show_login_prompt=getattr(response, 'show_login_prompt', False),
            booking_created=getattr(response, 'booking_created', None),
            guest_status=getattr(response, 'guest_status', None),
            loyalty_points=getattr(response, 'loyalty_points', None),
            loyalty_tier=getattr(response, 'loyalty_tier', None),
        )

    except Exception as e:
        logger.error(f"Error in voice chat: {e}", exc_info=True)
        return AGIChatResponse(
            message="I apologize, but I couldn't process your voice request. Please try again or type your message.",
            intent="error",
            confidence=0.0,
            session_id=payload.session_id or f"error_{int(datetime.utcnow().timestamp() * 1000)}"
        )


@router.post("/voice/tts", response_model=VoiceResponse)
async def text_to_speech(
    payload: TTSRequest,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Convert text to speech.

    Returns base64-encoded audio for playback.
    """
    from app.services.agi.voice_processor import get_voice_processor

    try:
        voice_processor = get_voice_processor()

        if not voice_processor.is_available:
            return VoiceResponse(
                text=payload.text,
                audio_base64=None,
                error="Text-to-speech not available"
            )

        result = await voice_processor.text_to_speech(
            text=payload.text,
            voice=payload.voice,
            speed=payload.speed
        )

        if result.get("success"):
            return VoiceResponse(
                text=payload.text,
                audio_base64=result["audio_base64"],
                audio_format=result["audio_format"],
                content_type=result["content_type"]
            )
        else:
            return VoiceResponse(
                text=payload.text,
                audio_base64=None
            )

    except Exception as e:
        logger.error(f"Error generating speech: {e}", exc_info=True)
        return VoiceResponse(text=payload.text, audio_base64=None)


@router.get("/voice/voices")
async def get_available_voices():
    """Get list of available TTS voices."""
    from app.services.agi.voice_processor import get_voice_processor

    voice_processor = get_voice_processor()
    return voice_processor.get_available_voices()


@router.get("/voice/formats")
async def get_supported_formats():
    """Get supported audio formats."""
    from app.services.agi.voice_processor import get_voice_processor

    voice_processor = get_voice_processor()
    return voice_processor.get_supported_formats()


@router.get("/context/{session_id}", response_model=ContextResponse)
async def get_session_context(
    session_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Get the current guest context for a session."""
    from app.services.agi.memory import get_memory_manager

    try:
        memory_manager = get_memory_manager(session)
        context = await memory_manager.get_or_create_context(session_id)

        return ContextResponse(
            success=True,
            context=memory_manager.serialize_context(session_id)
        )

    except Exception as e:
        logger.error(f"Error getting context: {e}")
        return ContextResponse(
            success=False,
            context={}
        )


@router.post("/context/{session_id}/clear")
async def clear_session_context(
    session_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Clear session context and start fresh."""
    from app.services.agi.memory import get_memory_manager

    try:
        memory_manager = get_memory_manager(session)
        memory_manager.clear_session(session_id)

        return {"success": True, "message": "Session context cleared"}

    except Exception as e:
        logger.error(f"Error clearing context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear session context"
        )


@router.post("/feedback")
async def submit_feedback(
    session_id: str,
    rating: int,
    feedback: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Submit feedback about the AGI assistant interaction."""
    try:
        # Log feedback (could also save to database)
        logger.info(f"AGI Feedback - Session: {session_id}, Rating: {rating}, Feedback: {feedback}")

        return {
            "success": True,
            "message": "Thank you for your feedback! We use this to improve our service."
        }

    except Exception as e:
        logger.error(f"Error submitting feedback: {e}")
        return {"success": False, "message": "Failed to submit feedback"}


@router.get("/capabilities")
async def get_agi_capabilities():
    """Get list of AGI assistant capabilities."""
    return {
        "version": "2.0",
        "capabilities": [
            {
                "name": "Booking",
                "description": "Make new reservations with OTP verification, browse room types, check availability",
                "examples": ["I want to book a room", "Show me available rooms", "Book Dec 8-10", "2 adults, 1 child"]
            },
            {
                "name": "My Bookings",
                "description": "View upcoming and past reservations, cancel or modify bookings",
                "examples": ["Show my bookings", "Cancel my reservation", "Change my check-in date", "My booking history"]
            },
            {
                "name": "Pre-Check-in",
                "description": "Complete pre-check-in, select your room, add preferences before arrival",
                "examples": ["Start pre-check-in", "Select room 503", "I prefer a high floor"]
            },
            {
                "name": "Profile Management",
                "description": "View and update your profile, change name, manage preferences",
                "examples": ["Show my profile", "Change my name to John", "Update my preferences"]
            },
            {
                "name": "Loyalty Program",
                "description": "Check points balance, tier status, redemption options",
                "examples": ["My loyalty points", "What's my tier?", "How do I earn points?"]
            },
            {
                "name": "Housekeeping",
                "description": "Room cleaning, towels, amenities, turndown service (checked-in guests)",
                "examples": ["I need extra towels", "Please clean my room", "Schedule turndown service"]
            },
            {
                "name": "Maintenance",
                "description": "Report and track repairs, HVAC, plumbing, WiFi issues (checked-in guests)",
                "examples": ["The AC isn't working", "There's a leak in the bathroom", "WiFi is slow"]
            },
            {
                "name": "Room Service",
                "description": "Food ordering, menu browsing, dietary accommodations (checked-in guests)",
                "examples": ["What's on the menu?", "I'd like to order breakfast", "Any vegetarian options?"]
            },
            {
                "name": "Concierge",
                "description": "Restaurant reservations, transportation, spa, tours",
                "examples": ["Recommend a restaurant", "Book a taxi for 5pm", "Schedule a massage"]
            },
            {
                "name": "In-House Assistance",
                "description": "WiFi password, amenity hours, staff assistance (checked-in guests)",
                "examples": ["What's the WiFi password?", "Pool hours?", "I need help from staff"]
            },
            {
                "name": "Hotel Information",
                "description": "Policies, amenities, hours, FAQs",
                "examples": ["Checkout time?", "Do you have a pool?", "Is breakfast included?"]
            }
        ],
        "features": {
            "otp_verification": True,
            "email_confirmation": True,
            "voice_enabled": True,
            "loyalty_integration": True,
            "pre_checkin": True,
        },
        "supported_languages": ["English"],
        "availability": "24/7"
    }
