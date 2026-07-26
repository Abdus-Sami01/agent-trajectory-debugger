import pytest

from atd.adapters import from_agentflow, from_openai_messages
from atd.recorder import Recorder
from atd.store import TraceStore
from atd.trace import Span, Trace


def test_trace_roundtrip_preserves_spans():
    t = Trace(trace_id="rt", metadata={"k": "v"})
    t.add(Span("a", "one", "tool", 0, 5, input={"q": 1}, output="r"))
    restored = Trace.from_dict(t.to_dict())
    assert restored.trace_id == "rt"
    assert restored.metadata == {"k": "v"}
    assert restored.spans[0].name == "one"
    assert restored.spans[0].duration_ms == 5


def test_roots_treats_dangling_parent_as_root():
    t = Trace(trace_id="d")
    t.add(Span("a", "orphan", "tool", 0, 1, parent_id="missing"))
    assert [s.span_id for s in t.roots()] == ["a"]


def test_store_save_load_list(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(trace_id="saved")
    t.add(Span("a", "n", "tool", 0, 1))
    store.save(t)
    assert store.list_ids() == ["saved"]
    assert store.load("saved").spans[0].name == "n"


def test_store_rejects_unusable_id(tmp_path):
    with pytest.raises(ValueError):
        TraceStore(tmp_path).load("///")


def test_store_missing_trace_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        TraceStore(tmp_path).load("nope")


def test_recorder_nests_spans_and_records_duration():
    ticks = iter([0, 0, 5, 10, 20, 30])
    rec = Recorder("r", clock=lambda: float(next(ticks)))
    with rec.span("outer", "agent"):
        with rec.span("inner", "tool"):
            pass
    spans = {s.name: s for s in rec.trace.spans}
    assert spans["inner"].parent_id == spans["outer"].span_id
    assert spans["outer"].parent_id == ""


def test_recorder_marks_error_and_reraises():
    rec = Recorder("r")
    with pytest.raises(ValueError):
        with rec.span("boom", "tool"):
            raise ValueError("bad")
    span = rec.trace.spans[0]
    assert span.status == "error"
    assert "ValueError: bad" in span.error


def test_from_agentflow_maps_status_and_durations():
    payload = {
        "workflow_id": "wf1",
        "status": "failed",
        "total_ms": 30.0,
        "nodes": {
            "start": {"status": "completed", "elapsed_ms": 10.0, "attempts": 1},
            "boom": {"status": "failed", "elapsed_ms": 20.0, "attempts": 3, "error": "kaput"},
        },
    }
    trace = from_agentflow(payload)
    assert trace.trace_id == "wf1"
    assert [s.status for s in trace.spans] == ["ok", "error"]
    assert trace.spans[1].error == "kaput"
    assert trace.spans[0].end_ms == 10.0
    assert trace.spans[1].start_ms == 10.0
    assert trace.metadata["timeline"] == "synthesized-sequential"


def test_from_agentflow_empty_nodes():
    trace = from_agentflow({"workflow_id": "e", "nodes": {}})
    assert trace.spans == []
    assert trace.duration_ms == 0.0


def test_from_openai_messages_nests_tool_calls():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "calling", "tool_calls": [
            {"function": {"name": "search", "arguments": '{"q":"x"}'}}
        ]},
        {"role": "tool", "name": "search", "content": "results"},
    ]
    trace = from_openai_messages("t", messages)
    kinds = [(s.name, s.kind, s.parent_id) for s in trace.spans]
    assert kinds[0] == ("assistant", "llm", "")
    assert kinds[1] == ("search", "tool", trace.spans[0].span_id)
    assert kinds[2][0] == "search"


def test_from_agentflow_uses_real_timestamps_when_present():
    payload = {
        "workflow_id": "wf",
        "nodes": {
            "a": {"status": "completed", "elapsed_ms": 120.0, "started_ms": 33.1, "ended_ms": 153.1},
            "b": {"status": "completed", "elapsed_ms": 120.0, "started_ms": 33.4, "ended_ms": 153.4},
        },
    }
    trace = from_agentflow(payload)
    assert trace.metadata["timeline"] == "real"
    assert trace.spans[0].start_ms == 33.1
    assert trace.spans[1].start_ms == 33.4
    # overlapping spans mean wall-clock is less than the sum of durations
    assert trace.duration_ms < sum(s.duration_ms for s in trace.spans)


def test_from_agentflow_falls_back_when_timestamps_absent():
    payload = {
        "workflow_id": "wf",
        "nodes": {
            "a": {"status": "completed", "elapsed_ms": 10.0},
            "b": {"status": "completed", "elapsed_ms": 20.0},
        },
    }
    trace = from_agentflow(payload)
    assert trace.metadata["timeline"] == "synthesized-sequential"
    assert trace.spans[1].start_ms == 10.0
