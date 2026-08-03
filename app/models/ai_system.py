"""
AI System Models
Includes: AIIntents, AIPrompts, AIConversations (already exists in guest_chat.py)
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class AIIntents(SQLModel, table=True):
    """Store AI chatbot intents and training data"""
    __tablename__ = "ai_intents"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    intent_key: str = Field(unique=True, index=True)
    intent_name: str = Field(nullable=False)
    category: Optional[str] = Field(default=None, index=True)  # booking, support, inquiry, complaint, information, action
    description: Optional[str] = None
    training_phrases: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB: Array of example phrases
    response_template: Optional[str] = None
    requires_auth: bool = Field(default=False)
    confidence_threshold: float = Field(default=0.7)
    handler_function: Optional[str] = None
    parameters: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    follow_up_intents: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    is_active: bool = Field(default=True, index=True)
    usage_count: int = Field(default=0)
    success_rate: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AIPrompts(SQLModel, table=True):
    """Store AI system prompts and templates"""
    __tablename__ = "ai_prompts"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    prompt_key: str = Field(unique=True, index=True)
    module: Optional[str] = Field(default=None, index=True)  # guest_ai, admin_ai, housekeeping, revenue, crm, reputation
    prompt_type: Optional[str] = Field(default=None, index=True)  # system, user, assistant, function
    prompt_text: str = Field(nullable=False)
    variables: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    version: Optional[str] = None
    is_active: bool = Field(default=True, index=True)
    last_used: Optional[datetime] = None
    usage_count: int = Field(default=0)
    avg_response_time: Optional[int] = None  # milliseconds
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

