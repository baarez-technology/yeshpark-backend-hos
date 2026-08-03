"""
Recommendation Engine
Combines AI insights with ML predictions to generate intelligent pricing,
revenue optimization recommendations, and alerts.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

import numpy as np

from app.services.ai_service import AIService, get_ai_service
from app.services.ml_forecast_service import MLForecastService, get_ml_forecast_service

logger = logging.getLogger(__name__)


class RecommendationType(str, Enum):
    """Types of recommendations."""
    PRICING = "pricing"
    REVENUE_OPPORTUNITY = "revenue_opportunity"
    CHANNEL = "channel"
    PROMOTION = "promotion"
    COMPETITIVE = "competitive"
    ALERT = "alert"


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Types of alerts."""
    DEMAND = "demand"
    RATE_PARITY = "rate_parity"
    COMPETITOR = "competitor"
    OCCUPANCY = "occupancy"
    REVENUE = "revenue"
    FORECAST = "forecast"
    ANOMALY = "anomaly"


@dataclass
class PricingRecommendation:
    """A pricing recommendation."""
    date: str
    room_type_id: int
    room_type_name: str
    current_rate: float
    recommended_rate: float
    change_percent: float
    demand_level: str
    forecasted_occupancy: float
    competitor_avg: float
    confidence: float
    reasoning: str
    priority: str
    ai_enhanced: bool = False


@dataclass
class RevenueOpportunity:
    """A revenue optimization opportunity."""
    id: str
    type: str
    title: str
    description: str
    revenue_impact: float
    priority: str
    action: str
    confidence: float
    due_date: Optional[str] = None
    ai_generated: bool = False


@dataclass
class Alert:
    """A revenue alert."""
    id: str
    type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    date: Optional[str]
    created_at: str
    data: Optional[Dict[str, Any]] = None
    ai_generated: bool = False


class RecommendationEngine:
    """
    Intelligent recommendation engine that combines AI analysis
    with ML predictions for revenue optimization.
    """

    def __init__(
        self,
        ai_service: Optional[AIService] = None,
        ml_service: Optional[MLForecastService] = None,
        total_rooms: int = 70
    ):
        """
        Initialize the recommendation engine.

        Args:
            ai_service: AI service for natural language insights
            ml_service: ML service for forecasting
            total_rooms: Total number of hotel rooms
        """
        self.ai = ai_service or get_ai_service()
        self.ml = ml_service or get_ml_forecast_service(total_rooms)
        self.total_rooms = total_rooms
        logger.info("RecommendationEngine initialized")

    async def generate_pricing_recommendations(
        self,
        room_types: List[Dict[str, Any]],
        forecast: List[Dict[str, Any]],
        competitor_rates: List[Dict[str, Any]],
        current_rates: Dict[str, float],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate AI-powered pricing recommendations.

        OPTIMIZED: Generate all base recommendations first, then batch-enhance
        only high-priority recommendations with a single AI call to prevent
        excessive API calls (was: 60+ calls, now: 1-2 calls max).

        Args:
            room_types: List of room type configurations
            forecast: Demand forecast data
            competitor_rates: Competitor rate data
            current_rates: Current rates by room type
            start_date: Start of recommendation period
            end_date: End of recommendation period

        Returns:
            List of pricing recommendations
        """
        if start_date is None:
            start_date = date.today()
        if end_date is None:
            end_date = date.today() + timedelta(days=30)

        # Index forecast by date for quick lookup
        forecast_by_date = {f['date']: f for f in forecast}

        # Index competitor rates by date
        competitor_by_date = self._aggregate_competitor_rates(competitor_rates)

        recommendations = []

        # PHASE 1: Generate all base recommendations WITHOUT AI calls
        for room_type in room_types:
            room_type_id = room_type.get('id', 0)
            room_type_name = room_type.get('name', 'Unknown')
            base_rate = current_rates.get(str(room_type_id), room_type.get('base_price', 150))

            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.isoformat()
                forecast_data = forecast_by_date.get(date_str, {})
                comp_data = competitor_by_date.get(date_str, {})

                # Get forecast values
                demand_level = forecast_data.get('demand_level', 'moderate')
                occupancy = forecast_data.get('forecasted_occupancy', 70)
                confidence = forecast_data.get('confidence_level', 75)

                # Get competitor average
                comp_avg = comp_data.get('avg_rate', base_rate)

                # Calculate base recommendation using ML/rules only
                recommended_rate = self._calculate_recommended_rate(
                    base_rate=base_rate,
                    demand_level=demand_level,
                    occupancy=occupancy,
                    competitor_avg=comp_avg,
                    days_out=(current_date - date.today()).days,
                    day_of_week=current_date.weekday()
                )

                # Generate basic reasoning (no AI)
                reasoning = self._generate_basic_reasoning(demand_level, occupancy, comp_avg, base_rate)

                change_percent = ((recommended_rate - base_rate) / base_rate * 100) if base_rate > 0 else 0
                priority = self._determine_priority(change_percent, (current_date - date.today()).days)

                recommendation = {
                    'date': date_str,
                    'room_type_id': room_type_id,
                    'room_type_name': room_type_name,
                    'current_rate': round(base_rate, 2),
                    'recommended_rate': round(recommended_rate, 2),
                    'change_percent': round(change_percent, 1),
                    'demand_level': demand_level,
                    'forecasted_occupancy': round(occupancy, 1),
                    'competitor_avg': round(comp_avg, 2),
                    'confidence': round(confidence, 1),
                    'reasoning': reasoning,
                    'priority': priority,
                    'ai_enhanced': False,
                    'day_of_week': current_date.strftime('%A'),
                    'is_weekend': current_date.weekday() >= 5
                }

                recommendations.append(recommendation)
                current_date += timedelta(days=1)

        # PHASE 2: Batch-enhance only high-priority recommendations with single AI call
        if self.ai.is_available():
            await self._batch_enhance_recommendations(recommendations)

        # Sort by priority and date
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        recommendations.sort(key=lambda x: (priority_order.get(x['priority'], 4), x['date']))

        return recommendations

    async def _batch_enhance_recommendations(self, recommendations: List[Dict[str, Any]]) -> None:
        """
        Batch-enhance high-priority recommendations with a SINGLE AI call.
        This prevents excessive API calls (60+ reduced to 1-2 calls).

        Modifies recommendations in-place.
        """
        # Filter high-priority recommendations for AI enhancement
        high_priority = [r for r in recommendations if r['priority'] in ('critical', 'high')]

        if not high_priority:
            logger.info("No high-priority recommendations to enhance with AI")
            return

        # Limit to top 10 most critical for batch processing
        to_enhance = high_priority[:10]

        try:
            # Build batch context for single AI call
            batch_context = {
                'count': len(to_enhance),
                'recommendations': [
                    {
                        'date': r['date'],
                        'room_type': r['room_type_name'],
                        'current_rate': r['current_rate'],
                        'ml_recommended_rate': r['recommended_rate'],
                        'demand_level': r['demand_level'],
                        'occupancy': r['forecasted_occupancy'],
                        'competitor_avg': r['competitor_avg'],
                        'change_percent': r['change_percent'],
                        'priority': r['priority']
                    }
                    for r in to_enhance
                ]
            }

            # Single AI call for batch enhancement
            ai_result = await self.ai.generate_batch_pricing_insights(batch_context)

            if isinstance(ai_result, dict) and 'enhanced_recommendations' in ai_result:
                enhanced = ai_result['enhanced_recommendations']

                # Map AI enhancements back to recommendations
                for i, rec in enumerate(to_enhance):
                    if i < len(enhanced):
                        enhancement = enhanced[i]
                        if isinstance(enhancement, dict):
                            # Blend AI rate with ML rate
                            if 'recommended_rate' in enhancement:
                                ai_rate = enhancement['recommended_rate']
                                rec['recommended_rate'] = round((rec['recommended_rate'] + ai_rate) / 2, 2)
                                rec['change_percent'] = round(
                                    ((rec['recommended_rate'] - rec['current_rate']) / rec['current_rate'] * 100)
                                    if rec['current_rate'] > 0 else 0, 1
                                )
                            if 'reasoning' in enhancement:
                                rec['reasoning'] = enhancement['reasoning']
                            if 'confidence' in enhancement:
                                rec['confidence'] = enhancement['confidence']
                            rec['ai_enhanced'] = True

                logger.info(f"Batch-enhanced {len(enhanced)} recommendations with AI")
            else:
                logger.warning("AI batch enhancement returned unexpected format")

        except Exception as e:
            logger.warning(f"AI batch enhancement failed, using ML recommendations: {e}")

    def _calculate_recommended_rate(
        self,
        base_rate: float,
        demand_level: str,
        occupancy: float,
        competitor_avg: float,
        days_out: int,
        day_of_week: int
    ) -> float:
        """Calculate recommended rate using ML-based factors."""
        # Demand multiplier
        demand_multipliers = {
            'critical': 1.35,
            'high': 1.20,
            'moderate': 1.05,
            'low': 0.90,
            'very_low': 0.80
        }
        demand_factor = demand_multipliers.get(demand_level, 1.0)

        # Day of week multiplier
        dow_multipliers = {
            0: 0.95,  # Monday
            1: 0.95,  # Tuesday
            2: 1.00,  # Wednesday
            3: 1.00,  # Thursday
            4: 1.10,  # Friday
            5: 1.15,  # Saturday
            6: 1.05   # Sunday
        }
        dow_factor = dow_multipliers.get(day_of_week, 1.0)

        # Lead time multiplier
        if days_out <= 1:
            lead_time_factor = 1.15  # Last minute premium
        elif days_out <= 7:
            lead_time_factor = 1.10
        elif days_out <= 14:
            lead_time_factor = 1.05
        elif days_out <= 30:
            lead_time_factor = 1.0
        else:
            lead_time_factor = 0.95  # Early bird discount

        # Calculate initial recommended rate
        recommended_rate = base_rate * demand_factor * dow_factor * lead_time_factor

        # Competitive adjustment
        if competitor_avg > 0:
            rate_index = recommended_rate / competitor_avg
            if rate_index < 0.85:
                # We're too cheap, raise toward market
                recommended_rate = competitor_avg * 0.92
            elif rate_index > 1.2:
                # We're too expensive, lower toward market
                recommended_rate = competitor_avg * 1.12

        return recommended_rate

    def _generate_basic_reasoning(
        self,
        demand_level: str,
        occupancy: float,
        competitor_avg: float,
        current_rate: float
    ) -> str:
        """Generate basic reasoning for pricing recommendation."""
        reasons = []

        if demand_level in ['critical', 'high']:
            reasons.append(f"High demand forecasted ({demand_level})")
        elif demand_level in ['low', 'very_low']:
            reasons.append(f"Low demand expected ({demand_level})")

        if current_rate < competitor_avg * 0.9:
            reasons.append(f"Currently underpriced vs market (${current_rate:.0f} vs ${competitor_avg:.0f})")
        elif current_rate > competitor_avg * 1.1:
            reasons.append(f"Above market rate (${current_rate:.0f} vs ${competitor_avg:.0f})")

        if occupancy > 85:
            reasons.append("High occupancy opportunity")
        elif occupancy < 50:
            reasons.append("Low occupancy - consider rate reduction")

        return "; ".join(reasons) if reasons else "Standard rate optimization"

    def _determine_priority(self, change_percent: float, days_out: int) -> str:
        """Determine recommendation priority."""
        abs_change = abs(change_percent)

        if days_out <= 3 and abs_change > 10:
            return "critical"
        elif days_out <= 7 or abs_change > 15:
            return "high"
        elif abs_change > 5:
            return "medium"
        else:
            return "low"

    def _aggregate_competitor_rates(self, competitor_rates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Aggregate competitor rates by date."""
        by_date = {}
        for comp in competitor_rates:
            d = comp.get('date')
            if d:
                if isinstance(d, date):
                    d = d.isoformat()
                if d not in by_date:
                    by_date[d] = {'rates': [], 'avg_rate': 0}
                rate = comp.get('rate', comp.get('price', 0))
                if rate:
                    by_date[d]['rates'].append(float(rate))

        for d, data in by_date.items():
            if data['rates']:
                data['avg_rate'] = np.mean(data['rates'])

        return by_date

    async def identify_revenue_opportunities(
        self,
        kpis: Dict[str, Any],
        forecast: List[Dict[str, Any]],
        channel_data: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Identify revenue optimization opportunities.

        Args:
            kpis: Current KPI metrics
            forecast: Demand forecast data
            channel_data: Channel performance data

        Returns:
            List of revenue opportunities
        """
        opportunities = []
        today = date.today()

        # 1. High demand pricing opportunities
        high_demand_days = [f for f in forecast[:30] if f.get('demand_level') in ['high', 'critical']]
        for i, f in enumerate(high_demand_days[:5]):
            opportunities.append({
                'id': f"demand_pricing_{i}",
                'type': 'demand_pricing',
                'title': f"High Demand Pricing - {f['date']}",
                'description': f"Forecasted {f.get('forecasted_occupancy', 80):.0f}% occupancy with {f.get('demand_level')} demand. Consider rate increase of 15-25%.",
                'revenue_impact': round(1500 * (f.get('forecasted_occupancy', 80) / 100), 2),
                'priority': 'high' if f.get('demand_level') == 'critical' else 'medium',
                'action': 'Increase rates for this date',
                'confidence': f.get('confidence_level', 75),
                'due_date': f['date'],
                'ai_generated': False
            })

        # 2. Low demand promotional opportunities
        low_demand_days = [f for f in forecast[:30] if f.get('demand_level') in ['low', 'very_low']]
        if low_demand_days:
            # Group consecutive low demand days
            avg_low_occupancy = np.mean([f.get('forecasted_occupancy', 40) for f in low_demand_days])
            opportunities.append({
                'id': 'promotion_opportunity',
                'type': 'promotion',
                'title': f'Promotional Opportunity - {len(low_demand_days)} Low Demand Days',
                'description': f'Average {avg_low_occupancy:.0f}% occupancy forecasted for {len(low_demand_days)} days. Launch targeted promotion.',
                'revenue_impact': round(800 * len(low_demand_days) * (1 - avg_low_occupancy / 100), 2),
                'priority': 'medium',
                'action': 'Create promotional offer targeting these dates',
                'confidence': 70,
                'ai_generated': False
            })

        # 3. Upsell opportunity based on occupancy
        occupancy = kpis.get('occupancy', 70)
        if occupancy > 70:
            opportunities.append({
                'id': 'upsell_campaign',
                'type': 'upsell',
                'title': 'Room Upgrade Campaign',
                'description': 'Good occupancy levels create upsell opportunity. Offer suite upgrades at check-in.',
                'revenue_impact': round(2500 * (occupancy / 100), 2),
                'priority': 'medium',
                'action': 'Enable automatic upgrade offers for confirmed bookings',
                'confidence': 75,
                'ai_generated': False
            })

        # 4. Channel optimization
        if channel_data:
            direct_channel = next((c for c in channel_data if c.get('channel', '').lower() == 'direct'), None)
            ota_revenue = sum(c.get('total_revenue', 0) for c in channel_data if c.get('channel', '').lower() != 'direct')
            direct_revenue = direct_channel.get('total_revenue', 0) if direct_channel else 0

            if ota_revenue > direct_revenue * 1.5:
                commission_savings = ota_revenue * 0.15 * 0.1  # 10% shift saves 15% commission
                opportunities.append({
                    'id': 'channel_shift',
                    'type': 'channel_optimization',
                    'title': 'Increase Direct Bookings',
                    'description': f'OTA revenue (${ota_revenue:,.0f}) significantly exceeds direct (${direct_revenue:,.0f}). 10% shift could save ${commission_savings:,.0f} in commissions.',
                    'revenue_impact': round(commission_savings, 2),
                    'priority': 'high',
                    'action': 'Launch direct booking incentive campaign',
                    'confidence': 80,
                    'ai_generated': False
                })

        # 5. ADR improvement opportunity
        adr = kpis.get('adr', 0)
        adr_trend = kpis.get('adr_trend', 0)
        if adr_trend < -5:
            opportunities.append({
                'id': 'adr_improvement',
                'type': 'pricing',
                'title': 'ADR Improvement Required',
                'description': f'ADR declined by {abs(adr_trend):.1f}% to ${adr:.2f}. Review rate positioning.',
                'revenue_impact': round(adr * self.total_rooms * 0.05, 2),
                'priority': 'high',
                'action': 'Review and optimize rate structure',
                'confidence': 85,
                'ai_generated': False
            })

        # Try to enhance with AI insights
        if self.ai.is_available():
            try:
                ai_insights = await self.ai.generate_revenue_insights(kpis, forecast)
                for insight in ai_insights:
                    if insight.get('type') == 'opportunity':
                        opportunities.append({
                            'id': f"ai_insight_{len(opportunities)}",
                            'type': 'ai_insight',
                            'title': insight.get('title', 'AI Insight'),
                            'description': insight.get('description', ''),
                            'revenue_impact': insight.get('revenue_impact', 1000),
                            'priority': insight.get('priority', 'medium'),
                            'action': 'Review AI recommendation',
                            'confidence': 75,
                            'ai_generated': True
                        })
            except Exception as e:
                logger.warning(f"Failed to get AI insights: {e}")

        # Sort by revenue impact
        opportunities.sort(key=lambda x: x.get('revenue_impact', 0), reverse=True)

        return opportunities

    async def generate_alerts(
        self,
        data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate intelligent alerts based on patterns and thresholds.

        Args:
            data: Dictionary containing:
                - kpis: Current KPI metrics
                - forecast: Demand forecast
                - competitor_rates: Competitor rate data
                - historical_data: Historical performance data

        Returns:
            List of alerts
        """
        alerts = []
        now = datetime.now().isoformat()

        kpis = data.get('kpis', {})
        forecast = data.get('forecast', [])
        competitor_rates = data.get('competitor_rates', [])
        historical_data = data.get('historical_data', [])

        # 1. Demand alerts from forecast
        for f in forecast[:7]:  # Next 7 days
            if f.get('demand_level') == 'critical':
                alerts.append({
                    'id': f"demand_critical_{f['date']}",
                    'type': AlertType.DEMAND.value,
                    'severity': AlertSeverity.CRITICAL.value,
                    'title': f"Critical Demand Alert - {f['date']}",
                    'message': f"Occupancy forecasted at {f.get('forecasted_occupancy', 90):.0f}%. Immediate rate optimization recommended.",
                    'date': f['date'],
                    'created_at': now,
                    'data': {'occupancy': f.get('forecasted_occupancy'), 'demand_level': 'critical'},
                    'ai_generated': False
                })
            elif f.get('demand_level') == 'very_low':
                alerts.append({
                    'id': f"demand_low_{f['date']}",
                    'type': AlertType.DEMAND.value,
                    'severity': AlertSeverity.WARNING.value,
                    'title': f"Low Demand Warning - {f['date']}",
                    'message': f"Occupancy forecasted at only {f.get('forecasted_occupancy', 30):.0f}%. Consider promotional offers.",
                    'date': f['date'],
                    'created_at': now,
                    'data': {'occupancy': f.get('forecasted_occupancy'), 'demand_level': 'very_low'},
                    'ai_generated': False
                })

        # 2. Occupancy alerts
        occupancy = kpis.get('occupancy', 70)
        occupancy_trend = kpis.get('occupancy_trend', 0)

        if occupancy < 40:
            alerts.append({
                'id': 'low_occupancy_alert',
                'type': AlertType.OCCUPANCY.value,
                'severity': AlertSeverity.WARNING.value,
                'title': 'Low Occupancy Alert',
                'message': f'Current occupancy at {occupancy:.1f}% is below target. Consider promotional strategies.',
                'date': date.today().isoformat(),
                'created_at': now,
                'ai_generated': False
            })
        elif occupancy > 95:
            alerts.append({
                'id': 'high_occupancy_alert',
                'type': AlertType.OCCUPANCY.value,
                'severity': AlertSeverity.INFO.value,
                'title': 'High Occupancy Opportunity',
                'message': f'Occupancy at {occupancy:.1f}%. Maximize rates for remaining inventory.',
                'date': date.today().isoformat(),
                'created_at': now,
                'ai_generated': False
            })

        # 3. Revenue trend alerts
        revenue_trend = kpis.get('revenue_trend', 0)
        if revenue_trend < -15:
            alerts.append({
                'id': 'revenue_decline_alert',
                'type': AlertType.REVENUE.value,
                'severity': AlertSeverity.CRITICAL.value,
                'title': 'Significant Revenue Decline',
                'message': f'Revenue down {abs(revenue_trend):.1f}% vs previous period. Urgent review recommended.',
                'date': date.today().isoformat(),
                'created_at': now,
                'ai_generated': False
            })
        elif revenue_trend < -5:
            alerts.append({
                'id': 'revenue_warning_alert',
                'type': AlertType.REVENUE.value,
                'severity': AlertSeverity.WARNING.value,
                'title': 'Revenue Decline Warning',
                'message': f'Revenue down {abs(revenue_trend):.1f}% vs previous period. Monitor closely.',
                'date': date.today().isoformat(),
                'created_at': now,
                'ai_generated': False
            })

        # 4. Competitor rate alerts
        if competitor_rates:
            our_rate = kpis.get('adr', 150)
            comp_avg = np.mean([c.get('rate', 0) for c in competitor_rates if c.get('rate')])

            if comp_avg > 0:
                rate_index = our_rate / comp_avg * 100
                if rate_index < 85:
                    alerts.append({
                        'id': 'rate_too_low_alert',
                        'type': AlertType.COMPETITOR.value,
                        'severity': AlertSeverity.WARNING.value,
                        'title': 'Below Market Rate Alert',
                        'message': f'Your rate (${our_rate:.0f}) is significantly below market average (${comp_avg:.0f}). Potential revenue opportunity.',
                        'date': date.today().isoformat(),
                        'created_at': now,
                        'ai_generated': False
                    })
                elif rate_index > 120:
                    alerts.append({
                        'id': 'rate_too_high_alert',
                        'type': AlertType.COMPETITOR.value,
                        'severity': AlertSeverity.INFO.value,
                        'title': 'Above Market Rate',
                        'message': f'Your rate (${our_rate:.0f}) is above market average (${comp_avg:.0f}). Ensure value proposition supports premium.',
                        'date': date.today().isoformat(),
                        'created_at': now,
                        'ai_generated': False
                    })

        # 5. Anomaly detection alerts
        if historical_data:
            try:
                anomalies = await self.ml.detect_anomalies(historical_data)
                for anomaly in anomalies[:3]:  # Top 3 anomalies
                    alerts.append({
                        'id': f"anomaly_{anomaly['date']}",
                        'type': AlertType.ANOMALY.value,
                        'severity': AlertSeverity.WARNING.value if anomaly.get('severity') == 'high' else AlertSeverity.INFO.value,
                        'title': f"Demand Anomaly Detected - {anomaly['date']}",
                        'message': anomaly.get('description', 'Unusual demand pattern detected'),
                        'date': anomaly['date'],
                        'created_at': now,
                        'data': anomaly,
                        'ai_generated': False
                    })
            except Exception as e:
                logger.warning(f"Anomaly detection failed: {e}")

        # 6. Standard rate parity alert
        alerts.append({
            'id': 'rate_parity_check',
            'type': AlertType.RATE_PARITY.value,
            'severity': AlertSeverity.INFO.value,
            'title': 'Rate Parity Reminder',
            'message': 'Ensure rate parity across all distribution channels. Regular audits recommended.',
            'date': date.today().isoformat(),
            'created_at': now,
            'ai_generated': False
        })

        # Sort by severity
        severity_order = {AlertSeverity.CRITICAL.value: 0, AlertSeverity.WARNING.value: 1, AlertSeverity.INFO.value: 2}
        alerts.sort(key=lambda x: severity_order.get(x.get('severity'), 3))

        return alerts

    async def get_ai_enhanced_insights(
        self,
        kpis: Dict[str, Any],
        forecast: List[Dict[str, Any]],
        competitor_rates: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive AI-enhanced insights.

        Args:
            kpis: Current KPI metrics
            forecast: Demand forecast
            competitor_rates: Competitor rate data

        Returns:
            Dictionary with various AI insights
        """
        insights = {
            'revenue_insights': [],
            'forecast_explanation': '',
            'competitive_analysis': {},
            'recommendations': [],
            'ai_available': self.ai.is_available()
        }

        if self.ai.is_available():
            try:
                # Get revenue insights
                insights['revenue_insights'] = await self.ai.generate_revenue_insights(kpis, forecast)

                # Get forecast explanation
                if forecast:
                    insights['forecast_explanation'] = await self.ai.explain_forecast(forecast)

                # Get competitive analysis
                if competitor_rates:
                    our_rates = {'Standard': kpis.get('adr', 150)}
                    insights['competitive_analysis'] = await self.ai.analyze_competitor_positioning(
                        our_rates, competitor_rates
                    )

            except Exception as e:
                logger.error(f"Failed to generate AI insights: {e}")
                insights['error'] = str(e)
        else:
            # Generate fallback insights
            insights['revenue_insights'] = self.ai._generate_fallback_revenue_insights(kpis, forecast)
            if forecast:
                insights['forecast_explanation'] = self.ai._generate_fallback_forecast_explanation(forecast)

        return insights


# Singleton instance
_recommendation_engine_instance: Optional[RecommendationEngine] = None


def get_recommendation_engine(total_rooms: int = 70) -> RecommendationEngine:
    """Get or create RecommendationEngine singleton instance."""
    global _recommendation_engine_instance
    if _recommendation_engine_instance is None:
        _recommendation_engine_instance = RecommendationEngine(total_rooms=total_rooms)
    return _recommendation_engine_instance
