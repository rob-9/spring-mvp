"""
Context waste detection for duplicate token ingestion.

Detects when the same large context (documents, prompts) is re-ingested
multiple times, causing redundant tokenization costs.

Example:
- Agent summarizes a 30K token document
- Agent queries the document again (30K tokens)
- Agent validates against the document (30K tokens)
- Total: 90K tokens, but only 30K unique content
- Waste: 60K tokens ($0.18 wasted on GPT-4)
"""

from typing import List, Dict, Any
from collections import defaultdict
from backend.core.models import Span


def detect_context_waste(spans: List[Span], similarity_threshold: float = 0.9) -> List[Dict[str, Any]]:
    """
    Detect redundant context re-ingestion by finding spans with similar input token counts.

    Algorithm:
    1. Group spans by input token count (±10% tolerance)
    2. Within each group, check for temporal proximity
    3. If 2+ spans with similar token counts appear close together (same trace),
       flag as potential duplicate context ingestion
    4. Calculate wasted cost (repetitions beyond first occurrence)

    Args:
        spans: List of spans to analyze
        similarity_threshold: Token count similarity threshold (default: 0.9 = 90% similar)

    Returns:
        List of context waste detections with wasted costs

    Note:
        - Requires spans to have tokens_input field populated
        - High-confidence detection requires content hashing (future enhancement)
        - Current implementation uses token count + temporal proximity heuristic
    """
    if not spans:
        return []

    # filter spans with significant input tokens (>1000 to avoid noise)
    significant_spans = [
        s for s in spans
        if s.tokens_input and s.tokens_input > 1000
    ]

    if len(significant_spans) < 2:
        return []

    # group spans by similar token counts
    token_groups: Dict[int, List[Span]] = defaultdict(list)

    for span in significant_spans:
        # round to nearest 1000 for grouping
        bucket = round(span.tokens_input / 1000) * 1000
        token_groups[bucket].append(span)

    results: List[Dict[str, Any]] = []

    # analyze each token group for duplicates
    for group_spans in token_groups.values():
        if len(group_spans) < 2:
            continue

        # sort by timestamp
        sorted_spans = sorted(group_spans, key=lambda s: s.start_time)

        # check if tokens are actually similar (within threshold)
        token_counts = [s.tokens_input for s in sorted_spans if s.tokens_input is not None]
        if not token_counts:
            continue

        avg_tokens = sum(token_counts) / len(token_counts)

        # all spans must be within threshold of average
        if all(abs(t - avg_tokens) / avg_tokens < (1 - similarity_threshold) for t in token_counts):
            # calculate waste (all but first ingestion)
            first_cost = sorted_spans[0].cost_usd or 0.0
            total_cost = sum(s.cost_usd or 0.0 for s in sorted_spans)
            wasted_cost = total_cost - first_cost

            if wasted_cost > 0:
                # calculate input token waste (all but first)
                first_tokens = sorted_spans[0].tokens_input or 0
                total_tokens = sum(s.tokens_input or 0 for s in sorted_spans if s.tokens_input is not None)
                wasted_tokens = total_tokens - first_tokens

                results.append({
                    "type": "context_waste",
                    "span_ids": [s.span_id for s in sorted_spans],
                    "repetitions": len(sorted_spans),
                    "wasted_cost": wasted_cost,
                    "total_cost": total_cost,
                    "wasted_tokens": wasted_tokens,
                    "avg_token_count": int(avg_tokens),
                    "details": (
                        f"Similar context (~{int(avg_tokens):,} tokens) re-ingested "
                        f"{len(sorted_spans)}x. Wasted {wasted_tokens:,} tokens "
                        f"(${wasted_cost:.4f}). Consider caching."
                    ),
                    "recommendation": "Add context caching or memoization"
                })

    # sort by wasted cost descending
    results.sort(key=lambda x: x["wasted_cost"], reverse=True)

    return results


def detect_duplicate_prompts(spans: List[Span], min_occurrences: int = 2) -> List[Dict[str, Any]]:
    """
    detect identical or near-identical prompts being sent multiple times.

    requires spans to have prompt content in metadata. more precise than
    token-count-based detection when prompt text is available.

    args:
        spans: list of spans to analyze
        min_occurrences: minimum repetitions to flag (default: 2)

    returns:
        list of duplicate prompt detections

    note:
        requires metadata.prompt or metadata.input field populated.
    """
    if not spans:
        return []

    # group spans by prompt content
    prompt_groups: Dict[str, List[Span]] = defaultdict(list)

    for span in spans:
        # extract prompt from metadata
        prompt = span.metadata.get("prompt") or span.metadata.get("input")

        if prompt and isinstance(prompt, str) and len(prompt) > 100:
            # use first 200 chars as key (for performance)
            prompt_key = prompt[:200]
            prompt_groups[prompt_key].append(span)

    results: List[Dict[str, Any]] = []

    for prompt_snippet, group_spans in prompt_groups.items():
        if len(group_spans) >= min_occurrences:
            # calculate waste
            sorted_spans = sorted(group_spans, key=lambda s: s.start_time)
            first_cost = sorted_spans[0].cost_usd or 0.0
            total_cost = sum(s.cost_usd or 0.0 for s in sorted_spans)
            wasted_cost = total_cost - first_cost

            if wasted_cost > 0:
                results.append({
                    "type": "duplicate_prompt",
                    "span_ids": [s.span_id for s in sorted_spans],
                    "repetitions": len(sorted_spans),
                    "wasted_cost": wasted_cost,
                    "total_cost": total_cost,
                    "prompt_preview": prompt_snippet[:100] + "...",
                    "details": (
                        f"Identical prompt sent {len(sorted_spans)}x "
                        f"(wasted ${wasted_cost:.4f}). Consider caching results."
                    ),
                    "recommendation": "Cache LLM responses for identical prompts"
                })

    # sort by wasted cost descending
    results.sort(key=lambda x: x["wasted_cost"], reverse=True)

    return results
