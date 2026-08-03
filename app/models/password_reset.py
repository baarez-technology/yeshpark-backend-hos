from datetime import datetime, timedelta
from typing import Optional
from sqlmodel import SQLModel, Field
import secrets


class PasswordResetToken(SQLModel, table=True):
    """Password reset tokens with expiration"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token: str = Field(index=True, unique=True)  # Secure random token
    expires_at: datetime = Field(index=True)
    used: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    used_at: Optional[datetime] = None

    @staticmethod
    def generate_token() -> str:
        """Generate a secure random token"""
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_token(user_id: int, expires_in_hours: int = 1) -> "PasswordResetToken":
        """Create a new password reset token"""
        return PasswordResetToken(
            user_id=user_id,
            token=PasswordResetToken.generate_token(),
            expires_at=datetime.utcnow() + timedelta(hours=expires_in_hours),
            used=False,
        )

    def is_valid(self) -> bool:
        """Check if token is valid (not used and not expired)"""
        return not self.used and datetime.utcnow() < self.expires_at

    def mark_as_used(self):
        """Mark token as used"""
        self.used = True
        self.used_at = datetime.utcnow()

