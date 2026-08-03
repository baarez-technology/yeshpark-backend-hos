"""Script to update housekeeping.py with new endpoints"""

file_path = 'E:/Glimmora_Updated/Backend/app/api/v1/housekeeping.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already updated
if 'ForceAssignRequest' in content:
    print('Force-assign endpoints already exist')
    exit(0)

old_text = '''@router.get("/staff/workload")
async def get_housekeeping_staff_workload(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get workload summary for all housekeeping staff"""
    from app.services.staff_scheduling_service import get_scheduling_service

    scheduling_service = get_scheduling_service(session)
    workload_summary = await scheduling_service.get_staff_workload_summary(department="housekeeping")

    return {
        "department": "housekeeping",
        "staff_count": len(workload_summary),
        "available_count": len([s for s in workload_summary if s["availability"] == "available"]),
        "staff": workload_summary
    }


# ==================== DIGITAL KEY VALIDATION ===================='''

new_text = '''@router.get("/staff/workload")
async def get_housekeeping_staff_workload(
    session: AsyncSession = Depends(get_session),
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
    session: AsyncSession = Depends(get_session),
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

    task.assigned_to = staff.id
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

    notification = StaffNotification(
        staff_id=staff.id,
        notification_type="urgent_task_assigned",
        title=f"URGENT: {task.task_type.capitalize()} Task Force-Assigned",
        message=f"Room {room_number} - Priority: {task.priority}. Reason: {payload.reason}.",
        is_read=False,
        created_at=datetime.utcnow()
    )
    session.add(notification)
    await session.commit()

    return ForceAssignResponse(
        task_id=task_id,
        staff_id=staff.id,
        staff_name=f"{staff.first_name} {staff.last_name}",
        success=True,
        message=f"Task force-assigned to {staff.first_name} {staff.last_name}.",
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
    payload: Optional[AcceptTaskRequest] = None,
    session: AsyncSession = Depends(get_session),
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

    task.acceptance_status = "accepted"
    task.accepted_at = datetime.utcnow()
    task.status = "in_progress"
    task.started_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    await session.commit()

    if task.force_assigned and task.force_assigned_by:
        notification = StaffNotification(
            staff_id=task.force_assigned_by,
            notification_type="task_accepted",
            title="Force-Assigned Task Accepted",
            message=f"Task #{task_id} accepted by {staff.first_name} {staff.last_name}.",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        await session.commit()

    return TaskAcceptanceResponse(task_id=task_id, status=task.status, acceptance_status="accepted", message="Task accepted and started")


@router.post("/tasks/{task_id}/decline", response_model=TaskAcceptanceResponse)
async def decline_task(
    task_id: int,
    payload: DeclineTaskRequest,
    session: AsyncSession = Depends(get_session),
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
    room_number = room.number if room else str(task.room_id)
    declined_by_name = f"{staff.first_name} {staff.last_name}"
    force_assigned_by = task.force_assigned_by

    task.acceptance_status = "declined"
    task.decline_reason = payload.reason
    task.declined_at = datetime.utcnow()
    task.assigned_to = None
    task.status = "pending"
    task.force_assigned = False
    task.updated_at = datetime.utcnow()
    await session.commit()

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

    return TaskAcceptanceResponse(task_id=task_id, status="pending", acceptance_status="declined", message="Task declined.", declined_reason=payload.reason)


@router.get("/tasks/pending-acceptance")
async def get_tasks_pending_acceptance(
    session: AsyncSession = Depends(get_session),
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
    session: AsyncSession = Depends(get_session),
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


# ==================== DIGITAL KEY VALIDATION ===================='''

if old_text in content:
    content = content.replace(old_text, new_text)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Housekeeping endpoints updated successfully')
else:
    print('Pattern not found - checking file')
