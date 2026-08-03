"""
BILLING ENGINE - SINGLE SOURCE OF TRUTH

This module is the ONLY place where payment calculations happen.
All other code MUST call these functions for monetary calculations.

DO NOT:
- Create separate calculation logic elsewhere
- Hardcode tax rates in other files
- Reverse-calculate from totals

Tax Rules (Indian GST for Hotels):
- 12% GST for rooms ≤ ₹7,500/night
- 18% GST for rooms > ₹7,500/night
- GST split: 50% CGST + 50% SGST
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS - SINGLE DEFINITION (DO NOT DUPLICATE ELSEWHERE)
# ═══════════════════════════════════════════════════════════════════════════════

TAX_THRESHOLD = Decimal("7500.00")  # INR per night
TAX_RATE_LOW = Decimal("0.12")      # 12% for rooms ≤ ₹7,500/night
TAX_RATE_HIGH = Decimal("0.18")     # 18% for rooms > ₹7,500/night
MINIMUM_NIGHTS = 1                   # Minimum billable nights (same-day = 1 night)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES - Structured Output
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TaxBreakdown:
    """Tax calculation breakdown"""
    tax_rate: Decimal
    tax_rate_percent: int  # 12 or 18
    tax_amount: Decimal
    cgst: Decimal
    sgst: Decimal
    cgst_rate: Decimal  # 6% or 9%
    sgst_rate: Decimal  # 6% or 9%

    def to_dict(self) -> dict:
        return {
            "tax_rate": float(self.tax_rate),
            "tax_rate_percent": self.tax_rate_percent,
            "tax_amount": float(self.tax_amount),
            "cgst": float(self.cgst),
            "sgst": float(self.sgst),
            "cgst_rate": float(self.cgst_rate),
            "sgst_rate": float(self.sgst_rate),
        }


@dataclass
class StayCharges:
    """Complete charge breakdown for a stay"""
    nights: int
    nightly_rate: Decimal
    base_amount: Decimal
    tax: TaxBreakdown
    total_amount: Decimal

    @property
    def tax_amount(self) -> Decimal:
        return self.tax.tax_amount

    @property
    def tax_rate(self) -> Decimal:
        return self.tax.tax_rate

    @property
    def cgst(self) -> Decimal:
        return self.tax.cgst

    @property
    def sgst(self) -> Decimal:
        return self.tax.sgst

    def to_dict(self) -> dict:
        return {
            "nights": self.nights,
            "nightly_rate": float(self.nightly_rate),
            "base_amount": float(self.base_amount),
            "tax_amount": float(self.tax.tax_amount),
            "tax_rate": float(self.tax.tax_rate),
            "tax_rate_percent": self.tax.tax_rate_percent,
            "cgst": float(self.tax.cgst),
            "sgst": float(self.tax.sgst),
            "total_amount": float(self.total_amount),
        }


@dataclass
class ExtensionCharges:
    """Charges for stay extension"""
    original_nights: int
    new_nights: int
    extra_nights: int
    nightly_rate: Decimal
    original_charges: StayCharges
    new_charges: StayCharges
    delta_base: Decimal
    delta_tax: Decimal
    delta_total: Decimal

    def to_dict(self) -> dict:
        return {
            "original_nights": self.original_nights,
            "new_nights": self.new_nights,
            "extra_nights": self.extra_nights,
            "nightly_rate": float(self.nightly_rate),
            "original_charges": self.original_charges.to_dict(),
            "new_charges": self.new_charges.to_dict(),
            "delta_base": float(self.delta_base),
            "delta_tax": float(self.delta_tax),
            "delta_total": float(self.delta_total),
        }


@dataclass
class EarlyCheckoutRefund:
    """Refund calculation for early checkout"""
    original_nights: int
    actual_nights: int
    nights_refunded: int
    nightly_rate: Decimal
    original_charges: StayCharges
    actual_charges: StayCharges
    refund_base: Decimal
    refund_tax: Decimal
    refund_total: Decimal

    def to_dict(self) -> dict:
        return {
            "original_nights": self.original_nights,
            "actual_nights": self.actual_nights,
            "nights_refunded": self.nights_refunded,
            "nightly_rate": float(self.nightly_rate),
            "original_charges": self.original_charges.to_dict(),
            "actual_charges": self.actual_charges.to_dict(),
            "refund_base": float(self.refund_base),
            "refund_tax": float(self.refund_tax),
            "refund_total": float(self.refund_total),
        }


@dataclass
class FolioTotal:
    """Aggregated folio totals"""
    total_charges: Decimal
    total_tax: Decimal
    total_payments: Decimal
    balance_due: Decimal
    item_count: int

    def to_dict(self) -> dict:
        return {
            "total_charges": float(self.total_charges),
            "total_tax": float(self.total_tax),
            "total_payments": float(self.total_payments),
            "balance_due": float(self.balance_due),
            "item_count": self.item_count,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CORE CALCULATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _to_decimal(value: Any) -> Decimal:
    """Safely convert any numeric value to Decimal"""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _round_currency(value: Decimal) -> Decimal:
    """Round to 2 decimal places (currency precision)"""
    return value.quantize(Decimal("0.01"), ROUND_HALF_UP)


def calculate_nights(check_in: date, check_out: date) -> int:
    """
    Calculate billable nights between two dates.

    Args:
        check_in: Check-in date
        check_out: Check-out date

    Returns:
        Number of nights (minimum 1 for same-day checkout)
    """
    if isinstance(check_in, datetime):
        check_in = check_in.date()
    if isinstance(check_out, datetime):
        check_out = check_out.date()

    nights = (check_out - check_in).days
    return max(MINIMUM_NIGHTS, nights)


def get_tax_rate(nightly_rate: Decimal) -> Tuple[Decimal, int]:
    """
    Determine GST rate based on per-night room rate.

    Indian GST Rules:
    - Rooms ≤ ₹7,500/night: 12% GST
    - Rooms > ₹7,500/night: 18% GST

    Args:
        nightly_rate: Per-night room rate in INR

    Returns:
        Tuple of (tax_rate as decimal, tax_rate as percentage)
    """
    if nightly_rate <= TAX_THRESHOLD:
        return TAX_RATE_LOW, 12
    return TAX_RATE_HIGH, 18


def calculate_tax(base_amount: float, nightly_rate: float) -> TaxBreakdown:
    """
    Calculate tax breakdown for a given base amount.

    Args:
        base_amount: Total base amount (before tax)
        nightly_rate: Per-night rate (for determining tax slab)

    Returns:
        TaxBreakdown with all tax components
    """
    base = _to_decimal(base_amount)
    rate = _to_decimal(nightly_rate)

    # Get tax rate based on nightly rate
    tax_rate, tax_percent = get_tax_rate(rate)

    # Calculate total tax
    tax_amount = _round_currency(base * tax_rate)

    # Split into CGST and SGST (50% each)
    cgst_rate = tax_rate / 2
    sgst_rate = tax_rate / 2
    cgst = _round_currency(base * cgst_rate)
    sgst = tax_amount - cgst  # Remainder to avoid rounding drift

    return TaxBreakdown(
        tax_rate=tax_rate,
        tax_rate_percent=tax_percent,
        tax_amount=tax_amount,
        cgst=cgst,
        sgst=sgst,
        cgst_rate=cgst_rate,
        sgst_rate=sgst_rate,
    )


def calculate_stay_charges(nightly_rate: float, nights: int) -> StayCharges:
    """
    THE UNIVERSAL BILLING CALCULATION

    This is the PRIMARY function for all room charge calculations.
    All other code MUST use this function.

    Formula:
        base_amount = nightly_rate × nights
        tax_amount = base_amount × tax_rate
        total_amount = base_amount + tax_amount

    Args:
        nightly_rate: Per-night room rate in INR
        nights: Number of nights

    Returns:
        StayCharges with complete breakdown
    """
    rate = _to_decimal(nightly_rate)
    nights = max(MINIMUM_NIGHTS, nights)

    # Calculate base amount
    base_amount = _round_currency(rate * nights)

    # Calculate tax
    tax = calculate_tax(float(base_amount), float(rate))

    # Calculate total
    total_amount = _round_currency(base_amount + tax.tax_amount)

    logger.debug(
        f"calculate_stay_charges: rate={rate}, nights={nights}, "
        f"base={base_amount}, tax={tax.tax_amount}, total={total_amount}"
    )

    return StayCharges(
        nights=nights,
        nightly_rate=rate,
        base_amount=base_amount,
        tax=tax,
        total_amount=total_amount,
    )


def calculate_extension(
    old_nights: int,
    new_nights: int,
    nightly_rate: float,
) -> ExtensionCharges:
    """
    Calculate charges for stay extension.

    Args:
        old_nights: Original number of nights
        new_nights: New total number of nights
        nightly_rate: Per-night rate

    Returns:
        ExtensionCharges with delta amounts to add
    """
    if new_nights <= old_nights:
        raise ValueError(f"New nights ({new_nights}) must be greater than old nights ({old_nights})")

    extra_nights = new_nights - old_nights
    rate = _to_decimal(nightly_rate)

    # Calculate original and new charges
    original = calculate_stay_charges(float(rate), old_nights)
    new = calculate_stay_charges(float(rate), new_nights)

    # Calculate deltas (what to add)
    delta_base = new.base_amount - original.base_amount
    delta_tax = new.tax_amount - original.tax_amount
    delta_total = new.total_amount - original.total_amount

    return ExtensionCharges(
        original_nights=old_nights,
        new_nights=new_nights,
        extra_nights=extra_nights,
        nightly_rate=rate,
        original_charges=original,
        new_charges=new,
        delta_base=delta_base,
        delta_tax=delta_tax,
        delta_total=delta_total,
    )


def calculate_early_checkout(
    original_nights: int,
    actual_nights: int,
    nightly_rate: float,
) -> EarlyCheckoutRefund:
    """
    Calculate refund for early checkout.

    Args:
        original_nights: Originally booked nights
        actual_nights: Actual nights stayed
        nightly_rate: Per-night rate

    Returns:
        EarlyCheckoutRefund with refund amounts
    """
    actual_nights = max(MINIMUM_NIGHTS, actual_nights)

    if actual_nights >= original_nights:
        raise ValueError(f"Actual nights ({actual_nights}) must be less than original ({original_nights})")

    rate = _to_decimal(nightly_rate)
    nights_refunded = original_nights - actual_nights

    # Calculate original and actual charges
    original = calculate_stay_charges(float(rate), original_nights)
    actual = calculate_stay_charges(float(rate), actual_nights)

    # Calculate refunds
    refund_base = original.base_amount - actual.base_amount
    refund_tax = original.tax_amount - actual.tax_amount
    refund_total = original.total_amount - actual.total_amount

    return EarlyCheckoutRefund(
        original_nights=original_nights,
        actual_nights=actual_nights,
        nights_refunded=nights_refunded,
        nightly_rate=rate,
        original_charges=original,
        actual_charges=actual,
        refund_base=refund_base,
        refund_tax=refund_tax,
        refund_total=refund_total,
    )


def calculate_total(folio_items: List[Dict[str, Any]]) -> FolioTotal:
    """
    Calculate total from folio line items.

    Args:
        folio_items: List of folio line items with 'amount', 'item_type', 'is_voided'

    Returns:
        FolioTotal with aggregated amounts
    """
    total_charges = Decimal("0")
    total_tax = Decimal("0")
    total_payments = Decimal("0")
    item_count = 0

    for item in folio_items:
        if item.get("is_voided", False):
            continue

        amount = _to_decimal(item.get("amount", 0))
        item_type = item.get("item_type", "")

        if item_type == "payment" or amount < 0:
            # Payments are negative amounts
            total_payments += abs(amount)
        elif item_type == "tax":
            # Tax items
            total_tax += amount
            total_charges += amount
        else:
            # All other charges (room_charge, service, etc.)
            total_charges += amount
            # Include embedded tax if present
            tax_amount = _to_decimal(item.get("tax_amount", 0))
            if tax_amount > 0:
                total_tax += tax_amount

        item_count += 1

    balance_due = _round_currency(total_charges - total_payments)

    return FolioTotal(
        total_charges=_round_currency(total_charges),
        total_tax=_round_currency(total_tax),
        total_payments=_round_currency(total_payments),
        balance_due=balance_due,
        item_count=item_count,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP BOOKING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RoomChargeBreakdown:
    """Charge breakdown for a single room in a group"""
    booking_id: int
    room_number: Optional[str]
    room_type: Optional[str]
    nightly_rate: Decimal
    nights: int
    charges: StayCharges

    def to_dict(self) -> dict:
        return {
            "booking_id": self.booking_id,
            "room_number": self.room_number,
            "room_type": self.room_type,
            "nightly_rate": float(self.nightly_rate),
            "nights": self.nights,
            "charges": self.charges.to_dict(),
        }


@dataclass
class GroupBookingTotal:
    """Aggregated totals for a group booking"""
    booking_count: int
    total_nights: int
    total_base: Decimal
    total_tax: Decimal
    total_amount: Decimal
    total_payments: Decimal
    total_balance: Decimal
    room_breakdown: List[RoomChargeBreakdown]

    def to_dict(self) -> dict:
        return {
            "booking_count": self.booking_count,
            "total_nights": self.total_nights,
            "total_base": float(self.total_base),
            "total_tax": float(self.total_tax),
            "total_amount": float(self.total_amount),
            "total_payments": float(self.total_payments),
            "total_balance": float(self.total_balance),
            "room_breakdown": [r.to_dict() for r in self.room_breakdown],
        }


def calculate_group_total(
    bookings: List[Dict[str, Any]],
    payments: Optional[Decimal] = None,
) -> GroupBookingTotal:
    """
    Calculate consolidated totals for a group booking.

    Args:
        bookings: List of booking dicts with nightly_rate, nights, room info
        payments: Total payments made (optional)

    Returns:
        GroupBookingTotal with consolidated amounts
    """
    room_breakdown = []
    total_base = Decimal("0")
    total_tax = Decimal("0")
    total_amount = Decimal("0")
    total_nights = 0

    for booking in bookings:
        nightly_rate = _to_decimal(booking.get("nightly_rate", 0))
        nights = booking.get("nights", 1)

        # Calculate charges for this room
        charges = calculate_stay_charges(float(nightly_rate), nights)

        # Add to breakdown
        room_breakdown.append(RoomChargeBreakdown(
            booking_id=booking.get("id", 0),
            room_number=booking.get("room_number"),
            room_type=booking.get("room_type"),
            nightly_rate=nightly_rate,
            nights=nights,
            charges=charges,
        ))

        # Accumulate totals
        total_base += charges.base_amount
        total_tax += charges.tax_amount
        total_amount += charges.total_amount
        total_nights += nights

    total_payments = _to_decimal(payments) if payments else Decimal("0")
    total_balance = _round_currency(total_amount - total_payments)

    return GroupBookingTotal(
        booking_count=len(bookings),
        total_nights=total_nights,
        total_base=_round_currency(total_base),
        total_tax=_round_currency(total_tax),
        total_amount=_round_currency(total_amount),
        total_payments=total_payments,
        total_balance=total_balance,
        room_breakdown=room_breakdown,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS FOR FOLIO LINE ITEM CREATION
# ═══════════════════════════════════════════════════════════════════════════════

def create_room_charge_description(
    nights: int,
    nightly_rate: float,
    check_in: Optional[date] = None,
    check_out: Optional[date] = None,
) -> str:
    """Generate description for room charge line item"""
    rate_str = f"₹{nightly_rate:,.2f}"
    if nights == 1:
        if check_in:
            return f"Room charge – {check_in.strftime('%Y-%m-%d')} @ {rate_str}"
        return f"Room charge – 1 night @ {rate_str}"
    else:
        if check_in and check_out:
            return f"Room charges – {check_in.strftime('%Y-%m-%d')} to {check_out.strftime('%Y-%m-%d')} ({nights} nights @ {rate_str}/night)"
        return f"Room charges – {nights} nights @ {rate_str}/night"


def create_tax_description(tax: TaxBreakdown) -> str:
    """Generate description for tax line item"""
    return f"GST @ {tax.tax_rate_percent}% (CGST: ₹{float(tax.cgst):,.2f} + SGST: ₹{float(tax.sgst):,.2f})"


def create_extension_description(extra_nights: int, nightly_rate: float) -> str:
    """Generate description for extension charge"""
    rate_str = f"₹{nightly_rate:,.2f}"
    return f"Extended stay – {extra_nights} additional night(s) @ {rate_str}/night"


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def validate_nightly_rate(rate: float) -> bool:
    """Validate that nightly rate is positive"""
    return rate is not None and rate > 0


def validate_nights(nights: int) -> bool:
    """Validate that nights is at least minimum"""
    return nights is not None and nights >= MINIMUM_NIGHTS


def validate_dates(check_in: date, check_out: date) -> bool:
    """Validate that check_out is after check_in"""
    return check_out >= check_in
