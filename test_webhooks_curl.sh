#!/bin/bash
# Comprehensive Webhook Testing Script
# Tests all webhook-triggering APIs from dummy_channel_manager to glimmora-backend

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Webhook Connectivity Test Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Configuration
CHANNEL_MANAGER_URL="http://localhost:8001"
BACKEND_URL="http://localhost:8000"

echo -e "${YELLOW}Configuration:${NC}"
echo "  Channel Manager: $CHANNEL_MANAGER_URL"
echo "  Glimmora Backend: $BACKEND_URL"
echo ""

# Step 1: Check if webhook URL is configured
echo -e "${BLUE}[1/7] Checking webhook configuration...${NC}"
WEBHOOK_STATUS=$(curl -s "$CHANNEL_MANAGER_URL/api/webhooks/status")
echo "$WEBHOOK_STATUS" | python -m json.tool
echo ""

# Step 2: Configure webhook URL if needed
echo -e "${BLUE}[2/7] Configuring webhook URL...${NC}"
CONFIGURE_RESPONSE=$(curl -s -X POST "$CHANNEL_MANAGER_URL/api/webhooks/configure" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"$BACKEND_URL/api/v1/webhooks/channel-manager\"}")
echo "$CONFIGURE_RESPONSE" | python -m json.tool
echo ""

# Step 3: Create a reservation (triggers booking.created webhook)
echo -e "${BLUE}[3/7] Creating reservation (booking.created webhook)...${NC}"
CREATED_RESPONSE=$(curl -s -X POST "$CHANNEL_MANAGER_URL/api/v2/reservations" \
  -H "Content-Type: application/json" \
  -d '{
    "hotel_id": null,
    "room_id": 1,
    "rate_plan_id": 0,
    "arrival_date": "2024-12-20",
    "departure_date": "2024-12-23",
    "adults": 2,
    "children": 0,
    "guest": {
      "first_name": "John",
      "last_name": "Doe",
      "email": "john.doe@example.com",
      "phone": "+1234567890",
      "notes": "Test booking"
    },
    "special_requests": "Early check-in preferred"
  }')

echo "$CREATED_RESPONSE" | python -m json.tool
RESERVATION_ID=$(echo "$CREATED_RESPONSE" | python -c "import sys, json; data=json.load(sys.stdin); print(data.get('data', {}).get('id', ''))" 2>/dev/null)
echo -e "${GREEN}✓ Reservation created: $RESERVATION_ID${NC}"
echo -e "${YELLOW}Wait 2 seconds for webhook to be sent...${NC}"
sleep 2
echo ""

# Step 4: Modify the reservation (triggers booking.modified webhook)
if [ ! -z "$RESERVATION_ID" ]; then
  echo -e "${BLUE}[4/7] Modifying reservation (booking.modified webhook)...${NC}"
  MODIFIED_RESPONSE=$(curl -s -X PUT "$CHANNEL_MANAGER_URL/api/reservations/$RESERVATION_ID" \
    -H "Content-Type: application/json" \
    -d '{
      "check_out": "2024-12-24",
      "special_requests": "Late checkout preferred"
    }')
  echo "$MODIFIED_RESPONSE" | python -m json.tool
  echo -e "${GREEN}✓ Reservation modified${NC}"
  echo -e "${YELLOW}Wait 2 seconds for webhook to be sent...${NC}"
  sleep 2
  echo ""
else
  echo -e "${RED}⚠ Skipping modify test (no reservation ID)${NC}"
  echo ""
fi

# Step 5: Trigger availability webhook
echo -e "${BLUE}[5/7] Triggering availability.updated webhook...${NC}"
AVAILABILITY_RESPONSE=$(curl -s -X POST "$CHANNEL_MANAGER_URL/api/webhooks/trigger/availability?ota_connection_id=1")
echo "$AVAILABILITY_RESPONSE" | python -m json.tool
echo -e "${GREEN}✓ Availability webhook triggered${NC}"
echo -e "${YELLOW}Wait 2 seconds for webhook to be sent...${NC}"
sleep 2
echo ""

# Step 6: Trigger sync status webhook
echo -e "${BLUE}[6/7] Triggering sync.status webhook...${NC}"
SYNC_RESPONSE=$(curl -s -X POST "$CHANNEL_MANAGER_URL/api/webhooks/trigger/sync-status?ota_connection_id=1&connection_status=connected&sync_type=full&records_processed=150&records_failed=0")
echo "$SYNC_RESPONSE" | python -m json.tool
echo -e "${GREEN}✓ Sync status webhook triggered${NC}"
echo -e "${YELLOW}Wait 2 seconds for webhook to be sent...${NC}"
sleep 2
echo ""

# Step 7: Cancel the reservation (triggers booking.cancelled webhook)
if [ ! -z "$RESERVATION_ID" ]; then
  echo -e "${BLUE}[7/7] Cancelling reservation (booking.cancelled webhook)...${NC}"
  CANCELLED_RESPONSE=$(curl -s -X DELETE "$CHANNEL_MANAGER_URL/api/reservations/$RESERVATION_ID")
  echo "$CANCELLED_RESPONSE" | python -m json.tool
  echo -e "${GREEN}✓ Reservation cancelled${NC}"
  echo -e "${YELLOW}Wait 2 seconds for webhook to be sent...${NC}"
  sleep 2
  echo ""
else
  echo -e "${RED}⚠ Skipping cancel test (no reservation ID)${NC}"
  echo ""
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ All tests completed!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Please check the logs from both servers:${NC}"
echo "  1. Channel Manager (localhost:8001) - Look for [WEBHOOK] messages"
echo "  2. Glimmora Backend (localhost:8000) - Look for [WEBHOOK RECEIVER] messages"
echo ""
