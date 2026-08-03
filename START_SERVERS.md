# How to Start the Servers

## Server Configuration

- **Glimmora Backend API**: `http://localhost:8000`
- **Dummy Channel Manager**: `http://localhost:8002`

## Starting the Servers

### Terminal 1: Glimmora Backend
```bash
cd C:\Users\princ\Desktop\glimmora-backend
python -m uvicorn app.main:app --reload --port 8000
```

### Terminal 2: Dummy Channel Manager
```bash
cd C:\Users\princ\Desktop\glimmora-backend\dummy_channel_manager
python main.py
```

Or using uvicorn directly:
```bash
cd C:\Users\princ\Desktop\glimmora-backend\dummy_channel_manager
python -m uvicorn main:app --reload --port 8002
```

## Environment Variables (Optional)

You can override the default ports and URLs using environment variables:

### For Dummy Channel Manager:
```bash
# Windows PowerShell
$env:CHANNEL_MANAGER_PORT="8002"
$env:GLIMMORA_BACKEND_URL="http://localhost:8000"
$env:WEBHOOK_URL="http://localhost:8000/api/v1/webhooks/channel-manager"
$env:GLIMMORA_API_TOKEN="your-token-here"  # If authentication required

# Then run
python main.py
```

### For Glimmora Backend:
```bash
# Windows PowerShell
$env:PORT="8000"

# Then run
python -m uvicorn app.main:app --reload --port 8000
```

## Verification

Once both servers are running, you should see:

### Glimmora Backend (port 8000):
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

### Dummy Channel Manager (port 8002):
```
[STARTUP] Starting dummy channel manager on port 8002
[STARTUP] Glimmora Backend URL: http://localhost:8000
[STARTUP] Webhook URL: http://localhost:8000/api/v1/webhooks/channel-manager
[STARTUP] SUCCESS: Connected to Glimmora backend - Found X room types
[STARTUP] SUCCESS: DUMMY OTA connected to Glimmora backend
INFO:     Application startup complete.
```

## Testing the Connection

1. **Check Dummy Channel Manager Health:**
   ```bash
   curl http://localhost:8002/health
   ```

2. **Check Glimmora Backend Health:**
   ```bash
   curl http://localhost:8000/health
   ```

3. **Test DUMMY OTA Connection:**
   ```bash
   curl -X POST http://localhost:8002/api/ota/connect
   ```

4. **List OTAs from Glimmora Backend:**
   ```bash
   curl http://localhost:8000/api/v1/channel-manager/otas
   ```

## Troubleshooting

### Port Already in Use
If you get a "port already in use" error:
- Check what's running on that port: `netstat -ano | findstr :8000` or `netstat -ano | findstr :8002`
- Kill the process or use a different port

### Connection Errors
- Make sure Glimmora Backend is running before starting the Dummy Channel Manager
- Check that both servers are on the correct ports
- Verify firewall settings allow localhost connections

### Authentication Errors
- The channel manager endpoints now support optional authentication
- Internal service calls (from dummy channel manager) don't require authentication
- Frontend calls should include Bearer token in Authorization header
