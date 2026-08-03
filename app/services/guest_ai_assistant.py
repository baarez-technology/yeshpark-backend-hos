"""
Guest AI Assistant Service
Uses LangGraph to orchestrate booking creation with cross-questioning
Updated: 2025-12-27 - Added pre-checkin auto-lookup
"""
from typing import TypedDict, Literal, Optional, List
try:
    from typing import Annotated
except ImportError:
    from typing_extensions import Annotated
from datetime import datetime, date
import operator
try:
    from langchain_openai import ChatOpenAI
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    # Fallback classes for when LangGraph is not installed
    class HumanMessage:
        def __init__(self, content):
            self.content = content
    
    class AIMessage:
        def __init__(self, content):
            self.content = content
    
    class SystemMessage:
        def __init__(self, content):
            self.content = content
    
    class ChatOpenAI:
        def __init__(self, *args, **kwargs):
            pass
        def invoke(self, messages):
            return AIMessage("LangGraph is not installed. Please install it to use the AI assistant.")
    
    class StateGraph:
        pass
    
    class END:
        pass
    
    # Fallback for add_messages
    def add_messages(left: List, right: List) -> List:
        """Fallback function for add_messages when LangGraph is not available"""
        return left + right
from app.core.config import settings
from app.db.session import get_session
from app.models.user import User
from app.models.inventory import Room, RatePlan
from app.models.reservations import Reservation, Guest
from app.services.reservation_service import create_reservation
from sqlmodel import select
import logging

logger = logging.getLogger(__name__)


class BookingState(TypedDict):
    """State for the AGI conversation"""
    messages: Annotated[list, add_messages]
    user_id: Optional[int]
    intent: Optional[str]  # booking, check_bookings, update_profile, cancel_booking, general, precheckin, booking_lookup, etc.
    check_in_date: Optional[date]
    check_out_date: Optional[date]
    room_type: Optional[str]
    adults: Optional[int]
    children: Optional[int]
    special_requests: Optional[str]
    guest_name: Optional[str]
    guest_email: Optional[str]
    guest_phone: Optional[str]
    booking_complete: bool
    missing_fields: List[str]
    conversation_turns: int  # Track number of turns to prevent infinite loops
    wants_booking: bool  # Track if user actually wants to make a booking
    session: any  # Database session for queries
    bookings_data: Optional[str]  # Pre-fetched booking data
    profile_data: Optional[str]  # Pre-fetched profile data
    password_data: Optional[dict]  # Password change data {current_password, new_password}
    detected_booking_code: Optional[str]  # Booking code detected in user message (e.g., GLM-XXXXXX)
    current_booking_data: Optional[str]  # Current booking being discussed (for context)


def create_guest_ai_graph():
    """Create the LangGraph workflow for guest booking assistant"""
    
    if not LANGGRAPH_AVAILABLE:
        return None
    
    # Initialize OpenAI LLM
    # Use same key loading logic as guest_assistant_chatbot (prioritize .env file)
    import os
    from pathlib import Path
    from dotenv import dotenv_values
    
    # Load .env file directly to get the key (bypassing system env vars that might be wrong)
    env_file_path = Path(__file__).parent.parent / ".env"
    env_dict = {}
    if env_file_path.exists():
        env_dict = dotenv_values(env_file_path)
    
    # Priority: 1) .env file, 2) os.getenv, 3) settings
    env_key_from_file = env_dict.get("OPENAI_API_KEY", "").strip() if env_dict else ""
    env_key_from_system = os.getenv("OPENAI_API_KEY", "").strip()
    settings_key_raw = settings.openai_api_key.strip() if settings.openai_api_key else ""
    
    # Remove all whitespace (including newlines) to handle multi-line keys
    env_key_from_file_clean = "".join(env_key_from_file.split()) if env_key_from_file else ""
    env_key_from_system_clean = "".join(env_key_from_system.split()) if env_key_from_system else ""
    settings_key_clean = "".join(settings_key_raw.split()) if settings_key_raw else ""
    
    # Prefer .env file over system env (system env might have wrong/old key)
    api_key = env_key_from_file_clean if env_key_from_file_clean else (env_key_from_system_clean if env_key_from_system_clean else settings_key_clean)
    
    if not api_key or api_key == "your-openai-api-key-here" or api_key == "":
        logger.warning(f"OpenAI API key not set. Checked .env file, system env, and settings.")
        return None
    
    try:
        # Initialize LLM - langchain-openai reads from OPENAI_API_KEY env var or accepts api_key parameter
        # Temporarily set environment variable for langchain
        original_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = api_key
        
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.7
        )
        
        # Restore original if it existed
        if original_key:
            os.environ["OPENAI_API_KEY"] = original_key
        elif "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
            
        logger.info(f"OpenAI LLM initialized successfully with model {settings.openai_model}")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI LLM: {e}")
        return None
    
    # System prompt for general assistant
    general_system_prompt = """You are Baarez, a helpful AI assistant for Glimmora Hotel. 
You can help guests with:
1. Making new bookings
2. Checking existing bookings
3. Updating profile information
4. Cancelling bookings
5. General questions about the hotel
6. Changing passwords
7. Any other hotel-related inquiries

Be friendly, professional, and helpful. Understand the guest's intent and provide appropriate assistance."""

    # System prompt for booking creation
    booking_system_prompt = """You are helping a guest make a booking at Glimmora Hotel.
You need to collect:
1. Check-in date
2. Check-out date  
3. Room type preference (Standard, Deluxe, Suite, Pacific Suite)
4. Number of adults
5. Number of children (optional)
6. Guest name
7. Guest email
8. Guest phone number
9. Special requests (optional)

Ask questions naturally and one at a time. If the guest provides multiple pieces of information, acknowledge all of them.
Once you have all required information, confirm the booking details before proceeding."""

    def detect_intent(state: BookingState) -> Literal["general", "booking", "check_bookings", "update_profile", "cancel_booking", "change_password", "create_booking", "precheckin", "booking_lookup", "end"]:
        """Detect user intent from conversation"""
        turns = state.get("conversation_turns", 0)
        if turns >= 15:  # Safety limit - reduced to prevent loops
            logger.warning(f"Conversation limit reached ({turns} turns), ending")
            return "end"
        
        # Get last user message
        messages = state.get("messages", [])
        last_user_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_message = msg.content.lower()
                break
        
        if not last_user_message:
            return "end"  # No user message, end
        
        # Check if we just responded (last message is AI) - if so, end to wait for next user input
        if messages and isinstance(messages[-1], AIMessage):
            # We just responded, wait for next user input
            return "end"
        
        # Intent detection keywords
        booking_keywords = ["book", "reservation", "reserve", "new booking", "make a booking"]
        check_booking_keywords = ["my bookings", "existing bookings", "bookings i have", "my reservations", "check bookings", "show bookings", "list bookings", "total number of bookings"]
        cancel_keywords = ["cancel", "cancellation", "cancel booking", "cancel reservation"]
        profile_keywords = ["update profile", "change profile", "edit profile", "my profile"]
        password_keywords = ["change password", "update password", "reset password", "new password"]
        precheckin_keywords = ["pre-checkin", "precheckin", "pre checkin", "online checkin", "online check-in", "digital checkin", "check in online", "want to check in", "want to do precheckin", "i want to do precheckin", "start check-in", "begin checkin", "do precheckin"]
        booking_lookup_keywords = ["glm-", "booking number", "confirmation code", "reservation code", "my booking"]

        # Check for explicit intent - order matters (most specific first)
        # Pre-checkin has priority
        if any(kw in last_user_message for kw in precheckin_keywords):
            return "precheckin"

        # Check for booking code (GLM-XXXXXX pattern)
        import re
        booking_code_match = re.search(r'\b(GLM-[A-Z0-9]{6})\b', last_user_message.upper())
        if booking_code_match:
            # Store the booking code in state for later use
            state["detected_booking_code"] = booking_code_match.group(1)
            return "booking_lookup"

        if any(kw in last_user_message for kw in check_booking_keywords):
            return "check_bookings"
        if any(kw in last_user_message for kw in cancel_keywords):
            return "cancel_booking"
        if any(kw in last_user_message for kw in password_keywords):
            return "change_password"
        if any(kw in last_user_message for kw in profile_keywords):
            return "update_profile"
        if any(kw in last_user_message for kw in booking_keywords):
            return "booking"
        
        # If we're already in booking mode and have intent set, continue
        current_intent = state.get("intent")
        if current_intent == "booking":
            # Check if booking is complete
            if state.get("booking_complete", False):
                return "end"
            # Check if we have all required fields
            missing = []
            if not state.get("check_in_date"):
                missing.append("check_in_date")
            if not state.get("check_out_date"):
                missing.append("check_out_date")
            if not state.get("room_type"):
                missing.append("room_type")
            if not state.get("adults"):
                missing.append("adults")
            if not state.get("guest_name"):
                missing.append("guest_name")
            if not state.get("guest_email"):
                missing.append("guest_email")
            if not state.get("guest_phone"):
                missing.append("guest_phone")
            state["missing_fields"] = missing
            if not missing:
                return "create_booking"
            return "booking"
        
        # Default to general conversation (only if we haven't responded yet)
        return "general"
    
    def general_node(state: BookingState):
        """Node for general conversation and intent detection"""
        messages = state.get("messages", [])
        turns = state.get("conversation_turns", 0) + 1
        
        # Detect intent
        intent = detect_intent(state)
        state["intent"] = intent
        
        # If we're just checking intent and should end, return early
        if intent == "end":
            return {
                "messages": [],
                "conversation_turns": turns,
                "intent": intent
            }
        
        # Create messages for LLM - only use the last few messages to avoid context bloat
        recent_messages = messages[-10:] if len(messages) > 10 else messages
        llm_messages = [SystemMessage(content=general_system_prompt)]
        llm_messages.extend(recent_messages)
        
        # Add context based on intent - use pre-fetched data from state
        bookings_data = state.get("bookings_data")
        if intent == "check_bookings" and bookings_data:
            llm_messages.append(SystemMessage(content=f"USER'S BOOKING INFORMATION (use this data to answer):\n{bookings_data}"))
        elif intent == "check_bookings":
            llm_messages.append(SystemMessage(content="The user wants to see their existing bookings. Since you're logged in, I should be able to fetch your bookings. Let me check..."))
        
        profile_data = state.get("profile_data")
        if intent == "update_profile" and profile_data:
            llm_messages.append(SystemMessage(content=f"USER'S PROFILE INFORMATION:\n{profile_data}\nGuide them on how to update their profile information."))
        elif intent == "update_profile":
            llm_messages.append(SystemMessage(content="The user wants to update their profile. Guide them on what information they can update and how to do it."))
        
        if intent == "cancel_booking":
            llm_messages.append(SystemMessage(content="The user wants to cancel a booking. Ask for the confirmation code or booking details to proceed with cancellation."))
        
        # Handle password change - check if we have both passwords
        if intent == "change_password":
            password_data = state.get("password_data")
            if password_data and password_data.get("current_password") and password_data.get("new_password"):
                # Passwords provided, will be handled in process_guest_message
                llm_messages.append(SystemMessage(content="The user has provided both current and new passwords. The password change will be processed."))
            else:
                llm_messages.append(SystemMessage(content="The user wants to change their password. Ask for their current password and the new password they want to set."))

        # Handle booking lookup - user provided a booking code
        current_booking_data = state.get("current_booking_data")
        if intent == "booking_lookup" and current_booking_data:
            llm_messages.append(SystemMessage(content=f"BOOKING DETAILS:\n{current_booking_data}\n\nPresent this booking information nicely and ask how you can help with it (modify, cancel, pre-checkin, etc)."))
        elif intent == "booking_lookup":
            booking_code = state.get("detected_booking_code", "")
            llm_messages.append(SystemMessage(content=f"The user provided booking code {booking_code}. Looking up the booking details..."))

        # Handle pre-checkin
        if intent == "precheckin":
            if current_booking_data:
                llm_messages.append(SystemMessage(content=f"BOOKING FOR PRE-CHECK-IN:\n{current_booking_data}\n\nThe user wants to do pre-check-in. Guide them through the process or let them know they can complete pre-check-in on the Pre-Check-In page. Provide the booking confirmation code."))
            else:
                # Check if we have a detected booking code from previous message
                booking_code = state.get("detected_booking_code", "")
                if booking_code:
                    llm_messages.append(SystemMessage(content=f"The user wants to do pre-check-in for booking {booking_code}. Let them know they can complete pre-check-in using this confirmation code on the Pre-Check-In page."))
                else:
                    llm_messages.append(SystemMessage(content="The user wants to do pre-check-in. If they have a booking, ask for the confirmation code (e.g., GLM-XXXXXX) or guide them to the Pre-Check-In page where they can enter their details."))

        # Get single response from LLM
        response = llm.invoke(llm_messages)
        
        return {
            "messages": [response],
            "conversation_turns": turns,
            "intent": intent
        }
    
    def collect_info_node(state: BookingState):
        """Node to collect booking information through conversation"""
        messages = state.get("messages", [])
        turns = state.get("conversation_turns", 0) + 1
        
        # Set intent to booking
        state["intent"] = "booking"
        
        # Build context about what we know and what we need
        context = "Current booking information:\n"
        if state.get("check_in_date"):
            context += f"- Check-in: {state['check_in_date']}\n"
        if state.get("check_out_date"):
            context += f"- Check-out: {state['check_out_date']}\n"
        if state.get("room_type"):
            context += f"- Room type: {state['room_type']}\n"
        if state.get("adults"):
            context += f"- Adults: {state['adults']}\n"
        if state.get("children"):
            context += f"- Children: {state['children']}\n"
        if state.get("guest_name"):
            context += f"- Guest name: {state['guest_name']}\n"
        if state.get("guest_email"):
            context += f"- Guest email: {state['guest_email']}\n"
        if state.get("guest_phone"):
            context += f"- Guest phone: {state['guest_phone']}\n"
        
        missing = state.get("missing_fields", [])
        if missing:
            context += f"\nStill need: {', '.join(missing)}\n"
        
        # Create messages for LLM
        llm_messages = [SystemMessage(content=booking_system_prompt)]
        llm_messages.extend(messages)
        if context:
            llm_messages.append(SystemMessage(content=f"Context:\n{context}"))
        
        # Get response from LLM
        response = llm.invoke(llm_messages)
        
        # Try to extract information from the conversation
        last_user_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_message = msg.content
                break
        
        # Simple extraction (can be enhanced with NER)
        if last_user_message:
            # Extract dates (simple pattern matching)
            import re
            date_pattern = r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})'
            dates = re.findall(date_pattern, last_user_message)
            if dates and not state.get("check_in_date"):
                # Assume first date is check-in
                try:
                    m, d, y = dates[0]
                    year = int(y) if len(y) == 4 else 2000 + int(y)
                    state["check_in_date"] = date(year, int(m), int(d))
                except:
                    pass
            
            # Extract numbers for adults/children
            if "adult" in last_user_message.lower() or "people" in last_user_message.lower():
                numbers = re.findall(r'\d+', last_user_message)
                if numbers and not state.get("adults"):
                    state["adults"] = int(numbers[0])
            
            # Extract room type
            room_types = ["standard", "deluxe", "suite", "pacific suite"]
            for rt in room_types:
                if rt in last_user_message.lower() and not state.get("room_type"):
                    state["room_type"] = rt.title()
                    break
        
        return {
            "messages": [response],
            "conversation_turns": turns,
            "wants_booking": wants_booking
        }
    
    def create_booking_node(state: BookingState):
        """Node to create the actual booking"""
        # This will be called from the API endpoint with database session
        state["booking_complete"] = True
        return {
            "messages": [AIMessage(content="I have all the information I need. Let me create your booking now...")]
        }
    
    # Build the graph
    workflow = StateGraph(BookingState)
    
    # Add nodes - Note: LangGraph supports async nodes, but we need to handle it properly
    # For now, we'll make general_node sync and fetch data before calling it
    workflow.add_node("general", general_node)
    workflow.add_node("booking", collect_info_node)
    workflow.add_node("create_booking", create_booking_node)
    
    # Set entry point - start with general to detect intent
    workflow.set_entry_point("general")
    
    # Add conditional edges from general node
    workflow.add_conditional_edges(
        "general",
        detect_intent,
        {
            "general": END,  # After responding, end to wait for next user input
            "booking": "booking",
            "check_bookings": END,  # Respond and end
            "update_profile": END,  # Respond and end
            "cancel_booking": END,  # Respond and end
            "change_password": END,  # Respond and end (will be processed in process_guest_message)
            "precheckin": END,  # Respond with pre-checkin guidance and end
            "booking_lookup": END,  # Respond with booking info and end
            "end": END
        }
    )
    
    # Add conditional edges from booking node
    workflow.add_conditional_edges(
        "booking",
        detect_intent,
        {
            "booking": "booking",
            "create_booking": "create_booking",
            "general": END,  # Switch to general ends the turn
            "end": END
        }
    )
    
    workflow.add_edge("create_booking", END)
    
    return workflow.compile()


async def process_guest_message(
    user_message: str,
    user_id: Optional[int],
    conversation_history: Optional[List[dict]] = None,
    session = None
) -> dict:
    """
    Process a guest message and return AI response
    
    Args:
        user_message: The user's message
        user_id: Optional user ID if logged in
        conversation_history: Previous conversation messages
        session: Database session
    
    Returns:
        dict with response message and updated state
    """
    try:
        # DEBUG: Confirm new code version is running (v2)
        logger.info(f"=== GUEST AI v2 === user_id={user_id}, session={session is not None}, message={user_message[:50]}")

        # Initialize graph
        graph = create_guest_ai_graph()
        
        if not graph:
            # Provide more helpful error message
            error_msg = "I apologize, but the AI assistant is not fully configured."
            if not LANGGRAPH_AVAILABLE:
                error_msg += " LangGraph library is not installed."
            elif not settings.openai_api_key or settings.openai_api_key.strip() == "":
                error_msg += " OpenAI API key is not configured. Please set OPENAI_API_KEY in the .env file."
            else:
                error_msg += " Please contact our support team for assistance with bookings."
            
            logger.error(f"AI Assistant not available - LANGGRAPH_AVAILABLE: {LANGGRAPH_AVAILABLE}, API Key set: {bool(settings.openai_api_key and settings.openai_api_key.strip())}")
            return {
                "response": error_msg,
                "state": {},
                "error": "AI Assistant not configured"
            }
        
        # Build initial state
        messages = []
        if conversation_history:
            for msg in conversation_history:
                if msg.get("type") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("type") == "ai":
                    messages.append(AIMessage(content=msg.get("content", "")))
        
        # Add current user message
        messages.append(HumanMessage(content=user_message))
        
        # Pre-fetch user data if logged in
        bookings_data = None
        profile_data = None
        password_data = None
        
        # Extract password change information from message
        import re
        current_password = None
        new_password = None
        
        # Try multiple patterns to extract passwords
        # Pattern 1: "Current password - X, New password - Y"
        current_match = re.search(r"(?:current|old).*?password.*?[-:]\s*([^\s,]+)", user_message, re.IGNORECASE)
        new_match = re.search(r"(?:new).*?password.*?[-:]\s*([^\s,]+)", user_message, re.IGNORECASE)
        
        if current_match:
            current_password = current_match.group(1).strip()
        if new_match:
            new_password = new_match.group(1).strip()
        
        # Pattern 2: Split by comma and look for password in each part
        if not current_password or not new_password:
            parts = [p.strip() for p in user_message.split(',')]
            for part in parts:
                part_lower = part.lower()
                if 'current' in part_lower and 'password' in part_lower:
                    # Extract after "password" and any separator
                    match = re.search(r"password.*?[-:]\s*(.+)", part, re.IGNORECASE)
                    if match:
                        current_password = match.group(1).strip()
                if 'new' in part_lower and 'password' in part_lower:
                    match = re.search(r"password.*?[-:]\s*(.+)", part, re.IGNORECASE)
                    if match:
                        new_password = match.group(1).strip()
        
        # Pattern 3: Look for passwords in quotes or after specific keywords
        if not current_password or not new_password:
            # Try to find passwords that might contain special characters
            password_candidates = re.findall(r"(?:current|old).*?password.*?[-:]\s*([^\s,]+(?:\S+)?)", user_message, re.IGNORECASE)
            if password_candidates:
                current_password = password_candidates[0].strip()
            
            password_candidates = re.findall(r"(?:new).*?password.*?[-:]\s*([^\s,]+(?:\S+)?)", user_message, re.IGNORECASE)
            if password_candidates:
                new_password = password_candidates[0].strip()
        
        # Clean up passwords (remove trailing punctuation if any)
        if current_password:
            current_password = current_password.rstrip('.,;:!?')
        if new_password:
            new_password = new_password.rstrip('.,;:!?')
        
        if current_password and new_password:
            password_data = {
                "current_password": current_password,
                "new_password": new_password
            }
        
        if user_id and session:
            try:
                user = await session.get(User, user_id)
                if user:
                    # Pre-fill profile data
                    initial_guest_name = user.full_name
                    initial_guest_email = user.email
                    initial_guest_phone = user.phone
                    
                    # Build profile data string
                    profile_data = f"Current profile:\n- Name: {initial_guest_name or 'Not set'}\n- Email: {initial_guest_email}\n- Phone: {initial_guest_phone or 'Not set'}\n"
                    
                    # Check if user is asking about bookings - fetch them now
                    user_message_lower = user_message.lower()
                    if any(kw in user_message_lower for kw in ["booking", "reservation", "bookings", "my bookings", "how many bookings"]):
                        # Find guest by email
                        guest = (await session.exec(
                            select(Guest).where(Guest.email == user.email)
                        )).first()
                        
                        if guest:
                            # Get all reservations for this guest
                            reservations = (await session.exec(
                                select(Reservation)
                                .where(Reservation.guest_id == guest.id)
                                .order_by(Reservation.created_at.desc())
                            )).all()
                            
                            if reservations:
                                bookings_info = f"You have {len(reservations)} booking(s):\n\n"
                                for i, res in enumerate(reservations, 1):
                                    room_info = ""
                                    if res.room_id:
                                        room = await session.get(Room, res.room_id)
                                        if room:
                                            room_info = f", Room: {room.number}"
                                    bookings_info += f"{i}. Confirmation Code: {res.confirmation_code}\n"
                                    bookings_info += f"   Dates: {res.arrival_date} to {res.departure_date}\n"
                                    bookings_info += f"   Status: {res.status.title()}{room_info}\n"
                                    bookings_info += f"   Guests: {res.adults} adult(s), {res.children} child(ren)\n"
                                    bookings_info += f"   Total: {res.currency} {res.total_amount}\n\n"
                                bookings_data = bookings_info
                            else:
                                bookings_data = "The user has no bookings in the system."
                        else:
                            bookings_data = "No guest profile found for this user."
            except Exception as e:
                logger.error(f"Error pre-fetching user data: {e}")
                initial_guest_name = None
                initial_guest_email = None
                initial_guest_phone = None
        else:
            initial_guest_name = None
            initial_guest_email = None
            initial_guest_phone = None

        # Detect and lookup booking code from message (GLM-XXXXXX pattern)
        detected_booking_code = None
        current_booking_data = None
        import re
        from datetime import date as date_type
        booking_code_match = re.search(r'\b(GLM-[A-Z0-9]{6})\b', user_message.upper())

        # Check if user is asking for pre-checkin
        user_message_lower = user_message.lower()
        is_precheckin_request = any(kw in user_message_lower for kw in [
            "pre-checkin", "precheckin", "pre checkin", "online checkin",
            "want to check in", "do precheckin", "start check-in"
        ])

        if booking_code_match:
            detected_booking_code = booking_code_match.group(1)
            logger.info(f"Detected booking code: {detected_booking_code}")

            # Try to lookup booking by confirmation code
            if session:
                try:
                    from app.models.reservations import Booking
                    booking = (await session.exec(
                        select(Booking).where(Booking.confirmation_code == detected_booking_code)
                    )).first()

                    if booking:
                        # Build booking info string
                        current_booking_data = f"Confirmation Code: {booking.confirmation_code}\n"
                        current_booking_data += f"Status: {booking.status.title()}\n"
                        current_booking_data += f"Check-in: {booking.arrival_date}\n"
                        current_booking_data += f"Check-out: {booking.departure_date}\n"
                        current_booking_data += f"Guests: {booking.adults} adult(s), {booking.children or 0} child(ren)\n"
                        current_booking_data += f"Total: ${booking.total_amount or 0:.2f}\n"

                        # Get room type info
                        if booking.room_type_id:
                            from app.models.inventory import RoomType
                            room_type = await session.get(RoomType, booking.room_type_id)
                            if room_type:
                                current_booking_data += f"Room Type: {room_type.name}\n"

                        # Get room number if assigned
                        if booking.room_id:
                            room = await session.get(Room, booking.room_id)
                            if room:
                                current_booking_data += f"Room Number: {room.number}\n"

                        logger.info(f"Found booking: {detected_booking_code}")
                    else:
                        current_booking_data = f"No booking found with confirmation code {detected_booking_code}"
                        logger.warning(f"Booking not found: {detected_booking_code}")
                except Exception as e:
                    logger.error(f"Error looking up booking {detected_booking_code}: {e}")
                    current_booking_data = f"Error looking up booking: {str(e)}"

        # If user asks for pre-checkin without a booking code, try to find their upcoming bookings
        elif is_precheckin_request and user_id and session and not detected_booking_code:
            logger.info(f"Pre-checkin request without booking code, looking up user's bookings")
            try:
                from app.models.reservations import Reservation
                user = await session.get(User, user_id)
                if user:
                    # Find guest by user email
                    guest = (await session.exec(
                        select(Guest).where(Guest.email == user.email)
                    )).first()

                    if guest:
                        # Find upcoming bookings for this guest
                        today = date_type.today()
                        upcoming_bookings = (await session.exec(
                            select(Reservation)
                            .where(Reservation.guest_id == guest.id)
                            .where(Reservation.status.in_(["booked", "confirmed", "pending"]))
                            .where(Reservation.departure_date >= today)
                            .order_by(Reservation.arrival_date)
                        )).all()

                        if upcoming_bookings:
                            if len(upcoming_bookings) == 1:
                                # Auto-select the only booking
                                booking = upcoming_bookings[0]
                                detected_booking_code = booking.confirmation_code
                                current_booking_data = f"Confirmation Code: {booking.confirmation_code}\n"
                                current_booking_data += f"Status: {booking.status.title()}\n"
                                current_booking_data += f"Check-in: {booking.arrival_date}\n"
                                current_booking_data += f"Check-out: {booking.departure_date}\n"
                                current_booking_data += f"Guests: {booking.adults} adult(s), {booking.children or 0} child(ren)\n"
                                current_booking_data += f"Total: ${booking.total_amount or 0:.2f}\n"

                                # Get room type info
                                if booking.room_type_id:
                                    from app.models.inventory import RoomType
                                    room_type = await session.get(RoomType, booking.room_type_id)
                                    if room_type:
                                        current_booking_data += f"Room Type: {room_type.name}\n"

                                logger.info(f"Auto-selected booking for pre-checkin: {detected_booking_code}")
                            else:
                                # Multiple bookings - list them
                                current_booking_data = f"You have {len(upcoming_bookings)} upcoming booking(s):\n\n"
                                for i, booking in enumerate(upcoming_bookings, 1):
                                    current_booking_data += f"{i}. {booking.confirmation_code} - Check-in: {booking.arrival_date}\n"
                                current_booking_data += "\nPlease specify which booking you'd like to pre-check-in for."
                                logger.info(f"Found {len(upcoming_bookings)} bookings for pre-checkin")
                        else:
                            current_booking_data = "You don't have any upcoming bookings to pre-check-in for."
                            logger.info("No upcoming bookings found for pre-checkin")
            except Exception as e:
                logger.error(f"Error looking up user bookings for pre-checkin: {e}")
                current_booking_data = f"Error looking up your bookings: {str(e)}"

        initial_state: BookingState = {
            "messages": messages,
            "user_id": user_id,
            "intent": None,
            "check_in_date": None,
            "check_out_date": None,
            "room_type": None,
            "adults": None,
            "children": None,
            "special_requests": None,
            "guest_name": initial_guest_name,
            "guest_email": initial_guest_email,
            "guest_phone": initial_guest_phone,
            "booking_complete": False,
            "missing_fields": [],
            "conversation_turns": 0,
            "wants_booking": True,
            "session": session,
            "bookings_data": bookings_data,  # Pre-fetched booking data
            "profile_data": profile_data,  # Pre-fetched profile data
            "password_data": password_data,  # Password change data
            "detected_booking_code": detected_booking_code,  # Booking code from user message
            "current_booking_data": current_booking_data  # Current booking being discussed
        }
        
        # Handle password change BEFORE graph if we have both passwords
        password_changed = False
        password_error = None
        if password_data and password_data.get("current_password") and password_data.get("new_password") and user_id and session:
            try:
                from app.core.security import verify_password, get_password_hash
                user = await session.get(User, user_id)
                if user:
                    # Verify current password
                    if verify_password(password_data["current_password"], user.hashed_password):
                        # Update password
                        user.hashed_password = get_password_hash(password_data["new_password"])
                        await session.commit()
                        password_changed = True
                        logger.info(f"Password changed successfully for user {user_id}")
                    else:
                        password_error = "Current password is incorrect"
                        logger.warning(f"Password change failed for user {user_id}: incorrect current password")
            except Exception as e:
                password_error = f"Error changing password: {str(e)}"
                logger.error(f"Password change error for user {user_id}: {e}")
        
        # Run the graph with increased recursion limit to prevent infinite loops
        result = graph.invoke(initial_state, config={"recursion_limit": 30})
        
        # Extract AI response
        ai_response = None
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage):
                ai_response = msg.content
                break
        
        if not ai_response:
            ai_response = "I'm here to help you make a booking. What dates are you interested in?"
        
        # Override response if password was changed
        if password_changed:
            ai_response = "Your password has been changed successfully! You can now use your new password to log in."
        elif password_error:
            ai_response = f"I'm sorry, but I couldn't change your password. {password_error}. Please try again."
        
        # Check if booking is ready to be created
        booking_ready = result.get("booking_complete", False)
        
        return {
            "response": ai_response,
            "state": {
                "check_in_date": result.get("check_in_date"),
                "check_out_date": result.get("check_out_date"),
                "room_type": result.get("room_type"),
                "adults": result.get("adults"),
                "children": result.get("children"),
                "special_requests": result.get("special_requests"),
                "guest_name": result.get("guest_name"),
                "guest_email": result.get("guest_email"),
                "guest_phone": result.get("guest_phone"),
                "booking_ready": booking_ready,
                "missing_fields": result.get("missing_fields", [])
            }
        }
    
    except Exception as e:
        logger.error(f"Error processing guest message: {e}", exc_info=True)
        return {
            "response": "I apologize, but I encountered an error. Please try again or contact our support team.",
            "state": {},
            "error": str(e)
        }


async def create_booking_from_state(
    state: dict,
    user_id: int,
    session
) -> dict:
    """
    Create a booking from the collected state
    
    Args:
        state: Booking state with all required fields
        user_id: User ID making the booking
        session: Database session
    
    Returns:
        dict with booking details or error
    """
    try:
        # Find room type
        room_type_result = await session.exec(
            select(Room).where(Room.room_type == state["room_type"])
        )
        room = room_type_result.first()
        
        if not room:
            return {"error": f"No {state['room_type']} rooms available"}
        
        # Create guest
        guest_data = {
            "first_name": state["guest_name"].split()[0] if state["guest_name"] else "",
            "last_name": " ".join(state["guest_name"].split()[1:]) if state["guest_name"] and len(state["guest_name"].split()) > 1 else "",
            "email": state["guest_email"],
            "phone": state["guest_phone"]
        }
        
        # Create or get guest using reservation service
        from app.services.reservation_service import create_guest
        guest, _ = await create_guest(session, guest_data)
        
        # Create reservation
        reservation_data = {
            "guest_id": guest.id,
            "room_id": room.id,
            "arrival_date": state["check_in_date"],
            "departure_date": state["check_out_date"],
            "adults": state["adults"],
            "children": state.get("children", 0),
            "special_requests": state.get("special_requests"),
            "status": "booked"
        }
        
        reservation = await create_reservation(
            session,
            reservation_data,
            user_id=user_id,
            allow_overbooking=False
        )
        
        await session.commit()
        await session.refresh(reservation)
        
        return {
            "success": True,
            "booking_id": reservation.id,
            "confirmation_code": reservation.confirmation_code,
            "message": f"Booking created successfully! Your confirmation code is {reservation.confirmation_code}"
        }
    
    except Exception as e:
        logger.error(f"Error creating booking: {e}", exc_info=True)
        await session.rollback()
        return {"error": str(e)}

