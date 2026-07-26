from __future__ import annotations

import json
from pathlib import Path

from atd.trace import Trace


class TraceStore:
    def __init__(self, root: str | Path = "traces"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, trace_id: str) -> Path:
        safe = "".join(c for c in trace_id if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError(f"unusable trace_id: {trace_id!r}")
        return self.root / f"{safe}.json"

    def save(self, trace: Trace) -> Path:
        path = self._path(trace.trace_id)
        path.write_text(json.dumps(trace.to_dict(), indent=2, default=str), encoding="utf-8")
        return path

    def load(self, trace_id: str) -> Trace:
        path = self._path(trace_id)
        if not path.exists():
            raise FileNotFoundError(f"no trace {trace_id!r} in {self.root}")
        return Trace.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))
