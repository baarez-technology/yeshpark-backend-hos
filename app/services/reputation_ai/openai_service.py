"""
OpenAI Service for Reputation Management
Provides AI-powered review response generation, deep sentiment analysis,
category detection, and root cause analysis using OpenAI GPT models.
"""
import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from app.core.config import settings

logger = logging.getLogger(__name__)


class ReputationOpenAIService:
    """OpenAI integration for reputation management"""

    def __init__(self):
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model or "gpt-3.5-turbo"
        self._client: Optional[AsyncOpenAI] = None

        # Check if OpenAI is available and configured
        self._openai_enabled = bool(OPENAI_AVAILABLE and self.api_key)

        if self._openai_enabled:
            try:
                self._client = AsyncOpenAI(api_key=self.api_key)
                logger.info(f"OpenAI client initialized with model: {self.model}")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
                self._openai_enabled = False
        else:
            logger.info("OpenAI not configured - using fallback templates")

    @property
    def is_enabled(self) -> bool:
        """Check if OpenAI is available and configured"""
        return self._openai_enabled

    async def generate_response(
        self,
        review: dict,
        tone: str = "professional",
        guest_name: Optional[str] = None,
        hotel_name: str = "Glimmora"
    ) -> Dict[str, Any]:
        """
        Generate AI response for a review using OpenAI.

        Args:
            review: Dictionary containing review data (rating, comment, title, source, etc.)
            tone: Response tone - professional, friendly, apologetic, empathetic
            guest_name: Optional guest name for personalization
            hotel_name: Hotel name for branding

        Returns:
            Dictionary with response_text, confidence, and suggestions
        """
        if not self._openai_enabled:
            return await self._generate_fallback_response(review, tone, guest_name, hotel_name)

        try:
            rating = review.get("rating", review.get("overall_rating", 3))
            comment = review.get("comment", review.get("text", ""))
            title = review.get("title", "")
            source = review.get("source", "direct")
            sentiment = review.get("sentiment", "neutral")

            # Build context-aware prompt
            prompt = self._build_response_prompt(
                rating=rating,
                comment=comment,
                title=title,
                source=source,
                sentiment=sentiment,
                tone=tone,
                guest_name=guest_name,
                hotel_name=hotel_name
            )

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt_response(tone, hotel_name)
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )

            response_text = response.choices[0].message.content.strip()

            # Generate suggestions for improvement
            suggestions = await self._generate_response_suggestions(response_text, comment, tone)

            return {
                "response_text": response_text,
                "confidence": 0.92,
                "suggestions": suggestions,
                "tone_used": tone,
                "model": self.model,
                "generated_at": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"OpenAI response generation failed: {e}")
            return await self._generate_fallback_response(review, tone, guest_name, hotel_name)

    async def analyze_sentiment_deep(self, text: str) -> Dict[str, Any]:
        """
        Deep sentiment analysis with emotion detection using OpenAI.

        Args:
            text: Review text to analyze

        Returns:
            Dictionary with score, label, emotions, triggers, and confidence
        """
        if not self._openai_enabled:
            return self._analyze_sentiment_fallback(text)

        try:
            prompt = f"""Analyze the sentiment of this hotel review in detail:

"{text}"

Provide a JSON response with:
1. "score": A float from -1.0 (very negative) to 1.0 (very positive)
2. "label": One of "very_positive", "positive", "neutral", "negative", "very_negative"
3. "emotions": Object with emotion scores (0-1) for: happiness, satisfaction, frustration, anger, disappointment, surprise
4. "triggers": Array of specific aspects that triggered the sentiment (e.g., "slow check-in", "beautiful view")
5. "confidence": Float 0-1 indicating analysis confidence

Respond ONLY with valid JSON, no additional text."""

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a sentiment analysis expert for hospitality reviews. Always respond with valid JSON only."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=400
            )

            result_text = response.choices[0].message.content.strip()

            # Parse JSON response
            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            result = json.loads(result_text)

            return {
                "score": result.get("score", 0.0),
                "label": result.get("label", "neutral"),
                "emotions": result.get("emotions", {}),
                "triggers": result.get("triggers", []),
                "confidence": result.get("confidence", 0.85),
                "analysis_source": "openai",
                "model": self.model
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse OpenAI sentiment response: {e}")
            return self._analyze_sentiment_fallback(text)
        except Exception as e:
            logger.error(f"OpenAI sentiment analysis failed: {e}")
            return self._analyze_sentiment_fallback(text)

    async def detect_categories(
        self,
        review_text: str,
        categories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Detect which categories apply to a review using OpenAI.

        Args:
            review_text: The review text to analyze
            categories: List of available categories with id, name, and description

        Returns:
            List of detected categories with confidence and evidence
        """
        if not self._openai_enabled or not categories:
            return self._detect_categories_fallback(review_text, categories)

        try:
            # Build category list for prompt
            category_list = "\n".join([
                f"- {cat.get('name', cat.get('id'))}: {cat.get('description', 'No description')}"
                for cat in categories
            ])

            prompt = f"""Analyze this hotel review and identify which categories apply:

Review: "{review_text}"

Available Categories:
{category_list}

For each applicable category, provide:
1. "category_name": Name of the category
2. "confidence": Float 0-1 indicating how confident you are
3. "evidence": The specific text from the review that relates to this category

Respond with a JSON array of matching categories. Only include categories with confidence >= 0.5.
Respond ONLY with valid JSON array, no additional text."""

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at categorizing hotel reviews. Always respond with valid JSON array only."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            result_text = response.choices[0].message.content.strip()

            # Parse JSON response
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            detected = json.loads(result_text)

            # Map back to category IDs
            result = []
            for det in detected:
                cat_name = det.get("category_name", "")
                # Find matching category by name
                for cat in categories:
                    if cat.get("name", "").lower() == cat_name.lower():
                        result.append({
                            "category_id": cat.get("id"),
                            "category_name": cat_name,
                            "confidence": det.get("confidence", 0.5),
                            "evidence": det.get("evidence", "")
                        })
                        break

            return result

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse OpenAI category response: {e}")
            return self._detect_categories_fallback(review_text, categories)
        except Exception as e:
            logger.error(f"OpenAI category detection failed: {e}")
            return self._detect_categories_fallback(review_text, categories)

    async def generate_rca(self, trend_data: dict) -> Dict[str, Any]:
        """
        Generate Root Cause Analysis for a trend alert.

        Args:
            trend_data: Dictionary containing trend information (category, issue_count,
                       sample_reviews, time_period, severity, etc.)

        Returns:
            Dictionary with root_causes, contributing_factors, recommendations, confidence
        """
        if not self._openai_enabled:
            return self._generate_rca_fallback(trend_data)

        try:
            category = trend_data.get("category", "General")
            issue_count = trend_data.get("issue_count", 0)
            severity = trend_data.get("severity", "medium")
            sample_reviews = trend_data.get("sample_reviews", [])
            time_period = trend_data.get("time_period", "last 14 days")

            # Build sample reviews context
            reviews_context = "\n".join([
                f"- \"{r.get('comment', r)[:200]}...\"" if len(str(r)) > 200 else f"- \"{r.get('comment', r)}\""
                for r in sample_reviews[:5]
            ]) if sample_reviews else "No sample reviews provided"

            prompt = f"""Perform a Root Cause Analysis for this hotel trend alert:

Category: {category}
Issue Count: {issue_count} complaints in {time_period}
Severity: {severity}

Sample Guest Complaints:
{reviews_context}

Provide a detailed analysis with:
1. "root_causes": Array of primary causes (2-4 causes, most important first)
2. "contributing_factors": Array of secondary factors that may worsen the issue
3. "recommendations": Array of actionable recommendations to address the issue
4. "confidence": Float 0-1 indicating analysis confidence

Each cause/factor/recommendation should be a concise, actionable statement.
Respond ONLY with valid JSON, no additional text."""

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a hospitality operations expert performing root cause analysis. Provide practical, actionable insights. Always respond with valid JSON only."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=600
            )

            result_text = response.choices[0].message.content.strip()

            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            result = json.loads(result_text)

            return {
                "root_causes": result.get("root_causes", []),
                "contributing_factors": result.get("contributing_factors", []),
                "recommendations": result.get("recommendations", []),
                "confidence": result.get("confidence", 0.8),
                "analysis_source": "openai",
                "model": self.model,
                "generated_at": datetime.utcnow().isoformat()
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse OpenAI RCA response: {e}")
            return self._generate_rca_fallback(trend_data)
        except Exception as e:
            logger.error(f"OpenAI RCA generation failed: {e}")
            return self._generate_rca_fallback(trend_data)

    async def suggest_improvements(
        self,
        draft_text: str,
        review_text: str
    ) -> List[Dict[str, Any]]:
        """
        Suggest improvements for a response draft.

        Args:
            draft_text: The current draft response
            review_text: The original review being responded to

        Returns:
            List of suggestions with suggestion, reason, and improved_text
        """
        if not self._openai_enabled:
            return self._suggest_improvements_fallback(draft_text, review_text)

        try:
            prompt = f"""Review this hotel response and suggest improvements:

Original Guest Review:
"{review_text}"

Current Draft Response:
"{draft_text}"

Analyze the response and provide 2-4 specific improvements. For each:
1. "suggestion": Brief description of what to improve
2. "reason": Why this improvement matters
3. "improved_text": The suggested revision for that part

Focus on:
- Personalization and empathy
- Addressing specific concerns mentioned
- Professional tone and brand alignment
- Call to action or resolution offering

Respond with a JSON array of suggestions.
Respond ONLY with valid JSON array, no additional text."""

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a hospitality communication expert who helps improve guest response quality. Always respond with valid JSON array only."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=600
            )

            result_text = response.choices[0].message.content.strip()

            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            suggestions = json.loads(result_text)

            return suggestions if isinstance(suggestions, list) else []

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse OpenAI suggestions response: {e}")
            return self._suggest_improvements_fallback(draft_text, review_text)
        except Exception as e:
            logger.error(f"OpenAI suggestion generation failed: {e}")
            return self._suggest_improvements_fallback(draft_text, review_text)

    # ==================== PRIVATE HELPER METHODS ====================

    def _get_system_prompt_response(self, tone: str, hotel_name: str) -> str:
        """Get system prompt for response generation based on tone"""
        tone_instructions = {
            "professional": "Maintain a professional, courteous tone. Be formal but warm.",
            "friendly": "Use a warm, friendly tone. Be conversational and approachable.",
            "apologetic": "Express genuine apology and concern. Show empathy and commitment to improvement.",
            "empathetic": "Show deep understanding of the guest's experience. Validate their feelings."
        }

        instruction = tone_instructions.get(tone, tone_instructions["professional"])

        return f"""You are a guest relations specialist at {hotel_name}.
Your role is to craft thoughtful, personalized responses to guest reviews.

Guidelines:
- {instruction}
- Always thank the guest for their feedback
- Address specific points mentioned in the review
- For negative reviews, apologize sincerely and offer resolution
- For positive reviews, express genuine gratitude
- Keep responses concise (150-250 words)
- Include a call to action when appropriate (return visit, direct contact)
- Never be defensive or dismissive
- Use the guest's name if provided

Do not include any placeholder text like [Hotel Name] or [Guest Name] - write the actual response."""

    def _build_response_prompt(
        self,
        rating: float,
        comment: str,
        title: str,
        source: str,
        sentiment: str,
        tone: str,
        guest_name: Optional[str],
        hotel_name: str
    ) -> str:
        """Build the prompt for response generation"""
        guest_greeting = f"Guest Name: {guest_name}" if guest_name else "Guest Name: Not provided (use 'Dear Guest')"

        return f"""Generate a response for this review:

Rating: {rating}/5 stars
Review Source: {source}
Title: {title or 'No title'}
Sentiment: {sentiment}
{guest_greeting}
Hotel: {hotel_name}
Requested Tone: {tone}

Review Text:
"{comment}"

Write a complete, ready-to-publish response. Do not use any placeholders."""

    async def _generate_response_suggestions(
        self,
        response_text: str,
        review_text: str,
        tone: str
    ) -> List[str]:
        """Generate quick suggestions for the response"""
        suggestions = []

        # Check response length
        word_count = len(response_text.split())
        if word_count < 50:
            suggestions.append("Consider adding more detail to personalize the response")
        elif word_count > 300:
            suggestions.append("Response may be too long - consider condensing")

        # Check for personalization indicators
        if "dear guest" in response_text.lower() and review_text:
            suggestions.append("Consider using the guest's name if available for more personalization")

        # Check for call to action
        if not any(phrase in response_text.lower() for phrase in ["look forward", "hope to see", "please contact", "reach out"]):
            suggestions.append("Consider adding a call to action or invitation to return")

        return suggestions

    # ==================== FALLBACK METHODS ====================

    async def _generate_fallback_response(
        self,
        review: dict,
        tone: str,
        guest_name: Optional[str],
        hotel_name: str
    ) -> Dict[str, Any]:
        """Generate template-based response when OpenAI is unavailable"""
        rating = review.get("rating", review.get("overall_rating", 3))
        comment = review.get("comment", review.get("text", ""))

        greeting = f"Dear {guest_name}" if guest_name else "Dear Guest"
        sign_off = f"The {hotel_name} Team"

        if rating >= 4:
            response_text = f"""{greeting},

Thank you so much for taking the time to share your wonderful feedback! We are thrilled to hear that you enjoyed your stay with us at {hotel_name}.

Your kind words mean a lot to our team, and we are committed to maintaining the high standards that made your experience memorable. We look forward to welcoming you back soon!

Warm regards,
{sign_off}"""
        elif rating >= 3:
            response_text = f"""{greeting},

Thank you for sharing your feedback about your recent stay at {hotel_name}. We appreciate you taking the time to let us know about your experience.

We are always looking for ways to improve, and your comments are valuable to us. We would love the opportunity to exceed your expectations on your next visit.

Best regards,
{sign_off}"""
        else:
            response_text = f"""{greeting},

Thank you for bringing your concerns to our attention. We sincerely apologize that your experience at {hotel_name} did not meet your expectations.

We take all feedback seriously and are actively working to address the issues you've raised. We would appreciate the opportunity to make things right and hope you'll give us another chance.

Please feel free to reach out to us directly at your convenience so we can discuss this further.

With sincere apologies,
{sign_off}"""

        return {
            "response_text": response_text,
            "confidence": 0.70,
            "suggestions": [
                "Review generated using template - consider customizing for specific guest concerns",
                "Add specific references to points mentioned in the review"
            ],
            "tone_used": tone,
            "model": "template_fallback",
            "generated_at": datetime.utcnow().isoformat()
        }

    def _analyze_sentiment_fallback(self, text: str) -> Dict[str, Any]:
        """Fallback sentiment analysis using keyword matching"""
        from app.services.crm_ai.sentiment_analyzer import SentimentAnalyzer

        analyzer = SentimentAnalyzer()
        result = analyzer.analyze(text, source="review")

        # Map to expected format
        emotions = {
            "happiness": 0.0,
            "satisfaction": 0.0,
            "frustration": 0.0,
            "anger": 0.0,
            "disappointment": 0.0,
            "surprise": 0.0
        }

        # Map primary emotion to emotion scores
        primary = result.get("primary_emotion", "neutral")
        emotion_mapping = {
            "happy": ("happiness", 0.8),
            "satisfied": ("satisfaction", 0.8),
            "frustrated": ("frustration", 0.8),
            "angry": ("anger", 0.8),
            "disappointed": ("disappointment", 0.8)
        }

        if primary in emotion_mapping:
            emotion_key, score = emotion_mapping[primary]
            emotions[emotion_key] = score

        return {
            "score": result.get("sentiment_score", 0.0),
            "label": result.get("sentiment_label", "neutral"),
            "emotions": emotions,
            "triggers": [t.get("keyword", t.get("aspect", "")) for t in result.get("triggers", [])],
            "confidence": result.get("confidence", 0.6),
            "analysis_source": "rule_based",
            "model": "sentiment_analyzer_v1"
        }

    def _detect_categories_fallback(
        self,
        review_text: str,
        categories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Fallback category detection using keyword matching"""
        text_lower = review_text.lower()

        # Category keyword mapping
        category_keywords = {
            "room": ["room", "suite", "bed", "bathroom", "shower", "view", "balcony", "space", "bedroom"],
            "service": ["service", "staff", "reception", "concierge", "housekeeping", "response", "helpful", "rude"],
            "food": ["food", "breakfast", "dinner", "restaurant", "dining", "meal", "coffee", "menu"],
            "cleanliness": ["clean", "dirty", "spotless", "tidy", "hygiene", "sanitary", "dust", "stain"],
            "location": ["location", "area", "neighborhood", "walking", "distance", "beach", "city", "transport"],
            "amenities": ["pool", "spa", "gym", "wifi", "parking", "facilities", "amenities", "internet"],
            "value": ["price", "value", "worth", "expensive", "cheap", "cost", "money", "rate"],
            "check-in": ["check-in", "checkin", "arrival", "welcome", "front desk", "lobby"],
            "noise": ["noise", "noisy", "loud", "quiet", "sound", "neighbor"]
        }

        detected = []
        for cat in categories:
            cat_name = cat.get("name", "").lower()
            cat_id = cat.get("id")

            # Check if category keywords appear in text
            keywords = category_keywords.get(cat_name, [cat_name])
            matches = [kw for kw in keywords if kw in text_lower]

            if matches:
                confidence = min(0.9, 0.5 + len(matches) * 0.1)
                detected.append({
                    "category_id": cat_id,
                    "category_name": cat.get("name", cat_name),
                    "confidence": confidence,
                    "evidence": f"Keywords found: {', '.join(matches)}"
                })

        return sorted(detected, key=lambda x: x["confidence"], reverse=True)

    def _generate_rca_fallback(self, trend_data: dict) -> Dict[str, Any]:
        """Fallback RCA generation using templates"""
        category = trend_data.get("category", "General").lower()
        issue_count = trend_data.get("issue_count", 0)

        # Template-based RCA by category
        rca_templates = {
            "service": {
                "root_causes": [
                    "Insufficient staff training on guest service standards",
                    "High staff turnover affecting service consistency"
                ],
                "contributing_factors": [
                    "Peak season staffing challenges",
                    "Communication gaps between departments"
                ],
                "recommendations": [
                    "Implement refresher training for all guest-facing staff",
                    "Review and update service protocols",
                    "Establish daily briefings for shift handovers"
                ]
            },
            "cleanliness": {
                "root_causes": [
                    "Housekeeping team understaffed during high occupancy",
                    "Inconsistent room inspection procedures"
                ],
                "contributing_factors": [
                    "Equipment maintenance issues",
                    "Time pressure during quick turnovers"
                ],
                "recommendations": [
                    "Increase housekeeping staff during peak periods",
                    "Implement double-check inspection system",
                    "Upgrade cleaning equipment and supplies"
                ]
            },
            "room": {
                "root_causes": [
                    "Aging room fixtures and amenities",
                    "Maintenance backlog affecting room quality"
                ],
                "contributing_factors": [
                    "Budget constraints for renovations",
                    "Delayed preventive maintenance"
                ],
                "recommendations": [
                    "Prioritize high-impact room upgrades",
                    "Accelerate preventive maintenance schedule",
                    "Create room condition monitoring checklist"
                ]
            },
            "default": {
                "root_causes": [
                    "Process or system inconsistencies",
                    "Staff awareness gaps on guest expectations"
                ],
                "contributing_factors": [
                    "Recent operational changes",
                    "Communication breakdowns"
                ],
                "recommendations": [
                    "Conduct detailed analysis of specific complaints",
                    "Implement guest feedback monitoring system",
                    "Schedule team meeting to address concerns"
                ]
            }
        }

        template = rca_templates.get(category, rca_templates["default"])

        return {
            "root_causes": template["root_causes"],
            "contributing_factors": template["contributing_factors"],
            "recommendations": template["recommendations"],
            "confidence": 0.6,
            "analysis_source": "template",
            "model": "rca_template_v1",
            "generated_at": datetime.utcnow().isoformat()
        }

    def _suggest_improvements_fallback(
        self,
        draft_text: str,
        review_text: str
    ) -> List[Dict[str, Any]]:
        """Fallback improvement suggestions"""
        suggestions = []
        draft_lower = draft_text.lower()
        review_lower = review_text.lower()

        # Check for personalization
        if "dear guest" in draft_lower:
            suggestions.append({
                "suggestion": "Personalize the greeting",
                "reason": "Using the guest's name creates a more personal connection",
                "improved_text": "Use the guest's name if available instead of 'Dear Guest'"
            })

        # Check for specific issue acknowledgment
        if any(word in review_lower for word in ["dirty", "unclean", "stain"]):
            if "cleanliness" not in draft_lower and "clean" not in draft_lower:
                suggestions.append({
                    "suggestion": "Acknowledge specific cleanliness concerns",
                    "reason": "Guests want to know their specific issues are heard",
                    "improved_text": "Add: 'We are addressing the cleanliness issues you mentioned with our housekeeping team.'"
                })

        # Check for resolution offer
        if not any(phrase in draft_lower for phrase in ["compensation", "discount", "complimentary", "make it up"]):
            word_count = len(draft_text.split())
            if word_count > 50:  # Only suggest for substantive responses
                suggestions.append({
                    "suggestion": "Consider offering a gesture of goodwill",
                    "reason": "A concrete offer shows commitment to guest satisfaction",
                    "improved_text": "Add: 'We would like to offer you a complimentary upgrade on your next stay.'"
                })

        # Check for call to action
        if not any(phrase in draft_lower for phrase in ["please contact", "reach out", "call us", "email"]):
            suggestions.append({
                "suggestion": "Add contact information",
                "reason": "Makes it easy for guests to follow up directly",
                "improved_text": "Add: 'Please feel free to contact our guest services team directly at...'"
            })

        return suggestions[:4]  # Return max 4 suggestions
