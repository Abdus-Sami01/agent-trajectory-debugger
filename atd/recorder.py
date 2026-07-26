from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from atd.trace import Span, SpanKind, Trace


class Recorder:
    """Builds a Trace from live execution. Nest spans with the `span` context manager."""

    def __init__(self, trace_id: str, clock=None):
        self.trace = Trace(trace_id=trace_id)
        self._clock = clock or (lambda: time.perf_counter() * 1000.0)
        self._stack: list[str] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"s{self._counter}"

    @contextmanager
    def span(
        self,
        name: str,
        kind: SpanKind = "tool",
        input: Any = None,
        model: str = "",
        **metadata: Any,
    ) -> Iterator[Span]:
        span = Span(
            span_id=self._next_id(),
            name=name,
            kind=kind,
            start_ms=self._clock(),
            end_ms=self._clock(),
            parent_id=self._stack[-1] if self._stack else "",
            input=input,
            model=model,
            metadata=metadata,
        )
        self.trace.add(span)
        self._stack.append(span.span_id)
        try:
            yield span
        except Exception as exc:
            span.status = "error"
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.end_ms = self._clock()
            self._stack.pop()
