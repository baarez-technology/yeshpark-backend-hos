"""
Frequency Cap Service
Manages communication frequency limits to prevent guest fatigue
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import json

from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.reservations import Guest
from app.models.crm import CRMGuestActivities, Campaigns
from app.models.crm_ai import CampaignRecipient


class ChannelLimits:
    """Default limits per channel"""
    EMAIL = 4  # Max per week
    SMS = 2  # Max per week
    WHATSAPP = 3  # Max per week
    PUSH = 5  # Max per week
    CALL = 1  # Max per week


class FrequencyCapService:
    """Service for managing communication frequency caps"""

    # Default caps by channel (messages per week)
    DEFAULT_WEEKLY_CAPS = {
        "email": 4,
        "sms": 2,
        "whatsapp": 3,
        "push": 5,
        "call": 1,
        "in_app": 7
    }

    # Default caps by message type
    DEFAULT_TYPE_CAPS = {
        "promotional": 2,
        "transactional": 10,  # Higher limit for important messages
        "service": 5,
        "loyalty": 2,
        "win_back": 1,
        "survey": 1
    }

    # Rest periods (hours) after certain message types
    REST_PERIODS = {
        "promotional": 48,  # 2 days before another promo
        "win_back": 168,  # 7 days between win-back attempts
        "survey": 336,  # 14 days between surveys
        "complaint_response": 24,  # 1 day to follow up
    }

    # VIP multipliers (VIPs can receive more communications)
    VIP_MULTIPLIERS = {
        "member": 1.0,
        "bronze": 1.0,
        "silver": 1.1,
        "gold": 1.2,
        "platinum": 1.3,
        "diamond": 1.5
    }

    def __init__(self):
        self.enforce_caps = True
        self.cooldown_hours = 12  # Minimum hours between any messages

    async def check_can_contact(
        self,
        session: AsyncSession,
        guest_id: int,
        channel: str,
        message_type: str = "promotional"
    ) -> dict:
        """
        Check if a guest can be contacted via specified channel
        Returns: {can_contact, reason, next_available, stats}
        """
        # Get guest info
        guest = await session.get(Guest, guest_id)
        if not guest:
            return {
                "can_contact": False,
                "reason": "Guest not found",
                "next_available": None
            }

        # Check if guest has opted out
        if await self._is_opted_out(session, guest_id, channel):
            return {
                "can_contact": False,
                "reason": f"Guest has opted out of {channel} communications",
                "next_available": None,
                "opt_out": True
            }

        # Get tier-based cap adjustment
        tier = guest.loyalty_tier or "member"
        tier_multiplier = self.VIP_MULTIPLIERS.get(tier, 1.0)

        # Get contact history
        history = await self._get_contact_history(
            session, guest_id, channel, days=7
        )

        # Calculate effective caps
        channel_cap = int(self.DEFAULT_WEEKLY_CAPS.get(channel, 4) * tier_multiplier)
        type_cap = int(self.DEFAULT_TYPE_CAPS.get(message_type, 2) * tier_multiplier)

        # Check weekly channel cap
        channel_count = len(history)
        if channel_count >= channel_cap:
            next_available = await self._calculate_next_available(
                history, channel_cap
            )
            return {
                "can_contact": False,
                "reason": f"Weekly {channel} cap reached ({channel_count}/{channel_cap})",
                "next_available": next_available.isoformat() if next_available else None,
                "current_count": channel_count,
                "cap": channel_cap
            }

        # Check message type cap
        type_history = await self._get_contact_history(
            session, guest_id, channel, days=7, message_type=message_type
        )
        type_count = len(type_history)
        if type_count >= type_cap:
            return {
                "can_contact": False,
                "reason": f"Weekly {message_type} message cap reached ({type_count}/{type_cap})",
                "next_available": None,
                "current_count": type_count,
                "cap": type_cap
            }

        # Check cooldown period
        last_contact = await self._get_last_contact(session, guest_id)
        if last_contact:
            hours_since = (datetime.utcnow() - last_contact).total_seconds() / 3600
            if hours_since < self.cooldown_hours:
                next_available = last_contact + timedelta(hours=self.cooldown_hours)
                return {
                    "can_contact": False,
                    "reason": f"Cooldown period active ({hours_since:.1f}/{self.cooldown_hours}h)",
                    "next_available": next_available.isoformat(),
                    "hours_remaining": round(self.cooldown_hours - hours_since, 1)
                }

        # Check rest period for message type
        rest_period = self.REST_PERIODS.get(message_type)
        if rest_period:
            last_type_contact = await self._get_last_contact_by_type(
                session, guest_id, message_type
            )
            if last_type_contact:
                hours_since = (datetime.utcnow() - last_type_contact).total_seconds() / 3600
                if hours_since < rest_period:
                    next_available = last_type_contact + timedelta(hours=rest_period)
                    return {
                        "can_contact": False,
                        "reason": f"Rest period for {message_type} messages ({hours_since:.1f}/{rest_period}h)",
                        "next_available": next_available.isoformat(),
                        "hours_remaining": round(rest_period - hours_since, 1)
                    }

        # All checks passed
        return {
            "can_contact": True,
            "reason": "All frequency checks passed",
            "weekly_contacts": {
                "channel": channel_count,
                "channel_cap": channel_cap,
                "type": type_count,
                "type_cap": type_cap
            },
            "tier_multiplier": tier_multiplier
        }

    async def _is_opted_out(
        self,
        session: AsyncSession,
        guest_id: int,
        channel: str
    ) -> bool:
        """Check if guest has opted out of a channel"""
        try:
            # Check for unsubscribe activity
            opt_out = await session.exec(
                select(CRMGuestActivities)
                .where(
                    and_(
                        CRMGuestActivities.guest_id == guest_id,
                        CRMGuestActivities.activity_type == f"opt_out_{channel}"
                    )
                )
                .order_by(CRMGuestActivities.timestamp.desc())
                .limit(1)
            )
            opt_out_record = opt_out.first()

            if opt_out_record:
                # Check if they've opted back in
                opt_in = await session.exec(
                    select(CRMGuestActivities)
                    .where(
                        and_(
                            CRMGuestActivities.guest_id == guest_id,
                            CRMGuestActivities.activity_type == f"opt_in_{channel}",
                            CRMGuestActivities.timestamp > opt_out_record.timestamp
                        )
                    )
                    .limit(1)
                )
                return not opt_in.first()

            return False
        except Exception:
            return False

    async def _get_contact_history(
        self,
        session: AsyncSession,
        guest_id: int,
        channel: str,
        days: int = 7,
        message_type: Optional[str] = None
    ) -> List[dict]:
        """Get contact history for a guest"""
        since_date = datetime.utcnow() - timedelta(days=days)
        history = []

        # Check CampaignRecipient
        try:
            query = select(CampaignRecipient).where(
                and_(
                    CampaignRecipient.guest_id == guest_id,
                    CampaignRecipient.channel == channel,
                    CampaignRecipient.sent_at >= since_date,
                    CampaignRecipient.sent_at.isnot(None)
                )
            )

            recipients = await session.exec(query)
            for r in recipients.all():
                history.append({
                    "type": "campaign",
                    "sent_at": r.sent_at,
                    "campaign_id": r.campaign_id
                })
        except Exception:
            pass

        # Check CRM activities for direct communications
        try:
            activity_query = select(CRMGuestActivities).where(
                and_(
                    CRMGuestActivities.guest_id == guest_id,
                    CRMGuestActivities.activity_type.in_([
                        f"{channel}_sent",
                        f"outbound_{channel}",
                        "communication_sent"
                    ]),
                    CRMGuestActivities.timestamp >= since_date
                )
            )

            activities = await session.exec(activity_query)
            for a in activities.all():
                history.append({
                    "type": "activity",
                    "sent_at": a.timestamp,
                    "activity_id": a.id
                })
        except Exception:
            pass

        # Sort by date
        history.sort(key=lambda x: x.get("sent_at") or datetime.min, reverse=True)

        return history

    async def _get_last_contact(
        self,
        session: AsyncSession,
        guest_id: int
    ) -> Optional[datetime]:
        """Get timestamp of last contact to guest via any channel"""
        try:
            # Check campaign recipients
            last_campaign = await session.exec(
                select(CampaignRecipient.sent_at)
                .where(
                    and_(
                        CampaignRecipient.guest_id == guest_id,
                        CampaignRecipient.sent_at.isnot(None)
                    )
                )
                .order_by(CampaignRecipient.sent_at.desc())
                .limit(1)
            )
            campaign_date = last_campaign.first()

            # Check activities
            last_activity = await session.exec(
                select(CRMGuestActivities.timestamp)
                .where(
                    and_(
                        CRMGuestActivities.guest_id == guest_id,
                        CRMGuestActivities.activity_category == "communication"
                    )
                )
                .order_by(CRMGuestActivities.timestamp.desc())
                .limit(1)
            )
            activity_date = last_activity.first()

            dates = [d for d in [campaign_date, activity_date] if d]
            return max(dates) if dates else None

        except Exception:
            return None

    async def _get_last_contact_by_type(
        self,
        session: AsyncSession,
        guest_id: int,
        message_type: str
    ) -> Optional[datetime]:
        """Get timestamp of last contact of specific type"""
        try:
            result = await session.exec(
                select(CRMGuestActivities.timestamp)
                .where(
                    and_(
                        CRMGuestActivities.guest_id == guest_id,
                        CRMGuestActivities.activity_type.contains(message_type)
                    )
                )
                .order_by(CRMGuestActivities.timestamp.desc())
                .limit(1)
            )
            return result.first()
        except Exception:
            return None

    async def _calculate_next_available(
        self,
        history: List[dict],
        cap: int
    ) -> Optional[datetime]:
        """Calculate when the next contact slot will be available"""
        if not history:
            return datetime.utcnow()

        # Sort by date, oldest first
        sorted_history = sorted(
            history,
            key=lambda x: x.get("sent_at") or datetime.min
        )

        # Find the oldest message in the cap window
        if len(sorted_history) >= cap:
            oldest_in_window = sorted_history[0].get("sent_at")
            if oldest_in_window:
                return oldest_in_window + timedelta(days=7)

        return datetime.utcnow()

    async def record_contact(
        self,
        session: AsyncSession,
        guest_id: int,
        channel: str,
        message_type: str,
        campaign_id: Optional[int] = None,
        reference_id: Optional[int] = None
    ) -> dict:
        """Record a contact for frequency tracking"""
        activity = CRMGuestActivities(
            guest_id=guest_id,
            activity_type=f"outbound_{channel}",
            activity_category="communication",
            description=f"{message_type.capitalize()} message sent via {channel}",
            sentiment="neutral",
            importance="low",
            timestamp=datetime.utcnow(),
            extra_data=json.dumps({
                "channel": channel,
                "message_type": message_type,
                "campaign_id": campaign_id,
                "reference_id": reference_id
            })
        )

        session.add(activity)
        await session.commit()

        return {
            "guest_id": guest_id,
            "channel": channel,
            "message_type": message_type,
            "recorded_at": datetime.utcnow().isoformat(),
            "activity_id": activity.id
        }

    async def get_guest_contact_summary(
        self,
        session: AsyncSession,
        guest_id: int,
        days: int = 30
    ) -> dict:
        """Get comprehensive contact summary for a guest"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        summary = {
            "guest_id": guest_id,
            "period_days": days,
            "channels": {},
            "opt_outs": [],
            "total_contacts": 0,
            "last_contact": None
        }

        # Get counts by channel
        for channel in self.DEFAULT_WEEKLY_CAPS.keys():
            history = await self._get_contact_history(
                session, guest_id, channel, days=days
            )
            summary["channels"][channel] = {
                "count": len(history),
                "weekly_cap": self.DEFAULT_WEEKLY_CAPS[channel],
                "can_contact": len(history) < self.DEFAULT_WEEKLY_CAPS[channel]
            }
            summary["total_contacts"] += len(history)

            if await self._is_opted_out(session, guest_id, channel):
                summary["opt_outs"].append(channel)

        # Get last contact
        last = await self._get_last_contact(session, guest_id)
        if last:
            summary["last_contact"] = last.isoformat()
            summary["hours_since_last"] = round(
                (datetime.utcnow() - last).total_seconds() / 3600, 1
            )

        return summary

    async def update_caps(
        self,
        session: AsyncSession,
        channel: str,
        new_cap: int
    ) -> dict:
        """Update frequency cap for a channel"""
        if channel not in self.DEFAULT_WEEKLY_CAPS:
            raise ValueError(f"Unknown channel: {channel}")

        old_cap = self.DEFAULT_WEEKLY_CAPS[channel]
        self.DEFAULT_WEEKLY_CAPS[channel] = new_cap

        return {
            "channel": channel,
            "old_cap": old_cap,
            "new_cap": new_cap,
            "updated_at": datetime.utcnow().isoformat()
        }

    async def opt_out_guest(
        self,
        session: AsyncSession,
        guest_id: int,
        channel: str,
        reason: str = "Guest requested"
    ) -> dict:
        """Record guest opt-out for a channel"""
        activity = CRMGuestActivities(
            guest_id=guest_id,
            activity_type=f"opt_out_{channel}",
            activity_category="preference",
            description=f"Guest opted out of {channel} communications",
            sentiment="neutral",
            importance="high",
            timestamp=datetime.utcnow(),
            extra_data=json.dumps({
                "channel": channel,
                "reason": reason
            })
        )

        session.add(activity)
        await session.commit()

        return {
            "guest_id": guest_id,
            "channel": channel,
            "status": "opted_out",
            "recorded_at": datetime.utcnow().isoformat()
        }

    async def opt_in_guest(
        self,
        session: AsyncSession,
        guest_id: int,
        channel: str
    ) -> dict:
        """Record guest opt-in for a channel"""
        activity = CRMGuestActivities(
            guest_id=guest_id,
            activity_type=f"opt_in_{channel}",
            activity_category="preference",
            description=f"Guest opted in to {channel} communications",
            sentiment="positive",
            importance="medium",
            timestamp=datetime.utcnow(),
            extra_data=json.dumps({"channel": channel})
        )

        session.add(activity)
        await session.commit()

        return {
            "guest_id": guest_id,
            "channel": channel,
            "status": "opted_in",
            "recorded_at": datetime.utcnow().isoformat()
        }

    async def get_fatigue_score(
        self,
        session: AsyncSession,
        guest_id: int
    ) -> dict:
        """
        Calculate communication fatigue score for a guest
        Higher score = more fatigued, reduce communications
        """
        fatigue_score = 0.0
        factors = []

        # Get recent contact volume
        total_7d = 0
        total_30d = 0

        for channel in self.DEFAULT_WEEKLY_CAPS.keys():
            history_7d = await self._get_contact_history(
                session, guest_id, channel, days=7
            )
            history_30d = await self._get_contact_history(
                session, guest_id, channel, days=30
            )

            total_7d += len(history_7d)
            total_30d += len(history_30d)

            # Check if cap is being approached
            cap = self.DEFAULT_WEEKLY_CAPS[channel]
            utilization = len(history_7d) / cap if cap > 0 else 0

            if utilization >= 0.8:
                fatigue_score += 15
                factors.append(f"High {channel} utilization ({len(history_7d)}/{cap})")

        # Overall volume factor
        if total_7d >= 10:
            fatigue_score += 25
            factors.append(f"High weekly contact volume ({total_7d})")
        elif total_7d >= 6:
            fatigue_score += 15
            factors.append(f"Moderate weekly contact volume ({total_7d})")

        if total_30d >= 30:
            fatigue_score += 20
            factors.append(f"High monthly contact volume ({total_30d})")

        # Check for unsubscribes/complaints
        try:
            complaints = await session.exec(
                select(func.count(CRMGuestActivities.id))
                .where(
                    and_(
                        CRMGuestActivities.guest_id == guest_id,
                        CRMGuestActivities.activity_type.in_([
                            "unsubscribed", "complaint", "spam_report"
                        ]),
                        CRMGuestActivities.timestamp >= datetime.utcnow() - timedelta(days=90)
                    )
                )
            )
            complaint_count = complaints.one() or 0
            if complaint_count > 0:
                fatigue_score += 30 * complaint_count
                factors.append(f"Recent complaints/unsubscribes ({complaint_count})")
        except Exception:
            pass

        # Check engagement rates
        try:
            # Get campaign metrics for this guest
            opens = await session.exec(
                select(func.count(CampaignRecipient.id))
                .where(
                    and_(
                        CampaignRecipient.guest_id == guest_id,
                        CampaignRecipient.opened_at.isnot(None),
                        CampaignRecipient.sent_at >= datetime.utcnow() - timedelta(days=30)
                    )
                )
            )
            open_count = opens.one() or 0

            sent = await session.exec(
                select(func.count(CampaignRecipient.id))
                .where(
                    and_(
                        CampaignRecipient.guest_id == guest_id,
                        CampaignRecipient.sent_at >= datetime.utcnow() - timedelta(days=30),
                        CampaignRecipient.sent_at.isnot(None)
                    )
                )
            )
            sent_count = sent.one() or 0

            if sent_count >= 5:
                open_rate = open_count / sent_count
                if open_rate < 0.1:
                    fatigue_score += 20
                    factors.append(f"Low engagement rate ({open_rate:.0%})")
                elif open_rate < 0.2:
                    fatigue_score += 10
                    factors.append(f"Moderate engagement rate ({open_rate:.0%})")

        except Exception:
            pass

        # Cap score at 100
        fatigue_score = min(100, fatigue_score)

        # Determine recommendation
        if fatigue_score >= 70:
            recommendation = "critical"
            recommendation_text = "Significantly reduce communications. Consider communication break."
        elif fatigue_score >= 50:
            recommendation = "high"
            recommendation_text = "Reduce communication frequency by 50%."
        elif fatigue_score >= 30:
            recommendation = "moderate"
            recommendation_text = "Monitor engagement and consider reducing frequency."
        else:
            recommendation = "low"
            recommendation_text = "Continue with normal communication schedule."

        return {
            "guest_id": guest_id,
            "fatigue_score": round(fatigue_score, 1),
            "fatigue_level": recommendation,
            "recommendation": recommendation_text,
            "factors": factors,
            "contact_summary": {
                "last_7_days": total_7d,
                "last_30_days": total_30d
            },
            "calculated_at": datetime.utcnow().isoformat()
        }


# Singleton instance
frequency_cap_service = FrequencyCapService()
