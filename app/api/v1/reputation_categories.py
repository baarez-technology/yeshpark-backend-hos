"""
Category Management API Routes
Reputation AI Module - Glimmora Hotel Management System
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user_optional, get_current_user
from app.models.user import User
from app.models.reputation import (
    ReviewCategory,
    ReviewCategoryAssignment,
    CategoryRoutingRule
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== PYDANTIC SCHEMAS ====================

class CreateCategoryRequest(BaseModel):
    """Request schema for creating a category"""
    name: str = Field(..., min_length=1, max_length=100, description="Category name")
    description: Optional[str] = Field(None, description="Category description")
    parent_id: Optional[int] = Field(None, description="Parent category ID for hierarchical structure")
    icon: Optional[str] = Field(None, description="Lucide icon name")
    color: Optional[str] = Field(None, description="Hex color code for UI")
    sort_order: int = Field(default=0, description="Display order")


class UpdateCategoryRequest(BaseModel):
    """Request schema for updating a category"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Category name")
    description: Optional[str] = Field(None, description="Category description")
    parent_id: Optional[int] = Field(None, description="Parent category ID")
    icon: Optional[str] = Field(None, description="Lucide icon name")
    color: Optional[str] = Field(None, description="Hex color code")
    sort_order: Optional[int] = Field(None, description="Display order")
    is_active: Optional[bool] = Field(None, description="Active status")


class RoutingRuleRequest(BaseModel):
    """Request schema for routing rules"""
    target_department: str = Field(..., description="Target department: maintenance, housekeeping, frontdesk")
    default_priority: str = Field(default="medium", description="Priority: low, medium, high, critical")
    auto_create_ticket: bool = Field(default=False, description="Auto-create work ticket")
    notify_manager: bool = Field(default=True, description="Notify department manager")
    escalation_hours: Optional[int] = Field(None, ge=1, le=168, description="Hours before escalation")
    is_active: bool = Field(default=True, description="Rule active status")


class CategoryResponse(BaseModel):
    """Response schema for category"""
    id: int
    name: str
    description: Optional[str]
    parent_id: Optional[int]
    icon: Optional[str]
    color: Optional[str]
    is_active: bool
    sort_order: int
    created_at: datetime
    review_count: int = 0
    children: List["CategoryResponse"] = []

    class Config:
        from_attributes = True


class RoutingRuleResponse(BaseModel):
    """Response schema for routing rule"""
    id: int
    category_id: int
    target_department: str
    default_priority: str
    auto_create_ticket: bool
    notify_manager: bool
    escalation_hours: Optional[int]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# Enable forward reference resolution
CategoryResponse.model_rebuild()


# ==================== CATEGORY ENDPOINTS ====================

@router.get("/", response_model=List[CategoryResponse])
async def list_categories(
    include_inactive: bool = Query(False, description="Include inactive categories"),
    flat: bool = Query(False, description="Return flat list instead of tree structure"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    List all categories.

    Returns categories in hierarchical tree structure by default.
    Use `flat=true` for a flat list.
    """
    try:
        # Build query
        query = select(ReviewCategory)
        if not include_inactive:
            query = query.where(ReviewCategory.is_active == True)
        query = query.order_by(ReviewCategory.sort_order, ReviewCategory.name)

        result = await db.execute(query)
        categories = result.scalars().all()

        # Get review counts for each category
        review_counts = {}
        for cat in categories:
            count_result = await db.execute(
                select(func.count(ReviewCategoryAssignment.id)).where(
                    ReviewCategoryAssignment.category_id == cat.id
                )
            )
            review_counts[cat.id] = count_result.scalar() or 0

        if flat:
            # Return flat list
            return [
                CategoryResponse(
                    id=cat.id,
                    name=cat.name,
                    description=cat.description,
                    parent_id=cat.parent_id,
                    icon=cat.icon,
                    color=cat.color,
                    is_active=cat.is_active,
                    sort_order=cat.sort_order,
                    created_at=cat.created_at,
                    review_count=review_counts.get(cat.id, 0),
                    children=[]
                )
                for cat in categories
            ]

        # Build tree structure
        category_map = {}
        root_categories = []

        for cat in categories:
            cat_response = CategoryResponse(
                id=cat.id,
                name=cat.name,
                description=cat.description,
                parent_id=cat.parent_id,
                icon=cat.icon,
                color=cat.color,
                is_active=cat.is_active,
                sort_order=cat.sort_order,
                created_at=cat.created_at,
                review_count=review_counts.get(cat.id, 0),
                children=[]
            )
            category_map[cat.id] = cat_response

        # Second pass to build tree
        for cat in categories:
            cat_response = category_map[cat.id]
            if cat.parent_id and cat.parent_id in category_map:
                category_map[cat.parent_id].children.append(cat_response)
            else:
                root_categories.append(cat_response)

        return root_categories

    except Exception as e:
        logger.error(f"Error listing categories: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list categories"
        )


@router.post("/", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    request: CreateCategoryRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new category.

    Categories can be hierarchical by specifying a parent_id.
    """
    try:
        # Validate parent exists if specified
        if request.parent_id:
            parent_result = await db.execute(
                select(ReviewCategory).where(ReviewCategory.id == request.parent_id)
            )
            if not parent_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Parent category {request.parent_id} not found"
                )

        # Check for duplicate name at same level
        duplicate_query = select(ReviewCategory).where(
            and_(
                ReviewCategory.name == request.name,
                ReviewCategory.parent_id == request.parent_id
            )
        )
        duplicate = await db.execute(duplicate_query)
        if duplicate.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Category '{request.name}' already exists at this level"
            )

        # Create category
        category = ReviewCategory(
            name=request.name,
            description=request.description,
            parent_id=request.parent_id,
            icon=request.icon,
            color=request.color,
            sort_order=request.sort_order,
            is_active=True
        )

        db.add(category)
        await db.commit()
        await db.refresh(category)

        logger.info(f"Category '{category.name}' (id={category.id}) created by user {current_user.id}")

        return CategoryResponse(
            id=category.id,
            name=category.name,
            description=category.description,
            parent_id=category.parent_id,
            icon=category.icon,
            color=category.color,
            is_active=category.is_active,
            sort_order=category.sort_order,
            created_at=category.created_at,
            review_count=0,
            children=[]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating category: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create category"
        )


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get category details.

    Returns category with its children and review count.
    """
    try:
        result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.id == category_id)
        )
        category = result.scalar_one_or_none()

        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category {category_id} not found"
            )

        # Get review count
        count_result = await db.execute(
            select(func.count(ReviewCategoryAssignment.id)).where(
                ReviewCategoryAssignment.category_id == category_id
            )
        )
        review_count = count_result.scalar() or 0

        # Get children
        children_result = await db.execute(
            select(ReviewCategory).where(
                and_(
                    ReviewCategory.parent_id == category_id,
                    ReviewCategory.is_active == True
                )
            ).order_by(ReviewCategory.sort_order, ReviewCategory.name)
        )
        children = children_result.scalars().all()

        children_responses = []
        for child in children:
            child_count_result = await db.execute(
                select(func.count(ReviewCategoryAssignment.id)).where(
                    ReviewCategoryAssignment.category_id == child.id
                )
            )
            child_count = child_count_result.scalar() or 0
            children_responses.append(CategoryResponse(
                id=child.id,
                name=child.name,
                description=child.description,
                parent_id=child.parent_id,
                icon=child.icon,
                color=child.color,
                is_active=child.is_active,
                sort_order=child.sort_order,
                created_at=child.created_at,
                review_count=child_count,
                children=[]
            ))

        return CategoryResponse(
            id=category.id,
            name=category.name,
            description=category.description,
            parent_id=category.parent_id,
            icon=category.icon,
            color=category.color,
            is_active=category.is_active,
            sort_order=category.sort_order,
            created_at=category.created_at,
            review_count=review_count,
            children=children_responses
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting category: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get category"
        )


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    request: UpdateCategoryRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update a category.

    Allows partial updates - only provided fields will be changed.
    """
    try:
        result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.id == category_id)
        )
        category = result.scalar_one_or_none()

        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category {category_id} not found"
            )

        # Validate parent if changed
        if request.parent_id is not None and request.parent_id != category.parent_id:
            if request.parent_id == category_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Category cannot be its own parent"
                )
            if request.parent_id:
                parent_result = await db.execute(
                    select(ReviewCategory).where(ReviewCategory.id == request.parent_id)
                )
                if not parent_result.scalar_one_or_none():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Parent category {request.parent_id} not found"
                    )

        # Check for circular reference
        if request.parent_id:
            current_parent = request.parent_id
            visited = {category_id}
            while current_parent:
                if current_parent in visited:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Circular parent reference detected"
                    )
                visited.add(current_parent)
                parent_check = await db.execute(
                    select(ReviewCategory.parent_id).where(ReviewCategory.id == current_parent)
                )
                current_parent = parent_check.scalar()

        # Update fields
        update_data = request.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(category, field, value)

        await db.commit()
        await db.refresh(category)

        # Get review count
        count_result = await db.execute(
            select(func.count(ReviewCategoryAssignment.id)).where(
                ReviewCategoryAssignment.category_id == category_id
            )
        )
        review_count = count_result.scalar() or 0

        logger.info(f"Category {category_id} updated by user {current_user.id}")

        return CategoryResponse(
            id=category.id,
            name=category.name,
            description=category.description,
            parent_id=category.parent_id,
            icon=category.icon,
            color=category.color,
            is_active=category.is_active,
            sort_order=category.sort_order,
            created_at=category.created_at,
            review_count=review_count,
            children=[]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating category: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update category"
        )


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    hard_delete: bool = Query(False, description="Permanently delete (default is soft delete)"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a category (soft delete by default).

    Soft delete sets is_active=False. Hard delete removes the record.
    Children are not deleted but become root-level categories.
    """
    try:
        result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.id == category_id)
        )
        category = result.scalar_one_or_none()

        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category {category_id} not found"
            )

        # Check for review assignments
        assignment_count = await db.execute(
            select(func.count(ReviewCategoryAssignment.id)).where(
                ReviewCategoryAssignment.category_id == category_id
            )
        )
        assignments = assignment_count.scalar() or 0

        if hard_delete and assignments > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot hard delete category with {assignments} review assignments. Use soft delete instead."
            )

        # Update children to have no parent
        await db.execute(
            select(ReviewCategory).where(ReviewCategory.parent_id == category_id)
        )
        children_result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.parent_id == category_id)
        )
        for child in children_result.scalars().all():
            child.parent_id = None

        if hard_delete:
            # Delete routing rules first
            rules_result = await db.execute(
                select(CategoryRoutingRule).where(CategoryRoutingRule.category_id == category_id)
            )
            for rule in rules_result.scalars().all():
                await db.delete(rule)

            await db.delete(category)
            message = f"Category '{category.name}' permanently deleted"
        else:
            category.is_active = False
            message = f"Category '{category.name}' deactivated"

        await db.commit()

        logger.info(f"Category {category_id} {'hard' if hard_delete else 'soft'} deleted by user {current_user.id}")

        return {
            "success": True,
            "message": message,
            "category_id": category_id,
            "hard_delete": hard_delete
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting category: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete category"
        )


# ==================== ROUTING RULES ENDPOINTS ====================

@router.get("/{category_id}/routing", response_model=List[RoutingRuleResponse])
async def get_category_routing(
    category_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get routing rules for a category.

    Returns all routing rules configured for the specified category.
    """
    try:
        # Verify category exists
        cat_result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.id == category_id)
        )
        if not cat_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category {category_id} not found"
            )

        # Get routing rules
        result = await db.execute(
            select(CategoryRoutingRule).where(
                CategoryRoutingRule.category_id == category_id
            ).order_by(CategoryRoutingRule.created_at)
        )
        rules = result.scalars().all()

        return [
            RoutingRuleResponse(
                id=rule.id,
                category_id=rule.category_id,
                target_department=rule.target_department,
                default_priority=rule.default_priority,
                auto_create_ticket=rule.auto_create_ticket,
                notify_manager=rule.notify_manager,
                escalation_hours=rule.escalation_hours,
                is_active=rule.is_active,
                created_at=rule.created_at
            )
            for rule in rules
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting routing rules: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get routing rules"
        )


@router.put("/{category_id}/routing", response_model=RoutingRuleResponse)
async def update_category_routing(
    category_id: int,
    request: RoutingRuleRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update routing rules for a category.

    Creates or updates the routing rule for the specified department.
    """
    try:
        # Verify category exists
        cat_result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.id == category_id)
        )
        if not cat_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category {category_id} not found"
            )

        # Check if rule exists for this department
        existing_result = await db.execute(
            select(CategoryRoutingRule).where(
                and_(
                    CategoryRoutingRule.category_id == category_id,
                    CategoryRoutingRule.target_department == request.target_department
                )
            )
        )
        rule = existing_result.scalar_one_or_none()

        if rule:
            # Update existing rule
            rule.default_priority = request.default_priority
            rule.auto_create_ticket = request.auto_create_ticket
            rule.notify_manager = request.notify_manager
            rule.escalation_hours = request.escalation_hours
            rule.is_active = request.is_active
        else:
            # Create new rule
            rule = CategoryRoutingRule(
                category_id=category_id,
                target_department=request.target_department,
                default_priority=request.default_priority,
                auto_create_ticket=request.auto_create_ticket,
                notify_manager=request.notify_manager,
                escalation_hours=request.escalation_hours,
                is_active=request.is_active
            )
            db.add(rule)

        await db.commit()
        await db.refresh(rule)

        logger.info(f"Routing rule for category {category_id} updated by user {current_user.id}")

        return RoutingRuleResponse(
            id=rule.id,
            category_id=rule.category_id,
            target_department=rule.target_department,
            default_priority=rule.default_priority,
            auto_create_ticket=rule.auto_create_ticket,
            notify_manager=rule.notify_manager,
            escalation_hours=rule.escalation_hours,
            is_active=rule.is_active,
            created_at=rule.created_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating routing rule: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update routing rule"
        )


@router.delete("/{category_id}/routing/{rule_id}")
async def delete_routing_rule(
    category_id: int,
    rule_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a routing rule.
    """
    try:
        result = await db.execute(
            select(CategoryRoutingRule).where(
                and_(
                    CategoryRoutingRule.id == rule_id,
                    CategoryRoutingRule.category_id == category_id
                )
            )
        )
        rule = result.scalar_one_or_none()

        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Routing rule {rule_id} not found for category {category_id}"
            )

        await db.delete(rule)
        await db.commit()

        logger.info(f"Routing rule {rule_id} deleted by user {current_user.id}")

        return {
            "success": True,
            "message": "Routing rule deleted successfully",
            "rule_id": rule_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting routing rule: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete routing rule"
        )


# ==================== CATEGORY STATS ====================

@router.get("/{category_id}/stats")
async def get_category_stats(
    category_id: int,
    days: int = Query(30, ge=1, le=365, description="Days of history to analyze"),
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Get statistics for a category.

    Returns review distribution, sentiment breakdown, and trends.
    """
    try:
        from datetime import timedelta
        from app.models.reviews import Review

        # Verify category exists
        cat_result = await db.execute(
            select(ReviewCategory).where(ReviewCategory.id == category_id)
        )
        category = cat_result.scalar_one_or_none()

        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category {category_id} not found"
            )

        start_date = datetime.utcnow() - timedelta(days=days)

        # Get total reviews in period
        reviews_query = select(Review).join(
            ReviewCategoryAssignment,
            Review.id == ReviewCategoryAssignment.review_id
        ).where(
            and_(
                ReviewCategoryAssignment.category_id == category_id,
                Review.review_date >= start_date
            )
        )

        result = await db.execute(reviews_query)
        reviews = result.scalars().all()

        # Calculate stats
        total_reviews = len(reviews)
        if total_reviews == 0:
            return {
                "category_id": category_id,
                "category_name": category.name,
                "period_days": days,
                "total_reviews": 0,
                "average_rating": None,
                "sentiment_breakdown": {"positive": 0, "neutral": 0, "negative": 0},
                "rating_distribution": {},
                "response_rate": 0
            }

        # Average rating
        avg_rating = sum(r.overall_rating for r in reviews if r.overall_rating) / len([r for r in reviews if r.overall_rating])

        # Sentiment breakdown
        sentiment = {"positive": 0, "neutral": 0, "negative": 0}
        for r in reviews:
            if r.sentiment in sentiment:
                sentiment[r.sentiment] += 1

        # Rating distribution
        rating_dist = {}
        for r in reviews:
            if r.overall_rating:
                rating = int(r.overall_rating)
                rating_dist[rating] = rating_dist.get(rating, 0) + 1

        # Response rate
        responded = len([r for r in reviews if r.response])
        response_rate = (responded / total_reviews * 100) if total_reviews > 0 else 0

        return {
            "category_id": category_id,
            "category_name": category.name,
            "period_days": days,
            "total_reviews": total_reviews,
            "average_rating": round(avg_rating, 2),
            "sentiment_breakdown": sentiment,
            "rating_distribution": rating_dist,
            "response_rate": round(response_rate, 1),
            "responded_count": responded
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting category stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get category statistics"
        )
