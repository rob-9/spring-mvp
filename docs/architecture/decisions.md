# Architecture Decision Records (ADRs)

Document key architectural decisions here to provide context for future team members.

## Format

```
## ADR-XXX: [Title]

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded
**Context:** What is the issue we're facing?
**Decision:** What we decided to do
**Consequences:** What becomes easier/harder as a result
```

---

## ADR-001: Use Python for Backend

**Date:** 2026-02-04
**Status:** Accepted

**Context:**
- Building observability platform for AI agents
- Need to auto-instrument CrewAI, AutoGen, LangGraph (all Python frameworks)
- Customers write agent orchestration code in Python

**Decision:**
Use Python (FastAPI) for backend instead of TypeScript/Go.

**Consequences:**
- Native integration with AI agent frameworks
- Single codebase for backend + customer SDK
- Easy auto-instrumentation via Python callbacks
- May need to optimize hot paths later (acceptable trade-off)

**Alternatives Considered:**
- TypeScript: Would require maintaining separate Python SDK + manual instrumentation
- Go: Better performance but poor AI ecosystem integration

---

## ADR-002: Use OpenTelemetry for Tracing

**Date:** 2026-02-04
**Status:** Accepted

**Context:**
- Need framework-agnostic instrumentation
- Want production-ready, battle-tested solution
- Must support multiple agent frameworks (CrewAI, AutoGen, LangGraph)

**Decision:**
Use OpenTelemetry SDK as foundation for span capture.

**Consequences:**
- Industry standard, proven at scale (Netflix, Uber, Airbnb)
- Framework-agnostic
- Rich ecosystem (exporters, collectors, tooling)
- Future-proof (becoming standard for observability)
- Learning curve for distributed tracing concepts

**Alternatives Considered:**
- LangSmith SDK: LangChain-only, vendor lock-in
- Custom instrumentation: Reinventing the wheel
- Langfuse: Good option, but less mature than OTel

---

## ADR-003: Modular Monolith Architecture

**Date:** 2026-02-04
**Status:** Accepted

**Context:**
- Pre-PMF startup, need to ship fast
- Will have multiple bounded contexts (cost attribution, cascade detection, replay)
- Don't need microservices complexity yet
- Want clear module boundaries for future scalability

**Decision:**
Use modular monolith with DDD-inspired bounded contexts.

**Consequences:**
- Fast in-process communication (no HTTP overhead)
- Single deployment, simple ops
- Shared database transactions (ACID guarantees)
- Easy to test
- Can migrate to microservices later if needed
- Can't independently scale modules (acceptable for MVP)

**Migration Path:**
Scales to Series A and beyond (2-3 years). Revisit if:
- 50+ engineers and module boundaries slow teams down
- Need independent scaling of specific modules
- Different modules have vastly different SLAs

---

## Template for Future ADRs

```markdown
## ADR-XXX: [Title]

**Date:** YYYY-MM-DD
**Status:** Proposed

**Context:**
[What problem are we solving? What constraints exist?]

**Decision:**
[What did we decide to do?]

**Consequences:**
[What becomes easier/harder? What are the trade-offs?]

**Alternatives Considered:**
- [Option 1]: [Why not chosen]
- [Option 2]: [Why not chosen]
```
