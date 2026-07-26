# Agent Trajectory Debugger

Trace, analyze, and replay multi-step agent runs. Point it at a trace and it tells you where the time went, where the money went, and where the agent got stuck.

Most agent tooling shows you a log. This shows you the **failure structure**: which tool retried identically three times, which error kept repeating without progress, which failed span propagated up to kill the run, and which chain actually owned the wall-clock.

## What it detects

| Analysis | What it answers |
|---|---|
| `repeated_calls` | Same tool, same arguments, called again — the classic retry loop. Reports wasted milliseconds. |
| `stuck_loops` | Identical error text recurring — the agent is not making progress, it is spinning. |
| `failure_points` | Failed spans plus the ancestor chain the failure propagated into. |
| `critical_path` | Longest root-to-leaf chain — where wall-clock actually went, not just the slowest single span. |
| `cost_rollup` | Tokens and USD per model, and in total. |
| `tool_stats` | Per-tool call count, error rate, total and average latency. |

## Install

```bash
pip install -r requirements.txt
pip install -e .
```

## Run

```bash
python examples/generate_demo_trace.py
uvicorn atd.api:app --port 8011
```

Open http://localhost:8011. Set `ATD_TRACE_DIR` to point at a different trace directory; it defaults to `traces/` next to the package, not the current working directory.

## Recording your own traces

```python
from atd.recorder import Recorder
from atd.store import TraceStore

rec = Recorder("my-run-001")
with rec.span("planner", "agent"):
    with rec.span("plan", "llm", model="claude-sonnet-4") as s:
        s.output = "step 1, step 2"
        s.tokens_in, s.tokens_out, s.cost_usd = 420, 180, 0.0021
    with rec.span("search", "tool", input={"q": "pricing"}) as s:
        s.output = "8 results"

TraceStore("traces").save(rec.trace)
```

Exceptions raised inside a span are recorded (`status="error"`, error text captured) and then re-raised — recording never swallows a failure.

## Adapters

The trace schema is framework-agnostic. Existing adapters:

- `from_agentflow(payload)` — consumes [agentflow](https://github.com/Abdus-Sami01/agentflow)'s `workflow_to_dict` output. agentflow records per-node `elapsed_ms` but no absolute timestamps, so spans are laid out sequentially: **durations are real, start offsets are synthesized and do not reflect actual concurrency.** The UI labels this.
- `from_openai_messages(trace_id, messages)` — consumes an OpenAI-style chat transcript with `tool_calls`. Transcripts carry no timing, so all spans have zero duration; structure and cost are meaningful, latency is not.

Both limitations are surfaced in `trace.metadata["timeline"]` rather than being papered over.

## Schema

A `Trace` is a flat list of `Span`s linked by `parent_id`. A span carries `kind` (`agent` / `llm` / `tool` / `reasoning` / `retrieval`), `status` (`ok` / `error` / `timeout`), timing, optional input/output, token counts, cost, and free-form metadata. Spans whose `parent_id` points at nothing are treated as roots, so a partial or truncated trace still renders.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/traces` | All traces with span count, duration, error count |
| `GET /api/traces/{id}` | Full trace with every span |
| `GET /api/traces/{id}/analysis` | Every analysis above, as JSON |

## Tests

```bash
python -m pytest tests/ -q
```

26 tests, no network, no model downloads.
