"""
Core data models for spans, traces, and decisions.

Uses Pydantic for validation and type safety.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class SpanStatus(str, Enum):
    """Span execution status."""
    SUCCESS = "success"
    ERROR = "error"
    RUNNING = "running"


class Span(BaseModel):
    """
    Represents a single unit of work (LLM call, agent decision, tool call).

    Maps to OpenTelemetry span with additional agent-specific metadata.
    """
    span_id: str
    trace_id: str
    parent_span_id: Optional[str] = None
    name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None

    # Agent metadata
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    decision_node: bool = False  # Is this a decision point?
    triggered_by: Optional[str] = None

    # Cost tracking
    cost_usd: Optional[float] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    tokens_total: Optional[int] = None
    model: Optional[str] = None

    # Execution tracking
    status: SpanStatus = SpanStatus.RUNNING
    attempt_number: int = 1
    decision_made: Optional[str] = None

    # Additional context
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    """
    Represents a complete execution workflow (collection of related spans).
    """
    trace_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None

    # Aggregated metrics
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    span_count: int = 0

    # Outcome tracking
    status: SpanStatus = SpanStatus.RUNNING
    outcome: Optional[str] = None  # success, failure, timeout, etc.

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionCost(BaseModel):
    """
    Aggregated cost for a decision and all downstream work it triggered.

    This is the core differentiator - recursive cost aggregation.
    """
    decision_span_id: str
    decision_name: str
    agent_id: Optional[str] = None

    # Cost breakdown
    direct_cost: float
    child_cost: float
    total_cost: float

    # Execution info
    status: SpanStatus
    child_breakdown: List['DecisionCost'] = Field(default_factory=list)

    # Waste detection
    waste_detected: List[Dict[str, Any]] = Field(default_factory=list)
    cascade_impact: Optional[Dict[str, Any]] = None

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Enable forward references
DecisionCost.model_rebuild()
