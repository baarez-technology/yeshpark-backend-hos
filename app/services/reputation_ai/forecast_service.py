"""
Rating Forecast Service
Predicts future ratings based on historical trends and patterns.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from statistics import mean, stdev
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reviews import Review, SentimentTrends
from app.models.reputation import RatingForecast

logger = logging.getLogger(__name__)


class RatingForecastService:
    """Predict future ratings based on historical data"""

    # Horizon definitions in days
    HORIZONS = {
        "7d": 7,
        "14d": 14,
        "30d": 30,
        "90d": 90
    }

    def __init__(
        self,
        db: AsyncSession,
        openai_service: Optional["ReputationOpenAIService"] = None
    ):
        """
        Initialize RatingForecastService.

        Args:
            db: Database session
            openai_service: Optional OpenAI service for enhanced explanations
        """
        self.db = db
        self.openai_service = openai_service

    async def predict_rating(
        self,
        horizon: str = "30d",
        source: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Predict rating for given horizon.

        Uses historical trends, momentum, and seasonal patterns to predict
        future ratings.

        Args:
            horizon: Prediction horizon ("7d", "14d", "30d", "90d")
            source: Optional filter by review source

        Returns:
            Dictionary with current, predicted, confidence, trend_direction, key_factors
        """
        days = self.HORIZONS.get(horizon, 30)

        # Get historical data
        historical_data = await self._get_historical_ratings(
            lookback_days=max(days * 3, 90),  # Need enough history
            source=source
        )

        if not historical_data or len(historical_data) < 10:
            return {
                "current": 0.0,
                "predicted": 0.0,
                "confidence": 0.0,
                "trend_direction": "insufficient_data",
                "key_factors": [],
                "error": "Insufficient data for prediction"
            }

        # Calculate current rating
        current_rating = await self._get_current_rating(source=source)

        # Analyze trends
        trend_analysis = self._analyze_trends(historical_data)

        # Calculate momentum
        momentum = self._calculate_momentum(historical_data)

        # Get sentiment influence
        sentiment_factor = await self._get_sentiment_factor(source=source)

        # Calculate prediction
        predicted_rating, confidence = self._calculate_prediction(
            current_rating=current_rating,
            trend_analysis=trend_analysis,
            momentum=momentum,
            sentiment_factor=sentiment_factor,
            horizon_days=days
        )

        # Determine trend direction
        if predicted_rating > current_rating + 0.1:
            trend_direction = "up"
        elif predicted_rating < current_rating - 0.1:
            trend_direction = "down"
        else:
            trend_direction = "stable"

        # Identify key factors
        key_factors = self._identify_key_factors(
            trend_analysis=trend_analysis,
            momentum=momentum,
            sentiment_factor=sentiment_factor,
            predicted_change=predicted_rating - current_rating
        )

        return {
            "current": round(current_rating, 2),
            "predicted": round(predicted_rating, 2),
            "confidence": round(confidence, 2),
            "trend_direction": trend_direction,
            "key_factors": key_factors,
            "horizon": horizon,
            "source": source or "all",
            "analysis": {
                "trend_slope": round(trend_analysis.get("slope", 0), 4),
                "momentum": round(momentum, 3),
                "sentiment_factor": round(sentiment_factor, 3),
                "data_points": len(historical_data)
            }
        }

    async def generate_forecast(
        self,
        horizon: str,
        source: Optional[str] = None
    ) -> Optional[RatingForecast]:
        """
        Generate and save a forecast to the database.

        Args:
            horizon: Prediction horizon
            source: Optional filter by review source

        Returns:
            Created RatingForecast record
        """
        prediction = await self.predict_rating(horizon=horizon, source=source)

        if prediction.get("error"):
            logger.warning(f"Could not generate forecast: {prediction.get('error')}")
            return None

        # Build explanation
        explanation = self._build_explanation(prediction)

        forecast = RatingForecast(
            horizon=horizon,
            source=source,
            current_rating=prediction["current"],
            predicted_rating=prediction["predicted"],
            confidence=prediction["confidence"],
            trend_direction=prediction["trend_direction"],
            key_factors={"factors": prediction["key_factors"]},
            explanation=explanation
        )

        self.db.add(forecast)
        await self.db.commit()
        await self.db.refresh(forecast)

        logger.info(f"Generated forecast: {forecast.id} ({horizon}, {source or 'all'})")
        return forecast

    async def get_recent_forecasts(
        self,
        limit: int = 10,
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent forecasts from database.

        Args:
            limit: Maximum number of forecasts to return
            source: Optional filter by source

        Returns:
            List of forecast records
        """
        stmt = select(RatingForecast).order_by(
            RatingForecast.generated_at.desc()
        )

        if source:
            stmt = stmt.where(RatingForecast.source == source)

        stmt = stmt.limit(limit)

        result = await self.db.execute(stmt)
        forecasts = result.scalars().all()

        return [
            {
                "id": f.id,
                "horizon": f.horizon,
                "source": f.source,
                "current_rating": f.current_rating,
                "predicted_rating": f.predicted_rating,
                "confidence": f.confidence,
                "trend_direction": f.trend_direction,
                "key_factors": f.key_factors,
                "explanation": f.explanation,
                "generated_at": f.generated_at.isoformat() if f.generated_at else None
            }
            for f in forecasts
        ]

    async def validate_forecast_accuracy(
        self,
        forecast_id: int
    ) -> Dict[str, Any]:
        """
        Validate a past forecast against actual results.

        Args:
            forecast_id: ID of the forecast to validate

        Returns:
            Dictionary with validation results
        """
        stmt = select(RatingForecast).where(RatingForecast.id == forecast_id)
        result = await self.db.execute(stmt)
        forecast = result.scalar_one_or_none()

        if not forecast:
            return {"error": "Forecast not found"}

        # Calculate the end date based on horizon
        days = self.HORIZONS.get(forecast.horizon, 30)
        target_date = forecast.generated_at + timedelta(days=days)

        # Check if we've reached the target date
        if datetime.utcnow() < target_date:
            return {
                "forecast_id": forecast_id,
                "status": "pending",
                "target_date": target_date.isoformat(),
                "days_remaining": (target_date - datetime.utcnow()).days
            }

        # Get actual rating at target date
        actual_rating = await self._get_rating_at_date(
            target_date=target_date,
            source=forecast.source
        )

        if actual_rating is None:
            return {
                "forecast_id": forecast_id,
                "status": "no_data",
                "message": "No reviews found for validation period"
            }

        # Calculate accuracy metrics
        error = actual_rating - forecast.predicted_rating
        absolute_error = abs(error)
        percentage_error = (absolute_error / actual_rating * 100) if actual_rating > 0 else 0

        # Determine if prediction was accurate (within 0.2 points)
        is_accurate = absolute_error <= 0.2

        return {
            "forecast_id": forecast_id,
            "status": "validated",
            "predicted_rating": forecast.predicted_rating,
            "actual_rating": round(actual_rating, 2),
            "error": round(error, 2),
            "absolute_error": round(absolute_error, 2),
            "percentage_error": round(percentage_error, 1),
            "is_accurate": is_accurate,
            "trend_correct": (
                (forecast.trend_direction == "up" and actual_rating > forecast.current_rating) or
                (forecast.trend_direction == "down" and actual_rating < forecast.current_rating) or
                (forecast.trend_direction == "stable" and abs(actual_rating - forecast.current_rating) <= 0.1)
            )
        }

    async def generate_multi_horizon_forecast(
        self,
        source: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate forecasts for all horizons.

        Args:
            source: Optional filter by source

        Returns:
            Dictionary with forecasts for each horizon
        """
        forecasts = {}

        for horizon in self.HORIZONS.keys():
            prediction = await self.predict_rating(horizon=horizon, source=source)
            forecasts[horizon] = prediction

        # Calculate overall confidence
        confidences = [f.get("confidence", 0) for f in forecasts.values()]
        overall_confidence = mean(confidences) if confidences else 0

        return {
            "source": source or "all",
            "forecasts": forecasts,
            "overall_confidence": round(overall_confidence, 2),
            "generated_at": datetime.utcnow().isoformat()
        }

    # ==================== PRIVATE METHODS ====================

    async def _get_historical_ratings(
        self,
        lookback_days: int,
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get historical rating data grouped by week"""
        start_date = datetime.utcnow() - timedelta(days=lookback_days)

        # SQLite compatible date grouping
        stmt = select(
            func.date(Review.review_date).label("date"),
            func.count(Review.id).label("count"),
            func.avg(Review.overall_rating).label("avg_rating")
        ).where(
            Review.review_date >= start_date
        )

        if source:
            stmt = stmt.where(Review.source == source)

        stmt = stmt.group_by(func.date(Review.review_date)).order_by(func.date(Review.review_date))

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "date": str(row.date),
                "count": row.count,
                "avg_rating": float(row.avg_rating) if row.avg_rating else 0.0
            }
            for row in rows
            if row.avg_rating is not None
        ]

    async def _get_current_rating(
        self,
        days: int = 30,
        source: Optional[str] = None
    ) -> float:
        """Get current average rating"""
        start_date = datetime.utcnow() - timedelta(days=days)

        stmt = select(func.avg(Review.overall_rating)).where(
            Review.review_date >= start_date
        )

        if source:
            stmt = stmt.where(Review.source == source)

        result = await self.db.execute(stmt)
        avg = result.scalar()

        return float(avg) if avg else 0.0

    async def _get_sentiment_factor(
        self,
        days: int = 30,
        source: Optional[str] = None
    ) -> float:
        """Calculate sentiment influence factor"""
        start_date = datetime.utcnow() - timedelta(days=days)

        stmt = select(
            func.count(case((Review.sentiment == "positive", 1))).label("positive"),
            func.count(case((Review.sentiment == "negative", 1))).label("negative"),
            func.count(Review.id).label("total")
        ).where(
            Review.review_date >= start_date
        )

        if source:
            stmt = stmt.where(Review.source == source)

        result = (await self.db.execute(stmt)).one()

        total = result.total or 0
        if total == 0:
            return 0.0

        positive = result.positive or 0
        negative = result.negative or 0

        # Sentiment factor: ranges from -1 (all negative) to +1 (all positive)
        sentiment_ratio = (positive - negative) / total
        return sentiment_ratio

    async def _get_rating_at_date(
        self,
        target_date: datetime,
        source: Optional[str] = None,
        window_days: int = 7
    ) -> Optional[float]:
        """Get average rating around a specific date"""
        start_date = target_date - timedelta(days=window_days)
        end_date = target_date + timedelta(days=window_days)

        stmt = select(func.avg(Review.overall_rating)).where(
            Review.review_date >= start_date,
            Review.review_date <= end_date
        )

        if source:
            stmt = stmt.where(Review.source == source)

        result = await self.db.execute(stmt)
        avg = result.scalar()

        return float(avg) if avg else None

    def _analyze_trends(
        self,
        historical_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze rating trends using linear regression"""
        if len(historical_data) < 3:
            return {"slope": 0.0, "intercept": 0.0, "r_squared": 0.0}

        ratings = [d["avg_rating"] for d in historical_data]
        n = len(ratings)
        x = list(range(n))

        # Simple linear regression
        x_mean = sum(x) / n
        y_mean = sum(ratings) / n

        numerator = sum((x[i] - x_mean) * (ratings[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return {"slope": 0.0, "intercept": y_mean, "r_squared": 0.0}

        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

        # Calculate R-squared
        y_pred = [slope * x[i] + intercept for i in range(n)]
        ss_res = sum((ratings[i] - y_pred[i]) ** 2 for i in range(n))
        ss_tot = sum((ratings[i] - y_mean) ** 2 for i in range(n))

        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        return {
            "slope": slope,
            "intercept": intercept,
            "r_squared": max(0.0, r_squared)
        }

    def _calculate_momentum(
        self,
        historical_data: List[Dict[str, Any]]
    ) -> float:
        """Calculate recent momentum (rate of change)"""
        if len(historical_data) < 7:
            return 0.0

        # Compare recent period to earlier period
        recent = historical_data[-7:]
        earlier = historical_data[-14:-7] if len(historical_data) >= 14 else historical_data[:7]

        recent_avg = mean([d["avg_rating"] for d in recent])
        earlier_avg = mean([d["avg_rating"] for d in earlier])

        # Momentum is the change
        momentum = recent_avg - earlier_avg

        return momentum

    def _calculate_prediction(
        self,
        current_rating: float,
        trend_analysis: Dict[str, Any],
        momentum: float,
        sentiment_factor: float,
        horizon_days: int
    ) -> tuple:
        """Calculate predicted rating and confidence"""
        # Base prediction from trend
        slope = trend_analysis.get("slope", 0)
        trend_impact = slope * (horizon_days / 7)  # Scale by weeks

        # Momentum impact (recent changes matter)
        momentum_impact = momentum * 0.5 * (horizon_days / 30)

        # Sentiment impact
        sentiment_impact = sentiment_factor * 0.1

        # Calculate predicted change
        predicted_change = (
            trend_impact * 0.4 +
            momentum_impact * 0.4 +
            sentiment_impact * 0.2
        )

        # Predicted rating
        predicted = current_rating + predicted_change

        # Clamp to valid range (1-5)
        predicted = max(1.0, min(5.0, predicted))

        # Calculate confidence
        r_squared = trend_analysis.get("r_squared", 0)

        # Confidence factors
        trend_confidence = r_squared * 0.4  # How well trend fits data
        momentum_confidence = max(0, 0.3 - abs(momentum) * 0.5)  # Lower if volatile
        horizon_penalty = max(0, 0.3 - (horizon_days / 90) * 0.15)  # Further = less certain

        confidence = trend_confidence + momentum_confidence + horizon_penalty

        # Ensure confidence is in valid range
        confidence = max(0.1, min(0.95, confidence))

        return predicted, confidence

    def _identify_key_factors(
        self,
        trend_analysis: Dict[str, Any],
        momentum: float,
        sentiment_factor: float,
        predicted_change: float
    ) -> List[Dict[str, Any]]:
        """Identify key factors affecting the prediction"""
        factors = []

        # Trend factor
        slope = trend_analysis.get("slope", 0)
        if abs(slope) > 0.01:
            factors.append({
                "factor": "Historical Trend",
                "direction": "positive" if slope > 0 else "negative",
                "impact": "high" if abs(slope) > 0.03 else "medium",
                "description": f"Ratings have been {'increasing' if slope > 0 else 'decreasing'} over time"
            })

        # Momentum factor
        if abs(momentum) > 0.1:
            factors.append({
                "factor": "Recent Momentum",
                "direction": "positive" if momentum > 0 else "negative",
                "impact": "high" if abs(momentum) > 0.2 else "medium",
                "description": f"Recent reviews show {'improvement' if momentum > 0 else 'decline'}"
            })

        # Sentiment factor
        if abs(sentiment_factor) > 0.1:
            factors.append({
                "factor": "Guest Sentiment",
                "direction": "positive" if sentiment_factor > 0 else "negative",
                "impact": "medium",
                "description": f"{'More positive' if sentiment_factor > 0 else 'More negative'} sentiment in recent reviews"
            })

        # Overall prediction direction
        if abs(predicted_change) > 0.15:
            factors.append({
                "factor": "Combined Analysis",
                "direction": "positive" if predicted_change > 0 else "negative",
                "impact": "high" if abs(predicted_change) > 0.3 else "medium",
                "description": f"Multiple factors suggest ratings will {'improve' if predicted_change > 0 else 'decline'}"
            })

        return factors[:4]  # Return top 4 factors

    def _build_explanation(self, prediction: Dict[str, Any]) -> str:
        """Build human-readable explanation of the forecast"""
        current = prediction["current"]
        predicted = prediction["predicted"]
        confidence = prediction["confidence"]
        trend = prediction["trend_direction"]
        factors = prediction.get("key_factors", [])

        # Build explanation text
        if trend == "up":
            direction_text = "improve"
        elif trend == "down":
            direction_text = "decline"
        else:
            direction_text = "remain stable"

        explanation = f"Based on historical data analysis, ratings are predicted to {direction_text} "
        explanation += f"from {current:.2f} to {predicted:.2f} over the next {prediction['horizon']}. "

        # Add confidence interpretation
        if confidence >= 0.7:
            explanation += "This prediction has high confidence. "
        elif confidence >= 0.5:
            explanation += "This prediction has moderate confidence. "
        else:
            explanation += "This prediction has lower confidence due to data variability. "

        # Add key factors
        if factors:
            explanation += "Key factors include: "
            factor_texts = [f"{f['factor']} ({f['direction']})" for f in factors[:3]]
            explanation += ", ".join(factor_texts) + "."

        return explanation
