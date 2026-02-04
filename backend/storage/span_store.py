"""
Span persistence layer.

Stores spans to database for later analysis.
"""

from typing import List, Optional
from backend.core.models import Span


class SpanStore:
    """
    Interface for span storage.

    Can be backed by PostgreSQL, MongoDB, or other databases.
    """

    def __init__(self, connection_string: str):
        self.connection_string = connection_string

    def save_span(self, span: Span) -> None:
        """Save a span to storage."""
        # TODO: Implement database insert
        raise NotImplementedError("Coming soon")

    def get_span(self, span_id: str) -> Optional[Span]:
        """Retrieve a span by ID."""
        # TODO: Implement database query
        raise NotImplementedError("Coming soon")

    def get_spans_by_trace(self, trace_id: str) -> List[Span]:
        """Get all spans for a trace."""
        # TODO: Implement trace query
        raise NotImplementedError("Coming soon")

    def get_children(self, span_id: str) -> List[Span]:
        """Get all child spans of a given span."""
        # TODO: Implement parent-child query
        raise NotImplementedError("Coming soon")
