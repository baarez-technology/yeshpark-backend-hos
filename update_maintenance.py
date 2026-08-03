"""Script to update maintenance.py with new endpoints"""

file_path = 'E:/Glimmora_Updated/Backend/app/api/v1/maintenance.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already updated
if 'ForceAssignWorkOrderRequest' in content:
    print('Force-assign endpoints already exist in maintenance.py')
    exit(0)

# Find the end of file to append new endpoints
new_endpoints = '''

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
    session: AsyncSession = Depends(get_session),
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
    session: AsyncSession = Depends(get_session),
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
    session: AsyncSession = Depends(get_session),
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
    work_order.status = "open"
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
    session: AsyncSession = Depends(get_session),
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
    session: AsyncSession = Depends(get_session),
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
    session: AsyncSession = Depends(get_session),
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
    session: AsyncSession = Depends(get_session),
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
'''

# Append to file
content = content.rstrip() + new_endpoints

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Maintenance endpoints updated successfully')
