# Decision-Level Cost Attribution - Visual Guide

## What Competitors Show vs. What We Show

### Langfuse/Braintrust (Flat Cost View)
```
Trace #123 - Total: $0.45
├─ LLM Call 1: $0.05
├─ LLM Call 2: $0.12
├─ LLM Call 3: $0.08
├─ LLM Call 4: $0.15
└─ LLM Call 5: $0.05
```
**Problem:** Can't tell which decision triggered which costs.

---

### Our Platform (Decision-Level Aggregation)
```
Trace #123 - Total: $0.45

Agent: Coordinator ($0.05 direct, $0.40 downstream = $0.45 total)
├─ Agent: Classifier ($0.12 direct, $0.28 downstream = $0.40 total)
│  ├─ Agent: Validator ($0.08 direct, $0.16 downstream = $0.24 total)
│  │  ├─ LLM Call: Validate schema ($0.08)
│  │  └─ Agent: Retry Validator ($0.08) ⚠️ RETRY BLOAT
│  │     └─ LLM Call: Validate schema ($0.08) ⚠️ DUPLICATE
│  └─ Agent: Formatter ($0.04)
└─ Agent: Logger ($0.05)
```
**Insight:** Validator decision cost $0.24 total (not just $0.08) because it triggered a retry.

---

## Multi-Agent Example: Customer Support Workflow

### The Agent Mesh
```
User Query
    ↓
[Router Agent] ──→ Decides which workflow
    ↓
[Classifier] ──→ Categorizes intent
    ↓
[Retriever] ──→ Searches knowledge base
    ↓                ↓
[Validator]    [Fallback Retriever] ← Called on validation failure
    ↓
[Response Generator]
```

### Span Tree with Costs
```
span_001: Router Agent
├─ cost_direct: $0.02
├─ cost_downstream: $0.43
├─ cost_total: $0.45
└─ children:
    │
    └─ span_002: Classifier Agent
       ├─ cost_direct: $0.05
       ├─ cost_downstream: $0.36
       ├─ cost_total: $0.41
       └─ children:
           │
           ├─ span_003: Retriever Agent
           │  ├─ cost_direct: $0.08
           │  ├─ cost_downstream: $0.00
           │  └─ cost_total: $0.08
           │
           ├─ span_004: Validator Agent (FAILED)
           │  ├─ cost_direct: $0.06
           │  ├─ cost_downstream: $0.12
           │  ├─ cost_total: $0.18  ⚠️ DEAD-END COST
           │  ├─ status: "error"
           │  └─ children:
           │      └─ span_005: Check compliance
           │         ├─ cost_direct: $0.06
           │         └─ retry_attempt: 2  ⚠️ RETRY
           │            └─ span_006: Check compliance (retry)
           │               └─ cost_direct: $0.06
           │
           └─ span_007: Fallback Retriever (TRIGGERED BY FAILURE)
              ├─ cost_direct: $0.10
              ├─ cost_downstream: $0.00
              └─ cost_total: $0.10
```

---

## The Algorithm: Step-by-Step

### Input: Span Database
```python
spans_db = {
    "span_001": {
        "agent": "Router",
        "parent": None,
        "cost": 0.02,
        "children": ["span_002"]
    },
    "span_002": {
        "agent": "Classifier",
        "parent": "span_001",
        "cost": 0.05,
        "children": ["span_003", "span_004", "span_007"]
    },
    "span_003": {
        "agent": "Retriever",
        "parent": "span_002",
        "cost": 0.08,
        "children": []
    },
    "span_004": {
        "agent": "Validator",
        "parent": "span_002",
        "cost": 0.06,
        "status": "error",
        "children": ["span_005", "span_006"]
    },
    "span_005": {
        "agent": "Check compliance",
        "parent": "span_004",
        "cost": 0.06,
        "attempt": 1,
        "children": []
    },
    "span_006": {
        "agent": "Check compliance",
        "parent": "span_004",
        "cost": 0.06,
        "attempt": 2,  # RETRY!
        "children": []
    },
    "span_007": {
        "agent": "Fallback Retriever",
        "parent": "span_002",
        "cost": 0.10,
        "triggered_by": "span_004_failure",
        "children": []
    }
}
```

### Step 1: Start at Root (Router)
```
calculate_decision_path_cost("span_001")
├─ Direct cost: $0.02
└─ Find children: ["span_002"]
    └─ Recursively calculate span_002...
```

### Step 2: Calculate Classifier (span_002)
```
calculate_decision_path_cost("span_002")
├─ Direct cost: $0.05
└─ Find children: ["span_003", "span_004", "span_007"]
    ├─ Recursively calculate span_003... → $0.08
    ├─ Recursively calculate span_004... → $0.18
    └─ Recursively calculate span_007... → $0.10

Total child cost: $0.08 + $0.18 + $0.10 = $0.36
Total cost: $0.05 + $0.36 = $0.41
```

### Step 3: Calculate Validator (span_004) - Key Insight
```
calculate_decision_path_cost("span_004")
├─ Direct cost: $0.06
├─ Status: "error"  ⚠️ FAILED
└─ Find children: ["span_005", "span_006"]
    ├─ span_005: $0.06
    └─ span_006: $0.06 (same agent name!) ⚠️ RETRY DETECTED

Total child cost: $0.06 + $0.06 = $0.12
Total cost: $0.06 + $0.12 = $0.18

WASTE DETECTED:
- Type: "dead_end"
  Reason: "Spent $0.18 but ended in failure"

- Type: "retry_bloat"
  Reason: "Check compliance called 2x (wasted $0.06)"
```

### Step 4: Detect Cascade Impact
```
Validator failure (span_004) triggered:
└─ Fallback Retriever (span_007): $0.10

Blast radius:
- Direct failure cost: $0.18
- Triggered fallback cost: $0.10
- Total cascade cost: $0.28
```

---

## Output Format

### JSON Output
```json
{
  "decision_span_id": "span_004",
  "decision_name": "Validator Agent",
  "agent_id": "validator_v1",
  "direct_cost": 0.06,
  "child_cost": 0.12,
  "total_cost": 0.18,
  "status": "error",
  "child_breakdown": [
    {
      "span_id": "span_005",
      "name": "Check compliance",
      "cost": 0.06,
      "attempt": 1
    },
    {
      "span_id": "span_006",
      "name": "Check compliance",
      "cost": 0.06,
      "attempt": 2
    }
  ],
  "waste_detected": [
    {
      "type": "dead_end",
      "severity": "high",
      "wasted_cost": 0.18,
      "details": "Agent spent $0.18 but ended in failure"
    },
    {
      "type": "retry_bloat",
      "severity": "medium",
      "wasted_cost": 0.06,
      "details": "Check compliance retried 2x, wasted $0.06"
    }
  ],
  "cascade_impact": {
    "triggered_spans": ["span_007"],
    "cascade_cost": 0.10,
    "total_impact": 0.28
  }
}
```

### Dashboard View
```
┌─────────────────────────────────────────────────────────────┐
│  Agent: Validator                                           │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                             │
│  💰 Cost Breakdown:                                         │
│    Direct:     $0.06                                        │
│    Downstream: $0.12                                        │
│    Total:      $0.18 ████████████░░░░░░ (40% of workflow)  │
│                                                             │
│  ⚠️  Waste Detected:                                        │
│    • Dead-end: $0.18 wasted (agent failed)                 │
│    • Retry bloat: "Check compliance" called 2x             │
│                                                             │
│  💥 Cascade Impact:                                         │
│    • Triggered Fallback Retriever: $0.10                   │
│    • Total blast radius: $0.28                             │
│                                                             │
│  🔧 Suggested Fix:                                          │
│    Add validation before calling Validator to reduce       │
│    failure rate. Estimated savings: $120/month             │
└─────────────────────────────────────────────────────────────┘
```

---

## Visual: Agent Mesh with Cost Attribution

```
                    User Query
                        │
                        ▼
        ┌───────────────────────────────┐
        │   Router Agent                │
        │   Direct: $0.02               │
        │   Downstream: $0.43           │
        │   Total: $0.45                │
        └───────────────┬───────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │   Classifier Agent            │
        │   Direct: $0.05               │
        │   Downstream: $0.36           │
        │   Total: $0.41                │
        └───────┬───────────────┬───────┘
                │               │
        ┌───────┴─────┐    ┌────┴────────────┐
        │             │    │                  │
        ▼             ▼    ▼                  ▼
    ┌─────────┐  ┌──────────────┐      ┌─────────────┐
    │Retriever│  │  Validator   │      │  Fallback   │
    │$0.08    │  │  ❌ FAILED   │ ───▶ │  Retriever  │
    │         │  │  Total: $0.18│      │  $0.10      │
    └─────────┘  │  ⚠️ WASTE    │      │ (triggered) │
                 └──────┬───────┘      └─────────────┘
                        │
                ┌───────┴────────┐
                │                │
                ▼                ▼
         ┌──────────┐    ┌──────────┐
         │ Check    │    │ Check    │
         │ comply   │    │ comply   │
         │ $0.06    │    │ $0.06    │
         │ (try 1)  │    │ (RETRY)  │
         └──────────┘    └──────────┘
                         ⚠️ DUPLICATE
```

**Key Insights from Visualization:**
1. **Classifier looks cheap** ($0.05 direct) but **actually costs $0.41** with downstream
2. **Validator is the problem**: $0.18 total cost, all wasted (failed)
3. **Cascade detected**: Validator failure → triggered $0.10 fallback
4. **Total waste**: $0.28 (62% of workflow cost!)

---

## Comparison: What Users See

### Langfuse/Braintrust
```
Total trace cost: $0.45
Top expensive calls:
1. Fallback Retriever: $0.10
2. Retriever: $0.08
3. Validator: $0.06
4. Check compliance: $0.06
5. Classifier: $0.05
```
❌ **Problem**: Validator looks cheap, don't know it wasted $0.18

### Our Platform
```
Total trace cost: $0.45
Wasteful decisions (sorted by total cost):
1. ⚠️ Validator: $0.18 total (FAILED, triggered $0.10 fallback)
   └─ Fix: Add pre-validation check
   └─ Savings: $120/month

2. Classifier: $0.41 total ($0.05 direct + $0.36 downstream)
   └─ Expensive but productive

3. Fallback Retriever: $0.10 (only triggered due to Validator)
   └─ Secondary issue
```
✅ **Insight**: Fix Validator → save $0.28 per execution (62%)

---

## Code Implementation

```python
def calculate_decision_path_cost(span_id, span_db):
    """
    Recursively calculate total cost of agent decision.

    Returns decision cost + all downstream costs triggered.
    """
    span = span_db[span_id]
    direct_cost = span.get("cost", 0)

    # Find all child spans (downstream work triggered by this decision)
    children = [
        span_db[child_id]
        for child_id in span.get("children", [])
    ]

    # Recursively calculate child costs
    child_analyses = []
    total_child_cost = 0

    for child in children:
        child_analysis = calculate_decision_path_cost(
            child["span_id"],
            span_db
        )
        child_analyses.append(child_analysis)
        total_child_cost += child_analysis["total_cost"]

    # Detect waste patterns
    waste = detect_waste(span, children)

    # Calculate cascade impact
    cascade = detect_cascade(span, children, span_db)

    return {
        "decision_span_id": span_id,
        "decision_name": span["agent"],
        "agent_id": span.get("agent_id"),
        "direct_cost": direct_cost,
        "child_cost": total_child_cost,
        "total_cost": direct_cost + total_child_cost,
        "status": span.get("status", "success"),
        "child_breakdown": child_analyses,
        "waste_detected": waste,
        "cascade_impact": cascade
    }


def detect_waste(span, children):
    """Detect waste patterns in agent decisions."""
    waste = []

    # Pattern 1: Retry bloat (same agent called multiple times)
    agent_names = [c["agent"] for c in children]
    for name in set(agent_names):
        count = agent_names.count(name)
        if count > 1:
            wasted_cost = sum(
                c["cost"] for c in children
                if c["agent"] == name
            ) - (sum(c["cost"] for c in children if c["agent"] == name) / count)

            waste.append({
                "type": "retry_bloat",
                "severity": "high" if count > 3 else "medium",
                "agent": name,
                "retry_count": count,
                "wasted_cost": wasted_cost,
                "details": f"{name} called {count}x (likely stuck)"
            })

    # Pattern 2: Dead-end (spent money but failed)
    if span.get("status") == "error" and span.get("cost", 0) > 0:
        total_wasted = span["cost"] + sum(c["cost"] for c in children)
        waste.append({
            "type": "dead_end",
            "severity": "high",
            "wasted_cost": total_wasted,
            "details": f"Spent ${total_wasted:.2f} but ended in failure"
        })

    return waste


def detect_cascade(span, children, span_db):
    """Detect if this agent's failure triggered downstream work."""
    if span.get("status") != "error":
        return None

    # Find spans triggered by this failure
    triggered = []
    for other_span in span_db.values():
        if other_span.get("triggered_by") == f"{span['span_id']}_failure":
            triggered.append(other_span)

    if not triggered:
        return None

    cascade_cost = sum(s.get("cost", 0) for s in triggered)

    return {
        "triggered_spans": [s["span_id"] for s in triggered],
        "cascade_cost": cascade_cost,
        "total_impact": span.get("cost", 0) + cascade_cost
    }
```

---

## Why This Matters

### Traditional Observability
"Your workflow costs $0.45"
→ User: "Okay, but where do I optimize?"

### Decision-Level Cost Attribution
"Your workflow costs $0.45, but $0.28 (62%) is wasted on Validator failures and cascades"
→ User: "Fix Validator, save $120/month immediately"

**This is the differentiator.** Competitors show costs. We show **waste with root causes and fix recommendations.**
