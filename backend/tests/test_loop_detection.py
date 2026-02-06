"""
Unit tests for loop detection algorithms.
"""

import pytest
from datetime import datetime, timedelta
from backend.core.models import Span, SpanStatus, SpanLink
from backend.analysis.waste_detection.loop_detection import (
    detect_loops,
    detect_structural_loops,
    detect_behavioral_loops,
    _deduplicate_patterns
)


class TestStructuralLoopDetection:
    """Test suite for structural loop detection (via span links)."""

    def test_no_links_no_cycles(self, mock_span):
        """No cycles when spans have no links."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            mock_span(span_id="A", name="agent_a", cost_usd=0.05, start_time=base_time),
            mock_span(span_id="B", name="agent_b", cost_usd=0.03, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="C", name="agent_c", cost_usd=0.02, start_time=base_time + timedelta(seconds=2))
        ]

        result = detect_structural_loops(spans)

        assert result == []

    def test_simple_cycle_via_links(self, mock_span):
        """Detect cycle: A links to B, B links to A."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        trace_id = "trace-123"

        span_a = mock_span(
            span_id="A",
            trace_id=trace_id,
            name="agent_a",
            cost_usd=0.05,
            start_time=base_time
        )
        span_b = mock_span(
            span_id="B",
            trace_id=trace_id,
            name="agent_b",
            cost_usd=0.03,
            start_time=base_time + timedelta(seconds=1)
        )

        # A links to B, B links back to A (creating cycle)
        span_a.links = [SpanLink(trace_id=trace_id, span_id="B")]
        span_b.links = [SpanLink(trace_id=trace_id, span_id="A")]

        spans = [span_a, span_b]
        result = detect_structural_loops(spans)

        assert len(result) >= 1
        # Should detect the A → B → A cycle
        assert result[0]["loop_type"] == "structural"
        assert result[0]["cycle_length"] >= 2
        assert result[0]["wasted_cost"] > 0

    def test_three_node_cycle_via_links(self, mock_span):
        """Detect cycle: A → B → C → A via span links."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        trace_id = "trace-456"

        span_a = mock_span(
            span_id="A",
            trace_id=trace_id,
            name="planner",
            cost_usd=0.05,
            start_time=base_time
        )
        span_b = mock_span(
            span_id="B",
            trace_id=trace_id,
            name="researcher",
            cost_usd=0.08,
            start_time=base_time + timedelta(seconds=1)
        )
        span_c = mock_span(
            span_id="C",
            trace_id=trace_id,
            name="validator",
            cost_usd=0.06,
            start_time=base_time + timedelta(seconds=2)
        )

        # Create cycle: A → B → C → A
        span_a.links = [SpanLink(trace_id=trace_id, span_id="B")]
        span_b.links = [SpanLink(trace_id=trace_id, span_id="C")]
        span_c.links = [SpanLink(trace_id=trace_id, span_id="A")]

        spans = [span_a, span_b, span_c]
        result = detect_structural_loops(spans)

        assert len(result) >= 1
        loop = result[0]
        assert loop["loop_type"] == "structural"
        assert loop["cycle_length"] == 3
        assert loop["wasted_cost"] == pytest.approx(0.05 + 0.08 + 0.06)
        assert "planner" in loop["cycle_path"]
        assert "researcher" in loop["cycle_path"]
        assert "validator" in loop["cycle_path"]

    def test_links_to_different_trace_ignored(self, mock_span):
        """Links to spans in different traces are ignored."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        span_a = mock_span(
            span_id="A",
            trace_id="trace-1",
            name="agent_a",
            cost_usd=0.05,
            start_time=base_time
        )
        span_b = mock_span(
            span_id="B",
            trace_id="trace-2",  # Different trace
            name="agent_b",
            cost_usd=0.03,
            start_time=base_time + timedelta(seconds=1)
        )

        # A links to B (but different trace, should be ignored)
        span_a.links = [SpanLink(trace_id="trace-2", span_id="B")]
        span_b.links = [SpanLink(trace_id="trace-1", span_id="A")]

        result = detect_structural_loops([span_a, span_b])

        # No cycles because links cross trace boundaries
        assert result == []

    def test_zero_cost_cycle_not_reported(self, mock_span):
        """Cycles with zero cost are not reported as waste."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        trace_id = "trace-789"

        span_a = mock_span(
            span_id="A",
            trace_id=trace_id,
            name="free_op",
            cost_usd=0.0,
            start_time=base_time
        )
        span_b = mock_span(
            span_id="B",
            trace_id=trace_id,
            name="another_free",
            cost_usd=0.0,
            start_time=base_time + timedelta(seconds=1)
        )

        span_a.links = [SpanLink(trace_id=trace_id, span_id="B")]
        span_b.links = [SpanLink(trace_id=trace_id, span_id="A")]

        result = detect_structural_loops([span_a, span_b])

        # Cycle exists but has no cost, so not reported
        assert result == []

    def test_empty_spans(self):
        """Handles empty span list."""
        result = detect_structural_loops([])
        assert result == []


class TestBehavioralLoopDetection:
    """Test suite for behavioral loop detection (repeated patterns)."""

    def test_no_repetition_unique_sequence(self, mock_span):
        """No loops when all operations are unique."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            mock_span(span_id="1", name="op_a", cost_usd=0.05, start_time=base_time),
            mock_span(span_id="2", name="op_b", cost_usd=0.03, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="op_c", cost_usd=0.02, start_time=base_time + timedelta(seconds=2))
        ]

        result = detect_behavioral_loops(spans)

        assert result == []

    def test_simple_pattern_repetition(self, mock_span):
        """Detect repeated pattern: A → B, A → B."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            mock_span(span_id="1", name="check", cost_usd=0.05, start_time=base_time),
            mock_span(span_id="2", name="validate", cost_usd=0.03, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="check", cost_usd=0.05, start_time=base_time + timedelta(seconds=2)),
            mock_span(span_id="4", name="validate", cost_usd=0.03, start_time=base_time + timedelta(seconds=3))
        ]

        result = detect_behavioral_loops(spans)

        assert len(result) >= 1
        # Should detect the "check → validate" pattern repeating
        loop = result[0]
        assert loop["pattern"] == ["check", "validate"]
        assert loop["repetitions"] == 2
        assert loop["wasted_cost"] == pytest.approx(0.08)  # Second occurrence
        assert "occurrences" in loop
        assert len(loop["occurrences"]) == 2

    def test_three_operation_loop(self, mock_span):
        """Detect A → B → C pattern repeating 3 times."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = []
        for i in range(3):
            offset = i * 3
            spans.extend([
                mock_span(span_id=f"A{i}", name="plan", cost_usd=0.05, start_time=base_time + timedelta(seconds=offset)),
                mock_span(span_id=f"B{i}", name="research", cost_usd=0.08, start_time=base_time + timedelta(seconds=offset + 1)),
                mock_span(span_id=f"C{i}", name="validate", cost_usd=0.06, start_time=base_time + timedelta(seconds=offset + 2))
            ])

        result = detect_behavioral_loops(spans, window_size=3)

        assert len(result) >= 1
        # Should find the 3-operation pattern
        loop = [r for r in result if r["pattern"] == ["plan", "research", "validate"]][0]
        assert loop["repetitions"] == 3
        assert loop["wasted_cost"] == pytest.approx((0.05 + 0.08 + 0.06) * 2)  # 2 repetitions wasted

    def test_wasted_cost_calculation(self, mock_span):
        """Wasted cost excludes first occurrence."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            mock_span(span_id="1", name="expensive_op", cost_usd=0.10, start_time=base_time),
            mock_span(span_id="2", name="cheap_op", cost_usd=0.01, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="expensive_op", cost_usd=0.10, start_time=base_time + timedelta(seconds=2)),
            mock_span(span_id="4", name="cheap_op", cost_usd=0.01, start_time=base_time + timedelta(seconds=3))
        ]

        result = detect_behavioral_loops(spans)

        # Should detect the 2-op pattern
        assert len(result) >= 1
        loop = result[0]
        # First occurrence (0.11) is not wasted, second is (0.11)
        assert loop["wasted_cost"] == pytest.approx(0.11)
        assert loop["total_cost"] == pytest.approx(0.22)
        assert loop["repetitions"] == 2

    def test_min_pattern_length_filters_short_patterns(self, mock_span):
        """min_pattern_length parameter filters patterns below minimum length."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            mock_span(span_id="1", name="op", cost_usd=0.10, start_time=base_time),
            mock_span(span_id="2", name="op", cost_usd=0.10, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="op", cost_usd=0.10, start_time=base_time + timedelta(seconds=2))
        ]

        # With min_pattern_length=3, patterns shorter than 3 are ignored
        result = detect_behavioral_loops(spans, min_pattern_length=3)
        assert result == []

        # With min_pattern_length=1, patterns are detected
        result = detect_behavioral_loops(spans, min_pattern_length=1)
        assert len(result) >= 1
        # After deduplication, finds ["op", "op"] pattern (longer patterns preferred)
        assert result[0]["pattern"] == ["op", "op"]
        assert result[0]["repetitions"] == 2

    def test_window_size_parameter(self, mock_span):
        """Window size controls maximum pattern length detected."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        # Create a 5-operation pattern that repeats
        pattern = ["op_a", "op_b", "op_c", "op_d", "op_e"]
        spans = []
        for rep in range(2):
            for i, op_name in enumerate(pattern):
                spans.append(
                    mock_span(
                        span_id=f"{rep}_{i}",
                        name=op_name,
                        cost_usd=0.05,
                        start_time=base_time + timedelta(seconds=rep * 10 + i)
                    )
                )

        # Small window won't detect the full 5-op pattern
        result_small = detect_behavioral_loops(spans, window_size=3)
        # Should find smaller sub-patterns
        max_pattern_length = max(len(r["pattern"]) for r in result_small) if result_small else 0
        assert max_pattern_length <= 3

        # Large window can detect the full pattern
        result_large = detect_behavioral_loops(spans, window_size=10)
        patterns_found = [r["pattern"] for r in result_large]
        assert pattern in patterns_found

    def test_deduplication_removes_overlaps(self, mock_span):
        """Overlapping patterns are deduplicated to avoid double-counting."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        # Create A → B → C repeated twice
        spans = [
            mock_span(span_id="1", name="A", cost_usd=0.05, start_time=base_time),
            mock_span(span_id="2", name="B", cost_usd=0.03, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="C", cost_usd=0.02, start_time=base_time + timedelta(seconds=2)),
            mock_span(span_id="4", name="A", cost_usd=0.05, start_time=base_time + timedelta(seconds=3)),
            mock_span(span_id="5", name="B", cost_usd=0.03, start_time=base_time + timedelta(seconds=4)),
            mock_span(span_id="6", name="C", cost_usd=0.02, start_time=base_time + timedelta(seconds=5))
        ]

        result = detect_behavioral_loops(spans)

        # After deduplication, should only report the longest pattern
        # Should find A→B→C, not also A→B and B→C
        assert len(result) == 1
        assert result[0]["pattern"] == ["A", "B", "C"]

    def test_empty_spans(self):
        """Handles empty span list."""
        result = detect_behavioral_loops([])
        assert result == []

    def test_single_span(self, mock_span):
        """Handles single span (no patterns possible)."""
        spans = [mock_span(span_id="1", name="op", cost_usd=0.05)]
        result = detect_behavioral_loops(spans)
        assert result == []

    def test_occurrences_structure(self, mock_span):
        """Occurrences field contains detailed pattern information."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            mock_span(span_id="1", name="op_a", cost_usd=0.05, start_time=base_time),
            mock_span(span_id="2", name="op_b", cost_usd=0.03, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="op_a", cost_usd=0.05, start_time=base_time + timedelta(seconds=2)),
            mock_span(span_id="4", name="op_b", cost_usd=0.03, start_time=base_time + timedelta(seconds=3))
        ]

        result = detect_behavioral_loops(spans)

        assert len(result) >= 1
        loop = result[0]
        assert "occurrences" in loop
        assert len(loop["occurrences"]) == 2

        # Check structure of occurrences
        first_occ = loop["occurrences"][0]
        assert "start_idx" in first_occ
        assert "span_ids" in first_occ
        assert "cost" in first_occ
        assert len(first_occ["span_ids"]) == 2  # op_a → op_b


class TestDeduplicatePatterns:
    """Test suite for pattern deduplication logic."""

    def test_deduplication_keeps_longest(self):
        """Deduplication keeps longest non-overlapping patterns."""
        # Simulate overlapping patterns from A→B→C repeated
        results = [
            {
                "type": "loop",
                "loop_type": "behavioral",
                "pattern": ["A", "B", "C"],
                "repetitions": 2,
                "wasted_cost": 0.30,
                "total_cost": 0.60,
                "occurrences": [
                    {"start_idx": 0, "span_ids": ["1", "2", "3"], "cost": 0.30},
                    {"start_idx": 3, "span_ids": ["4", "5", "6"], "cost": 0.30}
                ],
                "details": "..."
            },
            {
                "type": "loop",
                "loop_type": "behavioral",
                "pattern": ["A", "B"],
                "repetitions": 2,
                "wasted_cost": 0.20,
                "total_cost": 0.40,
                "occurrences": [
                    {"start_idx": 0, "span_ids": ["1", "2"], "cost": 0.20},
                    {"start_idx": 3, "span_ids": ["4", "5"], "cost": 0.20}
                ],
                "details": "..."
            },
            {
                "type": "loop",
                "loop_type": "behavioral",
                "pattern": ["B", "C"],
                "repetitions": 2,
                "wasted_cost": 0.15,
                "total_cost": 0.30,
                "occurrences": [
                    {"start_idx": 1, "span_ids": ["2", "3"], "cost": 0.15},
                    {"start_idx": 4, "span_ids": ["5", "6"], "cost": 0.15}
                ],
                "details": "..."
            }
        ]

        deduplicated = _deduplicate_patterns(results)

        # Should only keep the longest pattern (A→B→C)
        assert len(deduplicated) == 1
        assert deduplicated[0]["pattern"] == ["A", "B", "C"]

    def test_deduplication_keeps_multiple_non_overlapping(self):
        """Non-overlapping patterns are all kept."""
        results = [
            {
                "type": "loop",
                "loop_type": "behavioral",
                "pattern": ["A", "B"],
                "repetitions": 2,
                "wasted_cost": 0.20,
                "total_cost": 0.40,
                "occurrences": [
                    {"start_idx": 0, "span_ids": ["1", "2"], "cost": 0.20},
                    {"start_idx": 2, "span_ids": ["3", "4"], "cost": 0.20}
                ],
                "details": "..."
            },
            {
                "type": "loop",
                "loop_type": "behavioral",
                "pattern": ["C", "D"],
                "repetitions": 2,
                "wasted_cost": 0.15,
                "total_cost": 0.30,
                "occurrences": [
                    {"start_idx": 4, "span_ids": ["5", "6"], "cost": 0.15},
                    {"start_idx": 6, "span_ids": ["7", "8"], "cost": 0.15}
                ],
                "details": "..."
            }
        ]

        deduplicated = _deduplicate_patterns(results)

        # Both patterns should be kept (no overlap)
        assert len(deduplicated) == 2

    def test_empty_results(self):
        """Handles empty results list."""
        assert _deduplicate_patterns([]) == []


class TestCombinedLoopDetection:
    """Test the combined detect_loops function."""

    def test_combined_detection(self, mock_span):
        """detect_loops() combines structural and behavioral detection."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            mock_span(span_id="1", name="check", cost_usd=0.05, start_time=base_time),
            mock_span(span_id="2", name="validate", cost_usd=0.03, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="check", cost_usd=0.05, start_time=base_time + timedelta(seconds=2)),
            mock_span(span_id="4", name="validate", cost_usd=0.03, start_time=base_time + timedelta(seconds=3))
        ]

        result = detect_loops(spans)

        # Should detect behavioral loop
        assert len(result) >= 1
        assert all(r["type"] == "loop" for r in result)
        assert any(r["loop_type"] == "behavioral" for r in result)

    def test_sorted_by_wasted_cost(self, mock_span):
        """Results sorted by wasted cost descending."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            # Expensive repetition
            mock_span(span_id="1", name="expensive_a", cost_usd=0.20, start_time=base_time),
            mock_span(span_id="2", name="expensive_b", cost_usd=0.20, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="expensive_a", cost_usd=0.20, start_time=base_time + timedelta(seconds=2)),
            mock_span(span_id="4", name="expensive_b", cost_usd=0.20, start_time=base_time + timedelta(seconds=3)),
            # Cheap repetition
            mock_span(span_id="5", name="cheap_a", cost_usd=0.01, start_time=base_time + timedelta(seconds=4)),
            mock_span(span_id="6", name="cheap_b", cost_usd=0.01, start_time=base_time + timedelta(seconds=5)),
            mock_span(span_id="7", name="cheap_a", cost_usd=0.01, start_time=base_time + timedelta(seconds=6)),
            mock_span(span_id="8", name="cheap_b", cost_usd=0.01, start_time=base_time + timedelta(seconds=7))
        ]

        result = detect_loops(spans)

        if len(result) >= 2:
            # First result should have higher wasted cost
            assert result[0]["wasted_cost"] >= result[1]["wasted_cost"]

    def test_max_spans_limit(self, mock_span):
        """max_spans parameter limits analysis for performance."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        # Create 100 spans
        spans = [
            mock_span(span_id=str(i), name=f"op_{i % 3}", cost_usd=0.01, start_time=base_time + timedelta(seconds=i))
            for i in range(100)
        ]

        # With max_spans=10, should only analyze first 10
        result = detect_loops(spans, max_spans=10)

        # Function should complete without error (limit enforced)
        assert isinstance(result, list)

    def test_details_message_format(self, mock_span):
        """Details field has human-readable format."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)

        spans = [
            mock_span(span_id="1", name="plan", cost_usd=0.05, start_time=base_time),
            mock_span(span_id="2", name="execute", cost_usd=0.08, start_time=base_time + timedelta(seconds=1)),
            mock_span(span_id="3", name="plan", cost_usd=0.05, start_time=base_time + timedelta(seconds=2)),
            mock_span(span_id="4", name="execute", cost_usd=0.08, start_time=base_time + timedelta(seconds=3))
        ]

        result = detect_loops(spans)

        if result:
            assert "details" in result[0]
            assert "pattern" in result[0]["details"].lower() or "cycle" in result[0]["details"].lower()
            assert "$" in result[0]["details"]  # Cost mentioned

    def test_both_structural_and_behavioral_loops(self, mock_span):
        """Can detect both structural and behavioral loops in same trace."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        trace_id = "trace-mix"

        # Behavioral loop: repeated pattern
        span_1 = mock_span(span_id="1", trace_id=trace_id, name="check", cost_usd=0.05, start_time=base_time)
        span_2 = mock_span(span_id="2", trace_id=trace_id, name="validate", cost_usd=0.03, start_time=base_time + timedelta(seconds=1))
        span_3 = mock_span(span_id="3", trace_id=trace_id, name="check", cost_usd=0.05, start_time=base_time + timedelta(seconds=2))
        span_4 = mock_span(span_id="4", trace_id=trace_id, name="validate", cost_usd=0.03, start_time=base_time + timedelta(seconds=3))

        # Structural loop: A → B → A via links
        span_a = mock_span(span_id="A", trace_id=trace_id, name="agent_a", cost_usd=0.10, start_time=base_time + timedelta(seconds=4))
        span_b = mock_span(span_id="B", trace_id=trace_id, name="agent_b", cost_usd=0.08, start_time=base_time + timedelta(seconds=5))
        span_a.links = [SpanLink(trace_id=trace_id, span_id="B")]
        span_b.links = [SpanLink(trace_id=trace_id, span_id="A")]

        spans = [span_1, span_2, span_3, span_4, span_a, span_b]
        result = detect_loops(spans)

        # Should detect both types
        loop_types = {r["loop_type"] for r in result}
        assert "behavioral" in loop_types
        assert "structural" in loop_types
