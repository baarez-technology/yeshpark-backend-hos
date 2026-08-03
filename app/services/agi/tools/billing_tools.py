"""
Billing Tools for AGI Guest Assistant
Handles all billing and folio operations
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from decimal import Decimal
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.billing_tools")


class BillingTools:
    """Tools for billing and folio management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_folio(
        self,
        room_number: str,
        booking_id: Optional[int] = None,
        guest_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get guest folio (bill summary).

        Args:
            room_number: Guest's room number
            booking_id: Booking ID
            guest_id: Guest ID

        Returns:
            Folio/bill summary
        """
        from app.models.operations import Folio, Payment
        from app.models.reservations import Booking, Guest
        from app.models.inventory import Room, RoomType

        try:
            # Get booking if not provided
            if not booking_id and room_number:
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
                    "message": "Unable to locate your booking. Please provide your confirmation number."
                }

            # Get booking details
            booking_result = await self.db.execute(
                select(Booking).where(Booking.id == booking_id)
            )
            booking = booking_result.scalars().first()

            if not booking:
                return {
                    "success": False,
                    "message": "Booking not found."
                }

            # Get guest info
            guest_result = await self.db.execute(
                select(Guest).where(Guest.id == booking.guest_id)
            )
            guest = guest_result.scalars().first()

            # Get room type for rate
            room_type_result = await self.db.execute(
                select(RoomType).where(RoomType.id == booking.room_type_id)
            )
            room_type = room_type_result.scalars().first()

            # Calculate nights
            nights = (booking.departure_date - booking.arrival_date).days

            # Build charges list
            charges = []

            # Room charges - use base_price from booking or calculate from room_type
            if booking.base_price and booking.base_price > 0:
                # base_price is the total base cost, divide by nights for nightly rate
                room_rate = float(booking.base_price) / nights if nights > 0 else float(booking.base_price)
                room_total = float(booking.base_price)
            elif room_type and room_type.base_rate:
                room_rate = float(room_type.base_rate)
                room_total = room_rate * nights
            else:
                room_rate = 16500.0  # Default fallback (INR)
                room_total = room_rate * nights
            charges.append({
                "date": booking.arrival_date.isoformat(),
                "description": f"Room Charges - {nights} night(s) @ {room_rate:.0f}/night",
                "amount": room_total,
                "category": "room"
            })

            # Add tax (typically 12-15%)
            tax_rate = 0.14
            tax_amount = round(room_total * tax_rate, 2)
            charges.append({
                "date": booking.arrival_date.isoformat(),
                "description": "Taxes & Fees (14%)",
                "amount": tax_amount,
                "category": "tax"
            })

            # Get any folio entries for additional charges
            try:
                folio_result = await self.db.execute(
                    select(Folio).where(Folio.booking_id == booking_id)
                )
                folio_entries = folio_result.scalars().all()

                for entry in folio_entries:
                    charges.append({
                        "date": entry.created_at.isoformat() if entry.created_at else None,
                        "description": entry.description or entry.charge_type,
                        "amount": float(entry.amount),
                        "category": entry.charge_type or "other"
                    })
            except Exception:
                # Folio table might not exist or have different structure
                pass

            # Calculate totals
            subtotal = sum(c["amount"] for c in charges if c["category"] != "tax")
            total_tax = sum(c["amount"] for c in charges if c["category"] == "tax")
            total_charges = sum(c["amount"] for c in charges)

            # Get payments
            payments = []
            total_paid = 0.0
            try:
                payment_result = await self.db.execute(
                    select(Payment).where(Payment.booking_id == booking_id)
                )
                payment_entries = payment_result.scalars().all()

                for payment in payment_entries:
                    payments.append({
                        "date": payment.payment_date.isoformat() if payment.payment_date else None,
                        "method": payment.payment_method,
                        "amount": float(payment.amount),
                        "status": payment.status
                    })
                    if payment.status == "completed":
                        total_paid += float(payment.amount)
            except Exception:
                pass

            balance_due = round(total_charges - total_paid, 2)

            return {
                "success": True,
                "folio": {
                    "booking_id": booking_id,
                    "confirmation_code": booking.confirmation_code,
                    "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Guest",
                    "room_number": room_number,
                    "arrival_date": booking.arrival_date.isoformat(),
                    "departure_date": booking.departure_date.isoformat(),
                    "nights": nights,
                    "charges": charges,
                    "subtotal": round(subtotal, 2),
                    "total_tax": round(total_tax, 2),
                    "total_charges": round(total_charges, 2),
                    "payments": payments,
                    "total_paid": round(total_paid, 2),
                    "balance_due": balance_due
                },
                "message": f"Your current balance is ${balance_due:.2f}. {'Paid in full!' if balance_due <= 0 else 'Payment due at checkout.'}"
            }

        except Exception as e:
            logger.error(f"Error getting folio: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to retrieve your folio. Please contact the front desk."
            }

    async def add_charge(
        self,
        room_number: str,
        charge_type: str,
        description: str,
        amount: float,
        booking_id: Optional[int] = None,
        guest_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Add a charge to the guest folio.

        Args:
            room_number: Guest's room number
            charge_type: Type of charge (room_service, minibar, spa, parking, etc.)
            description: Charge description
            amount: Charge amount
            booking_id: Booking ID
            guest_id: Guest ID

        Returns:
            Charge confirmation
        """
        from app.models.operations import Folio
        from app.models.reservations import Booking
        from app.models.inventory import Room

        try:
            # Get booking if not provided
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
                        guest_id = guest_id or booking.guest_id

            if not booking_id:
                return {
                    "success": False,
                    "message": "Unable to locate active booking for this room."
                }

            # Create folio entry
            folio_entry = Folio(
                booking_id=booking_id,
                guest_id=guest_id,
                charge_type=charge_type,
                description=description,
                amount=Decimal(str(amount)),
                charge_date=datetime.utcnow(),
                status="posted"
            )
            self.db.add(folio_entry)
            await self.db.commit()
            await self.db.refresh(folio_entry)

            return {
                "success": True,
                "charge_id": folio_entry.id,
                "charge_type": charge_type,
                "description": description,
                "amount": amount,
                "room_number": room_number,
                "status": "posted",
                "message": f"${amount:.2f} charge for {description} has been added to your room."
            }

        except Exception as e:
            logger.error(f"Error adding charge: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to add charge. Please contact the front desk."
            }

    async def request_checkout(
        self,
        room_number: str,
        booking_id: Optional[int] = None,
        guest_id: Optional[int] = None,
        express_checkout: bool = False,
        late_checkout: bool = False,
        feedback: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request checkout or express checkout.

        Args:
            room_number: Guest's room number
            booking_id: Booking ID
            guest_id: Guest ID
            express_checkout: Whether to use express checkout
            late_checkout: Whether to request late checkout
            feedback: Optional checkout feedback

        Returns:
            Checkout information
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            # Get folio first
            folio_result = await self.get_folio(room_number, booking_id, guest_id)

            if not folio_result.get("success"):
                return folio_result

            folio = folio_result["folio"]
            balance_due = folio["balance_due"]

            scheduling_service = get_scheduling_service(self.db)

            if late_checkout:
                # Request late checkout
                task, staff = await scheduling_service.create_and_assign_task(
                    task_type="concierge",
                    title=f"Late Checkout Request - Room {room_number}",
                    description=f"Guest in room {room_number} is requesting late checkout. Current balance: ${balance_due:.2f}",
                    priority="high",
                    room_number=room_number,
                    booking_id=booking_id,
                    guest_id=guest_id
                )

                return {
                    "success": True,
                    "request_type": "late_checkout",
                    "task_id": task.id if task else None,
                    "room_number": room_number,
                    "current_checkout_time": "11:00 AM",
                    "status": "pending_approval",
                    "balance_due": balance_due,
                    "late_checkout_fee": "$50 (if approved until 2 PM) / $100 (if approved until 4 PM)",
                    "message": "Your late checkout request has been submitted. The front desk will confirm availability and contact you shortly. Standard checkout is 11:00 AM."
                }

            if express_checkout:
                # Express checkout - charge to card on file
                if balance_due > 0:
                    checkout_info = {
                        "success": True,
                        "checkout_type": "express",
                        "room_number": room_number,
                        "balance_due": balance_due,
                        "payment_method": "Card on file",
                        "status": "pending_charge",
                        "folio_summary": {
                            "total_charges": folio["total_charges"],
                            "total_paid": folio["total_paid"],
                            "balance": balance_due
                        },
                        "message": f"Express checkout initiated. Your balance of ${balance_due:.2f} will be charged to the card on file. A receipt will be emailed to you. Please leave your key cards in the room. Thank you for staying with us!"
                    }
                else:
                    checkout_info = {
                        "success": True,
                        "checkout_type": "express",
                        "room_number": room_number,
                        "balance_due": 0,
                        "status": "complete",
                        "message": "Your account is settled. Please leave your key cards in the room. A receipt will be emailed to you. Thank you for staying with Glimmora Hotel & Suites!"
                    }

                # Create checkout task for staff
                task, staff = await scheduling_service.create_and_assign_task(
                    task_type="other",
                    title=f"Express Checkout - Room {room_number}",
                    description=f"Express checkout requested. Balance: ${balance_due:.2f}. Feedback: {feedback or 'None provided'}",
                    priority="normal",
                    room_number=room_number,
                    booking_id=booking_id,
                    guest_id=guest_id
                )

                checkout_info["task_id"] = task.id if task else None
                return checkout_info

            # Regular checkout - provide info
            return {
                "success": True,
                "checkout_type": "standard",
                "room_number": room_number,
                "checkout_time": "11:00 AM",
                "balance_due": balance_due,
                "folio_summary": {
                    "total_charges": folio["total_charges"],
                    "total_paid": folio["total_paid"],
                    "balance": balance_due
                },
                "options": {
                    "express_checkout": "Leave key cards in room, bill charged to card on file",
                    "late_checkout": "Subject to availability, additional fee applies",
                    "front_desk": "Visit front desk for in-person checkout"
                },
                "message": f"Checkout time is 11:00 AM. Your current balance is ${balance_due:.2f}. Would you like to proceed with express checkout or request late checkout?"
            }

        except Exception as e:
            logger.error(f"Error processing checkout request: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process checkout request. Please visit the front desk."
            }

    async def dispute_charge(
        self,
        room_number: str,
        charge_description: str,
        dispute_reason: str,
        booking_id: Optional[int] = None,
        guest_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Dispute a charge on the folio.

        Args:
            room_number: Guest's room number
            charge_description: Description of disputed charge
            dispute_reason: Reason for dispute
            booking_id: Booking ID
            guest_id: Guest ID

        Returns:
            Dispute confirmation
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            scheduling_service = get_scheduling_service(self.db)

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="other",
                title=f"Billing Dispute - Room {room_number}",
                description=f"Charge Disputed: {charge_description}\nReason: {dispute_reason}",
                priority="high",
                room_number=room_number,
                booking_id=booking_id,
                guest_id=guest_id
            )

            return {
                "success": True,
                "dispute_id": f"DSP-{task.id}" if task else None,
                "task_id": task.id if task else None,
                "disputed_charge": charge_description,
                "reason": dispute_reason,
                "status": "under_review",
                "message": f"Your dispute for '{charge_description}' has been submitted. Our billing team will review and contact you within 24 hours. Reference: DSP-{task.id if task else 'PENDING'}"
            }

        except Exception as e:
            logger.error(f"Error creating dispute: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process dispute. Please contact the front desk."
            }

    async def request_receipt(
        self,
        room_number: str,
        booking_id: Optional[int] = None,
        email_address: Optional[str] = None,
        format_type: str = "email"
    ) -> Dict[str, Any]:
        """
        Request a receipt/invoice.

        Args:
            room_number: Guest's room number
            booking_id: Booking ID
            email_address: Email address for receipt
            format_type: Format (email, print, pdf)

        Returns:
            Receipt request confirmation
        """
        from app.services.staff_scheduling_service import get_scheduling_service

        try:
            # Get folio
            folio_result = await self.get_folio(room_number, booking_id)

            if not folio_result.get("success"):
                return folio_result

            folio = folio_result["folio"]

            scheduling_service = get_scheduling_service(self.db)

            task, staff = await scheduling_service.create_and_assign_task(
                task_type="other",
                title=f"Receipt Request - Room {room_number}",
                description=f"Format: {format_type}\nEmail: {email_address or 'On file'}\nTotal: ${folio['total_charges']:.2f}",
                priority="normal",
                room_number=room_number,
                booking_id=booking_id
            )

            return {
                "success": True,
                "task_id": task.id if task else None,
                "format": format_type,
                "email": email_address or "Email on file",
                "folio_summary": {
                    "confirmation": folio["confirmation_code"],
                    "dates": f"{folio['arrival_date']} - {folio['departure_date']}",
                    "total": folio["total_charges"],
                    "paid": folio["total_paid"],
                    "balance": folio["balance_due"]
                },
                "status": "processing",
                "message": f"Your receipt will be sent to {email_address or 'your email on file'} shortly." if format_type == "email" else "Your receipt is being prepared. Please pick it up at the front desk."
            }

        except Exception as e:
            logger.error(f"Error requesting receipt: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to process receipt request. Please contact the front desk."
            }

    async def get_payment_options(
        self,
        room_number: str,
        booking_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get available payment options.

        Args:
            room_number: Guest's room number
            booking_id: Booking ID

        Returns:
            Payment options
        """
        # Get current balance
        folio_result = await self.get_folio(room_number, booking_id)

        balance = folio_result.get("folio", {}).get("balance_due", 0) if folio_result.get("success") else 0

        return {
            "success": True,
            "balance_due": balance,
            "payment_options": [
                {
                    "method": "credit_card",
                    "name": "Credit/Debit Card",
                    "accepted": ["Visa", "Mastercard", "American Express", "Discover"],
                    "description": "Card on file or new card"
                },
                {
                    "method": "cash",
                    "name": "Cash",
                    "description": "Pay at front desk"
                },
                {
                    "method": "room_charge",
                    "name": "Charge to Room",
                    "description": "Add to room folio, settle at checkout"
                },
                {
                    "method": "corporate",
                    "name": "Corporate/Direct Bill",
                    "description": "For approved corporate accounts"
                }
            ],
            "front_desk_hours": "24/7",
            "message": f"Your current balance is ${balance:.2f}. Payment can be made at the front desk or charged to your card on file at checkout."
        }


def get_billing_tools(db: AsyncSession) -> BillingTools:
    """Factory function to create BillingTools instance"""
    return BillingTools(db)
