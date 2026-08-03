"""
Category Detector Service
Detects and assigns categories to reviews, manages routing rules,
and auto-routes reviews to appropriate departments.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reviews import Review
from app.models.reputation import (
    ReviewCategory,
    ReviewCategoryAssignment,
    CategoryRoutingRule,
    TrendWorkOrder,
    TrendAlert
)

logger = logging.getLogger(__name__)


class CategoryDetector:
    """Detect and assign categories to reviews"""

    # Default category keywords for fallback detection
    DEFAULT_KEYWORDS = {
        "room": [
            "room", "suite", "bed", "bedroom", "bathroom", "shower", "bath", "view",
            "balcony", "space", "mattress", "pillow", "linens", "towel", "mini bar",
            "tv", "television", "air conditioning", "ac", "heating", "window"
        ],
        "service": [
            "service", "staff", "employee", "reception", "receptionist", "concierge",
            "housekeeping", "housekeeper", "bellboy", "porter", "manager", "helpful",
            "friendly", "rude", "attentive", "professional", "response", "attitude"
        ],
        "food": [
            "food", "breakfast", "lunch", "dinner", "restaurant", "dining", "meal",
            "coffee", "menu", "buffet", "chef", "waiter", "waitress", "bar", "drink",
            "cuisine", "taste", "portion", "quality"
        ],
        "cleanliness": [
            "clean", "dirty", "spotless", "tidy", "hygiene", "sanitary", "dust",
            "stain", "mold", "smell", "odor", "fresh", "pristine", "immaculate",
            "filthy", "grimy", "hair", "insect", "bug"
        ],
        "location": [
            "location", "area", "neighborhood", "walking", "distance", "beach",
            "city", "transport", "bus", "metro", "taxi", "nearby", "convenient",
            "central", "quiet", "safe", "scenic", "view"
        ],
        "amenities": [
            "pool", "spa", "gym", "fitness", "wifi", "internet", "parking",
            "facilities", "amenities", "elevator", "lobby", "lounge", "garden",
            "terrace", "sauna", "jacuzzi"
        ],
        "value": [
            "price", "value", "worth", "expensive", "cheap", "cost", "money",
            "rate", "deal", "affordable", "overpriced", "reasonable", "budget"
        ],
        "check-in": [
            "check-in", "checkin", "check in", "check-out", "checkout", "check out",
            "arrival", "departure", "welcome", "front desk", "lobby", "key",
            "registration", "waiting", "queue"
        ],
        "noise": [
            "noise", "noisy", "loud", "quiet", "sound", "neighbor", "music",
            "traffic", "construction", "peaceful", "disturb", "sleep"
        ],
        "maintenance": [
            "broken", "fix", "repair", "maintenance", "leak", "damage", "work",
            "malfunction", "issue", "problem", "faulty", "not working"
        ]
    }

    def __init__(
        self,
        db: AsyncSession,
        openai_service: Optional["ReputationOpenAIService"] = None
    ):
        """
        Initialize CategoryDetector.

        Args:
            db: Database session
            openai_service: Optional OpenAI service for AI-powered detection
        """
        self.db = db
        self.openai_service = openai_service
        self._categories_cache: Optional[List[Dict]] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minute cache

    async def detect_categories(
        self,
        review_text: str,
        use_ai: bool = True,
        min_confidence: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Detect categories from review text.

        Uses keyword matching first for speed, then OpenAI for better accuracy
        when available and enabled.

        Args:
            review_text: The review text to analyze
            use_ai: Whether to use AI for detection (default True)
            min_confidence: Minimum confidence threshold (default 0.5)

        Returns:
            List of detected categories with confidence and evidence
        """
        if not review_text:
            return []

        # Get available categories from database
        categories = await self._get_categories()

        if not categories:
            logger.warning("No categories found in database")
            return []

        # First pass: keyword-based detection (always run for speed)
        keyword_results = self._detect_by_keywords(review_text, categories)

        # Second pass: AI-based detection if available and enabled
        if use_ai and self.openai_service and self.openai_service.is_enabled:
            try:
                ai_results = await self.openai_service.detect_categories(
                    review_text,
                    categories
                )

                # Merge results, preferring AI confidence but keeping keyword matches
                merged = self._merge_detection_results(keyword_results, ai_results)
                return [r for r in merged if r.get("confidence", 0) >= min_confidence]
            except Exception as e:
                logger.warning(f"AI category detection failed, using keyword results: {e}")

        # Return keyword results filtered by confidence
        return [r for r in keyword_results if r.get("confidence", 0) >= min_confidence]

    async def assign_to_review(
        self,
        review_id: int,
        categories: List[Dict[str, Any]],
        is_ai_generated: bool = True
    ) -> List[ReviewCategoryAssignment]:
        """
        Assign detected categories to a review.

        Args:
            review_id: ID of the review
            categories: List of category detections with category_id and confidence
            is_ai_generated: Whether the assignment was AI-generated

        Returns:
            List of created ReviewCategoryAssignment records
        """
        assignments = []

        for cat in categories:
            category_id = cat.get("category_id")
            confidence = cat.get("confidence", 0.5)

            if not category_id:
                continue

            # Check if assignment already exists
            existing = await self.db.execute(
                select(ReviewCategoryAssignment).where(
                    ReviewCategoryAssignment.review_id == review_id,
                    ReviewCategoryAssignment.category_id == category_id
                )
            )
            if existing.scalar_one_or_none():
                continue

            assignment = ReviewCategoryAssignment(
                review_id=review_id,
                category_id=category_id,
                confidence_score=confidence,
                is_ai_generated=is_ai_generated
            )
            self.db.add(assignment)
            assignments.append(assignment)

        if assignments:
            await self.db.commit()
            for a in assignments:
                await self.db.refresh(a)

        return assignments

    async def get_routing_rules(self, category_id: int) -> Optional[Dict[str, Any]]:
        """
        Get routing rules for a category.

        Args:
            category_id: ID of the category

        Returns:
            Dictionary with routing configuration or None
        """
        stmt = select(CategoryRoutingRule).where(
            CategoryRoutingRule.category_id == category_id,
            CategoryRoutingRule.is_active == True
        )
        result = await self.db.execute(stmt)
        rule = result.scalar_one_or_none()

        if not rule:
            return None

        return {
            "id": rule.id,
            "category_id": rule.category_id,
            "target_department": rule.target_department,
            "default_priority": rule.default_priority,
            "auto_create_ticket": rule.auto_create_ticket,
            "notify_manager": rule.notify_manager,
            "escalation_hours": rule.escalation_hours
        }

    async def auto_route_review(
        self,
        review_id: int,
        detected_categories: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Auto-route a review based on detected categories.

        Creates work orders if auto_create_ticket is enabled for any category.

        Args:
            review_id: ID of the review to route
            detected_categories: Pre-detected categories (will detect if not provided)

        Returns:
            Dictionary with routing results including created work orders
        """
        # Get review
        review_result = await self.db.execute(
            select(Review).where(Review.id == review_id)
        )
        review = review_result.scalar_one_or_none()

        if not review:
            logger.error(f"Review {review_id} not found for routing")
            return {"success": False, "error": "Review not found"}

        # Get or detect categories
        if detected_categories is None:
            comment = review.comment or ""
            detected_categories = await self.detect_categories(comment)

        if not detected_categories:
            return {
                "success": True,
                "review_id": review_id,
                "categories_detected": 0,
                "work_orders_created": [],
                "notifications_sent": []
            }

        # Assign categories to review
        await self.assign_to_review(review_id, detected_categories)

        work_orders_created = []
        notifications_sent = []

        # Check routing rules for each category
        for cat in detected_categories:
            category_id = cat.get("category_id")
            if not category_id:
                continue

            routing_rule = await self.get_routing_rules(category_id)
            if not routing_rule:
                continue

            # Create work order if auto_create_ticket is enabled
            if routing_rule.get("auto_create_ticket"):
                work_order = await self._create_work_order_from_review(
                    review=review,
                    category=cat,
                    routing_rule=routing_rule
                )
                if work_order:
                    work_orders_created.append({
                        "id": work_order.id,
                        "category": cat.get("category_name"),
                        "department": routing_rule.get("target_department"),
                        "priority": routing_rule.get("default_priority")
                    })

            # Track notification intent (actual sending done elsewhere)
            if routing_rule.get("notify_manager"):
                notifications_sent.append({
                    "category": cat.get("category_name"),
                    "department": routing_rule.get("target_department")
                })

        return {
            "success": True,
            "review_id": review_id,
            "categories_detected": len(detected_categories),
            "categories": [c.get("category_name") for c in detected_categories],
            "work_orders_created": work_orders_created,
            "notifications_pending": notifications_sent
        }

    async def get_review_categories(self, review_id: int) -> List[Dict[str, Any]]:
        """
        Get all categories assigned to a review.

        Args:
            review_id: ID of the review

        Returns:
            List of assigned categories with details
        """
        stmt = select(
            ReviewCategoryAssignment,
            ReviewCategory
        ).join(
            ReviewCategory,
            ReviewCategoryAssignment.category_id == ReviewCategory.id
        ).where(
            ReviewCategoryAssignment.review_id == review_id
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "assignment_id": row[0].id,
                "category_id": row[1].id,
                "category_name": row[1].name,
                "category_description": row[1].description,
                "confidence_score": row[0].confidence_score,
                "is_ai_generated": row[0].is_ai_generated,
                "assigned_at": row[0].created_at.isoformat() if row[0].created_at else None
            }
            for row in rows
        ]

    async def bulk_categorize_reviews(
        self,
        review_ids: List[int],
        use_ai: bool = True
    ) -> Dict[str, Any]:
        """
        Categorize multiple reviews in bulk.

        Args:
            review_ids: List of review IDs to categorize
            use_ai: Whether to use AI for detection

        Returns:
            Summary of categorization results
        """
        results = {
            "total": len(review_ids),
            "processed": 0,
            "categories_assigned": 0,
            "errors": []
        }

        for review_id in review_ids:
            try:
                review_result = await self.db.execute(
                    select(Review).where(Review.id == review_id)
                )
                review = review_result.scalar_one_or_none()

                if not review:
                    results["errors"].append(f"Review {review_id} not found")
                    continue

                comment = review.comment or ""
                if not comment:
                    continue

                categories = await self.detect_categories(comment, use_ai=use_ai)
                if categories:
                    await self.assign_to_review(review_id, categories)
                    results["categories_assigned"] += len(categories)

                results["processed"] += 1

            except Exception as e:
                logger.error(f"Error categorizing review {review_id}: {e}")
                results["errors"].append(f"Review {review_id}: {str(e)}")

        return results

    # ==================== PRIVATE METHODS ====================

    async def _get_categories(self) -> List[Dict[str, Any]]:
        """Get categories from database with caching"""
        now = datetime.utcnow()

        # Check cache validity
        if (
            self._categories_cache is not None
            and self._cache_timestamp is not None
            and (now - self._cache_timestamp).total_seconds() < self._cache_ttl_seconds
        ):
            return self._categories_cache

        # Fetch from database
        stmt = select(ReviewCategory).where(ReviewCategory.is_active == True)
        result = await self.db.execute(stmt)
        categories = result.scalars().all()

        self._categories_cache = [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "parent_id": c.parent_id
            }
            for c in categories
        ]
        self._cache_timestamp = now

        return self._categories_cache

    def _detect_by_keywords(
        self,
        review_text: str,
        categories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Detect categories using keyword matching"""
        text_lower = review_text.lower()
        detected = []

        for cat in categories:
            cat_name = cat.get("name", "").lower()
            cat_id = cat.get("id")

            # Get keywords for this category
            keywords = self.DEFAULT_KEYWORDS.get(cat_name, [cat_name])

            # Find matches
            matches = []
            for kw in keywords:
                if kw in text_lower:
                    matches.append(kw)

            if matches:
                # Calculate confidence based on number of matches
                base_confidence = 0.5
                match_bonus = min(0.4, len(matches) * 0.08)
                confidence = base_confidence + match_bonus

                detected.append({
                    "category_id": cat_id,
                    "category_name": cat.get("name"),
                    "confidence": round(confidence, 2),
                    "evidence": f"Keywords: {', '.join(matches[:5])}"
                })

        return sorted(detected, key=lambda x: x["confidence"], reverse=True)

    def _merge_detection_results(
        self,
        keyword_results: List[Dict],
        ai_results: List[Dict]
    ) -> List[Dict[str, Any]]:
        """Merge keyword and AI detection results"""
        merged = {}

        # Add keyword results
        for r in keyword_results:
            cat_id = r.get("category_id")
            if cat_id:
                merged[cat_id] = {
                    "category_id": cat_id,
                    "category_name": r.get("category_name"),
                    "confidence": r.get("confidence", 0.5),
                    "evidence": r.get("evidence", ""),
                    "detection_method": "keyword"
                }

        # Merge/override with AI results (higher confidence)
        for r in ai_results:
            cat_id = r.get("category_id")
            if cat_id:
                existing = merged.get(cat_id)
                ai_confidence = r.get("confidence", 0.5)

                if existing:
                    # Boost confidence when both methods agree
                    combined_confidence = min(0.98, (existing["confidence"] + ai_confidence) / 2 + 0.1)
                    merged[cat_id]["confidence"] = round(combined_confidence, 2)
                    merged[cat_id]["detection_method"] = "keyword+ai"
                    merged[cat_id]["evidence"] = r.get("evidence", existing.get("evidence", ""))
                else:
                    merged[cat_id] = {
                        "category_id": cat_id,
                        "category_name": r.get("category_name"),
                        "confidence": ai_confidence,
                        "evidence": r.get("evidence", ""),
                        "detection_method": "ai"
                    }

        return list(merged.values())

    async def _create_work_order_from_review(
        self,
        review: Review,
        category: Dict[str, Any],
        routing_rule: Dict[str, Any]
    ) -> Optional[TrendWorkOrder]:
        """Create a work order from a review based on routing rules"""
        try:
            # First, create or get a trend alert for this
            alert = TrendAlert(
                category_id=category.get("category_id"),
                alert_type="review_issue",
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow(),
                issue_count=1,
                severity_score=1.0 if review.overall_rating and review.overall_rating <= 2 else 0.5,
                status="active"
            )
            self.db.add(alert)
            await self.db.commit()
            await self.db.refresh(alert)

            # Create work order
            work_order = TrendWorkOrder(
                trend_alert_id=alert.id,
                category_id=category.get("category_id"),
                title=f"Review Issue: {category.get('category_name', 'General')}",
                description=f"Auto-generated from review #{review.id}\n\nReview Comment:\n{review.comment[:500] if review.comment else 'No comment'}",
                status="open",
                priority=routing_rule.get("default_priority", "medium")
            )
            self.db.add(work_order)
            await self.db.commit()
            await self.db.refresh(work_order)

            logger.info(f"Created work order {work_order.id} from review {review.id}")
            return work_order

        except Exception as e:
            logger.error(f"Failed to create work order from review: {e}")
            await self.db.rollback()
            return None
