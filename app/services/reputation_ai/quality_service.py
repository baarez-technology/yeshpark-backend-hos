"""
Response Quality Service
Scores and improves the quality of response drafts.
"""
import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reputation import ResponseDraft, ReviewResponse
from app.models.reviews import Review

logger = logging.getLogger(__name__)


class ResponseQualityService:
    """Score and improve response quality"""

    # Quality scoring weights
    QUALITY_WEIGHTS = {
        "personalization": 0.25,
        "empathy": 0.25,
        "resolution": 0.25,
        "brand_alignment": 0.25
    }

    # Personalization indicators
    PERSONALIZATION_PATTERNS = {
        "name_usage": r"\b(dear\s+\w+|hi\s+\w+|hello\s+\w+)\b",
        "specific_reference": r"\b(you mentioned|your experience with|your comment about|you noted)\b",
        "detail_acknowledgment": r"\b(we noticed|we see that|we understand you|based on your)\b"
    }

    # Empathy indicators
    EMPATHY_PATTERNS = {
        "apologetic": r"\b(sorry|apologize|regret|apologies|sincerely sorry)\b",
        "understanding": r"\b(understand|appreciate|recognize|acknowledge)\b",
        "validation": r"\b(valid concern|legitimate|rightfully|justified|can imagine)\b",
        "care": r"\b(important to us|value your|matter to us|care about|concern us)\b"
    }

    # Resolution indicators
    RESOLUTION_PATTERNS = {
        "action": r"\b(we will|we have|we are implementing|steps to|address this)\b",
        "contact": r"\b(contact us|reach out|call|email|speak with)\b",
        "compensation": r"\b(complimentary|discount|upgrade|compensation|offer|refund)\b",
        "follow_up": r"\b(follow up|get back to you|contact you|reach out to)\b"
    }

    # Brand alignment indicators
    BRAND_KEYWORDS = {
        "professional_tone": ["sincerely", "regards", "respectfully", "cordially"],
        "hospitality_language": ["guest", "stay", "experience", "hospitality", "service", "welcome"],
        "positive_closing": ["look forward", "hope to see", "pleasure", "honor", "welcoming you"]
    }

    # Red flags to penalize
    RED_FLAGS = {
        "defensive": r"\b(but actually|however you|you should have|it's not our|wasn't our fault)\b",
        "dismissive": r"\b(unlikely|impossible|never happened|you must be mistaken)\b",
        "generic_only": r"^(thank you for your feedback\.?\s*we appreciate it\.?\s*)$",
        "placeholder": r"\[.+?\]"  # Unfilled placeholders like [Guest Name]
    }

    def __init__(
        self,
        db: AsyncSession,
        openai_service: Optional["ReputationOpenAIService"] = None
    ):
        """
        Initialize ResponseQualityService.

        Args:
            db: Database session
            openai_service: Optional OpenAI service for AI-powered suggestions
        """
        self.db = db
        self.openai_service = openai_service

    async def score_response(
        self,
        response_text: str,
        review_text: str,
        review_rating: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Score a response's quality.

        Args:
            response_text: The response text to score
            review_text: The original review being responded to
            review_rating: Optional rating from the review

        Returns:
            Dictionary with total_score and breakdown by dimension
        """
        if not response_text:
            return self._empty_score()

        response_lower = response_text.lower()
        review_lower = review_text.lower() if review_text else ""

        # Score each dimension
        personalization_score = self._score_personalization(response_lower, review_lower)
        empathy_score = self._score_empathy(response_lower, review_rating)
        resolution_score = self._score_resolution(response_lower, review_rating)
        brand_score = self._score_brand_alignment(response_text)

        # Apply red flag penalties
        penalty = self._calculate_penalties(response_text)

        # Calculate weighted total
        breakdown = {
            "personalization": personalization_score,
            "empathy": empathy_score,
            "resolution": resolution_score,
            "brand_alignment": brand_score
        }

        total_score = sum(
            score * self.QUALITY_WEIGHTS[dim]
            for dim, score in breakdown.items()
        )

        # Apply penalty
        total_score = max(0, total_score - penalty)

        # Normalize to 0-100
        total_score = round(total_score * 100, 1)
        breakdown = {k: round(v * 100, 1) for k, v in breakdown.items()}

        return {
            "total_score": total_score,
            "breakdown": breakdown,
            "penalty_applied": round(penalty * 100, 1),
            "quality_level": self._get_quality_level(total_score),
            "scored_at": datetime.utcnow().isoformat()
        }

    async def get_quality_breakdown(self, response_id: int) -> Dict[str, Any]:
        """
        Get detailed quality breakdown for a published response.

        Args:
            response_id: ID of the ReviewResponse

        Returns:
            Dictionary with detailed breakdown and suggestions
        """
        # Get the response
        stmt = select(ReviewResponse).where(ReviewResponse.id == response_id)
        result = await self.db.execute(stmt)
        response = result.scalar_one_or_none()

        if not response:
            logger.warning(f"Response {response_id} not found")
            return {"error": "Response not found"}

        # Get the original review
        review_stmt = select(Review).where(Review.id == response.review_id)
        review_result = await self.db.execute(review_stmt)
        review = review_result.scalar_one_or_none()

        review_text = review.comment if review else ""
        review_rating = review.overall_rating if review else None

        # Score the response
        score_result = await self.score_response(
            response.response_text,
            review_text,
            review_rating
        )

        # Get suggestions
        suggestions = await self.suggest_improvements(response.response_text, review_text)

        return {
            "response_id": response_id,
            "review_id": response.review_id,
            **score_result,
            "suggestions": suggestions,
            "response_length": len(response.response_text),
            "word_count": len(response.response_text.split())
        }

    async def suggest_improvements(
        self,
        response_text: str,
        review_text: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Suggest specific improvements for a response.

        Args:
            response_text: The response to improve
            review_text: The original review

        Returns:
            List of suggestions with reason and improved_text
        """
        suggestions = []

        # Try AI-powered suggestions first
        if self.openai_service and self.openai_service.is_enabled:
            try:
                ai_suggestions = await self.openai_service.suggest_improvements(
                    response_text,
                    review_text
                )
                if ai_suggestions:
                    return ai_suggestions
            except Exception as e:
                logger.warning(f"AI suggestion generation failed: {e}")

        # Fallback to rule-based suggestions
        response_lower = response_text.lower()
        review_lower = review_text.lower() if review_text else ""

        # Check personalization
        if "dear guest" in response_lower and not any(
            re.search(pat, response_lower) for pat in self.PERSONALIZATION_PATTERNS.values()
        ):
            suggestions.append({
                "suggestion": "Add more personalization",
                "reason": "Using generic greeting without specific references reduces engagement",
                "improved_text": "Reference specific details from the guest's review to show you read and understood their feedback"
            })

        # Check empathy for negative reviews
        if self._detect_negative_sentiment(review_lower):
            has_empathy = any(
                re.search(pat, response_lower)
                for pat in self.EMPATHY_PATTERNS.values()
            )
            if not has_empathy:
                suggestions.append({
                    "suggestion": "Express empathy",
                    "reason": "Negative reviews need acknowledgment of the guest's feelings",
                    "improved_text": "Add phrases like 'We sincerely apologize for the inconvenience' or 'We understand how disappointing this must have been'"
                })

        # Check resolution offering
        has_resolution = any(
            re.search(pat, response_lower)
            for pat in self.RESOLUTION_PATTERNS.values()
        )
        if not has_resolution and len(response_text.split()) > 30:
            suggestions.append({
                "suggestion": "Include a resolution or call to action",
                "reason": "Responses should guide the guest toward a positive next step",
                "improved_text": "Add: 'Please contact our guest services team at [email/phone] so we can make this right' or 'We would be honored to welcome you back and provide a complimentary upgrade'"
            })

        # Check response length
        word_count = len(response_text.split())
        if word_count < 40:
            suggestions.append({
                "suggestion": "Expand the response",
                "reason": "Short responses can seem dismissive, especially for detailed reviews",
                "improved_text": "Add specific acknowledgments of the points raised in the review"
            })
        elif word_count > 350:
            suggestions.append({
                "suggestion": "Consider condensing",
                "reason": "Very long responses may lose the reader's attention",
                "improved_text": "Focus on the most important points: acknowledgment, empathy, and resolution"
            })

        # Check for red flags
        for flag_name, pattern in self.RED_FLAGS.items():
            if re.search(pattern, response_lower, re.IGNORECASE):
                if flag_name == "defensive":
                    suggestions.append({
                        "suggestion": "Remove defensive language",
                        "reason": "Defensive tone can escalate conflict and damage brand image",
                        "improved_text": "Replace defensive phrases with acknowledgment and commitment to improvement"
                    })
                elif flag_name == "placeholder":
                    suggestions.append({
                        "suggestion": "Fill in placeholders",
                        "reason": "Unfilled placeholders look unprofessional",
                        "improved_text": "Replace all [bracketed] placeholders with actual content"
                    })

        # Limit to top suggestions
        return suggestions[:5]

    async def batch_score_responses(
        self,
        response_ids: List[int]
    ) -> List[Dict[str, Any]]:
        """
        Score multiple responses in batch.

        Args:
            response_ids: List of response IDs to score

        Returns:
            List of score results
        """
        results = []

        for response_id in response_ids:
            try:
                result = await self.get_quality_breakdown(response_id)
                results.append(result)
            except Exception as e:
                logger.error(f"Error scoring response {response_id}: {e}")
                results.append({
                    "response_id": response_id,
                    "error": str(e)
                })

        return results

    async def update_response_quality_score(
        self,
        response_id: int
    ) -> Optional[ReviewResponse]:
        """
        Calculate and store quality score for a response.

        Args:
            response_id: ID of the ReviewResponse

        Returns:
            Updated ReviewResponse or None
        """
        breakdown = await self.get_quality_breakdown(response_id)

        if "error" in breakdown:
            return None

        # Update the response record
        stmt = select(ReviewResponse).where(ReviewResponse.id == response_id)
        result = await self.db.execute(stmt)
        response = result.scalar_one_or_none()

        if response:
            response.quality_score = breakdown.get("total_score")
            response.quality_breakdown = {
                "breakdown": breakdown.get("breakdown"),
                "quality_level": breakdown.get("quality_level"),
                "penalty_applied": breakdown.get("penalty_applied"),
                "scored_at": breakdown.get("scored_at")
            }

            await self.db.commit()
            await self.db.refresh(response)

        return response

    async def get_quality_trends(
        self,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get quality score trends over time.

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with trend data
        """
        stmt = select(ReviewResponse).where(
            ReviewResponse.quality_score.isnot(None)
        ).order_by(ReviewResponse.published_at.desc()).limit(100)

        result = await self.db.execute(stmt)
        responses = result.scalars().all()

        if not responses:
            return {
                "average_score": 0,
                "score_distribution": {},
                "trend": "insufficient_data"
            }

        scores = [r.quality_score for r in responses if r.quality_score]

        # Calculate distribution
        distribution = {
            "excellent": len([s for s in scores if s >= 85]),
            "good": len([s for s in scores if 70 <= s < 85]),
            "fair": len([s for s in scores if 50 <= s < 70]),
            "needs_improvement": len([s for s in scores if s < 50])
        }

        # Calculate trend
        if len(scores) >= 10:
            first_half = sum(scores[:len(scores)//2]) / (len(scores)//2)
            second_half = sum(scores[len(scores)//2:]) / (len(scores) - len(scores)//2)
            change = second_half - first_half

            if change > 5:
                trend = "improving"
            elif change < -5:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "score_distribution": distribution,
            "total_scored": len(scores),
            "trend": trend
        }

    # ==================== PRIVATE SCORING METHODS ====================

    def _score_personalization(
        self,
        response_lower: str,
        review_lower: str
    ) -> float:
        """Score personalization dimension"""
        score = 0.3  # Base score

        # Check for personalization patterns
        for pattern in self.PERSONALIZATION_PATTERNS.values():
            if re.search(pattern, response_lower):
                score += 0.2

        # Check if response references specific review content
        if review_lower:
            # Extract key nouns/topics from review
            review_words = set(re.findall(r'\b\w{4,}\b', review_lower))
            response_words = set(re.findall(r'\b\w{4,}\b', response_lower))

            # Common words indicate specific reference
            common = review_words & response_words
            common_meaningful = [w for w in common if w not in {
                "hotel", "room", "stay", "time", "very", "this", "that", "have", "been",
                "your", "thank", "feedback", "review", "guest", "experience"
            }]

            if len(common_meaningful) >= 2:
                score += 0.2

        return min(1.0, score)

    def _score_empathy(
        self,
        response_lower: str,
        review_rating: Optional[float]
    ) -> float:
        """Score empathy dimension"""
        score = 0.4  # Base score

        # Count empathy indicators
        empathy_count = sum(
            1 for pattern in self.EMPATHY_PATTERNS.values()
            if re.search(pattern, response_lower)
        )

        score += empathy_count * 0.15

        # Adjust based on review rating - negative reviews need more empathy
        if review_rating and review_rating <= 2:
            # Penalty if no empathy for negative review
            if empathy_count == 0:
                score -= 0.3
        elif review_rating and review_rating >= 4:
            # Empathy less critical for positive reviews
            score += 0.1

        return min(1.0, max(0.0, score))

    def _score_resolution(
        self,
        response_lower: str,
        review_rating: Optional[float]
    ) -> float:
        """Score resolution dimension"""
        score = 0.3  # Base score

        # Count resolution indicators
        resolution_count = sum(
            1 for pattern in self.RESOLUTION_PATTERNS.values()
            if re.search(pattern, response_lower)
        )

        score += resolution_count * 0.2

        # Contact information is particularly important
        if re.search(self.RESOLUTION_PATTERNS["contact"], response_lower):
            score += 0.1

        # Compensation mention for negative reviews
        if review_rating and review_rating <= 2:
            if re.search(self.RESOLUTION_PATTERNS["compensation"], response_lower):
                score += 0.15

        return min(1.0, score)

    def _score_brand_alignment(self, response_text: str) -> float:
        """Score brand alignment dimension"""
        score = 0.4  # Base score
        response_lower = response_text.lower()

        # Check professional tone
        if any(word in response_lower for word in self.BRAND_KEYWORDS["professional_tone"]):
            score += 0.15

        # Check hospitality language
        hospitality_count = sum(
            1 for word in self.BRAND_KEYWORDS["hospitality_language"]
            if word in response_lower
        )
        score += min(0.2, hospitality_count * 0.05)

        # Check positive closing
        if any(phrase in response_lower for phrase in self.BRAND_KEYWORDS["positive_closing"]):
            score += 0.15

        # Check proper formatting
        if response_text[0].isupper():  # Starts with capital
            score += 0.05
        if response_text.strip().endswith(('.', '!')):  # Proper ending
            score += 0.05

        return min(1.0, score)

    def _calculate_penalties(self, response_text: str) -> float:
        """Calculate penalty score for red flags"""
        penalty = 0.0

        for flag_name, pattern in self.RED_FLAGS.items():
            if re.search(pattern, response_text, re.IGNORECASE):
                if flag_name == "defensive":
                    penalty += 0.2
                elif flag_name == "dismissive":
                    penalty += 0.25
                elif flag_name == "generic_only":
                    penalty += 0.3
                elif flag_name == "placeholder":
                    penalty += 0.15

        return min(0.5, penalty)  # Cap penalty at 50%

    def _get_quality_level(self, score: float) -> str:
        """Convert score to quality level"""
        if score >= 85:
            return "excellent"
        elif score >= 70:
            return "good"
        elif score >= 50:
            return "fair"
        else:
            return "needs_improvement"

    def _detect_negative_sentiment(self, text: str) -> bool:
        """Detect if text has negative sentiment"""
        negative_indicators = [
            "terrible", "awful", "horrible", "worst", "disappointing",
            "disappointed", "bad", "poor", "rude", "dirty", "unacceptable",
            "never again", "waste", "problem", "issue", "complaint"
        ]
        return any(word in text for word in negative_indicators)

    def _empty_score(self) -> Dict[str, Any]:
        """Return empty score for invalid input"""
        return {
            "total_score": 0,
            "breakdown": {
                "personalization": 0,
                "empathy": 0,
                "resolution": 0,
                "brand_alignment": 0
            },
            "penalty_applied": 0,
            "quality_level": "needs_improvement",
            "scored_at": datetime.utcnow().isoformat()
        }
