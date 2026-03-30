"""
API integration tests.

Tests the FastAPI endpoints using TestClient with an in-memory SQLite database.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from datetime import datetime

from backend.api.app import app
from backend.storage.database import Base, get_db


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true"


@pytest_asyncio.fixture
async def test_db():
    """Create a test database and provide session factory."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    yield session_factory

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db):
    """Async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_spans():
    """Sample span data for testing."""
    return {
        "spans": [
            {
                "span_id": "span_001",
                "trace_id": "trace_001",
                "name": "orchestrate",
                "start_time": "2025-01-15T10:00:00",
                "end_time": "2025-01-15T10:00:10",
                "duration_ms": 10000,
                "agent_id": "orchestrator",
                "agent_name": "Orchestrator Agent",
                "decision_node": True,
                "cost_usd": 0.02,
                "tokens_input": 500,
                "tokens_output": 200,
                "tokens_total": 700,
                "model": "gpt-4",
                "status": "success",
            },
            {
                "span_id": "span_002",
                "trace_id": "trace_001",
                "parent_span_id": "span_001",
                "name": "research",
                "start_time": "2025-01-15T10:00:01",
                "end_time": "2025-01-15T10:00:05",
                "duration_ms": 4000,
                "agent_id": "researcher",
                "agent_name": "Research Agent",
                "cost_usd": 0.10,
                "tokens_input": 2000,
                "tokens_output": 800,
                "tokens_total": 2800,
                "model": "gpt-4",
                "status": "success",
            },
            {
                "span_id": "span_003",
                "trace_id": "trace_001",
                "parent_span_id": "span_001",
                "name": "write_report",
                "start_time": "2025-01-15T10:00:05",
                "end_time": "2025-01-15T10:00:09",
                "duration_ms": 4000,
                "agent_id": "writer",
                "agent_name": "Writer Agent",
                "cost_usd": 0.08,
                "tokens_input": 1500,
                "tokens_output": 1000,
                "tokens_total": 2500,
                "model": "gpt-4",
                "status": "success",
            },
        ]
    }


@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_check(self, client, test_db):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
class TestSpanIngestion:
    async def test_ingest_spans(self, client, test_db, sample_spans):
        response = await client.post("/api/spans/ingest", json=sample_spans)
        assert response.status_code == 201
        data = response.json()
        assert data["spans_ingested"] == 3
        assert "trace_001" in data["traces"]

    async def test_get_span(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/spans/span_001")
        assert response.status_code == 200
        data = response.json()
        assert data["span_id"] == "span_001"
        assert data["name"] == "orchestrate"

    async def test_get_span_not_found(self, client, test_db):
        response = await client.get("/api/spans/nonexistent")
        assert response.status_code == 404

    async def test_get_trace_spans(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/spans/trace/trace_001")
        assert response.status_code == 200
        data = response.json()
        assert data["trace_id"] == "trace_001"
        assert data["span_count"] == 3


@pytest.mark.asyncio
class TestTraceEndpoints:
    async def test_list_traces(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/traces")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["traces"]) >= 1

    async def test_get_trace(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/traces/trace_001")
        assert response.status_code == 200
        data = response.json()
        assert data["trace_id"] == "trace_001"

    async def test_get_trace_not_found(self, client, test_db):
        response = await client.get("/api/traces/nonexistent")
        assert response.status_code == 404

    async def test_trace_analysis(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/traces/trace_001/analysis")
        assert response.status_code == 200
        data = response.json()

        assert data["trace_id"] == "trace_001"
        assert data["span_count"] == 3
        assert data["total_cost"] == pytest.approx(0.20)
        assert "decision_trees" in data
        assert "waste" in data
        assert "agents" in data

    async def test_trace_analysis_not_found(self, client, test_db):
        response = await client.get("/api/traces/nonexistent/analysis")
        assert response.status_code == 404

    async def test_decision_tree(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/traces/trace_001/tree")
        assert response.status_code == 200
        data = response.json()

        assert data["trace_id"] == "trace_001"
        assert data["total_cost"] == pytest.approx(0.20)
        assert len(data["trees"]) == 1

        root = data["trees"][0]
        assert root["decision_name"] == "orchestrate"
        assert root["direct_cost"] == pytest.approx(0.02)
        assert len(root["child_breakdown"]) == 2


@pytest.mark.asyncio
class TestAnalyticsEndpoints:
    async def test_overview(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/analytics/overview")
        assert response.status_code == 200
        data = response.json()
        assert "trace_count" in data
        assert "total_cost" in data
        assert "error_rate" in data

    async def test_agent_stats(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/analytics/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert len(data["agents"]) >= 2  # orchestrator, researcher, writer

    async def test_cost_trends(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/analytics/cost-trends?hours=720")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    async def test_waste_summary(self, client, test_db, sample_spans):
        await client.post("/api/spans/ingest", json=sample_spans)
        response = await client.get("/api/analytics/waste-summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_cost_analyzed" in data
        assert "total_waste_detected" in data
        assert "waste_by_type" in data
