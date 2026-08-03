"""
Script to create room type mappings for the dummy channel manager.
This maps ROOM_1, ROOM_2, etc. to PMS room_type_id values.

Run this script after connecting the DUMMY OTA to create the necessary mappings.
"""

import asyncio
import httpx
import json
from typing import Dict, Any, Optional

# Configuration
GLIMMORA_BACKEND_URL = "http://localhost:8000"
DUMMY_OTA_CODE = "DUMMY"  # The OTA code used by dummy channel manager

# You'll need to get an auth token first
# Login to get token:
# POST http://localhost:8000/api/v1/auth/login
# Body: {"email": "admin@glimmora.local", "password": "admin123"}


async def create_room_mapping(
    token: str,
    room_type_id: int,
    ota_room_code: str,
    ota_room_name: str
) -> bool:
    """Create a room type mapping"""
    url = f"{GLIMMORA_BACKEND_URL}/api/v1/channel-manager/room-mappings"
    
    payload = {
        "otaCode": DUMMY_OTA_CODE,
        "pmsRoomTypeId": room_type_id,
        "otaRoomId": ota_room_code,
        "otaRoomType": ota_room_name
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                print(f"✓ Created mapping: {ota_room_code} -> room_type_id={room_type_id}")
                return True
            else:
                print(f"✗ Failed to create mapping: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
    except Exception as e:
        print(f"✗ Error creating mapping: {str(e)}")
        return False


async def get_room_types(token: str) -> Optional[list]:
    """Get all room types from PMS"""
    url = f"{GLIMMORA_BACKEND_URL}/api/v1/room-types"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                return result.get("data", [])
            else:
                print(f"✗ Failed to get room types: {response.status_code}")
                return None
    except Exception as e:
        print(f"✗ Error getting room types: {str(e)}")
        return None


async def login(email: str, password: str) -> Optional[str]:
    """Login and get access token"""
    url = f"{GLIMMORA_BACKEND_URL}/api/v1/auth/login"
    
    payload = {
        "email": email,
        "password": password
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                return result.get("access_token")
            else:
                print(f"✗ Login failed: {response.status_code}")
                print(f"  Response: {response.text}")
                return None
    except Exception as e:
        print(f"✗ Error logging in: {str(e)}")
        return None


async def main():
    """Create room type mappings for dummy channel manager"""
    print("=" * 80)
    print("Create Room Type Mappings for Dummy Channel Manager")
    print("=" * 80)
    
    # Login
    print("\n1. Logging in...")
    token = await login("admin@glimmora.local", "admin123")
    if not token:
        print("✗ Failed to login. Please check credentials.")
        return
    
    print("✓ Login successful")
    
    # Get room types
    print("\n2. Getting room types from PMS...")
    room_types = await get_room_types(token)
    if not room_types:
        print("✗ Failed to get room types")
        return
    
    print(f"✓ Found {len(room_types)} room types")
    
    # Create mappings
    # Dummy channel manager uses ROOM_1, ROOM_2, etc.
    # Map them to the first N room types
    print("\n3. Creating room type mappings...")
    print(f"   Mapping ROOM_1, ROOM_2, etc. to first {min(len(room_types), 10)} room types\n")
    
    mappings_created = 0
    for i, room_type in enumerate(room_types[:10], start=1):  # Map first 10 room types
        room_type_id = room_type.get("id")
        room_type_name = room_type.get("name", f"Room Type {i}")
        ota_room_code = f"ROOM_{i}"
        
        success = await create_room_mapping(
            token=token,
            room_type_id=room_type_id,
            ota_room_code=ota_room_code,
            ota_room_name=room_type_name
        )
        
        if success:
            mappings_created += 1
    
    print(f"\n{'=' * 80}")
    print(f"Summary: Created {mappings_created} room type mappings")
    print(f"{'=' * 80}\n")
    
    if mappings_created > 0:
        print("✓ Room type mappings created successfully!")
        print("\nYou can now test the reservation creation and webhooks should work.")
    else:
        print("✗ No mappings were created. Please check the errors above.")


if __name__ == "__main__":
    asyncio.run(main())
