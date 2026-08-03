"""
Advanced Analytics Service
Provides AI-powered insights, predictions, and natural language BI capabilities
"""
import os
import json
import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal

from sqlalchemy import text, func
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import dotenv_values

# LangChain imports with fallback
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of metrics available"""
    REVENUE = "revenue"
    OCCUPANCY = "occupancy"
    ADR = "adr"
    REVPAR = "revpar"
    BOOKINGS = "bookings"
    GUESTS = "guests"
    HOUSEKEEPING = "housekeeping"
    MAINTENANCE = "maintenance"
    SATISFACTION = "satisfaction"


class TrendDirection(str, Enum):
    """Trend direction indicators"""
    UP = "up"
    DOWN = "down"
    STABLE = "stable"


class AlertSeverity(str, Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Insight:
    """AI-generated insight"""
    title: str
    description: str
    metric: str
    value: Any
    trend: TrendDirection
    change_percent: float
    severity: AlertSeverity = AlertSeverity.INFO
    recommendations: List[str] = field(default_factory=list)


@dataclass
class Prediction:
    """Predictive analytics result"""
    metric: str
    forecast_date: date
    predicted_value: float
    confidence_low: float
    confidence_high: float
    confidence_level: float  # 0-1


@dataclass
class Anomaly:
    """Detected anomaly"""
    metric: str
    detected_at: datetime
    expected_value: float
    actual_value: float
    deviation_percent: float
    severity: AlertSeverity
    description: str


@dataclass
class AnalyticsSession:
    """Conversational analytics session"""
    session_id: str
    user_id: int
    context: Dict[str, Any]
    history: List[Dict[str, str]]
    created_at: datetime
    last_active: datetime


class AdvancedAnalyticsService:
    """Service for advanced analytics, AI insights, and natural language BI"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.llm = None
        self._init_llm()
        self._sessions: Dict[str, AnalyticsSession] = {}

    def _init_llm(self):
        """Initialize the LLM for natural language processing"""
        if not LANGCHAIN_AVAILABLE:
            logger.warning("LangChain not available, AI features will be limited")
            return

        try:
            env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
            env_values = dotenv_values(env_path)
            api_key = env_values.get('OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY')

            if api_key:
                self.llm = ChatOpenAI(
                    model="gpt-4o-mini",
                    temperature=0.1,
                    api_key=api_key
                )
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")

    # ==================== KPI Dashboard ====================

    async def get_kpi_dashboard(self, date_range: str = "today") -> Dict[str, Any]:
        """Get comprehensive KPI dashboard data"""
        start_date, end_date = self._parse_date_range(date_range)
        prev_start, prev_end = self._get_previous_period(start_date, end_date)

        kpis = await self._calculate_all_kpis(start_date, end_date, prev_start, prev_end)
        insights = await self._generate_insights(kpis)
        anomalies = await self._detect_anomalies(kpis)

        return {
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "kpis": kpis,
            "insights": [self._insight_to_dict(i) for i in insights],
            "anomalies": [self._anomaly_to_dict(a) for a in anomalies],
            "generated_at": datetime.now().isoformat()
        }

    async def _calculate_all_kpis(
        self, start_date: date, end_date: date,
        prev_start: date, prev_end: date
    ) -> Dict[str, Any]:
        """Calculate all KPIs for the dashboard"""

        # Current period metrics
        revenue = await self._get_revenue(start_date, end_date)
        prev_revenue = await self._get_revenue(prev_start, prev_end)

        occupancy = await self._get_occupancy(start_date, end_date)
        prev_occupancy = await self._get_occupancy(prev_start, prev_end)

        bookings = await self._get_booking_count(start_date, end_date)
        prev_bookings = await self._get_booking_count(prev_start, prev_end)

        guests = await self._get_guest_count(start_date, end_date)
        prev_guests = await self._get_guest_count(prev_start, prev_end)

        adr = await self._get_adr(start_date, end_date)
        prev_adr = await self._get_adr(prev_start, prev_end)

        revpar = await self._get_revpar(start_date, end_date)
        prev_revpar = await self._get_revpar(prev_start, prev_end)

        return {
            "revenue": {
                "value": revenue,
                "previous": prev_revenue,
                "change": self._calc_change(revenue, prev_revenue),
                "trend": self._get_trend(revenue, prev_revenue)
            },
            "occupancy": {
                "value": occupancy,
                "previous": prev_occupancy,
                "change": self._calc_change(occupancy, prev_occupancy),
                "trend": self._get_trend(occupancy, prev_occupancy)
            },
            "bookings": {
                "value": bookings,
                "previous": prev_bookings,
                "change": self._calc_change(bookings, prev_bookings),
                "trend": self._get_trend(bookings, prev_bookings)
            },
            "guests": {
                "value": guests,
                "previous": prev_guests,
                "change": self._calc_change(guests, prev_guests),
                "trend": self._get_trend(guests, prev_guests)
            },
            "adr": {
                "value": adr,
                "previous": prev_adr,
                "change": self._calc_change(adr, prev_adr),
                "trend": self._get_trend(adr, prev_adr)
            },
            "revpar": {
                "value": revpar,
                "previous": prev_revpar,
                "change": self._calc_change(revpar, prev_revpar),
                "trend": self._get_trend(revpar, prev_revpar)
            }
        }

    # ==================== Natural Language BI ====================

    async def query_natural_language(
        self, query: str, session_id: Optional[str] = None, user_id: int = 0
    ) -> Dict[str, Any]:
        """Process natural language analytics query"""

        # Get or create session for context retention
        session = self._get_or_create_session(session_id, user_id)

        # Parse the query to understand intent
        parsed = await self._parse_query(query, session.context)

        # Execute the appropriate data retrieval
        data = await self._execute_analytics_query(parsed)

        # Generate natural language response
        response = await self._generate_response(query, data, session.context)

        # Suggest visualizations
        viz_suggestions = self._suggest_visualizations(parsed, data)

        # Update session context
        session.history.append({"role": "user", "content": query})
        session.history.append({"role": "assistant", "content": response})
        session.context.update(parsed.get("context_updates", {}))
        session.last_active = datetime.now()

        return {
            "response": response,
            "data": data,
            "visualization": viz_suggestions,
            "session_id": session.session_id,
            "parsed_query": parsed,
            "follow_up_suggestions": self._get_follow_up_suggestions(parsed)
        }

    async def _parse_query(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Parse natural language query to extract metrics, dates, and filters"""

        query_lower = query.lower()
        parsed = {
            "metrics": [],
            "date_range": "today",
            "filters": {},
            "aggregation": "total",
            "comparison": None,
            "context_updates": {}
        }

        # Extract metrics
        metric_keywords = {
            "revenue": ["revenue", "income", "earnings", "sales", "money"],
            "occupancy": ["occupancy", "occupied", "vacancy", "available", "empty"],
            "bookings": ["booking", "reservation", "booked"],
            "guests": ["guest", "customer", "visitor"],
            "adr": ["adr", "average daily rate", "average rate"],
            "revpar": ["revpar", "revenue per available room"],
            "housekeeping": ["housekeeping", "cleaning", "hk"],
            "maintenance": ["maintenance", "repairs", "issues"]
        }

        for metric, keywords in metric_keywords.items():
            if any(kw in query_lower for kw in keywords):
                parsed["metrics"].append(metric)

        # Extract date ranges
        if "today" in query_lower:
            parsed["date_range"] = "today"
        elif "yesterday" in query_lower:
            parsed["date_range"] = "yesterday"
        elif "this week" in query_lower:
            parsed["date_range"] = "this_week"
        elif "last week" in query_lower:
            parsed["date_range"] = "last_week"
        elif "this month" in query_lower:
            parsed["date_range"] = "this_month"
        elif "last month" in query_lower:
            parsed["date_range"] = "last_month"
        elif "ytd" in query_lower or "year to date" in query_lower:
            parsed["date_range"] = "ytd"
        elif "last 7 days" in query_lower:
            parsed["date_range"] = "last_7_days"
        elif "last 30 days" in query_lower:
            parsed["date_range"] = "last_30_days"

        # Extract comparison requests
        if "compare" in query_lower or "vs" in query_lower or "versus" in query_lower:
            parsed["comparison"] = "previous_period"

        # Extract aggregation
        if "by day" in query_lower or "daily" in query_lower:
            parsed["aggregation"] = "daily"
        elif "by week" in query_lower or "weekly" in query_lower:
            parsed["aggregation"] = "weekly"
        elif "by month" in query_lower or "monthly" in query_lower:
            parsed["aggregation"] = "monthly"

        # Use context for follow-up queries
        if not parsed["metrics"] and "last_metrics" in context:
            parsed["metrics"] = context["last_metrics"]

        # Update context
        if parsed["metrics"]:
            parsed["context_updates"]["last_metrics"] = parsed["metrics"]
        parsed["context_updates"]["last_date_range"] = parsed["date_range"]

        return parsed

    async def _execute_analytics_query(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the analytics query based on parsed parameters"""

        start_date, end_date = self._parse_date_range(parsed["date_range"])
        results = {}

        for metric in parsed.get("metrics", ["revenue", "occupancy", "bookings"]):
            if metric == "revenue":
                results["revenue"] = await self._get_revenue_breakdown(start_date, end_date, parsed["aggregation"])
            elif metric == "occupancy":
                results["occupancy"] = await self._get_occupancy_breakdown(start_date, end_date, parsed["aggregation"])
            elif metric == "bookings":
                results["bookings"] = await self._get_bookings_breakdown(start_date, end_date, parsed["aggregation"])
            elif metric == "guests":
                results["guests"] = await self._get_guests_breakdown(start_date, end_date)
            elif metric == "adr":
                results["adr"] = await self._get_adr(start_date, end_date)
            elif metric == "revpar":
                results["revpar"] = await self._get_revpar(start_date, end_date)
            elif metric == "housekeeping":
                results["housekeeping"] = await self._get_housekeeping_stats(start_date, end_date)
            elif metric == "maintenance":
                results["maintenance"] = await self._get_maintenance_stats(start_date, end_date)

        # Add comparison if requested
        if parsed.get("comparison"):
            prev_start, prev_end = self._get_previous_period(start_date, end_date)
            results["comparison"] = {
                "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
                "data": {}
            }
            for metric in parsed.get("metrics", []):
                if metric == "revenue":
                    results["comparison"]["data"]["revenue"] = await self._get_revenue(prev_start, prev_end)
                elif metric == "occupancy":
                    results["comparison"]["data"]["occupancy"] = await self._get_occupancy(prev_start, prev_end)

        results["period"] = {"start": start_date.isoformat(), "end": end_date.isoformat()}
        return results

    async def _generate_response(
        self, query: str, data: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """Generate natural language response from data"""

        if not self.llm:
            return self._generate_simple_response(data)

        try:
            system_prompt = """You are a hotel analytics assistant. Provide clear, concise insights
            about hotel performance metrics. Use the data provided to answer questions accurately.
            Format numbers appropriately (currency for revenue, percentages for rates).
            Keep responses brief but informative. Highlight trends and actionable insights."""

            data_context = json.dumps(data, default=str, indent=2)
            user_prompt = f"""Query: {query}

Data:
{data_context}

Provide a clear, conversational response based on this data."""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]

            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM response generation failed: {e}")
            return self._generate_simple_response(data)

    def _generate_simple_response(self, data: Dict[str, Any]) -> str:
        """Generate a simple response without LLM"""
        parts = []

        period = data.get("period", {})
        if period:
            parts.append(f"For the period {period.get('start')} to {period.get('end')}:")

        for key, value in data.items():
            if key == "period":
                continue
            if isinstance(value, dict) and "value" in value:
                parts.append(f"- {key.title()}: {value['value']}")
            elif isinstance(value, (int, float)):
                parts.append(f"- {key.title()}: {value}")

        return "\n".join(parts) if parts else "No data available for the specified query."

    # ==================== Predictive Analytics ====================

    async def get_predictions(
        self, metric: str, days_ahead: int = 30
    ) -> List[Dict[str, Any]]:
        """Generate predictions for a metric"""

        predictions = []
        today = date.today()

        # Get historical data for trend analysis
        historical = await self._get_historical_data(metric, days=90)

        if not historical:
            return []

        # Simple linear regression for predictions
        avg_daily_change = self._calculate_trend(historical)
        last_value = historical[-1]["value"] if historical else 0

        for i in range(1, days_ahead + 1):
            forecast_date = today + timedelta(days=i)
            predicted = last_value + (avg_daily_change * i)

            # Add some variance for confidence intervals
            variance = abs(predicted * 0.1)  # 10% variance

            predictions.append({
                "date": forecast_date.isoformat(),
                "predicted_value": round(max(0, predicted), 2),
                "confidence_low": round(max(0, predicted - variance), 2),
                "confidence_high": round(predicted + variance, 2),
                "confidence_level": 0.85 if i <= 7 else 0.70 if i <= 14 else 0.55
            })

        return predictions

    async def get_demand_forecast(self, days_ahead: int = 90) -> Dict[str, Any]:
        """Generate demand forecast with occupancy predictions"""

        occupancy_predictions = await self.get_predictions("occupancy", days_ahead)
        revenue_predictions = await self.get_predictions("revenue", days_ahead)

        # Identify high and low demand periods
        high_demand = [p for p in occupancy_predictions if p["predicted_value"] > 80]
        low_demand = [p for p in occupancy_predictions if p["predicted_value"] < 50]

        return {
            "occupancy_forecast": occupancy_predictions,
            "revenue_forecast": revenue_predictions,
            "high_demand_periods": high_demand[:10],  # Top 10
            "low_demand_periods": low_demand[:10],
            "recommendations": await self._generate_demand_recommendations(
                high_demand, low_demand
            )
        }

    async def run_scenario_analysis(
        self, scenario: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run what-if scenario analysis"""

        scenario_type = scenario.get("type", "rate_change")
        change_percent = scenario.get("change_percent", 0)

        # Get baseline metrics
        baseline = await self._calculate_all_kpis(
            date.today() - timedelta(days=30),
            date.today(),
            date.today() - timedelta(days=60),
            date.today() - timedelta(days=30)
        )

        impact = {}

        if scenario_type == "rate_change":
            # Model impact of rate changes on revenue and occupancy
            elasticity = -0.5  # Price elasticity of demand
            occupancy_change = change_percent * elasticity
            revenue_change = change_percent + occupancy_change

            impact = {
                "occupancy": {
                    "baseline": baseline["occupancy"]["value"],
                    "projected": baseline["occupancy"]["value"] * (1 + occupancy_change/100),
                    "change_percent": occupancy_change
                },
                "revenue": {
                    "baseline": baseline["revenue"]["value"],
                    "projected": baseline["revenue"]["value"] * (1 + revenue_change/100),
                    "change_percent": revenue_change
                }
            }
        elif scenario_type == "staffing_change":
            # Model impact of staffing changes
            current_staff = await self._get_staff_count()
            new_staff = current_staff * (1 + change_percent/100)

            # More staff = better service = higher satisfaction
            satisfaction_change = change_percent * 0.3

            impact = {
                "staff_count": {
                    "baseline": current_staff,
                    "projected": int(new_staff)
                },
                "satisfaction": {
                    "baseline": 4.2,
                    "projected": min(5.0, 4.2 * (1 + satisfaction_change/100)),
                    "change_percent": satisfaction_change
                }
            }

        return {
            "scenario": scenario,
            "baseline_period": "last_30_days",
            "impact": impact,
            "confidence": "medium",
            "assumptions": self._get_scenario_assumptions(scenario_type)
        }

    # ==================== Anomaly Detection ====================

    async def detect_anomalies(self, lookback_days: int = 30) -> List[Dict[str, Any]]:
        """Detect anomalies in key metrics"""

        anomalies = []
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)

        metrics_to_check = ["revenue", "occupancy", "bookings"]

        for metric in metrics_to_check:
            historical = await self._get_historical_data(metric, days=lookback_days)
            if not historical:
                continue

            values = [h["value"] for h in historical]
            mean = sum(values) / len(values) if values else 0
            std = (sum((x - mean) ** 2 for x in values) / len(values)) ** 0.5 if values else 0

            # Check for anomalies (values beyond 2 standard deviations)
            for data_point in historical[-7:]:  # Last 7 days
                if std > 0:
                    z_score = abs(data_point["value"] - mean) / std
                    if z_score > 2:
                        severity = AlertSeverity.CRITICAL if z_score > 3 else AlertSeverity.WARNING
                        anomalies.append({
                            "metric": metric,
                            "date": data_point["date"],
                            "expected_value": round(mean, 2),
                            "actual_value": data_point["value"],
                            "deviation_percent": round((data_point["value"] - mean) / mean * 100, 2) if mean else 0,
                            "severity": severity.value,
                            "description": f"Unusual {metric} detected on {data_point['date']}"
                        })

        return sorted(anomalies, key=lambda x: x.get("severity", ""), reverse=True)

    # ==================== AI Report Builder ====================

    async def generate_report(
        self, report_type: str, options: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Generate AI-powered report"""

        options = options or {}
        start_date, end_date = self._parse_date_range(options.get("date_range", "this_month"))

        if report_type == "daily_operations":
            return await self._generate_daily_ops_report(start_date, end_date)
        elif report_type == "revenue_analysis":
            return await self._generate_revenue_report(start_date, end_date)
        elif report_type == "housekeeping_efficiency":
            return await self._generate_housekeeping_report(start_date, end_date)
        elif report_type == "guest_analytics":
            return await self._generate_guest_report(start_date, end_date)
        elif report_type == "executive_summary":
            return await self._generate_executive_summary(start_date, end_date)
        else:
            raise ValueError(f"Unknown report type: {report_type}")

    async def _generate_daily_ops_report(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Generate daily operations report"""

        arrivals = await self._get_arrivals(end_date)
        departures = await self._get_departures(end_date)
        occupancy = await self._get_occupancy(start_date, end_date)
        revenue = await self._get_revenue(start_date, end_date)
        housekeeping = await self._get_housekeeping_stats(start_date, end_date)
        maintenance = await self._get_maintenance_stats(start_date, end_date)

        report = {
            "report_type": "daily_operations",
            "generated_at": datetime.now().isoformat(),
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "sections": {
                "arrivals_departures": {
                    "arrivals": arrivals,
                    "departures": departures
                },
                "occupancy": {
                    "rate": occupancy,
                    "rooms_available": await self._get_available_rooms()
                },
                "revenue": {
                    "total": revenue,
                    "breakdown": await self._get_revenue_breakdown(start_date, end_date, "total")
                },
                "housekeeping": housekeeping,
                "maintenance": maintenance
            },
            "highlights": [],
            "action_items": []
        }

        # Generate AI highlights
        if self.llm:
            report["highlights"] = await self._generate_report_highlights(report)

        return report

    async def _generate_revenue_report(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Generate revenue analysis report"""

        revenue = await self._get_revenue_breakdown(start_date, end_date, "daily")
        adr = await self._get_adr(start_date, end_date)
        revpar = await self._get_revpar(start_date, end_date)

        # Get previous period for comparison
        prev_start, prev_end = self._get_previous_period(start_date, end_date)
        prev_revenue = await self._get_revenue(prev_start, prev_end)
        current_revenue = await self._get_revenue(start_date, end_date)

        return {
            "report_type": "revenue_analysis",
            "generated_at": datetime.now().isoformat(),
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "metrics": {
                "total_revenue": current_revenue,
                "previous_period_revenue": prev_revenue,
                "change_percent": self._calc_change(current_revenue, prev_revenue),
                "adr": adr,
                "revpar": revpar
            },
            "breakdown": revenue,
            "trends": await self._analyze_revenue_trends(start_date, end_date),
            "recommendations": await self._get_revenue_recommendations(
                current_revenue, prev_revenue, adr, revpar
            )
        }

    async def _generate_executive_summary(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Generate executive summary report"""

        prev_start, prev_end = self._get_previous_period(start_date, end_date)
        kpis = await self._calculate_all_kpis(start_date, end_date, prev_start, prev_end)
        insights = await self._generate_insights(kpis)
        predictions = await self.get_predictions("revenue", days_ahead=30)

        return {
            "report_type": "executive_summary",
            "generated_at": datetime.now().isoformat(),
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "kpis": kpis,
            "key_insights": [self._insight_to_dict(i) for i in insights[:5]],
            "outlook": {
                "next_30_days": predictions[:30] if predictions else [],
                "trend": "positive" if kpis["revenue"]["trend"] == "up" else "cautious"
            },
            "strategic_recommendations": await self._get_strategic_recommendations(kpis)
        }

    # ==================== Helper Methods ====================

    def _parse_date_range(self, date_range: str) -> Tuple[date, date]:
        """
        Parse date range string to start and end dates.

        Supported values:
        - today, yesterday
        - this_week, last_week, week (alias for this_week)
        - this_month, last_month, month (alias for this_month)
        - year, ytd (year to date)
        - last_7_days, last_30_days, last_90_days, last_365_days

        Raises ValueError if date_range is not supported.
        """
        today = date.today()

        ranges = {
            # Day ranges
            "today": (today, today),
            "yesterday": (today - timedelta(days=1), today - timedelta(days=1)),

            # Week ranges
            "this_week": (today - timedelta(days=today.weekday()), today),
            "last_week": (today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday() + 1)),
            "week": (today - timedelta(days=today.weekday()), today),  # Alias for this_week

            # Month ranges
            "this_month": (today.replace(day=1), today),
            "last_month": (
                (today.replace(day=1) - timedelta(days=1)).replace(day=1),
                today.replace(day=1) - timedelta(days=1)
            ),
            "month": (today.replace(day=1), today),  # Alias for this_month

            # Year ranges
            "year": (today.replace(month=1, day=1), today),  # Year to date
            "ytd": (today.replace(month=1, day=1), today),
            "last_year": (
                today.replace(year=today.year - 1, month=1, day=1),
                today.replace(year=today.year - 1, month=12, day=31)
            ),

            # Rolling periods
            "last_7_days": (today - timedelta(days=7), today),
            "last_30_days": (today - timedelta(days=30), today),
            "last_90_days": (today - timedelta(days=90), today),
            "last_365_days": (today - timedelta(days=365), today),
        }

        if date_range not in ranges:
            supported = ", ".join(sorted(ranges.keys()))
            raise ValueError(
                f"Invalid date_range '{date_range}'. "
                f"Supported values: {supported}"
            )

        return ranges[date_range]

    def _get_previous_period(self, start_date: date, end_date: date) -> Tuple[date, date]:
        """Get the previous period for comparison"""
        period_length = (end_date - start_date).days + 1
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_length - 1)
        return prev_start, prev_end

    def _calc_change(self, current: float, previous: float) -> float:
        """Calculate percentage change"""
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round((current - previous) / previous * 100, 2)

    def _get_trend(self, current: float, previous: float) -> str:
        """Determine trend direction"""
        change = self._calc_change(current, previous)
        if change > 2:
            return "up"
        elif change < -2:
            return "down"
        return "stable"

    def _calculate_trend(self, historical: List[Dict]) -> float:
        """Calculate average daily change from historical data"""
        if len(historical) < 2:
            return 0

        changes = []
        for i in range(1, len(historical)):
            changes.append(historical[i]["value"] - historical[i-1]["value"])

        return sum(changes) / len(changes) if changes else 0

    def _get_or_create_session(self, session_id: Optional[str], user_id: int) -> AnalyticsSession:
        """Get or create an analytics session"""
        import uuid

        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.last_active = datetime.now()
            return session

        new_session_id = session_id or str(uuid.uuid4())
        session = AnalyticsSession(
            session_id=new_session_id,
            user_id=user_id,
            context={},
            history=[],
            created_at=datetime.now(),
            last_active=datetime.now()
        )
        self._sessions[new_session_id] = session
        return session

    def _suggest_visualizations(self, parsed: Dict, data: Dict) -> Dict[str, Any]:
        """Suggest appropriate visualizations for the data"""
        suggestions = []

        aggregation = parsed.get("aggregation", "total")
        metrics = parsed.get("metrics", [])

        if aggregation in ["daily", "weekly", "monthly"]:
            suggestions.append({
                "type": "line_chart",
                "title": "Trend Over Time",
                "description": "View how metrics change over the selected period"
            })

        if len(metrics) > 1:
            suggestions.append({
                "type": "bar_chart",
                "title": "Metric Comparison",
                "description": "Compare different metrics side by side"
            })

        if "occupancy" in metrics:
            suggestions.append({
                "type": "gauge",
                "title": "Occupancy Rate",
                "description": "Current occupancy as a percentage"
            })

        if "revenue" in metrics:
            suggestions.append({
                "type": "pie_chart",
                "title": "Revenue Breakdown",
                "description": "Revenue distribution by category"
            })

        return {
            "suggested": suggestions[0] if suggestions else None,
            "alternatives": suggestions[1:] if len(suggestions) > 1 else []
        }

    def _get_follow_up_suggestions(self, parsed: Dict) -> List[str]:
        """Generate follow-up query suggestions"""
        suggestions = []
        metrics = parsed.get("metrics", [])

        if "revenue" in metrics:
            suggestions.extend([
                "Break this down by room type",
                "Compare with last month",
                "Show daily trend"
            ])
        if "occupancy" in metrics:
            suggestions.extend([
                "What's the forecast for next week?",
                "Which room types are most booked?"
            ])
        if "bookings" in metrics:
            suggestions.extend([
                "Show booking sources",
                "What's the average lead time?"
            ])

        return suggestions[:4]

    def _insight_to_dict(self, insight: Insight) -> Dict[str, Any]:
        """Convert Insight to dictionary"""
        return {
            "title": insight.title,
            "description": insight.description,
            "metric": insight.metric,
            "value": insight.value,
            "trend": insight.trend.value,
            "change_percent": insight.change_percent,
            "severity": insight.severity.value,
            "recommendations": insight.recommendations
        }

    def _anomaly_to_dict(self, anomaly: Anomaly) -> Dict[str, Any]:
        """Convert Anomaly to dictionary"""
        return {
            "metric": anomaly.metric,
            "detected_at": anomaly.detected_at.isoformat(),
            "expected_value": anomaly.expected_value,
            "actual_value": anomaly.actual_value,
            "deviation_percent": anomaly.deviation_percent,
            "severity": anomaly.severity.value,
            "description": anomaly.description
        }

    def _get_scenario_assumptions(self, scenario_type: str) -> List[str]:
        """Get assumptions for scenario analysis"""
        assumptions = {
            "rate_change": [
                "Price elasticity of demand is -0.5",
                "No competitor rate changes",
                "Demand remains consistent"
            ],
            "staffing_change": [
                "Linear relationship between staff and service quality",
                "Current staff utilization at 85%",
                "Training period of 2 weeks for new staff"
            ]
        }
        return assumptions.get(scenario_type, [])

    # ==================== Data Retrieval Methods ====================

    async def _get_revenue(self, start_date: date, end_date: date) -> float:
        """Get total revenue for period"""
        try:
            result = await self.session.execute(text("""
                SELECT COALESCE(SUM(total_price), 0) as revenue
                FROM bookings
                WHERE DATE(created_at) >= :start_date
                AND DATE(created_at) <= :end_date
                AND status NOT IN ('cancelled')
            """), {"start_date": start_date, "end_date": end_date})
            row = result.fetchone()
            return float(row[0]) if row else 0.0
        except Exception as e:
            logger.error(f"Error getting revenue: {e}")
            return 0.0

    async def _get_revenue_breakdown(
        self, start_date: date, end_date: date, aggregation: str
    ) -> Dict[str, Any]:
        """Get revenue breakdown"""
        try:
            if aggregation == "daily":
                result = await self.session.execute(text("""
                    SELECT DATE(created_at) as date, SUM(total_price) as revenue
                    FROM bookings
                    WHERE DATE(created_at) >= :start_date
                    AND DATE(created_at) <= :end_date
                    AND status NOT IN ('cancelled')
                    GROUP BY DATE(created_at)
                    ORDER BY date
                """), {"start_date": start_date, "end_date": end_date})
                rows = result.fetchall()
                return {
                    "data": [{"date": str(r[0]), "value": float(r[1])} for r in rows],
                    "total": sum(float(r[1]) for r in rows)
                }
            else:
                total = await self._get_revenue(start_date, end_date)
                return {"total": total}
        except Exception as e:
            logger.error(f"Error getting revenue breakdown: {e}")
            return {"total": 0}

    async def _get_occupancy(self, start_date: date, end_date: date) -> float:
        """Get occupancy rate for period"""
        try:
            # Get total rooms
            rooms_result = await self.session.execute(text("""
                SELECT COUNT(*) FROM rooms WHERE status != 'out_of_order'
            """))
            total_rooms = rooms_result.scalar() or 1

            # Get occupied room nights
            result = await self.session.execute(text("""
                SELECT COUNT(DISTINCT r.id) as occupied
                FROM rooms r
                JOIN bookings b ON b.room_id = r.id
                WHERE b.status IN ('checked_in', 'confirmed')
                AND DATE(b.check_in_date) <= :end_date
                AND DATE(b.check_out_date) > :start_date
            """), {"start_date": start_date, "end_date": end_date})
            occupied = result.scalar() or 0

            return round(occupied / total_rooms * 100, 2)
        except Exception as e:
            logger.error(f"Error getting occupancy: {e}")
            return 0.0

    async def _get_occupancy_breakdown(
        self, start_date: date, end_date: date, aggregation: str
    ) -> Dict[str, Any]:
        """Get occupancy breakdown"""
        occupancy = await self._get_occupancy(start_date, end_date)
        return {"rate": occupancy, "aggregation": aggregation}

    async def _get_booking_count(self, start_date: date, end_date: date) -> int:
        """Get booking count for period"""
        try:
            result = await self.session.execute(text("""
                SELECT COUNT(*) FROM bookings
                WHERE DATE(created_at) >= :start_date
                AND DATE(created_at) <= :end_date
            """), {"start_date": start_date, "end_date": end_date})
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting booking count: {e}")
            return 0

    async def _get_bookings_breakdown(
        self, start_date: date, end_date: date, aggregation: str
    ) -> Dict[str, Any]:
        """Get bookings breakdown"""
        count = await self._get_booking_count(start_date, end_date)
        return {"count": count, "aggregation": aggregation}

    async def _get_guest_count(self, start_date: date, end_date: date) -> int:
        """Get guest count for period"""
        try:
            result = await self.session.execute(text("""
                SELECT COUNT(DISTINCT guest_id) FROM bookings
                WHERE DATE(created_at) >= :start_date
                AND DATE(created_at) <= :end_date
            """), {"start_date": start_date, "end_date": end_date})
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting guest count: {e}")
            return 0

    async def _get_guests_breakdown(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Get guests breakdown"""
        count = await self._get_guest_count(start_date, end_date)

        # Get returning vs new guests
        try:
            result = await self.session.execute(text("""
                SELECT
                    COUNT(CASE WHEN total_bookings > 1 THEN 1 END) as returning,
                    COUNT(CASE WHEN total_bookings = 1 THEN 1 END) as new
                FROM (
                    SELECT guest_id, COUNT(*) as total_bookings
                    FROM bookings
                    WHERE DATE(created_at) >= :start_date
                    AND DATE(created_at) <= :end_date
                    GROUP BY guest_id
                ) sub
            """), {"start_date": start_date, "end_date": end_date})
            row = result.fetchone()
            return {
                "total": count,
                "returning": row[0] if row else 0,
                "new": row[1] if row else count
            }
        except Exception as e:
            logger.error(f"Error getting guests breakdown: {e}")
            return {"total": count}

    async def _get_adr(self, start_date: date, end_date: date) -> float:
        """Get Average Daily Rate"""
        try:
            result = await self.session.execute(text("""
                SELECT AVG(total_price / NULLIF(nights, 0)) as adr
                FROM bookings
                WHERE DATE(created_at) >= :start_date
                AND DATE(created_at) <= :end_date
                AND status NOT IN ('cancelled')
                AND nights > 0
            """), {"start_date": start_date, "end_date": end_date})
            adr = result.scalar()
            return round(float(adr), 2) if adr else 0.0
        except Exception as e:
            logger.error(f"Error getting ADR: {e}")
            return 0.0

    async def _get_revpar(self, start_date: date, end_date: date) -> float:
        """Get Revenue Per Available Room"""
        try:
            revenue = await self._get_revenue(start_date, end_date)

            rooms_result = await self.session.execute(text("""
                SELECT COUNT(*) FROM rooms WHERE status != 'out_of_order'
            """))
            total_rooms = rooms_result.scalar() or 1

            days = (end_date - start_date).days + 1
            available_room_nights = total_rooms * days

            return round(revenue / available_room_nights, 2) if available_room_nights > 0 else 0.0
        except Exception as e:
            logger.error(f"Error getting RevPAR: {e}")
            return 0.0

    async def _get_housekeeping_stats(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Get housekeeping statistics"""
        try:
            result = await self.session.execute(text("""
                SELECT
                    COUNT(*) as total_tasks,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                    COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as in_progress
                FROM housekeeping_tasks
                WHERE DATE(created_at) >= :start_date
                AND DATE(created_at) <= :end_date
            """), {"start_date": start_date, "end_date": end_date})
            row = result.fetchone()

            if row:
                return {
                    "total_tasks": row[0] or 0,
                    "completed": row[1] or 0,
                    "pending": row[2] or 0,
                    "in_progress": row[3] or 0,
                    "completion_rate": round((row[1] or 0) / row[0] * 100, 2) if row[0] else 0
                }
            return {"total_tasks": 0, "completed": 0, "pending": 0, "in_progress": 0, "completion_rate": 0}
        except Exception as e:
            logger.error(f"Error getting housekeeping stats: {e}")
            return {"total_tasks": 0, "completed": 0, "pending": 0, "in_progress": 0, "completion_rate": 0}

    async def _get_maintenance_stats(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Get maintenance statistics"""
        try:
            result = await self.session.execute(text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                    COUNT(CASE WHEN priority = 'urgent' THEN 1 END) as urgent
                FROM maintenancerequest
                WHERE DATE(created_at) >= :start_date
                AND DATE(created_at) <= :end_date
            """), {"start_date": start_date, "end_date": end_date})
            row = result.fetchone()

            if row:
                return {
                    "total": row[0] or 0,
                    "completed": row[1] or 0,
                    "pending": row[2] or 0,
                    "urgent": row[3] or 0
                }
            return {"total": 0, "completed": 0, "pending": 0, "urgent": 0}
        except Exception as e:
            logger.error(f"Error getting maintenance stats: {e}")
            return {"total": 0, "completed": 0, "pending": 0, "urgent": 0}

    async def _get_arrivals(self, target_date: date) -> int:
        """Get number of arrivals for a date"""
        try:
            result = await self.session.execute(text("""
                SELECT COUNT(*) FROM bookings
                WHERE DATE(check_in_date) = :target_date
                AND status IN ('confirmed', 'checked_in')
            """), {"target_date": target_date})
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting arrivals: {e}")
            return 0

    async def _get_departures(self, target_date: date) -> int:
        """Get number of departures for a date"""
        try:
            result = await self.session.execute(text("""
                SELECT COUNT(*) FROM bookings
                WHERE DATE(check_out_date) = :target_date
                AND status IN ('checked_in', 'checked_out')
            """), {"target_date": target_date})
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting departures: {e}")
            return 0

    async def _get_available_rooms(self) -> int:
        """Get count of available rooms"""
        try:
            result = await self.session.execute(text("""
                SELECT COUNT(*) FROM rooms
                WHERE status = 'available'
            """))
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting available rooms: {e}")
            return 0

    async def _get_staff_count(self) -> int:
        """Get total staff count"""
        try:
            result = await self.session.execute(text("""
                SELECT COUNT(*) FROM users
                WHERE role IN ('housekeeping', 'maintenance', 'frontdesk', 'manager')
                AND is_active = 1
            """))
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error getting staff count: {e}")
            return 0

    async def _get_historical_data(
        self, metric: str, days: int = 90
    ) -> List[Dict[str, Any]]:
        """Get historical data for a metric"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        data = []
        current_date = start_date

        while current_date <= end_date:
            if metric == "revenue":
                value = await self._get_revenue(current_date, current_date)
            elif metric == "occupancy":
                value = await self._get_occupancy(current_date, current_date)
            elif metric == "bookings":
                value = await self._get_booking_count(current_date, current_date)
            else:
                value = 0

            data.append({
                "date": current_date.isoformat(),
                "value": value
            })
            current_date += timedelta(days=1)

        return data

    async def _generate_insights(self, kpis: Dict[str, Any]) -> List[Insight]:
        """Generate insights from KPI data"""
        insights = []

        for metric, data in kpis.items():
            if isinstance(data, dict) and "value" in data:
                trend = TrendDirection(data.get("trend", "stable"))
                change = data.get("change", 0)

                severity = AlertSeverity.INFO
                if abs(change) > 20:
                    severity = AlertSeverity.WARNING
                if abs(change) > 50:
                    severity = AlertSeverity.CRITICAL

                insights.append(Insight(
                    title=f"{metric.upper()} {'Increase' if change > 0 else 'Decrease'}",
                    description=f"{metric.title()} changed by {change:.1f}% compared to previous period",
                    metric=metric,
                    value=data["value"],
                    trend=trend,
                    change_percent=change,
                    severity=severity,
                    recommendations=self._get_metric_recommendations(metric, change, trend)
                ))

        return sorted(insights, key=lambda x: abs(x.change_percent), reverse=True)

    def _get_metric_recommendations(
        self, metric: str, change: float, trend: TrendDirection
    ) -> List[str]:
        """Get recommendations based on metric performance"""
        recommendations = []

        if metric == "revenue" and trend == TrendDirection.DOWN:
            recommendations.extend([
                "Consider running a promotional campaign",
                "Review pricing strategy against competitors",
                "Focus on upselling opportunities"
            ])
        elif metric == "occupancy" and change < -10:
            recommendations.extend([
                "Increase marketing efforts",
                "Consider last-minute deals",
                "Review OTA rankings and visibility"
            ])
        elif metric == "occupancy" and change > 20:
            recommendations.extend([
                "Consider dynamic pricing increases",
                "Ensure adequate staffing levels",
                "Monitor service quality closely"
            ])

        return recommendations[:3]

    async def _detect_anomalies(self, kpis: Dict[str, Any]) -> List[Anomaly]:
        """Detect anomalies in KPI data"""
        anomalies = []

        for metric, data in kpis.items():
            if isinstance(data, dict) and "value" in data:
                change = abs(data.get("change", 0))

                if change > 30:  # Significant deviation
                    severity = AlertSeverity.CRITICAL if change > 50 else AlertSeverity.WARNING
                    anomalies.append(Anomaly(
                        metric=metric,
                        detected_at=datetime.now(),
                        expected_value=data.get("previous", 0),
                        actual_value=data.get("value", 0),
                        deviation_percent=change,
                        severity=severity,
                        description=f"Unusual {metric} detected - {change:.1f}% deviation from expected"
                    ))

        return anomalies

    async def _analyze_revenue_trends(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Analyze revenue trends"""
        historical = await self._get_historical_data("revenue", days=30)

        if len(historical) < 7:
            return {"trend": "insufficient_data"}

        recent = sum(h["value"] for h in historical[-7:]) / 7
        previous = sum(h["value"] for h in historical[-14:-7]) / 7

        trend = "up" if recent > previous else "down" if recent < previous else "stable"

        return {
            "trend": trend,
            "recent_average": round(recent, 2),
            "previous_average": round(previous, 2),
            "change_percent": self._calc_change(recent, previous)
        }

    async def _get_revenue_recommendations(
        self, current: float, previous: float, adr: float, revpar: float
    ) -> List[str]:
        """Get revenue-specific recommendations"""
        recommendations = []
        change = self._calc_change(current, previous)

        if change < -10:
            recommendations.append("Implement targeted promotions for low-demand periods")
        if adr < revpar * 1.2:
            recommendations.append("Consider rate optimization to improve ADR")
        if change > 20:
            recommendations.append("Capitalize on high demand with dynamic pricing")

        return recommendations

    async def _generate_demand_recommendations(
        self, high_demand: List[Dict], low_demand: List[Dict]
    ) -> List[str]:
        """Generate demand-based recommendations"""
        recommendations = []

        if high_demand:
            recommendations.append(f"High demand expected on {len(high_demand)} days - consider rate increases")
        if low_demand:
            recommendations.append(f"Low demand expected on {len(low_demand)} days - plan promotions")

        return recommendations

    async def _get_strategic_recommendations(
        self, kpis: Dict[str, Any]
    ) -> List[str]:
        """Get strategic recommendations based on KPIs"""
        recommendations = []

        revenue_trend = kpis.get("revenue", {}).get("trend", "stable")
        occupancy_trend = kpis.get("occupancy", {}).get("trend", "stable")

        if revenue_trend == "down" and occupancy_trend == "down":
            recommendations.append("Focus on demand generation through marketing and partnerships")
        elif revenue_trend == "down" and occupancy_trend == "up":
            recommendations.append("Revenue leakage detected - review pricing and upselling")
        elif revenue_trend == "up" and occupancy_trend == "up":
            recommendations.append("Strong performance - maintain momentum and invest in guest experience")

        return recommendations

    async def _generate_report_highlights(self, report: Dict[str, Any]) -> List[str]:
        """Generate AI-powered report highlights"""
        if not self.llm:
            return []

        try:
            prompt = f"""Based on this hotel operations report data, provide 3-5 key highlights:
            {json.dumps(report['sections'], default=str)}

            Format as a simple list of observations."""

            messages = [
                SystemMessage(content="You are a hotel operations analyst. Provide concise, actionable insights."),
                HumanMessage(content=prompt)
            ]

            response = await self.llm.ainvoke(messages)
            highlights = response.content.strip().split('\n')
            return [h.strip('- ').strip() for h in highlights if h.strip()][:5]
        except Exception as e:
            logger.error(f"Error generating highlights: {e}")
            return []

    async def _generate_housekeeping_report(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Generate housekeeping efficiency report"""
        stats = await self._get_housekeeping_stats(start_date, end_date)

        return {
            "report_type": "housekeeping_efficiency",
            "generated_at": datetime.now().isoformat(),
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "metrics": stats,
            "efficiency_score": stats.get("completion_rate", 0),
            "recommendations": [
                "Optimize room assignment based on staff location" if stats.get("completion_rate", 0) < 90 else "Maintain current efficiency levels"
            ]
        }

    async def _generate_guest_report(
        self, start_date: date, end_date: date
    ) -> Dict[str, Any]:
        """Generate guest analytics report"""
        guests = await self._get_guests_breakdown(start_date, end_date)

        return {
            "report_type": "guest_analytics",
            "generated_at": datetime.now().isoformat(),
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "metrics": guests,
            "retention_rate": round(guests.get("returning", 0) / guests.get("total", 1) * 100, 2) if guests.get("total", 0) > 0 else 0,
            "insights": [
                f"{guests.get('returning', 0)} returning guests ({round(guests.get('returning', 0) / guests.get('total', 1) * 100, 1)}%)" if guests.get("total", 0) > 0 else "No guest data available"
            ]
        }
