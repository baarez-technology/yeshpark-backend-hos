"""
Hotel Configuration Loader

This module provides a centralized way to load and access hotel configuration.
The configuration is loaded from hotel_config.json and can be easily customized
for different hotel deployments.

Usage:
    from app.config import get_hotel_config

    config = get_hotel_config()
    hotel_name = config.hotel.name
    phone = config.contact.phone.main
"""

import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from functools import lru_cache


# ============================================================================
# Configuration Models
# ============================================================================

class PhoneConfig(BaseModel):
    main: str
    reservations: str
    emergency: str


class EmailConfig(BaseModel):
    general: str
    reservations: str
    support: str
    feedback: str


class AddressConfig(BaseModel):
    street: str
    city: str
    state: str
    zip: str
    country: str

    @property
    def full_address(self) -> str:
        return f"{self.street}, {self.city}, {self.state} {self.zip}, {self.country}"


class SocialConfig(BaseModel):
    instagram: str
    facebook: str
    twitter: str


class ContactConfig(BaseModel):
    phone: PhoneConfig
    email: EmailConfig
    address: AddressConfig
    social: SocialConfig


class HotelInfo(BaseModel):
    name: str
    tagline: str
    full_name: str
    description: str


class RestaurantHours(BaseModel):
    breakfast: str
    lunch: str
    dinner: str


class HoursConfig(BaseModel):
    front_desk: str
    check_in: str
    check_out: str
    early_check_in: str
    late_check_out: str
    restaurant: RestaurantHours
    spa: str
    gym: str
    pool: str


class CancellationPolicy(BaseModel):
    free_cancellation_hours: int
    penalty_percentage: int
    description: str


class PaymentPolicy(BaseModel):
    accepted_methods: List[str]
    deposit_required: bool
    deposit_percentage: int
    full_payment_due: str


class PetPolicy(BaseModel):
    allowed: bool
    fee_per_night: int
    max_weight_lbs: int
    description: str


class PoliciesConfig(BaseModel):
    cancellation: CancellationPolicy
    payment: PaymentPolicy
    pets: PetPolicy
    smoking: str
    age_requirement: str
    id_requirement: str


class AmenitiesConfig(BaseModel):
    complimentary: List[str]
    premium: List[str]


class RoomTypeConfig(BaseModel):
    name: str
    description: str
    max_occupancy: int
    bed_type: str


class AIAssistantConfig(BaseModel):
    name: str
    personality: str
    greeting: str
    fallback_message: str
    escalation_message: str


class SupportConfig(BaseModel):
    human_handoff_message: str
    emergency_message: str
    feedback_message: str


class HotelConfig(BaseModel):
    """
    Main hotel configuration class.

    This class holds all configurable hotel information that can be
    customized for different hotel deployments.
    """
    hotel: HotelInfo
    contact: ContactConfig
    hours: HoursConfig
    policies: PoliciesConfig
    amenities: AmenitiesConfig
    room_types: List[RoomTypeConfig]
    ai_assistant: AIAssistantConfig
    support: SupportConfig

    def get_formatted_greeting(self) -> str:
        """Get the AI greeting with placeholders replaced."""
        return self._format_template(self.ai_assistant.greeting)

    def get_formatted_fallback(self) -> str:
        """Get the fallback message with placeholders replaced."""
        return self._format_template(self.ai_assistant.fallback_message)

    def get_formatted_escalation(self) -> str:
        """Get the escalation message with placeholders replaced."""
        return self._format_template(self.ai_assistant.escalation_message)

    def get_formatted_handoff(self) -> str:
        """Get the human handoff message with placeholders replaced."""
        return self._format_template(self.support.human_handoff_message)

    def get_formatted_emergency(self) -> str:
        """Get the emergency message with placeholders replaced."""
        return self._format_template(self.support.emergency_message)

    def get_formatted_feedback(self) -> str:
        """Get the feedback message with placeholders replaced."""
        return self._format_template(self.support.feedback_message)

    def _format_template(self, template: str) -> str:
        """Replace placeholders in a template string with actual values."""
        replacements = {
            "{hotel_name}": self.hotel.name,
            "{hotel_full_name}": self.hotel.full_name,
            "{hotel_tagline}": self.hotel.tagline,
            "{phone_main}": self.contact.phone.main,
            "{phone_reservations}": self.contact.phone.reservations,
            "{phone_emergency}": self.contact.phone.emergency,
            "{email_general}": self.contact.email.general,
            "{email_reservations}": self.contact.email.reservations,
            "{email_support}": self.contact.email.support,
            "{email_feedback}": self.contact.email.feedback,
            "{check_in_time}": self.hours.check_in,
            "{check_out_time}": self.hours.check_out,
            "{ai_name}": self.ai_assistant.name,
        }

        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)

        return result

    def get_system_context(self) -> str:
        """
        Generate a comprehensive system context for the AI assistant.
        This provides all hotel information the AI needs to answer questions.
        """
        amenities_complimentary = ", ".join(self.amenities.complimentary)
        amenities_premium = ", ".join(self.amenities.premium)
        payment_methods = ", ".join(self.policies.payment.accepted_methods)

        room_types_info = "\n".join([
            f"  - {rt.name}: {rt.description} (Max {rt.max_occupancy} guests, {rt.bed_type})"
            for rt in self.room_types
        ])

        return f"""You are {self.ai_assistant.name}, the AI concierge for {self.hotel.full_name}.

HOTEL INFORMATION:
- Name: {self.hotel.full_name}
- Tagline: "{self.hotel.tagline}"
- Description: {self.hotel.description}
- Location: {self.contact.address.full_address}

CONTACT INFORMATION:
- Main Phone: {self.contact.phone.main}
- Reservations: {self.contact.phone.reservations}
- Emergency: {self.contact.phone.emergency}
- General Email: {self.contact.email.general}
- Reservations Email: {self.contact.email.reservations}
- Support Email: {self.contact.email.support}

HOURS OF OPERATION:
- Front Desk: {self.hours.front_desk}
- Check-in: {self.hours.check_in}
- Check-out: {self.hours.check_out}
- Early Check-in: {self.hours.early_check_in}
- Late Check-out: {self.hours.late_check_out}
- Spa: {self.hours.spa}
- Gym: {self.hours.gym}
- Pool: {self.hours.pool}
- Restaurant:
  - Breakfast: {self.hours.restaurant.breakfast}
  - Lunch: {self.hours.restaurant.lunch}
  - Dinner: {self.hours.restaurant.dinner}

ROOM TYPES:
{room_types_info}

AMENITIES:
- Complimentary: {amenities_complimentary}
- Premium: {amenities_premium}

POLICIES:
- Cancellation: {self.policies.cancellation.description}
- Payment Methods: {payment_methods}
- Deposit: {self.policies.payment.deposit_percentage}% required, full payment due {self.policies.payment.full_payment_due.lower()}
- Pets: {self.policies.pets.description}
- Smoking: {self.policies.smoking}
- Age Requirement: {self.policies.age_requirement}
- ID Requirement: {self.policies.id_requirement}

PERSONALITY:
You are {self.ai_assistant.personality}. Always maintain a warm, professional tone while being helpful and efficient.

IMPORTANT GUIDELINES:
1. You can ONLY assist authenticated/logged-in guests
2. Always verify the guest has an active booking when helping with booking-related requests
3. For requests you cannot handle, provide the appropriate contact information
4. Never make promises about things outside your capabilities
5. If unsure about something, acknowledge it and offer to connect them with the appropriate department
6. Keep responses concise but complete
7. Use the guest's name when available to personalize interactions
"""


# ============================================================================
# Configuration Loading
# ============================================================================

_config_instance: Optional[HotelConfig] = None


def _get_config_path() -> Path:
    """Get the path to the hotel configuration file."""
    # First check environment variable
    env_path = os.environ.get("HOTEL_CONFIG_PATH")
    if env_path:
        return Path(env_path)

    # Default to the config directory
    return Path(__file__).parent / "hotel_config.json"


def load_hotel_config(config_path: Optional[str] = None) -> HotelConfig:
    """
    Load the hotel configuration from the JSON file.

    Args:
        config_path: Optional path to the config file. If not provided,
                    uses the default location or HOTEL_CONFIG_PATH env var.

    Returns:
        HotelConfig: The loaded configuration object.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If the config file is invalid.
    """
    global _config_instance

    path = Path(config_path) if config_path else _get_config_path()

    if not path.exists():
        raise FileNotFoundError(
            f"Hotel configuration file not found at {path}. "
            "Please create the file or set HOTEL_CONFIG_PATH environment variable."
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        _config_instance = HotelConfig(**data)
        return _config_instance

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in hotel configuration file: {e}")
    except Exception as e:
        raise ValueError(f"Error loading hotel configuration: {e}")


@lru_cache(maxsize=1)
def get_hotel_config() -> HotelConfig:
    """
    Get the hotel configuration (cached).

    This function loads and caches the hotel configuration.
    The configuration is loaded once and reused for all subsequent calls.

    Returns:
        HotelConfig: The hotel configuration object.
    """
    global _config_instance

    if _config_instance is None:
        _config_instance = load_hotel_config()

    return _config_instance


def reload_hotel_config() -> HotelConfig:
    """
    Reload the hotel configuration from disk.

    Use this function if the configuration file has been updated
    and you need to load the new values.

    Returns:
        HotelConfig: The reloaded configuration object.
    """
    global _config_instance
    get_hotel_config.cache_clear()
    _config_instance = None
    return get_hotel_config()


# ============================================================================
# Utility Functions
# ============================================================================

def get_ai_name() -> str:
    """Get the AI assistant's name."""
    return get_hotel_config().ai_assistant.name


def get_hotel_name() -> str:
    """Get the hotel name."""
    return get_hotel_config().hotel.name


def get_support_phone() -> str:
    """Get the main support phone number."""
    return get_hotel_config().contact.phone.main


def get_support_email() -> str:
    """Get the support email address."""
    return get_hotel_config().contact.email.support


def get_emergency_phone() -> str:
    """Get the emergency phone number."""
    return get_hotel_config().contact.phone.emergency
