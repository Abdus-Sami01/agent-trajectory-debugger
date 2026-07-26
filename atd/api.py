from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from atd.analysis import analyze
from atd.store import TraceStore

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_TRACE_DIR = Path(__file__).resolve().parent.parent / "traces"

app = FastAPI(title="Agent Trajectory Debugger")


def get_store() -> TraceStore:
    """Trace dir is repo-relative by default so the server does not depend on cwd."""
    return TraceStore(os.environ.get("ATD_TRACE_DIR") or DEFAULT_TRACE_DIR)


@app.get("/api/traces")
def list_traces(store: TraceStore = Depends(get_store)) -> dict:
    out = []
    for trace_id in store.list_ids():
        trace = store.load(trace_id)
        errors = len([s for s in trace.spans if s.status != "ok"])
        out.append(
            {
                "trace_id": trace_id,
                "spans": len(trace.spans),
                "duration_ms": round(trace.duration_ms, 3),
                "errors": errors,
                "source": trace.metadata.get("source", ""),
            }
        )
    return {"traces": out}


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
