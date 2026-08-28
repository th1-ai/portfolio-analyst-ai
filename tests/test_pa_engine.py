"""Tests for tools/engine.py - the whole loop for one question, with
provider=mock against fixtures/expected/ask/. No network, no credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings
from core.store import Store

from tools import review
from tools.engine import _terminal_status, answer_question
from tools.tool_loop import LoopResult

AS_OF = "2026-06-15"


def _settings(*, dry_run: bool = False, mode: str = "shadow"):
    return load_settings(provider="mock", mode=mode, dry_run=dry_run)


def test_a_plain_clean_answer_is_skipped_with_no_human_needed(tmp_path):
    store = Store(_settings(), path=tmp_path / "engine1.db")
    item, did_work = answer_question(_settings(), store, "How are we doing this month?",
                                     source="test", external_id="q-financial-summary",
                                     provider="mock", as_of=AS_OF)
    assert did_work is True
    # skipped, not auto_sent: nothing was actually sent anywhere for this
    # item - see tools/engine.py:_terminal_status. auto_sent is reserved for
    # an item whose OWN guarded write actually succeeded, which never
    # happens for a plain text answer in this agent.
    assert item.review_status == "skipped"
    assert "98,589" in item.draft["reply_markdown"] or "revenue" in item.draft["reply_markdown"].lower()
    assert len(item.draft["tool_calls"]) == 1
    store.close()


def test_a_report_question_lands_in_pending_review_for_a_person_to_check(tmp_path):
    store = Store(_settings(), path=tmp_path / "engine2.db")
    item, _ = answer_question(_settings(), store,
                              "Build me a weekly briefing report with KPIs and a revenue chart",
                              source="test", external_id="q-weekly-report",
                              provider="mock", as_of=AS_OF)
    # pending_review, not skipped: a report was produced, so a person should
    # look it over before it counts as an audited answer (tools/review.py).
    assert item.review_status == "pending_review"
    assert len(item.draft["reports"]) == 1
    assert item.draft["reports"][0]["chart"]["type"] == "line"
    store.close()


def test_a_question_the_loop_cannot_answer_escalates_to_needs_human(tmp_path):
    store = Store(_settings(), path=tmp_path / "engine3.db")
    item, did_work = answer_question(
        _settings(), store, "What is our marketing spend by channel this quarter, and ROAS?",
        source="test", external_id="q-marketing-spend", provider="mock", as_of=AS_OF)
    assert did_work is True
    assert item.review_status == "needs_human"
    # what it tried is still visible for a reviewer, even though it never answered
    assert len(item.payload["_last_attempt"]["tool_calls"]) == 6
    store.close()


def test_the_same_external_id_asked_twice_is_a_no_op_the_second_time(tmp_path):
    store = Store(_settings(), path=tmp_path / "engine4.db")
    first, did_work_1 = answer_question(_settings(), store, "How are we doing this month?",
                                        source="test", external_id="q-financial-summary",
                                        provider="mock", as_of=AS_OF)
    second, did_work_2 = answer_question(_settings(), store, "How are we doing this month?",
                                         source="test", external_id="q-financial-summary",
                                         provider="mock", as_of=AS_OF)
    assert did_work_1 is True
    assert did_work_2 is False
    assert second.id == first.id
    assert len(store.list_items()) == 1
    store.close()


def test_dry_run_never_writes_an_item_row(tmp_path):
    db_path = tmp_path / "engine5.db"
    store = Store(_settings(), path=db_path)
    before = store.counts()
    item, did_work = answer_question(_settings(dry_run=True), store, "How are we doing this month?",
                                     source="test", external_id="q-financial-summary",
                                     provider="mock", as_of=AS_OF)
    after = store.counts()
    assert did_work is True
    assert item.review_status == "skipped"
    assert before == after == {}
    assert item.id.startswith("dryrun-")
    store.close()


def test_dry_run_twice_in_a_row_never_raises_an_integrity_error(tmp_path):
    store = Store(_settings(), path=tmp_path / "engine6.db")
    dry_settings = _settings(dry_run=True)
    for _ in range(2):
        item, did_work = answer_question(dry_settings, store, "How are we doing this month?",
                                         source="test", external_id="q-financial-summary",
                                         provider="mock", as_of=AS_OF)
        assert did_work is True
        assert item.review_status == "skipped"
    assert store.counts() == {}
    store.close()


def test_rate_limit_queues_needs_human_once_the_daily_cap_is_reached(tmp_path):
    settings = _settings()
    settings.agent["rate_limit"] = {"max_questions_per_day": 1}
    store = Store(settings, path=tmp_path / "engine7.db")
    first, _ = answer_question(settings, store, "How are we doing this month?", source="test",
                               external_id="q-financial-summary", provider="mock", as_of=AS_OF)
    assert first.review_status == "skipped"
    second, did_work = answer_question(settings, store, "Who is arriving today?", source="test",
                                       external_id="q-arrivals-today", provider="mock", as_of=AS_OF)
    assert did_work is True
    assert second.review_status == "needs_human"
    assert "quota" in second.draft["reply_markdown"]
    store.close()


def test_terminal_status_never_returns_auto_sent():
    # auto_sent means an item's OWN guarded write succeeded autonomously;
    # nothing in this agent's design does that per-item (see
    # tools/engine.py:_terminal_status), so it must never come out of here.
    assert _terminal_status(LoopResult(reply_markdown="")) == "needs_human"
    assert _terminal_status(LoopResult(reply_markdown="an answer")) == "skipped"
    assert _terminal_status(LoopResult(reply_markdown="an answer",
                                       reports=[{"title": "T"}])) == "pending_review"


def test_sample_item_shows_marker_in_list_line_and_show(tmp_path, capsys):
    """core/store.py tags an item read through a mock adapter outside `make
    demo` as `_sample` (`Item.is_sample`) - a human working the real queue
    must see that at a glance, in both `list` and `show`."""
    store = Store(_settings(), path=tmp_path / "sample.db")
    item = store.upsert_item("pms", "sample-marker-1", kind="question",
                             payload={"question": "How are arrivals looking today?",
                                      "_sample": True})
    assert item.is_sample

    capsys.readouterr()
    review._print_item_line(item)
    assert "[SAMPLE DATA]" in capsys.readouterr().out

    rc = review.cmd_show(store, SimpleNamespace(id=item.id))
    assert rc == 0
    assert "[SAMPLE DATA]" in capsys.readouterr().out
    store.close()
