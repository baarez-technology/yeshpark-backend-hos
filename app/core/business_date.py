"""
Business Date Helper — the hotel's operational date.

The business date only advances when night audit completes.
It does NOT auto-change at midnight. All revenue, arrivals,
departures, and front-desk operations reference this date.
"""
from datetime import date

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.operations import HotelConfig


async def get_business_date(session: AsyncSession) -> date:
    """Return the current hotel business date.
    Falls back to calendar date if HotelConfig row doesn't exist yet."""
    config = (await session.exec(select(HotelConfig))).first()
    if config and config.business_date:
        return config.business_date
    return date.today()


async def get_hotel_config(session: AsyncSession) -> HotelConfig:
    """Return the singleton HotelConfig, creating it if missing."""
    config = (await session.exec(select(HotelConfig))).first()
    if not config:
        config = HotelConfig(business_date=date.today())
        session.add(config)
        await session.commit()
        await session.refresh(config)
    return config


async def advance_business_date(session: AsyncSession, new_date: date, audit_by: int) -> HotelConfig:
    """Advance business date (called by night audit on completion)."""
    from datetime import datetime
    config = await get_hotel_config(session)
    config.business_date = new_date
    config.last_audit_completed_at = datetime.utcnow()
    config.last_audit_by = audit_by
    config.updated_at = datetime.utcnow()
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config
