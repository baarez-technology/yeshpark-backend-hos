"""
Comprehension Agent for Admin AI Multi-Agent Architecture.
LLM-backed intent classifier with structured output, multi-intent decomposition,
and entity extraction. Includes regex fallback (circuit breaker pattern).
"""
import json
import logging
import re
import time
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.services.admin_ai.protocol import (
    ComprehensionResult,
    DetectedIntent,
    IntentCategory,
)
from app.services.admin_ai.prompts import COMPREHENSION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# LangChain imports with fallback
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


# ─────────────────────── Regex Fallback Classifier ───────────────────────

# Compact intent patterns for regex fallback
_REGEX_PATTERNS: List[Tuple[str, str, str]] = [
    # (pattern, intent, category)
    # Bookings today (most specific)
    (r"\b(bookings?|arrivals?|check.?ins?)\b.*\b(today|tonight)\b", "query_bookings_today", "query"),
    (r"\b(today|tonight)\b.*\b(bookings?|arrivals?|check.?ins?)\b", "query_bookings_today", "query"),
    (r"\bhow many (bookings?|arrivals?|guests?) today\b", "query_bookings_today", "query"),

    # Checkouts today
    (r"\b(checkouts?|departures?|check.?outs?)\b.*\b(today|tonight)\b", "query_checkouts_today", "query"),
    (r"\b(today|tonight)\b.*\b(checkouts?|departures?|check.?outs?)\b", "query_checkouts_today", "query"),
    (r"\bwho.s (leaving|checking out|departing)\b", "query_checkouts_today", "query"),

    # Room occupant
    (r"\bwho.s in room\s*\d+\b", "query_room_occupant", "query"),
    (r"\bwho is (staying|in|occupying) room\b", "query_room_occupant", "query"),
    (r"\broom\s*\d+\s*(occupant|guest|who)\b", "query_room_occupant", "query"),

    # Create housekeeping task (before query patterns)
    (r"\b(clean|cleaning|turndown|deep.?clean|inspect)\b.*\broom\s*\d+\b", "create_task", "action"),
    (r"\b(create|add|schedule|make)\b.*\b(housekeeping|cleaning|hk)\s*(task|request)\b", "create_task", "action"),

    # Create maintenance
    (r"\b(report|create|log|raise)\b.*\b(maintenance|repair|fix|broken|issue)\b", "create_maintenance", "action"),
    (r"\b(ac|air.?condition|plumb|leak|electric|bulb|door|window|toilet)\b.*\b(broken|not working|issue|problem|fix)\b", "create_maintenance", "action"),

    # Create booking — must be BEFORE update_booking so "book <Name>" isn't eaten by check-in
    (r"\b(book|create|make|new)\b.*\b(booking|reservation)\b", "create_booking", "action"),
    (r"\bbook\s+[A-Z][a-z]", "create_booking", "action"),

    # Update booking (check in/out)
    (r"\b(check.?in|checkin)\b.*\b(booking|guest|reservation)\b", "update_booking", "action"),
    (r"\b(check.?out|checkout)\b.*\b(booking|guest|room)\b", "update_booking", "action"),
    (r"\b(cancel|no.?show)\b.*\bbooking\b", "update_booking", "action"),

    # Update room status
    (r"\b(mark|set|update|change)\b.*\broom\s*\d+\b.*\b(clean|dirty|maintenance|out of order|oos|ooo)\b", "update_room", "action"),

    # Assign task
    (r"\b(assign|give|delegate)\b.*\b(task|job|work)\b", "assign_task", "action"),

    # VIP guests
    (r"\bvip\b", "query_vip_guests", "query"),
    (r"\b(loyalty|premium|gold|platinum|diamond)\s*(member|guest)s?\b", "query_vip_guests", "query"),

    # General bookings
    (r"\b(show|list|get|find|search|display)\b.*\bbookings?\b", "query_bookings", "query"),
    (r"\b(arrivals?|reservations?)\b.*\b(for|on|tomorrow|this week)\b", "query_bookings", "query"),

    # Guests
    (r"\b(show|list|how many|count|total)\b.*\bguests?\b", "query_guests", "query"),

    # Revenue
    (r"\brevenue\b", "query_revenue", "query"),
    (r"\b(earnings?|income|sales|total.?amount|adr|revpar)\b", "query_revenue", "query"),

    # Occupancy
    (r"\b(occupancy|occupied|vacancy|available rooms?)\b", "query_occupancy", "query"),

    # Rooms
    (r"\b(show|list|all)\b.*\brooms?\b", "query_rooms", "query"),
    (r"\broom\s*(status|list|inventory)\b", "query_rooms", "query"),

    # Staff
    (r"\b(staff|employee|team|worker|who.s (on shift|working))\b", "query_staff", "query"),

    # Housekeeping query
    (r"\b(pending|open|outstanding)\b.*\b(housekeeping|cleaning|hk)\b", "query_housekeeping", "query"),
    (r"\b(housekeeping|hk)\b.*\b(status|tasks?|pending|list)\b", "query_housekeeping", "query"),

    # Maintenance query
    (r"\b(pending|open|outstanding)\b.*\bmaintenance\b", "query_maintenance", "query"),
    (r"\bmaintenance\b.*\b(status|requests?|pending|list|open)\b", "query_maintenance", "query"),

    # Email
    (r"\b(send|email|notify|notification)\b.*\b(guest|all|checkout|welcome)\b", "send_email", "action"),
    (r"\bdraft\b.*\bemail\b", "draft_email", "action"),

    # Reports
    (r"\b(generate|create|make|produce)\b.*\breport\b", "generate_report", "report"),
    (r"\b(daily|weekly|monthly)\s*(ops?|operations?|report)\b", "generate_report", "report"),

    # Trends
    (r"\b(analyze|analysis|trend|compare|comparison)\b", "analyze_trends", "report"),

    # Forecast
    (r"\b(forecast|predict|projection)\b", "forecast", "report"),

    # Guest note
    (r"\b(add|create|write)\b.*\bnote\b.*\bguest\b", "create_guest_note", "action"),

    # Help
    (r"\b(help|what can you|capabilities|how to|how do i)\b", "help", "general"),

    # Follow-up indicators
    (r"^(sort|filter|order|group|show more|more details?|and the|what about)", "follow_up", "follow_up"),
    (r"^(yes|yeah|yep|sure|ok|okay|confirm|go ahead|proceed|do it)\s*[.!?]?\s*$", "confirmation", "general"),
    (r"^(no|nope|cancel|never\s*mind|stop|don.t)\s*[.!?]?\s*$", "cancellation", "general"),
]

# Compile patterns
_COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), intent, cat) for p, intent, cat in _REGEX_PATTERNS]


# ─────────────────────── Entity Extractor (Regex) ───────────────────────

class EntityExtractor:
    """Extract structured entities from user messages using regex patterns."""

    # Month name lookup for date parsing
    _MONTH_NAMES = {
        "jan": 1, "january": 1, "feb": 2, "february": 2,
        "mar": 3, "march": 3, "apr": 4, "april": 4,
        "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "september": 9, "sept": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    # Regex for month names (used in multiple patterns)
    _MONTH_RE = (
        r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
        r'jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
    )

    # Pattern: "check-in <date>" or "checkin <date>" — captures the date portion
    _CHECKIN_DATE_RE = re.compile(
        r'check[\-\s]?in\s+(?:on\s+)?'
        r'(?:(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?'                       # DD/MM or DD/MM/YY
        r'|(' + _MONTH_RE + r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?'  # Month Day [Year]
        r'|(\d{1,2})(?:st|nd|rd|th)?\s+(' + _MONTH_RE + r')(?:\s+(\d{4}))?'  # Day Month [Year]
        r'|(today|tomorrow))',                                                  # today/tomorrow
        re.IGNORECASE
    )

    _CHECKOUT_DATE_RE = re.compile(
        r'check[\-\s]?out\s+(?:on\s+)?'
        r'(?:(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?'
        r'|(' + _MONTH_RE + r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?'
        r'|(\d{1,2})(?:st|nd|rd|th)?\s+(' + _MONTH_RE + r')(?:\s+(\d{4}))?'
        r'|(today|tomorrow))',
        re.IGNORECASE
    )

    # Pattern: "from <date> to <date>" — extracts checkin and checkout from range syntax
    _FROM_TO_DATE_RE = re.compile(
        r'\bfrom\s+(' + _MONTH_RE + r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?'
        r'\s+to\s+(' + _MONTH_RE + r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?',
        re.IGNORECASE
    )

    # Pattern: "Book <Name>" or "booking for <Name>" — extract guest name for bookings
    # Uses case-sensitive capture for names (Capitalized Words) to avoid grabbing keywords
    _BOOKING_GUEST_RE = re.compile(
        r'(?:^|\b)[Bb]ook(?:ing)?(?:\s+[Ff]or)?\s+'
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})'
    )

    @classmethod
    def _parse_natural_date(cls, month_str: str, day: int, year_str: Optional[str] = None) -> Optional[date]:
        """Parse a natural month+day into a date, auto-advancing to next year if in the past."""
        month_num = cls._MONTH_NAMES.get(month_str.lower())
        if not month_num:
            return None
        today = date.today()
        year = int(year_str) if year_str else today.year
        try:
            parsed = date(year, month_num, day)
            # Auto-advance to next year if date is in the past and no explicit year
            if not year_str and parsed < today:
                parsed = date(year + 1, month_num, day)
            return parsed
        except ValueError:
            return None

    @classmethod
    def _extract_labelled_date(cls, match: re.Match) -> Optional[str]:
        """Extract a date from a check-in/check-out regex match group.
        Groups: (dd, mm, yy?, month_name, day, year?, day2, month_name2, year2?, today_tomorrow)
        """
        if not match:
            return None
        g = match.groups()
        today = date.today()

        # DD/MM[/YY] numeric
        if g[0] and g[1]:
            d, m = int(g[0]), int(g[1])
            y = int(g[2]) if g[2] else today.year
            if y < 100:
                y += 2000
            try:
                return date(y, m, d).isoformat()
            except ValueError:
                pass

        # "Month Day [Year]"
        if g[3] and g[4]:
            parsed = cls._parse_natural_date(g[3], int(g[4]), g[5])
            if parsed:
                return parsed.isoformat()

        # "Day Month [Year]"
        if g[6] and g[7]:
            parsed = cls._parse_natural_date(g[7], int(g[6]), g[8])
            if parsed:
                return parsed.isoformat()

        # "today" / "tomorrow"
        if g[9]:
            word = g[9].lower()
            if word == "today":
                return today.isoformat()
            elif word == "tomorrow":
                return (today + timedelta(days=1)).isoformat()

        return None

    @classmethod
    def extract(cls, message: str) -> Dict[str, Any]:
        """Extract all detectable entities from a message."""
        entities = {}
        msg_lower = message.lower()

        # ── Booking-specific: check-in / check-out dates ──────────────
        # Must run BEFORE generic date extraction so labelled dates take priority
        checkin_match = cls._CHECKIN_DATE_RE.search(message)
        if checkin_match:
            checkin_iso = cls._extract_labelled_date(checkin_match)
            if checkin_iso:
                entities["checkin_date"] = checkin_iso

        checkout_match = cls._CHECKOUT_DATE_RE.search(message)
        if checkout_match:
            checkout_iso = cls._extract_labelled_date(checkout_match)
            if checkout_iso:
                entities["checkout_date"] = checkout_iso

        # ── "from <date> to <date>" range syntax ──────────────────────
        if "checkin_date" not in entities or "checkout_date" not in entities:
            from_to_match = cls._FROM_TO_DATE_RE.search(message)
            if from_to_match:
                g = from_to_match.groups()
                # g: (from_month, from_day, from_year?, to_month, to_day, to_year?)
                from_date = cls._parse_natural_date(g[0], int(g[1]), g[2])
                to_date = cls._parse_natural_date(g[3], int(g[4]), g[5])
                if from_date:
                    entities.setdefault("checkin_date", from_date.isoformat())
                if to_date:
                    entities.setdefault("checkout_date", to_date.isoformat())

        # ── Booking guest name: "Book Yadhu Krishnan, ..." ────────────
        booking_guest_match = cls._BOOKING_GUEST_RE.search(message)
        if booking_guest_match:
            raw_name = booking_guest_match.group(1).strip()
            # Strip trailing date/keyword fragments that might have been captured
            raw_name = re.sub(r',?\s*$', '', raw_name).strip()
            if raw_name and len(raw_name) > 1:
                entities["booking_guest_name"] = raw_name

        # Room number
        room_match = re.search(r'\broom\s*#?\s*(\d{1,4})\b', msg_lower)
        if room_match:
            entities["room_id"] = int(room_match.group(1))

        # Booking ID
        booking_match = re.search(r'\bbooking\s*#?\s*(\d+)\b', msg_lower)
        if booking_match:
            entities["booking_id"] = int(booking_match.group(1))

        # Guest ID
        guest_match = re.search(r'\bguest\s*#?\s*(\d+)\b', msg_lower)
        if guest_match:
            entities["guest_id"] = int(guest_match.group(1))

        # Staff ID
        staff_match = re.search(r'\bstaff\s*#?\s*(\d+)\b', msg_lower)
        if staff_match:
            entities["staff_id"] = int(staff_match.group(1))

        # Task ID
        task_match = re.search(r'\btask\s*#?\s*(\d+)\b', msg_lower)
        if task_match:
            entities["task_id"] = int(task_match.group(1))

        # Priority
        priority_match = re.search(r'\b(urgent|high|medium|low)\s*(priority)?\b', msg_lower)
        if priority_match:
            entities["priority"] = priority_match.group(1)

        # Task type
        for task_type in ["deep_clean", "deep clean", "daily_clean", "daily clean",
                          "turndown", "inspection", "sanitize", "linen change"]:
            if task_type in msg_lower:
                entities["task_type"] = task_type.replace(" ", "_")
                break

        # Status
        for status in ["clean", "dirty", "available", "occupied", "maintenance",
                       "out of order", "checked_in", "checked_out", "confirmed",
                       "cancelled", "no_show", "inspected"]:
            if status.replace("_", " ") in msg_lower or status in msg_lower:
                entities["status"] = status.replace(" ", "_")
                break

        # Room type — search for multi-word types first, then single words
        # Includes common typos (delux → deluxe)
        room_type_patterns = [
            "deluxe suite", "delux suite", "ocean view", "garden view", "wellness suite",
            "oasis suite", "millimus studio",
            "standard", "deluxe", "delux", "suite", "penthouse", "studio",
            "family", "executive", "presidential", "premium", "oasis", "wellness",
        ]
        for room_type in room_type_patterns:
            if room_type in msg_lower:
                # Normalize common typos
                normalized = room_type.replace(" ", "_")
                if normalized.startswith("delux_") and not normalized.startswith("deluxe_"):
                    normalized = "deluxe_" + normalized[6:]
                elif normalized == "delux":
                    normalized = "deluxe"
                entities["room_type"] = normalized
                break

        # ── Dates — generic (only if no labelled check-in/out found) ──
        today = date.today()
        if "today" in msg_lower or "tonight" in msg_lower:
            entities.setdefault("target_date", today.isoformat())
        elif "tomorrow" in msg_lower:
            entities.setdefault("target_date", (today + timedelta(days=1)).isoformat())
        elif "yesterday" in msg_lower:
            entities.setdefault("target_date", (today - timedelta(days=1)).isoformat())
        else:
            # Try DD/MM or MM/DD or natural month+day
            date_match = re.search(r'\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b', message)
            if date_match:
                d, m, y = date_match.group(1), date_match.group(2), date_match.group(3)
                try:
                    year = int(y) if y else today.year
                    if year < 100:
                        year += 2000
                    entities.setdefault("target_date", date(year, int(m), int(d)).isoformat())
                except (ValueError, TypeError):
                    pass

            # Month name + day: "december 15", "jan 3"
            month_match = re.search(
                r'\b(' + cls._MONTH_RE + r')\s+(\d{1,2})\b', msg_lower
            )
            if month_match and "target_date" not in entities:
                parsed = cls._parse_natural_date(month_match.group(1), int(month_match.group(2)))
                if parsed:
                    entities.setdefault("target_date", parsed.isoformat())

        # ── Extract two numeric dates for booking (DD/MM/YY, DD/MM/YY) ──
        if "checkin_date" not in entities or "checkout_date" not in entities:
            all_numeric_dates = re.findall(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b', message)
            if len(all_numeric_dates) >= 2:
                for idx, (d, m, y) in enumerate(all_numeric_dates[:2]):
                    yr = int(y)
                    if yr < 100:
                        yr += 2000
                    try:
                        parsed_date = date(yr, int(m), int(d))
                        key = "checkin_date" if idx == 0 else "checkout_date"
                        entities.setdefault(key, parsed_date.isoformat())
                    except ValueError:
                        pass

        # Guest name — "for <Name>" or "guest <Name>"
        if "booking_guest_name" not in entities:
            name_match = re.search(r'\b(?:for|guest)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', message)
            if name_match:
                entities["guest_name"] = name_match.group(1)

        # Staff name — "assign to <Name>" or "by <Name>"
        staff_name_match = re.search(r'\b(?:assign to|to|by)\s+([A-Z][a-z]+)\b', message)
        if staff_name_match and "guest_name" not in entities and "booking_guest_name" not in entities:
            entities["staff_name"] = staff_name_match.group(1)

        # Note text — "note: ..." or "note that ..."
        note_match = re.search(r'\bnote[:\s]+(.+)', message, re.IGNORECASE)
        if note_match:
            entities["note_text"] = note_match.group(1).strip()

        return entities


# ─────────────────────── Circuit Breaker ───────────────────────

class CircuitBreaker:
    """Circuit breaker for LLM calls — falls back to regex after repeated failures."""

    def __init__(self, failure_threshold: int = 3, recovery_window_sec: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_window_sec = recovery_window_sec
        self._failures: List[float] = []
        self._tripped_at: Optional[float] = None

    def record_failure(self):
        now = time.time()
        self._failures.append(now)
        # Keep only recent failures
        cutoff = now - 60  # failures within last 60 seconds
        self._failures = [t for t in self._failures if t > cutoff]
        if len(self._failures) >= self.failure_threshold:
            self._tripped_at = now
            logger.warning(
                f"Circuit breaker TRIPPED — {self.failure_threshold} LLM failures in 60s. "
                f"Falling back to regex for {self.recovery_window_sec}s."
            )

    def record_success(self):
        self._failures.clear()
        self._tripped_at = None

    @property
    def is_open(self) -> bool:
        """True if circuit breaker is tripped (should use fallback)."""
        if self._tripped_at is None:
            return False
        if time.time() - self._tripped_at > self.recovery_window_sec:
            # Recovery window elapsed, try LLM again
            self._tripped_at = None
            self._failures.clear()
            return False
        return True


# ─────────────────────── Comprehension Agent ───────────────────────

class ComprehensionAgent:
    """LLM-backed intent classifier with regex fallback.

    Responsibilities:
    - Classify user intent(s) using GPT-4 structured output
    - Extract entities from the message
    - Detect multi-intent messages and decompose them
    - Detect follow-ups, confirmations, cancellations
    - Fall back to regex when LLM is unavailable or failing
    """

    def __init__(self):
        self._entity_extractor = EntityExtractor()
        self._circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_window_sec=300)
        self._llm: Optional[Any] = None
        self._init_llm()

    def _init_llm(self):
        """Initialize the LLM for intent classification."""
        if not LLM_AVAILABLE:
            logger.warning("LangChain not available — comprehension agent will use regex only")
            return

        try:
            from dotenv import dotenv_values
            from pathlib import Path

            # Load API key from .env
            env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
            env_vars = dotenv_values(str(env_path))
            api_key = env_vars.get("OPENAI_API_KEY") or settings.openai_api_key

            if not api_key:
                logger.warning("No OpenAI API key — comprehension agent will use regex only")
                return

            model = env_vars.get("OPENAI_MODEL", settings.openai_model) or "gpt-4"
            self._llm = ChatOpenAI(
                model=model,
                temperature=0,
                api_key=api_key,
                max_tokens=500,
            )
            logger.info(f"Comprehension agent LLM initialized with model: {model}")
        except Exception as e:
            logger.error(f"Failed to initialize comprehension LLM: {e}")

    async def classify(
        self,
        message: str,
        context_summary: str = "",
        active_entities: Optional[Dict[str, Any]] = None,
    ) -> ComprehensionResult:
        """Classify user intent(s) from message.

        Args:
            message: The user's raw message
            context_summary: Summary of recent conversation history
            active_entities: Currently tracked entities (for pronoun resolution)

        Returns:
            ComprehensionResult with detected intents and entities
        """
        # Check for simple confirmation/cancellation first (no LLM needed)
        quick_result = self._check_quick_patterns(message)
        if quick_result:
            return quick_result

        # Try LLM classification (if available and circuit breaker is closed)
        if self._llm and not self._circuit_breaker.is_open:
            try:
                result = await self._classify_with_llm(message, context_summary, active_entities)
                self._circuit_breaker.record_success()
                return result
            except Exception as e:
                logger.error(f"LLM classification failed: {e}")
                self._circuit_breaker.record_failure()

        # Fallback to regex
        return self._classify_with_regex(message)

    def _check_quick_patterns(self, message: str) -> Optional[ComprehensionResult]:
        """Quick-check for confirmations and cancellations (no LLM needed)."""
        msg_lower = message.lower().strip()

        confirmation_words = {"yes", "yeah", "yep", "sure", "ok", "okay", "confirm",
                              "go ahead", "proceed", "do it", "approved", "accept"}
        cancellation_words = {"no", "nope", "cancel", "nevermind", "never mind",
                              "stop", "don't", "abort", "reject"}

        # Only match if the message is short (< 5 words) to avoid false positives
        words = msg_lower.split()
        if len(words) <= 4:
            is_confirm = any(w in confirmation_words for w in words)
            is_cancel = any(w in cancellation_words for w in words)

            if is_confirm and not is_cancel:
                return ComprehensionResult(
                    intents=[],
                    raw_message=message,
                    is_confirmation=True,
                )
            if is_cancel and not is_confirm:
                return ComprehensionResult(
                    intents=[],
                    raw_message=message,
                    is_cancellation=True,
                )

        return None

    async def _classify_with_llm(
        self,
        message: str,
        context_summary: str,
        active_entities: Optional[Dict[str, Any]],
    ) -> ComprehensionResult:
        """Use LLM for intent classification with structured output."""
        # Build user prompt with context
        user_parts = []
        if context_summary:
            user_parts.append(f"[Conversation context: {context_summary}]")
        if active_entities:
            entity_strs = [f"{k}={v}" for k, v in active_entities.items() if v is not None]
            if entity_strs:
                user_parts.append(f"[Active entities: {', '.join(entity_strs)}]")
        user_parts.append(f"User message: {message}")

        user_prompt = "\n".join(user_parts)

        response = await self._llm.ainvoke([
            SystemMessage(content=COMPREHENSION_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])

        # Parse LLM JSON response
        return self._parse_llm_response(response.content, message)

    def _parse_llm_response(self, content: str, original_message: str) -> ComprehensionResult:
        """Parse LLM JSON response into ComprehensionResult."""
        try:
            # Extract JSON from response (may be wrapped in markdown code blocks)
            json_str = content.strip()
            if json_str.startswith("```"):
                # Strip markdown code block
                json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
                json_str = re.sub(r"\s*```$", "", json_str)

            data = json.loads(json_str)

            intents = []
            for intent_data in data.get("intents", []):
                category_str = intent_data.get("category", "general")
                try:
                    category = IntentCategory(category_str)
                except ValueError:
                    category = IntentCategory.GENERAL

                intents.append(DetectedIntent(
                    intent=intent_data.get("intent", "general"),
                    category=category,
                    confidence=float(intent_data.get("confidence", 0.8)),
                    entities=intent_data.get("entities", {}),
                ))

            # Merge regex-extracted entities into each intent
            regex_entities = self._entity_extractor.extract(original_message)
            for intent in intents:
                for key, value in regex_entities.items():
                    if key not in intent.entities:
                        intent.entities[key] = value

            return ComprehensionResult(
                intents=intents,
                raw_message=original_message,
                is_follow_up=data.get("is_follow_up", False),
                is_confirmation=data.get("is_confirmation", False),
                is_cancellation=data.get("is_cancellation", False),
                requires_clarification=data.get("requires_clarification", False),
                clarification_question=data.get("clarification_question"),
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse LLM comprehension response: {e}")
            # Fall back to regex
            return self._classify_with_regex(original_message)

    def _classify_with_regex(self, message: str) -> ComprehensionResult:
        """Regex-based fallback classification (mirrors existing IntentClassifier)."""
        msg_lower = message.lower().strip()
        entities = self._entity_extractor.extract(message)

        # Check compiled patterns
        matched_intents: List[DetectedIntent] = []
        matched_names = set()

        for pattern, intent_name, category_str in _COMPILED_PATTERNS:
            if intent_name in matched_names:
                continue
            if pattern.search(msg_lower):
                # Special handling for confirmation/cancellation
                if intent_name == "confirmation":
                    return ComprehensionResult(
                        intents=[], raw_message=message, is_confirmation=True
                    )
                if intent_name == "cancellation":
                    return ComprehensionResult(
                        intents=[], raw_message=message, is_cancellation=True
                    )

                try:
                    category = IntentCategory(category_str)
                except ValueError:
                    category = IntentCategory.GENERAL

                matched_intents.append(DetectedIntent(
                    intent=intent_name,
                    category=category,
                    confidence=0.75,
                    entities=entities.copy(),
                ))
                matched_names.add(intent_name)

        # If nothing matched, classify as general
        if not matched_intents:
            matched_intents.append(DetectedIntent(
                intent="general",
                category=IntentCategory.GENERAL,
                confidence=0.3,
                entities=entities,
            ))

        # Check for follow-up
        is_follow_up = any(
            re.match(r"^(sort|filter|order|group|show more|more details?|and the|what about)",
                      msg_lower)
            for _ in [None]
        )

        return ComprehensionResult(
            intents=matched_intents,
            raw_message=message,
            is_follow_up=is_follow_up,
        )
