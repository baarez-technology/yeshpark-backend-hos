"""
Unified Guest Chatbot Service - Advanced AI-Powered
A comprehensive AI-powered chatbot for hotel guests with:
- OpenAI LLM integration for natural language understanding
- FAQ handling with semantic search
- Booking verification and lookup
- Intelligent staff task scheduling
- Real-time assistance tracking
- Email notifications for staff

This is the MAIN chatbot service for in-house guests (distinct from AGI booking assistant)
"""

import os
import re
import json
import uuid
import logging
from datetime import datetime, timedelta, date as date_type
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import func

from app.models.guest_chat import (
    GuestChatSession, GuestChatConversation, StaffTask, StaffNotification
)
from app.models.reservations import Booking, Guest, Reservation
from app.models.inventory import Room, RoomType
from app.models.user import User
from app.models.precheckin import PreCheckIn
from app.services.staff_scheduling_service import StaffSchedulingService, get_scheduling_service
from app.services.email_service import get_email_service, EmailService
from app.services.chatbot_state_machine import (
    ConversationState, ConversationContext, StateMachine, FlowType, state_machine
)
from app.services.chatbot_actions import (
    ActionExecutor, RoomSearchAction, BookingDetailsAction, BookingModifyAction,
    BookingCancelAction, BookingCreateAction, ProfileViewAction, ProfileUpdateAction,
    MyBookingsAction, PreCheckinVerifyAction, PreCheckinCreateAction
)
from app.core.config import settings

# Load environment variables
from dotenv import load_dotenv
load_dotenv(override=True)

logger = logging.getLogger("unified_guest_chatbot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class MessageIntent(Enum):
    """Classified intents for guest messages"""
    GREETING = "greeting"
    FAQ = "faq"
    HOUSEKEEPING = "housekeeping"
    MAINTENANCE = "maintenance"
    ROOM_SERVICE = "room_service"
    CONCIERGE = "concierge"
    BOOKING_INQUIRY = "booking_inquiry"
    BOOKING_LOOKUP = "booking_lookup"
    COMPLAINT = "complaint"
    FEEDBACK = "feedback"
    EMERGENCY = "emergency"
    GENERAL = "general"
    OTHER = "other"
    # New comprehensive AGI intents
    ROOM_SEARCH = "room_search"           # Search for available rooms
    MAKE_BOOKING = "make_booking"         # Create a new booking
    PRECHECKIN = "precheckin"             # Start pre-checkin flow
    PROFILE_VIEW = "profile_view"         # View guest profile
    PROFILE_UPDATE = "profile_update"     # Update profile information
    BOOKING_MODIFY = "booking_modify"     # Modify existing booking
    BOOKING_CANCEL = "booking_cancel"     # Cancel a booking
    MY_BOOKINGS = "my_bookings"           # List user's bookings
    # Staff assistance intents
    STAFF_HELP = "staff_help"             # Request staff assistance
    CAPABILITIES = "capabilities"         # What can Aria do?


@dataclass
class ChatResponse:
    """Structured chat response"""
    response: str
    intent: str
    confidence: float
    requires_staff_action: bool = False
    staff_task_id: Optional[int] = None
    task_type: Optional[str] = None
    assigned_staff_name: Optional[str] = None
    estimated_response_time: Optional[int] = None  # minutes
    # Enhanced task details
    task_priority: Optional[str] = None  # critical, high, medium, low
    task_title: Optional[str] = None
    task_description: Optional[str] = None
    task_category: Optional[str] = None  # e.g., "Plumbing Issue", "HVAC Issue"
    detected_issue: Optional[str] = None  # e.g., "shower", "ac", "wifi"
    required_skills: Optional[List[str]] = None
    assigned_staff_role: Optional[str] = None
    faq_id: Optional[str] = None
    booking_info: Optional[Dict[str, Any]] = None
    quick_actions: Optional[List[Dict[str, str]]] = None
    # New comprehensive AGI fields
    room_search_results: Optional[List[Dict[str, Any]]] = None
    profile_info: Optional[Dict[str, Any]] = None
    bookings_list: Optional[List[Dict[str, Any]]] = None
    precheckin_info: Optional[Dict[str, Any]] = None
    flow_state: Optional[Dict[str, Any]] = None  # {flow_type, current_step, step_label, progress, can_cancel}
    requires_auth: bool = False
    auth_error: Optional[str] = None
    action_result: Optional[Dict[str, Any]] = None  # Result from action executors


class OpenAIService:
    """
    OpenAI integration for advanced natural language processing
    """

    def __init__(self):
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model or "gpt-3.5-turbo"
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize OpenAI client if API key is available"""
        if not self.api_key:
            logger.warning("OpenAI API key not configured - using fallback mode")
            return

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
            logger.info(f"OpenAI client initialized with model: {self.model}")
        except ImportError:
            logger.warning("OpenAI package not installed - using fallback mode")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")

    @property
    def is_available(self) -> bool:
        return self.client is not None

    async def classify_intent(self, message: str, context: Optional[str] = None) -> Tuple[str, float]:
        """
        Use OpenAI to classify message intent
        Returns: (intent_name, confidence)
        """
        if not self.is_available:
            return None, 0.0

        try:
            system_prompt = """You are an intent classifier for a hotel chatbot. Classify the guest's message into ONE of these categories:

- GREETING: Hello, hi, good morning, etc.
- BOOKING_LOOKUP: Guest providing a booking/confirmation number (e.g., "GLM-XXX123", "my booking is ABC123")
- BOOKING_INQUIRY: Questions about their reservation, check-in/out times
- HOUSEKEEPING: Room cleaning, towels, toiletries, sheets, minibar, turndown service
- MAINTENANCE: Broken items, repairs, AC not working, plumbing issues, wifi problems
- ROOM_SERVICE: Food orders, menu questions, in-room dining
- CONCIERGE: Recommendations, taxi, directions, local attractions, spa, gym
- COMPLAINT: Expressing dissatisfaction, problems, asking for manager
- FEEDBACK: Positive feedback, compliments, thanks
- EMERGENCY: Medical emergency, fire, security issues
- FAQ: General questions about hotel policies, amenities, hours, wifi password
- ROOM_SEARCH: Looking for available rooms, checking room availability, searching for rooms to book
- MAKE_BOOKING: Wants to make a new booking, reserve a room, create a reservation
- PRECHECKIN: Online check-in, pre-checkin, digital check-in, web check-in
- PROFILE_VIEW: View my profile, show my account, see my details
- PROFILE_UPDATE: Update phone, change email, modify profile, update preferences
- BOOKING_MODIFY: Change booking dates, extend stay, modify reservation
- BOOKING_CANCEL: Cancel booking, cancel reservation, cancellation request
- MY_BOOKINGS: Show my bookings, list my reservations, booking history
- STAFF_HELP: Need help, send someone, talk to a person, front desk, speak to staff
- CAPABILITIES: What can you do, your features, how can you help, tell me about yourself
- GENERAL: General conversation or unclear intent

Respond with ONLY the category name and confidence score (0-1) in this exact format:
CATEGORY|0.95

Examples:
- "GLM-LSS334" -> BOOKING_LOOKUP|0.98
- "My booking number is ABC123" -> BOOKING_LOOKUP|0.99
- "I need more towels" -> HOUSEKEEPING|0.95
- "The AC is not working" -> MAINTENANCE|0.97
- "What time is checkout?" -> FAQ|0.90
- "Hello" -> GREETING|0.99
- "Show available rooms" -> ROOM_SEARCH|0.95
- "I want to book a room" -> MAKE_BOOKING|0.96
- "Start my pre-checkin" -> PRECHECKIN|0.97
- "Show my profile" -> PROFILE_VIEW|0.95
- "Update my phone number" -> PROFILE_UPDATE|0.94
- "Change my booking dates" -> BOOKING_MODIFY|0.95
- "Cancel my reservation" -> BOOKING_CANCEL|0.96
- "Show my bookings" -> MY_BOOKINGS|0.97
- "I need to talk to someone" -> STAFF_HELP|0.95
- "Send someone to help" -> STAFF_HELP|0.96
- "What can you help me with?" -> CAPABILITIES|0.95
- "What can you do?" -> CAPABILITIES|0.97"""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                max_tokens=20,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip()
            parts = result.split("|")

            if len(parts) == 2:
                intent = parts[0].strip().upper()
                confidence = float(parts[1].strip())
                return intent, min(confidence, 1.0)

            return parts[0].strip().upper(), 0.8

        except Exception as e:
            logger.error(f"OpenAI intent classification error: {e}")
            return None, 0.0

    async def generate_response(
        self,
        message: str,
        intent: str,
        context: Dict[str, Any],
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        Generate a natural, contextual response using OpenAI with comprehensive guest context
        """
        if not self.is_available:
            return None

        try:
            # Build comprehensive context string
            context_info = []

            # Guest identification
            if context.get("guest_name"):
                guest_intro = f"Guest: {context['guest_name']}"
                if context.get("loyalty_tier") and context["loyalty_tier"] != "Standard":
                    guest_intro += f" ({context['loyalty_tier']} Member)"
                if context.get("is_vip"):
                    guest_intro += " - VIP"
                context_info.append(guest_intro)

            # Stay information
            if context.get("room_number"):
                context_info.append(f"Room: {context['room_number']}")
            if context.get("room_type"):
                context_info.append(f"Room Type: {context['room_type']}")
            if context.get("booking_status"):
                status_display = context['booking_status'].replace('_', ' ').title()
                context_info.append(f"Status: {status_display}")
            if context.get("check_out_date"):
                context_info.append(f"Check-out: {context['check_out_date']}")
            if context.get("nights_staying"):
                context_info.append(f"Stay Duration: {context['nights_staying']} night(s)")

            # Loyalty and history
            if context.get("is_repeat_guest"):
                stays = context.get("total_stays", 0)
                context_info.append(f"Returning Guest ({stays} previous stays)")
            if context.get("loyalty_points") and context["loyalty_points"] > 0:
                context_info.append(f"Loyalty Points: {context['loyalty_points']:,}")

            # Preferences and requests
            if context.get("special_requests"):
                context_info.append(f"Special Requests: {context['special_requests']}")
            if context.get("preferences"):
                prefs = context["preferences"]
                pref_items = []
                if prefs.get("room_temperature"):
                    pref_items.append(f"prefers {prefs['room_temperature']} temperature")
                if prefs.get("pillow_type"):
                    pref_items.append(f"{prefs['pillow_type']} pillows")
                if prefs.get("dietary"):
                    pref_items.append(f"dietary: {prefs['dietary']}")
                if pref_items:
                    context_info.append(f"Preferences: {', '.join(pref_items)}")

            # Task creation context
            if context.get("task_created"):
                context_info.append("Service task has been created")
                if context.get("assigned_staff"):
                    context_info.append(f"Assigned to: {context['assigned_staff']}")

            context_str = "\n".join(context_info) if context_info else "Anonymous guest (not yet identified)"

            # Time-aware greeting
            time_of_day = context.get("current_time_of_day", "day")

            # Build personalized system prompt
            vip_note = ""
            if context.get("is_vip") or context.get("loyalty_tier") in ["Gold", "Platinum", "Diamond"]:
                vip_note = """
IMPORTANT: This is a VIP/Loyalty member. Provide elevated service:
- Use their name and acknowledge their loyalty status
- Offer expedited service where possible
- Mention any exclusive benefits or perks available to them
- Be extra attentive to their preferences"""

            repeat_guest_note = ""
            if context.get("is_repeat_guest") and not context.get("is_vip"):
                repeat_guest_note = """
Note: This is a returning guest. Welcome them back warmly and reference their loyalty to the hotel."""

            system_prompt = f"""You are Aria, a friendly and highly capable AI concierge for Glimmora Hotel & Suites. You are knowledgeable, warm, and genuinely helpful.

Current Time: Good {time_of_day}

=== GUEST CONTEXT ===
{context_str}
{vip_note}
{repeat_guest_note}

=== YOUR PERSONALITY ===
- Warm, professional, and genuinely caring
- Proactive in anticipating guest needs
- Knowledgeable about all hotel services and local area
- Quick to escalate urgent issues appropriately
- Use the guest's first name when you know it

=== RESPONSE GUIDELINES ===
1. For SERVICE REQUESTS (housekeeping, maintenance, room service):
   - Confirm the specific request and acknowledge any urgency
   - Assure them you're arranging assistance immediately
   - Provide estimated response time based on priority
   - Ask if there's anything else they need

2. For MAINTENANCE ISSUES:
   - Show empathy for any inconvenience
   - Confirm you understand the specific problem
   - Explain that a qualified technician will be dispatched
   - Offer interim solutions if applicable (e.g., "While you wait, you can use the pool towels in the fitness center")

3. For EMERGENCIES:
   - Stay calm but act urgently
   - Direct them to call extension 0 immediately
   - Confirm help is on the way

4. For COMPLAINTS:
   - Apologize sincerely and specifically
   - Acknowledge their feelings
   - Assure immediate escalation to management
   - Offer to make it right

5. For VIP GUESTS:
   - Acknowledge their loyalty status
   - Offer premium service options
   - Be extra attentive to preferences

=== HOTEL INFORMATION ===
- Check-in: 3:00 PM | Check-out: 11:00 AM (early/late available on request)
- WiFi: "Glimmora_Guest" - password at check-in
- Room Service: 24/7
- Breakfast: 6:30 AM - 10:30 AM (11:00 AM weekends)
- Fitness Center: 24 hours
- Pool: Indoor 6 AM-10 PM, Outdoor 8 AM-8 PM (seasonal)
- Spa: 15% guest discount, advance booking recommended
- Parking: Complimentary self-parking, Valet $25/day
- Concierge Desk: Available 24/7
- Front Desk: Extension 0

=== CURRENT INTENT ===
The guest's message has been classified as: {intent}

Keep responses conversational and concise (2-4 sentences for simple queries, more for complex issues)."""

            messages = [{"role": "system", "content": system_prompt}]

            # Add conversation history if available
            if conversation_history:
                for msg in conversation_history[-6:]:  # Last 3 exchanges
                    messages.append({
                        "role": "user" if msg.get("is_user") else "assistant",
                        "content": msg.get("content", "")
                    })

            messages.append({"role": "user", "content": message})

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=400,
                temperature=0.7
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"OpenAI response generation error: {e}")
            return None

    async def extract_booking_number(self, message: str) -> Optional[str]:
        """
        Use AI to extract booking/confirmation number from message
        """
        if not self.is_available:
            return self._fallback_extract_booking(message)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """Extract the booking or confirmation number from the message.
Return ONLY the booking number (alphanumeric code), or "NONE" if no booking number is found.
Examples:
- "My booking is GLM-LSS334" -> GLM-LSS334
- "GLM-LSS334" -> GLM-LSS334
- "Confirmation ABC123XYZ" -> ABC123XYZ
- "I need towels" -> NONE"""
                    },
                    {"role": "user", "content": message}
                ],
                max_tokens=30,
                temperature=0
            )

            result = response.choices[0].message.content.strip().upper()
            if result == "NONE" or len(result) < 4:
                return None
            return result

        except Exception as e:
            logger.error(f"OpenAI booking extraction error: {e}")
            return self._fallback_extract_booking(message)

    def _fallback_extract_booking(self, message: str) -> Optional[str]:
        """Fallback regex-based booking number extraction"""
        # Pattern for booking numbers like GLM-XXX123, ABC123, etc.
        patterns = [
            r'\b([A-Z]{2,4}[-]?[A-Z0-9]{4,10})\b',  # GLM-LSS334, GLMLSS334
            r'\b([A-Z0-9]{6,12})\b',  # Generic alphanumeric
        ]

        message_upper = message.upper()
        for pattern in patterns:
            match = re.search(pattern, message_upper)
            if match:
                return match.group(1)
        return None


class IntentClassifier:
    """
    Hybrid intent classifier using both AI and pattern matching
    """

    # Intent patterns with keywords and phrases
    INTENT_PATTERNS = {
        MessageIntent.GREETING: {
            "keywords": ["hi", "hello", "hey", "good morning", "good afternoon",
                        "good evening", "howdy", "greetings", "hola"],
            "patterns": [r"^(hi|hello|hey|good\s+(morning|afternoon|evening))(\s|!|$)"],
            "priority": 1
        },
        MessageIntent.EMERGENCY: {
            "keywords": ["emergency", "fire", "medical", "ambulance", "police",
                        "help urgent", "danger", "accident", "injured"],
            "patterns": [r"emergency", r"(need|call).*(ambulance|police|fire)"],
            "priority": 0
        },
        MessageIntent.BOOKING_LOOKUP: {
            "keywords": ["booking number", "confirmation number", "my booking", "reservation number"],
            "patterns": [
                r"^[A-Z]{2,4}[-]?[A-Z0-9]{4,10}$",  # Just a booking code
                r"(booking|confirmation|reservation)\s*(number|code|#|is|:)?\s*[A-Z0-9-]+",
                r"my\s+(booking|confirmation|reservation)\s+(is|number)",
            ],
            "priority": 0
        },
        MessageIntent.HOUSEKEEPING: {
            "keywords": ["clean", "cleaning", "housekeeping", "towels", "towel",
                        "sheets", "bedding", "vacuum", "maid", "trash", "garbage",
                        "linens", "pillows", "blanket", "minibar", "toiletries"],
            "patterns": [r"clean\s*(my)?\s*room", r"need\s*(more)?\s*towels?"],
            "priority": 2
        },
        MessageIntent.MAINTENANCE: {
            "keywords": ["broken", "fix", "repair", "maintenance", "not working",
                        "leak", "leaking", "clogged", "stuck", "noise",
                        "ac", "air conditioning", "heating", "light", "bulb",
                        "tv", "television", "wifi", "internet", "plumbing"],
            "patterns": [r"(broken|not\s*working)", r"fix\s*(the|my)"],
            "priority": 2
        },
        MessageIntent.ROOM_SERVICE: {
            "keywords": ["room service", "food", "order food", "menu", "breakfast",
                        "lunch", "dinner", "snack", "drink", "coffee", "tea", "hungry"],
            "patterns": [r"room\s*service", r"order\s*(some)?\s*food"],
            "priority": 2
        },
        MessageIntent.CONCIERGE: {
            "keywords": ["recommend", "recommendation", "restaurant", "taxi", "cab",
                        "uber", "directions", "tour", "attraction", "shopping", "spa", "gym", "pool"],
            "patterns": [r"recommend\s*(a|me)", r"where\s*(can|should)"],
            "priority": 3
        },
        MessageIntent.BOOKING_INQUIRY: {
            "keywords": ["check-in", "check-out", "checkout", "checkin", "extend",
                        "cancel", "modify", "my room", "reservation"],
            "patterns": [r"check[\s\-]*(in|out)\s*time", r"(extend|cancel|modify)\s*(my)?\s*(stay|booking)"],
            "priority": 3
        },
        MessageIntent.COMPLAINT: {
            "keywords": ["complaint", "complain", "unhappy", "disappointed", "terrible",
                        "awful", "worst", "unacceptable", "refund", "manager"],
            "patterns": [r"(want|need)\s*to\s*complain", r"speak\s*(to|with)\s*(a)?\s*manager"],
            "priority": 2
        },
        MessageIntent.FEEDBACK: {
            "keywords": ["feedback", "wonderful", "amazing", "great", "excellent",
                        "thank you", "thanks", "appreciate", "loved"],
            "patterns": [r"thank\s*you\s*(so\s*much|for)"],
            "priority": 4
        },
        MessageIntent.FAQ: {
            "keywords": ["what", "when", "where", "how", "policy", "wifi password",
                        "parking", "breakfast time", "checkout time", "amenities"],
            "patterns": [r"^(what|when|where|how)\s", r"do\s*you\s*(have|offer)"],
            "priority": 3
        },
        # New comprehensive AGI intents
        MessageIntent.ROOM_SEARCH: {
            "keywords": ["available rooms", "find room", "search rooms", "show rooms",
                        "room availability", "vacant rooms", "what rooms", "looking for room",
                        "any rooms", "rooms available"],
            "patterns": [
                r"(available|find|search|show|check)\s*(for)?\s*rooms?",
                r"room\s*availability",
                r"(what|any)\s*rooms?\s*(are)?\s*available",
                r"looking\s*for\s*(a)?\s*room",
                r"need\s*a\s*room",
                r"book\s*a\s*room\s*for"
            ],
            "priority": 1
        },
        MessageIntent.MAKE_BOOKING: {
            "keywords": ["make booking", "book room", "reserve", "reservation",
                        "i want to book", "create booking", "new booking", "book a stay",
                        "make a booking", "make reservation"],
            "patterns": [
                r"(make|create)\s*(a)?\s*(new)?\s*(booking|reservation)",
                r"(new)\s*(booking|reservation)",
                r"(book|reserve)\s*(a|the)?\s*(room|stay|suite)",
                r"i\s*(want|would\s*like|need)\s*to\s*(make\s*(a)?\s*)?(new\s*)?(book|reserve|booking|reservation)",
                r"can\s*i\s*(make\s*(a)?\s*)?(book|reserve|booking)",
                r"(want|need)\s*(a|to\s*make\s*a)?\s*(new\s*)?(booking|reservation)"
            ],
            "priority": 1
        },
        MessageIntent.PRECHECKIN: {
            "keywords": ["pre-checkin", "precheckin", "online checkin", "digital checkin",
                        "check in online", "early checkin", "web checkin", "pre check-in",
                        "do precheckin", "want precheckin"],
            "patterns": [
                r"pre[\s\-]?check[\s\-]?in",
                r"(online|digital|web)\s*check[\s\-]?in",
                r"check[\s\-]?in\s*(online|early|before)",
                r"start\s*(my)?\s*(pre[\s\-]?)?check[\s\-]?in",
                r"complete\s*(my)?\s*check[\s\-]?in",
                r"(want|do|begin|initiate)\s*(to\s*)?(do\s*)?(my\s*)?(pre[\s\-]?)?check[\s\-]?in",
                r"(pre[\s\-]?)?check[\s\-]?in\s*(for|with)\s*[A-Z0-9\-]+",
                r"(i\s+)?(want|need)\s*(to)?\s*(do\s*)?(pre[\s\-]?)?check[\s\-]?in"
            ],
            "priority": 1
        },
        MessageIntent.PROFILE_VIEW: {
            "keywords": ["my profile", "my account", "view profile", "show profile",
                        "my details", "my information", "account info", "profile info"],
            "patterns": [
                r"(show|view|see|display)\s*(my)?\s*(profile|account|details|info)",
                r"my\s*(profile|account|details|information)",
                r"what\s*(is|are)\s*my\s*(details|info)"
            ],
            "priority": 2
        },
        MessageIntent.PROFILE_UPDATE: {
            "keywords": ["update profile", "change phone", "change email", "update my",
                        "modify profile", "edit profile", "change my details", "update contact"],
            "patterns": [
                r"(update|change|modify|edit)\s*(my)?\s*(profile|phone|email|contact|address|details)",
                r"(update|change)\s*(my)?\s*(preferences|settings)",
                r"my\s*(new)?\s*(phone|email|address)\s*(is|:)"
            ],
            "priority": 2
        },
        MessageIntent.BOOKING_MODIFY: {
            "keywords": ["change booking", "modify booking", "change dates", "extend stay",
                        "modify reservation", "update booking", "change my booking"],
            "patterns": [
                r"(change|modify|update|extend)\s*(my)?\s*(booking|reservation|stay|dates)",
                r"(move|shift)\s*(my)?\s*(check[\s\-]?in|check[\s\-]?out|dates)",
                r"(add|remove)\s*nights?",
                r"extend\s*(my)?\s*stay"
            ],
            "priority": 2
        },
        MessageIntent.BOOKING_CANCEL: {
            "keywords": ["cancel booking", "cancel reservation", "cancel my stay",
                        "cancellation", "want to cancel", "cancel my booking"],
            "patterns": [
                r"cancel\s*(my)?\s*(booking|reservation|stay)",
                r"(i\s*)?(want|need|would like)\s*to\s*cancel",
                r"cancellation\s*(policy|request)?",
                r"(how|can)\s*(i|to)\s*cancel"
            ],
            "priority": 1
        },
        MessageIntent.MY_BOOKINGS: {
            "keywords": ["my bookings", "my reservations", "show my bookings", "list bookings",
                        "all my bookings", "my stays", "booking history", "past bookings"],
            "patterns": [
                r"(show|view|see|list|display)\s*(my|all)?\s*(bookings?|reservations?|stays?)",
                r"my\s*(bookings?|reservations?|stays?)",
                r"(booking|reservation)\s*history",
                r"(past|upcoming|future)\s*(bookings?|reservations?|stays?)"
            ],
            "priority": 2
        },
        MessageIntent.STAFF_HELP: {
            "keywords": ["need help", "send someone", "talk to someone", "human", "real person",
                        "staff", "front desk", "call someone", "assistance", "help me",
                        "speak to someone", "manager", "need assistance", "person"],
            "patterns": [
                r"(need|want|get)\s*(some)?\s*(help|assistance|support)",
                r"(send|call|get)\s*(me)?\s*(someone|staff|person)",
                r"(talk|speak)\s*to\s*(a|the)?\s*(person|human|staff|someone|manager)",
                r"(real|actual|live)\s*(person|human)",
                r"(contact|reach|call)\s*(front)?\s*desk"
            ],
            "priority": 1
        },
        MessageIntent.CAPABILITIES: {
            "keywords": ["what can you do", "what are you", "your capabilities", "help me understand",
                        "what do you do", "how can you help", "what services", "what can i ask",
                        "features", "abilities", "tell me about yourself"],
            "patterns": [
                r"what\s*(can|do)\s*you\s*(do|help|offer|provide)",
                r"what\s*are\s*you(r)?\s*(capabilities|features|abilities)?",
                r"(tell|explain)\s*(me)?\s*about\s*(yourself|you|your\s*services)",
                r"(how|what)\s*(can|ways)\s*(you|i)\s*(help|ask|do)",
                r"your\s*(capabilities|features|services)"
            ],
            "priority": 2
        }
    }

    def __init__(self, openai_service: OpenAIService):
        self.openai = openai_service

    async def classify(self, message: str) -> Tuple[MessageIntent, float]:
        """
        Classify message intent using hybrid AI + pattern approach
        """
        if not message or not message.strip():
            return MessageIntent.OTHER, 0.5

        message_clean = message.strip()
        message_lower = message_clean.lower()
        message_upper = message_clean.upper()

        # Check if it looks like a booking number (just the code)
        if re.match(r'^[A-Z]{2,4}[-]?[A-Z0-9]{4,10}$', message_upper):
            return MessageIntent.BOOKING_LOOKUP, 0.98

        # Try OpenAI classification first
        if self.openai.is_available:
            ai_intent, ai_confidence = await self.openai.classify_intent(message_clean)
            if ai_intent and ai_confidence >= 0.7:
                try:
                    intent = MessageIntent[ai_intent]
                    return intent, ai_confidence
                except KeyError:
                    pass  # Fall through to pattern matching

        # Fallback to pattern matching
        return self._pattern_classify(message_lower)

    def _pattern_classify(self, message_lower: str) -> Tuple[MessageIntent, float]:
        """Pattern-based classification fallback"""
        scores: Dict[MessageIntent, float] = {}

        for intent, config in self.INTENT_PATTERNS.items():
            score = 0.0

            # Check keywords
            keyword_matches = sum(1 for kw in config["keywords"] if kw in message_lower)
            if keyword_matches > 0:
                score += min(keyword_matches * 0.2, 0.6)

            # Check patterns
            for pattern in config["patterns"]:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    score += 0.4
                    break

            # Priority boost
            priority_boost = (5 - config["priority"]) * 0.05
            score += priority_boost

            scores[intent] = min(score, 1.0)

        if not scores:
            return MessageIntent.GENERAL, 0.5

        best_intent = max(scores, key=lambda k: scores[k])
        best_score = scores[best_intent]

        if best_score < 0.3:
            return MessageIntent.GENERAL, 0.5

        return best_intent, best_score


class FAQEngine:
    """FAQ search engine with semantic and fuzzy matching"""

    def __init__(self, faqs_path: Optional[Path] = None):
        self.faqs: List[Dict[str, Any]] = []
        self.semantic_available = False
        self._load_faqs(faqs_path)
        self._init_semantic_search()

    def _load_faqs(self, faqs_path: Optional[Path] = None):
        """Load FAQs from JSON file"""
        if faqs_path is None:
            # Try multiple paths
            possible_paths = [
                Path(__file__).parent.parent / "hotel_faqs.json",
                Path(__file__).parent.parent.parent / "hotel_faqs.json",
                Path("Backend/hotel_faqs.json"),
                Path("hotel_faqs.json"),
            ]
            for path in possible_paths:
                if path.exists():
                    faqs_path = path
                    break

        if faqs_path is None or not faqs_path.exists():
            logger.warning("FAQ file not found, using defaults")
            self.faqs = self._get_default_faqs()
            return

        try:
            with open(faqs_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            def extract_faqs(obj, result, category="general"):
                if isinstance(obj, dict):
                    if "question" in obj and "answer" in obj:
                        result.append({
                            "id": f"faq_{len(result)+1}",
                            "question": obj["question"],
                            "answer": obj["answer"],
                            "paraphrases": obj.get("paraphrases", []),
                            "category": category
                        })
                    else:
                        for key, value in obj.items():
                            cat = key if isinstance(key, str) else category
                            extract_faqs(value, result, cat)
                elif isinstance(obj, list):
                    for item in obj:
                        extract_faqs(item, result, category)

            extract_faqs(data, self.faqs)
            logger.info(f"Loaded {len(self.faqs)} FAQs")

        except Exception as e:
            logger.error(f"Error loading FAQs: {e}")
            self.faqs = self._get_default_faqs()

    def _get_default_faqs(self) -> List[Dict[str, Any]]:
        """Default FAQs"""
        return [
            {
                "id": "faq_1",
                "question": "What are your check-in and check-out times?",
                "answer": "Check-in time is 3:00 PM and check-out time is 11:00 AM. Early check-in and late check-out may be available upon request, subject to availability.",
                "paraphrases": ["check in time", "check out time", "when can I check in"],
                "category": "policy"
            },
            {
                "id": "faq_2",
                "question": "What is the WiFi password?",
                "answer": "Connect to 'Glimmora_Guest' network. The password is provided at check-in or available at the front desk.",
                "paraphrases": ["wifi", "internet", "wireless password", "wifi password"],
                "category": "amenities"
            },
            {
                "id": "faq_3",
                "question": "Is parking available?",
                "answer": "Yes, we offer complimentary self-parking for all guests. Valet parking is available for $25/day. Electric vehicle charging stations are available.",
                "paraphrases": ["parking", "car parking", "valet", "where to park"],
                "category": "amenities"
            },
            {
                "id": "faq_4",
                "question": "What time is breakfast served?",
                "answer": "Breakfast is served from 6:30 AM to 10:30 AM on weekdays and until 11:00 AM on weekends. Both buffet and a la carte options are available.",
                "paraphrases": ["breakfast hours", "when is breakfast", "breakfast time"],
                "category": "dining"
            },
            {
                "id": "faq_5",
                "question": "Do you have a spa?",
                "answer": "Yes, our full-service spa offers massages, facials, body treatments, and salon services. Advance booking is recommended. Hotel guests receive a 15% discount.",
                "paraphrases": ["spa", "massage", "treatment", "wellness"],
                "category": "amenities"
            },
        ]

    def _init_semantic_search(self):
        """Initialize semantic search if available"""
        try:
            from sentence_transformers import SentenceTransformer
            import faiss
            import numpy as np

            self.model = SentenceTransformer("all-MiniLM-L6-v2")  # Faster model

            texts = []
            self.text_to_faq = []
            for i, faq in enumerate(self.faqs):
                texts.append(faq["question"])
                self.text_to_faq.append(i)
                for p in faq.get("paraphrases", []):
                    texts.append(p)
                    self.text_to_faq.append(i)

            if texts:
                embeddings = self.model.encode(texts, convert_to_numpy=True).astype("float32")
                faiss.normalize_L2(embeddings)
                self.index = faiss.IndexFlatIP(embeddings.shape[1])
                self.index.add(embeddings)
                self.semantic_available = True
                logger.info("Semantic FAQ search initialized")

        except ImportError:
            logger.info("Semantic libraries not available, using fuzzy matching")
        except Exception as e:
            logger.warning(f"Semantic init failed: {e}")

    def search(self, query: str, top_k: int = 3) -> List[Tuple[Dict[str, Any], float]]:
        """Search FAQs for best matches"""
        if self.semantic_available:
            return self._semantic_search(query, top_k)
        return self._fuzzy_search(query, top_k)

    def _semantic_search(self, query: str, top_k: int) -> List[Tuple[Dict[str, Any], float]]:
        """Semantic embedding search"""
        try:
            import faiss

            query_embedding = self.model.encode([query], convert_to_numpy=True).astype("float32")
            faiss.normalize_L2(query_embedding)

            scores, indices = self.index.search(query_embedding, top_k * 2)

            results = []
            seen = set()
            for i, idx in enumerate(indices[0]):
                if idx < len(self.text_to_faq):
                    faq_idx = self.text_to_faq[idx]
                    if faq_idx not in seen:
                        seen.add(faq_idx)
                        results.append((self.faqs[faq_idx], float(scores[0][i])))
                        if len(results) >= top_k:
                            break

            return results
        except Exception as e:
            logger.warning(f"Semantic search failed: {e}")
            return self._fuzzy_search(query, top_k)

    def _fuzzy_search(self, query: str, top_k: int) -> List[Tuple[Dict[str, Any], float]]:
        """Fuzzy string matching fallback"""
        from difflib import SequenceMatcher

        query_lower = query.lower()
        query_words = set(query_lower.split())

        results = []
        for faq in self.faqs:
            question_lower = faq["question"].lower()
            question_words = set(question_lower.split())

            # Word overlap
            overlap = len(query_words & question_words) / max(len(query_words), 1)

            # Sequence match
            seq_score = SequenceMatcher(None, query_lower, question_lower).ratio()

            # Paraphrase match
            para_score = 0.0
            for p in faq.get("paraphrases", []):
                p_lower = p.lower()
                if p_lower in query_lower or query_lower in p_lower:
                    para_score = max(para_score, 0.85)
                else:
                    para_score = max(para_score, SequenceMatcher(None, query_lower, p_lower).ratio())

            final_score = max(overlap * 0.6 + seq_score * 0.4, para_score)
            results.append((faq, final_score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


class UnifiedGuestChatbot:
    """Main chatbot service with AI integration"""

    TEMPLATES = {
        "greeting": [
            "Hello! Welcome to Glimmora Hotel & Suites. I'm your virtual assistant. How can I help you today?",
            "Hi there! I'm here to assist you with any questions or requests. What can I do for you?",
        ],
        "emergency": "This sounds like an emergency. Please call the front desk immediately at extension 0 or dial 911. Our staff is available 24/7.",
        "task_created": "I've arranged {task_type} assistance for you. {staff_info}Your request will be handled {time_info}. Is there anything else I can help with?",
        "task_created_no_staff": "I've logged your {task_type} request. Our team will assist you shortly. Is there anything else?",
        "need_booking": "I'd be happy to help! To assist you with service requests, I'll need to verify your booking. Could you please provide your booking confirmation number?",
        "booking_found": "I found your booking:\n\n- Confirmation: {confirmation}\n- Room: {room}\n- Check-out: {checkout}\n\nHow can I assist you today?",
        "booking_not_found": "I couldn't find a booking with confirmation number '{booking_number}'. Please double-check the number or contact our front desk at extension 0.",
        "complaint_acknowledgment": "I'm truly sorry to hear about your experience. Your feedback is very important to us. I've escalated this to our management team who will reach out shortly.",
        "feedback_thanks": "Thank you so much for your kind feedback! We're delighted you're enjoying your stay. Is there anything else we can do for you?",
    }

    FAQ_THRESHOLD = 0.45

    def __init__(self, db: AsyncSession, current_user: Optional[User] = None):
        self.db = db
        self.current_user = current_user
        self.openai = OpenAIService()
        self.classifier = IntentClassifier(self.openai)
        self.faq_engine = FAQEngine()
        self.scheduling_service = get_scheduling_service(db)
        self.state_machine = state_machine
        # Session conversation contexts (in-memory, could be moved to DB)
        self._conversation_contexts: Dict[str, ConversationContext] = {}

    async def process_message(
        self,
        message: str,
        session_id: str,
        user_id: Optional[int] = None,
        guest_id: Optional[int] = None,
        room_number: Optional[str] = None,
        booking_number: Optional[str] = None
    ) -> ChatResponse:
        """Process a guest message and return appropriate response"""
        if not message or not message.strip():
            return ChatResponse(
                response="I'm here to help! Please send me a message.",
                intent="other",
                confidence=0.5
            )

        message = message.strip()

        # Get or create chat session
        session = await self._get_or_create_session(session_id, user_id, guest_id)
        session.last_activity = datetime.utcnow()

        # Check if message looks like a booking number first
        potential_booking = await self.openai.extract_booking_number(message)

        # Classify intent
        intent, confidence = await self.classifier.classify(message)
        logger.info(f"Classified '{message[:50]}...' as {intent.value} ({confidence:.2f})")

        # Override intent if booking number detected, but NOT for actions that USE the booking number
        # PRECHECKIN, BOOKING_MODIFY, BOOKING_CANCEL all need the booking number as context, not as lookup
        booking_action_intents = [
            MessageIntent.BOOKING_LOOKUP, MessageIntent.BOOKING_INQUIRY,
            MessageIntent.PRECHECKIN, MessageIntent.BOOKING_MODIFY, MessageIntent.BOOKING_CANCEL
        ]
        if potential_booking and intent not in booking_action_intents:
            intent = MessageIntent.BOOKING_LOOKUP
            confidence = 0.95

        # Build context for AI
        context = await self._build_context(session, user_id, guest_id, room_number)

        # Handle based on intent
        if intent == MessageIntent.GREETING:
            response = await self._handle_greeting(message, session, context)

        elif intent == MessageIntent.EMERGENCY:
            response = await self._handle_emergency(message, session, context)

        elif intent == MessageIntent.BOOKING_LOOKUP:
            response = await self._handle_booking_lookup(message, session, potential_booking, context)

        elif intent == MessageIntent.FAQ:
            response = await self._handle_faq(message, session, context)

        elif intent in [MessageIntent.HOUSEKEEPING, MessageIntent.MAINTENANCE,
                       MessageIntent.ROOM_SERVICE, MessageIntent.CONCIERGE]:
            response = await self._handle_service_request(
                message=message,
                intent=intent,
                session=session,
                room_number=room_number or session.room_number,
                booking_number=booking_number,
                context=context
            )

        elif intent == MessageIntent.BOOKING_INQUIRY:
            response = await self._handle_booking_inquiry(message, session, booking_number, context)

        elif intent == MessageIntent.COMPLAINT:
            response = await self._handle_complaint(message, session, context)

        elif intent == MessageIntent.FEEDBACK:
            response = await self._handle_feedback(message, session, context)

        # New comprehensive AGI intents
        elif intent == MessageIntent.ROOM_SEARCH:
            response = await self._handle_room_search(message, session, context)

        elif intent == MessageIntent.MAKE_BOOKING:
            response = await self._handle_make_booking(message, session, context)

        elif intent == MessageIntent.PRECHECKIN:
            response = await self._handle_precheckin(message, session, context, potential_booking or booking_number)

        elif intent == MessageIntent.PROFILE_VIEW:
            response = await self._handle_profile_view(message, session, context)

        elif intent == MessageIntent.PROFILE_UPDATE:
            response = await self._handle_profile_update(message, session, context)

        elif intent == MessageIntent.BOOKING_MODIFY:
            response = await self._handle_booking_modify(message, session, context, potential_booking or booking_number)

        elif intent == MessageIntent.BOOKING_CANCEL:
            response = await self._handle_booking_cancel(message, session, context, potential_booking or booking_number)

        elif intent == MessageIntent.MY_BOOKINGS:
            response = await self._handle_my_bookings(message, session, context)

        elif intent == MessageIntent.STAFF_HELP:
            response = await self._handle_staff_help(message, session, context)

        elif intent == MessageIntent.CAPABILITIES:
            response = await self._handle_capabilities(message, session, context)

        else:
            response = await self._handle_general(message, session, context)

        # Save conversation
        await self._save_conversation(
            session_id=session_id,
            user_query=message,
            bot_response=response.response,
            classification=intent.value,
            requires_staff_action=response.requires_staff_action,
            staff_task_id=response.staff_task_id,
            room_number=room_number or session.room_number,
            faq_id=response.faq_id
        )

        await self.db.commit()
        return response

    async def _build_context(
        self,
        session: GuestChatSession,
        user_id: Optional[int],
        guest_id: Optional[int],
        room_number: Optional[str]
    ) -> Dict[str, Any]:
        """
        Build comprehensive context for AI responses
        Includes guest profile, booking details, preferences, loyalty info, and stay history
        """
        context = {
            # Basic info
            "guest_name": None,
            "guest_first_name": None,
            "room_number": room_number or session.room_number,
            "booking_status": None,
            # Enhanced context
            "loyalty_tier": None,
            "loyalty_points": 0,
            "total_stays": 0,
            "is_vip": False,
            "is_repeat_guest": False,
            "check_in_date": None,
            "check_out_date": None,
            "nights_staying": 0,
            "room_type": None,
            "special_requests": None,
            "preferences": {},
            "has_active_booking": False,
            "is_checked_in": False,
            "current_time_of_day": self._get_time_of_day(),
            "guest_email": None,
            "guest_phone": None,
        }

        guest = None
        booking = None

        # Get guest info if available
        gid = guest_id or session.guest_id
        if gid:
            result = await self.db.exec(select(Guest).where(Guest.id == gid))
            guest = result.first()
            if guest:
                context["guest_name"] = f"{guest.first_name} {guest.last_name}"
                context["guest_first_name"] = guest.first_name
                context["guest_email"] = guest.email
                context["guest_phone"] = guest.phone

                # Loyalty information
                context["loyalty_tier"] = guest.loyalty_tier or "Standard"
                context["loyalty_points"] = guest.loyalty_points or 0
                context["total_stays"] = guest.total_bookings or 0  # Using total_bookings field
                context["is_vip"] = guest.vip_status or (guest.loyalty_tier in ["Gold", "Platinum", "Diamond"])
                context["is_repeat_guest"] = (guest.total_bookings or 0) > 1

                # Guest preferences (stored as JSON)
                if hasattr(guest, 'preferences') and guest.preferences:
                    try:
                        import json
                        if isinstance(guest.preferences, str):
                            context["preferences"] = json.loads(guest.preferences)
                        elif isinstance(guest.preferences, dict):
                            context["preferences"] = guest.preferences
                    except:
                        pass

                # Special requests
                if hasattr(guest, 'special_requests'):
                    context["special_requests"] = guest.special_requests

        # Get booking information
        if session.booking_id:
            # Try Booking table first
            result = await self.db.exec(select(Booking).where(Booking.id == session.booking_id))
            booking = result.first()
            if booking:
                context["booking_status"] = booking.status
                context["has_active_booking"] = booking.status in ["confirmed", "checked_in"]
                context["is_checked_in"] = booking.status == "checked_in"
                context["check_in_date"] = booking.arrival_date.isoformat() if booking.arrival_date else None
                context["check_out_date"] = booking.departure_date.isoformat() if booking.departure_date else None

                # Calculate nights
                if booking.arrival_date and booking.departure_date:
                    context["nights_staying"] = (booking.departure_date - booking.arrival_date).days

                # Get room type info
                if booking.room_type_id:
                    rt_result = await self.db.exec(select(RoomType).where(RoomType.id == booking.room_type_id))
                    room_type = rt_result.first()
                    if room_type:
                        context["room_type"] = room_type.name

                # Get guest from booking if not yet loaded
                if not guest and booking.guest_id:
                    guest_result = await self.db.exec(select(Guest).where(Guest.id == booking.guest_id))
                    guest = guest_result.first()
                    if guest:
                        context["guest_name"] = f"{guest.first_name} {guest.last_name}"
                        context["guest_first_name"] = guest.first_name
                        context["loyalty_tier"] = guest.loyalty_tier or "Standard"
                        context["loyalty_points"] = guest.loyalty_points or 0
                        context["is_vip"] = guest.vip_status or False
            else:
                # Try legacy Reservation table
                result = await self.db.exec(select(Reservation).where(Reservation.id == session.booking_id))
                reservation = result.first()
                if reservation:
                    status_map = {"booked": "confirmed", "checked_in": "checked_in"}
                    context["booking_status"] = status_map.get(reservation.status, reservation.status)
                    context["has_active_booking"] = reservation.status in ["booked", "checked_in"]
                    context["is_checked_in"] = reservation.status == "checked_in"
                    context["check_in_date"] = reservation.arrival_date.isoformat() if reservation.arrival_date else None
                    context["check_out_date"] = reservation.departure_date.isoformat() if reservation.departure_date else None

                    if reservation.arrival_date and reservation.departure_date:
                        context["nights_staying"] = (reservation.departure_date - reservation.arrival_date).days

                    # Get guest from reservation
                    if not guest and reservation.guest_id:
                        guest_result = await self.db.exec(select(Guest).where(Guest.id == reservation.guest_id))
                        guest = guest_result.first()
                        if guest:
                            context["guest_name"] = f"{guest.first_name} {guest.last_name}"
                            context["guest_first_name"] = guest.first_name

        # If still no guest but have current_user, try to find by user_id
        if not guest and self.current_user:
            result = await self.db.exec(select(Guest).where(Guest.user_id == self.current_user.id))
            guest = result.first()
            if guest:
                context["guest_name"] = f"{guest.first_name} {guest.last_name}"
                context["guest_first_name"] = guest.first_name
                context["guest_email"] = guest.email
                context["loyalty_tier"] = guest.loyalty_tier or "Standard"
                context["loyalty_points"] = guest.loyalty_points or 0
                context["total_stays"] = guest.total_stays or 0
                context["is_repeat_guest"] = (guest.total_stays or 0) > 1

        return context

    def _get_time_of_day(self) -> str:
        """Get current time of day for contextual responses"""
        from datetime import datetime
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"

    async def _get_or_create_session(
        self, session_id: str, user_id: Optional[int], guest_id: Optional[int]
    ) -> GuestChatSession:
        """Get existing session or create new one"""
        result = await self.db.exec(
            select(GuestChatSession).where(GuestChatSession.session_id == session_id)
        )
        session = result.first()

        if not session:
            session = GuestChatSession(
                session_id=session_id,
                user_id=user_id,
                guest_id=guest_id,
                status="active"
            )
            self.db.add(session)
            await self.db.commit()
            await self.db.refresh(session)

        return session

    async def _handle_greeting(self, message: str, session: GuestChatSession, context: Dict) -> ChatResponse:
        """Handle greeting messages with context-aware proactive suggestions"""
        # Generate proactive suggestions based on context
        quick_actions = self._generate_proactive_suggestions(context)

        if self.openai.is_available:
            ai_response = await self.openai.generate_response(message, "GREETING", context)
            if ai_response:
                return ChatResponse(
                    response=ai_response,
                    intent="greeting",
                    confidence=0.95,
                    quick_actions=quick_actions
                )

        # Build personalized greeting
        import random
        time_of_day = context.get("current_time_of_day", "day")
        time_greetings = {
            "morning": "Good morning",
            "afternoon": "Good afternoon",
            "evening": "Good evening",
            "night": "Hello"
        }

        greeting = time_greetings.get(time_of_day, "Hello")
        first_name = context.get("guest_first_name")

        if first_name:
            if context.get("is_repeat_guest"):
                response_text = f"{greeting}, {first_name}! Welcome back to Glimmora Hotel & Suites. It's wonderful to have you staying with us again. How may I assist you today?"
            elif context.get("is_vip"):
                tier = context.get("loyalty_tier", "VIP")
                response_text = f"{greeting}, {first_name}! Welcome to Glimmora Hotel & Suites. As our valued {tier} member, we're here to make your stay exceptional. How can I help you?"
            else:
                response_text = f"{greeting}, {first_name}! Welcome to Glimmora Hotel & Suites. I'm Aria, your AI concierge. How may I assist you today?"
        else:
            response_text = f"{greeting}! Welcome to Glimmora Hotel & Suites. I'm Aria, your AI concierge. I can help with housekeeping, maintenance, room service, and more. How may I assist you today?"

        return ChatResponse(
            response=response_text,
            intent="greeting",
            confidence=0.95,
            quick_actions=quick_actions
        )

    def _generate_proactive_suggestions(self, context: Dict) -> List[Dict[str, str]]:
        """Generate contextual quick action suggestions based on guest context"""
        suggestions = []
        time_of_day = context.get("current_time_of_day", "day")
        is_checked_in = context.get("is_checked_in", False)
        has_booking = context.get("has_active_booking", False)

        # Time-based suggestions
        if time_of_day == "morning":
            suggestions.append({"label": "Breakfast Info", "action": "breakfast_info"})
        elif time_of_day == "evening":
            suggestions.append({"label": "Turndown Service", "action": "turndown"})
            suggestions.append({"label": "Dinner Options", "action": "room_service"})
        elif time_of_day == "night":
            suggestions.append({"label": "Room Service", "action": "room_service"})

        # Status-based suggestions
        if is_checked_in:
            # Guest is checked in - offer service options
            if len(suggestions) < 4:
                suggestions.append({"label": "Housekeeping", "action": "housekeeping"})
            if len(suggestions) < 4:
                suggestions.append({"label": "Report Issue", "action": "maintenance"})
        elif has_booking and not is_checked_in:
            # Has booking but not checked in - likely pre-arrival
            suggestions.append({"label": "Pre-Check-in", "action": "precheckin"})
            suggestions.append({"label": "My Booking", "action": "booking_inquiry"})
        else:
            # No booking - offer to help find one
            suggestions.append({"label": "Book Room", "action": "room_search"})
            suggestions.append({"label": "Hotel Info", "action": "faq"})

        # VIP/Loyalty suggestions
        if context.get("is_vip") or context.get("loyalty_tier") in ["Gold", "Platinum", "Diamond"]:
            if len(suggestions) < 4:
                suggestions.append({"label": "Spa & Wellness", "action": "spa_wellness"})

        # Always include these if space
        if len(suggestions) < 4 and {"label": "Hotel Info", "action": "faq"} not in suggestions:
            suggestions.append({"label": "Hotel Info", "action": "faq"})

        # Limit to 4 suggestions
        return suggestions[:4]

    async def _handle_emergency(self, message: str, session: GuestChatSession, context: Dict) -> ChatResponse:
        """Handle emergency situations"""
        task, staff = await self.scheduling_service.create_and_assign_task(
            task_type="other",
            title="EMERGENCY - Immediate attention required",
            description=f"Emergency request: {message}",
            priority="urgent",
            room_number=session.room_number,
            guest_id=session.guest_id
        )

        if staff:
            await self._send_staff_notification_email(
                staff_email=staff.email,
                staff_name=staff.staff_name,
                task_type="EMERGENCY",
                room_number=session.room_number,
                priority="urgent",
                description=message
            )

        return ChatResponse(
            response=self.TEMPLATES["emergency"],
            intent="emergency",
            confidence=0.99,
            requires_staff_action=True,
            staff_task_id=task.id if task else None,
            task_type="emergency"
        )

    async def _handle_booking_lookup(
        self, message: str, session: GuestChatSession,
        booking_number: Optional[str], context: Dict
    ) -> ChatResponse:
        """Handle booking number lookup"""
        # Extract booking number
        if not booking_number:
            booking_number = await self.openai.extract_booking_number(message)

        if not booking_number:
            return ChatResponse(
                response="I couldn't find a booking number in your message. Please provide your confirmation number (e.g., GLM-XXX123).",
                intent="booking_lookup",
                confidence=0.7
            )

        # Look up booking
        booking_info = await self.lookup_booking(booking_number)

        if booking_info:
            # Update session with booking info
            session.booking_id = booking_info["id"]
            session.guest_id = booking_info.get("guest_id")
            if booking_info.get("room_number"):
                session.room_number = booking_info["room_number"]

            response_text = self.TEMPLATES["booking_found"].format(
                confirmation=booking_info["confirmation_code"],
                room=booking_info.get("room_number") or "Not yet assigned",
                checkout=booking_info["departure_date"]
            )

            # Build quick actions based on booking status
            quick_actions = []

            # Add Pre-Checkin if booking is eligible (not yet checked in)
            if booking_info["status"] in ["booked", "confirmed", "pending"]:
                quick_actions.append({"label": "Pre-Checkin", "action": "precheckin"})

            # Add service options if checked in or has room assigned
            if booking_info.get("room_number") or booking_info["status"] == "checked_in":
                quick_actions.extend([
                    {"label": "Housekeeping", "action": "housekeeping"},
                    {"label": "Maintenance", "action": "maintenance"},
                    {"label": "Room Service", "action": "room_service"}
                ])
            else:
                quick_actions.append({"label": "Contact Front Desk", "action": "front_desk"})

            return ChatResponse(
                response=response_text,
                intent="booking_lookup",
                confidence=0.95,
                booking_info={
                    "confirmation_code": booking_info["confirmation_code"],
                    "room_number": booking_info.get("room_number"),
                    "guest_name": booking_info.get("guest_name"),
                    "checkout": booking_info["departure_date"],
                    "status": booking_info["status"]
                },
                quick_actions=quick_actions
            )
        else:
            return ChatResponse(
                response=self.TEMPLATES["booking_not_found"].format(booking_number=booking_number),
                intent="booking_lookup",
                confidence=0.8,
                quick_actions=[
                    {"label": "Try Again", "action": "enter_booking"},
                    {"label": "Contact Front Desk", "action": "front_desk"}
                ]
            )

    async def _handle_faq(self, message: str, session: GuestChatSession, context: Dict) -> ChatResponse:
        """Handle FAQ queries"""
        # Try AI response first
        if self.openai.is_available:
            ai_response = await self.openai.generate_response(message, "FAQ", context)
            if ai_response:
                return ChatResponse(
                    response=ai_response,
                    intent="faq",
                    confidence=0.85
                )

        # Fallback to FAQ search
        results = self.faq_engine.search(message, top_k=3)

        if results and results[0][1] >= self.FAQ_THRESHOLD:
            best_faq, score = results[0]
            return ChatResponse(
                response=best_faq["answer"],
                intent="faq",
                confidence=score,
                faq_id=best_faq["id"]
            )

        return ChatResponse(
            response="I'm not sure about that. Would you like me to connect you with our front desk for more information?",
            intent="faq",
            confidence=0.3,
            quick_actions=[
                {"label": "Contact Front Desk", "action": "front_desk"},
                {"label": "Hotel Amenities", "action": "faq"}
            ]
        )

    async def _handle_service_request(
        self, message: str, intent: MessageIntent, session: GuestChatSession,
        room_number: Optional[str], booking_number: Optional[str], context: Dict
    ) -> ChatResponse:
        """Handle service requests with proper authentication and authorization"""

        # INTEGRITY CHECK 1: Require authentication for service requests
        if not session.user_id and not session.guest_id:
            logger.warning(f"Unauthenticated service request attempt: {message[:50]}...")
            return ChatResponse(
                response="To request hotel services, please log in to your account first. This helps us verify your booking and provide you with the best service.",
                intent=intent.value,
                confidence=0.9,
                requires_auth=True,
                auth_error="Authentication required for service requests",
                quick_actions=[
                    {"label": "Log In", "action": "login"},
                    {"label": "Contact Front Desk", "action": "front_desk"}
                ]
            )

        final_room = room_number

        # INTEGRITY CHECK 2: Validate booking ownership if booking_number provided
        if booking_number and not session.booking_id:
            is_authorized, booking_data = await self._validate_booking_ownership(
                booking_number, session.user_id, session.guest_id
            )
            if not is_authorized:
                logger.warning(
                    f"Unauthorized booking access attempt: {booking_number} by user:{session.user_id}/guest:{session.guest_id}"
                )
                return ChatResponse(
                    response="I couldn't verify your access to this booking. Please ensure you're logged into the correct account or contact our front desk for assistance.",
                    intent=intent.value,
                    confidence=0.9,
                    requires_auth=True,
                    auth_error="Not authorized to access this booking",
                    quick_actions=[
                        {"label": "Try Another Booking", "action": "enter_booking"},
                        {"label": "Contact Front Desk", "action": "front_desk"}
                    ]
                )
            # Use validated booking info
            booking_info = await self.lookup_booking(booking_number)
            if booking_info:
                session.booking_id = booking_info["id"]
                session.guest_id = booking_info.get("guest_id")
                if booking_info.get("room_number"):
                    final_room = booking_info["room_number"]
                    session.room_number = final_room

        # INTEGRITY CHECK 3: Validate room ownership if room_number provided directly
        if room_number and not session.booking_id:
            is_authorized, booking_data = await self._validate_room_ownership(
                room_number, session.user_id, session.guest_id
            )
            if not is_authorized:
                logger.warning(
                    f"Unauthorized room access attempt: {room_number} by user:{session.user_id}/guest:{session.guest_id}"
                )
                return ChatResponse(
                    response="I couldn't verify your booking for this room. Please provide your booking confirmation number so I can assist you.",
                    intent=intent.value,
                    confidence=0.9,
                    requires_auth=True,
                    auth_error="Room not associated with your booking",
                    quick_actions=[
                        {"label": "Enter Booking Number", "action": "enter_booking"},
                        {"label": "Contact Front Desk", "action": "front_desk"}
                    ]
                )
            # Use validated booking info
            if booking_data:
                session.booking_id = booking_data["id"]
                session.guest_id = booking_data["guest_id"]

        # Try to get room from booking if not provided
        if not final_room and session.booking_id:
            # Check Booking table first
            result = await self.db.exec(
                select(Booking).where(Booking.id == session.booking_id)
            )
            booking = result.first()
            if booking and booking.room_id:
                room_result = await self.db.exec(select(Room).where(Room.id == booking.room_id))
                room = room_result.first()
                if room:
                    final_room = room.number
                    session.room_number = final_room
            else:
                # Try Reservation table
                result = await self.db.exec(
                    select(Reservation).where(Reservation.id == session.booking_id)
                )
                reservation = result.first()
                if reservation and reservation.room_id:
                    room_result = await self.db.exec(select(Room).where(Room.id == reservation.room_id))
                    room = room_result.first()
                    if room:
                        final_room = room.number
                        session.room_number = final_room

        # If still no room, check if we need to ask for booking
        if not final_room and not session.booking_id:
            # Check for active booking
            booking = await self._find_active_booking(session.user_id, session.guest_id, booking_number)
            if not booking:
                return ChatResponse(
                    response=self.TEMPLATES["need_booking"],
                    intent=intent.value,
                    confidence=0.8,
                    quick_actions=[
                        {"label": "Enter Booking Number", "action": "enter_booking"},
                        {"label": "Contact Front Desk", "action": "front_desk"}
                    ]
                )
            else:
                session.booking_id = booking.id
                session.guest_id = booking.guest_id
                if booking.room_id:
                    room_result = await self.db.exec(select(Room).where(Room.id == booking.room_id))
                    room = room_result.first()
                    if room:
                        final_room = room.number
                        session.room_number = final_room

        # Rebuild context with updated session info (guest_id, room, etc.)
        context = await self._build_context(session, session.user_id, session.guest_id, final_room)

        # Extract task details with advanced classification
        task_info = self._extract_task_info(message, intent)

        # Log detailed classification
        logger.info(
            f"Task classification - Type: {task_info['task_type']}, "
            f"Category: {task_info.get('category', 'N/A')}, "
            f"Priority: {task_info['priority']}, "
            f"Skills: {task_info.get('required_skills', 'N/A')}"
        )

        # Create and assign task with required skills
        task, assigned_staff = await self.scheduling_service.create_and_assign_task(
            task_type=task_info["task_type"],
            title=task_info["title"],
            description=task_info["description"],
            priority=task_info["priority"],
            room_number=final_room,
            booking_id=session.booking_id,
            guest_id=session.guest_id,
            required_skills=task_info.get("required_skills")
        )

        # Send email notification
        if assigned_staff:
            await self._send_staff_notification_email(
                staff_email=assigned_staff.email,
                staff_name=assigned_staff.staff_name,
                task_type=task_info["task_type"],
                room_number=final_room,
                priority=task_info["priority"],
                description=task_info["description"]
            )

        # Get staff role if assigned
        staff_role = None
        if assigned_staff:
            staff_role = getattr(assigned_staff, 'role', None) or getattr(assigned_staff, 'department', None)

        # Generate response with updated context
        if self.openai.is_available:
            ai_response = await self.openai.generate_response(
                message, intent.value.upper(),
                {**context, "room_number": final_room, "task_created": True,
                 "assigned_staff": assigned_staff.staff_name if assigned_staff else None}
            )
            if ai_response:
                return ChatResponse(
                    response=ai_response,
                    intent=intent.value,
                    confidence=0.9,
                    requires_staff_action=True,
                    staff_task_id=task.id if task else None,
                    task_type=task_info["task_type"],
                    assigned_staff_name=assigned_staff.staff_name if assigned_staff else None,
                    estimated_response_time=self._get_response_minutes(task_info["priority"]),
                    # Enhanced task details
                    task_priority=task_info["priority"],
                    task_title=task_info.get("title"),
                    task_description=task_info.get("description"),
                    task_category=task_info.get("category"),
                    detected_issue=task_info.get("detected_issue"),
                    required_skills=task_info.get("required_skills"),
                    assigned_staff_role=staff_role
                )

        # Fallback response
        if assigned_staff:
            staff_info = f"Our team member {assigned_staff.staff_name} has been assigned. "
            time_info = self._get_estimated_time(task_info["priority"])
            response_text = self.TEMPLATES["task_created"].format(
                task_type=task_info["task_type"].replace("_", " "),
                staff_info=staff_info,
                time_info=time_info
            )
        else:
            response_text = self.TEMPLATES["task_created_no_staff"].format(
                task_type=task_info["task_type"].replace("_", " ")
            )

        return ChatResponse(
            response=response_text,
            intent=intent.value,
            confidence=0.9,
            requires_staff_action=True,
            staff_task_id=task.id if task else None,
            task_type=task_info["task_type"],
            assigned_staff_name=assigned_staff.staff_name if assigned_staff else None,
            estimated_response_time=self._get_response_minutes(task_info["priority"]),
            # Enhanced task details
            task_priority=task_info["priority"],
            task_title=task_info.get("title"),
            task_description=task_info.get("description"),
            task_category=task_info.get("category"),
            detected_issue=task_info.get("detected_issue"),
            required_skills=task_info.get("required_skills"),
            assigned_staff_role=staff_role
        )

    async def _handle_booking_inquiry(
        self, message: str, session: GuestChatSession,
        booking_number: Optional[str], context: Dict
    ) -> ChatResponse:
        """Handle booking-related inquiries"""
        if self.openai.is_available:
            ai_response = await self.openai.generate_response(message, "BOOKING_INQUIRY", context)
            if ai_response:
                return ChatResponse(
                    response=ai_response,
                    intent="booking_inquiry",
                    confidence=0.85
                )

        return ChatResponse(
            response="For booking modifications, check-in/out time changes, or other reservation inquiries, please contact our front desk at extension 0 or visit the lobby.",
            intent="booking_inquiry",
            confidence=0.7
        )

    async def _handle_complaint(self, message: str, session: GuestChatSession, context: Dict) -> ChatResponse:
        """Handle complaints"""
        task, staff = await self.scheduling_service.create_and_assign_task(
            task_type="other",
            title="Guest Complaint - Management Attention Required",
            description=f"Complaint: {message}",
            priority="high",
            room_number=session.room_number,
            guest_id=session.guest_id
        )

        if staff:
            await self._send_staff_notification_email(
                staff_email=staff.email,
                staff_name=staff.staff_name,
                task_type="COMPLAINT",
                room_number=session.room_number,
                priority="high",
                description=message
            )

        if self.openai.is_available:
            ai_response = await self.openai.generate_response(message, "COMPLAINT", context)
            if ai_response:
                return ChatResponse(
                    response=ai_response,
                    intent="complaint",
                    confidence=0.85,
                    requires_staff_action=True,
                    staff_task_id=task.id if task else None,
                    task_type="complaint"
                )

        return ChatResponse(
            response=self.TEMPLATES["complaint_acknowledgment"],
            intent="complaint",
            confidence=0.85,
            requires_staff_action=True,
            staff_task_id=task.id if task else None,
            task_type="complaint"
        )

    async def _handle_feedback(self, message: str, session: GuestChatSession, context: Dict) -> ChatResponse:
        """Handle positive feedback"""
        if self.openai.is_available:
            ai_response = await self.openai.generate_response(message, "FEEDBACK", context)
            if ai_response:
                return ChatResponse(response=ai_response, intent="feedback", confidence=0.9)

        return ChatResponse(
            response=self.TEMPLATES["feedback_thanks"],
            intent="feedback",
            confidence=0.9
        )

    async def _handle_general(self, message: str, session: GuestChatSession, context: Dict) -> ChatResponse:
        """Handle general/unclear messages"""
        # Try AI first
        if self.openai.is_available:
            ai_response = await self.openai.generate_response(message, "GENERAL", context)
            if ai_response:
                return ChatResponse(
                    response=ai_response,
                    intent="general",
                    confidence=0.7,
                    quick_actions=[
                        {"label": "Housekeeping", "action": "housekeeping"},
                        {"label": "Room Service", "action": "room_service"},
                        {"label": "Hotel Info", "action": "faq"}
                    ]
                )

        # Try FAQ as fallback
        results = self.faq_engine.search(message, top_k=1)
        if results and results[0][1] >= 0.4:
            return ChatResponse(
                response=results[0][0]["answer"],
                intent="faq",
                confidence=results[0][1],
                faq_id=results[0][0]["id"]
            )

        return ChatResponse(
            response="I'm here to help with housekeeping, maintenance, room service, or answer questions about the hotel. What would you like assistance with?",
            intent="general",
            confidence=0.5,
            quick_actions=[
                {"label": "Housekeeping", "action": "housekeeping"},
                {"label": "Maintenance", "action": "maintenance"},
                {"label": "Room Service", "action": "room_service"},
                {"label": "Contact Front Desk", "action": "front_desk"}
            ]
        )

    # Detailed issue classification for intelligent task routing
    ISSUE_CLASSIFICATIONS = {
        # Plumbing issues
        "plumbing": {
            "keywords": ["shower", "toilet", "sink", "faucet", "drain", "clog", "leak", "water", "pipe", "bathroom", "tub", "bathtub", "plumbing", "flooding", "flooded", "dripping"],
            "task_type": "maintenance",
            "required_skills": ["plumbing"],
            "base_priority": "high",
            "category": "Plumbing Issue",
            "urgent_triggers": ["flooding", "flooded", "burst", "no water", "sewage", "overflow"]
        },
        # HVAC issues
        "hvac": {
            "keywords": ["ac", "air conditioning", "a/c", "heating", "heater", "thermostat", "temperature", "cold", "hot", "fan", "ventilation", "hvac", "climate"],
            "task_type": "maintenance",
            "required_skills": ["hvac"],
            "base_priority": "high",
            "category": "HVAC Issue",
            "urgent_triggers": ["freezing", "too hot", "no ac", "no heat", "smoke from ac"]
        },
        # Electrical issues
        "electrical": {
            "keywords": ["light", "bulb", "lamp", "outlet", "socket", "switch", "power", "electricity", "electrical", "sparking", "flickering", "blackout"],
            "task_type": "maintenance",
            "required_skills": ["electrical"],
            "base_priority": "normal",
            "category": "Electrical Issue",
            "urgent_triggers": ["sparking", "smoke", "burning smell", "blackout", "no power", "shock"]
        },
        # TV/Entertainment issues
        "tv_entertainment": {
            "keywords": ["tv", "television", "remote", "cable", "channel", "streaming", "netflix", "chromecast", "hdmi", "entertainment"],
            "task_type": "maintenance",
            "required_skills": ["electrical"],
            "base_priority": "normal",
            "category": "Entertainment System Issue",
            "urgent_triggers": []
        },
        # WiFi/Internet issues
        "wifi": {
            "keywords": ["wifi", "wi-fi", "internet", "network", "connection", "slow internet", "can't connect", "no wifi", "password"],
            "task_type": "maintenance",
            "required_skills": ["it_support"],
            "base_priority": "high",
            "category": "WiFi/Internet Issue",
            "urgent_triggers": ["no wifi", "no internet", "business meeting", "urgent work"]
        },
        # Door/Lock issues
        "door_lock": {
            "keywords": ["door", "lock", "key", "keycard", "card not working", "locked out", "stuck", "latch", "deadbolt", "safe", "safe box"],
            "task_type": "maintenance",
            "required_skills": ["locksmith", "general"],
            "base_priority": "urgent",
            "category": "Door/Lock Issue",
            "urgent_triggers": ["locked out", "can't get in", "safety", "broken lock"]
        },
        # Furniture issues
        "furniture": {
            "keywords": ["bed", "mattress", "chair", "table", "desk", "furniture", "drawer", "closet", "wardrobe", "curtain", "blind", "broken furniture"],
            "task_type": "maintenance",
            "required_skills": ["carpentry", "general"],
            "base_priority": "normal",
            "category": "Furniture Issue",
            "urgent_triggers": ["bed broken", "can't sleep"]
        },
        # Housekeeping - cleaning
        "cleaning": {
            "keywords": ["clean", "dirty", "mess", "stain", "spill", "vacuum", "dust", "trash", "garbage", "mop", "sanitize"],
            "task_type": "housekeeping",
            "required_skills": ["cleaning"],
            "base_priority": "normal",
            "category": "Room Cleaning",
            "urgent_triggers": ["urgent clean", "spill", "accident", "vomit", "blood"]
        },
        # Housekeeping - supplies
        "supplies": {
            "keywords": ["towel", "towels", "sheets", "linen", "bedding", "pillow", "blanket", "toiletries", "soap", "shampoo", "tissue", "toilet paper", "minibar"],
            "task_type": "housekeeping",
            "required_skills": ["housekeeping"],
            "base_priority": "normal",
            "category": "Room Supplies",
            "urgent_triggers": ["no towels", "no toilet paper"]
        },
        # Turndown service
        "turndown": {
            "keywords": ["turndown", "turn down", "evening service", "night service"],
            "task_type": "housekeeping",
            "required_skills": ["turndown"],
            "base_priority": "normal",
            "category": "Turndown Service",
            "urgent_triggers": []
        },
        # Room service - food
        "food_order": {
            "keywords": ["hungry", "food", "eat", "meal", "breakfast", "lunch", "dinner", "snack", "order food", "room service menu", "menu"],
            "task_type": "room_service",
            "required_skills": ["food_service"],
            "base_priority": "normal",
            "category": "Food Order",
            "urgent_triggers": ["starving", "diabetic", "medication with food"]
        },
        # Room service - drinks
        "beverage_order": {
            "keywords": ["drink", "water", "coffee", "tea", "juice", "soda", "alcohol", "wine", "beer", "cocktail", "ice"],
            "task_type": "room_service",
            "required_skills": ["food_service"],
            "base_priority": "normal",
            "category": "Beverage Order",
            "urgent_triggers": ["dehydrated", "medication"]
        },
        # Concierge - transportation
        "transportation": {
            "keywords": ["taxi", "cab", "uber", "lyft", "car", "ride", "airport", "shuttle", "transportation", "pickup", "drop off", "driver"],
            "task_type": "concierge",
            "required_skills": ["concierge"],
            "base_priority": "normal",
            "category": "Transportation Request",
            "urgent_triggers": ["flight", "urgent", "emergency", "hospital"]
        },
        # Concierge - recommendations
        "recommendations": {
            "keywords": ["recommend", "suggestion", "where to eat", "restaurant", "attraction", "sightseeing", "tour", "shopping", "things to do"],
            "task_type": "concierge",
            "required_skills": ["concierge", "local_knowledge"],
            "base_priority": "low",
            "category": "Recommendations",
            "urgent_triggers": []
        },
        # Concierge - spa/wellness
        "spa_wellness": {
            "keywords": ["spa", "massage", "facial", "treatment", "wellness", "gym", "fitness", "pool", "sauna", "steam"],
            "task_type": "concierge",
            "required_skills": ["concierge"],
            "base_priority": "normal",
            "category": "Spa/Wellness Booking",
            "urgent_triggers": []
        },
        # Pest issues
        "pest": {
            "keywords": ["bug", "insect", "cockroach", "ant", "spider", "mouse", "rat", "pest", "fly", "mosquito", "bed bugs"],
            "task_type": "maintenance",
            "required_skills": ["pest_control", "housekeeping"],
            "base_priority": "urgent",
            "category": "Pest Issue",
            "urgent_triggers": ["bed bugs", "multiple", "infestation"]
        },
        # Noise complaint
        "noise": {
            "keywords": ["noise", "loud", "noisy", "neighbor", "party", "music", "construction", "quiet", "disturbance", "can't sleep"],
            "task_type": "concierge",
            "required_skills": ["front_desk", "security"],
            "base_priority": "high",
            "category": "Noise Complaint",
            "urgent_triggers": ["can't sleep", "all night", "excessive"]
        },
        # Safety/Security
        "safety": {
            "keywords": ["safety", "security", "suspicious", "theft", "stolen", "lost", "found", "stranger", "harassment"],
            "task_type": "other",
            "required_skills": ["security"],
            "base_priority": "urgent",
            "category": "Safety/Security Concern",
            "urgent_triggers": ["theft", "stolen", "harassment", "threat", "suspicious person"]
        }
    }

    def _extract_task_info(self, message: str, intent: MessageIntent) -> Dict[str, Any]:
        """
        Advanced task extraction with intelligent issue classification
        Detects specific issues, required skills, and appropriate priority
        """
        msg_lower = message.lower()

        intent_to_task = {
            MessageIntent.HOUSEKEEPING: "housekeeping",
            MessageIntent.MAINTENANCE: "maintenance",
            MessageIntent.ROOM_SERVICE: "room_service",
            MessageIntent.CONCIERGE: "concierge"
        }
        default_task_type = intent_to_task.get(intent, "other")

        # Detect specific issue classification
        detected_issue = self._classify_issue(msg_lower)

        if detected_issue:
            task_type = detected_issue["task_type"]
            required_skills = detected_issue["required_skills"]
            category = detected_issue["category"]
            base_priority = detected_issue["base_priority"]

            # Check for urgent triggers
            priority = base_priority
            for trigger in detected_issue.get("urgent_triggers", []):
                if trigger in msg_lower:
                    priority = "urgent"
                    break
        else:
            task_type = default_task_type
            required_skills = None
            category = task_type.replace("_", " ").title()
            priority = "normal"

        # Override priority based on explicit urgency keywords
        if any(kw in msg_lower for kw in ["urgent", "emergency", "immediately", "asap", "right now", "help"]):
            priority = "urgent"
        elif any(kw in msg_lower for kw in ["soon", "quickly", "fast", "when possible"]):
            if priority == "normal":
                priority = "high"
        elif any(kw in msg_lower for kw in ["whenever", "no rush", "when convenient", "later", "tomorrow"]):
            priority = "low"

        # Check for "broken" or "not working" patterns to boost priority
        if any(pattern in msg_lower for pattern in ["broken", "not working", "doesn't work", "won't work", "stopped working", "malfunctioning"]):
            if priority == "normal":
                priority = "high"

        # Generate descriptive title based on category
        title = self._generate_task_title(category, message, msg_lower)

        # Generate detailed description
        description = self._generate_task_description(message, category, detected_issue)

        return {
            "task_type": task_type,
            "priority": priority,
            "title": title,
            "description": description,
            "required_skills": required_skills,
            "category": category,
            "detected_issue": detected_issue["keywords"][0] if detected_issue else None
        }

    def _classify_issue(self, message: str) -> Optional[Dict[str, Any]]:
        """Classify the issue based on keywords with scoring"""
        best_match = None
        best_score = 0

        for issue_type, config in self.ISSUE_CLASSIFICATIONS.items():
            score = 0
            matched_keywords = []

            for keyword in config["keywords"]:
                if keyword in message:
                    # Longer keywords get higher scores
                    score += len(keyword.split())
                    matched_keywords.append(keyword)

            if score > best_score:
                best_score = score
                best_match = {**config, "matched_keywords": matched_keywords, "issue_type": issue_type}

        return best_match if best_score > 0 else None

    def _generate_task_title(self, category: str, message: str, msg_lower: str) -> str:
        """Generate a descriptive task title"""
        # Extract specific items mentioned
        specific_items = []

        # Common items to detect
        items_to_check = [
            "shower", "toilet", "sink", "faucet", "ac", "air conditioning", "heater",
            "tv", "light", "lamp", "wifi", "internet", "door", "lock", "keycard",
            "bed", "mattress", "towels", "sheets", "remote", "safe", "minibar"
        ]

        for item in items_to_check:
            if item in msg_lower:
                specific_items.append(item)

        if specific_items:
            items_str = ", ".join(specific_items[:2])  # Max 2 items in title

            # Determine issue type
            if any(word in msg_lower for word in ["broken", "not working", "doesn't work"]):
                return f"{category}: {items_str.title()} Not Working"
            elif any(word in msg_lower for word in ["leak", "leaking", "dripping"]):
                return f"{category}: {items_str.title()} Leaking"
            elif any(word in msg_lower for word in ["need", "request", "want", "missing"]):
                return f"{category}: {items_str.title()} Request"
            else:
                return f"{category}: {items_str.title()} Issue"

        # Fallback to first 60 chars of message
        return f"{category}: {message[:60]}{'...' if len(message) > 60 else ''}"

    def _generate_task_description(self, message: str, category: str, detected_issue: Optional[Dict]) -> str:
        """Generate detailed task description with context"""
        description_parts = [
            f"Guest Request: {message}",
            f"Category: {category}"
        ]

        if detected_issue:
            if detected_issue.get("matched_keywords"):
                description_parts.append(f"Detected Issues: {', '.join(detected_issue['matched_keywords'])}")

            # Add skill requirements note
            if detected_issue.get("required_skills"):
                skills = ", ".join(detected_issue["required_skills"])
                description_parts.append(f"Recommended Skills: {skills}")

        return "\n".join(description_parts)

    def _get_estimated_time(self, priority: str) -> str:
        """Get estimated response time text"""
        times = {
            "urgent": "within 10-15 minutes",
            "high": "within 20-30 minutes",
            "normal": "within the hour",
            "low": "at the earliest convenience"
        }
        return times.get(priority, "shortly")

    def _get_response_minutes(self, priority: str) -> int:
        """Get estimated response time in minutes"""
        return {"urgent": 15, "high": 30, "normal": 60, "low": 120}.get(priority, 60)

    async def _validate_booking_ownership(
        self, booking_number: str, user_id: Optional[int], guest_id: Optional[int]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Validate that the user/guest owns the booking.
        Returns (is_authorized, booking_info) tuple.
        """
        if not booking_number:
            return False, None

        clean_number = booking_number.strip().upper()

        # Look up the booking
        result = await self.db.exec(
            select(Booking).where(
                or_(
                    Booking.booking_number == clean_number,
                    Booking.confirmation_code == clean_number
                )
            )
        )
        booking = result.first()

        if not booking:
            # Try legacy Reservation table
            result = await self.db.exec(
                select(Reservation).where(
                    Reservation.confirmation_code == clean_number
                )
            )
            reservation = result.first()
            if not reservation:
                return False, None

            # Validate ownership for Reservation
            is_owner = False
            if guest_id and reservation.guest_id == guest_id:
                is_owner = True
            elif user_id:
                guest_result = await self.db.exec(select(Guest).where(Guest.user_id == user_id))
                user_guest = guest_result.first()
                if user_guest and reservation.guest_id == user_guest.id:
                    is_owner = True

            if is_owner:
                return True, {"id": reservation.id, "guest_id": reservation.guest_id, "type": "reservation"}
            return False, None

        # Validate ownership for Booking
        is_owner = False
        if guest_id and booking.guest_id == guest_id:
            is_owner = True
        elif user_id:
            # Check if user is linked to the booking's guest
            guest_result = await self.db.exec(select(Guest).where(Guest.user_id == user_id))
            user_guest = guest_result.first()
            if user_guest and booking.guest_id == user_guest.id:
                is_owner = True
            # Also check if user_id directly matches booking's user_id
            elif booking.user_id and booking.user_id == user_id:
                is_owner = True

        if is_owner:
            return True, {"id": booking.id, "guest_id": booking.guest_id, "type": "booking"}
        return False, None

    async def _validate_room_ownership(
        self, room_number: str, user_id: Optional[int], guest_id: Optional[int]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Validate that the user/guest has an active booking for the room.
        Returns (is_authorized, booking_info) tuple.
        """
        if not room_number:
            return False, None

        today = date_type.today()

        # Find the room
        room_result = await self.db.exec(select(Room).where(Room.number == room_number))
        room = room_result.first()
        if not room:
            return False, None

        # Check if there's an active booking for this room owned by the user/guest
        if guest_id:
            result = await self.db.exec(
                select(Booking).where(
                    and_(
                        Booking.room_id == room.id,
                        Booking.guest_id == guest_id,
                        Booking.status.in_(["confirmed", "checked_in"]),
                        Booking.arrival_date <= today,
                        Booking.departure_date >= today
                    )
                )
            )
            booking = result.first()
            if booking:
                return True, {"id": booking.id, "guest_id": booking.guest_id}

        if user_id:
            # Get guest linked to user
            guest_result = await self.db.exec(select(Guest).where(Guest.user_id == user_id))
            user_guest = guest_result.first()
            if user_guest:
                result = await self.db.exec(
                    select(Booking).where(
                        and_(
                            Booking.room_id == room.id,
                            Booking.guest_id == user_guest.id,
                            Booking.status.in_(["confirmed", "checked_in"]),
                            Booking.arrival_date <= today,
                            Booking.departure_date >= today
                        )
                    )
                )
                booking = result.first()
                if booking:
                    return True, {"id": booking.id, "guest_id": booking.guest_id}

        return False, None

    async def _find_active_booking(
        self, user_id: Optional[int], guest_id: Optional[int], booking_number: Optional[str]
    ) -> Optional[Any]:
        """Find an active booking for the guest - checks both Booking and Reservation tables"""
        today = date_type.today()

        # First try new Booking table
        if booking_number:
            result = await self.db.exec(
                select(Booking).where(
                    and_(
                        or_(
                            Booking.confirmation_code == booking_number.upper(),
                            Booking.booking_number == booking_number.upper()
                        ),
                        Booking.status.in_(["confirmed", "checked_in"])
                    )
                )
            )
            booking = result.first()
            if booking:
                return booking

            # Try legacy Reservation table
            result = await self.db.exec(
                select(Reservation).where(
                    and_(
                        Reservation.confirmation_code == booking_number.upper(),
                        Reservation.status.in_(["booked", "checked_in"])
                    )
                )
            )
            reservation = result.first()
            if reservation:
                return reservation

        if guest_id:
            # Try Booking table first
            result = await self.db.exec(
                select(Booking).where(
                    and_(
                        Booking.guest_id == guest_id,
                        Booking.status.in_(["confirmed", "checked_in"]),
                        Booking.arrival_date <= today,
                        Booking.departure_date >= today
                    )
                ).order_by(Booking.created_at.desc())
            )
            booking = result.first()
            if booking:
                return booking

            # Try Reservation table
            result = await self.db.exec(
                select(Reservation).where(
                    and_(
                        Reservation.guest_id == guest_id,
                        Reservation.status.in_(["booked", "checked_in"]),
                        Reservation.arrival_date <= today,
                        Reservation.departure_date >= today
                    )
                ).order_by(Reservation.created_at.desc())
            )
            reservation = result.first()
            if reservation:
                return reservation

        if user_id:
            guest_result = await self.db.exec(select(Guest).where(Guest.user_id == user_id))
            guest = guest_result.first()
            if guest:
                # Try Booking table
                result = await self.db.exec(
                    select(Booking).where(
                        and_(
                            Booking.guest_id == guest.id,
                            Booking.status.in_(["confirmed", "checked_in"]),
                            Booking.arrival_date <= today,
                            Booking.departure_date >= today
                        )
                    ).order_by(Booking.created_at.desc())
                )
                booking = result.first()
                if booking:
                    return booking

                # Try Reservation table
                result = await self.db.exec(
                    select(Reservation).where(
                        and_(
                            Reservation.guest_id == guest.id,
                            Reservation.status.in_(["booked", "checked_in"]),
                            Reservation.arrival_date <= today,
                            Reservation.departure_date >= today
                        )
                    ).order_by(Reservation.created_at.desc())
                )
                return result.first()

        return None

    async def _save_conversation(
        self, session_id: str, user_query: str, bot_response: str,
        classification: str, requires_staff_action: bool = False,
        staff_task_id: Optional[int] = None, room_number: Optional[str] = None,
        faq_id: Optional[str] = None
    ):
        """Save conversation to database"""
        conversation = GuestChatConversation(
            conversation_id=str(uuid.uuid4()),
            session_id=session_id,
            user_query=user_query,
            bot_response=bot_response,
            classification=classification,
            requires_staff_action=requires_staff_action,
            staff_task_id=staff_task_id,
            room_number=room_number,
            faq_id=faq_id
        )
        self.db.add(conversation)

    async def _send_staff_notification_email(
        self, staff_email: str, staff_name: str, task_type: str,
        room_number: Optional[str], priority: str, description: str
    ):
        """Send email notification to assigned staff"""
        try:
            email_service = get_email_service()
            email_service.send_task_assignment_email(
                to_email=staff_email,
                staff_name=staff_name,
                task_type=task_type,
                room_number=room_number or "N/A",
                priority=priority,
                notes=description
            )
            logger.info(f"Task notification email sent to {staff_email}")
        except Exception as e:
            logger.error(f"Error sending notification email: {e}")

    async def lookup_booking(self, booking_number: str) -> Optional[Dict[str, Any]]:
        """Look up booking by confirmation number - checks both Booking and Reservation tables"""
        # Clean up the booking number
        clean_number = booking_number.strip().upper()
        logger.info(f"Looking up booking: {clean_number}")

        # First try the new Booking table
        result = await self.db.exec(
            select(Booking).where(
                or_(
                    Booking.confirmation_code == clean_number,
                    Booking.booking_number == clean_number,
                    Booking.confirmation_code.ilike(f"%{clean_number}%"),
                    Booking.booking_number.ilike(f"%{clean_number}%")
                )
            )
        )
        booking = result.first()

        if booking:
            logger.info(f"Found in Booking table: {booking.confirmation_code}")
            # Get guest info
            guest_result = await self.db.exec(select(Guest).where(Guest.id == booking.guest_id))
            guest = guest_result.first()

            # Get room info
            room_number = None
            if booking.room_id:
                room_result = await self.db.exec(select(Room).where(Room.id == booking.room_id))
                room = room_result.first()
                if room:
                    room_number = room.number

            return {
                "id": booking.id,
                "confirmation_code": booking.confirmation_code,
                "booking_number": booking.booking_number,
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
                "guest_id": booking.guest_id,
                "room_number": room_number,
                "room_id": booking.room_id,
                "arrival_date": booking.arrival_date.isoformat(),
                "departure_date": booking.departure_date.isoformat(),
                "status": booking.status,
                "is_checked_in": booking.status == "checked_in"
            }

        # Fallback to legacy Reservation table
        logger.info(f"Not found in Booking table, checking Reservation table...")
        result = await self.db.exec(
            select(Reservation).where(
                or_(
                    Reservation.confirmation_code == clean_number,
                    Reservation.confirmation_code.ilike(f"%{clean_number}%")
                )
            )
        )
        reservation = result.first()

        if reservation:
            logger.info(f"Found in Reservation table: {reservation.confirmation_code}")
            # Get guest info
            guest_result = await self.db.exec(select(Guest).where(Guest.id == reservation.guest_id))
            guest = guest_result.first()

            # Get room info
            room_number = None
            if reservation.room_id:
                room_result = await self.db.exec(select(Room).where(Room.id == reservation.room_id))
                room = room_result.first()
                if room:
                    room_number = room.number

            # Map reservation status to frontend-friendly status
            status_map = {
                "booked": "confirmed",
                "checked_in": "checked_in",
                "checked_out": "checked_out",
                "cancelled": "cancelled",
                "no_show": "no_show"
            }

            return {
                "id": reservation.id,
                "confirmation_code": reservation.confirmation_code,
                "booking_number": reservation.confirmation_code,  # Use confirmation_code as booking number
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
                "guest_id": reservation.guest_id,
                "room_number": room_number,
                "room_id": reservation.room_id,
                "arrival_date": reservation.arrival_date.isoformat(),
                "departure_date": reservation.departure_date.isoformat(),
                "status": status_map.get(reservation.status, reservation.status),
                "is_checked_in": reservation.status == "checked_in"
            }

        logger.info(f"Booking not found in any table: {clean_number}")
        return None

    # ============================================================
    # NEW COMPREHENSIVE AGI HANDLERS
    # ============================================================

    def _get_conversation_context(self, session_id: str) -> ConversationContext:
        """Get or create conversation context for a session"""
        if session_id not in self._conversation_contexts:
            self._conversation_contexts[session_id] = ConversationContext()

        context = self._conversation_contexts[session_id]

        # Check for expiration
        if context.is_expired():
            context.reset()

        return context

    async def _get_guest_for_user(self) -> Optional[Guest]:
        """Get guest record for current user (via email matching)"""
        if not self.current_user:
            return None

        result = await self.db.exec(
            select(Guest).where(Guest.email == self.current_user.email)
        )
        return result.first()

    def _is_staff_or_admin(self) -> bool:
        """Check if current user is staff or admin"""
        if not self.current_user:
            return False
        return self.current_user.is_superuser or self.current_user.role in ["admin", "front_desk", "manager", "staff"]

    async def _handle_room_search(
        self, message: str, session: GuestChatSession, context: Dict
    ) -> ChatResponse:
        """Handle room search and availability queries"""
        logger.info(f"Handling room search: {message}")

        # Create action executor
        action = RoomSearchAction(self.db, self.current_user)

        # Try to extract date information from message
        dates = await self._extract_dates_from_message(message)
        guests = self._extract_guest_count(message)

        # If dates found, perform search
        if dates.get("arrival_date") and dates.get("departure_date"):
            params = {
                "arrival_date": dates["arrival_date"],
                "departure_date": dates["departure_date"],
                "adults": guests.get("adults", 2),
                "children": guests.get("children", 0)
            }

            result = await action.execute(params)

            if result["success"]:
                rooms = result["data"]["room_types"]
                if rooms:
                    room_list = "\n".join([
                        f"• **{r['name']}** - ${r['price_per_night']}/night ({r['available_count']} available)"
                        for r in rooms[:5]
                    ])
                    response_text = f"I found {len(rooms)} room types available for your dates ({dates['arrival_date']} to {dates['departure_date']}):\n\n{room_list}\n\nWould you like to book one of these rooms?"
                else:
                    response_text = f"I'm sorry, no rooms are available for {dates['arrival_date']} to {dates['departure_date']}. Would you like to try different dates?"

                return ChatResponse(
                    response=response_text,
                    intent="room_search",
                    confidence=0.95,
                    room_search_results=rooms,
                    quick_actions=[
                        {"label": "Book Now", "action": "make_booking"},
                        {"label": "Change Dates", "action": "room_search"},
                        {"label": "Talk to Staff", "action": "front_desk"}
                    ]
                )
            else:
                return ChatResponse(
                    response=f"I encountered an issue searching for rooms: {result.get('error', 'Unknown error')}. Please try again or contact our front desk.",
                    intent="room_search",
                    confidence=0.7
                )

        # No dates found - ask for dates
        return ChatResponse(
            response="I'd be happy to help you find available rooms! Please provide your check-in and check-out dates. For example: 'Show rooms from January 15 to January 18' or 'Rooms for next weekend'.",
            intent="room_search",
            confidence=0.9,
            quick_actions=[
                {"label": "This Weekend", "action": "room_search_weekend"},
                {"label": "Next Week", "action": "room_search_next_week"},
                {"label": "Pick Dates", "action": "room_search_calendar"}
            ]
        )

    async def _handle_make_booking(
        self, message: str, session: GuestChatSession, context: Dict
    ) -> ChatResponse:
        """Handle booking creation requests"""
        logger.info(f"Handling make booking: {message}")

        # Check authentication
        if not self.current_user:
            return ChatResponse(
                response="To make a booking, please log in to your account first. If you don't have an account, you can create one or book as a guest through our website.",
                intent="make_booking",
                confidence=0.9,
                requires_auth=True,
                quick_actions=[
                    {"label": "Log In", "action": "login"},
                    {"label": "Create Account", "action": "register"},
                    {"label": "Book on Website", "action": "website_booking"}
                ]
            )

        # Get conversation context
        conv_context = self._get_conversation_context(session.session_id)

        # If not in booking flow, start it with room search
        if not conv_context.is_in_flow() or conv_context.flow_type != FlowType.BOOKING.value:
            # Start booking flow
            self.state_machine.start_flow(conv_context, FlowType.BOOKING.value)

            return ChatResponse(
                response="Great! Let's book a room for you. First, what dates would you like to stay? Please provide your check-in and check-out dates.",
                intent="make_booking",
                confidence=0.95,
                flow_state=self.state_machine.get_current_step_info(conv_context),
                quick_actions=[
                    {"label": "This Weekend", "action": "dates_this_weekend"},
                    {"label": "Next Week", "action": "dates_next_week"},
                    {"label": "Cancel", "action": "cancel_flow"}
                ]
            )

        # Continue booking flow based on current state
        step_info = self.state_machine.get_current_step_info(conv_context)
        return ChatResponse(
            response=f"You're in step {step_info['current_step']} of {step_info['total_steps']}: {step_info['step_label']}. Please provide the required information or say 'cancel' to start over.",
            intent="make_booking",
            confidence=0.9,
            flow_state=step_info,
            quick_actions=[
                {"label": "Continue", "action": "continue_flow"},
                {"label": "Cancel", "action": "cancel_flow"}
            ]
        )

    async def _handle_precheckin(
        self, message: str, session: GuestChatSession, context: Dict,
        passed_booking_number: Optional[str] = None
    ) -> ChatResponse:
        """Handle pre-checkin flow"""
        logger.info(f"Handling pre-checkin: {message}, passed_booking_number: {passed_booking_number}")

        booking_number = passed_booking_number  # Use booking number from caller (sent by frontend)

        # If no booking number passed, check if session already has a booking from previous lookup
        if not booking_number and session.booking_id:
            result = await self.db.exec(
                select(Booking).where(Booking.id == session.booking_id)
            )
            existing_booking = result.first()
            if existing_booking and existing_booking.status in ["booked", "confirmed", "pending"]:
                booking_number = existing_booking.confirmation_code
                logger.info(f"Using booking from session context: {booking_number}")

        # If no booking in session, try to extract from message
        if not booking_number:
            booking_number = await self.openai.extract_booking_number(message)

        # Try to find booking for current user if no number provided
        if not booking_number and self.current_user:
            guest = await self._get_guest_for_user()
            if guest:
                # Find upcoming booking - include "booked" status which is the default
                today = date_type.today()
                result = await self.db.exec(
                    select(Booking).where(
                        and_(
                            Booking.guest_id == guest.id,
                            Booking.status.in_(["booked", "confirmed", "pending"]),
                            Booking.arrival_date >= today
                        )
                    ).order_by(Booking.arrival_date)
                )
                booking = result.first()
                if booking:
                    booking_number = booking.confirmation_code

        if not booking_number:
            return ChatResponse(
                response="I'd be happy to help you with pre-checkin! Please provide your booking confirmation number (e.g., GLM-XXX123).",
                intent="precheckin",
                confidence=0.9,
                quick_actions=[
                    {"label": "Enter Booking Number", "action": "enter_booking"},
                    {"label": "Find My Booking", "action": "my_bookings"}
                ]
            )

        # Verify booking
        action = PreCheckinVerifyAction(self.db, self.current_user)
        result = await action.execute({"booking_number": booking_number})

        if not result["success"]:
            return ChatResponse(
                response=f"I couldn't find a booking with confirmation number '{booking_number}'. Please check the number and try again.",
                intent="precheckin",
                confidence=0.8,
                auth_error=result.get("error"),
                quick_actions=[
                    {"label": "Try Again", "action": "enter_booking"},
                    {"label": "Contact Front Desk", "action": "front_desk"}
                ]
            )

        booking_info = result["data"]

        # Check if pre-checkin already exists
        existing_precheckin = await self.db.exec(
            select(PreCheckIn).where(PreCheckIn.reservation_id == booking_info["id"])
        )
        precheckin = existing_precheckin.first()

        if precheckin and precheckin.status == "completed":
            return ChatResponse(
                response=f"Great news! Pre-checkin for booking {booking_number} is already complete. Your room will be ready at check-in time. Is there anything else I can help you with?",
                intent="precheckin",
                confidence=0.95,
                booking_info=booking_info,
                precheckin_info={
                    "status": "completed",
                    "room_number": precheckin.selected_room_number
                },
                quick_actions=[
                    {"label": "View Booking", "action": "booking_details"},
                    {"label": "Contact Front Desk", "action": "front_desk"}
                ]
            )

        # Start or continue pre-checkin flow
        conv_context = self._get_conversation_context(session.session_id)
        self.state_machine.start_flow(conv_context, FlowType.PRECHECKIN.value)
        conv_context.set_data("booking_number", booking_number)
        conv_context.set_data("booking_info", booking_info)

        response_text = f"""I found your booking!

**Confirmation:** {booking_info['confirmation_code']}
**Guest:** {booking_info['guest_name']}
**Check-in:** {booking_info['arrival_date']}
**Check-out:** {booking_info['departure_date']}

Let's complete your pre-checkin. First, please confirm your contact information:
- Email: {booking_info.get('email', 'Not on file')}
- Phone: {booking_info.get('phone', 'Not on file')}

Is this information correct?"""

        return ChatResponse(
            response=response_text,
            intent="precheckin",
            confidence=0.95,
            booking_info=booking_info,
            flow_state=self.state_machine.get_current_step_info(conv_context),
            quick_actions=[
                {"label": "Yes, Continue", "action": "confirm_contact"},
                {"label": "Update Contact", "action": "update_contact"},
                {"label": "Cancel", "action": "cancel_flow"}
            ]
        )

    async def _handle_profile_view(
        self, message: str, session: GuestChatSession, context: Dict
    ) -> ChatResponse:
        """Handle profile view requests"""
        logger.info(f"Handling profile view: {message}")

        # Check authentication
        if not self.current_user:
            return ChatResponse(
                response="To view your profile, please log in to your account first.",
                intent="profile_view",
                confidence=0.9,
                requires_auth=True,
                quick_actions=[
                    {"label": "Log In", "action": "login"},
                    {"label": "Create Account", "action": "register"}
                ]
            )

        # Get profile info
        action = ProfileViewAction(self.db, self.current_user)
        result = await action.execute({})

        if not result["success"]:
            return ChatResponse(
                response="I couldn't retrieve your profile information. Please try again or contact support.",
                intent="profile_view",
                confidence=0.7,
                auth_error=result.get("error")
            )

        profile = result["data"]

        # Format profile information
        profile_text = f"""Here's your profile information:

**Name:** {profile.get('name', 'Not set')}
**Email:** {profile.get('email', 'Not set')}
**Phone:** {profile.get('phone', 'Not set')}
**Address:** {profile.get('address', 'Not set')}
**Country:** {profile.get('country', 'Not set')}

**Loyalty Status:** {profile.get('loyalty_tier', 'Member')}
**Total Stays:** {profile.get('total_stays', 0)}
**Loyalty Points:** {profile.get('loyalty_points', 0)}

Would you like to update any of this information?"""

        return ChatResponse(
            response=profile_text,
            intent="profile_view",
            confidence=0.95,
            profile_info=profile,
            quick_actions=[
                {"label": "Update Phone", "action": "update_phone"},
                {"label": "Update Preferences", "action": "update_preferences"},
                {"label": "View Bookings", "action": "my_bookings"}
            ]
        )

    async def _handle_profile_update(
        self, message: str, session: GuestChatSession, context: Dict
    ) -> ChatResponse:
        """Handle profile update requests"""
        logger.info(f"Handling profile update: {message}")

        # Check authentication
        if not self.current_user:
            return ChatResponse(
                response="To update your profile, please log in to your account first.",
                intent="profile_update",
                confidence=0.9,
                requires_auth=True,
                quick_actions=[
                    {"label": "Log In", "action": "login"}
                ]
            )

        # Try to extract what field to update and the new value
        field, value = self._extract_profile_update(message)

        if field and value:
            # Perform the update
            action = ProfileUpdateAction(self.db, self.current_user)
            result = await action.execute({field: value})

            if result["success"]:
                return ChatResponse(
                    response=f"I've updated your {field.replace('_', ' ')} successfully. Is there anything else you'd like to update?",
                    intent="profile_update",
                    confidence=0.95,
                    action_result=result["data"],
                    quick_actions=[
                        {"label": "View Profile", "action": "profile_view"},
                        {"label": "Update More", "action": "profile_update"},
                        {"label": "Done", "action": "done"}
                    ]
                )
            else:
                return ChatResponse(
                    response=f"I couldn't update your profile: {result.get('error', 'Unknown error')}. Please try again.",
                    intent="profile_update",
                    confidence=0.7,
                    auth_error=result.get("error")
                )

        # Ask what to update
        return ChatResponse(
            response="What would you like to update in your profile? You can update your phone number, address, country, or preferences. Just tell me what you'd like to change.",
            intent="profile_update",
            confidence=0.9,
            quick_actions=[
                {"label": "Update Phone", "action": "update_phone"},
                {"label": "Update Address", "action": "update_address"},
                {"label": "Update Preferences", "action": "update_preferences"}
            ]
        )

    async def _handle_booking_modify(
        self, message: str, session: GuestChatSession, context: Dict,
        passed_booking_number: Optional[str] = None
    ) -> ChatResponse:
        """Handle booking modification requests"""
        logger.info(f"Handling booking modify: {message}, passed_booking_number: {passed_booking_number}")

        # Check authentication
        if not self.current_user:
            return ChatResponse(
                response="To modify a booking, please log in to your account first.",
                intent="booking_modify",
                confidence=0.9,
                requires_auth=True,
                quick_actions=[
                    {"label": "Log In", "action": "login"}
                ]
            )

        # Use passed booking number first, then try to extract from message
        booking_number = passed_booking_number
        if not booking_number:
            booking_number = await self.openai.extract_booking_number(message)

        if not booking_number:
            # Try to find booking from context or session
            if session.booking_id:
                result = await self.db.exec(
                    select(Booking).where(Booking.id == session.booking_id)
                )
                booking = result.first()
                if booking:
                    booking_number = booking.confirmation_code

        if not booking_number:
            return ChatResponse(
                response="Which booking would you like to modify? Please provide your booking confirmation number or say 'show my bookings' to see your reservations.",
                intent="booking_modify",
                confidence=0.8,
                quick_actions=[
                    {"label": "Show My Bookings", "action": "my_bookings"},
                    {"label": "Enter Booking Number", "action": "enter_booking"}
                ]
            )

        # Verify booking and authorization
        action = BookingModifyAction(self.db, self.current_user)

        # First validate authorization
        booking_info = await self.lookup_booking(booking_number)
        if not booking_info:
            return ChatResponse(
                response=f"I couldn't find a booking with confirmation number '{booking_number}'. Please check the number and try again.",
                intent="booking_modify",
                confidence=0.8
            )

        # Check ownership
        if not self._is_staff_or_admin():
            guest = await self._get_guest_for_user()
            if not guest or booking_info.get("guest_id") != guest.id:
                return ChatResponse(
                    response="I'm sorry, but you don't have permission to modify this booking. You can only modify bookings that belong to your account.",
                    intent="booking_modify",
                    confidence=0.9,
                    requires_auth=True,
                    auth_error="Not authorized to modify this booking"
                )

        # Start modification flow
        return ChatResponse(
            response=f"""I found your booking ({booking_number}). What would you like to change?

**Current Details:**
- Check-in: {booking_info['arrival_date']}
- Check-out: {booking_info['departure_date']}
- Status: {booking_info['status']}

Please note: Date changes may affect pricing and are subject to availability.""",
            intent="booking_modify",
            confidence=0.95,
            booking_info=booking_info,
            quick_actions=[
                {"label": "Change Dates", "action": "modify_dates"},
                {"label": "Add Nights", "action": "extend_stay"},
                {"label": "Cancel Booking", "action": "booking_cancel"}
            ]
        )

    async def _handle_booking_cancel(
        self, message: str, session: GuestChatSession, context: Dict,
        passed_booking_number: Optional[str] = None
    ) -> ChatResponse:
        """Handle booking cancellation requests"""
        logger.info(f"Handling booking cancel: {message}, passed_booking_number: {passed_booking_number}")

        # Check authentication
        if not self.current_user:
            return ChatResponse(
                response="To cancel a booking, please log in to your account first.",
                intent="booking_cancel",
                confidence=0.9,
                requires_auth=True,
                quick_actions=[
                    {"label": "Log In", "action": "login"}
                ]
            )

        # Use passed booking number first, then try to extract from message
        booking_number = passed_booking_number
        if not booking_number:
            booking_number = await self.openai.extract_booking_number(message)
        if not booking_number and session.booking_id:
            # Try to get from session context
            result = await self.db.exec(select(Booking).where(Booking.id == session.booking_id))
            booking = result.first()
            if booking:
                booking_number = booking.confirmation_code

        if not booking_number:
            return ChatResponse(
                response="Which booking would you like to cancel? Please provide your booking confirmation number.",
                intent="booking_cancel",
                confidence=0.8,
                quick_actions=[
                    {"label": "Show My Bookings", "action": "my_bookings"},
                    {"label": "Enter Booking Number", "action": "enter_booking"}
                ]
            )

        # Verify booking and authorization
        booking_info = await self.lookup_booking(booking_number)
        if not booking_info:
            return ChatResponse(
                response=f"I couldn't find a booking with confirmation number '{booking_number}'. Please check the number and try again.",
                intent="booking_cancel",
                confidence=0.8
            )

        # Check ownership
        if not self._is_staff_or_admin():
            guest = await self._get_guest_for_user()
            if not guest or booking_info.get("guest_id") != guest.id:
                return ChatResponse(
                    response="I'm sorry, but you don't have permission to cancel this booking. You can only cancel bookings that belong to your account.",
                    intent="booking_cancel",
                    confidence=0.9,
                    requires_auth=True,
                    auth_error="Not authorized to cancel this booking"
                )

        # Check if booking can be cancelled
        if booking_info["status"] in ["checked_in", "checked_out", "cancelled"]:
            return ChatResponse(
                response=f"This booking cannot be cancelled because it is currently '{booking_info['status']}'. Please contact our front desk for assistance.",
                intent="booking_cancel",
                confidence=0.9,
                booking_info=booking_info,
                quick_actions=[
                    {"label": "Contact Front Desk", "action": "front_desk"}
                ]
            )

        # Confirm cancellation
        return ChatResponse(
            response=f"""Are you sure you want to cancel this booking?

**Booking:** {booking_number}
**Check-in:** {booking_info['arrival_date']}
**Check-out:** {booking_info['departure_date']}

Please note: Cancellation fees may apply depending on your booking terms. Reply 'yes' to confirm or 'no' to keep your reservation.""",
            intent="booking_cancel",
            confidence=0.95,
            booking_info=booking_info,
            quick_actions=[
                {"label": "Yes, Cancel", "action": "confirm_cancel"},
                {"label": "No, Keep Booking", "action": "keep_booking"},
                {"label": "View Cancellation Policy", "action": "cancellation_policy"}
            ]
        )

    async def _handle_my_bookings(
        self, message: str, session: GuestChatSession, context: Dict
    ) -> ChatResponse:
        """Handle my bookings list requests"""
        logger.info(f"Handling my bookings: {message}")

        # Check authentication
        if not self.current_user:
            return ChatResponse(
                response="To view your bookings, please log in to your account first.",
                intent="my_bookings",
                confidence=0.9,
                requires_auth=True,
                quick_actions=[
                    {"label": "Log In", "action": "login"},
                    {"label": "Look Up Booking", "action": "booking_lookup"}
                ]
            )

        # Get bookings
        action = MyBookingsAction(self.db, self.current_user)
        result = await action.execute({})

        if not result["success"]:
            return ChatResponse(
                response="I couldn't retrieve your bookings. Please try again or contact support.",
                intent="my_bookings",
                confidence=0.7,
                auth_error=result.get("error")
            )

        bookings = result["data"]["bookings"]

        if not bookings:
            return ChatResponse(
                response="You don't have any bookings at the moment. Would you like to make a new reservation?",
                intent="my_bookings",
                confidence=0.9,
                bookings_list=[],
                quick_actions=[
                    {"label": "Find Rooms", "action": "room_search"},
                    {"label": "Make Booking", "action": "make_booking"}
                ]
            )

        # Format bookings list
        booking_lines = []
        for b in bookings[:5]:  # Show up to 5 most recent
            status_emoji = {
                "confirmed": "✓",
                "pending": "⏳",
                "checked_in": "🏨",
                "checked_out": "✓",
                "cancelled": "✗"
            }.get(b["status"], "•")

            booking_lines.append(
                f"{status_emoji} **{b['confirmation_code']}** - {b['arrival_date']} to {b['departure_date']} ({b['status']})"
            )

        bookings_text = "\n".join(booking_lines)

        response_text = f"""Here are your bookings:

{bookings_text}

Would you like details on a specific booking? Just provide the confirmation number."""

        return ChatResponse(
            response=response_text,
            intent="my_bookings",
            confidence=0.95,
            bookings_list=bookings,
            quick_actions=[
                {"label": "Make New Booking", "action": "make_booking"},
                {"label": "Pre-Checkin", "action": "precheckin"}
            ]
        )

    async def _handle_staff_help(
        self, message: str, session: GuestChatSession, context: Dict
    ) -> ChatResponse:
        """
        Handle direct staff assistance requests
        Creates a task for front desk staff to contact the guest
        """
        logger.info(f"Handling staff help request: {message}")

        room_number = context.get("room_number") or session.room_number
        guest_name = context.get("guest_first_name") or context.get("guest_name", "Guest")

        task_title = f"Guest Assistance Request - {guest_name}"
        task_description = f"Guest has requested to speak with staff.\nOriginal request: {message}\nRoom: {room_number or 'Not specified'}"

        # Create staff assistance task
        task, assigned_staff = await self.scheduling_service.create_and_assign_task(
            task_type="concierge",
            title=task_title,
            description=task_description,
            priority="high",
            room_number=room_number,
            booking_id=session.booking_id,
            guest_id=session.guest_id
        )

        # Get staff role
        staff_role = None
        if assigned_staff:
            staff_role = getattr(assigned_staff, 'role', None) or getattr(assigned_staff, 'department', None)
            response_text = f"I understand you'd like to speak with someone directly. I've notified {assigned_staff.staff_name}, who will contact you shortly. "
            if room_number:
                response_text += f"They will reach out to Room {room_number} or call the number on your profile. "
            response_text += "In the meantime, is there anything I can help you with?"
        else:
            response_text = "I've sent a request to our front desk team. Someone will reach out to you shortly. You can also call the front desk directly at extension 0 for immediate assistance. Is there anything I can help you with in the meantime?"

        return ChatResponse(
            response=response_text,
            intent="staff_help",
            confidence=0.95,
            requires_staff_action=True,
            staff_task_id=task.id if task else None,
            task_type="staff_assistance",
            assigned_staff_name=assigned_staff.staff_name if assigned_staff else None,
            estimated_response_time=15,
            # Enhanced task details
            task_priority="high",
            task_title=task_title,
            task_description=task_description,
            task_category="Staff Assistance",
            assigned_staff_role=staff_role,
            quick_actions=[
                {"label": "Call Front Desk", "action": "front_desk"},
                {"label": "Housekeeping", "action": "housekeeping"},
                {"label": "Maintenance", "action": "maintenance"}
            ]
        )

    async def _handle_capabilities(
        self, message: str, session: GuestChatSession, context: Dict
    ) -> ChatResponse:
        """Handle inquiries about Aria's capabilities"""
        logger.info(f"Handling capabilities query: {message}")

        guest_name = context.get("guest_first_name")
        is_checked_in = context.get("is_checked_in", False)

        # Build personalized capabilities list
        greeting = f"Great question, {guest_name}!" if guest_name else "Great question!"

        capabilities_response = f"""{greeting} I'm Aria, your AI concierge, and I'm here to make your stay exceptional. Here's what I can help you with:

**🛎️ Services & Requests**
• Housekeeping - Extra towels, room cleaning, turndown service
• Maintenance - Report issues (AC, plumbing, WiFi, etc.)
• Room Service - Food and beverage orders 24/7
• Concierge - Recommendations, transportation, spa bookings

**📅 Booking Management**
• Search for available rooms and make reservations
• View and modify your existing bookings
• Complete online pre-check-in
• Request early check-in or late check-out

**ℹ️ Information**
• Hotel amenities, hours, and policies
• Local recommendations and attractions
• Your loyalty points and benefits

**🆘 Urgent Matters**
• Emergency assistance (I'll alert staff immediately)
• Connect you with a staff member directly

Just tell me what you need, and I'll take care of it!"""

        # Generate relevant quick actions based on context
        if is_checked_in:
            quick_actions = [
                {"label": "Room Service", "action": "room_service"},
                {"label": "Report Issue", "action": "maintenance"},
                {"label": "Housekeeping", "action": "housekeeping"},
                {"label": "Concierge", "action": "concierge"}
            ]
        else:
            quick_actions = [
                {"label": "Find Rooms", "action": "room_search"},
                {"label": "My Bookings", "action": "my_bookings"},
                {"label": "Hotel Info", "action": "faq"},
                {"label": "Contact Staff", "action": "staff_help"}
            ]

        return ChatResponse(
            response=capabilities_response,
            intent="capabilities",
            confidence=0.95,
            quick_actions=quick_actions
        )

    # Helper methods for extraction

    async def _extract_dates_from_message(self, message: str) -> Dict[str, str]:
        """Extract check-in and check-out dates from message using AI"""
        if not self.openai.is_available:
            return {}

        try:
            today = date_type.today()
            response = self.openai.client.chat.completions.create(
                model=self.openai.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"""Extract check-in and check-out dates from the message.
Today's date is {today.isoformat()}.

Return dates in ISO format (YYYY-MM-DD) as JSON:
{{"arrival_date": "YYYY-MM-DD", "departure_date": "YYYY-MM-DD"}}

If dates cannot be determined, return {{"arrival_date": null, "departure_date": null}}

Examples:
- "next weekend" with today=2025-01-15 -> {{"arrival_date": "2025-01-18", "departure_date": "2025-01-19"}}
- "January 20 to 23" -> {{"arrival_date": "2025-01-20", "departure_date": "2025-01-23"}}
- "3 nights starting tomorrow" with today=2025-01-15 -> {{"arrival_date": "2025-01-16", "departure_date": "2025-01-19"}}"""
                    },
                    {"role": "user", "content": message}
                ],
                max_tokens=100,
                temperature=0
            )

            result = response.choices[0].message.content.strip()
            # Parse JSON from response
            import json
            data = json.loads(result)
            return {
                "arrival_date": data.get("arrival_date"),
                "departure_date": data.get("departure_date")
            }
        except Exception as e:
            logger.error(f"Date extraction error: {e}")
            return {}

    def _extract_guest_count(self, message: str) -> Dict[str, int]:
        """Extract guest count from message"""
        import re

        adults = 2  # Default
        children = 0

        # Look for patterns like "2 adults", "3 guests", "family of 4"
        adult_patterns = [
            r"(\d+)\s*adult",
            r"(\d+)\s*guest",
            r"(\d+)\s*person",
            r"family\s*of\s*(\d+)",
            r"for\s*(\d+)\s*people"
        ]

        for pattern in adult_patterns:
            match = re.search(pattern, message.lower())
            if match:
                adults = int(match.group(1))
                break

        # Look for children
        child_patterns = [
            r"(\d+)\s*child",
            r"(\d+)\s*kid"
        ]

        for pattern in child_patterns:
            match = re.search(pattern, message.lower())
            if match:
                children = int(match.group(1))
                break

        return {"adults": adults, "children": children}

    def _extract_profile_update(self, message: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract field and value for profile update from message"""
        import re

        message_lower = message.lower()

        # Phone number patterns
        phone_patterns = [
            r"(?:phone|mobile|cell)\s*(?:number|#)?\s*(?:is|to|:)?\s*([+\d\s\-()]{7,20})",
            r"(?:update|change)\s*(?:my)?\s*phone\s*(?:to|:)?\s*([+\d\s\-()]{7,20})"
        ]

        for pattern in phone_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return "phone", match.group(1).strip()

        # Address patterns
        address_patterns = [
            r"(?:address)\s*(?:is|to|:)?\s*(.+?)(?:\.|$)",
            r"(?:update|change)\s*(?:my)?\s*address\s*(?:to|:)?\s*(.+?)(?:\.|$)"
        ]

        for pattern in address_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return "address", match.group(1).strip()

        return None, None


def get_chatbot_service(db: AsyncSession, current_user: Optional[User] = None) -> UnifiedGuestChatbot:
    """Factory function to create chatbot service instance"""
    return UnifiedGuestChatbot(db, current_user)
