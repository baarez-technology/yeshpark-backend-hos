# Frontend Channel Manager Implementation Guide

This guide details the exact API endpoints, data models, and real-time event handling required to connect the Glimmora Frontend to the Channel Manager functionality.

## 1. Authentication

All requests (API and SSE) require the `Authorization: Bearer <token>` header.

## 2. Real-Time Updates (SSE)

The Channel Manager relies heavily on Server-Sent Events (SSE) to update the UI without refreshing.

**Endpoint:** `GET /api/v1/webhooks/channel-manager/sse`

### Connection Logic (React Example)

You MUST use the **Fetch API** (not `EventSource`) to support the Authorization header.

```typescript
// hooks/useChannelManagerEvents.ts

import { useEffect, useRef } from 'react';

export const useChannelManagerEvents = (onEvent: (type: string, data: any) => void) => {
  const abortController = useRef<AbortController | null>(null);

  useEffect(() => {
    const connect = async () => {
      const token = localStorage.getItem('access_token'); 
      if (!token) return;

      abortController.current = new AbortController();

      try {
        const response = await fetch('http://localhost:8000/api/v1/webhooks/channel-manager/sse', {
          headers: {
            'Authorization': `Bearer ${token}`,
            'Accept': 'text/event-stream',
          },
          signal: abortController.current.signal,
        });

        if (!response.ok) throw new Error('SSE Connection failed');

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        
        while (reader) {
          const { done, value } = await reader.read();
          if (done) break;
          
          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');
          
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const event = JSON.parse(line.slice(6));
                onEvent(event.type, event.data);
              } catch (e) {
                console.error('Parse error', e);
              }
            }
          }
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          console.error('SSE Error', error);
          // Implement retry logic here (e.g. setTimeout(connect, 5000))
        }
      }
    };

    connect();

    return () => abortController.current?.abort();
  }, []);
};
```

### Event Types to Handle

| Event Type | Trigger | Required Action |
|------------|---------|-----------------|
| `rates.updated` | Rates changed (from OTA or internal) | Refresh Rate Calendar |
| `availability.updated` | Avail/Restr changed | Refresh Availability Grid |
| `booking.created` | New booking from OTA | Add to Booking List |
| `booking.modified` | Booking changed | Update Booking List |
| `booking.cancelled` | Booking cancelled | Update Booking List |
| `sync.status` | Sync job finished | Update Connection Status |

---

## 3. API Endpoints & Implementation by Tab

### Tab 1: Dashboard

**Goal:** Show high-level stats and channel health.

*   **GET** `/api/v1/channel-manager/stats`
    *   Returns: `{ connectedOTAs: 1, totalBookings: 150, revenue: 5000.00, ... }`
*   **GET** `/api/v1/channel-manager/sync-logs?limit=5`
    *   Returns recent activity for the activity feed.

### Tab 2: OTA Connections

**Goal:** List connected channels and manage them.

*   **GET** `/api/v1/channel-manager/otas`
    *   Returns list of OTAs: `[{ id: "1", code: "DUMMY", status: "connected", ... }]`
*   **POST** `/api/v1/channel-manager/otas`
    *   Body: `{ code: "BOOKING_COM", hotel_id: "...", api_key: "..." }`
    *   Connect a new OTA.
*   **POST** `/api/v1/channel-manager/otas/{id}/sync`
    *   Trigger a manual sync for a specific OTA.
*   **DELETE** `/api/v1/channel-manager/otas/{id}`
    *   Disconnect an OTA.

### Tab 3: Room Mapping

**Goal:** Map Glimmora Room Types to OTA Room Codes.

*   **GET** `/api/v1/channel-manager/room-mappings`
    *   Returns mappings: `[{ pms_room_type_id: 1, ota_mappings: [{ ota_code: "DUMMY", ota_room_id: "ROOM_1" }] }]`
*   **POST** `/api/v1/channel-manager/room-mappings`
    *   Create a new mapping manually.
*   **POST** `/api/v1/channel-manager/room-mappings/auto-map`
    *   Trigger auto-discovery and mapping of rooms (Useful for initialization).

### Tab 4: Rate Sync

**Goal:** View and manage rates distributed to channels.

*   **GET** `/api/v1/channel-manager/rates/calendar?start_date=...&end_date=...`
    *   Returns rate grid.
*   **POST** `/api/v1/channel-manager/rates/push`
    *   Body: `{ room_type_id: 1, date_from: "...", date_to: "...", amount: 150.00 }`
    *   Push a manual rate update to connected OTAs.

### Tab 5: Restrictions

**Goal:** Manage Stop Sells, CTAs, Minimum Stay.

*   **GET** `/api/v1/channel-manager/restrictions`
    *   List current active restrictions.
*   **POST** `/api/v1/channel-manager/restrictions`
    *   Body: `{ room_type_id: 1, date_from: "...", date_to: "...", restriction_type: "stop_sell", value: 1 }`
    *   Apply a restriction.
*   **DELETE** `/api/v1/channel-manager/restrictions/{id}`
    *   Remove a restriction.

### Tab 6: Promotions

*   *Note: This feature is simulated via Rate updates currently. Use Rate Sync tab for manual price adjustments.*

### Tab 7: Sync Logs

**Goal:** Debugging and audit trail.

*   **GET** `/api/v1/channel-manager/sync-logs?limit=50&offset=0`
    *   Full usage history. supports filtering by `status` (success/error).

---

## 4. Testing the Integration (Frontend Developer Checklist)

Use the functioning `Dummy Channel Manager` to verify your frontend.

1.  **Connect Dummy CM:**
    *   Go to OTA Connections tab.
    *   If "Dummy Channel Manager" is not listed/connected, click "Add Connection" or use the `POST /otas` endpoint with code `DUMMY`. It should auto-connect.
2.  **Verify Real-time Rates:**
    *   Open your Frontend Rate Calendar.
    *   Open a separate terminal.
    *   Run default rate update script (or use the Dummy CM API directly).
    *   **Verify:** Did the rate change on your screen instantly without refresh?
3.  **Verify Booking Import:**
    *   Trigger a simulated booking import (via Dummy CM API `POST /api/bookings/import`).
    *   **Verify:** Did the booking appear in your Booking List instantly?

## 5. Type Definitions (Reference)

```typescript
interface OTAConnection {
  id: string;
  code: string; // 'DUMMY', 'BOOKING_COM', 'EXPEDIA'
  name: string;
  status: 'connected' | 'disconnected' | 'error';
  last_sync: string; // ISO Date
}

interface RoomMapping {
  pms_room_type_id: number;
  pms_room_name: string;
  ota_mappings: {
    ota_code: string;
    ota_room_id: string;
    status: 'active' | 'inactive';
  }[];
}

interface SyncLog {
  id: string;
  timestamp: string;
  action: string;
  status: 'success' | 'error';
  message: string;
}
```
