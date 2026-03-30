"""
Seed script that generates realistic multi-agent trace data.

Creates traces that demonstrate all waste detection capabilities:
- Retry bloat (agent retrying LLM calls)
- Dead-ends (failed research paths)
- Cascade failures (one agent failure propagating)
- Loop detection (agent stuck in reasoning loop)
- Context waste (duplicate document ingestion)

Usage:
    python -m backend.scripts.seed_demo_data
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from backend.core.models import Span, SpanStatus, SpanLink
from backend.storage.database import get_db, init_db
from backend.storage.span_store import SpanStore
from backend.storage.trace_store import TraceStore


def _id():
    return str(uuid.uuid4())[:12]


def _now(offset_seconds=0):
    return datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def generate_healthy_trace() -> list[Span]:
    """
    Trace 1: Healthy multi-agent workflow.
    CrewAI crew: Research -> Write -> Review -> Publish
    Total cost: ~$0.45, no waste.
    """
    trace_id = "trace_healthy_001"
    spans = []

    # Root: Crew kickoff
    root_id = "crew_root"
    spans.append(Span(
        span_id=root_id, trace_id=trace_id, name="crew:market-analysis",
        start_time=_now(0), end_time=_now(30), duration_ms=30000,
        agent_id="orchestrator", agent_name="CrewAI Orchestrator",
        decision_node=True, cost_usd=0.02, model="gpt-4",
        tokens_input=300, tokens_output=100, tokens_total=400,
        status=SpanStatus.SUCCESS, decision_made="execute_all_tasks",
    ))

    # Agent 1: Researcher
    r_id = "researcher_task"
    spans.append(Span(
        span_id=r_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Senior Researcher", start_time=_now(1), end_time=_now(12),
        duration_ms=11000, agent_id="researcher_v1", agent_name="Senior Researcher",
        decision_node=True, cost_usd=0.15, model="gpt-4",
        tokens_input=3000, tokens_output=1500, tokens_total=4500,
        status=SpanStatus.SUCCESS, decision_made="found_3_market_reports",
    ))
    # Researcher LLM call
    spans.append(Span(
        span_id=_id(), trace_id=trace_id, parent_span_id=r_id,
        name="llm:gpt-4", start_time=_now(2), end_time=_now(5),
        duration_ms=3000, model="gpt-4", cost_usd=0.08,
        tokens_input=2000, tokens_output=800, tokens_total=2800,
        status=SpanStatus.SUCCESS,
    ))
    # Researcher tool call
    spans.append(Span(
        span_id=_id(), trace_id=trace_id, parent_span_id=r_id,
        name="tool:web_search", start_time=_now(6), end_time=_now(7),
        duration_ms=1000, status=SpanStatus.SUCCESS,
        metadata={"query": "AI agent market size 2026"},
    ))

    # Agent 2: Writer
    w_id = "writer_task"
    spans.append(Span(
        span_id=w_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Content Writer", start_time=_now(13), end_time=_now(22),
        duration_ms=9000, agent_id="writer_v1", agent_name="Content Writer",
        decision_node=True, cost_usd=0.12, model="gpt-4",
        tokens_input=4000, tokens_output=2000, tokens_total=6000,
        status=SpanStatus.SUCCESS, decision_made="drafted_report",
    ))
    spans.append(Span(
        span_id=_id(), trace_id=trace_id, parent_span_id=w_id,
        name="llm:gpt-4", start_time=_now(14), end_time=_now(20),
        duration_ms=6000, model="gpt-4", cost_usd=0.10,
        tokens_input=3500, tokens_output=1800, tokens_total=5300,
        status=SpanStatus.SUCCESS,
    ))

    # Agent 3: Reviewer
    rev_id = "reviewer_task"
    spans.append(Span(
        span_id=rev_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Quality Reviewer", start_time=_now(23), end_time=_now(28),
        duration_ms=5000, agent_id="reviewer_v1", agent_name="Quality Reviewer",
        decision_node=True, cost_usd=0.08, model="gpt-4",
        tokens_input=2500, tokens_output=500, tokens_total=3000,
        status=SpanStatus.SUCCESS, decision_made="approved",
    ))

    return spans


def generate_retry_bloat_trace() -> list[Span]:
    """
    Trace 2: Agent stuck retrying LLM calls.
    Writer agent retries 4 times due to output validation failure.
    Wasted: ~$0.30 (3 unnecessary retries).
    """
    trace_id = "trace_retry_002"
    spans = []

    root_id = "crew_retry_root"
    spans.append(Span(
        span_id=root_id, trace_id=trace_id, name="crew:content-generation",
        start_time=_now(0), end_time=_now(45), duration_ms=45000,
        agent_id="orchestrator", agent_name="Orchestrator",
        decision_node=True, cost_usd=0.02, model="gpt-4",
        tokens_input=300, tokens_output=100, tokens_total=400,
        status=SpanStatus.SUCCESS,
    ))

    # Writer retries 4 times
    w_id = "writer_retry_task"
    spans.append(Span(
        span_id=w_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Writer", start_time=_now(1), end_time=_now(40),
        duration_ms=39000, agent_id="writer_v2", agent_name="Content Writer",
        decision_node=True, cost_usd=0.02, model="gpt-4",
        tokens_input=500, tokens_output=200, tokens_total=700,
        status=SpanStatus.SUCCESS, decision_made="generated_after_retries",
    ))

    for attempt in range(1, 5):
        status = SpanStatus.ERROR if attempt < 4 else SpanStatus.SUCCESS
        spans.append(Span(
            span_id=f"llm_retry_{attempt}", trace_id=trace_id, parent_span_id=w_id,
            name="llm:gpt-4", start_time=_now(2 + attempt * 8), end_time=_now(8 + attempt * 8),
            duration_ms=6000, model="gpt-4", cost_usd=0.10,
            tokens_input=3000, tokens_output=1500, tokens_total=4500,
            status=status, attempt_number=attempt,
            metadata={"validation_error": "output too short" if attempt < 4 else None},
        ))

    return spans


def generate_cascade_failure_trace() -> list[Span]:
    """
    Trace 3: Cascade failure - planner fails, everything downstream fails.
    Planner validation error -> researcher fails -> writer fails -> reviewer fails.
    Root cause: $0.05 validation error. Blast radius: $0.55 wasted.
    """
    trace_id = "trace_cascade_003"
    spans = []

    root_id = "crew_cascade_root"
    spans.append(Span(
        span_id=root_id, trace_id=trace_id, name="crew:report-pipeline",
        start_time=_now(0), end_time=_now(25), duration_ms=25000,
        agent_id="orchestrator", agent_name="Orchestrator",
        decision_node=True, cost_usd=0.02, model="gpt-4",
        tokens_input=300, tokens_output=100, tokens_total=400,
        status=SpanStatus.ERROR,
    ))

    # Planner fails
    p_id = "planner_fail"
    spans.append(Span(
        span_id=p_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Planner", start_time=_now(1), end_time=_now(5),
        duration_ms=4000, agent_id="planner_v1", agent_name="Task Planner",
        decision_node=True, cost_usd=0.05, model="gpt-4",
        tokens_input=1000, tokens_output=500, tokens_total=1500,
        status=SpanStatus.ERROR, decision_made="failed_validation",
        metadata={"error": "Invalid task decomposition: missing required fields"},
    ))

    # Researcher runs on bad plan, fails
    r_id = "researcher_cascade"
    spans.append(Span(
        span_id=r_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Researcher", start_time=_now(6), end_time=_now(15),
        duration_ms=9000, agent_id="researcher_v1", agent_name="Researcher",
        decision_node=True, cost_usd=0.15, model="gpt-4",
        tokens_input=3000, tokens_output=1000, tokens_total=4000,
        status=SpanStatus.ERROR, triggered_by=p_id,
        metadata={"error": "Research targets undefined due to planner failure"},
    ))
    spans.append(Span(
        span_id=_id(), trace_id=trace_id, parent_span_id=r_id,
        name="llm:gpt-4", start_time=_now(7), end_time=_now(12),
        duration_ms=5000, model="gpt-4", cost_usd=0.10,
        tokens_input=2500, tokens_output=800, tokens_total=3300,
        status=SpanStatus.ERROR,
    ))

    # Writer runs, fails
    w_id = "writer_cascade"
    spans.append(Span(
        span_id=w_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Writer", start_time=_now(16), end_time=_now(22),
        duration_ms=6000, agent_id="writer_v1", agent_name="Writer",
        decision_node=True, cost_usd=0.12, model="gpt-4",
        tokens_input=2000, tokens_output=800, tokens_total=2800,
        status=SpanStatus.ERROR, triggered_by=r_id,
        metadata={"error": "No research data to write from"},
    ))

    # Reviewer runs, fails
    spans.append(Span(
        span_id="reviewer_cascade", trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Reviewer", start_time=_now(23), end_time=_now(25),
        duration_ms=2000, agent_id="reviewer_v1", agent_name="Reviewer",
        decision_node=True, cost_usd=0.08, model="gpt-4",
        tokens_input=1000, tokens_output=200, tokens_total=1200,
        status=SpanStatus.ERROR,
        metadata={"error": "Nothing to review"},
    ))

    return spans


def generate_context_waste_trace() -> list[Span]:
    """
    Trace 4: Context waste - same document re-ingested 3 times.
    Research agent reads the same 30K token document in 3 separate LLM calls.
    Wasted: ~$0.24 (2 redundant ingestions).
    """
    trace_id = "trace_context_004"
    spans = []

    root_id = "crew_context_root"
    spans.append(Span(
        span_id=root_id, trace_id=trace_id, name="crew:document-analysis",
        start_time=_now(0), end_time=_now(35), duration_ms=35000,
        agent_id="orchestrator", agent_name="Orchestrator",
        decision_node=True, cost_usd=0.02, model="gpt-4",
        tokens_input=300, tokens_output=100, tokens_total=400,
        status=SpanStatus.SUCCESS,
    ))

    r_id = "research_context"
    spans.append(Span(
        span_id=r_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Analyst", start_time=_now(1), end_time=_now(30),
        duration_ms=29000, agent_id="analyst_v1", agent_name="Document Analyst",
        decision_node=True, cost_usd=0.02, model="gpt-4",
        tokens_input=500, tokens_output=200, tokens_total=700,
        status=SpanStatus.SUCCESS,
    ))

    # 3 LLM calls all ingesting ~30K tokens (same document)
    for i, task in enumerate(["summarize", "extract_facts", "validate"]):
        spans.append(Span(
            span_id=f"context_{task}", trace_id=trace_id, parent_span_id=r_id,
            name=f"llm:gpt-4:{task}", start_time=_now(3 + i * 8), end_time=_now(9 + i * 8),
            duration_ms=6000, model="gpt-4", cost_usd=0.12,
            tokens_input=30000, tokens_output=2000, tokens_total=32000,
            status=SpanStatus.SUCCESS,
            metadata={"prompt": "Analyze the following quarterly earnings report: " + "x" * 200},
        ))

    return spans


def generate_loop_trace() -> list[Span]:
    """
    Trace 5: Agent stuck in reasoning loop.
    Agent keeps calling "think" -> "search" -> "think" -> "search" pattern.
    4 repetitions, should have stopped after 1.
    """
    trace_id = "trace_loop_005"
    spans = []

    root_id = "crew_loop_root"
    spans.append(Span(
        span_id=root_id, trace_id=trace_id, name="crew:qa-pipeline",
        start_time=_now(0), end_time=_now(50), duration_ms=50000,
        agent_id="orchestrator", agent_name="Orchestrator",
        decision_node=True, cost_usd=0.02, model="gpt-4",
        tokens_input=300, tokens_output=100, tokens_total=400,
        status=SpanStatus.SUCCESS,
    ))

    agent_id = "qa_agent_v1"
    task_id = "qa_task"
    spans.append(Span(
        span_id=task_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:QA Agent", start_time=_now(1), end_time=_now(45),
        duration_ms=44000, agent_id=agent_id, agent_name="QA Agent",
        decision_node=True, cost_usd=0.02, model="gpt-4",
        tokens_input=500, tokens_output=200, tokens_total=700,
        status=SpanStatus.SUCCESS,
    ))

    # Repeated think-search pattern 4 times
    t = 2
    for iteration in range(4):
        think_id = f"think_{iteration}"
        spans.append(Span(
            span_id=think_id, trace_id=trace_id, parent_span_id=task_id,
            name="llm:gpt-4:think", start_time=_now(t), end_time=_now(t + 3),
            duration_ms=3000, model="gpt-4", cost_usd=0.06,
            tokens_input=2000, tokens_output=500, tokens_total=2500,
            agent_id=agent_id, status=SpanStatus.SUCCESS,
        ))
        t += 4
        search_id = f"search_{iteration}"
        spans.append(Span(
            span_id=search_id, trace_id=trace_id, parent_span_id=task_id,
            name="tool:web_search", start_time=_now(t), end_time=_now(t + 2),
            duration_ms=2000, agent_id=agent_id, status=SpanStatus.SUCCESS,
            cost_usd=0.02,
        ))
        t += 3

    return spans


def generate_mixed_trace() -> list[Span]:
    """
    Trace 6: Complex trace with multiple waste types.
    Retries + dead-end + some healthy work. Realistic production scenario.
    """
    trace_id = "trace_mixed_006"
    spans = []

    root_id = "crew_mixed_root"
    spans.append(Span(
        span_id=root_id, trace_id=trace_id, name="crew:customer-onboarding",
        start_time=_now(0), end_time=_now(60), duration_ms=60000,
        agent_id="orchestrator", agent_name="Orchestrator",
        decision_node=True, cost_usd=0.03, model="gpt-4o",
        tokens_input=400, tokens_output=150, tokens_total=550,
        status=SpanStatus.SUCCESS,
    ))

    # Healthy: Data collector agent
    dc_id = "data_collector"
    spans.append(Span(
        span_id=dc_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Data Collector", start_time=_now(1), end_time=_now(15),
        duration_ms=14000, agent_id="data_collector_v1", agent_name="Data Collector",
        decision_node=True, cost_usd=0.08, model="gpt-4o",
        tokens_input=2000, tokens_output=1000, tokens_total=3000,
        status=SpanStatus.SUCCESS,
    ))
    spans.append(Span(
        span_id=_id(), trace_id=trace_id, parent_span_id=dc_id,
        name="tool:crm_lookup", start_time=_now(3), end_time=_now(4),
        duration_ms=1000, status=SpanStatus.SUCCESS,
    ))

    # Dead-end: Verification agent fails after spending money
    v_id = "verification_deadend"
    spans.append(Span(
        span_id=v_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Verification Agent", start_time=_now(16), end_time=_now(28),
        duration_ms=12000, agent_id="verifier_v1", agent_name="Identity Verifier",
        decision_node=True, cost_usd=0.15, model="gpt-4o",
        tokens_input=5000, tokens_output=1500, tokens_total=6500,
        status=SpanStatus.ERROR, decision_made="verification_failed",
        metadata={"error": "Third-party API returned 503"},
    ))
    spans.append(Span(
        span_id=_id(), trace_id=trace_id, parent_span_id=v_id,
        name="tool:id_verify_api", start_time=_now(18), end_time=_now(20),
        duration_ms=2000, status=SpanStatus.ERROR, cost_usd=0.02,
        metadata={"error": "503 Service Unavailable"},
    ))

    # Retry: Email agent retries 3 times
    e_id = "email_retry_task"
    spans.append(Span(
        span_id=e_id, trace_id=trace_id, parent_span_id=root_id,
        name="agent_task:Email Composer", start_time=_now(30), end_time=_now(55),
        duration_ms=25000, agent_id="email_v1", agent_name="Email Composer",
        decision_node=True, cost_usd=0.02, model="gpt-4o",
        tokens_input=400, tokens_output=150, tokens_total=550,
        status=SpanStatus.SUCCESS,
    ))
    for attempt in range(1, 4):
        status = SpanStatus.ERROR if attempt < 3 else SpanStatus.SUCCESS
        spans.append(Span(
            span_id=f"email_llm_{attempt}", trace_id=trace_id, parent_span_id=e_id,
            name="llm:gpt-4o", start_time=_now(31 + attempt * 7),
            end_time=_now(36 + attempt * 7),
            duration_ms=5000, model="gpt-4o", cost_usd=0.07,
            tokens_input=2500, tokens_output=1000, tokens_total=3500,
            status=status, attempt_number=attempt,
        ))

    return spans


async def seed():
    """Insert all demo traces."""
    await init_db()

    generators = [
        ("Healthy workflow", generate_healthy_trace),
        ("Retry bloat", generate_retry_bloat_trace),
        ("Cascade failure", generate_cascade_failure_trace),
        ("Context waste", generate_context_waste_trace),
        ("Loop detection", generate_loop_trace),
        ("Mixed waste", generate_mixed_trace),
    ]

    async for session in get_db():
        span_store = SpanStore(session)
        trace_store = TraceStore(session)

        for name, generator in generators:
            spans = generator()
            await span_store.save_spans(spans)
            await trace_store.upsert_trace_from_spans(spans)
            trace_id = spans[0].trace_id
            total_cost = sum(s.cost_usd or 0.0 for s in spans)
            print(f"  Seeded: {name} ({trace_id}) - ${total_cost:.2f}, {len(spans)} spans")

        print(f"\nDone! Seeded {len(generators)} traces.")


if __name__ == "__main__":
    asyncio.run(seed())
