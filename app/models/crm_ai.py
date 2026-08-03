"""
CRM AI Models - ReConnect AI Integration
Includes: AIScore, GuestSegment, AIAlert, CampaignRecipient, RecoveryLog
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
from enum import Enum


class ScoreType(str, Enum):
    """AI score type enum"""
    HEALTH_SCORE = "health_score"
    CHURN_PROBABILITY = "churn_probability"
    LTV = "ltv"
    REBOOKING_PROBABILITY = "rebooking_probability"
    SENTIMENT_SCORE = "sentiment_score"
    ENGAGEMENT_SCORE = "engagement_score"


class AlertPriority(str, Enum):
    """Alert priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AIScore(SQLModel, table=True):
    """AI Score model - versioned ML predictions for guests"""
    __tablename__ = "ai_scores"

    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)

    # Score details
    score_type: str = Field(nullable=False, index=True)  # health_score, churn_probability, ltv, rebooking_probability
    score_value: float = Field(nullable=False)  # Main score value
    score_label: Optional[str] = None  # e.g., "Excellent", "At-risk", "High"

    # Model information
    model_version: str = Field(default="1.0.0", nullable=False)
    model_name: Optional[str] = None
    feature_values: Optional[str] = Field(default=None, sa_column=Column(JSON))  # Input features used

    # Explainability
    shap_values: Optional[str] = Field(default=None, sa_column=Column(JSON))  # Feature importance
    explanation: Optional[str] = None  # Human-readable explanation

    # Additional metadata
    meta_data: Optional[str] = Field(default=None, sa_column=Column(JSON))
    confidence: Optional[float] = None  # Model confidence (0-1)

    # Timestamps
    calculated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIAlert(SQLModel, table=True):
    """AI-generated alerts for at-risk guests or opportunities"""
    __tablename__ = "ai_alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)
    booking_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)

    # Alert details
    alert_type: str = Field(nullable=False, index=True)  # churn_risk, sentiment_drop, recovery_needed, rebooking_opportunity, vip_alert
    priority: str = Field(default="medium", index=True)  # low, medium, high, critical
    title: str = Field(nullable=False)
    message: str = Field(nullable=False)

    # Related scores
    related_score_id: Optional[int] = Field(default=None, foreign_key="ai_scores.id")
    trigger_value: Optional[float] = None  # The value that triggered the alert
    threshold: Optional[float] = None  # The threshold that was crossed

    # Status tracking
    status: str = Field(default="open", index=True)  # open, acknowledged, in_progress, resolved, dismissed
    acknowledged_by: Optional[int] = Field(default=None, foreign_key="users.id")
    acknowledged_at: Optional[datetime] = None
    resolved_by: Optional[int] = Field(default=None, foreign_key="users.id")
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None

    # Campaign trigger
    campaign_triggered: bool = Field(default=False)
    triggered_campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id")

    # Metadata
    extra_data: Optional[str] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RecoveryLog(SQLModel, table=True):
    """Track service recovery attempts for at-risk guests"""
    __tablename__ = "recovery_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)
    booking_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)
    alert_id: Optional[int] = Field(default=None, foreign_key="ai_alerts.id")

    # Issue details
    issue_type: str = Field(nullable=False, index=True)  # service_delay, room_issue, quality_issue, complaint, sentiment_drop
    issue_description: str = Field(nullable=False)
    severity_score: float = Field(default=0.5)  # 0-1 severity
    detected_method: str = Field(default="ai")  # ai, manual, feedback

    # Recovery action
    status: str = Field(default="detected", index=True)  # detected, in_progress, resolved, failed
    recommended_actions: Optional[str] = Field(default=None, sa_column=Column(JSON))  # List of recommended actions
    action_taken: Optional[str] = None
    compensation_offered: Optional[str] = None
    compensation_value: Optional[float] = None

    # Outcome tracking
    guest_satisfaction_before: Optional[float] = None  # Sentiment before recovery
    guest_satisfaction_after: Optional[float] = None  # Sentiment after recovery
    recovery_success: Optional[bool] = None

    # Staff assignment
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id")
    resolved_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    resolved_at: Optional[datetime] = None

    # Timestamps
    detected_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SentimentLog(SQLModel, table=True):
    """Track guest sentiment from various touchpoints"""
    __tablename__ = "sentiment_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)
    booking_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)

    # Source and content
    source: str = Field(nullable=False, index=True)  # feedback, review, chat, email, call
    original_text: Optional[str] = None

    # Sentiment analysis results
    sentiment_score: float = Field(default=0.0)  # -1 to 1 scale
    sentiment_label: str = Field(default="neutral")  # positive, neutral, negative
    primary_emotion: Optional[str] = None  # happy, satisfied, frustrated, angry, disappointed
    emotion_scores: Optional[str] = Field(default=None, sa_column=Column(JSON))  # All emotion scores
    emotion_intensity: Optional[float] = None  # 0-1 intensity
    triggers: Optional[str] = Field(default=None, sa_column=Column(JSON))  # What triggered the emotion

    # Model info
    model_version: str = Field(default="1.0.0")
    confidence: Optional[float] = None

    # Timestamps
    analyzed_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    occurred_at: Optional[datetime] = None  # When the sentiment event occurred
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CampaignRecipient(SQLModel, table=True):
    """Track campaign recipients and their responses"""
    __tablename__ = "campaign_recipients"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True, nullable=False)
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)

    # Delivery
    channel: str = Field(default="email")  # email, sms, whatsapp, push
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None

    # Engagement tracking
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    converted_at: Optional[datetime] = None
    unsubscribed_at: Optional[datetime] = None

    # Personalization
    personalized_content: Optional[str] = Field(default=None, sa_column=Column(JSON))
    offer_details: Optional[str] = Field(default=None, sa_column=Column(JSON))

    # AI predictions
    predicted_conversion_rate: Optional[float] = None
    optimal_send_time: Optional[datetime] = None

    # A/B test
    ab_test_variant: Optional[str] = None

    # Status
    status: str = Field(default="pending", index=True)  # pending, sent, delivered, opened, clicked, converted, bounced, unsubscribed

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ABTest(SQLModel, table=True):
    """A/B testing for campaigns"""
    __tablename__ = "ab_tests"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    test_type: str = Field(nullable=False)  # subject_line, offer, template, cta, timing
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id", index=True)

    # Test configuration
    variants: str = Field(sa_column=Column(JSON, nullable=False))  # List of variant configurations
    traffic_split: Optional[str] = Field(default=None, sa_column=Column(JSON))  # {"A": 50, "B": 50}
    significance_threshold: float = Field(default=0.95)

    # Status
    status: str = Field(default="draft", index=True)  # draft, running, completed, stopped
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    # Results
    winning_variant: Optional[str] = None
    statistical_significance: Optional[float] = None
    p_value: Optional[float] = None
    results: Optional[str] = Field(default=None, sa_column=Column(JSON))

    # Timestamps
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
