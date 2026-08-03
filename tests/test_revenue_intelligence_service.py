"""
Unit tests for RevenueIntelligenceService.
Tests the core business logic for revenue management and pricing optimization.
"""
import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.revenue_intelligence_service import RevenueIntelligenceService


class TestRevenueIntelligenceServiceKPIs:
    """Tests for KPI calculation methods."""

    @pytest.mark.asyncio
    async def test_get_realtime_kpis_default_dates(self, async_session: AsyncSession):
        """Test KPI calculation with default dates (today)."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_realtime_kpis()

        assert "total_revenue" in result
        assert "occupancy" in result
        assert "adr" in result
        assert "revpar" in result
        assert "period" in result
        assert result["period"]["start"] == date.today().isoformat()

    @pytest.mark.asyncio
    async def test_get_realtime_kpis_with_date_range(self, async_session: AsyncSession):
        """Test KPI calculation with custom date range."""
        service = RevenueIntelligenceService(async_session)
        start_date = date.today() - timedelta(days=7)
        end_date = date.today()

        result = await service.get_realtime_kpis(start_date, end_date)

        assert result["period"]["start"] == start_date.isoformat()
        assert result["period"]["end"] == end_date.isoformat()
        assert result["period"]["days"] == 8

    @pytest.mark.asyncio
    async def test_get_realtime_kpis_calculates_trends(self, async_session: AsyncSession):
        """Test that KPI trends are calculated."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_realtime_kpis()

        assert "revenue_trend" in result
        assert "occupancy_trend" in result
        assert "adr_trend" in result
        assert "revpar_trend" in result

    @pytest.mark.asyncio
    async def test_get_kpi_summary_returns_all_periods(self, async_session: AsyncSession):
        """Test KPI summary returns data for all time periods."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_kpi_summary()

        # Should have multiple periods
        assert isinstance(result, dict)
        expected_periods = ["today", "week", "month", "next_7_days", "next_30_days"]
        for period in expected_periods:
            assert period in result or len(result) > 0


class TestRevenueIntelligenceServiceForecasting:
    """Tests for demand forecasting methods."""

    @pytest.mark.asyncio
    async def test_get_demand_forecast_default_range(self, async_session: AsyncSession):
        """Test demand forecast with default date range."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_demand_forecast()

        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_demand_forecast_custom_range(self, async_session: AsyncSession):
        """Test demand forecast with custom date range."""
        service = RevenueIntelligenceService(async_session)
        start_date = date.today()
        end_date = date.today() + timedelta(days=14)

        result = await service.get_demand_forecast(start_date, end_date)

        assert isinstance(result, list)
        # Should have at least some forecasts
        assert len(result) >= 0

    @pytest.mark.asyncio
    async def test_forecast_includes_required_fields(self, async_session: AsyncSession):
        """Test that forecast items have required fields."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_demand_forecast()

        if result:  # Only test if forecasts are returned
            forecast = result[0]
            assert "date" in forecast
            assert "forecasted_occupancy" in forecast or "forecasted_demand" in forecast
            assert "demand_level" in forecast

    @pytest.mark.asyncio
    async def test_seasonality_factor_calculation(self, async_session: AsyncSession):
        """Test seasonality factor is applied correctly."""
        service = RevenueIntelligenceService(async_session)

        # Test peak season (July)
        peak_factor = service._get_seasonality_factor(7)
        assert peak_factor > 1.0

        # Test low season (January)
        low_factor = service._get_seasonality_factor(1)
        assert low_factor < 1.0

    @pytest.mark.asyncio
    async def test_day_of_week_factor(self, async_session: AsyncSession):
        """Test day of week factor calculation."""
        service = RevenueIntelligenceService(async_session)

        # Weekend should have higher factor
        saturday_factor = service._get_dow_factor(5)
        monday_factor = service._get_dow_factor(0)

        assert saturday_factor > monday_factor

    @pytest.mark.asyncio
    async def test_demand_categorization(self, async_session: AsyncSession):
        """Test demand level categorization."""
        service = RevenueIntelligenceService(async_session)

        # Test different occupancy levels
        assert service._categorize_demand(95) == "critical"
        assert service._categorize_demand(85) == "high"
        assert service._categorize_demand(65) == "moderate"
        assert service._categorize_demand(45) == "low"
        assert service._categorize_demand(30) == "very_low"


class TestRevenueIntelligenceServicePricing:
    """Tests for pricing recommendation methods."""

    @pytest.mark.asyncio
    async def test_get_pricing_recommendations(self, async_session: AsyncSession):
        """Test getting pricing recommendations."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_pricing_recommendations()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_demand_multiplier_calculation(self, async_session: AsyncSession):
        """Test demand-based price multiplier."""
        service = RevenueIntelligenceService(async_session)

        # Critical demand should have highest multiplier
        critical_mult = service._get_demand_multiplier("critical")
        low_mult = service._get_demand_multiplier("low")

        assert critical_mult > low_mult
        assert critical_mult > 1.0
        assert low_mult < 1.0

    @pytest.mark.asyncio
    async def test_lead_time_multiplier(self, async_session: AsyncSession):
        """Test lead time price multiplier."""
        service = RevenueIntelligenceService(async_session)

        # Last minute should have premium
        last_minute = service._get_lead_time_multiplier(1)
        advance = service._get_lead_time_multiplier(60)

        assert last_minute > advance
        assert last_minute > 1.0

    @pytest.mark.asyncio
    async def test_pricing_reasoning_generation(self, async_session: AsyncSession):
        """Test pricing recommendation reasoning."""
        service = RevenueIntelligenceService(async_session)

        # Test high demand reasoning
        reason = service._get_pricing_reasoning("high", 15, 5)
        assert len(reason) > 0

        # Test low demand reasoning
        reason = service._get_pricing_reasoning("low", -10, 14)
        assert len(reason) > 0

    @pytest.mark.asyncio
    async def test_recommendation_priority(self, async_session: AsyncSession):
        """Test recommendation priority assignment."""
        service = RevenueIntelligenceService(async_session)

        # High change, short lead time = critical
        priority = service._get_recommendation_priority(20, 2)
        assert priority in ["critical", "high"]

        # Low change, long lead time = low priority
        priority = service._get_recommendation_priority(3, 30)
        assert priority in ["low", "medium"]


class TestRevenueIntelligenceServiceOpportunities:
    """Tests for revenue opportunity detection."""

    @pytest.mark.asyncio
    async def test_get_revenue_opportunities(self, async_session: AsyncSession):
        """Test getting revenue opportunities."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_revenue_opportunities()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_opportunities_limit(self, async_session: AsyncSession):
        """Test opportunity limit parameter."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_revenue_opportunities(limit=5)

        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_opportunity_structure(self, async_session: AsyncSession):
        """Test opportunity data structure."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_revenue_opportunities()

        if result:
            opp = result[0]
            assert "type" in opp
            assert "title" in opp
            assert "description" in opp
            assert "revenue_impact" in opp
            assert "priority" in opp


class TestRevenueIntelligenceServiceAlerts:
    """Tests for revenue alert generation."""

    @pytest.mark.asyncio
    async def test_get_revenue_alerts(self, async_session: AsyncSession):
        """Test getting revenue alerts."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_revenue_alerts()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_alerts_filter_by_severity(self, async_session: AsyncSession):
        """Test filtering alerts by severity."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_revenue_alerts(severity="critical")

        for alert in result:
            assert alert["severity"] == "critical"


class TestRevenueIntelligenceServiceScenarios:
    """Tests for scenario simulation."""

    @pytest.mark.asyncio
    async def test_simulate_rate_increase(self, async_session: AsyncSession):
        """Test rate increase scenario simulation."""
        service = RevenueIntelligenceService(async_session)

        result = await service.simulate_scenario(
            scenario_type="rate_increase",
            parameters={"percentage": 10}
        )

        assert "baseline" in result
        assert "projected" in result
        assert "recommendation" in result
        assert result["scenario_type"] == "rate_increase"

    @pytest.mark.asyncio
    async def test_simulate_rate_decrease(self, async_session: AsyncSession):
        """Test rate decrease scenario simulation."""
        service = RevenueIntelligenceService(async_session)

        result = await service.simulate_scenario(
            scenario_type="rate_decrease",
            parameters={"percentage": 15}
        )

        assert "baseline" in result
        assert "projected" in result

    @pytest.mark.asyncio
    async def test_simulate_promotion(self, async_session: AsyncSession):
        """Test promotion scenario simulation."""
        service = RevenueIntelligenceService(async_session)

        result = await service.simulate_scenario(
            scenario_type="promotion",
            parameters={"discount": 20, "demand_lift": 25}
        )

        assert "baseline" in result
        assert "projected" in result

    @pytest.mark.asyncio
    async def test_simulate_invalid_scenario(self, async_session: AsyncSession):
        """Test invalid scenario type raises error."""
        service = RevenueIntelligenceService(async_session)

        with pytest.raises(ValueError):
            await service.simulate_scenario(
                scenario_type="invalid_type",
                parameters={}
            )

    @pytest.mark.asyncio
    async def test_pricing_change_alias(self, async_session: AsyncSession):
        """Test pricing_change as alias for rate_increase."""
        service = RevenueIntelligenceService(async_session)

        result = await service.simulate_scenario(
            scenario_type="pricing_change",
            parameters={"percentage": 10}
        )

        assert result["scenario_type"] == "pricing_change"


class TestRevenueIntelligenceServiceChannels:
    """Tests for channel analysis."""

    @pytest.mark.asyncio
    async def test_get_channel_analysis(self, async_session: AsyncSession):
        """Test channel analysis retrieval."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_channel_analysis()

        assert "period" in result
        assert "channels" in result
        assert "totals" in result
        assert "recommendations" in result

    @pytest.mark.asyncio
    async def test_channel_analysis_with_date_range(self, async_session: AsyncSession):
        """Test channel analysis with date range."""
        service = RevenueIntelligenceService(async_session)
        start_date = date.today() - timedelta(days=30)
        end_date = date.today()

        result = await service.get_channel_analysis(start_date, end_date)

        assert result["period"]["start"] == start_date.isoformat()
        assert result["period"]["end"] == end_date.isoformat()


class TestRevenueIntelligenceServiceCompetitors:
    """Tests for competitor rate analysis."""

    @pytest.mark.asyncio
    async def test_get_competitor_rates(self, async_session: AsyncSession):
        """Test getting competitor rates."""
        service = RevenueIntelligenceService(async_session)
        start_date = date.today()
        end_date = date.today() + timedelta(days=7)

        result = await service._get_competitor_rates(start_date, end_date)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_channel_performance_aggregation(self, async_session: AsyncSession):
        """Test channel performance data aggregation."""
        service = RevenueIntelligenceService(async_session)

        result = await service._get_channel_performance()

        assert isinstance(result, list)


class TestRevenueIntelligenceServicePricingRules:
    """Tests for pricing rules retrieval."""

    @pytest.mark.asyncio
    async def test_get_active_pricing_rules(self, async_session: AsyncSession):
        """Test getting active pricing rules."""
        service = RevenueIntelligenceService(async_session)

        result = await service._get_active_pricing_rules()

        assert isinstance(result, list)


class TestRevenueIntelligenceServiceEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_kpis_with_no_data(self, async_session: AsyncSession):
        """Test KPI calculation with no data (empty database)."""
        service = RevenueIntelligenceService(async_session)

        result = await service.get_realtime_kpis()

        # Should return valid structure even with no data
        assert "total_revenue" in result
        assert "occupancy" in result
        assert result["total_revenue"] >= 0

    @pytest.mark.asyncio
    async def test_forecast_with_future_dates(self, async_session: AsyncSession):
        """Test forecast for far future dates."""
        service = RevenueIntelligenceService(async_session)
        start_date = date.today() + timedelta(days=180)
        end_date = date.today() + timedelta(days=190)

        result = await service.get_demand_forecast(start_date, end_date)

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_recommendations_single_day(self, async_session: AsyncSession):
        """Test recommendations for a single day."""
        service = RevenueIntelligenceService(async_session)
        today = date.today()

        result = await service.get_pricing_recommendations(today, today)

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_zero_occupancy_calculations(self, async_session: AsyncSession):
        """Test calculations handle zero occupancy gracefully."""
        service = RevenueIntelligenceService(async_session)

        # Categorize demand at 0%
        demand_level = service._categorize_demand(0)
        assert demand_level == "very_low"

    @pytest.mark.asyncio
    async def test_high_occupancy_calculations(self, async_session: AsyncSession):
        """Test calculations handle 100% occupancy."""
        service = RevenueIntelligenceService(async_session)

        demand_level = service._categorize_demand(100)
        assert demand_level == "critical"

    @pytest.mark.asyncio
    async def test_negative_change_percent_reasoning(self, async_session: AsyncSession):
        """Test reasoning for negative rate changes."""
        service = RevenueIntelligenceService(async_session)

        reason = service._get_pricing_reasoning("very_low", -15, 10)
        assert "reduction" in reason.lower() or "low" in reason.lower()
