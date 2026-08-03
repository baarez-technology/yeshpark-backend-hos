from typing import List, Optional
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, Field

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.inventory import Room, RatePlan, RoomType, RoomStatus, DailyRate
from app.models.user import User
from app.services.reservation_service import check_availability
from app.models.reservations import Reservation, Booking

router = APIRouter()


async def get_room_type_name(session: AsyncSession, room: Room) -> str:
    """Helper to get room type name from room_type_id"""
    if room.room_type_id:
        rt = await session.get(RoomType, room.room_type_id)
        if rt:
            return rt.name
    return "Standard Room"


class RoomRead(BaseModel):
    id: str
    name: str
    slug: str
    number: Optional[str] = None  # Room number
    description: str
    shortDescription: Optional[str] = None
    price: float
    images: List[str] = []
    amenities: List[str] = []
    maxGuests: int
    bedType: str
    size: int
    view: str
    floor: Optional[int] = None  # Floor number
    status: Optional[str] = None  # Room status (clean, dirty, etc.)
    occupancyStatus: Optional[str] = None  # F-03: vacant, occupied, reserved
    cleaningStatus: Optional[str] = None  # F-03: clean, dirty, inspected, in_progress
    category: Optional[str] = None
    type: Optional[str] = None  # Room type name (proper case)
    features: List[str] = []
    rating: Optional[float] = None
    reviewCount: Optional[int] = None
    notes: Optional[str] = None  # Room notes (visible to admin/maintenance)
    available: bool = True  # Default to True, matches frontend expectation

    class Config:
        from_attributes = True


class RoomListResponse(BaseModel):
    items: List[RoomRead]
    total: int
    page: int
    pageSize: int
    totalPages: int



@router.get("/availability", response_model=List[RoomRead])
async def check_all_rooms_availability(
    startDate: str = Query(..., alias="startDate"),
    endDate: str = Query(..., alias="endDate"),
    guests: Optional[int] = Query(1),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Check availability for all rooms (generic search)"""
    try:
        arrival = date.fromisoformat(startDate)
        departure = date.fromisoformat(endDate)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid date format")

    available_rooms = await check_availability(
        session=session,
        arrival_date=arrival,
        departure_date=departure,
        room_type=None,
        adults=guests or 1
    )
    
    # Convert to RoomRead format
    results = []
    for room in available_rooms:
        results.append(await room_to_read(room, session))
        
    return results


def _derive_room_status(room) -> str:
    """Derive effective room status from compound fields for consistent counts."""
    occupancy = getattr(room, 'occupancy_status', None) or 'vacant'
    cleaning = getattr(room, 'cleaning_status', None)
    if occupancy == 'occupied' or room.status == 'occupied':
        return 'occupied'
    if room.status in ('out_of_service', 'out_of_order', 'maintenance'):
        return room.status
    if cleaning in ('dirty', 'in_progress', 'inspected', 'clean'):
        return cleaning
    return room.status


@router.get("", response_model=RoomListResponse)
async def list_rooms(
    checkIn: Optional[str] = Query(None),
    checkOut: Optional[str] = Query(None),
    guests: Optional[int] = Query(None),
    minPrice: Optional[float] = Query(None),
    maxPrice: Optional[float] = Query(None),
    type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_tenant_session)
):
    """List all rooms with optional filters"""
    from sqlmodel import asc
    
    query = select(Room)
    
    # Apply filters
    if type:
        # Filter by room type name - need to do this after fetching since Room has room_type_id not room_type
        pass  # Will filter after fetching
    if guests:
        query = query.where(Room.capacity >= guests)
    
    # Add ordering by floor and room number for consistent display
    query = query.order_by(asc(Room.floor), asc(Room.number))
    
    # Get total count
    result = await session.exec(query)
    all_rooms = result.all()
    
    # Filter by room type name if specified (post-fetch filter since we need to look up room type)
    if type:
        filtered_rooms = []
        for room in all_rooms:
            rt = await session.get(RoomType, room.room_type_id)
            if rt and (type.lower() in rt.name.lower() or (rt.category and type.lower() in rt.category.lower())):
                filtered_rooms.append(room)
        all_rooms = filtered_rooms
    total = len(all_rooms)
    
    # Paginate
    offset = (page - 1) * pageSize
    paginated_rooms = all_rooms[offset:offset + pageSize]
    
    # Pre-fetch today's occupied room IDs from both Booking and Reservation tables (single queries)
    # This ensures rooms with active bookings show as unavailable even without checkIn/checkOut params
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Check Booking table (new bookings)
    booking_occupied_stmt = select(Booking.room_id).where(
        and_(
            Booking.arrival_date < tomorrow,
            Booking.departure_date > today,
            Booking.status.in_(["booked", "confirmed", "checked_in"]),
            Booking.room_id.isnot(None)
        )
    )
    booking_occupied_result = await session.exec(booking_occupied_stmt)
    occupied_room_ids = set(booking_occupied_result.all())

    # Check Reservation table (legacy reservations)
    reservation_occupied_stmt = select(Reservation.room_id).where(
        and_(
            Reservation.arrival_date < tomorrow,
            Reservation.departure_date > today,
            Reservation.status.in_(["booked", "confirmed", "checked_in"]),
            Reservation.room_id.isnot(None)
        )
    )
    reservation_occupied_result = await session.exec(reservation_occupied_stmt)
    occupied_room_ids |= set(reservation_occupied_result.all())

    # Pre-compute date-range availability if dates are provided (single bulk query)
    date_range_available_ids = None
    if checkIn and checkOut:
        try:
            arrival = date.fromisoformat(checkIn)
            departure = date.fromisoformat(checkOut)
            all_available_for_dates = await check_availability(
                session=session,
                arrival_date=arrival,
                departure_date=departure,
                room_type=None,
                adults=guests or 1
            )
            date_range_available_ids = {r.id for r in all_available_for_dates}
        except Exception as e:
            import logging
            logging.error(f"Bulk availability check failed: {e}")
            date_range_available_ids = None

    # Pre-fetch today's DailyRate overrides keyed by room_type_id so room
    # cards reflect AI recommendations, bulk edits, and manual rate changes.
    today_rate_overrides: dict = {}  # room_type_id -> override_rate
    try:
        bar_plan_result = await session.exec(
            select(RatePlan).where(RatePlan.code == "BAR").limit(1)
        )
        bar_plan = bar_plan_result.first()
        if bar_plan:
            rt_ids = list({r.room_type_id for r in paginated_rooms if r.room_type_id})
            if rt_ids:
                dr_result = await session.exec(
                    select(DailyRate).where(
                        and_(
                            DailyRate.room_type_id.in_(rt_ids),
                            DailyRate.rate_plan_id == bar_plan.id,
                            DailyRate.date == today,
                        )
                    )
                )
                for dr in dr_result.all():
                    if dr.override_rate is not None:
                        today_rate_overrides[dr.room_type_id] = round(float(dr.override_rate), 2)
    except Exception:
        pass

    # Convert to frontend format
    rooms_data = []
    for room in paginated_rooms:
        # Get room type name
        room_type_name = await get_room_type_name(session, room)

        # Parse amenities and images from JSON strings
        import json
        amenities = []
        images = []

        if room.amenities:
            try:
                amenities = json.loads(room.amenities) if isinstance(room.amenities, str) else room.amenities
            except:
                amenities = room.amenities.split(',') if isinstance(room.amenities, str) else []

        if room.images:
            try:
                images = json.loads(room.images) if isinstance(room.images, str) else room.images
            except:
                images = [room.images] if isinstance(room.images, str) else []

        # Get room type object for price and images fallback
        room_type_obj = None
        if room.room_type_id:
            room_type_obj = await session.get(RoomType, room.room_type_id)

        # If room has no images, try to get from room type
        if (not images or len(images) == 0) and room_type_obj and room_type_obj.images:
            try:
                images = json.loads(room_type_obj.images) if isinstance(room_type_obj.images, str) else room_type_obj.images
            except:
                images = []

        # Check availability - use pre-computed date-range if available, else fall back to status
        if date_range_available_ids is not None:
            # Date-range based: room is available if it has no conflicting bookings for the period
            available = room.id in date_range_available_ids
        else:
            # No dates provided — use current physical status + today's occupancy
            normalized_status = RoomStatus.normalize(room.status) if room.status else RoomStatus.AVAILABLE
            available = normalized_status not in RoomStatus.UNAVAILABLE
            if room.id in occupied_room_ids:
                available = False

        # Create slug from room number and type
        slug = f"{room_type_name.lower().replace(' ', '-')}-{room.number}"

        # Get price — prefer today's DailyRate override (set by Rate Calendar,
        # AI recommendations, or bulk edits), then room-specific price, then
        # room type base price.  This keeps the Rooms page in sync with the
        # Rate Calendar without affecting booking or reservation pricing.
        room_price = 0.0
        if room.room_type_id and room.room_type_id in today_rate_overrides:
            room_price = today_rate_overrides[room.room_type_id]
        elif room.price_per_night is not None:
            room_price = room.price_per_night
        elif room_type_obj and room_type_obj.base_price:
            room_price = room_type_obj.base_price
        else:
            logger.warning(f"Room {room.number} has no price set and no room type base_price")

        # Use local room images - override external URLs (Unsplash, etc.) with local images
        # Local images are stored in frontend public folder at /images/rooms/
        if not images or len(images) == 0 or any('unsplash' in str(img) or 'http' in str(img) for img in images):
            # Use room number to pick a local image (cycle through 1-14)
            room_num = int(room.number) if room.number.isdigit() else hash(room.number) % 14 + 1
            image_index = ((room_num - 1) % 14) + 1
            images = [f"/images/rooms/room-{image_index}.jpg"]

        # Use room-specific description if available, else fallback to default
        room_description = room.description if room.description else f"Beautiful {room_type_name} room"

        rooms_data.append(RoomRead(
            id=str(room.id),
            name=f"{room_type_name} {room.number}",
            slug=slug,
            number=room.number,
            description=room_description,
            shortDescription=f"{room_type_name} room",
            price=room_price,
            images=images,
            amenities=amenities,
            maxGuests=room.max_occupancy,
            bedType=room.bed_type or "King",
            size=room.size_sqft or 300,
            view=room.view_type or "City",
            floor=room.floor,
            status=_derive_room_status(room),
            occupancyStatus=getattr(room, 'occupancy_status', None) or "vacant",
            cleaningStatus=getattr(room, 'cleaning_status', None) or "clean",
            category=room_type_name.lower(),
            type=room_type_name,
            features=amenities,
            available=available
        ))
    
    total_pages = (total + pageSize - 1) // pageSize
    
    return RoomListResponse(
        items=rooms_data,
        total=total,
        page=page,
        pageSize=pageSize,
        totalPages=total_pages
    )


@router.get("/{room_id}", response_model=RoomRead)
async def get_room(
    room_id: str,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get room by ID or slug"""
    room = None
    
    # Try as integer ID first
    try:
        room_id_int = int(room_id)
        room = await session.get(Room, room_id_int)
    except ValueError:
        # Not an integer, try to find by room number (last part of slug)
        # Slug format: "room-type-roomnumber" or just "roomnumber"
        room_number = room_id.split('-').pop()
        result = await session.exec(select(Room).where(Room.number == room_number))
        room = result.first()
    
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Get room type name
    room_type_name = await get_room_type_name(session, room)

    # Parse amenities and images
    import json
    amenities = []
    images = []

    if room.amenities:
        try:
            amenities = json.loads(room.amenities) if isinstance(room.amenities, str) else room.amenities
        except:
            amenities = room.amenities.split(',') if isinstance(room.amenities, str) else []

    if room.images:
        try:
            images = json.loads(room.images) if isinstance(room.images, str) else room.images
        except:
            images = [room.images] if isinstance(room.images, str) else []

    # Get room type object for price and images fallback
    room_type_obj = None
    if room.room_type_id:
        room_type_obj = await session.get(RoomType, room.room_type_id)

    # If room has no images, try to get from room type
    if (not images or len(images) == 0) and room_type_obj and room_type_obj.images:
        try:
            images = json.loads(room_type_obj.images) if isinstance(room_type_obj.images, str) else room_type_obj.images
        except:
            images = []

    slug = f"{room_type_name.lower().replace(' ', '-')}-{room.number}"

    # Get price - use room-specific price first, then fall back to room type base price
    # No hardcoded defaults - all prices must come from database
    room_price = 0.0
    if room.price_per_night is not None:
        room_price = room.price_per_night
    elif room_type_obj and room_type_obj.base_price:
        room_price = room_type_obj.base_price
    else:
        logger.warning(f"Room {room.number} has no price set and no room type base_price")

    # Use room-specific description if available
    room_description = room.description if room.description else f"Beautiful {room_type_name} room"

    # Use local room images - override external URLs (Unsplash, etc.) with local images
    if not images or len(images) == 0 or any('unsplash' in str(img) or 'http' in str(img) for img in images):
        room_num = int(room.number) if room.number.isdigit() else hash(room.number) % 14 + 1
        image_index = ((room_num - 1) % 14) + 1
        images = [f"/images/rooms/room-{image_index}.jpg"]

    # Determine availability based on room status
    normalized_status = RoomStatus.normalize(room.status) if room.status else RoomStatus.AVAILABLE
    available = normalized_status not in RoomStatus.UNAVAILABLE

    return RoomRead(
        id=str(room.id),
        name=f"{room_type_name} {room.number}",
        slug=slug,
        number=room.number,
        description=room_description,
        shortDescription=f"{room_type_name} room",
        price=room_price,
        images=images,
        amenities=amenities,
        maxGuests=room.max_occupancy,
        bedType=room.bed_type or "King",
        size=room.size_sqft or 300,
        view=room.view_type or "City",
        floor=room.floor,
        status=room.status,
        occupancyStatus=getattr(room, 'occupancy_status', None) or "vacant",
        cleaningStatus=getattr(room, 'cleaning_status', None) or "clean",
        category=room_type_name.lower(),
        type=room_type_name,
        features=amenities,
        available=available,
    )


@router.get("/{room_id}/availability")
async def check_room_availability(
    room_id: str,
    checkIn: str = Query(...),
    checkOut: str = Query(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Check if a specific room is available for dates"""
    try:
        room_id_int = int(room_id)
        arrival = date.fromisoformat(checkIn)
        departure = date.fromisoformat(checkOut)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid parameters")
    
    room = await session.get(Room, room_id_int)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    room_type_name = await get_room_type_name(session, room)

    available_rooms = await check_availability(
        session=session,
        arrival_date=arrival,
        departure_date=departure,
        room_type=room_type_name,
        adults=1
    )
    
    is_available = any(r.id == room.id for r in available_rooms)
    
    return {"available": is_available}


class RoomCreate(BaseModel):
    number: str
    room_type: str
    floor: Optional[int] = None
    status: str = "clean"
    capacity: int = 2
    max_occupancy: int = 2
    bed_type: Optional[str] = None
    view_type: Optional[str] = None
    amenities: Optional[str] = None
    images: Optional[str] = None
    description: Optional[str] = None
    size_sqft: Optional[int] = None
    price_per_night: Optional[float] = None  # Room-specific price override


class RoomUpdate(BaseModel):
    status: Optional[str] = None
    amenities: Optional[str] = None
    description: Optional[str] = None
    bed_type: Optional[str] = None
    view_type: Optional[str] = None
    floor: Optional[int] = None
    price_per_night: Optional[float] = Field(None, alias="price")  # Room-specific price; accept "price" from frontend
    capacity: Optional[int] = None
    max_occupancy: Optional[int] = None
    notes: Optional[str] = None

    class Config:
        populate_by_name = True  # allow both "price" and "price_per_night"


class RoomNoteAdd(BaseModel):
    note: str


@router.post("", response_model=RoomRead)
async def create_room(
    room_data: RoomCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new room (admin only)"""
    if not current_user.is_superuser and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create rooms")

    # Check if room number already exists
    existing = (await session.exec(
        select(Room).where(Room.number == room_data.number)
    )).first()

    if existing:
        raise HTTPException(status_code=400, detail=f"Room {room_data.number} already exists")

    # Find matching room type by name/category
    room_type_name = room_data.room_type or "Standard"
    room_type = (await session.exec(
        select(RoomType).where(
            or_(
                RoomType.name.ilike(f"%{room_type_name}%"),
                RoomType.category.ilike(f"%{room_type_name}%")
            )
        )
    )).first()

    # If room type not found, use first available or create default
    if not room_type:
        room_type = (await session.exec(select(RoomType))).first()

    if not room_type:
        # Create a default room type if none exists
        # Use room's price_per_night as base_price, or require price to be provided
        room_base_price = room_data.price_per_night
        if not room_base_price or room_base_price <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Room type '{room_type_name}' not found. Please create the room type first or provide price_per_night for the room."
            )
        room_type = RoomType(
            name=room_type_name,
            slug=room_type_name.lower().replace(' ', '-'),
            description=f"{room_type_name} room type",
            base_price=room_base_price,
            max_guests=room_data.max_occupancy or 2,
        )
        session.add(room_type)
        await session.flush()

    # Create room with proper room_type_id
    room = Room(
        number=room_data.number,
        room_type_id=room_type.id,
        floor=room_data.floor,
        status=room_data.status,
        capacity=room_data.capacity,
        max_occupancy=room_data.max_occupancy,
        bed_type=room_data.bed_type,
        view_type=room_data.view_type,
        amenities=room_data.amenities,
        images=room_data.images,
        size_sqft=room_data.size_sqft,
        price_per_night=room_data.price_per_night,
        description=room_data.description,
    )

    session.add(room)
    await session.commit()
    await session.refresh(room)

    return await room_to_read(room, session)


@router.patch("/{room_id}", response_model=RoomRead)
async def update_room(
    room_id: str,
    room_data: RoomUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a room (admin only)"""
    if not current_user.is_superuser and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update rooms")
    
    try:
        room_id_int = int(room_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid room ID")
    
    room = await session.get(Room, room_id_int)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Update fields
    if room_data.status is not None:
        # Prevent marking occupied rooms as out_of_service or maintenance
        new_status = room_data.status.lower().strip()
        if new_status in ("out_of_service", "oos", "maintenance"):
            # Check if room is currently occupied
            if room.occupancy_status == "occupied" or room.status == "occupied":
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot mark room {room.number} as '{new_status}' while it is occupied. "
                           f"Please check out the guest first."
                )
            # Also check for active checked-in bookings
            from app.models.reservations import Booking
            active_booking = (await session.exec(
                select(Booking).where(
                    Booking.room_id == room_id_int,
                    Booking.status == "checked_in"
                )
            )).first()
            if active_booking:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot mark room {room.number} as '{new_status}'. "
                           f"Room has an active checked-in booking (#{active_booking.booking_number or active_booking.id}). "
                           f"Please check out the guest first."
                )
        room.status = room_data.status
    if room_data.amenities is not None:
        room.amenities = room_data.amenities
    if room_data.description is not None:
        room.description = room_data.description
    if room_data.bed_type is not None:
        room.bed_type = room_data.bed_type
    if room_data.view_type is not None:
        room.view_type = room_data.view_type
    if room_data.floor is not None:
        room.floor = room_data.floor
    # Support both "price" and "price_per_night"; allow setting or clearing room-specific price
    if "price_per_night" in room_data.model_dump(exclude_unset=True):
        room.price_per_night = room_data.price_per_night
    if room_data.capacity is not None:
        room.capacity = room_data.capacity
    if room_data.max_occupancy is not None:
        room.max_occupancy = room_data.max_occupancy
    if room_data.notes is not None:
        room.notes = room_data.notes

    room.updated_at = datetime.utcnow()
    session.add(room)
    await session.commit()
    await session.refresh(room)

    return await room_to_read(room, session)


@router.post("/{room_id}/notes")
async def add_room_note(
    room_id: str,
    payload: RoomNoteAdd,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Append a timestamped note to a room. Visible to Admin and Maintenance."""
    try:
        room_id_int = int(room_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid room ID")

    room = await session.get(Room, room_id_int)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    staff_name = current_user.full_name or current_user.email or f"User #{current_user.id}"
    formatted_note = f"[{timestamp}] ({staff_name}) {payload.note}"

    if room.notes:
        room.notes = f"{room.notes}\n{formatted_note}"
    else:
        room.notes = formatted_note

    room.updated_at = datetime.utcnow()
    session.add(room)
    await session.commit()
    await session.refresh(room)

    return {
        "success": True,
        "room_id": room.id,
        "room_number": room.number,
        "notes": room.notes,
        "message": f"Note added to Room {room.number}"
    }


@router.delete("/{room_id}")
async def delete_room(
    room_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a room (admin only)"""
    if not current_user.is_superuser and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete rooms")
    
    try:
        room_id_int = int(room_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid room ID")
    
    room = await session.get(Room, room_id_int)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Check if room has active reservations
    from app.models.reservations import Reservation
    active_reservations = (await session.exec(
        select(Reservation).where(
            Reservation.room_id == room_id_int,
            Reservation.status.in_(["booked", "checked_in"])
        )
    )).all()
    
    if active_reservations:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete room with active reservations"
        )
    
    await session.delete(room)
    await session.commit()
    
    return {"success": True, "message": f"Room {room.number} deleted"}


async def room_to_read(room: Room, session: AsyncSession) -> RoomRead:
    """Helper to convert Room model to RoomRead"""
    import json

    # Get room type name
    room_type_name = await get_room_type_name(session, room)

    amenities = []
    images = []

    if room.amenities:
        try:
            amenities = json.loads(room.amenities) if isinstance(room.amenities, str) else room.amenities
        except:
            amenities = room.amenities.split(',') if isinstance(room.amenities, str) else []

    if room.images:
        try:
            images = json.loads(room.images) if isinstance(room.images, str) else room.images
        except:
            images = [room.images] if isinstance(room.images, str) else []

    # Get room type object for price and images fallback
    room_type_obj = None
    if room.room_type_id:
        room_type_obj = await session.get(RoomType, room.room_type_id)

    # If room has no images, try to get from room type
    if (not images or len(images) == 0) and room_type_obj and room_type_obj.images:
        try:
            images = json.loads(room_type_obj.images) if isinstance(room_type_obj.images, str) else room_type_obj.images
        except:
            images = []

    # Use local room images - override external URLs (Unsplash, etc.) with local images
    if not images or len(images) == 0 or any('unsplash' in str(img) or 'http' in str(img) for img in images):
        # Use room number to pick a local image (cycle through 1-14)
        room_num = int(room.number) if room.number.isdigit() else hash(room.number) % 14 + 1
        image_index = ((room_num - 1) % 14) + 1
        images = [f"/images/rooms/room-{image_index}.jpg"]

    slug = f"{room_type_name.lower().replace(' ', '-')}-{room.number}"

    # Get price - use room-specific price first, then fall back to room type base price
    # No hardcoded defaults - all prices must come from database
    room_price = 0.0
    if room.price_per_night is not None:
        room_price = room.price_per_night
    elif room_type_obj and room_type_obj.base_price:
        room_price = room_type_obj.base_price
    else:
        logger.warning(f"Room {room.number} has no price set and no room type base_price")

    # Use room-specific description if available
    room_description = room.description if room.description else f"Beautiful {room_type_name} room"

    # Determine availability based on room status
    normalized_status = RoomStatus.normalize(room.status) if room.status else RoomStatus.AVAILABLE
    available = normalized_status not in RoomStatus.UNAVAILABLE

    return RoomRead(
        id=str(room.id),
        name=f"{room_type_name} {room.number}",
        slug=slug,
        number=room.number,
        description=room_description,
        shortDescription=f"{room_type_name} room",
        price=room_price,
        images=images,
        amenities=amenities,
        maxGuests=room.max_occupancy,
        bedType=room.bed_type or "King",
        size=room.size_sqft or 300,
        view=room.view_type or "City",
        floor=room.floor,
        status=room.status,
        occupancyStatus=getattr(room, 'occupancy_status', None) or "vacant",
        cleaningStatus=getattr(room, 'cleaning_status', None) or "clean",
        category=room_type_name.lower(),
        type=room_type_name,
        features=amenities,
        available=available,
    )

