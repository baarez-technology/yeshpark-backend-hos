"""
Revenue Intelligence Service
Provides AI-powered revenue management, forecasting, and pricing optimization
Integrates with OpenAI-powered AI services for intelligent recommendations.
"""
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from sqlmodel import select, func, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.exc import OperationalError
import numpy as np
import logging
from decimal import Decimal

from app.models.revenue import (
    PricingAdjustments,
    ChannelPerformance,
    DynamicPricingRules,
    CompetitorData,
    ForecastData
)
from app.models.bookings import DailyMetrics, RevenueBySource
from app.models.inventory import RoomType, Room, DailyRate, RatePlan, DailyAvailability
from app.models.reservations import Reservation, Booking

# AI Service imports
from app.services.ai_service import AIService, get_ai_service
from app.services.ml_forecast_service import MLForecastService, get_ml_forecast_service
from app.services.recommendation_engine import RecommendationEngine, get_recommendation_engine

logger = logging.getLogger(__name__)


def _serialize_utc_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Serialize datetime to ISO string; append 'Z' for naive UTC so frontend parses as UTC (shows 'just now' correctly)."""
    if dt is None:
        return None
    s = dt.isoformat()
    if dt.tzinfo is None:
        return s + "Z"
    return s


class RevenueIntelligenceService:
    """Service for revenue intelligence and optimization."""

    def __init__(self, session: AsyncSession):
        self.session = session
        # Initialize AI services
        self._ai_service: Optional[AIService] = None
        self._ml_service: Optional[MLForecastService] = None
        self._recommendation_engine: Optional[RecommendationEngine] = None
        self._total_rooms: int = 70  # Default, will be updated on first query

    @property
    def ai_service(self) -> AIService:
        """Lazy load AI service."""
        if self._ai_service is None:
            self._ai_service = get_ai_service()
        return self._ai_service

    @property
    def ml_service(self) -> MLForecastService:
        """Lazy load ML forecast service."""
        if self._ml_service is None:
            self._ml_service = get_ml_forecast_service(self._total_rooms)
        return self._ml_service

    @property
    def recommendation_engine(self) -> RecommendationEngine:
        """Lazy load recommendation engine."""
        if self._recommendation_engine is None:
            self._recommendation_engine = get_recommendation_engine(self._total_rooms)
        return self._recommendation_engine

    async def _get_total_rooms(self) -> int:
        """Get total room count from database."""
        rooms_result = await self.session.exec(
            select(func.count(Room.id)).where(Room.status != 'out_of_service')
        )
        total = rooms_result.one() or 70
        self._total_rooms = total
        return total

    # ==================== KPI METRICS ====================

    async def get_realtime_kpis(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Get real-time revenue KPIs."""
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today()

        # Get total rooms (exclude out_of_service)
        rooms_result = await self.session.exec(
            select(func.count(Room.id)).where(Room.status != 'out_of_service')
        )
        total_rooms = rooms_result.one() or 1

        # Get bookings from new Booking model (primary source)
        bookings_result = await self.session.exec(
            select(Booking).where(
                and_(
                    Booking.arrival_date <= end_date,
                    Booking.departure_date >= start_date,
                    Booking.status.in_(['confirmed', 'checked_in', 'booked'])
                )
            )
        )
        bookings = bookings_result.all()

        # Also get legacy reservations for backward compatibility
        reservations_result = await self.session.exec(
            select(Reservation).where(
                and_(
                    Reservation.arrival_date <= end_date,
                    Reservation.departure_date >= start_date,
                    Reservation.status.in_(['booked', 'checked_in', 'confirmed'])
                )
            )
        )
        reservations = reservations_result.all()

        # Calculate metrics from both sources
        # Use net_revenue if available (new schema), fallback to total_price, then total_amount
        booking_revenue = sum(
            float(b.net_revenue or b.total_price or 0) for b in bookings
        )
        reservation_revenue = sum(float(r.total_amount or 0) for r in reservations)
        total_revenue = booking_revenue + reservation_revenue
        occupied_room_nights = len(bookings) + len(reservations)

        days_in_period = (end_date - start_date).days + 1
        available_room_nights = total_rooms * days_in_period

        occupancy = (occupied_room_nights / available_room_nights * 100) if available_room_nights > 0 else 0
        adr = total_revenue / occupied_room_nights if occupied_room_nights > 0 else 0
        revpar = total_revenue / available_room_nights if available_room_nights > 0 else 0

        # Get previous period for comparison
        prev_start = start_date - timedelta(days=days_in_period)
        prev_end = start_date - timedelta(days=1)

        # Get previous bookings from new Booking model
        prev_bookings_result = await self.session.exec(
            select(Booking).where(
                and_(
                    Booking.arrival_date <= prev_end,
                    Booking.departure_date >= prev_start,
                    Booking.status.in_(['confirmed', 'checked_in', 'booked'])
                )
            )
        )
        prev_bookings = prev_bookings_result.all()

        # Also get previous legacy reservations
        prev_result = await self.session.exec(
            select(Reservation).where(
                and_(
                    Reservation.arrival_date <= prev_end,
                    Reservation.departure_date >= prev_start,
                    Reservation.status.in_(['booked', 'checked_in', 'confirmed'])
                )
            )
        )
        prev_reservations = prev_result.all()

        # Calculate previous period metrics from both sources
        prev_booking_revenue = sum(
            float(b.net_revenue or b.total_price or 0) for b in prev_bookings
        )
        prev_reservation_revenue = sum(float(r.total_amount or 0) for r in prev_reservations)
        prev_revenue = prev_booking_revenue + prev_reservation_revenue
        prev_occupied = len(prev_bookings) + len(prev_reservations)

        prev_occupancy = (prev_occupied / available_room_nights * 100) if available_room_nights > 0 else 0
        prev_adr = prev_revenue / prev_occupied if prev_occupied > 0 else 0
        prev_revpar = prev_revenue / available_room_nights if available_room_nights > 0 else 0

        # Calculate trends
        revenue_trend = ((total_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0
        occupancy_trend = occupancy - prev_occupancy
        adr_trend = ((adr - prev_adr) / prev_adr * 100) if prev_adr > 0 else 0
        revpar_trend = ((revpar - prev_revpar) / prev_revpar * 100) if prev_revpar > 0 else 0

        return {
            "total_revenue": round(total_revenue, 2),
            "revenue_trend": round(revenue_trend, 1),
            "occupancy": round(occupancy, 1),
            "occupancy_trend": round(occupancy_trend, 1),
            "adr": round(adr, 2),
            "adr_trend": round(adr_trend, 1),
            "revpar": round(revpar, 2),
            "revpar_trend": round(revpar_trend, 1),
            "total_bookings": len(reservations),
            "available_room_nights": available_room_nights,
            "occupied_room_nights": occupied_room_nights,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days_in_period
            }
        }

    async def get_kpi_summary(
        self,
        period_type: str = "daily"
    ) -> Dict[str, Any]:
        """Get KPI summary for different periods."""
        today = date.today()

        periods = {
            "today": {
                "start": today,
                "end": today,
                "label": "Today"
            },
            "week": {
                "start": today - timedelta(days=7),
                "end": today,
                "label": "Last 7 Days"
            },
            "month": {
                "start": today - timedelta(days=30),
                "end": today,
                "label": "Last 30 Days"
            },
            "next_7_days": {
                "start": today,
                "end": today + timedelta(days=7),
                "label": "Next 7 Days"
            },
            "next_30_days": {
                "start": today,
                "end": today + timedelta(days=30),
                "label": "Next 30 Days"
            }
        }

        result = {}
        for period_name, period_config in periods.items():
            kpis = await self.get_realtime_kpis(
                start_date=period_config["start"],
                end_date=period_config["end"]
            )
            result[period_name] = {
                **kpis,
                "label": period_config["label"]
            }

        return result

    # ==================== DEMAND FORECASTING ====================

    async def get_demand_forecast(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        room_type_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get demand forecast for the specified period."""
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today() + timedelta(days=90)

        # Check if we have forecasts in the database
        query = select(ForecastData).where(
            and_(
                ForecastData.forecast_date >= start_date,
                ForecastData.forecast_date <= end_date,
                ForecastData.forecast_type == "demand"
            )
        ).order_by(ForecastData.forecast_date)

        result = await self.session.exec(query)
        forecasts = result.all()

        if forecasts:
            return [
                {
                    "date": f.forecast_date.isoformat(),
                    "forecasted_demand": f.forecasted_value,
                    "actual_demand": f.actual_value,
                    "confidence_level": self._normalize_confidence_0_100(f.confidence_level or 85),
                    "variance": f.variance_percentage,
                    "forecasted_occupancy": getattr(f, "forecasted_occupancy", None) or 70,
                    "demand_level": getattr(f, "demand_level", None) or "moderate",
                }
                for f in forecasts
            ]

        # Generate forecast using historical data and simple prediction
        return await self._generate_demand_forecast(start_date, end_date, room_type_id)

    async def _generate_demand_forecast(
        self,
        start_date: date,
        end_date: date,
        room_type_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Generate demand forecast based on historical patterns."""
        # Get historical booking patterns from both Booking and Reservation tables
        historical_start = start_date - timedelta(days=365)

        # Get from new Booking model
        booking_query = select(
            func.date(Booking.arrival_date).label('date'),
            func.count(Booking.id).label('bookings')
        ).where(
            and_(
                Booking.arrival_date >= historical_start,
                Booking.arrival_date < start_date,
                Booking.status.in_(['confirmed', 'checked_in', 'checked_out', 'booked'])
            )
        ).group_by(func.date(Booking.arrival_date))

        booking_result = await self.session.exec(booking_query)

        # Get from legacy Reservation model
        query = select(
            func.date(Reservation.arrival_date).label('date'),
            func.count(Reservation.id).label('bookings')
        ).where(
            and_(
                Reservation.arrival_date >= historical_start,
                Reservation.arrival_date < start_date,
                Reservation.status.in_(['booked', 'checked_in', 'checked_out', 'completed'])
            )
        ).group_by(func.date(Reservation.arrival_date))

        result = await self.session.exec(query)

        # Parse dates to date objects if they're strings and combine both sources
        historical = {}

        # Process new Booking results
        for row in booking_result.all():
            row_date = row.date
            if isinstance(row_date, str):
                from datetime import datetime as dt
                try:
                    row_date = dt.strptime(row_date, "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue
            historical[row_date] = historical.get(row_date, 0) + row.bookings

        # Process legacy Reservation results
        for row in result.all():
            row_date = row.date
            if isinstance(row_date, str):
                from datetime import datetime as dt
                try:
                    row_date = dt.strptime(row_date, "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue
            historical[row_date] = historical.get(row_date, 0) + row.bookings

        # Get total rooms for capacity (exclude out_of_service)
        rooms_result = await self.session.exec(
            select(func.count(Room.id)).where(Room.status != 'out_of_service')
        )
        total_rooms = rooms_result.one() or 70

        forecasts = []
        current_date = start_date

        while current_date <= end_date:
            # Use day of week pattern from historical data
            day_of_week = current_date.weekday()

            # Calculate average for this day of week from historical data
            same_dow_bookings = [
                v for d, v in historical.items()
                if hasattr(d, 'weekday') and d.weekday() == day_of_week
            ]

            if same_dow_bookings:
                base_demand = np.mean(same_dow_bookings)
            else:
                # Default occupancy-based demand
                base_demand = total_rooms * 0.7  # 70% baseline

            # Apply seasonality adjustments
            month = current_date.month
            seasonality_factor = self._get_seasonality_factor(month)

            # Apply day of week adjustments
            dow_factor = self._get_dow_factor(day_of_week)

            # Calculate forecasted demand
            forecasted_demand = base_demand * seasonality_factor * dow_factor

            # Add some variance for confidence interval (0-100 scale, clamped)
            confidence = min(100.0, max(0.0, 85 + np.random.uniform(-5, 10)))

            # Calculate occupancy percentage
            occupancy = min((forecasted_demand / total_rooms) * 100, 100)

            forecasts.append({
                "date": current_date.isoformat(),
                "forecasted_demand": round(forecasted_demand, 1),
                "forecasted_occupancy": round(occupancy, 1),
                "confidence_level": round(confidence, 1),
                "day_of_week": current_date.strftime("%A"),
                "is_weekend": day_of_week >= 5,
                "demand_level": self._categorize_demand(occupancy)
            })

            current_date += timedelta(days=1)

        return forecasts

    def _get_seasonality_factor(self, month: int) -> float:
        """Get seasonality adjustment factor by month."""
        factors = {
            1: 0.8,   # January - low
            2: 0.85,  # February
            3: 0.95,  # March
            4: 1.0,   # April
            5: 1.1,   # May - picking up
            6: 1.2,   # June - high
            7: 1.25,  # July - peak
            8: 1.2,   # August - high
            9: 1.05,  # September
            10: 1.0,  # October
            11: 0.9,  # November
            12: 1.15  # December - holiday
        }
        return factors.get(month, 1.0)

    def _get_dow_factor(self, day_of_week: int) -> float:
        """Get day of week adjustment factor."""
        factors = {
            0: 0.85,  # Monday
            1: 0.85,  # Tuesday
            2: 0.9,   # Wednesday
            3: 0.95,  # Thursday
            4: 1.15,  # Friday
            5: 1.25,  # Saturday
            6: 1.0    # Sunday
        }
        return factors.get(day_of_week, 1.0)

    def _categorize_demand(self, occupancy: float) -> str:
        """Categorize demand level based on occupancy."""
        if occupancy >= 90:
            return "critical"
        elif occupancy >= 80:
            return "high"
        elif occupancy >= 60:
            return "moderate"
        elif occupancy >= 40:
            return "low"
        else:
            return "very_low"

    @staticmethod
    def _normalize_confidence_0_100(value: Optional[float], default: float = 85.0) -> float:
        """
        Normalize confidence to 0-100 scale and clamp. Prevents values like 8876%.
        - If value is None or missing, return default.
        - If value <= 1, treat as 0-1 fraction and convert to 0-100.
        - Otherwise treat as 0-100 and clamp to [0, 100].
        """
        if value is None:
            return min(100.0, max(0.0, default))
        if value <= 1.0:
            return min(100.0, max(0.0, value * 100.0))
        return min(100.0, max(0.0, float(value)))

    # ==================== PRICING RECOMMENDATIONS ====================

    async def get_pricing_recommendations(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        room_type_id: Optional[int] = None,
        use_ai: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get AI-powered pricing recommendations.

        Args:
            start_date: Start date for recommendations
            end_date: End date for recommendations
            room_type_id: Optional specific room type
            use_ai: Whether to use AI enhancement (default True)

        Returns:
            List of pricing recommendations with AI-enhanced insights
        """
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today() + timedelta(days=30)

        # Update total rooms count
        await self._get_total_rooms()

        # Get room types
        room_types_query = select(RoomType)
        if room_type_id:
            room_types_query = room_types_query.where(RoomType.id == room_type_id)

        result = await self.session.exec(room_types_query)
        room_types = result.all()

        # Convert room types to dict format
        room_types_data = [
            {"id": rt.id, "name": rt.name, "base_price": float(rt.base_price or 0)}
            for rt in room_types
        ]

        # Get demand forecast
        forecasts = await self.get_demand_forecast(start_date, end_date)

        # Get competitor data
        competitor_rates_by_date = await self._get_competitor_rates(start_date, end_date)
        competitor_rates = [
            {"date": d, "rate": data.get("avg_rate", 0)}
            for d, data in competitor_rates_by_date.items()
        ]

        # Build current rates dict
        current_rates = {str(rt.id): float(rt.base_price or 0) for rt in room_types}

        # Use AI-powered recommendation engine if enabled
        if use_ai:
            try:
                recommendations = await self.recommendation_engine.generate_pricing_recommendations(
                    room_types=room_types_data,
                    forecast=forecasts,
                    competitor_rates=competitor_rates,
                    current_rates=current_rates,
                    start_date=start_date,
                    end_date=end_date
                )
                logger.info(f"Generated {len(recommendations)} AI-enhanced pricing recommendations")
                return recommendations
            except Exception as e:
                logger.warning(f"AI recommendation failed, falling back to basic: {e}")

        # Fallback to basic recommendation logic
        return await self._generate_basic_pricing_recommendations(
            room_types=room_types,
            forecasts=forecasts,
            competitor_rates=competitor_rates_by_date,
            start_date=start_date,
            end_date=end_date
        )

    async def _generate_basic_pricing_recommendations(
        self,
        room_types: List[RoomType],
        forecasts: List[Dict[str, Any]],
        competitor_rates: Dict[str, Dict[str, Any]],
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """Generate basic pricing recommendations without AI."""
        forecast_by_date = {f["date"]: f for f in forecasts}
        recommendations = []

        for room_type in room_types:
            base_rate = float(room_type.base_price or 0)

            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.isoformat()
                forecast = forecast_by_date.get(date_str, {})
                demand_level = forecast.get("demand_level", "moderate")
                occupancy = forecast.get("forecasted_occupancy", 70)

                # Calculate recommended rate based on demand
                demand_multiplier = self._get_demand_multiplier(demand_level)

                # Apply day of week adjustment
                dow_multiplier = self._get_dow_factor(current_date.weekday())

                # Apply lead time adjustment (closer dates = higher rates)
                days_out = (current_date - date.today()).days
                lead_time_multiplier = self._get_lead_time_multiplier(days_out)

                # Calculate recommended rate
                recommended_rate = base_rate * demand_multiplier * dow_multiplier * lead_time_multiplier

                # Get competitor average for comparison
                comp_avg = competitor_rates.get(date_str, {}).get("avg_rate", recommended_rate)

                # Ensure we're competitive but not underpricing
                if recommended_rate < comp_avg * 0.9:
                    recommended_rate = comp_avg * 0.95  # Stay slightly below market
                elif recommended_rate > comp_avg * 1.2:
                    recommended_rate = comp_avg * 1.15  # Don't go too high

                change_percent = ((recommended_rate - base_rate) / base_rate * 100) if base_rate > 0 else 0

                recommendation = {
                    "date": date_str,
                    "room_type_id": room_type.id,
                    "room_type_name": room_type.name,
                    "current_rate": base_rate,
                    "recommended_rate": round(recommended_rate, 2),
                    "change_percent": round(change_percent, 1),
                    "demand_level": demand_level,
                    "forecasted_occupancy": occupancy,
                    "competitor_avg": round(comp_avg, 2),
                    "confidence": round(85 + np.random.uniform(-5, 10), 1),
                    "reasoning": self._get_pricing_reasoning(demand_level, change_percent, days_out),
                    "priority": self._get_recommendation_priority(abs(change_percent), days_out),
                    "ai_enhanced": False
                }

                recommendations.append(recommendation)
                current_date += timedelta(days=1)

        # Sort by priority (high priority first) and date
        recommendations.sort(key=lambda x: (
            0 if x["priority"] == "critical" else 1 if x["priority"] == "high" else 2,
            x["date"]
        ))

        return recommendations

    def _get_demand_multiplier(self, demand_level: str) -> float:
        """Get price multiplier based on demand level."""
        multipliers = {
            "critical": 1.35,
            "high": 1.20,
            "moderate": 1.05,
            "low": 0.90,
            "very_low": 0.80
        }
        return multipliers.get(demand_level, 1.0)

    def _get_lead_time_multiplier(self, days_out: int) -> float:
        """Get price multiplier based on lead time."""
        if days_out <= 1:
            return 1.15  # Last minute premium
        elif days_out <= 7:
            return 1.10
        elif days_out <= 14:
            return 1.05
        elif days_out <= 30:
            return 1.0
        else:
            return 0.95  # Early bird discount

    def _get_pricing_reasoning(self, demand_level: str, change_percent: float, days_out: int) -> str:
        """Generate reasoning for price recommendation."""
        reasons = []

        if demand_level in ["critical", "high"]:
            reasons.append(f"High demand expected ({demand_level})")
        elif demand_level in ["low", "very_low"]:
            reasons.append(f"Low demand forecasted ({demand_level})")

        if days_out <= 3:
            reasons.append("Last-minute booking window")
        elif days_out <= 7:
            reasons.append("Short lead time")
        elif days_out > 60:
            reasons.append("Advance booking opportunity")

        if change_percent > 15:
            reasons.append("Significant revenue opportunity")
        elif change_percent < -10:
            reasons.append("Rate reduction to drive occupancy")

        return "; ".join(reasons) if reasons else "Standard rate recommendation"

    def _get_recommendation_priority(self, change_magnitude: float, days_out: int) -> str:
        """Determine priority of recommendation."""
        if days_out <= 3 and change_magnitude > 10:
            return "critical"
        elif days_out <= 7 or change_magnitude > 15:
            return "high"
        elif change_magnitude > 5:
            return "medium"
        else:
            return "low"

    async def _get_competitor_rates(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[str, Dict[str, Any]]:
        """Get competitor rate data."""
        result = await self.session.exec(
            select(CompetitorData).where(
                and_(
                    CompetitorData.date >= start_date,
                    CompetitorData.date <= end_date
                )
            )
        )
        competitors = result.all()

        rates_by_date = {}
        for comp in competitors:
            date_str = comp.date.isoformat()
            if date_str not in rates_by_date:
                rates_by_date[date_str] = {"rates": [], "avg_rate": 0}
            if comp.rate:
                rates_by_date[date_str]["rates"].append(comp.rate)

        # Calculate averages
        for date_str, data in rates_by_date.items():
            if data["rates"]:
                data["avg_rate"] = np.mean(data["rates"])

        return rates_by_date

    async def _get_active_pricing_rules(self) -> List[DynamicPricingRules]:
        """Get active pricing rules."""
        result = await self.session.exec(
            select(DynamicPricingRules).where(
                DynamicPricingRules.is_active == True
            ).order_by(DynamicPricingRules.priority.desc())
        )
        return result.all()

    # ==================== REVENUE OPPORTUNITIES ====================

    async def get_revenue_opportunities(
        self,
        limit: int = 20,
        use_ai: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get AI-identified revenue opportunities.

        Args:
            limit: Maximum number of opportunities to return
            use_ai: Whether to use AI enhancement

        Returns:
            List of revenue optimization opportunities
        """
        today = date.today()

        # Get current KPIs
        kpis = await self.get_realtime_kpis(
            start_date=today - timedelta(days=30),
            end_date=today
        )

        # Get demand forecast
        forecasts = await self.get_demand_forecast(
            start_date=today,
            end_date=today + timedelta(days=30)
        )

        # Get channel performance
        channel_perf = await self._get_channel_performance()

        # Use AI-powered recommendation engine if enabled
        if use_ai:
            try:
                opportunities = await self.recommendation_engine.identify_revenue_opportunities(
                    kpis=kpis,
                    forecast=forecasts,
                    channel_data=channel_perf
                )
                logger.info(f"Generated {len(opportunities)} AI-enhanced revenue opportunities")
                return opportunities[:limit]
            except Exception as e:
                logger.warning(f"AI opportunity detection failed, falling back to basic: {e}")

        # Fallback to basic opportunity detection
        return await self._generate_basic_revenue_opportunities(
            forecasts=forecasts,
            channel_perf=channel_perf,
            limit=limit
        )

    async def _generate_basic_revenue_opportunities(
        self,
        forecasts: List[Dict[str, Any]],
        channel_perf: List[Dict[str, Any]],
        limit: int
    ) -> List[Dict[str, Any]]:
        """Generate basic revenue opportunities without AI."""
        opportunities = []

        # 1. High demand dates with low rates
        high_demand_dates = [f for f in forecasts if f["demand_level"] in ["high", "critical"]]

        for forecast in high_demand_dates[:5]:
            opportunities.append({
                "id": f"demand_pricing_{forecast['date']}",
                "type": "demand_pricing",
                "title": f"High Demand Opportunity - {forecast['date']}",
                "description": f"Forecasted {forecast['forecasted_occupancy']:.0f}% occupancy with {forecast['demand_level']} demand. Consider rate increase.",
                "revenue_impact": round(1000 * (forecast['forecasted_occupancy'] / 100), 2),
                "priority": "high" if forecast["demand_level"] == "critical" else "medium",
                "action": "Increase rates by 15-25%",
                "date": forecast["date"],
                "confidence": forecast["confidence_level"],
                "ai_generated": False
            })

        # 2. Low occupancy dates needing promotion
        low_demand_dates = [f for f in forecasts if f["demand_level"] in ["low", "very_low"]]

        for forecast in low_demand_dates[:3]:
            opportunities.append({
                "id": f"promotion_{forecast['date']}",
                "type": "promotion",
                "title": f"Drive Occupancy - {forecast['date']}",
                "description": f"Low demand forecasted ({forecast['forecasted_occupancy']:.0f}%). Consider promotional offer.",
                "revenue_impact": round(500 * (1 - forecast['forecasted_occupancy'] / 100), 2),
                "priority": "medium",
                "action": "Launch promotional campaign or discount",
                "date": forecast["date"],
                "confidence": forecast["confidence_level"],
                "ai_generated": False
            })

        # 3. Upsell opportunities
        opportunities.append({
            "id": "upsell_campaign",
            "type": "upsell",
            "title": "Room Upgrade Campaign",
            "description": "Offer suite upgrades at check-in for weekend bookings",
            "revenue_impact": 2500.00,
            "priority": "medium",
            "action": "Enable automatic upgrade offers",
            "confidence": 75,
            "ai_generated": False
        })

        # 4. Channel optimization
        if channel_perf:
            low_commission_channels = [c for c in channel_perf if c.get("commission_rate", 0) < 10]
            if low_commission_channels:
                opportunities.append({
                    "id": "channel_shift",
                    "type": "channel_optimization",
                    "title": "Shift Bookings to Direct Channel",
                    "description": "Increase direct bookings by 10% to save on OTA commissions",
                    "revenue_impact": 3500.00,
                    "priority": "high",
                    "action": "Launch direct booking incentive campaign",
                    "confidence": 80,
                    "ai_generated": False
                })

        # Sort by revenue impact
        opportunities.sort(key=lambda x: x.get("revenue_impact", 0), reverse=True)

        return opportunities[:limit]

    async def _get_channel_performance(self) -> List[Dict[str, Any]]:
        """Get channel performance summary."""
        today = date.today()
        start_date = today - timedelta(days=30)

        result = await self.session.exec(
            select(ChannelPerformance).where(
                ChannelPerformance.date >= start_date
            )
        )
        channels = result.all()

        # Aggregate by channel
        channel_data = {}
        for ch in channels:
            if ch.channel not in channel_data:
                channel_data[ch.channel] = {
                    "channel": ch.channel,
                    "bookings": 0,
                    "revenue": 0,
                    "commission": 0
                }
            channel_data[ch.channel]["bookings"] += ch.bookings_count or 0
            channel_data[ch.channel]["revenue"] += ch.revenue or 0
            channel_data[ch.channel]["commission"] += ch.commission_amount or 0

        # Calculate commission rates
        for ch_name, data in channel_data.items():
            if data["revenue"] > 0:
                data["commission_rate"] = (data["commission"] / data["revenue"]) * 100
            else:
                data["commission_rate"] = 0

        return list(channel_data.values())

    # ==================== ALERTS ====================

    async def get_revenue_alerts(
        self,
        severity: Optional[str] = None,
        use_ai: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get revenue alerts with AI-powered detection.

        Args:
            severity: Optional filter by severity (info, warning, critical)
            use_ai: Whether to use AI enhancement

        Returns:
            List of revenue alerts
        """
        today = date.today()

        # Get current KPIs
        kpis = await self.get_realtime_kpis(
            start_date=today - timedelta(days=30),
            end_date=today
        )

        # Get demand forecast
        forecast = await self.get_demand_forecast(
            start_date=today,
            end_date=today + timedelta(days=7)
        )

        # Get competitor rates
        competitor_rates_by_date = await self._get_competitor_rates(today, today + timedelta(days=7))
        competitor_rates = [
            {"date": d, "rate": data.get("avg_rate", 0)}
            for d, data in competitor_rates_by_date.items()
        ]

        # Use AI-powered alert detection if enabled
        if use_ai:
            try:
                alerts = await self.recommendation_engine.generate_alerts({
                    "kpis": kpis,
                    "forecast": forecast,
                    "competitor_rates": competitor_rates,
                    "historical_data": []  # Could add historical data here
                })
                logger.info(f"Generated {len(alerts)} AI-enhanced alerts")

                # Filter by severity if specified
                if severity:
                    alerts = [a for a in alerts if a.get("severity") == severity]

                return alerts
            except Exception as e:
                logger.warning(f"AI alert detection failed, falling back to basic: {e}")

        # Fallback to basic alert detection
        return await self._generate_basic_revenue_alerts(
            forecast=forecast,
            severity=severity
        )

    async def _generate_basic_revenue_alerts(
        self,
        forecast: List[Dict[str, Any]],
        severity: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Generate basic revenue alerts without AI."""
        alerts = []

        for f in forecast:
            if f["demand_level"] == "critical":
                alerts.append({
                    "id": f"demand_critical_{f['date']}",
                    "type": "demand",
                    "severity": "critical",
                    "title": f"Critical Demand Alert - {f['date']}",
                    "message": f"Occupancy forecasted at {f['forecasted_occupancy']:.0f}%. Immediate rate optimization recommended.",
                    "date": f["date"],
                    "created_at": datetime.now().isoformat(),
                    "ai_generated": False
                })
            elif f["demand_level"] == "very_low":
                alerts.append({
                    "id": f"demand_low_{f['date']}",
                    "type": "demand",
                    "severity": "warning",
                    "title": f"Low Demand Warning - {f['date']}",
                    "message": f"Occupancy forecasted at only {f['forecasted_occupancy']:.0f}%. Consider promotional offers.",
                    "date": f["date"],
                    "created_at": datetime.now().isoformat(),
                    "ai_generated": False
                })

        # Add rate parity alerts (simulated)
        alerts.append({
            "id": "rate_parity_1",
            "type": "rate_parity",
            "severity": "warning",
            "title": "Rate Disparity Detected",
            "message": "Your rates on Booking.com are 5% lower than direct channel for Standard Room.",
            "created_at": datetime.now().isoformat(),
            "ai_generated": False
        })

        # Filter by severity if specified
        if severity:
            alerts = [a for a in alerts if a["severity"] == severity]

        return alerts

    # ==================== SCENARIO PLANNING ====================

    async def simulate_scenario(
        self,
        scenario_type: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Simulate a pricing/revenue scenario.

        Supported scenario types:
        - rate_increase / pricing_change: Simulate rate increase with demand elasticity
        - rate_decrease: Simulate rate decrease with demand elasticity
        - promotion: Simulate promotional discount with demand lift

        Raises ValueError if scenario_type is not supported.
        """
        # Validate scenario type
        valid_types = {
            "rate_increase", "pricing_change",  # pricing_change is alias for rate_increase
            "rate_decrease",
            "promotion"
        }

        if scenario_type not in valid_types:
            raise ValueError(
                f"Invalid scenario_type '{scenario_type}'. "
                f"Supported types: rate_increase, rate_decrease, promotion, pricing_change (alias for rate_increase)"
            )

        # Get baseline forecast
        start_date = date.today()
        end_date = start_date + timedelta(days=30)

        baseline_kpis = await self.get_realtime_kpis(start_date, end_date)
        baseline_revenue = baseline_kpis["total_revenue"]

        # Apply scenario adjustments
        if scenario_type in ("rate_increase", "pricing_change"):
            rate_change = parameters.get("percentage", 10) / 100
            # Simple elasticity model: 10% price increase = ~5% demand decrease
            elasticity = -0.5
            demand_change = rate_change * elasticity

            new_revenue = baseline_revenue * (1 + rate_change) * (1 + demand_change)

        elif scenario_type == "rate_decrease":
            rate_change = -abs(parameters.get("percentage", 10)) / 100
            elasticity = -0.5
            demand_change = rate_change * elasticity

            new_revenue = baseline_revenue * (1 + rate_change) * (1 + demand_change)

        elif scenario_type == "promotion":
            discount = parameters.get("discount", 15) / 100
            expected_demand_lift = parameters.get("demand_lift", 20) / 100

            new_revenue = baseline_revenue * (1 - discount) * (1 + expected_demand_lift)

        else:
            # This should never happen due to validation above, but keeping for safety
            new_revenue = baseline_revenue

        revenue_impact = new_revenue - baseline_revenue
        revenue_change_pct = ((new_revenue - baseline_revenue) / baseline_revenue * 100) if baseline_revenue > 0 else 0

        return {
            "scenario_type": scenario_type,
            "parameters": parameters,
            "baseline": {
                "revenue": round(baseline_revenue, 2),
                "occupancy": baseline_kpis["occupancy"],
                "adr": baseline_kpis["adr"]
            },
            "projected": {
                "revenue": round(new_revenue, 2),
                "revenue_change": round(revenue_impact, 2),
                "revenue_change_percent": round(revenue_change_pct, 1)
            },
            "recommendation": "Proceed" if revenue_impact > 0 else "Not recommended",
            "confidence": 75,
            "simulated_at": datetime.now().isoformat()
        }

    # ==================== CHANNEL ANALYSIS ====================

    async def get_channel_analysis(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Get channel performance analysis."""
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        result = await self.session.exec(
            select(ChannelPerformance).where(
                and_(
                    ChannelPerformance.date >= start_date,
                    ChannelPerformance.date <= end_date
                )
            )
        )
        channel_data = result.all()

        # Aggregate by channel
        channels = {}
        for ch in channel_data:
            if ch.channel not in channels:
                channels[ch.channel] = {
                    "channel": ch.channel,
                    "total_bookings": 0,
                    "total_revenue": 0,
                    "total_commission": 0,
                    "net_revenue": 0,
                    "cancellations": 0,
                    "avg_booking_value": 0,
                    "days": 0
                }

            channels[ch.channel]["total_bookings"] += ch.bookings_count or 0
            channels[ch.channel]["total_revenue"] += ch.revenue or 0
            channels[ch.channel]["total_commission"] += ch.commission_amount or 0
            channels[ch.channel]["net_revenue"] += ch.net_revenue or 0
            channels[ch.channel]["cancellations"] += ch.cancellations_count or 0
            channels[ch.channel]["days"] += 1

        # Calculate metrics
        for ch_name, data in channels.items():
            if data["total_bookings"] > 0:
                data["avg_booking_value"] = data["total_revenue"] / data["total_bookings"]
                data["commission_rate"] = (data["total_commission"] / data["total_revenue"] * 100) if data["total_revenue"] > 0 else 0
                data["cancellation_rate"] = (data["cancellations"] / data["total_bookings"] * 100)
            else:
                data["avg_booking_value"] = 0
                data["commission_rate"] = 0
                data["cancellation_rate"] = 0

        # Calculate totals
        total_revenue = sum(ch["total_revenue"] for ch in channels.values())
        total_bookings = sum(ch["total_bookings"] for ch in channels.values())

        # Add market share
        for ch_name, data in channels.items():
            data["revenue_share"] = (data["total_revenue"] / total_revenue * 100) if total_revenue > 0 else 0
            data["booking_share"] = (data["total_bookings"] / total_bookings * 100) if total_bookings > 0 else 0

        # Generate recommendations
        recommendations = []
        for ch_name, data in channels.items():
            if data["commission_rate"] > 15:
                recommendations.append({
                    "channel": ch_name,
                    "type": "reduce_commission",
                    "message": f"High commission rate ({data['commission_rate']:.1f}%). Consider renegotiating or reducing allocation."
                })
            if data["cancellation_rate"] > 20:
                recommendations.append({
                    "channel": ch_name,
                    "type": "reduce_cancellations",
                    "message": f"High cancellation rate ({data['cancellation_rate']:.1f}%). Review booking policies."
                })

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "channels": list(channels.values()),
            "totals": {
                "revenue": total_revenue,
                "bookings": total_bookings
            },
            "recommendations": recommendations
        }

    # ==================== PRICING RECOMMENDATION ACTIONS ====================

    async def accept_pricing_recommendation(self, recommendation_id: int = None, *, room_type_id: int = None, rec_date: str = None) -> Dict[str, Any]:
        """Accept a pricing recommendation and apply the rate.

        Can be called with either:
        - room_type_id + rec_date (preferred, used by composite IDs like '1_2026-02-23')
        - recommendation_id (legacy integer index)
        """
        rec = None

        if room_type_id is not None and rec_date is not None:
            # Direct lookup by room_type_id and date — no index dependency
            target_date = date.fromisoformat(rec_date) if isinstance(rec_date, str) else rec_date
            recommendations = await self.get_pricing_recommendations(
                start_date=target_date,
                end_date=target_date + timedelta(days=1),
                room_type_id=room_type_id
            )
            for r in recommendations:
                if r.get("room_type_id") == room_type_id and r.get("date") == rec_date:
                    rec = r
                    break
            if not rec:
                raise ValueError(f"Recommendation not found for room_type_id={room_type_id}, date={rec_date}")
        elif recommendation_id is not None:
            # Legacy index-based lookup
            today = date.today()
            recommendations = await self.get_pricing_recommendations(
                start_date=today,
                end_date=today + timedelta(days=30)
            )
            if recommendation_id < 0 or recommendation_id >= len(recommendations):
                raise ValueError(f"Recommendation {recommendation_id} not found")
            rec = recommendations[recommendation_id]
        else:
            raise ValueError("Must provide either room_type_id+rec_date or recommendation_id")

        # Get room type to validate bounds
        room_type_result = await self.session.exec(
            select(RoomType).where(RoomType.id == rec["room_type_id"])
        )
        room_type = room_type_result.first()
        if not room_type:
            raise ValueError(f"Room type {rec['room_type_id']} not found")

        # Get auto-pricing config for rate bounds
        config = await self.get_auto_pricing_config()
        base_rate = float(room_type.base_price or 0)
        min_rate = base_rate * (1 + config.get("min_rate_adjustment", -30) / 100)
        max_rate = base_rate * (1 + config.get("max_rate_adjustment", 50) / 100)

        new_rate = rec["recommended_rate"]
        if new_rate < min_rate:
            new_rate = min_rate
        elif new_rate > max_rate:
            new_rate = max_rate

        # Apply the rate to DailyRate (BAR plan) so Rate Calendar reflects the change
        rec_date_obj = datetime.strptime(rec["date"], "%Y-%m-%d").date()
        bar_plan_result = await self.session.exec(
            select(RatePlan).where(RatePlan.code == "BAR").limit(1)
        )
        bar_plan = bar_plan_result.first()

        if bar_plan:
            daily_rate_result = await self.session.exec(
                select(DailyRate).where(
                    and_(
                        DailyRate.room_type_id == rec["room_type_id"],
                        DailyRate.rate_plan_id == bar_plan.id,
                        DailyRate.date == rec_date_obj,
                    )
                ).limit(1)
            )
            existing_daily = daily_rate_result.first()
            if existing_daily:
                existing_daily.override_rate = round(new_rate, 2)
                existing_daily.updated_at = datetime.utcnow()
            else:
                daily_rate = DailyRate(
                    room_type_id=rec["room_type_id"],
                    rate_plan_id=bar_plan.id,
                    date=rec_date_obj,
                    base_rate=base_rate,
                    override_rate=round(new_rate, 2),
                )
                self.session.add(daily_rate)

        # Sync to DailyAvailability so CMS Availability Calendar shows the same price
        da_result = await self.session.exec(
            select(DailyAvailability).where(
                and_(
                    DailyAvailability.room_type_id == rec["room_type_id"],
                    DailyAvailability.date == rec_date_obj,
                )
            )
        )
        daily_record = da_result.first()
        if daily_record:
            daily_record.base_rate = round(new_rate, 2)
            daily_record.updated_at = datetime.utcnow()
        else:
            daily_record = DailyAvailability(
                room_type_id=rec["room_type_id"],
                date=rec_date_obj,
                total_rooms=room_type.total_rooms if hasattr(room_type, 'total_rooms') else 0,
                base_rate=round(new_rate, 2),
            )
            self.session.add(daily_record)

        # Create audit trail entry
        audit_entry = PricingAdjustments(
            name=f"AI Recommendation Accepted - {rec['room_type_name']}",
            adjustment_type="fixed_amount",
            adjustment_value=new_rate,
            applies_to="room_type",
            entity_id=str(rec["room_type_id"]),
            priority=1,
            valid_from=rec_date_obj,
            valid_to=rec_date_obj,
            is_active=True
        )
        self.session.add(audit_entry)
        await self.session.commit()
        await self.session.refresh(audit_entry)

        return {
            "success": True,
            "recommendation_id": recommendation_id or 0,
            "applied_rate": round(new_rate, 2),
            "room_type_id": rec["room_type_id"],
            "date": rec["date"],
            "audit_id": audit_entry.id,
            "message": f"Rate updated to ${new_rate:.2f} for {rec['room_type_name']} on {rec['date']}"
        }

    async def dismiss_pricing_recommendation(
        self,
        recommendation_id: int,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Dismiss a pricing recommendation without applying it."""
        # In production, this would mark the recommendation as dismissed in the database
        return {
            "success": True,
            "recommendation_id": recommendation_id,
            "message": f"Recommendation {recommendation_id} dismissed" + (f": {reason}" if reason else "")
        }

    async def apply_all_recommendations(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_confidence: float = 80.0
    ) -> Dict[str, Any]:
        """Apply all recommendations that meet the confidence threshold."""
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today() + timedelta(days=7)

        recommendations = await self.get_pricing_recommendations(start_date, end_date)

        applied_count = 0
        failed_count = 0
        total_impact = 0.0
        results = []

        for idx, rec in enumerate(recommendations):
            if rec.get("confidence", 0) >= min_confidence:
                try:
                    result = await self.accept_pricing_recommendation(idx)
                    applied_count += 1
                    total_impact += abs(rec["recommended_rate"] - rec["current_rate"])
                    results.append({
                        "recommendation_id": idx,
                        "status": "applied",
                        "rate": result["applied_rate"]
                    })
                except Exception as e:
                    failed_count += 1
                    results.append({
                        "recommendation_id": idx,
                        "status": "failed",
                        "error": str(e)
                    })

        return {
            "success": True,
            "applied_count": applied_count,
            "failed_count": failed_count,
            "total_revenue_impact": round(total_impact * 10, 2),
            "results": results
        }

    async def dismiss_all_recommendations(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Dismiss all recommendations for the specified period."""
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today() + timedelta(days=7)

        recommendations = await self.get_pricing_recommendations(start_date, end_date)
        dismissed_count = len(recommendations)

        return {
            "success": True,
            "dismissed_count": dismissed_count,
            "message": f"Dismissed {dismissed_count} recommendations" + (f": {reason}" if reason else "")
        }

    # ==================== RATE MANAGEMENT ====================

    async def update_single_rate(
        self,
        room_type_id: int,
        rate_date: date,
        new_rate: float,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update the rate for a specific room type on a specific date."""
        # Get room type
        room_type_result = await self.session.exec(
            select(RoomType).where(RoomType.id == room_type_id)
        )
        room_type = room_type_result.first()
        if not room_type:
            raise ValueError(f"Room type {room_type_id} not found")

        # Get auto-pricing config for bounds validation
        config = await self.get_auto_pricing_config()
        base_rate = float(room_type.base_price or 0)
        min_rate = base_rate * (1 + config.get("min_rate_adjustment", -30) / 100)
        max_rate = base_rate * (1 + config.get("max_rate_adjustment", 50) / 100)

        # Validate rate bounds
        if new_rate < min_rate:
            raise ValueError(f"Rate ${new_rate:.2f} is below minimum allowed (${min_rate:.2f})")
        if new_rate > max_rate:
            raise ValueError(f"Rate ${new_rate:.2f} is above maximum allowed (${max_rate:.2f})")

        # Resolve BAR rate plan for DailyRate persistence (Rate Calendar uses BAR)
        bar_plan_result = await self.session.exec(
            select(RatePlan).where(RatePlan.code == "BAR").limit(1)
        )
        bar_plan = bar_plan_result.first()

        # Get current effective rate (from DailyRate override if any) for accurate audit
        existing_daily = None
        if bar_plan:
            daily_rate_result = await self.session.exec(
                select(DailyRate).where(
                    and_(
                        DailyRate.room_type_id == room_type_id,
                        DailyRate.rate_plan_id == bar_plan.id,
                        DailyRate.date == rate_date
                    )
                ).limit(1)
            )
            existing_daily = daily_rate_result.first()
        previous_rate = float(existing_daily.override_rate or existing_daily.base_rate) if existing_daily else base_rate
        change_percent = ((new_rate - previous_rate) / previous_rate * 100) if previous_rate > 0 else 0

        # Create pricing adjustment entry
        adjustment = PricingAdjustments(
            name=f"Manual Rate Update - {room_type.name}",
            adjustment_type="fixed_amount",
            adjustment_value=new_rate,
            applies_to="room_type",
            entity_id=str(room_type_id),
            condition_type="date",
            priority=1,
            valid_from=rate_date,
            valid_to=rate_date,
            is_active=True
        )
        self.session.add(adjustment)

        # Persist to DailyRate so Rate Calendar (channel manager and inventory) shows the update
        if bar_plan:
            if existing_daily:
                existing_daily.override_rate = new_rate
                existing_daily.updated_at = datetime.utcnow()
            else:
                daily_rate = DailyRate(
                    room_type_id=room_type_id,
                    rate_plan_id=bar_plan.id,
                    date=rate_date,
                    base_rate=base_rate,
                    override_rate=new_rate,
                )
                self.session.add(daily_rate)

        # Sync to DailyAvailability so CMS Availability Calendar and room views show the same price
        _da_result = await self.session.exec(
            select(DailyAvailability).where(
                and_(
                    DailyAvailability.room_type_id == room_type_id,
                    DailyAvailability.date == rate_date,
                )
            ).limit(1)
        )
        daily_avail = _da_result.first()
        if daily_avail:
            daily_avail.base_rate = new_rate
            daily_avail.updated_at = datetime.utcnow()
        else:
            _room_count = await self.session.exec(
                select(func.count(Room.id)).where(Room.room_type_id == room_type_id)
            )
            total_rooms = _room_count.one() or 0
            daily_avail = DailyAvailability(
                room_type_id=room_type_id,
                date=rate_date,
                total_rooms=total_rooms,
                available=total_rooms,
                base_rate=new_rate,
            )
            self.session.add(daily_avail)

        await self.session.commit()
        await self.session.refresh(adjustment)

        return {
            "success": True,
            "room_type_id": room_type_id,
            "date": rate_date.isoformat(),
            "previous_rate": round(previous_rate, 2),
            "new_rate": round(new_rate, 2),
            "change_percent": round(change_percent, 1),
            "audit_id": adjustment.id,
            "message": f"Rate updated from ${previous_rate:.2f} to ${new_rate:.2f}" + (f" - {reason}" if reason else "")
        }

    async def bulk_update_rates(
        self,
        updates: List[Any],
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Bulk update multiple rates.

        Unlike single-rate updates, bulk operations clamp each rate to the
        allowed min/max bounds instead of rejecting it outright.  This avoids
        partial failures when a flat adjustment pushes some room types outside
        their configured range.
        """
        updated_count = 0
        failed_count = 0
        audit_ids = []
        results = []

        # Pre-fetch pricing config once (used for clamping)
        config = await self.get_auto_pricing_config()

        for update in updates:
            try:
                # Clamp rate to allowed bounds for the room type
                rt_result = await self.session.exec(
                    select(RoomType).where(RoomType.id == update.room_type_id)
                )
                rt = rt_result.first()
                if not rt:
                    raise ValueError(f"Room type {update.room_type_id} not found")

                base_rate = float(rt.base_price or 0)
                min_rate = base_rate * (1 + config.get("min_rate_adjustment", -30) / 100)
                max_rate = base_rate * (1 + config.get("max_rate_adjustment", 50) / 100)
                clamped_rate = max(min_rate, min(max_rate, update.rate))

                result = await self.update_single_rate(
                    room_type_id=update.room_type_id,
                    rate_date=update.date,
                    new_rate=round(clamped_rate, 2),
                    reason=reason
                )
                updated_count += 1
                audit_ids.append(result["audit_id"])
                results.append({
                    "room_type_id": update.room_type_id,
                    "date": update.date.isoformat(),
                    "status": "success",
                    "new_rate": result["new_rate"]
                })
            except Exception as e:
                failed_count += 1
                results.append({
                    "room_type_id": update.room_type_id,
                    "date": update.date.isoformat(),
                    "status": "failed",
                    "error": str(e)
                })

        return {
            "success": failed_count == 0,
            "updated_count": updated_count,
            "failed_count": failed_count,
            "audit_ids": audit_ids,
            "results": results
        }

    async def get_rate_calendar(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        room_type_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get rate calendar data for visualization."""
        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today() + timedelta(days=30)

        # Get room types
        room_types_query = select(RoomType).where(RoomType.is_active == True)
        if room_type_id:
            room_types_query = room_types_query.where(RoomType.id == room_type_id)

        result = await self.session.exec(room_types_query)
        room_types = result.all()
        room_type_ids = [rt.id for rt in room_types]

        # Load stored rate overrides (DailyRate) so calendar reflects bulk/single updates and pricing rule execution
        # Prefer BAR plan; then fill any (room_type_id, date) from other plans so rule-applied rates always show
        stored_rates: Dict[tuple, float] = {}  # (room_type_id, date_str) -> rate
        if room_type_ids:
            bar_plan_result = await self.session.exec(
                select(RatePlan).where(RatePlan.code == "BAR").limit(1)
            )
            bar_plan = bar_plan_result.first()
            dr_query = select(DailyRate).where(
                and_(
                    DailyRate.room_type_id.in_(room_type_ids),
                    DailyRate.date >= start_date,
                    DailyRate.date <= end_date
                )
            )
            dr_result = await self.session.exec(dr_query)
            all_drs = dr_result.all()
            for dr in all_drs:
                key = (dr.room_type_id, dr.date.isoformat())
                rate = float(dr.override_rate or dr.base_rate)
                if bar_plan and dr.rate_plan_id == bar_plan.id:
                    stored_rates[key] = rate
            for dr in all_drs:
                key = (dr.room_type_id, dr.date.isoformat())
                if key not in stored_rates:
                    stored_rates[key] = float(dr.override_rate or dr.base_rate)

        # Get demand forecast
        forecasts = await self.get_demand_forecast(start_date, end_date)
        forecast_by_date = {f["date"]: f for f in forecasts}

        # Get events
        from app.models.rms import MarketEvent
        events_result = await self.session.exec(
            select(MarketEvent).where(
                and_(
                    MarketEvent.start_date <= end_date,
                    MarketEvent.end_date >= start_date
                )
            )
        )
        events = events_result.all()

        # Map events to dates
        event_dates = {}
        for event in events:
            current = event.start_date
            while current <= event.end_date:
                if start_date <= current <= end_date:
                    event_dates[current.isoformat()] = event.event_name
                current += timedelta(days=1)

        # Get total room counts per room type for availability display
        room_counts: Dict[int, int] = {}
        if room_type_ids:
            for rt_id in room_type_ids:
                count_result = await self.session.exec(
                    select(func.count(Room.id)).where(
                        Room.room_type_id == rt_id,
                        Room.status.in_(["available", "clean", "inspected", "occupied", "dirty"])
                    )
                )
                room_counts[rt_id] = count_result.one() or 0

        calendar = []
        total_revenue = 0
        avg_occupancy = 0

        for room_type in room_types:
            base_rate = float(room_type.base_price or 0)
            total_rooms = room_counts.get(room_type.id, 0)
            current_date = start_date

            while current_date <= end_date:
                date_str = current_date.isoformat()
                forecast = forecast_by_date.get(date_str, {})
                occupancy = forecast.get("forecasted_occupancy", 70)
                demand_level = forecast.get("demand_level", "moderate")

                # Use stored override (from bulk/single update) when present; else demand-based
                stored_key = (room_type.id, date_str)
                if stored_key in stored_rates:
                    effective_rate = stored_rates[stored_key]
                else:
                    demand_multiplier = self._get_demand_multiplier(demand_level)
                    effective_rate = base_rate * demand_multiplier

                has_event = date_str in event_dates
                available_rooms = max(0, round(total_rooms * (1 - occupancy / 100)))

                calendar.append({
                    "date": date_str,
                    "room_type_id": room_type.id,
                    "room_type_name": room_type.name,
                    "base_rate": round(base_rate, 2),
                    "effective_rate": round(effective_rate, 2),
                    "occupancy": round(occupancy, 1),
                    "demand_level": demand_level,
                    "has_event": has_event,
                    "event_name": event_dates.get(date_str),
                    "available": available_rooms
                })

                total_revenue += effective_rate * (occupancy / 100)
                avg_occupancy += occupancy
                current_date += timedelta(days=1)

        days_count = (end_date - start_date).days + 1
        avg_occupancy = avg_occupancy / (len(room_types) * days_count) if room_types and days_count > 0 else 0

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "calendar": calendar,
            "summary": {
                "total_projected_revenue": round(total_revenue, 2),
                "average_occupancy": round(avg_occupancy, 1),
                "days_with_events": len(event_dates),
                "room_types_count": len(room_types)
            }
        }

    # ==================== PRICING RULES CRUD ====================

    async def list_pricing_rules(
        self,
        is_active: Optional[bool] = None,
        room_type_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """List all pricing rules with optional filtering."""
        from app.models.rms import PricingRule

        query = select(PricingRule)
        if is_active is not None:
            query = query.where(PricingRule.is_active == is_active)
        if room_type_id is not None:
            # Filter rules that apply to this room type or to all room types (None or "ALL" or ID in list)
            query = query.where(
                or_(
                    PricingRule.room_types == None,
                    PricingRule.room_types.contains([room_type_id]),
                    PricingRule.room_types.contains(["ALL"]),
                )
            )

        query = query.order_by(PricingRule.priority)
        result = await self.session.exec(query)
        rules = result.all()

        # Get room type names
        room_types_result = await self.session.exec(select(RoomType))
        room_types = {rt.id: rt.name for rt in room_types_result.all()}

        rules_list = []
        for rule in rules:
            room_type_name = None
            if rule.room_types and len(rule.room_types) == 1:
                room_type_name = room_types.get(rule.room_types[0])

            rules_list.append({
                "id": rule.id,
                "rule_name": rule.rule_name,
                "description": rule.description,
                "room_type_id": rule.room_types[0] if rule.room_types and len(rule.room_types) == 1 else None,
                "room_type_name": room_type_name,
                "priority": rule.priority,
                "conditions": rule.conditions or [],
                "actions": rule.actions or [],
                "is_active": rule.is_active,
                "valid_from": None,
                "valid_to": None,
                "times_triggered": rule.times_triggered,
                "last_triggered_at": _serialize_utc_datetime(rule.last_triggered_at),
                "created_at": rule.created_at.isoformat()
            })

        return {
            "rules": rules_list,
            "total": len(rules_list),
            "active_count": len([r for r in rules_list if r["is_active"]])
        }

    async def create_pricing_rule(self, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new pricing rule."""
        from app.models.rms import PricingRule

        # Get default property_id
        from app.models.configuration import HotelSettings
        hotel_result = await self.session.exec(select(HotelSettings).limit(1))
        hotel = hotel_result.first()
        property_id = hotel.id if hotel else 1

        # Convert conditions and actions from Pydantic models to dicts
        conditions = [
            {"type": c["type"].value if hasattr(c["type"], "value") else c["type"],
             "operator": c["operator"],
             "value": c["value"]}
            for c in rule_data.get("conditions", [])
        ]
        actions = [
            {"type": a["type"].value if hasattr(a["type"], "value") else a["type"],
             "value": a["value"]}
            for a in rule_data.get("actions", [])
        ]

        rule = PricingRule(
            property_id=property_id,
            rule_name=rule_data["rule_name"],
            description=rule_data.get("description"),
            priority=rule_data.get("priority", 3),
            is_active=rule_data.get("is_active", True),
            room_types=[rule_data["room_type_id"]] if rule_data.get("room_type_id") else None,
            conditions=conditions,
            actions=actions
        )

        self.session.add(rule)
        await self.session.commit()
        await self.session.refresh(rule)

        # Get room type name if applicable
        room_type_name = None
        if rule_data.get("room_type_id"):
            rt_result = await self.session.exec(
                select(RoomType).where(RoomType.id == rule_data["room_type_id"])
            )
            rt = rt_result.first()
            room_type_name = rt.name if rt else None

        return {
            "id": rule.id,
            "rule_name": rule.rule_name,
            "description": rule.description,
            "room_type_id": rule_data.get("room_type_id"),
            "room_type_name": room_type_name,
            "priority": rule.priority,
            "conditions": conditions,
            "actions": actions,
            "is_active": rule.is_active,
            "valid_from": rule_data.get("valid_from").isoformat() if rule_data.get("valid_from") else None,
            "valid_to": rule_data.get("valid_to").isoformat() if rule_data.get("valid_to") else None,
            "times_triggered": 0,
            "last_triggered_at": None,
            "created_at": rule.created_at.isoformat()
        }

    async def get_pricing_rule(self, rule_id: int) -> Optional[Dict[str, Any]]:
        """Get a single pricing rule by ID."""
        from app.models.rms import PricingRule

        result = await self.session.exec(
            select(PricingRule).where(PricingRule.id == rule_id)
        )
        rule = result.first()
        if not rule:
            return None

        # Get room type name if applicable
        room_type_name = None
        room_type_id = None
        if rule.room_types and len(rule.room_types) > 0:
            room_type_id = rule.room_types[0]
            rt_result = await self.session.exec(
                select(RoomType).where(RoomType.id == room_type_id)
            )
            rt = rt_result.first()
            room_type_name = rt.name if rt else None

        return {
            "id": rule.id,
            "rule_name": rule.rule_name,
            "description": rule.description,
            "room_type_id": room_type_id,
            "room_type_name": room_type_name,
            "priority": rule.priority,
            "conditions": rule.conditions or [],
            "actions": rule.actions or [],
            "is_active": rule.is_active,
            "valid_from": None,
            "valid_to": None,
            "times_triggered": rule.times_triggered,
            "last_triggered_at": _serialize_utc_datetime(rule.last_triggered_at),
            "created_at": rule.created_at.isoformat()
        }

    async def update_pricing_rule(
        self,
        rule_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update an existing pricing rule."""
        from app.models.rms import PricingRule

        result = await self.session.exec(
            select(PricingRule).where(PricingRule.id == rule_id)
        )
        rule = result.first()
        if not rule:
            return None

        # Update fields
        if "rule_name" in update_data:
            rule.rule_name = update_data["rule_name"]
        if "description" in update_data:
            rule.description = update_data["description"]
        if "priority" in update_data:
            rule.priority = update_data["priority"]
        if "is_active" in update_data:
            rule.is_active = update_data["is_active"]
        if "room_type_id" in update_data:
            rule.room_types = [update_data["room_type_id"]] if update_data["room_type_id"] else None
        if "conditions" in update_data:
            rule.conditions = [
                {"type": c["type"].value if hasattr(c["type"], "value") else c["type"],
                 "operator": c["operator"],
                 "value": c["value"]}
                for c in update_data["conditions"]
            ]
        if "actions" in update_data:
            rule.actions = [
                {"type": a["type"].value if hasattr(a["type"], "value") else a["type"],
                 "value": a["value"]}
                for a in update_data["actions"]
            ]

        # Retry commit on SQLite "database is locked" (scheduler/other requests can hold brief locks)
        for attempt in range(4):
            try:
                await self.session.commit()
                break
            except OperationalError as e:
                if "locked" in str(e).lower() and attempt < 3:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise
        await self.session.refresh(rule)

        # Build response first so we always return 200 even if re-execute fails
        result = await self.get_pricing_rule(rule_id)

        # Re-execute pricing rules so room prices / rate calendar reflect the updated rule
        if rule.is_active:
            try:
                await self.execute_pricing_rules(
                    start_date=date.today(),
                    end_date=date.today() + timedelta(days=30),
                    dry_run=False,
                )
            except Exception as e:
                logger.warning("Re-execute pricing rules after update failed: %s", e, exc_info=True)

        return result

    async def delete_pricing_rule(self, rule_id: int) -> Optional[Dict[str, Any]]:
        """Delete a pricing rule. Returns rule info if found, None if not found."""
        from app.models.rms import PricingRule

        result = await self.session.exec(
            select(PricingRule).where(PricingRule.id == rule_id)
        )
        rule = result.first()
        if not rule:
            return None

        # Store rule name before deletion
        rule_name = rule.rule_name
        
        await self.session.delete(rule)
        await self.session.commit()
        
        return {
            "success": True,
            "rule_id": rule_id,
            "rule_name": rule_name
        }

    async def toggle_pricing_rule(self, rule_id: int) -> Optional[Dict[str, Any]]:
        """Toggle the active status of a pricing rule."""
        from app.models.rms import PricingRule

        try:
            result = await self.session.exec(
                select(PricingRule).where(PricingRule.id == rule_id)
            )
            rule = result.first()
            if not rule:
                return None

            rule.is_active = not rule.is_active
            # When activating a rule, set last_triggered_at so "last run" date updates in the UI
            if rule.is_active:
                rule.last_triggered_at = datetime.utcnow()
            await self.session.commit()
            await self.session.refresh(rule)

            return {
                "success": True,
                "rule_id": rule_id,
                "is_active": rule.is_active,
                "message": f"Rule {'activated' if rule.is_active else 'deactivated'} successfully"
            }
        except Exception as e:
            await self.session.rollback()
            raise

    async def execute_pricing_rules(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Execute all active pricing rules."""
        from app.models.rms import PricingRule

        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today() + timedelta(days=7)

        # Get active rules ordered by priority
        result = await self.session.exec(
            select(PricingRule).where(
                PricingRule.is_active == True
            ).order_by(PricingRule.priority)
        )
        rules = result.all()

        # Get forecasts for context
        forecasts = await self.get_demand_forecast(start_date, end_date)
        forecast_by_date = {f["date"]: f for f in forecasts}

        # Get room types
        room_types_result = await self.session.exec(select(RoomType).where(RoomType.is_active == True))
        room_types = room_types_result.all()

        # Resolve a rate plan for DailyRate persistence (rate calendar uses any DailyRate for room_type+date)
        # Prefer BAR; fallback to first rate plan so room prices always get updated
        bar_plan_result = await self.session.exec(
            select(RatePlan).where(RatePlan.code == "BAR").limit(1)
        )
        rate_plan_for_persistence = bar_plan_result.first()
        if not rate_plan_for_persistence:
            any_plan_result = await self.session.exec(select(RatePlan).limit(1))
            rate_plan_for_persistence = any_plan_result.first()

        executed_rules = 0
        total_rates_adjusted = 0
        total_revenue_impact = 0.0
        results = []

        for rule in rules:
            rates_adjusted = 0
            revenue_impact = 0.0

            for room_type in room_types:
                # Check if rule applies to this room type (None/empty/"ALL" = all room types; else IDs or slugs)
                if not self._rule_applies_to_room_type(rule, room_type):
                    continue

                current_date = start_date
                while current_date <= end_date:
                    date_str = current_date.isoformat()
                    forecast = forecast_by_date.get(date_str, {})

                    # Check all conditions
                    conditions_met = True
                    for condition in (rule.conditions or []):
                        if not self._evaluate_condition(condition, forecast, current_date):
                            conditions_met = False
                            break

                    if conditions_met:
                        # Apply actions
                        base_rate = float(room_type.base_price or 0)
                        new_rate = base_rate

                        for action in (rule.actions or []):
                            new_rate = self._apply_action(action, new_rate)

                        if not dry_run:
                            # Create pricing adjustment (audit trail)
                            adjustment = PricingAdjustments(
                                name=f"Rule: {rule.rule_name}",
                                adjustment_type="fixed_amount",
                                adjustment_value=new_rate,
                                applies_to="room_type",
                                entity_id=str(room_type.id),
                                priority=rule.priority,
                                valid_from=current_date,
                                valid_to=current_date,
                                is_active=True
                            )
                            self.session.add(adjustment)

                            # Persist to DailyRate so rate calendar and room prices reflect the rule.
                            # Calendar fetches by (room_type_id, date) with limit(1), so we update ALL
                            # DailyRate rows for this room_type+date so whichever row is returned shows the new rate.
                            if rate_plan_for_persistence:
                                all_daily_rates_result = await self.session.exec(
                                    select(DailyRate).where(
                                        and_(
                                            DailyRate.room_type_id == room_type.id,
                                            DailyRate.date == current_date
                                        )
                                    )
                                )
                                existing_daily_list = all_daily_rates_result.all()
                                if existing_daily_list:
                                    for dr in existing_daily_list:
                                        dr.override_rate = new_rate
                                        dr.updated_at = datetime.utcnow()
                                else:
                                    daily_rate = DailyRate(
                                        room_type_id=room_type.id,
                                        rate_plan_id=rate_plan_for_persistence.id,
                                        date=current_date,
                                        base_rate=base_rate,
                                        override_rate=new_rate,
                                    )
                                    self.session.add(daily_rate)

                            # Also update DailyAvailability.base_rate so inventory availability grid shows the new rate
                            da_result = await self.session.exec(
                                select(DailyAvailability).where(
                                    and_(
                                        DailyAvailability.room_type_id == room_type.id,
                                        DailyAvailability.date == current_date
                                    )
                                ).limit(1)
                            )
                            daily_avail = da_result.first()
                            if daily_avail:
                                daily_avail.base_rate = new_rate
                                daily_avail.updated_at = datetime.utcnow()
                            else:
                                daily_avail_new = DailyAvailability(
                                    room_type_id=room_type.id,
                                    date=current_date,
                                    total_rooms=0,
                                    sold=0,
                                    blocked=0,
                                    available=0,
                                    base_rate=new_rate,
                                )
                                self.session.add(daily_avail_new)

                        rates_adjusted += 1
                        revenue_impact += abs(new_rate - base_rate)

                    current_date += timedelta(days=1)

            if rates_adjusted > 0:
                executed_rules += 1
                total_rates_adjusted += rates_adjusted
                total_revenue_impact += revenue_impact

                # Update rule trigger count
                if not dry_run:
                    rule.times_triggered += 1
                    rule.last_triggered_at = datetime.now()

                results.append({
                    "rule_id": rule.id,
                    "rule_name": rule.rule_name,
                    "rates_adjusted": rates_adjusted,
                    "revenue_impact": round(revenue_impact, 2),
                    "status": "executed" if not dry_run else "preview",
                    "message": f"{'Would adjust' if dry_run else 'Adjusted'} {rates_adjusted} rates"
                })

        if not dry_run:
            await self.session.commit()

        return {
            "success": True,
            "executed_rules": executed_rules,
            "total_rates_adjusted": total_rates_adjusted,
            "total_revenue_impact": round(total_revenue_impact, 2),
            "results": results
        }

    def _rule_applies_to_room_type(self, rule: Any, room_type: Any) -> bool:
        """Return True if this rule applies to the given room type (room_types: None/empty/ALL = all; else IDs or slugs)."""
        rts = rule.room_types
        if not rts or len(rts) == 0:
            return True
        if any(str(x).upper() == "ALL" for x in (rts or [])):
            return True
        for rt in rts:
            if rt == room_type.id:
                return True
            if isinstance(rt, str) and getattr(room_type, "slug", None) == rt:
                return True
        return False

    def _evaluate_condition(
        self,
        condition: Dict[str, Any],
        forecast: Dict[str, Any],
        current_date: date
    ) -> bool:
        """Evaluate a single rule condition."""
        cond_type = condition.get("type")
        operator = condition.get("operator")
        value = condition.get("value")

        if cond_type == "demand_level":
            actual = forecast.get("demand_level", "moderate")
            if operator == "eq":
                return actual == value
            elif operator == "in":
                return actual in value
        elif cond_type in ("occupancy", "occupancy_above", "occupancy_below"):
            actual = forecast.get("forecasted_occupancy", 70)
            if cond_type == "occupancy_above":
                op = operator if operator in ("gt", "gte", "eq") else "gte"
                return self._compare_values(actual, op, value)
            if cond_type == "occupancy_below":
                op = operator if operator in ("lt", "lte", "eq") else "lte"
                return self._compare_values(actual, op, value)
            return self._compare_values(actual, operator, value)
        elif cond_type == "day_of_week":
            actual = current_date.weekday()
            if operator == "eq":
                return actual == value
            elif operator == "in":
                return actual in value
        elif cond_type == "lead_time":
            actual = (current_date - date.today()).days
            return self._compare_values(actual, operator, value)

        return True

    def _compare_values(self, actual: float, operator: str, value: float) -> bool:
        """Compare values using the specified operator."""
        if operator == "eq":
            return actual == value
        elif operator == "ne":
            return actual != value
        elif operator == "gt":
            return actual > value
        elif operator == "lt":
            return actual < value
        elif operator == "gte":
            return actual >= value
        elif operator == "lte":
            return actual <= value
        return False

    def _apply_action(self, action: Dict[str, Any], current_rate: float) -> float:
        """Apply a pricing action to a rate."""
        action_type = action.get("type")
        if hasattr(action_type, "value"):
            action_type = action_type.value
        try:
            value = float(action.get("value", 0) or 0)
        except (TypeError, ValueError):
            value = 0.0

        if action_type == "adjust_percent":
            return current_rate * (1 + value / 100)
        elif action_type == "set_rate":
            return value
        elif action_type == "set_min_rate":
            return max(current_rate, value)
        elif action_type == "multiply_by":
            return current_rate * value

        return current_rate

    # ==================== AUTO-PRICING SETTINGS ====================

    async def get_auto_pricing_config(self) -> Dict[str, Any]:
        """Get auto-pricing configuration."""
        from app.models.configuration import SystemSettings

        # Try to get from system settings
        result = await self.session.exec(
            select(SystemSettings).where(
                SystemSettings.setting_key == "auto_pricing_config"
            )
        )
        setting = result.first()

        if setting and setting.setting_value:
            import json
            try:
                return json.loads(setting.setting_value)
            except json.JSONDecodeError:
                pass

        # Return default config
        return {
            "enabled": False,
            "min_rate_adjustment": -30,
            "max_rate_adjustment": 50,
            "auto_accept_threshold": 5,
            "competitor_weight": 0.3,
            "demand_weight": 0.5,
            "historical_weight": 0.2,
            "room_type_overrides": None,
            "update_frequency": "daily",
            "last_run": None
        }

    async def update_auto_pricing_config(
        self,
        update_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update auto-pricing configuration."""
        from app.models.configuration import SystemSettings
        import json

        current_config = await self.get_auto_pricing_config()

        # Merge updates
        for key, value in update_data.items():
            if value is not None:
                current_config[key] = value

        # Validate weights sum to 1
        total_weight = (
            current_config.get("competitor_weight", 0) +
            current_config.get("demand_weight", 0) +
            current_config.get("historical_weight", 0)
        )
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0 (current: {total_weight})")

        # Save to system settings
        result = await self.session.exec(
            select(SystemSettings).where(
                SystemSettings.setting_key == "auto_pricing_config"
            )
        )
        setting = result.first()

        if setting:
            setting.setting_value = json.dumps(current_config)
            setting.updated_at = datetime.now()
        else:
            setting = SystemSettings(
                setting_key="auto_pricing_config",
                setting_value=json.dumps(current_config),
                setting_type="json",
                category="revenue_intelligence",
                description="Auto-pricing configuration"
            )
            self.session.add(setting)

        await self.session.commit()
        return current_config

    async def toggle_auto_pricing(
        self,
        enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Toggle auto-pricing on or off."""
        config = await self.get_auto_pricing_config()

        if enabled is None:
            enabled = not config.get("enabled", False)

        await self.update_auto_pricing_config({"enabled": enabled})

        return {
            "success": True,
            "enabled": enabled,
            "message": f"Auto-pricing {'enabled' if enabled else 'disabled'}"
        }

    # ==================== COMPETITOR MANAGEMENT ====================

    async def list_competitors(
        self,
        is_active: Optional[bool] = None
    ) -> Dict[str, Any]:
        """List all tracked competitors."""
        from app.models.rms import Competitor

        query = select(Competitor)
        if is_active is not None:
            query = query.where(Competitor.is_active == is_active)

        result = await self.session.exec(query)
        competitors = result.all()

        competitors_list = [
            {
                "id": c.id,
                "name": c.name,
                "address": c.address,
                "star_rating": c.star_rating,
                "room_count": c.room_count,
                "distance_km": c.distance_km,
                "google_place_id": c.google_place_id,
                "booking_com_id": c.booking_com_id,
                "tripadvisor_id": c.tripadvisor_id,
                "is_active": c.is_active,
                "notes": c.notes,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat()
            }
            for c in competitors
        ]

        return {
            "competitors": competitors_list,
            "total": len(competitors_list)
        }

    async def add_competitor(
        self,
        competitor_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Add a new competitor."""
        from app.models.rms import Competitor
        from app.models.configuration import HotelSettings

        # Get default property_id
        hotel_result = await self.session.exec(select(HotelSettings).limit(1))
        hotel = hotel_result.first()
        property_id = hotel.id if hotel else 1

        competitor = Competitor(
            property_id=property_id,
            name=competitor_data["name"],
            address=competitor_data.get("address"),
            star_rating=competitor_data.get("star_rating"),
            room_count=competitor_data.get("room_count"),
            distance_km=competitor_data.get("distance_km"),
            google_place_id=competitor_data.get("google_place_id"),
            booking_com_id=competitor_data.get("booking_com_id"),
            tripadvisor_id=competitor_data.get("tripadvisor_id"),
            is_active=True,
            notes=competitor_data.get("notes")
        )

        self.session.add(competitor)
        await self.session.commit()
        await self.session.refresh(competitor)

        return {
            "id": competitor.id,
            "name": competitor.name,
            "address": competitor.address,
            "star_rating": competitor.star_rating,
            "room_count": competitor.room_count,
            "distance_km": competitor.distance_km,
            "google_place_id": competitor.google_place_id,
            "booking_com_id": competitor.booking_com_id,
            "tripadvisor_id": competitor.tripadvisor_id,
            "is_active": competitor.is_active,
            "notes": competitor.notes,
            "created_at": competitor.created_at.isoformat(),
            "updated_at": competitor.updated_at.isoformat()
        }

    async def remove_competitor(self, competitor_id: int) -> Dict[str, Any]:
        """Remove a competitor from tracking."""
        from app.models.rms import Competitor

        result = await self.session.exec(
            select(Competitor).where(Competitor.id == competitor_id)
        )
        competitor = result.first()

        if not competitor:
            return {
                "success": False,
                "competitor_id": competitor_id,
                "message": f"Competitor {competitor_id} not found"
            }

        await self.session.delete(competitor)
        await self.session.commit()

        return {
            "success": True,
            "competitor_id": competitor_id,
            "message": f"Competitor '{competitor.name}' removed successfully"
        }

    async def update_competitor(self, competitor_id: int, competitor_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing competitor."""
        from app.models.rms import Competitor

        result = await self.session.exec(
            select(Competitor).where(Competitor.id == competitor_id)
        )
        competitor = result.first()
        if not competitor:
            raise ValueError(f"Competitor {competitor_id} not found")

        allowed = {"name", "address", "star_rating", "room_count", "distance_km", "google_place_id", "booking_com_id", "tripadvisor_id", "is_active", "notes"}
        for key, value in competitor_data.items():
            if key in allowed and value is not None:
                setattr(competitor, key, value)
        competitor.updated_at = datetime.now()
        await self.session.commit()
        await self.session.refresh(competitor)

        return {
            "id": competitor.id,
            "name": competitor.name,
            "address": competitor.address,
            "star_rating": competitor.star_rating,
            "room_count": competitor.room_count,
            "distance_km": competitor.distance_km,
            "google_place_id": competitor.google_place_id,
            "booking_com_id": competitor.booking_com_id,
            "tripadvisor_id": competitor.tripadvisor_id,
            "is_active": competitor.is_active,
            "notes": competitor.notes,
            "created_at": competitor.created_at.isoformat(),
            "updated_at": competitor.updated_at.isoformat()
        }

    async def refresh_competitor_rates(
        self,
        competitor_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """Trigger competitor rate refresh."""
        from app.models.rms import Competitor, CompetitorRate
        from app.models.configuration import HotelSettings
        import random

        # Get property_id
        hotel_result = await self.session.exec(select(HotelSettings).limit(1))
        hotel = hotel_result.first()
        property_id = hotel.id if hotel else 1

        # Get competitors
        query = select(Competitor).where(Competitor.is_active == True)
        if competitor_ids:
            query = query.where(Competitor.id.in_(competitor_ids))

        result = await self.session.exec(query)
        competitors = result.all()

        rates_scraped = 0
        today = date.today()

        # Simulate rate scraping (in production, this would call external APIs)
        for competitor in competitors:
            for days_out in range(7):  # Scrape next 7 days
                rate_date = today + timedelta(days=days_out)

                # Generate simulated rate (in production, fetch from external source)
                base_rate = 150 + random.uniform(-30, 50)
                weekend_premium = 1.2 if rate_date.weekday() >= 5 else 1.0
                rate = base_rate * weekend_premium

                comp_rate = CompetitorRate(
                    property_id=property_id,
                    competitor_id=competitor.id,
                    rate_date=rate_date,
                    room_type="Standard",
                    rate_amount=round(rate, 2),
                    rate_source="booking_com",
                    currency="INR"
                )
                self.session.add(comp_rate)
                rates_scraped += 1

            # Update competitor timestamp
            competitor.updated_at = datetime.now()

        await self.session.commit()

        return {
            "success": True,
            "competitors_updated": len(competitors),
            "rates_scraped": rates_scraped,
            "last_refresh": datetime.now().isoformat(),
            "message": f"Refreshed rates for {len(competitors)} competitors"
        }

    async def get_competitor_rate_history(
        self,
        competitor_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Optional[Dict[str, Any]]:
        """Get historical rate data for a competitor."""
        from app.models.rms import Competitor, CompetitorRate

        # Get competitor
        comp_result = await self.session.exec(
            select(Competitor).where(Competitor.id == competitor_id)
        )
        competitor = comp_result.first()
        if not competitor:
            return None

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        # Get rates
        rates_result = await self.session.exec(
            select(CompetitorRate).where(
                and_(
                    CompetitorRate.competitor_id == competitor_id,
                    CompetitorRate.rate_date >= start_date,
                    CompetitorRate.rate_date <= end_date
                )
            ).order_by(CompetitorRate.rate_date)
        )
        rates = rates_result.all()

        rates_list = [
            {
                "date": r.rate_date.isoformat(),
                "room_type": r.room_type,
                "rate_amount": r.rate_amount,
                "rate_source": r.rate_source,
                "captured_at": r.captured_at.isoformat()
            }
            for r in rates
        ]

        # Calculate average and trend
        if rates:
            avg_rate = sum(r.rate_amount for r in rates) / len(rates)
            if len(rates) > 1:
                first_half = rates[:len(rates)//2]
                second_half = rates[len(rates)//2:]
                first_avg = sum(r.rate_amount for r in first_half) / len(first_half)
                second_avg = sum(r.rate_amount for r in second_half) / len(second_half)
                rate_trend = ((second_avg - first_avg) / first_avg * 100) if first_avg > 0 else 0
            else:
                rate_trend = 0
        else:
            avg_rate = 0
            rate_trend = 0

        return {
            "competitor_id": competitor_id,
            "competitor_name": competitor.name,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "rates": rates_list,
            "average_rate": round(avg_rate, 2),
            "rate_trend": round(rate_trend, 1)
        }

    # ==================== AI INSIGHTS ====================

    async def get_ai_insights(
        self,
        severity: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get AI-generated insights."""
        today = date.today()

        # Generate insights based on current data
        insights = []

        # Get demand forecast for insights
        forecasts = await self.get_demand_forecast(
            start_date=today,
            end_date=today + timedelta(days=14)
        )

        # Check for high demand days
        high_demand_days = [f for f in forecasts if f["demand_level"] in ["high", "critical"]]
        for forecast in high_demand_days[:3]:
            insights.append({
                "id": f"demand_{forecast['date']}",
                "type": "demand_spike",
                "severity": "warning" if forecast["demand_level"] == "high" else "critical",
                "title": f"High Demand Predicted - {forecast['date']}",
                "message": f"Occupancy forecasted at {forecast['forecasted_occupancy']:.0f}% with {forecast['demand_level']} demand.",
                "recommendation": "Consider increasing rates by 15-25% to maximize revenue.",
                "potential_impact": round(1000 * forecast['forecasted_occupancy'] / 100, 2),
                "confidence": forecast["confidence_level"],
                "data": {"forecast": forecast},
                "is_read": False,
                "is_dismissed": False,
                "created_at": datetime.now().isoformat()
            })

        # Check for low demand days
        low_demand_days = [f for f in forecasts if f["demand_level"] in ["low", "very_low"]]
        for forecast in low_demand_days[:2]:
            insights.append({
                "id": f"low_demand_{forecast['date']}",
                "type": "low_demand",
                "severity": "info",
                "title": f"Low Demand Expected - {forecast['date']}",
                "message": f"Occupancy forecasted at only {forecast['forecasted_occupancy']:.0f}%.",
                "recommendation": "Consider promotional offers or rate reductions to stimulate demand.",
                "potential_impact": round(500 * (100 - forecast['forecasted_occupancy']) / 100, 2),
                "confidence": forecast["confidence_level"],
                "data": {"forecast": forecast},
                "is_read": False,
                "is_dismissed": False,
                "created_at": datetime.now().isoformat()
            })

        # Add competitor insight
        insights.append({
            "id": "competitor_price_change",
            "type": "competitor_movement",
            "severity": "info",
            "title": "Competitor Rate Change Detected",
            "message": "A competitor has lowered rates by 8% for next weekend.",
            "recommendation": "Monitor booking pace and consider adjusting if occupancy drops.",
            "potential_impact": 1200.00,
            "confidence": 75,
            "data": None,
            "is_read": False,
            "is_dismissed": False,
            "created_at": datetime.now().isoformat()
        })

        # Filter by severity
        if severity:
            insights = [i for i in insights if i["severity"] == severity]

        # Filter unread
        if unread_only:
            insights = [i for i in insights if not i["is_read"]]

        # Limit results
        insights = insights[:limit]

        return {
            "insights": insights,
            "unread_count": len([i for i in insights if not i["is_read"]]),
            "critical_count": len([i for i in insights if i["severity"] == "critical"]),
            "generated_at": datetime.now().isoformat()
        }

    async def dismiss_ai_insight(self, insight_id: str) -> Dict[str, Any]:
        """Dismiss an AI insight."""
        # In production, this would update a database record
        return {
            "success": True,
            "insight_id": insight_id,
            "message": f"Insight {insight_id} dismissed"
        }

    async def mark_insight_read(self, insight_id: str) -> Dict[str, Any]:
        """Mark an AI insight as read."""
        # In production, this would update a database record
        return {
            "success": True,
            "insight_id": insight_id,
            "message": f"Insight {insight_id} marked as read"
        }

    # ==================== SEGMENTS ====================

    async def get_segment_performance(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Get revenue performance by market segment."""
        from app.models.rms import SegmentPerformance

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        result = await self.session.exec(
            select(SegmentPerformance).where(
                and_(
                    SegmentPerformance.period_month >= start_date,
                    SegmentPerformance.period_month <= end_date
                )
            )
        )
        segment_data = result.all()

        # Aggregate by segment
        segments_agg = {}
        for seg in segment_data:
            if seg.segment_name not in segments_agg:
                segments_agg[seg.segment_name] = {
                    "segment_name": seg.segment_name,
                    "segment_id": seg.segment_id,
                    "revenue": 0,
                    "room_nights": 0,
                    "bookings": 0,
                    "cancellations": 0,
                    "lead_times": [],
                    "los": []
                }

            segments_agg[seg.segment_name]["revenue"] += seg.revenue
            segments_agg[seg.segment_name]["room_nights"] += seg.room_nights
            segments_agg[seg.segment_name]["bookings"] += seg.bookings
            segments_agg[seg.segment_name]["cancellations"] += seg.cancellations
            if seg.avg_lead_time_days:
                segments_agg[seg.segment_name]["lead_times"].append(seg.avg_lead_time_days)
            if seg.avg_los:
                segments_agg[seg.segment_name]["los"].append(seg.avg_los)

        # Calculate metrics
        total_revenue = sum(s["revenue"] for s in segments_agg.values())
        segments_list = []
        top_performer = ""
        max_revenue = 0

        for seg_name, data in segments_agg.items():
            adr = data["revenue"] / data["room_nights"] if data["room_nights"] > 0 else 0
            avg_lead_time = sum(data["lead_times"]) / len(data["lead_times"]) if data["lead_times"] else 0
            avg_los = sum(data["los"]) / len(data["los"]) if data["los"] else 0
            cancel_rate = (data["cancellations"] / data["bookings"] * 100) if data["bookings"] > 0 else 0
            revenue_pct = (data["revenue"] / total_revenue * 100) if total_revenue > 0 else 0

            if data["revenue"] > max_revenue:
                max_revenue = data["revenue"]
                top_performer = seg_name

            segments_list.append({
                "segment_name": seg_name,
                "segment_id": data["segment_id"],
                "revenue": round(data["revenue"], 2),
                "room_nights": data["room_nights"],
                "bookings": data["bookings"],
                "adr": round(adr, 2),
                "revpar": round(data["revenue"] / (data["room_nights"] or 1), 2),
                "revenue_contribution_pct": round(revenue_pct, 1),
                "avg_lead_time_days": round(avg_lead_time, 1),
                "avg_los": round(avg_los, 1),
                "cancellation_rate": round(cancel_rate, 1),
                "yoy_variance_pct": None
            })

        # If no data, generate sample segments
        if not segments_list:
            sample_segments = [
                {"name": "Leisure", "revenue": 45000, "nights": 300},
                {"name": "Business", "revenue": 38000, "nights": 200},
                {"name": "Corporate", "revenue": 25000, "nights": 150},
                {"name": "Group", "revenue": 18000, "nights": 180},
                {"name": "OTA", "revenue": 32000, "nights": 220}
            ]
            total_revenue = sum(s["revenue"] for s in sample_segments)
            top_performer = "Leisure"

            for seg in sample_segments:
                adr = seg["revenue"] / seg["nights"]
                segments_list.append({
                    "segment_name": seg["name"],
                    "segment_id": None,
                    "revenue": seg["revenue"],
                    "room_nights": seg["nights"],
                    "bookings": seg["nights"] // 2,
                    "adr": round(adr, 2),
                    "revpar": round(adr * 0.75, 2),
                    "revenue_contribution_pct": round(seg["revenue"] / total_revenue * 100, 1),
                    "avg_lead_time_days": 14,
                    "avg_los": 2.5,
                    "cancellation_rate": 8.5,
                    "yoy_variance_pct": 5.2
                })

        # Sort by revenue
        segments_list.sort(key=lambda x: x["revenue"], reverse=True)

        # Generate recommendations
        recommendations = []
        for seg in segments_list:
            if seg["cancellation_rate"] > 15:
                recommendations.append(f"High cancellation rate in {seg['segment_name']} segment. Consider tighter policies.")
            if seg["avg_lead_time_days"] < 7 and seg["revenue_contribution_pct"] > 20:
                recommendations.append(f"{seg['segment_name']} has short lead times. Consider early bird incentives.")

        if not recommendations:
            recommendations.append(f"Focus marketing efforts on {top_performer} segment for highest ROI.")

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "segments": segments_list,
            "totals": {
                "total_revenue": round(total_revenue, 2),
                "total_bookings": sum(s["bookings"] for s in segments_list),
                "total_room_nights": sum(s["room_nights"] for s in segments_list)
            },
            "top_performer": top_performer,
            "recommendations": recommendations
        }

    # ==================== EVENTS ====================

    async def list_events(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        event_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """List market events."""
        from app.models.rms import MarketEvent

        query = select(MarketEvent)

        if start_date:
            query = query.where(MarketEvent.end_date >= start_date)
        if end_date:
            query = query.where(MarketEvent.start_date <= end_date)
        if event_type:
            query = query.where(MarketEvent.event_type == event_type)

        query = query.order_by(MarketEvent.start_date)

        result = await self.session.exec(query)
        events = result.all()

        today = date.today()
        events_list = [
            {
                "id": e.id,
                "event_name": e.event_name,
                "event_type": e.event_type,
                "start_date": e.start_date.isoformat(),
                "end_date": e.end_date.isoformat(),
                "impact_multiplier": e.impact_multiplier,
                "is_recurring": e.is_recurring,
                "recurrence_rule": e.recurrence_rule,
                "notes": e.notes,
                "created_at": e.created_at.isoformat()
            }
            for e in events
        ]

        upcoming_count = len([e for e in events if e.start_date >= today])

        return {
            "events": events_list,
            "total": len(events_list),
            "upcoming_count": upcoming_count
        }

    async def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new market event."""
        from app.models.rms import MarketEvent
        from app.models.configuration import HotelSettings

        # Validate dates
        if event_data["end_date"] < event_data["start_date"]:
            raise ValueError("End date must be after start date")

        # Get property_id
        hotel_result = await self.session.exec(select(HotelSettings).limit(1))
        hotel = hotel_result.first()
        property_id = hotel.id if hotel else 1

        event = MarketEvent(
            property_id=property_id,
            event_name=event_data["event_name"],
            event_type=event_data["event_type"].value if hasattr(event_data["event_type"], "value") else event_data["event_type"],
            start_date=event_data["start_date"],
            end_date=event_data["end_date"],
            impact_multiplier=event_data.get("impact_multiplier", 1.0),
            is_recurring=event_data.get("is_recurring", False),
            recurrence_rule=event_data.get("recurrence_rule"),
            notes=event_data.get("notes")
        )

        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)

        return {
            "id": event.id,
            "event_name": event.event_name,
            "event_type": event.event_type,
            "start_date": event.start_date.isoformat(),
            "end_date": event.end_date.isoformat(),
            "impact_multiplier": event.impact_multiplier,
            "is_recurring": event.is_recurring,
            "recurrence_rule": event.recurrence_rule,
            "notes": event.notes,
            "created_at": event.created_at.isoformat()
        }

    async def update_event(self, event_id: int, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing market event."""
        from app.models.rms import MarketEvent

        result = await self.session.exec(
            select(MarketEvent).where(MarketEvent.id == event_id)
        )
        event = result.first()
        if not event:
            raise ValueError(f"Event with ID {event_id} not found")

        allowed = {"event_name", "event_type", "start_date", "end_date", "impact_multiplier", "is_recurring", "recurrence_rule", "notes"}
        for key, value in event_data.items():
            if key not in allowed or value is None:
                continue
            if key in ("start_date", "end_date") and isinstance(value, str):
                value = date.fromisoformat(value)
            if hasattr(event, key):
                setattr(event, key, value)

        if "end_date" in event_data and "start_date" in event_data:
            if event.end_date < event.start_date:
                raise ValueError("End date must be after start date")

        await self.session.commit()
        await self.session.refresh(event)

        return {
            "id": event.id,
            "event_name": event.event_name,
            "event_type": event.event_type,
            "start_date": event.start_date.isoformat(),
            "end_date": event.end_date.isoformat(),
            "impact_multiplier": event.impact_multiplier,
            "is_recurring": event.is_recurring,
            "recurrence_rule": event.recurrence_rule,
            "notes": event.notes,
            "created_at": event.created_at.isoformat()
        }

    async def delete_event(self, event_id: int) -> None:
        """Delete a market event by ID."""
        from app.models.rms import MarketEvent

        result = await self.session.exec(
            select(MarketEvent).where(MarketEvent.id == event_id)
        )
        event = result.first()
        if not event:
            raise ValueError(f"Event with ID {event_id} not found")

        await self.session.delete(event)
        await self.session.commit()

    async def get_event_calendar(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Get event calendar view."""
        from app.models.rms import MarketEvent

        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today() + timedelta(days=30)

        result = await self.session.exec(
            select(MarketEvent).where(
                and_(
                    MarketEvent.end_date >= start_date,
                    MarketEvent.start_date <= end_date
                )
            )
        )
        events = result.all()

        # Map events to dates
        calendar = []
        current_date = start_date
        events_in_period = set()

        while current_date <= end_date:
            date_events = []
            combined_impact = 1.0

            for event in events:
                if event.start_date <= current_date <= event.end_date:
                    date_events.append({
                        "id": event.id,
                        "name": event.event_name,
                        "type": event.event_type,
                        "impact": event.impact_multiplier
                    })
                    combined_impact *= event.impact_multiplier
                    events_in_period.add(event.id)

            calendar.append({
                "date": current_date.isoformat(),
                "events": date_events,
                "combined_impact": round(combined_impact, 2)
            })

            current_date += timedelta(days=1)

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "calendar": calendar,
            "events_in_period": len(events_in_period)
        }

    async def get_event_demand_impact(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Get demand impact analysis for events."""
        from app.models.rms import MarketEvent

        if not start_date:
            start_date = date.today()
        if not end_date:
            end_date = date.today() + timedelta(days=90)

        result = await self.session.exec(
            select(MarketEvent).where(
                and_(
                    MarketEvent.end_date >= start_date,
                    MarketEvent.start_date <= end_date
                )
            ).order_by(MarketEvent.start_date)
        )
        events = result.all()

        # Get baseline KPIs
        baseline_kpis = await self.get_realtime_kpis(start_date, end_date)
        daily_revenue = baseline_kpis["total_revenue"] / max((end_date - start_date).days, 1)

        events_impact = []
        total_opportunity = 0

        for event in events:
            days_duration = (event.end_date - event.start_date).days + 1
            demand_increase = (event.impact_multiplier - 1) * 100
            revenue_impact = daily_revenue * days_duration * (event.impact_multiplier - 1)
            rate_adjustment = max(0, (event.impact_multiplier - 1) * 100 * 0.8)  # 80% of demand increase

            total_opportunity += revenue_impact

            events_impact.append({
                "event_id": event.id,
                "event_name": event.event_name,
                "event_type": event.event_type,
                "start_date": event.start_date.isoformat(),
                "end_date": event.end_date.isoformat(),
                "days_duration": days_duration,
                "impact_multiplier": event.impact_multiplier,
                "estimated_demand_increase": round(demand_increase, 1),
                "estimated_revenue_impact": round(revenue_impact, 2),
                "recommended_rate_adjustment": round(rate_adjustment, 1)
            })

        recommendations = []
        if events_impact:
            high_impact = [e for e in events_impact if e["impact_multiplier"] >= 1.3]
            if high_impact:
                recommendations.append(f"Consider rate increases of 20-30% for {len(high_impact)} high-impact events")

            low_impact = [e for e in events_impact if e["impact_multiplier"] < 1.1]
            if low_impact:
                recommendations.append(f"Monitor {len(low_impact)} lower-impact events for actual booking pace")
        else:
            recommendations.append("No events detected in the selected period. Consider creating events for local activities.")

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "events": events_impact,
            "total_revenue_opportunity": round(total_opportunity, 2),
            "recommendations": recommendations
        }
