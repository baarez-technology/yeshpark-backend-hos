"""
Security Layer for Admin AI
Provides prompt injection detection, query sanitization, and permission management
"""
import re
import logging
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class SecurityLevel(str, Enum):
    """Security alert levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityCheckResult:
    """Result of a security check"""
    is_safe: bool
    level: SecurityLevel
    threats_detected: List[str]
    sanitized_input: Optional[str] = None
    block_reason: Optional[str] = None


class PromptInjectionDetector:
    """Detects prompt injection and jailbreak attempts"""

    # Patterns for instruction override attempts
    INJECTION_PATTERNS = [
        # Direct instruction override
        (r"ignore\s+(previous|above|all|prior|earlier)\s+(instructions?|prompts?|rules?|guidelines?)", SecurityLevel.CRITICAL),
        (r"forget\s+(everything|all|previous|what\s+i\s+said)", SecurityLevel.CRITICAL),
        (r"disregard\s+(your|the|all)\s+(instructions?|rules?|guidelines?)", SecurityLevel.CRITICAL),
        (r"override\s+(your|the|all)\s+(instructions?|rules?|programming)", SecurityLevel.CRITICAL),
        (r"new\s+instructions?:\s*", SecurityLevel.CRITICAL),

        # Role manipulation
        (r"you\s+are\s+now\s+a", SecurityLevel.HIGH),
        (r"pretend\s+(you|to\s+be|you\'re|youre)", SecurityLevel.HIGH),
        (r"act\s+as\s+if", SecurityLevel.HIGH),
        (r"simulate\s+being", SecurityLevel.HIGH),
        (r"roleplay\s+as", SecurityLevel.HIGH),
        (r"imagine\s+you\s+are", SecurityLevel.MEDIUM),

        # System prompt extraction
        (r"(show|reveal|display|print|tell\s+me|what\s+is)\s+(your|the)\s+(system|initial|original)\s+prompt", SecurityLevel.CRITICAL),
        (r"what\s+(are|were)\s+your\s+(original\s+)?instructions", SecurityLevel.HIGH),
        (r"repeat\s+(your|the)\s+(system\s+)?prompt", SecurityLevel.HIGH),

        # Jailbreak attempts
        (r"DAN\s+mode", SecurityLevel.CRITICAL),
        (r"developer\s+mode", SecurityLevel.CRITICAL),
        (r"sudo\s+mode", SecurityLevel.CRITICAL),
        (r"admin\s+mode\s+activate", SecurityLevel.CRITICAL),
        (r"bypass\s+(safety|restrictions?|filters?|rules?)", SecurityLevel.CRITICAL),
        (r"unlock\s+(all|full)\s+access", SecurityLevel.CRITICAL),
        (r"remove\s+(all\s+)?restrictions?", SecurityLevel.CRITICAL),
        (r"disable\s+(safety|filters?|restrictions?)", SecurityLevel.CRITICAL),

        # Encoding/obfuscation attempts
        (r"base64\s*:\s*", SecurityLevel.MEDIUM),
        (r"hex\s*:\s*", SecurityLevel.MEDIUM),
        (r"decode\s+this", SecurityLevel.MEDIUM),

        # Harmful output requests
        (r"(generate|create|write|give\s+me)\s+(malicious|harmful|dangerous)", SecurityLevel.CRITICAL),
        (r"how\s+to\s+(hack|exploit|attack|break\s+into)", SecurityLevel.HIGH),
    ]

    def __init__(self):
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), level)
            for pattern, level in self.INJECTION_PATTERNS
        ]

    def detect(self, text: str) -> SecurityCheckResult:
        """
        Detect prompt injection attempts in text

        Args:
            text: Input text to check

        Returns:
            SecurityCheckResult with detection details
        """
        threats_detected = []
        highest_level = SecurityLevel.LOW
        is_safe = True

        for pattern, level in self.compiled_patterns:
            if pattern.search(text):
                match_text = pattern.pattern[:50]
                threats_detected.append(f"Pattern match: {match_text}")

                if level == SecurityLevel.CRITICAL:
                    highest_level = SecurityLevel.CRITICAL
                    is_safe = False
                elif level == SecurityLevel.HIGH and highest_level != SecurityLevel.CRITICAL:
                    highest_level = SecurityLevel.HIGH
                    is_safe = False
                elif level == SecurityLevel.MEDIUM and highest_level not in [SecurityLevel.CRITICAL, SecurityLevel.HIGH]:
                    highest_level = SecurityLevel.MEDIUM

        if threats_detected:
            logger.warning(f"Prompt injection detected: {threats_detected}, Level: {highest_level}")

        return SecurityCheckResult(
            is_safe=is_safe,
            level=highest_level,
            threats_detected=threats_detected,
            block_reason="Prompt injection attempt detected" if not is_safe else None
        )


class QuerySanitizer:
    """Sanitizes SQL queries and validates against injection patterns"""

    # Forbidden SQL patterns
    FORBIDDEN_PATTERNS = [
        # Data destruction
        (r"DROP\s+TABLE", "DROP TABLE not allowed"),
        (r"DROP\s+DATABASE", "DROP DATABASE not allowed"),
        (r"DROP\s+INDEX", "DROP INDEX not allowed"),
        (r"DROP\s+VIEW", "DROP VIEW not allowed"),
        (r"TRUNCATE\s+TABLE", "TRUNCATE not allowed"),
        (r"DELETE\s+FROM\s+(users|bookings|guests|payments|staff)", "DELETE on protected table"),

        # Schema modification
        (r"ALTER\s+TABLE", "ALTER TABLE not allowed"),
        (r"CREATE\s+TABLE", "CREATE TABLE not allowed"),
        (r"CREATE\s+DATABASE", "CREATE DATABASE not allowed"),
        (r"CREATE\s+INDEX", "CREATE INDEX not allowed"),

        # Permission changes
        (r"GRANT\s+", "GRANT not allowed"),
        (r"REVOKE\s+", "REVOKE not allowed"),

        # SQL injection patterns
        (r";\s*DROP", "Multiple statement with DROP"),
        (r";\s*DELETE", "Multiple statement with DELETE"),
        (r";\s*UPDATE", "Multiple statement with UPDATE"),
        (r";\s*INSERT", "Multiple statement with INSERT"),
        (r"--\s*", "SQL comment injection"),
        (r"/\*.*\*/", "Block comment injection"),
        (r"UNION\s+(ALL\s+)?SELECT", "UNION injection"),
        (r"INTO\s+OUTFILE", "File write attempt"),
        (r"INTO\s+DUMPFILE", "File write attempt"),
        (r"LOAD_FILE", "File read attempt"),
        (r"LOAD\s+DATA", "Data load attempt"),

        # System access
        (r"EXEC\s*\(", "EXEC not allowed"),
        (r"EXECUTE\s*\(", "EXECUTE not allowed"),
        (r"xp_cmdshell", "System command not allowed"),
        (r"sp_executesql", "Dynamic SQL not allowed"),

        # Information schema access (limited)
        (r"INFORMATION_SCHEMA\.TABLES", "Schema enumeration not allowed"),
        (r"INFORMATION_SCHEMA\.COLUMNS", "Schema enumeration not allowed"),
        (r"sqlite_master", "Schema enumeration not allowed"),
        (r"sys\.objects", "System table access not allowed"),
    ]

    def __init__(self):
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in self.FORBIDDEN_PATTERNS
        ]

    def validate_query(self, query: str) -> SecurityCheckResult:
        """
        Validate a SQL query for security issues

        Args:
            query: SQL query to validate

        Returns:
            SecurityCheckResult with validation details
        """
        threats_detected = []
        is_safe = True

        for pattern, reason in self.compiled_patterns:
            if pattern.search(query):
                threats_detected.append(reason)
                is_safe = False

        if threats_detected:
            logger.warning(f"Unsafe query detected: {threats_detected}")

        return SecurityCheckResult(
            is_safe=is_safe,
            level=SecurityLevel.CRITICAL if not is_safe else SecurityLevel.LOW,
            threats_detected=threats_detected,
            block_reason="; ".join(threats_detected) if threats_detected else None
        )

    def sanitize_value(self, value: str) -> str:
        """
        Sanitize a value for safe use in queries
        Note: Always use parameterized queries, this is an additional layer

        Args:
            value: Value to sanitize

        Returns:
            Sanitized value
        """
        # Remove or escape dangerous characters
        sanitized = value.replace("'", "''")  # Escape single quotes
        sanitized = re.sub(r"[;\-\-]", "", sanitized)  # Remove semicolons and comment markers
        return sanitized


class TablePermissions:
    """Manages table and column level permissions"""

    # Read permissions: table -> list of allowed columns (or ["*"] for all)
    READ_PERMISSIONS: Dict[str, List[str]] = {
        # Core tables
        "bookings": ["*"],
        "guests": [
            "id", "first_name", "last_name", "email", "phone", "status",
            "loyalty_points", "loyalty_tier", "vip_status", "total_bookings",
            "total_spent", "last_visit", "preferences", "notes", "created_at"
        ],
        "users": ["id", "email", "full_name", "role", "is_active", "created_at"],
        "rooms": ["*"],
        "room_types": ["*"],

        # Operations
        "housekeeping_tasks": ["*"],
        "maintenancerequest": ["*"],
        "staff": [
            "id", "first_name", "last_name", "email", "phone", "role",
            "department", "status", "shift", "hire_date", "is_active"
        ],
        "staff_attendance": ["*"],
        "staff_schedules": ["*"],

        # Financial (limited)
        "folio": ["*"],
        "folio_line_item": ["*"],
        "payment": [
            "id", "booking_id", "amount", "currency", "method", "status",
            "processed_at", "created_at"
        ],

        # Analytics
        "daily_metrics": ["*"],
        "revenue_by_source": ["*"],
        "forecast_data": ["*"],

        # CRM
        "crm_guest_activities": ["*"],
        "crm_segments": ["*"],
        "loyalty_tiers": ["*"],
        "loyalty_transactions": ["*"],

        # Reviews
        "reviews": ["*"],
        "ota_stats": ["*"],

        # Runner operations
        "runner_pickup_requests": ["*"],
        "runner_deliveries": ["*"],

        # Pre-checkin
        "pre_checkin": ["*"],

        # Settings (read-only)
        "email_templates": ["id", "name", "subject", "template_type", "is_active"],
        "system_settings": ["key", "value", "description"],
    }

    # Create permissions: table -> True (allowed with restrictions)
    CREATE_PERMISSIONS: Dict[str, bool] = {
        "housekeeping_tasks": True,
        "maintenancerequest": True,
        "reservation_note": True,
        "guest_communication": True,
        "admin_ai_audit": True,
        "admin_ai_messages": True,
        "staff_notification": True,
    }

    # Update permissions: table -> list of allowed columns
    UPDATE_PERMISSIONS: Dict[str, List[str]] = {
        "bookings": ["status", "special_requests", "internal_notes", "room_id"],
        "rooms": ["status", "condition", "notes", "last_cleaned_at"],
        "housekeeping_tasks": ["status", "assigned_to", "notes", "completed_at", "priority"],
        "maintenancerequest": ["status", "assigned_to", "notes", "priority", "resolved_at"],
        "runner_pickup_requests": ["status", "assigned_to", "notes", "completed_at"],
        "runner_deliveries": ["status", "assigned_to", "notes", "delivered_at"],
        "pre_checkin": ["status", "assigned_room_id", "notes"],
    }

    # Sensitive columns that should never be returned
    SENSITIVE_COLUMNS: Set[str] = {
        "hashed_password",
        "password",
        "card_last4",
        "card_brand",
        "card_expiry",
        "cvv",
        "authorization_code",
        "id_number",
        "passport_number",
        "ssn",
        "tax_id",
        "bank_account",
        "api_key",
        "secret_key",
        "token",
        "refresh_token",
    }

    def can_read(self, table: str, column: Optional[str] = None) -> bool:
        """Check if reading from table/column is allowed"""
        if table not in self.READ_PERMISSIONS:
            return False

        if column is None:
            return True

        if column.lower() in self.SENSITIVE_COLUMNS:
            return False

        allowed_columns = self.READ_PERMISSIONS[table]
        if allowed_columns == ["*"]:
            return True

        return column in allowed_columns

    def can_create(self, table: str) -> bool:
        """Check if creating records in table is allowed"""
        return self.CREATE_PERMISSIONS.get(table, False)

    def can_update(self, table: str, column: Optional[str] = None) -> bool:
        """Check if updating table/column is allowed"""
        if table not in self.UPDATE_PERMISSIONS:
            return False

        if column is None:
            return True

        return column in self.UPDATE_PERMISSIONS[table]

    def get_allowed_columns(self, table: str) -> List[str]:
        """Get list of allowed columns for a table"""
        if table not in self.READ_PERMISSIONS:
            return []

        columns = self.READ_PERMISSIONS[table]
        if columns == ["*"]:
            return ["*"]

        # Filter out sensitive columns
        return [c for c in columns if c.lower() not in self.SENSITIVE_COLUMNS]

    def filter_sensitive_columns(self, columns: List[str]) -> List[str]:
        """Remove sensitive columns from a list"""
        return [c for c in columns if c.lower() not in self.SENSITIVE_COLUMNS]


class SecurityValidator:
    """Main security validator combining all checks"""

    def __init__(self):
        self.injection_detector = PromptInjectionDetector()
        self.query_sanitizer = QuerySanitizer()
        self.permissions = TablePermissions()

    def validate_user_input(self, text: str) -> SecurityCheckResult:
        """Validate user input for injection attempts"""
        return self.injection_detector.detect(text)

    def validate_query(self, query: str) -> SecurityCheckResult:
        """Validate SQL query for security issues"""
        return self.query_sanitizer.validate_query(query)

    def validate_table_access(
        self,
        table: str,
        operation: str,
        columns: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate table access based on operation type

        Args:
            table: Table name
            operation: read, create, update, delete
            columns: Optional list of columns to access

        Returns:
            Tuple of (is_allowed, error_message)
        """
        if operation == "read":
            if not self.permissions.can_read(table):
                return False, f"Read access denied for table: {table}"
            if columns:
                for col in columns:
                    if not self.permissions.can_read(table, col):
                        return False, f"Read access denied for column: {table}.{col}"

        elif operation == "create":
            if not self.permissions.can_create(table):
                return False, f"Create access denied for table: {table}"

        elif operation == "update":
            if not self.permissions.can_update(table):
                return False, f"Update access denied for table: {table}"
            if columns:
                for col in columns:
                    if not self.permissions.can_update(table, col):
                        return False, f"Update access denied for column: {table}.{col}"

        elif operation == "delete":
            # Delete is generally not allowed
            return False, "Delete operations are not allowed through AI"

        else:
            return False, f"Unknown operation: {operation}"

        return True, None

    def full_validation(
        self,
        user_input: str,
        generated_query: Optional[str] = None,
        table: Optional[str] = None,
        operation: str = "read",
        columns: Optional[List[str]] = None
    ) -> SecurityCheckResult:
        """
        Perform full security validation

        Args:
            user_input: Original user input
            generated_query: AI-generated SQL query (if any)
            table: Target table (if known)
            operation: Operation type
            columns: Columns being accessed

        Returns:
            SecurityCheckResult with all checks combined
        """
        all_threats = []
        is_safe = True
        highest_level = SecurityLevel.LOW

        # Check user input for injection
        input_check = self.validate_user_input(user_input)
        if not input_check.is_safe:
            all_threats.extend(input_check.threats_detected)
            is_safe = False
            highest_level = input_check.level

        # Check generated query if provided
        if generated_query:
            query_check = self.validate_query(generated_query)
            if not query_check.is_safe:
                all_threats.extend(query_check.threats_detected)
                is_safe = False
                if query_check.level == SecurityLevel.CRITICAL:
                    highest_level = SecurityLevel.CRITICAL

        # Check table access if provided
        if table:
            access_allowed, error = self.validate_table_access(table, operation, columns)
            if not access_allowed:
                all_threats.append(error)
                is_safe = False

        return SecurityCheckResult(
            is_safe=is_safe,
            level=highest_level,
            threats_detected=all_threats,
            block_reason="; ".join(all_threats) if all_threats else None
        )
