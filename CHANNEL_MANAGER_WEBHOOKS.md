# Channel Manager Webhook Requirements

This document outlines what data needs to be updated by a channel manager (OTA) via webhooks in this PMS system.

## Overview

Channel managers need to push updates to the PMS for:
1. **Bookings** - New, modified, and cancelled bookings
2. **Availability** - Real-time inventory updates
3. **Rates** - Rate changes and updates
4. **Restrictions** - Availability restrictions (CTA, CTD, Stop Sell, Min/Max Stay)
5. **Connection Status** - Sync status updates

---

## 1. BOOKINGS WEBHOOKS

### 1.1 New Booking (`booking.created`)
**Purpose:** Notify PMS when a new booking is created on the OTA platform.

**Webhook Payload:**
```json
{
  "event_type": "booking.created",
  "ota_connection_id": 1,  // OTA identifier
  "ota_code": "BOOKING",   // BOOKING, EXPEDIA, AGODA, AIRBNB
  "external_booking_id": "OTA-123456",  // OTA's booking reference
  "timestamp": "2024-01-15T10:30:00Z",
  
  "booking": {
    "guest": {
      "first_name": "John",
      "last_name": "Doe",
      "email": "john.doe@example.com",
      "phone": "+1234567890",
      "country": "US",
      "nationality": "US",
      "date_of_birth": "1980-05-15",  // Optional
      "passport_number": "AB123456"    // Optional
    },
    "room_type_code": "DELUXE_SUITE",  // Must match OTARoomMapping.ota_room_code
    "rate_plan_code": "BAR",            // Must match OTARateMapping.ota_rate_code
    "arrival_date": "2024-02-01",
    "departure_date": "2024-02-05",
    "adults": 2,
    "children": 1,
    "infants": 0,
    "special_requests": "Late check-in requested",
    
    "pricing": {
      "base_price": 299.00,
      "taxes": 35.88,
      "service_fee": 10.00,
      "total_price": 344.88,
      "currency": "USD",
      "commission_rate": 15.0,  // Percentage
      "commission_amount": 51.73,
      "net_revenue": 293.15
    },
    
    "payment": {
      "payment_status": "paid",  // pending, paid, partial, failed
      "payment_method": "card",  // card, pay_at_hotel
      "deposit_amount": 0.00,
      "balance_due": 0.00
    }
  }
}
```

**PMS Actions:**
- Create/update `Guest` record
- Create `Booking` record with:
  - `booking_source` = OTA code (e.g., "booking_com", "expedia")
  - `channel` = OTA name
  - `commission_rate` and `commission_amount`
  - `net_revenue` = total_price - commission
- Map room_type using `OTARoomMapping.ota_room_code`
- Map rate_plan using `OTARateMapping.ota_rate_code`
- Update `AvailabilityGrid` (decrement available rooms)
- Create `SyncLog` entry

---

### 1.2 Booking Modified (`booking.modified`)
**Purpose:** Notify PMS when booking details change on OTA.

**Webhook Payload:**
```json
{
  "event_type": "booking.modified",
  "ota_connection_id": 1,
  "external_booking_id": "OTA-123456",
  "timestamp": "2024-01-20T14:00:00Z",
  
  "changes": {
    "arrival_date": "2024-02-02",  // Changed from 2024-02-01
    "departure_date": "2024-02-06", // Changed from 2024-02-05
    "adults": 3,                     // Changed from 2
    "total_price": 389.88           // Changed due to date/guest change
  },
  
  "booking": {
    // Full booking object (updated values)
  }
}
```

**PMS Actions:**
- Find booking by `external_booking_id` (stored in `Booking.internal_notes` or separate mapping table)
- Update `Booking` record:
  - Update date/guest/pricing fields
  - Increment `modification_count`
- Recalculate availability for old and new date ranges
- Update `AvailabilityGrid`
- Create `ReservationHistory` entry

---

### 1.3 Booking Cancelled (`booking.cancelled`)
**Purpose:** Notify PMS when booking is cancelled on OTA.

**Webhook Payload:**
```json
{
  "event_type": "booking.cancelled",
  "ota_connection_id": 1,
  "external_booking_id": "OTA-123456",
  "timestamp": "2024-01-25T09:00:00Z",
  "cancellation_reason": "Guest requested cancellation",
  "refund_status": "processed"  // processed, pending, declined
}
```

**PMS Actions:**
- Find booking by `external_booking_id`
- Update `Booking`:
  - `status` = "cancelled"
  - `cancellation_reason` = reason from webhook
  - `cancelled_at` = timestamp
  - `payment_status` = "refunded" if refund processed
- Update `AvailabilityGrid` (increment available rooms)
- Create `ReservationHistory` entry

---

## 2. AVAILABILITY WEBHOOKS

### 2.1 Availability Update (`availability.updated`)
**Purpose:** Push availability changes from OTA back to PMS (rare but useful for reconciliation).

**Webhook Payload:**
```json
{
  "event_type": "availability.updated",
  "ota_connection_id": 1,
  "timestamp": "2024-01-15T10:30:00Z",
  
  "availability": [
    {
      "room_type_code": "DELUXE_SUITE",  // Must match OTARoomMapping
      "date": "2024-02-01",
      "available": 5,  // Available rooms on OTA
      "sold": 10,      // Sold on OTA
      "blocked": 2,    // Blocked on OTA
      "total": 17      // Total inventory
    },
    {
      "room_type_code": "STANDARD_ROOM",
      "date": "2024-02-01",
      "available": 20,
      "sold": 15,
      "blocked": 0,
      "total": 35
    }
  ]
}
```

**PMS Actions:**
- Update `AvailabilityGrid` records:
  - Match by `room_type_id` (via `OTARoomMapping`)
  - Update `available`, `sold`, `blocked`, `total_inventory`
- Create `SyncLog` entry (sync_direction = "pull")
- Compare with PMS availability to detect discrepancies

---

## 3. RATES WEBHOOKS

### 3.1 Rate Update (`rates.updated`)
**Purpose:** Push rate changes from OTA to PMS (for reconciliation or dynamic pricing feedback).

**Webhook Payload:**
```json
{
  "event_type": "rates.updated",
  "ota_connection_id": 1,
  "timestamp": "2024-01-15T10:30:00Z",
  
  "rates": [
    {
      "room_type_code": "DELUXE_SUITE",
      "rate_plan_code": "BAR",
      "date": "2024-02-01",
      "rate": 349.00,  // New rate on OTA
      "currency": "USD"
    },
    {
      "room_type_code": "DELUXE_SUITE",
      "rate_plan_code": "BAR",
      "date": "2024-02-02",
      "rate": 359.00,
      "currency": "USD"
    }
  ]
}
```

**PMS Actions:**
- Update `DailyRate` records:
  - Match by `room_type_id` (via `OTARoomMapping`)
  - Match by `rate_plan_id` (via `OTARateMapping`)
  - Update `calculated_rate` or create override
- Update `AvailabilityGrid.rate_amount` if applicable
- Create `SyncLog` entry

---

## 4. RESTRICTIONS WEBHOOKS

### 4.1 Restrictions Update (`restrictions.updated`)
**Purpose:** Update channel-specific restrictions applied on OTA.

**Webhook Payload:**
```json
{
  "event_type": "restrictions.updated",
  "ota_connection_id": 1,
  "timestamp": "2024-01-15T10:30:00Z",
  
  "restrictions": [
    {
      "room_type_code": "DELUXE_SUITE",
      "date": "2024-02-01",
      "restriction_type": "stop_sell",  // stop_sell, CTA, CTD, min_stay, max_stay
      "restriction_value": 1  // 1/0 for boolean, nights for stay limits
    },
    {
      "room_type_code": "DELUXE_SUITE",
      "date": "2024-02-01",
      "restriction_type": "min_stay",
      "restriction_value": 2  // Minimum 2 nights
    }
  ]
}
```

**PMS Actions:**
- Create/update `ChannelRestriction` records:
  - `ota_connection_id` = webhook ota_connection_id
  - `room_type_id` = mapped from `room_type_code`
  - `restriction_type` = from webhook
  - `restriction_value` = from webhook
  - `restriction_date` = date from webhook
- Update `AvailabilityGrid` flags:
  - `stop_sell_flag` = true if restriction_type = "stop_sell"
  - `cta_flag` = true if restriction_type = "CTA"
  - `ctd_flag` = true if restriction_type = "CTD"
  - `min_stay` = restriction_value if restriction_type = "min_stay"
  - `max_stay` = restriction_value if restriction_type = "max_stay"

---

## 5. CONNECTION/SYNC STATUS WEBHOOKS

### 5.1 Sync Status Update (`sync.status`)
**Purpose:** Update PMS about sync status from OTA.

**Webhook Payload:**
```json
{
  "event_type": "sync.status",
  "ota_connection_id": 1,
  "timestamp": "2024-01-15T10:30:00Z",
  
  "status": {
    "connection_status": "connected",  // connected, disconnected, error, syncing
    "last_sync_at": "2024-01-15T10:00:00Z",
    "sync_type": "full",  // rates, availability, bookings, restrictions, full
    "records_processed": 150,
    "records_failed": 0,
    "error_message": null
  }
}
```

**PMS Actions:**
- Update `OTAConnection`:
  - `connection_status` = status from webhook
  - `last_sync_at` = timestamp
  - `error_message` = error_message if any
- Create `SyncLog` entry:
  - `sync_type` = sync_type from webhook
  - `sync_direction` = "pull"
  - `status` = "success" or "failed"
  - `records_processed` = records_processed
  - `records_failed` = records_failed

---

## 6. ADDITIONAL CONSIDERATIONS

### 6.1 Required Mapping Tables

Before processing webhooks, ensure these mappings exist:

1. **OTARoomMapping** - Maps OTA room codes to PMS room_type_id
   - `ota_room_code` (from webhook) → `room_type_id`

2. **OTARateMapping** - Maps OTA rate codes to PMS rate_plan_id
   - `ota_rate_code` (from webhook) → `rate_plan_id`

3. **External Booking ID Mapping** - Store OTA booking ID for lookups
   - Option 1: Store in `Booking.internal_notes` as JSON
   - Option 2: Create separate `ExternalBookingMapping` table

### 6.2 Data Models to Update

Based on codebase analysis, these are the key models:

**Bookings:**
- `Booking` (primary booking model)
- `Reservation` (legacy, kept for backward compatibility)
- `ReservationHistory` (audit trail)
- `Guest` (guest information)

**Availability:**
- `AvailabilityGrid` (channel_manager.py)
- `DailyAvailability` (inventory.py)
- `RoomBlock` (blocked inventory)

**Rates:**
- `DailyRate` (inventory.py)
- `RateOverride` (channel_manager.py)

**Restrictions:**
- `ChannelRestriction` (channel_manager.py)

**Sync Logging:**
- `SyncLog` (channel_manager.py)
- `InventorySyncQueue` (inventory.py)

**Connection:**
- `OTAConnection` (channel_manager.py)

---

## 7. WEBHOOK ENDPOINT SUGGESTIONS

Create these endpoints in the PMS to receive webhooks:

```
POST /api/v1/webhooks/channel-manager/bookings
POST /api/v1/webhooks/channel-manager/availability
POST /api/v1/webhooks/channel-manager/rates
POST /api/v1/webhooks/channel-manager/restrictions
POST /api/v1/webhooks/channel-manager/sync-status

OR

POST /api/v1/webhooks/channel-manager
  (with event_type in payload to route internally)
```

**Security:**
- Validate webhook signature/secret
- Verify `ota_connection_id` exists and is active
- Rate limiting per OTA connection
- Idempotency keys for duplicate prevention

---

## 8. SAMPLE WEBHOOK IMPLEMENTATION (Dummy Channel Manager)

For your demo channel manager, implement these webhook endpoints:

1. **booking.created** - Triggered when demo booking is created
2. **booking.modified** - Triggered when demo booking is modified
3. **booking.cancelled** - Triggered when demo booking is cancelled
4. **availability.updated** - Periodic availability sync (optional)
5. **rates.updated** - Rate changes sync (optional)
6. **restrictions.updated** - Restriction changes (optional)
7. **sync.status** - Sync status updates

Each webhook should include:
- `event_type` field
- `ota_connection_id` or `ota_code`
- `timestamp` field
- Event-specific payload

---

## 9. PRIORITY WEBHOOKS FOR DEMO

For a minimal viable demo, focus on:

1. **booking.created** (HIGH PRIORITY) - Essential for OTA bookings
2. **booking.cancelled** (HIGH PRIORITY) - Essential for cancellations
3. **booking.modified** (MEDIUM PRIORITY) - Useful for modifications
4. **sync.status** (LOW PRIORITY) - Nice to have for status updates

Availability, rates, and restrictions webhooks can be added later as they're more about bidirectional sync rather than critical OTA→PMS updates.

---

## 10. NOTES

- All dates should be in ISO 8601 format (YYYY-MM-DD)
- All timestamps should be in ISO 8601 format with timezone (YYYY-MM-DDTHH:MM:SSZ)
- Currency codes should follow ISO 4217 (USD, EUR, etc.)
- Room type codes and rate plan codes must match the mappings in `OTARoomMapping` and `OTARateMapping`
- The PMS should validate all incoming data and return appropriate error responses
- Consider implementing webhook retry logic in the channel manager for failed deliveries
