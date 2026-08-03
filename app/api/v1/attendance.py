"""
Attendance Management API Endpoints
GET /api/v1/attendance          - List attendance records with filters
GET /api/v1/attendance/summary  - Summary counts for a specific date
GET /api/v1/attendance/export   - CSV export of attendance data
"""
from typing import Optional, List
from datetime import datetime, date, time
from io import StringIO
import csv

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.staff import Staff, StaffAttendance

router = APIRouter()


# ── Response Schemas ──

class AttendanceSummaryResponse(BaseModel):
    present: int = 0
    absent: int = 0
    late: int = 0
    early_leave: int = 0
    overtime: int = 0
    total_scheduled: int = 0


class AttendanceEntryResponse(BaseModel):
    id: int
    staff_id: int
    staff_name: str
    staff_role: str
    department: str
    shift_type: Optional[str] = None
    date: str
    clock_in: Optional[str] = None
    clock_out: Optional[str] = None
    status: str
    total_hours: Optional[float] = None
    late_minutes: int = 0
    early_leave_minutes: int = 0
    notes: Optional[str] = None


# ── Helper: Build staff lookup ──

async def _get_staff_lookup(session: AsyncSession) -> dict:
    """Build a dict of staff_id -> Staff for quick lookups."""
    result = await session.exec(select(Staff))
    return {s.id: s for s in result.all()}


# ── GET /attendance ──

@router.get("", response_model=List[AttendanceEntryResponse])
async def list_attendance(
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    start_date: Optional[str] = Query(None, description="Start date for range"),
    end_date: Optional[str] = Query(None, description="End date for range"),
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    shift_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """List attendance records with optional filters."""
    # Only admin/manager can view all attendance
    if current_user.role not in ("admin", "manager", "superuser") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    staff_lookup = await _get_staff_lookup(session)

    # Build query
    query = select(StaffAttendance)

    # Date filters
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        query = query.where(StaffAttendance.date == target_date)
    elif start_date or end_date:
        if start_date:
            try:
                sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")
            query = query.where(StaffAttendance.date >= sd)
        if end_date:
            try:
                ed = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")
            query = query.where(StaffAttendance.date <= ed)
    else:
        # Default to today
        query = query.where(StaffAttendance.date == datetime.utcnow().date())

    # Status filter
    if status:
        query = query.where(StaffAttendance.status == status)

    # Shift filter
    if shift_type:
        query = query.where(StaffAttendance.shift_type == shift_type)

    # Order and paginate
    query = query.order_by(StaffAttendance.date.desc(), StaffAttendance.id.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await session.exec(query)
    records = result.all()

    # Deduplicate: keep one record per (staff_id, date).
    # Merge hours, keep earliest clock-in, latest clock-out, worst status.
    deduped: dict[tuple, any] = {}
    for record in records:
        key = (record.staff_id, record.date)
        if key not in deduped:
            deduped[key] = record
        else:
            kept = deduped[key]
            # Accumulate hours
            if record.total_hours_worked:
                kept.total_hours_worked = (kept.total_hours_worked or 0) + record.total_hours_worked
            # Keep earliest clock-in
            if record.actual_clock_in and (not kept.actual_clock_in or record.actual_clock_in < kept.actual_clock_in):
                kept.actual_clock_in = record.actual_clock_in
            # Keep latest clock-out
            if record.actual_clock_out and (not kept.actual_clock_out or record.actual_clock_out > kept.actual_clock_out):
                kept.actual_clock_out = record.actual_clock_out
            # Keep worst late_minutes
            kept.late_minutes = max(kept.late_minutes or 0, record.late_minutes or 0)
            # Merge notes
            if record.notes:
                kept.notes = f"{kept.notes or ''}\n{record.notes}".strip()

    # Build response with staff info
    entries = []
    for record in deduped.values():
        staff = staff_lookup.get(record.staff_id)
        if not staff:
            continue

        # Apply department filter (need staff info)
        if department and staff.department != department:
            continue

        # Apply search filter
        if search:
            q = search.lower()
            if not (q in staff.name.lower() or q in staff.role.lower() or q in staff.department.lower()):
                continue

        entries.append(AttendanceEntryResponse(
            id=record.id,
            staff_id=record.staff_id,
            staff_name=staff.name,
            staff_role=staff.role,
            department=staff.department,
            shift_type=record.shift_type,
            date=record.date.isoformat(),
            clock_in=record.actual_clock_in.strftime("%H:%M") if record.actual_clock_in else None,
            clock_out=record.actual_clock_out.strftime("%H:%M") if record.actual_clock_out else None,
            status=record.status or "absent",
            total_hours=record.total_hours_worked,
            late_minutes=record.late_minutes or 0,
            early_leave_minutes=record.early_leave_minutes or 0,
            notes=record.notes,
        ))

    return entries


# ── GET /attendance/summary ──

@router.get("/summary", response_model=AttendanceSummaryResponse)
async def attendance_summary(
    date: str = Query(..., description="Date for summary (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Get attendance summary counts for a specific date."""
    if current_user.role not in ("admin", "manager", "superuser") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Get all attendance records for this date
    result = await session.exec(
        select(StaffAttendance).where(StaffAttendance.date == target_date)
    )
    records = result.all()

    # Deduplicate: keep one record per staff_id (earliest by id)
    deduped: dict[int, any] = {}
    for record in records:
        if record.staff_id not in deduped:
            deduped[record.staff_id] = record
        else:
            kept = deduped[record.staff_id]
            # Accumulate hours
            if record.total_hours_worked:
                kept.total_hours_worked = (kept.total_hours_worked or 0) + record.total_hours_worked
            # Merge overtime flag
            if record.is_overtime:
                kept.is_overtime = True

    # Count total scheduled staff
    staff_result = await session.exec(
        select(func.count(Staff.id)).where(Staff.status.in_(["active", "on_leave", "sick"]))
    )
    total_staff = staff_result.one()

    present = 0
    absent = 0
    late = 0
    early_leave = 0
    overtime = 0
    staff_with_records = set()

    for record in deduped.values():
        staff_with_records.add(record.staff_id)
        status = record.status or "absent"

        if status == "present":
            present += 1
        elif status == "late":
            late += 1
            present += 1  # Late staff are still present
        elif status == "early_leave":
            early_leave += 1
            present += 1  # Early leave staff were present
        elif status == "overtime":
            overtime += 1
            present += 1
        elif status in ("absent", "sick", "on_leave"):
            absent += 1

        # Check overtime flag independently
        if record.is_overtime and status != "overtime":
            overtime += 1

    # Staff without records are absent (for today or past dates)
    absent += max(0, total_staff - len(staff_with_records))

    return AttendanceSummaryResponse(
        present=present,
        absent=absent,
        late=late,
        early_leave=early_leave,
        overtime=overtime,
        total_scheduled=total_staff,
    )


# ── GET /attendance/export ──

@router.get("/export")
async def export_attendance(
    date: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Export attendance data as CSV."""
    if current_user.role not in ("admin", "manager", "superuser") and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    staff_lookup = await _get_staff_lookup(session)

    # Build query
    query = select(StaffAttendance)

    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        query = query.where(StaffAttendance.date == target_date)
    elif start_date:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        query = query.where(StaffAttendance.date >= sd)
        if end_date:
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()
            query = query.where(StaffAttendance.date <= ed)

    if status:
        query = query.where(StaffAttendance.status == status)

    query = query.order_by(StaffAttendance.date.desc(), StaffAttendance.staff_id)

    result = await session.exec(query)
    raw_records = result.all()

    # Deduplicate: one record per (staff_id, date)
    deduped: dict[tuple, any] = {}
    for record in raw_records:
        key = (record.staff_id, record.date)
        if key not in deduped:
            deduped[key] = record
        else:
            kept = deduped[key]
            if record.total_hours_worked:
                kept.total_hours_worked = (kept.total_hours_worked or 0) + record.total_hours_worked
            if record.actual_clock_in and (not kept.actual_clock_in or record.actual_clock_in < kept.actual_clock_in):
                kept.actual_clock_in = record.actual_clock_in
            if record.actual_clock_out and (not kept.actual_clock_out or record.actual_clock_out > kept.actual_clock_out):
                kept.actual_clock_out = record.actual_clock_out

    records = list(deduped.values())

    # Build CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Staff Name", "Role", "Department", "Shift", "Date", "Clock In", "Clock Out", "Status", "Total Hours", "Late (min)", "Early Leave (min)", "Notes"])

    for record in records:
        staff = staff_lookup.get(record.staff_id)
        if not staff:
            continue
        if department and staff.department != department:
            continue

        writer.writerow([
            staff.name,
            staff.role,
            staff.department,
            record.shift_type or "--",
            record.date.isoformat(),
            record.actual_clock_in.strftime("%H:%M") if record.actual_clock_in else "--",
            record.actual_clock_out.strftime("%H:%M") if record.actual_clock_out else "--",
            record.status or "absent",
            f"{record.total_hours_worked:.1f}" if record.total_hours_worked else "--",
            record.late_minutes or 0,
            record.early_leave_minutes or 0,
            record.notes or "",
        ])

    output.seek(0)
    filename = f"attendance_{date or 'export'}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
