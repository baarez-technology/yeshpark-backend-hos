from datetime import date
from typing import List, Optional, Tuple
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.inventory import Room, RatePlan
from app.models.reservations import Reservation


async def find_available_rooms(
    session: AsyncSession,
    arrival_date: date,
    departure_date: date,
    adults: int = 1,
    children: int = 0,
    room_type: Optional[str] = None,
) -> List[Room]:
    """Find available rooms - now uses the comprehensive check_availability from reservation_service"""
    from app.services.reservation_service import check_availability
    return await check_availability(session, arrival_date, departure_date, room_type, adults)


async def rate_for_room(session: AsyncSession, rate_plan_id: int) -> Tuple[float, str]:
    rp = (await session.execute(select(RatePlan).where(RatePlan.id == rate_plan_id))).scalars().first()
    if not rp or not rp.is_active:
        return 0.0, "INR"
    return rp.base_price, rp.currency


