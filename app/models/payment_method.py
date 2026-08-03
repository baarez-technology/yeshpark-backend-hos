from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class PaymentMethod(SQLModel, table=True):
    """Saved payment methods for users"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Card details (encrypted in production)
    card_type: str = Field(index=True)  # visa, mastercard, amex
    last4: str  # Last 4 digits
    expiry_month: int
    expiry_year: int
    cardholder_name: Optional[str] = None
    
    # Metadata
    is_default: bool = Field(default=False, index=True)
    is_active: bool = Field(default=True, index=True)
    
    # Encrypted card token (for payment processor integration)
    card_token: Optional[str] = None  # Encrypted token from payment processor
    
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None  # Soft delete

