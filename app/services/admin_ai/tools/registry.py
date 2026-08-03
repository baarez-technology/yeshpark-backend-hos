"""
Tool Registry for Admin AI Multi-Agent Architecture.
Provides @register_tool decorator and ToolRegistry for dynamic tool discovery.
Tools auto-register on import via decorator.
"""
import inspect
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    """Categories for registered tools."""
    QUERY = "query"
    ACTION = "action"
    REPORT = "report"
    FILE = "file"
    UTILITY = "utility"


class ToolDefinition:
    """Metadata for a registered tool."""

    def __init__(
        self,
        name: str,
        func: Callable,
        category: ToolCategory,
        description: str,
        parameters_schema: Optional[Type[BaseModel]] = None,
        examples: Optional[List[str]] = None,
        requires_confirmation: bool = False,
        required_permissions: Optional[List[str]] = None,
    ):
        self.name = name
        self.func = func
        self.category = category
        self.description = description
        self.parameters_schema = parameters_schema
        self.examples = examples or []
        self.requires_confirmation = requires_confirmation
        self.required_permissions = required_permissions or []

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for LLM system prompts."""
        result = {
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "examples": self.examples,
            "requires_confirmation": self.requires_confirmation,
        }
        if self.parameters_schema:
            result["parameters"] = self.parameters_schema.model_json_schema()
        return result


class ToolRegistry:
    """Central registry for all admin AI tools.

    Tools register themselves via the @register_tool decorator.
    The registry provides tool lookup, filtering, and serialization
    for LLM function calling and system prompts.
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        func: Callable,
        category: ToolCategory,
        description: str = "",
        parameters_schema: Optional[Type[BaseModel]] = None,
        examples: Optional[List[str]] = None,
        requires_confirmation: bool = False,
        required_permissions: Optional[List[str]] = None,
    ) -> ToolDefinition:
        """Register a tool in the registry."""
        if not description:
            description = inspect.getdoc(func) or f"Tool: {name}"

        tool_def = ToolDefinition(
            name=name,
            func=func,
            category=category,
            description=description,
            parameters_schema=parameters_schema,
            examples=examples,
            requires_confirmation=requires_confirmation,
            required_permissions=required_permissions,
        )
        self._tools[name] = tool_def
        logger.debug(f"Registered tool: {name} (category: {category.value})")
        return tool_def

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_by_category(self, category: ToolCategory) -> List[ToolDefinition]:
        """Get all tools in a category."""
        return [t for t in self._tools.values() if t.category == category]

    def get_all(self) -> List[ToolDefinition]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_tool_names(self) -> List[str]:
        """Get all registered tool names."""
        return list(self._tools.keys())

    def get_tool_descriptions(self) -> str:
        """Generate formatted tool descriptions for LLM system prompts."""
        sections = {}
        for tool in self._tools.values():
            cat = tool.category.value.upper()
            if cat not in sections:
                sections[cat] = []
            entry = f"- **{tool.name}**: {tool.description}"
            if tool.examples:
                entry += f"\n  Examples: {', '.join(repr(e) for e in tool.examples[:3])}"
            sections[cat].append(entry)

        parts = []
        for cat, entries in sections.items():
            parts.append(f"### {cat} Tools\n" + "\n".join(entries))
        return "\n\n".join(parts)

    def get_intent_to_tool_map(self) -> Dict[str, str]:
        """Map intent names to tool names (by convention: tool name = intent name)."""
        return {name: name for name in self._tools}

    async def execute(self, name: str, params: Dict[str, Any]) -> Any:
        """Execute a tool by name with given parameters."""
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")

        func = tool.func
        if inspect.iscoroutinefunction(func):
            return await func(**params)
        else:
            return func(**params)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# ─── Global registry singleton ───

_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def register_tool(
    name: str,
    category: ToolCategory,
    description: str = "",
    parameters_schema: Optional[Type[BaseModel]] = None,
    examples: Optional[List[str]] = None,
    requires_confirmation: bool = False,
    required_permissions: Optional[List[str]] = None,
):
    """Decorator to register a function as an admin AI tool.

    Usage:
        @register_tool(
            name="query_bookings",
            category=ToolCategory.QUERY,
            parameters_schema=QueryBookingsParams,
            examples=["Show bookings today", "Arrivals for Dec 15"]
        )
        async def query_bookings(date=None, status=None, _session=None):
            ...
    """
    def decorator(func: Callable) -> Callable:
        registry = get_registry()
        registry.register(
            name=name,
            func=func,
            category=category,
            description=description or inspect.getdoc(func) or "",
            parameters_schema=parameters_schema,
            examples=examples,
            requires_confirmation=requires_confirmation,
            required_permissions=required_permissions,
        )
        # Mark the function so we know it's registered
        func._tool_name = name
        func._tool_category = category
        return func

    return decorator
