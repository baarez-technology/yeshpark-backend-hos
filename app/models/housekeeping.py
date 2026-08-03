"""
Housekeeping Models
Includes: HousekeepingChecklistTemplates, HousekeepingSupplies
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class HousekeepingChecklistTemplates(SQLModel, table=True):
    """Configurable cleaning checklist templates by room type"""
    __tablename__ = "housekeeping_checklist_templates"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    room_type: Optional[str] = Field(default=None, index=True)
    description: Optional[str] = None
    checklist_items: str = Field(sa_column=Column(JSON, nullable=False))  # JSONB: [{id, task, order, required, estimated_minutes}]
    estimated_duration: Optional[int] = None  # minutes
    is_active: bool = Field(default=True, index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HousekeepingSupplies(SQLModel, table=True):
    """Track housekeeping supplies inventory"""
    __tablename__ = "housekeeping_supplies"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    item_name: str = Field(nullable=False, index=True)
    category: Optional[str] = Field(default=None, index=True)  # cleaning_agent, amenity, linen, equipment
    unit_type: Optional[str] = None  # bottle, box, roll, piece
    quantity_on_hand: int = Field(default=0)
    reorder_level: int = Field(default=0)
    reorder_quantity: int = Field(default=0)
    unit_cost: Optional[float] = None
    storage_location: Optional[str] = None
    supplier: Optional[str] = None
    last_ordered_date: Optional[datetime] = None
    last_restocked_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

