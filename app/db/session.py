"""
Database session management for Glimmora Hotel Management System.

Supports both single-database mode (legacy) and multi-tenant mode.
Multi-tenant mode uses separate databases for each hotel tenant.
"""
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings


def _to_async_url(url: str) -> str:
    """Convert sync database URL to async format"""
    if url.startswith("sqlite:///") and "aiosqlite" not in url:
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    return url


# Legacy single-DB engine (for migration period and single-tenant mode)
ASYNC_DATABASE_URL = _to_async_url(settings.database_url)
engine = create_async_engine(ASYNC_DATABASE_URL, future=True, echo=False)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _add_missing_columns(connection):
    """Add columns that SQLite create_all won't add to existing tables."""
    import sqlalchemy as sa
    new_columns = [
        # users
        ("users", "must_reset_password", "BOOLEAN DEFAULT 0"),
        ("users", "first_login", "BOOLEAN DEFAULT 0"),
        ("users", "temp_password_expires_at", "DATETIME"),
        ("users", "permissions", "TEXT"),
        ("users", "hotel_code", "VARCHAR"),
        # staff
        ("staff", "personal_email", "VARCHAR"),
        ("staff", "shift_start", "TIME"),
        ("staff", "shift_end", "TIME"),
        ("staff", "clocked_in", "BOOLEAN DEFAULT 0"),
        ("staff", "clock_in_time", "DATETIME"),
        ("staff", "supervisor_id", "INTEGER"),
        ("staff", "supervisor_name", "VARCHAR"),
        # bookings
        ("bookings", "nightly_rate", "FLOAT"),
        ("bookings", "tax_rate", "FLOAT"),
        ("bookings", "do_not_move", "BOOLEAN DEFAULT 0"),
        ("bookings", "dnm_set_by", "INTEGER"),
        ("bookings", "dnm_set_at", "DATETIME"),
        ("bookings", "check_in_date", "DATETIME"),
        ("bookings", "check_out_date", "DATETIME"),
        ("bookings", "vip_flag", "BOOLEAN DEFAULT 0"),
        ("bookings", "number_of_guests", "INTEGER"),
        ("bookings", "upsells", "TEXT"),
        ("bookings", "discount_code", "VARCHAR"),
        ("bookings", "discount_amount", "FLOAT DEFAULT 0.0"),
        ("bookings", "commission_rate", "FLOAT"),
        ("bookings", "commission_amount", "FLOAT"),
        ("bookings", "net_revenue", "FLOAT"),
        ("bookings", "modification_count", "INTEGER DEFAULT 0"),
        # guests
        ("guests", "state", "VARCHAR"),
        ("guests", "avatar", "VARCHAR"),
        ("guests", "status", "VARCHAR"),
        ("guests", "emotion", "VARCHAR DEFAULT 'neutral'"),
        ("guests", "preferred_room_type", "VARCHAR"),
        ("guests", "notes", "TEXT"),
        # housekeeping_tasks
        ("housekeeping_tasks", "acceptance_status", "VARCHAR"),
        ("housekeeping_tasks", "decline_reason", "TEXT"),
        ("housekeeping_tasks", "accepted_at", "DATETIME"),
        ("housekeeping_tasks", "declined_at", "DATETIME"),
        ("housekeeping_tasks", "force_assigned", "BOOLEAN DEFAULT 0"),
        ("housekeeping_tasks", "force_assign_reason", "TEXT"),
        ("housekeeping_tasks", "force_assigned_by", "INTEGER"),
        # maintenancerequest
        ("maintenancerequest", "room_number", "VARCHAR"),
        ("maintenancerequest", "issue_type", "VARCHAR"),
        ("maintenancerequest", "estimated_completion", "DATETIME"),
        ("maintenancerequest", "ooo_category", "VARCHAR"),
        ("maintenancerequest", "room_block_id", "INTEGER"),
        ("maintenancerequest", "acceptance_status", "VARCHAR"),
        ("maintenancerequest", "decline_reason", "TEXT"),
        ("maintenancerequest", "accepted_at", "DATETIME"),
        ("maintenancerequest", "declined_at", "DATETIME"),
        ("maintenancerequest", "force_assigned", "BOOLEAN DEFAULT 0"),
        ("maintenancerequest", "force_assign_reason", "TEXT"),
        ("maintenancerequest", "force_assigned_by", "INTEGER"),
        # precheckin
        ("precheckin", "booking_id", "INTEGER"),
        # staffnotification
        ("staffnotification", "guest_id", "INTEGER"),
        ("staffnotification", "booking_id", "INTEGER"),
        ("staffnotification", "room_id", "INTEGER"),
        # foliolineitem — tax breakdown columns
        # nightaudit — Sprint 2 batch charge posting fields
        ("nightaudit", "room_charges_posted", "INTEGER DEFAULT 0"),
        ("nightaudit", "room_charge_revenue", "FLOAT DEFAULT 0.0"),
        ("nightaudit", "auto_checkouts", "INTEGER DEFAULT 0"),
        # foliolineitem — tax breakdown columns
        ("foliolineitem", "tax_category_id", "INTEGER"),
        ("foliolineitem", "tax_rate_pct", "FLOAT"),
        ("foliolineitem", "tax_amount", "FLOAT"),
        ("foliolineitem", "tax_component_1_name", "VARCHAR"),
        ("foliolineitem", "tax_component_1_pct", "FLOAT"),
        ("foliolineitem", "tax_component_1_amount", "FLOAT"),
        ("foliolineitem", "tax_component_2_name", "VARCHAR"),
        ("foliolineitem", "tax_component_2_pct", "FLOAT"),
        ("foliolineitem", "tax_component_2_amount", "FLOAT"),
        # folio — invoice immutability fields (Sprint 5)
        ("folio", "invoice_number", "VARCHAR"),
        ("folio", "is_settled", "BOOLEAN DEFAULT 0"),
        ("folio", "print_count", "INTEGER DEFAULT 0"),
        # Sprint 6 — guest management
        ("guests", "vip_level", "INTEGER"),
        ("guests", "profile_number", "VARCHAR"),
        # Sprint 6 — booking ETA/ETD + accompanying guests
        ("bookings", "expected_arrival_time", "VARCHAR"),
        ("bookings", "expected_departure_time", "VARCHAR"),
        ("bookings", "accompanying_guests", "TEXT"),
        # Sprint 6 — compound room statuses (F-03)
        ("rooms", "occupancy_status", "VARCHAR DEFAULT 'vacant'"),
        ("rooms", "cleaning_status", "VARCHAR DEFAULT 'clean'"),
        # Sprint 7A — transaction code on line items
        ("foliolineitem", "transaction_code", "VARCHAR"),
        # Sprint 7A — UPI ID on payments
        ("payment", "upi_id", "VARCHAR"),
        # Sprint 7C — cross-booking transfer source tracking
        ("foliolineitem", "source_booking_id", "INTEGER"),
        # FolioLineItem — voiding and transfer tracking
        ("foliolineitem", "is_voided", "BOOLEAN DEFAULT 0"),
        ("foliolineitem", "voided_by", "INTEGER"),
        ("foliolineitem", "voided_at", "DATETIME"),
        ("foliolineitem", "original_line_item_id", "INTEGER"),
        ("foliolineitem", "source_folio_id", "INTEGER"),
        # Sprint 7D — digital room key activation timing
        ("hotelconfig", "digital_key_activation_minutes", "INTEGER DEFAULT 60"),
        # Sprint 8 — multi-room booking
        ("bookings", "number_of_rooms", "INTEGER DEFAULT 1"),
        ("bookings", "parent_booking_id", "INTEGER"),
        # Admin AI Multi-Agent — session context tracking
        ("admin_ai_sessions", "context_summary", "TEXT"),
        ("admin_ai_sessions", "active_entities", "TEXT"),
        # Night Audit — Opera PMS statistics fields
        ("nightaudit", "adr", "FLOAT"),
        ("nightaudit", "revpar", "FLOAT"),
        ("nightaudit", "total_room_revenue", "FLOAT DEFAULT 0.0"),
        ("nightaudit", "total_fnb_revenue", "FLOAT DEFAULT 0.0"),
        ("nightaudit", "total_other_revenue", "FLOAT DEFAULT 0.0"),
        ("nightaudit", "total_tax_collected", "FLOAT DEFAULT 0.0"),
        ("nightaudit", "total_payments_received", "FLOAT DEFAULT 0.0"),
        ("nightaudit", "rooms_returned_from_ooo", "INTEGER DEFAULT 0"),
        ("nightaudit", "expired_auth_holds_count", "INTEGER DEFAULT 0"),
        ("nightaudit", "ar_postings_aged", "INTEGER DEFAULT 0"),
        ("nightaudit", "rooms_set_dirty", "INTEGER DEFAULT 0"),
        ("nightaudit", "procedure_log", "TEXT"),
        # Folio — missing columns
        ("folio", "booking_id", "INTEGER"),
        ("folio", "window_label", "VARCHAR DEFAULT 'A'"),
        ("folio", "folio_type", "VARCHAR DEFAULT 'guest'"),
        ("folio", "closed_at", "DATETIME"),
        ("folio", "closed_by", "INTEGER"),
        # Channel restrictions — original date range and grouping
        ("channel_restrictions", "date_range_start", "DATE"),
        ("channel_restrictions", "date_range_end", "DATE"),
        ("channel_restrictions", "group_id", "VARCHAR"),
    ]
    for table, column, col_type in new_columns:
        try:
            connection.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        except Exception:
            pass  # Column already exists


async def init_db() -> None:
    """Initialize legacy single database tables"""
    # Import all models to ensure they are registered with SQLModel metadata
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # Add new columns to existing tables (SQLite doesn't do this via create_all)
        await conn.run_sync(_add_missing_columns)


async def init_master_db() -> None:
    """Initialize master database tables (hotels registry, global users)"""
    from app.db.master_models import Hotel, GlobalUser
    from app.db.tenant_manager import tenant_manager

    async with tenant_manager.master_engine.begin() as conn:
        # Create only master database tables
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[Hotel.__table__, GlobalUser.__table__]
        )


async def init_hotel_db(hotel_code: str) -> None:
    """Initialize tables for a specific hotel database"""
    from app.db.tenant_manager import tenant_manager
    import app.models  # noqa: F401 - Import all models

    engine = await tenant_manager.get_engine(hotel_code)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


# ============ SESSION DEPENDENCIES ============

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Legacy: Get session for single-DB mode.

    Used during migration period and for routes that don't need tenant isolation.
    After full migration, this should only be used for development/testing.
    """
    async with async_session_maker() as session:
        yield session


async def get_tenant_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Get session for current tenant (from request context).

    When multi_tenant_enabled=false, falls back to legacy single-DB session
    so the app works without PostgreSQL / hotel provisioning.

    When multi_tenant_enabled=true, the hotel_code is extracted from the JWT
    token by TenantMiddleware and stored in request.state.hotel_code.

    Raises:
        HTTPException: If multi-tenant is enabled but no hotel context found (401)
    """
    # Single-tenant mode: use legacy SQLite/single-DB session
    if not settings.multi_tenant_enabled:
        async with async_session_maker() as session:
            yield session
        return

    from fastapi import HTTPException, status
    from app.db.tenant_manager import tenant_manager

    # Resolve hotel_code: middleware sets request.state.hotel_code from JWT,
    # but fall back to the X-Hotel-Code header directly so lookup-only routes
    # (guest-email-hint, guest-profile-summary, etc.) work without a JWT.
    hotel_code = getattr(request.state, 'hotel_code', None)
    if not hotel_code:
        raw = request.headers.get("X-Hotel-Code")
        if raw:
            hotel_code = raw.strip()
    if not hotel_code:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please login with your hotel credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async for session in tenant_manager.get_session(hotel_code):
        yield session


async def get_master_session() -> AsyncGenerator[AsyncSession, None]:
    """Get session for master database (hotel registry, global users)"""
    from app.db.tenant_manager import tenant_manager

    async with tenant_manager.master_session_maker() as session:
        yield session


@asynccontextmanager
async def get_async_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for getting async session (for scripts/seeds)."""
    async with async_session_maker() as session:
        yield session


@asynccontextmanager
async def get_tenant_session_context(hotel_code: str) -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for getting tenant session (for background jobs/scripts).

    Usage:
        async with get_tenant_session_context("marriott_mumbai") as session:
            # ... perform database operations
    """
    from app.db.tenant_manager import tenant_manager

    async for session in tenant_manager.get_session(hotel_code):
        yield session
