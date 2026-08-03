# Channel Manager Webhooks - Testing Guide

This document provides step-by-step instructions to test the connectivity between dummy_channel_manager and glimmora-backend.

## Prerequisites

1. **Python 3.10+** installed
2. **Dependencies installed** for both projects:
   ```bash
   # In glimmora-backend
   pip install -r requirements.txt
   
   # In dummy_channel_manager
   cd dummy_channel_manager
   pip install -r requirements.txt
   ```

3. **Database setup** in glimmora-backend:
   - Ensure database is initialized
   - OTA connection exists (id=1)
   - Room mappings exist (OTA room codes → PMS room_type_id)
   - Rate mappings exist (OTA rate codes → PMS rate_plan_id)

## Test Setup

### Step 1: Start Glimmora Backend

```bash
# Terminal 1
cd glimmora-backend
uvicorn app.main:app --reload --port 8001
```

**Expected Output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8001
```

### Step 2: Start Dummy Channel Manager

```bash
# Terminal 2
cd glimmora-backend/dummy_channel_manager
python main.py
```

**Expected Output:**
```
CRS Simulator API started successfully!
[OK] Seeded 3 hotels
[OK] Seeded 6 room types
[OK] Seeded 9 rates
[OK] Seeded 1 reservations
INFO:     Started server process
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Step 3: Configure Webhook URL

```bash
# Terminal 3 (or use any HTTP client)
curl -X POST http://localhost:8000/api/webhooks/configure \
  -H "Content-Type: application/json" \
  -d '{"url": "http://localhost:8001/api/v1/webhooks/channel-manager"}'
```

**Expected Output in Terminal 2 (dummy_channel_manager):**
```
[No output, but webhook URL is now configured]
```

**Verify configuration:**
```bash
curl http://localhost:8000/api/webhooks/status
```

**Expected Response:**
```json
{
  "success": true,
  "data": {
    "webhook_url": "http://localhost:8001/api/v1/webhooks/channel-manager",
    "configured": true
  }
}
```

## Test Cases

### Test 1: Booking Created Webhook

**Objective:** Verify that creating a booking in dummy_channel_manager triggers a webhook that creates a booking in glimmora-backend.

**Steps:**

1. **Check initial booking count** (optional):
   ```bash
   # Check bookings in glimmora-backend via API or database
   ```

2. **Create a booking via dummy channel manager:**
   ```bash
   curl -X POST http://localhost:8000/api/v2/reservations \
     -H "Content-Type: application/json" \
     -d '{
       "guest": {
         "first_name": "John",
         "last_name": "Doe",
         "email": "john.doe@test.com",
         "phone": "+1234567890"
       },
       "room_id": 1,
       "rate_plan_id": 0,
       "arrival_date": "2024-02-15",
       "departure_date": "2024-02-18",
       "adults": 2,
       "children": 0
     }'
   ```

**Expected Output in Terminal 2 (dummy_channel_manager):**
```
[WEBHOOK] 📤 Sending webhook: booking.created
[WEBHOOK]    URL: http://localhost:8001/api/v1/webhooks/channel-manager
[WEBHOOK]    Payload keys: ['event_type', 'ota_connection_id', 'ota_code', 'external_booking_id', 'timestamp', 'booking']
[WEBHOOK] ✅ SUCCESS - Status: 200
[WEBHOOK]    Response: {"success":true,"message":"Booking created successfully","booking_id":123,"booking_number":"BK-..."}
```

**Expected Output in Terminal 1 (glimmora-backend):**
```
================================================================================
[WEBHOOK RECEIVER] 📥 Received webhook
[WEBHOOK RECEIVER]    Event Type: booking.created
[WEBHOOK RECEIVER]    OTA Connection ID: 1
[WEBHOOK RECEIVER]    Payload keys: ['event_type', 'ota_connection_id', 'ota_code', 'external_booking_id', 'timestamp', 'booking']
================================================================================
[WEBHOOK RECEIVER] → Routing to handle_booking_created
[handle_booking_created] 🔄 Processing booking.created webhook...
[handle_booking_created] ✓ Payload validated
[handle_booking_created] 🔍 Looking up OTA connection ID: 1
[handle_booking_created] ✓ OTA connection found: Booking.com (ID: 1)
[handle_booking_created] 🔍 Mapping room_type_code: ROOM_1
[get_room_type_id_from_code] 🔍 Looking up room mapping: ota_connection_id=1, room_type_code=ROOM_1
[get_room_type_id_from_code] ✓ Found mapping: ROOM_1 → room_type_id=5
[handle_booking_created] ✓ Room type mapped: ROOM_1 → room_type_id=5
[handle_booking_created] 🔍 Mapping rate_plan_code: BAR
[handle_booking_created] ✓ Rate plan mapped: BAR → rate_plan_id=1
[handle_booking_created] 👤 Processing guest: john.doe@test.com
[get_or_create_guest] 🔍 Looking up guest by email: john.doe@test.com
[get_or_create_guest] ➕ Creating new guest: John Doe
[get_or_create_guest] ✓ New guest added to session
[get_or_create_guest] ✓ Guest flushed: ID=45
[handle_booking_created] ✓ Guest ready: ID=45, Email=john.doe@test.com
[handle_booking_created] 📅 Dates: 2024-02-15 to 2024-02-18 (3 nights)
[handle_booking_created] 🎫 Generated booking_number: BK-20240115-A1B2C3, confirmation_code: D4E5F6G7
[handle_booking_created] 💾 Booking added to session (not yet committed)
[handle_booking_created] 📊 Updating availability grid for room_type_id=5
[handle_booking_created] ✓ Availability grid updated
[handle_booking_created] 📝 Sync log created
[handle_booking_created] 💾 Committing to database...
[handle_booking_created] ✅ Database commit successful! Booking ID: 123
[WEBHOOK RECEIVER] ✅ booking.created processed successfully
```

**Verification:**

1. Check database for new booking:
   ```sql
   SELECT * FROM bookings WHERE booking_number LIKE 'BK-%' ORDER BY created_at DESC LIMIT 1;
   ```

2. Check guest was created:
   ```sql
   SELECT * FROM guests WHERE email = 'john.doe@test.com';
   ```

3. Check availability grid updated:
   ```sql
   SELECT * FROM availability_grid WHERE room_type_id = 5 AND grid_date BETWEEN '2024-02-15' AND '2024-02-17';
   ```

---

### Test 2: Booking Modified Webhook

**Objective:** Verify that modifying a booking in dummy_channel_manager triggers a webhook that updates the booking in glimmora-backend.

**Prerequisites:** Complete Test 1 first to have a booking to modify.

**Steps:**

1. **Note the external_booking_id** from Test 1 (it's the confirmation_number from dummy channel manager)

2. **Modify the booking via dummy channel manager:**
   ```bash
   # Get the reservation UUID from Test 1 response
   RESERVATION_ID="<UUID_FROM_PREVIOUS_TEST>"
   
   curl -X PUT http://localhost:8000/api/reservations/${RESERVATION_ID} \
     -H "Content-Type: application/json" \
     -d '{
       "check_in": "2024-02-16",
       "check_out": "2024-02-20",
       "adults": 3
     }'
   ```

**Expected Output in Terminal 1 (glimmora-backend):**
```
================================================================================
[WEBHOOK RECEIVER] 📥 Received webhook
[WEBHOOK RECEIVER]    Event Type: booking.modified
[WEBHOOK RECEIVER]    OTA Connection ID: 1
================================================================================
[WEBHOOK RECEIVER] → Routing to handle_booking_modified
[handle_booking_modified] 🔄 Processing booking.modified webhook...
[handle_booking_modified] ✓ Payload validated
[handle_booking_modified] 🔍 Looking up booking by external_booking_id: HRS-2024-XXXXXX
[handle_booking_modified] ✓ Found booking: ID=123, booking_number=BK-...
[handle_booking_modified] ✓ Booking updated successfully
```

**Verification:**
- Check booking dates were updated in database
- Check modification_count was incremented
- Check availability grid was updated for old and new dates

---

### Test 3: Booking Cancelled Webhook

**Objective:** Verify that cancelling a booking in dummy_channel_manager triggers a webhook that cancels the booking in glimmora-backend.

**Prerequisites:** Complete Test 1 or Test 2 first.

**Steps:**

1. **Cancel the booking:**
   ```bash
   RESERVATION_ID="<UUID_FROM_PREVIOUS_TEST>"
   
   curl -X DELETE http://localhost:8000/api/reservations/${RESERVATION_ID}
   ```

**Expected Output in Terminal 1 (glimmora-backend):**
```
================================================================================
[WEBHOOK RECEIVER] 📥 Received webhook
[WEBHOOK RECEIVER]    Event Type: booking.cancelled
[WEBHOOK RECEIVER]    OTA Connection ID: 1
================================================================================
[handle_booking_cancelled] 🔄 Processing booking.cancelled webhook...
[handle_booking_cancelled] ✓ Found booking: ID=123, booking_number=BK-...
[handle_booking_cancelled] ✓ Booking cancelled successfully
```

**Verification:**
- Check booking status = "cancelled"
- Check cancelled_at timestamp is set
- Check availability grid restored (sold count decreased)

---

### Test 4: Availability Updated Webhook

**Objective:** Verify that availability updates trigger webhooks correctly.

**Steps:**

1. **Trigger availability webhook:**
   ```bash
   curl -X POST "http://localhost:8000/api/webhooks/trigger/availability?ota_connection_id=1&date=2024-02-15"
   ```

**Expected Output in Terminal 1 (glimmora-backend):**
```
================================================================================
[WEBHOOK RECEIVER] 📥 Received webhook
[WEBHOOK RECEIVER]    Event Type: availability.updated
[WEBHOOK RECEIVER]    OTA Connection ID: 1
================================================================================
[WEBHOOK RECEIVER] → Routing to handle_availability_updated
[handle_availability_updated] 🔄 Processing availability.updated webhook...
[handle_availability_updated] ✅ Availability updated for 3 room types
```

**Verification:**
- Check AvailabilityGrid table was updated
- Check availability counts match webhook data

---

### Test 5: Rates Updated Webhook

**Objective:** Verify that rate updates trigger webhooks correctly.

**Note:** This webhook type is triggered manually or via rate updates. For testing, we'll need to implement a trigger endpoint in dummy_channel_manager if not already present.

**Verification:**
- Check DailyRate table was updated
- Check rates match webhook data

---

### Test 6: Restrictions Updated Webhook

**Objective:** Verify that restriction updates trigger webhooks correctly.

**Note:** This webhook type may need manual triggering. Check dummy_channel_manager for endpoint.

**Verification:**
- Check ChannelRestriction table was updated
- Check AvailabilityGrid flags were updated (CTA, CTD, Stop Sell, etc.)

---

### Test 7: Sync Status Webhook

**Objective:** Verify that sync status updates work correctly.

**Steps:**

1. **Trigger sync status webhook:**
   ```bash
   curl -X POST "http://localhost:8000/api/webhooks/trigger/sync-status?ota_connection_id=1&connection_status=connected&sync_type=full&records_processed=150&records_failed=0"
   ```

**Expected Output in Terminal 1 (glimmora-backend):**
```
================================================================================
[WEBHOOK RECEIVER] 📥 Received webhook
[WEBHOOK RECEIVER]    Event Type: sync.status
[WEBHOOK RECEIVER]    OTA Connection ID: 1
================================================================================
[handle_sync_status] 🔄 Processing sync.status webhook...
[handle_sync_status] ✅ Sync status updated
```

**Verification:**
- Check OTAConnection table - connection_status updated
- Check last_sync_at timestamp updated
- Check SyncLog table has new entry

---

## Troubleshooting

### Issue 1: Webhook Not Being Sent

**Symptoms:**
- No logs in dummy_channel_manager console
- No logs in glimmora-backend console

**Solutions:**
1. Check WEBHOOK_URL is configured:
   ```bash
   curl http://localhost:8000/api/webhooks/status
   ```

2. Verify glimmora-backend is running and accessible:
   ```bash
   curl http://localhost:8001/health
   ```

3. Check network connectivity between services

### Issue 2: Webhook Received But Processing Failed

**Symptoms:**
- Logs show webhook received in glimmora-backend
- Error logs appear

**Common Causes:**
1. **OTA Connection not found:**
   - Ensure OTAConnection with id=1 exists in database
   - Check ota_connections table

2. **Room/Rate mapping not found:**
   - Ensure OTARoomMapping exists for room_type_code
   - Ensure OTARateMapping exists for rate_plan_code
   - Check mappings in database:
     ```sql
     SELECT * FROM ota_room_mappings WHERE ota_connection_id = 1;
     SELECT * FROM ota_rate_mappings WHERE ota_connection_id = 1;
     ```

3. **Database connection issues:**
   - Check database file exists
   - Check database permissions

### Issue 3: Webhook Sent But Backend Not Receiving

**Symptoms:**
- Logs in dummy_channel_manager show "SUCCESS - Status: 200"
- No logs in glimmora-backend

**Solutions:**
1. Check webhook URL is correct (should be `http://localhost:8001/api/v1/webhooks/channel-manager`)
2. Check firewall/proxy blocking connection
3. Check CORS settings (if applicable)
4. Verify endpoint is registered in routes.py

### Issue 4: Booking Created But Not in Database

**Symptoms:**
- Webhook processed successfully
- No booking in database

**Solutions:**
1. Check for database transaction rollback (check logs for errors)
2. Check database file permissions
3. Verify database commit is happening
4. Check database file location

## Test Checklist

- [ ] Glimmora-backend starts successfully
- [ ] Dummy channel manager starts successfully
- [ ] Webhook URL configured correctly
- [ ] Test 1: Booking Created - Webhook sent and received
- [ ] Test 1: Booking Created - Database updated (Booking, Guest, AvailabilityGrid)
- [ ] Test 2: Booking Modified - Webhook sent and received
- [ ] Test 2: Booking Modified - Database updated
- [ ] Test 3: Booking Cancelled - Webhook sent and received
- [ ] Test 3: Booking Cancelled - Database updated (status, availability restored)
- [ ] Test 4: Availability Updated - Webhook sent and received
- [ ] Test 4: Availability Updated - Database updated
- [ ] Test 7: Sync Status - Webhook sent and received
- [ ] Test 7: Sync Status - Database updated (OTAConnection, SyncLog)

## Database Verification Queries

### Check Bookings Created
```sql
SELECT 
    b.id, b.booking_number, b.confirmation_code, b.status,
    g.first_name || ' ' || g.last_name as guest_name,
    b.arrival_date, b.departure_date, b.total_price, b.channel
FROM bookings b
JOIN guests g ON b.guest_id = g.id
ORDER BY b.created_at DESC
LIMIT 10;
```

### Check OTA Mappings
```sql
-- Room mappings
SELECT 
    orm.id, orm.ota_room_code, orm.room_type_id, rt.name as room_type_name
FROM ota_room_mappings orm
JOIN room_types rt ON orm.room_type_id = rt.id
WHERE orm.ota_connection_id = 1;

-- Rate mappings
SELECT 
    otrm.id, otrm.ota_rate_code, otrm.rate_plan_id, rp.name as rate_plan_name
FROM ota_rate_mappings otrm
JOIN rateplan rp ON otrm.rate_plan_id = rp.id
WHERE otrm.ota_connection_id = 1;
```

### Check Availability Grid
```sql
SELECT 
    ag.id, ag.room_type_id, rt.name as room_type_name,
    ag.grid_date, ag.total_inventory, ag.sold, ag.blocked, ag.available
FROM availability_grid ag
JOIN room_types rt ON ag.room_type_id = rt.id
WHERE ag.grid_date >= DATE('now')
ORDER BY ag.grid_date, ag.room_type_id;
```

### Check Sync Logs
```sql
SELECT 
    sl.id, sl.sync_type, sl.sync_direction, sl.status,
    sl.records_processed, sl.records_failed,
    oc.ota_name, sl.started_at, sl.completed_at
FROM sync_logs sl
JOIN ota_connections oc ON sl.ota_connection_id = oc.id
ORDER BY sl.started_at DESC
LIMIT 10;
```

## Success Criteria

All tests pass if:
1. ✅ Webhooks are sent from dummy_channel_manager
2. ✅ Webhooks are received by glimmora-backend (visible in logs)
3. ✅ Database is updated correctly (verified via queries)
4. ✅ No errors in console logs
5. ✅ All webhook types work (booking.created, booking.modified, booking.cancelled, availability.updated, sync.status)

## Next Steps

Once all tests pass:
1. Frontend can connect to SSE endpoint to receive real-time updates
2. Implement remaining webhook types if needed (rates.updated, restrictions.updated)
3. Add webhook authentication for production
4. Add webhook retry logic in dummy_channel_manager
