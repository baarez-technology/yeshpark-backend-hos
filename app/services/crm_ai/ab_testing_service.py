"""
A/B Testing Service with Statistical Analysis
Uses two-proportion z-test for significance calculation
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
import math
import json

try:
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.crm_ai import ABTest, CampaignRecipient
from app.models.crm import Campaigns


class ABTestVariant:
    """In-memory variant tracking for A/B tests"""
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.impressions = 0
        self.conversions = 0
        self.revenue = 0.0


class ABTestingService:
    """Service for managing A/B tests with statistical analysis"""

    def __init__(self):
        self.min_sample_size = 100
        self.default_significance = 0.95

    async def create_test(
        self,
        session: AsyncSession,
        name: str,
        test_type: str,
        campaign_id: Optional[int],
        variants: List[dict],
        traffic_split: Optional[dict] = None,
        significance_threshold: float = 0.95,
        created_by: Optional[int] = None
    ) -> dict:
        """
        Create a new A/B test with variants

        Args:
            session: Database session
            name: Test name
            test_type: Type of test (subject_line, offer, template, cta, timing)
            campaign_id: Optional campaign to associate test with
            variants: List of variant configurations [{"name": "A", "config": {...}}, ...]
            traffic_split: Traffic distribution {"A": 50, "B": 50}
            significance_threshold: Required confidence level (default 0.95)
            created_by: User ID creating the test

        Returns:
            Created test details
        """
        # Validate variants
        if len(variants) < 2:
            raise ValueError("A/B test requires at least 2 variants")

        # Default traffic split if not provided
        if not traffic_split:
            split_value = 100 // len(variants)
            traffic_split = {v.get("name", f"Variant_{i}"): split_value
                          for i, v in enumerate(variants)}

        # Validate traffic split totals 100
        total_split = sum(traffic_split.values())
        if total_split != 100:
            # Normalize
            traffic_split = {k: round(v * 100 / total_split)
                          for k, v in traffic_split.items()}

        # Initialize variant metrics
        for variant in variants:
            variant["impressions"] = 0
            variant["conversions"] = 0
            variant["revenue"] = 0.0
            variant["conversion_rate"] = 0.0

        # Create ABTest record
        ab_test = ABTest(
            name=name,
            test_type=test_type,
            campaign_id=campaign_id,
            variants=json.dumps(variants),
            traffic_split=json.dumps(traffic_split),
            significance_threshold=significance_threshold,
            status="draft",
            created_by=created_by,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        session.add(ab_test)
        await session.commit()
        await session.refresh(ab_test)

        return {
            "id": ab_test.id,
            "name": ab_test.name,
            "test_type": ab_test.test_type,
            "campaign_id": ab_test.campaign_id,
            "variants": variants,
            "traffic_split": traffic_split,
            "significance_threshold": significance_threshold,
            "status": ab_test.status,
            "created_at": ab_test.created_at.isoformat()
        }

    async def start_test(self, session: AsyncSession, test_id: int) -> dict:
        """Start running an A/B test"""
        ab_test = await session.get(ABTest, test_id)
        if not ab_test:
            raise ValueError(f"Test {test_id} not found")

        if ab_test.status == "running":
            raise ValueError("Test is already running")

        if ab_test.status == "completed":
            raise ValueError("Test has already been completed")

        ab_test.status = "running"
        ab_test.started_at = datetime.utcnow()
        ab_test.updated_at = datetime.utcnow()

        session.add(ab_test)
        await session.commit()

        return {
            "id": ab_test.id,
            "name": ab_test.name,
            "status": ab_test.status,
            "started_at": ab_test.started_at.isoformat(),
            "message": "A/B test started successfully"
        }

    async def stop_test(self, session: AsyncSession, test_id: int) -> dict:
        """Stop a running test"""
        ab_test = await session.get(ABTest, test_id)
        if not ab_test:
            raise ValueError(f"Test {test_id} not found")

        if ab_test.status != "running":
            raise ValueError("Test is not currently running")

        ab_test.status = "stopped"
        ab_test.ended_at = datetime.utcnow()
        ab_test.updated_at = datetime.utcnow()

        # Calculate final results
        results = await self.get_test_results(session, test_id)
        ab_test.results = json.dumps(results)

        session.add(ab_test)
        await session.commit()

        return {
            "id": ab_test.id,
            "name": ab_test.name,
            "status": ab_test.status,
            "ended_at": ab_test.ended_at.isoformat(),
            "results": results,
            "message": "A/B test stopped"
        }

    async def record_impression(
        self, session: AsyncSession, test_id: int, variant_name: str
    ) -> None:
        """Record an impression for a variant"""
        ab_test = await session.get(ABTest, test_id)
        if not ab_test:
            raise ValueError(f"Test {test_id} not found")

        if ab_test.status != "running":
            return  # Silently ignore if test not running

        variants = json.loads(ab_test.variants) if ab_test.variants else []

        for variant in variants:
            if variant.get("name") == variant_name:
                variant["impressions"] = variant.get("impressions", 0) + 1
                break

        ab_test.variants = json.dumps(variants)
        ab_test.updated_at = datetime.utcnow()

        session.add(ab_test)
        await session.commit()

    async def record_conversion(
        self, session: AsyncSession, test_id: int, variant_name: str, revenue: float = 0
    ) -> None:
        """Record a conversion for a variant"""
        ab_test = await session.get(ABTest, test_id)
        if not ab_test:
            raise ValueError(f"Test {test_id} not found")

        if ab_test.status != "running":
            return  # Silently ignore if test not running

        variants = json.loads(ab_test.variants) if ab_test.variants else []

        for variant in variants:
            if variant.get("name") == variant_name:
                variant["conversions"] = variant.get("conversions", 0) + 1
                variant["revenue"] = variant.get("revenue", 0) + revenue
                # Recalculate conversion rate
                impressions = variant.get("impressions", 0)
                if impressions > 0:
                    variant["conversion_rate"] = variant["conversions"] / impressions * 100
                break

        ab_test.variants = json.dumps(variants)
        ab_test.updated_at = datetime.utcnow()

        session.add(ab_test)
        await session.commit()

    def calculate_significance(
        self,
        control_conversions: int,
        control_impressions: int,
        variant_conversions: int,
        variant_impressions: int
    ) -> dict:
        """
        Calculate statistical significance using two-proportion z-test
        Returns: {p_value, z_score, significant, confidence, lift}
        """
        if control_impressions == 0 or variant_impressions == 0:
            return {
                "p_value": 1.0,
                "z_score": 0,
                "significant": False,
                "confidence": 0,
                "lift": 0,
                "control_rate": 0,
                "variant_rate": 0,
                "sample_size_sufficient": False
            }

        p1 = control_conversions / control_impressions
        p2 = variant_conversions / variant_impressions

        # Check minimum sample size
        sample_size_sufficient = (
            control_impressions >= self.min_sample_size and
            variant_impressions >= self.min_sample_size
        )

        # Pooled proportion
        p_pool = (control_conversions + variant_conversions) / (control_impressions + variant_impressions)

        # Standard error
        se_squared = p_pool * (1 - p_pool) * (1/control_impressions + 1/variant_impressions)

        if se_squared <= 0:
            return {
                "p_value": 1.0,
                "z_score": 0,
                "significant": False,
                "confidence": 0,
                "lift": 0,
                "control_rate": p1 * 100,
                "variant_rate": p2 * 100,
                "sample_size_sufficient": sample_size_sufficient
            }

        se = math.sqrt(se_squared)

        # Z-score
        z_score = (p2 - p1) / se if se > 0 else 0

        # Two-tailed p-value
        if SCIPY_AVAILABLE:
            p_value = 2 * (1 - stats.norm.cdf(abs(z_score)))
        else:
            # Fallback approximation using error function
            p_value = self._approximate_p_value(abs(z_score))

        # Lift calculation
        lift = ((p2 - p1) / p1 * 100) if p1 > 0 else 0

        # Determine significance
        alpha = 1 - self.default_significance
        significant = p_value < alpha and sample_size_sufficient

        return {
            "p_value": round(p_value, 6),
            "z_score": round(z_score, 4),
            "significant": significant,
            "confidence": round((1 - p_value) * 100, 2),
            "lift": round(lift, 2),
            "control_rate": round(p1 * 100, 4),
            "variant_rate": round(p2 * 100, 4),
            "sample_size_sufficient": sample_size_sufficient,
            "min_sample_size": self.min_sample_size
        }

    def _approximate_p_value(self, z: float) -> float:
        """Approximate p-value without scipy using error function approximation"""
        # Approximation of standard normal CDF
        # Using Abramowitz and Stegun approximation
        a1 = 0.254829592
        a2 = -0.284496736
        a3 = 1.421413741
        a4 = -1.453152027
        a5 = 1.061405429
        p = 0.3275911

        sign = 1 if z >= 0 else -1
        z = abs(z) / math.sqrt(2)

        t = 1.0 / (1.0 + p * z)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-z * z)

        cdf = 0.5 * (1.0 + sign * y)
        return 2 * (1 - cdf)

    async def get_test_results(self, session: AsyncSession, test_id: int) -> dict:
        """Get comprehensive test results with statistics"""
        ab_test = await session.get(ABTest, test_id)
        if not ab_test:
            raise ValueError(f"Test {test_id} not found")

        variants = json.loads(ab_test.variants) if ab_test.variants else []

        if len(variants) < 2:
            return {
                "test_id": test_id,
                "error": "Insufficient variants for analysis"
            }

        # Calculate metrics for each variant
        results = []
        for variant in variants:
            impressions = variant.get("impressions", 0)
            conversions = variant.get("conversions", 0)
            revenue = variant.get("revenue", 0)

            conversion_rate = (conversions / impressions * 100) if impressions > 0 else 0
            avg_revenue = revenue / conversions if conversions > 0 else 0

            results.append({
                "name": variant.get("name"),
                "impressions": impressions,
                "conversions": conversions,
                "conversion_rate": round(conversion_rate, 4),
                "revenue": round(revenue, 2),
                "avg_revenue_per_conversion": round(avg_revenue, 2),
                "config": variant.get("config", {})
            })

        # Sort by conversion rate descending
        results.sort(key=lambda x: x["conversion_rate"], reverse=True)

        # Control is usually first variant (or lowest conversion for comparison)
        control = results[-1]  # Use lowest performer as baseline
        winner = results[0]

        # Calculate significance between winner and control
        significance = self.calculate_significance(
            control["conversions"], control["impressions"],
            winner["conversions"], winner["impressions"]
        )

        # Pairwise comparisons
        pairwise_results = []
        for i, variant in enumerate(results[:-1]):
            pair_sig = self.calculate_significance(
                control["conversions"], control["impressions"],
                variant["conversions"], variant["impressions"]
            )
            pairwise_results.append({
                "variant": variant["name"],
                "vs_control": control["name"],
                "lift": pair_sig["lift"],
                "confidence": pair_sig["confidence"],
                "significant": pair_sig["significant"]
            })

        # Determine winner
        winning_variant = None
        if significance["significant"] and significance["lift"] > 0:
            winning_variant = winner["name"]

        # Calculate total metrics
        total_impressions = sum(v["impressions"] for v in results)
        total_conversions = sum(v["conversions"] for v in results)
        total_revenue = sum(v["revenue"] for v in results)

        # Test duration
        duration_hours = None
        if ab_test.started_at:
            end_time = ab_test.ended_at or datetime.utcnow()
            duration_hours = (end_time - ab_test.started_at).total_seconds() / 3600

        return {
            "test_id": test_id,
            "test_name": ab_test.name,
            "test_type": ab_test.test_type,
            "status": ab_test.status,
            "started_at": ab_test.started_at.isoformat() if ab_test.started_at else None,
            "ended_at": ab_test.ended_at.isoformat() if ab_test.ended_at else None,
            "duration_hours": round(duration_hours, 2) if duration_hours else None,
            "variants": results,
            "winning_variant": winning_variant,
            "statistical_analysis": {
                "control_variant": control["name"],
                "winner_variant": winner["name"],
                "significance": significance,
                "pairwise_comparisons": pairwise_results
            },
            "totals": {
                "impressions": total_impressions,
                "conversions": total_conversions,
                "overall_conversion_rate": round(
                    total_conversions / total_impressions * 100, 4
                ) if total_impressions > 0 else 0,
                "total_revenue": round(total_revenue, 2)
            },
            "recommendation": self._generate_recommendation(
                winning_variant, significance, results
            )
        }

    def _generate_recommendation(
        self,
        winning_variant: Optional[str],
        significance: dict,
        results: List[dict]
    ) -> dict:
        """Generate actionable recommendation based on test results"""
        if not significance["sample_size_sufficient"]:
            return {
                "action": "continue_test",
                "reason": f"Insufficient sample size. Need at least {self.min_sample_size} impressions per variant.",
                "confidence": "low"
            }

        if winning_variant and significance["significant"]:
            return {
                "action": "deploy_winner",
                "variant": winning_variant,
                "reason": f"Statistically significant winner found with {significance['lift']:.1f}% lift and {significance['confidence']:.1f}% confidence.",
                "confidence": "high"
            }

        if significance["confidence"] >= 80:
            return {
                "action": "continue_test",
                "reason": f"Trending towards significance ({significance['confidence']:.1f}% confidence). Continue collecting data.",
                "confidence": "medium"
            }

        return {
            "action": "no_significant_difference",
            "reason": "No statistically significant difference detected between variants.",
            "confidence": "medium"
        }

    async def deploy_winner(self, session: AsyncSession, test_id: int) -> dict:
        """Deploy the winning variant to the campaign"""
        ab_test = await session.get(ABTest, test_id)
        if not ab_test:
            raise ValueError(f"Test {test_id} not found")

        # Get test results
        results = await self.get_test_results(session, test_id)
        winning_variant = results.get("winning_variant")

        if not winning_variant:
            raise ValueError("No statistically significant winner to deploy")

        # Update test with winner
        ab_test.winning_variant = winning_variant
        ab_test.statistical_significance = results["statistical_analysis"]["significance"]["confidence"]
        ab_test.p_value = results["statistical_analysis"]["significance"]["p_value"]
        ab_test.status = "completed"
        ab_test.ended_at = datetime.utcnow()
        ab_test.updated_at = datetime.utcnow()
        ab_test.results = json.dumps(results)

        # Update campaign if associated
        deployment_details = {"test_id": test_id, "deployed_variant": winning_variant}

        if ab_test.campaign_id:
            campaign = await session.get(Campaigns, ab_test.campaign_id)
            if campaign:
                # Find winning variant config
                variants = json.loads(ab_test.variants) if ab_test.variants else []
                winning_config = next(
                    (v.get("config", {}) for v in variants if v.get("name") == winning_variant),
                    {}
                )

                # Apply winning configuration to campaign
                if "subject" in winning_config:
                    campaign.subject = winning_config["subject"]
                if "message" in winning_config:
                    campaign.message = winning_config["message"]

                campaign.updated_at = datetime.utcnow()
                session.add(campaign)

                deployment_details["campaign_id"] = ab_test.campaign_id
                deployment_details["applied_config"] = winning_config

        session.add(ab_test)
        await session.commit()

        return {
            "test_id": test_id,
            "status": "deployed",
            "winning_variant": winning_variant,
            "confidence": results["statistical_analysis"]["significance"]["confidence"],
            "lift": results["statistical_analysis"]["significance"]["lift"],
            "deployment_details": deployment_details,
            "message": f"Winning variant '{winning_variant}' deployed successfully"
        }

    async def list_tests(
        self, session: AsyncSession, status: Optional[str] = None, limit: int = 50
    ) -> List[dict]:
        """List all A/B tests with optional filtering"""
        query = select(ABTest).order_by(ABTest.created_at.desc()).limit(limit)

        if status:
            query = query.where(ABTest.status == status)

        result = await session.exec(query)
        tests = result.all()

        test_list = []
        for test in tests:
            variants = json.loads(test.variants) if test.variants else []

            # Calculate summary stats
            total_impressions = sum(v.get("impressions", 0) for v in variants)
            total_conversions = sum(v.get("conversions", 0) for v in variants)

            test_list.append({
                "id": test.id,
                "name": test.name,
                "test_type": test.test_type,
                "campaign_id": test.campaign_id,
                "status": test.status,
                "variant_count": len(variants),
                "total_impressions": total_impressions,
                "total_conversions": total_conversions,
                "overall_conversion_rate": round(
                    total_conversions / total_impressions * 100, 2
                ) if total_impressions > 0 else 0,
                "winning_variant": test.winning_variant,
                "statistical_significance": test.statistical_significance,
                "started_at": test.started_at.isoformat() if test.started_at else None,
                "ended_at": test.ended_at.isoformat() if test.ended_at else None,
                "created_at": test.created_at.isoformat()
            })

        return test_list

    async def get_variant_for_guest(
        self,
        session: AsyncSession,
        test_id: int,
        guest_id: int
    ) -> dict:
        """
        Get the assigned variant for a guest based on traffic split
        Uses consistent hashing for deterministic assignment
        """
        ab_test = await session.get(ABTest, test_id)
        if not ab_test:
            raise ValueError(f"Test {test_id} not found")

        if ab_test.status != "running":
            raise ValueError("Test is not currently running")

        traffic_split = json.loads(ab_test.traffic_split) if ab_test.traffic_split else {}
        variants = json.loads(ab_test.variants) if ab_test.variants else []

        if not variants or not traffic_split:
            raise ValueError("Test has no variants configured")

        # Deterministic assignment using guest_id hash
        hash_value = hash(f"{test_id}_{guest_id}") % 100

        cumulative = 0
        assigned_variant = variants[0]["name"]  # Default to first

        for variant_name, percentage in traffic_split.items():
            cumulative += percentage
            if hash_value < cumulative:
                assigned_variant = variant_name
                break

        # Find variant config
        variant_config = next(
            (v for v in variants if v.get("name") == assigned_variant),
            {"name": assigned_variant, "config": {}}
        )

        return {
            "test_id": test_id,
            "guest_id": guest_id,
            "assigned_variant": assigned_variant,
            "variant_config": variant_config.get("config", {})
        }


# Singleton instance
ab_testing_service = ABTestingService()
