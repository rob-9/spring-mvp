"""
Trace analysis and listing endpoints.

Provides trace-level views, cost attribution trees, and waste analysis.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from backend.storage.database import get_db
from backend.storage.span_store import SpanStore
from backend.storage.trace_store import TraceStore
from backend.analysis.trace_analyzer import analyze_trace
from backend.analysis.decision_path import calculate_trace_cost_tree

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("")
async def list_traces(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    min_cost: Optional[float] = Query(default=None, ge=0),
    sort_by: str = Query(default="start_time"),
    sort_order: str = Query(default="desc"),
    db: AsyncSession = Depends(get_db),
):
    """
    List traces with pagination, filtering, and sorting.

    Returns summary info for each trace (not full span data).
    """
    store = TraceStore(db)

    traces = await store.list_traces(
        limit=limit,
        offset=offset,
        status=status_filter,
        min_cost=min_cost,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = await store.get_trace_count(status=status_filter)

    return {
        "traces": traces,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{trace_id}")
async def get_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get trace summary by ID."""
    store = TraceStore(db)
    trace = await store.get_trace(trace_id)

    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace {trace_id} not found"
        )

    return trace


@router.get("/{trace_id}/analysis")
async def get_trace_analysis(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Full trace analysis: cost attribution trees + waste detection.

    This is the core product endpoint. Returns:
    - Decision-level cost trees (recursive aggregation)
    - Waste breakdown (retry bloat, loops, dead-ends, cascades, context waste)
    - Per-agent performance summary
    """
    span_store = SpanStore(db)
    spans = await span_store.get_spans_by_trace(trace_id)

    if not spans:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No spans found for trace {trace_id}"
        )

    analysis = analyze_trace(spans)
    return analysis


@router.get("/{trace_id}/tree")
async def get_decision_tree(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the decision cost tree for visualization.

    Returns a hierarchical tree structure showing cost attribution
    from root decisions through all downstream work.
    """
    span_store = SpanStore(db)
    spans = await span_store.get_spans_by_trace(trace_id)

    if not spans:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No spans found for trace {trace_id}"
        )

    trees = calculate_trace_cost_tree(spans)

    total_cost = sum(t.total_cost for t in trees)
    total_waste = sum(
        w.get("wasted_cost", 0.0)
        for t in trees
        for w in t.waste_detected
    )

    return {
        "trace_id": trace_id,
        "total_cost": total_cost,
        "total_waste": total_waste,
        "trees": trees,
    }
