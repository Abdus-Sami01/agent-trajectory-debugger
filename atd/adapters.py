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

    agentflow >=0.2 records started_ms/ended_ms per node, so the timeline shows real
    concurrency. Older payloads carry only elapsed_ms; those are laid out sequentially
    and marked timeline="synthesized-sequential" - durations real, start offsets are not.
    """
    nodes = payload.get("nodes", {})
    has_real_timing = any(
        "started_ms" in node and "ended_ms" in node for node in nodes.values()
    )

    trace = Trace(
        trace_id=payload.get("workflow_id") or "agentflow",
        metadata={
            "source": "agentflow",
            "status": payload.get("status", ""),
            "reported_total_ms": payload.get("total_ms", 0.0),
            "timeline": "real" if has_real_timing else "synthesized-sequential",
            "final_output": payload.get("final_output"),
        },
    )

    cursor = 0.0
    for index, (name, node) in enumerate(nodes.items(), start=1):
        elapsed = float(node.get("elapsed_ms", 0.0) or 0.0)
        if has_real_timing and "started_ms" in node:
            start = float(node.get("started_ms") or 0.0)
            end = float(node.get("ended_ms") or start + elapsed)
        else:
            start, end = cursor, cursor + elapsed
            cursor += elapsed
        node_type = str(node.get("node_type", "") or "")
        trace.add(
            Span(
                span_id=f"n{index}",
                name=name,
                kind=_KIND_BY_NODE_TYPE.get(node_type, "tool"),
                start_ms=start,
                end_ms=end,
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
