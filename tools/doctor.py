#!/usr/bin/env python3
"""tools/doctor.py - is the Analyst configured and reachable right now?

    make doctor
    python3 tools/doctor.py

Runs the generic core.doctor checks (python, deps, config, .env, hotel
identity, mode, llm provider, every adapter, the store, knowledge) plus three
checks specific to this agent: the tool specs load, the financial ledger is
readable, and the prompt/schema files are present. Exits 0 when everything
passed, 1 when a FAIL line needs fixing. Never a traceback.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.doctor import Check, FAIL, PASS, WARN, print_table, run_checks  # noqa: E402


def check_tools(settings: Settings) -> Check:
    try:
        from tools.toolkit import TOOL_SPECS
    except Exception as exc:  # noqa: BLE001
        return Check("tools", FAIL, f"tools/toolkit.py failed to import: {exc}"[:160],
                     "Run `make test` to see the full traceback.")
    return Check("tools", PASS, f"{len(TOOL_SPECS)} tools: "
                 f"{', '.join(s['name'] for s in TOOL_SPECS)}")


def check_financial_data(settings: Settings) -> Check:
    try:
        from tools.data import load_financial_daily
        rows = load_financial_daily(settings)
    except Exception as exc:  # noqa: BLE001
        return Check("financial ledger", FAIL, f"could not load: {exc}"[:160],
                     "Check data/imports/financial_daily.csv, or restore "
                     "fixtures/hotel/financial_daily.json from git.")
    if not rows:
        return Check("financial ledger", WARN, "no rows found",
                     "get_financial_summary and run_forecast will answer with zeros "
                     "until data/imports/financial_daily.csv exists. See "
                     "docs/integrations.md.")
    return Check("financial ledger", PASS,
                 f"{len(rows)} day(s), {rows[0]['date']} to {rows[-1]['date']}")


def check_knowledge_base(settings: Settings) -> Check:
    try:
        from tools.data import knowledge_passages
        passages = knowledge_passages()
    except Exception as exc:  # noqa: BLE001
        return Check("knowledge search", FAIL, f"could not load passages: {exc}"[:160], "")
    if not passages:
        return Check("knowledge search", WARN, "no passages found",
                     "search_knowledge_base will always fall back to nothing. Fill in "
                     "knowledge/property.md and knowledge/faq.md.")
    return Check("knowledge search", PASS, f"{len(passages)} passage(s) indexed")


def check_prompt_files() -> Check:
    missing = [p for p in ("prompts/ask.md", "prompts/schemas/step.json")
              if not (REPO_ROOT / p).is_file()]
    if missing:
        return Check("prompts", FAIL, f"missing {', '.join(missing)}",
                     "These ship with the repo - restore them from git.")
    return Check("prompts", PASS, "ask.md + schemas/step.json present")


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        checks = run_checks(None) + [Check("config", FAIL, str(exc),
                                           "Fix config/hotel.yaml or config/agent.yaml.")]
        return print_table(checks, title="Portfolio Analyst AI - doctor")

    checks = run_checks(settings, extra=[check_tools, check_financial_data, check_knowledge_base])
    checks.append(check_prompt_files())
    return print_table(checks, title="Portfolio Analyst AI - doctor")


if __name__ == "__main__":
    raise SystemExit(main())
