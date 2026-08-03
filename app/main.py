from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from starlette.routing import Route
from starlette.convertors import Convertor, CONVERTOR_TYPES
from app.core.config import settings


# Custom path convertor that only matches positive integers
# This ensures routes like /available are not matched by /{staff_id:posint}
class PositiveIntConvertor(Convertor):
    regex = "[1-9][0-9]*"  # Matches positive integers (no leading zeros)

    def convert(self, value: str) -> int:
        return int(value)

    def to_string(self, value: int) -> str:
        return str(value)


# Register the custom convertor
CONVERTOR_TYPES["posint"] = PositiveIntConvertor()
from app.services.email_service import init_email_service
from app.services.scheduler import (
    send_day_before_precheckin_reminders,
    send_arrival_day_precheckin_reminders,
    auto_cancel_no_precheckin_bookings,
    cleanup_expired_holds,
    sync_room_statuses,
    process_waitlist_conversions,
    cleanup_stale_locks,
    send_whatsapp_checkin_reminders,
    send_whatsapp_checkout_reminders,
)
from app.api.routes import api_router
from app.db.session import init_db, init_master_db
from app.db.tenant_manager import tenant_manager
from app.middleware.tenant import TenantMiddleware
import logging

# Import ALL models to ensure they're registered with SQLModel
# This is critical for SQLModel to create all tables via metadata.create_all()
from app.models import *  # Import all models from __init__.py

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()


async def sync_business_date_on_startup():
    """
    Auto-recovery: Sync business date with calendar date on server startup.

    This handles scenarios where:
    - Night audit was run multiple times during testing
    - Business date advanced ahead of the real calendar date
    - Server was restarted on a new day

    For POC/testing environments, this ensures the system is always usable.
    In production, this behavior can be controlled via settings.
    """
    from datetime import date, datetime
    from sqlmodel import select
    from app.db.session import async_session_maker
    from app.models.operations import HotelConfig, NightAudit

    try:
        async with async_session_maker() as session:
            result = await session.exec(select(HotelConfig))
            config = result.first()

            if not config:
                return

            today = date.today()

            if config.business_date > today:
                days_ahead = (config.business_date - today).days
                logger.warning(
                    f"Business date {config.business_date} is {days_ahead} day(s) ahead of calendar. "
                    f"Auto-correcting for POC environment..."
                )

                # Clean up future-dated night audit records
                future_audits = (await session.exec(
                    select(NightAudit).where(NightAudit.audit_date >= today)
                )).all()

                for audit in future_audits:
                    await session.delete(audit)
                    logger.info(f"Cleaned up audit record for {audit.audit_date}")

                # Reset business date to today
                config.business_date = today
                config.updated_at = datetime.utcnow()
                session.add(config)
                await session.commit()

                logger.info(f"Business date auto-corrected to {today}")
            else:
                logger.info(f"Business date: {config.business_date} (calendar: {today})")

    except Exception as e:
        logger.warning(f"Could not sync business date on startup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database(s)
    if settings.multi_tenant_enabled:
        # Initialize master database for multi-tenant mode
        await init_master_db()
        logger.info("Master database initialized (multi-tenant mode)")
    else:
        # Initialize single database for legacy mode
        await init_db()
        logger.info("Database initialized (single-tenant mode)")

    # Auto-sync business date for POC/testing environments
    if not settings.multi_tenant_enabled:
        await sync_business_date_on_startup()

    # Initialize email service (Brevo preferred, Resend/SMTP fallback)
    init_email_service(
        smtp_server=settings.smtp_server,
        smtp_port=settings.smtp_port,
        sender_email=settings.email_sender,
        sender_password=settings.email_sender_password,
        use_tls=settings.smtp_use_tls,
        resend_api_key=settings.resend_api_key,
        use_resend=settings.use_resend,
        resend_from_email=settings.resend_from_email,
        brevo_api_key=settings.brevo_api_key,
        use_brevo=settings.use_brevo,
        brevo_from_email=settings.brevo_from_email,
        brevo_from_name=settings.brevo_from_name,
    )

    # Initialize Redis Lock Manager (with fallback if Redis unavailable)
    try:
        from app.services.redis_lock_service import init_lock_manager
        await init_lock_manager(settings.redis_url)
        logger.info("Redis Lock Manager initialized")
    except Exception as e:
        logger.warning(f"Redis Lock Manager unavailable, using DB-only mode: {e}")

    # Initialize WhatsApp service if enabled (credentials from .env)
    if settings.whatsapp_enabled:
        try:
            from app.services.whatsapp_service import init_whatsapp_service
            init_whatsapp_service(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                from_number=settings.twilio_whatsapp_from,
            )
            logger.info("WhatsApp service initialized")
        except Exception as e:
            logger.warning(f"WhatsApp service unavailable: {e}")

    # === CRON JOBS (Daily scheduled tasks) ===

    # Job 1: Day-before reminder - runs at 10 AM daily
    scheduler.add_job(
        send_day_before_precheckin_reminders,
        CronTrigger(hour=settings.precheckin_reminder_1_hour, minute=0),
        id="day_before_precheckin_reminder",
        replace_existing=True,
        name="Pre-checkin reminder (day before arrival)"
    )

    # Job 2: Arrival day reminder - runs at 8 AM daily
    scheduler.add_job(
        send_arrival_day_precheckin_reminders,
        CronTrigger(hour=settings.precheckin_reminder_2_hour, minute=0),
        id="arrival_day_precheckin_reminder",
        replace_existing=True,
        name="Pre-checkin reminder (arrival day)"
    )

    # Job 3: Auto-cancel and refund - runs at 11:59 PM daily
    scheduler.add_job(
        auto_cancel_no_precheckin_bookings,
        CronTrigger(hour=settings.auto_cancel_hour, minute=settings.auto_cancel_minute),
        id="auto_cancel_no_precheckin",
        replace_existing=True,
        name="Auto-cancel bookings without pre-checkin"
    )

    # === INTERVAL JOBS (Continuous background tasks) ===

    # Job 4: Cleanup expired holds - every 60 seconds
    scheduler.add_job(
        cleanup_expired_holds,
        IntervalTrigger(seconds=settings.hold_cleanup_interval_seconds),
        id="cleanup_expired_holds",
        replace_existing=True,
        name="Cleanup expired room holds and stale Redis locks"
    )

    # Job 5: Sync room statuses - every 5 minutes
    scheduler.add_job(
        sync_room_statuses,
        IntervalTrigger(minutes=settings.room_sync_interval_minutes),
        id="sync_room_statuses",
        replace_existing=True,
        name="Sync room status with booking state"
    )

    # Job 6: Process waitlist conversions - every 5 minutes
    scheduler.add_job(
        process_waitlist_conversions,
        IntervalTrigger(minutes=settings.waitlist_process_interval_minutes),
        id="process_waitlist_conversions",
        replace_existing=True,
        name="Auto-book waitlist when rooms available"
    )

    # Job 7: Cleanup stale locks - every 2 minutes
    scheduler.add_job(
        cleanup_stale_locks,
        IntervalTrigger(minutes=settings.stale_lock_cleanup_interval_minutes),
        id="cleanup_stale_locks",
        replace_existing=True,
        name="Release locks for cancelled/checked-out bookings"
    )

    # === WHATSAPP NOTIFICATION JOBS (if enabled) ===
    if settings.whatsapp_enabled:
        # Job 8: WhatsApp check-in reminders - every 5 minutes
        scheduler.add_job(
            send_whatsapp_checkin_reminders,
            IntervalTrigger(minutes=settings.whatsapp_reminder_interval_minutes),
            id="whatsapp_checkin_reminder",
            replace_existing=True,
            name="WhatsApp check-in reminders (1 hour before)"
        )

        # Job 9: WhatsApp check-out reminders - every 5 minutes
        scheduler.add_job(
            send_whatsapp_checkout_reminders,
            IntervalTrigger(minutes=settings.whatsapp_reminder_interval_minutes),
            id="whatsapp_checkout_reminder",
            replace_existing=True,
            name="WhatsApp check-out reminders (1 hour before)"
        )

    # Start the scheduler
    scheduler.start()
    job_count = 9 if settings.whatsapp_enabled else 7
    logger.info(f"APScheduler started with {job_count} scheduled jobs:")
    logger.info(f"  CRON JOBS:")
    logger.info(f"    - Day-before reminder: {settings.precheckin_reminder_1_hour}:00")
    logger.info(f"    - Arrival day reminder: {settings.precheckin_reminder_2_hour}:00")
    logger.info(f"    - Auto-cancel: {settings.auto_cancel_hour}:{settings.auto_cancel_minute:02d}")
    logger.info(f"  INTERVAL JOBS:")
    logger.info(f"    - Cleanup expired holds: every {settings.hold_cleanup_interval_seconds}s")
    logger.info(f"    - Sync room statuses: every {settings.room_sync_interval_minutes}min")
    logger.info(f"    - Process waitlist: every {settings.waitlist_process_interval_minutes}min")
    logger.info(f"    - Cleanup stale locks: every {settings.stale_lock_cleanup_interval_minutes}min")
    if settings.whatsapp_enabled:
        logger.info(f"  WHATSAPP JOBS:")
        logger.info(f"    - WhatsApp check-in reminders: every {settings.whatsapp_reminder_interval_minutes}min")
        logger.info(f"    - WhatsApp check-out reminders: every {settings.whatsapp_reminder_interval_minutes}min")

    # Start SSE Redis subscriber only if Redis is reachable (avoids reconnection spam when Redis is not running)
    try:
        from app.api.v1 import webhooks as webhooks_module
        if await webhooks_module.sse_redis_available():
            sse_task = webhooks_module.start_sse_redis_subscriber_background()
            if sse_task is not None:
                logger.info("SSE Redis subscriber started (multi-worker SSE enabled)")
        else:
            logger.info("SSE Redis not reachable; using local-only broadcast (single worker). Set REDIS_URL and run Redis for multi-worker SSE.")
    except Exception as e:
        logger.debug(f"SSE Redis subscriber not started: {e}")

    yield

    # Shutdown: Cancel SSE Redis subscriber task
    try:
        from app.api.v1 import webhooks as webhooks_module
        if getattr(webhooks_module, "_sse_redis_subscriber_task", None) is not None:
            webhooks_module._sse_redis_subscriber_task.cancel()
            logger.info("SSE Redis subscriber task cancelled")
    except Exception as e:
        logger.debug(f"Error cancelling SSE Redis subscriber: {e}")

    # Shutdown: Stop the scheduler
    scheduler.shutdown()
    logger.info("APScheduler shut down")

    # Close Redis Lock Manager
    try:
        from app.services.redis_lock_service import close_lock_manager
        await close_lock_manager()
        logger.info("Redis Lock Manager closed")
    except Exception as e:
        logger.debug(f"Error closing Redis Lock Manager: {e}")

    # Close all tenant database connections (multi-tenant mode)
    if settings.multi_tenant_enabled:
        await tenant_manager.close_all()
        logger.info("All tenant database connections closed")


app = FastAPI(title="Glimmora API", version="0.1.0", lifespan=lifespan)

# Add tenant middleware BEFORE CORS (for multi-tenant hotel context extraction)
if settings.multi_tenant_enabled:
    app.add_middleware(TenantMiddleware)

# CORS configuration - allow all origins for development (no credentials)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Ensure 500 and other errors return CORS headers (browser otherwise shows CORS error instead of 500)
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )

app.include_router(api_router, prefix="/api")

@app.get("/health")
async def health():
    return {"status": "ok"}

