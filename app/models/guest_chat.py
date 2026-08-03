from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class GuestChatSession(SQLModel, table=True):
    """Chat session for guest assistant chatbot"""
    __tablename__ = "guestchatsession"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True, unique=True)
    guest_id: Optional[int] = Field(default=None, foreign_key="guests.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    room_number: Optional[str] = Field(default=None, index=True)
    # Support both old reservation and new booking tables
    reservation_id: Optional[int] = Field(default=None, index=True)  # Legacy
    booking_id: Optional[int] = Field(default=None, index=True)  # NEW: FK to bookings
    status: str = Field(default="active", index=True)  # active, closed, archived
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow, index=True)


class GuestChatConversation(SQLModel, table=True):
    """Individual conversation entries in chat sessions"""
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: str = Field(index=True, unique=True)
    session_id: str = Field(foreign_key="guestchatsession.session_id", index=True)
    user_query: str
    bot_response: str
    classification: str = Field(index=True)  # FAQ, Assistance, Other, Greeting
    faq_id: Optional[str] = None
    requires_staff_action: bool = Field(default=False, index=True)
    staff_task_id: Optional[int] = Field(default=None, foreign_key="stafftask.id", index=True)
    room_number: Optional[str] = None
    extra_data: Optional[str] = None  # JSON string for additional data (renamed from metadata to avoid SQLAlchemy conflict)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class StaffTask(SQLModel, table=True):
    """Staff tasks created from guest requests"""
    __tablename__ = "stafftask"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    task_type: str = Field(index=True)  # housekeeping, maintenance, concierge, room_service, other
    title: str
    description: str
    room_number: Optional[str] = Field(default=None, index=True)
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)
    # Support both old reservation and new booking tables
    reservation_id: Optional[int] = Field(default=None, index=True)  # Legacy
    booking_id: Optional[int] = Field(default=None, index=True)  # NEW: FK to bookings
    guest_id: Optional[int] = Field(default=None, foreign_key="guests.id", index=True)
    conversation_id: Optional[str] = Field(default=None, foreign_key="guestchatconversation.conversation_id", index=True)
    priority: str = Field(default="normal", index=True)  # low, normal, high, urgent
    status: str = Field(default="pending", index=True)  # pending, assigned, in_progress, completed, cancelled
    assigned_to: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    scheduled_for: Optional[datetime] = Field(default=None, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_duration: Optional[int] = None  # minutes
    actual_duration: Optional[int] = None  # minutes
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StaffNotification(SQLModel, table=True):
    """Notifications sent to staff for new tasks"""
    __tablename__ = "staffnotification"

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="users.id", index=True)
    task_id: Optional[int] = Field(default=None, foreign_key="stafftask.id", index=True)  # Made optional
    notification_type: str = Field(default="task_assigned", index=True)  # task_assigned, task_reminder, task_update, alert, info, system
    title: str
    message: str

    # Entity references for navigation (clicking notification highlights the entity)
    guest_id: Optional[int] = Field(default=None, foreign_key="guests.id", index=True)
    booking_id: Optional[int] = Field(default=None, index=True)
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)

    is_read: bool = Field(default=False, index=True)
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

