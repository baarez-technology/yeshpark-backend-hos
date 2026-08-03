"""
Overbooking Service

Handles advanced overbooking controls including:
- Per room type overbooking limits
- Dynamic adjustment based on historical no-show/cancellation rates
- Alert generation when thresholds are exceeded
- Overbooking status reporting
"""
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass

from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.inventory import (
    Room, RoomType, RoomBlock, RoomHold,
    OverbookingAlert, OverbookingConfig, DailyAvailability
)
from app.models.reservations import Reservation, Booking

logger = logging.getLogger(__name__)


@dataclass
class OverbookingStatus:
    """Status of overbooking for a room type on a specific date"""
    room_type_id: int
    room_type_name: str
    date: date
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


@dataclass
class OverbookingCheckResult:
    """Result of checking if a new booking would cause overbooking"""
    can_book: bool
    would_cause_overbooking: bool
    overbooking_allowed: bool
    current_overbooking_count: int
    max_overbooking_allowed: int
    remaining_capacity: int
    alert_severity: Optional[str] = None  # warning, critical, None
    message: str = ""
    recommendation: str = ""


class OverbookingService:
    """Service for managing overbooking controls"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_global_config(self) -> OverbookingConfig:
        """Get or create global overbooking configuration"""
        result = await self.session.exec(select(OverbookingConfig).limit(1))
        config = result.first()

        if not config:
            # Create default config
            config = OverbookingConfig()
            self.session.add(config)
            await self.session.flush()

        return config

    async def get_room_type_overbooking_limit(
        self,
        room_type: RoomType,
        target_date: date
    ) -> Tuple[float, int]:
        """
        Get the effective overbooking limit for a room type.
        Returns (percent_limit, absolute_limit)

        Priority:
        1. Room type specific absolute limit
        2. Dynamic calculation if enabled
        3. Room type specific percent limit
        4. Global default percent limit
        """
        global_config = await self.get_global_config()

        # If overbooking is disabled globally or for this room type
        if not global_config.overbooking_enabled or not room_type.overbooking_enabled:
            return 0.0, 0

        # Get total rooms of this type
        total_rooms = await self._count_rooms_by_type(room_type.id)

        # Use room type's absolute limit if set
        if room_type.overbooking_limit_absolute is not None:
            absolute_limit = room_type.overbooking_limit_absolute
            percent_limit = (absolute_limit / total_rooms * 100) if total_rooms > 0 else 0
            return percent_limit, absolute_limit

        # Use dynamic calculation if enabled
        if room_type.dynamic_overbooking and global_config.dynamic_overbooking_enabled:
            dynamic_limit = await self._calculate_dynamic_limit(room_type, target_date)
            if dynamic_limit is not None:
                # Cap at global max
                dynamic_limit = min(dynamic_limit, global_config.max_limit_percent)
                absolute_limit = int(total_rooms * dynamic_limit / 100)
                return dynamic_limit, absolute_limit

        # Use room type's percent limit
        percent_limit = room_type.overbooking_limit_percent
        percent_limit = min(percent_limit, global_config.max_limit_percent)
        absolute_limit = int(total_rooms * percent_limit / 100)

        return percent_limit, absolute_limit

    async def _calculate_dynamic_limit(
        self,
        room_type: RoomType,
        target_date: date
    ) -> Optional[float]:
        """
        Calculate dynamic overbooking limit based on historical data.
        Uses no-show and cancellation rates to determine safe overbooking level.
        """
        global_config = await self.get_global_config()

        # Calculate lookback period
        lookback_start = target_date - timedelta(days=global_config.historical_lookback_days)

        # Get historical reservations for this room type
        result = await self.session.exec(
            select(Reservation).where(
                and_(
                    Reservation.room_type_id == room_type.id,
                    Reservation.arrival_date >= lookback_start,
                    Reservation.arrival_date < target_date
                )
            )
        )
        reservations = result.all()

        if len(reservations) < global_config.min_data_points:
            # Not enough data, use static rate from room type
            return None

        # Calculate rates
        total = len(reservations)
        no_shows = len([r for r in reservations if r.status == "no_show"])
        cancellations = len([r for r in reservations if r.status == "cancelled"])

        no_show_rate = no_shows / total if total > 0 else 0
        cancellation_rate = cancellations / total if total > 0 else 0

        # Update room type with calculated rates
        room_type.no_show_rate = no_show_rate
        room_type.cancellation_rate = cancellation_rate

        # Dynamic limit = combined rate * safety factor (0.8)
        combined_rate = (no_show_rate + cancellation_rate * 0.5) * 0.8
        dynamic_limit = combined_rate * 100

        # Minimum 2%, maximum from global config
        dynamic_limit = max(2.0, min(dynamic_limit, global_config.max_limit_percent))

        return dynamic_limit

    async def _count_rooms_by_type(self, room_type_id: int) -> int:
        """Count total physical rooms of a given type"""
        result = await self.session.exec(
            select(func.count(Room.id)).where(
                and_(
                    Room.room_type_id == room_type_id,
                    Room.status != "out_of_service"
                )
            )
        )
        return result.one() or 0

    async def get_overbooking_status(
        self,
        room_type_id: int,
        target_date: date
    ) -> OverbookingStatus:
        """
        Get comprehensive overbooking status for a room type on a specific date.
        """
        # Get room type
        room_type = await self.session.get(RoomType, room_type_id)
        if not room_type:
            raise ValueError(f"Room type {room_type_id} not found")

        # Count total rooms
        total_rooms = await self._count_rooms_by_type(room_type_id)

        # Count booked rooms (reservations overlapping this date)
        booked_result = await self.session.exec(
            select(func.count(Reservation.id)).where(
                and_(
                    Reservation.room_type_id == room_type_id,
                    Reservation.status.in_(["booked", "confirmed", "checked_in"]),
                    Reservation.arrival_date <= target_date,
                    Reservation.departure_date > target_date
                )
            )
        )
        booked_count = booked_result.one() or 0

        # Count blocked rooms
        blocked_result = await self.session.exec(
            select(func.coalesce(func.sum(RoomBlock.quantity), 0)).where(
                and_(
                    RoomBlock.room_type_id == room_type_id,
                    RoomBlock.status == "active",
                    RoomBlock.start_date <= target_date,
                    RoomBlock.end_date > target_date
                )
            )
        )
        blocked_count = blocked_result.one() or 0

        # Count active holds
        held_result = await self.session.exec(
            select(func.count(RoomHold.id)).where(
                and_(
                    RoomHold.room_type_id == room_type_id,
                    RoomHold.status == "active",
                    RoomHold.expires_at > datetime.utcnow(),
                    RoomHold.arrival_date <= target_date,
                    RoomHold.departure_date > target_date
                )
            )
        )
        held_count = held_result.one() or 0

        # Calculate availability
        available_physical = total_rooms - blocked_count
        available_for_booking = available_physical - booked_count - held_count

        # Get overbooking limits
        limit_percent, limit_absolute = await self.get_room_type_overbooking_limit(
            room_type, target_date
        )

        # Calculate overbooking metrics
        current_overbooking = max(0, booked_count - available_physical)
        current_overbooking_percent = (
            (current_overbooking / total_rooms * 100) if total_rooms > 0 else 0
        )
        remaining_overbooking = max(0, limit_absolute - current_overbooking)

        is_overbooked = booked_count > available_physical
        is_at_limit = current_overbooking >= limit_absolute

        return OverbookingStatus(
            room_type_id=room_type_id,
            room_type_name=room_type.name,
            date=target_date,
            total_rooms=total_rooms,
            booked_count=booked_count,
            blocked_count=blocked_count,
            held_count=held_count,
            available_count=max(0, available_for_booking),
            overbooking_enabled=room_type.overbooking_enabled,
            overbooking_limit_percent=limit_percent,
            overbooking_limit_absolute=limit_absolute,
            current_overbooking_count=current_overbooking,
            current_overbooking_percent=current_overbooking_percent,
            remaining_overbooking_capacity=remaining_overbooking,
            is_overbooked=is_overbooked,
            is_at_limit=is_at_limit,
            dynamic_limit=limit_percent if room_type.dynamic_overbooking else None,
            no_show_rate=room_type.no_show_rate,
            cancellation_rate=room_type.cancellation_rate
        )

    async def check_overbooking_for_booking(
        self,
        room_type_id: int,
        arrival_date: date,
        departure_date: date
    ) -> OverbookingCheckResult:
        """
        Check if a new booking would cause or worsen overbooking.
        Returns detailed result with recommendation.
        """
        room_type = await self.session.get(RoomType, room_type_id)
        if not room_type:
            return OverbookingCheckResult(
                can_book=False,
                would_cause_overbooking=False,
                overbooking_allowed=False,
                current_overbooking_count=0,
                max_overbooking_allowed=0,
                remaining_capacity=0,
                message="Room type not found"
            )

        global_config = await self.get_global_config()

        # Check each night of the stay
        worst_status = None
        current_date = arrival_date

        while current_date < departure_date:
            status = await self.get_overbooking_status(room_type_id, current_date)

            if worst_status is None or status.remaining_overbooking_capacity < worst_status.remaining_overbooking_capacity:
                worst_status = status

            current_date += timedelta(days=1)

        if worst_status is None:
            return OverbookingCheckResult(
                can_book=True,
                would_cause_overbooking=False,
                overbooking_allowed=True,
                current_overbooking_count=0,
                max_overbooking_allowed=0,
                remaining_capacity=0,
                message="No dates to check"
            )

        # Determine if booking is allowed
        would_cause_overbooking = worst_status.available_count <= 0
        overbooking_allowed = worst_status.overbooking_enabled and not worst_status.is_at_limit

        if not would_cause_overbooking:
            can_book = True
            alert_severity = None
            message = "Rooms available - no overbooking needed"
            recommendation = "Proceed with booking"
        elif overbooking_allowed:
            can_book = True
            # Determine severity
            usage_percent = (
                worst_status.current_overbooking_count / worst_status.overbooking_limit_absolute * 100
                if worst_status.overbooking_limit_absolute > 0 else 100
            )
            if usage_percent >= global_config.critical_threshold_percent:
                alert_severity = "critical"
                message = f"Critical: Overbooking at {usage_percent:.0f}% of limit"
                recommendation = "Consider alternatives before booking"
            elif usage_percent >= global_config.warning_threshold_percent:
                alert_severity = "warning"
                message = f"Warning: Overbooking at {usage_percent:.0f}% of limit"
                recommendation = "Proceed with caution"
            else:
                alert_severity = None
                message = "Within safe overbooking limits"
                recommendation = "Proceed with booking"
        else:
            can_book = False
            alert_severity = "critical"
            message = "Overbooking limit reached or disabled"
            if global_config.auto_waitlist_when_full:
                recommendation = "Add to waitlist"
            else:
                recommendation = "Booking not allowed"

        return OverbookingCheckResult(
            can_book=can_book,
            would_cause_overbooking=would_cause_overbooking,
            overbooking_allowed=overbooking_allowed,
            current_overbooking_count=worst_status.current_overbooking_count,
            max_overbooking_allowed=worst_status.overbooking_limit_absolute,
            remaining_capacity=worst_status.remaining_overbooking_capacity,
            alert_severity=alert_severity,
            message=message,
            recommendation=recommendation
        )

    async def create_overbooking_alert(
        self,
        room_type_id: int,
        alert_date: date,
        triggering_booking_id: Optional[int] = None,
        severity: str = "warning"
    ) -> OverbookingAlert:
        """Create an overbooking alert"""
        status = await self.get_overbooking_status(room_type_id, alert_date)

        alert = OverbookingAlert(
            room_type_id=room_type_id,
            alert_date=alert_date,
            total_rooms=status.total_rooms,
            booked_count=status.booked_count,
            overbooking_count=status.current_overbooking_count,
            overbooking_percent=status.current_overbooking_percent,
            configured_limit_percent=status.overbooking_limit_percent,
            exceeded_by_percent=max(0, status.current_overbooking_percent - status.overbooking_limit_percent),
            severity=severity,
            alert_type="threshold_exceeded",
            message=f"Overbooking alert for {status.room_type_name} on {alert_date}: {status.current_overbooking_count} rooms overbooked ({status.current_overbooking_percent:.1f}%)",
            triggering_booking_id=triggering_booking_id,
            status="active"
        )

        self.session.add(alert)
        await self.session.flush()

        logger.warning(f"Overbooking alert created: {alert.message}")

        return alert

    async def get_active_alerts(
        self,
        room_type_id: Optional[int] = None,
        severity: Optional[str] = None,
        limit: int = 50
    ) -> List[OverbookingAlert]:
        """Get active overbooking alerts"""
        query = select(OverbookingAlert).where(
            OverbookingAlert.status.in_(["active", "acknowledged"])
        )

        if room_type_id:
            query = query.where(OverbookingAlert.room_type_id == room_type_id)
        if severity:
            query = query.where(OverbookingAlert.severity == severity)

        query = query.order_by(
            OverbookingAlert.severity.desc(),
            OverbookingAlert.alert_date.asc()
        ).limit(limit)

        result = await self.session.exec(query)
        return result.all()

    async def resolve_alert(
        self,
        alert_id: int,
        user_id: int,
        resolution_method: str,
        resolution_notes: Optional[str] = None
    ) -> OverbookingAlert:
        """Resolve an overbooking alert"""
        alert = await self.session.get(OverbookingAlert, alert_id)
        if not alert:
            raise ValueError(f"Alert {alert_id} not found")

        alert.status = "resolved"
        alert.resolved_at = datetime.utcnow()
        alert.resolved_by = user_id
        alert.resolution_method = resolution_method
        alert.resolution_notes = resolution_notes
        alert.updated_at = datetime.utcnow()

        await self.session.flush()
        return alert

    async def get_overbooking_report(
        self,
        start_date: date,
        end_date: date,
        room_type_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Generate overbooking report for a date range.
        Shows daily status and alerts.
        """
        # Get room types to report on
        if room_type_id:
            room_types = [await self.session.get(RoomType, room_type_id)]
        else:
            result = await self.session.exec(
                select(RoomType).where(RoomType.is_active == True)
            )
            room_types = result.all()

        report = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "room_types": []
        }

        for rt in room_types:
            if not rt:
                continue

            rt_report = {
                "room_type_id": rt.id,
                "room_type_name": rt.name,
                "overbooking_enabled": rt.overbooking_enabled,
                "overbooking_limit_percent": rt.overbooking_limit_percent,
                "daily_status": [],
                "alerts_count": 0,
                "max_overbooking_reached": 0
            }

            current_date = start_date
            while current_date <= end_date:
                status = await self.get_overbooking_status(rt.id, current_date)
                rt_report["daily_status"].append({
                    "date": current_date.isoformat(),
                    "total_rooms": status.total_rooms,
                    "booked": status.booked_count,
                    "blocked": status.blocked_count,
                    "available": status.available_count,
                    "overbooking_count": status.current_overbooking_count,
                    "overbooking_percent": round(status.current_overbooking_percent, 1),
                    "is_overbooked": status.is_overbooked,
                    "is_at_limit": status.is_at_limit
                })

                if status.current_overbooking_count > rt_report["max_overbooking_reached"]:
                    rt_report["max_overbooking_reached"] = status.current_overbooking_count

                current_date += timedelta(days=1)

            # Count alerts for this room type in date range
            alerts_result = await self.session.exec(
                select(func.count(OverbookingAlert.id)).where(
                    and_(
                        OverbookingAlert.room_type_id == rt.id,
                        OverbookingAlert.alert_date >= start_date,
                        OverbookingAlert.alert_date <= end_date
                    )
                )
            )
            rt_report["alerts_count"] = alerts_result.one() or 0

            report["room_types"].append(rt_report)

        return report

    async def update_room_type_overbooking_settings(
        self,
        room_type_id: int,
        enabled: Optional[bool] = None,
        limit_percent: Optional[float] = None,
        limit_absolute: Optional[int] = None,
        dynamic_enabled: Optional[bool] = None
    ) -> RoomType:
        """Update overbooking settings for a room type"""
        room_type = await self.session.get(RoomType, room_type_id)
        if not room_type:
            raise ValueError(f"Room type {room_type_id} not found")

        global_config = await self.get_global_config()

        if enabled is not None:
            room_type.overbooking_enabled = enabled

        if limit_percent is not None:
            # Validate against global max
            if limit_percent > global_config.max_limit_percent:
                raise ValueError(
                    f"Limit percent {limit_percent}% exceeds global max {global_config.max_limit_percent}%"
                )
            room_type.overbooking_limit_percent = limit_percent

        if limit_absolute is not None:
            room_type.overbooking_limit_absolute = limit_absolute

        if dynamic_enabled is not None:
            room_type.dynamic_overbooking = dynamic_enabled

        room_type.updated_at = datetime.utcnow()
        await self.session.flush()

        logger.info(f"Updated overbooking settings for room type {room_type_id}")
        return room_type


def get_overbooking_service(session: AsyncSession) -> OverbookingService:
    """Factory function to create OverbookingService instance"""
    return OverbookingService(session)
