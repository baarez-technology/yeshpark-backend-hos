"""
Pre-Checkin Tools for AGI Guest Assistant
Handles all pre-check-in related operations via chat
"""

import logging
import secrets
import base64
from typing import Any, Dict, List, Optional
from datetime import datetime, date, timedelta
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.precheckin_tools")


class PreCheckinTools:
    """Tools for pre-check-in operations via chat"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def verify_booking_for_precheckin(
        self,
        confirmation_code: str,
        guest_name: str
    ) -> Dict[str, Any]:
        """
        Verify a booking is eligible for pre-check-in.

        Args:
            confirmation_code: Booking confirmation code
            guest_name: Guest name for verification

        Returns:
            Booking verification result
        """
        from app.models.reservations import Reservation, Guest, Booking
        from app.models.inventory import RoomType

        try:
            # Find reservation first
            result = await self.db.execute(
                select(Reservation).where(
                    Reservation.confirmation_code.ilike(f"%{confirmation_code.strip().upper()}%")
                )
            )
            reservation = result.scalars().first()

            # If not found in Reservation, check Booking table
            booking = None
            if not reservation:
                booking_result = await self.db.execute(
                    select(Booking).where(
                        Booking.confirmation_code.ilike(f"%{confirmation_code.strip().upper()}%")
                    )
                )
                booking = booking_result.scalars().first()

            if not reservation and not booking:
                return {
                    "success": False,
                    "eligible": False,
                    "message": "I couldn't find a booking with that confirmation code. Please double-check and try again."
                }

            # Use whichever record we found (reservation or booking)
            # They have similar fields but different names
            record = reservation or booking
            is_booking = booking is not None and reservation is None

            # Get guest
            guest_result = await self.db.execute(
                select(Guest).where(Guest.id == record.guest_id)
            )
            guest = guest_result.scalars().first()

            if not guest:
                return {
                    "success": False,
                    "eligible": False,
                    "message": "Unable to verify guest information for this booking."
                }

            # Verify name (flexible matching)
            guest_full_name = f"{guest.first_name} {guest.last_name}".lower()
            provided_name = guest_name.lower().strip()

            name_match = (
                provided_name in guest_full_name or
                guest_full_name in provided_name or
                guest.first_name.lower() in provided_name or
                guest.last_name.lower() in provided_name
            )

            if not name_match:
                return {
                    "success": False,
                    "eligible": False,
                    "message": "The name provided doesn't match our records. Please verify the name on your booking."
                }

            # Check booking status
            if record.status == "cancelled":
                return {
                    "success": False,
                    "eligible": False,
                    "message": "This booking has been cancelled and is not eligible for pre-check-in."
                }

            if record.status in ["checked_out", "completed"]:
                return {
                    "success": False,
                    "eligible": False,
                    "message": "This booking has already been completed."
                }

            if record.status == "checked_in":
                return {
                    "success": True,
                    "eligible": False,
                    "already_checked_in": True,
                    "message": "You're already checked in! Is there anything else I can help you with during your stay?"
                }

            # Get arrival/departure dates (different field names for Booking vs Reservation)
            arrival_date = record.arrival_date
            departure_date = record.departure_date

            # Check if within pre-checkin window (7 days before arrival)
            today = date.today()
            days_until_arrival = (arrival_date - today).days

            if days_until_arrival > 7:
                return {
                    "success": True,
                    "eligible": False,
                    "too_early": True,
                    "arrival_date": arrival_date.isoformat(),
                    "message": f"Pre-check-in opens 7 days before arrival. Your arrival is on {arrival_date.strftime('%B %d, %Y')}, so you can start pre-check-in from {(arrival_date - timedelta(days=7)).strftime('%B %d, %Y')}."
                }

            # Get room type
            room_type_name = None
            if record.room_type_id:
                rt_result = await self.db.execute(
                    select(RoomType).where(RoomType.id == record.room_type_id)
                )
                room_type = rt_result.scalars().first()
                if room_type:
                    room_type_name = room_type.name

            nights = (departure_date - arrival_date).days

            return {
                "success": True,
                "eligible": True,
                "reservation_id": record.id,  # Works for both models
                "booking_id": record.id if is_booking else None,
                "is_booking": is_booking,
                "confirmation_code": record.confirmation_code,
                "guest_id": guest.id,
                "guest_name": f"{guest.first_name} {guest.last_name}",
                "guest_email": guest.email,
                "guest_phone": guest.phone,
                "room_type": room_type_name,
                "arrival_date": arrival_date.isoformat(),
                "departure_date": departure_date.isoformat(),
                "nights": nights,
                "status": record.status,
                "message": f"Great! I found your booking, {guest.first_name}! You're staying in our {room_type_name or 'room'} from {arrival_date.strftime('%B %d')} to {departure_date.strftime('%B %d, %Y')} ({nights} nights). Let's get you pre-checked in!"
            }

        except Exception as e:
            logger.error(f"Error verifying booking for pre-checkin: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to verify your booking. Please try again or contact the front desk."
            }

    async def start_precheckin(
        self,
        reservation_id: int,
        email: str,
        phone: str,
        is_booking: bool = False
    ) -> Dict[str, Any]:
        """
        Start or get existing pre-checkin record.

        Args:
            reservation_id: Reservation or Booking ID
            email: Guest email
            phone: Guest phone
            is_booking: True if reservation_id is actually a Booking ID

        Returns:
            Pre-checkin record info
        """
        from app.models.precheckin import PreCheckIn
        from app.models.reservations import Reservation, Booking

        try:
            guest_id = None

            # Get record from appropriate table
            if is_booking:
                res_result = await self.db.execute(
                    select(Booking).where(Booking.id == reservation_id)
                )
                record = res_result.scalars().first()
                if record:
                    guest_id = record.guest_id
            else:
                res_result = await self.db.execute(
                    select(Reservation).where(Reservation.id == reservation_id)
                )
                record = res_result.scalars().first()
                if record:
                    guest_id = record.guest_id

            if not record:
                return {
                    "success": False,
                    "message": "Reservation not found."
                }

            # Check if pre-checkin already exists (check both reservation_id and booking_id)
            if is_booking:
                result = await self.db.execute(
                    select(PreCheckIn).where(PreCheckIn.booking_id == reservation_id)
                )
            else:
                result = await self.db.execute(
                    select(PreCheckIn).where(PreCheckIn.reservation_id == reservation_id)
                )
            precheckin = result.scalars().first()

            if precheckin:
                if precheckin.status == "completed":
                    return {
                        "success": True,
                        "already_completed": True,
                        "precheckin_id": precheckin.id,
                        "message": "You've already completed pre-check-in! Your room is ready and waiting for you."
                    }
                else:
                    # Update contact info
                    precheckin.email = email
                    precheckin.phone = phone
                    precheckin.updated_at = datetime.utcnow()
                    await self.db.commit()

                    return {
                        "success": True,
                        "existing": True,
                        "precheckin_id": precheckin.id,
                        "status": precheckin.status,
                        "id_verified": precheckin.id_verified,
                        "message": "I found your existing pre-check-in. Let's continue where you left off!"
                    }

            # Create new pre-checkin
            precheckin = PreCheckIn(
                reservation_id=reservation_id if not is_booking else 0,  # Use 0 for bookings since field is required
                booking_id=reservation_id if is_booking else None,
                guest_id=guest_id,
                email=email,
                phone=phone,
                status="in_progress",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )

            self.db.add(precheckin)
            await self.db.commit()
            await self.db.refresh(precheckin)

            return {
                "success": True,
                "new": True,
                "precheckin_id": precheckin.id,
                "message": "Perfect! I've started your pre-check-in. Now let's collect your preferences to find the perfect room for you."
            }

        except Exception as e:
            logger.error(f"Error starting pre-checkin: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to start pre-check-in. Please try again."
            }

    async def update_preferences(
        self,
        precheckin_id: int,
        floor_preference: Optional[str] = None,
        view_preference: Optional[str] = None,
        bed_type_preference: Optional[str] = None,
        quietness_preference: Optional[str] = None,
        arrival_time: Optional[str] = None,
        special_requests: Optional[str] = None,
        early_check_in: bool = False,
        late_check_out: bool = False
    ) -> Dict[str, Any]:
        """
        Update room preferences for pre-check-in.

        Args:
            precheckin_id: Pre-check-in ID
            floor_preference: Floor preference (low, mid, high, any)
            view_preference: View preference (ocean, city, garden, any)
            bed_type_preference: Bed type preference (king, queen, twin, any)
            quietness_preference: Quietness preference (quiet, moderate, any)
            arrival_time: Expected arrival time (HH:MM)
            special_requests: Any special requests
            early_check_in: Request early check-in
            late_check_out: Request late check-out

        Returns:
            Update result
        """
        from app.models.precheckin import PreCheckIn

        try:
            result = await self.db.execute(
                select(PreCheckIn).where(PreCheckIn.id == precheckin_id)
            )
            precheckin = result.scalars().first()

            if not precheckin:
                return {
                    "success": False,
                    "message": "Pre-check-in record not found."
                }

            # Update preferences
            if floor_preference:
                precheckin.floor_preference = floor_preference
            if view_preference:
                precheckin.view_preference = view_preference
            if bed_type_preference:
                precheckin.bed_type_preference = bed_type_preference
            if quietness_preference:
                precheckin.quietness_preference = quietness_preference
            if arrival_time:
                precheckin.arrival_time = arrival_time
            if special_requests:
                precheckin.special_requests = special_requests

            precheckin.early_check_in = early_check_in
            precheckin.late_check_out = late_check_out
            precheckin.updated_at = datetime.utcnow()

            await self.db.commit()

            # Build preferences summary
            prefs = []
            if floor_preference and floor_preference != "any":
                prefs.append(f"{floor_preference} floor")
            if view_preference and view_preference != "any":
                prefs.append(f"{view_preference} view")
            if bed_type_preference and bed_type_preference != "any":
                prefs.append(f"{bed_type_preference} bed")
            if quietness_preference == "quiet":
                prefs.append("quiet room")
            if early_check_in:
                prefs.append("early check-in requested")
            if late_check_out:
                prefs.append("late check-out requested")

            prefs_summary = ", ".join(prefs) if prefs else "No specific preferences"

            return {
                "success": True,
                "precheckin_id": precheckin_id,
                "preferences": {
                    "floor": floor_preference,
                    "view": view_preference,
                    "bed_type": bed_type_preference,
                    "quietness": quietness_preference,
                    "arrival_time": arrival_time,
                    "special_requests": special_requests,
                    "early_check_in": early_check_in,
                    "late_check_out": late_check_out
                },
                "message": f"Got it! Your preferences: {prefs_summary}. Now I'll find the best room matches for you!"
            }

        except Exception as e:
            logger.error(f"Error updating preferences: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to save preferences. Please try again."
            }

    async def get_room_recommendations(
        self,
        precheckin_id: int
    ) -> Dict[str, Any]:
        """
        Get AI-powered room recommendations based on preferences.

        Args:
            precheckin_id: Pre-check-in ID

        Returns:
            Room recommendations with scores
        """
        from app.models.precheckin import PreCheckIn
        from app.models.reservations import Reservation
        from app.models.inventory import Room, RoomType
        from app.services.reservation_service import check_availability

        try:
            # Get pre-checkin
            result = await self.db.execute(
                select(PreCheckIn).where(PreCheckIn.id == precheckin_id)
            )
            precheckin = result.scalars().first()

            if not precheckin:
                return {
                    "success": False,
                    "message": "Pre-check-in record not found."
                }

            # Get reservation
            res_result = await self.db.execute(
                select(Reservation).where(Reservation.id == precheckin.reservation_id)
            )
            reservation = res_result.scalars().first()

            if not reservation:
                return {
                    "success": False,
                    "message": "Reservation not found."
                }

            # Get room type
            room_type = None
            if reservation.room_type_id:
                rt_result = await self.db.execute(
                    select(RoomType).where(RoomType.id == reservation.room_type_id)
                )
                room_type = rt_result.scalars().first()

            # Get available rooms
            available_rooms = await check_availability(
                self.db,
                reservation.arrival_date,
                reservation.departure_date,
                room_type.name if room_type else None,
                reservation.adults
            )

            if not available_rooms:
                return {
                    "success": True,
                    "rooms": [],
                    "message": "No rooms are currently available for your dates. Our front desk team will assign you the best available room upon arrival."
                }

            # Score rooms based on preferences
            scored_rooms = []
            for room in available_rooms:
                score = 0
                reasons = []

                # Floor preference (25 points)
                floor_pref = precheckin.floor_preference or "any"
                if floor_pref == "high" and room.floor >= 15:
                    score += 25
                    reasons.append("High floor as requested")
                elif floor_pref == "high" and room.floor >= 10:
                    score += 15
                    reasons.append("Upper floor")
                elif floor_pref == "mid" and 8 <= room.floor <= 14:
                    score += 25
                    reasons.append("Mid floor as requested")
                elif floor_pref == "low" and room.floor < 8:
                    score += 25
                    reasons.append("Lower floor as requested")
                elif floor_pref == "any":
                    score += 15

                # View preference (25 points)
                view_pref = precheckin.view_preference or "any"
                room_view = getattr(room, 'view', '') or ''
                if view_pref != "any" and view_pref.lower() in room_view.lower():
                    score += 25
                    reasons.append(f"{room_view} view as requested")
                elif view_pref == "any":
                    score += 15

                # Bed type preference (20 points)
                bed_pref = precheckin.bed_type_preference or "any"
                room_bed = getattr(room, 'bed_type', '') or ''
                if bed_pref != "any" and bed_pref.lower() in room_bed.lower():
                    score += 20
                    reasons.append(f"{room_bed} bed as requested")
                elif bed_pref == "any":
                    score += 12

                # Quietness preference (15 points)
                quiet_pref = precheckin.quietness_preference or "any"
                if quiet_pref == "quiet":
                    if room.floor >= 15:
                        score += 15
                        reasons.append("Quiet high floor location")
                    elif room.floor >= 10:
                        score += 10
                        reasons.append("Quieter upper floor")
                    else:
                        score += 5
                else:
                    score += 10

                # Room type match (15 points)
                if room_type and room.room_type_id == room_type.id:
                    score += 15
                    reasons.append(f"Matches your booked {room_type.name}")
                else:
                    score += 5

                # Get room type info
                rt_info = None
                if room.room_type_id:
                    rt_res = await self.db.execute(
                        select(RoomType).where(RoomType.id == room.room_type_id)
                    )
                    rt_info = rt_res.first()

                scored_rooms.append({
                    "room_id": room.id,
                    "room_number": room.number,
                    "floor": room.floor,
                    "room_type": rt_info.name if rt_info else "Standard",
                    "view": getattr(room, 'view', 'Standard'),
                    "bed_type": getattr(room, 'bed_type', 'Standard'),
                    "score": min(score, 100),
                    "reasons": reasons if reasons else ["Available room"]
                })

            # Sort by score descending
            scored_rooms.sort(key=lambda x: x["score"], reverse=True)

            # Take top 5
            top_rooms = scored_rooms[:5]

            # Add badges
            if top_rooms:
                top_rooms[0]["badge"] = "Best Match"
                if len(top_rooms) > 1:
                    top_rooms[1]["badge"] = "Great Choice"
                if len(top_rooms) > 2:
                    top_rooms[2]["badge"] = "Good Option"

            return {
                "success": True,
                "precheckin_id": precheckin_id,
                "rooms": top_rooms,
                "total_available": len(available_rooms),
                "preferences_used": {
                    "floor": precheckin.floor_preference,
                    "view": precheckin.view_preference,
                    "bed_type": precheckin.bed_type_preference,
                    "quietness": precheckin.quietness_preference
                },
                "message": f"I found {len(top_rooms)} great room options for you based on your preferences! Here are my top recommendations:"
            }

        except Exception as e:
            logger.error(f"Error getting room recommendations: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to get room recommendations. Please try again."
            }

    async def select_room(
        self,
        precheckin_id: int,
        room_id: int,
        ai_score: Optional[float] = None,
        ai_reasoning: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Select a room for the pre-check-in.

        Args:
            precheckin_id: Pre-check-in ID
            room_id: Selected room ID
            ai_score: AI recommendation score
            ai_reasoning: AI reasoning for selection

        Returns:
            Selection result
        """
        from app.models.precheckin import PreCheckIn
        from app.models.inventory import Room, RoomType
        import json

        try:
            # Get pre-checkin
            result = await self.db.execute(
                select(PreCheckIn).where(PreCheckIn.id == precheckin_id)
            )
            precheckin = result.scalars().first()

            if not precheckin:
                return {
                    "success": False,
                    "message": "Pre-check-in record not found."
                }

            # Get room
            room_result = await self.db.execute(
                select(Room).where(Room.id == room_id)
            )
            room = room_result.scalars().first()

            if not room:
                return {
                    "success": False,
                    "message": "Selected room not found."
                }

            # Get room type
            rt_result = await self.db.execute(
                select(RoomType).where(RoomType.id == room.room_type_id)
            )
            room_type = rt_result.scalars().first()

            # Update pre-checkin with selected room
            precheckin.selected_room_id = room_id
            precheckin.ai_score = ai_score
            precheckin.ai_reasoning = json.dumps(ai_reasoning) if ai_reasoning else None
            precheckin.updated_at = datetime.utcnow()

            await self.db.commit()

            return {
                "success": True,
                "precheckin_id": precheckin_id,
                "selected_room": {
                    "room_id": room.id,
                    "room_number": room.number,
                    "floor": room.floor,
                    "room_type": room_type.name if room_type else "Standard",
                    "view": getattr(room, 'view', 'Standard')
                },
                "id_verification_required": not precheckin.id_verified,
                "message": f"Excellent choice! Room {room.number} on floor {room.floor} is now reserved for you. {'Now we just need to verify your ID to complete the pre-check-in.' if not precheckin.id_verified else 'Your pre-check-in is almost complete!'}"
            }

        except Exception as e:
            logger.error(f"Error selecting room: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to select room. Please try again."
            }

    async def complete_precheckin(
        self,
        precheckin_id: int,
        skip_id_verification: bool = False
    ) -> Dict[str, Any]:
        """
        Complete the pre-check-in process.

        Args:
            precheckin_id: Pre-check-in ID
            skip_id_verification: Skip ID verification (for testing/special cases)

        Returns:
            Completion result with digital key
        """
        from app.models.precheckin import PreCheckIn
        from app.models.reservations import Reservation, Guest
        from app.models.inventory import Room, RoomType
        import json

        try:
            # Get pre-checkin
            result = await self.db.execute(
                select(PreCheckIn).where(PreCheckIn.id == precheckin_id)
            )
            precheckin = result.scalars().first()

            if not precheckin:
                return {
                    "success": False,
                    "message": "Pre-check-in record not found."
                }

            if precheckin.status == "completed":
                return {
                    "success": True,
                    "already_completed": True,
                    "digital_key": precheckin.digital_key_id,
                    "message": "Your pre-check-in is already complete! Your digital key is ready."
                }

            # Check if room is selected
            if not precheckin.selected_room_id:
                return {
                    "success": False,
                    "needs_room_selection": True,
                    "message": "Please select a room first before completing pre-check-in."
                }

            # Check ID verification (unless skipped)
            if not skip_id_verification and not precheckin.id_verified:
                return {
                    "success": False,
                    "needs_id_verification": True,
                    "message": "ID verification is required to complete pre-check-in. You can verify your ID at the front desk upon arrival, or upload your ID document through the mobile app."
                }

            # Get reservation
            res_result = await self.db.execute(
                select(Reservation).where(Reservation.id == precheckin.reservation_id)
            )
            reservation = res_result.scalars().first()

            # Get room
            room_result = await self.db.execute(
                select(Room).where(Room.id == precheckin.selected_room_id)
            )
            room = room_result.scalars().first()

            # Get room type
            rt_result = await self.db.execute(
                select(RoomType).where(RoomType.id == room.room_type_id)
            )
            room_type = rt_result.scalars().first()

            # Get guest
            guest_result = await self.db.execute(
                select(Guest).where(Guest.id == precheckin.guest_id)
            )
            guest = guest_result.scalars().first()

            # Generate digital key
            key_bytes = secrets.token_bytes(6)
            digital_key_id = f"DK-{base64.urlsafe_b64encode(key_bytes).decode()[:8]}"
            qr_code = f"GLIMMORA-KEY-{digital_key_id}-ROOM-{room.number}-RESERVATION-{reservation.id}"

            # Update pre-checkin
            precheckin.digital_key_id = digital_key_id
            precheckin.digital_key_activated = True
            precheckin.qr_code = qr_code
            precheckin.status = "completed"
            precheckin.completed_at = datetime.utcnow()
            precheckin.updated_at = datetime.utcnow()

            # Update reservation with room assignment
            reservation.room_id = precheckin.selected_room_id
            reservation.status = "checked_in"
            reservation.updated_at = datetime.utcnow()

            # Save guest preferences
            if guest:
                preferences = {
                    "floor": precheckin.floor_preference,
                    "view": precheckin.view_preference,
                    "bedType": precheckin.bed_type_preference,
                    "quietness": precheckin.quietness_preference
                }
                existing_prefs = guest.preferences or {}
                if isinstance(existing_prefs, str):
                    try:
                        existing_prefs = json.loads(existing_prefs)
                    except:
                        existing_prefs = {}
                existing_prefs.update({k: v for k, v in preferences.items() if v})
                guest.preferences = json.dumps(existing_prefs)

            await self.db.commit()

            return {
                "success": True,
                "precheckin_id": precheckin_id,
                "reservation_id": reservation.id,
                "confirmation_code": reservation.confirmation_code,
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Guest",
                "room": {
                    "number": room.number,
                    "floor": room.floor,
                    "type": room_type.name if room_type else "Standard",
                    "view": getattr(room, 'view', 'Standard')
                },
                "digital_key": {
                    "key_id": digital_key_id,
                    "qr_code": qr_code,
                    "activated": True
                },
                "check_in": reservation.arrival_date.strftime("%B %d, %Y"),
                "check_out": reservation.departure_date.strftime("%B %d, %Y"),
                "message": f"🎉 Congratulations! Your pre-check-in is complete!\n\nRoom {room.number} is ready for you on floor {room.floor}.\n\nYour Digital Key: {digital_key_id}\n\nSimply show your digital key QR code at the hotel entrance to access your room. Skip the front desk and go straight to your room! We can't wait to welcome you."
            }

        except Exception as e:
            logger.error(f"Error completing pre-checkin: {e}")
            await self.db.rollback()
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to complete pre-check-in. Please try again or contact the front desk."
            }

    async def get_precheckin_status(
        self,
        confirmation_code: Optional[str] = None,
        precheckin_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get the status of a pre-check-in.

        Args:
            confirmation_code: Booking confirmation code
            precheckin_id: Pre-check-in ID

        Returns:
            Pre-check-in status
        """
        from app.models.precheckin import PreCheckIn
        from app.models.reservations import Reservation, Guest
        from app.models.inventory import Room, RoomType

        try:
            precheckin = None

            if precheckin_id:
                result = await self.db.execute(
                    select(PreCheckIn).where(PreCheckIn.id == precheckin_id)
                )
                precheckin = result.scalars().first()
            elif confirmation_code:
                # Get reservation first
                res_result = await self.db.execute(
                    select(Reservation).where(
                        Reservation.confirmation_code.ilike(f"%{confirmation_code.strip().upper()}%")
                    )
                )
                reservation = res_result.scalars().first()
                if reservation:
                    result = await self.db.execute(
                        select(PreCheckIn).where(PreCheckIn.reservation_id == reservation.id)
                    )
                    precheckin = result.scalars().first()

            if not precheckin:
                return {
                    "success": True,
                    "found": False,
                    "message": "No pre-check-in found for this booking. Would you like to start the pre-check-in process?"
                }

            # Get related data
            res_result = await self.db.execute(
                select(Reservation).where(Reservation.id == precheckin.reservation_id)
            )
            reservation = res_result.scalars().first()

            room_info = None
            if precheckin.selected_room_id:
                room_result = await self.db.execute(
                    select(Room).where(Room.id == precheckin.selected_room_id)
                )
                room = room_result.scalars().first()
                if room:
                    rt_result = await self.db.execute(
                        select(RoomType).where(RoomType.id == room.room_type_id)
                    )
                    room_type = rt_result.scalars().first()
                    room_info = {
                        "number": room.number,
                        "floor": room.floor,
                        "type": room_type.name if room_type else "Standard"
                    }

            # Determine what's completed
            steps_completed = []
            steps_remaining = []

            steps_completed.append("Booking verified")

            if precheckin.floor_preference or precheckin.view_preference:
                steps_completed.append("Preferences saved")
            else:
                steps_remaining.append("Set room preferences")

            if precheckin.selected_room_id:
                steps_completed.append("Room selected")
            else:
                steps_remaining.append("Select a room")

            if precheckin.id_verified:
                steps_completed.append("ID verified")
            else:
                steps_remaining.append("Verify ID")

            if precheckin.status == "completed":
                steps_completed.append("Pre-check-in complete")

            return {
                "success": True,
                "found": True,
                "precheckin_id": precheckin.id,
                "status": precheckin.status,
                "confirmation_code": reservation.confirmation_code if reservation else None,
                "arrival_date": reservation.arrival_date.isoformat() if reservation else None,
                "selected_room": room_info,
                "id_verified": precheckin.id_verified,
                "digital_key": precheckin.digital_key_id if precheckin.status == "completed" else None,
                "steps_completed": steps_completed,
                "steps_remaining": steps_remaining,
                "preferences": {
                    "floor": precheckin.floor_preference,
                    "view": precheckin.view_preference,
                    "bed_type": precheckin.bed_type_preference,
                    "quietness": precheckin.quietness_preference
                },
                "message": f"Pre-check-in status: {precheckin.status.replace('_', ' ').title()}. {len(steps_completed)} steps completed, {len(steps_remaining)} remaining." if steps_remaining else "Your pre-check-in is complete!"
            }

        except Exception as e:
            logger.error(f"Error getting pre-checkin status: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to retrieve pre-check-in status."
            }


def get_precheckin_tools(db: AsyncSession) -> PreCheckinTools:
    """Factory function to create PreCheckinTools instance"""
    return PreCheckinTools(db)
