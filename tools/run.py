#!/usr/bin/env python3
"""tools/run.py - Portfolio Analyst AI's main loop: ask -> tool loop -> log.

    python3 tools/run.py --once --question "How are we doing this month?"
    python3 tools/run.py --once --digest              # the standing morning briefing
    python3 tools/run.py --watch --digest              # keep running it on schedule
    python3 tools/run.py --once --question "..." --provider mock
    python3 tools/run.py --once --question "..." --as-of 2026-06-15   # tests/demo only
    python3 tools/run.py --once --question "..." --resume ask-2026-06-15-a1b2c3d4e5f6

There is no inbox to poll here (ARCHITECTURE.md's "fetch -> dedup -> decide"
shape becomes "ask -> tool loop -> log" for a chat-shaped agent - see
docs/how-it-works.md). `--question` answers one question right now, the way
the source system's chat box does. `--digest` asks the standing list in
`config/agent.yaml: digest.questions` and exports the results - see
`workflows/16-digest.md`. Neither ever sends anything or writes to your PMS;
see docs/safety.md.

Every `--question` run prints `question id: ask-<day>-<hash>` first. The id
comes from a hash of the normalized question text plus the day
(`tools/engine.py:question_external_id`), not a random number, so re-running
the exact same command - the way `workflows/10-ask.md` tells you to when
`llm.provider: interactive` is waiting on an answer - resumes the same
question instead of starting a new one. Pass `--resume <id>` to continue a
specific question by that printed id instead (useful if you reworded the
question, or the day rolled over).

Exit codes: 0 ok, 3 waiting on an `interactive` answer (see the message),
1 a real error. That is the direct `python3 tools/run.py` exit code. Through
`make run ARGS='...'`, `make` wraps it: GNU Make reports its own generic
failure code (2) for any failing recipe and separately prints the real one,
e.g. `make: *** [run] Error 3` - read the `3` after `Error` in that printed
line, not `make`'s own `$?`.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.llm import LLMError, LLMPendingInteractive  # noqa: E402
from core.log import Run, get_logger, summary_line  # noqa: E402
from core.store import Store  # noqa: E402
from tools.digest import run_digest  # noqa: E402
from tools.engine import answer_question, question_external_id  # noqa: E402

log = get_logger("run")


def ask_once(settings, store, *, question: str, asked_by: str, provider: str | None,
            as_of: str | None, external_id: str) -> tuple[int, dict]:
    stats = {"processed": 0, "drafted": 0, "needs_human": 0, "sent": 0, "skipped": 0}
    print(f"question id: {external_id}")
    run_store = None if settings.dry_run else store  # --dry-run writes no `runs` row either
    with Run("ask", settings, run_store) as run:
        item, did_work = answer_question(settings, store, question, source="cli",
                                         external_id=external_id, asked_by=asked_by,
                                         provider=provider, as_of=as_of)
        if not did_work:
            print(f"Already answered ({item.review_status}) - "
                 f"reword the question, wait until tomorrow, or run "
                 f"`python3 tools/review.py show {item.id}` to see it, to ask again.")
            stats["skipped"] = 1
            run.stats = dict(stats)
            return 0, stats
        stats["processed"] = 1
        stats["drafted"] = 1
        if item.review_status == "needs_human":
            stats["needs_human"] = 1
        draft = item.draft or {}
        print(draft.get("reply_markdown", "(no answer)"))
        for report in draft.get("reports") or []:
            print(f"\n[report: {report.get('title')}]")
        log.info("answered", item_id=item.id, status=item.review_status,
                 tool_calls=len(draft.get("tool_calls") or []))
        run.stats = dict(stats)
    return 0, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--once", action="store_true", help="run once (default)")
    mode_group.add_argument("--watch", action="store_true",
                            help="keep running --digest on the configured interval")
    parser.add_argument("--question", default=None, help="ask one question and print the answer")
    parser.add_argument("--resume", default=None, metavar="ID",
                        help="continue a specific pending question by the id printed when it "
                             "first paused, instead of deriving one from --question's wording")
    parser.add_argument("--digest", action="store_true",
                        help="ask the standing digest.questions list and export the results")
    parser.add_argument("--asked-by", default="owner", help="who is asking (for the audit log)")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute everything, export nothing, even in live mode")
    parser.add_argument("--provider", default=None, help="override llm.provider for this run")
    parser.add_argument("--as-of", default=None,
                        help="pretend this ISO date is 'today' (tests and fixture demos only)")
    parser.add_argument("--poll-seconds", type=int, default=None,
                        help="override the --watch interval (default: agent.yaml or 3600)")
    args = parser.parse_args(argv)

    if not args.question and not args.digest:
        parser.error("pass --question \"...\" or --digest")
    if args.resume and not args.question:
        parser.error("--resume only makes sense with --question")

    try:
        settings = load_settings(provider=args.provider, dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    try:
        if args.watch:
            if not args.digest:
                parser.error("--watch only makes sense with --digest")
            poll_seconds = args.poll_seconds or int(settings.agent_get("poll_seconds", 3600))
            while True:
                code, stats = run_digest(settings, store, provider=args.provider, as_of=args.as_of)
                print(summary_line(stats, settings.mode))
                if code != 0:
                    return code
                time.sleep(poll_seconds)
        if args.digest:
            code, stats = run_digest(settings, store, provider=args.provider, as_of=args.as_of)
        else:
            day = args.as_of or datetime.now(timezone.utc).date().isoformat()
            external_id = args.resume or question_external_id(args.question, day)
            code, stats = ask_once(settings, store, question=args.question,
                                   asked_by=args.asked_by, provider=args.provider,
                                   as_of=args.as_of, external_id=external_id)
        print(summary_line(stats, settings.mode))
        return code
    except LLMPendingInteractive as exc:
        print(str(exc))
        return 3
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
