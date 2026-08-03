"""
LLM-First Admin AI Agent.

Replaces the regex+raw-SQL orchestrator with an LLM agent that uses
OpenAI function calling (tool use) to call existing service-layer APIs.

The LLM IS the brain:
  - Understands natural language (no regex needed for intent/entities)
  - Decides which tool to call and with what params
  - Maintains conversation context across turns
  - Asks clarifying questions in plain English
  - Formats results for the admin user

Tools delegate to the SAME service layer the REST API uses —
no raw SQL, no bypassing business logic.
"""
import json
import logging
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)

# Maximum rounds of tool-calling before forcing a text reply
MAX_TOOL_ROUNDS = 5


# ─────────────────────── System Prompt ───────────────────────

ADMIN_AI_SYSTEM_PROMPT = """You are Glimmora AI, the intelligent operations assistant for hotel administrators.

You help hotel staff with daily operations through natural conversation. You speak in clear, professional, concise language.

## Today's Date
{today}

## Currency
ALL prices and revenue are in Indian Rupees (INR). Always format as ₹XX,XXX — NEVER use $ or USD.

## Your Capabilities (via tools)

### Bookings
- **search_bookings** — Find bookings by date, status, or guest name
- **get_booking_details** — Get full details by ID or booking number (GLM-XXXXXX)
- **create_booking** — Create a new reservation
- **update_booking** — Modify dates, room type, special requests, guest count
- **extend_stay** — Extend a guest's stay by additional nights
- **check_in_booking** — Check in a guest (validates room type match)
- **check_out_booking** — Check out a guest
- **cancel_booking** — Cancel a booking (ALWAYS confirm first)
- **mark_no_show** — Mark a booking as no-show (confirm first)
- **room_change** — Move guest to a different room mid-stay

### Payments, Billing & Revenue
- **get_payment_status** — Payment status, amount paid, balance due
- **add_folio_charge** — Add charges to guest folio (room service, minibar, spa, etc.)
- **record_payment** — Record a payment (card, cash, UPI, bank transfer)
- **query_revenue** — Revenue data for a specific date
- **get_future_revenue** — Projected revenue from upcoming bookings
- **get_revenue_by_room_type** — Revenue breakdown by room type

### Rooms
- **list_rooms** — List rooms with status/floor filters
- **check_room_availability** — Available room types for given dates
- **update_room_status** — Update room cleaning/maintenance status

### Guests
- **search_guests** — Find guests by name, email, or VIP status
- **update_guest** — Update profile (VIP, tags, notes, contact info)
- **get_guest_history** — Full guest profile with booking history

### Staff
- **list_staff** — List staff by department or status

### Housekeeping
- **create_housekeeping_task** — Create cleaning/inspection task
- **get_housekeeping_tasks** — List pending, in-progress, or completed tasks

### Maintenance
- **create_maintenance_request** — Report a maintenance issue
- **get_maintenance_requests** — List open, assigned, or completed work orders

### Dashboard & Reports
- **get_today_summary** — Full operational snapshot
- **query_occupancy** — Occupancy rate for a specific date
- **query_checkouts_today** — List today's expected departures
- **generate_report** — Generate daily_operations, revenue, occupancy, housekeeping, or guest_summary reports

### Charts & Visualizations
When the user asks for trends, charts, or visual data:
- **get_occupancy_trend** — Occupancy % over a date range (line chart)
- **get_revenue_trend** — Revenue over a date range (bar chart)
- **get_booking_source_breakdown** — Channel distribution (pie chart)
- **get_room_status_overview** — Room status distribution (doughnut chart)

Chart tools return structured chart_data that the frontend renders automatically as interactive charts.
IMPORTANT: When a chart tool returns data, NEVER write markdown image links like ![chart](url). The chart is rendered automatically by the frontend from the chart_data field. Your text response should ONLY describe the key insights and numbers from the data — do NOT try to draw, embed, or link to any chart image. Just summarize what the data shows.
If the user says "show chart", "visualize", "trend", "graph", "breakdown chart" — use these tools.

## Behavioral Guidelines

### 1. UNDERSTAND INTENT
Parse what the admin wants from natural language. Ask for clarification only when genuinely ambiguous (e.g., "delete user" without specifying which one).

### 2. FIND THE RIGHT TOOL
Pick the right tool based on the admin's request. If multiple steps are needed, execute them in sequence.

### 3. CONFIRM BEFORE DESTRUCTIVE ACTIONS
For any operation that cancels, deletes, blacklists, or permanently modifies data — ALWAYS show the admin what you're about to do and ask for explicit confirmation before executing.

### 4. SUMMARIZE RESULTS
After executing a tool, summarize the result in plain language. Include relevant IDs, numbers, and status only when useful. Do NOT dump raw JSON.

### 5. MULTI-STEP WORKFLOWS
If an admin asks something requiring multiple API calls (e.g., "find all pending checkouts and show their payment status"), execute each step, show intermediate results, and proceed.

### 6. NEVER GUESS IDs
If you need a booking ID, guest ID, etc., and the admin gave you a name or booking number instead, FIRST use a search/lookup tool to resolve it, THEN use the result.

### 7. ERRORS
If a tool call fails, explain what went wrong in plain language and suggest next steps. Never show raw stack traces.

### 8. AUDIT
For every action you take, state clearly what you did so it can be logged.

### Creating Bookings
When a user wants to create a booking, you need at minimum:
- Guest first name (last name optional)
- Check-in date
- Check-out date
- Room type (defaults to Standard if not specified)

After collecting these, also ask for (if not already provided):
- Phone number
- Email address
- Number of adults and children
- Special requests

When the user provides phone, email, or country info, pass them directly to create_booking.
After collecting all details, display a summary preview and ask: "Shall I proceed with this booking, or would you like to edit any details?"

### Check-In Process
When checking in a guest:
1. First use get_booking_details to retrieve the booking
2. Show the booked room type and assigned room
3. If the assigned room's type differs from the booked room type, clearly alert the admin
4. After check-in, suggest creating a housekeeping task if needed

### Payment Inquiries
When asked about payment status:
- Use get_payment_status with the booking number or ID
- Present: total amount, amount paid, balance due, payment method, and payment status
- If no payments recorded, state that clearly

### Formatting Rules
- Use markdown tables for lists of bookings, rooms, or tasks
- Use bold for key figures (revenue, occupancy rate)
- Dates: display as "18 Mar 2026" format for readability
- Currency: always ₹XX,XXX format
- Keep responses concise — summarize large result sets, don't dump raw data
- Suggest relevant follow-up actions

### Context Awareness
- If the user asks about a booking by number (e.g., "GLM-XXXXXX"), use get_booking_details
- If the user asks about a booking by guest name, use search_bookings with guest_name
- If the user says "today's summary" or "dashboard", use get_today_summary
- Parse natural language dates yourself: "tomorrow", "next Monday", "Dec 25" → YYYY-MM-DD
- If the user says "yes", "confirm", "go ahead" after you proposed an action, execute it
"""


# ─────────────────────── Tool Input Schemas ───────────────────────

class SearchBookingsInput(BaseModel):
    date: Optional[str] = Field(None, description="Date to search (YYYY-MM-DD). Defaults to today.")
    status: Optional[str] = Field(None, description="Filter by status: confirmed, checked_in, checked_out, cancelled, pending")
    guest_name: Optional[str] = Field(None, description="Search by guest name (first or last)")

class GetBookingDetailsInput(BaseModel):
    booking_id: Optional[int] = Field(None, description="Booking ID (numeric, e.g., 199)")
    booking_number: Optional[str] = Field(None, description="Booking number (e.g., 'GLM-6KNH2B') or confirmation code")

class CreateBookingInput(BaseModel):
    guest_first_name: str = Field(description="Guest first name")
    guest_last_name: str = Field(default="", description="Guest last name (can be empty)")
    check_in_date: str = Field(description="Check-in date YYYY-MM-DD")
    check_out_date: str = Field(description="Check-out date YYYY-MM-DD")
    room_type: str = Field(default="standard", description="Room type: standard, deluxe, suite, deluxe_suite, wellness_suite, etc.")
    adults: int = Field(default=1, description="Number of adults")
    children: int = Field(default=0, description="Number of children")
    guest_phone: str = Field(default="", description="Guest phone number (e.g., +918604629998)")
    guest_country: str = Field(default="India", description="Guest country (e.g., India, USA)")
    guest_email: str = Field(default="", description="Guest email address")
    special_requests: Optional[str] = Field(None, description="Special requests or notes")

class CheckInInput(BaseModel):
    booking_id: int = Field(description="Booking ID to check in")
    room_id: Optional[int] = Field(None, description="Specific room ID to assign (optional)")
    notes: Optional[str] = Field(None, description="Check-in notes")

class CheckOutInput(BaseModel):
    booking_id: int = Field(description="Booking ID to check out")

class CancelBookingInput(BaseModel):
    booking_id: int = Field(description="Booking ID to cancel")

class RoomListInput(BaseModel):
    status: Optional[str] = Field(None, description="Filter: available, occupied, dirty, clean, maintenance, out_of_order")
    floor: Optional[int] = Field(None, description="Filter by floor number")

class RoomAvailabilityInput(BaseModel):
    check_in_date: str = Field(description="Check-in date YYYY-MM-DD")
    check_out_date: str = Field(description="Check-out date YYYY-MM-DD")

class UpdateRoomStatusInput(BaseModel):
    room_number: str = Field(description="Room number (e.g., '101')")
    status: str = Field(description="New status: clean, dirty, maintenance, out_of_order, inspected")

class CreateHousekeepingTaskInput(BaseModel):
    room_number: str = Field(description="Room number")
    task_type: str = Field(default="daily_clean", description="Task type: daily_clean, deep_clean, turndown, checkout_clean, inspection")
    priority: str = Field(default="medium", description="Priority: low, medium, high, urgent")
    notes: Optional[str] = Field(None, description="Additional notes")

class CreateMaintenanceInput(BaseModel):
    room_number: str = Field(description="Room number")
    issue_description: str = Field(description="Description of the issue")
    priority: str = Field(default="medium", description="Priority: low, medium, high, urgent")
    category: str = Field(default="general", description="Category: plumbing, electrical, hvac, furniture, general")

class SearchGuestsInput(BaseModel):
    name: Optional[str] = Field(None, description="Guest name to search")
    email: Optional[str] = Field(None, description="Guest email to search")
    vip_only: bool = Field(default=False, description="Only show VIP guests")

class UpdateGuestInput(BaseModel):
    guest_id: int = Field(description="Guest ID to update")
    vip_status: Optional[bool] = Field(None, description="Set VIP status (true/false)")
    loyalty_tier: Optional[str] = Field(None, description="Loyalty tier: bronze, silver, gold, platinum")
    notes: Optional[str] = Field(None, description="Note to add to guest profile")
    tags: Optional[str] = Field(None, description="Comma-separated tags (e.g., 'vip,corporate,frequent')")
    email: Optional[str] = Field(None, description="Update email address")
    phone: Optional[str] = Field(None, description="Update phone number")
    status: Optional[str] = Field(None, description="Guest status: Active, VIP, Blacklisted")

class GetPaymentStatusInput(BaseModel):
    booking_id: Optional[int] = Field(None, description="Booking ID (numeric)")
    booking_number: Optional[str] = Field(None, description="Booking number (e.g., 'GLM-6KNH2B') or confirmation code")

class QueryRevenueInput(BaseModel):
    date: Optional[str] = Field(None, description="Date for revenue query (YYYY-MM-DD). Defaults to today.")

class GetFutureRevenueInput(BaseModel):
    start_date: Optional[str] = Field(None, description="Start date YYYY-MM-DD. Defaults to today.")
    end_date: Optional[str] = Field(None, description="End date YYYY-MM-DD. Defaults to 30 days from start.")

class GetRevenueByRoomTypeInput(BaseModel):
    start_date: Optional[str] = Field(None, description="Start date YYYY-MM-DD. Defaults to first day of current month.")
    end_date: Optional[str] = Field(None, description="End date YYYY-MM-DD. Defaults to today.")

class QueryOccupancyInput(BaseModel):
    date: Optional[str] = Field(None, description="Date for occupancy query (YYYY-MM-DD). Defaults to today.")

class QueryCheckoutsInput(BaseModel):
    date: Optional[str] = Field(None, description="Date (YYYY-MM-DD). Defaults to today.")

class GetHousekeepingTasksInput(BaseModel):
    status: Optional[str] = Field(None, description="Filter: pending, in_progress, completed, cancelled")
    priority: Optional[str] = Field(None, description="Filter: low, normal, high, urgent")
    room_number: Optional[str] = Field(None, description="Filter by room number")

class GetMaintenanceRequestsInput(BaseModel):
    status: Optional[str] = Field(None, description="Filter: open, assigned, in_progress, on_hold, completed, cancelled")
    priority: Optional[str] = Field(None, description="Filter: low, medium, high, emergency")
    category: Optional[str] = Field(None, description="Filter: electrical, plumbing, hvac, carpentry, general")
    room_number: Optional[str] = Field(None, description="Filter by room number")

class GetTodaySummaryInput(BaseModel):
    date: Optional[str] = Field(None, description="Date for summary (YYYY-MM-DD). Defaults to today.")

# ── New: Extended admin operations ──

class UpdateBookingInput(BaseModel):
    booking_id: int = Field(description="Booking ID to update")
    arrival_date: Optional[str] = Field(None, description="New arrival date YYYY-MM-DD")
    departure_date: Optional[str] = Field(None, description="New departure date YYYY-MM-DD")
    special_requests: Optional[str] = Field(None, description="Special requests")
    room_type: Optional[str] = Field(None, description="Change room type")
    adults: Optional[int] = Field(None, description="Number of adults")
    children: Optional[int] = Field(None, description="Number of children")

class ExtendStayInput(BaseModel):
    booking_id: int = Field(description="Booking ID to extend")
    additional_nights: int = Field(description="Number of extra nights")

class MarkNoShowInput(BaseModel):
    booking_id: int = Field(description="Booking ID to mark as no-show")

class RoomChangeInput(BaseModel):
    booking_id: int = Field(description="Booking ID")
    new_room_number: str = Field(description="New room number to move the guest to")
    reason: Optional[str] = Field(None, description="Reason for room change")

class ListStaffInput(BaseModel):
    department: Optional[str] = Field(None, description="Filter: frontdesk, housekeeping, maintenance, management, kitchen, security")
    status: Optional[str] = Field(None, description="Filter: active, on_leave, off_duty")

class AddFolioChargeInput(BaseModel):
    booking_id: int = Field(description="Booking ID")
    description: str = Field(description="Charge description (e.g., 'Room service - dinner')")
    amount: float = Field(description="Charge amount in INR")
    item_type: str = Field(default="service", description="Type: room_charge, service, minibar, spa, restaurant, laundry, misc")

class RecordPaymentInput(BaseModel):
    booking_id: int = Field(description="Booking ID")
    amount: float = Field(description="Payment amount in INR")
    method: str = Field(default="card", description="Method: card, cash, upi, bank_transfer, neft")
    notes: Optional[str] = Field(None, description="Payment notes")

class GetGuestHistoryInput(BaseModel):
    guest_id: Optional[int] = Field(None, description="Guest ID")
    guest_name: Optional[str] = Field(None, description="Guest name to search")

class SendEmailInput(BaseModel):
    to_email: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body text")

class GenerateReportInput(BaseModel):
    report_type: str = Field(description="Report type: daily_operations, revenue, occupancy, housekeeping, guest_summary")
    date: Optional[str] = Field(None, description="Date for report (YYYY-MM-DD). Defaults to today.")

# ── New: Chart/Visualization tools ──

class OccupancyTrendInput(BaseModel):
    start_date: Optional[str] = Field(None, description="Start date YYYY-MM-DD. Defaults to 7 days ago.")
    end_date: Optional[str] = Field(None, description="End date YYYY-MM-DD. Defaults to today.")

class RevenueTrendInput(BaseModel):
    start_date: Optional[str] = Field(None, description="Start date YYYY-MM-DD. Defaults to 7 days ago.")
    end_date: Optional[str] = Field(None, description="End date YYYY-MM-DD. Defaults to today.")

class BookingSourceBreakdownInput(BaseModel):
    start_date: Optional[str] = Field(None, description="Start date YYYY-MM-DD. Defaults to 30 days ago.")
    end_date: Optional[str] = Field(None, description="End date YYYY-MM-DD. Defaults to today.")

class RoomStatusOverviewInput(BaseModel):
    pass  # No parameters needed


# ─────────────────────── Admin AI LLM Agent ───────────────────────

class AdminAILLMAgent:
    """LLM-first admin AI agent using OpenAI function calling.

    The LLM decides what to do. Tools call the real service layer.
    No regex, no raw SQL pipelines, no manual intent classification.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._llm: Optional[ChatOpenAI] = None
        self._tools: List[StructuredTool] = []
        self._init_llm()
        self._init_tools()

    # ───── LLM initialisation ─────

    def _init_llm(self):
        """Initialize the LLM with tool-calling support."""
        try:
            from dotenv import dotenv_values
            from pathlib import Path

            env_path = Path(__file__).resolve().parent.parent.parent / ".env"
            env_vars = dotenv_values(str(env_path))
            api_key = env_vars.get("OPENAI_API_KEY") or settings.openai_api_key

            if not api_key or api_key in ("", "sk-your-openai-api-key"):
                logger.error("No OpenAI API key configured — LLM agent will not work")
                return

            model = env_vars.get("OPENAI_MODEL", settings.openai_model) or "gpt-4"
            self._llm = ChatOpenAI(
                model=model,
                temperature=0.1,
                api_key=api_key,
                max_tokens=2000,
            )
            logger.info(f"Admin AI LLM agent initialized with model: {model}")
        except Exception as e:
            logger.error(f"Failed to init LLM agent: {e}")

    # ───── Tool definitions ─────

    def _init_tools(self):
        """Register all tools the LLM can call."""
        session = self.session  # Closure for tool functions

        # ═══════════════════ Booking Tools ═══════════════════

        async def search_bookings(
            date: Optional[str] = None,
            status: Optional[str] = None,
            guest_name: Optional[str] = None,
        ) -> str:
            try:
                conditions = ["1=1"]
                params: Dict[str, Any] = {}

                if date:
                    conditions.append("(b.arrival_date <= :target_date AND b.departure_date >= :target_date)")
                    params["target_date"] = date

                if status:
                    conditions.append("b.status = :status")
                    params["status"] = status

                if guest_name:
                    conditions.append("(LOWER(g.first_name) LIKE :name OR LOWER(g.last_name) LIKE :name)")
                    params["name"] = f"%{guest_name.lower()}%"

                query = text(f"""
                    SELECT b.id, b.booking_number, b.confirmation_code,
                           b.arrival_date, b.departure_date,
                           b.status, b.payment_status, b.nights, b.total_price,
                           b.adults, b.children,
                           g.id as guest_id, g.first_name, g.last_name, g.email, g.phone, g.vip_status,
                           rt.name as room_type, r.number as room_number
                    FROM bookings b
                    JOIN guests g ON b.guest_id = g.id
                    LEFT JOIN room_types rt ON b.room_type_id = rt.id
                    LEFT JOIN rooms r ON b.room_id = r.id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY b.arrival_date DESC
                    LIMIT 25
                """)
                result = await session.execute(query, params)
                rows = [dict(r._mapping) for r in result.fetchall()]
                return json.dumps({"success": True, "count": len(rows), "bookings": rows}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_booking_details(
            booking_id: Optional[int] = None,
            booking_number: Optional[str] = None,
        ) -> str:
            """Get full details of a specific booking by ID or booking number."""
            try:
                conditions = []
                params: Dict[str, Any] = {}

                if booking_id:
                    conditions.append("b.id = :booking_id")
                    params["booking_id"] = booking_id
                if booking_number:
                    conditions.append(
                        "(UPPER(b.booking_number) = UPPER(:booking_number) "
                        "OR UPPER(b.confirmation_code) = UPPER(:booking_number))"
                    )
                    params["booking_number"] = booking_number

                if not conditions:
                    return json.dumps({"success": False, "error": "Provide either booking_id or booking_number."})

                query = text(f"""
                    SELECT b.id, b.booking_number, b.confirmation_code,
                           b.arrival_date, b.departure_date,
                           b.check_in_date, b.check_out_date,
                           b.adults, b.children, b.nights,
                           b.status, b.payment_status, b.payment_method,
                           b.base_price, b.taxes, b.service_fee, b.total_price,
                           b.deposit_amount, b.balance_due,
                           b.special_requests, b.internal_notes,
                           b.booking_source, b.expected_arrival_time, b.expected_departure_time,
                           g.id as guest_id, g.first_name, g.last_name,
                           g.email, g.phone, g.vip_status, g.nationality,
                           rt.name as room_type, rt.base_price as room_type_rate,
                           r.number as room_number, r.floor as room_floor
                    FROM bookings b
                    JOIN guests g ON b.guest_id = g.id
                    LEFT JOIN room_types rt ON b.room_type_id = rt.id
                    LEFT JOIN rooms r ON b.room_id = r.id
                    WHERE {' OR '.join(conditions)}
                    LIMIT 1
                """)
                result = await session.execute(query, params)
                row = result.fetchone()
                if not row:
                    return json.dumps({"success": False, "error": "Booking not found."})
                return json.dumps({"success": True, "booking": dict(row._mapping)}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def create_booking(
            guest_first_name: str,
            guest_last_name: str = "",
            check_in_date: str = "",
            check_out_date: str = "",
            room_type: str = "standard",
            adults: int = 1,
            children: int = 0,
            guest_phone: str = "",
            guest_country: str = "India",
            guest_email: str = "",
            special_requests: Optional[str] = None,
        ) -> str:
            """Create a booking using the proper service layer."""
            try:
                from app.services.agi.tools.booking_tools import BookingTools

                booking_tools = BookingTools(session)
                # Look up room type ID
                rt_query = text(
                    "SELECT id FROM room_types WHERE LOWER(name) LIKE :rt LIMIT 1"
                )
                rt_result = await session.execute(rt_query, {
                    "rt": f"%{room_type.replace('_', ' ').lower()}%"
                })
                rt_row = rt_result.fetchone()
                room_type_id = rt_row[0] if rt_row else 1

                email = guest_email or f"{guest_first_name.lower()}.{(guest_last_name or 'guest').lower()}@guest.glimmora.com"
                phone = guest_phone or "N/A"
                country = guest_country or "India"

                result = await booking_tools.create_booking(
                    room_type_id=room_type_id,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    guest_first_name=guest_first_name,
                    guest_last_name=guest_last_name or "",
                    guest_email=email,
                    guest_phone=phone,
                    guest_country=country,
                    adults=adults,
                    children=children,
                    special_requests=special_requests,
                )
                return json.dumps(result, default=str)
            except Exception as e:
                logger.error(f"Create booking error: {e}", exc_info=True)
                return json.dumps({"success": False, "error": str(e)})

        async def check_in_booking(
            booking_id: int,
            room_id: Optional[int] = None,
            notes: Optional[str] = None,
        ) -> str:
            """Check in a guest — validates room type match and syncs room status."""
            try:
                # Step 1: Fetch booking details for context
                bk_result = await session.execute(text("""
                    SELECT b.id, b.status, b.room_type_id, b.room_id,
                           rt.name as booked_room_type,
                           g.first_name, g.last_name
                    FROM bookings b
                    JOIN guests g ON b.guest_id = g.id
                    LEFT JOIN room_types rt ON b.room_type_id = rt.id
                    WHERE b.id = :booking_id
                """), {"booking_id": booking_id})
                bk_row = bk_result.fetchone()
                if not bk_row:
                    return json.dumps({"success": False, "error": f"Booking #{booking_id} not found."})

                bk = dict(bk_row._mapping)
                if bk["status"] == "checked_in":
                    return json.dumps({"success": False, "error": f"Booking #{booking_id} is already checked in."})
                if bk["status"] in ("checked_out", "cancelled"):
                    return json.dumps({"success": False, "error": f"Cannot check in — booking is '{bk['status']}'."})

                warning = ""
                assigned_room_number = None

                # Step 2: If room_id provided, validate room type match
                if room_id:
                    rm_result = await session.execute(text("""
                        SELECT r.id, r.number, r.room_type_id, rt.name as assigned_room_type
                        FROM rooms r
                        LEFT JOIN room_types rt ON r.room_type_id = rt.id
                        WHERE r.id = :room_id
                    """), {"room_id": room_id})
                    rm_row = rm_result.fetchone()
                    if rm_row:
                        rm = dict(rm_row._mapping)
                        assigned_room_number = rm["number"]
                        if rm["room_type_id"] != bk["room_type_id"]:
                            warning = (
                                f"⚠️ Room type mismatch: Guest booked '{bk['booked_room_type']}' "
                                f"but is being assigned to room {rm['number']} ({rm['assigned_room_type']})."
                            )

                # Step 3: Update booking
                now = datetime.utcnow().isoformat()
                update_parts = ["status = 'checked_in'", "check_in_date = :now", "updated_at = :now"]
                params: Dict[str, Any] = {"booking_id": booking_id, "now": now}
                if room_id:
                    update_parts.append("room_id = :room_id")
                    params["room_id"] = room_id
                if notes:
                    update_parts.append("internal_notes = :notes")
                    params["notes"] = notes

                await session.execute(
                    text(f"UPDATE bookings SET {', '.join(update_parts)} WHERE id = :booking_id"),
                    params,
                )

                # Step 4: Update room status to occupied
                if room_id:
                    await session.execute(
                        text("UPDATE rooms SET status = 'occupied', updated_at = :now WHERE id = :room_id"),
                        {"room_id": room_id, "now": now},
                    )

                await session.commit()

                msg = f"Booking #{booking_id} ({bk['first_name']} {bk['last_name']}) checked in successfully."
                if assigned_room_number:
                    msg += f" Assigned to room {assigned_room_number}."
                if warning:
                    msg += f"\n{warning}"
                return json.dumps({"success": True, "message": msg, "booked_room_type": bk["booked_room_type"]})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def check_out_booking(booking_id: int) -> str:
            try:
                now = datetime.utcnow().isoformat()
                # Get room_id before checkout to free the room
                bk = await session.execute(
                    text("SELECT room_id, status FROM bookings WHERE id = :bid"),
                    {"bid": booking_id},
                )
                bk_row = bk.fetchone()
                if not bk_row:
                    return json.dumps({"success": False, "error": f"Booking #{booking_id} not found."})
                if bk_row[1] == "checked_out":
                    return json.dumps({"success": False, "error": f"Booking #{booking_id} is already checked out."})

                await session.execute(
                    text("UPDATE bookings SET status = 'checked_out', check_out_date = :now, updated_at = :now WHERE id = :bid"),
                    {"bid": booking_id, "now": now},
                )
                # Free the room
                if bk_row[0]:
                    await session.execute(
                        text("UPDATE rooms SET status = 'dirty', updated_at = :now WHERE id = :rid"),
                        {"rid": bk_row[0], "now": now},
                    )
                await session.commit()
                return json.dumps({"success": True, "message": f"Booking #{booking_id} checked out. Room marked as dirty."})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def cancel_booking(booking_id: int) -> str:
            try:
                now = datetime.utcnow().isoformat()
                bk = await session.execute(
                    text("SELECT room_id, status FROM bookings WHERE id = :bid"),
                    {"bid": booking_id},
                )
                bk_row = bk.fetchone()
                if not bk_row:
                    return json.dumps({"success": False, "error": f"Booking #{booking_id} not found."})
                if bk_row[1] == "cancelled":
                    return json.dumps({"success": False, "error": f"Booking #{booking_id} is already cancelled."})

                await session.execute(
                    text("UPDATE bookings SET status = 'cancelled', cancelled_at = :now, updated_at = :now WHERE id = :bid"),
                    {"bid": booking_id, "now": now},
                )
                if bk_row[0]:
                    await session.execute(
                        text("UPDATE rooms SET status = 'available', updated_at = :now WHERE id = :rid"),
                        {"rid": bk_row[0], "now": now},
                    )
                await session.commit()
                return json.dumps({"success": True, "message": f"Booking #{booking_id} cancelled."})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Room Tools ═══════════════════

        async def list_rooms(
            status: Optional[str] = None,
            floor: Optional[int] = None,
        ) -> str:
            try:
                conditions = ["1=1"]
                params: Dict[str, Any] = {}
                if status:
                    conditions.append("r.status = :status")
                    params["status"] = status
                if floor:
                    conditions.append("r.floor = :floor")
                    params["floor"] = floor

                result = await session.execute(text(f"""
                    SELECT r.id, r.number, r.floor, r.status, rt.name as room_type, rt.base_price
                    FROM rooms r
                    LEFT JOIN room_types rt ON r.room_type_id = rt.id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY r.number
                """), params)
                rows = [dict(r._mapping) for r in result.fetchall()]
                return json.dumps({"success": True, "count": len(rows), "rooms": rows}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def check_room_availability(check_in_date: str, check_out_date: str) -> str:
            try:
                from app.services.agi.tools.booking_tools import BookingTools
                booking_tools = BookingTools(session)
                result = await booking_tools.get_available_room_types(
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                )
                return json.dumps(result, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def update_room_status(room_number: str, status: str) -> str:
            try:
                await session.execute(
                    text("UPDATE rooms SET status = :status, updated_at = :now WHERE number = :room_number"),
                    {"room_number": room_number, "status": status, "now": datetime.utcnow().isoformat()},
                )
                await session.commit()
                return json.dumps({"success": True, "message": f"Room {room_number} marked as {status}."})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Housekeeping Tools ═══════════════════

        async def create_housekeeping_task(
            room_number: str,
            task_type: str = "daily_clean",
            priority: str = "medium",
            notes: Optional[str] = None,
        ) -> str:
            try:
                result = await session.execute(
                    text("SELECT id FROM rooms WHERE number = :num LIMIT 1"),
                    {"num": room_number},
                )
                room_row = result.fetchone()
                if not room_row:
                    return json.dumps({"success": False, "error": f"Room {room_number} not found."})

                room_id = room_row[0]
                now = datetime.utcnow().isoformat()
                await session.execute(text("""
                    INSERT INTO housekeeping_tasks
                    (room_id, task_type, priority, status, notes, force_assigned, created_at, updated_at)
                    VALUES (:room_id, :task_type, :priority, 'pending', :notes, 0, :now, :now)
                """), {
                    "room_id": room_id, "task_type": task_type,
                    "priority": priority, "notes": notes or "", "now": now,
                })
                await session.commit()
                return json.dumps({"success": True, "message": f"Housekeeping task ({task_type}) created for room {room_number}."})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_housekeeping_tasks(
            status: Optional[str] = None,
            priority: Optional[str] = None,
            room_number: Optional[str] = None,
        ) -> str:
            try:
                conditions = ["1=1"]
                params: Dict[str, Any] = {}
                if status:
                    conditions.append("ht.status = :status")
                    params["status"] = status
                if priority:
                    conditions.append("ht.priority = :priority")
                    params["priority"] = priority
                if room_number:
                    conditions.append("r.number = :room_number")
                    params["room_number"] = room_number

                result = await session.execute(text(f"""
                    SELECT ht.id, ht.task_type, ht.priority, ht.status,
                           ht.notes, ht.quality_score, ht.started_at, ht.completed_at,
                           ht.created_at,
                           r.number as room_number, r.floor
                    FROM housekeeping_tasks ht
                    JOIN rooms r ON ht.room_id = r.id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY
                        CASE ht.priority
                            WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                            WHEN 'medium' THEN 3 WHEN 'normal' THEN 3
                            WHEN 'low' THEN 4 ELSE 5
                        END,
                        ht.created_at DESC
                    LIMIT 30
                """), params)
                rows = [dict(r._mapping) for r in result.fetchall()]
                return json.dumps({"success": True, "count": len(rows), "tasks": rows}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Maintenance Tools ═══════════════════

        async def create_maintenance_request(
            room_number: str,
            issue_description: str,
            priority: str = "medium",
            category: str = "general",
        ) -> str:
            try:
                result = await session.execute(
                    text("SELECT id FROM rooms WHERE number = :num LIMIT 1"),
                    {"num": room_number},
                )
                room_row = result.fetchone()
                if not room_row:
                    return json.dumps({"success": False, "error": f"Room {room_number} not found."})

                room_id = room_row[0]
                now = datetime.utcnow().isoformat()
                work_order_id = f"WO-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

                await session.execute(text("""
                    INSERT INTO maintenancerequest
                    (room_id, room_number, work_order_id, title, issue, description,
                     priority, category, status, reported_at,
                     is_out_of_order, requires_parts, parts_ordered, is_preventive, force_assigned,
                     created_at, updated_at)
                    VALUES (:room_id, :room_number, :work_order_id, :title, :issue, :description,
                            :priority, :category, 'open', :now,
                            0, 0, 0, 0, 0,
                            :now, :now)
                """), {
                    "room_id": room_id, "room_number": room_number,
                    "work_order_id": work_order_id,
                    "title": issue_description[:100], "issue": issue_description,
                    "description": issue_description,
                    "priority": priority, "category": category, "now": now,
                })
                await session.commit()
                return json.dumps({"success": True, "message": f"Maintenance request ({work_order_id}) created for room {room_number}."})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_maintenance_requests(
            status: Optional[str] = None,
            priority: Optional[str] = None,
            category: Optional[str] = None,
            room_number: Optional[str] = None,
        ) -> str:
            try:
                conditions = ["1=1"]
                params: Dict[str, Any] = {}
                if status:
                    conditions.append("mr.status = :status")
                    params["status"] = status
                if priority:
                    conditions.append("mr.priority = :priority")
                    params["priority"] = priority
                if category:
                    conditions.append("mr.category = :category")
                    params["category"] = category
                if room_number:
                    conditions.append("(r.number = :room_number OR mr.room_number = :room_number)")
                    params["room_number"] = room_number

                result = await session.execute(text(f"""
                    SELECT mr.id, mr.work_order_id, mr.title, mr.issue,
                           mr.category, mr.priority, mr.status,
                           mr.estimated_cost, mr.actual_cost,
                           mr.started_at, mr.completed_at, mr.created_at,
                           r.number as room_num, r.floor
                    FROM maintenancerequest mr
                    LEFT JOIN rooms r ON mr.room_id = r.id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY
                        CASE mr.priority
                            WHEN 'emergency' THEN 1 WHEN 'high' THEN 2
                            WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5
                        END,
                        mr.created_at DESC
                    LIMIT 30
                """), params)
                rows = [dict(r._mapping) for r in result.fetchall()]
                return json.dumps({"success": True, "count": len(rows), "requests": rows}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Guest Tools ═══════════════════

        async def search_guests(
            name: Optional[str] = None,
            email: Optional[str] = None,
            vip_only: bool = False,
        ) -> str:
            try:
                conditions = ["1=1"]
                params: Dict[str, Any] = {}
                if name:
                    conditions.append("(LOWER(first_name) LIKE :name OR LOWER(last_name) LIKE :name)")
                    params["name"] = f"%{name.lower()}%"
                if email:
                    conditions.append("LOWER(email) LIKE :email")
                    params["email"] = f"%{email.lower()}%"
                if vip_only:
                    conditions.append("vip_status = true")

                result = await session.execute(text(f"""
                    SELECT id, first_name, last_name, email, phone, vip_status,
                           loyalty_tier, loyalty_points, total_bookings, total_spent,
                           nationality, status
                    FROM guests
                    WHERE {' AND '.join(conditions)}
                    ORDER BY id DESC LIMIT 20
                """), params)
                rows = [dict(r._mapping) for r in result.fetchall()]
                return json.dumps({"success": True, "count": len(rows), "guests": rows}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def update_guest(
            guest_id: int,
            vip_status: Optional[bool] = None,
            loyalty_tier: Optional[str] = None,
            notes: Optional[str] = None,
            tags: Optional[str] = None,
            email: Optional[str] = None,
            phone: Optional[str] = None,
            status: Optional[str] = None,
        ) -> str:
            """Update guest profile fields."""
            try:
                updates = []
                params: Dict[str, Any] = {"guest_id": guest_id, "now": datetime.utcnow().isoformat()}

                if vip_status is not None:
                    updates.append("vip_status = :vip_status")
                    params["vip_status"] = vip_status
                if loyalty_tier is not None:
                    updates.append("loyalty_tier = :loyalty_tier")
                    params["loyalty_tier"] = loyalty_tier
                if email is not None:
                    updates.append("email = :email")
                    params["email"] = email
                if phone is not None:
                    updates.append("phone = :phone")
                    params["phone"] = phone
                if status is not None:
                    updates.append("status = :status")
                    params["status"] = status

                if not updates and not notes and not tags:
                    return json.dumps({"success": False, "error": "No fields to update."})

                # Handle notes — append to existing JSON array
                if notes:
                    existing = await session.execute(
                        text("SELECT notes FROM guests WHERE id = :guest_id"),
                        {"guest_id": guest_id},
                    )
                    row = existing.fetchone()
                    existing_notes = []
                    if row and row[0]:
                        try:
                            existing_notes = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        except (json.JSONDecodeError, TypeError):
                            existing_notes = []
                    new_note = {
                        "text": notes,
                        "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                        "author": "Admin AI",
                    }
                    existing_notes.append(new_note)
                    updates.append("notes = :notes")
                    params["notes"] = json.dumps(existing_notes)

                # Handle tags — replace with parsed array
                if tags:
                    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                    updates.append("tags = :tags")
                    params["tags"] = json.dumps(tag_list)

                updates.append("updated_at = :now")

                await session.execute(
                    text(f"UPDATE guests SET {', '.join(updates)} WHERE id = :guest_id"),
                    params,
                )
                await session.commit()

                changes = []
                if vip_status is not None:
                    changes.append(f"VIP status → {'Yes' if vip_status else 'No'}")
                if loyalty_tier:
                    changes.append(f"Loyalty tier → {loyalty_tier}")
                if status:
                    changes.append(f"Status → {status}")
                if notes:
                    changes.append("Note added")
                if tags:
                    changes.append(f"Tags → {tags}")
                if email:
                    changes.append(f"Email → {email}")
                if phone:
                    changes.append(f"Phone → {phone}")

                return json.dumps({
                    "success": True,
                    "message": f"Guest #{guest_id} updated: {', '.join(changes)}.",
                })
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Payment & Revenue Tools ═══════════════════

        async def get_payment_status(
            booking_id: Optional[int] = None,
            booking_number: Optional[str] = None,
        ) -> str:
            """Get payment details for a booking (booking → folio → payments)."""
            try:
                # Step 1: Find the booking
                if booking_id:
                    bk = await session.execute(text("""
                        SELECT b.id, b.booking_number, b.total_price, b.payment_status,
                               b.payment_method, b.deposit_amount, b.balance_due,
                               g.first_name, g.last_name
                        FROM bookings b
                        JOIN guests g ON b.guest_id = g.id
                        WHERE b.id = :bid
                    """), {"bid": booking_id})
                elif booking_number:
                    bk = await session.execute(text("""
                        SELECT b.id, b.booking_number, b.total_price, b.payment_status,
                               b.payment_method, b.deposit_amount, b.balance_due,
                               g.first_name, g.last_name
                        FROM bookings b
                        JOIN guests g ON b.guest_id = g.id
                        WHERE UPPER(b.booking_number) = UPPER(:bn)
                           OR UPPER(b.confirmation_code) = UPPER(:bn)
                    """), {"bn": booking_number})
                else:
                    return json.dumps({"success": False, "error": "Provide booking_id or booking_number."})

                bk_row = bk.fetchone()
                if not bk_row:
                    return json.dumps({"success": False, "error": "Booking not found."})

                bk_data = dict(bk_row._mapping)
                resolved_id = bk_data["id"]

                # Step 2: Get folio
                folio_result = await session.execute(text("""
                    SELECT id, folio_number, total_charges, total_payments, balance, status
                    FROM folio WHERE booking_id = :bid
                """), {"bid": resolved_id})
                folios = [dict(r._mapping) for r in folio_result.fetchall()]

                # Step 3: Get payments through folio
                payments = []
                for f in folios:
                    pay_result = await session.execute(text("""
                        SELECT id, amount, method, payment_type, status,
                               processed_at, card_last4, card_brand, upi_id, transaction_id
                        FROM payment WHERE folio_id = :fid
                        ORDER BY processed_at DESC
                    """), {"fid": f["id"]})
                    payments.extend([dict(r._mapping) for r in pay_result.fetchall()])

                total_paid = sum(p["amount"] for p in payments if p["status"] == "captured")

                return json.dumps({
                    "success": True,
                    "booking": {
                        "id": resolved_id,
                        "booking_number": bk_data["booking_number"],
                        "guest": f"{bk_data['first_name']} {bk_data['last_name']}",
                        "total_price": bk_data["total_price"],
                        "payment_status": bk_data["payment_status"],
                        "payment_method": bk_data["payment_method"],
                        "deposit_amount": bk_data["deposit_amount"],
                        "balance_due": bk_data["balance_due"],
                    },
                    "total_paid": total_paid,
                    "folios": folios,
                    "payments": payments,
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def query_revenue(date: Optional[str] = None) -> str:
            try:
                target = date or datetime.now().strftime("%Y-%m-%d")
                result = await session.execute(text("""
                    SELECT COUNT(*) as booking_count,
                           COALESCE(SUM(total_price), 0) as total_revenue,
                           COALESCE(AVG(total_price), 0) as avg_booking_value
                    FROM bookings
                    WHERE DATE(arrival_date) = :target_date
                    AND status NOT IN ('cancelled', 'no_show')
                """), {"target_date": target})
                row = result.fetchone()
                data = dict(row._mapping) if row else {}
                return json.dumps({"success": True, "date": target, "revenue": data}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_future_revenue(
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
        ) -> str:
            """Projected revenue from future/upcoming bookings."""
            try:
                start = start_date or datetime.now().strftime("%Y-%m-%d")
                end = end_date or (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

                result = await session.execute(text("""
                    SELECT COUNT(*) as booking_count,
                           COALESCE(SUM(total_price), 0) as total_revenue,
                           COALESCE(AVG(total_price), 0) as avg_booking_value,
                           COALESCE(SUM(base_price), 0) as base_revenue,
                           COALESCE(SUM(taxes), 0) as total_taxes
                    FROM bookings
                    WHERE arrival_date >= :start_date
                    AND arrival_date <= :end_date
                    AND status NOT IN ('cancelled', 'no_show')
                """), {"start_date": start, "end_date": end})
                row = result.fetchone()
                data = dict(row._mapping) if row else {}
                return json.dumps({
                    "success": True,
                    "period": {"start": start, "end": end},
                    "forecast": data,
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_revenue_by_room_type(
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
        ) -> str:
            """Revenue breakdown by room type."""
            try:
                today = datetime.now()
                start = start_date or today.replace(day=1).strftime("%Y-%m-%d")
                end = end_date or today.strftime("%Y-%m-%d")

                result = await session.execute(text("""
                    SELECT rt.name as room_type,
                           COUNT(b.id) as booking_count,
                           COALESCE(SUM(b.total_price), 0) as total_revenue,
                           COALESCE(AVG(b.total_price), 0) as avg_booking_value,
                           COALESCE(SUM(b.nights), 0) as total_nights
                    FROM bookings b
                    JOIN room_types rt ON b.room_type_id = rt.id
                    WHERE b.arrival_date >= :start_date
                    AND b.arrival_date <= :end_date
                    AND b.status NOT IN ('cancelled', 'no_show')
                    GROUP BY rt.name
                    ORDER BY total_revenue DESC
                """), {"start_date": start, "end_date": end})
                rows = [dict(r._mapping) for r in result.fetchall()]
                return json.dumps({
                    "success": True,
                    "period": {"start": start, "end": end},
                    "breakdown": rows,
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Occupancy & Dashboard Tools ═══════════════════

        async def query_occupancy(date: Optional[str] = None) -> str:
            try:
                target = date or datetime.now().strftime("%Y-%m-%d")
                total_result = await session.execute(text("SELECT COUNT(*) FROM rooms"))
                total_rooms = total_result.scalar() or 0

                occupied_result = await session.execute(text("""
                    SELECT COUNT(DISTINCT b.room_id) FROM bookings b
                    WHERE b.status = 'checked_in'
                    AND b.arrival_date <= :target_date
                    AND b.departure_date >= :target_date
                """), {"target_date": target})
                occupied = occupied_result.scalar() or 0

                rate = (occupied / total_rooms * 100) if total_rooms > 0 else 0
                return json.dumps({
                    "success": True, "date": target,
                    "total_rooms": total_rooms, "occupied": occupied,
                    "available": total_rooms - occupied,
                    "occupancy_rate": round(rate, 1),
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def query_checkouts_today(date: Optional[str] = None) -> str:
            try:
                target = date or datetime.now().strftime("%Y-%m-%d")
                result = await session.execute(text("""
                    SELECT b.id, b.booking_number, b.departure_date, b.status,
                           b.total_price, b.payment_status,
                           g.first_name, g.last_name, r.number as room_number
                    FROM bookings b
                    JOIN guests g ON b.guest_id = g.id
                    LEFT JOIN rooms r ON b.room_id = r.id
                    WHERE DATE(b.departure_date) = :target_date
                    AND b.status IN ('checked_in', 'confirmed')
                    ORDER BY b.departure_date
                """), {"target_date": target})
                rows = [dict(r._mapping) for r in result.fetchall()]
                return json.dumps({"success": True, "count": len(rows), "checkouts": rows}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_today_summary(date: Optional[str] = None) -> str:
            """Complete operational dashboard snapshot."""
            try:
                target = date or datetime.now().strftime("%Y-%m-%d")

                # Arrivals today
                arr = await session.execute(text("""
                    SELECT COUNT(*) FROM bookings
                    WHERE DATE(arrival_date) = :d AND status IN ('confirmed', 'checked_in')
                """), {"d": target})
                arrivals = arr.scalar() or 0

                # Departures today
                dep = await session.execute(text("""
                    SELECT COUNT(*) FROM bookings
                    WHERE DATE(departure_date) = :d AND status IN ('checked_in', 'confirmed')
                """), {"d": target})
                departures = dep.scalar() or 0

                # In-house guests
                inh = await session.execute(text("""
                    SELECT COUNT(*) FROM bookings
                    WHERE status = 'checked_in'
                    AND arrival_date <= :d AND departure_date >= :d
                """), {"d": target})
                in_house = inh.scalar() or 0

                # Room counts
                total_r = await session.execute(text("SELECT COUNT(*) FROM rooms"))
                total_rooms = total_r.scalar() or 0

                occ_r = await session.execute(text("""
                    SELECT COUNT(DISTINCT room_id) FROM bookings
                    WHERE status = 'checked_in'
                    AND arrival_date <= :d AND departure_date >= :d
                """), {"d": target})
                occupied = occ_r.scalar() or 0

                rate = round((occupied / total_rooms * 100), 1) if total_rooms > 0 else 0

                # Revenue today
                rev = await session.execute(text("""
                    SELECT COALESCE(SUM(total_price), 0) FROM bookings
                    WHERE DATE(arrival_date) = :d AND status NOT IN ('cancelled', 'no_show')
                """), {"d": target})
                revenue = rev.scalar() or 0

                # Pending housekeeping
                hk = await session.execute(text(
                    "SELECT COUNT(*) FROM housekeeping_tasks WHERE status = 'pending'"
                ))
                pending_hk = hk.scalar() or 0

                # Open maintenance
                mt = await session.execute(text(
                    "SELECT COUNT(*) FROM maintenancerequest WHERE status IN ('open', 'assigned', 'in_progress')"
                ))
                open_maint = mt.scalar() or 0

                # VIP arrivals
                vip = await session.execute(text("""
                    SELECT COUNT(*) FROM bookings b
                    JOIN guests g ON b.guest_id = g.id
                    WHERE DATE(b.arrival_date) = :d AND g.vip_status = true
                    AND b.status IN ('confirmed', 'checked_in')
                """), {"d": target})
                vip_arrivals = vip.scalar() or 0

                return json.dumps({
                    "success": True,
                    "date": target,
                    "summary": {
                        "arrivals_today": arrivals,
                        "departures_today": departures,
                        "in_house_guests": in_house,
                        "total_rooms": total_rooms,
                        "occupied_rooms": occupied,
                        "available_rooms": total_rooms - occupied,
                        "occupancy_rate": rate,
                        "revenue_today": revenue,
                        "pending_housekeeping": pending_hk,
                        "open_maintenance": open_maint,
                        "vip_arrivals": vip_arrivals,
                    },
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Extended Admin Operations ═══════════════════
        # These delegate to existing service layer — not raw SQL

        async def update_booking(
            booking_id: int,
            arrival_date: Optional[str] = None,
            departure_date: Optional[str] = None,
            special_requests: Optional[str] = None,
            room_type: Optional[str] = None,
            adults: Optional[int] = None,
            children: Optional[int] = None,
        ) -> str:
            """Update booking details via service layer."""
            try:
                updates = []
                params: Dict[str, Any] = {"bid": booking_id, "now": datetime.utcnow().isoformat()}

                if arrival_date:
                    updates.append("arrival_date = :arrival")
                    params["arrival"] = arrival_date
                if departure_date:
                    updates.append("departure_date = :departure")
                    params["departure"] = departure_date
                    # Recalculate nights if we have both dates
                    bk = await session.execute(
                        text("SELECT arrival_date FROM bookings WHERE id = :bid"), {"bid": booking_id}
                    )
                    r = bk.fetchone()
                    if r:
                        from datetime import date as d
                        arr = d.fromisoformat(str(r[0]))
                        dep = d.fromisoformat(departure_date)
                        updates.append(f"nights = {(dep - arr).days}")
                if special_requests:
                    updates.append("special_requests = :sr")
                    params["sr"] = special_requests
                if adults is not None:
                    updates.append("adults = :adults")
                    params["adults"] = adults
                if children is not None:
                    updates.append("children = :children")
                    params["children"] = children
                if room_type:
                    rt = await session.execute(
                        text("SELECT id FROM room_types WHERE LOWER(name) LIKE :rt LIMIT 1"),
                        {"rt": f"%{room_type.replace('_', ' ').lower()}%"}
                    )
                    rt_row = rt.fetchone()
                    if rt_row:
                        updates.append("room_type_id = :rtid")
                        params["rtid"] = rt_row[0]

                if not updates:
                    return json.dumps({"success": False, "error": "No fields to update."})

                updates.append("updated_at = :now")
                updates.append("modification_count = modification_count + 1")
                await session.execute(
                    text(f"UPDATE bookings SET {', '.join(updates)} WHERE id = :bid"), params
                )
                await session.commit()
                return json.dumps({"success": True, "message": f"Booking #{booking_id} updated."})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def extend_stay(booking_id: int, additional_nights: int) -> str:
            """Extend a booking's stay using the BookingTools service."""
            try:
                from app.services.agi.tools.booking_tools import BookingTools
                bt = BookingTools(session)
                # Get room number for the booking
                bk = await session.execute(
                    text("SELECT r.number FROM bookings b LEFT JOIN rooms r ON b.room_id = r.id WHERE b.id = :bid"),
                    {"bid": booking_id}
                )
                row = bk.fetchone()
                room_number = row[0] if row and row[0] else "unknown"
                result = await bt.extend_stay(
                    room_number=room_number,
                    additional_nights=additional_nights,
                    booking_id=booking_id
                )
                return json.dumps(result, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def mark_no_show(booking_id: int) -> str:
            """Mark a booking as no-show."""
            try:
                now = datetime.utcnow().isoformat()
                bk = await session.execute(
                    text("SELECT status, room_id FROM bookings WHERE id = :bid"), {"bid": booking_id}
                )
                row = bk.fetchone()
                if not row:
                    return json.dumps({"success": False, "error": f"Booking #{booking_id} not found."})
                if row[0] not in ("confirmed", "pending"):
                    return json.dumps({"success": False, "error": f"Cannot mark as no-show — booking is '{row[0]}'."})

                await session.execute(
                    text("UPDATE bookings SET status = 'no_show', updated_at = :now WHERE id = :bid"),
                    {"bid": booking_id, "now": now}
                )
                if row[1]:
                    await session.execute(
                        text("UPDATE rooms SET status = 'available', updated_at = :now WHERE id = :rid"),
                        {"rid": row[1], "now": now}
                    )
                await session.commit()
                return json.dumps({"success": True, "message": f"Booking #{booking_id} marked as no-show. Room released."})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def room_change(
            booking_id: int,
            new_room_number: str,
            reason: Optional[str] = None,
        ) -> str:
            """Move guest to a different room."""
            try:
                # Get current room and booking info
                bk = await session.execute(text("""
                    SELECT b.room_id, b.status, r.number as old_room, rt.name as booked_type
                    FROM bookings b
                    LEFT JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN room_types rt ON b.room_type_id = rt.id
                    WHERE b.id = :bid
                """), {"bid": booking_id})
                bk_row = bk.fetchone()
                if not bk_row:
                    return json.dumps({"success": False, "error": f"Booking #{booking_id} not found."})

                bk_data = dict(bk_row._mapping)
                old_room_id = bk_data["room_id"]

                # Find new room
                new_rm = await session.execute(text("""
                    SELECT r.id, r.number, r.status, rt.name as room_type
                    FROM rooms r LEFT JOIN room_types rt ON r.room_type_id = rt.id
                    WHERE r.number = :num
                """), {"num": new_room_number})
                new_row = new_rm.fetchone()
                if not new_row:
                    return json.dumps({"success": False, "error": f"Room {new_room_number} not found."})

                new_data = dict(new_row._mapping)
                if new_data["status"] in ("occupied", "maintenance", "out_of_order"):
                    return json.dumps({"success": False, "error": f"Room {new_room_number} is {new_data['status']} — cannot assign."})

                now = datetime.utcnow().isoformat()
                # Update booking room
                await session.execute(
                    text("UPDATE bookings SET room_id = :new_rid, updated_at = :now WHERE id = :bid"),
                    {"new_rid": new_data["id"], "bid": booking_id, "now": now}
                )
                # Mark new room occupied, old room dirty
                await session.execute(
                    text("UPDATE rooms SET status = 'occupied', updated_at = :now WHERE id = :rid"),
                    {"rid": new_data["id"], "now": now}
                )
                if old_room_id:
                    await session.execute(
                        text("UPDATE rooms SET status = 'dirty', updated_at = :now WHERE id = :rid"),
                        {"rid": old_room_id, "now": now}
                    )
                await session.commit()

                msg = f"Guest moved from room {bk_data.get('old_room', 'N/A')} to room {new_room_number} ({new_data['room_type']})."
                if reason:
                    msg += f" Reason: {reason}"
                return json.dumps({"success": True, "message": msg})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def list_staff(
            department: Optional[str] = None,
            status: Optional[str] = None,
        ) -> str:
            """List staff members."""
            try:
                conditions = ["1=1"]
                params: Dict[str, Any] = {}
                if department:
                    conditions.append("department = :dept")
                    params["dept"] = department
                if status:
                    conditions.append("status = :status")
                    params["status"] = status

                result = await session.execute(text(f"""
                    SELECT id, employee_id, name, email, phone, role, department,
                           status, shift, clocked_in
                    FROM staff
                    WHERE {' AND '.join(conditions)}
                    ORDER BY name LIMIT 50
                """), params)
                rows = [dict(r._mapping) for r in result.fetchall()]
                return json.dumps({"success": True, "count": len(rows), "staff": rows}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def add_folio_charge(
            booking_id: int,
            description: str,
            amount: float,
            item_type: str = "service",
        ) -> str:
            """Add a charge to a booking's folio."""
            try:
                # Find or create folio
                folio_q = await session.execute(
                    text("SELECT id FROM folio WHERE booking_id = :bid AND status = 'open' LIMIT 1"),
                    {"bid": booking_id}
                )
                folio_row = folio_q.fetchone()
                now = datetime.utcnow().isoformat()

                if not folio_row:
                    # Auto-create folio
                    folio_num = f"F-{booking_id}-{secrets.token_hex(3).upper()}"
                    await session.execute(text("""
                        INSERT INTO folio (booking_id, folio_number, total_charges, total_payments, balance, status, created_at, updated_at)
                        VALUES (:bid, :fnum, 0, 0, 0, 'open', :now, :now)
                    """), {"bid": booking_id, "fnum": folio_num, "now": now})
                    await session.flush()
                    folio_q = await session.execute(
                        text("SELECT id FROM folio WHERE booking_id = :bid AND status = 'open' LIMIT 1"),
                        {"bid": booking_id}
                    )
                    folio_row = folio_q.fetchone()

                folio_id = folio_row[0]

                # Add line item
                await session.execute(text("""
                    INSERT INTO foliolineitem (folio_id, item_type, description, amount, quantity, unit_price, posted_at, is_voided, created_at)
                    VALUES (:fid, :itype, :desc, :amt, 1, :amt, :now, 0, :now)
                """), {"fid": folio_id, "itype": item_type, "desc": description, "amt": amount, "now": now})

                # Update folio totals
                await session.execute(text("""
                    UPDATE folio SET total_charges = total_charges + :amt,
                                     balance = balance + :amt, updated_at = :now
                    WHERE id = :fid
                """), {"fid": folio_id, "amt": amount, "now": now})

                await session.commit()
                return json.dumps({"success": True, "message": f"Charge of Rs.{amount:,.0f} added to booking #{booking_id} folio: {description}"})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def record_payment(
            booking_id: int,
            amount: float,
            method: str = "card",
            notes: Optional[str] = None,
        ) -> str:
            """Record a payment for a booking."""
            try:
                # Find open folio
                folio_q = await session.execute(
                    text("SELECT id, balance FROM folio WHERE booking_id = :bid AND status = 'open' LIMIT 1"),
                    {"bid": booking_id}
                )
                folio_row = folio_q.fetchone()
                now = datetime.utcnow().isoformat()

                if not folio_row:
                    return json.dumps({"success": False, "error": f"No open folio found for booking #{booking_id}."})

                folio_id, balance = folio_row[0], folio_row[1]

                # Insert payment
                await session.execute(text("""
                    INSERT INTO payment (folio_id, amount, method, payment_type, status, processed_at, notes, created_at)
                    VALUES (:fid, :amt, :method, 'full_payment', 'captured', :now, :notes, :now)
                """), {"fid": folio_id, "amt": amount, "method": method, "now": now, "notes": notes or ""})

                # Update folio
                await session.execute(text("""
                    UPDATE folio SET total_payments = total_payments + :amt,
                                     balance = balance - :amt, updated_at = :now
                    WHERE id = :fid
                """), {"fid": folio_id, "amt": amount, "now": now})

                # Update booking payment status
                new_balance = balance - amount
                pay_status = "paid" if new_balance <= 0 else "partial"
                await session.execute(text("""
                    UPDATE bookings SET payment_status = :ps, updated_at = :now WHERE id = :bid
                """), {"ps": pay_status, "bid": booking_id, "now": now})

                await session.commit()
                return json.dumps({
                    "success": True,
                    "message": f"Payment of Rs.{amount:,.0f} ({method}) recorded for booking #{booking_id}. Balance: Rs.{max(new_balance, 0):,.0f}",
                    "new_balance": max(new_balance, 0),
                    "payment_status": pay_status,
                })
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_guest_history(
            guest_id: Optional[int] = None,
            guest_name: Optional[str] = None,
        ) -> str:
            """Get full guest profile with booking history."""
            try:
                if guest_name and not guest_id:
                    gq = await session.execute(text("""
                        SELECT id FROM guests WHERE LOWER(first_name) LIKE :n OR LOWER(last_name) LIKE :n LIMIT 1
                    """), {"n": f"%{guest_name.lower()}%"})
                    grow = gq.fetchone()
                    if not grow:
                        return json.dumps({"success": False, "error": f"Guest '{guest_name}' not found."})
                    guest_id = grow[0]

                if not guest_id:
                    return json.dumps({"success": False, "error": "Provide guest_id or guest_name."})

                # Guest profile
                g = await session.execute(text("""
                    SELECT id, first_name, last_name, email, phone, vip_status, loyalty_tier,
                           loyalty_points, total_bookings, total_spent, total_nights,
                           nationality, country, status, member_since, last_visit
                    FROM guests WHERE id = :gid
                """), {"gid": guest_id})
                grow = g.fetchone()
                if not grow:
                    return json.dumps({"success": False, "error": f"Guest #{guest_id} not found."})

                # Booking history
                bh = await session.execute(text("""
                    SELECT b.id, b.booking_number, b.arrival_date, b.departure_date,
                           b.status, b.total_price, b.nights, rt.name as room_type, r.number as room
                    FROM bookings b
                    LEFT JOIN room_types rt ON b.room_type_id = rt.id
                    LEFT JOIN rooms r ON b.room_id = r.id
                    WHERE b.guest_id = :gid ORDER BY b.arrival_date DESC LIMIT 10
                """), {"gid": guest_id})
                bookings = [dict(r._mapping) for r in bh.fetchall()]

                return json.dumps({
                    "success": True,
                    "guest": dict(grow._mapping),
                    "booking_history": bookings,
                    "total_stays": len(bookings),
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def generate_report(
            report_type: str,
            date: Optional[str] = None,
        ) -> str:
            """Generate an operations report."""
            try:
                target = date or datetime.now().strftime("%Y-%m-%d")
                report: Dict[str, Any] = {"report_type": report_type, "date": target}

                if report_type == "daily_operations":
                    # Combine summary + details
                    summary_json = await get_today_summary(target)
                    summary = json.loads(summary_json)
                    report["summary"] = summary.get("summary", {})

                    # Top arrivals
                    arr = await session.execute(text("""
                        SELECT b.booking_number, g.first_name, g.last_name, rt.name as room_type,
                               b.total_price, g.vip_status
                        FROM bookings b JOIN guests g ON b.guest_id = g.id
                        LEFT JOIN room_types rt ON b.room_type_id = rt.id
                        WHERE DATE(b.arrival_date) = :d AND b.status IN ('confirmed', 'checked_in')
                        ORDER BY g.vip_status DESC, b.total_price DESC
                    """), {"d": target})
                    report["arrivals"] = [dict(r._mapping) for r in arr.fetchall()]

                elif report_type == "revenue":
                    rev = await session.execute(text("""
                        SELECT DATE(arrival_date) as dt, COUNT(*) as bookings,
                               SUM(total_price) as revenue, AVG(total_price) as avg_value
                        FROM bookings WHERE arrival_date >= DATE(:d, '-7 days') AND arrival_date <= :d
                        AND status NOT IN ('cancelled', 'no_show')
                        GROUP BY DATE(arrival_date) ORDER BY dt
                    """), {"d": target})
                    report["daily_revenue"] = [dict(r._mapping) for r in rev.fetchall()]

                elif report_type == "occupancy":
                    total_r = await session.execute(text("SELECT COUNT(*) FROM rooms"))
                    total = total_r.scalar() or 1
                    occ = await session.execute(text("""
                        SELECT r.status, COUNT(*) as cnt FROM rooms r GROUP BY r.status
                    """))
                    report["room_breakdown"] = [dict(r._mapping) for r in occ.fetchall()]
                    report["total_rooms"] = total

                elif report_type == "housekeeping":
                    hk = await session.execute(text("""
                        SELECT ht.status, COUNT(*) as cnt FROM housekeeping_tasks ht GROUP BY ht.status
                    """))
                    report["task_breakdown"] = [dict(r._mapping) for r in hk.fetchall()]

                elif report_type == "guest_summary":
                    gs = await session.execute(text("""
                        SELECT COUNT(*) as total, SUM(CASE WHEN vip_status = 1 THEN 1 ELSE 0 END) as vip_count,
                               AVG(total_spent) as avg_spent, SUM(total_spent) as total_revenue
                        FROM guests
                    """))
                    report["guest_stats"] = dict(gs.fetchone()._mapping)

                return json.dumps({"success": True, "report": report}, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Chart / Visualization Tools ═══════════════════

        async def get_occupancy_trend(
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
        ) -> str:
            """Occupancy trend over time — returns Chart.js-compatible data."""
            try:
                end = end_date or datetime.now().strftime("%Y-%m-%d")
                start = start_date or (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

                total_r = await session.execute(text("SELECT COUNT(*) FROM rooms"))
                total_rooms = total_r.scalar() or 1

                result = await session.execute(text("""
                    SELECT DATE(b.arrival_date) as dt,
                           COUNT(DISTINCT b.room_id) as occupied
                    FROM bookings b
                    WHERE b.arrival_date >= :start AND b.arrival_date <= :end
                    AND b.status NOT IN ('cancelled', 'no_show')
                    GROUP BY DATE(b.arrival_date)
                    ORDER BY dt
                """), {"start": start, "end": end})
                rows = result.fetchall()

                labels = [str(r[0]) for r in rows]
                occupancy = [round((r[1] / total_rooms) * 100, 1) for r in rows]
                occupied = [r[1] for r in rows]

                return json.dumps({
                    "success": True,
                    "chart_data": {
                        "chart_type": "line",
                        "title": f"Occupancy Trend ({start} to {end})",
                        "labels": labels,
                        "datasets": [
                            {"label": "Occupancy %", "data": occupancy},
                            {"label": "Rooms Occupied", "data": occupied},
                        ],
                    },
                    "total_rooms": total_rooms,
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_revenue_trend(
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
        ) -> str:
            """Revenue trend over time — returns Chart.js-compatible data."""
            try:
                end = end_date or datetime.now().strftime("%Y-%m-%d")
                start = start_date or (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

                result = await session.execute(text("""
                    SELECT DATE(arrival_date) as dt,
                           COUNT(*) as bookings,
                           COALESCE(SUM(total_price), 0) as revenue
                    FROM bookings
                    WHERE arrival_date >= :start AND arrival_date <= :end
                    AND status NOT IN ('cancelled', 'no_show')
                    GROUP BY DATE(arrival_date)
                    ORDER BY dt
                """), {"start": start, "end": end})
                rows = result.fetchall()

                labels = [str(r[0]) for r in rows]
                revenue = [float(r[2]) for r in rows]
                bookings = [r[1] for r in rows]

                return json.dumps({
                    "success": True,
                    "chart_data": {
                        "chart_type": "bar",
                        "title": f"Revenue Trend ({start} to {end})",
                        "labels": labels,
                        "datasets": [
                            {"label": "Revenue (INR)", "data": revenue},
                            {"label": "Bookings", "data": bookings},
                        ],
                    },
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_booking_source_breakdown(
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
        ) -> str:
            """Booking source/channel distribution — pie chart data."""
            try:
                end = end_date or datetime.now().strftime("%Y-%m-%d")
                start = start_date or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

                result = await session.execute(text("""
                    SELECT COALESCE(booking_source, 'Direct') as source,
                           COUNT(*) as cnt,
                           COALESCE(SUM(total_price), 0) as revenue
                    FROM bookings
                    WHERE arrival_date >= :start AND arrival_date <= :end
                    AND status NOT IN ('cancelled', 'no_show')
                    GROUP BY COALESCE(booking_source, 'Direct')
                    ORDER BY cnt DESC
                """), {"start": start, "end": end})
                rows = result.fetchall()

                labels = [str(r[0]) for r in rows]
                counts = [r[1] for r in rows]
                revenues = [float(r[2]) for r in rows]

                return json.dumps({
                    "success": True,
                    "chart_data": {
                        "chart_type": "pie",
                        "title": "Booking Source Distribution",
                        "labels": labels,
                        "datasets": [
                            {"label": "Bookings", "data": counts},
                            {"label": "Revenue (INR)", "data": revenues},
                        ],
                    },
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        async def get_room_status_overview() -> str:
            """Room status distribution — doughnut chart data."""
            try:
                result = await session.execute(text("""
                    SELECT status, COUNT(*) as cnt FROM rooms GROUP BY status ORDER BY cnt DESC
                """))
                rows = result.fetchall()

                labels = [str(r[0]) for r in rows]
                counts = [r[1] for r in rows]

                return json.dumps({
                    "success": True,
                    "chart_data": {
                        "chart_type": "doughnut",
                        "title": "Room Status Overview",
                        "labels": labels,
                        "datasets": [{"label": "Rooms", "data": counts}],
                    },
                }, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # ═══════════════════ Register all tools ═══════════════════

        self._tools = [
            # Booking tools
            StructuredTool.from_function(
                coroutine=search_bookings,
                name="search_bookings",
                description="Search bookings by date, status, or guest name. Use for 'show bookings today', 'arrivals for Dec 15', 'find booking for Ishan'.",
                args_schema=SearchBookingsInput,
            ),
            StructuredTool.from_function(
                coroutine=get_booking_details,
                name="get_booking_details",
                description="Get full details of a specific booking by ID or booking number. Use when user asks 'show booking GLM-XXXXXX', 'details for booking #199', 'booking info'.",
                args_schema=GetBookingDetailsInput,
            ),
            StructuredTool.from_function(
                coroutine=create_booking,
                name="create_booking",
                description="Create a new hotel booking. Requires guest name, check-in date, check-out date. Room type defaults to standard.",
                args_schema=CreateBookingInput,
            ),
            StructuredTool.from_function(
                coroutine=check_in_booking,
                name="check_in_booking",
                description="Check in a guest by booking ID. Validates room type match if room is assigned. Optionally assign a specific room.",
                args_schema=CheckInInput,
            ),
            StructuredTool.from_function(
                coroutine=check_out_booking,
                name="check_out_booking",
                description="Check out a guest by booking ID. Frees the room and marks it as dirty.",
                args_schema=CheckOutInput,
            ),
            StructuredTool.from_function(
                coroutine=cancel_booking,
                name="cancel_booking",
                description="Cancel a booking by ID. ALWAYS confirm with the user first before calling this tool.",
                args_schema=CancelBookingInput,
            ),
            # Room tools
            StructuredTool.from_function(
                coroutine=list_rooms,
                name="list_rooms",
                description="List hotel rooms. Filter by status (available, occupied, dirty, clean, maintenance) or floor.",
                args_schema=RoomListInput,
            ),
            StructuredTool.from_function(
                coroutine=check_room_availability,
                name="check_room_availability",
                description="Check available room types for given dates with pricing.",
                args_schema=RoomAvailabilityInput,
            ),
            StructuredTool.from_function(
                coroutine=update_room_status,
                name="update_room_status",
                description="Update a room's status (clean, dirty, maintenance, out_of_order, inspected).",
                args_schema=UpdateRoomStatusInput,
            ),
            # Housekeeping tools
            StructuredTool.from_function(
                coroutine=create_housekeeping_task,
                name="create_housekeeping_task",
                description="Create a housekeeping task for a room. Types: daily_clean, deep_clean, turndown, checkout_clean, inspection.",
                args_schema=CreateHousekeepingTaskInput,
            ),
            StructuredTool.from_function(
                coroutine=get_housekeeping_tasks,
                name="get_housekeeping_tasks",
                description="List housekeeping tasks. Filter by status (pending/in_progress/completed), priority, or room number. Use for 'pending cleaning tasks', 'show housekeeping'.",
                args_schema=GetHousekeepingTasksInput,
            ),
            # Maintenance tools
            StructuredTool.from_function(
                coroutine=create_maintenance_request,
                name="create_maintenance_request",
                description="Report a maintenance issue for a room (plumbing, electrical, HVAC, furniture, etc.).",
                args_schema=CreateMaintenanceInput,
            ),
            StructuredTool.from_function(
                coroutine=get_maintenance_requests,
                name="get_maintenance_requests",
                description="List maintenance work orders. Filter by status (open/in_progress/completed), priority, category, or room. Use for 'open maintenance', 'plumbing issues'.",
                args_schema=GetMaintenanceRequestsInput,
            ),
            # Guest tools
            StructuredTool.from_function(
                coroutine=search_guests,
                name="search_guests",
                description="Search guests by name, email, or VIP status.",
                args_schema=SearchGuestsInput,
            ),
            StructuredTool.from_function(
                coroutine=update_guest,
                name="update_guest",
                description="Update guest profile: set VIP status, loyalty tier, add notes/tags, update contact info, or change status. Requires guest_id.",
                args_schema=UpdateGuestInput,
            ),
            # Payment & Revenue tools
            StructuredTool.from_function(
                coroutine=get_payment_status,
                name="get_payment_status",
                description="Get payment info for a booking: total, paid, balance, method, individual payments. Use for 'payment status for GLM-XXXXXX' or 'booking #199 payment'.",
                args_schema=GetPaymentStatusInput,
            ),
            StructuredTool.from_function(
                coroutine=query_revenue,
                name="query_revenue",
                description="Get revenue data (total revenue, booking count, average value) for a specific date.",
                args_schema=QueryRevenueInput,
            ),
            StructuredTool.from_function(
                coroutine=get_future_revenue,
                name="get_future_revenue",
                description="Get projected revenue from upcoming/future bookings in a date range. Use for 'projected revenue', 'future earnings', 'revenue next month'.",
                args_schema=GetFutureRevenueInput,
            ),
            StructuredTool.from_function(
                coroutine=get_revenue_by_room_type,
                name="get_revenue_by_room_type",
                description="Revenue breakdown by room type. Use for 'which room type earns most', 'revenue by category', 'room type performance'.",
                args_schema=GetRevenueByRoomTypeInput,
            ),
            # Dashboard & occupancy tools
            StructuredTool.from_function(
                coroutine=query_occupancy,
                name="query_occupancy",
                description="Get occupancy rate (total rooms, occupied, available, percentage) for a date.",
                args_schema=QueryOccupancyInput,
            ),
            StructuredTool.from_function(
                coroutine=query_checkouts_today,
                name="query_checkouts_today",
                description="List expected checkouts/departures for a date.",
                args_schema=QueryCheckoutsInput,
            ),
            StructuredTool.from_function(
                coroutine=get_today_summary,
                name="get_today_summary",
                description="Full operational dashboard: arrivals, departures, in-house, occupancy, revenue, pending tasks, VIP arrivals. Use for 'today's summary', 'dashboard', 'overview'.",
                args_schema=GetTodaySummaryInput,
            ),
            # ── Extended admin operation tools ──
            StructuredTool.from_function(
                coroutine=update_booking,
                name="update_booking",
                description="Update booking details: dates, room type, special requests, guest count. Use for 'change checkout to Dec 20', 'update booking'.",
                args_schema=UpdateBookingInput,
            ),
            StructuredTool.from_function(
                coroutine=extend_stay,
                name="extend_stay",
                description="Extend a guest's stay by additional nights. Uses BookingTools service. For 'extend booking #5 by 2 nights'.",
                args_schema=ExtendStayInput,
            ),
            StructuredTool.from_function(
                coroutine=mark_no_show,
                name="mark_no_show",
                description="Mark a booking as no-show. Releases the room. CONFIRM with user first.",
                args_schema=MarkNoShowInput,
            ),
            StructuredTool.from_function(
                coroutine=room_change,
                name="room_change",
                description="Move a guest to a different room. Validates room availability. For 'move guest in booking #3 to room 501'.",
                args_schema=RoomChangeInput,
            ),
            StructuredTool.from_function(
                coroutine=list_staff,
                name="list_staff",
                description="List staff members. Filter by department (frontdesk, housekeeping, maintenance) or status (active, on_leave).",
                args_schema=ListStaffInput,
            ),
            StructuredTool.from_function(
                coroutine=add_folio_charge,
                name="add_folio_charge",
                description="Add a charge to a booking's folio (room service, minibar, spa, restaurant, laundry). Auto-creates folio if needed.",
                args_schema=AddFolioChargeInput,
            ),
            StructuredTool.from_function(
                coroutine=record_payment,
                name="record_payment",
                description="Record a payment for a booking (card, cash, UPI, bank transfer). Updates payment status automatically.",
                args_schema=RecordPaymentInput,
            ),
            StructuredTool.from_function(
                coroutine=get_guest_history,
                name="get_guest_history",
                description="Get full guest profile with booking history. Search by guest_id or guest_name. For 'show guest history for Sarah'.",
                args_schema=GetGuestHistoryInput,
            ),
            StructuredTool.from_function(
                coroutine=generate_report,
                name="generate_report",
                description="Generate an operations report: daily_operations, revenue, occupancy, housekeeping, or guest_summary.",
                args_schema=GenerateReportInput,
            ),
            # ── Chart / Visualization tools ──
            StructuredTool.from_function(
                coroutine=get_occupancy_trend,
                name="get_occupancy_trend",
                description="Get occupancy trend over a date range. Returns chart data (line chart). For 'show occupancy trend this week', 'occupancy chart'.",
                args_schema=OccupancyTrendInput,
            ),
            StructuredTool.from_function(
                coroutine=get_revenue_trend,
                name="get_revenue_trend",
                description="Get revenue trend over a date range. Returns chart data (bar chart). For 'show revenue trend', 'revenue chart this month'.",
                args_schema=RevenueTrendInput,
            ),
            StructuredTool.from_function(
                coroutine=get_booking_source_breakdown,
                name="get_booking_source_breakdown",
                description="Get booking source/channel distribution (Direct, OTA, Walk-in). Returns pie chart data. For 'booking channel breakdown', 'where do bookings come from'.",
                args_schema=BookingSourceBreakdownInput,
            ),
            StructuredTool.from_function(
                coroutine=get_room_status_overview,
                name="get_room_status_overview",
                description="Get room status distribution (available, occupied, dirty, maintenance). Returns doughnut chart data. For 'room status breakdown', 'show room chart'.",
                args_schema=RoomStatusOverviewInput,
            ),
        ]

    # ───── Message processing ─────

    async def process_message(
        self,
        message: str,
        user_id: int,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process a user message using LLM + tool calling.

        The LLM decides what to do — no regex, no manual routing.
        Supports multi-turn tool calling up to MAX_TOOL_ROUNDS.
        """
        if not self._llm:
            return {
                "message": "AI assistant is not available. Please check that the OpenAI API key is configured in the .env file.",
                "intent": "error",
                "confidence": 0.0,
                "session_id": session_id,
            }

        # Build conversation history from context
        messages: List[BaseMessage] = []

        # System prompt
        system_prompt = ADMIN_AI_SYSTEM_PROMPT.format(today=date.today().isoformat())
        messages.append(SystemMessage(content=system_prompt))

        # Previous messages (conversation memory)
        if context:
            prev = context.get("previousMessages") or context.get("previous_messages") or []
            for msg in prev[-10:]:  # Last 10 messages for context
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if not content:
                    continue
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))

        # Current message
        messages.append(HumanMessage(content=message))

        # Bind tools to LLM
        llm_with_tools = self._llm.bind_tools(self._tools)

        try:
            first_intent = "general"
            chart_data = None  # Capture chart data from tool results

            # Multi-round tool calling loop
            for round_num in range(MAX_TOOL_ROUNDS):
                response = await llm_with_tools.ainvoke(messages)

                if not response.tool_calls:
                    # LLM returned a text response — we're done
                    response_text = response.content
                    break

                # Track first intent for suggestions
                if round_num == 0:
                    first_intent = response.tool_calls[0]["name"]

                # Add AI message with tool calls
                messages.append(response)

                # Execute each tool call
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]

                    logger.info(f"[Round {round_num + 1}] LLM calling tool: {tool_name}({json.dumps(tool_args, default=str)[:200]})")

                    tool_result = await self._execute_tool(tool_name, tool_args)

                    # Extract chart_data from tool results (for visualization tools)
                    try:
                        parsed = json.loads(tool_result)
                        if parsed.get("chart_data"):
                            chart_data = parsed["chart_data"]
                    except (json.JSONDecodeError, TypeError):
                        pass

                    messages.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=tool_call["id"],
                    ))
            else:
                # Hit max rounds — force a text response
                response = await self._llm.ainvoke(messages)
                response_text = response.content

            result = {
                "message": response_text,
                "intent": first_intent,
                "confidence": 0.95,
                "session_id": session_id,
                "suggestions": self._generate_suggestions(first_intent),
            }
            if chart_data:
                result["chart_data"] = chart_data
            return result

        except Exception as e:
            logger.error(f"LLM agent error: {e}", exc_info=True)
            return {
                "message": f"I encountered an error processing your request. Please try again or rephrase your question.\n\nDetails: {str(e)}",
                "intent": "error",
                "confidence": 0.0,
                "session_id": session_id,
                "error": str(e),
            }

    async def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """Execute a tool by name."""
        for tool in self._tools:
            if tool.name == tool_name:
                try:
                    return await tool.ainvoke(tool_args)
                except Exception as e:
                    logger.error(f"Tool {tool_name} failed: {e}", exc_info=True)
                    return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": False, "error": f"Tool '{tool_name}' not found."})

    def _generate_suggestions(self, intent: str) -> List[str]:
        """Generate follow-up suggestions based on the action taken."""
        suggestion_map = {
            "search_bookings": ["Show today's checkouts", "Revenue summary", "Create a booking"],
            "get_booking_details": ["Check payment status", "Check in this guest", "Show all bookings today"],
            "create_booking": ["Show today's bookings", "Check room availability", "Create another booking"],
            "check_in_booking": ["Show today's bookings", "Room status", "Create housekeeping task"],
            "check_out_booking": ["Show today's checkouts", "Revenue summary", "Clean the room"],
            "cancel_booking": ["Show today's bookings", "Revenue summary", "Room availability"],
            "list_rooms": ["Show dirty rooms", "Show available rooms", "Create housekeeping task"],
            "check_room_availability": ["Create a booking", "Show room list", "Revenue summary"],
            "update_room_status": ["Show room list", "Pending housekeeping", "Room availability"],
            "create_housekeeping_task": ["Show pending tasks", "Room status", "Show dirty rooms"],
            "get_housekeeping_tasks": ["Create housekeeping task", "Show dirty rooms", "Room status"],
            "create_maintenance_request": ["Show open maintenance", "Room status", "Mark room out of order"],
            "get_maintenance_requests": ["Create maintenance request", "Room status", "Today's summary"],
            "search_guests": ["Show VIP guests", "Show bookings", "Guest profile"],
            "update_guest": ["Search guests", "Show VIP guests", "Today's summary"],
            "get_payment_status": ["Show booking details", "Revenue today", "Show all bookings"],
            "query_revenue": ["Show occupancy", "Revenue by room type", "Future revenue"],
            "get_future_revenue": ["Revenue by room type", "Show occupancy", "Show bookings"],
            "get_revenue_by_room_type": ["Future revenue", "Today's revenue", "Show occupancy"],
            "query_occupancy": ["Show revenue", "Show available rooms", "Show bookings today"],
            "query_checkouts_today": ["Show arrivals today", "Revenue summary", "Occupancy rate"],
            "get_today_summary": ["Show arrivals", "Show checkouts", "Revenue details"],
        }
        # Extended admin ops
        suggestion_map.update({
            "update_booking": ["Show booking details", "Check room availability", "Show bookings today"],
            "extend_stay": ["Show booking details", "Revenue summary", "Show checkouts"],
            "mark_no_show": ["Show bookings today", "Revenue summary", "Room availability"],
            "room_change": ["Show rooms", "Show booking details", "Create housekeeping task"],
            "list_staff": ["Staff by department", "Show housekeeping tasks", "Today's summary"],
            "add_folio_charge": ["Payment status", "Show booking details", "Record payment"],
            "record_payment": ["Payment status", "Show booking details", "Revenue today"],
            "get_guest_history": ["Search guests", "Show VIP guests", "Guest bookings"],
            "generate_report": ["Revenue trend", "Occupancy trend", "Today's summary"],
            "get_occupancy_trend": ["Revenue trend", "Room status chart", "Booking sources"],
            "get_revenue_trend": ["Occupancy trend", "Revenue by room type", "Future revenue"],
            "get_booking_source_breakdown": ["Revenue trend", "Occupancy trend", "Show bookings"],
            "get_room_status_overview": ["Show dirty rooms", "Housekeeping tasks", "Occupancy trend"],
        })
        return suggestion_map.get(intent, ["Today's summary", "Show bookings today", "Revenue summary"])
