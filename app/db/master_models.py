"""
Master database models for multi-tenant architecture.

These models are stored in the master database (glimmora_master) and manage:
- Hotel registry: All registered hotels/tenants
- Global users: Super admins and support staff who can access multiple hotels
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Hotel(SQLModel, table=True):
    """Hotel registry in master database"""
    __tablename__ = "hotels"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    code: str = Field(unique=True, index=True, nullable=False)  # e.g., "marriott_mumbai"
    db_name: str = Field(unique=True, nullable=False)  # e.g., "glimmora_marriott_mumbai"

    # Hotel details
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    timezone: str = Field(default="UTC")
    currency: str = Field(default="INR")

    # Contact information
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None

    # Status
    is_active: bool = Field(default=True, index=True)
    subscription_tier: str = Field(default="standard")  # standard, premium, enterprise

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GlobalUser(SQLModel, table=True):
    """Users who can access multiple hotels (super admins, support staff)"""
    __tablename__ = "global_users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, nullable=False)
    hashed_password: str = Field(nullable=False)
    full_name: str = Field(nullable=False)

    # Access control
    is_super_admin: bool = Field(default=False)
    allowed_hotels: Optional[str] = None  # JSON array of hotel codes, null = all

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
