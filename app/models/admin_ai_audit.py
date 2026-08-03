"""
Admin AI Audit Model
Tracks all AI operations for security and compliance
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Text, JSON


class AdminAIAudit(SQLModel, table=True):
    """Audit trail for all Admin AI operations"""
    __tablename__ = "admin_ai_audit"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True, max_length=100)
    user_id: int = Field(foreign_key="users.id", index=True)

    # Operation details
    action_type: str = Field(max_length=50)  # query, create, update, delete, email, report
    input_message: str = Field(sa_column=Column(Text))
    detected_intent: str = Field(max_length=100)
    confidence: float = Field(default=0.0)

    # Query details (for SQL operations)
    generated_query: Optional[str] = Field(default=None, sa_column=Column(Text))
    query_result_count: Optional[int] = Field(default=None)

    # Action details (for CRUD/automation operations)
    action_details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    target_table: Optional[str] = Field(default=None, max_length=100)
    target_ids: Optional[list] = Field(default=None, sa_column=Column(JSON))

    # Result
    success: bool = Field(default=False)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    response_message: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Metadata
    execution_time_ms: int = Field(default=0)
    ip_address: Optional[str] = Field(default=None, max_length=45)
    user_agent: Optional[str] = Field(default=None, max_length=500)

    # Security flags
    injection_detected: bool = Field(default=False)
    blocked: bool = Field(default=False)
    block_reason: Optional[str] = Field(default=None, max_length=255)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AdminAISession(SQLModel, table=True):
    """Track AI conversation sessions"""
    __tablename__ = "admin_ai_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(unique=True, index=True, max_length=100)
    user_id: int = Field(foreign_key="users.id", index=True)

    # Session state
    is_active: bool = Field(default=True)
    message_count: int = Field(default=0)
    last_intent: Optional[str] = Field(default=None, max_length=100)

    # Context
    context_data: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    context_summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    active_entities: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = Field(default=None)


class AdminAIMessage(SQLModel, table=True):
    """Store conversation messages for history"""
    __tablename__ = "admin_ai_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True, max_length=100)

    # Message details
    role: str = Field(max_length=20)  # user, assistant, system
    content: str = Field(sa_column=Column(Text))

    # Response metadata
    intent: Optional[str] = Field(default=None, max_length=100)
    has_query_results: bool = Field(default=False)
    has_pending_action: bool = Field(default=False)
    action_id: Optional[str] = Field(default=None, max_length=100)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
