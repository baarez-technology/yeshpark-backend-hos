"""
ReConnect AI Service
Main orchestration service for all CRM AI features
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlmodel import select, func, and_
from sqlmodel.ext.asyncio.session import AsyncSession
import json

from .feature_store import FeatureStore
from .health_score import HealthScoreModel
from .churn_prediction import ChurnPredictionModel
from .ltv_model import LTVModel
from .rebooking_model import RebookingModel
from .sentiment_analyzer import SentimentAnalyzer
from .campaign_optimizer import CampaignOptimizer, CampaignType

from app.models.reservations import Guest
from app.models.crm_ai import AIScore, AIAlert, RecoveryLog, SentimentLog


class ReConnectAIService:
    """
    ReConnect AI - Unified CRM Intelligence Service

    Provides:
    - Guest Intelligence (health score, churn, LTV, rebooking)
    - Sentiment Analysis
    - Proactive Recovery
    - Campaign Optimization
    - Guest Segmentation
    """

    def __init__(self):
        self.health_model = HealthScoreModel()
        self.churn_model = ChurnPredictionModel()
        self.ltv_model = LTVModel()
        self.rebooking_model = RebookingModel()
        self.sentiment_analyzer = SentimentAnalyzer()
        self.campaign_optimizer = CampaignOptimizer()

    async def get_guest_intelligence(
        self,
        session: AsyncSession,
        guest_id: int,
        include_history: bool = False
    ) -> Dict[str, Any]:
        """
        Get comprehensive AI intelligence for a guest
        Combines all AI scores and recommendations
        """
        # Get guest features
        features = await FeatureStore.get_guest_features(session, guest_id)

        # Calculate all AI scores
        health_result = self.health_model.calculate(features)
        churn_result = self.churn_model.predict(features)
        ltv_result = self.ltv_model.predict(features)
        rebooking_result = self.rebooking_model.predict(features)

        # Get campaign recommendation
        guest_scores = {
            "health_score": health_result["health_score"],
            "churn_probability": churn_result["churn_probability"],
            "predicted_ltv": ltv_result["predicted_ltv"],
            "rebooking_probability": rebooking_result["rebooking_probability"],
        }
        campaign_rec = self.campaign_optimizer.recommend_campaign(features, guest_scores)

        # Store scores in database
        await self._store_ai_scores(session, guest_id, health_result, churn_result, ltv_result, rebooking_result)

        # Check for alerts
        alerts = await self._check_and_create_alerts(session, guest_id, churn_result, health_result)

        result = {
            "guest_id": guest_id,
            "guest_info": {
                "name": features.get("guest_name"),
                "email": features.get("email"),
                "vip_status": features.get("vip_status"),
                "loyalty_tier": features.get("loyalty_tier"),
            },
            "scores": {
                "health": {
                    "score": health_result["health_score"],
                    "label": health_result["score_label"],
                    "components": health_result["components"],
                },
                "churn": {
                    "probability": churn_result["churn_probability"],
                    "risk_level": churn_result["churn_risk"],
                    "is_high_risk": churn_result["is_high_risk"],
                    "drivers": churn_result["churn_drivers"][:3],
                },
                "ltv": {
                    "predicted_value": ltv_result["predicted_ltv"],
                    "historical_value": ltv_result["historical_ltv"],
                    "future_value": ltv_result["future_ltv"],
                    "segment": ltv_result["ltv_segment"],
                },
                "rebooking": {
                    "probability": rebooking_result["rebooking_probability"],
                    "likelihood": rebooking_result["probability_label"],
                    "optimal_contact": rebooking_result["optimal_contact"],
                },
            },
            "campaign_recommendation": campaign_rec,
            "alerts": alerts,
            "key_insights": self._generate_key_insights(health_result, churn_result, ltv_result, rebooking_result),
            "recommended_actions": self._get_top_actions(churn_result, rebooking_result, ltv_result),
            "calculated_at": datetime.utcnow().isoformat(),
        }

        # Include score history if requested
        if include_history:
            result["score_history"] = await self._get_score_history(session, guest_id)

        return result

    async def analyze_sentiment(
        self,
        session: AsyncSession,
        guest_id: int,
        text: str,
        source: str = "feedback",
        booking_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Analyze sentiment and store result"""
        # Analyze text
        analysis = self.sentiment_analyzer.analyze(text, source)

        # Store sentiment log
        sentiment_log = SentimentLog(
            guest_id=guest_id,
            booking_id=booking_id,
            source=source,
            original_text=text[:1000] if text else None,
            sentiment_score=analysis["sentiment_score"],
            sentiment_label=analysis["sentiment_label"],
            primary_emotion=analysis["primary_emotion"],
            emotion_scores=json.dumps(analysis["emotion_scores"]),
            emotion_intensity=analysis["emotion_intensity"],
            triggers=json.dumps(analysis["triggers"]),
            confidence=analysis["confidence"],
            occurred_at=datetime.utcnow(),
        )
        session.add(sentiment_log)
        await session.commit()

        # Check if recovery needed
        if analysis["sentiment_score"] < -0.4:
            await self._trigger_recovery_check(
                session, guest_id, booking_id, analysis
            )

        return {
            "guest_id": guest_id,
            "analysis": analysis,
            "recovery_triggered": analysis["sentiment_score"] < -0.4,
            "logged_at": datetime.utcnow().isoformat(),
        }

    async def get_sentiment_timeline(
        self,
        session: AsyncSession,
        guest_id: int,
        days: int = 90
    ) -> Dict[str, Any]:
        """Get sentiment history for a guest"""
        since_date = datetime.utcnow() - timedelta(days=days)

        result = await session.exec(
            select(SentimentLog)
            .where(
                and_(
                    SentimentLog.guest_id == guest_id,
                    SentimentLog.created_at >= since_date
                )
            )
            .order_by(SentimentLog.created_at.desc())
        )
        logs = result.all()

        # Calculate trend
        analyses = [{"sentiment_score": log.sentiment_score} for log in logs]
        trend = self.sentiment_analyzer.get_sentiment_trend(analyses)

        return {
            "guest_id": guest_id,
            "period_days": days,
            "total_entries": len(logs),
            "trend": trend,
            "timeline": [
                {
                    "date": log.created_at.isoformat(),
                    "source": log.source,
                    "sentiment_score": log.sentiment_score,
                    "sentiment_label": log.sentiment_label,
                    "emotion": log.primary_emotion,
                }
                for log in logs[:20]  # Limit to recent 20
            ],
            "by_source": self._aggregate_by_source(logs),
        }

    async def get_at_risk_guests(
        self,
        session: AsyncSession,
        limit: int = 50,
        min_churn_risk: int = 60
    ) -> List[Dict[str, Any]]:
        """Get list of at-risk guests requiring attention"""
        # Get recent high-risk alerts
        result = await session.exec(
            select(AIAlert)
            .where(
                and_(
                    AIAlert.alert_type == "churn_risk",
                    AIAlert.status == "open",
                    AIAlert.priority.in_(["high", "critical"])
                )
            )
            .order_by(AIAlert.created_at.desc())
            .limit(limit)
        )
        alerts = result.all()

        at_risk_guests = []
        for alert in alerts:
            guest = await session.get(Guest, alert.guest_id)
            if guest:
                at_risk_guests.append({
                    "guest_id": alert.guest_id,
                    "guest_name": f"{guest.first_name} {guest.last_name}",
                    "email": guest.email,
                    "priority": alert.priority,
                    "churn_probability": alert.trigger_value,
                    "alert_message": alert.message,
                    "days_since_alert": (datetime.utcnow() - alert.created_at).days,
                    "vip_status": guest.vip_status,
                })

        return at_risk_guests

    async def get_recovery_opportunities(
        self,
        session: AsyncSession,
        status: str = "detected",
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get service recovery opportunities"""
        result = await session.exec(
            select(RecoveryLog)
            .where(RecoveryLog.status == status)
            .order_by(RecoveryLog.severity_score.desc())
            .limit(limit)
        )
        logs = result.all()

        opportunities = []
        for log in logs:
            guest = await session.get(Guest, log.guest_id)
            opportunities.append({
                "recovery_id": log.id,
                "guest_id": log.guest_id,
                "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
                "issue_type": log.issue_type,
                "issue_description": log.issue_description,
                "severity": log.severity_score,
                "recommended_actions": json.loads(log.recommended_actions) if log.recommended_actions else [],
                "detected_at": log.detected_at.isoformat(),
                "status": log.status,
            })

        return opportunities

    async def get_campaign_recommendations(
        self,
        session: AsyncSession,
        campaign_type: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get campaign recommendations for guest segments"""
        # Get all guests with scores
        all_features = await FeatureStore.get_all_guests_features(session, limit=limit)

        recommendations = {
            "win_back": [],
            "loyalty": [],
            "upsell": [],
            "direct_booking": [],
        }

        for features in all_features:
            guest_id = features.get("guest_id")

            # Calculate scores
            health = self.health_model.calculate(features)
            churn = self.churn_model.predict(features)
            ltv = self.ltv_model.predict(features)
            rebooking = self.rebooking_model.predict(features)

            guest_scores = {
                "health_score": health["health_score"],
                "churn_probability": churn["churn_probability"],
                "predicted_ltv": ltv["predicted_ltv"],
                "rebooking_probability": rebooking["rebooking_probability"],
            }

            campaign_rec = self.campaign_optimizer.recommend_campaign(features, guest_scores)
            rec_type = campaign_rec["recommended_campaign"]["type"]

            if rec_type in recommendations:
                recommendations[rec_type].append({
                    "guest_id": guest_id,
                    "guest_name": features.get("guest_name"),
                    "priority": campaign_rec["recommended_campaign"]["priority"],
                    "channel": campaign_rec["channel_recommendation"]["primary_channel"],
                    "predicted_conversion": campaign_rec["predicted_metrics"]["conversion_rate"],
                    "ltv": ltv["predicted_ltv"],
                })

        # Sort each category by priority and LTV
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for key in recommendations:
            recommendations[key].sort(
                key=lambda x: (priority_order.get(x["priority"], 4), -x["ltv"])
            )
            recommendations[key] = recommendations[key][:20]  # Top 20 per category

        # Filter by type if specified
        if campaign_type and campaign_type in recommendations:
            return {campaign_type: recommendations[campaign_type]}

        return recommendations

    async def get_dashboard_stats(
        self,
        session: AsyncSession
    ) -> Dict[str, Any]:
        """Get CRM AI dashboard statistics"""
        # Get guest counts by health score
        total_guests = await session.exec(
            select(func.count(Guest.id)).where(Guest.status != "Inactive")
        )
        total_count = total_guests.one() or 0

        # Get recent AI scores
        recent_scores = await session.exec(
            select(AIScore)
            .where(AIScore.score_type == "health_score")
            .order_by(AIScore.calculated_at.desc())
            .limit(100)
        )
        scores = recent_scores.all()

        # Calculate health distribution
        health_distribution = {"excellent": 0, "good": 0, "fair": 0, "at_risk": 0, "critical": 0}
        for score in scores:
            label = score.score_label.lower() if score.score_label else "fair"
            if label in health_distribution:
                health_distribution[label] += 1

        # Get open alerts
        open_alerts = await session.exec(
            select(func.count(AIAlert.id)).where(AIAlert.status == "open")
        )
        alert_count = open_alerts.one() or 0

        # Get recovery pending
        recovery_pending = await session.exec(
            select(func.count(RecoveryLog.id)).where(RecoveryLog.status == "detected")
        )
        recovery_count = recovery_pending.one() or 0

        # Calculate averages
        avg_health = sum(s.score_value for s in scores) / len(scores) if scores else 50
        churn_scores = [s for s in scores if s.score_type == "churn_probability"]
        avg_churn = sum(s.score_value for s in churn_scores) / len(churn_scores) if churn_scores else 30

        return {
            "total_guests": total_count,
            "guests_analyzed": len(scores),
            "health_distribution": health_distribution,
            "average_health_score": round(avg_health, 1),
            "average_churn_risk": round(avg_churn, 1),
            "open_alerts": alert_count,
            "recovery_pending": recovery_count,
            "last_updated": datetime.utcnow().isoformat(),
        }

    # Private helper methods

    async def _store_ai_scores(
        self,
        session: AsyncSession,
        guest_id: int,
        health: Dict,
        churn: Dict,
        ltv: Dict,
        rebooking: Dict
    ):
        """Store AI scores in database"""
        now = datetime.utcnow()

        scores = [
            AIScore(
                guest_id=guest_id,
                score_type="health_score",
                score_value=health["health_score"],
                score_label=health["score_label"],
                model_version=health["model_version"],
                feature_values=json.dumps(health["components"]),
                explanation=health["explanation"]["summary"],
                calculated_at=now,
            ),
            AIScore(
                guest_id=guest_id,
                score_type="churn_probability",
                score_value=churn["churn_probability"],
                score_label=churn["churn_risk"],
                model_version=churn["model_version"],
                feature_values=json.dumps(churn["churn_drivers"]),
                explanation=churn["explanation"]["summary"],
                calculated_at=now,
            ),
            AIScore(
                guest_id=guest_id,
                score_type="ltv",
                score_value=ltv["predicted_ltv"],
                score_label=ltv["ltv_segment"],
                model_version=ltv["model_version"],
                feature_values=json.dumps(ltv["components"]),
                explanation=ltv["explanation"]["summary"],
                confidence=ltv["confidence"],
                calculated_at=now,
            ),
            AIScore(
                guest_id=guest_id,
                score_type="rebooking_probability",
                score_value=rebooking["rebooking_probability"],
                score_label=rebooking["probability_label"],
                model_version=rebooking["model_version"],
                feature_values=json.dumps(rebooking["factors"]),
                explanation=rebooking["explanation"]["summary"],
                calculated_at=now,
            ),
        ]

        for score in scores:
            session.add(score)
        await session.commit()

    async def _check_and_create_alerts(
        self,
        session: AsyncSession,
        guest_id: int,
        churn: Dict,
        health: Dict
    ) -> List[Dict]:
        """Check thresholds and create alerts if needed"""
        alerts = []

        # Check churn risk
        if churn["is_high_risk"]:
            # Check if alert already exists
            existing = await session.exec(
                select(AIAlert)
                .where(
                    and_(
                        AIAlert.guest_id == guest_id,
                        AIAlert.alert_type == "churn_risk",
                        AIAlert.status == "open"
                    )
                )
            )
            if not existing.first():
                priority = "critical" if churn["churn_probability"] >= 80 else "high"
                alert = AIAlert(
                    guest_id=guest_id,
                    alert_type="churn_risk",
                    priority=priority,
                    title=f"High Churn Risk: {churn['churn_probability']:.0f}%",
                    message=churn["explanation"]["summary"],
                    trigger_value=churn["churn_probability"],
                    threshold=self.churn_model.churn_threshold,
                    extra_data=json.dumps({
                        "drivers": churn["churn_drivers"],
                        "actions": churn["explanation"]["mitigation_actions"],
                    }),
                )
                session.add(alert)
                await session.commit()
                alerts.append({
                    "type": "churn_risk",
                    "priority": priority,
                    "message": alert.message,
                })

        return alerts

    async def _trigger_recovery_check(
        self,
        session: AsyncSession,
        guest_id: int,
        booking_id: Optional[int],
        sentiment_analysis: Dict
    ):
        """Create recovery log for negative sentiment"""
        recovery = RecoveryLog(
            guest_id=guest_id,
            booking_id=booking_id,
            issue_type="sentiment_drop",
            issue_description=sentiment_analysis["analysis_summary"],
            severity_score=abs(sentiment_analysis["sentiment_score"]),
            detected_method="ai",
            recommended_actions=json.dumps([
                "Review recent guest interactions",
                "Proactive outreach to understand concerns",
                "Consider service recovery offer",
            ]),
            guest_satisfaction_before=sentiment_analysis["sentiment_score"],
        )
        session.add(recovery)
        await session.commit()

    async def _get_score_history(
        self,
        session: AsyncSession,
        guest_id: int,
        days: int = 90
    ) -> Dict[str, List]:
        """Get score history for a guest"""
        since_date = datetime.utcnow() - timedelta(days=days)

        result = await session.exec(
            select(AIScore)
            .where(
                and_(
                    AIScore.guest_id == guest_id,
                    AIScore.calculated_at >= since_date
                )
            )
            .order_by(AIScore.calculated_at.desc())
        )
        scores = result.all()

        history = {"health_score": [], "churn_probability": [], "ltv": [], "rebooking_probability": []}

        for score in scores:
            if score.score_type in history:
                history[score.score_type].append({
                    "value": score.score_value,
                    "date": score.calculated_at.isoformat(),
                })

        return history

    def _generate_key_insights(
        self,
        health: Dict,
        churn: Dict,
        ltv: Dict,
        rebooking: Dict
    ) -> List[str]:
        """Generate key insights from all scores"""
        insights = []

        # Health insight
        if health["health_score"] >= 80:
            insights.append(f"Excellent guest health ({health['health_score']:.0f}/100) - prioritize for loyalty programs")
        elif health["health_score"] < 50:
            insights.append(f"Guest health needs attention ({health['health_score']:.0f}/100) - review engagement strategy")

        # Churn insight
        if churn["is_high_risk"]:
            main_driver = churn["churn_drivers"][0]["factor"] if churn["churn_drivers"] else "Unknown"
            insights.append(f"High churn risk ({churn['churn_probability']:.0f}%) - primary concern: {main_driver}")

        # LTV insight
        if ltv["ltv_segment"] == "high_value":
            insights.append(f"High-value guest (${ltv['predicted_ltv']:,.0f} LTV) - VIP treatment recommended")

        # Rebooking insight
        if rebooking["rebooking_probability"] >= 70:
            insights.append(f"High rebooking likelihood ({rebooking['rebooking_probability']:.0f}%) - optimal time to reach out")
        elif rebooking["rebooking_probability"] < 30:
            insights.append(f"Low rebooking probability ({rebooking['rebooking_probability']:.0f}%) - win-back campaign needed")

        return insights[:4]

    def _get_top_actions(
        self,
        churn: Dict,
        rebooking: Dict,
        ltv: Dict
    ) -> List[Dict[str, str]]:
        """Get prioritized recommended actions"""
        actions = []

        # Add churn mitigation actions
        if churn["is_high_risk"]:
            for action in churn["explanation"]["mitigation_actions"][:2]:
                actions.append({"action": action, "priority": "high", "category": "retention"})

        # Add rebooking actions
        contact_rec = rebooking["optimal_contact"]["recommendation"]
        actions.append({"action": contact_rec, "priority": "medium", "category": "engagement"})

        # Add LTV actions
        for rec in ltv["recommendations"][:1]:
            actions.append({"action": rec, "priority": "medium", "category": "value"})

        return actions[:5]

    def _aggregate_by_source(self, logs: List) -> Dict[str, Dict]:
        """Aggregate sentiment by source"""
        by_source = {}
        for log in logs:
            source = log.source
            if source not in by_source:
                by_source[source] = {"count": 0, "total_score": 0}
            by_source[source]["count"] += 1
            by_source[source]["total_score"] += log.sentiment_score

        for source in by_source:
            count = by_source[source]["count"]
            by_source[source]["average_score"] = round(
                by_source[source]["total_score"] / count, 2
            ) if count > 0 else 0

        return by_source


# Singleton instance
reconnect_ai = ReConnectAIService()
