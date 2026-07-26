import pytest
from fastapi.testclient import TestClient

from atd.api import app, get_store
from atd.store import TraceStore
from atd.trace import Span, Trace


@pytest.fixture
def client(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(trace_id="demo", metadata={"source": "test"})
    t.add(Span("a", "root", "agent", 0, 20))
    t.add(Span("b", "boom", "tool", 0, 15, "a", status="error", error="nope"))
    store.save(t)
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_traces(client):
    body = client.get("/api/traces").json()
    assert body["traces"][0]["trace_id"] == "demo"
    assert body["traces"][0]["errors"] == 1


def test_get_trace(client):
    body = client.get("/api/traces/demo").json()
    assert len(body["spans"]) == 2
    assert body["spans"][0]["duration_ms"] == 20


def test_get_analysis_reports_failure(client):
    body = client.get("/api/traces/demo/analysis").json()
    assert body["summary"]["errors"] == 1
    assert body["failures"][0]["name"] == "boom"
    assert body["failures"][0]["propagated_to"] == ["root"]


def test_missing_trace_returns_404(client):
    assert client.get("/api/traces/ghost").status_code == 404
    assert client.get("/api/traces/ghost/analysis").status_code == 404


def test_index_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Agent Trajectory Debugger" in r.text
