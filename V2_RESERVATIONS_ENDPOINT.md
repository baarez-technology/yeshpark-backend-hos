# V2 Reservations Endpoint Location

## Where is `POST /api/v2/reservations`?

The endpoint `POST http://localhost:8001/api/v2/reservations` is located in the **Dummy Channel Manager** service, which is a **separate FastAPI application** from the main Glimmora backend.

## Location in Codebase

**File:** `dummy_channel_manager/main.py`  
**Line:** ~1003  
**Port:** 8001 (different from main API which runs on 8000)

## What is the Dummy Channel Manager?

The Dummy Channel Manager is a **CRS Simulator** (Central Reservation System) that:
- Simulates real channel manager behavior (like STAAH, SiteMinder, Cloudbeds)
- Provides mock hotel booking APIs for testing
- Runs as a separate service on port 8001
- Used for testing integrations without real third-party APIs

## How to Run It

### Option 1: Run directly
```bash
cd dummy_channel_manager
python main.py
```

### Option 2: Run with uvicorn
```bash
cd dummy_channel_manager
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

The service will start on `http://localhost:8001`

## Endpoint Details

**URL:** `POST http://localhost:8001/api/v2/reservations`

**Request Body Format:**
```json
{
  "guest": {
    "first_name": "Prince",
    "last_name": "kumar",
    "email": "princetripathi087@gmail.com",
    "phone": "999999999",
    "notes": "notes"
  },
  "rate_plan_id": 0,
  "arrival_date": "2026-01-19",
  "departure_date": "2026-01-20",
  "adults": 1,
  "children": 0,
  "special_requests": "Early check-in preferred",
  "group_code": "string",
  "promo_code": "string",
  "room_id": 1,
  "hotel_id": "optional-uuid"
}
```

## Rate Plan IDs

- `0` = BAR (Best Available Rate)
- `1` = NON_REFUNDABLE
- `2` = CORPORATE
- `3` = PROMOTIONAL
- `4` = LONG_STAY

## Differences from Main API

| Feature | Main API (`/api/v1/reservations`) | Dummy Channel Manager (`/api/v2/reservations`) |
|---------|-----------------------------------|-----------------------------------------------|
| **Port** | 8000 | 8001 |
| **Authentication** | Required (Bearer token) | Not required |
| **Purpose** | Production hotel management | Testing/simulation |
| **Data Storage** | SQLite database | In-memory (resets on restart) |
| **Response Format** | Standard FastAPI response | AI-friendly structured response |

## Example Request

### Using curl:
```bash
curl -X POST http://localhost:8001/api/v2/reservations \
  -H "Content-Type: application/json" \
  -d '{
    "guest": {
      "first_name": "Prince",
      "last_name": "kumar",
      "email": "princetripathi087@gmail.com",
      "phone": "999999999"
    },
    "rate_plan_id": 0,
    "arrival_date": "2026-01-19",
    "departure_date": "2026-01-20",
    "adults": 1,
    "children": 0,
    "room_id": 1
  }'
```

### Using PowerShell:
```powershell
$reservation = @{
    guest = @{
        first_name = "Prince"
        last_name = "kumar"
        email = "princetripathi087@gmail.com"
        phone = "999999999"
    }
    rate_plan_id = 0
    arrival_date = "2026-01-19"
    departure_date = "2026-01-20"
    adults = 1
    children = 0
    room_id = 1
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8001/api/v2/reservations" `
    -Method Post `
    -Body $reservation `
    -ContentType "application/json"
```

## Response Format

The v2 endpoint returns an AI-friendly structured response:

```json
{
  "success": true,
  "data": {
    "id": "uuid-here",
    "confirmation_number": "HRS-2026-A1B2C3",
    "hotel_id": "uuid-here",
    "room_type_id": "uuid-here",
    "check_in": "2026-01-19",
    "check_out": "2026-01-20",
    "status": "CONFIRMED",
    "guest_name": "Prince kumar",
    "total_amount": 150.0,
    "currency": "USD"
  },
  "metadata": {
    "source": "simulator",
    "confidence": "high",
    "timestamp": "2026-01-15T10:30:00Z"
  },
  "message": "Reservation created successfully"
}
```

## Important Notes

1. **No Authentication Required**: Unlike the main API, this endpoint doesn't require authentication
2. **In-Memory Storage**: Data is stored in memory and resets when the service restarts
3. **Separate Service**: Must be running separately from the main API
4. **Testing Purpose**: Designed for testing and development, not production use
5. **Port 8001**: Make sure nothing else is using port 8001

## Checking if Service is Running

```bash
# Check if port 8001 is in use
netstat -ano | findstr :8001

# Test health endpoint
curl http://localhost:8001/health

# View API docs
# Open browser: http://localhost:8001/docs
```

## Related Endpoints

The dummy channel manager also provides:
- `GET /api/v2/rooms` - List available rooms
- `GET /api/availability` - Check availability
- `GET /api/reservations` - List reservations
- `PUT /api/reservations/{id}` - Modify reservation
- `DELETE /api/reservations/{id}` - Cancel reservation

See `dummy_channel_manager/README.md` for full API documentation.
