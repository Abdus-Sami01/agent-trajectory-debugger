from atd.diff import diff_traces
from atd.trace import Span, Trace


def _run(trace_id, spans):
    t = Trace(trace_id=trace_id)
    for s in spans:
        t.add(s)
    return t


def test_identical_runs_report_ok():
    a = _run("a", [Span("s1", "step", "tool", 0, 10)])
    b = _run("b", [Span("x9", "step", "tool", 0, 10)])
    d = diff_traces(a, b)
    assert d["verdict"] == "ok"
    assert d["regressions"] == []
    assert d["unchanged_count"] == 1


def test_matches_spans_across_differing_span_ids():
    a = _run("a", [Span("s1", "step", "tool", 0, 10)])
    b = _run("b", [Span("totally-different", "step", "tool", 0, 10)])
    assert diff_traces(a, b)["added"] == []
    assert diff_traces(a, b)["removed"] == []


def test_detects_slowdown_beyond_threshold():
    a = _run("a", [Span("s1", "step", "tool", 0, 100)])
    b = _run("b", [Span("s1", "step", "tool", 0, 200)])
    d = diff_traces(a, b, regression_pct=0.20)
    assert d["verdict"] == "regressed"
    assert d["regressions"][0]["slower"] is True
    assert d["regressions"][0]["duration_pct"] == 1.0


def test_small_slowdown_under_threshold_is_not_a_regression():
    a = _run("a", [Span("s1", "step", "tool", 0, 100)])
    b = _run("b", [Span("s1", "step", "tool", 0, 105)])
    d = diff_traces(a, b, regression_pct=0.20)
    assert d["verdict"] == "ok"
    assert d["changed"][0]["slower"] is False


def test_detects_newly_failing_span():
    a = _run("a", [Span("s1", "step", "tool", 0, 10)])
    b = _run("b", [Span("s1", "step", "tool", 0, 10, status="error", error="x")])
    d = diff_traces(a, b)
    assert d["verdict"] == "regressed"
    assert d["regressions"][0]["newly_failing"] is True


def test_detects_retry_loop_as_more_calls():
    a = _run("a", [Span("s1", "fetch", "tool", 0, 10)])
    b = _run("b", [
        Span("s1", "fetch", "tool", 0, 10),
        Span("s2", "fetch", "tool", 10, 20),
        Span("s3", "fetch", "tool", 20, 30),
    ])
    d = diff_traces(a, b)
    reg = d["regressions"][0]
    assert reg["more_calls"] is True
    assert reg["calls_before"] == 1 and reg["calls_after"] == 3


def test_added_and_removed_steps():
    a = _run("a", [Span("s1", "old", "tool", 0, 10)])
    b = _run("b", [Span("s1", "new", "tool", 0, 10)])
    d = diff_traces(a, b)
    assert [x["name"] for x in d["added"]] == ["new"]
    assert [x["name"] for x in d["removed"]] == ["old"]


def test_cost_delta_reported():
    a = _run("a", [Span("s1", "llm", "llm", 0, 10, tokens_in=100, tokens_out=10,
                        cost_usd=0.001, model="m")])
    b = _run("b", [Span("s1", "llm", "llm", 0, 10, tokens_in=300, tokens_out=30,
                        cost_usd=0.003, model="m")])
    totals = diff_traces(a, b)["totals"]
    assert totals["cost_delta_usd"] == 0.002
    assert totals["tokens_before"] == 110 and totals["tokens_after"] == 330


def test_zero_baseline_duration_yields_none_pct():
    a = _run("a", [Span("s1", "step", "tool", 0, 0)])
    b = _run("b", [Span("s1", "step", "tool", 0, 50)])
    assert diff_traces(a, b)["changed"][0]["duration_pct"] is None
