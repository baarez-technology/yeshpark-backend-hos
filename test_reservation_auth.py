"""
Script to test reservation creation with authentication
"""
import requests
import json

# API base URL
BASE_URL = "http://localhost:8000"

# Step 1: Login to get access token
print("Step 1: Authenticating...")
login_data = {
    "email": "admin@glimmora.com",
    "password": "admin123"
}

response = requests.post(f"{BASE_URL}/api/v1/auth/login", json=login_data)
if response.status_code != 200:
    print(f"Login failed: {response.status_code}")
    print(response.text)
    exit(1)

token_data = response.json()
access_token = token_data["access_token"]
print("Authentication successful!")
print(f"Token: {access_token[:50]}...\n")

# Step 2: Create reservation with authentication
print("Step 2: Creating reservation...")
reservation_data = {
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

headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

response = requests.post(
    f"{BASE_URL}/api/v1/reservations",
    json=reservation_data,
    headers=headers
)

print(f"Status Code: {response.status_code}")
print(f"Response:")
print(json.dumps(response.json(), indent=2))

if response.status_code == 201:
    print("\nReservation created successfully!")
else:
    print("\nReservation creation failed")
