"""
Maintenance API Endpoints
Handles work orders, equipment issues, and maintenance tracking
"""
from typing import List, Optional
from datetime import datetime, date, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import select, and_, or_, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel
import uuid

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.staff import Staff
from app.models.maintenance import EquipmentIssues, MaintenanceParts, Vendors, MaintenanceInventory, PreventiveMaintenanceSchedule
from app.models.operations import MaintenanceRequest
from app.models.inventory import Room, RoomType
from app.services.admin_notification_service import notify_maintenance_request

router = APIRouter()


# ============== SCHEMAS ==============

class WorkOrderCreate(BaseModel):
    title: str
    description: str
    location: str
    room_id: Optional[int] = None
    room_number: Optional[str] = None
    issue_type: str  # plumbing, electrical, hvac, structural, appliance, other
    priority: str = "medium"  # low, medium, high, critical
    scheduled_date: Optional[date] = None
    estimated_hours: Optional[float] = None
    notes: Optional[str] = None
    assigned_to: Optional[int] = None  # Technician staff ID to assign


class WorkOrderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None
    scheduled_date: Optional[date] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    resolution_notes: Optional[str] = None
    notes: Optional[str] = None


class WorkOrderRead(BaseModel):
    id: int
    work_order_number: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    room_id: Optional[int] = None
    room_number: Optional[str] = None
    issue_type: Optional[str] = None
    priority: str
    status: str
    reported_by: Optional[int] = None
    reported_by_name: Optional[str] = None
    reported_at: datetime
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    accepted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    scheduled_date: Optional[date] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    resolution_notes: Optional[str] = None
    notes: Optional[str] = None
    parts_used: Optional[List[dict]] = None
    is_out_of_order: bool = False
    ooo_category: Optional[str] = None
    estimated_completion: Optional[datetime] = None

    class Config:
        from_attributes = True


class EquipmentIssueCreate(BaseModel):
    equipment_name: str
    equipment_id: Optional[str] = None
    equipment_category: Optional[str] = None  # hvac, elevator, kitchen, pool, generator, safety, laundry, other
    location: str
    room_id: Optional[int] = None
    issue_type: str
    issue_description: str
    severity: str  # low, medium, high, critical
    affects_operations: bool = False
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None


class EquipmentIssueUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[int] = None
    severity: Optional[str] = None
    resolution_notes: Optional[str] = None
    estimated_repair_cost: Optional[float] = None
    actual_repair_cost: Optional[float] = None
    downtime_hours: Optional[float] = None


class EquipmentIssueRead(BaseModel):
    id: int
    issue_number: str
    equipment_name: str
    equipment_id: Optional[str] = None
    equipment_category: Optional[str] = None
    location: str
    room_id: Optional[int] = None
    issue_type: str
    issue_description: str
    severity: str
    status: str
    reported_by: int
    reported_by_name: Optional[str] = None
    reported_at: datetime
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    accepted_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    warranty_status: Optional[str] = None
    warranty_expiry_date: Optional[date] = None
    estimated_repair_cost: Optional[float] = None
    actual_repair_cost: Optional[float] = None
    affects_operations: bool = False

    class Config:
        from_attributes = True


class MaintenanceDashboard(BaseModel):
    open_work_orders: int
    critical_issues: int
    completed_today: int
    pending_parts: int
    avg_completion_time: Optional[float] = None
    overdue_count: int


class MaintenanceTask(BaseModel):
    id: int
    title: str
    description: str
    location: str
    priority: str
    status: str
    task_type: str
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    due_date: Optional[datetime] = None
    created_at: datetime


# ===== Preventive Maintenance Schemas =====

class PMScheduleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    location: str = ""
    maintenance_type: str = "general"
    frequency: str = "monthly"
    estimated_duration: int = 60
    assigned_to: Optional[int] = None
    priority: str = "normal"
    next_due_date: Optional[date] = None
    checklist: Optional[list] = None

class PMScheduleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    maintenance_type: Optional[str] = None
    frequency: Optional[str] = None
    estimated_duration: Optional[int] = None
    assigned_to: Optional[int] = None
    priority: Optional[str] = None
    active: Optional[bool] = None
    next_due_date: Optional[date] = None
    last_performed: Optional[date] = None

class PMScheduleRead(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    location: str
    maintenance_type: str
    frequency: str
    estimated_duration: int
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    priority: str
    active: bool
    last_performed: Optional[date] = None
    next_due_date: Optional[date] = None
    total_completions: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============== WORK ORDER ENDPOINTS ==============

@router.get("/work-orders", response_model=List[WorkOrderRead])
async def list_work_orders(
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    issue_type: Optional[str] = Query(None, description="Filter by issue type"),
    assigned_to: Optional[int] = Query(None, description="Filter by assigned staff"),
    room_number: Optional[str] = Query(None, description="Filter by room"),
    date_from: Optional[date] = Query(None, description="Filter from date"),
    date_to: Optional[date] = Query(None, description="Filter to date"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List all work orders with optional filters"""
    query = select(MaintenanceRequest)

    conditions = []
    if status:
        # Map frontend status values to backend equivalents for filtering
        # Frontend uses "open" but backend stores as "pending"
        status_map = {"open": "pending"}
        mapped_status = status_map.get(status, status)
        conditions.append(MaintenanceRequest.status == mapped_status)
    if priority:
        conditions.append(MaintenanceRequest.priority == priority)
    if issue_type:
        conditions.append(MaintenanceRequest.issue_type == issue_type)
    if assigned_to:
        conditions.append(MaintenanceRequest.assigned_to == assigned_to)
    if room_number:
        conditions.append(MaintenanceRequest.room_number == room_number)
    if date_from:
        conditions.append(MaintenanceRequest.reported_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conditions.append(MaintenanceRequest.reported_at <= datetime.combine(date_to, datetime.max.time()))

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(MaintenanceRequest.reported_at.desc())

    result = await session.exec(query)
    work_orders = result.all()

    # Enrich with staff names and parts
    work_order_list = []
    for wo in work_orders:
        # Normalize status: map "pending" to "open" for frontend consistency
        normalized_status = "open" if wo.status == "pending" else wo.status

        wo_dict = {
            "id": wo.id,
            "work_order_number": getattr(wo, 'work_order_number', f"WO-{wo.id}"),
            "title": wo.title,
            "description": wo.description,
            "location": wo.location,
            "room_id": wo.room_id,
            "room_number": wo.room_number,
            "issue_type": wo.issue_type,
            "priority": wo.priority,
            "status": normalized_status,
            "reported_by": wo.reported_by,
            "reported_by_name": None,
            "reported_at": wo.reported_at,
            "assigned_to": wo.assigned_to,
            "assigned_to_name": None,
            "accepted_at": getattr(wo, 'accepted_at', None),
            "started_at": getattr(wo, 'started_at', None),
            "completed_at": wo.completed_at,
            "scheduled_date": getattr(wo, 'scheduled_date', None),
            "estimated_hours": round(wo.estimated_duration / 60, 1) if wo.estimated_duration else None,
            "actual_hours": getattr(wo, 'actual_hours', None),
            "resolution_notes": wo.resolution_notes,
            "notes": getattr(wo, 'notes', None),
            "parts_used": [],
            "is_out_of_order": getattr(wo, 'is_out_of_order', False),
            "ooo_category": getattr(wo, 'ooo_category', None),
            "estimated_completion": getattr(wo, 'estimated_completion', None),
        }

        if wo.assigned_to:
            staff_result = await session.exec(
                select(Staff).where(Staff.id == wo.assigned_to)
            )
            staff = staff_result.first()
            if staff:
                wo_dict["assigned_to_name"] = staff.name

        if wo.reported_by:
            reporter_result = await session.exec(
                select(Staff).where(Staff.id == wo.reported_by)
            )
            reporter = reporter_result.first()
            if reporter:
                wo_dict["reported_by_name"] = reporter.name

        # Fetch parts used for this work order
        parts_result = await session.exec(
            select(MaintenanceParts).where(MaintenanceParts.work_order_id == wo.id)
        )
        parts = parts_result.all()
        if parts:
            wo_dict["parts_used"] = [
                {"name": p.part_name, "quantity": p.quantity, "cost": p.total_cost}
                for p in parts
            ]

        work_order_list.append(WorkOrderRead(**wo_dict))

    return work_order_list


@router.get("/rooms/oos-ooo")
async def get_oos_ooo_rooms(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get all rooms with out_of_service or out_of_order status,
    including those that do NOT have a maintenance work order.
    """
    # Rooms with OOS/OOO status
    rooms_result = await session.exec(
        select(Room, RoomType)
        .join(RoomType, Room.room_type_id == RoomType.id, isouter=True)
        .where(Room.status.in_(["out_of_service", "out_of_order", "maintenance"]))
        .order_by(Room.number)
    )
    rooms = rooms_result.all()

    # Find which rooms already have an active (non-completed) work order
    room_ids = [r.id for r, rt in rooms]
    linked_room_ids = set()
    if room_ids:
        linked_result = await session.exec(
            select(MaintenanceRequest.room_id).where(
                and_(
                    MaintenanceRequest.room_id.in_(room_ids),
                    MaintenanceRequest.status.notin_(["completed", "cancelled"]),
                )
            )
        )
        linked_room_ids = {rid for rid in linked_result.all() if rid is not None}

    items = []
    for room, room_type in rooms:
        status_label = {
            "out_of_service": "Out of Service",
            "out_of_order": "Out of Order",
            "maintenance": "Maintenance",
        }.get(room.status, room.status)

        items.append({
            "id": room.id,
            "number": room.number,
            "floor": room.floor,
            "status": room.status,
            "statusLabel": status_label,
            "roomType": room_type.name if room_type else "Standard",
            "condition": room.condition,
            "notes": room.notes,
            "lastMaintenance": room.last_maintenance.isoformat() if room.last_maintenance else None,
            "hasWorkOrder": room.id in linked_room_ids,
        })

    return {"success": True, "data": items, "total": len(items)}


@router.get("/work-orders/my-tasks", response_model=List[WorkOrderRead])
async def get_my_work_orders(
    status: Optional[str] = Query(None, description="Filter by status"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get work orders assigned to the current user"""
    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        return []

    query = select(MaintenanceRequest).where(
        MaintenanceRequest.assigned_to == staff.id
    )

    if status:
        query = query.where(MaintenanceRequest.status == status)
    else:
        # Default: show active work orders
        query = query.where(MaintenanceRequest.status.in_(["pending", "in_progress", "assigned"]))

    query = query.order_by(MaintenanceRequest.priority.desc(), MaintenanceRequest.reported_at.asc())

    result = await session.exec(query)
    work_orders = result.all()

    return [WorkOrderRead(
        id=wo.id,
        work_order_number=getattr(wo, 'work_order_number', f"WO-{wo.id}"),
        title=wo.title,
        description=wo.description,
        location=wo.location,
        room_id=wo.room_id,
        room_number=wo.room_number,
        issue_type=wo.issue_type,
        priority=wo.priority,
        status=wo.status,
        reported_by=wo.reported_by,
        reported_at=wo.reported_at,
        assigned_to=wo.assigned_to,
        assigned_to_name=staff.name,
        completed_at=wo.completed_at,
        resolution_notes=wo.resolution_notes
    ) for wo in work_orders]


@router.post("/work-orders", response_model=WorkOrderRead)
async def create_work_order(
    payload: WorkOrderCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new work order"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        # Find staff record for current user (reporter)
        staff_result = await session.exec(
            select(Staff).where(Staff.user_id == current_user.id)
        )
        staff = staff_result.first()

        # Find room if room_number provided
        room_id = payload.room_id
        if payload.room_number and not room_id:
            room_result = await session.exec(
                select(Room).where(Room.number == payload.room_number)
            )
            room = room_result.first()
            if room:
                room_id = room.id

        # Generate unique work order ID
        work_order_id = f"WO-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

        work_order = MaintenanceRequest(
            work_order_id=work_order_id,
            title=payload.title,
            description=payload.description,
            location=payload.location,
            room_id=room_id,
            room_number=payload.room_number,
            category=payload.issue_type,  # Required field
            issue_type=payload.issue_type,
            issue=payload.description,  # Required field - use description as issue
            priority=payload.priority,
            status="pending",
            reported_by=staff.id if staff else None,
            reported_at=datetime.utcnow(),
            assigned_to=payload.assigned_to,  # Assign technician if provided
            scheduled_date=payload.scheduled_date,
            estimated_duration=int(payload.estimated_hours * 60) if payload.estimated_hours else None,
        )

        session.add(work_order)
        await session.commit()
        await session.refresh(work_order)

        # Notify admins about new maintenance request
        try:
            await notify_maintenance_request(
                session=session,
                room_number=payload.room_number or "N/A",
                issue_type=payload.issue_type,
                priority=payload.priority,
                description=payload.description[:100] if payload.description else "N/A",
                request_id=work_order.id
            )
            await session.commit()
        except Exception as notif_error:
            logger.error(f"Failed to send maintenance notification: {notif_error}")

        # Normalize status for frontend (pending -> open)
        normalized_status = "open" if work_order.status == "pending" else work_order.status

        # Lookup assigned technician name if assigned
        assigned_to_name = None
        if work_order.assigned_to:
            assigned_staff_result = await session.exec(
                select(Staff).where(Staff.id == work_order.assigned_to)
            )
            assigned_staff = assigned_staff_result.first()
            if assigned_staff:
                assigned_to_name = assigned_staff.name

        return WorkOrderRead(
            id=work_order.id,
            work_order_number=f"WO-{work_order.id}",
            title=work_order.title,
            description=work_order.description,
            location=work_order.location,
            room_id=work_order.room_id,
            room_number=work_order.room_number,
            issue_type=work_order.issue_type,
            priority=work_order.priority,
            status=normalized_status,
            reported_by=work_order.reported_by,
            reported_by_name=staff.name if staff else None,
            reported_at=work_order.reported_at,
            assigned_to=work_order.assigned_to,
            assigned_to_name=assigned_to_name,
            scheduled_date=work_order.scheduled_date,
            estimated_hours=round(work_order.estimated_duration / 60, 1) if work_order.estimated_duration else None,
            parts_used=[]
        )
    except Exception as e:
        logger.error(f"Error creating work order: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderRead)
async def get_work_order(
    work_order_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a specific work order"""
    result = await session.exec(
        select(MaintenanceRequest).where(MaintenanceRequest.id == work_order_id)
    )
    wo = result.first()

    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    # Normalize status: map "pending" to "open" for frontend consistency
    normalized_status = "open" if wo.status == "pending" else wo.status

    wo_dict = {
        "id": wo.id,
        "work_order_number": getattr(wo, 'work_order_number', f"WO-{wo.id}"),
        "title": wo.title,
        "description": wo.description,
        "location": wo.location,
        "room_id": wo.room_id,
        "room_number": wo.room_number,
        "issue_type": wo.issue_type,
        "priority": wo.priority,
        "status": normalized_status,
        "reported_by": wo.reported_by,
        "reported_by_name": None,
        "reported_at": wo.reported_at,
        "assigned_to": wo.assigned_to,
        "assigned_to_name": None,
        "accepted_at": getattr(wo, 'accepted_at', None),
        "started_at": getattr(wo, 'started_at', None),
        "completed_at": wo.completed_at,
        "scheduled_date": getattr(wo, 'scheduled_date', None),
        "estimated_hours": round(wo.estimated_duration / 60, 1) if wo.estimated_duration else None,
        "actual_hours": getattr(wo, 'actual_hours', None),
        "resolution_notes": wo.resolution_notes,
        "notes": getattr(wo, 'notes', None),
        "parts_used": []
    }

    if wo.assigned_to:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == wo.assigned_to)
        )
        staff = staff_result.first()
        if staff:
            wo_dict["assigned_to_name"] = staff.name

    # Fetch reported_by staff name
    if wo.reported_by:
        reporter_result = await session.exec(
            select(Staff).where(Staff.id == wo.reported_by)
        )
        reporter = reporter_result.first()
        if reporter:
            wo_dict["reported_by_name"] = reporter.name

    # Fetch parts used for this work order
    parts_result = await session.exec(
        select(MaintenanceParts).where(MaintenanceParts.work_order_id == wo.id)
    )
    parts = parts_result.all()
    if parts:
        wo_dict["parts_used"] = [
            {"name": p.part_name, "quantity": p.quantity, "cost": p.total_cost}
            for p in parts
        ]

    return WorkOrderRead(**wo_dict)


@router.patch("/work-orders/{work_order_id}", response_model=WorkOrderRead)
async def update_work_order(
    work_order_id: int,
    payload: WorkOrderUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a work order"""
    result = await session.exec(
        select(MaintenanceRequest).where(MaintenanceRequest.id == work_order_id)
    )
    wo = result.first()

    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    # Check if assigned_to is being updated (new assignment)
    new_assignment = payload.assigned_to is not None and payload.assigned_to != wo.assigned_to

    update_data = payload.dict(exclude_unset=True)

    # Convert schema fields to model fields (schema uses hours, model uses minutes)
    if 'estimated_hours' in update_data:
        hours = update_data.pop('estimated_hours')
        update_data['estimated_duration'] = int(hours * 60) if hours else None
    if 'actual_hours' in update_data:
        hours = update_data.pop('actual_hours')
        update_data['actual_duration'] = int(hours * 60) if hours else None

    for field, value in update_data.items():
        if hasattr(wo, field):
            setattr(wo, field, value)

    wo.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(wo)

    # Send notification and email if newly assigned
    if new_assignment and payload.assigned_to:
        try:
            # Get staff info
            staff_result = await session.exec(
                select(Staff).where(Staff.id == payload.assigned_to)
            )
            staff = staff_result.first()

            if staff:
                # Create notification
                from app.models.guest_chat import StaffNotification
                notification = StaffNotification(
                    staff_id=payload.assigned_to,
                    notification_type="task_assigned",
                    title=f"New Maintenance Work Order Assigned",
                    message=f"You have been assigned work order: {wo.title}. Location: {wo.location}. Priority: {wo.priority or 'normal'}.",
                    is_read=False,
                    created_at=datetime.utcnow()
                )
                session.add(notification)
                await session.commit()

                # Send email in background
                from app.services.background_email import send_task_assignment_email_bg
                background_tasks.add_task(
                    send_task_assignment_email_bg,
                    to_email=staff.email,
                    staff_name=staff.name,
                    task_type="maintenance",
                    room_number=wo.room_number or wo.location,
                    priority=wo.priority or "normal",
                    notes=wo.description,
                )
        except Exception as e:
            import logging
            logging.error(f"Failed to create notification: {e}")

    # Get staff names for response
    assigned_to_name = None
    reported_by_name = None
    
    if wo.assigned_to:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == wo.assigned_to)
        )
        staff = staff_result.first()
        if staff:
            assigned_to_name = staff.name

    if wo.reported_by:
        reporter_result = await session.exec(
            select(Staff).where(Staff.id == wo.reported_by)
        )
        reporter = reporter_result.first()
        if reporter:
            reported_by_name = reporter.name

    # Fetch parts used
    parts_used = []
    parts_result = await session.exec(
        select(MaintenanceParts).where(MaintenanceParts.work_order_id == wo.id)
    )
    parts = parts_result.all()
    if parts:
        parts_used = [
            {"name": p.part_name, "quantity": p.quantity, "cost": p.total_cost}
            for p in parts
        ]

    # Normalize status for frontend
    normalized_status = "open" if wo.status == "pending" else wo.status

    return WorkOrderRead(
        id=wo.id,
        work_order_number=f"WO-{wo.id}",
        title=wo.title,
        description=wo.description,
        location=wo.location,
        room_id=wo.room_id,
        room_number=wo.room_number,
        issue_type=wo.issue_type,
        priority=wo.priority,
        status=normalized_status,
        reported_by=wo.reported_by,
        reported_by_name=reported_by_name,
        reported_at=wo.reported_at,
        assigned_to=wo.assigned_to,
        assigned_to_name=assigned_to_name,
        accepted_at=getattr(wo, 'accepted_at', None),
        started_at=getattr(wo, 'started_at', None),
        completed_at=wo.completed_at,
        scheduled_date=getattr(wo, 'scheduled_date', None),
        estimated_hours=round(wo.estimated_duration / 60, 1) if wo.estimated_duration else None,
        actual_hours=getattr(wo, 'actual_hours', None),
        resolution_notes=wo.resolution_notes,
        notes=getattr(wo, 'notes', None),
        parts_used=parts_used
    )


@router.post("/work-orders/{work_order_id}/accept", response_model=WorkOrderRead)
async def accept_work_order(
    work_order_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Accept/assign a work order to the current user"""
    result = await session.exec(
        select(MaintenanceRequest).where(MaintenanceRequest.id == work_order_id)
    )
    wo = result.first()

    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        raise HTTPException(status_code=400, detail="Staff record not found for current user")

    wo.assigned_to = staff.id
    wo.status = "in_progress"
    wo.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(wo)

    return WorkOrderRead(
        id=wo.id,
        work_order_number=f"WO-{wo.id}",
        title=wo.title,
        description=wo.description,
        location=wo.location,
        room_id=wo.room_id,
        room_number=wo.room_number,
        issue_type=wo.issue_type,
        priority=wo.priority,
        status=wo.status,
        reported_by=wo.reported_by,
        reported_at=wo.reported_at,
        assigned_to=wo.assigned_to,
        assigned_to_name=staff.name,
        completed_at=wo.completed_at,
        resolution_notes=wo.resolution_notes,
        parts_used=[]
    )


@router.post("/work-orders/{work_order_id}/complete", response_model=WorkOrderRead)
async def complete_work_order(
    work_order_id: int,
    resolution_notes: Optional[str] = None,
    actual_hours: Optional[float] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark a work order as completed"""
    result = await session.exec(
        select(MaintenanceRequest).where(MaintenanceRequest.id == work_order_id)
    )
    wo = result.first()

    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    wo.status = "completed"
    wo.completed_at = datetime.utcnow()
    if resolution_notes:
        wo.resolution_notes = resolution_notes
    wo.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(wo)

    # Fetch parts used
    parts_used = []
    parts_result = await session.exec(
        select(MaintenanceParts).where(MaintenanceParts.work_order_id == wo.id)
    )
    parts = parts_result.all()
    if parts:
        parts_used = [
            {"name": p.part_name, "quantity": p.quantity, "cost": p.total_cost}
            for p in parts
        ]

    return WorkOrderRead(
        id=wo.id,
        work_order_number=f"WO-{wo.id}",
        title=wo.title,
        description=wo.description,
        location=wo.location,
        room_id=wo.room_id,
        room_number=wo.room_number,
        issue_type=wo.issue_type,
        priority=wo.priority,
        status=wo.status,
        reported_by=wo.reported_by,
        reported_at=wo.reported_at,
        assigned_to=wo.assigned_to,
        completed_at=wo.completed_at,
        resolution_notes=wo.resolution_notes,
        parts_used=parts_used
    )


# ============== EQUIPMENT ISSUE ENDPOINTS ==============

@router.get("/equipment-issues", response_model=List[EquipmentIssueRead])
async def list_equipment_issues(
    status: Optional[str] = Query(None, description="Filter by status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    category: Optional[str] = Query(None, description="Filter by equipment category"),
    assigned_to: Optional[int] = Query(None, description="Filter by assigned staff"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List all equipment issues"""
    query = select(EquipmentIssues)

    conditions = []
    if status:
        conditions.append(EquipmentIssues.status == status)
    if severity:
        conditions.append(EquipmentIssues.severity == severity)
    if category:
        conditions.append(EquipmentIssues.equipment_category == category)
    if assigned_to:
        conditions.append(EquipmentIssues.assigned_to == assigned_to)

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(EquipmentIssues.reported_at.desc())

    result = await session.exec(query)
    issues = result.all()

    # Enrich with staff names
    issue_list = []
    for issue in issues:
        issue_dict = {k: v for k, v in issue.__dict__.items() if not k.startswith('_')}
        issue_dict["reported_by_name"] = None
        issue_dict["assigned_to_name"] = None

        if issue.reported_by:
            staff_result = await session.exec(
                select(Staff).where(Staff.id == issue.reported_by)
            )
            staff = staff_result.first()
            if staff:
                issue_dict["reported_by_name"] = staff.name

        if issue.assigned_to:
            staff_result = await session.exec(
                select(Staff).where(Staff.id == issue.assigned_to)
            )
            staff = staff_result.first()
            if staff:
                issue_dict["assigned_to_name"] = staff.name

        issue_list.append(EquipmentIssueRead(**issue_dict))

    return issue_list


@router.post("/equipment-issues", response_model=EquipmentIssueRead)
async def create_equipment_issue(
    payload: EquipmentIssueCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Report a new equipment issue"""
    # Find staff record for current user (reporter)
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        raise HTTPException(status_code=400, detail="Staff record not found for current user")

    # Generate issue number
    issue_number = f"EQ-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    issue = EquipmentIssues(
        issue_number=issue_number,
        equipment_name=payload.equipment_name,
        equipment_id=payload.equipment_id,
        equipment_category=payload.equipment_category,
        location=payload.location,
        room_id=payload.room_id,
        issue_type=payload.issue_type,
        issue_description=payload.issue_description,
        severity=payload.severity,
        affects_operations=payload.affects_operations,
        manufacturer=payload.manufacturer,
        model_number=payload.model_number,
        serial_number=payload.serial_number,
        reported_by=staff.id,
        reported_at=datetime.utcnow(),
        status="pending"
    )

    session.add(issue)
    await session.commit()
    await session.refresh(issue)

    return EquipmentIssueRead(
        **{k: v for k, v in issue.__dict__.items() if not k.startswith('_')},
        reported_by_name=staff.name
    )


@router.get("/equipment-issues/{issue_id}", response_model=EquipmentIssueRead)
async def get_equipment_issue(
    issue_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a specific equipment issue"""
    result = await session.exec(
        select(EquipmentIssues).where(EquipmentIssues.id == issue_id)
    )
    issue = result.first()

    if not issue:
        raise HTTPException(status_code=404, detail="Equipment issue not found")

    issue_dict = {k: v for k, v in issue.__dict__.items() if not k.startswith('_')}
    issue_dict["reported_by_name"] = None
    issue_dict["assigned_to_name"] = None

    if issue.reported_by:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == issue.reported_by)
        )
        staff = staff_result.first()
        if staff:
            issue_dict["reported_by_name"] = staff.name

    if issue.assigned_to:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == issue.assigned_to)
        )
        staff = staff_result.first()
        if staff:
            issue_dict["assigned_to_name"] = staff.name

    return EquipmentIssueRead(**issue_dict)


@router.patch("/equipment-issues/{issue_id}", response_model=EquipmentIssueRead)
async def update_equipment_issue(
    issue_id: int,
    payload: EquipmentIssueUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update an equipment issue"""
    result = await session.exec(
        select(EquipmentIssues).where(EquipmentIssues.id == issue_id)
    )
    issue = result.first()

    if not issue:
        raise HTTPException(status_code=404, detail="Equipment issue not found")

    # Check if assigned_to is being updated (new assignment)
    new_assignment = payload.assigned_to is not None and payload.assigned_to != issue.assigned_to

    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(issue, field, value)

    if payload.status == "resolved":
        issue.resolved_at = datetime.utcnow()

    issue.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(issue)

    # Send notification and email if newly assigned
    if new_assignment and payload.assigned_to:
        try:
            # Get staff info
            staff_result = await session.exec(
                select(Staff).where(Staff.id == payload.assigned_to)
            )
            staff = staff_result.first()

            if staff:
                # Create notification
                from app.models.guest_chat import StaffNotification
                notification = StaffNotification(
                    staff_id=payload.assigned_to,
                    notification_type="task_assigned",
                    title=f"Equipment Issue Assigned: {issue.equipment_name}",
                    message=f"You have been assigned to fix {issue.equipment_name} at {issue.location}. Severity: {issue.severity}.",
                    is_read=False,
                    created_at=datetime.utcnow()
                )
                session.add(notification)
                await session.commit()

                # Send email in background
                from app.services.background_email import send_task_assignment_email_bg
                background_tasks.add_task(
                    send_task_assignment_email_bg,
                    to_email=staff.email,
                    staff_name=staff.name,
                    task_type="equipment repair",
                    room_number=issue.location,
                    priority=issue.severity or "normal",
                    notes=issue.issue_description,
                )
        except Exception as e:
            import logging
            logging.error(f"Failed to create notification: {e}")

    return EquipmentIssueRead(**{k: v for k, v in issue.__dict__.items() if not k.startswith('_')})


@router.post("/equipment-issues/{issue_id}/accept", response_model=EquipmentIssueRead)
async def accept_equipment_issue(
    issue_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Accept/assign an equipment issue to the current user"""
    result = await session.exec(
        select(EquipmentIssues).where(EquipmentIssues.id == issue_id)
    )
    issue = result.first()

    if not issue:
        raise HTTPException(status_code=404, detail="Equipment issue not found")

    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        raise HTTPException(status_code=400, detail="Staff record not found for current user")

    issue.assigned_to = staff.id
    issue.accepted_at = datetime.utcnow()
    issue.status = "in_progress"
    issue.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(issue)

    return EquipmentIssueRead(
        **{k: v for k, v in issue.__dict__.items() if not k.startswith('_')},
        assigned_to_name=staff.name
    )


@router.post("/equipment-issues/{issue_id}/resolve", response_model=EquipmentIssueRead)
async def resolve_equipment_issue(
    issue_id: int,
    resolution_notes: Optional[str] = None,
    actual_repair_cost: Optional[float] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark an equipment issue as resolved"""
    result = await session.exec(
        select(EquipmentIssues).where(EquipmentIssues.id == issue_id)
    )
    issue = result.first()

    if not issue:
        raise HTTPException(status_code=404, detail="Equipment issue not found")

    issue.status = "resolved"
    issue.resolved_at = datetime.utcnow()
    if resolution_notes:
        issue.resolution_notes = resolution_notes
    if actual_repair_cost:
        issue.actual_repair_cost = actual_repair_cost

    issue.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(issue)

    return EquipmentIssueRead(**{k: v for k, v in issue.__dict__.items() if not k.startswith('_')})


# ============== DASHBOARD ==============

@router.get("/dashboard", response_model=MaintenanceDashboard)
async def get_maintenance_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get maintenance dashboard statistics"""
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # Open work orders
    open_wo_result = await session.exec(
        select(func.count(MaintenanceRequest.id)).where(
            MaintenanceRequest.status.in_(["pending", "in_progress", "assigned"])
        )
    )
    open_work_orders = open_wo_result.one() or 0

    # Critical issues
    critical_result = await session.exec(
        select(func.count(EquipmentIssues.id)).where(
            and_(
                EquipmentIssues.severity == "critical",
                EquipmentIssues.status.in_(["pending", "in_progress"])
            )
        )
    )
    critical_issues = critical_result.one() or 0

    # Completed today
    completed_wo_result = await session.exec(
        select(func.count(MaintenanceRequest.id)).where(
            and_(
                MaintenanceRequest.status == "completed",
                MaintenanceRequest.completed_at >= today_start,
                MaintenanceRequest.completed_at <= today_end
            )
        )
    )
    completed_today = completed_wo_result.one() or 0

    # Pending parts (equipment issues requiring parts)
    pending_parts_result = await session.exec(
        select(func.count(EquipmentIssues.id)).where(
            EquipmentIssues.status == "requires_parts"
        )
    )
    pending_parts = pending_parts_result.one() or 0

    # Overdue work orders (older than 3 days and not completed)
    three_days_ago = datetime.utcnow() - timedelta(days=3)
    overdue_result = await session.exec(
        select(func.count(MaintenanceRequest.id)).where(
            and_(
                MaintenanceRequest.status.in_(["pending", "in_progress"]),
                MaintenanceRequest.reported_at < three_days_ago
            )
        )
    )
    overdue_count = overdue_result.one() or 0

    return MaintenanceDashboard(
        open_work_orders=open_work_orders,
        critical_issues=critical_issues,
        completed_today=completed_today,
        pending_parts=pending_parts,
        avg_completion_time=None,
        overdue_count=overdue_count
    )


@router.get("/my-dashboard", response_model=MaintenanceDashboard)
async def get_my_maintenance_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get dashboard statistics for the current maintenance staff"""
    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        return MaintenanceDashboard(
            open_work_orders=0,
            critical_issues=0,
            completed_today=0,
            pending_parts=0,
            overdue_count=0
        )

    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # My open work orders
    open_wo_result = await session.exec(
        select(func.count(MaintenanceRequest.id)).where(
            and_(
                MaintenanceRequest.assigned_to == staff.id,
                MaintenanceRequest.status.in_(["pending", "in_progress", "assigned"])
            )
        )
    )
    open_work_orders = open_wo_result.one() or 0

    # My critical issues
    critical_result = await session.exec(
        select(func.count(EquipmentIssues.id)).where(
            and_(
                EquipmentIssues.assigned_to == staff.id,
                EquipmentIssues.severity == "critical",
                EquipmentIssues.status.in_(["pending", "in_progress"])
            )
        )
    )
    critical_issues = critical_result.one() or 0

    # My completed today
    completed_wo_result = await session.exec(
        select(func.count(MaintenanceRequest.id)).where(
            and_(
                MaintenanceRequest.assigned_to == staff.id,
                MaintenanceRequest.status == "completed",
                MaintenanceRequest.completed_at >= today_start,
                MaintenanceRequest.completed_at <= today_end
            )
        )
    )
    completed_today = completed_wo_result.one() or 0

    return MaintenanceDashboard(
        open_work_orders=open_work_orders,
        critical_issues=critical_issues,
        completed_today=completed_today,
        pending_parts=0,
        overdue_count=0
    )


# ============== PREVENTIVE MAINTENANCE ENDPOINTS ==============

@router.get("/preventive-schedules", response_model=List[PMScheduleRead])
async def list_preventive_schedules(
    active_only: Optional[bool] = Query(None, description="Filter by active status"),
    maintenance_type: Optional[str] = Query(None, description="Filter by maintenance type"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List all preventive maintenance schedules"""
    query = select(PreventiveMaintenanceSchedule)

    conditions = []
    if active_only is not None:
        conditions.append(PreventiveMaintenanceSchedule.active == active_only)
    if maintenance_type:
        conditions.append(PreventiveMaintenanceSchedule.maintenance_type == maintenance_type)

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(PreventiveMaintenanceSchedule.next_due_date.asc())

    result = await session.exec(query)
    schedules = result.all()

    pm_list = []
    for pm in schedules:
        assigned_to_name = None
        if pm.assigned_to:
            staff_result = await session.exec(
                select(Staff).where(Staff.id == pm.assigned_to)
            )
            staff = staff_result.first()
            if staff:
                assigned_to_name = staff.name

        pm_list.append(PMScheduleRead(
            id=pm.id,
            name=pm.name,
            description=pm.description,
            location=pm.location,
            maintenance_type=pm.maintenance_type,
            frequency=pm.frequency,
            estimated_duration=pm.estimated_duration,
            assigned_to=pm.assigned_to,
            assigned_to_name=assigned_to_name,
            priority=pm.priority,
            active=pm.active,
            last_performed=pm.last_performed,
            next_due_date=pm.next_due_date,
            total_completions=pm.total_completions,
            created_at=pm.created_at,
            updated_at=pm.updated_at
        ))

    return pm_list


@router.post("/preventive-schedules", response_model=PMScheduleRead)
async def create_preventive_schedule(
    payload: PMScheduleCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new preventive maintenance schedule"""
    pm = PreventiveMaintenanceSchedule(
        name=payload.name,
        description=payload.description,
        location=payload.location or "",
        maintenance_type=payload.maintenance_type,
        frequency=payload.frequency,
        estimated_duration=payload.estimated_duration,
        assigned_to=payload.assigned_to,
        priority=payload.priority,
        next_due_date=payload.next_due_date,
        active=True,
        created_by=current_user.id
    )

    session.add(pm)
    await session.commit()
    await session.refresh(pm)

    assigned_to_name = None
    if pm.assigned_to:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == pm.assigned_to)
        )
        staff = staff_result.first()
        if staff:
            assigned_to_name = staff.name

    return PMScheduleRead(
        id=pm.id,
        name=pm.name,
        description=pm.description,
        location=pm.location,
        maintenance_type=pm.maintenance_type,
        frequency=pm.frequency,
        estimated_duration=pm.estimated_duration,
        assigned_to=pm.assigned_to,
        assigned_to_name=assigned_to_name,
        priority=pm.priority,
        active=pm.active,
        last_performed=pm.last_performed,
        next_due_date=pm.next_due_date,
        total_completions=pm.total_completions,
        created_at=pm.created_at,
        updated_at=pm.updated_at
    )


@router.patch("/preventive-schedules/{pm_id}", response_model=PMScheduleRead)
async def update_preventive_schedule(
    pm_id: int,
    payload: PMScheduleUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a preventive maintenance schedule"""
    result = await session.exec(
        select(PreventiveMaintenanceSchedule).where(PreventiveMaintenanceSchedule.id == pm_id)
    )
    pm = result.first()

    if not pm:
        raise HTTPException(status_code=404, detail="Preventive schedule not found")

    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(pm, field, value)

    pm.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(pm)

    assigned_to_name = None
    if pm.assigned_to:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == pm.assigned_to)
        )
        staff = staff_result.first()
        if staff:
            assigned_to_name = staff.name

    return PMScheduleRead(
        id=pm.id,
        name=pm.name,
        description=pm.description,
        location=pm.location,
        maintenance_type=pm.maintenance_type,
        frequency=pm.frequency,
        estimated_duration=pm.estimated_duration,
        assigned_to=pm.assigned_to,
        assigned_to_name=assigned_to_name,
        priority=pm.priority,
        active=pm.active,
        last_performed=pm.last_performed,
        next_due_date=pm.next_due_date,
        total_completions=pm.total_completions,
        created_at=pm.created_at,
        updated_at=pm.updated_at
    )


@router.post("/preventive-schedules/{pm_id}/complete", response_model=PMScheduleRead)
async def complete_preventive_schedule(
    pm_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark a preventive maintenance task as completed and schedule next"""
    result = await session.exec(
        select(PreventiveMaintenanceSchedule).where(PreventiveMaintenanceSchedule.id == pm_id)
    )
    pm = result.first()

    if not pm:
        raise HTTPException(status_code=404, detail="Preventive schedule not found")

    today = date.today()
    pm.last_performed = today
    pm.total_completions += 1

    # Calculate next due date based on frequency
    freq_map = {
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
        "biweekly": timedelta(days=14),
        "monthly": timedelta(days=30),
        "quarterly": timedelta(days=90),
        "semi-annual": timedelta(days=182),
        "annual": timedelta(days=365),
    }
    delta = freq_map.get(pm.frequency, timedelta(days=30))
    pm.next_due_date = today + delta

    pm.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(pm)

    assigned_to_name = None
    if pm.assigned_to:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == pm.assigned_to)
        )
        staff = staff_result.first()
        if staff:
            assigned_to_name = staff.name

    return PMScheduleRead(
        id=pm.id,
        name=pm.name,
        description=pm.description,
        location=pm.location,
        maintenance_type=pm.maintenance_type,
        frequency=pm.frequency,
        estimated_duration=pm.estimated_duration,
        assigned_to=pm.assigned_to,
        assigned_to_name=assigned_to_name,
        priority=pm.priority,
        active=pm.active,
        last_performed=pm.last_performed,
        next_due_date=pm.next_due_date,
        total_completions=pm.total_completions,
        created_at=pm.created_at,
        updated_at=pm.updated_at
    )


@router.delete("/preventive-schedules/{pm_id}")
async def delete_preventive_schedule(
    pm_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a preventive maintenance schedule"""
    result = await session.exec(
        select(PreventiveMaintenanceSchedule).where(PreventiveMaintenanceSchedule.id == pm_id)
    )
    pm = result.first()

    if not pm:
        raise HTTPException(status_code=404, detail="Preventive schedule not found")

    await session.delete(pm)
    await session.commit()

    return {"success": True, "message": "Preventive schedule deleted"}


# ============== MAINTENANCE INVENTORY ENDPOINTS ==============

class InventoryItemCreate(BaseModel):
    name: str
    category: str = "general"
    stock_level: int = 0
    min_stock: int = 0
    unit_cost: float = 0.0
    location: Optional[str] = None

class InventoryItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    stock_level: Optional[int] = None
    min_stock: Optional[int] = None
    unit_cost: Optional[float] = None
    location: Optional[str] = None

class InventoryItemRead(BaseModel):
    id: int
    name: str
    category: str
    stock_level: int
    min_stock: int
    unit_cost: float
    location: Optional[str] = None
    is_active: bool
    last_restocked: Optional[date] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/inventory", response_model=List[InventoryItemRead])
async def list_maintenance_inventory(
    category: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List all maintenance inventory items"""
    query = select(MaintenanceInventory).where(MaintenanceInventory.is_active == True)
    if category:
        query = query.where(MaintenanceInventory.category == category)
    query = query.order_by(MaintenanceInventory.name)

    result = await session.exec(query)
    items = result.all()

    return [InventoryItemRead(
        id=item.id,
        name=item.name,
        category=item.category,
        stock_level=item.stock_level,
        min_stock=item.min_stock,
        unit_cost=item.unit_cost,
        location=item.location,
        is_active=item.is_active,
        last_restocked=item.last_restocked,
        created_at=item.created_at,
        updated_at=item.updated_at
    ) for item in items]


@router.post("/inventory", response_model=InventoryItemRead)
async def create_maintenance_inventory_item(
    payload: InventoryItemCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new maintenance inventory item"""
    item = MaintenanceInventory(
        name=payload.name,
        category=payload.category,
        stock_level=payload.stock_level,
        min_stock=payload.min_stock,
        unit_cost=payload.unit_cost,
        location=payload.location,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    return InventoryItemRead(
        id=item.id,
        name=item.name,
        category=item.category,
        stock_level=item.stock_level,
        min_stock=item.min_stock,
        unit_cost=item.unit_cost,
        location=item.location,
        is_active=item.is_active,
        last_restocked=item.last_restocked,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


@router.patch("/inventory/{item_id}", response_model=InventoryItemRead)
async def update_maintenance_inventory_item(
    item_id: int,
    payload: InventoryItemUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a maintenance inventory item"""
    result = await session.exec(
        select(MaintenanceInventory).where(MaintenanceInventory.id == item_id)
    )
    item = result.first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    item.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(item)

    return InventoryItemRead(
        id=item.id,
        name=item.name,
        category=item.category,
        stock_level=item.stock_level,
        min_stock=item.min_stock,
        unit_cost=item.unit_cost,
        location=item.location,
        is_active=item.is_active,
        last_restocked=item.last_restocked,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


@router.post("/inventory/{item_id}/adjust-stock")
async def adjust_inventory_stock(
    item_id: int,
    quantity: int = Query(..., description="Quantity to adjust"),
    is_addition: bool = Query(True, description="True to add, False to subtract"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Adjust stock level for an inventory item"""
    result = await session.exec(
        select(MaintenanceInventory).where(MaintenanceInventory.id == item_id)
    )
    item = result.first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    if is_addition:
        item.stock_level += quantity
        item.last_restocked = date.today()
    else:
        item.stock_level = max(0, item.stock_level - quantity)

    item.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(item)

    return {
        "success": True,
        "id": item.id,
        "stock_level": item.stock_level,
        "message": f"Stock {'added' if is_addition else 'removed'}: {quantity}"
    }


@router.delete("/inventory/{item_id}")
async def delete_maintenance_inventory_item(
    item_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a maintenance inventory item"""
    result = await session.exec(
        select(MaintenanceInventory).where(MaintenanceInventory.id == item_id)
    )
    item = result.first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    await session.delete(item)
    await session.commit()

    return {"success": True, "message": "Inventory item deleted"}


# ============== AUTO-ASSIGNMENT ENDPOINTS ==============

class MaintenanceAutoAssignResult(BaseModel):
    work_order_id: int
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    score: Optional[float] = None
    success: bool
    message: str


class MaintenanceBulkAutoAssignResult(BaseModel):
    total_work_orders: int
    assigned_count: int
    failed_count: int
    results: List[MaintenanceAutoAssignResult]


@router.post("/work-orders/{work_order_id}/auto-assign", response_model=MaintenanceAutoAssignResult)
async def auto_assign_work_order(
    work_order_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Auto-assign a maintenance work order to the best available staff member.
    Uses multi-factor scoring: workload (30%), skills (25%), availability (20%),
    performance (15%), floor proximity (10%).
    """
    from app.services.staff_scheduling_service import get_scheduling_service

    result = await session.exec(
        select(MaintenanceRequest).where(MaintenanceRequest.id == work_order_id)
    )
    wo = result.first()

    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    if wo.status in ["completed", "cancelled"]:
        return MaintenanceAutoAssignResult(
            work_order_id=work_order_id,
            success=False,
            message=f"Work order is already {wo.status}"
        )

    # Use scheduling service to find best staff
    scheduling_service = get_scheduling_service(session)
    best_staff = await scheduling_service.find_best_staff_for_task(
        task_type="maintenance",
        priority=wo.priority or "normal",
        room_number=wo.room_number
    )

    if not best_staff:
        return MaintenanceAutoAssignResult(
            work_order_id=work_order_id,
            success=False,
            message="No available maintenance staff found"
        )

    # Assign the work order
    wo.assigned_to = best_staff.staff_id
    wo.status = "assigned"
    wo.updated_at = datetime.utcnow()
    await session.commit()

    # Create notification
    try:
        from app.models.guest_chat import StaffNotification
        notification = StaffNotification(
            staff_id=best_staff.staff_id,
            notification_type="task_assigned",
            title=f"Auto-Assigned: {wo.issue_type} Work Order",
            message=f"{wo.title} at {wo.location}. Priority: {wo.priority or 'normal'}.",
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
        task_type="maintenance",
        room_number=wo.room_number or wo.location,
        priority=wo.priority or "normal",
        notes=wo.description,
    )

    return MaintenanceAutoAssignResult(
        work_order_id=work_order_id,
        assigned_to=best_staff.staff_id,
        assigned_to_name=best_staff.staff_name,
        score=round(best_staff.total_score, 2),
        success=True,
        message=f"Work order assigned to {best_staff.staff_name} (score: {best_staff.total_score:.2f})"
    )


@router.post("/work-orders/auto-assign-all", response_model=MaintenanceBulkAutoAssignResult)
async def auto_assign_all_pending_work_orders(
    priority: Optional[str] = Query(None, description="Only assign work orders with this priority"),
    max_work_orders: int = Query(50, description="Maximum work orders to assign in one call"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Auto-assign all pending maintenance work orders to available staff members.
    Work orders are assigned in priority order (critical first).
    """
    from app.services.staff_scheduling_service import get_scheduling_service

    query = select(MaintenanceRequest).where(
        MaintenanceRequest.status.in_(["pending"])
    )
    if priority:
        query = query.where(MaintenanceRequest.priority == priority)

    query = query.order_by(
        MaintenanceRequest.priority.desc(),
        MaintenanceRequest.reported_at.asc()
    ).limit(max_work_orders)

    result = await session.exec(query)
    work_orders = result.all()

    results = []
    assigned_count = 0
    scheduling_service = get_scheduling_service(session)

    for wo in work_orders:
        best_staff = await scheduling_service.find_best_staff_for_task(
            task_type="maintenance",
            priority=wo.priority or "normal",
            room_number=wo.room_number
        )

        if best_staff:
            wo.assigned_to = best_staff.staff_id
            wo.status = "assigned"
            wo.updated_at = datetime.utcnow()
            assigned_count += 1

            results.append(MaintenanceAutoAssignResult(
                work_order_id=wo.id,
                assigned_to=best_staff.staff_id,
                assigned_to_name=best_staff.staff_name,
                score=round(best_staff.total_score, 2),
                success=True,
                message=f"Assigned to {best_staff.staff_name}"
            ))

            try:
                from app.models.guest_chat import StaffNotification
                notification = StaffNotification(
                    staff_id=best_staff.staff_id,
                    notification_type="task_assigned",
                    title=f"Auto-Assigned: {wo.issue_type} Work Order",
                    message=f"{wo.title} at {wo.location}. Priority: {wo.priority or 'normal'}.",
                    is_read=False,
                    created_at=datetime.utcnow()
                )
                session.add(notification)
            except Exception:
                pass
        else:
            results.append(MaintenanceAutoAssignResult(
                work_order_id=wo.id,
                success=False,
                message="No available staff"
            ))

    await session.commit()

    return MaintenanceBulkAutoAssignResult(
        total_work_orders=len(work_orders),
        assigned_count=assigned_count,
        failed_count=len(work_orders) - assigned_count,
        results=results
    )


@router.get("/staff/workload")
async def get_maintenance_staff_workload(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get workload summary for all maintenance staff"""
    from app.services.staff_scheduling_service import get_scheduling_service

    scheduling_service = get_scheduling_service(session)
    workload_summary = await scheduling_service.get_staff_workload_summary(department="maintenance")

    return {
        "department": "maintenance",
        "staff_count": len(workload_summary),
        "available_count": len([s for s in workload_summary if s["availability"] == "available"]),
        "staff": workload_summary
    }


# ============== PREVENTIVE MAINTENANCE SCHEDULING ==============

class PreventiveScheduleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    equipment_id: Optional[int] = None
    location: str
    maintenance_type: str  # hvac, electrical, plumbing, fire_safety, elevator, general
    frequency: str  # daily, weekly, biweekly, monthly, quarterly, semi-annual, annual
    day_of_week: Optional[int] = None  # 0=Monday, 6=Sunday (for weekly)
    day_of_month: Optional[int] = None  # 1-31 (for monthly)
    estimated_duration: int = 60  # minutes
    assigned_to: Optional[int] = None
    checklist: Optional[List[str]] = None
    priority: str = "normal"
    active: bool = True


class PreventiveScheduleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    frequency: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    estimated_duration: Optional[int] = None
    assigned_to: Optional[int] = None
    checklist: Optional[List[str]] = None
    priority: Optional[str] = None
    active: Optional[bool] = None


class PreventiveScheduleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    equipment_id: Optional[int] = None
    location: str
    maintenance_type: str
    frequency: str
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    estimated_duration: int
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    checklist: Optional[List[str]] = None
    priority: str
    active: bool
    last_performed: Optional[str] = None
    next_due: Optional[str] = None
    created_at: str


@router.post("/preventive-schedules/{schedule_id}/generate-work-order")
async def generate_work_order_from_schedule(
    schedule_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Generate a work order from a preventive maintenance schedule"""
    from app.models.maintenance import PreventiveMaintenanceSchedule

    schedule = await session.get(PreventiveMaintenanceSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    now = datetime.utcnow()

    # Create work order
    work_order = MaintenanceRequest(
        title=f"PM: {schedule.name}",
        description=schedule.description or f"Preventive maintenance - {schedule.maintenance_type}",
        location=schedule.location,
        issue_type=schedule.maintenance_type,
        priority=schedule.priority,
        status="pending",
        assigned_to=schedule.assigned_to,
        estimated_duration=schedule.estimated_duration,
        reported_by=current_user.id,
        reported_at=now,
        scheduled_date=date.today(),
        is_preventive=True,
        preventive_schedule_id=schedule_id,
    )
    session.add(work_order)

    # Update schedule's last performed and next due
    schedule.last_performed = now.date()
    schedule.next_due_date = calculate_next_due_date(
        frequency=schedule.frequency,
        day_of_week=schedule.day_of_week,
        day_of_month=schedule.day_of_month,
        from_date=date.today()
    )
    schedule.updated_at = now

    await session.commit()
    await session.refresh(work_order)

    # Create notification if assigned
    if schedule.assigned_to:
        try:
            from app.models.guest_chat import StaffNotification
            notification = StaffNotification(
                staff_id=schedule.assigned_to,
                notification_type="task_assigned",
                title=f"Preventive Maintenance: {schedule.name}",
                message=f"Scheduled maintenance at {schedule.location}. Est. duration: {schedule.estimated_duration} min",
                is_read=False,
                created_at=now
            )
            session.add(notification)
            await session.commit()
        except Exception:
            pass

    return {
        "message": "Work order generated successfully",
        "work_order_id": work_order.id,
        "next_due_date": schedule.next_due_date.isoformat()
    }


@router.post("/preventive-schedules/generate-due")
async def generate_all_due_work_orders(
    include_overdue: bool = Query(True),
    auto_assign: bool = Query(True),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Generate work orders for all due/overdue preventive maintenance schedules"""
    if current_user.role not in ["admin", "manager", "maintenance"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    from app.models.maintenance import PreventiveMaintenanceSchedule
    from app.services.staff_scheduling_service import get_scheduling_service

    today = date.today()
    query = select(PreventiveMaintenanceSchedule).where(
        PreventiveMaintenanceSchedule.active == True,
        PreventiveMaintenanceSchedule.next_due_date <= today
    )

    result = await session.exec(query)
    schedules = result.all()

    if not schedules:
        return {"message": "No due schedules found", "generated_count": 0}

    scheduling_service = get_scheduling_service(session) if auto_assign else None
    now = datetime.utcnow()
    generated = []

    for schedule in schedules:
        # Create work order
        assigned_to = schedule.assigned_to

        # Auto-assign if not pre-assigned
        if auto_assign and not assigned_to and scheduling_service:
            best_staff = await scheduling_service.find_best_staff_for_task(
                task_type="maintenance",
                priority=schedule.priority
            )
            if best_staff:
                assigned_to = best_staff.staff_id

        work_order = MaintenanceRequest(
            title=f"PM: {schedule.name}",
            description=schedule.description or f"Preventive maintenance - {schedule.maintenance_type}",
            location=schedule.location,
            issue_type=schedule.maintenance_type,
            priority=schedule.priority,
            status="pending" if not assigned_to else "assigned",
            assigned_to=assigned_to,
            estimated_duration=schedule.estimated_duration,
            reported_by=current_user.id,
            reported_at=now,
            scheduled_date=today,
            is_preventive=True,
            preventive_schedule_id=schedule.id,
        )
        session.add(work_order)

        # Update schedule
        schedule.last_performed = today
        schedule.next_due_date = calculate_next_due_date(
            frequency=schedule.frequency,
            day_of_week=schedule.day_of_week,
            day_of_month=schedule.day_of_month,
            from_date=today
        )
        schedule.updated_at = now

        generated.append({
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "assigned_to": assigned_to
        })

    await session.commit()

    return {
        "message": f"Generated {len(generated)} work orders",
        "generated_count": len(generated),
        "work_orders": generated
    }


@router.get("/preventive-schedules/calendar")
async def get_preventive_maintenance_calendar(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    maintenance_type: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get preventive maintenance calendar view"""
    from app.models.maintenance import PreventiveMaintenanceSchedule
    from datetime import timedelta

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    query = select(PreventiveMaintenanceSchedule).where(
        PreventiveMaintenanceSchedule.active == True
    )
    if maintenance_type:
        query = query.where(PreventiveMaintenanceSchedule.maintenance_type == maintenance_type)

    result = await session.exec(query)
    schedules = result.all()

    # Generate calendar events
    calendar_events = []
    for schedule in schedules:
        # Calculate occurrences between start and end dates
        occurrences = calculate_occurrences(
            frequency=schedule.frequency,
            day_of_week=schedule.day_of_week,
            day_of_month=schedule.day_of_month,
            start_date=start,
            end_date=end
        )

        for occ_date in occurrences:
            calendar_events.append({
                "date": occ_date.isoformat(),
                "schedule_id": schedule.id,
                "name": schedule.name,
                "location": schedule.location,
                "maintenance_type": schedule.maintenance_type,
                "estimated_duration": schedule.estimated_duration,
                "priority": schedule.priority,
                "assigned_to": schedule.assigned_to,
            })

    # Sort by date
    calendar_events.sort(key=lambda x: x["date"])

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_events": len(calendar_events),
        "events": calendar_events
    }


def calculate_next_due_date(
    frequency: str,
    day_of_week: Optional[int] = None,
    day_of_month: Optional[int] = None,
    from_date: Optional[date] = None
) -> date:
    """Calculate the next due date based on frequency"""
    from datetime import timedelta

    base = from_date or date.today()

    if frequency == "daily":
        return base + timedelta(days=1)

    elif frequency == "weekly":
        days_ahead = (day_of_week or 0) - base.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return base + timedelta(days=days_ahead)

    elif frequency == "biweekly":
        days_ahead = (day_of_week or 0) - base.weekday()
        if days_ahead <= 0:
            days_ahead += 14
        else:
            days_ahead += 7
        return base + timedelta(days=days_ahead)

    elif frequency == "monthly":
        target_day = day_of_month or 1
        next_month = base.replace(day=1)
        if base.month == 12:
            next_month = next_month.replace(year=base.year + 1, month=1)
        else:
            next_month = next_month.replace(month=base.month + 1)

        try:
            return next_month.replace(day=min(target_day, 28))
        except ValueError:
            return next_month.replace(day=28)

    elif frequency == "quarterly":
        month = ((base.month - 1) // 3 + 1) * 3 + 1
        year = base.year
        if month > 12:
            month = 1
            year += 1
        return date(year, month, day_of_month or 1)

    elif frequency == "semi-annual":
        if base.month <= 6:
            return date(base.year, 7, day_of_month or 1)
        else:
            return date(base.year + 1, 1, day_of_month or 1)

    elif frequency == "annual":
        return date(base.year + 1, base.month, day_of_month or base.day)

    return base + timedelta(days=30)  # Default fallback


def calculate_occurrences(
    frequency: str,
    day_of_week: Optional[int],
    day_of_month: Optional[int],
    start_date: date,
    end_date: date
) -> List[date]:
    """Calculate all occurrences between two dates"""
    from datetime import timedelta

    occurrences = []
    current = start_date

    if frequency == "daily":
        while current <= end_date:
            occurrences.append(current)
            current += timedelta(days=1)

    elif frequency == "weekly":
        target_day = day_of_week or 0
        days_ahead = target_day - current.weekday()
        if days_ahead < 0:
            days_ahead += 7
        current += timedelta(days=days_ahead)
        while current <= end_date:
            occurrences.append(current)
            current += timedelta(days=7)

    elif frequency == "biweekly":
        target_day = day_of_week or 0
        days_ahead = target_day - current.weekday()
        if days_ahead < 0:
            days_ahead += 7
        current += timedelta(days=days_ahead)
        while current <= end_date:
            occurrences.append(current)
            current += timedelta(days=14)

    elif frequency == "monthly":
        target_day = day_of_month or 1
        while current <= end_date:
            try:
                occ = current.replace(day=min(target_day, 28))
                if occ >= start_date and occ <= end_date:
                    occurrences.append(occ)
            except ValueError:
                pass
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    elif frequency == "quarterly":
        target_day = day_of_month or 1
        quarter_months = [1, 4, 7, 10]
        for year in range(start_date.year, end_date.year + 1):
            for month in quarter_months:
                try:
                    occ = date(year, month, min(target_day, 28))
                    if start_date <= occ <= end_date:
                        occurrences.append(occ)
                except ValueError:
                    pass

    elif frequency in ["semi-annual", "annual"]:
        target_day = day_of_month or 1
        interval = 6 if frequency == "semi-annual" else 12
        current_month = start_date.month
        current_year = start_date.year

        while True:
            try:
                occ = date(current_year, current_month, min(target_day, 28))
                if occ > end_date:
                    break
                if occ >= start_date:
                    occurrences.append(occ)
            except ValueError:
                pass
            current_month += interval
            while current_month > 12:
                current_month -= 12
                current_year += 1

    return occurrences


# Import json for checklist serialization
import json

# ==================== FORCE ASSIGN & ACCEPT/DECLINE WORKFLOW ====================

class ForceAssignWorkOrderRequest(BaseModel):
    """Request model for force-assigning a work order to busy technician"""
    staff_id: int
    reason: str
    require_acceptance: bool = True


class ForceAssignWorkOrderResponse(BaseModel):
    work_order_id: int
    staff_id: int
    staff_name: str
    specialty: Optional[str] = None
    success: bool
    message: str
    requires_acceptance: bool
    force_assigned: bool


class AcceptWorkOrderRequest(BaseModel):
    notes: Optional[str] = None


class DeclineWorkOrderRequest(BaseModel):
    reason: str


class WorkOrderAcceptanceResponse(BaseModel):
    work_order_id: int
    status: str
    acceptance_status: str
    message: str
    declined_reason: Optional[str] = None


@router.post("/work-orders/{work_order_id}/force-assign", response_model=ForceAssignWorkOrderResponse)
async def force_assign_work_order(
    work_order_id: int,
    payload: ForceAssignWorkOrderRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Force-assign a work order to a specific technician, bypassing availability limits.
    Use for emergency maintenance when all technicians are busy.
    """
    from app.models.guest_chat import StaffNotification

    if current_user.role not in ["admin", "manager", "supervisor"]:
        raise HTTPException(status_code=403, detail="Only admins/managers can force-assign")

    work_order = await session.get(MaintenanceRequest, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    if work_order.status in ["completed", "cancelled"]:
        raise HTTPException(status_code=400, detail=f"Cannot assign with status '{work_order.status}'")

    staff = await session.get(Staff, payload.staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Technician not found")

    work_order.assigned_to = staff.id
    work_order.status = "assigned"
    work_order.force_assigned = True
    work_order.force_assign_reason = payload.reason
    work_order.force_assigned_by = current_user.id
    work_order.updated_at = datetime.utcnow()

    if payload.require_acceptance:
        work_order.acceptance_status = "pending_acceptance"
    else:
        work_order.acceptance_status = "accepted"
        work_order.accepted_at = datetime.utcnow()

    await session.commit()

    notification = StaffNotification(
        staff_id=staff.id,
        notification_type="urgent_work_order",
        title=f"URGENT: {work_order.category.upper()} - {work_order.priority.upper()}",
        message=f"Work Order #{work_order.work_order_id}: {work_order.issue[:100]}. Reason: {payload.reason}",
        is_read=False,
        created_at=datetime.utcnow()
    )
    session.add(notification)
    await session.commit()

    return ForceAssignWorkOrderResponse(
        work_order_id=work_order_id,
        staff_id=staff.id,
        staff_name=f"{staff.first_name} {staff.last_name}",
        specialty=staff.specialty,
        success=True,
        message=f"Work order force-assigned to {staff.first_name} {staff.last_name}.",
        requires_acceptance=payload.require_acceptance,
        force_assigned=True
    )


@router.post("/work-orders/{work_order_id}/accept-assignment", response_model=WorkOrderAcceptanceResponse)
async def accept_work_order_assignment(
    work_order_id: int,
    payload: Optional[AcceptWorkOrderRequest] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Accept an assigned work order."""
    from app.models.guest_chat import StaffNotification

    work_order = await session.get(MaintenanceRequest, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    staff_result = await session.execute(select(Staff).where(Staff.user_id == current_user.id))
    staff = staff_result.scalar_one_or_none()

    if not staff or work_order.assigned_to != staff.id:
        raise HTTPException(status_code=403, detail="You can only accept work orders assigned to you")

    if work_order.acceptance_status == "accepted":
        return WorkOrderAcceptanceResponse(
            work_order_id=work_order_id,
            status=work_order.status,
            acceptance_status="accepted",
            message="Already accepted"
        )

    work_order.acceptance_status = "accepted"
    work_order.accepted_at = datetime.utcnow()
    work_order.status = "in_progress"
    work_order.started_at = datetime.utcnow()
    work_order.updated_at = datetime.utcnow()
    await session.commit()

    if work_order.force_assigned and work_order.force_assigned_by:
        notification = StaffNotification(
            staff_id=work_order.force_assigned_by,
            notification_type="work_order_accepted",
            title="Work Order Accepted",
            message=f"Work order #{work_order.work_order_id} accepted by {staff.first_name} {staff.last_name}.",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()

    return WorkOrderAcceptanceResponse(
        work_order_id=work_order_id,
        status=work_order.status,
        acceptance_status="accepted",
        message="Work order accepted"
    )


@router.post("/work-orders/{work_order_id}/decline-assignment", response_model=WorkOrderAcceptanceResponse)
async def decline_work_order_assignment(
    work_order_id: int,
    payload: DeclineWorkOrderRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Decline an assigned work order with a reason."""
    from app.models.guest_chat import StaffNotification

    work_order = await session.get(MaintenanceRequest, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    staff_result = await session.execute(select(Staff).where(Staff.user_id == current_user.id))
    staff = staff_result.scalar_one_or_none()

    if not staff or work_order.assigned_to != staff.id:
        raise HTTPException(status_code=403, detail="You can only decline work orders assigned to you")

    declined_by_name = f"{staff.first_name} {staff.last_name}"
    force_assigned_by = work_order.force_assigned_by

    work_order.acceptance_status = "declined"
    work_order.decline_reason = payload.reason
    work_order.declined_at = datetime.utcnow()
    work_order.assigned_to = None
    work_order.status = "pending"  # Store as pending, but return as open to frontend
    work_order.force_assigned = False
    work_order.updated_at = datetime.utcnow()
    await session.commit()

    if force_assigned_by:
        notification = StaffNotification(
            staff_id=force_assigned_by,
            notification_type="work_order_declined",
            title=f"Work Order Declined - {work_order.work_order_id}",
            message=f"Declined by {declined_by_name}. Reason: {payload.reason}",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()

    return WorkOrderAcceptanceResponse(
        work_order_id=work_order_id,
        status="open",
        acceptance_status="declined",
        message="Work order declined",
        declined_reason=payload.reason
    )


@router.get("/work-orders/pending-acceptance")
async def get_work_orders_pending_acceptance(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all work orders pending acceptance for the current technician."""
    staff_result = await session.execute(select(Staff).where(Staff.user_id == current_user.id))
    staff = staff_result.scalar_one_or_none()
    if not staff:
        return {"work_orders": [], "count": 0}

    wo_result = await session.execute(
        select(MaintenanceRequest).where(
            MaintenanceRequest.assigned_to == staff.id,
            MaintenanceRequest.acceptance_status == "pending_acceptance"
        ).order_by(MaintenanceRequest.priority.desc())
    )
    work_orders = wo_result.scalars().all()

    wo_list = []
    for wo in work_orders:
        wo_list.append({
            "id": wo.id,
            "work_order_id": wo.work_order_id,
            "category": wo.category,
            "priority": wo.priority,
            "issue": wo.issue[:200] if wo.issue else "",
            "room_number": wo.room_number,
            "force_assigned": wo.force_assigned,
            "force_assign_reason": wo.force_assign_reason,
        })

    return {"work_orders": wo_list, "count": len(wo_list)}


@router.get("/technicians/availability-status")
async def get_technicians_availability_status(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get overall technician availability status with specialty breakdown."""
    from app.services.staff_scheduling_service import get_scheduling_service

    scheduling_service = get_scheduling_service(session)
    workload_summary = await scheduling_service.get_staff_workload_summary(department="maintenance")

    available = [s for s in workload_summary if s["availability"] == "available"]
    busy = [s for s in workload_summary if s["availability"] != "available"]

    pending_result = await session.execute(
        select(MaintenanceRequest).where(MaintenanceRequest.status == "open")
    )
    pending = pending_result.scalars().all()
    emergency_pending = len([w for w in pending if w.priority == "emergency"])

    all_busy = len(available) == 0 and len(workload_summary) > 0

    # Group by specialty
    specialty_availability = {}
    for s in workload_summary:
        spec = s.get("specialty", "general") or "general"
        if spec not in specialty_availability:
            specialty_availability[spec] = {"available": 0, "busy": 0, "total": 0}
        specialty_availability[spec]["total"] += 1
        if s["availability"] == "available":
            specialty_availability[spec]["available"] += 1
        else:
            specialty_availability[spec]["busy"] += 1

    response = {
        "total_technicians": len(workload_summary),
        "available_count": len(available),
        "busy_count": len(busy),
        "all_technicians_busy": all_busy,
        "pending_work_orders": len(pending),
        "emergency_pending": emergency_pending,
        "specialty_availability": specialty_availability,
        "available_technicians": [
            {"id": s["staff_id"], "name": s["name"], "specialty": s.get("specialty", "general")}
            for s in available
        ],
        "busy_technicians": [
            {"id": s["staff_id"], "name": s["name"], "specialty": s.get("specialty", "general"), "active_tasks": s.get("active_tasks", 0)}
            for s in busy
        ]
    }

    if all_busy:
        response["alert"] = {
            "type": "warning" if emergency_pending == 0 else "critical",
            "title": "All Technicians Busy",
            "message": f"All {len(workload_summary)} technicians occupied. {len(pending)} work order(s) pending.",
            "emergency_pending": emergency_pending
        }

    return response


# ==================== SPECIALIZATION MANAGEMENT ====================

VALID_SPECIALIZATIONS = [
    "electrical", "plumbing", "hvac", "carpentry", "appliance",
    "fire_safety", "elevator", "pool", "general", "it_network"
]


class UpdateTechnicianSpecializationRequest(BaseModel):
    specialty: str
    secondary_specialties: Optional[List[str]] = None


@router.get("/specializations")
async def get_available_specializations():
    """Get list of valid technician specializations."""
    return {
        "specializations": VALID_SPECIALIZATIONS,
        "descriptions": {
            "electrical": "Electrical systems, wiring, lighting",
            "plumbing": "Plumbing, pipes, water systems",
            "hvac": "Heating, ventilation, air conditioning",
            "carpentry": "Woodwork, furniture, doors",
            "appliance": "Appliance repair and maintenance",
            "fire_safety": "Fire alarms, sprinklers, extinguishers",
            "elevator": "Elevator maintenance and repair",
            "pool": "Pool and spa equipment",
            "general": "General maintenance tasks",
            "it_network": "IT, WiFi, network equipment"
        }
    }


@router.put("/technicians/{staff_id}/specialization")
async def update_technician_specialization(
    staff_id: int,
    payload: UpdateTechnicianSpecializationRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a technician's specialization."""
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Only admins/managers can update specializations")

    if payload.specialty not in VALID_SPECIALIZATIONS:
        raise HTTPException(status_code=400, detail=f"Invalid specialization. Valid options: {VALID_SPECIALIZATIONS}")

    staff = await session.get(Staff, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="Technician not found")

    staff.specialty = payload.specialty
    if payload.secondary_specialties:
        # Store as JSON in a field or create separate table
        staff.secondary_specialties = ",".join(payload.secondary_specialties)
    staff.updated_at = datetime.utcnow()
    await session.commit()

    return {
        "staff_id": staff_id,
        "name": f"{staff.first_name} {staff.last_name}",
        "specialty": staff.specialty,
        "message": "Specialization updated successfully"
    }


@router.get("/technicians/by-specialty/{specialty}")
async def get_technicians_by_specialty(
    specialty: str,
    available_only: bool = Query(False),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all technicians with a specific specialization."""
    if specialty not in VALID_SPECIALIZATIONS:
        raise HTTPException(status_code=400, detail=f"Invalid specialization")

    query = select(Staff).where(
        Staff.department == "maintenance",
        Staff.specialty == specialty,
        Staff.status == "active"
    )
    result = await session.execute(query)
    technicians = result.scalars().all()

    tech_list = []
    for tech in technicians:
        # Get active task count
        task_result = await session.execute(
            select(MaintenanceRequest).where(
                MaintenanceRequest.assigned_to == tech.id,
                MaintenanceRequest.status.in_(["assigned", "in_progress"])
            )
        )
        active_tasks = len(task_result.scalars().all())
        is_available = active_tasks < 3

        if available_only and not is_available:
            continue

        tech_list.append({
            "id": tech.id,
            "name": f"{tech.first_name} {tech.last_name}",
            "specialty": tech.specialty,
            "active_tasks": active_tasks,
            "is_available": is_available,
            "phone": tech.phone
        })

    return {
        "specialty": specialty,
        "total": len(tech_list),
        "available": len([t for t in tech_list if t["is_available"]]),
        "technicians": tech_list
    }


# ==================== OUT OF ORDER (OOO) ROOM BLOCKING ====================

class MarkOOORequest(BaseModel):
    """Request to mark a room as Out of Order from maintenance"""
    is_out_of_order: bool
    estimated_completion: Optional[datetime] = None
    ooo_category: Optional[str] = None  # plumbing, electrical, hvac, renovation, damage
    notes: Optional[str] = None


class OOOBlockResponse(BaseModel):
    """Response for OOO block operations"""
    success: bool
    room_block_id: Optional[int] = None
    maintenance_request_id: int
    action_taken: str
    message: str
    affected_bookings_count: int = 0
    affected_bookings: Optional[list] = None


class ExtendOOORequest(BaseModel):
    """Request to extend an OOO block"""
    new_end_date: date
    extension_reason: Optional[str] = None


@router.post("/work-orders/{work_order_id}/mark-ooo", response_model=OOOBlockResponse)
async def mark_work_order_ooo(
    work_order_id: int,
    payload: MarkOOORequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Mark a work order as Out of Order (OOO).
    Automatically creates a room block when is_out_of_order=True.
    Automatically releases the block when is_out_of_order=False.
    """
    from app.services.maintenance_block_service import get_maintenance_block_service

    service = get_maintenance_block_service(session)

    result = await service.handle_maintenance_ooo_change(
        maintenance_request_id=work_order_id,
        is_out_of_order=payload.is_out_of_order,
        estimated_completion=payload.estimated_completion,
        ooo_category=payload.ooo_category,
        user_id=current_user.id
    )

    # Update notes if provided
    if payload.notes:
        wo = await session.get(MaintenanceRequest, work_order_id)
        if wo:
            wo.notes = (wo.notes or "") + f"\nOOO Note: {payload.notes}"

    await session.commit()

    return OOOBlockResponse(
        success=result.success,
        room_block_id=result.room_block_id,
        maintenance_request_id=result.maintenance_request_id,
        action_taken=result.action_taken,
        message=result.message,
        affected_bookings_count=len(result.affected_bookings),
        affected_bookings=[
            {
                "reservation_id": ab.reservation_id,
                "confirmation_code": ab.confirmation_code,
                "guest_name": ab.guest_name,
                "arrival_date": ab.arrival_date.isoformat(),
                "departure_date": ab.departure_date.isoformat(),
                "requires_action": ab.requires_action
            }
            for ab in result.affected_bookings
        ] if result.affected_bookings else None
    )


@router.post("/work-orders/{work_order_id}/extend-ooo", response_model=OOOBlockResponse)
async def extend_work_order_ooo(
    work_order_id: int,
    payload: ExtendOOORequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Extend the OOO block for a maintenance work order"""
    from app.services.maintenance_block_service import get_maintenance_block_service

    service = get_maintenance_block_service(session)

    result = await service.extend_maintenance_block(
        maintenance_request_id=work_order_id,
        new_end_date=payload.new_end_date,
        extension_reason=payload.extension_reason,
        user_id=current_user.id
    )

    await session.commit()

    return OOOBlockResponse(
        success=result.success,
        room_block_id=result.room_block_id,
        maintenance_request_id=result.maintenance_request_id,
        action_taken=result.action_taken,
        message=result.message,
        affected_bookings_count=len(result.affected_bookings),
        affected_bookings=[
            {
                "reservation_id": ab.reservation_id,
                "confirmation_code": ab.confirmation_code,
                "guest_name": ab.guest_name,
                "arrival_date": ab.arrival_date.isoformat(),
                "departure_date": ab.departure_date.isoformat()
            }
            for ab in result.affected_bookings
        ] if result.affected_bookings else None
    )


@router.post("/work-orders/{work_order_id}/complete-and-release", response_model=OOOBlockResponse)
async def complete_work_order_and_release_ooo(
    work_order_id: int,
    resolution_notes: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Complete a maintenance work order and automatically release the room block.
    The room will be marked as available again.
    """
    from app.services.maintenance_block_service import get_maintenance_block_service

    service = get_maintenance_block_service(session)

    result = await service.complete_maintenance_and_release(
        maintenance_request_id=work_order_id,
        resolution_notes=resolution_notes,
        user_id=current_user.id
    )

    await session.commit()

    return OOOBlockResponse(
        success=result.success,
        room_block_id=result.room_block_id,
        maintenance_request_id=result.maintenance_request_id,
        action_taken=result.action_taken,
        message=result.message,
        affected_bookings_count=0,
        affected_bookings=None
    )


@router.get("/room-blocks")
async def get_maintenance_room_blocks(
    room_id: Optional[int] = Query(None, description="Filter by room"),
    room_type_id: Optional[int] = Query(None, description="Filter by room type"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all active maintenance room blocks"""
    from app.services.maintenance_block_service import get_maintenance_block_service

    service = get_maintenance_block_service(session)
    blocks = await service.get_active_maintenance_blocks(
        room_id=room_id,
        room_type_id=room_type_id
    )

    return {
        "total": len(blocks),
        "blocks": blocks
    }


@router.get("/work-orders/{work_order_id}/ooo-status")
async def get_work_order_ooo_status(
    work_order_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get the OOO status for a specific work order"""
    from app.models.inventory import Room, RoomBlock

    wo = await session.get(MaintenanceRequest, work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    room_block = None
    affected_bookings = []

    if wo.room_block_id:
        room_block = await session.get(RoomBlock, wo.room_block_id)

        if room_block and room_block.room_id:
            from app.services.maintenance_block_service import get_maintenance_block_service
            service = get_maintenance_block_service(session)
            affected = await service._find_affected_bookings(
                room_block.room_id,
                room_block.start_date,
                room_block.end_date
            )
            affected_bookings = [
                {
                    "reservation_id": ab.reservation_id,
                    "confirmation_code": ab.confirmation_code,
                    "guest_name": ab.guest_name,
                    "arrival_date": ab.arrival_date.isoformat(),
                    "departure_date": ab.departure_date.isoformat(),
                    "requires_action": ab.requires_action
                }
                for ab in affected
            ]

    # Get room details
    room_number = None
    if wo.room_id:
        room = await session.get(Room, wo.room_id)
        if room:
            room_number = room.number

    return {
        "work_order_id": wo.id,
        "work_order_number": wo.work_order_id,
        "room_id": wo.room_id,
        "room_number": room_number or wo.room_number,
        "is_out_of_order": wo.is_out_of_order,
        "ooo_category": wo.ooo_category,
        "estimated_completion": wo.estimated_completion.isoformat() if wo.estimated_completion else None,
        "room_block": {
            "id": room_block.id,
            "start_date": room_block.start_date.isoformat(),
            "end_date": room_block.end_date.isoformat(),
            "status": room_block.status,
            "reason": room_block.reason,
            "auto_created": room_block.auto_created,
            "auto_released": room_block.auto_released
        } if room_block else None,
        "affected_bookings_count": len(affected_bookings),
        "affected_bookings": affected_bookings
    }


# NOTE: Primary inventory CRUD endpoints are defined in the MAINTENANCE INVENTORY ENDPOINTS
# section above (around line 1519). The schemas and unique endpoints below complement them.

class InventoryItemResponse(BaseModel):
    """Extended inventory response with additional fields for detailed views"""
    id: int
    name: str
    category: str
    stock_level: int
    min_stock: int
    unit_cost: float
    location: Optional[str]
    part_number: Optional[str]
    supplier_id: Optional[int]
    reorder_quantity: Optional[int]
    last_restocked: Optional[str]
    notes: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("/inventory/{item_id}", response_model=InventoryItemResponse)
async def get_inventory_item(
    item_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a specific inventory item"""
    item = await session.get(MaintenanceInventory, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    return InventoryItemResponse(
        id=item.id,
        name=item.name,
        category=item.category,
        stock_level=item.stock_level,
        min_stock=item.min_stock,
        unit_cost=item.unit_cost,
        location=item.location,
        part_number=item.part_number,
        supplier_id=item.supplier_id,
        reorder_quantity=item.reorder_quantity,
        last_restocked=item.last_restocked.isoformat() if item.last_restocked else None,
        notes=item.notes,
        is_active=item.is_active,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat()
    )
