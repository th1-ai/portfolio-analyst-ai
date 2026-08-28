"""tools/toolkit.py - the seven tools the Analyst can call, and nothing else.

Deterministic decisioning, LLM for language (ARCHITECTURE.md section 1): every
number below is plain Python over the property's own data. The model never
computes a total, a percentage or a forecast itself - it only decides which of
these to call and then writes the answer up in words. This is also the whole
of the read-only guarantee: there is no eighth tool that writes anything, so
"it doesn't change rates or settings" (the roster's own words) is enforced by
what exists here, not by a prompt instruction.

Every tool takes a :class:`ToolContext` and a plain dict of arguments, and
returns a plain dict (JSON-safe) or raises - `tools/tool_loop.py` catches the
raise and feeds `{"error": ...}` back to the model rather than failing the
whole question, exactly like the source system this was ported from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from core.adapters.base import PMS
from core.config import Settings

from tools import data as pa_data

WINDOWS = ("today_arrivals", "today_departures", "in_house", "upcoming_7d",
           "upcoming_30d", "recent_7d")
FORECAST_METRICS = ("revenue", "occupancy")


class ToolError(ValueError):
    """A tool call had bad arguments or nothing to answer with."""


@dataclass
class ToolContext:
    """Everything a tool needs, loaded once per question (not once per call).

    ``financial_connected``/``guest_emails_connected``/``fleet_connected``
    default to ``True`` - a `ToolContext` built by hand (every test in
    `tests/test_pa_toolkit.py` that passes ``financial_rows=``/
    ``guest_email_rows=``/``fleet_rows=`` directly, say) is trusted to mean
    what it says. Only `ToolContext.build` - the constructor the real tool
    loop actually uses - sets them from whether the hotel has dropped its
    own CSV in `data/imports/`, so only real runs can ever see them come
    back ``False``. `make demo` is unaffected (see
    `tools/data.py:financial_connected`'s docstring) and stays on the
    fixture route deliberately - it is not "a real context with a silent
    fallback", it is the documented sample-data path.
    """

    settings: Settings
    pms: PMS
    today: str
    financial_rows: list[dict] = field(default_factory=list)
    guest_email_rows: list[dict] = field(default_factory=list)
    fleet_rows: list[dict] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)
    financial_connected: bool = True
    guest_emails_connected: bool = True
    fleet_connected: bool = True

    @classmethod
    def build(cls, settings: Settings, pms: PMS, *, today: str | None = None) -> "ToolContext":
        resolved = pa_data.today_iso(settings, today)
        return cls(settings=settings, pms=pms, today=resolved,
                   financial_rows=pa_data.load_financial_daily(settings),
                   guest_email_rows=pa_data.load_guest_emails(settings),
                   fleet_rows=pa_data.load_agents_fleet(settings),
                   passages=pa_data.knowledge_passages(),
                   financial_connected=pa_data.financial_connected(),
                   guest_emails_connected=pa_data.guest_emails_connected(),
                   fleet_connected=pa_data.agents_fleet_connected())


# --------------------------------------------------------------------------
# tool specs - fed into the system prompt (prompts/ask.md's {{tool_list}}) and
# used to validate arguments before a tool ever runs.
# --------------------------------------------------------------------------
TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "get_financial_summary",
     "description": "Today / week-to-date / month-to-date / year-to-date revenue, "
                     "costs, profit, occupancy, ADR and RevPAR, each compared to the "
                     "same period last year. No arguments.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_reservations",
     "description": "Up to 25 reservations for one window: ref, guest, room type, "
                     "dates, pax, channel, status, total, vip, notes.",
     "parameters": {"type": "object",
                    "properties": {"window": {"type": "string", "enum": list(WINDOWS)}},
                    "required": ["window"], "additionalProperties": False}},
    {"name": "list_pending_emails",
     "description": "Up to 25 guest emails waiting on a person, newest first. "
                     "Default status filter: pending_review, escalated.",
     "parameters": {"type": "object",
                    "properties": {"status": {"type": ["string", "null"]}},
                    "additionalProperties": False}},
    {"name": "get_agent_status",
     "description": "Status of one AI agent (by slug) or the whole fleet at this "
                     "property: runs today, runs last 30 days, success rate.",
     "parameters": {"type": "object",
                    "properties": {"slug": {"type": ["string", "null"]}},
                    "additionalProperties": False}},
    {"name": "search_knowledge_base",
     "description": "Ranked full-text search over the property knowledge base "
                     "(policies, rooms, spa, FAQ). Always use this for a property "
                     "fact instead of guessing.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"], "additionalProperties": False}},
    {"name": "run_forecast",
     "description": "Project revenue or occupancy forward, scaling same-day-last-year "
                     "by the trailing year-over-year ratio.",
     "parameters": {"type": "object",
                    "properties": {"metric": {"type": "string", "enum": list(FORECAST_METRICS)},
                                   "days": {"type": "integer", "minimum": 1, "maximum": 90}},
                    "required": ["metric", "days"], "additionalProperties": False}},
    {"name": "generate_report",
     "description": "Emit a structured report card: title, markdown body, optional "
                     "KPI tiles and a bar/line chart. Call this whenever asked for a "
                     "report, briefing or chart.",
     "parameters": {"type": "object",
                    "properties": {
                        "title": {"type": "string"}, "subtitle": {"type": ["string", "null"]},
                        "markdown": {"type": "string"},
                        "kpis": {"type": "array", "items": {"type": "object"}},
                        "chart": {"type": ["object", "null"]},
                    },
                    "required": ["title", "markdown"], "additionalProperties": False}},
]

TOOL_NAMES = tuple(spec["name"] for spec in TOOL_SPECS)


def render_tool_list() -> str:
    """The markdown bullet list embedded in prompts/ask.md via {{tool_list}}."""
    lines = ["Tools you may call:"]
    for spec in TOOL_SPECS:
        lines.append(f"- `{spec['name']}` - {spec['description']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# small maths shared by the summary and forecast tools
# --------------------------------------------------------------------------
def _pct_change(current: float, previous: float) -> str:
    if not previous:
        return "n/a"
    change = (current - previous) / previous * 100.0
    return f"{'+' if change >= 0 else ''}{change:.1f}%"


def _sum(rows: list[dict], field_name: str) -> float:
    return round(sum(r.get(field_name, 0.0) for r in rows), 2)


def _mean(rows: list[dict], field_name: str) -> float:
    if not rows:
        return 0.0
    return round(sum(r.get(field_name, 0.0) for r in rows) / len(rows), 2)


def _mean_revpar(rows: list[dict]) -> float:
    """Mean of each day's own revenue_rooms / rooms_available - a simple daily
    average, same style as occupancy_avg_pct and adr_avg above it."""
    values = [r["revenue_rooms"] / r["rooms_available"] for r in rows if r.get("rooms_available")]
    return round(sum(values) / len(values), 2) if values else 0.0


def _not_connected(csv_name: str, what: str) -> dict:
    """The shared shape every disconnected-source tool returns instead of the
    bundled fixture rows - never both. See `ToolContext.__doc__` and
    docs/integrations.md: a source with no real CSV yet has no fixture
    fallback at this boundary, on purpose, so the model can never echo
    invented data (a different hotel's guest names, say) as this property's
    own. ``message`` is written to be read and repeated back verbatim in the
    final answer - prompts/ask.md's DATA TRUTHFULNESS rule tells the model to
    do exactly that whenever a tool result says ``"connected": false``."""
    return {"connected": False,
           "message": f"{what} is not connected yet ({csv_name} was not found in "
                      f"data/imports/) - say so plainly instead of guessing or using "
                      f"sample data. See docs/integrations.md."}


# --------------------------------------------------------------------------
# 1. get_financial_summary
# --------------------------------------------------------------------------
def get_financial_summary(ctx: ToolContext, args: dict) -> dict:
    if not ctx.financial_connected:
        return _not_connected("data/imports/financial_daily.csv", "The financial ledger")
    today = ctx.today
    rows = ctx.financial_rows
    by_date = {r["date"]: r for r in rows}

    def period(start: str, end: str) -> list[dict]:
        return pa_data.financial_window(rows, start, end)

    def ly(start: str, end: str) -> list[dict]:
        return period(pa_data.same_day_last_year(start), pa_data.same_day_last_year(end))

    wtd_start = pa_data.week_start(today)
    mtd_start = pa_data.month_start(today)
    ytd_start = pa_data.year_start(today)

    today_row = by_date.get(today, {})
    today_ly_row = by_date.get(pa_data.same_day_last_year(today), {})
    wtd_rows, mtd_rows, ytd_rows = period(wtd_start, today), period(mtd_start, today), period(ytd_start, today)

    return {
        "connected": True,
        "as_of": today,
        "today": {
            "revenue": today_row.get("revenue_total", 0.0),
            "occupancy_pct": today_row.get("occupancy_pct", 0.0),
            "vs_last_year_revenue": _pct_change(today_row.get("revenue_total", 0.0),
                                                today_ly_row.get("revenue_total", 0.0)),
        },
        "wtd": {"revenue": _sum(wtd_rows, "revenue_total")},
        "mtd": {
            "revenue_total": _sum(mtd_rows, "revenue_total"),
            "revenue_rooms": _sum(mtd_rows, "revenue_rooms"),
            "revenue_fnb": _sum(mtd_rows, "revenue_fnb"),
            "revenue_other": _sum(mtd_rows, "revenue_other"),
            "costs_total": _sum(mtd_rows, "costs_total"),
            "profit": _sum(mtd_rows, "profit"),
            "occupancy_avg_pct": _mean(mtd_rows, "occupancy_pct"),
            "adr_avg": _mean(mtd_rows, "adr"),
            "revpar_avg": _mean_revpar(mtd_rows),
            "vs_last_year_revenue": _pct_change(_sum(mtd_rows, "revenue_total"),
                                                _sum(ly(mtd_start, today), "revenue_total")),
        },
        "ytd": {
            "revenue": _sum(ytd_rows, "revenue_total"),
            "profit": _sum(ytd_rows, "profit"),
            "vs_last_year_revenue": _pct_change(_sum(ytd_rows, "revenue_total"),
                                                _sum(ly(ytd_start, today), "revenue_total")),
        },
    }


# --------------------------------------------------------------------------
# 2. list_reservations
# --------------------------------------------------------------------------
def _reservation_row(res: Any) -> dict:
    return {
        "ref": res.external_ref or res.id, "guest": res.guest.full_name or "(no name)",
        "room_type": res.room_type_name or res.room_type_id, "check_in": res.check_in,
        "check_out": res.check_out, "pax": res.adults + res.children,
        "channel": res.source, "status": res.status, "total": res.total,
        "currency": res.currency, "vip": bool(res.guest.vip), "notes": res.notes,
    }


def list_reservations(ctx: ToolContext, args: dict) -> dict:
    window = args.get("window")
    if window not in WINDOWS:
        raise ToolError(f"window must be one of {', '.join(WINDOWS)}, got {window!r}")
    max_rows = int(ctx.settings.agent_get("reservations.max_rows", 25))
    today = ctx.today

    if window == "today_arrivals":
        rows, sort_key = ctx.pms.list_arrivals(today), "check_in"
    elif window == "today_departures":
        rows, sort_key = ctx.pms.list_departures(today), "check_out"
    elif window == "in_house":
        rows, sort_key = ctx.pms.list_in_house(today), "check_in"
    elif window == "upcoming_7d":
        rows, sort_key = ctx.pms.list_reservations(today, pa_data.add_days(today, 7)), "check_in"
    elif window == "upcoming_30d":
        rows, sort_key = ctx.pms.list_reservations(today, pa_data.add_days(today, 30)), "check_in"
    else:  # recent_7d
        rows, sort_key = ctx.pms.list_reservations(pa_data.add_days(today, -7), today), "check_out"

    rows = sorted(rows, key=lambda r: (getattr(r, sort_key), r.id))
    total = len(rows)
    out = [_reservation_row(r) for r in rows[:max_rows]]
    return {"window": window, "count": total, "returned": len(out),
           "truncated": total > max_rows, "rows": out}


# --------------------------------------------------------------------------
# 3. list_pending_emails
# --------------------------------------------------------------------------
def list_pending_emails(ctx: ToolContext, args: dict) -> dict:
    if not ctx.guest_emails_connected:
        return _not_connected("data/imports/guest_emails.csv", "The guest email snapshot")
    status = args.get("status")
    statuses = [status] if status else ["pending_review", "escalated"]
    rows = [r for r in ctx.guest_email_rows if r.get("status") in statuses]
    rows.sort(key=lambda r: r.get("received_at", ""), reverse=True)
    max_rows = 25
    out = rows[:max_rows]
    return {"connected": True, "filter_status": statuses, "count": len(rows), "returned": len(out),
           "truncated": len(rows) > max_rows, "rows": out}


# --------------------------------------------------------------------------
# 4. get_agent_status
# --------------------------------------------------------------------------
def get_agent_status(ctx: ToolContext, args: dict) -> dict:
    if not ctx.fleet_connected:
        return _not_connected("data/imports/agents_fleet.csv", "The agent fleet snapshot")
    slug = args.get("slug")
    rows = ctx.fleet_rows
    if slug:
        rows = [r for r in rows if r.get("slug") == slug]
        if not rows:
            return {"connected": True, "slug": slug, "found": False, "rows": []}
    return {"connected": True, "slug": slug, "found": bool(rows) if slug else None,
           "count": len(rows), "rows": rows}


# --------------------------------------------------------------------------
# 5. search_knowledge_base
# --------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"a", "an", "the", "is", "are", "was", "were", "of", "to", "in",
             "on", "for", "and", "or", "it", "we", "our", "you", "your",
             "do", "does", "not", "no", "at", "by", "with", "what", "how"}


def _tokens(text: str) -> set[str]:
    """Words worth matching on: lowercased, at least 2 characters, with the
    commonest English stopwords dropped so a query like "what's our policy"
    ranks on "policy", not on "what" and "our" matching almost everything."""
    return {t for t in _WORD.findall(text.lower()) if len(t) >= 2 and t not in _STOPWORDS}


def _score(passage: dict, query_tokens: set[str]) -> float:
    haystack = _tokens(f"{passage['title']} {passage['section']} {passage['passage']}")
    if not query_tokens:
        return 0.0
    return len(query_tokens & haystack) / len(query_tokens)


def search_knowledge_base(ctx: ToolContext, args: dict) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolError("query must not be empty")
    top_k = int(ctx.settings.agent_get("knowledge_search.top_k", 8))
    query_tokens = _tokens(query)
    ranked = sorted(
        ((p, _score(p, query_tokens)) for p in ctx.passages),
        key=lambda pair: pair[1], reverse=True)
    hits = [{"doc_key": p["doc_key"], "title": p["title"], "category": p["category"],
            "section": p["section"], "passage": p["passage"], "relevance": round(s, 3)}
           for p, s in ranked if s > 0][:top_k]
    if hits:
        return {"query": query, "fallback": False, "count": len(hits), "results": hits}

    # FTS-equivalent found nothing: fall back to a title substring match, the
    # same two-step behaviour as the source system (see docs/how-it-works.md).
    needle = query.lower()
    loose = [{"doc_key": p["doc_key"], "title": p["title"], "category": p["category"],
             "section": p["section"], "passage": p["passage"], "relevance": 0.0}
            for p in ctx.passages if needle in p["title"].lower()][:4]
    return {"query": query, "fallback": True, "count": len(loose), "results": loose}


# --------------------------------------------------------------------------
# 6. run_forecast
# --------------------------------------------------------------------------
def _metric_value(row: dict, metric: str) -> float:
    return row.get("revenue_total", 0.0) if metric == "revenue" else row.get("occupancy_pct", 0.0)


def run_forecast(ctx: ToolContext, args: dict) -> dict:
    metric = args.get("metric")
    if metric not in FORECAST_METRICS:
        raise ToolError(f"metric must be one of {', '.join(FORECAST_METRICS)}, got {metric!r}")
    if not ctx.financial_connected:
        return _not_connected("data/imports/financial_daily.csv", "The financial ledger")
    days = max(1, min(int(args.get("days", 30)),
                      int(ctx.settings.agent_get("forecast.max_days", 90))))
    trailing = int(ctx.settings.agent_get("forecast.trailing_days", 28))
    by_date = {r["date"]: r for r in ctx.financial_rows}
    today = ctx.today

    trailing_dates = pa_data.days_between(pa_data.add_days(today, -trailing + 1), today)
    actual = sum(_metric_value(by_date[d], metric) for d in trailing_dates if d in by_date)
    ly_trailing = sum(_metric_value(by_date[pa_data.same_day_last_year(d)], metric)
                      for d in trailing_dates if pa_data.same_day_last_year(d) in by_date)
    yoy = (actual / ly_trailing) if ly_trailing else 1.0

    forecast_dates = pa_data.days_between(pa_data.add_days(today, 1), pa_data.add_days(today, days))
    points = []
    for d in forecast_dates:
        ly_date = pa_data.same_day_last_year(d)
        ly_value = _metric_value(by_date[ly_date], metric) if ly_date in by_date else 0.0
        points.append({"date": d, "projected": round(ly_value * yoy, 2), "last_year": ly_value})

    total_projected = round(sum(p["projected"] for p in points), 2)
    total_last_year = round(sum(p["last_year"] for p in points), 2)
    return {"connected": True, "metric": metric, "days": days, "yoy_ratio": round(yoy, 3),
           "total_projected": total_projected, "total_last_year": total_last_year,
           "vs_last_year": _pct_change(total_projected, total_last_year), "points": points}


# --------------------------------------------------------------------------
# 7. generate_report
# --------------------------------------------------------------------------
def generate_report(ctx: ToolContext, args: dict) -> dict:
    title, markdown = args.get("title"), args.get("markdown")
    if not title or not markdown:
        raise ToolError("generate_report needs both 'title' and 'markdown'")
    report = {"title": title, "subtitle": args.get("subtitle") or "", "markdown": markdown,
             "kpis": args.get("kpis") or [], "chart": args.get("chart")}
    chart = report["chart"]
    if chart is not None:
        if chart.get("type") not in ("bar", "line"):
            raise ToolError("chart.type must be 'bar' or 'line'")
        if not chart.get("series"):
            raise ToolError("chart.series must not be empty")
    return report


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------
TOOL_FUNCS: dict[str, Callable[[ToolContext, dict], dict]] = {
    "get_financial_summary": get_financial_summary,
    "list_reservations": list_reservations,
    "list_pending_emails": list_pending_emails,
    "get_agent_status": get_agent_status,
    "search_knowledge_base": search_knowledge_base,
    "run_forecast": run_forecast,
    "generate_report": generate_report,
}


def call_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    """Run one tool by name. Raises :class:`ToolError` for a bad name/args;
    the tool functions themselves may also raise - `tool_loop.py` catches
    both and turns them into ``{"error": ...}`` in the transcript."""
    func = TOOL_FUNCS.get(name)
    if func is None:
        raise ToolError(f"no such tool '{name}'. Known: {', '.join(TOOL_NAMES)}")
    if not isinstance(args, dict):
        raise ToolError(f"{name}: arguments must be a JSON object, got {type(args).__name__}")
    return func(ctx, args)
