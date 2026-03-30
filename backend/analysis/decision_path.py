"""
Decision-level cost attribution algorithm.

Core differentiator: Recursively aggregate costs across entire agent
decision tree, not just individual API calls.

Example:
    Agent decides to "research topic" ($0.05 direct)
      → spawns 3 LLM calls ($0.10 each)
      → one triggers a retry loop ($0.15 wasted)

    Traditional tools show: 5 separate API calls totaling $0.50
    We show: "research topic" decision cost $0.50 ($0.05 direct + $0.30 children + $0.15 waste)
"""

from typing import Dict, List, Optional
from collections import defaultdict
from backend.core.models import DecisionCost, Span, SpanStatus
from backend.analysis.waste_detection.retry_bloat import detect_retry_bloat
from backend.analysis.waste_detection.dead_end import detect_dead_end
from backend.analysis.waste_detection.loop_detection import detect_loops


def build_span_tree(spans: List[Span]) -> Dict[str, List[str]]:
    """
    Build parent->children mapping from flat span list.

    Args:
        spans: Flat list of spans (e.g. from a trace)

    Returns:
        Dictionary mapping span_id -> list of child span_ids
    """
    tree: Dict[str, List[str]] = defaultdict(list)
    for span in spans:
        if span.parent_span_id:
            tree[span.parent_span_id].append(span.span_id)
    return dict(tree)


def calculate_decision_path_cost(
    span_id: str,
    span_db: Dict[str, Span],
    tree: Optional[Dict[str, List[str]]] = None,
    _depth: int = 0,
    _max_depth: int = 50,
) -> DecisionCost:
    """
    Recursively calculate total cost of a decision and all downstream work.

    Algorithm:
    1. Start at decision span
    2. Calculate direct cost (this span alone)
    3. Find all child spans (downstream work triggered by this decision)
    4. Recursively calculate cost for each child
    5. Sum: total_cost = direct_cost + sum(child_costs)
    6. Detect waste patterns among children
    7. Return aggregated result

    Args:
        span_id: The span ID to analyze
        span_db: Dictionary mapping span_id -> Span
        tree: Pre-built parent->children mapping (built if not provided)
        _depth: Current recursion depth (internal)
        _max_depth: Maximum recursion depth to prevent infinite loops

    Returns:
        DecisionCost with recursive aggregation
    """
    if _depth > _max_depth:
        span = span_db.get(span_id)
        return DecisionCost(
            decision_span_id=span_id,
            decision_name=span.name if span else "unknown",
            agent_id=span.agent_id if span else None,
            direct_cost=span.cost_usd or 0.0 if span else 0.0,
            child_cost=0.0,
            total_cost=span.cost_usd or 0.0 if span else 0.0,
            status=span.status if span else SpanStatus.ERROR,
            metadata={"truncated": True, "reason": "max_depth_exceeded"},
        )

    # Build tree if not provided
    if tree is None:
        tree = build_span_tree(list(span_db.values()))

    span = span_db.get(span_id)
    if span is None:
        return DecisionCost(
            decision_span_id=span_id,
            decision_name="unknown",
            direct_cost=0.0,
            child_cost=0.0,
            total_cost=0.0,
            status=SpanStatus.ERROR,
            metadata={"error": "span_not_found"},
        )

    direct_cost = span.cost_usd or 0.0

    # Get child span IDs
    child_ids = tree.get(span_id, [])

    # Recursively calculate cost for each child
    child_breakdowns: List[DecisionCost] = []
    for child_id in child_ids:
        child_cost_result = calculate_decision_path_cost(
            child_id, span_db, tree, _depth=_depth + 1, _max_depth=_max_depth
        )
        child_breakdowns.append(child_cost_result)

    child_cost = sum(cb.total_cost for cb in child_breakdowns)
    total_cost = direct_cost + child_cost

    # Run waste detection on children
    waste_detected = _detect_waste_for_children(span, child_ids, span_db)

    # Calculate cascade impact
    cascade_impact = _calculate_cascade_impact(span, child_breakdowns)

    return DecisionCost(
        decision_span_id=span_id,
        decision_name=span.name,
        agent_id=span.agent_id,
        direct_cost=direct_cost,
        child_cost=child_cost,
        total_cost=total_cost,
        status=span.status,
        child_breakdown=child_breakdowns,
        waste_detected=waste_detected,
        cascade_impact=cascade_impact,
    )


def calculate_trace_cost_tree(spans: List[Span]) -> List[DecisionCost]:
    """
    Calculate the full decision cost tree for a trace.

    Finds root spans and builds the complete cost tree from each root.

    Args:
        spans: All spans in a trace

    Returns:
        List of DecisionCost trees (one per root span)
    """
    if not spans:
        return []

    span_db = {s.span_id: s for s in spans}
    tree = build_span_tree(spans)

    # Find root spans (no parent or parent not in this trace)
    root_ids = [
        s.span_id for s in spans
        if s.parent_span_id is None or s.parent_span_id not in span_db
    ]

    return [
        calculate_decision_path_cost(root_id, span_db, tree)
        for root_id in root_ids
    ]


def _detect_waste_for_children(
    parent: Span,
    child_ids: List[str],
    span_db: Dict[str, Span],
) -> List[Dict]:
    """
    Run waste detection algorithms on a span's children.

    Detects retry bloat, dead-ends, and loops among siblings.
    """
    children = [span_db[cid] for cid in child_ids if cid in span_db]
    if not children:
        return []

    waste: List[Dict] = []

    # Retry bloat detection (siblings with same name)
    try:
        waste.extend(detect_retry_bloat(children))
    except ValueError:
        # Children may not share same parent in edge cases
        pass

    # Dead-end detection on each child
    for child in children:
        grandchild_ids = [
            s.span_id for s in span_db.values()
            if s.parent_span_id == child.span_id
        ]
        grandchildren = [span_db[gid] for gid in grandchild_ids if gid in span_db]
        waste.extend(detect_dead_end(child, grandchildren))

    return waste


def _calculate_cascade_impact(
    span: Span,
    child_breakdowns: List[DecisionCost],
) -> Optional[Dict]:
    """
    Calculate cascade impact if this span failed.

    Returns summary of how failure propagated to children.
    """
    if span.status != SpanStatus.ERROR:
        return None

    failed_children = [cb for cb in child_breakdowns if cb.status == SpanStatus.ERROR]
    if not failed_children:
        return None

    return {
        "failed_children": len(failed_children),
        "total_children": len(child_breakdowns),
        "cascade_cost": sum(cb.total_cost for cb in failed_children),
        "affected_agents": list({
            cb.agent_id for cb in failed_children if cb.agent_id
        }),
    }
