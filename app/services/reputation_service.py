"""
Reputation AI Service
Integrated from Yadhu's Reputation AI System
Handles review analytics, response generation, and reputation management
"""
import logging
import asyncio
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from sqlalchemy import func, select, case, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import json
import os

from app.models.reviews import Review, SentimentTrends
from app.models.reputation import (
    ResponseDraft,
    ResponseDraftHistory,
    ReviewResponse,
    ReviewCategory,
    ReviewCategoryAssignment,
    TrendAlert,
    PerformanceGoal,
    RatingForecast,
    AutomationConfig,
    CompetitorBenchmark,
    ResponseTemplate
)
from app.models.reservations import Guest
from app.services.reputation_ai.openai_service import ReputationOpenAIService

logger = logging.getLogger(__name__)

# Initialize OpenAI service as a module-level singleton
_openai_service = None

def get_openai_service() -> ReputationOpenAIService:
    """Get or create the OpenAI service singleton"""
    global _openai_service
    if _openai_service is None:
        _openai_service = ReputationOpenAIService()
    return _openai_service


class ReputationService:
    """Main service for reputation management and analytics"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== DASHBOARD METRICS ====================

    async def get_reputation_dashboard(self) -> Dict[str, Any]:
        """Get comprehensive reputation dashboard data"""

        # Run all queries in parallel using asyncio.gather for better performance
        (
            metrics,
            source_breakdown,
            recent_reviews,
            trends,
            pending_responses,
            active_goals
        ) = await asyncio.gather(
            self._get_overall_metrics(),
            self._get_source_breakdown(),
            self._get_recent_reviews(limit=10),
            self._get_sentiment_trends(),
            self._get_pending_responses_count(),
            self._get_active_goals()
        )

        return {
            "metrics": metrics,
            "source_breakdown": source_breakdown,
            "recent_reviews": recent_reviews,
            "sentiment_trends": trends,
            "pending_responses": pending_responses,
            "active_goals": active_goals,
            "last_updated": datetime.utcnow().isoformat()
        }

    async def _get_overall_metrics(self) -> Dict[str, Any]:
        """Calculate overall reputation metrics"""

        # Total reviews and average rating
        stmt = select(
            func.count(Review.id).label("total_reviews"),
            func.avg(Review.overall_rating).label("avg_rating"),
            func.count(case((Review.response != None, 1))).label("responded_reviews")
        )

        result = await self.db.execute(stmt)
        row = result.one()

        total = row.total_reviews or 0
        avg = float(row.avg_rating or 0.0)
        responded = row.responded_reviews or 0
        response_rate = (responded / total * 100) if total > 0 else 0.0

        # Sentiment distribution
        stmt_sentiment = select(
            func.count(case((Review.sentiment == 'positive', 1))).label("positive"),
            func.count(case((Review.sentiment == 'neutral', 1))).label("neutral"),
            func.count(case((Review.sentiment == 'negative', 1))).label("negative")
        )
        result_sent = await self.db.execute(stmt_sentiment)
        sent_row = result_sent.one()

        # NPS calculation (simplified: positive - negative percentage)
        if total > 0:
            nps = ((sent_row.positive - sent_row.negative) / total) * 100
        else:
            nps = 0.0

        return {
            "total_reviews": total,
            "average_rating": round(avg, 2),
            "response_rate": round(response_rate, 1),
            "sentiment": {
                "positive": sent_row.positive or 0,
                "neutral": sent_row.neutral or 0,
                "negative": sent_row.negative or 0
            },
            "nps_score": round(nps, 1)
        }

    async def _get_source_breakdown(self) -> List[Dict[str, Any]]:
        """Get review breakdown by source"""
        stmt = select(
            Review.source,
            func.count(Review.id).label("count"),
            func.avg(Review.overall_rating).label("avg_rating")
        ).group_by(Review.source).order_by(text("count DESC"))

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "source": row.source,
                "count": row.count,
                "avg_rating": round(float(row.avg_rating or 0), 2)
            }
            for row in rows
        ]

    async def _get_recent_reviews(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most recent reviews"""
        stmt = select(Review).order_by(Review.review_date.desc()).limit(limit)
        result = await self.db.execute(stmt)
        reviews = result.scalars().all()

        return [
            {
                "id": r.id,
                "source": r.source,
                "rating": r.overall_rating,
                "title": r.title,
                "comment": r.comment[:200] + "..." if r.comment and len(r.comment) > 200 else r.comment,
                "sentiment": r.sentiment,
                "review_date": r.review_date.isoformat() if r.review_date else None,
                "has_response": bool(r.response)
            }
            for r in reviews
        ]

    async def _get_sentiment_trends(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get sentiment trends over time"""
        start_date = datetime.utcnow() - timedelta(days=days)

        stmt = select(SentimentTrends).where(
            SentimentTrends.date >= start_date.date()
        ).order_by(SentimentTrends.date)

        result = await self.db.execute(stmt)
        trends = result.scalars().all()

        return [
            {
                "date": t.date.isoformat(),
                "positive": t.positive_count,
                "neutral": t.neutral_count,
                "negative": t.negative_count,
                "score": t.sentiment_score
            }
            for t in trends
        ]

    async def _get_pending_responses_count(self) -> int:
        """Count reviews needing response"""
        stmt = select(func.count(Review.id)).where(Review.response == None)
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def _get_active_goals(self) -> List[Dict[str, Any]]:
        """Get active performance goals"""
        stmt = select(PerformanceGoal).where(
            PerformanceGoal.status == "active"
        ).order_by(PerformanceGoal.end_date)

        result = await self.db.execute(stmt)
        goals = result.scalars().all()

        return [
            {
                "id": g.id,
                "metric_type": g.metric_type,
                "baseline": g.baseline_value,
                "target": g.target_value,
                "current": g.current_value,
                "progress": g.progress_percentage,
                "end_date": g.end_date.isoformat() if g.end_date else None
            }
            for g in goals
        ]

    # ==================== REVIEW LISTING ====================

    async def get_all_reviews(
        self,
        page: int = 1,
        page_size: int = 20,
        source: Optional[str] = None,
        sentiment: Optional[str] = None,
        min_rating: Optional[float] = None,
        max_rating: Optional[float] = None,
        has_response: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        keyword: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get all reviews with filters and pagination"""
        offset = (page - 1) * page_size

        # Build filters
        filters = []
        if source and source != 'all':
            # Handle source name variations
            source_lower = source.lower()
            if source_lower in ['booking.com', 'booking']:
                filters.append(Review.source.in_(['booking_com', 'booking.com', 'Booking.com']))
            else:
                filters.append(func.lower(Review.source) == source_lower)
        if sentiment and sentiment != 'all':
            filters.append(Review.sentiment == sentiment)
        if min_rating is not None:
            filters.append(Review.overall_rating >= min_rating)
        if max_rating is not None:
            filters.append(Review.overall_rating <= max_rating)
        if has_response is not None:
            if has_response:
                filters.append(Review.response != None)
            else:
                filters.append(Review.response == None)
        if start_date:
            filters.append(Review.review_date >= start_date)
        if end_date:
            filters.append(Review.review_date <= end_date)
        if keyword:
            keyword_filter = f"%{keyword.lower()}%"
            filters.append(
                (func.lower(Review.title).like(keyword_filter)) |
                (func.lower(Review.comment).like(keyword_filter))
            )

        # Count total
        count_stmt = select(func.count(Review.id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Get reviews
        stmt = select(Review).order_by(Review.review_date.desc())
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.offset(offset).limit(page_size)

        result = await self.db.execute(stmt)
        reviews = result.scalars().all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "reviews": [
                {
                    "id": r.id,
                    "source": r.source,
                    "rating": r.overall_rating,
                    "title": r.title,
                    "comment": r.comment,
                    "pros": r.pros,
                    "cons": r.cons,
                    "sentiment": r.sentiment,
                    "review_date": r.review_date.isoformat() if r.review_date else None,
                    "has_response": bool(r.response),
                    "response": r.response,
                    "response_text": r.response,
                    "responded_at": r.responded_at.isoformat() if r.responded_at else None,
                    "response_date": r.responded_at.isoformat() if r.responded_at else None,
                    "responded_by": r.responded_by,
                    "guest_id": r.guest_id,
                    "is_verified": r.is_verified,
                    "helpful_count": r.helpful_count,
                    "cleanliness_rating": r.cleanliness_rating,
                    "service_rating": r.service_rating,
                    "location_rating": r.location_rating,
                    "value_rating": r.value_rating
                }
                for r in reviews
            ]
        }

    # ==================== REVIEW ANALYTICS ====================

    async def get_review_analytics(
        self,
        source: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get detailed review analytics with filters"""

        # Build list of filters
        filters = []
        if source:
            filters.append(Review.source == source)
        if start_date:
            filters.append(Review.review_date >= start_date)
        if end_date:
            filters.append(Review.review_date <= end_date)

        # Run all analytics queries in parallel
        async def get_rating_distribution():
            stmt_rating = select(
                func.round(Review.overall_rating).label("rating"),
                func.count(Review.id).label("count")
            )
            if filters:
                stmt_rating = stmt_rating.where(*filters)
            stmt_rating = stmt_rating.group_by(text("rating")).order_by(text("rating"))
            result_rating = await self.db.execute(stmt_rating)
            return {int(r.rating): r.count for r in result_rating.all() if r.rating}

        # Execute all queries in parallel
        (
            rating_dist,
            category_data,
            response_times,
            volume_trend
        ) = await asyncio.gather(
            get_rating_distribution(),
            self._get_category_breakdown(filters),
            self._get_response_time_analysis(filters),
            self._get_volume_trend(filters)
        )

        return {
            "rating_distribution": rating_dist,
            "category_breakdown": category_data,
            "response_times": response_times,
            "volume_trend": volume_trend
        }

    async def _get_category_breakdown(self, filters: List) -> List[Dict[str, Any]]:
        """Get review breakdown by category"""
        stmt = select(
            ReviewCategory.name,
            func.count(ReviewCategoryAssignment.id).label("count")
        ).join(
            ReviewCategoryAssignment,
            ReviewCategory.id == ReviewCategoryAssignment.category_id
        ).group_by(ReviewCategory.name).order_by(text("count DESC")).limit(10)

        try:
            result = await self.db.execute(stmt)
            return [{"category": r.name, "count": r.count} for r in result.all()]
        except Exception:
            return []

    async def _get_response_time_analysis(self, filters: List) -> Dict[str, Any]:
        """Analyze response times"""
        # For reviews that have been responded to
        stmt = select(
            func.avg(
                func.extract('epoch', Review.responded_at) -
                func.extract('epoch', Review.review_date)
            ).label("avg_seconds")
        )
        # Apply filters plus the responded_at condition
        all_filters = filters + [Review.responded_at != None]
        stmt = stmt.where(*all_filters)

        result = await self.db.execute(stmt)
        avg_seconds = result.scalar()
        avg_hours = (avg_seconds / 3600) if avg_seconds else 0.0

        return {
            "average_hours": round(avg_hours, 1),
            "target_hours": 24  # Target SLA
        }

    async def _get_volume_trend(self, filters: List, days: int = 30) -> List[Dict[str, Any]]:
        """Get review volume over time"""
        start_date = datetime.utcnow() - timedelta(days=days)

        # Use date() function for SQLite compatibility instead of date_trunc
        stmt = select(
            func.date(Review.review_date).label("date"),
            func.count(Review.id).label("count")
        )
        # Apply filters plus the date range
        all_filters = filters + [Review.review_date >= start_date]
        stmt = stmt.where(*all_filters).group_by(text("date")).order_by(text("date"))

        result = await self.db.execute(stmt)
        return [
            {
                "date": str(r.date) if r.date else None,
                "count": r.count
            }
            for r in result.all()
        ]

    # ==================== RESPONSE MANAGEMENT ====================

    async def get_reviews_needing_response(
        self,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """Get reviews that need responses, prioritized"""
        offset = (page - 1) * page_size

        # Count total
        count_stmt = select(func.count(Review.id)).where(Review.response == None)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Get reviews, prioritize by rating (lower = more urgent)
        stmt = select(Review).where(
            Review.response == None
        ).order_by(
            Review.overall_rating.asc(),  # Lower ratings first
            Review.review_date.desc()     # Then by recency
        ).offset(offset).limit(page_size)

        result = await self.db.execute(stmt)
        reviews = result.scalars().all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "reviews": [
                {
                    "id": r.id,
                    "source": r.source,
                    "rating": r.overall_rating,
                    "title": r.title,
                    "comment": r.comment,
                    "sentiment": r.sentiment,
                    "review_date": r.review_date.isoformat() if r.review_date else None,
                    "guest_id": r.guest_id,
                    "urgency": "high" if r.overall_rating and r.overall_rating <= 2 else (
                        "medium" if r.overall_rating and r.overall_rating <= 3 else "low"
                    )
                }
                for r in reviews
            ]
        }

    async def generate_response_draft(
        self,
        review_id: int,
        tone: str = "professional",
        include_resolution: bool = False
    ) -> Dict[str, Any]:
        """Generate AI response draft for a review"""

        # Get the review
        stmt = select(Review).where(Review.id == review_id)
        result = await self.db.execute(stmt)
        review = result.scalar_one_or_none()

        if not review:
            raise ValueError(f"Review {review_id} not found")

        # Generate response based on review content (returns full result dict)
        ai_result = await self._generate_ai_response(review, tone)
        draft_text = ai_result.get("response_text", "")
        confidence_score = ai_result.get("confidence", 0.85)
        suggestions = ai_result.get("suggestions", [])
        model_used = ai_result.get("model", "unknown")

        # Create draft record
        draft = ResponseDraft(
            review_id=review_id,
            draft_text=draft_text,
            status="pending",
            tone=tone,
            confidence_score=confidence_score
        )

        self.db.add(draft)
        await self.db.commit()
        await self.db.refresh(draft)

        return {
            "id": draft.id,
            "review_id": review_id,
            "draft_text": draft_text,
            "tone": tone,
            "status": "pending",
            "confidence_score": confidence_score,
            "suggestions": suggestions,
            "model": model_used,
            "generated_at": ai_result.get("generated_at")
        }

    async def _generate_ai_response(self, review: Review, tone: str) -> Dict[str, Any]:
        """Generate AI-powered response using OpenAI. Returns full result dict."""
        openai_service = get_openai_service()

        # Prepare review data for OpenAI service
        review_data = {
            "rating": review.overall_rating,
            "comment": review.comment or "",
            "title": review.title or "",
            "source": review.source or "direct",
            "sentiment": review.sentiment or "neutral"
        }

        # Get guest name if available
        guest_name = None
        if review.guest_id:
            try:
                guest_result = await self.db.execute(
                    select(Guest).where(Guest.id == review.guest_id)
                )
                guest = guest_result.scalar_one_or_none()
                if guest:
                    guest_name = guest.full_name or guest.first_name
            except Exception as e:
                logger.warning(f"Could not fetch guest name: {e}")

        # Generate response using OpenAI
        try:
            result = await openai_service.generate_response(
                review=review_data,
                tone=tone,
                guest_name=guest_name,
                hotel_name="Glimmora"
            )
            logger.info(f"OpenAI response generated successfully using model: {result.get('model', 'unknown')}")
            return result
        except Exception as e:
            logger.error(f"OpenAI response generation failed: {e}")
            fallback_text = await self._get_fallback_response(review)
            return {
                "response_text": fallback_text,
                "confidence": 0.70,
                "suggestions": ["Response generated using fallback template - OpenAI unavailable"],
                "model": "template_fallback",
                "tone_used": tone
            }

    async def _get_fallback_response(self, review: Review) -> str:
        """Fallback template response when OpenAI is unavailable.

        Fetches templates from ResponseTemplate database table.
        Falls back to hardcoded templates if no database template exists.
        """
        # Determine sentiment based on rating
        if review.overall_rating and review.overall_rating >= 4:
            sentiment = "positive"
        elif review.overall_rating and review.overall_rating >= 3:
            sentiment = "neutral"
        else:
            sentiment = "negative"

        # Try to fetch template from database
        try:
            result = await self.db.execute(
                select(ResponseTemplate).where(
                    ResponseTemplate.sentiment == sentiment,
                    ResponseTemplate.is_active == True
                ).order_by(ResponseTemplate.is_default.desc()).limit(1)
            )
            db_template = result.scalar_one_or_none()

            if db_template:
                # Use database template with placeholder replacement
                template_text = db_template.content
                try:
                    response = template_text.format(
                        guest_name="Valued Guest",
                        hotel_name="Glimmora",
                        review_date=datetime.utcnow().strftime("%B %d, %Y"),
                        contact_email="info@glimmora.com",
                        manager_name="The Management"
                    )
                    logger.info(f"Using database fallback template id={db_template.id} for sentiment={sentiment}")
                    return response
                except KeyError as e:
                    logger.warning(f"Template placeholder error: {e}, using template as-is")
                    return template_text
        except Exception as e:
            logger.warning(f"Failed to fetch fallback template from database: {e}")

        # Hardcoded fallback templates
        greeting = "Dear Guest"

        if sentiment == "positive":
            return f"""{greeting},

Thank you so much for taking the time to share your wonderful feedback! We are thrilled to hear that you enjoyed your stay with us.

Your kind words mean a lot to our team, and we are glad that we could provide you with a memorable experience. We look forward to welcoming you back soon!

Warm regards,
The Glimmora Team"""
        elif sentiment == "neutral":
            return f"""{greeting},

Thank you for sharing your feedback about your recent stay. We appreciate you taking the time to let us know about your experience.

We are constantly working to improve our services, and your comments help us do just that. We would love the opportunity to exceed your expectations on your next visit.

Best regards,
The Glimmora Team"""
        else:
            return f"""{greeting},

Thank you for bringing this to our attention. We sincerely apologize that your experience did not meet your expectations.

We take all feedback seriously and are actively working to address the concerns you've raised. We would appreciate the opportunity to make things right and hope you'll give us another chance to provide you with the exceptional service you deserve.

Please feel free to reach out to us directly so we can discuss this further.

With apologies,
The Glimmora Team"""

    async def approve_and_publish_response(
        self,
        draft_id: int,
        editor_id: int,
        final_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """Approve a draft and publish it as the official response"""

        # Get draft
        stmt = select(ResponseDraft).where(ResponseDraft.id == draft_id)
        result = await self.db.execute(stmt)
        draft = result.scalar_one_or_none()

        if not draft:
            raise ValueError(f"Draft {draft_id} not found")

        response_text = final_text or draft.draft_text
        published_at = datetime.utcnow()

        # Update review with response
        review_stmt = select(Review).where(Review.id == draft.review_id)
        review_result = await self.db.execute(review_stmt)
        review = review_result.scalar_one_or_none()

        if review:
            review.response = response_text
            review.responded_by = editor_id
            review.responded_at = published_at

        # Update draft status
        draft.status = "approved"
        draft.current_stage = "ready"
        draft.updated_at = published_at

        # Create history record if text was changed
        if final_text and final_text != draft.draft_text:
            history = ResponseDraftHistory(
                draft_id=draft_id,
                editor_id=editor_id,
                previous_text=draft.draft_text,
                new_text=final_text,
                change_reason="Manual edit before approval"
            )
            self.db.add(history)

        # Create or update ReviewResponse record for tracking published responses
        existing_response_stmt = select(ReviewResponse).where(ReviewResponse.review_id == draft.review_id)
        existing_response_result = await self.db.execute(existing_response_stmt)
        existing_response = existing_response_result.scalar_one_or_none()

        if existing_response:
            # Update existing response
            existing_response.response_text = response_text
            existing_response.published_at = published_at
            existing_response.published_by = editor_id
        else:
            # Create new ReviewResponse record
            review_response = ReviewResponse(
                review_id=draft.review_id,
                response_text=response_text,
                published_at=published_at,
                published_by=editor_id
            )
            self.db.add(review_response)

        await self.db.commit()

        return {
            "success": True,
            "message": "Response published successfully",
            "review_id": draft.review_id,
            "draft_id": draft_id,
            "response_text": response_text,
            "published_at": published_at.isoformat()
        }

    # ==================== TREND ANALYSIS ====================

    async def detect_trends(self, days: int = 14) -> List[Dict[str, Any]]:
        """Detect sentiment and rating trends"""
        start_date = datetime.utcnow() - timedelta(days=days)

        # Calculate current period metrics
        stmt_current = select(
            func.count(Review.id).label("count"),
            func.avg(Review.overall_rating).label("avg_rating"),
            func.count(case((Review.sentiment == 'negative', 1))).label("negative_count")
        ).where(Review.review_date >= start_date)

        current = (await self.db.execute(stmt_current)).one()

        # Calculate previous period metrics
        prev_start = start_date - timedelta(days=days)
        stmt_prev = select(
            func.count(Review.id).label("count"),
            func.avg(Review.overall_rating).label("avg_rating"),
            func.count(case((Review.sentiment == 'negative', 1))).label("negative_count")
        ).where(
            Review.review_date >= prev_start,
            Review.review_date < start_date
        )

        previous = (await self.db.execute(stmt_prev)).one()

        trends = []

        # Rating trend
        if current.avg_rating and previous.avg_rating:
            rating_change = float(current.avg_rating - previous.avg_rating)
            trends.append({
                "type": "rating",
                "direction": "up" if rating_change > 0.1 else ("down" if rating_change < -0.1 else "stable"),
                "change": round(rating_change, 2),
                "current_value": round(float(current.avg_rating), 2),
                "previous_value": round(float(previous.avg_rating), 2)
            })

        # Volume trend
        if current.count and previous.count:
            volume_change = ((current.count - previous.count) / previous.count * 100) if previous.count > 0 else 0
            trends.append({
                "type": "volume",
                "direction": "up" if volume_change > 10 else ("down" if volume_change < -10 else "stable"),
                "change_percent": round(volume_change, 1),
                "current_value": current.count,
                "previous_value": previous.count
            })

        # Negative sentiment trend
        if current.count > 0 and previous.count > 0:
            current_neg_pct = (current.negative_count / current.count * 100)
            prev_neg_pct = (previous.negative_count / previous.count * 100) if previous.count > 0 else 0
            neg_change = current_neg_pct - prev_neg_pct

            if neg_change > 5:  # Alert if negative reviews increased by 5%+
                trends.append({
                    "type": "negative_spike",
                    "direction": "up",
                    "change_percent": round(neg_change, 1),
                    "current_percent": round(current_neg_pct, 1),
                    "alert": True
                })

        return trends

    # ==================== COMPETITOR BENCHMARKING ====================

    async def get_competitor_benchmarks(self) -> List[Dict[str, Any]]:
        """Get competitor comparison data"""
        stmt = select(CompetitorBenchmark).order_by(CompetitorBenchmark.captured_at.desc())
        result = await self.db.execute(stmt)
        benchmarks = result.scalars().all()

        return [
            {
                "competitor": b.competitor_name,
                "source": b.source,
                "their_rating": b.rating,
                "our_rating": b.our_rating,
                "gap": b.rating_gap,
                "their_reviews": b.review_count,
                "captured_at": b.captured_at.isoformat() if b.captured_at else None
            }
            for b in benchmarks
        ]

    # ==================== PERFORMANCE GOALS ====================

    async def get_goals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all performance goals, optionally filtered by status."""
        stmt = select(PerformanceGoal).order_by(PerformanceGoal.created_at.desc())

        if status:
            stmt = stmt.where(PerformanceGoal.status == status)

        result = await self.db.execute(stmt)
        goals = result.scalars().all()

        return [
            {
                "id": g.id,
                "metric_type": g.metric_type,
                "baseline_value": g.baseline_value,
                "target_value": g.target_value,
                "current_value": g.current_value,
                "progress_percentage": g.progress_percentage,
                "status": g.status,
                "start_date": g.start_date.isoformat() if g.start_date else None,
                "end_date": g.end_date.isoformat() if g.end_date else None,
                "created_at": g.created_at.isoformat() if g.created_at else None
            }
            for g in goals
        ]

    async def create_goal(
        self,
        metric_type: str,
        target_value: float,
        start_date: datetime,
        end_date: datetime,
        created_by: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create a new performance goal"""

        # Calculate baseline from current metrics
        if metric_type == "rating":
            stmt = select(func.avg(Review.overall_rating))
            baseline = (await self.db.execute(stmt)).scalar() or 0.0
        elif metric_type == "response_rate":
            stmt = select(
                func.count(case((Review.response != None, 1))),
                func.count(Review.id)
            )
            result = (await self.db.execute(stmt)).one()
            baseline = (result[0] / result[1] * 100) if result[1] > 0 else 0.0
        else:
            baseline = 0.0

        goal = PerformanceGoal(
            metric_type=metric_type,
            baseline_value=float(baseline),
            target_value=target_value,
            current_value=float(baseline),
            start_date=start_date.date(),
            end_date=end_date.date(),
            status="active",
            progress_percentage=0.0,
            created_by=created_by
        )

        self.db.add(goal)
        await self.db.commit()
        await self.db.refresh(goal)

        return {
            "id": goal.id,
            "metric_type": goal.metric_type,
            "baseline": goal.baseline_value,
            "target": goal.target_value,
            "start_date": goal.start_date.isoformat(),
            "end_date": goal.end_date.isoformat()
        }

    async def update_goal_progress(self, goal_id: int, manual_value: Optional[float] = None) -> Dict[str, Any]:
        """
        Update progress for a goal.

        Args:
            goal_id: ID of the goal to update
            manual_value: Optional manual current_value. If provided, uses this instead of calculating from database.

        Returns:
            Dict with updated goal info
        """
        stmt = select(PerformanceGoal).where(PerformanceGoal.id == goal_id)
        result = await self.db.execute(stmt)
        goal = result.scalar_one_or_none()

        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        # Use manual value if provided, otherwise calculate from database
        if manual_value is not None:
            current = manual_value
        elif goal.metric_type == "rating":
            stmt = select(func.avg(Review.overall_rating))
            current = (await self.db.execute(stmt)).scalar() or 0.0
        elif goal.metric_type == "response_rate":
            stmt = select(
                func.count(case((Review.response != None, 1))),
                func.count(Review.id)
            )
            result = (await self.db.execute(stmt)).one()
            current = (result[0] / result[1] * 100) if result[1] > 0 else 0.0
        else:
            current = goal.current_value or 0.0

        goal.current_value = float(current)

        # Calculate progress
        if goal.target_value != goal.baseline_value:
            progress = ((current - goal.baseline_value) / (goal.target_value - goal.baseline_value)) * 100
            goal.progress_percentage = max(0, min(100, progress))

        # Check if achieved
        if goal.progress_percentage >= 100:
            goal.status = "achieved"
        elif datetime.utcnow().date() > goal.end_date:
            goal.status = "expired"

        goal.updated_at = datetime.utcnow()
        await self.db.commit()

        return {
            "id": goal.id,
            "current_value": goal.current_value,
            "progress": goal.progress_percentage,
            "status": goal.status
        }

    async def delete_goal(self, goal_id: int) -> None:
        """Delete a performance goal"""
        stmt = select(PerformanceGoal).where(PerformanceGoal.id == goal_id)
        result = await self.db.execute(stmt)
        goal = result.scalar_one_or_none()

        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        await self.db.delete(goal)
        await self.db.commit()

    async def toggle_goal_status(self, goal_id: int) -> Dict[str, Any]:
        """Toggle goal between active and deactivated status"""
        stmt = select(PerformanceGoal).where(PerformanceGoal.id == goal_id)
        result = await self.db.execute(stmt)
        goal = result.scalar_one_or_none()

        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        # Toggle status
        if goal.status == "deactivated":
            goal.status = "active"
        else:
            goal.status = "deactivated"

        goal.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(goal)

        return {
            "id": goal.id,
            "status": goal.status,
            "message": f"Goal {'activated' if goal.status == 'active' else 'deactivated'} successfully"
        }

    async def update_goal(self, goal_id: int, **kwargs) -> Dict[str, Any]:
        """Update a performance goal"""
        stmt = select(PerformanceGoal).where(PerformanceGoal.id == goal_id)
        result = await self.db.execute(stmt)
        goal = result.scalar_one_or_none()

        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        # Update fields
        if "target_value" in kwargs and kwargs["target_value"] is not None:
            goal.target_value = kwargs["target_value"]
        if "start_date" in kwargs and kwargs["start_date"] is not None:
            goal.start_date = kwargs["start_date"].date() if hasattr(kwargs["start_date"], 'date') else kwargs["start_date"]
        if "end_date" in kwargs and kwargs["end_date"] is not None:
            goal.end_date = kwargs["end_date"].date() if hasattr(kwargs["end_date"], 'date') else kwargs["end_date"]

        # Recalculate progress
        if goal.target_value != goal.baseline_value:
            progress = ((goal.current_value - goal.baseline_value) / (goal.target_value - goal.baseline_value)) * 100
            goal.progress_percentage = max(0, min(100, progress))

        goal.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(goal)

        return {
            "id": goal.id,
            "metric_type": goal.metric_type,
            "baseline_value": goal.baseline_value,
            "target_value": goal.target_value,
            "current_value": goal.current_value,
            "start_date": goal.start_date.isoformat(),
            "end_date": goal.end_date.isoformat(),
            "progress_percentage": goal.progress_percentage,
            "status": goal.status
        }

    # ==================== RESPONSE TEMPLATES ====================

    async def get_templates(
        self,
        tone: Optional[str] = None,
        sentiment: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get response templates with optional filtering"""
        stmt = select(ResponseTemplate).where(ResponseTemplate.is_active == True)

        if tone:
            stmt = stmt.where(ResponseTemplate.tone == tone)
        if sentiment:
            stmt = stmt.where(ResponseTemplate.sentiment == sentiment)

        stmt = stmt.order_by(ResponseTemplate.is_default.desc(), ResponseTemplate.name)
        result = await self.db.execute(stmt)
        templates = result.scalars().all()

        return [
            {
                "id": t.id,
                "name": t.name,
                "content": t.content,
                "tone": t.tone,
                "sentiment": t.sentiment,
                "is_default": t.is_default,
                "is_active": t.is_active,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None
            }
            for t in templates
        ]

    async def create_template(
        self,
        name: str,
        content: str,
        tone: str = "professional",
        sentiment: str = "positive",
        is_default: bool = False,
        created_by: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create a new response template"""
        template = ResponseTemplate(
            name=name,
            content=content,
            tone=tone,
            sentiment=sentiment,
            is_default=is_default,
            is_active=True
        )

        self.db.add(template)
        await self.db.commit()
        await self.db.refresh(template)

        return {
            "id": template.id,
            "name": template.name,
            "content": template.content,
            "tone": template.tone,
            "sentiment": template.sentiment,
            "is_default": template.is_default,
            "is_active": template.is_active,
            "created_at": template.created_at.isoformat() if template.created_at else None
        }

    async def update_template(self, template_id: int, **kwargs) -> Dict[str, Any]:
        """Update an existing response template"""
        stmt = select(ResponseTemplate).where(ResponseTemplate.id == template_id)
        result = await self.db.execute(stmt)
        template = result.scalar_one_or_none()

        if not template:
            raise ValueError(f"Template {template_id} not found")

        for key, value in kwargs.items():
            if hasattr(template, key) and value is not None:
                setattr(template, key, value)

        template.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(template)

        return {
            "id": template.id,
            "name": template.name,
            "content": template.content,
            "tone": template.tone,
            "sentiment": template.sentiment,
            "is_default": template.is_default,
            "is_active": template.is_active,
            "updated_at": template.updated_at.isoformat() if template.updated_at else None
        }

    async def delete_template(self, template_id: int) -> None:
        """Soft delete a response template"""
        stmt = select(ResponseTemplate).where(ResponseTemplate.id == template_id)
        result = await self.db.execute(stmt)
        template = result.scalar_one_or_none()

        if not template:
            raise ValueError(f"Template {template_id} not found")

        template.is_active = False
        template.updated_at = datetime.utcnow()
        await self.db.commit()
