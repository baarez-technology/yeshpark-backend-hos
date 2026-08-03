"""
CRM AI API Routes - ReConnect AI Integration
Provides endpoints for guest intelligence, churn prediction, LTV,
rebooking probability, sentiment analysis, and campaign optimization.
"""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, Field

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.services.crm_ai.reconnect_ai_service import reconnect_ai

router = APIRouter()


# ============ Request/Response Schemas ============

class SentimentAnalysisRequest(BaseModel):
    text: str = Field(..., description="Text to analyze")
    source: str = Field(default="feedback", description="Source of text (feedback, review, chat, email)")
    booking_id: Optional[int] = Field(default=None, description="Associated booking ID")


class SentimentAnalysisResponse(BaseModel):
    guest_id: int
    analysis: dict
    recovery_triggered: bool
    logged_at: str


class CampaignRecommendationRequest(BaseModel):
    campaign_type: Optional[str] = Field(default=None, description="Filter by campaign type")
    limit: int = Field(default=100, ge=1, le=500)


class BatchSentimentRequest(BaseModel):
    texts: List[dict] = Field(..., description="List of {text, source} objects")


class RecoveryActionRequest(BaseModel):
    action_taken: str = Field(..., description="Description of action taken")
    compensation_offered: Optional[str] = None
    compensation_value: Optional[float] = None


# ============ Dashboard & Statistics ============

@router.get("/dashboard")
async def get_crm_ai_dashboard(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get CRM AI dashboard statistics

    Returns overview metrics including:
    - Total guests analyzed
    - Health score distribution
    - Average churn risk
    - Open alerts count
    - Recovery opportunities pending
    """
    try:
        stats = await reconnect_ai.get_dashboard_stats(session)
        return {
            "success": True,
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Guest Intelligence ============

@router.get("/guests/{guest_id}/intelligence")
async def get_guest_intelligence(
    guest_id: int,
    include_history: bool = Query(default=False, description="Include score history"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get comprehensive AI intelligence for a guest

    Returns:
    - Health Score (0-100)
    - Churn Probability (0-100%)
    - Lifetime Value prediction
    - Rebooking probability
    - Campaign recommendations
    - Key insights and recommended actions
    """
    try:
        intelligence = await reconnect_ai.get_guest_intelligence(
            session, guest_id, include_history
        )
        return {
            "success": True,
            "data": intelligence
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guests/{guest_id}/health-score")
async def get_guest_health_score(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get guest health score with component breakdown

    Health score is calculated from:
    - Recency (25%)
    - Frequency (20%)
    - Monetary (20%)
    - Engagement (15%)
    - Sentiment (15%)
    - Loyalty (5%)
    """
    try:
        from app.services.crm_ai import FeatureStore, HealthScoreModel

        features = await FeatureStore.get_guest_features(session, guest_id)
        health_model = HealthScoreModel()
        result = health_model.calculate(features)

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "health_score": result["health_score"],
                "score_label": result["score_label"],
                "components": result["components"],
                "explanation": result["explanation"],
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guests/{guest_id}/churn-risk")
async def get_guest_churn_risk(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get guest churn prediction with risk factors

    Returns:
    - Churn probability (0-100%)
    - Risk level (low, medium, high, critical)
    - Key churn drivers
    - Mitigation recommendations
    """
    try:
        from app.services.crm_ai import FeatureStore, ChurnPredictionModel

        features = await FeatureStore.get_guest_features(session, guest_id)
        churn_model = ChurnPredictionModel()
        result = churn_model.predict(features)

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "churn_probability": result["churn_probability"],
                "churn_risk": result["churn_risk"],
                "is_high_risk": result["is_high_risk"],
                "churn_drivers": result["churn_drivers"],
                "churn_reasons": result["churn_reasons"],
                "mitigation_actions": result["explanation"]["mitigation_actions"],
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guests/{guest_id}/ltv")
async def get_guest_ltv(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get guest lifetime value prediction

    Returns:
    - Predicted total LTV
    - Historical LTV (already spent)
    - Future LTV prediction
    - LTV segment classification
    - Key value drivers
    """
    try:
        from app.services.crm_ai import FeatureStore, LTVModel

        features = await FeatureStore.get_guest_features(session, guest_id)
        ltv_model = LTVModel()
        result = ltv_model.predict(features)

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "predicted_ltv": result["predicted_ltv"],
                "historical_ltv": result["historical_ltv"],
                "future_ltv": result["future_ltv"],
                "ltv_segment": result["ltv_segment"],
                "confidence": result["confidence"],
                "components": result["components"],
                "explanation": result["explanation"],
                "recommendations": result["recommendations"],
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guests/{guest_id}/rebooking")
async def get_guest_rebooking_probability(
    guest_id: int,
    timeframe_days: int = Query(default=90, ge=30, le=365),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get guest rebooking probability prediction

    Returns:
    - Rebooking probability within timeframe
    - Optimal contact timing
    - Recommended offers
    - Key factors influencing probability
    """
    try:
        from app.services.crm_ai import FeatureStore, RebookingModel

        features = await FeatureStore.get_guest_features(session, guest_id)
        rebooking_model = RebookingModel()
        result = rebooking_model.predict(features, timeframe_days)

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "rebooking_probability": result["rebooking_probability"],
                "probability_label": result["probability_label"],
                "timeframe_days": result["timeframe_days"],
                "factors": result["factors"],
                "optimal_contact": result["optimal_contact"],
                "recommended_offers": result["recommended_offers"],
                "explanation": result["explanation"],
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Sentiment Analysis ============

@router.post("/guests/{guest_id}/sentiment")
async def analyze_guest_sentiment(
    guest_id: int,
    request: SentimentAnalysisRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Analyze sentiment from guest text (feedback, review, chat message)

    Automatically:
    - Logs sentiment to database
    - Triggers recovery check if negative
    - Creates alerts if needed
    """
    try:
        result = await reconnect_ai.analyze_sentiment(
            session,
            guest_id,
            request.text,
            request.source,
            request.booking_id
        )
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guests/{guest_id}/sentiment/timeline")
async def get_sentiment_timeline(
    guest_id: int,
    days: int = Query(default=90, ge=7, le=365),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get sentiment history timeline for a guest

    Returns:
    - Sentiment trend (improving/declining/stable)
    - Timeline of sentiment entries
    - Aggregation by source
    """
    try:
        result = await reconnect_ai.get_sentiment_timeline(session, guest_id, days)
        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sentiment/analyze")
async def analyze_text_sentiment(
    text: str = Body(..., embed=True),
    source: str = Body(default="feedback", embed=True),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Analyze sentiment of any text without associating with a guest
    Useful for previewing sentiment before logging
    """
    try:
        from app.services.crm_ai import SentimentAnalyzer

        analyzer = SentimentAnalyzer()
        result = analyzer.analyze(text, source)

        return {
            "success": True,
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ At-Risk Guests & Recovery ============

@router.get("/at-risk-guests")
async def get_at_risk_guests(
    limit: int = Query(default=50, ge=1, le=200),
    min_churn_risk: int = Query(default=60, ge=0, le=100),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get list of at-risk guests requiring attention

    Sorted by priority (critical, high) and churn probability
    """
    try:
        guests = await reconnect_ai.get_at_risk_guests(session, limit, min_churn_risk)
        return {
            "success": True,
            "data": {
                "at_risk_count": len(guests),
                "guests": guests
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recovery/opportunities")
async def get_recovery_opportunities(
    status: str = Query(default="detected", description="Filter by status"),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get service recovery opportunities

    Lists detected issues requiring proactive recovery action
    """
    try:
        opportunities = await reconnect_ai.get_recovery_opportunities(session, status, limit)
        return {
            "success": True,
            "data": {
                "count": len(opportunities),
                "opportunities": opportunities
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recovery/{recovery_id}/resolve")
async def resolve_recovery(
    recovery_id: int,
    request: RecoveryActionRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Mark a recovery case as resolved
    """
    try:
        from app.models.crm_ai import RecoveryLog

        recovery = await session.get(RecoveryLog, recovery_id)
        if not recovery:
            raise HTTPException(status_code=404, detail="Recovery log not found")

        recovery.status = "resolved"
        recovery.action_taken = request.action_taken
        recovery.compensation_offered = request.compensation_offered
        recovery.compensation_value = request.compensation_value
        recovery.resolved_by = current_user.staff_id if hasattr(current_user, 'staff_id') else None
        recovery.resolved_at = datetime.utcnow()
        recovery.updated_at = datetime.utcnow()

        session.add(recovery)
        await session.commit()

        return {
            "success": True,
            "message": "Recovery resolved successfully",
            "data": {
                "recovery_id": recovery_id,
                "status": "resolved",
                "resolved_at": recovery.resolved_at.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Campaign Optimization ============

@router.get("/campaigns/recommendations")
async def get_campaign_recommendations(
    campaign_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get AI-powered campaign recommendations

    Returns guests segmented by recommended campaign type:
    - win_back: High churn risk guests
    - loyalty: Healthy VIP guests
    - upsell: Good rebooking probability
    - direct_booking: OTA conversion opportunities
    """
    try:
        recommendations = await reconnect_ai.get_campaign_recommendations(
            session, campaign_type, limit
        )
        return {
            "success": True,
            "data": recommendations
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guests/{guest_id}/campaign-recommendation")
async def get_guest_campaign_recommendation(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get personalized campaign recommendation for a specific guest
    """
    try:
        from app.services.crm_ai import FeatureStore, HealthScoreModel, ChurnPredictionModel, LTVModel, RebookingModel, CampaignOptimizer

        features = await FeatureStore.get_guest_features(session, guest_id)

        health = HealthScoreModel().calculate(features)
        churn = ChurnPredictionModel().predict(features)
        ltv = LTVModel().predict(features)
        rebooking = RebookingModel().predict(features)

        guest_scores = {
            "health_score": health["health_score"],
            "churn_probability": churn["churn_probability"],
            "predicted_ltv": ltv["predicted_ltv"],
            "rebooking_probability": rebooking["rebooking_probability"],
        }

        optimizer = CampaignOptimizer()
        recommendation = optimizer.recommend_campaign(features, guest_scores)

        return {
            "success": True,
            "data": {
                "guest_id": guest_id,
                "recommendation": recommendation
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Alerts Management ============

@router.get("/alerts")
async def get_ai_alerts(
    status: str = Query(default="open", description="Alert status filter"),
    priority: Optional[str] = Query(default=None, description="Priority filter"),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get AI-generated alerts
    """
    try:
        from sqlmodel import select, and_
        from app.models.crm_ai import AIAlert
        from app.models.reservations import Guest

        query = select(AIAlert).where(AIAlert.status == status)

        if priority:
            query = query.where(AIAlert.priority == priority)

        query = query.order_by(AIAlert.created_at.desc()).limit(limit)

        result = await session.exec(query)
        alerts = result.all()

        alert_list = []
        for alert in alerts:
            guest = await session.get(Guest, alert.guest_id)
            alert_list.append({
                "id": alert.id,
                "guest_id": alert.guest_id,
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
                "alert_type": alert.alert_type,
                "priority": alert.priority,
                "title": alert.title,
                "message": alert.message,
                "trigger_value": alert.trigger_value,
                "status": alert.status,
                "created_at": alert.created_at.isoformat(),
            })

        return {
            "success": True,
            "data": {
                "count": len(alert_list),
                "alerts": alert_list
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/alerts/{alert_id}")
async def update_alert(
    alert_id: int,
    status: str = Body(..., embed=True),
    resolution_notes: Optional[str] = Body(default=None, embed=True),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update alert status (acknowledge, resolve, dismiss)
    """
    try:
        from app.models.crm_ai import AIAlert

        alert = await session.get(AIAlert, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        alert.status = status
        alert.updated_at = datetime.utcnow()

        if status == "acknowledged":
            alert.acknowledged_by = current_user.id
            alert.acknowledged_at = datetime.utcnow()
        elif status == "resolved":
            alert.resolved_by = current_user.id
            alert.resolved_at = datetime.utcnow()
            alert.resolution_notes = resolution_notes

        session.add(alert)
        await session.commit()

        return {
            "success": True,
            "message": f"Alert {status} successfully",
            "data": {
                "alert_id": alert_id,
                "status": status
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Batch Operations ============

@router.post("/batch/calculate-scores")
async def batch_calculate_scores(
    guest_ids: List[int] = Body(..., embed=True),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Calculate AI scores for multiple guests
    Useful for refreshing scores for a segment
    """
    try:
        results = []
        errors = []

        for guest_id in guest_ids[:100]:  # Limit to 100
            try:
                intelligence = await reconnect_ai.get_guest_intelligence(session, guest_id)
                results.append({
                    "guest_id": guest_id,
                    "health_score": intelligence["scores"]["health"]["score"],
                    "churn_probability": intelligence["scores"]["churn"]["probability"],
                    "ltv": intelligence["scores"]["ltv"]["predicted_value"],
                })
            except Exception as e:
                errors.append({"guest_id": guest_id, "error": str(e)})

        return {
            "success": True,
            "data": {
                "processed": len(results),
                "errors": len(errors),
                "results": results,
                "error_details": errors[:10]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/segments/analysis")
async def get_segment_analysis(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get AI-based guest segmentation analysis

    Returns distribution of guests across:
    - Health score segments
    - LTV segments
    - Churn risk levels
    """
    try:
        from sqlmodel import select
        from app.models.crm_ai import AIScore

        # Get latest scores
        health_result = await session.exec(
            select(AIScore)
            .where(AIScore.score_type == "health_score")
            .order_by(AIScore.calculated_at.desc())
            .limit(500)
        )
        health_scores = health_result.all()

        churn_result = await session.exec(
            select(AIScore)
            .where(AIScore.score_type == "churn_probability")
            .order_by(AIScore.calculated_at.desc())
            .limit(500)
        )
        churn_scores = churn_result.all()

        ltv_result = await session.exec(
            select(AIScore)
            .where(AIScore.score_type == "ltv")
            .order_by(AIScore.calculated_at.desc())
            .limit(500)
        )
        ltv_scores = ltv_result.all()

        # Aggregate
        health_segments = {"excellent": 0, "good": 0, "fair": 0, "at_risk": 0, "critical": 0}
        for score in health_scores:
            label = (score.score_label or "fair").lower().replace("-", "_")
            if label in health_segments:
                health_segments[label] += 1

        churn_segments = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for score in churn_scores:
            label = (score.score_label or "medium").lower()
            if label in churn_segments:
                churn_segments[label] += 1

        ltv_segments = {"high_value": 0, "medium_high": 0, "medium": 0, "low_medium": 0, "low": 0}
        for score in ltv_scores:
            label = (score.score_label or "medium").lower().replace(" ", "_")
            if label in ltv_segments:
                ltv_segments[label] += 1

        return {
            "success": True,
            "data": {
                "total_analyzed": len(health_scores),
                "health_segments": health_segments,
                "churn_segments": churn_segments,
                "ltv_segments": ltv_segments,
                "analyzed_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
