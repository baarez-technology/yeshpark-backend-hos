"""
Automation Configuration API Routes
Reputation AI Module - Glimmora Hotel Management System
"""
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user_optional, get_current_user
from app.models.user import User
from app.models.reputation import AutomationConfig, ResponseDraft, ResponseTemplate
from app.models.reviews import Review

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== PYDANTIC SCHEMAS ====================

class AutomationConfigUpdate(BaseModel):
    """Request schema for updating automation configuration"""
    global_enabled: Optional[bool] = Field(None, description="Enable/disable automation globally")
    safety_check_enabled: Optional[bool] = Field(None, description="Enable content safety checks")
    auto_respond_positive: Optional[bool] = Field(None, description="Auto-respond to positive reviews")
    auto_respond_threshold: Optional[float] = Field(None, ge=1.0, le=5.0, description="Minimum rating for auto-response")
    require_approval: Optional[bool] = Field(None, description="Require approval before posting")
    profanity_blocklist: Optional[List[str]] = Field(None, description="List of blocked words")
    brand_guidelines: Optional[str] = Field(None, description="Brand guidelines text")
    response_delay_hours: Optional[int] = Field(None, ge=0, le=72, description="Delay before auto-posting")
    rules: Optional[dict] = Field(None, description="Custom automation rules")


class AutomationConfigResponse(BaseModel):
    """Response schema for automation configuration"""
    id: int
    name: str
    global_enabled: bool
    safety_check_enabled: bool
    auto_respond_positive: bool
    auto_respond_threshold: float
    require_approval: bool
    profanity_blocklist: Optional[List[str]]
    brand_guidelines: Optional[str]
    response_delay_hours: int
    rules: Optional[dict]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TestAutoResponseRequest(BaseModel):
    """Request schema for testing auto-response generation"""
    review_id: Optional[int] = Field(None, description="Specific review ID to test")
    rating: Optional[float] = Field(None, ge=1.0, le=5.0, description="Test rating value")
    comment: Optional[str] = Field(None, description="Test review comment")
    tone: str = Field(default="professional", description="Response tone")


class ResponseTemplateUpdate(BaseModel):
    """Request schema for updating response templates"""
    template_text: str = Field(..., description="Template text with placeholders")
    variables: Optional[List[str]] = Field(None, description="Available template variables")
    is_active: bool = Field(default=True, description="Whether template is active")


class RunAutomationRequest(BaseModel):
    """Request schema for running automation on pending reviews"""
    dry_run: bool = Field(default=True, description="If true, don't actually create drafts")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum reviews to process")
    min_rating: Optional[float] = Field(None, ge=1.0, le=5.0, description="Filter by minimum rating")


# ==================== RESPONSE TEMPLATES ====================

# Default response templates (in production, these would be in database)
DEFAULT_TEMPLATES = {
    "positive": {
        "template_text": """Dear {guest_name},

Thank you so much for taking the time to share your wonderful feedback! We are absolutely delighted to hear that you enjoyed your stay with us.

Your kind words mean a great deal to our entire team. We strive to provide exceptional experiences for all our guests, and it's truly rewarding to know we succeeded in making your visit memorable.

We look forward to welcoming you back soon!

Warm regards,
The {hotel_name} Team""",
        "variables": ["guest_name", "hotel_name", "review_date"],
        "is_active": True
    },
    "neutral": {
        "template_text": """Dear {guest_name},

Thank you for taking the time to share your feedback about your recent stay with us.

We appreciate your honest review and are glad that certain aspects of your experience met your expectations. We are always looking for ways to improve, and your comments help us do exactly that.

We would love the opportunity to exceed your expectations on your next visit.

Best regards,
The {hotel_name} Team""",
        "variables": ["guest_name", "hotel_name", "review_date"],
        "is_active": True
    },
    "negative": {
        "template_text": """Dear {guest_name},

Thank you for bringing this to our attention. We sincerely apologize that your experience did not meet the standards we strive to uphold.

We take all feedback seriously and are actively working to address the concerns you've raised. Your comments have been shared with our management team for immediate review.

We would greatly appreciate the opportunity to make things right. Please feel free to reach out to us directly at your convenience so we can discuss this further.

With sincere apologies,
The {hotel_name} Team""",
        "variables": ["guest_name", "hotel_name", "review_date", "contact_email"],
        "is_active": True
    }
}


# ==================== AUTOMATION CONFIG ENDPOINTS ====================

@router.get("/config", response_model=AutomationConfigResponse)
async def get_automation_config(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get current automation settings.

    Returns the active automation configuration for the reputation system.
    """
    try:
        # Get active config or create default
        result = await db.execute(
            select(AutomationConfig).where(AutomationConfig.is_active == True).limit(1)
        )
        config = result.scalar_one_or_none()

        if not config:
            # Create default configuration
            config = AutomationConfig(
                name="Default Configuration",
                global_enabled=False,
                safety_check_enabled=True,
                auto_respond_positive=False,
                auto_respond_threshold=4.0,
                require_approval=True,
                response_delay_hours=2,
                is_active=True
            )
            db.add(config)
            await db.commit()
            await db.refresh(config)

        return AutomationConfigResponse(
            id=config.id,
            name=config.name,
            global_enabled=config.global_enabled,
            safety_check_enabled=config.safety_check_enabled,
            auto_respond_positive=config.auto_respond_positive,
            auto_respond_threshold=config.auto_respond_threshold,
            require_approval=config.require_approval,
            profanity_blocklist=config.profanity_blocklist,
            brand_guidelines=config.brand_guidelines,
            response_delay_hours=config.response_delay_hours,
            rules=config.rules,
            is_active=config.is_active,
            created_at=config.created_at,
            updated_at=config.updated_at
        )

    except Exception as e:
        logger.error(f"Error fetching automation config: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch automation configuration"
        )


@router.patch("/config", response_model=AutomationConfigResponse)
async def update_automation_config(
    updates: AutomationConfigUpdate,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update automation settings.

    Allows partial updates to the automation configuration.
    Only provided fields will be updated.
    """
    try:
        # Get active config
        result = await db.execute(
            select(AutomationConfig).where(AutomationConfig.is_active == True).limit(1)
        )
        config = result.scalar_one_or_none()

        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active automation configuration found"
            )

        # Update only provided fields
        update_data = updates.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(config, field, value)

        config.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(config)

        logger.info(f"Automation config updated by user {current_user.id}: {list(update_data.keys())}")

        return AutomationConfigResponse(
            id=config.id,
            name=config.name,
            global_enabled=config.global_enabled,
            safety_check_enabled=config.safety_check_enabled,
            auto_respond_positive=config.auto_respond_positive,
            auto_respond_threshold=config.auto_respond_threshold,
            require_approval=config.require_approval,
            profanity_blocklist=config.profanity_blocklist,
            brand_guidelines=config.brand_guidelines,
            response_delay_hours=config.response_delay_hours,
            rules=config.rules,
            is_active=config.is_active,
            created_at=config.created_at,
            updated_at=config.updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating automation config: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update automation configuration"
        )


@router.post("/test")
async def test_auto_response_generation(
    request: TestAutoResponseRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Test auto-response generation.

    Generates a test response without saving it. Useful for testing
    configuration changes before enabling automation.
    """
    try:
        review_data = None

        if request.review_id:
            # Fetch actual review
            result = await db.execute(
                select(Review).where(Review.id == request.review_id)
            )
            review = result.scalar_one_or_none()
            if not review:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Review {request.review_id} not found"
                )
            review_data = {
                "rating": review.overall_rating,
                "comment": review.comment,
                "sentiment": review.sentiment,
                "source": review.source
            }
        else:
            # Use provided test data
            review_data = {
                "rating": request.rating or 4.0,
                "comment": request.comment or "This is a test review comment.",
                "sentiment": "positive" if (request.rating or 4.0) >= 4 else (
                    "negative" if (request.rating or 4.0) <= 2 else "neutral"
                ),
                "source": "test"
            }

        # Get config for safety check
        config_result = await db.execute(
            select(AutomationConfig).where(AutomationConfig.is_active == True).limit(1)
        )
        config = config_result.scalar_one_or_none()

        # Generate response based on sentiment
        response_text = await _generate_auto_response(
            sentiment=review_data["sentiment"],
            comment=review_data["comment"],
            tone=request.tone,
            config=config,
            db=db
        )

        # Run safety check if enabled
        safety_result = {"passed": True, "issues": []}
        if config and config.safety_check_enabled:
            safety_result = _run_safety_check(response_text, config)

        return {
            "success": True,
            "test_mode": True,
            "input": {
                "rating": review_data["rating"],
                "sentiment": review_data["sentiment"],
                "tone": request.tone
            },
            "generated_response": response_text,
            "safety_check": safety_result,
            "would_auto_approve": (
                config and
                config.global_enabled and
                config.auto_respond_positive and
                review_data["rating"] >= config.auto_respond_threshold and
                safety_result["passed"] and
                not config.require_approval
            ),
            "generated_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing auto-response: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate test response"
        )


@router.get("/templates")
async def get_response_templates(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get response templates from database.

    Returns templates for positive, neutral, and negative reviews.
    Falls back to DEFAULT_TEMPLATES if no database templates exist.
    """
    try:
        # Fetch templates from ResponseTemplate table
        result = await db.execute(
            select(ResponseTemplate).where(ResponseTemplate.is_active == True)
        )
        db_templates = result.scalars().all()

        templates = {}

        # Group templates by sentiment
        for template in db_templates:
            sentiment = template.sentiment or "neutral"
            if sentiment not in templates:
                templates[sentiment] = {
                    "id": template.id,
                    "name": template.name,
                    "template_text": template.content,
                    "tone": template.tone,
                    "variables": ["guest_name", "hotel_name", "review_date", "contact_email", "manager_name"],
                    "is_active": template.is_active,
                    "is_default": template.is_default,
                    "created_at": template.created_at.isoformat() if template.created_at else None,
                    "updated_at": template.updated_at.isoformat() if template.updated_at else None
                }
            # If multiple templates exist for same sentiment, prefer default or most recent
            elif template.is_default or (template.updated_at and template.updated_at > datetime.fromisoformat(templates[sentiment].get("updated_at", "2000-01-01T00:00:00"))):
                templates[sentiment] = {
                    "id": template.id,
                    "name": template.name,
                    "template_text": template.content,
                    "tone": template.tone,
                    "variables": ["guest_name", "hotel_name", "review_date", "contact_email", "manager_name"],
                    "is_active": template.is_active,
                    "is_default": template.is_default,
                    "created_at": template.created_at.isoformat() if template.created_at else None,
                    "updated_at": template.updated_at.isoformat() if template.updated_at else None
                }

        # Fill in missing sentiments with defaults
        for template_type in ["positive", "neutral", "negative"]:
            if template_type not in templates:
                templates[template_type] = DEFAULT_TEMPLATES[template_type]

        return {
            "templates": templates,
            "available_variables": [
                {"name": "guest_name", "description": "Guest's name"},
                {"name": "hotel_name", "description": "Hotel name"},
                {"name": "review_date", "description": "Date of review"},
                {"name": "contact_email", "description": "Hotel contact email"},
                {"name": "manager_name", "description": "Manager's name"}
            ],
            "source": "database" if db_templates else "defaults"
        }

    except Exception as e:
        logger.error(f"Error fetching templates: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch response templates"
        )


@router.put("/templates/{template_type}")
async def update_response_template(
    template_type: str,
    template: ResponseTemplateUpdate,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update or create a response template in the database.

    Updates template for specified sentiment type (positive, neutral, or negative).
    If no template exists for this sentiment, creates a new one.
    """
    if template_type not in ["positive", "neutral", "negative"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template type must be 'positive', 'neutral', or 'negative'"
        )

    try:
        # Check if template exists for this sentiment
        result = await db.execute(
            select(ResponseTemplate).where(
                ResponseTemplate.sentiment == template_type,
                ResponseTemplate.is_active == True
            ).order_by(ResponseTemplate.is_default.desc()).limit(1)
        )
        existing_template = result.scalar_one_or_none()

        if existing_template:
            # Update existing template
            existing_template.content = template.template_text
            existing_template.is_active = template.is_active
            existing_template.updated_at = datetime.utcnow()

            await db.commit()
            await db.refresh(existing_template)

            logger.info(f"Template '{template_type}' (id={existing_template.id}) updated by user {current_user.id}")

            return {
                "success": True,
                "message": f"Template '{template_type}' updated successfully",
                "template": {
                    "id": existing_template.id,
                    "name": existing_template.name,
                    "template_text": existing_template.content,
                    "tone": existing_template.tone,
                    "sentiment": existing_template.sentiment,
                    "variables": template.variables or ["guest_name", "hotel_name", "review_date", "contact_email", "manager_name"],
                    "is_active": existing_template.is_active,
                    "updated_at": existing_template.updated_at.isoformat()
                }
            }
        else:
            # Create new template
            new_template = ResponseTemplate(
                name=f"Auto-Reply {template_type.capitalize()} Template",
                content=template.template_text,
                tone="professional",
                sentiment=template_type,
                is_active=template.is_active,
                is_default=True
            )
            db.add(new_template)
            await db.commit()
            await db.refresh(new_template)

            logger.info(f"Template '{template_type}' (id={new_template.id}) created by user {current_user.id}")

            return {
                "success": True,
                "message": f"Template '{template_type}' created successfully",
                "template": {
                    "id": new_template.id,
                    "name": new_template.name,
                    "template_text": new_template.content,
                    "tone": new_template.tone,
                    "sentiment": new_template.sentiment,
                    "variables": template.variables or ["guest_name", "hotel_name", "review_date", "contact_email", "manager_name"],
                    "is_active": new_template.is_active,
                    "created_at": new_template.created_at.isoformat()
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating template: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update template"
        )


@router.post("/run")
async def run_auto_response(
    request: RunAutomationRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Manually run auto-response on pending reviews.

    Processes reviews that haven't been responded to yet and generates
    AI response drafts based on current automation settings.
    """
    try:
        # Get config
        config_result = await db.execute(
            select(AutomationConfig).where(AutomationConfig.is_active == True).limit(1)
        )
        config = config_result.scalar_one_or_none()

        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active automation configuration found"
            )

        # Build query for pending reviews
        query = select(Review).where(Review.response == None)

        if request.min_rating:
            query = query.where(Review.overall_rating >= request.min_rating)
        elif config.auto_respond_positive:
            query = query.where(Review.overall_rating >= config.auto_respond_threshold)

        query = query.order_by(Review.review_date.desc()).limit(request.limit)

        result = await db.execute(query)
        reviews = result.scalars().all()

        processed = []
        skipped = []

        for review in reviews:
            # Check if draft already exists
            existing_draft = await db.execute(
                select(ResponseDraft).where(ResponseDraft.review_id == review.id)
            )
            if existing_draft.scalar_one_or_none():
                skipped.append({
                    "review_id": review.id,
                    "reason": "Draft already exists"
                })
                continue

            # Generate response
            response_text = await _generate_auto_response(
                sentiment=review.sentiment or "neutral",
                comment=review.comment,
                tone="professional",
                config=config,
                db=db
            )

            # Run safety check
            safety_result = {"passed": True, "issues": []}
            if config.safety_check_enabled:
                safety_result = _run_safety_check(response_text, config)

            if not safety_result["passed"]:
                skipped.append({
                    "review_id": review.id,
                    "reason": "Failed safety check",
                    "issues": safety_result["issues"]
                })
                continue

            if not request.dry_run:
                # Create draft
                draft = ResponseDraft(
                    review_id=review.id,
                    draft_text=response_text,
                    status="pending",
                    current_stage="draft" if config.require_approval else "ready",
                    tone="professional",
                    confidence_score=0.80
                )
                db.add(draft)

            processed.append({
                "review_id": review.id,
                "rating": review.overall_rating,
                "sentiment": review.sentiment,
                "response_preview": response_text[:200] + "..." if len(response_text) > 200 else response_text,
                "status": "draft_created" if not request.dry_run else "would_create_draft"
            })

        if not request.dry_run:
            await db.commit()

        logger.info(
            f"Auto-response run completed by user {current_user.id}: "
            f"processed={len(processed)}, skipped={len(skipped)}, dry_run={request.dry_run}"
        )

        return {
            "success": True,
            "dry_run": request.dry_run,
            "processed_count": len(processed),
            "skipped_count": len(skipped),
            "processed": processed,
            "skipped": skipped,
            "run_at": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running auto-response: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to run auto-response"
        )


@router.get("/stats")
async def get_automation_stats(
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get automation statistics.

    Returns statistics about automated responses and system performance.
    Uses parallel queries for better performance.
    """
    try:
        from datetime import timedelta
        week_ago = datetime.utcnow() - timedelta(days=7)

        # Define all queries as coroutines for parallel execution
        async def get_draft_counts():
            """Get all draft counts in a single batched query using CASE"""
            result = await db.execute(
                select(
                    func.count(ResponseDraft.id).filter(ResponseDraft.status == "pending").label("pending"),
                    func.count(ResponseDraft.id).filter(ResponseDraft.status == "approved").label("approved"),
                    func.count(ResponseDraft.id).filter(ResponseDraft.status == "rejected").label("rejected"),
                    func.count(ResponseDraft.id).filter(ResponseDraft.status == "published").label("published")
                )
            )
            row = result.one()
            return {
                "pending": row.pending or 0,
                "approved": row.approved or 0,
                "rejected": row.rejected or 0,
                "published": row.published or 0
            }

        async def get_pending_reviews():
            result = await db.execute(
                select(func.count(Review.id)).where(Review.response == None)
            )
            return result.scalar() or 0

        async def get_recent_stats():
            """Get recent drafts and auto-approved in single query"""
            result = await db.execute(
                select(
                    func.count(ResponseDraft.id).label("recent_drafts"),
                    func.count(ResponseDraft.id).filter(
                        ResponseDraft.current_stage == "ready"
                    ).label("auto_approved")
                ).where(ResponseDraft.created_at >= week_ago)
            )
            row = result.one()
            return {
                "recent_drafts": row.recent_drafts or 0,
                "auto_approved": row.auto_approved or 0
            }

        async def get_config():
            result = await db.execute(
                select(AutomationConfig).where(AutomationConfig.is_active == True).limit(1)
            )
            return result.scalar_one_or_none()

        # Execute all queries in parallel
        draft_counts, pending_reviews, recent_stats, config = await asyncio.gather(
            get_draft_counts(),
            get_pending_reviews(),
            get_recent_stats(),
            get_config()
        )

        return {
            "automation_enabled": config.global_enabled if config else False,
            "drafts": {
                "pending": draft_counts["pending"],
                "approved": draft_counts["approved"],
                "rejected": draft_counts["rejected"],
                "published": draft_counts["published"],
                "total": sum(draft_counts.values())
            },
            "reviews_pending_response": pending_reviews,
            "last_7_days": {
                "drafts_created": recent_stats["recent_drafts"],
                "auto_approved": recent_stats["auto_approved"]
            },
            "config": {
                "auto_respond_positive": config.auto_respond_positive if config else False,
                "threshold": config.auto_respond_threshold if config else 4.0,
                "require_approval": config.require_approval if config else True
            } if config else None
        }

    except Exception as e:
        logger.error(f"Error fetching automation stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch automation statistics"
        )


# ==================== HELPER FUNCTIONS ====================

async def _generate_auto_response(
    sentiment: str,
    comment: Optional[str],
    tone: str,
    config: Optional[AutomationConfig],
    db: Optional[AsyncSession] = None
) -> str:
    """Generate automated response based on sentiment and configuration.

    Fetches templates from ResponseTemplate database table.
    Falls back to DEFAULT_TEMPLATES if no database template exists.
    """

    # Get template based on sentiment
    template_type = sentiment if sentiment in ["positive", "neutral", "negative"] else "neutral"
    template_text = None

    # Try to get template from database
    if db:
        try:
            result = await db.execute(
                select(ResponseTemplate).where(
                    ResponseTemplate.sentiment == template_type,
                    ResponseTemplate.is_active == True
                ).order_by(ResponseTemplate.is_default.desc()).limit(1)
            )
            db_template = result.scalar_one_or_none()
            if db_template:
                template_text = db_template.content
                logger.info(f"Using database template id={db_template.id} for sentiment={template_type}")
        except Exception as e:
            logger.warning(f"Failed to fetch template from database: {e}")

    # Fall back to default templates
    if not template_text:
        template_text = DEFAULT_TEMPLATES[template_type]["template_text"]
        logger.info(f"Using default template for sentiment={template_type}")

    # Replace placeholders with generic values
    # In production, these would be fetched from guest/hotel data
    try:
        response = template_text.format(
            guest_name="Valued Guest",
            hotel_name="Glimmora",
            review_date=datetime.utcnow().strftime("%B %d, %Y"),
            contact_email="info@glimmora.com",
            manager_name="The Management"
        )
    except KeyError as e:
        # Handle missing placeholders gracefully
        logger.warning(f"Template has unrecognized placeholder: {e}")
        response = template_text

    return response


def _run_safety_check(response_text: str, config: AutomationConfig) -> Dict[str, Any]:
    """Run content safety checks on generated response."""

    issues = []

    # Check for profanity
    if config.profanity_blocklist:
        response_lower = response_text.lower()
        for word in config.profanity_blocklist:
            if word.lower() in response_lower:
                issues.append(f"Contains blocked word: {word}")

    # Check response length
    if len(response_text) < 50:
        issues.append("Response too short (minimum 50 characters)")
    if len(response_text) > 2000:
        issues.append("Response too long (maximum 2000 characters)")

    # Check for placeholder remnants
    if "{" in response_text and "}" in response_text:
        issues.append("Contains unreplaced placeholders")

    return {
        "passed": len(issues) == 0,
        "issues": issues
    }
