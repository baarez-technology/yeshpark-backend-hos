"""
OTA to Direct Booking Conversion Service
Identifies OTA guests and manages conversion campaigns
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import json

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.reservations import Guest, Reservation, Booking
from app.models.crm import Campaigns, CRMGuestActivities
from app.models.crm_ai import AIScore
from app.core.config import settings


class OTAConversionAttempt:
    """Track OTA conversion attempt"""
    def __init__(
        self,
        guest_id: int,
        offer_type: str,
        offer_value: float,
        channel: str
    ):
        self.guest_id = guest_id
        self.offer_type = offer_type
        self.offer_value = offer_value
        self.channel = channel
        self.sent_at = None
        self.opened_at = None
        self.clicked_at = None
        self.converted_at = None


class OTAConversionService:
    """Service for converting OTA guests to direct bookers"""

    OTA_CHANNELS = [
        "booking.com", "expedia", "hotels.com", "agoda",
        "trip.com", "trivago", "kayak", "priceline", "orbitz",
        "hotwire", "travelocity", "cheaptickets", "booking", "expedia_group"
    ]

    def __init__(self):
        self.min_conversion_probability = 0.3
        self.base_discount = 10.0
        self.openai_client = None

    def _get_openai_client(self):
        """Get or create OpenAI client"""
        if not self.openai_client and OPENAI_AVAILABLE and settings.openai_api_key:
            self.openai_client = openai.OpenAI(api_key=settings.openai_api_key)
        return self.openai_client

    async def identify_ota_guests(
        self,
        session: AsyncSession,
        limit: int = 100,
        min_stays: int = 1
    ) -> List[dict]:
        """
        Identify guests who booked through OTA channels
        Returns guests with their conversion probability and offer recommendations
        """
        # Query guests with OTA bookings
        ota_guests = []

        # Check Booking table (new schema)
        try:
            booking_result = await session.exec(
                select(Booking)
                .where(
                    Booking.booking_source.in_(self.OTA_CHANNELS) |
                    Booking.channel.in_(self.OTA_CHANNELS)
                )
                .order_by(Booking.created_at.desc())
            )
            ota_bookings = booking_result.all()
        except Exception:
            ota_bookings = []

        # Check Reservation table (legacy schema)
        try:
            reservation_result = await session.exec(
                select(Reservation)
                .where(Reservation.booking_source.in_(self.OTA_CHANNELS))
                .order_by(Reservation.created_at.desc())
            )
            ota_reservations = reservation_result.all()
        except Exception:
            ota_reservations = []

        # Collect unique guest IDs from OTA bookings
        guest_ids_with_ota = set()
        for booking in ota_bookings:
            guest_ids_with_ota.add(booking.guest_id)
        for reservation in ota_reservations:
            guest_ids_with_ota.add(reservation.guest_id)

        # Process each OTA guest
        processed_count = 0
        for guest_id in guest_ids_with_ota:
            if processed_count >= limit:
                break

            guest = await session.get(Guest, guest_id)
            if not guest:
                continue

            # Check if guest has any direct bookings (already converted)
            has_direct = await self._has_direct_booking(session, guest_id)
            if has_direct:
                continue  # Skip already converted guests

            # Get guest metrics
            metrics = await self._get_guest_metrics(session, guest_id)

            if metrics["total_stays"] < min_stays:
                continue

            # Calculate conversion probability
            conversion_prob = self.calculate_conversion_probability(
                total_stays=metrics["total_stays"],
                total_spend=metrics["total_spend"],
                health_score=metrics.get("health_score", 50),
                sentiment_score=metrics.get("sentiment_score", 0),
                days_since_last_stay=metrics["days_since_last_stay"]
            )

            if conversion_prob >= self.min_conversion_probability:
                # Determine recommended tier and offer
                tier = self._determine_tier_offer(metrics["total_spend"], conversion_prob)
                benefits = await self.get_direct_booking_benefits(tier)

                ota_guests.append({
                    "guest_id": guest_id,
                    "guest_name": f"{guest.first_name} {guest.last_name}",
                    "email": guest.email,
                    "phone": guest.phone,
                    "ota_source": metrics.get("primary_ota", "OTA"),
                    "total_ota_bookings": metrics["total_stays"],
                    "total_ota_spend": round(metrics["total_spend"], 2),
                    "days_since_last_stay": metrics["days_since_last_stay"],
                    "conversion_probability": round(conversion_prob, 3),
                    "recommended_tier": tier,
                    "recommended_discount": benefits["discount"],
                    "benefits": benefits["benefits"],
                    "priority": "high" if conversion_prob >= 0.6 else "medium"
                })
                processed_count += 1

        # Sort by conversion probability descending
        ota_guests.sort(key=lambda x: x["conversion_probability"], reverse=True)

        return ota_guests

    async def _has_direct_booking(
        self,
        session: AsyncSession,
        guest_id: int
    ) -> bool:
        """Check if guest has any direct bookings"""
        try:
            direct_booking = await session.exec(
                select(Booking)
                .where(
                    and_(
                        Booking.guest_id == guest_id,
                        Booking.booking_source == "direct"
                    )
                )
                .limit(1)
            )
            if direct_booking.first():
                return True

            direct_reservation = await session.exec(
                select(Reservation)
                .where(
                    and_(
                        Reservation.guest_id == guest_id,
                        Reservation.booking_source == "direct"
                    )
                )
                .limit(1)
            )
            return bool(direct_reservation.first())
        except Exception:
            return False

    async def _get_guest_metrics(
        self,
        session: AsyncSession,
        guest_id: int
    ) -> dict:
        """Get guest metrics for conversion calculation"""
        metrics = {
            "total_stays": 0,
            "total_spend": 0.0,
            "days_since_last_stay": 365,
            "health_score": 50,
            "sentiment_score": 0,
            "primary_ota": "OTA"
        }

        # Get booking metrics
        try:
            bookings = await session.exec(
                select(Booking)
                .where(Booking.guest_id == guest_id)
                .order_by(Booking.arrival_date.desc())
            )
            booking_list = bookings.all()

            if booking_list:
                metrics["total_stays"] = len(booking_list)
                metrics["total_spend"] = sum(b.total_price or 0 for b in booking_list)

                # Days since last stay
                last_booking = booking_list[0]
                if last_booking.arrival_date:
                    days_diff = (datetime.utcnow().date() - last_booking.arrival_date).days
                    metrics["days_since_last_stay"] = max(0, days_diff)

                # Primary OTA
                ota_sources = [b.booking_source for b in booking_list if b.booking_source in self.OTA_CHANNELS]
                if ota_sources:
                    metrics["primary_ota"] = max(set(ota_sources), key=ota_sources.count)

        except Exception:
            pass

        # Also check reservations
        try:
            reservations = await session.exec(
                select(Reservation)
                .where(Reservation.guest_id == guest_id)
                .order_by(Reservation.arrival_date.desc())
            )
            reservation_list = reservations.all()

            if reservation_list:
                metrics["total_stays"] += len(reservation_list)
                metrics["total_spend"] += sum(r.total_amount or 0 for r in reservation_list)

                if not booking_list and reservation_list:
                    last_res = reservation_list[0]
                    if last_res.arrival_date:
                        days_diff = (datetime.utcnow().date() - last_res.arrival_date).days
                        metrics["days_since_last_stay"] = min(
                            metrics["days_since_last_stay"],
                            max(0, days_diff)
                        )

        except Exception:
            pass

        # Get AI scores if available
        try:
            score_result = await session.exec(
                select(AIScore)
                .where(
                    and_(
                        AIScore.guest_id == guest_id,
                        AIScore.score_type == "health_score"
                    )
                )
                .order_by(AIScore.calculated_at.desc())
                .limit(1)
            )
            health_score = score_result.first()
            if health_score:
                metrics["health_score"] = health_score.score_value

            sentiment_result = await session.exec(
                select(AIScore)
                .where(
                    and_(
                        AIScore.guest_id == guest_id,
                        AIScore.score_type == "sentiment_score"
                    )
                )
                .order_by(AIScore.calculated_at.desc())
                .limit(1)
            )
            sentiment_score = sentiment_result.first()
            if sentiment_score:
                metrics["sentiment_score"] = sentiment_score.score_value

        except Exception:
            pass

        return metrics

    def calculate_conversion_probability(
        self,
        total_stays: int,
        total_spend: float,
        health_score: float,
        sentiment_score: float,
        days_since_last_stay: int
    ) -> float:
        """
        Calculate probability of converting OTA guest to direct
        Factors: loyalty potential, satisfaction, recency, value
        """
        # Base probability
        prob = 0.3

        # Repeat guest bonus (up to +20%)
        if total_stays >= 3:
            prob += 0.20
        elif total_stays >= 2:
            prob += 0.10

        # High spender bonus (up to +15%)
        if total_spend >= 5000:
            prob += 0.15
        elif total_spend >= 2000:
            prob += 0.10
        elif total_spend >= 1000:
            prob += 0.05

        # Health score bonus (up to +15%)
        if health_score >= 80:
            prob += 0.15
        elif health_score >= 60:
            prob += 0.10
        elif health_score >= 40:
            prob += 0.05

        # Sentiment bonus (up to +10%)
        if sentiment_score >= 0.5:
            prob += 0.10
        elif sentiment_score >= 0.2:
            prob += 0.05

        # Recency bonus (up to +10%)
        if days_since_last_stay <= 30:
            prob += 0.10
        elif days_since_last_stay <= 90:
            prob += 0.05

        # Recency penalty
        if days_since_last_stay > 365:
            prob -= 0.15
        elif days_since_last_stay > 180:
            prob -= 0.10

        return min(max(prob, 0.05), 0.95)

    def _determine_tier_offer(
        self,
        total_spend: float,
        conversion_prob: float
    ) -> str:
        """Determine appropriate tier offer based on guest value"""
        if total_spend >= 10000 or conversion_prob >= 0.8:
            return "diamond"
        elif total_spend >= 5000 or conversion_prob >= 0.7:
            return "platinum"
        elif total_spend >= 2500 or conversion_prob >= 0.6:
            return "gold"
        elif total_spend >= 1000 or conversion_prob >= 0.5:
            return "silver"
        else:
            return "bronze"

    async def generate_conversion_offer(
        self,
        session: AsyncSession,
        guest_id: int,
        use_ai: bool = True
    ) -> dict:
        """Generate personalized conversion offer for a guest"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        # Get guest metrics
        metrics = await self._get_guest_metrics(session, guest_id)

        # Calculate conversion probability
        conversion_prob = self.calculate_conversion_probability(
            total_stays=metrics["total_stays"],
            total_spend=metrics["total_spend"],
            health_score=metrics.get("health_score", 50),
            sentiment_score=metrics.get("sentiment_score", 0),
            days_since_last_stay=metrics["days_since_last_stay"]
        )

        # Determine tier and benefits
        tier = self._determine_tier_offer(metrics["total_spend"], conversion_prob)
        benefits = await self.get_direct_booking_benefits(tier)

        # Calculate personalized discount
        base_discount = benefits["discount"]

        # Bonus discount for high value or high probability guests
        bonus_discount = 0
        if metrics["total_spend"] >= 5000:
            bonus_discount += 2
        if conversion_prob >= 0.7:
            bonus_discount += 2
        if metrics["total_stays"] >= 3:
            bonus_discount += 1

        total_discount = min(base_discount + bonus_discount, 25)  # Cap at 25%

        # Generate personalized message
        guest_name = f"{guest.first_name} {guest.last_name}"
        offer_type = f"{tier.capitalize()} Member"

        if use_ai:
            message = await self._generate_ai_message(
                guest_name=guest_name,
                offer_type=offer_type,
                offer_value=total_discount,
                benefits=benefits["benefits"]
            )
        else:
            message = self._generate_template_message(
                guest_name=guest_name,
                offer_type=offer_type,
                offer_value=total_discount,
                benefits=benefits["benefits"]
            )

        # Generate subject line
        subject_lines = [
            f"Exclusive {total_discount}% Discount - Book Direct & Save!",
            f"{guest.first_name}, Unlock Your VIP Benefits Today!",
            f"Your Exclusive {tier.capitalize()} Member Offer Inside",
        ]

        return {
            "guest_id": guest_id,
            "guest_name": guest_name,
            "guest_email": guest.email,
            "conversion_probability": round(conversion_prob, 3),
            "offer": {
                "tier": tier,
                "discount_percentage": total_discount,
                "offer_type": offer_type,
                "benefits": benefits["benefits"],
                "valid_days": 30,
                "expiry_date": (datetime.utcnow() + timedelta(days=30)).isoformat()
            },
            "message": {
                "subject_lines": subject_lines,
                "body": message
            },
            "personalization": {
                "total_stays": metrics["total_stays"],
                "total_spend": round(metrics["total_spend"], 2),
                "primary_ota": metrics.get("primary_ota", "OTA"),
                "days_since_last_stay": metrics["days_since_last_stay"]
            },
            "generated_at": datetime.utcnow().isoformat()
        }

    async def _generate_ai_message(
        self,
        guest_name: str,
        offer_type: str,
        offer_value: float,
        benefits: List[str]
    ) -> str:
        """Use OpenAI to generate personalized conversion message"""
        client = self._get_openai_client()
        if not client:
            return self._generate_template_message(guest_name, offer_type, offer_value, benefits)

        benefits_text = ", ".join(benefits)
        prompt = f"""Generate a warm, personalized email message to convert a hotel guest from OTA booking to direct booking.

Guest Name: {guest_name}
Offer: {offer_value}% discount on direct bookings
Benefits: {benefits_text}

Requirements:
- Friendly and professional tone
- Highlight the exclusive benefits
- Create urgency without being pushy
- Keep it concise (max 150 words)
- Include a clear call-to-action
- Do not use excessive exclamation marks

Return only the email body text, no subject line."""

        try:
            response = client.chat.completions.create(
                model=settings.openai_model or "gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            # Fallback to template on error
            return self._generate_template_message(guest_name, offer_type, offer_value, benefits)

    def _generate_template_message(
        self, guest_name: str, offer_type: str, offer_value: float, benefits: List[str]
    ) -> str:
        """Fallback template message"""
        benefits_text = "\n".join([f"  * {b}" for b in benefits])

        return f"""Dear {guest_name},

We noticed you've been a valued guest through our booking partners, and we'd love to welcome you to our Direct Booking Program.

As a {offer_type}, you'll enjoy exclusive benefits not available through third-party sites:

{benefits_text}

Your exclusive offer: {offer_value:.0f}% OFF your next direct booking.

This special rate is reserved just for you and expires in 30 days. Simply book directly through our website or call us to claim your discount.

We look forward to welcoming you back soon.

Warm regards,
The Glimmora Team

P.S. Book direct and skip the middleman - your savings go straight to your experience."""

    async def send_conversion_offer(
        self,
        session: AsyncSession,
        guest_id: int,
        offer: dict,
        channel: str = "email"
    ) -> dict:
        """Send conversion offer to guest"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        # Create activity log for tracking
        activity = CRMGuestActivities(
            guest_id=guest_id,
            activity_type="ota_conversion_offer_sent",
            activity_category="communication",
            description=f"OTA conversion offer sent via {channel}",
            sentiment="positive",
            importance="high",
            timestamp=datetime.utcnow(),
            extra_data=json.dumps({
                "offer_tier": offer.get("offer", {}).get("tier"),
                "discount": offer.get("offer", {}).get("discount_percentage"),
                "channel": channel,
                "conversion_probability": offer.get("conversion_probability")
            })
        )

        session.add(activity)
        await session.commit()

        # In production, this would integrate with email/SMS service
        # For now, we return the tracking details
        return {
            "guest_id": guest_id,
            "channel": channel,
            "status": "queued",
            "offer_details": offer.get("offer"),
            "tracking_id": activity.id,
            "sent_at": datetime.utcnow().isoformat(),
            "message": f"Conversion offer queued for delivery via {channel}"
        }

    async def track_conversion_event(
        self,
        session: AsyncSession,
        attempt_id: int,
        event_type: str  # opened, clicked, converted
    ) -> None:
        """Track conversion funnel events"""
        # Get the activity record
        activity = await session.get(CRMGuestActivities, attempt_id)
        if not activity:
            return

        # Create tracking activity
        tracking_activity = CRMGuestActivities(
            guest_id=activity.guest_id,
            activity_type=f"ota_conversion_{event_type}",
            activity_category="engagement",
            description=f"OTA conversion offer {event_type}",
            sentiment="positive" if event_type == "converted" else "neutral",
            importance="high" if event_type == "converted" else "medium",
            timestamp=datetime.utcnow(),
            extra_data=json.dumps({
                "original_offer_id": attempt_id,
                "event_type": event_type
            })
        )

        session.add(tracking_activity)
        await session.commit()

    async def get_conversion_stats(self, session: AsyncSession) -> dict:
        """Get overall conversion statistics"""
        # Count OTA guests
        try:
            ota_guest_count = await session.exec(
                select(func.count(func.distinct(Booking.guest_id)))
                .where(Booking.booking_source.in_(self.OTA_CHANNELS))
            )
            total_ota_guests = ota_guest_count.one() or 0
        except Exception:
            total_ota_guests = 0

        # Count converted guests (have both OTA and direct)
        try:
            # This is a simplified count - in production would use more sophisticated query
            direct_guests = await session.exec(
                select(func.count(func.distinct(Booking.guest_id)))
                .where(Booking.booking_source == "direct")
            )
            total_direct_guests = direct_guests.one() or 0
        except Exception:
            total_direct_guests = 0

        # Count offers sent
        try:
            offers_sent = await session.exec(
                select(func.count(CRMGuestActivities.id))
                .where(CRMGuestActivities.activity_type == "ota_conversion_offer_sent")
            )
            total_offers_sent = offers_sent.one() or 0
        except Exception:
            total_offers_sent = 0

        # Count conversions tracked
        try:
            conversions = await session.exec(
                select(func.count(CRMGuestActivities.id))
                .where(CRMGuestActivities.activity_type == "ota_conversion_converted")
            )
            total_conversions = conversions.one() or 0
        except Exception:
            total_conversions = 0

        # Calculate rates
        conversion_rate = (total_conversions / total_offers_sent * 100) if total_offers_sent > 0 else 0

        return {
            "total_ota_guests": total_ota_guests,
            "total_direct_guests": total_direct_guests,
            "offers_sent": total_offers_sent,
            "conversions": total_conversions,
            "conversion_rate": round(conversion_rate, 2),
            "potential_conversions": max(0, total_ota_guests - total_conversions),
            "stats_as_of": datetime.utcnow().isoformat()
        }

    async def get_direct_booking_benefits(self, tier: str = "bronze") -> dict:
        """Get benefits for direct booking members by tier"""
        benefits = {
            "bronze": {
                "discount": 5,
                "benefits": [
                    "Best rate guarantee",
                    "Free WiFi upgrade",
                    "Early check-in (subject to availability)",
                    "Welcome drink on arrival"
                ]
            },
            "silver": {
                "discount": 8,
                "benefits": [
                    "All Bronze benefits",
                    "Room upgrade (subject to availability)",
                    "Late checkout until 2pm",
                    "10% F&B discount"
                ]
            },
            "gold": {
                "discount": 12,
                "benefits": [
                    "All Silver benefits",
                    "Guaranteed room upgrade",
                    "Late checkout until 4pm",
                    "15% F&B discount",
                    "Complimentary breakfast"
                ]
            },
            "platinum": {
                "discount": 16,
                "benefits": [
                    "All Gold benefits",
                    "Suite upgrade (subject to availability)",
                    "Late checkout until 6pm",
                    "20% spa discount",
                    "Airport transfer discount"
                ]
            },
            "diamond": {
                "discount": 20,
                "benefits": [
                    "All Platinum benefits",
                    "Guaranteed suite upgrade",
                    "24-hour checkout flexibility",
                    "Complimentary mini-bar",
                    "Personal concierge",
                    "Exclusive member events"
                ]
            }
        }
        return benefits.get(tier, benefits["bronze"])

    async def get_ota_revenue_analysis(
        self,
        session: AsyncSession,
        days: int = 365
    ) -> dict:
        """Analyze revenue by booking source to understand OTA impact"""
        since_date = datetime.utcnow() - timedelta(days=days)

        revenue_by_source = {}

        try:
            bookings = await session.exec(
                select(Booking)
                .where(Booking.created_at >= since_date)
            )
            for booking in bookings.all():
                source = booking.booking_source or "unknown"
                if source not in revenue_by_source:
                    revenue_by_source[source] = {
                        "bookings": 0,
                        "revenue": 0.0,
                        "avg_booking_value": 0.0
                    }
                revenue_by_source[source]["bookings"] += 1
                revenue_by_source[source]["revenue"] += booking.total_price or 0

        except Exception:
            pass

        # Calculate averages and OTA totals
        ota_revenue = 0.0
        ota_bookings = 0
        direct_revenue = 0.0
        direct_bookings = 0

        for source, data in revenue_by_source.items():
            if data["bookings"] > 0:
                data["avg_booking_value"] = round(data["revenue"] / data["bookings"], 2)

            if source in self.OTA_CHANNELS or source == "ota":
                ota_revenue += data["revenue"]
                ota_bookings += data["bookings"]
            elif source == "direct":
                direct_revenue += data["revenue"]
                direct_bookings += data["bookings"]

        total_revenue = ota_revenue + direct_revenue
        ota_percentage = (ota_revenue / total_revenue * 100) if total_revenue > 0 else 0

        return {
            "period_days": days,
            "revenue_by_source": revenue_by_source,
            "summary": {
                "ota_revenue": round(ota_revenue, 2),
                "ota_bookings": ota_bookings,
                "direct_revenue": round(direct_revenue, 2),
                "direct_bookings": direct_bookings,
                "ota_revenue_percentage": round(ota_percentage, 2),
                "direct_revenue_percentage": round(100 - ota_percentage, 2)
            },
            "recommendation": self._generate_revenue_recommendation(ota_percentage),
            "analyzed_at": datetime.utcnow().isoformat()
        }

    def _generate_revenue_recommendation(self, ota_percentage: float) -> str:
        """Generate recommendation based on OTA revenue percentage"""
        if ota_percentage >= 70:
            return "Critical: Over 70% revenue from OTAs. Prioritize direct booking campaigns immediately."
        elif ota_percentage >= 50:
            return "High OTA dependency. Implement aggressive OTA conversion and direct booking incentives."
        elif ota_percentage >= 30:
            return "Moderate OTA mix. Continue conversion efforts while maintaining OTA relationships."
        else:
            return "Healthy direct booking ratio. Maintain current strategies and optimize conversion funnel."


# Singleton instance
ota_conversion_service = OTAConversionService()
