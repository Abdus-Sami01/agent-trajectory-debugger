from __future__ import annotations

from collections import defaultdict
from typing import Any

from atd.analysis import cost_rollup
from atd.trace import Span, Trace


def _signature(span: Span) -> str:
    """Identity across runs. span_ids are per-run, so match on structural position."""
    return f"{span.kind}:{span.name}"


def _grouped(trace: Trace) -> dict[str, list[Span]]:
    groups: dict[str, list[Span]] = defaultdict(list)
    for span in trace.spans:
        groups[_signature(span)].append(span)
    return groups


def _pct_change(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return round((after - before) / before, 4)


def diff_traces(baseline: Trace, candidate: Trace, regression_pct: float = 0.20) -> dict[str, Any]:
    """Compare two runs of the same workflow.

    Spans are matched by kind+name, not span_id, because ids are per-run. A step
    appearing N times in one run and M in the other is reported as a count change,
    which is how retry-loop regressions surface.
    """
    base_groups, cand_groups = _grouped(baseline), _grouped(candidate)
    all_keys = sorted(set(base_groups) | set(cand_groups))

    added, removed, changed, unchanged = [], [], [], []

    for key in all_keys:
        before, after = base_groups.get(key, []), cand_groups.get(key, [])
        kind, name = key.split(":", 1)
        before_ms = sum(s.duration_ms for s in before)
        after_ms = sum(s.duration_ms for s in after)
        before_err = len([s for s in before if s.status != "ok"])
        after_err = len([s for s in after if s.status != "ok"])

        if not before:
            added.append({"name": name, "kind": kind, "calls": len(after),
                          "duration_ms": round(after_ms, 3), "errors": after_err})
            continue
        if not after:
            removed.append({"name": name, "kind": kind, "calls": len(before),
                            "duration_ms": round(before_ms, 3), "errors": before_err})
            continue

        entry = {
            "name": name,
            "kind": kind,
            "calls_before": len(before),
            "calls_after": len(after),
            "duration_before_ms": round(before_ms, 3),
            "duration_after_ms": round(after_ms, 3),
            "duration_delta_ms": round(after_ms - before_ms, 3),
            "duration_pct": _pct_change(before_ms, after_ms),
            "errors_before": before_err,
            "errors_after": after_err,
        }
        pct = entry["duration_pct"]
        entry["slower"] = pct is not None and pct >= regression_pct
        entry["newly_failing"] = after_err > before_err
        entry["more_calls"] = len(after) > len(before)

        if entry["slower"] or entry["newly_failing"] or entry["more_calls"] or \
           len(after) != len(before) or after_err != before_err or abs(after_ms - before_ms) > 1e-9:
            changed.append(entry)
        else:
            unchanged.append({"name": name, "kind": kind})

    base_cost = cost_rollup(baseline)["total"]
    cand_cost = cost_rollup(candidate)["total"]

    base_errors = len([s for s in baseline.spans if s.status != "ok"])
    cand_errors = len([s for s in candidate.spans if s.status != "ok"])

    regressions = [c for c in changed if c["slower"] or c["newly_failing"] or c["more_calls"]]

    return {
        "baseline_id": baseline.trace_id,
        "candidate_id": candidate.trace_id,
        "regression_pct_threshold": regression_pct,
        "totals": {
            "duration_before_ms": round(baseline.duration_ms, 3),
            "duration_after_ms": round(candidate.duration_ms, 3),
            "duration_delta_ms": round(candidate.duration_ms - baseline.duration_ms, 3),
            "duration_pct": _pct_change(baseline.duration_ms, candidate.duration_ms),
            "spans_before": len(baseline.spans),
            "spans_after": len(candidate.spans),
            "errors_before": base_errors,
            "errors_after": cand_errors,
            "cost_before_usd": base_cost["cost_usd"],
            "cost_after_usd": cand_cost["cost_usd"],
            "cost_delta_usd": round(cand_cost["cost_usd"] - base_cost["cost_usd"], 6),
            "tokens_before": base_cost["tokens_in"] + base_cost["tokens_out"],
            "tokens_after": cand_cost["tokens_in"] + cand_cost["tokens_out"],
        },
        "added": added,
        "removed": removed,
        "changed": sorted(changed, key=lambda c: c["duration_delta_ms"], reverse=True),
        "unchanged_count": len(unchanged),
        "regressions": sorted(regressions, key=lambda c: c["duration_delta_ms"], reverse=True),
        "verdict": "regressed" if regressions or cand_errors > base_errors else "ok",
    }
