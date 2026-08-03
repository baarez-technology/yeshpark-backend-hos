"""
CRM AI Services - ReConnect AI Integration
Provides AI-powered guest intelligence, churn prediction, LTV forecasting,
rebooking probability, sentiment analysis, campaign optimization, A/B testing,
OTA conversion, member tiers, AI segmentation, frequency capping, and channel learning.
"""
from .feature_store import FeatureStore
from .health_score import HealthScoreModel
from .churn_prediction import ChurnPredictionModel
from .ltv_model import LTVModel
from .rebooking_model import RebookingModel
from .sentiment_analyzer import SentimentAnalyzer
from .campaign_optimizer import CampaignOptimizer
from .reconnect_ai_service import ReConnectAIService, reconnect_ai

# New services
from .ab_testing_service import ABTestingService, ab_testing_service
from .ota_conversion_service import OTAConversionService, ota_conversion_service
from .member_tier_service import MemberTierService, member_tier_service
from .ai_segmentation_service import AISegmentationService, ai_segmentation_service
from .frequency_cap_service import FrequencyCapService, frequency_cap_service
from .channel_learning_service import ChannelLearningService, channel_learning_service

__all__ = [
    # Core Models
    "FeatureStore",
    "HealthScoreModel",
    "ChurnPredictionModel",
    "LTVModel",
    "RebookingModel",
    "SentimentAnalyzer",
    "CampaignOptimizer",
    # Main AI Service
    "ReConnectAIService",
    "reconnect_ai",
    # A/B Testing
    "ABTestingService",
    "ab_testing_service",
    # OTA Conversion
    "OTAConversionService",
    "ota_conversion_service",
    # Member Tiers
    "MemberTierService",
    "member_tier_service",
    # AI Segmentation
    "AISegmentationService",
    "ai_segmentation_service",
    # Frequency Capping
    "FrequencyCapService",
    "frequency_cap_service",
    # Channel Learning
    "ChannelLearningService",
    "channel_learning_service",
]
