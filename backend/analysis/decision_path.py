"""
Decision-level cost attribution algorithm.

Core differentiator: Recursively aggregate costs across entire agent
decision tree, not just individual API calls.
"""

from typing import Dict, Any, List
from backend.core.models import DecisionCost, Span


def calculate_decision_path_cost(
    span_id: str,
    span_db: Dict[str, Span]
) -> DecisionCost:
    """
    Recursively calculate total cost of a decision and all downstream work.

    Algorithm:
    1. Start at decision span
    2. Calculate direct cost (this span alone)
    3. Find all child spans (downstream work triggered by this decision)
    4. Recursively calculate cost for each child
    5. Sum: total_cost = direct_cost + sum(child_costs)
    6. Detect waste patterns
    7. Return aggregated result

    Args:
        span_id: The span ID to analyze
        span_db: Dictionary mapping span_id -> Span

    Returns:
        DecisionCost with recursive aggregation

    Example:
        >>> span_db = {...}  # Load from database
        >>> cost = calculate_decision_path_cost("span_001", span_db)
        >>> print(f"Total cost: ${cost.total_cost}")
        Total cost: $0.23 ($0.05 direct + $0.18 downstream)
    """
    # TODO: Implement recursive cost aggregation
    # See mvp-summary.md lines 461-589 for algorithm
    raise NotImplementedError("Coming soon")


def build_span_tree(spans: List[Span]) -> Dict[str, List[str]]:
    """
    Build parent->children mapping from flat span list.

    Returns:
        Dictionary mapping span_id -> list of child span_ids
    """
    # TODO: Implement tree building
    raise NotImplementedError("Coming soon")
