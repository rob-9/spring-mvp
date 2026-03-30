"""
Trace persistence and query layer.

Manages aggregated trace records and provides query methods
for the dashboard API.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, func, desc, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.models import Span, SpanStatus, Trace
from backend.storage.models import TraceModel, SpanModel


class TraceStore:
    """Interface for trace storage and querying."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_trace_from_spans(self, spans: List[Span]) -> None:
        """
        Create or update a trace record from its spans.

        Aggregates cost, tokens, timing, and status from all spans.
        """
        if not spans:
            return

        trace_id = spans[0].trace_id
        total_cost = sum(s.cost_usd or 0.0 for s in spans)
        total_tokens = sum(s.tokens_total or 0 for s in spans)
        start_times = [s.start_time for s in spans]
        end_times = [s.end_time for s in spans if s.end_time]

        statuses = {s.status for s in spans}
        if SpanStatus.ERROR in statuses:
            status = "error"
        elif SpanStatus.RUNNING in statuses:
            status = "running"
        else:
            status = "success"

        start_time = min(start_times)
        end_time = max(end_times) if end_times else None
        duration_ms = None
        if end_time:
            duration_ms = (end_time - start_time).total_seconds() * 1000

        # Determine outcome from root spans
        root_spans = [s for s in spans if s.parent_span_id is None]
        outcome = None
        if root_spans:
            root_statuses = {s.status for s in root_spans}
            if SpanStatus.ERROR in root_statuses:
                outcome = "failure"
            elif all(s.status == SpanStatus.SUCCESS for s in root_spans):
                outcome = "success"

        # Collect agent info for metadata
        agents = list({s.agent_id for s in spans if s.agent_id})

        trace_model = TraceModel(
            trace_id=trace_id,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            total_cost_usd=total_cost,
            total_tokens=total_tokens,
            span_count=len(spans),
            status=status,
            outcome=outcome,
            trace_metadata={"agents": agents},
        )

        await self.session.merge(trace_model)
        await self.session.commit()

    async def get_trace(self, trace_id: str) -> Optional[Trace]:
        """Retrieve a trace by ID."""
        result = await self.session.execute(
            select(TraceModel).where(TraceModel.trace_id == trace_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_pydantic(model)

    async def list_traces(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        min_cost: Optional[float] = None,
        sort_by: str = "start_time",
        sort_order: str = "desc",
    ) -> List[Trace]:
        """
        List traces with optional filtering and sorting.

        Args:
            limit: Max results to return
            offset: Pagination offset
            status: Filter by trace status
            min_cost: Filter traces above this cost
            sort_by: Field to sort by (start_time, total_cost_usd, duration_ms)
            sort_order: Sort direction (asc, desc)
        """
        query = select(TraceModel)

        if status:
            query = query.where(TraceModel.status == status)
        if min_cost is not None:
            query = query.where(TraceModel.total_cost_usd >= min_cost)

        # Sort
        sort_column = getattr(TraceModel, sort_by, TraceModel.start_time)
        if sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(sort_column)

        query = query.offset(offset).limit(limit)

        result = await self.session.execute(query)
        models = result.scalars().all()
        return [self._to_pydantic(m) for m in models]

    async def get_trace_count(self, status: Optional[str] = None) -> int:
        """Get total trace count with optional status filter."""
        query = select(func.count(TraceModel.trace_id))
        if status:
            query = query.where(TraceModel.status == status)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def get_cost_summary(
        self, since: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get aggregate cost statistics.

        Args:
            since: Only include traces after this time
        """
        query = select(
            func.count(TraceModel.trace_id).label("trace_count"),
            func.coalesce(func.sum(TraceModel.total_cost_usd), 0.0).label("total_cost"),
            func.coalesce(func.avg(TraceModel.total_cost_usd), 0.0).label("avg_cost"),
            func.coalesce(func.max(TraceModel.total_cost_usd), 0.0).label("max_cost"),
            func.coalesce(func.sum(TraceModel.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(TraceModel.span_count), 0).label("total_spans"),
        )

        if since:
            query = query.where(TraceModel.start_time >= since)

        result = await self.session.execute(query)
        row = result.one()

        return {
            "trace_count": row.trace_count,
            "total_cost": float(row.total_cost),
            "avg_cost_per_trace": float(row.avg_cost),
            "max_trace_cost": float(row.max_cost),
            "total_tokens": int(row.total_tokens),
            "total_spans": int(row.total_spans),
        }

    async def get_agent_stats(
        self, agent_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get per-agent performance statistics from span data.

        Args:
            agent_id: Optional filter to a specific agent
        """
        query = select(
            SpanModel.agent_id,
            SpanModel.agent_name,
            func.count(SpanModel.span_id).label("span_count"),
            func.coalesce(func.sum(SpanModel.cost_usd), 0.0).label("total_cost"),
            func.coalesce(func.avg(SpanModel.cost_usd), 0.0).label("avg_cost"),
            func.coalesce(func.sum(SpanModel.tokens_total), 0).label("total_tokens"),
            func.coalesce(func.avg(SpanModel.duration_ms), 0.0).label("avg_duration_ms"),
            func.sum(
                case((SpanModel.status == "error", 1), else_=0)
            ).label("error_count"),
            func.count(func.distinct(SpanModel.trace_id)).label("trace_count"),
        ).where(
            SpanModel.agent_id.isnot(None)
        ).group_by(
            SpanModel.agent_id, SpanModel.agent_name
        ).order_by(
            desc("total_cost")
        )

        if agent_id:
            query = query.where(SpanModel.agent_id == agent_id)

        result = await self.session.execute(query)
        rows = result.all()

        return [
            {
                "agent_id": row.agent_id,
                "agent_name": row.agent_name,
                "span_count": row.span_count,
                "total_cost": float(row.total_cost),
                "avg_cost_per_span": float(row.avg_cost),
                "total_tokens": int(row.total_tokens),
                "avg_duration_ms": float(row.avg_duration_ms),
                "error_count": int(row.error_count),
                "error_rate": round(int(row.error_count) / row.span_count * 100, 2) if row.span_count > 0 else 0.0,
                "trace_count": row.trace_count,
            }
            for row in rows
        ]

    async def get_cost_timeseries(
        self,
        since: Optional[datetime] = None,
        bucket_hours: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Get cost aggregated into time buckets for trend charts.

        Args:
            since: Start time (defaults to 24h ago)
            bucket_hours: Size of each time bucket in hours
        """
        if since is None:
            since = datetime.utcnow() - timedelta(hours=24)

        # Use date_trunc for bucketing
        query = select(
            func.date_trunc("hour", TraceModel.start_time).label("bucket"),
            func.count(TraceModel.trace_id).label("trace_count"),
            func.coalesce(func.sum(TraceModel.total_cost_usd), 0.0).label("total_cost"),
            func.coalesce(func.sum(TraceModel.total_tokens), 0).label("total_tokens"),
            func.sum(
                case((TraceModel.status == "error", 1), else_=0)
            ).label("error_count"),
        ).where(
            TraceModel.start_time >= since
        ).group_by("bucket").order_by("bucket")

        result = await self.session.execute(query)
        rows = result.all()

        return [
            {
                "timestamp": row.bucket.isoformat() if row.bucket else None,
                "trace_count": row.trace_count,
                "total_cost": float(row.total_cost),
                "total_tokens": int(row.total_tokens),
                "error_count": int(row.error_count),
            }
            for row in rows
        ]

    def _to_pydantic(self, model: TraceModel) -> Trace:
        """Convert SQLAlchemy model to Pydantic model."""
        return Trace(
            trace_id=model.trace_id,
            start_time=model.start_time,
            end_time=model.end_time,
            duration_ms=model.duration_ms,
            total_cost_usd=model.total_cost_usd or 0.0,
            total_tokens=model.total_tokens or 0,
            span_count=model.span_count or 0,
            status=SpanStatus(model.status) if model.status in SpanStatus.__members__.values() else SpanStatus.RUNNING,
            outcome=model.outcome,
            metadata=model.trace_metadata or {},
        )
