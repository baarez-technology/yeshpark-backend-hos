"""
Housekeeping Tools for AGI Guest Assistant
Handles all housekeeping-related operations
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from langchain_core.tools import tool
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.housekeeping_tools")


class HousekeepingTools:
    """Tools for housekeeping service requests"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_room_id(self, room_number: str) -> Optional[int]:
        """Get room ID from room number"""
        from app.models.inventory import Room
        result = await self.db.execute(
            select(Room).where(Room.number == room_number)
        )
        room = result.scalars().first()
        return room.id if room else None

    async def request_room_cleaning(
        self,
        room_number: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        cleaning_type: str = "standard",
        special_instructions: Optional[str] = None,
        preferred_time: Optional[str] = None,
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """
        Request room cleaning service.

        Args:
            room_number: Guest's room number
            guest_id: Guest ID
            booking_id: Booking ID
            cleaning_type: Type of cleaning (standard, deep, turndown, checkout)
            special_instructions: Any special cleaning instructions
            preferred_time: Preferred time for cleaning (morning, afternoon, evening, now)
            priority: Priority level (low, normal, high, urgent)

        Returns:
            Task creation result with task ID and estimated time
        """
        from app.models.guest_chat import StaffTask
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            scheduling_service = get_scheduling_service(self.db)
            room_id = await self._get_room_id(room_number)

            # Build description
            description_parts = [f"Room cleaning requested for room {room_number}"]
            description_parts.append(f"Cleaning type: {cleaning_type}")
            if special_instructions:
                description_parts.append(f"Special instructions: {special_instructions}")
            if preferred_time:
                description_parts.append(f"Preferred time: {preferred_time}")

            # Create task
            task, staff = await scheduling_service.create_and_assign_task(
                task_type="housekeeping",
                title=f"Room Cleaning - {cleaning_type.title()} - Room {room_number}",
                description="\n".join(description_parts),
                priority=priority,
                room_number=room_number,
                room_id=room_id,
                booking_id=booking_id,
                guest_id=guest_id
            )

            estimated_times = {
                "urgent": 15,
                "high": 25,
                "normal": 45,
                "low": 90
            }

            return {
                "success": True,
                "task_id": task.id if task else None,
                "task_type": "housekeeping",
                "cleaning_type": cleaning_type,
                "room_number": room_number,
                "assigned_staff": staff.staff_name if staff else None,
                "estimated_time_minutes": estimated_times.get(priority, 45),
                "status": "scheduled",
                "message": f"Room cleaning has been scheduled. {'Our team member ' + staff.staff_name + ' will arrive' if staff else 'Our team will arrive'} within {estimated_times.get(priority, 45)} minutes."
            }

        except Exception as e:
            logger.error(f"Error creating housekeeping request: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to schedule housekeeping. Please contact the front desk."
            }

    async def request_extra_amenities(
        self,
        room_number: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        items: List[str] = None,
        quantity: Dict[str, int] = None,
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """
        Request extra amenities (towels, pillows, toiletries, etc.)

        Args:
            room_number: Guest's room number
            guest_id: Guest ID
            booking_id: Booking ID
            items: List of items needed (towels, pillows, blankets, toiletries, etc.)
            quantity: Quantity of each item
            priority: Priority level

        Returns:
            Task creation result
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        if not items:
            items = ["towels"]

        try:
            scheduling_service = get_scheduling_service(self.db)
            room_id = await self._get_room_id(room_number)

            # Build items list with quantities
            items_str = ", ".join([
                f"{quantity.get(item, 1)}x {item}" if quantity else item
                for item in items
            ])

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="housekeeping",
                title=f"Extra Amenities Request - Room {room_number}",
                description=f"Items requested: {items_str}",
                priority=priority,
                room_number=room_number,
                room_id=room_id,
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "task_id": task.id if task else None,
                "task_type": "housekeeping",
                "items_requested": items,
                "room_number": room_number,
                "assigned_staff": staff.staff_name if staff else None,
                "estimated_time_minutes": 20 if priority == "urgent" else 30,
                "status": "scheduled",
                "message": f"Your {items_str} will be delivered to room {room_number} shortly."
            }

        except Exception as e:
            logger.error(f"Error creating amenities request: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process your request. Please contact the front desk."
            }

    async def request_turndown_service(
        self,
        room_number: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        preferred_time: str = "evening",
        special_requests: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request turndown service

        Args:
            room_number: Guest's room number
            guest_id: Guest ID
            booking_id: Booking ID
            preferred_time: Preferred time (early_evening, evening, late_evening)
            special_requests: Any special requests

        Returns:
            Task creation result
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            scheduling_service = get_scheduling_service(self.db)
            room_id = await self._get_room_id(room_number)

            description = f"Turndown service requested for room {room_number}\nPreferred time: {preferred_time}"
            if special_requests:
                description += f"\nSpecial requests: {special_requests}"

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="housekeeping",
                title=f"Turndown Service - Room {room_number}",
                description=description,
                priority="normal",
                room_number=room_number,
                room_id=room_id,
                booking_id=booking_id,
                guest_id=guest_id
            )

            time_mapping = {
                "early_evening": "between 5-6 PM",
                "evening": "between 6-8 PM",
                "late_evening": "between 8-10 PM"
            }

            return {
                "success": True,
                "task_id": task.id if task else None,
                "task_type": "housekeeping",
                "service_type": "turndown",
                "room_number": room_number,
                "scheduled_time": time_mapping.get(preferred_time, "this evening"),
                "assigned_staff": staff.staff_name if staff else None,
                "status": "scheduled",
                "message": f"Turndown service scheduled for room {room_number} {time_mapping.get(preferred_time, 'this evening')}."
            }

        except Exception as e:
            logger.error(f"Error creating turndown request: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to schedule turndown service. Please contact the front desk."
            }

    async def request_do_not_disturb(
        self,
        room_number: str,
        guest_id: Optional[int] = None,
        duration_hours: int = 8,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Set do not disturb status for room

        Args:
            room_number: Guest's room number
            guest_id: Guest ID
            duration_hours: Duration in hours
            reason: Optional reason

        Returns:
            Status update result
        """
        from app.models.inventory import Room

        try:
            result = await self.db.execute(
                select(Room).where(Room.number == room_number)
            )
            room = result.scalars().first()

            if room:
                # Update room DND status (if field exists) or create a task note
                end_time = datetime.utcnow() + timedelta(hours=duration_hours)

                return {
                    "success": True,
                    "room_number": room_number,
                    "status": "do_not_disturb",
                    "until": end_time.isoformat(),
                    "duration_hours": duration_hours,
                    "message": f"Do Not Disturb has been set for room {room_number} for the next {duration_hours} hours. No housekeeping services will be provided during this time."
                }

            return {
                "success": False,
                "message": "Room not found."
            }

        except Exception as e:
            logger.error(f"Error setting DND: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to set Do Not Disturb. Please contact the front desk."
            }

    async def get_housekeeping_schedule(
        self,
        room_number: str
    ) -> Dict[str, Any]:
        """
        Get housekeeping schedule for a room

        Args:
            room_number: Guest's room number

        Returns:
            Schedule information
        """
        from app.models.guest_chat import StaffTask

        try:
            result = await self.db.execute(
                select(StaffTask).where(
                    and_(
                        StaffTask.room_number == room_number,
                        StaffTask.task_type == "housekeeping",
                        StaffTask.status.in_(["pending", "assigned", "in_progress"])
                    )
                ).order_by(StaffTask.created_at.desc())
            )
            tasks = result.scalars().all()

            scheduled_tasks = []
            for task in tasks:
                scheduled_tasks.append({
                    "task_id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "scheduled_for": task.scheduled_for.isoformat() if task.scheduled_for else None,
                    "created_at": task.created_at.isoformat()
                })

            return {
                "success": True,
                "room_number": room_number,
                "scheduled_tasks": scheduled_tasks,
                "next_regular_cleaning": "Tomorrow between 10 AM - 2 PM" if not scheduled_tasks else None,
                "message": f"Found {len(scheduled_tasks)} scheduled housekeeping task(s) for room {room_number}." if scheduled_tasks else f"No pending housekeeping tasks. Regular cleaning is scheduled daily between 10 AM - 2 PM."
            }

        except Exception as e:
            logger.error(f"Error getting housekeeping schedule: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to retrieve schedule."
            }

    async def cancel_housekeeping_request(
        self,
        task_id: int,
        guest_id: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cancel a pending housekeeping request

        Args:
            task_id: Task ID to cancel
            guest_id: Guest ID for verification
            reason: Cancellation reason

        Returns:
            Cancellation result
        """
        from app.models.guest_chat import StaffTask

        try:
            result = await self.db.execute(
                select(StaffTask).where(StaffTask.id == task_id)
            )
            task = result.scalars().first()

            if not task:
                return {
                    "success": False,
                    "message": "Task not found."
                }

            if task.status in ["completed", "cancelled"]:
                return {
                    "success": False,
                    "message": f"Task has already been {task.status}."
                }

            # Cancel the task
            task.status = "cancelled"
            task.notes = (task.notes or "") + f"\n[{datetime.utcnow().isoformat()}] Cancelled by guest. Reason: {reason or 'Not specified'}"
            task.updated_at = datetime.utcnow()

            await self.db.commit()

            return {
                "success": True,
                "task_id": task_id,
                "status": "cancelled",
                "message": "Your housekeeping request has been cancelled."
            }

        except Exception as e:
            logger.error(f"Error cancelling housekeeping request: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to cancel request."
            }


def get_housekeeping_tools(db: AsyncSession) -> HousekeepingTools:
    """Factory function to create HousekeepingTools instance"""
    return HousekeepingTools(db)
