"""
Channel Manager Webhook Endpoints
Receives webhooks from dummy channel manager and updates PMS database
Also publishes SSE events for real-time frontend updates
"""
import asyncio
import json
import logging
from datetime import datetime, date as date_type, timedelta
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Body
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_tenant_session
from app.models.channel_manager import (
    OTAConnection, OTARoomMapping, OTARateMapping, 
    AvailabilityGrid, ChannelRestriction, SyncLog
)
from app.models.reservations import Booking, Guest, ReservationHistory
from app.models.inventory import DailyAvailability, DailyRate, RoomType
from app.models.user import User
from app.api.v1.auth import get_current_user, get_current_user_sse
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)

# SSE event broadcaster.
# Single-worker: in-memory list. Multi-worker: use Redis pub/sub (see broadcast_sse_event).
# IMPORTANT: If running uvicorn with --workers 2+, ensure Redis is available so all workers
# receive the same events; otherwise SSE may connect to Worker A while webhooks hit Worker B.
sse_connections: List[Any] = []

SSE_REDIS_CHANNEL = "sse:events"
_sse_redis_subscriber_task: Optional[Any] = None


# ============== WEBHOOK PAYLOAD MODELS ==============

class GuestInfo(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    country: Optional[str] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[date_type] = None
    passport_number: Optional[str] = None


class BookingPricing(BaseModel):
    base_price: float
    taxes: float = 0.0
    service_fee: float = 0.0
    total_price: float
    currency: str = "INR"
    commission_rate: Optional[float] = None
    commission_amount: Optional[float] = None
    net_revenue: Optional[float] = None


class BookingPayment(BaseModel):
    payment_status: str = "pending"  # pending, paid, partial, failed, refunded
    payment_method: str = "card"  # card, pay_at_hotel
    deposit_amount: float = 0.0
    balance_due: float = 0.0


class BookingWebhookPayload(BaseModel):
    guest: GuestInfo
    room_type_code: str
    rate_plan_code: str
    arrival_date: date_type
    departure_date: date_type
    adults: int = 1
    children: int = 0
    infants: int = 0
    special_requests: Optional[str] = None
    pricing: BookingPricing
    payment: BookingPayment


class BookingCreatedWebhook(BaseModel):
    event_type: str = "booking.created"
    ota_connection_id: int
    ota_code: str
    external_booking_id: str
    timestamp: str
    booking: BookingWebhookPayload


class BookingModifiedWebhook(BaseModel):
    event_type: str = "booking.modified"
    ota_connection_id: int
    external_booking_id: str
    timestamp: str
    changes: Optional[Dict[str, Any]] = None
    booking: BookingWebhookPayload


class BookingCancelledWebhook(BaseModel):
    event_type: str = "booking.cancelled"
    ota_connection_id: int
    external_booking_id: str
    timestamp: str
    cancellation_reason: Optional[str] = None
    refund_status: Optional[str] = None


class AvailabilityItem(BaseModel):
    room_type_code: str
    date: date_type
    available: int
    sold: int
    blocked: int
    total: int


class AvailabilityUpdatedWebhook(BaseModel):
    event_type: str = "availability.updated"
    ota_connection_id: int
    timestamp: str
    availability: List[AvailabilityItem]


class RateItem(BaseModel):
    room_type_code: str
    rate_plan_code: str
    date: date_type
    rate: float
    currency: str = "INR"


class RatesUpdatedWebhook(BaseModel):
    event_type: str = "rates.updated"
    ota_connection_id: int
    timestamp: str
    rates: List[RateItem]


class RestrictionItem(BaseModel):
    room_type_code: str
    date: date_type
    restriction_type: str  # stop_sell, CTA, CTD, min_stay, max_stay
    restriction_value: int


class RestrictionsUpdatedWebhook(BaseModel):
    event_type: str = "restrictions.updated"
    ota_connection_id: int
    timestamp: str
    restrictions: List[RestrictionItem]


class SyncStatusWebhook(BaseModel):
    event_type: str = "sync.status"
    ota_connection_id: int
    timestamp: str
    status: Dict[str, Any]


# ============== HELPER FUNCTIONS ==============

async def get_or_create_guest(session: AsyncSession, guest_info: GuestInfo) -> Guest:
    """Get existing guest or create new one"""
    print(f"[get_or_create_guest] Looking up guest by email: {guest_info.email.lower()}")
    # Try to find by email
    result = await session.exec(
        select(Guest).where(Guest.email == guest_info.email.lower())
    )
    guest = result.first()
    
    if guest:
        print(f"[get_or_create_guest] OK: Found existing guest: ID={guest.id}")
        # Update guest info
        guest.first_name = guest_info.first_name
        guest.last_name = guest_info.last_name
        guest.phone = guest_info.phone
        guest.country = guest_info.country
        guest.nationality = guest_info.nationality
        if guest_info.date_of_birth:
            guest.date_of_birth = guest_info.date_of_birth
        if guest_info.passport_number:
            guest.passport_number = guest_info.passport_number
        guest.updated_at = datetime.utcnow()
        print(f"[get_or_create_guest] OK: Guest info updated")
    else:
        print(f"[get_or_create_guest] Creating new guest: {guest_info.first_name} {guest_info.last_name}")
        # Create new guest
        guest = Guest(
            first_name=guest_info.first_name,
            last_name=guest_info.last_name,
            email=guest_info.email.lower(),
            phone=guest_info.phone,
            country=guest_info.country,
            nationality=guest_info.nationality,
            date_of_birth=guest_info.date_of_birth,
            passport_number=guest_info.passport_number
        )
        session.add(guest)
        print(f"[get_or_create_guest] OK: New guest added to session")
    
    await session.flush()
    print(f"[get_or_create_guest] OK: Guest flushed: ID={guest.id}")
    return guest


async def get_room_type_id_from_code(session: AsyncSession, ota_connection_id: int, room_type_code: str) -> Optional[int]:
    """Get PMS room_type_id from OTA room_type_code"""
    print(f"[get_room_type_id_from_code] Looking up room mapping: ota_connection_id={ota_connection_id}, room_type_code={room_type_code}")
    result = await session.execute(
        select(OTARoomMapping).where(
            OTARoomMapping.ota_connection_id == ota_connection_id,
            OTARoomMapping.ota_room_code == room_type_code,
            OTARoomMapping.is_active == True
        )
    )
    mapping = result.scalar_one_or_none()
    if mapping:
        print(f"[get_room_type_id_from_code] OK: Found mapping: {room_type_code} -> room_type_id={mapping.room_type_id}")
    else:
        print(f"[get_room_type_id_from_code] ERROR: No mapping found for {room_type_code}")
    return mapping.room_type_id if mapping else None


async def get_rate_plan_id_from_code(session: AsyncSession, ota_connection_id: int, rate_plan_code: str) -> Optional[int]:
    """Get PMS rate_plan_id from OTA rate_plan_code"""
    result = await session.exec(
        select(OTARateMapping).where(
            OTARateMapping.ota_connection_id == ota_connection_id,
            OTARateMapping.ota_rate_code == rate_plan_code,
            OTARateMapping.is_active == True
        )
    )
    mapping = result.first()
    return mapping.rate_plan_id if mapping else None


async def find_booking_by_external_id(session: AsyncSession, external_booking_id: str) -> Optional[Booking]:
    """Find booking by external booking ID (stored in internal_notes as JSON)"""
    return await find_booking_by_external_id_and_ota(session, external_booking_id, None)


def _parse_external_id_from_notes(internal_notes: Optional[str]) -> Optional[Tuple[str, Optional[int]]]:
    """Parse internal_notes JSON; return (external_booking_id, ota_connection_id) or None."""
    if not internal_notes:
        return None
    try:
        data = json.loads(internal_notes) if isinstance(internal_notes, str) else internal_notes
        if not isinstance(data, dict):
            return None
        ext_id = data.get("external_booking_id")
        if ext_id is None:
            return None
        ota_id = data.get("ota_connection_id")
        return (str(ext_id), int(ota_id) if ota_id is not None else None)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


async def find_booking_by_external_id_and_ota(
    session: AsyncSession, external_booking_id: str, ota_connection_id: Optional[int]
) -> Optional[Booking]:
    """Find booking by external_booking_id and optionally ota_connection_id (stored in internal_notes as JSON)."""
    result = await session.exec(select(Booking))
    all_bookings = result.all()
    for booking in all_bookings:
        parsed = _parse_external_id_from_notes(booking.internal_notes)
        if not parsed:
            continue
        ext_id, ota_id = parsed
        if ext_id != str(external_booking_id):
            continue
        if ota_connection_id is not None and ota_id != ota_connection_id:
            continue
        return booking
    return None


# In-memory lock per (external_booking_id, ota_connection_id) to prevent concurrent duplicate creation
_booking_created_locks: Dict[Tuple[str, int], asyncio.Lock] = {}
_lock_cleanup_max = 500


def _lock_key(external_booking_id: str, ota_connection_id: int) -> Tuple[str, int]:
    return (str(external_booking_id), int(ota_connection_id))


def _get_booking_created_lock(external_booking_id: str, ota_connection_id: int) -> asyncio.Lock:
    key = _lock_key(external_booking_id, ota_connection_id)
    if key not in _booking_created_locks:
        if len(_booking_created_locks) >= _lock_cleanup_max:
            # Drop oldest keys (arbitrary: remove first 100)
            to_remove = list(_booking_created_locks.keys())[:100]
            for k in to_remove:
                _booking_created_locks.pop(k, None)
        _booking_created_locks[key] = asyncio.Lock()
    return _booking_created_locks[key]


# ============== WEBHOOK ENDPOINTS ==============

@router.get("/channel-manager/health")
async def webhook_health_check():
    """Health check endpoint for webhook service"""
    return {"status": "ok", "service": "webhook-receiver", "endpoint": "/api/v1/webhooks/channel-manager"}


@router.post("/channel-manager")
async def receive_webhook(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Main webhook receiver endpoint - routes to appropriate handler based on event_type
    """
    event_type = payload.get("event_type")
    ota_connection_id = payload.get("ota_connection_id")
    
    print(f"\n{'='*80}")
    print(f"[WEBHOOK RECEIVER] Received webhook")
    print(f"[WEBHOOK RECEIVER]    Event Type: {event_type}")
    print(f"[WEBHOOK RECEIVER]    OTA Connection ID: {ota_connection_id}")
    print(f"[WEBHOOK RECEIVER]    Payload keys: {list(payload.keys())}")
    print(f"{'='*80}")
    
    if not event_type:
        logger.error("[WEBHOOK RECEIVER] ERROR: Missing event_type in payload")
        raise HTTPException(status_code=400, detail="event_type is required")
    
    try:
        if event_type == "booking.created":
            logger.info(f"[WEBHOOK RECEIVER] -> Routing to handle_booking_created")
            result = await handle_booking_created(payload, session, background_tasks)
            print(f"[WEBHOOK RECEIVER] SUCCESS: booking.created processed successfully")
            return result
        elif event_type == "booking.modified":
            logger.info(f"[WEBHOOK RECEIVER] -> Routing to handle_booking_modified")
            result = await handle_booking_modified(payload, session, background_tasks)
            print(f"[WEBHOOK RECEIVER] SUCCESS: booking.modified processed successfully")
            return result
        elif event_type == "booking.cancelled":
            logger.info(f"[WEBHOOK RECEIVER] -> Routing to handle_booking_cancelled")
            result = await handle_booking_cancelled(payload, session, background_tasks)
            print(f"[WEBHOOK RECEIVER] SUCCESS: booking.cancelled processed successfully")
            return result
        elif event_type == "availability.updated":
            logger.info(f"[WEBHOOK RECEIVER] -> Routing to handle_availability_updated")
            result = await handle_availability_updated(payload, session, background_tasks)
            print(f"[WEBHOOK RECEIVER] SUCCESS: availability.updated processed successfully")
            return result
        elif event_type == "rates.updated":
            logger.info(f"[WEBHOOK RECEIVER] -> Routing to handle_rates_updated")
            result = await handle_rates_updated(payload, session, background_tasks)
            print(f"[WEBHOOK RECEIVER] SUCCESS: rates.updated processed successfully")
            return result
        elif event_type == "restrictions.updated":
            logger.info(f"[WEBHOOK RECEIVER] -> Routing to handle_restrictions_updated")
            result = await handle_restrictions_updated(payload, session, background_tasks)
            print(f"[WEBHOOK RECEIVER] SUCCESS: restrictions.updated processed successfully")
            return result
        elif event_type == "sync.status":
            logger.info(f"[WEBHOOK RECEIVER] -> Routing to handle_sync_status")
            result = await handle_sync_status(payload, session, background_tasks)
            print(f"[WEBHOOK RECEIVER] SUCCESS: sync.status processed successfully")
            return result
        else:
            logger.error(f"[WEBHOOK RECEIVER] ERROR: Unknown event_type: {event_type}")
            raise HTTPException(status_code=400, detail=f"Unknown event_type: {event_type}")
    except HTTPException as e:
        logger.error(f"[WEBHOOK RECEIVER] ERROR: HTTP Error processing webhook {event_type}: {e.detail}")
        print(f"[WEBHOOK RECEIVER] ERROR: HTTP Error: {e.status_code} - {e.detail}")
        raise
    except Exception as e:
        logger.error(f"[WEBHOOK RECEIVER] ERROR: Error processing webhook {event_type}: {e}", exc_info=True)
        print(f"[WEBHOOK RECEIVER] ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        print(f"[WEBHOOK RECEIVER]    Traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


async def handle_booking_created(payload: Dict[str, Any], session: AsyncSession, background_tasks: BackgroundTasks):
    """Handle booking.created webhook"""
    print(f"[handle_booking_created] Processing booking.created webhook...")
    
    try:
        webhook_data = BookingCreatedWebhook(**payload)
        print(f"[handle_booking_created] OK: Payload validated")
    except Exception as e:
        print(f"[handle_booking_created] ERROR: Invalid payload: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    # Verify OTA connection exists
    print(f"[handle_booking_created] Looking up OTA connection ID: {webhook_data.ota_connection_id}")
    ota_connection = await session.get(OTAConnection, webhook_data.ota_connection_id)
    if not ota_connection or not ota_connection.is_active:
        print(f"[handle_booking_created] ERROR: OTA connection not found or inactive")
        raise HTTPException(status_code=404, detail="OTA connection not found or inactive")
    print(f"[handle_booking_created] OK: OTA connection found: {ota_connection.ota_name} (ID: {ota_connection.id})")
    
    # Idempotency: prevent duplicate bookings for same external_booking_id + ota_connection_id
    # Use a per-key lock so concurrent webhooks for the same booking don't both create
    lock = _get_booking_created_lock(webhook_data.external_booking_id, webhook_data.ota_connection_id)
    async with lock:
        existing_booking = await find_booking_by_external_id_and_ota(
            session, webhook_data.external_booking_id, webhook_data.ota_connection_id
        )
        if existing_booking:
            print(f"[handle_booking_created] OK: Booking already exists for external_booking_id={webhook_data.external_booking_id}, ID={existing_booking.id}")
            return {
                "success": True,
                "message": "Booking already processed",
                "booking_id": existing_booking.id,
                "booking_number": existing_booking.booking_number
            }

        # Map room type and rate plan
        print(f"[handle_booking_created] Mapping room_type_code: {webhook_data.booking.room_type_code}")
        room_type_id = await get_room_type_id_from_code(
            session, webhook_data.ota_connection_id, webhook_data.booking.room_type_code
        )

        # If mapping not found, try to auto-create it by extracting room_id from code (e.g., "ROOM_1" -> room_id 1)
        if not room_type_id:
            print(f"[handle_booking_created] WARNING: Room type mapping not found, attempting auto-creation...")
            import re
            room_code_match = re.match(r'ROOM[_\s]*(\d+)', webhook_data.booking.room_type_code.upper())

            target_room_type = None

            if room_code_match:
                extracted_room_id = int(room_code_match.group(1))
                print(f"[handle_booking_created] Extracted room_id={extracted_room_id} from code: {webhook_data.booking.room_type_code}")

                # Try to find a room type with this ID
                try:
                    target_room_type = await session.get(RoomType, extracted_room_id)
                    if target_room_type:
                        print(f"[handle_booking_created] Found room type by ID: {target_room_type.name} (ID: {target_room_type.id})")
                    else:
                        print(f"[handle_booking_created] Room type with ID {extracted_room_id} not found, trying alternative methods...")
                except Exception as e:
                    print(f"[handle_booking_created] Error looking up room type by ID: {str(e)}")

            # If not found by ID, try to get the first available room type as fallback
            if not target_room_type:
                print(f"[handle_booking_created] Attempting to find any available room type...")
                try:
                    # Get first room type (try with is_active filter first, then without)
                    try:
                        room_types_stmt = select(RoomType).where(RoomType.is_active == True).limit(1)
                        room_types_result = await session.execute(room_types_stmt)
                        target_room_type = room_types_result.scalar_one_or_none()
                    except Exception:
                        # If is_active doesn't exist or query fails, try without filter
                        room_types_stmt = select(RoomType).limit(1)
                        room_types_result = await session.execute(room_types_stmt)
                        target_room_type = room_types_result.scalar_one_or_none()

                    if target_room_type:
                        print(f"[handle_booking_created] Using fallback room type: {target_room_type.name} (ID: {target_room_type.id})")
                    else:
                        print(f"[handle_booking_created] ERROR: No room types found in Glimmora database")
                        # Try to get count of room types for debugging
                        count_stmt = select(func.count(RoomType.id))
                        count_result = await session.execute(count_stmt)
                        total_count = count_result.scalar() or 0
                        print(f"[handle_booking_created] Total room types in database: {total_count}")
                except Exception as e:
                    import traceback
                    print(f"[handle_booking_created] Error querying room types: {str(e)}")
                    print(f"[handle_booking_created] Traceback: {traceback.format_exc()}")

            # Auto-create or update the mapping if we found a room type
            if target_room_type:
                try:
                    # Check if mapping already exists by (ota_connection_id, room_type_id)
                    existing_stmt = select(OTARoomMapping).where(
                        and_(
                            OTARoomMapping.ota_connection_id == webhook_data.ota_connection_id,
                            OTARoomMapping.room_type_id == target_room_type.id
                        )
                    )
                    existing_result = await session.execute(existing_stmt)
                    existing_mapping = existing_result.scalar_one_or_none()

                    if existing_mapping:
                        print(f"[handle_booking_created] Mapping exists for room_type_id={target_room_type.id}, updating ota_room_code from '{existing_mapping.ota_room_code}' to '{webhook_data.booking.room_type_code}'")
                        existing_mapping.ota_room_code = webhook_data.booking.room_type_code
                        existing_mapping.ota_room_name = target_room_type.name
                        existing_mapping.is_active = True
                        existing_mapping.sync_status = "synced"
                        existing_mapping.last_synced_at = datetime.utcnow()
                        await session.flush()
                        room_type_id = existing_mapping.room_type_id
                        print(f"[handle_booking_created] OK: Updated room mapping: {webhook_data.booking.room_type_code} -> room_type_id={room_type_id}")
                    else:
                        existing_by_code_stmt = select(OTARoomMapping).where(
                            and_(
                                OTARoomMapping.ota_connection_id == webhook_data.ota_connection_id,
                                OTARoomMapping.ota_room_code == webhook_data.booking.room_type_code
                            )
                        )
                        existing_by_code_result = await session.execute(existing_by_code_stmt)
                        existing_by_code = existing_by_code_result.scalar_one_or_none()

                        if existing_by_code:
                            print(f"[handle_booking_created] Mapping exists for ota_room_code='{webhook_data.booking.room_type_code}' but different room_type_id ({existing_by_code.room_type_id} vs {target_room_type.id}), using existing")
                            room_type_id = existing_by_code.room_type_id
                        else:
                            print(f"[handle_booking_created] Creating new room mapping...")
                            new_mapping = OTARoomMapping(
                                property_id=ota_connection.property_id,
                                ota_connection_id=webhook_data.ota_connection_id,
                                room_type_id=target_room_type.id,
                                ota_room_code=webhook_data.booking.room_type_code,
                                ota_room_name=target_room_type.name,
                                is_active=True,
                                sync_status="synced",
                                last_synced_at=datetime.utcnow()
                            )
                            session.add(new_mapping)
                            await session.flush()
                            await session.refresh(new_mapping)
                            room_type_id = target_room_type.id
                            print(f"[handle_booking_created] OK: Auto-created room mapping: {webhook_data.booking.room_type_code} -> room_type_id={room_type_id} (mapping_id={new_mapping.id})")
                except Exception as mapping_error:
                    import traceback
                    print(f"[handle_booking_created] ERROR: Failed to auto-create/update mapping: {str(mapping_error)}")
                    print(f"[handle_booking_created] Traceback: {traceback.format_exc()}")

        if not room_type_id:
            print(f"[handle_booking_created] ERROR: Room type mapping not found for: {webhook_data.booking.room_type_code}")
            raise HTTPException(
                status_code=404,
                detail=f"Room type mapping not found for code: {webhook_data.booking.room_type_code}. Please create a room mapping in Channel Manager → Room Mapping."
            )

        print(f"[handle_booking_created] OK: Room type mapped: {webhook_data.booking.room_type_code} -> room_type_id={room_type_id}")

        print(f"[handle_booking_created] Mapping rate_plan_code: {webhook_data.booking.rate_plan_code}")
        rate_plan_id = await get_rate_plan_id_from_code(
            session, webhook_data.ota_connection_id, webhook_data.booking.rate_plan_code
        )
        if rate_plan_id:
            print(f"[handle_booking_created] OK: Rate plan mapped: {webhook_data.booking.rate_plan_code} -> rate_plan_id={rate_plan_id}")
        else:
            print(f"[handle_booking_created] WARNING: Rate plan mapping not found (will use None)")

        # Get or create guest
        print(f"[handle_booking_created] Processing guest: {webhook_data.booking.guest.email}")
        guest = await get_or_create_guest(session, webhook_data.booking.guest)
        print(f"[handle_booking_created] OK: Guest ready: ID={guest.id}, Email={guest.email}")

        # Calculate nights
        nights = (webhook_data.booking.departure_date - webhook_data.booking.arrival_date).days
        print(f"[handle_booking_created] Dates: {webhook_data.booking.arrival_date} to {webhook_data.booking.departure_date} ({nights} nights)")

        # Generate booking number
        import secrets
        booking_number = f"BK-{datetime.utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
        confirmation_code = secrets.token_hex(4).upper()
        print(f"[handle_booking_created] Generated booking_number: {booking_number}, confirmation_code: {confirmation_code}")

        # Store external booking ID in internal_notes as JSON
        internal_notes_data = {
            "external_booking_id": webhook_data.external_booking_id,
            "ota_connection_id": webhook_data.ota_connection_id,
            "ota_code": webhook_data.ota_code,
            "source": "channel_manager_webhook"
        }

        # Align with channel_manager.get_ota_booking_source(): DUMMY → CRS for stats/filtering
        booking_source_map = {
            "BOOKING": "Booking.com",
            "EXPEDIA": "Expedia",
            "AGODA": "Agoda",
            "AIRBNB": "airbnb",
            "MMT": "MakeMyTrip",
            "TRIP": "Trip.com",
            "GOOGLE": "Google Hotel Ads",
            "DUMMY": "CRS",
            "CRS": "CRS",
        }
        booking_source = booking_source_map.get(webhook_data.ota_code.upper(), webhook_data.ota_code.lower())
        # For DUMMY/CRS, always use "Dummy Channel Manager" as channel (ota_name may be misconfigured)
        channel_name = "Dummy Channel Manager" if webhook_data.ota_code.upper() in ("DUMMY", "CRS") else ota_connection.ota_name

        # Create booking
        booking = Booking(
            booking_number=booking_number,
            confirmation_code=confirmation_code,
            guest_id=guest.id,
            room_type_id=room_type_id,
            arrival_date=webhook_data.booking.arrival_date,
            departure_date=webhook_data.booking.departure_date,
            adults=webhook_data.booking.adults,
            children=webhook_data.booking.children,
            infants=webhook_data.booking.infants,
            nights=nights,
            status="confirmed",
            payment_status=webhook_data.booking.payment.payment_status,
            payment_method=webhook_data.booking.payment.payment_method,
            booking_source=booking_source,
            channel=channel_name,
            base_price=webhook_data.booking.pricing.base_price,
            taxes=webhook_data.booking.pricing.taxes,
            service_fee=webhook_data.booking.pricing.service_fee,
            total_price=webhook_data.booking.pricing.total_price,
            deposit_amount=webhook_data.booking.payment.deposit_amount,
            balance_due=webhook_data.booking.payment.balance_due or webhook_data.booking.pricing.total_price,
            special_requests=webhook_data.booking.special_requests,
            internal_notes=json.dumps(internal_notes_data),
            rate_plan_id=rate_plan_id,
            commission_rate=webhook_data.booking.pricing.commission_rate,
            commission_amount=webhook_data.booking.pricing.commission_amount,
            net_revenue=webhook_data.booking.pricing.net_revenue,
            number_of_guests=webhook_data.booking.adults + webhook_data.booking.children + webhook_data.booking.infants,
            modification_count=0
        )
        session.add(booking)
        print(f"[handle_booking_created] Booking added to session (not yet committed)")

        # Update availability grid (critical - must be done synchronously to prevent overbooking)
        print(f"[handle_booking_created] Updating availability grid for room_type_id={room_type_id}")
        await update_availability_grid(session, room_type_id, webhook_data.booking.arrival_date, webhook_data.booking.departure_date, -1)
        print(f"[handle_booking_created] OK: Availability grid updated")

        print(f"[handle_booking_created] Committing to database...")
        await session.commit()
        await session.refresh(booking)
        print(f"[handle_booking_created] SUCCESS: Database commit successful! Booking ID: {booking.id}")
    
    # Prepare response immediately (return as fast as possible)
    response_data = {
        "success": True,
        "message": "Booking created successfully",
        "booking_id": booking.id,
        "booking_number": booking.booking_number
    }
    
    # Schedule background tasks (non-blocking - done after response is sent)
    async def create_sync_log_background():
        """Create sync log in background"""
        from app.db.session import async_session_maker
        async with async_session_maker() as db_session:
            try:
                sync_log = SyncLog(
                    property_id=ota_connection.property_id,
                    ota_connection_id=webhook_data.ota_connection_id,
                    sync_type="bookings",
                    sync_direction="pull",
                    status="success",
                    records_processed=1,
                    records_failed=0,
                    completed_at=datetime.utcnow(),
                    duration_seconds=0.1
                )
                db_session.add(sync_log)
                await db_session.commit()
                print(f"[handle_booking_created] Sync log created in background")
            except Exception as e:
                print(f"[handle_booking_created] ERROR creating sync log in background: {e}")
    
    # Broadcast SSE event in background (non-blocking). Frontend listens and refetches
    # bookings (with cache cleared) so the new booking appears. Debug: look for logs
    # "[SSE] broadcast_sse_event CALLED: event_type=booking.created" and
    # "Successfully sent booking.created event to X connection(s)" (or "No active connections").
    print(f"[handle_booking_created] Scheduling SSE broadcast for booking.created event...")
    background_tasks.add_task(
        broadcast_sse_event,
        "booking.created",
        {
            "booking_id": booking.id,
            "booking_number": booking.booking_number,
            "confirmation_code": booking.confirmation_code,
            "guest_id": guest.id,
            "room_type_id": room_type_id,
            "arrival_date": booking.arrival_date.isoformat(),
            "departure_date": booking.departure_date.isoformat(),
            "status": booking.status,
            "channel": booking.channel
        }
    )
    background_tasks.add_task(create_sync_log_background)
    print(f"[handle_booking_created] Background tasks scheduled (SSE + sync log)")
    
    # Return response immediately (webhook processing continues in background)
    return response_data


async def handle_booking_modified(payload: Dict[str, Any], session: AsyncSession, background_tasks: BackgroundTasks):
    """Handle booking.modified webhook"""
    print(f"[handle_booking_modified] Processing booking.modified webhook...")
    
    try:
        webhook_data = BookingModifiedWebhook(**payload)
        print(f"[handle_booking_modified] OK: Payload validated")
    except Exception as e:
        print(f"[handle_booking_modified] ERROR: Invalid payload: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    # Find booking by external ID
    print(f"[handle_booking_modified] Looking up booking by external_booking_id: {webhook_data.external_booking_id}")
    booking = await find_booking_by_external_id(session, webhook_data.external_booking_id)
    if not booking:
        print(f"[handle_booking_modified] ERROR: Booking not found: {webhook_data.external_booking_id}")
        raise HTTPException(status_code=404, detail=f"Booking not found: {webhook_data.external_booking_id}")
    print(f"[handle_booking_modified] OK: Found booking: ID={booking.id}, booking_number={booking.booking_number}")
    
    # Store old values for history
    old_arrival = booking.arrival_date
    old_departure = booking.departure_date
    
    # Update booking fields
    booking.arrival_date = webhook_data.booking.arrival_date
    booking.departure_date = webhook_data.booking.departure_date
    booking.adults = webhook_data.booking.adults
    booking.children = webhook_data.booking.children
    booking.infants = webhook_data.booking.infants
    booking.base_price = webhook_data.booking.pricing.base_price
    booking.taxes = webhook_data.booking.pricing.taxes
    booking.service_fee = webhook_data.booking.pricing.service_fee
    booking.total_price = webhook_data.booking.pricing.total_price
    booking.special_requests = webhook_data.booking.special_requests
    booking.commission_rate = webhook_data.booking.pricing.commission_rate
    booking.commission_amount = webhook_data.booking.pricing.commission_amount
    booking.net_revenue = webhook_data.booking.pricing.net_revenue
    booking.number_of_guests = webhook_data.booking.adults + webhook_data.booking.children + webhook_data.booking.infants
    booking.modification_count = (booking.modification_count or 0) + 1
    booking.updated_at = datetime.utcnow()
    
    # Recalculate nights
    booking.nights = (booking.departure_date - booking.arrival_date).days
    
    # Update availability if dates changed
    if old_arrival != booking.arrival_date or old_departure != booking.departure_date:
        # Release old inventory
        await update_availability_grid(session, booking.room_type_id, old_arrival, old_departure, 1)
        # Reserve new inventory
        await update_availability_grid(session, booking.room_type_id, booking.arrival_date, booking.departure_date, -1)
    
    # Create history entry
    history = ReservationHistory(
        reservation_id=booking.id,
        action="modified",
        old_value=f"Dates: {old_arrival} to {old_departure}",
        new_value=f"Dates: {booking.arrival_date} to {booking.departure_date}",
        notes=f"Modified via channel manager webhook: {webhook_data.external_booking_id}"
    )
    session.add(history)
    
    await session.commit()
    await session.refresh(booking)
    
    # Broadcast SSE event
    background_tasks.add_task(
        broadcast_sse_event,
        "booking.modified",
        {
            "booking_id": booking.id,
            "booking_number": booking.booking_number,
            "changes": webhook_data.changes or {}
        }
    )
    
    return {
        "success": True,
        "message": "Booking modified successfully",
        "booking_id": booking.id
    }


async def handle_booking_cancelled(payload: Dict[str, Any], session: AsyncSession, background_tasks: BackgroundTasks):
    """Handle booking.cancelled webhook"""
    print(f"[handle_booking_cancelled] Processing booking.cancelled webhook...")
    
    try:
        webhook_data = BookingCancelledWebhook(**payload)
        print(f"[handle_booking_cancelled] OK: Payload validated")
    except Exception as e:
        print(f"[handle_booking_cancelled] ERROR: Invalid payload: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    # Find booking by external ID
    print(f"[handle_booking_cancelled] Looking up booking by external_booking_id: {webhook_data.external_booking_id}")
    booking = await find_booking_by_external_id(session, webhook_data.external_booking_id)
    if not booking:
        print(f"[handle_booking_cancelled] ERROR: Booking not found: {webhook_data.external_booking_id}")
        raise HTTPException(status_code=404, detail=f"Booking not found: {webhook_data.external_booking_id}")
    print(f"[handle_booking_cancelled] OK: Found booking: ID={booking.id}, booking_number={booking.booking_number}, current_status={booking.status}")
    
    if booking.status == "cancelled":
        print(f"[handle_booking_cancelled] WARNING: Booking already cancelled, skipping")
        return {"success": True, "message": "Booking already cancelled", "booking_id": booking.id}
    
    # Update booking
    booking.status = "cancelled"
    booking.cancellation_reason = webhook_data.cancellation_reason
    booking.cancelled_at = datetime.utcnow()
    if webhook_data.refund_status == "processed":
        booking.payment_status = "refunded"
    booking.updated_at = datetime.utcnow()
    
    # Release inventory
    await update_availability_grid(session, booking.room_type_id, booking.arrival_date, booking.departure_date, 1)
    
    # Create history entry
    history = ReservationHistory(
        reservation_id=booking.id,
        action="cancelled",
        notes=f"Cancelled via channel manager webhook. Reason: {webhook_data.cancellation_reason}"
    )
    session.add(history)
    
    await session.commit()
    
    # Broadcast SSE event
    background_tasks.add_task(
        broadcast_sse_event,
        "booking.cancelled",
        {
            "booking_id": booking.id,
            "booking_number": booking.booking_number,
            "reason": webhook_data.cancellation_reason
        }
    )
    
    return {
        "success": True,
        "message": "Booking cancelled successfully",
        "booking_id": booking.id
    }


async def handle_availability_updated(payload: Dict[str, Any], session: AsyncSession, background_tasks: BackgroundTasks):
    """Handle availability.updated webhook"""
    try:
        webhook_data = AvailabilityUpdatedWebhook(**payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    updated_count = 0
    
    for avail_item in webhook_data.availability:
        room_type_id = await get_room_type_id_from_code(
            session, webhook_data.ota_connection_id, avail_item.room_type_code
        )
        
        if room_type_id:
            # Update or create AvailabilityGrid entry
            result = await session.exec(
                select(AvailabilityGrid).where(
                    AvailabilityGrid.room_type_id == room_type_id,
                    AvailabilityGrid.grid_date == avail_item.date
                )
            )
            grid_entry = result.first()
            
            if grid_entry:
                grid_entry.total_inventory = avail_item.total
                grid_entry.sold = avail_item.sold
                grid_entry.blocked = avail_item.blocked
                grid_entry.available = avail_item.available
                grid_entry.updated_at = datetime.utcnow()
            else:
                ota_connection = await session.get(OTAConnection, webhook_data.ota_connection_id)
                grid_entry = AvailabilityGrid(
                    property_id=ota_connection.property_id if ota_connection else 1,
                    room_type_id=room_type_id,
                    grid_date=avail_item.date,
                    total_inventory=avail_item.total,
                    sold=avail_item.sold,
                    blocked=avail_item.blocked,
                    available=avail_item.available
                )
                session.add(grid_entry)
            
            updated_count += 1
    
    await session.commit()
    
    # Create sync log
    ota_connection = await session.get(OTAConnection, webhook_data.ota_connection_id)
    if ota_connection:
        sync_log = SyncLog(
            property_id=ota_connection.property_id,
            ota_connection_id=webhook_data.ota_connection_id,
            sync_type="availability",
            sync_direction="pull",
            status="success",
            records_processed=updated_count,
            records_failed=0,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            duration_seconds=0.0
        )
        session.add(sync_log)
        await session.commit()
    
    # Broadcast SSE event
    background_tasks.add_task(
        broadcast_sse_event,
        "availability.updated",
        {"updated_count": updated_count, "ota_connection_id": webhook_data.ota_connection_id}
    )
    
    return {
        "success": True,
        "message": f"Availability updated for {updated_count} room types",
        "updated_count": updated_count
    }


async def handle_rates_updated(payload: Dict[str, Any], session: AsyncSession, background_tasks: BackgroundTasks):
    """Handle rates.updated webhook"""
    try:
        webhook_data = RatesUpdatedWebhook(**payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    updated_count = 0
    
    for rate_item in webhook_data.rates:
        room_type_id = await get_room_type_id_from_code(
            session, webhook_data.ota_connection_id, rate_item.room_type_code
        )
        rate_plan_id = await get_rate_plan_id_from_code(
            session, webhook_data.ota_connection_id, rate_item.rate_plan_code
        )
        
        if room_type_id and rate_plan_id:
            # Update or create DailyRate entry
            result = await session.exec(
                select(DailyRate).where(
                    DailyRate.room_type_id == room_type_id,
                    DailyRate.rate_plan_id == rate_plan_id,
                    DailyRate.date == rate_item.date
                )
            )
            daily_rate = result.first()
            
            if daily_rate:
                daily_rate.override_rate = rate_item.rate
                daily_rate.updated_at = datetime.utcnow()
            else:
                daily_rate = DailyRate(
                    room_type_id=room_type_id,
                    rate_plan_id=rate_plan_id,
                    date=rate_item.date,
                    base_rate=rate_item.rate,
                    override_rate=rate_item.rate
                )
                session.add(daily_rate)
            
            updated_count += 1
    
    await session.commit()
    
    # Create sync log
    ota_connection = await session.get(OTAConnection, webhook_data.ota_connection_id)
    if ota_connection:
        sync_log = SyncLog(
            property_id=ota_connection.property_id,
            ota_connection_id=webhook_data.ota_connection_id,
            sync_type="rates",
            sync_direction="pull",
            status="success",
            records_processed=updated_count,
            records_failed=0,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            duration_seconds=0.0
        )
        session.add(sync_log)
        await session.commit()
    
    # Broadcast SSE event
    background_tasks.add_task(
        broadcast_sse_event,
        "rates.updated",
        {"updated_count": updated_count, "ota_connection_id": webhook_data.ota_connection_id}
    )
    
    return {
        "success": True,
        "message": f"Rates updated for {updated_count} entries",
        "updated_count": updated_count
    }


async def handle_restrictions_updated(payload: Dict[str, Any], session: AsyncSession, background_tasks: BackgroundTasks):
    """Handle restrictions.updated webhook"""
    try:
        webhook_data = RestrictionsUpdatedWebhook(**payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    updated_count = 0
    
    for restriction_item in webhook_data.restrictions:
        room_type_id = await get_room_type_id_from_code(
            session, webhook_data.ota_connection_id, restriction_item.room_type_code
        )
        
        if room_type_id:
            ota_connection = await session.get(OTAConnection, webhook_data.ota_connection_id)
            
            # Create or update ChannelRestriction
            result = await session.exec(
                select(ChannelRestriction).where(
                    ChannelRestriction.ota_connection_id == webhook_data.ota_connection_id,
                    ChannelRestriction.room_type_id == room_type_id,
                    ChannelRestriction.restriction_date == restriction_item.date,
                    ChannelRestriction.restriction_type == restriction_item.restriction_type
                )
            )
            restriction = result.first()
            
            if restriction:
                restriction.restriction_value = restriction_item.restriction_value
                restriction.updated_at = datetime.utcnow()
            else:
                restriction = ChannelRestriction(
                    property_id=ota_connection.property_id if ota_connection else 1,
                    ota_connection_id=webhook_data.ota_connection_id,
                    room_type_id=room_type_id,
                    restriction_date=restriction_item.date,
                    restriction_type=restriction_item.restriction_type,
                    restriction_value=restriction_item.restriction_value,
                    is_active=True
                )
                session.add(restriction)
            
            # Update AvailabilityGrid flags
            grid_result = await session.exec(
                select(AvailabilityGrid).where(
                    AvailabilityGrid.room_type_id == room_type_id,
                    AvailabilityGrid.grid_date == restriction_item.date
                )
            )
            grid_entry = grid_result.first()
            
            if grid_entry:
                if restriction_item.restriction_type == "stop_sell":
                    grid_entry.stop_sell_flag = restriction_item.restriction_value == 1
                elif restriction_item.restriction_type == "CTA":
                    grid_entry.cta_flag = restriction_item.restriction_value == 1
                elif restriction_item.restriction_type == "CTD":
                    grid_entry.ctd_flag = restriction_item.restriction_value == 1
                elif restriction_item.restriction_type == "min_stay":
                    grid_entry.min_stay = restriction_item.restriction_value
                elif restriction_item.restriction_type == "max_stay":
                    grid_entry.max_stay = restriction_item.restriction_value
                grid_entry.updated_at = datetime.utcnow()
            
            updated_count += 1
    
    await session.commit()
    
    # Create sync log
    ota_connection = await session.get(OTAConnection, webhook_data.ota_connection_id)
    if ota_connection:
        sync_log = SyncLog(
            property_id=ota_connection.property_id,
            ota_connection_id=webhook_data.ota_connection_id,
            sync_type="restrictions",
            sync_direction="pull",
            status="success",
            records_processed=updated_count,
            records_failed=0,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            duration_seconds=0.0
        )
        session.add(sync_log)
        await session.commit()
    
    # Broadcast SSE event
    background_tasks.add_task(
        broadcast_sse_event,
        "restrictions.updated",
        {"updated_count": updated_count, "ota_connection_id": webhook_data.ota_connection_id}
    )
    
    return {
        "success": True,
        "message": f"Restrictions updated for {updated_count} entries",
        "updated_count": updated_count
    }


async def handle_sync_status(payload: Dict[str, Any], session: AsyncSession, background_tasks: BackgroundTasks):
    """Handle sync.status webhook"""
    try:
        webhook_data = SyncStatusWebhook(**payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    
    # Update OTAConnection
    ota_connection = await session.get(OTAConnection, webhook_data.ota_connection_id)
    if ota_connection:
        status_dict = webhook_data.status
        new_status = status_dict.get("connection_status", "connected")
        ota_connection.connection_status = new_status
        # When reconnecting (e.g. after disconnect), restore is_active so sync and webhooks work
        if new_status == "connected":
            ota_connection.is_active = True
        if "last_sync_at" in status_dict:
            try:
                ota_connection.last_sync_at = datetime.fromisoformat(status_dict["last_sync_at"].replace("Z", "+00:00"))
            except:
                ota_connection.last_sync_at = datetime.utcnow()
        ota_connection.error_message = status_dict.get("error_message")
        ota_connection.updated_at = datetime.utcnow()
        
        await session.commit()
        
        # Create sync log
        sync_log = SyncLog(
            property_id=ota_connection.property_id,
            ota_connection_id=webhook_data.ota_connection_id,
            sync_type=status_dict.get("sync_type", "full"),
            sync_direction="pull",
            status="success" if status_dict.get("records_failed", 0) == 0 else "partial",
            records_processed=status_dict.get("records_processed", 0),
            records_failed=status_dict.get("records_failed", 0),
            completed_at=datetime.utcnow()
        )
        session.add(sync_log)
        await session.commit()
    
    # Broadcast SSE event
    background_tasks.add_task(
        broadcast_sse_event,
        "sync.status",
        {
            "ota_connection_id": webhook_data.ota_connection_id,
            "status": webhook_data.status
        }
    )
    
    return {
        "success": True,
        "message": "Sync status updated",
        "ota_connection_id": webhook_data.ota_connection_id
    }


async def update_availability_grid(session: AsyncSession, room_type_id: int, start_date: date_type, end_date: date_type, delta: int):
    """Update availability grid for date range - optimized with batch query"""
    # Batch query all dates at once instead of querying each date individually
    result = await session.exec(
        select(AvailabilityGrid).where(
            AvailabilityGrid.room_type_id == room_type_id,
            AvailabilityGrid.grid_date >= start_date,
            AvailabilityGrid.grid_date < end_date
        )
    )
    existing_entries = {entry.grid_date: entry for entry in result.all()}
    
    # Process all dates
    current_date = start_date
    while current_date < end_date:
        if current_date in existing_entries:
            # Update existing entry
            grid_entry = existing_entries[current_date]
            grid_entry.sold = max(0, grid_entry.sold - delta)  # Subtract delta because delta is negative for booking
            grid_entry.available = grid_entry.total_inventory - grid_entry.sold - grid_entry.blocked
            grid_entry.updated_at = datetime.utcnow()
        else:
            # Create new entry (shouldn't happen often, but handle it)
            grid_entry = AvailabilityGrid(
                property_id=1,  # Default property_id
                room_type_id=room_type_id,
                grid_date=current_date,
                total_inventory=10,  # Default - should be fetched from RoomType
                sold=max(0, -delta),
                blocked=0,
                available=10 - max(0, -delta)
            )
            session.add(grid_entry)
        
        current_date += timedelta(days=1)
    
    await session.flush()


# ============== SSE ENDPOINT ==============

@router.get("/channel-manager/sse")
async def channel_manager_sse_stream(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_sse),
):
    """
    Server-Side Events (SSE) stream for real-time channel manager updates.

    Auth: use either Authorization: Bearer <token> or query ?token=<access_token>
    (EventSource cannot send headers, so use ?token= for that).

    Example (Fetch with header):
        fetch('/api/v1/webhooks/channel-manager/sse', { headers: { Authorization: `Bearer ${token}` } })
    Example (EventSource with query token):
        const eventSource = new EventSource(`/api/v1/webhooks/channel-manager/sse?token=${accessToken}`);
        eventSource.onmessage = (event) => { const data = JSON.parse(event.data); ... };
    """
    import asyncio
    
    async def event_generator():
        """Generate SSE events"""
        event_queue = asyncio.Queue()
        sse_connections.append(event_queue)
        logger.info(f"[SSE] New connection established for user {current_user.id}. Total connections: {len(sse_connections)}")
        print(f"[SSE] New connection established for user {current_user.id}. Total connections: {len(sse_connections)}")
        
        try:
            # Send initial connection message
            initial_message = {
                "type": "connected",
                "message": "SSE connection established",
                "user_id": current_user.id
            }
            yield f"data: {json.dumps(initial_message)}\n\n"
            
            while True:
                try:
                    # Wait for event with timeout
                    event = await asyncio.wait_for(event_queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    event_queue.task_done()
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield ": keepalive\n\n"
                except Exception as e:
                    logger.error(f"[SSE] Error in event generator: {e}", exc_info=True)
                    print(f"[SSE] Error in event generator: {e}")
                    # Send error event
                    error_event = {
                        "type": "error",
                        "message": str(e),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
                    break
        except asyncio.CancelledError:
            logger.info(f"[SSE] Connection cancelled for user {current_user.id}")
            print(f"[SSE] Connection cancelled for user {current_user.id}")
        except Exception as e:
            logger.error(f"[SSE] Unexpected error in SSE stream: {e}", exc_info=True)
            print(f"[SSE] Unexpected error in SSE stream: {e}")
        finally:
            # Remove from connections when client disconnects
            if event_queue in sse_connections:
                sse_connections.remove(event_queue)
                logger.info(f"[SSE] Connection closed for user {current_user.id}. Remaining connections: {len(sse_connections)}")
                print(f"[SSE] Connection closed for user {current_user.id}. Remaining connections: {len(sse_connections)}")
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS"
        }
    )


@router.options("/channel-manager/sse")
async def channel_manager_sse_options():
    """Handle CORS preflight requests for SSE endpoint"""
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Max-Age": "3600"
        }
    )


def _sse_event_payload(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Build the event dict sent to clients."""
    return {
        "type": event_type,
        "data": data,
        "timestamp": datetime.utcnow().isoformat()
    }


async def _broadcast_to_local_connections(event_type: str, data: Dict[str, Any]) -> int:
    """Send event to all SSE connections in this worker. Returns count sent."""
    event = _sse_event_payload(event_type, data)
    sent_count = 0
    for connection in sse_connections.copy():
        try:
            await connection.put(event)
            sent_count += 1
        except Exception as e:
            logger.error(f"[SSE] Error sending SSE event to connection: {e}")
            if connection in sse_connections:
                sse_connections.remove(connection)
    return sent_count


async def broadcast_sse_event(event_type: str, data: Dict[str, Any]):
    """
    Broadcast SSE event to all connected clients.
    With Redis: publish to Redis so every worker receives and sends to its local connections.
    Without Redis: send only to this worker's connections (single-worker only).
    """
    try:
        print(f"[SSE] broadcast_sse_event CALLED: event_type={event_type}")
        logger.info(f"[SSE] broadcast_sse_event CALLED: event_type={event_type}")
        event = _sse_event_payload(event_type, data)
        payload = json.dumps(event)

        # Try Redis pub/sub first (multi-worker safe)
        try:
            from app.core.config import settings
            import redis.asyncio as aioredis
            redis_client = await aioredis.from_url(settings.redis_url)
            try:
                await redis_client.publish(SSE_REDIS_CHANNEL, payload)
                logger.info(f"[SSE] Published {event_type} to Redis channel {SSE_REDIS_CHANNEL}")
            finally:
                await redis_client.aclose()
            # Subscriber in each worker (including this one) will push to local connections
            return
        except Exception as redis_err:
            logger.debug(f"[SSE] Redis publish failed, using local broadcast only: {redis_err}")
            pass

        # Fallback: local broadcast only (single-worker or Redis unavailable)
        active_connections = len(sse_connections)
        logger.info(f"[SSE] Broadcasting event: {event_type} to {active_connections} connection(s) (local only)")
        print(f"[SSE] Broadcasting event: {event_type} to {active_connections} connection(s)")
        if active_connections == 0:
            logger.warning(f"[SSE] No active connections! Event {event_type} will not be delivered to frontend.")
            print(f"[SSE] WARNING: No active connections! Event {event_type} will not be delivered to frontend.")
        sent_count = await _broadcast_to_local_connections(event_type, data)
        if sent_count > 0:
            logger.info(f"[SSE] Successfully sent {event_type} event to {sent_count} connection(s)")
            print(f"[SSE] Successfully sent {event_type} event to {sent_count} connection(s)")
    except Exception as e:
        logger.error(f"[SSE] CRITICAL ERROR in broadcast_sse_event: {e}", exc_info=True)
        print(f"[SSE] CRITICAL ERROR in broadcast_sse_event: {e}")
        import traceback
        print(f"[SSE] Traceback:\n{traceback.format_exc()}")


async def _run_sse_redis_subscriber() -> None:
    """Listen on Redis for SSE events and push to this worker's local connections."""
    import asyncio
    try:
        from app.core.config import settings
        import redis.asyncio as aioredis
    except ImportError:
        logger.debug("[SSE] Redis not available, SSE subscriber not started")
        return
    while True:
        try:
            client = await aioredis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe(SSE_REDIS_CHANNEL)
            logger.info(f"[SSE] Subscribed to Redis channel {SSE_REDIS_CHANNEL} (multi-worker SSE enabled)")
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    raw = message.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    event = json.loads(raw)
                    event_type = event.get("type") or "unknown"
                    data = event.get("data") or {}
                    sent = await _broadcast_to_local_connections(event_type, data)
                    if sent > 0:
                        logger.info(f"[SSE] Redis: delivered {event_type} to {sent} local connection(s)")
                except Exception as e:
                    logger.warning(f"[SSE] Redis subscriber parse/send error: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[SSE] Redis subscriber error, reconnecting in 5s: {e}")
            await asyncio.sleep(5)


async def sse_redis_available() -> bool:
    """Return True if Redis is reachable (for SSE pub/sub). Use to avoid starting subscriber when Redis is not running."""
    try:
        from app.core.config import settings
        import redis.asyncio as aioredis
        client = await aioredis.from_url(settings.redis_url)
        try:
            await client.ping()
            return True
        finally:
            await client.aclose()
    except Exception:
        return False


def start_sse_redis_subscriber_background() -> Optional[Any]:
    """Start the Redis SSE subscriber in the background. Call from app lifespan. Returns the asyncio task."""
    import asyncio
    global _sse_redis_subscriber_task
    if _sse_redis_subscriber_task is not None:
        return _sse_redis_subscriber_task
    try:
        from app.core.config import settings
        import redis.asyncio as aioredis
        # Quick check that Redis is reachable
        _sse_redis_subscriber_task = asyncio.create_task(_run_sse_redis_subscriber())
        return _sse_redis_subscriber_task
    except Exception as e:
        logger.debug(f"[SSE] Not starting Redis SSE subscriber: {e}")
        return None
