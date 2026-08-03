"""
AI Service for Revenue Management
Provides OpenAI-powered insights, recommendations, and analysis for hotel revenue optimization.
"""
import os
import json
import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from functools import lru_cache

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# OpenAI imports with fallback
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None

from app.core.config import settings

logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    """Base exception for AI Service errors."""
    pass


class OpenAIConnectionError(AIServiceError):
    """Raised when OpenAI API connection fails."""
    pass


class AIResponseParseError(AIServiceError):
    """Raised when AI response cannot be parsed."""
    pass


class AIService:
    """
    AI Service for revenue management using OpenAI.
    Provides natural language insights, recommendations, and analysis.
    """

    def __init__(self):
        """Initialize OpenAI client."""
        self.api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = settings.openai_model or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
        self.client: Optional[AsyncOpenAI] = None
        self._cache: Dict[str, tuple] = {}  # Simple in-memory cache
        self._cache_ttl = 300  # 5 minutes cache TTL

        # Rate limiting: max 10 calls per minute
        self._rate_limit_calls = 10
        self._rate_limit_window = 60  # seconds
        self._call_timestamps: list = []

        if OPENAI_AVAILABLE and self.api_key:
            try:
                self.client = AsyncOpenAI(api_key=self.api_key)
                logger.info(f"AIService initialized with model: {self.model}")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self.client = None
        else:
            if not OPENAI_AVAILABLE:
                logger.warning("OpenAI library not available. AI features will use fallback.")
            if not self.api_key:
                logger.warning("OpenAI API key not configured. AI features will use fallback.")

    def _get_cache_key(self, method: str, data: Dict[str, Any]) -> str:
        """Generate cache key from method and data."""
        return f"{method}:{hash(json.dumps(data, sort_keys=True, default=str))}"

    def _get_cached(self, cache_key: str) -> Optional[Any]:
        """Get cached result if not expired."""
        if cache_key in self._cache:
            result, timestamp = self._cache[cache_key]
            if datetime.now().timestamp() - timestamp < self._cache_ttl:
                return result
            else:
                del self._cache[cache_key]
        return None

    def _set_cached(self, cache_key: str, result: Any) -> None:
        """Cache result with timestamp."""
        self._cache[cache_key] = (result, datetime.now().timestamp())

    def _check_rate_limit(self) -> bool:
        """
        Check if we're within rate limits.
        Returns True if call is allowed, False if rate limited.
        """
        now = datetime.now().timestamp()
        # Remove timestamps older than the window
        self._call_timestamps = [ts for ts in self._call_timestamps if now - ts < self._rate_limit_window]

        if len(self._call_timestamps) >= self._rate_limit_calls:
            logger.warning(f"Rate limit reached: {len(self._call_timestamps)} calls in last {self._rate_limit_window}s")
            return False

        self._call_timestamps.append(now)
        return True

    async def _call_openai(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        parse_json: bool = True
    ) -> Any:
        """
        Make an async call to OpenAI API with error handling and retries.

        Args:
            prompt: User prompt
            system_prompt: System message defining AI behavior
            temperature: Creativity parameter (0-1)
            max_tokens: Maximum response length
            parse_json: Whether to parse response as JSON

        Returns:
            Parsed response or raw text

        Raises:
            OpenAIConnectionError: If API call fails
            AIResponseParseError: If JSON parsing fails
        """
        if not self.client:
            raise OpenAIConnectionError("OpenAI client not initialized")

        # Check rate limit before making call
        if not self._check_rate_limit():
            raise OpenAIConnectionError("Rate limit exceeded - too many API calls")

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens
                )

                content = response.choices[0].message.content.strip()

                if parse_json:
                    # Try to extract JSON from response
                    try:
                        # Handle markdown code blocks
                        if "```json" in content:
                            content = content.split("```json")[1].split("```")[0].strip()
                        elif "```" in content:
                            content = content.split("```")[1].split("```")[0].strip()
                        return json.loads(content)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON response: {e}")
                        # Return as structured dict if possible
                        return {"raw_response": content}

                return content

            except Exception as e:
                logger.error(f"OpenAI API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                else:
                    raise OpenAIConnectionError(f"OpenAI API call failed after {max_retries} attempts: {e}")

    async def generate_pricing_insight(self, context: dict) -> str:
        """
        Generate natural language pricing recommendation.

        Args:
            context: Dictionary containing:
                - occupancy: Current/forecasted occupancy %
                - demand_level: high/moderate/low
                - competitor_avg: Average competitor rate
                - current_rate: Current rate
                - day: Day of week
                - lead_time: Days until arrival
                - room_type: Room type name

        Returns:
            Natural language pricing recommendation
        """
        cache_key = self._get_cache_key("pricing_insight", context)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        system_prompt = """You are a hotel revenue management AI expert. Analyze the provided data and give a concise, actionable pricing recommendation.
Focus on:
1. Market positioning relative to competitors
2. Demand-based pricing opportunities
3. Lead time optimization
Keep response under 100 words."""

        prompt = f"""Analyze this pricing scenario and provide a recommendation:

Current occupancy: {context.get('occupancy', 70)}%
Forecasted demand: {context.get('demand_level', 'moderate')}
Competitor average rate: ${context.get('competitor_avg', 150):.2f}
Current rate: ${context.get('current_rate', 150):.2f}
Day of week: {context.get('day', 'Monday')}
Days until arrival: {context.get('lead_time', 7)}
Room type: {context.get('room_type', 'Standard')}

Provide a brief pricing recommendation with reasoning."""

        try:
            result = await self._call_openai(prompt, system_prompt, temperature=0.5, parse_json=False)
            self._set_cached(cache_key, result)
            return result
        except (OpenAIConnectionError, AIResponseParseError) as e:
            logger.error(f"Failed to generate pricing insight: {e}")
            return self._generate_fallback_pricing_insight(context)

    def _generate_fallback_pricing_insight(self, context: dict) -> str:
        """Generate fallback pricing insight without AI."""
        occupancy = context.get('occupancy', 70)
        demand_level = context.get('demand_level', 'moderate')
        competitor_avg = context.get('competitor_avg', 150)
        current_rate = context.get('current_rate', 150)
        lead_time = context.get('lead_time', 7)

        if demand_level in ['high', 'critical'] and occupancy > 80:
            action = "increase"
            change = "10-15%"
            reason = "high demand and strong occupancy"
        elif demand_level in ['low', 'very_low'] and occupancy < 50:
            action = "reduce"
            change = "5-10%"
            reason = "low demand to drive bookings"
        elif current_rate < competitor_avg * 0.9:
            action = "increase"
            change = "5%"
            reason = "underpriced vs. market"
        elif current_rate > competitor_avg * 1.1:
            action = "reduce"
            change = "5%"
            reason = "overpriced vs. market"
        else:
            action = "maintain"
            change = "0%"
            reason = "competitive positioning"

        return f"Recommendation: {action.capitalize()} rates by {change} due to {reason}. " \
               f"Current rate (${current_rate:.2f}) vs market avg (${competitor_avg:.2f}). " \
               f"Lead time: {lead_time} days."

    async def generate_revenue_insights(self, kpis: dict, forecast: list) -> list:
        """
        Generate AI insights based on current KPIs and forecast data.

        Args:
            kpis: Current KPI metrics (revenue, occupancy, ADR, RevPAR, trends)
            forecast: List of forecast data points

        Returns:
            List of insight dictionaries with title, description, type, and priority
        """
        cache_key = self._get_cache_key("revenue_insights", {"kpis": kpis, "forecast_len": len(forecast)})
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        system_prompt = """You are a hotel revenue analytics AI. Analyze the KPIs and forecast data to generate actionable insights.
Return a JSON array of exactly 3-5 insights, each with:
{
  "title": "Brief insight title",
  "description": "2-3 sentence explanation with specific numbers",
  "type": "opportunity|warning|trend|recommendation",
  "priority": "high|medium|low",
  "metric": "revenue|occupancy|adr|revpar|forecast"
}"""

        # Summarize forecast for prompt
        if forecast:
            high_demand_days = sum(1 for f in forecast[:30] if f.get('demand_level') in ['high', 'critical'])
            low_demand_days = sum(1 for f in forecast[:30] if f.get('demand_level') in ['low', 'very_low'])
            avg_occupancy = sum(f.get('forecasted_occupancy', 0) for f in forecast[:30]) / max(len(forecast[:30]), 1)
        else:
            high_demand_days = 0
            low_demand_days = 0
            avg_occupancy = 0

        prompt = f"""Analyze these revenue metrics and generate insights:

Current KPIs:
- Total Revenue: ${kpis.get('total_revenue', 0):,.2f} (trend: {kpis.get('revenue_trend', 0):+.1f}%)
- Occupancy: {kpis.get('occupancy', 0):.1f}% (trend: {kpis.get('occupancy_trend', 0):+.1f}pp)
- ADR: ${kpis.get('adr', 0):.2f} (trend: {kpis.get('adr_trend', 0):+.1f}%)
- RevPAR: ${kpis.get('revpar', 0):.2f} (trend: {kpis.get('revpar_trend', 0):+.1f}%)

30-Day Forecast Summary:
- High demand days: {high_demand_days}
- Low demand days: {low_demand_days}
- Average forecasted occupancy: {avg_occupancy:.1f}%

Generate 3-5 actionable insights in JSON array format."""

        try:
            result = await self._call_openai(prompt, system_prompt, temperature=0.6)
            if isinstance(result, list):
                self._set_cached(cache_key, result)
                return result
            elif isinstance(result, dict) and "raw_response" in result:
                return self._generate_fallback_revenue_insights(kpis, forecast)
            return [result] if isinstance(result, dict) else []
        except (OpenAIConnectionError, AIResponseParseError) as e:
            logger.error(f"Failed to generate revenue insights: {e}")
            return self._generate_fallback_revenue_insights(kpis, forecast)

    def _generate_fallback_revenue_insights(self, kpis: dict, forecast: list) -> list:
        """Generate fallback revenue insights without AI."""
        insights = []

        # Revenue trend insight
        revenue_trend = kpis.get('revenue_trend', 0)
        if revenue_trend > 10:
            insights.append({
                "title": "Strong Revenue Growth",
                "description": f"Revenue is up {revenue_trend:.1f}% compared to the previous period. "
                              f"Current total: ${kpis.get('total_revenue', 0):,.2f}. Consider capitalizing on this momentum.",
                "type": "trend",
                "priority": "medium",
                "metric": "revenue"
            })
        elif revenue_trend < -10:
            insights.append({
                "title": "Revenue Decline Alert",
                "description": f"Revenue is down {abs(revenue_trend):.1f}% compared to the previous period. "
                              f"Review pricing strategy and promotional opportunities.",
                "type": "warning",
                "priority": "high",
                "metric": "revenue"
            })

        # Occupancy insight
        occupancy = kpis.get('occupancy', 0)
        if occupancy > 85:
            insights.append({
                "title": "High Occupancy Opportunity",
                "description": f"Occupancy at {occupancy:.1f}% indicates strong demand. "
                              f"Consider rate increases to maximize RevPAR.",
                "type": "opportunity",
                "priority": "high",
                "metric": "occupancy"
            })
        elif occupancy < 50:
            insights.append({
                "title": "Low Occupancy Warning",
                "description": f"Occupancy at {occupancy:.1f}% is below optimal levels. "
                              f"Consider promotional offers or OTA visibility improvements.",
                "type": "warning",
                "priority": "high",
                "metric": "occupancy"
            })

        # ADR insight
        adr = kpis.get('adr', 0)
        adr_trend = kpis.get('adr_trend', 0)
        if adr_trend > 5:
            insights.append({
                "title": "ADR Improvement",
                "description": f"Average Daily Rate improved by {adr_trend:.1f}% to ${adr:.2f}. "
                              f"Pricing strategy is effective.",
                "type": "trend",
                "priority": "medium",
                "metric": "adr"
            })

        # Forecast insight
        if forecast:
            high_demand = [f for f in forecast[:14] if f.get('demand_level') in ['high', 'critical']]
            if len(high_demand) >= 3:
                insights.append({
                    "title": "Upcoming High Demand Period",
                    "description": f"{len(high_demand)} high-demand days in the next 2 weeks. "
                                  f"Optimize rates now to capture maximum revenue.",
                    "type": "opportunity",
                    "priority": "high",
                    "metric": "forecast"
                })

        # Ensure at least one insight
        if not insights:
            insights.append({
                "title": "Performance Summary",
                "description": f"Current occupancy: {occupancy:.1f}%, ADR: ${adr:.2f}, "
                              f"RevPAR: ${kpis.get('revpar', 0):.2f}. Monitor trends for optimization opportunities.",
                "type": "trend",
                "priority": "low",
                "metric": "revenue"
            })

        return insights

    async def analyze_competitor_positioning(self, our_rates: dict, competitor_rates: list) -> dict:
        """
        Analyze competitive position and suggest strategy.

        Args:
            our_rates: Dict of our rates by room type
            competitor_rates: List of competitor rate data

        Returns:
            Analysis with positioning, recommendations, and market share estimate
        """
        cache_key = self._get_cache_key("competitor_analysis", {"our_rates": our_rates, "comp_count": len(competitor_rates)})
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        system_prompt = """You are a hotel competitive intelligence AI. Analyze the rate positioning and provide strategic recommendations.
Return a JSON object with:
{
  "market_position": "premium|mid-market|budget|value",
  "positioning_score": 0-100,
  "avg_competitor_rate": number,
  "rate_index": number (our_rate / competitor_avg * 100),
  "recommendations": ["action 1", "action 2", "action 3"],
  "opportunities": ["opportunity 1", "opportunity 2"],
  "risks": ["risk 1", "risk 2"],
  "summary": "2-3 sentence executive summary"
}"""

        # Calculate competitor averages
        if competitor_rates:
            comp_avg = sum(c.get('rate', 0) for c in competitor_rates) / len(competitor_rates)
            comp_min = min(c.get('rate', 0) for c in competitor_rates)
            comp_max = max(c.get('rate', 0) for c in competitor_rates)
        else:
            comp_avg = comp_min = comp_max = 0

        # Our average rate
        our_avg = sum(our_rates.values()) / len(our_rates) if our_rates else 0

        prompt = f"""Analyze our competitive positioning:

Our Rates by Room Type:
{json.dumps(our_rates, indent=2)}

Our Average Rate: ${our_avg:.2f}

Competitor Data ({len(competitor_rates)} competitors):
- Average Rate: ${comp_avg:.2f}
- Rate Range: ${comp_min:.2f} - ${comp_max:.2f}

Provide competitive analysis in JSON format."""

        try:
            result = await self._call_openai(prompt, system_prompt, temperature=0.5)
            if isinstance(result, dict) and "market_position" in result:
                self._set_cached(cache_key, result)
                return result
            return self._generate_fallback_competitor_analysis(our_rates, competitor_rates)
        except (OpenAIConnectionError, AIResponseParseError) as e:
            logger.error(f"Failed to analyze competitor positioning: {e}")
            return self._generate_fallback_competitor_analysis(our_rates, competitor_rates)

    def _generate_fallback_competitor_analysis(self, our_rates: dict, competitor_rates: list) -> dict:
        """Generate fallback competitor analysis without AI."""
        if competitor_rates:
            comp_avg = sum(c.get('rate', 0) for c in competitor_rates) / len(competitor_rates)
        else:
            comp_avg = 150  # Default assumption

        our_avg = sum(our_rates.values()) / len(our_rates) if our_rates else 150
        rate_index = (our_avg / comp_avg * 100) if comp_avg > 0 else 100

        if rate_index > 110:
            position = "premium"
            score = 75
            recommendations = [
                "Ensure premium amenities justify higher rates",
                "Focus on value-added services",
                "Target high-value guest segments"
            ]
        elif rate_index > 95:
            position = "mid-market"
            score = 65
            recommendations = [
                "Maintain competitive positioning",
                "Monitor competitor rate changes closely",
                "Consider dynamic pricing for demand peaks"
            ]
        else:
            position = "value"
            score = 55
            recommendations = [
                "Evaluate if rates are leaving money on the table",
                "Consider rate increase during high-demand periods",
                "Focus on volume-based strategy"
            ]

        return {
            "market_position": position,
            "positioning_score": score,
            "avg_competitor_rate": round(comp_avg, 2),
            "rate_index": round(rate_index, 1),
            "recommendations": recommendations,
            "opportunities": [
                "Optimize rates during detected demand peaks",
                "Target underserved market segments"
            ],
            "risks": [
                "Competitor rate changes may require adjustment",
                "Market conditions may shift"
            ],
            "summary": f"Currently positioned as {position} with rates {rate_index:.0f}% of market average. "
                       f"Our average rate: ${our_avg:.2f} vs competitor average: ${comp_avg:.2f}."
        }

    async def predict_event_impact(self, event: dict, historical_data: dict) -> dict:
        """
        Predict demand impact of an event.

        Args:
            event: Event details (name, type, date, expected_attendance, location)
            historical_data: Historical demand patterns for similar events

        Returns:
            Impact prediction with demand lift, recommended rate adjustment, and confidence
        """
        system_prompt = """You are a hotel demand forecasting AI. Predict the impact of events on hotel demand.
Return a JSON object with:
{
  "demand_lift_percent": number (expected demand increase %),
  "rate_adjustment_percent": number (recommended rate increase %),
  "peak_days": ["date1", "date2"],
  "impact_duration_days": number,
  "confidence": number (0-100),
  "reasoning": "Brief explanation",
  "recommendations": ["action 1", "action 2"]
}"""

        prompt = f"""Predict the impact of this event on hotel demand:

Event Details:
- Name: {event.get('name', 'Unknown Event')}
- Type: {event.get('type', 'general')}
- Date: {event.get('date', 'TBD')}
- Expected Attendance: {event.get('expected_attendance', 'Unknown')}
- Distance from Hotel: {event.get('distance_km', 'Unknown')} km

Historical Context:
{json.dumps(historical_data, indent=2, default=str)}

Provide demand impact prediction in JSON format."""

        try:
            result = await self._call_openai(prompt, system_prompt, temperature=0.5)
            if isinstance(result, dict) and "demand_lift_percent" in result:
                return result
            return self._generate_fallback_event_impact(event, historical_data)
        except (OpenAIConnectionError, AIResponseParseError) as e:
            logger.error(f"Failed to predict event impact: {e}")
            return self._generate_fallback_event_impact(event, historical_data)

    def _generate_fallback_event_impact(self, event: dict, historical_data: dict) -> dict:
        """Generate fallback event impact prediction without AI."""
        event_type = event.get('type', 'general').lower()
        attendance = event.get('expected_attendance', 1000)

        # Base impact by event type
        type_multipliers = {
            'conference': 1.5,
            'concert': 1.3,
            'sports': 1.4,
            'festival': 1.6,
            'convention': 1.8,
            'trade_show': 1.5,
            'general': 1.2
        }

        base_lift = type_multipliers.get(event_type, 1.2)

        # Adjust by attendance
        if isinstance(attendance, int) and attendance > 5000:
            base_lift *= 1.3
        elif isinstance(attendance, int) and attendance > 1000:
            base_lift *= 1.1

        demand_lift = (base_lift - 1) * 100  # Convert to percentage
        rate_adjustment = demand_lift * 0.7  # Slightly lower than demand lift

        return {
            "demand_lift_percent": round(demand_lift, 1),
            "rate_adjustment_percent": round(rate_adjustment, 1),
            "peak_days": [event.get('date', date.today().isoformat())],
            "impact_duration_days": 3 if event_type in ['conference', 'convention'] else 1,
            "confidence": 65,
            "reasoning": f"Based on event type ({event_type}) and expected attendance patterns.",
            "recommendations": [
                f"Increase rates by {rate_adjustment:.0f}% for event dates",
                "Monitor booking pace and adjust accordingly",
                "Consider minimum stay requirements"
            ]
        }

    async def generate_channel_recommendations(self, channel_data: list) -> list:
        """
        Generate channel optimization recommendations.

        Args:
            channel_data: List of channel performance data with metrics

        Returns:
            List of recommendations for each channel
        """
        system_prompt = """You are a hotel distribution and channel management AI. Analyze channel performance and provide optimization recommendations.
Return a JSON array of recommendations:
[{
  "channel": "channel_name",
  "performance_score": 0-100,
  "action": "increase|maintain|reduce|optimize",
  "recommendation": "Specific action to take",
  "expected_impact": "Description of expected outcome",
  "priority": "high|medium|low"
}]"""

        # Summarize channel data
        channel_summary = []
        for ch in channel_data:
            channel_summary.append({
                "name": ch.get('channel', 'Unknown'),
                "revenue": ch.get('total_revenue', 0),
                "bookings": ch.get('total_bookings', 0),
                "commission_rate": ch.get('commission_rate', 0),
                "adr": ch.get('avg_booking_value', 0)
            })

        prompt = f"""Analyze these channel performance metrics and provide optimization recommendations:

Channel Performance:
{json.dumps(channel_summary, indent=2)}

Provide recommendations for each channel in JSON array format."""

        try:
            result = await self._call_openai(prompt, system_prompt, temperature=0.6)
            if isinstance(result, list):
                return result
            return self._generate_fallback_channel_recommendations(channel_data)
        except (OpenAIConnectionError, AIResponseParseError) as e:
            logger.error(f"Failed to generate channel recommendations: {e}")
            return self._generate_fallback_channel_recommendations(channel_data)

    def _generate_fallback_channel_recommendations(self, channel_data: list) -> list:
        """Generate fallback channel recommendations without AI."""
        recommendations = []

        for ch in channel_data:
            channel_name = ch.get('channel', 'Unknown')
            commission = ch.get('commission_rate', 0)
            revenue = ch.get('total_revenue', 0)
            bookings = ch.get('total_bookings', 0)

            if channel_name.lower() == 'direct':
                action = "increase"
                rec = "Increase direct booking incentives to reduce OTA dependency"
                priority = "high"
                score = 85
            elif commission > 18:
                action = "reduce"
                rec = f"High commission rate ({commission:.1f}%). Consider reducing allocation or renegotiating terms."
                priority = "high"
                score = 50
            elif commission > 12:
                action = "optimize"
                rec = "Monitor ROI and optimize rate parity"
                priority = "medium"
                score = 65
            else:
                action = "maintain"
                rec = "Good commission structure. Maintain current strategy."
                priority = "low"
                score = 75

            recommendations.append({
                "channel": channel_name,
                "performance_score": score,
                "action": action,
                "recommendation": rec,
                "expected_impact": f"Potential revenue optimization through {action} strategy",
                "priority": priority
            })

        return recommendations

    async def explain_forecast(self, forecast_data: list) -> str:
        """
        Generate natural language explanation of forecast.

        Args:
            forecast_data: List of forecast data points

        Returns:
            Natural language explanation of the forecast
        """
        if not forecast_data:
            return "No forecast data available for analysis."

        cache_key = self._get_cache_key("explain_forecast", {"length": len(forecast_data)})
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        system_prompt = """You are a hotel revenue analyst. Explain the demand forecast in clear, actionable language.
Focus on:
1. Overall trend (next 30 days)
2. Key high and low demand periods
3. Specific dates requiring attention
4. Actionable recommendations
Keep response under 200 words."""

        # Analyze forecast summary
        next_30 = forecast_data[:30]
        high_demand = [f for f in next_30 if f.get('demand_level') in ['high', 'critical']]
        low_demand = [f for f in next_30 if f.get('demand_level') in ['low', 'very_low']]
        avg_occupancy = sum(f.get('forecasted_occupancy', 0) for f in next_30) / max(len(next_30), 1)

        weekday_avg = sum(f.get('forecasted_occupancy', 0) for f in next_30 if not f.get('is_weekend', False)) / max(sum(1 for f in next_30 if not f.get('is_weekend', False)), 1)
        weekend_avg = sum(f.get('forecasted_occupancy', 0) for f in next_30 if f.get('is_weekend', False)) / max(sum(1 for f in next_30 if f.get('is_weekend', False)), 1)

        prompt = f"""Explain this 30-day demand forecast:

Summary:
- Average forecasted occupancy: {avg_occupancy:.1f}%
- High demand days: {len(high_demand)} (occupancy 80%+)
- Low demand days: {len(low_demand)} (occupancy <50%)
- Weekday average: {weekday_avg:.1f}%
- Weekend average: {weekend_avg:.1f}%

High Demand Dates: {', '.join(f['date'] for f in high_demand[:5]) if high_demand else 'None'}
Low Demand Dates: {', '.join(f['date'] for f in low_demand[:5]) if low_demand else 'None'}

Provide a clear explanation with actionable insights."""

        try:
            result = await self._call_openai(prompt, system_prompt, temperature=0.6, parse_json=False)
            self._set_cached(cache_key, result)
            return result
        except (OpenAIConnectionError, AIResponseParseError) as e:
            logger.error(f"Failed to explain forecast: {e}")
            return self._generate_fallback_forecast_explanation(forecast_data)

    def _generate_fallback_forecast_explanation(self, forecast_data: list) -> str:
        """Generate fallback forecast explanation without AI."""
        next_30 = forecast_data[:30]
        high_demand = [f for f in next_30 if f.get('demand_level') in ['high', 'critical']]
        low_demand = [f for f in next_30 if f.get('demand_level') in ['low', 'very_low']]
        avg_occupancy = sum(f.get('forecasted_occupancy', 0) for f in next_30) / max(len(next_30), 1)

        explanation = f"30-Day Forecast Summary: Average expected occupancy is {avg_occupancy:.1f}%. "

        if high_demand:
            explanation += f"There are {len(high_demand)} high-demand days identified, "
            if len(high_demand) <= 3:
                explanation += f"including {', '.join(f['date'] for f in high_demand)}. "
            else:
                explanation += "which present pricing optimization opportunities. "
            explanation += "Consider rate increases of 15-25% for these dates. "

        if low_demand:
            explanation += f"There are {len(low_demand)} low-demand days that may require promotional attention. "

        if avg_occupancy > 75:
            explanation += "Overall forecast is strong - focus on rate optimization."
        elif avg_occupancy > 55:
            explanation += "Moderate demand expected - balance rate and occupancy goals."
        else:
            explanation += "Lower demand projected - consider promotional strategies to drive bookings."

        return explanation

    async def generate_pricing_json(self, context: dict) -> dict:
        """
        Generate structured JSON pricing recommendation.

        Args:
            context: Same as generate_pricing_insight

        Returns:
            JSON dict with recommended_rate, confidence, reasoning
        """
        system_prompt = """You are a hotel revenue management AI. Analyze the data and provide a pricing recommendation.
Return a JSON object with:
{
  "recommended_rate": number,
  "confidence": number (0-100),
  "reasoning": "1-2 sentence explanation",
  "rate_change_percent": number,
  "action": "increase|decrease|maintain"
}"""

        prompt = f"""Analyze this pricing scenario:

Current occupancy: {context.get('occupancy', 70)}%
Forecasted demand: {context.get('demand_level', 'moderate')}
Competitor average rate: ${context.get('competitor_avg', 150):.2f}
Current rate: ${context.get('current_rate', 150):.2f}
Day of week: {context.get('day', 'Monday')}
Days until arrival: {context.get('lead_time', 7)}
Room type: {context.get('room_type', 'Standard')}

Provide pricing recommendation in JSON format."""

        try:
            result = await self._call_openai(prompt, system_prompt, temperature=0.4)
            if isinstance(result, dict) and "recommended_rate" in result:
                return result
            return self._generate_fallback_pricing_json(context)
        except (OpenAIConnectionError, AIResponseParseError) as e:
            logger.error(f"Failed to generate pricing JSON: {e}")
            return self._generate_fallback_pricing_json(context)

    def _generate_fallback_pricing_json(self, context: dict) -> dict:
        """Generate fallback pricing JSON without AI."""
        current_rate = context.get('current_rate', 150)
        competitor_avg = context.get('competitor_avg', 150)
        demand_level = context.get('demand_level', 'moderate')
        occupancy = context.get('occupancy', 70)

        # Calculate adjustment
        demand_multipliers = {
            'critical': 1.25,
            'high': 1.15,
            'moderate': 1.0,
            'low': 0.9,
            'very_low': 0.85
        }
        multiplier = demand_multipliers.get(demand_level, 1.0)

        # Competitive adjustment
        if current_rate < competitor_avg * 0.9:
            multiplier *= 1.05
        elif current_rate > competitor_avg * 1.15:
            multiplier *= 0.95

        recommended_rate = current_rate * multiplier
        change_percent = (recommended_rate - current_rate) / current_rate * 100

        if change_percent > 3:
            action = "increase"
        elif change_percent < -3:
            action = "decrease"
        else:
            action = "maintain"

        return {
            "recommended_rate": round(recommended_rate, 2),
            "confidence": 70,
            "reasoning": f"{demand_level.capitalize()} demand with {occupancy}% occupancy suggests {action} strategy.",
            "rate_change_percent": round(change_percent, 1),
            "action": action
        }

    async def generate_batch_pricing_insights(self, batch_context: dict) -> dict:
        """
        Generate pricing insights for multiple recommendations in a SINGLE API call.
        This batched approach reduces API calls from 60+ to just 1.

        Args:
            batch_context: Dict containing:
                - count: Number of recommendations
                - recommendations: List of recommendation dicts with date, room_type,
                  current_rate, ml_recommended_rate, demand_level, occupancy, etc.

        Returns:
            Dict with enhanced_recommendations list
        """
        recommendations = batch_context.get('recommendations', [])
        count = len(recommendations)

        if count == 0:
            return {"enhanced_recommendations": []}

        # Check cache first (use date range as cache key component)
        cache_data = {
            'count': count,
            'dates': [r.get('date') for r in recommendations[:3]],  # First 3 dates
            'room_types': list(set(r.get('room_type') for r in recommendations))
        }
        cache_key = self._get_cache_key("batch_pricing", cache_data)
        cached = self._get_cached(cache_key)
        if cached:
            logger.info("Returning cached batch pricing insights")
            return cached

        system_prompt = """You are a hotel revenue management AI. Analyze multiple pricing scenarios and provide optimized recommendations for each.
Return a JSON object with:
{
  "enhanced_recommendations": [
    {
      "recommended_rate": number,
      "confidence": number (0-100),
      "reasoning": "brief explanation"
    },
    ...
  ]
}
Provide exactly one entry for each input scenario in the same order."""

        # Build compact prompt for batch processing
        scenarios = []
        for i, rec in enumerate(recommendations):
            scenarios.append(
                f"{i+1}. {rec.get('room_type', 'Room')} on {rec.get('date', 'N/A')}: "
                f"${rec.get('current_rate', 150):.0f} current, "
                f"ML suggests ${rec.get('ml_recommended_rate', 150):.0f}, "
                f"{rec.get('demand_level', 'moderate')} demand ({rec.get('occupancy', 70):.0f}% occ), "
                f"competitors avg ${rec.get('competitor_avg', 150):.0f}, "
                f"priority: {rec.get('priority', 'medium')}"
            )

        prompt = f"""Analyze these {count} pricing scenarios and provide optimized recommendations:

{chr(10).join(scenarios)}

For each scenario, evaluate if the ML recommendation is appropriate given demand, competition, and priority.
Provide your response as JSON with enhanced_recommendations array containing {count} entries."""

        try:
            result = await self._call_openai(prompt, system_prompt, temperature=0.4)
            if isinstance(result, dict) and "enhanced_recommendations" in result:
                self._set_cached(cache_key, result)
                return result
            fallback = self._generate_fallback_batch_insights(recommendations)
            self._set_cached(cache_key, fallback)
            return fallback
        except Exception as e:
            logger.error(f"Failed to generate batch pricing insights: {e}")
            fallback = self._generate_fallback_batch_insights(recommendations)
            self._set_cached(cache_key, fallback)
            return fallback

    def _generate_fallback_batch_insights(self, recommendations: list) -> dict:
        """Generate fallback batch insights without AI."""
        enhanced = []
        for rec in recommendations:
            ml_rate = rec.get('ml_recommended_rate', rec.get('current_rate', 150))
            demand_level = rec.get('demand_level', 'moderate')
            occupancy = rec.get('occupancy', 70)

            enhanced.append({
                "recommended_rate": ml_rate,
                "confidence": 75,
                "reasoning": f"{demand_level.capitalize()} demand at {occupancy:.0f}% occupancy - rate optimized for market conditions."
            })
        return {"enhanced_recommendations": enhanced}

    def is_available(self) -> bool:
        """Check if AI service is available."""
        return self.client is not None and bool(self.api_key)

    def clear_cache(self) -> None:
        """Clear the response cache."""
        self._cache.clear()


# Singleton instance
_ai_service_instance: Optional[AIService] = None


def get_ai_service() -> AIService:
    """Get or create AIService singleton instance."""
    global _ai_service_instance
    if _ai_service_instance is None:
        _ai_service_instance = AIService()
    return _ai_service_instance
