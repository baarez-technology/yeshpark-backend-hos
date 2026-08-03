"""
In-House Guest Assistant Chatbot Service
Handles guest queries, FAQ search, assistance requests, and automatic staff scheduling
This is separate from the AGI guest_ai_assistant which handles bookings
"""

import os
import re
import json
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
from difflib import SequenceMatcher

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guest_chat import (
    GuestChatSession, GuestChatConversation, StaffTask, StaffNotification
)
from app.models.reservations import Reservation, Guest
from app.models.inventory import Room
from app.models.user import User
from app.models.operations import HousekeepingTask, MaintenanceRequest

# Load environment variables
from dotenv import load_dotenv, dotenv_values
from app.core.config import settings

# Load .env file directly to get the key (bypassing system env vars that might be wrong)
env_file_path = Path(__file__).parent.parent / ".env"
env_dict = {}
if env_file_path.exists():
    env_dict = dotenv_values(env_file_path)

# Also load into os.environ for other parts of the app
load_dotenv(override=True)  # override=True ensures .env file takes precedence over system env vars

# Setup logging first
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("guest_assistant_chatbot")

# Use settings from config (consistent with rest of app)
# Priority: 1) .env file (direct read), 2) os.getenv (system env), 3) settings, 4) empty
# This ensures .env file takes precedence (since system env might have wrong key)
env_key_from_file = env_dict.get("OPENAI_API_KEY", "").strip() if env_dict else ""
env_key_from_system = os.getenv("OPENAI_API_KEY", "").strip()
settings_key_raw = settings.openai_api_key.strip() if settings.openai_api_key else ""

# Remove all whitespace (including newlines) to handle multi-line keys
env_key_from_file_clean = "".join(env_key_from_file.split()) if env_key_from_file else ""
env_key_from_system_clean = "".join(env_key_from_system.split()) if env_key_from_system else ""
settings_key_clean = "".join(settings_key_raw.split()) if settings_key_raw else ""

# Prefer .env file over system env (system env might have wrong/old key)
OPENAI_API_KEY = env_key_from_file_clean if env_key_from_file_clean else (env_key_from_system_clean if env_key_from_system_clean else settings_key_clean)

# Get model from settings or env, default to gpt-3.5-turbo
OPENAI_MODEL = settings.openai_model if settings.openai_model else os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

# Log which key source is being used (without exposing the full key)
if OPENAI_API_KEY:
    if env_key_from_file_clean:
        key_source = ".env file"
    elif env_key_from_system_clean:
        key_source = "system environment variable"
    else:
        key_source = "settings"
    log.info(f"OpenAI API key loaded from {key_source} (length: {len(OPENAI_API_KEY)})")
    log.info(f"Using OpenAI model: {OPENAI_MODEL}")
else:
    log.info("No OpenAI API key found - will use heuristic classification only")

# Optional external libs (best-effort)
openai_client = None
try:
    from openai import OpenAI
    if OPENAI_API_KEY:
        try:
            # Initialize OpenAI client with the API key (new method)
            openai_client = OpenAI(api_key=OPENAI_API_KEY)
            _OPENAI = True
            log.info("OpenAI SDK available with client initialization.")
        except Exception as e:
            log.warning(f"OpenAI client initialization failed: {e}, will use heuristics only")
            _OPENAI = False
            openai_client = None
    else:
        _OPENAI = False
        log.info("OPENAI_API_KEY not set: Using heuristic classification (works without OpenAI).")
except ImportError:
    OpenAI = None
    _OPENAI = False
    log.info("OpenAI SDK not installed; Using heuristic classification (works without OpenAI).")
except Exception as e:
    log.warning(f"OpenAI import error: {e}, will use heuristics only")
    _OPENAI = False
    openai_client = None

try:
    from sentence_transformers import SentenceTransformer
    import faiss
    import numpy as np
    _SEMANTIC = True
    log.info("SentenceTransformer + FAISS available for semantic FAQ search.")
except Exception:
    SentenceTransformer = None
    faiss = None
    np = None
    _SEMANTIC = False
    log.info("Semantic libs not available; will use fuzzy fallback for FAQ.")

try:
    from rapidfuzz import fuzz
    _RAPIDFUZZ = True
except Exception:
    fuzz = None
    _RAPIDFUZZ = False

# ---------------- FAQ LOAD ----------------
# Try to load FAQ from Backend folder first, then old code location, or use default
FAQ_FILE = Path(__file__).parent.parent / "hotel_faqs.json"  # Backend/hotel_faqs.json
if not FAQ_FILE.exists():
    FAQ_FILE = Path(__file__).parent.parent.parent / "Extras" / "old code" / "backend" / "hotel_faqs.json"
if not FAQ_FILE.exists():
    FAQ_FILE = Path(__file__).parent.parent.parent / "Extras" / "old code" / "backend" / "Extras" / "AI_Agents_ChatBot" / "AI_Agents_ChatBot" / "hotel_faqs.json"

def load_faqs():
    """Load FAQs from JSON file"""
    if not FAQ_FILE.exists():
        log.warning(f"FAQ file not found at {FAQ_FILE}, using default FAQs")
        return get_default_faqs()
    try:
        with open(FAQ_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        qas = []
        def walk(x):
            if isinstance(x, dict):
                if "question" in x and "answer" in x:
                    qas.append({
                        "id": f"faq_{len(qas)+1}",
                        "question": x["question"],
                        "answer": x["answer"],
                        "paraphrases": x.get("paraphrases", [])
                    })
                else:
                    for v in x.values(): walk(v)
            elif isinstance(x, list):
                for i in x: walk(i)
        walk(data)
        return qas
    except Exception as e:
        log.error(f"Error loading FAQ data: {e}, using default FAQs")
        return get_default_faqs()

def get_default_faqs():
    """Default FAQs if file not found"""
    return [
        {
            "id": "faq_1",
            "question": "What are your check-in and check-out times?",
            "answer": "Check-in time is 3:00 PM and check-out time is 11:00 AM. Early check-in and late check-out may be available upon request, subject to availability.",
            "paraphrases": ["check in time", "check out time", "when can I check in", "when do I need to check out"]
        },
        {
            "id": "faq_2",
            "question": "What is your cancellation policy?",
            "answer": "Our cancellation policy varies by rate type. Standard rates allow free cancellation up to 24-48 hours before arrival. Non-refundable rates may apply. Check your booking confirmation for details.",
            "paraphrases": ["cancel booking", "refund policy", "cancellation"]
        },
        {
            "id": "faq_3",
            "question": "Do you have WiFi?",
            "answer": "Yes, we provide complimentary high-speed WiFi throughout the hotel. The WiFi password is available at the front desk or in your room.",
            "paraphrases": ["internet", "wifi password", "wireless", "internet access"]
        },
        {
            "id": "faq_4",
            "question": "Is parking available?",
            "answer": "Yes, we offer complimentary self-parking for all guests. Valet parking is also available for an additional fee.",
            "paraphrases": ["parking", "car parking", "valet"]
        },
        {
            "id": "faq_5",
            "question": "Do you have room service?",
            "answer": "Yes, room service is available 24/7. You can order from our menu by calling the front desk or using the in-room tablet.",
            "paraphrases": ["room service", "food delivery", "order food"]
        }
    ]

FAQS = load_faqs()
log.info(f"Loaded {len(FAQS)} FAQs")

# ---------------- Semantic Index (optional) ----------------
SB_MODEL, EMBED, INDEX = None, None, None
if _SEMANTIC and FAQS:
    try:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            log.info(f"Use pytorch device: {device}")
            SB_MODEL = SentenceTransformer("all-mpnet-base-v2", device=device)
        except:
            SB_MODEL = SentenceTransformer("all-mpnet-base-v2")
            log.info("Using CPU for sentence transformers")
            
        texts = []
        for f in FAQS:
            texts.append(f["question"] + " " + f.get("answer", ""))
            for p in f.get("paraphrases", []):
                texts.append(p)
        
        EMBED = SB_MODEL.encode(texts, convert_to_numpy=True, show_progress_bar=False).astype("float32")
        faiss.normalize_L2(EMBED)
        INDEX = faiss.IndexFlatIP(EMBED.shape[1])
        INDEX.add(EMBED)
        log.info("Semantic FAQ index ready")
    except Exception as e:
        log.warning(f"Semantic index init failed: {e}")
        SB_MODEL, EMBED, INDEX = None, None, None

# ---------------- Utils ----------------
def normalize(text):
    return re.sub(r'[^a-z0-9 ]+', '', text.lower())

def is_valid_room_number(text):
    """Check if text is a valid room number (3 digits)"""
    if not text:
        return False
    text = text.strip()
    return bool(re.match(r'^[1-9]\d{2}$', text))

greeting_patterns = [
    "hi", "hello", "hey", "greetings", "good morning", "good afternoon", 
    "good evening", "howdy", "welcome", "hola", "bonjour", "ciao"
]

def is_greeting(text):
    """Check if the message is a greeting"""
    text = text.lower().strip()
    return any(text.startswith(g) or text == g for g in greeting_patterns)

def generate_greeting_response():
    """Generate a greeting response"""
    greetings = [
        "Hello! Welcome to Glimmora Hotel & Suites! 👋 I'm your in-house assistant. How can I help you today?",
        "Hi there! I'm here to assist you with any questions or requests. What can I do for you?",
        "Good day! Welcome! I'm your hotel assistant. How may I assist you today?",
    ]
    return greetings[0]  # Use first greeting for consistency

# ---------------- FAQ Search ----------------
def hybrid_faq_search(query, top_n=3):
    """Return top-N FAQ candidates (semantic + fuzzy hybrid)"""
    candidates = []
    if SB_MODEL and INDEX is not None:
        try:
            qv = SB_MODEL.encode([query], convert_to_numpy=True).astype("float32")
            faiss.normalize_L2(qv)
            D, I = INDEX.search(qv, top_n)
            all_texts = [f["question"] + " " + f.get("answer", "") for f in FAQS]
            cnt = 0
            for i in I[0]:
                if i < len(all_texts):
                    faq_idx = i % len(FAQS)
                    f = FAQS[faq_idx]
                    sem_score = float(D[0][cnt])
                    if _RAPIDFUZZ:
                        texts = [f["question"]] + f.get("paraphrases", [])
                        fuzzy_score = max([fuzz.token_set_ratio(query, t)/100 for t in texts])
                    else:
                        fuzzy_score = SequenceMatcher(None, query, f["question"]).ratio()
                    combined_score = 0.7 * sem_score + 0.3 * fuzzy_score
                    candidates.append({"faq": f, "score": combined_score})
                    cnt += 1
        except Exception as e:
            log.warning(f"hybrid_faq_search semantic branch failed: {e}")

    if not candidates:
        # fallback fuzzy-only
        query_lower = query.lower()
        for f in FAQS:
            texts = [f["question"]] + f.get("paraphrases", [])
            # Try both full question and answer matching
            question_lower = f["question"].lower()
            answer_lower = f.get("answer", "").lower()
            
            # Calculate fuzzy scores
            question_score = max([SequenceMatcher(None, query_lower, t.lower()).ratio() for t in texts])
            # Also check if query keywords appear in question or answer
            query_words = set(query_lower.split())
            question_words = set(question_lower.split())
            answer_words = set(answer_lower.split())
            
            # Boost score if key terms match
            keyword_match = len(query_words & question_words) / max(len(query_words), 1)
            answer_match = len(query_words & answer_words) / max(len(query_words), 1)
            
            # Combine scores
            fuzzy_score = max(question_score, keyword_match * 0.8, answer_match * 0.6)
            candidates.append({"faq": f, "score": fuzzy_score})

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_n]

FAQ_CONFIDENCE_THRESHOLD = 0.40  # Lowered to catch more FAQ matches

# ---------------- Classification ----------------
faq_first_words = [
    "what", "when", "where", "which", "who", "why", "how",
    "can", "could", "shall", "should", "will", "would", "may", "might", "must",
    "do", "does", "did", "is", "are", "am", "was", "were", "have", "has", "had",
]

def heuristic_classify(text):
    """Lightweight classifier for when OpenAI is not available"""
    if not text or not text.strip():
        return {"classification": "Other", "confidence": 0.5}
    
    t = text.lower().strip()
    
    # Check for greetings first
    if is_greeting(t):
        return {"classification": "Greeting", "confidence": 0.9}
        
    # Assistance keywords (more specific to avoid false positives)
    assistance_keywords = [
        "clean my room", "cleaning my room", "towel", "towels", "bring me", "please bring",
        "broken", "fix", "repair", "maintenance", "room service", "housekeeping", 
        "concierge", "water", "blanket", "pillow", "help me", "assist me", "need help"
    ]
    # Check for room number pattern
    has_room_number = bool(re.search(r"\b\d{3}\b", t))
    # Check for assistance keywords
    has_assistance_keywords = any(kw in t for kw in assistance_keywords)
    
    if has_assistance_keywords or (has_room_number and any(kw in ["clean", "towel", "service", "help"] for kw in t.split())):
        return {"classification": "Assistance", "confidence": 0.8}
    
    # FAQ-like patterns - check for question words anywhere, not just at start
    # Also check for common FAQ keywords
    faq_keywords = [
        "policy", "cancellation", "check-in", "check-out", "check in", "check out",
        "wifi", "wifi", "internet", "parking", "breakfast", "amenities", "facilities",
        "payment", "refund", "booking", "reservation", "room type", "pets", "smoking",
        "pool", "gym", "spa", "restaurant", "hours", "time", "price", "rate", "cost"
    ]
    
    # Check if starts with question word
    starts_with_question = any(t.startswith(fw + " ") or t == fw for fw in faq_first_words)
    # Check if contains FAQ keywords
    has_faq_keywords = any(kw in t for kw in faq_keywords)
    # Check if it's a question (ends with ? or contains question structure)
    is_question = t.endswith("?") or any(fw in t for fw in ["what", "when", "where", "which", "who", "why", "how"])
    
    if starts_with_question or (has_faq_keywords and is_question) or (has_faq_keywords and not has_assistance_keywords):
        return {"classification": "FAQ", "confidence": 0.75}
    
    # fallback
    return {"classification": "Other", "confidence": 0.5}

def classify(q: str):
    """
    Classify into exactly one of: FAQ, Assistance, Greeting, Other
    Prefer OpenAI; fallback to heuristic_classify.
    """
    # First check if it's a greeting
    if is_greeting(q):
        return {"classification": "Greeting", "confidence": 0.9}
        
    try:
        if _OPENAI and openai_client and OPENAI_API_KEY:
            system_msg = """
You are an AI assistant for a hotel.
Your job is ONLY to classify each guest message into EXACTLY ONE of the following categories:
FAQ, Assistance, Greeting, Other
Return ONLY the category name.
"""
            user_msg = f"Guest message: {q}"
            try:
                # Use the new OpenAI client (same as user's working code)
                resp = openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg}
                    ],
                    temperature=0.0
                )
                txt = resp.choices[0].message.content.strip()
                
                valid = ["FAQ", "Assistance", "Greeting", "Other"]
                for v in valid:
                    if txt.lower() == v.lower():
                        return {"classification": v, "confidence": 0.9}
                # if LLM returns anything else, fallback
                return heuristic_classify(q)
            except Exception as api_error:
                # If OpenAI API fails (rate limit, quota, etc.), use heuristic
                error_str = str(api_error)
                if "429" in error_str or "rate limit" in error_str.lower() or "quota" in error_str.lower():
                    log.warning(f"OpenAI API rate limit/quota exceeded, using heuristic classification: {api_error}")
                else:
                    log.warning(f"OpenAI API call failed: {api_error}, using heuristic classification")
                return heuristic_classify(q)
        else:
            return heuristic_classify(q)
    except Exception as e:
        # Handle any other errors gracefully
        log.warning(f"classify() failed: {e}, using heuristic fallback")
        return heuristic_classify(q)

# ---------------- Database Helpers ----------------
async def get_or_create_chat_session(
    session_id: str,
    user_id: Optional[int],
    guest_id: Optional[int],
    db: AsyncSession
) -> GuestChatSession:
    """Get or create a chat session"""
    result = await db.exec(
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
        db.add(session)
        await db.commit()
        await db.refresh(session)
    
    return session

async def get_active_reservation(
    user_id: Optional[int],
    guest_id: Optional[int],
    room_number: Optional[str],
    db: AsyncSession
) -> Optional[Reservation]:
    """Get active reservation for guest (checked in)"""
    if not guest_id and not user_id:
        return None
    
    # Try to find guest by user_id if guest_id not provided
    if not guest_id and user_id:
        # In this system, user and guest might be separate
        # For now, we'll check reservations by user_id if there's a link
        pass
    
    # Check by guest_id
    if guest_id:
        result = await db.exec(
            select(Reservation)
            .where(Reservation.guest_id == guest_id)
            .where(Reservation.status == "checked_in")
            .order_by(Reservation.created_at.desc())
        )
        reservation = result.first()
        if reservation:
            return reservation
    
    # Check by room_number if provided
    if room_number:
        # Find room first
        room_result = await db.exec(
            select(Room).where(Room.number == room_number)
        )
        room = room_result.first()
        if room:
            result = await db.exec(
                select(Reservation)
                .where(Reservation.room_id == room.id)
                .where(Reservation.status == "checked_in")
                .order_by(Reservation.created_at.desc())
            )
            reservation = result.first()
            if reservation:
                return reservation
    
    return None

async def find_available_staff(
    task_type: str,
    priority: str,
    db: AsyncSession
) -> Optional[User]:
    """
    Find available staff member for task assignment
    Uses simple round-robin or priority-based assignment
    """
    # Map task types to staff roles
    role_mapping = {
        "housekeeping": "housekeeping",
        "maintenance": "operations",
        "concierge": "front_desk",
        "room_service": "front_desk",
        "other": "front_desk"
    }
    
    role = role_mapping.get(task_type, "front_desk")
    
    # Find active staff with matching role
    result = await db.exec(
        select(User)
        .where(User.role == role)
        .where(User.is_active == True)
    )
    staff_members = result.all()
    
    if not staff_members:
        # Fallback to any active staff
        from sqlmodel import or_
        result = await db.exec(
            select(User)
            .where(User.is_active == True)
            .where(
                or_(
                    User.role == "front_desk",
                    User.role == "operations",
                    User.role == "housekeeping"
                )
            )
        )
        staff_members = result.all()
    
    if not staff_members:
        return None
    
    # Simple round-robin: find staff with least pending tasks
    # For now, just return first available
    return staff_members[0]

async def create_staff_task(
    task_type: str,
    title: str,
    description: str,
    room_number: Optional[str],
    room_id: Optional[int],
    reservation_id: Optional[int],
    guest_id: Optional[int],
    conversation_id: str,
    priority: str,
    db: AsyncSession
) -> StaffTask:
    """Create a staff task and assign it"""
    # Find available staff
    assigned_staff = await find_available_staff(task_type, priority, db)
    
    # Estimate duration based on task type
    duration_map = {
        "housekeeping": 30,
        "maintenance": 60,
        "concierge": 15,
        "room_service": 20,
        "other": 30
    }
    estimated_duration = duration_map.get(task_type, 30)
    
    # Schedule for now or soon
    scheduled_for = datetime.utcnow() + timedelta(minutes=5)
    
    task = StaffTask(
        task_type=task_type,
        title=title,
        description=description,
        room_number=room_number,
        room_id=room_id,
        reservation_id=reservation_id,
        guest_id=guest_id,
        conversation_id=conversation_id,
        priority=priority,
        status="assigned" if assigned_staff else "pending",
        assigned_to=assigned_staff.id if assigned_staff else None,
        scheduled_for=scheduled_for,
        estimated_duration=estimated_duration
    )
    
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    # Create notification for staff if assigned
    if assigned_staff:
        notification = StaffNotification(
            staff_id=assigned_staff.id,
            task_id=task.id,
            notification_type="task_assigned",
            title=f"New {task_type} task assigned",
            message=f"{title} - {description}"
        )
        db.add(notification)
        await db.commit()
    
    return task

def extract_task_info(message: str) -> Dict[str, Any]:
    """Extract task information from user message"""
    msg_lower = message.lower()
    
    # Determine task type
    task_type = "other"
    if any(kw in msg_lower for kw in ["clean", "cleaning", "housekeeping", "towel", "towels", "bed", "sheets"]):
        task_type = "housekeeping"
    elif any(kw in msg_lower for kw in ["broken", "fix", "repair", "maintenance", "not working", "broken"]):
        task_type = "maintenance"
    elif any(kw in msg_lower for kw in ["room service", "food", "order", "delivery"]):
        task_type = "room_service"
    elif any(kw in msg_lower for kw in ["concierge", "help", "information", "recommendation"]):
        task_type = "concierge"
    
    # Determine priority
    priority = "normal"
    if any(kw in msg_lower for kw in ["urgent", "emergency", "immediately", "asap", "now"]):
        priority = "urgent"
    elif any(kw in msg_lower for kw in ["soon", "quickly", "fast"]):
        priority = "high"
    
    # Extract room number if mentioned
    room_match = re.search(r'\b(\d{3})\b', message)
    room_number = room_match.group(1) if room_match else None
    
    return {
        "task_type": task_type,
        "priority": priority,
        "room_number": room_number,
        "title": message[:100],  # Truncate for title
        "description": message
    }

async def generate_assistance_response(
    message: str,
    room_number: Optional[str],
    task_created: bool = False
) -> str:
    """Generate response for assistance requests"""
    if task_created:
        if room_number:
            return f"Thank you for your request! I've scheduled assistance for Room {room_number}. Our staff will be there shortly. Is there anything else I can help you with?"
        else:
            return "Thank you for your request! I've scheduled assistance for you. Our staff will be there shortly. Is there anything else I can help you with?"
    else:
        if not room_number:
            return "I'd be happy to help! To schedule assistance, I'll need your room number. Please provide your 3-digit room number (e.g., 305)."
        else:
            return f"Thank you! I have your room number as {room_number}. What kind of assistance do you need?"

# ---------------- Main Processing Function ----------------
async def process_guest_message(
    message: str,
    session_id: str,
    user_id: Optional[int] = None,
    guest_id: Optional[int] = None,
    room_number: Optional[str] = None,
    db: AsyncSession = None
) -> Dict[str, Any]:
    """
    Main function to process guest messages
    Returns response with classification and actions
    """
    if not db:
        raise ValueError("Database session is required")
    
    # Ensure message is not empty
    if not message or not message.strip():
        return {
            "response": "I'm here to help! Please send me a message and I'll assist you.",
            "classification": "Other",
            "requires_staff_action": False,
            "session_id": session_id
        }
    
    # Get or create chat session
    chat_session = await get_or_create_chat_session(session_id, user_id, guest_id, db)
    
    # Update last activity
    chat_session.last_activity = datetime.utcnow()
    await db.commit()
    
    # Check for active reservation/check-in
    active_reservation = await get_active_reservation(user_id, guest_id, room_number, db)
    has_active_booking = active_reservation is not None
    
    # Update session with reservation info if found
    if active_reservation:
        chat_session.reservation_id = active_reservation.id
        if active_reservation.room_id:
            room_result = await db.exec(select(Room).where(Room.id == active_reservation.room_id))
            room = room_result.first()
            if room:
                chat_session.room_number = room.number
                room_number = room.number
        await db.commit()
    
    # Classify message
    try:
        classification_result = classify(message)
        classification = classification_result.get("classification", "Other")
        if not classification:
            classification = "Other"
    except Exception as e:
        log.error(f"Error classifying message '{message}': {e}", exc_info=True)
        classification = "Other"
    
    # Handle greetings
    if classification == "Greeting":
        try:
            response = generate_greeting_response()
            if not response or not response.strip():
                response = "Hello! Welcome to Glimmora Hotel. How can I assist you today?"
        except Exception as e:
            log.error(f"Error generating greeting response: {e}")
            response = "Hello! Welcome to Glimmora Hotel. How can I assist you today?"
        
        conversation = GuestChatConversation(
            conversation_id=str(uuid.uuid4()),
            session_id=session_id,
            user_query=message,
            bot_response=response,
            classification=classification
        )
        db.add(conversation)
        await db.commit()
        
        log.info(f"Greeting response generated: {response[:50]}...")
        
        return {
            "response": response,
            "classification": classification,
            "requires_staff_action": False,
            "session_id": session_id
        }
    
    # Handle FAQ - also try FAQ search for "Other" classification if it looks like a question
    should_try_faq = classification == "FAQ"
    if not should_try_faq and classification == "Other":
        # Check if it might be an FAQ question
        message_lower = message.lower()
        faq_indicators = ["policy", "cancellation", "check-in", "check-out", "wifi", "parking", 
                         "breakfast", "amenities", "payment", "refund", "booking", "reservation"]
        question_indicators = ["what", "when", "where", "which", "who", "why", "how", "can", "do", "is", "are"]
        if any(ind in message_lower for ind in faq_indicators) or any(ind in message_lower for ind in question_indicators):
            should_try_faq = True
            log.info(f"Treating 'Other' classification as potential FAQ: {message[:50]}")
    
    if should_try_faq:
        faq_candidates = hybrid_faq_search(message, top_n=3)
        log.info(f"FAQ search for '{message[:50]}...' returned {len(faq_candidates)} candidates")
        if faq_candidates:
            best_score = faq_candidates[0].get("score", 0)
            log.info(f"Best FAQ match score: {best_score:.3f} (threshold: {FAQ_CONFIDENCE_THRESHOLD})")
        
        if faq_candidates and faq_candidates[0].get("score", 0) >= FAQ_CONFIDENCE_THRESHOLD:
            best_faq = faq_candidates[0]["faq"]
            response = best_faq["answer"]
            log.info(f"FAQ match found: {best_faq.get('id', 'unknown')} - {best_faq.get('question', '')[:50]}")
            
            conversation = GuestChatConversation(
                conversation_id=str(uuid.uuid4()),
                session_id=session_id,
                user_query=message,
                bot_response=response,
                classification="FAQ",  # Update classification to FAQ if we found a match
                faq_id=best_faq["id"]
            )
            db.add(conversation)
            await db.commit()
            
            return {
                "response": response,
                "classification": "FAQ",
                "faq_id": best_faq["id"],
                "requires_staff_action": False,
                "session_id": session_id
            }
        else:
            # No good FAQ match - but only show this message if it was classified as FAQ
            if classification == "FAQ":
                response = "I'm sorry, I couldn't find a specific answer to that question. Could you please rephrase it, or would you like me to connect you with our front desk?"
                
                conversation = GuestChatConversation(
                    conversation_id=str(uuid.uuid4()),
                    session_id=session_id,
                    user_query=message,
                    bot_response=response,
                    classification=classification
                )
                db.add(conversation)
                await db.commit()
                
                return {
                    "response": response,
                    "classification": classification,
                    "requires_staff_action": False,
                    "session_id": session_id
                }
            # If it was "Other" and we tried FAQ but didn't find a match, continue to "Other" handling
    
    # Handle Assistance requests
    if classification == "Assistance":
        # Check if guest has active booking
        if not has_active_booking:
            response = "I'd be happy to help with assistance requests! However, I can only schedule assistance for guests who have checked in. For general questions, I'm here to help. Would you like to know about our services or amenities?"
            
            conversation = GuestChatConversation(
                conversation_id=str(uuid.uuid4()),
                session_id=session_id,
                user_query=message,
                bot_response=response,
                classification=classification
            )
            db.add(conversation)
            await db.commit()
            
            return {
                "response": response,
                "classification": classification,
                "requires_staff_action": False,
                "session_id": session_id,
                "needs_active_booking": True
            }
        
        # Extract task info
        task_info = extract_task_info(message)
        
        # Get room number from session or task info
        final_room_number = room_number or task_info.get("room_number") or chat_session.room_number
        
        if not final_room_number:
            response = await generate_assistance_response(message, None, False)
            
            conversation = GuestChatConversation(
                conversation_id=str(uuid.uuid4()),
                session_id=session_id,
                user_query=message,
                bot_response=response,
                classification=classification
            )
            db.add(conversation)
            await db.commit()
            
            return {
                "response": response,
                "classification": classification,
                "requires_staff_action": False,
                "session_id": session_id,
                "needs_room_number": True
            }
        
        # Get room_id
        room_result = await db.exec(select(Room).where(Room.number == final_room_number))
        room = room_result.first()
        room_id = room.id if room else None
        
        # Create staff task
        conversation_id = str(uuid.uuid4())
        task = await create_staff_task(
            task_type=task_info["task_type"],
            title=task_info["title"],
            description=task_info["description"],
            room_number=final_room_number,
            room_id=room_id,
            reservation_id=active_reservation.id if active_reservation else None,
            guest_id=guest_id or chat_session.guest_id,
            conversation_id=conversation_id,
            priority=task_info["priority"]
        )
        
        response = await generate_assistance_response(message, final_room_number, True)
        
        conversation = GuestChatConversation(
            conversation_id=conversation_id,
            session_id=session_id,
            user_query=message,
            bot_response=response,
            classification=classification,
            requires_staff_action=True,
            staff_task_id=task.id,
            room_number=final_room_number
        )
        db.add(conversation)
        await db.commit()
        
        return {
            "response": response,
            "classification": classification,
            "requires_staff_action": True,
            "staff_task_id": task.id,
            "task_type": task_info["task_type"],
            "session_id": session_id
        }
    
    # Handle Other - fallback for any unhandled cases
    response = "I understand you need help. For specific assistance, please make sure you have an active booking and are checked in. Otherwise, I can help answer general questions about our hotel. How can I assist you?"
    
    # Ensure response is never empty
    if not response or not response.strip():
        response = "I'm here to help! Could you please rephrase your question or let me know what you need assistance with?"
    
    try:
        conversation = GuestChatConversation(
            conversation_id=str(uuid.uuid4()),
            session_id=session_id,
            user_query=message,
            bot_response=response,
            classification=classification
        )
        db.add(conversation)
        await db.commit()
    except Exception as e:
        log.error(f"Error saving conversation: {e}", exc_info=True)
        # Continue even if save fails
    
    log.info(f"Processed message '{message[:50]}...' - Classification: {classification}, Response length: {len(response)}")
    
    return {
        "response": response,
        "classification": classification,
        "requires_staff_action": False,
        "session_id": session_id
    }

