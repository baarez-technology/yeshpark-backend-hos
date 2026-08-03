from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, and_, or_, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel
from datetime import datetime, date

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.payment_method import PaymentMethod
from app.models.reservations import Reservation, Guest
from app.models.precheckin import PreCheckIn
from app.schemas.reservations import ReservationRead

router = APIRouter()


def require_admin(current_user: User):
    """Check if user is admin"""
    if current_user.role != "admin" and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


class AdminPaymentMethodRead(BaseModel):
    id: int
    user_id: int
    user_email: str
    user_name: Optional[str]
    card_type: str
    last4: str
    expiry_month: int
    expiry_year: int
    cardholder_name: Optional[str] = None
    is_default: bool
    is_active: bool
    created_at: str

    class Config:
        from_attributes = True


class AdminUserPreferencesRead(BaseModel):
    user_id: int
    email: str
    full_name: Optional[str]
    preferences: Optional[dict] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class AdminPreCheckInRead(BaseModel):
    id: int
    reservation_id: int
    guest_id: int
    guest_name: Optional[str]
    guest_email: str
    status: str
    floor_preference: Optional[str] = None
    view_preference: Optional[str] = None
    bed_type_preference: Optional[str] = None
    quietness_preference: Optional[str] = None
    arrival_time: Optional[str] = None
    flight_number: Optional[str] = None
    purpose: Optional[str] = None
    transportation_needed: bool = False
    pillow_type: Optional[str] = None
    temperature: Optional[int] = None
    minibar_preferences: Optional[str] = None
    dietary_restrictions: Optional[str] = None
    special_requests: Optional[str] = None
    early_check_in: bool = False
    late_check_out: bool = False
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("/payment-methods", response_model=List[AdminPaymentMethodRead])
async def admin_list_payment_methods(
    user_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Admin: Get all payment methods (all users)"""
    require_admin(current_user)
    
    query = select(PaymentMethod, User).join(User, PaymentMethod.user_id == User.id).where(
        PaymentMethod.deleted_at.is_(None)
    )
    
    if user_id:
        query = query.where(PaymentMethod.user_id == user_id)
    
    result = await session.exec(query.order_by(PaymentMethod.created_at.desc()))
    items = result.all()
    
    payment_methods = []
    for payment_method, user in items:
        payment_methods.append(AdminPaymentMethodRead(
            id=payment_method.id,
            user_id=payment_method.user_id,
            user_email=user.email,
            user_name=user.full_name,
            card_type=payment_method.card_type,
            last4=payment_method.last4,
            expiry_month=payment_method.expiry_month,
            expiry_year=payment_method.expiry_year,
            cardholder_name=payment_method.cardholder_name,
            is_default=payment_method.is_default,
            is_active=payment_method.is_active,
            created_at=payment_method.created_at.isoformat() if payment_method.created_at else "",
        ))
    
    return payment_methods


@router.get("/user-preferences", response_model=List[AdminUserPreferencesRead])
async def admin_list_user_preferences(
    user_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Admin: Get all user preferences"""
    require_admin(current_user)
    
    query = select(User).where(User.preferences.isnot(None))
    
    if user_id:
        query = query.where(User.id == user_id)
    
    result = await session.exec(query.order_by(User.updated_at.desc()))
    users = result.all()
    
    preferences_list = []
    for user in users:
        import json
        prefs = None
        if user.preferences:
            try:
                prefs = json.loads(user.preferences)
            except:
                pass
        
        preferences_list.append(AdminUserPreferencesRead(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            preferences=prefs,
            created_at=user.created_at.isoformat() if user.created_at else "",
            updated_at=user.updated_at.isoformat() if user.updated_at else "",
        ))
    
    return preferences_list


@router.get("/precheckins", response_model=List[AdminPreCheckInRead])
async def admin_list_precheckins(
    status: Optional[str] = Query(None),
    reservation_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Admin: Get all pre-checkins"""
    require_admin(current_user)
    
    query = select(PreCheckIn, Guest).join(Guest, PreCheckIn.guest_id == Guest.id)
    
    if status:
        query = query.where(PreCheckIn.status == status)
    if reservation_id:
        query = query.where(PreCheckIn.reservation_id == reservation_id)
    
    result = await session.exec(query.order_by(PreCheckIn.created_at.desc()))
    items = result.all()
    
    precheckins = []
    for precheckin, guest in items:
        precheckins.append(AdminPreCheckInRead(
            id=precheckin.id,
            reservation_id=precheckin.reservation_id,
            guest_id=precheckin.guest_id,
            guest_name=f"{guest.first_name} {guest.last_name}" if guest.first_name and guest.last_name else None,
            guest_email=precheckin.email,
            status=precheckin.status,
            floor_preference=precheckin.floor_preference,
            view_preference=precheckin.view_preference,
            bed_type_preference=precheckin.bed_type_preference,
            quietness_preference=precheckin.quietness_preference,
            arrival_time=precheckin.arrival_time,
            flight_number=precheckin.flight_number,
            purpose=precheckin.purpose,
            transportation_needed=precheckin.transportation_needed,
            pillow_type=precheckin.pillow_type,
            temperature=precheckin.temperature,
            minibar_preferences=precheckin.minibar_preferences,
            dietary_restrictions=precheckin.dietary_restrictions,
            special_requests=precheckin.special_requests,
            early_check_in=precheckin.early_check_in,
            late_check_out=precheckin.late_check_out,
            created_at=precheckin.created_at.isoformat() if precheckin.created_at else "",
            updated_at=precheckin.updated_at.isoformat() if precheckin.updated_at else "",
        ))
    
    return precheckins


@router.get("/bookings")
async def admin_list_all_bookings(
    status: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    limit: int = Query(1000, le=1000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Admin: Get all bookings with filters and relations"""
    require_admin(current_user)
    
    query = select(Reservation, Guest).join(Guest, Reservation.guest_id == Guest.id)
    
    if status:
        query = query.where(Reservation.status == status)
    if from_date:
        query = query.where(Reservation.arrival_date >= from_date)
    if to_date:
        query = query.where(Reservation.arrival_date <= to_date)
    
    query = query.order_by(Reservation.created_at.desc()).limit(limit).offset(offset)
    
    result = await session.exec(query)
    items = result.all()
    
    # Build response with relations
    bookings = []
    for reservation, guest in items:
        # Get room if assigned
        room = None
        room_type_name = "Standard Room"
        if reservation.room_id:
            from app.models.inventory import Room, RoomType
            room = await session.get(Room, reservation.room_id)
            if room and room.room_type_id:
                rt = await session.get(RoomType, room.room_type_id)
                if rt:
                    room_type_name = rt.name

        booking_data = {
            "id": reservation.id,
            "confirmation_code": reservation.confirmation_code,
            "guest_id": reservation.guest_id,
            "room_id": reservation.room_id,
            "rate_plan_id": reservation.rate_plan_id,
            "arrival_date": reservation.arrival_date.isoformat() if reservation.arrival_date else None,
            "departure_date": reservation.departure_date.isoformat() if reservation.departure_date else None,
            "adults": reservation.adults,
            "children": reservation.children,
            "status": reservation.status,
            "total_amount": float(reservation.total_amount) if reservation.total_amount else 0.0,
            "payment_status": getattr(reservation, 'payment_status', 'pending'),
            "booking_source": getattr(reservation, 'booking_source', 'direct'),
            "currency": reservation.currency,
            "special_requests": reservation.special_requests,
            "group_code": reservation.group_code,
            "created_at": reservation.created_at.isoformat() if reservation.created_at else None,
            "guest": {
                "id": guest.id,
                "first_name": guest.first_name,
                "last_name": guest.last_name,
                "email": guest.email,
                "phone": guest.phone,
            },
            "room": {
                "id": room.id,
                "number": room.number,
                "name": room_type_name,
                "room_type": room_type_name,
            } if room else None,
        }
        bookings.append(booking_data)
    
    return bookings

