"""
Admin AI Services Package
Provides secure AI-powered administration capabilities
"""
from .security import (
    PromptInjectionDetector,
    QuerySanitizer,
    TablePermissions,
    SecurityValidator,
)
from .sql_executor import SafeQueryBuilder, QueryValidator, SQLExecutor
from .action_executor import ActionExecutor, EmailActionExecutor

__all__ = [
    "PromptInjectionDetector",
    "QuerySanitizer",
    "TablePermissions",
    "SecurityValidator",
    "SafeQueryBuilder",
    "QueryValidator",
    "SQLExecutor",
    "ActionExecutor",
    "EmailActionExecutor",
]

# Multi-agent architecture (lazy imports to avoid circular deps)
def get_orchestrator(session):
    from .orchestrator import get_orchestrator as _get
    return _get(session)
