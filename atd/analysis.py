from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from atd.trace import Span, Trace


def cost_rollup(trace: Trace) -> dict[str, Any]:
    by_model: dict[str, dict[str, float]] = defaultdict(
        lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    )
    for span in trace.spans:
        if span.kind != "llm":
            continue
        key = span.model or "unknown"
        bucket = by_model[key]
        bucket["calls"] += 1
        bucket["tokens_in"] += span.tokens_in
        bucket["tokens_out"] += span.tokens_out
        bucket["cost_usd"] += span.cost_usd
    total = {
        "calls": sum(b["calls"] for b in by_model.values()),
        "tokens_in": sum(b["tokens_in"] for b in by_model.values()),
        "tokens_out": sum(b["tokens_out"] for b in by_model.values()),
        "cost_usd": round(sum(b["cost_usd"] for b in by_model.values()), 6),
    }
    return {"by_model": {k: dict(v) for k, v in by_model.items()}, "total": total}


def critical_path(trace: Trace) -> list[str]:
    """Longest-duration root-to-leaf chain. Where the wall-clock actually went."""
    memo: dict[str, tuple[float, list[str]]] = {}

    def walk(span: Span) -> tuple[float, list[str]]:
        if span.span_id in memo:
            return memo[span.span_id]
        children = trace.children_of(span.span_id)
        best_extra, best_chain = 0.0, []
        for child in children:
            extra, chain = walk(child)
            if extra > best_extra:
                best_extra, best_chain = extra, chain
        result = (span.duration_ms + best_extra, [span.span_id] + best_chain)
        memo[span.span_id] = result
        return result

    best: tuple[float, list[str]] = (0.0, [])
    for root in trace.roots():
        candidate = walk(root)
        if candidate[0] > best[0]:
            best = candidate
    return best[1]


def failure_points(trace: Trace) -> list[dict[str, Any]]:
    """Failed spans plus the ancestors they propagated into."""
    out = []
    for span in trace.spans:
        if span.status == "ok":
            continue
        ancestors = []
        cursor = span.parent_id
        seen = set()
        while cursor and cursor not in seen:
            seen.add(cursor)
            parent = trace.by_id(cursor)
            if parent is None:
                break
            ancestors.append(parent.name)
            cursor = parent.parent_id
        out.append(
            {
                "span_id": span.span_id,
                "name": span.name,
                "kind": span.kind,
                "status": span.status,
                "error": span.error,
                "propagated_to": ancestors,
            }
        )
    return out


def _call_signature(span: Span) -> str:
    try:
        payload = json.dumps(span.input, sort_keys=True, default=str)
    except (TypeError, ValueError):
        payload = str(span.input)
    return f"{span.name}|{payload}"


def repeated_calls(trace: Trace, threshold: int = 2) -> list[dict[str, Any]]:
    """Identical tool calls repeated - the classic agent retry loop."""
    groups: dict[str, list[Span]] = defaultdict(list)
    for span in trace.spans:
        if span.kind in ("tool", "retrieval"):
            groups[_call_signature(span)].append(span)

    out = []
    for signature, spans in groups.items():
        if len(spans) < threshold:
            continue
        name = signature.split("|", 1)[0]
        out.append(
            {
                "name": name,
                "count": len(spans),
                "span_ids": [s.span_id for s in spans],
                "all_failed": all(s.status != "ok" for s in spans),
                "wasted_ms": round(sum(s.duration_ms for s in spans[1:]), 3),
            }
        )
    return sorted(out, key=lambda r: r["count"], reverse=True)


def stuck_loops(trace: Trace, threshold: int = 2) -> list[dict[str, Any]]:
    """Same error text repeating - the agent is not making progress."""
    groups: dict[str, list[Span]] = defaultdict(list)
    for span in trace.spans:
        if span.status != "ok" and span.error:
            groups[span.error].append(span)

    return [
        {
            "error": error,
            "count": len(spans),
            "span_ids": [s.span_id for s in spans],
            "names": sorted({s.name for s in spans}),
        }
        for error, spans in groups.items()
        if len(spans) >= threshold
    ]


def tool_stats(trace: Trace) -> list[dict[str, Any]]:
    groups: dict[str, list[Span]] = defaultdict(list)
    for span in trace.spans:
        if span.kind in ("tool", "retrieval"):
            groups[span.name].append(span)

    out = []
    for name, spans in groups.items():
        errors = [s for s in spans if s.status != "ok"]
        durations = [s.duration_ms for s in spans]
        out.append(
            {
                "name": name,
                "calls": len(spans),
                "errors": len(errors),
                "error_rate": round(len(errors) / len(spans), 4),
                "total_ms": round(sum(durations), 3),
                "avg_ms": round(sum(durations) / len(spans), 3),
                "max_ms": round(max(durations), 3),
            }
        )
    return sorted(out, key=lambda r: r["total_ms"], reverse=True)


def slowest_spans(trace: Trace, limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(trace.spans, key=lambda s: s.duration_ms, reverse=True)
    return [
        {
            "span_id": s.span_id,
            "name": s.name,
            "kind": s.kind,
            "duration_ms": round(s.duration_ms, 3),
            "share": round(s.duration_ms / trace.duration_ms, 4) if trace.duration_ms else 0.0,
        }
        for s in ranked[:limit]
    ]


def analyze(trace: Trace) -> dict[str, Any]:
    errors = [s for s in trace.spans if s.status != "ok"]
    path = critical_path(trace)
    return {
        "trace_id": trace.trace_id,
        "summary": {
            "spans": len(trace.spans),
            "duration_ms": round(trace.duration_ms, 3),
            "errors": len(errors),
            "error_rate": round(len(errors) / len(trace.spans), 4) if trace.spans else 0.0,
            "llm_calls": len([s for s in trace.spans if s.kind == "llm"]),
            "tool_calls": len([s for s in trace.spans if s.kind == "tool"]),
        },
        "cost": cost_rollup(trace),
        "critical_path": [
            {"span_id": sid, "name": trace.by_id(sid).name if trace.by_id(sid) else sid}
            for sid in path
        ],
        "failures": failure_points(trace),
        "repeated_calls": repeated_calls(trace),
        "stuck_loops": stuck_loops(trace),
        "tools": tool_stats(trace),
        "slowest": slowest_spans(trace),
    }
