# Billing Flow Analysis - Same-Day Checkout ₹0 Issue

## Problem Statement
When a guest checks in and checks out on the same day, the checkout dialog shows ₹0 balance instead of the minimum 1-night charge.

---

## Flow Diagram

```
┌─────────────────┐     ┌──────────────────────┐     ┌───────────────────────┐
│   CHECK-IN      │     │  CHECKOUT DIALOG     │     │   ACTUAL CHECKOUT     │
│   frontdesk.py  │────▶│  CheckoutDialog.tsx  │────▶│   bookings.py         │
│   Lines 62-250  │     │  folio.service.ts    │     │   checkout_booking()  │
└─────────────────┘     └──────────────────────┘     └───────────────────────┘
        │                        │                            │
        ▼                        ▼                            ▼
  Folio created          GET /folios endpoint         Post charges if missing
  with ₹0 balance        folio.py:list_folios()       with fallback rate
                                 │
                                 ▼
                         TRY to post preview
                         charges if rate > 0
                                 │
                         ┌───────┴───────┐
                         │               │
                    rate > 0        rate = 0
                         │               │
                    POST charges    SKIP (bug!)
                         │               │
                    Show balance    Show ₹0
```

---

## Root Cause

### The Disconnect

| Location | Code | Behavior |
|----------|------|----------|
| `folio.py` line 245 | `if nightly_rate > 0:` | Skips posting if rate=0 |
| `folio.py` line 268-269 | `logger.warning(...)` | Only logs, doesn't fail |
| `bookings.py` line 3089-3091 | `nightly_rate = 1000.0` | Uses fallback rate |

**Problem**: The fallback rate logic exists in `checkout_booking()` but NOT in `list_folios()`.

### Why Rate = 0

`get_effective_nightly_rate()` returns 0 when ALL of these fail:
1. `booking.base_price / nights` → 0 if base_price not set
2. `booking.total_price / 1.12 / nights` → 0 if total_price not set
3. `room_type.base_price` → 0 if room type not configured
4. `booking.deposit_amount / 1.12 / nights` → 0 if no deposit

---

## Code Locations

### Frontend

| File | Line | Purpose |
|------|------|---------|
| `CheckoutDialog.tsx` | 37-38 | Gets bookingId |
| `CheckoutDialog.tsx` | 52 | Calls `folioService.listFolios(bookingId)` |
| `CheckoutDialog.tsx` | 61 | Reads `f.balance` field |
| `CheckoutDialog.tsx` | 78 | `canCheckout = unsettled.length === 0` |
| `folio.service.ts` | 16-23 | `GET /api/v1/bookings/{bookingId}/folios` |

### Backend

| File | Line | Purpose |
|------|------|---------|
| `frontdesk.py` | 141-157 | Creates folio with ₹0 at check-in |
| `folio.py` | 161-280 | `list_folios()` endpoint |
| `folio.py` | 201-269 | Preview charges logic (THE BUG) |
| `folio.py` | 245 | `if nightly_rate > 0:` - skips if rate=0 |
| `bookings.py` | 3062-3108 | Posts charges at checkout |
| `bookings.py` | 3089-3091 | Fallback rate ₹1000 |
| `billing_service.py` | 174-248 | `get_effective_nightly_rate()` |

---

## The Fix (APPLIED)

Added the same fallback rate logic to `list_folios()` that exists in `checkout_booking()`.

### Changes Made:

**File: `app/api/v1/folio.py` (list_folios function)**

```python
# Get nightly rate
nightly_rate = await get_effective_nightly_rate(session, booking)

# Fallback 1: try room type from booking
if nightly_rate <= 0 and booking.room_type_id:
    from app.models.inventory import RoomType
    rt = await session.get(RoomType, booking.room_type_id)
    if rt and rt.base_price:
        nightly_rate = float(rt.base_price)

# Fallback 2: try room's room_type
if nightly_rate <= 0 and booking.room_id:
    from app.models.inventory import Room, RoomType
    room_obj = await session.get(Room, booking.room_id)
    if room_obj and room_obj.room_type_id:
        rt = await session.get(RoomType, room_obj.room_type_id)
        if rt and rt.base_price:
            nightly_rate = float(rt.base_price)

# Fallback 3: Emergency fallback rate (same as checkout_booking)
if nightly_rate <= 0:
    nightly_rate = 1000.0  # Minimum fallback rate

# Now post charges (nightly_rate is guaranteed > 0 due to fallback)
room_charge, tax_item = await create_room_charge_line_item(...)
```

### Also Added:
- Legacy reservation_id fallback in folio queries
- Auto-linking folios to bookings when found via reservation_id

---

## Test Scenarios

1. **Same-day checkout**: Check-in and checkout on same day → Should show 1 night charge
2. **Early checkout**: 3-night booking, leave after 1 night → Should show 1 night charge
3. **Normal checkout**: 3-night booking, Night Audit ran → Should show accumulated charges
4. **Missing rate data**: No base_price set → Should use fallback ₹1000

---

## Related Files

- `/app/api/v1/folio.py` - Folio endpoints
- `/app/api/v1/bookings.py` - Checkout endpoint
- `/app/api/v1/frontdesk.py` - Check-in endpoint
- `/app/services/billing_service.py` - Billing calculations
- `/frontend/src/components/bookings/CheckoutDialog.tsx` - Checkout UI
- `/frontend/src/api/services/folio.service.ts` - API client
