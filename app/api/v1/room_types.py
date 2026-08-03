from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, Field
import json

from app.db.session import get_tenant_session
from app.models.inventory import Room, RoomType, DailyRate, RatePlan

router = APIRouter()


class RoomTypeRead(BaseModel):
    id: str
    roomTypeId: Optional[int] = None  # Numeric DB id for channel manager / internal APIs
    name: str
    slug: str
    description: str
    shortDescription: str
    price: float
    originalPrice: Optional[float] = None  # Non-None when dynamic pricing applied a discount
    images: List[str]
    amenities: List[str]
    maxGuests: int
    bedType: str
    size: int
    view: str
    category: str
    features: List[str]
    rating: Optional[float] = 4.5
    reviewCount: int = 0
    available: Optional[bool] = None
    availableRoomCount: int = 0

    class Config:
        from_attributes = True


class RoomTypeListResponse(BaseModel):
    items: List[RoomTypeRead]
    total: int
    page: int
    pageSize: int
    totalPages: int


class RoomTypeCreate(BaseModel):
    """Schema for creating a new room type"""
    name: str
    description: Optional[str] = None
    short_description: Optional[str] = None
    base_price: float
    max_guests: int
    amenities: Optional[List[str]] = None
    features: Optional[List[str]] = None
    bed_type: Optional[str] = None
    size_sqft: Optional[int] = None
    view_type: Optional[str] = None
    category: Optional[str] = None
    images: Optional[List[str]] = None


class RoomTypeUpdate(BaseModel):
    """Schema for updating a room type"""
    name: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    base_price: Optional[float] = Field(None, alias="price")  # accept "price" from frontend
    max_guests: Optional[int] = None
    amenities: Optional[List[str]] = None
    features: Optional[List[str]] = None
    bed_type: Optional[str] = None
    size_sqft: Optional[int] = None
    view_type: Optional[str] = None
    category: Optional[str] = None
    images: Optional[List[str]] = None
    is_active: Optional[bool] = None

    class Config:
        populate_by_name = True  # allow both "price" and "base_price"


def parse_json_field(value, default=None):
    """Parse JSON field that may be string or already parsed"""
    if value is None:
        return default or []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return default or []
    return default or []


def get_default_images(room_type_name: str, room_type_id: int = 1) -> List[str]:
    """Get default local images based on room type - uses local images stored in frontend public folder"""
    # Use room_type_id to determine which local images to use (cycle through 1-14)
    base_index = ((room_type_id - 1) % 14) + 1

    # Return 3 images starting from the base index, cycling through available images
    images = []
    for i in range(3):
        image_num = ((base_index - 1 + i) % 14) + 1
        images.append(f"/images/rooms/room-{image_num}.jpg")

    return images


@router.get("", response_model=RoomTypeListResponse)
async def list_room_types(
    checkIn: Optional[str] = Query(None),
    checkOut: Optional[str] = Query(None),
    guests: Optional[int] = Query(None),
    minPrice: Optional[float] = Query(None),
    maxPrice: Optional[float] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_tenant_session)
):
    """List room types from the RoomType table"""
    # Query RoomType table directly
    query = select(RoomType).where(RoomType.is_active == True)

    # Apply category filter
    if category:
        query = query.where(RoomType.category == category)

    # Apply price filters
    if minPrice:
        query = query.where(RoomType.base_price >= minPrice)
    if maxPrice:
        query = query.where(RoomType.base_price <= maxPrice)

    # Apply guests filter
    if guests:
        query = query.where(RoomType.max_guests >= guests)

    # Order by sort_order then name
    query = query.order_by(RoomType.sort_order, RoomType.name)

    result = await session.exec(query)
    room_types = result.all()

    # Parse optional date params for dynamic pricing
    arrival_date = None
    departure_date = None
    if checkIn and checkOut:
        try:
            arrival_date = date.fromisoformat(checkIn)
            departure_date = date.fromisoformat(checkOut)
        except ValueError:
            pass

    # Pre-fetch today's DailyRate overrides (for room listing without dates)
    today_overrides: dict = {}  # room_type_id -> override_rate
    if not (arrival_date and departure_date) and room_types:
        try:
            from sqlmodel import and_
            today = date.today()
            bar_plan_result = await session.exec(
                select(RatePlan).where(RatePlan.code == "BAR").limit(1)
            )
            bar_plan = bar_plan_result.first()
            if bar_plan:
                rt_ids = [rt.id for rt in room_types]
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
                        today_overrides[dr.room_type_id] = round(float(dr.override_rate), 2)
        except Exception:
            pass

    room_types_data = []

    for rt in room_types:
        # Count available rooms of this type
        available_count = 0
        available = None

        if arrival_date and departure_date:
            try:
                from app.services.reservation_service import check_availability
                available_rooms = await check_availability(
                    session=session,
                    arrival_date=arrival_date,
                    departure_date=departure_date,
                    room_type=rt.name,
                    adults=guests or 1
                )
                available_count = len(available_rooms)
                available = available_count > 0
            except Exception as e:
                print(f"Error checking availability: {e}")
                pass
        else:
            # Count total rooms of this type with available status
            count_query = select(func.count(Room.id)).where(
                Room.room_type_id == rt.id,
                Room.status.in_(["available", "clean", "inspected"])
            )
            count_result = await session.exec(count_query)
            available_count = count_result.one()
            available = available_count > 0

        # Dynamic pricing: calculate effective price when dates are provided
        effective_price = rt.base_price
        original_price = None
        if arrival_date and departure_date:
            try:
                from app.services.pricing_service import calculate_effective_price
                effective_price, original_price = await calculate_effective_price(
                    session=session,
                    room_type_name=rt.name,
                    room_type_id=rt.id,
                    base_price=rt.base_price,
                    check_in=arrival_date,
                    check_out=departure_date,
                )
            except Exception as e:
                print(f"Error calculating dynamic price for {rt.name}: {e}")
                effective_price = rt.base_price
                original_price = None
        else:
            # No dates provided — use today's DailyRate override (pre-fetched
            # above) so the room listing reflects AI recommendations, bulk
            # edits, and manual overrides applied via the Rate Calendar.
            if rt.id in today_overrides:
                effective_price = today_overrides[rt.id]
                if effective_price != rt.base_price:
                    original_price = rt.base_price

        # Parse JSON fields
        amenities = parse_json_field(rt.amenities, ["Free WiFi", "Air Conditioning", "Smart TV", "Mini Bar"])
        features = parse_json_field(rt.features, ["Modern Design", "Premium Comfort"])
        images = parse_json_field(rt.images)

        # Use local images if no images or if images are external URLs (Unsplash, etc.)
        # Local images are stored in frontend public folder at /images/rooms/
        if not images or (images and any('unsplash' in img or 'http' in img for img in images)):
            images = get_default_images(rt.name, rt.id)

        room_types_data.append(RoomTypeRead(
            id=rt.slug,
            roomTypeId=rt.id,
            name=rt.name,
            slug=rt.slug,
            description=rt.description or f"Beautiful {rt.name} with modern amenities",
            shortDescription=rt.short_description or f"Comfortable {rt.name} accommodation",
            price=effective_price,
            originalPrice=original_price,
            images=images,
            amenities=amenities,
            maxGuests=rt.max_guests,
            bedType=rt.bed_type or "King",
            size=rt.size_sqft or 350,
            view=rt.view_type or "City",
            category=rt.category or "standard",
            features=features,
            rating=rt.rating or 4.5,
            reviewCount=rt.review_count or 0,
            available=available,
            availableRoomCount=available_count,
        ))

    # Apply pagination
    total = len(room_types_data)
    total_pages = (total + pageSize - 1) // pageSize if total > 0 else 1
    offset = (page - 1) * pageSize
    paginated = room_types_data[offset:offset + pageSize]

    return RoomTypeListResponse(
        items=paginated,
        total=total,
        page=page,
        pageSize=pageSize,
        totalPages=total_pages
    )


@router.post("", response_model=RoomTypeRead, status_code=201)
async def create_room_type(
    create_data: RoomTypeCreate,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Create a new room type"""
    from datetime import datetime
    import re

    # Generate slug from name
    slug = re.sub(r'[^a-z0-9]+', '-', create_data.name.lower()).strip('-')

    # Check for duplicate slug
    existing = await session.exec(
        select(RoomType).where(RoomType.slug == slug)
    )
    if existing.first():
        raise HTTPException(status_code=400, detail=f"Room type with slug '{slug}' already exists")

    # Get max sort_order for ordering
    max_order_result = await session.exec(
        select(func.max(RoomType.sort_order))
    )
    max_order = max_order_result.one() or 0

    # Create room type
    rt = RoomType(
        name=create_data.name,
        slug=slug,
        description=create_data.description or f"Beautiful {create_data.name} with modern amenities",
        short_description=create_data.short_description or f"Comfortable {create_data.name} accommodation",
        base_price=create_data.base_price,
        max_guests=create_data.max_guests,
        bed_type=create_data.bed_type,
        size_sqft=create_data.size_sqft,
        view_type=create_data.view_type,
        category=create_data.category or "standard",
        amenities=json.dumps(create_data.amenities) if create_data.amenities else None,
        features=json.dumps(create_data.features) if create_data.features else None,
        images=json.dumps(create_data.images) if create_data.images else None,
        is_active=True,
        sort_order=max_order + 1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    session.add(rt)
    await session.commit()
    await session.refresh(rt)

    # Parse JSON fields for response
    amenities = parse_json_field(rt.amenities, ["Free WiFi", "Air Conditioning"])
    features = parse_json_field(rt.features, [])
    images = parse_json_field(rt.images)
    if not images:
        images = get_default_images(rt.name, rt.id)

    # Count available rooms (0 for new type)
    return RoomTypeRead(
        id=rt.slug,
        roomTypeId=rt.id,
        name=rt.name,
        slug=rt.slug,
        description=rt.description or f"Beautiful {rt.name} with modern amenities",
        shortDescription=rt.short_description or f"Comfortable {rt.name} accommodation",
        price=rt.base_price,
        images=images,
        amenities=amenities,
        maxGuests=rt.max_guests,
        bedType=rt.bed_type or "King",
        size=rt.size_sqft or 350,
        view=rt.view_type or "City",
        category=rt.category or "standard",
        features=features,
        rating=4.5,
        reviewCount=0,
        available=False,
        availableRoomCount=0,
    )


@router.get("/{room_type_slug}", response_model=RoomTypeRead)
async def get_room_type(
    room_type_slug: str,
    checkIn: Optional[str] = Query(None),
    checkOut: Optional[str] = Query(None),
    guests: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get details for a specific room type by slug"""
    # Query by slug
    result = await session.exec(
        select(RoomType).where(RoomType.slug == room_type_slug)
    )
    rt = result.first()

    if not rt:
        # Try converting slug to name format
        room_type_name = room_type_slug.replace('-', ' ').title()
        result = await session.exec(
            select(RoomType).where(RoomType.name == room_type_name)
        )
        rt = result.first()

    if not rt:
        raise HTTPException(status_code=404, detail="Room type not found")

    # Parse optional date params for dynamic pricing
    arrival_date = None
    departure_date = None
    if checkIn and checkOut:
        try:
            arrival_date = date.fromisoformat(checkIn)
            departure_date = date.fromisoformat(checkOut)
        except ValueError:
            pass

    # Count available rooms of this type
    available_count = 0
    available = None

    if arrival_date and departure_date:
        try:
            from app.services.reservation_service import check_availability
            available_rooms = await check_availability(
                session=session,
                arrival_date=arrival_date,
                departure_date=departure_date,
                room_type=rt.name,
                adults=guests or 1
            )
            available_count = len(available_rooms)
            available = available_count > 0
        except Exception as e:
            print(f"Error checking availability: {e}")
            pass
    else:
        count_query = select(func.count(Room.id)).where(
            Room.room_type_id == rt.id,
            Room.status.in_(["available", "clean", "inspected"])
        )
        count_result = await session.exec(count_query)
        available_count = count_result.one()
        available = available_count > 0

    # Dynamic pricing
    effective_price = rt.base_price
    original_price = None
    if arrival_date and departure_date:
        try:
            from app.services.pricing_service import calculate_effective_price
            effective_price, original_price = await calculate_effective_price(
                session=session,
                room_type_name=rt.name,
                room_type_id=rt.id,
                base_price=rt.base_price,
                check_in=arrival_date,
                check_out=departure_date,
            )
        except Exception as e:
            print(f"Error calculating dynamic price for {rt.name}: {e}")
            effective_price = rt.base_price
            original_price = None

    # Parse JSON fields
    amenities = parse_json_field(rt.amenities, ["Free WiFi", "Air Conditioning", "Smart TV", "Mini Bar"])
    features = parse_json_field(rt.features, ["Modern Design", "Premium Comfort"])
    images = parse_json_field(rt.images)

    # Use local images if no images or if images are external URLs (Unsplash, etc.)
    # Local images are stored in frontend public folder at /images/rooms/
    if not images or (images and any('unsplash' in img or 'http' in img for img in images)):
        images = get_default_images(rt.name, rt.id)

    return RoomTypeRead(
        id=rt.slug,
        roomTypeId=rt.id,  # Numeric ID for channel manager
        name=rt.name,
        slug=rt.slug,
        description=rt.description or f"Beautiful {rt.name} with modern amenities",
        shortDescription=rt.short_description or f"Comfortable {rt.name} accommodation",
        price=effective_price,
        originalPrice=original_price,
        images=images,
        amenities=amenities,
        maxGuests=rt.max_guests,
        bedType=rt.bed_type or "King",
        size=rt.size_sqft or 350,
        view=rt.view_type or "City",
        category=rt.category or "standard",
        features=features,
        rating=rt.rating or 4.5,
        reviewCount=rt.review_count or 0,
        available=available,
        availableRoomCount=available_count,
    )


@router.put("/{room_type_slug}", response_model=RoomTypeRead)
async def update_room_type(
    room_type_slug: str,
    update_data: RoomTypeUpdate,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Update a room type by slug"""
    # Query by slug
    result = await session.exec(
        select(RoomType).where(RoomType.slug == room_type_slug)
    )
    rt = result.first()

    if not rt:
        # Try converting slug to name format
        room_type_name = room_type_slug.replace('-', ' ').title()
        result = await session.exec(
            select(RoomType).where(RoomType.name == room_type_name)
        )
        rt = result.first()

    if not rt:
        raise HTTPException(status_code=404, detail="Room type not found")

    # Update fields that were provided
    update_dict = update_data.model_dump(exclude_unset=True)

    for field, value in update_dict.items():
        if value is not None:
            # Convert lists to JSON strings for storage
            if field in ['amenities', 'features', 'images'] and isinstance(value, list):
                setattr(rt, field, json.dumps(value))
            else:
                setattr(rt, field, value)

    # Commit the changes
    session.add(rt)
    await session.commit()
    await session.refresh(rt)

    # Parse JSON fields for response
    amenities = parse_json_field(rt.amenities, ["Free WiFi", "Air Conditioning", "Smart TV", "Mini Bar"])
    features = parse_json_field(rt.features, ["Modern Design", "Premium Comfort"])
    images = parse_json_field(rt.images)

    # Use local images if no images
    if not images or (images and any('unsplash' in img or 'http' in img for img in images)):
        images = get_default_images(rt.name, rt.id)

    # Count available rooms
    count_query = select(func.count(Room.id)).where(
        Room.room_type_id == rt.id,
        Room.status.in_(["available", "clean", "inspected"])
    )
    count_result = await session.exec(count_query)
    available_count = count_result.one()

    return RoomTypeRead(
        id=rt.slug,
        roomTypeId=rt.id,
        name=rt.name,
        slug=rt.slug,
        description=rt.description or f"Beautiful {rt.name} with modern amenities",
        shortDescription=rt.short_description or f"Comfortable {rt.name} accommodation",
        price=rt.base_price,
        images=images,
        amenities=amenities,
        maxGuests=rt.max_guests,
        bedType=rt.bed_type or "King",
        size=rt.size_sqft or 350,
        view=rt.view_type or "City",
        category=rt.category or "standard",
        features=features,
        rating=rt.rating or 4.5,
        reviewCount=rt.review_count or 0,
        available=available_count > 0,
        availableRoomCount=available_count,
    )


@router.delete("/{room_type_slug}", status_code=200)
async def delete_room_type(
    room_type_slug: str,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Soft-delete a room type by setting is_active=False"""
    from datetime import datetime

    result = await session.exec(
        select(RoomType).where(RoomType.slug == room_type_slug)
    )
    rt = result.first()

    if not rt:
        room_type_name = room_type_slug.replace('-', ' ').title()
        result = await session.exec(
            select(RoomType).where(RoomType.name == room_type_name)
        )
        rt = result.first()

    if not rt:
        raise HTTPException(status_code=404, detail="Room type not found")

    # Check if any active rooms reference this type
    room_count_result = await session.exec(
        select(func.count(Room.id)).where(Room.room_type_id == rt.id)
    )
    room_count = room_count_result.one()
    if room_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete room type '{rt.name}': {room_count} room(s) still assigned to it. Reassign or remove those rooms first."
        )

    rt.is_active = False
    rt.updated_at = datetime.utcnow()
    session.add(rt)
    await session.commit()

    return {"success": True, "message": f"Room type '{rt.name}' has been deactivated."}
