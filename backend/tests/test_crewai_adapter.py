"""
Tests for CrewAI auto-instrumentation adapter.
"""

import pytest
from datetime import datetime, timezone
from backend.core.models import SpanStatus
from backend.instrumentation.crewai_adapter import CrewAIInstrumentor


@pytest.fixture
def instrumentor():
    return CrewAIInstrumentor(service_name="test-crewai")


class TestCrewAIInstrumentor:
    def test_crew_lifecycle(self, instrumentor):
        """Test full crew start -> agent tasks -> end lifecycle."""
        crew_id = instrumentor.on_crew_start("research-crew")
        assert crew_id is not None

        # Start an agent task
        task_id = instrumentor.on_agent_task_start(
            agent_name="researcher",
            agent_role="Senior Researcher",
            task_description="Research quantum computing advances",
            parent_span_id=crew_id,
        )
        assert task_id is not None

        # Record an LLM call within the task
        llm_span = instrumentor.on_llm_call(
            model="gpt-4",
            parent_span_id=task_id,
            tokens_input=500,
            tokens_output=200,
            cost_usd=0.05,
        )
        assert llm_span.model == "gpt-4"
        assert llm_span.tokens_input == 500
        assert llm_span.cost_usd == 0.05

        # Record a tool call
        tool_span = instrumentor.on_tool_call(
            tool_name="web_search",
            parent_span_id=task_id,
            duration_ms=150.0,
        )
        assert tool_span.name == "tool:web_search"

        # End agent task
        task_span = instrumentor.on_agent_task_end(
            task_id, status="success", decision_made="found 3 relevant papers"
        )
        assert task_span is not None
        assert task_span.decision_made == "found 3 relevant papers"

        # End crew
        crew_span = instrumentor.on_crew_end(crew_id)
        assert crew_span is not None
        assert crew_span.name == "crew:research-crew"

        # Check collected spans
        spans = instrumentor.get_collected_spans()
        assert len(spans) == 4  # llm + tool + task + crew

    def test_trace_id_propagation(self, instrumentor):
        """Child spans inherit trace_id from parent."""
        crew_id = instrumentor.on_crew_start("test-crew")
        task_id = instrumentor.on_agent_task_start(
            agent_name="agent1",
            agent_role="Worker",
            task_description="Do work",
            parent_span_id=crew_id,
        )

        llm_span = instrumentor.on_llm_call(
            model="gpt-4",
            parent_span_id=task_id,
            cost_usd=0.01,
        )

        # All should share the same trace_id
        crew_trace = instrumentor._active_spans.get(crew_id, {}).get("trace_id")
        assert llm_span.trace_id == crew_trace

    def test_flush_clears_state(self, instrumentor):
        crew_id = instrumentor.on_crew_start("test")
        instrumentor.on_crew_end(crew_id)

        spans = instrumentor.flush()
        assert len(spans) == 1

        # After flush, state is clean
        assert instrumentor.get_collected_spans() == []
        assert instrumentor._active_spans == {}

    def test_on_crew_end_unknown_id(self, instrumentor):
        result = instrumentor.on_crew_end("nonexistent")
        assert result is None

    def test_agent_metadata(self, instrumentor):
        crew_id = instrumentor.on_crew_start("crew")
        task_id = instrumentor.on_agent_task_start(
            agent_name="agent_001",
            agent_role="Data Analyst",
            task_description="Analyze quarterly sales data for trends",
            parent_span_id=crew_id,
        )
        task_span = instrumentor.on_agent_task_end(task_id, status="success")

        assert task_span.agent_id == "agent_001"
        assert task_span.agent_name == "Data Analyst"
        assert task_span.decision_node is True
        assert "task" in task_span.metadata

    def test_tool_call_status(self, instrumentor):
        crew_id = instrumentor.on_crew_start("crew")
        tool_span = instrumentor.on_tool_call(
            tool_name="calculator",
            parent_span_id=crew_id,
            status="error",
            metadata={"error": "division by zero"},
        )
        assert tool_span.status == SpanStatus.ERROR
        assert tool_span.metadata["error"] == "division by zero"

    def test_llm_token_totals(self, instrumentor):
        crew_id = instrumentor.on_crew_start("crew")
        llm_span = instrumentor.on_llm_call(
            model="claude-3-opus",
            parent_span_id=crew_id,
            tokens_input=1000,
            tokens_output=500,
            cost_usd=0.08,
        )
        assert llm_span.tokens_total == 1500

    def test_multiple_agent_tasks(self, instrumentor):
        crew_id = instrumentor.on_crew_start("multi-agent")

        task1_id = instrumentor.on_agent_task_start(
            "agent_a", "Researcher", "Research", parent_span_id=crew_id
        )
        instrumentor.on_llm_call("gpt-4", task1_id, cost_usd=0.05)
        instrumentor.on_agent_task_end(task1_id)

        task2_id = instrumentor.on_agent_task_start(
            "agent_b", "Writer", "Write", parent_span_id=crew_id
        )
        instrumentor.on_llm_call("gpt-4", task2_id, cost_usd=0.08)
        instrumentor.on_agent_task_end(task2_id)

        instrumentor.on_crew_end(crew_id)

        spans = instrumentor.get_collected_spans()
        assert len(spans) == 5  # 2 llm + 2 tasks + 1 crew

        agent_ids = {s.agent_id for s in spans if s.agent_id}
        assert "agent_a" in agent_ids
        assert "agent_b" in agent_ids
