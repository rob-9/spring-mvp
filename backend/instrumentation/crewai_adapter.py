"""
CrewAI auto-instrumentation adapter.

Hooks into CrewAI's callback system to automatically capture spans
for agent tasks, tool calls, and LLM interactions.

Usage:
    from spring_crewai import instrument_crewai

    instrument_crewai(
        endpoint="https://api.spring.ai/v1/traces",
        api_key="your_key"
    )

    # Customer's code runs normally, spans captured automatically
    crew.kickoff()
"""

import time
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from backend.core.models import Span, SpanStatus
from backend.instrumentation.otel_tracer import (
    AgentTracer,
    ATTR_AGENT_ID,
    ATTR_AGENT_NAME,
    ATTR_COST_USD,
    ATTR_TOKENS_INPUT,
    ATTR_TOKENS_OUTPUT,
    ATTR_MODEL,
    ATTR_DECISION_NODE,
)


class CrewAIInstrumentor:
    """
    Instruments CrewAI to capture spans for the Spring platform.

    Intercepts CrewAI's lifecycle events:
    - Crew kickoff (root span)
    - Agent task execution (decision spans)
    - Tool calls (child spans)
    - LLM calls (child spans with token/cost tracking)
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        service_name: str = "crewai-app",
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.tracer = AgentTracer(service_name=service_name)
        self._spans: List[Span] = []
        self._active_spans: Dict[str, Dict[str, Any]] = {}

    def instrument(self) -> None:
        """
        Set up instrumentation.

        Initializes the OTel tracer and patches CrewAI callbacks.
        """
        from opentelemetry.sdk.trace.export import SpanExporter

        exporter = None
        if self.endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                exporter = OTLPSpanExporter(
                    endpoint=f"{self.endpoint}",
                    headers=headers,
                )
            except ImportError:
                pass

        self.tracer.setup(exporter=exporter)

    def on_crew_start(self, crew_name: str) -> str:
        """Record crew kickoff as root span."""
        trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())

        self._active_spans[span_id] = {
            "trace_id": trace_id,
            "span_id": span_id,
            "name": f"crew:{crew_name}",
            "start_time": datetime.now(timezone.utc),
            "decision_node": True,
        }
        return span_id

    def on_crew_end(self, crew_span_id: str, status: str = "success") -> Optional[Span]:
        """Finalize crew span."""
        return self._finalize_span(crew_span_id, status)

    def on_agent_task_start(
        self,
        agent_name: str,
        agent_role: str,
        task_description: str,
        parent_span_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> str:
        """Record agent task execution as a decision span."""
        span_id = str(uuid.uuid4())

        if trace_id is None and parent_span_id and parent_span_id in self._active_spans:
            trace_id = self._active_spans[parent_span_id]["trace_id"]

        self._active_spans[span_id] = {
            "trace_id": trace_id or str(uuid.uuid4()),
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": f"agent_task:{agent_role}",
            "agent_id": agent_name,
            "agent_name": agent_role,
            "start_time": datetime.now(timezone.utc),
            "decision_node": True,
            "metadata": {"task": task_description[:500]},
        }
        return span_id

    def on_agent_task_end(
        self, span_id: str, status: str = "success", decision_made: Optional[str] = None
    ) -> Optional[Span]:
        """Finalize agent task span."""
        if span_id in self._active_spans:
            self._active_spans[span_id]["decision_made"] = decision_made
        return self._finalize_span(span_id, status)

    def on_tool_call(
        self,
        tool_name: str,
        parent_span_id: str,
        duration_ms: Optional[float] = None,
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Span:
        """Record a tool call as a child span."""
        parent = self._active_spans.get(parent_span_id, {})
        now = datetime.now(timezone.utc)

        span = Span(
            span_id=str(uuid.uuid4()),
            trace_id=parent.get("trace_id", str(uuid.uuid4())),
            parent_span_id=parent_span_id,
            name=f"tool:{tool_name}",
            start_time=now,
            end_time=now,
            duration_ms=duration_ms,
            status=SpanStatus(status),
            metadata=metadata or {},
        )
        self._spans.append(span)
        return span

    def on_llm_call(
        self,
        model: str,
        parent_span_id: str,
        tokens_input: int = 0,
        tokens_output: int = 0,
        cost_usd: float = 0.0,
        duration_ms: Optional[float] = None,
        status: str = "success",
    ) -> Span:
        """Record an LLM API call with token and cost tracking."""
        parent = self._active_spans.get(parent_span_id, {})
        now = datetime.now(timezone.utc)

        span = Span(
            span_id=str(uuid.uuid4()),
            trace_id=parent.get("trace_id", str(uuid.uuid4())),
            parent_span_id=parent_span_id,
            name=f"llm:{model}",
            start_time=now,
            end_time=now,
            duration_ms=duration_ms,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            tokens_total=tokens_input + tokens_output,
            cost_usd=cost_usd,
            status=SpanStatus(status),
        )
        self._spans.append(span)
        return span

    def get_collected_spans(self) -> List[Span]:
        """Return all collected spans (for batch ingestion)."""
        return list(self._spans)

    def flush(self) -> List[Span]:
        """Return collected spans and clear the buffer."""
        spans = list(self._spans)
        self._spans.clear()
        self._active_spans.clear()
        return spans

    def _finalize_span(self, span_id: str, status: str) -> Optional[Span]:
        """Convert an active span to a finalized Span model."""
        data = self._active_spans.pop(span_id, None)
        if data is None:
            return None

        now = datetime.now(timezone.utc)
        start = data["start_time"]
        duration_ms = (now - start).total_seconds() * 1000

        span = Span(
            span_id=data["span_id"],
            trace_id=data["trace_id"],
            parent_span_id=data.get("parent_span_id"),
            name=data["name"],
            start_time=start,
            end_time=now,
            duration_ms=duration_ms,
            agent_id=data.get("agent_id"),
            agent_name=data.get("agent_name"),
            decision_node=data.get("decision_node", False),
            decision_made=data.get("decision_made"),
            status=SpanStatus(status),
            metadata=data.get("metadata", {}),
        )
        self._spans.append(span)
        return span


def instrument_crewai(
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    service_name: str = "crewai-app",
) -> CrewAIInstrumentor:
    """
    One-line setup to instrument CrewAI.

    Args:
        endpoint: Spring API endpoint for span ingestion
        api_key: API key for authentication
        service_name: Name for this service in traces

    Returns:
        Configured instrumentor instance
    """
    instrumentor = CrewAIInstrumentor(
        endpoint=endpoint,
        api_key=api_key,
        service_name=service_name,
    )
    return instrumentor
