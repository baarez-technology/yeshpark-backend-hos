"""
Rebooking Probability Model
Predicts the likelihood that a guest will book again within a specific timeframe
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import math


class RebookingModel:
    """Rebooking Probability Model - Rule-based prediction"""

    def __init__(self, model_version: str = "1.0.0"):
        self.model_version = model_version
        self.model_name = "rebooking_probability_v1"

    def predict(
        self,
        features: Dict[str, Any],
        timeframe_days: int = 90
    ) -> Dict[str, Any]:
        """Predict rebooking probability within timeframe"""
        rebooking_score = 50  # Base score
        factors = []

        # Recency factor (strong predictor)
        recency_days = features.get("recency_days", 999)
        if recency_days <= 30:
            recency_boost = 25
            factors.append({
                "factor": "Recent stay",
                "description": f"Stayed {recency_days} days ago",
                "impact": "positive",
                "contribution": recency_boost
            })
        elif recency_days <= 90:
            recency_boost = 15
            factors.append({
                "factor": "Recent activity",
                "description": f"Last stay was {recency_days} days ago",
                "impact": "positive",
                "contribution": recency_boost
            })
        elif recency_days <= 180:
            recency_boost = 0
        elif recency_days <= 365:
            recency_boost = -15
            factors.append({
                "factor": "Extended gap",
                "description": f"No visit in {recency_days} days",
                "impact": "negative",
                "contribution": recency_boost
            })
        else:
            recency_boost = -30
            factors.append({
                "factor": "Long absence",
                "description": f"No visit in over a year",
                "impact": "negative",
                "contribution": recency_boost
            })
        rebooking_score += recency_boost

        # Booking frequency factor
        total_bookings = features.get("total_bookings", 0)
        booking_frequency = features.get("booking_frequency", 0)

        if total_bookings >= 5:
            frequency_boost = 20
            factors.append({
                "factor": "Loyal guest",
                "description": f"{total_bookings} previous bookings",
                "impact": "positive",
                "contribution": frequency_boost
            })
        elif total_bookings >= 3:
            frequency_boost = 12
        elif total_bookings >= 2:
            frequency_boost = 5
        elif total_bookings == 1:
            frequency_boost = -5
            factors.append({
                "factor": "Single booking",
                "description": "Only one previous stay",
                "impact": "neutral",
                "contribution": frequency_boost
            })
        else:
            frequency_boost = -20
        rebooking_score += frequency_boost

        # Sentiment factor
        avg_sentiment = features.get("avg_sentiment_90d", 0)
        if avg_sentiment > 0.5:
            sentiment_boost = 15
            factors.append({
                "factor": "Positive sentiment",
                "description": "Guest expressed satisfaction",
                "impact": "positive",
                "contribution": sentiment_boost
            })
        elif avg_sentiment > 0.2:
            sentiment_boost = 8
        elif avg_sentiment < -0.3:
            sentiment_boost = -20
            factors.append({
                "factor": "Negative sentiment",
                "description": "Recent dissatisfaction detected",
                "impact": "negative",
                "contribution": sentiment_boost
            })
        elif avg_sentiment < 0:
            sentiment_boost = -8
        else:
            sentiment_boost = 0
        rebooking_score += sentiment_boost

        # Cancellation behavior
        cancellation_rate = features.get("cancellation_rate", 0)
        if cancellation_rate > 0.5:
            cancel_penalty = -15
            factors.append({
                "factor": "High cancellation rate",
                "description": f"{cancellation_rate:.0%} of bookings cancelled",
                "impact": "negative",
                "contribution": cancel_penalty
            })
        elif cancellation_rate > 0.3:
            cancel_penalty = -8
        else:
            cancel_penalty = 0
        rebooking_score += cancel_penalty

        # Loyalty factor
        vip_status = features.get("vip_status", False)
        loyalty_tier = features.get("loyalty_tier", "member")

        if vip_status:
            loyalty_boost = 15
            factors.append({
                "factor": "VIP status",
                "description": "High-value guest status",
                "impact": "positive",
                "contribution": loyalty_boost
            })
        elif loyalty_tier == "platinum":
            loyalty_boost = 12
        elif loyalty_tier == "gold":
            loyalty_boost = 8
        elif loyalty_tier == "silver":
            loyalty_boost = 4
        else:
            loyalty_boost = 0
        rebooking_score += loyalty_boost

        # Engagement factor
        recent_engagements = features.get("recent_engagements_90d", 0)
        if recent_engagements >= 3:
            engagement_boost = 10
            factors.append({
                "factor": "Active engagement",
                "description": f"{recent_engagements} recent interactions",
                "impact": "positive",
                "contribution": engagement_boost
            })
        elif recent_engagements >= 1:
            engagement_boost = 5
        else:
            engagement_boost = 0
        rebooking_score += engagement_boost

        # Clamp to 0-100
        rebooking_probability = max(0, min(100, rebooking_score))

        # Get likelihood label
        likelihood = self._get_likelihood_label(rebooking_probability)

        # Sort factors by absolute contribution
        factors.sort(key=lambda x: abs(x.get("contribution", 0)), reverse=True)

        # Calculate optimal contact timing
        optimal_timing = self._calculate_optimal_timing(features, recency_days)

        return {
            "rebooking_probability": round(rebooking_probability, 1),
            "probability_label": likelihood,
            "timeframe_days": timeframe_days,
            "factors": factors[:5],  # Top 5 factors
            "optimal_contact": optimal_timing,
            "recommended_offers": self._get_recommended_offers(features, likelihood),
            "explanation": {
                "summary": f"{likelihood} likelihood ({rebooking_probability:.0f}%) of rebooking within {timeframe_days} days",
                "positive_factors": [f["description"] for f in factors if f["impact"] == "positive"][:2],
                "negative_factors": [f["description"] for f in factors if f["impact"] == "negative"][:2],
            },
            "model_version": self.model_version,
        }

    def _get_likelihood_label(self, probability: float) -> str:
        """Get human-readable likelihood label"""
        if probability >= 80:
            return "Very High"
        elif probability >= 60:
            return "High"
        elif probability >= 40:
            return "Moderate"
        elif probability >= 20:
            return "Low"
        else:
            return "Very Low"

    def _calculate_optimal_timing(
        self,
        features: Dict[str, Any],
        recency_days: int
    ) -> Dict[str, Any]:
        """Calculate optimal timing for contact"""
        # Estimate typical booking interval
        total_bookings = features.get("total_bookings", 0)
        days_since_registration = features.get("days_since_registration", 365)

        if total_bookings >= 2 and days_since_registration > 0:
            avg_interval = days_since_registration / total_bookings
        else:
            avg_interval = 120  # Default assumption

        # Calculate days until optimal contact
        if recency_days < avg_interval * 0.5:
            # Too early - wait
            days_until_contact = int(avg_interval * 0.7 - recency_days)
            timing_window = "pre_decision"
        elif recency_days < avg_interval:
            # Good window - contact now
            days_until_contact = 0
            timing_window = "optimal"
        else:
            # Overdue - contact immediately
            days_until_contact = 0
            timing_window = "urgent"

        return {
            "days_until_optimal_contact": max(0, days_until_contact),
            "timing_window": timing_window,
            "estimated_booking_interval": round(avg_interval),
            "recommendation": self._get_timing_recommendation(timing_window, days_until_contact)
        }

    def _get_timing_recommendation(self, window: str, days: int) -> str:
        """Get timing recommendation text"""
        if window == "urgent":
            return "Contact immediately - guest may be booking elsewhere"
        elif window == "optimal":
            return "Contact now - guest likely considering next trip"
        elif days <= 7:
            return "Schedule contact within the next week"
        elif days <= 30:
            return f"Schedule contact in {days} days"
        else:
            return f"Add to nurture sequence, optimal contact in {days} days"

    def _get_recommended_offers(
        self,
        features: Dict[str, Any],
        likelihood: str
    ) -> List[Dict[str, Any]]:
        """Get recommended offers based on guest profile"""
        offers = []

        total_spent = features.get("total_spent", 0)
        total_bookings = features.get("total_bookings", 0)
        avg_booking_value = features.get("avg_booking_value", 0)
        loyalty_tier = features.get("loyalty_tier", "member")

        # High value guest offers
        if total_spent >= 5000 or avg_booking_value >= 500:
            offers.append({
                "type": "exclusive_access",
                "title": "Early Access to Premium Dates",
                "description": "Exclusive booking window for peak dates",
                "priority": 1
            })
            offers.append({
                "type": "upgrade",
                "title": "Complimentary Suite Upgrade",
                "description": "Free upgrade on next booking",
                "priority": 2
            })

        # Moderate value / win-back offers
        elif likelihood in ["Low", "Very Low"]:
            offers.append({
                "type": "discount",
                "title": "Welcome Back Special",
                "description": "15% off next stay",
                "priority": 1
            })
            offers.append({
                "type": "value_add",
                "title": "Free Breakfast Package",
                "description": "Complimentary breakfast for 2",
                "priority": 2
            })

        # Regular guests
        else:
            offers.append({
                "type": "loyalty",
                "title": "Double Points Promotion",
                "description": "Earn 2x loyalty points on next stay",
                "priority": 1
            })
            offers.append({
                "type": "package",
                "title": "Stay & Dine Package",
                "description": "Room + dining credit",
                "priority": 2
            })

        # Tier-specific offers
        if loyalty_tier == "platinum":
            offers.insert(0, {
                "type": "vip",
                "title": "Platinum Concierge Service",
                "description": "Personal concierge for your next visit",
                "priority": 0
            })

        return offers[:3]
