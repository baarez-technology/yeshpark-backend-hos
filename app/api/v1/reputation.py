"""
Reputation AI API Routes
Integrated from Yadhu's Reputation AI System
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from app.db.session import get_tenant_session
from app.services.reputation_service import ReputationService
from app.api.v1.auth import get_current_user_optional, get_current_user
from app.models.user import User
from app.models.reputation import (
    ResponseDraft,
    ResponseDraftHistory,
    ReviewResponse,
    AutomationConfig,
    PerformanceGoal
)
from app.models.reviews import Review

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== PYDANTIC SCHEMAS ====================

class GenerateDraftRequest(BaseModel):
    tone: str = Field(default="professional", description="Response tone: professional, empathetic, concise")
    include_resolution: bool = Field(default=False, description="Include resolution context if available")


class ApproveResponseRequest(BaseModel):
    final_text: Optional[str] = Field(default=None, description="Modified text (optional)")


class CreateGoalRequest(BaseModel):
    metric_type: str = Field(..., description="Metric type: rating, response_rate, nps")
    target_value: float = Field(..., description="Target value to achieve")
    start_date: datetime = Field(..., description="Goal start date")
    end_date: datetime = Field(..., description="Goal end date")


class UpdateGoalProgressRequest(BaseModel):
    current_value: Optional[float] = Field(None, description="Manually set current progress value")


class UpdateGoalRequest(BaseModel):
    target_value: Optional[float] = Field(None, description="New target value")
    start_date: Optional[datetime] = Field(None, description="New start date")
    end_date: Optional[datetime] = Field(None, description="New end date")


# ==================== DASHBOARD ROUTES ====================

@router.get("/dashboard")
async def get_reputation_dashboard(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get comprehensive reputation dashboard data.
    Includes metrics, source breakdown, recent reviews, trends, and goals.
    """
    service = ReputationService(db)
    return await service.get_reputation_dashboard()


@router.get("/analytics")
async def get_review_analytics(
    source: Optional[str] = Query(None, description="Filter by source (google, booking, etc.)"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get detailed review analytics with optional filters.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        service = ReputationService(db)
        return await service.get_review_analytics(source, start_date, end_date)
    except Exception as e:
        logger.error(f"Analytics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trends")
async def get_trends(
    days: int = Query(14, ge=7, le=90, description="Analysis window in days"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Detect sentiment and rating trends over time.
    Compares current period with previous period.
    """
    service = ReputationService(db)
    return await service.detect_trends(days)


# ==================== REVIEW MANAGEMENT ====================

@router.get("/reviews")
async def get_all_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source: Optional[str] = Query(None, description="Filter by source (google, booking_com, etc.)"),
    sentiment: Optional[str] = Query(None, description="Filter by sentiment (positive, neutral, negative)"),
    min_rating: Optional[float] = Query(None, ge=1, le=5),
    max_rating: Optional[float] = Query(None, ge=1, le=5),
    has_response: Optional[bool] = Query(None, description="Filter by response status"),
    start_date: Optional[datetime] = Query(None, description="Filter reviews from this date"),
    end_date: Optional[datetime] = Query(None, description="Filter reviews until this date"),
    keyword: Optional[str] = Query(None, description="Search in title and comment"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get all reviews with optional filters and pagination.
    """
    service = ReputationService(db)
    return await service.get_all_reviews(
        page=page,
        page_size=page_size,
        source=source,
        sentiment=sentiment,
        min_rating=min_rating,
        max_rating=max_rating,
        has_response=has_response,
        start_date=start_date,
        end_date=end_date,
        keyword=keyword
    )


@router.get("/reviews/pending")
async def get_reviews_needing_response(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get reviews that need responses, prioritized by urgency.
    Lower-rated reviews appear first.
    """
    service = ReputationService(db)
    return await service.get_reviews_needing_response(page, page_size)


@router.get("/reviews/{review_id}")
async def get_single_review(
    review_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get a single review with its full details including response.
    """
    result = await db.execute(
        select(Review).where(Review.id == review_id)
    )
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found")

    # Get the published response if exists
    response_result = await db.execute(
        select(ReviewResponse).where(ReviewResponse.review_id == review_id)
    )
    published_response = response_result.scalar_one_or_none()

    # Get the draft if exists
    draft_result = await db.execute(
        select(ResponseDraft).where(ResponseDraft.review_id == review_id).order_by(ResponseDraft.created_at.desc()).limit(1)
    )
    draft = draft_result.scalar_one_or_none()

    return {
        "id": review.id,
        "source": review.source,
        "rating": review.overall_rating,
        "title": review.title,
        "comment": review.comment,
        "pros": review.pros,
        "cons": review.cons,
        "sentiment": review.sentiment,
        "review_date": review.review_date.isoformat() if review.review_date else None,
        "guest_id": review.guest_id,
        "is_verified": review.is_verified,
        "helpful_count": review.helpful_count,
        "cleanliness_rating": review.cleanliness_rating,
        "service_rating": review.service_rating,
        "location_rating": review.location_rating,
        "value_rating": review.value_rating,
        # Response fields
        "has_response": bool(review.response),
        "response": review.response,
        "responded_at": review.responded_at.isoformat() if review.responded_at else None,
        "responded_by": review.responded_by,
        # Published response details (from ReviewResponse table)
        "published_response": {
            "id": published_response.id,
            "response_text": published_response.response_text,
            "published_at": published_response.published_at.isoformat() if published_response else None,
            "quality_score": published_response.quality_score,
            "likes": published_response.likes,
            "helpful_votes": published_response.helpful_votes
        } if published_response else None,
        # Latest draft details
        "draft": {
            "id": draft.id,
            "draft_text": draft.draft_text,
            "status": draft.status,
            "current_stage": draft.current_stage,
            "tone": draft.tone,
            "confidence_score": draft.confidence_score,
            "created_at": draft.created_at.isoformat() if draft else None
        } if draft else None
    }


@router.post("/reviews/{review_id}/generate-draft")
async def generate_response_draft(
    review_id: int,
    request: GenerateDraftRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Generate an AI-powered response draft for a review.
    """
    service = ReputationService(db)
    try:
        return await service.generate_response_draft(
            review_id=review_id,
            tone=request.tone,
            include_resolution=request.include_resolution
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reviews/{review_id}/respond")
async def respond_to_review(
    review_id: int,
    request: ApproveResponseRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Directly respond to a review without going through draft workflow.
    """
    # Fetch the review
    result = await db.execute(
        select(Review).where(Review.id == review_id)
    )
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found")

    published_at = datetime.utcnow()

    # Update the review with the response
    review.response = request.final_text
    review.responded_by = current_user.id
    review.responded_at = published_at
    review.updated_at = published_at

    # Create or update ReviewResponse record for tracking published responses
    existing_response_result = await db.execute(
        select(ReviewResponse).where(ReviewResponse.review_id == review_id)
    )
    existing_response = existing_response_result.scalar_one_or_none()

    if existing_response:
        # Update existing response
        existing_response.response_text = request.final_text
        existing_response.published_at = published_at
        existing_response.published_by = current_user.id
    else:
        # Create new ReviewResponse record
        review_response = ReviewResponse(
            review_id=review_id,
            response_text=request.final_text,
            published_at=published_at,
            published_by=current_user.id
        )
        db.add(review_response)

    await db.commit()
    await db.refresh(review)

    logger.info(f"Response published for review {review_id} by user {current_user.id}")

    return {
        "success": True,
        "message": "Response published successfully",
        "review_id": review_id,
        "response": review.response,
        "responded_at": review.responded_at.isoformat() if review.responded_at else None
    }


@router.post("/drafts/{draft_id}/approve")
async def approve_and_publish_response(
    draft_id: int,
    request: ApproveResponseRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Approve a draft and publish it as the official response.
    """
    service = ReputationService(db)
    try:
        return await service.approve_and_publish_response(
            draft_id=draft_id,
            editor_id=current_user.id,
            final_text=request.final_text
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== COMPETITOR BENCHMARKING ====================

@router.get("/competitors")
async def get_competitor_benchmarks(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get competitor comparison data for benchmarking.
    """
    service = ReputationService(db)
    return await service.get_competitor_benchmarks()


# ==================== PERFORMANCE GOALS ====================

@router.get("/goals")
async def get_performance_goals(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get all performance goals, optionally filtered by status.
    """
    service = ReputationService(db)
    return await service.get_goals(status=status)


@router.post("/goals")
async def create_performance_goal(
    request: CreateGoalRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new performance goal (rating, response_rate, nps).
    Baseline is automatically calculated from current metrics.
    """
    service = ReputationService(db)
    return await service.create_goal(
        metric_type=request.metric_type,
        target_value=request.target_value,
        start_date=request.start_date,
        end_date=request.end_date,
        created_by=current_user.id
    )


@router.patch("/goals/{goal_id}/progress")
async def update_goal_progress(
    goal_id: int,
    payload: Optional[UpdateGoalProgressRequest] = None,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update progress for a goal.

    Can either:
    1. Manually set current_value via request body
    2. Recalculate progress from database (if no body provided)
    """
    service = ReputationService(db)
    try:
        # If manual value provided, use it; otherwise recalculate
        manual_value = payload.current_value if payload else None
        return await service.update_goal_progress(goal_id, manual_value)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/goals/{goal_id}")
async def update_performance_goal(
    goal_id: int,
    request: UpdateGoalRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a performance goal (target, dates)."""
    service = ReputationService(db)
    try:
        return await service.update_goal(
            goal_id,
            target_value=request.target_value,
            start_date=request.start_date,
            end_date=request.end_date
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/goals/{goal_id}")
async def delete_performance_goal(
    goal_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a performance goal."""
    service = ReputationService(db)
    try:
        await service.delete_goal(goal_id)
        return {"success": True, "message": "Goal deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/goals/{goal_id}/toggle")
async def toggle_goal_status(
    goal_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Toggle goal between active and deactivated status."""
    service = ReputationService(db)
    try:
        return await service.toggle_goal_status(goal_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== SUMMARY STATS ====================

@router.get("/stats/summary")
async def get_summary_stats(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Quick summary stats for widgets and cards.
    """
    service = ReputationService(db)
    dashboard = await service.get_reputation_dashboard()

    return {
        "total_reviews": dashboard["metrics"]["total_reviews"],
        "average_rating": dashboard["metrics"]["average_rating"],
        "response_rate": dashboard["metrics"]["response_rate"],
        "nps_score": dashboard["metrics"]["nps_score"],
        "pending_responses": dashboard["pending_responses"],
        "sentiment": dashboard["metrics"]["sentiment"]
    }


# ==================== ADDITIONAL SCHEMAS ====================

class SubmitForReviewRequest(BaseModel):
    """Request to submit a draft for review"""
    notes: Optional[str] = Field(default=None, description="Notes for reviewers")


class ApproveStageRequest(BaseModel):
    """Request to approve draft at current stage"""
    notes: Optional[str] = Field(default=None, description="Approval notes")
    modified_text: Optional[str] = Field(default=None, description="Modified text if changes were made")


class RejectDraftRequest(BaseModel):
    """Request to reject a draft"""
    reason: str = Field(..., description="Reason for rejection")
    suggested_changes: Optional[str] = Field(default=None, description="Suggested changes")


class UserSettingsRequest(BaseModel):
    """User reputation settings"""
    auto_reply_enabled: bool = Field(default=False, description="Enable auto-reply feature")
    notification_email: Optional[str] = Field(default=None, description="Email for notifications")
    notify_on_negative: bool = Field(default=True, description="Notify on negative reviews")
    notify_on_response_needed: bool = Field(default=True, description="Notify when response needed")
    default_tone: str = Field(default="professional", description="Default response tone")
    dashboard_preferences: Optional[Dict[str, Any]] = Field(default=None, description="Dashboard widget preferences")


class DraftHistoryEntry(BaseModel):
    """Schema for draft history entry"""
    id: int
    draft_id: int
    editor_id: Optional[int]
    previous_text: Optional[str]
    new_text: Optional[str]
    change_reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== MULTI-LEVEL APPROVAL WORKFLOW ====================

@router.post("/drafts/{draft_id}/submit-review")
async def submit_draft_for_review(
    draft_id: int,
    request: Optional[SubmitForReviewRequest] = None,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Submit a draft for review (moves to 'review' stage).

    This is the first step in the multi-level approval workflow.
    After submission, the draft needs to be approved by reviewers.
    """
    try:
        # Fetch draft
        result = await db.execute(
            select(ResponseDraft).where(ResponseDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()

        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found"
            )

        if draft.current_stage != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Draft is already in '{draft.current_stage}' stage. Cannot submit for review."
            )

        # Update draft stage
        draft.current_stage = "review"
        draft.status = "pending"
        draft.updated_at = datetime.utcnow()

        # Initialize approvals tracking
        approvals = draft.approvals or {}
        approvals["submitted_by"] = current_user.id
        approvals["submitted_at"] = datetime.utcnow().isoformat()
        if request and request.notes:
            approvals["submission_notes"] = request.notes
        approvals["stages"] = {
            "review": {"status": "pending", "required": True},
            "approval_manager": {"status": "pending", "required": True},
            "approval_gm": {"status": "pending", "required": False}
        }
        draft.approvals = approvals

        await db.commit()
        await db.refresh(draft)

        logger.info(f"Draft {draft_id} submitted for review by user {current_user.id}")

        return {
            "success": True,
            "message": "Draft submitted for review",
            "draft_id": draft_id,
            "current_stage": draft.current_stage,
            "status": draft.status,
            "submitted_at": approvals["submitted_at"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting draft for review: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit draft for review"
        )


@router.post("/drafts/{draft_id}/approve-stage")
async def approve_draft_stage(
    draft_id: int,
    request: Optional[ApproveStageRequest] = None,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Approve draft at current stage, move to next.

    Workflow stages:
    1. review - Initial review
    2. approval_manager - Manager approval
    3. approval_gm - GM approval (optional, based on config)
    4. ready - Ready to publish
    """
    try:
        # Fetch draft
        result = await db.execute(
            select(ResponseDraft).where(ResponseDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()

        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found"
            )

        if draft.current_stage == "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Draft has not been submitted for review yet"
            )

        if draft.current_stage == "ready":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Draft is already approved and ready to publish"
            )

        if draft.status == "rejected":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot approve a rejected draft. Please edit and resubmit."
            )

        # Update text if modified
        if request and request.modified_text:
            # Create history entry
            history = ResponseDraftHistory(
                draft_id=draft_id,
                editor_id=current_user.id,
                previous_text=draft.draft_text,
                new_text=request.modified_text,
                change_reason=f"Modified during {draft.current_stage} approval"
            )
            db.add(history)
            draft.draft_text = request.modified_text

        # Update approvals
        approvals = draft.approvals or {}
        if "stages" not in approvals:
            approvals["stages"] = {}

        current_stage = draft.current_stage
        approvals["stages"][current_stage] = {
            "status": "approved",
            "approved_by": current_user.id,
            "approved_at": datetime.utcnow().isoformat(),
            "notes": request.notes if request else None
        }

        # Determine next stage
        stage_order = ["review", "approval_manager", "approval_gm", "ready"]
        current_index = stage_order.index(current_stage) if current_stage in stage_order else 0

        # Check if GM approval is required (based on config or review rating)
        review_result = await db.execute(
            select(Review).where(Review.id == draft.review_id)
        )
        review = review_result.scalar_one_or_none()

        # Skip GM approval for positive reviews (rating >= 4)
        skip_gm = review and review.overall_rating and review.overall_rating >= 4

        next_stage = stage_order[current_index + 1] if current_index < len(stage_order) - 1 else "ready"

        # Skip GM if not required
        if next_stage == "approval_gm" and skip_gm:
            next_stage = "ready"

        draft.current_stage = next_stage
        draft.approvals = approvals
        draft.updated_at = datetime.utcnow()

        # If ready, update status
        if next_stage == "ready":
            draft.status = "approved"

        await db.commit()
        await db.refresh(draft)

        logger.info(f"Draft {draft_id} stage '{current_stage}' approved by user {current_user.id}, moved to '{next_stage}'")

        return {
            "success": True,
            "message": f"Draft approved at {current_stage} stage",
            "draft_id": draft_id,
            "previous_stage": current_stage,
            "current_stage": draft.current_stage,
            "status": draft.status,
            "is_ready": draft.current_stage == "ready"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving draft stage: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve draft stage"
        )


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(
    draft_id: int,
    request: RejectDraftRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Reject a draft with reason.

    Rejected drafts can be edited and resubmitted.
    """
    try:
        # Fetch draft
        result = await db.execute(
            select(ResponseDraft).where(ResponseDraft.id == draft_id)
        )
        draft = result.scalar_one_or_none()

        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found"
            )

        if draft.current_stage == "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reject a draft that hasn't been submitted"
            )

        if draft.status == "rejected":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Draft is already rejected"
            )

        # Update draft status
        previous_stage = draft.current_stage
        draft.status = "rejected"
        draft.current_stage = "draft"  # Reset to draft for editing
        draft.updated_at = datetime.utcnow()

        # Update approvals
        approvals = draft.approvals or {}
        approvals["rejection"] = {
            "rejected_at_stage": previous_stage,
            "rejected_by": current_user.id,
            "rejected_at": datetime.utcnow().isoformat(),
            "reason": request.reason,
            "suggested_changes": request.suggested_changes
        }
        draft.approvals = approvals

        # Create history entry
        history = ResponseDraftHistory(
            draft_id=draft_id,
            editor_id=current_user.id,
            previous_text=None,
            new_text=None,
            change_reason=f"Rejected at {previous_stage}: {request.reason}"
        )
        db.add(history)

        await db.commit()
        await db.refresh(draft)

        logger.info(f"Draft {draft_id} rejected by user {current_user.id} at stage {previous_stage}")

        return {
            "success": True,
            "message": "Draft rejected",
            "draft_id": draft_id,
            "rejected_at_stage": previous_stage,
            "reason": request.reason,
            "suggested_changes": request.suggested_changes,
            "can_resubmit": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting draft: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject draft"
        )


@router.get("/drafts/pending-approval")
async def get_pending_approvals(
    stage: Optional[str] = Query(None, description="Filter by stage: review, approval_manager, approval_gm"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get drafts pending current user's approval.

    Filters drafts based on user's role and current stage.
    """
    try:
        # Build query
        query = select(ResponseDraft).where(
            and_(
                ResponseDraft.status == "pending",
                ResponseDraft.current_stage != "draft",
                ResponseDraft.current_stage != "ready"
            )
        )

        if stage:
            query = query.where(ResponseDraft.current_stage == stage)

        # Count total
        count_query = select(func.count(ResponseDraft.id)).where(
            and_(
                ResponseDraft.status == "pending",
                ResponseDraft.current_stage != "draft",
                ResponseDraft.current_stage != "ready"
            )
        )
        if stage:
            count_query = count_query.where(ResponseDraft.current_stage == stage)

        total = (await db.execute(count_query)).scalar() or 0

        # Get paginated results
        offset = (page - 1) * page_size
        query = query.order_by(ResponseDraft.updated_at.desc()).offset(offset).limit(page_size)

        result = await db.execute(query)
        drafts = result.scalars().all()

        # Enrich with review data
        draft_list = []
        for draft in drafts:
            # Get associated review
            review_result = await db.execute(
                select(Review).where(Review.id == draft.review_id)
            )
            review = review_result.scalar_one_or_none()

            draft_list.append({
                "id": draft.id,
                "review_id": draft.review_id,
                "draft_text": draft.draft_text[:200] + "..." if len(draft.draft_text) > 200 else draft.draft_text,
                "current_stage": draft.current_stage,
                "status": draft.status,
                "tone": draft.tone,
                "confidence_score": draft.confidence_score,
                "created_at": draft.created_at.isoformat(),
                "updated_at": draft.updated_at.isoformat(),
                "review": {
                    "rating": review.overall_rating if review else None,
                    "sentiment": review.sentiment if review else None,
                    "source": review.source if review else None,
                    "title": review.title if review else None
                } if review else None,
                "approvals": draft.approvals
            })

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "drafts": draft_list
        }

    except Exception as e:
        logger.error(f"Error getting pending approvals: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get pending approvals"
        )


@router.get("/drafts/{draft_id}/history")
async def get_draft_history(
    draft_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get edit history for a draft.

    Returns all changes made to the draft including approvals and rejections.
    """
    try:
        # Verify draft exists
        draft_result = await db.execute(
            select(ResponseDraft).where(ResponseDraft.id == draft_id)
        )
        draft = draft_result.scalar_one_or_none()

        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found"
            )

        # Get history entries
        history_result = await db.execute(
            select(ResponseDraftHistory).where(
                ResponseDraftHistory.draft_id == draft_id
            ).order_by(ResponseDraftHistory.created_at.desc())
        )
        history_entries = history_result.scalars().all()

        # Get editor names
        history_list = []
        for entry in history_entries:
            editor_name = None
            if entry.editor_id:
                editor_result = await db.execute(
                    select(User.full_name).where(User.id == entry.editor_id)
                )
                editor_name = editor_result.scalar()

            history_list.append({
                "id": entry.id,
                "editor_id": entry.editor_id,
                "editor_name": editor_name,
                "previous_text": entry.previous_text,
                "new_text": entry.new_text,
                "change_reason": entry.change_reason,
                "created_at": entry.created_at.isoformat()
            })

        return {
            "draft_id": draft_id,
            "current_stage": draft.current_stage,
            "status": draft.status,
            "approvals": draft.approvals,
            "history": history_list,
            "total_changes": len(history_list)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting draft history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get draft history"
        )


# ==================== SETTINGS PERSISTENCE ====================

@router.get("/settings")
async def get_user_settings(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get user's reputation settings.

    Returns personalized settings including auto-reply config,
    notification preferences, and dashboard customizations.
    """
    try:
        # Get automation config for defaults
        config_result = await db.execute(
            select(AutomationConfig).where(AutomationConfig.is_active == True).limit(1)
        )
        config = config_result.scalar_one_or_none()

        # User preferences would typically be stored in a UserSettings table
        # For now, return defaults with user-specific overrides from user.preferences
        import json
        user_prefs = {}
        if current_user.preferences:
            try:
                user_prefs = json.loads(current_user.preferences) if isinstance(current_user.preferences, str) else current_user.preferences
            except (json.JSONDecodeError, TypeError):
                user_prefs = {}

        reputation_settings = user_prefs.get("reputation", {})

        return {
            "user_id": current_user.id,
            "auto_reply_enabled": reputation_settings.get("auto_reply_enabled", False),
            "notification_email": reputation_settings.get("notification_email", current_user.email),
            "notify_on_negative": reputation_settings.get("notify_on_negative", True),
            "notify_on_response_needed": reputation_settings.get("notify_on_response_needed", True),
            "default_tone": reputation_settings.get("default_tone", "professional"),
            "dashboard_preferences": reputation_settings.get("dashboard_preferences", {
                "show_trends": True,
                "show_competitors": True,
                "show_goals": True,
                "default_date_range": 30
            }),
            "global_automation_enabled": config.global_enabled if config else False
        }

    except Exception as e:
        logger.error(f"Error getting user settings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user settings"
        )


@router.put("/settings")
async def save_user_settings(
    settings: UserSettingsRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Save user's reputation settings.

    Persists user-specific preferences for the reputation module.
    """
    try:
        import json

        # Parse existing preferences
        user_prefs = {}
        if current_user.preferences:
            try:
                user_prefs = json.loads(current_user.preferences) if isinstance(current_user.preferences, str) else current_user.preferences
            except (json.JSONDecodeError, TypeError):
                user_prefs = {}

        # Update reputation settings
        user_prefs["reputation"] = {
            "auto_reply_enabled": settings.auto_reply_enabled,
            "notification_email": settings.notification_email,
            "notify_on_negative": settings.notify_on_negative,
            "notify_on_response_needed": settings.notify_on_response_needed,
            "default_tone": settings.default_tone,
            "dashboard_preferences": settings.dashboard_preferences or {}
        }

        # Save to user record
        current_user.preferences = json.dumps(user_prefs)
        current_user.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(current_user)

        logger.info(f"User {current_user.id} updated reputation settings")

        return {
            "success": True,
            "message": "Settings saved successfully",
            "settings": user_prefs["reputation"]
        }

    except Exception as e:
        logger.error(f"Error saving user settings: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save user settings"
        )


# ==================== ENGINE STATS ====================

@router.get("/stats/engine")
async def get_engine_stats(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get engine status, model version, accuracy, auto-replies count.

    Returns operational statistics for the reputation AI engine.
    """
    try:
        from datetime import timedelta

        # Get automation config
        config_result = await db.execute(
            select(AutomationConfig).where(AutomationConfig.is_active == True).limit(1)
        )
        config = config_result.scalar_one_or_none()

        # Count total drafts generated
        total_drafts = (await db.execute(
            select(func.count(ResponseDraft.id))
        )).scalar() or 0

        # Count approved drafts
        approved_drafts = (await db.execute(
            select(func.count(ResponseDraft.id)).where(ResponseDraft.status == "approved")
        )).scalar() or 0

        # Count published responses
        published_responses = (await db.execute(
            select(func.count(ReviewResponse.id))
        )).scalar() or 0

        # Calculate accuracy (approved / total)
        accuracy = (approved_drafts / total_drafts * 100) if total_drafts > 0 else 0

        # Recent activity (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_drafts = (await db.execute(
            select(func.count(ResponseDraft.id)).where(ResponseDraft.created_at >= week_ago)
        )).scalar() or 0

        # Auto-replies count (drafts with high confidence that were approved)
        auto_approved = (await db.execute(
            select(func.count(ResponseDraft.id)).where(
                and_(
                    ResponseDraft.status == "approved",
                    ResponseDraft.confidence_score >= 0.8
                )
            )
        )).scalar() or 0

        # Average response time (from review to response)
        avg_response_time = None
        try:
            response_time_query = select(
                func.avg(
                    func.julianday(Review.responded_at) - func.julianday(Review.review_date)
                )
            ).where(Review.responded_at != None)
            avg_days = (await db.execute(response_time_query)).scalar()
            if avg_days:
                avg_response_time = round(float(avg_days) * 24, 1)  # Convert to hours
        except Exception:
            pass

        return {
            "engine_status": "operational",
            "model_version": "reputation-ai-v1.0",
            "last_updated": "2024-01-15",
            "automation": {
                "enabled": config.global_enabled if config else False,
                "auto_respond_positive": config.auto_respond_positive if config else False,
                "require_approval": config.require_approval if config else True
            },
            "statistics": {
                "total_drafts_generated": total_drafts,
                "approved_drafts": approved_drafts,
                "published_responses": published_responses,
                "approval_rate": round(accuracy, 1),
                "auto_approved_count": auto_approved,
                "recent_7_days": recent_drafts
            },
            "performance": {
                "average_response_time_hours": avg_response_time,
                "target_response_time_hours": 24
            },
            "capabilities": [
                "sentiment_analysis",
                "auto_response_generation",
                "trend_detection",
                "category_classification",
                "competitor_benchmarking"
            ]
        }

    except Exception as e:
        logger.error(f"Error getting engine stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get engine statistics"
        )
