from __future__ import annotations

import argparse
import json
import sys

from atd.analysis import analyze
from atd.diff import diff_traces
from atd.pricing import apply_pricing
from atd.store import TraceStore


def _fmt_ms(ms: float) -> str:
    return f"{ms/1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


def cmd_list(args) -> int:
    for row in TraceStore(args.dir).summaries():
        flag = f" {row['errors']} err" if row["errors"] else ""
        print(f"{row['trace_id']:<34} {row['spans']:>5} spans  {_fmt_ms(row['duration_ms']):>8}"
              f"  ${row['cost_usd']:.4f}{flag}")
    return 0


def cmd_analyze(args) -> int:
    trace = TraceStore(args.dir).load(args.trace_id)
    result = analyze(trace)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    s = result["summary"]
    print(f"{trace.trace_id}: {s['spans']} spans, {_fmt_ms(s['duration_ms'])}, "
          f"{s['errors']} errors, ${result['cost']['total']['cost_usd']:.4f}")
    print("critical path: " + " -> ".join(x["name"] for x in result["critical_path"]))

    for loop in result["stuck_loops"]:
        print(f"  STUCK   {loop['count']}x {loop['error']} ({', '.join(loop['names'])})")
    for rep in result["repeated_calls"]:
        tail = ", all failed" if rep["all_failed"] else ""
        print(f"  REPEAT  {rep['name']} x{rep['count']}, {_fmt_ms(rep['wasted_ms'])} wasted{tail}")
    for fail in result["failures"]:
        print(f"  FAIL    {fail['name']}: {fail['error']}")

    return 1 if args.fail_on_error and s["errors"] else 0


def cmd_diff(args) -> int:
    store = TraceStore(args.dir)
    result = diff_traces(store.load(args.baseline), store.load(args.candidate), args.threshold)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        t = result["totals"]
        pct = t["duration_pct"]
        pct_str = f" ({pct*100:+.1f}%)" if pct is not None else ""
        print(f"{result['baseline_id']} -> {result['candidate_id']}: {result['verdict'].upper()}")
        print(f"  duration {_fmt_ms(t['duration_before_ms'])} -> {_fmt_ms(t['duration_after_ms'])}{pct_str}")
        print(f"  errors   {t['errors_before']} -> {t['errors_after']}")
        print(f"  cost     ${t['cost_before_usd']:.4f} -> ${t['cost_after_usd']:.4f}")
        for r in result["regressions"]:
            marks = []
            if r["slower"]:
                marks.append(f"+{r['duration_pct']*100:.0f}% slower")
            if r["newly_failing"]:
                marks.append(f"errors {r['errors_before']}->{r['errors_after']}")
            if r["more_calls"]:
                marks.append(f"calls {r['calls_before']}->{r['calls_after']}")
            print(f"  REGRESS {r['name']}: {', '.join(marks)}")
        for a in result["added"]:
            print(f"  ADDED   {a['name']} ({a['calls']} calls)")
        for rm in result["removed"]:
            print(f"  REMOVED {rm['name']} ({rm['calls']} calls)")
    return 1 if args.fail_on_regression and result["verdict"] == "regressed" else 0


def cmd_price(args) -> int:
    store = TraceStore(args.dir)
    trace = store.load(args.trace_id)
    stats = apply_pricing(trace, overwrite=args.overwrite)
    store.save(trace)
    print(f"priced {stats['priced']}, kept {stats['skipped_existing']}, "
          f"unknown model {stats['unknown_model']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="atd", description="Agent trajectory debugger")
    p.add_argument("--dir", default="traces", help="trace directory")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list traces").set_defaults(func=cmd_list)

    a = sub.add_parser("analyze", help="analyze one trace")
    a.add_argument("trace_id")
    a.add_argument("--json", action="store_true")
    a.add_argument("--fail-on-error", action="store_true", help="exit 1 if the trace has errors")
    a.set_defaults(func=cmd_analyze)

    d = sub.add_parser("diff", help="compare two traces")
    d.add_argument("baseline")
    d.add_argument("candidate")
    d.add_argument("--threshold", type=float, default=0.20, help="slowdown fraction counted as regression")
    d.add_argument("--json", action="store_true")
    d.add_argument("--fail-on-regression", action="store_true", help="exit 1 if regressed")
    d.set_defaults(func=cmd_diff)

    pr = sub.add_parser("price", help="fill cost_usd from token counts")
    pr.add_argument("trace_id")
    pr.add_argument("--overwrite", action="store_true")
    pr.set_defaults(func=cmd_price)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
