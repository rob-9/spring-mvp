# Spring

Decision-level cost attribution for multi-agent AI systems. Track the true cost of every agent decision — not just per-call API spend, but the full downstream tree: retries it triggered, cascades it caused, and tokens it wasted.

**Stack:** FastAPI, PostgreSQL, OpenTelemetry

## Quickstart

```bash
cp .env.example .env         # set POSTGRES_PASSWORD
docker compose up             # starts postgres + api on :8000
python -m backend.scripts.seed_demo_data  # load demo traces
```

Or without Docker:

```bash
pip install -r requirements.txt
python -m backend.api.app  # requires local postgres
```

## API

| Endpoint | Description |
|---|---|
| `POST /api/spans/ingest` | Ingest spans from instrumented apps |
| `GET /api/traces` | List traces with filtering/sorting |
| `GET /api/traces/{id}/analysis` | Decision cost trees + waste detection |
| `GET /api/traces/{id}/tree` | Recursive cost attribution tree |
| `GET /api/analytics/overview` | Dashboard stats |
| `GET /api/analytics/agents` | Per-agent cost and error breakdown |
| `GET /api/analytics/cost-trends` | Cost over time |
| `GET /api/analytics/waste-summary` | Aggregate waste across traces |

## Customer SDK

```python
from spring_crewai import instrument_crewai

instrument_crewai(endpoint="https://api.spring.ai/v1/traces", api_key="sk-...")
crew.kickoff()  # spans captured automatically
```

## Tests

```bash
pytest backend/tests/ -v  # 152 tests
```
