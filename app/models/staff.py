"""
Staff and Staff-Related Models
Includes: Staff, StaffAttendance, StaffPerformanceMetrics, StaffSchedule, StaffLeave, StaffCertification, StaffTraining
"""
from datetime import datetime
from datetime import date as date_type  # Alias to avoid field name conflicts
from datetime import time as time_type  # Alias to avoid conflict with SQLAlchemy Time
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, Time
from app.models.base import TimestampedModel


class Staff(SQLModel, table=True):
    """Staff/employee information with ALL role-specific fields"""
    __tablename__ = "staff"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)
    employee_id: Optional[str] = Field(default=None, unique=True, index=True)
    name: str = Field(nullable=False)
    email: str = Field(nullable=False, index=True)  # Work email (login)
    personal_email: Optional[str] = Field(default=None, index=True)  # Personal email (for sending credentials)
    phone: Optional[str] = None
    role: str = Field(nullable=False)
    department: str = Field(nullable=False, index=True)  # frontdesk, housekeeping, maintenance, management, runner, security, kitchen, finance
    specialty: Optional[str] = Field(default=None, index=True)  # electrical, plumbing, hvac, carpentry, general, laundry, chef, etc.
    status: str = Field(default="active", index=True)  # active, inactive, on_leave, sick, off_duty, disabled
    shift: Optional[str] = None
    shift_start: Optional[time_type] = Field(default=None, sa_column=Column(Time))  # *** NEW FIELD ***
    shift_end: Optional[time_type] = Field(default=None, sa_column=Column(Time))  # *** NEW FIELD ***
    clocked_in: bool = Field(default=False, index=True)  # *** NEW FIELD ***
    clock_in_time: Optional[datetime] = None  # *** NEW FIELD ***
    supervisor_id: Optional[int] = Field(default=None, foreign_key="staff.id", index=True)  # *** NEW FIELD (self-referencing) ***
    supervisor_name: Optional[str] = None  # *** NEW FIELD ***
    floor_assignment: Optional[str] = Field(default=None, sa_column=Column("floor_assignment", JSON))  # JSONB in PostgreSQL
    hire_date: date_type = Field(nullable=False)
    termination_date: Optional[date_type] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    address: Optional[str] = None
    salary: Optional[float] = None
    hourly_rate: Optional[float] = None
    avatar: Optional[str] = None
    performance_rating: Optional[float] = None
    certifications: Optional[str] = Field(default=None, sa_column=Column("certifications", JSON))  # JSONB
    skills: Optional[str] = Field(default=None, sa_column=Column("skills", JSON))  # JSONB
    languages_spoken: Optional[str] = Field(default=None, sa_column=Column("languages_spoken", JSON))  # JSONB
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StaffAttendance(SQLModel, table=True):
    """Track staff clock in/out and daily attendance"""
    __tablename__ = "staff_attendance"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    date: date_type = Field(nullable=False, index=True)
    shift_type: Optional[str] = None
    scheduled_start: time_type = Field(sa_column=Column(Time, nullable=False))
    scheduled_end: time_type = Field(sa_column=Column(Time, nullable=False))
    actual_clock_in: Optional[datetime] = None
    actual_clock_out: Optional[datetime] = None
    total_hours_worked: Optional[float] = None
    overtime_hours: Optional[float] = None
    break_duration: Optional[int] = None  # minutes
    status: Optional[str] = Field(default=None, index=True)  # present, absent, late, early_leave, sick, vacation
    late_minutes: int = Field(default=0)
    early_leave_minutes: int = Field(default=0)
    is_overtime: bool = Field(default=False)
    approved_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    notes: Optional[str] = None
    clock_in_location: Optional[str] = None
    clock_out_location: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StaffPerformanceMetrics(SQLModel, table=True):
    """Track daily staff performance metrics"""
    __tablename__ = "staff_performance_metrics"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    date: date_type = Field(nullable=False, index=True)
    department: Optional[str] = Field(default=None, index=True)
    tasks_assigned: int = Field(default=0)
    tasks_completed: int = Field(default=0)
    tasks_completed_on_time: int = Field(default=0)
    avg_completion_time: Optional[int] = None  # minutes
    efficiency_score: Optional[float] = None  # percentage
    quality_score: Optional[float] = None  # 1-5 rating
    customer_rating: Optional[float] = None
    delays_count: int = Field(default=0)
    attendance_status: Optional[str] = None
    minutes_late: int = Field(default=0)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StaffSchedule(SQLModel, table=True):
    """Staff scheduling and shift management"""
    __tablename__ = "staff_schedules"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    schedule_date: date_type = Field(nullable=False, index=True)
    shift_type: str = Field(index=True)  # morning, afternoon, evening, night
    start_time: time_type = Field(sa_column=Column(Time, nullable=False))
    end_time: time_type = Field(sa_column=Column(Time, nullable=False))
    department: Optional[str] = Field(default=None, index=True)
    location: Optional[str] = None
    status: str = Field(default="scheduled", index=True)  # scheduled, confirmed, cancelled, completed
    notes: Optional[str] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StaffLeave(SQLModel, table=True):
    """Track staff leave requests and approvals"""
    __tablename__ = "staff_leave"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    leave_type: str = Field(index=True)  # vacation, sick, personal, emergency, bereavement
    start_date: date_type = Field(nullable=False, index=True)
    end_date: date_type = Field(nullable=False, index=True)
    total_days: int = Field(nullable=False)
    reason: Optional[str] = None
    status: str = Field(default="pending", index=True)  # pending, approved, rejected, cancelled
    approved_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StaffCertification(SQLModel, table=True):
    """Track staff certifications and qualifications"""
    __tablename__ = "staff_certifications"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    certification_name: str = Field(nullable=False)
    certification_type: Optional[str] = Field(default=None, index=True)  # safety, technical, professional, license
    issuing_organization: Optional[str] = None
    certification_number: Optional[str] = None
    issue_date: Optional[date_type] = None
    expiry_date: Optional[date_type] = Field(default=None, index=True)
    status: str = Field(default="active", index=True)  # active, expired, suspended, revoked
    renewal_required: bool = Field(default=False)
    document_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StaffTraining(SQLModel, table=True):
    """Track staff training programs and completion"""
    __tablename__ = "staff_training"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    training_name: str = Field(nullable=False)
    training_type: Optional[str] = Field(default=None, index=True)  # onboarding, compliance, skills, leadership
    training_provider: Optional[str] = None
    scheduled_date: Optional[date_type] = Field(default=None, index=True)
    completion_date: Optional[date_type] = Field(default=None, index=True)
    duration_hours: Optional[float] = None
    status: str = Field(default="scheduled", index=True)  # scheduled, in_progress, completed, cancelled
    score: Optional[float] = None
    passed: Optional[bool] = None
    certificate_url: Optional[str] = None
    cost: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

