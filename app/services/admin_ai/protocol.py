"""
Protocol models for the Admin AI Multi-Agent Architecture.
All shared Pydantic/TypedDict models used across agents and orchestrator.
"""
from __future__ import annotations

import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, TypedDict
try:
    from typing import Annotated
except ImportError:
    from typing_extensions import Annotated

from pydantic import BaseModel, Field

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# ─────────────────────── Enums ───────────────────────


class IntentCategory(str, Enum):
    """High-level intent categories for routing."""
    QUERY = "query"
    ACTION = "action"
    REPORT = "report"
    FILE = "file"
    GENERAL = "general"
    FOLLOW_UP = "follow_up"
    HELP = "help"
    UNKNOWN = "unknown"


class ToolCategory(str, Enum):
    """Categories for tool registry."""
    QUERY = "query"
    ACTION = "action"
    REPORT = "report"
    FILE = "file"
    UTILITY = "utility"


# ─────────────────────── Session Context ───────────────────────


class SessionContext(BaseModel):
    """Enriched context sent by frontend with every message."""
    current_page: Optional[str] = None
    current_module: Optional[str] = None
    selected_booking_id: Optional[int] = None
    selected_guest_id: Optional[int] = None
    selected_room_id: Optional[int] = None
    selected_staff_id: Optional[int] = None
    active_filters: Optional[Dict[str, Any]] = None
    user_role: Optional[str] = None
    business_date: Optional[str] = None
    previous_messages: Optional[List[Dict[str, str]]] = None
    pending_action: Optional[Dict[str, Any]] = None


# ─────────────────────── Comprehension Result ───────────────────────


class DetectedIntent(BaseModel):
    """A single detected intent from the comprehension agent."""
    intent: str = Field(description="The classified intent name (e.g. query_bookings)")
    category: IntentCategory = Field(description="High-level category for routing")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Extracted entities")


class ComprehensionResult(BaseModel):
    """Output of the comprehension agent — supports multi-intent decomposition."""
    intents: List[DetectedIntent] = Field(default_factory=list)
    raw_message: str = ""
    is_follow_up: bool = False
    is_confirmation: bool = False
    is_cancellation: bool = False
    requires_clarification: bool = False
    clarification_question: Optional[str] = None


# ─────────────────────── Parameter Result ───────────────────────


class ParameterResult(BaseModel):
    """Output of the parameter agent — resolved params for tool execution."""
    intent: str
    resolved_params: Dict[str, Any] = Field(default_factory=dict)
    missing_params: List[str] = Field(default_factory=list)
    auto_filled_from_context: List[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None


# ─────────────────────── Data Result ───────────────────────


class DataResult(BaseModel):
    """Output of the data agent — query results."""
    success: bool = True
    data: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


# ─────────────────────── Action Result ───────────────────────


class ActionConfirmation(BaseModel):
    """Pending action awaiting user confirmation."""
    action_id: str
    action_type: str
    description: str
    params: Dict[str, Any] = Field(default_factory=dict)
    preview: Optional[Dict[str, Any]] = None


class ActionOutcome(BaseModel):
    """Result of executing an action."""
    success: bool
    action_id: str
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


# ─────────────────────── Active Entities (Context Memory) ───────────────────────


class ActiveEntities(BaseModel):
    """Tracks recently mentioned entities for pronoun resolution.
    E.g., 'check them in' → the guest we just discussed.
    """
    last_room_id: Optional[int] = None
    last_room_number: Optional[str] = None
    last_guest_id: Optional[int] = None
    last_guest_name: Optional[str] = None
    last_booking_id: Optional[int] = None
    last_staff_id: Optional[int] = None
    last_staff_name: Optional[str] = None
    last_task_id: Optional[int] = None


# ─────────────────────── Orchestrator State (LangGraph) ───────────────────────


class OrchestratorState(TypedDict):
    """LangGraph StateGraph state — flows through all agent nodes."""
    # LangGraph message history
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Request metadata
    user_message: str
    user_id: int
    session_id: str
    request_start_time: float

    # Session context from frontend
    session_context: dict  # Serialized SessionContext

    # Security gate output
    security_passed: bool
    security_block_reason: str

    # Comprehension agent output
    comprehension: dict  # Serialized ComprehensionResult

    # Parameter agent output
    parameters: list  # List of serialized ParameterResult

    # Execution results (from data/action agents)
    execution_results: list  # List of serialized DataResult or ActionOutcome

    # Pending action (if action requires confirmation)
    pending_action: dict  # Serialized ActionConfirmation or empty dict

    # Context memory
    active_entities: dict  # Serialized ActiveEntities
    context_summary: str  # Summarized conversation history

    # Final response
    response_message: str
    response_intent: str
    response_confidence: float
    response_suggestions: list
    response_query_results: list
    response_query_metadata: dict
    response_error: str

    # Audit
    audit_id: int


# ─────────────────────── Orchestrator Response ───────────────────────


class OrchestratorResponse(BaseModel):
    """Final response from the orchestrator — backward-compatible with AdminAIResponse."""
    message: str
    intent: str
    confidence: float
    session_id: str
    query_results: Optional[List[Dict[str, Any]]] = None
    query_metadata: Optional[Dict[str, Any]] = None
    pending_action: Optional[Dict[str, Any]] = None
    action_result: Optional[Dict[str, Any]] = None
    suggestions: List[str] = Field(default_factory=list)
    audit_id: Optional[int] = None
    error: Optional[str] = None
    # New fields for multi-agent
    intents_detected: Optional[List[str]] = None
    auto_filled_params: Optional[List[str]] = None
    context_entities: Optional[Dict[str, Any]] = None
