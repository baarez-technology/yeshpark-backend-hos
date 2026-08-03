"""
Digital Key Service
Handles generation, validation, and management of digital room keys with QR codes.

Features:
- Generate secure digital keys with QR codes
- Validate keys for housekeeping/staff scanning
- Track scan history and key usage
- Email digital keys to guests
"""

import secrets
import hashlib
import base64
import json
import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional, Tuple
from io import BytesIO

from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.operations import DigitalKey, DigitalKeyScan
from app.models.precheckin import PreCheckIn
from app.models.reservations import Guest, Reservation
from app.models.inventory import Room

logger = logging.getLogger("services.digital_key")


class DigitalKeyService:
    """Service for managing digital room keys"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._qr_available = self._check_qr_library()

    def _check_qr_library(self) -> bool:
        """Check if QR code library is available"""
        try:
            import qrcode
            return True
        except ImportError:
            logger.warning("qrcode library not installed. QR images will not be generated.")
            return False

    def _generate_key_code(self) -> str:
        """Generate a unique key code"""
        return f"DK-{secrets.token_urlsafe(8).upper()}"

    def _generate_secret(self) -> Tuple[str, str]:
        """Generate a secret and its hash for validation"""
        secret = secrets.token_urlsafe(16)
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        return secret, secret_hash

    def _create_qr_payload(
        self,
        key_code: str,
        secret: str,
        room_number: str,
        check_in_date: date,
        check_out_date: date,
        guest_name: str
    ) -> str:
        """Create the encrypted payload for QR code"""
        payload = {
            "k": key_code,  # Key code
            "s": secret,    # Secret for validation
            "r": room_number,  # Room number
            "ci": check_in_date.isoformat(),  # Check-in date
            "co": check_out_date.isoformat(),  # Check-out date
            "g": guest_name[:30],  # Guest name (truncated)
            "v": "1",  # Version
            "t": datetime.utcnow().isoformat()  # Timestamp
        }
        # Encode as base64 JSON
        json_str = json.dumps(payload, separators=(',', ':'))
        encoded = base64.urlsafe_b64encode(json_str.encode()).decode()
        return f"GLIMMORA:{encoded}"

    def _decode_qr_payload(self, qr_data: str) -> Optional[Dict[str, Any]]:
        """Decode and validate QR code payload"""
        try:
            if not qr_data.startswith("GLIMMORA:"):
                return None
            encoded = qr_data[9:]  # Remove "GLIMMORA:" prefix
            decoded = base64.urlsafe_b64decode(encoded.encode()).decode()
            return json.loads(decoded)
        except Exception as e:
            logger.error(f"Failed to decode QR payload: {e}")
            return None

    def _generate_qr_image(self, data: str) -> Optional[str]:
        """Generate QR code image as base64 string"""
        if not self._qr_available:
            return None

        try:
            import qrcode
            from qrcode.image.styledpil import StyledPilImage
            from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

            # Create QR code with styling
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )
            qr.add_data(data)
            qr.make(fit=True)

            # Create image with rounded corners style
            try:
                img = qr.make_image(
                    image_factory=StyledPilImage,
                    module_drawer=RoundedModuleDrawer()
                )
            except:
                # Fallback to basic image if styled image fails
                img = qr.make_image(fill_color="black", back_color="white")

            # Convert to base64
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()

            return img_base64

        except Exception as e:
            logger.error(f"Failed to generate QR image: {e}")
            return None

    async def generate_digital_key(
        self,
        guest_id: int,
        room_id: int,
        room_number: str,
        check_in_date: date,
        check_out_date: date,
        guest_name: str,
        guest_email: Optional[str] = None,
        booking_id: Optional[int] = None,
        reservation_id: Optional[int] = None,
        precheckin_id: Optional[int] = None
    ) -> DigitalKey:
        """
        Generate a new digital key with QR code.

        Args:
            guest_id: Guest ID
            room_id: Room ID
            room_number: Room number string
            check_in_date: Check-in date
            check_out_date: Check-out date
            guest_name: Guest full name
            guest_email: Guest email for sending key
            booking_id: Optional booking ID
            reservation_id: Optional reservation ID
            precheckin_id: Optional pre-checkin ID

        Returns:
            DigitalKey object with QR code
        """
        # Generate key code and secret
        key_code = self._generate_key_code()
        secret, secret_hash = self._generate_secret()

        # Create QR payload
        qr_data = self._create_qr_payload(
            key_code=key_code,
            secret=secret,
            room_number=room_number,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            guest_name=guest_name
        )

        # Generate QR image
        qr_image_base64 = self._generate_qr_image(qr_data)

        # Set validity period (from check-in 2pm to check-out 11am)
        valid_from = datetime.combine(check_in_date, datetime.min.time().replace(hour=14))
        valid_until = datetime.combine(check_out_date, datetime.min.time().replace(hour=11))

        # Create digital key record
        digital_key = DigitalKey(
            key_code=key_code,
            booking_id=booking_id,
            reservation_id=reservation_id,
            precheckin_id=precheckin_id,
            guest_id=guest_id,
            room_id=room_id,
            room_number=room_number,
            qr_data=qr_data,
            qr_image_base64=qr_image_base64,
            valid_from=valid_from,
            valid_until=valid_until,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            status="active",
            activated_at=datetime.utcnow(),
            secret_hash=secret_hash,
            email_address=guest_email
        )

        self.db.add(digital_key)
        await self.db.commit()
        await self.db.refresh(digital_key)

        logger.info(f"Generated digital key {key_code} for room {room_number}, guest {guest_id}")

        return digital_key

    async def validate_key(
        self,
        qr_data: str,
        staff_id: int,
        expected_room_number: Optional[str] = None,
        scan_location: str = "housekeeping"
    ) -> Dict[str, Any]:
        """
        Validate a digital key from QR code scan.

        Args:
            qr_data: The raw QR code data
            staff_id: ID of staff member scanning
            expected_room_number: Optional room number to validate against
            scan_location: Where the scan occurred (housekeeping, front_desk, room_door)

        Returns:
            Validation result with guest and booking details
        """
        now = datetime.utcnow()
        today = now.date()

        # Decode QR payload
        payload = self._decode_qr_payload(qr_data)
        if not payload:
            return await self._record_scan(
                None, staff_id, False, "invalid_code",
                scan_location, expected_room_number,
                message="Invalid QR code format"
            )

        key_code = payload.get("k")
        secret = payload.get("s")
        room_number = payload.get("r")

        # Find the digital key
        result = await self.db.execute(
            select(DigitalKey).where(DigitalKey.key_code == key_code)
        )
        digital_key = result.scalar_one_or_none()

        if not digital_key:
            return await self._record_scan(
                None, staff_id, False, "invalid_code",
                scan_location, expected_room_number,
                message="Digital key not found"
            )

        # Validate secret hash
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        if secret_hash != digital_key.secret_hash:
            return await self._record_scan(
                digital_key.id, staff_id, False, "invalid_code",
                scan_location, expected_room_number,
                message="Invalid key secret"
            )

        # Check if revoked
        if digital_key.status == "revoked":
            return await self._record_scan(
                digital_key.id, staff_id, False, "revoked",
                scan_location, expected_room_number,
                message="This digital key has been revoked"
            )

        # Check expiry
        if digital_key.status == "expired" or now > digital_key.valid_until:
            if digital_key.status != "expired":
                digital_key.status = "expired"
                await self.db.commit()
            return await self._record_scan(
                digital_key.id, staff_id, False, "expired",
                scan_location, expected_room_number,
                message="This digital key has expired"
            )

        # Check if within valid date range
        if today < digital_key.check_in_date or today > digital_key.check_out_date:
            return await self._record_scan(
                digital_key.id, staff_id, False, "wrong_date",
                scan_location, expected_room_number,
                message=f"Key is valid from {digital_key.check_in_date} to {digital_key.check_out_date}"
            )

        # Check room number if expected
        if expected_room_number and digital_key.room_number != expected_room_number:
            return await self._record_scan(
                digital_key.id, staff_id, False, "wrong_room",
                scan_location, expected_room_number,
                message=f"Key is for room {digital_key.room_number}, not {expected_room_number}"
            )

        # Key is valid - update scan count
        digital_key.scan_count += 1
        digital_key.last_scanned_at = now
        digital_key.last_scanned_by = staff_id
        digital_key.updated_at = now
        await self.db.commit()

        # Get guest info
        guest_result = await self.db.execute(
            select(Guest).where(Guest.id == digital_key.guest_id)
        )
        guest = guest_result.scalar_one_or_none()

        # Record successful scan
        return await self._record_scan(
            digital_key.id, staff_id, True, "valid",
            scan_location, digital_key.room_number,
            message="Key validated successfully",
            extra_data={
                "key_code": digital_key.key_code,
                "room_number": digital_key.room_number,
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
                "guest_id": digital_key.guest_id,
                "check_in_date": digital_key.check_in_date.isoformat(),
                "check_out_date": digital_key.check_out_date.isoformat(),
                "booking_id": digital_key.booking_id,
                "reservation_id": digital_key.reservation_id,
                "scan_count": digital_key.scan_count,
                "valid_until": digital_key.valid_until.isoformat()
            }
        )

    async def _record_scan(
        self,
        digital_key_id: Optional[int],
        staff_id: int,
        is_valid: bool,
        validation_result: str,
        scan_location: str,
        room_number: Optional[str],
        message: str,
        extra_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Record a scan attempt and return result"""
        if digital_key_id:
            scan_record = DigitalKeyScan(
                digital_key_id=digital_key_id,
                scanned_by=staff_id,
                is_valid=is_valid,
                validation_result=validation_result,
                scan_location=scan_location,
                room_number=room_number,
                notes=message
            )
            self.db.add(scan_record)
            await self.db.commit()

        result = {
            "valid": is_valid,
            "result": validation_result,
            "message": message,
            "scanned_at": datetime.utcnow().isoformat()
        }

        if extra_data:
            result.update(extra_data)

        return result

    async def get_key_by_code(self, key_code: str) -> Optional[DigitalKey]:
        """Get digital key by key code"""
        result = await self.db.execute(
            select(DigitalKey).where(DigitalKey.key_code == key_code)
        )
        return result.scalar_one_or_none()

    async def get_keys_for_guest(self, guest_id: int) -> list:
        """Get all digital keys for a guest"""
        result = await self.db.execute(
            select(DigitalKey)
            .where(DigitalKey.guest_id == guest_id)
            .order_by(DigitalKey.created_at.desc())
        )
        return result.scalars().all()

    async def get_active_key_for_room(self, room_number: str) -> Optional[DigitalKey]:
        """Get active digital key for a room"""
        today = date.today()
        result = await self.db.execute(
            select(DigitalKey)
            .where(
                and_(
                    DigitalKey.room_number == room_number,
                    DigitalKey.status == "active",
                    DigitalKey.check_in_date <= today,
                    DigitalKey.check_out_date >= today
                )
            )
        )
        return result.scalar_one_or_none()

    async def revoke_key(
        self,
        key_code: str,
        staff_id: int,
        reason: str
    ) -> bool:
        """Revoke a digital key"""
        digital_key = await self.get_key_by_code(key_code)
        if not digital_key:
            return False

        digital_key.status = "revoked"
        digital_key.revoked_at = datetime.utcnow()
        digital_key.revoked_by = staff_id
        digital_key.revoke_reason = reason
        digital_key.updated_at = datetime.utcnow()

        await self.db.commit()
        logger.info(f"Revoked digital key {key_code} by staff {staff_id}: {reason}")
        return True

    async def get_scan_history(
        self,
        digital_key_id: Optional[int] = None,
        room_number: Optional[str] = None,
        staff_id: Optional[int] = None,
        limit: int = 50
    ) -> list:
        """Get scan history with optional filters"""
        query = select(DigitalKeyScan).order_by(DigitalKeyScan.scanned_at.desc())

        conditions = []
        if digital_key_id:
            conditions.append(DigitalKeyScan.digital_key_id == digital_key_id)
        if room_number:
            conditions.append(DigitalKeyScan.room_number == room_number)
        if staff_id:
            conditions.append(DigitalKeyScan.scanned_by == staff_id)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def mark_email_sent(self, key_code: str) -> bool:
        """Mark that the digital key email was sent"""
        digital_key = await self.get_key_by_code(key_code)
        if not digital_key:
            return False

        digital_key.email_sent = True
        digital_key.email_sent_at = datetime.utcnow()
        digital_key.updated_at = datetime.utcnow()
        await self.db.commit()
        return True


def get_digital_key_service(db: AsyncSession) -> DigitalKeyService:
    """Factory function to create DigitalKeyService"""
    return DigitalKeyService(db)
