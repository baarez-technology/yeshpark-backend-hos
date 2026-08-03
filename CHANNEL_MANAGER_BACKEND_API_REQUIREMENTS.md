# Channel Manager Backend API Requirements

## Overview
This document lists all API endpoints required by the frontend for the 7 Channel Manager tabs. The backend must implement these endpoints to ensure full functionality.

## Base URL
All endpoints are under: `/api/v1/channel-manager`

---

## Tab 1: Dashboard

### Required Endpoints

#### 1. Get Channel Statistics
**GET** `/api/v1/channel-manager/stats`

**Response:**
```json
{
  "data": {
    "connectedOTAs": 3,
    "disconnectedOTAs": 2,
    "errorOTAs": 1,
    "totalBookings": 450,
    "totalRevenue": 125000,
    "mappedRoomTypes": 6,
    "totalRoomTypes": 8,
    "activeRestrictions": 12,
    "rateParityIssues": [
      {
        "roomType": "Minimalist Studio",
        "minRate": 150,
        "maxRate": 180,
        "difference": 30
      }
    ],
    "lastSync": "2025-01-23T10:30:00Z",
    "revenueTrend": [12000, 15000, 18000, 20000],
    "bookingsTrend": [45, 52, 58, 62],
    "channelPerformance": [
      {
        "name": "Dummy Channel Manager",
        "code": "DUMMY",
        "color": "#A57865",
        "bookings": 156,
        "revenue": 45600,
        "rating": 4.7,
        "commission": 15,
        "conversionRate": 2.1
      }
    ],
    "avgCommission": 15,
    "avgConversionRate": 2.1,
    "revenueGrowth": "+12%",
    "bookingsGrowth": "+8%",
    "avgRate": 185,
    "occupancyRate": 78
  }
}
```

**Important Notes:**
- `channelPerformance` array should map OTA codes to booking sources:
  - `DUMMY` → filter bookings by `source: "CRS"`
  - `BOOKING` → filter bookings by `source: "Booking.com"`
  - `EXPEDIA` → filter bookings by `source: "Expedia"`
  - etc.
- Calculate `bookings` and `revenue` by filtering bookings table by the mapped source
- `lastSync` should be the most recent sync timestamp across all OTAs

#### 2. Get AI Insights
**GET** `/api/v1/channel-manager/stats/insights`

**Response:**
```json
{
  "data": {
    "insights": [
      {
        "type": "warning",
        "title": "Rate Parity Issue Detected",
        "message": "Minimalist Studio has 20% rate difference across channels",
        "action": "Review rate calendar"
      },
      {
        "type": "info",
        "title": "High Demand Period",
        "message": "Weekend bookings increased by 25%",
        "action": "Consider rate adjustments"
      }
    ]
  }
}
```

#### 3. Get Sync Logs (Recent)
**GET** `/api/v1/channel-manager/sync-logs?pageSize=5`

See **Tab 7: Sync Logs** for full endpoint details.

#### 4. Get OTA Connections
**GET** `/api/v1/channel-manager/otas`

See **Tab 2: OTA Connections** for full endpoint details.

#### 5. Get Bookings by Source (for OTA Performance Details)
**GET** `/api/v1/bookings?source={source}&limit=50`

**Query Parameters:**
- `source`: Booking source (e.g., "CRS" for dummy CM, "Booking.com" for Booking.com)
- `limit`: Number of bookings to return

**Response:**
```json
{
  "data": {
    "items": [
      {
        "id": "booking-123",
        "guest": "John Smith",
        "guestName": "John Smith",
        "email": "john@example.com",
        "phone": "+1234567890",
        "checkIn": "2025-01-25",
        "checkOut": "2025-01-27",
        "roomType": "Minimalist Studio",
        "amount": 300,
        "total": 300,
        "source": "CRS"
      }
    ],
    "total": 156
  }
}
```

---

## Tab 2: OTA Connections

### Required Endpoints

#### 1. Get All OTA Connections
**GET** `/api/v1/channel-manager/otas`

**Response:**
```json
{
  "data": {
    "items": [
      {
        "id": "ota-001",
        "name": "Dummy Channel Manager",
        "code": "DUMMY",
        "logo": null,
        "status": "connected",
        "lastSync": "2025-01-23T10:30:00Z",
        "nextSync": "2025-01-23T10:35:00Z",
        "errorMessage": null,
        "credentials": {
          "username": "dummy_channel_manager",
          "apiKey": "dummy_api_key",
          "hotelId": "DUMMY-HOTEL-001"
        },
        "syncSettings": {
          "autoSync": true,
          "syncInterval": 5,
          "syncRates": true,
          "syncAvailability": true,
          "syncRestrictions": true
        },
        "stats": {
          "totalBookings": 156,
          "revenue": 45600,
          "avgRating": 4.7,
          "commission": 15
        },
        "color": "#A57865"
      }
    ],
    "total": 1
  }
}
```

**Important Notes:**
- `stats.totalBookings` and `stats.revenue` should be calculated by filtering bookings by source:
  - For `DUMMY` code → filter by `source: "CRS"`
  - For other OTAs → filter by their respective source (see source mapping)
- `status` can be: `"connected"`, `"disconnected"`, `"error"`, `"syncing"`
- `lastSync` and `nextSync` should be ISO 8601 timestamps

#### 2. Get Specific OTA
**GET** `/api/v1/channel-manager/otas/{id}`

**Response:** Same as single OTA object in the array above.

#### 3. Create/Connect OTA
**POST** `/api/v1/channel-manager/otas`

**Request Body:**
```json
{
  "code": "DUMMY",
  "name": "Dummy Channel Manager",
  "credentials": {
    "username": "dummy_channel_manager",
    "apiKey": "dummy_api_key",
    "hotelId": "DUMMY-HOTEL-001"
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

**Response:** OTA object (same structure as GET response)

#### 4. Update OTA Connection
**PUT** `/api/v1/channel-manager/otas/{id}`

**Request Body:** Partial OTA object (any fields to update)

**Response:** Updated OTA object

#### 5. Delete/Disconnect OTA
**DELETE** `/api/v1/channel-manager/otas/{id}`

**Response:** `204 No Content`

#### 6. Test OTA Connection
**POST** `/api/v1/channel-manager/otas/{id}/test`

**Response:**
```json
{
  "data": {
    "connected": true,
    "message": "Connection successful",
    "responseTime": 245
  }
}
```

#### 7. Trigger Manual Sync
**POST** `/api/v1/channel-manager/otas/{id}/sync`

**Request Body (optional):**
```json
{
  "syncType": "all",
  "dateRange": {
    "start": "2025-01-23",
    "end": "2025-02-23"
  }
}
```

**Response:**
```json
{
  "data": {
    "syncId": "sync-123",
    "status": "pending",
    "estimatedDuration": 30
  }
}
```

#### 8. Sync All OTAs
**POST** `/api/v1/channel-manager/otas/sync/all`

**Response:** Same as individual sync response

---

## Tab 3: Room Mapping

### Required Endpoints

#### 1. Get All Room Mappings
**GET** `/api/v1/channel-manager/room-mappings?otaCode={code}&pmsRoomTypeId={id}`

**Query Parameters (optional):**
- `otaCode`: Filter by OTA code
- `pmsRoomTypeId`: Filter by PMS room type ID

**Response:**
```json
{
  "data": {
    "items": [
      {
        "id": "mapping-001",
        "pmsRoomType": "Minimalist Studio",
        "pmsRoomTypeId": "rt-001",
        "pmsRoomCode": "MINST",
        "basePrice": 150,
        "inventory": 10,
        "otaMappings": [
          {
            "otaCode": "DUMMY",
            "otaRoomType": "Studio Room",
            "otaRoomId": "STUDIO_ROOM",
            "otaRoomCode": "STUDIO",
            "maxGuests": 2,
            "defaultRatePlan": "BAR",
            "status": "active",
            "lastSync": "2025-01-23T10:30:00Z"
          }
        ]
      }
    ],
    "total": 8
  }
}
```

**Important Notes:**
- `pmsRoomTypeId` should match the room type ID from `/api/v1/room-types`
- `pmsRoomType` should match the room type name from `/api/v1/room-types`
- `otaMappings` is an array because one PMS room can map to multiple OTAs

#### 2. Get Specific Room Mapping
**GET** `/api/v1/channel-manager/room-mappings/{id}`

**Response:** Single room mapping object

#### 3. Create Room Mapping
**POST** `/api/v1/channel-manager/room-mappings`

**Request Body:**
```json
{
  "pmsRoomTypeId": "rt-001",
  "pmsRoomType": "Minimalist Studio",
  "otaCode": "DUMMY",
  "otaRoomType": "Studio Room",
  "otaRoomId": "STUDIO_ROOM",
  "maxGuests": 2,
  "defaultRatePlan": "BAR"
}
```

**Response:** Created room mapping object

#### 4. Update Room Mapping
**PUT** `/api/v1/channel-manager/room-mappings/{id}`

**Request Body:** Partial room mapping object

**Response:** Updated room mapping object

#### 5. Delete Room Mapping
**DELETE** `/api/v1/channel-manager/room-mappings/{id}`

**Response:** `204 No Content`

#### 6. Auto-Map Room Mappings
**POST** `/api/v1/channel-manager/room-mappings/auto-map`

**Request Body:**
```json
{
  "otaCode": "DUMMY"
}
```

**Response:**
```json
{
  "data": {
    "mappingsCreated": 5,
    "suggestions": [
      {
        "pmsRoomType": "Minimalist Studio",
        "pmsRoomTypeId": "rt-001",
        "pmsRoomName": "Minimalist Studio",
        "suggestedOTARoomType": "Studio Room",
        "suggestedOTARoomId": "STUDIO_ROOM",
        "confidence": 0.95
      }
    ]
  }
}
```

**Important Notes:**
- `mappingsCreated`: Number of mappings automatically created (high confidence)
- `suggestions`: Array of mappings that need user review (lower confidence or conflicts)
- If `mappingsCreated > 0`, those mappings should be immediately available
- If `suggestions.length > 0`, frontend will show them in a drawer for user approval

#### 7. Validate Room Mapping
**POST** `/api/v1/channel-manager/room-mappings/validate`

**Request Body:**
```json
{
  "pmsRoomTypeId": "rt-001",
  "otaCode": "DUMMY"
}
```

**Response:**
```json
{
  "data": {
    "valid": true,
    "errors": [],
    "warnings": ["Room type capacity mismatch"]
  }
}
```

#### 8. Get Room Types (from CMS)
**GET** `/api/v1/room-types`

**Response:**
```json
{
  "data": {
    "items": [
      {
        "id": "rt-001",
        "slug": "minimalist-studio",
        "name": "Minimalist Studio",
        "price": 150,
        "maxGuests": 2,
        "availableRoomCount": 10
      }
    ]
  }
}
```

---

## Tab 4: Rate Sync

### Required Endpoints

#### 1. Get Rate Calendar
**GET** `/api/v1/channel-manager/rates/calendar?startDate={start}&endDate={end}&roomTypeId={id}&otaCode={code}`

**Query Parameters:**
- `startDate`: Start date (ISO 8601, e.g., "2025-01-23")
- `endDate`: End date (ISO 8601, e.g., "2025-02-23")
- `roomTypeId` (optional): Filter by room type ID
- `otaCode` (optional): Filter by OTA code

**Response:**
```json
{
  "data": {
    "calendar": {
      "2025-01-23": {
        "Minimalist Studio": {
          "date": "2025-01-23",
          "roomType": "Minimalist Studio",
          "rates": {
            "BAR": 150,
            "Corporate": 135,
            "OTA": 135
          },
          "otaRates": {
            "DUMMY": 150,
            "BOOKING": 155,
            "EXPEDIA": 152
          },
          "availability": 8,
          "stopSell": false,
          "cta": false,
          "ctd": false
        }
      }
    }
  }
}
```

**Important Notes:**
- `rates` contains base rate plans (BAR, Corporate, OTA, etc.)
- `otaRates` contains OTA-specific rates (keyed by OTA code)
- `availability` is the number of available rooms
- `stopSell`, `cta`, `ctd` are boolean flags for restrictions

#### 2. Update Rate
**PUT** `/api/v1/channel-manager/rates/calendar/{date}/{roomType}`

**URL Parameters:**
- `date`: Date in format "YYYY-MM-DD"
- `roomType`: Room type name (e.g., "Minimalist Studio")

**Request Body:**
```json
{
  "rates": {
    "BAR": 160
  },
  "otaRates": {
    "DUMMY": 165
  },
  "availability": 7,
  "stopSell": false,
  "cta": false,
  "ctd": false
}
```

**Response:** Updated rate calendar entry

#### 3. Push Rates to OTAs
**POST** `/api/v1/channel-manager/rates/push`

**Request Body:**
```json
{
  "otaCodes": ["DUMMY", "BOOKING"],
  "dateRange": {
    "start": "2025-01-23",
    "end": "2025-02-23"
  },
  "roomTypeIds": ["rt-001", "rt-002"]
}
```

**Special Values:**
- `otaCodes: ["ALL"]` → Push to all connected OTAs
- `roomTypeIds: ["ALL"]` → Push all room types

**Response:**
```json
{
  "data": {
    "syncId": "sync-123",
    "status": "pending"
  }
}
```

#### 4. Pull Rates from OTAs
**POST** `/api/v1/channel-manager/rates/pull`

**Request Body:** Same as push rates

**Response:** Same as push rates

#### 5. Get Rate Parity Issues
**GET** `/api/v1/channel-manager/rates/parity?date={date}&threshold={threshold}`

**Query Parameters (optional):**
- `date`: Specific date to check (default: today)
- `threshold`: Percentage threshold for parity (default: 10)

**Response:**
```json
{
  "data": {
    "issues": [
      {
        "date": "2025-01-23",
        "roomType": "Minimalist Studio",
        "minRate": 150,
        "maxRate": 180,
        "difference": 30,
        "otas": ["DUMMY", "BOOKING"]
      }
    ]
  }
}
```

---

## Tab 5: Restrictions

### Required Endpoints

#### 1. Get All Restrictions
**GET** `/api/v1/channel-manager/restrictions?status={status}&roomType={type}&otaCode={code}&dateFrom={from}&dateTo={to}`

**Query Parameters (all optional):**
- `status`: `"active"` | `"inactive"` | `"all"` (default: "all")
- `roomType`: Filter by room type name
- `otaCode`: Filter by OTA code
- `dateFrom`: Start date filter (ISO 8601)
- `dateTo`: End date filter (ISO 8601)

**Response:**
```json
{
  "data": {
    "items": [
      {
        "id": "restriction-001",
        "roomType": "Minimalist Studio",
        "otaCode": "DUMMY",
        "dateRange": {
          "start": "2025-01-25",
          "end": "2025-01-27"
        },
        "restriction": {
          "minStay": 2,
          "maxStay": null,
          "cta": false,
          "ctd": false,
          "stopSell": true
        },
        "reason": "Maintenance period",
        "isActive": true,
        "createdAt": "2025-01-20T10:00:00Z",
        "createdBy": "admin@example.com"
      }
    ],
    "total": 12
  }
}
```

**Important Notes:**
- `roomType: "ALL"` means restriction applies to all room types
- `otaCode: "ALL"` means restriction applies to all OTAs
- `restriction.stopSell: true` means no bookings allowed
- `restriction.cta: true` means closed to arrival (no check-ins)
- `restriction.ctd: true` means closed to departure (no check-outs)
- `restriction.minStay` is minimum nights required
- `restriction.maxStay` is maximum nights allowed (null = no limit)

#### 2. Get Specific Restriction
**GET** `/api/v1/channel-manager/restrictions/{id}`

**Response:** Single restriction object

#### 3. Create Restriction
**POST** `/api/v1/channel-manager/restrictions`

**Request Body:**
```json
{
  "roomType": "Minimalist Studio",
  "otaCode": "DUMMY",
  "dateRange": {
    "start": "2025-01-25",
    "end": "2025-01-27"
  },
  "restriction": {
    "minStay": 2,
    "maxStay": null,
    "cta": false,
    "ctd": false,
    "stopSell": true
  },
  "reason": "Maintenance period"
}
```

**Response:** Created restriction object

#### 4. Update Restriction
**PUT** `/api/v1/channel-manager/restrictions/{id}`

**Request Body:** Partial restriction object

**Response:** Updated restriction object

#### 5. Delete Restriction
**DELETE** `/api/v1/channel-manager/restrictions/{id}`

**Response:** `204 No Content`

#### 6. Toggle Restriction Status
**PUT** `/api/v1/channel-manager/restrictions/{id}/toggle`

**Response:**
```json
{
  "data": {
    "isActive": false
  }
}
```

---

## Tab 6: Promotions

### Required Endpoints

#### 1. Get All Promotions
**GET** `/api/v1/channel-manager/promotions?status={status}&otaCode={code}`

**Query Parameters (optional):**
- `status`: `"active"` | `"scheduled"` | `"expired"` | `"inactive"` | `"all"` (default: "all")
- `otaCode`: Filter by OTA code

**Response:**
```json
{
  "data": {
    "items": [
      {
        "id": "promo-001",
        "name": "Winter Special",
        "description": "20% off for winter bookings",
        "discountType": "percentage",
        "discountValue": 20,
        "validFrom": "2025-01-01",
        "validTo": "2025-02-28",
        "otaCodes": ["DUMMY", "BOOKING"],
        "roomTypes": ["Minimalist Studio", "Coastal Retreat"],
        "minStay": 2,
        "bookingWindow": {
          "start": "2025-01-01",
          "end": "2025-01-31"
        },
        "usageCount": 45,
        "isActive": true,
        "createdAt": "2024-12-15T10:00:00Z",
        "updatedAt": "2025-01-20T10:00:00Z"
      }
    ],
    "total": 5
  }
}
```

**Important Notes:**
- `otaCodes: ["ALL"]` means promotion applies to all OTAs
- `roomTypes: ["ALL"]` means promotion applies to all room types
- `discountType`: `"percentage"` or `"fixed"` (fixed amount)
- `usageCount`: Number of times promotion has been used
- `bookingWindow`: Optional window for when bookings can be made (not stay dates)

#### 2. Get Specific Promotion
**GET** `/api/v1/channel-manager/promotions/{id}`

**Response:** Single promotion object

#### 3. Create Promotion
**POST** `/api/v1/channel-manager/promotions`

**Request Body:**
```json
{
  "name": "Winter Special",
  "description": "20% off for winter bookings",
  "discountType": "percentage",
  "discountValue": 20,
  "validFrom": "2025-01-01",
  "validTo": "2025-02-28",
  "otaCodes": ["DUMMY", "BOOKING"],
  "roomTypes": ["Minimalist Studio"],
  "minStay": 2,
  "bookingWindow": {
    "start": "2025-01-01",
    "end": "2025-01-31"
  }
}
```

**Response:** Created promotion object

#### 4. Update Promotion
**PUT** `/api/v1/channel-manager/promotions/{id}`

**Request Body:** Partial promotion object

**Response:** Updated promotion object

#### 5. Delete Promotion
**DELETE** `/api/v1/channel-manager/promotions/{id}`

**Response:** `204 No Content`

#### 6. Toggle Promotion Status
**PUT** `/api/v1/channel-manager/promotions/{id}/toggle`

**Response:**
```json
{
  "data": {
    "isActive": false
  }
}
```

#### 7. Apply Promotion to OTAs
**POST** `/api/v1/channel-manager/promotions/{id}/apply`

**Request Body:**
```json
{
  "otaCodes": ["DUMMY", "BOOKING"]
}
```

**Response:** `204 No Content`

---

## Tab 7: Sync Logs

### Required Endpoints

#### 1. Get Sync Logs
**GET** `/api/v1/channel-manager/sync-logs?otaCode={code}&action={action}&status={status}&dateFrom={from}&dateTo={to}&page={page}&pageSize={size}`

**Query Parameters (all optional):**
- `otaCode`: Filter by OTA code
- `action`: Filter by action type (`rate_update`, `availability_update`, `restriction_update`, `promotion_sync`, `booking_import`, `connection`, `bulk_sync`)
- `status`: Filter by status (`success`, `error`, `warning`, `pending`)
- `dateFrom`: Start date filter (ISO 8601)
- `dateTo`: End date filter (ISO 8601)
- `page`: Page number (default: 1)
- `pageSize`: Items per page (default: 50)

**Response:**
```json
{
  "data": {
    "items": [
      {
        "id": "log-001",
        "timestamp": "2025-01-23T10:30:00Z",
        "otaCode": "DUMMY",
        "otaName": "Dummy Channel Manager",
        "action": "rate_update",
        "status": "success",
        "message": "Rates synced successfully for all room types",
        "details": {
          "roomTypes": ["Minimalist Studio", "Coastal Retreat"],
          "dateRange": "30 days",
          "changesCount": 120
        }
      }
    ],
    "total": 250,
    "page": 1,
    "pageSize": 50,
    "totalPages": 5
  }
}
```

**Important Notes:**
- `action` values:
  - `rate_update`: Rate synchronization
  - `availability_update`: Availability/inventory sync
  - `restriction_update`: Restriction changes
  - `promotion_sync`: Promotion application
  - `booking_import`: Booking import from OTA
  - `connection`: Connection/disconnection events
  - `bulk_sync`: Bulk synchronization
- `status` values: `success`, `error`, `warning`, `pending`
- `details` is a flexible object that can contain any relevant information

#### 2. Get Specific Sync Log
**GET** `/api/v1/channel-manager/sync-logs/{id}`

**Response:** Single sync log object

#### 3. Clear All Sync Logs
**DELETE** `/api/v1/channel-manager/sync-logs`

**Response:** `204 No Content`

#### 4. Export Sync Logs
**GET** `/api/v1/channel-manager/sync-logs/export?format={format}&otaCode={code}&action={action}&status={status}`

**Query Parameters:**
- `format`: `"csv"` | `"excel"` | `"pdf"` (default: "csv")
- Other filters same as GET sync logs

**Response:** Blob (file download)
- CSV: `text/csv`
- Excel: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- PDF: `application/pdf`

---

## Common Requirements

### Authentication
All endpoints require authentication via Bearer token:
```
Authorization: Bearer <token>
```

### Error Responses
All endpoints should return errors in this format:
```json
{
  "error": "Error message",
  "detail": "Detailed error description"
}
```

### Pagination
Endpoints that support pagination should return:
```json
{
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "pageSize": 50,
    "totalPages": 2
  }
}
```

### Response Format
All successful responses should follow:
```json
{
  "data": { ... }
}
```

Or for paginated responses:
```json
{
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "pageSize": 50,
    "totalPages": 2
  }
}
```

---

## OTA to Booking Source Mapping

**CRITICAL:** The backend must map OTA codes to booking sources when calculating statistics:

| OTA Code | Booking Source |
|----------|----------------|
| `DUMMY` | `CRS` |
| `BOOKING` | `Booking.com` |
| `EXPEDIA` | `Expedia` |
| `AGODA` | `Agoda` |
| `MMT` | `MakeMyTrip` |
| `TRIP` | `Trip.com` |
| `GOOGLE` | `Google Hotel Ads` |

**Implementation Example:**
```typescript
const otaSourceMap = {
  'DUMMY': 'CRS',
  'BOOKING': 'Booking.com',
  'EXPEDIA': 'Expedia',
  // ... etc
};

// When calculating stats for an OTA:
const bookingSource = otaSourceMap[otaCode] || otaCode;
const bookings = await db.bookings.findMany({
  where: { source: bookingSource }
});
```

---

## Database Tables Required

The backend should have the following tables (or equivalent):

1. **`ota_connections`** - Stores OTA connection details
2. **`room_mappings`** - Stores PMS to OTA room type mappings
3. **`rate_calendar`** - Stores rate and availability data per date/room/OTA
4. **`restrictions`** - Stores booking restrictions
5. **`promotions`** - Stores channel promotions
6. **`sync_logs`** - Stores sync activity logs
7. **`bookings`** - Existing bookings table (used for stats)

---

## Missing APIs Summary

### Already Implemented in Frontend Service
All APIs are already defined in `src/api/services/channel-manager.service.ts` and are being called from the context.

### Missing Context Functions (Now Added)
The following functions were missing from `ChannelManagerContext` but have now been added:
- ✅ `updateChannelPromotion()` - Uses `PUT /api/v1/channel-manager/promotions/{id}`
- ✅ `deleteChannelPromotion()` - Uses `DELETE /api/v1/channel-manager/promotions/{id}`
- ✅ `toggleChannelPromotion()` - Uses `PUT /api/v1/channel-manager/promotions/{id}/toggle`

---

## Testing Checklist

For each endpoint, verify:
- [ ] Authentication is required
- [ ] Proper error handling (400, 401, 404, 500)
- [ ] Response format matches specification
- [ ] Pagination works correctly (where applicable)
- [ ] Filters work correctly (where applicable)
- [ ] OTA to booking source mapping is correct
- [ ] Real-time updates trigger SSE events
- [ ] Data is persisted in database

---

## Next Steps for Backend

1. **Implement all endpoints** listed in this document
2. **Set up database tables** for channel manager data
3. **Implement OTA to booking source mapping** in stats endpoint
4. **Set up SSE events** for real-time updates (see `FRONTEND_SSE_INTEGRATION.md`)
5. **Test with dummy channel manager** to ensure data flows correctly
