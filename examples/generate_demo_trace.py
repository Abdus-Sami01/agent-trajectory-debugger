"""Generate a realistic multi-agent trace exhibiting a retry loop and a hard failure."""
from __future__ import annotations

from atd.store import TraceStore
from atd.trace import Span, Trace


def build() -> Trace:
    trace = Trace(
        trace_id="research-agent-run-014",
        metadata={"source": "demo", "task": "Summarize Q3 competitor pricing", "timeline": "real"},
    )
    spans = [
        Span("s1", "planner", "agent", 0, 5120, "", "ok",
             input="Summarize Q3 competitor pricing",
             output="plan: search -> fetch -> extract -> draft"),
        Span("s2", "plan_task", "llm", 40, 980, "s1", "ok",
             input="Decompose the task into steps",
             output="1. search pricing pages 2. fetch 3. extract tiers 4. draft",
             tokens_in=420, tokens_out=180, cost_usd=0.0021, model="claude-sonnet-4"),
        Span("s3", "researcher", "agent", 1000, 4200, "s1", "ok"),
        Span("s4", "web_search", "tool", 1020, 1480, "s3", "ok",
             input={"query": "competitor pricing Q3 2026"},
             output="8 results"),
        Span("s5", "fetch_page", "tool", 1500, 2350, "s3", "error",
             input={"url": "https://competitor-a.example/pricing"},
             error="HTTPError: 429 Too Many Requests"),
        Span("s6", "fetch_page", "tool", 2400, 3260, "s3", "error",
             input={"url": "https://competitor-a.example/pricing"},
             error="HTTPError: 429 Too Many Requests"),
        Span("s7", "fetch_page", "tool", 3300, 4150, "s3", "error",
             input={"url": "https://competitor-a.example/pricing"},
             error="HTTPError: 429 Too Many Requests"),
        Span("s8", "extract_tiers", "llm", 4220, 5100, "s1", "ok",
             input="Extract pricing tiers from the fetched pages",
             output="only competitor-b tiers recovered; competitor-a missing",
             tokens_in=2100, tokens_out=340, cost_usd=0.0094, model="claude-sonnet-4"),
        Span("s9", "critic", "agent", 5140, 7900, "", "ok"),
        Span("s10", "review_draft", "llm", 5160, 7300, "s9", "ok",
             input="Review the draft for completeness",
             output="incomplete: competitor-a pricing absent, do not ship",
             tokens_in=1800, tokens_out=260, cost_usd=0.0078, model="claude-opus-4"),
        Span("s11", "quality_gate", "reasoning", 7320, 7880, "s9", "error",
             input={"require": "all competitors covered"},
             error="GateFailed: coverage 1/2 below threshold 1.0"),
    ]
    for span in spans:
        trace.add(span)
    return trace


if __name__ == "__main__":
    store = TraceStore("traces")
    path = store.save(build())
    print(f"wrote {path}")
