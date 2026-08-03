# Comprehensive Webhook Testing Script (PowerShell)
# Tests all webhook-triggering APIs from dummy_channel_manager to glimmora-backend

Write-Host "========================================" -ForegroundColor Blue
Write-Host "Webhook Connectivity Test Script" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue
Write-Host ""

# Configuration
$CHANNEL_MANAGER_URL = "http://localhost:8001"
$BACKEND_URL = "http://localhost:8000"

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Channel Manager: $CHANNEL_MANAGER_URL"
Write-Host "  Glimmora Backend: $BACKEND_URL"
Write-Host ""

# Step 1: Check if webhook URL is configured
Write-Host "[1/7] Checking webhook configuration..." -ForegroundColor Blue
try {
    $webhookStatus = Invoke-RestMethod -Uri "$CHANNEL_MANAGER_URL/api/webhooks/status" -Method Get
    $webhookStatus | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}
Write-Host ""

# Step 2: Configure webhook URL if needed
Write-Host "[2/7] Configuring webhook URL..." -ForegroundColor Blue
try {
    $webhookConfig = @{
        url = "$BACKEND_URL/api/v1/webhooks/channel-manager"
    } | ConvertTo-Json
    
    $configureResponse = Invoke-RestMethod -Uri "$CHANNEL_MANAGER_URL/api/webhooks/configure" `
        -Method Post `
        -ContentType "application/json" `
        -Body $webhookConfig
    $configureResponse | ConvertTo-Json -Depth 10
    Write-Host "OK Webhook URL configured" -ForegroundColor Green
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}
Write-Host ""

# Step 3: Create a reservation (triggers booking.created webhook)
Write-Host "[3/7] Creating reservation (booking.created webhook)..." -ForegroundColor Blue
try {
    $reservationData = @{
        hotel_id = $null
        room_id = 1
        rate_plan_id = 0
        arrival_date = "2024-12-20"
        departure_date = "2024-12-23"
        adults = 2
        children = 0
        guest = @{
            first_name = "John"
            last_name = "Doe"
            email = "john.doe@example.com"
            phone = "+1234567890"
            notes = "Test booking"
        }
        special_requests = "Early check-in preferred"
    } | ConvertTo-Json -Depth 10
    
    $createdResponse = Invoke-RestMethod -Uri "$CHANNEL_MANAGER_URL/api/v2/reservations" `
        -Method Post `
        -ContentType "application/json" `
        -Body $reservationData
    $createdResponse | ConvertTo-Json -Depth 10
    $reservationId = $createdResponse.data.id
    Write-Host "OK Reservation created: $reservationId" -ForegroundColor Green
    Write-Host "Wait 2 seconds for webhook to be sent..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    $reservationId = $null
}
Write-Host ""

# Step 4: Modify the reservation (triggers booking.modified webhook)
if ($reservationId) {
    Write-Host "[4/7] Modifying reservation (booking.modified webhook)..." -ForegroundColor Blue
    try {
        $modifyData = @{
            check_out = "2024-12-24"
            special_requests = "Late checkout preferred"
        } | ConvertTo-Json
        
        $modifiedResponse = Invoke-RestMethod -Uri "$CHANNEL_MANAGER_URL/api/reservations/$reservationId" `
            -Method Put `
            -ContentType "application/json" `
            -Body $modifyData
        $modifiedResponse | ConvertTo-Json -Depth 10
        Write-Host "OK Reservation modified" -ForegroundColor Green
        Write-Host "Wait 2 seconds for webhook to be sent..." -ForegroundColor Yellow
        Start-Sleep -Seconds 2
    } catch {
        Write-Host "Error: $_" -ForegroundColor Red
    }
} else {
    Write-Host "WARNING: Skipping modify test (no reservation ID)" -ForegroundColor Yellow
}
Write-Host ""

# Step 5: Trigger availability webhook
Write-Host "[5/7] Triggering availability.updated webhook..." -ForegroundColor Blue
try {
    $availabilityResponse = Invoke-RestMethod -Uri "$CHANNEL_MANAGER_URL/api/webhooks/trigger/availability?ota_connection_id=1" `
        -Method Post
    $availabilityResponse | ConvertTo-Json -Depth 10
    Write-Host "OK Availability webhook triggered" -ForegroundColor Green
    Write-Host "Wait 2 seconds for webhook to be sent..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}
Write-Host ""

# Step 6: Trigger sync status webhook
Write-Host "[6/7] Triggering sync.status webhook..." -ForegroundColor Blue
try {
    $syncResponse = Invoke-RestMethod -Uri "$CHANNEL_MANAGER_URL/api/webhooks/trigger/sync-status?ota_connection_id=1&connection_status=connected&sync_type=full&records_processed=150&records_failed=0" `
        -Method Post
    $syncResponse | ConvertTo-Json -Depth 10
    Write-Host "OK Sync status webhook triggered" -ForegroundColor Green
    Write-Host "Wait 2 seconds for webhook to be sent..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}
Write-Host ""

# Step 7: Cancel the reservation (triggers booking.cancelled webhook)
if ($reservationId) {
    Write-Host "[7/7] Cancelling reservation (booking.cancelled webhook)..." -ForegroundColor Blue
    try {
        $cancelledResponse = Invoke-RestMethod -Uri "$CHANNEL_MANAGER_URL/api/reservations/$reservationId" `
            -Method Delete
        $cancelledResponse | ConvertTo-Json -Depth 10
        Write-Host "OK Reservation cancelled" -ForegroundColor Green
        Write-Host "Wait 2 seconds for webhook to be sent..." -ForegroundColor Yellow
        Start-Sleep -Seconds 2
    } catch {
        Write-Host "Error: $_" -ForegroundColor Red
    }
} else {
    Write-Host "WARNING: Skipping cancel test (no reservation ID)" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Blue
Write-Host "All tests completed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Blue
Write-Host ""
Write-Host "Please check the logs from both servers:" -ForegroundColor Yellow
Write-Host "  1. Channel Manager (localhost:8001) - Look for WEBHOOK messages"
Write-Host "  2. Glimmora Backend (localhost:8000) - Look for WEBHOOK RECEIVER messages"
Write-Host ""
