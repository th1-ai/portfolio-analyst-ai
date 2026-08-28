"""tools/data.py - loaders and date maths shared by every tool in toolkit.py.

Portfolio Analyst AI has no PMS-write, POS or accounting adapter of its own
(see docs/integrations.md) - `core.adapters` has no daily-ledger or
knowledge-passage interface, so this module reads the property's own data the
same way `core.adapters.pms_csv` does: a CSV export in `data/imports/` if the
hotel has dropped one there, falling back to the bundled fixture otherwise.
Nothing here calls a model or writes anything - it is plain, testable Python.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.config import Settings, repo_root

def fixtures_hotel_dir() -> Path:
    """``<repo>/fixtures/hotel`` - computed fresh, not cached, so tests can
    override it via ``AGENT_REPO_ROOT`` (see core/config.py:repo_root)."""
    return repo_root() / "fixtures" / "hotel"


def imports_dir() -> Path:
    """``<repo>/data/imports`` - where a hotel drops its own CSV exports."""
    return repo_root() / "data" / "imports"


# --------------------------------------------------------------------------
# date maths - every tool that needs "today" takes an override so it is
# testable without depending on the wall clock (see tests/test_pa_dates.py).
# --------------------------------------------------------------------------
def today_iso(settings: Settings | None = None, override: str | None = None) -> str:
    """Today's date as ``YYYY-MM-DD``. ``override`` wins (tests, --as-of)."""
    if override:
        return override
    return date.today().isoformat()


def week_start(day: str) -> str:
    """Monday of the week containing ``day`` (ISO). Matches the demo's own
    ``(weekday + 6) % 7`` rule: weeks start Monday, not Sunday."""
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def month_start(day: str) -> str:
    return day[:8] + "01"


def year_start(day: str) -> str:
    return day[:4] + "-01-01"


def same_day_last_year(day: str) -> str:
    """``day`` shifted back exactly 365 days (not calendar-aware on purpose -
    it is a fixed offset, same as the source system, so a Monday compares to
    a Monday roughly as often as a calendar year-back would)."""
    d = date.fromisoformat(day)
    return (d - timedelta(days=365)).isoformat()


def days_between(start: str, end_inclusive: str) -> list[str]:
    """Every ISO date from ``start`` to ``end_inclusive``, inclusive."""
    s, e = date.fromisoformat(start), date.fromisoformat(end_inclusive)
    n = (e - s).days
    return [(s + timedelta(days=i)).isoformat() for i in range(n + 1)]


def add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


# --------------------------------------------------------------------------
# financial ledger - CSV export (real use) or the bundled fixture (demo)
# --------------------------------------------------------------------------
_FIN_FIELDS = ("date", "revenue_rooms", "revenue_fnb", "revenue_other",
               "costs_total", "occupancy_pct", "adr", "rooms_available")


def _fin_row(raw: dict) -> dict:
    out = {"date": str(raw.get("date", ""))}
    for key in _FIN_FIELDS[1:]:
        try:
            out[key] = float(raw.get(key, 0) or 0)
        except (TypeError, ValueError):
            out[key] = 0.0
    out["revenue_total"] = out["revenue_rooms"] + out["revenue_fnb"] + out["revenue_other"]
    out["profit"] = out["revenue_total"] - out["costs_total"]
    return out


def load_financial_daily(settings: Settings | None = None) -> list[dict]:
    """Every day of the ledger, oldest first. Rows are plain dicts, already
    typed to float, with ``revenue_total`` and ``profit`` computed.

    Real use: drop your own export at ``data/imports/financial_daily.csv``
    with these columns (extra columns are ignored): date, revenue_rooms,
    revenue_fnb, revenue_other, costs_total, occupancy_pct, adr,
    rooms_available. Demo/tests: ``fixtures/hotel/financial_daily.json``.
    """
    csv_path = imports_dir() / "financial_daily.csv"
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            rows = [_fin_row(r) for r in csv.DictReader(fh)]
    else:
        path = fixtures_hotel_dir() / "financial_daily.json"
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        rows = [_fin_row(r) for r in raw]
    rows.sort(key=lambda r: r["date"])
    return rows


def financial_connected() -> bool:
    """True once the hotel has dropped its own ``data/imports/financial_daily.csv``.

    ``load_financial_daily`` above always returns *something* - the bundled
    Hotel Aurora fixture when the real CSV is absent - because `make demo`
    and the tests need real arithmetic to run on. That fallback must never
    reach a REAL answer unlabelled: `tools/toolkit.py`'s
    `get_financial_summary`/`run_forecast` check this flag and say so
    plainly instead of quietly presenting Hotel Aurora's numbers as this
    property's own (docs/integrations.md; the same truthfulness principle as
    `guest_emails_connected`/`agents_fleet_connected` below). `make demo`
    is unaffected: it runs on `provider=mock`, whose canned final answer for
    each bundled question is read verbatim from
    `fixtures/expected/ask/*.json` regardless of what a tool actually
    returns - see `core/llm.py:_mock` and `tools/tool_loop.py`'s module
    docstring."""
    return (imports_dir() / "financial_daily.csv").exists()


def financial_window(rows: list[dict], start: str, end_inclusive: str) -> list[dict]:
    return [r for r in rows if start <= r["date"] <= end_inclusive]


# --------------------------------------------------------------------------
# guest email snapshot - front desk's own inbox status, read-only here
# --------------------------------------------------------------------------
def load_guest_emails(settings: Settings | None = None) -> list[dict]:
    """A snapshot of the front-desk inbox: ``id, from_name, subject,
    classification, confidence, status, summary, received_at``.

    Design decision (docs/how-it-works.md): a real portfolio could query a
    guest-comms agent's own database directly; this standalone template
    reads a CSV/JSON snapshot instead, so this repo has no hidden dependency
    on another repo. Real use: ``data/imports/guest_emails.csv``.
    """
    csv_path = imports_dir() / "guest_emails.csv"
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    path = fixtures_hotel_dir() / "guest_emails.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def guest_emails_connected() -> bool:
    """True once ``data/imports/guest_emails.csv`` exists. See
    ``financial_connected`` above for why this matters: without this check
    ``list_pending_emails`` would otherwise hand the model the bundled Hotel
    Aurora fixture (Priya Nair and friends) with nothing marking it as not
    this property's real inbox."""
    return (imports_dir() / "guest_emails.csv").exists()


# --------------------------------------------------------------------------
# agent fleet snapshot - other TH1 agents running at this property, if any
# --------------------------------------------------------------------------
def load_agents_fleet(settings: Settings | None = None) -> list[dict]:
    """``slug, name, nickname, status, runs_today, runs_30d, success_rate,
    last_run_at`` for every other agent at this property, if you run more
    than one. Real use: ``data/imports/agents_fleet.csv``, hand-maintained
    or exported from wherever you track it."""
    csv_path = imports_dir() / "agents_fleet.csv"
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    path = fixtures_hotel_dir() / "agents_fleet.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def agents_fleet_connected() -> bool:
    """True once ``data/imports/agents_fleet.csv`` exists. See
    ``financial_connected`` above."""
    return (imports_dir() / "agents_fleet.csv").exists()


# --------------------------------------------------------------------------
# knowledge passages - for tools/toolkit.py:search_knowledge_base
# --------------------------------------------------------------------------
def knowledge_documents() -> list[dict]:
    """Every knowledge document available right now: ``{doc_key, title,
    category, text}``.

    ``fixtures/hotel/*.md`` (the invented Hotel Aurora) always contributes,
    so `make demo` and the tests always have real content to search even on
    a fresh clone. Once a hotel copies ``knowledge/property.example.md`` to
    ``knowledge/property.md`` and fills it in, the real file wins over the
    fixture of the same name - see docs/how-it-works.md.
    """
    by_name: dict[str, Path] = {}
    if fixtures_hotel_dir().is_dir():
        for path in sorted(fixtures_hotel_dir().glob("*.md")):
            by_name[path.name] = path
    kdir = repo_root() / "knowledge"
    if kdir.is_dir():
        real = [p for p in sorted(kdir.glob("*.md"))
                if p.name != "README.md" and ".example." not in p.name]
        examples = [p for p in sorted(kdir.glob("*.example.md"))]
        for path in real or examples:
            name = path.name.replace(".example.md", ".md")
            by_name[name] = path
    docs = []
    for name, path in sorted(by_name.items()):
        text = path.read_text(encoding="utf-8")
        title = _first_heading(text) or name
        docs.append({"doc_key": name.removesuffix(".md"), "title": title,
                     "category": name.removesuffix(".md"), "path": str(path), "text": text})
    return docs


def _first_heading(text: str) -> str:
    m = re.match(r"^#\s+(.+)$", text.strip().splitlines()[0]) if text.strip() else None
    return m.group(1).strip() if m else ""


def knowledge_passages() -> list[dict]:
    """Every document split into ``## Section`` passages: ``{doc_key, title,
    category, section, passage}``. What ``search_knowledge_base`` ranks over.
    """
    out = []
    for doc in knowledge_documents():
        sections = re.split(r"^##\s+", doc["text"], flags=re.M)
        intro = sections[0].split("\n", 1)
        if len(intro) > 1 and intro[1].strip():
            out.append({"doc_key": doc["doc_key"], "title": doc["title"],
                       "category": doc["category"], "section": "Overview",
                       "passage": intro[1].strip()})
        for chunk in sections[1:]:
            lines = chunk.split("\n", 1)
            heading = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            if body:
                out.append({"doc_key": doc["doc_key"], "title": doc["title"],
                           "category": doc["category"], "section": heading,
                           "passage": body})
    return out
