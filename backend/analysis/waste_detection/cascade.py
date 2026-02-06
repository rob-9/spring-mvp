"""
cascade failure detection for identifying waste from error propagation.

detects when one failure triggers downstream failures, causing cascading waste.
simplified version for waste detection module (week 1-4).
full cascade analysis with binary search in module 3 (week 9-12).

example:
- planner agent fails validation ($0.05)
- triggers retry in researcher agent ($0.15)
- triggers retry in executor agent ($0.20)
- triggers retry in validator agent ($0.10)
- total cascade cost: $0.50, root cause: $0.05 validation failure
"""

from typing import List, Dict, Any, Set, Optional
from collections import defaultdict
from backend.core.models import Span, SpanStatus


def detect_cascade_failures(spans: List[Span]) -> List[Dict[str, Any]]:
    """
    detect cascade failures where one error triggers downstream failures.

    algorithm:
    1. build parent-child tree
    2. find error spans
    3. traverse descendants to find propagated failures
    4. calculate blast radius (count and cost of affected descendants)
    5. rank by total cascaded cost

    args:
        spans: list of all spans in trace

    returns:
        list of cascade detections sorted by cascaded cost descending

    note:
        requires spans to have status field. uses parent-child relationships.
        future: binary search for root cause (module 3).
    """
    if not spans:
        return []

    # build span map and parent-child relationships
    span_map: Dict[str, Span] = {s.span_id: s for s in spans}
    children_map: Dict[str, List[str]] = defaultdict(list)

    for span in spans:
        if span.parent_span_id:
            children_map[span.parent_span_id].append(span.span_id)

    # find all error spans
    error_spans = [s for s in spans if s.status == SpanStatus.ERROR]

    if not error_spans:
        return []

    results: List[Dict[str, Any]] = []

    # analyze each error for downstream impact
    for error_span in error_spans:
        # get all descendants
        descendants = _get_all_descendants(error_span.span_id, children_map, span_map)

        if not descendants:
            continue

        # calculate cascade impact
        descendant_spans = [span_map[sid] for sid in descendants]
        failed_descendants = [s for s in descendant_spans if s.status == SpanStatus.ERROR]

        # calculate costs
        direct_cost = error_span.cost_usd or 0.0
        cascade_cost = sum(s.cost_usd or 0.0 for s in descendant_spans)
        total_cost = direct_cost + cascade_cost

        # only report if significant cascade impact
        if cascade_cost > 0 and len(failed_descendants) > 0:
            results.append({
                "type": "cascade_failure",
                "root_span_id": error_span.span_id,
                "root_span_name": error_span.name,
                "root_cost": direct_cost,
                "cascade_cost": cascade_cost,
                "total_cost": total_cost,
                "wasted_cost": cascade_cost,  # All downstream work after failure is wasted
                "affected_span_ids": descendants,
                "blast_radius": len(descendants),
                "failed_descendants": len(failed_descendants),
                "details": (
                    f"Failure in '{error_span.name}' (${direct_cost:.4f}) triggered "
                    f"{len(descendants)} downstream operations (${cascade_cost:.4f}). "
                    f"{len(failed_descendants)} propagated failures detected."
                ),
                "recommendation": f"Fix root cause in '{error_span.name}' to prevent cascade"
            })

    # sort by total cascaded cost descending
    results.sort(key=lambda x: x["cascade_cost"], reverse=True)

    return results


def detect_error_clusters(spans: List[Span], time_window_seconds: float = 60) -> List[Dict[str, Any]]:
    """
    detect clusters of errors occurring close together in time.

    useful for identifying systemic issues causing multiple simultaneous failures.

    args:
        spans: list of all spans in trace
        time_window_seconds: time window for clustering (default: 60s)

    returns:
        list of error cluster detections
    """
    if not spans:
        return []

    # get all error spans sorted by time
    error_spans = sorted(
        [s for s in spans if s.status == SpanStatus.ERROR],
        key=lambda s: s.start_time
    )

    if len(error_spans) < 2:
        return []

    results: List[Dict[str, Any]] = []
    visited: Set[str] = set()

    for i, error_span in enumerate(error_spans):
        if error_span.span_id in visited:
            continue

        # find errors within time window
        cluster = [error_span]
        visited.add(error_span.span_id)

        for other_span in error_spans[i + 1:]:
            if other_span.span_id in visited:
                continue

            time_diff = (other_span.start_time - error_span.start_time).total_seconds()
            if time_diff <= time_window_seconds:
                cluster.append(other_span)
                visited.add(other_span.span_id)
            else:
                break  # spans sorted, no need to check further

        # report cluster if significant
        if len(cluster) >= 2:
            total_cost = sum(s.cost_usd or 0.0 for s in cluster)

            results.append({
                "type": "error_cluster",
                "cluster_size": len(cluster),
                "span_ids": [s.span_id for s in cluster],
                "total_cost": total_cost,
                "wasted_cost": total_cost,
                "time_window_seconds": time_window_seconds,
                "error_types": list(set(s.name for s in cluster)),
                "details": (
                    f"{len(cluster)} errors occurred within {time_window_seconds}s "
                    f"(${total_cost:.4f} total). Possible systemic issue."
                ),
                "recommendation": "Investigate common cause of clustered failures"
            })

    # sort by cluster size descending
    results.sort(key=lambda x: x["cluster_size"], reverse=True)

    return results


def analyze_retry_cascade(spans: List[Span]) -> List[Dict[str, Any]]:
    """
    detect when retries trigger more retries (retry cascade).

    example: api call fails → agent retries → triggers validation →
             validation fails → triggers more retries

    args:
        spans: list of all spans in trace

    returns:
        list of retry cascade detections
    """
    if not spans:
        return []

    # build parent-child relationships
    span_map: Dict[str, Span] = {s.span_id: s for s in spans}
    children_map: Dict[str, List[str]] = defaultdict(list)

    for span in spans:
        if span.parent_span_id:
            children_map[span.parent_span_id].append(span.span_id)

    results: List[Dict[str, Any]] = []

    # find spans with attempt_number > 1 (retries)
    retry_spans = [s for s in spans if s.attempt_number > 1]

    for retry_span in retry_spans:
        # check if this retry triggered more retries in descendants
        descendants = _get_all_descendants(retry_span.span_id, children_map, span_map)
        descendant_retries = [
            span_map[sid] for sid in descendants
            if span_map[sid].attempt_number > 1
        ]

        if descendant_retries:
            # calculate cascade cost
            retry_cost = retry_span.cost_usd or 0.0
            cascade_retry_cost = sum(s.cost_usd or 0.0 for s in descendant_retries)
            total_cost = retry_cost + cascade_retry_cost

            results.append({
                "type": "retry_cascade",
                "root_span_id": retry_span.span_id,
                "root_span_name": retry_span.name,
                "root_attempt": retry_span.attempt_number,
                "triggered_retries": len(descendant_retries),
                "cascade_cost": cascade_retry_cost,
                "total_cost": total_cost,
                "wasted_cost": cascade_retry_cost,
                "details": (
                    f"Retry #{retry_span.attempt_number} in '{retry_span.name}' "
                    f"triggered {len(descendant_retries)} downstream retries "
                    f"(${cascade_retry_cost:.4f} cascaded cost)"
                ),
                "recommendation": "Fix root issue to prevent retry cascades"
            })

    # sort by cascade cost descending
    results.sort(key=lambda x: x["cascade_cost"], reverse=True)

    return results


def _get_all_descendants(
    span_id: str,
    children_map: Dict[str, List[str]],
    span_map: Dict[str, Span]
) -> List[str]:
    """
    recursively get all descendants of a span.

    args:
        span_id: starting span id
        children_map: map of parent_id -> [child_ids]
        span_map: map of span_id -> span

    returns:
        list of all descendant span ids
    """
    descendants: List[str] = []
    to_visit = children_map.get(span_id, []).copy()

    while to_visit:
        child_id = to_visit.pop()
        if child_id not in span_map:
            continue

        descendants.append(child_id)
        # add children of this child
        to_visit.extend(children_map.get(child_id, []))

    return descendants
