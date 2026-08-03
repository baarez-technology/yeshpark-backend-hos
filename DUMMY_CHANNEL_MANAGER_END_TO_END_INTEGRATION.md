# Dummy Channel Manager - End-to-End Integration Guide

## Overview

This document provides a complete guide for integrating the `dummy_channel_manager` with the Glimmora booking system and channel manager system. This integration enables end-to-end functionality where bookings created in the dummy channel manager flow through to the PMS booking system, and channel manager operations (availability, rates, restrictions) are synchronized bidirectionally.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DUMMY CHANNEL MANAGER                            │
│                         (Port 8001)                                      │
│                                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │   Hotels     │  │  Room Types  │  │    Rates     │                  │
│  │   Management │  │  Management  │  │  Management  │                  │
│  └──────────────┘  └──────────────┘  └──────────────┘                  │
│                                                                           │
│  ┌──────────────────────────────────────────────────────┐               │
│  │         Reservation Management                        │               │
│  │  - Create Reservation                                │               │
│  │  - Modify Reservation                                │               │
│  │  - Cancel Reservation                                │               │
│  │  - Check Availability                                │               │
│  └──────────────────────────────────────────────────────┘               │
│                            │                                              │
│                            │ Webhooks (HTTP POST)                         │
│                            ▼                                              │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    GLIMMORA BACKEND (Port 8000)                          │
│                                                                           │
│  ┌──────────────────────────────────────────────────────┐               │
│  │         Webhook Receiver                             │               │
│  │  POST /api/v1/webhooks/channel-manager               │               │
│  │  - booking.created                                    │               │
│  │  - booking.modified                                   │               │
│  │  - booking.cancelled                                  │               │
│  │  - availability.updated                               │               │
│  │  - rates.updated                                      │               │
│  │  - restrictions.updated                               │               │
│  │  - sync.status                                        │               │
│  └──────────────────────────────────────────────────────┘               │
│                            │                                              │
│                            │ Process & Update                             │
│                            ▼                                              │
│  ┌──────────────────────────────────────────────────────┐               │
│  │              BOOKING SYSTEM                           │               │
│  │  - Booking Model                                      │               │
│  │  - Guest Model                                        │               │
│  │  - ReservationHistory                                 │               │
│  └──────────────────────────────────────────────────────┘               │
│                            │                                              │
│                            │                                              │
│  ┌──────────────────────────────────────────────────────┐               │
│  │           CHANNEL MANAGER SYSTEM                     │               │
│  │  - OTAConnection                                     │               │
│  │  - OTARoomMapping                                    │               │
│  │  - OTARateMapping                                    │               │
│  │  - AvailabilityGrid                                  │               │
│  │  - ChannelRestriction                                │               │
│  │  - SyncLog                                           │               │
│  └──────────────────────────────────────────────────────┘               │
│                            │                                              │
│                            │ SSE Events                                  │
│                            ▼                                              │
│  ┌──────────────────────────────────────────────────────┐               │
│  │         SSE Event Broadcaster                         │               │
│  │  GET /api/v1/webhooks/channel-manager/sse             │               │
│  └──────────────────────────────────────────────────────┘               │
└───────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Real-time Updates
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND APPLICATION                             │
│  - Channel Manager Dashboard                                             │
│  - Bookings List                                                         │
│  - Availability Grid                                                     │
│  - Rates Display                                                         │
│  - Sync Status                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

## Integration Components

### 1. Dummy Channel Manager

**Purpose:** Simulates a real OTA/Channel Manager (Booking.com, Expedia, etc.)

**Key Responsibilities:**
- Manage hotels, room types, rates, and reservations
- Send webhooks when bookings are created/modified/cancelled
- Send availability, rates, and restrictions updates
- Provide API endpoints for reservation management

**Port:** 8001

**Base URL:** `http://localhost:8001`

### 2. Glimmora Backend

**Purpose:** Receives webhooks and updates PMS database

**Key Responsibilities:**
- Receive and validate webhooks from dummy channel manager
- Process webhook events and update database
- Maintain booking and channel manager data
- Broadcast real-time events via SSE

**Port:** 8000

**Base URL:** `http://localhost:8000`

### 3. Booking System

**Purpose:** Manage hotel bookings and reservations

**Key Models:**
- `Booking` - Main booking records
- `Guest` - Guest information
- `ReservationHistory` - Booking audit trail

### 4. Channel Manager System

**Purpose:** Manage OTA connections and channel data

**Key Models:**
- `OTAConnection` - OTA integration configuration
- `OTARoomMapping` - Maps OTA room codes to PMS room types
- `OTARateMapping` - Maps OTA rate codes to PMS rate plans
- `AvailabilityGrid` - Daily availability tracking
- `ChannelRestriction` - Channel restrictions (CTA, CTD, Stop Sell)
- `SyncLog` - Sync activity audit log

## End-to-End Data Flow

### Flow 1: Booking Creation

```
1. User creates reservation in Dummy Channel Manager
   POST /api/v2/reservations
   
2. Dummy Channel Manager:
   - Validates reservation data
   - Checks availability
   - Creates reservation in its database
   - Generates confirmation number (e.g., HRS-2024-A1B2C3)
   - Builds booking.created webhook payload
   
3. Dummy Channel Manager sends webhook:
   POST http://localhost:8000/api/v1/webhooks/channel-manager
   {
     "event_type": "booking.created",
     "ota_connection_id": 1,
     "ota_code": "BOOKING",
     "external_booking_id": "HRS-2024-A1B2C3",
     "booking": { ... }
   }
   
4. Glimmora Backend receives webhook:
   - Validates payload
   - Looks up OTA connection
   - Maps OTA room code to PMS room_type_id
   - Maps OTA rate code to PMS rate_plan_id
   - Gets or creates guest record
   - Creates Booking record
   - Updates AvailabilityGrid (decrements available rooms)
   - Stores external_booking_id in Booking.internal_notes
   - Commits to database
   
5. Glimmora Backend broadcasts SSE event:
   - Event: booking.created
   - Data: { booking_id, booking_number, guest_id, ... }
   
6. Frontend receives SSE event:
   - Updates bookings list
   - Shows notification
   - Refreshes availability display
```

### Flow 2: Booking Modification

```
1. User modifies reservation in Dummy Channel Manager
   PUT /api/reservations/{id}
   
2. Dummy Channel Manager:
   - Validates modification
   - Updates reservation
   - Recalculates pricing if dates changed
   - Builds booking.modified webhook payload
   
3. Dummy Channel Manager sends webhook:
   POST http://localhost:8000/api/v1/webhooks/channel-manager
   {
     "event_type": "booking.modified",
     "external_booking_id": "HRS-2024-A1B2C3",
     "changes": { "departure_date": "2025-01-23" },
     "booking": { ... }
   }
   
4. Glimmora Backend receives webhook:
   - Finds booking by external_booking_id
   - Updates booking fields
   - If dates changed:
     * Releases old inventory (increments availability)
     * Reserves new inventory (decrements availability)
   - Creates ReservationHistory entry
   - Commits to database
   
5. Glimmora Backend broadcasts SSE event:
   - Event: booking.modified
   - Data: { booking_id, changes, ... }
   
6. Frontend receives SSE event:
   - Updates booking in list
   - Highlights changes
   - Refreshes availability display
```

### Flow 3: Booking Cancellation

```
1. User cancels reservation in Dummy Channel Manager
   DELETE /api/reservations/{id}
   
2. Dummy Channel Manager:
   - Marks reservation as cancelled
   - Releases inventory
   - Builds booking.cancelled webhook payload
   
3. Dummy Channel Manager sends webhook:
   POST http://localhost:8000/api/v1/webhooks/channel-manager
   {
     "event_type": "booking.cancelled",
     "external_booking_id": "HRS-2024-A1B2C3",
     "cancellation_reason": "Guest requested cancellation",
     "refund_status": "processed"
   }
   
4. Glimmora Backend receives webhook:
   - Finds booking by external_booking_id
   - Updates booking status to "cancelled"
   - Sets cancellation_reason and cancelled_at
   - Updates payment_status if refund processed
   - Releases inventory (increments availability)
   - Creates ReservationHistory entry
   - Commits to database
   
5. Glimmora Backend broadcasts SSE event:
   - Event: booking.cancelled
   - Data: { booking_id, reason, ... }
   
6. Frontend receives SSE event:
   - Marks booking as cancelled
   - Removes from active list
   - Shows notification
   - Refreshes availability display
```

### Flow 4: Availability Update

```
1. Dummy Channel Manager updates availability
   (Can be triggered manually or automatically)
   POST /api/webhooks/trigger/availability
   
2. Dummy Channel Manager:
   - Calculates current availability
   - Builds availability.updated webhook payload
   
3. Dummy Channel Manager sends webhook:
   POST http://localhost:8000/api/v1/webhooks/channel-manager
   {
     "event_type": "availability.updated",
     "ota_connection_id": 1,
     "availability": [
       {
         "room_type_code": "ROOM_1",
         "date": "2025-01-20",
         "available": 15,
         "sold": 5,
         "blocked": 0,
         "total": 20
       }
     ]
   }
   
4. Glimmora Backend receives webhook:
   - Maps OTA room codes to PMS room_type_id
   - Updates or creates AvailabilityGrid entries
   - Updates total_inventory, sold, blocked, available
   - Commits to database
   
5. Glimmora Backend broadcasts SSE event:
   - Event: availability.updated
   - Data: { updated_count, ota_connection_id }
   
6. Frontend receives SSE event:
   - Refreshes availability grid
   - Updates availability display
```

### Flow 5: Rates Update

```
1. Dummy Channel Manager updates rates
   POST /api/rates/update
   
2. Dummy Channel Manager:
   - Updates rate data
   - Builds rates.updated webhook payload
   
3. Dummy Channel Manager sends webhook:
   POST http://localhost:8000/api/v1/webhooks/channel-manager
   {
     "event_type": "rates.updated",
     "ota_connection_id": 1,
     "rates": [
       {
         "room_type_code": "ROOM_1",
         "rate_plan_code": "BAR",
         "date": "2025-01-20",
         "rate": 299.00,
         "currency": "USD"
       }
     ]
   }
   
4. Glimmora Backend receives webhook:
   - Maps OTA room codes to PMS room_type_id
   - Maps OTA rate codes to PMS rate_plan_id
   - Updates or creates DailyRate entries
   - Updates override_rate
   - Commits to database
   
5. Glimmora Backend broadcasts SSE event:
   - Event: rates.updated
   - Data: { updated_count, ota_connection_id }
   
6. Frontend receives SSE event:
   - Refreshes rates display
   - Updates rate information
```

### Flow 6: Restrictions Update

```
1. Dummy Channel Manager updates restrictions
   (Can be triggered manually)
   
2. Dummy Channel Manager:
   - Updates restriction data
   - Builds restrictions.updated webhook payload
   
3. Dummy Channel Manager sends webhook:
   POST http://localhost:8000/api/v1/webhooks/channel-manager
   {
     "event_type": "restrictions.updated",
     "ota_connection_id": 1,
     "restrictions": [
       {
         "room_type_code": "ROOM_1",
         "date": "2025-01-20",
         "restriction_type": "stop_sell",
         "restriction_value": 1
       }
     ]
   }
   
4. Glimmora Backend receives webhook:
   - Maps OTA room codes to PMS room_type_id
   - Creates or updates ChannelRestriction entries
   - Updates AvailabilityGrid flags:
     * stop_sell_flag
     * cta_flag
     * ctd_flag
     * min_stay / max_stay
   - Commits to database
   
5. Glimmora Backend broadcasts SSE event:
   - Event: restrictions.updated
   - Data: { updated_count, ota_connection_id }
   
6. Frontend receives SSE event:
   - Refreshes restrictions display
   - Updates availability grid flags
```

### Flow 7: Sync Status Update

```
1. Dummy Channel Manager sends sync status
   POST /api/webhooks/trigger/sync-status
   
2. Dummy Channel Manager:
   - Builds sync.status webhook payload
   
3. Dummy Channel Manager sends webhook:
   POST http://localhost:8000/api/v1/webhooks/channel-manager
   {
     "event_type": "sync.status",
     "ota_connection_id": 1,
     "status": {
       "connection_status": "connected",
       "last_sync_at": "2025-01-18T10:00:00Z",
       "sync_type": "full",
       "records_processed": 150,
       "records_failed": 0,
       "error_message": null
     }
   }
   
4. Glimmora Backend receives webhook:
   - Updates OTAConnection:
     * connection_status
     * last_sync_at
     * error_message
   - Creates SyncLog entry:
     * sync_type
     * sync_direction = "pull"
     * status
     * records_processed
     * records_failed
   - Commits to database
   
5. Glimmora Backend broadcasts SSE event:
   - Event: sync.status
   - Data: { ota_connection_id, status }
   
6. Frontend receives SSE event:
   - Updates connection status indicator
   - Updates last sync time
   - Shows sync progress
   - Displays sync logs
```

## Setup and Configuration

### Step 1: Start Both Servers

**Terminal 1 - Glimmora Backend:**
```bash
cd C:\Users\princ\Desktop\glimmora-backend
python -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2 - Dummy Channel Manager:**
```bash
cd C:\Users\princ\Desktop\glimmora-backend\dummy_channel_manager
python main.py
```

**Verify Both Servers:**
```bash
# Check Glimmora Backend
curl http://localhost:8000/health

# Check Dummy Channel Manager
curl http://localhost:8001/health
```

### Step 2: Database Setup

#### 2.1 Create OTA Connection

The database must have an OTA connection record that matches the dummy channel manager.

**Required Fields:**
- `id`: 1 (must match ota_connection_id in webhooks)
- `ota_code`: "BOOKING" (or match dummy channel manager)
- `ota_name`: "Booking.com" (or appropriate name)
- `property_id`: 1 (or your property ID)
- `is_active`: true
- `connection_status`: "connected"

**SQL Example:**
```sql
INSERT INTO ota_connections (
    id, property_id, ota_code, ota_name, 
    is_active, connection_status, created_at, updated_at
) VALUES (
    1, 1, 'BOOKING', 'Booking.com',
    true, 'connected', NOW(), NOW()
);
```

#### 2.2 Create Room Type Mappings

Map dummy channel manager room codes to PMS room types.

**Dummy Channel Manager Room Codes:**
- `ROOM_1` - Standard King
- `ROOM_2` - Deluxe Suite
- `ROOM_3` - Executive King
- `ROOM_4` - Ocean View King
- `ROOM_5` - Presidential Suite
- `ROOM_6` - Business Twin

**SQL Example:**
```sql
-- Map ROOM_1 to room_type_id 1
INSERT INTO ota_room_mappings (
    property_id, ota_connection_id, room_type_id,
    ota_room_code, ota_room_name, is_active, created_at
) VALUES (
    1, 1, 1, 'ROOM_1', 'Standard King', true, NOW()
);

-- Map ROOM_2 to room_type_id 2
INSERT INTO ota_room_mappings (
    property_id, ota_connection_id, room_type_id,
    ota_room_code, ota_room_name, is_active, created_at
) VALUES (
    1, 1, 2, 'ROOM_2', 'Deluxe Suite', true, NOW()
);

-- Repeat for ROOM_3 through ROOM_6
```

#### 2.3 Create Rate Plan Mappings

Map dummy channel manager rate codes to PMS rate plans.

**Dummy Channel Manager Rate Codes:**
- `BAR` - Best Available Rate
- `NON_REFUNDABLE` - Non-Refundable
- `CORPORATE` - Corporate
- `PROMOTIONAL` - Promotional
- `LONG_STAY` - Long Stay

**SQL Example:**
```sql
-- Map BAR to rate_plan_id 1
INSERT INTO ota_rate_mappings (
    property_id, ota_connection_id, rate_plan_id,
    ota_rate_code, ota_rate_name, is_active, created_at
) VALUES (
    1, 1, 1, 'BAR', 'Best Available Rate', true, NOW()
);

-- Map NON_REFUNDABLE to rate_plan_id 2
INSERT INTO ota_rate_mappings (
    property_id, ota_connection_id, rate_plan_id,
    ota_rate_code, ota_rate_name, is_active, created_at
) VALUES (
    1, 1, 2, 'NON_REFUNDABLE', 'Non-Refundable', true, NOW()
);

-- Repeat for other rate plans
```

#### 2.4 Initialize Availability Grid

Ensure availability grid entries exist for room types and dates.

**SQL Example:**
```sql
-- Create availability grid entries for room_type_id 1 for next 90 days
INSERT INTO availability_grid (
    property_id, room_type_id, grid_date,
    total_inventory, sold, blocked, available,
    updated_at
)
SELECT 
    1, 1, date_series.date,
    20, 0, 0, 20,  -- Adjust total_inventory as needed
    NOW()
FROM (
    SELECT CURRENT_DATE + INTERVAL '1 day' * generate_series(0, 89) AS date
) AS date_series;
```

### Step 3: Configure Webhook URL

Configure the dummy channel manager to send webhooks to Glimmora backend.

**API Call:**
```bash
curl -X POST http://localhost:8001/api/webhooks/configure \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://localhost:8000/api/v1/webhooks/channel-manager"
  }'
```

**PowerShell:**
```powershell
$webhookConfig = @{
    url = "http://localhost:8000/api/v1/webhooks/channel-manager"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8001/api/webhooks/configure" `
    -Method Post `
    -ContentType "application/json" `
    -Body $webhookConfig
```

**Verify Configuration:**
```bash
curl http://localhost:8001/api/webhooks/status
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "webhook_url": "http://localhost:8000/api/v1/webhooks/channel-manager",
    "configured": true
  },
  "message": "Webhook status retrieved"
}
```

## Integration Testing

### Test 1: End-to-End Booking Creation

**Objective:** Verify complete flow from reservation creation to booking in PMS

**Steps:**

1. **Create reservation in dummy channel manager:**
   ```bash
   curl -X POST http://localhost:8001/api/v2/reservations \
     -H "Content-Type: application/json" \
     -d '{
       "room_id": 1,
       "rate_plan_id": 0,
       "arrival_date": "2025-01-20",
       "departure_date": "2025-01-22",
       "adults": 2,
       "children": 0,
       "guest": {
         "first_name": "John",
         "last_name": "Doe",
         "email": "john.doe@example.com",
         "phone": "+1234567890"
       },
       "special_requests": "Early check-in preferred"
     }'
   ```

2. **Verify dummy channel manager response:**
   - Should return reservation with confirmation number
   - Should show webhook sent successfully in logs

3. **Verify backend received webhook:**
   - Check backend logs for `[WEBHOOK RECEIVER]` messages
   - Should show `booking.created` processed successfully

4. **Verify database:**
   ```sql
   -- Check booking was created
   SELECT id, booking_number, confirmation_code, guest_id, 
          arrival_date, departure_date, status, channel, booking_source
   FROM bookings
   ORDER BY created_at DESC
   LIMIT 1;
   
   -- Check guest was created/updated
   SELECT id, first_name, last_name, email, phone
   FROM guests
   WHERE email = 'john.doe@example.com';
   
   -- Check availability was updated
   SELECT room_type_id, grid_date, available, sold, total_inventory
   FROM availability_grid
   WHERE room_type_id = 1 
     AND grid_date >= '2025-01-20' 
     AND grid_date < '2025-01-22';
   ```

5. **Verify SSE event:**
   - Connect to SSE endpoint
   - Should receive `booking.created` event

**Expected Results:**
- ✅ Reservation created in dummy channel manager
- ✅ Webhook sent to backend
- ✅ Booking created in PMS database
- ✅ Guest record created/updated
- ✅ Availability grid updated
- ✅ SSE event broadcasted

### Test 2: End-to-End Booking Modification

**Steps:**

1. **Get reservation ID from previous test**

2. **Modify reservation:**
   ```bash
   curl -X PUT http://localhost:8001/api/reservations/{reservation_id} \
     -H "Content-Type: application/json" \
     -d '{
       "check_out": "2025-01-23"
     }'
   ```

3. **Verify database:**
   ```sql
   -- Check booking was updated
   SELECT id, booking_number, departure_date, modification_count
   FROM bookings
   WHERE id = {booking_id};
   
   -- Check reservation history
   SELECT * FROM reservation_history
   WHERE reservation_id = {booking_id}
   ORDER BY created_at DESC;
   
   -- Check availability for old dates (should be released)
   SELECT grid_date, available, sold
   FROM availability_grid
   WHERE room_type_id = 1 
     AND grid_date >= '2025-01-20' 
     AND grid_date < '2025-01-22';
   
   -- Check availability for new dates (should be reserved)
   SELECT grid_date, available, sold
   FROM availability_grid
   WHERE room_type_id = 1 
     AND grid_date >= '2025-01-20' 
     AND grid_date < '2025-01-23';
   ```

**Expected Results:**
- ✅ Reservation modified in dummy channel manager
- ✅ Webhook sent to backend
- ✅ Booking updated in PMS database
- ✅ Old inventory released
- ✅ New inventory reserved
- ✅ Reservation history entry created
- ✅ SSE event broadcasted

### Test 3: End-to-End Booking Cancellation

**Steps:**

1. **Cancel reservation:**
   ```bash
   curl -X DELETE http://localhost:8001/api/reservations/{reservation_id}
   ```

2. **Verify database:**
   ```sql
   -- Check booking was cancelled
   SELECT id, booking_number, status, cancellation_reason, cancelled_at
   FROM bookings
   WHERE id = {booking_id};
   
   -- Check availability was released
   SELECT grid_date, available, sold
   FROM availability_grid
   WHERE room_type_id = 1 
     AND grid_date >= '2025-01-20' 
     AND grid_date < '2025-01-23';
   ```

**Expected Results:**
- ✅ Reservation cancelled in dummy channel manager
- ✅ Webhook sent to backend
- ✅ Booking marked as cancelled in PMS
- ✅ Inventory released
- ✅ Reservation history entry created
- ✅ SSE event broadcasted

### Test 4: End-to-End Availability Update

**Steps:**

1. **Trigger availability webhook:**
   ```bash
   curl -X POST "http://localhost:8001/api/webhooks/trigger/availability?ota_connection_id=1"
   ```

2. **Verify database:**
   ```sql
   -- Check availability grid was updated
   SELECT room_type_id, grid_date, available, sold, blocked, total_inventory
   FROM availability_grid
   WHERE grid_date = CURRENT_DATE
   ORDER BY room_type_id;
   ```

**Expected Results:**
- ✅ Availability webhook sent
- ✅ Availability grid updated in PMS
- ✅ SSE event broadcasted

### Test 5: End-to-End Sync Status Update

**Steps:**

1. **Trigger sync status webhook:**
   ```bash
   curl -X POST "http://localhost:8001/api/webhooks/trigger/sync-status?ota_connection_id=1&connection_status=connected&sync_type=full&records_processed=150&records_failed=0"
   ```

2. **Verify database:**
   ```sql
   -- Check OTA connection status
   SELECT id, ota_code, connection_status, last_sync_at, error_message
   FROM ota_connections
   WHERE id = 1;
   
   -- Check sync log
   SELECT id, sync_type, sync_direction, status, 
          records_processed, records_failed, completed_at
   FROM sync_logs
   WHERE ota_connection_id = 1
   ORDER BY completed_at DESC
   LIMIT 1;
   ```

**Expected Results:**
- ✅ Sync status webhook sent
- ✅ OTA connection status updated
- ✅ Sync log entry created
- ✅ SSE event broadcasted

## Data Mapping Reference

### Room Type Mapping

| Dummy Channel Manager | PMS Database |
|----------------------|-------------|
| `ROOM_1` | `room_type_id: 1` (Standard King) |
| `ROOM_2` | `room_type_id: 2` (Deluxe Suite) |
| `ROOM_3` | `room_type_id: 3` (Executive King) |
| `ROOM_4` | `room_type_id: 4` (Ocean View King) |
| `ROOM_5` | `room_type_id: 5` (Presidential Suite) |
| `ROOM_6` | `room_type_id: 6` (Business Twin) |

**Table:** `ota_room_mappings`
- `ota_room_code` → `room_type_id`

### Rate Plan Mapping

| Dummy Channel Manager | PMS Database |
|----------------------|-------------|
| `BAR` | `rate_plan_id: 1` (Best Available Rate) |
| `NON_REFUNDABLE` | `rate_plan_id: 2` (Non-Refundable) |
| `CORPORATE` | `rate_plan_id: 3` (Corporate) |
| `PROMOTIONAL` | `rate_plan_id: 4` (Promotional) |
| `LONG_STAY` | `rate_plan_id: 5` (Long Stay) |

**Table:** `ota_rate_mappings`
- `ota_rate_code` → `rate_plan_id`

### External Booking ID Storage

Dummy channel manager confirmation numbers (e.g., `HRS-2024-A1B2C3`) are stored in `Booking.internal_notes` as JSON:

```json
{
  "external_booking_id": "HRS-2024-A1B2C3",
  "ota_connection_id": 1,
  "ota_code": "BOOKING",
  "source": "channel_manager_webhook"
}
```

This allows the backend to find bookings by external ID when processing modification/cancellation webhooks.

## Database Tables Updated

### Booking System Tables

1. **`bookings`**
   - New bookings created from `booking.created` webhook
   - Updated from `booking.modified` webhook
   - Status updated from `booking.cancelled` webhook
   - Fields: booking_number, confirmation_code, guest_id, room_type_id, arrival_date, departure_date, status, channel, booking_source, total_price, commission_rate, commission_amount, net_revenue, internal_notes

2. **`guests`**
   - Created or updated from booking webhooks
   - Fields: first_name, last_name, email, phone, country, nationality

3. **`reservation_history`**
   - Audit trail entries for modifications and cancellations
   - Fields: reservation_id, action, old_value, new_value, notes

### Channel Manager Tables

1. **`ota_connections`**
   - Connection status updated from `sync.status` webhook
   - Fields: connection_status, last_sync_at, error_message

2. **`availability_grid`**
   - Updated from `booking.created` (decrement available)
   - Updated from `booking.modified` (adjust for date changes)
   - Updated from `booking.cancelled` (increment available)
   - Updated from `availability.updated` webhook
   - Updated from `restrictions.updated` webhook (flags)
   - Fields: room_type_id, grid_date, total_inventory, sold, blocked, available, stop_sell_flag, cta_flag, ctd_flag, min_stay, max_stay

3. **`channel_restrictions`**
   - Created/updated from `restrictions.updated` webhook
   - Fields: ota_connection_id, room_type_id, restriction_date, restriction_type, restriction_value

4. **`sync_logs`**
   - Created from `sync.status` webhook
   - Fields: ota_connection_id, sync_type, sync_direction, status, records_processed, records_failed, completed_at

5. **`daily_rates`**
   - Updated from `rates.updated` webhook
   - Fields: room_type_id, rate_plan_id, date, override_rate

## Troubleshooting

### Issue: Webhook Not Received by Backend

**Symptoms:**
- Dummy channel manager shows webhook sent successfully
- Backend logs show no webhook received
- No booking created in database

**Diagnosis:**
1. Check webhook URL configuration:
   ```bash
   curl http://localhost:8001/api/webhooks/status
   ```
   Should show: `http://localhost:8000/api/v1/webhooks/channel-manager`

2. Check backend is running:
   ```bash
   curl http://localhost:8000/health
   ```

3. Check network connectivity:
   - Verify both servers are on same network
   - Check firewall settings
   - Verify ports 8000 and 8001 are accessible

**Solution:**
- Reconfigure webhook URL if incorrect
- Restart backend server if not running
- Check firewall/network settings

### Issue: Room Type Mapping Not Found

**Symptoms:**
- Backend logs show: `Room type mapping not found for code: ROOM_X`
- Webhook returns 404 error
- Booking not created

**Diagnosis:**
```sql
SELECT ota_room_code, room_type_id, is_active
FROM ota_room_mappings
WHERE ota_connection_id = 1;
```

**Solution:**
- Create missing room mappings
- Verify `is_active = true`
- Check `ota_connection_id` matches webhook

### Issue: Rate Plan Mapping Not Found

**Symptoms:**
- Backend logs show: `Rate plan mapping not found`
- Booking created but rate_plan_id is NULL
- Warning in logs

**Diagnosis:**
```sql
SELECT ota_rate_code, rate_plan_id, is_active
FROM ota_rate_mappings
WHERE ota_connection_id = 1;
```

**Solution:**
- Create missing rate mappings
- Verify `is_active = true`
- Booking will still be created (rate_plan_id will be NULL)

### Issue: Booking Not Found for Modification/Cancellation

**Symptoms:**
- Backend logs show: `Booking not found: HRS-2024-XXXXXX`
- Webhook returns 404 error
- Modification/cancellation fails

**Diagnosis:**
```sql
-- Check if booking exists
SELECT id, booking_number, internal_notes
FROM bookings
WHERE internal_notes LIKE '%HRS-2024-XXXXXX%';
```

**Solution:**
- Verify booking was created initially
- Check `internal_notes` contains correct `external_booking_id`
- Ensure external_booking_id in webhook matches stored value

### Issue: Availability Not Updating

**Symptoms:**
- Booking created but availability grid not updated
- Available count incorrect

**Diagnosis:**
```sql
-- Check availability grid
SELECT room_type_id, grid_date, available, sold, total_inventory
FROM availability_grid
WHERE room_type_id = 1
  AND grid_date >= '2025-01-20'
  AND grid_date < '2025-01-22';
```

**Solution:**
- Verify availability grid entries exist for dates
- Check backend logs for availability update errors
- Manually update availability grid if needed

### Issue: SSE Events Not Received

**Symptoms:**
- Webhooks processed successfully
- Database updated correctly
- No SSE events received by frontend

**Diagnosis:**
1. Check SSE connection:
   - Verify frontend is connected to SSE endpoint
   - Check authentication token is valid

2. Check backend logs:
   - Look for `[SSE]` messages
   - Verify `broadcast_sse_event` is called
   - Check number of active connections

**Solution:**
- Verify SSE endpoint is accessible
- Check authentication
- Ensure frontend SSE connection is established
- Check backend logs for SSE broadcast errors

## Best Practices

### 1. Idempotency

- Webhooks should be idempotent (can be safely retried)
- Use external_booking_id to prevent duplicate bookings
- Check if booking exists before creating

### 2. Error Handling

- Always validate webhook payloads
- Return appropriate HTTP status codes
- Log errors for debugging
- Don't fail silently

### 3. Data Consistency

- Use database transactions for multi-table updates
- Update availability grid atomically
- Create audit trail entries

### 4. Performance

- Process webhooks asynchronously where possible
- Batch availability grid updates
- Use database indexes for lookups

### 5. Monitoring

- Log all webhook events
- Track sync status
- Monitor error rates
- Alert on connection failures

## Summary

This end-to-end integration enables:

1. **Complete Booking Lifecycle:**
   - Create → Modify → Cancel
   - All operations flow from dummy channel manager to PMS

2. **Real-Time Synchronization:**
   - Availability updates
   - Rate updates
   - Restriction updates
   - Sync status updates

3. **Data Consistency:**
   - Bookings in PMS match dummy channel manager
   - Availability grid reflects current state
   - Guest information synchronized

4. **Real-Time Updates:**
   - SSE events broadcast to frontend
   - UI updates automatically
   - No manual refresh needed

## Next Steps

1. **Set up database mappings** (OTA connections, room mappings, rate mappings)
2. **Configure webhook URL** in dummy channel manager
3. **Test booking creation** end-to-end
4. **Test booking modification** end-to-end
5. **Test booking cancellation** end-to-end
6. **Test availability updates** end-to-end
7. **Test rates and restrictions** updates
8. **Monitor sync status** and logs
9. **Set up frontend** to receive SSE events
10. **Implement error handling** and retry logic

---

**Last Updated:** January 18, 2025
**Version:** 1.0.0
