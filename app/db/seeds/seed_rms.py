"""
Revenue Management System (RMS) Seed Data Script
Seeds sample data for PricingRule, Competitor, CompetitorRate, DemandForecast,
MarketEvent, PickupPace, and SegmentPerformance models.
"""
import asyncio
import random
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.rms import (
    PricingRule,
    Competitor,
    CompetitorRate,
    DemandForecast,
    MarketEvent,
    PickupPace,
    SegmentPerformance,
)


# ============================================================================
# PRICING RULES DATA
# ============================================================================

PRICING_RULES_DATA = [
    {
        "rule_name": "High Occupancy Premium",
        "description": "Increase rates when occupancy exceeds 85%",
        "priority": 1,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "occupancy_above", "operator": "gt", "value": 85}
        ],
        "actions": [
            {"type": "increase_percent", "value": 15},
            {"type": "set_min_rate", "value": 16500}
        ],
        "times_triggered": 156,
    },
    {
        "rule_name": "Compression Day Maximizer",
        "description": "Maximum rates during compression with min stay",
        "priority": 1,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "occupancy_above", "operator": "gt", "value": 92},
            {"type": "demand_level", "operator": "eq", "value": "compression"}
        ],
        "actions": [
            {"type": "increase_percent", "value": 25},
            {"type": "apply_min_stay", "value": 2},
            {"type": "apply_cta", "value": False}
        ],
        "times_triggered": 42,
    },
    {
        "rule_name": "Competitor Rate Match",
        "description": "Adjust when significantly below competitor average",
        "priority": 2,
        "is_active": True,
        "room_types": ["STD", "DLX"],
        "conditions": [
            {"type": "competitor_higher", "operator": "gt", "value": 15},
            {"type": "pickup_above", "operator": "gt", "value": 90}
        ],
        "actions": [
            {"type": "increase_percent", "value": 12}
        ],
        "times_triggered": 89,
    },
    {
        "rule_name": "Last Minute Discount",
        "description": "Reduce rates for unsold inventory within 3 days",
        "priority": 3,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "days_to_arrival", "operator": "between", "value": {"min": 0, "max": 3}},
            {"type": "occupancy_below", "operator": "lt", "value": 70}
        ],
        "actions": [
            {"type": "decrease_percent", "value": 15}
        ],
        "times_triggered": 234,
    },
    {
        "rule_name": "Weekend Premium",
        "description": "Apply premium pricing on weekends",
        "priority": 2,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "day_of_week", "operator": "in", "value": [4, 5]}  # Friday, Saturday
        ],
        "actions": [
            {"type": "increase_percent", "value": 18},
            {"type": "set_min_rate", "value": 18000}
        ],
        "times_triggered": 412,
    },
    {
        "rule_name": "Event Surge Pricing",
        "description": "Maximize rates during local events",
        "priority": 1,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "event_active", "operator": "eq", "value": True}
        ],
        "actions": [
            {"type": "increase_percent", "value": 20},
            {"type": "apply_min_stay", "value": 2}
        ],
        "times_triggered": 28,
    },
    {
        "rule_name": "Slow Pickup Stimulation",
        "description": "Reduce rates when booking pace is slow",
        "priority": 3,
        "is_active": True,
        "room_types": ["STD", "DLX"],
        "conditions": [
            {"type": "pickup_below", "operator": "lt", "value": 75},
            {"type": "days_to_arrival", "operator": "between", "value": {"min": 7, "max": 21}}
        ],
        "actions": [
            {"type": "decrease_percent", "value": 10}
        ],
        "times_triggered": 167,
    },
    {
        "rule_name": "Corporate Rate Protection",
        "description": "Ensure corporate rates stay below BAR",
        "priority": 4,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "segment", "operator": "eq", "value": "corporate"}
        ],
        "actions": [
            {"type": "set_max_rate", "value": 20500}
        ],
        "times_triggered": 892,
    },
    {
        "rule_name": "Suite Upsell Opportunity",
        "description": "Narrow gap between rooms when suites undersold",
        "priority": 3,
        "is_active": True,
        "room_types": ["SUP", "EXE"],
        "conditions": [
            {"type": "occupancy_below", "operator": "lt", "value": 50},
            {"type": "days_to_arrival", "operator": "between", "value": {"min": 0, "max": 14}}
        ],
        "actions": [
            {"type": "decrease_percent", "value": 12}
        ],
        "times_triggered": 78,
    },
    {
        "rule_name": "Low Demand Floor Protection",
        "description": "Prevent rates from dropping too low",
        "priority": 5,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "demand_level", "operator": "eq", "value": "very_low"}
        ],
        "actions": [
            {"type": "set_min_rate", "value": 12500}
        ],
        "times_triggered": 45,
    },
    {
        "rule_name": "Peak Season Surge",
        "description": "Increase rates during high-demand summer months",
        "priority": 2,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "month", "operator": "in", "value": [6, 7, 8]},
            {"type": "occupancy_above", "operator": "gt", "value": 75}
        ],
        "actions": [
            {"type": "increase_percent", "value": 22}
        ],
        "times_triggered": 124,
    },
    {
        "rule_name": "Holiday Premium Pricing",
        "description": "Apply premium rates during major holidays",
        "priority": 1,
        "is_active": True,
        "room_types": ["ALL"],
        "conditions": [
            {"type": "event_type", "operator": "eq", "value": "holiday"}
        ],
        "actions": [
            {"type": "increase_percent", "value": 30},
            {"type": "apply_min_stay", "value": 3},
            {"type": "set_min_rate", "value": 24000}
        ],
        "times_triggered": 35,
    },
]


# ============================================================================
# COMPETITORS DATA
# ============================================================================

COMPETITORS_DATA = [
    {
        "name": "Grand Luxe Resort",
        "address": "1500 Ocean Boulevard, Santa Monica, CA 90401",
        "star_rating": 5.0,
        "room_count": 250,
        "distance_km": 0.8,
        "booking_com_id": "grand-luxe-resort-santa-monica",
        "tripadvisor_id": "g60713-d123456",
        "is_active": True,
        "notes": "Primary luxury competitor - premium positioning"
    },
    {
        "name": "Seaside Boutique Hotel",
        "address": "789 Pacific Way, Santa Monica, CA 90402",
        "star_rating": 4.0,
        "room_count": 85,
        "distance_km": 1.2,
        "booking_com_id": "seaside-boutique-hotel",
        "tripadvisor_id": "g60713-d234567",
        "is_active": True,
        "notes": "Value-oriented boutique competitor"
    },
    {
        "name": "Metropolitan Suites",
        "address": "200 Main Street, Santa Monica, CA 90401",
        "star_rating": 4.0,
        "room_count": 120,
        "distance_km": 0.5,
        "booking_com_id": "metropolitan-suites-sm",
        "tripadvisor_id": "g60713-d345678",
        "is_active": True,
        "notes": "Direct competitor - similar positioning"
    },
    {
        "name": "Harbor View Inn",
        "address": "450 Harbor Drive, Marina del Rey, CA 90292",
        "star_rating": 3.0,
        "room_count": 60,
        "distance_km": 2.0,
        "booking_com_id": "harbor-view-inn-marina",
        "tripadvisor_id": "g60713-d456789",
        "is_active": True,
        "notes": "Budget option - lower tier competitor"
    },
    {
        "name": "The Ritz Downtown",
        "address": "100 Luxury Lane, Santa Monica, CA 90403",
        "star_rating": 5.0,
        "room_count": 180,
        "distance_km": 1.5,
        "booking_com_id": "ritz-downtown-santa-monica",
        "tripadvisor_id": "g60713-d567890",
        "is_active": True,
        "notes": "Ultra-luxury competitor - highest rates in market"
    },
    {
        "name": "Hilton Garden Inn",
        "address": "888 Business Center Drive, Santa Monica, CA 90401",
        "star_rating": 4.0,
        "room_count": 150,
        "distance_km": 1.8,
        "booking_com_id": "hilton-garden-inn-sm",
        "tripadvisor_id": "g60713-d678901",
        "is_active": True,
        "notes": "Corporate travel focused competitor"
    },
    {
        "name": "Hyatt Regency Beach",
        "address": "2200 Ocean Front Walk, Santa Monica, CA 90405",
        "star_rating": 4.5,
        "room_count": 200,
        "distance_km": 2.4,
        "booking_com_id": "hyatt-regency-beach-sm",
        "tripadvisor_id": "g60713-d789012",
        "is_active": True,
        "notes": "Major chain competitor with strong loyalty program"
    },
]


# ============================================================================
# MARKET EVENTS DATA
# ============================================================================

def generate_market_events(property_id: int, start_date: date) -> List[Dict]:
    """Generate market events for the next 90 days"""
    events = [
        # Holidays
        {
            "event_name": "New Year's Day",
            "event_type": "holiday",
            "start_date": date(start_date.year + 1, 1, 1) if start_date.month == 12 else date(start_date.year, 1, 1),
            "end_date": date(start_date.year + 1, 1, 2) if start_date.month == 12 else date(start_date.year, 1, 2),
            "impact_multiplier": 1.45,
            "is_recurring": True,
            "recurrence_rule": "RRULE:FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1",
            "notes": "Major holiday - high demand expected"
        },
        {
            "event_name": "MLK Weekend",
            "event_type": "holiday",
            "start_date": date(2026, 1, 17),
            "end_date": date(2026, 1, 19),
            "impact_multiplier": 1.20,
            "is_recurring": True,
            "recurrence_rule": "RRULE:FREQ=YEARLY;BYMONTH=1;BYDAY=3MO",
            "notes": "Long weekend - moderate demand increase"
        },
        {
            "event_name": "Valentine's Weekend",
            "event_type": "special",
            "start_date": date(2026, 2, 13),
            "end_date": date(2026, 2, 15),
            "impact_multiplier": 1.25,
            "is_recurring": True,
            "recurrence_rule": "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=14",
            "notes": "Romantic getaway weekend - suites in high demand"
        },
        {
            "event_name": "Presidents Day Weekend",
            "event_type": "holiday",
            "start_date": date(2026, 2, 14),
            "end_date": date(2026, 2, 16),
            "impact_multiplier": 1.18,
            "is_recurring": True,
            "recurrence_rule": "RRULE:FREQ=YEARLY;BYMONTH=2;BYDAY=3MO",
            "notes": "Long weekend - family travel spike"
        },
        # Conferences
        {
            "event_name": "TechCrunch Disrupt LA",
            "event_type": "conference",
            "start_date": start_date + timedelta(days=20),
            "end_date": start_date + timedelta(days=22),
            "impact_multiplier": 1.35,
            "is_recurring": False,
            "notes": "Major tech conference - high corporate demand"
        },
        {
            "event_name": "Medical Association Annual Meeting",
            "event_type": "conference",
            "start_date": start_date + timedelta(days=45),
            "end_date": start_date + timedelta(days=48),
            "impact_multiplier": 1.40,
            "is_recurring": True,
            "recurrence_rule": "RRULE:FREQ=YEARLY",
            "notes": "Large medical conference - 500+ attendees expected"
        },
        # Sports Events
        {
            "event_name": "LA Marathon",
            "event_type": "sports",
            "start_date": start_date + timedelta(days=60),
            "end_date": start_date + timedelta(days=61),
            "impact_multiplier": 1.30,
            "is_recurring": True,
            "recurrence_rule": "RRULE:FREQ=YEARLY",
            "notes": "Major sports event - expect early check-ins"
        },
        {
            "event_name": "Lakers Home Game Weekend",
            "event_type": "sports",
            "start_date": start_date + timedelta(days=14),
            "end_date": start_date + timedelta(days=15),
            "impact_multiplier": 1.15,
            "is_recurring": False,
            "notes": "NBA playoffs - increased weekend demand"
        },
        # Concerts & Entertainment
        {
            "event_name": "Summer Concert Series - Hollywood Bowl",
            "event_type": "concert",
            "start_date": start_date + timedelta(days=30),
            "end_date": start_date + timedelta(days=31),
            "impact_multiplier": 1.22,
            "is_recurring": False,
            "notes": "Major concert venue event - late check-ins expected"
        },
        {
            "event_name": "Film Festival Premiere Week",
            "event_type": "local",
            "start_date": start_date + timedelta(days=75),
            "end_date": start_date + timedelta(days=82),
            "impact_multiplier": 1.50,
            "is_recurring": True,
            "recurrence_rule": "RRULE:FREQ=YEARLY",
            "notes": "Major entertainment industry event - premium rates"
        },
        # Local Events
        {
            "event_name": "Santa Monica Arts Festival",
            "event_type": "local",
            "start_date": start_date + timedelta(days=10),
            "end_date": start_date + timedelta(days=12),
            "impact_multiplier": 1.18,
            "is_recurring": True,
            "recurrence_rule": "RRULE:FREQ=YEARLY",
            "notes": "Local cultural event - moderate demand increase"
        },
        {
            "event_name": "Beach Volleyball Tournament",
            "event_type": "sports",
            "start_date": start_date + timedelta(days=55),
            "end_date": start_date + timedelta(days=57),
            "impact_multiplier": 1.12,
            "is_recurring": False,
            "notes": "Sports tourism event"
        },
    ]

    # Add property_id to all events
    for event in events:
        event["property_id"] = property_id

    return events


# ============================================================================
# SEGMENT PERFORMANCE DATA
# ============================================================================

SEGMENTS_DATA = [
    {
        "segment_name": "Corporate",
        "base_revenue": 10375000,
        "base_room_nights": 480,
        "base_bookings": 320,
        "base_adr": 21500,
        "cancel_rate": 0.08,
        "avg_lead_time_days": 8,
        "avg_los": 1.8,
    },
    {
        "segment_name": "OTA",
        "base_revenue": 15350000,
        "base_room_nights": 820,
        "base_bookings": 650,
        "base_adr": 18750,
        "cancel_rate": 0.18,
        "avg_lead_time_days": 12,
        "avg_los": 2.2,
    },
    {
        "segment_name": "Direct",
        "base_revenue": 12000000,
        "base_room_nights": 520,
        "base_bookings": 380,
        "base_adr": 23000,
        "cancel_rate": 0.10,
        "avg_lead_time_days": 21,
        "avg_los": 2.5,
    },
    {
        "segment_name": "Travel Agent",
        "base_revenue": 7900000,
        "base_room_nights": 380,
        "base_bookings": 220,
        "base_adr": 20750,
        "cancel_rate": 0.06,
        "avg_lead_time_days": 35,
        "avg_los": 3.2,
    },
    {
        "segment_name": "VIP",
        "base_revenue": 6475000,
        "base_room_nights": 195,
        "base_bookings": 85,
        "base_adr": 33000,
        "cancel_rate": 0.04,
        "avg_lead_time_days": 18,
        "avg_los": 2.8,
    },
    {
        "segment_name": "Walk-in",
        "base_revenue": 3735000,
        "base_room_nights": 180,
        "base_bookings": 150,
        "base_adr": 15500,
        "cancel_rate": 0.02,
        "avg_lead_time_days": 0,
        "avg_los": 1.4,
    },
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_demand_level(demand_index: float) -> str:
    """Convert demand index to demand level category"""
    if demand_index >= 1.30:
        return "compression"
    elif demand_index >= 1.15:
        return "high"
    elif demand_index >= 0.95:
        return "normal"
    elif demand_index >= 0.75:
        return "low"
    else:
        return "very_low"


def get_pace_status(pace_ratio: float) -> str:
    """Convert pace ratio to status category"""
    if pace_ratio >= 1.15:
        return "strong"
    elif pace_ratio >= 0.95:
        return "on-pace"
    elif pace_ratio >= 0.80:
        return "slow"
    else:
        return "critical"


def generate_price_recommendation(demand_level: str, days_out: int) -> dict:
    """Generate pricing recommendation based on demand and timing"""
    recommendations = {
        "compression": {
            "action": "maximize",
            "adjustment_pct": 25,
            "message": "Compression day - maximize rates, apply min stay restrictions"
        },
        "high": {
            "action": "increase",
            "adjustment_pct": 15,
            "message": "High demand expected - increase rates gradually"
        },
        "normal": {
            "action": "maintain",
            "adjustment_pct": 0,
            "message": "Standard demand - maintain current pricing strategy"
        },
        "low": {
            "action": "stimulate",
            "adjustment_pct": -8,
            "message": "Soft demand - consider promotions or OTA boost"
        },
        "very_low": {
            "action": "aggressive_discount",
            "adjustment_pct": -15,
            "message": "Very low demand - activate discounts, remove restrictions"
        }
    }

    rec = recommendations.get(demand_level, recommendations["normal"])

    # Adjust for timing
    if days_out <= 3 and demand_level in ["low", "very_low"]:
        rec["adjustment_pct"] -= 5
        rec["message"] += " - Last minute pricing needed"

    return rec


def generate_pickup_alerts(days_out: int, pace_status: str, current: int, expected: int) -> list:
    """Generate pickup pace alerts"""
    alerts = []

    if pace_status == "strong" and days_out <= 14:
        adjustment = "10-15%" if days_out <= 7 else "5-10%"
        alerts.append({
            "type": "opportunity",
            "severity": "high",
            "message": f"Strong pickup - consider raising rates {adjustment}"
        })

    if pace_status == "critical" and days_out <= 21:
        alerts.append({
            "type": "warning",
            "severity": "high",
            "message": "Critical pace - activate promotions or lower rates immediately"
        })

    if pace_status == "slow" and days_out <= 14:
        alerts.append({
            "type": "warning",
            "severity": "medium",
            "message": "Below pace - consider OTA boost or flash sale"
        })

    if expected > 0 and current / expected < 0.5 and days_out <= 7:
        alerts.append({
            "type": "urgent",
            "severity": "critical",
            "message": "Occupancy gap within 7 days - last-minute pricing needed"
        })

    if expected > 0 and current / expected > 0.90 and days_out > 7:
        alerts.append({
            "type": "success",
            "severity": "info",
            "message": "Nearly sold out with time remaining - maximize rates"
        })

    return alerts


def generate_segment_optimizations(
    segment_name: str,
    cancel_rate: float,
    booking_pace: float,
    revenue_contribution: float,
    yoy_variance: float
) -> list:
    """Generate optimization suggestions for a segment"""
    optimizations = []

    if cancel_rate > 0.15:
        optimizations.append({
            "type": "reduce_cancellations",
            "priority": "high",
            "message": "High cancellation rate - consider stricter policies or deposits",
            "action": "Implement 48hr cancellation policy or require deposit"
        })

    if booking_pace < 0.85:
        optimizations.append({
            "type": "boost_pace",
            "priority": "medium",
            "message": "Booking pace below target - activate promotions",
            "action": "Launch targeted campaign or adjust rate positioning"
        })

    if revenue_contribution < 10 and segment_name not in ["Groups", "VIP"]:
        optimizations.append({
            "type": "grow_segment",
            "priority": "low",
            "message": "Low revenue contribution - opportunity for growth",
            "action": "Review rate competitiveness and marketing spend"
        })

    if yoy_variance < 0:
        optimizations.append({
            "type": "reverse_decline",
            "priority": "high",
            "message": f"Segment declining {abs(yoy_variance):.1f}% YoY",
            "action": "Analyze competitor activity and adjust strategy"
        })

    if segment_name == "OTA" and revenue_contribution > 30:
        optimizations.append({
            "type": "reduce_ota_dependency",
            "priority": "medium",
            "message": "High OTA dependency - commission costs impacting margin",
            "action": "Invest in direct booking incentives and website optimization"
        })

    if segment_name == "Direct" and revenue_contribution < 25:
        optimizations.append({
            "type": "grow_direct",
            "priority": "high",
            "message": "Direct channel underperforming - improve conversion",
            "action": "Enhance booking engine, add best rate guarantee"
        })

    return optimizations


# ============================================================================
# MAIN SEEDING FUNCTION
# ============================================================================

async def seed_rms_data(session: AsyncSession, property_id: int = 1) -> dict:
    """
    Seed Revenue Management System data for the specified property.

    This function is idempotent - it checks for existing data before inserting.

    Args:
        session: AsyncSession for database operations
        property_id: The property ID to associate with the data (default: 1)

    Returns:
        dict: Summary of created records
    """
    today = date.today()
    now = datetime.utcnow()

    summary = {
        "pricing_rules": 0,
        "competitors": 0,
        "competitor_rates": 0,
        "demand_forecasts": 0,
        "market_events": 0,
        "pickup_pace": 0,
        "segment_performance": 0,
    }

    print("=" * 60)
    print("Starting RMS data seeding...")
    print(f"Property ID: {property_id}")
    print(f"Date: {today}")
    print("=" * 60)

    # ========================================================================
    # 1. PRICING RULES
    # ========================================================================
    print("\n[1/7] Creating pricing rules...")

    for rule_data in PRICING_RULES_DATA:
        # Check if rule already exists
        existing = (await session.exec(
            select(PricingRule).where(
                PricingRule.property_id == property_id,
                PricingRule.rule_name == rule_data["rule_name"]
            )
        )).first()

        if not existing:
            rule = PricingRule(
                property_id=property_id,
                rule_name=rule_data["rule_name"],
                description=rule_data["description"],
                priority=rule_data["priority"],
                is_active=rule_data["is_active"],
                room_types=rule_data["room_types"],
                conditions=rule_data["conditions"],
                actions=rule_data["actions"],
                times_triggered=rule_data["times_triggered"],
                last_triggered_at=now - timedelta(days=random.randint(1, 30)) if rule_data["times_triggered"] > 0 else None,
                created_at=now - timedelta(days=random.randint(60, 365)),
            )
            session.add(rule)
            summary["pricing_rules"] += 1
            print(f"  + Created rule: {rule_data['rule_name']}")
        else:
            print(f"  - Rule exists: {rule_data['rule_name']}")

    await session.commit()

    # ========================================================================
    # 2. COMPETITORS
    # ========================================================================
    print("\n[2/7] Creating competitors...")

    competitor_ids = {}  # Map name to ID for rate generation

    for comp_data in COMPETITORS_DATA:
        existing = (await session.exec(
            select(Competitor).where(
                Competitor.property_id == property_id,
                Competitor.name == comp_data["name"]
            )
        )).first()

        if not existing:
            competitor = Competitor(
                property_id=property_id,
                name=comp_data["name"],
                address=comp_data["address"],
                star_rating=comp_data["star_rating"],
                room_count=comp_data["room_count"],
                distance_km=comp_data["distance_km"],
                booking_com_id=comp_data.get("booking_com_id"),
                tripadvisor_id=comp_data.get("tripadvisor_id"),
                is_active=comp_data["is_active"],
                notes=comp_data.get("notes"),
                created_at=now - timedelta(days=random.randint(90, 365)),
                updated_at=now,
            )
            session.add(competitor)
            await session.flush()
            competitor_ids[comp_data["name"]] = competitor.id
            summary["competitors"] += 1
            print(f"  + Created competitor: {comp_data['name']}")
        else:
            competitor_ids[comp_data["name"]] = existing.id
            print(f"  - Competitor exists: {comp_data['name']}")

    await session.commit()

    # ========================================================================
    # 3. COMPETITOR RATES (Last 30 days)
    # ========================================================================
    print("\n[3/7] Creating competitor rate snapshots (last 30 days)...")

    rate_sources = ["booking_com", "expedia", "tripadvisor", "direct"]
    room_types = ["Standard", "Deluxe", "Suite"]

    # Rate index multipliers for each competitor
    rate_indices = {
        "Grand Luxe Resort": 1.15,
        "Seaside Boutique Hotel": 0.95,
        "Metropolitan Suites": 1.05,
        "Harbor View Inn": 0.75,
        "The Ritz Downtown": 1.35,
        "Hilton Garden Inn": 1.00,
        "Hyatt Regency Beach": 1.10,
    }

    base_rate = 18000  # Our base rate (INR)

    for comp_name, comp_id in competitor_ids.items():
        rate_index = rate_indices.get(comp_name, 1.0)

        for days_ago in range(30):
            rate_date = today - timedelta(days=days_ago)

            for room_type in room_types:
                # Check if rate already exists
                existing = (await session.exec(
                    select(CompetitorRate).where(
                        CompetitorRate.competitor_id == comp_id,
                        CompetitorRate.rate_date == rate_date,
                        CompetitorRate.room_type == room_type
                    )
                )).first()

                if not existing:
                    # Calculate rate with variance
                    type_multiplier = 1.0 if room_type == "Standard" else (1.4 if room_type == "Deluxe" else 1.8)
                    variance = 0.92 + random.random() * 0.16
                    rate_amount = round(base_rate * rate_index * type_multiplier * variance, 2)

                    rate = CompetitorRate(
                        property_id=property_id,
                        competitor_id=comp_id,
                        rate_date=rate_date,
                        room_type=room_type,
                        rate_amount=rate_amount,
                        rate_source=random.choice(rate_sources),
                        currency="INR",
                        captured_at=datetime.combine(rate_date, datetime.min.time().replace(hour=random.randint(8, 18))),
                    )
                    session.add(rate)
                    summary["competitor_rates"] += 1

    await session.commit()
    print(f"  + Created {summary['competitor_rates']} competitor rate snapshots")

    # ========================================================================
    # 4. DEMAND FORECASTS (Next 30 days)
    # ========================================================================
    print("\n[4/7] Creating demand forecasts (next 30 days)...")

    # Historical demand patterns
    dow_patterns = {
        0: 0.65,  # Monday
        1: 0.70,  # Tuesday
        2: 0.80,  # Wednesday
        3: 0.90,  # Thursday
        4: 1.15,  # Friday
        5: 1.20,  # Saturday
        6: 0.75,  # Sunday
    }

    month_patterns = {
        1: 0.75, 2: 0.80, 3: 0.90, 4: 0.95,
        5: 1.05, 6: 1.20, 7: 1.30, 8: 1.25,
        9: 1.00, 10: 0.90, 11: 0.85, 12: 1.35
    }

    total_rooms = 70

    for days_out in range(30):
        forecast_date = today + timedelta(days=days_out)

        # Check if forecast exists
        existing = (await session.exec(
            select(DemandForecast).where(
                DemandForecast.property_id == property_id,
                DemandForecast.forecast_date == forecast_date
            )
        )).first()

        if not existing:
            dow = forecast_date.weekday()
            month = forecast_date.month

            # Calculate demand index
            dow_factor = dow_patterns.get(dow, 1.0)
            month_factor = month_patterns.get(month, 1.0)
            random_factor = 0.90 + random.random() * 0.20
            demand_index = (dow_factor + month_factor) / 2 * random_factor

            demand_level = get_demand_level(demand_index)

            # Calculate forecasted metrics
            typical_occ = 65 + (dow_factor * 15) + (month_factor * 10)
            forecasted_occupancy = min(98, round(typical_occ * demand_index))

            base_adr = 20500
            forecasted_adr = round(base_adr * demand_index)
            forecasted_revpar = round(forecasted_adr * (forecasted_occupancy / 100))

            rooms_sold = round(total_rooms * (forecasted_occupancy / 100))
            forecasted_revenue = rooms_sold * forecasted_adr

            # Confidence score (higher for closer dates)
            confidence_score = round(max(0.50, min(0.95, 0.95 - (days_out * 0.015))), 2)

            # YoY comparison
            yoy_comparison = {
                "occupancy_variance": round((random.random() - 0.3) * 20),
                "adr_variance": round((random.random() - 0.2) * 15),
                "revenue_variance": round((random.random() - 0.25) * 25),
            }

            forecast = DemandForecast(
                property_id=property_id,
                forecast_date=forecast_date,
                days_out=days_out,
                day_of_week=dow,
                demand_index=round(demand_index * 100, 1),
                demand_level=demand_level,
                forecasted_occupancy=forecasted_occupancy,
                forecasted_adr=forecasted_adr,
                forecasted_revpar=forecasted_revpar,
                forecasted_revenue=forecasted_revenue,
                confidence_score=confidence_score,
                price_recommendation=generate_price_recommendation(demand_level, days_out),
                yoy_comparison=yoy_comparison,
                generated_at=now,
            )
            session.add(forecast)
            summary["demand_forecasts"] += 1

    await session.commit()
    print(f"  + Created {summary['demand_forecasts']} demand forecasts")

    # ========================================================================
    # 5. MARKET EVENTS (Next 90 days)
    # ========================================================================
    print("\n[5/7] Creating market events...")

    events_data = generate_market_events(property_id, today)

    for event_data in events_data:
        # Only add events within next 90 days
        if event_data["start_date"] <= today + timedelta(days=90):
            existing = (await session.exec(
                select(MarketEvent).where(
                    MarketEvent.property_id == property_id,
                    MarketEvent.event_name == event_data["event_name"],
                    MarketEvent.start_date == event_data["start_date"]
                )
            )).first()

            if not existing:
                event = MarketEvent(
                    property_id=event_data["property_id"],
                    event_name=event_data["event_name"],
                    event_type=event_data["event_type"],
                    start_date=event_data["start_date"],
                    end_date=event_data["end_date"],
                    impact_multiplier=event_data["impact_multiplier"],
                    is_recurring=event_data.get("is_recurring", False),
                    recurrence_rule=event_data.get("recurrence_rule"),
                    notes=event_data.get("notes"),
                    created_at=now,
                )
                session.add(event)
                summary["market_events"] += 1
                print(f"  + Created event: {event_data['event_name']} ({event_data['start_date']})")
            else:
                print(f"  - Event exists: {event_data['event_name']}")

    await session.commit()

    # ========================================================================
    # 6. PICKUP PACE (Current month tracking)
    # ========================================================================
    print("\n[6/7] Creating pickup pace data...")

    for days_out in range(30):
        arrival_date = today + timedelta(days=days_out)
        dow = arrival_date.weekday()
        is_weekend = dow in [4, 5]  # Friday, Saturday

        # Check if exists
        existing = (await session.exec(
            select(PickupPace).where(
                PickupPace.property_id == property_id,
                PickupPace.arrival_date == arrival_date,
                PickupPace.snapshot_date == today
            )
        )).first()

        if not existing:
            # Expected total based on day of week
            expected_total = round(55 + random.random() * 15) if is_weekend else round(40 + random.random() * 15)

            # Booking progress based on days out
            if days_out <= 0:
                booking_progress = 0.98
            elif days_out <= 3:
                booking_progress = 0.85 + random.random() * 0.10
            elif days_out <= 7:
                booking_progress = 0.65 + random.random() * 0.15
            elif days_out <= 14:
                booking_progress = 0.45 + random.random() * 0.15
            else:
                booking_progress = 0.25 + random.random() * 0.15

            current_bookings = round(expected_total * booking_progress)
            predicted_final = round(current_bookings / booking_progress) if booking_progress > 0 else expected_total

            # LY comparison
            ly_bookings = round(expected_total * (0.85 + random.random() * 0.3))
            ly_progress = min(1, booking_progress * (0.9 + random.random() * 0.2))
            ly_at_this_point = round(ly_bookings * ly_progress)

            # LW comparison
            lw_bookings = round(current_bookings * (0.92 + random.random() * 0.16))

            # Pace status
            pace_ratio = current_bookings / ly_at_this_point if ly_at_this_point > 0 else 1.0
            pace_status = get_pace_status(pace_ratio)

            # Variances
            ly_variance_pct = round((pace_ratio - 1) * 100, 1)
            lw_variance_pct = round(((current_bookings / lw_bookings) - 1) * 100, 1) if lw_bookings > 0 else 0

            pickup = PickupPace(
                property_id=property_id,
                arrival_date=arrival_date,
                snapshot_date=today,
                days_out=days_out,
                current_bookings=current_bookings,
                expected_total=expected_total,
                predicted_final=predicted_final,
                booking_progress_pct=round(booking_progress * 100, 1),
                pace_status=pace_status,
                ly_bookings=ly_at_this_point,
                ly_variance_pct=ly_variance_pct,
                lw_bookings=lw_bookings,
                lw_variance_pct=lw_variance_pct,
                alerts=generate_pickup_alerts(days_out, pace_status, current_bookings, expected_total),
                created_at=now,
            )
            session.add(pickup)
            summary["pickup_pace"] += 1

    await session.commit()
    print(f"  + Created {summary['pickup_pace']} pickup pace records")

    # ========================================================================
    # 7. SEGMENT PERFORMANCE (Last 6 months + current)
    # ========================================================================
    print("\n[7/7] Creating segment performance data...")

    total_base_revenue = sum(s["base_revenue"] for s in SEGMENTS_DATA)

    for segment_data in SEGMENTS_DATA:
        # Create data for last 6 months
        for months_ago in range(6):
            period_date = date(today.year, today.month, 1) - timedelta(days=months_ago * 30)
            period_month = date(period_date.year, period_date.month, 1)

            existing = (await session.exec(
                select(SegmentPerformance).where(
                    SegmentPerformance.property_id == property_id,
                    SegmentPerformance.segment_name == segment_data["segment_name"],
                    SegmentPerformance.period_month == period_month
                )
            )).first()

            if not existing:
                # Apply variance to base metrics
                variance = 0.85 + random.random() * 0.30

                revenue = round(segment_data["base_revenue"] * variance)
                room_nights = round(segment_data["base_room_nights"] * variance)
                bookings = round(segment_data["base_bookings"] * variance)
                cancellations = round(bookings * segment_data["cancel_rate"])

                adr = round(revenue / room_nights) if room_nights > 0 else segment_data["base_adr"]
                revpar = round(adr * 0.70)  # Assuming 70% occupancy contribution
                cancel_rate_pct = round((cancellations / bookings) * 100, 1) if bookings > 0 else 0

                # Revenue contribution
                revenue_contribution_pct = round((segment_data["base_revenue"] / total_base_revenue) * 100, 1)

                # YoY variance
                yoy_variance_pct = round((random.random() - 0.3) * 20, 1)

                # Booking pace
                booking_pace = 0.90 + random.random() * 0.20

                perf = SegmentPerformance(
                    property_id=property_id,
                    segment_name=segment_data["segment_name"],
                    period_month=period_month,
                    revenue=revenue,
                    room_nights=room_nights,
                    bookings=bookings,
                    adr=adr,
                    revpar=revpar,
                    cancellations=cancellations,
                    cancel_rate_pct=cancel_rate_pct,
                    revenue_contribution_pct=revenue_contribution_pct,
                    avg_lead_time_days=segment_data["avg_lead_time_days"],
                    avg_los=segment_data["avg_los"],
                    yoy_variance_pct=yoy_variance_pct,
                    optimizations=generate_segment_optimizations(
                        segment_data["segment_name"],
                        segment_data["cancel_rate"],
                        booking_pace,
                        revenue_contribution_pct,
                        yoy_variance_pct
                    ),
                    created_at=now,
                )
                session.add(perf)
                summary["segment_performance"] += 1

    await session.commit()
    print(f"  + Created {summary['segment_performance']} segment performance records")

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("\n" + "=" * 60)
    print("RMS Data Seeding Complete!")
    print("=" * 60)
    print("\nSummary:")
    print(f"  - Pricing Rules: {summary['pricing_rules']}")
    print(f"  - Competitors: {summary['competitors']}")
    print(f"  - Competitor Rates: {summary['competitor_rates']}")
    print(f"  - Demand Forecasts: {summary['demand_forecasts']}")
    print(f"  - Market Events: {summary['market_events']}")
    print(f"  - Pickup Pace Records: {summary['pickup_pace']}")
    print(f"  - Segment Performance Records: {summary['segment_performance']}")
    print("=" * 60)

    return summary


# ============================================================================
# STANDALONE EXECUTION
# ============================================================================

async def main():
    """Standalone execution of RMS seeding"""
    from app.db.session import async_session_maker, init_db

    await init_db()

    async with async_session_maker() as session:
        await seed_rms_data(session, property_id=1)


if __name__ == "__main__":
    asyncio.run(main())
