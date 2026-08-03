from typing import Optional
from pydantic import BaseModel, EmailStr, validator


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_reset_password: bool = False
    first_login: bool = False


class LoginRequest(BaseModel):
    email: str  # Changed from EmailStr to str for more lenient validation
    password: str
    hotel_code: Optional[str] = None  # Required for multi-tenant mode

    @validator('email')
    def validate_email(cls, v: str) -> str:
        # Basic email validation - more lenient than EmailStr
        if not v or '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower().strip()


class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    hotel_code: Optional[str] = None  # Required for multi-tenant mode

    @validator('email')
    def validate_email(cls, v: str) -> str:
        if not v or '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower().strip()

    @validator('password')
    def validate_password(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v


class UserPublic(BaseModel):
    id: int
    email: str  # Changed from EmailStr to str to support .local domains
    full_name: Optional[str] = None
    role: str
    is_superuser: bool
    must_reset_password: bool = False
    first_login: bool = False
    permissions: Optional[dict] = None


class SetFirstPasswordRequest(BaseModel):
    new_password: str

    @validator('new_password')
    def validate_password(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one number')
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
            raise ValueError('Password must contain at least one special character')
        return v


class ForgotPasswordRequest(BaseModel):
    email: str
    hotel_code: Optional[str] = None

    @validator('email')
    def validate_email(cls, v: str) -> str:
        if not v or '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower().strip()


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    hotel_code: Optional[str] = None

    @validator('new_password')
    def validate_password(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v


