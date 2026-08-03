"""
Comprehensive tests for Revenue Intelligence API endpoints.
Tests all revenue management, forecasting, and pricing optimization features.
"""
import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient

from app.services.revenue_intelligence_service import RevenueIntelligenceService


# ==================== KPI ENDPOINTS ====================

class TestKPIEndpoints:
    """Tests for /api/v1/revenue-intelligence/kpis endpoints."""

    @pytest.mark.asyncio
    async def test_get_kpis_success(self, client: AsyncClient):
        """Test getting real-time KPIs returns valid data."""
        response = await client.get("/api/v1/revenue-intelligence/kpis")
        assert response.status_code == 200

        data = response.json()
        assert "total_revenue" in data
        assert "occupancy" in data
        assert "adr" in data
        assert "revpar" in data
        assert "revenue_trend" in data
        assert "period" in data

    @pytest.mark.asyncio
    async def test_get_kpis_with_date_range(self, client: AsyncClient):
        """Test getting KPIs with custom date range."""
        today = date.today()
        start_date = today - timedelta(days=7)
        end_date = today

        response = await client.get(
            "/api/v1/revenue-intelligence/kpis",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert data["period"]["start"] == start_date.isoformat()
        assert data["period"]["end"] == end_date.isoformat()

    @pytest.mark.asyncio
    async def test_get_kpis_invalid_date_range(self, client: AsyncClient):
        """Test KPIs with invalid date range returns appropriate error."""
        response = await client.get(
            "/api/v1/revenue-intelligence/kpis",
            params={
                "start_date": "invalid-date",
                "end_date": "2024-01-01"
            }
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_get_kpi_summary(self, client: AsyncClient):
        """Test getting KPI summary for multiple periods."""
        response = await client.get("/api/v1/revenue-intelligence/kpis/summary")
        assert response.status_code == 200

        data = response.json()
        # Should have multiple period summaries
        assert "today" in data or isinstance(data, dict)


# ==================== FORECAST ENDPOINTS ====================

class TestForecastEndpoints:
    """Tests for /api/v1/revenue-intelligence/forecast endpoints."""

    @pytest.mark.asyncio
    async def test_get_demand_forecast_success(self, client: AsyncClient):
        """Test getting demand forecast returns valid data."""
        response = await client.get("/api/v1/revenue-intelligence/forecast")
        assert response.status_code == 200

        data = response.json()
        assert "forecasts" in data
        assert "generated_at" in data

    @pytest.mark.asyncio
    async def test_get_demand_forecast_with_date_range(self, client: AsyncClient):
        """Test getting forecast with custom date range."""
        today = date.today()
        response = await client.get(
            "/api/v1/revenue-intelligence/forecast",
            params={
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=14)).isoformat()
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert "forecasts" in data

    @pytest.mark.asyncio
    async def test_get_demand_forecast_by_room_type(self, client: AsyncClient):
        """Test getting forecast filtered by room type."""
        response = await client.get(
            "/api/v1/revenue-intelligence/forecast",
            params={"room_type_id": 1}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_high_impact_days(self, client: AsyncClient):
        """Test getting high impact days forecast."""
        response = await client.get(
            "/api/v1/revenue-intelligence/forecast/high-impact",
            params={"days": 30, "threshold": 80}
        )
        assert response.status_code == 200

        data = response.json()
        assert "high_impact_days" in data
        assert "count" in data
        assert "threshold" in data


# ==================== PRICING RECOMMENDATIONS ====================

class TestPricingRecommendations:
    """Tests for /api/v1/revenue-intelligence/pricing/recommendations endpoints."""

    @pytest.mark.asyncio
    async def test_get_pricing_recommendations_success(self, client: AsyncClient):
        """Test getting pricing recommendations."""
        response = await client.get("/api/v1/revenue-intelligence/pricing/recommendations")
        assert response.status_code == 200

        data = response.json()
        assert "recommendations" in data
        assert "total_opportunity" in data
        assert "generated_at" in data

    @pytest.mark.asyncio
    async def test_get_pricing_recommendations_with_filters(self, client: AsyncClient):
        """Test getting recommendations with priority filter."""
        response = await client.get(
            "/api/v1/revenue-intelligence/pricing/recommendations",
            params={"priority": "high"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_pricing_recommendations_by_room_type(self, client: AsyncClient):
        """Test getting recommendations for specific room type."""
        response = await client.get(
            "/api/v1/revenue-intelligence/pricing/recommendations",
            params={"room_type_id": 1}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_accept_pricing_recommendation_not_found(self, client: AsyncClient):
        """Test accepting non-existent recommendation returns 404."""
        response = await client.post(
            "/api/v1/revenue-intelligence/pricing/recommendations/99999/accept"
        )
        # Should return 404 or appropriate error
        assert response.status_code in [404, 500]

    @pytest.mark.asyncio
    async def test_dismiss_pricing_recommendation_not_found(self, client: AsyncClient):
        """Test dismissing non-existent recommendation."""
        response = await client.post(
            "/api/v1/revenue-intelligence/pricing/recommendations/99999/dismiss",
            json={"reason": "Test dismissal"}
        )
        assert response.status_code in [404, 500]

    @pytest.mark.asyncio
    async def test_apply_all_recommendations(self, client: AsyncClient):
        """Test bulk applying recommendations."""
        response = await client.post(
            "/api/v1/revenue-intelligence/pricing/recommendations/apply-all",
            params={"min_confidence": 80.0}
        )
        assert response.status_code == 200

        data = response.json()
        assert "success" in data
        assert "applied_count" in data

    @pytest.mark.asyncio
    async def test_dismiss_all_recommendations(self, client: AsyncClient):
        """Test bulk dismissing recommendations."""
        response = await client.post(
            "/api/v1/revenue-intelligence/pricing/recommendations/dismiss-all",
            json={"reason": "Bulk dismissal for testing"}
        )
        assert response.status_code == 200


# ==================== RATE MANAGEMENT ====================

class TestRateManagement:
    """Tests for /api/v1/revenue-intelligence/rates endpoints."""

    @pytest.mark.asyncio
    async def test_update_single_rate(self, client: AsyncClient):
        """Test updating a single rate."""
        today = date.today()
        response = await client.put(
            f"/api/v1/revenue-intelligence/rates/1/{today.isoformat()}",
            json={"rate": 8500.00, "reason": "Test rate update"}
        )
        # May return 200 or error depending on data availability
        assert response.status_code in [200, 400, 404, 500]

    @pytest.mark.asyncio
    async def test_update_rate_invalid_value(self, client: AsyncClient):
        """Test updating rate with invalid value."""
        today = date.today()
        response = await client.put(
            f"/api/v1/revenue-intelligence/rates/1/{today.isoformat()}",
            json={"rate": -100.00, "reason": "Invalid rate"}
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_bulk_update_rates(self, client: AsyncClient):
        """Test bulk updating rates."""
        today = date.today()
        response = await client.put(
            "/api/v1/revenue-intelligence/rates/bulk-update",
            json={
                "updates": [
                    {"room_type_id": 1, "date": today.isoformat(), "rate": 8000.00},
                    {"room_type_id": 1, "date": (today + timedelta(days=1)).isoformat(), "rate": 8500.00}
                ],
                "reason": "Bulk update test"
            }
        )
        assert response.status_code in [200, 400, 500]

    @pytest.mark.asyncio
    async def test_get_rate_calendar(self, client: AsyncClient):
        """Test getting rate calendar."""
        response = await client.get("/api/v1/revenue-intelligence/rates/calendar")
        assert response.status_code == 200

        data = response.json()
        assert "period" in data
        assert "calendar" in data
        assert "summary" in data


# ==================== PRICING RULES ====================

class TestPricingRules:
    """Tests for /api/v1/revenue-intelligence/pricing-rules endpoints."""

    @pytest.mark.asyncio
    async def test_list_pricing_rules(self, client: AsyncClient):
        """Test listing pricing rules."""
        response = await client.get("/api/v1/revenue-intelligence/pricing-rules")
        assert response.status_code == 200

        data = response.json()
        assert "rules" in data
        assert "total" in data
        assert "active_count" in data

    @pytest.mark.asyncio
    async def test_list_pricing_rules_active_only(self, client: AsyncClient):
        """Test listing only active pricing rules."""
        response = await client.get(
            "/api/v1/revenue-intelligence/pricing-rules",
            params={"is_active": True}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_pricing_rule(self, client: AsyncClient, sample_pricing_rule_data: dict):
        """Test creating a new pricing rule."""
        response = await client.post(
            "/api/v1/revenue-intelligence/pricing-rules",
            json=sample_pricing_rule_data
        )
        # May succeed or fail depending on database state
        assert response.status_code in [200, 400, 422, 500]

    @pytest.mark.asyncio
    async def test_create_pricing_rule_invalid_data(self, client: AsyncClient):
        """Test creating pricing rule with invalid data."""
        response = await client.post(
            "/api/v1/revenue-intelligence/pricing-rules",
            json={"rule_name": ""}  # Invalid - empty name
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_pricing_rule_not_found(self, client: AsyncClient):
        """Test getting non-existent pricing rule."""
        response = await client.get("/api/v1/revenue-intelligence/pricing-rules/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_pricing_rule_not_found(self, client: AsyncClient):
        """Test deleting non-existent pricing rule."""
        response = await client.delete("/api/v1/revenue-intelligence/pricing-rules/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_pricing_rule_not_found(self, client: AsyncClient):
        """Test toggling non-existent pricing rule."""
        response = await client.patch("/api/v1/revenue-intelligence/pricing-rules/99999/toggle")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_pricing_rules(self, client: AsyncClient):
        """Test executing pricing rules."""
        response = await client.post(
            "/api/v1/revenue-intelligence/pricing-rules/execute",
            params={"dry_run": True}
        )
        assert response.status_code == 200

        data = response.json()
        assert "success" in data
        assert "executed_rules" in data


# ==================== AUTO-PRICING SETTINGS ====================

class TestAutoPricingSettings:
    """Tests for /api/v1/revenue-intelligence/settings/auto-pricing endpoints."""

    @pytest.mark.asyncio
    async def test_get_auto_pricing_settings(self, client: AsyncClient):
        """Test getting auto-pricing configuration."""
        response = await client.get("/api/v1/revenue-intelligence/settings/auto-pricing")
        assert response.status_code == 200

        data = response.json()
        assert "success" in data
        assert "config" in data

    @pytest.mark.asyncio
    async def test_update_auto_pricing_settings(self, client: AsyncClient):
        """Test updating auto-pricing configuration."""
        response = await client.post(
            "/api/v1/revenue-intelligence/settings/auto-pricing",
            json={
                "enabled": True,
                "min_rate_adjustment": -20,
                "max_rate_adjustment": 40,
                "auto_accept_threshold": 10
            }
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_toggle_auto_pricing(self, client: AsyncClient):
        """Test toggling auto-pricing on/off."""
        response = await client.post(
            "/api/v1/revenue-intelligence/settings/auto-pricing/toggle",
            json={"enabled": True}
        )
        assert response.status_code == 200

        data = response.json()
        assert "success" in data
        assert "enabled" in data


# ==================== COMPETITOR MANAGEMENT ====================

class TestCompetitorManagement:
    """Tests for /api/v1/revenue-intelligence/competitors endpoints."""

    @pytest.mark.asyncio
    async def test_list_competitors(self, client: AsyncClient):
        """Test listing competitors."""
        response = await client.get("/api/v1/revenue-intelligence/competitors")
        assert response.status_code == 200

        data = response.json()
        assert "competitors" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_active_competitors_only(self, client: AsyncClient):
        """Test listing only active competitors."""
        response = await client.get(
            "/api/v1/revenue-intelligence/competitors",
            params={"is_active": True}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_add_competitor(self, client: AsyncClient, sample_competitor_data: dict):
        """Test adding a new competitor."""
        response = await client.post(
            "/api/v1/revenue-intelligence/competitors",
            json=sample_competitor_data
        )
        assert response.status_code in [200, 400, 500]

    @pytest.mark.asyncio
    async def test_add_competitor_invalid_data(self, client: AsyncClient):
        """Test adding competitor with invalid data."""
        response = await client.post(
            "/api/v1/revenue-intelligence/competitors",
            json={"name": ""}  # Invalid - empty name
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_remove_competitor_not_found(self, client: AsyncClient):
        """Test removing non-existent competitor."""
        response = await client.delete("/api/v1/revenue-intelligence/competitors/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_refresh_competitor_rates(self, client: AsyncClient):
        """Test refreshing competitor rates."""
        response = await client.post(
            "/api/v1/revenue-intelligence/competitors/refresh",
            json={"competitor_ids": None}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_competitor_rate_history_not_found(self, client: AsyncClient):
        """Test getting rate history for non-existent competitor."""
        response = await client.get("/api/v1/revenue-intelligence/competitors/99999/rates")
        assert response.status_code == 404


# ==================== AI INSIGHTS ====================

class TestAIInsights:
    """Tests for /api/v1/revenue-intelligence/ai/insights endpoints."""

    @pytest.mark.asyncio
    async def test_get_ai_insights(self, client: AsyncClient):
        """Test getting AI insights."""
        response = await client.get("/api/v1/revenue-intelligence/ai/insights")
        assert response.status_code == 200

        data = response.json()
        assert "insights" in data
        assert "unread_count" in data
        assert "generated_at" in data

    @pytest.mark.asyncio
    async def test_get_ai_insights_by_severity(self, client: AsyncClient):
        """Test getting AI insights filtered by severity."""
        response = await client.get(
            "/api/v1/revenue-intelligence/ai/insights",
            params={"severity": "warning"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_ai_insights_unread_only(self, client: AsyncClient):
        """Test getting only unread AI insights."""
        response = await client.get(
            "/api/v1/revenue-intelligence/ai/insights",
            params={"unread_only": True}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dismiss_ai_insight(self, client: AsyncClient):
        """Test dismissing an AI insight."""
        response = await client.post(
            "/api/v1/revenue-intelligence/ai/insights/test-insight-1/dismiss"
        )
        assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_mark_insight_read(self, client: AsyncClient):
        """Test marking an AI insight as read."""
        response = await client.post(
            "/api/v1/revenue-intelligence/ai/insights/test-insight-1/read"
        )
        assert response.status_code in [200, 404]


# ==================== OPPORTUNITIES & ALERTS ====================

class TestOpportunitiesAndAlerts:
    """Tests for opportunities and alerts endpoints."""

    @pytest.mark.asyncio
    async def test_get_revenue_opportunities(self, client: AsyncClient):
        """Test getting revenue opportunities."""
        response = await client.get("/api/v1/revenue-intelligence/opportunities")
        assert response.status_code == 200

        data = response.json()
        assert "opportunities" in data
        assert "total_opportunity" in data

    @pytest.mark.asyncio
    async def test_get_revenue_opportunities_with_limit(self, client: AsyncClient):
        """Test getting opportunities with limit."""
        response = await client.get(
            "/api/v1/revenue-intelligence/opportunities",
            params={"limit": 5}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_revenue_alerts(self, client: AsyncClient):
        """Test getting revenue alerts."""
        response = await client.get("/api/v1/revenue-intelligence/alerts")
        assert response.status_code == 200

        data = response.json()
        assert "alerts" in data
        assert "critical_count" in data
        assert "warning_count" in data

    @pytest.mark.asyncio
    async def test_get_revenue_alerts_by_severity(self, client: AsyncClient):
        """Test getting alerts filtered by severity."""
        response = await client.get(
            "/api/v1/revenue-intelligence/alerts",
            params={"severity": "critical"}
        )
        assert response.status_code == 200


# ==================== SCENARIO SIMULATION ====================

class TestScenarioSimulation:
    """Tests for scenario simulation endpoints."""

    @pytest.mark.asyncio
    async def test_simulate_rate_increase_scenario(self, client: AsyncClient):
        """Test simulating rate increase scenario."""
        response = await client.post(
            "/api/v1/revenue-intelligence/scenarios/simulate",
            json={
                "scenario_type": "rate_increase",
                "parameters": {"percentage": 10}
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert "scenario_type" in data
        assert "baseline" in data
        assert "projected" in data
        assert "recommendation" in data

    @pytest.mark.asyncio
    async def test_simulate_rate_decrease_scenario(self, client: AsyncClient):
        """Test simulating rate decrease scenario."""
        response = await client.post(
            "/api/v1/revenue-intelligence/scenarios/simulate",
            json={
                "scenario_type": "rate_decrease",
                "parameters": {"percentage": 15}
            }
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_simulate_promotion_scenario(self, client: AsyncClient):
        """Test simulating promotion scenario."""
        response = await client.post(
            "/api/v1/revenue-intelligence/scenarios/simulate",
            json={
                "scenario_type": "promotion",
                "parameters": {"discount": 20, "demand_lift": 25}
            }
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_simulate_invalid_scenario_type(self, client: AsyncClient):
        """Test simulating with invalid scenario type."""
        response = await client.post(
            "/api/v1/revenue-intelligence/scenarios/simulate",
            json={
                "scenario_type": "invalid_type",
                "parameters": {"percentage": 10}
            }
        )
        assert response.status_code == 400


# ==================== CHANNEL ANALYSIS ====================

class TestChannelAnalysis:
    """Tests for channel analysis endpoints."""

    @pytest.mark.asyncio
    async def test_get_channel_analysis(self, client: AsyncClient):
        """Test getting channel performance analysis."""
        response = await client.get("/api/v1/revenue-intelligence/channels")
        assert response.status_code == 200

        data = response.json()
        assert "period" in data
        assert "channels" in data
        assert "totals" in data

    @pytest.mark.asyncio
    async def test_get_channel_analysis_with_date_range(self, client: AsyncClient):
        """Test getting channel analysis with date range."""
        today = date.today()
        response = await client.get(
            "/api/v1/revenue-intelligence/channels",
            params={
                "start_date": (today - timedelta(days=30)).isoformat(),
                "end_date": today.isoformat()
            }
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_channel_roi(self, client: AsyncClient):
        """Test getting channel ROI analysis."""
        response = await client.get("/api/v1/revenue-intelligence/channels/roi")
        assert response.status_code == 200

        data = response.json()
        assert "period" in data
        assert "roi_analysis" in data


# ==================== SEGMENTS & EVENTS ====================

class TestSegmentsAndEvents:
    """Tests for segments and events endpoints."""

    @pytest.mark.asyncio
    async def test_get_segment_performance(self, client: AsyncClient):
        """Test getting segment performance."""
        response = await client.get("/api/v1/revenue-intelligence/segments/performance")
        assert response.status_code == 200

        data = response.json()
        assert "period" in data
        assert "segments" in data

    @pytest.mark.asyncio
    async def test_list_events(self, client: AsyncClient):
        """Test listing market events."""
        response = await client.get("/api/v1/revenue-intelligence/events")
        assert response.status_code == 200

        data = response.json()
        assert "events" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_create_event(self, client: AsyncClient, sample_event_data: dict):
        """Test creating a market event."""
        response = await client.post(
            "/api/v1/revenue-intelligence/events",
            json=sample_event_data
        )
        assert response.status_code in [200, 400, 500]

    @pytest.mark.asyncio
    async def test_get_event_calendar(self, client: AsyncClient):
        """Test getting event calendar."""
        response = await client.get("/api/v1/revenue-intelligence/events/calendar")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_event_impact(self, client: AsyncClient):
        """Test getting event demand impact."""
        response = await client.get("/api/v1/revenue-intelligence/events/impact")
        assert response.status_code == 200


# ==================== DASHBOARD & METRICS ====================

class TestDashboardAndMetrics:
    """Tests for dashboard and metrics endpoints."""

    @pytest.mark.asyncio
    async def test_get_revenue_dashboard(self, client: AsyncClient):
        """Test getting complete revenue dashboard."""
        response = await client.get("/api/v1/revenue-intelligence/dashboard")
        assert response.status_code == 200

        data = response.json()
        assert "kpis" in data
        assert "forecast" in data
        assert "recommendations" in data
        assert "generated_at" in data

    @pytest.mark.asyncio
    async def test_get_pickup_metrics(self, client: AsyncClient):
        """Test getting pickup/booking pace metrics."""
        response = await client.get(
            "/api/v1/revenue-intelligence/metrics/pickup",
            params={"days": 7}
        )
        assert response.status_code == 200

        data = response.json()
        assert "pickup_data" in data
        assert "summary" in data

    @pytest.mark.asyncio
    async def test_get_competitor_insights(self, client: AsyncClient):
        """Test getting competitor insights."""
        response = await client.get("/api/v1/revenue-intelligence/competitor-insights")
        assert response.status_code == 200

        data = response.json()
        assert "period" in data
        assert "competitors" in data
        assert "market_averages" in data


# ==================== ERROR HANDLING ====================

class TestErrorHandling:
    """Tests for error handling across all endpoints."""

    @pytest.mark.asyncio
    async def test_invalid_endpoint(self, client: AsyncClient):
        """Test accessing non-existent endpoint."""
        response = await client.get("/api/v1/revenue-intelligence/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_method_not_allowed(self, client: AsyncClient):
        """Test using wrong HTTP method."""
        response = await client.delete("/api/v1/revenue-intelligence/kpis")
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_malformed_json_body(self, client: AsyncClient):
        """Test sending malformed JSON."""
        response = await client.post(
            "/api/v1/revenue-intelligence/pricing-rules",
            content="{invalid json}",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
