"""
Alert Management API Routes
Reputation AI Module - Glimmora Hotel Management System
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user_optional, get_current_user
from app.models.user import User
from app.models.reputation import (
    TrendAlert,
    TrendWorkOrder,
    ReviewCategory,
    ReviewCategoryAssignment
)
from app.models.reviews import Review

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== PYDANTIC SCHEMAS ====================

class AcknowledgeAlertRequest(BaseModel):
    """Request schema for acknowledging an alert"""
    notes: Optional[str] = Field(default=None, description="Optional notes when acknowledging")


class ResolveAlertRequest(BaseModel):
    """Request schema for resolving an alert"""
    resolution_notes: str = Field(..., description="Notes explaining the resolution")


class DismissAlertRequest(BaseModel):
    """Request schema for dismissing an alert"""
    reason: Optional[str] = Field(default=None, description="Optional reason for dismissal")


class CreateWorkOrderRequest(BaseModel):
    """Request schema for creating a work order from an alert"""
    title: Optional[str] = Field(default=None, description="Work order title (auto-generated if not provided)")
    description: Optional[str] = Field(default=None, description="Work order description")
    priority: str = Field(default="medium", description="Priority: low, medium, high, critical")
    assigned_to: Optional[int] = Field(default=None, description="Staff ID to assign")


class AlertResponse(BaseModel):
    """Response schema for alert details"""
    id: int
    category_id: int
    category_name: Optional[str] = None
    alert_type: str
    start_date: datetime
    end_date: datetime
    issue_count: int
    severity_score: float
    status: str
    rca_analysis: Optional[dict] = None
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    has_work_order: bool = False

    class Config:
        from_attributes = True


class AlertListResponse(BaseModel):
    """Response schema for list of alerts"""
    total: int
    alerts: List[AlertResponse]


class AlertDetectionResult(BaseModel):
    """Response schema for alert detection results"""
    detected_count: int
    alerts: List[dict]
    run_at: datetime


# ==================== ALERT ENDPOINTS ====================

@router.get("/", response_model=AlertListResponse)
async def get_alerts(
    status: Optional[str] = Query(None, description="Filter by status: active, resolved, dismissed"),
    alert_type: Optional[str] = Query(None, description="Filter by type: negative_spike, rating_drop, volume_increase"),
    category_id: Optional[int] = Query(None, description="Filter by category ID"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of alerts to return"),
    offset: int = Query(0, ge=0, description="Number of alerts to skip"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get all alerts with optional filters.

    Returns alerts ordered by severity (highest first) and creation date (newest first).
    """
    try:
        # Build query with filters
        query = select(TrendAlert)
        filters = []

        if status:
            filters.append(TrendAlert.status == status)
        if alert_type:
            filters.append(TrendAlert.alert_type == alert_type)
        if category_id:
            filters.append(TrendAlert.category_id == category_id)

        if filters:
            query = query.where(and_(*filters))

        # Order by severity (desc) and created_at (desc)
        query = query.order_by(
            TrendAlert.severity_score.desc(),
            TrendAlert.created_at.desc()
        ).offset(offset).limit(limit)

        # Count total matching alerts
        count_query = select(func.count(TrendAlert.id))
        if filters:
            count_query = count_query.where(and_(*filters))
        total = (await db.execute(count_query)).scalar() or 0

        # Fetch alerts
        result = await db.execute(query)
        alerts = result.scalars().all()

        # Get category names and work order status
        alert_responses = []
        for alert in alerts:
            # Get category name
            cat_result = await db.execute(
                select(ReviewCategory.name).where(ReviewCategory.id == alert.category_id)
            )
            category_name = cat_result.scalar()

            # Check if work order exists
            wo_result = await db.execute(
                select(TrendWorkOrder.id).where(TrendWorkOrder.trend_alert_id == alert.id)
            )
            has_work_order = wo_result.scalar() is not None

            alert_responses.append(AlertResponse(
                id=alert.id,
                category_id=alert.category_id,
                category_name=category_name,
                alert_type=alert.alert_type,
                start_date=alert.start_date,
                end_date=alert.end_date,
                issue_count=alert.issue_count,
                severity_score=alert.severity_score,
                status=alert.status,
                rca_analysis=alert.rca_analysis,
                resolved_by=alert.resolved_by,
                resolved_at=alert.resolved_at,
                resolution_notes=alert.resolution_notes,
                created_at=alert.created_at,
                has_work_order=has_work_order
            ))

        return AlertListResponse(total=total, alerts=alert_responses)

    except Exception as e:
        logger.error(f"Error fetching alerts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch alerts"
        )


@router.get("/{alert_id}")
async def get_alert_detail(
    alert_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get detailed alert info including RCA (Root Cause Analysis).

    Returns comprehensive information about a specific alert including:
    - Alert details and severity
    - AI-generated root cause analysis
    - Related reviews summary
    - Associated work order (if exists)
    """
    try:
        # Fetch alert
        result = await db.execute(
            select(TrendAlert).where(TrendAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alert {alert_id} not found"
            )

        # Get category info
        cat_result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.id == alert.category_id)
        )
        category = cat_result.scalar_one_or_none()

        # Get associated work order if exists
        wo_result = await db.execute(
            select(TrendWorkOrder).where(TrendWorkOrder.trend_alert_id == alert_id)
        )
        work_order = wo_result.scalar_one_or_none()

        # Get related reviews for this category in the alert period
        reviews_query = select(Review).join(
            ReviewCategoryAssignment,
            Review.id == ReviewCategoryAssignment.review_id
        ).where(
            and_(
                ReviewCategoryAssignment.category_id == alert.category_id,
                Review.review_date >= alert.start_date,
                Review.review_date <= alert.end_date
            )
        ).order_by(Review.overall_rating.asc()).limit(10)

        reviews_result = await db.execute(reviews_query)
        related_reviews = reviews_result.scalars().all()

        return {
            "id": alert.id,
            "alert_type": alert.alert_type,
            "status": alert.status,
            "severity_score": alert.severity_score,
            "issue_count": alert.issue_count,
            "period": {
                "start": alert.start_date.isoformat(),
                "end": alert.end_date.isoformat()
            },
            "category": {
                "id": category.id if category else None,
                "name": category.name if category else "Unknown",
                "description": category.description if category else None
            } if category else None,
            "rca_analysis": alert.rca_analysis or {
                "summary": "Root cause analysis not yet generated",
                "contributing_factors": [],
                "recommended_actions": []
            },
            "resolution": {
                "resolved_by": alert.resolved_by,
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                "notes": alert.resolution_notes
            } if alert.status == "resolved" else None,
            "work_order": {
                "id": work_order.id,
                "title": work_order.title,
                "status": work_order.status,
                "priority": work_order.priority,
                "assigned_to": work_order.assigned_to
            } if work_order else None,
            "related_reviews": [
                {
                    "id": r.id,
                    "rating": r.overall_rating,
                    "title": r.title,
                    "comment": r.comment[:200] + "..." if r.comment and len(r.comment) > 200 else r.comment,
                    "sentiment": r.sentiment,
                    "source": r.source,
                    "review_date": r.review_date.isoformat() if r.review_date else None
                }
                for r in related_reviews
            ],
            "created_at": alert.created_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching alert detail: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch alert details"
        )


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    request: Optional[AcknowledgeAlertRequest] = None,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Acknowledge an alert.

    Acknowledging an alert indicates that the user is aware of the issue
    and is tracking it without resolving it yet.
    """
    try:
        # Fetch alert
        result = await db.execute(
            select(TrendAlert).where(TrendAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alert {alert_id} not found"
            )

        if alert.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alert is already {alert.status}"
            )

        # Update RCA with acknowledgement info
        rca = alert.rca_analysis or {}
        rca["acknowledged_by"] = current_user.id
        rca["acknowledged_at"] = datetime.utcnow().isoformat()
        if request and request.notes:
            rca["acknowledgement_notes"] = request.notes

        alert.rca_analysis = rca

        await db.commit()
        await db.refresh(alert)

        logger.info(f"Alert {alert_id} acknowledged by user {current_user.id}")

        return {
            "success": True,
            "message": "Alert acknowledged successfully",
            "alert_id": alert_id,
            "acknowledged_by": current_user.id,
            "acknowledged_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to acknowledge alert"
        )


@router.post("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    request: ResolveAlertRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Resolve an alert with notes.

    Resolving an alert indicates that the underlying issue has been addressed.
    Resolution notes are required to document what action was taken.
    """
    try:
        # Fetch alert
        result = await db.execute(
            select(TrendAlert).where(TrendAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alert {alert_id} not found"
            )

        if alert.status == "resolved":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Alert is already resolved"
            )

        # Update alert status
        alert.status = "resolved"
        alert.resolved_by = current_user.id
        alert.resolved_at = datetime.utcnow()
        alert.resolution_notes = request.resolution_notes

        # Also update any associated work order
        wo_result = await db.execute(
            select(TrendWorkOrder).where(TrendWorkOrder.trend_alert_id == alert_id)
        )
        work_order = wo_result.scalar_one_or_none()
        if work_order and work_order.status != "completed":
            work_order.status = "completed"
            work_order.completed_at = datetime.utcnow()

        await db.commit()
        await db.refresh(alert)

        logger.info(f"Alert {alert_id} resolved by user {current_user.id}")

        return {
            "success": True,
            "message": "Alert resolved successfully",
            "alert_id": alert_id,
            "status": "resolved",
            "resolved_by": current_user.id,
            "resolved_at": alert.resolved_at.isoformat(),
            "resolution_notes": alert.resolution_notes
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving alert: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve alert"
        )


@router.post("/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: int,
    request: Optional[DismissAlertRequest] = None,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Dismiss an alert.

    Dismissing an alert indicates that it was a false positive or
    does not require action.
    """
    try:
        # Fetch alert
        result = await db.execute(
            select(TrendAlert).where(TrendAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alert {alert_id} not found"
            )

        if alert.status in ["resolved", "dismissed"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alert is already {alert.status}"
            )

        # Update alert status
        alert.status = "dismissed"
        alert.resolved_by = current_user.id
        alert.resolved_at = datetime.utcnow()

        if request and request.reason:
            alert.resolution_notes = f"Dismissed: {request.reason}"
        else:
            alert.resolution_notes = "Dismissed by user"

        await db.commit()
        await db.refresh(alert)

        logger.info(f"Alert {alert_id} dismissed by user {current_user.id}")

        return {
            "success": True,
            "message": "Alert dismissed successfully",
            "alert_id": alert_id,
            "status": "dismissed",
            "dismissed_by": current_user.id,
            "dismissed_at": alert.resolved_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error dismissing alert: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to dismiss alert"
        )


@router.post("/{alert_id}/work-order")
async def create_work_order_from_alert(
    alert_id: int,
    request: CreateWorkOrderRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Create a work order from an alert.

    Creates a TrendWorkOrder to track the resolution of systemic issues
    identified by the alert.
    """
    try:
        # Fetch alert
        result = await db.execute(
            select(TrendAlert).where(TrendAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alert {alert_id} not found"
            )

        # Check if work order already exists
        existing_wo = await db.execute(
            select(TrendWorkOrder).where(TrendWorkOrder.trend_alert_id == alert_id)
        )
        if existing_wo.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Work order already exists for this alert"
            )

        # Get category name for auto-generated title
        cat_result = await db.execute(
            select(ReviewCategory.name).where(ReviewCategory.id == alert.category_id)
        )
        category_name = cat_result.scalar() or "Unknown Category"

        # Generate title if not provided
        title = request.title or f"Address {alert.alert_type.replace('_', ' ').title()} - {category_name}"

        # Generate description if not provided
        description = request.description or (
            f"Work order created from alert #{alert_id}.\n"
            f"Alert Type: {alert.alert_type}\n"
            f"Category: {category_name}\n"
            f"Issue Count: {alert.issue_count}\n"
            f"Severity Score: {alert.severity_score}\n"
            f"Period: {alert.start_date.strftime('%Y-%m-%d')} to {alert.end_date.strftime('%Y-%m-%d')}"
        )

        # Create work order
        work_order = TrendWorkOrder(
            trend_alert_id=alert_id,
            category_id=alert.category_id,
            title=title,
            description=description,
            priority=request.priority,
            assigned_to=request.assigned_to,
            status="open"
        )

        db.add(work_order)
        await db.commit()
        await db.refresh(work_order)

        logger.info(f"Work order {work_order.id} created for alert {alert_id} by user {current_user.id}")

        return {
            "success": True,
            "message": "Work order created successfully",
            "work_order": {
                "id": work_order.id,
                "title": work_order.title,
                "description": work_order.description,
                "priority": work_order.priority,
                "status": work_order.status,
                "assigned_to": work_order.assigned_to,
                "alert_id": alert_id,
                "created_at": work_order.created_at.isoformat()
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating work order: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create work order"
        )


@router.post("/detect")
async def run_alert_detection(
    days: int = Query(14, ge=7, le=90, description="Analysis window in days"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Manually trigger alert detection.

    Analyzes reviews from the specified time window to detect:
    - Negative sentiment spikes
    - Rating drops
    - Volume increases in specific categories
    """
    try:
        from datetime import timedelta

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        prev_start = start_date - timedelta(days=days)

        detected_alerts = []

        # Get all active categories
        cat_result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.is_active == True)
        )
        categories = cat_result.scalars().all()

        for category in categories:
            # Count negative reviews in current period for this category
            current_query = select(func.count(ReviewCategoryAssignment.id)).join(
                Review, Review.id == ReviewCategoryAssignment.review_id
            ).where(
                and_(
                    ReviewCategoryAssignment.category_id == category.id,
                    Review.review_date >= start_date,
                    Review.review_date <= end_date,
                    Review.sentiment == "negative"
                )
            )
            current_count = (await db.execute(current_query)).scalar() or 0

            # Count negative reviews in previous period
            prev_query = select(func.count(ReviewCategoryAssignment.id)).join(
                Review, Review.id == ReviewCategoryAssignment.review_id
            ).where(
                and_(
                    ReviewCategoryAssignment.category_id == category.id,
                    Review.review_date >= prev_start,
                    Review.review_date < start_date,
                    Review.sentiment == "negative"
                )
            )
            prev_count = (await db.execute(prev_query)).scalar() or 0

            # Detect negative spike (more than 50% increase with minimum threshold)
            if current_count >= 3 and (prev_count == 0 or current_count / max(prev_count, 1) > 1.5):
                # Check if similar alert already exists for this period
                existing_alert = await db.execute(
                    select(TrendAlert).where(
                        and_(
                            TrendAlert.category_id == category.id,
                            TrendAlert.alert_type == "negative_spike",
                            TrendAlert.start_date == start_date,
                            TrendAlert.status == "active"
                        )
                    )
                )

                if not existing_alert.scalar_one_or_none():
                    # Calculate severity score (0-100)
                    severity = min(100, (current_count / max(prev_count, 1)) * 30 + current_count * 5)

                    # Generate RCA
                    rca = await _generate_rca(db, category.id, start_date, end_date)

                    # Create alert
                    alert = TrendAlert(
                        category_id=category.id,
                        alert_type="negative_spike",
                        start_date=start_date,
                        end_date=end_date,
                        issue_count=current_count,
                        severity_score=severity,
                        status="active",
                        rca_analysis=rca
                    )

                    db.add(alert)
                    detected_alerts.append({
                        "type": "negative_spike",
                        "category": category.name,
                        "issue_count": current_count,
                        "severity": severity,
                        "previous_count": prev_count
                    })

        await db.commit()

        logger.info(f"Alert detection completed. Detected {len(detected_alerts)} new alerts.")

        return AlertDetectionResult(
            detected_count=len(detected_alerts),
            alerts=detected_alerts,
            run_at=datetime.utcnow()
        )

    except Exception as e:
        logger.error(f"Error running alert detection: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to run alert detection"
        )


async def _generate_rca(
    db: AsyncSession,
    category_id: int,
    start_date: datetime,
    end_date: datetime
) -> dict:
    """Generate Root Cause Analysis for an alert."""

    # Get review comments for analysis
    reviews_query = select(Review.comment, Review.title, Review.overall_rating).join(
        ReviewCategoryAssignment, Review.id == ReviewCategoryAssignment.review_id
    ).where(
        and_(
            ReviewCategoryAssignment.category_id == category_id,
            Review.review_date >= start_date,
            Review.review_date <= end_date,
            Review.sentiment == "negative"
        )
    ).limit(20)

    result = await db.execute(reviews_query)
    reviews = result.all()

    # In production, this would use AI/LLM for analysis
    # For now, provide structured placeholder
    common_issues = []
    for r in reviews:
        if r.title:
            common_issues.append(r.title)

    return {
        "summary": f"Analysis of {len(reviews)} negative reviews identified patterns requiring attention.",
        "sample_size": len(reviews),
        "common_themes": list(set(common_issues[:5])) if common_issues else ["Requires manual review"],
        "contributing_factors": [
            "Review volume and patterns suggest operational attention needed",
            "Guest feedback indicates room for service improvement"
        ],
        "recommended_actions": [
            "Review staff procedures related to this category",
            "Conduct team briefing to address identified patterns",
            "Monitor closely over next 7 days"
        ],
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/summary")
async def get_alerts_summary(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get summary of alerts for dashboard widgets.

    Returns counts by status and severity breakdown.
    """
    try:
        # Count by status
        active_count = (await db.execute(
            select(func.count(TrendAlert.id)).where(TrendAlert.status == "active")
        )).scalar() or 0

        resolved_count = (await db.execute(
            select(func.count(TrendAlert.id)).where(TrendAlert.status == "resolved")
        )).scalar() or 0

        dismissed_count = (await db.execute(
            select(func.count(TrendAlert.id)).where(TrendAlert.status == "dismissed")
        )).scalar() or 0

        # Get high severity alerts (score > 70)
        high_severity = (await db.execute(
            select(func.count(TrendAlert.id)).where(
                and_(TrendAlert.status == "active", TrendAlert.severity_score > 70)
            )
        )).scalar() or 0

        # Get recent alerts (last 7 days)
        from datetime import timedelta
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_count = (await db.execute(
            select(func.count(TrendAlert.id)).where(TrendAlert.created_at >= week_ago)
        )).scalar() or 0

        return {
            "total_active": active_count,
            "total_resolved": resolved_count,
            "total_dismissed": dismissed_count,
            "high_severity_active": high_severity,
            "recent_7_days": recent_count,
            "requires_attention": active_count > 0 and high_severity > 0
        }

    except Exception as e:
        logger.error(f"Error fetching alerts summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch alerts summary"
        )
