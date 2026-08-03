from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field


class DashboardWidget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    role: Optional[str] = Field(default=None, index=True)  # If None, applies to all roles
    widget_type: str = Field(index=True)  # kpi, chart, table, list, alert
    widget_name: str
    widget_config: Optional[str] = None  # JSON configuration
    position: int = 0  # Order/position in dashboard
    is_visible: bool = True
    is_custom: bool = False  # User-created vs system default
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DashboardLayout(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    role: Optional[str] = Field(default=None, index=True)
    layout_name: str
    layout_config: str  # JSON configuration for grid layout
    is_default: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

