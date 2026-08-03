"""
Smart Room Assignment Service with Redis Distributed Locking

Implements intelligent room assignment algorithms based on:
- Guest preferences (from pre-checkin or profile)
- Room availability and status
- Optimization for housekeeping routes
- VIP prioritization
- Conflict prevention with Redis distributed locking
"""

import logging
from datetime import datetime, date
from typing import Optional, List, Tuple, Dict, Any
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi import HTTPException

from app.models.reservations import Reservation, Booking, Guest
from app.models.inventory import Room, RoomType, RoomHold


logger = logging.getLogger(__name__)


class RoomConflictError(Exception):
    """Raised when a room assignment conflict is detected."""
    pass


class RoomLockError(Exception):
    """Raised when a room lock cannot be acquired (room being assigned by another user)."""
    pass


def _get_lock_manager():
    """Get lock manager with fallback for when Redis is unavailable."""
    try:
        from app.services.redis_lock_service import get_lock_manager
        return get_lock_manager()
    except (RuntimeError, ImportError) as e:
        logger.debug(f"Lock manager not available: {e}")
        return None


async def assign_room_smart(
    session: AsyncSession,
    reservation_id: int,
    preferences: Optional[Dict[str, Any]] = None,
    requested_room_id: Optional[int] = None,
    use_redis_lock: bool = True
) -> Room:
    """
    Assign a room to a reservation with smart matching and Redis locking.

    Priority order:
    1. If specific room_id requested, validate and assign
    2. Match guest preferences (floor, view, bed type, etc.)
    3. Consider room status (prefer clean/inspected over dirty)
    4. Optimize for operations (cluster guests, minimize housekeeping walks)

    Args:
        session: Database session
        reservation_id: ID of the reservation
        preferences: Guest preferences for room selection
        requested_room_id: Specific room ID if requested
        use_redis_lock: Whether to use Redis distributed locks (default True)

    Returns assigned Room or raises HTTPException if no room available.
    """
    reservation = await session.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if reservation.room_id:
        # Room already assigned - return it
        room = await session.get(Room, reservation.room_id)
        if room:
            return room
        raise HTTPException(status_code=400, detail="Room already assigned but not found")

    # Get room type
    room_type = await session.get(RoomType, reservation.room_type_id)
    if not room_type:
        raise HTTPException(status_code=400, detail="Reservation has no room type assigned")

    # If specific room requested, validate it
    if requested_room_id:
        room = await validate_and_assign_room(
            session, reservation, requested_room_id, use_redis_lock
        )
        return room

    # Get all candidate rooms
    candidates = await get_available_rooms_for_reservation(
        session, reservation
    )

    if not candidates:
        raise HTTPException(
            status_code=400,
            detail=f"No {room_type.name} rooms available for the selected dates"
        )

    # Score and rank rooms
    scored_rooms = await score_rooms(
        session, candidates, reservation, preferences
    )

    # Try to assign best room with conflict check and Redis locking
    lock_manager = _get_lock_manager() if use_redis_lock else None

    for room, score in scored_rooms:
        try:
            # Try to acquire Redis lock first (optional, graceful fallback)
            if lock_manager:
                try:
                    lock_acquired, _ = await lock_manager.acquire_room_lock(
                        room_id=room.id,
                        booking_id=reservation_id,
                        ttl=900  # 15 minutes
                    )
                    if not lock_acquired:
                        logger.info(f"Room {room.number} locked by another booking, trying next")
                        continue
                except Exception as e:
                    # Redis unavailable - log and continue without locking
                    logger.warning(f"Redis lock unavailable for room {room.number}, proceeding: {e}")
                    lock_manager = None  # Disable for remaining attempts

            assigned = await try_assign_room(session, reservation, room)
            if assigned:
                logger.info(f"Room {room.number} assigned to reservation {reservation_id}")
                return room

        except RoomConflictError:
            # Release lock if we acquired it but assignment failed
            if lock_manager:
                try:
                    await lock_manager.release_room_lock(room.id, reservation_id)
                except Exception:
                    pass  # Ignore Redis errors during lock release
            continue
        except Exception as e:
            # Release lock on any error
            if lock_manager:
                try:
                    await lock_manager.release_room_lock(room.id, reservation_id)
                except Exception:
                    pass  # Ignore Redis errors during lock release
            logger.error(f"Error assigning room {room.number}: {e}")
            continue

    raise HTTPException(
        status_code=400,
        detail="Could not assign room - all options have conflicts or are locked"
    )


async def validate_and_assign_room(
    session: AsyncSession,
    reservation: Reservation,
    room_id: int,
    use_redis_lock: bool = True
) -> Room:
    """Validate requested room and assign with conflict check and Redis locking."""
    room = await session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")

    # Log if room type doesn't match (allow cross-type for upgrades/overbooking)
    if room.room_type_id != reservation.room_type_id:
        room_type = await session.get(RoomType, reservation.room_type_id)
        room_type_name = room_type.name if room_type else "the booked type"
        assigned_type = await session.get(RoomType, room.room_type_id)
        assigned_type_name = assigned_type.name if assigned_type else "unknown"
        logger.info(
            f"Cross-type assignment: Room {room.number} ({assigned_type_name}) "
            f"assigned to reservation expecting {room_type_name}"
        )

    # Check room status
    if room.status == "out_of_service":
        raise HTTPException(
            status_code=400,
            detail=f"Room {room.number} is out of service"
        )

    # Try to acquire Redis lock (optional, graceful fallback if Redis unavailable)
    lock_manager = _get_lock_manager() if use_redis_lock else None
    if lock_manager:
        try:
            lock_acquired, _ = await lock_manager.acquire_room_lock(
                room_id=room.id,
                booking_id=reservation.id,
                ttl=900
            )
            if not lock_acquired:
                raise RoomLockError(f"Room {room.number} is being assigned by another user")
        except Exception as e:
            # Redis unavailable - log and continue without locking
            logger.warning(f"Redis lock unavailable, proceeding without distributed locking: {e}")
            lock_manager = None  # Disable lock manager for this operation

    try:
        # Check for conflicts
        conflict = await check_room_conflict(
            session, room.id, reservation.arrival_date,
            reservation.departure_date, reservation.id
        )

        if conflict:
            if lock_manager:
                try:
                    await lock_manager.release_room_lock(room.id, reservation.id)
                except Exception:
                    pass  # Ignore Redis errors during lock release
            raise HTTPException(
                status_code=400,
                detail=f"Room {room.number} has a conflicting reservation"
            )

        # Assign the room
        reservation.room_id = room.id
        reservation.updated_at = datetime.utcnow()

        # Set room occupancy_status to "reserved" (not occupied - guest hasn't checked in yet)
        room.occupancy_status = "reserved"
        room.updated_at = datetime.utcnow()

        await session.flush()

        logger.info(f"Room {room.number} assigned to reservation {reservation.id} (status: reserved)")
        return room

    except Exception as e:
        # Release lock on any error
        if lock_manager:
            try:
                await lock_manager.release_room_lock(room.id, reservation.id)
            except Exception:
                pass  # Ignore Redis errors during lock release
        raise


async def check_room_conflict(
    session: AsyncSession,
    room_id: int,
    arrival_date: date,
    departure_date: date,
    exclude_reservation_id: Optional[int] = None,
    exclude_booking_id: Optional[int] = None
) -> bool:
    """Check if a room has conflicting reservations or bookings for the date range."""
    # Check legacy Reservation table
    query = select(Reservation).where(
        and_(
            Reservation.room_id == room_id,
            Reservation.status.in_(["booked", "confirmed", "checked_in"]),
            Reservation.arrival_date < departure_date,
            Reservation.departure_date > arrival_date
        )
    )

    if exclude_reservation_id:
        query = query.where(Reservation.id != exclude_reservation_id)

    conflicts = (await session.execute(query)).scalars().all()

    # Check Booking table (V2.0 model)
    booking_query = select(Booking).where(
        and_(
            Booking.room_id == room_id,
            Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
            Booking.arrival_date < departure_date,
            Booking.departure_date > arrival_date
        )
    )
    if exclude_booking_id:
        booking_query = booking_query.where(Booking.id != exclude_booking_id)
    # Also exclude by reservation's confirmation_code to avoid self-conflict
    if exclude_reservation_id:
        reservation = await session.get(Reservation, exclude_reservation_id)
        if reservation and reservation.confirmation_code:
            booking_query = booking_query.where(
                Booking.confirmation_code != reservation.confirmation_code
            )

    booking_conflicts = (await session.execute(booking_query)).scalars().all()

    # Also check for active holds
    hold_query = select(RoomHold).where(
        and_(
            RoomHold.room_id == room_id,
            RoomHold.status == "active",
            RoomHold.expires_at > datetime.utcnow(),
            RoomHold.arrival_date < departure_date,
            RoomHold.departure_date > arrival_date
        )
    )
    if exclude_reservation_id:
        hold_query = hold_query.where(
            RoomHold.reservation_id != exclude_reservation_id
        )

    active_holds = (await session.execute(hold_query)).scalars().all()

    return len(conflicts) > 0 or len(booking_conflicts) > 0 or len(active_holds) > 0


async def try_assign_room(
    session: AsyncSession,
    reservation: Reservation,
    room: Room
) -> bool:
    """
    Try to assign a room with conflict check.
    Returns True if successful, raises RoomConflictError if conflict.
    """
    # Double-check for conflicts before assignment
    conflict = await check_room_conflict(
        session, room.id, reservation.arrival_date,
        reservation.departure_date, reservation.id
    )

    if conflict:
        raise RoomConflictError(f"Room {room.number} has a conflict")

    # Assign the room
    reservation.room_id = room.id
    reservation.updated_at = datetime.utcnow()

    # Set room occupancy_status to "reserved" (not occupied - guest hasn't checked in yet)
    room.occupancy_status = "reserved"
    room.updated_at = datetime.utcnow()

    await session.flush()

    return True


async def score_rooms(
    session: AsyncSession,
    rooms: List[Room],
    reservation: Reservation,
    preferences: Optional[Dict[str, Any]]
) -> List[Tuple[Room, float]]:
    """
    Score rooms based on multiple factors.
    Higher score = better match.
    """
    scored = []

    # Get guest preferences (from precheckin or profile)
    prefs = preferences or {}
    guest = await session.get(Guest, reservation.guest_id)
    if guest and guest.preferences:
        # Merge with explicit prefs winning
        try:
            import json
            guest_prefs = json.loads(guest.preferences) if isinstance(guest.preferences, str) else guest.preferences
            prefs = {**guest_prefs, **prefs}
        except (json.JSONDecodeError, TypeError):
            pass

    for room in rooms:
        score = 100.0  # Base score

        # Floor preference (+25 points)
        if prefs.get("floor_preference"):
            pref_floor = prefs["floor_preference"]
            if isinstance(pref_floor, str):
                if pref_floor == "high" and room.floor and room.floor >= 5:
                    score += 25
                elif pref_floor == "low" and room.floor and room.floor <= 2:
                    score += 25
                elif pref_floor == "middle" and room.floor and 3 <= room.floor <= 4:
                    score += 25
            elif isinstance(pref_floor, int) and room.floor == pref_floor:
                score += 25

        # View preference (+20 points)
        if prefs.get("view_preference") and room.view_type:
            if str(prefs["view_preference"]).lower() == room.view_type.lower():
                score += 20

        # Bed type preference (+20 points)
        if prefs.get("bed_type") and room.bed_type:
            if str(prefs["bed_type"]).lower() == room.bed_type.lower():
                score += 20

        # Room status preference (+15 points for clean/inspected)
        if room.status in ["clean", "inspected"]:
            score += 15
        elif room.status == "available":
            score += 10
        elif room.status == "dirty":
            score += 0  # Will need cleaning

        # Accessibility (+10 if needed and available)
        if prefs.get("accessible") and room.is_accessible:
            score += 10

        # Quiet room preference (+10)
        if prefs.get("quiet_room"):
            # Rooms away from elevators/stairs (higher numbers on floor)
            room_num = room.number[-2:] if len(room.number) >= 2 else room.number
            try:
                if int(room_num) > 10:
                    score += 10
            except ValueError:
                pass

        # Smoking preference (+5)
        if prefs.get("smoking") is not None:
            if prefs.get("smoking") == room.is_smoking:
                score += 5

        # VIP bonus - prefer rooms with better views/higher floors
        if guest and guest.vip_status:
            if room.view_type and room.view_type.lower() in ["ocean", "sea", "premium"]:
                score += 15
            if room.floor and room.floor >= 8:
                score += 10

        # Recent cleaning bonus
        if room.last_cleaned:
            hours_since_cleaning = (datetime.utcnow() - room.last_cleaned).total_seconds() / 3600
            if hours_since_cleaning < 2:
                score += 5  # Freshly cleaned

        scored.append((room, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    return scored


async def get_available_rooms_for_reservation(
    session: AsyncSession,
    reservation: Reservation
) -> List[Room]:
    """Get all rooms available for a specific reservation (all types for upgrades/overbooking)."""
    # Get all rooms (not restricted to booked type — allows upgrades/overbooking)
    rooms_query = select(Room).where(
        Room.status.notin_(["out_of_service", "out_of_order"])
    )
    all_rooms = (await session.execute(rooms_query)).scalars().all()

    # Get room IDs with reservation conflicts
    conflicting = (await session.execute(
        select(Reservation.room_id).where(
            and_(
                Reservation.room_id.isnot(None),
                Reservation.id != reservation.id,
                Reservation.status.in_(["booked", "confirmed", "checked_in"]),
                Reservation.arrival_date < reservation.departure_date,
                Reservation.departure_date > reservation.arrival_date
            )
        )
    )).all()
    conflicting_ids = {r[0] for r in conflicting if r[0]}

    # Also get room IDs with active holds
    hold_conflicts = (await session.execute(
        select(RoomHold.room_id).where(
            and_(
                RoomHold.room_id.isnot(None),
                RoomHold.status == "active",
                RoomHold.expires_at > datetime.utcnow(),
                RoomHold.arrival_date < reservation.departure_date,
                RoomHold.departure_date > reservation.arrival_date,
                RoomHold.reservation_id != reservation.id
            )
        )
    )).all()
    hold_conflicting_ids = {r[0] for r in hold_conflicts if r[0]}

    # Check Booking table (V2.0 model) for conflicts
    booking_conflict_query = select(Booking.room_id).where(
        and_(
            Booking.room_id.isnot(None),
            Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
            Booking.arrival_date < reservation.departure_date,
            Booking.departure_date > reservation.arrival_date
        )
    )
    # Exclude the booking that corresponds to this reservation (by confirmation_code)
    if reservation.confirmation_code:
        booking_conflict_query = booking_conflict_query.where(
            Booking.confirmation_code != reservation.confirmation_code
        )
    booking_conflicts = (await session.execute(booking_conflict_query)).all()
    booking_conflicting_ids = {r[0] for r in booking_conflicts if r[0]}

    # Combine all unavailable room IDs
    unavailable_ids = conflicting_ids | hold_conflicting_ids | booking_conflicting_ids

    # Filter out conflicting rooms
    available = [r for r in all_rooms if r.id not in unavailable_ids]

    return available


async def get_room_recommendations(
    session: AsyncSession,
    reservation_id: int,
    preferences: Optional[Dict[str, Any]] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Get room recommendations for a reservation.
    Returns a list of room options with scores and details.
    """
    reservation = await session.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    # Get room type for display
    room_type = await session.get(RoomType, reservation.room_type_id)

    # Get available rooms
    candidates = await get_available_rooms_for_reservation(session, reservation)

    if not candidates:
        return []

    # Score the rooms
    scored_rooms = await score_rooms(session, candidates, reservation, preferences)

    # Pre-fetch all room types for the candidates to avoid N+1 queries
    candidate_type_ids = {room.room_type_id for room, _ in scored_rooms[:limit]}
    room_type_map = {}
    for rt_id in candidate_type_ids:
        rt = await session.get(RoomType, rt_id)
        if rt:
            room_type_map[rt_id] = rt.name

    # Return top N recommendations
    recommendations = []
    for room, score in scored_rooms[:limit]:
        actual_room_type = room_type_map.get(room.room_type_id, "Standard")
        recommendations.append({
            "room_id": room.id,
            "room_number": room.number,
            "floor": room.floor,
            "room_type": actual_room_type,
            "bed_type": room.bed_type,
            "view_type": room.view_type,
            "status": room.status,
            "is_accessible": room.is_accessible,
            "is_smoking": room.is_smoking,
            "match_score": round(score, 1),
            "last_cleaned": room.last_cleaned.isoformat() if room.last_cleaned else None
        })

    return recommendations


async def create_room_hold(
    session: AsyncSession,
    room_type_id: int,
    arrival_date: date,
    departure_date: date,
    room_id: Optional[int] = None,
    guest_session_id: Optional[str] = None
) -> RoomHold:
    """
    Create a temporary room hold during the booking process.
    Prevents race conditions by reserving inventory for 15 minutes.
    """
    # Check if room type has availability
    from app.services.reservation_service import check_availability

    room_type = await session.get(RoomType, room_type_id)
    if not room_type:
        raise HTTPException(status_code=404, detail="Room type not found")

    available = await check_availability(
        session, arrival_date, departure_date, room_type.name, adults=1
    )

    if not available:
        raise HTTPException(
            status_code=400,
            detail=f"No {room_type.name} rooms available for selected dates"
        )

    # Create the hold
    hold = RoomHold.create_hold(
        room_type_id=room_type_id,
        arrival_date=arrival_date,
        departure_date=departure_date,
        room_id=room_id,
        guest_session_id=guest_session_id
    )

    session.add(hold)
    await session.flush()

    return hold


async def convert_hold_to_reservation(
    session: AsyncSession,
    hold_token: str,
    reservation_id: int
) -> bool:
    """
    Convert a room hold to a confirmed reservation.
    Called when booking is successfully completed.
    """
    hold = (await session.execute(
        select(RoomHold).where(
            and_(
                RoomHold.hold_token == hold_token,
                RoomHold.status == "active"
            )
        )
    )).scalars().first()

    if not hold:
        return False

    if hold.is_expired():
        hold.status = "expired"
        await session.flush()
        return False

    hold.convert_to_reservation(reservation_id)
    await session.flush()

    return True


async def release_expired_holds(session: AsyncSession) -> int:
    """
    Release all expired room holds.
    Should be called periodically (e.g., every minute via scheduler).
    Returns count of released holds.
    """
    expired_holds = (await session.execute(
        select(RoomHold).where(
            and_(
                RoomHold.status == "active",
                RoomHold.expires_at <= datetime.utcnow()
            )
        )
    )).scalars().all()

    count = 0
    for hold in expired_holds:
        hold.status = "expired"
        count += 1

    await session.flush()
    return count


async def cancel_hold(
    session: AsyncSession,
    hold_token: str
) -> bool:
    """Cancel a room hold by token."""
    hold = (await session.execute(
        select(RoomHold).where(RoomHold.hold_token == hold_token)
    )).scalars().first()

    if not hold:
        return False

    hold.cancel()
    await session.flush()
    return True

async def release_room_lock_for_booking(booking_id: int, room_id: int) -> bool:
    """
    Release Redis lock for a room when booking is cancelled or checked out.
    Called by cancellation service and checkout process.
    """
    lock_manager = _get_lock_manager()
    if lock_manager:
        try:
            released = await lock_manager.release_room_lock(room_id, booking_id)
            if released:
                logger.info(f"Released lock for room {room_id}, booking {booking_id}")
            return released
        except Exception as e:
            logger.warning(f"Redis unavailable, cannot release lock for room {room_id}: {e}")
            return True  # Consider success if Redis unavailable
    return True  # No lock manager = no lock to release
