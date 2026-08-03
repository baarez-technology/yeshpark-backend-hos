"""
Maintenance Block Service

Handles automated room blocking when maintenance marks a room as Out of Order (OOO).
Features:
- Auto-create RoomBlock when maintenance request has is_out_of_order=True
- Auto-release RoomBlock when maintenance is completed
- Detect and alert for affected bookings
- Bidirectional sync between MaintenanceRequest and RoomBlock
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.inventory import Room, RoomType, RoomBlock
from app.models.operations import MaintenanceRequest
from app.models.reservations import Reservation

logger = logging.getLogger(__name__)


@dataclass
class AffectedBooking:
    """Booking affected by a room block"""
    reservation_id: int
    confirmation_code: str
    guest_name: str
    arrival_date: date
    departure_date: date
    room_id: Optional[int]
    room_number: Optional[str]
    status: str
    overlap_start: date
    overlap_end: date
    requires_action: bool  # True if room was specifically assigned


@dataclass
class MaintenanceBlockResult:
    """Result of creating/updating a maintenance block"""
    success: bool
    room_block_id: Optional[int]
    maintenance_request_id: int
    affected_bookings: List[AffectedBooking]
    action_taken: str  # created, updated, released, none
    message: str


class MaintenanceBlockService:
    """Service for managing automated room blocks from maintenance"""

    # Default OOO duration if not specified
    DEFAULT_OOO_DAYS = 3

    # Category-specific default durations
    CATEGORY_DURATIONS = {
        "plumbing": 2,
        "electrical": 1,
        "hvac": 2,
        "renovation": 14,
        "damage": 7,
        "inspection": 1,
        "deep_clean": 1,
        "pest_control": 2,
        "general": 2
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def handle_maintenance_ooo_change(
        self,
        maintenance_request_id: int,
        is_out_of_order: bool,
        estimated_completion: Optional[datetime] = None,
        ooo_category: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> MaintenanceBlockResult:
        """
        Handle changes to the is_out_of_order flag on a maintenance request.
        Auto-creates or releases room blocks as needed.
        """
        maintenance = await self.session.get(MaintenanceRequest, maintenance_request_id)
        if not maintenance:
            return MaintenanceBlockResult(
                success=False,
                room_block_id=None,
                maintenance_request_id=maintenance_request_id,
                affected_bookings=[],
                action_taken="none",
                message=f"Maintenance request {maintenance_request_id} not found"
            )

        if is_out_of_order:
            # Create or update room block
            return await self._create_or_update_block(
                maintenance,
                estimated_completion,
                ooo_category,
                user_id
            )
        else:
            # Release existing block if any
            return await self._release_block(maintenance, user_id)

    async def _create_or_update_block(
        self,
        maintenance: MaintenanceRequest,
        estimated_completion: Optional[datetime],
        ooo_category: Optional[str],
        user_id: Optional[int]
    ) -> MaintenanceBlockResult:
        """Create or update a room block for maintenance OOO"""

        # Room is required for blocking
        if not maintenance.room_id:
            return MaintenanceBlockResult(
                success=False,
                room_block_id=None,
                maintenance_request_id=maintenance.id,
                affected_bookings=[],
                action_taken="none",
                message="Cannot create block: No room associated with maintenance request"
            )

        # Get room details
        room = await self.session.get(Room, maintenance.room_id)
        if not room:
            return MaintenanceBlockResult(
                success=False,
                room_block_id=None,
                maintenance_request_id=maintenance.id,
                affected_bookings=[],
                action_taken="none",
                message="Room not found"
            )

        # Calculate block dates
        start_date = date.today()
        if estimated_completion:
            end_date = estimated_completion.date()
        else:
            # Use category-specific duration or default
            category = ooo_category or maintenance.category or "general"
            duration_days = self.CATEGORY_DURATIONS.get(category, self.DEFAULT_OOO_DAYS)
            end_date = start_date + timedelta(days=duration_days)

        # Update maintenance request with OOO details
        maintenance.is_out_of_order = True
        maintenance.estimated_completion = estimated_completion or datetime.combine(
            end_date, datetime.min.time()
        )
        maintenance.ooo_category = ooo_category or maintenance.category

        # Check for existing block
        existing_block = None
        if maintenance.room_block_id:
            existing_block = await self.session.get(RoomBlock, maintenance.room_block_id)

        if existing_block and existing_block.status == "active":
            # Update existing block
            existing_block.end_date = end_date
            existing_block.reason = self._generate_block_reason(maintenance)
            existing_block.notes = f"Updated from maintenance {maintenance.work_order_id}"
            existing_block.updated_at = datetime.utcnow()

            room_block = existing_block
            action_taken = "updated"
        else:
            # Create new block
            room_block = RoomBlock(
                room_type_id=room.room_type_id,
                room_id=room.id,
                start_date=start_date,
                end_date=end_date,
                block_type="maintenance",
                reason=self._generate_block_reason(maintenance),
                notes=f"Auto-created from maintenance {maintenance.work_order_id}",
                status="active",
                priority=self._get_block_priority(maintenance.priority),
                maintenance_request_id=maintenance.id,
                auto_created=True,
                created_by=user_id
            )
            self.session.add(room_block)
            await self.session.flush()
            action_taken = "created"

        # Link maintenance to block
        maintenance.room_block_id = room_block.id

        # Update room status
        room.status = "out_of_order"
        room.ooo_reason = maintenance.category
        room.ooo_category = ooo_category or maintenance.category
        room.ooo_start_date = datetime.utcnow()
        room.ooo_expected_end = maintenance.estimated_completion
        room.ooo_marked_by = user_id

        await self.session.flush()

        # Find affected bookings
        affected_bookings = await self._find_affected_bookings(
            room.id, start_date, end_date
        )

        logger.info(
            f"Room block {action_taken} for maintenance {maintenance.work_order_id}: "
            f"Room {room.number} blocked {start_date} to {end_date}. "
            f"{len(affected_bookings)} affected bookings."
        )

        return MaintenanceBlockResult(
            success=True,
            room_block_id=room_block.id,
            maintenance_request_id=maintenance.id,
            affected_bookings=affected_bookings,
            action_taken=action_taken,
            message=f"Room {room.number} blocked for maintenance until {end_date}. {len(affected_bookings)} booking(s) may need attention."
        )

    async def _release_block(
        self,
        maintenance: MaintenanceRequest,
        user_id: Optional[int]
    ) -> MaintenanceBlockResult:
        """Release room block when maintenance is completed"""

        # Update maintenance OOO status
        maintenance.is_out_of_order = False

        # Get and release associated block
        if maintenance.room_block_id:
            room_block = await self.session.get(RoomBlock, maintenance.room_block_id)
            if room_block and room_block.status == "active":
                room_block.status = "completed"
                room_block.auto_released = True
                room_block.notes = (room_block.notes or "") + f"\nAuto-released on {datetime.utcnow().isoformat()}"
                room_block.updated_at = datetime.utcnow()

                # Update room status back to available/clean
                if maintenance.room_id:
                    room = await self.session.get(Room, maintenance.room_id)
                    if room:
                        room.status = "available"
                        room.ooo_reason = None
                        room.ooo_category = None
                        room.ooo_start_date = None
                        room.ooo_expected_end = None
                        room.ooo_marked_by = None
                        room.updated_at = datetime.utcnow()

                await self.session.flush()

                logger.info(
                    f"Room block {room_block.id} released for completed maintenance {maintenance.work_order_id}"
                )

                return MaintenanceBlockResult(
                    success=True,
                    room_block_id=room_block.id,
                    maintenance_request_id=maintenance.id,
                    affected_bookings=[],
                    action_taken="released",
                    message=f"Room block released. Room is now available."
                )

        return MaintenanceBlockResult(
            success=True,
            room_block_id=None,
            maintenance_request_id=maintenance.id,
            affected_bookings=[],
            action_taken="none",
            message="No active block to release"
        )

    async def _find_affected_bookings(
        self,
        room_id: int,
        block_start: date,
        block_end: date
    ) -> List[AffectedBooking]:
        """Find bookings that overlap with the block dates"""
        affected = []

        # Find reservations with this specific room assigned that overlap
        result = await self.session.exec(
            select(Reservation).where(
                and_(
                    Reservation.room_id == room_id,
                    Reservation.status.in_(["booked", "confirmed"]),
                    Reservation.arrival_date < block_end,
                    Reservation.departure_date > block_start
                )
            )
        )
        reservations = result.all()

        for res in reservations:
            # Calculate overlap
            overlap_start = max(res.arrival_date, block_start)
            overlap_end = min(res.departure_date, block_end)

            # Get room number
            room_number = None
            if res.room_id:
                room = await self.session.get(Room, res.room_id)
                if room:
                    room_number = room.number

            # Get guest name (simplified - you might want to join with Guest table)
            guest_name = f"Guest (Reservation {res.id})"
            if res.guest_id:
                from app.models.reservations import Guest
                guest = await self.session.get(Guest, res.guest_id)
                if guest:
                    guest_name = f"{guest.first_name} {guest.last_name}"

            affected.append(AffectedBooking(
                reservation_id=res.id,
                confirmation_code=res.confirmation_code or "",
                guest_name=guest_name,
                arrival_date=res.arrival_date,
                departure_date=res.departure_date,
                room_id=res.room_id,
                room_number=room_number,
                status=res.status,
                overlap_start=overlap_start,
                overlap_end=overlap_end,
                requires_action=res.room_id == room_id  # Definitely needs action if specific room assigned
            ))

        return affected

    def _generate_block_reason(self, maintenance: MaintenanceRequest) -> str:
        """Generate a descriptive reason for the block"""
        parts = []

        if maintenance.category:
            parts.append(f"Maintenance ({maintenance.category})")
        else:
            parts.append("Maintenance")

        if maintenance.title:
            parts.append(f": {maintenance.title}")
        elif maintenance.issue:
            # Truncate long issues
            issue = maintenance.issue[:50] + "..." if len(maintenance.issue) > 50 else maintenance.issue
            parts.append(f": {issue}")

        return "".join(parts)

    def _get_block_priority(self, maintenance_priority: str) -> int:
        """Convert maintenance priority to block priority"""
        priority_map = {
            "emergency": 100,
            "high": 75,
            "medium": 50,
            "low": 25
        }
        return priority_map.get(maintenance_priority, 50)

    async def complete_maintenance_and_release(
        self,
        maintenance_request_id: int,
        resolution_notes: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> MaintenanceBlockResult:
        """
        Complete a maintenance request and auto-release the room block.
        Called when maintenance status changes to 'completed'.
        """
        maintenance = await self.session.get(MaintenanceRequest, maintenance_request_id)
        if not maintenance:
            return MaintenanceBlockResult(
                success=False,
                room_block_id=None,
                maintenance_request_id=maintenance_request_id,
                affected_bookings=[],
                action_taken="none",
                message=f"Maintenance request {maintenance_request_id} not found"
            )

        # Update maintenance status
        maintenance.status = "completed"
        maintenance.completed_at = datetime.utcnow()
        if resolution_notes:
            maintenance.resolution_notes = resolution_notes

        # Release block
        return await self._release_block(maintenance, user_id)

    async def get_active_maintenance_blocks(
        self,
        room_id: Optional[int] = None,
        room_type_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all active maintenance blocks with details"""
        query = select(RoomBlock).where(
            and_(
                RoomBlock.block_type == "maintenance",
                RoomBlock.status == "active",
                RoomBlock.auto_created == True
            )
        )

        if room_id:
            query = query.where(RoomBlock.room_id == room_id)
        if room_type_id:
            query = query.where(RoomBlock.room_type_id == room_type_id)

        result = await self.session.exec(query)
        blocks = result.all()

        block_details = []
        for block in blocks:
            # Get room details
            room_number = None
            room_type_name = None
            if block.room_id:
                room = await self.session.get(Room, block.room_id)
                if room:
                    room_number = room.number
                    if room.room_type_id:
                        room_type = await self.session.get(RoomType, room.room_type_id)
                        if room_type:
                            room_type_name = room_type.name

            # Get maintenance details
            maintenance_details = None
            if block.maintenance_request_id:
                maintenance = await self.session.get(MaintenanceRequest, block.maintenance_request_id)
                if maintenance:
                    maintenance_details = {
                        "work_order_id": maintenance.work_order_id,
                        "category": maintenance.category,
                        "priority": maintenance.priority,
                        "status": maintenance.status,
                        "assigned_to": maintenance.assigned_to,
                        "estimated_completion": maintenance.estimated_completion.isoformat() if maintenance.estimated_completion else None
                    }

            # Find affected bookings
            affected = await self._find_affected_bookings(
                block.room_id, block.start_date, block.end_date
            ) if block.room_id else []

            block_details.append({
                "block_id": block.id,
                "room_id": block.room_id,
                "room_number": room_number,
                "room_type_id": block.room_type_id,
                "room_type_name": room_type_name,
                "start_date": block.start_date.isoformat(),
                "end_date": block.end_date.isoformat(),
                "reason": block.reason,
                "notes": block.notes,
                "priority": block.priority,
                "maintenance": maintenance_details,
                "affected_bookings_count": len(affected),
                "affected_bookings": [
                    {
                        "reservation_id": ab.reservation_id,
                        "confirmation_code": ab.confirmation_code,
                        "guest_name": ab.guest_name,
                        "arrival_date": ab.arrival_date.isoformat(),
                        "departure_date": ab.departure_date.isoformat()
                    }
                    for ab in affected
                ],
                "created_at": block.created_at.isoformat()
            })

        return block_details

    async def extend_maintenance_block(
        self,
        maintenance_request_id: int,
        new_end_date: date,
        extension_reason: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> MaintenanceBlockResult:
        """Extend an existing maintenance block"""
        maintenance = await self.session.get(MaintenanceRequest, maintenance_request_id)
        if not maintenance:
            return MaintenanceBlockResult(
                success=False,
                room_block_id=None,
                maintenance_request_id=maintenance_request_id,
                affected_bookings=[],
                action_taken="none",
                message="Maintenance request not found"
            )

        if not maintenance.room_block_id:
            return MaintenanceBlockResult(
                success=False,
                room_block_id=None,
                maintenance_request_id=maintenance_request_id,
                affected_bookings=[],
                action_taken="none",
                message="No room block associated with this maintenance request"
            )

        room_block = await self.session.get(RoomBlock, maintenance.room_block_id)
        if not room_block or room_block.status != "active":
            return MaintenanceBlockResult(
                success=False,
                room_block_id=maintenance.room_block_id,
                maintenance_request_id=maintenance_request_id,
                affected_bookings=[],
                action_taken="none",
                message="Room block not found or not active"
            )

        old_end = room_block.end_date
        room_block.end_date = new_end_date
        room_block.notes = (room_block.notes or "") + f"\nExtended from {old_end} to {new_end_date}: {extension_reason or 'No reason provided'}"
        room_block.updated_at = datetime.utcnow()

        maintenance.estimated_completion = datetime.combine(new_end_date, datetime.min.time())

        # Update room OOO expected end
        if maintenance.room_id:
            room = await self.session.get(Room, maintenance.room_id)
            if room:
                room.ooo_expected_end = maintenance.estimated_completion

        await self.session.flush()

        # Find newly affected bookings
        affected_bookings = await self._find_affected_bookings(
            room_block.room_id, old_end, new_end_date
        ) if room_block.room_id else []

        logger.info(
            f"Extended maintenance block {room_block.id} from {old_end} to {new_end_date}. "
            f"{len(affected_bookings)} newly affected bookings."
        )

        return MaintenanceBlockResult(
            success=True,
            room_block_id=room_block.id,
            maintenance_request_id=maintenance_request_id,
            affected_bookings=affected_bookings,
            action_taken="updated",
            message=f"Block extended to {new_end_date}. {len(affected_bookings)} additional booking(s) may need attention."
        )


def get_maintenance_block_service(session: AsyncSession) -> MaintenanceBlockService:
    """Factory function to create MaintenanceBlockService instance"""
    return MaintenanceBlockService(session)
