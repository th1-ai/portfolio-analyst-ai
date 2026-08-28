#!/usr/bin/env python3
"""tools/report.py - what the Analyst answered, and what it cost.

    make report
    python3 tools/report.py
    python3 tools/report.py --json

Reads data/agent.db - nothing here calls a model or an adapter. Numbers tied
to the roster's own claim ("Any portfolio question answered in seconds" /
"-80% Time to answer a data question" - README.md section 2, docs/benefits.md):

``volumes``            questions asked, by status right now.
``answered cleanly %``  share that reached `skipped` - a plain answer with
                       nothing to export, delivered with no human touch at
                       all - the number behind "answered in seconds". A
                       `pending_review` report is not counted here even
                       once approved: a person looked at it, so it is not
                       "no human needed".
``avg rounds/tools``    how many round-trips and tool calls the average
                       question took - cheap questions should trend toward 1.
``time to answer``      average seconds from a question being asked to it
                       reaching a terminal status.
``spend``               LLM calls, tokens and cost, from `core.llm`'s usage
                       logging (`core.store.usage_totals`).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, load_settings  # noqa: E402
from core.store import Store, TERMINAL  # noqa: E402


def volumes(store: Store) -> dict:
    by_status = store.counts()
    rows = store.db.execute("SELECT kind, COUNT(*) AS n FROM items GROUP BY kind").fetchall()
    by_kind = {r["kind"]: r["n"] for r in rows}
    return {"by_kind": by_kind, "by_status": by_status, "total": sum(by_kind.values())}


def answered_cleanly(store: Store) -> dict:
    counts = store.counts()
    total_terminal = sum(counts.get(s, 0) for s in TERMINAL)
    skipped = counts.get("skipped", 0)
    rate = (skipped / total_terminal) if total_terminal else 0.0
    return {"skipped": skipped, "terminal": total_terminal, "rate": rate}


def loop_effort(store: Store) -> dict:
    rows = store.db.execute("SELECT payload_json, draft_json FROM items WHERE kind='question'").fetchall()
    rounds, tool_counts = [], []
    for row in rows:
        try:
            draft = json.loads(row["draft_json"] or "{}")
        except json.JSONDecodeError:
            continue
        calls = draft.get("tool_calls")
        if calls is not None:
            tool_counts.append(len(calls))
    return {"n": len(tool_counts),
           "avg_tool_calls": round(sum(tool_counts) / len(tool_counts), 1) if tool_counts else 0.0}


def time_to_answer_seconds(store: Store) -> dict:
    rows = store.db.execute(
        "SELECT id, created_at FROM items WHERE kind='question'").fetchall()
    deltas: list[float] = []
    for row in rows:
        terminal_event = store.db.execute(
            "SELECT ts FROM events WHERE item_id=? AND action IN "
            "('status:skipped', 'status:pending_review', 'status:needs_human') "
            "ORDER BY ts ASC LIMIT 1",
            (row["id"],)).fetchone()
        if terminal_event is None:
            continue
        try:
            start = datetime.fromisoformat(str(row["created_at"])[:19])
            end = datetime.fromisoformat(str(terminal_event["ts"])[:19])
        except ValueError:
            continue
        deltas.append(max(0.0, (end - start).total_seconds()))
    avg = (sum(deltas) / len(deltas)) if deltas else 0.0
    return {"n": len(deltas), "avg_seconds": round(avg, 1)}


def spend(store: Store, since: str | None = None) -> dict:
    return store.usage_totals(since=since)


def build_report(store: Store, since: str | None = None) -> dict:
    return {"volumes": volumes(store), "answered_cleanly": answered_cleanly(store),
           "loop_effort": loop_effort(store), "time_to_answer": time_to_answer_seconds(store),
           "spend": spend(store, since=since)}


def print_report(report: dict) -> None:
    v = report["volumes"]
    print("Portfolio Analyst AI - report\n")
    print(f"Questions: {v['total']} total")
    if v["by_kind"]:
        print("  by kind:   " + ", ".join(f"{k}={n}" for k, n in sorted(v["by_kind"].items())))
    if v["by_status"]:
        print("  by status: " + ", ".join(f"{k}={n}" for k, n in sorted(v["by_status"].items())))

    a = report["answered_cleanly"]
    print(f"\nAnswered cleanly: {a['skipped']}/{a['terminal']} finished question(s) "
         f"({a['rate']*100:.0f}%) needed no human at all.")

    e = report["loop_effort"]
    if e["n"]:
        print(f"Average tool calls per question: {e['avg_tool_calls']}.")

    t = report["time_to_answer"]
    if t["n"]:
        print(f"Time to answer: {t['avg_seconds']}s average, over {t['n']} question(s).")
    else:
        print("Time to answer: no finished questions yet.")

    s = report["spend"]
    print(f"\nSpend: {s['calls']} LLM call(s), {s['input_tokens']} input + "
         f"{s['output_tokens']} output token(s), USD {s['cost_usd']:.4f}.")
    if s["calls"] and s["cost_usd"] == 0.0:
        print("  (0.00 is expected on provider=mock, interactive or claude-code - only "
             "the anthropic provider bills per token.)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--since", default=None, help="ISO timestamp - only spend since then")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    try:
        report = build_report(store, since=args.since)
    finally:
        store.close()

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
