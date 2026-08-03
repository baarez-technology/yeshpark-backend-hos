"""
Lifetime Value (LTV) Prediction Model
Predicts expected total revenue from a guest over their lifetime
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import math


class LTVModel:
    """LTV Model - Rule-based lifetime value prediction"""

    def __init__(self, model_version: str = "1.0.0"):
        self.model_version = model_version
        self.model_name = "ltv_prediction_v1"

        # Business parameters
        self.avg_room_rate = 250  # Average nightly rate
        self.avg_stay_length = 2.5  # Average nights per stay
        self.discount_rate = 0.1  # Annual discount rate for NPV
        self.customer_lifespan_years = 5  # Expected customer relationship length

    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Predict lifetime value with breakdown"""
        # Historical value
        total_spent = features.get("total_spent", 0)
        total_bookings = features.get("total_bookings", 0)
        avg_booking_value = features.get("avg_booking_value", 0)

        if avg_booking_value == 0 and total_bookings > 0:
            avg_booking_value = total_spent / total_bookings
        elif avg_booking_value == 0:
            avg_booking_value = self.avg_room_rate * self.avg_stay_length

        # Frequency prediction
        booking_frequency = features.get("booking_frequency", 0)
        days_since_registration = features.get("days_since_registration", 365)

        # Estimate future bookings per year with reasonable bounds
        # Max reasonable bookings per year is 12 (monthly stays)
        MAX_BOOKINGS_PER_YEAR = 12
        # Minimum days needed to extrapolate booking frequency accurately
        MIN_DAYS_FOR_EXTRAPOLATION = 90

        if booking_frequency > 0:
            predicted_bookings_per_year = min(booking_frequency, MAX_BOOKINGS_PER_YEAR)
        elif total_bookings > 0 and days_since_registration >= MIN_DAYS_FOR_EXTRAPOLATION:
            # Only extrapolate if guest has been around long enough for accurate prediction
            predicted_bookings_per_year = (total_bookings / days_since_registration) * 365
            # Cap at reasonable maximum
            predicted_bookings_per_year = min(predicted_bookings_per_year, MAX_BOOKINGS_PER_YEAR)
        elif total_bookings > 0:
            # New guest with booking - use conservative estimate based on actual bookings
            # Assume they might book 2-4x per year based on their initial engagement
            predicted_bookings_per_year = min(total_bookings * 2, MAX_BOOKINGS_PER_YEAR)
        else:
            predicted_bookings_per_year = 0.5  # Default for guests with no bookings

        # Adjust for churn risk
        recency_days = features.get("recency_days", 999)
        cancellation_rate = features.get("cancellation_rate", 0)

        # Retention rate calculation
        if recency_days <= 90:
            retention_rate = 0.85
        elif recency_days <= 180:
            retention_rate = 0.70
        elif recency_days <= 365:
            retention_rate = 0.50
        else:
            retention_rate = 0.25

        # Adjust for cancellation behavior
        retention_rate *= (1 - cancellation_rate * 0.3)

        # Loyalty bonus
        vip_status = features.get("vip_status", False)
        loyalty_tier = features.get("loyalty_tier", "member")

        loyalty_multiplier = 1.0
        if vip_status:
            loyalty_multiplier = 1.5
        elif loyalty_tier == "platinum":
            loyalty_multiplier = 1.4
        elif loyalty_tier == "gold":
            loyalty_multiplier = 1.25
        elif loyalty_tier == "silver":
            loyalty_multiplier = 1.1

        # Calculate LTV components
        # Historical LTV
        historical_ltv = total_spent

        # Predicted future LTV (NPV of future bookings)
        future_ltv = 0.0
        remaining_years = self.customer_lifespan_years
        current_retention = retention_rate

        for year in range(1, remaining_years + 1):
            year_value = (
                predicted_bookings_per_year *
                avg_booking_value *
                current_retention *
                loyalty_multiplier
            )
            # Discount to present value
            discounted_value = year_value / ((1 + self.discount_rate) ** year)
            future_ltv += discounted_value
            # Retention decreases each year
            current_retention *= 0.85

        # Total LTV
        total_ltv = historical_ltv + future_ltv

        # Confidence based on data quality
        confidence = self._calculate_confidence(features)

        # LTV segment
        ltv_segment = self._get_ltv_segment(total_ltv)

        return {
            "predicted_ltv": round(total_ltv, 2),
            "historical_ltv": round(historical_ltv, 2),
            "future_ltv": round(future_ltv, 2),
            "ltv_segment": ltv_segment,
            "confidence": round(confidence, 2),
            "components": {
                "avg_booking_value": round(avg_booking_value, 2),
                "predicted_bookings_per_year": round(predicted_bookings_per_year, 2),
                "retention_rate": round(retention_rate, 2),
                "loyalty_multiplier": round(loyalty_multiplier, 2),
            },
            "explanation": {
                "summary": f"Guest predicted to generate ${total_ltv:,.0f} in lifetime value",
                "historical_contribution": f"${historical_ltv:,.0f} already spent",
                "future_potential": f"${future_ltv:,.0f} expected over next {self.customer_lifespan_years} years",
                "key_drivers": self._get_key_drivers(features, ltv_segment),
            },
            "recommendations": self._get_recommendations(ltv_segment, features),
            "model_version": self.model_version,
        }

    def _calculate_confidence(self, features: Dict[str, Any]) -> float:
        """Calculate prediction confidence based on data quality"""
        confidence = 0.5  # Base confidence

        total_bookings = features.get("total_bookings", 0)
        if total_bookings >= 5:
            confidence += 0.3
        elif total_bookings >= 2:
            confidence += 0.2
        elif total_bookings >= 1:
            confidence += 0.1

        days_since_registration = features.get("days_since_registration", 0)
        if days_since_registration >= 365:
            confidence += 0.1

        recent_engagements = features.get("recent_engagements_90d", 0)
        if recent_engagements >= 1:
            confidence += 0.1

        return min(0.95, confidence)

    def _get_ltv_segment(self, ltv: float) -> str:
        """Segment based on LTV"""
        if ltv >= 10000:
            return "high_value"
        elif ltv >= 5000:
            return "medium_high"
        elif ltv >= 2000:
            return "medium"
        elif ltv >= 500:
            return "low_medium"
        else:
            return "low"

    def _get_key_drivers(self, features: Dict[str, Any], segment: str) -> List[str]:
        """Get key drivers of LTV"""
        drivers = []

        total_bookings = features.get("total_bookings", 0)
        if total_bookings >= 5:
            drivers.append("Repeat guest with strong booking history")

        avg_booking_value = features.get("avg_booking_value", 0)
        if avg_booking_value >= 500:
            drivers.append("High average booking value")

        vip_status = features.get("vip_status", False)
        if vip_status:
            drivers.append("VIP status indicates premium engagement")

        recency_days = features.get("recency_days", 999)
        if recency_days <= 90:
            drivers.append("Recent activity suggests continued engagement")
        elif recency_days > 365:
            drivers.append("Long absence may impact future value")

        return drivers[:3] if drivers else ["Limited booking history"]

    def _get_recommendations(self, segment: str, features: Dict[str, Any]) -> List[str]:
        """Get recommendations based on LTV segment"""
        recommendations = []

        if segment in ["high_value", "medium_high"]:
            recommendations.append("Prioritize for VIP treatment and exclusive offers")
            recommendations.append("Assign dedicated guest relationship manager")
            if not features.get("vip_status"):
                recommendations.append("Consider VIP status upgrade")

        elif segment == "medium":
            recommendations.append("Target for loyalty program upgrades")
            recommendations.append("Offer personalized upsell opportunities")

        elif segment in ["low_medium", "low"]:
            if features.get("total_bookings", 0) <= 1:
                recommendations.append("Send welcome series to encourage repeat visits")
            recommendations.append("Promote value packages and special offers")
            recommendations.append("Focus on experience optimization")

        return recommendations[:3]
