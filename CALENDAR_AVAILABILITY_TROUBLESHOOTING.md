# Calendar / Availability Not Showing – Troubleshooting

If the calendar (availability grid) doesn’t show, the problem is often the **availability API** or the backend. Use the browser **Network** tab and backend logs to narrow it down.

## 1. Find the request in the Network tab

1. Open DevTools (F12) → **Network**.
2. Reload the page or open the screen that should show the calendar.
3. Filter by **Fetch/XHR** (or search for `availability` or `grid`).
4. Look for one of these requests:
   - **`/api/v1/availability/grid`** – CMS availability grid (no auth).
   - **`/api/v1/inventory/availability-grid`** – Inventory availability grid (requires auth).

## 2. Check the request

- **URL**: Should include query params, e.g.  
  `?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`  
  (or `start_date` / `end_date`). Dates must be **YYYY-MM-DD**.
- **Method**: `GET`.
- **Auth**: For `/api/v1/inventory/availability-grid`, the request must send an auth header (e.g. `Authorization: Bearer <token>`). Missing or invalid token → **401**.

## 3. Check the response

| Status | Meaning |
|--------|--------|
| **200** | Backend succeeded. If the calendar is still empty, check the **response body** (e.g. `availability` / `grid` array empty, or frontend not mapping the shape correctly). |
| **400** | Bad request – often **invalid date format**. Use `YYYY-MM-DD`. |
| **401** | Unauthorized – required for `/inventory/availability-grid`. Log in or fix the token. |
| **422** | Validation error – wrong or missing query params (e.g. wrong param names). Response body lists the validation errors. |
| **500** | Server error – check **backend logs** for the traceback. |

## 4. Backend endpoints (reference)

| Endpoint | Auth | Query params |
|----------|------|--------------|
| `GET /api/v1/availability/grid` | No | `startDate` or `start_date`, `endDate` or `end_date`; optional `roomTypeIds` or `room_type_ids` |
| `GET /api/v1/inventory/availability-grid` | Yes (Bearer) | `startDate` or `start_date`, `endDate` or `end_date`; optional `roomTypeId` or `room_type_id` |

Both accept **camelCase** (`startDate`, `endDate`) and **snake_case** (`start_date`, `end_date`).

## 5. Check backend logs

If the request returns **500** or you see errors in the console:

- Run the backend in a terminal and watch the log output when you trigger the calendar.
- For **500** on `/api/v1/availability/grid`, look for `Error in get_availability_grid:` and the traceback (e.g. DB, missing table, or bad date handling).

## 6. Quick curl checks

**Availability grid (no auth):**
```bash
curl -s "http://localhost:8000/api/v1/availability/grid?startDate=2025-02-01&endDate=2025-02-07"
```

**Inventory availability grid (with token):**
```bash
curl -s -H "Authorization: Bearer YOUR_TOKEN" "http://localhost:8000/api/v1/inventory/availability-grid?startDate=2025-02-01&endDate=2025-02-07"
```

Replace port and token as needed. A successful response has `start_date`, `end_date`, and an `availability` or `grid` array.
