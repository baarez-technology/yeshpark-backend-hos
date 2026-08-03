"""
Chat Session Manager

This module handles all session and conversation persistence for the Guest AI.
It provides a robust, database-backed session management system.

Features:
- Session creation and retrieval
- Conversation history persistence
- User authentication verification
- Admin visibility into all conversations
- Automatic session cleanup
"""

import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guest_chat import (
    GuestChatSession,
    GuestChatConversation,
    StaffTask,
    StaffNotification
)
from app.models.user import User
from app.models.reservations import Guest, Booking, Reservation

logger = logging.getLogger(__name__)


class ChatSessionManager:
    """
    Manages chat sessions and conversation persistence.

    This class handles:
    - Creating and retrieving chat sessions
    - Persisting conversation turns
    - Loading conversation history
    - Linking sessions to bookings/users
    - Admin queries for all conversations
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    # =========================================================================
    # Session Management
    # =========================================================================

    async def get_or_create_session(
        self,
        user_id: int,
        booking_id: Optional[int] = None
    ) -> Tuple[GuestChatSession, bool]:
        """
        Get an existing active session for the user or create a new one.

        Args:
            user_id: The authenticated user's ID
            booking_id: Optional booking ID to associate with the session

        Returns:
            Tuple of (session, is_new) where is_new indicates if a new session was created
        """
        # Try to find an active session for this user
        result = await self.db.exec(
            select(GuestChatSession)
            .where(GuestChatSession.user_id == user_id)
            .where(GuestChatSession.status == "active")
            .order_by(GuestChatSession.last_activity.desc())
        )
        session = result.first()

        # Check if session is stale (more than 1 hour old)
        if session:
            if datetime.utcnow() - session.last_activity > timedelta(hours=1):
                # Mark old session as closed
                session.status = "closed"
                session.updated_at = datetime.utcnow()
                self.db.add(session)
                await self.db.flush()
                session = None

        if session:
            # Update last activity
            session.last_activity = datetime.utcnow()
            session.updated_at = datetime.utcnow()

            # Update booking_id if provided and not already set
            if booking_id and not session.booking_id:
                session.booking_id = booking_id

            self.db.add(session)
            await self.db.flush()
            return session, False

        # Create new session
        new_session = GuestChatSession(
            session_id=f"chat_{uuid.uuid4().hex[:16]}",
            user_id=user_id,
            booking_id=booking_id,
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_activity=datetime.utcnow()
        )

        self.db.add(new_session)
        await self.db.flush()
        await self.db.refresh(new_session)

        logger.info(f"Created new chat session: {new_session.session_id} for user {user_id}")
        return new_session, True

    async def get_session_by_id(self, session_id: str) -> Optional[GuestChatSession]:
        """Get a session by its session_id."""
        result = await self.db.exec(
            select(GuestChatSession).where(GuestChatSession.session_id == session_id)
        )
        return result.first()

    async def close_session(self, session_id: str) -> bool:
        """Close a chat session."""
        session = await self.get_session_by_id(session_id)
        if session:
            session.status = "closed"
            session.updated_at = datetime.utcnow()
            self.db.add(session)
            await self.db.flush()
            logger.info(f"Closed chat session: {session_id}")
            return True
        return False

    # =========================================================================
    # Conversation Persistence
    # =========================================================================

    async def save_conversation_turn(
        self,
        session_id: str,
        user_query: str,
        bot_response: str,
        classification: str = "general",
        requires_staff_action: bool = False,
        staff_task_id: Optional[int] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> GuestChatConversation:
        """
        Save a single conversation turn (user message + bot response).

        Args:
            session_id: The session ID
            user_query: The user's message
            bot_response: The AI's response
            classification: Intent classification (general, booking, request, etc.)
            requires_staff_action: Whether this needs staff attention
            staff_task_id: Optional linked staff task ID
            extra_data: Optional additional metadata

        Returns:
            The created conversation record
        """
        conversation = GuestChatConversation(
            conversation_id=f"conv_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            user_query=user_query,
            bot_response=bot_response,
            classification=classification,
            requires_staff_action=requires_staff_action,
            staff_task_id=staff_task_id,
            extra_data=json.dumps(extra_data) if extra_data else None,
            created_at=datetime.utcnow()
        )

        self.db.add(conversation)
        await self.db.flush()
        await self.db.refresh(conversation)

        # Update session's last activity
        result = await self.db.exec(
            select(GuestChatSession).where(GuestChatSession.session_id == session_id)
        )
        session = result.first()
        if session:
            session.last_activity = datetime.utcnow()
            session.updated_at = datetime.utcnow()
            self.db.add(session)

        await self.db.flush()

        logger.debug(f"Saved conversation turn: {conversation.conversation_id}")
        return conversation

    async def get_conversation_history(
        self,
        session_id: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get conversation history for a session.

        Args:
            session_id: The session ID
            limit: Maximum number of conversation turns to return

        Returns:
            List of conversation dictionaries with user/bot messages
        """
        result = await self.db.exec(
            select(GuestChatConversation)
            .where(GuestChatConversation.session_id == session_id)
            .order_by(GuestChatConversation.created_at.asc())
            .limit(limit)
        )
        conversations = result.all()

        history = []
        for conv in conversations:
            history.append({
                "type": "user",
                "content": conv.user_query,
                "timestamp": conv.created_at.isoformat(),
                "conversation_id": conv.conversation_id
            })
            history.append({
                "type": "ai",
                "content": conv.bot_response,
                "timestamp": conv.created_at.isoformat(),
                "conversation_id": conv.conversation_id,
                "classification": conv.classification
            })

        return history

    async def get_recent_messages_for_context(
        self,
        session_id: str,
        limit: int = 10
    ) -> List[Dict[str, str]]:
        """
        Get recent messages formatted for AI context.

        Returns messages in format suitable for LLM conversation history.
        """
        result = await self.db.exec(
            select(GuestChatConversation)
            .where(GuestChatConversation.session_id == session_id)
            .order_by(GuestChatConversation.created_at.desc())
            .limit(limit)
        )
        conversations = list(result.all())
        conversations.reverse()  # Oldest first

        messages = []
        for conv in conversations:
            messages.append({"type": "user", "content": conv.user_query})
            messages.append({"type": "ai", "content": conv.bot_response})

        return messages

    # =========================================================================
    # Staff Task Creation
    # =========================================================================

    async def create_staff_task(
        self,
        task_type: str,
        title: str,
        description: str,
        conversation_id: str,
        booking_id: Optional[int] = None,
        guest_id: Optional[int] = None,
        room_number: Optional[str] = None,
        priority: str = "normal"
    ) -> StaffTask:
        """
        Create a staff task from a guest request.

        Args:
            task_type: Type of task (housekeeping, maintenance, concierge, etc.)
            title: Brief task title
            description: Detailed description
            conversation_id: The conversation that created this task
            booking_id: Optional booking ID
            guest_id: Optional guest ID
            room_number: Optional room number
            priority: Task priority (low, normal, high, urgent)

        Returns:
            The created staff task
        """
        task = StaffTask(
            task_type=task_type,
            title=title,
            description=description,
            conversation_id=conversation_id,
            booking_id=booking_id,
            guest_id=guest_id,
            room_number=room_number,
            priority=priority,
            status="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)

        logger.info(f"Created staff task: {task.id} - {task.title}")
        return task

    async def notify_staff(
        self,
        staff_id: int,
        task_id: Optional[int],
        notification_type: str,
        title: str,
        message: str
    ) -> StaffNotification:
        """
        Create a notification for staff.

        Args:
            staff_id: The staff user ID to notify
            task_id: Optional related task ID
            notification_type: Type of notification
            title: Notification title
            message: Notification message

        Returns:
            The created notification
        """
        notification = StaffNotification(
            staff_id=staff_id,
            task_id=task_id,
            notification_type=notification_type,
            title=title,
            message=message,
            is_read=False,
            created_at=datetime.utcnow()
        )

        self.db.add(notification)
        await self.db.flush()
        await self.db.refresh(notification)

        return notification

    # =========================================================================
    # Admin Queries
    # =========================================================================

    async def get_all_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get all chat sessions for admin view.

        Args:
            status: Optional filter by status
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (sessions list, total count)
        """
        query = select(GuestChatSession)

        if status:
            query = query.where(GuestChatSession.status == status)

        # Get total count
        count_result = await self.db.exec(query)
        total = len(count_result.all())

        # Get paginated results
        query = query.order_by(GuestChatSession.last_activity.desc())
        query = query.offset(offset).limit(limit)

        result = await self.db.exec(query)
        sessions = result.all()

        session_data = []
        for session in sessions:
            # Get user info
            user = await self.db.get(User, session.user_id) if session.user_id else None

            # Get conversation count
            conv_result = await self.db.exec(
                select(GuestChatConversation)
                .where(GuestChatConversation.session_id == session.session_id)
            )
            conv_count = len(conv_result.all())

            session_data.append({
                "session_id": session.session_id,
                "user_id": session.user_id,
                "user_name": user.full_name if user else None,
                "user_email": user.email if user else None,
                "booking_id": session.booking_id,
                "status": session.status,
                "conversation_count": conv_count,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat()
            })

        return session_data, total

    async def get_session_full_conversation(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        Get full conversation details for admin view.

        Returns session info with all conversation turns.
        """
        session = await self.get_session_by_id(session_id)
        if not session:
            return None

        # Get user info
        user = await self.db.get(User, session.user_id) if session.user_id else None

        # Get all conversations
        result = await self.db.exec(
            select(GuestChatConversation)
            .where(GuestChatConversation.session_id == session_id)
            .order_by(GuestChatConversation.created_at.asc())
        )
        conversations = result.all()

        conv_data = []
        for conv in conversations:
            conv_data.append({
                "conversation_id": conv.conversation_id,
                "user_query": conv.user_query,
                "bot_response": conv.bot_response,
                "classification": conv.classification,
                "requires_staff_action": conv.requires_staff_action,
                "staff_task_id": conv.staff_task_id,
                "extra_data": json.loads(conv.extra_data) if conv.extra_data else None,
                "created_at": conv.created_at.isoformat()
            })

        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "user_name": user.full_name if user else None,
            "user_email": user.email if user else None,
            "booking_id": session.booking_id,
            "status": session.status,
            "created_at": session.created_at.isoformat(),
            "last_activity": session.last_activity.isoformat(),
            "conversations": conv_data
        }

    async def get_conversations_requiring_action(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get conversations that require staff action.
        """
        result = await self.db.exec(
            select(GuestChatConversation)
            .where(GuestChatConversation.requires_staff_action == True)
            .order_by(GuestChatConversation.created_at.desc())
            .limit(limit)
        )
        conversations = result.all()

        conv_data = []
        for conv in conversations:
            # Get session info
            session = await self.get_session_by_id(conv.session_id)
            user = await self.db.get(User, session.user_id) if session and session.user_id else None

            conv_data.append({
                "conversation_id": conv.conversation_id,
                "session_id": conv.session_id,
                "user_name": user.full_name if user else None,
                "user_email": user.email if user else None,
                "user_query": conv.user_query,
                "bot_response": conv.bot_response,
                "classification": conv.classification,
                "staff_task_id": conv.staff_task_id,
                "created_at": conv.created_at.isoformat()
            })

        return conv_data

    # =========================================================================
    # User/Booking Helpers
    # =========================================================================

    async def get_user_bookings(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Get all bookings for a user.

        Checks both the new Booking table and legacy Reservation table.
        """
        user = await self.db.get(User, user_id)
        if not user:
            return []

        # Find guest by user email
        result = await self.db.exec(
            select(Guest).where(Guest.email == user.email)
        )
        guest = result.first()

        if not guest:
            return []

        bookings_data = []

        # Try new Booking table first
        try:
            result = await self.db.exec(
                select(Booking)
                .where(Booking.guest_id == guest.id)
                .order_by(Booking.arrival_date.desc())
            )
            bookings = result.all()

            for booking in bookings:
                bookings_data.append({
                    "id": booking.id,
                    "confirmation_code": booking.confirmation_code,
                    "check_in": booking.arrival_date.isoformat() if booking.arrival_date else None,
                    "check_out": booking.departure_date.isoformat() if booking.departure_date else None,
                    "status": booking.status,
                    "adults": booking.adults,
                    "children": booking.children or 0,
                    "total_amount": float(booking.total_price) if booking.total_price else 0,
                    "room_type_id": booking.room_type_id,
                    "room_id": booking.room_id,
                    "table": "booking"
                })
        except Exception as e:
            logger.debug(f"No Booking table or error: {e}")

        # Also check legacy Reservation table
        try:
            result = await self.db.exec(
                select(Reservation)
                .where(Reservation.guest_id == guest.id)
                .order_by(Reservation.arrival_date.desc())
            )
            reservations = result.all()

            for res in reservations:
                bookings_data.append({
                    "id": res.id,
                    "confirmation_code": res.confirmation_code,
                    "check_in": res.arrival_date.isoformat() if res.arrival_date else None,
                    "check_out": res.departure_date.isoformat() if res.departure_date else None,
                    "status": res.status,
                    "adults": res.adults,
                    "children": res.children or 0,
                    "total_amount": float(res.total_amount) if res.total_amount else 0,
                    "room_id": res.room_id,
                    "table": "reservation"
                })
        except Exception as e:
            logger.debug(f"No Reservation table or error: {e}")

        return bookings_data

    async def get_user_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user profile information."""
        user = await self.db.get(User, user_id)
        if not user:
            return None

        return {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "phone": user.phone,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }

    async def lookup_booking_by_code(
        self,
        confirmation_code: str
    ) -> Optional[Dict[str, Any]]:
        """
        Look up a booking by confirmation code.

        Checks both Booking and Reservation tables.
        """
        # Try Booking table
        try:
            result = await self.db.exec(
                select(Booking).where(Booking.confirmation_code == confirmation_code)
            )
            booking = result.first()

            if booking:
                # Get room type info
                room_type_name = None
                if booking.room_type_id:
                    from app.models.inventory import RoomType
                    room_type = await self.db.get(RoomType, booking.room_type_id)
                    if room_type:
                        room_type_name = room_type.name

                # Get room number
                room_number = None
                if booking.room_id:
                    from app.models.inventory import Room
                    room = await self.db.get(Room, booking.room_id)
                    if room:
                        room_number = room.number

                return {
                    "id": booking.id,
                    "confirmation_code": booking.confirmation_code,
                    "check_in": booking.arrival_date.isoformat() if booking.arrival_date else None,
                    "check_out": booking.departure_date.isoformat() if booking.departure_date else None,
                    "status": booking.status,
                    "adults": booking.adults,
                    "children": booking.children or 0,
                    "total_amount": float(booking.total_price) if booking.total_price else 0,
                    "room_type": room_type_name,
                    "room_number": room_number,
                    "pre_checked_in": booking.pre_checked_in if hasattr(booking, 'pre_checked_in') else False,
                    "table": "booking"
                }
        except Exception as e:
            logger.debug(f"Error checking Booking table: {e}")

        # Try Reservation table
        try:
            result = await self.db.exec(
                select(Reservation).where(Reservation.confirmation_code == confirmation_code)
            )
            reservation = result.first()

            if reservation:
                room_number = None
                if reservation.room_id:
                    from app.models.inventory import Room
                    room = await self.db.get(Room, reservation.room_id)
                    if room:
                        room_number = room.number

                return {
                    "id": reservation.id,
                    "confirmation_code": reservation.confirmation_code,
                    "check_in": reservation.arrival_date.isoformat() if reservation.arrival_date else None,
                    "check_out": reservation.departure_date.isoformat() if reservation.departure_date else None,
                    "status": reservation.status,
                    "adults": reservation.adults,
                    "children": reservation.children or 0,
                    "total_amount": float(reservation.total_amount) if reservation.total_amount else 0,
                    "room_number": room_number,
                    "table": "reservation"
                }
        except Exception as e:
            logger.debug(f"Error checking Reservation table: {e}")

        return None


# Factory function for easy use
def get_chat_session_manager(db_session: AsyncSession) -> ChatSessionManager:
    """Create a ChatSessionManager instance."""
    return ChatSessionManager(db_session)
