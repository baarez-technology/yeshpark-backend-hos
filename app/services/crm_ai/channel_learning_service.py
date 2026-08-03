"""
Channel Learning Service
Uses reinforcement learning concepts to optimize channel selection for each guest
Learns from engagement history to predict best communication channels
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import json
import math
import random

from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.reservations import Guest
from app.models.crm import CRMGuestActivities
from app.models.crm_ai import CampaignRecipient


class ThompsonSampler:
    """
    Thompson Sampling for multi-armed bandit channel selection
    Uses Beta distribution for exploration-exploitation balance
    """
    def __init__(self, arms: List[str]):
        self.arms = arms
        # Initialize with uniform prior (alpha=1, beta=1)
        self.successes = {arm: 1.0 for arm in arms}
        self.failures = {arm: 1.0 for arm in arms}

    def sample(self) -> str:
        """Sample from posterior and return best arm"""
        samples = {}
        for arm in self.arms:
            # Sample from Beta distribution
            samples[arm] = self._beta_sample(
                self.successes[arm],
                self.failures[arm]
            )
        return max(samples, key=samples.get)

    def _beta_sample(self, alpha: float, beta: float) -> float:
        """Sample from Beta distribution using transformation method"""
        # Using gamma distribution trick: Beta(a,b) = Gamma(a,1) / (Gamma(a,1) + Gamma(b,1))
        x = self._gamma_sample(alpha)
        y = self._gamma_sample(beta)
        return x / (x + y) if (x + y) > 0 else 0.5

    def _gamma_sample(self, alpha: float) -> float:
        """Simple gamma sampling using Marsaglia and Tsang's method for alpha >= 1"""
        if alpha < 1:
            return self._gamma_sample(1 + alpha) * (random.random() ** (1.0 / alpha))

        d = alpha - 1.0 / 3.0
        c = 1.0 / math.sqrt(9.0 * d)

        while True:
            x = random.gauss(0, 1)
            v = 1.0 + c * x
            if v > 0:
                v = v ** 3
                u = random.random()
                if u < 1.0 - 0.0331 * (x ** 2) ** 2:
                    return d * v
                if math.log(u) < 0.5 * x ** 2 + d * (1.0 - v + math.log(v)):
                    return d * v

    def update(self, arm: str, success: bool):
        """Update posterior with observed outcome"""
        if success:
            self.successes[arm] += 1
        else:
            self.failures[arm] += 1

    def get_probabilities(self) -> Dict[str, float]:
        """Get expected success probability for each arm"""
        return {
            arm: self.successes[arm] / (self.successes[arm] + self.failures[arm])
            for arm in self.arms
        }


class ChannelLearningService:
    """Service for learning optimal communication channels per guest"""

    CHANNELS = ["email", "sms", "whatsapp", "push", "in_app"]

    # Engagement weights for learning
    ENGAGEMENT_WEIGHTS = {
        "delivered": 0.1,
        "opened": 0.5,
        "clicked": 0.8,
        "converted": 1.0,
        "bounced": -0.5,
        "unsubscribed": -1.0,
        "complaint": -2.0
    }

    # Default channel effectiveness (prior beliefs)
    DEFAULT_EFFECTIVENESS = {
        "email": 0.25,
        "sms": 0.30,
        "whatsapp": 0.35,
        "push": 0.20,
        "in_app": 0.15
    }

    # Time-of-day preferences (hour buckets)
    TIME_BUCKETS = {
        "early_morning": (5, 8),
        "morning": (8, 12),
        "afternoon": (12, 17),
        "evening": (17, 21),
        "night": (21, 24),
        "late_night": (0, 5)
    }

    def __init__(self):
        self.exploration_rate = 0.2  # 20% exploration
        self.learning_rate = 0.1
        self.min_samples_for_prediction = 3

    async def get_best_channel(
        self,
        session: AsyncSession,
        guest_id: int,
        message_type: str = "promotional",
        exclude_channels: Optional[List[str]] = None
    ) -> dict:
        """
        Get the best channel for reaching a guest using Thompson Sampling
        Returns channel recommendation with confidence
        """
        exclude = exclude_channels or []
        available_channels = [c for c in self.CHANNELS if c not in exclude]

        if not available_channels:
            return {
                "error": "No available channels",
                "recommendation": None
            }

        # Get guest's engagement history
        history = await self._get_channel_history(session, guest_id)

        # Initialize Thompson Sampler with guest-specific priors
        sampler = ThompsonSampler(available_channels)
        await self._load_guest_priors(sampler, history)

        # Sample best channel
        if random.random() < self.exploration_rate:
            # Exploration: random channel
            recommended_channel = random.choice(available_channels)
            selection_type = "exploration"
        else:
            # Exploitation: Thompson sampling
            recommended_channel = sampler.sample()
            selection_type = "exploitation"

        # Get channel probabilities
        probabilities = sampler.get_probabilities()

        # Calculate confidence based on sample size
        samples = history.get(recommended_channel, {}).get("total", 0)
        confidence = min(0.95, 0.5 + (samples * 0.05))

        # Get best time to send
        best_time = await self._get_best_send_time(session, guest_id, recommended_channel)

        return {
            "guest_id": guest_id,
            "recommended_channel": recommended_channel,
            "confidence": round(confidence, 3),
            "selection_type": selection_type,
            "channel_scores": {
                ch: round(prob, 4) for ch, prob in probabilities.items()
            },
            "best_send_time": best_time,
            "sample_size": samples,
            "available_channels": available_channels,
            "recommendation_reason": self._generate_recommendation_reason(
                recommended_channel, probabilities, history
            )
        }

    async def _get_channel_history(
        self,
        session: AsyncSession,
        guest_id: int,
        days: int = 365
    ) -> Dict[str, Dict[str, int]]:
        """Get engagement history by channel"""
        history = {ch: {"total": 0, "success": 0, "failure": 0} for ch in self.CHANNELS}
        since_date = datetime.utcnow() - timedelta(days=days)

        try:
            # Get campaign recipient data
            recipients = await session.exec(
                select(CampaignRecipient)
                .where(
                    and_(
                        CampaignRecipient.guest_id == guest_id,
                        CampaignRecipient.sent_at >= since_date,
                        CampaignRecipient.sent_at.isnot(None)
                    )
                )
            )

            for recipient in recipients.all():
                channel = recipient.channel
                if channel not in history:
                    continue

                history[channel]["total"] += 1

                # Determine success/failure
                if recipient.converted_at:
                    history[channel]["success"] += 3  # Strong signal
                elif recipient.clicked_at:
                    history[channel]["success"] += 2
                elif recipient.opened_at:
                    history[channel]["success"] += 1
                elif recipient.unsubscribed_at:
                    history[channel]["failure"] += 2
                else:
                    history[channel]["failure"] += 0.5  # Mild failure

        except Exception:
            pass

        return history

    async def _load_guest_priors(
        self,
        sampler: ThompsonSampler,
        history: Dict[str, Dict[str, int]]
    ):
        """Load guest-specific engagement history into sampler"""
        for channel, data in history.items():
            if channel in sampler.arms:
                # Add observed successes and failures
                sampler.successes[channel] += data.get("success", 0)
                sampler.failures[channel] += data.get("failure", 0)

                # Add prior based on default effectiveness
                prior_weight = 5  # Weight of prior belief
                default_rate = self.DEFAULT_EFFECTIVENESS.get(channel, 0.2)
                sampler.successes[channel] += default_rate * prior_weight
                sampler.failures[channel] += (1 - default_rate) * prior_weight

    async def _get_best_send_time(
        self,
        session: AsyncSession,
        guest_id: int,
        channel: str
    ) -> dict:
        """Determine best time to send based on engagement history"""
        time_engagement = {bucket: {"opens": 0, "sends": 0} for bucket in self.TIME_BUCKETS}

        try:
            recipients = await session.exec(
                select(CampaignRecipient)
                .where(
                    and_(
                        CampaignRecipient.guest_id == guest_id,
                        CampaignRecipient.channel == channel,
                        CampaignRecipient.sent_at.isnot(None)
                    )
                )
            )

            for recipient in recipients.all():
                sent_hour = recipient.sent_at.hour

                # Find which bucket this falls into
                for bucket, (start, end) in self.TIME_BUCKETS.items():
                    if start <= sent_hour < end or (bucket == "late_night" and (sent_hour >= 0 and sent_hour < 5)):
                        time_engagement[bucket]["sends"] += 1
                        if recipient.opened_at:
                            time_engagement[bucket]["opens"] += 1
                        break

        except Exception:
            pass

        # Calculate open rates by time bucket
        best_bucket = "morning"  # Default
        best_rate = 0.0

        for bucket, data in time_engagement.items():
            if data["sends"] >= 2:  # Minimum sample
                rate = data["opens"] / data["sends"]
                if rate > best_rate:
                    best_rate = rate
                    best_bucket = bucket

        # Get recommended hour
        start_hour, end_hour = self.TIME_BUCKETS[best_bucket]
        recommended_hour = (start_hour + end_hour) // 2

        return {
            "time_bucket": best_bucket,
            "recommended_hour": recommended_hour,
            "open_rate": round(best_rate, 3) if best_rate > 0 else None,
            "sample_size": sum(d["sends"] for d in time_engagement.values())
        }

    def _generate_recommendation_reason(
        self,
        channel: str,
        probabilities: Dict[str, float],
        history: Dict[str, Dict[str, int]]
    ) -> str:
        """Generate human-readable reason for recommendation"""
        prob = probabilities.get(channel, 0)
        samples = history.get(channel, {}).get("total", 0)

        if samples >= 10:
            success_rate = history[channel]["success"] / max(samples, 1)
            return f"Based on {samples} historical interactions with {success_rate:.0%} engagement rate"
        elif samples >= 3:
            return f"Learning pattern from {samples} interactions, showing positive response"
        else:
            default_rate = self.DEFAULT_EFFECTIVENESS.get(channel, 0.2)
            return f"Using industry baseline ({default_rate:.0%} expected engagement) - more data needed"

    async def record_engagement(
        self,
        session: AsyncSession,
        guest_id: int,
        channel: str,
        engagement_type: str,
        campaign_id: Optional[int] = None
    ) -> dict:
        """Record an engagement event for learning"""
        weight = self.ENGAGEMENT_WEIGHTS.get(engagement_type, 0)

        activity = CRMGuestActivities(
            guest_id=guest_id,
            activity_type=f"channel_engagement_{engagement_type}",
            activity_category="engagement",
            description=f"Guest {engagement_type} via {channel}",
            sentiment="positive" if weight > 0 else "negative" if weight < 0 else "neutral",
            importance="medium" if abs(weight) >= 0.5 else "low",
            timestamp=datetime.utcnow(),
            extra_data=json.dumps({
                "channel": channel,
                "engagement_type": engagement_type,
                "weight": weight,
                "campaign_id": campaign_id
            })
        )

        session.add(activity)
        await session.commit()

        return {
            "guest_id": guest_id,
            "channel": channel,
            "engagement_type": engagement_type,
            "weight": weight,
            "recorded_at": datetime.utcnow().isoformat()
        }

    async def get_guest_channel_profile(
        self,
        session: AsyncSession,
        guest_id: int
    ) -> dict:
        """Get comprehensive channel preference profile for a guest"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        history = await self._get_channel_history(session, guest_id)

        channel_profiles = {}
        for channel in self.CHANNELS:
            data = history.get(channel, {})
            total = data.get("total", 0)
            success = data.get("success", 0)
            failure = data.get("failure", 0)

            if total > 0:
                engagement_rate = success / (success + failure) if (success + failure) > 0 else 0
                status = "active"
            else:
                engagement_rate = self.DEFAULT_EFFECTIVENESS.get(channel, 0.2)
                status = "no_data"

            best_time = await self._get_best_send_time(session, guest_id, channel)

            channel_profiles[channel] = {
                "total_sent": total,
                "engagement_rate": round(engagement_rate, 4),
                "status": status,
                "best_time": best_time,
                "recommendation_score": round(
                    (success + 1) / (success + failure + 2), 4
                )  # Laplace smoothing
            }

        # Rank channels
        ranked_channels = sorted(
            channel_profiles.items(),
            key=lambda x: x[1]["recommendation_score"],
            reverse=True
        )

        return {
            "guest_id": guest_id,
            "guest_name": f"{guest.first_name} {guest.last_name}",
            "channel_profiles": channel_profiles,
            "ranked_channels": [
                {"channel": ch, "score": round(data["recommendation_score"], 4)}
                for ch, data in ranked_channels
            ],
            "primary_channel": ranked_channels[0][0] if ranked_channels else "email",
            "secondary_channel": ranked_channels[1][0] if len(ranked_channels) > 1 else None,
            "total_interactions": sum(p["total_sent"] for p in channel_profiles.values()),
            "profile_generated_at": datetime.utcnow().isoformat()
        }

    async def get_channel_performance_stats(
        self,
        session: AsyncSession,
        days: int = 30
    ) -> dict:
        """Get overall channel performance statistics"""
        since_date = datetime.utcnow() - timedelta(days=days)

        stats = {ch: {
            "sent": 0,
            "delivered": 0,
            "opened": 0,
            "clicked": 0,
            "converted": 0,
            "unsubscribed": 0
        } for ch in self.CHANNELS}

        try:
            recipients = await session.exec(
                select(CampaignRecipient)
                .where(
                    and_(
                        CampaignRecipient.sent_at >= since_date,
                        CampaignRecipient.sent_at.isnot(None)
                    )
                )
            )

            for r in recipients.all():
                channel = r.channel
                if channel not in stats:
                    continue

                stats[channel]["sent"] += 1
                if r.delivered_at:
                    stats[channel]["delivered"] += 1
                if r.opened_at:
                    stats[channel]["opened"] += 1
                if r.clicked_at:
                    stats[channel]["clicked"] += 1
                if r.converted_at:
                    stats[channel]["converted"] += 1
                if r.unsubscribed_at:
                    stats[channel]["unsubscribed"] += 1

        except Exception:
            pass

        # Calculate rates
        performance = {}
        for channel, data in stats.items():
            sent = data["sent"]
            performance[channel] = {
                "sent": sent,
                "delivery_rate": round(data["delivered"] / sent, 4) if sent > 0 else 0,
                "open_rate": round(data["opened"] / sent, 4) if sent > 0 else 0,
                "click_rate": round(data["clicked"] / sent, 4) if sent > 0 else 0,
                "conversion_rate": round(data["converted"] / sent, 4) if sent > 0 else 0,
                "unsubscribe_rate": round(data["unsubscribed"] / sent, 4) if sent > 0 else 0
            }

        # Rank by effectiveness (weighted score)
        def effectiveness_score(channel: str) -> float:
            p = performance[channel]
            return (
                p["open_rate"] * 0.3 +
                p["click_rate"] * 0.4 +
                p["conversion_rate"] * 0.5 -
                p["unsubscribe_rate"] * 0.3
            )

        ranked = sorted(
            self.CHANNELS,
            key=effectiveness_score,
            reverse=True
        )

        return {
            "period_days": days,
            "channel_performance": performance,
            "ranked_by_effectiveness": ranked,
            "best_channel": ranked[0] if ranked else "email",
            "recommendations": self._generate_channel_recommendations(performance),
            "generated_at": datetime.utcnow().isoformat()
        }

    def _generate_channel_recommendations(
        self,
        performance: Dict[str, Dict[str, float]]
    ) -> List[dict]:
        """Generate actionable recommendations based on channel performance"""
        recommendations = []

        for channel, metrics in performance.items():
            if metrics["sent"] < 100:
                recommendations.append({
                    "channel": channel,
                    "type": "data",
                    "message": f"Increase {channel} volume for better learning (only {metrics['sent']} sent)"
                })
                continue

            if metrics["open_rate"] < 0.15:
                recommendations.append({
                    "channel": channel,
                    "type": "improve",
                    "message": f"Low {channel} open rate ({metrics['open_rate']:.1%}). Review subject lines and send times."
                })

            if metrics["unsubscribe_rate"] > 0.02:
                recommendations.append({
                    "channel": channel,
                    "type": "warning",
                    "message": f"High {channel} unsubscribe rate ({metrics['unsubscribe_rate']:.2%}). Review frequency and content."
                })

            if metrics["conversion_rate"] > 0.05:
                recommendations.append({
                    "channel": channel,
                    "type": "success",
                    "message": f"Strong {channel} conversion rate ({metrics['conversion_rate']:.2%}). Increase allocation."
                })

        return recommendations[:10]

    async def optimize_channel_mix(
        self,
        session: AsyncSession,
        target_guests: int = 1000
    ) -> dict:
        """
        Optimize channel mix for a set of guests using learned preferences
        Returns recommended distribution
        """
        channel_counts = {ch: 0 for ch in self.CHANNELS}

        try:
            guests = await session.exec(
                select(Guest)
                .where(Guest.status != "Inactive")
                .limit(target_guests)
            )

            for guest in guests.all():
                recommendation = await self.get_best_channel(session, guest.id)
                channel = recommendation.get("recommended_channel", "email")
                channel_counts[channel] += 1

        except Exception as e:
            return {"error": str(e)}

        total = sum(channel_counts.values())

        return {
            "target_guests": target_guests,
            "analyzed_guests": total,
            "recommended_mix": {
                ch: {
                    "count": count,
                    "percentage": round(count / total * 100, 2) if total > 0 else 0
                }
                for ch, count in channel_counts.items()
            },
            "primary_channel": max(channel_counts, key=channel_counts.get),
            "generated_at": datetime.utcnow().isoformat()
        }


# Singleton instance
channel_learning_service = ChannelLearningService()
