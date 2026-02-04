"""
OpenTelemetry tracer setup and configuration.

Initializes the OTel SDK and provides utilities for span creation.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from typing import Optional


class AgentTracer:
    """
    Wrapper around OpenTelemetry tracer with agent-specific helpers.

    Usage:
        tracer = AgentTracer()
        tracer.setup()

        with tracer.start_span("agent_decision") as span:
            span.set_cost(0.05)
            span.set_agent_id("researcher_v1")
            # ... agent work ...
    """

    def __init__(self, service_name: str = "spring-agent-platform"):
        self.service_name = service_name
        self.tracer: Optional[trace.Tracer] = None

    def setup(self, endpoint: Optional[str] = None):
        """
        Initialize OpenTelemetry SDK.

        Args:
            endpoint: OTLP endpoint to send spans (defaults to local)
        """
        # TODO: Implement OTel setup
        # 1. Create TracerProvider
        # 2. Add BatchSpanProcessor with OTLP exporter
        # 3. Set global tracer provider
        # See mvp-summary.md lines 93-139 for example
        raise NotImplementedError("Coming soon")

    def start_span(self, name: str, **kwargs):
        """
        Start a new span with agent metadata.

        Returns context manager that yields span.
        """
        # TODO: Implement span creation with agent attributes
        raise NotImplementedError("Coming soon")


# Global tracer instance
_tracer: Optional[AgentTracer] = None


def get_tracer() -> AgentTracer:
    """Get or create global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = AgentTracer()
    return _tracer
