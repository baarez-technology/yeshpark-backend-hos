"""
WhatsApp Service for Hotel PMS
Sends automated WhatsApp notifications via Twilio WhatsApp Business API.
Supports: check-in reminders, check-out reminders, and custom messages.
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Global service instance
_whatsapp_service: Optional["WhatsAppService"] = None


class WhatsAppService:
    """
    WhatsApp messaging service using Twilio WhatsApp Business API.

    Provides methods to send:
    - Check-in reminders (1 hour before check-in)
    - Check-out reminders (1 hour before check-out)
    - Custom messages to guests
    """

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        """
        Initialize WhatsApp service with Twilio credentials.

        Args:
            account_sid: Twilio Account SID
            auth_token: Twilio Auth Token
            from_number: Twilio WhatsApp number (e.g., "whatsapp:+14155238886")
        """
        try:
            from twilio.rest import Client
            self.client = Client(account_sid, auth_token)
            self.from_number = from_number
            self._enabled = True
            logger.info("WhatsApp service initialized successfully")
        except ImportError:
            logger.warning("Twilio library not installed. WhatsApp service disabled.")
            self.client = None
            self._enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize WhatsApp service: {e}")
            self.client = None
            self._enabled = False

    @property
    def is_enabled(self) -> bool:
        """Check if service is properly configured and enabled."""
        return self._enabled and self.client is not None

    def _format_phone_number(self, phone: str) -> str:
        """
        Format phone number for WhatsApp.
        Ensures the number has the 'whatsapp:' prefix.

        Args:
            phone: Raw phone number (e.g., "+919876543210" or "9876543210")

        Returns:
            Formatted WhatsApp number (e.g., "whatsapp:+919876543210")
        """
        # Remove any existing whatsapp: prefix
        phone = phone.replace("whatsapp:", "").strip()

        # Remove spaces, dashes, and parentheses
        phone = "".join(c for c in phone if c.isdigit() or c == "+")

        # Add country code if missing (assuming India +91 as default)
        if not phone.startswith("+"):
            if phone.startswith("0"):
                phone = phone[1:]  # Remove leading 0
            if len(phone) == 10:
                phone = "+91" + phone  # Add India country code
            else:
                phone = "+" + phone

        return f"whatsapp:{phone}"

    def send_message(self, to_phone: str, message: str) -> Dict[str, Any]:
        """
        Send a WhatsApp message to a phone number.

        Args:
            to_phone: Recipient's phone number
            message: Message content

        Returns:
            Dict with status and message SID or error
        """
        if not self.is_enabled:
            logger.warning("WhatsApp service not enabled, message not sent")
            return {"success": False, "error": "WhatsApp service not enabled"}

        try:
            formatted_to = self._format_phone_number(to_phone)

            twilio_message = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=formatted_to
            )

            logger.info(f"WhatsApp message sent to {formatted_to}, SID: {twilio_message.sid}")
            return {
                "success": True,
                "message_sid": twilio_message.sid,
                "to": formatted_to,
                "status": twilio_message.status
            }

        except Exception as e:
            logger.error(f"Failed to send WhatsApp message to {to_phone}: {e}")
            return {"success": False, "error": str(e)}

    def send_checkin_reminder(
        self,
        to_phone: str,
        guest_name: str,
        hotel_name: str,
        checkin_time: str,
        room_type: str,
        booking_code: str
    ) -> Dict[str, Any]:
        """
        Send check-in reminder 1 hour before check-in.

        Args:
            to_phone: Guest's phone number
            guest_name: Guest's name
            hotel_name: Hotel name
            checkin_time: Formatted check-in time (e.g., "2:00 PM")
            room_type: Room type booked
            booking_code: Booking confirmation code

        Returns:
            Dict with send status
        """
        message = f"""Hello {guest_name}!

This is a reminder that your check-in at {hotel_name} is in 1 hour.

Booking: {booking_code}
Room Type: {room_type}
Check-in Time: {checkin_time}

We look forward to welcoming you!

Warm regards,
{hotel_name}"""

        return self.send_message(to_phone, message)

    def send_checkout_reminder(
        self,
        to_phone: str,
        guest_name: str,
        hotel_name: str,
        checkout_time: str,
        room_number: str,
        booking_code: str
    ) -> Dict[str, Any]:
        """
        Send check-out reminder 1 hour before check-out.

        Args:
            to_phone: Guest's phone number
            guest_name: Guest's name
            hotel_name: Hotel name
            checkout_time: Formatted check-out time (e.g., "11:00 AM")
            room_number: Room number
            booking_code: Booking confirmation code

        Returns:
            Dict with send status
        """
        message = f"""Good morning {guest_name}!

This is a friendly reminder that your checkout time is in 1 hour at {checkout_time}.

Room: {room_number}
Booking: {booking_code}

Please ensure you have all your belongings.

Thank you for staying with us at {hotel_name}!"""

        return self.send_message(to_phone, message)

    def send_booking_confirmation(
        self,
        to_phone: str,
        guest_name: str,
        hotel_name: str,
        booking_code: str,
        checkin_date: str,
        checkout_date: str,
        room_type: str
    ) -> Dict[str, Any]:
        """
        Send booking confirmation message.

        Args:
            to_phone: Guest's phone number
            guest_name: Guest's name
            hotel_name: Hotel name
            booking_code: Booking confirmation code
            checkin_date: Check-in date
            checkout_date: Check-out date
            room_type: Room type booked

        Returns:
            Dict with send status
        """
        message = f"""Hello {guest_name}!

Your booking at {hotel_name} is confirmed!

Booking Code: {booking_code}
Check-in: {checkin_date}
Check-out: {checkout_date}
Room Type: {room_type}

We look forward to hosting you!

Best regards,
{hotel_name}"""

        return self.send_message(to_phone, message)


def init_whatsapp_service(account_sid: str, auth_token: str, from_number: str) -> WhatsAppService:
    """
    Initialize the global WhatsApp service instance.

    Args:
        account_sid: Twilio Account SID
        auth_token: Twilio Auth Token
        from_number: Twilio WhatsApp number

    Returns:
        WhatsAppService instance
    """
    global _whatsapp_service
    _whatsapp_service = WhatsAppService(account_sid, auth_token, from_number)
    return _whatsapp_service


def get_whatsapp_service() -> Optional[WhatsAppService]:
    """
    Get the global WhatsApp service instance.

    Returns:
        WhatsAppService instance or None if not initialized
    """
    return _whatsapp_service
