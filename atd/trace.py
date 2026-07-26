from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

SpanKind = Literal["agent", "llm", "tool", "reasoning", "retrieval"]
SpanStatus = Literal["ok", "error", "timeout"]


@dataclass
class Span:
    span_id: str
    name: str
    kind: SpanKind
    start_ms: float
    end_ms: float
    parent_id: str = ""
    status: SpanStatus = "ok"
    input: Any = None
    output: Any = None
    error: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_ms"] = self.duration_ms
        return d


@dataclass
class Trace:
    trace_id: str
    spans: list[Span] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, span: Span) -> None:
        self.spans.append(span)

    def by_id(self, span_id: str) -> Span | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def children_of(self, span_id: str) -> list[Span]:
        return [s for s in self.spans if s.parent_id == span_id]

    def roots(self) -> list[Span]:
        ids = {s.span_id for s in self.spans}
        return [s for s in self.spans if not s.parent_id or s.parent_id not in ids]

    @property
    def start_ms(self) -> float:
        return min((s.start_ms for s in self.spans), default=0.0)

    @property
    def end_ms(self) -> float:
        return max((s.end_ms for s in self.spans), default=0.0)

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "metadata": self.metadata,
            "spans": [s.to_dict() for s in self.spans],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Trace:
        spans = []
        for raw in data.get("spans", []):
            raw = {k: v for k, v in raw.items() if k != "duration_ms"}
            spans.append(Span(**raw))
        return Trace(
            trace_id=data.get("trace_id", ""),
            spans=spans,
            metadata=data.get("metadata", {}),
        )
