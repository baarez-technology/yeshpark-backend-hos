# CRS Simulator API

A production-like mock Central Reservation System (CRS) / Channel Manager API designed for Hotel AI applications. This simulator mimics the behavior of real CRS systems like **STAAH**, **SiteMinder**, and **Cloudbeds** without requiring any third-party APIs or API keys.

## Overview

This CRS Simulator provides a complete in-memory mock of hotel distribution systems, enabling AI applications to:
- Test hotel booking workflows
- Develop and test integrations before connecting to real CRS vendors
- Simulate realistic hotel operations (rates, inventory, reservations)
- Receive webhook events similar to production systems

## Features

### ✅ Core Functionality

- **Hotel & Room Management**: Create hotels and define room types with capacity and occupancy limits
- **Rate Management**: Support for multiple rate plans (BAR, Non-Refundable, Corporate, Promotional, Long-Stay)
  - Base rates per room type
  - Date-wise pricing overrides
  - Weekday/weekend multipliers
  - Rate plan-specific pricing
- **Inventory & Availability**: Real-time inventory tracking with overbooking prevention
- **Reservation Operations**: Full CRUD operations for bookings
  - Create, modify, cancel reservations
  - CRS-style confirmation numbers (e.g., `HRS-2024-A1B2C3`)
  - Reservation status tracking
- **CRS-Style Endpoints**: Vendor-like API endpoints (`/crs/*`) matching real CRS patterns
- **Webhook Simulation**: Asynchronous webhook events for booking lifecycle events
- **AI-Friendly Responses**: Structured responses with metadata and confidence indicators
- **Comprehensive Error Handling**: Validates date ranges, inventory availability, and prevents overbooking

## Quick Start

### Installation

1. **Clone or download this repository**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

### Running the API

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will start on `http://localhost:8000` with:
- **Interactive API docs**: `http://localhost:8000/docs`
- **ReDoc documentation**: `http://localhost:8000/redoc`
- **Health check**: `http://localhost:8000/health`

### Seed Data

The simulator automatically seeds realistic dummy data on startup:
- 3 hotels (Grand Plaza Hotel, Oceanview Resort, Metropolitan Business Hotel)
- Multiple room types per hotel (Standard King, Deluxe Suite, Ocean View, etc.)
- Various rate plans (BAR, Non-Refundable, Corporate)
- Sample reservation
- Inventory initialized for 90 days ahead

## API Endpoints

### Hotel Management

- `POST /api/hotels` - Create a new hotel
- `GET /api/hotels` - List all hotels
- `GET /api/hotels/{hotel_id}` - Get hotel details

### Room Type Management

- `POST /api/hotels/{hotel_id}/rooms` - Create room type
- `GET /api/hotels/{hotel_id}/rooms` - List room types for hotel
- `GET /api/rooms/{room_type_id}` - Get room type details

### Rate Management

- `POST /api/rates` - Create rate for a room type
- `GET /api/rates` - List rates (optionally filtered by room_type_id)
- `POST /api/rates/update` - Update rates for specific dates

### Availability & Inventory

- `GET /api/availability` - Check availability for date range
  - Parameters: `hotel_id`, `check_in`, `check_out`, `room_type_id` (optional), `rate_plan` (optional)

### Reservations

- `POST /api/reservations` - Create new reservation
- `GET /api/reservations/{reservation_id}` - Get reservation by ID or confirmation number
- `GET /api/reservations` - List reservations (filters: `hotel_id`, `room_type_id`, `status`)
- `PUT /api/reservations/{reservation_id}` - Modify reservation
- `DELETE /api/reservations/{reservation_id}` - Cancel reservation

### CRS-Style Endpoints (Vendor Simulation)

These endpoints mimic real CRS vendor APIs:

- `GET /crs/availability` - CRS-style availability check
- `POST /crs/rates` - CRS-style rate update
- `POST /crs/reservations` - CRS-style reservation creation
- `PUT /crs/reservations/{id}` - CRS-style reservation modification
- `DELETE /crs/reservations/{id}` - CRS-style reservation cancellation

## Usage Examples

### 1. Check Availability

```bash
curl -X GET "http://localhost:8000/api/availability?hotel_id=<hotel_id>&check_in=2024-01-15&check_out=2024-01-17"
```

Response includes available rooms per room type, rates for each rate plan, and AI-friendly metadata.

### 2. Create a Reservation

```bash
curl -X POST "http://localhost:8000/api/reservations" \
  -H "Content-Type: application/json" \
  -d '{
    "hotel_id": "<hotel_id>",
    "room_type_id": "<room_type_id>",
    "check_in": "2024-01-15",
    "check_out": "2024-01-17",
    "guest_name": "Jane Doe",
    "guest_email": "jane@example.com",
    "number_of_guests": 2,
    "rate_plan": "BAR",
    "total_amount": 300.0,
    "currency": "USD"
  }'
```

Response includes a CRS-style confirmation number (e.g., `HRS-2024-A1B2C3`).

### 3. CRS-Style Availability Check

```bash
curl -X GET "http://localhost:8000/crs/availability?hotel_id=<hotel_id>&check_in=2024-01-15&check_out=2024-01-17&rate_plan=BAR"
```

### 4. Update Rates for Specific Dates

```bash
curl -X POST "http://localhost:8000/api/rates/update" \
  -H "Content-Type: application/json" \
  -d '{
    "room_type_id": "<room_type_id>",
    "rate_plan": "BAR",
    "dates": ["2024-01-15", "2024-01-16"],
    "amount": 200.0,
    "currency": "USD"
  }'
```

### 5. Cancel Reservation

```bash
curl -X DELETE "http://localhost:8000/api/reservations/<reservation_id>"
```

This automatically releases inventory and triggers a `booking.cancelled` webhook event.

## Webhook Simulation

The simulator supports asynchronous webhook events that can be configured to POST JSON payloads to an external endpoint.

### Webhook Events

- `booking.created` - Triggered when a reservation is created
- `booking.modified` - Triggered when a reservation is modified
- `booking.cancelled` - Triggered when a reservation is cancelled

### Webhook Payload Structure

```json
{
  "event": "booking.created",
  "timestamp": "2024-01-15T10:30:00Z",
  "reservation_id": "<uuid>",
  "confirmation_number": "HRS-2024-A1B2C3",
  "hotel_id": "<uuid>",
  "room_type_id": "<uuid>",
  "check_in": "2024-01-15",
  "check_out": "2024-01-17",
  "status": "CONFIRMED",
  "data": {
    "guest_name": "Jane Doe",
    "total_amount": 300.0,
    "currency": "USD"
  }
}
```

### Configuring Webhooks

Currently, webhooks are disabled by default. To enable:

1. Set the `WEBHOOK_URL` environment variable, or
2. Modify `WEBHOOK_URL` in `main.py`

Future enhancement: Support webhook configuration via API endpoint.

## Rate Calculation Logic

The simulator implements realistic rate calculation:

1. **Specific Date Override**: If a date-specific rate exists, it takes precedence
2. **Weekend/Weekday Multiplier**: Applies multiplier based on day of week
   - Weekends (Saturday, Sunday): Uses `weekend_multiplier`
   - Weekdays: Uses `weekday_multiplier`
3. **Base Rate**: Falls back to base rate if no date-specific or multiplier rules apply

Example:
- Base rate: $150/night
- Weekend multiplier: 1.25
- Weekend night rate: $187.50
- Specific date override (Jan 15): $200 → uses $200

## Inventory Management

- Inventory is tracked per room type per date
- Creating a reservation reduces inventory by 1 for each night
- Canceling a reservation increases inventory by 1 for each night
- Overbooking is prevented: requests fail if inventory is exhausted
- Inventory is automatically initialized for 90 days ahead when room types are created

## Error Handling

The API returns structured error responses:

- **400 Bad Request**: Invalid date ranges, guest count exceeds occupancy
- **404 Not Found**: Hotel, room type, rate, or reservation not found
- **409 Conflict**: Inventory exhausted, cannot overbook
- **422 Validation Error**: Invalid request data

All errors include AI-friendly metadata with error codes and detailed messages.

## AI-Friendly Responses

All responses follow a consistent structure:

```json
{
  "success": true,
  "data": { /* response data */ },
  "metadata": {
    "source": "simulator",
    "confidence": "high",
    "timestamp": "2024-01-15T10:30:00Z"
  },
  "message": "Operation completed successfully"
}
```

This structure helps AI applications:
- Determine response source and confidence level
- Parse responses consistently
- Handle errors gracefully

## Architecture

### Data Storage

- **In-memory dictionaries**: All data stored in Python dicts (hotels_db, room_types_db, rates_db, reservations_db, inventory_db)
- **No persistence**: Data resets on server restart (designed for development/testing)
- **Extensible**: Can be replaced with database backend (PostgreSQL, MongoDB, etc.) without changing API contracts

### Code Structure

```
├── main.py          # FastAPI application with all endpoints
├── models.py        # Pydantic schemas for all data models
├── data.py          # In-memory data store and seed data
├── requirements.txt # Python dependencies
└── README.md        # This file
```

### Design Philosophy

This simulator is designed to be a **drop-in replacement** for real CRS integrations:
- API contracts match real CRS vendor patterns
- Response formats are consistent and structured
- Error handling mirrors production systems
- Webhook events follow industry standards

When ready to integrate with real CRS vendors (STAAH, SiteMinder, Cloudbeds), the same code structure can be adapted, with only the data layer and external API calls changing.

## Rate Plans Supported

- **BAR** (Best Available Rate): Standard flexible rate
- **NON_REFUNDABLE**: Discounted non-refundable rate
- **CORPORATE**: Corporate negotiated rates (often flat weekday/weekend)
- **PROMOTIONAL**: Special promotional rates
- **LONG_STAY**: Extended stay discounts

## Reservation Statuses

- **CONFIRMED**: Reservation is confirmed
- **MODIFIED**: Reservation was modified
- **CANCELLED**: Reservation is cancelled
- **CHECKED_IN**: (Reserved for future use)
- **CHECKED_OUT**: (Reserved for future use)

## Testing with AI Applications

This simulator is ideal for testing Hotel AI applications because:

1. **No API Keys Required**: Start immediately without vendor accounts
2. **Realistic Behavior**: Mimics real CRS inventory, rate, and booking logic
3. **Predictable Responses**: Consistent, structured responses for reliable testing
4. **Webhook Support**: Test webhook integration workflows
5. **Error Scenarios**: Test error handling (inventory exhaustion, invalid dates, etc.)

## Limitations & Future Enhancements

**Current Limitations:**
- In-memory storage (data resets on restart)
- Webhook URL requires code modification
- Single currency support (USD default)
- No authentication/authorization (designed for development)

**Potential Enhancements:**
- Database persistence (PostgreSQL, MongoDB)
- Webhook configuration API endpoint
- Multi-currency support
- Authentication/authorization (API keys, JWT)
- Bulk operations (batch rate updates, bulk availability)
- Reporting endpoints (occupancy reports, revenue analytics)
- Integration tests and CI/CD setup

## Contributing

This is a simulator/mock system. To extend:

1. Add new rate plan types in `models.py`
2. Enhance rate calculation logic in `main.py`
3. Add new webhook events in `models.py` and trigger in `main.py`
4. Extend seed data in `data.py`

## License

This is a development/testing tool. Use as needed for hotel AI application development.

## Support

For issues or questions about using this CRS Simulator:
1. Check the interactive API docs at `/docs`
2. Review example requests in this README
3. Examine seed data structure in `data.py`

---

**Built for Hotel AI Applications** | Simulating STAAH, SiteMinder, Cloudbeds behavior
