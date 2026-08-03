"""
Member Tier Service
Manages loyalty program tiers with dynamic pricing, benefits, and tier progression
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import json
import math

from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.reservations import Guest, Booking, Reservation
from app.models.crm import LoyaltyTiers, LoyaltyTransactions, CRMGuestActivities


class TierConfig:
    """Configuration for a loyalty tier"""
    def __init__(
        self,
        name: str,
        min_points: int,
        min_revenue: float,
        min_nights: int,
        discount_percentage: float,
        benefits: List[str],
        color: str = "#888888",
        icon: str = ""
    ):
        self.name = name
        self.min_points = min_points
        self.min_revenue = min_revenue
        self.min_nights = min_nights
        self.discount_percentage = discount_percentage
        self.benefits = benefits
        self.color = color
        self.icon = icon


class MemberTierService:
    """Service for managing member tiers with dynamic pricing and benefits"""

    # Default tier configuration
    DEFAULT_TIERS = {
        "member": TierConfig(
            name="Member",
            min_points=0,
            min_revenue=0,
            min_nights=0,
            discount_percentage=0,
            benefits=[
                "Member-only rates",
                "Earn 1 point per ₹100 spent"
            ],
            color="#A0AEC0",
            icon="user"
        ),
        "bronze": TierConfig(
            name="Bronze",
            min_points=500,
            min_revenue=500,
            min_nights=3,
            discount_percentage=5,
            benefits=[
                "5% discount on direct bookings",
                "Earn 1.25 points per ₹100 spent",
                "Early check-in (subject to availability)",
                "Welcome drink"
            ],
            color="#CD7F32",
            icon="award"
        ),
        "silver": TierConfig(
            name="Silver",
            min_points=2000,
            min_revenue=2000,
            min_nights=10,
            discount_percentage=8,
            benefits=[
                "8% discount on direct bookings",
                "Earn 1.5 points per ₹100 spent",
                "Room upgrade (subject to availability)",
                "Late checkout until 2pm",
                "10% F&B discount"
            ],
            color="#C0C0C0",
            icon="star"
        ),
        "gold": TierConfig(
            name="Gold",
            min_points=5000,
            min_revenue=5000,
            min_nights=25,
            discount_percentage=12,
            benefits=[
                "12% discount on direct bookings",
                "Earn 2 points per ₹100 spent",
                "Guaranteed room upgrade",
                "Late checkout until 4pm",
                "15% F&B discount",
                "Complimentary breakfast"
            ],
            color="#FFD700",
            icon="crown"
        ),
        "platinum": TierConfig(
            name="Platinum",
            min_points=10000,
            min_revenue=10000,
            min_nights=50,
            discount_percentage=15,
            benefits=[
                "15% discount on direct bookings",
                "Earn 2.5 points per ₹100 spent",
                "Suite upgrade (subject to availability)",
                "Late checkout until 6pm",
                "20% F&B discount",
                "Complimentary breakfast",
                "20% spa discount",
                "Airport pickup discount"
            ],
            color="#E5E4E2",
            icon="gem"
        ),
        "diamond": TierConfig(
            name="Diamond",
            min_points=25000,
            min_revenue=25000,
            min_nights=100,
            discount_percentage=20,
            benefits=[
                "20% discount on direct bookings",
                "Earn 3 points per ₹100 spent",
                "Guaranteed suite upgrade",
                "24-hour flexible checkout",
                "25% F&B discount",
                "Complimentary full breakfast",
                "Complimentary spa access",
                "Complimentary airport transfers",
                "Personal concierge",
                "Exclusive member events"
            ],
            color="#B9F2FF",
            icon="diamond"
        )
    }

    # Points earning rate by tier
    POINTS_MULTIPLIER = {
        "member": 1.0,
        "bronze": 1.25,
        "silver": 1.5,
        "gold": 2.0,
        "platinum": 2.5,
        "diamond": 3.0
    }

    def __init__(self):
        self.tier_order = ["member", "bronze", "silver", "gold", "platinum", "diamond"]
        self.base_points_per_dollar = 1
        self.points_expiry_months = 24

    async def get_all_tiers(
        self,
        session: AsyncSession
    ) -> List[dict]:
        """Get all tier configurations"""
        # Try to get from database first
        try:
            db_tiers = await session.exec(
                select(LoyaltyTiers)
                .where(LoyaltyTiers.is_active == True)
                .order_by(LoyaltyTiers.sort_order)
            )
            tiers_list = db_tiers.all()

            if tiers_list:
                return [
                    {
                        "id": tier.id,
                        "name": tier.name,
                        "min_points": tier.min_points,
                        "max_points": tier.max_points,
                        "min_revenue": tier.min_revenue,
                        "discount_percentage": tier.discount_percentage,
                        "benefits": json.loads(tier.benefits) if tier.benefits else [],
                        "color": tier.color,
                        "icon": tier.icon
                    }
                    for tier in tiers_list
                ]
        except Exception:
            pass

        # Return default tiers
        return [
            {
                "name": tier.name,
                "tier_code": code,
                "min_points": tier.min_points,
                "min_revenue": tier.min_revenue,
                "min_nights": tier.min_nights,
                "discount_percentage": tier.discount_percentage,
                "benefits": tier.benefits,
                "color": tier.color,
                "icon": tier.icon,
                "points_multiplier": self.POINTS_MULTIPLIER.get(code, 1.0)
            }
            for code, tier in self.DEFAULT_TIERS.items()
        ]

    async def get_guest_tier_status(
        self,
        session: AsyncSession,
        guest_id: int
    ) -> dict:
        """Get comprehensive tier status for a guest"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        # Get current tier from guest record
        current_tier = guest.loyalty_tier or "member"
        current_points = guest.loyalty_points or 0

        # Get tier configuration
        tier_config = self.DEFAULT_TIERS.get(current_tier, self.DEFAULT_TIERS["member"])

        # Calculate metrics
        metrics = await self._calculate_guest_metrics(session, guest_id)

        # Determine eligible tier based on current metrics
        eligible_tier = self._calculate_eligible_tier(
            points=current_points,
            revenue=metrics["total_revenue"],
            nights=metrics["total_nights"]
        )

        # Check if tier upgrade or downgrade is needed
        tier_change = None
        current_index = self.tier_order.index(current_tier)
        eligible_index = self.tier_order.index(eligible_tier)

        if eligible_index > current_index:
            tier_change = {
                "type": "upgrade",
                "from_tier": current_tier,
                "to_tier": eligible_tier,
                "reason": "Guest has qualified for tier upgrade"
            }
        elif eligible_index < current_index:
            # Check if within grace period before downgrade
            tier_change = {
                "type": "pending_downgrade",
                "from_tier": current_tier,
                "to_tier": eligible_tier,
                "reason": "Guest no longer meets tier requirements"
            }

        # Calculate progress to next tier
        next_tier_progress = self._calculate_next_tier_progress(
            current_tier, current_points, metrics["total_revenue"], metrics["total_nights"]
        )

        # Get recent transactions
        recent_transactions = await self._get_recent_transactions(session, guest_id, limit=10)

        return {
            "guest_id": guest_id,
            "guest_name": f"{guest.first_name} {guest.last_name}",
            "current_tier": {
                "code": current_tier,
                "name": tier_config.name,
                "color": tier_config.color,
                "icon": tier_config.icon,
                "discount_percentage": tier_config.discount_percentage,
                "benefits": tier_config.benefits,
                "points_multiplier": self.POINTS_MULTIPLIER.get(current_tier, 1.0)
            },
            "points": {
                "current": current_points,
                "expiring_soon": await self._get_expiring_points(session, guest_id, days=30),
                "lifetime_earned": metrics.get("lifetime_points_earned", current_points)
            },
            "metrics": {
                "total_revenue": round(metrics["total_revenue"], 2),
                "total_nights": metrics["total_nights"],
                "total_stays": metrics["total_stays"],
                "member_since": guest.member_since.isoformat() if guest.member_since else None
            },
            "eligible_tier": eligible_tier,
            "tier_change": tier_change,
            "next_tier_progress": next_tier_progress,
            "recent_transactions": recent_transactions,
            "updated_at": datetime.utcnow().isoformat()
        }

    async def _calculate_guest_metrics(
        self,
        session: AsyncSession,
        guest_id: int
    ) -> dict:
        """Calculate guest metrics for tier evaluation"""
        metrics = {
            "total_revenue": 0.0,
            "total_nights": 0,
            "total_stays": 0,
            "lifetime_points_earned": 0
        }

        # Get from Booking table
        try:
            bookings = await session.exec(
                select(Booking)
                .where(
                    and_(
                        Booking.guest_id == guest_id,
                        Booking.status.in_(["confirmed", "checked_in", "checked_out"])
                    )
                )
            )
            for booking in bookings.all():
                metrics["total_revenue"] += booking.total_price or 0
                metrics["total_nights"] += booking.nights or 0
                metrics["total_stays"] += 1
        except Exception:
            pass

        # Get from Reservation table (legacy)
        try:
            reservations = await session.exec(
                select(Reservation)
                .where(
                    and_(
                        Reservation.guest_id == guest_id,
                        Reservation.status.in_(["checked_out", "checked_in"])
                    )
                )
            )
            for res in reservations.all():
                metrics["total_revenue"] += res.total_amount or 0
                if res.arrival_date and res.departure_date:
                    nights = (res.departure_date - res.arrival_date).days
                    metrics["total_nights"] += nights
                metrics["total_stays"] += 1
        except Exception:
            pass

        # Get lifetime points from transactions
        try:
            points_earned = await session.exec(
                select(func.sum(LoyaltyTransactions.points))
                .where(
                    and_(
                        LoyaltyTransactions.guest_id == guest_id,
                        LoyaltyTransactions.transaction_type == "earned"
                    )
                )
            )
            metrics["lifetime_points_earned"] = points_earned.one() or 0
        except Exception:
            pass

        return metrics

    def _calculate_eligible_tier(
        self,
        points: int,
        revenue: float,
        nights: int
    ) -> str:
        """Calculate which tier a guest is eligible for based on metrics"""
        eligible_tier = "member"

        for tier_code in self.tier_order[1:]:  # Skip member tier
            tier = self.DEFAULT_TIERS[tier_code]

            # Must meet at least 2 of 3 requirements
            requirements_met = 0
            if points >= tier.min_points:
                requirements_met += 1
            if revenue >= tier.min_revenue:
                requirements_met += 1
            if nights >= tier.min_nights:
                requirements_met += 1

            if requirements_met >= 2:
                eligible_tier = tier_code

        return eligible_tier

    def _calculate_next_tier_progress(
        self,
        current_tier: str,
        points: int,
        revenue: float,
        nights: int
    ) -> Optional[dict]:
        """Calculate progress to next tier"""
        current_index = self.tier_order.index(current_tier)

        if current_index >= len(self.tier_order) - 1:
            return None  # Already at highest tier

        next_tier_code = self.tier_order[current_index + 1]
        next_tier = self.DEFAULT_TIERS[next_tier_code]

        points_progress = min(100, (points / next_tier.min_points) * 100) if next_tier.min_points > 0 else 100
        revenue_progress = min(100, (revenue / next_tier.min_revenue) * 100) if next_tier.min_revenue > 0 else 100
        nights_progress = min(100, (nights / next_tier.min_nights) * 100) if next_tier.min_nights > 0 else 100

        overall_progress = (points_progress + revenue_progress + nights_progress) / 3

        return {
            "next_tier": {
                "code": next_tier_code,
                "name": next_tier.name,
                "color": next_tier.color
            },
            "progress": {
                "overall": round(overall_progress, 1),
                "points": {
                    "current": points,
                    "required": next_tier.min_points,
                    "remaining": max(0, next_tier.min_points - points),
                    "percentage": round(points_progress, 1)
                },
                "revenue": {
                    "current": round(revenue, 2),
                    "required": next_tier.min_revenue,
                    "remaining": round(max(0, next_tier.min_revenue - revenue), 2),
                    "percentage": round(revenue_progress, 1)
                },
                "nights": {
                    "current": nights,
                    "required": next_tier.min_nights,
                    "remaining": max(0, next_tier.min_nights - nights),
                    "percentage": round(nights_progress, 1)
                }
            }
        }

    async def _get_recent_transactions(
        self,
        session: AsyncSession,
        guest_id: int,
        limit: int = 10
    ) -> List[dict]:
        """Get recent loyalty transactions"""
        try:
            transactions = await session.exec(
                select(LoyaltyTransactions)
                .where(LoyaltyTransactions.guest_id == guest_id)
                .order_by(LoyaltyTransactions.created_at.desc())
                .limit(limit)
            )
            return [
                {
                    "id": t.id,
                    "type": t.transaction_type,
                    "points": t.points,
                    "balance_after": t.balance_after,
                    "reason": t.reason,
                    "created_at": t.created_at.isoformat()
                }
                for t in transactions.all()
            ]
        except Exception:
            return []

    async def _get_expiring_points(
        self,
        session: AsyncSession,
        guest_id: int,
        days: int = 30
    ) -> int:
        """Get points expiring within specified days"""
        expiry_date = datetime.utcnow() + timedelta(days=days)
        try:
            expiring = await session.exec(
                select(func.sum(LoyaltyTransactions.points))
                .where(
                    and_(
                        LoyaltyTransactions.guest_id == guest_id,
                        LoyaltyTransactions.transaction_type == "earned",
                        LoyaltyTransactions.expires_at <= expiry_date,
                        LoyaltyTransactions.expires_at > datetime.utcnow()
                    )
                )
            )
            return expiring.one() or 0
        except Exception:
            return 0

    async def upgrade_tier(
        self,
        session: AsyncSession,
        guest_id: int,
        new_tier: str,
        reason: str = "Automatic tier upgrade"
    ) -> dict:
        """Upgrade a guest to a new tier"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        if new_tier not in self.tier_order:
            raise ValueError(f"Invalid tier: {new_tier}")

        old_tier = guest.loyalty_tier or "member"
        old_index = self.tier_order.index(old_tier)
        new_index = self.tier_order.index(new_tier)

        if new_index <= old_index:
            raise ValueError("New tier must be higher than current tier")

        # Update guest tier
        guest.loyalty_tier = new_tier
        guest.updated_at = datetime.utcnow()

        # Log activity
        activity = CRMGuestActivities(
            guest_id=guest_id,
            activity_type="tier_upgrade",
            activity_category="milestone",
            description=f"Tier upgraded from {old_tier} to {new_tier}",
            sentiment="positive",
            importance="high",
            timestamp=datetime.utcnow(),
            extra_data=json.dumps({
                "old_tier": old_tier,
                "new_tier": new_tier,
                "reason": reason
            })
        )

        session.add(guest)
        session.add(activity)
        await session.commit()

        new_tier_config = self.DEFAULT_TIERS[new_tier]

        return {
            "guest_id": guest_id,
            "previous_tier": old_tier,
            "new_tier": new_tier,
            "new_tier_name": new_tier_config.name,
            "new_benefits": new_tier_config.benefits,
            "new_discount": new_tier_config.discount_percentage,
            "upgraded_at": datetime.utcnow().isoformat()
        }

    async def earn_points(
        self,
        session: AsyncSession,
        guest_id: int,
        base_amount: float,
        reason: str,
        booking_id: Optional[int] = None
    ) -> dict:
        """Award points to a guest based on spending"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        current_tier = guest.loyalty_tier or "member"
        multiplier = self.POINTS_MULTIPLIER.get(current_tier, 1.0)

        # Calculate points
        points_earned = int(base_amount * self.base_points_per_dollar * multiplier)

        # Update guest points
        current_points = guest.loyalty_points or 0
        new_balance = current_points + points_earned
        guest.loyalty_points = new_balance
        guest.updated_at = datetime.utcnow()

        # Create transaction record
        expiry_date = datetime.utcnow() + timedelta(days=self.points_expiry_months * 30)

        transaction = LoyaltyTransactions(
            guest_id=guest_id,
            transaction_type="earned",
            points=points_earned,
            balance_after=new_balance,
            reason=reason,
            booking_id=booking_id,
            expires_at=expiry_date,
            created_at=datetime.utcnow()
        )

        session.add(guest)
        session.add(transaction)
        await session.commit()

        return {
            "guest_id": guest_id,
            "points_earned": points_earned,
            "multiplier": multiplier,
            "new_balance": new_balance,
            "expires_at": expiry_date.isoformat(),
            "transaction_id": transaction.id
        }

    async def redeem_points(
        self,
        session: AsyncSession,
        guest_id: int,
        points: int,
        reason: str,
        reference_id: Optional[int] = None
    ) -> dict:
        """Redeem points from a guest's balance"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            raise ValueError(f"Guest {guest_id} not found")

        current_points = guest.loyalty_points or 0
        if points > current_points:
            raise ValueError(f"Insufficient points. Available: {current_points}, Requested: {points}")

        new_balance = current_points - points
        guest.loyalty_points = new_balance
        guest.updated_at = datetime.utcnow()

        transaction = LoyaltyTransactions(
            guest_id=guest_id,
            transaction_type="redeemed",
            points=-points,
            balance_after=new_balance,
            reason=reason,
            reference_id=reference_id,
            created_at=datetime.utcnow()
        )

        session.add(guest)
        session.add(transaction)
        await session.commit()

        return {
            "guest_id": guest_id,
            "points_redeemed": points,
            "new_balance": new_balance,
            "transaction_id": transaction.id
        }

    async def calculate_dynamic_price(
        self,
        session: AsyncSession,
        guest_id: int,
        base_price: float,
        room_type: str = "standard"
    ) -> dict:
        """Calculate dynamic price with member discounts"""
        guest = await session.get(Guest, guest_id)

        if not guest:
            # Non-member pricing
            return {
                "base_price": base_price,
                "discount_percentage": 0,
                "discount_amount": 0,
                "final_price": base_price,
                "tier": None,
                "is_member": False
            }

        current_tier = guest.loyalty_tier or "member"
        tier_config = self.DEFAULT_TIERS.get(current_tier, self.DEFAULT_TIERS["member"])

        discount_percentage = tier_config.discount_percentage

        # Additional dynamic discounts based on loyalty
        if guest.vip_status:
            discount_percentage += 2  # VIP bonus

        total_bookings = guest.total_bookings or 0
        if total_bookings >= 10:
            discount_percentage += 2  # Loyalty bonus
        elif total_bookings >= 5:
            discount_percentage += 1

        # Cap discount at 25%
        discount_percentage = min(discount_percentage, 25)

        discount_amount = base_price * (discount_percentage / 100)
        final_price = base_price - discount_amount

        return {
            "guest_id": guest_id,
            "base_price": round(base_price, 2),
            "tier": current_tier,
            "tier_discount": tier_config.discount_percentage,
            "additional_discounts": discount_percentage - tier_config.discount_percentage,
            "total_discount_percentage": discount_percentage,
            "discount_amount": round(discount_amount, 2),
            "final_price": round(final_price, 2),
            "savings": round(discount_amount, 2),
            "is_member": True
        }

    async def process_tier_evaluations(
        self,
        session: AsyncSession,
        limit: int = 100
    ) -> dict:
        """Batch process tier evaluations for all guests"""
        upgrades = []
        downgrades = []
        processed = 0

        try:
            guests = await session.exec(
                select(Guest)
                .where(Guest.status != "Inactive")
                .limit(limit)
            )

            for guest in guests.all():
                processed += 1
                metrics = await self._calculate_guest_metrics(session, guest.id)

                eligible_tier = self._calculate_eligible_tier(
                    points=guest.loyalty_points or 0,
                    revenue=metrics["total_revenue"],
                    nights=metrics["total_nights"]
                )

                current_tier = guest.loyalty_tier or "member"
                current_index = self.tier_order.index(current_tier)
                eligible_index = self.tier_order.index(eligible_tier)

                if eligible_index > current_index:
                    # Upgrade
                    await self.upgrade_tier(
                        session, guest.id, eligible_tier,
                        "Automatic tier evaluation"
                    )
                    upgrades.append({
                        "guest_id": guest.id,
                        "from_tier": current_tier,
                        "to_tier": eligible_tier
                    })
                elif eligible_index < current_index:
                    # Mark for potential downgrade (in practice, might have grace period)
                    downgrades.append({
                        "guest_id": guest.id,
                        "current_tier": current_tier,
                        "eligible_tier": eligible_tier
                    })

        except Exception as e:
            return {
                "error": str(e),
                "processed": processed
            }

        return {
            "processed": processed,
            "upgrades": len(upgrades),
            "upgrade_details": upgrades,
            "pending_downgrades": len(downgrades),
            "downgrade_details": downgrades,
            "processed_at": datetime.utcnow().isoformat()
        }

    async def get_tier_statistics(
        self,
        session: AsyncSession
    ) -> dict:
        """Get statistics about tier distribution"""
        tier_counts = {tier: 0 for tier in self.tier_order}

        try:
            guests = await session.exec(
                select(Guest)
                .where(Guest.status != "Inactive")
            )

            total = 0
            for guest in guests.all():
                total += 1
                tier = guest.loyalty_tier or "member"
                if tier in tier_counts:
                    tier_counts[tier] += 1
                else:
                    tier_counts["member"] += 1

            # Calculate percentages
            tier_distribution = []
            for tier_code in self.tier_order:
                count = tier_counts[tier_code]
                percentage = (count / total * 100) if total > 0 else 0
                tier_config = self.DEFAULT_TIERS[tier_code]
                tier_distribution.append({
                    "tier": tier_code,
                    "name": tier_config.name,
                    "count": count,
                    "percentage": round(percentage, 2),
                    "color": tier_config.color
                })

        except Exception:
            return {"error": "Failed to fetch statistics"}

        return {
            "total_members": total,
            "tier_distribution": tier_distribution,
            "generated_at": datetime.utcnow().isoformat()
        }


# Singleton instance
member_tier_service = MemberTierService()
