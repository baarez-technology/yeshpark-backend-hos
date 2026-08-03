# Reservation JSON Input Examples

This document provides various JSON input examples for creating reservations via the API.

## Basic Reservation (Minimum Required Fields)

```json
{
  "guest": {
    "first_name": "Prince",
    "last_name": "kumar",
    "email": "princetripathi087@gmail.com",
    "phone": "999999999"
  },
  "arrival_date": "2026-01-19",
  "departure_date": "2026-01-20",
  "adults": 1
}
```

## Complete Reservation (All Fields)

```json
{
  "guest": {
    "first_name": "Prince",
    "last_name": "kumar",
    "email": "princetripathi087@gmail.com",
    "phone": "999999999",
    "notes": "VIP guest, prefers high floor"
  },
  "rate_plan_id": 1,
  "arrival_date": "2026-01-19",
  "departure_date": "2026-01-20",
  "adults": 2,
  "children": 1,
  "special_requests": "Early check-in preferred, late checkout if possible",
  "group_code": "CORP-2026-001",
  "promo_code": "SUMMER2026",
  "room_id": 5
}
```

## Family Reservation (With Children)

```json
{
  "guest": {
    "first_name": "John",
    "last_name": "Smith",
    "email": "john.smith@example.com",
    "phone": "+1-555-123-4567",
    "notes": "Traveling with family, needs connecting rooms"
  },
  "rate_plan_id": 2,
  "arrival_date": "2026-02-15",
  "departure_date": "2026-02-20",
  "adults": 2,
  "children": 2,
  "special_requests": "Need crib for infant, high chair for toddler",
  "room_id": null
}
```

## Business Traveler Reservation

```json
{
  "guest": {
    "first_name": "Sarah",
    "last_name": "Johnson",
    "email": "sarah.johnson@company.com",
    "phone": "+1-555-987-6543",
    "notes": "Corporate account, frequent guest"
  },
  "rate_plan_id": 3,
  "arrival_date": "2026-03-10",
  "departure_date": "2026-03-12",
  "adults": 1,
  "children": 0,
  "special_requests": "Quiet room, business center access needed",
  "group_code": "CORP-ACME-2026",
  "room_id": null
}
```

## Extended Stay Reservation

```json
{
  "guest": {
    "first_name": "Michael",
    "last_name": "Brown",
    "email": "michael.brown@example.com",
    "phone": "555-111-2222",
    "notes": "Extended stay guest, monthly rate preferred"
  },
  "rate_plan_id": 4,
  "arrival_date": "2026-04-01",
  "departure_date": "2026-04-30",
  "adults": 1,
  "children": 0,
  "special_requests": "Weekly housekeeping, kitchenette preferred",
  "room_id": null
}
```

## Group Booking Reservation

```json
{
  "guest": {
    "first_name": "David",
    "last_name": "Wilson",
    "email": "david.wilson@events.com",
    "phone": "+1-555-444-3333",
    "notes": "Group leader for wedding party"
  },
  "rate_plan_id": 5,
  "arrival_date": "2026-05-15",
  "departure_date": "2026-05-18",
  "adults": 2,
  "children": 0,
  "special_requests": "Part of wedding group, needs room near other guests",
  "group_code": "WEDDING-2026-001",
  "promo_code": "GROUP10",
  "room_id": null
}
```

## Honeymoon Reservation

```json
{
  "guest": {
    "first_name": "Emily",
    "last_name": "Davis",
    "email": "emily.davis@example.com",
    "phone": "555-777-8888",
    "notes": "Honeymoon couple, celebrating anniversary"
  },
  "rate_plan_id": 6,
  "arrival_date": "2026-06-01",
  "departure_date": "2026-06-07",
  "adults": 2,
  "children": 0,
  "special_requests": "Romantic room with view, champagne on arrival",
  "promo_code": "HONEYMOON2026",
  "room_id": null
}
```

## Reservation with Promo Code

```json
{
  "guest": {
    "first_name": "Lisa",
    "last_name": "Anderson",
    "email": "lisa.anderson@example.com",
    "phone": "555-999-0000"
  },
  "rate_plan_id": 1,
  "arrival_date": "2026-07-10",
  "departure_date": "2026-07-15",
  "adults": 2,
  "children": 0,
  "special_requests": "Early check-in",
  "promo_code": "SUMMER2026",
  "room_id": null
}
```

## Reservation with Specific Room Assignment

```json
{
  "guest": {
    "first_name": "Robert",
    "last_name": "Taylor",
    "email": "robert.taylor@example.com",
    "phone": "555-222-3333",
    "notes": "Returning guest, prefers room 101"
  },
  "rate_plan_id": 2,
  "arrival_date": "2026-08-20",
  "departure_date": "2026-08-25",
  "adults": 1,
  "children": 0,
  "special_requests": "Same room as last visit if available",
  "room_id": 101
}
```

## Field Descriptions

### Guest Object
- **first_name** (required): Guest's first name
- **last_name** (required): Guest's last name
- **email** (optional): Guest's email address
- **phone** (optional): Guest's phone number
- **notes** (optional): Additional notes about the guest

### Reservation Fields
- **rate_plan_id** (optional): ID of the rate plan to use (0 = default)
- **arrival_date** (required): Check-in date in YYYY-MM-DD format
- **departure_date** (required): Check-out date in YYYY-MM-DD format
- **adults** (required): Number of adult guests
- **children** (optional): Number of children (default: 0)
- **special_requests** (optional): Special requests or notes
- **group_code** (optional): Group booking code
- **promo_code** (optional): Promotional code for discounts
- **room_id** (optional): Specific room ID to assign (null = auto-assign)

## Date Format

All dates must be in **ISO 8601 format**: `YYYY-MM-DD`

Examples:
- ✅ `"2026-01-19"` (correct)
- ❌ `"01/19/2026"` (incorrect)
- ❌ `"19-01-2026"` (incorrect)
- ❌ `"2026-1-19"` (incorrect - must use zero-padded months/days)

## Validation Rules

1. **arrival_date** must be before **departure_date**
2. **adults** must be at least 1
3. **children** must be 0 or greater
4. **guest.first_name** and **guest.last_name** are required
5. Dates must be valid calendar dates

## Example cURL Commands

### Basic Reservation
```bash
curl -X POST http://localhost:8000/api/v1/reservations \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "guest": {
      "first_name": "Prince",
      "last_name": "kumar",
      "email": "princetripathi087@gmail.com",
      "phone": "999999999"
    },
    "arrival_date": "2026-01-19",
    "departure_date": "2026-01-20",
    "adults": 1
  }'
```

### Complete Reservation
```bash
curl -X POST http://localhost:8000/api/v1/reservations \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
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
    "room_id": 1
  }'
```

## Example PowerShell Commands

### Basic Reservation
```powershell
$reservation = @{
    guest = @{
        first_name = "Prince"
        last_name = "kumar"
        email = "princetripathi087@gmail.com"
        phone = "999999999"
    }
    arrival_date = "2026-01-19"
    departure_date = "2026-01-20"
    adults = 1
} | ConvertTo-Json -Depth 10

$headers = @{
    Authorization = "Bearer YOUR_TOKEN"
    "Content-Type" = "application/json"
}

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/reservations" `
    -Method Post `
    -Body $reservation `
    -Headers $headers
```

## Common Error Responses

### Missing Required Field
```json
{
  "detail": "Guest first_name and last_name are required"
}
```

### Invalid Date Range
```json
{
  "detail": "departure_date must be after arrival_date"
}
```

### Not Authenticated
```json
{
  "detail": "Not authenticated"
}
```

### Room Not Available
```json
{
  "detail": "Fully booked. Added to waitlist. Available rooms: 0"
}
```
