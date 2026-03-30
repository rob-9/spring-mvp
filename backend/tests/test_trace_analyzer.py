"""
Tests for the unified trace analysis engine.

Validates that analyze_trace correctly combines all waste detectors
and produces accurate summaries.
"""

import pytest
from datetime import datetime, timedelta
from backend.core.models import Span, SpanStatus
from backend.analysis.trace_analyzer import (
    analyze_trace,
    TraceAnalysis,
    WasteSummary,
    AgentSummary,
    _determine_trace_status,
    _calculate_trace_duration,
    _build_agent_summaries,
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


class TestDetermineTraceStatus:
    def test_all_success(self):
        spans = [
            make_span("s1", "a", status=SpanStatus.SUCCESS),
            make_span("s2", "b", status=SpanStatus.SUCCESS),
        ]
        assert _determine_trace_status(spans) == "success"

    def test_any_error(self):
        spans = [
            make_span("s1", "a", status=SpanStatus.SUCCESS),
            make_span("s2", "b", status=SpanStatus.ERROR),
        ]
        assert _determine_trace_status(spans) == "error"

    def test_running(self):
        spans = [
            make_span("s1", "a", status=SpanStatus.RUNNING),
        ]
        assert _determine_trace_status(spans) == "running"

    def test_error_takes_precedence_over_running(self):
        spans = [
            make_span("s1", "a", status=SpanStatus.RUNNING),
            make_span("s2", "b", status=SpanStatus.ERROR),
        ]
        assert _determine_trace_status(spans) == "error"


class TestCalculateTraceDuration:
    def test_with_end_times(self):
        start = datetime(2025, 1, 15, 10, 0, 0)
        end = datetime(2025, 1, 15, 10, 0, 5)
        spans = [
            make_span("s1", "a", start_time=start, end_time=end),
        ]
        duration = _calculate_trace_duration(spans)
        assert duration == 5000.0  # 5 seconds in ms

    def test_no_end_times(self):
        spans = [make_span("s1", "a")]
        assert _calculate_trace_duration(spans) is None

    def test_multiple_spans_uses_min_max(self):
        spans = [
            make_span("s1", "a",
                       start_time=datetime(2025, 1, 15, 10, 0, 0),
                       end_time=datetime(2025, 1, 15, 10, 0, 2)),
            make_span("s2", "b",
                       start_time=datetime(2025, 1, 15, 10, 0, 1),
                       end_time=datetime(2025, 1, 15, 10, 0, 10)),
        ]
        duration = _calculate_trace_duration(spans)
        assert duration == 10000.0  # 10 seconds


class TestBuildAgentSummaries:
    def test_no_agents(self):
        spans = [make_span("s1", "a")]
        assert _build_agent_summaries(spans) == []

    def test_single_agent(self):
        spans = [
            make_span("s1", "a", cost_usd=0.05, agent_id="agent_1", agent_name="Researcher"),
            make_span("s2", "b", cost_usd=0.10, agent_id="agent_1", agent_name="Researcher"),
        ]
        summaries = _build_agent_summaries(spans)
        assert len(summaries) == 1
        assert summaries[0].agent_id == "agent_1"
        assert summaries[0].span_count == 2
        assert summaries[0].total_cost == pytest.approx(0.15)

    def test_multiple_agents_sorted_by_cost(self):
        spans = [
            make_span("s1", "a", cost_usd=0.05, agent_id="cheap_agent"),
            make_span("s2", "b", cost_usd=0.50, agent_id="expensive_agent"),
        ]
        summaries = _build_agent_summaries(spans)
        assert len(summaries) == 2
        assert summaries[0].agent_id == "expensive_agent"
        assert summaries[1].agent_id == "cheap_agent"

    def test_error_count(self):
        spans = [
            make_span("s1", "a", agent_id="a1", status=SpanStatus.SUCCESS),
            make_span("s2", "b", agent_id="a1", status=SpanStatus.ERROR),
            make_span("s3", "c", agent_id="a1", status=SpanStatus.ERROR),
        ]
        summaries = _build_agent_summaries(spans)
        assert summaries[0].error_count == 2

    def test_models_used(self):
        spans = [
            make_span("s1", "a", agent_id="a1", model="gpt-4"),
            make_span("s2", "b", agent_id="a1", model="gpt-3.5-turbo"),
            make_span("s3", "c", agent_id="a1", model="gpt-4"),
        ]
        summaries = _build_agent_summaries(spans)
        assert set(summaries[0].models_used) == {"gpt-4", "gpt-3.5-turbo"}


class TestAnalyzeTrace:
    def test_empty_spans(self):
        result = analyze_trace([])
        assert result.trace_id == "unknown"
        assert result.span_count == 0

    def test_simple_trace(self):
        spans = [
            make_span("s1", "root", cost_usd=0.05),
            make_span("s2", "child", cost_usd=0.10, parent_span_id="s1"),
        ]
        result = analyze_trace(spans)

        assert result.trace_id == "trace_001"
        assert result.span_count == 2
        assert result.total_cost == pytest.approx(0.15)
        assert result.status == "success"
        assert len(result.decision_trees) == 1

    def test_detects_retry_bloat(self):
        spans = [
            make_span("s1", "root", cost_usd=0.01),
            make_span("s2", "llm_call", cost_usd=0.05, parent_span_id="s1", attempt_number=1),
            make_span("s3", "llm_call", cost_usd=0.05, parent_span_id="s1", attempt_number=2),
        ]
        result = analyze_trace(spans)

        assert len(result.retry_bloat) > 0
        assert result.waste.total_wasted_cost > 0

    def test_detects_dead_ends(self):
        spans = [
            make_span("s1", "root", cost_usd=0.01),
            make_span(
                "s2", "failed_call", cost_usd=0.10,
                parent_span_id="s1", status=SpanStatus.ERROR,
            ),
        ]
        result = analyze_trace(spans)

        assert len(result.dead_ends) > 0
        assert result.waste.total_wasted_cost > 0

    def test_detects_cascade_failures(self):
        spans = [
            make_span("s1", "root", cost_usd=0.01, status=SpanStatus.ERROR),
            make_span(
                "s2", "child", cost_usd=0.10, parent_span_id="s1",
                status=SpanStatus.ERROR,
            ),
            make_span(
                "s3", "grandchild", cost_usd=0.05, parent_span_id="s2",
                status=SpanStatus.ERROR,
            ),
        ]
        result = analyze_trace(spans)
        assert len(result.cascades) > 0

    def test_waste_percentage(self):
        """Waste percentage should be calculated from total cost."""
        spans = [
            make_span("s1", "root", cost_usd=0.10),
            make_span(
                "s2", "wasted", cost_usd=0.10, parent_span_id="s1",
                status=SpanStatus.ERROR,
            ),
        ]
        result = analyze_trace(spans)
        assert result.waste.waste_percentage > 0

    def test_token_tracking(self):
        spans = [
            make_span("s1", "llm", cost_usd=0.05, tokens_total=1000),
            make_span("s2", "llm", cost_usd=0.10, tokens_total=2000),
        ]
        result = analyze_trace(spans)
        assert result.total_tokens == 3000

    def test_agent_breakdown(self):
        spans = [
            make_span("s1", "a", cost_usd=0.05, agent_id="researcher"),
            make_span("s2", "b", cost_usd=0.10, agent_id="writer"),
        ]
        result = analyze_trace(spans)
        assert len(result.agents) == 2

    def test_complex_trace_with_multiple_waste_types(self):
        """Realistic trace with retries, dead-ends, and cascades."""
        base_time = datetime(2025, 1, 15, 10, 0, 0)
        spans = [
            # Root orchestrator
            make_span("root", "orchestrate", cost_usd=0.02, agent_id="orchestrator",
                       start_time=base_time),
            # Researcher agent - success
            make_span("r1", "research", cost_usd=0.10, parent_span_id="root",
                       agent_id="researcher", start_time=base_time + timedelta(seconds=1)),
            # Writer agent - retries
            make_span("w1", "write", cost_usd=0.08, parent_span_id="root",
                       agent_id="writer", attempt_number=1,
                       start_time=base_time + timedelta(seconds=2)),
            make_span("w2", "write", cost_usd=0.08, parent_span_id="root",
                       agent_id="writer", attempt_number=2,
                       start_time=base_time + timedelta(seconds=3)),
            # Reviewer - fails (dead end)
            make_span("rev1", "review", cost_usd=0.12, parent_span_id="root",
                       agent_id="reviewer", status=SpanStatus.ERROR,
                       start_time=base_time + timedelta(seconds=4)),
        ]
        result = analyze_trace(spans)

        assert result.total_cost == pytest.approx(0.40)
        assert result.span_count == 5
        assert len(result.agents) == 4  # orchestrator, researcher, writer, reviewer
        assert result.waste.total_wasted_cost > 0
        assert len(result.decision_trees) == 1
