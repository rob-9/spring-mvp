# AI Agent Cost Intelligence Platform - MVP Implementation Guide

## Executive Summary

**What we're building:** A unified platform that gives developers X-ray vision into AI agent workflows — showing exactly where money is wasted, why failures cascade, and how to test changes without risk.

**Core value prop:** Current tools (Datadog, Langfuse, AgentOps) show "you spent $500 this month." We show "you spent $500, but $180 was wasted on retry loops in the order-status workflow — here's the exact decision that caused it and how to fix it."

---

## Product Architecture Overview

### The Four Core Modules (Build in This Order):
i
1. **Decision-Level Cost Attribution** ← START HERE (MVP Week 1-4)
   - Track cost per agent decision, not just per API call
   - Detect waste (loops, retries, dead-ends)
   - Surface cost-per-outcome metrics

2. **Time-Travel Debugging** (MVP Week 5-8)
   - Replay failed workflows from any checkpoint
   - Fork execution with modified inputs
   - Compare "what happened" vs "what should have happened"

3. **Cascade Detection** (MVP Week 9-12)
   - Automatically find root cause of multi-agent failures
   - Build dependency graph showing what broke what
   - Rank fixes by cost-impact

4. **Dry-Run Proxy** (Post-MVP, Month 4+)
   - Intercept irreversible actions (emails, DB writes, API calls)
   - Preview outcomes in mock environment
   - Prevent costly mistakes before they execute

**Shared Foundation:** All four modules use the same trace capture infrastructure. Build #1 first, others layer on top.

---

# Module 1: Decision-Level Cost Attribution

## What It Does (User Perspective)

**Problem it solves:**

Current tools show: "You spent $450 on GPT-4 this month"

We show:
```
You spent $450 total:
  - $280 productive work
  - $170 wasted on:
    → $80: Retry loops in order-status workflow (23 incidents)
    → $50: Dead-end searches in refund-processor (41 incidents)  
    → $40: Context re-ingestion in document-summarizer (constant)

Top 3 fixes by ROI:
1. Fix order-status retry logic → Save $80/month
2. Cache document context → Save $40/month
3. Add validation to refund form → Save $50/month
```

**Key features:**

1. **Cost per decision path** - Not just "LLM call cost $0.05", but "When agent decided to verify user identity, entire branch cost $0.18 (3 LLM calls + 2 DB lookups + 1 retry)"

2. **Waste detection** - Auto-flags:
   - Loop detection: Same prompt repeated 5x
   - Retry bloat: Task that should cost $0.05 costs $0.25 due to 4 retries
   - Context re-ingestion: Same 30K token document tokenized 3 times
   - Dead-ends: Branches that cost money but contributed nothing

3. **Cost-per-outcome** - "Successful approvals cost $0.04, failures cost $0.22 (5x more due to retries)"

4. **A/B testing** - "Prompt V2 saves 15% at summarization step, costs 8% more at verification step, net 7% savings"

---

## Technical Implementation Options

### Core Decision: How do we capture spans + propagation metadata?

A **span** = one unit of work (LLM call, tool call, API call)
**Propagation metadata** = "what triggered this span? what decision led here?"

---

### **Option 1: OpenTelemetry (OTel) ⭐⭐⭐⭐⭐ RECOMMENDED**

**What it is:** Industry-standard distributed tracing framework. Think of it as the "universal adapter" for observability.

**How it works:**

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Setup
provider = TracerProvider()
exporter = OTLPSpanExporter(endpoint="your-backend:4317")
processor = BatchSpanProcessor(exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("agent-tracker")

# Instrument your agent code
def verify_user_identity(user_id, parent_span_context=None):
    with tracer.start_as_current_span(
        "verify_identity",
        context=parent_span_context
    ) as span:
        # Add propagation metadata
        span.set_attribute("node_id", "identity_verifier")
        span.set_attribute("triggered_by", "user_login_request")
        span.set_attribute("parent_decision", "authenticate_user")
        span.set_attribute("attempt_number", 1)
        
        # Make LLM call
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": f"Verify user {user_id}"}]
        )
        
        # Tag with cost
        tokens = response.usage.total_tokens
        cost = (tokens / 1_000_000) * 5.0  # GPT-4 pricing
        
        span.set_attribute("cost_usd", cost)
        span.set_attribute("tokens_input", response.usage.prompt_tokens)
        span.set_attribute("tokens_output", response.usage.completion_tokens)
        span.set_attribute("tokens_total", tokens)
        span.set_attribute("model", "gpt-4")
        span.set_attribute("decision_made", "verified" if success else "rejected")
        
        # Return span context for child spans
        return response, trace.get_current_span().get_span_context()
```

**Pros:**
- ✅ **Framework-agnostic** - Works with LangChain, CrewAI, AutoGen, custom agents
- ✅ **Industry standard** - Every observability platform supports it
- ✅ **Auto-instrumentation available** - Libraries like `opentelemetry-instrumentation-openai` auto-capture calls
- ✅ **Mature ecosystem** - Exporters for Jaeger, Zipkin, Prometheus, your own DB
- ✅ **No vendor lock-in** - Switch backends anytime
- ✅ **Built-in span hierarchy** - Parent-child relationships automatic
- ✅ **Production-proven** - Used by Netflix, Uber, Airbnb for distributed tracing

**Cons:**
- ⚠️ **Learning curve** - Distributed tracing concepts take time to learn
- ⚠️ **Boilerplate** - Requires wrapping code in `with tracer.start_as_current_span()`
- ⚠️ **Manual cost tagging** - Must calculate and attach cost yourself
- ⚠️ **Performance overhead** - ~1-5% latency increase (batch processing mitigates)

**When to use:**
- You want production-grade, enterprise solution
- You need multi-framework support (LangChain + CrewAI + custom)
- You might integrate with existing observability stack
- You value flexibility over simplicity

**Development effort:**
- Basic setup: 2-3 days
- Auto-instrumentation for common frameworks: 1 week
- Full production deployment: 3-4 weeks
- **Difficulty: Medium** ⭐⭐⭐

**Recommendation strength: 9/10** - Best choice for serious MVP that can scale

---

### **Option 2: LangSmith SDK - LangChain Native**

**What it is:** Observability platform built by LangChain team. Native support for LangChain/LangGraph workflows.

**How it works:**

```python
from langsmith import Client
from langchain.callbacks import LangChainTracer
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain

# Setup
client = Client()
tracer = LangChainTracer(project_name="cost-tracker")

# Your LangChain code (auto-traced)
llm = ChatOpenAI(model="gpt-4", callbacks=[tracer])
chain = LLMChain(llm=llm, prompt=prompt_template)

# Run (automatically captured)
result = chain.invoke({"input": "verify user identity"})

# Add custom cost metadata via API
run = client.read_run(result.run_id)
client.update_run(
    run.id,
    extra={
        "cost_usd": 0.015,
        "decision_node": "identity_verifier",
        "triggered_by": "user_login",
        "decision_made": "verified"
    }
)
```

**Pros:**
- ✅ **Zero-config for LangChain** - Works immediately with LangChain/LangGraph
- ✅ **Auto-captures everything** - Prompts, outputs, tool calls, retrieval steps
- ✅ **Built-in UI** - Comes with trace visualization dashboard
- ✅ **Dead simple** - 3 lines of code to start
- ✅ **LLM-native** - Understands chains, agents, retrievers out of box

**Cons:**
- ❌ **LangChain lock-in** - Only works well with LangChain ecosystem
- ❌ **Vendor lock-in** - Proprietary platform, can't easily switch
- ❌ **Limited multi-framework** - Painful to use with CrewAI, AutoGen
- ❌ **Pricing** - $39/mo after 5K traces (can get expensive)
- ⚠️ **Less customization** - Harder to add custom decision-path logic

**When to use:**
- You're 100% LangChain/LangGraph
- You want fastest time-to-value
- You're okay with vendor lock-in
- Volume fits free tier (<5K traces/month initially)

**Development effort:**
- Basic setup: 1 day
- Custom cost metadata: 3-5 days
- Production-ready: 1-2 weeks
- **Difficulty: Easy** ⭐

**Recommendation strength: 6/10** - Good for LangChain-only shops, risky otherwise

---

### **Option 3: Custom Instrumentation Layer (Roll Your Own)**

**What it is:** Build a lightweight wrapper that intercepts agent operations and logs to your database.

**How it works:**

```python
import time
import uuid
from datetime import datetime
import threading

class SpanTracker:
    def __init__(self, db_connection):
        self.db = db_connection
        self.local = threading.local()  # Thread-local storage for span context
    
    def start_span(self, name, parent_span_id=None, metadata=None):
        span_id = str(uuid.uuid4())
        
        # If no parent provided, check thread-local context
        if parent_span_id is None and hasattr(self.local, 'current_span'):
            parent_span_id = self.local.current_span
        
        span = {
            "span_id": span_id,
            "trace_id": metadata.get("trace_id", str(uuid.uuid4())),
            "name": name,
            "parent_span_id": parent_span_id,
            "start_time": datetime.utcnow(),
            "metadata": metadata or {},
            "status": "running"
        }
        
        # Store in thread-local for nested spans
        self.local.current_span = span_id
        
        # Cache in memory
        self.local.active_spans = getattr(self.local, 'active_spans', {})
        self.local.active_spans[span_id] = span
        
        return span_id
    
    def end_span(self, span_id, cost=None, decision=None, status="success"):
        if not hasattr(self.local, 'active_spans') or span_id not in self.local.active_spans:
            return
        
        span = self.local.active_spans[span_id]
        span["end_time"] = datetime.utcnow()
        span["duration_ms"] = (span["end_time"] - span["start_time"]).total_seconds() * 1000
        span["cost_usd"] = cost
        span["decision_made"] = decision
        span["status"] = status
        
        # Persist to database
        self.db.spans.insert_one(span)
        
        # Clean up
        del self.local.active_spans[span_id]
        
        # Restore parent context
        if span["parent_span_id"]:
            self.local.current_span = span["parent_span_id"]

# Usage
tracker = SpanTracker(mongo_client.cost_tracker)

def verify_identity(user_id):
    span_id = tracker.start_span(
        name="verify_identity",
        metadata={
            "node_id": "identity_verifier",
            "triggered_by": "user_login",
            "decision_node": True,
            "attempt_number": 1
        }
    )
    
    try:
        # LLM call
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": f"Verify {user_id}"}]
        )
        
        cost = (response.usage.total_tokens / 1_000_000) * 5.0
        decision = "verified" if is_valid(response) else "rejected"
        
        tracker.end_span(span_id, cost=cost, decision=decision, status="success")
        return response
        
    except Exception as e:
        tracker.end_span(span_id, status="error")
        raise
```

**Pros:**
- ✅ **Full control** - Design exactly what you need
- ✅ **Simple to understand** - No magic, just functions and database inserts
- ✅ **Lightweight** - Minimal dependencies
- ✅ **No vendor lock-in** - Your code, your data
- ✅ **Easy debugging** - Can console.log() and see exactly what's happening

**Cons:**
- ❌ **Reinventing the wheel** - OTel already solved this
- ❌ **Missing features** - No sampling, batching, async handling out of box
- ❌ **Maintenance burden** - You own all bugs
- ❌ **No ecosystem** - Can't leverage OTel exporters, tools
- ⚠️ **Context propagation is hard** - Thread-local storage has edge cases with async/parallel

**When to use:**
- You're prototyping and want something quick
- You have simple, synchronous workflows
- You want to learn by building
- You're confident you can maintain it

**Development effort:**
- Basic implementation: 3-5 days
- Production-hardened: 2-3 weeks
- **Difficulty: Easy to start, Medium to perfect** ⭐⭐

**Recommendation strength: 4/10** - Good for learning, risky for production

---

### **Option 4: Langfuse (Open Source + Self-Hostable)**

**What it is:** Open-source LLM observability platform. Like LangSmith but self-hostable.

**How it works:**

```python
from langfuse import Langfuse
from langfuse.decorators import observe

# Initialize
langfuse = Langfuse(
    public_key="pk-...",
    secret_key="sk-...",
    host="https://your-instance.langfuse.com"  # or self-hosted
)

# Decorate your functions
@observe(name="verify_identity")
def verify_identity(user_id):
    # Your code here
    response = openai.chat.completions.create(...)
    
    # Langfuse auto-captures LLM calls via monkey-patching
    # Manually add decision metadata
    langfuse.update_current_observation(
        metadata={
            "node_id": "identity_verifier",
            "triggered_by": "user_login",
            "decision_made": "verified",
            "cost_usd": 0.015
        }
    )
    
    return response
```

**Pros:**
- ✅ **Open source** - Can self-host, no vendor lock-in
- ✅ **Multi-framework** - Works with LangChain, LlamaIndex, OpenAI SDK
- ✅ **Built-in UI** - Nice dashboard out of box
- ✅ **Active development** - Good community, frequent updates
- ✅ **Cost tracking** - Auto-calculates costs for OpenAI, Anthropic

**Cons:**
- ⚠️ **Decorator-based** - Requires wrapping functions with `@observe`
- ⚠️ **Less mature than OTel** - Smaller ecosystem
- ⚠️ **Self-hosting overhead** - Need to run Postgres + Next.js app
- ⚠️ **Cloud option has limits** - Free tier: 50K observations/month

**When to use:**
- You want open-source but don't want to build from scratch
- You like decorator-based instrumentation
- You're okay with some vendor coupling (but can self-host as escape hatch)

**Development effort:**
- Basic setup: 1-2 days
- Self-hosting: +2-3 days
- Production-ready: 2-3 weeks
- **Difficulty: Easy-Medium** ⭐⭐

**Recommendation strength: 7/10** - Solid middle-ground option

---

## **Decision Matrix: Which Option Should You Choose?**

| Criteria | OTel | LangSmith | Custom | Langfuse |
|----------|------|-----------|--------|----------|
| Multi-framework support | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Time to first trace | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Production-ready | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| Customization | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Vendor lock-in risk | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Learning curve | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Ecosystem/tooling | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ |
| Cost (at scale) | Free | $$$ | Free | Free/$ |

### **Recommended Path:**

**For MVP (Week 1-4):**
- Start with **Langfuse** if you want to ship fast and validate product-market fit
- Choose **OTel** if you have time and want production-grade foundation

**For Production (Month 2+):**
- Migrate to **OTel** for long-term scalability and flexibility
- Stick with **Langfuse** if it's working and you're self-hosting

**Avoid:**
- Custom instrumentation (unless learning exercise)
- LangSmith (unless 100% committed to LangChain forever)

---

## Decision-Path Costing: The Core Algorithm

Once you have spans with propagation metadata, how do you aggregate cost per decision?

### Algorithm:

```python
def calculate_decision_path_cost(span_id, span_database):
    """
    Recursively calculate total cost of a decision and all its children.
    
    Args:
        span_id: The root span of the decision
        span_database: Database/dict of all spans
    
    Returns:
        {
            "decision_span_id": span_id,
            "direct_cost": 0.015,  # Cost of this span alone
            "total_cost": 0.047,   # Cost of this span + all children
            "child_costs": [...],  # Breakdown by child
            "waste_detected": [...]  # Any anomalies found
        }
    """
    span = span_database[span_id]
    direct_cost = span.get("cost_usd", 0)
    
    # Find all child spans (spans triggered by this one)
    children = [
        s for s in span_database.values()
        if s.get("parent_span_id") == span_id
    ]
    
    # Recursively calculate child costs
    child_costs = []
    total_child_cost = 0
    
    for child in children:
        child_analysis = calculate_decision_path_cost(child["span_id"], span_database)
        child_costs.append(child_analysis)
        total_child_cost += child_analysis["total_cost"]
    
    # Detect waste patterns
    waste = detect_waste(span, children)
    
    return {
        "decision_span_id": span_id,
        "decision_name": span["name"],
        "direct_cost": direct_cost,
        "child_cost": total_child_cost,
        "total_cost": direct_cost + total_child_cost,
        "child_breakdown": child_costs,
        "waste_detected": waste,
        "metadata": span.get("metadata", {})
    }

def detect_waste(span, children):
    """Detect common waste patterns."""
    waste = []
    
    # 1. Retry bloat: Same span name appears multiple times as siblings
    span_names = [c["name"] for c in children]
    duplicates = {name: span_names.count(name) for name in set(span_names)}
    retries = {name: count for name, count in duplicates.items() if count > 1}
    
    if retries:
        waste.append({
            "type": "retry_bloat",
            "details": f"Retried {retries} - might indicate stuck logic",
            "severity": "high" if max(retries.values()) > 3 else "medium"
        })
    
    # 2. Dead-end: This span cost money but decision_made indicates failure
    if span.get("decision_made") == "failed" or span.get("status") == "error":
        if span.get("cost_usd", 0) > 0:
            waste.append({
                "type": "dead_end",
                "details": f"Spent ${span['cost_usd']:.4f} but ended in failure",
                "severity": "medium"
            })
    
    # 3. Loop detection: Check if this span's prompt appears in recent history
    # (Requires tracking recent prompts in session)
    
    return waste

# Example usage:
spans_db = {
    "span_001": {
        "span_id": "span_001",
        "name": "verify_identity",
        "parent_span_id": None,
        "cost_usd": 0.015,
        "metadata": {"decision_node": True}
    },
    "span_002": {
        "span_id": "span_002",
        "name": "check_database",
        "parent_span_id": "span_001",
        "cost_usd": 0.002
    },
    "span_003": {
        "span_id": "span_003",
        "name": "check_database",  # Retry!
        "parent_span_id": "span_001",
        "cost_usd": 0.002,
        "metadata": {"attempt_number": 2}
    },
    "span_004": {
        "span_id": "span_004",
        "name": "format_response",
        "parent_span_id": "span_001",
        "cost_usd": 0.008
    }
}

analysis = calculate_decision_path_cost("span_001", spans_db)
print(analysis)
# Output:
# {
#   "decision_span_id": "span_001",
#   "decision_name": "verify_identity",
#   "direct_cost": 0.015,
#   "child_cost": 0.012,
#   "total_cost": 0.027,
#   "child_breakdown": [...],
#   "waste_detected": [{
#     "type": "retry_bloat",
#     "details": "Retried {'check_database': 2}",
#     "severity": "medium"
#   }]
# }
```

---

## Cost-Per-Outcome Tracking

### Algorithm:

```python
from collections import defaultdict

def calculate_cost_per_outcome(traces, outcome_classifier):
    """
    Group traces by outcome and calculate average cost per outcome type.
    
    Args:
        traces: List of complete trace objects
        outcome_classifier: Function that returns outcome type (success/failure/type)
    
    Returns:
        {
            "loan_approved": {"count": 80, "avg_cost": 0.04, "total": 3.20},
            "loan_rejected": {"count": 20, "avg_cost": 0.18, "total": 3.60}
        }
    """
    outcomes = defaultdict(lambda: {"costs": [], "count": 0})
    
    for trace in traces:
        # Classify outcome
        outcome = outcome_classifier(trace)
        
        # Calculate total trace cost
        total_cost = sum(span["cost_usd"] for span in trace["spans"] if span.get("cost_usd"))
        
        # Aggregate
        outcomes[outcome]["costs"].append(total_cost)
        outcomes[outcome]["count"] += 1
    
    # Calculate averages
    result = {}
    for outcome, data in outcomes.items():
        result[outcome] = {
            "count": data["count"],
            "avg_cost": sum(data["costs"]) / data["count"],
            "total_cost": sum(data["costs"]),
            "p50_cost": sorted(data["costs"])[len(data["costs"]) // 2],
            "p95_cost": sorted(data["costs"])[int(len(data["costs"]) * 0.95)]
        }
    
    return result

# Example outcome classifier
def classify_loan_outcome(trace):
    """Extract outcome from final span's decision."""
    final_span = trace["spans"][-1]
    decision = final_span.get("decision_made", "unknown")
    
    if "approved" in decision.lower():
        return "loan_approved"
    elif "rejected" in decision.lower():
        return "loan_rejected"
    else:
        return "unknown"

# Usage
traces = load_traces_from_db(date_range="last_week")
outcomes = calculate_cost_per_outcome(traces, classify_loan_outcome)

print(outcomes)
# {
#   "loan_approved": {
#     "count": 80,
#     "avg_cost": 0.04,
#     "total_cost": 3.20,
#     "p50_cost": 0.03,
#     "p95_cost": 0.08
#   },
#   "loan_rejected": {
#     "count": 20,
#     "avg_cost": 0.18,
#     "total_cost": 3.60,
#     "p50_cost": 0.15,
#     "p95_cost": 0.35
#   }
# }
```

---

# Module 2: Time-Travel Debugging

## What It Does (User Perspective)

**Problem:** Agent fails at step 12. You want to test a fix, but you have to wait for another real user query to see if it works. Slow feedback loop.

**Solution:** Rewind to step 5, inject a different message, re-execute steps 6-12, see if the fix works.

**Key features:**

1. **Session replay** - View complete execution history
2. **Checkpoint forking** - Rewind to any point, modify state, re-run
3. **Side-by-side diff** - Compare original vs. forked execution
4. **Regression testing** - Save failed scenarios, replay on every deploy

---

## Technical Implementation Options

### Core Decision: How do we capture + replay agent state?

---

### **Option 1: Framework-Native Checkpoints ⭐⭐⭐⭐**

**What it is:** Use framework's built-in state persistence (LangGraph has this, CrewAI sort of has it).

**How it works (LangGraph example):**

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph

# Define your agent
class AgentState(TypedDict):
    messages: List[str]
    current_step: str
    data: Dict

def agent_node(state: AgentState):
    # Agent logic
    return {"messages": state["messages"] + ["response"], "current_step": "next"}

# Build graph with checkpointing
workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.set_entry_point("agent")

# Enable checkpointing (LangGraph feature)
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")
app = workflow.compile(checkpointer=checkpointer)

# Run with thread_id (enables replay)
result = app.invoke(
    {"messages": ["user query"]},
    config={"configurable": {"thread_id": "thread_123"}}
)

# Later: Fork from checkpoint
# 1. Load state at specific checkpoint
checkpoint_state = checkpointer.get_tuple(
    config={"configurable": {"thread_id": "thread_123", "checkpoint_id": "step_5"}}
)

# 2. Modify state
modified_state = checkpoint_state.checkpoint["channel_values"].copy()
modified_state["messages"].append("INJECTED: Try a different approach")

# 3. Re-run from that point
forked_result = app.invoke(
    modified_state,
    config={"configurable": {"thread_id": "thread_123_fork"}}
)

# 4. Compare
print("Original result:", result)
print("Forked result:", forked_result)
```

**Pros:**
- ✅ **Native support** - Built into LangGraph, minimal custom code
- ✅ **Automatic state capture** - Every node transition saved
- ✅ **Simple API** - `.get_state()`, `.update_state()`, `.invoke_from_checkpoint()`
- ✅ **Production-tested** - LangGraph team maintains it

**Cons:**
- ❌ **Framework lock-in** - Only works with LangGraph (or similar frameworks with checkpointing)
- ⚠️ **Limited to state** - Doesn't capture external side effects (API calls, DB writes)
- ⚠️ **Storage overhead** - Saving full state at every step can be large

**When to use:**
- You're using LangGraph
- Your agent state is serializable
- You don't need to replay external tool calls

**Development effort:**
- Basic checkpoint replay: 3-5 days
- Fork + diff UI: 1-2 weeks
- **Difficulty: Easy** ⭐

**Recommendation: 8/10 for LangGraph users, 2/10 for others**

---

### **Option 2: Event Sourcing Pattern ⭐⭐⭐⭐⭐ RECOMMENDED**

**What it is:** Store every event (LLM call, tool invocation, state change) as immutable log entries. Replay = re-process events.

**How it works:**

```python
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Any
import json

@dataclass
class Event:
    event_id: str
    trace_id: str
    timestamp: datetime
    event_type: str  # "llm_call", "tool_call", "state_change"
    data: Dict[Any, Any]
    checkpoint_id: str  # Which checkpoint this event belongs to

class EventStore:
    def __init__(self, db):
        self.db = db
    
    def append(self, event: Event):
        """Append event to immutable log."""
        self.db.events.insert_one({
            **asdict(event),
            "timestamp": event.timestamp.isoformat()
        })
    
    def get_events(self, trace_id: str, up_to_checkpoint=None):
        """Get all events for a trace, optionally up to a checkpoint."""
        query = {"trace_id": trace_id}
        if up_to_checkpoint:
            query["checkpoint_id"] = {"$lte": up_to_checkpoint}
        
        events = self.db.events.find(query).sort("timestamp", 1)
        return list(events)
    
    def replay(self, trace_id: str, up_to_checkpoint: str, modifications: List[Event] = None):
        """Replay events to reconstruct state, optionally with modifications."""
        events = self.get_events(trace_id, up_to_checkpoint)
        
        # Insert modifications at the right point
        if modifications:
            events = events + modifications
            events.sort(key=lambda e: e["timestamp"])
        
        # Replay events to rebuild state
        state = {}
        for event in events:
            state = apply_event(state, event)
        
        return state

def apply_event(state: Dict, event: Dict) -> Dict:
    """Apply an event to state (pure function)."""
    if event["event_type"] == "llm_call":
        return {
            **state,
            "messages": state.get("messages", []) + [event["data"]["response"]]
        }
    elif event["event_type"] == "tool_call":
        return {
            **state,
            "tool_results": state.get("tool_results", []) + [event["data"]["result"]]
        }
    elif event["event_type"] == "state_change":
        return {
            **state,
            **event["data"]["changes"]
        }
    return state

# Usage in agent
event_store = EventStore(mongo_client.agent_db)

def run_agent_with_event_sourcing(user_query, trace_id):
    checkpoint_id = 0
    
    # Event: User message
    event_store.append(Event(
        event_id=str(uuid.uuid4()),
        trace_id=trace_id,
        timestamp=datetime.utcnow(),
        event_type="user_message",
        data={"message": user_query},
        checkpoint_id=str(checkpoint_id)
    ))
    checkpoint_id += 1
    
    # Event: LLM call
    response = call_llm(user_query)
    event_store.append(Event(
        event_id=str(uuid.uuid4()),
        trace_id=trace_id,
        timestamp=datetime.utcnow(),
        event_type="llm_call",
        data={"prompt": user_query, "response": response, "model": "gpt-4"},
        checkpoint_id=str(checkpoint_id)
    ))
    checkpoint_id += 1
    
    # Event: Tool call
    tool_result = call_tool(response)
    event_store.append(Event(
        event_id=str(uuid.uuid4()),
        trace_id=trace_id,
        timestamp=datetime.utcnow(),
        event_type="tool_call",
        data={"tool": "search_db", "result": tool_result},
        checkpoint_id=str(checkpoint_id)
    ))
    
    return tool_result

# Later: Fork from checkpoint
def fork_and_test_fix(trace_id, fork_at_checkpoint, injected_message):
    # 1. Replay up to fork point
    state = event_store.replay(trace_id, up_to_checkpoint=fork_at_checkpoint)
    
    # 2. Inject new event
    modification = Event(
        event_id=str(uuid.uuid4()),
        trace_id=trace_id + "_fork",
        timestamp=datetime.utcnow(),
        event_type="user_message",
        data={"message": injected_message, "injected": True},
        checkpoint_id=fork_at_checkpoint + "_modified"
    )
    
    # 3. Continue execution with modified state
    # (Run agent from this point with new state)
    result = continue_agent_from_state(state, modification)
    
    return result
```

**Pros:**
- ✅ **Framework-agnostic** - Works with any agent implementation
- ✅ **Complete audit trail** - Every event stored, perfect for debugging
- ✅ **Time-travel built-in** - Replay to any point by re-processing events
- ✅ **Testable** - Easy to inject events and see what happens
- ✅ **Production pattern** - Used in banking, trading systems for audit/replay

**Cons:**
- ⚠️ **Storage overhead** - Every event is a DB write (can be large)
- ⚠️ **Replay performance** - Replaying 10,000 events can be slow
- ⚠️ **Requires discipline** - Must remember to log every event

**When to use:**
- You need framework-agnostic solution
- You want complete audit trail
- You're building for production (not just prototyping)

**Development effort:**
- Event store implementation: 1 week
- Replay engine: 1 week
- Fork + diff UI: 1-2 weeks
- **Difficulty: Medium** ⭐⭐⭐

**Recommendation: 9/10** - Best long-term solution

---

### **Option 3: Snapshot-Based Checkpoints**

**What it is:** Periodically save complete agent state (like video game save points).

```python
import pickle
from dataclasses import dataclass
from typing import Any

@dataclass
class Checkpoint:
    checkpoint_id: str
    trace_id: str
    state: Any  # Pickled state object
    metadata: dict

class CheckpointManager:
    def __init__(self, storage_path):
        self.storage_path = storage_path
    
    def save_checkpoint(self, trace_id: str, state: Any, metadata: dict = None):
        checkpoint_id = f"checkpoint_{len(self.list_checkpoints(trace_id))}"
        
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            trace_id=trace_id,
            state=pickle.dumps(state),  # Serialize state
            metadata=metadata or {}
        )
        
        with open(f"{self.storage_path}/{trace_id}_{checkpoint_id}.pkl", "wb") as f:
            pickle.dump(checkpoint, f)
        
        return checkpoint_id
    
    def load_checkpoint(self, trace_id: str, checkpoint_id: str):
        with open(f"{self.storage_path}/{trace_id}_{checkpoint_id}.pkl", "rb") as f:
            checkpoint = pickle.load(f)
        
        return pickle.loads(checkpoint.state)  # Deserialize state

# Usage
checkpoints = CheckpointManager("./checkpoints")

def run_agent(query):
    state = {"messages": [], "step": 0}
    
    # Checkpoint 0
    checkpoints.save_checkpoint("trace_123", state, {"step": "start"})
    
    # Step 1: LLM call
    state["messages"].append(llm_call(query))
    state["step"] = 1
    checkpoints.save_checkpoint("trace_123", state, {"step": "after_llm"})
    
    # Step 2: Tool call
    state["tool_result"] = tool_call()
    state["step"] = 2
    checkpoints.save_checkpoint("trace_123", state, {"step": "after_tool"})
    
    return state

# Fork from checkpoint
def fork_from_checkpoint(trace_id, checkpoint_id, modifications):
    # Load state
    state = checkpoints.load_checkpoint(trace_id, checkpoint_id)
    
    # Apply modifications
    state = {**state, **modifications}
    
    # Continue execution
    return continue_agent(state)
```

**Pros:**
- ✅ **Simple concept** - Easy to understand
- ✅ **Fast replay** - Just load state, no event processing
- ✅ **Framework-agnostic**

**Cons:**
- ❌ **Large storage** - Full state at every checkpoint (can be MBs)
- ❌ **Lossy** - Only have state at checkpoint points, not every event
- ❌ **Serialization issues** - Not all Python objects pickle cleanly
- ❌ **No intermediate replay** - Can't replay "between" checkpoints

**When to use:**
- Your state is small and serializable
- You only need coarse-grained replay
- Prototyping

**Development effort:**
- Basic implementation: 3-5 days
- **Difficulty: Easy** ⭐

**Recommendation: 5/10** - Good for prototyping, not production

---

## Time-Travel Debugging: Recommendation

**For MVP:**
- Start with **event sourcing** (Option 2) if you want production-grade
- Use **LangGraph checkpoints** (Option 1) if you're already on LangGraph

**For Production:**
- **Event sourcing** is the way. Storage is cheap, debugging is expensive.

---

# Module 3: Cascade Detection & Root-Cause Analysis

## What It Does (User Perspective)

**Problem:** Multi-agent workflow fails. Agent A → Agent B → Agent C → Agent D. Output from Agent D is garbage. Which agent caused it?

**Current state:** Read through thousands of log messages manually.

**Solution:** Automatically trace failure back to root cause + show impact.

Example output:
```
Root Cause Analysis: workflow_#8829

❌ Root Cause: Agent B (step 5) - inventory_checker
    Decision: Returned warehouse_id="WH-999" (invalid)
    
📊 Blast Radius:
    → Agent C (step 7) - shipping_label_generator
       ❌ Failed: Invalid warehouse in lookup table
       
    → Agent C (step 9) - tracking_number_creator  
       ❌ Failed: No shipping label to reference
       
    → Agent D (step 11) - invoice_builder
       ❌ Failed: Missing tracking number
       
    → Agent D (step 13) - email_notifier
       ❌ Failed: No invoice to attach

💰 Cost Impact: $0.47 wasted
    - 12 retry attempts across agents C and D
    - 3 dead-end database lookups
    
🔧 Suggested Fix:
    Add validation: `assert warehouse_id in VALID_WAREHOUSES`
    before passing to downstream agents
    
    Estimated savings: $15/week (32 similar cascades detected)
```

---

## Technical Implementation Options

### Core Algorithm: Binary Search + Dependency Graph

The key insight from the AGDebugger paper: Don't check every step linearly. Use binary search.

---

### **Option 1: Binary Search Over Trajectory ⭐⭐⭐⭐⭐ RECOMMENDED**

**What it is:** Check if workflow is "still good" at midpoint. If yes, bug is in second half. If no, bug is in first half. Repeat.

```python
def find_root_cause_binary_search(trace, validator):
    """
    Find the earliest step where workflow became invalid.
    
    Args:
        trace: List of spans in execution order
        validator: Function that checks if state is valid
    
    Returns:
        Index of first invalid span
    """
    def is_valid_at_step(step_index):
        """Replay up to step_index and validate state."""
        partial_state = replay_events(trace[:step_index + 1])
        return validator(partial_state)
    
    left = 0
    right = len(trace) - 1
    first_failure = None
    
    while left <= right:
        mid = (left + right) // 2
        
        if is_valid_at_step(mid):
            # State is still valid at midpoint
            # Bug must be in second half
            left = mid + 1
        else:
            # State is invalid at midpoint
            # This could be the first failure, but there might be earlier
            first_failure = mid
            right = mid - 1
    
    return first_failure

# Example validator
def validate_order_processing_state(state):
    """Check if order state is valid."""
    # Check required fields exist
    if "order_id" not in state:
        return False
    
    # Check warehouse_id is valid
    if "warehouse_id" in state:
        if state["warehouse_id"] not in VALID_WAREHOUSES:
            return False
    
    # Check consistency
    if "tracking_number" in state and "shipping_label" not in state:
        return False  # Can't have tracking without label
    
    return True

# Usage
trace = load_trace("workflow_8829")
root_cause_index = find_root_cause_binary_search(trace, validate_order_processing_state)

print(f"Root cause at step {root_cause_index}: {trace[root_cause_index]['name']}")
```

**Pros:**
- ✅ **O(log n) complexity** - 10,000 steps → only 14 checks
- ✅ **Provably finds earliest failure** - Binary search guarantees
- ✅ **Framework-agnostic** - Works with any trace format
- ✅ **Research-backed** - AGDebugger paper showed 24% better accuracy than manual

**Cons:**
- ⚠️ **Requires replay capability** - Need to reconstruct state at arbitrary points
- ⚠️ **Validator must be defined** - Need domain knowledge to write good validators
- ⚠️ **Expensive for long traces** - Replaying 10K events 14 times can be slow

**When to use:**
- You have event sourcing or checkpointing in place
- You can write validators for your domain
- You want optimal solution

**Development effort:**
- Basic binary search: 3-5 days
- Validator framework: 1 week
- **Difficulty: Medium** ⭐⭐⭐

**Recommendation: 10/10** - This is the right algorithm

---

### **Option 2: Dependency Graph + Backward Traversal ⭐⭐⭐⭐**

**What it is:** Build a graph showing which agents depend on which. When something fails, trace backwards to find what fed it bad data.

```python
from collections import defaultdict, deque

class DependencyGraph:
    def __init__(self):
        self.graph = defaultdict(list)  # node -> list of children
        self.reverse_graph = defaultdict(list)  # node -> list of parents
        self.node_data = {}  # node_id -> span data
    
    def add_edge(self, parent_span_id, child_span_id):
        """Add dependency: child depends on parent."""
        self.graph[parent_span_id].append(child_span_id)
        self.reverse_graph[child_span_id].append(parent_span_id)
    
    def add_node(self, span):
        """Add node data."""
        self.node_data[span["span_id"]] = span
    
    def find_root_causes(self, failed_span_id):
        """
        Trace backwards from failure to find all potential root causes.
        Returns spans in topological order (root causes first).
        """
        # BFS backwards through dependency graph
        visited = set()
        queue = deque([failed_span_id])
        ancestors = []
        
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            
            visited.add(current)
            ancestors.append(current)
            
            # Add parents to queue
            for parent in self.reverse_graph[current]:
                if parent not in visited:
                    queue.append(parent)
        
        # Reverse to get root-first order
        ancestors.reverse()
        
        # Filter to only spans that had errors or produced invalid data
        potential_causes = []
        for span_id in ancestors:
            span = self.node_data[span_id]
            if self.is_suspicious(span):
                potential_causes.append(span)
        
        return potential_causes
    
    def is_suspicious(self, span):
        """Heuristics for whether a span might be root cause."""
        # Failed spans are suspicious
        if span.get("status") == "error":
            return True
        
        # Spans that produced unexpected output
        if "validation_failed" in span.get("metadata", {}):
            return True
        
        # Spans with high retry counts
        if span.get("metadata", {}).get("attempt_number", 1) > 2:
            return True
        
        return False
    
    def calculate_blast_radius(self, root_cause_span_id):
        """
        Calculate how many downstream spans were affected by root cause.
        """
        visited = set()
        queue = deque([root_cause_span_id])
        affected = []
        
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            
            visited.add(current)
            affected.append(self.node_data[current])
            
            # Add children
            for child in self.graph[current]:
                if child not in visited:
                    queue.append(child)
        
        return affected

# Usage
def build_dependency_graph_from_trace(trace):
    graph = DependencyGraph()
    
    for span in trace:
        graph.add_node(span)
        
        # Add edge from parent
        if span.get("parent_span_id"):
            graph.add_edge(span["parent_span_id"], span["span_id"])
    
    return graph

# Example
trace = load_trace("workflow_8829")
graph = build_dependency_graph_from_trace(trace)

# Find failure
failed_span = next(s for s in trace if s.get("status") == "error")

# Trace to root causes
root_causes = graph.find_root_causes(failed_span["span_id"])
print(f"Potential root causes: {[s['name'] for s in root_causes]}")

# Calculate impact
for root in root_causes:
    blast_radius = graph.calculate_blast_radius(root["span_id"])
    print(f"If {root['name']} caused it, {len(blast_radius)} spans affected")
```

**Pros:**
- ✅ **Visualizable** - Can show graph to users
- ✅ **Shows impact** - Blast radius calculation
- ✅ **Works without replay** - Only needs trace data
- ✅ **Fast** - O(n) traversal

**Cons:**
- ⚠️ **Heuristic-based** - "Suspicious" logic might miss subtle bugs
- ⚠️ **Can have false positives** - Might flag innocent ancestors
- ⚠️ **Doesn't prove causation** - Just shows correlation

**When to use:**
- You want quick heuristic answers
- You have a UI to show the dependency graph
- You don't have replay capability yet

**Development effort:**
- Basic implementation: 1 week
- Heuristic tuning: ongoing
- **Difficulty: Medium** ⭐⭐⭐

**Recommendation: 8/10** - Good complement to binary search

---

### **Option 3: Spectral Analysis (Advanced) ⭐⭐⭐**

**What it is:** Statistical approach - run many similar workflows, see which spans correlate with failures.

```python
import numpy as np
from collections import Counter

def calculate_suspiciousness_scores(traces):
    """
    For each unique span type, calculate how often it appears in
    failed vs. successful traces (Tarantula formula).
    
    Returns span types ranked by suspiciousness.
    """
    span_in_failed = Counter()  # How often span appears in failed traces
    span_in_passed = Counter()  # How often span appears in successful traces
    total_failed = 0
    total_passed = 0
    
    for trace in traces:
        is_failed = trace["outcome"] == "failure"
        
        if is_failed:
            total_failed += 1
        else:
            total_passed += 1
        
        # Track which span types appear
        span_types_in_trace = set(s["name"] for s in trace["spans"])
        
        for span_type in span_types_in_trace:
            if is_failed:
                span_in_failed[span_type] += 1
            else:
                span_in_passed[span_type] += 1
    
    # Calculate suspiciousness (Tarantula formula)
    suspiciousness = {}
    
    for span_type in set(span_in_failed.keys()) | set(span_in_passed.keys()):
        failed_freq = span_in_failed[span_type] / total_failed if total_failed > 0 else 0
        passed_freq = span_in_passed[span_type] / total_passed if total_passed > 0 else 0
        
        # Tarantula: failed% / (failed% + passed%)
        if failed_freq + passed_freq > 0:
            suspiciousness[span_type] = failed_freq / (failed_freq + passed_freq)
        else:
            suspiciousness[span_type] = 0
    
    # Rank by suspiciousness
    ranked = sorted(suspiciousness.items(), key=lambda x: x[1], reverse=True)
    
    return ranked

# Usage
traces = load_traces(date_range="last_week")
suspicious_spans = calculate_suspiciousness_scores(traces)

print("Most suspicious span types:")
for span_type, score in suspicious_spans[:5]:
    print(f"  {span_type}: {score:.2%} suspiciousness")
```

**Pros:**
- ✅ **Statistical rigor** - Backed by research
- ✅ **Finds subtle patterns** - Can detect intermittent bugs
- ✅ **No domain knowledge needed** - Works on any trace data

**Cons:**
- ❌ **Requires many traces** - Needs 100+ traces for statistical significance
- ❌ **Correlation ≠ causation** - High suspiciousness doesn't prove root cause
- ❌ **Complex to explain** - Users might not understand scores

**When to use:**
- You have lots of historical trace data
- You want to find patterns across many workflows
- You're okay with probabilistic answers

**Development effort:**
- Basic implementation: 1-2 weeks
- Tuning: ongoing
- **Difficulty: Hard** ⭐⭐⭐⭐

**Recommendation: 6/10** - Interesting research direction, not MVP-critical

---

## Cascade Detection: Recommended Approach

**For MVP:**
1. Start with **dependency graph** (Option 2) - gives you visualization
2. Add **binary search** (Option 1) for precise root-cause finding

**For Production:**
- Binary search is the core algorithm
- Dependency graph for UI/visualization
- Spectral analysis for pattern detection (post-MVP)

---

## Integration: How Cascade Detection Works with Cost Attribution

When you combine Module 1 (Cost) + Module 3 (Cascade):

```python
def analyze_cascade_with_cost(trace_id):
    # 1. Load trace
    trace = load_trace(trace_id)
    
    # 2. Find root cause (binary search)
    root_cause_index = find_root_cause_binary_search(trace, validator)
    root_span = trace[root_cause_index]
    
    # 3. Build dependency graph
    graph = build_dependency_graph_from_trace(trace)
    
    # 4. Calculate blast radius
    affected_spans = graph.calculate_blast_radius(root_span["span_id"])
    
    # 5. Calculate cost impact
    total_waste = sum(s.get("cost_usd", 0) for s in affected_spans)
    
    # 6. Generate report
    return {
        "root_cause": {
            "span_id": root_span["span_id"],
            "name": root_span["name"],
            "step": root_cause_index,
            "decision": root_span.get("decision_made")
        },
        "blast_radius": {
            "affected_spans": len(affected_spans),
            "total_cost_wasted": total_waste,
            "breakdown": [
                {
                    "name": s["name"],
                    "cost": s.get("cost_usd", 0),
                    "why_affected": "downstream of root cause"
                }
                for s in affected_spans
            ]
        },
        "suggested_fix": generate_fix_suggestion(root_span),
        "estimated_savings": estimate_savings(root_span, total_waste)
    }
```

This gives you the dashboard output:
```
Root Cause: inventory_checker (step 5)
Blast Radius: 4 agents failed
Cost Impact: $0.47 wasted
Fix: Add validation
Projected savings: $15/week
```

---

# Module 4: Dry-Run Proxy (Preview Actions Before Execution)

## What It Does (User Perspective)

**Problem:** Agent is about to send 200 emails with hallucinated product names. Or delete a production database. Or execute a $50K trade. Can't preview, can't undo.

**Solution:** Intercept all outbound actions, route to mock/sandbox, show what *would* happen, let user approve.

---

## Technical Implementation Options

### **Option 1: MCP (Model Context Protocol) Integration ⭐⭐⭐⭐⭐**

**What it is:** Anthropic's emerging standard for tool calling. Acts as a gateway between agents and tools.

```python
from mcp import Server, Tool

class DryRunMCPServer(Server):
    def __init__(self):
        super().__init__()
        self.dry_run_mode = True
        self.mock_responses = {}
        self.action_log = []
    
    def register_tool(self, tool: Tool):
        """Wrap tool with dry-run logic."""
        original_execute = tool.execute
        
        def dry_run_wrapper(*args, **kwargs):
            if self.dry_run_mode:
                # Don't execute, return mock response
                action = {
                    "tool": tool.name,
                    "args": args,
                    "kwargs": kwargs,
                    "timestamp": datetime.utcnow(),
                    "would_execute": True
                }
                self.action_log.append(action)
                
                # Return mock response
                if tool.name in self.mock_responses:
                    return self.mock_responses[tool.name]
                else:
                    return {"status": "dry_run", "message": "Would execute in live mode"}
            else:
                # Live mode - actually execute
                return original_execute(*args, **kwargs)
        
        tool.execute = dry_run_wrapper
        super().register_tool(tool)
    
    def preview_actions(self):
        """Show what would happen."""
        return self.action_log
    
    def promote_to_live(self):
        """Switch to live execution."""
        self.dry_run_mode = False
        # Re-run with actual execution
        ...

# Usage
server = DryRunMCPServer()

# Register tools with dry-run wrapping
server.register_tool(Tool(name="send_email", execute=send_email_fn))
server.register_tool(Tool(name="delete_database", execute=delete_db_fn))

# Agent uses tools (in dry-run mode)
agent.run("Clean up old data")

# Preview what it would do
actions = server.preview_actions()
print(actions)
# [
#   {"tool": "delete_database", "args": ["old_users"], "would_execute": True},
#   {"tool": "send_email", "args": ["admin@company.com", "Deleted 1000 users"], "would_execute": True}
# ]

# User reviews, approves
if user_approves(actions):
    server.promote_to_live()
    agent.run("Clean up old data")  # Runs for real this time
```

**Pros:**
- ✅ **Emerging standard** - Anthropic backing, growing ecosystem
- ✅ **Framework-agnostic** - Works with any agent that uses MCP
- ✅ **Clean abstraction** - Tools don't know they're being mocked
- ✅ **Future-proof** - MCP will likely become standard

**Cons:**
- ⚠️ **Early stage** - MCP spec still evolving (as of 2025)
- ⚠️ **Limited adoption** - Not all frameworks support it yet
- ⚠️ **Mock responses need setup** - Must define realistic mocks

**When to use:**
- You're betting on MCP becoming standard
- Your frameworks support MCP
- You want clean, maintainable abstraction

**Development effort:**
- MCP server setup: 1 week
- Mock response library: 2-3 weeks
- **Difficulty: Medium** ⭐⭐⭐

**Recommendation: 9/10** - Best long-term bet

---

### **Option 2: Proxy Layer (HTTP Interception)**

**What it is:** Sit between agent and external APIs, intercept HTTP calls.

```python
from mitmproxy import http
from mitmproxy.tools.main import mitmdump

class DryRunProxy:
    def __init__(self):
        self.intercepted_calls = []
        self.mock_db = {}  # URL pattern -> mock response
    
    def request(self, flow: http.HTTPFlow):
        """Intercept outbound HTTP requests."""
        # Check if this is a risky action
        if self.is_write_operation(flow.request):
            # Log the action
            self.intercepted_calls.append({
                "method": flow.request.method,
                "url": flow.request.url,
                "body": flow.request.content.decode("utf-8"),
                "headers": dict(flow.request.headers),
                "risk": "high",
                "action_type": self.classify_action(flow.request)
            })
            
            # Return mock response instead of executing
            mock_response = self.get_mock_response(flow.request)
            flow.response = http.Response.make(
                200,
                mock_response,
                {"Content-Type": "application/json"}
            )
    
    def is_write_operation(self, request):
        """Check if request is a write (POST, PUT, DELETE)."""
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            return True
        
        # Check URL patterns
        dangerous_patterns = [
            "/api/email/send",
            "/api/database/delete",
            "/api/stripe/charge"
        ]
        return any(pattern in request.url for pattern in dangerous_patterns)
    
    def classify_action(self, request):
        """Classify the type of action."""
        if "/email/" in request.url:
            return "email"
        elif "/database/" in request.url:
            return "database"
        elif "/payment/" in request.url:
            return "payment"
        else:
            return "api_call"
    
    def get_mock_response(self, request):
        """Return realistic mock response."""
        # Match URL pattern to mock
        for pattern, mock in self.mock_db.items():
            if pattern in request.url:
                return mock
        
        # Default mock
        return {"status": "success", "dry_run": True}

# Run proxy
# $ mitmdump -s dry_run_proxy.py

# Configure agent to use proxy
import os
os.environ["HTTP_PROXY"] = "http://localhost:8080"
os.environ["HTTPS_PROXY"] = "http://localhost:8080"

# Agent runs, all HTTP calls intercepted
agent.run("Send marketing emails")

# Review what was intercepted
proxy = DryRunProxy()
print(proxy.intercepted_calls)
# [
#   {
#     "method": "POST",
#     "url": "https://api.sendgrid.com/v3/mail/send",
#     "body": "{\"to\": [\"customer@example.com\"], ...}",
#     "risk": "high",
#     "action_type": "email"
#   }
# ]
```

**Pros:**
- ✅ **Works with any HTTP-based tool** - No code changes needed
- ✅ **Complete interception** - Captures all network traffic
- ✅ **Proven technology** - Proxies well-understood

**Cons:**
- ⚠️ **Only works for HTTP** - Doesn't catch direct database calls, file system ops
- ⚠️ **Setup complexity** - Requires proxy configuration
- ⚠️ **TLS/HTTPS issues** - Need to handle SSL certificate pinning

**When to use:**
- Your agents primarily use REST APIs
- You want quick implementation
- You're comfortable with proxy setup

**Development effort:**
- Basic proxy: 1 week
- Mock response library: 2 weeks
- **Difficulty: Medium** ⭐⭐⭐

**Recommendation: 7/10** - Pragmatic for HTTP-heavy workflows

---

### **Option 3: Decorator-Based Interception**

**What it is:** Wrap risky functions with decorators that check dry-run mode.

```python
from functools import wraps
import inspect

DRY_RUN_MODE = True  # Global flag
ACTION_LOG = []

def safe_action(action_type="generic", risk="medium"):
    """Decorator that intercepts risky actions in dry-run mode."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if DRY_RUN_MODE:
                # Log what would happen
                action = {
                    "function": func.__name__,
                    "action_type": action_type,
                    "risk": risk,
                    "args": args,
                    "kwargs": kwargs,
                    "would_execute": True
                }
                ACTION_LOG.append(action)
                
                # Return mock result
                return {"status": "dry_run", "function": func.__name__}
            else:
                # Actually execute
                return func(*args, **kwargs)
        
        return wrapper
    return decorator

# Decorate your risky functions
@safe_action(action_type="email", risk="high")
def send_email(to, subject, body):
    # Actual email sending logic
    smtp.send(to=to, subject=subject, body=body)

@safe_action(action_type="database", risk="critical")
def delete_users(user_ids):
    # Actual database deletion
    db.execute(f"DELETE FROM users WHERE id IN {user_ids}")

@safe_action(action_type="payment", risk="critical")
def charge_card(amount, card_token):
    # Actual payment processing
    stripe.charge(amount=amount, source=card_token)

# Agent code
def cleanup_old_users():
    old_users = [1, 2, 3]
    delete_users(old_users)
    send_email("admin@company.com", "Cleanup complete", f"Deleted {len(old_users)} users")

# Run in dry-run mode
DRY_RUN_MODE = True
cleanup_old_users()

# Review what would happen
print(ACTION_LOG)
# [
#   {"function": "delete_users", "action_type": "database", "risk": "critical", "args": [[1,2,3]]},
#   {"function": "send_email", "action_type": "email", "risk": "high", "args": ["admin@...", "..."]}
# ]

# User approves
if user_approves(ACTION_LOG):
    DRY_RUN_MODE = False
    ACTION_LOG.clear()
    cleanup_old_users()  # Runs for real
```

**Pros:**
- ✅ **Dead simple** - Just add decorators
- ✅ **Works with any function** - Database, file system, HTTP, anything
- ✅ **No dependencies** - Pure Python

**Cons:**
- ❌ **Requires code changes** - Must decorate every risky function
- ❌ **Easy to forget** - If you forget to decorate, action executes live
- ❌ **Global state** - DRY_RUN_MODE is global (threading issues)

**When to use:**
- You have full control over codebase
- You have a small, well-defined set of risky functions
- Prototyping

**Development effort:**
- Basic decorators: 2-3 days
- **Difficulty: Easy** ⭐

**Recommendation: 5/10** - Good for prototypes, risky for production

---

## Dry-Run Proxy: Recommendation

**For MVP:**
- Start with **decorator-based** (Option 3) to validate the concept quickly
- Migrate to **MCP** (Option 1) once it's more mature

**For Production:**
- **MCP** is the future - bet on this

**Skip:**
- HTTP proxy unless you're 100% HTTP-based

---

# MVP Implementation Roadmap

## Week-by-Week Build Plan

### **Weeks 1-4: Module 1 - Decision-Level Cost Attribution**

**Week 1: Instrumentation Setup**
- Choose: OpenTelemetry or Langfuse
- Set up basic span capture
- Test with simple LLM call
- **Deliverable:** Can capture one trace with cost

**Week 2: Decision-Path Costing**
- Implement recursive cost aggregation
- Build parent-child relationship tracker
- **Deliverable:** Can show "this decision cost $X (including children)"

**Week 3: Waste Detection**
- Implement loop detection algorithm
- Implement retry bloat detection
- **Deliverable:** Can flag "this span retried 5x, wasted $Y"

**Week 4: Dashboard V1**
- Build simple UI (React + Tailwind)
- Show heatmap of expensive nodes
- Show ranked list of wasteful paths
- **Deliverable:** Working dashboard

### **Weeks 5-8: Module 2 - Time-Travel Debugging**

**Week 5: Event Store**
- Implement event sourcing pattern
- Store all events to database
- **Deliverable:** Every agent action logged as event

**Week 6: Replay Engine**
- Implement event replay
- Test: can reconstruct state at any point
- **Deliverable:** Can replay to checkpoint N

**Week 7: Fork Logic**
- Implement fork: load state + inject modification
- **Deliverable:** Can test "what if I changed X at step Y?"

**Week 8: Diff UI**
- Build side-by-side comparison view
- **Deliverable:** Visual diff of original vs. fork

### **Weeks 9-12: Module 3 - Cascade Detection**

**Week 9: Dependency Graph**
- Build graph from trace data
- Implement backward traversal
- **Deliverable:** Can show "Y depends on X"

**Week 10: Binary Search**
- Implement binary search over trajectory
- Integrate with replay engine
- **Deliverable:** Can find root cause in O(log n)

**Week 11: Blast Radius**
- Calculate downstream impact
- Show affected spans
- **Deliverable:** "This bug affected 12 downstream nodes"

**Week 12: Integration**
- Combine cost + cascade data
- **Deliverable:** "Root cause cost $15/week, here's the fix"

### **Month 4+: Module 4 - Dry-Run Proxy (Post-MVP)**

---

## Tech Stack Recommendations

### **Backend:**
- **Language:** Python 3.11+
- **Framework:** FastAPI
- **Database:** PostgreSQL (spans, events) + MongoDB (flexible trace data)
- **Queue:** Redis for async processing
- **Tracing:** OpenTelemetry SDK

### **Frontend:**
- **Framework:** Next.js 14 (React)
- **Styling:** Tailwind CSS
- **Charts:** Recharts or D3.js
- **State:** Zustand or React Context

### **Infrastructure:**
- **Deployment:** Docker + Kubernetes
- **Storage:** S3 for large traces
- **Monitoring:** (Ironic, but) Datadog for platform health

---

## Success Metrics

**Week 4 (End of Module 1):**
- Can track cost per decision (not just per call)
- Can detect at least one type of waste (loops or retries)
- Dashboard shows top 3 expensive paths

**Week 8 (End of Module 2):**
- Can replay any trace
- Can fork and test alternative
- Side-by-side diff works

**Week 12 (End of Module 3):**
- Can find root cause in <1 second
- Blast radius calculation accurate
- Cost impact shown per cascade

---

## What You'll Have After 12 Weeks

A working platform that:

1. **Captures every agent action** with cost + context
2. **Shows where money is wasted** (loops, retries, dead-ends)
3. **Lets you replay and test fixes** without waiting for real traffic
4. **Automatically finds root causes** of cascading failures
5. **Quantifies impact** in dollars per bug

**Competitive moat:**
- LangGraph Studio: Time-travel, but only for LangGraph
- Datadog/Langfuse: Cost tracking, but per-call not per-decision
- AgentOps: Session replay, but view-only not re-executable
- **You:** All of the above, framework-agnostic, production-ready

---

## Next Steps

1. **Choose your stack:**
   - For fast MVP: Langfuse + LangGraph checkpoints
   - For production: OpenTelemetry + Event Sourcing

2. **Start with Module 1** (Weeks 1-4)
   - This validates core value prop
   - Can sell this alone

3. **Get one design partner**
   - Find a company with multi-agent workflows
   - Embed with their team
   - Build exactly what they need

4. **Ship fast, iterate**
   - Week 4: First demo
   - Week 8: Beta customers
   - Week 12: Public launch

---

## Questions to Resolve Before Starting

1. **Framework focus:** Start LangChain-only or multi-framework from day 1?
   - **Recommendation:** LangChain-only for MVP, add others in Month 2

2. **Self-hosted or cloud:** Offer self-hosted option or cloud-only?
   - **Recommendation:** Cloud-first, add self-hosted once validated

3. **Pricing model:** Per-trace, per-month, or usage-based?
   - **Recommendation:** Freemium (10K traces/mo free) + $99/mo unlimited

4. **Open source:** Open source the core or keep proprietary?
   - **Recommendation:** Open core (instrumentation) + closed UI/analytics

---

## Final Recommendation: Start Here

**Day 1 focus:**
```python
# Get this working first
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("my_agent_decision") as span:
    span.set_attribute("cost_usd", 0.01)
    span.set_attribute("triggered_by", "user_query")
    # Your agent code
    
# Once this works, you have 80% of the foundation
```

Build on that foundation for 12 weeks. Ship it. Win.
