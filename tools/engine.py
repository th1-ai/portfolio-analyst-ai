"""tools/engine.py - turn one question into a logged, answered item.

`answer_question()` is the whole thing for one question, shared by
`tools/run.py` (real use) and `tools/demo.py` (the fixtures) so both exercise
exactly the same code path - the same split Hello Desk (the factory's
reference agent) uses for `process_email()`.

Every question becomes a row in `items` (kind="question") whether it is asked
once from the command line or replayed from `fixtures/inbound/`. A question
the loop answers cleanly with a plain text answer needs nobody: it goes
straight to the terminal `skipped` status (informational - it was already
delivered to whoever asked; see `_terminal_status` below for why this is not
`auto_sent`, which this agent never uses). A clean answer that produced a
report (`generate_report`) goes to `pending_review` instead, so a person
looks it over before it counts as an audited answer. A question the loop
could not answer - it ran out of rounds, or the model's JSON did not match
the schema - goes to `needs_human`, so a manager can see exactly which
questions the Analyst could not answer and follow up. Both queues are real
work for `tools/review.py`.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from core.adapters import get_pms
from core.config import Settings
from core.llm import LLMPendingInteractive, LLMSchemaError
from core.store import Item, Store

from tools.tool_loop import LoopResult, ToolLoopExhausted, run_tool_loop
from tools.toolkit import ToolContext

RATE_LIMIT_MESSAGE = (
    "The Analyst has answered its daily quota of questions "
    "({limit}). This is a local safety cap, not a real outage - raise "
    "`rate_limit.max_questions_per_day` in config/agent.yaml, or wait until "
    "tomorrow. Nothing was asked or logged.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def question_external_id(question: str, day: str | None = None) -> str:
    """A stable ``external_id`` for an ad-hoc question: a hash of the
    normalized question text plus the day, not a random uuid.

    Fixes the BLOCKER `tools/run.py --once --question "..."` used to have:
    a random id meant every re-run of the exact command
    `workflows/10-ask.md` tells you to re-run started a brand-new item at
    round 1, orphaning whatever you had already answered. Two calls with the
    same question text (whitespace/case aside) and the same day now resolve
    to the same item, so the same command really does resume it - see
    `tools/tool_loop.py`'s round cache for how a round-in-progress survives
    the restart too. ``day`` defaults to today (UTC); pass ``--as-of`` /
    the digest's own date so tests and fixture demos get a stable id too.
    """
    day = day or datetime.now(timezone.utc).date().isoformat()
    normalized = re.sub(r"\s+", " ", question.strip().lower())
    digest = hashlib.sha256(f"{day}\n{normalized}".encode()).hexdigest()[:12]
    return f"ask-{day}-{digest}"


def check_rate_limit(settings: Settings, store: Store) -> tuple[bool, int, int]:
    """``(ok, asked_today, limit)``. Fails OPEN: any error reading/writing the
    counter is treated as "ok" rather than blocking a real question.

    ``--dry-run`` still reads the real counter (so a rehearsal respects the
    same cap a live run would see) but never increments it - a rehearsal must
    never spend part of the day's real quota."""
    limit = int(settings.agent_get("rate_limit.max_questions_per_day", 200))
    key = f"questions_asked:{datetime.now(timezone.utc).date().isoformat()}"
    try:
        asked = int(store.get(key, 0) or 0)
    except Exception:  # noqa: BLE001 - fail open, never block on a bookkeeping bug
        return True, 0, limit
    if asked >= limit:
        return False, asked, limit
    if not settings.dry_run:
        try:
            store.set(key, asked + 1)
        except Exception:  # noqa: BLE001
            pass
    return True, asked, limit


def _placeholder_item(source: str, external_id: str, question: str, asked_by: str) -> Item:
    """An in-memory :class:`Item`, never inserted - what ``--dry-run`` returns.
    See ARCHITECTURE.md's dry-run contract: compute everything, write nothing
    - not a database row, not a sequence bump, not an export file."""
    now = _now()
    return Item(id=f"dryrun-{uuid.uuid4().hex[:10]}", kind="question", source=source,
               external_id=external_id, payload={"question": question, "asked_by": asked_by,
                                                  "asked_at": now}, created_at=now, updated_at=now)


def answer_question(settings: Settings, store: Store, question: str, *,
                    source: str = "cli", external_id: str | None = None,
                    asked_by: str = "owner", provider: str | None = None,
                    as_of: str | None = None) -> tuple[Item, bool]:
    """Answer one question end to end and queue the result.

    Idempotent on ``(source, external_id)``: an item that already left the
    "new" status - answered cleanly, or waiting on a human - is returned
    untouched (``did_work=False``) rather than re-asked and re-billed. See
    the note above the status check below for why "new" is the only status
    this function ever acts from.

    ``--dry-run`` (``settings.dry_run``) computes the same tool loop but never
    touches the store: no item row, no event row, no LLM usage row, and
    (through the normal write guard) no export file either. A second
    ``--dry-run`` pass over the same question is always safe to repeat.

    ``external_id`` should be **stable** across restarts of the same logical
    question - `tools/run.py` passes ``question_external_id(question, day)``
    (this module) for the ad-hoc CLI path and ``digest-{day}-{i}`` for the
    standing digest; a random id here is what used to make an ad-hoc question
    unresumable (every restart looked like a new question - see
    `tools/tool_loop.py`'s module docstring). ``upsert_item`` refreshing
    ``payload`` on a re-run never wipes the tool loop's own
    ``payload["_rounds"]`` cache, because that key starts with ``_`` -
    underscore-prefixed payload keys are preserved across the refresh by
    design (``core/store.py:upsert_item``), which is what lets a mid-loop
    restart resume from the right round instead of round 1.
    """
    external_id = external_id or uuid.uuid4().hex
    record_store = None if settings.dry_run else store

    if not settings.dry_run:
        item = store.upsert_item(source, external_id, kind="question",
                                 payload={"question": question, "asked_by": asked_by,
                                         "asked_at": _now()})
        # Idempotent on (source, external_id): "new" is the only status this
        # function ever acts from. `skipped`/`pending_review` mean it already
        # has an answer; `needs_human` is waiting on a person - the shared
        # review_status FSM (core/store.py) only lets a human move an item out
        # of needs_human (approve/edit/reject) or pending_review (the same),
        # so re-running the tool loop over it here would try an illegal
        # transition rather than genuinely resuming anything.
        if item.review_status != "new":
            return item, False
    else:
        item = _placeholder_item(source, external_id, question, asked_by)

    ok, asked_today, limit = check_rate_limit(settings, store)
    if not ok:
        message = RATE_LIMIT_MESSAGE.format(limit=limit)
        draft = {"reply_markdown": message, "tool_calls": [], "reports": []}
        if settings.dry_run:
            item.draft, item.review_status = draft, "needs_human"
            return item, True
        store.set_fields(item.id, draft=draft)
        updated = store.transition(item.id, "needs_human", actor="agent",
                                   detail={"reason": "rate_limited", "asked_today": asked_today})
        return updated, True

    pms = get_pms(settings)
    ctx = ToolContext.build(settings, pms, today=as_of)
    try:
        result = run_tool_loop(settings, record_store, item, question, ctx,
                               provider=provider, fixture_id=external_id)
    except LLMPendingInteractive:
        raise  # let tools/run.py print the pending prompt and exit 3
    except (LLMSchemaError, ToolLoopExhausted) as exc:
        # Deliberately does NOT set `draft` - see the resumable-stages note in
        # ARCHITECTURE.md/build-repo.md: leaving `draft` unset is what lets the
        # NEXT `make run` pass retry this exact question automatically instead
        # of it being stuck until a human runs `tools/review.py retry`. What
        # was actually attempted is still visible to a reviewer, just filed
        # under payload._last_attempt rather than draft - `tools/review.py show`
        # prints the whole item, including payload.
        attempted = {"tool_calls": getattr(exc, "tool_calls", []),
                    "reports": getattr(exc, "reports", [])}
        if settings.dry_run:
            item.payload = {**(item.payload or {}), "_last_attempt": attempted}
            item.error, item.review_status = str(exc), "needs_human"
            return item, True
        store.set_fields(item.id, payload={**(item.payload or {}), "_last_attempt": attempted},
                         error=str(exc))
        updated = store.transition(item.id, "needs_human", actor="agent",
                                   detail={"reason": "loop_failed", "error": str(exc)[:300],
                                          "tool_calls": len(attempted["tool_calls"])})
        return updated, True

    draft = {"reply_markdown": result.reply_markdown, "tool_calls": result.tool_calls,
            "reports": result.reports}
    status = _terminal_status(result)
    if settings.dry_run:
        item.draft, item.review_status = draft, status
        return item, True

    store.set_fields(item.id, draft=draft)
    # Straight from "new" - core/store.py's TRANSITIONS allows "skipped" and
    # "needs_human" directly from "new", but NOT from "dispatched", and this
    # agent never actually dispatches anything for per-item sending (see
    # _terminal_status below), so there is no intermediate step to record.
    updated = store.transition(item.id, status, actor="agent",
                               detail={"rounds": result.rounds_used,
                                      "tool_calls": len(result.tool_calls),
                                      "reports": len(result.reports)})
    return updated, True


def _terminal_status(result: LoopResult) -> str:
    """Where a cleanly-finished question lands.

    `auto_sent` in this family means "a guarded write actually happened, with
    no human in the loop" (core/review.py). Nothing here ever fits that: an
    ad-hoc or fixture-replayed answer is printed straight to the person who
    asked and nothing is written anywhere; the scheduled digest's export
    (tools/digest.py) is a single bulk write covering the whole run, not a
    per-item send tied to one question's approval. So a clean answer is
    either:

    - `pending_review` - it called `generate_report`, so there is a report
      card a person should look over before it is treated as final (and,
      via `tools/review.py send`, before it is exported to
      `data/exports/answered_questions.csv` as an audited answer).
    - `skipped` - a plain text answer with nothing to export. Informational:
      it was already delivered to whoever asked, in full, right there.
    """
    if not result.reply_markdown.strip():
        return "needs_human"
    return "pending_review" if result.reports else "skipped"
