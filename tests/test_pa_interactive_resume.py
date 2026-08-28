"""Regression tests for the two BLOCKER findings an onboarding simulation
raised against `llm.provider: interactive` (see SIMULATION.md, 2026-08-27):

1. An ad-hoc `--question` used to get a random `external_id` on every call,
   so re-running the exact command `workflows/10-ask.md` tells you to
   re-run started a brand-new item at round 1 instead of resuming the
   pending one. Fixed by `tools/engine.py:question_external_id` - a hash of
   the normalized question text plus the day, not a random uuid.
2. Even with a stable id, `tools/tool_loop.py` restarted its round counter
   at 1 on every process invocation and `core.llm._interactive` renamed a
   consumed answer file to `.used`, so a restart re-asked for rounds already
   answered. Fixed by caching every resolved round on
   `item.payload["_rounds"]` and replaying it (no LLM call, no tool
   re-execution) instead of re-asking.

No network, no credentials: only the `interactive` provider's own file
protocol is exercised, redirected into `tmp_path` so this never touches the
real repo's `data/pending/`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

import core.llm as core_llm
from core.config import load_settings
from core.llm import LLMPendingInteractive
from core.store import Store

from tools.engine import answer_question, question_external_id

AS_OF = "2026-06-15"


def _settings(*, provider: str = "interactive"):
    return load_settings(provider=provider, mode="shadow")


def _redirect_pending(monkeypatch, tmp_path) -> Path:
    """Point `core.llm`'s `sub_data_dir("pending")` at `tmp_path/pending`
    instead of this repo's real `data/pending/`. Patching the name inside
    `core.llm`'s own module namespace (not `core.config`) is what actually
    takes effect, since `_interactive()` calls the `sub_data_dir` it imported
    at module load time."""
    pending_dir = tmp_path / "pending"

    def _sub_data_dir(name: str) -> Path:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(core_llm, "sub_data_dir", _sub_data_dir)
    return pending_dir


def test_question_external_id_is_stable_for_the_same_wording_and_day():
    a = question_external_id("How are we doing this month?", AS_OF)
    b = question_external_id("  HOW are we DOING this month?  ", AS_OF)  # re-typed, not identical
    c = question_external_id("How are we doing this month?", "2026-06-16")  # different day
    assert a == b
    assert a != c
    assert a.startswith(f"ask-{AS_OF}-")


def test_rerunning_the_same_ask_command_resumes_the_same_item_and_pending_round(tmp_path, monkeypatch):
    """Finding #1 (BLOCKER) regression: ask with `interactive`, get a pending
    prompt, re-run the exact same command before answering -> same item,
    same pending round, not a brand-new one."""
    _redirect_pending(monkeypatch, tmp_path)
    settings = _settings()
    store = Store(settings, path=tmp_path / "resume1.db")
    question = "How are we doing this month?"
    external_id = question_external_id(question, AS_OF)

    with pytest.raises(LLMPendingInteractive) as first:
        answer_question(settings, store, question, source="cli", external_id=external_id,
                        provider="interactive", as_of=AS_OF)
    with pytest.raises(LLMPendingInteractive) as second:
        # "re-run the same command again" - same question, same external_id,
        # nothing answered yet.
        answer_question(settings, store, question, source="cli", external_id=external_id,
                        provider="interactive", as_of=AS_OF)

    assert first.value.pending_id == second.value.pending_id
    assert first.value.prompt_path == second.value.prompt_path
    assert len(store.list_items()) == 1  # not two orphaned items
    store.close()


def test_three_round_question_resumes_across_restarts_answering_each_round_exactly_once(
        tmp_path, monkeypatch):
    """Finding #2 (BLOCKER) regression: a 3-round question through
    `interactive`, restarting between every answer. Each round's answer is
    written to disk exactly once; a restart never re-pends an already
    answered round, and never re-runs that round's tools."""
    pending_dir = _redirect_pending(monkeypatch, tmp_path)
    settings = _settings()
    store = Store(settings, path=tmp_path / "resume3.db")
    question = "Give me this month's numbers, the spa policy, and a one-line summary."
    external_id = question_external_id(question, AS_OF)

    def _ask():
        return answer_question(settings, store, question, source="cli", external_id=external_id,
                               provider="interactive", as_of=AS_OF)

    seen_pending_ids: list[str] = []

    # Restart 1: nothing answered yet -> pends on round 1.
    with pytest.raises(LLMPendingInteractive) as r1:
        _ask()
    seen_pending_ids.append(r1.value.pending_id)
    r1.value.answer_path.write_text(json.dumps(
        {"step": "tools", "tool_calls": [{"name": "get_financial_summary", "arguments_json": "{}"}]}
    ), encoding="utf-8")

    # Restart 2: round 1 is answered -> resolves live (one LLM call, one tool
    # run), then round 2 pends. Round 1's answer is never asked for again.
    with pytest.raises(LLMPendingInteractive) as r2:
        _ask()
    seen_pending_ids.append(r2.value.pending_id)
    assert r2.value.pending_id != r1.value.pending_id
    r2.value.answer_path.write_text(json.dumps(
        {"step": "tools", "tool_calls": [{"name": "search_knowledge_base",
                                          "arguments_json": "{\"query\": \"spa\"}"}]}
    ), encoding="utf-8")

    # Restart 3: round 2 is answered -> resolves live, round 3 pends.
    with pytest.raises(LLMPendingInteractive) as r3:
        _ask()
    seen_pending_ids.append(r3.value.pending_id)
    assert r3.value.pending_id not in seen_pending_ids[:-1]
    r3.value.answer_path.write_text(json.dumps(
        {"step": "final", "final_json": json.dumps({"reply_markdown": "All good."})}
    ), encoding="utf-8")

    # Restart 4: round 3 (final) is answered -> the question completes.
    item, did_work = _ask()

    assert len(set(seen_pending_ids)) == 3  # three distinct rounds, each pended exactly once
    assert did_work is True
    assert item.review_status == "skipped"
    assert item.draft["reply_markdown"] == "All good."
    assert [c["name"] for c in item.draft["tool_calls"]] == \
        ["get_financial_summary", "search_knowledge_base"]  # each tool ran exactly once

    # Nothing left pending, and every answer file was consumed (renamed
    # `.used`) exactly once - never re-read as a fresh prompt.
    assert list(pending_dir.glob("*.prompt.md")) == []
    assert list(pending_dir.glob("*.schema.json")) == []
    assert len(list(pending_dir.glob("*.json.used"))) == 3

    store.close()


def test_restart_mid_loop_replays_cached_rounds_without_a_store_query_for_the_llm(tmp_path, monkeypatch):
    """The round cache lives on item.payload["_rounds"] and survives the
    upsert_item refresh on every restart (underscore-prefixed payload keys
    are preserved - core/store.py:upsert_item), which is what makes replay
    possible without re-asking the model."""
    _redirect_pending(monkeypatch, tmp_path)
    settings = _settings()
    store = Store(settings, path=tmp_path / "resume_cache.db")
    question = "How are we doing this month, and who is arriving today?"
    external_id = question_external_id(question, AS_OF)

    def _ask():
        return answer_question(settings, store, question, source="cli", external_id=external_id,
                               provider="interactive", as_of=AS_OF)

    with pytest.raises(LLMPendingInteractive) as r1:
        _ask()
    r1.value.answer_path.write_text(json.dumps(
        {"step": "tools", "tool_calls": [{"name": "get_financial_summary", "arguments_json": "{}"}]}
    ), encoding="utf-8")
    with pytest.raises(LLMPendingInteractive):
        _ask()  # resolves round 1 live, pends on round 2

    item = store.get_by_external("cli", external_id)
    cached = (item.payload or {}).get("_rounds") or []
    assert len(cached) == 1
    assert cached[0]["round"] == 1
    assert cached[0]["tool_calls"][0]["name"] == "get_financial_summary"

    store.close()
