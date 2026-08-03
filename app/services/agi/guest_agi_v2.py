"""
Guest AGI V2 - Comprehensive AI Assistant for Hotel Guests
A production-grade AGI system with full guest services support.

Features:
- Authentication-aware (handles logged in vs anonymous users)
- Complete booking flow with OTP verification and email confirmation
- Profile management (view/edit)
- Booking management (view, cancel, modify)
- Pre-checkin with room selection
- Booking history and past stays
- Loyalty points system
- In-house assistance (WiFi, amenities, staff help)
- FAQ and hotel information
- Housekeeping, maintenance, room service (for checked-in guests)
"""

import logging
import json
import re
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Literal, Sequence
try:
    from typing import Annotated
except ImportError:
    from typing_extensions import Annotated
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum

try:
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
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
    END = "end"
    def add_messages(left, right):
        return (left or []) + (right or [])

from sqlmodel import select, and_, or_, desc
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.models.reservations import Guest, Booking
from app.models.precheckin import PreCheckIn
from app.models.inventory import Room, RoomType
from app.models.otp import EmailOTP
from app.models.guest_chat import StaffTask

logger = logging.getLogger("agi.guest_v2")


# ==================== ENUMS & CONSTANTS ====================

class GuestStatus(str, Enum):
    ANONYMOUS = "anonymous"  # Not logged in
    REGISTERED = "registered"  # Logged in but no active booking
    BOOKED = "booked"  # Has upcoming booking
    CHECKED_IN = "checked_in"  # Currently staying
    CHECKED_OUT = "checked_out"  # Past guest


class ConversationIntent(str, Enum):
    GREETING = "greeting"
    NEW_BOOKING = "new_booking"
    VIEW_BOOKINGS = "view_bookings"
    MODIFY_BOOKING = "modify_booking"
    CANCEL_BOOKING = "cancel_booking"
    PRE_CHECKIN = "pre_checkin"
    VIEW_PROFILE = "view_profile"
    EDIT_PROFILE = "edit_profile"
    LOYALTY_POINTS = "loyalty_points"
    BOOKING_HISTORY = "booking_history"
    HOUSEKEEPING = "housekeeping"
    MAINTENANCE = "maintenance"
    ROOM_SERVICE = "room_service"
    WIFI_INFO = "wifi_info"
    HOTEL_INFO = "hotel_info"
    FAQ = "faq"
    STAFF_HELP = "staff_help"
    CHECKOUT = "checkout"
    BILLING = "billing"
    GENERAL = "general"


# Room types mapping
ROOM_TYPES = {
    1: "Minimalist Studio",
    2: "Coastal Retreat",
    3: "Urban Oasis",
    4: "Sunset Vista",
    5: "Pacific Suite",
    6: "Wellness Suite",
    7: "Family Sanctuary",
    8: "Oceanfront Penthouse",
}

# WiFi and hotel info
HOTEL_INFO = {
    "wifi_password": "Glimmora2025",
    "wifi_network": "Glimmora-Guest",
    "checkout_time": "11:00 AM",
    "checkin_time": "3:00 PM",
    "pool_hours": "6:00 AM - 10:00 PM",
    "gym_hours": "24 hours",
    "spa_hours": "9:00 AM - 9:00 PM",
    "restaurant_hours": "6:30 AM - 10:30 PM",
    "room_service_hours": "24 hours",
    "front_desk": "24 hours",
    "parking": "Complimentary valet parking",
    "address": "123 Ocean Drive, Malibu, CA 90265",
    "phone": "+1 (310) 555-0123",
}


# ==================== STATE TYPES ====================

class BookingFlowState(TypedDict, total=False):
    """State for new booking flow"""
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
    rooms_shown: bool
    room_prices: Optional[Dict[int, float]]  # Stored when rooms are shown
    total_price: Optional[float]  # Stored when room is selected
    otp_sent: bool
    otp_verified: bool
    booking_created: bool
    booking_id: Optional[int]
    confirmation_code: Optional[str]


class GuestContext(TypedDict, total=False):
    """Complete guest context"""
    user_id: Optional[int]
    guest_id: Optional[int]
    email: Optional[str]
    full_name: Optional[str]
    phone: Optional[str]
    status: str  # GuestStatus value
    loyalty_points: int
    loyalty_tier: Optional[str]
    is_vip: bool

    # Current stay info (if checked in)
    current_booking_id: Optional[int]
    current_room_number: Optional[str]
    current_room_type: Optional[str]
    check_in_date: Optional[str]
    check_out_date: Optional[str]

    # Upcoming bookings count
    upcoming_bookings: int
    past_bookings: int


class AgentState(TypedDict):
    """Complete agent state"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    guest_context: GuestContext
    booking_flow: BookingFlowState
    current_intent: str
    session_id: str
    awaiting_input: Optional[str]  # What we're waiting for (otp, confirmation, etc.)


# ==================== RESPONSE TYPE ====================

@dataclass
class AGIResponse:
    """Response from AGI agent"""
    message: str
    intent: str
    confidence: float
    action_taken: bool = False
    action_result: Optional[Dict[str, Any]] = None
    requires_auth: bool = False
    requires_otp: bool = False
    otp_email: Optional[str] = None  # Email where OTP was sent
    otp_purpose: Optional[str] = None
    quick_actions: Optional[List[Dict[str, str]]] = None
    guest_context: Optional[Dict[str, Any]] = None
    booking_created: Optional[int] = None  # Booking ID if created
    show_login_prompt: bool = False
    # Fields expected by API
    task_id: Optional[int] = None
    task_type: Optional[str] = None
    follow_up_needed: bool = False
    guest_status: Optional[str] = None
    loyalty_points: Optional[int] = None
    loyalty_tier: Optional[str] = None


# ==================== DATE PARSING ====================

def parse_date(date_str: str) -> Optional[str]:
    """Parse various date formats to YYYY-MM-DD"""
    if not date_str:
        return None

    date_str = date_str.lower().strip()
    now = datetime.now()
    current_year = now.year

    if date_str == "today":
        return now.strftime("%Y-%m-%d")
    if date_str == "tomorrow":
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")

    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    month_map = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
        "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12
    }

    try:
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


def extract_confirmation_code(message: str) -> Optional[str]:
    """Extract a booking confirmation code from the message.

    Supports patterns like:
    - GLM-ABC123
    - GLMABC123
    - GLM ABC123
    - glm-trb0jz
    """
    message_upper = message.upper().strip()

    # Pattern 1: GLM-XXXXXX (with hyphen)
    match = re.search(r'\b(GLM[-_]?[A-Z0-9]{4,10})\b', message_upper)
    if match:
        code = match.group(1)
        # Normalize to GLM-XXXXXX format
        if '-' not in code and '_' not in code:
            code = 'GLM-' + code[3:]
        return code.replace('_', '-')

    # Pattern 2: Just the code part if message is mainly a code
    # e.g., user just types "TRB0JZ"
    clean_msg = re.sub(r'[^A-Z0-9]', '', message_upper)
    if len(clean_msg) >= 6 and len(clean_msg) <= 12:
        if clean_msg.startswith('GLM'):
            return 'GLM-' + clean_msg[3:]
        # Check if it looks like a code (mix of letters and numbers)
        if re.match(r'^[A-Z0-9]{6,10}$', clean_msg) and re.search(r'[A-Z]', clean_msg) and re.search(r'[0-9]', clean_msg):
            return 'GLM-' + clean_msg

    return None


def extract_dates(message: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract check-in and check-out dates from message"""
    message_lower = message.lower()

    # Range patterns
    range_patterns = [
        r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*(\w{3,9})\s*(?:to|-|till|until)\s*(\d{1,2})\s*(?:st|nd|rd|th)?\s*(\w{3,9})(?:\s+(\d{4}))?",
        r"(\w{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|-|till|until)\s*(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?",
        r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|-|till|until)\s*(\d{1,2})(?:st|nd|rd|th)?\s*(\w{3,9})(?:\s+(\d{4}))?",
    ]

    for pattern in range_patterns:
        match = re.search(pattern, message_lower)
        if match:
            groups = match.groups()

            if len(groups) >= 4 and groups[0].isdigit() and groups[2].isdigit() and len(groups[1]) > 2:
                # "8 december to 10 december"
                day1, month1, day2, month2 = groups[0], groups[1], groups[2], groups[3]
                year = groups[4] if len(groups) > 4 else None
                check_in = parse_date(f"{day1} {month1}" + (f" {year}" if year else ""))
                check_out = parse_date(f"{day2} {month2}" + (f" {year}" if year else ""))
                if check_in and check_out:
                    return check_in, check_out

            elif len(groups) >= 3 and groups[0].isalpha():
                # "december 8 to 10"
                month = groups[0]
                day1 = groups[1]
                day2 = groups[2]
                year = groups[3] if len(groups) > 3 else None
                check_in = parse_date(f"{month} {day1}" + (f" {year}" if year else ""))
                check_out = parse_date(f"{month} {day2}" + (f" {year}" if year else ""))
                if check_in and check_out:
                    return check_in, check_out

            elif len(groups) >= 3 and groups[0].isdigit() and groups[1].isdigit():
                # "8 to 10 december"
                day1, day2, month = groups[0], groups[1], groups[2]
                year = groups[3] if len(groups) > 3 else None
                check_in = parse_date(f"{day1} {month}" + (f" {year}" if year else ""))
                check_out = parse_date(f"{day2} {month}" + (f" {year}" if year else ""))
                if check_in and check_out:
                    return check_in, check_out

    # Single dates
    date_pattern = r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w{3,9})(?:\s+(\d{4}))?|(\w{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?"
    matches = list(re.finditer(date_pattern, message_lower))

    dates = []
    for match in matches:
        d = parse_date(match.group(0))
        if d and d not in dates:
            dates.append(d)

    if len(dates) >= 2:
        return dates[0], dates[1]
    elif len(dates) == 1:
        return dates[0], None

    return None, None


def extract_room_selection(message: str, rooms_shown: bool) -> Optional[int]:
    """Extract room selection from message"""
    message_lower = message.lower().strip()

    # Number selection
    if re.match(r"^(\d)$", message_lower) and rooms_shown:
        num = int(message_lower)
        if 1 <= num <= 8:
            return num

    # "option X" or "number X"
    match = re.search(r"(?:option|number|#)\s*(\d)", message_lower)
    if match and rooms_shown:
        num = int(match.group(1))
        if 1 <= num <= 8:
            return num

    # Room name keywords
    keywords = {
        1: ["minimalist", "studio"],
        2: ["coastal", "retreat"],
        3: ["urban", "oasis"],
        4: ["sunset", "vista"],
        5: ["pacific"],
        6: ["wellness"],
        7: ["family", "sanctuary"],
        8: ["oceanfront", "penthouse"],
    }

    for room_id, kws in keywords.items():
        if any(kw in message_lower for kw in kws):
            return room_id

    return None


def extract_otp(message: str) -> Optional[str]:
    """Extract 6-digit OTP from message"""
    match = re.search(r"\b(\d{6})\b", message)
    if match:
        return match.group(1)
    return None


def extract_guest_info(message: str) -> Dict[str, Optional[str]]:
    """Extract guest personal information"""
    info = {}

    # Email
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", message, re.IGNORECASE)
    if email_match:
        info["email"] = email_match.group().lower()

    # Phone
    phone_match = re.search(r"[\+]?[(]?[0-9]{1,3}[)]?[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,9}", message)
    if phone_match and len(phone_match.group().replace(" ", "").replace("-", "")) >= 7:
        info["phone"] = phone_match.group()

    # Name
    name_patterns = [
        r"(?:my name is|i'm|i am|name[:\s]+)\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)",
        r"^([A-Za-z]+\s+[A-Za-z]+)$",
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
    countries = ["usa", "us", "uk", "united states", "india", "canada", "australia",
                 "germany", "france", "spain", "italy", "japan", "china", "brazil"]
    message_lower = message.lower()
    for country in countries:
        if country in message_lower:
            info["country"] = country.upper() if len(country) <= 2 else country.title()
            break

    return info


def extract_guest_count(message: str) -> Tuple[int, int]:
    """Extract adults and children count"""
    message_lower = message.lower()
    adults = 1
    children = 0

    # Adults
    adult_patterns = [
        r"(\d+)\s*(?:adult|guest|person|people)",
        r"(?:for|with)\s*(\d+)",
    ]
    for pattern in adult_patterns:
        match = re.search(pattern, message_lower)
        if match:
            adults = min(int(match.group(1)), 10)
            break

    # Children
    child_patterns = [r"(\d+)\s*(?:child|children|kid|kids)"]
    for pattern in child_patterns:
        match = re.search(pattern, message_lower)
        if match:
            children = min(int(match.group(1)), 10)
            break

    return adults, children


# ==================== GLOBAL SESSION STORE ====================
# Module-level session storage - persists across API calls
# This ensures conversation context is maintained between requests
_GLOBAL_SESSIONS: Dict[str, Dict[str, Any]] = {}

def _cleanup_old_sessions():
    """Remove sessions older than 1 hour to prevent memory bloat"""
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(hours=1)
    expired = [
        sid for sid, data in _GLOBAL_SESSIONS.items()
        if data.get("last_access") and datetime.fromisoformat(data["last_access"]) < cutoff
    ]
    for sid in expired:
        del _GLOBAL_SESSIONS[sid]


# ==================== MAIN AGI CLASS ====================

class GuestAGIV2:
    """
    Comprehensive Guest AGI Assistant
    """

    def __init__(self, db: AsyncSession):
        self.db = db

        # Initialize LLM
        self.llm = ChatOpenAI(
            model=settings.openai_model or "gpt-4o",
            api_key=settings.openai_api_key,
            temperature=0.3,
            max_tokens=2000
        )

        # Use global session storage for persistence across requests
        self._sessions = _GLOBAL_SESSIONS

    # ==================== CONTEXT LOADING ====================

    async def _load_guest_context(
        self,
        user_id: Optional[int] = None,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        room_number: Optional[str] = None,
        email: Optional[str] = None
    ) -> GuestContext:
        """Load complete guest context from database"""
        context: GuestContext = {
            "user_id": user_id,
            "guest_id": guest_id,
            "email": email,
            "full_name": None,
            "phone": None,
            "status": GuestStatus.ANONYMOUS.value,
            "loyalty_points": 0,
            "loyalty_tier": None,
            "is_vip": False,
            "current_booking_id": booking_id,
            "current_room_number": room_number,
            "current_room_type": None,
            "check_in_date": None,
            "check_out_date": None,
            "upcoming_bookings": 0,
            "past_bookings": 0,
        }

        if not user_id and not email and not guest_id:
            return context

        try:
            # Load user
            if user_id:
                result = await self.db.exec(
                    select(User).where(User.id == user_id)
                )
                user = result.first()
                if user:
                    context["email"] = user.email
                    context["full_name"] = user.full_name
                    context["phone"] = user.phone
                    context["status"] = GuestStatus.REGISTERED.value

            # Load guest profile - by ID first, then by email
            guest = None
            if guest_id:
                result = await self.db.exec(
                    select(Guest).where(Guest.id == guest_id)
                )
                guest = result.first()

            if not guest:
                guest_email = context.get("email") or email
                if guest_email:
                    result = await self.db.exec(
                        select(Guest).where(Guest.email == guest_email)
                    )
                    guest = result.first()

            if guest:
                context["guest_id"] = guest.id
                context["full_name"] = context["full_name"] or f"{guest.first_name} {guest.last_name}"
                context["phone"] = context["phone"] or guest.phone
                context["email"] = context["email"] or guest.email
                context["loyalty_points"] = guest.loyalty_points or 0
                context["loyalty_tier"] = guest.loyalty_tier
                context["is_vip"] = guest.vip_status or False

            # Check for current/upcoming bookings
            if context.get("guest_id") or user_id:
                today = date.today()

                # Current stay (checked_in)
                query = select(Booking).where(
                    and_(
                        Booking.status == "checked_in",
                        or_(
                            Booking.guest_id == context.get("guest_id"),
                            Booking.user_id == user_id
                        ) if context.get("guest_id") else Booking.user_id == user_id
                    )
                )
                result = await self.db.exec(query)
                current_booking = result.first()

                if current_booking:
                    context["status"] = GuestStatus.CHECKED_IN.value
                    context["current_booking_id"] = current_booking.id
                    context["check_in_date"] = str(current_booking.arrival_date)
                    context["check_out_date"] = str(current_booking.departure_date)

                    # Get room info
                    if current_booking.room_id:
                        room_result = await self.db.exec(
                            select(Room).where(Room.id == current_booking.room_id)
                        )
                        room = room_result.first()
                        if room:
                            context["current_room_number"] = room.number
                            context["current_room_type"] = ROOM_TYPES.get(current_booking.room_type_id, "Unknown")

                # Count upcoming bookings
                query = select(Booking).where(
                    and_(
                        Booking.status.in_(["pending", "confirmed", "booked"]),
                        Booking.arrival_date >= today,
                        or_(
                            Booking.guest_id == context.get("guest_id"),
                            Booking.user_id == user_id
                        ) if context.get("guest_id") else Booking.user_id == user_id
                    )
                )
                result = await self.db.exec(query)
                upcoming = result.all()
                context["upcoming_bookings"] = len(upcoming)

                if upcoming and context["status"] != GuestStatus.CHECKED_IN.value:
                    context["status"] = GuestStatus.BOOKED.value

                # Count past bookings
                query = select(Booking).where(
                    and_(
                        Booking.status == "checked_out",
                        or_(
                            Booking.guest_id == context.get("guest_id"),
                            Booking.user_id == user_id
                        ) if context.get("guest_id") else Booking.user_id == user_id
                    )
                )
                result = await self.db.exec(query)
                past = result.all()
                context["past_bookings"] = len(past)

        except Exception as e:
            logger.error(f"Error loading guest context: {e}")

        return context

    # ==================== SESSION MANAGEMENT ====================

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        """Get or create session data"""
        # Periodically cleanup old sessions (every 100 accesses)
        if len(self._sessions) > 100:
            _cleanup_old_sessions()

        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "messages": [],
                "booking_flow": {},
                "collected_info": {},
                "awaiting_input": None,
                "active_intent": None,  # Track the current conversation flow
                "last_access": datetime.now().isoformat(),
            }
        else:
            # Update last access time
            self._sessions[session_id]["last_access"] = datetime.now().isoformat()

        logger.info(f"Session {session_id[:20]}... - Active intent: {self._sessions[session_id].get('active_intent')}, Booking flow: {bool(self._sessions[session_id].get('booking_flow'))}")
        return self._sessions[session_id]

    def _save_message(self, session_id: str, role: str, content: str):
        """Save message to session"""
        session = self._get_session(session_id)
        session["messages"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        # Keep only last 20 messages
        if len(session["messages"]) > 20:
            session["messages"] = session["messages"][-20:]

    def _get_booking_flow(self, session_id: str) -> BookingFlowState:
        """Get booking flow state"""
        session = self._get_session(session_id)
        return session.get("booking_flow", {})

    def _get_active_intent(self, session_id: str) -> Optional[str]:
        """Get the active conversation intent"""
        session = self._get_session(session_id)
        return session.get("active_intent")

    def _set_active_intent(self, session_id: str, intent: Optional[str]):
        """Set the active conversation intent"""
        session = self._get_session(session_id)
        session["active_intent"] = intent

    def _update_booking_flow(self, session_id: str, updates: Dict[str, Any]):
        """Update booking flow state"""
        session = self._get_session(session_id)
        if "booking_flow" not in session:
            session["booking_flow"] = {}
        session["booking_flow"].update(updates)

    def _clear_booking_flow(self, session_id: str):
        """Clear booking flow state"""
        session = self._get_session(session_id)
        session["booking_flow"] = {}
        session["active_intent"] = None

    # ==================== LLM-POWERED INTENT DETECTION ====================

    async def _detect_intent_with_llm(
        self,
        message: str,
        context: GuestContext,
        session_id: str,
        booking_flow: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use LLM to detect intent, extract entities, and determine conversation flow"""

        session = self._get_session(session_id)
        recent_messages = session.get("messages", [])[-6:]  # Last 3 exchanges

        # Build conversation history for context
        conv_history = ""
        for msg in recent_messages:
            role = "User" if msg["role"] == "user" else "Assistant"
            conv_history += f"{role}: {msg['content']}\n"

        # Build current state info
        current_state = ""
        if booking_flow.get("flow_started"):
            current_state = f"""
ACTIVE BOOKING FLOW:
- Check-in: {booking_flow.get('check_in_date', 'not set')}
- Check-out: {booking_flow.get('check_out_date', 'not set')}
- Room selected: {booking_flow.get('room_type_name', 'not set')}
- Guest name: {booking_flow.get('first_name', '')} {booking_flow.get('last_name', '')}
- Email: {booking_flow.get('email', 'not set')}
- OTP sent: {booking_flow.get('otp_sent', False)}
"""

        system_prompt = f"""You are the AI concierge for Glimmora Hotel & Suites. Analyze the user's message and respond with JSON.

GUEST CONTEXT:
- Name: {context.get('full_name', 'Guest')}
- Status: {context.get('status', 'anonymous')}
- Email: {context.get('email', 'unknown')}
- Current room: {context.get('current_room_number', 'N/A')}
- Loyalty tier: {context.get('loyalty_tier', 'Standard')}
- Loyalty points: {context.get('loyalty_points', 0)}
- Upcoming bookings: {context.get('upcoming_bookings', 0)}
{current_state}

RECENT CONVERSATION:
{conv_history if conv_history else "No previous messages"}

TODAY'S DATE: {date.today().strftime('%Y-%m-%d')}

AVAILABLE INTENTS:
- greeting: Hello, hi, welcome messages
- new_booking: User wants to book a room (includes providing dates, selecting rooms)
- view_bookings: User wants to see their bookings, asks about booking count/status
- modify_booking: User wants to change an existing booking
- cancel_booking: User wants to cancel a booking
- pre_checkin: User wants to do online check-in before arrival
- view_profile: User wants to see their profile
- edit_profile: User wants to update their profile
- loyalty_points: Questions about loyalty points/rewards
- booking_history: Past stays and booking history
- housekeeping: Room cleaning requests
- maintenance: Something broken/needs repair
- room_service: Food/beverage orders
- wifi_info: WiFi password/connection help
- hotel_info: Questions about hotel amenities, hours, facilities
- faq: General questions about the hotel
- staff_help: User wants to speak to a human
- checkout: Express checkout requests
- billing: Questions about charges/invoice
- continue_flow: User is providing info for an active flow (dates, room selection, etc.)
- general: Other/unclear intent

Respond with ONLY valid JSON (no markdown):
{{
  "intent": "the_intent",
  "confidence": 0.0-1.0,
  "is_topic_change": true/false,
  "extracted": {{
    "check_in_date": "YYYY-MM-DD or null",
    "check_out_date": "YYYY-MM-DD or null",
    "room_selection": "room number 1-8 or room name or null",
    "guest_count": {{"adults": N, "children": N}} or null,
    "confirmation_code": "GLM-XXXXX or null",
    "otp_code": "6 digits or null"
  }},
  "response": "Your natural response to the user"
}}

IMPORTANT:
- If user is clearly asking a NEW question (like "how many bookings do I have") while in a booking flow, set is_topic_change=true
- If user provides dates/info that continues the active booking flow, set intent=continue_flow
- Extract dates in YYYY-MM-DD format, interpreting relative dates based on today
- Be helpful and conversational in your response
- For booking queries, mention actual count if you can determine it
"""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"User message: {message}")
            ])

            # Parse JSON response
            response_text = response.content.strip()
            # Remove markdown code blocks if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            response_text = response_text.strip()

            result = json.loads(response_text)
            logger.info(f"LLM intent detection: {result.get('intent')} (conf: {result.get('confidence')}, topic_change: {result.get('is_topic_change')})")
            return result

        except Exception as e:
            logger.error(f"LLM intent detection failed: {e}")
            # Fallback to simple detection
            return {
                "intent": "general",
                "confidence": 0.5,
                "is_topic_change": False,
                "extracted": {},
                "response": None
            }

    def _detect_intent(self, message: str, context: GuestContext) -> Tuple[ConversationIntent, float]:
        """Legacy sync intent detection - kept for compatibility"""
        message_lower = message.lower().strip()

        # Quick pattern checks for common intents
        if re.match(r'^[a-z]{2,4}[-_][a-z0-9]{4,10}$', message_lower.replace(' ', '')):
            return ConversationIntent.VIEW_BOOKINGS, 0.95

        if any(g in message_lower for g in ["hello", "hi ", "hey", "good morning", "good afternoon", "good evening"]):
            return ConversationIntent.GREETING, 0.9

        if any(b in message_lower for b in ["book", "reservation", "reserve"]):
            return ConversationIntent.NEW_BOOKING, 0.8

        if any(v in message_lower for v in ["my booking", "how many booking", "booking history", "past booking"]):
            return ConversationIntent.VIEW_BOOKINGS, 0.85

        return ConversationIntent.GENERAL, 0.3

    # ==================== BOOKING OPERATIONS ====================

    async def _get_available_rooms(
        self,
        check_in: str,
        check_out: str,
        adults: int = 1,
        children: int = 0
    ) -> List[Dict[str, Any]]:
        """Get available room types with pricing"""
        try:
            logger.info(f"Getting available rooms: {check_in} to {check_out}, guests: {adults}+{children}")
            check_in_date = datetime.strptime(check_in, "%Y-%m-%d").date()
            check_out_date = datetime.strptime(check_out, "%Y-%m-%d").date()
            nights = (check_out_date - check_in_date).days
            logger.info(f"Parsed dates: {check_in_date} to {check_out_date}, nights={nights}")

            if nights <= 0:
                logger.warning(f"Invalid nights: {nights}")
                return []

            result = await self.db.exec(
                select(RoomType).where(RoomType.is_active == True)
            )
            room_types = result.all()
            logger.info(f"Found {len(room_types)} room types")

            available = []
            from app.core.tax import calculate_booking_taxes
            for rt in room_types:
                logger.info(f"  Room type {rt.name}: max_guests={rt.max_guests}, checking {adults}+{children}={adults+children}")
                if rt.max_guests >= adults + children:
                    per_night_rate = float(rt.base_price or 0)
                    tax_calc = calculate_booking_taxes(per_night_rate, nights)
                    base_price = tax_calc["calculated_base"]
                    taxes = tax_calc["taxes"]
                    service_fee = tax_calc["service_fee"]
                    total = tax_calc["total_price"]

                    available.append({
                        "id": rt.id,
                        "name": rt.name,
                        "description": rt.description,
                        "max_guests": rt.max_guests,
                        "bed_type": rt.bed_type,
                        "size_sqft": rt.size_sqft,
                        "base_price": base_price,
                        "taxes": round(taxes, 2),
                        "service_fee": round(service_fee, 2),
                        "total_price": round(total, 2),
                        "nights": nights,
                        "amenities": rt.amenities or [],
                    })

            return sorted(available, key=lambda x: x["total_price"])

        except Exception as e:
            logger.error(f"Error getting available rooms: {e}")
            return []

    async def _send_booking_otp(self, email: str, booking_flow: BookingFlowState) -> bool:
        """Send OTP for booking confirmation"""
        try:
            from app.services.email_service import get_email_service

            # Generate OTP
            otp_code = EmailOTP.generate_otp()

            # Create OTP record
            otp = EmailOTP(
                email=email.lower().strip(),
                otp_code=otp_code,
                purpose="booking_payment",
                expires_at=datetime.utcnow() + timedelta(minutes=10)
            )
            self.db.add(otp)
            await self.db.commit()

            # Send email (sync function - no await needed)
            email_service = get_email_service()
            email_service.send_otp_email(
                to_email=email,
                otp_code=otp_code,
                purpose="booking_payment"
            )

            logger.info(f"OTP sent to {email} for booking")
            return True

        except Exception as e:
            logger.error(f"Error sending OTP: {e}")
            return False

    async def _verify_otp(self, email: str, otp_code: str, purpose: str = "booking_payment") -> bool:
        """Verify OTP code"""
        try:
            result = await self.db.exec(
                select(EmailOTP).where(
                    and_(
                        EmailOTP.email == email.lower().strip(),
                        EmailOTP.otp_code == otp_code,
                        EmailOTP.purpose == purpose,
                        EmailOTP.verified == False,
                        EmailOTP.expires_at > datetime.utcnow()
                    )
                )
            )
            otp = result.first()

            if otp:
                otp.verified = True
                otp.verified_at = datetime.utcnow()
                await self.db.commit()
                return True

            return False

        except Exception as e:
            logger.error(f"Error verifying OTP: {e}")
            return False

    async def _create_booking(
        self,
        booking_flow: BookingFlowState,
        user_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Create actual booking in database"""
        try:
            from app.services.reservation_service import ReservationService

            # Find or create guest
            guest_email = booking_flow.get("email", "").lower().strip()
            result = await self.db.exec(
                select(Guest).where(Guest.email == guest_email)
            )
            guest = result.first()

            if not guest:
                guest = Guest(
                    first_name=booking_flow.get("first_name", ""),
                    last_name=booking_flow.get("last_name", ""),
                    email=guest_email,
                    phone=booking_flow.get("phone", ""),
                    country=booking_flow.get("country", ""),
                    status="Active",
                    loyalty_points=0,
                )
                self.db.add(guest)
                await self.db.flush()

            # Generate confirmation code and booking number
            import random
            import string
            conf_code = "GLM-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            booking_number = "BK" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

            # Calculate pricing
            check_in = datetime.strptime(booking_flow["check_in_date"], "%Y-%m-%d").date()
            check_out = datetime.strptime(booking_flow["check_out_date"], "%Y-%m-%d").date()
            nights = (check_out - check_in).days

            # Get room type price with GST slab-based tax
            from app.core.tax import calculate_booking_taxes
            result = await self.db.exec(
                select(RoomType).where(RoomType.id == booking_flow["room_type_id"])
            )
            room_type = result.first()
            per_night_rate = float(room_type.base_price or 185)
            tax_calc = calculate_booking_taxes(per_night_rate, nights)
            base_price = tax_calc["calculated_base"]
            taxes = tax_calc["taxes"]
            service_fee = tax_calc["service_fee"]
            total = round(tax_calc["total_price"], 2)

            # Calculate total guests
            adults_count = booking_flow.get("adults", 1)
            children_count = booking_flow.get("children", 0)
            total_guests = adults_count + children_count

            # Create booking with all required fields from new schema
            booking = Booking(
                booking_number=booking_number,
                confirmation_code=conf_code,
                user_id=user_id,
                guest_id=guest.id,
                room_type_id=booking_flow["room_type_id"],
                room_id=None,  # Room assigned at check-in/pre-checkin
                arrival_date=check_in,
                departure_date=check_out,
                adults=adults_count,
                children=children_count,
                infants=0,
                nights=nights,
                status="confirmed",
                payment_status="pending",
                booking_source="agi_chatbot",
                base_price=base_price,
                taxes=taxes,
                service_fee=service_fee,
                total_price=total,
                special_requests=booking_flow.get("special_requests"),
                # New fields from schema update
                vip_flag=guest.vip_status if guest.vip_status else False,
                number_of_guests=total_guests,
                upsells=None,
                discount_code=None,
                discount_amount=0.0,
                commission_rate=None,
                commission_amount=None,
                net_revenue=total,  # No commission for direct chatbot booking
                modification_count=0
            )
            self.db.add(booking)

            # Update guest stats when booking is created
            guest.total_bookings = (guest.total_bookings or 0) + 1
            guest.total_spent = (guest.total_spent or 0) + total
            guest.total_nights = (guest.total_nights or 0) + nights
            # Loyalty points: 10% of total spent
            guest.loyalty_points = int((guest.total_spent or 0) * 0.1)

            await self.db.commit()
            await self.db.refresh(booking)

            # Send confirmation email
            try:
                from app.services.email_service import get_email_service
                email_service = get_email_service()
                await email_service.send_booking_confirmation_email(
                    to_email=guest_email,
                    guest_name=f"{booking_flow.get('first_name', '')} {booking_flow.get('last_name', '')}",
                    booking_details={
                        "confirmation_code": conf_code,
                        "room_type": ROOM_TYPES.get(booking_flow["room_type_id"], "Unknown"),
                        "check_in_date": str(check_in),
                        "check_out_date": str(check_out),
                        "nights": nights,
                        "adults": booking_flow.get("adults", 1),
                        "children": booking_flow.get("children", 0),
                        "total_price": f"${total:.2f}",
                    }
                )
            except Exception as e:
                logger.error(f"Failed to send confirmation email: {e}")

            return {
                "booking_id": booking.id,
                "confirmation_code": conf_code,
                "room_type": ROOM_TYPES.get(booking_flow["room_type_id"], "Unknown"),
                "check_in_date": str(check_in),
                "check_out_date": str(check_out),
                "nights": nights,
                "total_price": round(total, 2),
                "guest_name": f"{booking_flow.get('first_name', '')} {booking_flow.get('last_name', '')}",
                "email": guest_email,
            }

        except Exception as e:
            logger.error(f"Error creating booking: {e}")
            await self.db.rollback()
            return None

    # ==================== GUEST OPERATIONS ====================

    async def _get_guest_bookings(
        self,
        guest_id: Optional[int] = None,
        user_id: Optional[int] = None,
        status_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get guest's bookings"""
        try:
            query = select(Booking)

            conditions = []
            if guest_id:
                conditions.append(Booking.guest_id == guest_id)
            if user_id:
                conditions.append(Booking.user_id == user_id)

            if conditions:
                query = query.where(or_(*conditions))

            if status_filter:
                query = query.where(Booking.status.in_(status_filter))

            query = query.order_by(desc(Booking.arrival_date))

            result = await self.db.exec(query)
            bookings = result.all()

            return [
                {
                    "id": b.id,
                    "confirmation_code": b.confirmation_code,
                    "room_type": ROOM_TYPES.get(b.room_type_id, "Unknown"),
                    "check_in": str(b.arrival_date),
                    "check_out": str(b.departure_date),
                    "nights": b.nights,
                    "status": b.status,
                    "total_price": float(b.total_price or 0),
                    "adults": b.adults,
                    "children": b.children,
                }
                for b in bookings
            ]

        except Exception as e:
            logger.error(f"Error getting bookings: {e}")
            return []

    async def _lookup_booking_by_code(self, confirmation_code: str) -> Optional[Dict[str, Any]]:
        """Look up a booking by confirmation code"""
        try:
            # Normalize the code
            code = confirmation_code.upper().strip()

            # Try both with and without prefix
            result = await self.db.exec(
                select(Booking).where(
                    or_(
                        Booking.confirmation_code == code,
                        Booking.confirmation_code.ilike(f"%{code}%"),
                        Booking.booking_number == code,
                        Booking.booking_number.ilike(f"%{code}%")
                    )
                )
            )
            booking = result.first()

            if booking:
                # Get room type name
                room_type_name = ROOM_TYPES.get(booking.room_type_id, "Unknown")
                if not room_type_name or room_type_name == "Unknown":
                    rt_result = await self.db.exec(
                        select(RoomType).where(RoomType.id == booking.room_type_id)
                    )
                    rt = rt_result.first()
                    if rt:
                        room_type_name = rt.name

                nights = (booking.departure_date - booking.arrival_date).days if booking.arrival_date and booking.departure_date else 0

                return {
                    "id": booking.id,
                    "booking_id": booking.id,
                    "confirmation_code": booking.confirmation_code or booking.booking_number,
                    "room_type": room_type_name,
                    "room_type_id": booking.room_type_id,
                    "check_in": str(booking.arrival_date),
                    "check_out": str(booking.departure_date),
                    "nights": nights,
                    "status": booking.status,
                    "total_price": float(booking.total_price or 0),
                    "adults": booking.adults or 1,
                    "children": booking.children or 0,
                    "guest_id": booking.guest_id,
                    "room_id": booking.room_id,
                    "special_requests": booking.special_requests,
                }

            # Also check Reservation table (legacy)
            from app.models.reservations import Reservation
            res_result = await self.db.exec(
                select(Reservation).where(
                    or_(
                        Reservation.confirmation_code == code,
                        Reservation.confirmation_code.ilike(f"%{code}%")
                    )
                )
            )
            reservation = res_result.first()

            if reservation:
                room_type_name = ROOM_TYPES.get(reservation.room_type_id, "Unknown")
                nights = (reservation.departure_date - reservation.arrival_date).days if reservation.arrival_date and reservation.departure_date else 0

                return {
                    "id": reservation.id,
                    "booking_id": reservation.id,
                    "confirmation_code": reservation.confirmation_code,
                    "room_type": room_type_name,
                    "room_type_id": reservation.room_type_id,
                    "check_in": str(reservation.arrival_date),
                    "check_out": str(reservation.departure_date),
                    "nights": nights,
                    "status": reservation.status,
                    "total_price": float(reservation.total_amount or 0),
                    "adults": reservation.adults or 1,
                    "children": reservation.children or 0,
                    "guest_id": reservation.guest_id,
                    "room_number": None,
                    "special_requests": reservation.special_requests,
                }

            return None

        except Exception as e:
            logger.error(f"Error looking up booking by code: {e}")
            return None

    async def _cancel_booking(
        self,
        booking_id: int,
        reason: str = "Guest requested cancellation"
    ) -> bool:
        """Cancel a booking"""
        try:
            result = await self.db.exec(
                select(Booking).where(Booking.id == booking_id)
            )
            booking = result.first()

            if booking and booking.status in ["pending", "confirmed"]:
                booking.status = "cancelled"
                booking.cancellation_reason = reason
                booking.cancelled_at = datetime.utcnow()
                await self.db.commit()
                return True

            return False

        except Exception as e:
            logger.error(f"Error cancelling booking: {e}")
            return False

    async def _get_loyalty_info(self, guest_id: int) -> Dict[str, Any]:
        """Get loyalty information for guest"""
        try:
            result = await self.db.exec(
                select(Guest).where(Guest.id == guest_id)
            )
            guest = result.first()

            if guest:
                return {
                    "points": guest.loyalty_points or 0,
                    "tier": guest.loyalty_tier or "member",
                    "total_spent": float(guest.total_spent or 0),
                    "total_nights": guest.total_nights or 0,
                    "total_bookings": guest.total_bookings or 0,
                    "is_vip": guest.vip_status or False,
                }

            return {"points": 0, "tier": "member"}

        except Exception as e:
            logger.error(f"Error getting loyalty info: {e}")
            return {"points": 0, "tier": "member"}

    async def _extract_profile_update(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and apply profile updates from user message using LLM"""
        try:
            guest_id = context.get("guest_id")
            if not guest_id:
                return {"updated": False, "message": "Please log in to update your profile."}

            # Use LLM to extract profile updates
            system_prompt = f"""You are a profile update extractor. Analyze the user's message and extract any profile information they want to update.

Current profile:
- Name: {context.get('full_name', 'Not set')}
- Phone: {context.get('phone', 'Not set')}
- Email: {context.get('email', 'Not set')}

Respond with ONLY valid JSON (no markdown):
{{
  "has_update": true/false,
  "updates": {{
    "first_name": "value or null",
    "last_name": "value or null",
    "phone": "value or null",
    "address": "value or null",
    "city": "value or null",
    "state": "value or null",
    "postal_code": "value or null",
    "country": "value or null"
  }},
  "confirmation_message": "Summary of what will be updated"
}}

Only include fields that the user explicitly wants to change.
For phone, extract just the number.
For address, try to parse city/state/postal_code if provided.
"""

            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"User message: {message}")
            ])

            response_text = response.content.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            response_text = response_text.strip()

            result = json.loads(response_text)

            if not result.get("has_update"):
                return {"updated": False, "message": ""}

            updates = result.get("updates", {})
            # Filter out null values
            updates = {k: v for k, v in updates.items() if v is not None}

            if not updates:
                return {"updated": False, "message": ""}

            # Apply updates to guest record
            guest_result = await self.db.exec(select(Guest).where(Guest.id == guest_id))
            guest = guest_result.first()

            if not guest:
                return {"updated": False, "message": "Could not find your profile."}

            # Apply each update
            changed = []
            for field, value in updates.items():
                if hasattr(guest, field) and value:
                    old_value = getattr(guest, field, None)
                    setattr(guest, field, value)
                    changed.append(f"**{field.replace('_', ' ').title()}**: {old_value or 'Not set'} → {value}")

            if changed:
                self.db.add(guest)
                await self.db.commit()
                await self.db.refresh(guest)

                return {
                    "updated": True,
                    "message": f"""✅ Profile updated successfully!

Changes made:
{chr(10).join(changed)}

Is there anything else you'd like to update?"""
                }

            return {"updated": False, "message": "No changes were made."}

        except json.JSONDecodeError as e:
            logger.error(f"Error parsing LLM response for profile update: {e}")
            return {"updated": False, "message": "I couldn't understand the update. Please try again with a clearer format like 'Update my phone to 555-123-4567'."}
        except Exception as e:
            logger.error(f"Error updating profile: {e}")
            return {"updated": False, "message": f"Sorry, I couldn't update your profile: {str(e)}"}

    # ==================== IN-HOUSE SERVICES ====================

    async def _create_service_request(
        self,
        request_type: str,
        room_number: str,
        description: str,
        priority: str = "normal"
    ) -> Optional[int]:
        """Create a service request (housekeeping/maintenance/room service)"""
        try:
            task = StaffTask(
                task_type=request_type,
                room_number=room_number,
                title=f"{request_type.title()} Request - Room {room_number}",
                description=description,
                priority=priority,
                status="pending",
            )
            self.db.add(task)
            await self.db.commit()
            await self.db.refresh(task)

            return task.id

        except Exception as e:
            logger.error(f"Error creating service request: {e}")
            return None

    # ==================== RESPONSE GENERATION ====================

    def _build_system_prompt(self, context: GuestContext, booking_flow: BookingFlowState) -> str:
        """Build dynamic system prompt"""
        today = datetime.now().strftime("%Y-%m-%d")

        # Guest status info
        status_info = f"Guest Status: {context['status']}"
        if context["full_name"]:
            status_info += f"\nName: {context['full_name']}"
        if context["loyalty_points"]:
            status_info += f"\nLoyalty: {context['loyalty_points']} points ({context['loyalty_tier'] or 'member'})"
        if context["current_room_number"]:
            status_info += f"\nCurrently in Room: {context['current_room_number']}"

        # Booking flow state
        booking_info = "No active booking in progress"
        if booking_flow:
            parts = []
            if booking_flow.get("room_type_id"):
                parts.append(f"✓ Room: {ROOM_TYPES.get(booking_flow['room_type_id'], 'Unknown')}")
            if booking_flow.get("check_in_date"):
                parts.append(f"✓ Check-in: {booking_flow['check_in_date']}")
            if booking_flow.get("check_out_date"):
                parts.append(f"✓ Check-out: {booking_flow['check_out_date']}")
            if booking_flow.get("first_name"):
                parts.append(f"✓ Name: {booking_flow.get('first_name')} {booking_flow.get('last_name', '')}")
            if booking_flow.get("email"):
                parts.append(f"✓ Email: {booking_flow['email']}")
            if booking_flow.get("phone"):
                parts.append(f"✓ Phone: {booking_flow['phone']}")
            if booking_flow.get("otp_sent"):
                parts.append("⏳ OTP sent, awaiting verification")
            if booking_flow.get("otp_verified"):
                parts.append("✓ OTP verified")
            if parts:
                booking_info = "\n".join(parts)

        prompt = f"""You are Aria, the AI concierge for Glimmora Hotel & Suites.

TODAY: {today}

=== GUEST CONTEXT ===
{status_info}

=== BOOKING FLOW STATE ===
{booking_info}

=== CAPABILITIES ===
Based on the guest's status, you can help with:

{"- Make new room reservations (with OTP verification)" if context['status'] in ['anonymous', 'registered'] else ""}
{"- View and manage current booking" if context['status'] in ['booked', 'checked_in'] else ""}
{"- Complete pre-check-in" if context['status'] == 'booked' else ""}
{"- Request housekeeping, maintenance, room service" if context['status'] == 'checked_in' else ""}
{"- Get WiFi password and hotel information" if context['status'] == 'checked_in' else ""}
{"- View loyalty points and rewards" if context['guest_id'] else ""}
{"- View booking history" if context['past_bookings'] else ""}
- Answer general questions about the hotel
- Provide hotel information and FAQs

=== CRITICAL RULES ===

1. **AUTHENTICATION**:
   - For profile changes, booking modifications, or viewing personal data: User MUST be logged in
   - If not logged in, politely ask them to log in first

2. **BOOKING FLOW**:
   - Collect: room type → dates → guest count → name → email → phone → country
   - After collecting email, SEND OTP for verification
   - After OTP verified, CREATE the booking and SEND confirmation email
   - NEVER skip OTP verification for new bookings

3. **NUMBER SELECTIONS**:
   - If rooms were shown and user says "2", they selected option 2 (Coastal Retreat)
   - If user provides OTP like "123456", verify it

4. **CHECKED-IN GUESTS**:
   - Can request housekeeping, maintenance, room service
   - WiFi: Network "{HOTEL_INFO['wifi_network']}", Password: "{HOTEL_INFO['wifi_password']}"

5. **BE HELPFUL AND CONCISE**:
   - One question at a time
   - Acknowledge what they provided
   - Don't repeat information already shown"""

        return prompt

    def _generate_quick_actions(self, intent: ConversationIntent, context: GuestContext) -> List[Dict[str, str]]:
        """Generate context-appropriate quick actions"""
        actions = []

        if context["status"] == GuestStatus.CHECKED_IN.value:
            actions = [
                {"label": "Housekeeping", "action": "I need housekeeping"},
                {"label": "Room Service", "action": "Show me the menu"},
                {"label": "WiFi Info", "action": "What's the WiFi password?"},
            ]
        elif context["status"] == GuestStatus.BOOKED.value:
            actions = [
                {"label": "Pre-Checkin", "action": "I want to do pre-check-in"},
                {"label": "View Booking", "action": "Show my booking"},
                {"label": "Modify Booking", "action": "I want to modify my booking"},
            ]
        else:
            actions = [
                {"label": "Book Room", "action": "I want to book a room"},
                {"label": "Hotel Info", "action": "Tell me about the hotel"},
                {"label": "Contact Us", "action": "How can I contact you?"},
            ]

        return actions

    # ==================== MAIN PROCESSING ====================

    async def process_message(
        self,
        message: str,
        session_id: str,
        user_id: Optional[int] = None,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        room_number: Optional[str] = None,
        voice_input: bool = False,
        email: Optional[str] = None,
    ) -> AGIResponse:
        """Main message processing method - LLM-powered

        Args:
            message: The user's message
            session_id: Unique session identifier
            user_id: ID of logged in user (if any)
            guest_id: ID of guest record (if any)
            booking_id: ID of current booking (if any)
            room_number: Current room number (if checked in)
            voice_input: Whether this was from voice
            email: User's email (if known)
        """
        try:
            # Load guest context
            context = await self._load_guest_context(
                user_id=user_id,
                guest_id=guest_id,
                booking_id=booking_id,
                room_number=room_number,
                email=email
            )

            # Get session data
            session = self._get_session(session_id)
            booking_flow = self._get_booking_flow(session_id)

            # Save user message
            self._save_message(session_id, "user", message)

            # Use LLM for intent detection and entity extraction
            llm_result = await self._detect_intent_with_llm(message, context, session_id, booking_flow)

            intent_str = llm_result.get("intent", "general")
            confidence = llm_result.get("confidence", 0.5)
            is_topic_change = llm_result.get("is_topic_change", False)
            extracted = llm_result.get("extracted", {})
            llm_response = llm_result.get("response")

            logger.info(f"LLM result - Intent: {intent_str}, Confidence: {confidence}, Topic change: {is_topic_change}")

            # If topic change detected, clear booking flow
            if is_topic_change and booking_flow.get("flow_started"):
                logger.info("Topic change detected - clearing booking flow")
                self._clear_booking_flow(session_id)
                booking_flow = {}

            # Map string intent to enum
            intent_map = {
                "greeting": ConversationIntent.GREETING,
                "new_booking": ConversationIntent.NEW_BOOKING,
                "continue_flow": ConversationIntent.NEW_BOOKING,
                "view_bookings": ConversationIntent.VIEW_BOOKINGS,
                "modify_booking": ConversationIntent.MODIFY_BOOKING,
                "cancel_booking": ConversationIntent.CANCEL_BOOKING,
                "pre_checkin": ConversationIntent.PRE_CHECKIN,
                "view_profile": ConversationIntent.VIEW_PROFILE,
                "edit_profile": ConversationIntent.EDIT_PROFILE,
                "loyalty_points": ConversationIntent.LOYALTY_POINTS,
                "booking_history": ConversationIntent.BOOKING_HISTORY,
                "housekeeping": ConversationIntent.HOUSEKEEPING,
                "maintenance": ConversationIntent.MAINTENANCE,
                "room_service": ConversationIntent.ROOM_SERVICE,
                "wifi_info": ConversationIntent.WIFI_INFO,
                "hotel_info": ConversationIntent.HOTEL_INFO,
                "faq": ConversationIntent.FAQ,
                "staff_help": ConversationIntent.STAFF_HELP,
                "checkout": ConversationIntent.CHECKOUT,
                "billing": ConversationIntent.BILLING,
            }
            intent = intent_map.get(intent_str, ConversationIntent.GENERAL)

            # Check for OTP in message (for booking confirmation)
            otp = extracted.get("otp_code") or extract_otp(message)
            if otp and booking_flow.get("otp_sent") and not booking_flow.get("otp_verified"):
                email_for_otp = booking_flow.get("email") or context.get("email")
                if email_for_otp:
                    verified = await self._verify_otp(email_for_otp, otp)
                    if verified:
                        self._update_booking_flow(session_id, {"otp_verified": True})
                        booking_flow["otp_verified"] = True

                        booking_result = await self._create_booking(booking_flow, user_id)
                        if booking_result:
                            self._clear_booking_flow(session_id)
                            response_text = f"""🎉 **Booking Confirmed!**

Your reservation is complete. Here are your details:

**Confirmation Code:** {booking_result['confirmation_code']}
**Room:** {booking_result['room_type']}
**Check-in:** {booking_result['check_in_date']}
**Check-out:** {booking_result['check_out_date']}
**Nights:** {booking_result['nights']}
**Total:** ${booking_result['total_price']:.2f}

A confirmation email has been sent to {booking_result['email']}.

Would you like to complete your pre-check-in now?"""

                            self._save_message(session_id, "assistant", response_text)
                            return AGIResponse(
                                message=response_text,
                                intent=intent.value,
                                confidence=1.0,
                                action_taken=True,
                                action_result=booking_result,
                                booking_created=booking_result.get("booking_id"),
                                quick_actions=[
                                    {"label": "Pre-Checkin", "action": "Yes, I want to do pre-check-in"},
                                    {"label": "Done", "action": "No thanks, I'm all set"},
                                ]
                            )
                        else:
                            return AGIResponse(
                                message="I'm sorry, there was an issue creating your booking. Please try again.",
                                intent="error",
                                confidence=0.0
                            )
                    else:
                        return AGIResponse(
                            message="The OTP code is incorrect or expired. Please try again.",
                            intent=intent.value,
                            confidence=0.8,
                            requires_otp=True,
                            otp_email=booking_flow.get("email"),
                        )

            # Apply LLM-extracted entities to booking flow
            if intent == ConversationIntent.NEW_BOOKING or (intent_str == "continue_flow" and booking_flow):
                if extracted.get("check_in_date"):
                    self._update_booking_flow(session_id, {"check_in_date": extracted["check_in_date"]})
                    booking_flow["check_in_date"] = extracted["check_in_date"]
                if extracted.get("check_out_date"):
                    self._update_booking_flow(session_id, {"check_out_date": extracted["check_out_date"]})
                    booking_flow["check_out_date"] = extracted["check_out_date"]
                if extracted.get("guest_count"):
                    gc = extracted["guest_count"]
                    if gc.get("adults"):
                        self._update_booking_flow(session_id, {"adults": gc["adults"], "children": gc.get("children", 0)})
                        booking_flow["adults"] = gc["adults"]
                        booking_flow["children"] = gc.get("children", 0)

                # Also try regex extraction as backup
                check_in, check_out = extract_dates(message)
                if check_in and not booking_flow.get("check_in_date"):
                    self._update_booking_flow(session_id, {"check_in_date": check_in})
                    booking_flow["check_in_date"] = check_in
                if check_out and not booking_flow.get("check_out_date"):
                    self._update_booking_flow(session_id, {"check_out_date": check_out})
                    booking_flow["check_out_date"] = check_out

                # Extract room selection
                room_id = extract_room_selection(message, booking_flow.get("rooms_shown", False))
                if room_id:
                    # Get the price from stored room prices
                    room_prices = booking_flow.get("room_prices", {})
                    total_price = room_prices.get(room_id, 0)

                    self._update_booking_flow(session_id, {
                        "room_type_id": room_id,
                        "room_type_name": ROOM_TYPES.get(room_id),
                        "total_price": total_price
                    })
                    booking_flow["room_type_id"] = room_id
                    booking_flow["room_type_name"] = ROOM_TYPES.get(room_id)
                    booking_flow["total_price"] = total_price

                # Extract guest info
                guest_info = extract_guest_info(message)
                if guest_info:
                    self._update_booking_flow(session_id, guest_info)
                    booking_flow.update(guest_info)

            # For simple intents, use LLM response directly if appropriate
            if intent in [ConversationIntent.GREETING, ConversationIntent.HOTEL_INFO,
                          ConversationIntent.FAQ, ConversationIntent.WIFI_INFO] and llm_response:
                self._save_message(session_id, "assistant", llm_response)
                return AGIResponse(
                    message=llm_response,
                    intent=intent.value,
                    confidence=confidence,
                    quick_actions=self._generate_quick_actions(intent, context),
                    guest_context=context,
                )

            # Process based on intent and state
            response = await self._process_intent(
                intent=intent,
                message=message,
                context=context,
                booking_flow=booking_flow,
                session_id=session_id,
                user_id=user_id
            )

            # Save assistant response
            self._save_message(session_id, "assistant", response.message)

            return response

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return AGIResponse(
                message="I apologize, but I encountered an issue. Please try again or contact our front desk at +1 (310) 555-0123.",
                intent="error",
                confidence=0.0
            )

    async def _process_intent(
        self,
        intent: ConversationIntent,
        message: str,
        context: GuestContext,
        booking_flow: BookingFlowState,
        session_id: str,
        user_id: Optional[int]
    ) -> AGIResponse:
        """Process specific intent"""

        # ====== GREETING ======
        if intent == ConversationIntent.GREETING:
            if context["full_name"]:
                greeting = f"Hello, {context['full_name']}! Welcome back to Glimmora Hotel & Suites."
            else:
                greeting = "Hello! Welcome to Glimmora Hotel & Suites."

            if context["status"] == GuestStatus.CHECKED_IN.value:
                greeting += f" I see you're currently staying in Room {context['current_room_number']}. How can I help you today?"
            elif context["status"] == GuestStatus.BOOKED.value:
                greeting += f" You have {context['upcoming_bookings']} upcoming booking(s). How can I assist you?"
            else:
                greeting += " How may I assist you today?"

            return AGIResponse(
                message=greeting,
                intent=intent.value,
                confidence=0.95,
                quick_actions=self._generate_quick_actions(intent, context),
                guest_context=context,
                guest_status=context.get("status"),
                loyalty_points=context.get("loyalty_points"),
                loyalty_tier=context.get("loyalty_tier"),
            )

        # ====== NEW BOOKING ======
        # Only enter booking flow if intent is NEW_BOOKING (LLM handles topic switching)
        if intent == ConversationIntent.NEW_BOOKING:
            return await self._handle_booking_flow(
                message=message,
                context=context,
                booking_flow=booking_flow,
                session_id=session_id,
                user_id=user_id
            )

        # ====== VIEW BOOKINGS ======
        if intent == ConversationIntent.VIEW_BOOKINGS:
            # First check if message contains a confirmation code
            confirmation_code = extract_confirmation_code(message)

            if confirmation_code:
                # Look up booking by confirmation code
                booking = await self._lookup_booking_by_code(confirmation_code)
                if booking:
                    response_text = f"""**Booking Found!**

**Confirmation Code:** {booking['confirmation_code']}
**Room Type:** {booking['room_type']}
**Check-in:** {booking['check_in']}
**Check-out:** {booking['check_out']}
**Nights:** {booking['nights']}
**Guests:** {booking['adults']} adults{f", {booking['children']} children" if booking.get('children') else ""}
**Status:** {booking['status'].title()}
**Total:** ${booking['total_price']:.2f}

What would you like to do with this booking?"""

                    return AGIResponse(
                        message=response_text,
                        intent=intent.value,
                        confidence=0.95,
                        action_result=booking,
                        quick_actions=[
                            {"label": "Pre-Checkin", "action": "Do pre-check-in for this booking"},
                            {"label": "Modify", "action": "I want to modify this booking"},
                            {"label": "Cancel", "action": "I want to cancel this booking"},
                        ]
                    )
                else:
                    return AGIResponse(
                        message=f"I couldn't find a booking with confirmation code **{confirmation_code}**. Please check the code and try again, or contact our front desk for assistance.",
                        intent=intent.value,
                        confidence=0.8,
                        quick_actions=[
                            {"label": "Book Now", "action": "I want to book a room"},
                            {"label": "Contact Us", "action": "I need to speak to front desk"},
                        ]
                    )

            # No confirmation code provided - need to be logged in
            if not user_id and not context.get("guest_id"):
                return AGIResponse(
                    message="To view your bookings, please provide your confirmation code (e.g., GLM-ABC123) or log in to your account.",
                    intent=intent.value,
                    confidence=0.9,
                    show_login_prompt=True
                )

            bookings = await self._get_guest_bookings(
                guest_id=context.get("guest_id"),
                user_id=user_id,
                status_filter=["pending", "confirmed", "booked", "checked_in"]
            )

            if not bookings:
                return AGIResponse(
                    message="You don't have any active bookings at the moment. Would you like to make a new reservation?",
                    intent=intent.value,
                    confidence=0.9,
                    quick_actions=[{"label": "Book Now", "action": "I want to book a room"}]
                )

            response_text = f"You have {len(bookings)} booking(s):\n\n"
            for i, b in enumerate(bookings[:5], 1):
                response_text += f"**{i}. {b['room_type']}**\n"
                response_text += f"   📅 {b['check_in']} → {b['check_out']} ({b['nights']} nights)\n"
                response_text += f"   🔖 {b['confirmation_code']} | Status: {b['status'].title()}\n"
                response_text += f"   💰 ${b['total_price']:.2f}\n\n"

            return AGIResponse(
                message=response_text,
                intent=intent.value,
                confidence=0.95,
                quick_actions=[
                    {"label": "Pre-Checkin", "action": "I want to do pre-check-in"},
                    {"label": "Modify Booking", "action": "I want to modify my booking"},
                ]
            )

        # ====== CANCEL BOOKING ======
        if intent == ConversationIntent.CANCEL_BOOKING:
            if not user_id:
                return AGIResponse(
                    message="To cancel a booking, please log in to your account first.",
                    intent=intent.value,
                    confidence=0.9,
                    requires_auth=True,
                    show_login_prompt=True
                )

            return AGIResponse(
                message="I can help you cancel your booking. Please note that cancellation policies may apply depending on how close we are to your check-in date.\n\nPlease provide your confirmation code (e.g., GLM-XXXXXX) or tell me which booking you'd like to cancel.",
                intent=intent.value,
                confidence=0.9
            )

        # ====== PRE-CHECKIN ======
        if intent == ConversationIntent.PRE_CHECKIN:
            # First check if message contains a confirmation code
            confirmation_code = extract_confirmation_code(message)
            if confirmation_code:
                booking = await self._lookup_booking_by_code(confirmation_code)
                if booking and booking.get("status") in ["booked", "confirmed", "pending"]:
                    return AGIResponse(
                        message=f"""Great! Let's complete your pre-check-in.

**Booking Found:**
• **Confirmation:** {booking['confirmation_code']}
• **Room Type:** {booking['room_type']}
• **Check-in:** {booking['check_in']}
• **Check-out:** {booking['check_out']}

Pre-check-in allows you to:
✓ Choose your preferred room
✓ Upload your ID
✓ Set your room preferences
✓ Get a digital key

Would you like to start the pre-check-in process?""",
                        intent=intent.value,
                        confidence=0.95,
                        action_result=booking,
                        quick_actions=[
                            {"label": "Start Pre-Checkin", "action": "Yes, start pre-check-in"},
                            {"label": "Not Now", "action": "I'll do it later"},
                        ]
                    )
                elif booking:
                    return AGIResponse(
                        message=f"The booking **{confirmation_code}** has status '{booking.get('status')}' and is not eligible for pre-check-in at this time.",
                        intent=intent.value,
                        confidence=0.8
                    )
                else:
                    return AGIResponse(
                        message=f"I couldn't find a booking with confirmation code **{confirmation_code}**. Please check the code and try again.",
                        intent=intent.value,
                        confidence=0.8
                    )

            if not context.get("guest_id") and not user_id:
                return AGIResponse(
                    message="To complete pre-check-in, please log in or provide your booking confirmation code (e.g., GLM-ABC123).",
                    intent=intent.value,
                    confidence=0.9,
                    show_login_prompt=True
                )

            bookings = await self._get_guest_bookings(
                guest_id=context.get("guest_id"),
                user_id=user_id,
                status_filter=["confirmed", "booked", "pending"]
            )

            if not bookings:
                return AGIResponse(
                    message="You don't have any upcoming confirmed bookings for pre-check-in. If you have a confirmation code, please provide it.",
                    intent=intent.value,
                    confidence=0.8
                )

            return AGIResponse(
                message=f"""Great! Let's complete your pre-check-in for your stay.

You have a booking for **{bookings[0]['room_type']}** from {bookings[0]['check_in']} to {bookings[0]['check_out']}.

Pre-check-in allows you to:
✓ Choose your preferred room
✓ Upload your ID
✓ Set your room preferences
✓ Get a digital key

Would you like to start the pre-check-in process?""",
                intent=intent.value,
                confidence=0.95,
                quick_actions=[
                    {"label": "Start Pre-Checkin", "action": "Yes, start pre-check-in"},
                    {"label": "Not Now", "action": "I'll do it later"},
                ]
            )

        # ====== VIEW PROFILE ======
        if intent == ConversationIntent.VIEW_PROFILE:
            if not user_id:
                return AGIResponse(
                    message="To view your profile, please log in to your account.",
                    intent=intent.value,
                    confidence=0.9,
                    requires_auth=True,
                    show_login_prompt=True
                )

            return AGIResponse(
                message=f"""Here's your profile information:

**Name:** {context.get('full_name', 'Not set')}
**Email:** {context.get('email', 'Not set')}
**Phone:** {context.get('phone', 'Not set')}

**Loyalty Status:**
🏆 Tier: {(context.get('loyalty_tier') or 'Member').title()}
💎 Points: {context.get('loyalty_points', 0):,}
{"⭐ VIP Member" if context.get('is_vip') else ""}

Would you like to update any of this information?""",
                intent=intent.value,
                confidence=0.95,
                quick_actions=[
                    {"label": "Edit Profile", "action": "I want to update my profile"},
                    {"label": "View Points", "action": "Tell me about my loyalty points"},
                ]
            )

        # ====== EDIT PROFILE ======
        if intent == ConversationIntent.EDIT_PROFILE:
            if not context.get("guest_id"):
                return AGIResponse(
                    message="To update your profile, please log in to your account.",
                    intent=intent.value,
                    confidence=0.9,
                    requires_auth=True,
                    show_login_prompt=True
                )

            # Extract profile update info from message using LLM
            update_result = await self._extract_profile_update(message, context)

            if update_result.get("needs_confirmation"):
                return AGIResponse(
                    message=update_result["message"],
                    intent=intent.value,
                    confidence=0.95,
                    quick_actions=[
                        {"label": "Yes, Update", "action": "Yes, please update my profile"},
                        {"label": "Cancel", "action": "Cancel the update"},
                    ]
                )

            if update_result.get("updated"):
                return AGIResponse(
                    message=update_result["message"],
                    intent=intent.value,
                    confidence=0.95,
                    action_taken=True
                )

            # No specific update detected - show options
            return AGIResponse(
                message=f"""What would you like to update?

You can update:
- **Phone number**: "Update my phone to 555-123-4567"
- **Address**: "Change my address to 123 Main St, City, State 12345"
- **Name**: "Update my name to John Doe"

Your current info:
- Name: {context.get('full_name', 'Not set')}
- Phone: {context.get('phone', 'Not set')}

Just tell me what you'd like to change!""",
                intent=intent.value,
                confidence=0.95
            )

        # ====== LOYALTY POINTS ======
        if intent == ConversationIntent.LOYALTY_POINTS:
            if not context.get("guest_id"):
                return AGIResponse(
                    message="To view your loyalty points, please log in to your account.",
                    intent=intent.value,
                    confidence=0.9,
                    requires_auth=True,
                    show_login_prompt=True
                )

            loyalty = await self._get_loyalty_info(context["guest_id"])

            tier_benefits = {
                "member": "5% discount on dining",
                "bronze": "10% discount on dining, early check-in when available",
                "silver": "15% discount on dining, free room upgrade when available",
                "gold": "20% discount on dining, guaranteed room upgrade, late checkout",
                "platinum": "25% discount on dining, suite upgrade, complimentary spa access",
            }

            tier = loyalty.get("tier", "member").lower()
            benefits = tier_benefits.get(tier, "Basic member benefits")

            return AGIResponse(
                message=f"""**Your Glimmora Rewards**

💎 **Current Points:** {loyalty['points']:,}
🏆 **Tier:** {tier.title()}
{"⭐ **VIP Status:** Active" if loyalty.get('is_vip') else ""}

**Your Benefits:**
{benefits}

**Lifetime Stats:**
📊 Total Stays: {loyalty.get('total_bookings', 0)}
🌙 Total Nights: {loyalty.get('total_nights', 0)}
💰 Total Spent: ${loyalty.get('total_spent', 0):,.2f}

Points can be redeemed for free nights, spa treatments, dining credits, and more!""",
                intent=intent.value,
                confidence=0.95
            )

        # ====== BOOKING HISTORY ======
        if intent == ConversationIntent.BOOKING_HISTORY:
            if not user_id and not context.get("guest_id"):
                return AGIResponse(
                    message="To view your booking history, please log in to your account.",
                    intent=intent.value,
                    confidence=0.9,
                    requires_auth=True,
                    show_login_prompt=True
                )

            bookings = await self._get_guest_bookings(
                guest_id=context.get("guest_id"),
                user_id=user_id,
                status_filter=["checked_out"]
            )

            if not bookings:
                return AGIResponse(
                    message="You don't have any past stays with us yet. We look forward to hosting you!",
                    intent=intent.value,
                    confidence=0.9,
                    quick_actions=[{"label": "Book Now", "action": "I want to book a room"}]
                )

            response_text = f"**Your Stay History** ({len(bookings)} past stays)\n\n"
            for b in bookings[:5]:
                response_text += f"• **{b['room_type']}** | {b['check_in']} - {b['check_out']}\n"

            if len(bookings) > 5:
                response_text += f"\n...and {len(bookings) - 5} more stays"

            return AGIResponse(
                message=response_text,
                intent=intent.value,
                confidence=0.95
            )

        # ====== WIFI INFO ======
        if intent == ConversationIntent.WIFI_INFO:
            if context["status"] != GuestStatus.CHECKED_IN.value:
                return AGIResponse(
                    message="WiFi credentials are available for checked-in guests. Once you check in, I'll be happy to provide the WiFi details!",
                    intent=intent.value,
                    confidence=0.9
                )

            return AGIResponse(
                message=f"""**WiFi Connection Details**

📶 **Network:** {HOTEL_INFO['wifi_network']}
🔑 **Password:** {HOTEL_INFO['wifi_password']}

**Tips:**
• Connect to this network from anywhere in the hotel
• High-speed internet (100+ Mbps)
• Complimentary for all guests
• Contact front desk if you experience any issues

Is there anything else I can help you with?""",
                intent=intent.value,
                confidence=1.0
            )

        # ====== HOUSEKEEPING ======
        if intent == ConversationIntent.HOUSEKEEPING:
            if context["status"] != GuestStatus.CHECKED_IN.value:
                return AGIResponse(
                    message="Housekeeping services are available for guests currently staying with us. If you have an upcoming booking, you can request housekeeping preferences during pre-check-in.",
                    intent=intent.value,
                    confidence=0.9
                )

            room_number = context.get("current_room_number")
            return AGIResponse(
                message=f"""I can help you with housekeeping for Room {room_number}. What would you like?

• **Room Cleaning** - Full room cleaning service
• **Extra Towels** - Fresh towels delivered
• **Extra Pillows/Blankets** - Additional bedding
• **Turndown Service** - Evening bed preparation
• **Toiletries** - Additional bathroom supplies

What can I arrange for you?""",
                intent=intent.value,
                confidence=0.95,
                quick_actions=[
                    {"label": "Room Cleaning", "action": "I need room cleaning"},
                    {"label": "Extra Towels", "action": "I need extra towels"},
                    {"label": "Turndown", "action": "I'd like turndown service"},
                ]
            )

        # ====== MAINTENANCE ======
        if intent == ConversationIntent.MAINTENANCE:
            # Extract issue description from message
            issue_keywords = ["broken", "not working", "doesn't work", "leaking", "leak"]
            issue_description = message  # Use full message as description

            if context["status"] != GuestStatus.CHECKED_IN.value:
                # Guest not checked in - they might have an upcoming booking
                if context.get("status") == GuestStatus.BOOKED.value:
                    return AGIResponse(
                        message=f"I understand you're reporting a maintenance issue. However, maintenance requests can only be submitted once you've checked in.\n\nYour check-in date is {context.get('check_in_date', 'upcoming')}. If you notice any issues upon arrival, please let us know and we'll address them immediately.\n\nIs there anything else I can help with?",
                        intent=intent.value,
                        confidence=0.9
                    )
                else:
                    return AGIResponse(
                        message="I understand you'd like to report a maintenance issue. Maintenance requests are available for guests currently staying with us.\n\nIf you have a booking, please provide your room number or confirmation code so I can assist you.",
                        intent=intent.value,
                        confidence=0.9,
                        quick_actions=[
                            {"label": "Book a Room", "action": "I want to book a room"},
                            {"label": "Contact Us", "action": "I need to speak to front desk"},
                        ]
                    )

            return AGIResponse(
                message=f"""I'm sorry to hear you're having an issue in Room {context.get('current_room_number')}.

Please describe the problem (e.g., "AC not cooling", "TV not working", "bathroom leak") and I'll create a maintenance request right away.

For urgent issues, you can also call the front desk directly at {HOTEL_INFO['phone']}.""",
                intent=intent.value,
                confidence=0.95
            )

        # ====== ROOM SERVICE ======
        if intent == ConversationIntent.ROOM_SERVICE:
            return AGIResponse(
                message=f"""**Room Service Menu**

🍳 **Breakfast** (6:30 AM - 11:00 AM)
• Continental Breakfast - ₹2,000
• American Breakfast - ₹2,650
• Avocado Toast - ₹1,500

🥗 **Lunch & Dinner** (11:00 AM - 10:30 PM)
• Caesar Salad - ₹1,350
• Grilled Salmon - ₹3,150
• Filet Mignon - ₹4,300
• Pasta Primavera - ₹2,150

🍷 **Beverages**
• Fresh Juices - ₹650
• Premium Coffee - ₹500
• Wine by the glass - from ₹1,150

Room service is available 24 hours. A service charge of 18% applies.

What would you like to order?""",
                intent=intent.value,
                confidence=0.95
            )

        # ====== HOTEL INFO ======
        if intent == ConversationIntent.HOTEL_INFO:
            return AGIResponse(
                message=f"""**Glimmora Hotel & Suites Information**

📍 **Location:** {HOTEL_INFO['address']}
📞 **Phone:** {HOTEL_INFO['phone']}

**Hours:**
• Check-in: {HOTEL_INFO['checkin_time']}
• Check-out: {HOTEL_INFO['checkout_time']}
• Pool: {HOTEL_INFO['pool_hours']}
• Gym: {HOTEL_INFO['gym_hours']}
• Spa: {HOTEL_INFO['spa_hours']}
• Restaurant: {HOTEL_INFO['restaurant_hours']}
• Room Service: {HOTEL_INFO['room_service_hours']}

**Amenities:**
• {HOTEL_INFO['parking']}
• Complimentary WiFi
• Rooftop pool with ocean views
• Full-service spa
• 24-hour fitness center

What else would you like to know?""",
                intent=intent.value,
                confidence=0.95,
                quick_actions=[
                    {"label": "Book Room", "action": "I want to book a room"},
                    {"label": "Spa Info", "action": "Tell me about the spa"},
                ]
            )

        # ====== STAFF HELP ======
        if intent == ConversationIntent.STAFF_HELP:
            return AGIResponse(
                message=f"""I'd be happy to connect you with our team!

**Front Desk:** {HOTEL_INFO['phone']}
Available 24/7 for any assistance

**Concierge Services:**
• Restaurant reservations
• Transportation arrangements
• Tour bookings
• Special requests

Would you like me to have someone call you, or would you prefer to call directly?""",
                intent=intent.value,
                confidence=0.95,
                quick_actions=[
                    {"label": "Call Me", "action": "Please have someone call me"},
                    {"label": "I'll Call", "action": "I'll call the front desk"},
                ]
            )

        # ====== DEFAULT/GENERAL ======
        return AGIResponse(
            message="I'm here to help! I can assist you with bookings, hotel information, housekeeping, room service, and more. What would you like to do?",
            intent=intent.value,
            confidence=0.5,
            quick_actions=self._generate_quick_actions(intent, context)
        )

    async def _handle_booking_flow(
        self,
        message: str,
        context: GuestContext,
        booking_flow: BookingFlowState,
        session_id: str,
        user_id: Optional[int]
    ) -> AGIResponse:
        """Handle the booking flow state machine"""

        # Mark that we're in a booking flow
        self._set_active_intent(session_id, "new_booking")
        # Initialize the flow if not started
        if not booking_flow.get("flow_started"):
            self._update_booking_flow(session_id, {"flow_started": True})
            booking_flow["flow_started"] = True

        # Step 1: Need dates
        if not booking_flow.get("check_in_date") or not booking_flow.get("check_out_date"):
            return AGIResponse(
                message="I'd be happy to help you book a room! When would you like to check in and check out?\n\n(e.g., \"December 8 to 10\" or \"Dec 15 to Dec 18 2025\")",
                intent=ConversationIntent.NEW_BOOKING.value,
                confidence=0.9
            )

        # Step 2: Show rooms if not shown
        if not booking_flow.get("rooms_shown"):
            rooms = await self._get_available_rooms(
                booking_flow["check_in_date"],
                booking_flow["check_out_date"],
                booking_flow.get("adults", 1),
                booking_flow.get("children", 0)
            )

            if not rooms:
                return AGIResponse(
                    message="I'm sorry, but there are no rooms available for those dates. Would you like to try different dates?",
                    intent=ConversationIntent.NEW_BOOKING.value,
                    confidence=0.9
                )

            # Store room options with prices for later use
            room_prices = {r["id"]: r["total_price"] for r in rooms}
            self._update_booking_flow(session_id, {"rooms_shown": True, "room_prices": room_prices})

            nights = rooms[0]["nights"]
            response_text = f"Here are our available rooms for {booking_flow['check_in_date']} to {booking_flow['check_out_date']} ({nights} nights):\n\n"

            for i, r in enumerate(rooms, 1):
                response_text += f"**{i}. {r['name']}**\n"
                response_text += f"   {r['description'][:80]}...\n"
                response_text += f"   💰 ${r['total_price']:.2f} total (incl. taxes & fees)\n\n"

            response_text += "Please select a room by number or name."

            return AGIResponse(
                message=response_text,
                intent=ConversationIntent.NEW_BOOKING.value,
                confidence=0.95
            )

        # Step 3: Need room selection
        if not booking_flow.get("room_type_id"):
            return AGIResponse(
                message="Please select a room from the list above by typing the number (1-8) or the room name.",
                intent=ConversationIntent.NEW_BOOKING.value,
                confidence=0.9
            )

        # Step 4: Need guest info
        if not booking_flow.get("first_name") or not booking_flow.get("last_name"):
            room_name = booking_flow.get("room_type_name") or ROOM_TYPES.get(booking_flow["room_type_id"])
            return AGIResponse(
                message=f"Excellent choice! The **{room_name}** is a wonderful room.\n\nTo proceed with your booking, please provide your full name.",
                intent=ConversationIntent.NEW_BOOKING.value,
                confidence=0.9
            )

        if not booking_flow.get("email"):
            # Check if user is logged in
            if context.get("email"):
                self._update_booking_flow(session_id, {"email": context["email"]})
                booking_flow["email"] = context["email"]
            else:
                return AGIResponse(
                    message=f"Thank you, {booking_flow['first_name']}! Please provide your email address for the booking confirmation.",
                    intent=ConversationIntent.NEW_BOOKING.value,
                    confidence=0.9
                )

        if not booking_flow.get("phone"):
            if context.get("phone"):
                self._update_booking_flow(session_id, {"phone": context["phone"]})
                booking_flow["phone"] = context["phone"]
            else:
                return AGIResponse(
                    message="Please provide your phone number (we'll only use this for important booking updates).",
                    intent=ConversationIntent.NEW_BOOKING.value,
                    confidence=0.9
                )

        if not booking_flow.get("country"):
            return AGIResponse(
                message="Which country are you from?",
                intent=ConversationIntent.NEW_BOOKING.value,
                confidence=0.9
            )

        # Step 5: All info collected - Send OTP
        if not booking_flow.get("otp_sent"):
            # Send OTP
            otp_sent = await self._send_booking_otp(booking_flow["email"], booking_flow)
            if otp_sent:
                self._update_booking_flow(session_id, {"otp_sent": True})

                # Try to get room details for display, but don't fail if this errors
                room_name = booking_flow.get("room_type_name") or ROOM_TYPES.get(booking_flow.get("room_type_id"))
                total_price = booking_flow.get("total_price", 0)

                try:
                    rooms = await self._get_available_rooms(
                        booking_flow["check_in_date"],
                        booking_flow["check_out_date"]
                    )
                    if rooms:
                        room_match = next((r for r in rooms if r["id"] == booking_flow.get("room_type_id")), None)
                        if room_match:
                            total_price = room_match.get("total_price", total_price)
                            if not room_name:
                                room_name = room_match.get("name", "Selected Room")
                except Exception as e:
                    logger.warning(f"Could not get room details for OTP confirmation: {e}")
                    # Continue with whatever info we have

                if not room_name:
                    room_name = "Selected Room"

                return AGIResponse(
                    message=f"""**Please verify your booking:**

📧 A 6-digit verification code has been sent to **{booking_flow['email']}**

**Booking Summary:**
• Room: {room_name}
• Check-in: {booking_flow['check_in_date']}
• Check-out: {booking_flow['check_out_date']}
• Guest: {booking_flow['first_name']} {booking_flow['last_name']}
• Total: ${total_price:.2f}

Please enter the 6-digit OTP to confirm your booking.""",
                    intent=ConversationIntent.NEW_BOOKING.value,
                    confidence=0.95,
                    requires_otp=True,
                    otp_email=booking_flow["email"],
                    otp_purpose="booking_payment"
                )
            else:
                return AGIResponse(
                    message="I'm sorry, there was an issue sending the verification code. Please try again.",
                    intent="error",
                    confidence=0.0
                )

        # Step 6: Waiting for OTP
        if booking_flow.get("otp_sent") and not booking_flow.get("otp_verified"):
            return AGIResponse(
                message=f"Please enter the 6-digit verification code sent to {booking_flow['email']}.",
                intent=ConversationIntent.NEW_BOOKING.value,
                confidence=0.9,
                requires_otp=True,
                otp_email=booking_flow.get("email")
            )

        # This shouldn't happen normally
        return AGIResponse(
            message="Let me help you complete your booking. What information do you need to provide?",
            intent=ConversationIntent.NEW_BOOKING.value,
            confidence=0.7
        )


def get_guest_agi_v2(db: AsyncSession) -> GuestAGIV2:
    """Factory function"""
    return GuestAGIV2(db)
