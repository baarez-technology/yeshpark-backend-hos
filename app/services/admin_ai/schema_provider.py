"""
Database Schema Provider for RAG
Extracts and formats database schema information for LLM context
Enables the AI to understand database structure for intelligent query assistance
"""
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from functools import lru_cache

from sqlmodel import SQLModel
from sqlalchemy import inspect
from sqlalchemy.orm import RelationshipProperty

logger = logging.getLogger(__name__)


@dataclass
class ColumnInfo:
    """Information about a database column"""
    name: str
    type: str
    nullable: bool
    primary_key: bool
    foreign_key: Optional[str] = None
    description: Optional[str] = None
    index: bool = False


@dataclass
class TableInfo:
    """Information about a database table"""
    name: str
    description: str
    columns: List[ColumnInfo] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)
    sample_queries: List[str] = field(default_factory=list)


class SchemaProvider:
    """
    Provides database schema context for RAG (Retrieval Augmented Generation).
    Extracts schema from SQLModel classes and formats for LLM consumption.
    """

    # Table descriptions for better LLM understanding
    TABLE_DESCRIPTIONS = {
        "bookings": "Main booking/reservation table storing guest bookings with dates, prices, status",
        "guests": "Guest profiles with contact info, loyalty status, preferences, and booking history",
        "users": "System users including staff and administrators with authentication info",
        "rooms": "Physical room inventory with room numbers, types, status, and amenities",
        "room_types": "Categories of rooms (e.g., Standard, Deluxe, Suite) with base prices and features",
        "reservation": "Legacy reservation table (use bookings instead)",
        "housekeeping_tasks": "Housekeeping task assignments with room, status, priority, assignee",
        "maintenance_requests": "Maintenance/repair requests for rooms and facilities",
        "staff": "Staff member profiles with department, position, and employment details",
        "staff_attendance": "Staff check-in/check-out and attendance records",
        "reviews": "Guest reviews and ratings from various platforms",
        "folio": "Guest billing folio/account for charges during stay",
        "folio_line_items": "Individual charges on guest folios",
        "payments": "Payment transactions and records",
        "daily_metrics": "Daily operational metrics (occupancy, revenue, ADR, RevPAR)",
        "rate_plans": "Pricing rate plans (BAR, corporate, promotional)",
        "promo_codes": "Promotional discount codes",
        "corporate_accounts": "Corporate/business accounts with negotiated rates",
        "loyalty_tiers": "Loyalty program tier definitions",
        "loyalty_transactions": "Guest loyalty point transactions",
        "precheckin": "Pre-arrival check-in information submitted by guests",
        "checkout_feedback": "Post-stay feedback collected during checkout",
        "admin_ai_audit": "Audit log for Admin AI interactions",
        "admin_ai_sessions": "Admin AI conversation sessions",
        "admin_ai_messages": "Individual messages in Admin AI conversations",
    }

    # Common query patterns for each table
    QUERY_EXAMPLES = {
        "bookings": [
            "SELECT * FROM bookings WHERE arrival_date = DATE('now')",
            "SELECT COUNT(*) FROM bookings WHERE status = 'checked_in'",
            "SELECT b.*, g.first_name, g.last_name FROM bookings b JOIN guests g ON b.guest_id = g.id",
        ],
        "guests": [
            "SELECT * FROM guests WHERE vip_status = 1",
            "SELECT * FROM guests WHERE loyalty_tier IN ('gold', 'platinum')",
            "SELECT * FROM guests ORDER BY total_spent DESC LIMIT 10",
        ],
        "rooms": [
            "SELECT * FROM rooms WHERE status = 'available'",
            "SELECT r.*, rt.name as room_type FROM rooms r JOIN room_types rt ON r.room_type_id = rt.id",
            "SELECT status, COUNT(*) FROM rooms GROUP BY status",
        ],
        "housekeeping_tasks": [
            "SELECT * FROM housekeeping_tasks WHERE status = 'pending'",
            "SELECT ht.*, r.number as room_number FROM housekeeping_tasks ht JOIN rooms r ON ht.room_id = r.id",
        ],
        "daily_metrics": [
            "SELECT * FROM daily_metrics WHERE metric_date = DATE('now')",
            "SELECT AVG(occupancy_percentage), AVG(adr) FROM daily_metrics WHERE metric_date >= DATE('now', '-7 days')",
        ],
    }

    # Relevant tables for different query contexts
    CONTEXT_TABLES = {
        "bookings": ["bookings", "guests", "rooms", "room_types"],
        "guests": ["guests", "bookings", "loyalty_tiers", "guest_stay_history"],
        "revenue": ["bookings", "folio", "folio_line_items", "payments", "daily_metrics"],
        "housekeeping": ["housekeeping_tasks", "rooms", "staff"],
        "maintenance": ["maintenance_requests", "rooms", "staff"],
        "occupancy": ["rooms", "room_types", "bookings", "daily_metrics"],
        "staff": ["staff", "staff_attendance", "users"],
        "reviews": ["reviews", "guests", "sentiment_trends"],
    }

    def __init__(self):
        self._schema_cache: Dict[str, TableInfo] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Initialize schema extraction from SQLModel classes"""
        if self._initialized:
            return

        try:
            # Import models with safe fallbacks
            models = []

            # Core models - import individually with error handling
            try:
                from app.models import User
                models.append(User)
            except ImportError:
                pass

            try:
                from app.models import Guest
                models.append(Guest)
            except ImportError:
                pass

            try:
                from app.models import Room, RoomType
                models.extend([Room, RoomType])
            except ImportError:
                pass

            try:
                from app.models import HousekeepingTask
                models.append(HousekeepingTask)
            except ImportError:
                pass

            try:
                from app.models import MaintenanceRequest
                models.append(MaintenanceRequest)
            except ImportError:
                pass

            try:
                from app.models import Staff, StaffAttendance
                models.extend([Staff, StaffAttendance])
            except ImportError:
                pass

            try:
                from app.models import Review
                models.append(Review)
            except ImportError:
                pass

            try:
                from app.models import Folio, FolioLineItem, Payment
                models.extend([Folio, FolioLineItem, Payment])
            except ImportError:
                pass

            try:
                from app.models import DailyMetrics
                models.append(DailyMetrics)
            except ImportError:
                pass

            try:
                from app.models import RatePlan, PromoCode, CorporateAccounts
                models.extend([RatePlan, PromoCode, CorporateAccounts])
            except ImportError:
                pass

            try:
                from app.models import PreCheckIn, CheckoutFeedback
                models.extend([PreCheckIn, CheckoutFeedback])
            except ImportError:
                pass

            # Try to import Booking from reservations (newer schema)
            try:
                from app.models.reservations import Booking
                models.append(Booking)
            except ImportError:
                pass

            # Try legacy Reservation
            try:
                from app.models import Reservation
                models.append(Reservation)
            except ImportError:
                pass

            for model in models:
                try:
                    table_info = self._extract_table_info(model)
                    if table_info:
                        self._schema_cache[table_info.name] = table_info
                except Exception as e:
                    logger.debug(f"Could not extract schema for {model}: {e}")

            self._initialized = True
            logger.info(f"Schema provider initialized with {len(self._schema_cache)} tables")

        except Exception as e:
            logger.error(f"Failed to initialize schema provider: {e}")

    def _extract_table_info(self, model: type) -> Optional[TableInfo]:
        """Extract table information from a SQLModel class"""
        try:
            # Get table name
            table_name = getattr(model, '__tablename__', model.__name__.lower())

            # Get description
            description = self.TABLE_DESCRIPTIONS.get(
                table_name,
                model.__doc__ or f"Table: {table_name}"
            )

            # Extract columns
            columns = []
            if hasattr(model, '__fields__'):
                for field_name, field_info in model.__fields__.items():
                    col_type = str(field_info.outer_type_).replace('typing.', '')
                    nullable = field_info.allow_none

                    # Check for primary key
                    is_pk = field_name == 'id'

                    # Check for foreign key
                    fk = None
                    if hasattr(field_info, 'field_info') and hasattr(field_info.field_info, 'extra'):
                        fk = field_info.field_info.extra.get('foreign_key')

                    columns.append(ColumnInfo(
                        name=field_name,
                        type=col_type,
                        nullable=nullable,
                        primary_key=is_pk,
                        foreign_key=fk
                    ))

            # Get sample queries
            sample_queries = self.QUERY_EXAMPLES.get(table_name, [])

            return TableInfo(
                name=table_name,
                description=description,
                columns=columns,
                sample_queries=sample_queries
            )

        except Exception as e:
            logger.debug(f"Error extracting table info: {e}")
            return None

    @lru_cache(maxsize=32)
    def get_schema_context(self, context_type: str = "general", max_tables: int = 10) -> str:
        """
        Get formatted schema context for LLM prompt injection.

        Args:
            context_type: Type of query context (bookings, guests, revenue, etc.)
            max_tables: Maximum number of tables to include

        Returns:
            Formatted schema string for LLM context
        """
        self.initialize()

        # Determine which tables to include
        if context_type in self.CONTEXT_TABLES:
            relevant_tables = self.CONTEXT_TABLES[context_type]
        else:
            # Include most common tables
            relevant_tables = ["bookings", "guests", "rooms", "room_types",
                            "housekeeping_tasks", "staff", "daily_metrics"]

        schema_parts = []
        schema_parts.append("## Database Schema Reference\n")

        included = 0
        for table_name in relevant_tables:
            if included >= max_tables:
                break

            table_info = self._schema_cache.get(table_name)
            if not table_info:
                # Provide basic info even if not cached
                description = self.TABLE_DESCRIPTIONS.get(table_name, f"Table: {table_name}")
                schema_parts.append(f"\n### {table_name}\n{description}\n")
                included += 1
                continue

            schema_parts.append(f"\n### {table_info.name}")
            schema_parts.append(f"*{table_info.description}*\n")

            # Add key columns
            if table_info.columns:
                schema_parts.append("**Key columns:**")
                for col in table_info.columns[:12]:  # Limit columns
                    fk_note = f" (FK: {col.foreign_key})" if col.foreign_key else ""
                    pk_note = " [PK]" if col.primary_key else ""
                    schema_parts.append(f"- `{col.name}`: {col.type}{pk_note}{fk_note}")

            included += 1

        # Add relationship hints
        schema_parts.append("\n## Key Relationships")
        schema_parts.append("- bookings.guest_id -> guests.id")
        schema_parts.append("- bookings.room_id -> rooms.id")
        schema_parts.append("- bookings.room_type_id -> room_types.id")
        schema_parts.append("- rooms.room_type_id -> room_types.id")
        schema_parts.append("- housekeeping_tasks.room_id -> rooms.id")
        schema_parts.append("- housekeeping_tasks.assigned_to -> staff.id")
        schema_parts.append("- staff.user_id -> users.id")

        return "\n".join(schema_parts)

    def get_table_schema(self, table_name: str) -> Optional[str]:
        """Get schema for a specific table"""
        self.initialize()

        table_info = self._schema_cache.get(table_name)
        if not table_info:
            description = self.TABLE_DESCRIPTIONS.get(table_name)
            if description:
                return f"### {table_name}\n{description}"
            return None

        parts = [f"### {table_info.name}", f"*{table_info.description}*\n"]

        if table_info.columns:
            parts.append("**Columns:**")
            for col in table_info.columns:
                fk_note = f" (FK: {col.foreign_key})" if col.foreign_key else ""
                pk_note = " [PK]" if col.primary_key else ""
                nullable = "" if not col.nullable else " [nullable]"
                parts.append(f"- `{col.name}`: {col.type}{pk_note}{fk_note}{nullable}")

        if table_info.sample_queries:
            parts.append("\n**Example queries:**")
            for query in table_info.sample_queries[:2]:
                parts.append(f"```sql\n{query}\n```")

        return "\n".join(parts)

    def get_context_for_intent(self, intent: str) -> str:
        """
        Get relevant schema context based on detected intent.

        Args:
            intent: The detected user intent (e.g., 'query_bookings', 'query_revenue')

        Returns:
            Formatted schema context relevant to the intent
        """
        # Map intents to context types
        intent_context_map = {
            "query_bookings": "bookings",
            "query_bookings_today": "bookings",
            "query_checkouts_today": "bookings",
            "query_guests": "guests",
            "query_vip_guests": "guests",
            "query_revenue": "revenue",
            "query_occupancy": "occupancy",
            "query_rooms": "occupancy",
            "query_staff": "staff",
            "query_housekeeping": "housekeeping",
            "query_maintenance": "maintenance",
            "analyze_trends": "revenue",
            "generate_report": "revenue",
        }

        context_type = intent_context_map.get(intent, "general")
        return self.get_schema_context(context_type)

    def get_full_schema_summary(self) -> str:
        """Get a comprehensive schema summary for complex queries"""
        self.initialize()

        parts = [
            "# Glimmora Hotel Database Schema\n",
            "## Core Tables\n"
        ]

        # Core operational tables
        core_tables = ["bookings", "guests", "rooms", "room_types", "staff"]
        for table in core_tables:
            schema = self.get_table_schema(table)
            if schema:
                parts.append(schema)
                parts.append("")

        parts.append("\n## Operations Tables\n")
        ops_tables = ["housekeeping_tasks", "maintenance_requests", "folio", "payments"]
        for table in ops_tables:
            schema = self.get_table_schema(table)
            if schema:
                parts.append(schema)
                parts.append("")

        parts.append("\n## Analytics Tables\n")
        analytics_tables = ["daily_metrics", "reviews"]
        for table in analytics_tables:
            schema = self.get_table_schema(table)
            if schema:
                parts.append(schema)
                parts.append("")

        return "\n".join(parts)


# Global schema provider instance
_schema_provider: Optional[SchemaProvider] = None


def get_schema_provider() -> SchemaProvider:
    """Get or create the global schema provider instance"""
    global _schema_provider
    if _schema_provider is None:
        _schema_provider = SchemaProvider()
    return _schema_provider


def get_schema_context(context_type: str = "general") -> str:
    """Convenience function to get schema context"""
    return get_schema_provider().get_schema_context(context_type)


def get_intent_schema_context(intent: str) -> str:
    """Convenience function to get schema context for an intent"""
    return get_schema_provider().get_context_for_intent(intent)
