"""
Unit tests for dead-end detection.
"""

import pytest
from datetime import datetime
from backend.core.models import Span, SpanStatus
from backend.analysis.waste_detection.dead_end import detect_dead_end


class TestDeadEndDetection:
    """Test suite for dead-end detector."""

    def test_error_span_with_cost(self, mock_span):
        """Dead-end detected when span has error status and cost."""
        span = mock_span(
            span_id="1",
            name="validate_user",
            cost_usd=0.05,
            status=SpanStatus.ERROR
        )

        result = detect_dead_end(span, [])

        assert len(result) == 1
        assert result[0]["type"] == "dead_end"
        assert result[0]["span_id"] == "1"
        assert result[0]["wasted_cost"] == 0.05
        assert result[0]["operation_name"] == "validate_user"
        assert result[0]["child_count"] == 0

    def test_success_span_no_waste(self, mock_span):
        """No waste detected when span succeeds."""
        span = mock_span(
            span_id="1",
            name="validate_user",
            cost_usd=0.05,
            status=SpanStatus.SUCCESS
        )

        result = detect_dead_end(span, [])

        assert result == []

    def test_error_span_no_cost(self, mock_span):
        """No waste when span fails but has no cost."""
        span = mock_span(
            span_id="1",
            name="validate_user",
            cost_usd=0.0,
            status=SpanStatus.ERROR
        )

        result = detect_dead_end(span, [])

        assert result == []

    def test_error_span_with_children(self, mock_span):
        """Total cost includes children when parent fails."""
        span = mock_span(
            span_id="1",
            name="process_order",
            cost_usd=0.05,
            status=SpanStatus.ERROR
        )
        children = [
            mock_span(span_id="2", name="check_inventory", cost_usd=0.03),
            mock_span(span_id="3", name="calculate_tax", cost_usd=0.02)
        ]

        result = detect_dead_end(span, children)

        assert len(result) == 1
        assert result[0]["wasted_cost"] == pytest.approx(0.10)  # 0.05 + 0.03 + 0.02
        assert result[0]["direct_cost"] == 0.05
        assert result[0]["child_cost"] == pytest.approx(0.05)
        assert result[0]["child_count"] == 2

    def test_failed_decision_detected(self, mock_span):
        """Dead-end detected via decision_made field."""
        span = mock_span(
            span_id="1",
            name="verify_payment",
            cost_usd=0.08,
            status=SpanStatus.SUCCESS,  # Status says success
            decision_made="payment_failed"  # But decision indicates failure
        )

        result = detect_dead_end(span, [])

        assert len(result) == 1
        assert result[0]["wasted_cost"] == 0.08

    def test_failed_variations(self, mock_span):
        """Detects various failure indicators in decision_made."""
        test_cases = [
            "failed",
            "Failed",
            "FAILED",
            "verification_failed",
            "fail"
        ]

        for decision in test_cases:
            span = mock_span(
                span_id="1",
                name="operation",
                cost_usd=0.05,
                status=SpanStatus.SUCCESS,
                decision_made=decision
            )

            result = detect_dead_end(span, [])

            assert len(result) == 1, f"Should detect failure for decision_made='{decision}'"

    def test_none_cost_treated_as_zero(self, mock_span):
        """Handles None costs gracefully."""
        span = mock_span(
            span_id="1",
            name="operation",
            cost_usd=None,
            status=SpanStatus.ERROR
        )
        children = [
            mock_span(span_id="2", name="child", cost_usd=None)
        ]

        result = detect_dead_end(span, children)

        # No cost, so no waste
        assert result == []

    def test_mixed_none_and_real_costs(self, mock_span):
        """Correctly sums costs when some are None."""
        span = mock_span(
            span_id="1",
            name="operation",
            cost_usd=0.05,
            status=SpanStatus.ERROR
        )
        children = [
            mock_span(span_id="2", name="child1", cost_usd=None),
            mock_span(span_id="3", name="child2", cost_usd=0.03)
        ]

        result = detect_dead_end(span, children)

        assert result[0]["wasted_cost"] == pytest.approx(0.08)

    def test_empty_children_list(self, mock_span):
        """Works with no children."""
        span = mock_span(
            span_id="1",
            name="operation",
            cost_usd=0.05,
            status=SpanStatus.ERROR
        )

        result = detect_dead_end(span, [])

        assert len(result) == 1
        assert result[0]["child_count"] == 0
        assert result[0]["child_cost"] == 0.0

    def test_details_message_format(self, mock_span):
        """Details field has correct format."""
        span = mock_span(
            span_id="1",
            name="validate_user",
            cost_usd=0.05,
            status=SpanStatus.ERROR
        )
        children = [
            mock_span(span_id="2", name="child", cost_usd=0.02)
        ]

        result = detect_dead_end(span, children)

        details = result[0]["details"]
        assert "validate_user" in details
        assert "failed" in details
        assert "$0.07" in details  # Total cost
        assert "1 child operation" in details

    def test_details_plural_children(self, mock_span):
        """Details uses plural for multiple children."""
        span = mock_span(
            span_id="1",
            name="operation",
            cost_usd=0.05,
            status=SpanStatus.ERROR
        )
        children = [
            mock_span(span_id="2", name="child1", cost_usd=0.01),
            mock_span(span_id="3", name="child2", cost_usd=0.01)
        ]

        result = detect_dead_end(span, children)

        assert "2 child operations" in result[0]["details"]

    def test_status_preserved(self, mock_span):
        """Result includes original status."""
        span = mock_span(
            span_id="1",
            name="operation",
            cost_usd=0.05,
            status=SpanStatus.ERROR
        )

        result = detect_dead_end(span, [])

        assert result[0]["status"] == "error"

    def test_decision_made_preserved(self, mock_span):
        """Result includes decision_made field."""
        span = mock_span(
            span_id="1",
            name="operation",
            cost_usd=0.05,
            status=SpanStatus.ERROR,
            decision_made="validation_failed"
        )

        result = detect_dead_end(span, [])

        assert result[0]["decision_made"] == "validation_failed"

    def test_running_status_not_dead_end(self, mock_span):
        """Running status is not a dead-end."""
        span = mock_span(
            span_id="1",
            name="operation",
            cost_usd=0.05,
            status=SpanStatus.RUNNING
        )

        result = detect_dead_end(span, [])

        assert result == []
