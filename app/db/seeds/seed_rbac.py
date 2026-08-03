"""
Seed script for Role-Based Access Control (RBAC) data.
Creates permissions, roles, role-permission mappings, and sample audit logs.
Does NOT create UserRole or UserSession (those are runtime-created).
"""
import json
from datetime import datetime, timedelta
import random
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.rbac import (
    Role,
    Permission,
    RolePermission,
    AuditLog,
)


async def seed_rbac_data(session: AsyncSession) -> dict:
    """
    Seed RBAC data including permissions, roles, role-permission mappings, and audit logs.

    Creates:
    - All Permission records (dashboard, bookings, guests, rooms, housekeeping, etc.)
    - Roles (Owner, Manager, Front Desk, Housekeeping, Finance, Staff)
    - RolePermission mappings with CRUD levels
    - Sample AuditLog entries

    Does NOT create:
    - UserRole (runtime-created when users are assigned roles)
    - UserSession (runtime-created during login)

    This function is idempotent - it checks for existing records before creating.

    Args:
        session: AsyncSession for database operations

    Returns:
        dict with counts of created records
    """
    print("=" * 60)
    print("Starting RBAC data seeding...")
    print("=" * 60)

    counts = {
        "permissions": 0,
        "roles": 0,
        "role_permissions": 0,
        "audit_logs": 0,
    }

    # ========== PERMISSIONS ==========
    print("\n[1/4] Creating permissions...")

    permissions_data = [
        # Core Features
        {
            "permission_code": "dashboard",
            "permission_name": "Dashboard",
            "module": "core",
            "description": "View main dashboard and key metrics",
        },
        {
            "permission_code": "bookings",
            "permission_name": "Bookings",
            "module": "core",
            "description": "Manage reservations and bookings",
        },
        {
            "permission_code": "guests",
            "permission_name": "Guests (CRM)",
            "module": "core",
            "description": "Access guest profiles and CRM",
        },
        {
            "permission_code": "rooms",
            "permission_name": "Rooms",
            "module": "core",
            "description": "View and manage room inventory",
        },
        # Operations
        {
            "permission_code": "housekeeping",
            "permission_name": "Housekeeping",
            "module": "operations",
            "description": "Manage cleaning and maintenance tasks",
        },
        {
            "permission_code": "staff",
            "permission_name": "Staff Management",
            "module": "operations",
            "description": "Manage team members and schedules",
        },
        # Analytics & Reports
        {
            "permission_code": "revenue",
            "permission_name": "Revenue & Analytics",
            "module": "analytics",
            "description": "View revenue reports and analytics",
        },
        {
            "permission_code": "reputation",
            "permission_name": "Reputation & Reviews",
            "module": "analytics",
            "description": "Manage reviews and reputation",
        },
        {
            "permission_code": "crm",
            "permission_name": "CRM",
            "module": "analytics",
            "description": "Advanced guest relationship management",
        },
        # Advanced Features
        {
            "permission_code": "ai",
            "permission_name": "AI Assistant",
            "module": "advanced",
            "description": "Access Glimmora AI features",
        },
        # Administration
        {
            "permission_code": "settings",
            "permission_name": "Settings",
            "module": "admin",
            "description": "Access system settings",
        },
        {
            "permission_code": "integrations",
            "permission_name": "Integrations",
            "module": "admin",
            "description": "Manage third-party integrations",
        },
        # Additional granular permissions
        {
            "permission_code": "reports",
            "permission_name": "Reports",
            "module": "analytics",
            "description": "Generate and export reports",
        },
        {
            "permission_code": "maintenance",
            "permission_name": "Maintenance",
            "module": "operations",
            "description": "Manage maintenance requests and work orders",
        },
        {
            "permission_code": "billing",
            "permission_name": "Billing & Invoices",
            "module": "core",
            "description": "Manage billing, invoices, and payments",
        },
        {
            "permission_code": "promotions",
            "permission_name": "Promotions",
            "module": "analytics",
            "description": "Create and manage promotional campaigns",
        },
    ]

    permission_objects = {}
    for perm_data in permissions_data:
        existing = (await session.exec(
            select(Permission).where(Permission.permission_code == perm_data["permission_code"])
        )).first()

        if existing:
            permission_objects[perm_data["permission_code"]] = existing
            print(f"  -> Permission already exists: {perm_data['permission_name']}")
            continue

        permission = Permission(
            permission_code=perm_data["permission_code"],
            permission_name=perm_data["permission_name"],
            module=perm_data["module"],
            description=perm_data["description"],
            is_active=True,
        )
        session.add(permission)
        await session.flush()
        permission_objects[perm_data["permission_code"]] = permission
        counts["permissions"] += 1
        print(f"  + Created permission: {perm_data['permission_name']} ({perm_data['module']})")

    await session.commit()
    print(f"  Total permissions created: {counts['permissions']}")

    # ========== ROLES ==========
    print("\n[2/4] Creating roles...")

    roles_data = [
        {
            "role_code": "owner",
            "role_name": "Property Owner",
            "description": "Full system access with all permissions",
            "color": "#8B5CF6",
            "is_system_role": True,
        },
        {
            "role_code": "manager",
            "role_name": "Manager",
            "description": "Manage operations, staff, and reports",
            "color": "#EC4899",
            "is_system_role": True,
        },
        {
            "role_code": "front_desk",
            "role_name": "Front Desk",
            "description": "Handle check-ins, bookings, and guest services",
            "color": "#3B82F6",
            "is_system_role": True,
        },
        {
            "role_code": "housekeeping",
            "role_name": "Housekeeping",
            "description": "Manage room cleaning and maintenance",
            "color": "#10B981",
            "is_system_role": True,
        },
        {
            "role_code": "finance",
            "role_name": "Finance",
            "description": "Access to revenue and billing",
            "color": "#F59E0B",
            "is_system_role": True,
        },
        {
            "role_code": "staff",
            "role_name": "Staff",
            "description": "Basic staff access",
            "color": "#6B7280",
            "is_system_role": True,
        },
        # Additional roles
        {
            "role_code": "maintenance",
            "role_name": "Maintenance",
            "description": "Handle maintenance requests and repairs",
            "color": "#EF4444",
            "is_system_role": True,
        },
        {
            "role_code": "concierge",
            "role_name": "Concierge",
            "description": "Guest services and special requests",
            "color": "#14B8A6",
            "is_system_role": False,
        },
    ]

    role_objects = {}
    for role_data in roles_data:
        existing = (await session.exec(
            select(Role).where(Role.role_code == role_data["role_code"])
        )).first()

        if existing:
            role_objects[role_data["role_code"]] = existing
            print(f"  -> Role already exists: {role_data['role_name']}")
            continue

        role = Role(
            role_code=role_data["role_code"],
            role_name=role_data["role_name"],
            description=role_data["description"],
            color=role_data["color"],
            is_system_role=role_data["is_system_role"],
            is_active=True,
        )
        session.add(role)
        await session.flush()
        role_objects[role_data["role_code"]] = role
        counts["roles"] += 1
        print(f"  + Created role: {role_data['role_name']}")

    await session.commit()
    print(f"  Total roles created: {counts['roles']}")

    # ========== ROLE PERMISSIONS ==========
    print("\n[3/4] Creating role-permission mappings...")

    # Define permission mappings for each role
    # Format: {permission_code: (can_view, can_create, can_edit, can_delete)}
    role_permission_mappings = {
        "owner": {
            # Owner has full access to everything
            "dashboard": (True, True, True, True),
            "bookings": (True, True, True, True),
            "guests": (True, True, True, True),
            "rooms": (True, True, True, True),
            "housekeeping": (True, True, True, True),
            "staff": (True, True, True, True),
            "revenue": (True, True, True, True),
            "reputation": (True, True, True, True),
            "crm": (True, True, True, True),
            "ai": (True, True, True, True),
            "settings": (True, True, True, True),
            "integrations": (True, True, True, True),
            "reports": (True, True, True, True),
            "maintenance": (True, True, True, True),
            "billing": (True, True, True, True),
            "promotions": (True, True, True, True),
        },
        "manager": {
            # Manager has broad access but limited admin
            "dashboard": (True, True, True, True),
            "bookings": (True, True, True, True),
            "guests": (True, True, True, True),
            "rooms": (True, True, True, True),
            "housekeeping": (True, True, True, True),
            "staff": (True, True, True, False),  # Can't delete staff
            "revenue": (True, True, True, False),
            "reputation": (True, True, True, True),
            "crm": (True, True, True, True),
            "ai": (True, True, True, False),
            "settings": (True, False, True, False),  # Can view and edit settings
            "integrations": (True, False, False, False),  # View only
            "reports": (True, True, True, False),
            "maintenance": (True, True, True, True),
            "billing": (True, True, True, False),
            "promotions": (True, True, True, True),
        },
        "front_desk": {
            # Front desk focuses on guest-facing operations
            "dashboard": (True, False, False, False),
            "bookings": (True, True, True, False),  # No delete
            "guests": (True, True, True, False),
            "rooms": (True, True, True, False),
            "housekeeping": (True, False, False, False),  # View only
            "staff": (False, False, False, False),  # No access
            "revenue": (False, False, False, False),
            "reputation": (True, False, False, False),  # View only
            "crm": (True, True, False, False),  # View and create
            "ai": (True, True, False, False),
            "settings": (False, False, False, False),
            "integrations": (False, False, False, False),
            "reports": (True, False, False, False),
            "maintenance": (True, True, False, False),  # Can report issues
            "billing": (True, True, True, False),
            "promotions": (True, False, False, False),
        },
        "housekeeping": {
            # Housekeeping focuses on room status and tasks
            "dashboard": (False, False, False, False),
            "bookings": (False, False, False, False),
            "guests": (False, False, False, False),
            "rooms": (True, False, True, False),  # View and update status
            "housekeeping": (True, True, True, False),
            "staff": (False, False, False, False),
            "revenue": (False, False, False, False),
            "reputation": (False, False, False, False),
            "crm": (False, False, False, False),
            "ai": (False, False, False, False),
            "settings": (False, False, False, False),
            "integrations": (False, False, False, False),
            "reports": (False, False, False, False),
            "maintenance": (True, True, False, False),  # Can report maintenance
            "billing": (False, False, False, False),
            "promotions": (False, False, False, False),
        },
        "finance": {
            # Finance focuses on revenue and billing
            "dashboard": (True, False, False, False),
            "bookings": (True, False, False, False),  # View only for reconciliation
            "guests": (True, False, False, False),
            "rooms": (False, False, False, False),
            "housekeeping": (False, False, False, False),
            "staff": (False, False, False, False),
            "revenue": (True, True, True, False),
            "reputation": (False, False, False, False),
            "crm": (False, False, False, False),
            "ai": (False, False, False, False),
            "settings": (False, False, False, False),
            "integrations": (False, False, False, False),
            "reports": (True, True, True, False),
            "maintenance": (False, False, False, False),
            "billing": (True, True, True, True),
            "promotions": (True, True, False, False),  # View and create
        },
        "staff": {
            # Basic staff has minimal access
            "dashboard": (True, False, False, False),
            "bookings": (False, False, False, False),
            "guests": (False, False, False, False),
            "rooms": (False, False, False, False),
            "housekeeping": (False, False, False, False),
            "staff": (False, False, False, False),
            "revenue": (False, False, False, False),
            "reputation": (False, False, False, False),
            "crm": (False, False, False, False),
            "ai": (False, False, False, False),
            "settings": (False, False, False, False),
            "integrations": (False, False, False, False),
            "reports": (False, False, False, False),
            "maintenance": (False, False, False, False),
            "billing": (False, False, False, False),
            "promotions": (False, False, False, False),
        },
        "maintenance": {
            # Maintenance focuses on work orders and room maintenance
            "dashboard": (False, False, False, False),
            "bookings": (False, False, False, False),
            "guests": (False, False, False, False),
            "rooms": (True, False, True, False),  # View and update status
            "housekeeping": (True, False, False, False),  # View only
            "staff": (False, False, False, False),
            "revenue": (False, False, False, False),
            "reputation": (False, False, False, False),
            "crm": (False, False, False, False),
            "ai": (False, False, False, False),
            "settings": (False, False, False, False),
            "integrations": (False, False, False, False),
            "reports": (False, False, False, False),
            "maintenance": (True, True, True, False),
            "billing": (False, False, False, False),
            "promotions": (False, False, False, False),
        },
        "concierge": {
            # Concierge focuses on guest services
            "dashboard": (True, False, False, False),
            "bookings": (True, True, True, False),
            "guests": (True, True, True, False),
            "rooms": (True, False, False, False),
            "housekeeping": (True, True, False, False),  # Can request housekeeping
            "staff": (False, False, False, False),
            "revenue": (False, False, False, False),
            "reputation": (True, True, True, False),
            "crm": (True, True, True, False),
            "ai": (True, True, False, False),
            "settings": (False, False, False, False),
            "integrations": (False, False, False, False),
            "reports": (True, False, False, False),
            "maintenance": (True, True, False, False),
            "billing": (True, True, False, False),
            "promotions": (True, False, False, False),
        },
    }

    for role_code, permissions in role_permission_mappings.items():
        role = role_objects.get(role_code)
        if not role:
            continue

        for perm_code, (can_view, can_create, can_edit, can_delete) in permissions.items():
            permission = permission_objects.get(perm_code)
            if not permission:
                continue

            # Skip if no access at all
            if not any([can_view, can_create, can_edit, can_delete]):
                continue

            # Check if mapping exists
            existing = (await session.exec(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id
                )
            )).first()

            if existing:
                continue

            role_permission = RolePermission(
                role_id=role.id,
                permission_id=permission.id,
                can_view=can_view,
                can_create=can_create,
                can_edit=can_edit,
                can_delete=can_delete,
            )
            session.add(role_permission)
            counts["role_permissions"] += 1

    await session.commit()
    print(f"  Total role-permission mappings created: {counts['role_permissions']}")

    # ========== AUDIT LOGS ==========
    print("\n[4/4] Creating sample audit log entries...")

    # Sample audit log entries for demo purposes
    audit_entries = [
        # Login events
        {
            "user_id": 1,
            "action_type": "login",
            "entity_type": "session",
            "entity_id": None,
            "old_values": None,
            "new_values": json.dumps({"session_id": "sess_abc123", "login_method": "email"}),
            "ip_address": "192.168.1.100",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        },
        {
            "user_id": 2,
            "action_type": "login",
            "entity_type": "session",
            "entity_id": None,
            "old_values": None,
            "new_values": json.dumps({"session_id": "sess_def456", "login_method": "email"}),
            "ip_address": "192.168.1.101",
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
        },
        # Booking events
        {
            "user_id": 2,
            "action_type": "create",
            "entity_type": "booking",
            "entity_id": 1001,
            "old_values": None,
            "new_values": json.dumps({
                "confirmation_code": "GLM123456",
                "guest_name": "John Smith",
                "room_number": "501",
                "check_in": "2025-01-15",
                "check_out": "2025-01-18",
            }),
            "ip_address": "192.168.1.101",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        },
        {
            "user_id": 2,
            "action_type": "update",
            "entity_type": "booking",
            "entity_id": 1001,
            "old_values": json.dumps({"check_out": "2025-01-18"}),
            "new_values": json.dumps({"check_out": "2025-01-20"}),
            "ip_address": "192.168.1.101",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        },
        # Guest events
        {
            "user_id": 3,
            "action_type": "create",
            "entity_type": "guest",
            "entity_id": 201,
            "old_values": None,
            "new_values": json.dumps({
                "name": "Sarah Johnson",
                "email": "sarah.johnson@email.com",
                "phone": "+1-555-123-4567",
            }),
            "ip_address": "192.168.1.102",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/121.0",
        },
        # Room status changes
        {
            "user_id": 4,
            "action_type": "update",
            "entity_type": "room",
            "entity_id": 501,
            "old_values": json.dumps({"status": "dirty"}),
            "new_values": json.dumps({"status": "clean"}),
            "ip_address": "192.168.1.103",
            "user_agent": "Glimmora Staff App/1.0 (Android 13)",
        },
        {
            "user_id": 4,
            "action_type": "update",
            "entity_type": "room",
            "entity_id": 502,
            "old_values": json.dumps({"status": "dirty"}),
            "new_values": json.dumps({"status": "inspected"}),
            "ip_address": "192.168.1.103",
            "user_agent": "Glimmora Staff App/1.0 (Android 13)",
        },
        # Role assignment
        {
            "user_id": 1,
            "action_type": "create",
            "entity_type": "user_role",
            "entity_id": 5,
            "old_values": None,
            "new_values": json.dumps({
                "user_id": 10,
                "role_code": "front_desk",
                "assigned_by": 1,
            }),
            "ip_address": "192.168.1.100",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        },
        # Settings change
        {
            "user_id": 1,
            "action_type": "update",
            "entity_type": "settings",
            "entity_id": 1,
            "old_values": json.dumps({"check_in_time": "15:00"}),
            "new_values": json.dumps({"check_in_time": "14:00"}),
            "ip_address": "192.168.1.100",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        },
        # Report export
        {
            "user_id": 5,
            "action_type": "export",
            "entity_type": "report",
            "entity_id": None,
            "old_values": None,
            "new_values": json.dumps({
                "report_type": "revenue_summary",
                "date_range": "2024-12-01 to 2024-12-31",
                "format": "xlsx",
            }),
            "ip_address": "192.168.1.104",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        },
        # Logout event
        {
            "user_id": 1,
            "action_type": "logout",
            "entity_type": "session",
            "entity_id": None,
            "old_values": json.dumps({"session_id": "sess_abc123"}),
            "new_values": None,
            "ip_address": "192.168.1.100",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        },
        # Maintenance request
        {
            "user_id": 4,
            "action_type": "create",
            "entity_type": "maintenance_request",
            "entity_id": 301,
            "old_values": None,
            "new_values": json.dumps({
                "room_id": 503,
                "issue": "AC not cooling",
                "priority": "high",
            }),
            "ip_address": "192.168.1.103",
            "user_agent": "Glimmora Staff App/1.0 (Android 13)",
        },
        # Promotion created
        {
            "user_id": 1,
            "action_type": "create",
            "entity_type": "promotion",
            "entity_id": 101,
            "old_values": None,
            "new_values": json.dumps({
                "code": "SUMMER25",
                "discount_type": "percentage",
                "discount_value": 25,
            }),
            "ip_address": "192.168.1.100",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        },
        # Check-in event
        {
            "user_id": 3,
            "action_type": "update",
            "entity_type": "booking",
            "entity_id": 1002,
            "old_values": json.dumps({"status": "booked"}),
            "new_values": json.dumps({"status": "checked_in", "actual_check_in": "2025-01-06T14:23:00"}),
            "ip_address": "192.168.1.102",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/121.0",
        },
        # Check-out event
        {
            "user_id": 3,
            "action_type": "update",
            "entity_type": "booking",
            "entity_id": 1000,
            "old_values": json.dumps({"status": "checked_in"}),
            "new_values": json.dumps({"status": "checked_out", "actual_check_out": "2025-01-06T11:05:00"}),
            "ip_address": "192.168.1.102",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/121.0",
        },
    ]

    for i, entry_data in enumerate(audit_entries):
        # Spread entries over the past 7 days
        days_ago = i % 7
        hours_ago = (i * 3) % 24
        created_at = datetime.utcnow() - timedelta(days=days_ago, hours=hours_ago)

        # Check for duplicates (based on action_type, entity_type, entity_id, and approximate time)
        existing = (await session.exec(
            select(AuditLog).where(
                AuditLog.user_id == entry_data["user_id"],
                AuditLog.action_type == entry_data["action_type"],
                AuditLog.entity_type == entry_data["entity_type"],
                AuditLog.entity_id == entry_data["entity_id"],
            )
        )).first()

        if existing:
            continue

        audit_log = AuditLog(
            user_id=entry_data["user_id"],
            action_type=entry_data["action_type"],
            entity_type=entry_data["entity_type"],
            entity_id=entry_data["entity_id"],
            old_values=entry_data["old_values"],
            new_values=entry_data["new_values"],
            ip_address=entry_data["ip_address"],
            user_agent=entry_data["user_agent"],
            created_at=created_at,
        )
        session.add(audit_log)
        counts["audit_logs"] += 1

    await session.commit()
    print(f"  Total audit log entries created: {counts['audit_logs']}")

    # ========== SUMMARY ==========
    print("\n" + "=" * 60)
    print("RBAC data seeding completed!")
    print("=" * 60)
    print(f"\nSummary:")
    print(f"  - Permissions: {counts['permissions']}")
    print(f"  - Roles: {counts['roles']}")
    print(f"  - Role-Permission mappings: {counts['role_permissions']}")
    print(f"  - Audit log entries: {counts['audit_logs']}")
    print("\nRole Permission Summary:")
    for role_code, role in role_objects.items():
        perm_count = len([p for p in role_permission_mappings.get(role_code, {}).values() if any(p)])
        print(f"  - {role.role_name}: {perm_count} permissions configured")
    print("=" * 60)

    return counts


# Standalone execution
if __name__ == "__main__":
    import asyncio
    from app.db.session import async_session_maker, init_db

    async def main():
        await init_db()
        async with async_session_maker() as session:
            await seed_rbac_data(session)

    asyncio.run(main())
