"""
Booking Tools for AGI Guest Assistant
Handles all booking-related operations
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.booking_tools")


def parse_flexible_date(date_str: str) -> Tuple[Optional[date], Optional[str]]:
    """
    Parse dates in various formats.

    Supported formats:
    - YYYY-MM-DD (2025-12-08)
    - DD-MMM-YY (8-dec-25, 08-Dec-2025)
    - MMM DD (Dec 8, December 8)
    - DD/MM/YY or DD/MM/YYYY
    - "today", "tomorrow", "next week"

    Returns:
        Tuple of (parsed_date, error_message)
    """
    if not date_str:
        return None, "No date provided"

    date_str = date_str.strip().lower()
    today = date.today()

    # Handle relative dates
    if date_str in ["today", "tonight"]:
        return today, None
    if date_str == "tomorrow":
        return today + timedelta(days=1), None
    if date_str in ["next week", "in a week"]:
        return today + timedelta(days=7), None

    # Clean the string
    date_str_clean = date_str.replace(",", " ").strip()

    # Month name mapping
    months = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12
    }

    try:
        # Try standard YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str_clean):
            return datetime.strptime(date_str_clean, "%Y-%m-%d").date(), None

        # Try DD-MMM-YY or DD-MMM-YYYY (e.g., 8-dec-25, 08-dec-2025)
        match = re.match(r"^(\d{1,2})[-/](\w{3,9})[-/](\d{2,4})$", date_str_clean)
        if match:
            day = int(match.group(1))
            month_str = match.group(2).lower()
            year_str = match.group(3)

            if month_str in months:
                month = months[month_str]
                year = int(year_str)
                if year < 100:
                    year = 2000 + year  # Assume 20xx for 2-digit years

                return date(year, month, day), None

        # Try MMM DD YYYY or MMM DD (e.g., Dec 8 2025, December 8)
        match = re.match(r"^(\w{3,9})\s+(\d{1,2})(?:\s+(\d{4}))?$", date_str_clean)
        if match:
            month_str = match.group(1).lower()
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else today.year

            if month_str in months:
                month = months[month_str]
                # If the date is in the past this year, assume next year
                result_date = date(year, month, day)
                if result_date < today and not match.group(3):
                    result_date = date(year + 1, month, day)
                return result_date, None

        # Try DD/MM/YY or DD/MM/YYYY
        match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", date_str_clean)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3))
            if year < 100:
                year = 2000 + year

            return date(year, month, day), None

        # Try DD MMM (e.g., "8 dec", "8 december")
        match = re.match(r"^(\d{1,2})\s+(\w{3,9})$", date_str_clean)
        if match:
            day = int(match.group(1))
            month_str = match.group(2).lower()

            if month_str in months:
                month = months[month_str]
                year = today.year
                result_date = date(year, month, day)
                if result_date < today:
                    result_date = date(year + 1, month, day)
                return result_date, None

    except (ValueError, TypeError) as e:
        logger.warning(f"Date parsing error for '{date_str}': {e}")

    return None, f"Could not parse date '{date_str}'. Please use format like 'Dec 8 2025' or '2025-12-08'."


class BookingTools:
    """Tools for booking management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def lookup_booking(
        self,
        confirmation_code: Optional[str] = None,
        guest_email: Optional[str] = None,
        guest_phone: Optional[str] = None,
        guest_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Look up a booking by confirmation code or guest details.

        Args:
            confirmation_code: Booking confirmation code
            guest_email: Guest email address
            guest_phone: Guest phone number
            guest_name: Guest name

        Returns:
            Booking information
        """
        from app.models.reservations import Booking, Guest, Reservation
        from app.models.inventory import Room, RoomType

        try:
            booking = None
            guest = None

            # Search by confirmation code first (most common)
            if confirmation_code:
                clean_code = confirmation_code.strip().upper()

                # Try Booking table first
                result = await self.db.execute(
                    select(Booking).where(
                        or_(
                            Booking.confirmation_code == clean_code,
                            Booking.booking_number == clean_code,
                            Booking.confirmation_code.ilike(f"%{clean_code}%"),
                            Booking.booking_number.ilike(f"%{clean_code}%")
                        )
                    )
                )
                booking = result.scalars().first()

                # Try Reservation table if not found
                if not booking:
                    result = await self.db.execute(
                        select(Reservation).where(
                            or_(
                                Reservation.confirmation_code == clean_code,
                                Reservation.confirmation_code.ilike(f"%{clean_code}%")
                            )
                        )
                    )
                    reservation = result.scalars().first()
                    if reservation:
                        # Convert reservation to booking-like response
                        guest_result = await self.db.execute(
                            select(Guest).where(Guest.id == reservation.guest_id)
                        )
                        guest = guest_result.scalars().first()

                        room_number = None
                        room_type_name = None
                        if reservation.room_id:
                            room_result = await self.db.execute(
                                select(Room).where(Room.id == reservation.room_id)
                            )
                            room = room_result.scalars().first()
                            if room:
                                room_number = room.number

                        return {
                            "success": True,
                            "found": True,
                            "booking": {
                                "id": reservation.id,
                                "confirmation_code": reservation.confirmation_code,
                                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
                                "guest_id": reservation.guest_id,
                                "room_number": room_number,
                                "room_type": room_type_name,
                                "arrival_date": reservation.arrival_date.isoformat(),
                                "departure_date": reservation.departure_date.isoformat(),
                                "nights": (reservation.departure_date - reservation.arrival_date).days,
                                "status": reservation.status,
                                "is_checked_in": reservation.status == "checked_in",
                                "total_guests": reservation.adults + (reservation.children or 0),
                                "special_requests": reservation.special_requests
                            },
                            "message": f"Found booking {reservation.confirmation_code} for {guest.first_name if guest else 'Guest'}."
                        }

            # Search by guest details if no confirmation code
            if not booking and (guest_email or guest_phone or guest_name):
                # Find guest first
                guest_query = select(Guest)
                conditions = []
                if guest_email:
                    conditions.append(Guest.email.ilike(f"%{guest_email}%"))
                if guest_phone:
                    conditions.append(Guest.phone.ilike(f"%{guest_phone}%"))
                if guest_name:
                    name_parts = guest_name.split()
                    if len(name_parts) >= 2:
                        conditions.append(
                            and_(
                                Guest.first_name.ilike(f"%{name_parts[0]}%"),
                                Guest.last_name.ilike(f"%{name_parts[-1]}%")
                            )
                        )
                    else:
                        conditions.append(
                            or_(
                                Guest.first_name.ilike(f"%{guest_name}%"),
                                Guest.last_name.ilike(f"%{guest_name}%")
                            )
                        )

                if conditions:
                    guest_result = await self.db.execute(
                        guest_query.where(or_(*conditions))
                    )
                    guest = guest_result.scalars().first()

                    if guest:
                        # Find their active booking
                        today = date.today()
                        result = await self.db.execute(
                            select(Booking).where(
                                and_(
                                    Booking.guest_id == guest.id,
                                    Booking.departure_date >= today
                                )
                            ).order_by(Booking.arrival_date)
                        )
                        booking = result.scalars().first()

            if booking:
                # Get guest info
                if not guest and booking.guest_id:
                    guest_result = await self.db.execute(
                        select(Guest).where(Guest.id == booking.guest_id)
                    )
                    guest = guest_result.scalars().first()

                # Get room info
                room_number = None
                if booking.room_id:
                    room_result = await self.db.execute(
                        select(Room).where(Room.id == booking.room_id)
                    )
                    room = room_result.scalars().first()
                    if room:
                        room_number = room.number

                # Get room type
                room_type_name = None
                if booking.room_type_id:
                    rt_result = await self.db.execute(
                        select(RoomType).where(RoomType.id == booking.room_type_id)
                    )
                    room_type = rt_result.scalars().first()
                    if room_type:
                        room_type_name = room_type.name

                return {
                    "success": True,
                    "found": True,
                    "booking": {
                        "id": booking.id,
                        "confirmation_code": booking.confirmation_code,
                        "booking_number": booking.booking_number,
                        "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
                        "guest_id": booking.guest_id,
                        "room_number": room_number,
                        "room_type": room_type_name,
                        "arrival_date": booking.arrival_date.isoformat(),
                        "departure_date": booking.departure_date.isoformat(),
                        "nights": (booking.departure_date - booking.arrival_date).days,
                        "status": booking.status,
                        "is_checked_in": booking.status == "checked_in",
                        "total_guests": booking.adults + (booking.children or 0),
                        "rate": float(booking.total_price) if booking.total_price else None,
                        "special_requests": booking.special_requests
                    },
                    "message": f"Found booking {booking.confirmation_code} for {guest.first_name if guest else 'Guest'}."
                }

            return {
                "success": True,
                "found": False,
                "message": "No booking found with the provided information. Please verify your confirmation code or contact the front desk."
            }

        except Exception as e:
            logger.error(f"Error looking up booking: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to look up booking. Please contact the front desk."
            }

    async def get_booking_details(
        self,
        booking_id: int
    ) -> Dict[str, Any]:
        """
        Get detailed booking information.

        Args:
            booking_id: Booking ID

        Returns:
            Detailed booking information
        """
        from app.models.reservations import Booking, Guest
        from app.models.inventory import Room, RoomType

        try:
            result = await self.db.execute(
                select(Booking).where(Booking.id == booking_id)
            )
            booking = result.scalars().first()

            if not booking:
                return {
                    "success": False,
                    "message": "Booking not found."
                }

            # Get all related info
            guest = None
            if booking.guest_id:
                guest_result = await self.db.execute(
                    select(Guest).where(Guest.id == booking.guest_id)
                )
                guest = guest_result.scalars().first()

            room = None
            if booking.room_id:
                room_result = await self.db.execute(
                    select(Room).where(Room.id == booking.room_id)
                )
                room = room_result.scalars().first()

            room_type = None
            if booking.room_type_id:
                rt_result = await self.db.execute(
                    select(RoomType).where(RoomType.id == booking.room_type_id)
                )
                room_type = rt_result.scalars().first()

            nights = (booking.departure_date - booking.arrival_date).days

            return {
                "success": True,
                "booking": {
                    "id": booking.id,
                    "confirmation_code": booking.confirmation_code,
                    "booking_number": booking.booking_number,
                    "status": booking.status,
                    "guest": {
                        "id": guest.id if guest else None,
                        "name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
                        "email": guest.email if guest else None,
                        "phone": guest.phone if guest else None
                    },
                    "room": {
                        "number": room.number if room else None,
                        "floor": room.floor if room else None,
                        "type": room_type.name if room_type else None,
                        "description": room_type.description if room_type else None
                    },
                    "dates": {
                        "arrival": booking.arrival_date.isoformat(),
                        "departure": booking.departure_date.isoformat(),
                        "nights": nights,
                        "check_in_time": "3:00 PM",
                        "check_out_time": "11:00 AM"
                    },
                    "guests": {
                        "adults": booking.adults,
                        "children": booking.children or 0,
                        "total": booking.adults + (booking.children or 0)
                    },
                    "rate": {
                        "per_night": float(booking.base_price) / nights if booking.base_price and nights > 0 else None,
                        "total_room": float(booking.base_price) if booking.base_price else None
                    },
                    "special_requests": booking.special_requests,
                    "created_at": booking.created_at.isoformat() if booking.created_at else None
                }
            }

        except Exception as e:
            logger.error(f"Error getting booking details: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to retrieve booking details."
            }

    async def extend_stay(
        self,
        room_number: str,
        additional_nights: int,
        booking_id: Optional[int] = None,
        guest_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Request to extend stay.

        Args:
            room_number: Guest's room number
            additional_nights: Number of additional nights
            booking_id: Booking ID
            guest_id: Guest ID

        Returns:
            Extension request result
        """
        from app.services.staff_scheduling_service import get_scheduling_service
        from app.models.reservations import Booking
        from app.models.inventory import Room

        try:
            # Get booking
            if not booking_id:
                room_result = await self.db.execute(
                    select(Room).where(Room.number == room_number)
                )
                room = room_result.scalars().first()
                if room:
                    booking_result = await self.db.execute(
                        select(Booking).where(
                            and_(
                                Booking.room_id == room.id,
                                Booking.status.in_(["confirmed", "checked_in"])
                            )
                        ).order_by(Booking.created_at.desc())
                    )
                    booking = booking_result.scalars().first()
                    if booking:
                        booking_id = booking.id

            if not booking_id:
                return {
                    "success": False,
                    "message": "Unable to find your booking. Please contact the front desk."
                }

            booking_result = await self.db.execute(
                select(Booking).where(Booking.id == booking_id)
            )
            booking = booking_result.scalars().first()

            if not booking:
                return {
                    "success": False,
                    "message": "Booking not found."
                }

            new_departure = booking.departure_date + timedelta(days=additional_nights)
            # Calculate per-night rate from base_price / nights
            booking_nights = (booking.departure_date - booking.arrival_date).days
            per_night_rate = float(booking.base_price) / booking_nights if booking.base_price and booking_nights > 0 else 200
            estimated_cost = per_night_rate * additional_nights

            # Create request task
            scheduling_service = get_scheduling_service(self.db)

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Stay Extension Request - Room {room_number}",
                description=f"""Stay Extension Request:
Current checkout: {booking.departure_date.isoformat()}
Requested new checkout: {new_departure.isoformat()}
Additional nights: {additional_nights}
Estimated additional cost: ${estimated_cost:.2f}""",
                priority="high",
                room_number=room_number,
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "request_id": f"EXT-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "current_checkout": booking.departure_date.isoformat(),
                "requested_checkout": new_departure.isoformat(),
                "additional_nights": additional_nights,
                "estimated_cost": estimated_cost,
                "status": "pending_availability",
                "message": f"Your request to extend your stay by {additional_nights} night(s) until {new_departure.strftime('%B %d, %Y')} has been submitted. Our front desk will confirm availability and contact you shortly. Estimated additional cost: ${estimated_cost:.2f}"
            }

        except Exception as e:
            logger.error(f"Error requesting stay extension: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process extension request. Please contact the front desk."
            }

    async def request_early_checkin(
        self,
        confirmation_code: str,
        requested_time: str,
        guest_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Request early check-in.

        Args:
            confirmation_code: Booking confirmation code
            requested_time: Requested check-in time
            guest_id: Guest ID

        Returns:
            Early check-in request result
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            # Lookup booking
            booking_result = await self.lookup_booking(confirmation_code=confirmation_code)

            if not booking_result.get("found"):
                return {
                    "success": False,
                    "message": "Booking not found. Please verify your confirmation code."
                }

            booking = booking_result["booking"]

            # Check if arrival is today or tomorrow
            arrival = datetime.fromisoformat(booking["arrival_date"]).date()
            today = date.today()
            tomorrow = today + timedelta(days=1)

            if arrival not in [today, tomorrow]:
                return {
                    "success": False,
                    "message": f"Early check-in requests can only be made for arrivals today or tomorrow. Your arrival date is {arrival.strftime('%B %d, %Y')}."
                }

            scheduling_service = get_scheduling_service(self.db)

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Early Check-in Request - {confirmation_code}",
                description=f"""Early Check-in Request:
Confirmation: {confirmation_code}
Guest: {booking['guest_name']}
Arrival Date: {booking['arrival_date']}
Requested Time: {requested_time}
Standard check-in: 3:00 PM""",
                priority="normal",
                booking_id=booking["id"],
                guest_id=guest_id
            )

            return {
                "success": True,
                "request_id": f"ECI-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "confirmation_code": confirmation_code,
                "arrival_date": booking["arrival_date"],
                "requested_time": requested_time,
                "standard_checkin": "3:00 PM",
                "status": "pending_confirmation",
                "fee_note": "Early check-in (before 12 PM) may be subject to availability and a fee of $50",
                "message": f"Your early check-in request for {requested_time} has been submitted. We will confirm availability and notify you. Standard check-in is 3:00 PM."
            }

        except Exception as e:
            logger.error(f"Error requesting early check-in: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process request. Please contact the front desk."
            }

    async def modify_booking(
        self,
        booking_id: int,
        modifications: Dict[str, Any],
        guest_id: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request booking modification.

        Args:
            booking_id: Booking ID
            modifications: Dictionary of requested changes
            guest_id: Guest ID
            reason: Reason for modification

        Returns:
            Modification request result
        """
        from app.services.staff_scheduling_service import get_scheduling_service
        from app.models.reservations import Booking

        try:
            result = await self.db.execute(
                select(Booking).where(Booking.id == booking_id)
            )
            booking = result.scalars().first()

            if not booking:
                return {
                    "success": False,
                    "message": "Booking not found."
                }

            scheduling_service = get_scheduling_service(self.db)

            mod_details = "\n".join([f"- {k}: {v}" for k, v in modifications.items()])

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Booking Modification - {booking.confirmation_code}",
                description=f"""Booking Modification Request:
Confirmation: {booking.confirmation_code}
Requested Changes:
{mod_details}
Reason: {reason or 'Not specified'}""",
                priority="high",
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "request_id": f"MOD-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "confirmation_code": booking.confirmation_code,
                "requested_modifications": modifications,
                "status": "pending_review",
                "message": f"Your modification request for booking {booking.confirmation_code} has been submitted. Our team will review and contact you within 2 hours to confirm availability and any rate adjustments."
            }

        except Exception as e:
            logger.error(f"Error requesting booking modification: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process modification. Please contact the front desk."
            }

    async def cancel_booking(
        self,
        confirmation_code: str,
        reason: str,
        guest_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Request booking cancellation.

        Args:
            confirmation_code: Booking confirmation code
            reason: Cancellation reason
            guest_id: Guest ID

        Returns:
            Cancellation request result
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            # Lookup booking
            booking_result = await self.lookup_booking(confirmation_code=confirmation_code)

            if not booking_result.get("found"):
                return {
                    "success": False,
                    "message": "Booking not found. Please verify your confirmation code."
                }

            booking = booking_result["booking"]

            # Check cancellation policy
            arrival = datetime.fromisoformat(booking["arrival_date"]).date()
            days_until_arrival = (arrival - date.today()).days

            cancellation_fee = 0
            if days_until_arrival < 1:
                cancellation_fee = 100  # Full night charge for same-day
                policy_note = "Same-day cancellation: Full night charge applies"
            elif days_until_arrival < 3:
                cancellation_fee = 50  # 50% charge for last-minute
                policy_note = "Cancellation within 3 days: 50% of first night applies"
            else:
                policy_note = "Free cancellation (more than 3 days before arrival)"

            scheduling_service = get_scheduling_service(self.db)

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Cancellation Request - {confirmation_code}",
                description=f"""Cancellation Request:
Confirmation: {confirmation_code}
Guest: {booking['guest_name']}
Arrival Date: {booking['arrival_date']}
Days until arrival: {days_until_arrival}
Reason: {reason}
Policy: {policy_note}
Estimated fee: ${cancellation_fee}""",
                priority="high",
                booking_id=booking["id"],
                guest_id=guest_id
            )

            return {
                "success": True,
                "request_id": f"CXL-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "confirmation_code": confirmation_code,
                "arrival_date": booking["arrival_date"],
                "cancellation_fee": cancellation_fee,
                "policy": policy_note,
                "status": "pending_confirmation",
                "message": f"Your cancellation request for booking {confirmation_code} has been received. {policy_note}. Our team will confirm the cancellation shortly."
            }

        except Exception as e:
            logger.error(f"Error requesting cancellation: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process cancellation. Please contact the front desk."
            }

    async def add_special_request(
        self,
        room_number: str,
        request_type: str,
        request_details: str,
        booking_id: Optional[int] = None,
        guest_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Add special request to booking.

        Args:
            room_number: Guest's room number
            request_type: Type of request (dietary, accessibility, celebration, preference)
            request_details: Details of the request
            booking_id: Booking ID
            guest_id: Guest ID

        Returns:
            Request confirmation
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            scheduling_service = get_scheduling_service(self.db)

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="concierge",
                title=f"Special Request - {request_type.title()} - Room {room_number}",
                description=f"Request Type: {request_type}\nDetails: {request_details}",
                priority="normal",
                room_number=room_number,
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "request_id": f"SR-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "request_type": request_type,
                "details": request_details,
                "status": "noted",
                "message": f"Your {request_type} request has been noted and added to your booking. Our team will ensure it's accommodated."
            }

        except Exception as e:
            logger.error(f"Error adding special request: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to add request. Please contact the front desk."
            }

    # ==================== ROOM BROWSING METHODS ====================

    async def browse_all_room_types(
        self,
        room_type_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Browse all room types with details and base prices.
        No dates required - just shows what's available at the hotel.

        Args:
            room_type_name: Optional specific room type to get details for

        Returns:
            List of room types with details and pricing
        """
        from app.models.inventory import RoomType, Room
        from sqlalchemy import func

        try:
            if room_type_name:
                # Get specific room type details
                result = await self.db.execute(
                    select(RoomType).where(
                        and_(
                            RoomType.is_active == True,
                            or_(
                                RoomType.name.ilike(f"%{room_type_name}%"),
                                RoomType.slug.ilike(f"%{room_type_name.lower().replace(' ', '-')}%")
                            )
                        )
                    )
                )
                room_type = result.scalars().first()

                if not room_type:
                    return {
                        "success": False,
                        "message": f"Room type '{room_type_name}' not found. Let me show you all available room types instead."
                    }

                # Count rooms of this type (using status instead of is_active)
                room_count_result = await self.db.execute(
                    select(func.count(Room.id)).where(
                        and_(Room.room_type_id == room_type.id, Room.status != "out_of_service")
                    )
                )
                room_count = room_count_result.scalar() or 0

                return {
                    "success": True,
                    "room_type": {
                        "id": room_type.id,
                        "name": room_type.name,
                        "slug": room_type.slug,
                        "description": room_type.description,
                        "max_guests": room_type.max_guests,
                        "bed_type": room_type.bed_type,
                        "size_sqft": room_type.size_sqft,
                        "base_price_per_night": float(room_type.base_price),
                        "amenities": room_type.amenities if room_type.amenities else [],
                        "total_rooms": room_count
                    },
                    "pricing_note": "Final price includes 12% taxes and 5% service fee. Prices may vary based on dates and demand.",
                    "message": f"Here are the details for our {room_type.name}. Starting at ${room_type.base_price}/night."
                }

            # Get all active room types
            result = await self.db.execute(
                select(RoomType).where(RoomType.is_active == True).order_by(RoomType.base_price)
            )
            room_types = result.scalars().all()

            if not room_types:
                return {
                    "success": False,
                    "message": "No room types are currently available. Please contact the front desk."
                }

            room_type_list = []
            for rt in room_types:
                # Count rooms of this type (using status instead of is_active)
                room_count_result = await self.db.execute(
                    select(func.count(Room.id)).where(
                        and_(Room.room_type_id == rt.id, Room.status != "out_of_service")
                    )
                )
                room_count = room_count_result.scalar() or 0

                room_type_list.append({
                    "id": rt.id,
                    "name": rt.name,
                    "slug": rt.slug,
                    "description": rt.description[:150] + "..." if rt.description and len(rt.description) > 150 else rt.description,
                    "max_guests": rt.max_guests,
                    "bed_type": rt.bed_type,
                    "size_sqft": rt.size_sqft,
                    "base_price_per_night": float(rt.base_price),
                    "amenities": (rt.amenities[:5] if rt.amenities and len(rt.amenities) > 5 else rt.amenities) if rt.amenities else [],
                    "total_rooms": room_count
                })

            # Format price range
            prices = [rt["base_price_per_night"] for rt in room_type_list]
            price_range = f"${min(prices):.0f} - ${max(prices):.0f}" if len(prices) > 1 else f"${prices[0]:.0f}"

            return {
                "success": True,
                "room_types": room_type_list,
                "total_types": len(room_type_list),
                "price_range": price_range,
                "pricing_note": "Prices shown are base rates per night. Final price includes 12% taxes and 5% service fee. Rates may vary based on dates and demand.",
                "message": f"We have {len(room_type_list)} room types available, ranging from {price_range}/night. Would you like details about a specific room type, or shall I check availability for your dates?"
            }

        except Exception as e:
            logger.error(f"Error browsing room types: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to retrieve room information. Please try again or contact the front desk."
            }

    # ==================== BOOKING CREATION METHODS ====================

    async def get_available_room_types(
        self,
        check_in_date: str,
        check_out_date: str,
        adults: int = 1,
        children: int = 0
    ) -> Dict[str, Any]:
        """
        Get available room types for given dates.

        Args:
            check_in_date: Check-in date (YYYY-MM-DD)
            check_out_date: Check-out date (YYYY-MM-DD)
            adults: Number of adults
            children: Number of children

        Returns:
            List of available room types with pricing
        """
        from app.models.inventory import RoomType, Room
        from app.services.reservation_service import check_availability, compute_total

        try:
            # Parse dates flexibly
            arrival, arrival_error = parse_flexible_date(check_in_date)
            if arrival_error:
                return {
                    "success": False,
                    "message": f"Check-in date error: {arrival_error}"
                }

            departure, departure_error = parse_flexible_date(check_out_date)
            if departure_error:
                return {
                    "success": False,
                    "message": f"Check-out date error: {departure_error}"
                }

            # Validate dates
            today = date.today()
            if arrival < today:
                return {
                    "success": False,
                    "message": "Check-in date cannot be in the past."
                }
            if departure <= arrival:
                return {
                    "success": False,
                    "message": "Check-out date must be after check-in date."
                }

            nights = (departure - arrival).days
            total_guests = adults + children

            # Get all room types
            result = await self.db.execute(select(RoomType).where(RoomType.is_active == True))
            room_types = result.scalars().all()

            available_room_types = []

            for rt in room_types:
                # Check if room type can accommodate guests
                if rt.max_guests < total_guests:
                    continue

                # Check availability
                available_rooms = await check_availability(
                    self.db,
                    arrival,
                    departure,
                    rt.name,
                    adults
                )

                if available_rooms and len(available_rooms) > 0:
                    # Calculate pricing using GST slab-based rates
                    from app.core.tax import calculate_booking_taxes
                    per_night_rate = float(rt.base_price)
                    tax_calc = calculate_booking_taxes(per_night_rate, nights)
                    base_price = tax_calc["calculated_base"]
                    taxes = tax_calc["taxes"]
                    service_fee = tax_calc["service_fee"]
                    total = tax_calc["total_price"]

                    available_room_types.append({
                        "room_type_id": rt.id,
                        "name": rt.name,
                        "slug": rt.slug,
                        "description": rt.description,
                        "max_guests": rt.max_guests,
                        "bed_type": rt.bed_type,
                        "size_sqft": rt.size_sqft,
                        "amenities": rt.amenities if rt.amenities else [],
                        "rooms_available": len(available_rooms),
                        "pricing": {
                            "per_night": float(rt.base_price),
                            "nights": nights,
                            "base_total": base_price,
                            "taxes": round(taxes, 2),
                            "service_fee": round(service_fee, 2),
                            "total": round(total, 2),
                            "currency": "INR"
                        }
                    })

            if not available_room_types:
                return {
                    "success": True,
                    "available": False,
                    "room_types": [],
                    "message": f"Unfortunately, no rooms are available for {nights} night(s) from {arrival.strftime('%B %d, %Y')} to {departure.strftime('%B %d, %Y')} for {total_guests} guest(s). Would you like to try different dates?"
                }

            # Sort by price
            available_room_types.sort(key=lambda x: x["pricing"]["per_night"])

            return {
                "success": True,
                "available": True,
                "check_in": check_in_date,
                "check_out": check_out_date,
                "nights": nights,
                "guests": {"adults": adults, "children": children, "total": total_guests},
                "room_types": available_room_types,
                "total_options": len(available_room_types),
                "message": f"Great news! I found {len(available_room_types)} room type(s) available for your dates. Here are your options:"
            }

        except Exception as e:
            logger.error(f"Error checking availability: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to check availability. Please try again or contact the front desk."
            }

    async def create_booking(
        self,
        room_type_id: int,
        check_in_date: str,
        check_out_date: str,
        guest_first_name: str,
        guest_last_name: str,
        guest_email: str,
        guest_phone: str,
        guest_country: str,
        adults: int = 1,
        children: int = 0,
        special_requests: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new booking.

        Args:
            room_type_id: Room type ID to book
            check_in_date: Check-in date (YYYY-MM-DD)
            check_out_date: Check-out date (YYYY-MM-DD)
            guest_first_name: Guest's first name
            guest_last_name: Guest's last name
            guest_email: Guest's email address
            guest_phone: Guest's phone number
            guest_country: Guest's country
            adults: Number of adults
            children: Number of children
            special_requests: Any special requests

        Returns:
            Booking confirmation details
        """
        from app.models.inventory import RoomType
        from app.models.reservations import Guest, Booking
        from app.services.reservation_service import check_availability, create_guest
        import secrets
        import string

        try:
            # Helper to check if a value is actually provided (not a placeholder)
            def is_valid_value(value: Optional[str]) -> bool:
                if not value:
                    return False
                value_lower = value.lower().strip()
                invalid_values = [
                    'not provided', 'not specified', 'unknown', 'n/a', 'na', 'none',
                    'not available', 'missing', 'required', 'needed', 'tbd', 'null',
                    'undefined', '', 'not_provided', 'notprovided'
                ]
                return value_lower not in invalid_values and len(value.strip()) > 0

            # Validate required fields - check for actual values, not placeholders
            missing_fields = []
            if not is_valid_value(guest_first_name):
                missing_fields.append("first name")
            if not is_valid_value(guest_last_name):
                missing_fields.append("last name")
            if not is_valid_value(guest_email) or '@' not in (guest_email or ''):
                missing_fields.append("email")
            if not is_valid_value(guest_phone):
                missing_fields.append("phone number")
            if not is_valid_value(guest_country):
                missing_fields.append("country")

            if missing_fields:
                return {
                    "success": False,
                    "message": f"Please provide the following information: {', '.join(missing_fields)}."
                }

            # Parse dates flexibly
            arrival, arrival_error = parse_flexible_date(check_in_date)
            if arrival_error:
                return {
                    "success": False,
                    "message": f"Check-in date error: {arrival_error}"
                }

            departure, departure_error = parse_flexible_date(check_out_date)
            if departure_error:
                return {
                    "success": False,
                    "message": f"Check-out date error: {departure_error}"
                }

            today = date.today()
            if arrival < today:
                return {
                    "success": False,
                    "message": "Check-in date cannot be in the past."
                }
            if departure <= arrival:
                return {
                    "success": False,
                    "message": "Check-out date must be after check-in date."
                }

            nights = (departure - arrival).days

            # Get room type
            result = await self.db.execute(
                select(RoomType).where(RoomType.id == room_type_id)
            )
            room_type = result.scalars().first()

            if not room_type:
                return {
                    "success": False,
                    "message": "The selected room type is not available. Please choose a different room type."
                }

            # Validate guest count
            total_guests = adults + children
            if total_guests > room_type.max_guests:
                return {
                    "success": False,
                    "message": f"The {room_type.name} can accommodate up to {room_type.max_guests} guests. You have {total_guests} guests. Please choose a larger room type."
                }

            # Check availability again
            available_rooms = await check_availability(
                self.db,
                arrival,
                departure,
                room_type.name,
                adults
            )

            if not available_rooms:
                return {
                    "success": False,
                    "message": f"Sorry, {room_type.name} is no longer available for your selected dates. Please check availability again."
                }

            # Create or update guest
            guest_data = {
                "first_name": guest_first_name.strip(),
                "last_name": guest_last_name.strip(),
                "email": guest_email.lower().strip(),
                "phone": guest_phone.strip(),
                "country": guest_country.strip()
            }

            guest, _ = await create_guest(self.db, guest_data)

            # Calculate pricing using GST slab-based rates
            from app.core.tax import calculate_booking_taxes
            per_night_rate = float(room_type.base_price)
            tax_calc = calculate_booking_taxes(per_night_rate, nights)
            base_price = tax_calc["calculated_base"]
            taxes = tax_calc["taxes"]
            service_fee = tax_calc["service_fee"]
            total = tax_calc["total_price"]

            # Generate confirmation code and booking number
            chars = string.ascii_uppercase + string.digits
            confirmation_code = 'GLM-' + ''.join(secrets.choice(chars) for _ in range(6))
            booking_number = 'BK' + ''.join(secrets.choice(chars) for _ in range(8))

            # Create booking using new Booking model with all required fields
            booking = Booking(
                booking_number=booking_number,
                confirmation_code=confirmation_code,
                guest_id=guest.id,
                room_type_id=room_type.id,
                room_id=None,  # Room assigned at check-in/pre-checkin
                arrival_date=arrival,
                departure_date=departure,
                adults=adults,
                children=children,
                infants=0,
                nights=nights,
                status="confirmed",
                payment_status="pending",
                booking_source="agi_assistant",
                base_price=base_price,
                taxes=round(taxes, 2),
                service_fee=round(service_fee, 2),
                total_price=round(total, 2),
                special_requests=special_requests,
                # New fields from schema update
                vip_flag=guest.vip_status if guest.vip_status else False,
                number_of_guests=total_guests,
                upsells=None,
                discount_code=None,
                discount_amount=0.0,
                commission_rate=None,
                commission_amount=None,
                net_revenue=round(total, 2),  # No commission for direct booking
                modification_count=0
            )

            self.db.add(booking)
            await self.db.commit()
            await self.db.refresh(booking)

            # Generate pre-checkin URL
            precheckin_url = f"/pre-checkin?bookingId={booking.id}"

            return {
                "success": True,
                "booking": {
                    "confirmation_code": confirmation_code,
                    "booking_id": booking.id,
                    "booking_number": booking_number,
                    "guest_name": f"{guest_first_name} {guest_last_name}",
                    "guest_email": guest_email,
                    "room_type": room_type.name,
                    "check_in": arrival.strftime("%B %d, %Y"),
                    "check_out": departure.strftime("%B %d, %Y"),
                    "nights": nights,
                    "guests": {"adults": adults, "children": children},
                    "pricing": {
                        "per_night": float(room_type.base_price),
                        "base_total": base_price,
                        "taxes": round(taxes, 2),
                        "service_fee": round(service_fee, 2),
                        "total": round(total, 2),
                        "currency": "INR"
                    },
                    "special_requests": special_requests,
                    "status": "confirmed",
                    "precheckin_url": precheckin_url
                },
                "message": f"Booking confirmed!\n\nConfirmation Code: {confirmation_code}\nRoom: {room_type.name}\nDates: {arrival.strftime('%B %d')} - {departure.strftime('%B %d, %Y')} ({nights} nights)\nTotal: ₹{total:,.2f}\n\nThe booking has been created successfully."
            }

        except Exception as e:
            logger.error(f"Error creating booking: {e}")
            await self.db.rollback()
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to complete your booking. Please try again or contact the front desk at extension 0."
            }

    async def get_room_type_details(
        self,
        room_type_id: Optional[int] = None,
        room_type_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get detailed information about a room type.

        Args:
            room_type_id: Room type ID
            room_type_name: Room type name or slug

        Returns:
            Room type details
        """
        from app.models.inventory import RoomType

        try:
            query = select(RoomType)

            if room_type_id:
                query = query.where(RoomType.id == room_type_id)
            elif room_type_name:
                # Try exact match first, then slug match
                query = query.where(
                    or_(
                        RoomType.name.ilike(f"%{room_type_name}%"),
                        RoomType.slug.ilike(f"%{room_type_name.lower().replace(' ', '-')}%")
                    )
                )
            else:
                return {
                    "success": False,
                    "message": "Please specify a room type."
                }

            result = await self.db.execute(query)
            room_type = result.scalars().first()

            if not room_type:
                return {
                    "success": False,
                    "message": "Room type not found."
                }

            return {
                "success": True,
                "room_type": {
                    "id": room_type.id,
                    "name": room_type.name,
                    "slug": room_type.slug,
                    "description": room_type.description,
                    "max_guests": room_type.max_guests,
                    "bed_type": room_type.bed_type,
                    "size_sqft": room_type.size_sqft,
                    "base_price": float(room_type.base_price),
                    "amenities": room_type.amenities if room_type.amenities else [],
                    "view": getattr(room_type, 'view', None),
                    "is_active": room_type.is_active
                },
                "message": f"Here are the details for {room_type.name}."
            }

        except Exception as e:
            logger.error(f"Error getting room type details: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to retrieve room type information."
            }


def get_booking_tools(db: AsyncSession) -> BookingTools:
    """Factory function to create BookingTools instance"""
    return BookingTools(db)
