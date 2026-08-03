"""
Reputation Engine Models
AI-Powered Review Management, Response Generation, and Analytics
Integrated from Yadhu's Reputation AI System
"""
from datetime import datetime
from datetime import date as date_type
from typing import Optional, List, Any
from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy import JSON, Text
import uuid


class ResponseDraft(SQLModel, table=True):
    """AI-generated response drafts for reviews"""
    __tablename__ = "response_drafts"

    id: Optional[int] = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="reviews.id", index=True)
    draft_text: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default="pending", index=True)  # pending, approved, rejected, published

    # Approval Workflow Fields
    current_stage: str = Field(default="draft")  # draft, review, approval_manager, approval_gm, ready
    approvals: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    locked_by: Optional[int] = Field(default=None, foreign_key="users.id")

    confidence_score: Optional[float] = None
    tone: str = Field(default="professional")  # professional, friendly, apologetic, empathetic

    created_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponseTemplate(SQLModel, table=True):
    """Fallback templates for when AI generation fails"""
    __tablename__ = "response_templates"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, nullable=False, index=True)
    content: str = Field(sa_column=Column(Text, nullable=False))

    # Matching criteria (simple exact match for fallback)
    tone: str = Field(default="professional", index=True)
    sentiment: str = Field(default="positive", index=True)  # positive, neutral, negative

    is_active: bool = Field(default=True)
    is_default: bool = Field(default=False)  # Fallback of last resort

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponseDraftHistory(SQLModel, table=True):
    """Tracks full audit history of draft edits"""
    __tablename__ = "response_draft_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: int = Field(foreign_key="response_drafts.id", index=True)
    editor_id: Optional[int] = Field(default=None, foreign_key="users.id")

    previous_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    new_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    change_reason: Optional[str] = None  # Grammar, Policy, Tone, Factual

    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewResponse(SQLModel, table=True):
    """Published responses to reviews"""
    __tablename__ = "review_responses"

    id: Optional[int] = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="reviews.id", unique=True)
    response_text: str = Field(sa_column=Column(Text, nullable=False))
    published_at: datetime = Field(default_factory=datetime.utcnow)
    platform_response_id: Optional[str] = None  # ID from external platform if posted

    # Engagement & Quality Metrics
    likes: int = Field(default=0)
    helpful_votes: int = Field(default=0)
    quality_score: Optional[float] = None  # AI-evaluated score (0.0 - 100.0)
    quality_breakdown: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    impact_analysis: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    published_by: Optional[int] = Field(default=None, foreign_key="staff.id")


class ReviewCategory(SQLModel, table=True):
    """Hierarchical Taxonomy for Review Issues (e.g. Service > Check-in)"""
    __tablename__ = "review_categories"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, nullable=False, index=True)
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    parent_id: Optional[int] = Field(default=None, foreign_key="review_categories.id")
    icon: Optional[str] = None  # lucide icon name
    color: Optional[str] = None  # hex color for UI
    is_active: bool = Field(default=True, index=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewCategoryAssignment(SQLModel, table=True):
    """Many-to-Many Link between Review and Category with Confidence"""
    __tablename__ = "review_category_assignments"

    id: Optional[int] = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="reviews.id", index=True)
    category_id: int = Field(foreign_key="review_categories.id", index=True)

    confidence_score: float = Field(nullable=False)  # 0.0 - 1.0 confidence
    is_ai_generated: bool = Field(default=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)


class CategoryRoutingRule(SQLModel, table=True):
    """Rules for auto-creating work orders based on categories"""
    __tablename__ = "category_routing_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="review_categories.id")

    target_department: str = Field(max_length=50, nullable=False)  # maintenance, housekeeping, frontdesk
    default_priority: str = Field(default="medium")  # low, medium, high, critical
    auto_create_ticket: bool = Field(default=False)
    notify_manager: bool = Field(default=True)
    escalation_hours: Optional[int] = None  # hours before escalation

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TrendAlert(SQLModel, table=True):
    """Tracks detected trends to prevent duplicate alerts"""
    __tablename__ = "trend_alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="review_categories.id", index=True)

    alert_type: str = Field(default="negative_spike")  # negative_spike, rating_drop, volume_increase
    start_date: datetime = Field(nullable=False)
    end_date: datetime = Field(nullable=False)
    issue_count: int = Field(default=0)
    severity_score: float = Field(default=0.0)
    status: str = Field(default="active", index=True)  # active, resolved, dismissed
    rca_analysis: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # AI-generated Root Cause Analysis

    resolved_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = Field(default=None, sa_column=Column(Text))

    created_at: datetime = Field(default_factory=datetime.utcnow)


class TrendWorkOrder(SQLModel, table=True):
    """Master Work Order for systemic issues aggregated by trends"""
    __tablename__ = "trend_work_orders"

    id: Optional[int] = Field(default=None, primary_key=True)
    trend_alert_id: int = Field(foreign_key="trend_alerts.id", unique=True)
    category_id: int = Field(foreign_key="review_categories.id")

    title: str = Field(max_length=255, nullable=False)
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id")
    status: str = Field(default="open", index=True)  # open, in_progress, completed
    priority: str = Field(default="medium")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class AutomationConfig(SQLModel, table=True):
    """Automation configuration for response generation"""
    __tablename__ = "automation_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, nullable=False)
    global_enabled: bool = Field(default=False)
    safety_check_enabled: bool = Field(default=True)

    # Auto-response rules
    auto_respond_positive: bool = Field(default=False)  # Auto-respond to 4-5 star reviews
    auto_respond_threshold: float = Field(default=4.0)  # Minimum rating for auto-response
    require_approval: bool = Field(default=True)  # Require manual approval before posting

    # Content safety
    profanity_blocklist: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    brand_guidelines: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Timing
    response_delay_hours: int = Field(default=2)  # Delay before auto-posting

    rules: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RatingForecast(SQLModel, table=True):
    """AI-generated rating forecasts"""
    __tablename__ = "rating_forecasts"

    id: Optional[int] = Field(default=None, primary_key=True)
    horizon: str = Field(max_length=20, nullable=False)  # 7d, 14d, 30d, 90d
    source: Optional[str] = None  # overall, google, booking, tripadvisor

    current_rating: float = Field(nullable=False)
    predicted_rating: float = Field(nullable=False)
    confidence: float = Field(nullable=False)
    trend_direction: str = Field(default="stable")  # up, down, stable

    key_factors: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    explanation: Optional[str] = Field(default=None, sa_column=Column(Text))

    generated_at: datetime = Field(default_factory=datetime.utcnow)


class PerformanceGoal(SQLModel, table=True):
    """Performance goals for reputation metrics"""
    __tablename__ = "performance_goals"

    id: Optional[int] = Field(default=None, primary_key=True)
    metric_type: str = Field(max_length=50, nullable=False, index=True)  # rating, response_rate, sentiment_score, nps

    baseline_value: float = Field(nullable=False)
    target_value: float = Field(nullable=False)
    current_value: Optional[float] = None

    start_date: date_type = Field(nullable=False)
    end_date: date_type = Field(nullable=False)

    status: str = Field(default="active", index=True)  # active, completed, expired, achieved
    progress_percentage: float = Field(default=0.0)

    created_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewSourceSync(SQLModel, table=True):
    """Tracks sync status for each review source"""
    __tablename__ = "review_source_syncs"

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(index=True)  # google, booking, tripadvisor, expedia

    last_sync_at: Optional[datetime] = None
    last_sync_status: str = Field(default="pending")  # pending, success, failed
    last_sync_error: Optional[str] = None
    reviews_synced: int = Field(default=0)

    # API credentials/config (encrypted in production)
    credentials: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    config: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    is_enabled: bool = Field(default=True, index=True)
    sync_frequency_hours: int = Field(default=24)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WebhookSubscription(SQLModel, table=True):
    """Webhook subscriptions for external integrations"""
    __tablename__ = "webhook_subscriptions"

    id: Optional[int] = Field(default=None, primary_key=True)
    target_url: str = Field(nullable=False)
    event_type: str = Field(default="review.created", index=True)  # review.created, response.published, alert.triggered
    secret_key: str = Field(nullable=False)

    headers: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    retry_count: int = Field(default=3)
    timeout_seconds: int = Field(default=30)

    is_active: bool = Field(default=True, index=True)
    last_triggered_at: Optional[datetime] = None
    last_response_code: Optional[int] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class EmailAlertSubscription(SQLModel, table=True):
    """Email alert subscriptions for reputation events"""
    __tablename__ = "email_alert_subscriptions"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    email: str = Field(nullable=False)

    # Alert types
    alert_negative_reviews: bool = Field(default=True)
    alert_response_needed: bool = Field(default=True)
    alert_trend_detected: bool = Field(default=True)
    alert_goal_progress: bool = Field(default=False)

    # Thresholds
    min_rating_alert: float = Field(default=3.0)  # Alert on reviews below this
    digest_frequency: str = Field(default="immediate")  # immediate, daily, weekly

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CompetitorBenchmark(SQLModel, table=True):
    """Competitor comparison data for benchmarking"""
    __tablename__ = "competitor_benchmarks"

    id: Optional[int] = Field(default=None, primary_key=True)
    competitor_name: str = Field(max_length=255, nullable=False, index=True)
    source: str = Field(index=True)  # google, tripadvisor, booking

    rating: float = Field(nullable=False)
    review_count: int = Field(default=0)
    response_rate: Optional[float] = None
    sentiment_score: Optional[float] = None

    our_rating: Optional[float] = None  # Our rating on same source for comparison
    rating_gap: Optional[float] = None  # Their rating - Our rating

    captured_at: datetime = Field(default_factory=datetime.utcnow)
