"""
Span ingestion and retrieval endpoints.

Receives spans from instrumented applications and stores them for analysis.
Auto-aggregates trace records on ingest.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from pydantic import BaseModel

from backend.core.models import Span
from backend.storage.database import get_db
from backend.storage.span_store import SpanStore
from backend.storage.trace_store import TraceStore

router = APIRouter(prefix="/api/spans", tags=["spans"])


class SpanIngestRequest(BaseModel):
    """Request model for span ingestion (simplified OTLP-compatible format)."""

    spans: List[Span]


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_spans(
    request: SpanIngestRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Ingest spans from instrumented applications.

    Saves spans and auto-aggregates trace records.
    """
    span_store = SpanStore(db)
    trace_store = TraceStore(db)

    try:
        await span_store.save_spans(request.spans)

        # Auto-aggregate trace records for each unique trace
        trace_ids = set(s.trace_id for s in request.spans)
        for trace_id in trace_ids:
            all_spans = await span_store.get_spans_by_trace(trace_id)
            await trace_store.upsert_trace_from_spans(all_spans)

        return {
            "status": "success",
            "spans_ingested": len(request.spans),
            "traces": list(trace_ids),
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest spans: {str(e)}"
        )


@router.get("/{span_id}")
async def get_span(
    span_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve a single span by ID."""
    store = SpanStore(db)
    span = await store.get_span(span_id)

    if span is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Span {span_id} not found"
        )

    return span


@router.get("/trace/{trace_id}")
async def get_trace_spans(
    trace_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get all spans for a trace, sorted by start time."""
    store = SpanStore(db)
    spans = await store.get_spans_by_trace(trace_id)

    return {
        "trace_id": trace_id,
        "span_count": len(spans),
        "spans": spans
    }
