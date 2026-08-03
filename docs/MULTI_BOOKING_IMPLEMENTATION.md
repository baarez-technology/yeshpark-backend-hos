# Multiple Booking Implementation Plan

## Current State
- Database fields exist: `is_group_booking`, `group_booking_id`, `parent_booking_id`, `number_of_rooms`
- Multi-room creation API works (`POST /multi-room/create`)
- Each booking gets its own folio with individual charges

## Problem
- Child bookings show their own charges (should show 0)
- No consolidated billing to parent
- Checkout treats each booking independently

## Solution

### 1. Backend: Billing Logic Changes [COMPLETED]

**File: `app/api/v1/folio.py`**
- Modified `list_folios` to return balance=0 for child bookings
- Added `is_child_booking` flag to response
- Charges still tracked internally as `actual_balance` but display shows 0
- Added `parent_info` with parent booking details

**File: `app/services/billing_service.py`**
- Added `is_child_booking()` helper - checks if `parent_booking_id` is set
- Added `is_parent_booking()` helper - checks if `is_group_booking=True` and no parent
- Added `get_parent_booking()` helper - returns parent booking for a child
- Added `get_group_bookings()` helper - returns all bookings in a group
- Added `get_group_total_charges()` helper - calculates consolidated totals
- Added `get_child_booking_display_balance()` helper - returns display values for child

### 2. Backend: Folio Consolidation [COMPLETED]

**New endpoint: `GET /bookings/{booking_id}/group-folios`**
- Returns all folios for a group (parent + children)
- Shows consolidated `group_totals` with total_charges, total_payments, total_balance
- Parent folios show actual balance (where payment is collected)
- Child folios show `display_balance=0` with note "Charges consolidated to main booking"
- Includes room numbers for each booking in the group

### 3. Backend: Checkout Flow [COMPLETED]

**File: `app/api/v1/bookings.py`**
- Child booking checkout: Skips payment validation (logs: "charges on parent")
- Parent/standalone bookings: Normal payment validation applies
- Both parent and child bookings can be checked out independently

### 4. Frontend: Display Changes [TODO]

**File: `src/pages/admin/Bookings.tsx`**
- Group child bookings visually under parent
- Show "Part of group" badge on child bookings
- Show 0 for child booking amounts

**File: `src/components/bookings/CheckoutDialog.tsx`**
- For child bookings: Show message "Payment collected at main booking"
- Allow checkout without payment for child bookings

## API Reference

### List Folios (existing, enhanced)
```
GET /api/v1/bookings/{booking_id}/folios
```
Response includes:
- `is_child_booking`: true/false
- `display_balance`: 0 for children, actual for parent/standalone
- `actual_balance`: real balance (for internal tracking)
- `parent_info`: { parent_booking_id, parent_booking_number, balance_note }

### Group Folios (new)
```
GET /api/v1/bookings/{booking_id}/group-folios
```
Response:
- `is_group_booking`: true
- `group_booking_id`: UUID for the group
- `booking_count`: number of bookings in group
- `parent_booking`: { id, booking_number }
- `group_totals`: { total_charges, total_payments, total_balance }
- `folios`: array of all folios with parent/child markers

## Implementation Order
1. [x] Add helper functions to billing_service.py
2. [x] Modify folio list_folios to handle child bookings
3. [x] Add group-folios endpoint
4. [x] Update checkout flow for child bookings
5. [ ] Update frontend display (Bookings.tsx)
6. [ ] Update checkout dialog for child bookings

