"""
Action Executor for Admin AI
Handles CRUD operations and automation actions
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .security import TablePermissions

logger = logging.getLogger(__name__)

# Module-level pending actions cache (persists across requests)
_GLOBAL_PENDING_ACTIONS: Dict[str, "PendingAction"] = {}


class ActionType(str, Enum):
    """Types of actions the AI can perform"""
    CREATE_TASK = "create_task"
    CREATE_MAINTENANCE = "create_maintenance"
    CREATE_BOOKING = "create_booking"
    CREATE_GUEST_NOTE = "create_guest_note"
    UPDATE_BOOKING_STATUS = "update_booking_status"
    UPDATE_ROOM_STATUS = "update_room_status"
    UPDATE_TASK_STATUS = "update_task_status"
    UPDATE_GUEST = "update_guest"
    ASSIGN_TASK = "assign_task"
    ASSIGN_ROOM = "assign_room"
    TRANSFER_ROOM = "transfer_room"
    SEND_EMAIL = "send_email"
    DRAFT_EMAIL = "draft_email"
    GENERATE_REPORT = "generate_report"
    CREATE_NOTE = "create_note"
    SEND_NOTIFICATION = "send_notification"
    GENERAL = "general"


@dataclass
class ActionRequest:
    """Request for an action to be executed"""
    action_type: ActionType
    params: Dict[str, Any]
    requires_confirmation: bool = True
    confirmation_message: Optional[str] = None


@dataclass
class ActionResult:
    """Result of an action execution"""
    success: bool
    action_type: ActionType
    action_id: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class PendingAction:
    """An action waiting for user confirmation"""
    action_id: str
    action_type: ActionType
    params: Dict[str, Any]
    description: str
    preview: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None


class ActionValidator:
    """Validates actions before execution"""

    # Allowed status transitions for bookings
    BOOKING_STATUS_TRANSITIONS = {
        "pending": ["confirmed", "cancelled"],
        "confirmed": ["checked_in", "cancelled", "no_show"],
        "checked_in": ["checked_out"],
        "checked_out": [],
        "cancelled": [],
        "no_show": [],
    }

    # Allowed room statuses
    ROOM_STATUSES = [
        "available", "occupied", "cleaning", "dirty", "clean",
        "inspected", "maintenance", "out_of_service"
    ]

    # Task statuses
    TASK_STATUSES = ["pending", "assigned", "in_progress", "completed", "cancelled"]

    # Maintenance priorities
    MAINTENANCE_PRIORITIES = ["low", "medium", "high", "emergency"]

    # Housekeeping task types (including common aliases)
    HOUSEKEEPING_TYPES = [
        "daily_cleaning", "checkout_cleaning", "deep_clean",
        "turndown", "inspection", "laundry", "amenity_restock",
        # Common aliases that map to daily_cleaning
        "clean", "cleaning", "room_clean", "standard_cleaning"
    ]

    # Task type normalization - map user-friendly terms to database values
    TASK_TYPE_MAP = {
        "clean": "daily_cleaning",
        "cleaning": "daily_cleaning",
        "room_clean": "daily_cleaning",
        "standard_cleaning": "daily_cleaning",
        "deep": "deep_clean",
        "deep_cleaning": "deep_clean",
        "checkout": "checkout_cleaning",
        "check_out": "checkout_cleaning",
        "turndown_service": "turndown",
        "inspect": "inspection",
        "restock": "amenity_restock",
    }

    def validate_action(self, action: ActionRequest, current_data: Optional[Dict] = None) -> Tuple[bool, Optional[str]]:
        """
        Validate an action request

        Args:
            action: The action to validate
            current_data: Current state data for transition validation

        Returns:
            Tuple of (is_valid, error_message)
        """
        if action.action_type == ActionType.UPDATE_BOOKING_STATUS:
            new_status = action.params.get("status")
            if new_status not in ["confirmed", "checked_in", "checked_out", "cancelled", "no_show"]:
                return False, f"Invalid booking status: {new_status}"

            if current_data:
                current_status = current_data.get("status")
                if current_status and new_status not in self.BOOKING_STATUS_TRANSITIONS.get(current_status, []):
                    return False, f"Cannot transition from {current_status} to {new_status}"

        elif action.action_type == ActionType.UPDATE_ROOM_STATUS:
            new_status = action.params.get("status")
            if new_status not in self.ROOM_STATUSES:
                return False, f"Invalid room status: {new_status}"

        elif action.action_type == ActionType.UPDATE_TASK_STATUS:
            new_status = action.params.get("status")
            if new_status not in self.TASK_STATUSES:
                return False, f"Invalid task status: {new_status}"

        elif action.action_type == ActionType.CREATE_TASK:
            task_type = action.params.get("task_type")
            if task_type:
                # Normalize task type using mapping
                normalized_type = self.TASK_TYPE_MAP.get(task_type.lower(), task_type.lower())
                if normalized_type not in self.HOUSEKEEPING_TYPES:
                    return False, f"Invalid housekeeping task type: {task_type}"
                # Update the action params with normalized type
                action.params["task_type"] = normalized_type

        elif action.action_type == ActionType.CREATE_MAINTENANCE:
            priority = action.params.get("priority", "medium")
            if priority not in self.MAINTENANCE_PRIORITIES:
                return False, f"Invalid maintenance priority: {priority}"

        return True, None


class ActionExecutor:
    """Executes approved actions"""

    # Actions that require confirmation
    CONFIRMATION_REQUIRED = {
        ActionType.SEND_EMAIL,
        ActionType.UPDATE_BOOKING_STATUS,
        ActionType.CREATE_MAINTENANCE,
    }

    def __init__(self, session: AsyncSession):
        self.session = session
        self.validator = ActionValidator()
        self.permissions = TablePermissions()
        # Use global cache for pending actions (persists across requests)
        global _GLOBAL_PENDING_ACTIONS
        self._pending_actions = _GLOBAL_PENDING_ACTIONS

    def prepare_action(self, action: ActionRequest, user_id: int) -> PendingAction:
        """
        Prepare an action for confirmation

        Args:
            action: The action request
            user_id: User requesting the action

        Returns:
            PendingAction for confirmation
        """
        action_id = str(uuid.uuid4())[:8]

        description = self._generate_action_description(action)
        preview = self._generate_action_preview(action)

        pending = PendingAction(
            action_id=action_id,
            action_type=action.action_type,
            params={**action.params, "user_id": user_id},
            description=description,
            preview=preview
        )

        self._pending_actions[action_id] = pending
        return pending

    def create_pending_action(
        self,
        action_type: ActionType,
        description: str,
        params: Dict[str, Any],
        requires_confirmation: bool = True
    ) -> PendingAction:
        """
        Create a pending action directly without ActionRequest wrapper.

        Args:
            action_type: Type of action to perform
            description: Human-readable description
            params: Action parameters
            requires_confirmation: Whether confirmation is required

        Returns:
            PendingAction for confirmation
        """
        action_id = str(uuid.uuid4())[:8]

        pending = PendingAction(
            action_id=action_id,
            action_type=action_type,
            params=params,
            description=description,
            preview={
                "action_type": action_type.value,
                "params": params,
            }
        )

        self._pending_actions[action_id] = pending
        return pending

    def _generate_action_description(self, action: ActionRequest) -> str:
        """Generate human-readable description of an action"""
        params = action.params

        descriptions = {
            ActionType.CREATE_TASK: lambda: f"Create {params.get('task_type', 'housekeeping')} task for room {params.get('room_id')}",
            ActionType.CREATE_MAINTENANCE: lambda: f"Create {params.get('priority', 'medium')} priority maintenance request for room {params.get('room_id')}: {params.get('issue', 'Issue')}",
            ActionType.UPDATE_BOOKING_STATUS: lambda: f"Update booking {params.get('booking_id')} status to {params.get('status')}",
            ActionType.UPDATE_ROOM_STATUS: lambda: f"Update room {params.get('room_id')} status to {params.get('status')}",
            ActionType.UPDATE_TASK_STATUS: lambda: f"Update task {params.get('task_id')} status to {params.get('status')}",
            ActionType.ASSIGN_TASK: lambda: f"Assign task {params.get('task_id')} to staff {params.get('staff_id')}",
            ActionType.SEND_EMAIL: lambda: f"Send {params.get('template', 'email')} to {params.get('recipient_email')}",
            ActionType.DRAFT_EMAIL: lambda: f"Draft {params.get('template', 'email')} for {params.get('recipient_email')}",
            ActionType.GENERATE_REPORT: lambda: f"Generate {params.get('report_type', 'report')} report",
            ActionType.CREATE_NOTE: lambda: f"Add note to {params.get('entity_type')} {params.get('entity_id')}",
            ActionType.SEND_NOTIFICATION: lambda: f"Send notification to {params.get('recipient_type')}",
            ActionType.ASSIGN_ROOM: lambda: f"Assign room {params.get('room_number', params.get('room_id'))} to booking {params.get('booking_id')}",
            ActionType.TRANSFER_ROOM: lambda: f"Transfer guest from room {params.get('from_room_number')} to room {params.get('to_room_number')}",
            ActionType.CREATE_GUEST_NOTE: lambda: f"Add note to guest {params.get('guest_id')}",
        }

        generator = descriptions.get(action.action_type)
        if generator:
            try:
                return generator()
            except:
                pass

        return f"Execute {action.action_type.value}"

    def _generate_action_preview(self, action: ActionRequest) -> Optional[Dict]:
        """Generate preview data for an action"""
        return {
            "action_type": action.action_type.value,
            "params": action.params,
        }

    async def execute(self, action: ActionRequest, user_id: int) -> ActionResult:
        """
        Execute an action

        Args:
            action: The action to execute
            user_id: User executing the action

        Returns:
            ActionResult with execution details
        """
        action_id = str(uuid.uuid4())[:8]

        # Validate action
        is_valid, error = self.validator.validate_action(action)
        if not is_valid:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                action_id=action_id,
                message="Action validation failed",
                error=error
            )

        try:
            if action.action_type == ActionType.CREATE_TASK:
                return await self._create_housekeeping_task(action, user_id, action_id)

            elif action.action_type == ActionType.CREATE_MAINTENANCE:
                return await self._create_maintenance_request(action, user_id, action_id)

            elif action.action_type == ActionType.UPDATE_BOOKING_STATUS:
                return await self._update_booking_status(action, user_id, action_id)

            elif action.action_type == ActionType.UPDATE_ROOM_STATUS:
                return await self._update_room_status(action, user_id, action_id)

            elif action.action_type == ActionType.UPDATE_TASK_STATUS:
                return await self._update_task_status(action, user_id, action_id)

            elif action.action_type == ActionType.ASSIGN_TASK:
                return await self._assign_task(action, user_id, action_id)

            elif action.action_type == ActionType.CREATE_NOTE:
                return await self._create_note(action, user_id, action_id)

            elif action.action_type == ActionType.CREATE_BOOKING:
                return await self._create_booking(action, user_id, action_id)

            elif action.action_type == ActionType.SEND_NOTIFICATION:
                return await self._send_notification(action, user_id, action_id)

            elif action.action_type == ActionType.ASSIGN_ROOM:
                return await self._assign_room(action, user_id, action_id)

            elif action.action_type == ActionType.TRANSFER_ROOM:
                return await self._transfer_room(action, user_id, action_id)

            elif action.action_type == ActionType.CREATE_GUEST_NOTE:
                return await self._create_guest_note(action, user_id, action_id)

            elif action.action_type == ActionType.UPDATE_GUEST:
                return await self._update_guest(action, user_id, action_id)

            else:
                return ActionResult(
                    success=False,
                    action_type=action.action_type,
                    action_id=action_id,
                    message="Action type not implemented",
                    error=f"Unknown action type: {action.action_type}"
                )

        except Exception as e:
            logger.error(f"Action execution error: {e}", exc_info=True)
            return ActionResult(
                success=False,
                action_type=action.action_type,
                action_id=action_id,
                message="Action execution failed",
                error=str(e)
            )

    async def execute_confirmed(self, action_id: str, user_id: int) -> ActionResult:
        """
        Execute a previously prepared action after confirmation

        Args:
            action_id: ID of the pending action
            user_id: User confirming the action

        Returns:
            ActionResult with execution details
        """
        pending = self._pending_actions.pop(action_id, None)

        if not pending:
            return ActionResult(
                success=False,
                action_type=ActionType.CREATE_TASK,  # Default
                action_id=action_id,
                message="Action not found or expired",
                error="Invalid action ID"
            )

        # Recreate action request
        action = ActionRequest(
            action_type=pending.action_type,
            params=pending.params,
            requires_confirmation=False
        )

        return await self.execute(action, user_id)

    async def _create_housekeeping_task(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Create a housekeeping task"""
        params = action.params

        now = datetime.utcnow()
        query = text("""
            INSERT INTO housekeeping_tasks
            (room_id, task_type, priority, status, notes, created_by, force_assigned, created_at, updated_at)
            VALUES (:room_id, :task_type, :priority, 'pending', :notes, :created_by, :force_assigned, :created_at, :updated_at)
        """)

        await self.session.execute(query, {
            "room_id": params.get("room_id"),
            "task_type": params.get("task_type", "daily_cleaning"),
            "priority": params.get("priority", "medium"),
            "notes": params.get("notes", "Created by Admin AI"),
            "created_by": user_id,
            "force_assigned": False,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })
        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Housekeeping task created for room {params.get('room_id')}",
            data={"room_id": params.get("room_id"), "task_type": params.get("task_type")}
        )

    async def _create_maintenance_request(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Create a maintenance request"""
        params = action.params

        # Generate work_order_id in format WO-YYYYMMDD-XXXX
        now = datetime.utcnow()
        date_str = now.strftime("%Y%m%d")

        # Get the next sequence number for today
        count_query = text("""
            SELECT COUNT(*) FROM maintenancerequest
            WHERE work_order_id LIKE :pattern
        """)
        result = await self.session.execute(count_query, {"pattern": f"WO-{date_str}-%"})
        count = result.scalar() or 0
        work_order_id = f"WO-{date_str}-{count:04d}"

        query = text("""
            INSERT INTO maintenancerequest
            (work_order_id, room_id, category, issue, description, priority, status, reported_by, reported_at, created_at, updated_at, is_out_of_order, requires_parts, parts_ordered, is_preventive)
            VALUES (:work_order_id, :room_id, :category, :issue, :description, :priority, 'open', :reported_by, :reported_at, :created_at, :updated_at, 0, 0, 0, 0)
        """)

        await self.session.execute(query, {
            "work_order_id": work_order_id,
            "room_id": params.get("room_id"),
            "category": params.get("category", "general"),
            "issue": params.get("issue", "Maintenance required"),
            "description": params.get("description", "Created by Admin AI"),
            "priority": params.get("priority", "medium"),
            "reported_by": user_id,
            "reported_at": now.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })
        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Maintenance request created for room {params.get('room_id')}",
            data={"room_id": params.get("room_id"), "issue": params.get("issue")}
        )

    async def _update_booking_status(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Update booking status"""
        params = action.params
        booking_id = params.get("booking_id")
        new_status = params.get("status")

        query = text("""
            UPDATE bookings
            SET status = :status, updated_at = :updated_at
            WHERE id = :booking_id
        """)

        await self.session.execute(query, {
            "booking_id": booking_id,
            "status": new_status,
            "updated_at": datetime.utcnow().isoformat(),
        })
        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Booking {booking_id} status updated to {new_status}",
            data={"booking_id": booking_id, "status": new_status}
        )

    async def _update_room_status(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Update room status with OOO reason tracking"""
        params = action.params
        room_id = params.get("room_id")
        new_status = params.get("status")
        ooo_reason = params.get("ooo_reason")
        ooo_category = params.get("ooo_category")
        ooo_expected_end = params.get("ooo_expected_end")

        # Check if marking as out of order/service
        is_ooo = new_status in ["out_of_order", "out_of_service", "ooo", "maintenance"]

        if is_ooo and ooo_reason:
            query = text("""
                UPDATE rooms
                SET status = :status,
                    ooo_reason = :ooo_reason,
                    ooo_category = :ooo_category,
                    ooo_start_date = :ooo_start_date,
                    ooo_expected_end = :ooo_expected_end,
                    ooo_marked_by = :marked_by,
                    updated_at = :updated_at
                WHERE id = :room_id
            """)
            await self.session.execute(query, {
                "room_id": room_id,
                "status": new_status,
                "ooo_reason": ooo_reason,
                "ooo_category": ooo_category or "maintenance",
                "ooo_start_date": datetime.utcnow().isoformat(),
                "ooo_expected_end": ooo_expected_end,
                "marked_by": user_id,
                "updated_at": datetime.utcnow().isoformat(),
            })
        elif not is_ooo:
            # Clearing OOO status - reset OOO fields
            query = text("""
                UPDATE rooms
                SET status = :status,
                    ooo_reason = NULL,
                    ooo_category = NULL,
                    ooo_start_date = NULL,
                    ooo_expected_end = NULL,
                    ooo_marked_by = NULL,
                    updated_at = :updated_at
                WHERE id = :room_id
            """)
            await self.session.execute(query, {
                "room_id": room_id,
                "status": new_status,
                "updated_at": datetime.utcnow().isoformat(),
            })
        else:
            query = text("""
                UPDATE rooms
                SET status = :status, updated_at = :updated_at
                WHERE id = :room_id
            """)
            await self.session.execute(query, {
                "room_id": room_id,
                "status": new_status,
                "updated_at": datetime.utcnow().isoformat(),
            })

        await self.session.commit()

        message = f"Room {room_id} status updated to {new_status}"
        if ooo_reason:
            message += f" (Reason: {ooo_reason})"

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=message,
            data={"room_id": room_id, "status": new_status, "ooo_reason": ooo_reason}
        )

    async def _update_task_status(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Update task status"""
        params = action.params
        task_id = params.get("task_id")
        task_table = params.get("task_table", "housekeeping_tasks")
        new_status = params.get("status")

        # Validate table access
        if task_table not in ["housekeeping_tasks", "maintenancerequest"]:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                action_id=action_id,
                message="Invalid task table",
                error=f"Cannot update tasks in table: {task_table}"
            )

        query = text(f"""
            UPDATE {task_table}
            SET status = :status, updated_at = :updated_at
            WHERE id = :task_id
        """)

        await self.session.execute(query, {
            "task_id": task_id,
            "status": new_status,
            "updated_at": datetime.utcnow().isoformat(),
        })
        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Task {task_id} status updated to {new_status}",
            data={"task_id": task_id, "status": new_status}
        )

    async def _assign_task(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Assign a task to staff"""
        params = action.params
        task_id = params.get("task_id")
        task_table = params.get("task_table", "housekeeping_tasks")
        staff_id = params.get("staff_id")

        # Validate table access
        if task_table not in ["housekeeping_tasks", "maintenancerequest"]:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                action_id=action_id,
                message="Invalid task table",
                error=f"Cannot assign tasks in table: {task_table}"
            )

        query = text(f"""
            UPDATE {task_table}
            SET assigned_to = :staff_id, status = 'assigned', updated_at = :updated_at
            WHERE id = :task_id
        """)

        await self.session.execute(query, {
            "task_id": task_id,
            "staff_id": staff_id,
            "updated_at": datetime.utcnow().isoformat(),
        })
        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Task {task_id} assigned to staff {staff_id}",
            data={"task_id": task_id, "staff_id": staff_id}
        )

    async def _create_note(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Create a note for an entity"""
        params = action.params
        entity_type = params.get("entity_type")  # booking, guest, room
        entity_id = params.get("entity_id")
        note_content = params.get("content", "")

        # Use reservation_note table for booking notes
        if entity_type == "booking":
            query = text("""
                INSERT INTO reservation_note
                (reservation_id, note, created_by, created_at)
                VALUES (:entity_id, :content, :created_by, :created_at)
            """)
        else:
            # For other entities, use guest_communication or similar
            query = text("""
                INSERT INTO guest_communication
                (guest_id, communication_type, direction, subject, message, sent_by, created_at)
                VALUES (:entity_id, 'note', 'internal', 'Admin AI Note', :content, :created_by, :created_at)
            """)

        await self.session.execute(query, {
            "entity_id": entity_id,
            "content": note_content,
            "created_by": user_id,
            "created_at": datetime.utcnow().isoformat(),
        })
        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Note added to {entity_type} {entity_id}",
            data={"entity_type": entity_type, "entity_id": entity_id}
        )

    async def _send_notification(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Send a staff notification"""
        params = action.params

        query = text("""
            INSERT INTO staffnotification
            (staff_id, title, message, type, is_read, created_at)
            VALUES (:staff_id, :title, :message, :type, false, :created_at)
        """)

        await self.session.execute(query, {
            "staff_id": params.get("staff_id"),
            "title": params.get("title", "Notification from Admin AI"),
            "message": params.get("message", ""),
            "type": params.get("type", "info"),
            "created_at": datetime.utcnow().isoformat(),
        })
        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Notification sent to staff {params.get('staff_id')}",
            data={"staff_id": params.get("staff_id")}
        )



    async def _assign_room(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Assign a room to a booking"""
        params = action.params
        booking_id = params.get("booking_id")
        room_id = params.get("room_id")
        room_number = params.get("room_number", room_id)

        # Update booking with room assignment
        query = text("""
            UPDATE bookings
            SET room_id = :room_id, updated_at = :updated_at
            WHERE id = :booking_id
        """)

        await self.session.execute(query, {
            "booking_id": booking_id,
            "room_id": room_id,
            "updated_at": datetime.utcnow().isoformat(),
        })

        # Check booking status to determine room status
        # Room should only be "occupied" when guest is checked_in
        # Otherwise, set occupancy_status to "reserved" (pre-arrival)
        status_query = text("SELECT status FROM bookings WHERE id = :booking_id")
        result = await self.session.execute(status_query, {"booking_id": booking_id})
        row = result.fetchone()
        booking_status = row[0] if row else None

        if booking_status == "checked_in":
            # Guest is checked in - room is occupied
            room_query = text("""
                UPDATE rooms
                SET status = 'occupied', occupancy_status = 'occupied', updated_at = :updated_at
                WHERE id = :room_id
            """)
        else:
            # Pre-arrival - room is reserved but not occupied
            room_query = text("""
                UPDATE rooms
                SET occupancy_status = 'reserved', updated_at = :updated_at
                WHERE id = :room_id
            """)

        await self.session.execute(room_query, {
            "room_id": room_id,
            "updated_at": datetime.utcnow().isoformat(),
        })

        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Room {room_number} assigned to booking {booking_id}",
            data={"booking_id": booking_id, "room_id": room_id, "room_number": room_number}
        )

    async def _transfer_room(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Transfer guest to a different room"""
        params = action.params
        booking_id = params.get("booking_id")
        from_room_id = params.get("from_room_id")
        to_room_id = params.get("to_room_id")
        from_room_number = params.get("from_room_number", from_room_id)
        to_room_number = params.get("to_room_number", to_room_id)

        # Update booking with new room
        booking_query = text("""
            UPDATE bookings
            SET room_id = :to_room_id, updated_at = :updated_at
            WHERE id = :booking_id
        """)

        await self.session.execute(booking_query, {
            "booking_id": booking_id,
            "to_room_id": to_room_id,
            "updated_at": datetime.utcnow().isoformat(),
        })

        # Set old room to dirty (needs cleaning)
        if from_room_id:
            old_room_query = text("""
                UPDATE rooms
                SET status = 'dirty', updated_at = :updated_at
                WHERE id = :room_id
            """)
            await self.session.execute(old_room_query, {
                "room_id": from_room_id,
                "updated_at": datetime.utcnow().isoformat(),
            })

        # Set new room to occupied
        new_room_query = text("""
            UPDATE rooms
            SET status = 'occupied', updated_at = :updated_at
            WHERE id = :room_id
        """)
        await self.session.execute(new_room_query, {
            "room_id": to_room_id,
            "updated_at": datetime.utcnow().isoformat(),
        })

        # Log the room change
        try:
            change_log_query = text("""
                INSERT INTO room_changes
                (booking_id, from_room_id, to_room_id, reason, changed_by, created_at)
                VALUES (:booking_id, :from_room_id, :to_room_id, :reason, :changed_by, :created_at)
            """)
            await self.session.execute(change_log_query, {
                "booking_id": booking_id,
                "from_room_id": from_room_id,
                "to_room_id": to_room_id,
                "reason": "Room transfer via Admin AI",
                "changed_by": user_id,
                "created_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            # Table might not exist, that's ok
            pass

        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Guest transferred from room {from_room_number} to room {to_room_number}",
            data={
                "booking_id": booking_id,
                "from_room_id": from_room_id,
                "to_room_id": to_room_id,
                "from_room_number": from_room_number,
                "to_room_number": to_room_number
            }
        )

    async def _create_guest_note(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Add a note to a guest's profile"""
        params = action.params
        guest_id = params.get("guest_id")
        note_text = params.get("note_text")
        author_id = params.get("author_id", user_id)

        # Get current notes and add new one
        # Guest notes are stored as JSON array in the 'notes' field
        import json as json_lib

        # Get current notes
        get_query = text("SELECT notes FROM guests WHERE id = :guest_id")
        result = await self.session.execute(get_query, {"guest_id": guest_id})
        row = result.fetchone()

        current_notes = []
        if row and row[0]:
            try:
                parsed = json_lib.loads(row[0]) if isinstance(row[0], str) else row[0]
                # Ensure we always have a list (handles JSON "null" case)
                current_notes = parsed if isinstance(parsed, list) else []
            except:
                current_notes = []

        # Add new note
        new_note = {
            "id": str(uuid.uuid4())[:8],
            "text": note_text,
            "author_id": author_id,
            "created_at": datetime.utcnow().isoformat()
        }
        current_notes.append(new_note)

        # Update guest notes
        update_query = text("""
            UPDATE guests
            SET notes = :notes, updated_at = :updated_at
            WHERE id = :guest_id
        """)

        await self.session.execute(update_query, {
            "guest_id": guest_id,
            "notes": json_lib.dumps(current_notes),
            "updated_at": datetime.utcnow().isoformat(),
        })

        await self.session.commit()

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Note added to guest {guest_id}",
            data={"guest_id": guest_id, "note": new_note}
        )

    async def _update_guest(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Update guest profile (VIP status, loyalty tier, status, etc.)"""
        params = action.params
        guest_id = params.get("guest_id")
        updates = params.get("updates", {})

        if not guest_id:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                action_id=action_id,
                message="Guest ID is required",
                error="Missing guest_id"
            )

        # Build dynamic update query
        update_parts = []
        query_params = {"guest_id": guest_id, "updated_at": datetime.utcnow().isoformat()}

        if updates.get("vip_status") is not None:
            update_parts.append("vip_status = :vip_status")
            query_params["vip_status"] = updates["vip_status"]

        if updates.get("loyalty_tier"):
            update_parts.append("loyalty_tier = :loyalty_tier")
            query_params["loyalty_tier"] = updates["loyalty_tier"]

        if updates.get("status"):
            update_parts.append("status = :status")
            query_params["status"] = updates["status"]

        if not update_parts:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                action_id=action_id,
                message="No updates specified",
                error="Empty updates"
            )

        update_parts.append("updated_at = :updated_at")

        # Execute update
        query = text(f"""
            UPDATE guests
            SET {', '.join(update_parts)}
            WHERE id = :guest_id
        """)

        await self.session.execute(query, query_params)
        await self.session.commit()

        # Build description of what was updated
        update_desc = []
        if updates.get("vip_status"):
            update_desc.append("VIP status enabled")
        if updates.get("loyalty_tier"):
            update_desc.append(f"Loyalty tier set to {updates['loyalty_tier']}")
        if updates.get("status"):
            update_desc.append(f"Status set to {updates['status']}")

        return ActionResult(
            success=True,
            action_type=action.action_type,
            action_id=action_id,
            message=f"Guest {guest_id} updated: {', '.join(update_desc)}",
            data={"guest_id": guest_id, "updates": updates}
        )

    async def _create_booking(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Create a new booking with guest"""
        import secrets
        from datetime import date

        params = action.params
        guest_name = params.get("booking_guest_name") or params.get("guest_name", "")
        guest_email = params.get("guest_email", "")
        checkin_date = params.get("checkin_date") or params.get("target_date")
        checkout_date = params.get("checkout_date")
        room_type = params.get("room_type", "")

        # Validate required fields
        if not room_type:
            return ActionResult(
                success=False,
                action_type=action.action_type,
                action_id=action_id,
                message="Please specify the room type for the booking.",
                error="Missing room type"
            )

        # Calculate nights from dates if not provided
        nights = params.get("nights", 1)
        if checkin_date and checkout_date:
            try:
                ci = date.fromisoformat(checkin_date) if isinstance(checkin_date, str) else checkin_date
                co = date.fromisoformat(checkout_date) if isinstance(checkout_date, str) else checkout_date
                calculated_nights = (co - ci).days
                if calculated_nights > 0:
                    nights = calculated_nights
            except (ValueError, TypeError):
                pass

        # Split guest name into first/last
        name_parts = guest_name.split()
        first_name = name_parts[0] if name_parts else "Guest"
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        now = datetime.utcnow()

        try:
            # 1. Check if guest already exists by name
            guest_query = text("""
                SELECT id FROM guests
                WHERE LOWER(first_name) = LOWER(:first_name)
                AND LOWER(last_name) = LOWER(:last_name)
                LIMIT 1
            """)
            result = await self.session.execute(guest_query, {
                "first_name": first_name,
                "last_name": last_name
            })
            guest_row = result.fetchone()

            if guest_row:
                guest_id = guest_row[0]
            else:
                # Validate email before creating guest - don't auto-generate placeholder
                if not guest_email or not guest_email.strip() or '@' not in guest_email:
                    return ActionResult(
                        success=False,
                        action_type=action.action_type,
                        action_id=action_id,
                        message=f"Please provide the guest's email address for {guest_name}. This is required for booking confirmation.",
                        error="Missing guest email"
                    )

                # 2. Create new guest
                create_guest_query = text("""
                    INSERT INTO guests
                    (first_name, last_name, email, phone, status, emotion, created_at, updated_at)
                    VALUES (:first_name, :last_name, :email, :phone, 'Active', 'neutral', :created_at, :updated_at)
                """)
                await self.session.execute(create_guest_query, {
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": guest_email.strip().lower(),
                    "phone": params.get("guest_phone", ""),
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                })

                # Get the new guest ID
                get_id_query = text("SELECT last_insert_rowid()")
                try:
                    result = await self.session.execute(get_id_query)
                    guest_id = result.scalar()
                except:
                    # Fallback for PostgreSQL
                    result = await self.session.execute(text(
                        "SELECT id FROM guests WHERE first_name = :first_name AND last_name = :last_name ORDER BY id DESC LIMIT 1"
                    ), {"first_name": first_name, "last_name": last_name})
                    row = result.fetchone()
                    guest_id = row[0] if row else None

            if not guest_id:
                return ActionResult(
                    success=False,
                    action_type=action.action_type,
                    action_id=action_id,
                    message="Failed to create or find guest",
                    error="Guest creation failed"
                )

            # 3. Find room type ID
            room_type_query = text("""
                SELECT id, base_price, name FROM room_types
                WHERE LOWER(name) LIKE :room_type OR LOWER(category) LIKE :room_type
                LIMIT 1
            """)
            result = await self.session.execute(room_type_query, {
                "room_type": f"%{room_type.lower()}%"
            })
            room_type_row = result.fetchone()

            if not room_type_row:
                # Fetch available room types to show admin
                all_rt_query = text("SELECT name, base_price FROM room_types ORDER BY base_price")
                all_rt_result = await self.session.execute(all_rt_query)
                all_rt_rows = all_rt_result.fetchall()
                available_types = [f"{row[0]} (₹{row[1]:,.0f}/night)" for row in all_rt_rows]
                return ActionResult(
                    success=False,
                    action_type=action.action_type,
                    action_id=action_id,
                    message=f"Room type '{room_type}' not found. Available types: {', '.join(available_types) if available_types else 'No room types configured'}",
                    error="Invalid room type"
                )

            room_type_id = room_type_row[0]
            base_price = room_type_row[1]
            room_type_name = room_type_row[2]

            # 4. Generate booking identifiers
            date_str = now.strftime("%Y%m%d")
            random_part = secrets.token_hex(4).upper()
            booking_number = f"BK-{date_str}-{random_part}"
            confirmation_code = f"GLM-{secrets.token_hex(3).upper()}"

            # Calculate pricing using GST slab-based rates
            from app.core.tax import calculate_booking_taxes
            tax_calc = calculate_booking_taxes(base_price, nights)
            total_price = tax_calc["calculated_base"]
            taxes = tax_calc["taxes"]
            service_fee = tax_calc["service_fee"]
            final_total = tax_calc["total_price"]

            # 5. Create booking
            booking_query = text("""
                INSERT INTO bookings
                (booking_number, confirmation_code, guest_id, room_type_id, user_id,
                 arrival_date, departure_date, nights, adults, children, infants,
                 status, payment_status, booking_source, channel,
                 base_price, taxes, service_fee, total_price, balance_due,
                 created_by, created_at, updated_at)
                VALUES
                (:booking_number, :confirmation_code, :guest_id, :room_type_id, :user_id,
                 :arrival_date, :departure_date, :nights, 1, 0, 0,
                 'confirmed', 'pending', 'admin_ai', 'direct',
                 :base_price, :taxes, :service_fee, :total_price, :total_price,
                 :created_by, :created_at, :updated_at)
            """)

            await self.session.execute(booking_query, {
                "booking_number": booking_number,
                "confirmation_code": confirmation_code,
                "guest_id": guest_id,
                "room_type_id": room_type_id,
                "user_id": user_id,
                "arrival_date": checkin_date,
                "departure_date": checkout_date,
                "nights": nights,
                "base_price": base_price * nights,
                "taxes": taxes,
                "service_fee": service_fee,
                "total_price": final_total,
                "created_by": user_id,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            })

            await self.session.commit()

            return ActionResult(
                success=True,
                action_type=action.action_type,
                action_id=action_id,
                message=f"Booking created for {guest_name}!\n"
                       f"Confirmation: **{confirmation_code}**\n"
                       f"Check-in: {checkin_date} | Check-out: {checkout_date}\n"
                       f"Total: ₹{final_total:,.2f}",
                data={
                    "booking_number": booking_number,
                    "confirmation_code": confirmation_code,
                    "guest_id": guest_id,
                    "guest_name": guest_name,
                    "checkin_date": checkin_date,
                    "checkout_date": checkout_date,
                    "total_price": final_total
                }
            )

        except Exception as e:
            logger.error(f"Booking creation error: {e}", exc_info=True)
            await self.session.rollback()
            return ActionResult(
                success=False,
                action_type=action.action_type,
                action_id=action_id,
                message="Failed to create booking",
                error=str(e)
            )


class EmailActionExecutor:
    """Handles email automation actions"""

    # Available email templates
    EMAIL_TEMPLATES = {
        "welcome": {
            "subject": "Welcome to Glimmora Hotel",
            "description": "Welcome email for new guests",
        },
        "booking_confirmation": {
            "subject": "Booking Confirmation",
            "description": "Booking confirmation with details",
        },
        "checkout_reminder": {
            "subject": "Checkout Reminder",
            "description": "Reminder for upcoming checkout",
        },
        "precheckin_reminder": {
            "subject": "Complete Your Pre-Check-in",
            "description": "Invitation to complete pre-check-in",
        },
        "feedback_request": {
            "subject": "How was your stay?",
            "description": "Post-checkout feedback request",
        },
        "custom": {
            "subject": "Message from Glimmora Hotel",
            "description": "Custom email with provided content",
        },
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def prepare_email(
        self,
        template_name: str,
        recipient_email: str,
        context: Dict[str, Any],
        user_id: int
    ) -> PendingAction:
        """
        Prepare an email for sending

        Args:
            template_name: Email template to use
            recipient_email: Recipient email address
            context: Template context variables
            user_id: User preparing the email

        Returns:
            PendingAction for confirmation
        """
        if template_name not in self.EMAIL_TEMPLATES:
            template_name = "custom"

        template = self.EMAIL_TEMPLATES[template_name]
        action_id = str(uuid.uuid4())[:8]

        return PendingAction(
            action_id=action_id,
            action_type=ActionType.SEND_EMAIL,
            params={
                "template": template_name,
                "recipient_email": recipient_email,
                "context": context,
                "user_id": user_id,
            },
            description=f"Send {template_name} email to {recipient_email}",
            preview={
                "template": template_name,
                "subject": template.get("subject"),
                "recipient": recipient_email,
                "context": context,
            }
        )

    async def send_email(
        self,
        template_name: str,
        recipient_email: str,
        context: Dict[str, Any],
        user_id: int
    ) -> ActionResult:
        """
        Send an email using existing email service

        Args:
            template_name: Email template to use
            recipient_email: Recipient email address
            context: Template context variables
            user_id: User sending the email

        Returns:
            ActionResult with send status
        """
        action_id = str(uuid.uuid4())[:8]

        try:
            # Import email service
            from app.services.email_service import EmailService

            email_service = EmailService()

            # Map template to email service method
            success = False
            if template_name == "booking_confirmation":
                success = email_service.send_booking_confirmation_email(
                    to_email=recipient_email,
                    guest_name=context.get("guest_name", "Guest"),
                    confirmation_code=context.get("confirmation_code", "N/A"),
                    check_in=context.get("check_in", "N/A"),
                    check_out=context.get("check_out", "N/A"),
                    room_type=context.get("room_type", "N/A"),
                )
            elif template_name == "checkout_reminder":
                success = email_service.send_checkout_reminder_email(
                    to_email=recipient_email,
                    guest_name=context.get("guest_name", "Guest"),
                    checkout_date=context.get("checkout_date", "N/A"),
                    checkout_time=context.get("checkout_time", "11:00 AM"),
                    room_number=context.get("room_number", "N/A"),
                )
            elif template_name == "precheckin_reminder":
                success = email_service.send_precheckin_reminder_email(
                    to_email=recipient_email,
                    guest_name=context.get("guest_name", "Guest"),
                    confirmation_code=context.get("confirmation_code", "N/A"),
                    check_in_date=context.get("check_in_date", "N/A"),
                    precheckin_url=context.get("precheckin_url", "#"),
                )
            elif template_name == "feedback_request":
                success = email_service.send_feedback_request_email(
                    to_email=recipient_email,
                    guest_name=context.get("guest_name", "Guest"),
                    stay_dates=context.get("stay_dates", "N/A"),
                    feedback_url=context.get("feedback_url", "#"),
                )
            else:
                # Custom email - would need generic send method
                logger.warning(f"Template {template_name} not implemented for direct sending")
                success = False

            # Log the communication
            if success:
                query = text("""
                    INSERT INTO guest_communication
                    (guest_id, communication_type, direction, subject, message, status, sent_by, created_at)
                    VALUES (:guest_id, 'email', 'outbound', :subject, :message, 'sent', :sent_by, :created_at)
                """)

                await self.session.execute(query, {
                    "guest_id": context.get("guest_id"),
                    "subject": f"[{template_name}] {self.EMAIL_TEMPLATES.get(template_name, {}).get('subject', 'Email')}",
                    "message": f"Template: {template_name}, Recipient: {recipient_email}",
                    "sent_by": user_id,
                    "created_at": datetime.utcnow().isoformat(),
                })
                await self.session.commit()

            return ActionResult(
                success=success,
                action_type=ActionType.SEND_EMAIL,
                action_id=action_id,
                message=f"Email {'sent' if success else 'failed'} to {recipient_email}",
                data={"template": template_name, "recipient": recipient_email}
            )

        except Exception as e:
            logger.error(f"Email send error: {e}", exc_info=True)
            return ActionResult(
                success=False,
                action_type=ActionType.SEND_EMAIL,
                action_id=action_id,
                message="Failed to send email",
                error=str(e)
            )

    async def draft_email(
        self,
        template_name: str,
        recipient_email: str,
        context: Dict[str, Any],
        custom_content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Draft an email without sending

        Args:
            template_name: Email template to use
            recipient_email: Recipient email address
            context: Template context variables
            custom_content: Optional custom content

        Returns:
            Dict with draft email details
        """
        template = self.EMAIL_TEMPLATES.get(template_name, self.EMAIL_TEMPLATES["custom"])

        return {
            "template": template_name,
            "subject": template.get("subject"),
            "recipient": recipient_email,
            "context": context,
            "custom_content": custom_content,
            "preview": f"To: {recipient_email}\nSubject: {template.get('subject')}\n\n[Template: {template_name}]",
        }
