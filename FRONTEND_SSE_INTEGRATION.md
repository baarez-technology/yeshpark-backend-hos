# Frontend SSE Integration Guide

This document provides details on integrating Server-Side Events (SSE) for real-time channel manager updates in the frontend application.

## Overview

The glimmora-backend now provides SSE endpoints that push real-time updates to the frontend when channel manager webhooks are processed. This allows the frontend to update the UI immediately when:
- New bookings are created from OTAs
- Bookings are modified
- Bookings are cancelled
- Availability is updated
- Rates are updated
- Restrictions are updated
- Sync status changes

## SSE Endpoint

**Endpoint:** `GET /api/v1/webhooks/channel-manager/sse`

**Authentication:** Required (uses `get_current_user` dependency)

**Response Type:** `text/event-stream`

**Headers:**
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`

## Connection Setup

**Important:** The SSE endpoint requires authentication via `Authorization: Bearer <token>` header. Since the native `EventSource` API doesn't support custom headers, you **must** use the Fetch API approach for authentication.

### Using Fetch API (Recommended - Supports Authentication)

```typescript
// Initialize SSE connection with authentication
let abortController: AbortController | null = null;
let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

async function connectSSE() {
  const token = localStorage.getItem('access_token'); // Or your auth token storage
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
        // Authentication failed - redirect to login
        console.error('SSE authentication failed');
        // Handle re-authentication
        return;
      }
      throw new Error(`SSE connection failed: ${response.status}`);
    }

    reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) {
      throw new Error('Response body is not readable');
    }

    // Process initial connection message
    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        console.log('SSE connection closed');
        // Implement reconnection logic
        setTimeout(connectSSE, 5000);
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // Keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            
            // Handle initial connection message
            if (data.type === 'connected') {
              console.log('SSE connected:', data.message);
              continue;
            }
            
            // Handle keepalive
            if (line.trim() === ': keepalive') {
              continue;
            }
            
            // Handle regular events
            handleSSEEvent(data);
          } catch (e) {
            console.error('Error parsing SSE data:', e);
          }
        } else if (line.trim() === ': keepalive') {
          // Keepalive ping - ignore
          continue;
        }
      }
    }
  } catch (error: any) {
    if (error.name === 'AbortError') {
      console.log('SSE connection aborted');
      return;
    }
    console.error('SSE connection error:', error);
    // Implement reconnection logic with exponential backoff
    setTimeout(connectSSE, 5000);
  }
}

function disconnectSSE() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
  if (reader) {
    reader.cancel();
    reader = null;
  }
}

function handleSSEEvent(data: any) {
  switch (data.type) {
    case 'booking.created':
      handleBookingCreated(data.data);
      break;
    case 'booking.modified':
      handleBookingModified(data.data);
      break;
    case 'booking.cancelled':
      handleBookingCancelled(data.data);
      break;
    case 'availability.updated':
      handleAvailabilityUpdated(data.data);
      break;
    case 'rates.updated':
      handleRatesUpdated(data.data);
      break;
    case 'restrictions.updated':
      handleRestrictionsUpdated(data.data);
      break;
    case 'sync.status':
      handleSyncStatus(data.data);
      break;
    default:
      console.log('Unknown SSE event type:', data.type);
  }
}

// Clean up on component unmount
function disconnectSSE() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}
```

### React Hook Implementation (Using Fetch API)

```typescript
import { useEffect, useRef, useCallback } from 'react';

interface SSEEvent {
  type: string;
  data: any;
  timestamp: string;
}

export function useChannelManagerSSE(
  onEvent: (event: SSEEvent) => void,
  enabled: boolean = true
) {
  const abortControllerRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayRef = useRef<number>(1000);

  const connect = useCallback(async () => {
    if (!enabled) return;

    const token = getAuthToken(); // Your auth token getter
    if (!token) {
      console.error('No auth token available for SSE');
      return;
    }

    const url = `${API_BASE_URL}/api/v1/webhooks/channel-manager/sse`;
    
    // Clean up previous connection
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    if (readerRef.current) {
      await readerRef.current.cancel();
    }

    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'text/event-stream',
        },
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        if (response.status === 401) {
          console.error('SSE authentication failed');
          // Handle re-authentication
          return;
        }
        throw new Error(`SSE connection failed: ${response.status}`);
      }

      readerRef.current = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!readerRef.current) {
        throw new Error('Response body is not readable');
      }

      let buffer = '';
      reconnectDelayRef.current = 1000; // Reset delay on successful connection

      while (true) {
        const { done, value } = await readerRef.current.read();
        
        if (done) {
          console.log('SSE connection closed');
          // Reconnect with exponential backoff
          reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 60000);
          reconnectTimeoutRef.current = setTimeout(connect, reconnectDelayRef.current);
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data: SSEEvent = JSON.parse(line.slice(6));
              
              // Skip connection message
              if (data.type === 'connected') {
                console.log('SSE connected');
                continue;
              }
              
              onEvent(data);
            } catch (error) {
              console.error('Error parsing SSE event:', error);
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === 'AbortError') {
        console.log('SSE connection aborted');
        return;
      }
      console.error('SSE connection error:', error);
      // Reconnect with exponential backoff
      reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 60000);
      reconnectTimeoutRef.current = setTimeout(connect, reconnectDelayRef.current);
    }
  }, [enabled, onEvent]);

  useEffect(() => {
    if (enabled) {
      connect();
    }

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (readerRef.current) {
        readerRef.current.cancel();
      }
    };
  }, [enabled, connect]);
}

// Usage in component
function BookingsPage() {
  const handleSSEEvent = (event: SSEEvent) => {
    switch (event.type) {
      case 'booking.created':
        // Refresh bookings list or add new booking to UI
        refetchBookings();
        showNotification('New booking received from channel manager');
        break;
      case 'booking.modified':
        // Update specific booking in UI
        updateBookingInList(event.data.booking_id, event.data.changes);
        break;
      case 'booking.cancelled':
        // Remove or mark booking as cancelled in UI
        removeBookingFromList(event.data.booking_id);
        break;
    }
  };

  useChannelManagerSSE(handleSSEEvent, true);

  return (
    // Your component JSX
  );
}
```

### Alternative: Using EventSource with Proxy (If Query Params Supported)

**Note:** The current backend implementation requires `Authorization` header. If you need to use EventSource, you would need to:
1. Create a proxy endpoint that accepts token as query param, OR
2. Modify the backend to support token in query parameters

For now, use the Fetch API approach shown above.

## Event Types and Data Formats

### 1. booking.created

**Event Type:** `booking.created`

**Data Structure:**
```json
{
  "type": "booking.created",
  "data": {
    "booking_id": 123,
    "booking_number": "BK-20240115-A1B2",
    "confirmation_code": "CONF123",
    "guest_id": 45,
    "room_type_id": 5,
    "arrival_date": "2024-02-01",
    "departure_date": "2024-02-05",
    "status": "confirmed",
    "channel": "Booking.com"
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Frontend Actions:**
- Add new booking to bookings list
- Show notification: "New booking from {channel}"
- Refresh bookings calendar view
- Update availability grid
- Update revenue dashboard

### 2. booking.modified

**Event Type:** `booking.modified`

**Data Structure:**
```json
{
  "type": "booking.modified",
  "data": {
    "booking_id": 123,
    "booking_number": "BK-20240115-A1B2",
    "changes": {
      "arrival_date": "2024-02-02",
      "departure_date": "2024-02-06",
      "adults": 3,
      "total_price": 389.88
    }
  },
  "timestamp": "2024-01-20T14:00:00Z"
}
```

**Frontend Actions:**
- Update booking details in bookings list
- Show notification: "Booking {booking_number} modified"
- Refresh calendar view if dates changed
- Update availability grid for old/new dates

### 3. booking.cancelled

**Event Type:** `booking.cancelled`

**Data Structure:**
```json
{
  "type": "booking.cancelled",
  "data": {
    "booking_id": 123,
    "booking_number": "BK-20240115-A1B2",
    "reason": "Guest requested cancellation"
  },
  "timestamp": "2024-01-25T09:00:00Z"
}
```

**Frontend Actions:**
- Remove booking from active list or mark as cancelled
- Show notification: "Booking {booking_number} cancelled"
- Refresh availability grid (increment available rooms)
- Update revenue dashboard

### 4. availability.updated

**Event Type:** `availability.updated`

**Data Structure:**
```json
{
  "type": "availability.updated",
  "data": {
    "updated_count": 3,
    "ota_connection_id": 1
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Frontend Actions:**
- Refresh availability grid view
- Show notification: "Availability updated from channel manager"
- Update room availability calendar

### 5. rates.updated

**Event Type:** `rates.updated`

**Data Structure:**
```json
{
  "type": "rates.updated",
  "data": {
    "updated_count": 10,
    "ota_connection_id": 1
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Frontend Actions:**
- Refresh rate grid view
- Show notification: "Rates updated from channel manager"
- Update pricing calendar

### 6. restrictions.updated

**Event Type:** `restrictions.updated`

**Data Structure:**
```json
{
  "type": "restrictions.updated",
  "data": {
    "updated_count": 5,
    "ota_connection_id": 1
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Frontend Actions:**
- Refresh availability grid with new restrictions
- Update restriction flags (CTA, CTD, Stop Sell, Min/Max Stay)
- Show notification: "Restrictions updated from channel manager"

### 7. sync.status

**Event Type:** `sync.status`

**Data Structure:**
```json
{
  "type": "sync.status",
  "data": {
    "ota_connection_id": 1,
    "status": {
      "connection_status": "connected",
      "last_sync_at": "2024-01-15T10:00:00Z",
      "sync_type": "full",
      "records_processed": 150,
      "records_failed": 0,
      "error_message": null
    }
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Note:** The `status` object structure matches the webhook payload structure. It may contain:
- `connection_status`: "connected" | "disconnected" | "error"
- `last_sync_at`: ISO 8601 timestamp string
- `sync_type`: "full" | "incremental" | "manual"
- `records_processed`: number
- `records_failed`: number
- `error_message`: string | null

**Frontend Actions:**
- Update OTA connection status indicator
- Show sync progress/status
- Display sync statistics
- Show error message if sync failed

## UI Components to Update

### 1. Bookings List/Table

**Location:** Bookings management page

**Updates:**
- Add new row when `booking.created` event received
- Update row when `booking.modified` event received
- Remove/mark cancelled when `booking.cancelled` event received
- Highlight new/modified bookings with visual indicator

**Implementation:**
```typescript
const [bookings, setBookings] = useState<Booking[]>([]);

useChannelManagerSSE((event) => {
  if (event.type === 'booking.created') {
    // Option 1: Refetch from API
    refetchBookings();
    
    // Option 2: Optimistically add to list
    setBookings(prev => [...prev, event.data]);
  } else if (event.type === 'booking.modified') {
    setBookings(prev => prev.map(b => 
      b.id === event.data.booking_id 
        ? { ...b, ...event.data.changes }
        : b
    ));
  } else if (event.type === 'booking.cancelled') {
    setBookings(prev => prev.filter(b => b.id !== event.data.booking_id));
  }
}, true);
```

### 2. Bookings Calendar View

**Location:** Calendar-based bookings view

**Updates:**
- Add new booking marker when `booking.created` event received
- Move booking marker when `booking.modified` event received (dates changed)
- Remove marker when `booking.cancelled` event received

### 3. Availability Grid

**Location:** Inventory/Availability management page

**Updates:**
- Refresh availability counts when `availability.updated` event received
- Update restriction flags when `restrictions.updated` event received
- Refresh when bookings are created/modified/cancelled

**Implementation:**
```typescript
useChannelManagerSSE((event) => {
  if (['booking.created', 'booking.modified', 'booking.cancelled', 
       'availability.updated', 'restrictions.updated'].includes(event.type)) {
    refetchAvailabilityGrid();
  }
}, true);
```

### 4. Rate Grid

**Location:** Rates/Pricing management page

**Updates:**
- Refresh rates when `rates.updated` event received

### 5. Channel Manager Status Dashboard

**Location:** Channel Manager settings/status page

**Updates:**
- Update connection status when `sync.status` event received
- Display last sync time
- Show sync statistics
- Display error messages

### 6. Revenue Dashboard

**Location:** Analytics/Revenue dashboard

**Updates:**
- Refresh when bookings are created/cancelled
- Recalculate metrics
- Update charts/graphs

## Notification System

Implement toast notifications for SSE events:

```typescript
import { toast } from 'react-toastify'; // Or your notification library

useChannelManagerSSE((event) => {
  switch (event.type) {
    case 'booking.created':
      toast.success(`New booking from ${event.data.channel}: ${event.data.booking_number}`);
      break;
    case 'booking.modified':
      toast.info(`Booking ${event.data.booking_number} has been modified`);
      break;
    case 'booking.cancelled':
      toast.warning(`Booking ${event.data.booking_number} has been cancelled`);
      break;
    case 'availability.updated':
      toast.info('Availability has been updated from channel manager');
      break;
    case 'rates.updated':
      toast.info('Rates have been updated from channel manager');
      break;
    case 'restrictions.updated':
      toast.info('Restrictions have been updated from channel manager');
      break;
    case 'sync.status':
      if (event.data.status.error_message) {
        toast.error(`Sync failed: ${event.data.status.error_message}`);
      } else {
        toast.success(`Sync completed: ${event.data.status.records_processed} records`);
      }
      break;
  }
}, true);
```

## Error Handling

### Connection Errors

```typescript
function handleSSEError(error: Event) {
  console.error('SSE connection error:', error);
  
  // Implement exponential backoff reconnection
  let reconnectDelay = 1000;
  const maxDelay = 60000; // 1 minute max
  
  const reconnect = () => {
    setTimeout(() => {
      if (eventSource?.readyState === EventSource.CLOSED) {
        connectSSE();
        reconnectDelay = Math.min(reconnectDelay * 2, maxDelay);
      }
    }, reconnectDelay);
  };
  
  reconnect();
}
```

### Authentication Errors

If SSE connection fails due to authentication:
- Redirect to login page
- Clear invalid tokens
- Show authentication error message

## Best Practices

1. **Reconnection Logic:** Always implement automatic reconnection with exponential backoff (start with 1s, max 60s)
2. **Error Boundaries:** Wrap SSE logic in error boundaries to prevent crashes
3. **Connection Management:** 
   - Close SSE connection when component unmounts or user navigates away
   - Clean up AbortController and ReadableStreamReader properly
   - Clear any reconnection timeouts
4. **Conditional Connection:** Only connect SSE when user is on relevant pages (bookings, availability, rates, etc.)
5. **Performance:** 
   - Use debouncing/throttling for rapid events
   - Batch UI updates when multiple events arrive quickly
   - Consider using requestAnimationFrame for UI updates
6. **State Management:** 
   - Consider using React Query or SWR for automatic cache invalidation on SSE events
   - Use optimistic updates with fallback to API refetch
7. **Authentication:**
   - Always check token validity before connecting
   - Handle 401 errors by redirecting to login
   - Refresh token if expired before reconnecting
8. **Error Handling:**
   - Log errors for debugging
   - Show user-friendly error messages
   - Implement retry limits to prevent infinite reconnection loops
9. **Testing:**
   - Test with network interruptions
   - Test with expired tokens
   - Test with multiple simultaneous connections
   - Test reconnection scenarios

## Testing

### Testing SSE Connection

1. **Verify Connection:**
   ```typescript
   // Check if connection is established
   // Look for "SSE connected" log message
   // Verify initial "connected" event is received
   ```

2. **Test Event Reception:**
   - Create a booking via API or webhook
   - Verify `booking.created` event is received
   - Check event data structure matches expected format

3. **Test Reconnection:**
   - Disconnect network temporarily
   - Verify reconnection logic triggers
   - Check exponential backoff is working

4. **Test Authentication:**
   - Use expired token
   - Verify 401 error is handled
   - Check re-authentication flow

### Mock SSE Server (for development/testing)

```typescript
// Mock SSE for testing without backend
function mockSSE(onMessage: (data: any) => void) {
  // Simulate initial connection
  setTimeout(() => {
    onMessage({
      type: 'connected',
      message: 'SSE connection established',
      timestamp: new Date().toISOString()
    });
  }, 100);

  // Send mock events
  const eventTypes = [
    'booking.created',
    'booking.modified',
    'booking.cancelled',
    'availability.updated',
    'rates.updated',
    'restrictions.updated',
    'sync.status'
  ];

  setInterval(() => {
    const eventType = eventTypes[Math.floor(Math.random() * eventTypes.length)];
    onMessage({
      type: eventType,
      data: generateMockData(eventType),
      timestamp: new Date().toISOString()
    });
  }, 10000); // Send mock event every 10 seconds
}

function generateMockData(eventType: string) {
  switch (eventType) {
    case 'booking.created':
      return {
        booking_id: Math.floor(Math.random() * 1000),
        booking_number: `BK-TEST-${Date.now()}`,
        confirmation_code: `CONF-${Math.random().toString(36).substr(2, 9).toUpperCase()}`,
        guest_id: Math.floor(Math.random() * 100),
        room_type_id: Math.floor(Math.random() * 10),
        arrival_date: new Date().toISOString().split('T')[0],
        departure_date: new Date(Date.now() + 86400000).toISOString().split('T')[0],
        status: 'confirmed',
        channel: 'Test Channel'
      };
    // Add other event types...
    default:
      return { updated_count: 1, ota_connection_id: 1 };
  }
}
```

### Browser DevTools Testing

1. **Network Tab:**
   - Verify SSE connection shows as "EventStream" type
   - Check request headers include Authorization
   - Monitor connection status

2. **Console:**
   - Check for connection logs
   - Verify events are being received
   - Check for any error messages

3. **Application Tab:**
   - Verify token is stored correctly
   - Check token expiration

## API Reference

### Webhook Receiver Endpoint

**Endpoint:** `POST /api/v1/webhooks/channel-manager`

**Authentication:** Not required (webhook endpoint)

**Payload:** See `CHANNEL_MANAGER_WEBHOOKS.md` for payload formats

**Response:**
```json
{
  "success": true,
  "message": "Booking created successfully",
  "booking_id": 123,
  "booking_number": "BK-20240115-A1B2"
}
```

### SSE Endpoint

**Endpoint:** `GET /api/v1/webhooks/channel-manager/sse`

**Authentication:** Required (Bearer token)

**Authentication:**
- **Required:** `Authorization: Bearer <token>` header
- **Note:** Query parameter authentication is NOT supported. You must use the Authorization header.

**Response Format:** SSE stream with JSON data

**Initial Message:**
Upon connection, the server sends:
```json
{
  "type": "connected",
  "message": "SSE connection established"
}
```

**Keepalive:** Server sends `: keepalive\n\n` every 30 seconds to maintain connection

**Event Format:**
All events follow this structure:
```json
{
  "type": "event_type",
  "data": { /* event-specific data */ },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Troubleshooting

### Connection Issues

1. **CORS Errors:** Ensure backend CORS is configured to allow SSE connections
2. **Authentication:** 
   - Verify token is valid and not expired
   - Ensure `Authorization: Bearer <token>` header is included
   - Check that token is passed correctly (not as query parameter)
   - If getting 401, refresh token and reconnect
3. **Network:** Check firewall/proxy settings allow long-lived connections
4. **Server Timeout:** Ensure server/proxy doesn't timeout SSE connections
5. **EventSource Limitations:** Remember that native EventSource doesn't support custom headers - use Fetch API instead

### Event Not Received

1. Check browser console for errors
2. Verify SSE connection is established (check Network tab)
3. Verify webhook was received and processed by backend
4. Check backend logs for SSE broadcast errors

### Performance Issues

1. Limit number of concurrent SSE connections
2. Use connection pooling for multiple components
3. Implement event filtering on client side
4. Debounce/throttle event handlers

## Complete Example: React Component with SSE

```typescript
import React, { useEffect, useState } from 'react';
import { useChannelManagerSSE } from './hooks/useChannelManagerSSE';

interface Booking {
  id: number;
  booking_number: string;
  confirmation_code: string;
  guest_id: number;
  room_type_id: number;
  arrival_date: string;
  departure_date: string;
  status: string;
  channel: string;
}

function BookingsPage() {
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [notifications, setNotifications] = useState<string[]>([]);

  const handleSSEEvent = (event: SSEEvent) => {
    switch (event.type) {
      case 'booking.created':
        // Option 1: Optimistically add to list
        setBookings(prev => [...prev, event.data as Booking]);
        // Option 2: Refetch from API for accuracy
        // refetchBookings();
        setNotifications(prev => [
          ...prev,
          `New booking from ${event.data.channel}: ${event.data.booking_number}`
        ]);
        break;
        
      case 'booking.modified':
        setBookings(prev => prev.map(b => 
          b.id === event.data.booking_id 
            ? { ...b, ...event.data.changes }
            : b
        ));
        setNotifications(prev => [
          ...prev,
          `Booking ${event.data.booking_number} has been modified`
        ]);
        break;
        
      case 'booking.cancelled':
        setBookings(prev => prev.filter(b => b.id !== event.data.booking_id));
        setNotifications(prev => [
          ...prev,
          `Booking ${event.data.booking_number} has been cancelled`
        ]);
        break;
        
      case 'availability.updated':
        // Refresh availability grid
        refetchAvailability();
        setNotifications(prev => [
          ...prev,
          'Availability has been updated from channel manager'
        ]);
        break;
        
      case 'rates.updated':
        // Refresh rates
        refetchRates();
        setNotifications(prev => [
          ...prev,
          'Rates have been updated from channel manager'
        ]);
        break;
        
      case 'restrictions.updated':
        // Refresh restrictions
        refetchRestrictions();
        setNotifications(prev => [
          ...prev,
          'Restrictions have been updated from channel manager'
        ]);
        break;
        
      case 'sync.status':
        // Update sync status indicator
        updateSyncStatus(event.data.ota_connection_id, event.data.status);
        if (event.data.status.error_message) {
          setNotifications(prev => [
            ...prev,
            `Sync failed: ${event.data.status.error_message}`
          ]);
        } else {
          setNotifications(prev => [
            ...prev,
            `Sync completed: ${event.data.status.records_processed} records`
          ]);
        }
        break;
    }
  };

  // Connect to SSE when component mounts
  useChannelManagerSSE(handleSSEEvent, true);

  return (
    <div>
      <h1>Bookings</h1>
      {/* Your bookings UI */}
      {notifications.map((msg, idx) => (
        <div key={idx} className="notification">{msg}</div>
      ))}
    </div>
  );
}
```

## Implementation Checklist

- [ ] Use Fetch API for SSE connection (not EventSource) to support Authorization header
- [ ] Implement exponential backoff reconnection logic
- [ ] Handle authentication errors (401) by redirecting to login
- [ ] Parse initial "connected" message correctly
- [ ] Handle keepalive pings (ignore `: keepalive` lines)
- [ ] Implement proper cleanup on component unmount
- [ ] Add error boundaries around SSE logic
- [ ] Test with network interruptions
- [ ] Verify all event types are handled
- [ ] Add loading states during reconnection
- [ ] Consider using React Query or SWR for cache invalidation

## Technical Details

### SSE Protocol Implementation

The backend implements SSE according to the [Server-Sent Events specification](https://html.spec.whatwg.org/multipage/server-sent-events.html):

1. **Content-Type:** `text/event-stream`
2. **Encoding:** UTF-8
3. **Line Endings:** `\n\n` (double newline) separates events
4. **Data Format:** `data: <JSON>\n\n`
5. **Keepalive:** `: keepalive\n\n` sent every 30 seconds

### Event Structure

All events follow this consistent structure:
```typescript
interface SSEEvent {
  type: string;           // Event type identifier
  data: any;              // Event-specific payload
  timestamp: string;      // ISO 8601 timestamp (UTC)
}
```

### Connection Lifecycle

1. **Initial Connection:**
   - Client sends GET request with `Authorization: Bearer <token>` header
   - Server validates token and creates connection
   - Server sends initial "connected" message
   - Connection is added to active connections pool

2. **Event Broadcasting:**
   - Webhook is received and processed
   - `broadcast_sse_event()` is called with event type and data
   - Event is formatted and sent to all active connections
   - Each client receives the event in their stream

3. **Keepalive:**
   - Every 30 seconds, server sends `: keepalive\n\n`
   - Prevents connection timeout
   - Client should ignore keepalive messages

4. **Disconnection:**
   - Client closes connection (abort, navigation, etc.)
   - Server detects disconnection
   - Connection is removed from active pool
   - Client should implement reconnection logic

### Backend Implementation Notes

- **Connection Storage:** In-memory list (`sse_connections`)
- **Concurrency:** Each connection has its own `asyncio.Queue`
- **Error Handling:** Dead connections are automatically removed
- **Scalability:** For production, consider using Redis Pub/Sub or similar for distributed systems

### CORS Configuration

The backend CORS middleware is configured to allow all origins. For production:
- Restrict allowed origins to your frontend domain(s)
- Ensure credentials are handled correctly if using cookies

### Security Considerations

1. **Authentication:** Always required - no anonymous connections
2. **Token Validation:** Tokens are validated on each connection
3. **Rate Limiting:** Consider implementing rate limiting for SSE endpoints
4. **Connection Limits:** Monitor and limit concurrent connections per user
5. **Data Validation:** All event data is validated before broadcasting

### Performance Considerations

1. **Connection Pooling:** Limit concurrent SSE connections
2. **Event Batching:** Consider batching multiple events if needed
3. **Memory Management:** Clean up disconnected clients promptly
4. **Network:** Use compression if supported (gzip/brotli)

### Monitoring

Monitor the following metrics:
- Number of active SSE connections
- Event broadcast rate
- Connection errors
- Reconnection frequency
- Average connection duration
