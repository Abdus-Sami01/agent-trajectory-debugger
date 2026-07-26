from atd.analysis import (
    analyze,
    cost_rollup,
    critical_path,
    failure_points,
    repeated_calls,
    stuck_loops,
    tool_stats,
)
from atd.trace import Span, Trace


def _trace() -> Trace:
    t = Trace(trace_id="t1")
    t.add(Span("a", "root", "agent", 0, 100))
    t.add(Span("b", "fast", "tool", 0, 10, "a", input={"x": 1}))
    t.add(Span("c", "slow", "llm", 10, 90, "a", tokens_in=100, tokens_out=50,
               cost_usd=0.002, model="claude-sonnet-4"))
    return t


def test_critical_path_follows_longest_chain():
    assert critical_path(_trace()) == ["a", "c"]


def test_critical_path_single_span():
    t = Trace(trace_id="x")
    t.add(Span("only", "solo", "tool", 0, 5))
    assert critical_path(t) == ["only"]


def test_cost_rollup_sums_llm_spans_only():
    roll = cost_rollup(_trace())
    assert roll["total"]["calls"] == 1
    assert roll["total"]["tokens_in"] == 100
    assert roll["total"]["cost_usd"] == 0.002
    assert "claude-sonnet-4" in roll["by_model"]


def test_repeated_calls_detects_identical_tool_retries():
    t = Trace(trace_id="r")
    for i in range(3):
        t.add(Span(f"s{i}", "fetch", "tool", i * 10, i * 10 + 5,
                   status="error", error="429", input={"url": "u"}))
    found = repeated_calls(t)
    assert len(found) == 1
    assert found[0]["name"] == "fetch"
    assert found[0]["count"] == 3
    assert found[0]["all_failed"] is True


def test_repeated_calls_ignores_differing_inputs():
    t = Trace(trace_id="r")
    t.add(Span("s1", "fetch", "tool", 0, 5, input={"url": "a"}))
    t.add(Span("s2", "fetch", "tool", 5, 10, input={"url": "b"}))
    assert repeated_calls(t) == []


def test_stuck_loops_groups_identical_errors():
    t = Trace(trace_id="s")
    t.add(Span("s1", "f", "tool", 0, 1, status="error", error="boom"))
    t.add(Span("s2", "g", "tool", 1, 2, status="error", error="boom"))
    t.add(Span("s3", "h", "tool", 2, 3, status="error", error="other"))
    loops = stuck_loops(t)
    assert len(loops) == 1
    assert loops[0]["error"] == "boom"
    assert loops[0]["count"] == 2
    assert loops[0]["names"] == ["f", "g"]


def test_failure_points_records_ancestor_chain():
    t = Trace(trace_id="f")
    t.add(Span("a", "root", "agent", 0, 10))
    t.add(Span("b", "mid", "agent", 1, 9, "a"))
    t.add(Span("c", "leaf", "tool", 2, 8, "b", status="error", error="nope"))
    points = failure_points(t)
    assert len(points) == 1
    assert points[0]["propagated_to"] == ["mid", "root"]


def test_failure_points_empty_when_all_ok():
    assert failure_points(_trace()) == []


def test_tool_stats_computes_error_rate():
    t = Trace(trace_id="t")
    t.add(Span("s1", "api", "tool", 0, 10))
    t.add(Span("s2", "api", "tool", 10, 30, status="error", error="x"))
    stats = tool_stats(t)
    assert stats[0]["calls"] == 2
    assert stats[0]["errors"] == 1
    assert stats[0]["error_rate"] == 0.5
    assert stats[0]["max_ms"] == 20


def test_analyze_returns_all_sections():
    result = analyze(_trace())
    for key in ("summary", "cost", "critical_path", "failures",
                "repeated_calls", "stuck_loops", "tools", "slowest"):
        assert key in result
    assert result["summary"]["spans"] == 3
    assert result["summary"]["errors"] == 0


def test_analyze_handles_empty_trace():
    result = analyze(Trace(trace_id="empty"))
    assert result["summary"]["spans"] == 0
    assert result["summary"]["error_rate"] == 0.0
