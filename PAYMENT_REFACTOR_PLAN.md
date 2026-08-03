# Payment Calculation Refactor Plan

## Executive Summary

The current payment system has **multiple calculation paths** leading to inconsistencies. This document outlines the problems and provides a unified solution.

---

## PART 1: ROOT PROBLEM ANALYSIS

### 1.1 Current Architecture (Problematic)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CURRENT PAYMENT CALCULATION PATHS                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  BOOKING CREATION ──┬── calculate_booking_taxes() ─── tax.py (12%/18%)     │
│                     └── pricing_service.py (dynamic rates)                  │
│                                                                             │
│  CHECK-IN ──────────┬── get_effective_nightly_rate() ─ billing_service.py  │
│                     └── create_room_charge_line_item() (posts 1 night)     │
│                                                                             │
│  NIGHT AUDIT ───────┬── booking.base_price / nights ── DIFFERENT FORMULA!  │
│                     └── apply_tax_to_line_item() ──── database tax slabs   │
│                                                                             │
│  EXTENDED STAY ─────┬── total_price / nights / 1.17 ── HARDCODED 17% TAX!  │
│                     └── additional * 1.17 ─────────── WRONG TAX RATE!      │
│                                                                             │
│  CHECKOUT ──────────┬── get_effective_nightly_rate() ─ billing_service.py  │
│                     └── calculate_room_charges() ──── billing_service.py   │
│                                                                             │
│  FOLIO ─────────────┬── recalculate_folio() ───────── sum of line items    │
│                     └── sync_booking_payment() ────── updates booking      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Specific Inconsistencies Found

#### Issue #1: Extended Stay Hardcoded Tax (CRITICAL)
**Location:** `app/api/v1/bookings.py:4585-4594`
```python
# WRONG: Hardcodes 1.17 (17% tax)
price_per_night = (booking.total_price / original_nights / 1.17)
additional_charge = price_per_night * extra_nights * 1.17
```
**Problem:** Should be 12% (≤₹7500/night) or 18% (>₹7500/night)

#### Issue #2: Night Audit Rate Calculation
**Location:** `app/api/v1/frontdesk.py:1275-1277`
```python
# Night Audit does its own calculation
nights = max(1, booking.nights or 1)
nightly_rate = round((booking.base_price or 0) / nights, 2)
```
**Problem:** Different from `get_effective_nightly_rate()` used elsewhere

#### Issue #3: Reverse Tax Calculation Assumes 12%
**Location:** `app/services/billing_service.py:223`
```python
# Assumes 12% tax when reversing
base_estimate = booking.total_price / 1.12
```
**Problem:** Will be wrong for rooms > ₹7500/night (should be 18%)

#### Issue #4: Duplicate Tax Constants
**Location 1:** `app/core/tax.py:167-171`
**Location 2:** `app/services/billing_service.py:31-34`
```python
# Duplicated in both files
ROOM_TAX_THRESHOLD = 7500
ROOM_TAX_RATE_LOW = 0.12
ROOM_TAX_RATE_HIGH = 0.18
```

#### Issue #5: Frontend Service Fee
**Location:** `src/hooks/useGSTCalculator.ts:33`
```python
SERVICE_FEE_RATE = 0.05  # 5% service fee
```
**Problem:** Backend doesn't apply this, causing mismatch

#### Issue #6: booking.base_price Semantics
- Stored as TOTAL for all nights (not per-night)
- But some code divides by nights, others don't
- Confusing and error-prone

#### Issue #7: Night Audit Dependency
- Room charges posted incrementally by night audit
- If night audit doesn't run, charges are missing
- Check-in posts first night, night audit posts rest
- Creates partial charge states

---

## PART 2: UNIFIED PAYMENT FLOW DESIGN

### 2.1 Core Principle: Single Source of Truth

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    NEW UNIFIED PAYMENT FLOW                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    SINGLE CALCULATION ENGINE                         │   │
│  │                                                                      │   │
│  │  app/services/billing_engine.py (NEW FILE)                          │   │
│  │                                                                      │   │
│  │  calculate_stay_charges(                                            │   │
│  │      room_type_id: int,                                             │   │
│  │      check_in: date,                                                │   │
│  │      check_out: date,                                               │   │
│  │      rate_override: Optional[float] = None                          │   │
│  │  ) -> StayCharges                                                   │   │
│  │                                                                      │   │
│  │  Returns:                                                            │   │
│  │    - nights: int                                                     │   │
│  │    - nightly_rate: float                                            │   │
│  │    - base_amount: float (rate × nights)                             │   │
│  │    - tax_rate: float (0.12 or 0.18)                                 │   │
│  │    - tax_amount: float                                              │   │
│  │    - cgst: float                                                    │   │
│  │    - sgst: float                                                    │   │
│  │    - total_amount: float                                            │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│           ┌──────────────────┼──────────────────┐                          │
│           │                  │                  │                          │
│           ▼                  ▼                  ▼                          │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                  │
│   │    BOOKING    │  │    FOLIO      │  │   CHECKOUT    │                  │
│   │   CREATION    │  │   CHARGES     │  │   BILLING     │                  │
│   │               │  │               │  │               │                  │
│   │ Uses engine   │  │ Uses engine   │  │ Uses engine   │                  │
│   │ to calculate  │  │ to post ALL   │  │ to calculate  │                  │
│   │ total upfront │  │ charges at    │  │ final amount  │                  │
│   │               │  │ CHECK-IN      │  │               │                  │
│   └───────────────┘  └───────────────┘  └───────────────┘                  │
│                                                                             │
│   NO NIGHT AUDIT DEPENDENCY FOR CHARGES                                    │
│   Night Audit only: room status updates, reports, housekeeping tasks       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 The Formula (Single, Universal)

```python
# UNIVERSAL FORMULA - Used everywhere
def calculate_stay_charges(nightly_rate: float, nights: int) -> dict:
    """
    THE ONLY FORMULA FOR PAYMENT CALCULATION

    Args:
        nightly_rate: Per-night room rate (from room_type.base_price or override)
        nights: Number of stay nights (check_out - check_in).days, minimum 1

    Returns:
        Complete charge breakdown
    """
    # Step 1: Calculate nights (minimum 1 for same-day)
    nights = max(1, nights)

    # Step 2: Calculate base amount
    base_amount = round(nightly_rate * nights, 2)

    # Step 3: Determine tax rate based on PER-NIGHT rate
    if nightly_rate <= 7500:
        tax_rate = 0.12  # 12% GST
    else:
        tax_rate = 0.18  # 18% GST

    # Step 4: Calculate tax
    tax_amount = round(base_amount * tax_rate, 2)
    cgst = round(tax_amount / 2, 2)
    sgst = round(tax_amount - cgst, 2)  # Avoid rounding errors

    # Step 5: Calculate total
    total_amount = round(base_amount + tax_amount, 2)

    return {
        "nights": nights,
        "nightly_rate": nightly_rate,
        "base_amount": base_amount,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "cgst": cgst,
        "sgst": sgst,
        "total_amount": total_amount,
    }
```

### 2.3 Rate Determination (Single Source)

```python
def get_nightly_rate(session, booking_or_room_type) -> float:
    """
    SINGLE SOURCE FOR NIGHTLY RATE

    Priority:
    1. room_type.base_price (canonical source)
    2. booking.nightly_rate (new field, stores rate at booking time)

    NEVER reverse-calculate from total_price
    """
    if hasattr(booking_or_room_type, 'nightly_rate') and booking_or_room_type.nightly_rate:
        return float(booking_or_room_type.nightly_rate)

    room_type_id = getattr(booking_or_room_type, 'room_type_id', None)
    if room_type_id:
        room_type = await session.get(RoomType, room_type_id)
        if room_type and room_type.base_price:
            return float(room_type.base_price)

    raise ValueError("Cannot determine nightly rate - no room type or rate available")
```

---

## PART 3: IMPLEMENTATION PLAN

### Phase 1: Create Billing Engine (Day 1)

#### 1.1 New File: `app/services/billing_engine.py`

```python
"""
SINGLE SOURCE OF TRUTH FOR ALL BILLING CALCULATIONS

All payment calculations MUST go through this module.
Do NOT create separate calculation logic elsewhere.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP

# Constants - SINGLE DEFINITION
TAX_THRESHOLD = Decimal("7500.00")  # INR per night
TAX_RATE_LOW = Decimal("0.12")      # 12% for ≤ ₹7500
TAX_RATE_HIGH = Decimal("0.18")     # 18% for > ₹7500
MINIMUM_NIGHTS = 1


@dataclass
class StayCharges:
    """Immutable charge breakdown"""
    nights: int
    nightly_rate: Decimal
    base_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    cgst: Decimal
    sgst: Decimal
    total_amount: Decimal

    def to_dict(self) -> dict:
        return {
            "nights": self.nights,
            "nightly_rate": float(self.nightly_rate),
            "base_amount": float(self.base_amount),
            "tax_rate": float(self.tax_rate),
            "tax_amount": float(self.tax_amount),
            "cgst": float(self.cgst),
            "sgst": float(self.sgst),
            "total_amount": float(self.total_amount),
        }


def calculate_nights(check_in: date, check_out: date) -> int:
    """Calculate billable nights with minimum of 1"""
    nights = (check_out - check_in).days
    return max(MINIMUM_NIGHTS, nights)


def get_tax_rate(nightly_rate: Decimal) -> Decimal:
    """Determine GST rate based on per-night rate"""
    if nightly_rate <= TAX_THRESHOLD:
        return TAX_RATE_LOW
    return TAX_RATE_HIGH


def calculate_stay_charges(
    nightly_rate: float,
    nights: int,
) -> StayCharges:
    """
    THE UNIVERSAL BILLING CALCULATION

    This is the ONLY function that should calculate charges.
    All other code must call this function.
    """
    rate = Decimal(str(nightly_rate))
    nights = max(MINIMUM_NIGHTS, nights)

    # Base amount
    base_amount = (rate * nights).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Tax calculation
    tax_rate = get_tax_rate(rate)
    tax_amount = (base_amount * tax_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Split into CGST/SGST
    cgst = (tax_amount / 2).quantize(Decimal("0.01"), ROUND_HALF_UP)
    sgst = tax_amount - cgst  # Remainder to avoid rounding drift

    # Total
    total_amount = base_amount + tax_amount

    return StayCharges(
        nights=nights,
        nightly_rate=rate,
        base_amount=base_amount,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        cgst=cgst,
        sgst=sgst,
        total_amount=total_amount,
    )


def calculate_extension_charges(
    nightly_rate: float,
    extra_nights: int,
) -> StayCharges:
    """Calculate charges for stay extension"""
    return calculate_stay_charges(nightly_rate, extra_nights)


def calculate_early_checkout_refund(
    nightly_rate: float,
    original_nights: int,
    actual_nights: int,
) -> dict:
    """Calculate refund for early checkout"""
    original = calculate_stay_charges(nightly_rate, original_nights)
    actual = calculate_stay_charges(nightly_rate, actual_nights)

    refund_base = original.base_amount - actual.base_amount
    refund_tax = original.tax_amount - actual.tax_amount
    refund_total = original.total_amount - actual.total_amount

    return {
        "original_charges": original.to_dict(),
        "actual_charges": actual.to_dict(),
        "refund_base": float(refund_base),
        "refund_tax": float(refund_tax),
        "refund_total": float(refund_total),
        "nights_refunded": original_nights - actual_nights,
    }
```

### Phase 2: Add nightly_rate Field to Booking (Day 1)

#### 2.1 Migration: Add `nightly_rate` column

```python
# In app/models/reservations.py - Booking model
class Booking(SQLModel, table=True):
    # ... existing fields ...

    # NEW: Store nightly rate at booking time (immutable)
    nightly_rate: Optional[float] = Field(default=None)

    # CLARIFY existing fields
    base_price: float = 0  # Total base for all nights (nightly_rate × nights)
    taxes: float = 0       # Total tax for all nights
    total_price: float = 0 # Grand total (base_price + taxes)
```

### Phase 3: Remove Night Audit Charge Posting (Day 2)

#### 3.1 Current Flow (Remove This):
```
Check-in → Post 1st night → Night Audit → Post remaining nights
```

#### 3.2 New Flow:
```
Check-in → Post ALL nights at once
```

#### 3.3 Modify Check-in in `frontdesk.py`:

```python
# BEFORE (posts only 1 night):
room_charge, tax_item = await create_room_charge_line_item(
    folio_id=folio.id,
    per_night_rate=nightly_rate,
    nights=1,  # Only first night
    ...
)

# AFTER (posts ALL nights):
from app.services.billing_engine import calculate_stay_charges

# Get total stay charges
charges = calculate_stay_charges(nightly_rate, booking.nights)

# Create single room charge line item for total base
room_charge = FolioLineItem(
    folio_id=folio.id,
    item_type="room_charge",
    description=f"Room charges: {booking.nights} night(s) @ ₹{nightly_rate:,.2f}/night",
    quantity=booking.nights,
    unit_price=nightly_rate,
    amount=float(charges.base_amount),
    posted_by=current_user.id,
)

# Create single tax line item
tax_item = FolioLineItem(
    folio_id=folio.id,
    item_type="tax",
    description=f"GST @ {float(charges.tax_rate)*100:.0f}% (CGST: ₹{charges.cgst:,.2f} + SGST: ₹{charges.sgst:,.2f})",
    quantity=1,
    unit_price=float(charges.tax_amount),
    amount=float(charges.tax_amount),
    tax_amount=float(charges.tax_amount),
    tax_component_1_name="CGST",
    tax_component_1_pct=float(charges.tax_rate) * 50,
    tax_component_1_amount=float(charges.cgst),
    tax_component_2_name="SGST",
    tax_component_2_pct=float(charges.tax_rate) * 50,
    tax_component_2_amount=float(charges.sgst),
    posted_by=current_user.id,
)
```

#### 3.4 Modify Night Audit (Remove charge posting):

```python
# In frontdesk.py - run_night_audit()

# REMOVE: Step 3 (Post Room & Tax Charges)
# This entire section should be removed

# KEEP:
# - Step 1: Day Close / Business Date Advance
# - Step 2: Room Status Updates (occupied rooms → dirty)
# - Step 4: Generate Reports
# - Step 5: Finalize
```

### Phase 4: Fix Extended Stay (Day 2)

#### 4.1 Update `extend_stay_async()`:

```python
# BEFORE (wrong):
price_per_night = (booking.total_price / original_nights / 1.17)
additional_charge = price_per_night * extra_nights * 1.17

# AFTER (correct):
from app.services.billing_engine import calculate_extension_charges

# Get nightly rate from stored field or room type
nightly_rate = booking.nightly_rate
if not nightly_rate:
    room_type = await session.get(RoomType, booking.room_type_id)
    nightly_rate = float(room_type.base_price)

# Calculate extension charges correctly
extension = calculate_extension_charges(nightly_rate, extra_nights)

# Post to folio
extension_charge = FolioLineItem(
    folio_id=folio.id,
    item_type="room_charge",
    description=f"Extended stay: {extra_nights} night(s) @ ₹{nightly_rate:,.2f}/night",
    quantity=extra_nights,
    unit_price=nightly_rate,
    amount=float(extension.base_amount),
    ...
)

extension_tax = FolioLineItem(
    folio_id=folio.id,
    item_type="tax",
    description=f"GST on extension @ {float(extension.tax_rate)*100:.0f}%",
    amount=float(extension.tax_amount),
    ...
)

# Update booking
booking.nights += extra_nights
booking.base_price += float(extension.base_amount)
booking.taxes += float(extension.tax_amount)
booking.total_price += float(extension.total_amount)
booking.departure_date = new_checkout
```

### Phase 5: Update Booking Creation (Day 2)

#### 5.1 Store nightly_rate at booking time:

```python
# In create_booking()

# Get nightly rate
if payload.ratePerNight and payload.ratePerNight > 0:
    nightly_rate = payload.ratePerNight
elif room_type_obj and room_type_obj.base_price:
    nightly_rate = float(room_type_obj.base_price)
else:
    raise HTTPException(400, "Cannot determine room rate")

# Calculate charges using billing engine
from app.services.billing_engine import calculate_stay_charges
charges = calculate_stay_charges(nightly_rate, nights)

# Create booking with all fields properly set
booking = Booking(
    ...
    nights=nights,
    nightly_rate=nightly_rate,  # NEW: Store rate
    base_price=float(charges.base_amount),
    taxes=float(charges.tax_amount),
    total_price=float(charges.total_amount),
    balance_due=float(charges.total_amount),
    ...
)
```

### Phase 6: Update Checkout (Day 3)

#### 6.1 Early Checkout Handling:

```python
# In checkout_booking()

from app.services.billing_engine import (
    calculate_stay_charges,
    calculate_early_checkout_refund,
)

# Calculate actual nights
actual_nights = (actual_checkout - check_in_date).days
actual_nights = max(1, actual_nights)

# Get nightly rate
nightly_rate = booking.nightly_rate or await get_room_type_rate(session, booking)

if actual_nights < booking.nights:
    # Early checkout - calculate refund
    refund_info = calculate_early_checkout_refund(
        nightly_rate, booking.nights, actual_nights
    )

    # Update booking
    booking.nights = actual_nights
    booking.base_price = refund_info["actual_charges"]["base_amount"]
    booking.taxes = refund_info["actual_charges"]["tax_amount"]
    booking.total_price = refund_info["actual_charges"]["total_amount"]

    # Void old charges, post new ones
    await void_and_repost_charges(session, folio, nightly_rate, actual_nights)
```

### Phase 7: Group Booking Updates (Day 3)

#### 7.1 Parent Booking Shows All:

```python
# When creating group booking
parent_total = sum(child.total_price for child in child_bookings)
parent.total_price = parent_total
parent.balance_due = parent_total

# For folio display
async def get_group_totals(session, parent_booking):
    children = await get_child_bookings(session, parent_booking.group_booking_id)

    total_charges = sum(c.total_price for c in [parent_booking] + children)
    total_payments = sum(get_folio_payments(c) for c in [parent_booking] + children)

    return {
        "total_charges": total_charges,
        "total_payments": total_payments,
        "total_balance": total_charges - total_payments,
        "booking_count": len(children) + 1,
        "room_breakdown": [
            {
                "booking_id": c.id,
                "room_number": c.room.number if c.room else None,
                "room_type": c.room_type.name if c.room_type else None,
                "total_charges": c.total_price,
            }
            for c in [parent_booking] + children
        ]
    }
```

### Phase 8: Frontend Alignment (Day 4)

#### 8.1 Remove Service Fee:
```typescript
// In useGSTCalculator.ts
// REMOVE: SERVICE_FEE_RATE = 0.05
// The backend doesn't charge service fee, frontend shouldn't show it
```

#### 8.2 Simplify GuestBillModal:
```typescript
// REMOVE reverse calculation logic
// Backend now always provides:
// - booking.nightly_rate
// - booking.base_price
// - booking.taxes
// - booking.total_price

// Just display these values directly
const basePrice = booking.basePrice || booking.base_price;
const taxes = booking.taxes;
const totalPrice = booking.totalPrice || booking.total_price;
const nightlyRate = booking.nightlyRate || booking.nightly_rate;
```

---

## PART 4: FILES TO MODIFY

### Backend Changes:

| File | Change | Priority |
|------|--------|----------|
| `app/services/billing_engine.py` | **CREATE** - New centralized billing engine | P0 |
| `app/models/reservations.py` | ADD `nightly_rate` field to Booking | P0 |
| `app/api/v1/bookings.py` | Use billing_engine for all calculations | P0 |
| `app/api/v1/frontdesk.py` | Post ALL charges at check-in, remove from night audit | P0 |
| `app/services/billing_service.py` | Deprecate, redirect to billing_engine | P1 |
| `app/core/tax.py` | Keep for backwards compat, but billing_engine is source | P1 |

### Frontend Changes:

| File | Change | Priority |
|------|--------|----------|
| `src/hooks/useGSTCalculator.ts` | Remove service fee, simplify | P1 |
| `src/components/bookings/GuestBillModal.tsx` | Remove reverse calculation | P1 |
| `src/services/bookingBilling.service.ts` | Simplify, trust backend values | P2 |

### Files to Delete/Deprecate:

| File | Reason |
|------|--------|
| Night audit charge posting logic | Moved to check-in |
| `billing_service.py` calculations | Replaced by billing_engine |

---

## PART 5: EDGE CASES TO HANDLE

### 5.1 Same-Day Checkout
- Minimum 1 night charged
- Check-in and checkout on same day = 1 night

### 5.2 Early Checkout
- Void existing charges
- Post new charges for actual nights
- Calculate refund if pre-paid

### 5.3 Extended Stay
- Calculate additional nights using same formula
- Post new charges to folio
- Update booking totals

### 5.4 Room Change (Upgrade/Downgrade)
- Current room charges remain
- New charges posted at new rate
- Clear audit trail

### 5.5 Partial Payments
- Folio tracks all payments
- Balance = total_charges - total_payments
- Payment status: pending/partial/paid

### 5.6 Group Booking
- Parent holds consolidated totals
- Each child has own folio
- API returns group_totals for display

### 5.7 Cancellation
- If pre-check-in: No charges (or cancellation fee)
- If post-check-in: Charge for nights stayed
- Refund calculation uses same formula

---

## PART 6: TESTING CHECKLIST

### Unit Tests:
- [ ] `billing_engine.calculate_stay_charges()` - various rates and nights
- [ ] Tax rate threshold (₹7500 boundary)
- [ ] Minimum 1 night enforcement
- [ ] CGST/SGST split accuracy
- [ ] Extension calculation
- [ ] Early checkout refund calculation

### Integration Tests:
- [ ] Booking creation → correct total
- [ ] Check-in → all charges posted
- [ ] Extended stay → charges added correctly
- [ ] Early checkout → refund calculated
- [ ] Group booking → parent shows all

### E2E Tests:
- [ ] Full booking flow (create → check-in → checkout)
- [ ] Extended stay scenario
- [ ] Early checkout scenario
- [ ] Group booking with 3 rooms

---

## PART 7: MIGRATION STEPS

### Step 1: Add nightly_rate field
```sql
ALTER TABLE bookings ADD COLUMN nightly_rate DECIMAL(10,2) NULL;
```

### Step 2: Backfill existing bookings
```python
# Migration script
for booking in all_bookings:
    if not booking.nightly_rate and booking.nights > 0:
        booking.nightly_rate = booking.base_price / booking.nights
```

### Step 3: Deploy billing_engine
- Create new file
- Update imports in all files
- Test thoroughly

### Step 4: Update check-in flow
- Post all charges at check-in
- Remove night audit charge posting

### Step 5: Update extended stay
- Use billing_engine
- Remove hardcoded 1.17

### Step 6: Frontend updates
- Remove service fee
- Simplify calculations
- Trust backend values

---

## SUMMARY

### Before (Inconsistent):
- 6+ different calculation paths
- Hardcoded tax rates in multiple places
- Night audit dependency for charges
- Confusing field semantics

### After (Consistent):
- 1 billing engine for all calculations
- Single tax rate determination
- All charges posted at check-in
- Clear field meanings with nightly_rate stored

### Key Benefits:
1. **Consistency**: Same formula everywhere
2. **Simplicity**: One source of truth
3. **Reliability**: No night audit dependency
4. **Accuracy**: Correct tax rates always
5. **Maintainability**: Changes in one place
