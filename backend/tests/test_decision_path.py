"""
Tests for decision-level cost attribution algorithm.

Tests the core differentiator: recursive cost aggregation across
agent decision trees.
"""

import pytest
from datetime import datetime, timedelta
from backend.core.models import Span, SpanStatus, DecisionCost
from backend.analysis.decision_path import (
    build_span_tree,
    calculate_decision_path_cost,
    calculate_trace_cost_tree,
)


@pytest.fixture
def base_kwargs():
    return {
        "trace_id": "trace_001",
        "start_time": datetime(2025, 1, 15, 10, 0, 0),
        "status": SpanStatus.SUCCESS,
    }


def make_span(span_id, name, cost_usd=0.0, parent_span_id=None, **kwargs):
    defaults = {
        "trace_id": "trace_001",
        "start_time": datetime(2025, 1, 15, 10, 0, 0),
        "status": SpanStatus.SUCCESS,
    }
    defaults.update(kwargs)
    return Span(
        span_id=span_id,
        name=name,
        cost_usd=cost_usd,
        parent_span_id=parent_span_id,
        **defaults,
    )


class TestBuildSpanTree:
    def test_empty_list(self):
        assert build_span_tree([]) == {}

    def test_single_root_span(self):
        spans = [make_span("s1", "root")]
        tree = build_span_tree(spans)
        assert tree == {}

    def test_parent_child(self):
        spans = [
            make_span("s1", "root"),
            make_span("s2", "child", parent_span_id="s1"),
        ]
        tree = build_span_tree(spans)
        assert tree == {"s1": ["s2"]}

    def test_multiple_children(self):
        spans = [
            make_span("s1", "root"),
            make_span("s2", "child1", parent_span_id="s1"),
            make_span("s3", "child2", parent_span_id="s1"),
        ]
        tree = build_span_tree(spans)
        assert set(tree["s1"]) == {"s2", "s3"}

    def test_deep_tree(self):
        spans = [
            make_span("s1", "root"),
            make_span("s2", "child", parent_span_id="s1"),
            make_span("s3", "grandchild", parent_span_id="s2"),
        ]
        tree = build_span_tree(spans)
        assert tree == {"s1": ["s2"], "s2": ["s3"]}


class TestCalculateDecisionPathCost:
    def test_leaf_span_no_children(self):
        span = make_span("s1", "leaf", cost_usd=0.05)
        span_db = {"s1": span}
        result = calculate_decision_path_cost("s1", span_db)

        assert result.decision_span_id == "s1"
        assert result.direct_cost == 0.05
        assert result.child_cost == 0.0
        assert result.total_cost == 0.05
        assert result.child_breakdown == []

    def test_span_not_found(self):
        result = calculate_decision_path_cost("missing", {})
        assert result.decision_name == "unknown"
        assert result.total_cost == 0.0

    def test_parent_with_one_child(self):
        root = make_span("s1", "parent", cost_usd=0.05, parent_span_id=None)
        child = make_span("s2", "child", cost_usd=0.10, parent_span_id="s1")
        span_db = {root.span_id: root, child.span_id: child}
        result = calculate_decision_path_cost("s1", span_db)

        assert result.direct_cost == pytest.approx(0.05)
        assert result.child_cost == pytest.approx(0.10)
        assert result.total_cost == pytest.approx(0.15)
        assert len(result.child_breakdown) == 1
        assert result.child_breakdown[0].decision_name == "child"

    def test_deep_recursive_cost(self):
        """Root -> Child -> Grandchild: costs should aggregate up."""
        spans = [
            make_span("s1", "root", cost_usd=0.01, parent_span_id=None),
            make_span("s2", "child", cost_usd=0.02, parent_span_id="s1"),
            make_span("s3", "grandchild", cost_usd=0.03, parent_span_id="s2"),
        ]
        span_db = {s.span_id: s for s in spans}
        result = calculate_decision_path_cost("s1", span_db)

        assert result.direct_cost == pytest.approx(0.01)
        assert result.child_cost == pytest.approx(0.05)  # 0.02 + 0.03
        assert result.total_cost == pytest.approx(0.06)

        child = result.child_breakdown[0]
        assert child.direct_cost == 0.02
        assert child.child_cost == 0.03
        assert child.total_cost == 0.05

    def test_fan_out_multiple_children(self):
        """Root spawns 3 children in parallel."""
        spans = [
            make_span("s1", "orchestrator", cost_usd=0.05),
            make_span("s2", "researcher", cost_usd=0.10, parent_span_id="s1"),
            make_span("s3", "writer", cost_usd=0.08, parent_span_id="s1"),
            make_span("s4", "reviewer", cost_usd=0.12, parent_span_id="s1"),
        ]
        span_db = {s.span_id: s for s in spans}
        result = calculate_decision_path_cost("s1", span_db)

        assert result.direct_cost == 0.05
        assert result.child_cost == pytest.approx(0.30, abs=1e-6)
        assert result.total_cost == pytest.approx(0.35, abs=1e-6)
        assert len(result.child_breakdown) == 3

    def test_none_cost_treated_as_zero(self):
        span = make_span("s1", "no_cost", cost_usd=None)
        span_db = {"s1": span}
        result = calculate_decision_path_cost("s1", span_db)
        assert result.direct_cost == 0.0
        assert result.total_cost == 0.0

    def test_agent_id_propagated(self):
        span = make_span("s1", "agent_work", cost_usd=0.05, agent_id="researcher_v1")
        span_db = {"s1": span}
        result = calculate_decision_path_cost("s1", span_db)
        assert result.agent_id == "researcher_v1"

    def test_waste_detection_retry_bloat(self):
        """Retried children should be flagged as waste."""
        spans = [
            make_span("s1", "parent", cost_usd=0.01),
            make_span("s2", "llm_call", cost_usd=0.05, parent_span_id="s1", attempt_number=1),
            make_span("s3", "llm_call", cost_usd=0.05, parent_span_id="s1", attempt_number=2),
            make_span("s4", "llm_call", cost_usd=0.05, parent_span_id="s1", attempt_number=3),
        ]
        span_db = {s.span_id: s for s in spans}
        result = calculate_decision_path_cost("s1", span_db)

        assert len(result.waste_detected) > 0
        retry_waste = [w for w in result.waste_detected if w["type"] == "retry_bloat"]
        assert len(retry_waste) == 1
        assert retry_waste[0]["retry_count"] == 2
        assert retry_waste[0]["wasted_cost"] == pytest.approx(0.10)

    def test_waste_detection_dead_end(self):
        """Failed child with cost should be flagged as dead-end."""
        spans = [
            make_span("s1", "parent", cost_usd=0.01),
            make_span("s2", "good_work", cost_usd=0.05, parent_span_id="s1"),
            make_span(
                "s3", "failed_work", cost_usd=0.08, parent_span_id="s1",
                status=SpanStatus.ERROR,
            ),
        ]
        span_db = {s.span_id: s for s in spans}
        result = calculate_decision_path_cost("s1", span_db)

        dead_ends = [w for w in result.waste_detected if w["type"] == "dead_end"]
        assert len(dead_ends) == 1
        assert dead_ends[0]["wasted_cost"] == pytest.approx(0.08)

    def test_cascade_impact_on_error(self):
        """Failed parent with failed children should report cascade impact."""
        spans = [
            make_span("s1", "root", cost_usd=0.01, status=SpanStatus.ERROR),
            make_span(
                "s2", "child_fail", cost_usd=0.05, parent_span_id="s1",
                status=SpanStatus.ERROR
            ),
        ]
        span_db = {s.span_id: s for s in spans}
        result = calculate_decision_path_cost("s1", span_db)

        assert result.cascade_impact is not None
        assert result.cascade_impact["failed_children"] == 1

    def test_no_cascade_impact_on_success(self):
        spans = [
            make_span("s1", "root", cost_usd=0.01),
            make_span("s2", "child", cost_usd=0.05, parent_span_id="s1"),
        ]
        span_db = {s.span_id: s for s in spans}
        result = calculate_decision_path_cost("s1", span_db)
        assert result.cascade_impact is None

    def test_max_depth_truncation(self):
        """Deep trees are truncated to prevent stack overflow."""
        spans = []
        for i in range(55):
            parent = f"s{i-1}" if i > 0 else None
            spans.append(make_span(f"s{i}", f"level_{i}", cost_usd=0.01, parent_span_id=parent))

        span_db = {s.span_id: s for s in spans}
        result = calculate_decision_path_cost("s0", span_db, _max_depth=50)

        # Should not raise, should truncate
        assert result.total_cost > 0

    def test_prebuilt_tree(self):
        """Passing a pre-built tree avoids rebuilding."""
        spans = [
            make_span("s1", "root", cost_usd=0.01),
            make_span("s2", "child", cost_usd=0.02, parent_span_id="s1"),
        ]
        span_db = {s.span_id: s for s in spans}
        tree = {"s1": ["s2"]}

        result = calculate_decision_path_cost("s1", span_db, tree=tree)
        assert result.total_cost == pytest.approx(0.03)


class TestCalculateTraceCostTree:
    def test_empty_spans(self):
        assert calculate_trace_cost_tree([]) == []

    def test_single_root(self):
        spans = [make_span("s1", "root", cost_usd=0.10)]
        trees = calculate_trace_cost_tree(spans)
        assert len(trees) == 1
        assert trees[0].total_cost == pytest.approx(0.10)

    def test_multiple_roots(self):
        """Trace with two independent root spans."""
        spans = [
            make_span("s1", "root1", cost_usd=0.05),
            make_span("s2", "root2", cost_usd=0.10),
        ]
        trees = calculate_trace_cost_tree(spans)
        assert len(trees) == 2
        total = sum(t.total_cost for t in trees)
        assert total == pytest.approx(0.15)

    def test_full_tree(self):
        """Complete tree: root -> 2 children, one with grandchild."""
        spans = [
            make_span("s1", "root", cost_usd=0.01),
            make_span("s2", "child_a", cost_usd=0.05, parent_span_id="s1"),
            make_span("s3", "child_b", cost_usd=0.03, parent_span_id="s1"),
            make_span("s4", "grandchild", cost_usd=0.02, parent_span_id="s2"),
        ]
        trees = calculate_trace_cost_tree(spans)
        assert len(trees) == 1
        root = trees[0]
        assert root.total_cost == pytest.approx(0.11)
        assert root.direct_cost == pytest.approx(0.01)
        assert root.child_cost == pytest.approx(0.10)

    def test_orphan_parent_becomes_root(self):
        """Span whose parent is not in the trace becomes a root."""
        spans = [
            make_span("s2", "orphan", cost_usd=0.05, parent_span_id="external_parent"),
        ]
        trees = calculate_trace_cost_tree(spans)
        assert len(trees) == 1
        assert trees[0].decision_span_id == "s2"
