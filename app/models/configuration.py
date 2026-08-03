"""
Configuration Models
Includes: SystemSettings, EmailTemplates, SMSTemplates, HotelSettings, Roles, Permissions, RolePermissions, NotificationSettings, Integrations
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class SystemSettings(SQLModel, table=True):
    """Store system-wide configuration settings"""
    __tablename__ = "system_settings"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    setting_key: str = Field(unique=True, index=True)
    setting_value: str = Field(nullable=False)
    setting_type: Optional[str] = None  # string, number, boolean, json, array
    category: Optional[str] = Field(default=None, index=True)
    subcategory: Optional[str] = Field(default=None, index=True)
    description: Optional[str] = None
    is_public: bool = Field(default=False)
    is_sensitive: bool = Field(default=False)
    requires_restart: bool = Field(default=False)
    updated_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EmailTemplates(SQLModel, table=True):
    """Email template management"""
    __tablename__ = "email_templates"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    template_key: str = Field(unique=True, index=True)
    name: str = Field(nullable=False)
    category: Optional[str] = Field(default=None, index=True)
    subject: str = Field(nullable=False)
    body_html: str = Field(nullable=False)
    body_text: Optional[str] = None
    template_type: Optional[str] = None
    variables: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    from_name: Optional[str] = None
    from_email: Optional[str] = None
    reply_to: Optional[str] = None
    cc: Optional[str] = None
    bcc: Optional[str] = None
    attachments: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    language: str = Field(default="en")
    is_active: bool = Field(default=True, index=True)
    usage_count: int = Field(default=0)
    last_sent: Optional[datetime] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SMSTemplates(SQLModel, table=True):
    """SMS template management"""
    __tablename__ = "sms_templates"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    template_key: str = Field(unique=True, index=True)
    name: str = Field(nullable=False)
    category: Optional[str] = Field(default=None, index=True)
    message: str = Field(nullable=False)
    variables: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    language: str = Field(default="en")
    is_active: bool = Field(default=True, index=True)
    usage_count: int = Field(default=0)
    last_sent: Optional[datetime] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HotelSettings(SQLModel, table=True):
    """Hotel-specific settings"""
    __tablename__ = "hotel_settings"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    hotel_name: str = Field(nullable=False)
    hotel_code: Optional[str] = Field(default=None, unique=True)
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    timezone: str = Field(default="UTC")
    currency: str = Field(default="INR")
    tax_rate: float = Field(default=0.0)
    service_charge_rate: float = Field(default=0.0)
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    cancellation_policy: Optional[str] = None
    logo_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Roles(SQLModel, table=True):
    """User roles"""
    __tablename__ = "roles"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: Optional[str] = None
    is_system_role: bool = Field(default=False)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Permissions(SQLModel, table=True):
    """System permissions"""
    __tablename__ = "permissions"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    resource: str = Field(index=True)  # bookings, guests, rooms, staff, etc.
    action: str = Field(index=True)  # create, read, update, delete, manage
    description: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RolePermissions(SQLModel, table=True):
    """Junction table for role-permission many-to-many relationship"""
    __tablename__ = "role_permissions"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    role_id: int = Field(foreign_key="roles.id", index=True)
    permission_id: int = Field(foreign_key="permissions.id", index=True)
    granted_at: datetime = Field(default_factory=datetime.utcnow)
    granted_by: Optional[int] = Field(default=None, foreign_key="users.id")


class NotificationSettings(SQLModel, table=True):
    """User notification preferences"""
    __tablename__ = "notification_settings"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, unique=True)
    email_notifications: bool = Field(default=True)
    sms_notifications: bool = Field(default=False)
    push_notifications: bool = Field(default=True)
    notification_types: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Integrations(SQLModel, table=True):
    """Third-party integrations configuration"""
    __tablename__ = "integrations"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    integration_name: str = Field(nullable=False, index=True)
    integration_type: str = Field(index=True)  # payment, channel_manager, pms, crm, email, sms
    api_endpoint: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    configuration: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    is_active: bool = Field(default=False, index=True)
    last_sync: Optional[datetime] = None
    sync_frequency: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

