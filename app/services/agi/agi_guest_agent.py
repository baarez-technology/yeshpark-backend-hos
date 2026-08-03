"""
AGI Guest Agent - Advanced LangGraph-based Guest Assistant
Completely redesigned with proper state management and conversation tracking
"""

import logging
import json
import re
from typing import Any, Dict, List, Optional, TypedDict, Literal, Sequence, Tuple
try:
    from typing import Annotated
except ImportError:
    from typing_extensions import Annotated
from datetime import datetime, timedelta
from dataclasses import dataclass, field

try:
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    from langgraph.checkpoint.memory import MemorySaver
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    # Fallback classes
    class BaseMessage:
        def __init__(self, content=""):
            self.content = content
    class HumanMessage(BaseMessage):
        pass
    class AIMessage(BaseMessage):
        pass
    class SystemMessage(BaseMessage):
        pass
    class ToolMessage(BaseMessage):
        pass
    class ChatOpenAI:
        def __init__(self, *args, **kwargs):
            pass
    class StateGraph:
        pass
    class MemorySaver:
        pass
    END = "end"
    def add_messages(left, right):
        return (left or []) + (right or [])

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from .memory import GuestMemoryManager, get_memory_manager, GuestContext
from .tools.housekeeping_tools import get_housekeeping_tools
from .tools.maintenance_tools import get_maintenance_tools
from .tools.room_service_tools import get_room_service_tools
from .tools.concierge_tools import get_concierge_tools
from .tools.billing_tools import get_billing_tools
from .tools.booking_tools import get_booking_tools
from .tools.hotel_info_tools import get_hotel_info_tools
from .tools.precheckin_tools import get_precheckin_tools
from .tools.chatbot_routing_tools import get_chatbot_routing_tools
from .voice_processor import get_voice_processor

logger = logging.getLogger("agi.guest_agent")


# ===================== STATE DEFINITION =====================

class BookingState(TypedDict, total=False):
    """Booking-specific state tracked throughout conversation"""
    room_type_id: Optional[int]
    room_type_name: Optional[str]
    check_in_date: Optional[str]
    check_out_date: Optional[str]
    adults: int
    children: int
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    country: Optional[str]
    special_requests: Optional[str]
    rooms_shown: bool  # Track if we've shown room list


class AgentState(TypedDict):
    """Complete state for the AGI agent graph"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    booking_state: BookingState
    guest_context: Dict[str, Any]
    current_intent: str
    session_id: str
    last_assistant_action: Optional[str]  # Track what we last did


# ===================== RESPONSE DATACLASS =====================

@dataclass
class AGIResponse:
    """Response from AGI agent"""
    message: str
    intent: str
    confidence: float
    action_taken: bool = False
    action_result: Optional[Dict[str, Any]] = None
    task_id: Optional[int] = None
    task_type: Optional[str] = None
    quick_actions: Optional[List[Dict[str, str]]] = None
    voice_response: Optional[str] = None
    guest_context: Optional[Dict[str, Any]] = None
    follow_up_needed: bool = False
    guest_emotion: Optional[str] = None  # happy, neutral, frustrated, upset
    wake_word_detected: bool = False  # For voice interactions
    requires_confirmation: bool = False  # For critical actions


# ===================== ROOM TYPE MAPPING =====================

ROOM_TYPES = {
    1: {"name": "Minimalist Studio", "keywords": ["minimalist", "studio"]},
    2: {"name": "Coastal Retreat", "keywords": ["coastal", "retreat"]},
    3: {"name": "Urban Oasis", "keywords": ["urban", "oasis"]},
    4: {"name": "Sunset Vista", "keywords": ["sunset", "vista"]},
    5: {"name": "Pacific Suite", "keywords": ["pacific"]},
    6: {"name": "Wellness Suite", "keywords": ["wellness"]},
    7: {"name": "Family Sanctuary", "keywords": ["family", "sanctuary"]},
    8: {"name": "Oceanfront Penthouse", "keywords": ["oceanfront", "penthouse"]},
}


# ===================== HELPER FUNCTIONS =====================

def parse_date(date_str: str) -> Optional[str]:
    """Parse various date formats to YYYY-MM-DD"""
    if not date_str:
        return None

    date_str = date_str.lower().strip()
    now = datetime.now()
    current_year = now.year

    # Handle relative dates
    if date_str == "today":
        return now.strftime("%Y-%m-%d")
    if date_str == "tomorrow":
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # Already ISO format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    month_map = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
        "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12
    }

    try:
        # Pattern: "8 dec", "8th december", "december 8"
        patterns = [
            r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w+)(?:\s+(\d{4}))?",
            r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?",
        ]

        for pattern in patterns:
            match = re.search(pattern, date_str)
            if match:
                groups = match.groups()
                if groups[0].isdigit():
                    day = int(groups[0])
                    month_str = groups[1]
                    year = int(groups[2]) if groups[2] else current_year
                else:
                    month_str = groups[0]
                    day = int(groups[1])
                    year = int(groups[2]) if groups[2] else current_year

                month = month_map.get(month_str.lower())
                if month:
                    if year < 100:
                        year = 2000 + year
                    return f"{year}-{month:02d}-{day:02d}"
    except:
        pass

    return None


def extract_dates_from_message(message: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract check-in and check-out dates from a message"""
    message_lower = message.lower()

    # Remove common prefixes that interfere with parsing
    message_lower = re.sub(r'^(from\s+|for\s+|between\s+)', '', message_lower.strip())

    # Pattern: "from X to Y", "X to Y", "X - Y"
    range_patterns = [
        # "dec 8 to dec 10", "dec 8 to dec 10 2025"
        r"(\w{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|-|till|until)\s*(\w{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?",
        # "8 december to 10 december", "dec 8 to dec 10"
        r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*(\w{3,9})\s*(?:to|-|till|until)\s*(\d{1,2})\s*(?:st|nd|rd|th)?\s*(\w{3,9})(?:\s+(\d{4}))?",
        # "december 8 to 10", "dec 8-10"
        r"(\w{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|-|till|until)\s*(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?",
        # "8 to 10 december"
        r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|-|till|until)\s*(\d{1,2})(?:st|nd|rd|th)?\s*(\w{3,9})(?:\s+(\d{4}))?",
    ]

    for pattern in range_patterns:
        match = re.search(pattern, message_lower)
        if match:
            groups = match.groups()

            # "dec 8 to dec 10" pattern - month day to month day
            if len(groups) >= 4 and groups[0].isalpha() and groups[2].isalpha():
                month1, day1, month2, day2 = groups[0], groups[1], groups[2], groups[3]
                year = groups[4] if len(groups) > 4 and groups[4] else None
                check_in = parse_date(f"{month1} {day1}" + (f" {year}" if year else ""))
                check_out = parse_date(f"{month2} {day2}" + (f" {year}" if year else ""))
                if check_in and check_out:
                    return check_in, check_out

            # "8 december to 10 december"
            elif len(groups) >= 4 and groups[0].isdigit() and not groups[2].isdigit():
                day1, month1, day2, month2 = groups[0], groups[1], groups[2], groups[3]
                year = groups[4] if len(groups) > 4 else None
                check_in = parse_date(f"{day1} {month1}" + (f" {year}" if year else ""))
                check_out = parse_date(f"{day2} {month2}" + (f" {year}" if year else ""))
                if check_in and check_out:
                    return check_in, check_out

            # "december 8 to 10" or "dec 8-10"
            elif len(groups) >= 3 and groups[0].isalpha():
                month = groups[0]
                day1 = groups[1]
                day2 = groups[2]
                year = groups[3] if len(groups) > 3 and groups[3] else None
                check_in = parse_date(f"{month} {day1}" + (f" {year}" if year else ""))
                check_out = parse_date(f"{month} {day2}" + (f" {year}" if year else ""))
                if check_in and check_out:
                    return check_in, check_out

            # "8 to 10 december"
            elif len(groups) >= 3 and groups[0].isdigit() and groups[1].isdigit():
                day1, day2, month = groups[0], groups[1], groups[2]
                year = groups[3] if len(groups) > 3 and groups[3] else None
                check_in = parse_date(f"{day1} {month}" + (f" {year}" if year else ""))
                check_out = parse_date(f"{day2} {month}" + (f" {year}" if year else ""))
                if check_in and check_out:
                    return check_in, check_out

    # Try to find two separate dates
    date_pattern = r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w{3,9})(?:\s+(\d{4}))?|(\w{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?"
    matches = list(re.finditer(date_pattern, message_lower))

    dates = []
    for match in matches:
        date = parse_date(match.group(0))
        if date and date not in dates:
            dates.append(date)

    if len(dates) >= 2:
        return dates[0], dates[1]
    elif len(dates) == 1:
        return dates[0], None

    return None, None


def extract_room_selection(message: str, rooms_shown: bool) -> Optional[int]:
    """Extract room selection from message"""
    message_lower = message.lower().strip()

    # Check for number selection (1-8)
    number_match = re.match(r"^(\d)$", message_lower)
    if number_match and rooms_shown:
        num = int(number_match.group(1))
        if 1 <= num <= 8:
            return num

    # Check for "option X" or "number X"
    option_match = re.search(r"(?:option|number|#)\s*(\d)", message_lower)
    if option_match and rooms_shown:
        num = int(option_match.group(1))
        if 1 <= num <= 8:
            return num

    # Check for room name keywords
    for room_id, room_info in ROOM_TYPES.items():
        for keyword in room_info["keywords"]:
            if keyword in message_lower:
                return room_id

    return None


def extract_guest_count(message: str) -> Tuple[int, int]:
    """Extract adults and children count from message"""
    message_lower = message.lower()
    adults = 1
    children = 0

    # Pattern: "2 adults", "for 2", "2 guests"
    adult_patterns = [
        r"(\d+)\s*(?:adult|guest|person|people)",
        r"(?:for|with)\s*(\d+)",
    ]

    for pattern in adult_patterns:
        match = re.search(pattern, message_lower)
        if match:
            adults = int(match.group(1))
            break

    # Pattern: "1 child", "2 children", "2 kids"
    child_patterns = [
        r"(\d+)\s*(?:child|children|kid|kids)",
    ]

    for pattern in child_patterns:
        match = re.search(pattern, message_lower)
        if match:
            children = int(match.group(1))
            break

    return min(adults, 10), min(children, 10)


def extract_guest_info(message: str) -> Dict[str, Optional[str]]:
    """Extract guest personal information from message"""
    info = {}

    # Email
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", message, re.IGNORECASE)
    if email_match:
        info["email"] = email_match.group().lower()

    # Phone
    phone_match = re.search(r"[\+]?[(]?[0-9]{1,3}[)]?[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,9}", message)
    if phone_match and len(phone_match.group().replace(" ", "").replace("-", "")) >= 7:
        info["phone"] = phone_match.group()

    # Name patterns
    name_patterns = [
        r"(?:my name is|i'm|i am|name[:\s]+)\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)",
        r"^([A-Za-z]+\s+[A-Za-z]+)$",  # Just a name
    ]

    for pattern in name_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            parts = name.split()
            if len(parts) >= 1:
                info["first_name"] = parts[0].title()
            if len(parts) >= 2:
                info["last_name"] = parts[1].title()
            break

    # Country
    countries = ["usa", "us", "uk", "united states", "united kingdom", "india", "canada",
                 "australia", "germany", "france", "spain", "italy", "japan", "china"]
    message_lower = message.lower()
    for country in countries:
        if country in message_lower:
            info["country"] = country.title()
            break

    return info


# ===================== AGI GUEST AGENT CLASS =====================

class AGIGuestAgent:
    """
    Advanced AGI Guest Agent using LangGraph with proper state management.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.memory_manager = get_memory_manager(db)
        self.voice_processor = get_voice_processor()

        # Initialize tools
        self._init_tools()

        # Initialize LLM - use GPT-4 for better reasoning
        self.llm = ChatOpenAI(
            model=settings.openai_model or "gpt-4o",
            api_key=settings.openai_api_key,
            temperature=0.3,  # Lower for more consistent responses
            max_tokens=1500
        )

        # Build the graph
        self._build_graph()

        # Memory saver for conversation persistence
        self.checkpointer = MemorySaver()

    def _init_tools(self):
        """Initialize all specialized tools"""
        self.housekeeping_tools = get_housekeeping_tools(self.db)
        self.maintenance_tools = get_maintenance_tools(self.db)
        self.room_service_tools = get_room_service_tools(self.db)
        self.concierge_tools = get_concierge_tools(self.db)
        self.billing_tools = get_billing_tools(self.db)
        self.booking_tools = get_booking_tools(self.db)
        self.hotel_info_tools = get_hotel_info_tools(self.db)
        self.precheckin_tools = get_precheckin_tools(self.db)
        self.chatbot_routing_tools = get_chatbot_routing_tools(self.db)

    def _build_system_prompt(self, state: AgentState) -> str:
        """Build dynamic system prompt with current state"""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        booking = state.get("booking_state", {})
        current_intent = state.get("current_intent", "general")

        # Build booking state summary only if relevant
        booking_summary = self._format_booking_state(booking) if current_intent == "new_booking" else "Not in booking flow"

        prompt = f"""You are Aria, the AI concierge for Glimmora Hotel & Suites.

TODAY: {today}
DETECTED INTENT: {current_intent}

=== YOUR CAPABILITIES ===
You can help guests with:
1. **Booking Lookup** - Look up existing bookings by confirmation code (e.g., GLM-ABC123) or guest info
2. **New Bookings** - Make new reservations with room selection and guest details
3. **Maintenance** - Report issues (broken shower, AC, WiFi problems, etc.) - requires room number
4. **Housekeeping** - Request cleaning, towels, amenities - requires room number
5. **Room Service** - Order food, view menu - requires room number
6. **Hotel Info** - Answer questions about amenities, policies, hours

=== INTENT-BASED RESPONSE ===

**IF USER PROVIDES A CONFIRMATION CODE** (like GLM-TRB0JZ):
→ Use the lookup_booking tool immediately with that code
→ Show them their booking details

**IF USER ASKS "my bookings" or "how many bookings"**:
→ If logged in, lookup their bookings
→ If not logged in, ask for their confirmation code or email

**IF USER REPORTS A MAINTENANCE ISSUE** (broken shower, AC not working, etc.):
→ Ask for their room number first
→ Then use report_maintenance_issue tool

**IF USER WANTS TO BOOK A NEW ROOM**:
{booking_summary}
→ Follow the progressive booking flow: dates → room selection → guest info

=== RESPONSE STYLE ===
- Be concise, friendly, and helpful
- Address what the user ACTUALLY asked
- Don't assume they want to book if they're asking about existing bookings
- Ask only ONE question at a time
- Use tools to take action, don't just describe what you would do

=== TOOLS AVAILABLE ===
- lookup_booking: Find existing booking by confirmation code, email, or name
- get_available_room_types: Check room availability for dates
- create_booking: Complete a new booking (need ALL guest info)
- report_maintenance_issue: Report broken items (need room number)
- request_room_cleaning: Request housekeeping (need room number)
- search_hotel_info: Answer hotel questions
- get_room_service_menu: Show food menu"""

        return prompt

    def _format_booking_state(self, booking: BookingState) -> str:
        """Format booking state for system prompt"""
        lines = []

        # Room
        if booking.get("room_type_id"):
            name = ROOM_TYPES.get(booking["room_type_id"], {}).get("name", "Unknown")
            lines.append(f"✓ Room: {name} (ID: {booking['room_type_id']})")
        else:
            lines.append("○ Room: Not selected")

        # Dates
        if booking.get("check_in_date"):
            lines.append(f"✓ Check-in: {booking['check_in_date']}")
        else:
            lines.append("○ Check-in: Not provided")

        if booking.get("check_out_date"):
            lines.append(f"✓ Check-out: {booking['check_out_date']}")
        else:
            lines.append("○ Check-out: Not provided")

        # Guests
        adults = booking.get("adults", 1)
        children = booking.get("children", 0)
        lines.append(f"✓ Guests: {adults} adults, {children} children")

        # Personal info
        if booking.get("first_name"):
            lines.append(f"✓ First name: {booking['first_name']}")
        else:
            lines.append("○ First name: Not provided")

        if booking.get("last_name"):
            lines.append(f"✓ Last name: {booking['last_name']}")
        else:
            lines.append("○ Last name: Not provided")

        if booking.get("email"):
            lines.append(f"✓ Email: {booking['email']}")
        else:
            lines.append("○ Email: Not provided")

        if booking.get("phone"):
            lines.append(f"✓ Phone: {booking['phone']}")
        else:
            lines.append("○ Phone: Not provided")

        if booking.get("country"):
            lines.append(f"✓ Country: {booking['country']}")
        else:
            lines.append("○ Country: Not provided")

        # Rooms shown flag
        lines.append(f"rooms_shown: {booking.get('rooms_shown', False)}")

        # What's needed next
        missing = self._get_next_missing(booking)
        if missing:
            lines.append(f"\n→ NEXT NEEDED: {missing}")
        else:
            lines.append("\n→ ALL INFO COLLECTED - CALL create_booking NOW!")

        return "\n".join(lines)

    def _get_next_missing(self, booking: BookingState) -> Optional[str]:
        """Get the next missing piece of information"""
        if not booking.get("room_type_id"):
            return "room selection"
        if not booking.get("check_in_date") or not booking.get("check_out_date"):
            return "dates"
        if not booking.get("first_name"):
            return "first name"
        if not booking.get("last_name"):
            return "last name"
        if not booking.get("email"):
            return "email"
        if not booking.get("phone"):
            return "phone"
        if not booking.get("country"):
            return "country"
        return None

    def _extract_info_from_message(self, message: str, current_state: BookingState) -> BookingState:
        """Extract booking information from user message"""
        new_state = dict(current_state)

        # Extract dates
        if not new_state.get("check_in_date") or not new_state.get("check_out_date"):
            check_in, check_out = extract_dates_from_message(message)
            if check_in:
                new_state["check_in_date"] = check_in
            if check_out:
                new_state["check_out_date"] = check_out

        # Extract room selection
        if not new_state.get("room_type_id"):
            room_id = extract_room_selection(message, new_state.get("rooms_shown", False))
            if room_id:
                new_state["room_type_id"] = room_id
                new_state["room_type_name"] = ROOM_TYPES[room_id]["name"]

        # Extract guest count
        adults, children = extract_guest_count(message)
        if adults > 1 or children > 0:
            new_state["adults"] = adults
            new_state["children"] = children
        elif "adults" not in new_state:
            new_state["adults"] = 1
            new_state["children"] = 0

        # Extract guest info
        guest_info = extract_guest_info(message)
        for key, value in guest_info.items():
            if value and not new_state.get(key):
                new_state[key] = value

        return new_state

    def _get_langchain_tools(self):
        """Get LangChain tools for the agent"""
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel, Field

        tools = []

        # Room availability tool
        class CheckAvailabilityInput(BaseModel):
            check_in_date: str = Field(description="Check-in date YYYY-MM-DD")
            check_out_date: str = Field(description="Check-out date YYYY-MM-DD")
            adults: int = Field(default=1, description="Number of adults")
            children: int = Field(default=0, description="Number of children")

        async def check_availability(check_in_date: str, check_out_date: str, adults: int = 1, children: int = 0) -> str:
            result = await self.booking_tools.get_available_room_types(
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                adults=adults,
                children=children
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=check_availability,
            name="get_available_room_types",
            description="Check room availability and pricing for given dates. Use this when guest wants to book and you need to show available rooms.",
            args_schema=CheckAvailabilityInput
        ))

        # Booking lookup tool
        class LookupBookingInput(BaseModel):
            confirmation_code: Optional[str] = Field(default=None, description="Booking confirmation code (e.g., GLM-ABC123)")
            guest_email: Optional[str] = Field(default=None, description="Guest email address")
            guest_name: Optional[str] = Field(default=None, description="Guest name")

        async def lookup_booking(confirmation_code: Optional[str] = None, guest_email: Optional[str] = None, guest_name: Optional[str] = None) -> str:
            result = await self.booking_tools.lookup_booking(
                confirmation_code=confirmation_code,
                guest_email=guest_email,
                guest_name=guest_name
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=lookup_booking,
            name="lookup_booking",
            description="Look up an existing booking by confirmation code, email, or guest name. Use when guest provides a confirmation code or asks about their booking.",
            args_schema=LookupBookingInput
        ))

        # Create booking tool
        class CreateBookingInput(BaseModel):
            room_type_id: int = Field(description="Room type ID (1-8)")
            check_in_date: str = Field(description="Check-in date YYYY-MM-DD")
            check_out_date: str = Field(description="Check-out date YYYY-MM-DD")
            guest_first_name: str = Field(description="Guest first name")
            guest_last_name: str = Field(description="Guest last name")
            guest_email: str = Field(description="Guest email")
            guest_phone: str = Field(description="Guest phone")
            guest_country: str = Field(description="Guest country")
            adults: int = Field(default=1)
            children: int = Field(default=0)
            special_requests: Optional[str] = Field(default=None)

        async def create_booking(
            room_type_id: int, check_in_date: str, check_out_date: str,
            guest_first_name: str, guest_last_name: str, guest_email: str,
            guest_phone: str, guest_country: str, adults: int = 1,
            children: int = 0, special_requests: Optional[str] = None
        ) -> str:
            result = await self.booking_tools.create_booking(
                room_type_id=room_type_id,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                guest_first_name=guest_first_name,
                guest_last_name=guest_last_name,
                guest_email=guest_email,
                guest_phone=guest_phone,
                guest_country=guest_country,
                adults=adults,
                children=children,
                special_requests=special_requests
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=create_booking,
            name="create_booking",
            description="Create a new room booking. Only use when you have ALL required info.",
            args_schema=CreateBookingInput
        ))

        # Housekeeping tool
        class RoomCleaningInput(BaseModel):
            room_number: str = Field(description="Room number")
            cleaning_type: str = Field(default="standard")
            special_instructions: Optional[str] = Field(default=None)
            priority: str = Field(default="normal")

        async def request_cleaning(room_number: str, cleaning_type: str = "standard",
                                   special_instructions: Optional[str] = None, priority: str = "normal") -> str:
            result = await self.housekeeping_tools.request_room_cleaning(
                room_number=room_number,
                cleaning_type=cleaning_type,
                special_instructions=special_instructions,
                priority=priority
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=request_cleaning,
            name="request_room_cleaning",
            description="Request housekeeping/room cleaning",
            args_schema=RoomCleaningInput
        ))

        # Hotel info tool
        class HotelInfoInput(BaseModel):
            query: str = Field(description="Question about hotel")

        async def search_info(query: str) -> str:
            result = await self.hotel_info_tools.search_faq(query=query)
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=search_info,
            name="search_hotel_info",
            description="Search hotel information and FAQs",
            args_schema=HotelInfoInput
        ))

        # Maintenance tool
        class MaintenanceInput(BaseModel):
            room_number: str = Field(description="Room number")
            issue_category: str = Field(description="Category: plumbing, electrical, hvac, appliance, wifi")
            issue_description: str = Field(description="Description of the issue")
            urgency: str = Field(default="normal")

        async def report_maintenance(room_number: str, issue_category: str,
                                     issue_description: str, urgency: str = "normal") -> str:
            result = await self.maintenance_tools.report_issue(
                room_number=room_number,
                issue_category=issue_category,
                issue_description=issue_description,
                urgency=urgency
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=report_maintenance,
            name="report_maintenance_issue",
            description="Report a maintenance issue",
            args_schema=MaintenanceInput
        ))

        # Room service menu
        class MenuInput(BaseModel):
            category: Optional[str] = Field(default=None)

        async def get_menu(category: Optional[str] = None) -> str:
            result = await self.room_service_tools.get_menu(category=category)
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=get_menu,
            name="get_room_service_menu",
            description="Get room service menu",
            args_schema=MenuInput
        ))

        # ==================== BILLING TOOLS ====================

        # View folio/bill
        class ViewFolioInput(BaseModel):
            room_number: str = Field(description="Guest's room number")
            booking_id: Optional[int] = Field(default=None, description="Booking ID if known")

        async def view_folio(room_number: str, booking_id: Optional[int] = None) -> str:
            result = await self.billing_tools.get_folio(
                room_number=room_number,
                booking_id=booking_id
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=view_folio,
            name="view_folio",
            description="View guest's bill/folio with all charges. Use when guest asks about their bill, charges, or balance.",
            args_schema=ViewFolioInput
        ))

        # Request checkout
        class CheckoutInput(BaseModel):
            room_number: str = Field(description="Guest's room number")
            express_checkout: bool = Field(default=False, description="Use express checkout")
            late_checkout: bool = Field(default=False, description="Request late checkout")
            feedback: Optional[str] = Field(default=None, description="Guest feedback")

        async def request_checkout(room_number: str, express_checkout: bool = False,
                                   late_checkout: bool = False, feedback: Optional[str] = None) -> str:
            result = await self.billing_tools.request_checkout(
                room_number=room_number,
                express_checkout=express_checkout,
                late_checkout=late_checkout,
                feedback=feedback
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=request_checkout,
            name="request_checkout",
            description="Request checkout, express checkout, or late checkout. Use when guest wants to check out or inquires about checkout.",
            args_schema=CheckoutInput
        ))

        # Dispute charge
        class DisputeChargeInput(BaseModel):
            room_number: str = Field(description="Guest's room number")
            charge_description: str = Field(description="Description of the disputed charge")
            dispute_reason: str = Field(description="Reason for the dispute")

        async def dispute_charge(room_number: str, charge_description: str, dispute_reason: str) -> str:
            result = await self.billing_tools.dispute_charge(
                room_number=room_number,
                charge_description=charge_description,
                dispute_reason=dispute_reason
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=dispute_charge,
            name="dispute_charge",
            description="Dispute a charge on the guest's bill. Use when guest questions or disputes a specific charge.",
            args_schema=DisputeChargeInput
        ))

        # Request receipt
        class RequestReceiptInput(BaseModel):
            room_number: str = Field(description="Guest's room number")
            email_address: Optional[str] = Field(default=None, description="Email for receipt")
            format_type: str = Field(default="email", description="Format: email, print, pdf")

        async def request_receipt(room_number: str, email_address: Optional[str] = None,
                                  format_type: str = "email") -> str:
            result = await self.billing_tools.request_receipt(
                room_number=room_number,
                email_address=email_address,
                format_type=format_type
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=request_receipt,
            name="request_receipt",
            description="Request a receipt or invoice. Use when guest asks for a receipt, invoice, or billing statement.",
            args_schema=RequestReceiptInput
        ))

        # ==================== PRE-CHECKIN TOOLS ====================

        # Verify booking for pre-checkin
        class VerifyPrecheckinInput(BaseModel):
            confirmation_code: str = Field(description="Booking confirmation code")
            guest_name: str = Field(description="Guest name for verification")

        async def verify_precheckin(confirmation_code: str, guest_name: str) -> str:
            result = await self.precheckin_tools.verify_booking_for_precheckin(
                confirmation_code=confirmation_code,
                guest_name=guest_name
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=verify_precheckin,
            name="verify_precheckin",
            description="Verify a booking is eligible for pre-check-in. Use when guest wants to start pre-check-in process.",
            args_schema=VerifyPrecheckinInput
        ))

        # Start pre-checkin
        class StartPrecheckinInput(BaseModel):
            reservation_id: int = Field(description="Reservation ID from verification")
            email: str = Field(description="Guest email")
            phone: str = Field(description="Guest phone")

        async def start_precheckin(reservation_id: int, email: str, phone: str) -> str:
            result = await self.precheckin_tools.start_precheckin(
                reservation_id=reservation_id,
                email=email,
                phone=phone
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=start_precheckin,
            name="start_precheckin",
            description="Start the pre-check-in process after verification.",
            args_schema=StartPrecheckinInput
        ))

        # Update preferences
        class UpdatePreferencesInput(BaseModel):
            precheckin_id: int = Field(description="Pre-check-in ID")
            floor_preference: Optional[str] = Field(default=None, description="Floor preference: low, mid, high, any")
            view_preference: Optional[str] = Field(default=None, description="View preference: ocean, city, garden, any")
            bed_type_preference: Optional[str] = Field(default=None, description="Bed type: king, queen, twin, any")
            quietness_preference: Optional[str] = Field(default=None, description="Quietness: quiet, moderate, any")
            arrival_time: Optional[str] = Field(default=None, description="Expected arrival time HH:MM")
            early_check_in: bool = Field(default=False, description="Request early check-in")

        async def update_preferences(precheckin_id: int, floor_preference: Optional[str] = None,
                                     view_preference: Optional[str] = None, bed_type_preference: Optional[str] = None,
                                     quietness_preference: Optional[str] = None, arrival_time: Optional[str] = None,
                                     early_check_in: bool = False) -> str:
            result = await self.precheckin_tools.update_preferences(
                precheckin_id=precheckin_id,
                floor_preference=floor_preference,
                view_preference=view_preference,
                bed_type_preference=bed_type_preference,
                quietness_preference=quietness_preference,
                arrival_time=arrival_time,
                early_check_in=early_check_in
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=update_preferences,
            name="update_precheckin_preferences",
            description="Update room preferences during pre-check-in. Use when guest specifies preferences like floor, view, bed type.",
            args_schema=UpdatePreferencesInput
        ))

        # Get room recommendations
        class GetRoomRecommendationsInput(BaseModel):
            precheckin_id: int = Field(description="Pre-check-in ID")

        async def get_room_recommendations(precheckin_id: int) -> str:
            result = await self.precheckin_tools.get_room_recommendations(
                precheckin_id=precheckin_id
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=get_room_recommendations,
            name="get_room_recommendations",
            description="Get AI-powered room recommendations based on guest preferences during pre-check-in.",
            args_schema=GetRoomRecommendationsInput
        ))

        # Select room for pre-checkin
        class SelectRoomInput(BaseModel):
            precheckin_id: int = Field(description="Pre-check-in ID")
            room_id: int = Field(description="Selected room ID from recommendations")

        async def select_room(precheckin_id: int, room_id: int) -> str:
            result = await self.precheckin_tools.select_room(
                precheckin_id=precheckin_id,
                room_id=room_id
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=select_room,
            name="select_precheckin_room",
            description="Select a specific room during pre-check-in process.",
            args_schema=SelectRoomInput
        ))

        # Complete pre-checkin
        class CompletePrecheckinInput(BaseModel):
            precheckin_id: int = Field(description="Pre-check-in ID")
            skip_id_verification: bool = Field(default=False, description="Skip ID verification (for testing)")

        async def complete_precheckin(precheckin_id: int, skip_id_verification: bool = False) -> str:
            result = await self.precheckin_tools.complete_precheckin(
                precheckin_id=precheckin_id,
                skip_id_verification=skip_id_verification
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=complete_precheckin,
            name="complete_precheckin",
            description="Complete the pre-check-in process and get digital key.",
            args_schema=CompletePrecheckinInput
        ))

        # Get pre-checkin status
        class GetPrecheckinStatusInput(BaseModel):
            confirmation_code: Optional[str] = Field(default=None, description="Booking confirmation code")
            precheckin_id: Optional[int] = Field(default=None, description="Pre-check-in ID")

        async def get_precheckin_status(confirmation_code: Optional[str] = None,
                                        precheckin_id: Optional[int] = None) -> str:
            result = await self.precheckin_tools.get_precheckin_status(
                confirmation_code=confirmation_code,
                precheckin_id=precheckin_id
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=get_precheckin_status,
            name="get_precheckin_status",
            description="Check the status of a pre-check-in process.",
            args_schema=GetPrecheckinStatusInput
        ))

        # ==================== CONCIERGE TOOLS ====================

        # Nearby recommendations
        class NearbyRecommendationsInput(BaseModel):
            category: str = Field(description="Category: restaurant, attraction, shopping, entertainment")
            cuisine: Optional[str] = Field(default=None, description="Cuisine type for restaurants")

        async def get_nearby_recommendations(category: str, cuisine: Optional[str] = None) -> str:
            result = await self.concierge_tools.get_nearby_recommendations(
                category=category,
                cuisine_type=cuisine
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=get_nearby_recommendations,
            name="get_nearby_recommendations",
            description="Get recommendations for restaurants, attractions, shopping near the hotel.",
            args_schema=NearbyRecommendationsInput
        ))

        # Arrange transportation
        class ArrangeTransportInput(BaseModel):
            transport_type: str = Field(description="Type: airport_shuttle, taxi, limo, car_rental")
            pickup_time: str = Field(description="Pickup time")
            destination: Optional[str] = Field(default=None, description="Destination")
            room_number: str = Field(description="Guest's room number")

        async def arrange_transportation(transport_type: str, pickup_time: str,
                                         destination: Optional[str] = None, room_number: str = "") -> str:
            result = await self.concierge_tools.arrange_transportation(
                transport_type=transport_type,
                pickup_time=pickup_time,
                destination=destination,
                guest_room=room_number
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=arrange_transportation,
            name="arrange_transportation",
            description="Arrange transportation: airport shuttle, taxi, limo, car rental.",
            args_schema=ArrangeTransportInput
        ))

        # ==================== CHATBOT ROUTING TOOLS ====================

        # Answer FAQ
        class AnswerFAQInput(BaseModel):
            query: str = Field(description="Guest's question")
            category: Optional[str] = Field(default=None, description="FAQ category: general, room, stay, amenities, policies, dining, transportation")

        async def answer_faq(query: str, category: Optional[str] = None) -> str:
            result = await self.chatbot_routing_tools.answer_faq(
                query=query,
                category=category
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=answer_faq,
            name="answer_faq",
            description="Answer frequently asked questions about the hotel. Use for general inquiries about policies, amenities, hours, etc.",
            args_schema=AnswerFAQInput
        ))

        # Get FAQ categories
        class GetFAQCategoriesInput(BaseModel):
            pass

        async def get_faq_categories() -> str:
            result = await self.chatbot_routing_tools.get_faq_categories()
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=get_faq_categories,
            name="get_faq_categories",
            description="Get available FAQ categories and sample questions. Use when guest wants to browse help topics.",
            args_schema=GetFAQCategoriesInput
        ))

        # Route request
        class RouteRequestInput(BaseModel):
            request_text: str = Field(description="Guest's request")
            room_number: str = Field(description="Guest's room number")
            guest_emotion: Optional[str] = Field(default=None, description="Detected emotion: happy, neutral, frustrated, upset")

        async def route_and_create_task(request_text: str, room_number: str, guest_emotion: Optional[str] = None) -> str:
            result = await self.chatbot_routing_tools.create_routed_task(
                request_text=request_text,
                room_number=room_number,
                guest_emotion=guest_emotion
            )
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=route_and_create_task,
            name="route_guest_request",
            description="Intelligently route a guest request to the appropriate department and create a task. Use for general requests when the specific department is unclear.",
            args_schema=RouteRequestInput
        ))

        # Get department contact
        class GetDepartmentContactInput(BaseModel):
            department: str = Field(description="Department name: front_desk, housekeeping, maintenance, room_service, concierge, billing, spa, security")

        async def get_department_contact(department: str) -> str:
            result = self.chatbot_routing_tools.get_department_contact(department)
            return json.dumps(result)

        tools.append(StructuredTool.from_function(
            coroutine=get_department_contact,
            name="get_department_contact",
            description="Get contact information (phone extension) for a hotel department.",
            args_schema=GetDepartmentContactInput
        ))

        return tools

    def _build_graph(self):
        """Build the LangGraph agent"""
        tools = self._get_langchain_tools()
        self.tools = tools
        self.llm_with_tools = self.llm.bind_tools(tools)

        async def agent_node(state: AgentState) -> Dict[str, Any]:
            """Main agent node - processes messages and decides actions"""
            messages = list(state["messages"])

            # Build system prompt with current state
            system_prompt = self._build_system_prompt(state)

            # Prepend system message
            full_messages = [SystemMessage(content=system_prompt)] + messages

            # Call LLM
            response = await self.llm_with_tools.ainvoke(full_messages)

            # Check if response contains room list (to track rooms_shown)
            new_booking_state = dict(state.get("booking_state", {}))
            if response.content and ("Minimalist Studio" in response.content or "room type" in response.content.lower()):
                new_booking_state["rooms_shown"] = True

            return {
                "messages": [response],
                "booking_state": new_booking_state
            }

        async def tools_node(state: AgentState) -> Dict[str, Any]:
            """Execute tool calls"""
            messages = state["messages"]
            last_message = messages[-1]

            tool_results = []
            new_booking_state = dict(state.get("booking_state", {}))

            for tool_call in last_message.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                logger.info(f"Executing tool: {tool_name} with args: {tool_args}")

                # Find and call the tool
                for tool in self.tools:
                    if tool.name == tool_name:
                        try:
                            result = await tool.ainvoke(tool_args)
                            tool_results.append(
                                ToolMessage(content=result, tool_call_id=tool_call["id"])
                            )

                            # Track rooms_shown if we called availability
                            if tool_name == "get_available_room_types":
                                new_booking_state["rooms_shown"] = True

                        except Exception as e:
                            logger.error(f"Tool error: {e}")
                            tool_results.append(
                                ToolMessage(
                                    content=json.dumps({"success": False, "error": str(e)}),
                                    tool_call_id=tool_call["id"]
                                )
                            )
                        break

            return {
                "messages": tool_results,
                "booking_state": new_booking_state
            }

        def should_continue(state: AgentState) -> Literal["tools", "end"]:
            """Decide whether to continue to tools or end"""
            messages = state["messages"]
            last_message = messages[-1]

            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                return "tools"
            return "end"

        # Build graph
        workflow = StateGraph(AgentState)

        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tools_node)

        workflow.set_entry_point("agent")

        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {"tools": "tools", "end": END}
        )

        workflow.add_edge("tools", "agent")

        self.graph = workflow.compile()

    def _detect_intent(self, message: str) -> Tuple[str, float]:
        """Detect intent from message"""
        message_lower = message.lower().strip()

        # Check for confirmation code pattern first (GLM-XXXXX or similar)
        if re.match(r'^[a-z]{2,4}[-_]?[a-z0-9]{4,10}$', message_lower.replace(' ', '')):
            return "booking_lookup", 0.95

        # Check for "my booking(s)" pattern
        if re.search(r'\b(my\s+)?booking(s)?\b', message_lower) and not re.search(r'\bbook\s+a\b', message_lower):
            return "booking_lookup", 0.9

        # Check for "how many bookings" pattern
        if re.search(r'how\s+many\s+booking', message_lower):
            return "booking_lookup", 0.9

        intent_keywords = {
            "new_booking": ["book a room", "make a reservation", "reserve a room", "want to book", "need a room", "available rooms"],
            "booking_lookup": ["my booking", "my reservation", "check booking", "find booking", "lookup", "confirmation"],
            "housekeeping": ["clean", "towel", "sheets", "housekeeping", "maid", "pillows", "linens"],
            "maintenance": ["broken", "fix", "repair", "not working", "doesn't work", "leaking", "leak", "shower", "toilet", "ac", "air condition", "heating", "wifi slow"],
            "room_service": ["food", "menu", "order food", "hungry", "eat", "drink", "breakfast", "lunch", "dinner"],
            "billing": ["bill", "charge", "checkout", "payment", "receipt", "invoice", "folio", "balance", "expenses", "statement"],
            "precheckin": ["pre-check", "precheckin", "pre check in", "early check", "mobile check", "online check", "check in early", "arrive early"],
            "hotel_info": ["wifi password", "pool", "gym", "parking", "hours", "amenity", "amenities", "check-in time", "check-out time"],
            "greeting": ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"],
            "concierge": ["restaurant", "recommend", "nearby", "taxi", "uber", "transportation", "shuttle", "airport", "attraction", "things to do"],
        }

        best_intent = "general"
        best_score = 0

        for intent, keywords in intent_keywords.items():
            score = 0
            for kw in keywords:
                if kw in message_lower:
                    # Give higher score for multi-word matches
                    score += len(kw.split())
            if score > best_score:
                best_score = score
                best_intent = intent

        confidence = min(best_score / 3, 1.0) if best_score > 0 else 0.3
        return best_intent, confidence

    def _detect_emotion(self, message: str) -> str:
        """
        Detect guest emotion from message tone.
        Returns: happy, neutral, frustrated, upset
        """
        message_lower = message.lower()

        # Frustrated/Upset indicators
        frustrated_patterns = [
            r"still\s+(not|broken|waiting)",
            r"(how|what)\s+(long|many\s+times)",
            r"this\s+is\s+(ridiculous|unacceptable|terrible)",
            r"(never|worst|horrible|awful|disgusting)",
            r"(can't|cannot)\s+believe",
            r"what\s+the\s+hell",
            r"again\?",
            r"not\s+happy",
            r"disappointed",
            r"frustrated",
            r"angry",
            r"upset",
            r"!{2,}",  # Multiple exclamation marks
        ]

        for pattern in frustrated_patterns:
            if re.search(pattern, message_lower):
                # Check severity
                if any(word in message_lower for word in ["worst", "terrible", "horrible", "awful", "disgusting", "angry"]):
                    return "upset"
                return "frustrated"

        # Happy indicators
        happy_patterns = [
            r"(thank|thanks|thx)\s*(you|u)?",
            r"(great|excellent|wonderful|amazing|perfect|fantastic|awesome)",
            r"(love|loving|loved)\s+(it|this|the)",
            r"appreciate",
            r"(so\s+)?helpful",
            r":[\)D]|😊|😃|👍|🎉|❤️",
            r"you('re|\s+are)\s+(the\s+)?best",
        ]

        for pattern in happy_patterns:
            if re.search(pattern, message_lower):
                return "happy"

        # Default to neutral
        return "neutral"

    async def process_message(
        self,
        message: str,
        session_id: str,
        user_id: Optional[int] = None,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        room_number: Optional[str] = None,
        voice_input: bool = False
    ) -> AGIResponse:
        """Process a guest message"""
        try:
            # Get/create context
            context = await self.memory_manager.get_or_create_context(
                session_id=session_id,
                user_id=user_id,
                guest_id=guest_id,
                booking_id=booking_id,
                room_number=room_number
            )

            # Get existing booking state from memory
            collected = self.memory_manager.get_collected_info(session_id)
            current_booking_state: BookingState = {
                "room_type_id": collected.get("room_type_id"),
                "room_type_name": collected.get("room_type_name"),
                "check_in_date": collected.get("check_in_date"),
                "check_out_date": collected.get("check_out_date"),
                "adults": collected.get("adults", 1),
                "children": collected.get("children", 0),
                "first_name": collected.get("first_name"),
                "last_name": collected.get("last_name"),
                "email": collected.get("email"),
                "phone": collected.get("phone"),
                "country": collected.get("country"),
                "rooms_shown": collected.get("rooms_shown", False),
            }

            # Extract info from current message
            updated_booking_state = self._extract_info_from_message(message, current_booking_state)

            # Save extracted info to memory
            for key, value in updated_booking_state.items():
                if value is not None:
                    self.memory_manager.collect_info(session_id, key, value)

            logger.info(f"Booking state after extraction: {updated_booking_state}")

            # Detect intent
            intent, confidence = self._detect_intent(message)

            # Detect emotion and track it
            emotion = self._detect_emotion(message)
            await self.memory_manager.update_guest_emotion(session_id, emotion)

            # If guest is frustrated/upset, log and adjust response behavior
            if emotion in ["frustrated", "upset"]:
                logger.warning(f"Guest emotion detected: {emotion} - Session: {session_id}")

            # Add message to memory with emotion metadata
            self.memory_manager.add_message_to_memory(
                session_id, "user", message,
                metadata={"emotion": emotion, "intent": intent}
            )

            # Get conversation history
            recent_messages = self.memory_manager.get_recent_messages(session_id, limit=10)

            # Build messages for graph
            graph_messages = []
            for msg in recent_messages[:-1]:
                if msg["role"] == "user":
                    graph_messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    graph_messages.append(AIMessage(content=msg["content"]))

            graph_messages.append(HumanMessage(content=message))

            # Prepare initial state
            initial_state: AgentState = {
                "messages": graph_messages,
                "booking_state": updated_booking_state,
                "guest_context": self.memory_manager.serialize_context(session_id),
                "current_intent": intent,
                "session_id": session_id,
                "last_assistant_action": None,
            }

            # Run the graph
            result = await self.graph.ainvoke(initial_state)

            # Extract response
            final_messages = result["messages"]
            response_message = ""
            action_taken = False
            action_result = None
            task_id = None
            task_type = None

            for msg in reversed(final_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    response_message = msg.content
                    break
                elif isinstance(msg, ToolMessage):
                    action_taken = True
                    try:
                        action_result = json.loads(msg.content)
                        task_id = action_result.get("task_id")
                        task_type = action_result.get("task_type")
                    except:
                        pass

            # Update booking state from result
            final_booking_state = result.get("booking_state", updated_booking_state)
            for key, value in final_booking_state.items():
                if value is not None:
                    self.memory_manager.collect_info(session_id, key, value)

            # Add response to memory
            self.memory_manager.add_message_to_memory(session_id, "assistant", response_message)

            # Generate quick actions
            quick_actions = self._generate_quick_actions(intent)

            return AGIResponse(
                message=response_message,
                intent=intent,
                confidence=confidence,
                action_taken=action_taken,
                action_result=action_result,
                task_id=task_id,
                task_type=task_type,
                quick_actions=quick_actions,
                guest_context=self.memory_manager.serialize_context(session_id),
                follow_up_needed=action_taken and task_id is not None,
                guest_emotion=emotion
            )

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return AGIResponse(
                message="I apologize, but I encountered an issue. Please try again or contact our front desk.",
                intent="error",
                confidence=0.0,
                quick_actions=[
                    {"label": "Try Again", "action": "retry"},
                    {"label": "Contact Front Desk", "action": "front_desk"}
                ]
            )

    async def process_voice(
        self,
        audio_data: bytes,
        session_id: str,
        audio_format: str = "webm",
        require_wake_word: bool = False,
        **kwargs
    ) -> AGIResponse:
        """
        Process voice input with optional wake word detection.

        Args:
            audio_data: Raw audio bytes
            session_id: Session ID
            audio_format: Audio format (default webm)
            require_wake_word: If True, only process when wake word is detected
            **kwargs: Additional args for process_message
        """
        # Transcribe with wake word detection
        transcription = await self.voice_processor.transcribe_with_wake_word(
            audio_data=audio_data,
            audio_format=audio_format,
            require_wake_word=require_wake_word
        )

        if not transcription.get("success"):
            return AGIResponse(
                message="I couldn't understand the audio. Please try again.",
                intent="error",
                confidence=0.0
            )

        # Check if wake word required but not detected
        if require_wake_word and not transcription.get("should_process", True):
            return AGIResponse(
                message=transcription.get("message", "Listening for 'Hey Baarez'..."),
                intent="listening",
                confidence=0.0,
                wake_word_detected=False
            )

        # Use the command (text after wake word) or full text
        message_text = transcription.get("command") or transcription.get("text", "")

        response = await self.process_message(
            message=message_text,
            session_id=session_id,
            voice_input=True,
            **kwargs
        )

        # Update wake word detection status
        response.wake_word_detected = transcription.get("wake_word_detected", False)

        return response

    async def process_voice_with_confirmation(
        self,
        audio_data: bytes,
        session_id: str,
        pending_action: Optional[Dict[str, Any]] = None,
        audio_format: str = "webm"
    ) -> AGIResponse:
        """
        Process voice input that may be a confirmation for a pending action.

        Args:
            audio_data: Raw audio bytes
            session_id: Session ID
            pending_action: Pending action awaiting confirmation
            audio_format: Audio format
        """
        # Transcribe
        transcription = await self.voice_processor.transcribe_audio(audio_data, audio_format)

        if not transcription.get("success"):
            return AGIResponse(
                message="I couldn't understand your response. Please say 'yes' to confirm or 'no' to cancel.",
                intent="confirmation_unclear",
                confidence=0.0,
                requires_confirmation=True
            )

        text = transcription.get("text", "")

        # If there's a pending action, check for confirmation
        if pending_action:
            confirmation = self.voice_processor.parse_confirmation_response(text)

            if confirmation["confirmed"] is True:
                # Execute the pending action
                return AGIResponse(
                    message=f"Confirmed! Processing your {pending_action.get('action_type', 'request')}...",
                    intent="confirmation_accepted",
                    confidence=confirmation["confidence"],
                    action_taken=True,
                    action_result={"status": "confirmed", "action": pending_action}
                )
            elif confirmation["confirmed"] is False:
                return AGIResponse(
                    message="No problem, I've cancelled that request.",
                    intent="confirmation_rejected",
                    confidence=confirmation["confidence"]
                )
            else:
                # Unclear response
                return AGIResponse(
                    message=confirmation.get("message", "Please say 'yes' to confirm or 'no' to cancel."),
                    intent="confirmation_unclear",
                    confidence=confirmation["confidence"],
                    requires_confirmation=True
                )

        # No pending action, process normally
        return await self.process_message(
            message=text,
            session_id=session_id,
            voice_input=True
        )

    def _generate_quick_actions(self, intent: str) -> List[Dict[str, str]]:
        """Generate quick action buttons"""
        if intent == "new_booking":
            return [
                {"label": "View Rooms", "action": "Show me available rooms"},
                {"label": "Check Rates", "action": "What are your rates?"},
            ]
        elif intent == "housekeeping":
            return [
                {"label": "Extra Towels", "action": "I need extra towels"},
                {"label": "Room Cleaning", "action": "Please clean my room"},
            ]
        elif intent == "room_service":
            return [
                {"label": "View Menu", "action": "Show me the menu"},
                {"label": "Order Status", "action": "Check my order status"},
            ]
        else:
            return [
                {"label": "Book Room", "action": "I want to book a room"},
                {"label": "Housekeeping", "action": "I need housekeeping"},
                {"label": "Hotel Info", "action": "Tell me about the hotel"},
            ]


def get_agi_agent(db: AsyncSession) -> AGIGuestAgent:
    """Factory function"""
    return AGIGuestAgent(db)
