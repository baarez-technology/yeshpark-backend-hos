# Frontend Guide: Revenue → Rate Calendar & Bulk Edit

This guide describes what to implement or change in the **frontend** so the **Revenue → Rate Calendar** page works with the Glimmora backend, including **bulk edit**.

---

## 1. Base URL and auth

- **Base:** `GET/PUT` to your backend base URL + `/api/v1/revenue-intelligence`
- **Auth:** Send the user’s auth token (e.g. Bearer) in the `Authorization` header for all requests below.

---

## 2. Get Rate Calendar (load the grid)

**Endpoint:** `GET /api/v1/revenue-intelligence/rates/calendar`

**Query params:**

| Param           | Type   | Required | Description                          |
|----------------|--------|----------|--------------------------------------|
| `start_date`   | string | No       | ISO date (e.g. `2026-02-22`). Default: today |
| `end_date`     | string | No       | ISO date. Default: today + 30 days   |
| `room_type_id` | number | No       | Filter by one room type               |

**Example request:**
```http
GET /api/v1/revenue-intelligence/rates/calendar?start_date=2026-02-22&end_date=2026-03-25
Authorization: Bearer <token>
```

**Response (200):**
```json
{
  "period": {
    "start": "2026-02-22",
    "end": "2026-03-25"
  },
  "calendar": [
    {
      "date": "2026-02-22",
      "room_type_id": 1,
      "room_type_name": "Standard King",
      "base_rate": 149.0,
      "effective_rate": 159.5,
      "occupancy": 72.0,
      "demand_level": "moderate",
      "has_event": false,
      "event_name": null
    }
  ],
  "summary": {
    "total_projected_revenue": 125000.5,
    "average_occupancy": 71.2,
    "days_with_events": 2,
    "room_types_count": 8
  }
}
```

**What to do in the frontend:**

1. **Fetch on load:** When the Rate Calendar page or date range changes, call this GET with `start_date` and `end_date` (and optional `room_type_id`).
2. **Render the grid:** Use `response.calendar` as the list of cells. Each item has:
   - `date`, `room_type_id`, `room_type_name` – for rows/columns and keys
   - `base_rate`, `effective_rate` – show the rate you want (usually `effective_rate` for “current” rate)
   - `occupancy`, `demand_level`, `has_event`, `event_name` – for extra UI (badges, tooltips)
3. **Use `period` and `summary`** for headers, range label, and summary cards if you have them.

---

## 3. Update a single rate (inline edit)

**Endpoint:** `PUT /api/v1/revenue-intelligence/rates/{room_type_id}/{rate_date}`

- `room_type_id`: number (path)
- `rate_date`: ISO date string, e.g. `2026-02-22` (path)

**Body:**
```json
{
  "rate": 169.99,
  "reason": "Optional note"
}
```

**Response (200):**
```json
{
  "success": true,
  "room_type_id": 1,
  "date": "2026-02-22",
  "previous_rate": 159.5,
  "new_rate": 169.99,
  "change_percent": 6.6,
  "audit_id": 42,
  "message": "Rate updated from $159.50 to $169.99"
}
```

**What to do in the frontend:**

- When the user edits one cell and saves, call this PUT with the cell’s `room_type_id` and `date`, and body `{ rate, reason? }`.
- On success, refresh the calendar (call the GET again) or update that cell’s `effective_rate` from the response so the grid stays in sync.

---

## 4. Bulk update (bulk edit)

**Endpoint:** `PUT /api/v1/revenue-intelligence/rates/bulk-update`

**Body:**
```json
{
  "updates": [
    { "room_type_id": 1, "date": "2026-02-22", "rate": 165.0 },
    { "room_type_id": 1, "date": "2026-02-23", "rate": 170.0 },
    { "room_type_id": 2, "date": "2026-02-22", "rate": 180.0 }
  ],
  "reason": "Optional reason for bulk change"
}
```

- `updates`: array of `{ room_type_id: number, date: string (YYYY-MM-DD), rate: number }`. `rate` must be &gt; 0.
- `reason`: optional string.

**Response (200):**
```json
{
  "success": true,
  "updated_count": 3,
  "failed_count": 0,
  "audit_ids": [43, 44, 45],
  "results": [
    { "room_type_id": 1, "date": "2026-02-22", "status": "success", "new_rate": 165.0 },
    { "room_type_id": 1, "date": "2026-02-23", "status": "success", "new_rate": 170.0 },
    { "room_type_id": 2, "date": "2026-02-22", "status": "success", "new_rate": 180.0 }
  ]
}
```

If some rows fail (e.g. validation), you still get 200 with `failed_count` &gt; 0 and some `results[].status === "failed"` with `results[].error`.

**What to change in the frontend for bulk edit:**

1. **Build `updates` from the UI:** When the user applies a “bulk edit” (e.g. “set these dates to $X” or “apply to selected cells”):
   - Collect each changed cell as `{ room_type_id, date: "YYYY-MM-DD", rate }`.
   - Use the **same** `date` format as the calendar API (`YYYY-MM-DD`). No `room_type_name` needed.
2. **Single request:** Send one `PUT .../rates/bulk-update` with `{ updates, reason? }`. Do not call the single-rate PUT in a loop for bulk.
3. **After success:** Re-fetch the rate calendar (GET) so the grid shows the new `effective_rate` for all updated cells. Optionally show a toast: “Updated N rates” or “Updated N, Y failed” if `failed_count` &gt; 0.
4. **Errors:** If the backend returns 400, show the `detail` message. For partial success, show which rows failed using `results[].status` and `results[].error`.

---

## 5. Checklist: what to change in the frontend

| Area | What to do |
|------|------------|
| **API base** | Ensure Revenue calls use `/api/v1/revenue-intelligence/...` (not channel-manager or another prefix). |
| **Load calendar** | Call `GET .../rates/calendar?start_date=...&end_date=...` and render `calendar` (and optionally `period`, `summary`). |
| **Field names** | Backend uses `snake_case` (`room_type_id`, `effective_rate`, `demand_level`, etc.). Map to your UI types if you use camelCase. |
| **Single edit** | On save of one cell, call `PUT .../rates/{room_type_id}/{rate_date}` with `{ rate, reason? }`, then refresh or patch that cell. |
| **Bulk edit** | On “Apply” bulk edit, build `updates: [{ room_type_id, date: "YYYY-MM-DD", rate }, ...]` and call `PUT .../rates/bulk-update` once. Then re-fetch the calendar. |
| **Dates** | Always send dates as `YYYY-MM-DD` (ISO). Use the same for path and query. |
| **Auth** | Attach the same Bearer (or your) auth header as for other authenticated APIs. |

---

## 6. Not the Channel Manager calendar

The **Channel Manager** has its own rate calendar:

- `GET /api/v1/channel-manager/rates/calendar`
- `PUT /api/v1/channel-manager/rates/calendar/{date}/{roomType}` (single)

For **Revenue → Rate Calendar** and **bulk edit**, use only the **revenue-intelligence** endpoints above. Do not mix the two.

---

## 7. Testing with dummy data

Backend can seed dummy DailyRates so the calendar has data:

```bash
python scripts/seed_rate_calendar_dummy.py
```

Then open Revenue → Rate Calendar and test:

1. Calendar loads with rates.
2. Single-cell edit updates and grid refreshes.
3. Bulk edit sends one `bulk-update` request and grid refreshes without affecting other features.

If you tell me your frontend stack (e.g. React + axios, fetch, React Query), I can suggest exact service/API functions and types next.
