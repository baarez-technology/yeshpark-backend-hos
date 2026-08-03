import asyncio
import httpx
import json
import logging
from datetime import date, timedelta

# Configuration
GLIMMORA_BACKEND_URL = "http://localhost:8000"
DUMMY_CHANNEL_MANAGER_URL = "http://localhost:8002"

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def get_auth_token():
    """Authenticate and get access token"""
    async with httpx.AsyncClient() as client:
        try:
            logger.info("Authenticating with Glimmora Backend...")
            response = await client.post(
                f"{GLIMMORA_BACKEND_URL}/api/v1/auth/login",
                json={"email": "admin@glimmora.com", "password": "admin123"}
            )
            response.raise_for_status()
            token = response.json()["access_token"]
            logger.info("Authentication successful")
            return token
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return None

async def trigger_dummy_update():
    """Trigger a rate update on the Dummy Channel Manager to generate an SSE event"""
    async with httpx.AsyncClient() as client:
        try:
            # First get a room type to update
            logger.info("Fetching room types from Dummy CM...")
            rooms_resp = await client.get(f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/rooms")
            if rooms_resp.status_code != 200 or not rooms_resp.json().get("success"):
                logger.error("Failed to fetch room types")
                return False
            
            room_type_id = rooms_resp.json()["data"][0]["id"]
            
            # Trigger rate update
            logger.info(f"Triggering rate update for room type {room_type_id}...")
            update_data = {
                "room_type_id": room_type_id,
                "rate_plan": "BAR",
                "dates": [(date.today() + timedelta(days=10)).isoformat()],
                "amount": 25000.0,
                "currency": "INR"
            }
            
            resp = await client.post(
                f"{DUMMY_CHANNEL_MANAGER_URL}/api/rates/update",
                json=update_data
            )
            
            if resp.status_code == 200:
                logger.info("Rate update triggered successfully on Dummy CM")
                return True
            else:
                logger.error(f"Failed to trigger rate update: {resp.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error triggering update: {e}")
            return False

async def listen_for_sse(token):
    """Listen for SSE events"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream"
    }
    
    timeout = httpx.Timeout(30.0, read=30.0)
    
    logger.info("Connecting to SSE stream...")
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", f"{GLIMMORA_BACKEND_URL}/api/v1/webhooks/channel-manager/sse", headers=headers) as response:
            if response.status_code != 200:
                logger.error(f"Failed to connect to SSE stream: {response.status_code}")
                return False
            
            logger.info("Connected to SSE stream. Waiting for events...")
            
            # Start a background task to trigger the update after a short delay
            # ensuring we are listening before the event happens
            asyncio.create_task(delayed_trigger())
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        logger.info(f"Received SSE Event: {data['type']}")
                        
                        if data['type'] == 'rates.updated':
                            logger.info("SUCCESS: Received expected 'rates.updated' event!")
                            logger.info(f"Event Data: {json.dumps(data, indent=2)}")
                            return True
                            
                    except json.JSONDecodeError:
                        pass

async def delayed_trigger():
    """Wait a bit then trigger the update"""
    await asyncio.sleep(2)
    logger.info("Executing delayed trigger...")
    await trigger_dummy_update()

async def main():
    logger.info("Starting Channel Manager SSE Verification...")
    
    # 1. Authenticate
    token = await get_auth_token()
    if not token:
        logger.error("Aborting verification due to auth failure")
        return
    
    # 2. Connect to SSE and wait for event (trigger happens inside)
    try:
        success = await asyncio.wait_for(listen_for_sse(token), timeout=15.0)
        if success:
            logger.info("\n✅ VERIFICATION SUCCESSFUL: SSE connection established and real-time updates received.")
        else:
            logger.error("\n❌ VERIFICATION FAILED: Did not receive expected event.")
    except asyncio.TimeoutError:
        logger.error("\n❌ VERIFICATION FAILED: Timed out waiting for SSE event.")
    except Exception as e:
        logger.error(f"\n❌ VERIFICATION FAILED: An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
