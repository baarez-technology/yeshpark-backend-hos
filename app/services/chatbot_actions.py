"""
Action Executors for Guest AI Chatbot

This module provides the action execution layer with built-in authorization.
Each action validates user permissions before executing database operations.
"""

from typing import Dict, Any, Optional, Tuple, List
from datetime import date, datetime, timedelta
from abc import ABC, abstractmethod
import logging

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, and_, or_

from app.models.reservations import Reservation, Guest
from app.models.inventory import Room, RoomType
from app.models.precheckin import PreCheckIn
from app.models.user import User

logger = logging.getLogger(__name__)


class AuthorizationError(Exception):
    """Raised when user is not authorized for an action"""
    pass


class ActionExecutor(ABC):
    """Base class for all action executors with authorization"""

    def __init__(self, db: AsyncSession, current_user: Optional[User] = None):
        self.db = db
        self.current_user = current_user

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Execute the action and return (success, result_data)"""
        pass

    @abstractmethod
    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate user authorization for this action. Returns (authorized, error_message)"""
        pass

    async def get_guest_for_user(self) -> Optional[Guest]:
        """Get the Guest record linked to the current user"""
        if not self.current_user:
            return None

        result = await self.db.exec(
            select(Guest).where(Guest.email == self.current_user.email)
        )
        return result.first()

    def is_staff_or_admin(self) -> bool:
        """Check if current user is staff or admin"""
        if not self.current_user:
            return False
        return (
            self.current_user.is_superuser or
            self.current_user.role in ["admin", "front_desk", "manager", "staff"]
        )


class RoomSearchAction(ActionExecutor):
    """Search available rooms - public action"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        # Room search is public, no authentication required
        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Search for available rooms"""
        try:
            arrival_date = params.get("arrival_date")
            departure_date = params.get("departure_date")
            adults = params.get("adults", 2)
            children = params.get("children", 0)
            room_type_filter = params.get("room_type")

            # Parse dates if strings
            if isinstance(arrival_date, str):
                arrival_date = date.fromisoformat(arrival_date)
            if isinstance(departure_date, str):
                departure_date = date.fromisoformat(departure_date)

            # Get all room types
            query = select(RoomType).where(RoomType.is_active == True)
            if room_type_filter:
                query = query.where(RoomType.slug == room_type_filter)

            result = await self.db.exec(query)
            room_types = result.all()

            # Get booked room IDs for the date range
            booked_query = select(Reservation.room_id).where(
                and_(
                    Reservation.status.in_(["booked", "confirmed", "checked_in"]),
                    Reservation.arrival_date < departure_date,
                    Reservation.departure_date > arrival_date
                )
            )
            booked_result = await self.db.exec(booked_query)
            booked_room_ids = set(r for r in booked_result.all() if r is not None)

            # Get available rooms for each room type
            available_room_types = []
            total_guests = adults + children

            for rt in room_types:
                # Check if room type can accommodate guests
                if rt.max_guests and rt.max_guests < total_guests:
                    continue

                # Count available rooms of this type
                rooms_query = select(Room).where(
                    and_(
                        Room.room_type_id == rt.id,
                        Room.status.in_(["available", "clean", "inspected"]),
                        Room.id.notin_(booked_room_ids) if booked_room_ids else True
                    )
                )
                rooms_result = await self.db.exec(rooms_query)
                available_rooms = rooms_result.all()

                if available_rooms:
                    nights = (departure_date - arrival_date).days
                    price_per_night = float(rt.base_price) if rt.base_price else 0

                    available_room_types.append({
                        "room_type_id": rt.id,
                        "room_type": rt.name,
                        "slug": rt.slug,
                        "description": rt.description or "",
                        "price_per_night": price_per_night,
                        "total_price": price_per_night * nights,
                        "currency": "INR",
                        "nights": nights,
                        "max_guests": rt.max_guests or 2,
                        "bed_type": rt.bed_type or "King",
                        "size_sqft": rt.size_sqft,
                        "amenities": rt.amenities or [],
                        "images": rt.images or [],
                        "available_count": len(available_rooms),
                    })

            # Sort by price
            available_room_types.sort(key=lambda x: x["price_per_night"])

            return True, {
                "rooms": available_room_types,
                "total": len(available_room_types),
                "arrival_date": arrival_date.isoformat(),
                "departure_date": departure_date.isoformat(),
                "nights": (departure_date - arrival_date).days,
                "guests": {"adults": adults, "children": children},
            }

        except Exception as e:
            logger.error(f"Room search error: {e}")
            return False, {"error": str(e)}


class BookingDetailsAction(ActionExecutor):
    """Get booking details - requires ownership or staff role"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        booking_id = params.get("booking_id")
        booking_number = params.get("booking_number")

        # Staff/admin can view any booking
        if self.is_staff_or_admin():
            return True, ""

        if not self.current_user:
            return False, "Please log in to view booking details"

        # Guest can only view their own bookings
        guest = await self.get_guest_for_user()
        if not guest:
            return False, "Guest profile not found. Please contact the front desk."

        # Find the booking
        if booking_id:
            reservation = await self.db.get(Reservation, booking_id)
        else:
            result = await self.db.exec(
                select(Reservation).where(Reservation.confirmation_code == booking_number)
            )
            reservation = result.first()

        if not reservation:
            return False, "Booking not found"

        if reservation.guest_id != guest.id:
            return False, "You don't have permission to view this booking"

        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Get booking details"""
        try:
            booking_id = params.get("booking_id")
            booking_number = params.get("booking_number")

            if booking_id:
                reservation = await self.db.get(Reservation, booking_id)
            else:
                result = await self.db.exec(
                    select(Reservation).where(Reservation.confirmation_code == booking_number)
                )
                reservation = result.first()

            if not reservation:
                return False, {"error": "Booking not found"}

            # Get related data
            guest = await self.db.get(Guest, reservation.guest_id) if reservation.guest_id else None
            room = await self.db.get(Room, reservation.room_id) if reservation.room_id else None
            room_type = await self.db.get(RoomType, reservation.room_type_id) if reservation.room_type_id else None

            return True, {
                "booking_id": reservation.id,
                "confirmation_code": reservation.confirmation_code,
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else None,
                "guest_email": guest.email if guest else None,
                "guest_phone": guest.phone if guest else None,
                "room_number": room.number if room else None,
                "room_type": room_type.name if room_type else "Standard Room",
                "arrival_date": reservation.arrival_date.isoformat() if reservation.arrival_date else None,
                "departure_date": reservation.departure_date.isoformat() if reservation.departure_date else None,
                "nights": (reservation.departure_date - reservation.arrival_date).days if reservation.arrival_date and reservation.departure_date else None,
                "status": reservation.status,
                "total_amount": float(reservation.total_amount) if reservation.total_amount else 0,
                "currency": reservation.currency or "INR",
                "adults": reservation.adults,
                "children": reservation.children,
                "special_requests": reservation.special_requests,
                "created_at": reservation.created_at.isoformat() if reservation.created_at else None,
            }

        except Exception as e:
            logger.error(f"Booking details error: {e}")
            return False, {"error": str(e)}


class BookingModifyAction(ActionExecutor):
    """Modify booking details - requires ownership or staff role"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        booking_id = params.get("booking_id")

        if not self.current_user:
            return False, "Please log in to modify bookings"

        # Staff/admin can modify any booking
        if self.is_staff_or_admin():
            return True, ""

        # Guest can only modify their own bookings
        guest = await self.get_guest_for_user()
        if not guest:
            return False, "Guest profile not found"

        reservation = await self.db.get(Reservation, booking_id)
        if not reservation:
            return False, "Booking not found"

        if reservation.guest_id != guest.id:
            return False, "You don't have permission to modify this booking"

        # Check booking status
        if reservation.status in ["checked_out", "cancelled", "no_show"]:
            return False, f"Cannot modify a {reservation.status} booking"

        if reservation.status == "checked_in":
            return False, "Cannot modify a checked-in booking. Please contact the front desk."

        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Modify booking"""
        try:
            booking_id = params.get("booking_id")
            reservation = await self.db.get(Reservation, booking_id)

            if not reservation:
                return False, {"error": "Booking not found"}

            updates = {}
            modified_fields = []

            # Handle date changes
            if "arrival_date" in params:
                new_arrival = params["arrival_date"]
                if isinstance(new_arrival, str):
                    new_arrival = date.fromisoformat(new_arrival)
                updates["arrival_date"] = new_arrival
                modified_fields.append("check-in date")

            if "departure_date" in params:
                new_departure = params["departure_date"]
                if isinstance(new_departure, str):
                    new_departure = date.fromisoformat(new_departure)
                updates["departure_date"] = new_departure
                modified_fields.append("check-out date")

            # Handle guest count changes
            if "adults" in params:
                updates["adults"] = params["adults"]
                modified_fields.append("adult count")

            if "children" in params:
                updates["children"] = params["children"]
                modified_fields.append("children count")

            # Handle special requests
            if "special_requests" in params:
                updates["special_requests"] = params["special_requests"]
                modified_fields.append("special requests")

            if not updates:
                return False, {"error": "No updates provided"}

            # Apply updates
            for key, value in updates.items():
                setattr(reservation, key, value)

            reservation.updated_at = datetime.utcnow()
            await self.db.commit()

            return True, {
                "message": f"Booking updated successfully. Modified: {', '.join(modified_fields)}",
                "booking_id": booking_id,
                "confirmation_code": reservation.confirmation_code,
                "modified_fields": modified_fields,
            }

        except Exception as e:
            logger.error(f"Booking modify error: {e}")
            await self.db.rollback()
            return False, {"error": str(e)}


class BookingCancelAction(ActionExecutor):
    """Cancel a booking - requires ownership or staff role"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        booking_id = params.get("booking_id")

        if not self.current_user:
            return False, "Please log in to cancel bookings"

        # Staff/admin can cancel any booking
        if self.is_staff_or_admin():
            return True, ""

        # Guest can only cancel their own bookings
        guest = await self.get_guest_for_user()
        if not guest:
            return False, "Guest profile not found"

        reservation = await self.db.get(Reservation, booking_id)
        if not reservation:
            return False, "Booking not found"

        if reservation.guest_id != guest.id:
            return False, "You don't have permission to cancel this booking"

        # Check booking status
        if reservation.status in ["checked_in", "checked_out", "cancelled", "no_show"]:
            return False, f"Cannot cancel a {reservation.status} booking"

        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Cancel booking"""
        try:
            booking_id = params.get("booking_id")
            reason = params.get("reason", "Guest requested cancellation")

            reservation = await self.db.get(Reservation, booking_id)
            if not reservation:
                return False, {"error": "Booking not found"}

            # Update status
            reservation.status = "cancelled"
            reservation.cancellation_reason = reason
            reservation.cancelled_at = datetime.utcnow()
            reservation.updated_at = datetime.utcnow()

            await self.db.commit()

            return True, {
                "message": "Booking cancelled successfully",
                "booking_id": booking_id,
                "confirmation_code": reservation.confirmation_code,
                "status": "cancelled",
            }

        except Exception as e:
            logger.error(f"Booking cancel error: {e}")
            await self.db.rollback()
            return False, {"error": str(e)}


class BookingCreateAction(ActionExecutor):
    """Create a new booking - requires authentication"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        # Creating a booking requires authentication (or guest info)
        if not self.current_user and not params.get("guest_info"):
            return False, "Please log in or provide guest information to create a booking"
        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Create a new booking"""
        try:
            from app.services.reservation_service import generate_confirmation_code

            arrival_date = params.get("arrival_date")
            departure_date = params.get("departure_date")
            room_type_id = params.get("room_type_id")
            adults = params.get("adults", 2)
            children = params.get("children", 0)
            guest_info = params.get("guest_info", {})
            special_requests = params.get("special_requests", "")

            # Parse dates
            if isinstance(arrival_date, str):
                arrival_date = date.fromisoformat(arrival_date)
            if isinstance(departure_date, str):
                departure_date = date.fromisoformat(departure_date)

            # Get or create guest
            guest = None
            if self.current_user:
                guest = await self.get_guest_for_user()

            if not guest and guest_info:
                # Create new guest
                guest = Guest(
                    first_name=guest_info.get("first_name", ""),
                    last_name=guest_info.get("last_name", ""),
                    email=guest_info.get("email", ""),
                    phone=guest_info.get("phone", ""),
                    country=guest_info.get("country", ""),
                    status="active",
                    member_since=datetime.utcnow(),
                )
                if self.current_user:
                    guest.user_id = self.current_user.id
                self.db.add(guest)
                await self.db.flush()

            if not guest:
                return False, {"error": "Guest information required"}

            # Get room type
            room_type = await self.db.get(RoomType, room_type_id)
            if not room_type:
                return False, {"error": "Invalid room type"}

            # Calculate pricing using GST slab-based rates
            from app.core.tax import calculate_booking_taxes
            nights = (departure_date - arrival_date).days
            base_price = float(room_type.base_price) if room_type.base_price else 0
            tax_calc = calculate_booking_taxes(base_price, nights)
            subtotal = tax_calc["calculated_base"]
            tax = tax_calc["taxes"]
            service_fee = tax_calc["service_fee"]
            total = tax_calc["total_price"]

            # Generate confirmation code
            confirmation_code = generate_confirmation_code()

            # Create reservation
            reservation = Reservation(
                confirmation_code=confirmation_code,
                guest_id=guest.id,
                room_type_id=room_type_id,
                arrival_date=arrival_date,
                departure_date=departure_date,
                adults=adults,
                children=children,
                status="booked",
                total_amount=total,
                currency="INR",
                special_requests=special_requests,
                booking_source="chatbot",
                created_at=datetime.utcnow(),
            )
            self.db.add(reservation)
            await self.db.commit()

            return True, {
                "message": "Booking created successfully!",
                "booking_id": reservation.id,
                "confirmation_code": confirmation_code,
                "room_type": room_type.name,
                "arrival_date": arrival_date.isoformat(),
                "departure_date": departure_date.isoformat(),
                "nights": nights,
                "total_amount": total,
                "currency": "INR",
                "status": "booked",
            }

        except Exception as e:
            logger.error(f"Booking create error: {e}")
            await self.db.rollback()
            return False, {"error": str(e)}


class ProfileViewAction(ActionExecutor):
    """View guest profile - requires authentication"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        if not self.current_user:
            return False, "Please log in to view your profile"
        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Get guest profile"""
        try:
            guest = await self.get_guest_for_user()
            if not guest:
                return False, {"error": "Profile not found. Please contact the front desk."}

            return True, {
                "guest_id": guest.id,
                "first_name": guest.first_name,
                "last_name": guest.last_name,
                "email": guest.email,
                "phone": guest.phone,
                "country": guest.country,
                "address": guest.address,
                "city": guest.city,
                "vip_status": guest.vip_status,
                "loyalty_points": guest.loyalty_points or 0,
                "loyalty_tier": guest.loyalty_tier,
                "total_bookings": guest.total_bookings or 0,
                "total_spent": float(guest.total_spent) if guest.total_spent else 0,
                "total_nights": guest.total_nights or 0,
                "preferences": guest.preferences or {},
                "member_since": guest.member_since.isoformat() if guest.member_since else None,
                "last_visit": guest.last_visit.isoformat() if guest.last_visit else None,
            }

        except Exception as e:
            logger.error(f"Profile view error: {e}")
            return False, {"error": str(e)}


class ProfileUpdateAction(ActionExecutor):
    """Update guest profile - requires authentication"""

    # Fields that guests can update themselves
    ALLOWED_FIELDS = ["phone", "address", "city", "country", "preferences"]

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        if not self.current_user:
            return False, "Please log in to update your profile"
        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Update guest profile"""
        try:
            guest = await self.get_guest_for_user()
            if not guest:
                return False, {"error": "Profile not found"}

            updated_fields = []

            for field in self.ALLOWED_FIELDS:
                if field in params:
                    setattr(guest, field, params[field])
                    updated_fields.append(field)

            if not updated_fields:
                return False, {"error": "No valid fields to update"}

            guest.updated_at = datetime.utcnow()
            await self.db.commit()

            return True, {
                "message": f"Profile updated successfully. Updated: {', '.join(updated_fields)}",
                "updated_fields": updated_fields,
            }

        except Exception as e:
            logger.error(f"Profile update error: {e}")
            await self.db.rollback()
            return False, {"error": str(e)}


class MyBookingsAction(ActionExecutor):
    """Get user's bookings - requires authentication"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        if not self.current_user:
            return False, "Please log in to view your bookings"
        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Get all bookings for the current user"""
        try:
            guest = await self.get_guest_for_user()
            if not guest:
                return True, {"bookings": [], "message": "No bookings found"}

            status_filter = params.get("status")  # "upcoming", "past", "all"

            query = select(Reservation).where(Reservation.guest_id == guest.id)

            today = date.today()
            if status_filter == "upcoming":
                query = query.where(
                    and_(
                        Reservation.arrival_date >= today,
                        Reservation.status.in_(["booked", "confirmed"])
                    )
                )
            elif status_filter == "past":
                query = query.where(
                    or_(
                        Reservation.departure_date < today,
                        Reservation.status.in_(["checked_out", "cancelled", "no_show"])
                    )
                )

            query = query.order_by(Reservation.arrival_date.desc())
            result = await self.db.exec(query)
            reservations = result.all()

            bookings = []
            for res in reservations:
                room_type = await self.db.get(RoomType, res.room_type_id) if res.room_type_id else None
                room = await self.db.get(Room, res.room_id) if res.room_id else None

                bookings.append({
                    "booking_id": res.id,
                    "confirmation_code": res.confirmation_code,
                    "room_type": room_type.name if room_type else "Standard Room",
                    "room_number": room.number if room else None,
                    "arrival_date": res.arrival_date.isoformat() if res.arrival_date else None,
                    "departure_date": res.departure_date.isoformat() if res.departure_date else None,
                    "status": res.status,
                    "total_amount": float(res.total_amount) if res.total_amount else 0,
                })

            return True, {
                "bookings": bookings,
                "total": len(bookings),
            }

        except Exception as e:
            logger.error(f"My bookings error: {e}")
            return False, {"error": str(e)}


class PreCheckinVerifyAction(ActionExecutor):
    """Verify booking for pre-checkin - can be done with booking number"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        # Pre-checkin verification can be done with just booking number
        if not params.get("booking_number"):
            return False, "Booking confirmation number required"
        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Verify booking for pre-checkin"""
        try:
            booking_number = params.get("booking_number")
            guest_name = params.get("guest_name")  # Optional verification

            result = await self.db.exec(
                select(Reservation).where(Reservation.confirmation_code == booking_number)
            )
            reservation = result.first()

            if not reservation:
                return False, {"error": "Booking not found. Please check your confirmation number."}

            # Get guest info
            guest = await self.db.get(Guest, reservation.guest_id) if reservation.guest_id else None

            # Validate name if provided
            if guest_name and guest:
                full_name = f"{guest.first_name} {guest.last_name}".lower()
                if guest_name.lower() not in full_name and full_name not in guest_name.lower():
                    return False, {"error": "Guest name does not match booking"}

            # Check if already checked in
            if reservation.status == "checked_in":
                return False, {"error": "This booking has already been checked in"}

            if reservation.status in ["checked_out", "cancelled", "no_show"]:
                return False, {"error": f"This booking is {reservation.status}"}

            # Check dates
            today = date.today()
            if reservation.arrival_date and reservation.arrival_date > today + timedelta(days=7):
                return False, {"error": "Pre-check-in is only available within 7 days of arrival"}

            room_type = await self.db.get(RoomType, reservation.room_type_id) if reservation.room_type_id else None

            return True, {
                "valid": True,
                "reservation_id": reservation.id,
                "confirmation_code": reservation.confirmation_code,
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else None,
                "guest_email": guest.email if guest else None,
                "guest_phone": guest.phone if guest else None,
                "room_type": room_type.name if room_type else "Standard Room",
                "arrival_date": reservation.arrival_date.isoformat() if reservation.arrival_date else None,
                "departure_date": reservation.departure_date.isoformat() if reservation.departure_date else None,
                "nights": (reservation.departure_date - reservation.arrival_date).days if reservation.arrival_date and reservation.departure_date else None,
                "status": reservation.status,
            }

        except Exception as e:
            logger.error(f"Pre-checkin verify error: {e}")
            return False, {"error": str(e)}


class PreCheckinCreateAction(ActionExecutor):
    """Create pre-checkin record - requires verified booking"""

    async def validate_authorization(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        reservation_id = params.get("reservation_id")
        if not reservation_id:
            return False, "Reservation ID required"

        # If user is logged in, verify they own the booking
        if self.current_user:
            guest = await self.get_guest_for_user()
            if guest:
                reservation = await self.db.get(Reservation, reservation_id)
                if reservation and reservation.guest_id != guest.id:
                    if not self.is_staff_or_admin():
                        return False, "You don't have permission for this booking"

        return True, ""

    async def execute(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Create or update pre-checkin record"""
        try:
            reservation_id = params.get("reservation_id")

            # Check if pre-checkin already exists
            result = await self.db.exec(
                select(PreCheckIn).where(PreCheckIn.reservation_id == reservation_id)
            )
            precheckin = result.first()

            if not precheckin:
                reservation = await self.db.get(Reservation, reservation_id)
                if not reservation:
                    return False, {"error": "Reservation not found"}

                precheckin = PreCheckIn(
                    reservation_id=reservation_id,
                    guest_id=reservation.guest_id,
                    status="in_progress",
                    created_at=datetime.utcnow(),
                )
                self.db.add(precheckin)
                await self.db.flush()

            # Update fields if provided
            update_fields = [
                "email", "phone", "address", "city", "zip_code", "country",
                "floor_preference", "view_preference", "bed_type_preference",
                "quietness_preference", "arrival_time", "flight_number",
                "purpose", "transportation_needed", "pillow_type", "temperature",
                "minibar_preferences", "dietary_restrictions", "special_requests",
                "early_check_in", "late_check_out"
            ]

            for field in update_fields:
                if field in params:
                    setattr(precheckin, field, params[field])

            precheckin.updated_at = datetime.utcnow()
            await self.db.commit()

            return True, {
                "precheckin_id": precheckin.id,
                "reservation_id": reservation_id,
                "status": precheckin.status,
                "message": "Pre-check-in information saved",
            }

        except Exception as e:
            logger.error(f"Pre-checkin create error: {e}")
            await self.db.rollback()
            return False, {"error": str(e)}


# Action registry for easy access
ACTION_REGISTRY = {
    "room_search": RoomSearchAction,
    "booking_details": BookingDetailsAction,
    "booking_modify": BookingModifyAction,
    "booking_cancel": BookingCancelAction,
    "booking_create": BookingCreateAction,
    "profile_view": ProfileViewAction,
    "profile_update": ProfileUpdateAction,
    "my_bookings": MyBookingsAction,
    "precheckin_verify": PreCheckinVerifyAction,
    "precheckin_create": PreCheckinCreateAction,
}


async def execute_action(
    action_name: str,
    params: Dict[str, Any],
    db: AsyncSession,
    current_user: Optional[User] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute an action with authorization check.

    Args:
        action_name: Name of the action to execute
        params: Parameters for the action
        db: Database session
        current_user: Currently authenticated user (optional)

    Returns:
        Tuple of (success, result_data)
    """
    if action_name not in ACTION_REGISTRY:
        return False, {"error": f"Unknown action: {action_name}"}

    executor_class = ACTION_REGISTRY[action_name]
    executor = executor_class(db, current_user)

    # Authorization check
    try:
        authorized, error_msg = await executor.validate_authorization(params)
        if not authorized:
            return False, {"error": error_msg, "unauthorized": True}
    except Exception as e:
        logger.error(f"Authorization check failed: {e}")
        return False, {"error": "Authorization check failed", "unauthorized": True}

    # Execute action
    try:
        return await executor.execute(params)
    except Exception as e:
        logger.error(f"Action execution failed: {e}")
        return False, {"error": str(e)}
