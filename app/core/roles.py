"""
Centralized role definitions and access-checking helpers.

The 10 granular staff roles map onto the legacy role names used by existing
endpoint guards so that both old-style (`"admin"`, `"manager"`, `"front_desk"`)
and new-style role values pass through correctly.
"""

from typing import List, Set, Dict

# ── All valid staff roles ─────────────────────────────────────────────────
VALID_STAFF_ROLES = {
    "admin",
    "general_manager",
    "front_office_manager",
    "duty_manager",
    "receptionist",
    "reservation_manager",
    "housekeeping_manager",
    "housekeeper",
    "revenue_manager",
    "accounts_manager",
}

# ── Legacy → new-role mapping ────────────────────────────────────────────
# Each legacy role name expands to the set of new granular roles that should
# be granted the same level of access.
_LEGACY_EXPANSION: Dict[str, Set[str]] = {
    "admin": {"admin"},
    "manager": {
        "admin", "general_manager", "front_office_manager", "duty_manager",
        "housekeeping_manager", "reservation_manager", "revenue_manager",
        "accounts_manager",
    },
    "front_desk": {
        "admin", "general_manager", "front_office_manager", "duty_manager",
        "receptionist", "reservation_manager",
    },
    "housekeeping": {
        "admin", "general_manager", "housekeeping_manager", "housekeeper",
    },
    "maintenance": {
        "admin", "general_manager", "duty_manager",
        "housekeeping_manager", "housekeeper",
    },
    "finance": {
        "admin", "general_manager", "revenue_manager", "accounts_manager",
    },
    "operations": {
        "admin", "general_manager", "front_office_manager", "duty_manager",
    },
    "management": {
        "admin", "general_manager",
    },
    "supervisor": {
        "admin", "general_manager", "front_office_manager",
        "housekeeping_manager", "duty_manager",
    },
    "staff": set(),   # generic — no elevated access
    "guest": set(),   # guests have no staff access
}

# ── New role → department mapping ────────────────────────────────────────
ROLE_DEPARTMENT_MAP = {
    "admin": "management",
    "general_manager": "management",
    "front_office_manager": "frontdesk",
    "duty_manager": "operations",
    "receptionist": "frontdesk",
    "reservation_manager": "reservations",
    "housekeeping_manager": "housekeeping",
    "housekeeper": "housekeeping",
    "revenue_manager": "revenue",
    "accounts_manager": "finance",
}

# ── New role → display label ─────────────────────────────────────────────
ROLE_LABELS = {
    "admin": "Administrator",
    "general_manager": "General Manager",
    "front_office_manager": "Front Office Manager",
    "duty_manager": "Duty Manager",
    "receptionist": "Receptionist (GSA)",
    "reservation_manager": "Reservation Manager",
    "housekeeping_manager": "Housekeeping Manager",
    "housekeeper": "Housekeeper",
    "revenue_manager": "Revenue Manager",
    "accounts_manager": "Accounts Manager",
}


def expand_allowed_roles(allowed_roles: List[str]) -> Set[str]:
    """
    Given a list of role names (legacy or new), return the full set of
    granular roles that should be granted access.

    Example:
        expand_allowed_roles(["admin", "manager", "front_desk"])
        →  {"admin", "general_manager", "front_office_manager", "duty_manager",
            "receptionist", "reservation_manager", "housekeeping_manager",
            "revenue_manager", "accounts_manager"}
    """
    expanded: Set[str] = set()
    for role in allowed_roles:
        if role in _LEGACY_EXPANSION:
            expanded.update(_LEGACY_EXPANSION[role])
        expanded.add(role)          # always include the literal value
    return expanded


def has_role_access(user_role: str, allowed_roles: List[str]) -> bool:
    """Check whether *user_role* is covered by *allowed_roles* (with expansion)."""
    return user_role in expand_allowed_roles(allowed_roles)


def is_admin_or_superuser(user) -> bool:
    """Quick check for admin-level access."""
    return user.is_superuser or user.role == "admin"


def check_access(user, allowed_roles: List[str], *, detail: str = "Access denied") -> None:
    """
    Raise HTTPException(403) if the user does not have access.
    Use in endpoints:  check_access(current_user, ["admin", "manager"])
    """
    if user.is_superuser:
        return
    if not has_role_access(user.role, allowed_roles):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=detail)
