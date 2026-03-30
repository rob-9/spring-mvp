"""
OpenTelemetry tracer setup and agent-aware span creation.

Provides a thin wrapper around OTel SDK that adds agent-specific
attributes to spans. Used by framework adapters (CrewAI, AutoGen, etc.)
to emit properly attributed spans.
"""

from contextlib import contextmanager
from typing import Optional, Dict, Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import StatusCode, Span as OTelSpan


# Semantic conventions for agent observability
ATTR_AGENT_ID = "agent.id"
ATTR_AGENT_NAME = "agent.name"
ATTR_DECISION_NODE = "agent.decision_node"
ATTR_TRIGGERED_BY = "agent.triggered_by"
ATTR_ATTEMPT_NUMBER = "agent.attempt_number"
ATTR_DECISION_MADE = "agent.decision_made"
ATTR_COST_USD = "llm.cost_usd"
ATTR_TOKENS_INPUT = "llm.tokens.input"
ATTR_TOKENS_OUTPUT = "llm.tokens.output"
ATTR_TOKENS_TOTAL = "llm.tokens.total"
ATTR_MODEL = "llm.model"


class AgentTracer:
    """
    Wrapper around OpenTelemetry tracer with agent-specific helpers.

    Usage:
        tracer = AgentTracer(service_name="my-agent-app")
        tracer.setup(exporter=OTLPSpanExporter(endpoint="http://localhost:8000"))

        with tracer.start_agent_span("research", agent_id="researcher_v1") as span:
            span.set_attribute(ATTR_COST_USD, 0.05)
            # ... agent work ...
    """

    def __init__(self, service_name: str = "spring-agent-platform"):
        self.service_name = service_name
        self.tracer: Optional[trace.Tracer] = None
        self._provider: Optional[TracerProvider] = None

    def setup(self, exporter: Optional[SpanExporter] = None) -> None:
        """
        Initialize OpenTelemetry SDK.

        Args:
            exporter: Span exporter (defaults to OTLP if not provided).
                      Pass a custom exporter for testing or alternative backends.
        """
        resource = Resource.create({
            "service.name": self.service_name,
            "service.version": "0.1.0",
            "telemetry.sdk.name": "spring-agent-sdk",
        })

        self._provider = TracerProvider(resource=resource)

        if exporter is None:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter()
            except ImportError:
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter
                exporter = ConsoleSpanExporter()

        self._provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(self._provider)
        self.tracer = trace.get_tracer(
            "spring-agent-tracer",
            "0.1.0",
        )

    @contextmanager
    def start_agent_span(
        self,
        name: str,
        agent_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        decision_node: bool = False,
        triggered_by: Optional[str] = None,
        attempt_number: int = 1,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """
        Start a new span with agent metadata.

        Args:
            name: Span operation name
            agent_id: Unique agent identifier
            agent_name: Human-readable agent name
            decision_node: Whether this is a decision point
            triggered_by: ID of the span/decision that triggered this work
            attempt_number: Retry attempt number (1 = first attempt)
            attributes: Additional span attributes

        Yields:
            OTel Span with agent attributes set
        """
        if self.tracer is None:
            raise RuntimeError("Tracer not initialized. Call setup() first.")

        attrs = {}
        if agent_id:
            attrs[ATTR_AGENT_ID] = agent_id
        if agent_name:
            attrs[ATTR_AGENT_NAME] = agent_name
        if decision_node:
            attrs[ATTR_DECISION_NODE] = True
        if triggered_by:
            attrs[ATTR_TRIGGERED_BY] = triggered_by
        if attempt_number > 1:
            attrs[ATTR_ATTEMPT_NUMBER] = attempt_number
        if attributes:
            attrs.update(attributes)

        with self.tracer.start_as_current_span(name, attributes=attrs) as span:
            yield span

    def shutdown(self) -> None:
        """Flush pending spans and shut down the tracer provider."""
        if self._provider:
            self._provider.shutdown()


# Global tracer instance
_tracer: Optional[AgentTracer] = None


def get_tracer() -> AgentTracer:
    """Get or create global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = AgentTracer()
    return _tracer
