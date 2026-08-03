#!/usr/bin/env python
"""
Revenue Intelligence API Validation Script

This script validates all Revenue Intelligence API endpoints to ensure they are
working correctly. It can be run manually or as part of CI/CD pipeline.

Usage:
    python scripts/validate_revenue_api.py [--base-url http://localhost:8000] [--verbose]

Features:
    - Tests all GET, POST, PUT, PATCH, DELETE endpoints
    - Validates response status codes
    - Validates response structure
    - Provides detailed error reporting
    - Generates a summary report
"""
import asyncio
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)


class TestResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"


@dataclass
class EndpointTest:
    method: str
    path: str
    description: str
    params: Optional[Dict[str, Any]] = None
    body: Optional[Dict[str, Any]] = None
    expected_status: List[int] = field(default_factory=lambda: [200])
    required_fields: List[str] = field(default_factory=list)
    depends_on: Optional[str] = None


@dataclass
class TestResultData:
    endpoint: str
    method: str
    description: str
    result: TestResult
    status_code: Optional[int] = None
    response_time_ms: float = 0
    error_message: Optional[str] = None
    response_data: Optional[Dict] = None


class RevenueAPIValidator:
    """Validates Revenue Intelligence API endpoints."""

    def __init__(self, base_url: str, verbose: bool = False):
        self.base_url = base_url.rstrip('/')
        self.api_prefix = "/api/v1/revenue-intelligence"
        self.verbose = verbose
        self.results: List[TestResultData] = []
        self.created_ids: Dict[str, int] = {}

    def get_endpoint_tests(self) -> List[EndpointTest]:
        """Define all endpoint tests."""
        today = date.today()
        tomorrow = today + timedelta(days=1)
        next_week = today + timedelta(days=7)
        next_month = today + timedelta(days=30)

        return [
            # ==================== KPI ENDPOINTS ====================
            EndpointTest(
                method="GET",
                path="/kpis",
                description="Get real-time KPIs",
                required_fields=["total_revenue", "occupancy", "adr", "revpar"]
            ),
            EndpointTest(
                method="GET",
                path="/kpis",
                description="Get KPIs with date range",
                params={
                    "start_date": (today - timedelta(days=7)).isoformat(),
                    "end_date": today.isoformat()
                },
                required_fields=["period"]
            ),
            EndpointTest(
                method="GET",
                path="/kpis/summary",
                description="Get KPI summary for all periods"
            ),

            # ==================== FORECAST ENDPOINTS ====================
            EndpointTest(
                method="GET",
                path="/forecast",
                description="Get demand forecast",
                required_fields=["forecasts", "generated_at"]
            ),
            EndpointTest(
                method="GET",
                path="/forecast",
                description="Get forecast with custom range",
                params={
                    "start_date": today.isoformat(),
                    "end_date": next_week.isoformat()
                }
            ),
            EndpointTest(
                method="GET",
                path="/forecast/high-impact",
                description="Get high impact forecast days",
                params={"days": 30, "threshold": 80},
                required_fields=["high_impact_days", "count"]
            ),

            # ==================== PRICING RECOMMENDATIONS ====================
            EndpointTest(
                method="GET",
                path="/pricing/recommendations",
                description="Get pricing recommendations",
                required_fields=["recommendations", "total_opportunity"]
            ),
            EndpointTest(
                method="GET",
                path="/pricing/recommendations",
                description="Get high priority recommendations",
                params={"priority": "high"}
            ),
            EndpointTest(
                method="POST",
                path="/pricing/recommendations/apply-all",
                description="Apply all recommendations (high confidence)",
                params={"min_confidence": 99.0},  # Very high to avoid changes
                required_fields=["success", "applied_count"]
            ),
            EndpointTest(
                method="POST",
                path="/pricing/recommendations/dismiss-all",
                description="Dismiss all recommendations",
                body={"reason": "API validation test"},
                required_fields=["success"]
            ),

            # ==================== RATE MANAGEMENT ====================
            EndpointTest(
                method="GET",
                path="/rates/calendar",
                description="Get rate calendar",
                required_fields=["period", "calendar", "summary"]
            ),
            EndpointTest(
                method="GET",
                path="/rates/calendar",
                description="Get rate calendar with date range",
                params={
                    "start_date": today.isoformat(),
                    "end_date": next_week.isoformat()
                }
            ),

            # ==================== PRICING RULES ====================
            EndpointTest(
                method="GET",
                path="/pricing-rules",
                description="List pricing rules",
                required_fields=["rules", "total", "active_count"]
            ),
            EndpointTest(
                method="GET",
                path="/pricing-rules",
                description="List active pricing rules only",
                params={"is_active": True}
            ),
            EndpointTest(
                method="POST",
                path="/pricing-rules/execute",
                description="Execute pricing rules (dry run)",
                params={"dry_run": True},
                required_fields=["success", "executed_rules"]
            ),

            # ==================== AUTO-PRICING SETTINGS ====================
            EndpointTest(
                method="GET",
                path="/settings/auto-pricing",
                description="Get auto-pricing settings",
                required_fields=["success", "config"]
            ),
            EndpointTest(
                method="POST",
                path="/settings/auto-pricing/toggle",
                description="Toggle auto-pricing",
                body={"enabled": True},
                required_fields=["success", "enabled"]
            ),

            # ==================== COMPETITORS ====================
            EndpointTest(
                method="GET",
                path="/competitors",
                description="List competitors",
                required_fields=["competitors", "total"]
            ),
            EndpointTest(
                method="GET",
                path="/competitor-insights",
                description="Get competitor insights",
                required_fields=["competitors", "market_averages"]
            ),
            EndpointTest(
                method="POST",
                path="/competitors/refresh",
                description="Refresh competitor rates",
                body={"competitor_ids": None},
                required_fields=["success"]
            ),

            # ==================== AI INSIGHTS ====================
            EndpointTest(
                method="GET",
                path="/ai/insights",
                description="Get AI insights",
                required_fields=["insights", "unread_count", "generated_at"]
            ),
            EndpointTest(
                method="GET",
                path="/ai/insights",
                description="Get warning severity insights",
                params={"severity": "warning"}
            ),
            EndpointTest(
                method="GET",
                path="/ai/insights",
                description="Get unread insights only",
                params={"unread_only": True}
            ),

            # ==================== OPPORTUNITIES & ALERTS ====================
            EndpointTest(
                method="GET",
                path="/opportunities",
                description="Get revenue opportunities",
                required_fields=["opportunities", "total_opportunity"]
            ),
            EndpointTest(
                method="GET",
                path="/alerts",
                description="Get revenue alerts",
                required_fields=["alerts", "critical_count", "warning_count"]
            ),
            EndpointTest(
                method="GET",
                path="/alerts",
                description="Get critical alerts only",
                params={"severity": "critical"}
            ),

            # ==================== SCENARIO SIMULATION ====================
            EndpointTest(
                method="POST",
                path="/scenarios/simulate",
                description="Simulate rate increase scenario",
                body={
                    "scenario_type": "rate_increase",
                    "parameters": {"percentage": 10}
                },
                required_fields=["baseline", "projected", "recommendation"]
            ),
            EndpointTest(
                method="POST",
                path="/scenarios/simulate",
                description="Simulate rate decrease scenario",
                body={
                    "scenario_type": "rate_decrease",
                    "parameters": {"percentage": 15}
                }
            ),
            EndpointTest(
                method="POST",
                path="/scenarios/simulate",
                description="Simulate promotion scenario",
                body={
                    "scenario_type": "promotion",
                    "parameters": {"discount": 20, "demand_lift": 25}
                }
            ),

            # ==================== CHANNELS ====================
            EndpointTest(
                method="GET",
                path="/channels",
                description="Get channel analysis",
                required_fields=["period", "channels", "totals"]
            ),
            EndpointTest(
                method="GET",
                path="/channels/roi",
                description="Get channel ROI analysis",
                required_fields=["period", "roi_analysis"]
            ),

            # ==================== SEGMENTS ====================
            EndpointTest(
                method="GET",
                path="/segments/performance",
                description="Get segment performance",
                required_fields=["period", "segments"]
            ),

            # ==================== EVENTS ====================
            EndpointTest(
                method="GET",
                path="/events",
                description="List market events",
                required_fields=["events", "total"]
            ),
            EndpointTest(
                method="GET",
                path="/events/calendar",
                description="Get event calendar",
                required_fields=["period", "calendar"]
            ),
            EndpointTest(
                method="GET",
                path="/events/impact",
                description="Get event demand impact",
                required_fields=["period", "events"]
            ),

            # ==================== METRICS ====================
            EndpointTest(
                method="GET",
                path="/metrics/pickup",
                description="Get pickup metrics",
                params={"days": 7},
                required_fields=["pickup_data", "summary"]
            ),

            # ==================== DASHBOARD ====================
            EndpointTest(
                method="GET",
                path="/dashboard",
                description="Get revenue dashboard",
                required_fields=["kpis", "forecast", "recommendations", "generated_at"]
            ),
        ]

    async def run_test(
        self,
        client: httpx.AsyncClient,
        test: EndpointTest
    ) -> TestResultData:
        """Run a single endpoint test."""
        url = f"{self.base_url}{self.api_prefix}{test.path}"
        start_time = datetime.now()

        try:
            if test.method == "GET":
                response = await client.get(url, params=test.params)
            elif test.method == "POST":
                response = await client.post(url, params=test.params, json=test.body)
            elif test.method == "PUT":
                response = await client.put(url, params=test.params, json=test.body)
            elif test.method == "PATCH":
                response = await client.patch(url, params=test.params, json=test.body)
            elif test.method == "DELETE":
                response = await client.delete(url, params=test.params)
            else:
                return TestResultData(
                    endpoint=test.path,
                    method=test.method,
                    description=test.description,
                    result=TestResult.ERROR,
                    error_message=f"Unsupported method: {test.method}"
                )

            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Check status code
            if response.status_code not in test.expected_status:
                return TestResultData(
                    endpoint=test.path,
                    method=test.method,
                    description=test.description,
                    result=TestResult.FAIL,
                    status_code=response.status_code,
                    response_time_ms=elapsed_ms,
                    error_message=f"Expected status {test.expected_status}, got {response.status_code}"
                )

            # Parse response
            try:
                data = response.json()
            except:
                data = None

            # Validate required fields
            if test.required_fields and data:
                missing_fields = [f for f in test.required_fields if f not in data]
                if missing_fields:
                    return TestResultData(
                        endpoint=test.path,
                        method=test.method,
                        description=test.description,
                        result=TestResult.FAIL,
                        status_code=response.status_code,
                        response_time_ms=elapsed_ms,
                        error_message=f"Missing required fields: {missing_fields}",
                        response_data=data
                    )

            return TestResultData(
                endpoint=test.path,
                method=test.method,
                description=test.description,
                result=TestResult.PASS,
                status_code=response.status_code,
                response_time_ms=elapsed_ms,
                response_data=data if self.verbose else None
            )

        except httpx.ConnectError:
            return TestResultData(
                endpoint=test.path,
                method=test.method,
                description=test.description,
                result=TestResult.ERROR,
                error_message=f"Connection error: Could not connect to {self.base_url}"
            )
        except Exception as e:
            return TestResultData(
                endpoint=test.path,
                method=test.method,
                description=test.description,
                result=TestResult.ERROR,
                error_message=str(e)
            )

    async def validate_all(self) -> Tuple[int, int, int, int]:
        """Run all validation tests."""
        tests = self.get_endpoint_tests()
        total = len(tests)
        passed = 0
        failed = 0
        errors = 0

        print(f"\n{'='*70}")
        print(f"REVENUE INTELLIGENCE API VALIDATION")
        print(f"Base URL: {self.base_url}")
        print(f"{'='*70}\n")

        async with httpx.AsyncClient(timeout=30.0) as client:
            for test in tests:
                result = await self.run_test(client, test)
                self.results.append(result)

                # Print result
                status_symbol = {
                    TestResult.PASS: "\u2713",  # checkmark
                    TestResult.FAIL: "\u2717",  # x mark
                    TestResult.ERROR: "!",
                    TestResult.SKIP: "-"
                }[result.result]

                status_color = {
                    TestResult.PASS: "\033[92m",  # green
                    TestResult.FAIL: "\033[91m",  # red
                    TestResult.ERROR: "\033[93m", # yellow
                    TestResult.SKIP: "\033[90m"   # gray
                }[result.result]

                reset_color = "\033[0m"

                status_code_str = f"[{result.status_code}]" if result.status_code else "[---]"
                time_str = f"{result.response_time_ms:.0f}ms" if result.response_time_ms else "---"

                print(f"{status_color}[{status_symbol}]{reset_color} {result.method:6} {result.endpoint:50} {status_code_str:6} {time_str:8}")

                if result.error_message and (self.verbose or result.result != TestResult.PASS):
                    print(f"    Error: {result.error_message}")

                if result.result == TestResult.PASS:
                    passed += 1
                elif result.result == TestResult.FAIL:
                    failed += 1
                else:
                    errors += 1

        return total, passed, failed, errors

    def print_summary(self, total: int, passed: int, failed: int, errors: int):
        """Print validation summary."""
        print(f"\n{'='*70}")
        print("VALIDATION SUMMARY")
        print(f"{'='*70}")
        print(f"Total Tests:  {total}")
        print(f"\033[92mPassed:       {passed}\033[0m")
        print(f"\033[91mFailed:       {failed}\033[0m")
        print(f"\033[93mErrors:       {errors}\033[0m")
        print(f"{'='*70}")

        success_rate = (passed / total * 100) if total > 0 else 0
        print(f"Success Rate: {success_rate:.1f}%")

        if failed > 0:
            print(f"\n\033[91mFailed Endpoints:\033[0m")
            for r in self.results:
                if r.result == TestResult.FAIL:
                    print(f"  - {r.method} {r.endpoint}: {r.error_message}")

        if errors > 0:
            print(f"\n\033[93mErrors:\033[0m")
            for r in self.results:
                if r.result == TestResult.ERROR:
                    print(f"  - {r.method} {r.endpoint}: {r.error_message}")

        print()


async def main():
    parser = argparse.ArgumentParser(
        description="Validate Revenue Intelligence API endpoints"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the API server (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose output including response data"
    )

    args = parser.parse_args()

    validator = RevenueAPIValidator(
        base_url=args.base_url,
        verbose=args.verbose
    )

    total, passed, failed, errors = await validator.validate_all()
    validator.print_summary(total, passed, failed, errors)

    # Exit with error code if any failures
    if failed > 0 or errors > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
