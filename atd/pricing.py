from __future__ import annotations

import json
import os
from pathlib import Path

from atd.trace import Trace

# USD per 1M tokens (input, output). Published list prices, not contract rates.
# Override with a JSON file via ATD_PRICING_FILE: {"model": [in_per_mtok, out_per_mtok]}
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4": (0.80, 4.0),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}


def load_pricing() -> dict[str, tuple[float, float]]:
    table = dict(DEFAULT_PRICING)
    path = os.environ.get("ATD_PRICING_FILE")
    if path and Path(path).exists():
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        for model, pair in raw.items():
            table[model] = (float(pair[0]), float(pair[1]))
    return table


def price_span(model: str, tokens_in: int, tokens_out: int,
               table: dict[str, tuple[float, float]] | None = None) -> float | None:
    """USD for one call, or None when the model is not in the table.

    None means unknown, never zero - a missing price must not silently read as free.
    """
    table = table if table is not None else load_pricing()
    rates = table.get(model)
    if rates is None:
        return None
    return round(tokens_in / 1e6 * rates[0] + tokens_out / 1e6 * rates[1], 8)


def apply_pricing(trace: Trace, overwrite: bool = False) -> dict[str, int]:
    """Fill in cost_usd from token counts. Returns counts of what happened."""
    table = load_pricing()
    stats = {"priced": 0, "skipped_existing": 0, "unknown_model": 0}
    for span in trace.spans:
        if span.kind != "llm" or (not span.tokens_in and not span.tokens_out):
            continue
        if span.cost_usd and not overwrite:
            stats["skipped_existing"] += 1
            continue
        cost = price_span(span.model, span.tokens_in, span.tokens_out, table)
        if cost is None:
            span.metadata["pricing"] = "unknown_model"
            stats["unknown_model"] += 1
            continue
        span.cost_usd = cost
        stats["priced"] += 1
    return stats
