"""
Scheduled Room Move API — Schedule, execute, and cancel room moves for checked-in guests.
Night audit pre-flight blocks if unresolved moves exist for the current business date.
"""

from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.operations import ScheduledRoomMove, AuditLog
from app.models.reservations import Booking, ReservationHistory
from app.models.inventory import Room
from app.core.business_date import get_business_date

router = APIRouter()


# --- Schemas ---

class CreateRoomMoveRequest(BaseModel):
    booking_id: int
    to_room_id: int
    scheduled_date: str  # YYYY-MM-DD
    move_reason: Optional[str] = None  # upgrade, downgrade, complaint, maintenance, consolidation
    notes: Optional[str] = None


class ExecuteRoomMoveRequest(BaseModel):
    notes: Optional[str] = None


def serialize_move(m: ScheduledRoomMove, from_room: Room = None, to_room: Room = None) -> dict:
    result = {
        "id": m.id,
        "booking_id": m.booking_id,
        "from_room_id": m.from_room_id,
        "to_room_id": m.to_room_id,
        "scheduled_date": str(m.scheduled_date) if m.scheduled_date else None,
        "move_reason": m.move_reason,
        "status": m.status,
        "moved_at": m.moved_at.isoformat() if m.moved_at else None,
        "moved_by": m.moved_by,
        "notes": m.notes,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
    if from_room:
        result["from_room_number"] = from_room.number
    if to_room:
        result["to_room_number"] = to_room.number
    return result


# --- Endpoints ---

@router.get("")
async def list_room_moves(
    booking_id: Optional[int] = None,
    status: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List scheduled room moves with optional filters."""
    query = select(ScheduledRoomMove)
    if booking_id:
        query = query.where(ScheduledRoomMove.booking_id == booking_id)
    if status:
        query = query.where(ScheduledRoomMove.status == status)
    if scheduled_date:
        query = query.where(ScheduledRoomMove.scheduled_date == scheduled_date)
    query = query.order_by(ScheduledRoomMove.scheduled_date.desc()).limit(limit)

    results = (await session.exec(query)).all()
    items = []
    for m in results:
        from_room = await session.get(Room, m.from_room_id) if m.from_room_id else None
        to_room = await session.get(Room, m.to_room_id) if m.to_room_id else None
        items.append(serialize_move(m, from_room, to_room))
    return {"items": items}


@router.post("", status_code=201)
async def create_room_move(
    payload: CreateRoomMoveRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Schedule a room move for a checked-in guest."""
    booking = await session.get(Booking, payload.booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")
    if booking.status != "checked_in":
        raise HTTPException(400, "Room moves can only be scheduled for checked-in guests")
    if not booking.room_id:
        raise HTTPException(400, "Booking has no current room assignment")

    # Check DNM
    if getattr(booking, 'do_not_move', False):
        raise HTTPException(400, "This booking is marked 'Do Not Move'")

    # Validate target room exists and is clean
    to_room = await session.get(Room, payload.to_room_id)
    if not to_room:
        raise HTTPException(404, "Target room not found")
    
    target_status = (to_room.status or "").lower()
    target_cleaning = (getattr(to_room, 'cleaning_status', '') or target_status).lower()
    if target_status == "dirty" or target_cleaning in ["dirty", "in_progress"]:
        raise HTTPException(
            status_code=400,
            detail=f"Target room {to_room.number} is dirty and cannot be assigned for a room move until cleaned."
        )

    parsed_date = date.fromisoformat(payload.scheduled_date)
    move = ScheduledRoomMove(
        booking_id=payload.booking_id,
        from_room_id=booking.room_id,
        to_room_id=payload.to_room_id,
        scheduled_date=parsed_date,
        move_reason=payload.move_reason,
        notes=payload.notes,
        created_by=current_user.id,
    )
    session.add(move)
    await session.commit()
    await session.refresh(move)

    from_room = await session.get(Room, move.from_room_id)
    return serialize_move(move, from_room, to_room)


@router.post("/{move_id}/execute")
async def execute_room_move(
    move_id: int,
    payload: ExecuteRoomMoveRequest = ExecuteRoomMoveRequest(),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Execute a scheduled room move — actually reassign the room."""
    move = await session.get(ScheduledRoomMove, move_id)
    if not move:
        raise HTTPException(404, "Room move not found")
    if move.status != "scheduled":
        raise HTTPException(400, f"Room move is already {move.status}")

    booking = await session.get(Booking, move.booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    to_room = await session.get(Room, move.to_room_id)
    if not to_room:
        raise HTTPException(404, "Target room not found")

    # Check target room availability and cleanliness
    if getattr(to_room, 'occupancy_status', 'vacant') == 'occupied':
        raise HTTPException(400, f"Room {to_room.number} is currently occupied")

    exec_status = (to_room.status or "").lower()
    exec_cleaning = (getattr(to_room, 'cleaning_status', '') or exec_status).lower()
    if exec_status == "dirty" or exec_cleaning in ["dirty", "in_progress"]:
        raise HTTPException(
            status_code=400,
            detail=f"Target room {to_room.number} is dirty and must be cleaned before executing room move."
        )

    from_room = await session.get(Room, move.from_room_id)

    # Execute the move
    old_room_id = booking.room_id
    booking.room_id = move.to_room_id

    # Update room statuses
    if from_room:
        from_room.status = "dirty"
        from_room.occupancy_status = "vacant"
        from_room.cleaning_status = "dirty"

    to_room.status = "occupied"
    to_room.occupancy_status = "occupied"
    to_room.cleaning_status = getattr(to_room, 'cleaning_status', 'clean')

    # Mark move as completed
    move.status = "completed"
    move.moved_at = datetime.utcnow()
    move.moved_by = current_user.id
    if payload.notes:
        move.notes = (move.notes or "") + f"\nExecution: {payload.notes}"

    # Log history
    session.add(ReservationHistory(
        reservation_id=booking.id,
        action="room_changed",
        old_value=str(old_room_id),
        new_value=str(move.to_room_id),
        notes=f"Room move #{move.id}: {move.move_reason or 'scheduled move'}",
        changed_by=current_user.id,
    ))

    # Audit log
    session.add(AuditLog(
        user_id=current_user.id,
        action="room_move",
        entity_type="booking",
        entity_id=booking.id,
        description=f"Room move from {from_room.number if from_room else old_room_id} to {to_room.number} (booking #{booking.id})",
        old_value={"room_id": old_room_id},
        new_value={"room_id": move.to_room_id, "reason": move.move_reason},
    ))

    await session.commit()
    return {"success": True, "message": f"Room move completed. Guest moved to Room {to_room.number}.", "move": serialize_move(move, from_room, to_room)}


@router.post("/{move_id}/cancel")
async def cancel_room_move(
    move_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Cancel a scheduled room move."""
    move = await session.get(ScheduledRoomMove, move_id)
    if not move:
        raise HTTPException(404, "Room move not found")
    if move.status != "scheduled":
        raise HTTPException(400, f"Cannot cancel — move is already {move.status}")

    move.status = "cancelled"
    move.updated_at = datetime.utcnow()
    session.add(move)
    await session.commit()
    return {"success": True, "message": "Room move cancelled"}


@router.get("/pending/check")
async def check_pending_moves(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Check pending room moves for today (used by night audit pre-flight B-04)."""
    biz_date = await get_business_date(session)
    results = (await session.exec(
        select(ScheduledRoomMove).where(
            ScheduledRoomMove.status == "scheduled",
            ScheduledRoomMove.scheduled_date <= biz_date,
        )
    )).all()
    return {
        "pending_count": len(results),
        "moves": [serialize_move(m) for m in results],
    }
