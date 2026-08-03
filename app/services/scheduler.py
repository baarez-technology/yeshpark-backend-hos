"""
Scheduled tasks for email reminders, auto-cancellation, room sync, lock cleanup, and staff automation.

Background Tasks:
- cleanup_expired_holds: Every 60 seconds - clean expired DB holds + stale Redis locks
- sync_room_statuses: Every 5 minutes - sync room status with booking state
- process_waitlist_conversions: Every 5 minutes - auto-book waitlist when rooms available
- cleanup_stale_locks: Every 2 minutes - release locks for cancelled/checked-out bookings
- send_day_before_precheckin_reminders: 10 AM - Pre-checkin reminder
- send_arrival_day_precheckin_reminders: 8 AM - Urgent reminder
- auto_cancel_no_precheckin_bookings: 11:59 PM - Cancel no-shows

Staff Automation Tasks:
- auto_assign_pending_tasks: Every 5 minutes - auto-assign unassigned HK/Maintenance/Runner tasks
- process_due_preventive_maintenance: Daily 6 AM - generate work orders for due PM schedules
- update_staff_performance_metrics: Daily 11 PM - calculate staff performance metrics

Multi-Tenant Support:
- When MULTI_TENANT_ENABLED=true, all jobs iterate over all active hotels
- Each hotel's tasks are processed independently with its own database session
"""
import asyncio
from datetime import datetime, timedelta, date
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.session import async_session_maker
from app.models.reservations import Reservation, Booking, Guest, Waitlist
from app.models.inventory import Room, RoomType, RoomHold
from app.models.precheckin import PreCheckIn
from app.services.email_service import get_email_service
from app.services.refund_service import cancel_and_refund_booking
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


async def _get_session_for_job():
    """
    Get appropriate session based on multi-tenant mode.

    In single-tenant mode: Returns a generator for the single database
    In multi-tenant mode: This function shouldn't be used directly;
                         use _run_for_all_hotels() instead
    """
    if settings.multi_tenant_enabled:
        raise RuntimeError(
            "In multi-tenant mode, use _run_for_all_hotels() instead of direct session access"
        )
    async with async_session_maker() as session:
        yield session


async def _run_for_all_hotels(job_func, job_name: str):
    """
    Run a job function for all active hotels in multi-tenant mode.

    Args:
        job_func: Async function that takes (session, hotel) as arguments
        job_name: Name of the job for logging
    """
    if not settings.multi_tenant_enabled:
        # Single-tenant mode: run with default session
        async with async_session_maker() as session:
            await job_func(session, None)
        return

    # Multi-tenant mode: iterate all hotels
    from app.db.tenant_manager import tenant_manager

    try:
        hotels = await tenant_manager.get_all_active_hotels()
        logger.debug(f"{job_name}: Processing {len(hotels)} active hotels")

        for hotel in hotels:
            try:
                async for session in tenant_manager.get_session(hotel.code):
                    await job_func(session, hotel)
            except Exception as e:
                logger.error(f"{job_name} failed for hotel {hotel.code}: {e}")
                continue

    except Exception as e:
        logger.error(f"{job_name} failed to get hotels list: {e}")


def _get_lock_manager():
    """Get lock manager with fallback for when Redis is unavailable."""
    try:
        from app.services.redis_lock_service import get_lock_manager
        return get_lock_manager()
    except (RuntimeError, ImportError) as e:
        logger.debug(f"Lock manager not available: {e}")
        return None


async def _send_precheckin_reminders_for_hotel(session: AsyncSession, hotel):
    """
    Send pre-checkin reminder emails for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"
    tomorrow = date.today() + timedelta(days=1)

    # Find reservations checking in tomorrow that haven't completed pre-checkin
    reservations = await session.exec(
        select(Reservation).where(
            and_(
                Reservation.arrival_date == tomorrow,
                Reservation.status.in_(["booked", "confirmed"]),
            )
        )
    )
    reservations_list = reservations.all()

    if not reservations_list:
        logger.debug(f"[{hotel_name}] No reservations found for pre-checkin reminder on {tomorrow}")
        return

    email_service = get_email_service()
    sent_count = 0

    for reservation in reservations_list:
        try:
            # Check if pre-checkin already completed
            precheckin = await session.exec(
                select(PreCheckIn).where(
                    and_(
                        PreCheckIn.reservation_id == reservation.id,
                        PreCheckIn.status == "completed"
                    )
                )
            )
            if precheckin.first():
                continue  # Skip if already completed

            # Get guest
            guest = await session.get(Guest, reservation.guest_id)
            if not guest or not guest.email:
                continue

            # Generate pre-checkin URL
            precheckin_url = f"{settings.frontend_url}/pre-checkin?bookingId={reservation.id}"

            # Format check-in date
            check_in_formatted = reservation.arrival_date.strftime("%B %d, %Y")

            # Send reminder email
            email_service.send_precheckin_reminder_email(
                to_email=guest.email,
                guest_name=f"{guest.first_name} {guest.last_name}",
                booking_number=reservation.confirmation_code,
                check_in_date=check_in_formatted,
                precheckin_url=precheckin_url,
            )

            sent_count += 1
            logger.info(f"[{hotel_name}] Sent pre-checkin reminder to {guest.email} for booking {reservation.confirmation_code}")

        except Exception as e:
            logger.error(f"[{hotel_name}] Failed to send pre-checkin reminder for reservation {reservation.id}: {str(e)}")
            continue

    logger.info(f"[{hotel_name}] Pre-checkin reminders sent: {sent_count}/{len(reservations_list)}")


async def send_precheckin_reminders():
    """
    Send pre-checkin reminder emails to guests whose check-in is tomorrow.
    This should be run daily (e.g., via cron or scheduled task).

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_send_precheckin_reminders_for_hotel, "send_precheckin_reminders")
    except Exception as e:
        logger.error(f"Error in send_precheckin_reminders: {str(e)}")


async def _send_arrival_day_reminders_for_hotel(session: AsyncSession, hotel):
    """
    Send URGENT pre-checkin reminder emails for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"
    today = date.today()

    # Find reservations checking in TODAY that haven't completed pre-checkin
    reservations = await session.exec(
        select(Reservation).where(
            and_(
                Reservation.arrival_date == today,
                Reservation.status.in_(["booked", "confirmed"]),
            )
        )
    )
    reservations_list = reservations.all()

    if not reservations_list:
        logger.debug(f"[{hotel_name}] No reservations found for arrival day reminder on {today}")
        return

    email_service = get_email_service()
    sent_count = 0

    for reservation in reservations_list:
        try:
            # Check if pre-checkin already completed
            precheckin = await session.exec(
                select(PreCheckIn).where(
                    and_(
                        PreCheckIn.reservation_id == reservation.id,
                        PreCheckIn.status == "completed"
                    )
                )
            )
            if precheckin.first():
                continue  # Skip if already completed

            # Get guest
            guest = await session.get(Guest, reservation.guest_id)
            if not guest or not guest.email:
                continue

            # Generate pre-checkin URL
            precheckin_url = f"{settings.frontend_url}/pre-checkin?bookingId={reservation.id}"

            # Format check-in date
            check_in_formatted = reservation.arrival_date.strftime("%B %d, %Y")

            # Send URGENT reminder email with modified subject
            email_service.send_precheckin_reminder_email(
                to_email=guest.email,
                guest_name=f"{guest.first_name} {guest.last_name}",
                booking_number=reservation.confirmation_code,
                check_in_date=check_in_formatted,
                precheckin_url=precheckin_url,
            )

            sent_count += 1
            logger.info(f"[{hotel_name}] Sent URGENT arrival day reminder to {guest.email} for booking {reservation.confirmation_code}")

        except Exception as e:
            logger.error(f"[{hotel_name}] Failed to send arrival day reminder for reservation {reservation.id}: {str(e)}")
            continue

    logger.info(f"[{hotel_name}] Arrival day reminders sent: {sent_count}/{len(reservations_list)}")


async def send_arrival_day_precheckin_reminders():
    """
    Send URGENT pre-checkin reminder emails to guests checking in TODAY.
    Second reminder - sent at 8 AM on arrival day.
    Schedule: Run daily at 8:00 AM

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_send_arrival_day_reminders_for_hotel, "send_arrival_day_reminders")
    except Exception as e:
        logger.error(f"Error in send_arrival_day_precheckin_reminders: {str(e)}")


async def _auto_cancel_for_hotel(session: AsyncSession, hotel):
    """
    Auto-cancel bookings for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"
    today = date.today()

    # Find bookings for TODAY that are still pending/confirmed (not checked in)
    reservations = await session.exec(
        select(Reservation).where(
            and_(
                Reservation.arrival_date == today,
                Reservation.status.in_(["booked", "confirmed"]),
            )
        )
    )
    reservations_list = reservations.all()

    if not reservations_list:
        logger.debug(f"[{hotel_name}] No unchecked-in reservations found for auto-cancel on {today}")
        return

    cancelled_count = 0
    skipped_count = 0

    for reservation in reservations_list:
        try:
            # Check if pre-checkin was completed - if so, don't auto-cancel
            precheckin = await session.exec(
                select(PreCheckIn).where(
                    and_(
                        PreCheckIn.reservation_id == reservation.id,
                        PreCheckIn.status == "completed"
                    )
                )
            )
            if precheckin.first():
                skipped_count += 1
                logger.debug(f"[{hotel_name}] Skipping reservation {reservation.id} - pre-checkin completed")
                continue

            # Cancel and refund the booking
            cancelled_res, refund_payment = await cancel_and_refund_booking(
                session,
                reservation.id,
                cancellation_reason="auto_cancelled_no_precheckin"
            )

            if cancelled_res:
                cancelled_count += 1
                refund_amount = abs(refund_payment.amount) if refund_payment else 0
                logger.info(
                    f"[{hotel_name}] Auto-cancelled reservation {reservation.id} "
                    f"(booking: {reservation.confirmation_code}), "
                    f"refund: ${refund_amount:.2f}"
                )

        except Exception as e:
            logger.error(f"[{hotel_name}] Failed to auto-cancel reservation {reservation.id}: {str(e)}")
            continue

    # Commit all changes
    await session.commit()

    logger.info(
        f"[{hotel_name}] Auto-cancellation completed: {cancelled_count} cancelled, "
        f"{skipped_count} skipped (pre-checkin completed)"
    )


async def auto_cancel_no_precheckin_bookings():
    """
    Auto-cancel bookings at 11:59 PM on arrival day if:
    - Guest hasn't checked in (status still pending/confirmed)
    - Pre-checkin not completed

    Processes 50% refund and sends cancellation email.
    Schedule: Run daily at 11:59 PM

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_auto_cancel_for_hotel, "auto_cancel_no_precheckin")
    except Exception as e:
        logger.error(f"Error in auto_cancel_no_precheckin_bookings: {str(e)}")




async def _cleanup_expired_holds_for_hotel(session: AsyncSession, hotel):
    """
    Clean expired DB room holds for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"

    # Release expired DB holds
    from app.services.room_assignment_service import release_expired_holds
    released_count = await release_expired_holds(session)

    if released_count > 0:
        logger.info(f"[{hotel_name}] Released {released_count} expired room holds")

    await session.commit()


async def cleanup_expired_holds():
    """
    Clean expired DB room holds and stale Redis locks.
    Schedule: Every 60 seconds

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_cleanup_expired_holds_for_hotel, "cleanup_expired_holds")

        # Cleanup stale Redis locks (global, not per-hotel)
        lock_manager = _get_lock_manager()
        if lock_manager:
            try:
                cleaned = await lock_manager.cleanup_stale_locks()
                if cleaned > 0:
                    logger.info(f"Cleaned {cleaned} stale Redis locks")
            except Exception as redis_err:
                logger.debug(f"Redis unavailable for lock cleanup: {redis_err}")

    except Exception as e:
        logger.error(f"Error in cleanup_expired_holds: {str(e)}")


async def _sync_room_statuses_for_hotel(session: AsyncSession, hotel):
    """
    Sync room status with booking state for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"
    today = date.today()
    fixed_count = 0

    # Get all rooms
    rooms = (await session.execute(select(Room))).scalars().all()

    for room in rooms:
        # Get active reservations for this room
        active_res = (await session.execute(
            select(Reservation).where(
                and_(
                    Reservation.room_id == room.id,
                    Reservation.status == "checked_in",
                    Reservation.arrival_date <= today,
                    Reservation.departure_date > today
                )
            )
        )).scalars().first()

        if room.status == "occupied" and not active_res:
            # Room says occupied but no one is checked in
            room.status = "dirty"
            room.current_guest_id = None
            room.updated_at = datetime.utcnow()
            fixed_count += 1
            logger.info(f"[{hotel_name}] Room {room.number}: occupied -> dirty (no active check-in)")

        elif room.status in ["available", "clean", "inspected"] and active_res:
            # Room says available but guest is checked in
            room.status = "occupied"
            room.current_guest_id = active_res.guest_id
            room.updated_at = datetime.utcnow()
            fixed_count += 1
            logger.info(f"[{hotel_name}] Room {room.number}: {room.status} -> occupied (guest checked in)")

    if fixed_count > 0:
        logger.info(f"[{hotel_name}] Fixed {fixed_count} room status inconsistencies")
        await session.commit()


async def sync_room_statuses():
    """
    Sync room status with booking state.
    - Rooms marked 'occupied' with no active check-in -> mark 'dirty'
    - Rooms marked 'available' with active check-in -> mark 'occupied'
    Schedule: Every 5 minutes

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_sync_room_statuses_for_hotel, "sync_room_statuses")
    except Exception as e:
        logger.error(f"Error in sync_room_statuses: {str(e)}")


async def _process_waitlist_for_hotel(session: AsyncSession, hotel):
    """
    Process waitlist conversions for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"
    today = date.today()
    converted_count = 0

    # Get active waitlist entries for upcoming dates
    waitlist_entries = (await session.execute(
        select(Waitlist).where(
            and_(
                Waitlist.status == "active",
                Waitlist.arrival_date >= today
            )
        ).order_by(
            Waitlist.priority.desc(),
            Waitlist.created_at.asc()
        )
    )).scalars().all()

    if not waitlist_entries:
        return

    from app.services.cancellation_service import process_waitlist_for_dates

    for entry in waitlist_entries:
        try:
            # Get room type
            room_type = (await session.execute(
                select(RoomType).where(RoomType.name == entry.room_type_preference)
            )).scalars().first()

            if not room_type:
                continue

            # Try to convert
            new_reservation_id = await process_waitlist_for_dates(
                session,
                room_type_id=room_type.id,
                arrival_date=entry.arrival_date,
                departure_date=entry.departure_date
            )

            if new_reservation_id:
                converted_count += 1

        except Exception as e:
            logger.warning(f"[{hotel_name}] Failed to process waitlist entry {entry.id}: {e}")
            continue

    if converted_count > 0:
        logger.info(f"[{hotel_name}] Converted {converted_count} waitlist entries to reservations")
        await session.commit()


async def process_waitlist_conversions():
    """
    Check for available rooms and auto-book waitlist entries.
    Schedule: Every 5 minutes

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_process_waitlist_for_hotel, "process_waitlist_conversions")
    except Exception as e:
        logger.error(f"Error in process_waitlist_conversions: {str(e)}")


async def _cleanup_stale_locks_for_hotel(session: AsyncSession, hotel):
    """
    Clean stale locks for a specific hotel.
    Note: Redis locks are global, so this validates against hotel-specific reservations.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"

    lock_manager = _get_lock_manager()
    if not lock_manager:
        return

    try:
        # Get all active locks - will fail if Redis unavailable
        active_locks = await lock_manager.get_all_active_locks()

        if not active_locks:
            return

        released_count = 0

        for room_id, lock_data in active_locks:
            booking_id = lock_data.get("booking_id")
            if not booking_id:
                continue

            # Check if booking still needs the lock
            reservation = await session.get(Reservation, booking_id)

            if not reservation:
                # Booking doesn't exist in this hotel - skip (might be from another hotel)
                continue

            if reservation.status in ["cancelled", "checked_out", "no_show"]:
                # Booking is cancelled/completed - release lock
                await lock_manager.force_release_lock(room_id)
                released_count += 1
                logger.info(f"[{hotel_name}] Released stale lock: room {room_id}, booking {booking_id} ({reservation.status})")
                continue

            if reservation.room_id and reservation.room_id != room_id:
                # Booking was assigned a different room - release this lock
                await lock_manager.force_release_lock(room_id)
                released_count += 1
                logger.info(f"[{hotel_name}] Released stale lock: room {room_id}, booking {booking_id} (different room assigned)")

        if released_count > 0:
            logger.info(f"[{hotel_name}] Cleaned up {released_count} stale room locks")

    except Exception as redis_err:
        logger.debug(f"[{hotel_name}] Redis unavailable for stale lock cleanup: {redis_err}")


async def cleanup_stale_locks():
    """
    Release Redis locks for cancelled or checked-out bookings.
    Schedule: Every 2 minutes
    Optional - graceful fallback if Redis unavailable

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_cleanup_stale_locks_for_hotel, "cleanup_stale_locks")
    except Exception as e:
        logger.error(f"Error in cleanup_stale_locks: {str(e)}")


# ============== STAFF AUTOMATION BACKGROUND JOBS ==============

async def _auto_assign_tasks_for_hotel(session: AsyncSession, hotel):
    """
    Auto-assign pending tasks for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"

    from app.services.staff_scheduling_service import get_scheduling_service
    from app.models.operations import HousekeepingTask, MaintenanceRequest
    from app.models.runner import RunnerPickupRequest, RunnerDelivery

    scheduling_service = get_scheduling_service(session)
    total_assigned = 0

    # 1. Auto-assign pending housekeeping tasks
    try:
        hk_tasks = (await session.execute(
            select(HousekeepingTask).where(
                and_(
                    HousekeepingTask.status == "pending",
                    HousekeepingTask.assigned_to == None
                )
            ).order_by(
                HousekeepingTask.priority.desc(),
                HousekeepingTask.created_at.asc()
            ).limit(20)
        )).scalars().all()

        for task in hk_tasks:
            best_staff = await scheduling_service.find_best_staff_for_task(
                task_type="housekeeping",
                priority=task.priority or "normal",
                room_number=task.room_number
            )
            if best_staff:
                task.assigned_to = best_staff.staff_id
                task.status = "assigned"
                task.updated_at = datetime.utcnow()
                total_assigned += 1
    except Exception as e:
        logger.warning(f"[{hotel_name}] Error auto-assigning housekeeping tasks: {e}")

    # 2. Auto-assign pending maintenance work orders
    try:
        maint_tasks = (await session.execute(
            select(MaintenanceRequest).where(
                and_(
                    MaintenanceRequest.status.in_(["open", "pending"]),
                    MaintenanceRequest.assigned_to == None
                )
            ).order_by(
                MaintenanceRequest.priority.desc(),
                MaintenanceRequest.reported_at.asc()
            ).limit(20)
        )).scalars().all()

        for task in maint_tasks:
            best_staff = await scheduling_service.find_best_staff_for_task(
                task_type="maintenance",
                priority=task.priority or "normal",
                room_number=task.room_number
            )
            if best_staff:
                task.assigned_to = best_staff.staff_id
                task.status = "assigned"
                task.updated_at = datetime.utcnow()
                total_assigned += 1
    except Exception as e:
        logger.warning(f"[{hotel_name}] Error auto-assigning maintenance tasks: {e}")

    # 3. Auto-assign pending runner pickups
    try:
        pickups = (await session.execute(
            select(RunnerPickupRequest).where(
                and_(
                    RunnerPickupRequest.status == "pending",
                    RunnerPickupRequest.assigned_to == None
                )
            ).order_by(
                RunnerPickupRequest.priority.desc(),
                RunnerPickupRequest.requested_at.asc()
            ).limit(20)
        )).scalars().all()

        for pickup in pickups:
            best_staff = await scheduling_service.find_best_staff_for_task(
                task_type="room_service",
                priority=pickup.priority or "normal",
                room_number=pickup.room_number
            )
            if best_staff:
                pickup.assigned_to = best_staff.staff_id
                pickup.status = "in_progress"
                pickup.updated_at = datetime.utcnow()
                total_assigned += 1
    except Exception as e:
        logger.warning(f"[{hotel_name}] Error auto-assigning runner pickups: {e}")

    # 4. Auto-assign pending runner deliveries
    try:
        deliveries = (await session.execute(
            select(RunnerDelivery).where(
                and_(
                    RunnerDelivery.status == "pending",
                    RunnerDelivery.assigned_to == None
                )
            ).order_by(
                RunnerDelivery.priority.desc(),
                RunnerDelivery.ordered_at.asc()
            ).limit(20)
        )).scalars().all()

        for delivery in deliveries:
            best_staff = await scheduling_service.find_best_staff_for_task(
                task_type="room_service",
                priority=delivery.priority or "normal",
                room_number=delivery.room_number
            )
            if best_staff:
                delivery.assigned_to = best_staff.staff_id
                delivery.status = "in_transit"
                delivery.picked_up_at = datetime.utcnow()
                delivery.updated_at = datetime.utcnow()
                total_assigned += 1
    except Exception as e:
        logger.warning(f"[{hotel_name}] Error auto-assigning runner deliveries: {e}")

    if total_assigned > 0:
        await session.commit()
        logger.info(f"[{hotel_name}] Auto-assigned {total_assigned} pending tasks to available staff")


async def auto_assign_pending_tasks():
    """
    Auto-assign pending tasks to available staff based on shift and workload.
    Handles: Housekeeping tasks, Maintenance work orders, Runner pickups/deliveries
    Schedule: Every 5 minutes

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_auto_assign_tasks_for_hotel, "auto_assign_pending_tasks")
    except Exception as e:
        logger.error(f"Error in auto_assign_pending_tasks: {str(e)}")


async def _process_pm_for_hotel(session: AsyncSession, hotel):
    """
    Generate PM work orders for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"

    from app.models.maintenance import PreventiveMaintenanceSchedule
    from app.models.operations import MaintenanceRequest
    from app.services.staff_scheduling_service import get_scheduling_service

    today = date.today()

    # Get due schedules
    schedules = (await session.execute(
        select(PreventiveMaintenanceSchedule).where(
            and_(
                PreventiveMaintenanceSchedule.active == True,
                PreventiveMaintenanceSchedule.next_due_date <= today
            )
        )
    )).scalars().all()

    if not schedules:
        return

    scheduling_service = get_scheduling_service(session)
    generated_count = 0

    for schedule in schedules:
        try:
            # Determine assignee
            assigned_to = schedule.assigned_to

            # Auto-assign if not pre-assigned
            if not assigned_to:
                best_staff = await scheduling_service.find_best_staff_for_task(
                    task_type="maintenance",
                    priority=schedule.priority
                )
                if best_staff:
                    assigned_to = best_staff.staff_id

            # Generate unique work order ID
            import uuid
            work_order_id = f"PM-{today.strftime('%Y%m%d')}-{schedule.id}-{uuid.uuid4().hex[:4].upper()}"

            # Create work order
            work_order = MaintenanceRequest(
                work_order_id=work_order_id,
                title=f"PM: {schedule.name}",
                description=schedule.description or f"Preventive maintenance - {schedule.maintenance_type}",
                location=schedule.location,
                category=schedule.maintenance_type,
                issue_type=schedule.maintenance_type,
                issue=f"Scheduled preventive maintenance: {schedule.name}",
                priority=schedule.priority,
                status="pending" if not assigned_to else "assigned",
                assigned_to=assigned_to,
                estimated_duration=schedule.estimated_duration,
                is_preventive=True,
                preventive_schedule_id=schedule.id,
                scheduled_date=today,
                reported_at=datetime.utcnow(),
            )
            session.add(work_order)

            # Update schedule
            schedule.last_performed = today
            schedule.total_completions += 1

            # Calculate next due date
            from app.api.v1.maintenance import calculate_next_due_date
            schedule.next_due_date = calculate_next_due_date(
                frequency=schedule.frequency,
                day_of_week=schedule.day_of_week,
                day_of_month=schedule.day_of_month,
                from_date=today
            )
            schedule.updated_at = datetime.utcnow()

            generated_count += 1

            # Create notification if assigned
            if assigned_to:
                try:
                    from app.models.guest_chat import StaffNotification
                    notification = StaffNotification(
                        staff_id=assigned_to,
                        notification_type="task_assigned",
                        title=f"Preventive Maintenance: {schedule.name}",
                        message=f"Scheduled PM at {schedule.location}. Est. duration: {schedule.estimated_duration} min",
                        is_read=False,
                        created_at=datetime.utcnow()
                    )
                    session.add(notification)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"[{hotel_name}] Failed to generate PM work order for schedule {schedule.id}: {e}")
            continue

    if generated_count > 0:
        await session.commit()
        logger.info(f"[{hotel_name}] Generated {generated_count} preventive maintenance work orders")


async def process_due_preventive_maintenance():
    """
    Generate work orders for due preventive maintenance schedules.
    Schedule: Daily at 6:00 AM

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_process_pm_for_hotel, "process_due_preventive_maintenance")
    except Exception as e:
        logger.error(f"Error in process_due_preventive_maintenance: {str(e)}")


async def _update_metrics_for_hotel(session: AsyncSession, hotel):
    """
    Update staff performance metrics for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"

    from app.models.staff import Staff, StaffPerformanceMetrics
    from app.models.operations import HousekeepingTask, MaintenanceRequest

    today = date.today()

    # Get all active staff
    staff_list = (await session.execute(
        select(Staff).where(Staff.status == "active")
    )).scalars().all()

    if not staff_list:
        return

    for staff in staff_list:
        try:
            # Calculate metrics for today
            tasks_assigned = 0
            tasks_completed = 0
            total_duration = 0
            task_count_with_duration = 0

            # Housekeeping tasks
            hk_tasks = (await session.execute(
                select(HousekeepingTask).where(
                    and_(
                        HousekeepingTask.assigned_to == staff.id,
                        HousekeepingTask.created_at >= datetime.combine(today, datetime.min.time())
                    )
                )
            )).scalars().all()

            for task in hk_tasks:
                tasks_assigned += 1
                if task.status == "completed":
                    tasks_completed += 1
                    if task.actual_duration:
                        total_duration += task.actual_duration
                        task_count_with_duration += 1

            # Maintenance tasks
            maint_tasks = (await session.execute(
                select(MaintenanceRequest).where(
                    and_(
                        MaintenanceRequest.assigned_to == staff.id,
                        MaintenanceRequest.reported_at >= datetime.combine(today, datetime.min.time())
                    )
                )
            )).scalars().all()

            for task in maint_tasks:
                tasks_assigned += 1
                if task.status == "completed":
                    tasks_completed += 1
                    if task.actual_duration:
                        total_duration += task.actual_duration
                        task_count_with_duration += 1

            # Calculate averages
            avg_completion_time = total_duration / task_count_with_duration if task_count_with_duration > 0 else 0
            completion_rate = tasks_completed / tasks_assigned if tasks_assigned > 0 else 0

            # Check for existing metric entry for today
            existing = (await session.execute(
                select(StaffPerformanceMetrics).where(
                    and_(
                        StaffPerformanceMetrics.staff_id == staff.id,
                        StaffPerformanceMetrics.date == today
                    )
                )
            )).scalars().first()

            if existing:
                existing.tasks_assigned = tasks_assigned
                existing.tasks_completed = tasks_completed
                existing.avg_completion_time = avg_completion_time
                existing.efficiency_score = min(completion_rate * 100, 100)
                existing.updated_at = datetime.utcnow()
            else:
                metric = StaffPerformanceMetrics(
                    staff_id=staff.id,
                    date=today,
                    tasks_assigned=tasks_assigned,
                    tasks_completed=tasks_completed,
                    avg_completion_time=avg_completion_time,
                    efficiency_score=min(completion_rate * 100, 100),
                    quality_score=95.0,  # Default, updated by inspections
                )
                session.add(metric)

            # Update staff overall rating (rolling average of last 30 days)
            recent_metrics = (await session.execute(
                select(StaffPerformanceMetrics).where(
                    and_(
                        StaffPerformanceMetrics.staff_id == staff.id,
                        StaffPerformanceMetrics.date >= today - timedelta(days=30)
                    )
                )
            )).scalars().all()

            if recent_metrics:
                avg_efficiency = sum(m.efficiency_score or 0 for m in recent_metrics) / len(recent_metrics)
                avg_quality = sum(m.quality_score or 0 for m in recent_metrics) / len(recent_metrics)
                staff.performance_rating = round((avg_efficiency * 0.6 + avg_quality * 0.4) / 20, 1)  # Scale to 5.0

        except Exception as e:
            logger.warning(f"[{hotel_name}] Failed to update metrics for staff {staff.id}: {e}")
            continue

    await session.commit()
    logger.info(f"[{hotel_name}] Updated performance metrics for {len(staff_list)} staff members")


async def update_staff_performance_metrics():
    """
    Calculate and update staff performance metrics daily.
    Tracks: tasks completed, avg completion time, quality scores, efficiency
    Schedule: Daily at 11:00 PM

    Multi-tenant: Processes all active hotels.
    """
    try:
        await _run_for_all_hotels(_update_metrics_for_hotel, "update_staff_performance_metrics")
    except Exception as e:
        logger.error(f"Error in update_staff_performance_metrics: {str(e)}")


async def _check_unassigned_for_hotel(session: AsyncSession, hotel):
    """
    Check for unassigned tasks for a specific hotel.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    hotel_name = hotel.name if hotel else "default"

    from app.models.operations import HousekeepingTask, MaintenanceRequest
    from app.models.user import User
    from app.models.guest_chat import StaffNotification

    # Get unassigned housekeeping tasks
    unassigned_hk = (await session.execute(
        select(HousekeepingTask).where(
            and_(
                HousekeepingTask.assigned_to == None,
                HousekeepingTask.status.in_(["pending", "open"])
            )
        )
    )).scalars().all()

    # Get unassigned maintenance requests
    unassigned_maint = (await session.execute(
        select(MaintenanceRequest).where(
            and_(
                MaintenanceRequest.assigned_to == None,
                MaintenanceRequest.status.in_(["open", "pending", "reported"])
            )
        )
    )).scalars().all()

    total_unassigned = len(unassigned_hk) + len(unassigned_maint)

    if total_unassigned == 0:
        logger.debug(f"[{hotel_name}] No unassigned tasks found")
        return

    # Count by priority
    urgent_hk = len([t for t in unassigned_hk if t.priority in ["urgent", "critical", "high"]])
    urgent_maint = len([t for t in unassigned_maint if t.priority in ["urgent", "critical", "high"]])
    total_urgent = urgent_hk + urgent_maint

    # Get admin/manager users to notify
    admins = (await session.execute(
        select(User).where(
            and_(
                User.role.in_(["admin", "manager", "supervisor"]),
                User.is_active == True
            )
        )
    )).scalars().all()

    # Create notification message
    message = f"You have {total_unassigned} unassigned task(s) pending:\n"
    if len(unassigned_hk) > 0:
        message += f"- {len(unassigned_hk)} housekeeping task(s)"
        if urgent_hk > 0:
            message += f" ({urgent_hk} urgent)"
        message += "\n"
    if len(unassigned_maint) > 0:
        message += f"- {len(unassigned_maint)} maintenance request(s)"
        if urgent_maint > 0:
            message += f" ({urgent_maint} urgent)"
        message += "\n"
    message += "\nPlease review and assign these tasks."

    # Create notifications for each admin
    for admin in admins:
        notification = StaffNotification(
            staff_id=admin.id,
            notification_type="unassigned_tasks_reminder",
            title="Unassigned Tasks Pending",
            message=message,
            priority="high" if total_urgent > 0 else "normal",
            is_read=False,
            created_at=datetime.utcnow()
        )
        session.add(notification)

    await session.commit()
    logger.info(f"[{hotel_name}] Sent unassigned task reminders to {len(admins)} admin(s). Total unassigned: {total_unassigned}")


async def check_unassigned_tasks():
    """
    Check for unassigned housekeeping and maintenance tasks and notify admins.
    Runs at end of day/week to alert about pending tasks.
    Schedule: Daily at 5:00 PM, or Fridays for weekly summary

    Multi-tenant: Processes all active hotels.
    """
    logger.info("Checking for unassigned tasks...")

    try:
        await _run_for_all_hotels(_check_unassigned_for_hotel, "check_unassigned_tasks")
    except Exception as e:
        logger.error(f"Error in check_unassigned_tasks: {str(e)}")


async def run_daily_tasks():
    """
    Run all daily scheduled tasks
    This function should be called daily (e.g., via cron or scheduler)
    """
    logger.info("Running daily scheduled tasks...")
    await send_precheckin_reminders()
    await check_unassigned_tasks()  # Check for unassigned tasks daily
    logger.info("Daily scheduled tasks completed")


# ============== WHATSAPP NOTIFICATION JOBS ==============

async def _send_whatsapp_checkin_reminders_for_hotel(session: AsyncSession, hotel):
    """
    Send WhatsApp check-in reminders for guests checking in within the next hour.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    from app.services.whatsapp_service import get_whatsapp_service
    from app.models.reservations import Booking
    from app.models.inventory import RoomType

    hotel_name = hotel.name if hotel else "Glimmora Hotel"
    whatsapp_service = get_whatsapp_service()

    if not whatsapp_service or not whatsapp_service.is_enabled:
        logger.debug(f"[{hotel_name}] WhatsApp service not available, skipping check-in reminders")
        return

    today = date.today()
    now = datetime.now()

    # Get default check-in time from settings
    checkin_hour = settings.default_checkin_time_hour

    # Calculate the check-in datetime for today
    checkin_time = datetime.combine(today, datetime.min.time().replace(hour=checkin_hour))

    # Check if current time is approximately 1 hour before check-in (within 5 minute window)
    time_until_checkin = (checkin_time - now).total_seconds() / 60  # in minutes

    # Only send reminders if we're within the window (55-65 minutes before check-in)
    if not (55 <= time_until_checkin <= 65):
        logger.debug(f"[{hotel_name}] Not within check-in reminder window ({time_until_checkin:.0f} min to check-in)")
        return

    # Find bookings arriving today that are still pending/confirmed
    bookings = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date == today,
                Booking.status.in_(["booked", "confirmed"]),
            )
        )
    )).all()

    if not bookings:
        logger.debug(f"[{hotel_name}] No bookings found for check-in reminder on {today}")
        return

    sent_count = 0
    for booking in bookings:
        try:
            # Get guest
            guest = await session.get(Guest, booking.guest_id)
            if not guest or not guest.phone:
                continue

            # Check if we already sent a WhatsApp reminder for this booking (using GuestCommunication or activity log)
            # For now, we'll track via GuestActivityLog to avoid duplicate messages
            from app.models.crm_extended import GuestActivityLog

            existing_reminder = (await session.exec(
                select(GuestActivityLog).where(
                    and_(
                        GuestActivityLog.guest_id == guest.id,
                        GuestActivityLog.activity_type == "whatsapp_checkin_reminder",
                        GuestActivityLog.related_entity_id == booking.id,
                        GuestActivityLog.timestamp >= datetime.combine(today, datetime.min.time())
                    )
                )
            )).first()

            if existing_reminder:
                continue  # Already sent today

            # Get room type
            room_type = await session.get(RoomType, booking.room_type_id)
            room_type_name = room_type.name if room_type else "Standard Room"

            # Format check-in time
            checkin_time_str = f"{checkin_hour % 12 or 12}:00 {'PM' if checkin_hour >= 12 else 'AM'}"

            # Send WhatsApp message
            result = whatsapp_service.send_checkin_reminder(
                to_phone=guest.phone,
                guest_name=f"{guest.first_name} {guest.last_name}".strip(),
                hotel_name=hotel_name,
                checkin_time=checkin_time_str,
                room_type=room_type_name,
                booking_code=booking.confirmation_code
            )

            if result.get("success"):
                sent_count += 1

                # Log the activity
                import json
                activity_log = GuestActivityLog(
                    property_id=1,
                    guest_id=guest.id,
                    activity_type="whatsapp_checkin_reminder",
                    description=f"Check-in reminder sent via WhatsApp for booking {booking.confirmation_code}",
                    related_entity_type="booking",
                    related_entity_id=booking.id,
                    activity_metadata=json.dumps({
                        "message_sid": result.get("message_sid"),
                        "phone": guest.phone,
                        "booking_code": booking.confirmation_code,
                    }),
                    platform="whatsapp",
                    timestamp=datetime.utcnow(),
                )
                session.add(activity_log)

                logger.info(f"[{hotel_name}] Sent WhatsApp check-in reminder to {guest.phone} for booking {booking.confirmation_code}")
            else:
                logger.warning(f"[{hotel_name}] Failed to send WhatsApp to {guest.phone}: {result.get('error')}")

        except Exception as e:
            logger.error(f"[{hotel_name}] Error sending check-in reminder for booking {booking.id}: {e}")
            continue

    if sent_count > 0:
        await session.commit()
        logger.info(f"[{hotel_name}] WhatsApp check-in reminders sent: {sent_count}/{len(bookings)}")


async def send_whatsapp_checkin_reminders():
    """
    Send WhatsApp check-in reminders to guests checking in within the next hour.
    Schedule: Every 5 minutes (configured via whatsapp_reminder_interval_minutes)

    Multi-tenant: Processes all active hotels.
    """
    if not settings.whatsapp_enabled:
        return

    try:
        await _run_for_all_hotels(_send_whatsapp_checkin_reminders_for_hotel, "send_whatsapp_checkin_reminders")
    except Exception as e:
        logger.error(f"Error in send_whatsapp_checkin_reminders: {str(e)}")


async def _send_whatsapp_checkout_reminders_for_hotel(session: AsyncSession, hotel):
    """
    Send WhatsApp check-out reminders for guests checking out within the next hour.

    Args:
        session: Database session for the hotel
        hotel: Hotel object (None in single-tenant mode)
    """
    from app.services.whatsapp_service import get_whatsapp_service
    from app.models.reservations import Booking
    from app.models.inventory import Room

    hotel_name = hotel.name if hotel else "Glimmora Hotel"
    whatsapp_service = get_whatsapp_service()

    if not whatsapp_service or not whatsapp_service.is_enabled:
        logger.debug(f"[{hotel_name}] WhatsApp service not available, skipping check-out reminders")
        return

    today = date.today()
    now = datetime.now()

    # Get default check-out time from settings
    checkout_hour = settings.default_checkout_time_hour

    # Calculate the check-out datetime for today
    checkout_time = datetime.combine(today, datetime.min.time().replace(hour=checkout_hour))

    # Check if current time is approximately 1 hour before check-out (within 5 minute window)
    time_until_checkout = (checkout_time - now).total_seconds() / 60  # in minutes

    # Only send reminders if we're within the window (55-65 minutes before check-out)
    if not (55 <= time_until_checkout <= 65):
        logger.debug(f"[{hotel_name}] Not within check-out reminder window ({time_until_checkout:.0f} min to check-out)")
        return

    # Find bookings checking out today that are currently checked-in
    bookings = (await session.exec(
        select(Booking).where(
            and_(
                Booking.departure_date == today,
                Booking.status == "checked_in",
            )
        )
    )).all()

    if not bookings:
        logger.debug(f"[{hotel_name}] No checked-in guests found for check-out reminder on {today}")
        return

    sent_count = 0
    for booking in bookings:
        try:
            # Get guest
            guest = await session.get(Guest, booking.guest_id)
            if not guest or not guest.phone:
                continue

            # Check if we already sent a WhatsApp reminder for this booking today
            from app.models.crm_extended import GuestActivityLog

            existing_reminder = (await session.exec(
                select(GuestActivityLog).where(
                    and_(
                        GuestActivityLog.guest_id == guest.id,
                        GuestActivityLog.activity_type == "whatsapp_checkout_reminder",
                        GuestActivityLog.related_entity_id == booking.id,
                        GuestActivityLog.timestamp >= datetime.combine(today, datetime.min.time())
                    )
                )
            )).first()

            if existing_reminder:
                continue  # Already sent today

            # Get room number
            room = await session.get(Room, booking.room_id) if booking.room_id else None
            room_number = room.number if room else "N/A"

            # Format check-out time
            checkout_time_str = f"{checkout_hour % 12 or 12}:00 {'PM' if checkout_hour >= 12 else 'AM'}"

            # Send WhatsApp message
            result = whatsapp_service.send_checkout_reminder(
                to_phone=guest.phone,
                guest_name=f"{guest.first_name} {guest.last_name}".strip(),
                hotel_name=hotel_name,
                checkout_time=checkout_time_str,
                room_number=room_number,
                booking_code=booking.confirmation_code
            )

            if result.get("success"):
                sent_count += 1

                # Log the activity
                import json
                activity_log = GuestActivityLog(
                    property_id=1,
                    guest_id=guest.id,
                    activity_type="whatsapp_checkout_reminder",
                    description=f"Check-out reminder sent via WhatsApp for booking {booking.confirmation_code}",
                    related_entity_type="booking",
                    related_entity_id=booking.id,
                    activity_metadata=json.dumps({
                        "message_sid": result.get("message_sid"),
                        "phone": guest.phone,
                        "booking_code": booking.confirmation_code,
                        "room_number": room_number,
                    }),
                    platform="whatsapp",
                    timestamp=datetime.utcnow(),
                )
                session.add(activity_log)

                logger.info(f"[{hotel_name}] Sent WhatsApp check-out reminder to {guest.phone} for booking {booking.confirmation_code}")
            else:
                logger.warning(f"[{hotel_name}] Failed to send WhatsApp to {guest.phone}: {result.get('error')}")

        except Exception as e:
            logger.error(f"[{hotel_name}] Error sending check-out reminder for booking {booking.id}: {e}")
            continue

    if sent_count > 0:
        await session.commit()
        logger.info(f"[{hotel_name}] WhatsApp check-out reminders sent: {sent_count}/{len(bookings)}")


async def send_whatsapp_checkout_reminders():
    """
    Send WhatsApp check-out reminders to guests checking out within the next hour.
    Schedule: Every 5 minutes (configured via whatsapp_reminder_interval_minutes)

    Multi-tenant: Processes all active hotels.
    """
    if not settings.whatsapp_enabled:
        return

    try:
        await _run_for_all_hotels(_send_whatsapp_checkout_reminders_for_hotel, "send_whatsapp_checkout_reminders")
    except Exception as e:
        logger.error(f"Error in send_whatsapp_checkout_reminders: {str(e)}")


# Alias for day-before reminder (for APScheduler job naming)
send_day_before_precheckin_reminders = send_precheckin_reminders


if __name__ == "__main__":
    # For testing: run the scheduler manually
    asyncio.run(run_daily_tasks())

