from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, EmailStr

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.core.security import get_password_hash, verify_password

router = APIRouter()


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    preferences: Optional[str] = None  # JSON string


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserProfileResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    role: str
    is_superuser: bool

    class Config:
        from_attributes = True


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get current user profile"""
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        phone=current_user.phone,
        address=current_user.address,
        city=current_user.city,
        zip_code=current_user.zip_code,
        country=current_user.country,
        role=current_user.role,
        is_superuser=current_user.is_superuser,
    )


@router.patch("/profile", response_model=UserProfileResponse)
async def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Update user profile and sync to Guest record"""
    from app.models.reservations import Guest
    import logging

    logging.info(f"[Users API] Updating profile for user {current_user.id} ({current_user.email})")
    logging.info(f"[Users API] Payload: {payload.model_dump(exclude_unset=True)}")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, key, value)

    await session.commit()
    await session.refresh(current_user)

    logging.info(f"[Users API] User updated - full_name: {current_user.full_name}")

    # Sync name and contact info to Guest record
    if payload.full_name or payload.phone or payload.address:
        try:
            # Find guest by user_id first
            guest_result = await session.exec(
                select(Guest).where(Guest.user_id == current_user.id)
            )
            guest = guest_result.first()
            logging.info(f"[Users API] Guest by user_id {current_user.id}: {guest}")

            # If not found by user_id, try by email (case insensitive)
            if not guest and current_user.email:
                user_email = current_user.email.lower().strip()
                guest_result = await session.exec(
                    select(Guest).where(Guest.email == user_email)
                )
                guest = guest_result.first()
                logging.info(f"[Users API] Guest by email '{user_email}': {guest}")

                if guest and not guest.user_id:
                    guest.user_id = current_user.id
                    logging.info(f"[Users API] Linked user_id {current_user.id} to Guest {guest.id}")

            if guest:
                old_name = f"{guest.first_name} {guest.last_name}"

                # Sync name - split full_name into first_name and last_name
                if payload.full_name:
                    name_parts = payload.full_name.strip().split(maxsplit=1)
                    guest.first_name = name_parts[0] if name_parts else ""
                    guest.last_name = name_parts[1] if len(name_parts) > 1 else ""

                # Sync contact info
                if payload.phone:
                    guest.phone = payload.phone
                if payload.address:
                    guest.address = payload.address
                if payload.city:
                    guest.city = payload.city
                if payload.zip_code:
                    guest.postal_code = payload.zip_code  # Guest uses postal_code, not zip_code
                if payload.country:
                    guest.country = payload.country

                # Also ensure user_id is linked
                if not guest.user_id:
                    guest.user_id = current_user.id

                guest.updated_at = datetime.utcnow()
                await session.commit()
                await session.refresh(guest)

                new_name = f"{guest.first_name} {guest.last_name}"
                logging.info(f"[Users API] Synced profile to Guest ID {guest.id}: '{old_name}' -> '{new_name}'")
            else:
                logging.warning(f"[Users API] No guest record found for user {current_user.id} ({current_user.email})")
        except Exception as e:
            logging.error(f"[Users API] Error syncing profile to Guest: {e}")
            import traceback
            traceback.print_exc()
            # Don't fail the request if guest sync fails

    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        phone=current_user.phone,
        address=current_user.address,
        city=current_user.city,
        zip_code=current_user.zip_code,
        country=current_user.country,
        role=current_user.role,
        is_superuser=current_user.is_superuser,
    )


@router.post("/sync-guest")
async def sync_profile_to_guest(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Force sync current user profile to Guest record"""
    from app.models.reservations import Guest

    if not current_user.full_name:
        raise HTTPException(status_code=400, detail="Profile name is not set")

    try:
        # Find guest by user_id or email
        guest_result = await session.exec(
            select(Guest).where(Guest.user_id == current_user.id)
        )
        guest = guest_result.first()

        if not guest and current_user.email:
            guest_result = await session.exec(
                select(Guest).where(Guest.email == current_user.email.lower().strip())
            )
            guest = guest_result.first()
            if guest and not guest.user_id:
                guest.user_id = current_user.id

        if not guest:
            raise HTTPException(status_code=404, detail="No guest record found for this user")

        # Sync name
        name_parts = current_user.full_name.strip().split(maxsplit=1)
        old_name = f"{guest.first_name} {guest.last_name}"
        guest.first_name = name_parts[0] if name_parts else ""
        guest.last_name = name_parts[1] if len(name_parts) > 1 else ""

        # Sync contact info if available
        if current_user.phone:
            guest.phone = current_user.phone
        if current_user.address:
            guest.address = current_user.address
        if current_user.city:
            guest.city = current_user.city
        if current_user.zip_code:
            guest.postal_code = current_user.zip_code  # Guest uses postal_code
        if current_user.country:
            guest.country = current_user.country

        guest.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(guest)

        return {
            "success": True,
            "message": f"Guest record updated from '{old_name}' to '{guest.first_name} {guest.last_name}'",
            "guest_id": guest.id,
            "new_name": f"{guest.first_name} {guest.last_name}"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync: {str(e)}")


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Change user password"""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    # Update password
    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.updated_at = datetime.utcnow()

    # Ensure the session tracks the changes
    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)

    return {"success": True, "message": "Password changed successfully"}


@router.get("/preferences")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get user preferences"""
    import json
    if current_user.preferences:
        try:
            return json.loads(current_user.preferences)
        except:
            return {}
    return {}


@router.post("/preferences")
async def save_preferences(
    preferences: dict,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Save user preferences and sync to Guest record"""
    import json
    from app.models.reservations import Guest

    # Save to User table
    current_user.preferences = json.dumps(preferences)
    await session.commit()
    await session.refresh(current_user)

    # Also sync to Guest table - find guest by user_id or email
    try:
        # First try to find guest by user_id
        guest_result = await session.exec(
            select(Guest).where(Guest.user_id == current_user.id)
        )
        guest = guest_result.first()

        # If not found by user_id, try by email
        if not guest and current_user.email:
            guest_result = await session.exec(
                select(Guest).where(Guest.email == current_user.email.lower().strip())
            )
            guest = guest_result.first()

            # If found by email, also link user_id for future lookups
            if guest and not guest.user_id:
                guest.user_id = current_user.id

        if guest:
            # Sync preferences to guest record
            guest.preferences = preferences  # Guest.preferences is JSON column, stores dict directly
            guest.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(guest)
            print(f"[Users API] Synced preferences to Guest ID {guest.id}")
    except Exception as e:
        print(f"[Users API] Warning: Could not sync preferences to Guest: {e}")
        # Don't fail the request if guest sync fails

    return {"success": True, "preferences": json.loads(current_user.preferences)}

