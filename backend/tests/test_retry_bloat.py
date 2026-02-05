"""
Unit tests for retry bloat detection.
"""

import pytest
from datetime import datetime, timedelta
from backend.core.models import Span, SpanStatus
from backend.analysis.waste_detection.retry_bloat import (
    detect_retry_bloat,
    _group_spans_by_name,
    _calculate_retry_metrics,
)


class TestRetryBloatDetection:
    """Test suite for retry bloat detector."""

    def test_no_retries(self, mock_span):
        """No retries detected when all spans have unique names."""
        children = [
            mock_span(span_id="1", name="operation_a", cost_usd=0.05),
            mock_span(span_id="2", name="operation_b", cost_usd=0.03),
            mock_span(span_id="3", name="operation_c", cost_usd=0.02)
        ]

        result = detect_retry_bloat(children)

        assert result == []

    def test_single_retry(self, mock_span):
        """Single retry (2 calls) detected."""
        children = [
            mock_span(span_id="1", name="check_db", cost_usd=0.05, attempt_number=1),
            mock_span(span_id="2", name="check_db", cost_usd=0.05, attempt_number=2),
            mock_span(span_id="3", name="format", cost_usd=0.02, attempt_number=1)
        ]

        result = detect_retry_bloat(children)

        assert len(result) == 1
        assert result[0]["type"] == "retry_bloat"
        assert result[0]["operation_name"] == "check_db"
        assert result[0]["retry_count"] == 1
        assert result[0]["wasted_cost"] == 0.05
        assert result[0]["total_cost"] == 0.10
        assert result[0]["span_ids"] == ["1", "2"]

    def test_multiple_retries_same_operation(self, mock_span):
        """Multiple retries (5 calls) of same operation."""
        children = [
            mock_span(span_id="1", name="stuck_op", cost_usd=0.05, attempt_number=1),
            mock_span(span_id="2", name="stuck_op", cost_usd=0.05, attempt_number=2),
            mock_span(span_id="3", name="stuck_op", cost_usd=0.05, attempt_number=3),
            mock_span(span_id="4", name="stuck_op", cost_usd=0.05, attempt_number=4),
            mock_span(span_id="5", name="stuck_op", cost_usd=0.05, attempt_number=5)
        ]

        result = detect_retry_bloat(children)

        assert len(result) == 1
        assert result[0]["retry_count"] == 4
        assert result[0]["wasted_cost"] == 0.20
        assert result[0]["total_cost"] == 0.25

    def test_multiple_operations_with_retries(self, mock_span):
        """Multiple different operations each have retries."""
        children = [
            mock_span(span_id="1", name="op_a", cost_usd=0.10, attempt_number=1),
            mock_span(span_id="2", name="op_a", cost_usd=0.10, attempt_number=2),
            mock_span(span_id="3", name="op_b", cost_usd=0.05, attempt_number=1),
            mock_span(span_id="4", name="op_b", cost_usd=0.05, attempt_number=2),
            mock_span(span_id="5", name="op_b", cost_usd=0.05, attempt_number=3)
        ]

        result = detect_retry_bloat(children)

        # Should detect both operations
        assert len(result) == 2

        # Sorted by wasted cost descending
        assert result[0]["operation_name"] == "op_b"  # wasted 0.10
        assert result[0]["wasted_cost"] == pytest.approx(0.10)

        assert result[1]["operation_name"] == "op_a"  # wasted 0.10
        assert result[1]["wasted_cost"] == pytest.approx(0.10)

    def test_cost_calculation_excludes_first_attempt(self, mock_span):
        """Wasted cost correctly excludes first attempt."""
        children = [
            mock_span(span_id="1", name="op", cost_usd=0.03, attempt_number=1),
            mock_span(span_id="2", name="op", cost_usd=0.07, attempt_number=2),
            mock_span(span_id="3", name="op", cost_usd=0.09, attempt_number=3)
        ]

        result = detect_retry_bloat(children)

        # First attempt (0.03) not wasted, retries (0.07 + 0.09) are wasted
        assert result[0]["wasted_cost"] == 0.16
        assert result[0]["total_cost"] == 0.19

    def test_missing_cost_treated_as_zero(self, mock_span):
        """Handles spans with None cost_usd."""
        children = [
            mock_span(span_id="1", name="op", cost_usd=None, attempt_number=1),
            mock_span(span_id="2", name="op", cost_usd=0.05, attempt_number=2)
        ]

        result = detect_retry_bloat(children)

        assert result[0]["wasted_cost"] == 0.05
        assert result[0]["total_cost"] == 0.05

    def test_empty_children_list(self, mock_span):
        """Returns empty list when no children provided."""
        result = detect_retry_bloat([])

        assert result == []

    def test_single_child(self, mock_span):
        """No retries detected with only one child."""
        children = [mock_span(span_id="1", name="op", cost_usd=0.05)]

        result = detect_retry_bloat(children)

        assert result == []

    def test_span_ids_captured_in_order(self, mock_span):
        """All retry span IDs captured in order by attempt_number."""
        children = [
            mock_span(span_id="span_3", name="op", attempt_number=3),
            mock_span(span_id="span_1", name="op", attempt_number=1),
            mock_span(span_id="span_2", name="op", attempt_number=2)
        ]

        result = detect_retry_bloat(children)

        # Should be sorted by attempt_number
        assert result[0]["span_ids"] == ["span_1", "span_2", "span_3"]

    def test_attempt_number_sorting(self, mock_span):
        """Uses attempt_number for sorting (not insertion order)."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        # Insert in reverse order but with correct attempt_numbers
        children = [
            mock_span(span_id="3", name="op", cost_usd=0.01, attempt_number=3, start_time=base_time),
            mock_span(span_id="2", name="op", cost_usd=0.02, attempt_number=2, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="1", name="op", cost_usd=0.03, attempt_number=1, start_time=base_time + timedelta(seconds=2))
        ]

        result = detect_retry_bloat(children)

        # First attempt should be span_id="1" (attempt_number=1)
        # wasted_cost = (0.01 + 0.02) = 0.03
        assert result[0]["wasted_cost"] == pytest.approx(0.03)
        assert result[0]["span_ids"] == ["1", "2", "3"]

    def test_details_message_format(self, mock_span):
        """Details field has correct human-readable format."""
        children = [
            mock_span(span_id="1", name="validate_user", cost_usd=0.05, attempt_number=1),
            mock_span(span_id="2", name="validate_user", cost_usd=0.05, attempt_number=2)
        ]

        result = detect_retry_bloat(children)

        assert "validate_user" in result[0]["details"]
        assert "1x" in result[0]["details"]
        assert "$0.0500" in result[0]["details"]

    def test_sibling_validation_fails_different_parents(self, mock_span):
        """Raises error when children have different parent_span_ids."""
        children = [
            mock_span(span_id="1", name="op", parent_span_id="parent_a"),
            mock_span(span_id="2", name="op", parent_span_id="parent_b")
        ]

        with pytest.raises(ValueError, match="same parent_span_id"):
            detect_retry_bloat(children)

    def test_sibling_validation_passes_same_parent(self, mock_span):
        """No error when all children share same parent."""
        children = [
            mock_span(span_id="1", name="op", parent_span_id="parent_x"),
            mock_span(span_id="2", name="op", parent_span_id="parent_x")
        ]

        # Should not raise
        result = detect_retry_bloat(children)
        assert len(result) == 1


class TestHelperFunctions:
    """Test helper functions in isolation."""

    def test_group_spans_by_name(self, mock_span):
        """Spans correctly grouped by name."""
        spans = [
            mock_span(span_id="1", name="op_a"),
            mock_span(span_id="2", name="op_b"),
            mock_span(span_id="3", name="op_a"),
            mock_span(span_id="4", name="op_c")
        ]

        grouped = _group_spans_by_name(spans)

        assert len(grouped) == 3
        assert len(grouped["op_a"]) == 2
        assert len(grouped["op_b"]) == 1
        assert len(grouped["op_c"]) == 1

    def test_calculate_retry_metrics(self, mock_span):
        """Retry metrics calculated correctly."""
        spans = [
            mock_span(span_id="1", name="op", cost_usd=0.05, attempt_number=1),
            mock_span(span_id="2", name="op", cost_usd=0.06, attempt_number=2),
            mock_span(span_id="3", name="op", cost_usd=0.07, attempt_number=3)
        ]

        metrics = _calculate_retry_metrics(spans)

        assert metrics["retry_count"] == 2
        assert metrics["wasted_cost"] == 0.13  # 0.06 + 0.07
        assert metrics["total_cost"] == 0.18   # 0.05 + 0.06 + 0.07
        assert metrics["span_ids"] == ["1", "2", "3"]
