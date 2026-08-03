"""
Hotel Information Tools for AGI Guest Assistant
Handles all hotel information and FAQ queries
"""

import logging
import json
from typing import Any, Dict, List, Optional
from pathlib import Path
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.hotel_info_tools")


class HotelInfoTools:
    """Tools for hotel information and FAQs"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._hotel_info = self._load_hotel_info()
        self._faqs = self._load_faqs()

    def _load_hotel_info(self) -> Dict[str, Any]:
        """Load comprehensive hotel information"""
        return {
            "name": "Glimmora Hotel & Suites",
            "address": "123 Luxury Lane, City Center, ST 12345",
            "phone": "+1 (555) 123-4567",
            "email": "info@glimmorahotel.com",
            "website": "www.glimmorahotel.com",
            "star_rating": 5,
            "description": "A world-class luxury hotel offering exceptional service and amenities in the heart of the city.",

            "hours": {
                "front_desk": "24/7",
                "concierge": "24/7",
                "room_service": "24/7",
                "restaurant_breakfast": "6:30 AM - 10:30 AM (11:00 AM weekends)",
                "restaurant_lunch": "11:00 AM - 5:00 PM",
                "restaurant_dinner": "5:00 PM - 11:00 PM",
                "bar": "4:00 PM - 1:00 AM",
                "fitness_center": "24 hours (keycard access)",
                "pool_indoor": "6:00 AM - 10:00 PM",
                "pool_outdoor": "8:00 AM - 8:00 PM (seasonal)",
                "spa": "9:00 AM - 8:00 PM",
                "business_center": "24 hours (keycard access)"
            },

            "amenities": {
                "in_room": [
                    "High-speed WiFi",
                    "Smart TV with streaming services",
                    "Mini bar",
                    "In-room safe",
                    "Coffee/tea maker",
                    "Iron and ironing board",
                    "Hair dryer",
                    "Bathrobes and slippers",
                    "Premium toiletries",
                    "Blackout curtains",
                    "Climate control",
                    "Work desk"
                ],
                "hotel": [
                    "Indoor heated pool",
                    "Outdoor pool (seasonal)",
                    "Full-service spa",
                    "Fitness center",
                    "Business center",
                    "Multiple dining options",
                    "Rooftop bar",
                    "Concierge service",
                    "Valet parking",
                    "EV charging stations",
                    "Gift shop",
                    "Laundry service"
                ]
            },

            "policies": {
                "check_in": "3:00 PM",
                "check_out": "11:00 AM",
                "early_check_in": "Subject to availability, fee may apply",
                "late_check_out": "Subject to availability, fee may apply ($50 until 2 PM, $100 until 4 PM)",
                "cancellation": "Free cancellation up to 3 days before arrival. Cancellation within 3 days: 50% of first night. Same-day: Full first night charge.",
                "pets": "Pets welcome under 50 lbs. $50 per stay pet fee. Maximum 2 pets per room.",
                "smoking": "Non-smoking property. Designated outdoor smoking areas available. $250 cleaning fee for smoking in room.",
                "minimum_age": "21 years old to check in without a parent/guardian",
                "payment": "Major credit cards accepted (Visa, Mastercard, AmEx, Discover). Cash deposits available.",
                "incidentals": "$100/night hold for incidentals, released within 3-5 business days after checkout"
            },

            "wifi": {
                "network_name": "Glimmora_Guest",
                "password": "Provided at check-in",
                "speed": "High-speed fiber (up to 100 Mbps)",
                "coverage": "Throughout hotel and grounds",
                "premium_wifi": "Available for $15/day (up to 500 Mbps)"
            },

            "parking": {
                "self_parking": "Complimentary",
                "valet": "$25/day",
                "ev_charging": "Available (4 stations, complimentary)",
                "oversized_vehicles": "Limited availability, $40/day",
                "location": "Underground parking garage, accessible via main entrance"
            },

            "dining": {
                "main_restaurant": {
                    "name": "The Glimmora Grill",
                    "cuisine": "American Contemporary",
                    "dress_code": "Smart Casual",
                    "reservations": "Recommended for dinner"
                },
                "rooftop_bar": {
                    "name": "Sky Lounge",
                    "specialty": "Craft cocktails and small plates",
                    "dress_code": "Smart Casual",
                    "age": "21+ after 9 PM"
                },
                "room_service": {
                    "availability": "24/7",
                    "menu": "Full menu plus late-night options",
                    "delivery_time": "30-45 minutes"
                }
            },

            "spa": {
                "name": "Serenity Spa",
                "services": ["Massage", "Facials", "Body Treatments", "Salon Services"],
                "booking": "Advance booking recommended",
                "guest_discount": "15% for hotel guests",
                "couples_suites": "Available",
                "location": "Floor 3"
            },

            "fitness": {
                "equipment": "State-of-the-art cardio and strength equipment",
                "classes": "Yoga and fitness classes available (schedule at front desk)",
                "towels": "Provided",
                "water": "Complimentary",
                "personal_training": "Available by appointment"
            },

            "pool": {
                "indoor": {
                    "temperature": "82°F year-round",
                    "hours": "6 AM - 10 PM",
                    "towels": "Provided",
                    "depth": "3.5 ft - 8 ft"
                },
                "outdoor": {
                    "season": "Memorial Day - Labor Day",
                    "hours": "8 AM - 8 PM",
                    "bar_service": "Available",
                    "cabanas": "Available for rent ($75/day)"
                },
                "rules": "No glass, no running, children under 12 must be supervised"
            },

            "business_services": {
                "business_center": "Complimentary computers, printing, and scanning",
                "meeting_rooms": "Multiple sizes available (2-200 people)",
                "av_equipment": "Available for rental",
                "catering": "Full catering services for events"
            },

            "transportation": {
                "airport_shuttle": "Available by reservation ($45 each way)",
                "taxi": "Available at main entrance 24/7",
                "ride_share": "Designated pickup area",
                "car_rental": "Can be arranged through concierge",
                "limo_service": "Available by reservation"
            },

            "emergency_contacts": {
                "front_desk": "0 (from room phone)",
                "security": "9999",
                "medical": "911",
                "maintenance": "88"
            }
        }

    def _load_faqs(self) -> List[Dict[str, Any]]:
        """Load FAQs from file or use defaults"""
        try:
            possible_paths = [
                Path(__file__).parent.parent.parent.parent / "hotel_faqs.json",
                Path(__file__).parent.parent.parent.parent.parent / "hotel_faqs.json",
                Path("Backend/hotel_faqs.json"),
                Path("hotel_faqs.json"),
            ]

            for path in possible_paths:
                if path.exists():
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Flatten FAQs
                    faqs = []

                    def extract_faqs(obj, category="general"):
                        if isinstance(obj, dict):
                            if "question" in obj and "answer" in obj:
                                faqs.append({
                                    "question": obj["question"],
                                    "answer": obj["answer"],
                                    "category": category,
                                    "keywords": obj.get("paraphrases", [])
                                })
                            else:
                                for key, value in obj.items():
                                    extract_faqs(value, key if isinstance(key, str) else category)
                        elif isinstance(obj, list):
                            for item in obj:
                                extract_faqs(item, category)

                    extract_faqs(data)
                    return faqs

        except Exception as e:
            logger.warning(f"Error loading FAQs: {e}")

        # Default FAQs
        return [
            {"question": "What are check-in and check-out times?", "answer": "Check-in is at 3:00 PM and check-out is at 11:00 AM.", "category": "policies", "keywords": ["check in", "check out", "time"]},
            {"question": "Is WiFi free?", "answer": "Yes, high-speed WiFi is complimentary for all guests. Connect to 'Glimmora_Guest' network.", "category": "amenities", "keywords": ["wifi", "internet", "wireless"]},
            {"question": "Is parking available?", "answer": "Yes, complimentary self-parking is available. Valet parking is $25/day.", "category": "amenities", "keywords": ["parking", "car", "valet"]},
            {"question": "What time is breakfast?", "answer": "Breakfast is served 6:30 AM - 10:30 AM weekdays and until 11:00 AM on weekends.", "category": "dining", "keywords": ["breakfast", "food", "morning"]},
            {"question": "Do you allow pets?", "answer": "Yes, pets under 50 lbs are welcome with a $50 pet fee per stay.", "category": "policies", "keywords": ["pets", "dogs", "cats", "animals"]},
        ]

    async def get_hotel_info(
        self,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get general hotel information.

        Args:
            category: Specific category (hours, amenities, policies, etc.)

        Returns:
            Hotel information
        """
        if category:
            if category in self._hotel_info:
                return {
                    "success": True,
                    "category": category,
                    "info": self._hotel_info[category],
                    "message": f"Here's the {category} information for {self._hotel_info['name']}."
                }
            return {
                "success": False,
                "message": f"Category '{category}' not found. Available: {list(self._hotel_info.keys())}"
            }

        # Return summary
        return {
            "success": True,
            "hotel": {
                "name": self._hotel_info["name"],
                "address": self._hotel_info["address"],
                "phone": self._hotel_info["phone"],
                "star_rating": self._hotel_info["star_rating"]
            },
            "key_info": {
                "check_in": self._hotel_info["policies"]["check_in"],
                "check_out": self._hotel_info["policies"]["check_out"],
                "wifi": self._hotel_info["wifi"]["network_name"],
                "front_desk": self._hotel_info["hours"]["front_desk"]
            },
            "available_categories": list(self._hotel_info.keys()),
            "message": f"Welcome to {self._hotel_info['name']}! Ask me about any specific information."
        }

    async def get_amenities(
        self,
        amenity_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get hotel amenities information.

        Args:
            amenity_type: Specific amenity (pool, spa, fitness, dining, etc.)

        Returns:
            Amenity information
        """
        amenity_details = {
            "pool": self._hotel_info["pool"],
            "spa": self._hotel_info["spa"],
            "fitness": self._hotel_info["fitness"],
            "dining": self._hotel_info["dining"],
            "business": self._hotel_info["business_services"],
            "in_room": self._hotel_info["amenities"]["in_room"],
            "hotel_wide": self._hotel_info["amenities"]["hotel"]
        }

        if amenity_type:
            amenity_lower = amenity_type.lower()
            # Try to find matching amenity
            for key, value in amenity_details.items():
                if amenity_lower in key or key in amenity_lower:
                    return {
                        "success": True,
                        "amenity": key,
                        "details": value,
                        "message": f"Here's information about our {key} facilities."
                    }

            # Check in the lists
            all_amenities = self._hotel_info["amenities"]["in_room"] + self._hotel_info["amenities"]["hotel"]
            matching = [a for a in all_amenities if amenity_lower in a.lower()]
            if matching:
                return {
                    "success": True,
                    "amenity": amenity_type,
                    "available": True,
                    "matching_amenities": matching,
                    "message": f"Yes, we offer {', '.join(matching)}."
                }

            return {
                "success": True,
                "amenity": amenity_type,
                "available": False,
                "message": f"I couldn't find specific information about '{amenity_type}'. Our amenities include: {', '.join(all_amenities[:10])}..."
            }

        return {
            "success": True,
            "amenities": {
                "in_room": self._hotel_info["amenities"]["in_room"],
                "hotel": self._hotel_info["amenities"]["hotel"]
            },
            "highlights": {
                "pool": "Indoor heated pool & seasonal outdoor pool",
                "spa": "Full-service spa with 15% guest discount",
                "fitness": "24-hour fitness center",
                "dining": "24/7 room service, restaurant, rooftop bar"
            },
            "message": "Here are our hotel amenities. Would you like details about any specific amenity?"
        }

    async def get_hours(
        self,
        facility: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get operating hours for hotel facilities.

        Args:
            facility: Specific facility name

        Returns:
            Hours information
        """
        hours = self._hotel_info["hours"]

        if facility:
            facility_lower = facility.lower().replace(" ", "_")
            for key, value in hours.items():
                if facility_lower in key or key.replace("_", " ") in facility.lower():
                    return {
                        "success": True,
                        "facility": key.replace("_", " ").title(),
                        "hours": value,
                        "message": f"The {key.replace('_', ' ').title()} is open {value}."
                    }

            return {
                "success": False,
                "message": f"Hours for '{facility}' not found. Available facilities: {', '.join(h.replace('_', ' ').title() for h in hours.keys())}"
            }

        return {
            "success": True,
            "hours": {k.replace("_", " ").title(): v for k, v in hours.items()},
            "message": "Here are the operating hours for all hotel facilities."
        }

    async def get_policies(
        self,
        policy_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get hotel policies.

        Args:
            policy_type: Specific policy (cancellation, pets, smoking, etc.)

        Returns:
            Policy information
        """
        policies = self._hotel_info["policies"]

        if policy_type:
            policy_lower = policy_type.lower().replace(" ", "_")
            for key, value in policies.items():
                if policy_lower in key or key in policy_lower:
                    return {
                        "success": True,
                        "policy": key.replace("_", " ").title(),
                        "details": value,
                        "message": f"Our {key.replace('_', ' ')} policy: {value}"
                    }

            return {
                "success": False,
                "message": f"Policy '{policy_type}' not found. Available policies: {', '.join(policies.keys())}"
            }

        return {
            "success": True,
            "policies": policies,
            "key_policies": {
                "check_in": policies["check_in"],
                "check_out": policies["check_out"],
                "cancellation": policies["cancellation"],
                "pets": policies["pets"]
            },
            "message": "Here are our hotel policies."
        }

    async def search_faq(
        self,
        query: str
    ) -> Dict[str, Any]:
        """
        Search FAQs for an answer.

        Args:
            query: User's question

        Returns:
            FAQ answer if found
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        best_match = None
        best_score = 0

        for faq in self._faqs:
            score = 0

            # Check question similarity
            question_lower = faq["question"].lower()
            question_words = set(question_lower.split())
            word_overlap = len(query_words & question_words) / max(len(query_words), 1)
            score += word_overlap * 0.5

            # Check keywords
            keywords = [k.lower() for k in faq.get("keywords", [])]
            for keyword in keywords:
                if keyword in query_lower:
                    score += 0.3

            # Check if query is in question or vice versa
            if query_lower in question_lower or question_lower in query_lower:
                score += 0.4

            if score > best_score:
                best_score = score
                best_match = faq

        if best_match and best_score >= 0.3:
            return {
                "success": True,
                "found": True,
                "question": best_match["question"],
                "answer": best_match["answer"],
                "category": best_match.get("category"),
                "confidence": round(best_score, 2),
                "message": best_match["answer"]
            }

        return {
            "success": True,
            "found": False,
            "message": "I couldn't find a specific answer to that question. Would you like me to connect you with the front desk for more information?"
        }

    async def get_contact_info(
        self,
        department: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get contact information.

        Args:
            department: Specific department (front_desk, security, etc.)

        Returns:
            Contact information
        """
        contacts = {
            "front_desk": {"extension": "0", "description": "24/7 assistance"},
            "room_service": {"extension": "33", "description": "Food and beverage"},
            "housekeeping": {"extension": "44", "description": "Room cleaning and supplies"},
            "concierge": {"extension": "55", "description": "Tours, reservations, recommendations"},
            "spa": {"extension": "66", "description": "Spa appointments"},
            "security": {"extension": "9999", "description": "Safety and security"},
            "maintenance": {"extension": "88", "description": "Room repairs and issues"},
            "main_line": {"number": self._hotel_info["phone"], "description": "Hotel main number"}
        }

        if department:
            dept_lower = department.lower().replace(" ", "_")
            for key, value in contacts.items():
                if dept_lower in key or key in dept_lower:
                    contact_info = f"Extension {value.get('extension')}" if 'extension' in value else value.get('number')
                    return {
                        "success": True,
                        "department": key.replace("_", " ").title(),
                        "contact": contact_info,
                        "description": value["description"],
                        "message": f"To reach {key.replace('_', ' ').title()}, dial {contact_info} from your room phone."
                    }

        return {
            "success": True,
            "contacts": contacts,
            "emergency": self._hotel_info["emergency_contacts"],
            "message": "Here are all our contact numbers. Dial from your room phone."
        }

    async def get_wifi_info(self) -> Dict[str, Any]:
        """Get WiFi connection information."""
        wifi = self._hotel_info["wifi"]
        return {
            "success": True,
            "wifi": wifi,
            "connection_steps": [
                f"1. Open your device's WiFi settings",
                f"2. Select network: {wifi['network_name']}",
                f"3. Enter password (provided at check-in)",
                f"4. Open a browser - you may need to accept terms"
            ],
            "message": f"Connect to '{wifi['network_name']}'. Password was provided at check-in. If you need help, call front desk at extension 0."
        }

    async def get_parking_info(self) -> Dict[str, Any]:
        """Get parking information."""
        parking = self._hotel_info["parking"]
        return {
            "success": True,
            "parking": parking,
            "message": f"Self-parking is complimentary. Valet is ${parking['valet']}. EV charging is available. Access via main entrance to underground garage."
        }

    async def get_emergency_info(self) -> Dict[str, Any]:
        """Get emergency contact information."""
        return {
            "success": True,
            "emergency_contacts": self._hotel_info["emergency_contacts"],
            "instructions": {
                "fire": "Exit via nearest stairwell. Do not use elevators. Meet at assembly point in front parking lot.",
                "medical": "Call 911 or front desk (0). AED located in lobby.",
                "security": "Call security at 9999 or front desk at 0."
            },
            "message": "For emergencies: Call 911. For hotel security: dial 9999. Front desk: dial 0."
        }


def get_hotel_info_tools(db: AsyncSession) -> HotelInfoTools:
    """Factory function to create HotelInfoTools instance"""
    return HotelInfoTools(db)
