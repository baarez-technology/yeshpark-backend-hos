"""
Test script for Channel Manager Integration
Tests the integration between dummy channel manager and Glimmora backend.

Run this script to verify all integration points are working correctly.
"""
import asyncio
import httpx
import json
from datetime import date, datetime, timedelta

# Configuration
DUMMY_CHANNEL_MANAGER_URL = "http://localhost:8002"
GLIMMORA_BACKEND_URL = "http://localhost:8000"

async def test_endpoint(method: str, url: str, data: dict = None, description: str = ""):
    """Test an API endpoint"""
    print(f"\n{'='*80}")
    print(f"TEST: {description}")
    print(f"      {method} {url}")
    if data:
        print(f"      Body: {json.dumps(data, indent=2, default=str)}")
    print(f"{'='*80}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                response = await client.get(url)
            elif method == "POST":
                response = await client.post(url, json=data)
            elif method == "PUT":
                response = await client.put(url, json=data)
            elif method == "DELETE":
                response = await client.delete(url)
            else:
                print(f"ERROR: Unsupported method {method}")
                return None
            
            print(f"Status: {response.status_code}")
            try:
                result = response.json()
                print(f"Response: {json.dumps(result, indent=2, default=str)}")
                return result
            except:
                print(f"Response: {response.text}")
                return {"status_code": response.status_code, "text": response.text}
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        print(traceback.format_exc())
        return None

async def main():
    """Run all integration tests"""
    print("\n" + "="*80)
    print("CHANNEL MANAGER INTEGRATION TEST")
    print("="*80)
    print(f"Dummy Channel Manager: {DUMMY_CHANNEL_MANAGER_URL}")
    print(f"Glimmora Backend: {GLIMMORA_BACKEND_URL}")
    print("="*80)
    
    # Test 1: Check dummy channel manager health
    print("\n[TEST 1] Dummy Channel Manager Health Check")
    await test_endpoint("GET", f"{DUMMY_CHANNEL_MANAGER_URL}/health", description="Health check")
    
    # Test 2: Check Glimmora backend health
    print("\n[TEST 2] Glimmora Backend Health Check")
    await test_endpoint("GET", f"{GLIMMORA_BACKEND_URL}/health", description="Health check")
    
    # Test 3: Connect DUMMY OTA
    print("\n[TEST 3] Connect DUMMY OTA to Glimmora Backend")
    await test_endpoint("POST", f"{DUMMY_CHANNEL_MANAGER_URL}/api/ota/connect", description="Connect DUMMY OTA")
    
    # Test 4: Get DUMMY OTA status
    print("\n[TEST 4] Get DUMMY OTA Status")
    await test_endpoint("GET", f"{DUMMY_CHANNEL_MANAGER_URL}/api/ota/status", description="Get OTA status")
    
    # Test 5: List OTAs from Glimmora backend
    print("\n[TEST 5] List OTAs from Glimmora Backend")
    await test_endpoint("GET", f"{GLIMMORA_BACKEND_URL}/api/v1/channel-manager/otas", description="List OTAs")
    
    # Test 6: Test integration
    print("\n[TEST 6] Test Integration")
    await test_endpoint("POST", f"{DUMMY_CHANNEL_MANAGER_URL}/api/test/integration", description="Integration test")
    
    # Test 7: Get room types from Glimmora
    print("\n[TEST 7] Get Room Types from Glimmora Backend")
    await test_endpoint("GET", f"{GLIMMORA_BACKEND_URL}/api/v1/room-types", description="Get room types")
    
    # Test 8: Create a restriction
    print("\n[TEST 8] Create Restriction (syncs to Glimmora)")
    restriction_data = {
        "room_type_id": None,  # Will use first room type
        "restriction_date": (date.today() + timedelta(days=7)).isoformat(),
        "restriction_type": "stop_sell",
        "restriction_value": 1
    }
    # First get a room type
    rooms_result = await test_endpoint("GET", f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/rooms", description="Get rooms")
    if rooms_result and rooms_result.get("success") and rooms_result.get("data"):
        rooms = rooms_result["data"]
        if rooms:
            room_type_id = rooms[0].get("id")
            restriction_data["room_type_id"] = room_type_id
            await test_endpoint("POST", f"{DUMMY_CHANNEL_MANAGER_URL}/api/restrictions", restriction_data, description="Create restriction")
    
    # Test 9: Update rate (syncs to Glimmora)
    print("\n[TEST 9] Update Rate (syncs to Glimmora)")
    if rooms_result and rooms_result.get("success") and rooms_result.get("data"):
        rooms = rooms_result["data"]
        if rooms:
            room_type_id = rooms[0].get("id")
            rate_update = {
                "room_type_id": room_type_id,
                "rate_plan": "BAR",
                "dates": [(date.today() + timedelta(days=7)).isoformat()],
                "amount": 20750.0,
                "currency": "INR"
            }
            await test_endpoint("POST", f"{DUMMY_CHANNEL_MANAGER_URL}/api/rates/update", rate_update, description="Update rate")
    
    # Test 10: Simulate booking import
    print("\n[TEST 10] Simulate Booking Import (creates in Glimmora)")
    await test_endpoint("POST", f"{DUMMY_CHANNEL_MANAGER_URL}/api/bookings/import", {}, description="Import booking")
    
    # Test 11: Get sync logs
    print("\n[TEST 11] Get Sync Logs from Glimmora Backend")
    await test_endpoint("GET", f"{GLIMMORA_BACKEND_URL}/api/v1/channel-manager/sync-logs", description="Get sync logs")
    
    # Test 12: Get channel stats
    print("\n[TEST 12] Get Channel Stats from Glimmora Backend")
    await test_endpoint("GET", f"{GLIMMORA_BACKEND_URL}/api/v1/channel-manager/stats", description="Get stats")
    
    print("\n" + "="*80)
    print("INTEGRATION TEST COMPLETE")
    print("="*80)
    print("\nCheck the console logs for detailed information about each test.")
    print("All operations should show [GLIMMORA_API] and [WEBHOOK] log messages.")

if __name__ == "__main__":
    asyncio.run(main())
