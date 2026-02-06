"""
Span ingestion endpoints.

Receives spans from instrumented applications and stores them for analysis.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from pydantic import BaseModel

from backend.core.models import Span
from backend.storage.database import get_db
from backend.storage.span_store import SpanStore

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

    This endpoint receives spans in our simplified format. In production,
    this would parse full OTLP protobuf format.

    Args:
        request: Batch of spans to ingest
        db: Database session

    Returns:
        Success response with count of ingested spans
    """
    store = SpanStore(db)

    try:
        await store.save_spans(request.spans)

        return {
            "status": "success",
            "spans_ingested": len(request.spans),
            "traces": list(set(s.trace_id for s in request.spans))
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
    """
    Retrieve a single span by ID.

    Args:
        span_id: Unique span identifier
        db: Database session

    Returns:
        Span object if found

    Raises:
        404 if span not found
    """
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
    """
    Get all spans for a trace.

    Args:
        trace_id: Trace identifier
        db: Database session

    Returns:
        List of spans in the trace, sorted by start time
    """
    store = SpanStore(db)
    spans = await store.get_spans_by_trace(trace_id)

    return {
        "trace_id": trace_id,
        "span_count": len(spans),
        "spans": spans
    }
