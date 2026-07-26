import json

from atd.cli import main
from atd.pricing import DEFAULT_PRICING, apply_pricing, price_span
from atd.store import TraceStore
from atd.trace import Span, Trace


def test_price_span_known_model():
    cost = price_span("claude-sonnet-4", 1_000_000, 1_000_000, DEFAULT_PRICING)
    assert cost == 18.0


def test_price_span_unknown_model_returns_none_not_zero():
    assert price_span("nonexistent-model", 1000, 1000, DEFAULT_PRICING) is None


def test_apply_pricing_fills_cost_and_flags_unknown():
    t = Trace(trace_id="p")
    t.add(Span("a", "call", "llm", 0, 1, tokens_in=1_000_000, tokens_out=0, model="claude-sonnet-4"))
    t.add(Span("b", "call", "llm", 1, 2, tokens_in=1000, tokens_out=1000, model="mystery"))
    t.add(Span("c", "tool", "tool", 2, 3))
    stats = apply_pricing(t)
    assert stats == {"priced": 1, "skipped_existing": 0, "unknown_model": 1}
    assert t.spans[0].cost_usd == 3.0
    assert t.spans[1].cost_usd == 0.0
    assert t.spans[1].metadata["pricing"] == "unknown_model"


def test_apply_pricing_preserves_existing_unless_overwrite():
    t = Trace(trace_id="p")
    t.add(Span("a", "call", "llm", 0, 1, tokens_in=1_000_000, tokens_out=0,
               cost_usd=99.0, model="claude-sonnet-4"))
    assert apply_pricing(t)["skipped_existing"] == 1
    assert t.spans[0].cost_usd == 99.0
    apply_pricing(t, overwrite=True)
    assert t.spans[0].cost_usd == 3.0


def test_store_index_written_and_used(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(trace_id="one", metadata={"source": "test"})
    t.add(Span("a", "n", "tool", 0, 5, status="error", error="x"))
    store.save(t)
    assert store.index_path.exists()
    rows = store.summaries()
    assert rows == [{"trace_id": "one", "spans": 1, "duration_ms": 5, "errors": 1,
                     "llm_calls": 0, "cost_usd": 0.0, "source": "test"}]


def test_summaries_backfills_traces_saved_without_index(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(trace_id="manual")
    t.add(Span("a", "n", "tool", 0, 3))
    (tmp_path / "manual.json").write_text(json.dumps(t.to_dict()), encoding="utf-8")
    rows = store.summaries()
    assert len(rows) == 1 and rows[0]["trace_id"] == "manual"


def test_summaries_refreshes_when_file_changes(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(trace_id="ch")
    t.add(Span("a", "n", "tool", 0, 3))
    store.save(t)
    assert store.summaries()[0]["spans"] == 1
    t.add(Span("b", "n2", "tool", 3, 6))
    store.save(t)
    assert store.summaries()[0]["spans"] == 2


def test_summaries_drops_deleted_traces(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(trace_id="gone")
    t.add(Span("a", "n", "tool", 0, 1))
    store.save(t)
    store.delete("gone")
    assert store.summaries() == []


def test_index_file_not_listed_as_a_trace(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(trace_id="real")
    t.add(Span("a", "n", "tool", 0, 1))
    store.save(t)
    assert store.list_ids() == ["real"]


def test_cli_diff_exit_code_on_regression(tmp_path, capsys):
    store = TraceStore(tmp_path)
    a = Trace(trace_id="base")
    a.add(Span("s1", "step", "tool", 0, 100))
    b = Trace(trace_id="cand")
    b.add(Span("s1", "step", "tool", 0, 400))
    store.save(a)
    store.save(b)

    code = main(["--dir", str(tmp_path), "diff", "base", "cand", "--fail-on-regression"])
    assert code == 1
    assert "REGRESS" in capsys.readouterr().out

    assert main(["--dir", str(tmp_path), "diff", "base", "cand"]) == 0


def test_cli_analyze_fail_on_error(tmp_path, capsys):
    store = TraceStore(tmp_path)
    t = Trace(trace_id="bad")
    t.add(Span("a", "n", "tool", 0, 1, status="error", error="boom"))
    store.save(t)
    assert main(["--dir", str(tmp_path), "analyze", "bad", "--fail-on-error"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_missing_trace_returns_2(tmp_path, capsys):
    assert main(["--dir", str(tmp_path), "analyze", "ghost"]) == 2
    assert "error:" in capsys.readouterr().err
