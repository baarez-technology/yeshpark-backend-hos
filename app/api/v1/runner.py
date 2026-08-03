"""
Runner/Bell Staff API Endpoints
Handles pickup requests, deliveries, and runner performance tracking
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
from app.models.runner import RunnerPickupRequest, RunnerDelivery, RunnerActivityLog
from app.models.inventory import Room
from app.models.reservations import Guest

router = APIRouter()


# ============== SCHEMAS ==============

class PickupRequestCreate(BaseModel):
    room_number: str
    guest_name: str
    pickup_type: str  # luggage, laundry, package, amenity_request, other
    items_description: str
    item_count: int = 1
    pickup_location: str
    destination: str
    priority: str = "normal"  # low, normal, high, urgent
    scheduled_time: Optional[datetime] = None
    special_instructions: Optional[str] = None
    signature_required: bool = False


class PickupRequestUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    special_instructions: Optional[str] = None
    priority: Optional[str] = None


class PickupRequestRead(BaseModel):
    id: int
    request_number: str
    room_id: int
    room_number: str
    guest_id: Optional[int] = None
    guest_name: str
    pickup_type: str
    items_description: str
    item_count: int
    pickup_location: str
    destination: str
    scheduled_time: Optional[datetime] = None
    priority: str
    status: str
    requested_by: Optional[str] = None
    requested_at: datetime
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    accepted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    notes: Optional[str] = None
    special_instructions: Optional[str] = None
    signature_required: bool = False

    class Config:
        from_attributes = True


class DeliveryCreate(BaseModel):
    delivery_type: str  # room_service, package, laundry, amenity, other
    room_number: str
    guest_name: str
    items_description: str
    item_count: int = 1
    origin_location: str
    destination_location: str
    priority: str = "normal"
    estimated_delivery_time: Optional[datetime] = None
    special_instructions: Optional[str] = None
    signature_required: bool = False
    temperature_sensitive: bool = False
    fragile: bool = False


class DeliveryUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    special_instructions: Optional[str] = None
    priority: Optional[str] = None


class DeliveryRead(BaseModel):
    id: int
    delivery_number: str
    delivery_type: str
    room_id: int
    room_number: str
    guest_id: Optional[int] = None
    guest_name: str
    items_description: str
    item_count: int
    origin_location: str
    destination_location: str
    priority: str
    status: str
    ordered_at: datetime
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    accepted_at: Optional[datetime] = None
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    estimated_delivery_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    special_instructions: Optional[str] = None
    notes: Optional[str] = None
    signature_required: bool = False
    temperature_sensitive: bool = False
    fragile: bool = False

    class Config:
        from_attributes = True


class RunnerDashboard(BaseModel):
    active_pickups: int
    active_deliveries: int
    completed_today: int
    pending_count: int
    avg_completion_time: Optional[int] = None
    on_time_percentage: Optional[float] = None


class RunnerPerformance(BaseModel):
    staff_id: int
    staff_name: str
    date: date
    total_pickups: int
    total_deliveries: int
    completed_pickups: int
    completed_deliveries: int
    avg_pickup_time: Optional[int] = None
    avg_delivery_time: Optional[int] = None
    on_time_percentage: Optional[float] = None
    performance_rating: Optional[float] = None


# ============== PICKUP REQUEST ENDPOINTS ==============

@router.get("/pickups", response_model=List[PickupRequestRead])
async def list_pickup_requests(
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    pickup_type: Optional[str] = Query(None, description="Filter by pickup type"),
    assigned_to: Optional[int] = Query(None, description="Filter by assigned staff"),
    room_number: Optional[str] = Query(None, description="Filter by room"),
    date_from: Optional[date] = Query(None, description="Filter from date"),
    date_to: Optional[date] = Query(None, description="Filter to date"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List all pickup requests with optional filters"""
    query = select(RunnerPickupRequest)

    conditions = []
    if status:
        conditions.append(RunnerPickupRequest.status == status)
    if priority:
        conditions.append(RunnerPickupRequest.priority == priority)
    if pickup_type:
        conditions.append(RunnerPickupRequest.pickup_type == pickup_type)
    if assigned_to:
        conditions.append(RunnerPickupRequest.assigned_to == assigned_to)
    if room_number:
        conditions.append(RunnerPickupRequest.room_number == room_number)
    if date_from:
        conditions.append(RunnerPickupRequest.requested_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conditions.append(RunnerPickupRequest.requested_at <= datetime.combine(date_to, datetime.max.time()))

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(RunnerPickupRequest.requested_at.desc())

    result = await session.exec(query)
    pickups = result.all()

    # Enrich with staff names
    pickup_list = []
    for pickup in pickups:
        pickup_dict = {
            "id": pickup.id,
            "request_number": pickup.request_number,
            "room_id": pickup.room_id,
            "room_number": pickup.room_number,
            "guest_id": pickup.guest_id,
            "guest_name": pickup.guest_name,
            "pickup_type": pickup.pickup_type,
            "items_description": pickup.items_description,
            "item_count": pickup.item_count,
            "pickup_location": pickup.pickup_location,
            "destination": pickup.destination,
            "scheduled_time": pickup.scheduled_time,
            "priority": pickup.priority,
            "status": pickup.status,
            "requested_by": pickup.requested_by,
            "requested_at": pickup.requested_at,
            "assigned_to": pickup.assigned_to,
            "assigned_to_name": None,
            "accepted_at": pickup.accepted_at,
            "completed_at": pickup.completed_at,
            "duration_minutes": pickup.duration_minutes,
            "notes": pickup.notes,
            "special_instructions": pickup.special_instructions,
            "signature_required": pickup.signature_required,
        }

        if pickup.assigned_to:
            staff_result = await session.exec(
                select(Staff).where(Staff.id == pickup.assigned_to)
            )
            staff = staff_result.first()
            if staff:
                pickup_dict["assigned_to_name"] = staff.name

        pickup_list.append(PickupRequestRead(**pickup_dict))

    return pickup_list


@router.get("/pickups/my-tasks", response_model=List[PickupRequestRead])
async def get_my_pickup_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get pickup requests assigned to the current user"""
    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        return []

    query = select(RunnerPickupRequest).where(
        RunnerPickupRequest.assigned_to == staff.id
    )

    if status:
        query = query.where(RunnerPickupRequest.status == status)
    else:
        # Default: show active tasks
        query = query.where(RunnerPickupRequest.status.in_(["pending", "in_progress"]))

    query = query.order_by(RunnerPickupRequest.priority.desc(), RunnerPickupRequest.requested_at.asc())

    result = await session.exec(query)
    pickups = result.all()

    return [PickupRequestRead(
        **{k: v for k, v in pickup.__dict__.items() if not k.startswith('_')},
        assigned_to_name=staff.name
    ) for pickup in pickups]


@router.post("/pickups", response_model=PickupRequestRead)
async def create_pickup_request(
    payload: PickupRequestCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new pickup request"""
    # Find room
    room_result = await session.exec(
        select(Room).where(Room.room_number == payload.room_number)
    )
    room = room_result.first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Generate request number
    request_number = f"PU-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    pickup = RunnerPickupRequest(
        request_number=request_number,
        room_id=room.id,
        room_number=payload.room_number,
        guest_name=payload.guest_name,
        pickup_type=payload.pickup_type,
        items_description=payload.items_description,
        item_count=payload.item_count,
        pickup_location=payload.pickup_location,
        destination=payload.destination,
        priority=payload.priority,
        scheduled_time=payload.scheduled_time,
        special_instructions=payload.special_instructions,
        signature_required=payload.signature_required,
        requested_by=current_user.full_name,
        requested_at=datetime.utcnow(),
    )

    session.add(pickup)
    await session.commit()
    await session.refresh(pickup)

    return PickupRequestRead(**{k: v for k, v in pickup.__dict__.items() if not k.startswith('_')})


@router.get("/pickups/{pickup_id}", response_model=PickupRequestRead)
async def get_pickup_request(
    pickup_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a specific pickup request"""
    result = await session.exec(
        select(RunnerPickupRequest).where(RunnerPickupRequest.id == pickup_id)
    )
    pickup = result.first()

    if not pickup:
        raise HTTPException(status_code=404, detail="Pickup request not found")

    pickup_dict = {k: v for k, v in pickup.__dict__.items() if not k.startswith('_')}

    if pickup.assigned_to:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == pickup.assigned_to)
        )
        staff = staff_result.first()
        if staff:
            pickup_dict["assigned_to_name"] = staff.name

    return PickupRequestRead(**pickup_dict)


@router.patch("/pickups/{pickup_id}", response_model=PickupRequestRead)
async def update_pickup_request(
    pickup_id: int,
    payload: PickupRequestUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a pickup request"""
    result = await session.exec(
        select(RunnerPickupRequest).where(RunnerPickupRequest.id == pickup_id)
    )
    pickup = result.first()

    if not pickup:
        raise HTTPException(status_code=404, detail="Pickup request not found")

    # Check if assigned_to is being updated (new assignment)
    new_assignment = payload.assigned_to is not None and payload.assigned_to != pickup.assigned_to

    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(pickup, field, value)

    pickup.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(pickup)

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
                    title=f"New Pickup Request: Room {pickup.room_number}",
                    message=f"Pickup {pickup.pickup_type} from {pickup.pickup_location} to {pickup.destination}. Priority: {pickup.priority or 'normal'}.",
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
                    task_type=f"pickup ({pickup.pickup_type})",
                    room_number=pickup.room_number,
                    priority=pickup.priority or "normal",
                    notes=pickup.special_instructions,
                )
        except Exception as e:
            import logging
            logging.error(f"Failed to create notification: {e}")

    return PickupRequestRead(**{k: v for k, v in pickup.__dict__.items() if not k.startswith('_')})


@router.post("/pickups/{pickup_id}/accept", response_model=PickupRequestRead)
async def accept_pickup_request(
    pickup_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Accept/assign a pickup request to the current user"""
    result = await session.exec(
        select(RunnerPickupRequest).where(RunnerPickupRequest.id == pickup_id)
    )
    pickup = result.first()

    if not pickup:
        raise HTTPException(status_code=404, detail="Pickup request not found")

    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        raise HTTPException(status_code=400, detail="Staff record not found for current user")

    pickup.assigned_to = staff.id
    pickup.accepted_at = datetime.utcnow()
    pickup.status = "in_progress"
    pickup.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(pickup)

    return PickupRequestRead(
        **{k: v for k, v in pickup.__dict__.items() if not k.startswith('_')},
        assigned_to_name=staff.name
    )


@router.post("/pickups/{pickup_id}/complete", response_model=PickupRequestRead)
async def complete_pickup_request(
    pickup_id: int,
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark a pickup request as completed"""
    result = await session.exec(
        select(RunnerPickupRequest).where(RunnerPickupRequest.id == pickup_id)
    )
    pickup = result.first()

    if not pickup:
        raise HTTPException(status_code=404, detail="Pickup request not found")

    pickup.status = "completed"
    pickup.completed_at = datetime.utcnow()
    if notes:
        pickup.notes = notes

    # Calculate duration
    if pickup.accepted_at:
        duration = (pickup.completed_at - pickup.accepted_at).total_seconds() / 60
        pickup.duration_minutes = int(duration)

    pickup.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(pickup)

    # Update runner activity log
    await _update_runner_activity(session, pickup.assigned_to, "pickup")

    return PickupRequestRead(**{k: v for k, v in pickup.__dict__.items() if not k.startswith('_')})


# ============== DELIVERY ENDPOINTS ==============

@router.get("/deliveries", response_model=List[DeliveryRead])
async def list_deliveries(
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    delivery_type: Optional[str] = Query(None, description="Filter by delivery type"),
    assigned_to: Optional[int] = Query(None, description="Filter by assigned staff"),
    room_number: Optional[str] = Query(None, description="Filter by room"),
    date_from: Optional[date] = Query(None, description="Filter from date"),
    date_to: Optional[date] = Query(None, description="Filter to date"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List all deliveries with optional filters"""
    query = select(RunnerDelivery)

    conditions = []
    if status:
        conditions.append(RunnerDelivery.status == status)
    if priority:
        conditions.append(RunnerDelivery.priority == priority)
    if delivery_type:
        conditions.append(RunnerDelivery.delivery_type == delivery_type)
    if assigned_to:
        conditions.append(RunnerDelivery.assigned_to == assigned_to)
    if room_number:
        conditions.append(RunnerDelivery.room_number == room_number)
    if date_from:
        conditions.append(RunnerDelivery.ordered_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conditions.append(RunnerDelivery.ordered_at <= datetime.combine(date_to, datetime.max.time()))

    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(RunnerDelivery.ordered_at.desc())

    result = await session.exec(query)
    deliveries = result.all()

    # Enrich with staff names
    delivery_list = []
    for delivery in deliveries:
        delivery_dict = {k: v for k, v in delivery.__dict__.items() if not k.startswith('_')}
        delivery_dict["assigned_to_name"] = None

        if delivery.assigned_to:
            staff_result = await session.exec(
                select(Staff).where(Staff.id == delivery.assigned_to)
            )
            staff = staff_result.first()
            if staff:
                delivery_dict["assigned_to_name"] = staff.name

        delivery_list.append(DeliveryRead(**delivery_dict))

    return delivery_list


@router.get("/deliveries/my-tasks", response_model=List[DeliveryRead])
async def get_my_delivery_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get deliveries assigned to the current user"""
    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        return []

    query = select(RunnerDelivery).where(
        RunnerDelivery.assigned_to == staff.id
    )

    if status:
        query = query.where(RunnerDelivery.status == status)
    else:
        # Default: show active tasks
        query = query.where(RunnerDelivery.status.in_(["pending", "in_transit"]))

    query = query.order_by(RunnerDelivery.priority.desc(), RunnerDelivery.ordered_at.asc())

    result = await session.exec(query)
    deliveries = result.all()

    return [DeliveryRead(
        **{k: v for k, v in d.__dict__.items() if not k.startswith('_')},
        assigned_to_name=staff.name
    ) for d in deliveries]


@router.post("/deliveries", response_model=DeliveryRead)
async def create_delivery(
    payload: DeliveryCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new delivery"""
    # Find room
    room_result = await session.exec(
        select(Room).where(Room.room_number == payload.room_number)
    )
    room = room_result.first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Generate delivery number
    delivery_number = f"DL-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    delivery = RunnerDelivery(
        delivery_number=delivery_number,
        delivery_type=payload.delivery_type,
        room_id=room.id,
        room_number=payload.room_number,
        guest_name=payload.guest_name,
        items_description=payload.items_description,
        item_count=payload.item_count,
        origin_location=payload.origin_location,
        destination_location=payload.destination_location,
        priority=payload.priority,
        estimated_delivery_time=payload.estimated_delivery_time,
        special_instructions=payload.special_instructions,
        signature_required=payload.signature_required,
        temperature_sensitive=payload.temperature_sensitive,
        fragile=payload.fragile,
        ordered_at=datetime.utcnow(),
    )

    session.add(delivery)
    await session.commit()
    await session.refresh(delivery)

    return DeliveryRead(**{k: v for k, v in delivery.__dict__.items() if not k.startswith('_')})


@router.get("/deliveries/{delivery_id}", response_model=DeliveryRead)
async def get_delivery(
    delivery_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a specific delivery"""
    result = await session.exec(
        select(RunnerDelivery).where(RunnerDelivery.id == delivery_id)
    )
    delivery = result.first()

    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    delivery_dict = {k: v for k, v in delivery.__dict__.items() if not k.startswith('_')}

    if delivery.assigned_to:
        staff_result = await session.exec(
            select(Staff).where(Staff.id == delivery.assigned_to)
        )
        staff = staff_result.first()
        if staff:
            delivery_dict["assigned_to_name"] = staff.name

    return DeliveryRead(**delivery_dict)


@router.patch("/deliveries/{delivery_id}", response_model=DeliveryRead)
async def update_delivery(
    delivery_id: int,
    payload: DeliveryUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a delivery"""
    result = await session.exec(
        select(RunnerDelivery).where(RunnerDelivery.id == delivery_id)
    )
    delivery = result.first()

    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    # Check if assigned_to is being updated (new assignment)
    new_assignment = payload.assigned_to is not None and payload.assigned_to != delivery.assigned_to

    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(delivery, field, value)

    delivery.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(delivery)

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
                    title=f"New Delivery: Room {delivery.room_number}",
                    message=f"Deliver {delivery.delivery_type} from {delivery.origin_location} to {delivery.destination_location}. Priority: {delivery.priority or 'normal'}.",
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
                    task_type=f"delivery ({delivery.delivery_type})",
                    room_number=delivery.room_number,
                    priority=delivery.priority or "normal",
                    notes=delivery.special_instructions,
                )
        except Exception as e:
            import logging
            logging.error(f"Failed to create notification: {e}")

    return DeliveryRead(**{k: v for k, v in delivery.__dict__.items() if not k.startswith('_')})


@router.post("/deliveries/{delivery_id}/accept", response_model=DeliveryRead)
async def accept_delivery(
    delivery_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Accept/assign a delivery to the current user"""
    result = await session.exec(
        select(RunnerDelivery).where(RunnerDelivery.id == delivery_id)
    )
    delivery = result.first()

    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        raise HTTPException(status_code=400, detail="Staff record not found for current user")

    delivery.assigned_to = staff.id
    delivery.accepted_at = datetime.utcnow()
    delivery.status = "in_transit"
    delivery.picked_up_at = datetime.utcnow()
    delivery.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(delivery)

    return DeliveryRead(
        **{k: v for k, v in delivery.__dict__.items() if not k.startswith('_')},
        assigned_to_name=staff.name
    )


@router.post("/deliveries/{delivery_id}/complete", response_model=DeliveryRead)
async def complete_delivery(
    delivery_id: int,
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark a delivery as completed"""
    result = await session.exec(
        select(RunnerDelivery).where(RunnerDelivery.id == delivery_id)
    )
    delivery = result.first()

    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    delivery.status = "delivered"
    delivery.delivered_at = datetime.utcnow()
    delivery.actual_delivery_time = datetime.utcnow()
    if notes:
        delivery.notes = notes

    # Calculate duration
    if delivery.accepted_at:
        duration = (delivery.delivered_at - delivery.accepted_at).total_seconds() / 60
        delivery.duration_minutes = int(duration)

    delivery.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(delivery)

    # Update runner activity log
    await _update_runner_activity(session, delivery.assigned_to, "delivery")

    return DeliveryRead(**{k: v for k, v in delivery.__dict__.items() if not k.startswith('_')})


# ============== DASHBOARD & PERFORMANCE ==============

@router.get("/dashboard", response_model=RunnerDashboard)
async def get_runner_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get runner dashboard statistics"""
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # Active pickups
    active_pickups_result = await session.exec(
        select(func.count(RunnerPickupRequest.id)).where(
            RunnerPickupRequest.status.in_(["pending", "in_progress"])
        )
    )
    active_pickups = active_pickups_result.one() or 0

    # Active deliveries
    active_deliveries_result = await session.exec(
        select(func.count(RunnerDelivery.id)).where(
            RunnerDelivery.status.in_(["pending", "in_transit"])
        )
    )
    active_deliveries = active_deliveries_result.one() or 0

    # Completed today
    completed_pickups_result = await session.exec(
        select(func.count(RunnerPickupRequest.id)).where(
            and_(
                RunnerPickupRequest.status == "completed",
                RunnerPickupRequest.completed_at >= today_start,
                RunnerPickupRequest.completed_at <= today_end
            )
        )
    )
    completed_pickups = completed_pickups_result.one() or 0

    completed_deliveries_result = await session.exec(
        select(func.count(RunnerDelivery.id)).where(
            and_(
                RunnerDelivery.status == "delivered",
                RunnerDelivery.delivered_at >= today_start,
                RunnerDelivery.delivered_at <= today_end
            )
        )
    )
    completed_deliveries = completed_deliveries_result.one() or 0

    # Pending count
    pending_pickups_result = await session.exec(
        select(func.count(RunnerPickupRequest.id)).where(
            RunnerPickupRequest.status == "pending"
        )
    )
    pending_pickups = pending_pickups_result.one() or 0

    pending_deliveries_result = await session.exec(
        select(func.count(RunnerDelivery.id)).where(
            RunnerDelivery.status == "pending"
        )
    )
    pending_deliveries = pending_deliveries_result.one() or 0

    # Average completion time for today
    avg_time_result = await session.exec(
        select(func.avg(RunnerPickupRequest.duration_minutes)).where(
            and_(
                RunnerPickupRequest.status == "completed",
                RunnerPickupRequest.completed_at >= today_start,
                RunnerPickupRequest.duration_minutes.isnot(None)
            )
        )
    )
    avg_time = avg_time_result.one()

    return RunnerDashboard(
        active_pickups=active_pickups,
        active_deliveries=active_deliveries,
        completed_today=completed_pickups + completed_deliveries,
        pending_count=pending_pickups + pending_deliveries,
        avg_completion_time=int(avg_time) if avg_time else None,
        on_time_percentage=None  # TODO: Calculate based on estimated vs actual times
    )


@router.get("/my-dashboard", response_model=RunnerDashboard)
async def get_my_runner_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get dashboard statistics for the current runner"""
    # Find staff record for current user
    staff_result = await session.exec(
        select(Staff).where(Staff.user_id == current_user.id)
    )
    staff = staff_result.first()

    if not staff:
        return RunnerDashboard(
            active_pickups=0,
            active_deliveries=0,
            completed_today=0,
            pending_count=0
        )

    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # My active pickups
    active_pickups_result = await session.exec(
        select(func.count(RunnerPickupRequest.id)).where(
            and_(
                RunnerPickupRequest.assigned_to == staff.id,
                RunnerPickupRequest.status.in_(["pending", "in_progress"])
            )
        )
    )
    active_pickups = active_pickups_result.one() or 0

    # My active deliveries
    active_deliveries_result = await session.exec(
        select(func.count(RunnerDelivery.id)).where(
            and_(
                RunnerDelivery.assigned_to == staff.id,
                RunnerDelivery.status.in_(["pending", "in_transit"])
            )
        )
    )
    active_deliveries = active_deliveries_result.one() or 0

    # My completed today
    completed_pickups_result = await session.exec(
        select(func.count(RunnerPickupRequest.id)).where(
            and_(
                RunnerPickupRequest.assigned_to == staff.id,
                RunnerPickupRequest.status == "completed",
                RunnerPickupRequest.completed_at >= today_start,
                RunnerPickupRequest.completed_at <= today_end
            )
        )
    )
    completed_pickups = completed_pickups_result.one() or 0

    completed_deliveries_result = await session.exec(
        select(func.count(RunnerDelivery.id)).where(
            and_(
                RunnerDelivery.assigned_to == staff.id,
                RunnerDelivery.status == "delivered",
                RunnerDelivery.delivered_at >= today_start,
                RunnerDelivery.delivered_at <= today_end
            )
        )
    )
    completed_deliveries = completed_deliveries_result.one() or 0

    return RunnerDashboard(
        active_pickups=active_pickups,
        active_deliveries=active_deliveries,
        completed_today=completed_pickups + completed_deliveries,
        pending_count=0,  # For personal dashboard, focus on assigned tasks
        avg_completion_time=None,
        on_time_percentage=None
    )


@router.get("/performance/{staff_id}", response_model=RunnerPerformance)
async def get_runner_performance(
    staff_id: int,
    target_date: Optional[date] = Query(None, description="Date to get performance for"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get performance metrics for a specific runner"""
    target_date = target_date or date.today()

    # Get staff info
    staff_result = await session.exec(
        select(Staff).where(Staff.id == staff_id)
    )
    staff = staff_result.first()

    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    # Check for existing activity log
    log_result = await session.exec(
        select(RunnerActivityLog).where(
            and_(
                RunnerActivityLog.staff_id == staff_id,
                RunnerActivityLog.date == target_date
            )
        )
    )
    activity_log = log_result.first()

    if activity_log:
        return RunnerPerformance(
            staff_id=staff_id,
            staff_name=staff.name,
            date=target_date,
            total_pickups=activity_log.total_pickups,
            total_deliveries=activity_log.total_deliveries,
            completed_pickups=activity_log.completed_pickups,
            completed_deliveries=activity_log.completed_deliveries,
            avg_pickup_time=activity_log.avg_pickup_time,
            avg_delivery_time=activity_log.avg_delivery_time,
            on_time_percentage=activity_log.on_time_percentage,
            performance_rating=activity_log.performance_rating
        )

    # Calculate from raw data
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = datetime.combine(target_date, datetime.max.time())

    # Pickups
    pickups_result = await session.exec(
        select(RunnerPickupRequest).where(
            and_(
                RunnerPickupRequest.assigned_to == staff_id,
                RunnerPickupRequest.requested_at >= day_start,
                RunnerPickupRequest.requested_at <= day_end
            )
        )
    )
    pickups = pickups_result.all()

    # Deliveries
    deliveries_result = await session.exec(
        select(RunnerDelivery).where(
            and_(
                RunnerDelivery.assigned_to == staff_id,
                RunnerDelivery.ordered_at >= day_start,
                RunnerDelivery.ordered_at <= day_end
            )
        )
    )
    deliveries = deliveries_result.all()

    completed_pickups = [p for p in pickups if p.status == "completed"]
    completed_deliveries = [d for d in deliveries if d.status == "delivered"]

    avg_pickup_time = None
    if completed_pickups:
        times = [p.duration_minutes for p in completed_pickups if p.duration_minutes]
        if times:
            avg_pickup_time = sum(times) // len(times)

    avg_delivery_time = None
    if completed_deliveries:
        times = [d.duration_minutes for d in completed_deliveries if d.duration_minutes]
        if times:
            avg_delivery_time = sum(times) // len(times)

    return RunnerPerformance(
        staff_id=staff_id,
        staff_name=staff.name,
        date=target_date,
        total_pickups=len(pickups),
        total_deliveries=len(deliveries),
        completed_pickups=len(completed_pickups),
        completed_deliveries=len(completed_deliveries),
        avg_pickup_time=avg_pickup_time,
        avg_delivery_time=avg_delivery_time,
        on_time_percentage=None,
        performance_rating=None
    )


# ============== HELPER FUNCTIONS ==============

async def _update_runner_activity(session: AsyncSession, staff_id: Optional[int], task_type: str):
    """Update or create runner activity log for today"""
    if not staff_id:
        return

    today = date.today()

    # Check for existing log
    log_result = await session.exec(
        select(RunnerActivityLog).where(
            and_(
                RunnerActivityLog.staff_id == staff_id,
                RunnerActivityLog.date == today
            )
        )
    )
    activity_log = log_result.first()

    if not activity_log:
        activity_log = RunnerActivityLog(
            staff_id=staff_id,
            date=today,
            total_pickups=0,
            total_deliveries=0,
            completed_pickups=0,
            completed_deliveries=0
        )
        session.add(activity_log)

    if task_type == "pickup":
        activity_log.completed_pickups += 1
        activity_log.total_pickups += 1
    elif task_type == "delivery":
        activity_log.completed_deliveries += 1
        activity_log.total_deliveries += 1

    await session.commit()
# ============== AUTO-ASSIGNMENT ENDPOINTS ==============

class RunnerAutoAssignResult(BaseModel):
    task_id: int
    task_type: str  # pickup or delivery
    assigned_to: Optional[int] = None
    assigned_to_name: Optional[str] = None
    score: Optional[float] = None
    success: bool
    message: str


class RunnerBulkAutoAssignResult(BaseModel):
    total_tasks: int
    assigned_count: int
    failed_count: int
    results: List[RunnerAutoAssignResult]


@router.post("/pickups/{pickup_id}/auto-assign", response_model=RunnerAutoAssignResult)
async def auto_assign_pickup(
    pickup_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Auto-assign a pickup request to the best available runner.
    Uses multi-factor scoring: workload (30%), skills (25%), availability (20%),
    performance (15%), floor proximity (10%).
    """
    from app.services.staff_scheduling_service import get_scheduling_service

    result = await session.exec(
        select(RunnerPickupRequest).where(RunnerPickupRequest.id == pickup_id)
    )
    pickup = result.first()

    if not pickup:
        raise HTTPException(status_code=404, detail="Pickup request not found")

    if pickup.status in ["completed", "cancelled"]:
        return RunnerAutoAssignResult(
            task_id=pickup_id,
            task_type="pickup",
            success=False,
            message=f"Pickup is already {pickup.status}"
        )

    # Use scheduling service to find best staff
    scheduling_service = get_scheduling_service(session)
    best_staff = await scheduling_service.find_best_staff_for_task(
        task_type="room_service",
        priority=pickup.priority or "normal",
        room_number=pickup.room_number
    )

    if not best_staff:
        return RunnerAutoAssignResult(
            task_id=pickup_id,
            task_type="pickup",
            success=False,
            message="No available runner staff found"
        )

    # Assign the pickup
    pickup.assigned_to = best_staff.staff_id
    pickup.status = "in_progress"
    pickup.updated_at = datetime.utcnow()
    await session.commit()

    # Create notification
    try:
        from app.models.guest_chat import StaffNotification
        notification = StaffNotification(
            staff_id=best_staff.staff_id,
            notification_type="task_assigned",
            title=f"Auto-Assigned: Pickup from Room {pickup.room_number}",
            message=f"{pickup.pickup_type} pickup: {pickup.items_description}. Priority: {pickup.priority or 'normal'}.",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to create notification: {e}")

    return RunnerAutoAssignResult(
        task_id=pickup_id,
        task_type="pickup",
        assigned_to=best_staff.staff_id,
        assigned_to_name=best_staff.staff_name,
        score=round(best_staff.total_score, 2),
        success=True,
        message=f"Pickup assigned to {best_staff.staff_name} (score: {best_staff.total_score:.2f})"
    )


@router.post("/deliveries/{delivery_id}/auto-assign", response_model=RunnerAutoAssignResult)
async def auto_assign_delivery(
    delivery_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Auto-assign a delivery to the best available runner."""
    from app.services.staff_scheduling_service import get_scheduling_service

    result = await session.exec(
        select(RunnerDelivery).where(RunnerDelivery.id == delivery_id)
    )
    delivery = result.first()

    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    if delivery.status in ["delivered", "cancelled"]:
        return RunnerAutoAssignResult(
            task_id=delivery_id,
            task_type="delivery",
            success=False,
            message=f"Delivery is already {delivery.status}"
        )

    scheduling_service = get_scheduling_service(session)
    best_staff = await scheduling_service.find_best_staff_for_task(
        task_type="room_service",
        priority=delivery.priority or "normal",
        room_number=delivery.room_number
    )

    if not best_staff:
        return RunnerAutoAssignResult(
            task_id=delivery_id,
            task_type="delivery",
            success=False,
            message="No available runner staff found"
        )

    delivery.assigned_to = best_staff.staff_id
    delivery.status = "in_transit"
    delivery.picked_up_at = datetime.utcnow()
    delivery.updated_at = datetime.utcnow()
    await session.commit()

    try:
        from app.models.guest_chat import StaffNotification
        notification = StaffNotification(
            staff_id=best_staff.staff_id,
            notification_type="task_assigned",
            title=f"Auto-Assigned: Delivery to Room {delivery.room_number}",
            message=f"{delivery.delivery_type}: {delivery.items_description}. Priority: {delivery.priority or 'normal'}.",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to create notification: {e}")

    return RunnerAutoAssignResult(
        task_id=delivery_id,
        task_type="delivery",
        assigned_to=best_staff.staff_id,
        assigned_to_name=best_staff.staff_name,
        score=round(best_staff.total_score, 2),
        success=True,
        message=f"Delivery assigned to {best_staff.staff_name} (score: {best_staff.total_score:.2f})"
    )


@router.post("/tasks/auto-assign-all", response_model=RunnerBulkAutoAssignResult)
async def auto_assign_all_pending_runner_tasks(
    priority: Optional[str] = Query(None, description="Only assign tasks with this priority"),
    max_tasks: int = Query(50, description="Maximum tasks to assign in one call"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Auto-assign all pending pickups and deliveries to available runners."""
    from app.services.staff_scheduling_service import get_scheduling_service

    results = []
    assigned_count = 0
    total_count = 0
    scheduling_service = get_scheduling_service(session)

    # Get pending pickups
    pickup_query = select(RunnerPickupRequest).where(
        RunnerPickupRequest.status == "pending"
    )
    if priority:
        pickup_query = pickup_query.where(RunnerPickupRequest.priority == priority)
    pickup_query = pickup_query.order_by(
        RunnerPickupRequest.priority.desc(),
        RunnerPickupRequest.requested_at.asc()
    ).limit(max_tasks // 2)

    pickups = (await session.exec(pickup_query)).all()
    total_count += len(pickups)

    for pickup in pickups:
        best_staff = await scheduling_service.find_best_staff_for_task(
            task_type="room_service",
            priority=pickup.priority or "normal",
            room_number=pickup.room_number
        )

        if best_staff:
            pickup.assigned_to = best_staff.staff_id
            pickup.status = "in_progress"
            pickup.updated_at = datetime.utcnow()
            assigned_count += 1
            results.append(RunnerAutoAssignResult(
                task_id=pickup.id,
                task_type="pickup",
                assigned_to=best_staff.staff_id,
                assigned_to_name=best_staff.staff_name,
                score=round(best_staff.total_score, 2),
                success=True,
                message=f"Assigned to {best_staff.staff_name}"
            ))
        else:
            results.append(RunnerAutoAssignResult(
                task_id=pickup.id,
                task_type="pickup",
                success=False,
                message="No available staff"
            ))

    # Get pending deliveries
    delivery_query = select(RunnerDelivery).where(
        RunnerDelivery.status == "pending"
    )
    if priority:
        delivery_query = delivery_query.where(RunnerDelivery.priority == priority)
    delivery_query = delivery_query.order_by(
        RunnerDelivery.priority.desc(),
        RunnerDelivery.ordered_at.asc()
    ).limit(max_tasks // 2)

    deliveries = (await session.exec(delivery_query)).all()
    total_count += len(deliveries)

    for delivery in deliveries:
        best_staff = await scheduling_service.find_best_staff_for_task(
            task_type="room_service",
            priority=delivery.priority or "normal",
            room_number=delivery.room_number
        )

        if best_staff:
            delivery.assigned_to = best_staff.staff_id
            delivery.status = "in_transit"
            delivery.picked_up_at = datetime.utcnow()
            delivery.updated_at = datetime.utcnow()
            assigned_count += 1
            results.append(RunnerAutoAssignResult(
                task_id=delivery.id,
                task_type="delivery",
                assigned_to=best_staff.staff_id,
                assigned_to_name=best_staff.staff_name,
                score=round(best_staff.total_score, 2),
                success=True,
                message=f"Assigned to {best_staff.staff_name}"
            ))
        else:
            results.append(RunnerAutoAssignResult(
                task_id=delivery.id,
                task_type="delivery",
                success=False,
                message="No available staff"
            ))

    await session.commit()

    return RunnerBulkAutoAssignResult(
        total_tasks=total_count,
        assigned_count=assigned_count,
        failed_count=total_count - assigned_count,
        results=results
    )


@router.get("/staff/workload")
async def get_runner_staff_workload(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get workload summary for all runner/bell desk staff"""
    from app.services.staff_scheduling_service import get_scheduling_service

    scheduling_service = get_scheduling_service(session)
    workload_summary = await scheduling_service.get_staff_workload_summary(department="front_desk")

    return {
        "department": "runner",
        "staff_count": len(workload_summary),
        "available_count": len([s for s in workload_summary if s["availability"] == "available"]),
        "staff": workload_summary
    }
