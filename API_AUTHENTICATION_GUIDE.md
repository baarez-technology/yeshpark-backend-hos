# API Authentication Guide

## Problem
When you try to create a reservation without authentication, you get:
```json
{
  "detail": "Not authenticated"
}
```

## Solution
You need to authenticate first to get an access token, then include it in your requests.

## Step-by-Step Guide

### Step 1: Login to Get Access Token

**Endpoint:** `POST /api/v1/auth/login`

**Request Body:**
```json
{
  "email": "admin@glimmora.com",
  "password": "admin123"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Example using curl:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@glimmora.com", "password": "admin123"}'
```

**Example using PowerShell:**
```powershell
$loginData = @{
    email = "admin@glimmora.com"
    password = "admin123"
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login" `
    -Method Post `
    -Body $loginData `
    -ContentType "application/json"

$token = $response.access_token
```

### Step 2: Use Token in Reservation Request

**Endpoint:** `POST /api/v1/reservations`

**Headers:**
```
Authorization: Bearer <your_access_token>
Content-Type: application/json
```

**Request Body:**
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
  "room_id": 1
}
```

**Example using curl:**
```bash
curl -X POST http://localhost:8000/api/v1/reservations \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE" \
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

**Example using PowerShell:**
```powershell
$reservationData = @{
    guest = @{
        first_name = "Prince"
        last_name = "kumar"
        email = "princetripathi087@gmail.com"
        phone = "999999999"
        notes = "notes"
    }
    rate_plan_id = 0
    arrival_date = "2026-01-19"
    departure_date = "2026-01-20"
    adults = 1
    children = 0
    special_requests = "Early check-in preferred"
    group_code = "string"
    promo_code = "string"
    room_id = 1
} | ConvertTo-Json -Depth 10

$headers = @{
    Authorization = "Bearer $token"
    "Content-Type" = "application/json"
}

$response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/reservations" `
    -Method Post `
    -Body $reservationData `
    -Headers $headers
```

## Default Login Credentials

Based on the seed scripts, here are the default credentials:

- **Admin:** `admin@glimmora.com` / `admin123`
- **Manager:** `manager@glimmora.com` / `password123`
- **Front Desk:** `frontdesk@glimmora.com` / `password123`
- **Guest:** `guest@example.com` / `password123`

## Using in Postman/Insomnia

1. **Create a Login Request:**
   - Method: `POST`
   - URL: `http://localhost:8000/api/v1/auth/login`
   - Body (JSON):
     ```json
     {
       "email": "admin@glimmora.com",
       "password": "admin123"
     }
     ```

2. **Extract Token:**
   - In Postman: Use Tests tab to save token:
     ```javascript
     var jsonData = pm.response.json();
     pm.environment.set("access_token", jsonData.access_token);
     ```

3. **Create Reservation Request:**
   - Method: `POST`
   - URL: `http://localhost:8000/api/v1/reservations`
   - Headers:
     - `Authorization: Bearer {{access_token}}`
     - `Content-Type: application/json`
   - Body: Your reservation JSON

## Token Expiration

Tokens expire after 60 minutes by default (configurable in `app/core/config.py`).

If you get authentication errors, simply login again to get a new token.

## Complete Example Script

See `test_reservation_auth.py` for a complete Python example that:
1. Authenticates
2. Gets the token
3. Creates a reservation
4. Shows the response

Run it with:
```bash
python test_reservation_auth.py
```
