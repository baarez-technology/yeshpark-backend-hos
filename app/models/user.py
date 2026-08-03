from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from app.models.base import TimestampedModel


class User(SQLModel, table=True):
    """Store all system users (staff, guests, administrators)"""
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, nullable=False)
    hashed_password: str = Field(nullable=False)  # Keep as hashed_password for backward compatibility
    full_name: str = Field(nullable=False)
    phone: Optional[str] = None
    avatar: Optional[str] = None
    # Profile fields
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    preferences: Optional[str] = None  # JSON string for user preferences
    role: str = Field(default="guest", index=True)  # admin, general_manager, front_office_manager, duty_manager, receptionist, reservation_manager, housekeeping_manager, housekeeper, revenue_manager, accounts_manager, guest
    is_superuser: bool = Field(default=False)
    is_active: bool = Field(default=True, index=True)
    email_verified: bool = Field(default=False)

    # Onboarding flags
    must_reset_password: bool = Field(default=False)
    first_login: bool = Field(default=False)
    temp_password_expires_at: Optional[datetime] = None

    # Multi-tenant: Hotel association
    hotel_code: Optional[str] = Field(default=None, index=True)

    # Granular permissions (JSON string) - mirrors RBAC tables for quick access
    permissions: Optional[str] = None  # JSON: {"dashboard": {"view": true, "edit": false, "delete": false}, ...}

    last_login: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


