"""
Glimmora AGI Guest Assistant V2
Comprehensive AI-powered guest assistant with full booking flow, authentication,
OTP verification, profile management, loyalty system, and in-house services.
"""

# V2 is the new comprehensive AGI system
from .guest_agi_v2 import GuestAGIV2, get_guest_agi_v2, AGIResponse

# Legacy agent (kept for reference)
from .agi_guest_agent import AGIGuestAgent as LegacyAGIGuestAgent

# Tools (still used by V2)
from .tools import (
    HousekeepingTools,
    MaintenanceTools,
    RoomServiceTools,
    ConciergeTools,
    BillingTools,
    BookingTools,
    HotelInfoTools,
)
from .memory import GuestMemoryManager
from .voice_processor import VoiceProcessor

# Use V2 as the default
AGIGuestAgent = GuestAGIV2
get_agi_agent = get_guest_agi_v2

__all__ = [
    # V2 (default)
    "AGIGuestAgent",
    "get_agi_agent",
    "AGIResponse",
    "GuestAGIV2",
    "get_guest_agi_v2",
    # Legacy
    "LegacyAGIGuestAgent",
    # Tools
    "HousekeepingTools",
    "MaintenanceTools",
    "RoomServiceTools",
    "ConciergeTools",
    "BillingTools",
    "BookingTools",
    "HotelInfoTools",
    # Memory & Voice
    "GuestMemoryManager",
    "VoiceProcessor",
]
