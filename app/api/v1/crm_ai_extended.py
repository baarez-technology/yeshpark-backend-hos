"""
Extended CRM AI API Endpoints
Includes A/B Testing, OTA Conversion, Member Tiers, AI Segmentation,
Frequency Caps, Sidebar Stats, and Channel Preferences.
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, Field

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User

# Import services (will be created)
# from app.services.crm_ai.ab_testing_service import ab_testing_service
# from app.services.crm_ai.ota_conversion_service import ota_conversion_service
# from app.services.crm_ai.member_tier_service import member_tier_service
# from app.services.crm_ai.ai_segmentation_service import ai_segmentation_service
# from app.services.crm_ai.frequency_cap_service import frequency_cap_service

router = APIRouter()


# ============================================
# PYDANTIC SCHEMAS
# ============================================

# A/B Testing Schemas
class ABTestVariant(BaseModel):
    """Schema for A/B test variant"""
    name: str = Field(..., min_length=1, max_length=100)
    content: Optional[dict] = None
    weight: float = Field(default=50.0, ge=0, le=100)


class ABTestCreate(BaseModel):
    """Schema for creating a new A/B test"""
    name: str = Field(..., min_length=1, max_length=255, description="Name of the A/B test")
    description: Optional[str] = Field(default=None, max_length=1000, description="Description of the test")
    test_type: str = Field(
        ...,
        pattern="^(subject_line|offer|template|cta|timing|channel)$",
        description="Type of element being tested"
    )
    campaign_id: Optional[int] = Field(default=None, description="Associated campaign ID")
    variants: List[dict] = Field(..., min_length=2, max_length=5, description="Test variants (2-5)")
    traffic_split: Optional[dict] = Field(default=None, description="Custom traffic split percentages")
    significance_threshold: float = Field(
        default=0.95,
        ge=0.8,
        le=0.99,
        description="Statistical significance threshold (0.8-0.99)"
    )


class ABTestUpdate(BaseModel):
    """Schema for updating an A/B test"""
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[str] = Field(default=None, pattern="^(draft|running|paused|completed|stopped)$")


class ABTestResponse(BaseModel):
    """Schema for A/B test response"""
    id: int
    name: str
    description: Optional[str]
    test_type: str
    status: str
    variants: List[dict]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    winning_variant: Optional[str]
    results_summary: Optional[dict]


# OTA Conversion Schemas
class ConversionOfferCreate(BaseModel):
    """Schema for creating a conversion offer"""
    guest_id: int = Field(..., description="Guest ID to send offer to")
    offer_type: str = Field(
        default="discount",
        pattern="^(discount|points|upgrade|package)$",
        description="Type of offer to send"
    )
    offer_value: Optional[float] = Field(default=None, ge=0, description="Offer value (percentage or amount)")
    channel: str = Field(
        default="email",
        pattern="^(email|sms|whatsapp)$",
        description="Delivery channel"
    )
    custom_message: Optional[str] = Field(default=None, max_length=2000, description="Custom message override")
    use_ai_message: bool = Field(default=True, description="Use AI-generated personalized message")


class ConversionOfferResponse(BaseModel):
    """Schema for conversion offer response"""
    attempt_id: int
    guest_id: int
    guest_name: str
    conversion_probability: float
    offer_type: str
    offer_value: float
    message_preview: str
    status: str


# Member Tier Schemas
class MemberEnroll(BaseModel):
    """Schema for enrolling a guest in membership program"""
    guest_id: int = Field(..., description="Guest ID to enroll")
    initial_tier: str = Field(
        default="bronze",
        pattern="^(bronze|silver|gold|platinum|diamond)$",
        description="Initial membership tier"
    )


class TierUpdateRequest(BaseModel):
    """Schema for updating member tier"""
    new_tier: str = Field(
        ...,
        pattern="^(bronze|silver|gold|platinum|diamond)$",
        description="New tier to assign"
    )
    reason: Optional[str] = Field(default=None, max_length=500, description="Reason for tier change")


class DynamicPricingRequest(BaseModel):
    """Schema for dynamic pricing calculation"""
    guest_id: int = Field(..., description="Guest ID")
    base_rate: float = Field(..., gt=0, description="Base room rate")
    room_type: Optional[str] = Field(default=None, description="Room type code")


# AI Segmentation Schemas
class GenerateSegmentsRequest(BaseModel):
    """Schema for AI segment generation"""
    n_clusters: int = Field(default=5, ge=2, le=20, description="Number of segments to generate")
    min_cluster_size: int = Field(default=10, ge=5, description="Minimum guests per segment")
    algorithm: str = Field(
        default="kmeans",
        pattern="^(kmeans|hdbscan)$",
        description="Clustering algorithm"
    )


class SegmentResponse(BaseModel):
    """Schema for segment response"""
    id: int
    name: str
    description: Optional[str]
    segment_type: str
    member_count: int
    avg_ltv: Optional[float]
    avg_health_score: Optional[float]
    characteristics: Optional[dict]


class CreateCRMSegmentRequest(BaseModel):
    """Schema for creating a custom CRM segment (persisted)"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default="", max_length=1000)
    conditions: List[dict] = Field(default_factory=list, description="Filter conditions")
    guestCount: int = Field(default=0, ge=0, description="Number of guests matching at creation")
    avgRevenue: float = Field(default=0, ge=0)
    repeatRate: float = Field(default=0, ge=0, le=100)
    color: Optional[str] = Field(default="#6B7280", max_length=20)
    icon: Optional[str] = Field(default="users", max_length=50)


# ============================================
# A/B TESTING ENDPOINTS
# ============================================

@router.post("/ab-tests", response_model=dict)
async def create_ab_test(
    request: ABTestCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new A/B test

    Creates a test to compare different variants of:
    - Subject lines
    - Offers
    - Templates
    - CTAs
    - Timing
    - Channels
    """
    try:
        # Validate variants have at least 2 items
        if len(request.variants) < 2:
            raise HTTPException(status_code=400, detail="At least 2 variants are required")

        # TODO: Implement actual service call
        # result = await ab_testing_service.create_test(
        #     session=session,
        #     name=request.name,
        #     description=request.description,
        #     test_type=request.test_type,
        #     campaign_id=request.campaign_id,
        #     variants=request.variants,
        #     traffic_split=request.traffic_split,
        #     significance_threshold=request.significance_threshold,
        #     created_by=current_user.id
        # )

        return {
            "success": True,
            "message": "A/B test created successfully",
            "data": {
                "test_id": 1,
                "name": request.name,
                "test_type": request.test_type,
                "status": "draft",
                "variants_count": len(request.variants),
                "created_at": datetime.utcnow().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ab-tests", response_model=dict)
async def list_ab_tests(
    status: Optional[str] = Query(
        default=None,
        pattern="^(draft|running|paused|completed|stopped)$",
        description="Filter by test status"
    ),
    test_type: Optional[str] = Query(
        default=None,
        pattern="^(subject_line|offer|template|cta|timing|channel)$",
        description="Filter by test type"
    ),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum results to return"),
    offset: int = Query(default=0, ge=0, description="Results offset for pagination"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    List all A/B tests with optional filtering

    Returns paginated list of A/B tests with summary statistics
    """
    try:
        # TODO: Implement actual service call
        # tests = await ab_testing_service.list_tests(session, status, test_type, limit, offset)

        return {
            "success": True,
            "data": {
                "tests": [],
                "total": 0,
                "limit": limit,
                "offset": offset
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ab-tests/{test_id}", response_model=dict)
async def get_ab_test(
    test_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get A/B test details

    Returns complete test configuration and current results
    """
    try:
        # TODO: Implement actual service call
        # test = await ab_testing_service.get_test(session, test_id)
        # if not test:
        #     raise HTTPException(status_code=404, detail="A/B test not found")

        return {
            "success": True,
            "data": {
                "id": test_id,
                "name": "Sample Test",
                "description": None,
                "test_type": "subject_line",
                "status": "draft",
                "variants": [],
                "traffic_split": {"A": 50, "B": 50},
                "significance_threshold": 0.95,
                "created_at": datetime.utcnow().isoformat(),
                "started_at": None,
                "ended_at": None
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/ab-tests/{test_id}", response_model=dict)
async def update_ab_test(
    test_id: int,
    request: ABTestUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update A/B test

    Can update name, description, or status (if test hasn't completed)
    """
    try:
        # TODO: Implement actual service call
        # test = await ab_testing_service.get_test(session, test_id)
        # if not test:
        #     raise HTTPException(status_code=404, detail="A/B test not found")
        # if test.status == "completed":
        #     raise HTTPException(status_code=400, detail="Cannot update completed test")

        return {
            "success": True,
            "message": "A/B test updated successfully",
            "data": {
                "id": test_id,
                "updated": True,
                "updated_at": datetime.utcnow().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/ab-tests/{test_id}", response_model=dict)
async def delete_ab_test(
    test_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Delete A/B test

    Can only delete tests that are in draft status
    """
    try:
        # TODO: Implement actual service call
        # test = await ab_testing_service.get_test(session, test_id)
        # if not test:
        #     raise HTTPException(status_code=404, detail="A/B test not found")
        # if test.status != "draft":
        #     raise HTTPException(status_code=400, detail="Can only delete draft tests")

        return {
            "success": True,
            "message": "A/B test deleted successfully",
            "data": {
                "deleted": True,
                "test_id": test_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ab-tests/{test_id}/start", response_model=dict)
async def start_ab_test(
    test_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Start running an A/B test

    Transitions test from draft to running status
    """
    try:
        # TODO: Implement actual service call
        # result = await ab_testing_service.start_test(session, test_id)

        return {
            "success": True,
            "message": "A/B test started successfully",
            "data": {
                "id": test_id,
                "status": "running",
                "started_at": datetime.utcnow().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ab-tests/{test_id}/stop", response_model=dict)
async def stop_ab_test(
    test_id: int,
    declare_winner: Optional[str] = Query(
        default=None,
        description="Optionally declare a winner variant when stopping"
    ),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Stop a running A/B test

    Optionally declare a winner when stopping early
    """
    try:
        # TODO: Implement actual service call
        # result = await ab_testing_service.stop_test(session, test_id, declare_winner)

        return {
            "success": True,
            "message": "A/B test stopped successfully",
            "data": {
                "id": test_id,
                "status": "stopped",
                "stopped_at": datetime.utcnow().isoformat(),
                "winning_variant": declare_winner
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ab-tests/{test_id}/results", response_model=dict)
async def get_ab_test_results(
    test_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get A/B test results with statistical analysis

    Returns:
    - Per-variant metrics (impressions, conversions, rates)
    - Statistical significance (p-value, confidence)
    - Winner determination
    - Lift percentage
    """
    try:
        # TODO: Implement actual service call
        # results = await ab_testing_service.get_test_results(session, test_id)

        return {
            "success": True,
            "data": {
                "test_id": test_id,
                "status": "running",
                "variants": [
                    {
                        "name": "A",
                        "impressions": 1000,
                        "conversions": 50,
                        "conversion_rate": 5.0,
                        "revenue": 2500.00
                    },
                    {
                        "name": "B",
                        "impressions": 1000,
                        "conversions": 65,
                        "conversion_rate": 6.5,
                        "revenue": 3250.00
                    }
                ],
                "statistics": {
                    "winner": "B",
                    "p_value": 0.032,
                    "confidence": 96.8,
                    "lift": 30.0,
                    "is_significant": True,
                    "sample_size_adequate": True
                },
                "recommendation": "Variant B shows statistically significant improvement. Consider deploying.",
                "analyzed_at": datetime.utcnow().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ab-tests/{test_id}/deploy-winner", response_model=dict)
async def deploy_ab_test_winner(
    test_id: int,
    variant_name: Optional[str] = Query(
        default=None,
        description="Variant to deploy (uses statistical winner if not specified)"
    ),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Deploy the winning variant to production

    Applies the winning variant configuration to the associated campaign
    """
    try:
        # TODO: Implement actual service call
        # result = await ab_testing_service.deploy_winner(session, test_id, variant_name)

        return {
            "success": True,
            "message": "Winning variant deployed successfully",
            "data": {
                "deployed": True,
                "test_id": test_id,
                "variant": variant_name or "B",
                "deployed_at": datetime.utcnow().isoformat(),
                "deployed_by": current_user.id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# OTA CONVERSION ENDPOINTS
# ============================================

@router.get("/ota-conversion/guests", response_model=dict)
async def get_ota_guests(
    limit: int = Query(default=50, ge=1, le=200, description="Maximum results"),
    min_probability: float = Query(
        default=0.3,
        ge=0,
        le=1,
        description="Minimum conversion probability filter"
    ),
    booking_source: Optional[str] = Query(
        default=None,
        description="Filter by OTA source (booking.com, expedia, etc.)"
    ),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get guests who booked through OTA channels

    Returns OTA guests ranked by conversion probability with:
    - Guest details
    - Booking history
    - Conversion probability score
    - Recommended offer type
    """
    try:
        # TODO: Implement actual service call
        # guests = await ota_conversion_service.identify_ota_guests(
        #     session, limit, min_probability, booking_source
        # )

        return {
            "success": True,
            "data": {
                "guests": [],
                "total": 0,
                "limit": limit,
                "min_probability": min_probability
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ota-conversion/generate-offer", response_model=dict)
async def generate_conversion_offer(
    request: ConversionOfferCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Generate a personalized conversion offer for an OTA guest

    AI generates personalized offer based on:
    - Guest booking history
    - Spending patterns
    - Preferences
    - Similar guest conversion data
    """
    try:
        # TODO: Implement actual service call
        # offer = await ota_conversion_service.generate_conversion_offer(
        #     session,
        #     request.guest_id,
        #     request.offer_type,
        #     request.use_ai_message
        # )

        return {
            "success": True,
            "data": {
                "guest_id": request.guest_id,
                "conversion_probability": 0.65,
                "offer_type": request.offer_type,
                "offer_value": 15.0,
                "message_preview": "Dear Guest, we'd like to offer you an exclusive 15% discount on your next direct booking...",
                "benefits": [
                    "Best rate guarantee",
                    "Free room upgrade (subject to availability)",
                    "Late checkout until 2 PM",
                    "Welcome amenity"
                ],
                "personalization_factors": [
                    "Previous stay preferences",
                    "Spending history",
                    "Room type preference"
                ]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ota-conversion/send-offer", response_model=dict)
async def send_conversion_offer(
    request: ConversionOfferCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Send conversion offer to guest

    Sends the offer via specified channel and creates tracking record
    """
    try:
        # TODO: Implement actual service call
        # result = await ota_conversion_service.send_conversion_offer(
        #     session, request.guest_id, request.offer_type,
        #     request.channel, request.custom_message
        # )

        return {
            "success": True,
            "message": "Conversion offer sent successfully",
            "data": {
                "attempt_id": 1,
                "guest_id": request.guest_id,
                "channel": request.channel,
                "status": "sent",
                "sent_at": datetime.utcnow().isoformat(),
                "sent_by": current_user.id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ota-conversion/stats", response_model=dict)
async def get_conversion_stats(
    days: int = Query(default=30, ge=7, le=365, description="Days to include in stats"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get OTA conversion statistics

    Returns conversion funnel metrics and revenue impact
    """
    try:
        # TODO: Implement actual service call
        # stats = await ota_conversion_service.get_conversion_stats(session, days)

        return {
            "success": True,
            "data": {
                "period_days": days,
                "total_ota_guests": 245,
                "offers_sent": 89,
                "offers_opened": 67,
                "offers_clicked": 34,
                "converted": 18,
                "conversion_rate": 20.2,
                "revenue_impact": 12500.00,
                "avg_booking_value": 694.44,
                "funnel": {
                    "identified": 245,
                    "contacted": 89,
                    "engaged": 67,
                    "clicked": 34,
                    "converted": 18
                },
                "by_channel": {
                    "email": {"sent": 65, "converted": 12},
                    "sms": {"sent": 15, "converted": 4},
                    "whatsapp": {"sent": 9, "converted": 2}
                },
                "calculated_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ota-conversion/benefits/{tier}", response_model=dict)
async def get_direct_booking_benefits(
    tier: str = "bronze",
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get direct booking benefits by membership tier

    Returns tier-specific benefits to highlight in conversion offers
    """
    try:
        # TODO: Implement actual service call
        # benefits = await ota_conversion_service.get_direct_booking_benefits(tier)

        tier_benefits = {
            "bronze": {
                "discount": 5,
                "benefits": [
                    "Best rate guarantee",
                    "Free WiFi",
                    "Early check-in (subject to availability)"
                ]
            },
            "silver": {
                "discount": 8,
                "benefits": [
                    "Best rate guarantee",
                    "Free WiFi",
                    "Early check-in priority",
                    "Late checkout until 1 PM"
                ]
            },
            "gold": {
                "discount": 12,
                "benefits": [
                    "Best rate guarantee",
                    "Free WiFi",
                    "Guaranteed early check-in",
                    "Late checkout until 2 PM",
                    "Room upgrade (subject to availability)"
                ]
            },
            "platinum": {
                "discount": 16,
                "benefits": [
                    "Best rate guarantee",
                    "Free WiFi",
                    "Guaranteed early check-in",
                    "Late checkout until 4 PM",
                    "Complimentary room upgrade",
                    "Welcome amenity"
                ]
            },
            "diamond": {
                "discount": 20,
                "benefits": [
                    "Best rate guarantee",
                    "Free WiFi",
                    "Flexible check-in/out",
                    "Guaranteed room upgrade",
                    "Premium welcome amenity",
                    "Complimentary breakfast",
                    "Executive lounge access"
                ]
            }
        }

        benefits = tier_benefits.get(tier.lower(), tier_benefits["bronze"])

        return {
            "success": True,
            "data": {
                "tier": tier.lower(),
                "discount": benefits["discount"],
                "benefits": benefits["benefits"]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ota-conversion/track/{attempt_id}", response_model=dict)
async def track_conversion_event(
    attempt_id: int,
    event_type: str = Query(
        ...,
        pattern="^(opened|clicked|converted|unsubscribed)$",
        description="Type of tracking event"
    ),
    metadata: Optional[dict] = Body(default=None, embed=True),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Track conversion funnel event

    Can be called from email tracking pixel or landing page
    Note: Does not require authentication for tracking pixel use
    """
    try:
        # TODO: Implement actual service call
        # result = await ota_conversion_service.track_event(
        #     session, attempt_id, event_type, metadata
        # )

        return {
            "success": True,
            "data": {
                "tracked": True,
                "attempt_id": attempt_id,
                "event": event_type,
                "tracked_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# MEMBER TIER ENDPOINTS
# ============================================

@router.get("/member/tiers", response_model=dict)
async def get_all_tiers(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get all membership tiers with benefits and thresholds

    Returns complete tier structure with member counts
    """
    try:
        # TODO: Implement actual service call with real counts
        # tiers = await member_tier_service.get_all_tiers(session)

        return {
            "success": True,
            "data": {
                "tiers": [
                    {
                        "tier": "bronze",
                        "display_name": "Bronze",
                        "discount": 5,
                        "points_multiplier": 1.0,
                        "threshold_spend": 0,
                        "threshold_nights": 0,
                        "member_count": 450
                    },
                    {
                        "tier": "silver",
                        "display_name": "Silver",
                        "discount": 8,
                        "points_multiplier": 1.25,
                        "threshold_spend": 2000,
                        "threshold_nights": 5,
                        "member_count": 180
                    },
                    {
                        "tier": "gold",
                        "display_name": "Gold",
                        "discount": 12,
                        "points_multiplier": 1.5,
                        "threshold_spend": 5000,
                        "threshold_nights": 15,
                        "member_count": 85
                    },
                    {
                        "tier": "platinum",
                        "display_name": "Platinum",
                        "discount": 16,
                        "points_multiplier": 2.0,
                        "threshold_spend": 10000,
                        "threshold_nights": 30,
                        "member_count": 32
                    },
                    {
                        "tier": "diamond",
                        "display_name": "Diamond",
                        "discount": 20,
                        "points_multiplier": 3.0,
                        "threshold_spend": 20000,
                        "threshold_nights": 50,
                        "member_count": 12
                    }
                ],
                "total_members": 759
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/member/tiers/{tier}/benefits", response_model=dict)
async def get_tier_benefits(
    tier: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed benefits for a specific membership tier
    """
    try:
        valid_tiers = ["bronze", "silver", "gold", "platinum", "diamond"]
        if tier.lower() not in valid_tiers:
            raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {', '.join(valid_tiers)}")

        # TODO: Implement actual service call
        # benefits = await member_tier_service.get_tier_benefits(session, tier)

        return {
            "success": True,
            "data": {
                "tier": tier.lower(),
                "discount_percentage": 10,
                "points_multiplier": 1.5,
                "benefits": [
                    {"category": "Room", "benefit": "Best available rate guarantee"},
                    {"category": "Room", "benefit": "Room upgrade (subject to availability)"},
                    {"category": "Service", "benefit": "Priority check-in"},
                    {"category": "Service", "benefit": "Late checkout"},
                    {"category": "Dining", "benefit": "10% F&B discount"}
                ],
                "perks": [
                    "Welcome amenity on arrival",
                    "Birthday bonus points",
                    "Exclusive member offers"
                ]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/member/enroll", response_model=dict)
async def enroll_member(
    request: MemberEnroll,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Enroll a guest in the direct booking membership program

    Creates membership record and assigns initial tier
    """
    try:
        # TODO: Implement actual service call
        # member = await member_tier_service.enroll_guest(
        #     session, request.guest_id, request.initial_tier
        # )

        # Generate member number
        member_number = f"GLM-{datetime.utcnow().year}-{str(request.guest_id).zfill(4)}"

        return {
            "success": True,
            "message": "Guest enrolled successfully",
            "data": {
                "member_id": 1,
                "guest_id": request.guest_id,
                "tier": request.initial_tier,
                "member_number": member_number,
                "points_balance": 0,
                "enrolled_at": datetime.utcnow().isoformat(),
                "enrolled_by": current_user.id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/member/{guest_id}", response_model=dict)
async def get_member_details(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get membership details for a guest

    Returns current tier, points, progress to next tier
    """
    try:
        # TODO: Implement actual service call
        # member = await member_tier_service.get_member(session, guest_id)
        # if not member:
        #     raise HTTPException(status_code=404, detail="Member not found")

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "member_number": f"GLM-2024-{str(guest_id).zfill(4)}",
                "tier": "silver",
                "tier_since": "2023-06-15",
                "points_balance": 2500,
                "points_earned_ytd": 3200,
                "points_redeemed_ytd": 700,
                "total_spend": 3200.00,
                "total_nights": 8,
                "next_tier": "gold",
                "next_tier_requirements": {
                    "spend_needed": 1800.00,
                    "nights_needed": 7,
                    "progress_percent": 64
                },
                "tier_expiry": "2025-12-31",
                "benefits_used": [
                    "Room upgrade - 2 times",
                    "Late checkout - 3 times"
                ]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/member/{guest_id}/tier", response_model=dict)
async def update_member_tier(
    guest_id: int,
    request: TierUpdateRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Manually update member tier

    Used for tier adjustments, courtesy upgrades, or corrections
    """
    try:
        # TODO: Implement actual service call
        # result = await member_tier_service.update_tier(
        #     session, guest_id, request.new_tier, request.reason, current_user.id
        # )

        return {
            "success": True,
            "message": "Member tier updated successfully",
            "data": {
                "guest_id": guest_id,
                "old_tier": "silver",
                "new_tier": request.new_tier,
                "reason": request.reason,
                "updated_at": datetime.utcnow().isoformat(),
                "updated_by": current_user.id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/member/calculate-pricing", response_model=dict)
async def calculate_dynamic_pricing(
    request: DynamicPricingRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Calculate dynamic pricing for a member

    Applies tier discount plus AI-based LTV and health score bonuses
    """
    try:
        # TODO: Implement actual service call
        # pricing = await member_tier_service.calculate_dynamic_price(
        #     session, request.guest_id, request.base_rate, request.room_type
        # )

        # Calculate discounts
        tier_discount = 12.0  # Gold tier
        ltv_bonus = 3.0  # High LTV bonus
        health_bonus = 2.0  # Good health score bonus
        total_discount = tier_discount + ltv_bonus + health_bonus
        final_rate = request.base_rate * (1 - total_discount / 100)

        return {
            "success": True,
            "data": {
                "guest_id": request.guest_id,
                "room_type": request.room_type,
                "base_rate": request.base_rate,
                "tier": "gold",
                "discounts": {
                    "tier_discount": tier_discount,
                    "ltv_bonus": ltv_bonus,
                    "health_bonus": health_bonus,
                    "total_discount": total_discount
                },
                "final_rate": round(final_rate, 2),
                "savings": round(request.base_rate - final_rate, 2),
                "points_earned": int(final_rate * 1.5)  # 1.5x multiplier for Gold
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/member/stats", response_model=dict)
async def get_member_stats(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get membership program statistics

    Returns program-wide metrics and trends
    """
    try:
        # TODO: Implement actual service call with real data
        # stats = await member_tier_service.get_program_stats(session)

        return {
            "success": True,
            "data": {
                "total_members": 759,
                "active_members": 623,
                "by_tier": {
                    "bronze": 450,
                    "silver": 180,
                    "gold": 85,
                    "platinum": 32,
                    "diamond": 12
                },
                "new_this_month": 45,
                "upgrades_this_month": 12,
                "downgrades_this_month": 3,
                "points": {
                    "total_issued": 1250000,
                    "total_redeemed": 450000,
                    "outstanding": 800000,
                    "issued_this_month": 125000,
                    "redeemed_this_month": 45000
                },
                "revenue_metrics": {
                    "member_revenue_share": 68.5,
                    "avg_member_spend": 425.00,
                    "avg_non_member_spend": 285.00
                },
                "calculated_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# AI SEGMENTATION ENDPOINTS
# ============================================

@router.post("/segments/generate", response_model=dict)
async def generate_ai_segments(
    request: GenerateSegmentsRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Generate AI-powered guest segments using clustering

    Uses ML clustering (K-means or HDBSCAN) on guest features:
    - RFM scores
    - Health scores
    - LTV predictions
    - Behavioral patterns
    """
    try:
        # TODO: Implement actual service call
        # segments = await ai_segmentation_service.generate_segments(
        #     session, request.n_clusters, request.min_cluster_size, request.algorithm
        # )

        return {
            "success": True,
            "message": "AI segments generated successfully",
            "data": {
                "segments_created": request.n_clusters,
                "total_guests_segmented": 2500,
                "algorithm": request.algorithm,
                "segments": [
                    {
                        "id": 1,
                        "name": "High Value Frequent Guests",
                        "description": "Top-tier guests with high spend and frequent visits",
                        "count": 234,
                        "avg_ltv": 12500.00,
                        "avg_health_score": 85
                    },
                    {
                        "id": 2,
                        "name": "Medium Value Regular Guests",
                        "description": "Consistent guests with moderate spend",
                        "count": 567,
                        "avg_ltv": 4500.00,
                        "avg_health_score": 72
                    },
                    {
                        "id": 3,
                        "name": "Low Value Occasional Guests",
                        "description": "Infrequent guests with lower engagement",
                        "count": 890,
                        "avg_ltv": 1200.00,
                        "avg_health_score": 45
                    },
                    {
                        "id": 4,
                        "name": "At-Risk Lapsed Guests",
                        "description": "Previously active guests showing churn signals",
                        "count": 345,
                        "avg_ltv": 3200.00,
                        "avg_health_score": 28
                    },
                    {
                        "id": 5,
                        "name": "New Potential VIPs",
                        "description": "Recent guests with high potential based on initial behavior",
                        "count": 464,
                        "avg_ltv": 6800.00,
                        "avg_health_score": 68
                    }
                ],
                "generated_at": datetime.utcnow().isoformat(),
                "generated_by": current_user.id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/segments/ai", response_model=dict)
async def get_ai_segments(
    is_active: bool = Query(default=True, description="Filter by active status"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get all AI-generated segments

    Returns list of segments with summary statistics
    """
    try:
        # TODO: Implement actual service call
        # segments = await ai_segmentation_service.get_segments(session, is_active)

        return {
            "success": True,
            "data": {
                "segments": [],
                "total": 0,
                "is_active_filter": is_active
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/segments/ai/{segment_id}", response_model=dict)
async def get_ai_segment_details(
    segment_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed information about an AI segment

    Returns characteristics, metrics, and campaign recommendations
    """
    try:
        # TODO: Implement actual service call
        # segment = await ai_segmentation_service.get_segment(session, segment_id)
        # if not segment:
        #     raise HTTPException(status_code=404, detail="Segment not found")

        return {
            "success": True,
            "data": {
                "id": segment_id,
                "name": "High Value Frequent Guests",
                "description": "Top-tier guests with high spend and frequent visits",
                "segment_type": "ai_generated",
                "is_active": True,
                "member_count": 234,
                "characteristics": {
                    "value": "High Value",
                    "frequency": "Frequent",
                    "recency": "Recent",
                    "sentiment": "Very Positive",
                    "channel_preference": "Email"
                },
                "metrics": {
                    "avg_ltv": 12500.00,
                    "avg_health_score": 85,
                    "avg_churn_risk": 12,
                    "avg_spend_per_stay": 850.00,
                    "avg_stays_per_year": 4.2
                },
                "demographics": {
                    "avg_age": 42,
                    "top_countries": ["USA", "UK", "Canada"],
                    "business_vs_leisure": {"business": 65, "leisure": 35}
                },
                "recommended_campaigns": [
                    {"type": "loyalty_reward", "priority": "high"},
                    {"type": "upsell", "priority": "high"},
                    {"type": "referral", "priority": "medium"}
                ],
                "created_at": "2024-01-01T00:00:00Z",
                "last_refreshed": datetime.utcnow().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/segments/ai/{segment_id}/members", response_model=dict)
async def get_segment_members(
    segment_id: int,
    limit: int = Query(default=50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(default=0, ge=0, description="Results offset"),
    sort_by: str = Query(default="ltv", pattern="^(ltv|health_score|churn_risk|last_stay)$"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get members of an AI segment with pagination
    """
    try:
        # TODO: Implement actual service call
        # members = await ai_segmentation_service.get_segment_members(
        #     session, segment_id, limit, offset, sort_by
        # )

        return {
            "success": True,
            "data": {
                "segment_id": segment_id,
                "segment_name": "High Value Frequent Guests",
                "total_members": 234,
                "members": [],
                "limit": limit,
                "offset": offset,
                "sort_by": sort_by
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/segments/ai/refresh", response_model=dict)
async def refresh_ai_segments(
    segment_ids: Optional[List[int]] = Body(
        default=None,
        embed=True,
        description="Specific segment IDs to refresh (all if not specified)"
    ),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Refresh AI segment memberships

    Re-evaluates guest assignments based on current data
    """
    try:
        # TODO: Implement actual service call
        # result = await ai_segmentation_service.refresh_segments(session, segment_ids)

        return {
            "success": True,
            "message": "Segments refreshed successfully",
            "data": {
                "refreshed": True,
                "segments_updated": 5 if segment_ids is None else len(segment_ids),
                "guests_reassigned": 150,
                "refreshed_at": datetime.utcnow().isoformat(),
                "refreshed_by": current_user.id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/segments/ai/{segment_id}", response_model=dict)
async def delete_ai_segment(
    segment_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Delete an AI segment

    Removes segment definition (does not affect guests)
    """
    try:
        # TODO: Implement actual service call
        # segment = await ai_segmentation_service.get_segment(session, segment_id)
        # if not segment:
        #     raise HTTPException(status_code=404, detail="Segment not found")
        # await ai_segmentation_service.delete_segment(session, segment_id)

        return {
            "success": True,
            "message": "Segment deleted successfully",
            "data": {
                "deleted": True,
                "segment_id": segment_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# FREQUENCY CAP ENDPOINTS
# ============================================

@router.get("/frequency-cap/{guest_id}", response_model=dict)
async def check_frequency_cap(
    guest_id: int,
    channel: str = Query(
        ...,
        pattern="^(email|sms|whatsapp|push)$",
        description="Communication channel to check"
    ),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Check if we can send to a guest on a specific channel

    Returns remaining capacity and next available send time
    """
    try:
        # TODO: Implement actual service call
        # cap_status = await frequency_cap_service.check_cap(session, guest_id, channel)

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "channel": channel,
                "can_send": True,
                "limits": {
                    "daily": {"limit": 1, "used": 0, "remaining": 1},
                    "weekly": {"limit": 3, "used": 2, "remaining": 1},
                    "monthly": {"limit": 8, "used": 4, "remaining": 4}
                },
                "last_sent": "2024-01-15T10:30:00Z",
                "next_available": None,
                "opt_out_status": False
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frequency-cap/{guest_id}/all-channels", response_model=dict)
async def get_all_frequency_caps(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get frequency cap status for all communication channels
    """
    try:
        # TODO: Implement actual service call
        # caps = await frequency_cap_service.get_all_caps(session, guest_id)

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "channels": {
                    "email": {
                        "can_send": True,
                        "remaining_daily": 1,
                        "remaining_weekly": 1,
                        "remaining_monthly": 4,
                        "last_sent": "2024-01-15T10:30:00Z",
                        "opt_out": False
                    },
                    "sms": {
                        "can_send": True,
                        "remaining_daily": 1,
                        "remaining_weekly": 1,
                        "remaining_monthly": 2,
                        "last_sent": "2024-01-10T14:00:00Z",
                        "opt_out": False
                    },
                    "whatsapp": {
                        "can_send": False,
                        "remaining_daily": 0,
                        "remaining_weekly": 0,
                        "remaining_monthly": 1,
                        "last_sent": "2024-01-18T09:00:00Z",
                        "next_available": "2024-01-20T00:00:00Z",
                        "opt_out": False
                    },
                    "push": {
                        "can_send": True,
                        "remaining_daily": 2,
                        "remaining_weekly": 4,
                        "remaining_monthly": 12,
                        "last_sent": "2024-01-16T16:00:00Z",
                        "opt_out": False
                    }
                },
                "global_opt_out": False,
                "preferred_channel": "email"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/frequency-cap/{guest_id}/record", response_model=dict)
async def record_communication(
    guest_id: int,
    channel: str = Query(..., pattern="^(email|sms|whatsapp|push)$"),
    campaign_id: Optional[int] = Body(default=None, embed=True),
    message_type: str = Body(default="marketing", embed=True),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Record a communication sent to update frequency caps
    """
    try:
        # TODO: Implement actual service call
        # result = await frequency_cap_service.record_send(
        #     session, guest_id, channel, campaign_id, message_type
        # )

        return {
            "success": True,
            "message": "Communication recorded",
            "data": {
                "guest_id": guest_id,
                "channel": channel,
                "recorded_at": datetime.utcnow().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# SIDEBAR STATS ENDPOINT
# ============================================

@router.get("/sidebar-stats", response_model=dict)
async def get_sidebar_stats(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get CRM AI sidebar statistics

    Provides real-time data for the CRMAI.tsx sidebar component.
    Replaces hardcoded frontend values with actual database counts.

    Returns:
    - Total guests count
    - Loyalty members count
    - VIP guests count
    - Average LTV
    - At-risk guest count
    - Recovery opportunities pending
    - Open alerts count
    - Active campaigns count
    """
    try:
        # TODO: Implement actual database queries
        # Example queries to implement:
        # total_guests = await session.exec(select(func.count(Guest.id))).one()
        # loyalty_members = await session.exec(
        #     select(func.count(DirectMember.id)).where(DirectMember.is_active == True)
        # ).one()
        # vip_guests = await session.exec(
        #     select(func.count(Guest.id)).where(Guest.vip_status == True)
        # ).one()
        # avg_ltv = await session.exec(
        #     select(func.avg(AIScore.score_value))
        #     .where(AIScore.score_type == 'ltv')
        # ).one()
        # at_risk = await session.exec(
        #     select(func.count(AIScore.guest_id))
        #     .where(AIScore.score_type == 'churn_probability')
        #     .where(AIScore.score_value >= 70)
        # ).one()
        # recovery_pending = await session.exec(
        #     select(func.count(RecoveryLog.id))
        #     .where(RecoveryLog.status == 'detected')
        # ).one()
        # open_alerts = await session.exec(
        #     select(func.count(AIAlert.id))
        #     .where(AIAlert.status == 'open')
        # ).one()
        # active_campaigns = await session.exec(
        #     select(func.count(Campaign.id))
        #     .where(Campaign.status == 'active')
        # ).one()

        return {
            "success": True,
            "data": {
                "total_guests": 2847,
                "loyalty_members": 1234,
                "vip_guests": 156,
                "avg_ltv": 4250.00,
                "at_risk_count": 45,
                "recovery_pending": 12,
                "open_alerts": 23,
                "campaigns_active": 5,
                "health_distribution": {
                    "excellent": 312,
                    "good": 856,
                    "fair": 1023,
                    "at_risk": 478,
                    "critical": 178
                },
                "trend_indicators": {
                    "guests_change": 3.2,
                    "members_change": 5.8,
                    "ltv_change": 2.1,
                    "at_risk_change": -1.5
                },
                "updated_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CHANNEL PREFERENCE ENDPOINTS
# ============================================

@router.get("/channel-preference/{guest_id}", response_model=dict)
async def get_channel_preference(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get learned channel preferences for a guest

    Returns AI-learned preferences based on engagement history
    """
    try:
        # TODO: Implement actual service call
        # preferences = await channel_preference_service.get_preferences(session, guest_id)

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "preferred_channel": "email",
                "confidence": 0.85,
                "scores": {
                    "email": 0.85,
                    "sms": 0.60,
                    "whatsapp": 0.72,
                    "push": 0.45
                },
                "engagement_history": {
                    "email": {
                        "sent": 10,
                        "opened": 8,
                        "clicked": 5,
                        "open_rate": 80.0,
                        "click_rate": 50.0
                    },
                    "sms": {
                        "sent": 3,
                        "clicked": 1,
                        "click_rate": 33.3
                    },
                    "whatsapp": {
                        "sent": 5,
                        "read": 4,
                        "replied": 2,
                        "read_rate": 80.0,
                        "reply_rate": 40.0
                    },
                    "push": {
                        "sent": 8,
                        "opened": 3,
                        "open_rate": 37.5
                    }
                },
                "best_send_times": {
                    "email": {"day": "Tuesday", "hour": 10},
                    "sms": {"day": "Wednesday", "hour": 14},
                    "whatsapp": {"day": "Monday", "hour": 11}
                },
                "last_updated": datetime.utcnow().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/channel-preference/{guest_id}/update", response_model=dict)
async def update_channel_preference(
    guest_id: int,
    channel: str = Query(..., pattern="^(email|sms|whatsapp|push)$"),
    event_type: str = Query(
        ...,
        pattern="^(sent|opened|clicked|replied|unsubscribed)$",
        description="Type of engagement event"
    ),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Update channel preference based on engagement event

    Called when guest engages (or doesn't) with a communication.
    Updates the AI preference model.
    """
    try:
        # TODO: Implement actual service call
        # result = await channel_preference_service.record_engagement(
        #     session, guest_id, channel, event_type
        # )

        return {
            "success": True,
            "data": {
                "updated": True,
                "guest_id": guest_id,
                "channel": channel,
                "event": event_type,
                "recorded_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/channel-preference/{guest_id}/set-preferred", response_model=dict)
async def set_preferred_channel(
    guest_id: int,
    channel: str = Query(..., pattern="^(email|sms|whatsapp|push)$"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Manually set guest's preferred communication channel

    Overrides AI-learned preference with explicit guest choice
    """
    try:
        # TODO: Implement actual service call
        # result = await channel_preference_service.set_explicit_preference(
        #     session, guest_id, channel
        # )

        return {
            "success": True,
            "message": f"Preferred channel set to {channel}",
            "data": {
                "guest_id": guest_id,
                "preferred_channel": channel,
                "set_by": "explicit",
                "updated_at": datetime.utcnow().isoformat(),
                "updated_by": current_user.id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# CRM GUESTS ENDPOINT (Real Database Data)
# ============================================

class CRMGuestResponse(BaseModel):
    """CRM-formatted guest data"""
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    totalStays: int = 0
    totalNights: int = 0
    totalRevenue: float = 0.0
    loyaltyTier: Optional[str] = None
    lastStay: Optional[str] = None
    bookingSource: Optional[str] = None
    preferredRoomType: Optional[str] = None
    tags: List[str] = []
    createdAt: Optional[str] = None


@router.get("/crm-guests", response_model=dict)
async def get_crm_guests(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get all guests formatted for CRM display

    Returns guest data from the database in the format expected by CRM.tsx
    Calculates stats from actual Booking records for accuracy
    Uses database-level pagination for efficiency
    """
    from sqlmodel import select, func
    from app.models.reservations import Guest, Booking
    import json as json_module

    try:
        # Get total count first (for pagination info)
        count_query = select(func.count(Guest.id)).where(Guest.status != "Inactive")
        count_result = await session.exec(count_query)
        total = count_result.one()

        # Get paginated guests using database-level OFFSET/LIMIT
        offset = (page - 1) * page_size
        query = (
            select(Guest)
            .where(Guest.status != "Inactive")
            .order_by(Guest.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await session.exec(query)
        paginated_guests = result.all()

        # Get guest IDs for the current page
        guest_ids = [g.id for g in paginated_guests]

        # Get booking stats only for guests on this page (much faster)
        booking_stats = {}
        if guest_ids:
            booking_stats_query = (
                select(
                    Booking.guest_id,
                    func.sum(Booking.total_price).label("total_revenue"),
                    func.count(Booking.id).label("booking_count"),
                    func.sum(Booking.nights).label("total_nights"),
                    func.max(Booking.arrival_date).label("last_stay")
                )
                .where(Booking.status.notin_(["cancelled", "no_show"]))
                .where(Booking.guest_id.in_(guest_ids))
                .group_by(Booking.guest_id)
            )
            booking_result = await session.exec(booking_stats_query)
            booking_stats = {
                row[0]: {
                    "revenue": float(row[1] or 0),
                    "bookings": int(row[2] or 0),
                    "nights": int(row[3] or 0),
                    "last_stay": row[4]
                }
                for row in booking_result.all()
            }

        crm_guests = []
        for guest in paginated_guests:
            # Parse tags from JSON field
            tags = []
            if guest.tags:
                if isinstance(guest.tags, list):
                    tags = guest.tags
                elif isinstance(guest.tags, str):
                    try:
                        tags = json_module.loads(guest.tags)
                    except:
                        tags = []

            # Get actual stats from bookings
            stats = booking_stats.get(guest.id, {"revenue": 0, "bookings": 0, "nights": 0, "last_stay": None})
            total_revenue = stats["revenue"]
            total_bookings = stats["bookings"]
            total_nights = stats["nights"]
            last_stay = stats["last_stay"]

            # Determine loyalty tier based on actual revenue from bookings
            loyalty_tier = guest.loyalty_tier
            if not loyalty_tier and total_revenue > 0:
                if total_revenue >= 20000:
                    loyalty_tier = "platinum"
                elif total_revenue >= 10000:
                    loyalty_tier = "gold"
                elif total_revenue >= 5000:
                    loyalty_tier = "silver"
                else:
                    loyalty_tier = "bronze"
            elif not loyalty_tier:
                loyalty_tier = "bronze"

            crm_guest = {
                "id": f"G{guest.id:03d}",
                "name": f"{guest.first_name} {guest.last_name}",
                "email": guest.email,
                "phone": guest.phone,
                "country": guest.country or "Unknown",
                "totalStays": total_bookings,
                "totalNights": total_nights,
                "totalRevenue": total_revenue,
                "loyaltyTier": loyalty_tier,
                "lastStay": last_stay.isoformat() if last_stay else (guest.last_visit.isoformat() if guest.last_visit else None),
                "bookingSource": guest.booking_source or "direct",
                "preferredRoomType": guest.preferred_room_type or "standard",
                "tags": tags if tags else (["vip"] if guest.vip_status else []),
                "createdAt": guest.created_at.isoformat() if guest.created_at else None
            }
            crm_guests.append(crm_guest)

        return {
            "success": True,
            "data": {
                "guests": crm_guests,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/crm-segments", response_model=dict)
async def create_crm_segment(
    request: CreateCRMSegmentRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Create a custom CRM segment (persisted). Segment will appear in the list after refresh.
    """
    from sqlmodel import select
    from app.models.crm import CRMSegments

    try:
        # Check for duplicate name
        existing = await session.exec(select(CRMSegments).where(CRMSegments.name == request.name))
        if existing.first():
            raise HTTPException(status_code=400, detail="A segment with this name already exists.")
        criteria = {
            "conditions": request.conditions,
            "color": request.color or "#6B7280",
            "icon": request.icon or "users",
            "avgRevenue": request.avgRevenue,
            "repeatRate": request.repeatRate,
        }
        segment = CRMSegments(
            name=request.name,
            description=request.description or None,
            segment_type="custom",
            criteria=criteria,
            is_active=True,
            member_count=request.guestCount,
            created_by=current_user.id,
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)
        # Return same shape as GET for frontend (id format matches list)
        return {
            "success": True,
            "data": {
                "id": f"seg-custom-{segment.id}",
                "name": segment.name,
                "description": segment.description or "",
                "conditions": request.conditions,
                "guestCount": segment.member_count,
                "avgRevenue": request.avgRevenue,
                "repeatRate": request.repeatRate,
                "color": request.color or "#6B7280",
                "icon": request.icon or "users",
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/crm-segments/{segment_id}", response_model=dict)
@router.put("/crm-segments/{segment_id}", response_model=dict)
async def update_crm_segment(
    segment_id: str,
    request: CreateCRMSegmentRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update a custom CRM segment (color, filters, name, description, etc.). Only custom segments can be updated.
    segment_id can be "seg-custom-123" or the numeric id "123".
    """
    from sqlmodel import select
    from app.models.crm import CRMSegments

    try:
        raw = segment_id.strip()
        if raw.startswith("seg-custom-"):
            try:
                pk = int(raw.replace("seg-custom-", "", 1))
            except ValueError:
                raise HTTPException(status_code=404, detail="Segment not found.")
        else:
            try:
                pk = int(raw)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Built-in segments cannot be edited. Only custom segments (created by you) can be updated."
                )

        segment = await session.get(CRMSegments, pk)
        if not segment:
            raise HTTPException(status_code=404, detail="Segment not found.")
        if segment.segment_type != "custom":
            raise HTTPException(
                status_code=400,
                detail="Only user-created segments can be updated. Built-in segments are read-only."
            )
        if request.name != segment.name:
            existing = await session.exec(select(CRMSegments).where(CRMSegments.name == request.name))
            if existing.first():
                raise HTTPException(status_code=400, detail="A segment with this name already exists.")

        criteria = {
            "conditions": request.conditions,
            "color": request.color or "#6B7280",
            "icon": request.icon or "users",
            "avgRevenue": request.avgRevenue,
            "repeatRate": request.repeatRate,
        }
        segment.name = request.name
        segment.description = request.description or None
        segment.criteria = criteria
        segment.member_count = request.guestCount
        segment.updated_at = datetime.utcnow()
        session.add(segment)
        await session.commit()
        await session.refresh(segment)
        return {
            "success": True,
            "data": {
                "id": f"seg-custom-{segment.id}",
                "name": segment.name,
                "description": segment.description or "",
                "conditions": request.conditions,
                "guestCount": segment.member_count,
                "avgRevenue": request.avgRevenue,
                "repeatRate": request.repeatRate,
                "color": request.color or "#6B7280",
                "icon": request.icon or "users",
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/crm-segments/{segment_id}", response_model=dict)
async def delete_crm_segment(
    segment_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a custom CRM segment by id. Only custom (user-created) segments can be deleted.
    segment_id can be "seg-custom-123" or the numeric id "123".
    """
    from sqlmodel import select
    from app.models.crm import CRMSegments, GuestSegments
    from sqlalchemy import delete as sql_delete

    try:
        # Parse numeric id from "seg-custom-123" or "123"
        raw = segment_id.strip()
        if raw.startswith("seg-custom-"):
            try:
                pk = int(raw.replace("seg-custom-", "", 1))
            except ValueError:
                raise HTTPException(status_code=404, detail="Segment not found.")
        else:
            try:
                pk = int(raw)
            except ValueError:
                raise HTTPException(status_code=404, detail="Segment not found.")

        segment = await session.get(CRMSegments, pk)
        if not segment:
            raise HTTPException(status_code=404, detail="Segment not found.")
        if segment.segment_type != "custom":
            raise HTTPException(
                status_code=400,
                detail="Only user-created segments can be deleted. Built-in segments are read-only."
            )

        # Remove guest-segment associations first (FK constraint)
        await session.execute(sql_delete(GuestSegments).where(GuestSegments.segment_id == pk))
        await session.delete(segment)
        await session.commit()
        return {"success": True, "message": "Segment deleted."}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/crm-segments", response_model=dict)
async def get_crm_segments(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get dynamic guest segments based on actual database data, plus user-created custom segments.
    """
    from sqlmodel import select, func
    from app.models.reservations import Guest, Booking
    from app.models.crm import CRMSegments
    from datetime import timedelta
    import json

    try:
        # Get all active guests
        guest_query = select(Guest).where(Guest.status != "Inactive")
        result = await session.exec(guest_query)
        all_guests = result.all()

        # Get actual booking stats per guest (revenue, booking count, nights)
        booking_stats_query = (
            select(
                Booking.guest_id,
                func.sum(Booking.total_price).label("total_revenue"),
                func.count(Booking.id).label("booking_count"),
                func.sum(Booking.nights).label("total_nights")
            )
            .where(Booking.status.notin_(["cancelled", "no_show"]))
            .group_by(Booking.guest_id)
        )
        booking_result = await session.exec(booking_stats_query)
        booking_stats = {row[0]: {"revenue": row[1] or 0, "bookings": row[2] or 0, "nights": row[3] or 0} for row in booking_result.all()}

        # Helper to get actual guest revenue from bookings
        def get_guest_revenue(g):
            return booking_stats.get(g.id, {}).get("revenue", 0)

        def get_guest_bookings(g):
            return booking_stats.get(g.id, {}).get("bookings", 0)

        def get_guest_nights(g):
            return booking_stats.get(g.id, {}).get("nights", 0)

        # Calculate segment data dynamically
        segments = []

        # 1. High Value Guests (LTV > INR 12,50,000 from actual bookings)
        high_value = [g for g in all_guests if get_guest_revenue(g) >= 1250000]
        if high_value:
            avg_rev = sum(get_guest_revenue(g) for g in high_value) / len(high_value)
            repeat_rate = len([g for g in high_value if get_guest_bookings(g) > 1]) / len(high_value) * 100
            segments.append({
                "id": "seg-high-value",
                "name": "High Value Guests",
                "description": "Guests with lifetime value above INR 12,50,000",
                "conditions": [{"field": "totalRevenue", "operator": ">=", "value": 1250000}],
                "guestCount": len(high_value),
                "avgRevenue": round(avg_rev, 2),
                "repeatRate": round(repeat_rate, 0),
                "color": "#22C55E",
                "icon": "dollar-sign"
            })

        # 2. OTA Frequent Bookers (booking source is OTA and 3+ stays)
        ota_sources = ["booking", "expedia", "agoda", "hotels.com", "ota"]
        ota_frequent = [g for g in all_guests if g.booking_source and g.booking_source.lower() in ota_sources and get_guest_bookings(g) >= 3]
        if ota_frequent:
            avg_rev = sum(get_guest_revenue(g) for g in ota_frequent) / len(ota_frequent)
            repeat_rate = len([g for g in ota_frequent if get_guest_bookings(g) > 1]) / len(ota_frequent) * 100
            segments.append({
                "id": "seg-ota-frequent",
                "name": "OTA Frequent Bookers",
                "description": "Guests who book via OTAs and have 3+ stays",
                "conditions": [
                    {"field": "bookingSource", "operator": "in", "value": ota_sources},
                    {"field": "totalStays", "operator": ">=", "value": 3}
                ],
                "guestCount": len(ota_frequent),
                "avgRevenue": round(avg_rev, 2),
                "repeatRate": round(repeat_rate, 0),
                "color": "#3B82F6",
                "icon": "globe"
            })

        # 3. Corporate Travellers
        corporate = [g for g in all_guests if g.booking_source and "corporate" in g.booking_source.lower()]
        if corporate:
            avg_rev = sum(get_guest_revenue(g) for g in corporate) / len(corporate) if corporate else 0
            repeat_rate = len([g for g in corporate if get_guest_bookings(g) > 1]) / len(corporate) * 100 if corporate else 0
            segments.append({
                "id": "seg-corporate",
                "name": "Corporate Travellers",
                "description": "Corporate account guests",
                "conditions": [{"field": "bookingSource", "operator": "==", "value": "corporate"}],
                "guestCount": len(corporate),
                "avgRevenue": round(avg_rev, 2),
                "repeatRate": round(repeat_rate, 0),
                "color": "#8B5CF6",
                "icon": "briefcase"
            })

        # 4. Long-Stay Guests (average stay > 5 nights from actual bookings)
        long_stay = [g for g in all_guests if get_guest_nights(g) > 0 and get_guest_bookings(g) > 0 and (get_guest_nights(g) / get_guest_bookings(g)) > 5]
        if long_stay:
            avg_rev = sum(get_guest_revenue(g) for g in long_stay) / len(long_stay)
            repeat_rate = len([g for g in long_stay if get_guest_bookings(g) > 1]) / len(long_stay) * 100
            segments.append({
                "id": "seg-long-stay",
                "name": "Long-Stay Guests",
                "description": "Guests with average stay > 5 nights",
                "conditions": [{"field": "avgStayDuration", "operator": ">", "value": 5}],
                "guestCount": len(long_stay),
                "avgRevenue": round(avg_rev, 2),
                "repeatRate": round(repeat_rate, 0),
                "color": "#F59E0B",
                "icon": "calendar"
            })

        # 5. VIP Guests
        vip_guests = [g for g in all_guests if g.vip_status]
        if vip_guests:
            avg_rev = sum(get_guest_revenue(g) for g in vip_guests) / len(vip_guests) if vip_guests else 0
            repeat_rate = len([g for g in vip_guests if get_guest_bookings(g) > 1]) / len(vip_guests) * 100 if vip_guests else 0
            segments.append({
                "id": "seg-vip",
                "name": "VIP Guests",
                "description": "Guests with VIP status",
                "conditions": [{"field": "vipStatus", "operator": "==", "value": True}],
                "guestCount": len(vip_guests),
                "avgRevenue": round(avg_rev, 2),
                "repeatRate": round(repeat_rate, 0),
                "color": "#EC4899",
                "icon": "crown"
            })

        # 6. Recent Guests (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent = [g for g in all_guests if g.last_visit and g.last_visit >= thirty_days_ago]
        if recent:
            avg_rev = sum(get_guest_revenue(g) for g in recent) / len(recent) if recent else 0
            repeat_rate = len([g for g in recent if get_guest_bookings(g) > 1]) / len(recent) * 100 if recent else 0
            segments.append({
                "id": "seg-recent",
                "name": "Last 30 Days Guests",
                "description": "Recent guests for retention campaigns",
                "conditions": [{"field": "lastStay", "operator": "within", "value": "30d"}],
                "guestCount": len(recent),
                "avgRevenue": round(avg_rev, 2),
                "repeatRate": round(repeat_rate, 0),
                "color": "#06B6D4",
                "icon": "clock"
            })

        # 7. All Guests segment (always show this)
        if all_guests:
            avg_rev = sum(get_guest_revenue(g) for g in all_guests) / len(all_guests) if all_guests else 0
            repeat_rate = len([g for g in all_guests if get_guest_bookings(g) > 1]) / len(all_guests) * 100 if all_guests else 0
            segments.insert(0, {
                "id": "seg-all",
                "name": "All Guests",
                "description": "Complete guest database",
                "conditions": [],
                "guestCount": len(all_guests),
                "avgRevenue": round(avg_rev, 2),
                "repeatRate": round(repeat_rate, 0),
                "color": "#6B7280",
                "icon": "users"
            })

        # 8. User-created custom segments (persisted in crm_segments)
        custom_result = await session.exec(
            select(CRMSegments).where(
                CRMSegments.segment_type == "custom",
                CRMSegments.is_active == True
            ).order_by(CRMSegments.created_at.desc())
        )
        for row in custom_result.all():
            criteria = row.criteria or {}
            if isinstance(criteria, str):
                try:
                    criteria = json.loads(criteria) if criteria else {}
                except Exception:
                    criteria = {}
            segments.append({
                "id": f"seg-custom-{row.id}",
                "name": row.name,
                "description": row.description or "",
                "conditions": criteria.get("conditions", []),
                "guestCount": row.member_count,
                "avgRevenue": float(criteria.get("avgRevenue", 0)),
                "repeatRate": float(criteria.get("repeatRate", 0)),
                "color": criteria.get("color") or "#6B7280",
                "icon": criteria.get("icon") or "users"
            })

        return {
            "success": True,
            "data": {
                "segments": segments,
                "total": len(segments)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/crm-stats", response_model=dict)
async def get_crm_stats(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get CRM statistics from real database
    """
    from sqlmodel import select, func
    from app.models.reservations import Guest, Booking
    from app.models.crm import Campaigns

    try:
        # Total guests
        total_query = select(func.count(Guest.id)).where(Guest.status != "Inactive")
        total_result = await session.exec(total_query)
        total_guests = total_result.one()

        # Repeat guests (more than 1 booking) - count from actual bookings
        repeat_subquery = (
            select(Booking.guest_id, func.count(Booking.id).label("booking_count"))
            .where(Booking.status.notin_(["cancelled", "no_show"]))
            .group_by(Booking.guest_id)
            .having(func.count(Booking.id) > 1)
        ).subquery()
        repeat_query = select(func.count()).select_from(repeat_subquery)
        repeat_result = await session.exec(repeat_query)
        repeat_guests = repeat_result.one() or 0

        # Average LTV - Calculate from actual Booking.total_price, not Guest.total_spent
        # Only count guests who actually have bookings
        ltv_subquery = (
            select(
                Booking.guest_id,
                func.sum(Booking.total_price).label("guest_ltv")
            )
            .where(Booking.status.notin_(["cancelled", "no_show"]))
            .group_by(Booking.guest_id)
        ).subquery()

        ltv_query = select(func.avg(ltv_subquery.c.guest_ltv))
        ltv_result = await session.exec(ltv_query)
        avg_ltv = ltv_result.one() or 0

        # VIP count
        vip_query = select(func.count(Guest.id)).where(
            Guest.status != "Inactive",
            Guest.vip_status == True
        )
        vip_result = await session.exec(vip_query)
        vip_count = vip_result.one()

        # Loyalty members (guests with loyalty tier)
        loyalty_query = select(func.count(Guest.id)).where(
            Guest.status != "Inactive",
            Guest.loyalty_tier.isnot(None)
        )
        loyalty_result = await session.exec(loyalty_query)
        loyalty_members = loyalty_result.one()

        # Active campaigns
        try:
            campaign_query = select(func.count(Campaigns.id)).where(Campaigns.status == "active")
            campaign_result = await session.exec(campaign_query)
            active_campaigns = campaign_result.one()
        except:
            active_campaigns = 0

        return {
            "success": True,
            "data": {
                "totalGuests": total_guests,
                "repeatGuests": repeat_guests,
                "avgLTV": round(float(avg_ltv), 2),
                "vipGuests": vip_count,
                "loyaltyMembers": loyalty_members,
                "activeCampaigns": active_campaigns,
                "engagementRate": 44  # Placeholder - would need campaign tracking
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# AI SUGGESTIONS ENDPOINT
# ============================================

@router.get("/ai-suggestions", response_model=dict)
async def get_ai_suggestions(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get AI-powered suggestions for campaigns, segments, and guest engagement.
    Analyzes guest data to provide actionable recommendations.
    """
    from sqlmodel import select, func
    from app.models.reservations import Guest, Booking
    from datetime import timedelta

    try:
        suggestions = {
            "campaign_suggestions": [],
            "segment_insights": [],
            "action_items": [],
            "quick_wins": []
        }

        # Get all active guests
        guest_query = select(Guest).where(Guest.status != "Inactive")
        result = await session.exec(guest_query)
        all_guests = result.all()

        if not all_guests:
            return {
                "success": True,
                "data": {
                    **suggestions,
                    "message": "No guest data available for analysis"
                }
            }

        # Get booking stats per guest
        booking_stats_query = (
            select(
                Booking.guest_id,
                func.sum(Booking.total_price).label("total_revenue"),
                func.count(Booking.id).label("booking_count"),
                func.max(Booking.arrival_date).label("last_stay")
            )
            .where(Booking.status.notin_(["cancelled", "no_show"]))
            .group_by(Booking.guest_id)
        )
        booking_result = await session.exec(booking_stats_query)
        booking_stats = {
            row[0]: {"revenue": float(row[1] or 0), "bookings": int(row[2] or 0), "last_stay": row[3]}
            for row in booking_result.all()
        }

        def get_guest_revenue(g):
            return booking_stats.get(g.id, {}).get("revenue", 0)

        def get_guest_bookings(g):
            return booking_stats.get(g.id, {}).get("bookings", 0)

        # Analyze guest data for suggestions
        total_guests = len(all_guests)
        guests_with_bookings = [g for g in all_guests if get_guest_bookings(g) > 0]
        high_value_guests = [g for g in all_guests if get_guest_revenue(g) >= 10000]
        repeat_guests = [g for g in all_guests if get_guest_bookings(g) > 1]
        vip_guests = [g for g in all_guests if g.vip_status]

        # OTA guests for direct booking conversion
        ota_sources = ["booking", "expedia", "agoda", "hotels.com", "ota"]
        ota_guests = [g for g in all_guests if g.booking_source and g.booking_source.lower() in ota_sources]

        # Guests without recent activity (30+ days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        inactive_guests = [g for g in all_guests if g.last_visit and g.last_visit < thirty_days_ago]

        # Generate Campaign Suggestions
        if ota_guests:
            ota_conversion_rate = len([g for g in ota_guests if get_guest_bookings(g) > 1]) / len(ota_guests) * 100 if ota_guests else 0
            suggestions["campaign_suggestions"].append({
                "id": "ota-conversion",
                "title": "OTA to Direct Booking Campaign",
                "description": f"Convert {len(ota_guests)} OTA bookers to direct bookers with exclusive discounts",
                "priority": "high",
                "type": "win_back",
                "target_count": len(ota_guests),
                "estimated_impact": f"Potential 15-20% commission savings",
                "recommended_offer": "15% direct booking discount + loyalty points",
                "best_channel": "email",
                "icon": "globe"
            })

        if inactive_guests:
            suggestions["campaign_suggestions"].append({
                "id": "reactivation",
                "title": "Guest Reactivation Campaign",
                "description": f"Re-engage {len(inactive_guests)} guests who haven't stayed in 30+ days",
                "priority": "high" if len(inactive_guests) > 10 else "medium",
                "type": "win_back",
                "target_count": len(inactive_guests),
                "estimated_impact": f"Recover {round(len(inactive_guests) * 0.1)} potential bookings",
                "recommended_offer": "10% comeback discount or free upgrade",
                "best_channel": "email",
                "icon": "refresh"
            })

        if high_value_guests:
            suggestions["campaign_suggestions"].append({
                "id": "vip-appreciation",
                "title": "High-Value Guest Appreciation",
                "description": f"Reward your top {len(high_value_guests)} high-value guests",
                "priority": "medium",
                "type": "loyalty",
                "target_count": len(high_value_guests),
                "estimated_impact": "Increase repeat bookings by 25%",
                "recommended_offer": "Complimentary upgrade or spa credit",
                "best_channel": "email",
                "icon": "star"
            })

        if repeat_guests:
            suggestions["campaign_suggestions"].append({
                "id": "loyalty-tier-upgrade",
                "title": "Loyalty Tier Advancement",
                "description": f"Encourage {len(repeat_guests)} repeat guests to reach the next tier",
                "priority": "medium",
                "type": "loyalty",
                "target_count": len(repeat_guests),
                "estimated_impact": "Drive additional 2-3 stays per guest",
                "recommended_offer": "Double points on next stay",
                "best_channel": "email",
                "icon": "award"
            })

        # Generate Segment Insights
        if guests_with_bookings:
            booking_ratio = len(guests_with_bookings) / total_guests * 100
            suggestions["segment_insights"].append({
                "title": "Booking Activity",
                "insight": f"{booking_ratio:.1f}% of registered guests have made bookings",
                "recommendation": "Focus on activating non-booking guests with first-time offers" if booking_ratio < 50 else "Healthy booking rate - focus on repeat bookings",
                "icon": "activity"
            })

        if vip_guests:
            vip_ratio = len(vip_guests) / total_guests * 100
            suggestions["segment_insights"].append({
                "title": "VIP Concentration",
                "insight": f"{len(vip_guests)} VIP guests ({vip_ratio:.1f}% of total)",
                "recommendation": "Maintain VIP relationships with personalized outreach",
                "icon": "crown"
            })

        if ota_guests:
            ota_ratio = len(ota_guests) / total_guests * 100
            suggestions["segment_insights"].append({
                "title": "OTA Dependency",
                "insight": f"{ota_ratio:.1f}% of guests book through OTAs",
                "recommendation": "High OTA dependency - prioritize direct booking incentives" if ota_ratio > 40 else "Good direct booking balance",
                "icon": "globe"
            })

        # Generate Action Items
        if len(inactive_guests) > 5:
            suggestions["action_items"].append({
                "title": "Send Win-Back Emails",
                "description": f"Target {len(inactive_guests)} inactive guests with special offers",
                "urgency": "high",
                "action_type": "campaign",
                "icon": "mail"
            })

        if ota_guests and len(ota_guests) > total_guests * 0.3:
            suggestions["action_items"].append({
                "title": "Launch Direct Booking Initiative",
                "description": "Create incentive program to convert OTA guests",
                "urgency": "medium",
                "action_type": "strategy",
                "icon": "trending-up"
            })

        suggestions["action_items"].append({
            "title": "Review Guest Segments",
            "description": "Ensure segments are up-to-date for targeted campaigns",
            "urgency": "low",
            "action_type": "maintenance",
            "icon": "layers"
        })

        # Generate Quick Wins
        suggestions["quick_wins"].append({
            "title": "Welcome Email Automation",
            "description": "Set up automated welcome emails for new guests",
            "effort": "low",
            "impact": "medium",
            "icon": "zap"
        })

        if guests_with_bookings:
            suggestions["quick_wins"].append({
                "title": "Post-Stay Feedback Request",
                "description": "Send automated feedback requests after checkout",
                "effort": "low",
                "impact": "high",
                "icon": "message-circle"
            })

        suggestions["quick_wins"].append({
            "title": "Birthday Campaign",
            "description": "Send personalized birthday offers to guests",
            "effort": "low",
            "impact": "medium",
            "icon": "gift"
        })

        return {
            "success": True,
            "data": {
                **suggestions,
                "analyzed_guests": total_guests,
                "generated_at": datetime.utcnow().isoformat()
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
