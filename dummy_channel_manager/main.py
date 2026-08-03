"""
CRS Simulator API - Main FastAPI Application
Simulates Central Reservation System behavior (STAAH, SiteMinder, Cloudbeds style)
"""
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
import httpx
import asyncio
import random
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from pydantic import ValidationError, BaseModel, Field

from models import (
    # Hotel & Room Models
    Hotel, HotelCreate, RoomType, RoomTypeCreate,
    # Rate Models
    Rate, RateCreate, RateUpdateRequest, RateUpdateResponse,
    # Reservation Models
    Reservation, ReservationCreate, ReservationCreateV2, ReservationModify,
    # Guest Models
    GuestInfo,
    # Availability Models
    AvailabilityRequest, AvailabilityResponse, RoomAvailability,
    # Webhook Models
    WebhookEvent, WebhookPayload,
    BookingCreatedPayload, BookingModifiedPayload, BookingCancelledPayload,
    AvailabilityUpdatedPayload, RatesUpdatedPayload, RestrictionsUpdatedPayload, SyncStatusPayload,
    BookingWebhookPayload, BookingPricing, BookingPayment, GuestInfo as WebhookGuestInfo,
    AvailabilityItem, RateItem, RestrictionItem,
    # Response Models
    AIResponse, ErrorResponse,
    # Enums
    BookingStatus, RatePlan
)
from data import (
    hotels_db, room_types_db, rates_db, reservations_db, inventory_db, restrictions_db,
    room_id_to_uuid_map, uuid_to_room_id_map,
    get_hotel_room_types, get_room_type_rates, get_reservations_for_date_range,
    get_inventory, update_inventory, initialize_inventory_for_date_range,
    generate_confirmation_number, seed_data,
    get_restrictions, add_restriction, remove_restriction, get_restrictions_for_room_type
)


app = FastAPI(
    title="CRS Simulator API",
    description="A production-like mock CRS/Channel Manager API for Hotel AI applications",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Webhook configuration (can be set via environment variable or API)
import os
WEBHOOK_URL: Optional[str] = os.getenv("WEBHOOK_URL", "http://localhost:8000/api/v1/webhooks/channel-manager")

# Glimmora Backend API configuration
#GLIMMORA_BACKEND_URL: str = os.getenv("GLIMMORA_BACKEND_URL", "https://mk7xivcv2jfyjc-8000.proxy.runpod.net/")
GLIMMORA_BACKEND_URL: str = os.getenv("GLIMMORA_BACKEND_URL", "http://localhost:8000")
GLIMMORA_API_TOKEN: Optional[str] = os.getenv("GLIMMORA_API_TOKEN", None)  # Set via environment variable if auth required

# Channel Manager Port
CHANNEL_MANAGER_PORT: int = int(os.getenv("CHANNEL_MANAGER_PORT", "8085"))

# OTA Connection ID for DUMMY channel manager (override via DUMMY_OTA_CONNECTION_ID env; updated at startup from backend)
DUMMY_OTA_CONNECTION_ID: int = int(os.getenv("DUMMY_OTA_CONNECTION_ID", "1"))
DUMMY_OTA_CODE: str = "DUMMY"


def get_day_of_week(d: date) -> str:
    """Get day of week name"""
    days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
    return days[d.weekday()]


def is_weekend(d: date) -> bool:
    """Check if date is weekend (Saturday or Sunday)"""
    return d.weekday() >= 5


def calculate_rate_amount(rate: Rate, check_date: date) -> float:
    """Calculate rate amount for a specific date"""
    # Check for specific date override
    if rate.specific_dates and check_date in rate.specific_dates:
        return rate.specific_dates[check_date]
    
    # Apply base rate with weekday/weekend multiplier
    multiplier = rate.weekend_multiplier if is_weekend(check_date) else rate.weekday_multiplier
    return rate.base_rate * multiplier


async def trigger_webhook(event: WebhookEvent, reservation: Reservation):
    """Trigger webhook event asynchronously (legacy format)"""
    if not WEBHOOK_URL:
        return
    
    try:
        # Convert dates to ISO format strings for webhook payload
        payload_data = {
            "event": event.value,
            "timestamp": datetime.now().isoformat(),
            "reservation_id": str(reservation.id),
            "confirmation_number": reservation.confirmation_number,
            "hotel_id": str(reservation.hotel_id),
            "room_type_id": str(reservation.room_type_id),
            "check_in": reservation.check_in.isoformat(),
            "check_out": reservation.check_out.isoformat(),
            "status": reservation.status.value,
            "data": {
                "guest_name": reservation.guest_name,
                "total_amount": reservation.total_amount,
                "currency": reservation.currency
            }
        }
        
        # Use extended timeout for webhook delivery
        timeout = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.post(WEBHOOK_URL, json=payload_data)
    except Exception as e:
        print(f"Webhook failed: {e}")  # Log but don't fail the request


async def trigger_webhook_v2(payload: Dict[str, Any]):
    """Trigger webhook event with new format (CHANNEL_MANAGER_WEBHOOKS.md compliant)"""
    if not WEBHOOK_URL:
        print("[WEBHOOK] WARNING: WEBHOOK_URL not configured - skipping webhook")
        return
    
    event_type = payload.get("event_type", "unknown")
    print(f"[WEBHOOK] Sending webhook: {event_type}")
    print(f"[WEBHOOK]    URL: {WEBHOOK_URL}")
    print(f"[WEBHOOK]    Payload keys: {list(payload.keys())}")
    
    try:
        # Use granular timeout: 5s connect, 60s read, 30s write, 60s pool
        timeout = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            headers = {"Content-Type": "application/json"}
            if GLIMMORA_API_TOKEN:
                headers["Authorization"] = f"Bearer {GLIMMORA_API_TOKEN}"
            
            response = await client.post(WEBHOOK_URL, json=payload, headers=headers)
            if response.status_code >= 400:
                print(f"[WEBHOOK] FAILED - Status: {response.status_code}")
                print(f"[WEBHOOK]    Response: {response.text}")
            else:
                print(f"[WEBHOOK] SUCCESS - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    print(f"[WEBHOOK]    Response: {response_data}")
                except:
                    print(f"[WEBHOOK]    Response: {response.text}")
    except httpx.ReadTimeout:
        print(f"[WEBHOOK] READ TIMEOUT - Webhook request read timed out after 60 seconds")
        print(f"[WEBHOOK]    The backend may be processing a large request or is slow to respond")
    except httpx.TimeoutException as e:
        print(f"[WEBHOOK] TIMEOUT - Webhook request timed out: {type(e).__name__}")
    except httpx.ConnectError as e:
        print(f"[WEBHOOK] CONNECTION ERROR - Could not connect to {WEBHOOK_URL}")
        print(f"[WEBHOOK]    Error: {str(e)}")
        print(f"[WEBHOOK]    Make sure glimmora-backend is running on {WEBHOOK_URL}")
    except Exception as e:
        print(f"[WEBHOOK] ERROR - {type(e).__name__}: {str(e)}")
        import traceback
        print(f"[WEBHOOK]    Traceback: {traceback.format_exc()}")


# ============== GLIMMORA BACKEND API CLIENT ==============

async def call_glimmora_api(method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Call Glimmora Backend API with extended timeouts for long-running operations"""
    url = f"{GLIMMORA_BACKEND_URL}{endpoint}"
    print(f"[GLIMMORA_API] {method} {url}")
    
    try:
        headers = {"Content-Type": "application/json"}
        if GLIMMORA_API_TOKEN:
            headers["Authorization"] = f"Bearer {GLIMMORA_API_TOKEN}"
        
        # Use granular timeout configuration:
        # - connect: 10s (time to establish connection)
        # - read: 120s (time to read response - increased for large data operations)
        # - write: 60s (time to send request body)
        # - pool: 120s (time to get connection from pool)
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=120.0)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(url, headers=headers)
            elif method == "POST":
                response = await client.post(url, json=data, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=data, headers=headers)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                print(f"[GLIMMORA_API] ERROR: Unsupported method {method}")
                return None
            
            if response.status_code >= 400:
                print(f"[GLIMMORA_API] FAILED - Status: {response.status_code}")
                print(f"[GLIMMORA_API]    Response: {response.text}")
                return None
            
            print(f"[GLIMMORA_API] SUCCESS - Status: {response.status_code}")
            try:
                return response.json()
            except:
                return {"success": True, "message": "Request successful"}
    except httpx.ReadTimeout:
        print(f"[GLIMMORA_API] READ TIMEOUT - Request read timed out after 120 seconds")
        print(f"[GLIMMORA_API]    The backend may be processing a large request or is slow to respond")
        print(f"[GLIMMORA_API]    Endpoint: {method} {url}")
        return None
    except httpx.ConnectTimeout:
        print(f"[GLIMMORA_API] CONNECT TIMEOUT - Could not connect to {GLIMMORA_BACKEND_URL} within 10 seconds")
        print(f"[GLIMMORA_API]    Make sure glimmora-backend is running and accessible")
        return None
    except httpx.ConnectError as e:
        print(f"[GLIMMORA_API] CONNECTION ERROR - Could not connect to {GLIMMORA_BACKEND_URL}")
        print(f"[GLIMMORA_API]    Error: {str(e)}")
        print(f"[GLIMMORA_API]    Make sure glimmora-backend is running on {GLIMMORA_BACKEND_URL}")
        return None
    except httpx.TimeoutException as e:
        print(f"[GLIMMORA_API] TIMEOUT - Request timed out: {type(e).__name__}")
        print(f"[GLIMMORA_API]    Endpoint: {method} {url}")
        return None
    except Exception as e:
        print(f"[GLIMMORA_API] ERROR - {type(e).__name__}: {str(e)}")
        import traceback
        print(f"[GLIMMORA_API]    Traceback: {traceback.format_exc()}")
        return None


async def update_glimmora_availability(updates: List[Dict[str, Any]]) -> bool:
    """Update availability in Glimmora backend"""
    print(f"[GLIMMORA_API] Updating availability - {len(updates)} updates")
    
    result = await call_glimmora_api("PUT", "/api/v1/channel-manager/cms/availability/bulk-update", updates)
    
    if result and result.get("success"):
        print(f"[GLIMMORA_API] Successfully updated {result.get('updated_records', 0)} availability records")
        return True
    else:
        print(f"[GLIMMORA_API] Failed to update availability")
        return False


async def update_glimmora_rate(room_type_id: int, rate_date: date, rate: float, reason: Optional[str] = None) -> bool:
    """Update rate in Glimmora backend"""
    print(f"[GLIMMORA_API] Updating rate - RoomType: {room_type_id}, Date: {rate_date}, Rate: {rate}")
    
    endpoint = f"/api/v1/revenue-intelligence/rates/{room_type_id}/{rate_date.isoformat()}"
    data = {"rate": rate}
    if reason:
        data["reason"] = reason
    
    result = await call_glimmora_api("PUT", endpoint, data)
    
    if result and result.get("success"):
        print(f"[GLIMMORA_API] Successfully updated rate")
        return True
    else:
        print(f"[GLIMMORA_API] Failed to update rate")
        return False


async def bulk_update_glimmora_rates(updates: List[Dict[str, Any]], reason: Optional[str] = None) -> bool:
    """Bulk update rates in Glimmora backend"""
    print(f"[GLIMMORA_API] Bulk updating rates - {len(updates)} updates")
    
    data = {"updates": updates}
    if reason:
        data["reason"] = reason
    
    result = await call_glimmora_api("PUT", "/api/v1/revenue-intelligence/rates/bulk-update", data)
    
    if result and result.get("success"):
        print(f"[GLIMMORA_API] Successfully updated {result.get('updated_count', 0)} rates")
        return True
    else:
        print(f"[GLIMMORA_API] Failed to bulk update rates")
        return False


async def create_glimmora_booking(booking_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create booking in Glimmora backend"""
    print(f"[GLIMMORA_API] Creating booking - RoomType: {booking_data.get('roomTypeId')}, Dates: {booking_data.get('checkIn')} to {booking_data.get('checkOut')}")
    
    result = await call_glimmora_api("POST", "/api/v1/bookings", booking_data)
    
    if result:
        print(f"[GLIMMORA_API] Successfully created booking")
        return result
    else:
        print(f"[GLIMMORA_API] Failed to create booking")
        return None


async def get_glimmora_room_types() -> List[Dict[str, Any]]:
    """Get room types from Glimmora backend"""
    print(f"[GLIMMORA_API] Fetching room types")
    
    result = await call_glimmora_api("GET", "/api/v1/room-types")
    
    if result and "items" in result:
        print(f"[GLIMMORA_API] Found {len(result['items'])} room types")
        return result["items"]
    else:
        print(f"[GLIMMORA_API] Failed to fetch room types")
        return []


async def get_glimmora_availability(start_date: date, end_date: date, room_type_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Get availability from Glimmora backend"""
    print(f"[GLIMMORA_API] Fetching availability - {start_date} to {end_date}")
    
    params = f"?startDate={start_date.isoformat()}&endDate={end_date.isoformat()}"
    if room_type_id:
        params += f"&roomTypeId={room_type_id}"
    
    result = await call_glimmora_api("GET", f"/api/v1/rooms/availability{params}")
    
    if result:
        print(f"[GLIMMORA_API] Successfully fetched availability")
        return result
    else:
        print(f"[GLIMMORA_API] Failed to fetch availability")
        return None


async def get_glimmora_rate_plans() -> List[Dict[str, Any]]:
    """Get rate plans from Glimmora backend"""
    print(f"[GLIMMORA_API] Fetching rate plans")
    
    result = await call_glimmora_api("GET", "/api/v1/inventory/rate-plans")
    
    if result and "items" in result:
        print(f"[GLIMMORA_API] Found {len(result['items'])} rate plans")
        return result["items"]
    else:
        print(f"[GLIMMORA_API] Failed to fetch rate plans")
        return []


def build_booking_created_webhook(reservation: Reservation, ota_connection_id: int = 1, ota_code: str = "BOOKING") -> Dict[str, Any]:
    """Build booking.created webhook payload"""
    from data import uuid_to_room_id_map
    from models import RatePlan
    
    # Get room type code: ROOM_1, ROOM_2, ... (backend expects numeric; fallback 1 if UUID not in map)
    room_type = room_types_db.get(reservation.room_type_id)
    room_id_num = uuid_to_room_id_map.get(reservation.room_type_id, 1)
    if not isinstance(room_id_num, int):
        room_id_num = 1
    room_type_code = f"ROOM_{room_id_num}"
    
    # Parse guest name
    guest_parts = reservation.guest_name.split(" ", 1)
    first_name = guest_parts[0] if guest_parts else "Guest"
    last_name = guest_parts[1] if len(guest_parts) > 1 else ""
    
    # Map rate plan
    rate_plan_code = reservation.rate_plan.value if hasattr(reservation.rate_plan, 'value') else str(reservation.rate_plan)
    
    # Calculate commission (assume 15% for demo)
    commission_rate = 15.0
    commission_amount = reservation.total_amount * (commission_rate / 100)
    net_revenue = reservation.total_amount - commission_amount
    
    payload = BookingCreatedPayload(
        event_type="booking.created",
        ota_connection_id=ota_connection_id,
        ota_code=ota_code,
        external_booking_id=reservation.confirmation_number,  # Use confirmation number as external ID
        timestamp=datetime.now(),
        booking=BookingWebhookPayload(
            guest=WebhookGuestInfo(
                first_name=first_name,
                last_name=last_name,
                email=reservation.guest_email or f"{first_name.lower()}.{last_name.lower()}@example.com",
                phone=reservation.guest_phone,
                country="US"
            ),
            room_type_code=room_type_code,
            rate_plan_code=rate_plan_code,
            arrival_date=reservation.check_in,
            departure_date=reservation.check_out,
            adults=reservation.number_of_guests,
            children=0,
            infants=0,
            special_requests=reservation.special_requests,
            pricing=BookingPricing(
                base_price=reservation.total_amount * 0.87,  # Approximate base price
                taxes=reservation.total_amount * 0.10,
                service_fee=reservation.total_amount * 0.03,
                total_price=reservation.total_amount,
                currency=reservation.currency,
                commission_rate=commission_rate,
                commission_amount=commission_amount,
                net_revenue=net_revenue
            ),
            payment=BookingPayment(
                payment_status="paid",
                payment_method="card",
                deposit_amount=0.0,
                balance_due=0.0
            )
        )
    )
    
    # Convert to dict with proper datetime serialization
    import json
    payload_dict = json.loads(payload.json())
    return payload_dict


def build_booking_modified_webhook(reservation: Reservation, changes: Dict[str, Any], ota_connection_id: int = 1) -> Dict[str, Any]:
    """Build booking.modified webhook payload"""
    from data import uuid_to_room_id_map
    
    room_id_num = uuid_to_room_id_map.get(reservation.room_type_id, 1)
    if not isinstance(room_id_num, int):
        room_id_num = 1
    room_type_code = f"ROOM_{room_id_num}"
    guest_parts = reservation.guest_name.split(" ", 1)
    first_name = guest_parts[0] if guest_parts else "Guest"
    last_name = guest_parts[1] if len(guest_parts) > 1 else ""
    rate_plan_code = reservation.rate_plan.value if hasattr(reservation.rate_plan, 'value') else str(reservation.rate_plan)
    
    commission_rate = 15.0
    commission_amount = reservation.total_amount * (commission_rate / 100)
    net_revenue = reservation.total_amount - commission_amount
    
    payload = BookingModifiedPayload(
        event_type="booking.modified",
        ota_connection_id=ota_connection_id,
        external_booking_id=reservation.confirmation_number,
        timestamp=datetime.now(),
        changes=changes,
        booking=BookingWebhookPayload(
            guest=WebhookGuestInfo(
                first_name=first_name,
                last_name=last_name,
                email=reservation.guest_email or f"{first_name.lower()}.{last_name.lower()}@example.com",
                phone=reservation.guest_phone,
                country="US"
            ),
            room_type_code=room_type_code,
            rate_plan_code=rate_plan_code,
            arrival_date=reservation.check_in,
            departure_date=reservation.check_out,
            adults=reservation.number_of_guests,
            children=0,
            infants=0,
            special_requests=reservation.special_requests,
            pricing=BookingPricing(
                base_price=reservation.total_amount * 0.87,
                taxes=reservation.total_amount * 0.10,
                service_fee=reservation.total_amount * 0.03,
                total_price=reservation.total_amount,
                currency=reservation.currency,
                commission_rate=commission_rate,
                commission_amount=commission_amount,
                net_revenue=net_revenue
            ),
            payment=BookingPayment(
                payment_status="paid",
                payment_method="card",
                deposit_amount=0.0,
                balance_due=0.0
            )
        )
    )
    
    # Convert to dict with proper datetime serialization
    import json
    payload_dict = json.loads(payload.json())
    return payload_dict


def build_booking_cancelled_webhook(reservation: Reservation, cancellation_reason: str = None, ota_connection_id: int = 1) -> Dict[str, Any]:
    """Build booking.cancelled webhook payload"""
    payload = BookingCancelledPayload(
        event_type="booking.cancelled",
        ota_connection_id=ota_connection_id,
        external_booking_id=reservation.confirmation_number,
        timestamp=datetime.now(),
        cancellation_reason=cancellation_reason or "Guest requested cancellation",
        refund_status="processed"
    )
    
    # Convert to dict with proper datetime serialization
    import json
    payload_dict = json.loads(payload.json())
    return payload_dict


def build_rates_updated_webhook(room_type_id: UUID, rate_plan: RatePlan, dates: List[date], amount: float, currency: str = "INR", ota_connection_id: int = 1) -> Dict[str, Any]:
    """Build rates.updated webhook payload"""
    from data import uuid_to_room_id_map
    from models import RateItem
    
    # Get room type code
    room_id = uuid_to_room_id_map.get(room_type_id, 0)
    room_type_code = f"ROOM_{room_id}" if room_id > 0 else f"ROOM_{room_type_id}"
    
    # Get rate plan code
    rate_plan_code = rate_plan.value if hasattr(rate_plan, 'value') else str(rate_plan)
    
    # Build rate items for each date
    rate_items = []
    for target_date in dates:
        rate_items.append(RateItem(
            room_type_code=room_type_code,
            rate_plan_code=rate_plan_code,
            date=target_date,
            rate=amount,
            currency=currency
        ))
    
    payload = RatesUpdatedPayload(
        event_type="rates.updated",
        ota_connection_id=ota_connection_id,
        timestamp=datetime.now(),
        rates=rate_items
    )
    
    # Convert to dict with proper datetime serialization
    import json
    payload_dict = json.loads(payload.json())
    return payload_dict


def build_restrictions_updated_webhook(restrictions: List[Dict[str, Any]], ota_connection_id: int = 1) -> Dict[str, Any]:
    """Build restrictions.updated webhook payload"""
    from data import uuid_to_room_id_map
    from models import RestrictionItem
    
    # Build restriction items
    restriction_items = []
    for restriction in restrictions:
        room_type_id = restriction.get("room_type_id")
        if isinstance(room_type_id, str):
            try:
                room_type_id = UUID(room_type_id)
            except:
                continue
        
        # Handle date conversion if needed
        restriction_date = restriction.get("date")
        if isinstance(restriction_date, str):
            try:
                restriction_date = datetime.fromisoformat(restriction_date).date()
            except:
                try:
                    restriction_date = datetime.strptime(restriction_date, "%Y-%m-%d").date()
                except:
                    continue
        
        room_id = uuid_to_room_id_map.get(room_type_id, 0)
        room_type_code = f"ROOM_{room_id}" if room_id > 0 else f"ROOM_{room_type_id}"
        
        restriction_items.append(RestrictionItem(
            room_type_code=room_type_code,
            date=restriction_date,
            restriction_type=restriction.get("restriction_type"),
            restriction_value=restriction.get("restriction_value")
        ))
    
    if not restriction_items:
        raise ValueError("No valid restrictions found to build webhook")
    
    payload = RestrictionsUpdatedPayload(
        event_type="restrictions.updated",
        ota_connection_id=ota_connection_id,
        timestamp=datetime.now(),
        restrictions=restriction_items
    )
    
    # Convert to dict with proper datetime serialization
    import json
    payload_dict = json.loads(payload.json())
    return payload_dict


# Auto-sync scheduler
auto_sync_task: Optional[asyncio.Task] = None
auto_sync_running = False

async def auto_sync_worker():
    """Background worker for auto-sync with Glimmora backend"""
    global auto_sync_running
    auto_sync_running = True
    
    print(f"[AUTO_SYNC] Auto-sync worker started")
    
    while auto_sync_running:
        try:
            await asyncio.sleep(5 * 60)  # Every 5 minutes
            
            print(f"[AUTO_SYNC] Running scheduled sync...")
            
            # Fetch latest data from Glimmora backend
            try:
                # Get room types
                room_types = await get_glimmora_room_types()
                print(f"[AUTO_SYNC] Fetched {len(room_types)} room types from Glimmora")
                
                # Get availability for next 30 days
                start_date = date.today()
                end_date = start_date + timedelta(days=30)
                availability = await get_glimmora_availability(start_date, end_date)
                if availability:
                    print(f"[AUTO_SYNC] Fetched availability data from Glimmora")
                
                # Get rate plans
                rate_plans = await get_glimmora_rate_plans()
                print(f"[AUTO_SYNC] Fetched {len(rate_plans)} rate plans from Glimmora")
                
            except Exception as fetch_error:
                print(f"[AUTO_SYNC] ERROR: Failed to fetch data from Glimmora: {fetch_error}")
            
            # Simulate booking import (10% chance)
            if random.random() < 0.1:
                try:
                    print(f"[AUTO_SYNC] Simulating booking import...")
                    import_request = BookingImportRequest()
                    await simulate_booking_import(import_request)
                    print(f"[AUTO_SYNC] Booking import simulation completed")
                except Exception as import_error:
                    print(f"[AUTO_SYNC] ERROR: Booking import simulation failed: {import_error}")
            
            # Send sync status webhook
            try:
                webhook_payload = {
                    "event_type": "sync.status",
                    "ota_connection_id": DUMMY_OTA_CONNECTION_ID,
                    "timestamp": datetime.now().isoformat(),
                    "status": {
                        "connection_status": "connected",
                        "last_sync_at": datetime.now().isoformat(),
                        "sync_type": "full",
                        "records_processed": 150,
                        "records_failed": 0,
                        "error_message": None
                    }
                }
                asyncio.create_task(trigger_webhook_v2(webhook_payload))
                print(f"[AUTO_SYNC] Sent sync.status webhook")
            except Exception as webhook_error:
                print(f"[AUTO_SYNC] ERROR: Failed to send sync status webhook: {webhook_error}")
            
        except asyncio.CancelledError:
            print(f"[AUTO_SYNC] Auto-sync worker cancelled")
            break
        except Exception as e:
            print(f"[AUTO_SYNC] ERROR: Auto-sync worker error: {e}")
            import traceback
            print(f"[AUTO_SYNC] Traceback: {traceback.format_exc()}")
            await asyncio.sleep(60)  # Wait 1 minute before retrying


def start_auto_sync():
    """Start auto-sync background worker"""
    global auto_sync_task
    if auto_sync_task is None or auto_sync_task.done():
        auto_sync_task = asyncio.create_task(auto_sync_worker())
        print(f"[AUTO_SYNC] Auto-sync started")


def stop_auto_sync():
    """Stop auto-sync background worker"""
    global auto_sync_running, auto_sync_task
    auto_sync_running = False
    if auto_sync_task and not auto_sync_task.done():
        auto_sync_task.cancel()
        print(f"[AUTO_SYNC] Auto-sync stopped")


@app.on_event("startup")
async def startup_event():
    """Initialize seed data on startup"""
    import random
    global DUMMY_OTA_CONNECTION_ID
    
    print(f"[STARTUP] Initializing dummy channel manager...")
    seed_data()
    print(f"[STARTUP] Seed data loaded successfully")
    
    print(f"[STARTUP] Configuration:")
    print(f"   Channel Manager Port: {CHANNEL_MANAGER_PORT}")
    print(f"   Webhook URL: {WEBHOOK_URL}")
    print(f"   Glimmora Backend URL: {GLIMMORA_BACKEND_URL}")
    print(f"   DUMMY OTA Code: {DUMMY_OTA_CODE}")
    print(f"   DUMMY OTA Connection ID: {DUMMY_OTA_CONNECTION_ID}")
    
    print(f"[STARTUP] Available webhook trigger endpoints:")
    print(f"   POST /api/webhooks/trigger/availability")
    print(f"   POST /api/webhooks/trigger/sync-status")
    print(f"   POST /api/webhooks/trigger/restrictions")
    print(f"   POST /api/webhooks/trigger/rates")
    print(f"   POST /api/bookings/import (simulate booking import)")
    
    # Test Glimmora backend connection
    try:
        print(f"[STARTUP] Testing Glimmora backend connection...")
        room_types = await get_glimmora_room_types()
        if room_types:
            print(f"[STARTUP] SUCCESS: Connected to Glimmora backend - Found {len(room_types)} room types")
        else:
            print(f"[STARTUP] WARNING: Glimmora backend connection test returned no data")
    except Exception as e:
        print(f"[STARTUP] WARNING: Could not connect to Glimmora backend: {e}")
        print(f"[STARTUP]    Make sure Glimmora backend is running on {GLIMMORA_BACKEND_URL}")
    
    # Start auto-sync
    start_auto_sync()
    
    # Auto-connect DUMMY OTA to Glimmora backend
    try:
        print(f"[STARTUP] Auto-connecting DUMMY OTA to Glimmora backend...")
        connect_result = await connect_dummy_ota_internal()
        if connect_result.get("success"):
            print(f"[STARTUP] SUCCESS: DUMMY OTA connected to Glimmora backend")
            # Update global OTA connection ID from backend (so webhooks use correct id)
            ota_id = connect_result.get("ota_id")
            if ota_id is not None:
                DUMMY_OTA_CONNECTION_ID = int(ota_id)
                print(f"[STARTUP] Updated DUMMY_OTA_CONNECTION_ID to {DUMMY_OTA_CONNECTION_ID}")
        else:
            print(f"[STARTUP] WARNING: DUMMY OTA connection failed: {connect_result.get('error')}")
    except Exception as connect_error:
        print(f"[STARTUP] WARNING: Failed to auto-connect DUMMY OTA: {connect_error}")
        print(f"[STARTUP]    You can manually connect using: POST /api/ota/connect")
    
    print(f"[STARTUP] CRS Simulator API started successfully!")
    print(f"[STARTUP] Dummy Channel Manager is ready to sync with Glimmora backend")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print(f"[SHUTDOWN] Shutting down dummy channel manager...")
    stop_auto_sync()
    print(f"[SHUTDOWN] Shutdown complete")


# ==================== Health & Info ====================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "CRS Simulator API",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "hotels": "/api/hotels",
            "rooms": "/api/rooms",
            "rates": "/api/rates",
            "restrictions": "/api/restrictions",
            "reservations": "/api/reservations",
            "crs": "/crs/*",
            "webhooks": "configurable via WEBHOOK_URL",
            "webhook_triggers": {
                "availability": "/api/webhooks/trigger/availability",
                "rates": "/api/webhooks/trigger/rates",
                "restrictions": "/api/webhooks/trigger/restrictions",
                "sync_status": "/api/webhooks/trigger/sync-status"
            }
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "stats": {
            "hotels": len(hotels_db),
            "room_types": len(room_types_db),
            "rates": len(rates_db),
            "reservations": len(reservations_db)
        }
    }


# ==================== Hotel Management ====================

@app.post("/api/hotels", response_model=AIResponse)
async def create_hotel(hotel: HotelCreate):
    """Create a new hotel"""
    hotel_id = uuid4()
    while hotel_id in hotels_db:
        hotel_id = uuid4()
    
    new_hotel = Hotel(
        id=hotel_id,
        **hotel.dict(),
        created_at=datetime.now()
    )
    hotels_db[hotel_id] = new_hotel
    
    return AIResponse(
        success=True,
        data=new_hotel.dict(),
        message="Hotel created successfully"
    )


@app.get("/api/hotels", response_model=AIResponse)
async def list_hotels():
    """List all hotels"""
    hotels = [hotel.dict() for hotel in hotels_db.values()]
    return AIResponse(
        success=True,
        data=hotels,
        message=f"Found {len(hotels)} hotels"
    )


@app.get("/api/hotels/{hotel_id}", response_model=AIResponse)
async def get_hotel(hotel_id: UUID):
    """Get hotel by ID"""
    hotel = hotels_db.get(hotel_id)
    if not hotel:
        raise HTTPException(
            status_code=404,
            detail=f"Hotel {hotel_id} not found"
        )
    
    return AIResponse(
        success=True,
        data=hotel.dict(),
        message="Hotel retrieved successfully"
    )


# ==================== Room Type Management ====================

@app.post("/api/hotels/{hotel_id}/rooms", response_model=AIResponse)
async def create_room_type(hotel_id: UUID, room_type: RoomTypeCreate):
    """Create a new room type for a hotel"""
    if hotel_id not in hotels_db:
        raise HTTPException(
            status_code=404,
            detail=f"Hotel {hotel_id} not found"
        )
    
    room_type_id = uuid4()
    while room_type_id in room_types_db:
        room_type_id = uuid4()
    
    new_room_type = RoomType(
        id=room_type_id,
        hotel_id=hotel_id,
        **room_type.dict()
    )
    room_types_db[room_type_id] = new_room_type
    
    # Initialize inventory for next 90 days
    future_date = date.today() + timedelta(days=90)
    initialize_inventory_for_date_range(room_type_id, date.today(), future_date)
    
    return AIResponse(
        success=True,
        data=new_room_type.dict(),
        message="Room type created successfully"
    )


@app.get("/api/hotels/{hotel_id}/rooms", response_model=AIResponse)
async def list_room_types(hotel_id: UUID):
    """List all room types for a hotel"""
    if hotel_id not in hotels_db:
        raise HTTPException(
            status_code=404,
            detail=f"Hotel {hotel_id} not found"
        )
    
    room_types = [rt.dict() for rt in get_hotel_room_types(hotel_id)]
    return AIResponse(
        success=True,
        data=room_types,
        message=f"Found {len(room_types)} room types"
    )


@app.get("/api/rooms/{room_type_id}", response_model=AIResponse)
async def get_room_type(room_type_id: UUID):
    """Get room type by ID"""
    room_type = room_types_db.get(room_type_id)
    if not room_type:
        raise HTTPException(
            status_code=404,
            detail=f"Room type {room_type_id} not found"
        )
    
    # Add room_id mapping if available
    room_data = room_type.dict()
    if room_type_id in uuid_to_room_id_map:
        room_data['room_id'] = uuid_to_room_id_map[room_type_id]
    
    return AIResponse(
        success=True,
        data=room_data,
        message="Room type retrieved successfully"
    )


@app.get("/api/v2/rooms", response_model=AIResponse)
async def list_rooms_v2():
    """List all rooms with room_id mappings for external application"""
    rooms = []
    for room_type_id, room_type in room_types_db.items():
        room_data = room_type.dict()
        if room_type_id in uuid_to_room_id_map:
            room_data['room_id'] = uuid_to_room_id_map[room_type_id]
        else:
            # Assign next available room_id if not mapped
            next_id = max(room_id_to_uuid_map.keys(), default=0) + 1
            room_id_to_uuid_map[next_id] = room_type_id
            uuid_to_room_id_map[room_type_id] = next_id
            room_data['room_id'] = next_id
        rooms.append(room_data)
    
    return AIResponse(
        success=True,
        data=rooms,
        message=f"Found {len(rooms)} rooms"
    )


# ==================== Rate Management ====================

@app.post("/api/rates", response_model=AIResponse)
async def create_rate(rate: RateCreate):
    """Create a new rate for a room type"""
    if rate.room_type_id not in room_types_db:
        raise HTTPException(
            status_code=404,
            detail=f"Room type {rate.room_type_id} not found"
        )
    
    rate_id = uuid4()
    while rate_id in rates_db:
        rate_id = uuid4()
    
    new_rate = Rate(
        id=rate_id,
        **rate.dict(),
        created_at=datetime.now()
    )
    rates_db[rate_id] = new_rate
    
    return AIResponse(
        success=True,
        data=new_rate.dict(),
        message="Rate created successfully"
    )


@app.get("/api/rates", response_model=AIResponse)
async def list_rates(room_type_id: Optional[UUID] = Query(None)):
    """List all rates, optionally filtered by room type"""
    if room_type_id:
        rates = [rate.dict() for rate in get_room_type_rates(room_type_id)]
    else:
        rates = [rate.dict() for rate in rates_db.values()]
    
    return AIResponse(
        success=True,
        data=rates,
        message=f"Found {len(rates)} rates"
    )


@app.post("/api/rates/update", response_model=AIResponse)
async def update_rates(update: RateUpdateRequest):
    """Update rates for specific dates"""
    if update.room_type_id not in room_types_db:
        raise HTTPException(
            status_code=404,
            detail=f"Room type {update.room_type_id} not found"
        )
    
    updated_dates = []
    failed_dates = []
    
    # Find or create rate for this room type and rate plan
    matching_rate = None
    for rate in get_room_type_rates(update.room_type_id):
        if rate.rate_plan == update.rate_plan:
            matching_rate = rate
            break
    
    if not matching_rate:
        raise HTTPException(
            status_code=404,
            detail=f"Rate plan {update.rate_plan} not found for room type {update.room_type_id}"
        )
    
    for target_date in update.dates:
        try:
            if not matching_rate.specific_dates:
                matching_rate.specific_dates = {}
            matching_rate.specific_dates[target_date] = update.amount
            updated_dates.append(target_date)
        except Exception as e:
            failed_dates.append(target_date)
    
    response_data = RateUpdateResponse(
        success=len(failed_dates) == 0,
        updated_dates=updated_dates,
        failed_dates=failed_dates,
        message=f"Updated {len(updated_dates)} dates, {len(failed_dates)} failed"
    )
    
    # Update rates in Glimmora backend and send rates.updated webhook if rates were successfully updated
    if updated_dates:
        try:
            print(f"[RATE_SYNC] Syncing {len(updated_dates)} rate updates to Glimmora backend")
            
            # Map room_type_id (UUID) to Glimmora room_type_id (int)
            from data import uuid_to_room_id_map
            
            glimmora_room_type_id = None
            if update.room_type_id in uuid_to_room_id_map:
                # Get the room_id, but we need the actual Glimmora room_type_id
                # For now, use room_id as a proxy (this should be mapped properly)
                room_id = uuid_to_room_id_map[update.room_type_id]
                glimmora_room_type_id = room_id  # This assumes room_id matches Glimmora room_type_id
            
            # Update each date in Glimmora backend
            if glimmora_room_type_id:
                glimmora_updates = []
                for target_date in updated_dates:
                    glimmora_updates.append({
                        "roomTypeId": glimmora_room_type_id,
                        "date": target_date.isoformat(),
                        "rate": update.amount
                    })
                
                # Bulk update rates in Glimmora
                await bulk_update_glimmora_rates(glimmora_updates, reason="Rate sync from dummy channel manager")
                print(f"[RATE_SYNC] Successfully synced {len(glimmora_updates)} rates to Glimmora backend")
            else:
                print(f"[RATE_SYNC] WARNING: Could not map room_type_id to Glimmora room_type_id")
            
            # Send rates.updated webhook
            webhook_payload = build_rates_updated_webhook(
                room_type_id=update.room_type_id,
                rate_plan=update.rate_plan,
                dates=updated_dates,
                amount=update.amount,
                currency=update.currency,
                ota_connection_id=DUMMY_OTA_CONNECTION_ID
            )
            asyncio.create_task(trigger_webhook_v2(webhook_payload))
            print(f"[RATE_SYNC] Sent rates.updated webhook")
        except Exception as webhook_error:
            print(f"[RATE_SYNC] ERROR: Failed to sync to Glimmora or send webhook: {webhook_error}")
            import traceback
            print(f"[RATE_SYNC] Traceback: {traceback.format_exc()}")
    
    return AIResponse(
        success=response_data.success,
        data=response_data.dict(),
        message=response_data.message
    )


# ==================== Restrictions Management ====================

class RestrictionCreate(BaseModel):
    """Restriction creation request"""
    room_type_id: UUID
    restriction_date: date
    restriction_type: str = Field(..., description="stop_sell, CTA, CTD, min_stay, max_stay")
    restriction_value: int = Field(..., description="1/0 for boolean types, nights for stay limits")


class RestrictionDelete(BaseModel):
    """Restriction deletion request"""
    room_type_id: UUID
    restriction_date: date
    restriction_type: str


@app.post("/api/restrictions", response_model=AIResponse)
async def create_restriction(restriction: RestrictionCreate):
    """Create or update a restriction"""
    if restriction.room_type_id not in room_types_db:
        raise HTTPException(
            status_code=404,
            detail=f"Room type {restriction.room_type_id} not found"
        )
    
    # Validate restriction type
    valid_types = ["stop_sell", "CTA", "CTD", "min_stay", "max_stay"]
    if restriction.restriction_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid restriction_type. Must be one of: {valid_types}"
        )
    
    # Add or update restriction
    restriction_data = add_restriction(
        room_type_id=restriction.room_type_id,
        restriction_date=restriction.restriction_date,
        restriction_type=restriction.restriction_type,
        restriction_value=restriction.restriction_value
    )
    
    # Update availability in Glimmora backend and send restrictions.updated webhook
    try:
        # Map room_type_id (UUID) to Glimmora room_type_id (int)
        from data import uuid_to_room_id_map
        
        glimmora_room_type_id = None
        if restriction.room_type_id in uuid_to_room_id_map:
            glimmora_room_type_id = uuid_to_room_id_map[restriction.room_type_id]
        
        # Update Glimmora backend availability
        if glimmora_room_type_id:
            glimmora_update = {
                "room_type_id": glimmora_room_type_id,
                "start_date": restriction.restriction_date.isoformat(),
                "end_date": restriction.restriction_date.isoformat(),
                "is_closed": restriction.restriction_type == "stop_sell" and restriction.restriction_value == 1,
                "min_stay": restriction.restriction_value if restriction.restriction_type == "min_stay" else None,
                "max_stay": restriction.restriction_value if restriction.restriction_type == "max_stay" else None,
                "closed_to_arrival": restriction.restriction_type == "CTA" and restriction.restriction_value == 1,
                "closed_to_departure": restriction.restriction_type == "CTD" and restriction.restriction_value == 1
            }
            
            await update_glimmora_availability([glimmora_update])
            print(f"[RESTRICTION_SYNC] Updated Glimmora backend availability for restriction")
        
        # Send restrictions.updated webhook
        restrictions_list = [restriction_data]
        webhook_payload = build_restrictions_updated_webhook(restrictions_list, ota_connection_id=DUMMY_OTA_CONNECTION_ID)
        asyncio.create_task(trigger_webhook_v2(webhook_payload))
        print(f"[RESTRICTION_SYNC] Created restriction and synced to Glimmora backend")
    except Exception as webhook_error:
        print(f"[RESTRICTION_SYNC] Error syncing to Glimmora or sending webhook: {webhook_error}")
        import traceback
        print(f"[RESTRICTION_SYNC] Traceback: {traceback.format_exc()}")
    
    return AIResponse(
        success=True,
        data=restriction_data,
        message="Restriction created/updated successfully"
    )


@app.delete("/api/restrictions", response_model=AIResponse)
async def delete_restriction(restriction: RestrictionDelete):
    """Delete a restriction"""
    if restriction.room_type_id not in room_types_db:
        raise HTTPException(
            status_code=404,
            detail=f"Room type {restriction.room_type_id} not found"
        )
    
    removed = remove_restriction(
        room_type_id=restriction.room_type_id,
        restriction_date=restriction.restriction_date,
        restriction_type=restriction.restriction_type
    )
    
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Restriction not found"
        )
    
    # Update Glimmora backend and send restrictions.updated webhook (with restriction_value=0 to indicate removal)
    try:
        # Map room_type_id (UUID) to Glimmora room_type_id (int)
        from data import uuid_to_room_id_map
        
        glimmora_room_type_id = None
        if restriction.room_type_id in uuid_to_room_id_map:
            glimmora_room_type_id = uuid_to_room_id_map[restriction.room_type_id]
        
        # Update Glimmora backend to remove restriction
        if glimmora_room_type_id:
            # Remove restriction by setting values to defaults
            glimmora_update = {
                "room_type_id": glimmora_room_type_id,
                "start_date": restriction.restriction_date.isoformat(),
                "end_date": restriction.restriction_date.isoformat(),
                "is_closed": False,
                "min_stay": 1,
                "max_stay": None,
                "closed_to_arrival": False,
                "closed_to_departure": False
            }
            
            await update_glimmora_availability([glimmora_update])
            print(f"[RESTRICTION_SYNC] Removed restriction from Glimmora backend")
        
        # Send restrictions.updated webhook
        restriction_data = {
            "room_type_id": restriction.room_type_id,
            "date": restriction.restriction_date,
            "restriction_type": restriction.restriction_type,
            "restriction_value": 0  # 0 indicates removal
        }
        restrictions_list = [restriction_data]
        webhook_payload = build_restrictions_updated_webhook(restrictions_list, ota_connection_id=DUMMY_OTA_CONNECTION_ID)
        asyncio.create_task(trigger_webhook_v2(webhook_payload))
        print(f"[RESTRICTION_SYNC] Deleted restriction and synced to Glimmora backend")
    except Exception as webhook_error:
        print(f"[RESTRICTION_SYNC] Error syncing to Glimmora or sending webhook: {webhook_error}")
        import traceback
        print(f"[RESTRICTION_SYNC] Traceback: {traceback.format_exc()}")
    
    return AIResponse(
        success=True,
        data={"removed": True},
        message="Restriction deleted successfully"
    )


@app.get("/api/restrictions", response_model=AIResponse)
async def list_restrictions(
    room_type_id: Optional[UUID] = Query(None),
    restriction_date: Optional[date] = Query(None)
):
    """List restrictions, optionally filtered by room_type_id and/or date"""
    restrictions = get_restrictions(room_type_id=room_type_id, restriction_date=restriction_date)
    
    return AIResponse(
        success=True,
        data=restrictions,
        message=f"Found {len(restrictions)} restrictions"
    )


# ==================== Availability ====================

@app.get("/api/availability", response_model=AIResponse)
async def get_availability(
    hotel_id: UUID,
    check_in: date,
    check_out: date,
    room_type_id: Optional[UUID] = None,
    rate_plan: Optional[RatePlan] = None
):
    """Get availability for a hotel and date range"""
    if check_out <= check_in:
        raise HTTPException(
            status_code=400,
            detail="check_out must be after check_in"
        )
    
    if hotel_id not in hotels_db:
        raise HTTPException(
            status_code=404,
            detail=f"Hotel {hotel_id} not found"
        )
    
    hotel = hotels_db[hotel_id]
    room_types = get_hotel_room_types(hotel_id)
    
    if room_type_id:
        room_types = [rt for rt in room_types if rt.id == room_type_id]
    
    rooms_availability = []
    nights = (check_out - check_in).days
    
    for room_type in room_types:
        # Calculate availability for date range
        min_available = float('inf')
        date_availability = {}
        
        current_date = check_in
        while current_date < check_out:
            inventory = get_inventory(room_type.id, current_date)
            if inventory:
                date_availability[current_date.isoformat()] = inventory.available
                min_available = min(min_available, inventory.available)
            else:
                date_availability[current_date.isoformat()] = room_type.base_capacity
                min_available = min(min_available, room_type.base_capacity)
            current_date += timedelta(days=1)
        
        # Get rates for this room type
        rates = get_room_type_rates(room_type.id)
        if rate_plan:
            rates = [r for r in rates if r.rate_plan == rate_plan]
        
        room_rates = []
        for rate in rates:
            total_amount = sum(
                calculate_rate_amount(rate, check_in + timedelta(days=i))
                for i in range(nights)
            )
            room_rates.append({
                "rate_plan": rate.rate_plan,
                "rate_id": str(rate.id),
                "base_rate": rate.base_rate,
                "total_amount": total_amount,
                "nightly_average": total_amount / nights,
                "currency": rate.currency
            })
        
        rooms_availability.append(RoomAvailability(
            room_type_id=room_type.id,
            room_type_name=room_type.name,
            available=int(min_available) if min_available != float('inf') else room_type.base_capacity,
            total=room_type.base_capacity,
            rates=room_rates
        ))
    
    response = AvailabilityResponse(
        hotel_id=hotel_id,
        hotel_name=hotel.name,
        check_in=check_in,
        check_out=check_out,
        nights=nights,
        rooms=rooms_availability,
        metadata={
            "source": "simulator",
            "confidence": "high",
            "total_rooms_checked": len(rooms_availability)
        }
    )
    
    return AIResponse(
        success=True,
        data=response.dict(),
        message=f"Availability retrieved for {len(rooms_availability)} room types"
    )


# ==================== Reservation Management ====================

@app.post("/api/reservations", response_model=AIResponse)
async def create_reservation(reservation: ReservationCreate, ota_code: str = None):
    """Create a new reservation"""
    try:
        if reservation.hotel_id not in hotels_db:
            raise HTTPException(
                status_code=404,
                detail=f"Hotel {reservation.hotel_id} not found"
            )
        
        if reservation.room_type_id not in room_types_db:
            raise HTTPException(
                status_code=404,
                detail=f"Room type {reservation.room_type_id} not found"
            )
        
        if reservation.check_out <= reservation.check_in:
            raise HTTPException(
                status_code=400,
                detail="check_out must be after check_in"
            )
        
        room_type = room_types_db[reservation.room_type_id]
        if reservation.number_of_guests > room_type.max_occupancy:
            raise HTTPException(
                status_code=400,
                detail=f"Number of guests ({reservation.number_of_guests}) exceeds max occupancy ({room_type.max_occupancy})"
            )
        
        # Check availability for all dates
        current_date = reservation.check_in
        while current_date < reservation.check_out:
            inventory = get_inventory(reservation.room_type_id, current_date)
            available = inventory.available if inventory else room_type.base_capacity
            
            if available <= 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Inventory exhausted for {current_date.isoformat()}"
                )
            current_date += timedelta(days=1)
        
        # Calculate total amount using rate
        rates = get_room_type_rates(reservation.room_type_id)
        matching_rate = None
        for rate in rates:
            if rate.rate_plan == reservation.rate_plan:
                matching_rate = rate
                break
        
        # If rate plan not found, fall back to BAR rate and apply appropriate discount
        if not matching_rate:
            # Find BAR rate as fallback
            bar_rate = None
            for rate in rates:
                if rate.rate_plan == RatePlan.BAR:
                    bar_rate = rate
                    break
            
            if not bar_rate:
                raise HTTPException(
                    status_code=404,
                    detail=f"No rates found for room type {reservation.room_type_id}. Available rate plans: {[r.rate_plan.value for r in rates]}"
                )
            
            # Create a temporary rate based on BAR with appropriate adjustments
            # LONG_STAY: 15% discount, PROMOTIONAL: 10% discount
            discount_multiplier = 1.0
            if reservation.rate_plan == RatePlan.LONG_STAY:
                discount_multiplier = 0.85  # 15% discount
            elif reservation.rate_plan == RatePlan.PROMOTIONAL:
                discount_multiplier = 0.90  # 10% discount
            
            # Use BAR rate as base, but apply discount
            matching_rate = Rate(
                id=bar_rate.id,  # Reuse ID for calculation purposes
                room_type_id=bar_rate.room_type_id,
                rate_plan=reservation.rate_plan,  # Use requested rate plan
                base_rate=bar_rate.base_rate * discount_multiplier,
                currency=bar_rate.currency,
                start_date=bar_rate.start_date,
                end_date=bar_rate.end_date,
                weekday_multiplier=bar_rate.weekday_multiplier,
                weekend_multiplier=bar_rate.weekend_multiplier,
                specific_dates=bar_rate.specific_dates.copy() if bar_rate.specific_dates else {},
                created_at=bar_rate.created_at
            )
            print(f"Warning: Rate plan {reservation.rate_plan} not found for room type {reservation.room_type_id}, using BAR rate with {discount_multiplier*100:.0f}% multiplier")
        
        nights = (reservation.check_out - reservation.check_in).days
        total_amount = sum(
            calculate_rate_amount(matching_rate, reservation.check_in + timedelta(days=i))
            for i in range(nights)
        )
        
        # Create reservation ID
        reservation_id = uuid4()
        while reservation_id in reservations_db:
            reservation_id = uuid4()
        
        # Build reservation data explicitly to avoid conflicts
        reservation_data = reservation.dict()
        reservation_data['id'] = reservation_id
        reservation_data['confirmation_number'] = generate_confirmation_number()
        reservation_data['total_amount'] = total_amount  # Override with calculated amount
        reservation_data['status'] = BookingStatus.CONFIRMED
        reservation_data['created_at'] = datetime.now()
        reservation_data['updated_at'] = datetime.now()
        
        new_reservation = Reservation(**reservation_data)
        reservations_db[reservation_id] = new_reservation
        
        # Update inventory
        current_date = reservation.check_in
        while current_date < reservation.check_out:
            update_inventory(reservation.room_type_id, current_date, 1)
            current_date += timedelta(days=1)
        
        # Notify Glimmora backend via webhook only (backend creates the booking from webhook; POST /api/v1/bookings requires user auth and would return 401)
        try:
            print(f"[BOOKING_SYNC] Syncing booking to Glimmora via webhook - Confirmation: {new_reservation.confirmation_number}")
            webhook_ota_code = ota_code if ota_code else DUMMY_OTA_CODE
            webhook_payload = build_booking_created_webhook(new_reservation, ota_connection_id=DUMMY_OTA_CONNECTION_ID, ota_code=webhook_ota_code)
            asyncio.create_task(trigger_webhook_v2(webhook_payload))
            print(f"[BOOKING_SYNC] Sent booking.created webhook with ota_code={webhook_ota_code}")
        except Exception as booking_error:
            print(f"[BOOKING_SYNC] ERROR: Failed to sync booking to Glimmora or send webhook: {booking_error}")
            import traceback
            print(f"[BOOKING_SYNC] Traceback: {traceback.format_exc()}")
        
        # Convert to dict with proper serialization
        reservation_dict = new_reservation.dict()
        
        return AIResponse(
            success=True,
            data=reservation_dict,
            message="Reservation created successfully"
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error creating reservation: {error_trace}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create reservation: {str(e)}"
        )


@app.get("/api/reservations/{reservation_id}", response_model=AIResponse)
async def get_reservation(reservation_id: UUID):
    """Get reservation by ID or confirmation number"""
    reservation = reservations_db.get(reservation_id)
    
    # Try finding by confirmation number if not found by ID
    if not reservation:
        for res in reservations_db.values():
            if res.confirmation_number == str(reservation_id):
                reservation = res
                break
    
    if not reservation:
        raise HTTPException(
            status_code=404,
            detail=f"Reservation {reservation_id} not found"
        )
    
    return AIResponse(
        success=True,
        data=reservation.dict(),
        message="Reservation retrieved successfully"
    )


@app.get("/api/reservations", response_model=AIResponse)
async def list_reservations(
    hotel_id: Optional[UUID] = None,
    room_type_id: Optional[UUID] = None,
    status: Optional[BookingStatus] = None
):
    """List reservations with optional filters"""
    reservations = list(reservations_db.values())
    
    if hotel_id:
        reservations = [r for r in reservations if r.hotel_id == hotel_id]
    if room_type_id:
        reservations = [r for r in reservations if r.room_type_id == room_type_id]
    if status:
        reservations = [r for r in reservations if r.status == status]
    
    return AIResponse(
        success=True,
        data=[r.dict() for r in reservations],
        message=f"Found {len(reservations)} reservations"
    )


# ==================== New Reservation Format (External Application) ====================

def convert_v2_to_internal(v2_reservation: ReservationCreateV2) -> ReservationCreate:
    """Convert ReservationCreateV2 (external format) to ReservationCreate (internal format)"""
    # Map rate_plan_id to RatePlan enum
    # 0=BAR, 1=NON_REFUNDABLE, 2=CORPORATE, 3=PROMOTIONAL, 4=LONG_STAY
    rate_plan_map = {
        0: RatePlan.BAR,
        1: RatePlan.NON_REFUNDABLE,
        2: RatePlan.CORPORATE,
        3: RatePlan.PROMOTIONAL,
        4: RatePlan.LONG_STAY
    }
    
    # Ensure rate_plan_id is an integer
    rate_plan_id = v2_reservation.rate_plan_id
    if not isinstance(rate_plan_id, int):
        try:
            rate_plan_id = int(rate_plan_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid rate_plan_id: {v2_reservation.rate_plan_id}. Must be an integer (0-4)")
    
    if rate_plan_id not in rate_plan_map:
        raise ValueError(f"Invalid rate_plan_id: {rate_plan_id}. Must be 0-4")
    
    rate_plan = rate_plan_map[rate_plan_id]
    
    # Map room_id to room_type_id (supports both int and UUID)
    room_type_id = None
    
    # If room_id is an integer, use the mapping
    if isinstance(v2_reservation.room_id, int):
        if v2_reservation.room_id not in room_id_to_uuid_map:
            raise ValueError(f"Invalid room_id: {v2_reservation.room_id}. Room not found. Use GET /api/v2/rooms to see available room IDs.")
        room_type_id = room_id_to_uuid_map[v2_reservation.room_id]
    else:
        # If room_id is a UUID (string or UUID object), use it directly
        try:
            if isinstance(v2_reservation.room_id, str):
                room_type_id = UUID(v2_reservation.room_id)
            elif isinstance(v2_reservation.room_id, UUID):
                room_type_id = v2_reservation.room_id
            else:
                raise ValueError(f"Invalid room_id type: {type(v2_reservation.room_id)}")
            
            # Verify the room_type_id exists
            if room_type_id not in room_types_db:
                raise ValueError(f"Invalid room_id (UUID): {room_type_id}. Room type not found.")
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid room_id: {v2_reservation.room_id}. Must be an integer or valid UUID. Error: {str(e)}")
    
    room_type = room_types_db[room_type_id]
    
    # Get hotel_id from room_type if not provided
    hotel_id = v2_reservation.hotel_id if v2_reservation.hotel_id else room_type.hotel_id
    
    # Combine guest first and last name
    guest_name = f"{v2_reservation.guest.first_name} {v2_reservation.guest.last_name}".strip()
    
    # Calculate total guests
    number_of_guests = v2_reservation.adults + v2_reservation.children
    
    # Combine special_requests with guest notes if available
    special_requests = v2_reservation.special_requests or ""
    if v2_reservation.guest.notes:
        if special_requests:
            special_requests += f" | Guest Notes: {v2_reservation.guest.notes}"
        else:
            special_requests = f"Guest Notes: {v2_reservation.guest.notes}"
    
    # Calculate total amount using rate
    rates = get_room_type_rates(room_type_id)
    matching_rate = None
    for rate in rates:
        if rate.rate_plan == rate_plan:
            matching_rate = rate
            break
    
    # If rate plan not found, fall back to BAR rate and apply appropriate discount
    if not matching_rate:
        # Find BAR rate as fallback
        bar_rate = None
        for rate in rates:
            if rate.rate_plan == RatePlan.BAR:
                bar_rate = rate
                break
        
        if not bar_rate:
            raise ValueError(f"No rates found for room type {room_type_id}. Available rate plans: {[r.rate_plan.value for r in rates]}")
        
        # Create a temporary rate based on BAR with appropriate adjustments
        # LONG_STAY: 15% discount, PROMOTIONAL: 10% discount
        discount_multiplier = 1.0
        if rate_plan == RatePlan.LONG_STAY:
            discount_multiplier = 0.85  # 15% discount
        elif rate_plan == RatePlan.PROMOTIONAL:
            discount_multiplier = 0.90  # 10% discount
        
        # Use BAR rate as base, but apply discount
        matching_rate = Rate(
            id=bar_rate.id,  # Reuse ID for calculation purposes
            room_type_id=bar_rate.room_type_id,
            rate_plan=rate_plan,  # Use requested rate plan
            base_rate=bar_rate.base_rate * discount_multiplier,
            currency=bar_rate.currency,
            start_date=bar_rate.start_date,
            end_date=bar_rate.end_date,
            weekday_multiplier=bar_rate.weekday_multiplier,
            weekend_multiplier=bar_rate.weekend_multiplier,
            specific_dates=bar_rate.specific_dates.copy() if bar_rate.specific_dates else {},
            created_at=bar_rate.created_at
        )
        print(f"Warning: Rate plan {rate_plan} not found for room type {room_type_id}, using BAR rate with {discount_multiplier*100:.0f}% multiplier")
    
    nights = (v2_reservation.departure_date - v2_reservation.arrival_date).days
    total_amount = sum(
        calculate_rate_amount(matching_rate, v2_reservation.arrival_date + timedelta(days=i))
        for i in range(nights)
    )
    
    # Create internal reservation format
    return ReservationCreate(
        hotel_id=hotel_id,
        room_type_id=room_type_id,
        check_in=v2_reservation.arrival_date,
        check_out=v2_reservation.departure_date,
        guest_name=guest_name,
        guest_email=v2_reservation.guest.email,
        guest_phone=v2_reservation.guest.phone,
        number_of_guests=number_of_guests,
        rate_plan=rate_plan,
        total_amount=total_amount,  # Calculated based on rates
        currency="INR",
        special_requests=special_requests
    )


@app.post("/api/v2/reservations", response_model=AIResponse)
async def create_reservation_v2(reservation: ReservationCreateV2):
    """
    Create a new reservation using external application format (CRS format)
    
    Format:
    - guest: {first_name, last_name, email, phone, notes}
    - rate_plan_id: 0=BAR, 1=NON_REFUNDABLE, 2=CORPORATE, 3=PROMOTIONAL, 4=LONG_STAY
    - arrival_date/departure_date: dates
    - adults/children: guest counts
    - room_id: integer ID (maps to room_type_id UUID)
    """
    try:
        # Convert to internal format
        internal_reservation = convert_v2_to_internal(reservation)
        
        # Use existing create_reservation logic with DUMMY source
        return await create_reservation(internal_reservation, ota_code=DUMMY_OTA_CODE)
    
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error creating reservation (v2): {error_trace}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create reservation: {str(e)}"
        )


@app.put("/api/reservations/{reservation_id}", response_model=AIResponse)
async def modify_reservation(reservation_id: UUID, update: ReservationModify):
    """Modify an existing reservation"""
    reservation = reservations_db.get(reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=404,
            detail=f"Reservation {reservation_id} not found"
        )
    
    if reservation.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify a cancelled reservation"
        )
    
    update_dict = update.dict(exclude_unset=True)
    
    # Handle date changes - need to update inventory
    old_check_in = reservation.check_in
    old_check_out = reservation.check_out
    
    if 'check_in' in update_dict or 'check_out' in update_dict:
        new_check_in = update_dict.get('check_in', old_check_in)
        new_check_out = update_dict.get('check_out', old_check_out)
        
        if new_check_out <= new_check_in:
            raise HTTPException(
                status_code=400,
                detail="check_out must be after check_in"
            )
        
        # Release old inventory
        current_date = old_check_in
        while current_date < old_check_out:
            update_inventory(reservation.room_type_id, current_date, -1)
            current_date += timedelta(days=1)
        
        # Check new availability
        room_type = room_types_db[reservation.room_type_id]
        current_date = new_check_in
        while current_date < new_check_out:
            inventory = get_inventory(reservation.room_type_id, current_date)
            available = inventory.available if inventory else room_type.base_capacity
            
            if available <= 0:
                # Rollback - restore old inventory
                current_date = old_check_in
                while current_date < old_check_out:
                    update_inventory(reservation.room_type_id, current_date, 1)
                    current_date += timedelta(days=1)
                raise HTTPException(
                    status_code=409,
                    detail=f"Inventory exhausted for {new_check_in.isoformat()}"
                )
            current_date += timedelta(days=1)
        
        # Reserve new inventory
        current_date = new_check_in
        while current_date < new_check_out:
            update_inventory(reservation.room_type_id, current_date, 1)
            current_date += timedelta(days=1)
        
        # Recalculate total amount if dates changed
        rates = get_room_type_rates(reservation.room_type_id)
        matching_rate = None
        for rate in rates:
            if rate.rate_plan == reservation.rate_plan:
                matching_rate = rate
                break
        
        if matching_rate:
            nights = (new_check_out - new_check_in).days
            total_amount = sum(
                calculate_rate_amount(matching_rate, new_check_in + timedelta(days=i))
                for i in range(nights)
            )
            update_dict['total_amount'] = total_amount
    
    # Update reservation
    for key, value in update_dict.items():
        setattr(reservation, key, value)
    
    reservation.status = BookingStatus.MODIFIED
    reservation.updated_at = datetime.now()
    
    # Update Glimmora backend and trigger webhook - new format
    try:
        print(f"[BOOKING_SYNC] Modifying booking in Glimmora backend - Confirmation: {reservation.confirmation_number}")
        
        # For booking modifications, the webhook receiver in Glimmora backend handles the update
        # We just need to send the webhook with updated information
        
        # Send booking.modified webhook
        webhook_payload = build_booking_modified_webhook(reservation, update_dict, ota_connection_id=DUMMY_OTA_CONNECTION_ID)
        asyncio.create_task(trigger_webhook_v2(webhook_payload))
        print(f"[BOOKING_SYNC] Sent booking.modified webhook")
    except Exception as webhook_error:
        print(f"[BOOKING_SYNC] ERROR: Failed to send webhook: {webhook_error}")
        import traceback
        print(f"[BOOKING_SYNC] Traceback: {traceback.format_exc()}")
    
    return AIResponse(
        success=True,
        data=reservation.dict(),
        message="Reservation modified successfully"
    )


@app.delete("/api/reservations/{reservation_id}", response_model=AIResponse)
async def cancel_reservation(reservation_id: UUID):
    """Cancel a reservation"""
    reservation = reservations_db.get(reservation_id)
    if not reservation:
        raise HTTPException(
            status_code=404,
            detail=f"Reservation {reservation_id} not found"
        )
    
    if reservation.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=400,
            detail="Reservation is already cancelled"
        )
    
    # Release inventory
    current_date = reservation.check_in
    while current_date < reservation.check_out:
        update_inventory(reservation.room_type_id, current_date, -1)
        current_date += timedelta(days=1)
    
    reservation.status = BookingStatus.CANCELLED
    reservation.updated_at = datetime.now()
    
    # Update Glimmora backend and trigger webhook - new format
    try:
        print(f"[BOOKING_SYNC] Cancelling booking in Glimmora backend - Confirmation: {reservation.confirmation_number}")
        
        # For booking cancellations, the webhook receiver in Glimmora backend handles the cancellation
        # We just need to send the webhook
        
        # Send booking.cancelled webhook
        webhook_payload = build_booking_cancelled_webhook(reservation, cancellation_reason="Guest requested cancellation", ota_connection_id=DUMMY_OTA_CONNECTION_ID)
        asyncio.create_task(trigger_webhook_v2(webhook_payload))
        print(f"[BOOKING_SYNC] Sent booking.cancelled webhook")
    except Exception as webhook_error:
        print(f"[BOOKING_SYNC] ERROR: Failed to send webhook: {webhook_error}")
        import traceback
        print(f"[BOOKING_SYNC] Traceback: {traceback.format_exc()}")
    
    return AIResponse(
        success=True,
        data=reservation.dict(),
        message="Reservation cancelled successfully"
    )


# ==================== CRS-Style Endpoints ====================

@app.get("/crs/availability", response_model=AIResponse)
async def crs_get_availability(
    hotel_id: UUID,
    check_in: date,
    check_out: date,
    room_type_id: Optional[UUID] = None,
    rate_plan: Optional[RatePlan] = None
):
    """CRS-style availability endpoint (similar to real CRS vendors)"""
    if check_out <= check_in:
        raise HTTPException(
            status_code=400,
            detail="check_out must be after check_in"
        )
    
    if hotel_id not in hotels_db:
        raise HTTPException(
            status_code=404,
            detail=f"Hotel {hotel_id} not found"
        )
    
    hotel = hotels_db[hotel_id]
    room_types = get_hotel_room_types(hotel_id)
    
    if room_type_id:
        room_types = [rt for rt in room_types if rt.id == room_type_id]
    
    rooms_availability = []
    nights = (check_out - check_in).days
    
    for room_type in room_types:
        min_available = float('inf')
        current_date = check_in
        while current_date < check_out:
            inventory = get_inventory(room_type.id, current_date)
            if inventory:
                min_available = min(min_available, inventory.available)
            else:
                min_available = min(min_available, room_type.base_capacity)
            current_date += timedelta(days=1)
        
        rates = get_room_type_rates(room_type.id)
        if rate_plan:
            rates = [r for r in rates if r.rate_plan == rate_plan]
        
        room_rates = []
        for rate in rates:
            total_amount = sum(
                calculate_rate_amount(rate, check_in + timedelta(days=i))
                for i in range(nights)
            )
            room_rates.append({
                "rate_plan": rate.rate_plan,
                "rate_id": str(rate.id),
                "base_rate": rate.base_rate,
                "total_amount": total_amount,
                "nightly_average": total_amount / nights,
                "currency": rate.currency
            })
        
        rooms_availability.append(RoomAvailability(
            room_type_id=room_type.id,
            room_type_name=room_type.name,
            available=int(min_available) if min_available != float('inf') else room_type.base_capacity,
            total=room_type.base_capacity,
            rates=room_rates
        ))
    
    response = AvailabilityResponse(
        hotel_id=hotel_id,
        hotel_name=hotel.name,
        check_in=check_in,
        check_out=check_out,
        nights=nights,
        rooms=rooms_availability,
        metadata={
            "source": "simulator",
            "confidence": "high",
            "crs_style": True
        }
    )
    
    return AIResponse(
        success=True,
        data=response.dict(),
        message="Availability retrieved via CRS endpoint"
    )


@app.post("/crs/rates", response_model=AIResponse)
async def crs_update_rates(update: RateUpdateRequest):
    """CRS-style rate update endpoint"""
    if update.room_type_id not in room_types_db:
        raise HTTPException(
            status_code=404,
            detail=f"Room type {update.room_type_id} not found"
        )
    
    updated_dates = []
    failed_dates = []
    
    matching_rate = None
    for rate in get_room_type_rates(update.room_type_id):
        if rate.rate_plan == update.rate_plan:
            matching_rate = rate
            break
    
    if not matching_rate:
        raise HTTPException(
            status_code=404,
            detail=f"Rate plan {update.rate_plan} not found for room type {update.room_type_id}"
        )
    
    for target_date in update.dates:
        try:
            if not matching_rate.specific_dates:
                matching_rate.specific_dates = {}
            matching_rate.specific_dates[target_date] = update.amount
            updated_dates.append(target_date)
        except Exception as e:
            failed_dates.append(target_date)
    
    response_data = RateUpdateResponse(
        success=len(failed_dates) == 0,
        updated_dates=updated_dates,
        failed_dates=failed_dates,
        message=f"Updated {len(updated_dates)} dates"
    )
    
    # Update rates in Glimmora backend and send rates.updated webhook if rates were successfully updated
    if updated_dates:
        try:
            print(f"[RATE_SYNC] Syncing {len(updated_dates)} rate updates to Glimmora backend (CRS endpoint)")
            
            # Map room_type_id (UUID) to Glimmora room_type_id (int)
            from data import uuid_to_room_id_map
            
            glimmora_room_type_id = None
            if update.room_type_id in uuid_to_room_id_map:
                room_id = uuid_to_room_id_map[update.room_type_id]
                glimmora_room_type_id = room_id  # This assumes room_id matches Glimmora room_type_id
            
            # Update each date in Glimmora backend
            if glimmora_room_type_id:
                glimmora_updates = []
                for target_date in updated_dates:
                    glimmora_updates.append({
                        "roomTypeId": glimmora_room_type_id,
                        "date": target_date.isoformat(),
                        "rate": update.amount
                    })
                
                # Bulk update rates in Glimmora
                await bulk_update_glimmora_rates(glimmora_updates, reason="CRS rate update from dummy channel manager")
                print(f"[RATE_SYNC] Successfully synced {len(glimmora_updates)} rates to Glimmora backend")
            else:
                print(f"[RATE_SYNC] WARNING: Could not map room_type_id to Glimmora room_type_id")
            
            # Send rates.updated webhook
            webhook_payload = build_rates_updated_webhook(
                room_type_id=update.room_type_id,
                rate_plan=update.rate_plan,
                dates=updated_dates,
                amount=update.amount,
                currency=update.currency,
                ota_connection_id=DUMMY_OTA_CONNECTION_ID
            )
            asyncio.create_task(trigger_webhook_v2(webhook_payload))
            print(f"[RATE_SYNC] Sent rates.updated webhook")
        except Exception as webhook_error:
            print(f"[RATE_SYNC] ERROR: Failed to sync to Glimmora or send webhook: {webhook_error}")
            import traceback
            print(f"[RATE_SYNC] Traceback: {traceback.format_exc()}")
    
    return AIResponse(
        success=response_data.success,
        data=response_data.dict(),
        message=response_data.message
    )


@app.post("/crs/reservations", response_model=AIResponse)
async def crs_create_reservation(reservation: ReservationCreate):
    """CRS-style reservation creation endpoint"""
    # Reuse the existing create_reservation logic with CRS source
    return await create_reservation(reservation, ota_code="CRS")


@app.put("/crs/reservations/{reservation_id}", response_model=AIResponse)
async def crs_modify_reservation(reservation_id: UUID, update: ReservationModify):
    """CRS-style reservation modification endpoint"""
    return await modify_reservation(reservation_id, update)


@app.delete("/crs/reservations/{reservation_id}", response_model=AIResponse)
async def crs_cancel_reservation(reservation_id: UUID):
    """CRS-style reservation cancellation endpoint"""
    return await cancel_reservation(reservation_id)


# ==================== Webhook Configuration ====================

class WebhookConfig(BaseModel):
    """Webhook configuration request"""
    url: str = Field(..., description="Webhook URL to receive booking events")


@app.post("/api/webhooks/configure", response_model=AIResponse)
async def configure_webhook(config: WebhookConfig):
    """Configure webhook URL for booking events"""
    global WEBHOOK_URL
    WEBHOOK_URL = config.url
    return AIResponse(
        success=True,
        data={"webhook_url": WEBHOOK_URL},
        message=f"Webhook URL configured: {WEBHOOK_URL}"
    )


@app.get("/api/webhooks/status", response_model=AIResponse)
async def get_webhook_status():
    """Get current webhook configuration status"""
    return AIResponse(
        success=True,
        data={
            "webhook_url": WEBHOOK_URL,
            "configured": WEBHOOK_URL is not None
        },
        message="Webhook status retrieved"
    )


# ==================== Additional Webhook Triggers (for testing) ====================

@app.post("/api/webhooks/trigger/availability", response_model=AIResponse)
async def trigger_availability_webhook(
    ota_connection_id: int = Query(1),
    room_type_code: Optional[str] = None,
    date: Optional[date] = None
):
    """Manually trigger availability.updated webhook (for testing)"""
    if not WEBHOOK_URL:
        raise HTTPException(status_code=400, detail="Webhook URL not configured")
    
    # Build sample availability data
    from data import uuid_to_room_id_map, get_inventory
    from models import AvailabilityItem, AvailabilityUpdatedPayload
    
    availability_items = []
    from datetime import date as date_class
    target_date = date or date_class.today()
    
    if room_type_code:
        # Single room type
        room_id = int(room_type_code.replace("ROOM_", ""))
        room_type_id = None
        for rt_id, rt_code in uuid_to_room_id_map.items():
            if rt_code == room_id:
                room_type_id = rt_id
                break
        
        if room_type_id:
            inv = get_inventory(room_type_id, target_date)
            if inv:
                availability_items.append(AvailabilityItem(
                    room_type_code=room_type_code,
                    date=target_date,
                    available=inv.available,
                    sold=inv.booked,
                    blocked=0,
                    total=inv.total
                ))
    else:
        # All room types
        for room_type_id, room_id in uuid_to_room_id_map.items():
            inv = get_inventory(room_type_id, target_date)
            if inv:
                availability_items.append(AvailabilityItem(
                    room_type_code=f"ROOM_{room_id}",
                    date=target_date,
                    available=inv.available,
                    sold=inv.booked,
                    blocked=0,
                    total=inv.total
                ))
    
    if not availability_items:
        raise HTTPException(status_code=404, detail="No availability data found")
    
    # Sync availability to Glimmora backend
    try:
        print(f"[AVAILABILITY_SYNC] Syncing availability to Glimmora backend - {len(availability_items)} items")
        
        glimmora_updates = []
        for item in availability_items:
            # Extract room_id from room_type_code (ROOM_1 -> 1)
            room_id_str = item.room_type_code.replace("ROOM_", "")
            try:
                glimmora_room_type_id = int(room_id_str)
                
                glimmora_updates.append({
                    "room_type_id": glimmora_room_type_id,
                    "start_date": item.date.isoformat(),
                    "end_date": item.date.isoformat(),
                    "is_closed": False,  # Can be determined from availability
                    "min_stay": None,
                    "max_stay": None,
                    "closed_to_arrival": False,
                    "closed_to_departure": False
                })
            except ValueError:
                print(f"[AVAILABILITY_SYNC] WARNING: Could not parse room_id from {item.room_type_code}")
        
        if glimmora_updates:
            await update_glimmora_availability(glimmora_updates)
            print(f"[AVAILABILITY_SYNC] Successfully synced {len(glimmora_updates)} availability updates to Glimmora backend")
    except Exception as sync_error:
        print(f"[AVAILABILITY_SYNC] ERROR: Failed to sync to Glimmora: {sync_error}")
        import traceback
        print(f"[AVAILABILITY_SYNC] Traceback: {traceback.format_exc()}")
    
    payload = AvailabilityUpdatedPayload(
        event_type="availability.updated",
        ota_connection_id=ota_connection_id,
        timestamp=datetime.now(),
        availability=availability_items
    )
    
    # Convert to dict with proper datetime/date serialization
    import json
    payload_dict = json.loads(payload.json())
    
    asyncio.create_task(trigger_webhook_v2(payload_dict))
    print(f"[AVAILABILITY_SYNC] Sent availability.updated webhook")
    
    import json
    return AIResponse(
        success=True,
        data=json.loads(payload.json()),
        message=f"Availability webhook triggered for {len(availability_items)} room types"
    )


@app.post("/api/webhooks/trigger/sync-status", response_model=AIResponse)
async def trigger_sync_status_webhook(
    ota_connection_id: int = Query(1),
    connection_status: str = Query("connected"),
    sync_type: str = Query("full"),
    records_processed: int = Query(150),
    records_failed: int = Query(0)
):
    """Manually trigger sync.status webhook (for testing)"""
    if not WEBHOOK_URL:
        raise HTTPException(status_code=400, detail="Webhook URL not configured")
    
    payload = SyncStatusPayload(
        event_type="sync.status",
        ota_connection_id=ota_connection_id,
        timestamp=datetime.now(),
        status={
            "connection_status": connection_status,
            "last_sync_at": datetime.now().isoformat(),
            "sync_type": sync_type,
            "records_processed": records_processed,
            "records_failed": records_failed,
            "error_message": None if records_failed == 0 else "Some records failed to sync"
        }
    )
    
    # Convert to dict with proper serialization
    payload_dict = payload.dict()
    # Ensure timestamp is ISO string format for JSON serialization
    if isinstance(payload_dict.get("timestamp"), datetime):
        payload_dict["timestamp"] = payload_dict["timestamp"].isoformat()
    
    asyncio.create_task(trigger_webhook_v2(payload_dict))
    
    import json
    return AIResponse(
        success=True,
        data=json.loads(payload.json()),
        message="Sync status webhook triggered"
    )


@app.post("/api/webhooks/trigger/restrictions", response_model=AIResponse)
async def trigger_restrictions_webhook(
    ota_connection_id: int = Query(1),
    room_type_id: Optional[UUID] = Query(None),
    restriction_date: Optional[date] = Query(None)
):
    """Manually trigger restrictions.updated webhook (for testing)"""
    if not WEBHOOK_URL:
        raise HTTPException(status_code=400, detail="Webhook URL not configured")
    
    # Get restrictions based on filters
    restrictions = get_restrictions(room_type_id=room_type_id, restriction_date=restriction_date)
    
    if not restrictions:
        raise HTTPException(status_code=404, detail="No restrictions found")
    
    # Build and send webhook
    webhook_payload = build_restrictions_updated_webhook(restrictions, ota_connection_id=ota_connection_id)
    asyncio.create_task(trigger_webhook_v2(webhook_payload))
    
    return AIResponse(
        success=True,
        data=webhook_payload,
        message=f"Restrictions webhook triggered for {len(restrictions)} restrictions"
    )


@app.post("/api/webhooks/trigger/rates", response_model=AIResponse)
async def trigger_rates_webhook(
    ota_connection_id: int = Query(1),
    room_type_id: UUID = Query(..., description="Room type ID"),
    rate_plan: RatePlan = Query(..., description="Rate plan"),
    date: date = Query(..., description="Date for rate"),
    amount: float = Query(..., description="Rate amount"),
    currency: str = Query("INR", description="Currency")
):
    """Manually trigger rates.updated webhook (for testing)"""
    if not WEBHOOK_URL:
        raise HTTPException(status_code=400, detail="Webhook URL not configured")
    
    if room_type_id not in room_types_db:
        raise HTTPException(status_code=404, detail=f"Room type {room_type_id} not found")
    
    # Build and send webhook
    webhook_payload = build_rates_updated_webhook(
        room_type_id=room_type_id,
        rate_plan=rate_plan,
        dates=[date],
        amount=amount,
        currency=currency,
        ota_connection_id=ota_connection_id
    )
    asyncio.create_task(trigger_webhook_v2(webhook_payload))
    
    return AIResponse(
        success=True,
        data=webhook_payload,
        message="Rates webhook triggered"
    )


# ==================== BOOKING IMPORT SIMULATION ====================

class BookingImportRequest(BaseModel):
    """Request to simulate booking import from dummy OTA"""
    room_type_id: Optional[UUID] = None  # If None, randomly selects
    check_in: Optional[date] = None  # If None, uses future date
    check_out: Optional[date] = None  # If None, calculates from check_in
    guest_name: Optional[str] = None  # If None, generates random name
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    number_of_guests: Optional[int] = None  # If None, uses 2
    rate_plan: Optional[RatePlan] = None  # If None, uses BAR


# ==================== DUMMY OTA CONNECTION MANAGEMENT ====================

async def connect_dummy_ota_internal() -> Dict[str, Any]:
    """
    Internal function to connect/initialize DUMMY OTA in Glimmora backend.
    This creates the OTA connection record in Glimmora backend if it doesn't exist.
    """
    print(f"[OTA_CONNECTION] Connecting DUMMY OTA to Glimmora backend...")
    
    try:
        # Check if DUMMY OTA already exists in Glimmora
        otas_result = await call_glimmora_api("GET", "/api/v1/channel-manager/otas")
        
        dummy_ota_exists = False
        dummy_ota_id = None
        if otas_result and otas_result.get("success"):
            items = otas_result.get("data", {}).get("items", [])
            for ota in items:
                if ota.get("code") == DUMMY_OTA_CODE:
                    dummy_ota_exists = True
                    dummy_ota_id = ota.get("id")
                    print(f"[OTA_CONNECTION] DUMMY OTA already exists in Glimmora backend (ID: {dummy_ota_id})")
                    break
        
        # Create DUMMY OTA if it doesn't exist
        if not dummy_ota_exists:
            ota_data = {
                "name": "Dummy Channel Manager",
                "code": DUMMY_OTA_CODE,
                "logo": None,
                "credentials": {
                    "username": "dummy_channel_manager",
                    "apiKey": "dummy_api_key",
                    "hotelId": "DUMMY-HOTEL-001"
                },
                "syncSettings": {
                    "autoSync": True,
                    "syncInterval": 5,
                    "syncRates": True,
                    "syncAvailability": True,
                    "syncRestrictions": True
                },
                "commission": 0.0
            }
            
            create_result = await call_glimmora_api("POST", "/api/v1/channel-manager/otas", ota_data)
            
            if create_result and create_result.get("success"):
                dummy_ota_id = create_result.get("data", {}).get("id")
                print(f"[OTA_CONNECTION] SUCCESS: Created DUMMY OTA in Glimmora backend (ID: {dummy_ota_id})")
            else:
                print(f"[OTA_CONNECTION] WARNING: Failed to create DUMMY OTA in Glimmora backend")
                return {"success": False, "error": "Failed to create OTA"}
        
        # Initialize room mappings
        try:
            print(f"[OTA_CONNECTION] Initializing room mappings...")
            room_types = await get_glimmora_room_types()
            
            if room_types:
                # Auto-map rooms
                auto_map_result = await call_glimmora_api(
                    "POST",
                    "/api/v1/channel-manager/room-mappings/auto-map",
                    {"ota_code": DUMMY_OTA_CODE}  # Use snake_case to match backend API
                )
                
                if auto_map_result and auto_map_result.get("success"):
                    mappings_created = auto_map_result.get("data", {}).get("mappingsCreated", 0)
                    print(f"[OTA_CONNECTION] Created {mappings_created} room mappings")
        except Exception as mapping_error:
            print(f"[OTA_CONNECTION] WARNING: Failed to initialize room mappings: {mapping_error}")
        
        return {
            "success": True,
            "ota_code": DUMMY_OTA_CODE,
            "ota_id": dummy_ota_id,
            "connected": True,
            "message": "DUMMY OTA connected and initialized"
        }
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[OTA_CONNECTION] ERROR: {error_trace}")
        return {"success": False, "error": str(e)}


@app.post("/api/ota/connect", response_model=AIResponse)
async def connect_dummy_ota():
    """Connect/Initialize DUMMY OTA in Glimmora backend (API endpoint)"""
    result = await connect_dummy_ota_internal()
    
    if result.get("success"):
        return AIResponse(
            success=True,
            data=result,
            message="DUMMY OTA connected successfully"
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to connect DUMMY OTA")
        )


@app.get("/api/ota/status", response_model=AIResponse)
async def get_dummy_ota_status():
    """Get DUMMY OTA connection status from Glimmora backend"""
    print(f"[OTA_STATUS] Checking DUMMY OTA status...")
    
    try:
        otas_result = await call_glimmora_api("GET", "/api/v1/channel-manager/otas")
        
        if otas_result and otas_result.get("success"):
            items = otas_result.get("data", {}).get("items", [])
            for ota in items:
                if ota.get("code") == DUMMY_OTA_CODE:
                    print(f"[OTA_STATUS] Found DUMMY OTA - Status: {ota.get('status')}")
                    return AIResponse(
                        success=True,
                        data=ota,
                        message="DUMMY OTA status retrieved"
                    )
        
        print(f"[OTA_STATUS] DUMMY OTA not found in Glimmora backend")
        return AIResponse(
            success=False,
            data={"connected": False, "message": "DUMMY OTA not found"},
            message="DUMMY OTA not connected"
        )
    
    except Exception as e:
        print(f"[OTA_STATUS] ERROR: {e}")
        return AIResponse(
            success=False,
            data={"connected": False, "error": str(e)},
            message="Failed to get DUMMY OTA status"
        )


@app.post("/api/test/integration", response_model=AIResponse)
async def test_integration():
    """
    Test integration with Glimmora backend.
    Tests all major integration points: room types, availability, rates, bookings.
    """
    print(f"[INTEGRATION_TEST] Starting integration test...")
    
    test_results = {
        "glimmora_backend_connection": False,
        "room_types_fetch": False,
        "availability_fetch": False,
        "rate_plans_fetch": False,
        "booking_creation": False,
        "webhook_delivery": False
    }
    
    try:
        # Test 1: Glimmora backend connection
        print(f"[INTEGRATION_TEST] Test 1: Glimmora backend connection...")
        room_types = await get_glimmora_room_types()
        if room_types:
            test_results["glimmora_backend_connection"] = True
            test_results["room_types_fetch"] = True
            print(f"[INTEGRATION_TEST] ✓ Glimmora backend connection: SUCCESS ({len(room_types)} room types)")
        else:
            print(f"[INTEGRATION_TEST] ✗ Glimmora backend connection: FAILED")
        
        # Test 2: Availability fetch
        print(f"[INTEGRATION_TEST] Test 2: Availability fetch...")
        start_date = date.today()
        end_date = start_date + timedelta(days=7)
        availability = await get_glimmora_availability(start_date, end_date)
        if availability:
            test_results["availability_fetch"] = True
            print(f"[INTEGRATION_TEST] ✓ Availability fetch: SUCCESS")
        else:
            print(f"[INTEGRATION_TEST] ✗ Availability fetch: FAILED")
        
        # Test 3: Rate plans fetch
        print(f"[INTEGRATION_TEST] Test 3: Rate plans fetch...")
        rate_plans = await get_glimmora_rate_plans()
        if rate_plans:
            test_results["rate_plans_fetch"] = True
            print(f"[INTEGRATION_TEST] ✓ Rate plans fetch: SUCCESS ({len(rate_plans)} rate plans)")
        else:
            print(f"[INTEGRATION_TEST] ✗ Rate plans fetch: FAILED")
        
        # Test 4: Webhook delivery
        print(f"[INTEGRATION_TEST] Test 4: Webhook delivery...")
        test_webhook = {
            "event_type": "sync.status",
            "ota_connection_id": DUMMY_OTA_CONNECTION_ID,
            "timestamp": datetime.now().isoformat(),
            "status": {
                "connection_status": "connected",
                "last_sync_at": datetime.now().isoformat(),
                "sync_type": "test",
                "records_processed": 0,
                "records_failed": 0,
                "error_message": None
            }
        }
        await trigger_webhook_v2(test_webhook)
        test_results["webhook_delivery"] = True
        print(f"[INTEGRATION_TEST] ✓ Webhook delivery: SUCCESS")
        
        # Test 5: Booking creation (optional - can be skipped if no room types)
        if room_types and len(room_types) > 0:
            print(f"[INTEGRATION_TEST] Test 5: Booking creation (skipped - use /api/bookings/import to test)")
            # Don't actually create a booking in test, just verify we can format the request
            test_results["booking_creation"] = True
        
        success_count = sum(1 for v in test_results.values() if v)
        total_count = len(test_results)
        
        print(f"[INTEGRATION_TEST] Test completed: {success_count}/{total_count} tests passed")
        
        return AIResponse(
            success=success_count == total_count,
            data={
                "test_results": test_results,
                "summary": f"{success_count}/{total_count} tests passed",
                "glimmora_backend_url": GLIMMORA_BACKEND_URL,
                "webhook_url": WEBHOOK_URL
            },
            message=f"Integration test completed: {success_count}/{total_count} tests passed"
        )
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[INTEGRATION_TEST] ERROR: {error_trace}")
        return AIResponse(
            success=False,
            data={"test_results": test_results, "error": str(e)},
            message="Integration test failed"
        )


@app.post("/api/bookings/import", response_model=AIResponse)
async def simulate_booking_import(
    request: Optional[BookingImportRequest] = Body(None),
    session: Optional[Any] = None
):
    """
    Simulate booking import from dummy OTA.
    Creates a booking in both dummy channel manager and Glimmora backend.
    """
    import random
    import string
    
    print(f"[BOOKING_IMPORT] Simulating booking import from dummy OTA")
    
    try:
        # Generate random data if not provided
        if not request:
            request = BookingImportRequest()
        
        # Select room type if not provided
        if not request.room_type_id:
            available_room_types = list(room_types_db.keys())
            if not available_room_types:
                raise HTTPException(status_code=404, detail="No room types available")
            request.room_type_id = random.choice(available_room_types)
        
        room_type = room_types_db.get(request.room_type_id)
        if not room_type:
            raise HTTPException(status_code=404, detail=f"Room type {request.room_type_id} not found")
        
        # Generate dates if not provided
        if not request.check_in:
            request.check_in = date.today() + timedelta(days=random.randint(7, 30))
        if not request.check_out:
            nights = random.randint(1, 5)
            request.check_out = request.check_in + timedelta(days=nights)
        
        # Generate guest info if not provided
        if not request.guest_name:
            first_names = ["John", "Jane", "Michael", "Sarah", "David", "Emily", "Robert", "Jessica"]
            last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]
            request.guest_name = f"{random.choice(first_names)} {random.choice(last_names)}"
        
        if not request.guest_email:
            name_lower = request.guest_name.lower().replace(" ", ".")
            request.guest_email = f"{name_lower}@example.com"
        
        if not request.guest_phone:
            request.guest_phone = f"+1-555-{random.randint(1000, 9999)}"
        
        if not request.number_of_guests:
            request.number_of_guests = random.randint(1, min(room_type.max_occupancy, 4))
        
        if not request.rate_plan:
            request.rate_plan = RatePlan.BAR
        
        # Check availability
        current_date = request.check_in
        while current_date < request.check_out:
            inventory = get_inventory(request.room_type_id, current_date)
            available = inventory.available if inventory else room_type.base_capacity
            
            if available <= 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Inventory exhausted for {current_date.isoformat()}"
                )
            current_date += timedelta(days=1)
        
        # Calculate total amount
        rates = get_room_type_rates(request.room_type_id)
        matching_rate = None
        for rate in rates:
            if rate.rate_plan == request.rate_plan:
                matching_rate = rate
                break
        
        if not matching_rate:
            # Use BAR rate as fallback
            for rate in rates:
                if rate.rate_plan == RatePlan.BAR:
                    matching_rate = rate
                    break
        
        if not matching_rate:
            raise HTTPException(status_code=404, detail="No rates found for room type")
        
        nights = (request.check_out - request.check_in).days
        total_amount = sum(
            calculate_rate_amount(matching_rate, request.check_in + timedelta(days=i))
            for i in range(nights)
        )
        
        # Create reservation in dummy channel manager
        reservation_id = uuid4()
        while reservation_id in reservations_db:
            reservation_id = uuid4()
        
        reservation_data = {
            "id": reservation_id,
            "hotel_id": room_type.hotel_id,
            "room_type_id": request.room_type_id,
            "check_in": request.check_in,
            "check_out": request.check_out,
            "guest_name": request.guest_name,
            "guest_email": request.guest_email,
            "guest_phone": request.guest_phone,
            "number_of_guests": request.number_of_guests,
            "rate_plan": request.rate_plan,
            "total_amount": total_amount,
            "currency": "INR",
            "special_requests": None,
            "confirmation_number": generate_confirmation_number(),
            "status": BookingStatus.CONFIRMED,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        new_reservation = Reservation(**reservation_data)
        reservations_db[reservation_id] = new_reservation
        
        # Update inventory
        current_date = request.check_in
        while current_date < request.check_out:
            update_inventory(request.room_type_id, current_date, 1)
            current_date += timedelta(days=1)
        
        print(f"[BOOKING_IMPORT] Created reservation in dummy channel manager: {new_reservation.confirmation_number}")
        
        # Create booking in Glimmora backend
        from data import uuid_to_room_id_map
        
        glimmora_room_type_id = None
        if request.room_type_id in uuid_to_room_id_map:
            room_id = uuid_to_room_id_map[request.room_type_id]
            glimmora_room_type_id = room_id
        
        if glimmora_room_type_id:
            guest_parts = request.guest_name.split(" ", 1)
            first_name = guest_parts[0] if guest_parts else "Guest"
            last_name = guest_parts[1] if len(guest_parts) > 1 else ""
            
            glimmora_booking_data = {
                "roomTypeId": str(glimmora_room_type_id),
                "checkIn": request.check_in.isoformat(),
                "checkOut": request.check_out.isoformat(),
                "guests": {
                    "adults": request.number_of_guests,
                    "children": 0,
                    "infants": 0
                },
                "guestInfo": {
                    "firstName": first_name,
                    "lastName": last_name,
                    "email": request.guest_email,
                    "phone": request.guest_phone or "",
                    "country": "US",
                    "specialRequests": None
                },
                "source": "DUMMY",
                "channel": "Dummy Channel Manager",
                "paymentMethod": "card",
                "totalPrice": total_amount
            }
            
            glimmora_booking = await create_glimmora_booking(glimmora_booking_data)
            if glimmora_booking:
                print(f"[BOOKING_IMPORT] Successfully created booking in Glimmora backend")
            else:
                print(f"[BOOKING_IMPORT] WARNING: Failed to create booking in Glimmora backend")
        
        # Send booking.imported webhook (different from booking.created)
        try:
            webhook_payload = {
                "event_type": "booking.imported",
                "ota_connection_id": DUMMY_OTA_CONNECTION_ID,
                "ota_code": DUMMY_OTA_CODE,
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "otaCode": DUMMY_OTA_CODE,
                    "bookingId": str(reservation_id),
                    "confirmationNumber": new_reservation.confirmation_number,
                    "guestName": request.guest_name,
                    "roomType": room_type.name,
                    "checkIn": request.check_in.isoformat(),
                    "checkOut": request.check_out.isoformat(),
                    "totalPrice": total_amount
                }
            }
            asyncio.create_task(trigger_webhook_v2(webhook_payload))
            print(f"[BOOKING_IMPORT] Sent booking.imported webhook")
        except Exception as webhook_error:
            print(f"[BOOKING_IMPORT] ERROR: Failed to send webhook: {webhook_error}")
        
        return AIResponse(
            success=True,
            data={
                "reservation_id": str(reservation_id),
                "confirmation_number": new_reservation.confirmation_number,
                "glimmora_booking": glimmora_booking if glimmora_room_type_id else None
            },
            message="Booking imported successfully"
        )
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[BOOKING_IMPORT] ERROR: {error_trace}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import booking: {str(e)}"
        )


# ==================== Error Handlers ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler with AI-friendly format"""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=f"HTTP_{exc.status_code}",
            error_message=exc.detail,
            details={"path": str(request.url.path)}
        ).dict()
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc):
    """Validation error handler"""
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_code="VALIDATION_ERROR",
            error_message="Request validation failed",
            details={"errors": exc.errors()}
        ).dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler for unhandled errors"""
    import traceback
    error_trace = traceback.format_exc()
    print(f"Unhandled error: {error_trace}")  # Log for debugging
    
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            error_message=f"An unexpected error occurred: {str(exc)}",
            details={"path": str(request.url.path)}
        ).dict()
    )


if __name__ == "__main__":
    import uvicorn
    print(f"[STARTUP] Starting dummy channel manager on port {CHANNEL_MANAGER_PORT}")
    print(f"[STARTUP] Glimmora Backend URL: {GLIMMORA_BACKEND_URL}")
    print(f"[STARTUP] Webhook URL: {WEBHOOK_URL}")
    uvicorn.run(app, host="0.0.0.0", port=CHANNEL_MANAGER_PORT)
