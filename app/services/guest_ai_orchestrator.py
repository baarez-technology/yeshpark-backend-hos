"""
Guest AI Orchestrator - Action-Based Implementation

This orchestrator uses OpenAI function calling to execute real actions
and returns structured action data for frontend UI rendering.

Key Features:
- Profile-aware: Uses stored user data, never asks for info we already have
- Action-based: Returns structured actions that tell frontend what UI to show
- Real actions: All tools actually modify the database
- UI Flow matching: Follows exact same flows as manual UI interactions

Action Types:
- show_room_options: Display room selection cards
- show_payment: Open payment modal with booking data
- show_precheckin_preferences: Show preference form
- show_precheckin_rooms: Show AI-recommended rooms
- show_booking_confirmation: Display booking success
- show_booking_details: Display booking info card
- show_digital_key: Show completed pre-check-in with QR
- request_confirmation: Ask user to confirm an action
- show_error: Display error message
"""

import logging
import json
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.chat_session_manager import ChatSessionManager, get_chat_session_manager
from app.services.agi.tools.booking_tools import BookingTools
from app.services.agi.tools.precheckin_tools import PreCheckinTools
from app.models.user import User
from app.models.reservations import Guest

logger = logging.getLogger("guest_ai_orchestrator")


# =============================================================================
# OpenAI Tool Definitions - Profile Aware
# =============================================================================

TOOLS = [
    # ==================== BOOKING TOOLS ====================
    {
        "type": "function",
        "function": {
            "name": "get_user_bookings",
            "description": "Get all bookings for the current logged-in user. The user's profile info (name, email, phone) is already loaded - do NOT ask for it.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_booking",
            "description": "Look up a specific booking by confirmation code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmation_code": {"type": "string", "description": "The booking confirmation code (e.g., GLM-ABC123)"}
                },
                "required": ["confirmation_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "modify_booking_dates",
            "description": "Modify a booking's check-in or check-out dates. This ACTUALLY changes the booking in the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmation_code": {"type": "string", "description": "The booking confirmation code"},
                    "new_check_in": {"type": "string", "description": "New check-in date (YYYY-MM-DD or natural like 'Jan 15'). Optional."},
                    "new_check_out": {"type": "string", "description": "New check-out date (YYYY-MM-DD or natural like 'Jan 20'). Optional."},
                    "reason": {"type": "string", "description": "Reason for modification"}
                },
                "required": ["confirmation_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": "Cancel a booking. Ask for confirmation before calling this.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmation_code": {"type": "string", "description": "The booking confirmation code to cancel"},
                    "reason": {"type": "string", "description": "Reason for cancellation"}
                },
                "required": ["confirmation_code", "reason"]
            }
        }
    },
    # ==================== PRE-CHECKIN TOOLS ====================
    {
        "type": "function",
        "function": {
            "name": "start_precheckin",
            "description": "Start pre-check-in process. User profile data (name, email, phone) will be used automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmation_code": {"type": "string", "description": "The booking confirmation code"}
                },
                "required": ["confirmation_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_precheckin_preferences",
            "description": "Set room preferences during pre-check-in. Call this when user provides their preferences.",
            "parameters": {
                "type": "object",
                "properties": {
                    "precheckin_id": {"type": "integer", "description": "The pre-check-in ID from start_precheckin"},
                    "floor_preference": {"type": "string", "enum": ["low", "mid", "high", "any"]},
                    "view_preference": {"type": "string", "enum": ["ocean", "city", "garden", "pool", "any"]},
                    "bed_type_preference": {"type": "string", "enum": ["king", "queen", "twin", "any"]},
                    "quietness_preference": {"type": "string", "enum": ["quiet", "moderate", "any"]},
                    "arrival_time": {"type": "string", "description": "Expected arrival time"},
                    "special_requests": {"type": "string", "description": "Any special requests"},
                    "early_check_in": {"type": "boolean"},
                    "late_check_out": {"type": "boolean"}
                },
                "required": ["precheckin_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_room_recommendations",
            "description": "Get AI-recommended rooms based on preferences. Returns room options for user to select.",
            "parameters": {
                "type": "object",
                "properties": {
                    "precheckin_id": {"type": "integer", "description": "The pre-check-in ID"}
                },
                "required": ["precheckin_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "select_room",
            "description": "Select a specific room from recommendations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "precheckin_id": {"type": "integer", "description": "The pre-check-in ID"},
                    "room_id": {"type": "integer", "description": "The room ID to select"}
                },
                "required": ["precheckin_id", "room_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_precheckin",
            "description": "Complete pre-check-in and generate digital key. Call after room is selected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "precheckin_id": {"type": "integer", "description": "The pre-check-in ID"},
                    "skip_id_verification": {"type": "boolean", "default": True}
                },
                "required": ["precheckin_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_precheckin_status",
            "description": "Check pre-check-in progress status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmation_code": {"type": "string", "description": "The booking confirmation code"}
                },
                "required": ["confirmation_code"]
            }
        }
    },
    # ==================== NEW BOOKING TOOLS ====================
    {
        "type": "function",
        "function": {
            "name": "browse_room_types",
            "description": "Browse all available room types at the hotel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room_type_name": {"type": "string", "description": "Optional specific room type to get details for"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check room availability for specific dates. Returns available room types with prices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "check_in_date": {"type": "string", "description": "Check-in date (YYYY-MM-DD or natural)"},
                    "check_out_date": {"type": "string", "description": "Check-out date (YYYY-MM-DD or natural)"},
                    "adults": {"type": "integer", "default": 1},
                    "children": {"type": "integer", "default": 0}
                },
                "required": ["check_in_date", "check_out_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "initiate_booking",
            "description": "Start a new booking. User profile data (name, email, phone) is used automatically. Returns room options for selection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "check_in_date": {"type": "string", "description": "Check-in date"},
                    "check_out_date": {"type": "string", "description": "Check-out date"},
                    "adults": {"type": "integer", "default": 1},
                    "children": {"type": "integer", "default": 0}
                },
                "required": ["check_in_date", "check_out_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_room_selection",
            "description": "User selected a room type. Proceed to payment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room_type_id": {"type": "integer", "description": "Selected room type ID"},
                    "check_in_date": {"type": "string"},
                    "check_out_date": {"type": "string"},
                    "adults": {"type": "integer", "default": 1},
                    "children": {"type": "integer", "default": 0},
                    "special_requests": {"type": "string", "description": "Optional special requests"}
                },
                "required": ["room_type_id", "check_in_date", "check_out_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": "Create a booking with 'pay at hotel' option. User profile data is used automatically. Call this when user wants to reserve now and pay later.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room_type_id": {"type": "integer", "description": "Room type ID to book"},
                    "check_in_date": {"type": "string", "description": "Check-in date (YYYY-MM-DD)"},
                    "check_out_date": {"type": "string", "description": "Check-out date (YYYY-MM-DD)"},
                    "adults": {"type": "integer", "default": 1},
                    "children": {"type": "integer", "default": 0},
                    "special_requests": {"type": "string", "description": "Optional special requests"}
                },
                "required": ["room_type_id", "check_in_date", "check_out_date"]
            }
        }
    },
    # ==================== PROFILE TOOLS ====================
    {
        "type": "function",
        "function": {
            "name": "update_profile",
            "description": "Update user profile information (address, phone, preferences).",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "New phone number"},
                    "address": {"type": "string", "description": "Street address"},
                    "city": {"type": "string", "description": "City"},
                    "country": {"type": "string", "description": "Country"},
                    "postal_code": {"type": "string", "description": "Postal/ZIP code"},
                    "dietary_restrictions": {"type": "string", "description": "Dietary restrictions or preferences"},
                    "room_preferences": {"type": "string", "description": "General room preferences"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_profile",
            "description": "Get current user profile information.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    # ==================== SERVICE REQUEST TOOLS ====================
    {
        "type": "function",
        "function": {
            "name": "create_service_request",
            "description": "Create a service request (housekeeping, maintenance, room service, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_type": {"type": "string", "enum": ["housekeeping", "maintenance", "room_service", "concierge", "laundry", "spa", "transport"]},
                    "title": {"type": "string", "description": "Brief title"},
                    "description": {"type": "string", "description": "Detailed description"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "default": "normal"},
                    "room_number": {"type": "string", "description": "Room number if known"}
                },
                "required": ["service_type", "title", "description"]
            }
        }
    },
    # ==================== HOTEL INFO ====================
    {
        "type": "function",
        "function": {
            "name": "get_hotel_info",
            "description": "Get hotel information, policies, amenities, or contact details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": ["amenities", "policies", "dining", "spa", "pool", "gym", "wifi", "parking", "checkout", "checkin", "contact", "location", "general"]}
                },
                "required": ["topic"]
            }
        }
    }
]


# =============================================================================
# Hotel Information
# =============================================================================

HOTEL_INFO = {
    "name": "Glimmora Hotel & Suites",
    "tagline": "Where Luxury Meets Serenity",
    "address": "123 Paradise Boulevard, Miami Beach, FL 33139",
    "phone": "+1 (305) 555-0100",
    "email": "concierge@glimmora.com",
    "checkin_time": "3:00 PM",
    "checkout_time": "11:00 AM",
    "early_checkin_fee": "₹4,000 (subject to availability)",
    "late_checkout_fee": "₹4,000 per hour (subject to availability)",
    "amenities": {
        "pool": "Infinity pool open 7 AM - 10 PM, heated year-round",
        "spa": "Full-service spa open 9 AM - 9 PM, reservations recommended",
        "gym": "24-hour fitness center with modern equipment",
        "wifi": "Complimentary high-speed WiFi throughout the property",
        "parking": "Valet parking ₹3,300/day, Self-parking ₹2,000/day",
        "dining": {
            "main_restaurant": "Azure Restaurant - Fine dining, 7 AM - 11 PM",
            "poolside": "Cabana Bar - Light fare and cocktails, 11 AM - 8 PM",
            "room_service": "24-hour room service available"
        }
    },
    "policies": {
        "cancellation": "Free cancellation up to 3 days before arrival. Within 3 days: 50% of first night. Same-day: Full night charge.",
        "pets": "Pet-friendly rooms available. ₹6,000/night pet fee. Max 2 pets, under 25 kg each.",
        "smoking": "Non-smoking property. Designated smoking areas available outside.",
        "children": "Children of all ages welcome. Rollaway beds and cribs available upon request."
    },
    "contact": {
        "front_desk": "Extension 0",
        "concierge": "Extension 100",
        "room_service": "Extension 200",
        "housekeeping": "Extension 300",
        "spa": "Extension 400",
        "valet": "Extension 500"
    }
}


# =============================================================================
# Orchestrator Class
# =============================================================================

class GuestAIOrchestrator:
    """
    AI Orchestrator with action-based responses.

    Returns structured action data that tells the frontend what UI to render.
    Uses profile data automatically - never asks for info we already have.
    """

    def __init__(self, db_session: AsyncSession, user: User):
        self.db = db_session
        self.user = user
        self.session_manager = get_chat_session_manager(db_session)
        self.booking_tools = BookingTools(db_session)
        self.precheckin_tools = PreCheckinTools(db_session)
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

        # Cache for current flow state
        self._pending_booking = None
        self._pending_precheckin = None

    async def process_message(
        self,
        message: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a user message and return response with action data.

        Returns:
            {
                "response": str,  # AI's text response
                "session_id": str,
                "intent": str,
                "action": {  # Optional - tells frontend what UI to show
                    "type": str,  # e.g., "show_room_options", "show_payment"
                    "data": dict,  # Data for the UI component
                    "await_selection": bool  # Whether to wait for user interaction
                },
                "requires_staff_action": bool
            }
        """
        try:
            # Get or create session
            if session_id:
                session = await self.session_manager.get_session_by_id(session_id)
                if not session or session.status != "active":
                    session, _ = await self.session_manager.get_or_create_session(self.user.id)
            else:
                session, _ = await self.session_manager.get_or_create_session(self.user.id)

            session_id = session.session_id

            # Load user context - THIS IS KEY: Never ask for this info
            user_profile = await self._get_full_user_profile()
            user_bookings = await self.session_manager.get_user_bookings(self.user.id)

            # Get conversation history
            recent_messages = await self.session_manager.get_recent_messages_for_context(
                session_id, limit=10
            )

            # Build system prompt with full context
            system_prompt = self._build_system_prompt(user_profile, user_bookings)

            # Build messages for OpenAI
            messages = [{"role": "system", "content": system_prompt}]
            for msg in recent_messages:
                role = "user" if msg["type"] == "user" else "assistant"
                messages.append({"role": role, "content": msg["content"]})
            messages.append({"role": "user", "content": message})

            # Call OpenAI with function calling
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=1000
            )

            assistant_message = response.choices[0].message
            action = None
            intent = "general"

            # Execute tool calls if any
            if assistant_message.tool_calls:
                tool_results = await self._execute_tool_calls(
                    assistant_message.tool_calls,
                    user_profile,
                    user_bookings
                )

                # Add to messages for final response
                messages.append(assistant_message)
                for tool_call, result in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result.get("_raw", result))
                    })

                # Extract action from tool results
                action = self._extract_action_from_results(tool_results)
                intent = self._get_intent_from_tools(assistant_message.tool_calls)

                # Get final response
                final_response = await self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.7,
                    max_tokens=800
                )
                response_text = final_response.choices[0].message.content or ""
            else:
                response_text = assistant_message.content or ""

            # Format response
            response_text = self._format_response(response_text, action)

            # Save conversation
            requires_staff = intent in ["service_request", "escalate"]
            conversation = await self.session_manager.save_conversation_turn(
                session_id=session_id,
                user_query=message,
                bot_response=response_text,
                classification=intent,
                requires_staff_action=requires_staff,
                extra_data={"action": action} if action else None
            )

            await self.db.commit()

            result = {
                "response": response_text,
                "session_id": session_id,
                "conversation_id": conversation.conversation_id,
                "intent": intent,
                "requires_staff_action": requires_staff
            }

            if action:
                result["action"] = action

            return result

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            await self.db.rollback()
            return {
                "response": "I apologize, but I encountered an issue. Please try again or contact front desk at extension 0.",
                "session_id": session_id,
                "intent": "error",
                "error": str(e)
            }

    async def _get_full_user_profile(self) -> Dict[str, Any]:
        """Get complete user profile including guest record details."""
        profile = {
            "id": self.user.id,
            "email": self.user.email,
            "full_name": self.user.full_name or "",
            "phone": self.user.phone or "",
        }

        # Parse name parts
        name_parts = (self.user.full_name or "").strip().split(" ", 1)
        profile["first_name"] = name_parts[0] if name_parts else ""
        profile["last_name"] = name_parts[1] if len(name_parts) > 1 else ""

        # Try to get additional info from Guest record
        try:
            result = await self.db.exec(
                select(Guest).where(Guest.email == self.user.email)
            )
            guest = result.first()
            if guest:
                profile["guest_id"] = guest.id
                profile["address"] = guest.address or ""
                profile["city"] = guest.city or ""
                profile["country"] = guest.country or ""
                profile["postal_code"] = guest.postal_code or ""
                profile["loyalty_tier"] = guest.loyalty_tier or "standard"
                profile["loyalty_points"] = guest.loyalty_points or 0
                profile["preferences"] = guest.preferences or {}
                if not profile["phone"] and guest.phone:
                    profile["phone"] = guest.phone
        except Exception as e:
            logger.debug(f"Could not load guest details: {e}")

        return profile

    async def _execute_tool_calls(
        self,
        tool_calls: List,
        user_profile: Dict,
        user_bookings: List[Dict]
    ) -> List[Tuple[Any, Dict]]:
        """Execute tool calls and return results with action metadata."""
        results = []

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}

            logger.info(f"Executing tool: {function_name} with args: {args}")

            try:
                result = await self._execute_single_tool(
                    function_name, args, user_profile, user_bookings
                )
            except Exception as e:
                logger.error(f"Tool execution error: {e}", exc_info=True)
                result = {
                    "success": False,
                    "error": str(e),
                    "_action": {"type": "show_error", "data": {"message": str(e)}}
                }

            results.append((tool_call, result))

        return results

    async def _execute_single_tool(
        self,
        function_name: str,
        args: Dict,
        user_profile: Dict,
        user_bookings: List[Dict]
    ) -> Dict[str, Any]:
        """Execute a single tool with action metadata."""

        # ==================== BOOKING LOOKUP ====================
        if function_name == "get_user_bookings":
            if not user_bookings:
                return {
                    "success": True,
                    "bookings": [],
                    "message": "No bookings found.",
                    "_raw": {"bookings": [], "count": 0}
                }

            formatted = []
            for b in user_bookings:
                formatted.append({
                    "confirmation_code": b.get("confirmation_code"),
                    "check_in": b.get("check_in"),
                    "check_out": b.get("check_out"),
                    "status": b.get("status"),
                    "room_type_id": b.get("room_type_id"),
                    "total_amount": b.get("total_amount")
                })

            return {
                "success": True,
                "bookings": formatted,
                "count": len(formatted),
                "_raw": {"bookings": formatted, "count": len(formatted)},
                "_action": {
                    "type": "show_bookings_list",
                    "data": {"bookings": formatted}
                }
            }

        elif function_name == "lookup_booking":
            result = await self.booking_tools.lookup_booking(
                confirmation_code=args.get("confirmation_code")
            )
            if result.get("found"):
                result["_action"] = {
                    "type": "show_booking_details",
                    "data": {"booking": result.get("booking")}
                }
            result["_raw"] = result.copy()
            return result

        # ==================== BOOKING MODIFICATION ====================
        elif function_name == "modify_booking_dates":
            lookup = await self.booking_tools.lookup_booking(
                confirmation_code=args.get("confirmation_code")
            )
            if not lookup.get("found"):
                return {**lookup, "_raw": lookup}

            booking = lookup["booking"]
            modifications = {}
            if args.get("new_check_in"):
                modifications["check_in_date"] = args["new_check_in"]
            if args.get("new_check_out"):
                modifications["check_out_date"] = args["new_check_out"]

            result = await self.booking_tools.modify_booking(
                booking_id=booking["id"],
                modifications=modifications,
                guest_id=booking.get("guest_id"),
                reason=args.get("reason", "Guest requested date change")
            )

            if result.get("success"):
                result["_action"] = {
                    "type": "show_modification_success",
                    "data": {
                        "confirmation_code": args.get("confirmation_code"),
                        "changes": modifications,
                        "message": result.get("message")
                    }
                }
            result["_raw"] = result.copy()
            return result

        elif function_name == "cancel_booking":
            result = await self.booking_tools.cancel_booking(
                confirmation_code=args.get("confirmation_code"),
                reason=args.get("reason", "Guest requested cancellation")
            )
            result["_raw"] = result.copy()
            if result.get("success"):
                result["_action"] = {
                    "type": "show_cancellation_success",
                    "data": {"confirmation_code": args.get("confirmation_code")}
                }
            return result

        # ==================== PRE-CHECKIN ====================
        elif function_name == "start_precheckin":
            # Verify booking first
            guest_name = user_profile.get("full_name", "")
            verify_result = await self.precheckin_tools.verify_booking_for_precheckin(
                confirmation_code=args.get("confirmation_code"),
                guest_name=guest_name
            )

            if not verify_result.get("eligible"):
                return {**verify_result, "_raw": verify_result}

            # Start pre-checkin with profile data
            start_result = await self.precheckin_tools.start_precheckin(
                reservation_id=verify_result["reservation_id"],
                email=user_profile.get("email", ""),
                phone=user_profile.get("phone", ""),
                is_booking=verify_result.get("is_booking", False)
            )

            start_result["booking_info"] = {
                "confirmation_code": verify_result.get("confirmation_code"),
                "guest_name": verify_result.get("guest_name"),
                "room_type": verify_result.get("room_type"),
                "arrival_date": verify_result.get("arrival_date"),
                "departure_date": verify_result.get("departure_date"),
                "nights": verify_result.get("nights")
            }

            # Return action to show preference form
            start_result["_action"] = {
                "type": "show_precheckin_preferences",
                "data": {
                    "precheckin_id": start_result.get("precheckin_id"),
                    "booking_info": start_result["booking_info"],
                    "current_step": 1,
                    "total_steps": 4
                },
                "await_selection": True
            }
            start_result["_raw"] = start_result.copy()
            return start_result

        elif function_name == "set_precheckin_preferences":
            result = await self.precheckin_tools.update_preferences(
                precheckin_id=args.get("precheckin_id"),
                floor_preference=args.get("floor_preference"),
                view_preference=args.get("view_preference"),
                bed_type_preference=args.get("bed_type_preference"),
                quietness_preference=args.get("quietness_preference"),
                arrival_time=args.get("arrival_time"),
                special_requests=args.get("special_requests"),
                early_check_in=args.get("early_check_in", False),
                late_check_out=args.get("late_check_out", False)
            )

            # After preferences, show room recommendations
            if result.get("success"):
                rooms = await self.precheckin_tools.get_room_recommendations(
                    precheckin_id=args.get("precheckin_id")
                )
                result["rooms"] = rooms.get("rooms", [])
                result["_action"] = {
                    "type": "show_precheckin_rooms",
                    "data": {
                        "precheckin_id": args.get("precheckin_id"),
                        "rooms": rooms.get("rooms", []),
                        "current_step": 2,
                        "total_steps": 4
                    },
                    "await_selection": True
                }
            result["_raw"] = result.copy()
            return result

        elif function_name == "get_room_recommendations":
            result = await self.precheckin_tools.get_room_recommendations(
                precheckin_id=args.get("precheckin_id")
            )
            result["_action"] = {
                "type": "show_precheckin_rooms",
                "data": {
                    "precheckin_id": args.get("precheckin_id"),
                    "rooms": result.get("rooms", []),
                    "current_step": 2,
                    "total_steps": 4
                },
                "await_selection": True
            }
            result["_raw"] = result.copy()
            return result

        elif function_name == "select_room":
            result = await self.precheckin_tools.select_room(
                precheckin_id=args.get("precheckin_id"),
                room_id=args.get("room_id")
            )
            if result.get("success"):
                result["_action"] = {
                    "type": "show_room_selected",
                    "data": {
                        "precheckin_id": args.get("precheckin_id"),
                        "selected_room": result.get("selected_room"),
                        "current_step": 3,
                        "total_steps": 4,
                        "next_action": "complete_precheckin"
                    }
                }
            result["_raw"] = result.copy()
            return result

        elif function_name == "complete_precheckin":
            result = await self.precheckin_tools.complete_precheckin(
                precheckin_id=args.get("precheckin_id"),
                skip_id_verification=args.get("skip_id_verification", True)
            )
            if result.get("success"):
                result["_action"] = {
                    "type": "show_digital_key",
                    "data": {
                        "digital_key": result.get("digital_key"),
                        "room_number": result.get("room_number"),
                        "check_in_time": result.get("check_in_time"),
                        "current_step": 4,
                        "total_steps": 4
                    }
                }
            result["_raw"] = result.copy()
            return result

        elif function_name == "get_precheckin_status":
            result = await self.precheckin_tools.get_precheckin_status(
                confirmation_code=args.get("confirmation_code")
            )
            result["_raw"] = result.copy()
            return result

        # ==================== NEW BOOKING ====================
        elif function_name == "browse_room_types":
            result = await self.booking_tools.browse_all_room_types(
                room_type_name=args.get("room_type_name")
            )
            # Transform room types to match frontend interface
            # Backend returns: id, base_price_per_night
            # Frontend expects: id, base_price
            transformed_rooms = []
            for rt in result.get("room_types", []):
                transformed_rooms.append({
                    "id": rt.get("id"),
                    "name": rt.get("name"),
                    "description": rt.get("description"),
                    "base_price": rt.get("base_price_per_night", 0),
                    "max_occupancy": rt.get("max_guests"),
                    "image_url": rt.get("image_url"),
                    "amenities": rt.get("amenities", []),
                })
            result["_action"] = {
                "type": "show_room_types_info",
                "data": {"room_types": transformed_rooms}
            }
            result["_raw"] = result.copy()
            return result

        elif function_name == "check_availability":
            result = await self.booking_tools.get_available_room_types(
                check_in_date=args.get("check_in_date"),
                check_out_date=args.get("check_out_date"),
                adults=args.get("adults", 1),
                children=args.get("children", 0)
            )
            if result.get("success") and result.get("room_types"):
                result["_action"] = {
                    "type": "show_available_rooms",
                    "data": {
                        "room_types": result.get("room_types", []),
                        "check_in": args.get("check_in_date"),
                        "check_out": args.get("check_out_date"),
                        "nights": result.get("nights", 1),
                        "guests": {"adults": args.get("adults", 1), "children": args.get("children", 0)}
                    }
                }
            result["_raw"] = result.copy()
            return result

        elif function_name == "initiate_booking":
            # Check availability first
            result = await self.booking_tools.get_available_room_types(
                check_in_date=args.get("check_in_date"),
                check_out_date=args.get("check_out_date"),
                adults=args.get("adults", 1),
                children=args.get("children", 0)
            )

            if result.get("success") and result.get("room_types"):
                # Transform room types to match frontend interface
                # Backend returns: room_type_id, pricing.per_night, max_guests, rooms_available
                # Frontend expects: id, base_price, max_occupancy, available_count
                transformed_rooms = []
                for rt in result.get("room_types", []):
                    pricing = rt.get("pricing", {})
                    transformed_rooms.append({
                        "id": rt.get("room_type_id"),
                        "name": rt.get("name"),
                        "description": rt.get("description"),
                        "base_price": pricing.get("per_night", 0),
                        "max_occupancy": rt.get("max_guests"),
                        "image_url": rt.get("image_url"),
                        "amenities": rt.get("amenities", []),
                        "available_count": rt.get("rooms_available"),
                        # Keep full pricing for display
                        "pricing": pricing
                    })

                # Calculate nights from dates
                try:
                    check_in = datetime.strptime(args.get("check_in_date"), "%Y-%m-%d").date()
                    check_out = datetime.strptime(args.get("check_out_date"), "%Y-%m-%d").date()
                    nights = (check_out - check_in).days
                except:
                    nights = 1

                # Return room options with user info pre-filled
                result["_action"] = {
                    "type": "show_room_selection",
                    "data": {
                        "room_types": transformed_rooms,
                        "check_in": args.get("check_in_date"),
                        "check_out": args.get("check_out_date"),
                        "nights": nights,
                        "guests": {"adults": args.get("adults", 1), "children": args.get("children", 0)},
                        "guest_info": {  # Pre-filled from profile
                            "first_name": user_profile.get("first_name"),
                            "last_name": user_profile.get("last_name"),
                            "email": user_profile.get("email"),
                            "phone": user_profile.get("phone"),
                            "country": user_profile.get("country", "United States")
                        }
                    },
                    "await_selection": True
                }
            result["_raw"] = result.copy()
            return result

        elif function_name == "confirm_room_selection":
            # Create the booking with profile data
            room_type_id = args.get("room_type_id")

            # Get room type details for the response
            room_types = await self.booking_tools.browse_all_room_types()
            room_type = next((r for r in room_types.get("room_types", []) if r.get("id") == room_type_id), None)

            # Calculate total
            try:
                check_in = datetime.strptime(args.get("check_in_date"), "%Y-%m-%d").date()
                check_out = datetime.strptime(args.get("check_out_date"), "%Y-%m-%d").date()
                nights = (check_out - check_in).days
            except:
                nights = 1

            # Note: browse_all_room_types returns base_price_per_night, not base_price
            # Use GST slab-based tax: ≤₹7,500 = 12%, >₹7,500 = 18%, plus 5% service fee
            from app.core.tax import calculate_booking_taxes
            nightly_rate = room_type.get("base_price_per_night", 0) if room_type else 200
            tax_calc = calculate_booking_taxes(nightly_rate, nights)
            subtotal = tax_calc["calculated_base"]
            tax = tax_calc["taxes"]
            service_fee = tax_calc["service_fee"]
            total = tax_calc["total_price"]

            # Return payment action
            return {
                "success": True,
                "message": "Room selected. Please complete payment.",
                "_raw": {
                    "room_type_id": room_type_id,
                    "room_type_name": room_type.get("name") if room_type else "Room",
                    "check_in": args.get("check_in_date"),
                    "check_out": args.get("check_out_date"),
                    "nights": nights,
                    "total": total
                },
                "_action": {
                    "type": "show_payment",
                    "data": {
                        "booking_summary": {
                            "room_type_id": room_type_id,
                            "room_type_name": room_type.get("name") if room_type else "Room",
                            "room_type_image": room_type.get("image_url") if room_type else None,
                            "check_in": args.get("check_in_date"),
                            "check_out": args.get("check_out_date"),
                            "nights": nights,
                            "adults": args.get("adults", 1),
                            "children": args.get("children", 0),
                            "special_requests": args.get("special_requests"),
                            "pricing": {
                                "nightly_rate": nightly_rate,
                                "subtotal": subtotal,
                                "tax": round(tax, 2),
                                "service_fee": round(service_fee, 2),
                                "total": round(total, 2)
                            }
                        },
                        "guest_info": {
                            "first_name": user_profile.get("first_name"),
                            "last_name": user_profile.get("last_name"),
                            "email": user_profile.get("email"),
                            "phone": user_profile.get("phone"),
                            "country": user_profile.get("country", "United States")
                        }
                    },
                    "await_completion": True  # Wait for payment to complete
                }
            }

        elif function_name == "create_booking":
            # Create booking with pay-at-hotel option (payment_status="pending")
            result = await self.booking_tools.create_booking(
                room_type_id=args.get("room_type_id"),
                check_in_date=args.get("check_in_date"),
                check_out_date=args.get("check_out_date"),
                guest_first_name=user_profile.get("first_name", ""),
                guest_last_name=user_profile.get("last_name", ""),
                guest_email=user_profile.get("email", ""),
                guest_phone=user_profile.get("phone", ""),
                guest_country=user_profile.get("country", "United States"),
                adults=args.get("adults", 1),
                children=args.get("children", 0),
                special_requests=args.get("special_requests")
            )

            if result.get("success"):
                booking = result.get("booking", {})
                result["_action"] = {
                    "type": "show_booking_confirmation",
                    "data": {
                        "booking": {
                            "confirmation_code": booking.get("confirmation_code"),
                            "booking_id": booking.get("booking_id"),
                            "room_type": booking.get("room_type"),
                            "check_in": booking.get("check_in"),
                            "check_out": booking.get("check_out"),
                            "nights": booking.get("nights"),
                            "guests": booking.get("guests"),
                            "pricing": booking.get("pricing"),
                            "guest_name": booking.get("guest_name"),
                            "guest_email": booking.get("guest_email"),
                            "status": booking.get("status"),
                            "payment_status": "pay_at_hotel",
                            "precheckin_url": booking.get("precheckin_url")
                        }
                    }
                }
            else:
                result["_action"] = {
                    "type": "show_error",
                    "data": {"message": result.get("message", "Failed to create booking")}
                }
            result["_raw"] = result.copy()
            return result

        # ==================== PROFILE ====================
        elif function_name == "get_profile":
            return {
                "success": True,
                "profile": user_profile,
                "_raw": {"profile": user_profile},
                "_action": {
                    "type": "show_profile",
                    "data": {"profile": user_profile}
                }
            }

        elif function_name == "update_profile":
            # Update user and guest records
            updates = {}
            if args.get("phone"):
                updates["phone"] = args["phone"]
                self.user.phone = args["phone"]

            # Update Guest record if exists
            try:
                result = await self.db.exec(
                    select(Guest).where(Guest.email == self.user.email)
                )
                guest = result.first()
                if guest:
                    if args.get("address"):
                        guest.address = args["address"]
                    if args.get("city"):
                        guest.city = args["city"]
                    if args.get("country"):
                        guest.country = args["country"]
                    if args.get("postal_code"):
                        guest.postal_code = args["postal_code"]
                    if args.get("phone"):
                        guest.phone = args["phone"]
                    guest.updated_at = datetime.utcnow()
                    self.db.add(guest)

                self.db.add(self.user)
                await self.db.flush()

                return {
                    "success": True,
                    "message": "Profile updated successfully.",
                    "_raw": {"updated_fields": list(args.keys())},
                    "_action": {
                        "type": "show_profile_updated",
                        "data": {"updated_fields": list(args.keys())}
                    }
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "_raw": {"error": str(e)}
                }

        # ==================== SERVICE REQUESTS ====================
        elif function_name == "create_service_request":
            room_number = args.get("room_number")
            booking_id = None
            guest_id = user_profile.get("guest_id")

            if user_bookings:
                for b in user_bookings:
                    if b.get("status") == "checked_in":
                        booking_id = b.get("id")
                        break
                if not booking_id:
                    booking_id = user_bookings[0].get("id") if user_bookings else None

            task = await self.session_manager.create_staff_task(
                task_type=args.get("service_type"),
                title=args.get("title"),
                description=args.get("description"),
                conversation_id=f"ai_request_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                booking_id=booking_id,
                guest_id=guest_id,
                room_number=room_number,
                priority=args.get("priority", "normal")
            )

            return {
                "success": True,
                "task_id": task.id,
                "service_type": args.get("service_type"),
                "message": f"Your {args.get('service_type')} request has been submitted.",
                "_raw": {"task_id": task.id, "status": "pending"},
                "_action": {
                    "type": "show_service_request_created",
                    "data": {
                        "task_id": task.id,
                        "service_type": args.get("service_type"),
                        "title": args.get("title"),
                        "estimated_response": self._get_estimated_response_time(args.get("priority", "normal"))
                    }
                }
            }

        # ==================== HOTEL INFO ====================
        elif function_name == "get_hotel_info":
            topic = args.get("topic", "general")
            result = self._get_hotel_info(topic)
            result["_raw"] = result.copy()
            return result

        else:
            return {"success": False, "message": f"Unknown function: {function_name}", "_raw": {}}

    def _get_hotel_info(self, topic: str) -> Dict[str, Any]:
        """Get hotel information for a specific topic."""
        info = HOTEL_INFO

        if topic == "general":
            return {
                "success": True,
                "hotel_name": info["name"],
                "tagline": info["tagline"],
                "address": info["address"],
                "phone": info["phone"],
                "email": info["email"]
            }
        elif topic == "checkin":
            return {
                "success": True,
                "checkin_time": info["checkin_time"],
                "early_checkin": info["early_checkin_fee"]
            }
        elif topic == "checkout":
            return {
                "success": True,
                "checkout_time": info["checkout_time"],
                "late_checkout": info["late_checkout_fee"]
            }
        elif topic == "amenities":
            return {"success": True, "amenities": info["amenities"]}
        elif topic == "policies":
            return {"success": True, "policies": info["policies"]}
        elif topic == "contact":
            return {"success": True, "contacts": info["contact"]}
        elif topic in ["dining", "spa", "pool", "gym", "wifi", "parking"]:
            if topic == "dining":
                return {"success": True, "dining": info["amenities"]["dining"]}
            return {"success": True, topic: info["amenities"].get(topic, "Information not available")}
        else:
            return {
                "success": True,
                "hotel_name": info["name"],
                "phone": info["phone"]
            }

    def _get_estimated_response_time(self, priority: str) -> str:
        """Get estimated response time based on priority."""
        times = {
            "urgent": "15 minutes",
            "high": "30 minutes",
            "normal": "1 hour",
            "low": "2-4 hours"
        }
        return times.get(priority, "1 hour")

    def _build_system_prompt(
        self,
        user_profile: Dict,
        user_bookings: List[Dict]
    ) -> str:
        """Build system prompt with user context."""
        guest_name = user_profile.get("full_name", "Guest")
        first_name = user_profile.get("first_name", "")

        # Build booking context
        booking_context = ""
        if user_bookings:
            booking_list = []
            for b in user_bookings:
                status = b.get("status", "unknown")
                booking_list.append(
                    f"  - {b.get('confirmation_code')}: {b.get('check_in')} to {b.get('check_out')} ({status})"
                )
            booking_context = f"\n\nGuest's bookings:\n" + "\n".join(booking_list)

        # Format loyalty info
        loyalty_tier = user_profile.get('loyalty_tier', 'standard').title()
        loyalty_points = user_profile.get('loyalty_points', 0)

        return f"""You are Aria, the AI concierge at Glimmora Hotel & Suites.

CURRENT GUEST: {guest_name}
- Email: {user_profile.get('email')}
- Phone: {user_profile.get('phone') or 'Not provided'}
- First Name: {first_name}
- Last Name: {user_profile.get('last_name', '')}
- Loyalty Tier: {loyalty_tier}
- Loyalty Points: {loyalty_points:,}
{booking_context}

CRITICAL RULES:

1. NEVER ASK FOR INFORMATION YOU ALREADY HAVE:
   - Do NOT ask for name, email, or phone - you have them above
   - When creating bookings, USE the profile data automatically
   - Only ask for dates and preferences (room type, special requests)

2. USE TOOLS TO PERFORM REAL ACTIONS:
   - For new bookings: use initiate_booking with dates → show room options → confirm_room_selection triggers payment
   - For pre-check-in: use start_precheckin → user sets preferences → show rooms → select → complete
   - For modifications: use modify_booking_dates - it ACTUALLY changes the database
   - For cancellations: use cancel_booking - confirm first, then execute

3. BOOKING FLOW (follow this exactly):
   a. User says "I want to book" → Ask for dates and number of guests only
   b. Call initiate_booking → This shows room options to user
   c. User picks room → Call confirm_room_selection → This triggers payment UI
   d. Two payment options:
      - "Pay Now" → User goes to payment page
      - "Pay at Hotel" → User says "create my booking with pay-at-hotel" → Call create_booking tool

4. PRE-CHECK-IN FLOW:
   a. User wants pre-check-in → Call start_precheckin
   b. This shows preference form → User submits preferences
   c. Show AI-recommended rooms → User selects
   d. Call complete_precheckin → Show digital key

5. RESPONSE FORMAT:
   - Keep responses SHORT (2-3 sentences max)
   - Use bullet points for lists
   - Include confirmation codes when relevant
   - Be warm but concise

6. PROFILE EDITING:
   - User can update address, phone, preferences via update_profile tool

Address user as "{first_name}" if known, otherwise "there"."""

    def _format_response(self, text: str, action: Optional[Dict] = None) -> str:
        """Format response for readability."""
        if not text:
            return text

        # Clean up excessive whitespace
        text = text.strip()

        # If there's an action that shows UI, keep response brief
        if action and action.get("type") in [
            "show_room_selection", "show_payment", "show_precheckin_preferences",
            "show_precheckin_rooms", "show_digital_key"
        ]:
            # Remove verbose explanations if UI will show the data
            lines = text.split("\n")
            filtered = []
            for line in lines[:5]:  # Keep only first 5 lines max
                if len(line) < 200:  # Skip very long lines
                    filtered.append(line)
            text = "\n".join(filtered)

        return text

    def _get_intent_from_tools(self, tool_calls: List) -> str:
        """Determine intent from tool calls."""
        if not tool_calls:
            return "general"

        function_names = [tc.function.name for tc in tool_calls]

        if any("precheckin" in fn for fn in function_names):
            return "precheckin"
        elif any(fn in ["initiate_booking", "confirm_room_selection", "check_availability", "create_booking"] for fn in function_names):
            return "new_booking"
        elif any(fn in ["modify_booking_dates", "cancel_booking", "lookup_booking"] for fn in function_names):
            return "booking_management"
        elif any(fn in ["update_profile", "get_profile"] for fn in function_names):
            return "profile"
        elif "create_service_request" in function_names:
            return "service_request"
        elif "get_hotel_info" in function_names:
            return "hotel_info"
        elif "get_user_bookings" in function_names:
            return "check_bookings"
        else:
            return "general"

    def _extract_action_from_results(self, tool_results: List[Tuple]) -> Optional[Dict]:
        """Extract the primary action from tool results."""
        for tool_call, result in tool_results:
            if "_action" in result:
                return result["_action"]
        return None


# =============================================================================
# Factory Functions
# =============================================================================

async def create_guest_ai_orchestrator(
    db_session: AsyncSession,
    user: User
) -> GuestAIOrchestrator:
    """Create a GuestAIOrchestrator instance."""
    return GuestAIOrchestrator(db_session, user)


def get_guest_ai_orchestrator(db: AsyncSession, user_id: int) -> GuestAIOrchestrator:
    """Alternate factory for compatibility."""
    class MinimalUser:
        def __init__(self, user_id: int):
            self.id = user_id
            self.full_name = "Guest"
            self.email = ""
            self.phone = ""

    return GuestAIOrchestrator(db, MinimalUser(user_id))
