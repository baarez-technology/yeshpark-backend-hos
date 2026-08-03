# Channel Manager Quick Reference

## Overview
This is a quick reference guide for implementing the Channel Manager service. For detailed instructions, see `CHANNEL_MANAGER_IMPLEMENTATION_GUIDE.md`.

---

## 7 Tabs to Implement

1. **Dashboard** - Stats, insights, OTA performance
2. **OTA Connections** - Connect/disconnect/manage OTAs
3. **Room Mapping** - Map PMS rooms to OTA rooms
4. **Rate Sync** - Push/pull rates, manage calendar
5. **Restrictions** - CTA, CTD, Stop Sell, Min/Max Stay
6. **Promotions** - OTA-specific promotions
7. **Sync Logs** - Activity logs and monitoring

---

## Required API Endpoints

### Base URLs
- Channel Manager: `http://localhost:3001/api/v1/channel-manager`
- Glimmora Backend (Proxy): `http://localhost:3000/api/v1/channel-manager`

### Endpoint Groups

#### OTA Connections (`/otas`)
- `GET /otas` - List all
- `GET /otas/:id` - Get one
- `POST /otas` - Create/Connect
- `PUT /otas/:id` - Update
- `DELETE /otas/:id` - Disconnect
- `POST /otas/:id/test` - Test connection
- `POST /otas/:id/sync` - Manual sync
- `POST /otas/sync/all` - Sync all

#### Room Mappings (`/room-mappings`)
- `GET /room-mappings` - List all
- `POST /room-mappings` - Create
- `PUT /room-mappings/:id` - Update
- `DELETE /room-mappings/:id` - Delete
- `POST /room-mappings/auto-map` - Auto-map
- `POST /room-mappings/validate` - Validate

#### Rate Sync (`/rates`)
- `GET /rates/calendar` - Get calendar
- `PUT /rates/calendar/:date/:roomType` - Update rate
- `POST /rates/push` - Push to OTAs
- `POST /rates/pull` - Pull from OTAs
- `GET /rates/parity` - Check parity

#### Restrictions (`/restrictions`)
- `GET /restrictions` - List all
- `POST /restrictions` - Create
- `PUT /restrictions/:id` - Update
- `DELETE /restrictions/:id` - Delete
- `PUT /restrictions/:id/toggle` - Toggle active

#### Promotions (`/promotions`)
- `GET /promotions` - List all
- `POST /promotions` - Create
- `PUT /promotions/:id` - Update
- `DELETE /promotions/:id` - Delete
- `PUT /promotions/:id/toggle` - Toggle active
- `POST /promotions/:id/apply` - Apply to OTAs

#### Sync Logs (`/sync-logs`)
- `GET /sync-logs` - List (with filters)
- `GET /sync-logs/:id` - Get one
- `DELETE /sync-logs` - Clear all
- `GET /sync-logs/export` - Export CSV

#### Stats (`/stats`)
- `GET /stats` - Channel statistics
- `GET /stats/insights` - AI insights

---

## Webhook Events (Channel Manager → Glimmora Backend)

Send to: `POST {GLIMMORA_BACKEND_URL}/api/v1/webhooks/channel-manager`

### Events:
1. `ota.connection.status_changed`
2. `rates.updated`
3. `availability.updated`
4. `restrictions.updated`
5. `sync.status`
6. `booking.imported`

---

## Key Data Models

### OTA Connection
```typescript
{
  id: string;
  name: string;
  code: string;
  status: 'connected' | 'disconnected' | 'error' | 'syncing';
  credentials: { username, apiKey, hotelId };
  syncSettings: { autoSync, syncInterval, syncRates, ... };
  stats: { totalBookings, revenue, avgRating, commission };
}
```

### Room Mapping
```typescript
{
  pmsRoomType: string;
  pmsRoomTypeId: string;
  otaMappings: [{ otaCode, otaRoomType, otaRoomId, status }];
}
```

### Rate Calendar Entry
```typescript
{
  date: "YYYY-MM-DD";
  roomType: string;
  rates: { BAR: number };
  otaRates: { [otaCode]: number };
  availability: number;
  stopSell: boolean;
  cta: boolean;
  ctd: boolean;
}
```

### Restriction
```typescript
{
  roomType: string | "ALL";
  otaCode: string | "ALL";
  dateRange: { start, end };
  restriction: { minStay, maxStay, cta, ctd, stopSell };
  isActive: boolean;
}
```

### Promotion
```typescript
{
  name: string;
  discountType: 'percentage' | 'fixed';
  discountValue: number;
  validFrom: string;
  validTo: string;
  otaCodes: string[];
  roomTypes: string[];
  isActive: boolean;
}
```

### Sync Log
```typescript
{
  timestamp: string;
  otaCode: string;
  action: 'rate_update' | 'availability_update' | ...;
  status: 'success' | 'error' | 'warning';
  message: string;
}
```

---

## Implementation Steps

### Channel Manager Project:
1. Create Express/Node.js project
2. Implement data storage (in-memory or DB)
3. Create services for each feature
4. Create API routes
5. Implement webhook sender
6. Add auto-sync scheduler
7. Initialize with sample data

### Glimmora Backend Project:
1. Create proxy routes
2. Create controller (proxy to Channel Manager)
3. Create webhook handler
4. Forward webhooks to SSE
5. Add environment variables

---

## Environment Variables

### Channel Manager:
```env
PORT=3001
GLIMMORA_BACKEND_URL=http://localhost:3000
WEBHOOK_SECRET=your-secret
API_KEY=your-api-key
```

### Glimmora Backend:
```env
CHANNEL_MANAGER_URL=http://localhost:3001/api/v1/channel-manager
CHANNEL_MANAGER_API_KEY=your-api-key
WEBHOOK_SECRET=your-secret
```

---

## Sample Data Sources

Reference these files in the frontend for sample data structure:
- `src/data/channel-manager/sampleOTAs.ts`
- `src/data/channel-manager/sampleRoomMappings.ts`
- `src/data/channel-manager/sampleRestrictions.ts`
- `src/data/channel-manager/sampleSyncLogs.ts`

---

## Questions?

See the full guide: `CHANNEL_MANAGER_IMPLEMENTATION_GUIDE.md`
