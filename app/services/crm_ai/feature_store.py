"""
Feature Store for ML model features - Adapted for Glimmora Database
Extracts guest features from reservations, feedback, and engagement data
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from sqlmodel import select, func, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
import json

from app.models.reservations import Guest, Reservation, Booking
from app.models.crm import GuestFeedback, CRMGuestActivities, GuestStayHistory
from app.models.reviews import Review


class FeatureStore:
    """Feature store for extracting and caching ML features from Glimmora database"""

    @staticmethod
    async def get_guest_features(
        session: AsyncSession,
        guest_id: int,
    ) -> Dict[str, Any]:
        """Extract comprehensive guest features for ML models"""
        # Get guest
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        # Get all guest IDs that share this email (for unified profile)
        guest_ids_to_search = [guest_id]
        if guest.email:
            try:
                matching_result = await session.exec(
                    select(Guest.id).where(Guest.email == guest.email.lower().strip())
                )
                guest_ids_to_search = list(set([guest_id] + list(matching_result.all())))
            except Exception:
                pass

        # Booking/Reservation features
        try:
            reservations = (await session.exec(
                select(Reservation)
                .where(Reservation.guest_id.in_(guest_ids_to_search))
                .order_by(Reservation.arrival_date.desc())
            )).all()
        except Exception:
            reservations = []

        # Also try Booking table
        try:
            bookings = (await session.exec(
                select(Booking)
                .where(Booking.guest_id.in_(guest_ids_to_search))
                .order_by(Booking.arrival_date.desc())
            )).all()
        except Exception:
            bookings = []

        # Combine all bookings
        all_bookings = list(reservations) + list(bookings)

        # Calculate booking metrics
        total_bookings = len(all_bookings)
        confirmed_bookings = [b for b in all_bookings if getattr(b, 'status', '') in ['confirmed', 'checked_in', 'checked_out', 'booked']]
        cancelled_bookings = [b for b in all_bookings if getattr(b, 'status', '') == 'cancelled']

        # Calculate total spent
        total_spent = 0.0
        total_nights = 0
        for b in all_bookings:
            amount = getattr(b, 'total_price', 0) or getattr(b, 'total_amount', 0) or 0
            total_spent += float(amount)
            nights = getattr(b, 'nights', 0) or 0
            if nights == 0:
                arrival = getattr(b, 'arrival_date', None)
                departure = getattr(b, 'departure_date', None)
                if arrival and departure:
                    nights = (departure - arrival).days
            total_nights += nights

        # Recency (days since last booking)
        recency_days = 999
        if all_bookings:
            last_booking = all_bookings[0]
            last_date = getattr(last_booking, 'arrival_date', None) or getattr(last_booking, 'created_at', None)
            if last_date:
                if hasattr(last_date, 'replace'):
                    try:
                        recency_days = (datetime.utcnow().date() - last_date).days if hasattr(last_date, 'days') else (datetime.utcnow() - last_date.replace(tzinfo=None)).days
                    except:
                        recency_days = (datetime.utcnow().date() - last_date).days

        # Frequency (bookings per year)
        days_since_first = 365
        if guest.created_at:
            try:
                days_since_first = (datetime.utcnow() - guest.created_at.replace(tzinfo=None)).days
            except:
                days_since_first = (datetime.utcnow() - guest.created_at).days
        frequency = (total_bookings / max(days_since_first, 1)) * 365 if days_since_first > 0 else 0

        # Average booking value
        avg_booking_value = total_spent / max(total_bookings, 1)

        # Cancellation rate
        cancellation_rate = len(cancelled_bookings) / max(total_bookings, 1)

        # Get feedback/sentiment data
        avg_sentiment = 0.0
        recent_engagements = 0
        try:
            # Check for feedback
            feedback_result = await session.exec(
                select(GuestFeedback)
                .where(
                    and_(
                        GuestFeedback.guest_id.in_(guest_ids_to_search),
                        GuestFeedback.created_at >= datetime.utcnow() - timedelta(days=90)
                    )
                )
            )
            feedbacks = feedback_result.all()
            recent_engagements = len(feedbacks)

            # Calculate average sentiment from feedback ratings
            ratings = [f.guest_satisfaction_after or 3 for f in feedbacks if f.guest_satisfaction_after]
            if ratings:
                avg_sentiment = (sum(ratings) / len(ratings) - 3) / 2  # Normalize to -1 to 1
        except Exception:
            pass

        # Get CRM activities count
        try:
            activities_result = await session.exec(
                select(func.count(CRMGuestActivities.id))
                .where(
                    and_(
                        CRMGuestActivities.guest_id.in_(guest_ids_to_search),
                        CRMGuestActivities.timestamp >= datetime.utcnow() - timedelta(days=90)
                    )
                )
            )
            activity_count = activities_result.one_or_none() or 0
            recent_engagements += activity_count
        except Exception:
            pass

        # Get review sentiment
        try:
            reviews_result = await session.exec(
                select(Review)
                .where(Review.guest_id.in_(guest_ids_to_search))
            )
            reviews = reviews_result.all()
            if reviews:
                review_sentiments = [r.sentiment_score or 0 for r in reviews if hasattr(r, 'sentiment_score')]
                if review_sentiments:
                    avg_sentiment = sum(review_sentiments) / len(review_sentiments)
        except Exception:
            pass

        # Last engagement days
        last_engagement_days = recency_days

        # Features dictionary
        features = {
            # Basic
            "guest_id": guest_id,
            "guest_name": f"{guest.first_name} {guest.last_name}",
            "email": guest.email,
            "vip_status": guest.vip_status or False,
            "loyalty_tier": guest.loyalty_tier or "member",
            "days_since_registration": days_since_first,
            "age_days": days_since_first,

            # Booking features
            "total_bookings": total_bookings,
            "confirmed_bookings": len(confirmed_bookings),
            "cancelled_bookings": len(cancelled_bookings),
            "cancellation_rate": cancellation_rate,
            "recency_days": recency_days,
            "booking_frequency": frequency,
            "avg_nights_per_stay": total_nights / max(len(confirmed_bookings), 1),
            "total_nights": total_nights,

            # Monetary features
            "total_spent": total_spent,
            "avg_booking_value": avg_booking_value,

            # Engagement features
            "recent_engagements_90d": recent_engagements,
            "last_engagement_days": last_engagement_days,

            # Sentiment features
            "avg_sentiment_90d": avg_sentiment,
        }

        return features

    @staticmethod
    async def get_all_guests_features(
        session: AsyncSession,
        limit: int = 1000,
        min_bookings: int = 0
    ) -> List[Dict[str, Any]]:
        """Get features for all guests (for batch predictions)"""
        # Get all active guests
        guests = (await session.exec(
            select(Guest)
            .where(Guest.status != "Inactive")
            .limit(limit)
        )).all()

        features_list = []
        for guest in guests:
            try:
                features = await FeatureStore.get_guest_features(session, guest.id)
                if features.get("total_bookings", 0) >= min_bookings:
                    features_list.append(features)
            except Exception as e:
                print(f"Error getting features for guest {guest.id}: {e}")
                continue

        return features_list

    @staticmethod
    async def get_segment_features(
        session: AsyncSession,
        segment_criteria: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get features for guests matching segment criteria"""
        # Build query based on criteria
        query = select(Guest).where(Guest.status != "Inactive")

        if segment_criteria.get("vip_only"):
            query = query.where(Guest.vip_status == True)

        if segment_criteria.get("min_total_spent"):
            query = query.where(Guest.total_spent >= segment_criteria["min_total_spent"])

        if segment_criteria.get("loyalty_tier"):
            query = query.where(Guest.loyalty_tier == segment_criteria["loyalty_tier"])

        guests = (await session.exec(query.limit(500))).all()

        features_list = []
        for guest in guests:
            try:
                features = await FeatureStore.get_guest_features(session, guest.id)
                features_list.append(features)
            except Exception:
                continue

        return features_list
