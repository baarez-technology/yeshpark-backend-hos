"""
Maintenance-Related Models
Includes: EquipmentIssues, MaintenanceParts, Vendors
"""
from datetime import datetime, date
from datetime import date as date_type
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class EquipmentIssues(SQLModel, table=True):
    """Track equipment health, warranty, service history (separate from work orders)"""
    __tablename__ = "equipment_issues"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    issue_number: str = Field(unique=True, index=True)
    equipment_name: str = Field(nullable=False, index=True)
    equipment_id: Optional[str] = None
    equipment_category: Optional[str] = Field(default=None, index=True)  # hvac, elevator, kitchen, pool, generator, safety, laundry, other
    location: str = Field(nullable=False, index=True)
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)
    issue_type: str = Field(nullable=False)
    issue_description: str = Field(nullable=False)
    severity: str = Field(nullable=False, index=True)  # low, medium, high, critical
    status: str = Field(default="pending", index=True)  # pending, in_progress, resolved, requires_parts, escalated
    reported_by: int = Field(foreign_key="staff.id", index=True)
    reported_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id", index=True)
    accepted_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    purchase_date: Optional[date_type] = None
    warranty_status: Optional[str] = Field(default=None, index=True)  # active, expired, not_applicable, unknown
    warranty_expiry_date: Optional[date_type] = None
    last_service_date: Optional[date_type] = None
    next_service_date: Optional[date_type] = None
    service_contract: bool = Field(default=False)
    estimated_repair_cost: Optional[float] = None
    actual_repair_cost: Optional[float] = None
    downtime_hours: Optional[float] = None
    affects_operations: bool = Field(default=False)
    photos: Optional[str] = Field(default=None, sa_column=Column("photos", JSON))  # JSONB
    parts_needed: Optional[str] = Field(default=None, sa_column=Column("parts_needed", JSON))  # JSONB
    vendor_id: Optional[int] = Field(default=None, foreign_key="vendors.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MaintenanceParts(SQLModel, table=True):
    """Track parts used in maintenance work orders"""
    __tablename__ = "maintenance_parts"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    work_order_id: int = Field(foreign_key="maintenancerequest.id", index=True)
    part_name: str = Field(nullable=False)
    part_number: Optional[str] = None
    category: Optional[str] = None
    quantity: int = Field(nullable=False)
    unit_cost: Optional[float] = None
    total_cost: Optional[float] = None
    vendor_id: Optional[int] = Field(default=None, foreign_key="vendors.id", index=True)
    ordered_date: Optional[date_type] = None
    received_date: Optional[date_type] = None
    installed_date: Optional[date_type] = None
    status: Optional[str] = Field(default=None, index=True)  # ordered, received, installed, returned
    warranty_expiry: Optional[date_type] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Vendors(SQLModel, table=True):
    """Track vendors/suppliers for parts and services"""
    __tablename__ = "vendors"

    id: Optional[int] = Field(default=None, primary_key=True)
    vendor_code: Optional[str] = Field(default=None, unique=True, index=True)
    name: str = Field(nullable=False)
    category: Optional[str] = Field(default=None, index=True)  # parts, services, supplies, equipment
    specialty: Optional[str] = Field(default=None, index=True)
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    payment_terms: Optional[str] = None
    tax_id: Optional[str] = None
    rating: Optional[float] = None
    total_orders: int = Field(default=0)
    total_spent: float = Field(default=0.0)
    last_order_date: Optional[date_type] = None
    is_active: bool = Field(default=True, index=True)
    is_preferred: bool = Field(default=False, index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MaintenanceInventory(SQLModel, table=True):
    """Inventory items for maintenance supplies, parts, and equipment"""
    __tablename__ = "maintenance_inventory"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False, index=True)
    category: str = Field(default="general", index=True)  # general, electrical, plumbing, hvac, hardware, cleaning, linens, amenities, other
    stock_level: int = Field(default=0)
    min_stock: int = Field(default=0)
    unit_cost: float = Field(default=0.0)
    location: Optional[str] = None
    part_number: Optional[str] = Field(default=None, index=True)
    supplier_id: Optional[int] = Field(default=None, foreign_key="vendors.id", index=True)
    reorder_quantity: Optional[int] = Field(default=None)
    last_restocked: Optional[date_type] = None
    notes: Optional[str] = None
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PreventiveMaintenanceSchedule(SQLModel, table=True):
    """Preventive maintenance schedules for recurring maintenance tasks"""
    __tablename__ = "preventive_maintenance_schedules"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False, index=True)
    description: Optional[str] = None
    equipment_id: Optional[int] = Field(default=None, index=True)
    location: str = Field(nullable=False)
    maintenance_type: str = Field(nullable=False, index=True)  # hvac, electrical, plumbing, fire_safety, elevator, general
    frequency: str = Field(nullable=False, index=True)  # daily, weekly, biweekly, monthly, quarterly, semi-annual, annual
    day_of_week: Optional[int] = None  # 0=Monday, 6=Sunday (for weekly schedules)
    day_of_month: Optional[int] = None  # 1-31 (for monthly schedules)
    estimated_duration: int = Field(default=60)  # minutes
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id", index=True)
    checklist: Optional[str] = Field(default=None, sa_column=Column("checklist", JSON))  # JSONB
    priority: str = Field(default="normal")  # low, normal, high
    active: bool = Field(default=True, index=True)
    last_performed: Optional[date_type] = None
    next_due_date: Optional[date_type] = Field(default=None, index=True)
    total_completions: int = Field(default=0)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

