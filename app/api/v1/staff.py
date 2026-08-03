from typing import List, Optional
from datetime import datetime, date, time
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Path
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, EmailStr
import json

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user, get_password_hash
from app.models.user import User
from app.models.staff import Staff, StaffAttendance, StaffSchedule, StaffLeave, StaffPerformanceMetrics
from app.models.operations import HousekeepingTask
from app.services.admin_notification_service import notify_staff_leave_request
from app.core.roles import check_access, has_role_access, VALID_STAFF_ROLES, ROLE_DEPARTMENT_MAP

router = APIRouter()


# ============== SCHEMAS ==============

class StaffRead(BaseModel):
    id: int
    user_id: Optional[int] = None
    employee_id: Optional[str] = None
    name: str
    role: str
    department: Optional[str] = None
    email: str
    personal_email: Optional[str] = None
    phone: Optional[str] = None
    status: str = "active"
    shift: Optional[str] = None
    hire_date: str
    avatar: Optional[str] = None
    performance_rating: Optional[float] = None
    clocked_in: bool = False

    class Config:
        from_attributes = True


class StaffCreateResponse(StaffRead):
    """Extended response returned only on staff creation — includes the temp password."""
    temp_password: Optional[str] = None
    must_reset_password: bool = False
    email_sent: bool = False


class StaffFullProfile(BaseModel):
    id: int
    user_id: Optional[int] = None
    employee_id: Optional[str] = None
    name: str
    email: str
    personal_email: Optional[str] = None
    phone: Optional[str] = None
    role: str
    department: str
    specialty: Optional[str] = None
    status: str
    shift: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    clocked_in: bool = False
    clock_in_time: Optional[str] = None
    supervisor_id: Optional[int] = None
    supervisor_name: Optional[str] = None
    floor_assignment: Optional[List[str]] = None
    hire_date: str
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    address: Optional[str] = None
    salary: Optional[float] = None
    hourly_rate: Optional[float] = None
    avatar: Optional[str] = None
    performance_rating: Optional[float] = None
    certifications: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    languages_spoken: Optional[List[str]] = None
    schedule: Optional[List[dict]] = None
    attendance_stats: Optional[dict] = None

    class Config:
        from_attributes = True


class StaffCreate(BaseModel):
    email: str                         # Work email (used for login)
    personal_email: Optional[str] = None  # Personal email (credentials sent here)
    full_name: str
    phone: Optional[str] = None
    role: str = "receptionist"
    department: Optional[str] = None  # Auto-derived from role if not provided
    password: Optional[str] = None    # Auto-generated temp password if not provided
    specialty: Optional[str] = None
    shift: Optional[str] = None
    hourly_rate: Optional[float] = None
    permissions: Optional[dict] = None  # {"dashboard": {"view": true, "edit": false, "delete": false}, ...}


class StaffUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    personal_email: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    status: Optional[str] = None
    shift: Optional[str] = None
    specialty: Optional[str] = None
    supervisor_id: Optional[int] = None
    floor_assignment: Optional[List[str]] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    hourly_rate: Optional[float] = None
    avatar: Optional[str] = None
    skills: Optional[List[str]] = None
    languages_spoken: Optional[List[str]] = None


class ShiftAssignment(BaseModel):
    schedule_date: str  # YYYY-MM-DD
    shift_type: str  # morning, afternoon, evening, night
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    department: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class AttendanceRecord(BaseModel):
    action: str  # clock_in, clock_out
    location: Optional[str] = None
    notes: Optional[str] = None


class LeaveRequest(BaseModel):
    leave_type: str  # vacation, sick, personal, emergency, bereavement
    start_date: str
    end_date: str
    reason: Optional[str] = None


class MessageRequest(BaseModel):
    subject: str
    message: str
    priority: str = "normal"  # low, normal, high, urgent


# ============== HELPER FUNCTIONS ==============

def staff_to_read(staff: Staff) -> StaffRead:
    """Convert Staff model to StaffRead schema"""
    return StaffRead(
        id=staff.id,
        user_id=staff.user_id,
        employee_id=staff.employee_id,
        name=staff.name,
        role=staff.role,
        department=staff.department,
        email=staff.email,
        personal_email=staff.personal_email,
        phone=staff.phone,
        status=staff.status,
        shift=staff.shift,
        hire_date=staff.hire_date.isoformat() if staff.hire_date else None,
        avatar=staff.avatar,
        performance_rating=staff.performance_rating,
        clocked_in=staff.clocked_in or False,
    )


def user_to_staff_read(user: User) -> StaffRead:
    """Convert User model to StaffRead schema (fallback)"""
    return StaffRead(
        id=user.id,
        name=user.full_name or user.email,
        role=user.role,
        email=user.email,
        phone=user.phone,
        status="active" if user.is_active else "off-duty",
        shift=None,
        hire_date=user.created_at.date().isoformat(),
        avatar=user.avatar,
    )


async def get_or_create_staff_record(session: AsyncSession, user: User) -> Staff:
    """Get existing staff record or create one from user"""
    result = await session.exec(select(Staff).where(Staff.user_id == user.id))
    staff = result.first()

    if not staff:
        # Create staff record from user
        staff = Staff(
            user_id=user.id,
            name=user.full_name or user.email,
            email=user.email,
            phone=user.phone,
            role=user.role,
            department=user.role if user.role in ['housekeeping', 'maintenance', 'runner', 'front_desk', 'finance'] else 'general',
            status="active" if user.is_active else "inactive",
            hire_date=user.created_at.date(),
        )
        session.add(staff)
        await session.commit()
        await session.refresh(staff)

    return staff


# ============== ENDPOINTS ==============

@router.get("/me", response_model=StaffFullProfile)
async def get_my_profile(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get current staff member's full profile"""
    # Find staff record for current user
    result = await session.exec(select(Staff).where(Staff.user_id == current_user.id))
    staff = result.first()

    if staff:
        # Get supervisor name if exists
        supervisor_name = None
        if staff.supervisor_id:
            sup_result = await session.exec(select(Staff).where(Staff.id == staff.supervisor_id))
            supervisor = sup_result.first()
            if supervisor:
                supervisor_name = supervisor.name

        # Parse JSON fields safely
        floor_assignment = None
        if staff.floor_assignment:
            if isinstance(staff.floor_assignment, str):
                try:
                    floor_assignment = json.loads(staff.floor_assignment)
                except:
                    floor_assignment = [staff.floor_assignment]
            else:
                floor_assignment = staff.floor_assignment
        # Ensure all floor values are strings
        if floor_assignment and isinstance(floor_assignment, list):
            floor_assignment = [str(f) for f in floor_assignment]

        certifications = None
        if staff.certifications:
            if isinstance(staff.certifications, str):
                try:
                    certifications = json.loads(staff.certifications)
                except:
                    certifications = [staff.certifications]
            else:
                certifications = staff.certifications

        languages = None
        if staff.languages_spoken:
            if isinstance(staff.languages_spoken, str):
                try:
                    languages = json.loads(staff.languages_spoken)
                except:
                    languages = [staff.languages_spoken]
            else:
                languages = staff.languages_spoken

        return StaffFullProfile(
            id=staff.id,
            user_id=staff.user_id,
            employee_id=staff.employee_id,
            name=staff.name,
            email=staff.email,
            personal_email=staff.personal_email,
            phone=staff.phone,
            role=staff.role,
            department=staff.department or 'general',
            specialty=staff.specialty,
            status=staff.status or 'active',
            shift=staff.shift,
            shift_start=staff.shift_start.strftime("%H:%M") if staff.shift_start else None,
            shift_end=staff.shift_end.strftime("%H:%M") if staff.shift_end else None,
            clocked_in=staff.clocked_in or False,
            clock_in_time=staff.clock_in_time.isoformat() if staff.clock_in_time else None,
            supervisor_id=staff.supervisor_id,
            supervisor_name=supervisor_name,
            floor_assignment=floor_assignment,
            hire_date=str(staff.hire_date) if staff.hire_date else str(date.today()),
            emergency_contact_name=staff.emergency_contact_name,
            emergency_contact_phone=staff.emergency_contact_phone,
            emergency_contact_relationship=staff.emergency_contact_relationship,
            address=staff.address,
            salary=staff.salary,
            hourly_rate=staff.hourly_rate,
            avatar=staff.avatar,
            performance_rating=staff.performance_rating,
            certifications=certifications,
            skills=staff.skills if isinstance(staff.skills, list) else None,
            languages_spoken=languages,
            schedule=None,
            attendance_stats=None
        )

    # Fallback: Build profile from User table
    return StaffFullProfile(
        id=current_user.id,
        user_id=current_user.id,
        employee_id=None,
        name=current_user.full_name or current_user.email,
        email=current_user.email,
        phone=current_user.phone,
        role=current_user.role,
        department='general',
        specialty=None,
        status='active' if current_user.is_active else 'inactive',
        shift=None,
        shift_start=None,
        shift_end=None,
        clocked_in=False,
        clock_in_time=None,
        supervisor_id=None,
        supervisor_name=None,
        floor_assignment=None,
        hire_date=str(date.today()),
        emergency_contact_name=None,
        emergency_contact_phone=None,
        emergency_contact_relationship=None,
        address=None,
        salary=None,
        hourly_rate=None,
        avatar=current_user.avatar,
        performance_rating=None,
        certifications=None,
        skills=None,
        languages_spoken=None,
        schedule=None,
        attendance_stats=None
    )


@router.get("", response_model=List[StaffRead])
async def list_staff(
    role: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List staff members with filters"""
    check_access(current_user, ["admin", "manager", "front_desk"], detail="Access denied")

    # First try to get from Staff table
    query = select(Staff)

    if role:
        query = query.where(Staff.role == role)
    if department:
        query = query.where(Staff.department == department)
    if status:
        query = query.where(Staff.status == status)
    if search:
        query = query.where(
            or_(
                Staff.name.ilike(f"%{search}%"),
                Staff.email.ilike(f"%{search}%"),
                Staff.employee_id.ilike(f"%{search}%")
            )
        )

    result = await session.exec(query.order_by(Staff.name))
    staff_list = result.all()

    if staff_list:
        return [staff_to_read(s) for s in staff_list]

    # Fallback: Get from Users table if no Staff records
    user_query = select(User).where(User.role != "guest")

    if role:
        user_query = user_query.where(User.role == role)
    if status:
        if status == "active":
            user_query = user_query.where(User.is_active == True)
        elif status in ["inactive", "off-duty"]:
            user_query = user_query.where(User.is_active == False)
    if search:
        user_query = user_query.where(
            or_(
                User.full_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
        )

    result = await session.exec(user_query.order_by(User.full_name))
    users = result.all()

    return [user_to_staff_read(u) for u in users]


@router.get("/available")
async def get_available_staff(
    department: Optional[str] = Query(None),
    shift_type: Optional[str] = Query(None),
    target_date: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get list of available staff for a specific date/shift"""
    check_access(current_user, ["admin", "manager", "front_desk"])

    # Direct query for available staff
    query = select(Staff).where(Staff.status == "active")

    if department:
        query = query.where(Staff.department == department)

    result = await session.exec(query)
    staff_list = result.all()

    # Build available staff list
    available_staff = []
    for staff in staff_list:
        available_staff.append({
            "id": staff.id,
            "name": staff.name,
            "role": staff.role,
            "department": staff.department,
            "clocked_in": staff.clocked_in or False,
            "current_tasks": 0,
        })

    return {
        "department": department,
        "shift_type": shift_type,
        "date": target_date or date.today().isoformat(),
        "available_count": len(available_staff),
        "staff": available_staff
    }


@router.get("/{staff_id:int}", response_model=StaffFullProfile)
async def get_staff(
    staff_id: int = Path(..., gt=0, description="Staff ID must be a positive integer"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get full staff profile by ID"""
    # Allow staff to view their own profile
    is_own_profile = False

    # First try Staff table
    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if staff:
        if staff.user_id == current_user.id:
            is_own_profile = True
    else:
        # Try User table with ID
        user = await session.get(User, staff_id)
        if user:
            if user.id == current_user.id:
                is_own_profile = True
            # Create staff record
            staff = await get_or_create_staff_record(session, user)

    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    if not is_own_profile:
        check_access(current_user, ["admin", "manager", "front_desk"])

    # Get schedule for the next 7 days
    today = date.today()
    schedule_result = await session.exec(
        select(StaffSchedule)
        .where(and_(
            StaffSchedule.staff_id == staff.id,
            StaffSchedule.schedule_date >= today
        ))
        .order_by(StaffSchedule.schedule_date)
        .limit(7)
    )
    schedules = schedule_result.all()

    schedule_list = [
        {
            "date": s.schedule_date.isoformat(),
            "shift_type": s.shift_type,
            "start_time": s.start_time.strftime("%H:%M") if s.start_time else None,
            "end_time": s.end_time.strftime("%H:%M") if s.end_time else None,
            "status": s.status,
        }
        for s in schedules
    ]

    # Get attendance stats for this month
    first_of_month = today.replace(day=1)
    attendance_result = await session.exec(
        select(StaffAttendance)
        .where(and_(
            StaffAttendance.staff_id == staff.id,
            StaffAttendance.date >= first_of_month
        ))
    )
    all_attendances = attendance_result.all()

    # Deduplicate: one record per date
    deduped_att: dict = {}
    for a in all_attendances:
        if a.date not in deduped_att:
            deduped_att[a.date] = a
        else:
            kept = deduped_att[a.date]
            if a.total_hours_worked:
                kept.total_hours_worked = (kept.total_hours_worked or 0) + a.total_hours_worked
            if a.overtime_hours:
                kept.overtime_hours = (kept.overtime_hours or 0) + a.overtime_hours
    attendances = list(deduped_att.values())

    attendance_stats = {
        "days_present": sum(1 for a in attendances if a.status == "present"),
        "days_absent": sum(1 for a in attendances if a.status == "absent"),
        "days_late": sum(1 for a in attendances if a.status == "late"),
        "total_hours": sum(a.total_hours_worked or 0 for a in attendances),
        "overtime_hours": sum(a.overtime_hours or 0 for a in attendances),
    }

    # Parse JSON fields
    certifications = None
    skills = None
    languages = None
    floors = None

    if staff.certifications:
        try:
            certifications = json.loads(staff.certifications) if isinstance(staff.certifications, str) else staff.certifications
        except:
            certifications = None

    if staff.skills:
        try:
            skills = json.loads(staff.skills) if isinstance(staff.skills, str) else staff.skills
        except:
            skills = None

    if staff.languages_spoken:
        try:
            languages = json.loads(staff.languages_spoken) if isinstance(staff.languages_spoken, str) else staff.languages_spoken
        except:
            languages = None

    if staff.floor_assignment:
        try:
            floors = json.loads(staff.floor_assignment) if isinstance(staff.floor_assignment, str) else staff.floor_assignment
            # Ensure all floor values are strings
            if floors and isinstance(floors, list):
                floors = [str(f) for f in floors]
        except:
            floors = None

    return StaffFullProfile(
        id=staff.id,
        user_id=staff.user_id,
        employee_id=staff.employee_id,
        name=staff.name,
        email=staff.email,
        personal_email=staff.personal_email,
        phone=staff.phone,
        role=staff.role,
        department=staff.department,
        specialty=staff.specialty,
        status=staff.status,
        shift=staff.shift,
        shift_start=staff.shift_start.strftime("%H:%M") if staff.shift_start else None,
        shift_end=staff.shift_end.strftime("%H:%M") if staff.shift_end else None,
        clocked_in=staff.clocked_in or False,
        clock_in_time=staff.clock_in_time.isoformat() if staff.clock_in_time else None,
        supervisor_id=staff.supervisor_id,
        supervisor_name=staff.supervisor_name,
        floor_assignment=floors,
        hire_date=staff.hire_date.isoformat() if staff.hire_date else None,
        emergency_contact_name=staff.emergency_contact_name,
        emergency_contact_phone=staff.emergency_contact_phone,
        emergency_contact_relationship=staff.emergency_contact_relationship,
        address=staff.address,
        salary=staff.salary,
        hourly_rate=staff.hourly_rate,
        avatar=staff.avatar,
        performance_rating=staff.performance_rating,
        certifications=certifications,
        skills=skills,
        languages_spoken=languages,
        schedule=schedule_list,
        attendance_stats=attendance_stats,
    )


@router.post("", response_model=StaffCreateResponse, status_code=201)
async def create_staff(
    payload: StaffCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new staff member with RBAC permissions and onboarding flow"""
    check_access(current_user, ["admin", "manager"], detail="Admin or manager access required")

    # Validate role
    if payload.role not in VALID_STAFF_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{payload.role}'. Must be one of: {', '.join(sorted(VALID_STAFF_ROLES))}"
        )

    # Check if user with email already exists
    existing = (await session.exec(
        select(User).where(User.email == payload.email.lower().strip())
    )).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    # Auto-generate temp password if not provided
    import secrets
    import string
    temp_password = payload.password
    is_temp_password = False
    if not temp_password:
        # Generate secure 14-char password: letters + digits + punctuation
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        temp_password = ''.join(secrets.choice(alphabet) for _ in range(14))
        is_temp_password = True

    # Auto-derive department from role if not provided
    department = payload.department or ROLE_DEPARTMENT_MAP.get(payload.role, "general")

    # Serialize permissions to JSON if provided
    permissions_json = None
    if payload.permissions:
        permissions_json = json.dumps(payload.permissions)

    # Create new user with onboarding flags
    from datetime import timedelta
    new_user = User(
        email=payload.email.lower().strip(),
        full_name=payload.full_name,
        phone=payload.phone,
        hashed_password=get_password_hash(temp_password),
        is_active=True,
        is_superuser=(payload.role == "admin"),
        role=payload.role,
        must_reset_password=is_temp_password,
        first_login=True,
        temp_password_expires_at=datetime.utcnow() + timedelta(hours=72) if is_temp_password else None,
        permissions=permissions_json,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    # Create staff record
    new_staff = Staff(
        user_id=new_user.id,
        name=payload.full_name,
        email=new_user.email,
        personal_email=payload.personal_email,
        phone=payload.phone,
        role=payload.role,
        department=department,
        specialty=payload.specialty,
        shift=payload.shift,
        hourly_rate=payload.hourly_rate,
        status="active",
        hire_date=date.today(),
    )
    session.add(new_staff)
    await session.commit()
    await session.refresh(new_staff)

    # Persist permissions to RBAC tables
    if payload.permissions:
        try:
            from app.models.rbac import Role, Permission, RolePermission, UserRole
            # Find or create the RBAC role
            rbac_role = (await session.exec(
                select(Role).where(Role.role_code == payload.role)
            )).first()
            if not rbac_role:
                from app.core.roles import ROLE_LABELS
                rbac_role = Role(
                    role_code=payload.role,
                    role_name=ROLE_LABELS.get(payload.role, payload.role.replace("_", " ").title()),
                    is_system_role=True,
                    is_active=True,
                )
                session.add(rbac_role)
                await session.commit()
                await session.refresh(rbac_role)

            # Link user to role
            user_role = UserRole(
                user_id=new_user.id,
                role_id=rbac_role.id,
                assigned_by=current_user.id,
                assigned_at=datetime.utcnow(),
            )
            session.add(user_role)

            # Create permission entries for each module
            for module_code, perms in payload.permissions.items():
                # Find or create the permission record
                perm = (await session.exec(
                    select(Permission).where(Permission.permission_code == module_code)
                )).first()
                if not perm:
                    perm = Permission(
                        permission_code=module_code,
                        permission_name=module_code.replace("_", " ").title(),
                        module="core",
                        is_active=True,
                    )
                    session.add(perm)
                    await session.commit()
                    await session.refresh(perm)

                # Create role-permission mapping
                role_perm = RolePermission(
                    role_id=rbac_role.id,
                    permission_id=perm.id,
                    can_view=perms.get("view", False),
                    can_create=perms.get("edit", False),
                    can_edit=perms.get("edit", False),
                    can_delete=perms.get("delete", False),
                )
                session.add(role_perm)

            await session.commit()
        except Exception as e:
            import logging
            logging.error(f"Failed to persist RBAC permissions: {e}")

    # Send welcome email in background - doesn't block response
    credential_email_target = payload.personal_email or new_staff.email
    email_sent = True  # Optimistic - background task will log on failure
    from app.services.background_email import send_staff_welcome_email_bg
    background_tasks.add_task(
        send_staff_welcome_email_bg,
        to_email=credential_email_target,
        staff_name=new_staff.name,
        role=new_staff.role,
        department=department,
        password=temp_password,
        work_email=new_staff.email,
    )

    # Return the temp password so the admin can share it manually if email fails
    base = staff_to_read(new_staff)
    return StaffCreateResponse(
        **base.model_dump(),
        temp_password=temp_password if is_temp_password else None,
        must_reset_password=is_temp_password,
        email_sent=bool(email_sent),
    )


@router.patch("/{staff_id:int}", response_model=StaffRead)
async def update_staff(
    staff_id: int,
    payload: StaffUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update staff member"""
    check_access(current_user, ["admin", "manager"], detail="Admin or manager access required")

    # Try Staff table first
    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if not staff:
        # Try User table and create staff record
        user = await session.get(User, staff_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found")
        staff = await get_or_create_staff_record(session, user)

    # Update fields
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "full_name":
            staff.name = value
        elif key == "floor_assignment":
            staff.floor_assignment = json.dumps(value) if value else None
        elif key == "skills":
            staff.skills = json.dumps(value) if value else None
        elif key == "languages_spoken":
            staff.languages_spoken = json.dumps(value) if value else None
        elif key == "is_active":
            staff.status = "active" if value else "inactive"
        elif hasattr(staff, key):
            setattr(staff, key, value)

    staff.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(staff)

    # Also update User record if exists
    if staff.user_id:
        user = await session.get(User, staff.user_id)
        if user:
            if payload.full_name:
                user.full_name = payload.full_name
            if payload.phone:
                user.phone = payload.phone
            if payload.role:
                user.role = payload.role
            if payload.is_active is not None:
                user.is_active = payload.is_active
            await session.commit()

    return staff_to_read(staff)


@router.delete("/{staff_id:int}")
async def delete_staff(
    staff_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Soft delete (disable) staff member"""
    check_access(current_user, ["admin", "manager"], detail="Admin or manager access required")

    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if staff:
        staff.status = "disabled"
        staff.updated_at = datetime.utcnow()

        # Also disable user account
        if staff.user_id:
            user = await session.get(User, staff.user_id)
            if user:
                user.is_active = False
        await session.commit()
        return {"message": "Staff member disabled", "id": staff_id}

    # Try User table
    user = await session.get(User, staff_id)
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")

    user.is_active = False
    await session.commit()
    return {"message": "Staff member disabled", "id": staff_id}


@router.post("/{staff_id:int}/assign-shift")
async def assign_shift(
    staff_id: int,
    payload: ShiftAssignment,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Assign a shift to staff member"""
    allowed_roles = ["admin", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get staff
    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if not staff:
        user = await session.get(User, staff_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found")
        staff = await get_or_create_staff_record(session, user)

    # Parse dates and times
    try:
        schedule_date = date.fromisoformat(payload.schedule_date)
        start_time = time.fromisoformat(payload.start_time)
        end_time = time.fromisoformat(payload.end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date/time format: {e}")

    # Check for existing schedule on that date
    existing = (await session.exec(
        select(StaffSchedule).where(and_(
            StaffSchedule.staff_id == staff.id,
            StaffSchedule.schedule_date == schedule_date
        ))
    )).first()

    if existing:
        # Update existing
        existing.shift_type = payload.shift_type
        existing.start_time = start_time
        existing.end_time = end_time
        existing.department = payload.department or staff.department
        existing.location = payload.location
        existing.notes = payload.notes
        existing.updated_at = datetime.utcnow()
        await session.commit()
        schedule_id = existing.id
    else:
        # Create new
        schedule = StaffSchedule(
            staff_id=staff.id,
            schedule_date=schedule_date,
            shift_type=payload.shift_type,
            start_time=start_time,
            end_time=end_time,
            department=payload.department or staff.department,
            location=payload.location,
            notes=payload.notes,
            created_by=current_user.id,
        )
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)
        schedule_id = schedule.id

    # Send notification email in background
    from app.services.background_email import send_shift_assignment_email_bg
    background_tasks.add_task(
        send_shift_assignment_email_bg,
        to_email=staff.email,
        staff_name=staff.name,
        shift_date=payload.schedule_date,
        shift_type=payload.shift_type,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )

    return {
        "message": "Shift assigned successfully",
        "schedule_id": schedule_id,
        "staff_id": staff.id,
        "date": payload.schedule_date,
        "shift": payload.shift_type,
    }


@router.post("/{staff_id:int}/clock")
async def clock_in_out(
    staff_id: int,
    payload: AttendanceRecord,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Clock in or clock out"""
    # Staff can clock themselves, or admin/manager can do it
    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if not staff:
        user = await session.get(User, staff_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found")
        staff = await get_or_create_staff_record(session, user)

    # Check permission
    is_own = staff.user_id == current_user.id
    is_admin = current_user.role in ["admin", "manager"] or current_user.is_superuser
    if not is_own and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    now = datetime.utcnow()
    today = now.date()

    if payload.action == "clock_in":
        if staff.clocked_in:
            raise HTTPException(status_code=400, detail="Already clocked in")

        staff.clocked_in = True
        staff.clock_in_time = now

        # Check for existing attendance record today
        existing = (await session.exec(
            select(StaffAttendance).where(and_(
                StaffAttendance.staff_id == staff.id,
                StaffAttendance.date == today,
            )).order_by(StaffAttendance.id.asc())
        )).first()

        if existing:
            # Reopen existing record — preserve original clock-in, clear clock-out
            existing.actual_clock_out = None
            existing.early_leave_minutes = 0
            # Only reset status if it was early_leave (preserve "late" from original clock-in)
            if existing.status == "early_leave":
                existing.status = "present"
            existing.updated_at = now
            if payload.location:
                existing.clock_in_location = payload.location
            if payload.notes:
                existing.notes = f"{existing.notes or ''}\n{payload.notes}".strip()
        else:
            # First clock-in of the day — create new record
            attendance = StaffAttendance(
                staff_id=staff.id,
                date=today,
                shift_type=staff.shift,
                scheduled_start=staff.shift_start or time(9, 0),
                scheduled_end=staff.shift_end or time(17, 0),
                actual_clock_in=now,
                status="present",
                clock_in_location=payload.location,
                notes=payload.notes,
            )
            # Check if late
            if staff.shift_start:
                scheduled = datetime.combine(today, staff.shift_start)
                if now > scheduled:
                    late_minutes = int((now - scheduled).total_seconds() / 60)
                    attendance.late_minutes = late_minutes
                    attendance.status = "late"
            session.add(attendance)

        await session.commit()

        return {"message": "Clocked in successfully", "time": now.isoformat()}

    elif payload.action == "clock_out":
        if not staff.clocked_in:
            raise HTTPException(status_code=400, detail="Not clocked in")

        staff.clocked_in = False
        clock_in_time = staff.clock_in_time
        staff.clock_in_time = None

        # Update attendance record
        attendance = (await session.exec(
            select(StaffAttendance).where(and_(
                StaffAttendance.staff_id == staff.id,
                StaffAttendance.date == today,
                StaffAttendance.actual_clock_out == None
            ))
        )).first()

        if attendance:
            attendance.actual_clock_out = now
            attendance.clock_out_location = payload.location

            if clock_in_time:
                session_hours = (now - clock_in_time).total_seconds() / 3600
                previous_hours = attendance.total_hours_worked or 0
                attendance.total_hours_worked = round(previous_hours + session_hours, 2)

                # Calculate overtime (assuming 8 hour shift)
                total = attendance.total_hours_worked
                if total > 8:
                    attendance.overtime_hours = round(total - 8, 2)
                    attendance.is_overtime = True

            # Check for early leave
            if staff.shift_end:
                scheduled_end = datetime.combine(today, staff.shift_end)
                if now < scheduled_end:
                    early_minutes = int((scheduled_end - now).total_seconds() / 60)
                    if early_minutes > 5:  # 5-minute grace period
                        attendance.early_leave_minutes = early_minutes
                        # Only change status if not already marked as late
                        if attendance.status not in ("late",):
                            attendance.status = "early_leave"

            if payload.notes:
                attendance.notes = f"{attendance.notes or ''}\n{payload.notes}".strip()

        await session.commit()

        return {"message": "Clocked out successfully", "time": now.isoformat()}

    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'clock_in' or 'clock_out'")


@router.post("/{staff_id:int}/leave")
async def request_leave(
    staff_id: int,
    payload: LeaveRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Submit leave request"""
    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if not staff:
        user = await session.get(User, staff_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found")
        staff = await get_or_create_staff_record(session, user)

    # Check permission (staff can request their own leave)
    is_own = staff.user_id == current_user.id
    is_admin = current_user.role in ["admin", "manager"] or current_user.is_superuser
    if not is_own and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        start = date.fromisoformat(payload.start_date)
        end = date.fromisoformat(payload.end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    if end < start:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    total_days = (end - start).days + 1

    leave = StaffLeave(
        staff_id=staff.id,
        leave_type=payload.leave_type,
        start_date=start,
        end_date=end,
        total_days=total_days,
        reason=payload.reason,
        status="pending",
    )
    session.add(leave)
    await session.commit()
    await session.refresh(leave)

    # Notify admins about the leave request
    try:
        await notify_staff_leave_request(
            session=session,
            staff_name=staff.name,
            leave_type=payload.leave_type,
            start_date=payload.start_date,
            end_date=payload.end_date,
            staff_id=staff.id
        )
        await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to send leave request notification: {str(e)}")

    return {
        "message": "Leave request submitted",
        "leave_id": leave.id,
        "status": "pending",
        "total_days": total_days,
    }


@router.patch("/{staff_id:int}/leave/{leave_id:int}")
async def update_leave_status(
    staff_id: int,
    leave_id: int,
    background_tasks: BackgroundTasks,
    action: str = Query(..., description="approve or reject"),
    rejection_reason: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Approve or reject leave request"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    leave = await session.get(StaffLeave, leave_id)
    if not leave or leave.staff_id != staff_id:
        raise HTTPException(status_code=404, detail="Leave request not found")

    if action == "approve":
        leave.status = "approved"
        leave.approved_by = current_user.id
        leave.approved_at = datetime.utcnow()

        # Update staff status to on_leave during leave period
        staff = await session.get(Staff, staff_id)
        if staff:
            today = date.today()
            if leave.start_date <= today <= leave.end_date:
                staff.status = "on_leave"

    elif action == "reject":
        leave.status = "rejected"
        leave.rejection_reason = rejection_reason
    else:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    leave.updated_at = datetime.utcnow()
    await session.commit()

    # Send notification email in background
    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()
    if staff:
        from app.services.background_email import send_leave_status_email_bg
        background_tasks.add_task(
            send_leave_status_email_bg,
            to_email=staff.email,
            staff_name=staff.name,
            leave_type=leave.leave_type,
            start_date=leave.start_date.isoformat(),
            end_date=leave.end_date.isoformat(),
            status=leave.status,
            rejection_reason=rejection_reason,
        )

    return {
        "message": f"Leave request {leave.status}",
        "leave_id": leave_id,
        "status": leave.status,
    }


@router.get("/{staff_id:int}/schedule")
async def get_staff_schedule(
    staff_id: int,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get staff schedule"""
    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if not staff:
        user = await session.get(User, staff_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found")
        staff = await get_or_create_staff_record(session, user)

    # Check permission
    is_own = staff.user_id == current_user.id
    is_admin = current_user.role in ["admin", "manager", "front_desk"] or current_user.is_superuser
    if not is_own and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    query = select(StaffSchedule).where(StaffSchedule.staff_id == staff.id)

    if start_date:
        query = query.where(StaffSchedule.schedule_date >= date.fromisoformat(start_date))
    if end_date:
        query = query.where(StaffSchedule.schedule_date <= date.fromisoformat(end_date))

    result = await session.exec(query.order_by(StaffSchedule.schedule_date))
    schedules = result.all()

    return [
        {
            "id": s.id,
            "date": s.schedule_date.isoformat(),
            "shift_type": s.shift_type,
            "start_time": s.start_time.strftime("%H:%M") if s.start_time else None,
            "end_time": s.end_time.strftime("%H:%M") if s.end_time else None,
            "department": s.department,
            "location": s.location,
            "status": s.status,
            "notes": s.notes,
        }
        for s in schedules
    ]


@router.get("/{staff_id:int}/tasks")
async def get_staff_tasks(
    staff_id: int,
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get tasks assigned to staff member"""
    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if not staff:
        user = await session.get(User, staff_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found")
        staff = await get_or_create_staff_record(session, user)

    # Check permission
    is_own = staff.user_id == current_user.id
    is_admin = current_user.role in ["admin", "manager", "front_desk"] or current_user.is_superuser
    if not is_own and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get housekeeping tasks
    query = select(HousekeepingTask).where(HousekeepingTask.assigned_to == staff.id)
    if status:
        query = query.where(HousekeepingTask.status == status)

    query = query.order_by(HousekeepingTask.created_at.desc())
    result = await session.exec(query)
    tasks = result.all()

    return [
        {
            "id": t.id,
            "room_id": t.room_id,
            "task_type": t.task_type,
            "status": t.status,
            "priority": t.priority,
            "scheduled_for": t.scheduled_for.isoformat() if t.scheduled_for else None,
            "estimated_duration": t.estimated_duration,
            "notes": t.notes,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tasks
    ]


@router.get("/{staff_id:int}/performance")
async def get_staff_performance(
    staff_id: int,
    period: str = Query("month", description="week, month, quarter, year"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get staff performance metrics"""
    allowed_roles = ["admin", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    # Calculate date range
    today = date.today()
    if period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=month, day=1)
    else:  # year
        start = today.replace(month=1, day=1)

    # Get performance metrics
    metrics_result = await session.exec(
        select(StaffPerformanceMetrics)
        .where(and_(
            StaffPerformanceMetrics.staff_id == staff.id,
            StaffPerformanceMetrics.date >= start
        ))
    )
    metrics = metrics_result.all()

    if not metrics:
        return {
            "staff_id": staff_id,
            "period": period,
            "tasks_completed": 0,
            "tasks_assigned": 0,
            "completion_rate": 0,
            "avg_completion_time": 0,
            "quality_score": 0,
            "efficiency_score": 0,
        }

    total_assigned = sum(m.tasks_assigned for m in metrics)
    total_completed = sum(m.tasks_completed for m in metrics)
    avg_completion_time = sum(m.avg_completion_time or 0 for m in metrics) / len(metrics) if metrics else 0
    avg_quality = sum(m.quality_score or 0 for m in metrics) / len(metrics) if metrics else 0
    avg_efficiency = sum(m.efficiency_score or 0 for m in metrics) / len(metrics) if metrics else 0

    return {
        "staff_id": staff_id,
        "staff_name": staff.name,
        "period": period,
        "tasks_assigned": total_assigned,
        "tasks_completed": total_completed,
        "completion_rate": round(total_completed / total_assigned * 100, 1) if total_assigned > 0 else 0,
        "avg_completion_time": round(avg_completion_time, 1),
        "quality_score": round(avg_quality, 2),
        "efficiency_score": round(avg_efficiency, 2),
        "performance_rating": staff.performance_rating,
    }


@router.post("/{staff_id:int}/message")
async def send_message_to_staff(
    staff_id: int,
    payload: MessageRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Send message/notification to staff member"""
    allowed_roles = ["admin", "manager", "front_desk"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await session.exec(select(Staff).where(Staff.id == staff_id))
    staff = result.first()

    if not staff:
        user = await session.get(User, staff_id)
        if not user:
            raise HTTPException(status_code=404, detail="Staff member not found")
        staff = await get_or_create_staff_record(session, user)

    # Send email notification in background - doesn't block response
    from app.services.background_email import send_staff_message_email_bg
    background_tasks.add_task(
        send_staff_message_email_bg,
        to_email=staff.email,
        staff_name=staff.name,
        subject=payload.subject,
        message=payload.message,
        priority=payload.priority,
        sender_name=current_user.full_name or current_user.email,
    )
    return {
        "message": "Message sent successfully",
        "recipient": staff.email,
        "subject": payload.subject,
    }


# Import timedelta for performance endpoint
from datetime import timedelta


# ============== ADVANCED SCHEDULING ENDPOINTS ==============

class BulkShiftAssignment(BaseModel):
    staff_ids: List[int]
    schedule_date: str
    shift_type: str
    start_time: str
    end_time: str
    department: Optional[str] = None
    notes: Optional[str] = None


class ShiftHandoverCreate(BaseModel):
    incoming_staff_id: int
    shift_type: str = "morning"  # morning, afternoon, night
    handover_notes: str
    arrivals_count: Optional[int] = 0
    departures_count: Optional[int] = 0
    in_house_count: Optional[int] = 0
    issues: Optional[str] = None


@router.post("/bulk-assign-shifts")
async def bulk_assign_shifts(
    payload: BulkShiftAssignment,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Assign the same shift to multiple staff members"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin/Manager access required")

    try:
        schedule_date = date.fromisoformat(payload.schedule_date)
        start_time = time.fromisoformat(payload.start_time)
        end_time = time.fromisoformat(payload.end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date/time format: {e}")

    results = []
    for staff_id in payload.staff_ids:
        staff = await session.get(Staff, staff_id)
        if not staff:
            results.append({"staff_id": staff_id, "success": False, "error": "Staff not found"})
            continue

        # Check for existing schedule
        existing = (await session.exec(
            select(StaffSchedule).where(and_(
                StaffSchedule.staff_id == staff_id,
                StaffSchedule.schedule_date == schedule_date
            ))
        )).first()

        if existing:
            existing.shift_type = payload.shift_type
            existing.start_time = start_time
            existing.end_time = end_time
            existing.department = payload.department or staff.department
            existing.notes = payload.notes
            existing.updated_at = datetime.utcnow()
        else:
            schedule = StaffSchedule(
                staff_id=staff_id,
                schedule_date=schedule_date,
                shift_type=payload.shift_type,
                start_time=start_time,
                end_time=end_time,
                department=payload.department or staff.department,
                notes=payload.notes,
                created_by=current_user.id,
            )
            session.add(schedule)

        results.append({"staff_id": staff_id, "success": True, "staff_name": staff.name})

    await session.commit()

    return {
        "message": f"Shifts assigned to {len([r for r in results if r.get('success')])} staff members",
        "date": payload.schedule_date,
        "shift": payload.shift_type,
        "results": results
    }


@router.get("/schedule/department/{department}")
async def get_department_schedule(
    department: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get schedule for all staff in a department"""
    if current_user.role not in ["admin", "manager", "front_desk"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get all staff in department
    staff_result = await session.exec(
        select(Staff).where(Staff.department == department)
    )
    department_staff = staff_result.all()

    if not department_staff:
        return {"department": department, "staff": [], "schedules": []}

    staff_ids = [s.id for s in department_staff]

    # Get schedules
    query = select(StaffSchedule).where(StaffSchedule.staff_id.in_(staff_ids))

    if start_date:
        query = query.where(StaffSchedule.schedule_date >= date.fromisoformat(start_date))
    else:
        query = query.where(StaffSchedule.schedule_date >= date.today())

    if end_date:
        query = query.where(StaffSchedule.schedule_date <= date.fromisoformat(end_date))

    schedule_result = await session.exec(query.order_by(StaffSchedule.schedule_date, StaffSchedule.staff_id))
    schedules = schedule_result.all()

    # Build staff lookup
    staff_lookup = {s.id: s for s in department_staff}

    return {
        "department": department,
        "staff": [
            {"id": s.id, "name": s.name, "role": s.role, "status": s.status}
            for s in department_staff
        ],
        "schedules": [
            {
                "id": sch.id,
                "staff_id": sch.staff_id,
                "staff_name": staff_lookup.get(sch.staff_id, {}).name if staff_lookup.get(sch.staff_id) else "Unknown",
                "date": sch.schedule_date.isoformat(),
                "shift_type": sch.shift_type,
                "start_time": sch.start_time.strftime("%H:%M") if sch.start_time else None,
                "end_time": sch.end_time.strftime("%H:%M") if sch.end_time else None,
                "status": sch.status,
            }
            for sch in schedules
        ]
    }


@router.post("/{staff_id:int}/handover")
async def create_shift_handover(
    staff_id: int,
    payload: ShiftHandoverCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create shift handover from current staff to incoming staff"""
    from app.models.operations import ShiftHandover as HandoverModel

    # Verify outgoing staff
    outgoing_staff = await session.get(Staff, staff_id)
    if not outgoing_staff:
        raise HTTPException(status_code=404, detail="Outgoing staff not found")

    # Verify incoming staff
    incoming_staff = await session.get(Staff, payload.incoming_staff_id)
    if not incoming_staff:
        raise HTTPException(status_code=404, detail="Incoming staff not found")

    # Check permission
    is_own = outgoing_staff.user_id == current_user.id
    is_admin = current_user.role in ["admin", "manager"] or current_user.is_superuser
    if not is_own and not is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    now = datetime.utcnow()

    # Create handover using correct field names from ShiftHandover model
    handover = HandoverModel(
        shift_date=now.date(),
        shift_type=payload.shift_type,
        handed_over_by=current_user.id,  # User ID of outgoing staff
        handed_over_to=incoming_staff.user_id if incoming_staff.user_id else payload.incoming_staff_id,  # User ID of incoming staff
        handover_time=now,
        arrivals_count=payload.arrivals_count or 0,
        departures_count=payload.departures_count or 0,
        in_house_count=payload.in_house_count or 0,
        issues=payload.issues,
        notes=payload.handover_notes,
    )
    session.add(handover)
    await session.commit()
    await session.refresh(handover)

    # Create notification for incoming staff
    try:
        from app.models.guest_chat import StaffNotification
        notification = StaffNotification(
            staff_id=incoming_staff.user_id if incoming_staff.user_id else payload.incoming_staff_id,
            notification_type="shift_handover",
            title=f"Shift Handover from {outgoing_staff.name}",
            message=f"Please review handover notes for {payload.shift_type} shift.",
            is_read=False,
            created_at=now
        )
        session.add(notification)
        await session.commit()
    except Exception as e:
        import logging
        logging.warning(f"Failed to create handover notification: {e}")

    return {
        "message": "Shift handover created successfully",
        "handover_id": handover.id,
        "outgoing_staff": outgoing_staff.name,
        "incoming_staff": incoming_staff.name,
        "shift_type": payload.shift_type,
        "handover_time": now.isoformat()
    }


@router.get("/workload/summary")
async def get_staff_workload_summary(
    department: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get workload summary for all staff (for scheduling optimization)"""
    if current_user.role not in ["admin", "manager", "front_desk"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    from app.services.staff_scheduling_service import get_scheduling_service

    scheduling_service = get_scheduling_service(session)
    workload = await scheduling_service.get_staff_workload_summary(department=department)

    # Calculate department stats
    total_staff = len(workload)
    available_count = len([s for s in workload if s.get("availability") == "available"])
    avg_workload = sum(s.get("workload_score", 0) for s in workload) / total_staff if total_staff > 0 else 0

    return {
        "department": department or "all",
        "total_staff": total_staff,
        "available_count": available_count,
        "busy_count": total_staff - available_count,
        "average_workload_score": round(avg_workload, 2),
        "staff": workload
    }


# ============== PERFORMANCE ANALYTICS ENDPOINTS ==============

@router.get("/analytics/department/{department}")
async def get_department_performance_analytics(
    department: str,
    period: str = Query("month", description="week, month, quarter, year"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get comprehensive performance analytics for a department"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    # Calculate date range
    today = date.today()
    if period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=month, day=1)
    else:  # year
        start = today.replace(month=1, day=1)

    # Get all staff in department
    staff_result = await session.exec(
        select(Staff).where(Staff.department == department)
    )
    department_staff = staff_result.all()
    staff_ids = [s.id for s in department_staff]

    if not staff_ids:
        return {"department": department, "period": period, "error": "No staff found in department"}

    # Get performance metrics for all staff
    metrics_result = await session.exec(
        select(StaffPerformanceMetrics)
        .where(and_(
            StaffPerformanceMetrics.staff_id.in_(staff_ids),
            StaffPerformanceMetrics.date >= start
        ))
    )
    all_metrics = metrics_result.all()

    # Aggregate metrics
    total_tasks_assigned = sum(m.tasks_assigned for m in all_metrics)
    total_tasks_completed = sum(m.tasks_completed for m in all_metrics)
    avg_completion_time = sum(m.avg_completion_time or 0 for m in all_metrics) / len(all_metrics) if all_metrics else 0
    avg_quality = sum(m.quality_score or 0 for m in all_metrics) / len(all_metrics) if all_metrics else 0
    avg_efficiency = sum(m.efficiency_score or 0 for m in all_metrics) / len(all_metrics) if all_metrics else 0

    # Per-staff breakdown
    staff_breakdown = {}
    for staff in department_staff:
        staff_metrics = [m for m in all_metrics if m.staff_id == staff.id]
        if staff_metrics:
            staff_breakdown[staff.id] = {
                "name": staff.name,
                "tasks_assigned": sum(m.tasks_assigned for m in staff_metrics),
                "tasks_completed": sum(m.tasks_completed for m in staff_metrics),
                "avg_quality": round(sum(m.quality_score or 0 for m in staff_metrics) / len(staff_metrics), 2),
                "avg_efficiency": round(sum(m.efficiency_score or 0 for m in staff_metrics) / len(staff_metrics), 2),
            }

    # Get attendance stats
    attendance_result = await session.exec(
        select(StaffAttendance)
        .where(and_(
            StaffAttendance.staff_id.in_(staff_ids),
            StaffAttendance.date >= start
        ))
    )
    raw_attendances = attendance_result.all()

    # Deduplicate: one record per (staff_id, date)
    deduped_team: dict[tuple, any] = {}
    for a in raw_attendances:
        key = (a.staff_id, a.date)
        if key not in deduped_team:
            deduped_team[key] = a
        else:
            kept = deduped_team[key]
            if a.total_hours_worked:
                kept.total_hours_worked = (kept.total_hours_worked or 0) + a.total_hours_worked
            if a.overtime_hours:
                kept.overtime_hours = (kept.overtime_hours or 0) + a.overtime_hours
    attendances = list(deduped_team.values())

    attendance_stats = {
        "total_days_present": sum(1 for a in attendances if a.status == "present"),
        "total_days_late": sum(1 for a in attendances if a.status == "late"),
        "total_days_absent": sum(1 for a in attendances if a.status == "absent"),
        "total_hours_worked": round(sum(a.total_hours_worked or 0 for a in attendances), 1),
        "total_overtime_hours": round(sum(a.overtime_hours or 0 for a in attendances), 1),
    }

    return {
        "department": department,
        "period": period,
        "date_range": {"start": start.isoformat(), "end": today.isoformat()},
        "staff_count": len(department_staff),
        "performance_summary": {
            "total_tasks_assigned": total_tasks_assigned,
            "total_tasks_completed": total_tasks_completed,
            "completion_rate": round(total_tasks_completed / total_tasks_assigned * 100, 1) if total_tasks_assigned > 0 else 0,
            "avg_completion_time_minutes": round(avg_completion_time, 1),
            "avg_quality_score": round(avg_quality, 2),
            "avg_efficiency_score": round(avg_efficiency, 2),
        },
        "attendance_summary": attendance_stats,
        "staff_breakdown": list(staff_breakdown.values()),
    }


@router.get("/analytics/trends")
async def get_performance_trends(
    department: Optional[str] = Query(None),
    staff_id: Optional[int] = Query(None),
    days: int = Query(30, description="Number of days to analyze"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get performance trends over time (daily data points)"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    start = date.today() - timedelta(days=days)

    # Build query
    query = select(StaffPerformanceMetrics).where(StaffPerformanceMetrics.date >= start)

    if staff_id:
        query = query.where(StaffPerformanceMetrics.staff_id == staff_id)
    elif department:
        # Get staff IDs in department
        staff_result = await session.exec(
            select(Staff.id).where(Staff.department == department)
        )
        staff_ids = [s for s in staff_result.all()]
        if staff_ids:
            query = query.where(StaffPerformanceMetrics.staff_id.in_(staff_ids))

    query = query.order_by(StaffPerformanceMetrics.date)
    metrics_result = await session.exec(query)
    all_metrics = metrics_result.all()

    # Group by date
    daily_data = {}
    for m in all_metrics:
        date_key = m.date.isoformat()
        if date_key not in daily_data:
            daily_data[date_key] = {
                "date": date_key,
                "tasks_assigned": 0,
                "tasks_completed": 0,
                "quality_scores": [],
                "efficiency_scores": [],
                "completion_times": [],
            }
        daily_data[date_key]["tasks_assigned"] += m.tasks_assigned
        daily_data[date_key]["tasks_completed"] += m.tasks_completed
        if m.quality_score:
            daily_data[date_key]["quality_scores"].append(m.quality_score)
        if m.efficiency_score:
            daily_data[date_key]["efficiency_scores"].append(m.efficiency_score)
        if m.avg_completion_time:
            daily_data[date_key]["completion_times"].append(m.avg_completion_time)

    # Calculate averages for each day
    trends = []
    for date_key, data in sorted(daily_data.items()):
        trends.append({
            "date": data["date"],
            "tasks_assigned": data["tasks_assigned"],
            "tasks_completed": data["tasks_completed"],
            "completion_rate": round(data["tasks_completed"] / data["tasks_assigned"] * 100, 1) if data["tasks_assigned"] > 0 else 0,
            "avg_quality": round(sum(data["quality_scores"]) / len(data["quality_scores"]), 2) if data["quality_scores"] else 0,
            "avg_efficiency": round(sum(data["efficiency_scores"]) / len(data["efficiency_scores"]), 2) if data["efficiency_scores"] else 0,
            "avg_completion_time": round(sum(data["completion_times"]) / len(data["completion_times"]), 1) if data["completion_times"] else 0,
        })

    return {
        "department": department,
        "staff_id": staff_id,
        "days": days,
        "data_points": len(trends),
        "trends": trends
    }


@router.get("/analytics/leaderboard")
async def get_performance_leaderboard(
    department: Optional[str] = Query(None),
    metric: str = Query("efficiency", description="efficiency, quality, completion_rate, tasks_completed"),
    period: str = Query("month", description="week, month, quarter, year"),
    limit: int = Query(10, description="Number of top performers to return"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get performance leaderboard ranking staff by chosen metric"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    # Calculate date range
    today = date.today()
    if period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=month, day=1)
    else:  # year
        start = today.replace(month=1, day=1)

    # Get staff
    staff_query = select(Staff).where(Staff.status == "active")
    if department:
        staff_query = staff_query.where(Staff.department == department)

    staff_result = await session.exec(staff_query)
    all_staff = staff_result.all()
    staff_ids = [s.id for s in all_staff]
    staff_lookup = {s.id: s for s in all_staff}

    # Get metrics
    metrics_result = await session.exec(
        select(StaffPerformanceMetrics)
        .where(and_(
            StaffPerformanceMetrics.staff_id.in_(staff_ids),
            StaffPerformanceMetrics.date >= start
        ))
    )
    all_metrics = metrics_result.all()

    # Calculate aggregated metrics per staff
    staff_scores = {}
    for staff_id in staff_ids:
        staff_metrics = [m for m in all_metrics if m.staff_id == staff_id]
        if staff_metrics:
            total_assigned = sum(m.tasks_assigned for m in staff_metrics)
            total_completed = sum(m.tasks_completed for m in staff_metrics)
            avg_quality = sum(m.quality_score or 0 for m in staff_metrics) / len(staff_metrics)
            avg_efficiency = sum(m.efficiency_score or 0 for m in staff_metrics) / len(staff_metrics)
            completion_rate = (total_completed / total_assigned * 100) if total_assigned > 0 else 0

            staff_scores[staff_id] = {
                "staff_id": staff_id,
                "name": staff_lookup[staff_id].name,
                "department": staff_lookup[staff_id].department,
                "tasks_completed": total_completed,
                "tasks_assigned": total_assigned,
                "completion_rate": round(completion_rate, 1),
                "quality_score": round(avg_quality, 2),
                "efficiency_score": round(avg_efficiency, 2),
            }

    # Sort by selected metric
    metric_map = {
        "efficiency": "efficiency_score",
        "quality": "quality_score",
        "completion_rate": "completion_rate",
        "tasks_completed": "tasks_completed",
    }
    sort_key = metric_map.get(metric, "efficiency_score")

    ranked = sorted(staff_scores.values(), key=lambda x: x.get(sort_key, 0), reverse=True)

    # Add rank
    for i, entry in enumerate(ranked[:limit]):
        entry["rank"] = i + 1

    return {
        "department": department or "all",
        "metric": metric,
        "period": period,
        "total_staff": len(ranked),
        "leaderboard": ranked[:limit]
    }


@router.get("/analytics/compare")
async def compare_staff_performance(
    staff_ids: str = Query(..., description="Comma-separated staff IDs to compare"),
    period: str = Query("month", description="week, month, quarter, year"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Compare performance metrics between multiple staff members"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        ids = [int(id.strip()) for id in staff_ids.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid staff IDs format")

    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 staff members required for comparison")

    if len(ids) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 staff members can be compared at once")

    # Calculate date range
    today = date.today()
    if period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=month, day=1)
    else:  # year
        start = today.replace(month=1, day=1)

    # Get staff
    staff_result = await session.exec(
        select(Staff).where(Staff.id.in_(ids))
    )
    staff_list = staff_result.all()
    staff_lookup = {s.id: s for s in staff_list}

    # Get metrics
    metrics_result = await session.exec(
        select(StaffPerformanceMetrics)
        .where(and_(
            StaffPerformanceMetrics.staff_id.in_(ids),
            StaffPerformanceMetrics.date >= start
        ))
    )
    all_metrics = metrics_result.all()

    # Build comparison
    comparison = []
    for staff_id in ids:
        staff = staff_lookup.get(staff_id)
        if not staff:
            continue

        staff_metrics = [m for m in all_metrics if m.staff_id == staff_id]
        if staff_metrics:
            total_assigned = sum(m.tasks_assigned for m in staff_metrics)
            total_completed = sum(m.tasks_completed for m in staff_metrics)
            avg_quality = sum(m.quality_score or 0 for m in staff_metrics) / len(staff_metrics)
            avg_efficiency = sum(m.efficiency_score or 0 for m in staff_metrics) / len(staff_metrics)
            avg_completion_time = sum(m.avg_completion_time or 0 for m in staff_metrics) / len(staff_metrics)

            comparison.append({
                "staff_id": staff_id,
                "name": staff.name,
                "department": staff.department,
                "role": staff.role,
                "tasks_assigned": total_assigned,
                "tasks_completed": total_completed,
                "completion_rate": round(total_completed / total_assigned * 100, 1) if total_assigned > 0 else 0,
                "avg_completion_time_minutes": round(avg_completion_time, 1),
                "quality_score": round(avg_quality, 2),
                "efficiency_score": round(avg_efficiency, 2),
                "performance_rating": staff.performance_rating,
            })
        else:
            comparison.append({
                "staff_id": staff_id,
                "name": staff.name,
                "department": staff.department,
                "role": staff.role,
                "tasks_assigned": 0,
                "tasks_completed": 0,
                "completion_rate": 0,
                "avg_completion_time_minutes": 0,
                "quality_score": 0,
                "efficiency_score": 0,
                "performance_rating": staff.performance_rating,
            })

    # Calculate averages for comparison context
    if comparison:
        avg_metrics = {
            "avg_tasks_completed": round(sum(c["tasks_completed"] for c in comparison) / len(comparison), 1),
            "avg_completion_rate": round(sum(c["completion_rate"] for c in comparison) / len(comparison), 1),
            "avg_quality_score": round(sum(c["quality_score"] for c in comparison) / len(comparison), 2),
            "avg_efficiency_score": round(sum(c["efficiency_score"] for c in comparison) / len(comparison), 2),
        }
    else:
        avg_metrics = {}

    return {
        "period": period,
        "date_range": {"start": start.isoformat(), "end": today.isoformat()},
        "staff_count": len(comparison),
        "group_averages": avg_metrics,
        "comparison": comparison
    }


@router.get("/analytics/task-breakdown")
async def get_task_type_breakdown(
    department: Optional[str] = Query(None),
    staff_id: Optional[int] = Query(None),
    period: str = Query("month", description="week, month, quarter, year"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get breakdown of completed tasks by type"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    from app.models.operations import MaintenanceRequest
    from app.models.runner import RunnerPickupRequest, RunnerDelivery

    # Calculate date range
    today = date.today()
    if period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=month, day=1)
    else:  # year
        start = today.replace(month=1, day=1)

    start_dt = datetime.combine(start, time.min)

    # Get staff IDs if filtering by department
    staff_filter = None
    if staff_id:
        staff_filter = [staff_id]
    elif department:
        staff_result = await session.exec(
            select(Staff.id).where(Staff.department == department)
        )
        staff_filter = [s for s in staff_result.all()]

    # Housekeeping tasks breakdown
    hk_query = select(HousekeepingTask).where(and_(
        HousekeepingTask.status == "completed",
        HousekeepingTask.completed_at >= start_dt
    ))
    if staff_filter:
        hk_query = hk_query.where(HousekeepingTask.assigned_to.in_(staff_filter))

    hk_result = await session.exec(hk_query)
    hk_tasks = hk_result.all()

    hk_breakdown = {}
    for task in hk_tasks:
        task_type = task.task_type or "cleaning"
        if task_type not in hk_breakdown:
            hk_breakdown[task_type] = {"count": 0, "avg_duration": []}
        hk_breakdown[task_type]["count"] += 1
        if task.actual_duration:
            hk_breakdown[task_type]["avg_duration"].append(task.actual_duration)

    # Calculate averages
    for task_type, data in hk_breakdown.items():
        if data["avg_duration"]:
            data["avg_duration_minutes"] = round(sum(data["avg_duration"]) / len(data["avg_duration"]), 1)
        else:
            data["avg_duration_minutes"] = 0
        del data["avg_duration"]

    # Maintenance tasks breakdown
    maint_query = select(MaintenanceRequest).where(and_(
        MaintenanceRequest.status == "completed",
        MaintenanceRequest.completed_at >= start_dt
    ))
    if staff_filter:
        maint_query = maint_query.where(MaintenanceRequest.assigned_to.in_(staff_filter))

    maint_result = await session.exec(maint_query)
    maint_tasks = maint_result.all()

    maint_breakdown = {}
    for task in maint_tasks:
        category = task.category or "general"
        if category not in maint_breakdown:
            maint_breakdown[category] = {"count": 0, "avg_duration": []}
        maint_breakdown[category]["count"] += 1
        if task.actual_duration:
            maint_breakdown[category]["avg_duration"].append(task.actual_duration)

    for category, data in maint_breakdown.items():
        if data["avg_duration"]:
            data["avg_duration_minutes"] = round(sum(data["avg_duration"]) / len(data["avg_duration"]), 1)
        else:
            data["avg_duration_minutes"] = 0
        del data["avg_duration"]

    # Runner tasks
    runner_stats = {"pickups": 0, "deliveries": 0}
    try:
        pickup_query = select(RunnerPickupRequest).where(and_(
            RunnerPickupRequest.status == "completed",
            RunnerPickupRequest.completed_at >= start_dt
        ))
        if staff_filter:
            pickup_query = pickup_query.where(RunnerPickupRequest.assigned_to.in_(staff_filter))
        pickup_result = await session.exec(pickup_query)
        runner_stats["pickups"] = len(pickup_result.all())

        delivery_query = select(RunnerDelivery).where(and_(
            RunnerDelivery.status == "delivered",
            RunnerDelivery.delivered_at >= start_dt
        ))
        if staff_filter:
            delivery_query = delivery_query.where(RunnerDelivery.assigned_to.in_(staff_filter))
        delivery_result = await session.exec(delivery_query)
        runner_stats["deliveries"] = len(delivery_result.all())
    except Exception:
        pass  # Runner tables may not exist

    total_tasks = (
        sum(d["count"] for d in hk_breakdown.values()) +
        sum(d["count"] for d in maint_breakdown.values()) +
        runner_stats["pickups"] + runner_stats["deliveries"]
    )

    return {
        "department": department,
        "staff_id": staff_id,
        "period": period,
        "date_range": {"start": start.isoformat(), "end": today.isoformat()},
        "total_tasks_completed": total_tasks,
        "housekeeping": {
            "total": sum(d["count"] for d in hk_breakdown.values()),
            "by_type": hk_breakdown
        },
        "maintenance": {
            "total": sum(d["count"] for d in maint_breakdown.values()),
            "by_category": maint_breakdown
        },
        "runner": runner_stats
    }
