"""
Quick test script to verify endpoints are working
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_rooms_endpoint():
    """Test rooms endpoint with various parameters"""
    print("\n=== Testing Rooms Endpoint ===")
    
    # Test 1: Basic list (should work)
    print("\n1. Testing basic list_rooms...")
    try:
        response = requests.get(f"{BASE_URL}/api/v1/rooms", params={"page": 1, "pageSize": 100})
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✓ Success: Found {len(data.get('items', []))} rooms")
        else:
            print(f"   ✗ Error: {response.text}")
    except Exception as e:
        print(f"   ✗ Exception: {e}")
    
    # Test 2: With invalid pageSize (should fail with 422)
    print("\n2. Testing with pageSize > 100 (should fail)...")
    try:
        response = requests.get(f"{BASE_URL}/api/v1/rooms", params={"page": 1, "pageSize": 1000})
        print(f"   Status: {response.status_code}")
        if response.status_code == 422:
            print(f"   ✓ Correctly rejected invalid pageSize")
        else:
            print(f"   ⚠ Unexpected status: {response.text}")
    except Exception as e:
        print(f"   ✗ Exception: {e}")
    
    # Test 3: With status parameter (should fail with 422)
    print("\n3. Testing with status parameter (should fail)...")
    try:
        response = requests.get(f"{BASE_URL}/api/v1/rooms", params={"page": 1, "pageSize": 100, "status": "clean"})
        print(f"   Status: {response.status_code}")
        if response.status_code == 422:
            print(f"   ✓ Correctly rejected invalid status parameter")
        else:
            print(f"   ⚠ Unexpected status: {response.text}")
    except Exception as e:
        print(f"   ✗ Exception: {e}")

def test_precheckin_status():
    """Test pre-checkin status update"""
    print("\n=== Testing Pre-Check-In Status ===")
    print("Note: This requires authentication and existing pre-checkin")
    print("Status should be 'completed' after submission")

if __name__ == "__main__":
    print("Testing Backend Endpoints")
    print("=" * 50)
    test_rooms_endpoint()
    test_precheckin_status()
    print("\n" + "=" * 50)
    print("Testing complete!")






