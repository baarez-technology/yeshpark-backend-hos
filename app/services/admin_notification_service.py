"""
Admin Notification Service

Provides a centralized way to send notifications to all admin users
for important system events like bookings, check-ins, maintenance requests, etc.
"""

from datetime import datetime
from typing import Optional, List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guest_chat import StaffNotification
from app.models.user import User


class NotificationType:
    """Notification type constants"""
    # Booking events
    BOOKING_CREATED = "booking_created"
    BOOKING_CANCELLED = "booking_cancelled"
    BOOKING_MODIFIED = "booking_modified"

    # Guest events
    GUEST_CHECKIN = "guest_checkin"
    GUEST_CHECKOUT = "guest_checkout"
    GUEST_NO_SHOW = "no_show"
    PRECHECKIN_COMPLETED = "precheckin_completed"

    # Room events
    ROOM_BLOCKED = "room_blocked"
    ROOM_UNBLOCKED = "room_unblocked"
    ROOM_STATUS_CHANGED = "room_status_changed"

    # Maintenance events
    MAINTENANCE_CREATED = "maintenance_created"
    MAINTENANCE_URGENT = "maintenance_urgent"
    MAINTENANCE_COMPLETED = "maintenance_completed"

    # Housekeeping events
    HOUSEKEEPING_ISSUE = "housekeeping_issue"
    HOUSEKEEPING_COMPLETED = "housekeeping_completed"

    # Staff events
    STAFF_LEAVE_REQUEST = "staff_leave_request"
    STAFF_SHIFT_CHANGE = "staff_shift_change"
    TASK_DECLINED = "task_declined"
    TASK_ACCEPTED = "task_accepted"

    # System events
    SYSTEM_ALERT = "system_alert"
    LOW_INVENTORY = "low_inventory"
    PAYMENT_FAILED = "payment_failed"

    # General
    INFO = "info"
    ALERT = "alert"
    URGENT = "urgent"


async def get_admin_user_ids(session: AsyncSession) -> List[int]:
    """Get all admin user IDs from the database"""
    result = await session.exec(
        select(User.id).where(User.role == "admin", User.is_active == True)
    )
    admin_ids = result.all()
    return list(admin_ids)


async def notify_admins(
    session: AsyncSession,
    notification_type: str,
    title: str,
    message: str,
    task_id: Optional[int] = None,
    guest_id: Optional[int] = None,
    booking_id: Optional[int] = None,
    room_id: Optional[int] = None,
    exclude_user_id: Optional[int] = None
) -> List[StaffNotification]:
    """
    Send a notification to all admin users.

    Args:
        session: Database session
        notification_type: Type of notification (use NotificationType constants)
        title: Notification title
        message: Notification message
        task_id: Optional related task ID
        guest_id: Optional guest ID (for highlighting guest in UI)
        booking_id: Optional booking ID (for highlighting booking in UI)
        room_id: Optional room ID (for highlighting room in UI)
        exclude_user_id: Optional user ID to exclude (e.g., the user who triggered the action)

    Returns:
        List of created notifications
    """
    admin_ids = await get_admin_user_ids(session)

    if exclude_user_id and exclude_user_id in admin_ids:
        admin_ids.remove(exclude_user_id)

    notifications = []
    for admin_id in admin_ids:
        notification = StaffNotification(
            staff_id=admin_id,
            task_id=task_id,
            notification_type=notification_type,
            title=title,
            message=message,
            guest_id=guest_id,
            booking_id=booking_id,
            room_id=room_id,
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)
        notifications.append(notification)

    return notifications


async def notify_user(
    session: AsyncSession,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    task_id: Optional[int] = None,
    guest_id: Optional[int] = None,
    booking_id: Optional[int] = None,
    room_id: Optional[int] = None
) -> StaffNotification:
    """
    Send a notification to a specific user.

    Args:
        session: Database session
        user_id: ID of the user to notify
        notification_type: Type of notification
        title: Notification title
        message: Notification message
        task_id: Optional related task ID
        guest_id: Optional guest ID (for highlighting guest in UI)
        booking_id: Optional booking ID (for highlighting booking in UI)
        room_id: Optional room ID (for highlighting room in UI)

    Returns:
        Created notification
    """
    notification = StaffNotification(
        staff_id=user_id,
        task_id=task_id,
        notification_type=notification_type,
        title=title,
        message=message,
        guest_id=guest_id,
        booking_id=booking_id,
        room_id=room_id,
        is_read=False,
        created_at=datetime.utcnow()
    )
    session.add(notification)
    return notification


# Convenience functions for common notification types

async def notify_new_booking(
    session: AsyncSession,
    guest_name: str,
    room_number: str,
    check_in_date: str,
    check_out_date: str,
    booking_id: int,
    total_amount: float,
    guest_id: Optional[int] = None,
    room_id: Optional[int] = None
):
    """Notify admins about a new booking"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.BOOKING_CREATED,
        title="New Booking Received",
        message=f"New booking #{booking_id} from {guest_name}. Room {room_number}, {check_in_date} to {check_out_date}. Total: ${total_amount:.2f}",
        guest_id=guest_id,
        booking_id=booking_id,
        room_id=room_id
    )


async def notify_booking_cancelled(
    session: AsyncSession,
    guest_name: str,
    room_number: str,
    booking_id: int,
    reason: Optional[str] = None,
    guest_id: Optional[int] = None,
    room_id: Optional[int] = None
):
    """Notify admins about a cancelled booking"""
    msg = f"Booking #{booking_id} cancelled. Guest: {guest_name}, Room: {room_number}"
    if reason:
        msg += f". Reason: {reason}"

    await notify_admins(
        session=session,
        notification_type=NotificationType.BOOKING_CANCELLED,
        title="Booking Cancelled",
        message=msg,
        guest_id=guest_id,
        booking_id=booking_id,
        room_id=room_id
    )


async def notify_guest_checkin(
    session: AsyncSession,
    guest_name: str,
    room_number: str,
    booking_id: int,
    guest_id: Optional[int] = None,
    room_id: Optional[int] = None
):
    """Notify admins about a guest check-in"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.GUEST_CHECKIN,
        title="Guest Checked In",
        message=f"{guest_name} has checked in to Room {room_number} (Booking #{booking_id})",
        guest_id=guest_id,
        booking_id=booking_id,
        room_id=room_id
    )


async def notify_guest_checkout(
    session: AsyncSession,
    guest_name: str,
    room_number: str,
    booking_id: int,
    guest_id: Optional[int] = None,
    room_id: Optional[int] = None
):
    """Notify admins about a guest check-out"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.GUEST_CHECKOUT,
        title="Guest Checked Out",
        message=f"{guest_name} has checked out from Room {room_number} (Booking #{booking_id})",
        guest_id=guest_id,
        booking_id=booking_id,
        room_id=room_id
    )


async def notify_maintenance_request(
    session: AsyncSession,
    room_number: str,
    issue_type: str,
    priority: str,
    description: str,
    request_id: int,
    room_id: Optional[int] = None,
    guest_id: Optional[int] = None
):
    """Notify admins about a new maintenance request"""
    notification_type = NotificationType.MAINTENANCE_URGENT if priority in ["high", "critical", "urgent"] else NotificationType.MAINTENANCE_CREATED
    title = "Urgent Maintenance Request" if priority in ["high", "critical", "urgent"] else "New Maintenance Request"

    await notify_admins(
        session=session,
        notification_type=notification_type,
        title=title,
        message=f"Room {room_number}: {issue_type} - {description[:100]}... (Priority: {priority}, Request #{request_id})",
        room_id=room_id,
        guest_id=guest_id
    )


async def notify_room_blocked(
    session: AsyncSession,
    room_number: str,
    reason: str,
    blocked_by: str,
    room_id: Optional[int] = None
):
    """Notify admins when a room is blocked"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.ROOM_BLOCKED,
        title="Room Blocked",
        message=f"Room {room_number} has been blocked. Reason: {reason}. Blocked by: {blocked_by}",
        room_id=room_id
    )


async def notify_room_unblocked(
    session: AsyncSession,
    room_number: str,
    unblocked_by: str,
    room_id: Optional[int] = None
):
    """Notify admins when a room is unblocked"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.ROOM_UNBLOCKED,
        title="Room Unblocked",
        message=f"Room {room_number} is now available. Unblocked by: {unblocked_by}",
        room_id=room_id
    )


async def notify_staff_leave_request(
    session: AsyncSession,
    staff_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    staff_id: int
):
    """Notify admins about a staff leave request"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.STAFF_LEAVE_REQUEST,
        title="Staff Leave Request",
        message=f"{staff_name} has requested {leave_type} leave from {start_date} to {end_date}"
    )


async def notify_no_show(
    session: AsyncSession,
    guest_name: str,
    room_number: str,
    booking_id: int,
    guest_id: Optional[int] = None,
    room_id: Optional[int] = None
):
    """Notify admins about a no-show"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.GUEST_NO_SHOW,
        title="Guest No-Show",
        message=f"Guest {guest_name} did not check in for booking #{booking_id} (Room {room_number})",
        guest_id=guest_id,
        booking_id=booking_id,
        room_id=room_id
    )


async def notify_payment_issue(
    session: AsyncSession,
    guest_name: str,
    booking_id: int,
    amount: float,
    error: str,
    guest_id: Optional[int] = None
):
    """Notify admins about a payment issue"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.PAYMENT_FAILED,
        title="Payment Failed",
        message=f"Payment of ${amount:.2f} failed for {guest_name} (Booking #{booking_id}). Error: {error}",
        guest_id=guest_id,
        booking_id=booking_id
    )


async def notify_housekeeping_issue(
    session: AsyncSession,
    room_number: str,
    issue: str,
    reported_by: str,
    room_id: Optional[int] = None,
    guest_id: Optional[int] = None
):
    """Notify admins about a housekeeping issue"""
    await notify_admins(
        session=session,
        notification_type=NotificationType.HOUSEKEEPING_ISSUE,
        title="Housekeeping Issue Reported",
        message=f"Room {room_number}: {issue}. Reported by: {reported_by}",
        room_id=room_id,
        guest_id=guest_id
    )
