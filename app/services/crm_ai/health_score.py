"""
Guest Health Score Model
Calculates a 0-100 score predicting guest satisfaction and loyalty
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import math


class HealthScoreModel:
    """Health Score Model - Rule-based with weighted components"""

    def __init__(self, model_version: str = "1.0.0"):
        self.model_version = model_version
        self.model_name = "health_score_v1"

        # Component weights
        self.weights = {
            "recency": 0.25,
            "frequency": 0.20,
            "monetary": 0.20,
            "engagement": 0.15,
            "sentiment": 0.15,
            "loyalty": 0.05,
        }

    def calculate(self, features: Dict[str, Any], last_score_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Calculate guest health score with component breakdown"""
        # Recency score (0-100) - More recent = higher score
        recency_days = features.get("recency_days", 999)
        if recency_days <= 30:
            recency_score = 100
        elif recency_days <= 90:
            recency_score = 85
        elif recency_days <= 180:
            recency_score = 70
        elif recency_days <= 365:
            recency_score = 50
        else:
            recency_score = max(20, 100 - (recency_days / 10))

        # Frequency score (0-100) - More bookings = higher score
        total_bookings = features.get("total_bookings", 0)
        if total_bookings >= 10:
            frequency_score = 100
        elif total_bookings >= 5:
            frequency_score = 85
        elif total_bookings >= 3:
            frequency_score = 70
        elif total_bookings >= 2:
            frequency_score = 55
        elif total_bookings >= 1:
            frequency_score = 40
        else:
            frequency_score = 20

        # Monetary score (0-100) - Higher spend = higher score
        total_spent = features.get("total_spent", 0)
        if total_spent >= 10000:
            monetary_score = 100
        elif total_spent >= 5000:
            monetary_score = 90
        elif total_spent >= 2500:
            monetary_score = 75
        elif total_spent >= 1000:
            monetary_score = 60
        elif total_spent >= 500:
            monetary_score = 45
        else:
            monetary_score = max(20, total_spent / 25)

        # Engagement score (0-100)
        recent_engagements = features.get("recent_engagements_90d", 0)
        if recent_engagements >= 5:
            engagement_score = 100
        elif recent_engagements >= 3:
            engagement_score = 80
        elif recent_engagements >= 1:
            engagement_score = 60
        else:
            engagement_score = 30

        # Sentiment score (0-100) - Convert from -1 to 1 scale
        avg_sentiment = features.get("avg_sentiment_90d", 0)
        sentiment_score = (avg_sentiment + 1) * 50  # Convert to 0-100

        # Loyalty bonus
        vip_status = features.get("vip_status", False)
        loyalty_tier = features.get("loyalty_tier", "member")
        loyalty_bonus = 0
        if vip_status:
            loyalty_bonus = 20
        elif loyalty_tier == "platinum":
            loyalty_bonus = 15
        elif loyalty_tier == "gold":
            loyalty_bonus = 10
        elif loyalty_tier == "silver":
            loyalty_bonus = 5
        loyalty_score = 50 + loyalty_bonus

        # Cancellation penalty
        cancellation_rate = features.get("cancellation_rate", 0)
        cancellation_penalty = cancellation_rate * 20

        # Calculate weighted score
        health_score = (
            recency_score * self.weights["recency"] +
            frequency_score * self.weights["frequency"] +
            monetary_score * self.weights["monetary"] +
            engagement_score * self.weights["engagement"] +
            sentiment_score * self.weights["sentiment"] +
            loyalty_score * self.weights["loyalty"]
        ) - cancellation_penalty

        # Apply time-based decay if applicable
        if last_score_date:
            days_since_last = (datetime.utcnow() - last_score_date).days
            decay_factor = max(0.9, 1 - (days_since_last * 0.001))  # 0.1% decay per day
            health_score *= decay_factor

        # Clamp to 0-100
        health_score = max(0, min(100, health_score))

        # Get score label
        score_label = self.get_score_label(health_score)

        return {
            "health_score": round(health_score, 1),
            "score_label": score_label,
            "components": {
                "recency_score": round(recency_score, 1),
                "frequency_score": round(frequency_score, 1),
                "monetary_score": round(monetary_score, 1),
                "engagement_score": round(engagement_score, 1),
                "sentiment_score": round(sentiment_score, 1),
                "loyalty_score": round(loyalty_score, 1),
                "cancellation_penalty": round(cancellation_penalty, 1),
            },
            "explanation": self._generate_explanation(features, health_score, score_label),
            "model_version": self.model_version,
        }

    def get_score_label(self, score: float) -> str:
        """Get human-readable label for score"""
        if score >= 85:
            return "Excellent"
        elif score >= 70:
            return "Good"
        elif score >= 55:
            return "Fair"
        elif score >= 40:
            return "At-Risk"
        else:
            return "Critical"

    def _generate_explanation(self, features: Dict[str, Any], score: float, label: str) -> Dict[str, Any]:
        """Generate human-readable explanation"""
        insights = []
        recommendations = []

        # Recency insights
        recency_days = features.get("recency_days", 999)
        if recency_days > 180:
            insights.append(f"Guest hasn't visited in {recency_days} days")
            recommendations.append("Send a win-back campaign with special offer")
        elif recency_days <= 30:
            insights.append("Recent visit indicates active engagement")

        # Booking insights
        total_bookings = features.get("total_bookings", 0)
        if total_bookings >= 5:
            insights.append(f"Loyal guest with {total_bookings} bookings")
        elif total_bookings == 1:
            insights.append("New guest - first booking")
            recommendations.append("Send welcome series to encourage repeat visits")

        # Spending insights
        total_spent = features.get("total_spent", 0)
        if total_spent >= 5000:
            insights.append(f"High-value guest with ${total_spent:.0f} lifetime value")
        elif total_spent < 500 and total_bookings > 0:
            recommendations.append("Consider upselling opportunities")

        # Cancellation insights
        cancellation_rate = features.get("cancellation_rate", 0)
        if cancellation_rate > 0.3:
            insights.append(f"High cancellation rate ({cancellation_rate:.0%})")
            recommendations.append("Review booking flexibility and communication")

        # Sentiment insights
        avg_sentiment = features.get("avg_sentiment_90d", 0)
        if avg_sentiment < -0.3:
            insights.append("Recent negative sentiment detected")
            recommendations.append("Proactive recovery outreach recommended")

        return {
            "summary": f"Guest has a {label.lower()} health score of {score:.0f}/100",
            "insights": insights,
            "recommendations": recommendations,
            "top_factors": [
                {"factor": "Recency", "impact": "positive" if recency_days <= 90 else "negative"},
                {"factor": "Booking History", "impact": "positive" if total_bookings >= 2 else "neutral"},
                {"factor": "Lifetime Value", "impact": "positive" if total_spent >= 1000 else "neutral"},
            ]
        }
