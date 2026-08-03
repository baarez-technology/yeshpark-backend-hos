from datetime import datetime, timedelta
from typing import Optional
from sqlmodel import SQLModel, Field
import secrets
import random


class EmailOTP(SQLModel, table=True):
    """Email OTP for verification"""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    otp_code: str = Field(index=True)  # 6-digit OTP
    purpose: str = Field(index=True)  # 'booking_payment', 'email_verification', etc.
    booking_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)
    expires_at: datetime = Field(index=True)
    verified: bool = Field(default=False, index=True)
    verified_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    @staticmethod
    def generate_otp() -> str:
        """Generate a 6-digit OTP"""
        return f"{random.randint(100000, 999999)}"

    @staticmethod
    def create_otp(
        email: str,
        purpose: str,
        booking_id: Optional[int] = None,
        expires_in_minutes: int = 10
    ) -> "EmailOTP":
        """Create a new OTP"""
        return EmailOTP(
            email=email.lower().strip(),
            otp_code=EmailOTP.generate_otp(),
            purpose=purpose,
            booking_id=booking_id,
            expires_at=datetime.utcnow() + timedelta(minutes=expires_in_minutes),
            verified=False,
        )

    def is_valid(self) -> bool:
        """Check if OTP is valid (not verified and not expired)"""
        return not self.verified and datetime.utcnow() < self.expires_at

    def mark_as_verified(self):
        """Mark OTP as verified"""
        self.verified = True
        self.verified_at = datetime.utcnow()

