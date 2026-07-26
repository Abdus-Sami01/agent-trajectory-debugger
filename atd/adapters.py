from __future__ import annotations

from typing import Any

from atd.trace import Span, Trace

_AGENTFLOW_STATUS = {"completed": "ok", "failed": "error", "skipped": "ok", "timeout": "timeout"}

_KIND_BY_NODE_TYPE = {
    "llm": "llm",
    "tool": "tool",
    "retrieval": "retrieval",
    "supervisor": "agent",
    "conditional": "reasoning",
    "gate": "reasoning",
    "transform": "tool",
    "aggregator": "tool",
    "loop": "agent",
}


def from_agentflow(payload: dict[str, Any]) -> Trace:
    """Convert agentflow's workflow_to_dict output into a Trace.

    agentflow records per-node elapsed_ms but no absolute timestamps, so spans are
    laid out sequentially in dict order. Durations are real; start offsets are
    synthesized and do NOT reflect actual concurrency.
    """
    trace = Trace(
        trace_id=payload.get("workflow_id") or "agentflow",
        metadata={
            "source": "agentflow",
            "status": payload.get("status", ""),
            "reported_total_ms": payload.get("total_ms", 0.0),
            "timeline": "synthesized-sequential",
            "final_output": payload.get("final_output"),
        },
    )

    cursor = 0.0
    for index, (name, node) in enumerate(payload.get("nodes", {}).items(), start=1):
        elapsed = float(node.get("elapsed_ms", 0.0) or 0.0)
        node_type = str(node.get("node_type", "") or "")
        trace.add(
            Span(
                span_id=f"n{index}",
                name=name,
                kind=_KIND_BY_NODE_TYPE.get(node_type, "tool"),
                start_ms=cursor,
                end_ms=cursor + elapsed,
                status=_AGENTFLOW_STATUS.get(str(node.get("status", "")), "ok"),
                output=node.get("output"),
                error=str(node.get("error", "") or ""),
                metadata={
                    "attempts": node.get("attempts", 1),
                    "agentflow_status": node.get("status", ""),
                    **(node.get("metadata") or {}),
                },
            )
        )
        cursor += elapsed

    return trace


def from_openai_messages(trace_id: str, messages: list[dict[str, Any]]) -> Trace:
    """Convert an OpenAI-style chat transcript (with tool_calls) into a Trace.

    No timing data exists in a transcript, so every span has zero duration.
    Structure and cost are real; latency analysis is not meaningful here.
    """
    trace = Trace(trace_id=trace_id, metadata={"source": "openai-messages", "timeline": "none"})
    index = 0
    for message in messages:
        role = message.get("role", "")
        if role == "assistant":
            index += 1
            trace.add(
                Span(
                    span_id=f"m{index}",
                    name="assistant",
                    kind="llm",
                    start_ms=0.0,
                    end_ms=0.0,
                    output=message.get("content"),
                    model=str(message.get("model", "") or ""),
                )
            )
            parent = f"m{index}"
            for call in message.get("tool_calls", []) or []:
                index += 1
                fn = call.get("function", {})
                trace.add(
                    Span(
                        span_id=f"m{index}",
                        name=str(fn.get("name", "tool")),
                        kind="tool",
                        start_ms=0.0,
                        end_ms=0.0,
                        parent_id=parent,
                        input=fn.get("arguments"),
                    )
                )
        elif role == "tool":
            index += 1
            trace.add(
                Span(
                    span_id=f"m{index}",
                    name=str(message.get("name", "tool_result")),
                    kind="tool",
                    start_ms=0.0,
                    end_ms=0.0,
                    output=message.get("content"),
                )
            )
    return trace
