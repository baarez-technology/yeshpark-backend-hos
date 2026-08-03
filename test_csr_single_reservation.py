"""
Simple test script to create a single reservation using the CSR v2 format
with the exact payload provided.
"""

import asyncio
import httpx
import json
from datetime import date, timedelta

# Configuration
DUMMY_CHANNEL_MANAGER_URL = "http://localhost:8001"


async def create_reservation():
    """Create a reservation using the v2 format"""
    
    # Calculate dates (7 days from today)
    arrival_date = (date.today() + timedelta(days=7)).isoformat()
    departure_date = (date.today() + timedelta(days=9)).isoformat()
    
    # Your exact payload (with dates filled in)
    reservation_data = {
        "guest": {
            "first_name": "tripathi",
            "last_name": "prince",
            "email": "pkumar@gmail.com",
            "phone": "9999999999",
            "notes": "notes"
        },
        "rate_plan_id": 0,  # BAR (Best Available Rate)
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "adults": 2,
        "children": 0,  # Room ID 1 has max_occupancy=2, so only 2 adults allowed
        "special_requests": "Early check-in preferred, late checkout if possible",
        "group_code": "CSR-TEST-001",
        "promo_code": "SUMMER2026",
        "room_id": 1
        # hotel_id is optional - will be inferred from room_id
    }
    
    print("=" * 80)
    print("CSR V2 Reservation Creation Test")
    print("=" * 80)
    print(f"\nEndpoint: POST {DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations")
    print(f"\nRequest Payload:")
    print(json.dumps(reservation_data, indent=2))
    print("\n" + "=" * 80)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
                json=reservation_data
            )
            
            print(f"\nStatus Code: {response.status_code}")
            print(f"\nResponse:")
            
            try:
                result = response.json()
                print(json.dumps(result, indent=2))
                
                if response.status_code == 200:
                    print("\n✓ SUCCESS: Reservation created successfully!")
                    if result.get("data"):
                        data = result["data"]
                        print(f"\nReservation Details:")
                        print(f"  ID: {data.get('id')}")
                        print(f"  Confirmation Number: {data.get('confirmation_number')}")
                        print(f"  Status: {data.get('status')}")
                        print(f"  Guest: {data.get('guest_name')}")
                        print(f"  Check-in: {data.get('check_in')}")
                        print(f"  Check-out: {data.get('check_out')}")
                        print(f"  Total Amount: {data.get('total_amount')} {data.get('currency', 'USD')}")
                else:
                    print(f"\n✗ ERROR: Reservation creation failed")
                    
            except json.JSONDecodeError:
                print(response.text)
                
    except httpx.ConnectError:
        print(f"\n✗ ERROR: Cannot connect to {DUMMY_CHANNEL_MANAGER_URL}")
        print("Make sure the dummy channel manager is running on port 8001")
        print("\nTo start it, run:")
        print("  cd dummy_channel_manager")
        print("  python main.py")
    except Exception as e:
        print(f"\n✗ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())


if __name__ == "__main__":
    asyncio.run(create_reservation())
