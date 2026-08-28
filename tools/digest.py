"""tools/digest.py - the standing morning briefing.

    python3 tools/run.py --once --digest
    make run ARGS="--digest"

Asks every question in `config/agent.yaml: digest.questions` (ported from the
source system's scheduled-reports job - see docs/how-it-works.md), logs each
one as its own `items` row via `tools/engine.py:answer_question` exactly like
an ad-hoc question, then exports one combined row to
`data/exports/digest_reports.csv` through the Sheets adapter.

The export is a real write (`sheets_write`, `core/adapters/base.py`), so it
goes through the same guard as everything else in this family: nothing is
written in `mode: shadow`. In `mode: live` it runs straight through -
`sheets_write` is not on `review.require_approval_for` by default, because a
local CSV export is not guest-facing and does not touch the PMS. Add it to
that list in `config/hotel.yaml` if you want a person to approve each
morning's digest before it lands on disk.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from core.adapters import get_sheets
from core.review import WriteBlocked
from core.config import Settings
from core.log import Run, get_logger
from core.store import Store

from tools.engine import answer_question

log = get_logger("digest")


def run_digest(settings: Settings, store: Store, *, provider: str | None = None,
               as_of: str | None = None) -> tuple[int, dict]:
    questions = list(settings.agent_get("digest.questions", []) or [])
    stats = {"processed": 0, "drafted": 0, "needs_human": 0, "sent": 0, "skipped": 0}
    if not questions:
        log.warn("no digest.questions configured in config/agent.yaml")
        return 0, stats

    today = as_of or datetime.now(timezone.utc).date().isoformat()
    answers = []
    run_store = None if settings.dry_run else store  # --dry-run writes no `runs` row either
    with Run("digest", settings, run_store) as run:
        for i, question in enumerate(questions):
            item, did_work = answer_question(
                settings, store, question, source="digest",
                external_id=f"digest-{today}-{i}", asked_by="digest",
                provider=provider, as_of=as_of)
            if did_work:
                stats["processed"] += 1
                stats["drafted"] += 1
                if item.review_status == "needs_human":
                    stats["needs_human"] += 1
            else:
                stats["skipped"] += 1
            draft = item.draft or {}
            answers.append({"question": question, "status": item.review_status,
                           "reply_markdown": draft.get("reply_markdown", "")})

        exported, reason = _export(settings, today, answers)
        if exported:
            stats["sent"] = 1
        run.stats = dict(stats)
        log.info("digest complete", exported=exported, reason=reason,
                 processed=stats["processed"], needs_human=stats["needs_human"])
    return 0, stats


def _export(settings: Settings, today: str, answers: list[dict]) -> tuple[bool, str]:
    sheets = get_sheets(settings)
    rows = [[today, a["question"], a["status"], a["reply_markdown"].replace("\n", " ")[:2000]]
           for a in answers]
    try:
        existing = sheets.read("digest_reports")
    except Exception:  # noqa: BLE001 - a broken read must not block the export attempt
        existing = []
    if not existing:
        rows = [["date", "question", "status", "answer"], *rows]
    try:
        sheets.append("digest_reports", rows)
    except WriteBlocked as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - a broken export must not fail the digest
        return False, f"export failed: {exc}"
    return True, "exported to data/exports/digest_reports.csv"
