"""
Role-Based Access Control (RBAC) Models
Enhanced RBAC system with granular permissions, session tracking, and audit logging.
Includes: Role, Permission, RolePermission, UserRole, UserSession, AuditLog
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, Text


class Role(SQLModel, table=True):
    """
    User roles with enhanced metadata.
    Roles are global (not property-specific) for system-wide access control.
    """
    __tablename__ = "rbac_roles"

    id: Optional[int] = Field(default=None, primary_key=True)
    role_code: str = Field(unique=True, nullable=False, index=True)  # owner, manager, front_desk, housekeeping, finance, staff
    role_name: str = Field(nullable=False)  # Display name: "Property Owner", "Front Desk Agent", etc.
    description: Optional[str] = None
    color: Optional[str] = None  # Hex color for UI display (e.g., "#3B82F6")
    is_system_role: bool = Field(default=False)  # System roles cannot be deleted
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class Permission(SQLModel, table=True):
    """
    Available permissions organized by module.
    Permissions are global (not property-specific).
    """
    __tablename__ = "rbac_permissions"

    id: Optional[int] = Field(default=None, primary_key=True)
    permission_code: str = Field(unique=True, nullable=False, index=True)  # dashboard, bookings, guests, rooms, housekeeping, etc.
    permission_name: str = Field(nullable=False)  # Display name: "Dashboard Access", "Manage Bookings", etc.
    module: str = Field(nullable=False, index=True)  # core, operations, analytics, advanced, admin
    description: Optional[str] = None
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class RolePermission(SQLModel, table=True):
    """
    Role-permission mapping with granular access levels (CRUD).
    Defines what each role can do for each permission.
    """
    __tablename__ = "rbac_role_permissions"

    id: Optional[int] = Field(default=None, primary_key=True)
    role_id: int = Field(foreign_key="rbac_roles.id", nullable=False, index=True)
    permission_id: int = Field(foreign_key="rbac_permissions.id", nullable=False, index=True)
    can_view: bool = Field(default=False)  # Read access
    can_create: bool = Field(default=False)  # Create access
    can_edit: bool = Field(default=False)  # Update access
    can_delete: bool = Field(default=False)  # Delete access
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class UserRole(SQLModel, table=True):
    """
    User-role assignment.
    Links users to their assigned roles.
    """
    __tablename__ = "rbac_user_roles"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    role_id: int = Field(foreign_key="rbac_roles.id", nullable=False, index=True)
    assigned_by: Optional[int] = Field(default=None, foreign_key="users.id")  # User who assigned this role
    assigned_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)


class UserSession(SQLModel, table=True):
    """
    Session tracking for user authentication.
    Tracks active sessions, login history, and security information.
    """
    __tablename__ = "rbac_user_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    session_token: str = Field(unique=True, nullable=False, index=True)  # Unique session identifier
    ip_address: Optional[str] = Field(default=None, max_length=45)  # IPv4 or IPv6
    user_agent: Optional[str] = Field(default=None, sa_column=Column(Text))  # Browser/client info
    login_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    last_activity_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    logout_at: Optional[datetime] = Field(default=None, index=True)
    is_active: bool = Field(default=True, index=True)


class AuditLog(SQLModel, table=True):
    """
    System audit trail for tracking all important actions.
    Records who did what, when, and from where.
    """
    __tablename__ = "rbac_audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)  # Nullable for system actions
    action_type: str = Field(nullable=False, index=True)  # create, update, delete, login, logout, view, export, import, etc.
    entity_type: Optional[str] = Field(default=None, index=True)  # booking, guest, room, user, role, permission, etc.
    entity_id: Optional[int] = Field(default=None, index=True)  # ID of the affected entity
    old_values: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB: Previous state
    new_values: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB: New state
    ip_address: Optional[str] = Field(default=None, max_length=45)  # IPv4 or IPv6
    user_agent: Optional[str] = Field(default=None, sa_column=Column(Text))  # Browser/client info
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
