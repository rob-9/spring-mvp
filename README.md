# Spring MVP

Cut unnecessary costs for multi-agent systems. 

FasAPI, TypeScript, Postgres, OpenTelemtry SDK

## Skeleton

```
backend/
├── core/              # Data models (Span, Trace, DecisionCost)
├── instrumentation/   # OpenTelemetry setup and agent instrumentation
├── analysis/          # Core algorithms
│   ├── waste_detection/   # Waste detection algorithms (retry, loops, dead-ends)
│   ├── decision_path.py   # Decision-level cost attribution
│   └── graph_builder.py   # Dependency graph construction
├── storage/           # Database persistence layer
└── api/               # FastAPI routes
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
