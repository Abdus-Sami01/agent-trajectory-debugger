from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from atd.analysis import analyze
from atd.diff import diff_traces
from atd.store import TraceStore

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_TRACE_DIR = Path(__file__).resolve().parent.parent / "traces"

app = FastAPI(title="Agent Trajectory Debugger")


def get_store() -> TraceStore:
    """Trace dir is repo-relative by default so the server does not depend on cwd."""
    return TraceStore(os.environ.get("ATD_TRACE_DIR") or DEFAULT_TRACE_DIR)


@app.get("/api/traces")
def list_traces(store: TraceStore = Depends(get_store)) -> dict:
    return {"traces": store.summaries()}


@app.get("/api/diff")
def get_diff(
    baseline: str,
    candidate: str,
    threshold: float = 0.20,
    store: TraceStore = Depends(get_store),
) -> dict:
    try:
        base = store.load(baseline)
        cand = store.load(candidate)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return diff_traces(base, cand, threshold)


@app.get("/api/traces/{trace_id}")
def get_trace(trace_id: str, store: TraceStore = Depends(get_store)) -> dict:
    try:
        trace = store.load(trace_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail=f"trace not found: {trace_id}")
    return trace.to_dict()


@app.get("/api/traces/{trace_id}/analysis")
def get_analysis(trace_id: str, store: TraceStore = Depends(get_store)) -> dict:
    try:
        trace = store.load(trace_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail=f"trace not found: {trace_id}")
    return analyze(trace)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
