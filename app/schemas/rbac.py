"""
Role-Based Access Control (RBAC) Schemas
Pydantic schemas for Role, Permission, RolePermission, UserRole, UserSession, AuditLog
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============== ROLE SCHEMAS ==============

class RoleBase(BaseModel):
    """Base schema for roles"""
    role_code: str
    role_name: str
    description: Optional[str] = None
    color: Optional[str] = None  # Hex color for UI display
    is_system_role: bool = False
    is_active: bool = True


class RoleCreate(RoleBase):
    """Schema for creating a role"""
    pass


class RoleUpdate(BaseModel):
    """Schema for updating a role - all fields optional"""
    role_code: Optional[str] = None
    role_name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


class RoleResponse(RoleBase):
    """Schema for role API responses"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoleWithPermissions(RoleResponse):
    """Role response with associated permissions"""
    permissions: List["RolePermissionResponse"] = []


# ============== PERMISSION SCHEMAS ==============

class PermissionBase(BaseModel):
    """Base schema for permissions"""
    permission_code: str
    permission_name: str
    module: str  # core, operations, analytics, advanced, admin
    description: Optional[str] = None
    is_active: bool = True


class PermissionCreate(PermissionBase):
    """Schema for creating a permission"""
    pass


class PermissionUpdate(BaseModel):
    """Schema for updating a permission - all fields optional"""
    permission_code: Optional[str] = None
    permission_name: Optional[str] = None
    module: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class PermissionResponse(PermissionBase):
    """Schema for permission API responses"""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============== ROLE PERMISSION SCHEMAS ==============

class RolePermissionBase(BaseModel):
    """Base schema for role-permission mappings"""
    role_id: int
    permission_id: int
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False


class RolePermissionCreate(RolePermissionBase):
    """Schema for creating a role-permission mapping"""
    pass


class RolePermissionUpdate(BaseModel):
    """Schema for updating a role-permission mapping - all fields optional"""
    can_view: Optional[bool] = None
    can_create: Optional[bool] = None
    can_edit: Optional[bool] = None
    can_delete: Optional[bool] = None


class RolePermissionResponse(RolePermissionBase):
    """Schema for role-permission API responses"""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class RolePermissionWithDetails(RolePermissionResponse):
    """Role permission with permission details"""
    permission_code: Optional[str] = None
    permission_name: Optional[str] = None
    module: Optional[str] = None


# ============== USER ROLE SCHEMAS ==============

class UserRoleBase(BaseModel):
    """Base schema for user-role assignments"""
    user_id: int
    role_id: int


class UserRoleCreate(UserRoleBase):
    """Schema for creating a user-role assignment"""
    assigned_by: Optional[int] = None


class UserRoleResponse(UserRoleBase):
    """Schema for user-role API responses"""
    id: int
    assigned_by: Optional[int] = None
    assigned_at: datetime

    class Config:
        from_attributes = True


class UserRoleWithDetails(UserRoleResponse):
    """User role with role details"""
    role_code: Optional[str] = None
    role_name: Optional[str] = None
    color: Optional[str] = None


# ============== USER SESSION SCHEMAS ==============

class UserSessionBase(BaseModel):
    """Base schema for user sessions"""
    user_id: int
    session_token: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class UserSessionCreate(UserSessionBase):
    """Schema for creating a user session"""
    pass


class UserSessionUpdate(BaseModel):
    """Schema for updating a user session - all fields optional"""
    is_active: Optional[bool] = None
    logout_at: Optional[datetime] = None


class UserSessionResponse(BaseModel):
    """Schema for user session API responses"""
    id: int
    user_id: int
    session_token: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    login_at: datetime
    last_activity_at: datetime
    logout_at: Optional[datetime] = None
    is_active: bool = True

    class Config:
        from_attributes = True


# ============== AUDIT LOG SCHEMAS ==============

class AuditLogBase(BaseModel):
    """Base schema for audit logs"""
    user_id: Optional[int] = None
    action_type: str  # create, update, delete, login, logout, view, export, import
    entity_type: Optional[str] = None  # booking, guest, room, user, role, permission
    entity_id: Optional[int] = None
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogCreate(AuditLogBase):
    """Schema for creating an audit log"""
    pass


class AuditLogResponse(AuditLogBase):
    """Schema for audit log API responses"""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogWithUser(AuditLogResponse):
    """Audit log with user details"""
    user_email: Optional[str] = None
    user_name: Optional[str] = None


# ============== LIST RESPONSE SCHEMAS ==============

class RoleListResponse(BaseModel):
    """Paginated role list response"""
    items: List[RoleResponse]
    total: int
    page: int
    page_size: int


class PermissionListResponse(BaseModel):
    """Paginated permission list response"""
    items: List[PermissionResponse]
    total: int
    page: int
    page_size: int


class UserSessionListResponse(BaseModel):
    """Paginated user session list response"""
    items: List[UserSessionResponse]
    total: int
    page: int
    page_size: int


class AuditLogListResponse(BaseModel):
    """Paginated audit log list response"""
    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int


# ============== PERMISSION CHECK SCHEMAS ==============

class PermissionCheckRequest(BaseModel):
    """Schema for checking user permissions"""
    user_id: int
    permission_code: str
    action: str = "view"  # view, create, edit, delete


class PermissionCheckResponse(BaseModel):
    """Schema for permission check response"""
    allowed: bool
    permission_code: str
    action: str
    user_id: int
    roles: List[str] = []
    message: Optional[str] = None


# ============== BULK OPERATION SCHEMAS ==============

class BulkRolePermissionAssign(BaseModel):
    """Schema for bulk role-permission assignment"""
    role_id: int
    permissions: List[Dict[str, Any]]
    # Each permission: {"permission_id": 1, "can_view": true, "can_create": false, ...}


class BulkUserRoleAssign(BaseModel):
    """Schema for bulk user-role assignment"""
    user_ids: List[int]
    role_id: int
    assigned_by: Optional[int] = None


# ============== USER PERMISSIONS SUMMARY ==============

class UserPermissionsSummary(BaseModel):
    """Summary of all permissions for a user"""
    user_id: int
    roles: List[RoleResponse]
    permissions: Dict[str, Dict[str, bool]]
    # Format: {"permission_code": {"view": true, "create": false, "edit": true, "delete": false}}


class ModulePermissions(BaseModel):
    """Permissions grouped by module"""
    module: str
    permissions: List[PermissionResponse]


class PermissionsByModule(BaseModel):
    """All permissions organized by module"""
    modules: List[ModulePermissions]
