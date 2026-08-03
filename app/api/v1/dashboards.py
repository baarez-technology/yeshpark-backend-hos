from datetime import date, datetime, timedelta
from typing import Optional, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, func, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.reservations import Reservation, Booking, Guest
from app.models.operations import Folio, Payment, HousekeepingTask, MaintenanceRequest
from app.models.inventory import Room, RoomType
from app.models.user import User
from app.models.dashboards import DashboardWidget, DashboardLayout
from app.models.staff import Staff
from app.core.business_date import get_business_date

router = APIRouter()


# Comprehensive list of staff roles that have read access to dashboards
DASHBOARD_STAFF_ROLES = [
    "admin", "manager", "owner", "superuser",
    # Front office roles
    "front_desk", "frontdesk", "reception", "receptionist",
    "front_office_manager", "front_office", "guest_services",
    # Management roles
    "general_manager", "gm", "assistant_manager", "duty_manager",
    "management", "operations_manager", "operations",
    # Department heads
    "housekeeping_manager", "maintenance_manager", "revenue_manager",
    "finance", "finance_manager", "accounting",
    # Other staff with dashboard access
    "concierge", "night_auditor", "supervisor",
    # Frontend RBAC roles (must stay in sync with frontend rolePermissions.ts)
    "reservation_manager", "housekeeper", "accounts_manager",
]


@router.get("/admin")
async def admin_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Comprehensive Admin dashboard with all real-time metrics"""
    if current_user.role not in DASHBOARD_STAFF_ROLES and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Staff access required")

    today = await get_business_date(session)
    week_start = today - timedelta(days=7)
    last_week_start = week_start - timedelta(days=7)
    month_start = today.replace(day=1)

    # ============== ROOMS METRICS ==============
    all_rooms = (await session.exec(select(Room))).all()
    total_rooms = len(all_rooms)

    # Room status breakdown — derive from compound fields for accuracy
    room_status_counts = {"available": 0, "occupied": 0, "dirty": 0, "clean": 0, "inspected": 0, "in_progress": 0, "maintenance": 0, "out_of_service": 0, "out_of_order": 0}
    for room in all_rooms:
        occ = getattr(room, 'occupancy_status', None) or 'vacant'
        cln = getattr(room, 'cleaning_status', None)
        raw = room.status or "available"
        if occ == 'occupied' or raw == 'occupied':
            status = 'occupied'
        elif raw in ('out_of_service', 'out_of_order', 'maintenance'):
            status = raw
        elif cln in ('dirty', 'in_progress', 'inspected', 'clean'):
            status = cln
        elif raw in ("cleaning",):
            status = "in_progress"
        else:
            status = raw
        if status in room_status_counts:
            room_status_counts[status] += 1
        else:
            room_status_counts["available"] += 1

    # Occupied rooms from reservations (checked_in status)
    occupied_reservations = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date <= today,
                Booking.departure_date > today,
                Booking.status == "checked_in"
            )
        )
    )).all()
    occupied_rooms = len(occupied_reservations)

    # Available rooms (not occupied, not out of service, not out of order)
    out_of_service = room_status_counts.get("out_of_service", 0)
    out_of_order = room_status_counts.get("out_of_order", 0)
    unavailable_rooms = out_of_service + out_of_order
    available_rooms = total_rooms - occupied_rooms - unavailable_rooms
    dirty_rooms = room_status_counts.get("dirty", 0)
    in_progress_rooms = room_status_counts.get("in_progress", 0)

    # Occupancy rate (OOO rooms are not bookable, OOS can be sold in emergency)
    bookable_rooms = total_rooms - out_of_order
    occupancy_rate = (occupied_rooms / bookable_rooms * 100) if bookable_rooms > 0 else 0

    # ============== BOOKINGS METRICS ==============
    # Today's arrivals (expected check-ins)
    today_arrivals = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date == today,
                Booking.status.in_(["booked", "confirmed"])
            )
        )
    )).all()
    checkins_today = len(today_arrivals)

    # Today's departures (expected check-outs)
    today_departures = (await session.exec(
        select(Booking).where(
            and_(
                Booking.departure_date == today,
                Booking.status == "checked_in"
            )
        )
    )).all()
    checkouts_today = len(today_departures)

    # Bookings this week
    week_bookings = (await session.exec(
        select(Booking).where(
            and_(
                Booking.created_at >= datetime.combine(week_start, datetime.min.time()),
                Booking.status.in_(["booked", "confirmed", "checked_in", "checked_out"])
            )
        )
    )).all()
    bookings_this_week = len(week_bookings)

    # Last week bookings for trend
    last_week_bookings = (await session.exec(
        select(Booking).where(
            and_(
                Booking.created_at >= datetime.combine(last_week_start, datetime.min.time()),
                Booking.created_at < datetime.combine(week_start, datetime.min.time()),
                Booking.status.in_(["booked", "confirmed", "checked_in", "checked_out"])
            )
        )
    )).all()
    last_week_bookings_count = len(last_week_bookings)

    # ============== REVENUE METRICS ==============
    # Calculate ACTUAL revenue for this week (based on stays happening this week, not bookings created)
    week_revenue = 0
    total_nights_this_week = 0

    # Get all bookings that have stays during this week
    active_this_week = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date <= today,
                Booking.departure_date >= week_start,
                Booking.status.in_(["checked_in", "checked_out"])
            )
        )
    )).all()

    for booking in active_this_week:
        if booking.total_price and booking.arrival_date and booking.departure_date:
            total_nights = (booking.departure_date - booking.arrival_date).days
            if total_nights > 0:
                daily_rate = booking.total_price / total_nights

                # Calculate how many nights of this booking fall within this week
                stay_start = max(booking.arrival_date, week_start)
                stay_end = min(booking.departure_date, today + timedelta(days=1))
                nights_this_week = (stay_end - stay_start).days

                week_revenue += daily_rate * nights_this_week
                total_nights_this_week += nights_this_week

    # Calculate last week's revenue the same way
    last_week_revenue = 0
    active_last_week = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date <= last_week_start + timedelta(days=6),
                Booking.departure_date >= last_week_start,
                Booking.status.in_(["checked_in", "checked_out"])
            )
        )
    )).all()

    for booking in active_last_week:
        if booking.total_price and booking.arrival_date and booking.departure_date:
            total_nights = (booking.departure_date - booking.arrival_date).days
            if total_nights > 0:
                daily_rate = booking.total_price / total_nights

                stay_start = max(booking.arrival_date, last_week_start)
                stay_end = min(booking.departure_date, last_week_start + timedelta(days=7))
                nights_last_week = (stay_end - stay_start).days

                last_week_revenue += daily_rate * nights_last_week

    # TODAY'S REVENUE (bookings active today)
    today_revenue = 0
    today_bookings = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date <= today,
                Booking.departure_date > today,
                Booking.status.in_(["checked_in", "checked_out"])
            )
        )
    )).all()

    for booking in today_bookings:
        if booking.total_price and booking.arrival_date and booking.departure_date:
            total_nights = (booking.departure_date - booking.arrival_date).days
            if total_nights > 0:
                today_revenue += booking.total_price / total_nights

    # Calculate ADR (Average Daily Rate) - revenue per night
    adr = (week_revenue / total_nights_this_week) if total_nights_this_week > 0 else 0

    # Calculate RevPAR (Revenue Per Available Room) - using actual occupancy
    revpar = adr * (occupancy_rate / 100) if occupancy_rate > 0 else 0

    # ============== MTD / YTD / 30-DAY METRICS (optimized: single query) ==============
    year_start = today.replace(month=1, day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    thirty_days_ago = today - timedelta(days=30)

    # Single query: all bookings active from year_start to today (covers MTD, YTD, last month, 30-day occ)
    all_period_bookings = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date <= today,
                Booking.departure_date >= last_month_start,
                Booking.status.in_(["checked_in", "checked_out"])
            )
        )
    )).all()

    # Also fetch YTD bookings that started before last_month_start
    ytd_extra = []
    if year_start < last_month_start:
        ytd_extra = (await session.exec(
            select(Booking).where(
                and_(
                    Booking.arrival_date <= today,
                    Booking.departure_date >= year_start,
                    Booking.departure_date < last_month_start,
                    Booking.status.in_(["checked_in", "checked_out"])
                )
            )
        )).all()

    def _calc_revenue(bookings, period_start, period_end):
        total = 0
        for b in bookings:
            if b.total_price and b.arrival_date and b.departure_date:
                nights = (b.departure_date - b.arrival_date).days
                if nights > 0:
                    rate = b.total_price / nights
                    s = max(b.arrival_date, period_start)
                    e = min(b.departure_date, period_end + timedelta(days=1))
                    total += rate * max(0, (e - s).days)
        return total

    revenue_mtd = _calc_revenue(all_period_bookings, month_start, today)
    revenue_ytd = _calc_revenue(all_period_bookings + ytd_extra, year_start, today)
    revenue_last_month = _calc_revenue(all_period_bookings, last_month_start, last_month_end)

    revenue_mtd_trend = 0
    if revenue_last_month > 0:
        revenue_mtd_trend = round(((revenue_mtd - revenue_last_month) / revenue_last_month) * 100, 1)

    # Average occupancy over last 30 days (single query + in-memory calculation)
    occ_bookings = [b for b in all_period_bookings if b.departure_date > thirty_days_ago]
    occ_sum = 0
    for i in range(30):
        d = today - timedelta(days=i)
        occ_sum += sum(1 for b in occ_bookings if b.arrival_date <= d and b.departure_date > d)
    avg_occupancy_30d = round((occ_sum / (30 * bookable_rooms)) * 100, 1) if bookable_rooms > 0 else 0

    # Total completed bookings
    total_completed_result = (await session.exec(
        select(func.count(Booking.id)).where(
            Booking.status.in_(["checked_out", "completed"])
        )
    )).one()
    total_completed_bookings = total_completed_result or 0

    # ============== GUESTS METRICS ==============
    all_guests = (await session.exec(select(Guest))).all()
    total_guests = len(all_guests)
    vip_guests = len([g for g in all_guests if g.vip_status])

    # ============== HOUSEKEEPING METRICS ==============
    # Today's housekeeping tasks
    hk_tasks = (await session.exec(select(HousekeepingTask))).all()
    pending_hk_tasks = len([t for t in hk_tasks if t.status == "pending"])
    in_progress_hk_tasks = len([t for t in hk_tasks if t.status == "in_progress"])

    # Completed today
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    completed_hk_today = len([t for t in hk_tasks if t.status == "completed" and t.completed_at and t.completed_at >= today_start])

    # Staff on shift (housekeeping)
    try:
        hk_staff = (await session.exec(
            select(Staff).where(
                and_(
                    Staff.department == "housekeeping",
                    Staff.status == "active"
                )
            )
        )).all()
        hk_staff_on_shift = len([s for s in hk_staff if getattr(s, 'clocked_in', False)])
    except:
        hk_staff_on_shift = 0

    # ============== MAINTENANCE METRICS ==============
    maintenance_requests = (await session.exec(select(MaintenanceRequest))).all()
    open_maintenance = len([m for m in maintenance_requests if m.status in ["open", "pending", "in_progress"]])
    high_priority_maintenance = len([m for m in maintenance_requests if m.status in ["open", "pending"] and m.priority in ["high", "urgent", "critical"]])

    # ============== STAFF METRICS ==============
    try:
        all_staff = (await session.exec(select(Staff).where(Staff.status == "active"))).all()
        active_staff = len(all_staff)
        staff_on_shift = len([s for s in all_staff if getattr(s, 'clocked_in', False)])
    except:
        active_staff = 0
        staff_on_shift = 0

    # ============== CALCULATE TRENDS (% change vs last week) ==============
    def calc_trend(current, previous):
        if previous == 0:
            return 0 if current == 0 else 0  # No change if both are zero
        return round(((current - previous) / previous) * 100, 1)

    # Calculate last week's occupancy for comparison
    last_week_occupied = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date <= last_week_start,
                Booking.departure_date > last_week_start,
                Booking.status == "checked_in"
            )
        )
    )).all()
    last_week_occupancy = (len(last_week_occupied) / bookable_rooms * 100) if bookable_rooms > 0 else 0

    occupancy_trend = calc_trend(occupancy_rate, last_week_occupancy)
    bookings_trend = calc_trend(bookings_this_week, last_week_bookings_count)
    revenue_trend = calc_trend(week_revenue, last_week_revenue)

    # ============== RECENT BOOKINGS (from today onwards) ==============
    recent_reservations = (await session.exec(
        select(Booking).where(
            Booking.arrival_date >= today
        ).order_by(Booking.arrival_date.asc()).limit(5)
    )).all()

    recent_bookings = []
    for res in recent_reservations:
        guest = await session.get(Guest, res.guest_id) if res.guest_id else None
        room = await session.get(Room, res.room_id) if res.room_id else None
        room_type = None
        room_type_name = "Standard Room"

        if res.room_type_id:
            room_type = await session.get(RoomType, res.room_type_id)
            if room_type:
                room_type_name = room_type.name
        elif room and room.room_type_id:
            room_type = await session.get(RoomType, room.room_type_id)
            if room_type:
                room_type_name = room_type.name

        guest_name = f"{guest.first_name} {guest.last_name}" if guest else "Unknown Guest"

        recent_bookings.append({
            "id": res.id,
            "guest": guest_name,
            "room": room.number if room else "TBD",
            "roomType": room_type_name,
            "checkIn": res.arrival_date.isoformat(),
            "checkOut": res.departure_date.isoformat(),
            "status": res.status,
            "source": res.booking_source or "Website",
            "totalAmount": res.total_price or 0,
            "paymentStatus": res.payment_status or "pending",
            "amountPaid": (res.total_price or 0) - (res.balance_due or 0),
        })

    # ============== UPCOMING ARRIVALS (from today onwards) ==============
    upcoming_arrivals = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date >= today,
                Booking.status.in_(["booked", "confirmed", "pending"])
            )
        ).order_by(Booking.arrival_date.asc()).limit(5)
    )).all()
    upcoming_arrivals_list = []
    for arrival in upcoming_arrivals:
        guest = await session.get(Guest, arrival.guest_id) if arrival.guest_id else None
        room = await session.get(Room, arrival.room_id) if arrival.room_id else None
        room_type = None
        room_type_name = "Standard Room"

        if arrival.room_type_id:
            room_type = await session.get(RoomType, arrival.room_type_id)
            if room_type:
                room_type_name = room_type.name
        elif room and room.room_type_id:
            room_type = await session.get(RoomType, room.room_type_id)
            if room_type:
                room_type_name = room_type.name

        guest_name = f"{guest.first_name} {guest.last_name}" if guest else "Unknown Guest"

        upcoming_arrivals_list.append({
            "id": arrival.id,
            "guest": guest_name,
            "room": room.number if room else "TBD",
            "roomType": room_type_name,
            "checkIn": arrival.arrival_date.isoformat(),
            "checkOut": arrival.departure_date.isoformat(),
            "status": arrival.status,
            "source": arrival.booking_source or "Website",
            "totalAmount": arrival.total_price or 0,
            "isVIP": guest.vip_status if guest else False,
            "specialRequests": arrival.special_requests or "",
            "expectedArrivalTime": arrival.expected_arrival_time or "",
        })

    # ============== CHANNEL DISTRIBUTION ==============
    # Calculate booking sources distribution
    channel_counts = {}
    for res in week_bookings:
        source = res.booking_source or "Direct"
        channel_counts[source] = channel_counts.get(source, 0) + 1

    total_week_bookings = len(week_bookings) if week_bookings else 1
    channel_distribution = [
        {"name": source, "value": round((count / total_week_bookings) * 100, 1)}
        for source, count in channel_counts.items()
    ]

    # ============== RECENT REVIEWS ==============
    from app.models.reviews import Review
    recent_reviews_query = (await session.exec(
        select(Review).order_by(Review.review_date.desc()).limit(5)
    )).all()

    recent_reviews_list = []
    for review in recent_reviews_query:
        guest = await session.get(Guest, review.guest_id) if review.guest_id else None
        guest_name = f"{guest.first_name} {guest.last_name}" if guest else "Anonymous"

        recent_reviews_list.append({
            "id": review.id,
            "guestName": guest_name,
            "rating": review.overall_rating,
            "sentiment": review.sentiment or "neutral",
            "reviewText": review.comment or "",
            "date": review.review_date.isoformat(),
            "platform": review.source.title(),
            "hasReply": bool(review.response),
        })

    # ============== REVENUE CHART DATA (optimized: reuse already-fetched bookings) ==============
    # Last 7 days DAILY revenue (not cumulative) - use week_bookings already in memory
    chart_start = today - timedelta(days=6)
    # Also include bookings from all_period_bookings that overlap the chart period
    chart_bookings = [
        b for b in (week_bookings + all_period_bookings)
        if b.arrival_date <= today and b.departure_date > chart_start
        and b.total_price and b.arrival_date and b.departure_date
    ]
    # Deduplicate by id
    seen_ids = set()
    unique_chart_bookings = []
    for b in chart_bookings:
        if b.id not in seen_ids:
            seen_ids.add(b.id)
            unique_chart_bookings.append(b)

    revenue_chart = []
    for i in range(6, -1, -1):
        day_date = today - timedelta(days=i)
        day_revenue = 0
        for b in unique_chart_bookings:
            if b.arrival_date <= day_date and b.departure_date > day_date:
                total_nights = (b.departure_date - b.arrival_date).days
                if total_nights > 0:
                    day_revenue += b.total_price / total_nights
                else:
                    day_revenue += b.total_price
        revenue_chart.append({
            "day": day_date.strftime("%a"),
            "revenue": max(0, round(day_revenue, 2)),
        })

    return {
        "kpis": {
            "occupancy_rate": round(occupancy_rate, 1),
            "avg_occupancy_30d": avg_occupancy_30d,
            "adr": round(adr, 2),
            "revpar": round(revpar, 2),
            "total_rooms": total_rooms,
            "occupied_rooms": occupied_rooms,
            "available_rooms": available_rooms,
            "dirty_rooms": dirty_rooms,
            "out_of_order": out_of_order,
            "checkins_today": checkins_today,
            "checkouts_today": checkouts_today,
            "bookings_this_week": bookings_this_week,
            "total_completed_bookings": total_completed_bookings,
            "revenue_week": round(week_revenue, 2),
            "revenue_today": round(today_revenue, 2),
            "revenue_mtd": round(revenue_mtd, 2),
            "revenue_ytd": round(revenue_ytd, 2),
            "revenue_last_month": round(revenue_last_month, 2),
            "total_guests": total_guests,
            "vip_guests": vip_guests,
        },
        "housekeeping": {
            "pending_tasks": pending_hk_tasks,
            "in_progress_tasks": in_progress_hk_tasks,
            "in_progress_rooms": in_progress_rooms,
            "completed_today": completed_hk_today,
            "dirty_rooms": dirty_rooms,
            "clean_rooms": room_status_counts.get("clean", 0) + room_status_counts.get("inspected", 0),
            "occupied_rooms": occupied_rooms,
            "out_of_order": out_of_order,
            "out_of_service": out_of_service,
            "maintenance": room_status_counts.get("maintenance", 0),
            "staff_on_shift": hk_staff_on_shift,
        },
        "maintenance": {
            "open_requests": open_maintenance,
            "high_priority": high_priority_maintenance,
        },
        "staff": {
            "active_count": active_staff,
            "on_shift": staff_on_shift,
        },
        "trends": {
            "occupancy": occupancy_trend,
            "adr": revenue_trend,
            "revpar": revenue_trend,
            "bookings": bookings_trend,
            "revenue_mtd": revenue_mtd_trend,
            "checkins": 0,
            "checkouts": 0,
            "available_rooms": 0,
        },
        "recent_bookings": recent_bookings,
        "upcoming_arrivals": upcoming_arrivals_list,
        "channel_distribution": channel_distribution,
        "recent_reviews": recent_reviews_list,
        "revenue_chart": revenue_chart,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/finance")
async def finance_dashboard(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Finance dashboard with revenue and payment metrics"""
    if current_user.role not in ["admin", "finance"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Finance access required")
    
    end = end_date or await get_business_date(session)
    start = start_date or (end - timedelta(days=30))
    
    # Revenue metrics
    folios = (await session.exec(
        select(Folio).join(Reservation).where(
            and_(
                Booking.arrival_date >= start,
                Booking.arrival_date <= end
            )
        )
    )).all()
    
    total_revenue = sum(f.total_payments for f in folios)
    total_charges = sum(f.total_charges for f in folios)
    outstanding = sum(f.balance for f in folios if f.balance > 0)
    
    # Payment methods breakdown
    payments = (await session.exec(
        select(Payment).join(Folio).join(Reservation).where(
            and_(
                Payment.status == "captured",
                Payment.processed_at >= datetime.combine(start, datetime.min.time()),
                Payment.processed_at <= datetime.combine(end, datetime.max.time())
            )
        )
    )).all()
    
    revenue_by_method = {}
    for p in payments:
        revenue_by_method[p.method] = revenue_by_method.get(p.method, 0) + p.amount
    
    return {
        "total_revenue": total_revenue,
        "outstanding_balance": outstanding,
        "payment_methods": revenue_by_method,
        "top_rate_plans": []  # TODO: Implement rate plan breakdown
    }


@router.get("/operations")
async def operations_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Operations dashboard with room and staff metrics"""
    if current_user.role not in ["admin", "operations"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Operations access required")
    
    # Room status breakdown
    rooms = (await session.exec(select(Room))).all()
    room_status = {}
    for room in rooms:
        room_status[room.status] = room_status.get(room.status, 0) + 1
    
    # Housekeeping tasks
    pending_tasks = len((await session.exec(
        select(HousekeepingTask).where(HousekeepingTask.status == "pending")
    )).all())
    
    in_progress_tasks = len((await session.exec(
        select(HousekeepingTask).where(HousekeepingTask.status == "in_progress")
    )).all())
    
    # Maintenance requests
    open_maintenance = len((await session.exec(
        select(MaintenanceRequest).where(MaintenanceRequest.status == "open")
    )).all())
    
    critical_maintenance = len((await session.exec(
        select(MaintenanceRequest).where(
            and_(
                MaintenanceRequest.status == "open",
                MaintenanceRequest.severity == "critical"
            )
        )
    )).all())
    
    return {
        "rooms": {
            "total": len(rooms),
            "status_breakdown": room_status
        },
        "room_status_summary": room_status,
        "housekeeping": {
            "pending_tasks": pending_tasks,
            "in_progress_tasks": in_progress_tasks
        },
        "housekeeping_tasks": {
            "pending": pending_tasks,
            "in_progress": in_progress_tasks,
            "completed": 0,
        },
        "maintenance": {
            "open_requests": open_maintenance,
            "critical_requests": critical_maintenance
        }
    }


@router.get("/frontdesk")
async def frontdesk_dashboard(
    target_date: Optional[date] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Front desk dashboard with arrivals, departures, and tasks"""
    if current_user.role not in ["admin", "front_desk", "receptionist", "reception"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Front desk access required")
    
    target = target_date or await get_business_date(session)
    
    # Arrivals
    arrivals_query = select(Booking).where(
        and_(
            Booking.arrival_date == target,
            Booking.status.in_(["booked", "checked_in"])
        )
    )
    arrivals = (await session.exec(arrivals_query)).all()
    
    # Get room numbers for arrivals
    arrival_list = []
    for res in arrivals:
        room = None
        if res.room_id:
            room = await session.get(Room, res.room_id)
        arrival_list.append({
            "id": res.id,
            "confirmation_code": res.confirmation_code,
            "room_number": room.number if room else None
        })
    
    # Departures
    departures_query = select(Booking).where(
        and_(
            Booking.departure_date == target,
            Booking.status == "checked_in"
        )
    )
    departures = (await session.exec(departures_query)).all()
    
    # Get room numbers for departures
    departure_list = []
    for res in departures:
        room = None
        if res.room_id:
            room = await session.get(Room, res.room_id)
        departure_list.append({
            "id": res.id,
            "confirmation_code": res.confirmation_code,
            "room_number": room.number if room else None
        })
    
    # In-house
    in_house = (await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date <= target,
                Booking.departure_date > target,
                Booking.status == "checked_in"
            )
        )
    )).all()
    
    return {
        "date": target,
        "arrivals_today": len(arrival_list),
        "departures_today": len(departure_list),
        "in_house": len(in_house),
        "available_rooms": len((await session.exec(select(Room).where(Room.status == "clean"))).all()),
        "arrivals": arrival_list,
        "departures": departure_list
    }


@router.get("/management")
async def management_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Management dashboard with KPIs and alerts"""
    if current_user.role not in ["admin", "management"] and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Management access required")
    
    # KPIs
    biz_date = await get_business_date(session)
    total_rooms = len((await session.exec(select(Room).where(Room.status != "out_of_order"))).all())
    occupied = len((await session.exec(
        select(Booking).where(
            and_(
                Booking.arrival_date <= biz_date,
                Booking.departure_date > biz_date,
                Booking.status == "checked_in"
            )
        )
    )).all())

    occupancy_rate = (occupied / total_rooms * 100) if total_rooms > 0 else 0

    # Revenue this month
    month_start = biz_date.replace(day=1)
    month_folios = (await session.exec(
        select(Folio).join(Reservation).where(
            Booking.arrival_date >= month_start
        )
    )).all()
    month_revenue = sum(f.total_payments for f in month_folios)
    
    # Alerts
    alerts = []
    if occupancy_rate > 90:
        alerts.append({"type": "warning", "message": "High occupancy rate"})
    
    critical_maintenance = len((await session.exec(
        select(MaintenanceRequest).where(
            and_(
                MaintenanceRequest.status == "open",
                MaintenanceRequest.severity == "critical"
            )
        )
    )).all())
    
    if critical_maintenance > 0:
        alerts.append({"type": "critical", "message": f"{critical_maintenance} critical maintenance requests"})
    
    return {
        "kpis": {
            "occupancy_rate": round(occupancy_rate, 2),
            "month_revenue": month_revenue,
            "total_rooms": total_rooms,
            "occupied_rooms": occupied
        },
        "alerts": alerts
    }


@router.get("/guest")
async def guest_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Guest dashboard with personal booking statistics"""
    from app.models.reservations import Guest

    # Find guest by user email (case-insensitive)
    from sqlalchemy import func
    guest = (await session.exec(
        select(Guest).where(func.lower(Guest.email) == current_user.email.lower())
    )).first()

    # Also try to find by user_id if no guest found by email
    if not guest and hasattr(current_user, 'id'):
        # Check if there's a guest linked to reservations made by this user
        user_reservations = (await session.exec(
            select(Booking).where(Booking.created_by == current_user.id)
        )).all()
        if user_reservations:
            guest = await session.get(Guest, user_reservations[0].guest_id)

    if not guest:
        # Return empty stats if no guest record found
        return {
            "total_bookings": 0,
            "nights_stayed": 0,
            "loyalty_points": 0,
            "member_since": current_user.created_at.date().isoformat() if current_user.created_at else None,
            "upcoming_booking": None,
            "recent_activity": []
        }

    # Get all reservations for this guest (excluding cancelled)
    reservations = (await session.exec(
        select(Booking).where(Booking.guest_id == guest.id)
    )).all()

    # Calculate stats - count active bookings (not cancelled)
    active_reservations = [r for r in reservations if r.status != "cancelled"]
    total_bookings = len(active_reservations)

    # Calculate total nights (completed stays + upcoming stays)
    nights_stayed = sum(
        (r.departure_date - r.arrival_date).days
        for r in active_reservations
    )

    # Calculate loyalty points (10% of total spending for non-cancelled bookings)
    total_spent = sum(r.total_price or 0 for r in active_reservations)
    loyalty_points = int(total_spent * 0.1)
    
    # Get upcoming booking (first confirmed/booked reservation with future or today's check-in)
    today = await get_business_date(session)
    upcoming = None
    for res in sorted(active_reservations, key=lambda r: r.arrival_date):
        if res.status in ["booked", "confirmed", "checked_in"] and res.arrival_date >= today:
            room_type_name = "Room"
            # First try to get from room_type_id directly
            if res.room_type_id:
                rt = await session.get(RoomType, res.room_type_id)
                if rt:
                    room_type_name = rt.name
            # Fallback to room's room_type
            elif res.room_id:
                room = await session.get(Room, res.room_id)
                if room and room.room_type_id:
                    rt = await session.get(RoomType, room.room_type_id)
                    if rt:
                        room_type_name = rt.name
            upcoming = {
                "id": str(res.id),
                "bookingNumber": res.confirmation_code,
                "roomType": room_type_name,
                "checkIn": res.arrival_date.isoformat(),
                "checkOut": res.departure_date.isoformat(),
                "guests": res.adults + res.children,
                "nights": (res.departure_date - res.arrival_date).days,
                "status": res.status
            }
            break

    # Get recent activity (last 5 reservations)
    recent_activity = []
    for res in sorted(reservations, key=lambda r: r.created_at or r.arrival_date, reverse=True)[:5]:
        room_type_name = "Room"
        # First try to get from room_type_id directly
        if res.room_type_id:
            rt = await session.get(RoomType, res.room_type_id)
            if rt:
                room_type_name = rt.name
        # Fallback to room's room_type
        elif res.room_id:
            room = await session.get(Room, res.room_id)
            if room and room.room_type_id:
                rt = await session.get(RoomType, room.room_type_id)
                if rt:
                    room_type_name = rt.name

        activity_type = "Booking confirmed" if res.status in ["booked", "confirmed"] else \
                       "Checked in" if res.status == "checked_in" else \
                       "Booking completed" if res.status in ["checked_out", "completed"] else \
                       "Booking cancelled" if res.status == "cancelled" else "Booking updated"

        recent_activity.append({
            "date": (res.created_at or res.arrival_date).isoformat() if res.created_at else res.arrival_date.isoformat(),
            "action": activity_type,
            "details": f"{room_type_name} · {res.arrival_date.strftime('%b %d')}-{res.departure_date.strftime('%b %d')}"
        })
    
    return {
        "total_bookings": total_bookings,
        "nights_stayed": nights_stayed,
        "loyalty_points": loyalty_points,
        "member_since": guest.created_at.date().isoformat() if guest.created_at else current_user.created_at.date().isoformat() if current_user.created_at else None,
        "upcoming_booking": upcoming,
        "recent_activity": recent_activity
    }


@router.get("/guest/billing")
async def guest_billing_history(
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get billing history for current guest"""

    # Find guest by user email
    guest = (await session.exec(
        select(Guest).where(Guest.email == current_user.email)
    )).first()

    if not guest:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "pageSize": pageSize,
            "totalPages": 0
        }

    # Get all reservations for this guest
    reservations = (await session.exec(
        select(Booking)
        .where(Booking.guest_id == guest.id)
        .order_by(Booking.created_at.desc())
    )).all()

    # Build billing history from reservations
    billing_items = []
    for res in reservations:
        # Get room type info
        room = await session.get(Room, res.room_id) if res.room_id else None
        room_type_name = "Room"

        if res.room_type_id:
            rt = await session.get(RoomType, res.room_type_id)
            if rt:
                room_type_name = rt.name
        elif room and room.room_type_id:
            rt = await session.get(RoomType, room.room_type_id)
            if rt:
                room_type_name = rt.name

        from app.core.tax import get_room_tax_rate
        nights = (res.departure_date - res.arrival_date).days

        # Calculate breakdown using GST slab-based rate
        per_night_rate = rt.base_price if rt else 0
        tax_rate = get_room_tax_rate(per_night_rate) if per_night_rate > 0 else 0.12
        total_markup = tax_rate  # No service fee
        base_price = (res.total_price or 0) / (1 + total_markup)
        taxes = base_price * tax_rate
        service_fee = 0.0  # Service fee removed

        # Determine payment status
        payment_status = "paid" if res.status in ["checked_out", "completed"] else \
                        "refunded" if res.status == "cancelled" else "pending"

        # Get payment method (from folio if available)
        payment_method = "Card ending ****4242"  # Default

        try:
            folio = (await session.exec(
                select(Folio).where(Folio.reservation_id == res.id)
            )).first()

            if folio:
                payments = (await session.exec(
                    select(Payment).where(Payment.folio_id == folio.id)
                )).all()
                if payments:
                    last_payment = payments[-1]
                    payment_method = f"Card ending ****{last_payment.last4}" if hasattr(last_payment, 'last4') and last_payment.last4 else "Card"
        except:
            pass

        billing_items.append({
            "id": res.id,
            "booking_number": res.confirmation_code,
            "date": res.created_at.isoformat() if res.created_at else res.arrival_date.isoformat(),
            "description": f"{room_type_name} - {nights} night{'s' if nights > 1 else ''} ({res.arrival_date.strftime('%b %d')} - {res.departure_date.strftime('%b %d, %Y')})",
            "room_type": room_type_name,
            "check_in": res.arrival_date.isoformat(),
            "check_out": res.departure_date.isoformat(),
            "nights": nights,
            "base_price": round(base_price, 2),
            "taxes": round(taxes, 2),
            "service_fee": round(service_fee, 2),
            "amount": round(res.total_price or 0, 2),
            "status": payment_status,
            "payment_method": payment_method,
            "booking_status": res.status,
        })

    # Paginate
    total = len(billing_items)
    offset = (page - 1) * pageSize
    paginated = billing_items[offset:offset + pageSize]
    total_pages = (total + pageSize - 1) // pageSize if pageSize > 0 else 0

    return {
        "items": paginated,
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "totalPages": total_pages,
        "summary": {
            "total_spent": sum(item["amount"] for item in billing_items if item["status"] != "refunded"),
            "total_bookings": len(billing_items),
            "pending_amount": sum(item["amount"] for item in billing_items if item["status"] == "pending"),
        }
    }
