from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def create_access_token(
    subject: str,
    hotel_code: Optional[str] = None,
    expires_minutes: Optional[int] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        subject: User ID or identifier to encode in the token
        hotel_code: Hotel code for multi-tenant isolation (optional)
        expires_minutes: Token expiration time in minutes (default from settings)

    Returns:
        Encoded JWT token string
    """
    if expires_minutes is None:
        expires_minutes = settings.access_token_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

    to_encode = {
        "exp": expire,
        "sub": str(subject),
    }

    # Include hotel_code for multi-tenant support
    if hotel_code:
        to_encode["hotel_code"] = hotel_code

    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


