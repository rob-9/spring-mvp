"""
Unified trace analysis engine.

Combines all waste detection algorithms + decision-level cost attribution
into a single analysis result per trace. This is what powers the dashboard.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from backend.core.models import Span, SpanStatus, DecisionCost
from backend.analysis.decision_path import calculate_trace_cost_tree, build_span_tree
from backend.analysis.waste_detection.retry_bloat import detect_retry_bloat
from backend.analysis.waste_detection.dead_end import detect_dead_end
from backend.analysis.waste_detection.loop_detection import detect_loops
from backend.analysis.waste_detection.cascade import (
    detect_cascade_failures,
    detect_error_clusters,
    analyze_retry_cascade,
)
from backend.analysis.waste_detection.context_waste import (
    detect_context_waste,
    detect_duplicate_prompts,
)


class AgentSummary(BaseModel):
    """Per-agent cost and performance summary within a trace."""
    agent_id: str
    agent_name: Optional[str] = None
    span_count: int = 0
    total_cost: float = 0.0
    error_count: int = 0
    avg_duration_ms: Optional[float] = None
    models_used: List[str] = Field(default_factory=list)
    total_tokens: int = 0


class WasteSummary(BaseModel):
    """Aggregated waste across all detection algorithms."""
    total_wasted_cost: float = 0.0
    waste_percentage: float = 0.0
    by_type: Dict[str, float] = Field(default_factory=dict)
    detections: List[Dict[str, Any]] = Field(default_factory=list)


class TraceAnalysis(BaseModel):
    """Complete analysis result for a single trace."""
    trace_id: str
    span_count: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0
    duration_ms: Optional[float] = None
    status: str = "unknown"

    # Decision cost tree (core differentiator)
    decision_trees: List[DecisionCost] = Field(default_factory=list)

    # Waste analysis
    waste: WasteSummary = Field(default_factory=WasteSummary)

    # Agent breakdown
    agents: List[AgentSummary] = Field(default_factory=list)

    # Raw detections by category
    retry_bloat: List[Dict[str, Any]] = Field(default_factory=list)
    loops: List[Dict[str, Any]] = Field(default_factory=list)
    dead_ends: List[Dict[str, Any]] = Field(default_factory=list)
    cascades: List[Dict[str, Any]] = Field(default_factory=list)
    context_waste: List[Dict[str, Any]] = Field(default_factory=list)


def analyze_trace(spans: List[Span]) -> TraceAnalysis:
    """
    Run full analysis on a trace's spans.

    Combines:
    - Decision-level cost attribution (recursive tree)
    - Retry bloat detection
    - Loop detection (structural + behavioral)
    - Dead-end detection
    - Cascade failure detection
    - Context waste detection
    - Per-agent breakdown

    Args:
        spans: All spans belonging to a single trace

    Returns:
        Complete TraceAnalysis with cost trees, waste summary, and agent breakdown
    """
    if not spans:
        return TraceAnalysis(trace_id="unknown")

    trace_id = spans[0].trace_id

    # Basic metrics
    total_cost = sum(s.cost_usd or 0.0 for s in spans)
    total_tokens = sum(s.tokens_total or 0 for s in spans)
    status = _determine_trace_status(spans)
    duration_ms = _calculate_trace_duration(spans)

    # Decision cost trees
    decision_trees = calculate_trace_cost_tree(spans)

    # Run all waste detectors
    all_waste: List[Dict[str, Any]] = []

    # 1. Retry bloat (per parent group)
    retry_results = _detect_all_retry_bloat(spans)
    all_waste.extend(retry_results)

    # 2. Loops
    loop_results = detect_loops(spans)
    all_waste.extend(loop_results)

    # 3. Dead ends
    dead_end_results = _detect_all_dead_ends(spans)
    all_waste.extend(dead_end_results)

    # 4. Cascades
    cascade_results = detect_cascade_failures(spans)
    error_clusters = detect_error_clusters(spans)
    retry_cascades = analyze_retry_cascade(spans)
    all_waste.extend(cascade_results)
    all_waste.extend(error_clusters)
    all_waste.extend(retry_cascades)

    # 5. Context waste
    context_results = detect_context_waste(spans)
    duplicate_prompts = detect_duplicate_prompts(spans)
    all_waste.extend(context_results)
    all_waste.extend(duplicate_prompts)

    # Aggregate waste
    waste_summary = _build_waste_summary(all_waste, total_cost)

    # Agent breakdown
    agents = _build_agent_summaries(spans)

    return TraceAnalysis(
        trace_id=trace_id,
        span_count=len(spans),
        total_cost=total_cost,
        total_tokens=total_tokens,
        duration_ms=duration_ms,
        status=status,
        decision_trees=decision_trees,
        waste=waste_summary,
        agents=agents,
        retry_bloat=retry_results,
        loops=loop_results,
        dead_ends=dead_end_results,
        cascades=cascade_results + error_clusters + retry_cascades,
        context_waste=context_results + duplicate_prompts,
    )


def _determine_trace_status(spans: List[Span]) -> str:
    """Determine overall trace status from span statuses."""
    statuses = {s.status for s in spans}
    if SpanStatus.ERROR in statuses:
        return "error"
    if SpanStatus.RUNNING in statuses:
        return "running"
    return "success"


def _calculate_trace_duration(spans: List[Span]) -> Optional[float]:
    """Calculate trace duration from earliest start to latest end."""
    starts = [s.start_time for s in spans]
    ends = [s.end_time for s in spans if s.end_time]

    if not starts or not ends:
        return None

    earliest = min(starts)
    latest = max(ends)
    return (latest - earliest).total_seconds() * 1000


def _detect_all_retry_bloat(spans: List[Span]) -> List[Dict[str, Any]]:
    """Run retry bloat detection across all parent groups."""
    # Group children by parent
    parent_groups: Dict[str, List[Span]] = {}
    for span in spans:
        parent_id = span.parent_span_id or "__root__"
        if parent_id not in parent_groups:
            parent_groups[parent_id] = []
        parent_groups[parent_id].append(span)

    results: List[Dict[str, Any]] = []
    for children in parent_groups.values():
        if len(children) > 1:
            try:
                results.extend(detect_retry_bloat(children))
            except ValueError:
                pass

    return results


def _detect_all_dead_ends(spans: List[Span]) -> List[Dict[str, Any]]:
    """Run dead-end detection on all spans."""
    span_db = {s.span_id: s for s in spans}
    tree = build_span_tree(spans)
    results: List[Dict[str, Any]] = []

    for span in spans:
        child_ids = tree.get(span.span_id, [])
        children = [span_db[cid] for cid in child_ids if cid in span_db]
        results.extend(detect_dead_end(span, children))

    return results


def _build_waste_summary(
    all_waste: List[Dict[str, Any]], total_cost: float
) -> WasteSummary:
    """Aggregate waste detections into a summary."""
    # Deduplicate by tracking span IDs already counted
    counted_span_ids = set()
    total_wasted = 0.0
    by_type: Dict[str, float] = {}

    for detection in all_waste:
        waste_type = detection.get("type", "unknown")
        wasted_cost = detection.get("wasted_cost", 0.0)

        # Avoid double-counting spans across detection types
        span_ids = set(detection.get("span_ids", []))
        if detection.get("span_id"):
            span_ids.add(detection["span_id"])

        new_spans = span_ids - counted_span_ids
        if not new_spans and span_ids:
            continue

        counted_span_ids.update(span_ids)
        total_wasted += wasted_cost
        by_type[waste_type] = by_type.get(waste_type, 0.0) + wasted_cost

    waste_pct = (total_wasted / total_cost * 100) if total_cost > 0 else 0.0

    return WasteSummary(
        total_wasted_cost=total_wasted,
        waste_percentage=round(waste_pct, 2),
        by_type=by_type,
        detections=all_waste,
    )


def _build_agent_summaries(spans: List[Span]) -> List[AgentSummary]:
    """Build per-agent summaries from trace spans."""
    agent_spans: Dict[str, List[Span]] = {}

    for span in spans:
        agent_id = span.agent_id or "__unattributed__"
        if agent_id not in agent_spans:
            agent_spans[agent_id] = []
        agent_spans[agent_id].append(span)

    summaries = []
    for agent_id, a_spans in agent_spans.items():
        if agent_id == "__unattributed__":
            continue

        durations = [s.duration_ms for s in a_spans if s.duration_ms is not None]
        models = list({s.model for s in a_spans if s.model})

        summaries.append(AgentSummary(
            agent_id=agent_id,
            agent_name=next((s.agent_name for s in a_spans if s.agent_name), None),
            span_count=len(a_spans),
            total_cost=sum(s.cost_usd or 0.0 for s in a_spans),
            error_count=sum(1 for s in a_spans if s.status == SpanStatus.ERROR),
            avg_duration_ms=sum(durations) / len(durations) if durations else None,
            models_used=models,
            total_tokens=sum(s.tokens_total or 0 for s in a_spans),
        ))

    summaries.sort(key=lambda a: a.total_cost, reverse=True)
    return summaries
