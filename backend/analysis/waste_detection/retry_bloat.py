"""
Retry bloat detection algorithm.

Identifies when the same operation is retried multiple times as sibling spans,
indicating potential stuck logic or unnecessary retry loops.
"""

from typing import List, Dict, Any
from collections import defaultdict
from backend.core.models import Span


def detect_retry_bloat(children: List[Span]) -> List[Dict[str, Any]]:
    """
    Detect retry bloat patterns among sibling spans.

    Algorithm:
    1. Group spans by name (operation name)
    2. Identify operations called multiple times (count > 1)
    3. For each retried operation:
       - Calculate wasted cost (all attempts except first)
       - Determine severity based on retry count
       - Build detailed result dictionary

    Args:
        children: List of child spans (siblings under same parent)

    Returns:
        List of waste detection results. Each result contains:
        - type: "retry_bloat"
        - operation_name: Name of the retried operation
        - retry_count: Number of retry attempts (total calls - 1)
        - wasted_cost: Cost of retry attempts (excluding first)
        - total_cost: Total cost of all attempts
        - details: Human-readable description
        - span_ids: List of all span IDs involved in the retries

    Example:
        >>> from backend.core.models import Span, SpanStatus
        >>> from datetime import datetime
        >>> spans = [
        ...     Span(span_id="1", trace_id="t1", name="check_db", cost_usd=0.05,
        ...          start_time=datetime.now(), status=SpanStatus.SUCCESS),
        ...     Span(span_id="2", trace_id="t1", name="check_db", cost_usd=0.05,
        ...          start_time=datetime.now(), status=SpanStatus.SUCCESS),
        ... ]
        >>> result = detect_retry_bloat(spans)
        >>> result[0]["retry_count"]
        1
        >>> result[0]["wasted_cost"]
        0.05
    """
    # ec: empty or single child
    if len(children) <= 1:
        return []

    # verify all children share same parent (sibling validation)
    parent_ids = {s.parent_span_id for s in children}
    if len(parent_ids) > 1:
        raise ValueError(
            f"All children must share same parent_span_id. Found {len(parent_ids)} different parents."
        )

    # group spans by operation name
    grouped = _group_spans_by_name(children)

    # find retry patterns
    waste_results = []
    for operation_name, spans in grouped.items():
        if len(spans) > 1:
            # calculate metrics for this retry pattern
            metrics = _calculate_retry_metrics(spans)

            # build result dictionary
            waste_results.append({
                "type": "retry_bloat",
                "operation_name": operation_name,
                "retry_count": metrics["retry_count"],
                "wasted_cost": metrics["wasted_cost"],
                "total_cost": metrics["total_cost"],
                "details": (
                    f"Operation '{operation_name}' retried {metrics['retry_count']}x "
                    f"(wasted ${metrics['wasted_cost']:.4f})"
                ),
                "span_ids": metrics["span_ids"]
            })

    # sort by wasted cost DESC
    waste_results.sort(key=lambda x: x["wasted_cost"], reverse=True)

    return waste_results


def _group_spans_by_name(children: List[Span]) -> Dict[str, List[Span]]:
    """
    Helper to group spans by operation name.

    Args:
        children: List of spans to group

    Returns:
        Dictionary mapping span name to list of spans with that name
    """
    grouped = defaultdict(list)

    for span in children:
        grouped[span.name].append(span)
    return dict(grouped)


def _calculate_retry_metrics(spans: List[Span]) -> Dict[str, Any]:
    """
    Calculate retry metrics for a group of spans with same name.

    Args:
        spans: List of spans with same operation name

    Returns:
        Dictionary with:
        - retry_count: Number of retries (total - 1)
        - wasted_cost: Cost of retry attempts (total - first)
        - total_cost: Total cost of all attempts
        - span_ids: List of all span IDs

    Note:
        - Sorts by attempt_number (primary) and start_time (fallback)
        - Treats None costs as 0.0
        - First attempt cost is not considered wasted
    """
    # sort by attempt_number (primary), start_time (fallback for safety)
    sorted_spans = sorted(spans, key=lambda s: (s.attempt_number, s.start_time))

    # calculate costs
    first_attempt_cost = sorted_spans[0].cost_usd or 0.0
    total_cost = sum(s.cost_usd or 0.0 for s in sorted_spans)
    wasted_cost = total_cost - first_attempt_cost

    # retry count = total attempts - 1
    retry_count = len(sorted_spans) - 1

    # collect span ids
    span_ids = [s.span_id for s in sorted_spans]

    return {
        "retry_count": retry_count,
        "wasted_cost": wasted_cost,
        "total_cost": total_cost,
        "span_ids": span_ids
    }
