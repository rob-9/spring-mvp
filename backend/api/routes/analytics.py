"""
Analytics and dashboard endpoints.

Aggregate views for the dashboard: cost trends, agent performance,
waste summaries across all traces.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timedelta

from backend.storage.database import get_db
from backend.storage.trace_store import TraceStore
from backend.storage.span_store import SpanStore
from backend.analysis.trace_analyzer import analyze_trace

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview")
async def get_overview(
    hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    """
    Dashboard overview: key metrics for the time period.

    Returns total cost, trace count, error rate, and top-level stats.
    """
    trace_store = TraceStore(db)
    since = datetime.utcnow() - timedelta(hours=hours)

    cost_summary = await trace_store.get_cost_summary(since=since)
    total_traces = cost_summary["trace_count"]

    # Error rate
    error_count = await trace_store.get_trace_count(status="error")
    error_rate = round(error_count / total_traces * 100, 2) if total_traces > 0 else 0.0

    return {
        "period_hours": hours,
        **cost_summary,
        "error_count": error_count,
        "error_rate": error_rate,
    }


@router.get("/agents")
async def get_agent_stats(
    agent_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Per-agent performance statistics.

    Shows cost, error rate, token usage, and span count for each agent.
    """
    trace_store = TraceStore(db)
    stats = await trace_store.get_agent_stats(agent_id=agent_id)
    return {"agents": stats}


@router.get("/cost-trends")
async def get_cost_trends(
    hours: int = Query(default=24, ge=1, le=720),
    bucket_hours: int = Query(default=1, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
):
    """
    Cost over time for trend charts.

    Returns time-bucketed cost, token, and error data.
    """
    trace_store = TraceStore(db)
    since = datetime.utcnow() - timedelta(hours=hours)

    timeseries = await trace_store.get_cost_timeseries(
        since=since, bucket_hours=bucket_hours
    )

    return {
        "period_hours": hours,
        "bucket_hours": bucket_hours,
        "data": timeseries,
    }


@router.get("/waste-summary")
async def get_waste_summary(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate waste analysis across recent traces.

    Finds the most wasteful traces and provides a breakdown by waste type.
    Inspired by Foam's approach: show actionable insights, not just raw data.
    """
    trace_store = TraceStore(db)
    span_store = SpanStore(db)

    # Get recent traces sorted by cost (most expensive first)
    traces = await trace_store.list_traces(
        limit=limit, sort_by="total_cost_usd", sort_order="desc"
    )

    results = []
    total_waste = 0.0
    total_cost = 0.0
    waste_by_type = {}

    for trace in traces:
        spans = await span_store.get_spans_by_trace(trace.trace_id)
        if not spans:
            continue

        analysis = analyze_trace(spans)

        total_waste += analysis.waste.total_wasted_cost
        total_cost += analysis.total_cost

        for waste_type, amount in analysis.waste.by_type.items():
            waste_by_type[waste_type] = waste_by_type.get(waste_type, 0.0) + amount

        if analysis.waste.total_wasted_cost > 0:
            results.append({
                "trace_id": trace.trace_id,
                "total_cost": analysis.total_cost,
                "wasted_cost": analysis.waste.total_wasted_cost,
                "waste_percentage": analysis.waste.waste_percentage,
                "top_waste_type": max(
                    analysis.waste.by_type, key=analysis.waste.by_type.get
                ) if analysis.waste.by_type else None,
                "detection_count": len(analysis.waste.detections),
            })

    waste_pct = round(total_waste / total_cost * 100, 2) if total_cost > 0 else 0.0

    return {
        "total_cost_analyzed": total_cost,
        "total_waste_detected": total_waste,
        "overall_waste_percentage": waste_pct,
        "waste_by_type": waste_by_type,
        "wasteful_traces": results,
    }
