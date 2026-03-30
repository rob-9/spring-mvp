"""
Tests for cascade failure detection.

Validates detection of cascading failures, error clusters,
and retry cascades.
"""

import pytest
from datetime import datetime, timedelta
from backend.core.models import Span, SpanStatus
from backend.analysis.waste_detection.cascade import (
    detect_cascade_failures,
    detect_error_clusters,
    analyze_retry_cascade,
    _get_all_descendants,
)


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


class TestDetectCascadeFailures:
    def test_empty_spans(self):
        assert detect_cascade_failures([]) == []

    def test_no_errors(self):
        spans = [
            make_span("s1", "root"),
            make_span("s2", "child", parent_span_id="s1"),
        ]
        assert detect_cascade_failures(spans) == []

    def test_error_without_descendants(self):
        """Single error with no children = no cascade."""
        spans = [make_span("s1", "root", status=SpanStatus.ERROR)]
        assert detect_cascade_failures(spans) == []

    def test_error_with_successful_children(self):
        """Error parent but children succeed = no cascade flagged."""
        spans = [
            make_span("s1", "root", cost_usd=0.05, status=SpanStatus.ERROR),
            make_span("s2", "child", cost_usd=0.10, parent_span_id="s1"),
        ]
        # Children exist and have cost, but none failed -> no cascade
        result = detect_cascade_failures(spans)
        assert len(result) == 0

    def test_cascade_failure_detected(self):
        """Error propagates from parent to children."""
        spans = [
            make_span("s1", "root", cost_usd=0.05, status=SpanStatus.ERROR),
            make_span("s2", "child", cost_usd=0.10, parent_span_id="s1",
                       status=SpanStatus.ERROR),
        ]
        result = detect_cascade_failures(spans)
        assert len(result) == 1
        assert result[0]["type"] == "cascade_failure"
        assert result[0]["root_span_id"] == "s1"
        assert result[0]["cascade_cost"] == pytest.approx(0.10)
        assert result[0]["blast_radius"] == 1

    def test_deep_cascade(self):
        """Error cascades through multiple levels."""
        spans = [
            make_span("s1", "root", cost_usd=0.01, status=SpanStatus.ERROR),
            make_span("s2", "child", cost_usd=0.05, parent_span_id="s1",
                       status=SpanStatus.ERROR),
            make_span("s3", "grandchild", cost_usd=0.10, parent_span_id="s2",
                       status=SpanStatus.ERROR),
        ]
        result = detect_cascade_failures(spans)

        # Root sees both descendants
        root_cascade = [r for r in result if r["root_span_id"] == "s1"]
        assert len(root_cascade) == 1
        assert root_cascade[0]["blast_radius"] == 2
        assert root_cascade[0]["cascade_cost"] == pytest.approx(0.15)

    def test_sorted_by_cascade_cost(self):
        spans = [
            make_span("s1", "err_cheap", cost_usd=0.01, status=SpanStatus.ERROR),
            make_span("s2", "child_cheap", cost_usd=0.02, parent_span_id="s1",
                       status=SpanStatus.ERROR),
            make_span("s3", "err_expensive", cost_usd=0.01, status=SpanStatus.ERROR),
            make_span("s4", "child_expensive", cost_usd=0.50, parent_span_id="s3",
                       status=SpanStatus.ERROR),
        ]
        result = detect_cascade_failures(spans)
        costs = [r["cascade_cost"] for r in result]
        assert costs == sorted(costs, reverse=True)


class TestDetectErrorClusters:
    def test_empty_spans(self):
        assert detect_error_clusters([]) == []

    def test_single_error(self):
        spans = [make_span("s1", "err", status=SpanStatus.ERROR)]
        assert detect_error_clusters(spans) == []

    def test_cluster_detected(self):
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "err1", cost_usd=0.05, status=SpanStatus.ERROR,
                       start_time=base),
            make_span("s2", "err2", cost_usd=0.10, status=SpanStatus.ERROR,
                       start_time=base + timedelta(seconds=5)),
        ]
        result = detect_error_clusters(spans)
        assert len(result) == 1
        assert result[0]["cluster_size"] == 2
        assert result[0]["total_cost"] == pytest.approx(0.15)

    def test_errors_outside_window(self):
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "err1", status=SpanStatus.ERROR,
                       start_time=base),
            make_span("s2", "err2", status=SpanStatus.ERROR,
                       start_time=base + timedelta(seconds=120)),
        ]
        result = detect_error_clusters(spans, time_window_seconds=60)
        assert len(result) == 0

    def test_custom_time_window(self):
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "err1", cost_usd=0.01, status=SpanStatus.ERROR,
                       start_time=base),
            make_span("s2", "err2", cost_usd=0.01, status=SpanStatus.ERROR,
                       start_time=base + timedelta(seconds=3)),
        ]
        # Window too small
        assert detect_error_clusters(spans, time_window_seconds=2) == []
        # Window large enough
        result = detect_error_clusters(spans, time_window_seconds=10)
        assert len(result) == 1


class TestAnalyzeRetryCascade:
    def test_empty_spans(self):
        assert analyze_retry_cascade([]) == []

    def test_no_retries(self):
        spans = [
            make_span("s1", "root"),
            make_span("s2", "child", parent_span_id="s1"),
        ]
        assert analyze_retry_cascade(spans) == []

    def test_retry_triggers_more_retries(self):
        spans = [
            make_span("s1", "root"),
            make_span("s2", "retry_parent", parent_span_id="s1", attempt_number=2,
                       cost_usd=0.05),
            make_span("s3", "retry_child", parent_span_id="s2", attempt_number=2,
                       cost_usd=0.10),
        ]
        result = analyze_retry_cascade(spans)
        assert len(result) == 1
        assert result[0]["root_span_id"] == "s2"
        assert result[0]["triggered_retries"] == 1
        assert result[0]["cascade_cost"] == pytest.approx(0.10)

    def test_retry_without_downstream_retries(self):
        """Retry that doesn't trigger more retries = not reported."""
        spans = [
            make_span("s1", "root"),
            make_span("s2", "retry", parent_span_id="s1", attempt_number=2,
                       cost_usd=0.05),
            make_span("s3", "normal_child", parent_span_id="s2", attempt_number=1,
                       cost_usd=0.10),
        ]
        result = analyze_retry_cascade(spans)
        assert len(result) == 0


class TestGetAllDescendants:
    def test_no_children(self):
        result = _get_all_descendants("s1", {}, {})
        assert result == []

    def test_direct_children(self):
        span_map = {
            "s1": make_span("s1", "root"),
            "s2": make_span("s2", "child"),
        }
        children_map = {"s1": ["s2"]}
        result = _get_all_descendants("s1", children_map, span_map)
        assert result == ["s2"]

    def test_deep_descendants(self):
        span_map = {
            "s1": make_span("s1", "root"),
            "s2": make_span("s2", "child"),
            "s3": make_span("s3", "grandchild"),
        }
        children_map = {"s1": ["s2"], "s2": ["s3"]}
        result = _get_all_descendants("s1", children_map, span_map)
        assert set(result) == {"s2", "s3"}
