from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import field_validator

# Get the absolute path to the database file in the Backend directory
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _BACKEND_DIR / "glimmora.db"


class Settings(BaseSettings):
    environment: str = "development"
    secret_key: str = "change_me_in_prod"
    access_token_expire_minutes: int = 60
    database_url: str = f"sqlite:///{_DB_PATH}"
    redis_url: str = "redis://localhost:6379/0"
    first_superuser_email: str = "admin@glimmora.local"
    first_superuser_password: str = "admin123"

    # Multi-tenant database settings
    multi_tenant_enabled: bool = False  # Feature flag for gradual rollout
    master_database_url: str = "postgresql+asyncpg://glimmora:password@localhost:5432/glimmora_master"
    hotel_database_template: str = "postgresql+asyncpg://glimmora:password@localhost:5432/{db_name}"

    # PostgreSQL connection details (for provisioning)
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "glimmora"
    db_password: str = "password"

    # Email settings
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    email_sender: str = "baarezrpa@gmail.com"
    email_sender_password: str = "euyy oree jspc tanj"

    # Resend settings (requires domain verification)
    resend_api_key: str = ""  # Set RESEND_API_KEY in .env
    use_resend: bool = False  # Set to True to use Resend
    resend_from_email: str = "onboarding@resend.dev"

    # Brevo settings (preferred - no domain verification needed, 300 emails/day free)
    brevo_api_key: str = ""  # Set BREVO_API_KEY in .env
    use_brevo: bool = True  # Set to False to use SMTP instead
    brevo_from_email: str = "baarezrpa@gmail.com"  # Your verified sender email
    brevo_from_name: str = "Glimmora Hotel"

    # Frontend URL for password reset links, feedback emails, etc.
    frontend_url: str = "http://localhost:5173"

    @field_validator("frontend_url")
    @classmethod
    def ensure_frontend_url_has_protocol(cls, v: str) -> str:
        """Ensure frontend_url has a protocol prefix to prevent broken email links."""
        v = v.rstrip("/")
        if v and not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        return v

    # OpenAI API settings for AI Assistant
    openai_api_key: str = ""  # Set in .env file as OPENAI_API_KEY
    openai_model: str = "gpt-3.5-turbo"  # Set in .env file as OPENAI_MODEL, defaults to gpt-3.5-turbo

    # Admin AI Multi-Agent Architecture feature flag
    admin_ai_multi_agent_enabled: bool = True  # Set ADMIN_AI_MULTI_AGENT_ENABLED=false to rollback

    # Auto-cancellation and reminder settings
    auto_cancel_refund_percentage: float = 0.5  # 50% refund on auto-cancel
    precheckin_reminder_1_hour: int = 10  # 10 AM - day before arrival reminder
    precheckin_reminder_2_hour: int = 8   # 8 AM - arrival day reminder
    auto_cancel_hour: int = 23  # 11:59 PM - auto cancel time
    auto_cancel_minute: int = 59

    # Encryption
    encryption_key: str = ""

    # Razorpay Payment Gateway
    razorpay_enabled: bool = False
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    payment_currency: str = "INR"
    payment_auto_capture: bool = True

    # Redis lock settings
    redis_lock_ttl_seconds: int = 900  # 15 minutes
    redis_lock_extend_seconds: int = 300  # 5 minutes extension

    # Twilio WhatsApp Business API settings (all from .env)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""  # e.g., "whatsapp:+14155238886"
    whatsapp_enabled: bool = False

    # Default check-in/check-out times for WhatsApp reminders
    default_checkin_time_hour: int = 14  # 2 PM default check-in
    default_checkout_time_hour: int = 11  # 11 AM default check-out
    whatsapp_reminder_interval_minutes: int = 5  # How often to run reminder check

    # Background task intervals
    hold_cleanup_interval_seconds: int = 60  # Every 60 seconds
    room_sync_interval_minutes: int = 5  # Every 5 minutes
    waitlist_process_interval_minutes: int = 5  # Every 5 minutes
    stale_lock_cleanup_interval_minutes: int = 2  # Every 2 minutes

    class Config:
        env_file = ".env"
        case_sensitive = False
        # Allow reading multi-line values (for long API keys)
        env_file_encoding = 'utf-8'
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
