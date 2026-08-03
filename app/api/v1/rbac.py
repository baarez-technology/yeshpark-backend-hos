"""
RBAC (Role-Based Access Control) API endpoints.

Provides:
- GET  /roles              → list all roles with staff counts
- GET  /roles/{code}       → single role detail with permission matrix
- PUT  /roles/{code}/permissions → update a role's default permissions
- POST /roles/{code}/push  → push permissions to all staff with this role
- GET  /permissions        → list all permission modules
- PATCH /staff/{id}/permissions → update individual staff permissions
- POST /staff/{id}/resend-credentials → regenerate temp password and resend email
"""

from typing import List, Optional, Dict
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel
import json
import secrets
import string

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user, get_password_hash
from app.models.user import User
from app.models.staff import Staff
from app.models.rbac import Role, Permission, RolePermission, UserRole
from app.core.roles import check_access, VALID_STAFF_ROLES, ROLE_LABELS, ROLE_DEPARTMENT_MAP

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────

class ModulePermission(BaseModel):
    view: bool = False
    edit: bool = False
    delete: bool = False


class RolePermissionsPayload(BaseModel):
    """Full permission matrix for a role."""
    permissions: Dict[str, ModulePermission]  # {"dashboard": {"view": true, ...}, ...}


class RoleSummary(BaseModel):
    role_code: str
    role_name: str
    description: Optional[str] = None
    color: Optional[str] = None
    is_system_role: bool = True
    staff_count: int = 0
    department: Optional[str] = None


class RoleDetail(RoleSummary):
    permissions: Dict[str, ModulePermission] = {}


class StaffPermissionsUpdate(BaseModel):
    permissions: Dict[str, ModulePermission]


# ── Default Permission Templates (matches frontend rolePermissions.ts) ──

NONE = ModulePermission(view=False, edit=False, delete=False)
V    = ModulePermission(view=True, edit=False, delete=False)
VE   = ModulePermission(view=True, edit=True, delete=False)
VED  = ModulePermission(view=True, edit=True, delete=True)

DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, ModulePermission]] = {
    "admin": {m: VED for m in [
        "dashboard", "bookings", "guests", "rooms", "staff",
        "housekeeping", "maintenance", "aiAssistant", "revenueAI",
        "reputationAI", "crmAI", "reports", "settings",
    ]},
    "general_manager": {
        "dashboard": VE, "bookings": VED, "guests": VED, "rooms": VED,
        "staff": VE, "housekeeping": VE, "maintenance": VE,
        "aiAssistant": VE, "revenueAI": VE, "reputationAI": VE,
        "crmAI": VE, "reports": VED, "settings": V,
    },
    "front_office_manager": {
        "dashboard": V, "bookings": VED, "guests": VED, "rooms": VE,
        "staff": V, "housekeeping": V, "maintenance": NONE,
        "aiAssistant": VE, "revenueAI": V, "reputationAI": V,
        "crmAI": VED, "reports": V, "settings": NONE,
    },
    "duty_manager": {
        "dashboard": V, "bookings": VE, "guests": VE, "rooms": VE,
        "staff": V, "housekeeping": V, "maintenance": VE,
        "aiAssistant": VE, "revenueAI": NONE, "reputationAI": NONE,
        "crmAI": NONE, "reports": V, "settings": NONE,
    },
    "receptionist": {
        "dashboard": V, "bookings": VE, "guests": VE, "rooms": V,
        "staff": NONE, "housekeeping": NONE, "maintenance": NONE,
        "aiAssistant": V, "revenueAI": NONE, "reputationAI": NONE,
        "crmAI": NONE, "reports": NONE, "settings": NONE,
    },
    "reservation_manager": {
        "dashboard": V, "bookings": VED, "guests": VE, "rooms": VE,
        "staff": NONE, "housekeeping": NONE, "maintenance": NONE,
        "aiAssistant": VE, "revenueAI": V, "reputationAI": NONE,
        "crmAI": VE, "reports": V, "settings": NONE,
    },
    "housekeeping_manager": {
        "dashboard": V, "bookings": NONE, "guests": V, "rooms": VE,
        "staff": V, "housekeeping": VED, "maintenance": VE,
        "aiAssistant": V, "revenueAI": NONE, "reputationAI": NONE,
        "crmAI": NONE, "reports": V, "settings": NONE,
    },
    "housekeeper": {
        "dashboard": NONE, "bookings": NONE, "guests": NONE, "rooms": V,
        "staff": NONE, "housekeeping": VE, "maintenance": VE,
        "aiAssistant": V, "revenueAI": NONE, "reputationAI": NONE,
        "crmAI": NONE, "reports": NONE, "settings": NONE,
    },
    "revenue_manager": {
        "dashboard": V, "bookings": VE, "guests": V, "rooms": V,
        "staff": NONE, "housekeeping": NONE, "maintenance": NONE,
        "aiAssistant": V, "revenueAI": VED, "reputationAI": V,
        "crmAI": V, "reports": VED, "settings": NONE,
    },
    "accounts_manager": {
        "dashboard": V, "bookings": VE, "guests": VE, "rooms": NONE,
        "staff": NONE, "housekeeping": NONE, "maintenance": NONE,
        "aiAssistant": V, "revenueAI": V, "reputationAI": NONE,
        "crmAI": NONE, "reports": VED, "settings": NONE,
    },
}


# ── Helpers ────────────────────────────────────────────────────────────

def _get_default_perms(role_code: str) -> Dict[str, ModulePermission]:
    return DEFAULT_ROLE_PERMISSIONS.get(role_code, {})


def _user_permissions_dict(user: User) -> dict:
    """Parse the JSON permissions column into a dict."""
    if user.permissions:
        try:
            return json.loads(user.permissions) if isinstance(user.permissions, str) else user.permissions
        except Exception:
            pass
    return {}


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("/roles", response_model=List[RoleSummary])
async def list_roles(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """List all roles with active staff counts."""
    check_access(current_user, ["admin", "manager"], detail="Admin access required")

    roles_out = []
    for role_code in VALID_STAFF_ROLES:
        # Count active staff with this role
        count_result = await session.exec(
            select(func.count()).where(Staff.role == role_code, Staff.status == "active")
        )
        count = count_result.one_or_none() or 0

        roles_out.append(RoleSummary(
            role_code=role_code,
            role_name=ROLE_LABELS.get(role_code, role_code),
            is_system_role=True,
            staff_count=count,
            department=ROLE_DEPARTMENT_MAP.get(role_code),
        ))

    return roles_out


@router.get("/roles/{role_code}", response_model=RoleDetail)
async def get_role_detail(
    role_code: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Get a single role with its full permission matrix."""
    check_access(current_user, ["admin", "manager"], detail="Admin access required")

    if role_code not in VALID_STAFF_ROLES:
        raise HTTPException(status_code=404, detail=f"Role '{role_code}' not found")

    count_result = await session.exec(
        select(func.count()).where(Staff.role == role_code, Staff.status == "active")
    )
    count = count_result.one_or_none() or 0

    # Check if there's a customised template stored in the DB role
    db_role = (await session.exec(
        select(Role).where(Role.role_code == role_code)
    )).first()

    permissions = _get_default_perms(role_code)

    # If DB role exists, try to load persisted permissions
    if db_role:
        perms_result = await session.exec(
            select(RolePermission, Permission)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == db_role.id)
        )
        rows = perms_result.all()
        if rows:
            permissions = {}
            for rp, perm in rows:
                permissions[perm.permission_code] = ModulePermission(
                    view=rp.can_view,
                    edit=rp.can_edit,
                    delete=rp.can_delete,
                )

    return RoleDetail(
        role_code=role_code,
        role_name=ROLE_LABELS.get(role_code, role_code),
        is_system_role=True,
        staff_count=count,
        department=ROLE_DEPARTMENT_MAP.get(role_code),
        permissions={k: v for k, v in permissions.items()},
    )


@router.put("/roles/{role_code}/permissions")
async def update_role_permissions(
    role_code: str,
    payload: RolePermissionsPayload,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Update the default permission template for a role."""
    check_access(current_user, ["admin"], detail="Admin access required")

    if role_code not in VALID_STAFF_ROLES:
        raise HTTPException(status_code=404, detail=f"Role '{role_code}' not found")

    # Find or create RBAC role
    db_role = (await session.exec(select(Role).where(Role.role_code == role_code))).first()
    if not db_role:
        db_role = Role(
            role_code=role_code,
            role_name=ROLE_LABELS.get(role_code, role_code),
            is_system_role=True,
            is_active=True,
        )
        session.add(db_role)
        await session.commit()
        await session.refresh(db_role)

    # Delete existing role-permissions
    existing = await session.exec(
        select(RolePermission).where(RolePermission.role_id == db_role.id)
    )
    for rp in existing.all():
        await session.delete(rp)

    # Create new permission entries
    for module_code, perms in payload.permissions.items():
        perm = (await session.exec(
            select(Permission).where(Permission.permission_code == module_code)
        )).first()
        if not perm:
            perm = Permission(
                permission_code=module_code,
                permission_name=module_code.replace("_", " ").title(),
                module="core",
                is_active=True,
            )
            session.add(perm)
            await session.commit()
            await session.refresh(perm)

        session.add(RolePermission(
            role_id=db_role.id,
            permission_id=perm.id,
            can_view=perms.view,
            can_create=perms.edit,
            can_edit=perms.edit,
            can_delete=perms.delete,
        ))

    await session.commit()
    return {"message": f"Permissions updated for role '{role_code}'"}


@router.post("/roles/{role_code}/push")
async def push_role_permissions(
    role_code: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Push the role's default permissions to ALL active staff with this role."""
    check_access(current_user, ["admin"], detail="Admin access required")

    if role_code not in VALID_STAFF_ROLES:
        raise HTTPException(status_code=404, detail=f"Role '{role_code}' not found")

    # Resolve the permissions to push (DB-stored or hardcoded defaults)
    perms = _get_default_perms(role_code)
    db_role = (await session.exec(select(Role).where(Role.role_code == role_code))).first()
    if db_role:
        perms_result = await session.exec(
            select(RolePermission, Permission)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == db_role.id)
        )
        rows = perms_result.all()
        if rows:
            perms = {}
            for rp, perm in rows:
                perms[perm.permission_code] = ModulePermission(
                    view=rp.can_view,
                    edit=rp.can_edit,
                    delete=rp.can_delete,
                )

    # Serialize to JSON
    perms_json = json.dumps({k: v.model_dump() for k, v in perms.items()})

    # Find all users with this role
    users_result = await session.exec(
        select(User).where(User.role == role_code, User.is_active == True)
    )
    users = users_result.all()
    updated = 0
    for user in users:
        user.permissions = perms_json
        user.updated_at = datetime.utcnow()
        updated += 1

    await session.commit()
    return {"message": f"Pushed permissions to {updated} staff member(s) with role '{role_code}'"}


@router.get("/permissions")
async def list_permission_modules(
    current_user: User = Depends(get_current_user),
):
    """List all permission module codes."""
    check_access(current_user, ["admin", "manager"])
    modules = [
        {"code": "dashboard", "name": "Dashboard", "category": "core"},
        {"code": "bookings", "name": "Bookings", "category": "operations"},
        {"code": "guests", "name": "Guests", "category": "operations"},
        {"code": "rooms", "name": "Rooms", "category": "operations"},
        {"code": "staff", "name": "Staff", "category": "operations"},
        {"code": "housekeeping", "name": "Housekeeping", "category": "operations"},
        {"code": "maintenance", "name": "Maintenance", "category": "operations"},
        {"code": "aiAssistant", "name": "AI Assistant", "category": "advanced"},
        {"code": "revenueAI", "name": "Revenue AI", "category": "advanced"},
        {"code": "reputationAI", "name": "Reputation AI", "category": "advanced"},
        {"code": "crmAI", "name": "CRM AI", "category": "advanced"},
        {"code": "reports", "name": "Reports", "category": "analytics"},
        {"code": "settings", "name": "Settings", "category": "admin"},
    ]
    return modules


@router.patch("/staff/{staff_id}/permissions")
async def update_staff_permissions(
    staff_id: int,
    payload: StaffPermissionsUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Update individual staff member's permissions (override from role defaults)."""
    check_access(current_user, ["admin"], detail="Admin access required")

    staff = (await session.exec(select(Staff).where(Staff.id == staff_id))).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    user = await session.get(User, staff.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found")

    perms_json = json.dumps({k: v.model_dump() for k, v in payload.permissions.items()})
    user.permissions = perms_json
    user.updated_at = datetime.utcnow()
    await session.commit()

    return {"message": "Permissions updated", "staff_id": staff_id}


@router.post("/staff/{staff_id}/resend-credentials")
async def resend_staff_credentials(
    staff_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Regenerate temp password and resend welcome email (for expired credentials)."""
    check_access(current_user, ["admin", "manager"], detail="Admin access required")

    staff = (await session.exec(select(Staff).where(Staff.id == staff_id))).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    user = await session.get(User, staff.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User account not found")

    # Generate new temp password
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    new_temp = ''.join(secrets.choice(alphabet) for _ in range(14))

    user.hashed_password = get_password_hash(new_temp)
    user.must_reset_password = True
    user.first_login = True
    user.temp_password_expires_at = datetime.utcnow() + timedelta(hours=72)
    user.updated_at = datetime.utcnow()
    await session.commit()

    # Send email in background - doesn't block response
    from app.services.background_email import send_staff_welcome_email_bg
    background_tasks.add_task(
        send_staff_welcome_email_bg,
        to_email=staff.email,
        staff_name=staff.name,
        role=staff.role,
        department=staff.department or ROLE_DEPARTMENT_MAP.get(staff.role, ""),
        password=new_temp,
    )

    return {"message": f"New credentials sent to {staff.email}"}
