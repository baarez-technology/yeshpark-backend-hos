"""
Maintenance Tools for AGI Guest Assistant
Handles all maintenance-related operations
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.maintenance_tools")


class MaintenanceTools:
    """Tools for maintenance service requests"""

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

    async def report_issue(
        self,
        room_number: str,
        issue_category: str,
        issue_description: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        urgency: str = "normal",
        location_in_room: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Report a maintenance issue.

        Args:
            room_number: Guest's room number
            issue_category: Category (plumbing, electrical, hvac, appliance, furniture, other)
            issue_description: Description of the issue
            guest_id: Guest ID
            booking_id: Booking ID
            urgency: Urgency level (low, normal, high, emergency)
            location_in_room: Specific location (bathroom, bedroom, balcony, etc.)

        Returns:
            Work order creation result
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            scheduling_service = get_scheduling_service(self.db)
            room_id = await self._get_room_id(room_number)

            # Map urgency to priority
            priority_map = {
                "emergency": "urgent",
                "high": "high",
                "normal": "normal",
                "low": "low"
            }
            priority = priority_map.get(urgency, "normal")

            # Build description
            description_parts = [
                f"Issue Category: {issue_category}",
                f"Description: {issue_description}"
            ]
            if location_in_room:
                description_parts.append(f"Location: {location_in_room}")

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="maintenance",
                title=f"Maintenance - {issue_category.title()} Issue - Room {room_number}",
                description="\n".join(description_parts),
                priority=priority,
                room_number=room_number,
                room_id=room_id,
                booking_id=booking_id,
                guest_id=guest_id
            )

            estimated_times = {
                "urgent": 15,
                "high": 30,
                "normal": 60,
                "low": 120
            }

            return {
                "success": True,
                "task_id": task.id if task else None,
                "work_order_id": f"WO-{task.id}" if task else None,
                "task_type": "maintenance",
                "issue_category": issue_category,
                "room_number": room_number,
                "assigned_technician": staff.staff_name if staff else None,
                "estimated_response_minutes": estimated_times.get(priority, 60),
                "priority": priority,
                "status": "reported",
                "message": f"Your maintenance issue has been reported. {'Our technician ' + staff.staff_name + ' will arrive' if staff else 'A technician will arrive'} within {estimated_times.get(priority, 60)} minutes."
            }

        except Exception as e:
            logger.error(f"Error creating maintenance request: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to report maintenance issue. Please contact the front desk immediately."
            }

    async def report_hvac_issue(
        self,
        room_number: str,
        issue_type: str,
        current_temp: Optional[float] = None,
        desired_temp: Optional[float] = None,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Report HVAC (heating/cooling) issue.

        Args:
            room_number: Guest's room number
            issue_type: Type (too_hot, too_cold, not_working, noisy, thermostat_issue)
            current_temp: Current room temperature (if known)
            desired_temp: Desired temperature
            guest_id: Guest ID
            booking_id: Booking ID

        Returns:
            Work order creation result
        """
        description = f"HVAC Issue: {issue_type.replace('_', ' ').title()}"
        if current_temp:
            description += f"\nCurrent temperature: {current_temp}°F"
        if desired_temp:
            description += f"\nDesired temperature: {desired_temp}°F"

        # HVAC issues are typically high priority for guest comfort
        priority = "high" if issue_type in ["not_working", "too_hot", "too_cold"] else "normal"

        return await self.report_issue(
            room_number=room_number,
            issue_category="hvac",
            issue_description=description,
            guest_id=guest_id,
            booking_id=booking_id,
            urgency=priority
        )

    async def report_plumbing_issue(
        self,
        room_number: str,
        issue_type: str,
        location: str = "bathroom",
        is_leaking: bool = False,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Report plumbing issue.

        Args:
            room_number: Guest's room number
            issue_type: Type (clogged_drain, low_pressure, no_hot_water, leaking, toilet_issue)
            location: Location (bathroom, kitchen, etc.)
            is_leaking: Whether there's active leaking
            guest_id: Guest ID
            booking_id: Booking ID

        Returns:
            Work order creation result
        """
        description = f"Plumbing Issue: {issue_type.replace('_', ' ').title()}"
        description += f"\nLocation: {location}"
        if is_leaking:
            description += "\nACTIVE LEAK - URGENT ATTENTION REQUIRED"

        # Active leaks are emergency priority
        urgency = "emergency" if is_leaking else ("high" if issue_type in ["no_hot_water", "clogged_drain"] else "normal")

        return await self.report_issue(
            room_number=room_number,
            issue_category="plumbing",
            issue_description=description,
            guest_id=guest_id,
            booking_id=booking_id,
            urgency=urgency,
            location_in_room=location
        )

    async def report_electrical_issue(
        self,
        room_number: str,
        issue_type: str,
        affected_items: Optional[List[str]] = None,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Report electrical issue.

        Args:
            room_number: Guest's room number
            issue_type: Type (no_power, outlet_not_working, light_not_working, sparking, flickering)
            affected_items: List of affected items/areas
            guest_id: Guest ID
            booking_id: Booking ID

        Returns:
            Work order creation result
        """
        description = f"Electrical Issue: {issue_type.replace('_', ' ').title()}"
        if affected_items:
            description += f"\nAffected items/areas: {', '.join(affected_items)}"

        # Sparking is emergency, power issues are high priority
        urgency = "emergency" if issue_type == "sparking" else ("high" if issue_type == "no_power" else "normal")

        return await self.report_issue(
            room_number=room_number,
            issue_category="electrical",
            issue_description=description,
            guest_id=guest_id,
            booking_id=booking_id,
            urgency=urgency
        )

    async def report_wifi_issue(
        self,
        room_number: str,
        issue_type: str,
        devices_affected: Optional[int] = None,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Report WiFi/Internet issue.

        Args:
            room_number: Guest's room number
            issue_type: Type (no_connection, slow_speed, intermittent, cant_connect)
            devices_affected: Number of devices affected
            guest_id: Guest ID
            booking_id: Booking ID

        Returns:
            Troubleshooting steps and work order if needed
        """
        # First, provide troubleshooting steps
        troubleshooting = [
            "1. Try forgetting the network and reconnecting",
            "2. Ensure you're connected to 'Glimmora_Guest' network",
            "3. Restart your device",
            "4. Move closer to the room's access point"
        ]

        # Also create a maintenance ticket for IT
        result = await self.report_issue(
            room_number=room_number,
            issue_category="wifi",
            issue_description=f"WiFi Issue: {issue_type.replace('_', ' ').title()}\nDevices affected: {devices_affected or 'Unknown'}",
            guest_id=guest_id,
            booking_id=booking_id,
            urgency="high"  # WiFi issues impact guest experience
        )

        result["troubleshooting_steps"] = troubleshooting
        result["wifi_network"] = "Glimmora_Guest"
        result["support_extension"] = "8888"

        return result

    async def report_appliance_issue(
        self,
        room_number: str,
        appliance: str,
        issue_description: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Report appliance issue (TV, minibar, safe, coffee maker, etc.)

        Args:
            room_number: Guest's room number
            appliance: Appliance name
            issue_description: Description of the issue
            guest_id: Guest ID
            booking_id: Booking ID

        Returns:
            Work order creation result
        """
        return await self.report_issue(
            room_number=room_number,
            issue_category="appliance",
            issue_description=f"Appliance: {appliance}\nIssue: {issue_description}",
            guest_id=guest_id,
            booking_id=booking_id,
            urgency="normal"
        )

    async def get_maintenance_status(
        self,
        room_number: str,
        task_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get status of maintenance requests for a room.

        Args:
            room_number: Guest's room number
            task_id: Specific task ID (optional)

        Returns:
            Status information
        """
        from app.models.guest_chat import StaffTask
        from app.models.user import User

        try:
            query = select(StaffTask).where(
                and_(
                    StaffTask.room_number == room_number,
                    StaffTask.task_type == "maintenance"
                )
            )
            if task_id:
                query = query.where(StaffTask.id == task_id)

            query = query.order_by(StaffTask.created_at.desc()).limit(10)

            result = await self.db.execute(query)
            tasks = result.scalars().all()

            maintenance_requests = []
            for task in tasks:
                # Get technician name
                technician_name = None
                if task.assigned_to:
                    user_result = await self.db.execute(
                        select(User).where(User.id == task.assigned_to)
                    )
                    user = user_result.scalars().first()
                    if user:
                        technician_name = user.full_name or user.email

                maintenance_requests.append({
                    "task_id": task.id,
                    "work_order_id": f"WO-{task.id}",
                    "title": task.title,
                    "description": task.description,
                    "status": task.status,
                    "priority": task.priority,
                    "assigned_technician": technician_name,
                    "created_at": task.created_at.isoformat(),
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None
                })

            return {
                "success": True,
                "room_number": room_number,
                "maintenance_requests": maintenance_requests,
                "total_count": len(maintenance_requests),
                "message": f"Found {len(maintenance_requests)} maintenance request(s) for room {room_number}." if maintenance_requests else "No maintenance requests found for this room."
            }

        except Exception as e:
            logger.error(f"Error getting maintenance status: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to retrieve maintenance status."
            }

    async def report_emergency(
        self,
        room_number: str,
        emergency_type: str,
        description: str,
        guest_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Report an emergency situation.

        Args:
            room_number: Guest's room number
            emergency_type: Type (fire, flood, gas_leak, medical, security)
            description: Description of emergency
            guest_id: Guest ID

        Returns:
            Emergency response information
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            scheduling_service = get_scheduling_service(self.db)
            room_id = await self._get_room_id(room_number)

            # Create urgent task
            task, staff = await scheduling_service.create_and_assign_task(
                task_type="maintenance",
                title=f"EMERGENCY - {emergency_type.upper()} - Room {room_number}",
                description=f"EMERGENCY ALERT\nType: {emergency_type}\nDescription: {description}\nIMMMEDIATE RESPONSE REQUIRED",
                priority="urgent",
                room_number=room_number,
                room_id=room_id,
                guest_id=guest_id
            )

            emergency_contacts = {
                "fire": {"action": "Evacuate via nearest stairwell. Do not use elevators.", "number": "911"},
                "flood": {"action": "Turn off water at the main valve if safe. Evacuate if necessary.", "number": "Front Desk: 0"},
                "gas_leak": {"action": "Do not use electrical switches. Open windows. Evacuate immediately.", "number": "911"},
                "medical": {"action": "Our staff is on the way. Stay calm.", "number": "911"},
                "security": {"action": "Lock your door. Our security team is en route.", "number": "Security: 9999"}
            }

            contact = emergency_contacts.get(emergency_type, {"action": "Stay calm. Help is on the way.", "number": "Front Desk: 0"})

            return {
                "success": True,
                "task_id": task.id if task else None,
                "emergency_type": emergency_type,
                "room_number": room_number,
                "status": "emergency_dispatched",
                "immediate_action": contact["action"],
                "emergency_number": contact["number"],
                "message": f"EMERGENCY REPORTED. {contact['action']} Help is being dispatched to room {room_number} immediately. Emergency contact: {contact['number']}"
            }

        except Exception as e:
            logger.error(f"Error reporting emergency: {e}")
            return {
                "success": False,
                "error": str(e),
                "emergency_number": "911",
                "front_desk": "0",
                "message": "Please call 911 immediately for emergencies or dial 0 for the front desk."
            }


def get_maintenance_tools(db: AsyncSession) -> MaintenanceTools:
    """Factory function to create MaintenanceTools instance"""
    return MaintenanceTools(db)
