from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, and_, or_, func
from pydantic import BaseModel, Field as PydanticField, AliasChoices

from app.db.session import get_tenant_session
from app.schemas.reservations import AvailabilityQuery, AvailabilityResponse, AvailableRoom
from app.services.availability_service import find_available_rooms, rate_for_room
from app.services.reservation_service import compute_total, check_availability, get_default_rate_plan_id
from app.models.inventory import RatePlan, RoomType, Room, RoomBlock, DailyAvailability, DailyRate
from app.models.reservations import Booking, Reservation

router = APIRouter()


# ============================================
# SCHEMAS
# ============================================

class RoomBlockCreate(BaseModel):
    room_type_id: Optional[int] = None
    room_id: Optional[int] = None
    start_date: date
    end_date: date
    block_type: str = "maintenance"
    reason: str
    notes: Optional[str] = None
    quantity: int = 1


class RoomBlockUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class RoomBlockResponse(BaseModel):
    id: int
    room_type_id: Optional[int]
    room_type_name: Optional[str]
    room_id: Optional[int]
    room_number: Optional[str]
    start_date: date
    end_date: date
    block_type: str
    reason: str
    notes: Optional[str]
    quantity: int
    status: str
    created_at: datetime


class DailyAvailabilityData(BaseModel):
    date: date
    room_type_id: int
    room_type_name: str
    total_rooms: int
    sold: int  # Only checked_in guests
    reserved: int  # Confirmed/booked but not checked in
    blocked: int
    available: int
    is_closed: bool
    min_stay: int
    max_stay: Optional[int]
    closed_to_arrival: bool
    closed_to_departure: bool
    base_rate: Optional[float]


class AvailabilityGridResponse(BaseModel):
    start_date: date
    end_date: date
    room_types: List[Dict[str, Any]]
    availability: List[DailyAvailabilityData]


class BulkAvailabilityUpdate(BaseModel):
    room_type_id: int
    start_date: date
    end_date: date
    is_closed: Optional[bool] = None
    min_stay: Optional[int] = None
    max_stay: Optional[int] = None
    closed_to_arrival: Optional[bool] = None
    closed_to_departure: Optional[bool] = None
    base_rate: Optional[float] = None


class AIInsightsResponse(BaseModel):
    recommendations: List[Dict[str, Any]]
    demand_forecast: List[Dict[str, Any]]
    pricing_suggestions: List[Dict[str, Any]]
    occupancy_trends: Dict[str, Any]
    generated_at: datetime


class MultiRoomBooking(BaseModel):
    rooms: List[AvailabilityQuery]
    promo_code: Optional[str] = None


# ============================================
# HELPER FUNCTIONS
# ============================================

async def calculate_daily_availability(
    session: AsyncSession,
    room_type_id: int,
    target_date: date
) -> Dict[str, int]:
    """
    Calculate availability for a specific room type on a specific date.
    Uses EXACT same logic as dashboard to ensure consistency.
    """

    # Get total rooms for this room type (excluding out_of_service and out_of_order)
    # OOS = minor issues, can be sold in emergency
    # OOO = major issues (plumbing, electrical, renovation), CANNOT be sold
    total_stmt = select(func.count(Room.id)).where(
        and_(
            Room.room_type_id == room_type_id,
            Room.status.notin_(["out_of_service", "out_of_order"])
        )
    )
    total_result = await session.execute(total_stmt)
    total_rooms = total_result.scalar() or 0

    # Count unavailable rooms (OOS + OOO) for reporting purposes
    unavailable_stmt = select(func.count(Room.id)).where(
        and_(
            Room.room_type_id == room_type_id,
            Room.status.in_(["out_of_service", "out_of_order"])
        )
    )
    unavailable_result = await session.execute(unavailable_stmt)
    out_of_order = unavailable_result.scalar() or 0

    # Calculate sold rooms (ONLY checked_in to match dashboard)
    # Match dashboard logic: arrival_date <= target AND departure_date > target
    # ONLY count physically checked-in guests for true occupancy
    sold_stmt = select(func.count(Booking.id)).where(
        and_(
            Booking.room_type_id == room_type_id,
            Booking.arrival_date <= target_date,
            Booking.departure_date > target_date,
            Booking.status == "checked_in"  # ONLY checked_in for consistency
        )
    )
    sold_result = await session.execute(sold_stmt)
    sold = sold_result.scalar() or 0

    # Also check legacy reservations (for backward compatibility)
    legacy_sold_stmt = select(func.count(Reservation.id)).where(
        and_(
            Reservation.room_type_id == room_type_id,
            Reservation.arrival_date <= target_date,
            Reservation.departure_date > target_date,
            Reservation.status == "checked_in"  # ONLY checked_in
        )
    )
    legacy_sold_result = await session.execute(legacy_sold_stmt)
    legacy_sold = legacy_sold_result.scalar() or 0
    sold += legacy_sold

    # Calculate reserved rooms (confirmed/booked but not yet checked in)
    reserved_stmt = select(func.count(Booking.id)).where(
        and_(
            Booking.room_type_id == room_type_id,
            Booking.arrival_date <= target_date,
            Booking.departure_date > target_date,
            Booking.status.in_(["confirmed", "booked"])
        )
    )
    reserved_result = await session.execute(reserved_stmt)
    reserved = reserved_result.scalar() or 0

    # Also check legacy reservations
    legacy_reserved_stmt = select(func.count(Reservation.id)).where(
        and_(
            Reservation.room_type_id == room_type_id,
            Reservation.arrival_date <= target_date,
            Reservation.departure_date > target_date,
            Reservation.status == "booked"  # Booked but not checked in
        )
    )
    legacy_reserved_result = await session.execute(legacy_reserved_stmt)
    reserved += legacy_reserved_result.scalar() or 0

    # Calculate blocked rooms (maintenance, events, etc.)
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

    # Calculate specific room blocks (when a specific room ID is blocked)
    # Must filter by room_type_id to avoid counting blocks from other room types
    specific_room_blocks_stmt = (
        select(func.count(RoomBlock.id))
        .select_from(RoomBlock)
        .join(Room, Room.id == RoomBlock.room_id)
        .where(
            and_(
                RoomBlock.room_id != None,
                Room.room_type_id == room_type_id,  # Filter by room type
                RoomBlock.start_date <= target_date,
                RoomBlock.end_date >= target_date,
                RoomBlock.status == "active"
            )
        )
    )
    specific_room_blocks_result = await session.execute(specific_room_blocks_stmt)
    specific_room_blocks = specific_room_blocks_result.scalar() or 0
    blocked += specific_room_blocks

    # Calculate available = total - sold (checked_in) - reserved - out_of_order - blocked
    # This matches dashboard formula while accounting for reservations
    available = max(0, total_rooms - sold - reserved - out_of_order - blocked)

    return {
        "total_rooms": total_rooms,
        "sold": sold,  # Only checked_in guests
        "reserved": reserved,  # Confirmed/booked but not checked in
        "blocked": blocked,
        "out_of_order": out_of_order,
        "available": available
    }


async def ensure_daily_availability_record(
    session: AsyncSession,
    room_type_id: int,
    target_date: date
) -> DailyAvailability:
    """Get or create a DailyAvailability record. Handles duplicate records by using the first one."""

    # Try to find existing record(s) - handle duplicates
    stmt = select(DailyAvailability).where(
        and_(
            DailyAvailability.room_type_id == room_type_id,
            DailyAvailability.date == target_date
        )
    ).order_by(DailyAvailability.id.desc())  # Get most recent first
    result = await session.execute(stmt)
    all_records = result.scalars().all()
    
    # Handle duplicates - keep the most recent one
    if len(all_records) > 1:
        print(f"[AVAILABILITY] WARNING: Found {len(all_records)} duplicate DailyAvailability records for room_type_id={room_type_id}, date={target_date}")
        print(f"[AVAILABILITY] Keeping most recent (ID: {all_records[0].id}), deleting others...")
        
        # Delete duplicates (keep the first/most recent one)
        keep_id = all_records[0].id
        for record in all_records[1:]:  # Skip the first one
            await session.delete(record)
        await session.commit()
        print(f"[AVAILABILITY] Deleted {len(all_records) - 1} duplicate records")
        daily_avail = all_records[0]
    elif len(all_records) == 1:
        daily_avail = all_records[0]
    else:
        daily_avail = None

    if not daily_avail:
        # Calculate availability
        avail_data = await calculate_daily_availability(session, room_type_id, target_date)

        # Create new record
        daily_avail = DailyAvailability(
            room_type_id=room_type_id,
            date=target_date,
            **avail_data
        )
        session.add(daily_avail)
        await session.commit()
        await session.refresh(daily_avail)
    else:
        # Update counts
        avail_data = await calculate_daily_availability(session, room_type_id, target_date)
        daily_avail.total_rooms = avail_data["total_rooms"]
        daily_avail.sold = avail_data["sold"]
        daily_avail.blocked = avail_data["blocked"]
        daily_avail.available = avail_data["available"]
        daily_avail.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(daily_avail)

    return daily_avail


# ============================================
# LEGACY ENDPOINTS (kept for backward compatibility)
# ============================================

@router.post("", response_model=AvailabilityResponse)
async def search_availability(
    payload: AvailabilityQuery,
    rate_plan_id: Optional[int] = Query(None, description="Rate plan ID (optional, defaults to BAR)"),
    promo_code: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Search room availability with pricing (legacy endpoint)"""
    # Get valid rate plan ID
    if not rate_plan_id:
        rate_plan_id = await get_default_rate_plan_id(session)

    rooms = await check_availability(
        session=session,
        arrival_date=payload.arrival_date,
        departure_date=payload.departure_date,
        room_type=payload.room_type,
        adults=payload.adults
    )

    if payload.room_type:
        rooms = [r for r in rooms if r.room_type == payload.room_type]

    available_rooms = []
    for room in rooms:
        room_type_name = "Standard Room"
        if room.room_type_id:
            rt = await session.get(RoomType, room.room_type_id)
            if rt:
                room_type_name = rt.name

        rate_plan = await session.get(RatePlan, rate_plan_id)
        if not rate_plan:
            continue

        total, currency = await compute_total(
            session,
            rate_plan_id,
            payload.arrival_date,
            payload.departure_date,
            room_type_name,
            promo_code
        )

        nights = (payload.departure_date - payload.arrival_date).days
        price_per_night = total / nights if nights > 0 else total

        available_rooms.append(
            AvailableRoom(
                room_id=room.id,
                number=room.number,
                room_type=room_type_name,
                price=price_per_night,
                currency=currency
            )
        )

    return AvailabilityResponse(available_rooms=available_rooms)


@router.post("/multi-room")
async def search_multi_room(
    payload: MultiRoomBooking,
    rate_plan_id: Optional[int] = Query(None, description="Rate plan ID (optional, defaults to BAR)"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Search availability for multiple rooms (group booking)"""
    # Get valid rate plan ID
    if not rate_plan_id:
        rate_plan_id = await get_default_rate_plan_id(session)
    results = []

    for room_query in payload.rooms:
        rooms = await check_availability(
            session=session,
            arrival_date=room_query.arrival_date,
            departure_date=room_query.departure_date,
            room_type=room_query.room_type,
            adults=room_query.adults
        )

        for room in rooms:
            room_type_name = "Standard Room"
            if room.room_type_id:
                rt = await session.get(RoomType, room.room_type_id)
                if rt:
                    room_type_name = rt.name

            total, currency = await compute_total(
                session,
                rate_plan_id,
                room_query.arrival_date,
                room_query.departure_date,
                room_type_name,
                payload.promo_code
            )

            nights = (room_query.departure_date - room_query.arrival_date).days
            price_per_night = total / nights if nights > 0 else total

            results.append({
                "room_id": room.id,
                "number": room.number,
                "room_type": room_type_name,
                "price": price_per_night,
                "currency": currency,
                "arrival_date": room_query.arrival_date,
                "departure_date": room_query.departure_date
            })

    return {"available_rooms": results}


# ============================================
# NEW CMS AVAILABILITY ENDPOINTS
# ============================================

@router.get("/grid", response_model=AvailabilityGridResponse)
async def get_availability_grid(
    start_date: date = Query(..., validation_alias=AliasChoices("startDate", "start_date"), description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., validation_alias=AliasChoices("endDate", "end_date"), description="End date (YYYY-MM-DD)"),
    room_type_ids: Optional[str] = Query(None, validation_alias=AliasChoices("roomTypeIds", "room_type_ids"), description="Comma-separated room type IDs"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Get availability grid for CMS.
    Returns daily availability data for all room types within date range.
    Optimized to use bulk queries instead of per-day queries.
    Query params: startDate/endDate (or start_date/end_date), optional roomTypeIds.
    """
    try:
        # Get all room types
        room_types_stmt = select(RoomType).where(RoomType.is_active == True)
        if room_type_ids:
            type_ids = [int(x.strip()) for x in room_type_ids.split(",")]
            room_types_stmt = room_types_stmt.where(RoomType.id.in_(type_ids))

        room_types_result = await session.execute(room_types_stmt)
        room_types = room_types_result.scalars().all()

        if not room_types:
            return AvailabilityGridResponse(
                start_date=start_date,
                end_date=end_date,
                room_types=[],
                availability=[]
            )

        room_type_ids_list = [rt.id for rt in room_types]

        # Bulk load: Get total rooms per room type (excluding out_of_service and out_of_order)
        total_rooms_stmt = (
            select(Room.room_type_id, func.count(Room.id).label("count"))
            .where(
                and_(
                    Room.room_type_id.in_(room_type_ids_list),
                    Room.status.notin_(["out_of_service", "out_of_order"])
                )
            )
            .group_by(Room.room_type_id)
        )
        total_rooms_result = await session.execute(total_rooms_stmt)
        total_rooms_map = {}
        for row in total_rooms_result:
            # Handle both Row and tuple results
            if hasattr(row, 'room_type_id'):
                total_rooms_map[row.room_type_id] = row.count if hasattr(row, 'count') else row[1]
            else:
                total_rooms_map[row[0]] = row[1]

        # Bulk load: Get out_of_order rooms per room type
        ooo_stmt = (
            select(Room.room_type_id, func.count(Room.id).label("count"))
            .where(
                and_(
                    Room.room_type_id.in_(room_type_ids_list),
                    Room.status == "out_of_order"
                )
            )
            .group_by(Room.room_type_id)
        )
        ooo_result = await session.execute(ooo_stmt)
        out_of_order_map = {}
        for row in ooo_result:
            # Handle both Row and tuple results
            if hasattr(row, 'room_type_id'):
                out_of_order_map[row.room_type_id] = row.count if hasattr(row, 'count') else row[1]
            else:
                out_of_order_map[row[0]] = row[1]

        # Bulk load: Get all bookings that overlap with date range
        bookings_stmt = select(Booking).where(
            and_(
                Booking.room_type_id.in_(room_type_ids_list),
                Booking.arrival_date <= end_date,
                Booking.departure_date > start_date
            )
        )
        bookings_result = await session.execute(bookings_stmt)
        all_bookings = bookings_result.scalars().all()

        # Bulk load: Get all legacy reservations that overlap with date range
        reservations_stmt = select(Reservation).where(
            and_(
                Reservation.room_type_id.in_(room_type_ids_list),
                Reservation.arrival_date <= end_date,
                Reservation.departure_date > start_date
            )
        )
        reservations_result = await session.execute(reservations_stmt)
        all_reservations = reservations_result.scalars().all()

        # Bulk load: Get all room blocks that overlap with date range
        blocks_stmt = select(RoomBlock).where(
            and_(
                or_(
                    RoomBlock.room_type_id.in_(room_type_ids_list),
                    RoomBlock.room_id != None  # Will filter by room_type_id in join later
                ),
                RoomBlock.start_date <= end_date,
                RoomBlock.end_date >= start_date,
                RoomBlock.status == "active"
            )
        )
        blocks_result = await session.execute(blocks_stmt)
        all_blocks = blocks_result.scalars().all()

        # Bulk load: Get all daily availability records for the date range
        daily_avail_stmt = select(DailyAvailability).where(
            and_(
                DailyAvailability.room_type_id.in_(room_type_ids_list),
                DailyAvailability.date >= start_date,
                DailyAvailability.date <= end_date
            )
        )
        daily_avail_result = await session.execute(daily_avail_stmt)
        all_daily_avail = daily_avail_result.scalars().all()
        
        # Create a map for quick lookup: (room_type_id, date) -> DailyAvailability
        daily_avail_map = {}
        for da in all_daily_avail:
            key = (da.room_type_id, da.date)
            # Keep the most recent if duplicates exist
            if key not in daily_avail_map or da.id > daily_avail_map[key].id:
                daily_avail_map[key] = da

        # Get specific room blocks (where room_id is set) and map to room types
        specific_room_blocks = [b for b in all_blocks if b.room_id is not None]
        if specific_room_blocks:
            room_ids = [b.room_id for b in specific_room_blocks]
            rooms_stmt = select(Room).where(Room.id.in_(room_ids))
            rooms_result = await session.execute(rooms_stmt)
            room_to_type_map = {room.id: room.room_type_id for room in rooms_result.scalars().all()}
        else:
            room_to_type_map = {}

        # Build room types list
        room_types_data = []
        for rt in room_types:
            total_rooms = total_rooms_map.get(rt.id, 0)
            room_types_data.append({
                "id": rt.id,
                "name": rt.name,
                "slug": rt.slug,
                "base_price": rt.base_price,
                "total_rooms": total_rooms
            })

        # Calculate availability for each date and room type combination
        availability_data = []
        new_daily_avail_records = []
        current_date = start_date

        while current_date <= end_date:
            for rt in room_types:
                room_type_id = rt.id
                total_rooms = total_rooms_map.get(room_type_id, 0)
                out_of_order = out_of_order_map.get(room_type_id, 0)

                # Count sold (checked_in) bookings for this date
                sold = 0
                for booking in all_bookings:
                    if (booking.room_type_id == room_type_id and
                        booking.arrival_date <= current_date < booking.departure_date and
                        booking.status == "checked_in"):
                        sold += 1

                # Count sold (checked_in) legacy reservations
                for reservation in all_reservations:
                    if (reservation.room_type_id == room_type_id and
                        reservation.arrival_date <= current_date < reservation.departure_date and
                        reservation.status == "checked_in"):
                        sold += 1

                # Count reserved (confirmed/booked but not checked in)
                reserved = 0
                for booking in all_bookings:
                    if (booking.room_type_id == room_type_id and
                        booking.arrival_date <= current_date < booking.departure_date and
                        booking.status in ["confirmed", "booked"]):
                        reserved += 1

                for reservation in all_reservations:
                    if (reservation.room_type_id == room_type_id and
                        reservation.arrival_date <= current_date < reservation.departure_date and
                        reservation.status == "booked"):
                        reserved += 1

                # Count blocked rooms
                blocked = 0
                for block in all_blocks:
                    if (block.start_date <= current_date <= block.end_date):
                        if block.room_type_id == room_type_id:
                            blocked += block.quantity or 1
                        elif block.room_id and room_to_type_map.get(block.room_id) == room_type_id:
                            blocked += 1

                # Calculate available
                available = max(0, total_rooms - sold - reserved - out_of_order - blocked)

                # Get or create daily availability record (for settings like is_closed, min_stay, etc.)
                daily_avail_key = (room_type_id, current_date)
                daily_avail = daily_avail_map.get(daily_avail_key)
                
                if not daily_avail:
                    # Create new record if it doesn't exist (batch add later)
                    daily_avail = DailyAvailability(
                        room_type_id=room_type_id,
                        date=current_date,
                        total_rooms=total_rooms,
                        sold=sold,
                        blocked=blocked,
                        available=available,
                        is_closed=False,
                        min_stay=1,
                        max_stay=None,
                        closed_to_arrival=False,
                        closed_to_departure=False,
                        base_rate=rt.base_price
                    )
                    new_daily_avail_records.append(daily_avail)
                    session.add(daily_avail)
                else:
                    # Update counts in existing record
                    daily_avail.total_rooms = total_rooms
                    daily_avail.sold = sold
                    daily_avail.blocked = blocked
                    daily_avail.available = available
                    daily_avail.updated_at = datetime.utcnow()

                availability_data.append(
                    DailyAvailabilityData(
                        date=current_date,
                        room_type_id=room_type_id,
                        room_type_name=rt.name,
                        total_rooms=total_rooms,
                        sold=sold,
                        reserved=reserved,
                        blocked=blocked,
                        available=available,
                        is_closed=daily_avail.is_closed,
                        min_stay=daily_avail.min_stay,
                        max_stay=daily_avail.max_stay,
                        closed_to_arrival=daily_avail.closed_to_arrival,
                        closed_to_departure=daily_avail.closed_to_departure,
                        base_rate=daily_avail.base_rate or rt.base_price
                    )
                )

            current_date += timedelta(days=1)

        # Batch commit all new records and updates
        await session.commit()
        # Refresh new records to get their IDs
        for da in new_daily_avail_records:
            await session.refresh(da)

        return AvailabilityGridResponse(
            start_date=start_date,
            end_date=end_date,
            room_types=room_types_data,
            availability=availability_data
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in get_availability_grid: {error_trace}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching availability grid: {str(e)}"
        )


@router.post("/bulk-update")
async def bulk_update_availability(
    updates: List[BulkAvailabilityUpdate],
    session: AsyncSession = Depends(get_tenant_session)
):
    """Bulk update availability restrictions for multiple date ranges.

    Optimised path: pre-fetches all affected DailyAvailability rows in one
    query, applies changes in-memory, and commits once at the end.  The
    expensive ``calculate_daily_availability`` is only called for rows that
    need to be *created* (not for existing rows where we only toggle
    restrictions like stop-sell).
    """
    if not updates:
        return {"success": True, "updated_records": 0, "message": "No updates provided"}

    # ------------------------------------------------------------------
    # 1. Collect every (room_type_id, date) pair we need to touch
    # ------------------------------------------------------------------
    needed: dict[tuple[int, date], BulkAvailabilityUpdate] = {}
    all_rt_ids: set[int] = set()
    global_min_date = updates[0].start_date
    global_max_date = updates[0].end_date

    for update in updates:
        all_rt_ids.add(update.room_type_id)
        d = update.start_date
        while d <= update.end_date:
            needed[(update.room_type_id, d)] = update
            d += timedelta(days=1)
        if update.start_date < global_min_date:
            global_min_date = update.start_date
        if update.end_date > global_max_date:
            global_max_date = update.end_date

    # ------------------------------------------------------------------
    # 2. Batch-fetch all existing DailyAvailability rows in one query
    # ------------------------------------------------------------------
    existing_stmt = select(DailyAvailability).where(
        and_(
            DailyAvailability.room_type_id.in_(list(all_rt_ids)),
            DailyAvailability.date >= global_min_date,
            DailyAvailability.date <= global_max_date,
        )
    )
    existing_result = await session.execute(existing_stmt)
    existing_rows = existing_result.scalars().all()

    existing_map: dict[tuple[int, date], DailyAvailability] = {}
    for row in existing_rows:
        key = (row.room_type_id, row.date)
        # Keep the row with the highest id (most recent) in case of duplicates
        if key not in existing_map or row.id > existing_map[key].id:
            existing_map[key] = row

    # ------------------------------------------------------------------
    # 3. Pre-fetch lookup data needed for base_rate sync (only if any
    #    update actually sets base_rate)
    # ------------------------------------------------------------------
    needs_rate_sync = any(u.base_rate is not None for u in updates)
    bar_plan = None
    rt_cache: dict[int, RoomType] = {}
    dr_map: dict[tuple[int, date], DailyRate] = {}

    if needs_rate_sync:
        bar_plan_result = await session.exec(
            select(RatePlan).where(RatePlan.code == "BAR").limit(1)
        )
        bar_plan = bar_plan_result.first()

        # Pre-fetch room types
        rt_result = await session.exec(
            select(RoomType).where(RoomType.id.in_(list(all_rt_ids)))
        )
        for rt in rt_result.all():
            rt_cache[rt.id] = rt

        # Pre-fetch existing DailyRate rows
        if bar_plan:
            dr_result = await session.exec(
                select(DailyRate).where(
                    and_(
                        DailyRate.room_type_id.in_(list(all_rt_ids)),
                        DailyRate.rate_plan_id == bar_plan.id,
                        DailyRate.date >= global_min_date,
                        DailyRate.date <= global_max_date,
                    )
                )
            )
            for dr in dr_result.all():
                dr_map[(dr.room_type_id, dr.date)] = dr

    # ------------------------------------------------------------------
    # 4. Pre-fetch room counts per room type (for creating new records)
    # ------------------------------------------------------------------
    room_counts: dict[int, int] = {}
    for rt_id in all_rt_ids:
        cnt_result = await session.execute(
            select(func.count(Room.id)).where(
                and_(
                    Room.room_type_id == rt_id,
                    Room.status.notin_(["out_of_service", "out_of_order"])
                )
            )
        )
        room_counts[rt_id] = cnt_result.scalar() or 0

    # ------------------------------------------------------------------
    # 5. Apply updates — no commits inside the loop
    # ------------------------------------------------------------------
    updated_count = 0
    now = datetime.utcnow()

    for (rt_id, d), update in needed.items():
        daily_avail = existing_map.get((rt_id, d))

        if not daily_avail:
            # Create a lightweight record (skip expensive availability calc)
            daily_avail = DailyAvailability(
                room_type_id=rt_id,
                date=d,
                total_rooms=room_counts.get(rt_id, 0),
                sold=0,
                blocked=0,
                available=room_counts.get(rt_id, 0),
            )
            session.add(daily_avail)
            existing_map[(rt_id, d)] = daily_avail

        # Apply restriction fields
        if update.is_closed is not None:
            daily_avail.is_closed = update.is_closed
        if update.min_stay is not None:
            daily_avail.min_stay = update.min_stay
        if update.max_stay is not None:
            daily_avail.max_stay = update.max_stay
        if update.closed_to_arrival is not None:
            daily_avail.closed_to_arrival = update.closed_to_arrival
        if update.closed_to_departure is not None:
            daily_avail.closed_to_departure = update.closed_to_departure

        if update.base_rate is not None:
            daily_avail.base_rate = update.base_rate
            # Sync to DailyRate (using pre-fetched data)
            if bar_plan:
                existing_dr = dr_map.get((rt_id, d))
                if existing_dr:
                    existing_dr.override_rate = update.base_rate
                    existing_dr.updated_at = now
                else:
                    rt_obj = rt_cache.get(rt_id)
                    new_dr = DailyRate(
                        room_type_id=rt_id,
                        rate_plan_id=bar_plan.id,
                        date=d,
                        base_rate=float(rt_obj.base_price or 0) if rt_obj else 0,
                        override_rate=update.base_rate,
                    )
                    session.add(new_dr)
                    dr_map[(rt_id, d)] = new_dr

        daily_avail.updated_at = now
        updated_count += 1

    # ------------------------------------------------------------------
    # 6. Single commit for the entire batch
    # ------------------------------------------------------------------
    await session.commit()

    return {
        "success": True,
        "updated_records": updated_count,
        "message": f"Successfully updated {updated_count} availability records"
    }


# ============================================
# ROOM TYPE PRICE ENDPOINTS
# ============================================

class RoomTypePriceUpdate(BaseModel):
    base_price: float


class BulkRoomTypePriceItem(BaseModel):
    room_type_id: int
    base_price: float


@router.put("/room-types/bulk-price")
async def bulk_update_room_type_prices(
    updates: List[BulkRoomTypePriceItem],
    session: AsyncSession = Depends(get_tenant_session)
):
    """Bulk update room type base prices."""
    updated_count = 0
    for item in updates:
        rt = await session.get(RoomType, item.room_type_id)
        if rt:
            rt.base_price = item.base_price
            rt.updated_at = datetime.utcnow()
            session.add(rt)
            updated_count += 1

    await session.commit()

    return {
        "success": True,
        "updated_count": updated_count,
        "message": f"Updated {updated_count} room type prices"
    }


@router.put("/room-types/{room_type_id}/price")
async def update_room_type_price(
    room_type_id: int,
    payload: RoomTypePriceUpdate,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Update a single room type's base price."""
    rt = await session.get(RoomType, room_type_id)
    if not rt:
        raise HTTPException(status_code=404, detail="Room type not found")

    rt.base_price = payload.base_price
    rt.updated_at = datetime.utcnow()
    session.add(rt)
    await session.commit()

    return {
        "success": True,
        "message": f"Updated {rt.name} base price to {payload.base_price}"
    }


# ============================================
# RESET RATES TO BASE PRICE
# ============================================


class ResetRatesPayload(BaseModel):
    room_type_id: Optional[int] = None  # None = all room types
    start_date: Optional[date] = None   # None = today onwards
    end_date: Optional[date] = None     # None = 90 days from start


@router.post("/reset-to-base-price")
async def reset_rates_to_base_price(
    payload: ResetRatesPayload = Body(default=ResetRatesPayload()),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Reset DailyAvailability.base_rate and DailyRate.override_rate back to RoomType.base_price
    for the given room type and date range."""

    start = payload.start_date or date.today()
    end = payload.end_date or (start + timedelta(days=90))

    # Get room types to reset
    if payload.room_type_id:
        rt = await session.get(RoomType, payload.room_type_id)
        if not rt:
            raise HTTPException(status_code=404, detail="Room type not found")
        room_types = [rt]
    else:
        result = await session.exec(select(RoomType).where(RoomType.is_active == True))
        room_types = result.all()

    reset_count = 0
    for rt in room_types:
        # Reset DailyAvailability.base_rate to RoomType.base_price
        da_query = select(DailyAvailability).where(
            and_(
                DailyAvailability.room_type_id == rt.id,
                DailyAvailability.date >= start,
                DailyAvailability.date <= end,
            )
        )
        da_results = await session.exec(da_query)
        for da in da_results.all():
            if da.base_rate != rt.base_price:
                da.base_rate = rt.base_price
                session.add(da)
                reset_count += 1

    await session.commit()

    return {
        "success": True,
        "reset_count": reset_count,
        "room_types": len(room_types),
        "date_range": {"start": str(start), "end": str(end)},
        "message": f"Reset {reset_count} daily rates to base price across {len(room_types)} room types"
    }


# ============================================
# ROOM BLOCKS ENDPOINTS
# ============================================

@router.get("/blocks", response_model=List[RoomBlockResponse])
async def get_room_blocks(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    room_type_id: Optional[int] = Query(None),
    status: str = Query("active"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get all room blocks with optional filtering."""

    stmt = select(RoomBlock).where(RoomBlock.status == status)

    if start_date:
        stmt = stmt.where(RoomBlock.end_date >= start_date)
    if end_date:
        stmt = stmt.where(RoomBlock.start_date <= end_date)
    if room_type_id:
        stmt = stmt.where(RoomBlock.room_type_id == room_type_id)

    stmt = stmt.order_by(RoomBlock.start_date.desc())

    result = await session.execute(stmt)
    blocks = result.scalars().all()

    # Enrich with room type and room details
    response = []
    for block in blocks:
        room_type_name = None
        if block.room_type_id:
            rt = await session.get(RoomType, block.room_type_id)
            if rt:
                room_type_name = rt.name

        room_number = None
        if block.room_id:
            room = await session.get(Room, block.room_id)
            if room:
                room_number = room.number

        response.append(
            RoomBlockResponse(
                id=block.id,
                room_type_id=block.room_type_id,
                room_type_name=room_type_name,
                room_id=block.room_id,
                room_number=room_number,
                start_date=block.start_date,
                end_date=block.end_date,
                block_type=block.block_type,
                reason=block.reason,
                notes=block.notes,
                quantity=block.quantity,
                status=block.status,
                created_at=block.created_at
            )
        )

    return response


@router.post("/blocks", response_model=RoomBlockResponse)
async def create_room_block(
    block_data: RoomBlockCreate,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Create a new room block."""

    # Validate dates
    if block_data.end_date < block_data.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    # Create block
    block = RoomBlock(
        room_type_id=block_data.room_type_id,
        room_id=block_data.room_id,
        start_date=block_data.start_date,
        end_date=block_data.end_date,
        block_type=block_data.block_type,
        reason=block_data.reason,
        notes=block_data.notes,
        quantity=block_data.quantity
    )

    session.add(block)
    await session.commit()
    await session.refresh(block)

    # Update daily availability records
    if block.room_type_id:
        current_date = block.start_date
        while current_date <= block.end_date:
            await ensure_daily_availability_record(session, block.room_type_id, current_date)
            current_date += timedelta(days=1)

    # Get enriched response
    room_type_name = None
    if block.room_type_id:
        rt = await session.get(RoomType, block.room_type_id)
        if rt:
            room_type_name = rt.name

    room_number = None
    if block.room_id:
        room = await session.get(Room, block.room_id)
        if room:
            room_number = room.number

    return RoomBlockResponse(
        id=block.id,
        room_type_id=block.room_type_id,
        room_type_name=room_type_name,
        room_id=block.room_id,
        room_number=room_number,
        start_date=block.start_date,
        end_date=block.end_date,
        block_type=block.block_type,
        reason=block.reason,
        notes=block.notes,
        quantity=block.quantity,
        status=block.status,
        created_at=block.created_at
    )


@router.put("/blocks/{block_id}", response_model=RoomBlockResponse)
async def update_room_block(
    block_id: int,
    block_data: RoomBlockUpdate,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Update an existing room block."""

    block = await session.get(RoomBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Room block not found")

    # Update fields
    if block_data.start_date is not None:
        block.start_date = block_data.start_date
    if block_data.end_date is not None:
        block.end_date = block_data.end_date
    if block_data.reason is not None:
        block.reason = block_data.reason
    if block_data.notes is not None:
        block.notes = block_data.notes
    if block_data.status is not None:
        block.status = block_data.status

    block.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(block)

    # Get enriched response
    room_type_name = None
    if block.room_type_id:
        rt = await session.get(RoomType, block.room_type_id)
        if rt:
            room_type_name = rt.name

    room_number = None
    if block.room_id:
        room = await session.get(Room, block.room_id)
        if room:
            room_number = room.number

    return RoomBlockResponse(
        id=block.id,
        room_type_id=block.room_type_id,
        room_type_name=room_type_name,
        room_id=block.room_id,
        room_number=room_number,
        start_date=block.start_date,
        end_date=block.end_date,
        block_type=block.block_type,
        reason=block.reason,
        notes=block.notes,
        quantity=block.quantity,
        status=block.status,
        created_at=block.created_at
    )


@router.delete("/blocks/{block_id}")
async def delete_room_block(
    block_id: int,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Delete (cancel) a room block."""

    block = await session.get(RoomBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Room block not found")

    block.status = "cancelled"
    block.cancelled_at = datetime.utcnow()
    block.updated_at = datetime.utcnow()

    await session.commit()

    # Update daily availability records
    if block.room_type_id:
        current_date = block.start_date
        while current_date <= block.end_date:
            await ensure_daily_availability_record(session, block.room_type_id, current_date)
            current_date += timedelta(days=1)

    return {
        "success": True,
        "message": "Room block cancelled successfully"
    }


# ============================================
# AI INSIGHTS ENDPOINT
# ============================================

@router.get("/today-stats")
async def get_today_stats(
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get today's activity statistics (arrivals, departures, in-house)."""

    today = date.today()

    # Arrivals (expected check-ins today - NOT already checked in)
    # Match dashboard logic: only confirmed/booked, excluding checked_in
    arrivals_stmt = select(func.count(Booking.id)).where(
        and_(
            Booking.arrival_date == today,
            Booking.status.in_(["confirmed", "booked"])  # Expected, not yet checked in
        )
    )
    arrivals_result = await session.execute(arrivals_stmt)
    arrivals = arrivals_result.scalar() or 0

    # Also check legacy reservations
    legacy_arrivals_stmt = select(func.count(Reservation.id)).where(
        and_(
            Reservation.arrival_date == today,
            Reservation.status == "booked"  # Expected arrivals only
        )
    )
    legacy_arrivals_result = await session.execute(legacy_arrivals_stmt)
    arrivals += legacy_arrivals_result.scalar() or 0

    # Departures (guests currently staying who are checking out today)
    # Match dashboard logic: only checked_in guests
    departures_stmt = select(func.count(Booking.id)).where(
        and_(
            Booking.departure_date == today,
            Booking.status == "checked_in"  # Only currently staying guests
        )
    )
    departures_result = await session.execute(departures_stmt)
    departures = departures_result.scalar() or 0

    # Legacy departures
    legacy_departures_stmt = select(func.count(Reservation.id)).where(
        and_(
            Reservation.departure_date == today,
            Reservation.status == "checked_in"  # Only checked in
        )
    )
    legacy_departures_result = await session.execute(legacy_departures_stmt)
    departures += legacy_departures_result.scalar() or 0

    # In-house (currently staying - ONLY checked_in)
    # Match dashboard logic: only physically present guests
    in_house_stmt = select(func.count(Booking.id)).where(
        and_(
            Booking.arrival_date <= today,
            Booking.departure_date > today,
            Booking.status == "checked_in"  # ONLY checked_in guests
        )
    )
    in_house_result = await session.execute(in_house_stmt)
    in_house = in_house_result.scalar() or 0

    # Legacy in-house
    legacy_in_house_stmt = select(func.count(Reservation.id)).where(
        and_(
            Reservation.arrival_date <= today,
            Reservation.departure_date > today,
            Reservation.status == "checked_in"  # ONLY checked_in
        )
    )
    legacy_in_house_result = await session.execute(legacy_in_house_stmt)
    in_house += legacy_in_house_result.scalar() or 0

    return {
        "date": today.isoformat(),
        "arrivals": arrivals,
        "departures": departures,
        "in_house": in_house
    }


@router.get("/insights", response_model=AIInsightsResponse)
async def get_ai_insights(
    days_ahead: int = Query(30, description="Number of days to analyze"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Generate AI insights for availability patterns and recommendations."""

    start_date = date.today()
    end_date = start_date + timedelta(days=days_ahead)

    # Get all active room types
    room_types_stmt = select(RoomType).where(RoomType.is_active == True)
    room_types_result = await session.execute(room_types_stmt)
    room_types = room_types_result.scalars().all()

    # Analyze occupancy and generate insights
    recommendations = []
    demand_forecast = []
    pricing_suggestions = []
    occupancy_data = {
        "average_occupancy": 0,
        "high_demand_days": 0,
        "low_demand_days": 0,
        "peak_occupancy_date": None,
        "lowest_occupancy_date": None
    }

    total_occupancy = 0
    days_analyzed = 0
    max_occupancy = 0
    min_occupancy = 100
    peak_date = None
    lowest_date = None

    current_date = start_date
    while current_date <= end_date:
        daily_total = 0
        daily_sold = 0

        for rt in room_types:
            avail_data = await calculate_daily_availability(session, rt.id, current_date)
            daily_total += avail_data["total_rooms"]
            daily_sold += avail_data["sold"]

        if daily_total > 0:
            occupancy_pct = (daily_sold / daily_total) * 100
            total_occupancy += occupancy_pct
            days_analyzed += 1

            # Track peak and lowest
            if occupancy_pct > max_occupancy:
                max_occupancy = occupancy_pct
                peak_date = current_date
            if occupancy_pct < min_occupancy:
                min_occupancy = occupancy_pct
                lowest_date = current_date

            # Count high/low demand days
            if occupancy_pct >= 80:
                occupancy_data["high_demand_days"] += 1
            elif occupancy_pct <= 40:
                occupancy_data["low_demand_days"] += 1

            # Add to forecast
            demand_forecast.append({
                "date": current_date.isoformat(),
                "occupancy_forecast": round(occupancy_pct, 1),
                "demand_level": "high" if occupancy_pct >= 80 else "low" if occupancy_pct <= 40 else "medium"
            })

        current_date += timedelta(days=1)

    # Calculate average occupancy
    if days_analyzed > 0:
        occupancy_data["average_occupancy"] = round(total_occupancy / days_analyzed, 1)

    occupancy_data["peak_occupancy_date"] = peak_date.isoformat() if peak_date else None
    occupancy_data["lowest_occupancy_date"] = lowest_date.isoformat() if lowest_date else None

    # Generate recommendations based on patterns
    if occupancy_data["average_occupancy"] >= 85:
        recommendations.append({
            "type": "pricing",
            "priority": "high",
            "title": "Increase Rates - High Demand Detected",
            "description": f"Average occupancy is {occupancy_data['average_occupancy']}%. Consider increasing rates by 10-15%.",
            "action": "increase_rates",
            "impact": "revenue_optimization"
        })

    if occupancy_data["average_occupancy"] < 50:
        recommendations.append({
            "type": "promotion",
            "priority": "high",
            "title": "Create Promotional Offer",
            "description": f"Low occupancy detected ({occupancy_data['average_occupancy']}%). Flash sale recommended.",
            "action": "create_promo",
            "impact": "occupancy_boost"
        })

    if occupancy_data["high_demand_days"] > 10:
        recommendations.append({
            "type": "restriction",
            "priority": "medium",
            "title": "Consider Minimum Stay Requirements",
            "description": f"{occupancy_data['high_demand_days']} high-demand days detected. Consider 2-night minimum stay.",
            "action": "set_min_stay",
            "impact": "revenue_optimization"
        })

    # Generate pricing suggestions for each room type
    for rt in room_types:
        avg_occupancy_for_type = 0
        days_counted = 0

        current_date = start_date
        while current_date <= end_date:
            avail_data = await calculate_daily_availability(session, rt.id, current_date)
            if avail_data["total_rooms"] > 0:
                occ_pct = (avail_data["sold"] / avail_data["total_rooms"]) * 100
                avg_occupancy_for_type += occ_pct
                days_counted += 1
            current_date += timedelta(days=1)

        if days_counted > 0:
            avg_occupancy_for_type /= days_counted

            suggested_adjustment = 0
            if avg_occupancy_for_type >= 90:
                suggested_adjustment = 15
            elif avg_occupancy_for_type >= 80:
                suggested_adjustment = 10
            elif avg_occupancy_for_type >= 70:
                suggested_adjustment = 5
            elif avg_occupancy_for_type < 40:
                suggested_adjustment = -10
            elif avg_occupancy_for_type < 50:
                suggested_adjustment = -5

            if suggested_adjustment != 0:
                pricing_suggestions.append({
                    "room_type_id": rt.id,
                    "room_type_name": rt.name,
                    "current_rate": rt.base_price,
                    "suggested_rate": round(rt.base_price * (1 + suggested_adjustment/100), 2),
                    "adjustment_percentage": suggested_adjustment,
                    "reason": f"Based on {round(avg_occupancy_for_type, 1)}% occupancy forecast"
                })

    return AIInsightsResponse(
        recommendations=recommendations,
        demand_forecast=demand_forecast,
        pricing_suggestions=pricing_suggestions,
        occupancy_trends=occupancy_data,
        generated_at=datetime.utcnow()
    )
