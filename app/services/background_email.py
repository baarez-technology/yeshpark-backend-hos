"""
Background email helpers.

Every function in this module is designed to be passed to
FastAPI's ``BackgroundTasks.add_task()`` so that SMTP calls
never block an API response.

Usage in an endpoint::

    from app.services.background_email import send_otp_email_bg

    @router.post("/send")
    async def send_otp(background_tasks: BackgroundTasks, ...):
        ...
        background_tasks.add_task(send_otp_email_bg, to_email=..., otp_code=..., purpose=...)
        return {"message": "OTP sent"}
"""

import logging

logger = logging.getLogger(__name__)


def _get_email_service():
    from app.services.email_service import get_email_service
    return get_email_service()


# ── OTP ───────────────────────────────────────────────────────────────────────

def send_otp_email_bg(*, to_email: str, otp_code: str, purpose: str):
    try:
        _get_email_service().send_otp_email(
            to_email=to_email, otp_code=otp_code, purpose=purpose,
        )
        logger.info(f"Sent OTP email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send OTP email to {to_email}: {e}")


# ── AUTH ──────────────────────────────────────────────────────────────────────

def send_password_reset_email_bg(*, to_email: str, reset_token: str, reset_url: str, user_name: str):
    try:
        _get_email_service().send_password_reset_email(
            to_email=to_email, reset_token=reset_token, reset_url=reset_url, user_name=user_name,
        )
        logger.info(f"Sent password reset email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send password reset email to {to_email}: {e}")


# ── BOOKING CONFIRMATION ─────────────────────────────────────────────────────

def send_booking_confirmation_email_bg(
    *, to_email: str, booking_number: str, guest_name: str,
    check_in: str, check_out: str, room_type: str, room_number,
    total_amount: float, currency: str, precheckin_url: str, pdf_content
):
    try:
        _get_email_service().send_booking_confirmation_email(
            to_email=to_email, booking_number=booking_number,
            guest_name=guest_name, check_in=check_in, check_out=check_out,
            room_type=room_type, room_number=room_number,
            total_amount=total_amount, currency=currency,
            precheckin_url=precheckin_url, pdf_content=pdf_content,
        )
        logger.info(f"Sent booking confirmation email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send booking confirmation email to {to_email}: {e}")


# ── BOOKING MODIFICATION ─────────────────────────────────────────────────────

def send_booking_modification_email_bg(
    *, to_email: str, guest_name: str, booking_number: str,
    room_type: str, original_check_in: str, original_check_out: str,
    new_check_in: str, new_check_out: str,
    original_total: float, new_total: float, balance_amount: float, currency: str
):
    try:
        _get_email_service().send_booking_modification_email(
            to_email=to_email, guest_name=guest_name,
            booking_number=booking_number, room_type=room_type,
            original_check_in=original_check_in, original_check_out=original_check_out,
            new_check_in=new_check_in, new_check_out=new_check_out,
            original_total=original_total, new_total=new_total,
            balance_amount=balance_amount, currency=currency,
        )
        logger.info(f"Sent booking modification email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send booking modification email to {to_email}: {e}")


# ── CHECKOUT THANK YOU ────────────────────────────────────────────────────────

def send_checkout_thank_you_email_bg(
    *, to_email: str, guest_name: str, booking_number: str,
    room_number: str, room_type: str, check_in_date: str,
    check_out_date: str, nights_stayed: int, total_spent: float,
    currency: str, loyalty_points_earned: int, is_vip: bool, feedback_url: str
):
    try:
        _get_email_service().send_checkout_thank_you_email(
            to_email=to_email, guest_name=guest_name,
            booking_number=booking_number, room_number=room_number,
            room_type=room_type, check_in_date=check_in_date,
            check_out_date=check_out_date, nights_stayed=nights_stayed,
            total_spent=total_spent, currency=currency,
            loyalty_points_earned=loyalty_points_earned,
            is_vip=is_vip, feedback_url=feedback_url,
        )
        logger.info(f"Sent checkout thank you email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send checkout thank you email to {to_email}: {e}")


# ── PRE-CHECKIN CONFIRMATION ─────────────────────────────────────────────────

def send_precheckin_confirmation_email_bg(
    *, to_email: str, guest_name: str, booking_number: str,
    room_number: str, room_type: str, check_in_date: str,
    check_out_date: str, digital_key_id: str, qr_code: str,
    qr_image_base64: str
):
    try:
        from app.services.email_service import email_service
        if email_service:
            email_service.send_precheckin_confirmation_email(
                to_email=to_email, guest_name=guest_name,
                booking_number=booking_number, room_number=room_number,
                room_type=room_type, check_in_date=check_in_date,
                check_out_date=check_out_date, digital_key_id=digital_key_id,
                qr_code=qr_code, qr_image_base64=qr_image_base64,
            )
            logger.info(f"Sent pre-checkin confirmation email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send pre-checkin confirmation email to {to_email}: {e}")


# ── GUEST MESSAGE ─────────────────────────────────────────────────────────────

def send_guest_email_bg(*, to_email: str, subject: str, html_body: str, text_body: str):
    try:
        _get_email_service().send_email(
            to_email=to_email, subject=subject, html_body=html_body, text_body=text_body,
        )
        logger.info(f"Sent guest message email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send guest message email to {to_email}: {e}")


# ── STAFF WELCOME ─────────────────────────────────────────────────────────────

def send_staff_welcome_email_bg(*, to_email: str, staff_name: str, role: str, department: str, password: str, work_email: str = None):
    try:
        kwargs = dict(
            to_email=to_email, staff_name=staff_name,
            role=role, department=department, password=password,
        )
        if work_email is not None:
            kwargs["work_email"] = work_email
        _get_email_service().send_staff_welcome_email(**kwargs)
        logger.info(f"Sent staff welcome email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send staff welcome email to {to_email}: {e}")


# ── TASK ASSIGNMENT ───────────────────────────────────────────────────────────

def send_task_assignment_email_bg(
    *, to_email: str, staff_name: str, task_type: str,
    room_number: str, priority: str, notes: str = None
):
    try:
        _get_email_service().send_task_assignment_email(
            to_email=to_email, staff_name=staff_name,
            task_type=task_type, room_number=room_number,
            priority=priority, notes=notes,
        )
        logger.info(f"Sent task assignment email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send task assignment email to {to_email}: {e}")


# ── TASK ACCEPTED / DECLINED ─────────────────────────────────────────────────

def send_task_accepted_email_bg(
    *, to_email: str, admin_name: str, staff_name: str,
    task_id: int, task_type: str, room_number: str, accepted_at: str
):
    try:
        _get_email_service().send_task_accepted_email(
            to_email=to_email, admin_name=admin_name,
            staff_name=staff_name, task_id=task_id,
            task_type=task_type, room_number=room_number,
            accepted_at=accepted_at,
        )
        logger.info(f"Sent task accepted email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send task accepted email to {to_email}: {e}")


def send_task_declined_email_bg(
    *, to_email: str, admin_name: str, staff_name: str,
    task_id: int, task_type: str, room_number: str,
    decline_reason: str, declined_at: str, priority: str
):
    try:
        _get_email_service().send_task_declined_email(
            to_email=to_email, admin_name=admin_name,
            staff_name=staff_name, task_id=task_id,
            task_type=task_type, room_number=room_number,
            decline_reason=decline_reason, declined_at=declined_at,
            priority=priority,
        )
        logger.info(f"Sent task declined email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send task declined email to {to_email}: {e}")


# ── SHIFT ASSIGNMENT ──────────────────────────────────────────────────────────

def send_shift_assignment_email_bg(
    *, to_email: str, staff_name: str, shift_date: str,
    shift_type: str, start_time: str, end_time: str
):
    try:
        _get_email_service().send_shift_assignment_email(
            to_email=to_email, staff_name=staff_name,
            shift_date=shift_date, shift_type=shift_type,
            start_time=start_time, end_time=end_time,
        )
        logger.info(f"Sent shift assignment email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send shift assignment email to {to_email}: {e}")


# ── LEAVE STATUS ──────────────────────────────────────────────────────────────

def send_leave_status_email_bg(
    *, to_email: str, staff_name: str, leave_type: str,
    start_date: str, end_date: str, status: str, rejection_reason: str = None
):
    try:
        _get_email_service().send_leave_status_email(
            to_email=to_email, staff_name=staff_name,
            leave_type=leave_type, start_date=start_date,
            end_date=end_date, status=status,
            rejection_reason=rejection_reason,
        )
        logger.info(f"Sent leave status email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send leave status email to {to_email}: {e}")


# ── STAFF MESSAGE ─────────────────────────────────────────────────────────────

def send_staff_message_email_bg(
    *, to_email: str, staff_name: str, subject: str,
    message: str, priority: str, sender_name: str
):
    try:
        _get_email_service().send_staff_message_email(
            to_email=to_email, staff_name=staff_name,
            subject=subject, message=message,
            priority=priority, sender_name=sender_name,
        )
        logger.info(f"Sent staff message email to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send staff message email to {to_email}: {e}")