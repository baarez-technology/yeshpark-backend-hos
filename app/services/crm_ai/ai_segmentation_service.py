"""
AI-Powered Guest Segmentation using clustering algorithms
Supports K-Means clustering with optional HDBSCAN for advanced use cases
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import json
import math

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    StandardScaler = None
    KMeans = None

from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.reservations import Guest, Booking, Reservation
from app.models.crm import CRMSegments, GuestSegments, CRMGuestActivities
from app.models.crm_ai import AIScore


class AISegmentationService:
    """Service for AI-powered guest micro-segmentation"""

    FEATURE_NAMES = [
        "recency_days",
        "booking_count",
        "total_spend",
        "avg_booking_value",
        "engagement_score",
        "sentiment_score",
        "cancellation_rate",
        "days_as_customer"
    ]

    def __init__(self):
        self.min_cluster_size = 10
        self.default_n_clusters = 5
        if SKLEARN_AVAILABLE:
            self.scaler = StandardScaler()
        else:
            self.scaler = None

    async def extract_features(
        self,
        session: AsyncSession,
        guest_ids: Optional[List[int]] = None,
        limit: int = 1000
    ) -> Tuple[Any, List[int]]:
        """
        Extract ML features for segmentation
        Features: recency, frequency, monetary, engagement, sentiment, loyalty
        Returns: (feature_matrix, guest_ids_list)
        """
        if not NUMPY_AVAILABLE:
            raise RuntimeError("NumPy is required for AI segmentation")

        # Get guests
        if guest_ids:
            guests_result = await session.exec(
                select(Guest).where(Guest.id.in_(guest_ids))
            )
        else:
            guests_result = await session.exec(
                select(Guest)
                .where(Guest.status != "Inactive")
                .limit(limit)
            )

        guests = guests_result.all()

        features_list = []
        valid_guest_ids = []

        for guest in guests:
            feature_vector = await self._calculate_guest_features_vector(session, guest)
            if feature_vector:
                features_list.append(feature_vector)
                valid_guest_ids.append(guest.id)

        if not features_list:
            return np.array([]), []

        return np.array(features_list), valid_guest_ids

    async def _calculate_guest_features_vector(
        self,
        session: AsyncSession,
        guest: Guest
    ) -> Optional[List[float]]:
        """Calculate feature vector for a single guest"""
        guest_data = {}

        # Days since registration
        if guest.created_at:
            try:
                guest_data["days_as_customer"] = (datetime.utcnow() - guest.created_at.replace(tzinfo=None)).days
            except Exception:
                guest_data["days_as_customer"] = 365
        else:
            guest_data["days_as_customer"] = 365

        # Get booking data
        total_bookings = 0
        total_spend = 0.0
        recency_days = 365
        cancellation_count = 0

        try:
            bookings = await session.exec(
                select(Booking)
                .where(Booking.guest_id == guest.id)
                .order_by(Booking.arrival_date.desc())
            )
            booking_list = bookings.all()

            total_bookings = len(booking_list)
            total_spend = sum(b.total_price or 0 for b in booking_list)
            cancellation_count = len([b for b in booking_list if b.status == "cancelled"])

            if booking_list:
                last_booking = booking_list[0]
                if last_booking.arrival_date:
                    recency_days = (datetime.utcnow().date() - last_booking.arrival_date).days

        except Exception:
            pass

        # Also check reservations
        try:
            reservations = await session.exec(
                select(Reservation)
                .where(Reservation.guest_id == guest.id)
                .order_by(Reservation.arrival_date.desc())
            )
            res_list = reservations.all()

            total_bookings += len(res_list)
            total_spend += sum(r.total_amount or 0 for r in res_list)
            cancellation_count += len([r for r in res_list if r.status == "cancelled"])

            if res_list and not booking_list:
                last_res = res_list[0]
                if last_res.arrival_date:
                    recency_days = min(
                        recency_days,
                        (datetime.utcnow().date() - last_res.arrival_date).days
                    )
        except Exception:
            pass

        guest_data["recency_days"] = max(0, recency_days)
        guest_data["booking_count"] = total_bookings
        guest_data["total_spend"] = total_spend
        guest_data["avg_booking_value"] = total_spend / max(total_bookings, 1)
        guest_data["cancellation_rate"] = cancellation_count / max(total_bookings, 1)

        # Get engagement score from activities
        try:
            activity_count = await session.exec(
                select(func.count(CRMGuestActivities.id))
                .where(
                    and_(
                        CRMGuestActivities.guest_id == guest.id,
                        CRMGuestActivities.timestamp >= datetime.utcnow() - timedelta(days=90)
                    )
                )
            )
            guest_data["engagement_score"] = min(100, (activity_count.one() or 0) * 10)
        except Exception:
            guest_data["engagement_score"] = 0

        # Get sentiment score from AI scores
        try:
            sentiment_result = await session.exec(
                select(AIScore)
                .where(
                    and_(
                        AIScore.guest_id == guest.id,
                        AIScore.score_type.in_(["sentiment_score", "health_score"])
                    )
                )
                .order_by(AIScore.calculated_at.desc())
                .limit(1)
            )
            sentiment_score = sentiment_result.first()
            if sentiment_score:
                # Normalize to 0-1 range
                guest_data["sentiment_score"] = sentiment_score.score_value / 100.0
            else:
                guest_data["sentiment_score"] = 0.5
        except Exception:
            guest_data["sentiment_score"] = 0.5

        # Build feature vector in consistent order
        return self._calculate_guest_features(guest_data)

    def _calculate_guest_features(self, guest_data: dict) -> List[float]:
        """Calculate feature vector for a single guest from data dict"""
        features = [
            guest_data.get("recency_days", 365),
            guest_data.get("booking_count", 0),
            guest_data.get("total_spend", 0),
            guest_data.get("avg_booking_value", 0),
            guest_data.get("engagement_score", 0),
            guest_data.get("sentiment_score", 0),
            guest_data.get("cancellation_rate", 0),
            guest_data.get("days_as_customer", 0)
        ]
        return features

    async def generate_segments(
        self,
        session: AsyncSession,
        n_clusters: int = 5,
        min_cluster_size: int = 10,
        algorithm: str = "kmeans"  # kmeans or hdbscan
    ) -> List[dict]:
        """
        Generate AI segments using clustering
        Returns list of created segments with characteristics
        """
        if not SKLEARN_AVAILABLE or not NUMPY_AVAILABLE:
            raise RuntimeError("scikit-learn and NumPy are required for AI segmentation")

        # Extract features
        features, guest_ids = await self.extract_features(session)

        if len(features) < min_cluster_size * n_clusters:
            raise ValueError(
                f"Not enough guests ({len(features)}) for {n_clusters} clusters "
                f"(need at least {min_cluster_size * n_clusters})"
            )

        # Scale features
        scaled_features = self.scaler.fit_transform(features)

        # Perform clustering
        if algorithm == "hdbscan":
            clusters = self._hdbscan_clustering(scaled_features, min_cluster_size)
        else:
            clusters = self._kmeans_clustering(scaled_features, n_clusters)

        # Create segment records
        segments = await self._create_segment_records(
            session, clusters, guest_ids, features
        )

        return segments

    def _kmeans_clustering(self, features: Any, n_clusters: int) -> Any:
        """Perform K-Means clustering"""
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn required for K-Means clustering")

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        return kmeans.fit_predict(features)

    def _hdbscan_clustering(self, features: Any, min_cluster_size: int) -> Any:
        """Perform HDBSCAN clustering"""
        try:
            import hdbscan
            clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size)
            return clusterer.fit_predict(features)
        except ImportError:
            # Fallback to K-Means if HDBSCAN not available
            return self._kmeans_clustering(features, 5)

    async def _create_segment_records(
        self,
        session: AsyncSession,
        clusters: Any,
        guest_ids: List[int],
        features: Any
    ) -> List[dict]:
        """Create segment records in database from clustering results"""
        unique_clusters = set(clusters)
        segments_created = []

        # Remove noise cluster (-1 in HDBSCAN)
        unique_clusters.discard(-1)

        for cluster_id in unique_clusters:
            # Get indices for this cluster
            cluster_mask = clusters == cluster_id
            cluster_indices = [i for i, m in enumerate(cluster_mask) if m]

            if len(cluster_indices) < self.min_cluster_size:
                continue

            # Get features for this cluster
            cluster_features = features[cluster_mask]
            cluster_guest_ids = [guest_ids[i] for i in cluster_indices]

            # Analyze cluster characteristics
            characteristics = self._analyze_cluster_characteristics(
                cluster_features, self.FEATURE_NAMES
            )

            # Generate segment name
            segment_name = self._generate_segment_name(characteristics)

            # Check if segment already exists
            existing = await session.exec(
                select(CRMSegments).where(CRMSegments.name == segment_name)
            )
            if existing.first():
                segment_name = f"{segment_name} ({cluster_id})"

            # Create segment record
            segment = CRMSegments(
                name=segment_name,
                description=self._generate_segment_description(characteristics),
                segment_type="behavioral",
                criteria=json.dumps({
                    "algorithm": "ai_clustering",
                    "cluster_id": int(cluster_id),
                    "characteristics": characteristics
                }),
                is_active=True,
                member_count=len(cluster_guest_ids),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )

            session.add(segment)
            await session.flush()  # Get segment ID

            # Create guest-segment associations
            for guest_id in cluster_guest_ids:
                guest_segment = GuestSegments(
                    guest_id=guest_id,
                    segment_id=segment.id,
                    added_at=datetime.utcnow()
                )
                session.add(guest_segment)

            await session.commit()

            # Calculate cluster statistics
            cluster_stats = self._calculate_cluster_stats(cluster_features)

            segments_created.append({
                "id": segment.id,
                "name": segment_name,
                "member_count": len(cluster_guest_ids),
                "characteristics": characteristics,
                "statistics": cluster_stats,
                "guest_ids": cluster_guest_ids[:10]  # Sample of guest IDs
            })

        return segments_created

    def _analyze_cluster_characteristics(
        self,
        cluster_features: Any,
        feature_names: List[str]
    ) -> dict:
        """Analyze and describe cluster characteristics"""
        if not NUMPY_AVAILABLE:
            return {}

        characteristics = {}
        means = np.mean(cluster_features, axis=0)

        for i, name in enumerate(feature_names):
            value = means[i]

            if name == "recency_days":
                if value < 30:
                    characteristics["recency"] = "Very Recent"
                elif value < 90:
                    characteristics["recency"] = "Recent"
                elif value < 180:
                    characteristics["recency"] = "Moderate"
                elif value < 365:
                    characteristics["recency"] = "Distant"
                else:
                    characteristics["recency"] = "Lapsed"

            elif name == "booking_count":
                if value >= 5:
                    characteristics["frequency"] = "Frequent"
                elif value >= 3:
                    characteristics["frequency"] = "Regular"
                elif value >= 2:
                    characteristics["frequency"] = "Occasional"
                else:
                    characteristics["frequency"] = "New"

            elif name == "total_spend":
                if value >= 5000:
                    characteristics["value"] = "High Value"
                elif value >= 2000:
                    characteristics["value"] = "Medium-High Value"
                elif value >= 1000:
                    characteristics["value"] = "Medium Value"
                elif value >= 500:
                    characteristics["value"] = "Low-Medium Value"
                else:
                    characteristics["value"] = "Low Value"

            elif name == "sentiment_score":
                if value >= 0.7:
                    characteristics["sentiment"] = "Very Positive"
                elif value >= 0.5:
                    characteristics["sentiment"] = "Positive"
                elif value >= 0.3:
                    characteristics["sentiment"] = "Neutral"
                elif value >= 0.1:
                    characteristics["sentiment"] = "Negative"
                else:
                    characteristics["sentiment"] = "Very Negative"

            elif name == "engagement_score":
                if value >= 70:
                    characteristics["engagement"] = "Highly Engaged"
                elif value >= 40:
                    characteristics["engagement"] = "Moderately Engaged"
                else:
                    characteristics["engagement"] = "Low Engagement"

            elif name == "cancellation_rate":
                if value >= 0.3:
                    characteristics["reliability"] = "High Cancellation Risk"
                elif value >= 0.15:
                    characteristics["reliability"] = "Moderate Cancellation Risk"
                else:
                    characteristics["reliability"] = "Reliable"

        return characteristics

    def _generate_segment_name(self, characteristics: dict) -> str:
        """Generate descriptive segment name from characteristics"""
        parts = []

        if "value" in characteristics:
            parts.append(characteristics["value"])
        if "frequency" in characteristics:
            parts.append(characteristics["frequency"])
        if "recency" in characteristics:
            parts.append(characteristics["recency"])

        if not parts:
            return "General Segment"

        # Take first two characteristics for name
        return " ".join(parts[:2]) + " Guests"

    def _generate_segment_description(self, characteristics: dict) -> str:
        """Generate segment description from characteristics"""
        descriptions = []

        if "value" in characteristics:
            descriptions.append(f"{characteristics['value']} spending pattern")
        if "frequency" in characteristics:
            descriptions.append(f"{characteristics['frequency'].lower()} bookings")
        if "recency" in characteristics:
            descriptions.append(f"{characteristics['recency'].lower()} activity")
        if "sentiment" in characteristics:
            descriptions.append(f"{characteristics['sentiment'].lower()} sentiment")
        if "engagement" in characteristics:
            descriptions.append(f"{characteristics['engagement'].lower()}")

        if descriptions:
            return "Guests with " + ", ".join(descriptions) + "."
        return "AI-generated guest segment."

    def _calculate_cluster_stats(self, cluster_features: Any) -> dict:
        """Calculate statistics for a cluster"""
        if not NUMPY_AVAILABLE:
            return {}

        return {
            "avg_recency_days": round(float(np.mean(cluster_features[:, 0])), 1),
            "avg_booking_count": round(float(np.mean(cluster_features[:, 1])), 1),
            "avg_total_spend": round(float(np.mean(cluster_features[:, 2])), 2),
            "avg_booking_value": round(float(np.mean(cluster_features[:, 3])), 2),
            "avg_engagement": round(float(np.mean(cluster_features[:, 4])), 1),
            "avg_sentiment": round(float(np.mean(cluster_features[:, 5])), 3),
            "avg_cancellation_rate": round(float(np.mean(cluster_features[:, 6])), 3),
            "avg_tenure_days": round(float(np.mean(cluster_features[:, 7])), 1)
        }

    async def assign_guest_to_segment(
        self,
        session: AsyncSession,
        guest_id: int
    ) -> Optional[dict]:
        """Assign a single guest to the best matching segment"""
        guest = await session.get(Guest, guest_id)
        if not guest:
            return None

        # Get existing AI segments
        segments = await session.exec(
            select(CRMSegments)
            .where(
                and_(
                    CRMSegments.is_active == True,
                    CRMSegments.segment_type == "behavioral"
                )
            )
        )
        segment_list = segments.all()

        if not segment_list:
            return None

        # Calculate guest features
        feature_vector = await self._calculate_guest_features_vector(session, guest)
        if not feature_vector:
            return None

        # Find best matching segment based on characteristics
        best_match = None
        best_score = -1

        for segment in segment_list:
            criteria = json.loads(segment.criteria) if segment.criteria else {}
            characteristics = criteria.get("characteristics", {})

            score = self._calculate_match_score(feature_vector, characteristics)
            if score > best_score:
                best_score = score
                best_match = segment

        if best_match and best_score > 0.5:
            # Remove from previous segments
            await session.exec(
                select(GuestSegments)
                .where(GuestSegments.guest_id == guest_id)
            )
            # Note: Would need delete in real implementation

            # Add to new segment
            guest_segment = GuestSegments(
                guest_id=guest_id,
                segment_id=best_match.id,
                added_at=datetime.utcnow()
            )
            session.add(guest_segment)
            await session.commit()

            return {
                "guest_id": guest_id,
                "segment_id": best_match.id,
                "segment_name": best_match.name,
                "match_score": round(best_score, 3),
                "assigned_at": datetime.utcnow().isoformat()
            }

        return None

    def _calculate_match_score(
        self,
        feature_vector: List[float],
        characteristics: dict
    ) -> float:
        """Calculate how well a guest matches segment characteristics"""
        score = 0.0
        checks = 0

        recency = feature_vector[0]
        if "recency" in characteristics:
            checks += 1
            if characteristics["recency"] == "Very Recent" and recency < 30:
                score += 1
            elif characteristics["recency"] == "Recent" and recency < 90:
                score += 1
            elif characteristics["recency"] == "Moderate" and 90 <= recency < 180:
                score += 1
            elif characteristics["recency"] == "Lapsed" and recency >= 365:
                score += 1

        spend = feature_vector[2]
        if "value" in characteristics:
            checks += 1
            if characteristics["value"] == "High Value" and spend >= 5000:
                score += 1
            elif characteristics["value"] == "Medium Value" and 1000 <= spend < 5000:
                score += 1
            elif characteristics["value"] == "Low Value" and spend < 1000:
                score += 1

        bookings = feature_vector[1]
        if "frequency" in characteristics:
            checks += 1
            if characteristics["frequency"] == "Frequent" and bookings >= 5:
                score += 1
            elif characteristics["frequency"] == "Regular" and 2 <= bookings < 5:
                score += 1
            elif characteristics["frequency"] == "Occasional" and bookings < 2:
                score += 1

        return score / checks if checks > 0 else 0

    async def refresh_all_memberships(self, session: AsyncSession) -> dict:
        """Refresh segment memberships for all guests"""
        refreshed = 0
        errors = 0

        try:
            guests = await session.exec(
                select(Guest).where(Guest.status != "Inactive")
            )

            for guest in guests.all():
                try:
                    result = await self.assign_guest_to_segment(session, guest.id)
                    if result:
                        refreshed += 1
                except Exception:
                    errors += 1

        except Exception as e:
            return {
                "error": str(e),
                "refreshed": refreshed,
                "errors": errors
            }

        return {
            "refreshed": refreshed,
            "errors": errors,
            "completed_at": datetime.utcnow().isoformat()
        }

    async def get_segment_recommendations(
        self,
        session: AsyncSession,
        segment_id: int
    ) -> dict:
        """Get campaign recommendations for a segment"""
        segment = await session.get(CRMSegments, segment_id)
        if not segment:
            raise ValueError(f"Segment {segment_id} not found")

        criteria = json.loads(segment.criteria) if segment.criteria else {}
        characteristics = criteria.get("characteristics", {})

        recommendations = {
            "segment_id": segment_id,
            "segment_name": segment.name,
            "member_count": segment.member_count,
            "characteristics": characteristics,
            "campaign_recommendations": [],
            "channel_recommendations": [],
            "timing_recommendations": [],
            "offer_recommendations": []
        }

        # Campaign recommendations based on characteristics
        if characteristics.get("recency") == "Lapsed":
            recommendations["campaign_recommendations"].append({
                "type": "win_back",
                "priority": "high",
                "reason": "High recency indicates need for re-engagement"
            })
            recommendations["offer_recommendations"].append({
                "type": "discount",
                "value": "20%",
                "description": "Win-back discount to re-engage lapsed guests"
            })

        if characteristics.get("value") == "High Value":
            recommendations["campaign_recommendations"].append({
                "type": "loyalty",
                "priority": "high",
                "reason": "High-value guests deserve VIP treatment"
            })
            recommendations["offer_recommendations"].append({
                "type": "upgrade",
                "value": "complimentary",
                "description": "Free room upgrade for VIP experience"
            })

        if characteristics.get("frequency") == "Frequent":
            recommendations["campaign_recommendations"].append({
                "type": "rewards",
                "priority": "medium",
                "reason": "Frequent guests benefit from rewards program"
            })
            recommendations["offer_recommendations"].append({
                "type": "points",
                "value": "2x",
                "description": "Double loyalty points promotion"
            })

        if characteristics.get("sentiment") in ["Negative", "Very Negative"]:
            recommendations["campaign_recommendations"].append({
                "type": "recovery",
                "priority": "critical",
                "reason": "Negative sentiment requires immediate attention"
            })
            recommendations["offer_recommendations"].append({
                "type": "compensation",
                "value": "25%",
                "description": "Service recovery discount"
            })

        # Channel recommendations
        if characteristics.get("engagement") == "Highly Engaged":
            recommendations["channel_recommendations"] = ["email", "push", "app"]
        elif characteristics.get("engagement") == "Low Engagement":
            recommendations["channel_recommendations"] = ["sms", "whatsapp"]
        else:
            recommendations["channel_recommendations"] = ["email", "sms"]

        # Timing recommendations
        if characteristics.get("recency") == "Lapsed":
            recommendations["timing_recommendations"].append("Send immediately - urgent re-engagement needed")
        elif characteristics.get("frequency") == "Frequent":
            recommendations["timing_recommendations"].append("Schedule around typical booking patterns")
        else:
            recommendations["timing_recommendations"].append("Optimal: Tuesday-Thursday, 10am-2pm")

        return recommendations

    async def get_segmentation_stats(self, session: AsyncSession) -> dict:
        """Get overall segmentation statistics"""
        try:
            # Total segments
            segment_count = await session.exec(
                select(func.count(CRMSegments.id))
                .where(CRMSegments.is_active == True)
            )
            total_segments = segment_count.one() or 0

            # Total segmented guests
            segmented_guests = await session.exec(
                select(func.count(func.distinct(GuestSegments.guest_id)))
            )
            total_segmented = segmented_guests.one() or 0

            # Total guests
            total_guests = await session.exec(
                select(func.count(Guest.id))
                .where(Guest.status != "Inactive")
            )
            total = total_guests.one() or 0

            # Get segment distribution
            segments = await session.exec(
                select(CRMSegments)
                .where(CRMSegments.is_active == True)
                .order_by(CRMSegments.member_count.desc())
            )

            segment_distribution = [
                {
                    "id": s.id,
                    "name": s.name,
                    "member_count": s.member_count,
                    "percentage": round((s.member_count / total * 100), 2) if total > 0 else 0
                }
                for s in segments.all()
            ]

        except Exception as e:
            return {"error": str(e)}

        coverage = (total_segmented / total * 100) if total > 0 else 0

        return {
            "total_segments": total_segments,
            "total_guests": total,
            "segmented_guests": total_segmented,
            "coverage_percentage": round(coverage, 2),
            "unsegmented_guests": total - total_segmented,
            "segment_distribution": segment_distribution,
            "generated_at": datetime.utcnow().isoformat()
        }


# Singleton instance
ai_segmentation_service = AISegmentationService()
