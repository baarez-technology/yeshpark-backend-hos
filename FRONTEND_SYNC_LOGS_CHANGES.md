# Frontend Changes for Channels → Sync Logs

Use this checklist to align the frontend with the backend Sync Logs API (dates + filters).

---

## 1. API request (query parameters)

Call the list endpoint with these **query parameter names** (backend accepts these):

| Frontend sends | Description |
|----------------|-------------|
| `page` | Page number (1-based). Default: 1 |
| `pageSize` | Items per page. Default: 50. **Use `pageSize` (camelCase), not `page_size`** |
| `action` | Filter by action (dropdown). See allowed values below |
| `status` | Filter by status (dropdown). See allowed values below |
| `dateFrom` | Start date filter `YYYY-MM-DD` (optional) |
| `dateTo` | End date filter `YYYY-MM-DD` (optional) |
| `otaCode` | Filter by OTA code (e.g. `BOOKING`, `EXPEDIA`) |
| `otaConnectionId` | Filter by OTA connection ID (when coming from “View Logs” for one OTA) |

**Example:**

```text
GET /api/v1/channel-manager/sync-logs?page=1&pageSize=50&action=rate_update&status=success&dateFrom=2025-02-01&dateTo=2025-02-20
```

---

## 2. Dropdown filter values

Send these exact values from the UI dropdowns.

**Action dropdown:**

- `rate_update`
- `availability_update`
- `restriction_update`
- `promotion_sync`
- `booking_import`
- `connection`
- `bulk_sync`

**Status dropdown:**

- `success`
- `error`
- `warning`
- `pending`

When the user changes a dropdown, update the query params and refetch (e.g. set `action` or `status` and call the API again).

---

## 3. Response shape

The backend returns:

```json
{
  "success": true,
  "data": {
    "items": [ ... ],
    "total": 250,
    "page": 1,
    "pageSize": 50,
    "totalPages": 5
  }
}
```

**Each item in `data.items`:**

| Field       | Type   | Description |
|------------|--------|-------------|
| `id`       | number | Sync log ID |
| `timestamp`| string | Full ISO datetime (e.g. `2025-02-20T10:30:00`) |
| `date`     | string | **Date only** `YYYY-MM-DD` — use this for the “Date” column |
| `otaCode`  | string | e.g. `BOOKING` |
| `otaName`  | string | Display name for channel |
| `action`   | string | Same as filter values above |
| `status`   | string | `success` \| `error` \| `warning` \| `pending` |
| `message`  | string | Short description |
| `details`  | object \| null | Optional (e.g. `recordsProcessed`, `duration`, etc.) |

---

## 4. What to change in the frontend

### 4.1 Show dates

- Add or use a **Date** column in the Sync Logs table.
- Use **`item.date`** for that column (already `YYYY-MM-DD`).
- Optionally use **`item.timestamp`** for a “Time” or “Date & time” column (format as needed, e.g. `new Date(item.timestamp).toLocaleString()`).

### 4.2 Pagination

- Use **`pageSize`** in the request (not `page_size`).
- Use **`data.page`**, **`data.pageSize`**, **`data.total`**, **`data.totalPages`** for pagination UI and “Page X of Y” / page size selector.

### 4.3 Dropdown filters

- **Action dropdown:** On change, set `action` to one of the values in section 2 (or clear for “All”). Then refetch with the new params.
- **Status dropdown:** On change, set `status` to one of the values in section 2 (or clear for “All”). Then refetch.
- Optional: add **date range** inputs and send **`dateFrom`** and **`dateTo`** as `YYYY-MM-DD` when set.

### 4.4 Export

- Export endpoint supports the same filters. Use the same query param names:
  - `format`, `otaCode`, `otaConnectionId`, `action`, `status`, **`dateFrom`**, **`dateTo`**
- So when the user has filters (including date range) applied, pass those same values to the export URL so the file matches the list.

---

## 5. TypeScript types (optional)

```ts
interface SyncLogItem {
  id: number;
  timestamp: string | null;  // ISO datetime
  date: string | null;       // YYYY-MM-DD
  otaCode: string;
  otaName: string;
  action: string;
  status: 'success' | 'error' | 'warning' | 'pending';
  message: string;
  details: {
    recordsProcessed?: number;
    recordsFailed?: number;
    duration?: number;
    changesCount?: number;
    dateRange?: string;
  } | null;
}

interface SyncLogsResponse {
  success: boolean;
  data: {
    items: SyncLogItem[];
    total: number;
    page: number;
    pageSize: number;
    totalPages: number;
  };
}
```

---

## 6. Summary checklist

- [ ] Use **`pageSize`** (camelCase) in the sync-logs list request.
- [ ] Add/use a **Date** column and display **`item.date`** (and optionally **`item.timestamp`**).
- [ ] Action dropdown: send **`action`** with one of the allowed values; refetch on change.
- [ ] Status dropdown: send **`status`** with one of the allowed values; refetch on change.
- [ ] Optional: add date range and send **`dateFrom`** / **`dateTo`** as `YYYY-MM-DD`.
- [ ] Read list from **`response.data.items`** and pagination from **`response.data`**.
- [ ] Export: pass **`dateFrom`** and **`dateTo`** when user has applied a date range.

No other backend APIs or Channel Manager tabs are affected by these changes.
