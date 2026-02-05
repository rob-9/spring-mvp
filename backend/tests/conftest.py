"""
Shared pytest fixtures and configuration.
"""

import pytest
from datetime import datetime
from backend.core.models import Span, SpanStatus


@pytest.fixture
def base_span_kwargs():
    """
    Common keyword arguments for creating Span objects.

    Provides defaults that can be overridden in tests.
    """
    return {
        "trace_id": "test_trace_001",
        "parent_span_id": "parent_span",
        "start_time": datetime(2025, 1, 15, 10, 0, 0),
        "status": SpanStatus.SUCCESS
    }


@pytest.fixture
def mock_span(base_span_kwargs):
    """
    Factory function to create mock Span objects.

    Usage:
        def test_example(mock_span):
            span = mock_span(span_id="test", name="operation", cost_usd=0.05)
    """
    def _create_span(
        span_id: str = "test_span",
        name: str = "test_operation",
        cost_usd: float = 0.05,
        attempt_number: int = 1,
        **kwargs
    ) -> Span:
        # Merge base kwargs with overrides
        span_kwargs = {**base_span_kwargs, **kwargs}

        return Span(
            span_id=span_id,
            name=name,
            cost_usd=cost_usd,
            attempt_number=attempt_number,
            **span_kwargs
        )

    return _create_span
