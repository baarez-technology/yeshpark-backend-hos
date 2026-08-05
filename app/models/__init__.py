"""
Glimmora Hotel Management System - Models
Complete import of all database models for SQLModel metadata
"""

# Core Models
from app.models.base import TimestampedModel
from app.models.user import User
from app.models.reservations import (
    Guest,
    Booking,
    Reservation,
    ReservationHistory,
    ReservationNote,
    Waitlist,
    GroupBooking,
    AccompanyingGuest
)

# Inventory & Room Management
from app.models.inventory import (
    RoomType,
    Room,
    RatePlan,
    RateRestriction,
    SeasonalRate,
    LengthOfStayRate,
    DayOfWeekRate,
    PromoCode,
    RoomHold,
    RoomBlock,
    DailyAvailability
)

# Operations
from app.models.operations import (
    HousekeepingTask,
    MaintenanceRequest,
    LostFound,
    LinenInventory,
    Folio,
    FolioLineItem,
    Payment,
    AuthorizationHold,
    KeyCard,
    DigitalKey,
    DigitalKeyScan,
    GuestCommunication,
    NightAudit,
    ShiftHandover,
    HotelConfig,
    TaxCategory,
    TaxSlab
)

# Staff Management
from app.models.staff import (
    Staff,
    StaffAttendance,
    StaffPerformanceMetrics,
    StaffSchedule,
    StaffLeave,
    StaffCertification,
    StaffTraining
)

# Runner/Bell Staff Operations
from app.models.runner import (
    RunnerPickupRequest,
    RunnerDelivery,
    RunnerActivityLog
)

# Maintenance
from app.models.maintenance import (
    EquipmentIssues,
    MaintenanceParts,
    Vendors
)

# Housekeeping
from app.models.housekeeping import (
    HousekeepingChecklistTemplates,
    HousekeepingSupplies
)

# CRM & Marketing
from app.models.crm import (
    GuestStayHistory,
    CRMGuestActivities,
    CRMSegments,
    GuestSegments,
    LoyaltyTiers,
    LoyaltyTransactions,
    GuestSpecialRequests,
    GuestFeedback,
    Campaigns
)

# CRM AI - ReConnect AI
from app.models.crm_ai import (
    AIScore,
    AIAlert,
    RecoveryLog,
    SentimentLog,
    CampaignRecipient,
    ABTest
)

# AI System
from app.models.ai_system import (
    AIIntents,
    AIPrompts
)

# Admin AI
from app.models.admin_ai_audit import (
    AdminAIAudit,
    AdminAISession,
    AdminAIMessage
)

# Guest Chat
from app.models.guest_chat import (
    GuestChatSession,
    GuestChatConversation,
    StaffTask,
    StaffNotification
)

# Reviews & Reputation
from app.models.reviews import (
    Review,
    OTAStats,
    ReviewSourcesConfig,
    SentimentTrends
)

# Reputation AI Engine
from app.models.reputation import (
    ResponseDraft,
    ResponseDraftHistory,
    ReviewResponse,
    ReviewCategory,
    ReviewCategoryAssignment,
    CategoryRoutingRule,
    TrendAlert,
    TrendWorkOrder,
    AutomationConfig,
    RatingForecast,
    PerformanceGoal,
    ReviewSourceSync,
    WebhookSubscription,
    EmailAlertSubscription,
    CompetitorBenchmark
)

# Accounts Receivable
from app.models.ar import (
    ARAccount,
    ARPosting
)

# Bookings
from app.models.bookings import (
    RoomChanges,
    BookingAddOns,
    CorporateAccounts,
    Packages,
    MarketSegments,
    DailyMetrics,
    RevenueBySource
)

# Revenue Management
from app.models.revenue import (
    PricingAdjustments,
    ChannelPerformance,
    DynamicPricingRules,
    CompetitorData,
    ForecastData
)

# Promotions & Discounts
from app.models.promotions import (
    Promotion,
    PromotionApplicability,
    PromotionUsage,
    PromotionBlackoutDate,
    PromotionAnalytics
)

# Configuration & Settings
from app.models.configuration import (
    SystemSettings,
    EmailTemplates,
    SMSTemplates,
    HotelSettings,
    Roles,
    Permissions,
    RolePermissions,
    NotificationSettings,
    Integrations
)

# Pre-Check-In
from app.models.precheckin import (
    PreCheckIn
)

# Checkout Feedback
from app.models.checkout_feedback import CheckoutFeedback

# OTP & Auth
from app.models.otp import EmailOTP
from app.models.password_reset import PasswordResetToken
from app.models.payment_method import PaymentMethod

# Help & Support
from app.models.help import (
    HelpArticle,
    HelpSearchLog
)

# Dashboards
from app.models.dashboards import (
    DashboardWidget,
    DashboardLayout
)

# Revenue Management System (RMS)
from app.models.rms import (
    PricingRule,
    Competitor,
    CompetitorRate,
    DemandForecast,
    MarketEvent,
    PickupPace,
    SegmentPerformance
)

# RBAC - Role-Based Access Control
from app.models.rbac import (
    Role,
    Permission,
    RolePermission,
    UserRole,
    UserSession,
    AuditLog
)

# CRM Extended
from app.models.crm_extended import (
    GuestActivityLog,
    GuestLTVSnapshot,
    SentimentTheme,
    SentimentByCategory
)

# CRM AI Extended - Advanced AI Features
from app.models.crm_ai_extended import (
    ABTestExtended,
    ABTestVariant,
    ConversionAttempt,
    DirectMember,
    AISegment,
    AISegmentMembership,
    FrequencyCapLog,
    ChannelPreference
)

# Export all models
__all__ = [
    # Base
    "TimestampedModel",
    
    # Core
    "User",
    "Guest",
    "Booking",
    "Reservation",
    "ReservationHistory",
    "ReservationNote",
    "Waitlist",
    "GroupBooking",
    "AccompanyingGuest",

    # Inventory
    "RoomType",
    "Room",
    "RatePlan",
    "RateRestriction",
    "SeasonalRate",
    "LengthOfStayRate",
    "DayOfWeekRate",
    "PromoCode",
    "RoomHold",
    "RoomBlock",
    "DailyAvailability",
    
    # Operations
    "HousekeepingTask",
    "MaintenanceRequest",
    "LostFound",
    "LinenInventory",
    "Folio",
    "FolioLineItem",
    "Payment",
    "AuthorizationHold",
    "KeyCard",
    "DigitalKey",
    "DigitalKeyScan",
    "GuestCommunication",
    "NightAudit",
    "ShiftHandover",
    "HotelConfig",
    "TaxCategory",
    "TaxSlab",
    
    # Staff
    "Staff",
    "StaffAttendance",
    "StaffPerformanceMetrics",
    "StaffSchedule",
    "StaffLeave",
    "StaffCertification",
    "StaffTraining",
    
    # Runner Operations
    "RunnerPickupRequest",
    "RunnerDelivery",
    "RunnerActivityLog",
    
    # Maintenance
    "EquipmentIssues",
    "MaintenanceParts",
    "Vendors",
    
    # Housekeeping
    "HousekeepingChecklistTemplates",
    "HousekeepingSupplies",
    
    # CRM
    "GuestStayHistory",
    "CRMGuestActivities",
    "CRMSegments",
    "GuestSegments",
    "LoyaltyTiers",
    "LoyaltyTransactions",
    "GuestSpecialRequests",
    "GuestFeedback",
    "Campaigns",

    # CRM AI - ReConnect AI
    "AIScore",
    "AIAlert",
    "RecoveryLog",
    "SentimentLog",
    "CampaignRecipient",
    "ABTest",

    # AI
    "AIIntents",
    "AIPrompts",

    # Admin AI
    "AdminAIAudit",
    "AdminAISession",
    "AdminAIMessage",
    
    # Guest Chat
    "GuestChatSession",
    "GuestChatConversation",
    "StaffTask",
    "StaffNotification",
    
    # Reviews
    "Review",
    "OTAStats",
    "ReviewSourcesConfig",
    "SentimentTrends",
    
    # Reputation AI
    "ResponseDraft",
    "ResponseDraftHistory",
    "ReviewResponse",
    "ReviewCategory",
    "ReviewCategoryAssignment",
    "CategoryRoutingRule",
    "TrendAlert",
    "TrendWorkOrder",
    "AutomationConfig",
    "RatingForecast",
    "PerformanceGoal",
    "ReviewSourceSync",
    "WebhookSubscription",
    "EmailAlertSubscription",
    "CompetitorBenchmark",
    
    # Accounts Receivable
    "ARAccount",
    "ARPosting",

    # Bookings
    "RoomChanges",
    "BookingAddOns",
    "CorporateAccounts",
    "Packages",
    "MarketSegments",
    "DailyMetrics",
    "RevenueBySource",
    
    # Revenue
    "PricingAdjustments",
    "ChannelPerformance",
    "DynamicPricingRules",
    "CompetitorData",
    "ForecastData",

    # Promotions
    "Promotion",
    "PromotionApplicability",
    "PromotionUsage",
    "PromotionBlackoutDate",
    "PromotionAnalytics",

    # Configuration
    "SystemSettings",
    "EmailTemplates",
    "SMSTemplates",
    "HotelSettings",
    "Roles",
    "Permissions",
    "RolePermissions",
    "NotificationSettings",
    "Integrations",
    
    # Pre-Check-In
    "PreCheckIn",

    # Checkout Feedback
    "CheckoutFeedback",

    # Auth
    "EmailOTP",
    "PasswordResetToken",
    "PaymentMethod",
    
    # Help
    "HelpArticle",
    "HelpSearchLog",
    
    # Dashboards
    "DashboardWidget",
    "DashboardLayout",

    # Revenue Management System (RMS)
    "PricingRule",
    "Competitor",
    "CompetitorRate",
    "DemandForecast",
    "MarketEvent",
    "PickupPace",
    "SegmentPerformance",

    # RBAC - Role-Based Access Control
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "UserSession",
    "AuditLog",

    # CRM Extended
    "GuestActivityLog",
    "GuestLTVSnapshot",
    "SentimentTheme",
    "SentimentByCategory",

    # CRM AI Extended - Advanced AI Features
    "ABTestExtended",
    "ABTestVariant",
    "ConversionAttempt",
    "DirectMember",
    "AISegment",
    "AISegmentMembership",
    "FrequencyCapLog",
    "ChannelPreference",
]

