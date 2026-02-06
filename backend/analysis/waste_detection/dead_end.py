"""
Dead-end detection algorithm.

Identifies spans that cost money but ended in failure, indicating wasted work
that produced no value.
"""

from typing import List, Dict, Any
from backend.core.models import Span, SpanStatus


def detect_dead_end(span: Span, children: List[Span]) -> List[Dict[str, Any]]:
    """
    Detect when a span and its children cost money but ended in failure.

    A dead-end occurs when:
    1. The span has error status OR decision_made indicates failure
    2. The span and/or its children incurred cost
    3. No successful outcome was produced

    Args:
        span: The parent span to check
        children: List of child spans under this parent

    Returns:
        List with single waste detection result if dead-end detected, empty list otherwise.
        Result contains:
        - type: "dead_end"
        - span_id: ID of the failed span
        - wasted_cost: Total cost of span + children
        - details: Human-readable description
        - child_count: Number of children affected

    Example:
        >>> from backend.core.models import Span, SpanStatus
        >>> from datetime import datetime
        >>> span = Span(
        ...     span_id="1", trace_id="t1", name="validate",
        ...     cost_usd=0.05, start_time=datetime.now(),
        ...     status=SpanStatus.ERROR
        ... )
        >>> result = detect_dead_end(span, [])
        >>> result[0]["type"]
        'dead_end'
        >>> result[0]["wasted_cost"]
        0.05
    """
    # check if span indicates failure
    is_failed = (
        span.status == SpanStatus.ERROR or
        (span.decision_made and "fail" in span.decision_made.lower())
    )

    #  no dead-end waste
    if not is_failed:
        return []

    # calc total cost (span + all children)
    span_cost = span.cost_usd or 0.0
    children_cost = sum(child.cost_usd or 0.0 for child in children)
    total_cost = span_cost + children_cost

    # no waste
    if total_cost == 0.0:
        return []

    # dead end detected, return
    return [{
        "type": "dead_end",
        "span_id": span.span_id,
        "operation_name": span.name,
        "wasted_cost": total_cost,
        "direct_cost": span_cost,
        "child_cost": children_cost,
        "child_count": len(children),
        "status": span.status.value,
        "decision_made": span.decision_made,
        "details": (
            f"Operation '{span.name}' failed after spending ${total_cost:.4f} "
            f"({len(children)} child operation{'s' if len(children) != 1 else ''})"
        )
    }]
