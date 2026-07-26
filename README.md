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
| `diff_traces` | Run A vs run B: what got slower, what started failing, what retried more. |

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

## Regression diffing (CI)

Agent runs regress silently: a prompt change makes a tool retry three times instead of once, and nothing fails loudly. `atd diff` catches that and returns a non-zero exit code.

```bash
atd diff run-014 run-015 --fail-on-regression
```

```
research-agent-run-014 -> research-agent-run-015: REGRESSED
  duration 7.90s -> 9.36s (+18.5%)
  errors   4 -> 6
  cost     $0.0193 -> $0.0193
  REGRESS review_draft: +96% slower
  REGRESS fetch_page: +66% slower, errors 3->5, calls 3->5
```

Spans are matched across runs by `kind:name`, not `span_id`, because ids are per-run. A step called once in the baseline and three times in the candidate surfaces as `more_calls` — which is exactly how a new retry loop shows up.

## CLI

```bash
atd list                                   # all traces, fast (index-backed)
atd analyze <id> [--json] [--fail-on-error]
atd diff <baseline> <candidate> [--threshold 0.2] [--fail-on-regression]
atd price <id> [--overwrite]               # fill cost_usd from token counts
```

## Pricing

`atd price` converts token counts to USD using a published-list-price table. An unknown model yields `None`, never `0.0` — a missing price must not silently read as free; those spans are tagged `metadata.pricing = "unknown_model"`. Override the table with `ATD_PRICING_FILE=path.json`.

## Scale

Listing is index-backed. `TraceStore` maintains a `_index.json` sidecar and re-parses a trace only when its mtime changes.

| Traces (200 spans each) | Full parse | Index hit |
|---|---|---|
| 300 | ~7750ms | ~14ms |

Measured on the benchmark in this repo. The cold path (index absent) still parses everything once, then stays warm.

## Adapters

The trace schema is framework-agnostic. Existing adapters:

- `from_agentflow(payload)` — consumes [agentflow](https://github.com/Abdus-Sami01/agentflow)'s `workflow_to_dict` output. agentflow now records `started_ms`/`ended_ms` per node, so the timeline shows **real concurrency**: in a parallel two-branch workflow the branches overlap (33.1ms and 33.4ms starts) and wall-clock is 156ms against 276ms of summed span time. Older payloads carrying only `elapsed_ms` fall back to a sequential layout marked `synthesized-sequential`.
- `from_openai_messages(trace_id, messages)` — consumes an OpenAI-style chat transcript with `tool_calls`. Transcripts carry no timing, so all spans have zero duration; structure and cost are meaningful, latency is not.

Timeline fidelity is always reported in `trace.metadata["timeline"]` (`real` / `synthesized-sequential` / `none`) and shown in the UI, rather than being papered over.

## Known limitations

- **Critical path needs hierarchy.** It walks `parent_id` links. Adapters that produce a flat span list (agentflow, which reports nodes without parent/child structure) degenerate to "longest single span". Traces recorded via `Recorder`, which nests spans, get a true path.
- **Cost is only as good as the token counts** you record. Spans without `tokens_in`/`tokens_out` contribute nothing to the rollup.
- **No streaming yet** — traces are read from disk, so a run must finish before you inspect it.

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
