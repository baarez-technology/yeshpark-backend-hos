"""
ML Forecast Service
Provides machine learning-based demand forecasting, anomaly detection, and price elasticity analysis.
Uses statistical methods including exponential smoothing, trend analysis, and seasonality decomposition.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class DemandLevel(str, Enum):
    """Demand level categories."""
    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    VERY_LOW = "very_low"


class AnomalyType(str, Enum):
    """Types of anomalies detected in demand patterns."""
    SPIKE = "spike"
    DROP = "drop"
    UNUSUAL_PATTERN = "unusual_pattern"
    TREND_BREAK = "trend_break"


@dataclass
class ForecastPoint:
    """A single forecast data point."""
    date: date
    forecasted_demand: float
    forecasted_occupancy: float
    confidence_level: float
    lower_bound: float
    upper_bound: float
    demand_level: DemandLevel
    day_of_week: str
    is_weekend: bool
    seasonality_factor: float
    trend_component: float


@dataclass
class AnomalyResult:
    """Result of anomaly detection."""
    date: date
    anomaly_type: AnomalyType
    severity: str  # low, medium, high
    observed_value: float
    expected_value: float
    deviation_percent: float
    description: str


@dataclass
class ElasticityResult:
    """Price elasticity analysis result."""
    overall_elasticity: float
    elasticity_by_segment: Dict[str, float]
    optimal_price_range: Tuple[float, float]
    revenue_maximizing_price: float
    confidence: float
    interpretation: str


class MLForecastService:
    """
    Machine Learning-based forecasting service.
    Implements statistical forecasting methods without requiring external ML libraries.
    """

    # Seasonality factors by month
    MONTH_SEASONALITY = {
        1: 0.80,   # January - low season
        2: 0.85,   # February
        3: 0.95,   # March
        4: 1.00,   # April
        5: 1.10,   # May - picking up
        6: 1.20,   # June - high season
        7: 1.25,   # July - peak
        8: 1.20,   # August - high
        9: 1.05,   # September
        10: 1.00,  # October
        11: 0.90,  # November
        12: 1.15   # December - holiday
    }

    # Day of week factors
    DOW_FACTORS = {
        0: 0.85,  # Monday
        1: 0.85,  # Tuesday
        2: 0.90,  # Wednesday
        3: 0.95,  # Thursday
        4: 1.15,  # Friday
        5: 1.25,  # Saturday
        6: 1.00   # Sunday
    }

    def __init__(self, total_rooms: int = 70):
        """
        Initialize the ML Forecast Service.

        Args:
            total_rooms: Total number of rooms in the property
        """
        self.total_rooms = total_rooms
        self._model_params: Dict[str, Any] = {}
        logger.info(f"MLForecastService initialized with {total_rooms} rooms")

    async def generate_90_day_forecast(
        self,
        historical_data: List[Dict[str, Any]],
        events: Optional[List[Dict[str, Any]]] = None,
        start_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate 90-day demand forecast using statistical methods.

        Args:
            historical_data: Historical booking/demand data
            events: Known upcoming events that may impact demand
            start_date: Start date for forecast (defaults to today)

        Returns:
            List of forecast data points for 90 days
        """
        if start_date is None:
            start_date = date.today()

        # Extract and prepare historical values
        historical_values = self._extract_historical_values(historical_data)

        # Fit exponential smoothing model
        level, trend, seasonal_indices = self._fit_exponential_smoothing(historical_values)

        # Generate forecasts
        forecasts = []
        for day_offset in range(90):
            forecast_date = start_date + timedelta(days=day_offset)

            # Get seasonal and day-of-week factors
            month_factor = self.MONTH_SEASONALITY.get(forecast_date.month, 1.0)
            dow_factor = self.DOW_FACTORS.get(forecast_date.weekday(), 1.0)

            # Calculate seasonal index from historical data or use defaults
            week_of_year = forecast_date.isocalendar()[1]
            seasonal_index = seasonal_indices.get(week_of_year, month_factor)

            # Base forecast with trend
            days_ahead = day_offset + 1
            base_forecast = (level + trend * days_ahead) * seasonal_index * dow_factor

            # Apply event impact if applicable
            if events:
                event_factor = self._calculate_event_impact(forecast_date, events)
                base_forecast *= event_factor

            # Convert to occupancy percentage
            forecasted_occupancy = min((base_forecast / self.total_rooms) * 100, 100)
            forecasted_occupancy = max(forecasted_occupancy, 5)  # Minimum 5%

            # Calculate confidence interval
            confidence_level = self._calculate_confidence(days_ahead, len(historical_values))
            ci_width = (100 - confidence_level) / 100 * forecasted_occupancy * 0.3

            # Determine demand level
            demand_level = self._categorize_demand(forecasted_occupancy)

            forecast_point = {
                "date": forecast_date.isoformat(),
                "forecasted_demand": round(base_forecast, 1),
                "forecasted_occupancy": round(forecasted_occupancy, 1),
                "confidence_level": round(confidence_level, 1),
                "lower_bound": round(max(forecasted_occupancy - ci_width, 5), 1),
                "upper_bound": round(min(forecasted_occupancy + ci_width, 100), 1),
                "demand_level": demand_level,
                "day_of_week": forecast_date.strftime("%A"),
                "is_weekend": forecast_date.weekday() >= 5,
                "seasonality_factor": round(month_factor * dow_factor, 2),
                "trend_component": round(trend * days_ahead, 2)
            }

            forecasts.append(forecast_point)

        return forecasts

    def _extract_historical_values(self, historical_data: List[Dict[str, Any]]) -> List[float]:
        """Extract demand values from historical data."""
        if not historical_data:
            # Generate synthetic historical data based on typical patterns
            return [self.total_rooms * 0.7 + np.random.normal(0, 5) for _ in range(365)]

        values = []
        for record in historical_data:
            if 'demand' in record:
                values.append(float(record['demand']))
            elif 'occupancy' in record:
                values.append(float(record['occupancy']) * self.total_rooms / 100)
            elif 'bookings' in record:
                values.append(float(record['bookings']))
            else:
                values.append(self.total_rooms * 0.7)

        return values if values else [self.total_rooms * 0.7 for _ in range(365)]

    def _fit_exponential_smoothing(
        self,
        data: List[float],
        alpha: float = 0.3,
        beta: float = 0.1
    ) -> Tuple[float, float, Dict[int, float]]:
        """
        Fit Holt-Winters exponential smoothing model.

        Args:
            data: Historical demand values
            alpha: Smoothing parameter for level
            beta: Smoothing parameter for trend

        Returns:
            Tuple of (level, trend, seasonal_indices)
        """
        if len(data) < 2:
            return (self.total_rooms * 0.7, 0.0, {})

        # Initialize level and trend
        level = data[0]
        trend = (data[-1] - data[0]) / len(data) if len(data) > 1 else 0

        # Update with exponential smoothing
        for i, value in enumerate(data):
            prev_level = level
            level = alpha * value + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend

        # Calculate seasonal indices by week
        seasonal_indices = {}
        if len(data) >= 52:
            # Group by week and calculate average
            for week in range(1, 53):
                week_values = [data[i] for i in range(len(data)) if (i // 7) % 52 == week - 1]
                if week_values:
                    avg_value = np.mean(week_values)
                    seasonal_indices[week] = avg_value / level if level > 0 else 1.0

        return level, trend, seasonal_indices

    def _calculate_event_impact(self, forecast_date: date, events: List[Dict[str, Any]]) -> float:
        """Calculate demand multiplier from events."""
        impact_factor = 1.0

        for event in events:
            event_date = event.get('date')
            if isinstance(event_date, str):
                try:
                    event_date = date.fromisoformat(event_date)
                except (ValueError, TypeError):
                    continue

            if event_date:
                days_diff = abs((forecast_date - event_date).days)
                if days_diff <= 3:  # Event affects nearby days
                    event_type = event.get('type', 'general').lower()
                    base_impact = event.get('impact', 1.2)

                    # Type-based impact
                    type_multipliers = {
                        'conference': 1.5,
                        'concert': 1.3,
                        'sports': 1.4,
                        'festival': 1.6,
                        'convention': 1.8,
                        'trade_show': 1.5
                    }
                    type_impact = type_multipliers.get(event_type, base_impact)

                    # Decay by distance from event
                    distance_decay = 1 - (days_diff * 0.2)
                    distance_decay = max(distance_decay, 0.5)

                    impact_factor *= (1 + (type_impact - 1) * distance_decay)

        return min(impact_factor, 2.0)  # Cap at 2x

    def _calculate_confidence(self, days_ahead: int, data_points: int) -> float:
        """Calculate forecast confidence based on horizon and data availability."""
        # Base confidence from data availability
        data_confidence = min(data_points / 365, 1.0) * 30  # Up to 30 points

        # Horizon penalty
        if days_ahead <= 7:
            horizon_confidence = 70
        elif days_ahead <= 14:
            horizon_confidence = 65
        elif days_ahead <= 30:
            horizon_confidence = 55
        elif days_ahead <= 60:
            horizon_confidence = 45
        else:
            horizon_confidence = 35

        return min(horizon_confidence + data_confidence, 95)

    def _categorize_demand(self, occupancy: float) -> str:
        """Categorize demand level based on occupancy."""
        if occupancy >= 90:
            return DemandLevel.CRITICAL.value
        elif occupancy >= 80:
            return DemandLevel.HIGH.value
        elif occupancy >= 60:
            return DemandLevel.MODERATE.value
        elif occupancy >= 40:
            return DemandLevel.LOW.value
        else:
            return DemandLevel.VERY_LOW.value

    async def calculate_confidence_intervals(
        self,
        forecast: List[Dict[str, Any]],
        confidence_level: float = 0.95
    ) -> List[Dict[str, Any]]:
        """
        Add confidence intervals to forecast data.

        Args:
            forecast: List of forecast data points
            confidence_level: Confidence level (e.g., 0.95 for 95%)

        Returns:
            Forecast with updated confidence intervals
        """
        # Z-score for confidence level
        z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
        z = z_scores.get(confidence_level, 1.96)

        updated_forecast = []
        for i, point in enumerate(forecast):
            forecasted_occupancy = point.get('forecasted_occupancy', 70)

            # Calculate standard error based on horizon
            days_ahead = i + 1
            base_std = 5  # Base standard deviation

            # Error grows with forecast horizon
            horizon_factor = 1 + (days_ahead / 30) * 0.5
            std_error = base_std * horizon_factor

            # Calculate bounds
            margin = z * std_error
            lower_bound = max(forecasted_occupancy - margin, 5)
            upper_bound = min(forecasted_occupancy + margin, 100)

            updated_point = {
                **point,
                "lower_bound": round(lower_bound, 1),
                "upper_bound": round(upper_bound, 1),
                "confidence_interval_level": confidence_level
            }
            updated_forecast.append(updated_point)

        return updated_forecast

    async def detect_anomalies(
        self,
        data: List[Dict[str, Any]],
        sensitivity: float = 2.0
    ) -> List[Dict[str, Any]]:
        """
        Detect unusual patterns in demand data.

        Args:
            data: Historical demand data
            sensitivity: Number of standard deviations for anomaly threshold

        Returns:
            List of detected anomalies
        """
        if len(data) < 7:
            return []

        # Extract values
        values = []
        dates = []
        for record in data:
            if 'occupancy' in record:
                values.append(float(record['occupancy']))
            elif 'demand' in record:
                values.append(float(record['demand']))
            else:
                continue

            if 'date' in record:
                dates.append(record['date'])
            else:
                dates.append(date.today().isoformat())

        if len(values) < 7:
            return []

        # Calculate rolling statistics
        window_size = min(7, len(values) - 1)
        anomalies = []

        for i in range(window_size, len(values)):
            window = values[i - window_size:i]
            current = values[i]

            window_mean = np.mean(window)
            window_std = np.std(window)

            if window_std > 0:
                z_score = abs(current - window_mean) / window_std

                if z_score > sensitivity:
                    deviation_percent = ((current - window_mean) / window_mean) * 100 if window_mean > 0 else 0

                    # Determine anomaly type
                    if current > window_mean:
                        anomaly_type = AnomalyType.SPIKE.value
                    else:
                        anomaly_type = AnomalyType.DROP.value

                    # Determine severity
                    if z_score > 3:
                        severity = "high"
                    elif z_score > 2.5:
                        severity = "medium"
                    else:
                        severity = "low"

                    anomaly = {
                        "date": dates[i] if i < len(dates) else date.today().isoformat(),
                        "anomaly_type": anomaly_type,
                        "severity": severity,
                        "observed_value": round(current, 1),
                        "expected_value": round(window_mean, 1),
                        "deviation_percent": round(deviation_percent, 1),
                        "z_score": round(z_score, 2),
                        "description": f"{'Spike' if current > window_mean else 'Drop'} in demand - "
                                      f"observed {current:.0f}% vs expected {window_mean:.0f}%"
                    }
                    anomalies.append(anomaly)

        return anomalies

    async def calculate_price_elasticity(
        self,
        historical_rates: List[Dict[str, Any]],
        historical_bookings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate price elasticity of demand.

        Args:
            historical_rates: Historical rate data
            historical_bookings: Historical booking data

        Returns:
            Elasticity analysis results
        """
        # Extract paired data
        rate_booking_pairs = self._pair_rate_booking_data(historical_rates, historical_bookings)

        if len(rate_booking_pairs) < 10:
            return self._generate_default_elasticity()

        rates = [p['rate'] for p in rate_booking_pairs]
        bookings = [p['bookings'] for p in rate_booking_pairs]

        # Calculate point elasticity
        elasticities = []
        for i in range(1, len(rate_booking_pairs)):
            rate_change = (rates[i] - rates[i - 1]) / rates[i - 1] if rates[i - 1] > 0 else 0
            booking_change = (bookings[i] - bookings[i - 1]) / bookings[i - 1] if bookings[i - 1] > 0 else 0

            if abs(rate_change) > 0.01:  # Minimum 1% rate change
                elasticity = booking_change / rate_change
                if -5 < elasticity < 0:  # Reasonable elasticity range
                    elasticities.append(elasticity)

        # Calculate overall elasticity
        overall_elasticity = np.mean(elasticities) if elasticities else -0.5

        # Segment elasticity by rate level
        rate_segments = {
            'budget': [],
            'standard': [],
            'premium': []
        }

        avg_rate = np.mean(rates)
        for i, e in enumerate(elasticities):
            rate = rates[i]
            if rate < avg_rate * 0.85:
                rate_segments['budget'].append(e)
            elif rate > avg_rate * 1.15:
                rate_segments['premium'].append(e)
            else:
                rate_segments['standard'].append(e)

        elasticity_by_segment = {
            segment: round(np.mean(values), 2) if values else overall_elasticity
            for segment, values in rate_segments.items()
        }

        # Calculate optimal price range
        optimal_rate = self._calculate_optimal_rate(rates, bookings, overall_elasticity)

        # Generate interpretation
        interpretation = self._interpret_elasticity(overall_elasticity)

        return {
            "overall_elasticity": round(overall_elasticity, 2),
            "elasticity_by_segment": elasticity_by_segment,
            "optimal_price_range": (round(optimal_rate * 0.95, 2), round(optimal_rate * 1.05, 2)),
            "revenue_maximizing_price": round(optimal_rate, 2),
            "confidence": min(len(elasticities) / 100 * 100, 90),
            "interpretation": interpretation,
            "data_points_analyzed": len(rate_booking_pairs),
            "analysis_period": {
                "start": rate_booking_pairs[0].get('date') if rate_booking_pairs else None,
                "end": rate_booking_pairs[-1].get('date') if rate_booking_pairs else None
            }
        }

    def _pair_rate_booking_data(
        self,
        rates: List[Dict[str, Any]],
        bookings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Pair rate and booking data by date."""
        rate_by_date = {}
        for r in rates:
            d = r.get('date')
            if d:
                rate_by_date[d] = float(r.get('rate', r.get('price', 100)))

        booking_by_date = {}
        for b in bookings:
            d = b.get('date')
            if d:
                booking_by_date[d] = float(b.get('bookings', b.get('count', 0)))

        # Match dates
        paired = []
        for d in rate_by_date:
            if d in booking_by_date:
                paired.append({
                    'date': d,
                    'rate': rate_by_date[d],
                    'bookings': booking_by_date[d]
                })

        return sorted(paired, key=lambda x: x['date'])

    def _calculate_optimal_rate(
        self,
        rates: List[float],
        bookings: List[float],
        elasticity: float
    ) -> float:
        """Calculate revenue-maximizing rate."""
        if not rates or not bookings:
            return 12500.0  # Default rate (INR)

        # Calculate average revenue at each rate level
        revenues = [r * b for r, b in zip(rates, bookings)]

        # Find rate that maximized revenue
        max_revenue_idx = np.argmax(revenues)
        base_optimal = rates[max_revenue_idx]

        # Adjust based on elasticity
        if elasticity > -1:
            # Inelastic demand - can increase price
            adjusted_rate = base_optimal * 1.05
        elif elasticity < -2:
            # Elastic demand - lower price may increase revenue
            adjusted_rate = base_optimal * 0.95
        else:
            adjusted_rate = base_optimal

        return adjusted_rate

    def _generate_default_elasticity(self) -> Dict[str, Any]:
        """Generate default elasticity when insufficient data."""
        return {
            "overall_elasticity": -0.5,
            "elasticity_by_segment": {
                "budget": -0.7,
                "standard": -0.5,
                "premium": -0.3
            },
            "optimal_price_range": (11500.0, 13500.0),
            "revenue_maximizing_price": 12500.0,
            "confidence": 30,
            "interpretation": "Insufficient data for accurate elasticity calculation. "
                             "Using industry-typical values. Demand appears moderately price-sensitive.",
            "data_points_analyzed": 0
        }

    def _interpret_elasticity(self, elasticity: float) -> str:
        """Generate human-readable elasticity interpretation."""
        if elasticity > -0.3:
            return ("Demand is highly inelastic (price-insensitive). "
                   "Price increases will likely increase revenue. "
                   "Consider premium positioning and rate optimization.")
        elif elasticity > -0.7:
            return ("Demand is moderately inelastic. "
                   "Small price increases may be beneficial. "
                   "Monitor competitor pricing closely.")
        elif elasticity > -1.0:
            return ("Demand has unit elasticity. "
                   "Price changes will have proportional effect on bookings. "
                   "Focus on value perception and service quality.")
        elif elasticity > -1.5:
            return ("Demand is moderately elastic. "
                   "Price increases may reduce revenue. "
                   "Consider promotional strategies for low-demand periods.")
        else:
            return ("Demand is highly elastic (price-sensitive). "
                   "Competitive pricing is crucial. "
                   "Focus on volume strategy and promotions.")

    async def generate_trend_analysis(
        self,
        historical_data: List[Dict[str, Any]],
        period: str = "month"
    ) -> Dict[str, Any]:
        """
        Analyze trends in historical data.

        Args:
            historical_data: Historical demand/occupancy data
            period: Analysis period (week, month, quarter)

        Returns:
            Trend analysis results
        """
        values = self._extract_historical_values(historical_data)

        if len(values) < 14:
            return {
                "trend_direction": "stable",
                "trend_strength": 0,
                "average": round(np.mean(values), 1) if values else 0,
                "volatility": 0,
                "recommendation": "Insufficient data for trend analysis"
            }

        # Calculate trend using linear regression
        x = np.arange(len(values))
        slope = np.cov(x, values)[0, 1] / np.var(x) if np.var(x) > 0 else 0

        # Determine trend direction
        if slope > 0.5:
            trend_direction = "increasing"
            trend_strength = min(abs(slope) * 10, 100)
        elif slope < -0.5:
            trend_direction = "decreasing"
            trend_strength = min(abs(slope) * 10, 100)
        else:
            trend_direction = "stable"
            trend_strength = 0

        # Calculate volatility
        volatility = np.std(values) / np.mean(values) * 100 if np.mean(values) > 0 else 0

        # Period averages
        recent_avg = np.mean(values[-30:]) if len(values) >= 30 else np.mean(values)
        prior_avg = np.mean(values[-60:-30]) if len(values) >= 60 else np.mean(values[:-30]) if len(values) > 30 else recent_avg

        change_percent = ((recent_avg - prior_avg) / prior_avg * 100) if prior_avg > 0 else 0

        # Generate recommendation
        if trend_direction == "increasing" and volatility < 20:
            recommendation = "Strong upward trend with low volatility. Consider rate optimization."
        elif trend_direction == "decreasing" and change_percent < -10:
            recommendation = "Declining trend detected. Review competitive positioning and promotions."
        elif volatility > 30:
            recommendation = "High volatility detected. Implement dynamic pricing to capture demand swings."
        else:
            recommendation = "Stable demand patterns. Focus on maintaining occupancy and gradual rate increases."

        return {
            "trend_direction": trend_direction,
            "trend_strength": round(trend_strength, 1),
            "average": round(np.mean(values), 1),
            "recent_average": round(recent_avg, 1),
            "change_percent": round(change_percent, 1),
            "volatility": round(volatility, 1),
            "peak_value": round(max(values), 1),
            "trough_value": round(min(values), 1),
            "data_points": len(values),
            "recommendation": recommendation
        }


# Singleton instance
_ml_forecast_service_instance: Optional[MLForecastService] = None


def get_ml_forecast_service(total_rooms: int = 70) -> MLForecastService:
    """Get or create MLForecastService singleton instance."""
    global _ml_forecast_service_instance
    if _ml_forecast_service_instance is None:
        _ml_forecast_service_instance = MLForecastService(total_rooms)
    return _ml_forecast_service_instance
