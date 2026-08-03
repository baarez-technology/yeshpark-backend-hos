from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.models.otp import EmailOTP
from app.services.background_email import send_otp_email_bg
from app.core.config import settings

router = APIRouter()


class OTPRequest(BaseModel):
    email: str
    purpose: str = "booking_payment"
    booking_id: Optional[int] = None


class OTPVerifyRequest(BaseModel):
    email: str
    otp_code: str
    purpose: str = "booking_payment"
    booking_id: Optional[int] = None


@router.post("/send")
async def send_otp(
    payload: OTPRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
):
    """
    Send OTP to email for verification
    """
    # Normalize email
    normalized_email = payload.email.lower().strip()
    
    # Invalidate any existing unverified OTPs for this email and purpose
    existing_otps = await session.exec(
        select(EmailOTP).where(
            and_(
                EmailOTP.email == normalized_email,
                EmailOTP.purpose == payload.purpose,
                EmailOTP.verified == False,
                EmailOTP.expires_at > datetime.utcnow()
            )
        )
    )
    for otp in existing_otps.all():
        otp.verified = True  # Mark as used/invalid
    
    # Create new OTP
    otp = EmailOTP.create_otp(
        email=normalized_email,
        purpose=payload.purpose,
        booking_id=payload.booking_id,
        expires_in_minutes=10
    )
    session.add(otp)
    await session.commit()
    await session.refresh(otp)
    
    # Send email in background - doesn't block response
    background_tasks.add_task(
        send_otp_email_bg,
        to_email=normalized_email,
        otp_code=otp.otp_code,
        purpose=payload.purpose,
    )
    
    # Always return success (security best practice)
    return {
        "message": "OTP has been sent to your email address",
        "expires_in_minutes": 10
    }


@router.post("/verify")
async def verify_otp(
    payload: OTPVerifyRequest,
    session: AsyncSession = Depends(get_tenant_session),
):
    """
    Verify OTP code
    """
    # Normalize email
    normalized_email = payload.email.lower().strip()
    
    # Find OTP
    query = select(EmailOTP).where(
        and_(
            EmailOTP.email == normalized_email,
            EmailOTP.otp_code == payload.otp_code,
            EmailOTP.purpose == payload.purpose,
        )
    )
    
    if payload.booking_id:
        query = query.where(EmailOTP.booking_id == payload.booking_id)
    
    result = await session.exec(query)
    otp = result.first()
    
    if not otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OTP code"
        )
    
    if not otp.is_valid():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired or has already been used"
        )
    
    # Mark as verified
    otp.mark_as_verified()
    await session.commit()
    
    return {
        "message": "OTP verified successfully",
        "verified": True
    }

