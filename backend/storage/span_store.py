"""
Span persistence layer.

Stores spans to PostgreSQL for later analysis.
"""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.models import Span, SpanStatus, SpanLink
from .models import SpanModel
from datetime import datetime


class SpanStore:
    """
    Interface for span storage operations.

    Handles conversion between Pydantic models and SQLAlchemy models.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_span(self, span: Span) -> None:
        """
        Save a span to database.

        Args:
            span: Pydantic Span model to persist
        """
        # convert pydantic model to sqlalchemy model
        span_model = SpanModel(
            span_id=span.span_id,
            trace_id=span.trace_id,
            parent_span_id=span.parent_span_id,
            name=span.name,
            start_time=span.start_time,
            end_time=span.end_time,
            duration_ms=span.duration_ms,
            agent_id=span.agent_id,
            agent_name=span.agent_name,
            decision_node=span.decision_node,
            triggered_by=span.triggered_by,
            cost_usd=span.cost_usd,
            tokens_input=span.tokens_input,
            tokens_output=span.tokens_output,
            tokens_total=span.tokens_total,
            model=span.model,
            status=span.status.value,
            attempt_number=span.attempt_number,
            decision_made=span.decision_made,
            links=[
                {
                    "trace_id": link.trace_id,
                    "span_id": link.span_id,
                    "link_type": link.link_type,
                    "attributes": link.attributes,
                }
                for link in span.links
            ] if span.links else None,
            span_metadata=span.metadata,
        )

        # upsert (insert or update if exists)
        await self.session.merge(span_model)
        await self.session.commit()

    async def save_spans(self, spans: List[Span]) -> None:
        """
        Batch save multiple spans.

        More efficient than calling save_span multiple times.

        Args:
            spans: List of spans to persist
        """
        span_models = [
            SpanModel(
                span_id=s.span_id,
                trace_id=s.trace_id,
                parent_span_id=s.parent_span_id,
                name=s.name,
                start_time=s.start_time,
                end_time=s.end_time,
                duration_ms=s.duration_ms,
                agent_id=s.agent_id,
                agent_name=s.agent_name,
                decision_node=s.decision_node,
                triggered_by=s.triggered_by,
                cost_usd=s.cost_usd,
                tokens_input=s.tokens_input,
                tokens_output=s.tokens_output,
                tokens_total=s.tokens_total,
                model=s.model,
                status=s.status.value,
                attempt_number=s.attempt_number,
                decision_made=s.decision_made,
                links=[
                    {
                        "trace_id": link.trace_id,
                        "span_id": link.span_id,
                        "link_type": link.link_type,
                        "attributes": link.attributes,
                    }
                    for link in s.links
                ] if s.links else None,
                metadata=s.metadata,
            )
            for s in spans
        ]

        for model in span_models:
            await self.session.merge(model)

        await self.session.commit()

    async def get_span(self, span_id: str) -> Optional[Span]:
        """
        Retrieve a span by ID.

        Args:
            span_id: Unique span identifier

        Returns:
            Span if found, None otherwise
        """
        result = await self.session.execute(
            select(SpanModel).where(SpanModel.span_id == span_id)
        )
        span_model = result.scalar_one_or_none()

        if span_model is None:
            return None

        return self._to_pydantic(span_model)

    async def get_spans_by_trace(self, trace_id: str) -> List[Span]:
        """
        Get all spans for a trace, sorted by start time.

        Args:
            trace_id: Trace identifier

        Returns:
            List of spans in the trace
        """
        result = await self.session.execute(
            select(SpanModel)
            .where(SpanModel.trace_id == trace_id)
            .order_by(SpanModel.start_time)
        )
        span_models = result.scalars().all()

        return [self._to_pydantic(sm) for sm in span_models]

    async def get_children(self, span_id: str) -> List[Span]:
        """
        Get all child spans of a given span.

        Args:
            span_id: Parent span identifier

        Returns:
            List of child spans
        """
        result = await self.session.execute(
            select(SpanModel)
            .where(SpanModel.parent_span_id == span_id)
            .order_by(SpanModel.start_time)
        )
        span_models = result.scalars().all()

        return [self._to_pydantic(sm) for sm in span_models]

    async def get_root_spans(self, trace_id: str) -> List[Span]:
        """
        Get root spans (no parent) for a trace.

        Args:
            trace_id: Trace identifier

        Returns:
            List of root spans
        """
        result = await self.session.execute(
            select(SpanModel)
            .where(SpanModel.trace_id == trace_id)
            .where(SpanModel.parent_span_id.is_(None))
            .order_by(SpanModel.start_time)
        )
        span_models = result.scalars().all()

        return [self._to_pydantic(sm) for sm in span_models]

    def _to_pydantic(self, span_model: SpanModel) -> Span:
        """
        Convert SQLAlchemy model to Pydantic model.

        Args:
            span_model: Database model

        Returns:
            Pydantic Span model
        """
        # convert links from json to SpanLink objects
        links = []
        if span_model.links:
            for link_data in span_model.links:
                links.append(
                    SpanLink(
                        trace_id=link_data["trace_id"],
                        span_id=link_data["span_id"],
                        link_type=link_data.get("link_type"),
                        attributes=link_data.get("attributes", {}),
                    )
                )

        return Span(
            span_id=span_model.span_id,
            trace_id=span_model.trace_id,
            parent_span_id=span_model.parent_span_id,
            name=span_model.name,
            start_time=span_model.start_time,
            end_time=span_model.end_time,
            duration_ms=span_model.duration_ms,
            agent_id=span_model.agent_id,
            agent_name=span_model.agent_name,
            decision_node=span_model.decision_node,
            triggered_by=span_model.triggered_by,
            cost_usd=span_model.cost_usd,
            tokens_input=span_model.tokens_input,
            tokens_output=span_model.tokens_output,
            tokens_total=span_model.tokens_total,
            model=span_model.model,
            status=SpanStatus(span_model.status),
            attempt_number=span_model.attempt_number,
            decision_made=span_model.decision_made,
            links=links,
            metadata=span_model.span_metadata or {},
        )
