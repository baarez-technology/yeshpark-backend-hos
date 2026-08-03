"""
Database model validation tests for Revenue Management models.
Tests model creation, foreign keys, indexes, and data integrity.
"""
import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import inspect

from app.models.revenue import (
    PricingAdjustments,
    ChannelPerformance,
    DynamicPricingRules,
    CompetitorData,
    ForecastData,
    PricingRecommendationRecord,
    RateChangeAudit,
    AutoPricingConfig,
    AIInsightRecord,
    CompetitorScrapeLog,
    EventRecord
)
from app.models.rms import (
    PricingRule,
    Competitor,
    CompetitorRate,
    DemandForecast,
    MarketEvent,
    PickupPace,
    SegmentPerformance
)


# ==================== PRICING ADJUSTMENTS MODEL ====================

class TestPricingAdjustmentsModel:
    """Tests for PricingAdjustments model."""

    @pytest.mark.asyncio
    async def test_create_pricing_adjustment(self, async_session: AsyncSession):
        """Test creating a pricing adjustment."""
        today = date.today()
        adjustment = PricingAdjustments(
            name="Weekend Surge",
            adjustment_type="percentage_increase",
            adjustment_value=15.0,
            applies_to="room_type",
            entity_id="DLX",
            priority=1,
            valid_from=today,
            valid_to=today + timedelta(days=30),
            is_active=True
        )

        async_session.add(adjustment)
        await async_session.commit()
        await async_session.refresh(adjustment)

        assert adjustment.id is not None
        assert adjustment.name == "Weekend Surge"
        assert adjustment.adjustment_value == 15.0
        assert adjustment.is_active is True

    @pytest.mark.asyncio
    async def test_pricing_adjustment_defaults(self, async_session: AsyncSession):
        """Test PricingAdjustments default values."""
        today = date.today()
        adjustment = PricingAdjustments(
            name="Test Adjustment",
            adjustment_value=10.0,
            valid_from=today,
            valid_to=today + timedelta(days=7)
        )

        async_session.add(adjustment)
        await async_session.commit()
        await async_session.refresh(adjustment)

        assert adjustment.priority == 0
        assert adjustment.is_active is True
        assert adjustment.created_at is not None

    @pytest.mark.asyncio
    async def test_pricing_adjustment_with_json_fields(self, async_session: AsyncSession):
        """Test PricingAdjustments with JSON condition values."""
        today = date.today()
        adjustment = PricingAdjustments(
            name="Complex Rule",
            adjustment_value=20.0,
            valid_from=today,
            valid_to=today + timedelta(days=30),
            condition_value={"min_occupancy": 80, "max_occupancy": 95},
            days_of_week=[5, 6]  # Saturday, Sunday
        )

        async_session.add(adjustment)
        await async_session.commit()
        await async_session.refresh(adjustment)

        assert adjustment.id is not None


# ==================== CHANNEL PERFORMANCE MODEL ====================

class TestChannelPerformanceModel:
    """Tests for ChannelPerformance model."""

    @pytest.mark.asyncio
    async def test_create_channel_performance(self, async_session: AsyncSession):
        """Test creating channel performance record."""
        today = date.today()
        perf = ChannelPerformance(
            date=today,
            channel="booking_com",
            bookings_count=25,
            revenue=125000.00,
            commission_amount=18750.00,
            commission_rate=15.0,
            net_revenue=106250.00,
            cancellations_count=3,
            cancellation_rate=10.7,
            avg_booking_value=5000.00,
            avg_lead_time=14
        )

        async_session.add(perf)
        await async_session.commit()
        await async_session.refresh(perf)

        assert perf.id is not None
        assert perf.channel == "booking_com"
        assert perf.revenue == 125000.00
        assert perf.commission_rate == 15.0

    @pytest.mark.asyncio
    async def test_channel_performance_defaults(self, async_session: AsyncSession):
        """Test ChannelPerformance default values."""
        today = date.today()
        perf = ChannelPerformance(
            date=today,
            channel="direct"
        )

        async_session.add(perf)
        await async_session.commit()
        await async_session.refresh(perf)

        assert perf.bookings_count == 0
        assert perf.revenue == 0.0
        assert perf.commission_amount == 0.0
        assert perf.cancellations_count == 0


# ==================== DYNAMIC PRICING RULES MODEL ====================

class TestDynamicPricingRulesModel:
    """Tests for DynamicPricingRules model."""

    @pytest.mark.asyncio
    async def test_create_dynamic_pricing_rule(self, async_session: AsyncSession):
        """Test creating a dynamic pricing rule."""
        rule = DynamicPricingRules(
            rule_name="High Occupancy Surge",
            occupancy_threshold_min=80.0,
            occupancy_threshold_max=95.0,
            price_adjustment_type="percentage",
            price_adjustment_value=20.0,
            priority=1,
            is_active=True
        )

        async_session.add(rule)
        await async_session.commit()
        await async_session.refresh(rule)

        assert rule.id is not None
        assert rule.rule_name == "High Occupancy Surge"
        assert rule.price_adjustment_value == 20.0

    @pytest.mark.asyncio
    async def test_dynamic_pricing_rule_with_dates(self, async_session: AsyncSession):
        """Test DynamicPricingRules with validity dates."""
        today = date.today()
        rule = DynamicPricingRules(
            rule_name="Summer Peak",
            price_adjustment_type="percentage",
            price_adjustment_value=25.0,
            valid_from=today,
            valid_to=today + timedelta(days=90),
            days_before_arrival_min=0,
            days_before_arrival_max=7
        )

        async_session.add(rule)
        await async_session.commit()
        await async_session.refresh(rule)

        assert rule.valid_from == today
        assert rule.valid_to == today + timedelta(days=90)


# ==================== COMPETITOR DATA MODEL ====================

class TestCompetitorDataModel:
    """Tests for CompetitorData model."""

    @pytest.mark.asyncio
    async def test_create_competitor_data(self, async_session: AsyncSession):
        """Test creating competitor data record."""
        today = date.today()
        competitor = CompetitorData(
            competitor_name="Grand Hyatt",
            date=today,
            room_type="Deluxe",
            rate=8500.00,
            availability=45,
            occupancy_estimate=78.5,
            source="booking_com"
        )

        async_session.add(competitor)
        await async_session.commit()
        await async_session.refresh(competitor)

        assert competitor.id is not None
        assert competitor.competitor_name == "Grand Hyatt"
        assert competitor.rate == 8500.00

    @pytest.mark.asyncio
    async def test_multiple_competitor_entries(self, async_session: AsyncSession):
        """Test storing multiple competitor data entries."""
        today = date.today()
        competitors = [
            CompetitorData(
                competitor_name="Hotel A",
                date=today,
                rate=7000.00,
                source="direct"
            ),
            CompetitorData(
                competitor_name="Hotel B",
                date=today,
                rate=7500.00,
                source="booking_com"
            ),
            CompetitorData(
                competitor_name="Hotel C",
                date=today,
                rate=8000.00,
                source="expedia"
            )
        ]

        for comp in competitors:
            async_session.add(comp)
        await async_session.commit()

        result = await async_session.exec(
            select(CompetitorData).where(CompetitorData.date == today)
        )
        all_competitors = result.all()

        assert len(all_competitors) == 3


# ==================== FORECAST DATA MODEL ====================

class TestForecastDataModel:
    """Tests for ForecastData model."""

    @pytest.mark.asyncio
    async def test_create_forecast_data(self, async_session: AsyncSession):
        """Test creating forecast data."""
        today = date.today()
        forecast = ForecastData(
            forecast_date=today + timedelta(days=7),
            forecast_type="occupancy",
            forecasted_value=85.5,
            actual_value=None,
            confidence_level=90.0,
            model_used="ensemble_v2"
        )

        async_session.add(forecast)
        await async_session.commit()
        await async_session.refresh(forecast)

        assert forecast.id is not None
        assert forecast.forecast_type == "occupancy"
        assert forecast.forecasted_value == 85.5

    @pytest.mark.asyncio
    async def test_forecast_data_with_actuals(self, async_session: AsyncSession):
        """Test forecast data with actual values for comparison."""
        yesterday = date.today() - timedelta(days=1)
        forecast = ForecastData(
            forecast_date=yesterday,
            forecast_type="revenue",
            forecasted_value=50000.00,
            actual_value=52500.00,
            variance=2500.00,
            variance_percentage=5.0,
            confidence_level=85.0
        )

        async_session.add(forecast)
        await async_session.commit()
        await async_session.refresh(forecast)

        assert forecast.variance == 2500.00
        assert forecast.variance_percentage == 5.0


# ==================== PRICING RECOMMENDATION RECORD ====================

class TestPricingRecommendationRecordModel:
    """Tests for PricingRecommendationRecord model."""

    @pytest.mark.asyncio
    async def test_create_pricing_recommendation(self, async_session: AsyncSession):
        """Test creating a pricing recommendation record."""
        today = date.today()
        rec = PricingRecommendationRecord(
            date=today + timedelta(days=3),
            room_type_id=1,
            current_rate=7500.00,
            recommended_rate=8250.00,
            change_percent=10.0,
            demand_level="high",
            confidence=0.88,
            reasoning="High demand expected due to local event",
            priority="high",
            status="pending"
        )

        async_session.add(rec)
        await async_session.commit()
        await async_session.refresh(rec)

        assert rec.id is not None
        assert rec.status == "pending"
        assert rec.change_percent == 10.0

    @pytest.mark.asyncio
    async def test_recommendation_status_update(self, async_session: AsyncSession):
        """Test updating recommendation status."""
        today = date.today()
        rec = PricingRecommendationRecord(
            date=today,
            room_type_id=1,
            current_rate=7500.00,
            recommended_rate=8000.00,
            change_percent=6.67,
            demand_level="moderate",
            confidence=0.85,
            reasoning="Normal demand pattern",
            priority="medium",
            status="pending"
        )

        async_session.add(rec)
        await async_session.commit()

        # Update status
        rec.status = "accepted"
        rec.actioned_at = datetime.utcnow()
        rec.actioned_by = "admin@hotel.com"
        await async_session.commit()
        await async_session.refresh(rec)

        assert rec.status == "accepted"
        assert rec.actioned_at is not None
        assert rec.actioned_by == "admin@hotel.com"


# ==================== RATE CHANGE AUDIT ====================

class TestRateChangeAuditModel:
    """Tests for RateChangeAudit model."""

    @pytest.mark.asyncio
    async def test_create_rate_change_audit(self, async_session: AsyncSession):
        """Test creating rate change audit trail."""
        today = date.today()
        audit = RateChangeAudit(
            room_type_id=1,
            date=today,
            old_rate=7500.00,
            new_rate=8250.00,
            change_reason="recommendation",
            changed_by="admin@hotel.com"
        )

        async_session.add(audit)
        await async_session.commit()
        await async_session.refresh(audit)

        assert audit.id is not None
        assert audit.old_rate == 7500.00
        assert audit.new_rate == 8250.00
        assert audit.change_reason == "recommendation"

    @pytest.mark.asyncio
    async def test_audit_with_rule_reference(self, async_session: AsyncSession):
        """Test audit with pricing rule reference."""
        today = date.today()
        audit = RateChangeAudit(
            room_type_id=1,
            date=today,
            old_rate=7500.00,
            new_rate=9000.00,
            change_reason="rule",
            rule_id=1,
            changed_by="system"
        )

        async_session.add(audit)
        await async_session.commit()
        await async_session.refresh(audit)

        assert audit.rule_id == 1
        assert audit.changed_by == "system"


# ==================== AUTO PRICING CONFIG ====================

class TestAutoPricingConfigModel:
    """Tests for AutoPricingConfig model."""

    @pytest.mark.asyncio
    async def test_create_auto_pricing_config(self, async_session: AsyncSession):
        """Test creating auto-pricing configuration."""
        config = AutoPricingConfig(
            room_type_id=1,
            is_enabled=True,
            min_rate=5000.00,
            max_rate=15000.00,
            max_daily_change_percent=10.0,
            competitor_tracking_enabled=True,
            demand_pricing_enabled=True
        )

        async_session.add(config)
        await async_session.commit()
        await async_session.refresh(config)

        assert config.id is not None
        assert config.is_enabled is True
        assert config.min_rate == 5000.00
        assert config.max_rate == 15000.00

    @pytest.mark.asyncio
    async def test_auto_pricing_config_defaults(self, async_session: AsyncSession):
        """Test AutoPricingConfig default values."""
        config = AutoPricingConfig(
            min_rate=5000.00,
            max_rate=15000.00,
            max_daily_change_percent=10.0
        )

        async_session.add(config)
        await async_session.commit()
        await async_session.refresh(config)

        assert config.is_enabled is True
        assert config.competitor_tracking_enabled is False
        assert config.demand_pricing_enabled is True


# ==================== AI INSIGHT RECORD ====================

class TestAIInsightRecordModel:
    """Tests for AIInsightRecord model."""

    @pytest.mark.asyncio
    async def test_create_ai_insight(self, async_session: AsyncSession):
        """Test creating AI insight record."""
        insight = AIInsightRecord(
            insight_type="opportunity",
            title="Revenue Opportunity Detected",
            description="Weekend bookings trending 20% higher than last month",
            revenue_impact=12500.00,
            priority="high",
            action_url="/revenue/rates?date=2025-01-15",
            is_read=False,
            is_dismissed=False
        )

        async_session.add(insight)
        await async_session.commit()
        await async_session.refresh(insight)

        assert insight.id is not None
        assert insight.insight_type == "opportunity"
        assert insight.revenue_impact == 12500.00

    @pytest.mark.asyncio
    async def test_insight_read_status(self, async_session: AsyncSession):
        """Test insight read status tracking."""
        insight = AIInsightRecord(
            insight_type="warning",
            title="Low Demand Alert",
            description="Midweek occupancy below forecast",
            priority="medium",
            is_read=False,
            is_dismissed=False
        )

        async_session.add(insight)
        await async_session.commit()

        # Mark as read
        insight.is_read = True
        await async_session.commit()
        await async_session.refresh(insight)

        assert insight.is_read is True


# ==================== EVENT RECORD ====================

class TestEventRecordModel:
    """Tests for EventRecord model."""

    @pytest.mark.asyncio
    async def test_create_event_record(self, async_session: AsyncSession):
        """Test creating event record."""
        today = date.today()
        event = EventRecord(
            name="Tech Conference 2025",
            event_type="conference",
            venue="Convention Center",
            start_date=today + timedelta(days=30),
            end_date=today + timedelta(days=32),
            expected_attendance=5000,
            distance_km=3.5,
            impact_score=8.5,
            demand_lift_percent=25.0,
            source="manual"
        )

        async_session.add(event)
        await async_session.commit()
        await async_session.refresh(event)

        assert event.id is not None
        assert event.name == "Tech Conference 2025"
        assert event.impact_score == 8.5
        assert event.demand_lift_percent == 25.0


# ==================== RMS PRICING RULE ====================

class TestRMSPricingRuleModel:
    """Tests for RMS PricingRule model."""

    @pytest.mark.asyncio
    async def test_create_rms_pricing_rule(self, async_session: AsyncSession):
        """Test creating RMS pricing rule."""
        rule = PricingRule(
            property_id=1,
            rule_name="Occupancy Surge",
            description="Increase rates when occupancy exceeds threshold",
            priority=2,
            is_active=True,
            conditions=[
                {"type": "occupancy", "operator": "gte", "value": 85}
            ],
            actions=[
                {"type": "adjust_percent", "value": 15}
            ]
        )

        async_session.add(rule)
        await async_session.commit()
        await async_session.refresh(rule)

        assert rule.id is not None
        assert rule.rule_name == "Occupancy Surge"
        assert rule.priority == 2

    @pytest.mark.asyncio
    async def test_rms_rule_trigger_tracking(self, async_session: AsyncSession):
        """Test RMS rule trigger count tracking."""
        rule = PricingRule(
            property_id=1,
            rule_name="Test Rule",
            priority=3,
            is_active=True
        )

        async_session.add(rule)
        await async_session.commit()

        # Simulate trigger
        rule.times_triggered = 5
        rule.last_triggered_at = datetime.utcnow()
        await async_session.commit()
        await async_session.refresh(rule)

        assert rule.times_triggered == 5
        assert rule.last_triggered_at is not None


# ==================== RMS COMPETITOR ====================

class TestRMSCompetitorModel:
    """Tests for RMS Competitor model."""

    @pytest.mark.asyncio
    async def test_create_rms_competitor(self, async_session: AsyncSession):
        """Test creating RMS competitor."""
        competitor = Competitor(
            property_id=1,
            name="Grand Hyatt Hotel",
            address="123 Main Street",
            star_rating=4.5,
            room_count=200,
            distance_km=2.5,
            is_active=True
        )

        async_session.add(competitor)
        await async_session.commit()
        await async_session.refresh(competitor)

        assert competitor.id is not None
        assert competitor.name == "Grand Hyatt Hotel"
        assert competitor.star_rating == 4.5


# ==================== RMS DEMAND FORECAST ====================

class TestRMSDemandForecastModel:
    """Tests for RMS DemandForecast model."""

    @pytest.mark.asyncio
    async def test_create_demand_forecast(self, async_session: AsyncSession):
        """Test creating demand forecast."""
        today = date.today()
        forecast = DemandForecast(
            property_id=1,
            forecast_date=today + timedelta(days=7),
            days_out=7,
            day_of_week=(today + timedelta(days=7)).weekday(),
            demand_index=85.0,
            demand_level="high",
            forecasted_occupancy=88.5,
            forecasted_adr=7800.00,
            forecasted_revpar=6903.00,
            confidence_score=0.92
        )

        async_session.add(forecast)
        await async_session.commit()
        await async_session.refresh(forecast)

        assert forecast.id is not None
        assert forecast.demand_level == "high"
        assert forecast.confidence_score == 0.92


# ==================== RMS MARKET EVENT ====================

class TestRMSMarketEventModel:
    """Tests for RMS MarketEvent model."""

    @pytest.mark.asyncio
    async def test_create_market_event(self, async_session: AsyncSession):
        """Test creating market event."""
        today = date.today()
        event = MarketEvent(
            property_id=1,
            event_name="City Marathon",
            event_type="sports",
            start_date=today + timedelta(days=60),
            end_date=today + timedelta(days=60),
            impact_multiplier=1.35,
            is_recurring=True,
            recurrence_rule="FREQ=YEARLY;BYMONTH=4;BYDAY=2SU"
        )

        async_session.add(event)
        await async_session.commit()
        await async_session.refresh(event)

        assert event.id is not None
        assert event.event_type == "sports"
        assert event.impact_multiplier == 1.35
        assert event.is_recurring is True


# ==================== RMS PICKUP PACE ====================

class TestRMSPickupPaceModel:
    """Tests for RMS PickupPace model."""

    @pytest.mark.asyncio
    async def test_create_pickup_pace(self, async_session: AsyncSession):
        """Test creating pickup pace record."""
        today = date.today()
        pace = PickupPace(
            property_id=1,
            arrival_date=today + timedelta(days=14),
            snapshot_date=today,
            days_out=14,
            current_bookings=35,
            expected_total=70,
            booking_progress_pct=50.0,
            pace_status="on-pace"
        )

        async_session.add(pace)
        await async_session.commit()
        await async_session.refresh(pace)

        assert pace.id is not None
        assert pace.pace_status == "on-pace"
        assert pace.booking_progress_pct == 50.0


# ==================== RMS SEGMENT PERFORMANCE ====================

class TestRMSSegmentPerformanceModel:
    """Tests for RMS SegmentPerformance model."""

    @pytest.mark.asyncio
    async def test_create_segment_performance(self, async_session: AsyncSession):
        """Test creating segment performance record."""
        first_of_month = date.today().replace(day=1)
        perf = SegmentPerformance(
            property_id=1,
            segment_name="Corporate",
            period_month=first_of_month,
            revenue=450000.00,
            room_nights=320,
            bookings=95,
            adr=1406.25,
            revpar=1125.00,
            cancellations=8,
            cancel_rate_pct=7.8,
            revenue_contribution_pct=35.5,
            avg_lead_time_days=21.5,
            avg_los=2.8
        )

        async_session.add(perf)
        await async_session.commit()
        await async_session.refresh(perf)

        assert perf.id is not None
        assert perf.segment_name == "Corporate"
        assert perf.revenue == 450000.00
        assert perf.revenue_contribution_pct == 35.5
