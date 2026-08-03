# Multi-Tenant Database Migration Guide

## Overview

This document describes the migration from a single-database architecture to a multi-tenant database-per-hotel architecture in Glimmora Hotel Management System.

---

## Architecture Comparison

### Before: Single Database

```
┌─────────────────────────────────────────┐
│           PostgreSQL Server             │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │         glimmora_db               │  │
│  │                                   │  │
│  │  • All hotels in same tables     │  │
│  │  • No data isolation             │  │
│  │  • Single point of failure       │  │
│  │  • Scaling limitations           │  │
│  └───────────────────────────────────┘  │
│                                         │
└─────────────────────────────────────────┘
```

### After: Multi-Tenant (Database per Hotel)

```
┌─────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Server                          │
│                                                                 │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │ glimmora_     │  │ glimmora_     │  │ glimmora_     │       │
│  │ master        │  │ hotel_abc     │  │ hotel_xyz     │       │
│  │               │  │               │  │               │       │
│  │ • hotels      │  │ • rooms       │  │ • rooms       │       │
│  │ • global_     │  │ • bookings    │  │ • bookings    │       │
│  │   users       │  │ • guests      │  │ • guests      │       │
│  │               │  │ • users       │  │ • users       │       │
│  └───────────────┘  └───────────────┘  └───────────────┘       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Changes

### 1. Database Structure

| Component | Before | After |
|-----------|--------|-------|
| Databases | 1 (glimmora_db) | 1 master + N hotel DBs |
| User storage | Single users table | Per-hotel users table |
| Data isolation | None | Complete |
| Hotel identification | hotel_id column | Separate database |

### 2. Configuration Changes

**New Environment Variables:**

```env
# Master database (hotel registry)
MASTER_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/glimmora_master

# Template for hotel databases
HOTEL_DATABASE_TEMPLATE=postgresql+asyncpg://user:pass@localhost:5432/{db_name}

# Feature flag
MULTI_TENANT_ENABLED=true
```

### 3. Authentication Flow

**Before:**
```
Login Request → Check users table → Create JWT → Done
```

**After:**
```
Login Request (with hotel_code)
    ↓
Look up hotel in master DB
    ↓
Connect to hotel's database
    ↓
Check users table in hotel DB
    ↓
Create JWT with hotel_code claim
    ↓
Done
```

### 4. Request Flow

**Before:**
```python
@router.get("/rooms")
async def get_rooms(session: AsyncSession = Depends(get_session)):
    # Single database connection
    return await session.exec(select(Room))
```

**After:**
```python
@router.get("/rooms")
async def get_rooms(session: AsyncSession = Depends(get_tenant_session)):
    # Tenant-specific database connection based on request context
    return await session.exec(select(Room))
```

---

## Files Changed

### New Files

| File | Purpose |
|------|---------|
| `app/db/master_models.py` | Hotel and GlobalUser models for master DB |
| `app/db/tenant_manager.py` | TenantDatabaseManager class |
| `app/middleware/tenant.py` | TenantMiddleware for extracting hotel context |
| `app/scripts/provision_hotel.py` | Script to create new hotel databases |
| `app/scripts/seed_hotels_data.py` | Seed data for test hotels |

### Modified Files

| File | Changes |
|------|---------|
| `app/core/config.py` | Added multi-tenant config settings |
| `app/core/security.py` | JWT now includes hotel_code |
| `app/db/session.py` | Added get_tenant_session, get_master_session |
| `app/main.py` | Added TenantMiddleware, updated startup |
| `app/models/user.py` | Added hotel_code field |
| `app/schemas/auth.py` | Added hotel_code to auth schemas |
| `app/api/v1/*.py` | All routes updated to use get_tenant_session |
| `app/services/scheduler.py` | Background jobs iterate all hotels |

---

## Migration Steps

### Step 1: Set Up Master Database

```bash
# Create master database
createdb glimmora_master

# Run master migrations (creates hotels and global_users tables)
python -c "
import asyncio
from app.db.session import init_master_db
asyncio.run(init_master_db())
"
```

### Step 2: Provision Hotels

```bash
# Create a new hotel
python -m app.scripts.provision_hotel "Crown Plaza Kochi" "crownplaza_kochi" --city "Kochi" --country "India"

# This will:
# 1. Create database: glimmora_crownplaza_kochi
# 2. Run all migrations on new DB
# 3. Register hotel in master DB
# 4. Create admin user
```

### Step 3: Migrate Existing Data (if applicable)

```bash
# Export from old single DB
pg_dump glimmora_db > backup.sql

# For each hotel, import relevant data
# (Custom script needed based on your data structure)
python -m app.scripts.migrate_existing --source glimmora_db --target crownplaza_kochi
```

### Step 4: Update Environment

```env
# Add to .env
MASTER_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/glimmora_master
HOTEL_DATABASE_TEMPLATE=postgresql+asyncpg://user:pass@localhost:5432/{db_name}
MULTI_TENANT_ENABLED=true
```

### Step 5: Restart Application

```bash
# Restart backend
uvicorn app.main:app --reload

# Update frontend .env.local
VITE_HOTEL_CODE=crownplaza_kochi
```

---

## Developer Guide

### Creating a New Route

```python
from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.session import get_tenant_session  # NOT get_session

router = APIRouter()

@router.get("/items")
async def get_items(
    session: AsyncSession = Depends(get_tenant_session)  # Tenant-aware
):
    # This session connects to the correct hotel database
    # based on request.state.hotel_code set by TenantMiddleware
    result = await session.exec(select(Item))
    return result.all()
```

### Accessing Master Database

```python
from app.db.session import get_master_session

@router.get("/hotels")
async def list_hotels(
    session: AsyncSession = Depends(get_master_session)  # Master DB
):
    result = await session.exec(select(Hotel))
    return result.all()
```

### Getting Current Hotel Context

```python
from fastapi import Request

@router.get("/info")
async def get_info(request: Request):
    hotel_code = request.state.hotel_code
    # Use hotel_code as needed
```

### Background Jobs

```python
from app.db.tenant_manager import tenant_manager

async def process_all_hotels():
    """Run a job for all active hotels."""
    hotels = await tenant_manager.get_all_active_hotels()

    for hotel in hotels:
        async for session in tenant_manager.get_session(hotel.code):
            await process_hotel(session, hotel)
```

---

## Frontend Integration

### Hotel Code Detection

```typescript
// src/config/env.ts

function getHotelCodeFromSubdomain(): string {
  const hostname = window.location.hostname;

  // Development: use env variable
  if (hostname === 'localhost' || /^\d+\.\d+\.\d+\.\d+$/.test(hostname)) {
    return import.meta.env.VITE_HOTEL_CODE || '';
  }

  // Production: extract from subdomain
  // crownplaza.glimmora.com → crownplaza
  const parts = hostname.split('.');
  if (parts.length >= 3) {
    return parts[0];
  }

  return '';
}
```

### API Client Headers

```typescript
// Always send X-Hotel-Code header
apiClient.interceptors.request.use((config) => {
  if (ENV.HOTEL_CODE) {
    config.headers['X-Hotel-Code'] = ENV.HOTEL_CODE;
  }
  return config;
});
```

### Auth Service

```typescript
// Include hotel_code in auth requests
const login = async (email: string, password: string) => {
  return apiClient.post('/api/v1/auth/login', {
    email,
    password,
    hotel_code: ENV.HOTEL_CODE  // Required for multi-tenant
  });
};
```

---

## Troubleshooting

### Error: "No hotel context found"

**Cause:** Request missing hotel_code

**Solution:**
1. Check if X-Hotel-Code header is being sent
2. Check if JWT contains hotel_code claim
3. Verify VITE_HOTEL_CODE is set in frontend .env.local

### Error: "Hotel not found: xyz"

**Cause:** Hotel not registered in master database

**Solution:**
```bash
# Check if hotel exists
python -c "
from app.db.tenant_manager import tenant_manager
import asyncio

async def check():
    hotels = await tenant_manager.get_all_active_hotels()
    for h in hotels:
        print(f'{h.code}: {h.name}')

asyncio.run(check())
"
```

### Error: "Foreign key violation on rate_plan_id"

**Cause:** Hardcoded rate_plan_id=1 but actual IDs differ per hotel

**Solution:** Use `get_default_rate_plan_id()` helper instead of hardcoded IDs

### Error: Database connection timeout

**Cause:** Too many connections or DB not running

**Solution:**
1. Check PostgreSQL is running
2. Check connection pool settings
3. Verify database exists: `psql -l | grep glimmora`

---

## Best Practices

### DO:
- Always use `get_tenant_session` for tenant data
- Include hotel_code in all auth-related requests
- Use `get_default_rate_plan_id()` instead of hardcoded IDs
- Test with multiple hotels before deploying

### DON'T:
- Never use `get_session` (legacy) in new code
- Never hardcode hotel-specific IDs
- Never access tenant data from master session
- Never skip hotel_code in frontend requests

---

## Database Naming Convention

| Type | Pattern | Example |
|------|---------|---------|
| Master DB | `glimmora_master` | `glimmora_master` |
| Hotel DB | `glimmora_{hotel_code}` | `glimmora_crownplaza_kochi` |
| Hotel Code | `{brand}_{city}` | `marriott_mumbai`, `taj_goa` |

---

## Testing Checklist

- [ ] Create new hotel via provisioning script
- [ ] Login as hotel admin → correct DB connection
- [ ] Create booking → data in correct hotel DB
- [ ] Switch hotels → see different data
- [ ] Background jobs run for all hotels
- [ ] Hotel A user cannot see Hotel B data
- [ ] Frontend subdomain detection works
- [ ] X-Hotel-Code header sent on all requests

---

## Support

For issues with multi-tenant setup:
1. Check this documentation
2. Review audit logs for errors
3. Contact: support@glimmora.com
