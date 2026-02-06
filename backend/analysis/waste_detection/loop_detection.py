"""
Loop detection algorithms for agent execution graphs.

Detects two types of loops:
1. Structural loops: Cycles via span links (non-hierarchical DAG relationships)
2. Behavioral loops: Repeated execution patterns in sequence

OpenTelemetry Background:
- Traces are DAGs (Directed Acyclic Graphs) via parent-child relationships
- Cycles are represented using SpanLinks (non-hierarchical connections)
- Each loop iteration creates a new span with links to previous iterations
"""

from typing import List, Dict, Tuple, Set
from typing_extensions import TypedDict
from collections import defaultdict
from backend.core.models import Span
import logging

logger = logging.getLogger(__name__)


class LoopOccurrence(TypedDict):
    """Single occurrence of a repeated pattern."""
    start_idx: int
    span_ids: List[str]
    cost: float


class StructuralLoopDetection(TypedDict):
    """Detection result for structural loops (via span links)."""
    type: str  # Always "loop"
    loop_type: str  # Always "structural"
    cycle_path: List[str]
    span_ids: List[str]
    cycle_length: int
    wasted_cost: float
    details: str


class BehavioralLoopDetection(TypedDict):
    """Detection result for behavioral loops (repeated patterns)."""
    type: str  # Always "loop"
    loop_type: str  # Always "behavioral"
    pattern: List[str]
    repetitions: int
    wasted_cost: float
    total_cost: float
    occurrences: List[LoopOccurrence]
    details: str


LoopDetection = StructuralLoopDetection | BehavioralLoopDetection


def detect_loops(
    spans: List[Span],
    window_size: int = 6,
    min_pattern_length: int = 2,
    max_spans: int = 5000
) -> List[LoopDetection]:
    """
    Detect both structural and behavioral loops in agent execution.

    Combines:
    - Structural loop detection (cycles via span links)
    - Behavioral loop detection (repeated patterns via sliding window)

    Args:
        spans: List of all spans in the trace (in execution order)
        window_size: Maximum pattern length to detect (default: 6)
        min_pattern_length: Minimum pattern length (default: 2, avoid single-op noise)
        max_spans: Performance limit - max spans to analyze (default: 5000)

    Returns:
        List of detected loop patterns, sorted by wasted cost descending

    Example:
        >>> spans = [...]  # Agent A links to B which links back to A
        >>> loops = detect_loops(spans)
        >>> loops[0]["type"]
        'loop'
        >>> loops[0]["loop_type"]
        'structural'
    """
    if len(spans) > max_spans:
        logger.warning(
            f"Trace has {len(spans)} spans, limiting analysis to first {max_spans}"
        )
        spans = spans[:max_spans]

    results: List[LoopDetection] = []

    # Detect structural loops (cycles via span links)
    structural = detect_structural_loops(spans)
    results.extend(structural)

    # Detect behavioral loops (repeated patterns)
    behavioral = detect_behavioral_loops(
        spans,
        window_size=window_size,
        min_pattern_length=min_pattern_length
    )
    results.extend(behavioral)

    # Sort by wasted cost descending
    results.sort(key=lambda x: x["wasted_cost"], reverse=True)

    return results


def detect_structural_loops(spans: List[Span]) -> List[StructuralLoopDetection]:
    """
    Detect cycles via span links (non-hierarchical DAG relationships).

    In OpenTelemetry, cycles are represented using SpanLinks rather than
    parent-child relationships. This detects when span links create cycles,
    such as:
    - Loop iterations linking back to the loop start
    - Recursive agent calls linking to earlier invocations
    - Retry chains linking back to original attempts

    Algorithm:
    1. Build directed graph from span links
    2. Run DFS with recursion stack tracking
    3. Back edge to node in recursion stack = cycle detected
    4. Extract cycle path and calculate wasted cost

    Args:
        spans: List of all spans in trace

    Returns:
        List of structural loop detections with cycle paths and costs

    Note:
        Only detects cycles via span.links, not parent-child relationships
        (which form a DAG by definition).
    """
    if not spans:
        return []

    # Build adjacency list from span links: span_id -> [linked_span_ids]
    link_graph: Dict[str, List[str]] = defaultdict(list)
    span_map: Dict[str, Span] = {s.span_id: s for s in spans}

    for span in spans:
        for link in span.links:
            # Only consider links within the same trace
            if link.trace_id == span.trace_id and link.span_id in span_map:
                link_graph[span.span_id].append(link.span_id)

    # If no links exist, no cycles possible
    if not link_graph:
        return []

    # DFS to find cycles
    visited: Set[str] = set()
    rec_stack: Set[str] = set()
    cycles_found: List[List[str]] = []

    def dfs(node_id: str, path: List[str]) -> None:
        """DFS with cycle detection via recursion stack."""
        visited.add(node_id)
        rec_stack.add(node_id)
        path.append(node_id)

        for linked_id in link_graph.get(node_id, []):
            if linked_id not in visited:
                dfs(linked_id, path[:])
            elif linked_id in rec_stack:
                # Back edge found - extract cycle
                try:
                    cycle_start_idx = path.index(linked_id)
                    cycle = path[cycle_start_idx:] + [linked_id]
                    cycles_found.append(cycle)
                except ValueError:
                    # Should not happen, but defensive programming
                    pass

        rec_stack.remove(node_id)

    # Run DFS from all nodes that have links
    for node_id in link_graph.keys():
        if node_id not in visited:
            dfs(node_id, [])

    # Build waste detection results for each cycle
    results: List[StructuralLoopDetection] = []
    for cycle in cycles_found:
        # Remove duplicate end node
        cycle_spans = [span_map[sid] for sid in cycle[:-1] if sid in span_map]
        total_cost = sum(s.cost_usd or 0.0 for s in cycle_spans)

        # Only report cycles with actual cost
        if total_cost > 0:
            results.append({
                "type": "loop",
                "loop_type": "structural",
                "cycle_path": [span_map[sid].name for sid in cycle if sid in span_map],
                "span_ids": cycle[:-1],
                "cycle_length": len(cycle) - 1,
                "wasted_cost": total_cost,
                "details": (
                    f"Circular dependency detected via span links: "
                    f"{' → '.join([span_map[sid].name for sid in cycle if sid in span_map])}"
                )
            })

    return results


def detect_behavioral_loops(
    spans: List[Span],
    window_size: int = 6,
    min_pattern_length: int = 2
) -> List[BehavioralLoopDetection]:
    """
    Detect repeated execution patterns using sliding window.

    Identifies when the same sequence of operations repeats, even without
    structural cycles. Example: A → B → C → A → B → C (pattern repeats).

    Algorithm:
    1. Create sliding windows over sequential spans
    2. Hash each window by operation names
    3. Find repeated patterns (same hash appears multiple times)
    4. Deduplicate overlapping patterns (keep longest non-overlapping)
    5. Calculate cost of redundant repetitions

    Args:
        spans: List of spans in execution order
        window_size: Max size of sliding window for pattern matching (default: 6)
        min_pattern_length: Min pattern length to avoid noise (default: 2)

    Returns:
        List of behavioral loop detections with patterns and costs

    Note:
        - Deduplicates overlapping patterns to avoid double-counting
        - Window size should be 3-10 to capture meaningful patterns
        - Min pattern length filters out single-operation repetitions
    """
    if len(spans) < min_pattern_length:
        return []

    # Sort spans by start_time to ensure sequential order
    sorted_spans = sorted(spans, key=lambda s: s.start_time)

    # Sliding window to find repeated patterns
    patterns: Dict[Tuple[str, ...], List[LoopOccurrence]] = defaultdict(list)

    for i in range(len(sorted_spans)):
        for window in range(min_pattern_length, min(window_size + 1, len(sorted_spans) - i + 1)):
            sequence = sorted_spans[i:i + window]
            pattern_key = tuple(s.name for s in sequence)

            # Store occurrence info
            occurrence: LoopOccurrence = {
                "start_idx": i,
                "span_ids": [s.span_id for s in sequence],
                "cost": sum(s.cost_usd or 0.0 for s in sequence)
            }
            patterns[pattern_key].append(occurrence)

    # Find patterns that repeat (appear 2+ times)
    raw_results: List[BehavioralLoopDetection] = []

    for pattern_key, occurrences in patterns.items():
        if len(occurrences) >= 2:
            # Calculate wasted cost (all repetitions except first)
            first_cost: float = occurrences[0]["cost"]
            total_cost: float = sum(occ["cost"] for occ in occurrences)
            wasted_cost: float = total_cost - first_cost

            if wasted_cost > 0:
                raw_results.append({
                    "type": "loop",
                    "loop_type": "behavioral",
                    "pattern": list(pattern_key),
                    "repetitions": len(occurrences),
                    "wasted_cost": wasted_cost,
                    "total_cost": total_cost,
                    "occurrences": occurrences,
                    "details": (
                        f"Repeated pattern detected {len(occurrences)}x: "
                        f"{' → '.join(pattern_key)} "
                        f"(wasted ${wasted_cost:.4f})"
                    )
                })

    # Deduplicate overlapping patterns (keep longest non-overlapping ones)
    deduplicated = _deduplicate_patterns(raw_results)

    return deduplicated


def _deduplicate_patterns(results: List[BehavioralLoopDetection]) -> List[BehavioralLoopDetection]:
    """
    Remove overlapping pattern detections to avoid double-counting costs.

    Strategy: Keep longest patterns that don't share span IDs. This prevents
    reporting both "A → B → C" and its sub-patterns "A → B" and "B → C".

    Args:
        results: List of raw behavioral loop detections

    Returns:
        Deduplicated list with non-overlapping patterns

    Example:
        Input: ["A → B → C" (2x), "A → B" (2x), "B → C" (2x)]
        Output: ["A → B → C" (2x)]  # Longest pattern, excludes sub-patterns
    """
    if not results:
        return []

    # Sort by pattern length descending, then by wasted cost descending
    sorted_results = sorted(
        results,
        key=lambda x: (len(x["pattern"]), x["wasted_cost"]),
        reverse=True
    )

    kept: List[BehavioralLoopDetection] = []
    used_span_ids: Set[str] = set()

    for result in sorted_results:
        # Collect all span IDs from all occurrences
        all_span_ids: Set[str] = set()
        for occ in result["occurrences"]:
            all_span_ids.update(occ["span_ids"])

        # If this pattern's spans don't overlap with kept patterns, keep it
        if not any(sid in used_span_ids for sid in all_span_ids):
            kept.append(result)
            used_span_ids.update(all_span_ids)

    return kept