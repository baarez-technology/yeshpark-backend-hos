# Channel Manager Implementation Guide

## Overview
This document provides comprehensive instructions for implementing a dummy Channel Manager service that integrates with the Glimmora Frontend and Backend API. The Channel Manager handles OTA (Online Travel Agency) connections, room mappings, rate synchronization, restrictions, promotions, and sync logging.

**IMPORTANT**: The dummy Channel Manager should appear as a **connectable OTA** in the UI (e.g., "Dummy Channel Manager" or "Test Channel Manager") and must **actually update the Glimmora backend database** (availability, rates, bookings, etc.) to make all Channel Manager tabs fully functional with real data updates.

### Key Requirements Summary

1. **Dummy Channel Manager as OTA**: Must appear in OTA Connections list with code "DUMMY"
2. **Real Data Updates**: Must call Glimmora Backend APIs to update:
   - Room availability (`PUT /api/v1/cms/availability/bulk-update`)
   - Rates (`PUT /api/v1/revenue-intelligence/rates/:roomTypeId/:date`)
   - Bookings (`POST /api/v1/bookings` for simulated imports)
3. **Functional Tabs**: All 7 tabs must work with real data from Glimmora backend
4. **Bidirectional Sync**: Read from and write to Glimmora backend
5. **Real-time Updates**: Send webhooks that trigger SSE events in frontend

---

## Table of Contents
1. [Features Overview](#features-overview)
2. [Dummy Channel Manager as Working OTA](#dummy-channel-manager-as-working-ota)
3. [Glimmora Backend API Integration](#glimmora-backend-api-integration)
4. [Data Models](#data-models)
5. [API Endpoints Specification](#api-endpoints-specification)
6. [Webhooks & SSE Events](#webhooks--sse-events)
7. [Channel Manager Project Instructions](#channel-manager-project-instructions)
8. [Glimmora Backend API Instructions](#glimmora-backend-api-instructions)
9. [Real Data Sync Implementation](#real-data-sync-implementation)
10. [Integration Flow](#integration-flow)
11. [Testing Checklist](#testing-checklist)

---

## Features Overview

### 1. Dashboard Tab
**Purpose**: Overview of channel manager status and performance

**Features**:
- KPI Cards: Connected OTAs, OTA Revenue (MTD), OTA Bookings, Avg Conversion Rate
- AI Channel Insights: Rate parity alerts, connection issues, unmapped rooms, high demand suggestions
- OTA Performance Table: Channel analytics with bookings, revenue, ratings, last sync time
- Revenue by Channel: Distribution breakdown with visual bars
- Recent Sync Activity: Latest synchronizations with status indicators

**Required Data**:
- OTA connection status and statistics
- Revenue and booking metrics per OTA
- Sync logs (last 4-5 entries)
- Channel performance metrics

---

### 2. OTA Connections Tab
**Purpose**: Manage OTA platform connections

**Features**:
- List all available OTAs (including "Dummy Channel Manager" as a connectable OTA, plus Booking.com, Expedia, Agoda, Airbnb, MakeMyTrip, Trip.com, Google Hotel Ads, etc.)
- Connect/Disconnect OTAs (including the dummy Channel Manager)
- Edit OTA credentials (username, API key, hotel ID)
- Test OTA connection
- View connection status (connected, disconnected, error, syncing)
- Configure sync settings (auto-sync, sync interval, sync types)
- View OTA statistics (bookings, revenue, ratings, commission)
- Search and filter OTAs by status
- Manual sync trigger per OTA or all OTAs

**Required Data**:
- OTA list with connection status
- OTA credentials (encrypted)
- Sync settings per OTA
- OTA statistics

---

### 3. Room Mapping Tab
**Purpose**: Map PMS room types to OTA room types

**Features**:
- View all PMS room types
- Map each PMS room type to OTA-specific room types
- Auto-mapping suggestions (AI-powered)
- Edit/Remove room mappings
- View mapping status per OTA
- Search and filter by OTA or room type
- Validate mappings before activation
- Track last sync time per mapping

**Required Data**:
- PMS room types (from Glimmora backend)
- OTA room type mappings
- Mapping status and sync history

---

### 4. Rate Sync Tab
**Purpose**: Synchronize rates and inventory across OTAs

**Features**:
- Rate calendar view (date range, room types, rates per OTA)
- Push rates to OTAs (manual or scheduled)
- Pull rates from OTAs
- View rate parity issues
- Update rates for specific dates/room types/OTAs
- Update availability (inventory) per date/room type
- Toggle stop sell, CTA, CTD per date/room type
- AI rate insights and recommendations

**Required Data**:
- Rate calendar (date × room type × OTA)
- Base rates from PMS
- OTA-specific rates
- Availability data
- Rate parity calculations

---

### 5. Restrictions Tab
**Purpose**: Manage booking restrictions (CTA, CTD, Stop Sell, Min/Max Stay)

**Features**:
- Create/Edit/Delete restrictions
- Restriction types: Min Stay, Max Stay, CTA (Close to Arrival), CTD (Close to Departure), Stop Sell
- Apply restrictions to specific room types or all rooms
- Apply restrictions to specific OTAs or all OTAs
- Date range selection for restrictions
- Reason/notes field for each restriction
- Active/Inactive toggle
- Search and filter restrictions
- View restriction statistics

**Required Data**:
- Restriction rules with date ranges
- Room type and OTA associations
- Restriction status and history

---

### 6. Promotions Tab
**Purpose**: Manage OTA-specific promotions and deals

**Features**:
- Create/Edit/Delete channel promotions
- Promotion types: Percentage discount, Fixed discount
- Apply to specific OTAs or all OTAs
- Apply to specific room types or all rooms
- Date range (valid from/to)
- Booking window restrictions
- Min stay requirements
- Track promotion usage count
- Active/Scheduled/Expired/Inactive status
- Search and filter promotions

**Required Data**:
- Promotion definitions
- OTA and room type associations
- Usage tracking
- Status and validity dates

---

### 7. Sync Logs Tab
**Purpose**: Monitor channel synchronization activity

**Features**:
- View all sync activity logs
- Filter by OTA, action type, status
- Search by message or OTA name
- View log details (drawer/modal)
- Export logs to CSV
- Real-time log updates via SSE
- Status indicators (success, error, warning, pending)
- Action type icons (rate update, availability update, restriction update, promotion sync, booking import, connection, bulk sync)

**Required Data**:
- Sync log entries with timestamps
- Action types and status
- Detailed error messages
- OTA and room type associations

---

## Dummy Channel Manager as Working OTA

### Overview
The dummy Channel Manager must appear as a **connectable OTA** in the UI and **actually update the Glimmora backend database** to make all Channel Manager tabs fully functional. It should simulate real OTA behavior while updating real data.

### Implementation Requirements

#### 1. Appear as Connectable OTA
The dummy Channel Manager should be listed in the OTA Connections tab as:

```typescript
{
  id: 'ota-dummy',
  name: 'Dummy Channel Manager',
  code: 'DUMMY',
  logo: null, // or a custom logo URL
  status: 'disconnected', // Initially disconnected
  color: '#A57865', // Use Glimmora terra color
  // ... other OTA fields
}
```

**When user clicks "Connect":**
- Validate connection (always succeed for dummy)
- Set status to 'connected'
- Fetch current data from Glimmora backend
- Initialize room mappings from Glimmora room types
- Start auto-sync scheduler

#### 2. Real Data Updates
When the dummy Channel Manager is connected and syncing, it must:

**Update Availability:**
- Read current availability from Glimmora backend
- Update availability when restrictions are applied
- Update availability when bookings are imported
- Sync availability changes back to Glimmora backend

**Update Rates:**
- Read current rates from Glimmora rate plans
- Update rates when rate sync is triggered
- Apply promotions to rates
- Sync rate changes back to Glimmora backend

**Create Bookings:**
- Simulate booking imports from the dummy OTA
- Create actual bookings in Glimmora backend
- Update availability automatically
- Track booking statistics

**Apply Restrictions:**
- Update Glimmora backend availability/restrictions
- Apply CTA, CTD, Stop Sell, Min/Max Stay
- Reflect restrictions in availability calendar

#### 3. Functional Tabs
All tabs must work with real data:

- **Dashboard**: Show real stats from Glimmora backend
- **OTA Connections**: Connect/disconnect dummy Channel Manager
- **Room Mapping**: Map real Glimmora room types
- **Rate Sync**: Update real rates in Glimmora backend
- **Restrictions**: Apply real restrictions to Glimmora backend
- **Promotions**: Apply promotions that affect real rates
- **Sync Logs**: Log real sync operations

---

## Glimmora Backend API Integration

### Required API Endpoints

The Channel Manager must call these Glimmora Backend APIs to read and update data:

#### 1. Room Types & Availability

**GET `/api/v1/room-types`**
- Fetch all room types from Glimmora
- Use for room mapping initialization
- Response: `{ items: RoomType[] }`

**GET `/api/v1/rooms/availability`**
- Get current availability for date range
- Query params: `startDate`, `endDate`, `roomTypeId?`
- Response: Availability data per date/room type

**PUT `/api/v1/cms/availability/bulk-update`**
- Update availability in bulk
- Request body: `BulkAvailabilityUpdate[]`
- Updates: `is_closed`, `min_stay`, `max_stay`, `closed_to_arrival`, `closed_to_departure`

**Example Request:**
```json
[{
  "room_type_id": "room-type-123",
  "start_date": "2025-01-20",
  "end_date": "2025-01-22",
  "is_closed": false,
  "min_stay": 2,
  "max_stay": null,
  "closed_to_arrival": false,
  "closed_to_departure": false
}]
```

#### 2. Rates & Rate Plans

**GET `/api/v1/cms/rate-plans`**
- Fetch all rate plans
- Use to get base rates per room type
- Response: `{ items: RatePlan[] }`

**PUT `/api/v1/revenue-intelligence/rates/:roomTypeId/:date`**
- Update rate for specific room type and date
- Request body: `{ rate: number, reason?: string }`
- Updates the rate in Glimmora backend

**POST `/api/v1/revenue-intelligence/rates/bulk-update`**
- Bulk update rates
- Request body: `Array<{ roomTypeId: number, date: string, rate: number }>`

**Example Request:**
```json
[
  {
    "roomTypeId": 123,
    "date": "2025-01-20",
    "rate": 220
  },
  {
    "roomTypeId": 123,
    "date": "2025-01-21",
    "rate": 225
  }
]
```

#### 3. Bookings

**GET `/api/v1/bookings`**
- Fetch bookings for statistics
- Query params: `pageSize`, `source?`, `channel?`
- Use to calculate OTA revenue and booking counts

**POST `/api/v1/bookings`**
- Create booking (for simulated booking imports)
- Request body: Booking creation data
- Must include: `roomTypeId`, `checkIn`, `checkOut`, `guests`, `source: "DUMMY"`

**Example Request:**
```json
{
  "roomTypeId": "room-type-123",
  "checkIn": "2025-01-20",
  "checkOut": "2025-01-22",
  "guests": {
    "adults": 2,
    "children": 0
  },
  "source": "DUMMY",
  "channel": "Dummy Channel Manager",
  "totalPrice": 440,
  "guest": {
    "name": "John Smith",
    "email": "john@example.com",
    "phone": "+1234567890"
  }
}
```

#### 4. Room Types (for Mapping)

**GET `/api/v1/room-types`**
- Get all room types with IDs
- Use for room mapping initialization
- Response includes: `id`, `name`, `slug`, `price`, `availableRoomCount`

### API Client Setup

The Channel Manager should use an HTTP client (axios) to call Glimmora Backend:

```typescript
import axios from 'axios';

const glimmoraClient = axios.create({
  baseURL: process.env.GLIMMORA_BACKEND_URL || 'http://localhost:3000',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${process.env.GLIMMORA_API_TOKEN}` // If auth required
  }
});
```

### Error Handling

- Handle API errors gracefully
- Retry failed requests (exponential backoff)
- Log errors to sync logs
- Fallback to cached data if API unavailable

---

## Real Data Sync Implementation

### Sync Flow

#### 1. Initial Connection
When dummy Channel Manager is connected:

```typescript
async function connectDummyChannelManager() {
  // 1. Fetch room types from Glimmora
  const roomTypes = await glimmoraClient.get('/api/v1/room-types');
  
  // 2. Initialize room mappings
  const mappings = roomTypes.data.items.map(rt => ({
    pmsRoomType: rt.name,
    pmsRoomTypeId: rt.id,
    otaMappings: [{
      otaCode: 'DUMMY',
      otaRoomType: rt.name,
      otaRoomId: `DUMMY-${rt.id}`,
      status: 'active'
    }]
  }));
  
  // 3. Fetch current rates
  const ratePlans = await glimmoraClient.get('/api/v1/cms/rate-plans');
  
  // 4. Fetch current availability
  const availability = await glimmoraClient.get('/api/v1/rooms/availability', {
    params: {
      startDate: getToday(),
      endDate: getDatePlusDays(365)
    }
  });
  
  // 5. Initialize rate calendar
  initializeRateCalendar(roomTypes, ratePlans, availability);
  
  // 6. Start auto-sync
  startAutoSync();
}
```

#### 2. Rate Sync (Push to Glimmora)
When rates are pushed:

```typescript
async function pushRatesToGlimmora(rateUpdates: RateUpdate[]) {
  // Update rates in Glimmora backend
  await glimmoraClient.post('/api/v1/revenue-intelligence/rates/bulk-update', {
    updates: rateUpdates.map(update => ({
      roomTypeId: update.roomTypeId,
      date: update.date,
      rate: update.rate
    }))
  });
  
  // Send webhook to notify Glimmora
  await sendWebhook('rates.updated', {
    otaCode: 'DUMMY',
    updates: rateUpdates
  });
}
```

#### 3. Availability Sync (Push to Glimmora)
When availability is updated:

```typescript
async function pushAvailabilityToGlimmora(availabilityUpdates: AvailabilityUpdate[]) {
  // Update availability in Glimmora backend
  await glimmoraClient.put('/api/v1/cms/availability/bulk-update', 
    availabilityUpdates.map(update => ({
      room_type_id: update.roomTypeId,
      start_date: update.date,
      end_date: update.date,
      is_closed: update.isClosed || false,
      min_stay: update.minStay || 1,
      max_stay: update.maxStay || null,
      closed_to_arrival: update.cta || false,
      closed_to_departure: update.ctd || false
    }))
  );
  
  // Send webhook
  await sendWebhook('availability.updated', {
    otaCode: 'DUMMY',
    updates: availabilityUpdates
  });
}
```

#### 4. Restriction Sync (Push to Glimmora)
When restrictions are applied:

```typescript
async function applyRestrictionToGlimmora(restriction: Restriction) {
  // Get affected dates
  const dates = getDateRange(restriction.dateRange.start, restriction.dateRange.end);
  
  // Update availability for each date
  const updates = dates.map(date => ({
    room_type_id: getRoomTypeId(restriction.roomType),
    start_date: date,
    end_date: date,
    min_stay: restriction.restriction.minStay,
    max_stay: restriction.restriction.maxStay,
    closed_to_arrival: restriction.restriction.cta,
    closed_to_departure: restriction.restriction.ctd,
    is_closed: restriction.restriction.stopSell
  }));
  
  await glimmoraClient.put('/api/v1/cms/availability/bulk-update', updates);
  
  // Send webhook
  await sendWebhook('restrictions.updated', {
    restrictionId: restriction.id,
    restriction: restriction
  });
}
```

#### 5. Booking Import (Create in Glimmora)
When simulating booking import:

```typescript
async function importBookingFromDummyOTA(bookingData: {
  roomTypeId: string;
  checkIn: string;
  checkOut: string;
  guests: { adults: number; children: number };
  guest: { name: string; email: string; phone: string };
  totalPrice: number;
}) {
  // Create booking in Glimmora backend
  const booking = await glimmoraClient.post('/api/v1/bookings', {
    ...bookingData,
    source: 'DUMMY',
    channel: 'Dummy Channel Manager',
    status: 'confirmed'
  });
  
  // Update availability (decrease by 1)
  const dates = getDateRange(bookingData.checkIn, bookingData.checkOut);
  for (const date of dates) {
    await updateAvailabilityForDate(bookingData.roomTypeId, date, -1);
  }
  
  // Send webhook
  await sendWebhook('booking.imported', {
    otaCode: 'DUMMY',
    bookingId: booking.data.id,
    booking: booking.data
  });
  
  // Update OTA stats
  updateOTAStats('DUMMY', {
    totalBookings: +1,
    revenue: +bookingData.totalPrice
  });
}
```

#### 6. Auto-Sync Scheduler
Periodically sync data:

```typescript
function startAutoSync() {
  setInterval(async () => {
    if (isConnected('DUMMY')) {
      // Pull latest data from Glimmora
      const availability = await fetchAvailability();
      const rates = await fetchRates();
      
      // Update local cache
      updateLocalCache(availability, rates);
      
      // Simulate booking imports (randomly)
      if (Math.random() < 0.1) { // 10% chance
        await simulateBookingImport();
      }
      
      // Send sync status webhook
      await sendWebhook('sync.status', {
        otaCode: 'DUMMY',
        status: 'completed',
        message: 'Auto-sync completed'
      });
    }
  }, 5 * 60 * 1000); // Every 5 minutes
}
```

### Data Consistency

- Always read from Glimmora before updating
- Use optimistic updates with rollback on error
- Track sync timestamps to avoid conflicts
- Handle concurrent updates gracefully

---

## Data Models

### OTA Connection
```typescript
interface OTAConnection {
  id: string;                    // Unique identifier
  name: string;                   // OTA name (e.g., "Booking.com")
  code: string;                   // OTA code (e.g., "BOOKING")
  logo?: string;                  // Logo URL
  status: 'connected' | 'disconnected' | 'error' | 'syncing';
  lastSync: string;               // ISO timestamp
  nextSync: string | null;        // ISO timestamp or null
  errorMessage?: string;          // Error message if status is 'error'
  credentials: {
    username: string;
    apiKey: string;               // Should be encrypted
    hotelId: string;
  };
  syncSettings: {
    autoSync: boolean;
    syncInterval: number;         // Minutes
    syncRates: boolean;
    syncAvailability: boolean;
    syncRestrictions: boolean;
  };
  stats: {
    totalBookings: number;
    revenue: number;
    avgRating: number;
    commission: number;          // Percentage
  };
  color: string;                  // Hex color for UI
}
```

### Room Mapping
```typescript
interface RoomMapping {
  id: string;
  pmsRoomType: string;            // PMS room type name
  pmsRoomTypeId: string;          // PMS room type ID
  pmsRoomCode?: string;           // PMS room code
  basePrice: number;              // Base rate
  inventory: number;               // Total inventory
  otaMappings: OTARoomMapping[];
}

interface OTARoomMapping {
  otaCode: string;                // OTA code (BOOKING, EXPEDIA, etc.)
  otaRoomType: string;            // OTA room type name
  otaRoomId: string;              // OTA room ID
  otaRoomCode?: string;           // OTA room code
  maxGuests?: number;
  defaultRatePlan?: string;        // BAR, OTA, etc.
  status: 'active' | 'inactive' | 'pending';
  lastSync: string;                // ISO timestamp
}
```

### Rate Calendar Entry
```typescript
interface RateCalendarEntry {
  date: string;                   // YYYY-MM-DD
  roomType: string;               // Room type name
  rates: {
    BAR?: number;                 // Best Available Rate
    [ratePlan: string]: number;    // Other rate plans
  };
  otaRates: {
    [otaCode: string]: number;     // Rate per OTA
  };
  availability: number;            // Available rooms
  stopSell: boolean;
  cta: boolean;                   // Close to Arrival
  ctd: boolean;                   // Close to Departure
}
```

### Restriction
```typescript
interface Restriction {
  id: string;
  roomType: string;               // Room type or 'ALL'
  otaCode: string;                // OTA code or 'ALL'
  dateRange: {
    start: string;                // YYYY-MM-DD
    end: string;                  // YYYY-MM-DD
  };
  restriction: {
    minStay: number;              // Minimum nights (default: 1)
    maxStay: number | null;       // Maximum nights (null = no limit)
    cta: boolean;                 // Close to Arrival
    ctd: boolean;                 // Close to Departure
    stopSell: boolean;            // Stop Sell
  };
  reason?: string;                // Reason/notes
  isActive: boolean;
  createdAt: string;              // ISO timestamp
  createdBy: string;              // User who created
}
```

### Channel Promotion
```typescript
interface ChannelPromotion {
  id: string;
  name: string;
  description: string;
  discountType: 'percentage' | 'fixed';
  discountValue: number;          // Percentage or fixed amount
  validFrom: string;              // YYYY-MM-DD
  validTo: string;                // YYYY-MM-DD
  otaCodes: string[];             // OTA codes or ['ALL']
  roomTypes: string[];            // Room type names or ['ALL']
  minStay: number;                // Minimum nights required
  bookingWindow?: {               // Optional booking window
    start: string;                // YYYY-MM-DD
    end: string;                  // YYYY-MM-DD
  };
  usageCount: number;             // Number of times used
  isActive: boolean;
  createdAt?: string;
  updatedAt?: string;
}
```

### Sync Log
```typescript
interface SyncLog {
  id: string;
  timestamp: string;              // ISO timestamp
  otaCode: string;                // OTA code or 'ALL'
  otaName: string;                // OTA display name
  action: 'rate_update' | 'availability_update' | 'restriction_update' | 
         'promotion_sync' | 'booking_import' | 'connection' | 'bulk_sync';
  status: 'success' | 'error' | 'warning' | 'pending';
  message: string;
  details?: {                     // Additional details
    [key: string]: any;
  };
}
```

### Channel Stats
```typescript
interface ChannelStats {
  connectedOTAs: number;
  disconnectedOTAs: number;
  errorOTAs: number;
  totalBookings: number;
  totalRevenue: number;
  mappedRoomTypes: number;
  totalRoomTypes: number;
  activeRestrictions: number;
  rateParityIssues: Array<{
    roomType: string;
    minRate: number;
    maxRate: number;
    difference: number;           // Percentage
  }>;
  lastSync: string;               // ISO timestamp
  revenueTrend: number[];         // Last 7 days revenue
  bookingsTrend: number[];        // Last 7 days bookings
  channelPerformance: Array<{
    name: string;
    code: string;
    color: string;
    bookings: number;
    revenue: number;
    rating: number;
    commission: number;
    conversionRate: number;
  }>;
  avgCommission: number;
  avgConversionRate: number;
  revenueGrowth: string;          // e.g., "+12%"
  bookingsGrowth: string;         // e.g., "+8%"
  avgRate?: number;
  occupancyRate?: number;
}
```

---

## API Endpoints Specification

### Base URL
- **Channel Manager Service**: `http://localhost:3001/api/v1/channel-manager` (or your channel manager service URL)
- **Glimmora Backend API**: `http://localhost:3000/api/v1/channel-manager` (proxy endpoints)

---

### 1. OTA Connections Endpoints

#### GET `/otas`
Get all OTA connections

**Response**:
```json
{
  "success": true,
  "data": {
    "items": [OTAConnection[]],
    "total": number
  }
}
```

#### GET `/otas/:id`
Get specific OTA connection

**Response**:
```json
{
  "success": true,
  "data": OTAConnection
}
```

#### POST `/otas`
Create/Connect new OTA

**Request Body**:
```json
{
  "name": "Booking.com",
  "code": "BOOKING",
  "credentials": {
    "username": "glimmora_hotel",
    "apiKey": "bk_live_xxxxx",
    "hotelId": "BK-12345678"
  },
  "syncSettings": {
    "autoSync": true,
    "syncInterval": 5,
    "syncRates": true,
    "syncAvailability": true,
    "syncRestrictions": true
  },
  "commission": 15
}
```

**Response**:
```json
{
  "success": true,
  "data": OTAConnection
}
```

#### PUT `/otas/:id`
Update OTA connection (credentials, settings)

**Request Body**:
```json
{
  "credentials": { ... },
  "syncSettings": { ... }
}
```

#### DELETE `/otas/:id`
Disconnect OTA

**Response**:
```json
{
  "success": true,
  "message": "OTA disconnected successfully"
}
```

#### POST `/otas/:id/test`
Test OTA connection

**Response**:
```json
{
  "success": true,
  "data": {
    "connected": boolean,
    "message": string,
    "responseTime": number
  }
}
```

#### POST `/otas/:id/sync`
Trigger manual sync for specific OTA

**Request Body** (optional):
```json
{
  "syncType": "rates" | "availability" | "restrictions" | "all",
  "dateRange": {
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  }
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "syncId": string,
    "status": "pending" | "in_progress",
    "estimatedDuration": number
  }
}
```

#### POST `/otas/sync/all`
Trigger sync for all connected OTAs

**Response**: Same as above

---

### 2. Room Mappings Endpoints

#### GET `/room-mappings`
Get all room mappings

**Query Parameters**:
- `otaCode` (optional): Filter by OTA code
- `pmsRoomTypeId` (optional): Filter by PMS room type ID

**Response**:
```json
{
  "success": true,
  "data": {
    "items": RoomMapping[],
    "total": number
  }
}
```

#### GET `/room-mappings/:id`
Get specific room mapping

#### POST `/room-mappings`
Create new room mapping

**Request Body**:
```json
{
  "pmsRoomTypeId": "room-type-123",
  "pmsRoomType": "Minimalist Studio",
  "otaCode": "BOOKING",
  "otaRoomType": "Studio Room",
  "otaRoomId": "BK-STUDIO-001",
  "maxGuests": 2,
  "defaultRatePlan": "BAR"
}
```

#### PUT `/room-mappings/:id`
Update room mapping

#### DELETE `/room-mappings/:id`
Delete room mapping

#### POST `/room-mappings/auto-map`
Auto-map all PMS room types to OTA

**Request Body**:
```json
{
  "otaCode": "BOOKING"
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "mappingsCreated": number,
    "suggestions": Array<{
      "pmsRoomType": string,
      "suggestedOTARoomType": string,
      "confidence": number
    }>
  }
}
```

#### POST `/room-mappings/validate`
Validate room mapping

**Request Body**:
```json
{
  "pmsRoomTypeId": "room-type-123",
  "otaCode": "BOOKING"
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "valid": boolean,
    "errors": string[],
    "warnings": string[]
  }
}
```

---

### 3. Rate Sync Endpoints

#### GET `/rates/calendar`
Get rate calendar

**Query Parameters**:
- `startDate` (required): YYYY-MM-DD
- `endDate` (required): YYYY-MM-DD
- `roomTypeId` (optional): Filter by room type
- `otaCode` (optional): Filter by OTA

**Response**:
```json
{
  "success": true,
  "data": {
    "calendar": {
      "YYYY-MM-DD": {
        "room-type-name": RateCalendarEntry
      }
    }
  }
}
```

#### PUT `/rates/calendar/:date/:roomType`
Update rate for specific date and room type

**Request Body**:
```json
{
  "rates": {
    "BAR": 200,
    "OTA": 180
  },
  "otaRates": {
    "BOOKING": 195,
    "EXPEDIA": 190
  },
  "availability": 5,
  "stopSell": false,
  "cta": false,
  "ctd": false
}
```

#### POST `/rates/push`
Push rates to OTAs

**Request Body**:
```json
{
  "otaCodes": ["BOOKING", "EXPEDIA"] | ["ALL"],
  "dateRange": {
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  },
  "roomTypeIds": ["room-type-123"] | ["ALL"]
}
```

**Response**:
```json
{
  "success": true,
  "data": {
    "syncId": string,
    "status": "pending"
  }
}
```

#### POST `/rates/pull`
Pull rates from OTAs

**Request Body**: Same as push

#### GET `/rates/parity`
Get rate parity issues

**Query Parameters**:
- `date` (optional): YYYY-MM-DD (default: today)
- `threshold` (optional): Percentage threshold (default: 10)

**Response**:
```json
{
  "success": true,
  "data": {
    "issues": Array<{
      "date": string,
      "roomType": string,
      "minRate": number,
      "maxRate": number,
      "difference": number,
      "otas": string[]
    }>
  }
}
```

---

### 4. Restrictions Endpoints

#### GET `/restrictions`
Get all restrictions

**Query Parameters**:
- `status` (optional): 'active' | 'inactive' | 'all'
- `roomType` (optional): Filter by room type
- `otaCode` (optional): Filter by OTA
- `dateFrom` (optional): YYYY-MM-DD
- `dateTo` (optional): YYYY-MM-DD

**Response**:
```json
{
  "success": true,
  "data": {
    "items": Restriction[],
    "total": number
  }
}
```

#### GET `/restrictions/:id`
Get specific restriction

#### POST `/restrictions`
Create new restriction

**Request Body**:
```json
{
  "roomType": "Minimalist Studio" | "ALL",
  "otaCode": "BOOKING" | "ALL",
  "dateRange": {
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  },
  "restriction": {
    "minStay": 2,
    "maxStay": null,
    "cta": false,
    "ctd": false,
    "stopSell": false
  },
  "reason": "Valentine's Day weekend"
}
```

#### PUT `/restrictions/:id`
Update restriction

#### DELETE `/restrictions/:id`
Delete restriction

#### PUT `/restrictions/:id/toggle`
Toggle restriction active status

**Response**:
```json
{
  "success": true,
  "data": {
    "isActive": boolean
  }
}
```

---

### 5. Promotions Endpoints

#### GET `/promotions`
Get all channel promotions

**Query Parameters**:
- `status` (optional): 'active' | 'scheduled' | 'expired' | 'inactive' | 'all'
- `otaCode` (optional): Filter by OTA

**Response**:
```json
{
  "success": true,
  "data": {
    "items": ChannelPromotion[],
    "total": number
  }
}
```

#### GET `/promotions/:id`
Get specific promotion

#### POST `/promotions`
Create new promotion

**Request Body**:
```json
{
  "name": "Winter Flash Sale",
  "description": "Limited time discount",
  "discountType": "percentage",
  "discountValue": 15,
  "validFrom": "YYYY-MM-DD",
  "validTo": "YYYY-MM-DD",
  "otaCodes": ["BOOKING"] | ["ALL"],
  "roomTypes": ["Minimalist Studio"] | ["ALL"],
  "minStay": 2,
  "bookingWindow": {
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  }
}
```

#### PUT `/promotions/:id`
Update promotion

#### DELETE `/promotions/:id`
Delete promotion

#### PUT `/promotions/:id/toggle`
Toggle promotion active status

#### POST `/promotions/:id/apply`
Apply promotion to specific OTAs

**Request Body**:
```json
{
  "otaCodes": ["BOOKING", "EXPEDIA"]
}
```

---

### 6. Sync Logs Endpoints

#### GET `/sync-logs`
Get sync logs

**Query Parameters**:
- `otaCode` (optional): Filter by OTA
- `action` (optional): Filter by action type
- `status` (optional): Filter by status
- `dateFrom` (optional): ISO timestamp
- `dateTo` (optional): ISO timestamp
- `page` (optional): Page number (default: 1)
- `pageSize` (optional): Items per page (default: 50)

**Response**:
```json
{
  "success": true,
  "data": {
    "items": SyncLog[],
    "total": number,
    "page": number,
    "pageSize": number,
    "totalPages": number
  }
}
```

#### GET `/sync-logs/:id`
Get specific sync log with details

#### DELETE `/sync-logs`
Clear all sync logs (admin only)

**Response**:
```json
{
  "success": true,
  "message": "Sync logs cleared"
}
```

#### GET `/sync-logs/export`
Export sync logs to CSV

**Query Parameters**: Same as GET `/sync-logs`

**Response**: CSV file download

---

### 7. Dashboard/Stats Endpoints

#### GET `/stats`
Get channel manager statistics

**Response**:
```json
{
  "success": true,
  "data": ChannelStats
}
```

#### GET `/stats/insights`
Get AI insights and recommendations

**Response**:
```json
{
  "success": true,
  "data": {
    "insights": Array<{
      "type": "error" | "warning" | "info" | "success",
      "title": string,
      "message": string,
      "action": string
    }>
  }
}
```

---

## Webhooks & SSE Events

### Webhook Endpoints (Channel Manager → Glimmora Backend)

The Channel Manager should send webhooks to the Glimmora Backend when events occur:

#### Webhook URL Format
`POST {GLIMMORA_BACKEND_URL}/api/v1/webhooks/channel-manager`

#### Webhook Events

1. **OTA Connection Status Changed**
```json
{
  "event": "ota.connection.status_changed",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "otaId": "ota-001",
    "otaCode": "BOOKING",
    "otaName": "Booking.com",
    "oldStatus": "disconnected",
    "newStatus": "connected",
    "errorMessage": null
  }
}
```

2. **Rate Updated**
```json
{
  "event": "rates.updated",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "otaCode": "BOOKING",
    "date": "2025-01-20",
    "roomType": "Minimalist Studio",
    "oldRate": 200,
    "newRate": 220,
    "syncId": "sync-123"
  }
}
```

3. **Availability Updated**
```json
{
  "event": "availability.updated",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "otaCode": "BOOKING",
    "date": "2025-01-20",
    "roomType": "Minimalist Studio",
    "oldAvailability": 5,
    "newAvailability": 3,
    "syncId": "sync-123"
  }
}
```

4. **Restriction Updated**
```json
{
  "event": "restrictions.updated",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "restrictionId": "rest-001",
    "roomType": "ALL",
    "otaCode": "ALL",
    "action": "created" | "updated" | "deleted",
    "restriction": { ... }
  }
}
```

5. **Sync Status**
```json
{
  "event": "sync.status",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "syncId": "sync-123",
    "otaCode": "BOOKING",
    "status": "in_progress" | "completed" | "failed",
    "progress": 75,
    "message": "Syncing rates..."
  }
}
```

6. **Booking Imported**
```json
{
  "event": "booking.imported",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "otaCode": "BOOKING",
    "bookingId": "BK-789456",
    "guestName": "John Smith",
    "roomType": "Sunset Vista",
    "checkIn": "2025-01-20",
    "checkOut": "2025-01-22",
    "totalPrice": 400
  }
}
```

### SSE Events (Glimmora Backend → Frontend)

The Glimmora Backend should forward these events via SSE to the frontend:

- `availability.updated`
- `rates.updated`
- `restrictions.updated`
- `sync.status`

(These are already implemented in the frontend SSE integration)

---

## Channel Manager Project Instructions

### Project Setup

1. **Create a new Node.js/Express project** (or use your preferred framework)
2. **Install dependencies**:
   ```bash
   npm install express cors dotenv axios
   npm install -D @types/node @types/express typescript ts-node nodemon
   ```

3. **Project Structure**:
   ```
   channel-manager/
   ├── src/
   │   ├── controllers/
   │   │   ├── ota.controller.ts
   │   │   ├── roomMapping.controller.ts
   │   │   ├── rate.controller.ts
   │   │   ├── restriction.controller.ts
   │   │   ├── promotion.controller.ts
   │   │   ├── syncLog.controller.ts
   │   │   └── stats.controller.ts
   │   ├── services/
   │   │   ├── ota.service.ts
   │   │   ├── roomMapping.service.ts
   │   │   ├── rate.service.ts
   │   │   ├── restriction.service.ts
   │   │   ├── promotion.service.ts
   │   │   ├── sync.service.ts
   │   │   └── webhook.service.ts
   │   ├── models/
   │   │   ├── OTA.ts
   │   │   ├── RoomMapping.ts
   │   │   ├── RateCalendar.ts
   │   │   ├── Restriction.ts
   │   │   ├── Promotion.ts
   │   │   └── SyncLog.ts
   │   ├── routes/
   │   │   └── index.ts
   │   ├── middleware/
   │   │   ├── auth.middleware.ts
   │   │   └── error.middleware.ts
   │   ├── utils/
   │   │   ├── logger.ts
   │   │   └── validators.ts
   │   └── app.ts
   ├── .env
   ├── package.json
   └── tsconfig.json
   ```

### Implementation Steps

#### Step 1: Create Data Storage
- Use in-memory storage (Map/Array) for dummy implementation
- Or use a simple database (SQLite, MongoDB, etc.)
- Initialize with sample data matching the frontend sample data
- **IMPORTANT**: Also initialize "Dummy Channel Manager" as a connectable OTA with code "DUMMY"

#### Step 1.5: Initialize Dummy Channel Manager as OTA
Add the dummy Channel Manager to the available OTAs list:

```typescript
const dummyOTA = {
  id: 'ota-dummy',
  name: 'Dummy Channel Manager',
  code: 'DUMMY',
  logo: null,
  status: 'disconnected',
  color: '#A57865', // Glimmora terra color
  credentials: {
    username: 'dummy_channel_manager',
    apiKey: 'dummy_api_key',
    hotelId: 'DUMMY-HOTEL-001'
  },
  syncSettings: {
    autoSync: true,
    syncInterval: 5,
    syncRates: true,
    syncAvailability: true,
    syncRestrictions: true
  },
  stats: {
    totalBookings: 0,
    revenue: 0,
    avgRating: 0,
    commission: 0
  }
};
```

#### Step 2: Implement OTA Service
- `connectOTA()`: Validate credentials, create OTA connection
  - **For DUMMY OTA**: Always succeed, fetch data from Glimmora backend, initialize mappings
- `disconnectOTA()`: Mark OTA as disconnected
- `testConnection()`: Test API connection with credentials
  - **For DUMMY OTA**: Test connection to Glimmora backend API
- `updateCredentials()`: Update OTA credentials
- `updateSyncSettings()`: Update sync configuration
- `triggerSync()`: Start sync process for OTA
  - **For DUMMY OTA**: Sync rates/availability to/from Glimmora backend

#### Step 3: Implement Room Mapping Service
- `getMappings()`: Get all room mappings
- `createMapping()`: Create new mapping
- `updateMapping()`: Update existing mapping
- `deleteMapping()`: Remove mapping
- `autoMap()`: AI-powered auto-mapping suggestions
- `validateMapping()`: Validate mapping before activation

#### Step 4: Implement Rate Service
- `getRateCalendar()`: Get rates for date range
  - **For DUMMY OTA**: Fetch from Glimmora backend rate plans
- `updateRate()`: Update rate for specific date/room/OTA
  - **For DUMMY OTA**: Update rate in Glimmora backend via API
- `pushRates()`: Push rates to OTAs
  - **For DUMMY OTA**: Update rates in Glimmora backend, send webhook
- `pullRates()`: Pull rates from OTAs
  - **For DUMMY OTA**: Fetch latest rates from Glimmora backend
- `checkRateParity()`: Check for rate parity issues
- `updateAvailability()`: Update inventory
  - **For DUMMY OTA**: Update availability in Glimmora backend via bulk update API

#### Step 5: Implement Restriction Service
- `getRestrictions()`: Get all restrictions with filters
- `createRestriction()`: Create new restriction
  - **For DUMMY OTA**: Apply restriction to Glimmora backend availability
- `updateRestriction()`: Update restriction
  - **For DUMMY OTA**: Update restriction in Glimmora backend
- `deleteRestriction()`: Remove restriction
  - **For DUMMY OTA**: Remove restriction from Glimmora backend
- `toggleRestriction()`: Toggle active status
  - **For DUMMY OTA**: Update restriction status in Glimmora backend

#### Step 6: Implement Promotion Service
- `getPromotions()`: Get all promotions
- `createPromotion()`: Create new promotion
- `updatePromotion()`: Update promotion
- `deletePromotion()`: Remove promotion
- `applyPromotion()`: Apply promotion to OTAs

#### Step 7: Implement Sync Service
- `syncRates()`: Sync rates to/from OTAs
  - **For DUMMY OTA**: Read/write rates from/to Glimmora backend
- `syncAvailability()`: Sync inventory
  - **For DUMMY OTA**: Read/write availability from/to Glimmora backend
- `syncRestrictions()`: Sync restrictions
  - **For DUMMY OTA**: Apply restrictions to Glimmora backend availability
- `syncAll()`: Full sync for all OTAs
  - **For DUMMY OTA**: Full sync with Glimmora backend
- `getSyncStatus()`: Get sync progress
- `simulateBookingImport()`: Simulate booking import from dummy OTA
  - **For DUMMY OTA**: Create actual booking in Glimmora backend, update availability

#### Step 8: Implement Sync Log Service
- `createLog()`: Create sync log entry
- `getLogs()`: Get logs with filters and pagination
- `getLogById()`: Get specific log
- `clearLogs()`: Clear all logs

#### Step 9: Implement Stats Service
- `getChannelStats()`: Calculate all statistics
- `getAIInsights()`: Generate AI insights and recommendations

#### Step 10: Implement Webhook Service
- `sendWebhook()`: Send webhook to Glimmora Backend
- Configure webhook URL from environment variable
- Retry logic for failed webhooks
- Webhook authentication (API key)

#### Step 11: Create API Routes
- Map all endpoints to controllers
- Add authentication middleware
- Add request validation
- Add error handling

#### Step 12: Add Auto-Sync Scheduler
- Background job to auto-sync connected OTAs
- Configurable sync interval per OTA
- Respect sync settings (autoSync flag)
- **For DUMMY OTA**: 
  - Periodically fetch latest data from Glimmora backend
  - Simulate booking imports (randomly, e.g., 10% chance per sync)
  - Update OTA statistics from real bookings
  - Send sync status webhooks

### Environment Variables

```env
PORT=3001
NODE_ENV=development
GLIMMORA_BACKEND_URL=http://localhost:3000
GLIMMORA_API_TOKEN=your-glimmora-api-token  # If authentication required
WEBHOOK_SECRET=your-webhook-secret-key
API_KEY=your-api-key-for-authentication
```

**Note**: The Channel Manager must be able to call Glimmora Backend APIs. Ensure:
- CORS is configured in Glimmora Backend to allow Channel Manager requests
- Authentication token is provided if required
- API endpoints are accessible

### Sample Data Initialization

Initialize your database/storage with sample data matching:
- `src/data/channel-manager/sampleOTAs.ts`
- `src/data/channel-manager/sampleRoomMappings.ts`
- `src/data/channel-manager/sampleRestrictions.ts`
- `src/data/channel-manager/sampleSyncLogs.ts`

---

## Glimmora Backend API Instructions

### Integration Steps

#### Step 1: Create Channel Manager Routes

Create new route file: `src/routes/channel-manager.routes.ts`

```typescript
import express from 'express';
import { channelManagerController } from '../controllers/channel-manager.controller';
import { authenticate } from '../middleware/auth.middleware';

const router = express.Router();

// OTA Connections
router.get('/otas', authenticate, channelManagerController.getOTAs);
router.get('/otas/:id', authenticate, channelManagerController.getOTA);
router.post('/otas', authenticate, channelManagerController.createOTA);
router.put('/otas/:id', authenticate, channelManagerController.updateOTA);
router.delete('/otas/:id', authenticate, channelManagerController.deleteOTA);
router.post('/otas/:id/test', authenticate, channelManagerController.testOTA);
router.post('/otas/:id/sync', authenticate, channelManagerController.syncOTA);
router.post('/otas/sync/all', authenticate, channelManagerController.syncAllOTAs);

// Room Mappings
router.get('/room-mappings', authenticate, channelManagerController.getRoomMappings);
router.get('/room-mappings/:id', authenticate, channelManagerController.getRoomMapping);
router.post('/room-mappings', authenticate, channelManagerController.createRoomMapping);
router.put('/room-mappings/:id', authenticate, channelManagerController.updateRoomMapping);
router.delete('/room-mappings/:id', authenticate, channelManagerController.deleteRoomMapping);
router.post('/room-mappings/auto-map', authenticate, channelManagerController.autoMap);
router.post('/room-mappings/validate', authenticate, channelManagerController.validateMapping);

// Rate Sync
router.get('/rates/calendar', authenticate, channelManagerController.getRateCalendar);
router.put('/rates/calendar/:date/:roomType', authenticate, channelManagerController.updateRate);
router.post('/rates/push', authenticate, channelManagerController.pushRates);
router.post('/rates/pull', authenticate, channelManagerController.pullRates);
router.get('/rates/parity', authenticate, channelManagerController.getRateParity);

// Restrictions
router.get('/restrictions', authenticate, channelManagerController.getRestrictions);
router.get('/restrictions/:id', authenticate, channelManagerController.getRestriction);
router.post('/restrictions', authenticate, channelManagerController.createRestriction);
router.put('/restrictions/:id', authenticate, channelManagerController.updateRestriction);
router.delete('/restrictions/:id', authenticate, channelManagerController.deleteRestriction);
router.put('/restrictions/:id/toggle', authenticate, channelManagerController.toggleRestriction);

// Promotions
router.get('/promotions', authenticate, channelManagerController.getPromotions);
router.get('/promotions/:id', authenticate, channelManagerController.getPromotion);
router.post('/promotions', authenticate, channelManagerController.createPromotion);
router.put('/promotions/:id', authenticate, channelManagerController.updatePromotion);
router.delete('/promotions/:id', authenticate, channelManagerController.deletePromotion);
router.put('/promotions/:id/toggle', authenticate, channelManagerController.togglePromotion);
router.post('/promotions/:id/apply', authenticate, channelManagerController.applyPromotion);

// Sync Logs
router.get('/sync-logs', authenticate, channelManagerController.getSyncLogs);
router.get('/sync-logs/:id', authenticate, channelManagerController.getSyncLog);
router.delete('/sync-logs', authenticate, channelManagerController.clearSyncLogs);
router.get('/sync-logs/export', authenticate, channelManagerController.exportSyncLogs);

// Stats
router.get('/stats', authenticate, channelManagerController.getStats);
router.get('/stats/insights', authenticate, channelManagerController.getInsights);

export default router;
```

#### Step 2: Create Channel Manager Controller

Create: `src/controllers/channel-manager.controller.ts`

This controller will proxy requests to the Channel Manager service:

```typescript
import { Request, Response } from 'express';
import axios from 'axios';
import { CHANNEL_MANAGER_URL } from '../config';

const channelManagerClient = axios.create({
  baseURL: CHANNEL_MANAGER_URL,
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': process.env.CHANNEL_MANAGER_API_KEY
  }
});

export const channelManagerController = {
  // OTA Methods
  getOTAs: async (req: Request, res: Response) => {
    try {
      const response = await channelManagerClient.get('/otas');
      res.json(response.data);
    } catch (error) {
      res.status(500).json({ success: false, error: error.message });
    }
  },

  createOTA: async (req: Request, res: Response) => {
    try {
      const response = await channelManagerClient.post('/otas', req.body);
      res.json(response.data);
    } catch (error) {
      res.status(500).json({ success: false, error: error.message });
    }
  },

  // ... Implement all other methods similarly
};
```

#### Step 3: Create Webhook Handler

Create: `src/routes/webhooks.routes.ts`

```typescript
import express from 'express';
import { webhookController } from '../controllers/webhook.controller';
import { verifyWebhookSignature } from '../middleware/webhook.middleware';

const router = express.Router();

router.post('/channel-manager', 
  verifyWebhookSignature,
  webhookController.handleChannelManagerWebhook
);

export default router;
```

Create: `src/controllers/webhook.controller.ts`

```typescript
import { Request, Response } from 'express';
import { sseService } from '../services/sse.service';

export const webhookController = {
  handleChannelManagerWebhook: async (req: Request, res: Response) => {
    const { event, data } = req.body;

    // Forward to SSE for real-time frontend updates
    switch (event) {
      case 'rates.updated':
        sseService.broadcast('rates.updated', data);
        break;
      case 'availability.updated':
        sseService.broadcast('availability.updated', data);
        break;
      case 'restrictions.updated':
        sseService.broadcast('restrictions.updated', data);
        break;
      case 'sync.status':
        sseService.broadcast('sync.status', data);
        break;
      // Handle other events as needed
    }

    // Update database if needed
    // await updateDatabase(event, data);

    res.json({ success: true });
  }
};
```

#### Step 4: Update App Routes

Add to your main app file:

```typescript
import channelManagerRoutes from './routes/channel-manager.routes';
import webhookRoutes from './routes/webhooks.routes';

app.use('/api/v1/channel-manager', channelManagerRoutes);
app.use('/api/v1/webhooks', webhookRoutes);
```

#### Step 5: Environment Variables

Add to `.env`:

```env
CHANNEL_MANAGER_URL=http://localhost:3001/api/v1/channel-manager
CHANNEL_MANAGER_API_KEY=your-channel-manager-api-key
WEBHOOK_SECRET=your-webhook-secret
```

---

## Integration Flow

### 1. Frontend → Glimmora Backend → Channel Manager

```
Frontend (React)
    ↓ HTTP Request
Glimmora Backend API (Proxy)
    ↓ HTTP Request (with API Key)
Channel Manager Service
    ↓ Process & Store
Channel Manager Database
    ↓ Webhook
Glimmora Backend (Webhook Handler)
    ↓ SSE Event
Frontend (Real-time Update)
```

### 2. Channel Manager → Glimmora Backend → Frontend

```
Channel Manager (Event Occurs)
    ↓ Webhook POST
Glimmora Backend (Webhook Handler)
    ↓ Process & Store
Glimmora Backend Database
    ↓ SSE Broadcast
Frontend (Real-time Update)
```

### 3. Dummy Channel Manager → Glimmora Backend (Direct Update)

**IMPORTANT**: When the dummy Channel Manager (DUMMY OTA) is connected, it directly updates Glimmora Backend:

```
Dummy Channel Manager (DUMMY OTA Connected)
    ↓ Direct API Calls
Glimmora Backend APIs:
    - PUT /api/v1/cms/availability/bulk-update (Update availability)
    - PUT /api/v1/revenue-intelligence/rates/:roomTypeId/:date (Update rates)
    - POST /api/v1/bookings (Create bookings)
    ↓ Database Updated
Glimmora Backend Database
    ↓ SSE Broadcast (via webhook)
Frontend (Real-time Update)
```

**Example Flow for Rate Update:**
1. User updates rate in Channel Manager UI
2. Frontend → Glimmora Backend → Channel Manager API
3. Channel Manager processes update
4. **Channel Manager directly calls**: `PUT /api/v1/revenue-intelligence/rates/:roomTypeId/:date`
5. Glimmora Backend updates rate in database
6. Channel Manager sends webhook: `rates.updated`
7. Glimmora Backend forwards webhook to SSE
8. Frontend receives real-time update

**Example Flow for Booking Import:**
1. Dummy Channel Manager auto-sync runs
2. Simulates booking import (randomly)
3. **Channel Manager directly calls**: `POST /api/v1/bookings`
4. Glimmora Backend creates booking, updates availability
5. Channel Manager sends webhook: `booking.imported`
6. Glimmora Backend forwards to SSE
7. Frontend shows new booking in real-time

### 4. Auto-Sync Flow (Dummy Channel Manager)

```
Dummy Channel Manager (Scheduled Job - Every 5 min)
    ↓ Fetch latest data from Glimmora
    GET /api/v1/room-types
    GET /api/v1/rooms/availability
    GET /api/v1/cms/rate-plans
    ↓ Update local cache
    ↓ Simulate booking import (10% chance)
    POST /api/v1/bookings (Create real booking)
    ↓ Update availability
    PUT /api/v1/cms/availability/bulk-update
    ↓ Send webhook
    POST /api/v1/webhooks/channel-manager
    ↓ Glimmora Backend processes
    ↓ SSE Broadcast
    Frontend (Real-time Update)
```

---

## Testing Checklist

### OTA Connections
- [ ] List all OTAs (including "Dummy Channel Manager")
- [ ] Connect "Dummy Channel Manager" OTA
- [ ] Verify connection fetches data from Glimmora backend
- [ ] Update OTA credentials
- [ ] Test OTA connection (tests Glimmora backend API)
- [ ] Disconnect OTA
- [ ] Manual sync per OTA (updates Glimmora backend)
- [ ] Manual sync all OTAs
- [ ] Auto-sync scheduler (updates Glimmora backend periodically)

### Room Mappings
- [ ] List all room mappings
- [ ] Create room mapping
- [ ] Update room mapping
- [ ] Delete room mapping
- [ ] Auto-map all rooms
- [ ] Validate mapping
- [ ] Filter by OTA

### Rate Sync
- [ ] Get rate calendar (fetches from Glimmora backend)
- [ ] Update rate for date/room (updates Glimmora backend)
- [ ] Push rates to OTAs (updates Glimmora backend for DUMMY)
- [ ] Pull rates from OTAs (fetches from Glimmora backend for DUMMY)
- [ ] Check rate parity
- [ ] Update availability (updates Glimmora backend)
- [ ] Toggle stop sell/CTA/CTD (updates Glimmora backend)
- [ ] Verify changes reflect in Glimmora CMS/RMS

### Restrictions
- [ ] List restrictions
- [ ] Create restriction (applies to Glimmora backend availability)
- [ ] Update restriction (updates Glimmora backend)
- [ ] Delete restriction (removes from Glimmora backend)
- [ ] Toggle restriction status (updates Glimmora backend)
- [ ] Filter by room type/OTA/status
- [ ] Verify restrictions affect availability in Glimmora CMS

### Promotions
- [ ] List promotions
- [ ] Create promotion
- [ ] Update promotion
- [ ] Delete promotion
- [ ] Toggle promotion status
- [ ] Apply promotion to OTAs

### Sync Logs
- [ ] List sync logs
- [ ] Filter logs
- [ ] Export logs to CSV
- [ ] Clear logs
- [ ] Real-time log updates

### Dashboard
- [ ] Get channel stats
- [ ] Get AI insights
- [ ] Real-time updates via SSE

### Webhooks
- [ ] OTA connection status changed
- [ ] Rates updated (triggers when Glimmora backend is updated)
- [ ] Availability updated (triggers when Glimmora backend is updated)
- [ ] Restrictions updated (triggers when Glimmora backend is updated)
- [ ] Sync status
- [ ] Booking imported (triggers when booking created in Glimmora backend)

### Real Data Integration (Dummy Channel Manager)
- [ ] Connect "Dummy Channel Manager" OTA
- [ ] Verify room mappings initialized from Glimmora room types
- [ ] Update rate → Verify rate updated in Glimmora backend
- [ ] Update availability → Verify availability updated in Glimmora backend
- [ ] Apply restriction → Verify restriction applied in Glimmora backend
- [ ] Simulate booking import → Verify booking created in Glimmora backend
- [ ] Verify booking appears in Glimmora bookings list
- [ ] Verify availability decreased after booking
- [ ] Verify OTA stats calculated from real bookings
- [ ] Verify all changes reflect in real-time via SSE

---

## Questions & Clarifications

If you have any questions about:
- Data structure details
- API endpoint specifications
- Webhook payload formats
- Integration flow
- Error handling
- Authentication/Authorization

Please ask before starting implementation to ensure alignment.

---

## Additional Notes

1. **Authentication**: All endpoints should require authentication (JWT token or API key)
2. **Error Handling**: Return consistent error format: `{ success: false, error: string, code?: string }`
3. **Validation**: Validate all request bodies before processing
4. **Logging**: Log all operations for debugging
5. **Rate Limiting**: Implement rate limiting for API endpoints
6. **CORS**: Configure CORS to allow Glimmora Backend requests
7. **Encryption**: Encrypt OTA credentials in storage
8. **Retry Logic**: Implement retry logic for webhook delivery
9. **Health Check**: Add `/health` endpoint for monitoring
10. **Documentation**: Generate API documentation (Swagger/OpenAPI)

---

**End of Document**
