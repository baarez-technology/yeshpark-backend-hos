# Frontend Channel Manager Integration Guide

## Overview

This document provides a complete guide for integrating the frontend channel manager interface with the `dummy_channel_manager` system. The integration enables the frontend to display real-time channel manager data, including bookings, availability, rates, and sync status from the dummy channel manager.

## Architecture Overview

```
┌─────────────────────┐         ┌──────────────────────┐         ┌─────────────────────┐
│                     │         │                      │         │                     │
│  Frontend           │◄──SSE───┤  Glimmora Backend    │◄──HTTP──┤  Dummy Channel      │
│  (React/Vue/etc)    │         │  (Port 8000)         │         │  Manager            │
│                     │         │                      │         │  (Port 8001)        │
│                     │         │                      │         │                     │
└─────────────────────┘         └──────────────────────┘         └─────────────────────┘
       │                                  │                                  │
       │                                  │                                  │
       └─────────── API Calls ───────────┘                                  │
                                                                             │
                                                                      Webhooks
                                                                      (HTTP POST)
```

### Data Flow

1. **Dummy Channel Manager** → Creates/modifies bookings → Sends webhooks to **Glimmora Backend**
2. **Glimmora Backend** → Receives webhooks → Updates database → Broadcasts SSE events
3. **Frontend** → Connects to SSE stream → Receives real-time updates → Updates UI

## Components

### 1. Dummy Channel Manager (Port 8001)

**Purpose:** Simulates a real OTA/Channel Manager (like Booking.com, Expedia, etc.)

**Key Features:**
- Manages hotels, room types, rates, and reservations
- Sends webhooks when bookings are created/modified/cancelled
- Provides API endpoints for CRUD operations
- Supports availability and rate updates

**Endpoints:**
- `POST /api/v2/reservations` - Create reservation (triggers `booking.created` webhook)
- `PUT /api/reservations/{id}` - Modify reservation (triggers `booking.modified` webhook)
- `DELETE /api/reservations/{id}` - Cancel reservation (triggers `booking.cancelled` webhook)
- `GET /api/v2/rooms` - List all rooms with room_id mappings
- `GET /api/availability` - Check availability
- `POST /api/webhooks/configure` - Configure webhook URL
- `POST /api/webhooks/trigger/availability` - Manually trigger availability webhook
- `POST /api/webhooks/trigger/sync-status` - Manually trigger sync status webhook

### 2. Glimmora Backend (Port 8000)

**Purpose:** Receives webhooks from dummy channel manager and updates PMS database

**Key Features:**
- Webhook receiver endpoint: `POST /api/v1/webhooks/channel-manager`
- SSE endpoint: `GET /api/v1/webhooks/channel-manager/sse`
- Processes webhooks and updates bookings, availability, rates
- Broadcasts real-time events to frontend via SSE

**Webhook Types Handled:**
- `booking.created` - New booking from OTA
- `booking.modified` - Booking modification
- `booking.cancelled` - Booking cancellation
- `availability.updated` - Availability changes
- `rates.updated` - Rate changes
- `restrictions.updated` - Restriction changes
- `sync.status` - Sync status updates

### 3. Frontend Channel Manager Interface

**Purpose:** Display channel manager data and receive real-time updates

**Required Features:**
- Display OTA connections and their status
- Show bookings from OTAs
- Display availability grid
- Show rates and restrictions
- Real-time updates via SSE
- Manual sync triggers

## Integration Steps

### Step 1: Database Setup

Before the frontend can display channel manager data, ensure the database has:

1. **OTA Connections** - At least one OTA connection record
2. **OTA Room Mappings** - Maps OTA room codes (e.g., "ROOM_1") to PMS room_type_id
3. **OTA Rate Mappings** - Maps OTA rate codes (e.g., "BAR") to PMS rate_plan_id

**Example OTA Connection:**
```json
{
  "id": 1,
  "ota_code": "BOOKING",
  "ota_name": "Booking.com",
  "property_id": 1,
  "is_active": true,
  "connection_status": "connected"
}
```

**Example Room Mapping:**
```json
{
  "ota_connection_id": 1,
  "ota_room_code": "ROOM_1",
  "room_type_id": 1,
  "is_active": true
}
```

**Example Rate Mapping:**
```json
{
  "ota_connection_id": 1,
  "ota_rate_code": "BAR",
  "rate_plan_id": 1,
  "is_active": true
}
```

### Step 2: Configure Dummy Channel Manager Webhook URL

The dummy channel manager needs to know where to send webhooks:

**API Call:**
```http
POST http://localhost:8001/api/webhooks/configure
Content-Type: application/json

{
  "url": "http://localhost:8000/api/v1/webhooks/channel-manager"
}
```

**Verify Configuration:**
```http
GET http://localhost:8001/api/webhooks/status
```

### Step 3: Frontend SSE Connection Setup

The frontend must establish an SSE connection to receive real-time updates.

**Endpoint:** `GET /api/v1/webhooks/channel-manager/sse`

**Authentication:** Required (Bearer token in Authorization header)

**Important:** Since `EventSource` API doesn't support custom headers, use Fetch API instead.

**TypeScript/JavaScript Example:**
```typescript
let abortController: AbortController | null = null;
let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

async function connectSSE() {
  const token = localStorage.getItem('access_token');
  const url = `${API_BASE_URL}/api/v1/webhooks/channel-manager/sse`;
  
  abortController = new AbortController();
  
  try {
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'text/event-stream',
      },
      signal: abortController.signal,
    });

    if (!response.ok) {
      if (response.status === 401) {
        // Handle authentication failure
        return;
      }
      throw new Error(`SSE connection failed: ${response.status}`);
    }

    reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) {
      throw new Error('Response body is not readable');
    }

    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6));
          handleSSEEvent(data);
        } else if (line.startsWith(': ')) {
          // Keepalive ping - ignore
        }
      }
    }
  } catch (error) {
    console.error('SSE connection error:', error);
    // Implement reconnection logic
  }
}

function handleSSEEvent(event: any) {
  switch (event.type) {
    case 'connected':
      console.log('SSE connected');
      break;
    case 'booking.created':
      // Update UI with new booking
      updateBookingsList(event.data);
      break;
    case 'booking.modified':
      // Update existing booking in UI
      updateBookingInList(event.data);
      break;
    case 'booking.cancelled':
      // Remove or mark booking as cancelled
      removeBookingFromList(event.data.booking_id);
      break;
    case 'availability.updated':
      // Refresh availability grid
      refreshAvailabilityGrid();
      break;
    case 'rates.updated':
      // Refresh rates display
      refreshRatesDisplay();
      break;
    case 'sync.status':
      // Update sync status indicator
      updateSyncStatus(event.data);
      break;
  }
}

// Disconnect
function disconnectSSE() {
  if (abortController) {
    abortController.abort();
  }
  if (reader) {
    reader.cancel();
  }
}
```

### Step 4: Frontend API Integration

The frontend needs to call various backend APIs to display channel manager data.

#### 4.1 Get OTA Connections

**Endpoint:** `GET /api/v1/channel-manager/connections`

**Purpose:** Display list of OTA connections and their status

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "ota_code": "BOOKING",
      "ota_name": "Booking.com",
      "property_id": 1,
      "is_active": true,
      "connection_status": "connected",
      "last_sync_at": "2025-01-18T10:00:00Z",
      "error_message": null
    }
  ]
}
```

#### 4.2 Get Bookings from OTAs

**Endpoint:** `GET /api/v1/bookings?channel=booking_com`

**Purpose:** Display bookings that came from OTAs

**Query Parameters:**
- `channel` - Filter by channel (e.g., "booking_com", "expedia")
- `status` - Filter by status (e.g., "confirmed", "cancelled")
- `arrival_date_from` - Filter by arrival date
- `arrival_date_to` - Filter by arrival date

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "booking_number": "BK-20250118-ABCD",
      "confirmation_code": "1234",
      "guest_id": 1,
      "room_type_id": 1,
      "arrival_date": "2025-01-20",
      "departure_date": "2025-01-22",
      "status": "confirmed",
      "channel": "Booking.com",
      "booking_source": "booking_com",
      "total_price": 300.00,
      "commission_rate": 15.0,
      "commission_amount": 45.00,
      "net_revenue": 255.00
    }
  ]
}
```

#### 4.3 Get Availability Grid

**Endpoint:** `GET /api/v1/inventory/availability-grid`

**Purpose:** Display availability grid for channel manager

**Query Parameters:**
- `room_type_id` - Filter by room type
- `start_date` - Start date for grid
- `end_date` - End date for grid
- `ota_connection_id` - Filter by OTA connection

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "room_type_id": 1,
      "grid_date": "2025-01-20",
      "total_inventory": 20,
      "sold": 5,
      "blocked": 2,
      "available": 13,
      "stop_sell_flag": false,
      "cta_flag": false,
      "ctd_flag": false,
      "min_stay": null,
      "max_stay": null
    }
  ]
}
```

#### 4.4 Get Sync Logs

**Endpoint:** `GET /api/v1/channel-manager/sync-logs`

**Purpose:** Display sync history and status

**Query Parameters:**
- `ota_connection_id` - Filter by OTA connection
- `sync_type` - Filter by sync type (e.g., "full", "bookings", "rates")
- `status` - Filter by status (e.g., "success", "failed")
- `limit` - Number of records to return

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "ota_connection_id": 1,
      "sync_type": "bookings",
      "sync_direction": "pull",
      "status": "success",
      "records_processed": 10,
      "records_failed": 0,
      "completed_at": "2025-01-18T10:00:00Z",
      "duration_seconds": 2.5
    }
  ]
}
```

### Step 5: Frontend UI Components

The frontend should implement the following components:

#### 5.1 Channel Manager Dashboard

**Displays:**
- List of OTA connections with status indicators
- Connection health (connected/disconnected/error)
- Last sync time
- Quick stats (total bookings, revenue, etc.)

**Updates:**
- Real-time status updates via SSE `sync.status` events
- Connection status changes

#### 5.2 Bookings List

**Displays:**
- All bookings from OTAs
- Booking details (guest, dates, room, pricing)
- Channel/source indicator
- Commission and net revenue

**Updates:**
- New bookings via SSE `booking.created` events
- Modified bookings via SSE `booking.modified` events
- Cancelled bookings via SSE `booking.cancelled` events

**Actions:**
- Filter by channel, status, date range
- View booking details
- Export bookings

#### 5.3 Availability Grid

**Displays:**
- Calendar view of availability
- Room types as rows, dates as columns
- Available/sold/blocked counts
- Restrictions (stop sell, CTA, CTD, min/max stay)

**Updates:**
- Real-time updates via SSE `availability.updated` events
- Manual refresh button

**Actions:**
- Filter by room type, date range
- View restrictions
- Export availability

#### 5.4 Rates Display

**Displays:**
- Rates by room type and date
- Rate plans (BAR, Non-Refundable, etc.)
- Commission rates

**Updates:**
- Real-time updates via SSE `rates.updated` events

#### 5.5 Sync Status Panel

**Displays:**
- Current sync status for each OTA
- Sync history/logs
- Last sync time
- Error messages (if any)

**Updates:**
- Real-time updates via SSE `sync.status` events

**Actions:**
- Manual sync trigger (if backend supports it)
- View detailed sync logs

### Step 6: Real-Time Updates Handling

The frontend must handle all SSE event types:

#### 6.1 Booking Events

**`booking.created`:**
```typescript
{
  "type": "booking.created",
  "data": {
    "booking_id": 1,
    "booking_number": "BK-20250118-ABCD",
    "confirmation_code": "1234",
    "guest_id": 1,
    "room_type_id": 1,
    "arrival_date": "2025-01-20",
    "departure_date": "2025-01-22",
    "status": "confirmed",
    "channel": "Booking.com"
  },
  "timestamp": "2025-01-18T10:00:00Z"
}
```

**Action:** Add new booking to bookings list, show notification

**`booking.modified`:**
```typescript
{
  "type": "booking.modified",
  "data": {
    "booking_id": 1,
    "booking_number": "BK-20250118-ABCD",
    "changes": {
      "departure_date": "2025-01-23"
    }
  },
  "timestamp": "2025-01-18T11:00:00Z"
}
```

**Action:** Update existing booking in list, highlight changes

**`booking.cancelled`:**
```typescript
{
  "type": "booking.cancelled",
  "data": {
    "booking_id": 1,
    "booking_number": "BK-20250118-ABCD",
    "reason": "Guest requested cancellation"
  },
  "timestamp": "2025-01-18T12:00:00Z"
}
```

**Action:** Mark booking as cancelled, remove from active list, show notification

#### 6.2 Availability Events

**`availability.updated`:**
```typescript
{
  "type": "availability.updated",
  "data": {
    "updated_count": 6,
    "ota_connection_id": 1
  },
  "timestamp": "2025-01-18T10:00:00Z"
}
```

**Action:** Refresh availability grid data

#### 6.3 Rates Events

**`rates.updated`:**
```typescript
{
  "type": "rates.updated",
  "data": {
    "updated_count": 10,
    "ota_connection_id": 1
  },
  "timestamp": "2025-01-18T10:00:00Z"
}
```

**Action:** Refresh rates display

#### 6.4 Sync Status Events

**`sync.status`:**
```typescript
{
  "type": "sync.status",
  "data": {
    "ota_connection_id": 1,
    "status": {
      "connection_status": "connected",
      "last_sync_at": "2025-01-18T10:00:00Z",
      "sync_type": "full",
      "records_processed": 150,
      "records_failed": 0,
      "error_message": null
    }
  },
  "timestamp": "2025-01-18T10:00:00Z"
}
```

**Action:** Update connection status indicator, update last sync time, show sync progress

## Testing the Integration

### Test 1: Create Booking from Dummy Channel Manager

1. **Create reservation in dummy channel manager:**
   ```http
   POST http://localhost:8001/api/v2/reservations
   Content-Type: application/json

   {
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
     }
   }
   ```

2. **Expected Results:**
   - Dummy channel manager sends `booking.created` webhook to backend
   - Backend creates booking in database
   - Backend broadcasts SSE event
   - Frontend receives SSE event and updates UI

### Test 2: Modify Booking

1. **Modify reservation:**
   ```http
   PUT http://localhost:8001/api/reservations/{reservation_id}
   Content-Type: application/json

   {
     "check_out": "2025-01-23"
   }
   ```

2. **Expected Results:**
   - Dummy channel manager sends `booking.modified` webhook
   - Backend updates booking
   - Frontend receives SSE event and updates booking in list

### Test 3: Cancel Booking

1. **Cancel reservation:**
   ```http
   DELETE http://localhost:8001/api/reservations/{reservation_id}
   ```

2. **Expected Results:**
   - Dummy channel manager sends `booking.cancelled` webhook
   - Backend marks booking as cancelled
   - Frontend receives SSE event and removes/updates booking

### Test 4: Availability Update

1. **Trigger availability webhook:**
   ```http
   POST http://localhost:8001/api/webhooks/trigger/availability?ota_connection_id=1
   ```

2. **Expected Results:**
   - Dummy channel manager sends `availability.updated` webhook
   - Backend updates availability grid
   - Frontend receives SSE event and refreshes availability display

### Test 5: Sync Status Update

1. **Trigger sync status webhook:**
   ```http
   POST http://localhost:8001/api/webhooks/trigger/sync-status?ota_connection_id=1&connection_status=connected&sync_type=full&records_processed=150&records_failed=0
   ```

2. **Expected Results:**
   - Dummy channel manager sends `sync.status` webhook
   - Backend updates connection status
   - Frontend receives SSE event and updates status indicator

## Error Handling

### SSE Connection Errors

**Issue:** SSE connection fails or disconnects

**Solution:**
- Implement automatic reconnection with exponential backoff
- Show connection status indicator in UI
- Queue events if connection is down (optional)

**Example:**
```typescript
let reconnectDelay = 1000;
const maxReconnectDelay = 30000;

async function connectWithRetry() {
  try {
    await connectSSE();
    reconnectDelay = 1000; // Reset on success
  } catch (error) {
    console.error('SSE connection failed, retrying...', error);
    setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
      connectWithRetry();
    }, reconnectDelay);
  }
}
```

### Webhook Processing Errors

**Issue:** Backend returns error when processing webhook

**Solution:**
- Backend logs errors and returns appropriate HTTP status
- Frontend doesn't need to handle webhook errors directly (webhooks are backend-to-backend)
- Frontend should handle SSE event errors gracefully

### Missing Mappings

**Issue:** Room type or rate plan mapping not found

**Solution:**
- Backend returns 404 error with clear message
- Frontend should display error message if booking creation fails
- Ensure mappings are created before testing

## Data Mapping Requirements

### Room Type Mapping

The dummy channel manager uses room codes like `ROOM_1`, `ROOM_2`, etc. These must be mapped to PMS `room_type_id` values.

**Mapping Table:** `ota_room_mappings`

**Example:**
- `ROOM_1` → `room_type_id: 1` (Standard King)
- `ROOM_2` → `room_type_id: 2` (Deluxe Suite)

### Rate Plan Mapping

The dummy channel manager uses rate codes like `BAR`, `NON_REFUNDABLE`, etc. These must be mapped to PMS `rate_plan_id` values.

**Mapping Table:** `ota_rate_mappings`

**Example:**
- `BAR` → `rate_plan_id: 1` (Best Available Rate)
- `NON_REFUNDABLE` → `rate_plan_id: 2` (Non-Refundable)

### External Booking ID Mapping

The dummy channel manager uses confirmation numbers like `HRS-2024-A1B2C3` as external booking IDs. These are stored in the `Booking.internal_notes` field as JSON.

**Format:**
```json
{
  "external_booking_id": "HRS-2024-A1B2C3",
  "ota_connection_id": 1,
  "ota_code": "BOOKING",
  "source": "channel_manager_webhook"
}
```

## Performance Considerations

### SSE Connection Management

- Limit number of concurrent SSE connections per user
- Implement connection pooling if multiple components need SSE
- Use a single SSE connection and route events internally

### Data Refresh Strategy

- Use SSE for real-time updates (push)
- Use API calls for initial data load and manual refresh (pull)
- Implement debouncing for rapid SSE events
- Cache data locally to reduce API calls

### UI Update Optimization

- Batch multiple SSE events before updating UI
- Use virtual scrolling for large booking lists
- Implement pagination for bookings and sync logs
- Lazy load availability grid data

## Security Considerations

### Authentication

- SSE endpoint requires authentication (Bearer token)
- All API endpoints require authentication
- Implement token refresh for long-lived SSE connections

### Authorization

- Verify user has permission to view channel manager data
- Filter data based on user's property access
- Implement role-based access control (RBAC)

### Webhook Security

- Validate webhook signatures (if implemented)
- Rate limit webhook endpoints
- Implement idempotency keys for duplicate prevention

## Troubleshooting

### Issue: SSE Not Receiving Events

**Check:**
1. SSE connection is established (check browser network tab)
2. Backend is broadcasting events (check backend logs)
3. Authentication token is valid
4. No CORS issues

**Solution:**
- Check browser console for errors
- Verify SSE endpoint returns 200 status
- Check backend logs for `[SSE]` messages

### Issue: Bookings Not Appearing

**Check:**
1. Webhook is being sent from dummy channel manager
2. Backend is receiving webhook (check backend logs)
3. Room type and rate mappings exist
4. Booking is being created in database

**Solution:**
- Check dummy channel manager logs for webhook delivery
- Check backend logs for webhook processing
- Verify database has booking record
- Check mappings in database

### Issue: Availability Not Updating

**Check:**
1. Availability webhook is being sent
2. Backend is processing webhook
3. Availability grid is being updated in database
4. Frontend is refreshing data

**Solution:**
- Manually trigger availability webhook
- Check availability grid table in database
- Verify frontend is calling refresh API after SSE event

## Summary

This integration enables the frontend to:

1. **Display** channel manager data (bookings, availability, rates, sync status)
2. **Receive** real-time updates via SSE when webhooks are processed
3. **Interact** with channel manager data through API calls
4. **Monitor** OTA connection health and sync status

The key to a successful integration is:

- ✅ Proper database setup (OTA connections, mappings)
- ✅ SSE connection established and maintained
- ✅ All SSE event types handled in frontend
- ✅ API endpoints called for initial data load
- ✅ Error handling and reconnection logic
- ✅ UI components that update in real-time

## Next Steps

1. **Implement SSE connection** in frontend
2. **Create UI components** for channel manager dashboard
3. **Integrate API calls** for data fetching
4. **Handle SSE events** to update UI in real-time
5. **Test integration** with dummy channel manager
6. **Add error handling** and reconnection logic
7. **Optimize performance** with caching and batching

## Additional Resources

- **Webhook Specification:** See `CHANNEL_MANAGER_WEBHOOKS.md`
- **Testing Guide:** See `CHANNEL_MANAGER_TESTING_GUIDE.md`
- **SSE Integration:** See `FRONTEND_SSE_INTEGRATION.md`
- **Implementation Summary:** See `IMPLEMENTATION_SUMMARY.md`

---

**Last Updated:** January 18, 2025
**Version:** 1.0.0
