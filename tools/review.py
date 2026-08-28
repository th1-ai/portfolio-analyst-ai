#!/usr/bin/env python3
"""tools/review.py - work the queue of questions waiting for a person.

    python3 tools/review.py list [--status needs_human] [--kind question]
    python3 tools/review.py show <id>
    python3 tools/review.py approve <id> [--note "..."]
    python3 tools/review.py edit <id> --body-file answer.txt [--note "..."]
    python3 tools/review.py reject <id> --reason "out of scope"
    python3 tools/review.py retry <id>          # re-queue a failed export
    python3 tools/review.py send                # export approved/edited answers
    python3 tools/review.py stale                # go-live step

Most plain-text questions never reach this queue: a clean answer with
nothing to export goes straight to `skipped` (see docs/how-it-works.md).
Two kinds of question do land here - `python3 tools/review.py list` shows
both together: a question that produced a report (`pending_review` - a
person should look it over before it counts as an audited answer), and a
question the tool loop genuinely could not answer (`needs_human` - it ran
out of rounds, a tool kept failing, or the model's JSON did not match the
schema). `approve` records that the answer on file is correct as-is;
`edit` rewrites it; `send` exports every approved/edited answer to
`data/exports/answered_questions.csv` for the record. Nothing here ever
touches your PMS or a guest - this agent has no such tool at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_sheets  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.review import (WriteBlocked, approve, edit, list_queue, reject,  # noqa: E402
                         retry, show, stale_backlog)
from core.store import Store, StoreError  # noqa: E402


def _print_item_line(item) -> None:
    payload = item.payload or {}
    question = str(payload.get("question", ""))
    # `item.is_sample` is set by core (core/store.py) for anything read
    # through a mock adapter outside `make demo` - see docs/integrations.md
    # "Sample data is labelled".
    marker = "  [SAMPLE DATA]" if item.is_sample else ""
    print(f"  {item.id}  {item.review_status:<14} {question[:60]}{marker}")


def cmd_list(store, args) -> int:
    items = list_queue(store, status=args.status, kind=args.kind or "question", limit=args.limit)
    if not items:
        print("Nothing is waiting for you. Every question so far was either answered "
             "cleanly or already resolved.")
        return 0
    print(f"{len(items)} question(s) waiting:\n")
    for item in items:
        _print_item_line(item)
    print("\nRun `python3 tools/review.py show <id>` for the full question and tool log.")
    return 0


def cmd_show(store, args) -> int:
    try:
        detail = show(store, args.id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if (detail["item"].get("payload") or {}).get("_sample"):
        print("[SAMPLE DATA] this item was read through a mock adapter, not your "
             "property - see docs/integrations.md.\n")
    print(json.dumps(detail, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_approve(store, args) -> int:
    item = approve(store, args.id, note=args.note or "")
    print(f"approved {item.id} - now in the export queue (`send`)")
    return 0


def cmd_edit(store, args) -> int:
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    body = Path(args.body_file).read_text(encoding="utf-8")
    new_draft = dict(item.draft or {})
    new_draft["reply_markdown"] = body
    edit(store, args.id, new_draft, note=args.note or "")
    print(f"edited {item.id} - now in the export queue (`send`)")
    return 0


def cmd_reject(store, args) -> int:
    item = reject(store, args.id, reason=args.reason or "")
    print(f"rejected {item.id}")
    return 0


def cmd_retry(store, args) -> int:
    """Re-queue an answer whose EXPORT failed (`send` below), not the question
    itself - the answer text is already approved/edited and unchanged. Fix
    whatever broke the export (`make doctor` says what), then retry."""
    item = retry(store, args.id)
    print(f"queued {item.id} for another export attempt - run `python3 tools/review.py send`")
    return 0


def cmd_send(store, settings, args) -> int:
    claimed = store.claim_for_send(limit=args.limit)
    if not claimed:
        print("Nothing approved or edited is waiting to export.")
        return 0
    sheets = get_sheets(settings)
    sent, failed = 0, 0
    for item in claimed:
        draft = item.draft or {}
        payload = item.payload or {}
        row = [item.id, payload.get("question", ""), payload.get("asked_by", ""),
              draft.get("reply_markdown", "").replace("\n", " ")[:2000]]
        try:
            existing = sheets.read("answered_questions")
        except Exception:  # noqa: BLE001
            existing = []
        rows = [row] if existing else [["item_id", "question", "asked_by", "answer"], row]
        try:
            sheets.append("answered_questions", rows, item=item)
        except WriteBlocked as exc:
            # Not a failure: the mode blocked it. The approval stands for go-live.
            store.transition(item.id, "approved", "agent", {"blocked": str(exc)[:200]})
            print(f"blocked {item.id} (approval kept): {exc}")
            failed += 1
            continue
        except Exception as exc:  # noqa: BLE001 - record and move on, never crash the batch
            store.mark_send_failed(item.id, str(exc))
            print(f"failed {item.id}: {exc}")
            failed += 1
            continue
        store.mark_sent(item.id)
        print(f"exported {item.id}")
        sent += 1
    print(f"\n{sent} exported, {failed} failed.")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="what is waiting for a human")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--kind", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sub.add_parser("show", help="full detail for one question")
    p_show.add_argument("id")

    p_approve = sub.add_parser("approve", help="the answer on file is correct as-is")
    p_approve.add_argument("id")
    p_approve.add_argument("--note", default="")

    p_edit = sub.add_parser("edit", help="rewrite the answer, then queue it for export")
    p_edit.add_argument("id")
    p_edit.add_argument("--body-file", required=True)
    p_edit.add_argument("--note", default="")

    p_reject = sub.add_parser("reject", help="discard - not a question this agent should answer")
    p_reject.add_argument("id")
    p_reject.add_argument("--reason", default="")

    p_retry = sub.add_parser("retry", help="re-queue a failed export")
    p_retry.add_argument("id")

    p_send = sub.add_parser("send", help="export everything approved or edited")
    p_send.add_argument("--limit", type=int, default=20)

    sub.add_parser("stale", help="go-live step: mark everything still un-exported as stale "
                                 "(the shadow-era queue was never exported and may be out of date)")

    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    try:
        if args.command == "list":
            return cmd_list(store, args)
        if args.command == "show":
            return cmd_show(store, args)
        if args.command == "approve":
            return cmd_approve(store, args)
        if args.command == "edit":
            return cmd_edit(store, args)
        if args.command == "reject":
            return cmd_reject(store, args)
        if args.command == "retry":
            return cmd_retry(store, args)
        if args.command == "send":
            return cmd_send(store, settings, args)
        if args.command == "stale":
            moved = stale_backlog(store)
            print(f"marked {len(moved)} item(s) stale. Nothing from before go-live will "
                 f"be exported by surprise.")
            return 0
        parser.error(f"unknown command {args.command}")
        return 2
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
