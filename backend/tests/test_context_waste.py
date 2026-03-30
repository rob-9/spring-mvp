"""
Tests for context waste and duplicate prompt detection.
"""

import pytest
from datetime import datetime, timedelta
from backend.core.models import Span, SpanStatus
from backend.analysis.waste_detection.context_waste import (
    detect_context_waste,
    detect_duplicate_prompts,
)


def make_span(span_id, name, cost_usd=0.0, **kwargs):
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
        **defaults,
    )


class TestDetectContextWaste:
    def test_empty_spans(self):
        assert detect_context_waste([]) == []

    def test_no_significant_tokens(self):
        """Spans with < 1000 tokens are ignored."""
        spans = [
            make_span("s1", "a", tokens_input=500),
            make_span("s2", "b", tokens_input=500),
        ]
        assert detect_context_waste(spans) == []

    def test_single_significant_span(self):
        """Need at least 2 similar spans to detect waste."""
        spans = [make_span("s1", "a", tokens_input=5000, cost_usd=0.10)]
        assert detect_context_waste(spans) == []

    def test_duplicate_context_detected(self):
        """Two spans with similar token counts flagged as waste."""
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "a", tokens_input=5000, cost_usd=0.10,
                       start_time=base),
            make_span("s2", "b", tokens_input=5100, cost_usd=0.10,
                       start_time=base + timedelta(seconds=5)),
        ]
        result = detect_context_waste(spans)
        assert len(result) == 1
        assert result[0]["type"] == "context_waste"
        assert result[0]["repetitions"] == 2
        assert result[0]["wasted_cost"] == pytest.approx(0.10)

    def test_different_token_counts_not_flagged(self):
        """Spans with very different token counts are not similar."""
        spans = [
            make_span("s1", "a", tokens_input=5000, cost_usd=0.10),
            make_span("s2", "b", tokens_input=20000, cost_usd=0.40),
        ]
        result = detect_context_waste(spans)
        assert len(result) == 0

    def test_sorted_by_wasted_cost(self):
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "a", tokens_input=5000, cost_usd=0.05,
                       start_time=base),
            make_span("s2", "b", tokens_input=5100, cost_usd=0.05,
                       start_time=base + timedelta(seconds=1)),
            make_span("s3", "c", tokens_input=10000, cost_usd=0.20,
                       start_time=base + timedelta(seconds=2)),
            make_span("s4", "d", tokens_input=10100, cost_usd=0.20,
                       start_time=base + timedelta(seconds=3)),
        ]
        result = detect_context_waste(spans)
        if len(result) >= 2:
            costs = [r["wasted_cost"] for r in result]
            assert costs == sorted(costs, reverse=True)


class TestDetectDuplicatePrompts:
    def test_empty_spans(self):
        assert detect_duplicate_prompts([]) == []

    def test_no_prompts_in_metadata(self):
        spans = [
            make_span("s1", "a"),
            make_span("s2", "b"),
        ]
        assert detect_duplicate_prompts(spans) == []

    def test_short_prompts_ignored(self):
        """Prompts shorter than 100 chars are ignored."""
        spans = [
            make_span("s1", "a", metadata={"prompt": "short"}),
            make_span("s2", "b", metadata={"prompt": "short"}),
        ]
        assert detect_duplicate_prompts(spans) == []

    def test_duplicate_prompts_detected(self):
        long_prompt = "x" * 200
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "a", cost_usd=0.10, metadata={"prompt": long_prompt},
                       start_time=base),
            make_span("s2", "b", cost_usd=0.10, metadata={"prompt": long_prompt},
                       start_time=base + timedelta(seconds=1)),
        ]
        result = detect_duplicate_prompts(spans)
        assert len(result) == 1
        assert result[0]["type"] == "duplicate_prompt"
        assert result[0]["repetitions"] == 2
        assert result[0]["wasted_cost"] == pytest.approx(0.10)

    def test_uses_input_field_too(self):
        """Also checks metadata.input field."""
        long_input = "y" * 200
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "a", cost_usd=0.05, metadata={"input": long_input},
                       start_time=base),
            make_span("s2", "b", cost_usd=0.05, metadata={"input": long_input},
                       start_time=base + timedelta(seconds=1)),
        ]
        result = detect_duplicate_prompts(spans)
        assert len(result) == 1

    def test_min_occurrences(self):
        long_prompt = "z" * 200
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "a", cost_usd=0.10, metadata={"prompt": long_prompt},
                       start_time=base),
            make_span("s2", "b", cost_usd=0.10, metadata={"prompt": long_prompt},
                       start_time=base + timedelta(seconds=1)),
        ]
        # min_occurrences=3 means 2 is not enough
        assert detect_duplicate_prompts(spans, min_occurrences=3) == []
        # min_occurrences=2 should detect
        assert len(detect_duplicate_prompts(spans, min_occurrences=2)) == 1

    def test_different_prompts_not_flagged(self):
        base = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            make_span("s1", "a", cost_usd=0.10,
                       metadata={"prompt": "a" * 200}, start_time=base),
            make_span("s2", "b", cost_usd=0.10,
                       metadata={"prompt": "b" * 200},
                       start_time=base + timedelta(seconds=1)),
        ]
        assert detect_duplicate_prompts(spans) == []
