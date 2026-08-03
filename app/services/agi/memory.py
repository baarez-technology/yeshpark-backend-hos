"""
Guest Memory Manager for AGI Assistant
Handles conversation memory, guest preferences, and context management
"""

import logging
import json
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.memory")


@dataclass
class GuestContext:
    """Current guest context for the conversation"""
    session_id: str
    guest_id: Optional[int] = None
    user_id: Optional[int] = None
    booking_id: Optional[int] = None
    room_number: Optional[str] = None
    confirmation_code: Optional[str] = None
    guest_name: Optional[str] = None
    check_in_date: Optional[str] = None
    check_out_date: Optional[str] = None
    is_checked_in: bool = False
    loyalty_tier: Optional[str] = None
    preferences: Dict[str, Any] = field(default_factory=dict)
    special_requests: List[str] = field(default_factory=list)
    active_tasks: List[Dict[str, Any]] = field(default_factory=list)
    emotion: Optional[str] = None  # happy, neutral, frustrated, upset
    last_updated: Optional[str] = None


@dataclass
class ConversationMemory:
    """Memory of the current conversation"""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    current_intent: Optional[str] = None
    pending_action: Optional[Dict[str, Any]] = None
    collected_info: Dict[str, Any] = field(default_factory=dict)
    follow_up_needed: bool = False
    follow_up_topic: Optional[str] = None


class GuestMemoryManager:
    """
    Manages guest memory and context for AGI conversations.

    Features:
    - Short-term conversation memory
    - Long-term guest preferences
    - Context persistence across sessions
    - Emotion tracking
    - Active task tracking
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._context_cache: Dict[str, GuestContext] = {}
        self._memory_cache: Dict[str, ConversationMemory] = {}

    async def get_or_create_context(
        self,
        session_id: str,
        user_id: Optional[int] = None,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        room_number: Optional[str] = None
    ) -> GuestContext:
        """
        Get existing context or create new one for the session.

        Args:
            session_id: Chat session ID
            user_id: User ID if authenticated
            guest_id: Guest ID if known
            booking_id: Booking ID if known
            room_number: Room number if known

        Returns:
            GuestContext object
        """
        # Check cache first
        if session_id in self._context_cache:
            context = self._context_cache[session_id]
            # Update with any new info
            if user_id and not context.user_id:
                context.user_id = user_id
            if guest_id and not context.guest_id:
                context.guest_id = guest_id
            if booking_id and not context.booking_id:
                context.booking_id = booking_id
            if room_number and not context.room_number:
                context.room_number = room_number
            return context

        # Create new context
        context = GuestContext(
            session_id=session_id,
            user_id=user_id,
            guest_id=guest_id,
            booking_id=booking_id,
            room_number=room_number,
            last_updated=datetime.utcnow().isoformat()
        )

        # Load from database if we have identifiers
        if guest_id or user_id or booking_id:
            context = await self._load_context_from_db(context)

        self._context_cache[session_id] = context
        return context

    async def _load_context_from_db(self, context: GuestContext) -> GuestContext:
        """Load guest context from database"""
        from app.models.reservations import Booking, Guest
        from app.models.inventory import Room
        from app.models.guest_chat import StaffTask

        try:
            # Load guest info
            if context.guest_id:
                result = await self.db.execute(
                    select(Guest).where(Guest.id == context.guest_id)
                )
                guest = result.scalars().first()
                if guest:
                    context.guest_name = f"{guest.first_name} {guest.last_name}"
                    context.loyalty_tier = getattr(guest, 'loyalty_tier', None)
                    context.emotion = getattr(guest, 'emotion', 'neutral')
                    if hasattr(guest, 'preferences') and guest.preferences:
                        try:
                            context.preferences = json.loads(guest.preferences) if isinstance(guest.preferences, str) else guest.preferences
                        except:
                            pass

            # Load booking info
            if context.booking_id:
                result = await self.db.execute(
                    select(Booking).where(Booking.id == context.booking_id)
                )
                booking = result.scalars().first()
                if booking:
                    context.confirmation_code = booking.confirmation_code
                    context.check_in_date = booking.arrival_date.isoformat() if booking.arrival_date else None
                    context.check_out_date = booking.departure_date.isoformat() if booking.departure_date else None
                    context.is_checked_in = booking.status == "checked_in"
                    context.special_requests = [booking.special_requests] if booking.special_requests else []

                    # Get room number from booking
                    if booking.room_id and not context.room_number:
                        room_result = await self.db.execute(
                            select(Room).where(Room.id == booking.room_id)
                        )
                        room = room_result.scalars().first()
                        if room:
                            context.room_number = room.number

                    # Get guest if not already loaded
                    if not context.guest_id and booking.guest_id:
                        context.guest_id = booking.guest_id
                        guest_result = await self.db.execute(
                            select(Guest).where(Guest.id == booking.guest_id)
                        )
                        guest = guest_result.scalars().first()
                        if guest:
                            context.guest_name = f"{guest.first_name} {guest.last_name}"

            # Load active tasks
            if context.room_number:
                result = await self.db.execute(
                    select(StaffTask).where(
                        and_(
                            StaffTask.room_number == context.room_number,
                            StaffTask.status.in_(["pending", "assigned", "in_progress"])
                        )
                    ).order_by(StaffTask.created_at.desc()).limit(5)
                )
                tasks = result.scalars().all()
                context.active_tasks = [
                    {
                        "task_id": t.id,
                        "type": t.task_type,
                        "title": t.title,
                        "status": t.status,
                        "created_at": t.created_at.isoformat()
                    }
                    for t in tasks
                ]

        except Exception as e:
            logger.error(f"Error loading context from DB: {e}")

        return context

    async def update_context(
        self,
        session_id: str,
        updates: Dict[str, Any]
    ) -> GuestContext:
        """
        Update guest context with new information.

        Args:
            session_id: Chat session ID
            updates: Dictionary of updates to apply

        Returns:
            Updated GuestContext
        """
        context = await self.get_or_create_context(session_id)

        for key, value in updates.items():
            if hasattr(context, key):
                setattr(context, key, value)

        context.last_updated = datetime.utcnow().isoformat()
        self._context_cache[session_id] = context

        return context

    async def update_from_booking(
        self,
        session_id: str,
        booking_info: Dict[str, Any]
    ) -> GuestContext:
        """
        Update context from booking lookup result.

        Args:
            session_id: Chat session ID
            booking_info: Booking information dictionary

        Returns:
            Updated GuestContext
        """
        updates = {
            "booking_id": booking_info.get("id"),
            "confirmation_code": booking_info.get("confirmation_code"),
            "guest_id": booking_info.get("guest_id"),
            "guest_name": booking_info.get("guest_name"),
            "room_number": booking_info.get("room_number"),
            "check_in_date": booking_info.get("arrival_date"),
            "check_out_date": booking_info.get("departure_date"),
            "is_checked_in": booking_info.get("is_checked_in", False)
        }

        # Filter out None values
        updates = {k: v for k, v in updates.items() if v is not None}

        return await self.update_context(session_id, updates)

    def get_conversation_memory(self, session_id: str) -> ConversationMemory:
        """
        Get conversation memory for session.

        Args:
            session_id: Chat session ID

        Returns:
            ConversationMemory object
        """
        if session_id not in self._memory_cache:
            self._memory_cache[session_id] = ConversationMemory()
        return self._memory_cache[session_id]

    def add_message_to_memory(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Add a message to conversation memory.

        Args:
            session_id: Chat session ID
            role: Message role (user, assistant, system)
            content: Message content
            metadata: Optional metadata
        """
        memory = self.get_conversation_memory(session_id)

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        }
        if metadata:
            message["metadata"] = metadata

        memory.messages.append(message)

        # Keep only last 20 messages for context window
        if len(memory.messages) > 20:
            memory.messages = memory.messages[-20:]

        self._memory_cache[session_id] = memory

    def get_recent_messages(
        self,
        session_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get recent messages for context.

        Args:
            session_id: Chat session ID
            limit: Maximum number of messages

        Returns:
            List of recent messages
        """
        memory = self.get_conversation_memory(session_id)
        return memory.messages[-limit:]

    def set_pending_action(
        self,
        session_id: str,
        action_type: str,
        action_data: Dict[str, Any]
    ):
        """
        Set a pending action that requires follow-up.

        Args:
            session_id: Chat session ID
            action_type: Type of action
            action_data: Action data/parameters
        """
        memory = self.get_conversation_memory(session_id)
        memory.pending_action = {
            "type": action_type,
            "data": action_data,
            "created_at": datetime.utcnow().isoformat()
        }
        memory.follow_up_needed = True
        self._memory_cache[session_id] = memory

    def clear_pending_action(self, session_id: str):
        """Clear pending action after completion."""
        memory = self.get_conversation_memory(session_id)
        memory.pending_action = None
        memory.follow_up_needed = False
        memory.follow_up_topic = None
        self._memory_cache[session_id] = memory

    def collect_info(
        self,
        session_id: str,
        key: str,
        value: Any
    ):
        """
        Collect information during multi-turn conversations.

        Args:
            session_id: Chat session ID
            key: Information key
            value: Information value
        """
        memory = self.get_conversation_memory(session_id)
        memory.collected_info[key] = value
        self._memory_cache[session_id] = memory

    def get_collected_info(self, session_id: str) -> Dict[str, Any]:
        """Get all collected information for session."""
        memory = self.get_conversation_memory(session_id)
        return memory.collected_info

    def clear_collected_info(self, session_id: str):
        """Clear collected information after action completion."""
        memory = self.get_conversation_memory(session_id)
        memory.collected_info = {}
        self._memory_cache[session_id] = memory

    async def update_guest_emotion(
        self,
        session_id: str,
        emotion: str
    ):
        """
        Update guest emotion based on conversation analysis.

        Args:
            session_id: Chat session ID
            emotion: Detected emotion (happy, neutral, frustrated, upset)
        """
        context = await self.get_or_create_context(session_id)
        context.emotion = emotion

        # Persist to database if we have guest_id
        if context.guest_id:
            try:
                from app.models.reservations import Guest
                result = await self.db.execute(
                    select(Guest).where(Guest.id == context.guest_id)
                )
                guest = result.scalars().first()
                if guest and hasattr(guest, 'emotion'):
                    guest.emotion = emotion
                    await self.db.commit()
            except Exception as e:
                logger.error(f"Error updating guest emotion: {e}")

        self._context_cache[session_id] = context

    async def add_active_task(
        self,
        session_id: str,
        task_info: Dict[str, Any]
    ):
        """
        Add an active task to context.

        Args:
            session_id: Chat session ID
            task_info: Task information
        """
        context = await self.get_or_create_context(session_id)
        context.active_tasks.append(task_info)

        # Keep only last 10 tasks
        if len(context.active_tasks) > 10:
            context.active_tasks = context.active_tasks[-10:]

        self._context_cache[session_id] = context

    async def save_guest_preference(
        self,
        session_id: str,
        preference_key: str,
        preference_value: Any
    ):
        """
        Save a guest preference for future reference.

        Args:
            session_id: Chat session ID
            preference_key: Preference key (e.g., "room_temperature", "dietary")
            preference_value: Preference value
        """
        context = await self.get_or_create_context(session_id)
        context.preferences[preference_key] = preference_value

        # Persist to database if we have guest_id
        if context.guest_id:
            try:
                from app.models.reservations import Guest
                result = await self.db.execute(
                    select(Guest).where(Guest.id == context.guest_id)
                )
                guest = result.scalars().first()
                if guest and hasattr(guest, 'preferences'):
                    existing = {}
                    if guest.preferences:
                        try:
                            existing = json.loads(guest.preferences) if isinstance(guest.preferences, str) else guest.preferences
                        except:
                            pass
                    existing[preference_key] = preference_value
                    guest.preferences = json.dumps(existing)
                    await self.db.commit()
            except Exception as e:
                logger.error(f"Error saving guest preference: {e}")

        self._context_cache[session_id] = context

    def get_context_summary(self, session_id: str) -> str:
        """
        Get a text summary of the current context for the LLM.

        Args:
            session_id: Chat session ID

        Returns:
            Text summary of context
        """
        if session_id not in self._context_cache:
            return "No guest context available."

        context = self._context_cache[session_id]
        parts = []

        if context.guest_name:
            parts.append(f"Guest: {context.guest_name}")
        if context.room_number:
            parts.append(f"Room: {context.room_number}")
        if context.is_checked_in:
            parts.append("Status: Currently checked in")
        if context.check_out_date:
            parts.append(f"Check-out: {context.check_out_date}")
        if context.loyalty_tier:
            parts.append(f"Loyalty: {context.loyalty_tier}")
        if context.emotion and context.emotion != "neutral":
            parts.append(f"Guest mood: {context.emotion}")
        if context.active_tasks:
            task_summary = [f"{t['type']} ({t['status']})" for t in context.active_tasks[:3]]
            parts.append(f"Active requests: {', '.join(task_summary)}")
        if context.preferences:
            pref_summary = [f"{k}: {v}" for k, v in list(context.preferences.items())[:3]]
            parts.append(f"Preferences: {', '.join(pref_summary)}")

        return " | ".join(parts) if parts else "Guest not yet identified."

    def serialize_context(self, session_id: str) -> Dict[str, Any]:
        """Serialize context for API response."""
        if session_id not in self._context_cache:
            return {}
        return asdict(self._context_cache[session_id])

    def clear_session(self, session_id: str):
        """Clear all cached data for a session."""
        self._context_cache.pop(session_id, None)
        self._memory_cache.pop(session_id, None)


def get_memory_manager(db: AsyncSession) -> GuestMemoryManager:
    """Factory function to create GuestMemoryManager instance"""
    return GuestMemoryManager(db)
