"""
Channel Manager Seed Data Script
Seeds OTA connections, room/rate mappings, availability grid, restrictions, and sync logs.
"""
import random
from datetime import datetime, timedelta
from datetime import date as date_type
from typing import Optional, List
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.channel_manager import (
    OTAConnection,
    OTARoomMapping,
    OTARateMapping,
    RateOverride,
    ChannelRestriction,
    AvailabilityGrid,
    SyncLog,
)
from app.models.inventory import RoomType, RatePlan


# ============================================================================
# OTA Connection Data
# Based on Frontend/src/data/channel-manager/sampleOTAs.ts
# ============================================================================
OTA_CONNECTIONS_DATA = [
    {
        "ota_code": "BOOKING",
        "ota_name": "Booking.com",
        "logo_url": "https://cf.bstatic.com/static/img/favicon/9ca83ba2a5a3293ff07452cb24949a5843af4592.svg",
        "brand_color": "#003580",
        "connection_status": "connected",
        "api_username": "glimmora_hotel",
        "api_key_encrypted": "ENCRYPTED_PLACEHOLDER_bk_live_xxxxx",
        "hotel_id_on_ota": "BK-12345678",
        "auto_sync_enabled": True,
        "sync_interval_minutes": 5,
        "sync_rates": True,
        "sync_availability": True,
        "sync_restrictions": True,
        "commission_rate": 15.0,
        "is_active": True,
    },
    {
        "ota_code": "EXPEDIA",
        "ota_name": "Expedia",
        "logo_url": "https://www.expedia.com/favicon.ico",
        "brand_color": "#FFD700",
        "connection_status": "connected",
        "api_username": "glimmora_exp",
        "api_key_encrypted": "ENCRYPTED_PLACEHOLDER_exp_api_xxxxx",
        "hotel_id_on_ota": "EXP-987654",
        "auto_sync_enabled": True,
        "sync_interval_minutes": 5,
        "sync_rates": True,
        "sync_availability": True,
        "sync_restrictions": True,
        "commission_rate": 18.0,
        "is_active": True,
    },
    {
        "ota_code": "AGODA",
        "ota_name": "Agoda",
        "logo_url": "https://www.agoda.com/favicon.ico",
        "brand_color": "#E51937",
        "connection_status": "connected",
        "api_username": "glimmora_agoda",
        "api_key_encrypted": "ENCRYPTED_PLACEHOLDER_ag_key_xxxxx",
        "hotel_id_on_ota": "AG-456789",
        "auto_sync_enabled": True,
        "sync_interval_minutes": 5,
        "sync_rates": True,
        "sync_availability": True,
        "sync_restrictions": False,
        "commission_rate": 17.0,
        "is_active": True,
    },
    {
        "ota_code": "AIRBNB",
        "ota_name": "Airbnb",
        "logo_url": "https://www.airbnb.com/favicon.ico",
        "brand_color": "#FF5A5F",
        "connection_status": "disconnected",
        "api_username": "",
        "api_key_encrypted": "",
        "hotel_id_on_ota": "",
        "auto_sync_enabled": False,
        "sync_interval_minutes": 10,
        "sync_rates": True,
        "sync_availability": True,
        "sync_restrictions": False,
        "commission_rate": 3.0,
        "is_active": False,
    },
    {
        "ota_code": "HOTELS",
        "ota_name": "Hotels.com",
        "logo_url": "https://www.hotels.com/favicon.ico",
        "brand_color": "#8B5CF6",
        "connection_status": "connected",
        "api_username": "glimmora_hotels",
        "api_key_encrypted": "ENCRYPTED_PLACEHOLDER_htl_api_xxxxx",
        "hotel_id_on_ota": "HTL-567890",
        "auto_sync_enabled": True,
        "sync_interval_minutes": 10,
        "sync_rates": True,
        "sync_availability": True,
        "sync_restrictions": True,
        "commission_rate": 20.0,
        "is_active": True,
    },
    {
        "ota_code": "MMT",
        "ota_name": "MakeMyTrip",
        "logo_url": "https://www.makemytrip.com/favicon.ico",
        "brand_color": "#F97316",
        "connection_status": "connected",
        "api_username": "glimmora_mmt",
        "api_key_encrypted": "ENCRYPTED_PLACEHOLDER_mmt_live_xxxxx",
        "hotel_id_on_ota": "MMT-789012",
        "auto_sync_enabled": True,
        "sync_interval_minutes": 5,
        "sync_rates": True,
        "sync_availability": True,
        "sync_restrictions": True,
        "commission_rate": 20.0,
        "is_active": True,
    },
    {
        "ota_code": "TRIP",
        "ota_name": "Trip.com",
        "logo_url": "https://www.trip.com/favicon.ico",
        "brand_color": "#06B6D4",
        "connection_status": "error",
        "api_username": "glimmora_trip",
        "api_key_encrypted": "ENCRYPTED_PLACEHOLDER_trip_expired_xxxxx",
        "hotel_id_on_ota": "TRIP-345678",
        "error_message": "API authentication failed - please update credentials",
        "auto_sync_enabled": True,
        "sync_interval_minutes": 5,
        "sync_rates": True,
        "sync_availability": True,
        "sync_restrictions": True,
        "commission_rate": 16.0,
        "is_active": True,
    },
    {
        "ota_code": "GOOGLE",
        "ota_name": "Google Hotel Ads",
        "logo_url": "https://www.google.com/favicon.ico",
        "brand_color": "#10B981",
        "connection_status": "connected",
        "api_username": "glimmora_google",
        "api_key_encrypted": "ENCRYPTED_PLACEHOLDER_goog_api_xxxxx",
        "hotel_id_on_ota": "GOOG-567890",
        "auto_sync_enabled": True,
        "sync_interval_minutes": 10,
        "sync_rates": True,
        "sync_availability": True,
        "sync_restrictions": False,
        "commission_rate": 10.0,
        "is_active": True,
    },
]

# ============================================================================
# Room Mapping Data
# Based on Frontend/src/data/channel-manager/sampleRoomMappings.ts
# ============================================================================
ROOM_MAPPINGS_DATA = {
    # PMS room type slug -> OTA mappings
    "minimalist-studio": {
        "BOOKING": {"ota_room_code": "STD_DBL", "ota_room_name": "Standard Double Room"},
        "EXPEDIA": {"ota_room_code": "STDROOM", "ota_room_name": "Standard Room"},
        "AGODA": {"ota_room_code": "SD", "ota_room_name": "Standard Double"},
        "MMT": {"ota_room_code": "STD", "ota_room_name": "Standard Room"},
        "GOOGLE": {"ota_room_code": "STANDARD", "ota_room_name": "Standard"},
        "HOTELS": {"ota_room_code": "STD_RM", "ota_room_name": "Standard Room"},
    },
    "coastal-retreat": {
        "BOOKING": {"ota_room_code": "STD_DBL", "ota_room_name": "Standard Double Room"},
        "EXPEDIA": {"ota_room_code": "STDROOM", "ota_room_name": "Standard Room"},
        "AGODA": {"ota_room_code": "SD", "ota_room_name": "Standard Double"},
        "MMT": {"ota_room_code": "STD", "ota_room_name": "Standard Room"},
        "GOOGLE": {"ota_room_code": "STANDARD", "ota_room_name": "Standard"},
    },
    "urban-oasis": {
        "BOOKING": {"ota_room_code": "SUP_KNG", "ota_room_name": "Superior King Room"},
        "EXPEDIA": {"ota_room_code": "PREMIUM", "ota_room_name": "Premium Room"},
        "AGODA": {"ota_room_code": "SR", "ota_room_name": "Superior Room"},
        "GOOGLE": {"ota_room_code": "PREMIUM", "ota_room_name": "Premium"},
        "HOTELS": {"ota_room_code": "DLX_RM", "ota_room_name": "Deluxe Room"},
    },
    "sunset-vista": {
        "BOOKING": {"ota_room_code": "DLX_OV", "ota_room_name": "Deluxe Room with Ocean View"},
        "EXPEDIA": {"ota_room_code": "DLXOV", "ota_room_name": "Deluxe Ocean View"},
        "AGODA": {"ota_room_code": "DVR", "ota_room_name": "Deluxe View Room"},
        "GOOGLE": {"ota_room_code": "DELUXE", "ota_room_name": "Deluxe"},
        "HOTELS": {"ota_room_code": "DLX_VW", "ota_room_name": "Deluxe View Room"},
    },
    "pacific-suite": {
        "BOOKING": {"ota_room_code": "EXEC_STE", "ota_room_name": "Executive Suite"},
        "EXPEDIA": {"ota_room_code": "PRMSTE", "ota_room_name": "Premium Suite"},
        "GOOGLE": {"ota_room_code": "SUITE", "ota_room_name": "Suite"},
        "HOTELS": {"ota_room_code": "SUITE", "ota_room_name": "Executive Suite"},
    },
    "wellness-suite": {
        "BOOKING": {"ota_room_code": "WELL_STE", "ota_room_name": "Wellness Suite"},
        "EXPEDIA": {"ota_room_code": "WELLSTE", "ota_room_name": "Wellness Suite"},
        "GOOGLE": {"ota_room_code": "WELLNESS", "ota_room_name": "Wellness Suite"},
    },
    "family-sanctuary": {
        "BOOKING": {"ota_room_code": "FAM_STE", "ota_room_name": "Family Suite"},
        "EXPEDIA": {"ota_room_code": "FAMSTE", "ota_room_name": "Family Suite"},
        "HOTELS": {"ota_room_code": "FAM_STE", "ota_room_name": "Family Suite"},
    },
    "oceanfront-penthouse": {
        "BOOKING": {"ota_room_code": "PENT_OC", "ota_room_name": "Oceanfront Penthouse"},
        "EXPEDIA": {"ota_room_code": "PENTHOUSE", "ota_room_name": "Penthouse Suite"},
        "GOOGLE": {"ota_room_code": "PENTHOUSE", "ota_room_name": "Penthouse"},
    },
}

# ============================================================================
# Rate Plan Mapping Data
# Maps local rate plans to OTA rate codes
# ============================================================================
RATE_MAPPINGS_DATA = {
    "BAR": {
        "BOOKING": {"ota_rate_code": "BAR_BK", "ota_rate_name": "Best Available Rate", "markup_percentage": 5.0},
        "EXPEDIA": {"ota_rate_code": "BAR_EX", "ota_rate_name": "Standard Rate", "markup_percentage": 8.0},
        "AGODA": {"ota_rate_code": "BAR_AG", "ota_rate_name": "Best Rate", "markup_percentage": 6.0},
        "HOTELS": {"ota_rate_code": "BAR_HT", "ota_rate_name": "Standard Rate", "markup_percentage": 5.0},
        "MMT": {"ota_rate_code": "BAR_MM", "ota_rate_name": "Best Available", "markup_percentage": 7.0},
        "GOOGLE": {"ota_rate_code": "BAR_GG", "ota_rate_name": "Best Rate", "markup_percentage": 0.0},
    },
    "ADVANCE": {
        "BOOKING": {"ota_rate_code": "ADV_BK", "ota_rate_name": "Advance Purchase", "markup_percentage": 3.0},
        "EXPEDIA": {"ota_rate_code": "ADV_EX", "ota_rate_name": "Early Bird", "markup_percentage": 5.0},
        "AGODA": {"ota_rate_code": "ADV_AG", "ota_rate_name": "Advance Purchase", "markup_percentage": 4.0},
    },
    "MEMBER": {
        "BOOKING": {"ota_rate_code": "MEM_BK", "ota_rate_name": "Genius Rate", "markup_percentage": 0.0},
        "EXPEDIA": {"ota_rate_code": "MEM_EX", "ota_rate_name": "Member Rate", "markup_percentage": 2.0},
    },
    "WEEKEND": {
        "BOOKING": {"ota_rate_code": "WKD_BK", "ota_rate_name": "Weekend Special", "markup_percentage": 5.0},
        "EXPEDIA": {"ota_rate_code": "WKD_EX", "ota_rate_name": "Weekend Rate", "markup_percentage": 5.0},
        "HOTELS": {"ota_rate_code": "WKD_HT", "ota_rate_name": "Weekend Deal", "markup_percentage": 4.0},
    },
}

# ============================================================================
# Rate Overrides Data
# Based on Frontend/src/data/channel-manager/sampleRateOverrides.ts
# ============================================================================
def get_rate_overrides_data(room_types: dict, ota_connections: dict) -> List[dict]:
    """Generate rate override data based on available room types and OTA connections."""
    today = date_type.today()
    overrides = []

    # Standard room +5% on Booking.com for premium visibility
    if "minimalist-studio" in room_types and "BOOKING" in ota_connections:
        overrides.append({
            "ota_connection_id": ota_connections["BOOKING"],
            "room_type_id": room_types["minimalist-studio"],
            "start_date": today,
            "end_date": today + timedelta(days=7),
            "adjustment_type": "percentage",
            "adjustment_value": 5.0,
            "reason": "Booking.com premium visibility",
            "is_active": True,
        })

    # Standard room +INR 800 fixed on Expedia for commission offset
    if "coastal-retreat" in room_types and "EXPEDIA" in ota_connections:
        overrides.append({
            "ota_connection_id": ota_connections["EXPEDIA"],
            "room_type_id": room_types["coastal-retreat"],
            "start_date": today,
            "end_date": today + timedelta(days=14),
            "adjustment_type": "fixed",
            "adjustment_value": 800.0,
            "reason": "Expedia commission offset",
            "is_active": True,
        })

    # Deluxe room -8% on Agoda for flash sale
    if "urban-oasis" in room_types and "AGODA" in ota_connections:
        overrides.append({
            "ota_connection_id": ota_connections["AGODA"],
            "room_type_id": room_types["urban-oasis"],
            "start_date": today + timedelta(days=10),
            "end_date": today + timedelta(days=20),
            "adjustment_type": "percentage",
            "adjustment_value": -8.0,
            "reason": "Flash sale campaign",
            "is_active": True,
        })

    # Suite +15% across all OTAs for peak season
    if "pacific-suite" in room_types and "BOOKING" in ota_connections:
        overrides.append({
            "ota_connection_id": ota_connections["BOOKING"],
            "room_type_id": room_types["pacific-suite"],
            "start_date": today + timedelta(days=20),
            "end_date": today + timedelta(days=30),
            "adjustment_type": "percentage",
            "adjustment_value": 15.0,
            "reason": "Peak season premium",
            "is_active": True,
        })

    # Suite -INR 2000 on Google for promotion
    if "wellness-suite" in room_types and "GOOGLE" in ota_connections:
        overrides.append({
            "ota_connection_id": ota_connections["GOOGLE"],
            "room_type_id": room_types["wellness-suite"],
            "start_date": today + timedelta(days=5),
            "end_date": today + timedelta(days=15),
            "adjustment_type": "fixed",
            "adjustment_value": -2000.0,
            "reason": "Google Hotel Ads promotion",
            "is_active": True,
        })

    # Hotels.com premium for sunset vista
    if "sunset-vista" in room_types and "HOTELS" in ota_connections:
        overrides.append({
            "ota_connection_id": ota_connections["HOTELS"],
            "room_type_id": room_types["sunset-vista"],
            "start_date": today + timedelta(days=3),
            "end_date": today + timedelta(days=18),
            "adjustment_type": "percentage",
            "adjustment_value": 8.0,
            "reason": "Hotels.com rewards program premium",
            "is_active": True,
        })

    return overrides


# ============================================================================
# Restrictions Data
# Based on Frontend/src/data/channel-manager/sampleRestrictions.ts
# ============================================================================
def get_restrictions_data(room_types: dict, ota_connections: dict) -> List[dict]:
    """Generate channel restriction data."""
    today = date_type.today()
    restrictions = []

    # Min stay 2 nights for Valentine's Day weekend (all rooms, all channels)
    for day_offset in range(14, 17):
        restrictions.append({
            "ota_connection_id": None,  # Applies to all channels
            "room_type_id": None,  # Applies to all rooms
            "restriction_date": today + timedelta(days=day_offset),
            "restriction_type": "min_stay",
            "restriction_value": 2,
            "reason": "Valentine's Day weekend - minimum 2 nights",
            "is_active": True,
        })

    # Min stay 3 nights for Suite during high demand period
    if "pacific-suite" in room_types:
        for day_offset in range(20, 26):
            restrictions.append({
                "ota_connection_id": None,
                "room_type_id": room_types["pacific-suite"],
                "restriction_date": today + timedelta(days=day_offset),
                "restriction_type": "min_stay",
                "restriction_value": 3,
                "reason": "High demand period - Suite minimum 3 nights",
                "is_active": True,
            })

    # CTA (Closed to Arrival) for Standard on Booking.com during conference
    if "minimalist-studio" in room_types and "BOOKING" in ota_connections:
        for day_offset in range(5, 8):
            restrictions.append({
                "ota_connection_id": ota_connections["BOOKING"],
                "room_type_id": room_types["minimalist-studio"],
                "restriction_date": today + timedelta(days=day_offset),
                "restriction_type": "CTA",
                "restriction_value": 1,
                "reason": "CTA for Booking.com during conference",
                "is_active": True,
            })

    # CTD (Closed to Departure) for Deluxe on Expedia
    if "sunset-vista" in room_types and "EXPEDIA" in ota_connections:
        for day_offset in range(8, 11):
            restrictions.append({
                "ota_connection_id": ota_connections["EXPEDIA"],
                "room_type_id": room_types["sunset-vista"],
                "restriction_date": today + timedelta(days=day_offset),
                "restriction_type": "CTD",
                "restriction_value": 1,
                "reason": "CTD for Expedia - inventory management",
                "is_active": True,
            })

    # Stop Sell for Premium on Agoda (rate parity correction)
    if "urban-oasis" in room_types and "AGODA" in ota_connections:
        for day_offset in range(12, 15):
            restrictions.append({
                "ota_connection_id": ota_connections["AGODA"],
                "room_type_id": room_types["urban-oasis"],
                "restriction_date": today + timedelta(days=day_offset),
                "restriction_type": "stop_sell",
                "restriction_value": 1,
                "reason": "Stop sell for Agoda - rate parity correction",
                "is_active": True,
            })

    # Max stay 7 nights during peak season (all rooms, all channels)
    for day_offset in range(25, 31):
        restrictions.append({
            "ota_connection_id": None,
            "room_type_id": None,
            "restriction_date": today + timedelta(days=day_offset),
            "restriction_type": "max_stay",
            "restriction_value": 7,
            "reason": "Maximum 7-night stay during peak season",
            "is_active": True,
        })

    return restrictions


# ============================================================================
# Availability Grid Data
# Based on Frontend/src/data/inventory/sampleInventoryData.ts
# ============================================================================
ROOM_TYPE_INVENTORY = {
    "minimalist-studio": {"total": 3, "base_rate": 15000.0},
    "coastal-retreat": {"total": 3, "base_rate": 15500.0},
    "urban-oasis": {"total": 4, "base_rate": 20500.0},
    "sunset-vista": {"total": 4, "base_rate": 26000.0},
    "pacific-suite": {"total": 3, "base_rate": 32000.0},
    "wellness-suite": {"total": 2, "base_rate": 35000.0},
    "family-sanctuary": {"total": 2, "base_rate": 40000.0},
    "oceanfront-penthouse": {"total": 2, "base_rate": 62500.0},
}


def is_weekend(d: date_type) -> bool:
    """Check if date is weekend (Fri, Sat, Sun)."""
    return d.weekday() in (4, 5, 6)


def generate_availability_grid_data(room_types: dict) -> List[dict]:
    """Generate 30-day availability grid data."""
    today = date_type.today()
    grid_entries = []

    for day_offset in range(30):
        current_date = today + timedelta(days=day_offset)
        is_wknd = is_weekend(current_date)

        for slug, room_type_id in room_types.items():
            if slug not in ROOM_TYPE_INVENTORY:
                continue

            info = ROOM_TYPE_INVENTORY[slug]
            total = info["total"]
            base_rate = info["base_rate"]

            # Simulate varying occupancy
            sold = random.randint(0, max(0, total - 1))
            if is_wknd:
                sold = min(sold + 1, total)

            blocked = 1 if day_offset % 10 == 0 else 0
            available = max(0, total - sold - blocked)

            # Rate calculations with weekend premium
            rate_multiplier = 1.15 if is_wknd else 1.0
            rate_amount = round(base_rate * rate_multiplier, 2)
            min_rate = round(base_rate * 0.85, 2)
            max_rate = round(base_rate * 1.5, 2)

            # Restrictions - simulate some CTA/CTD days
            cta_flag = day_offset in (15, 16) and "standard" in slug.lower()
            ctd_flag = False
            stop_sell_flag = day_offset == 20 and "suite" in slug.lower()
            min_stay = 2 if is_wknd and "suite" in slug.lower() else 1
            max_stay = 30

            grid_entries.append({
                "room_type_id": room_type_id,
                "grid_date": current_date,
                "total_inventory": total,
                "sold": sold,
                "blocked": blocked,
                "available": available,
                "rate_amount": rate_amount,
                "min_rate": min_rate,
                "max_rate": max_rate,
                "cta_flag": cta_flag,
                "ctd_flag": ctd_flag,
                "stop_sell_flag": stop_sell_flag,
                "min_stay": min_stay,
                "max_stay": max_stay,
            })

    return grid_entries


# ============================================================================
# Sync Logs Data
# Based on Frontend/src/data/channel-manager/sampleSyncLogs.ts
# ============================================================================
def generate_sync_logs_data(ota_connections: dict) -> List[dict]:
    """Generate sample sync log entries."""
    now = datetime.utcnow()
    logs = []

    # Success: Booking.com rate update
    if "BOOKING" in ota_connections:
        started = now - timedelta(minutes=1)
        logs.append({
            "ota_connection_id": ota_connections["BOOKING"],
            "sync_type": "rates",
            "sync_direction": "push",
            "status": "success",
            "records_processed": 120,
            "records_failed": 0,
            "error_details": None,
            "started_at": started,
            "completed_at": started + timedelta(seconds=3),
            "duration_seconds": 3.2,
        })

    # Success: Expedia availability update
    if "EXPEDIA" in ota_connections:
        started = now - timedelta(minutes=3)
        logs.append({
            "ota_connection_id": ota_connections["EXPEDIA"],
            "sync_type": "availability",
            "sync_direction": "push",
            "status": "success",
            "records_processed": 28,
            "records_failed": 0,
            "error_details": None,
            "started_at": started,
            "completed_at": started + timedelta(seconds=2),
            "duration_seconds": 2.1,
        })

    # Success: Agoda restriction update
    if "AGODA" in ota_connections:
        started = now - timedelta(minutes=5)
        logs.append({
            "ota_connection_id": ota_connections["AGODA"],
            "sync_type": "restrictions",
            "sync_direction": "push",
            "status": "success",
            "records_processed": 15,
            "records_failed": 0,
            "error_details": None,
            "started_at": started,
            "completed_at": started + timedelta(seconds=1),
            "duration_seconds": 1.5,
        })

    # Error: Trip.com authentication failed
    if "TRIP" in ota_connections:
        started = now - timedelta(minutes=8)
        logs.append({
            "ota_connection_id": ota_connections["TRIP"],
            "sync_type": "full",
            "sync_direction": "push",
            "status": "failed",
            "records_processed": 0,
            "records_failed": 0,
            "error_details": '{"errorCode": "AUTH_401", "message": "API authentication failed - invalid credentials", "retryCount": 3}',
            "started_at": started,
            "completed_at": started + timedelta(seconds=5),
            "duration_seconds": 5.0,
        })

    # Success: Google rate update
    if "GOOGLE" in ota_connections:
        started = now - timedelta(minutes=12)
        logs.append({
            "ota_connection_id": ota_connections["GOOGLE"],
            "sync_type": "rates",
            "sync_direction": "push",
            "status": "success",
            "records_processed": 120,
            "records_failed": 0,
            "error_details": None,
            "started_at": started,
            "completed_at": started + timedelta(seconds=4),
            "duration_seconds": 4.3,
        })

    # Success: Booking.com promotion sync
    if "BOOKING" in ota_connections:
        started = now - timedelta(minutes=15)
        logs.append({
            "ota_connection_id": ota_connections["BOOKING"],
            "sync_type": "rates",
            "sync_direction": "push",
            "status": "success",
            "records_processed": 8,
            "records_failed": 0,
            "error_details": None,
            "started_at": started,
            "completed_at": started + timedelta(seconds=2),
            "duration_seconds": 2.0,
        })

    # Partial: MMT availability update with some skips
    if "MMT" in ota_connections:
        started = now - timedelta(minutes=20)
        logs.append({
            "ota_connection_id": ota_connections["MMT"],
            "sync_type": "availability",
            "sync_direction": "push",
            "status": "partial",
            "records_processed": 25,
            "records_failed": 5,
            "error_details": '{"skippedDates": 5, "reason": "Rate parity validation required"}',
            "started_at": started,
            "completed_at": started + timedelta(seconds=8),
            "duration_seconds": 8.5,
        })

    # Success: Expedia booking import
    if "EXPEDIA" in ota_connections:
        started = now - timedelta(minutes=30)
        logs.append({
            "ota_connection_id": ota_connections["EXPEDIA"],
            "sync_type": "bookings",
            "sync_direction": "pull",
            "status": "success",
            "records_processed": 1,
            "records_failed": 0,
            "error_details": None,
            "started_at": started,
            "completed_at": started + timedelta(seconds=3),
            "duration_seconds": 3.0,
        })

    # Error: Agoda rate sync timeout
    if "AGODA" in ota_connections:
        started = now - timedelta(minutes=45)
        logs.append({
            "ota_connection_id": ota_connections["AGODA"],
            "sync_type": "rates",
            "sync_direction": "push",
            "status": "failed",
            "records_processed": 50,
            "records_failed": 70,
            "error_details": '{"errorCode": "TIMEOUT_504", "message": "API timeout after 30 seconds"}',
            "started_at": started,
            "completed_at": started + timedelta(seconds=35),
            "duration_seconds": 35.0,
        })

    # Success: Booking.com availability update
    if "BOOKING" in ota_connections:
        started = now - timedelta(minutes=60)
        logs.append({
            "ota_connection_id": ota_connections["BOOKING"],
            "sync_type": "availability",
            "sync_direction": "push",
            "status": "success",
            "records_processed": 45,
            "records_failed": 0,
            "error_details": None,
            "started_at": started,
            "completed_at": started + timedelta(seconds=4),
            "duration_seconds": 4.0,
        })

    # Success: Google connection established
    if "GOOGLE" in ota_connections:
        started = now - timedelta(minutes=90)
        logs.append({
            "ota_connection_id": ota_connections["GOOGLE"],
            "sync_type": "full",
            "sync_direction": "push",
            "status": "success",
            "records_processed": 0,
            "records_failed": 0,
            "error_details": '{"connectionTime": "245ms", "apiVersion": "v3.2"}',
            "started_at": started,
            "completed_at": started + timedelta(seconds=1),
            "duration_seconds": 0.245,
        })

    # Success: Hotels.com rate update
    if "HOTELS" in ota_connections:
        started = now - timedelta(minutes=100)
        logs.append({
            "ota_connection_id": ota_connections["HOTELS"],
            "sync_type": "rates",
            "sync_direction": "push",
            "status": "success",
            "records_processed": 96,
            "records_failed": 0,
            "error_details": None,
            "started_at": started,
            "completed_at": started + timedelta(seconds=5),
            "duration_seconds": 5.2,
        })

    return logs


# ============================================================================
# Main Seed Function
# ============================================================================
async def seed_channel_manager_data(
    session: AsyncSession,
    property_id: int = 1,
    force_reseed: bool = False
) -> dict:
    """
    Seed Channel Manager data for the specified property.

    Args:
        session: AsyncSession for database operations
        property_id: Property ID to seed data for (default: 1)
        force_reseed: If True, delete existing data and reseed

    Returns:
        Dictionary with counts of seeded records
    """
    print("=" * 60)
    print(f"Seeding Channel Manager data for property_id={property_id}")
    print("=" * 60)

    stats = {
        "ota_connections": 0,
        "room_mappings": 0,
        "rate_mappings": 0,
        "rate_overrides": 0,
        "restrictions": 0,
        "availability_grid": 0,
        "sync_logs": 0,
    }

    # Check if data already exists (idempotency check)
    existing_connections = await session.exec(
        select(OTAConnection).where(OTAConnection.property_id == property_id)
    )
    existing = existing_connections.first()

    if existing and not force_reseed:
        print(f"Channel Manager data already exists for property {property_id}. Skipping...")
        print("Use force_reseed=True to delete and reseed data.")
        return stats

    if existing and force_reseed:
        print("Removing existing Channel Manager data...")
        # Delete in reverse order of dependencies
        await session.exec(
            select(SyncLog).where(SyncLog.property_id == property_id)
        )
        for log in (await session.exec(select(SyncLog).where(SyncLog.property_id == property_id))).all():
            await session.delete(log)

        for grid in (await session.exec(select(AvailabilityGrid).where(AvailabilityGrid.property_id == property_id))).all():
            await session.delete(grid)

        for restriction in (await session.exec(select(ChannelRestriction).where(ChannelRestriction.property_id == property_id))).all():
            await session.delete(restriction)

        for override in (await session.exec(select(RateOverride).where(RateOverride.property_id == property_id))).all():
            await session.delete(override)

        for rate_mapping in (await session.exec(select(OTARateMapping).where(OTARateMapping.property_id == property_id))).all():
            await session.delete(rate_mapping)

        for room_mapping in (await session.exec(select(OTARoomMapping).where(OTARoomMapping.property_id == property_id))).all():
            await session.delete(room_mapping)

        for connection in (await session.exec(select(OTAConnection).where(OTAConnection.property_id == property_id))).all():
            await session.delete(connection)

        await session.commit()
        print("Existing data removed.")

    # ========== Step 1: Get Room Types ==========
    print("\n[1/7] Loading room types...")
    room_types_result = await session.exec(select(RoomType).where(RoomType.is_active == True))
    room_types_list = room_types_result.all()
    room_types_map = {rt.slug: rt.id for rt in room_types_list}
    print(f"  Found {len(room_types_map)} room types")

    if not room_types_map:
        print("  WARNING: No room types found. Please seed room types first.")
        return stats

    # ========== Step 2: Get Rate Plans ==========
    print("\n[2/7] Loading rate plans...")
    rate_plans_result = await session.exec(select(RatePlan).where(RatePlan.is_active == True))
    rate_plans_list = rate_plans_result.all()
    rate_plans_map = {rp.code: rp.id for rp in rate_plans_list}
    print(f"  Found {len(rate_plans_map)} rate plans")

    # ========== Step 3: Create OTA Connections ==========
    print("\n[3/7] Creating OTA connections...")
    ota_connections_map = {}
    now = datetime.utcnow()

    for ota_data in OTA_CONNECTIONS_DATA:
        last_sync = now - timedelta(minutes=random.randint(1, 30)) if ota_data["connection_status"] == "connected" else None
        next_sync = now + timedelta(minutes=ota_data["sync_interval_minutes"]) if ota_data["auto_sync_enabled"] and ota_data["connection_status"] == "connected" else None

        connection = OTAConnection(
            property_id=property_id,
            ota_code=ota_data["ota_code"],
            ota_name=ota_data["ota_name"],
            logo_url=ota_data.get("logo_url"),
            brand_color=ota_data.get("brand_color"),
            connection_status=ota_data["connection_status"],
            last_sync_at=last_sync,
            next_sync_at=next_sync,
            error_message=ota_data.get("error_message"),
            api_username=ota_data.get("api_username"),
            api_key_encrypted=ota_data.get("api_key_encrypted"),
            hotel_id_on_ota=ota_data.get("hotel_id_on_ota"),
            auto_sync_enabled=ota_data["auto_sync_enabled"],
            sync_interval_minutes=ota_data["sync_interval_minutes"],
            sync_rates=ota_data["sync_rates"],
            sync_availability=ota_data["sync_availability"],
            sync_restrictions=ota_data["sync_restrictions"],
            commission_rate=ota_data["commission_rate"],
            is_active=ota_data["is_active"],
        )
        session.add(connection)
        await session.flush()  # Get the ID
        ota_connections_map[ota_data["ota_code"]] = connection.id
        stats["ota_connections"] += 1
        print(f"  Created OTA connection: {ota_data['ota_name']} ({ota_data['ota_code']})")

    # ========== Step 4: Create Room Mappings ==========
    print("\n[4/7] Creating room type mappings...")
    for room_slug, ota_mappings in ROOM_MAPPINGS_DATA.items():
        if room_slug not in room_types_map:
            continue

        room_type_id = room_types_map[room_slug]

        for ota_code, mapping in ota_mappings.items():
            if ota_code not in ota_connections_map:
                continue

            room_mapping = OTARoomMapping(
                property_id=property_id,
                ota_connection_id=ota_connections_map[ota_code],
                room_type_id=room_type_id,
                ota_room_code=mapping["ota_room_code"],
                ota_room_name=mapping.get("ota_room_name"),
                is_active=True,
                sync_status="synced",
                last_synced_at=now - timedelta(minutes=random.randint(1, 15)),
            )
            session.add(room_mapping)
            stats["room_mappings"] += 1

    print(f"  Created {stats['room_mappings']} room mappings")

    # ========== Step 5: Create Rate Mappings ==========
    print("\n[5/7] Creating rate plan mappings...")
    for rate_code, ota_mappings in RATE_MAPPINGS_DATA.items():
        if rate_code not in rate_plans_map:
            continue

        rate_plan_id = rate_plans_map[rate_code]

        for ota_code, mapping in ota_mappings.items():
            if ota_code not in ota_connections_map:
                continue

            rate_mapping = OTARateMapping(
                property_id=property_id,
                ota_connection_id=ota_connections_map[ota_code],
                rate_plan_id=rate_plan_id,
                ota_rate_code=mapping["ota_rate_code"],
                ota_rate_name=mapping.get("ota_rate_name"),
                markup_percentage=mapping.get("markup_percentage", 0.0),
                is_active=True,
                last_synced_at=now - timedelta(minutes=random.randint(1, 15)),
            )
            session.add(rate_mapping)
            stats["rate_mappings"] += 1

    print(f"  Created {stats['rate_mappings']} rate mappings")

    # ========== Step 6: Create Rate Overrides ==========
    print("\n[6/7] Creating rate overrides...")
    rate_overrides = get_rate_overrides_data(room_types_map, ota_connections_map)
    for override_data in rate_overrides:
        override = RateOverride(
            property_id=property_id,
            **override_data
        )
        session.add(override)
        stats["rate_overrides"] += 1
    print(f"  Created {stats['rate_overrides']} rate overrides")

    # ========== Step 7: Create Channel Restrictions ==========
    print("\n[7/7] Creating channel restrictions...")
    restrictions = get_restrictions_data(room_types_map, ota_connections_map)
    for restriction_data in restrictions:
        restriction = ChannelRestriction(
            property_id=property_id,
            **restriction_data
        )
        session.add(restriction)
        stats["restrictions"] += 1
    print(f"  Created {stats['restrictions']} channel restrictions")

    # ========== Step 8: Create Availability Grid ==========
    print("\n[8/8] Creating availability grid (30 days)...")
    grid_entries = generate_availability_grid_data(room_types_map)
    for entry_data in grid_entries:
        entry = AvailabilityGrid(
            property_id=property_id,
            **entry_data
        )
        session.add(entry)
        stats["availability_grid"] += 1
    print(f"  Created {stats['availability_grid']} availability grid entries")

    # ========== Step 9: Create Sync Logs ==========
    print("\n[9/9] Creating sync logs...")
    sync_logs = generate_sync_logs_data(ota_connections_map)
    for log_data in sync_logs:
        log = SyncLog(
            property_id=property_id,
            **log_data
        )
        session.add(log)
        stats["sync_logs"] += 1
    print(f"  Created {stats['sync_logs']} sync log entries")

    # Commit all changes
    await session.commit()

    print("\n" + "=" * 60)
    print("Channel Manager seeding completed!")
    print("=" * 60)
    print("\nSummary:")
    for key, count in stats.items():
        print(f"  {key.replace('_', ' ').title()}: {count}")

    return stats


async def run_seed():
    """Standalone function to run the seed script."""
    from app.db.session import async_session_maker, init_db

    await init_db()
    async with async_session_maker() as session:
        await seed_channel_manager_data(session, property_id=1, force_reseed=True)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_seed())
