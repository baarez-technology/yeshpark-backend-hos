"""
Inventory Management API
Consolidated endpoint for inventory management operations.
Handles rooms, rates, availability, restrictions, and OTA sync.
"""

from typing import List, Optional, Dict, Any
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, AliasChoices

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.inventory import (
    RoomType, Room, RatePlan, DailyAvailability, DailyRate,
    InventorySyncQueue, PromoCode, RoomBlock
)
from app.models.channel_manager import (
    OTAConnection as OTAChannel, OTARoomMapping, SyncLog as OTASyncLog
)
from app.models.user import User

router = APIRouter()


# ============================================
# SCHEMAS
# ============================================

class RoomTypeResponse(BaseModel):
    id: int
    name: str
    slug: str
    category: Optional[str]
    description: str
    base_price: float
    max_guests: int
    total_rooms: int
    amenities: Optional[List[str]]
    images: Optional[List[str]]
    is_active: bool


class DailyRateUpdate(BaseModel):
    room_type_id: int
    rate_plan_id: int
    date: date
    rate: float
    reason: Optional[str] = None


class BulkRateUpdate(BaseModel):
    room_type_id: int
    rate_plan_id: int
    start_date: date
    end_date: date
    rate: float
    reason: Optional[str] = None


class OTAChannelResponse(BaseModel):
    id: int
    code: str
    name: str
    logo_url: Optional[str]
    is_active: bool
    is_connected: bool
    sync_enabled: bool
    last_sync_at: Optional[datetime]
    last_sync_status: Optional[str]
    commission_percent: float


class OTAChannelCreate(BaseModel):
    code: str
    name: str
    logo_url: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_key: Optional[str] = None
    commission_percent: float = 15.0


class OTARoomMappingCreate(BaseModel):
    ota_channel_id: int
    room_type_id: int
    ota_room_code: str
    ota_room_name: Optional[str] = None
    ota_rate_plan_code: Optional[str] = None


class InventoryStateResponse(BaseModel):
    room_types: List[Dict[str, Any]]
    rate_plans: List[Dict[str, Any]]
    promotions: List[Dict[str, Any]]
    ota_channels: List[Dict[str, Any]]
    sync_status: Dict[str, Any]


class AvailabilityGridCell(BaseModel):
    date: str
    room_type_id: int
    total: int
    sold: int
    blocked: int
    available: int
    rate: Optional[float]
    min_stay: int
    closed_to_arrival: bool
    closed_to_departure: bool
    is_closed: bool


class RateGridCell(BaseModel):
    date: str
    room_type_id: int
    rate_plan_id: int
    base_rate: float
    override_rate: Optional[float]
    effective_rate: float


# ============================================
# HELPER FUNCTIONS
# ============================================

async def get_room_count_for_type(session: AsyncSession, room_type_id: int) -> int:
    """Get total room count for a room type."""
    stmt = select(func.count(Room.id)).where(Room.room_type_id == room_type_id)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def calculate_availability(
    session: AsyncSession,
    room_type_id: int,
    target_date: date
) -> Dict[str, int]:
    """Calculate availability for a room type on a specific date."""
    from app.models.reservations import Booking, Reservation

    # Total rooms
    total_stmt = select(func.count(Room.id)).where(
        and_(Room.room_type_id == room_type_id, Room.status != "out_of_service")
    )
    total_result = await session.execute(total_stmt)
    total = total_result.scalar() or 0

    # Sold (checked_in)
    sold_stmt = select(func.count(Booking.id)).where(
        and_(
            Booking.room_type_id == room_type_id,
            Booking.arrival_date <= target_date,
            Booking.departure_date > target_date,
            Booking.status == "checked_in"
        )
    )
    sold_result = await session.execute(sold_stmt)
    sold = sold_result.scalar() or 0

    # Blocked
    blocked_stmt = select(func.sum(RoomBlock.quantity)).where(
        and_(
            RoomBlock.room_type_id == room_type_id,
            RoomBlock.start_date <= target_date,
            RoomBlock.end_date >= target_date,
            RoomBlock.status == "active"
        )
    )
    blocked_result = await session.execute(blocked_stmt)
    blocked = blocked_result.scalar() or 0

    available = max(0, total - sold - blocked)

    return {
        "total": total,
        "sold": sold,
        "blocked": blocked,
        "available": available
    }


# ============================================
# INVENTORY STATE ENDPOINT
# ============================================

@router.get("/state", response_model=InventoryStateResponse)
async def get_inventory_state(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get complete inventory state for frontend InventoryContext.
    Returns room types, rate plans, promotions, OTA channels, and sync status.
    """
    import json

    # Get room types
    room_types_stmt = select(RoomType).where(RoomType.is_active == True)
    room_types_result = await session.execute(room_types_stmt)
    room_types = room_types_result.scalars().all()

    room_types_data = []
    for rt in room_types:
        total_rooms = await get_room_count_for_type(session, rt.id)
        amenities = []
        images = []
        if rt.amenities:
            try:
                amenities = json.loads(rt.amenities) if isinstance(rt.amenities, str) else rt.amenities
            except:
                pass
        if rt.images:
            try:
                images = json.loads(rt.images) if isinstance(rt.images, str) else rt.images
            except:
                pass

        room_types_data.append({
            "id": rt.id,
            "name": rt.name,
            "slug": rt.slug,
            "category": rt.category,
            "description": rt.description,
            "base_price": rt.base_price,
            "max_guests": rt.max_guests,
            "total_rooms": total_rooms,
            "amenities": amenities,
            "images": images,
            "is_active": rt.is_active
        })

    # Get rate plans
    rate_plans_stmt = select(RatePlan).where(RatePlan.is_active == True)
    rate_plans_result = await session.execute(rate_plans_stmt)
    rate_plans = rate_plans_result.scalars().all()

    rate_plans_data = [
        {
            "id": rp.id,
            "code": rp.code,
            "name": rp.name,
            "description": rp.description,
            "plan_type": rp.plan_type,
            "base_price": rp.base_price,
            "currency": rp.currency,
            "is_active": rp.is_active
        }
        for rp in rate_plans
    ]

    # Get active promotions
    today = date.today()
    promos_stmt = select(PromoCode).where(
        and_(
            PromoCode.is_active == True,
            PromoCode.valid_until >= today
        )
    )
    promos_result = await session.execute(promos_stmt)
    promos = promos_result.scalars().all()

    promos_data = [
        {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "description": p.description,
            "discount_type": p.discount_type,
            "discount_value": p.discount_value,
            "valid_from": p.valid_from.isoformat(),
            "valid_until": p.valid_until.isoformat(),
            "usage_count": p.usage_count,
            "usage_limit": p.usage_limit,
            "is_active": p.is_active
        }
        for p in promos
    ]

    # Get OTA channels (using OTAConnection model)
    ota_stmt = select(OTAChannel).where(OTAChannel.is_active == True)
    ota_result = await session.execute(ota_stmt)
    ota_channels = ota_result.scalars().all()

    ota_data = [
        {
            "id": ota.id,
            "code": ota.ota_code,
            "name": ota.ota_name,
            "logo_url": ota.logo_url,
            "is_connected": ota.connection_status == "connected",
            "sync_enabled": ota.auto_sync_enabled,
            "last_sync_at": ota.last_sync_at.isoformat() if ota.last_sync_at else None,
            "last_sync_status": ota.connection_status,
            "commission_percent": ota.commission_rate or 0.0
        }
        for ota in ota_channels
    ]

    # Get sync status
    pending_stmt = select(func.count(InventorySyncQueue.id)).where(
        InventorySyncQueue.status == "pending"
    )
    pending_result = await session.execute(pending_stmt)
    pending_count = pending_result.scalar() or 0

    last_sync_stmt = select(OTASyncLog).order_by(OTASyncLog.started_at.desc()).limit(1)
    last_sync_result = await session.execute(last_sync_stmt)
    last_sync = last_sync_result.scalar_one_or_none()

    sync_status = {
        "pending_syncs": pending_count,
        "last_sync_at": last_sync.started_at.isoformat() if last_sync else None,
        "last_sync_status": last_sync.status if last_sync else None
    }

    return InventoryStateResponse(
        room_types=room_types_data,
        rate_plans=rate_plans_data,
        promotions=promos_data,
        ota_channels=ota_data,
        sync_status=sync_status
    )


# ============================================
# AVAILABILITY GRID ENDPOINTS
# ============================================

@router.get("/availability-grid")
async def get_availability_grid(
    start_date: date = Query(..., validation_alias=AliasChoices("startDate", "start_date")),
    end_date: date = Query(..., validation_alias=AliasChoices("endDate", "end_date")),
    room_type_id: Optional[int] = Query(None, validation_alias=AliasChoices("roomTypeId", "room_type_id")),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get availability grid for date range. Query params: startDate/endDate (or start_date/end_date), optional roomTypeId."""

    # Get room types
    room_types_stmt = select(RoomType).where(RoomType.is_active == True)
    if room_type_id:
        room_types_stmt = room_types_stmt.where(RoomType.id == room_type_id)
    room_types_result = await session.execute(room_types_stmt)
    room_types = room_types_result.scalars().all()

    grid = []
    current_date = start_date

    while current_date <= end_date:
        for rt in room_types:
            # Get availability
            avail = await calculate_availability(session, rt.id, current_date)

            # Get daily availability record for restrictions
            daily_stmt = select(DailyAvailability).where(
                and_(
                    DailyAvailability.room_type_id == rt.id,
                    DailyAvailability.date == current_date
                )
            )
            daily_result = await session.execute(daily_stmt)
            daily_avail = daily_result.scalar_one_or_none()

            grid.append({
                "date": current_date.isoformat(),
                "room_type_id": rt.id,
                "room_type_name": rt.name,
                "total": avail["total"],
                "sold": avail["sold"],
                "blocked": avail["blocked"],
                "available": avail["available"],
                "rate": daily_avail.base_rate if daily_avail else rt.base_price,
                "min_stay": daily_avail.min_stay if daily_avail else 1,
                "max_stay": daily_avail.max_stay if daily_avail else None,
                "closed_to_arrival": daily_avail.closed_to_arrival if daily_avail else False,
                "closed_to_departure": daily_avail.closed_to_departure if daily_avail else False,
                "is_closed": daily_avail.is_closed if daily_avail else False
            })

        current_date += timedelta(days=1)

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "grid": grid
    }


@router.post("/availability-grid/update")
async def update_availability(
    room_type_id: int,
    target_date: date,
    is_closed: Optional[bool] = None,
    min_stay: Optional[int] = None,
    max_stay: Optional[int] = None,
    closed_to_arrival: Optional[bool] = None,
    closed_to_departure: Optional[bool] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update availability restrictions for a specific date."""

    # Get or create daily availability record
    stmt = select(DailyAvailability).where(
        and_(
            DailyAvailability.room_type_id == room_type_id,
            DailyAvailability.date == target_date
        )
    )
    result = await session.execute(stmt)
    daily_avail = result.scalar_one_or_none()

    if not daily_avail:
        # Get room type for base rate
        rt = await session.get(RoomType, room_type_id)
        if not rt:
            raise HTTPException(status_code=404, detail="Room type not found")

        avail = await calculate_availability(session, room_type_id, target_date)
        daily_avail = DailyAvailability(
            room_type_id=room_type_id,
            date=target_date,
            total_rooms=avail["total"],
            sold=avail["sold"],
            blocked=avail["blocked"],
            available=avail["available"],
            base_rate=rt.base_price
        )
        session.add(daily_avail)

    # Apply updates
    if is_closed is not None:
        daily_avail.is_closed = is_closed
    if min_stay is not None:
        daily_avail.min_stay = min_stay
    if max_stay is not None:
        daily_avail.max_stay = max_stay
    if closed_to_arrival is not None:
        daily_avail.closed_to_arrival = closed_to_arrival
    if closed_to_departure is not None:
        daily_avail.closed_to_departure = closed_to_departure

    daily_avail.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(daily_avail)

    # Queue sync to OTAs
    sync_item = InventorySyncQueue(
        room_type_id=room_type_id,
        sync_type="restrictions",
        date=target_date,
        change_type="update",
        changed_by=current_user.id
    )
    session.add(sync_item)
    await session.commit()

    return {"success": True, "message": "Availability updated"}


# ============================================
# RATE GRID ENDPOINTS
# ============================================

@router.get("/rate-grid")
async def get_rate_grid(
    start_date: date = Query(...),
    end_date: date = Query(...),
    room_type_id: Optional[int] = Query(None),
    rate_plan_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get rate grid for date range."""

    # Get room types
    room_types_stmt = select(RoomType).where(RoomType.is_active == True)
    if room_type_id:
        room_types_stmt = room_types_stmt.where(RoomType.id == room_type_id)
    room_types_result = await session.execute(room_types_stmt)
    room_types = room_types_result.scalars().all()

    # Get rate plans
    rate_plans_stmt = select(RatePlan).where(RatePlan.is_active == True)
    if rate_plan_id:
        rate_plans_stmt = rate_plans_stmt.where(RatePlan.id == rate_plan_id)
    rate_plans_result = await session.execute(rate_plans_stmt)
    rate_plans = rate_plans_result.scalars().all()

    grid = []
    current_date = start_date

    while current_date <= end_date:
        for rt in room_types:
            for rp in rate_plans:
                # Get daily rate
                rate_stmt = select(DailyRate).where(
                    and_(
                        DailyRate.room_type_id == rt.id,
                        DailyRate.rate_plan_id == rp.id,
                        DailyRate.date == current_date
                    )
                )
                rate_result = await session.execute(rate_stmt)
                daily_rate = rate_result.scalar_one_or_none()

                base_rate = rt.base_price
                override_rate = None
                effective_rate = base_rate

                if daily_rate:
                    base_rate = daily_rate.base_rate
                    override_rate = daily_rate.override_rate
                    effective_rate = override_rate if override_rate else base_rate

                grid.append({
                    "date": current_date.isoformat(),
                    "room_type_id": rt.id,
                    "room_type_name": rt.name,
                    "rate_plan_id": rp.id,
                    "rate_plan_code": rp.code,
                    "base_rate": base_rate,
                    "override_rate": override_rate,
                    "effective_rate": effective_rate
                })

        current_date += timedelta(days=1)

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "grid": grid
    }


@router.post("/rate-grid/update")
async def update_rate(
    payload: DailyRateUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update rate for a specific date."""

    # Get or create daily rate record
    stmt = select(DailyRate).where(
        and_(
            DailyRate.room_type_id == payload.room_type_id,
            DailyRate.rate_plan_id == payload.rate_plan_id,
            DailyRate.date == payload.date
        )
    )
    result = await session.execute(stmt)
    daily_rate = result.scalar_one_or_none()

    # Get room type for base rate
    rt = await session.get(RoomType, payload.room_type_id)
    if not rt:
        raise HTTPException(status_code=404, detail="Room type not found")

    if not daily_rate:
        daily_rate = DailyRate(
            room_type_id=payload.room_type_id,
            rate_plan_id=payload.rate_plan_id,
            date=payload.date,
            base_rate=rt.base_price
        )
        session.add(daily_rate)

    # Set override
    daily_rate.override_rate = payload.rate
    daily_rate.override_reason = payload.reason
    daily_rate.override_by = current_user.id
    daily_rate.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(daily_rate)

    # Queue sync to OTAs
    sync_item = InventorySyncQueue(
        room_type_id=payload.room_type_id,
        sync_type="rates",
        date=payload.date,
        change_type="override",
        new_value=str(payload.rate),
        changed_by=current_user.id
    )
    session.add(sync_item)
    await session.commit()

    return {"success": True, "message": "Rate updated"}


@router.post("/rate-grid/bulk-update")
async def bulk_update_rates(
    payload: BulkRateUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Bulk update rates for a date range."""

    # Get room type
    rt = await session.get(RoomType, payload.room_type_id)
    if not rt:
        raise HTTPException(status_code=404, detail="Room type not found")

    current_date = payload.start_date
    updated_count = 0

    while current_date <= payload.end_date:
        # Get or create daily rate
        stmt = select(DailyRate).where(
            and_(
                DailyRate.room_type_id == payload.room_type_id,
                DailyRate.rate_plan_id == payload.rate_plan_id,
                DailyRate.date == current_date
            )
        )
        result = await session.execute(stmt)
        daily_rate = result.scalar_one_or_none()

        if not daily_rate:
            daily_rate = DailyRate(
                room_type_id=payload.room_type_id,
                rate_plan_id=payload.rate_plan_id,
                date=current_date,
                base_rate=rt.base_price
            )
            session.add(daily_rate)

        daily_rate.override_rate = payload.rate
        daily_rate.override_reason = payload.reason
        daily_rate.override_by = current_user.id
        daily_rate.updated_at = datetime.utcnow()

        # Queue sync
        sync_item = InventorySyncQueue(
            room_type_id=payload.room_type_id,
            sync_type="rates",
            date=current_date,
            change_type="bulk",
            new_value=str(payload.rate),
            changed_by=current_user.id
        )
        session.add(sync_item)

        updated_count += 1
        current_date += timedelta(days=1)

    await session.commit()

    return {
        "success": True,
        "message": f"Updated {updated_count} rate records"
    }



# ============================================
# OTA CHANNEL ENDPOINTS
# ============================================


@router.get("/rate-plans")
async def list_rate_plans_inventory(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List rate plans for inventory mapping view"""
    stmt = select(RatePlan).where(RatePlan.is_active == True)
    result = await session.execute(stmt)
    rate_plans = result.scalars().all()
    
    return [
        {
            "id": rp.id,
            "code": rp.code,
            "name": rp.name,
            "description": rp.description,
            "plan_type": rp.plan_type,
            "base_price": rp.base_price,
            "currency": rp.currency
        }
        for rp in rate_plans
    ]


@router.get("/ota-channels", response_model=List[OTAChannelResponse])
async def list_ota_channels(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List all OTA channels."""
    stmt = select(OTAChannel).order_by(OTAChannel.ota_name)
    result = await session.execute(stmt)
    channels = result.scalars().all()

    return [
        OTAChannelResponse(
            id=ch.id,
            code=ch.ota_code,
            name=ch.ota_name,
            logo_url=ch.logo_url,
            is_active=ch.is_active,
            is_connected=ch.connection_status == "connected",
            sync_enabled=ch.auto_sync_enabled,
            last_sync_at=ch.last_sync_at,
            last_sync_status=ch.connection_status,
            commission_percent=ch.commission_rate or 0.0
        )
        for ch in channels
    ]


@router.post("/ota-channels", response_model=OTAChannelResponse)
async def create_ota_channel(
    payload: OTAChannelCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new OTA channel."""

    # Check if code exists
    existing = (await session.execute(
        select(OTAChannel).where(OTAChannel.ota_code == payload.code)
    )).scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail="OTA channel code already exists")

    channel = OTAChannel(
        property_id=1,  # Default property for single-tenant
        ota_code=payload.code,
        ota_name=payload.name,
        logo_url=payload.logo_url,
        commission_rate=payload.commission_percent
    )

    session.add(channel)
    await session.commit()
    await session.refresh(channel)

    return OTAChannelResponse(
        id=channel.id,
        code=channel.ota_code,
        name=channel.ota_name,
        logo_url=channel.logo_url,
        is_active=channel.is_active,
        is_connected=channel.connection_status == "connected",
        sync_enabled=channel.auto_sync_enabled,
        last_sync_at=channel.last_sync_at,
        last_sync_status=channel.connection_status,
        commission_percent=channel.commission_rate or 0.0
    )


@router.post("/ota-channels/{channel_id}/sync")
async def trigger_ota_sync(
    channel_id: int,
    sync_type: str = Query("full"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Trigger sync to an OTA channel."""

    channel = await session.get(OTAChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="OTA channel not found")

    if channel.connection_status != "connected":
        raise HTTPException(status_code=400, detail="OTA channel is not connected")

    # Create sync log (using SyncLog model from channel_manager)
    sync_log = OTASyncLog(
        property_id=channel.property_id,
        ota_connection_id=channel_id,
        sync_type=sync_type,
        sync_direction="push",
        status="in_progress"
    )
    session.add(sync_log)
    await session.commit()

    # In production, this would trigger actual API calls to OTA
    # For now, simulate success
    sync_log.status = "success"
    sync_log.completed_at = datetime.utcnow()
    sync_log.records_processed = 30  # Simulated
    sync_log.duration_seconds = 2.5

    channel.last_sync_at = datetime.utcnow()
    channel.connection_status = "connected"

    await session.commit()

    return {
        "success": True,
        "message": f"Sync triggered for {channel.ota_name}",
        "sync_log_id": sync_log.id
    }


@router.get("/sync-logs")
async def get_sync_logs(
    ota_channel_id: Optional[int] = Query(None),
    limit: int = Query(50),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get sync history logs."""

    stmt = select(OTASyncLog).order_by(OTASyncLog.started_at.desc()).limit(limit)
    if ota_channel_id:
        stmt = stmt.where(OTASyncLog.ota_connection_id == ota_channel_id)

    result = await session.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "ota_channel_id": log.ota_connection_id,
            "sync_type": log.sync_type,
            "sync_direction": log.sync_direction,
            "started_at": log.started_at.isoformat(),
            "completed_at": log.completed_at.isoformat() if log.completed_at else None,
            "status": log.status,
            "records_synced": log.records_processed,
            "records_failed": log.records_failed,
            "error_message": None  # SyncLog uses error_details JSON instead
        }
        for log in logs
    ]


@router.get("/sync-queue")
async def get_sync_queue(
    status: str = Query("pending"),
    limit: int = Query(100),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get pending sync queue items."""

    stmt = (
        select(InventorySyncQueue)
        .where(InventorySyncQueue.status == status)
        .order_by(InventorySyncQueue.priority.desc(), InventorySyncQueue.queued_at)
        .limit(limit)
    )

    result = await session.execute(stmt)
    items = result.scalars().all()

    return [
        {
            "id": item.id,
            "ota_channel_id": item.ota_channel_id,
            "room_type_id": item.room_type_id,
            "sync_type": item.sync_type,
            "date": item.date.isoformat(),
            "change_type": item.change_type,
            "status": item.status,
            "priority": item.priority,
            "queued_at": item.queued_at.isoformat()
        }
        for item in items
    ]
