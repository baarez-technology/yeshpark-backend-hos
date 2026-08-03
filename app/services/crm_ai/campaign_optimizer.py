"""
Campaign Optimizer
Optimizes marketing campaigns using AI-driven recommendations
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum


class CampaignType(str, Enum):
    WIN_BACK = "win_back"
    LOYALTY = "loyalty"
    UPSELL = "upsell"
    DIRECT_BOOKING = "direct_booking"
    SEASONAL = "seasonal"
    EVENT = "event"
    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"


class CampaignOptimizer:
    """AI-powered campaign optimization"""

    def __init__(self, model_version: str = "1.0.0"):
        self.model_version = model_version
        self.model_name = "campaign_optimizer_v1"

        # Channel effectiveness by segment (historical averages)
        self.channel_effectiveness = {
            "high_value": {"email": 0.25, "sms": 0.15, "whatsapp": 0.20, "push": 0.10},
            "medium_value": {"email": 0.20, "sms": 0.18, "whatsapp": 0.22, "push": 0.12},
            "low_value": {"email": 0.15, "sms": 0.20, "whatsapp": 0.25, "push": 0.15},
            "at_risk": {"email": 0.18, "sms": 0.22, "whatsapp": 0.28, "push": 0.08},
        }

        # Optimal send times by segment (hour of day)
        self.optimal_times = {
            "business": [8, 9, 10, 18, 19],
            "leisure": [10, 11, 19, 20, 21],
            "family": [20, 21, 9, 10],
            "default": [10, 11, 18, 19, 20],
        }

    def recommend_campaign(
        self,
        guest_features: Dict[str, Any],
        guest_scores: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Recommend optimal campaign for a guest"""
        # Extract key metrics
        churn_probability = guest_scores.get("churn_probability", 50)
        health_score = guest_scores.get("health_score", 50)
        rebooking_probability = guest_scores.get("rebooking_probability", 50)
        ltv = guest_scores.get("predicted_ltv", 0)

        recency_days = guest_features.get("recency_days", 999)
        total_bookings = guest_features.get("total_bookings", 0)
        total_spent = guest_features.get("total_spent", 0)
        vip_status = guest_features.get("vip_status", False)

        # Determine campaign type based on guest state
        campaign_type, priority = self._determine_campaign_type(
            churn_probability, health_score, rebooking_probability,
            recency_days, total_bookings, vip_status
        )

        # Get guest segment
        segment = self._get_guest_segment(total_spent, total_bookings, vip_status)

        # Recommend channel
        channel, channel_confidence = self._recommend_channel(segment, guest_features)

        # Recommend timing
        optimal_time = self._recommend_timing(guest_features)

        # Generate personalized content
        content = self._generate_content_recommendation(
            campaign_type, guest_features, guest_scores, segment
        )

        # Calculate predicted conversion rate
        predicted_conversion = self._predict_conversion(
            campaign_type, segment, channel, guest_scores
        )

        return {
            "recommended_campaign": {
                "type": campaign_type.value,
                "priority": priority,
                "segment": segment,
            },
            "channel_recommendation": {
                "primary_channel": channel,
                "confidence": round(channel_confidence, 2),
                "fallback_channel": self._get_fallback_channel(channel),
            },
            "timing_recommendation": {
                "optimal_hour": optimal_time,
                "optimal_days": self._get_optimal_days(campaign_type),
                "send_within_days": self._get_urgency(priority),
            },
            "content_recommendation": content,
            "predicted_metrics": {
                "conversion_rate": round(predicted_conversion * 100, 1),
                "expected_revenue": round(predicted_conversion * ltv * 0.1, 2),
            },
            "personalization_suggestions": self._get_personalization_suggestions(
                guest_features, campaign_type
            ),
            "model_version": self.model_version,
        }

    def _determine_campaign_type(
        self,
        churn_probability: float,
        health_score: float,
        rebooking_probability: float,
        recency_days: int,
        total_bookings: int,
        vip_status: bool
    ) -> tuple:
        """Determine optimal campaign type and priority"""
        # High churn risk - win back campaign
        if churn_probability >= 70:
            return CampaignType.WIN_BACK, "critical"

        # At risk but not critical
        if churn_probability >= 50 and recency_days > 180:
            return CampaignType.WIN_BACK, "high"

        # High value guest with good health - loyalty
        if health_score >= 70 and vip_status:
            return CampaignType.LOYALTY, "medium"

        # Good rebooking probability - upsell opportunity
        if rebooking_probability >= 60 and health_score >= 60:
            return CampaignType.UPSELL, "medium"

        # OTA conversion opportunity (assuming first booking)
        if total_bookings == 1 and recency_days <= 90:
            return CampaignType.DIRECT_BOOKING, "high"

        # Default to seasonal campaign
        return CampaignType.SEASONAL, "low"

    def _get_guest_segment(
        self,
        total_spent: float,
        total_bookings: int,
        vip_status: bool
    ) -> str:
        """Segment guest for campaign optimization"""
        if vip_status or total_spent >= 5000:
            return "high_value"
        elif total_spent >= 1000 or total_bookings >= 3:
            return "medium_value"
        else:
            return "low_value"

    def _recommend_channel(
        self,
        segment: str,
        guest_features: Dict[str, Any]
    ) -> tuple:
        """Recommend optimal communication channel"""
        effectiveness = self.channel_effectiveness.get(segment, self.channel_effectiveness["low_value"])

        # Adjust based on guest preferences (if available)
        preferred_channel = guest_features.get("preferred_channel")
        if preferred_channel and preferred_channel in effectiveness:
            effectiveness[preferred_channel] *= 1.3

        # Find best channel
        best_channel = max(effectiveness, key=effectiveness.get)
        confidence = effectiveness[best_channel]

        return best_channel, confidence

    def _get_fallback_channel(self, primary: str) -> str:
        """Get fallback channel"""
        fallbacks = {
            "email": "whatsapp",
            "whatsapp": "sms",
            "sms": "email",
            "push": "email",
        }
        return fallbacks.get(primary, "email")

    def _recommend_timing(self, guest_features: Dict[str, Any]) -> int:
        """Recommend optimal send time (hour)"""
        # Determine guest type
        guest_type = guest_features.get("guest_type", "default")
        if guest_type not in self.optimal_times:
            guest_type = "default"

        # Return first optimal hour
        return self.optimal_times[guest_type][0]

    def _get_optimal_days(self, campaign_type: CampaignType) -> List[str]:
        """Get optimal days for campaign type"""
        if campaign_type in [CampaignType.WIN_BACK, CampaignType.DIRECT_BOOKING]:
            return ["Tuesday", "Wednesday", "Thursday"]
        elif campaign_type == CampaignType.LOYALTY:
            return ["Monday", "Tuesday"]
        else:
            return ["Thursday", "Friday"]

    def _get_urgency(self, priority: str) -> int:
        """Get send urgency in days"""
        urgency = {
            "critical": 1,
            "high": 3,
            "medium": 7,
            "low": 14,
        }
        return urgency.get(priority, 7)

    def _generate_content_recommendation(
        self,
        campaign_type: CampaignType,
        guest_features: Dict[str, Any],
        guest_scores: Dict[str, Any],
        segment: str
    ) -> Dict[str, Any]:
        """Generate content recommendations"""
        guest_name = guest_features.get("guest_name", "Guest")
        first_name = guest_name.split()[0] if guest_name else "Guest"

        content = {
            "subject_line_suggestions": [],
            "body_focus": [],
            "cta_suggestions": [],
            "offer_recommendations": [],
        }

        if campaign_type == CampaignType.WIN_BACK:
            content["subject_line_suggestions"] = [
                f"We miss you, {first_name}! Here's a special offer",
                f"{first_name}, it's been a while - come back and save",
                "Your exclusive return offer awaits",
            ]
            content["body_focus"] = [
                "Remind of positive past experiences",
                "Highlight new amenities or improvements",
                "Create sense of urgency with limited offer",
            ]
            content["cta_suggestions"] = ["Claim Your Offer", "Book Now & Save", "Return to Paradise"]
            content["offer_recommendations"] = [
                {"type": "discount", "value": "20%", "description": "20% off next stay"},
                {"type": "upgrade", "value": "free", "description": "Free room upgrade"},
            ]

        elif campaign_type == CampaignType.LOYALTY:
            content["subject_line_suggestions"] = [
                f"Thank you, {first_name} - A special reward for you",
                "Your loyalty deserves recognition",
                f"Exclusive VIP offer for {first_name}",
            ]
            content["body_focus"] = [
                "Express gratitude for loyalty",
                "Offer exclusive experiences",
                "Reinforce VIP status benefits",
            ]
            content["cta_suggestions"] = ["Explore VIP Benefits", "Unlock Exclusive Access", "Claim Reward"]
            content["offer_recommendations"] = [
                {"type": "experience", "value": "complimentary", "description": "Spa treatment"},
                {"type": "points", "value": "2x", "description": "Double loyalty points"},
            ]

        elif campaign_type == CampaignType.UPSELL:
            content["subject_line_suggestions"] = [
                f"{first_name}, enhance your next stay",
                "Exclusive upgrade opportunity",
                "Make your next visit unforgettable",
            ]
            content["body_focus"] = [
                "Highlight premium room options",
                "Showcase special packages",
                "Present value-added services",
            ]
            content["cta_suggestions"] = ["Upgrade Now", "View Premium Options", "Enhance Your Stay"]
            content["offer_recommendations"] = [
                {"type": "package", "value": "bundled", "description": "Stay & Dine package"},
                {"type": "upgrade", "value": "discounted", "description": "50% off suite upgrade"},
            ]

        elif campaign_type == CampaignType.DIRECT_BOOKING:
            content["subject_line_suggestions"] = [
                "Book direct and save more!",
                f"{first_name}, get the best rate - guaranteed",
                "Why book through OTAs when you can save?",
            ]
            content["body_focus"] = [
                "Highlight direct booking benefits",
                "Price match guarantee messaging",
                "Exclusive direct-only perks",
            ]
            content["cta_suggestions"] = ["Book Direct", "Get Best Rate", "Unlock Member Rates"]
            content["offer_recommendations"] = [
                {"type": "discount", "value": "15%", "description": "15% off vs OTA prices"},
                {"type": "perk", "value": "free", "description": "Free breakfast with direct booking"},
            ]

        else:  # Seasonal
            content["subject_line_suggestions"] = [
                "Escape this season with special rates",
                f"{first_name}, your perfect getaway awaits",
                "Limited-time seasonal offer inside",
            ]
            content["body_focus"] = [
                "Seasonal highlights and activities",
                "Limited availability messaging",
                "Visual appeal of destination",
            ]
            content["cta_suggestions"] = ["Plan Your Escape", "See Seasonal Offers", "Book Your Getaway"]
            content["offer_recommendations"] = [
                {"type": "rate", "value": "seasonal", "description": "Seasonal special rate"},
                {"type": "package", "value": "seasonal", "description": "Season-themed package"},
            ]

        return content

    def _predict_conversion(
        self,
        campaign_type: CampaignType,
        segment: str,
        channel: str,
        guest_scores: Dict[str, Any]
    ) -> float:
        """Predict campaign conversion rate"""
        # Base rates by campaign type
        base_rates = {
            CampaignType.WIN_BACK: 0.08,
            CampaignType.LOYALTY: 0.15,
            CampaignType.UPSELL: 0.12,
            CampaignType.DIRECT_BOOKING: 0.10,
            CampaignType.SEASONAL: 0.06,
            CampaignType.EVENT: 0.08,
            CampaignType.BIRTHDAY: 0.20,
            CampaignType.ANNIVERSARY: 0.18,
        }

        base_rate = base_rates.get(campaign_type, 0.05)

        # Adjust by segment
        segment_multipliers = {
            "high_value": 1.5,
            "medium_value": 1.2,
            "low_value": 0.9,
            "at_risk": 0.7,
        }
        base_rate *= segment_multipliers.get(segment, 1.0)

        # Adjust by channel effectiveness
        channel_effectiveness = self.channel_effectiveness.get(segment, {})
        channel_rate = channel_effectiveness.get(channel, 0.15)
        base_rate *= (channel_rate / 0.15)

        # Adjust by guest scores
        health_score = guest_scores.get("health_score", 50)
        rebooking_prob = guest_scores.get("rebooking_probability", 50)

        score_multiplier = 0.5 + (health_score / 100) * 0.3 + (rebooking_prob / 100) * 0.2
        base_rate *= score_multiplier

        return min(0.5, max(0.01, base_rate))

    def _get_personalization_suggestions(
        self,
        guest_features: Dict[str, Any],
        campaign_type: CampaignType
    ) -> List[str]:
        """Get personalization suggestions"""
        suggestions = []

        # Name personalization
        suggestions.append("Use first name in subject and greeting")

        # Stay history
        total_bookings = guest_features.get("total_bookings", 0)
        if total_bookings > 1:
            suggestions.append("Reference previous stays and preferences")

        # Loyalty
        if guest_features.get("vip_status"):
            suggestions.append("Emphasize VIP status and exclusive access")
        elif guest_features.get("loyalty_tier") in ["gold", "platinum"]:
            suggestions.append("Highlight loyalty tier benefits")

        # Preferences
        suggestions.append("Include preferred room type if known")

        # Timing
        if campaign_type == CampaignType.WIN_BACK:
            suggestions.append("Create urgency with time-limited offer")

        return suggestions[:5]

    def optimize_ab_test(
        self,
        variant_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze A/B test results and recommend winner"""
        if len(variant_results) < 2:
            return {"error": "Need at least 2 variants for A/B test analysis"}

        # Calculate conversion rates
        for variant in variant_results:
            sent = variant.get("sent", 0)
            converted = variant.get("converted", 0)
            variant["conversion_rate"] = converted / sent if sent > 0 else 0

        # Sort by conversion rate
        sorted_variants = sorted(
            variant_results,
            key=lambda x: x["conversion_rate"],
            reverse=True
        )

        winner = sorted_variants[0]
        runner_up = sorted_variants[1]

        # Calculate lift
        lift = (
            (winner["conversion_rate"] - runner_up["conversion_rate"])
            / runner_up["conversion_rate"]
            if runner_up["conversion_rate"] > 0 else 0
        )

        # Simple statistical significance (would use proper stats in production)
        total_sample = sum(v.get("sent", 0) for v in variant_results)
        is_significant = total_sample >= 1000 and lift > 0.1

        return {
            "winning_variant": winner.get("name", "Variant A"),
            "winning_conversion_rate": round(winner["conversion_rate"] * 100, 2),
            "lift_vs_runner_up": round(lift * 100, 1),
            "is_statistically_significant": is_significant,
            "recommendation": (
                f"Deploy {winner.get('name', 'winning variant')} - "
                f"{round(lift * 100, 1)}% lift observed"
                if is_significant else
                "Continue test - need more data for significance"
            ),
            "all_variants": [
                {
                    "name": v.get("name"),
                    "conversion_rate": round(v["conversion_rate"] * 100, 2),
                    "sent": v.get("sent", 0),
                    "converted": v.get("converted", 0),
                }
                for v in sorted_variants
            ],
        }
