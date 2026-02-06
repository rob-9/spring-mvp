/Users/robert/spring-mvp/backend/analysis/waste_detection/loop_detection.py
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

## ADR-004: Span Links for Structural Loop Detection

**Date:** 2026-02-05
**Status:** Accepted

**Context:**
- OpenTelemetry traces are Directed Acyclic Graphs (DAGs) via parent-child relationships
- True cycles cannot exist in parent-child relationships (each span has exactly one parent)
- However, agent workflows often contain loops (recursive calls, retry loops, iterative patterns)
- Initial implementation tried to detect cycles in parent-child graph (impossible)

**Decision:**
Use OpenTelemetry SpanLinks to represent non-hierarchical relationships and detect structural loops.

Implementation:
1. Added `SpanLink` model with `trace_id`, `span_id`, `link_type`, and `attributes`
2. Added `links: List[SpanLink]` field to Span model
3. Redesigned `detect_structural_loops()` to build graph from span links instead of parent-child relationships
4. Links represent: loop iterations, recursive calls, retry chains, scatter/gather patterns

**Consequences:**
- **Pros:**
  - Correctly models how OpenTelemetry represents cycles
  - Follows OTel best practices (used by Google, Netflix, Uber)
  - Can detect true circular dependencies in multi-agent systems
  - Compatible with standard OTel collectors and tools
- **Cons:**
  - Requires instrumentation code to create span links (not automatic)
  - Framework adapters (CrewAI, AutoGen) must be updated to emit links
  - Empty results until instrumentation adds links

**Migration Path:**
1. MVP: Accept that structural loop detection requires span links
2. Week 2-3: Update CrewAI/AutoGen/LangGraph adapters to emit span links for:
   - Loop iterations (link back to loop start)
   - Recursive agent calls (link to previous invocation)
   - Retry attempts (link to original attempt)
3. Documentation: Guide customers on adding links to custom agents

**Alternatives Considered:**
- Use `triggered_by` metadata: Less formal, harder to query, non-standard
- Custom cycle representation: Reinvents OTel, incompatible with ecosystem
- Remove structural loop detection: Loses 36.94% of failure cases (coordination failures)

---

## ADR-005: Behavioral Loop Deduplication Strategy

**Date:** 2026-02-05
**Status:** Accepted

**Context:**
- Sliding window pattern detection creates overlapping patterns
- Example: `[A, B, C]` repeated creates patterns: `[A]`, `[B]`, `[C]`, `[A,B]`, `[B,C]`, `[A,B,C]`
- All patterns share the same spans, leading to:
  - Noisy output (6 detections instead of 1)
  - Potential cost double-counting
- Need deterministic way to choose which pattern to report

**Decision:**
Deduplicate overlapping patterns by keeping longest non-overlapping patterns.

Algorithm:
1. Sort patterns by length descending, then by wasted cost descending
2. Iterate through sorted patterns
3. Track used span IDs across all occurrences
4. Keep pattern if its span IDs don't overlap with already-kept patterns
5. Mark all its span IDs as used

**Consequences:**
- **Pros:**
  - No cost double-counting (each span appears in at most one result)
  - Clean output (meaningful patterns, not sub-patterns)
  - Deterministic (always chooses same pattern for given input)
  - Efficient (O(n log n) sort + O(n×m) dedup where m = avg occurrences)
- **Cons:**
  - May hide sub-patterns that have value (e.g., if `[A,B,C]` and `[A,B]` both repeat)
  - Longest pattern isn't always most meaningful (e.g., artifact of window size)

**Parameters:**
- `min_pattern_length`: Minimum pattern length (default 2, filters single-op noise)
- `window_size`: Maximum pattern length (default 6, limits combinatorial explosion)
- `max_spans`: Performance limit (default 5000, prevents O(n²) slowdown)

**Alternatives Considered:**
- Keep all patterns: Too noisy, cost double-counting
- Keep highest cost patterns: Misses frequency patterns (many cheap repetitions)
- Use longest repeated substring algorithm: More complex, similar results

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
