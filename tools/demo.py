#!/usr/bin/env python3
"""tools/demo.py - the whole loop on the bundled fixtures, zero credentials.

    make demo
    python3 tools/demo.py

`load_settings(demo=True)` forces `llm.provider=mock`, `mode=shadow` and the
`mock` adapter for every system, whatever config/hotel.yaml says, so this
always works on a fresh clone with a blank .env. It runs against its own
database (data/demo/demo.db) and never touches data/agent.db (that is `make
run`'s file), so running it twice always shows the same result.

FIXTURE_TODAY pins "today" to the last day covered by
fixtures/hotel/financial_daily.json, so the numbers you see are real
arithmetic over invented data, not zeros - see docs/how-it-works.md "Design
decisions". A real `make run` always uses the real date.

Prints one line every check reads for the pass/fail signal:

    DEMO OK — 5 items processed, 5 drafted, 0 sent (shadow)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, load_settings, sub_data_dir  # noqa: E402
from core.log import summary_line  # noqa: E402
from core.store import Store  # noqa: E402
from tools.engine import answer_question  # noqa: E402

FIXTURE_TODAY = "2026-06-15"


def _load_fixture_questions() -> list[dict]:
    inbound = REPO_ROOT / "fixtures" / "inbound"
    items = []
    for path in sorted(inbound.glob("question-*.json")):
        items.append(json.loads(path.read_text(encoding="utf-8")))
    return items


def main() -> int:
    try:
        settings = load_settings(demo=True)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    demo_db = sub_data_dir("demo") / "demo.db"
    if demo_db.exists():
        demo_db.unlink()  # every `make demo` is a clean, repeatable run
    store = Store(settings, path=demo_db)

    questions = _load_fixture_questions()
    if not questions:
        print("no fixtures found in fixtures/inbound/ - nothing to demo", file=sys.stderr)
        return 1

    stats = {"processed": 0, "drafted": 0, "needs_human": 0, "sent": 0}
    print(f"Portfolio Analyst AI demo - {len(questions)} sample question(s) from "
         f"fixtures/inbound/, pretending today is {FIXTURE_TODAY}\n")
    for entry in questions:
        item, _ = answer_question(settings, store, entry["question"], source="demo",
                                  external_id=entry["id"], asked_by=entry.get("asked_by", "owner"),
                                  provider="mock", as_of=FIXTURE_TODAY)
        stats["processed"] += 1
        stats["drafted"] += 1
        if item.review_status == "needs_human":
            stats["needs_human"] += 1
        draft = item.draft or {}
        if item.review_status == "needs_human":
            attempted = ((item.payload or {}).get("_last_attempt") or {}).get("tool_calls") or []
            tool_names = ", ".join(c["name"] for c in attempted) or "none"
            answer_preview = "(could not answer - see `python3 tools/review.py show " + item.id + "`)"
        else:
            tool_names = ", ".join(c["name"] for c in draft.get("tool_calls") or []) or "none"
            lines = (draft.get("reply_markdown") or "").splitlines()
            answer_preview = lines[0][:70] if lines else "(empty answer)"
        print(f"  {entry['id']}: \"{entry['question'][:50]}\" -> tools=[{tool_names}] "
             f"status={item.review_status}")
        print(f"      {answer_preview}")

    print(f"\n{stats['needs_human']} of {stats['processed']} could not be answered cleanly "
         f"(see docs/safety.md for why that happens).")
    print("Nothing was exported: mode is shadow, and generate_report never writes on its own.")
    print("Next: `make review` to see anything waiting, or read workflows/10-ask.md.\n")

    print(f"DEMO OK — {summary_line(stats, settings.mode)}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
