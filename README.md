# Spring MVP

Cost observability platform for multi-agent AI systems. Shows which agent is breaking your workflow, how much money it's wasting, and which downstream agents are affected.

### Customer Usage

```python
# 1. Install OpenTelemetry SDK (standard)
pip install opentelemetry-api opentelemetry-sdk

# 2. Install our framework adapter
pip install spring-crewai  # or spring-autogen, spring-langgraph

# 3. Configure to send to our backend
from spring_crewai import instrument_crewai

instrument_crewai(
    endpoint="https://api.spring.ai/v1/traces",
    api_key="your_key"
)

# Customer's code runs normally, spans captured automatically
crew.kickoff()
```

**Stack:** FastAPI, TypeScript, PostgreSQL, OpenTelemetry SDK

## Codebase Structure

```
backend/
├── core/              # Data models (Span, Trace, DecisionCost)
│   └── models.py
├── instrumentation/   # OpenTelemetry setup and agent instrumentation
│   └── otel_tracer.py
├── analysis/          # Core algorithms
│   ├── waste_detection/     # Waste detection algorithms
│   │   ├── retry_bloat.py   # Retry pattern detection
│   │   ├── loop_detection.py # Structural & behavioral loop detection
│   │   ├── dead_end.py       # Dead-end path detection
│   │   ├── cascade.py        # Cascading failure detection
│   │   └── context_waste.py  # Context window waste detection
│   └── decision_path.py      # Decision-level cost attribution
├── storage/           # Database persistence layer
│   └── span_store.py
├── api/               # FastAPI routes
│   ├── app.py
│   └── routes/
└── tests/             # Test suite
```

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run backend
python -m backend.api.app
```

## Documentation

- `/docs/mvp-summary.md` - Full MVP implementation guide
- `/docs/architecture/decisions.md` - Architecture decision records
- `/docs/decision-cost-visualization.md` - Cost visualization specs
