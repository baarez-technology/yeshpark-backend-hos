"""
Alert Service for Reputation Management
Detects trends, manages alerts, and creates work orders for systemic issues.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, func, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reviews import Review, SentimentTrends
from app.models.reputation import (
    TrendAlert,
    TrendWorkOrder,
    ReviewCategory,
    ReviewCategoryAssignment
)

logger = logging.getLogger(__name__)


class AlertService:
    """Manage reputation alerts and trend detection"""

    def __init__(
        self,
        db: AsyncSession,
        openai_service: Optional["ReputationOpenAIService"] = None
    ):
        """
        Initialize AlertService.

        Args:
            db: Database session
            openai_service: Optional OpenAI service for RCA generation
        """
        self.db = db
        self.openai_service = openai_service

    async def detect_negative_spike(
        self,
        threshold_percent: float = 5.0,
        lookback_days: int = 14,
        comparison_days: int = 14
    ) -> List[Dict[str, Any]]:
        """
        Detect if negative reviews have spiked compared to the previous period.

        Args:
            threshold_percent: Minimum percentage increase to trigger alert (default 5%)
            lookback_days: Number of days to analyze for current period
            comparison_days: Number of days for the comparison period

        Returns:
            List of detected negative spikes by category
        """
        now = datetime.utcnow()
        current_start = now - timedelta(days=lookback_days)
        prev_start = current_start - timedelta(days=comparison_days)
        prev_end = current_start

        spikes = []

        # Get categories
        categories_result = await self.db.execute(
            select(ReviewCategory).where(ReviewCategory.is_active == True)
        )
        categories = categories_result.scalars().all()

        # Check overall negative spike first
        overall_spike = await self._check_negative_spike_period(
            current_start=current_start,
            current_end=now,
            prev_start=prev_start,
            prev_end=prev_end,
            threshold_percent=threshold_percent
        )

        if overall_spike:
            spikes.append({
                "type": "overall",
                "category_id": None,
                "category_name": "Overall",
                **overall_spike
            })

        # Check by category
        for category in categories:
            cat_spike = await self._check_category_negative_spike(
                category_id=category.id,
                category_name=category.name,
                current_start=current_start,
                current_end=now,
                prev_start=prev_start,
                prev_end=prev_end,
                threshold_percent=threshold_percent
            )

            if cat_spike:
                spikes.append(cat_spike)

        return spikes

    async def detect_rating_drop(
        self,
        threshold: float = 0.2,
        lookback_days: int = 30,
        comparison_days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Detect if overall rating has dropped compared to the previous period.

        Args:
            threshold: Minimum rating drop to trigger alert (default 0.2)
            lookback_days: Number of days for current period
            comparison_days: Number of days for comparison period

        Returns:
            List of detected rating drops by source
        """
        now = datetime.utcnow()
        current_start = now - timedelta(days=lookback_days)
        prev_start = current_start - timedelta(days=comparison_days)
        prev_end = current_start

        drops = []

        # Overall rating drop
        overall_drop = await self._check_rating_drop_period(
            current_start=current_start,
            current_end=now,
            prev_start=prev_start,
            prev_end=prev_end,
            threshold=threshold
        )

        if overall_drop:
            drops.append({
                "source": "overall",
                **overall_drop
            })

        # By source
        sources_result = await self.db.execute(
            select(Review.source).distinct()
        )
        sources = [r[0] for r in sources_result.all() if r[0]]

        for source in sources:
            source_drop = await self._check_rating_drop_period(
                current_start=current_start,
                current_end=now,
                prev_start=prev_start,
                prev_end=prev_end,
                threshold=threshold,
                source=source
            )

            if source_drop:
                drops.append({
                    "source": source,
                    **source_drop
                })

        return drops

    async def create_alert(
        self,
        alert_type: str,
        category_id: Optional[int],
        data: Dict[str, Any]
    ) -> TrendAlert:
        """
        Create a new trend alert.

        Args:
            alert_type: Type of alert (negative_spike, rating_drop, volume_increase)
            category_id: Optional category ID (can be None for overall alerts)
            data: Alert data including severity, counts, etc.

        Returns:
            Created TrendAlert record
        """
        # Check for duplicate active alerts
        existing_stmt = select(TrendAlert).where(
            TrendAlert.alert_type == alert_type,
            TrendAlert.status == "active"
        )
        if category_id:
            existing_stmt = existing_stmt.where(TrendAlert.category_id == category_id)

        existing = await self.db.execute(existing_stmt)
        if existing.scalar_one_or_none():
            logger.info(f"Active alert already exists for {alert_type}/{category_id}")
            # Return the existing alert after updating it
            existing_alert = (await self.db.execute(existing_stmt)).scalar_one()
            existing_alert.issue_count = data.get("issue_count", existing_alert.issue_count)
            existing_alert.severity_score = data.get("severity_score", existing_alert.severity_score)
            existing_alert.end_date = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(existing_alert)
            return existing_alert

        # If no category_id provided, use a default or create without
        # For the model, we need a valid category_id, so get or create a default
        if not category_id:
            default_cat = await self._get_or_create_default_category()
            category_id = default_cat.id

        alert = TrendAlert(
            category_id=category_id,
            alert_type=alert_type,
            start_date=data.get("start_date", datetime.utcnow() - timedelta(days=14)),
            end_date=data.get("end_date", datetime.utcnow()),
            issue_count=data.get("issue_count", 0),
            severity_score=data.get("severity_score", 0.5),
            status="active"
        )

        # Generate RCA if OpenAI is available
        if self.openai_service and self.openai_service.is_enabled:
            try:
                rca_data = await self.openai_service.generate_rca({
                    "category": data.get("category_name", "General"),
                    "issue_count": data.get("issue_count", 0),
                    "severity": "high" if data.get("severity_score", 0) > 0.7 else "medium",
                    "sample_reviews": data.get("sample_reviews", []),
                    "time_period": f"last {data.get('lookback_days', 14)} days"
                })
                alert.rca_analysis = rca_data
            except Exception as e:
                logger.warning(f"Failed to generate RCA for alert: {e}")

        self.db.add(alert)
        await self.db.commit()
        await self.db.refresh(alert)

        logger.info(f"Created new alert: {alert.id} ({alert_type})")
        return alert

    async def get_active_alerts(
        self,
        alert_type: Optional[str] = None,
        category_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all active alerts with optional filtering.

        Args:
            alert_type: Optional filter by alert type
            category_id: Optional filter by category

        Returns:
            List of active alerts with details
        """
        stmt = select(TrendAlert, ReviewCategory).join(
            ReviewCategory,
            TrendAlert.category_id == ReviewCategory.id
        ).where(TrendAlert.status == "active")

        if alert_type:
            stmt = stmt.where(TrendAlert.alert_type == alert_type)
        if category_id:
            stmt = stmt.where(TrendAlert.category_id == category_id)

        stmt = stmt.order_by(TrendAlert.severity_score.desc())

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "id": row[0].id,
                "alert_type": row[0].alert_type,
                "category_id": row[0].category_id,
                "category_name": row[1].name,
                "start_date": row[0].start_date.isoformat() if row[0].start_date else None,
                "end_date": row[0].end_date.isoformat() if row[0].end_date else None,
                "issue_count": row[0].issue_count,
                "severity_score": row[0].severity_score,
                "status": row[0].status,
                "rca_analysis": row[0].rca_analysis,
                "created_at": row[0].created_at.isoformat() if row[0].created_at else None
            }
            for row in rows
        ]

    async def acknowledge_alert(
        self,
        alert_id: int,
        user_id: int
    ) -> Optional[TrendAlert]:
        """
        Acknowledge an alert (mark as being worked on).

        Args:
            alert_id: ID of the alert
            user_id: ID of the user acknowledging

        Returns:
            Updated TrendAlert or None if not found
        """
        stmt = select(TrendAlert).where(TrendAlert.id == alert_id)
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            logger.warning(f"Alert {alert_id} not found for acknowledgment")
            return None

        alert.status = "acknowledged"
        alert.resolved_by = user_id

        await self.db.commit()
        await self.db.refresh(alert)

        logger.info(f"Alert {alert_id} acknowledged by user {user_id}")
        return alert

    async def resolve_alert(
        self,
        alert_id: int,
        user_id: int,
        notes: str
    ) -> Optional[TrendAlert]:
        """
        Resolve an alert with notes.

        Args:
            alert_id: ID of the alert
            user_id: ID of the user resolving
            notes: Resolution notes

        Returns:
            Updated TrendAlert or None if not found
        """
        stmt = select(TrendAlert).where(TrendAlert.id == alert_id)
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            logger.warning(f"Alert {alert_id} not found for resolution")
            return None

        alert.status = "resolved"
        alert.resolved_by = user_id
        alert.resolved_at = datetime.utcnow()
        alert.resolution_notes = notes

        await self.db.commit()
        await self.db.refresh(alert)

        logger.info(f"Alert {alert_id} resolved by user {user_id}")
        return alert

    async def dismiss_alert(
        self,
        alert_id: int,
        user_id: int
    ) -> Optional[TrendAlert]:
        """
        Dismiss an alert (false positive or not actionable).

        Args:
            alert_id: ID of the alert
            user_id: ID of the user dismissing

        Returns:
            Updated TrendAlert or None if not found
        """
        stmt = select(TrendAlert).where(TrendAlert.id == alert_id)
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            logger.warning(f"Alert {alert_id} not found for dismissal")
            return None

        alert.status = "dismissed"
        alert.resolved_by = user_id
        alert.resolved_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(alert)

        logger.info(f"Alert {alert_id} dismissed by user {user_id}")
        return alert

    async def create_work_order_from_alert(
        self,
        alert_id: int,
        assigned_to: Optional[int] = None,
        priority: Optional[str] = None
    ) -> Optional[TrendWorkOrder]:
        """
        Create a work order from an alert.

        Args:
            alert_id: ID of the alert
            assigned_to: Optional staff ID to assign to
            priority: Optional priority override

        Returns:
            Created TrendWorkOrder or None if alert not found
        """
        # Get alert with category
        stmt = select(TrendAlert, ReviewCategory).join(
            ReviewCategory,
            TrendAlert.category_id == ReviewCategory.id
        ).where(TrendAlert.id == alert_id)

        result = await self.db.execute(stmt)
        row = result.first()

        if not row:
            logger.warning(f"Alert {alert_id} not found for work order creation")
            return None

        alert, category = row

        # Check if work order already exists for this alert
        existing_wo = await self.db.execute(
            select(TrendWorkOrder).where(TrendWorkOrder.trend_alert_id == alert_id)
        )
        if existing_wo.scalar_one_or_none():
            logger.info(f"Work order already exists for alert {alert_id}")
            return existing_wo.scalar_one()

        # Determine priority based on severity
        if not priority:
            if alert.severity_score >= 0.8:
                priority = "critical"
            elif alert.severity_score >= 0.6:
                priority = "high"
            elif alert.severity_score >= 0.4:
                priority = "medium"
            else:
                priority = "low"

        # Build description
        description = f"""Trend Alert: {alert.alert_type.replace('_', ' ').title()}

Category: {category.name}
Issue Count: {alert.issue_count}
Severity Score: {alert.severity_score}
Period: {alert.start_date.strftime('%Y-%m-%d')} to {alert.end_date.strftime('%Y-%m-%d')}

"""
        if alert.rca_analysis:
            rca = alert.rca_analysis
            if rca.get("root_causes"):
                description += "Root Causes:\n"
                for cause in rca["root_causes"]:
                    description += f"- {cause}\n"
                description += "\n"

            if rca.get("recommendations"):
                description += "Recommendations:\n"
                for rec in rca["recommendations"]:
                    description += f"- {rec}\n"

        work_order = TrendWorkOrder(
            trend_alert_id=alert_id,
            category_id=alert.category_id,
            title=f"{alert.alert_type.replace('_', ' ').title()}: {category.name}",
            description=description.strip(),
            assigned_to=assigned_to,
            status="open",
            priority=priority
        )

        self.db.add(work_order)

        # Update alert status
        alert.status = "acknowledged"

        await self.db.commit()
        await self.db.refresh(work_order)

        logger.info(f"Created work order {work_order.id} from alert {alert_id}")
        return work_order

    async def get_alert_summary(self) -> Dict[str, Any]:
        """
        Get summary of all alerts for dashboard.

        Returns:
            Dictionary with alert counts and recent alerts
        """
        # Count by status
        status_counts = {}
        for status in ["active", "acknowledged", "resolved", "dismissed"]:
            count_result = await self.db.execute(
                select(func.count(TrendAlert.id)).where(TrendAlert.status == status)
            )
            status_counts[status] = count_result.scalar() or 0

        # Count by type (active only)
        type_counts = {}
        for alert_type in ["negative_spike", "rating_drop", "volume_increase"]:
            count_result = await self.db.execute(
                select(func.count(TrendAlert.id)).where(
                    TrendAlert.status == "active",
                    TrendAlert.alert_type == alert_type
                )
            )
            type_counts[alert_type] = count_result.scalar() or 0

        # Get recent alerts
        recent = await self.get_active_alerts()

        return {
            "total_active": status_counts.get("active", 0),
            "total_acknowledged": status_counts.get("acknowledged", 0),
            "total_resolved": status_counts.get("resolved", 0),
            "by_type": type_counts,
            "recent_alerts": recent[:5]
        }

    async def run_all_detections(
        self,
        auto_create_alerts: bool = True
    ) -> Dict[str, Any]:
        """
        Run all trend detection algorithms.

        Args:
            auto_create_alerts: Whether to automatically create alerts

        Returns:
            Summary of all detected issues
        """
        results = {
            "negative_spikes": [],
            "rating_drops": [],
            "alerts_created": 0
        }

        # Detect negative spikes
        spikes = await self.detect_negative_spike()
        results["negative_spikes"] = spikes

        if auto_create_alerts:
            for spike in spikes:
                if spike.get("current_negative_pct", 0) > 10:  # Only alert for significant spikes
                    await self.create_alert(
                        alert_type="negative_spike",
                        category_id=spike.get("category_id"),
                        data={
                            "category_name": spike.get("category_name", "Overall"),
                            "issue_count": spike.get("current_negative_count", 0),
                            "severity_score": min(1.0, spike.get("change_percent", 0) / 20),
                            "lookback_days": 14
                        }
                    )
                    results["alerts_created"] += 1

        # Detect rating drops
        drops = await self.detect_rating_drop()
        results["rating_drops"] = drops

        if auto_create_alerts:
            for drop in drops:
                if drop.get("change", 0) < -0.3:  # Only alert for significant drops
                    default_cat = await self._get_or_create_default_category()
                    await self.create_alert(
                        alert_type="rating_drop",
                        category_id=default_cat.id,
                        data={
                            "category_name": drop.get("source", "Overall"),
                            "issue_count": drop.get("current_count", 0),
                            "severity_score": min(1.0, abs(drop.get("change", 0)) / 0.5),
                            "lookback_days": 30
                        }
                    )
                    results["alerts_created"] += 1

        return results

    # ==================== PRIVATE METHODS ====================

    async def _check_negative_spike_period(
        self,
        current_start: datetime,
        current_end: datetime,
        prev_start: datetime,
        prev_end: datetime,
        threshold_percent: float,
        source: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Check for negative spike in a period"""
        # Current period stats
        current_stmt = select(
            func.count(Review.id).label("total"),
            func.count(case((Review.sentiment == "negative", 1))).label("negative")
        ).where(
            Review.review_date >= current_start,
            Review.review_date <= current_end
        )
        if source:
            current_stmt = current_stmt.where(Review.source == source)

        current_result = (await self.db.execute(current_stmt)).one()

        # Previous period stats
        prev_stmt = select(
            func.count(Review.id).label("total"),
            func.count(case((Review.sentiment == "negative", 1))).label("negative")
        ).where(
            Review.review_date >= prev_start,
            Review.review_date < prev_end
        )
        if source:
            prev_stmt = prev_stmt.where(Review.source == source)

        prev_result = (await self.db.execute(prev_stmt)).one()

        # Calculate percentages
        current_total = current_result.total or 0
        current_negative = current_result.negative or 0
        prev_total = prev_result.total or 0
        prev_negative = prev_result.negative or 0

        if current_total == 0:
            return None

        current_pct = (current_negative / current_total * 100)
        prev_pct = (prev_negative / prev_total * 100) if prev_total > 0 else 0

        change = current_pct - prev_pct

        if change >= threshold_percent:
            return {
                "current_total": current_total,
                "current_negative_count": current_negative,
                "current_negative_pct": round(current_pct, 1),
                "previous_total": prev_total,
                "previous_negative_count": prev_negative,
                "previous_negative_pct": round(prev_pct, 1),
                "change_percent": round(change, 1),
                "is_spike": True
            }

        return None

    async def _check_category_negative_spike(
        self,
        category_id: int,
        category_name: str,
        current_start: datetime,
        current_end: datetime,
        prev_start: datetime,
        prev_end: datetime,
        threshold_percent: float
    ) -> Optional[Dict[str, Any]]:
        """Check for negative spike in a specific category"""
        # Current period - reviews with this category assignment
        current_stmt = select(
            func.count(Review.id).label("total"),
            func.count(case((Review.sentiment == "negative", 1))).label("negative")
        ).join(
            ReviewCategoryAssignment,
            Review.id == ReviewCategoryAssignment.review_id
        ).where(
            ReviewCategoryAssignment.category_id == category_id,
            Review.review_date >= current_start,
            Review.review_date <= current_end
        )

        current_result = (await self.db.execute(current_stmt)).one()

        # Previous period
        prev_stmt = select(
            func.count(Review.id).label("total"),
            func.count(case((Review.sentiment == "negative", 1))).label("negative")
        ).join(
            ReviewCategoryAssignment,
            Review.id == ReviewCategoryAssignment.review_id
        ).where(
            ReviewCategoryAssignment.category_id == category_id,
            Review.review_date >= prev_start,
            Review.review_date < prev_end
        )

        prev_result = (await self.db.execute(prev_stmt)).one()

        current_total = current_result.total or 0
        current_negative = current_result.negative or 0
        prev_total = prev_result.total or 0
        prev_negative = prev_result.negative or 0

        if current_total < 3:  # Not enough data
            return None

        current_pct = (current_negative / current_total * 100)
        prev_pct = (prev_negative / prev_total * 100) if prev_total > 0 else 0

        change = current_pct - prev_pct

        if change >= threshold_percent:
            return {
                "type": "category",
                "category_id": category_id,
                "category_name": category_name,
                "current_total": current_total,
                "current_negative_count": current_negative,
                "current_negative_pct": round(current_pct, 1),
                "previous_total": prev_total,
                "previous_negative_count": prev_negative,
                "previous_negative_pct": round(prev_pct, 1),
                "change_percent": round(change, 1),
                "is_spike": True
            }

        return None

    async def _check_rating_drop_period(
        self,
        current_start: datetime,
        current_end: datetime,
        prev_start: datetime,
        prev_end: datetime,
        threshold: float,
        source: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Check for rating drop in a period"""
        # Current period average
        current_stmt = select(
            func.count(Review.id).label("count"),
            func.avg(Review.overall_rating).label("avg_rating")
        ).where(
            Review.review_date >= current_start,
            Review.review_date <= current_end
        )
        if source:
            current_stmt = current_stmt.where(Review.source == source)

        current_result = (await self.db.execute(current_stmt)).one()

        # Previous period average
        prev_stmt = select(
            func.count(Review.id).label("count"),
            func.avg(Review.overall_rating).label("avg_rating")
        ).where(
            Review.review_date >= prev_start,
            Review.review_date < prev_end
        )
        if source:
            prev_stmt = prev_stmt.where(Review.source == source)

        prev_result = (await self.db.execute(prev_stmt)).one()

        current_count = current_result.count or 0
        current_avg = float(current_result.avg_rating or 0)
        prev_count = prev_result.count or 0
        prev_avg = float(prev_result.avg_rating or 0)

        if current_count < 5 or prev_count < 5:  # Not enough data
            return None

        change = current_avg - prev_avg

        if change <= -threshold:  # Negative change means drop
            return {
                "current_count": current_count,
                "current_rating": round(current_avg, 2),
                "previous_count": prev_count,
                "previous_rating": round(prev_avg, 2),
                "change": round(change, 2),
                "is_drop": True
            }

        return None

    async def _get_or_create_default_category(self) -> ReviewCategory:
        """Get or create a default category for alerts without specific category"""
        stmt = select(ReviewCategory).where(ReviewCategory.name == "General")
        result = await self.db.execute(stmt)
        category = result.scalar_one_or_none()

        if not category:
            category = ReviewCategory(
                name="General",
                description="General category for overall alerts",
                is_active=True
            )
            self.db.add(category)
            await self.db.commit()
            await self.db.refresh(category)

        return category
