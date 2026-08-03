"""
SQL Executor for Admin AI
Provides safe SQL query building and execution with validation
"""
import re
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .security import SecurityValidator, TablePermissions

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result of a SQL query execution"""
    success: bool
    data: List[Dict[str, Any]]
    row_count: int
    query: str
    parameters: Dict[str, Any]
    execution_time_ms: int
    error: Optional[str] = None
    truncated: bool = False


class QueryValidator:
    """Validates SQL queries before execution"""

    DEFAULT_LIMIT = 100
    MAX_LIMIT = 1000

    def __init__(self):
        self.security = SecurityValidator()
        self.permissions = TablePermissions()

    def validate_and_limit(self, query: str, limit: Optional[int] = None) -> Tuple[bool, str, Optional[str]]:
        """
        Validate query and add limit if not present

        Args:
            query: SQL query to validate
            limit: Optional limit override

        Returns:
            Tuple of (is_valid, modified_query, error_message)
        """
        # Security validation
        check = self.security.validate_query(query)
        if not check.is_safe:
            return False, query, check.block_reason

        # Ensure query has a limit
        query_upper = query.upper().strip()

        # Skip limit for aggregate queries
        aggregate_patterns = [
            r"SELECT\s+COUNT\s*\(",
            r"SELECT\s+SUM\s*\(",
            r"SELECT\s+AVG\s*\(",
            r"SELECT\s+MIN\s*\(",
            r"SELECT\s+MAX\s*\(",
        ]

        is_aggregate = any(re.search(p, query_upper) for p in aggregate_patterns)

        if not is_aggregate:
            # Add or modify LIMIT
            actual_limit = min(limit or self.DEFAULT_LIMIT, self.MAX_LIMIT)

            if "LIMIT" in query_upper:
                # Modify existing limit
                query = re.sub(
                    r"LIMIT\s+\d+",
                    f"LIMIT {actual_limit}",
                    query,
                    flags=re.IGNORECASE
                )
            else:
                # Add limit
                query = f"{query.rstrip().rstrip(';')} LIMIT {actual_limit}"

        return True, query, None


class SafeQueryBuilder:
    """Builds safe parameterized SQL queries"""

    def __init__(self):
        self.permissions = TablePermissions()

    def build_select(
        self,
        table: str,
        columns: Optional[List[str]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        order_dir: str = "DESC",
        limit: int = 100,
        joins: Optional[List[Dict]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Build a safe SELECT query with parameterized values

        Args:
            table: Main table name
            columns: Columns to select (None = allowed columns)
            conditions: WHERE conditions as {column: value}
            order_by: Column to order by
            order_dir: ASC or DESC
            limit: Result limit
            joins: List of join definitions

        Returns:
            Tuple of (query_string, parameters)
        """
        # Validate table access
        if not self.permissions.can_read(table):
            raise PermissionError(f"Read access denied for table: {table}")

        # Get columns
        if columns is None or columns == ["*"]:
            allowed = self.permissions.get_allowed_columns(table)
            if allowed == ["*"]:
                select_cols = "*"
            else:
                select_cols = ", ".join(allowed)
        else:
            # Validate and filter columns
            safe_columns = self.permissions.filter_sensitive_columns(columns)
            for col in safe_columns:
                if not self.permissions.can_read(table, col):
                    raise PermissionError(f"Read access denied for column: {table}.{col}")
            select_cols = ", ".join(safe_columns)

        # Start building query
        query = f"SELECT {select_cols} FROM {table}"
        params = {}

        # Add joins
        if joins:
            for i, join in enumerate(joins):
                join_table = join.get("table")
                join_type = join.get("type", "LEFT")
                join_on = join.get("on")

                if join_table and join_on:
                    if not self.permissions.can_read(join_table):
                        raise PermissionError(f"Read access denied for join table: {join_table}")
                    query += f" {join_type} JOIN {join_table} ON {join_on}"

        # Add WHERE conditions
        if conditions:
            where_clauses = []
            for i, (key, value) in enumerate(conditions.items()):
                param_name = f"p{i}"

                # Handle different condition types
                if isinstance(value, dict):
                    # Complex conditions like {"operator": ">=", "value": x}
                    op = value.get("operator", "=")
                    val = value.get("value")

                    if op.upper() in ["=", "!=", ">", "<", ">=", "<=", "LIKE", "IN", "IS NULL", "IS NOT NULL"]:
                        if op.upper() == "IN" and isinstance(val, list):
                            placeholders = ", ".join([f":p{i}_{j}" for j in range(len(val))])
                            where_clauses.append(f"{key} IN ({placeholders})")
                            for j, v in enumerate(val):
                                params[f"p{i}_{j}"] = v
                        elif op.upper() in ["IS NULL", "IS NOT NULL"]:
                            where_clauses.append(f"{key} {op}")
                        else:
                            where_clauses.append(f"{key} {op} :{param_name}")
                            params[param_name] = val
                elif value is None:
                    where_clauses.append(f"{key} IS NULL")
                else:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value

            if where_clauses:
                query += f" WHERE {' AND '.join(where_clauses)}"

        # Add ORDER BY
        if order_by:
            # Validate order_by column
            safe_order = re.sub(r"[^a-zA-Z0-9_.]", "", order_by)
            safe_dir = "DESC" if order_dir.upper() == "DESC" else "ASC"
            query += f" ORDER BY {safe_order} {safe_dir}"

        # Add LIMIT
        query += f" LIMIT {min(limit, 1000)}"

        return query, params

    def build_count(
        self,
        table: str,
        conditions: Optional[Dict[str, Any]] = None,
        group_by: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Build a COUNT query

        Args:
            table: Table name
            conditions: WHERE conditions
            group_by: Column to group by

        Returns:
            Tuple of (query_string, parameters)
        """
        if not self.permissions.can_read(table):
            raise PermissionError(f"Read access denied for table: {table}")

        query = f"SELECT COUNT(*) as count FROM {table}"
        params = {}

        # Add WHERE conditions
        if conditions:
            where_clauses = []
            for i, (key, value) in enumerate(conditions.items()):
                param_name = f"p{i}"
                if value is None:
                    where_clauses.append(f"{key} IS NULL")
                else:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value

            if where_clauses:
                query += f" WHERE {' AND '.join(where_clauses)}"

        # Add GROUP BY
        if group_by:
            safe_group = re.sub(r"[^a-zA-Z0-9_.]", "", group_by)
            query = query.replace("COUNT(*) as count", f"{safe_group}, COUNT(*) as count")
            query += f" GROUP BY {safe_group}"

        return query, params

    def build_aggregation(
        self,
        table: str,
        aggregations: List[Dict[str, str]],
        conditions: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Build an aggregation query (SUM, AVG, MIN, MAX)

        Args:
            table: Table name
            aggregations: List of {"function": "SUM", "column": "total_price", "alias": "revenue"}
            conditions: WHERE conditions

        Returns:
            Tuple of (query_string, parameters)
        """
        if not self.permissions.can_read(table):
            raise PermissionError(f"Read access denied for table: {table}")

        allowed_functions = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
        select_parts = []

        for agg in aggregations:
            func = agg.get("function", "COUNT").upper()
            column = agg.get("column", "*")
            alias = agg.get("alias", f"{func.lower()}_{column}")

            if func not in allowed_functions:
                raise ValueError(f"Aggregation function not allowed: {func}")

            if column != "*" and not self.permissions.can_read(table, column):
                raise PermissionError(f"Read access denied for column: {table}.{column}")

            safe_col = re.sub(r"[^a-zA-Z0-9_.*]", "", column)
            safe_alias = re.sub(r"[^a-zA-Z0-9_]", "", alias)
            select_parts.append(f"{func}({safe_col}) as {safe_alias}")

        query = f"SELECT {', '.join(select_parts)} FROM {table}"
        params = {}

        # Add WHERE conditions
        if conditions:
            where_clauses = []
            for i, (key, value) in enumerate(conditions.items()):
                param_name = f"p{i}"
                if isinstance(value, dict):
                    op = value.get("operator", "=")
                    val = value.get("value")
                    where_clauses.append(f"{key} {op} :{param_name}")
                    params[param_name] = val
                elif value is None:
                    where_clauses.append(f"{key} IS NULL")
                else:
                    where_clauses.append(f"{key} = :{param_name}")
                    params[param_name] = value

            if where_clauses:
                query += f" WHERE {' AND '.join(where_clauses)}"

        return query, params


class SQLExecutor:
    """Executes validated SQL queries"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.validator = QueryValidator()
        self.builder = SafeQueryBuilder()

    async def execute_raw(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> QueryResult:
        """
        Execute a raw SQL query with validation

        Args:
            query: SQL query to execute
            params: Query parameters
            limit: Result limit

        Returns:
            QueryResult with execution details
        """
        import time
        start_time = time.time()

        # Validate query
        is_valid, modified_query, error = self.validator.validate_and_limit(query, limit)

        if not is_valid:
            return QueryResult(
                success=False,
                data=[],
                row_count=0,
                query=query,
                parameters=params or {},
                execution_time_ms=0,
                error=error
            )

        try:
            result = await self.session.execute(
                text(modified_query),
                params or {}
            )

            # Fetch results
            rows = result.fetchall()
            columns = result.keys() if hasattr(result, 'keys') else []

            # Convert to list of dicts
            data = [dict(zip(columns, row)) for row in rows]

            execution_time = int((time.time() - start_time) * 1000)

            return QueryResult(
                success=True,
                data=data,
                row_count=len(data),
                query=modified_query,
                parameters=params or {},
                execution_time_ms=execution_time,
                truncated=len(data) >= (limit or self.validator.DEFAULT_LIMIT)
            )

        except Exception as e:
            logger.error(f"Query execution error: {e}")
            execution_time = int((time.time() - start_time) * 1000)

            return QueryResult(
                success=False,
                data=[],
                row_count=0,
                query=modified_query,
                parameters=params or {},
                execution_time_ms=execution_time,
                error=str(e)
            )

    async def execute_safe(
        self,
        table: str,
        columns: Optional[List[str]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        order_dir: str = "DESC",
        limit: int = 100
    ) -> QueryResult:
        """
        Execute a safe parameterized SELECT query

        Args:
            table: Table name
            columns: Columns to select
            conditions: WHERE conditions
            order_by: Order by column
            order_dir: ASC or DESC
            limit: Result limit

        Returns:
            QueryResult with execution details
        """
        try:
            query, params = self.builder.build_select(
                table=table,
                columns=columns,
                conditions=conditions,
                order_by=order_by,
                order_dir=order_dir,
                limit=limit
            )
            return await self.execute_raw(query, params, limit)
        except PermissionError as e:
            return QueryResult(
                success=False,
                data=[],
                row_count=0,
                query="",
                parameters={},
                execution_time_ms=0,
                error=str(e)
            )

    async def count(
        self,
        table: str,
        conditions: Optional[Dict[str, Any]] = None,
        group_by: Optional[str] = None
    ) -> QueryResult:
        """Execute a COUNT query"""
        try:
            query, params = self.builder.build_count(table, conditions, group_by)
            return await self.execute_raw(query, params)
        except PermissionError as e:
            return QueryResult(
                success=False,
                data=[],
                row_count=0,
                query="",
                parameters={},
                execution_time_ms=0,
                error=str(e)
            )

    async def aggregate(
        self,
        table: str,
        aggregations: List[Dict[str, str]],
        conditions: Optional[Dict[str, Any]] = None
    ) -> QueryResult:
        """Execute an aggregation query"""
        try:
            query, params = self.builder.build_aggregation(table, aggregations, conditions)
            return await self.execute_raw(query, params)
        except PermissionError as e:
            return QueryResult(
                success=False,
                data=[],
                row_count=0,
                query="",
                parameters={},
                execution_time_ms=0,
                error=str(e)
            )


# Query templates for common admin queries
# These templates work with SQLite (date comparisons use DATE() function)
QUERY_TEMPLATES = {
    "bookings_all": {
        "description": "Get all bookings (no date filter)",
        "query": """
            SELECT b.id, b.confirmation_code, b.arrival_date, b.departure_date,
                   b.check_in_date, b.check_out_date, b.status, b.total_price,
                   b.adults, b.children,
                   g.first_name, g.last_name, g.email, g.phone, g.vip_status,
                   rt.name as room_type_name, r.number as room_number
            FROM bookings b
            LEFT JOIN guests g ON b.guest_id = g.id
            LEFT JOIN room_types rt ON b.room_type_id = rt.id
            LEFT JOIN rooms r ON b.room_id = r.id
            ORDER BY b.arrival_date DESC
            LIMIT 100
        """,
        "params": lambda: {},
    },
    "bookings_today": {
        "description": "Get today's bookings with check-in time",
        "query": """
            SELECT b.id, b.confirmation_code, b.arrival_date, b.departure_date,
                   b.check_in_date, b.check_out_date,
                   COALESCE(b.check_in_date, b.arrival_date || ' 15:00:00') as expected_check_in_time,
                   b.status, b.total_price, b.adults, b.children,
                   g.first_name, g.last_name, g.email, g.phone, g.vip_status,
                   rt.name as room_type_name, r.number as room_number
            FROM bookings b
            LEFT JOIN guests g ON b.guest_id = g.id
            LEFT JOIN room_types rt ON b.room_type_id = rt.id
            LEFT JOIN rooms r ON b.room_id = r.id
            WHERE b.arrival_date >= :today_start AND b.arrival_date < :today_end
            ORDER BY b.arrival_date, b.check_in_date
            LIMIT 100
        """,
        "params": lambda: {
            "today_start": date.today().isoformat(),
            "today_end": (date.today() + timedelta(days=1)).isoformat()
        },
    },
    "bookings_tomorrow": {
        "description": "Get tomorrow's arrivals with check-in time",
        "query": """
            SELECT b.id, b.confirmation_code, b.arrival_date, b.departure_date,
                   b.check_in_date, b.check_out_date,
                   COALESCE(b.check_in_date, b.arrival_date || ' 15:00:00') as expected_check_in_time,
                   b.status, b.total_price, b.adults, b.children,
                   g.first_name, g.last_name, g.email, g.phone, g.vip_status,
                   rt.name as room_type_name, r.number as room_number
            FROM bookings b
            LEFT JOIN guests g ON b.guest_id = g.id
            LEFT JOIN room_types rt ON b.room_type_id = rt.id
            LEFT JOIN rooms r ON b.room_id = r.id
            WHERE b.arrival_date >= :tomorrow_start AND b.arrival_date < :tomorrow_end
            ORDER BY b.arrival_date, b.check_in_date
            LIMIT 100
        """,
        "params": lambda: {
            "tomorrow_start": (date.today() + timedelta(days=1)).isoformat(),
            "tomorrow_end": (date.today() + timedelta(days=2)).isoformat()
        },
    },
    "vip_guests": {
        "description": "Get VIP guests",
        "query": """
            SELECT id, first_name, last_name, email, phone,
                   loyalty_tier, loyalty_points, vip_status,
                   total_bookings, total_spent
            FROM guests
            WHERE vip_status = 1 OR loyalty_tier IN ('gold', 'platinum')
            ORDER BY total_spent DESC
            LIMIT 50
        """,
        "params": lambda: {},
    },
    "revenue_today": {
        "description": "Get today's revenue",
        "query": """
            SELECT
                COALESCE(SUM(total_price), 0) as total_revenue,
                COUNT(*) as booking_count,
                COALESCE(AVG(total_price), 0) as avg_booking_value
            FROM bookings
            WHERE arrival_date >= :today_start AND arrival_date < :today_end
        """,
        "params": lambda: {
            "today_start": date.today().isoformat(),
            "today_end": (date.today() + timedelta(days=1)).isoformat()
        },
    },
    "occupancy_current": {
        "description": "Get current occupancy",
        "query": """
            SELECT
                COUNT(CASE WHEN status IN ('occupied', 'checked_in') THEN 1 END) as occupied_rooms,
                COUNT(*) as total_rooms,
                ROUND(
                    CAST(COUNT(CASE WHEN status IN ('occupied', 'checked_in') THEN 1 END) AS FLOAT) * 100.0 /
                    NULLIF(COUNT(*), 0), 1
                ) as occupancy_rate
            FROM rooms
            WHERE status != 'out_of_service'
        """,
        "params": lambda: {},
    },
    "pending_housekeeping": {
        "description": "Get pending housekeeping tasks",
        "query": """
            SELECT ht.id, ht.room_id, ht.task_type, ht.priority, ht.status,
                   ht.created_at, r.number as room_number
            FROM housekeeping_tasks ht
            LEFT JOIN rooms r ON ht.room_id = r.id
            WHERE ht.status IN ('pending', 'in_progress')
            ORDER BY
                CASE ht.priority
                    WHEN 'urgent' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END,
                ht.created_at
            LIMIT 50
        """,
        "params": lambda: {},
    },
    "open_maintenance": {
        "description": "Get open maintenance requests",
        "query": """
            SELECT mr.id, mr.room_id, mr.category, mr.issue, mr.priority,
                   mr.status, mr.created_at, r.number as room_number
            FROM maintenancerequest mr
            LEFT JOIN rooms r ON mr.room_id = r.id
            WHERE mr.status IN ('open', 'in_progress')
            ORDER BY
                CASE mr.priority
                    WHEN 'emergency' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END,
                mr.created_at
            LIMIT 50
        """,
        "params": lambda: {},
    },
    "staff_on_shift": {
        "description": "Get staff currently on shift",
        "query": """
            SELECT s.id, s.name, s.department, s.role,
                   s.phone, s.shift, s.clocked_in
            FROM staff s
            WHERE s.status = 'active' AND s.clocked_in = 1
            ORDER BY s.department, s.name
            LIMIT 50
        """,
        "params": lambda: {},
    },
    "staff_all": {
        "description": "Get all active staff with count",
        "query": """
            SELECT s.id, s.name, s.department, s.role,
                   s.phone, s.shift, s.status, s.clocked_in
            FROM staff s
            WHERE s.status = 'active'
            ORDER BY s.department, s.name
            LIMIT 100
        """,
        "params": lambda: {},
    },
    "checkouts_today": {
        "description": "Get today's checkouts",
        "query": """
            SELECT b.id, b.confirmation_code, b.departure_date, b.status,
                   g.first_name, g.last_name, g.email, r.number as room_number
            FROM bookings b
            LEFT JOIN guests g ON b.guest_id = g.id
            LEFT JOIN rooms r ON b.room_id = r.id
            WHERE b.departure_date >= :today_start AND b.departure_date < :today_end
              AND b.status = 'checked_in'
            ORDER BY b.departure_date
            LIMIT 100
        """,
        "params": lambda: {
            "today_start": date.today().isoformat(),
            "today_end": (date.today() + timedelta(days=1)).isoformat()
        },
    },
    "revenue_this_month": {
        "description": "Get this month's revenue",
        "query": """
            SELECT
                COALESCE(SUM(total_price), 0) as total_revenue,
                COUNT(*) as booking_count,
                COALESCE(AVG(total_price), 0) as avg_booking_value,
                COALESCE(SUM(CASE WHEN status = 'checked_out' THEN total_price ELSE 0 END), 0) as realized_revenue
            FROM bookings
            WHERE arrival_date >= :month_start AND arrival_date < :month_end
        """,
        "params": lambda: {
            "month_start": date.today().replace(day=1).isoformat(),
            "month_end": (date.today().replace(day=1) + timedelta(days=32)).replace(day=1).isoformat()
        },
    },
}
