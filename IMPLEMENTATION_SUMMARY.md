# Channel Manager Webhooks & SSE Implementation Summary

This document summarizes all the changes made to implement channel manager webhooks and Server-Side Events (SSE) for real-time updates.

## Overview

The implementation includes:
1. **Updated Dummy Channel Manager** - Now sends all webhook types in the correct format
2. **Backend Webhook Receivers** - Processes webhooks and updates PMS database
3. **SSE Endpoints** - Real-time event streaming to frontend
4. **Frontend Integration Guide** - Complete documentation for frontend developers

## Files Modified

### 1. Dummy Channel Manager

**File:** `dummy_channel_manager/models.py`
- Added new webhook payload models:
  - `BookingCreatedPayload`
  - `BookingModifiedPayload`
  - `BookingCancelledPayload`
  - `AvailabilityUpdatedPayload`
  - `RatesUpdatedPayload`
  - `RestrictionsUpdatedPayload`
  - `SyncStatusPayload`
  - Supporting models: `BookingWebhookPayload`, `GuestInfo`, `BookingPricing`, `BookingPayment`, etc.

**File:** `dummy_channel_manager/main.py`
- Updated `trigger_webhook()` function to support new format
- Added `trigger_webhook_v2()` for new webhook format
- Added helper functions:
  - `build_booking_created_webhook()`
  - `build_booking_modified_webhook()`
  - `build_booking_cancelled_webhook()`
- Updated reservation endpoints to use new webhook format
- Added API endpoints for manual webhook triggering:
  - `POST /api/webhooks/trigger/availability`
  - `POST /api/webhooks/trigger/sync-status`

### 2. Glimmora Backend

**File:** `app/api/v1/webhooks.py` (NEW)
- Main webhook receiver endpoint: `POST /api/v1/webhooks/channel-manager`
- SSE endpoint: `GET /api/v1/webhooks/channel-manager/sse`
- Webhook handlers:
  - `handle_booking_created()` - Creates booking from OTA webhook
  - `handle_booking_modified()` - Updates existing booking
  - `handle_booking_cancelled()` - Cancels booking
  - `handle_availability_updated()` - Updates availability grid
  - `handle_rates_updated()` - Updates rate data
  - `handle_restrictions_updated()` - Updates restrictions
  - `handle_sync_status()` - Updates sync status
- Helper functions:
  - `get_or_create_guest()` - Guest management
  - `get_room_type_id_from_code()` - OTA code to PMS ID mapping
  - `get_rate_plan_id_from_code()` - Rate code to PMS ID mapping
  - `find_booking_by_external_id()` - Find booking by OTA booking ID
  - `update_availability_grid()` - Update availability data
  - `broadcast_sse_event()` - Broadcast SSE events to connected clients

**File:** `app/api/routes.py`
- Added webhook router registration:
  ```python
  api_router.include_router(webhooks.router, prefix="/v1/webhooks", tags=["webhooks"])
  ```

### 3. Documentation

**File:** `CHANNEL_MANAGER_WEBHOOKS.md` (Existing)
- Complete webhook specification document
- All webhook payload formats
- PMS actions for each webhook type

**File:** `FRONTEND_SSE_INTEGRATION.md` (NEW)
- Complete frontend integration guide
- SSE connection setup examples (JavaScript/TypeScript/React)
- Event type documentation with data structures
- UI component update recommendations
- Notification system examples
- Error handling and best practices
- Testing guide

**File:** `IMPLEMENTATION_SUMMARY.md` (This file)
- Summary of all changes
- API endpoint reference
- Testing instructions

## API Endpoints

### Webhook Receiver

**POST** `/api/v1/webhooks/channel-manager`

Receives webhooks from channel manager and processes them. Routes internally based on `event_type` field.

**Payload:** See `CHANNEL_MANAGER_WEBHOOKS.md` for complete payload formats.

**Response:**
```json
{
  "success": true,
  "message": "Booking created successfully",
  "booking_id": 123,
  "booking_number": "BK-20240115-A1B2"
}
```

### SSE Stream

**GET** `/api/v1/webhooks/channel-manager/sse`

Server-Side Events stream for real-time updates. Requires authentication.

**Query Parameters:**
- `token` (optional): Auth token if not using Authorization header

**Response:** `text/event-stream`

**Events:**
- `booking.created` - New booking from OTA
- `booking.modified` - Booking modified
- `booking.cancelled` - Booking cancelled
- `availability.updated` - Availability updated
- `rates.updated` - Rates updated
- `restrictions.updated` - Restrictions updated
- `sync.status` - Sync status update

See `FRONTEND_SSE_INTEGRATION.md` for event data formats.

## Database Updates

The webhook handlers update the following database tables:

1. **Bookings:**
   - `Booking` - Main booking table
   - `Guest` - Guest information
   - `ReservationHistory` - Audit trail

2. **Channel Manager:**
   - `AvailabilityGrid` - Availability data
   - `ChannelRestriction` - Restrictions
   - `SyncLog` - Sync audit log
   - `OTAConnection` - Connection status

3. **Inventory:**
   - `DailyRate` - Rate data
   - `DailyAvailability` - Availability data

**Note:** External booking IDs are stored in `Booking.internal_notes` as JSON:
```json
{
  "external_booking_id": "OTA-123456",
  "ota_connection_id": 1,
  "ota_code": "BOOKING",
  "source": "channel_manager_webhook"
}
```

## Testing

### 1. Test Dummy Channel Manager Webhooks

1. Start dummy channel manager:
   ```bash
   cd dummy_channel_manager
   python main.py
   ```

2. Configure webhook URL:
   ```bash
   curl -X POST http://localhost:8000/api/webhooks/configure \
     -H "Content-Type: application/json" \
     -d '{"url": "http://localhost:8001/api/v1/webhooks/channel-manager"}'
   ```

3. Create a test booking:
   ```bash
   curl -X POST http://localhost:8000/api/v2/reservations \
     -H "Content-Type: application/json" \
     -d '{
       "guest": {"first_name": "Test", "last_name": "User", "email": "test@example.com"},
       "room_id": 1,
       "rate_plan_id": 0,
       "arrival_date": "2024-02-01",
       "departure_date": "2024-02-05",
       "adults": 2
     }'
   ```

4. Verify webhook was received by backend (check backend logs)

### 2. Test SSE Connection

1. Start glimmora-backend:
   ```bash
   uvicorn app.main:app --reload --port 8001
   ```

2. Connect to SSE endpoint:
   ```javascript
   const eventSource = new EventSource('http://localhost:8001/api/v1/webhooks/channel-manager/sse?token=YOUR_TOKEN');
   eventSource.onmessage = (event) => {
     console.log('SSE Event:', JSON.parse(event.data));
   };
   ```

3. Trigger a webhook from dummy channel manager
4. Verify SSE event is received in browser console

### 3. Test All Webhook Types

**Booking Created:**
- Create reservation via dummy channel manager API
- Verify booking appears in PMS database
- Verify SSE event is broadcast

**Booking Modified:**
- Modify reservation via dummy channel manager API
- Verify booking is updated in PMS
- Verify SSE event with changes

**Booking Cancelled:**
- Cancel reservation via dummy channel manager API
- Verify booking status is cancelled
- Verify availability is restored

**Availability Updated:**
```bash
curl -X POST http://localhost:8000/api/webhooks/trigger/availability?ota_connection_id=1
```

**Sync Status:**
```bash
curl -X POST http://localhost:8000/api/webhooks/trigger/sync-status?ota_connection_id=1&connection_status=connected&sync_type=full
```

## Prerequisites

### Before Processing Webhooks

The following must be configured in the PMS:

1. **OTA Connection** - Create `OTAConnection` record with `ota_connection_id`
2. **Room Mappings** - Create `OTARoomMapping` records mapping OTA room codes to PMS `room_type_id`
3. **Rate Mappings** - Create `OTARateMapping` records mapping OTA rate codes to PMS `rate_plan_id`

These can be created via:
- Database seed scripts (`app/db/seeds/seed_channel_manager.py`)
- Admin API endpoints (if available)
- Direct database insertion

### Required Mappings Example

```python
# Room mapping
OTARoomMapping(
    property_id=1,
    ota_connection_id=1,
    room_type_id=5,  # PMS room type ID
    ota_room_code="ROOM_1",  # Code from webhook
    is_active=True
)

# Rate mapping
OTARateMapping(
    property_id=1,
    ota_connection_id=1,
    rate_plan_id=1,  # PMS rate plan ID
    ota_rate_code="BAR",  # Code from webhook
    is_active=True
)
```

## Configuration

### Dummy Channel Manager

**Environment Variable:**
- `WEBHOOK_URL` - Target webhook URL (default: `http://localhost:8001/webhooks/crs`)

**API Configuration:**
- `POST /api/webhooks/configure` - Set webhook URL
- `GET /api/webhooks/status` - Get current webhook status

### Glimmora Backend

**No special configuration required** - Webhook endpoints are available at:
- `/api/v1/webhooks/channel-manager` (POST)
- `/api/v1/webhooks/channel-manager/sse` (GET)

Ensure proper authentication is configured for SSE endpoint.

## Error Handling

### Webhook Errors

- Invalid payload → 400 Bad Request
- OTA connection not found → 404 Not Found
- Room/Rate mapping not found → 404 Not Found
- Processing error → 500 Internal Server Error

All errors are logged with full stack traces for debugging.

### SSE Errors

- Authentication failure → Connection closed
- Network error → Auto-reconnect (client-side)
- Server error → Event skipped, connection maintained

## Security Considerations

1. **Webhook Authentication:** Currently no authentication on webhook endpoint. In production, implement:
   - Webhook signature verification
   - IP whitelist
   - API key validation

2. **SSE Authentication:** Required via `get_current_user` dependency. Token can be passed:
   - Authorization header (preferred)
   - Query parameter `token` (fallback)

3. **Data Validation:** All webhook payloads are validated using Pydantic models

## Performance Notes

1. **SSE Connections:** In-memory storage of SSE connections. For production:
   - Use Redis for distributed SSE broadcasting
   - Implement connection pooling
   - Add connection limits per user

2. **Database Updates:** Webhook handlers update multiple tables. Consider:
   - Batch operations for bulk updates
   - Database indexing on lookup fields
   - Connection pooling

3. **Background Tasks:** SSE broadcasting uses FastAPI BackgroundTasks for non-blocking execution

## Future Enhancements

1. **Webhook Authentication:** Add signature verification
2. **Distributed SSE:** Use Redis Pub/Sub for multi-instance deployments
3. **Webhook Retry:** Implement retry logic in dummy channel manager
4. **Event Filtering:** Allow clients to subscribe to specific event types
5. **Webhook Queue:** Add queue system for handling webhook bursts
6. **External Booking Mapping Table:** Create dedicated table for OTA booking ID tracking

## Support

For questions or issues:
1. Check `CHANNEL_MANAGER_WEBHOOKS.md` for webhook specifications
2. Check `FRONTEND_SSE_INTEGRATION.md` for frontend integration
3. Review backend logs for webhook processing errors
4. Test with dummy channel manager endpoints
