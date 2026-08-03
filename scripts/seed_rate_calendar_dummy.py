"""
Seed dummy DailyRate data for Revenue -> Rate Calendar.

Use this to populate the Rate Calendar with test data so you can verify:
- Rate Calendar display (GET /api/v1/revenue-intelligence/rates/calendar)
- Bulk edit (PUT /api/v1/revenue-intelligence/rates/bulk-update)

Only inserts DailyRate rows for BAR plan; does not modify room types, reservations,
or other features. Safe to run multiple times (skips dates that already have a rate).

Usage (from project root):
    python scripts/seed_rate_calendar_dummy.py

Optional env:
    RATE_CALENDAR_DAYS=60   Number of days to seed (default 60 from today)
"""
import sys
from pathlib import Path

# Allow running as: python scripts/seed_rate_calendar_dummy.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import os
import random
from datetime import date, timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import async_session_maker, init_db
from app.models.inventory import RoomType, RatePlan, DailyRate


# Default: seed 60 days from today so calendar has plenty of rows to bulk-edit
SEED_DAYS = int(os.environ.get("RATE_CALENDAR_DAYS", "60"))


async def ensure_bar_plan(session: AsyncSession) -> RatePlan | None:
    """Get BAR rate plan; create if missing so Rate Calendar and bulk update work."""
    result = await session.exec(select(RatePlan).where(RatePlan.code == "BAR").limit(1))
    bar = result.first()
    if bar:
        return bar
    bar = RatePlan(
        code="BAR",
        name="Best Available Rate",
        plan_type="BAR",
        currency="INR",
        base_price=0.0,
        is_active=True,
    )
    session.add(bar)
    await session.commit()
    await session.refresh(bar)
    return bar


async def seed_rate_calendar_dummy():
    await init_db()
    async with async_session_maker() as session:
        # Resolve BAR plan (required for Revenue Rate Calendar and bulk update)
        bar_plan = await ensure_bar_plan(session)
        if not bar_plan:
            print("ERROR: Could not get or create BAR rate plan.")
            return

        # Active room types only
        rt_result = await session.exec(select(RoomType).where(RoomType.is_active == True))
        room_types = rt_result.all()
        if not room_types:
            print("WARNING: No active room types. Create room types first, then re-run this script.")
            return

        start = date.today()
        end = start + timedelta(days=SEED_DAYS - 1)
        added = 0
        skipped = 0

        for room_type in room_types:
            base = float(room_type.base_price or 100.0)
            current = start
            while current <= end:
                # Skip if we already have a BAR DailyRate for this room_type + date
                existing = await session.exec(
                    select(DailyRate).where(
                        DailyRate.room_type_id == room_type.id,
                        DailyRate.rate_plan_id == bar_plan.id,
                        DailyRate.date == current,
                    ).limit(1)
                )
                if existing.first():
                    skipped += 1
                    current += timedelta(days=1)
                    continue

                # Dummy rate: base + small random variation so calendar shows different values
                variation = random.uniform(-0.15, 0.25)
                rate = round(base * (1 + variation), 2)
                rate = max(rate, 10.0)

                dr = DailyRate(
                    room_type_id=room_type.id,
                    rate_plan_id=bar_plan.id,
                    date=current,
                    base_rate=base,
                    override_rate=rate,
                    is_active=True,
                )
                session.add(dr)
                added += 1
                current += timedelta(days=1)

        await session.commit()
        print(f"Rate Calendar dummy data: added {added} DailyRate rows, skipped {skipped} (already present).")
        print(f"Room types: {len(room_types)}, date range: {start} to {end}.")
        print("Open Revenue -> Rate Calendar and test bulk edit.")


if __name__ == "__main__":
    asyncio.run(seed_rate_calendar_dummy())
