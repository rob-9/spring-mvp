# Spring MVP

Cut unnecessary costs for multi-agent systems. 

FasAPI, TypeScript, Postgres, OpenTelemtry SDK

## Skeleton

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

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run backend
python -m backend.api.app
```

## Docs

See `/docs/mvp-summary.md`
See `/docs/decision-cost-visualization.md`
