"""
In-House Chatbot Routing Tools for AGI Guest Assistant
Handles FAQ answering, request categorization, and intelligent routing to departments.

Features:
- FAQ answering with category support (General, Room, Stay)
- Request routing to proper departments
- Staff scheduling auto-assignment integration
- Escalation to human agents when needed
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger("agi.chatbot_routing")


class Department(str, Enum):
    """Hotel departments for request routing"""
    FRONT_DESK = "front_desk"
    HOUSEKEEPING = "housekeeping"
    MAINTENANCE = "maintenance"
    ROOM_SERVICE = "room_service"
    CONCIERGE = "concierge"
    BILLING = "billing"
    SECURITY = "security"
    SPA = "spa"
    MANAGER = "manager"
    GENERAL = "general"


class FAQCategory(str, Enum):
    """FAQ categories"""
    GENERAL = "general"
    ROOM = "room"
    STAY = "stay"
    AMENITIES = "amenities"
    POLICIES = "policies"
    DINING = "dining"
    SPA = "spa"
    TRANSPORTATION = "transportation"
    EVENTS = "events"


class EscalationReason(str, Enum):
    """Reasons for escalating to human agent"""
    COMPLAINT = "complaint"
    VIP_REQUEST = "vip_request"
    BILLING_DISPUTE = "billing_dispute"
    EMERGENCY = "emergency"
    COMPLEX_REQUEST = "complex_request"
    REPEATED_ISSUE = "repeated_issue"
    GUEST_UPSET = "guest_upset"
    AI_UNABLE = "ai_unable"


# ==================== COMPREHENSIVE FAQ DATABASE ====================

FAQS = {
    FAQCategory.GENERAL: [
        {
            "question": "What are your check-in and check-out times?",
            "answer": "Check-in time is 3:00 PM and check-out time is 11:00 AM. Early check-in and late check-out may be available upon request, subject to availability.",
            "keywords": ["check-in", "check-out", "time", "arrive", "leave", "checkout"]
        },
        {
            "question": "What is the hotel address?",
            "answer": "We are located at 123 Luxury Lane, City Center, ST 12345. We're in the heart of the city, easily accessible from the main highway.",
            "keywords": ["address", "location", "where", "directions", "find"]
        },
        {
            "question": "What forms of payment do you accept?",
            "answer": "We accept all major credit cards (Visa, Mastercard, American Express, Discover), debit cards, and cash. For cash payments, a deposit may be required.",
            "keywords": ["payment", "pay", "credit card", "cash", "debit"]
        },
        {
            "question": "How do I contact the front desk?",
            "answer": "From your room, dial 0 on your phone. You can also visit the front desk in the lobby 24/7, or call our main line at +1 (555) 123-4567.",
            "keywords": ["contact", "front desk", "phone", "call", "reach"]
        },
        {
            "question": "Is there a business center?",
            "answer": "Yes! Our 24-hour business center is on the ground floor. It offers computers, high-speed internet, printing, scanning, and fax services.",
            "keywords": ["business center", "print", "computer", "fax", "scan"]
        },
    ],
    FAQCategory.ROOM: [
        {
            "question": "What is the WiFi password?",
            "answer": "Connect to network 'Glimmora_Guest'. The password is provided at check-in. If you need assistance, dial 0 for the front desk.",
            "keywords": ["wifi", "wi-fi", "password", "internet", "wireless"]
        },
        {
            "question": "How do I adjust the room temperature?",
            "answer": "The thermostat is located on the wall near the entrance. Use the up/down arrows to adjust the temperature. For assistance, dial 88 for maintenance.",
            "keywords": ["temperature", "thermostat", "ac", "air conditioning", "heating", "cold", "hot"]
        },
        {
            "question": "How do I use the TV?",
            "answer": "Use the remote control on your nightstand. Press 'Guide' for the channel list. Smart TV apps (Netflix, etc.) are available. Your room number is the access code.",
            "keywords": ["tv", "television", "channels", "remote", "streaming", "netflix"]
        },
        {
            "question": "Can I get extra towels or pillows?",
            "answer": "Absolutely! Dial 44 for housekeeping or use the guest app. Extra towels and pillows will be delivered within 15 minutes.",
            "keywords": ["towel", "pillow", "extra", "blanket", "linen"]
        },
        {
            "question": "How does the safe work?",
            "answer": "The in-room safe is in your closet. Press 'CLR', enter a 4-digit code, and press 'LOCK'. To open, enter your code. For issues, call the front desk.",
            "keywords": ["safe", "lock", "security", "valuables"]
        },
        {
            "question": "What's in the minibar?",
            "answer": "The minibar includes snacks, beverages, and select alcohol. Prices are listed on the menu card. Charges will be added to your folio automatically.",
            "keywords": ["minibar", "snacks", "drinks", "beverages"]
        },
    ],
    FAQCategory.STAY: [
        {
            "question": "Can I extend my stay?",
            "answer": "Yes! Contact the front desk by dialing 0 or use the guest app. Extensions are subject to availability and current rates.",
            "keywords": ["extend", "stay longer", "extra night", "extension"]
        },
        {
            "question": "How do I request a late check-out?",
            "answer": "Late check-out may be available for a fee ($50 until 2 PM, $100 until 4 PM). Please request at least one day in advance through the front desk.",
            "keywords": ["late checkout", "late check-out", "leave late", "checkout late"]
        },
        {
            "question": "How do I request an early check-in?",
            "answer": "Early check-in is subject to availability. We'll do our best to accommodate. A fee may apply. Please request in advance.",
            "keywords": ["early checkin", "early check-in", "arrive early"]
        },
        {
            "question": "Can I change rooms?",
            "answer": "Room changes are subject to availability. Please contact the front desk to discuss your needs. We'll do our best to accommodate.",
            "keywords": ["change room", "different room", "switch room", "move room"]
        },
        {
            "question": "How do I check my bill?",
            "answer": "You can view your bill anytime using the guest app, the in-room TV, or by requesting a copy from the front desk.",
            "keywords": ["bill", "folio", "charges", "balance", "receipt"]
        },
    ],
    FAQCategory.AMENITIES: [
        {
            "question": "What are the pool hours?",
            "answer": "Indoor pool: 6 AM - 10 PM daily. Outdoor pool (seasonal): 8 AM - 8 PM. Towels are provided poolside. Children under 12 must be supervised.",
            "keywords": ["pool", "swim", "swimming", "hours"]
        },
        {
            "question": "What are the gym hours?",
            "answer": "Our fitness center is open 24 hours with your room keycard. We have cardio equipment, free weights, and exercise machines. Towels provided.",
            "keywords": ["gym", "fitness", "workout", "exercise"]
        },
        {
            "question": "Is there a spa?",
            "answer": "Yes! Serenity Spa offers massages, facials, and body treatments. Open 9 AM - 8 PM. Book in advance at extension 66. Hotel guests receive 15% off.",
            "keywords": ["spa", "massage", "facial", "treatment", "relax"]
        },
        {
            "question": "Is parking available?",
            "answer": "Self-parking is complimentary. Valet parking is $25/day. We also have EV charging stations (4 stations, complimentary). Underground garage via main entrance.",
            "keywords": ["parking", "car", "valet", "garage", "ev", "electric"]
        },
    ],
    FAQCategory.POLICIES: [
        {
            "question": "What is your pet policy?",
            "answer": "Pets under 50 lbs are welcome! There's a $50 pet fee per stay. Maximum 2 pets per room. Pet-friendly rooms must be requested at booking.",
            "keywords": ["pet", "dog", "cat", "animal"]
        },
        {
            "question": "What is your smoking policy?",
            "answer": "This is a non-smoking property. Designated outdoor smoking areas are available. A $250 cleaning fee applies for smoking in rooms.",
            "keywords": ["smoking", "smoke", "cigarette", "vape"]
        },
        {
            "question": "What is your cancellation policy?",
            "answer": "Free cancellation up to 3 days before arrival. Cancellation within 3 days: 50% of first night. Same-day cancellation: full first night charge.",
            "keywords": ["cancel", "cancellation", "refund"]
        },
        {
            "question": "Do you have accessible rooms?",
            "answer": "Yes, we have ADA-compliant accessible rooms with roll-in showers, grab bars, and other accessibility features. Please request when booking.",
            "keywords": ["accessible", "ada", "wheelchair", "disability", "handicap"]
        },
    ],
    FAQCategory.DINING: [
        {
            "question": "What are the restaurant hours?",
            "answer": "The Glimmora Grill: Breakfast 6:30-10:30 AM, Lunch 11 AM-5 PM, Dinner 5-11 PM. Sky Lounge Bar: 4 PM-1 AM. Room service is 24/7.",
            "keywords": ["restaurant", "dining", "hours", "eat", "food"]
        },
        {
            "question": "Is room service available 24/7?",
            "answer": "Yes! Room service is available around the clock. Dial 33 from your room or use the guest app. Average delivery time is 30-45 minutes.",
            "keywords": ["room service", "order food", "delivery"]
        },
        {
            "question": "Do you have breakfast included?",
            "answer": "Breakfast inclusion depends on your rate. Check your booking confirmation or ask the front desk. Our buffet is $35 per person.",
            "keywords": ["breakfast", "included", "complimentary", "buffet"]
        },
    ],
    FAQCategory.TRANSPORTATION: [
        {
            "question": "Do you offer airport shuttle?",
            "answer": "Yes! Airport shuttle is $45 each way and must be reserved in advance. Contact concierge at extension 55 to book. Allow 24 hours notice.",
            "keywords": ["airport", "shuttle", "transportation", "transfer"]
        },
        {
            "question": "Can you arrange a taxi?",
            "answer": "Taxis are available 24/7 at our main entrance. We can also arrange ride-share pickups or limo service through our concierge.",
            "keywords": ["taxi", "uber", "lyft", "ride", "car"]
        },
        {
            "question": "Can I rent a car?",
            "answer": "We partner with major car rental companies. Contact concierge at extension 55 to arrange. On-site pickup can often be arranged.",
            "keywords": ["car rental", "rent car", "rental"]
        },
    ],
}


class ChatbotRoutingTools:
    """
    In-House Chatbot Tools for FAQ answering and intelligent request routing.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._request_history: Dict[str, List[Dict]] = {}  # Track requests by session

    async def answer_faq(
        self,
        query: str,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Answer a FAQ question with category-aware search.

        Args:
            query: User's question
            category: Optional category to search (general, room, stay, etc.)

        Returns:
            Answer if found, or suggestion to speak with staff
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        best_match = None
        best_score = 0
        best_category = None

        # Determine which categories to search
        if category:
            categories_to_search = [FAQCategory(category.lower())]
        else:
            categories_to_search = list(FAQCategory)

        for cat in categories_to_search:
            if cat not in FAQS:
                continue

            for faq in FAQS[cat]:
                score = 0

                # Check keywords
                for keyword in faq.get("keywords", []):
                    if keyword in query_lower:
                        score += 2 if " " in keyword else 1

                # Check question similarity
                question_words = set(faq["question"].lower().split())
                word_overlap = len(query_words & question_words) / max(len(query_words), 1)
                score += word_overlap * 2

                # Exact phrase match in question
                if query_lower in faq["question"].lower():
                    score += 3

                if score > best_score:
                    best_score = score
                    best_match = faq
                    best_category = cat

        if best_match and best_score >= 1.5:
            return {
                "success": True,
                "found": True,
                "question": best_match["question"],
                "answer": best_match["answer"],
                "category": best_category.value if best_category else None,
                "confidence": min(best_score / 5, 1.0),
                "message": best_match["answer"]
            }

        return {
            "success": True,
            "found": False,
            "query": query,
            "category": category,
            "message": "I don't have a specific answer for that. Would you like me to connect you with a staff member who can help?",
            "suggested_action": "escalate_to_human"
        }

    async def get_faq_categories(self) -> Dict[str, Any]:
        """Get available FAQ categories with sample questions."""
        categories = {}
        for cat in FAQCategory:
            if cat in FAQS:
                categories[cat.value] = {
                    "name": cat.value.replace("_", " ").title(),
                    "question_count": len(FAQS[cat]),
                    "sample_questions": [faq["question"] for faq in FAQS[cat][:3]]
                }

        return {
            "success": True,
            "categories": categories,
            "total_faqs": sum(len(FAQS[cat]) for cat in FAQS),
            "message": "Here are our FAQ categories. Which topic interests you?"
        }

    def route_request(
        self,
        request_text: str,
        guest_emotion: Optional[str] = None,
        is_vip: bool = False
    ) -> Dict[str, Any]:
        """
        Route a guest request to the appropriate department.

        Args:
            request_text: The guest's request text
            guest_emotion: Detected emotion (happy, neutral, frustrated, upset)
            is_vip: Whether the guest is a VIP

        Returns:
            Routing decision with department and priority
        """
        request_lower = request_text.lower()

        # Department routing patterns
        routing_patterns = {
            Department.HOUSEKEEPING: [
                r"clean", r"towel", r"sheet", r"pillow", r"housekeep", r"maid",
                r"linen", r"amenities", r"toiletries", r"soap", r"shampoo",
                r"trash", r"garbage"
            ],
            Department.MAINTENANCE: [
                r"broken", r"fix", r"repair", r"not working", r"doesn't work",
                r"leak", r"plumb", r"electric", r"light", r"ac\b", r"air condition",
                r"heat", r"cold", r"hot water", r"toilet", r"shower", r"wifi.*slow",
                r"internet.*slow"
            ],
            Department.ROOM_SERVICE: [
                r"food", r"menu", r"order", r"hungry", r"eat", r"drink",
                r"breakfast", r"lunch", r"dinner", r"snack", r"coffee", r"tea"
            ],
            Department.CONCIERGE: [
                r"restaurant", r"recommend", r"nearby", r"taxi", r"uber",
                r"transport", r"shuttle", r"airport", r"attraction", r"tour",
                r"ticket", r"reservation", r"book.*restaurant"
            ],
            Department.BILLING: [
                r"bill", r"charge", r"folio", r"payment", r"receipt",
                r"invoice", r"dispute", r"checkout", r"check out"
            ],
            Department.SPA: [
                r"spa\b", r"massage", r"facial", r"treatment", r"salon",
                r"manicure", r"pedicure", r"wellness"
            ],
            Department.SECURITY: [
                r"safe", r"security", r"lost", r"found", r"theft", r"stolen",
                r"suspicious", r"noise.*complain", r"loud"
            ],
            Department.FRONT_DESK: [
                r"check.?in", r"check.?out", r"reservation", r"booking",
                r"extend.*stay", r"room.*change", r"upgrade", r"key.*card",
                r"wake.*up.*call"
            ],
        }

        # Score each department
        department_scores = {}
        for dept, patterns in routing_patterns.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, request_lower):
                    score += 1
            if score > 0:
                department_scores[dept] = score

        # Determine primary department
        if department_scores:
            primary_dept = max(department_scores.keys(), key=lambda d: department_scores[d])
        else:
            primary_dept = Department.GENERAL

        # Determine priority
        priority = "normal"
        if any(word in request_lower for word in ["urgent", "emergency", "asap", "immediately"]):
            priority = "urgent"
        elif any(word in request_lower for word in ["important", "soon", "quickly"]):
            priority = "high"
        elif is_vip:
            priority = "high"

        # Check for escalation needs
        escalation_needed = False
        escalation_reason = None

        if guest_emotion in ["frustrated", "upset"]:
            escalation_needed = True
            escalation_reason = EscalationReason.GUEST_UPSET

        if any(word in request_lower for word in ["complaint", "complain", "unacceptable", "manager"]):
            escalation_needed = True
            escalation_reason = EscalationReason.COMPLAINT
            primary_dept = Department.MANAGER

        if any(word in request_lower for word in ["dispute", "overcharge", "wrong charge"]):
            escalation_needed = True
            escalation_reason = EscalationReason.BILLING_DISPUTE

        return {
            "success": True,
            "department": primary_dept.value,
            "department_name": primary_dept.value.replace("_", " ").title(),
            "priority": priority,
            "escalation_needed": escalation_needed,
            "escalation_reason": escalation_reason.value if escalation_reason else None,
            "confidence": department_scores.get(primary_dept, 0) / 3 if department_scores else 0.3,
            "all_departments": list(department_scores.keys()) if len(department_scores) > 1 else None
        }

    async def create_routed_task(
        self,
        request_text: str,
        room_number: str,
        guest_id: Optional[int] = None,
        booking_id: Optional[int] = None,
        guest_emotion: Optional[str] = None,
        is_vip: bool = False,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a task based on intelligent routing.

        Args:
            request_text: The guest's request
            room_number: Guest's room number
            guest_id: Guest ID
            booking_id: Booking ID
            guest_emotion: Detected emotion
            is_vip: VIP status
            session_id: Chat session ID for tracking

        Returns:
            Task creation result with routing info
        """
        from app.models.guest_chat import StaffTask
        from app.services.staff_scheduling_service import get_scheduling_service

        # Route the request
        routing = self.route_request(request_text, guest_emotion, is_vip)

        department = routing["department"]
        priority = routing["priority"]

        # Map department to task type
        task_type_map = {
            "housekeeping": "housekeeping",
            "maintenance": "maintenance",
            "room_service": "room_service",
            "concierge": "concierge",
            "billing": "billing",
            "spa": "spa",
            "security": "security",
            "front_desk": "front_desk",
            "manager": "escalation",
            "general": "general"
        }
        task_type = task_type_map.get(department, "general")

        try:
            scheduling_service = get_scheduling_service(self.db)

            # Get room ID
            from app.models.inventory import Room
            room_id = None
            if room_number:
                result = await self.db.execute(
                    select(Room).where(Room.number == room_number)
                )
                room = result.scalars().first()
                room_id = room.id if room else None

            # Create and assign task
            task, staff = await scheduling_service.create_and_assign_task(
                task_type=task_type,
                title=f"{department.replace('_', ' ').title()} Request - Room {room_number}",
                description=f"Guest Request: {request_text}\n\nRouted by AI Assistant.",
                priority=priority,
                room_number=room_number,
                room_id=room_id,
                booking_id=booking_id,
                guest_id=guest_id
            )

            # Track request history
            if session_id:
                if session_id not in self._request_history:
                    self._request_history[session_id] = []
                self._request_history[session_id].append({
                    "task_id": task.id if task else None,
                    "department": department,
                    "request": request_text,
                    "timestamp": datetime.utcnow().isoformat()
                })

            estimated_times = {
                "urgent": 10,
                "high": 20,
                "normal": 30,
                "low": 60
            }

            return {
                "success": True,
                "task_id": task.id if task else None,
                "task_type": task_type,
                "department": department,
                "priority": priority,
                "assigned_staff": staff.staff_name if staff else None,
                "estimated_time_minutes": estimated_times.get(priority, 30),
                "escalation_needed": routing.get("escalation_needed", False),
                "escalation_reason": routing.get("escalation_reason"),
                "message": f"Your request has been sent to our {routing['department_name']} team. "
                          f"{'Our team member ' + staff.staff_name if staff else 'A team member'} "
                          f"will assist you within {estimated_times.get(priority, 30)} minutes."
            }

        except Exception as e:
            logger.error(f"Error creating routed task: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "I apologize, but I couldn't process your request. Please dial 0 for the front desk."
            }

    async def should_escalate(
        self,
        session_id: str,
        guest_emotion: Optional[str] = None,
        request_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Determine if a conversation should be escalated to a human agent.

        Args:
            session_id: Chat session ID
            guest_emotion: Current detected emotion
            request_text: Current request text

        Returns:
            Escalation decision with reason
        """
        escalate = False
        reasons = []

        # Check emotion
        if guest_emotion == "upset":
            escalate = True
            reasons.append("Guest appears upset")

        # Check for repeated issues (more than 3 requests in same session)
        if session_id in self._request_history:
            history = self._request_history[session_id]
            if len(history) >= 3:
                escalate = True
                reasons.append("Multiple requests in same session")

        # Check for escalation keywords
        if request_text:
            request_lower = request_text.lower()
            escalation_keywords = [
                "manager", "supervisor", "complaint", "unacceptable",
                "lawsuit", "lawyer", "refund", "compensation", "speak to someone"
            ]
            if any(kw in request_lower for kw in escalation_keywords):
                escalate = True
                reasons.append("Guest requested escalation or expressed serious concern")

        return {
            "should_escalate": escalate,
            "reasons": reasons,
            "suggested_action": "connect_to_human" if escalate else "continue_ai",
            "message": "I'm connecting you with a member of our management team who can better assist you." if escalate else None
        }

    def get_department_contact(self, department: str) -> Dict[str, Any]:
        """Get contact information for a department."""
        contacts = {
            "front_desk": {"extension": "0", "description": "24/7 assistance"},
            "housekeeping": {"extension": "44", "description": "Room cleaning and supplies"},
            "maintenance": {"extension": "88", "description": "Repairs and technical issues"},
            "room_service": {"extension": "33", "description": "Food and beverage"},
            "concierge": {"extension": "55", "description": "Reservations and recommendations"},
            "billing": {"extension": "0", "description": "Charges and payments (Front Desk)"},
            "spa": {"extension": "66", "description": "Spa appointments"},
            "security": {"extension": "9999", "description": "Safety and security"},
            "manager": {"extension": "0", "description": "Request a manager (Front Desk)"},
        }

        dept_info = contacts.get(department.lower(), contacts["front_desk"])

        return {
            "success": True,
            "department": department,
            "extension": dept_info["extension"],
            "description": dept_info["description"],
            "message": f"To reach {department.replace('_', ' ').title()}, dial {dept_info['extension']} from your room phone."
        }


def get_chatbot_routing_tools(db: AsyncSession) -> ChatbotRoutingTools:
    """Factory function to create ChatbotRoutingTools instance"""
    return ChatbotRoutingTools(db)
