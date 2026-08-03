"""
Churn Prediction Model
Predicts probability that a guest won't return (0-100% churn risk)
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta
import math


class ChurnPredictionModel:
    """Churn Prediction Model - Rule-based with risk factors"""

    def __init__(self, model_version: str = "1.0.0"):
        self.model_version = model_version
        self.model_name = "churn_prediction_v1"
        self.churn_threshold = 70  # Alert threshold

    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Predict churn probability with risk factors"""
        churn_factors = []
        churn_score = 0

        # Recency factor (biggest churn indicator)
        recency_days = features.get("recency_days", 999)
        if recency_days > 365:
            recency_risk = 40
            churn_factors.append({
                "factor": "Long absence",
                "description": f"No visit in {recency_days} days",
                "risk_contribution": recency_risk,
                "category": "recency"
            })
        elif recency_days > 180:
            recency_risk = 25
            churn_factors.append({
                "factor": "Extended gap",
                "description": f"Last visit was {recency_days} days ago",
                "risk_contribution": recency_risk,
                "category": "recency"
            })
        elif recency_days > 90:
            recency_risk = 10
        else:
            recency_risk = 0
        churn_score += recency_risk

        # Booking frequency factor
        booking_frequency = features.get("booking_frequency", 0)
        total_bookings = features.get("total_bookings", 0)
        if total_bookings == 1 and recency_days > 90:
            frequency_risk = 20
            churn_factors.append({
                "factor": "Single booking guest",
                "description": "Only one booking and no return",
                "risk_contribution": frequency_risk,
                "category": "frequency"
            })
        elif booking_frequency < 0.5 and total_bookings > 0:
            frequency_risk = 10
        else:
            frequency_risk = 0
        churn_score += frequency_risk

        # Cancellation factor
        cancellation_rate = features.get("cancellation_rate", 0)
        if cancellation_rate > 0.5:
            cancel_risk = 20
            churn_factors.append({
                "factor": "High cancellation rate",
                "description": f"{cancellation_rate:.0%} of bookings cancelled",
                "risk_contribution": cancel_risk,
                "category": "behavior"
            })
        elif cancellation_rate > 0.3:
            cancel_risk = 10
        else:
            cancel_risk = 0
        churn_score += cancel_risk

        # Sentiment factor
        avg_sentiment = features.get("avg_sentiment_90d", 0)
        if avg_sentiment < -0.5:
            sentiment_risk = 20
            churn_factors.append({
                "factor": "Negative sentiment",
                "description": "Recent interactions show dissatisfaction",
                "risk_contribution": sentiment_risk,
                "category": "sentiment"
            })
        elif avg_sentiment < -0.2:
            sentiment_risk = 10
        elif avg_sentiment > 0.3:
            sentiment_risk = -10  # Positive sentiment reduces churn
        else:
            sentiment_risk = 0
        churn_score += sentiment_risk

        # Engagement factor
        recent_engagements = features.get("recent_engagements_90d", 0)
        if recent_engagements == 0 and recency_days > 60:
            engagement_risk = 15
            churn_factors.append({
                "factor": "No recent engagement",
                "description": "No interactions in last 90 days",
                "risk_contribution": engagement_risk,
                "category": "engagement"
            })
        else:
            engagement_risk = 0
        churn_score += engagement_risk

        # Loyalty factor (reduces churn risk)
        vip_status = features.get("vip_status", False)
        loyalty_tier = features.get("loyalty_tier", "member")
        loyalty_reduction = 0
        if vip_status:
            loyalty_reduction = 15
        elif loyalty_tier == "platinum":
            loyalty_reduction = 12
        elif loyalty_tier == "gold":
            loyalty_reduction = 8
        elif loyalty_tier == "silver":
            loyalty_reduction = 4
        churn_score -= loyalty_reduction

        # High value guest factor (reduces churn risk)
        total_spent = features.get("total_spent", 0)
        if total_spent >= 10000:
            churn_score -= 10
        elif total_spent >= 5000:
            churn_score -= 5

        # Clamp to 0-100
        churn_probability = max(0, min(100, churn_score))

        # Get risk level
        churn_risk = self.get_risk_level(churn_probability)

        # Categorize churn reasons
        churn_reasons = self._categorize_reasons(features, churn_factors)

        return {
            "churn_probability": round(churn_probability, 1),
            "churn_risk": churn_risk,
            "churn_drivers": churn_factors[:5],  # Top 5 drivers
            "churn_reasons": churn_reasons,
            "is_high_risk": churn_probability >= self.churn_threshold,
            "explanation": {
                "summary": f"Guest has {churn_risk} churn risk ({churn_probability:.0f}%)",
                "main_concerns": [f["description"] for f in churn_factors[:3]],
                "mitigation_actions": self._get_mitigation_actions(churn_reasons),
            },
            "model_version": self.model_version,
        }

    def get_risk_level(self, probability: float) -> str:
        """Get risk level label"""
        if probability >= 80:
            return "critical"
        elif probability >= 60:
            return "high"
        elif probability >= 40:
            return "medium"
        else:
            return "low"

    def _categorize_reasons(self, features: Dict[str, Any], factors: List[Dict]) -> List[Dict[str, Any]]:
        """Categorize churn reasons into main categories"""
        reasons = []

        # Check for price-related reasons
        total_spent = features.get("total_spent", 0)
        avg_booking_value = features.get("avg_booking_value", 0)
        if total_spent > 0 and avg_booking_value > 300:
            reasons.append({
                "category": "price",
                "reason": "Price sensitivity - may be seeking better value",
                "confidence": 0.6,
                "indicators": ["High average booking value"]
            })

        # Check for service-related reasons
        sentiment_factors = [f for f in factors if f.get("category") == "sentiment"]
        if sentiment_factors:
            reasons.append({
                "category": "service",
                "reason": "Service experience issues detected",
                "confidence": 0.8,
                "indicators": [f["description"] for f in sentiment_factors]
            })

        # Check for recency-related reasons
        recency_factors = [f for f in factors if f.get("category") == "recency"]
        if recency_factors:
            reasons.append({
                "category": "recency",
                "reason": "Lost interest - long gap since last visit",
                "confidence": 0.7,
                "indicators": [f["description"] for f in recency_factors]
            })

        # Check for engagement-related reasons
        engagement_factors = [f for f in factors if f.get("category") == "engagement"]
        if engagement_factors:
            reasons.append({
                "category": "engagement",
                "reason": "Low engagement with hotel communications",
                "confidence": 0.5,
                "indicators": [f["description"] for f in engagement_factors]
            })

        return sorted(reasons, key=lambda x: x["confidence"], reverse=True)

    def _get_mitigation_actions(self, reasons: List[Dict[str, Any]]) -> List[str]:
        """Get recommended mitigation actions based on churn reasons"""
        actions = []

        for reason in reasons:
            category = reason.get("category", "")
            if category == "price":
                actions.append("Offer loyalty discount or exclusive member rate")
            elif category == "service":
                actions.append("Proactive manager outreach to address concerns")
                actions.append("Offer complimentary upgrade on next stay")
            elif category == "recency":
                actions.append("Send personalized win-back campaign")
                actions.append("Offer time-limited special promotion")
            elif category == "engagement":
                actions.append("Retarget with relevant content and offers")

        if not actions:
            actions.append("Schedule follow-up communication")

        return actions[:3]  # Return top 3 actions
