from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request, Query
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime

from app.core.security import create_access_token, verify_password, get_password_hash
from app.core.config import settings
from app.db.tenant_manager import tenant_manager
from app.db.session import async_session_maker
from app.models.user import User
from app.models.password_reset import PasswordResetToken
from app.models.reservations import Guest
from app.schemas.auth import Token, UserPublic, LoginRequest, SignupRequest, ForgotPasswordRequest, ResetPasswordRequest, SetFirstPasswordRequest
from app.services.background_email import send_password_reset_email_bg
from contextlib import asynccontextmanager

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


@asynccontextmanager
async def _get_auth_session(hotel_code: Optional[str] = None):
    """Get a DB session for auth operations. Falls back to legacy single-DB when multi-tenant is off."""
    if settings.multi_tenant_enabled:
        if not hotel_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="hotel_code is required"
            )
        async for session in tenant_manager.get_session(hotel_code):
            yield session
            return
    else:
        async with async_session_maker() as session:
            yield session


async def authenticate_user(session: AsyncSession, email: str, password: str) -> Optional[User]:
    """Authenticate user against the given session."""
    email = email.lower().strip()
    result = await session.exec(select(User).where(User.email == email))
    user = result.first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest):
    """Login with email, password, and hotel_code (hotel_code optional in single-tenant mode)."""
    try:
        async with _get_auth_session(payload.hotel_code) as session:
            user = await authenticate_user(session, payload.email, payload.password)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect email or password"
                )

            # Check if temp password has expired (72-hour window)
            if user.must_reset_password and user.temp_password_expires_at:
                if datetime.utcnow() > user.temp_password_expires_at:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Temporary password has expired. Please contact your administrator for a new one."
                    )

            # Update last login timestamp
            user.last_login = datetime.utcnow()
            await session.commit()

            # Create token with hotel_code (None in single-tenant mode)
            token = create_access_token(
                subject=str(user.id),
                hotel_code=payload.hotel_code if settings.multi_tenant_enabled else None
            )
            return Token(
                access_token=token,
                must_reset_password=user.must_reset_password or False,
                first_login=user.first_login or False,
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/token", response_model=Token)
async def login_form(
    email: str = Query(...),
    password: str = Query(...),
    hotel_code: str = Query(None),
):
    """OAuth2 compatible token endpoint."""
    try:
        async with _get_auth_session(hotel_code) as session:
            user = await authenticate_user(session, email, password)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect email or password"
                )

            user.last_login = datetime.utcnow()
            await session.commit()

            token = create_access_token(
                subject=str(user.id),
                hotel_code=hotel_code if settings.multi_tenant_enabled else None
            )
            return Token(access_token=token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Get current user from JWT token. Falls back to legacy session in single-tenant mode."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id: Optional[str] = payload.get("sub")
        hotel_code: Optional[str] = payload.get("hotel_code")

        if user_id is None:
            raise credentials_exception
        # hotel_code is only required in multi-tenant mode
        if settings.multi_tenant_enabled and not hotel_code:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    try:
        async with _get_auth_session(hotel_code) as session:
            result = await session.exec(select(User).where(User.id == int(user_id)))
            user = result.first()
            if user is None:
                raise credentials_exception
            return user
    except (ValueError, HTTPException):
        raise credentials_exception


async def get_current_user_sse(
    request: Request,
    token_query: Optional[str] = Query(None, alias="token"),
) -> User:
    """Auth for SSE endpoint: accept token from header or query param."""
    token: Optional[str] = token_query
    if not token and request.headers.get("authorization"):
        parts = request.headers["authorization"].split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await get_current_user(token)


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optional),
) -> Optional[User]:
    """Get current user if token is provided, otherwise return None."""
    if not token:
        return None

    try:
        return await get_current_user(token)
    except HTTPException:
        return None


async def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """Verify user is a superuser."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have sufficient permissions"
        )
    return current_user


@router.post("/signup", response_model=UserPublic)
async def signup(payload: SignupRequest):
    """Register a new user (hotel_code optional in single-tenant mode)."""
    try:
        async with _get_auth_session(payload.hotel_code) as session:
            normalized_email = payload.email.lower().strip()

            # Check if user already exists
            result = await session.exec(select(User).where(User.email == normalized_email))
            if result.first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )

            # Check for existing guest
            existing_guest = (await session.exec(
                select(Guest).where(Guest.email == normalized_email)
            )).first()

            # Parse name
            full_name = payload.full_name or "Guest"
            name_parts = full_name.strip().split(' ', 1)
            first_name = name_parts[0] if name_parts else "Guest"
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            try:
                # Create user
                new_user = User(
                    email=normalized_email,
                    full_name=full_name,
                    phone=payload.phone,
                    hashed_password=get_password_hash(payload.password),
                    is_active=True,
                    is_superuser=False,
                    role="guest",
                    hotel_code=payload.hotel_code if settings.multi_tenant_enabled else None,
                )
                session.add(new_user)
                await session.flush()

                # Link or create guest record
                if existing_guest:
                    existing_guest.user_id = new_user.id
                    existing_guest.first_name = first_name
                    existing_guest.last_name = last_name
                    existing_guest.phone = payload.phone or existing_guest.phone
                    existing_guest.updated_at = datetime.utcnow()
                else:
                    new_guest = Guest(
                        user_id=new_user.id,
                        first_name=first_name,
                        last_name=last_name,
                        email=normalized_email,
                        phone=payload.phone,
                        status='Active',
                        member_since=datetime.utcnow(),
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                    session.add(new_guest)

                await session.commit()
                await session.refresh(new_user)

                return UserPublic(
                    id=new_user.id,
                    email=new_user.email,
                    full_name=new_user.full_name,
                    role=new_user.role,
                    is_superuser=new_user.is_superuser,
                )

            except Exception as e:
                await session.rollback()
                import logging
                logging.error(f"Signup error: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create account"
                )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/me", response_model=UserPublic)
async def read_users_me(current_user: User = Depends(get_current_user)):
    """Get current user info including permissions and onboarding flags."""
    import json as json_module
    permissions = None
    if current_user.permissions:
        try:
            permissions = json_module.loads(current_user.permissions) if isinstance(current_user.permissions, str) else current_user.permissions
        except Exception:
            permissions = None

    return UserPublic(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_superuser=current_user.is_superuser,
        must_reset_password=current_user.must_reset_password or False,
        first_login=current_user.first_login or False,
        permissions=permissions,
    )


@router.post("/set-first-password")
async def set_first_password(
    payload: SetFirstPasswordRequest,
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    """
    Set password on first login. Clears must_reset_password and first_login flags.
    Called after a staff member logs in with their temp password.
    """
    if not current_user.must_reset_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset not required for this account"
        )

    # Get hotel_code from the request for session resolution
    hotel_code = None
    if settings.multi_tenant_enabled and request:
        hotel_code = request.headers.get("x-hotel-code") or request.query_params.get("hotel_code")

    async with _get_auth_session(hotel_code) as session:
        user = await session.get(User, current_user.id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.hashed_password = get_password_hash(payload.new_password)
        user.must_reset_password = False
        user.first_login = False
        user.temp_password_expires_at = None
        user.updated_at = datetime.utcnow()
        await session.commit()

    return {"message": "Password updated successfully"}


@router.post("/refresh", response_model=Token)
async def refresh_token(current_user: User = Depends(get_current_user)):
    """Refresh access token."""
    token = create_access_token(
        subject=str(current_user.id),
        hotel_code=current_user.hotel_code if settings.multi_tenant_enabled else None
    )
    return Token(access_token=token)


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, background_tasks: BackgroundTasks):
    """Request password reset (hotel_code optional in single-tenant mode)."""
    try:
        async with _get_auth_session(payload.hotel_code) as session:
            normalized_email = payload.email.lower().strip()

            result = await session.exec(select(User).where(User.email == normalized_email))
            user = result.first()

            if user and user.is_active:
                # Invalidate existing tokens
                existing_tokens = await session.exec(
                    select(PasswordResetToken).where(
                        and_(
                            PasswordResetToken.user_id == user.id,
                            PasswordResetToken.used == False,
                            PasswordResetToken.expires_at > datetime.utcnow()
                        )
                    )
                )
                for token in existing_tokens.all():
                    token.used = True
                    token.used_at = datetime.utcnow()

                # Create new reset token
                reset_token = PasswordResetToken.create_token(user_id=user.id, expires_in_hours=1)
                session.add(reset_token)
                await session.commit()
                await session.refresh(reset_token)

                # Send email in background - doesn't block response
                reset_url = f"{settings.frontend_url}/reset-password?token={reset_token.token}"
                background_tasks.add_task(
                    send_password_reset_email_bg,
                    to_email=user.email,
                    reset_token=reset_token.token,
                    reset_url=reset_url,
                    user_name=user.full_name,
                )

            # Always return success (prevent email enumeration)
            return {"message": "If an account exists, a reset link has been sent."}

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest):
    """Reset password using token (hotel_code optional in single-tenant mode)."""
    try:
        async with _get_auth_session(payload.hotel_code) as session:
            result = await session.exec(
                select(PasswordResetToken).where(PasswordResetToken.token == payload.token)
            )
            reset_token = result.first()

            if not reset_token or not reset_token.is_valid():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired reset token"
                )

            user = await session.get(User, reset_token.user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            user.hashed_password = get_password_hash(payload.new_password)
            user.updated_at = datetime.utcnow()
            reset_token.mark_as_used()

            await session.commit()

            return {"message": "Password reset successfully"}

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/verify-reset-token")
async def verify_reset_token(token: str, hotel_code: str = None):
    """Verify if reset token is valid (hotel_code optional in single-tenant mode)."""
    try:
        async with _get_auth_session(hotel_code) as session:
            result = await session.exec(
                select(PasswordResetToken).where(PasswordResetToken.token == token)
            )
            reset_token = result.first()

            if not reset_token or not reset_token.is_valid():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired reset token"
                )

            return {"valid": True}

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/verify-email")
async def verify_email(payload: dict):
    """Verify email using OTP token (hotel_code optional in single-tenant mode)."""
    from app.models.otp import EmailOTP

    token = payload.get("token")
    hotel_code = payload.get("hotel_code")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="token is required"
        )

    try:
        async with _get_auth_session(hotel_code) as session:
            result = await session.exec(
                select(EmailOTP).where(
                    and_(
                        EmailOTP.otp_code == token,
                        EmailOTP.purpose == "email_verification",
                        EmailOTP.verified == False
                    )
                )
            )
            otp = result.first()

            if not otp or not otp.is_valid():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired verification token"
                )

            user_result = await session.exec(
                select(User).where(User.email == otp.email)
            )
            user = user_result.first()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            user.email_verified = True
            user.updated_at = datetime.utcnow()
            otp.mark_as_verified()

            await session.commit()

            return {"message": "Email verified successfully", "verified": True}

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
