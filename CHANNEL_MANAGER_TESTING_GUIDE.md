# Channel Manager Webhooks - Complete Testing Guide

This document provides step-by-step instructions to test all channel manager webhook endpoints between `dummy_channel_manager` and `glimmora-backend`.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Server Setup](#server-setup)
3. [Database Setup](#database-setup)
4. [API Testing](#api-testing)
   - [Booking Created Webhook](#1-booking-created-webhook)
   - [Booking Modified Webhook](#2-booking-modified-webhook)
   - [Booking Cancelled Webhook](#3-booking-cancelled-webhook)
   - [Availability Updated Webhook](#4-availability-updated-webhook)
   - [Sync Status Webhook](#5-sync-status-webhook)
5. [Verification](#verification)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

1. **Python 3.10+** installed
2. **Dependencies installed** for both projects:
   ```bash
   # In glimmora-backend
   cd C:\Users\princ\Desktop\glimmora-backend
   pip install -r requirements.txt
   
   # In dummy_channel_manager
   cd C:\Users\princ\Desktop\glimmora-backend\dummy_channel_manager
   pip install -r requirements.txt
   ```
3. **Database initialized** with OTA connections and room mappings

---

## Server Setup

### Step 1: Start Glimmora Backend

```bash
# Terminal 1
cd C:\Users\princ\Desktop\glimmora-backend
python -m uvicorn app.main:app --reload --port 8000
```

**Expected Output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

**Verify:**
```bash
curl http://localhost:8000/health
# Expected: {"status": "ok"}
```

### Step 2: Start Dummy Channel Manager

```bash
# Terminal 2
cd C:\Users\princ\Desktop\glimmora-backend\dummy_channel_manager
python main.py
```

**Expected Output:**
```
CRS Simulator API started successfully!
[WEBHOOK] Webhook URL: http://localhost:8001/webhooks/crs
[INFO] Available webhook trigger endpoints:
   POST /api/webhooks/trigger/availability
   POST /api/webhooks/trigger/sync-status
INFO:     Uvicorn running on http://0.0.0.0:8001
```

**Verify:**
```bash
curl http://localhost:8001/
# Expected: Service information JSON
```

---

## Database Setup

### Step 3: Create OTA Room Mappings

Before testing webhooks, ensure room mappings exist. The dummy channel manager uses `ROOM_1` through `ROOM_6` codes.

**Option A: Run Seed Script (if available)**
```bash
cd C:\Users\princ\Desktop\glimmora-backend
python -m app.db.seeds.seed_channel_manager
```

**Option B: Verify Mappings Exist**
```bash
# Check if mappings exist for ROOM_1 through ROOM_6
# If not, they will need to be created manually or via API
```

### Step 4: Configure Webhook URL

Configure the channel manager to send webhooks to the backend:

```bash
# PowerShell
$webhookConfig = @{
    url = "http://localhost:8000/api/v1/webhooks/channel-manager"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8001/api/webhooks/configure" `
    -Method Post `
    -ContentType "application/json" `
    -Body $webhookConfig
```

**Expected Response:**
```json
{
    "success": true,
    "data": {
        "webhook_url": "http://localhost:8000/api/v1/webhooks/channel-manager"
    },
    "message": "Webhook URL configured: http://localhost:8000/api/v1/webhooks/channel-manager",
    "errors": null
}
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

---

## API Testing

### 1. Booking Created Webhook

This webhook is triggered when a new reservation is created in the channel manager.

#### Test: Create a Reservation

**PowerShell:**
```powershell
$reservationData = @{
    hotel_id = $null
    room_id = 1
    rate_plan_id = 0  # 0=BAR, 1=NON_REFUNDABLE, 2=CORPORATE, 3=PROMOTIONAL, 4=LONG_STAY
    arrival_date = "2025-01-15"
    departure_date = "2025-01-17"
    adults = 2
    children = 0
    guest = @{
        first_name = "John"
        last_name = "Doe"
        email = "john.doe@example.com"
        phone = "+1234567890"
        notes = "Test booking"
    }
    special_requests = "Early check-in preferred"
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri "http://localhost:8001/api/v2/reservations" `
    -Method Post `
    -ContentType "application/json" `
    -Body $reservationData

$reservationId = $response.data.id
$confirmationNumber = $response.data.confirmation_number

Write-Output "Reservation ID: $reservationId"
Write-Output "Confirmation Number: $confirmationNumber"
```

**cURL:**
```bash
curl -X POST http://localhost:8001/api/v2/reservations \
  -H "Content-Type: application/json" \
  -d '{
    "hotel_id": null,
    "room_id": 1,
    "rate_plan_id": 0,
    "arrival_date": "2025-01-15",
    "departure_date": "2025-01-17",
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

**Expected Channel Manager Response:**
```json
{
    "success": true,
    "data": {
        "id": "uuid-here",
        "confirmation_number": "HRS-2026-XXXXXX",
        "hotel_id": "uuid-here",
        "room_type_id": "uuid-here",
        "check_in": "2025-01-15",
        "check_out": "2025-01-17",
        "guest_name": "John Doe",
        "guest_email": "john.doe@example.com",
        "status": "CONFIRMED",
        "total_amount": 525.0,
        "currency": "USD"
    },
    "message": "Reservation created successfully"
}
```

**Expected Channel Manager Logs:**
```
[WEBHOOK] Sending webhook: booking.created
[WEBHOOK]    URL: http://localhost:8000/api/v1/webhooks/channel-manager
[WEBHOOK]    Payload keys: ['event_type', 'ota_connection_id', 'ota_code', 'external_booking_id', 'timestamp', 'booking']
[WEBHOOK] SUCCESS - Status: 200
[WEBHOOK]    Response: {'success': True, 'message': 'Booking created successfully', 'booking_id': X, 'booking_number': 'BK-XXXXXX-XXXX'}
```

**Expected Backend Response:**
```json
{
    "success": true,
    "message": "Booking created successfully",
    "booking_id": 1,
    "booking_number": "BK-20250118-XXXX"
}
```

**Expected Backend Logs:**
```
================================================================================
[WEBHOOK RECEIVER] Received webhook
[WEBHOOK RECEIVER]    Event Type: booking.created
[WEBHOOK RECEIVER]    OTA Connection ID: 1
[handle_booking_created] Processing booking.created webhook...
[handle_booking_created] OK: Payload validated
[handle_booking_created] OK: OTA connection found: Booking.com (ID: 1)
[handle_booking_created] OK: Room type mapped: ROOM_1 -> room_type_id=1
[handle_booking_created] OK: Guest ready: ID=X, Email=john.doe@example.com
[handle_booking_created] SUCCESS: Database commit successful! Booking ID: X
[WEBHOOK RECEIVER] SUCCESS: booking.created processed successfully
```

**Verification:**
- Check backend database for new booking entry
- Verify guest was created or updated
- Verify availability grid was updated

---

### 2. Booking Modified Webhook

This webhook is triggered when an existing reservation is modified.

#### Test: Modify a Reservation

**PowerShell:**
```powershell
# Use the reservation ID from previous test
$reservationId = "uuid-from-previous-test"

$modifyData = @{
    check_out = "2025-01-18"  # Extended stay
    special_requests = "Late checkout preferred"
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "http://localhost:8001/api/reservations/$reservationId" `
    -Method Put `
    -ContentType "application/json" `
    -Body $modifyData

$response | ConvertTo-Json -Depth 3
```

**cURL:**
```bash
curl -X PUT http://localhost:8001/api/reservations/{reservation_id} \
  -H "Content-Type: application/json" \
  -d '{
    "check_out": "2025-01-18",
    "special_requests": "Late checkout preferred"
  }'
```

**Expected Channel Manager Response:**
```json
{
    "success": true,
    "data": {
        "id": "uuid-here",
        "check_in": "2025-01-15",
        "check_out": "2025-01-18",
        "status": "MODIFIED",
        "total_amount": 675.0
    },
    "message": "Reservation modified successfully"
}
```

**Expected Channel Manager Logs:**
```
[WEBHOOK] Sending webhook: booking.modified
[WEBHOOK] SUCCESS - Status: 200
[WEBHOOK]    Response: {'success': True, 'message': 'Booking modified successfully', 'booking_id': X}
```

**Expected Backend Response:**
```json
{
    "success": true,
    "message": "Booking modified successfully",
    "booking_id": 1
}
```

**Expected Backend Logs:**
```
[WEBHOOK RECEIVER] Received webhook
[WEBHOOK RECEIVER]    Event Type: booking.modified
[handle_booking_modified] Processing booking.modified webhook...
[handle_booking_modified] OK: Found booking: ID=X, booking_number=BK-XXXXXX
[WEBHOOK RECEIVER] SUCCESS: booking.modified processed successfully
```

**Verification:**
- Check backend database for updated booking
- Verify dates were updated correctly
- Verify availability grid reflects the changes

---

### 3. Booking Cancelled Webhook

This webhook is triggered when a reservation is cancelled.

#### Test: Cancel a Reservation

**PowerShell:**
```powershell
$reservationId = "uuid-from-previous-test"

$response = Invoke-RestMethod -Uri "http://localhost:8001/api/reservations/$reservationId" `
    -Method Delete

$response | ConvertTo-Json -Depth 3
```

**cURL:**
```bash
curl -X DELETE http://localhost:8001/api/reservations/{reservation_id}
```

**Expected Channel Manager Response:**
```json
{
    "success": true,
    "data": {
        "id": "uuid-here",
        "status": "CANCELLED",
        "updated_at": "2025-01-18T16:XX:XX"
    },
    "message": "Reservation cancelled successfully"
}
```

**Expected Channel Manager Logs:**
```
[WEBHOOK] Sending webhook: booking.cancelled
[WEBHOOK] SUCCESS - Status: 200
[WEBHOOK]    Response: {'success': True, 'message': 'Booking cancelled successfully', 'booking_id': X}
```

**Expected Backend Response:**
```json
{
    "success": true,
    "message": "Booking cancelled successfully",
    "booking_id": 1
}
```

**Expected Backend Logs:**
```
[WEBHOOK RECEIVER] Received webhook
[WEBHOOK RECEIVER]    Event Type: booking.cancelled
[handle_booking_cancelled] Processing booking.cancelled webhook...
[handle_booking_cancelled] OK: Found booking: ID=X, booking_number=BK-XXXXXX
[WEBHOOK RECEIVER] SUCCESS: booking.cancelled processed successfully
```

**Verification:**
- Check backend database for cancelled booking status
- Verify availability grid was updated (inventory released)
- Verify booking status is "cancelled"

---

### 4. Availability Updated Webhook

This webhook is triggered manually to update availability information.

#### Test: Trigger Availability Update

**PowerShell:**
```powershell
# Update all room types for today
$response = Invoke-RestMethod -Uri "http://localhost:8001/api/webhooks/trigger/availability?ota_connection_id=1" `
    -Method Post

$response | ConvertTo-Json -Depth 3
```

**cURL:**
```bash
curl -X POST "http://localhost:8001/api/webhooks/trigger/availability?ota_connection_id=1"
```

**Optional Parameters:**
- `room_type_code`: Specific room type (e.g., "ROOM_1")
- `date`: Specific date (e.g., "2025-01-20")

**Example with parameters:**
```bash
curl -X POST "http://localhost:8001/api/webhooks/trigger/availability?ota_connection_id=1&room_type_code=ROOM_1&date=2025-01-20"
```

**Expected Channel Manager Response:**
```json
{
    "success": true,
    "data": {
        "event_type": "availability.updated",
        "ota_connection_id": 1,
        "timestamp": "2025-01-18T16:XX:XX",
        "availability": [
            {
                "room_type_code": "ROOM_1",
                "date": "2025-01-18",
                "available": 20,
                "sold": 0,
                "blocked": 0,
                "total": 20
            },
            {
                "room_type_code": "ROOM_2",
                "date": "2025-01-18",
                "available": 10,
                "sold": 0,
                "blocked": 0,
                "total": 10
            }
            // ... more room types
        ]
    },
    "message": "Availability webhook triggered for 6 room types"
}
```

**Expected Channel Manager Logs:**
```
[WEBHOOK] Sending webhook: availability.updated
[WEBHOOK] SUCCESS - Status: 200
[WEBHOOK]    Response: {'success': True, 'message': 'Availability updated for 6 room types', 'updated_count': 6}
```

**Expected Backend Response:**
```json
{
    "success": true,
    "message": "Availability updated for 6 room types",
    "updated_count": 6
}
```

**Expected Backend Logs:**
```
[WEBHOOK RECEIVER] Received webhook
[WEBHOOK RECEIVER]    Event Type: availability.updated
[WEBHOOK RECEIVER] -> Routing to handle_availability_updated
[WEBHOOK RECEIVER] SUCCESS: availability.updated processed successfully
```

**Verification:**
- Check backend `availability_grid` table for updated entries
- Verify availability counts match the webhook payload

---

### 5. Sync Status Webhook

This webhook is triggered manually to update the sync status of the OTA connection.

#### Test: Trigger Sync Status Update

**PowerShell:**
```powershell
$response = Invoke-RestMethod -Uri "http://localhost:8001/api/webhooks/trigger/sync-status?ota_connection_id=1&connection_status=connected&sync_type=full&records_processed=150&records_failed=0" `
    -Method Post

$response | ConvertTo-Json -Depth 3
```

**cURL:**
```bash
curl -X POST "http://localhost:8001/api/webhooks/trigger/sync-status?ota_connection_id=1&connection_status=connected&sync_type=full&records_processed=150&records_failed=0"
```

**Query Parameters:**
- `ota_connection_id`: OTA connection ID (required, default: 1)
- `connection_status`: Status of connection (default: "connected")
- `sync_type`: Type of sync - "full" or "incremental" (default: "full")
- `records_processed`: Number of records processed (default: 150)
- `records_failed`: Number of records that failed (default: 0)

**Expected Channel Manager Response:**
```json
{
    "success": true,
    "data": {
        "event_type": "sync.status",
        "ota_connection_id": 1,
        "timestamp": "2025-01-18T16:XX:XX",
        "status": {
            "connection_status": "connected",
            "last_sync_at": "2025-01-18T16:XX:XX",
            "sync_type": "full",
            "records_processed": 150,
            "records_failed": 0,
            "error_message": null
        }
    },
    "message": "Sync status webhook triggered"
}
```

**Expected Channel Manager Logs:**
```
[WEBHOOK] Sending webhook: sync.status
[WEBHOOK] SUCCESS - Status: 200
[WEBHOOK]    Response: {'success': True, 'message': 'Sync status updated', 'ota_connection_id': 1}
```

**Expected Backend Response:**
```json
{
    "success": true,
    "message": "Sync status updated",
    "ota_connection_id": 1
}
```

**Expected Backend Logs:**
```
[WEBHOOK RECEIVER] Received webhook
[WEBHOOK RECEIVER]    Event Type: sync.status
[WEBHOOK RECEIVER] -> Routing to handle_sync_status
[WEBHOOK RECEIVER] SUCCESS: sync.status processed successfully
```

**Verification:**
- Check `ota_connections` table for updated `connection_status` and `last_sync_at`
- Check `sync_logs` table for new sync log entry

---

## Verification

### Check Backend Database

After testing webhooks, verify the data in the backend database:

1. **Bookings Table:**
   ```sql
   SELECT id, booking_number, confirmation_code, guest_id, room_type_id, 
          arrival_date, departure_date, status, channel
   FROM bookings
   ORDER BY created_at DESC
   LIMIT 10;
   ```

2. **Guests Table:**
   ```sql
   SELECT id, first_name, last_name, email, phone
   FROM guests
   ORDER BY created_at DESC
   LIMIT 10;
   ```

3. **Availability Grid:**
   ```sql
   SELECT room_type_id, grid_date, total_inventory, sold, blocked, available
   FROM availability_grid
   WHERE grid_date >= DATE('now')
   ORDER BY grid_date, room_type_id;
   ```

4. **Sync Logs:**
   ```sql
   SELECT id, ota_connection_id, sync_type, status, records_processed, 
          records_failed, completed_at
   FROM sync_logs
   ORDER BY completed_at DESC
   LIMIT 10;
   ```

### Check Logs

**Backend Logs:**
- Look for `[WEBHOOK RECEIVER]` messages
- Verify all webhooks show `SUCCESS` status
- Check for any `ERROR` messages

**Channel Manager Logs:**
- Look for `[WEBHOOK]` messages
- Verify all webhooks show `SUCCESS - Status: 200`
- Check for any `FAILED` or `ERROR` messages

---

## Troubleshooting

### Issue: Webhook URL Not Configured

**Symptoms:**
- Channel manager logs show: `[WEBHOOK] WARNING: WEBHOOK_URL not configured`
- No webhooks being sent

**Solution:**
```bash
# Configure webhook URL
curl -X POST http://localhost:8001/api/webhooks/configure \
  -H "Content-Type: application/json" \
  -d '{"url": "http://localhost:8000/api/v1/webhooks/channel-manager"}'
```

### Issue: Room Type Mapping Not Found

**Symptoms:**
- Backend logs show: `ERROR: Room type mapping not found for code: ROOM_X`
- Webhook returns 404 error

**Solution:**
1. Verify OTA room mappings exist in database:
   ```sql
   SELECT ota_room_code, room_type_id, is_active
   FROM ota_room_mappings
   WHERE ota_connection_id = 1;
   ```
2. If mappings don't exist, create them for ROOM_1 through ROOM_6

### Issue: OTA Connection Not Found

**Symptoms:**
- Backend logs show: `ERROR: OTA connection not found or inactive`
- Webhook returns 404 error

**Solution:**
1. Verify OTA connection exists:
   ```sql
   SELECT id, ota_code, ota_name, is_active
   FROM ota_connections
   WHERE id = 1;
   ```
2. If not found, seed channel manager data

### Issue: Unicode Encoding Errors

**Symptoms:**
- Backend crashes with `UnicodeEncodeError`
- Emoji characters in logs cause issues on Windows

**Solution:**
- All emoji characters have been removed from the codebase
- Use plain ASCII text in logs

### Issue: Webhook Timeout

**Symptoms:**
- Channel manager logs show: `[WEBHOOK] TIMEOUT - Webhook request timed out after 10 seconds`

**Solution:**
1. Verify backend is running on port 8000
2. Check firewall settings
3. Verify webhook URL is correct

---

## Test Summary

After running all tests, you should have:

✅ **5 Webhook Types Tested:**
1. `booking.created` - Creates new bookings
2. `booking.modified` - Updates existing bookings
3. `booking.cancelled` - Cancels bookings
4. `availability.updated` - Updates availability grid
5. `sync.status` - Updates sync status and logs

✅ **Verification Points:**
- All webhooks return 200 status
- Database entries are created/updated correctly
- Logs show successful processing
- Availability grid reflects changes
- Sync logs are created

---

## Additional Resources

- **Webhook Specification:** See `CHANNEL_MANAGER_WEBHOOKS.md`
- **Implementation Details:** See `IMPLEMENTATION_SUMMARY.md`
- **Frontend Integration:** See `FRONTEND_SSE_INTEGRATION.md`

---

## Notes

- All webhooks are sent asynchronously from the channel manager
- Backend processes webhooks synchronously and returns immediate responses
- Database commits are performed after successful webhook processing
- SSE events are broadcast to connected frontend clients (not tested in this guide)

---

**Last Updated:** January 18, 2026
**Tested With:**
- Glimmora Backend: v0.1.0 (port 8000)
- Dummy Channel Manager: v1.0.0 (port 8001)
