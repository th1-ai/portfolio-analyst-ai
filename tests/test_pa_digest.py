"""Tests for tools/digest.py - the standing morning briefing and its export.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings
from core.store import Store

from tools.digest import run_digest

AS_OF = "2026-06-15"


def _settings(mode: str, tmp_path: Path):
    """Real config/agent.example.yaml (digest.questions and all), but the
    Sheets export redirected into the test's own tmp dir - never the real
    repo's data/exports/. See core/adapters/sheets_csv.py:CsvSheets."""
    settings = load_settings(provider="mock", mode=mode)
    settings.systems.sheets.options["exports_dir"] = str(tmp_path / "exports")
    return settings


def test_shadow_mode_never_writes_the_digest_export_file(tmp_path):
    settings = _settings("shadow", tmp_path)
    store = Store(settings, path=tmp_path / "digest1.db")
    code, stats = run_digest(settings, store, provider="mock", as_of=AS_OF)
    assert code == 0
    assert stats["sent"] == 0  # blocked - see core/review.py, shadow is a global kill switch
    assert not (tmp_path / "exports" / "digest_reports.csv").exists()
    store.close()


def test_live_mode_exports_one_row_per_digest_question(tmp_path):
    settings = _settings("live", tmp_path)
    store = Store(settings, path=tmp_path / "digest2.db")
    code, stats = run_digest(settings, store, provider="mock", as_of=AS_OF)
    assert code == 0
    assert stats["sent"] == 1
    export_path = tmp_path / "exports" / "digest_reports.csv"
    assert export_path.exists()
    lines = export_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("date,question,status,answer")
    n_questions = len(settings.agent_get("digest.questions", []))
    assert len(lines) == 1 + n_questions
    store.close()


def test_digest_logs_every_question_as_its_own_item(tmp_path):
    settings = _settings("live", tmp_path)
    store = Store(settings, path=tmp_path / "digest3.db")
    run_digest(settings, store, provider="mock", as_of=AS_OF)
    items = store.list_items(kind="question")
    n_questions = len(settings.agent_get("digest.questions", []))
    assert len(items) == n_questions
    store.close()


def test_no_digest_questions_configured_is_a_harmless_no_op(tmp_path):
    settings = _settings("live", tmp_path)
    settings.agent["digest"] = {"questions": []}
    store = Store(settings, path=tmp_path / "digest4.db")
    code, stats = run_digest(settings, store, provider="mock", as_of=AS_OF)
    assert code == 0
    assert stats["processed"] == 0
    store.close()
