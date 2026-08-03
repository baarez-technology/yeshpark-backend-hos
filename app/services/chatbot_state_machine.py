"""
Conversation State Machine for Guest AI Chatbot

This module manages multi-step conversation flows for complex operations like:
- Room search and booking
- Pre-checkin process
- Profile updates
- Booking modifications
"""

from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json


class ConversationState(Enum):
    """Multi-step conversation states for different flows"""

    # Idle state - ready for new conversation
    IDLE = "idle"

    # Room Search Flow
    ROOM_SEARCH_DATES = "room_search_dates"       # Collecting check-in/check-out dates
    ROOM_SEARCH_GUESTS = "room_search_guests"     # Collecting guest count
    ROOM_SEARCH_RESULTS = "room_search_results"   # Showing available rooms

    # Booking Flow (extends room search)
    BOOKING_ROOM_SELECT = "booking_room_select"   # Guest selecting a room type
    BOOKING_GUEST_INFO = "booking_guest_info"     # Collecting guest details
    BOOKING_PAYMENT = "booking_payment"           # Payment information
    BOOKING_CONFIRM = "booking_confirm"           # Final confirmation

    # Pre-Checkin Flow
    PRECHECKIN_VERIFY = "precheckin_verify"       # Verify booking number
    PRECHECKIN_CONTACT = "precheckin_contact"     # Confirm/update contact info
    PRECHECKIN_PREFERENCES = "precheckin_prefs"   # Room preferences (floor, view, etc.)
    PRECHECKIN_ID_UPLOAD = "precheckin_id"        # ID document verification
    PRECHECKIN_ROOM_SELECT = "precheckin_room"    # AI room recommendations
    PRECHECKIN_COMPLETE = "precheckin_complete"   # Final confirmation with digital key

    # Profile Update Flow
    PROFILE_FIELD_SELECT = "profile_field"        # Which field to update
    PROFILE_VALUE_INPUT = "profile_value"         # New value input
    PROFILE_CONFIRM = "profile_confirm"           # Confirm the change

    # Booking Modification Flow
    MODIFY_BOOKING_SELECT = "modify_booking_select"  # Select which booking to modify
    MODIFY_FIELD_SELECT = "modify_field"             # What to modify (dates, guests, etc.)
    MODIFY_VALUE_INPUT = "modify_value"              # New value
    MODIFY_CONFIRM = "modify_confirm"                # Confirm modification

    # Booking Cancellation Flow
    CANCEL_VERIFY = "cancel_verify"               # Verify booking to cancel
    CANCEL_REASON = "cancel_reason"               # Cancellation reason
    CANCEL_CONFIRM = "cancel_confirm"             # Final confirmation


class FlowType(Enum):
    """Types of conversation flows"""
    ROOM_SEARCH = "room_search"
    BOOKING = "booking"
    PRECHECKIN = "precheckin"
    PROFILE_VIEW = "profile_view"
    PROFILE_UPDATE = "profile_update"
    BOOKING_MODIFY = "booking_modify"
    BOOKING_CANCEL = "booking_cancel"
    MY_BOOKINGS = "my_bookings"


@dataclass
class ConversationContext:
    """Tracks multi-step conversation state and collected data"""

    state: ConversationState = ConversationState.IDLE
    flow_type: Optional[str] = None
    step_data: Dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    last_activity: datetime = field(default_factory=datetime.utcnow)

    # Session timeout in minutes
    TIMEOUT_MINUTES = 30

    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = datetime.utcnow() + timedelta(minutes=self.TIMEOUT_MINUTES)

    def set_data(self, key: str, value: Any) -> None:
        """Store data for the current flow step"""
        self.step_data[key] = value
        self.last_activity = datetime.utcnow()

    def get_data(self, key: str, default: Any = None) -> Any:
        """Retrieve stored data"""
        return self.step_data.get(key, default)

    def has_data(self, key: str) -> bool:
        """Check if data exists"""
        return key in self.step_data

    def reset(self) -> None:
        """Reset conversation to idle state"""
        self.state = ConversationState.IDLE
        self.flow_type = None
        self.step_data = {}
        self.started_at = datetime.utcnow()
        self.expires_at = datetime.utcnow() + timedelta(minutes=self.TIMEOUT_MINUTES)
        self.last_activity = datetime.utcnow()

    def is_expired(self) -> bool:
        """Check if conversation has timed out"""
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return True
        # Also check inactivity
        if datetime.utcnow() - self.last_activity > timedelta(minutes=self.TIMEOUT_MINUTES):
            return True
        return False

    def extend_timeout(self) -> None:
        """Extend the conversation timeout"""
        self.expires_at = datetime.utcnow() + timedelta(minutes=self.TIMEOUT_MINUTES)
        self.last_activity = datetime.utcnow()

    def is_in_flow(self) -> bool:
        """Check if currently in a multi-step flow"""
        return self.state != ConversationState.IDLE

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for database storage"""
        return {
            "state": self.state.value,
            "flow_type": self.flow_type,
            "step_data": self.step_data,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationContext":
        """Deserialize from dictionary"""
        if not data:
            return cls()

        return cls(
            state=ConversationState(data.get("state", "idle")),
            flow_type=data.get("flow_type"),
            step_data=data.get("step_data", {}),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else datetime.utcnow(),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            last_activity=datetime.fromisoformat(data["last_activity"]) if data.get("last_activity") else datetime.utcnow(),
        )

    def to_json(self) -> str:
        """Serialize to JSON string"""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "ConversationContext":
        """Deserialize from JSON string"""
        if not json_str:
            return cls()
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, ValueError):
            return cls()


class StateMachine:
    """Manages conversation state transitions and flow definitions"""

    # Define the sequence of states for each flow
    FLOW_DEFINITIONS: Dict[str, List[ConversationState]] = {
        FlowType.ROOM_SEARCH.value: [
            ConversationState.ROOM_SEARCH_DATES,
            ConversationState.ROOM_SEARCH_GUESTS,
            ConversationState.ROOM_SEARCH_RESULTS,
        ],
        FlowType.BOOKING.value: [
            ConversationState.ROOM_SEARCH_DATES,
            ConversationState.ROOM_SEARCH_GUESTS,
            ConversationState.ROOM_SEARCH_RESULTS,
            ConversationState.BOOKING_ROOM_SELECT,
            ConversationState.BOOKING_GUEST_INFO,
            ConversationState.BOOKING_CONFIRM,
        ],
        FlowType.PRECHECKIN.value: [
            ConversationState.PRECHECKIN_VERIFY,
            ConversationState.PRECHECKIN_CONTACT,
            ConversationState.PRECHECKIN_PREFERENCES,
            ConversationState.PRECHECKIN_ID_UPLOAD,
            ConversationState.PRECHECKIN_ROOM_SELECT,
            ConversationState.PRECHECKIN_COMPLETE,
        ],
        FlowType.PROFILE_UPDATE.value: [
            ConversationState.PROFILE_FIELD_SELECT,
            ConversationState.PROFILE_VALUE_INPUT,
            ConversationState.PROFILE_CONFIRM,
        ],
        FlowType.BOOKING_MODIFY.value: [
            ConversationState.MODIFY_BOOKING_SELECT,
            ConversationState.MODIFY_FIELD_SELECT,
            ConversationState.MODIFY_VALUE_INPUT,
            ConversationState.MODIFY_CONFIRM,
        ],
        FlowType.BOOKING_CANCEL.value: [
            ConversationState.CANCEL_VERIFY,
            ConversationState.CANCEL_REASON,
            ConversationState.CANCEL_CONFIRM,
        ],
    }

    # User-friendly step labels for each state
    STATE_LABELS: Dict[ConversationState, str] = {
        ConversationState.IDLE: "Ready",
        # Room Search
        ConversationState.ROOM_SEARCH_DATES: "Select Dates",
        ConversationState.ROOM_SEARCH_GUESTS: "Guest Count",
        ConversationState.ROOM_SEARCH_RESULTS: "View Results",
        # Booking
        ConversationState.BOOKING_ROOM_SELECT: "Select Room",
        ConversationState.BOOKING_GUEST_INFO: "Guest Details",
        ConversationState.BOOKING_PAYMENT: "Payment",
        ConversationState.BOOKING_CONFIRM: "Confirm Booking",
        # Pre-checkin
        ConversationState.PRECHECKIN_VERIFY: "Verify Booking",
        ConversationState.PRECHECKIN_CONTACT: "Contact Info",
        ConversationState.PRECHECKIN_PREFERENCES: "Room Preferences",
        ConversationState.PRECHECKIN_ID_UPLOAD: "ID Verification",
        ConversationState.PRECHECKIN_ROOM_SELECT: "Room Selection",
        ConversationState.PRECHECKIN_COMPLETE: "Complete",
        # Profile
        ConversationState.PROFILE_FIELD_SELECT: "Select Field",
        ConversationState.PROFILE_VALUE_INPUT: "Enter Value",
        ConversationState.PROFILE_CONFIRM: "Confirm Update",
        # Booking Modification
        ConversationState.MODIFY_BOOKING_SELECT: "Select Booking",
        ConversationState.MODIFY_FIELD_SELECT: "What to Change",
        ConversationState.MODIFY_VALUE_INPUT: "New Value",
        ConversationState.MODIFY_CONFIRM: "Confirm Change",
        # Cancellation
        ConversationState.CANCEL_VERIFY: "Verify Booking",
        ConversationState.CANCEL_REASON: "Cancellation Reason",
        ConversationState.CANCEL_CONFIRM: "Confirm Cancellation",
    }

    def __init__(self):
        pass

    def start_flow(self, context: ConversationContext, flow_type: str) -> ConversationState:
        """Start a new conversation flow"""
        if flow_type not in self.FLOW_DEFINITIONS:
            raise ValueError(f"Unknown flow type: {flow_type}")

        context.reset()
        context.flow_type = flow_type
        first_state = self.FLOW_DEFINITIONS[flow_type][0]
        context.state = first_state
        context.extend_timeout()

        return first_state

    def get_current_step_info(self, context: ConversationContext) -> Dict[str, Any]:
        """Get information about the current step in the flow"""
        if not context.flow_type or context.flow_type not in self.FLOW_DEFINITIONS:
            return {
                "flow_type": None,
                "current_step": 0,
                "total_steps": 0,
                "step_label": "Ready",
                "progress": 0,
            }

        flow = self.FLOW_DEFINITIONS[context.flow_type]
        try:
            current_idx = flow.index(context.state)
        except ValueError:
            current_idx = 0

        return {
            "flow_type": context.flow_type,
            "current_step": current_idx + 1,
            "total_steps": len(flow),
            "step_label": self.STATE_LABELS.get(context.state, "Unknown"),
            "progress": int((current_idx + 1) / len(flow) * 100),
            "can_go_back": current_idx > 0,
            "can_cancel": True,
        }

    def can_transition(self, context: ConversationContext, to_state: ConversationState) -> bool:
        """Check if a transition to the target state is valid"""
        # Can always go to IDLE (cancel/reset)
        if to_state == ConversationState.IDLE:
            return True

        if not context.flow_type or context.flow_type not in self.FLOW_DEFINITIONS:
            return False

        flow = self.FLOW_DEFINITIONS[context.flow_type]

        try:
            current_idx = flow.index(context.state)
            to_idx = flow.index(to_state)
        except ValueError:
            return False

        # Allow forward progression by one step
        if to_idx == current_idx + 1:
            return True

        # Allow going back one step
        if to_idx == current_idx - 1:
            return True

        return False

    def next_state(self, context: ConversationContext) -> Optional[ConversationState]:
        """Get the next state in the current flow"""
        if not context.flow_type or context.flow_type not in self.FLOW_DEFINITIONS:
            return None

        flow = self.FLOW_DEFINITIONS[context.flow_type]

        try:
            current_idx = flow.index(context.state)
        except ValueError:
            return None

        if current_idx + 1 < len(flow):
            return flow[current_idx + 1]

        # Flow complete
        return ConversationState.IDLE

    def previous_state(self, context: ConversationContext) -> Optional[ConversationState]:
        """Get the previous state in the current flow"""
        if not context.flow_type or context.flow_type not in self.FLOW_DEFINITIONS:
            return None

        flow = self.FLOW_DEFINITIONS[context.flow_type]

        try:
            current_idx = flow.index(context.state)
        except ValueError:
            return None

        if current_idx > 0:
            return flow[current_idx - 1]

        # At the beginning
        return None

    def advance(self, context: ConversationContext) -> ConversationState:
        """Advance to the next state in the flow"""
        next_st = self.next_state(context)
        if next_st:
            context.state = next_st
            context.extend_timeout()
        return context.state

    def go_back(self, context: ConversationContext) -> ConversationState:
        """Go back to the previous state in the flow"""
        prev_st = self.previous_state(context)
        if prev_st:
            context.state = prev_st
            context.extend_timeout()
        return context.state

    def is_flow_complete(self, context: ConversationContext) -> bool:
        """Check if the current flow is complete"""
        if not context.flow_type or context.flow_type not in self.FLOW_DEFINITIONS:
            return True

        flow = self.FLOW_DEFINITIONS[context.flow_type]
        try:
            current_idx = flow.index(context.state)
        except ValueError:
            return False

        return current_idx == len(flow) - 1

    def get_required_data_for_state(self, state: ConversationState) -> List[str]:
        """Get the data keys required for a specific state"""
        REQUIRED_DATA = {
            ConversationState.ROOM_SEARCH_GUESTS: ["arrival_date", "departure_date"],
            ConversationState.ROOM_SEARCH_RESULTS: ["arrival_date", "departure_date", "adults"],
            ConversationState.BOOKING_ROOM_SELECT: ["arrival_date", "departure_date", "adults", "search_results"],
            ConversationState.BOOKING_GUEST_INFO: ["selected_room_type"],
            ConversationState.BOOKING_CONFIRM: ["guest_info"],
            ConversationState.PRECHECKIN_CONTACT: ["reservation_id", "booking_info"],
            ConversationState.PRECHECKIN_PREFERENCES: ["contact_confirmed"],
            ConversationState.PRECHECKIN_ID_UPLOAD: ["preferences_set"],
            ConversationState.PRECHECKIN_ROOM_SELECT: ["id_verified"],
            ConversationState.PRECHECKIN_COMPLETE: ["selected_room_id"],
            ConversationState.PROFILE_VALUE_INPUT: ["field_to_update"],
            ConversationState.PROFILE_CONFIRM: ["new_value"],
            ConversationState.MODIFY_FIELD_SELECT: ["booking_id"],
            ConversationState.MODIFY_VALUE_INPUT: ["field_to_modify"],
            ConversationState.MODIFY_CONFIRM: ["new_value"],
            ConversationState.CANCEL_REASON: ["booking_id"],
            ConversationState.CANCEL_CONFIRM: ["cancellation_reason"],
        }
        return REQUIRED_DATA.get(state, [])

    def validate_state_data(self, context: ConversationContext) -> Tuple[bool, List[str]]:
        """Validate that all required data is present for the current state"""
        required = self.get_required_data_for_state(context.state)
        missing = [key for key in required if not context.has_data(key)]
        return len(missing) == 0, missing


# Singleton instance
state_machine = StateMachine()
