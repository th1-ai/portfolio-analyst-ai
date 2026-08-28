"""Tests for tools/toolkit.py - the seven tools, in isolation from the LLM
loop. No network, no credentials, provider=mock throughout.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_pms
from core.config import load_settings

from tools import data as pa_data
from tools.toolkit import (ToolContext, ToolError, generate_report, get_agent_status,
                           get_financial_summary, list_pending_emails, list_reservations,
                           run_forecast, search_knowledge_base)


def _settings():
    return load_settings(provider="mock", mode="shadow")


def _synthetic_rows() -> list[dict]:
    """A tiny, hand-checkable financial ledger: two years of one repeated day
    (today and the same day last year), so every total is easy to verify."""
    rows = []
    for d, revenue_rooms, occ in (("2025-06-01", 1000.0, 60.0), ("2026-06-01", 1100.0, 66.0)):
        rows.append({"date": d, "revenue_rooms": revenue_rooms, "revenue_fnb": 200.0,
                    "revenue_other": 50.0, "revenue_total": revenue_rooms + 250.0,
                    "costs_total": 800.0, "profit": revenue_rooms + 250.0 - 800.0,
                    "occupancy_pct": occ, "adr": 140.0, "rooms_available": 42})
    return rows


def test_get_financial_summary_computes_vs_last_year_from_matching_day():
    ctx = ToolContext(settings=_settings(), pms=get_pms(_settings()), today="2026-06-01",
                      financial_rows=_synthetic_rows())
    out = get_financial_summary(ctx, {})
    assert out["today"]["revenue"] == 1350.0          # 1100 + 200 + 50
    assert out["today"]["vs_last_year_revenue"] == "+8.0%"   # (1350-1250)/1250
    assert out["mtd"]["revenue_total"] == 1350.0        # only one day of June 2026 in the fixture


def test_list_reservations_today_arrivals_uses_the_bundled_fixture():
    settings = _settings()
    ctx = ToolContext.build(settings, get_pms(settings), today="2026-06-15")
    out = list_reservations(ctx, {"window": "today_arrivals"})
    assert out["window"] == "today_arrivals"
    assert out["count"] == 3
    assert out["truncated"] is False
    refs = {row["ref"] for row in out["rows"]}
    assert refs == {"AUR-1003", "AUR-1004", "AUR-1013"}


def test_list_reservations_rejects_an_unknown_window():
    settings = _settings()
    ctx = ToolContext.build(settings, get_pms(settings), today="2026-06-15")
    try:
        list_reservations(ctx, {"window": "next_millennium"})
        assert False, "expected a ToolError"
    except ToolError:
        pass


def test_search_knowledge_base_ranks_the_matching_spa_passage_first():
    settings = _settings()
    ctx = ToolContext.build(settings, get_pms(settings), today="2026-06-15")
    out = search_knowledge_base(ctx, {"query": "spa children policy age"})
    assert out["fallback"] is False
    assert out["count"] > 0
    assert "16" in out["results"][0]["passage"]


def test_search_knowledge_base_falls_back_to_a_title_match_when_ranking_finds_nothing():
    settings = _settings()
    ctx = ToolContext.build(settings, get_pms(settings), today="2026-06-15")
    out = search_knowledge_base(ctx, {"query": "qwzxjklm zyxxvubn"})
    assert out["fallback"] is True
    assert out["count"] == 0  # no document titled anything like that either


def test_run_forecast_clamps_days_to_the_configured_maximum():
    # Built from the fixtures path explicitly (financial_connected=True,
    # financial_rows loaded straight from tools/data.py) rather than via
    # ToolContext.build - that constructor now reflects whether a real
    # data/imports/financial_daily.csv exists, which it does not on a test
    # machine. The fixture route itself stays fully valid to exercise; only
    # a *silent* fallback inside a real (non-demo, non-test) context is the
    # bug `financial_connected` fixes - see test_run_forecast_says_not_connected
    # below for that case.
    settings = _settings()
    ctx = ToolContext(settings=settings, pms=get_pms(settings), today="2026-06-15",
                      financial_rows=pa_data.load_financial_daily(settings),
                      financial_connected=True)
    out = run_forecast(ctx, {"metric": "revenue", "days": 9000})
    assert out["connected"] is True
    assert out["days"] == 90  # forecast.max_days in config/agent.example.yaml
    assert len(out["points"]) == 90


def test_get_financial_summary_says_not_connected_instead_of_blending_fixture_rows():
    # Same truthfulness principle as guest_emails/agents_fleet above: a
    # property with no data/imports/financial_daily.csv must be told the
    # ledger is not connected, never handed Hotel Aurora's numbers as if
    # they were its own.
    settings = _settings()
    ctx = ToolContext(settings=settings, pms=get_pms(settings), today="2026-06-01",
                      financial_rows=_synthetic_rows(), financial_connected=False)
    out = get_financial_summary(ctx, {})
    assert out["connected"] is False
    assert "not connected" in out["message"].lower()
    assert "today" not in out  # no fixture-derived numbers leak into a real answer


def test_run_forecast_says_not_connected_instead_of_blending_fixture_rows():
    settings = _settings()
    ctx = ToolContext(settings=settings, pms=get_pms(settings), today="2026-06-15",
                      financial_rows=_synthetic_rows(), financial_connected=False)
    out = run_forecast(ctx, {"metric": "revenue", "days": 30})
    assert out["connected"] is False
    assert "not connected" in out["message"].lower()
    assert "points" not in out


def test_list_pending_emails_says_not_connected_instead_of_blending_fixture_rows():
    # Finding #3 (MAJOR): a hotel that has not dropped data/imports/guest_emails.csv
    # yet must never see a *different, invented* hotel's guest mail presented as
    # its own. `rows` here stands in for what tools/data.py's fixture fallback
    # would have loaded - the tool must ignore it outright when disconnected,
    # not just add a caveat next to it.
    settings = _settings()
    phantom_rows = [{"id": "e1", "from_name": "Priya Nair", "status": "pending_review",
                     "received_at": "2026-06-15T08:00:00Z"}]
    ctx = ToolContext(settings=settings, pms=get_pms(settings), today="2026-06-15",
                      guest_email_rows=phantom_rows, guest_emails_connected=False)
    out = list_pending_emails(ctx, {})
    assert out["connected"] is False
    assert "rows" not in out or out.get("rows") == []
    assert "not connected" in out["message"].lower()
    assert "Priya Nair" not in str(out)


def test_list_pending_emails_uses_real_rows_when_connected():
    settings = _settings()
    real_rows = [{"id": "e1", "from_name": "Real Guest", "status": "pending_review",
                 "received_at": "2026-06-15T08:00:00Z"}]
    ctx = ToolContext(settings=settings, pms=get_pms(settings), today="2026-06-15",
                      guest_email_rows=real_rows, guest_emails_connected=True)
    out = list_pending_emails(ctx, {})
    assert out["connected"] is True
    assert out["count"] == 1
    assert out["rows"][0]["from_name"] == "Real Guest"


def test_get_agent_status_says_not_connected_instead_of_blending_fixture_rows():
    settings = _settings()
    phantom_rows = [{"slug": "phantom-agent", "name": "Phantom", "status": "active"}]
    ctx = ToolContext(settings=settings, pms=get_pms(settings), today="2026-06-15",
                      fleet_rows=phantom_rows, fleet_connected=False)
    out = get_agent_status(ctx, {})
    assert out["connected"] is False
    assert "rows" not in out or out.get("rows") == []
    assert "not connected" in out["message"].lower()
    assert "phantom-agent" not in str(out)


def test_toolcontext_build_detects_the_csv_files_presence(tmp_path, monkeypatch):
    # ToolContext.build (what the real tool loop uses) must derive
    # financial_connected/guest_emails_connected/fleet_connected from
    # whether the hotel's own CSV exists in data/imports/ - not from the
    # fixture fallback existing.
    monkeypatch.setattr(pa_data, "imports_dir", lambda: tmp_path)
    settings = _settings()
    ctx = ToolContext.build(settings, get_pms(settings), today="2026-06-15")
    assert ctx.financial_connected is False
    assert ctx.guest_emails_connected is False
    assert ctx.fleet_connected is False

    (tmp_path / "financial_daily.csv").write_text(
        "date,revenue_rooms,revenue_fnb,revenue_other,costs_total,occupancy_pct,adr,rooms_available\n",
        encoding="utf-8")
    (tmp_path / "guest_emails.csv").write_text("id,from_name,status,received_at\n",
                                                encoding="utf-8")
    (tmp_path / "agents_fleet.csv").write_text("slug,name,status\n", encoding="utf-8")
    ctx2 = ToolContext.build(settings, get_pms(settings), today="2026-06-15")
    assert ctx2.financial_connected is True
    assert ctx2.guest_emails_connected is True
    assert ctx2.fleet_connected is True


def test_generate_report_rejects_a_missing_markdown_body():
    try:
        generate_report(None, {"title": "Weekly"})
        assert False, "expected a ToolError"
    except ToolError:
        pass


def test_generate_report_rejects_a_chart_with_no_series():
    try:
        generate_report(None, {"title": "T", "markdown": "m", "chart": {"type": "bar", "series": []}})
        assert False, "expected a ToolError"
    except ToolError:
        pass
