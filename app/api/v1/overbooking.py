"""
Overbooking Management API Endpoints

Provides endpoints for:
- Viewing overbooking status per room type
- Configuring overbooking limits
- Managing overbooking alerts
- Generating overbooking reports
"""
from typing import List, Optional
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.inventory import RoomType, OverbookingAlert, OverbookingConfig
from app.services.overbooking_service import (
    OverbookingService,
    get_overbooking_service,
    OverbookingStatus as OverbookingStatusModel
)

router = APIRouter()


# ============== SCHEMAS ==============

class OverbookingStatusResponse(BaseModel):
    room_type_id: int
    room_type_name: str
    date: str
    total_rooms: int
    booked_count: int
    blocked_count: int
    held_count: int
    available_count: int
    overbooking_enabled: bool
    overbooking_limit_percent: float
    overbooking_limit_absolute: int
    current_overbooking_count: int
    current_overbooking_percent: float
    remaining_overbooking_capacity: int
    is_overbooked: bool
    is_at_limit: bool
    dynamic_limit: Optional[float] = None
    no_show_rate: Optional[float] = None
    cancellation_rate: Optional[float] = None


class OverbookingCheckRequest(BaseModel):
    room_type_id: int
    arrival_date: date
    departure_date: date


class OverbookingCheckResponse(BaseModel):
    can_book: bool
    would_cause_overbooking: bool
    overbooking_allowed: bool
    current_overbooking_count: int
    max_overbooking_allowed: int
    remaining_capacity: int
    alert_severity: Optional[str] = None
    message: str
    recommendation: str


class RoomTypeOverbookingSettings(BaseModel):
    overbooking_enabled: Optional[bool] = None
    overbooking_limit_percent: Optional[float] = None
    overbooking_limit_absolute: Optional[int] = None
    dynamic_overbooking: Optional[bool] = None


class GlobalOverbookingConfigUpdate(BaseModel):
    overbooking_enabled: Optional[bool] = None
    default_limit_percent: Optional[float] = None
    max_limit_percent: Optional[float] = None
    dynamic_overbooking_enabled: Optional[bool] = None
    historical_lookback_days: Optional[int] = None
    min_data_points: Optional[int] = None
    warning_threshold_percent: Optional[float] = None
    critical_threshold_percent: Optional[float] = None
    alert_managers: Optional[bool] = None
    alert_front_desk: Optional[bool] = None
    email_notifications: Optional[bool] = None
    relocation_compensation_percent: Optional[float] = None
    upgrade_when_relocating: Optional[bool] = None
    auto_waitlist_when_full: Optional[bool] = None
    block_new_bookings_at_limit: Optional[bool] = None


class AlertResolveRequest(BaseModel):
    resolution_method: str  # relocated, cancelled, waitlisted, no_action_needed
    resolution_notes: Optional[str] = None


class OverbookingAlertResponse(BaseModel):
    id: int
    room_type_id: int
    room_type_name: Optional[str] = None
    alert_date: str
    total_rooms: int
    booked_count: int
    overbooking_count: int
    overbooking_percent: float
    configured_limit_percent: float
    exceeded_by_percent: float
    severity: str
    alert_type: str
    message: str
    status: str
    resolved_at: Optional[str] = None
    resolution_method: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: str


# ============== STATUS ENDPOINTS ==============

@router.get("/status/{room_type_id}", response_model=OverbookingStatusResponse)
async def get_overbooking_status(
    room_type_id: int,
    target_date: date = Query(default=None, description="Date to check (defaults to today)"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get overbooking status for a specific room type on a date"""
    if target_date is None:
        target_date = date.today()

    service = get_overbooking_service(session)

    try:
        status = await service.get_overbooking_status(room_type_id, target_date)
        return OverbookingStatusResponse(
            room_type_id=status.room_type_id,
            room_type_name=status.room_type_name,
            date=status.date.isoformat(),
            total_rooms=status.total_rooms,
            booked_count=status.booked_count,
            blocked_count=status.blocked_count,
            held_count=status.held_count,
            available_count=status.available_count,
            overbooking_enabled=status.overbooking_enabled,
            overbooking_limit_percent=status.overbooking_limit_percent,
            overbooking_limit_absolute=status.overbooking_limit_absolute,
            current_overbooking_count=status.current_overbooking_count,
            current_overbooking_percent=status.current_overbooking_percent,
            remaining_overbooking_capacity=status.remaining_overbooking_capacity,
            is_overbooked=status.is_overbooked,
            is_at_limit=status.is_at_limit,
            dynamic_limit=status.dynamic_limit,
            no_show_rate=status.no_show_rate,
            cancellation_rate=status.cancellation_rate
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/status-all")
async def get_all_overbooking_status(
    target_date: date = Query(default=None, description="Date to check (defaults to today)"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get overbooking status for all active room types"""
    if target_date is None:
        target_date = date.today()

    service = get_overbooking_service(session)

    # Get all active room types
    result = await session.exec(
        select(RoomType).where(RoomType.is_active == True)
    )
    room_types = result.all()

    statuses = []
    for rt in room_types:
        try:
            status = await service.get_overbooking_status(rt.id, target_date)
            statuses.append({
                "room_type_id": status.room_type_id,
                "room_type_name": status.room_type_name,
                "date": status.date.isoformat(),
                "total_rooms": status.total_rooms,
                "booked_count": status.booked_count,
                "available_count": status.available_count,
                "overbooking_enabled": status.overbooking_enabled,
                "overbooking_limit_percent": status.overbooking_limit_percent,
                "current_overbooking_count": status.current_overbooking_count,
                "current_overbooking_percent": round(status.current_overbooking_percent, 1),
                "remaining_capacity": status.remaining_overbooking_capacity,
                "is_overbooked": status.is_overbooked,
                "is_at_limit": status.is_at_limit
            })
        except Exception as e:
            statuses.append({
                "room_type_id": rt.id,
                "room_type_name": rt.name,
                "error": str(e)
            })

    # Summary
    total_overbooked = len([s for s in statuses if s.get("is_overbooked")])
    at_limit_count = len([s for s in statuses if s.get("is_at_limit")])

    return {
        "date": target_date.isoformat(),
        "total_room_types": len(room_types),
        "overbooked_count": total_overbooked,
        "at_limit_count": at_limit_count,
        "room_types": statuses
    }


@router.post("/check", response_model=OverbookingCheckResponse)
async def check_overbooking_for_booking(
    request: OverbookingCheckRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Check if a potential booking would cause or worsen overbooking"""
    service = get_overbooking_service(session)

    result = await service.check_overbooking_for_booking(
        request.room_type_id,
        request.arrival_date,
        request.departure_date
    )

    return OverbookingCheckResponse(
        can_book=result.can_book,
        would_cause_overbooking=result.would_cause_overbooking,
        overbooking_allowed=result.overbooking_allowed,
        current_overbooking_count=result.current_overbooking_count,
        max_overbooking_allowed=result.max_overbooking_allowed,
        remaining_capacity=result.remaining_capacity,
        alert_severity=result.alert_severity,
        message=result.message,
        recommendation=result.recommendation
    )


# ============== CONFIGURATION ENDPOINTS ==============

@router.get("/config")
async def get_global_overbooking_config(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get global overbooking configuration"""
    service = get_overbooking_service(session)
    config = await service.get_global_config()

    return {
        "id": config.id,
        "overbooking_enabled": config.overbooking_enabled,
        "default_limit_percent": config.default_limit_percent,
        "max_limit_percent": config.max_limit_percent,
        "dynamic_overbooking_enabled": config.dynamic_overbooking_enabled,
        "historical_lookback_days": config.historical_lookback_days,
        "min_data_points": config.min_data_points,
        "warning_threshold_percent": config.warning_threshold_percent,
        "critical_threshold_percent": config.critical_threshold_percent,
        "alert_managers": config.alert_managers,
        "alert_front_desk": config.alert_front_desk,
        "email_notifications": config.email_notifications,
        "relocation_compensation_percent": config.relocation_compensation_percent,
        "upgrade_when_relocating": config.upgrade_when_relocating,
        "auto_waitlist_when_full": config.auto_waitlist_when_full,
        "block_new_bookings_at_limit": config.block_new_bookings_at_limit,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat()
    }


@router.patch("/config")
async def update_global_overbooking_config(
    updates: GlobalOverbookingConfigUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update global overbooking configuration (admin only)"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    service = get_overbooking_service(session)
    config = await service.get_global_config()

    update_data = updates.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(config, field):
            setattr(config, field, value)

    config.updated_at = datetime.utcnow()
    await session.commit()

    return {"message": "Configuration updated successfully", "config_id": config.id}


@router.get("/room-type/{room_type_id}/settings")
async def get_room_type_overbooking_settings(
    room_type_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get overbooking settings for a specific room type"""
    room_type = await session.get(RoomType, room_type_id)
    if not room_type:
        raise HTTPException(status_code=404, detail="Room type not found")

    return {
        "room_type_id": room_type.id,
        "room_type_name": room_type.name,
        "overbooking_enabled": room_type.overbooking_enabled,
        "overbooking_limit_percent": room_type.overbooking_limit_percent,
        "overbooking_limit_absolute": room_type.overbooking_limit_absolute,
        "dynamic_overbooking": room_type.dynamic_overbooking,
        "no_show_rate": room_type.no_show_rate,
        "cancellation_rate": room_type.cancellation_rate
    }


@router.patch("/room-type/{room_type_id}/settings")
async def update_room_type_overbooking_settings(
    room_type_id: int,
    settings: RoomTypeOverbookingSettings,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update overbooking settings for a specific room type"""
    if current_user.role not in ["admin", "manager"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    service = get_overbooking_service(session)

    try:
        room_type = await service.update_room_type_overbooking_settings(
            room_type_id,
            enabled=settings.overbooking_enabled,
            limit_percent=settings.overbooking_limit_percent,
            limit_absolute=settings.overbooking_limit_absolute,
            dynamic_enabled=settings.dynamic_overbooking
        )
        await session.commit()

        return {
            "message": "Settings updated successfully",
            "room_type_id": room_type.id,
            "room_type_name": room_type.name,
            "overbooking_enabled": room_type.overbooking_enabled,
            "overbooking_limit_percent": room_type.overbooking_limit_percent,
            "overbooking_limit_absolute": room_type.overbooking_limit_absolute,
            "dynamic_overbooking": room_type.dynamic_overbooking
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============== ALERT ENDPOINTS ==============

@router.get("/alerts", response_model=List[OverbookingAlertResponse])
async def get_overbooking_alerts(
    status: Optional[str] = Query(None, description="Filter by status (active, acknowledged, resolved)"),
    severity: Optional[str] = Query(None, description="Filter by severity (warning, critical)"),
    room_type_id: Optional[int] = Query(None, description="Filter by room type"),
    limit: int = Query(50, le=100),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get overbooking alerts"""
    service = get_overbooking_service(session)
    alerts = await service.get_active_alerts(
        room_type_id=room_type_id,
        severity=severity,
        limit=limit
    )

    # Get room type names
    response = []
    for alert in alerts:
        room_type_name = None
        room_type = await session.get(RoomType, alert.room_type_id)
        if room_type:
            room_type_name = room_type.name

        response.append(OverbookingAlertResponse(
            id=alert.id,
            room_type_id=alert.room_type_id,
            room_type_name=room_type_name,
            alert_date=alert.alert_date.isoformat(),
            total_rooms=alert.total_rooms,
            booked_count=alert.booked_count,
            overbooking_count=alert.overbooking_count,
            overbooking_percent=alert.overbooking_percent,
            configured_limit_percent=alert.configured_limit_percent,
            exceeded_by_percent=alert.exceeded_by_percent,
            severity=alert.severity,
            alert_type=alert.alert_type,
            message=alert.message,
            status=alert.status,
            resolved_at=alert.resolved_at.isoformat() if alert.resolved_at else None,
            resolution_method=alert.resolution_method,
            resolution_notes=alert.resolution_notes,
            created_at=alert.created_at.isoformat()
        ))

    return response


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Acknowledge an overbooking alert"""
    alert = await session.get(OverbookingAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status == "resolved":
        raise HTTPException(status_code=400, detail="Alert is already resolved")

    alert.status = "acknowledged"
    alert.updated_at = datetime.utcnow()
    await session.commit()

    return {"message": "Alert acknowledged", "alert_id": alert_id}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    request: AlertResolveRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Resolve an overbooking alert"""
    service = get_overbooking_service(session)

    try:
        alert = await service.resolve_alert(
            alert_id,
            current_user.id,
            request.resolution_method,
            request.resolution_notes
        )
        await session.commit()

        return {
            "message": "Alert resolved",
            "alert_id": alert_id,
            "resolution_method": request.resolution_method
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============== REPORT ENDPOINTS ==============

@router.get("/report")
async def get_overbooking_report(
    start_date: date = Query(..., description="Report start date"),
    end_date: date = Query(..., description="Report end date"),
    room_type_id: Optional[int] = Query(None, description="Filter by room type"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Generate overbooking report for a date range"""
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    if (end_date - start_date).days > 90:
        raise HTTPException(status_code=400, detail="Date range cannot exceed 90 days")

    service = get_overbooking_service(session)
    report = await service.get_overbooking_report(start_date, end_date, room_type_id)

    return report


@router.get("/dashboard")
async def get_overbooking_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get overbooking dashboard summary"""
    service = get_overbooking_service(session)
    config = await service.get_global_config()

    today = date.today()
    next_week = today + timedelta(days=7)

    # Get all room types
    result = await session.exec(
        select(RoomType).where(RoomType.is_active == True)
    )
    room_types = result.all()

    # Calculate summary for today
    today_summary = {
        "total_room_types": len(room_types),
        "overbooked_count": 0,
        "at_limit_count": 0,
        "total_overbooking_count": 0
    }

    for rt in room_types:
        try:
            status = await service.get_overbooking_status(rt.id, today)
            if status.is_overbooked:
                today_summary["overbooked_count"] += 1
            if status.is_at_limit:
                today_summary["at_limit_count"] += 1
            today_summary["total_overbooking_count"] += status.current_overbooking_count
        except Exception:
            pass

    # Get active alerts count
    active_alerts = await service.get_active_alerts(limit=100)
    critical_alerts = len([a for a in active_alerts if a.severity == "critical"])
    warning_alerts = len([a for a in active_alerts if a.severity == "warning"])

    # Get weekly forecast (simplified)
    weekly_forecast = []
    current = today
    while current <= next_week:
        day_overbooked = 0
        for rt in room_types:
            try:
                status = await service.get_overbooking_status(rt.id, current)
                if status.is_overbooked:
                    day_overbooked += 1
            except Exception:
                pass

        weekly_forecast.append({
            "date": current.isoformat(),
            "overbooked_room_types": day_overbooked
        })
        current += timedelta(days=1)

    return {
        "config_enabled": config.overbooking_enabled,
        "today": today_summary,
        "alerts": {
            "total_active": len(active_alerts),
            "critical": critical_alerts,
            "warning": warning_alerts
        },
        "weekly_forecast": weekly_forecast
    }


# Helper import
from datetime import timedelta
