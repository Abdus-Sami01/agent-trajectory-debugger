from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atd.trace import Trace

INDEX_NAME = "_index.json"


def summarize(trace: Trace) -> dict[str, Any]:
    return {
        "trace_id": trace.trace_id,
        "spans": len(trace.spans),
        "duration_ms": round(trace.duration_ms, 3),
        "errors": len([s for s in trace.spans if s.status != "ok"]),
        "llm_calls": len([s for s in trace.spans if s.kind == "llm"]),
        "cost_usd": round(sum(s.cost_usd for s in trace.spans), 6),
        "source": trace.metadata.get("source", ""),
    }


class TraceStore:
    """Trace persistence with a sidecar index.

    Listing reads only the index, so it stays fast as trace count grows -
    parsing every trace file just to render a list does not scale.
    """

    def __init__(self, root: str | Path = "traces"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, trace_id: str) -> Path:
        safe = "".join(c for c in trace_id if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError(f"unusable trace_id: {trace_id!r}")
        return self.root / f"{safe}.json"

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_NAME

    def _read_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_index(self, index: dict[str, dict[str, Any]]) -> None:
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, indent=1, default=str), encoding="utf-8")
        tmp.replace(self.index_path)

    def save(self, trace: Trace) -> Path:
        path = self._path(trace.trace_id)
        path.write_text(json.dumps(trace.to_dict(), indent=2, default=str), encoding="utf-8")
        index = self._read_index()
        entry = summarize(trace)
        entry["mtime"] = path.stat().st_mtime
        index[path.stem] = entry
        self._write_index(index)
        return path

    def load(self, trace_id: str) -> Trace:
        path = self._path(trace_id)
        if not path.exists():
            raise FileNotFoundError(f"no trace {trace_id!r} in {self.root}")
        return Trace.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json") if p.name != INDEX_NAME)

    def summaries(self) -> list[dict[str, Any]]:
        """Summaries for every trace, parsing only files the index does not cover."""
        index = self._read_index()
        out: list[dict[str, Any]] = []
        dirty = False

        for path in sorted(self.root.glob("*.json")):
            if path.name == INDEX_NAME:
                continue
            mtime = path.stat().st_mtime
            entry = index.get(path.stem)
            if entry is None or entry.get("mtime") != mtime:
                trace = Trace.from_dict(json.loads(path.read_text(encoding="utf-8")))
                entry = summarize(trace)
                entry["mtime"] = mtime
                index[path.stem] = entry
                dirty = True
            out.append({k: v for k, v in entry.items() if k != "mtime"})

        for stale in set(index) - {p.stem for p in self.root.glob("*.json")}:
            del index[stale]
            dirty = True

        if dirty:
            self._write_index(index)
        return out

    def delete(self, trace_id: str) -> None:
        path = self._path(trace_id)
        path.unlink(missing_ok=True)
        index = self._read_index()
        if index.pop(path.stem, None) is not None:
            self._write_index(index)
