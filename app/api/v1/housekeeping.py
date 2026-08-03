from datetime import datetime, date, timezone
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.inventory import Room, RoomType, RoomStatus
from app.models.operations import HousekeepingTask, MaintenanceRequest, LostFound, LinenInventory
from app.models.reservations import Booking
from app.models.user import User

router = APIRouter()


def _utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """BUG-020 FIX: Convert naive UTC datetime to ISO string with Z suffix.
    Without Z, JavaScript treats the string as local time, causing timezone offset errors."""
    if dt is None:
        return None
    # If naive (no tzinfo), assume UTC and add Z
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


class RoomStatusUpdate(BaseModel):
    status: str  # Use RoomStatus constants: clean, dirty, inspected, cleaning, maintenance, out_of_service
    notes: Optional[str] = None


class TaskCreate(BaseModel):
    room_id: int
    task_type: str = "clean"  # clean, inspect, maintenance, deep_clean
    priority: str = "normal"
    scheduled_for: Optional[datetime] = None
    estimated_duration: Optional[int] = None
    notes: Optional[str] = None


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    actual_duration: Optional[int] = None
    notes: Optional[str] = None
    checklist: Optional[list] = None


class MaintenanceRequestCreate(BaseModel):
    room_id: Optional[int] = None
    issue: str
    description: Optional[str] = None
    severity: str = "normal"
    estimated_cost: Optional[float] = None
    notes: Optional[str] = None


class LostFoundCreate(BaseModel):
    item_description: str
    location_found: Optional[str] = None
    room_id: Optional[int] = None
    found_date: Optional[date] = None
    storage_location: Optional[str] = None
    notes: Optional[str] = None


@router.get("/rooms")
async def list_rooms(
    status_filter: Optional[str] = Query(None, alias="status"),
    room_type: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    from app.models.staff import Staff

    # Join with RoomType to get room type name
    query = select(Room, RoomType).join(RoomType, Room.room_type_id == RoomType.id, isouter=True)
    if status_filter:
        query = query.where(Room.status == status_filter)
    if room_type:
        query = query.where(RoomType.name == room_type)

    results = (await session.exec(query.order_by(Room.number))).all()

    # Pre-fetch the most relevant task per room (latest non-cancelled task)
    all_room_ids = [r.id for r, rt in results]
    task_query = select(HousekeepingTask).where(
        HousekeepingTask.room_id.in_(all_room_ids),
        HousekeepingTask.status != "cancelled"
    ).order_by(HousekeepingTask.created_at.desc())
    all_tasks = (await session.exec(task_query)).all()

    # Build map: room_id -> most relevant task
    # Tasks are pre-sorted by created_at DESC, so first encountered per room is newest.
    # Priority: in_progress always wins; otherwise keep newest task (which has the
    # most recent assignment/completion data).
    task_by_room = {}
    for t in all_tasks:
        existing = task_by_room.get(t.room_id)
        if not existing:
            task_by_room[t.room_id] = t
        elif t.status == "in_progress" and existing.status != "in_progress":
            # In-progress always wins — cleaning is happening right now
            task_by_room[t.room_id] = t

    # Build staff name cache
    staff_ids = {t.assigned_to for t in all_tasks if t.assigned_to}
    staff_map = {}
    if staff_ids:
        staff_result = await session.exec(select(Staff).where(Staff.id.in_(staff_ids)))
        for s in staff_result.all():
            staff_map[s.id] = s.name

    room_list = []
    for r, rt in results:
        task = task_by_room.get(r.id)

        # Derive effective housekeeping status from compound fields
        # Priority: occupancy > maintenance/OOS/OOO > cleaning_status > legacy status
        occupancy = getattr(r, 'occupancy_status', None) or 'vacant'
        cleaning = getattr(r, 'cleaning_status', None)
        if occupancy == 'occupied' or r.status == 'occupied':
            effective_status = 'occupied'
        elif r.status in ('out_of_service', 'out_of_order', 'maintenance'):
            effective_status = r.status
        elif cleaning in ('dirty', 'in_progress', 'inspected', 'clean'):
            effective_status = cleaning
        else:
            effective_status = r.status

        room_list.append({
            "id": r.id,
            "number": r.number,
            "room_type": rt.name if rt else "Standard",
            "room_type_category": rt.category if rt else None,
            "status": effective_status,
            "floor": r.floor,
            "capacity": r.capacity,
            "max_occupancy": r.max_occupancy,
            "bed_type": r.bed_type or (rt.bed_type if rt else None),
            "view_type": r.view_type or (rt.view_type if rt else None),
            "last_cleaned": r.last_cleaned,
            # Task details for frontend (BUG-021: preserve task details for clean rooms)
            "task_id": task.id if task else None,
            "task_status": task.status if task else None,
            "task_priority": task.priority if task else None,
            "assigned_to": task.assigned_to if task else None,
            "assigned_staff_name": staff_map.get(task.assigned_to) if task and task.assigned_to else None,
            "started_at": _utc_iso(task.started_at) if task else None,
            "completed_at": _utc_iso(task.completed_at) if task else None,
            "notes": task.notes if task else None,
            "checklist": task.checklist if task else None,
        })

    return room_list


@router.get("/rooms/my-rooms")
async def list_my_rooms(
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get rooms assigned to the current staff member via housekeeping tasks.
    BUG-002 FIX: Now returns task details (notes, checklist, priority, etc.)
    so the frontend can display them in room cards."""
    from app.models.staff import Staff

    # Find staff record for current user
    result = await session.exec(select(Staff).where(Staff.user_id == current_user.id))
    staff = result.first()

    if not staff:
        return []

    # BUG-002 FIX: Include HousekeepingTask in select to get task details
    query = select(Room, RoomType, HousekeepingTask).join(
        HousekeepingTask, Room.id == HousekeepingTask.room_id
    ).join(
        RoomType, Room.room_type_id == RoomType.id, isouter=True
    ).where(
        HousekeepingTask.assigned_to == staff.id
    ).where(
        HousekeepingTask.status.in_(["pending", "in_progress", "assigned"])
    )

    if status:
        query = query.where(Room.status == status)

    query = query.order_by(Room.number)
    results = (await session.exec(query)).all()

    # Return unique rooms with their most relevant task details
    # Priority: in_progress > assigned > pending (pick the most active task)
    seen_rooms = {}
    for r, rt, t in results:
        existing = seen_rooms.get(r.id)
        if not existing:
            seen_rooms[r.id] = (r, rt, t)
        else:
            _, _, existing_task = existing
            # Prefer in_progress task, then assigned, then pending
            priority_map = {"in_progress": 0, "assigned": 1, "pending": 2}
            if priority_map.get(t.status, 3) < priority_map.get(existing_task.status, 3):
                seen_rooms[r.id] = (r, rt, t)

    unique_rooms = []
    for r, rt, task in seen_rooms.values():
        unique_rooms.append({
            "id": r.id,
            "number": r.number,
            "room_number": r.number,
            "room_type": rt.name if rt else "Standard",
            "room_type_category": rt.category if rt else None,
            "status": r.status,
            "floor": r.floor,
            "capacity": r.capacity,
            "max_occupancy": r.max_occupancy,
            "bed_type": r.bed_type or (rt.bed_type if rt else None),
            "view_type": r.view_type or (rt.view_type if rt else None),
            "last_cleaned": r.last_cleaned,
            # Task details for room cards (BUG-002 FIX)
            "task_id": task.id,
            "task_status": task.status,
            "priority": task.priority,
            "assigned_to": task.assigned_to,
            "started_at": _utc_iso(task.started_at),
            "completed_at": _utc_iso(task.completed_at),
            "notes": task.notes,
            "checklist": task.checklist,
        })

    # Sort by room number
    unique_rooms.sort(key=lambda x: x["number"])
    return unique_rooms


@router.patch("/rooms/{room_id}/status")
async def update_room_status(
    room_id: int,
    payload: RoomStatusUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    room = await session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    old_status = room.status
    # Normalize incoming status to standard values (handles ooo -> out_of_service, etc.)
    normalized_status = RoomStatus.normalize(payload.status)

    # Warn if blocking an occupied room but allow it (emergency maintenance scenarios)
    warning = None
    if normalized_status in (RoomStatus.OUT_OF_SERVICE, RoomStatus.OUT_OF_ORDER, RoomStatus.MAINTENANCE):
        if room.occupancy_status == "occupied" or room.status == "occupied":
            warning = f"Room {room.number} was occupied — status forced to '{normalized_status}'"
            room.occupancy_status = "vacant"

    room.status = normalized_status
    # F-03: Sync compound cleaning_status
    if normalized_status in ("dirty", "clean", "inspected", "in_progress"):
        room.cleaning_status = normalized_status
    # Sync compound occupancy_status
    if normalized_status == "occupied":
        room.occupancy_status = "occupied"
    elif normalized_status in ("available", "clean", "inspected", "dirty"):
        room.occupancy_status = "vacant"
    room.updated_at = datetime.utcnow()

    # Auto-complete active tasks when room is marked clean/inspected
    # This preserves task data (assigned staff, start time, etc.) for display
    if normalized_status in ("clean", "inspected") and old_status != normalized_status:
        active_task_q = select(HousekeepingTask).where(
            HousekeepingTask.room_id == room_id,
            HousekeepingTask.status.in_(["pending", "assigned", "in_progress"])
        ).order_by(HousekeepingTask.created_at.desc())
        active_task = (await session.exec(active_task_q)).first()
        if active_task:
            now = datetime.utcnow()
            active_task.status = "completed"
            active_task.completed_at = now
            active_task.updated_at = now
            if active_task.started_at:
                duration = (now - active_task.started_at).total_seconds() / 60
                active_task.actual_duration = int(duration)
            room.last_cleaned = now

    # Auto-create cleaning task if room becomes dirty
    if normalized_status == RoomStatus.DIRTY and old_status != RoomStatus.DIRTY:
        # Check if there's already an active task for this room to avoid duplicates
        existing_task_q = select(HousekeepingTask).where(
            HousekeepingTask.room_id == room_id,
            HousekeepingTask.status.in_(["pending", "assigned", "in_progress"])
        )
        existing_task = (await session.exec(existing_task_q)).first()
        if not existing_task:
            task = HousekeepingTask(
                room_id=room_id,
                task_type="cleaning",
                status="pending",
                priority="normal",
                created_at=datetime.utcnow()
            )
            session.add(task)
    
    await session.commit()
    await session.refresh(room)
    result = {"id": room.id, "number": room.number, "status": room.status}
    if warning:
        result["warning"] = warning
    return result


@router.get("/tasks")
async def list_hk_tasks(
    status: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    room_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    List housekeeping tasks with optional filters.

    Returns empty list if no tasks found.
    """
    from app.models.staff import Staff

    try:
        # Join with Room and Staff to get room number and staff name
        query = select(HousekeepingTask, Room, Staff).join(
            Room, HousekeepingTask.room_id == Room.id, isouter=True
        ).join(
            Staff, HousekeepingTask.assigned_to == Staff.id, isouter=True
        )

        if status:
            # Treat "assigned" as a variant of "pending" for API consumers
            if status == "pending":
                query = query.where(HousekeepingTask.status.in_(["pending", "assigned"]))
            else:
                query = query.where(HousekeepingTask.status == status)
        if task_type:
            query = query.where(HousekeepingTask.task_type == task_type)
        if assigned_to:
            query = query.where(HousekeepingTask.assigned_to == assigned_to)
        if room_id:
            query = query.where(HousekeepingTask.room_id == room_id)

        results = (await session.exec(query.order_by(HousekeepingTask.priority.desc(), HousekeepingTask.scheduled_for))).all()

        return [{
            "id": t.id,
            "room_id": t.room_id,
            "room_number": r.number if r else None,
            "task_type": t.task_type,
            "status": t.status,
            "assigned_to": t.assigned_to,
            "assigned_staff_name": s.name if s else None,
            "priority": t.priority,
            "scheduled_for": t.scheduled_for,
            "started_at": _utc_iso(t.started_at),
            "completed_at": _utc_iso(t.completed_at),
            "estimated_duration": t.estimated_duration,
            "actual_duration": t.actual_duration,
            "notes": t.notes,
            "created_at": t.created_at
        } for t, r, s in results]

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve housekeeping tasks: {str(e)}"
        )


@router.get("/tasks/my-tasks")
async def list_my_hk_tasks(
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get housekeeping tasks assigned to the current user"""
    from app.models.staff import Staff
    from app.api.v1.staff import get_or_create_staff_record

    try:
        # Find or create staff record for current user
        staff = await get_or_create_staff_record(session, current_user)

        query = select(HousekeepingTask, Room).join(Room, HousekeepingTask.room_id == Room.id, isouter=True).where(
            HousekeepingTask.assigned_to == staff.id
        )

        if status:
            # Treat "assigned" as a variant of "pending" - both mean "waiting to be started"
            if status == "pending":
                query = query.where(HousekeepingTask.status.in_(["pending", "assigned"]))
            else:
                query = query.where(HousekeepingTask.status == status)
        else:
            # Default: show active tasks
            query = query.where(HousekeepingTask.status.in_(["pending", "in_progress", "assigned"]))

        query = query.order_by(HousekeepingTask.priority.desc(), HousekeepingTask.scheduled_for)
        results = (await session.exec(query)).all()

        return [{
            "id": t.id,
            "room_id": t.room_id,
            "room_number": r.number if r else None,
            "task_type": t.task_type,
            "status": t.status,
            "assigned_to": t.assigned_to,
            "assigned_to_name": staff.name,
            "priority": t.priority,
            "scheduled_for": t.scheduled_for,
            "started_at": _utc_iso(t.started_at),
            "completed_at": _utc_iso(t.completed_at),
            "estimated_duration": t.estimated_duration,
            "actual_duration": t.actual_duration,
            "notes": t.notes,
            "created_at": t.created_at
        } for t, r in results]

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve my tasks: {str(e)}"
        )


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_hk_task(
    payload: TaskCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new housekeeping task"""
    # Validate room exists
    room = await session.get(Room, payload.room_id)
    if not room:
        raise HTTPException(
            status_code=400,
            detail=f"Room with ID {payload.room_id} does not exist. Please use GET /rooms to see available rooms."
        )

    task = HousekeepingTask(
        room_id=payload.room_id,
        task_type=payload.task_type,
        priority=payload.priority,
        scheduled_for=payload.scheduled_for,
        estimated_duration=payload.estimated_duration,
        notes=payload.notes,
        status="pending"
    )
    session.add(task)

    try:
        await session.commit()
        await session.refresh(task)
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create housekeeping task: {str(e)}"
        )

    return {"id": task.id, "room_id": task.room_id, "task_type": task.task_type, "status": task.status, "created": True}


@router.patch("/tasks/{task_id}")
async def update_hk_task(
    task_id: int,
    payload: TaskUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    task = await session.get(HousekeepingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    old_task_status = task.status
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(task, key, value)

    # Auto-update room status when task status changes
    room = await session.get(Room, task.room_id) if task.room_id else None
    if payload.status == "in_progress" and old_task_status != "in_progress":
        if room:
            room.status = "in_progress"
            room.cleaning_status = "in_progress"
        if not task.started_at:
            task.started_at = datetime.utcnow()
    elif payload.status == "completed" and old_task_status != "completed":
        if room:
            if task.task_type == "clean":
                room.status = "clean"
                room.cleaning_status = "clean"
            elif task.task_type == "inspect":
                room.status = "inspected"
                room.cleaning_status = "inspected"

    task.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(task)
    return {"id": task.id, "status": task.status}


@router.get("/maintenance")
async def list_maintenance_requests(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    room_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    query = select(MaintenanceRequest)
    if status:
        query = query.where(MaintenanceRequest.status == status)
    if severity:
        query = query.where(MaintenanceRequest.severity == severity)
    if room_id:
        query = query.where(MaintenanceRequest.room_id == room_id)
    
    requests = (await session.exec(query.order_by(
        MaintenanceRequest.severity.desc(), MaintenanceRequest.reported_at.desc()
    ))).all()
    
    return [{"id": r.id, "room_id": r.room_id, "issue": r.issue, "severity": r.severity,
             "status": r.status, "reported_at": r.reported_at} for r in requests]


@router.post("/maintenance", status_code=status.HTTP_201_CREATED)
async def create_maintenance_request(
    payload: MaintenanceRequestCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    request = MaintenanceRequest(
        room_id=payload.room_id,
        issue=payload.issue,
        description=payload.description,
        severity=payload.severity,
        estimated_cost=payload.estimated_cost,
        notes=payload.notes,
        reported_by=current_user.id,
        status="open"
    )
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return {"id": request.id, "status": "created"}


@router.get("/lost-found")
async def list_lost_found(
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    query = select(LostFound)
    if status:
        query = query.where(LostFound.status == status)
    
    items = (await session.exec(query.order_by(LostFound.found_date.desc()))).all()
    return [{"id": i.id, "item_description": i.item_description, "location_found": i.location_found,
             "room_id": i.room_id, "found_date": i.found_date, "status": i.status,
             "storage_location": i.storage_location} for i in items]


@router.post("/lost-found", status_code=status.HTTP_201_CREATED)
async def create_lost_found(
    payload: LostFoundCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    item = LostFound(
        item_description=payload.item_description,
        location_found=payload.location_found,
        room_id=payload.room_id,
        found_date=payload.found_date or date.today(),
        storage_location=payload.storage_location,
        notes=payload.notes,
        found_by=current_user.id,
        status="stored"
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": item.id, "status": "created"}


@router.get("/linen-inventory")
async def list_linen_inventory(
    item_type: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    query = select(LinenInventory)
    if item_type:
        query = query.where(LinenInventory.item_type == item_type)
    if location:
        query = query.where(LinenInventory.location == location)
    
    items = (await session.exec(query.order_by(LinenInventory.item_type))).all()
    return [{"id": i.id, "item_type": i.item_type, "quantity": i.quantity,
             "location": i.location, "status": i.status} for i in items]


@router.post("/linen-inventory", status_code=status.HTTP_201_CREATED)
async def update_linen_inventory(
    item_type: str,
    quantity: int,
    location: Optional[str] = None,
    status: str = "available",
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    # Check if item exists
    existing = (await session.exec(
        select(LinenInventory).where(
            and_(
                LinenInventory.item_type == item_type,
                LinenInventory.location == location
            )
        )
    )).first()

    if existing:
        existing.quantity = quantity
        existing.status = status
        existing.last_updated = datetime.utcnow()
        await session.commit()
        await session.refresh(existing)
        return {"id": existing.id, "status": "updated"}
    else:
        item = LinenInventory(
            item_type=item_type,
            quantity=quantity,
            location=location,
            status=status
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return {"id": item.id, "status": "created"}


# ============== TASK ASSIGNMENT ==============

class TaskAssignmentRequest(BaseModel):
    staff_id: int
    priority: Optional[str] = None
    notes: Optional[str] = None


@router.post("/tasks/{task_id}/assign")
async def assign_task(
    task_id: int,
    payload: TaskAssignmentRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Assign a housekeeping task to a staff member"""
    task = await session.get(HousekeepingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Get staff info
    from app.models.staff import Staff
    staff = await session.get(Staff, payload.staff_id)
    staff_user_id = None  # User ID for notifications
    if not staff:
        # Try to get from User table
        user = await session.get(User, payload.staff_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found")
        staff_email = user.email
        staff_name = user.full_name or user.email
        staff_user_id = user.id
    else:
        staff_email = staff.email
        staff_name = staff.name
        staff_user_id = staff.user_id

    # Update task
    task.assigned_to = payload.staff_id
    if payload.priority:
        task.priority = payload.priority
    if payload.notes:
        task.notes = (task.notes or "") + f"\n{payload.notes}"
    task.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(task)

    # Get room info for email
    room = await session.get(Room, task.room_id)
    room_number = room.number if room else str(task.room_id)

    # Create notification for the staff member (staff_id is FK to users.id)
    try:
        from app.models.guest_chat import StaffNotification
        notification = StaffNotification(
            staff_id=staff_user_id,
            task_id=task.id,
            room_id=task.room_id,
            notification_type="task_assigned",
            title=f"New {task.task_type.capitalize()} Task Assigned",
            message=f"You have been assigned a {task.task_type} task for Room {room_number}. Priority: {task.priority or 'normal'}.",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to create notification: {e}")

    # Send email notification in background
    from app.services.background_email import send_task_assignment_email_bg
    background_tasks.add_task(
        send_task_assignment_email_bg,
        to_email=staff_email,
        staff_name=staff_name,
        task_type=task.task_type,
        room_number=room_number,
        priority=task.priority or "normal",
        notes=task.notes,
    )

    return {
        "message": "Task assigned successfully",
        "task_id": task_id,
        "assigned_to": payload.staff_id,
        "staff_name": staff_name,
    }


@router.post("/tasks/{task_id}/start")
async def start_task(
    task_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark a task as started and update the room status to in_progress"""
    task = await session.get(HousekeepingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "in_progress":
        raise HTTPException(status_code=400, detail="Task is already in progress")

    now = datetime.utcnow()
    task.status = "in_progress"
    task.started_at = now
    task.updated_at = now

    # Also update room status to in_progress so room shows as being cleaned
    room = await session.get(Room, task.room_id)
    if room:
        room.status = "in_progress"
        room.cleaning_status = "in_progress"
        room.updated_at = now

    await session.commit()
    await session.refresh(task)

    return {
        "message": "Task started",
        "task_id": task_id,
        "status": "in_progress",
        "started_at": _utc_iso(task.started_at),
    }


class TaskCompleteRequest(BaseModel):
    notes: Optional[str] = None
    quality_score: Optional[int] = None
    issues_found: Optional[list] = None
    checklist: Optional[list] = None


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: int,
    payload: Optional[TaskCompleteRequest] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark a task as completed"""
    notes = payload.notes if payload else None

    task = await session.get(HousekeepingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "completed":
        raise HTTPException(status_code=400, detail="Task is already completed")

    now = datetime.utcnow()
    task.status = "completed"
    task.completed_at = now
    task.updated_at = now

    # Calculate actual duration if started
    if task.started_at:
        duration = (now - task.started_at).total_seconds() / 60  # in minutes
        task.actual_duration = int(duration)

    if notes:
        task.notes = (task.notes or "") + f"\n[Completion note]: {notes}"

    # BUG-003 FIX: Save checklist data on completion
    if payload and payload.checklist:
        task.checklist = payload.checklist
    elif task.checklist and isinstance(task.checklist, list):
        # BUG-022 FIX: Auto-mark all checklist items as completed when task is completed
        # without explicit checklist data (e.g. marking clean from list view)
        task.checklist = [
            {**item, "completed": True} if isinstance(item, dict) else item
            for item in task.checklist
        ]

    # Update room status and last_cleaned timestamp
    room = await session.get(Room, task.room_id)
    if room:
        if task.task_type == "clean":
            room.status = "clean"
            room.cleaning_status = "clean"
        elif task.task_type == "inspect":
            room.status = "inspected"
            room.cleaning_status = "inspected"
        elif task.task_type in ["deep_clean", "checkout_clean"]:
            room.status = "clean"
            room.cleaning_status = "clean"
        room.last_cleaned = now
        room.updated_at = now

    await session.commit()

    return {
        "message": "Task completed",
        "task_id": task_id,
        "status": "completed",
        "actual_duration": task.actual_duration,
        "started_at": _utc_iso(task.started_at),
        "completed_at": _utc_iso(task.completed_at),
        "room_status": room.status if room else None,
    }


@router.get("/dashboard")
async def housekeeping_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get housekeeping dashboard data"""
    from app.models.staff import Staff

    today = date.today()

    # Room status counts — single source of truth from Room table
    rooms = (await session.exec(select(Room))).all()
    # Derive effective status from compound fields for accurate counts
    def _eff_status(r):
        occ = getattr(r, 'occupancy_status', None) or 'vacant'
        cln = getattr(r, 'cleaning_status', None)
        if occ == 'occupied' or r.status == 'occupied':
            return 'occupied'
        if r.status in ('out_of_service', 'out_of_order', 'maintenance'):
            return r.status
        if cln in ('dirty', 'in_progress', 'inspected', 'clean'):
            return cln
        return r.status

    eff_statuses = [_eff_status(r) for r in rooms]
    room_status = {
        "total": len(rooms),
        "clean": eff_statuses.count("clean"),
        "dirty": eff_statuses.count("dirty"),
        "in_progress": eff_statuses.count("in_progress"),
        "inspected": eff_statuses.count("inspected"),
        "occupied": eff_statuses.count("occupied"),
        "out_of_order": eff_statuses.count("out_of_order") + eff_statuses.count("maintenance"),
        "out_of_service": eff_statuses.count("out_of_service"),
    }

    # Task counts
    tasks_query = await session.exec(select(HousekeepingTask))
    tasks = tasks_query.all()

    pending_count = len([t for t in tasks if t.status == "pending"])
    in_progress_count = len([t for t in tasks if t.status == "in_progress"])
    completed_today_count = len([t for t in tasks if t.status == "completed" and t.completed_at and t.completed_at.date() == today])

    # Calculate average cleaning time from completed tasks
    completed_tasks = [t for t in tasks if t.actual_duration is not None]
    avg_cleaning_time = sum(t.actual_duration for t in completed_tasks) / len(completed_tasks) if completed_tasks else 30

    # Get housekeeping staff
    staff_result = await session.exec(
        select(Staff).where(Staff.department == "housekeeping")
    )
    hk_staff = staff_result.all()

    staff_list = []
    for s in hk_staff:
        # Check if staff is working on a room
        current_room = None
        for t in tasks:
            if t.assigned_to == s.id and t.status == "in_progress":
                room = await session.get(Room, t.room_id)
                current_room = room.number if room else None
                break

        staff_list.append({
            "id": s.id,
            "name": s.name,
            "status": "active" if s.clocked_in else "off-duty",
            "current_room": current_room
        })

    # Priority tasks with room details
    priority_rooms = []
    for t in tasks:
        if t.status == "pending" and t.priority in ["high", "urgent"]:
            room = await session.get(Room, t.room_id)
            priority_rooms.append({
                "room_id": t.room_id,
                "room_number": room.number if room else str(t.room_id),
                "priority": t.priority,
                "task_type": t.task_type,
            })

    return {
        "room_status": room_status,
        "tasks": {
            "pending": pending_count,
            "in_progress": in_progress_count,
            "completed_today": completed_today_count,
            "avg_cleaning_time": int(avg_cleaning_time),
        },
        "staff": {
            "on_shift": len([s for s in hk_staff if s.clocked_in]),
            "list": staff_list,
        },
        "priority_rooms": priority_rooms[:10],
    }


@router.post("/rooms/{room_id}/inspect")
async def mark_room_inspected(
    room_id: int,
    passed: bool = True,
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark a room as inspected"""
    room = await session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    if passed:
        room.status = "inspected"
        room.cleaning_status = "inspected"
    else:
        room.status = "dirty"  # Needs re-cleaning
        room.cleaning_status = "dirty"
        # Create a new cleaning task
        task = HousekeepingTask(
            room_id=room_id,
            task_type="clean",
            status="pending",
            priority="high",
            notes=f"Re-clean required: {notes}" if notes else "Re-clean required after failed inspection",
        )
        session.add(task)

    room.updated_at = datetime.utcnow()
    await session.commit()

    return {
        "room_id": room_id,
        "status": room.status,
        "passed_inspection": passed,
        "notes": notes,
    }


# ============== AUTO-ASSIGNMENT ENDPOINTS ==============

class AutoAssignResult(BaseModel):
    task_id: int
    room_id: Optional[int] = None
    room_number: Optional[str] = None
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    score: Optional[float] = None
    success: bool
    message: str


class BulkAutoAssignResult(BaseModel):
    total_tasks: int
    total_assigned: int  # Frontend expected field name
    total_failed: int    # Frontend expected field name
    assigned_count: int  # Alias for backward compatibility
    failed_count: int    # Alias for backward compatibility
    results: List[AutoAssignResult]


@router.post("/tasks/{task_id}/auto-assign", response_model=AutoAssignResult)
async def auto_assign_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Auto-assign a housekeeping task to the best available staff member.
    Uses multi-factor scoring: workload (30%), skills (25%), availability (20%),
    performance (15%), floor proximity (10%).
    """
    from app.services.staff_scheduling_service import get_scheduling_service
    from app.models.staff import Staff

    task = await session.get(HousekeepingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Get room details first for all responses
    room = await session.get(Room, task.room_id) if task.room_id else None
    room_number = room.number if room else None

    if task.status in ["completed", "cancelled"]:
        return AutoAssignResult(
            task_id=task_id,
            room_id=task.room_id,
            room_number=room_number,
            success=False,
            message=f"Task is already {task.status}"
        )

    # BUG-005 FIX: Validate room actually needs cleaning (only dirty rooms)
    # Rooms that are in_progress already have an active cleaning session
    if room and room.status != "dirty":
        # Cancel the stale task
        task.status = "cancelled"
        task.updated_at = datetime.utcnow()
        await session.commit()
        return AutoAssignResult(
            task_id=task_id,
            room_id=task.room_id,
            room_number=room_number,
            success=False,
            message=f"Room is {room.status}, not dirty — task cancelled"
        )

    # Use scheduling service to find best staff
    scheduling_service = get_scheduling_service(session)
    best_staff = await scheduling_service.find_best_staff_for_task(
        task_type="housekeeping",
        priority=task.priority or "normal",
        room_number=room_number
    )

    if not best_staff:
        return AutoAssignResult(
            task_id=task_id,
            room_id=task.room_id,
            room_number=room_number,
            success=False,
            message="No available housekeeping staff found"
        )

    # Assign the task
    task.assigned_to = best_staff.staff_id
    task.status = "assigned"
    task.updated_at = datetime.utcnow()
    await session.commit()

    # Create notification
    try:
        from app.models.guest_chat import StaffNotification
        # Note: StaffNotification.staff_id is FK to users.id, use user_id
        notification = StaffNotification(
            staff_id=best_staff.user_id,
            task_id=task.id,
            room_id=task.room_id,
            notification_type="task_assigned",
            title=f"Auto-Assigned: {task.task_type.capitalize()} Task",
            message=f"Room {room_number} - {task.task_type}. Priority: {task.priority or 'normal'}.",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to create notification: {e}")

    # Send email notification in background
    from app.services.background_email import send_task_assignment_email_bg
    background_tasks.add_task(
        send_task_assignment_email_bg,
        to_email=best_staff.email,
        staff_name=best_staff.staff_name,
        task_type=task.task_type,
        room_number=room_number or str(task.room_id),
        priority=task.priority or "normal",
        notes=task.notes,
    )

    return AutoAssignResult(
        task_id=task_id,
        room_id=task.room_id,
        room_number=room_number,
        assigned_to=best_staff.staff_id,
        assigned_to_name=best_staff.staff_name,
        score=round(best_staff.total_score, 2),
        success=True,
        message=f"Task assigned to {best_staff.staff_name} (score: {best_staff.total_score:.2f})"
    )


@router.post("/tasks/auto-assign-all", response_model=BulkAutoAssignResult)
async def auto_assign_all_pending_tasks(
    priority: Optional[str] = Query(None, description="Only assign tasks with this priority"),
    max_tasks: int = Query(50, description="Maximum tasks to assign in one call"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Auto-assign all pending housekeeping tasks to available staff members.
    Tasks are assigned in priority order (urgent first).
    """
    from app.services.staff_scheduling_service import get_scheduling_service

    query = select(HousekeepingTask).where(
        HousekeepingTask.status.in_(["pending"])
    )
    if priority:
        query = query.where(HousekeepingTask.priority == priority)

    query = query.order_by(
        HousekeepingTask.priority.desc(),
        HousekeepingTask.created_at.asc()
    ).limit(max_tasks)

    tasks = (await session.exec(query)).all()

    results = []
    assigned_count = 0
    scheduling_service = get_scheduling_service(session)

    for task in tasks:
        room = await session.get(Room, task.room_id) if task.room_id else None
        room_number = room.number if room else None

        # BUG-005/BUG-017 FIX: Only assign tasks for dirty rooms
        # Rooms that are in_progress already have an active cleaning session
        if room and room.status != "dirty":
            results.append(AutoAssignResult(
                task_id=task.id,
                room_id=task.room_id,
                room_number=room_number,
                success=False,
                message=f"Room is {room.status}, not dirty — skipping"
            ))
            # Cancel the stale task since room doesn't need a new assignment
            task.status = "cancelled"
            task.updated_at = datetime.utcnow()
            continue

        best_staff = await scheduling_service.find_best_staff_for_task(
            task_type="housekeeping",
            priority=task.priority or "normal",
            room_number=room_number
        )

        if best_staff:
            task.assigned_to = best_staff.staff_id
            task.status = "assigned"
            task.updated_at = datetime.utcnow()
            assigned_count += 1

            results.append(AutoAssignResult(
                task_id=task.id,
                room_id=task.room_id,
                room_number=room_number,
                assigned_to=best_staff.staff_id,
                assigned_to_name=best_staff.staff_name,
                score=round(best_staff.total_score, 2),
                success=True,
                message=f"Assigned to {best_staff.staff_name}"
            ))

            try:
                from app.models.guest_chat import StaffNotification
                # Note: StaffNotification.staff_id is FK to users.id, use user_id
                notification = StaffNotification(
                    staff_id=best_staff.user_id,
                    task_id=task.id,
                    room_id=task.room_id,
                    notification_type="task_assigned",
                    title=f"Auto-Assigned: {task.task_type.capitalize()} Task",
                    message=f"Room {room_number} - {task.task_type}. Priority: {task.priority or 'normal'}.",
                    is_read=False,
                    created_at=datetime.utcnow()
                )
                session.add(notification)
            except Exception:
                pass
        else:
            results.append(AutoAssignResult(
                task_id=task.id,
                room_id=task.room_id,
                room_number=room_number,
                success=False,
                message="No available staff"
            ))

    await session.commit()

    return BulkAutoAssignResult(
        total_tasks=len(tasks),
        total_assigned=assigned_count,
        total_failed=len(tasks) - assigned_count,
        assigned_count=assigned_count,
        failed_count=len(tasks) - assigned_count,
        results=results
    )


@router.get("/staff/workload")
async def get_housekeeping_staff_workload(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get workload summary for all housekeeping staff"""
    from app.services.staff_scheduling_service import get_scheduling_service

    scheduling_service = get_scheduling_service(session)
    workload_summary = await scheduling_service.get_staff_workload_summary(department="housekeeping")

    available_count = len([s for s in workload_summary if s["availability"] == "available"])
    all_busy = available_count == 0 and len(workload_summary) > 0

    return {
        "department": "housekeeping",
        "staff_count": len(workload_summary),
        "available_count": available_count,
        "all_staff_busy": all_busy,
        "busy_alert": "All housekeeping staff are currently occupied with tasks." if all_busy else None,
        "staff": workload_summary
    }


# ==================== FORCE ASSIGN (Admin Override) ====================

class ForceAssignRequest(BaseModel):
    """Request model for force-assigning a task to busy staff"""
    staff_id: int
    reason: str  # Required reason for force assignment
    require_acceptance: bool = True  # Whether staff must accept/decline


class ForceAssignResponse(BaseModel):
    task_id: int
    staff_id: int
    staff_name: str
    success: bool
    message: str
    requires_acceptance: bool
    force_assigned: bool


@router.post("/tasks/{task_id}/force-assign", response_model=ForceAssignResponse)
async def force_assign_task(
    task_id: int,
    payload: ForceAssignRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Force-assign a task to a specific staff member, bypassing availability limits.
    Use this for urgent/high-priority tasks when all staff are busy.
    """
    from app.models.staff import Staff
    from app.models.guest_chat import StaffNotification

    if current_user.role not in ["admin", "manager", "supervisor"]:
        raise HTTPException(status_code=403, detail="Only admins/managers can force-assign tasks")

    task = await session.get(HousekeepingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in ["completed", "cancelled"]:
        raise HTTPException(status_code=400, detail=f"Cannot assign task with status '{task.status}'")

    staff = await session.get(Staff, payload.staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    staff_user = await session.get(User, staff.user_id)
    room = await session.get(Room, task.room_id) if task.room_id else None
    room_number = room.number if room else str(task.room_id)

    # Store attributes BEFORE commit to avoid lazy loading issues after commit
    task_type = task.task_type or "housekeeping"
    task_priority = task.priority or "normal"
    task_room_id = task.room_id
    staff_id = staff.id
    staff_name = staff.name
    staff_user_id = staff.user_id

    task.assigned_to = staff_id
    task.status = "assigned"
    task.force_assigned = True
    task.force_assign_reason = payload.reason
    task.force_assigned_by = current_user.id
    task.updated_at = datetime.utcnow()

    if payload.require_acceptance:
        task.acceptance_status = "pending_acceptance"
    else:
        task.acceptance_status = "accepted"
        task.accepted_at = datetime.utcnow()

    await session.commit()

    # Note: StaffNotification.staff_id is FK to users.id, so use staff_user_id
    # Use stored values to avoid lazy loading issues after commit
    notification = StaffNotification(
        staff_id=staff_user_id,
        task_id=task_id,
        room_id=task_room_id,
        notification_type="urgent_task_assigned",
        title=f"URGENT: {task_type.capitalize()} Task Force-Assigned",
        message=f"Room {room_number} - Priority: {task_priority}. Reason: {payload.reason}.",
        is_read=False,
        created_at=datetime.utcnow()
    )
    session.add(notification)
    await session.commit()

    # Send email to staff about the force-assigned task (non-blocking)
    if staff_user:
        from app.services.background_email import send_task_assignment_email_bg
        background_tasks.add_task(
            send_task_assignment_email_bg,
            to_email=staff_user.email,
            staff_name=staff_name,
            task_type=task_type,
            room_number=room_number,
            priority=task_priority,
            notes=f"FORCE-ASSIGNED: {payload.reason}",
        )

    return ForceAssignResponse(
        task_id=task_id,
        staff_id=staff_id,
        staff_name=staff_name,
        success=True,
        message=f"Task force-assigned to {staff_name}.",
        requires_acceptance=payload.require_acceptance,
        force_assigned=True
    )


# ==================== ACCEPT/DECLINE WORKFLOW ====================

class AcceptTaskRequest(BaseModel):
    notes: Optional[str] = None


class DeclineTaskRequest(BaseModel):
    reason: str


class TaskAcceptanceResponse(BaseModel):
    task_id: int
    status: str
    acceptance_status: str
    message: str
    declined_reason: Optional[str] = None


@router.post("/tasks/{task_id}/accept", response_model=TaskAcceptanceResponse)
async def accept_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    payload: Optional[AcceptTaskRequest] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Accept an assigned task. Changes task status to 'in_progress'."""
    from app.models.staff import Staff
    from app.models.guest_chat import StaffNotification

    task = await session.get(HousekeepingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    staff_result = await session.execute(select(Staff).where(Staff.user_id == current_user.id))
    staff = staff_result.scalar_one_or_none()

    if not staff:
        raise HTTPException(status_code=403, detail="Staff record not found")

    if task.assigned_to != staff.id:
        raise HTTPException(status_code=403, detail="You can only accept tasks assigned to you")

    if task.acceptance_status == "accepted":
        return TaskAcceptanceResponse(task_id=task_id, status=task.status, acceptance_status="accepted", message="Task already accepted")

    # Get room info for notifications
    room = await session.get(Room, task.room_id) if task.room_id else None
    room_number = room.number if room else str(task.room_id or "N/A")
    staff_name = staff.name

    task.acceptance_status = "accepted"
    task.accepted_at = datetime.utcnow()
    task.status = "in_progress"
    task.started_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    await session.commit()

    # Notify admin (force assigner) via in-app notification AND email
    if task.force_assigned and task.force_assigned_by:
        notification = StaffNotification(
            staff_id=task.force_assigned_by,
            notification_type="task_accepted",
            title="Force-Assigned Task Accepted",
            message=f"Task #{task_id} accepted by {staff_name}.",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()

        # Send email notification to admin (non-blocking)
        admin_result = await session.execute(select(User).where(User.id == task.force_assigned_by))
        admin_user = admin_result.scalar_one_or_none()
        if admin_user:
            admin_staff_result = await session.execute(select(Staff).where(Staff.user_id == admin_user.id))
            admin_staff = admin_staff_result.scalar_one_or_none()
            admin_name = admin_staff.name if admin_staff else admin_user.email.split("@")[0]
            from app.services.background_email import send_task_accepted_email_bg
            background_tasks.add_task(
                send_task_accepted_email_bg,
                to_email=admin_user.email,
                admin_name=admin_name,
                staff_name=staff_name,
                task_id=task_id,
                task_type=task.task_type or "housekeeping",
                room_number=room_number,
                accepted_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            )

    return TaskAcceptanceResponse(task_id=task_id, status=task.status, acceptance_status="accepted", message="Task accepted and started")


@router.post("/tasks/{task_id}/decline", response_model=TaskAcceptanceResponse)
async def decline_task(
    task_id: int,
    payload: DeclineTaskRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Decline an assigned task with a reason. Task returns to pending."""
    from app.models.staff import Staff
    from app.models.guest_chat import StaffNotification

    task = await session.get(HousekeepingTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    staff_result = await session.execute(select(Staff).where(Staff.user_id == current_user.id))
    staff = staff_result.scalar_one_or_none()

    if not staff:
        raise HTTPException(status_code=403, detail="Staff record not found")

    if task.assigned_to != staff.id:
        raise HTTPException(status_code=403, detail="You can only decline tasks assigned to you")

    room = await session.get(Room, task.room_id) if task.room_id else None
    room_number = room.number if room else str(task.room_id or "N/A")
    declined_by_name = staff.name
    force_assigned_by = task.force_assigned_by
    task_type = task.task_type or "housekeeping"
    task_priority = task.priority or "normal"

    task.acceptance_status = "declined"
    task.decline_reason = payload.reason
    task.declined_at = datetime.utcnow()
    task.assigned_to = None
    task.status = "pending"
    task.force_assigned = False
    task.updated_at = datetime.utcnow()
    await session.commit()

    # Notify admin (force assigner) via in-app notification AND email
    if force_assigned_by:
        notification = StaffNotification(
            staff_id=force_assigned_by,
            notification_type="task_declined",
            title=f"Task Declined - Room {room_number}",
            message=f"Task #{task_id} declined by {declined_by_name}. Reason: {payload.reason}",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()

        # Send email notification to admin (non-blocking)
        admin_result = await session.execute(select(User).where(User.id == force_assigned_by))
        admin_user = admin_result.scalar_one_or_none()
        if admin_user:
            admin_staff_result = await session.execute(select(Staff).where(Staff.user_id == admin_user.id))
            admin_staff = admin_staff_result.scalar_one_or_none()
            admin_name = admin_staff.name if admin_staff else admin_user.email.split("@")[0]
            from app.services.background_email import send_task_declined_email_bg
            background_tasks.add_task(
                send_task_declined_email_bg,
                to_email=admin_user.email,
                admin_name=admin_name,
                staff_name=declined_by_name,
                task_id=task_id,
                task_type=task_type,
                room_number=room_number,
                decline_reason=payload.reason,
                declined_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                priority=task_priority,
            )

    return TaskAcceptanceResponse(task_id=task_id, status="pending", acceptance_status="declined", message="Task declined.", declined_reason=payload.reason)


@router.get("/tasks/pending-acceptance")
async def get_tasks_pending_acceptance(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all tasks pending acceptance for the current staff member."""
    from app.models.staff import Staff

    staff_result = await session.execute(select(Staff).where(Staff.user_id == current_user.id))
    staff = staff_result.scalar_one_or_none()
    if not staff:
        return {"tasks": [], "count": 0}

    tasks_result = await session.execute(
        select(HousekeepingTask).where(
            HousekeepingTask.assigned_to == staff.id,
            HousekeepingTask.acceptance_status == "pending_acceptance"
        ).order_by(HousekeepingTask.priority.desc())
    )
    tasks = tasks_result.scalars().all()

    task_list = []
    for task in tasks:
        room = await session.get(Room, task.room_id) if task.room_id else None
        task_list.append({
            "id": task.id,
            "room_number": room.number if room else str(task.room_id),
            "task_type": task.task_type,
            "priority": task.priority,
            "force_assigned": task.force_assigned,
            "force_assign_reason": task.force_assign_reason,
        })

    return {"tasks": task_list, "count": len(task_list)}


@router.get("/staff/availability-status")
async def get_staff_availability_status(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get overall staff availability status with alert if all staff are busy."""
    from app.services.staff_scheduling_service import get_scheduling_service

    scheduling_service = get_scheduling_service(session)
    workload_summary = await scheduling_service.get_staff_workload_summary(department="housekeeping")

    available_staff = [s for s in workload_summary if s["availability"] == "available"]
    busy_staff = [s for s in workload_summary if s["availability"] != "available"]

    pending_result = await session.execute(select(HousekeepingTask).where(HousekeepingTask.status == "pending"))
    pending_tasks = pending_result.scalars().all()
    pending_count = len(pending_tasks)
    urgent_pending = len([t for t in pending_tasks if t.priority in ["urgent", "high"]])

    all_busy = len(available_staff) == 0 and len(workload_summary) > 0

    response = {
        "total_staff": len(workload_summary),
        "available_count": len(available_staff),
        "busy_count": len(busy_staff),
        "all_staff_busy": all_busy,
        "pending_tasks": pending_count,
        "urgent_pending": urgent_pending,
        "available_staff": [{"id": s["staff_id"], "name": s["name"], "active_tasks": s.get("active_tasks", 0)} for s in available_staff],
        "busy_staff": [{"id": s["staff_id"], "name": s["name"], "active_tasks": s.get("active_tasks", 0)} for s in busy_staff]
    }

    if all_busy:
        response["alert"] = {
            "type": "warning",
            "title": "All Housekeeping Staff Busy",
            "message": f"All {len(workload_summary)} staff occupied. {pending_count} task(s) pending.",
            "urgent_pending": urgent_pending
        }

    return response


# ==================== DIGITAL KEY VALIDATION ====================

class DigitalKeyScanRequest(BaseModel):
    """Request model for scanning/validating a digital key"""
    qr_data: str  # The raw QR code data scanned
    expected_room_number: Optional[str] = None  # Room number being serviced


class DigitalKeyScanResponse(BaseModel):
    """Response model for digital key validation"""
    valid: bool
    result: str  # valid, expired, revoked, wrong_room, wrong_date, invalid_code
    message: str
    scanned_at: str
    key_code: Optional[str] = None
    room_number: Optional[str] = None
    guest_name: Optional[str] = None
    guest_id: Optional[int] = None
    check_in_date: Optional[str] = None
    check_out_date: Optional[str] = None
    booking_id: Optional[int] = None
    reservation_id: Optional[int] = None
    scan_count: Optional[int] = None
    valid_until: Optional[str] = None


@router.post("/digital-key/scan", response_model=DigitalKeyScanResponse)
async def scan_digital_key(
    payload: DigitalKeyScanRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Scan and validate a guest's digital key QR code.

    Housekeeping staff can scan the QR code on a guest's phone/email to:
    - Verify the guest has a valid booking for that room on the current date
    - Confirm the room can be serviced
    - Log the validation for audit purposes

    Returns validation result with guest and booking details if valid.
    """
    from app.services.digital_key_service import get_digital_key_service
    from app.models.staff import Staff

    # Get staff ID for the current user
    staff_result = await session.execute(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.scalar_one_or_none()

    if not staff:
        raise HTTPException(
            status_code=403,
            detail="Only staff members can scan digital keys"
        )

    digital_key_service = get_digital_key_service(session)

    # Validate the key
    result = await digital_key_service.validate_key(
        qr_data=payload.qr_data,
        staff_id=staff.id,
        expected_room_number=payload.expected_room_number,
        scan_location="housekeeping"
    )

    return DigitalKeyScanResponse(**result)


@router.get("/digital-key/room/{room_number}")
async def get_active_digital_key_for_room(
    room_number: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get the active digital key for a room.

    Housekeeping can use this to verify if a room has an active booking
    before servicing without needing to scan a QR code.
    """
    from app.services.digital_key_service import get_digital_key_service
    from app.models.reservations import Guest

    digital_key_service = get_digital_key_service(session)
    digital_key = await digital_key_service.get_active_key_for_room(room_number)

    if not digital_key:
        return {
            "has_active_key": False,
            "room_number": room_number,
            "message": "No active digital key for this room. Room may be vacant or guest hasn't completed pre-checkin."
        }

    # Get guest info
    guest_result = await session.execute(
        select(Guest).where(Guest.id == digital_key.guest_id)
    )
    guest = guest_result.scalar_one_or_none()

    return {
        "has_active_key": True,
        "room_number": room_number,
        "key_code": digital_key.key_code,
        "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
        "guest_id": digital_key.guest_id,
        "check_in_date": digital_key.check_in_date.isoformat(),
        "check_out_date": digital_key.check_out_date.isoformat(),
        "booking_id": digital_key.booking_id,
        "reservation_id": digital_key.reservation_id,
        "status": digital_key.status,
        "scan_count": digital_key.scan_count,
        "last_scanned_at": digital_key.last_scanned_at.isoformat() if digital_key.last_scanned_at else None
    }


@router.get("/digital-key/scan-history")
async def get_digital_key_scan_history(
    room_number: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get scan history for digital keys.

    Can filter by room number to see all scans for a specific room.
    Useful for audit purposes and tracking staff activities.
    """
    from app.services.digital_key_service import get_digital_key_service
    from app.models.staff import Staff
    from app.models.operations import DigitalKeyScan

    digital_key_service = get_digital_key_service(session)
    scans = await digital_key_service.get_scan_history(
        room_number=room_number,
        limit=limit
    )

    # Enrich with staff names
    results = []
    for scan in scans:
        staff_result = await session.execute(
            select(Staff).where(Staff.id == scan.scanned_by)
        )
        staff = staff_result.scalar_one_or_none()

        results.append({
            "id": scan.id,
            "scanned_at": scan.scanned_at.isoformat(),
            "scanned_by": {
                "id": staff.id if staff else None,
                "name": staff.name if staff else "Unknown"
            },
            "is_valid": scan.is_valid,
            "validation_result": scan.validation_result,
            "scan_location": scan.scan_location,
            "room_number": scan.room_number,
            "notes": scan.notes
        })

    return {
        "total": len(results),
        "room_number": room_number,
        "scans": results
    }








