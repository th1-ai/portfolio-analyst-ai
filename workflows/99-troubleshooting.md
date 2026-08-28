# Workflow: troubleshooting

Read the whole error before doing anything - every tool here is written to
say what broke and what to do about it. If you fix something not covered
below, add it here.

## `make doctor` shows a FAIL

Each `FAIL` line has a `->` fix hint right under it. Common ones:

- **`hotel identity`: name is still 'Hotel Aurora'.** Expected on a fresh
  clone. Edit `config/hotel.yaml`.
- **`financial ledger`: could not load.** Check
  `data/imports/financial_daily.csv`'s columns match
  `docs/integrations.md`, or restore `fixtures/hotel/financial_daily.json`
  from git if you deleted it.
- **`llm provider`: claude-code selected but `claude` is not on PATH.**
  Install Claude Code, or switch `llm.provider` to `interactive` or
  `anthropic` in `config/hotel.yaml`.
- **`llm provider`: ANTHROPIC_API_KEY is not set.** Add it to `.env`, or
  switch `llm.provider` to `claude-code` or `interactive`.
- **The email or messaging adapter lines.** These show green because the
  shared `make doctor` check covers all four adapter families - this agent
  does not actually use either one. See `docs/integrations.md`.

## `make demo` does not print `DEMO OK`

- Make sure `make setup` ran first (`.venv` must exist).
- `tools/demo.py` forces `llm.provider=mock` and reads
  `fixtures/inbound/question-*.json` plus the matching round fixtures in
  `fixtures/expected/ask/` - if you deleted or renamed those files, restore
  them from git.
- Read the traceback if there is one; `tools/demo.py` does not swallow
  errors on purpose, so a fixture problem shows up immediately.

## `make run` exits with code 3 (or code 2 - read the line above it)

Not an error either way. `llm.provider: interactive` parked a prompt. Read
`data/pending/*.prompt.md`, write your answer to the matching
`*.answer.json` (JSON only, matching the schema shown, no prose, no code
fence), and run the exact same command again - same question, same
`--as-of` if you used one. It resumes the same question at the round you
just answered; it does not start over (see `tools/tool_loop.py`'s round
cache and `workflows/10-ask.md` step 2). This may take several rounds for
one question - one per tool call, plus the final answer.

The exit code itself depends on how you ran it. `python3 tools/run.py --once
--question "..."` exits 3 directly - `echo $?` after it shows `3`. Through
`make run ARGS='...'`, `make` wraps that: GNU Make reports its own generic
failure code, `2`, and separately prints the real one, e.g. `make: ***
[run] Error 3`. Read the `3` in that printed line, not `$?` after `make`.

## A question always escalates to `needs_human`

- Check `python3 tools/review.py show <id>` - `payload._last_attempt` shows
  exactly which tools were tried and what came back. If
  `search_knowledge_base` keeps returning nothing, the fact probably is not
  in `knowledge/` yet - add it. If `get_financial_summary`/`run_forecast`
  look empty, check `data/imports/financial_daily.csv` is present and dated
  correctly.
- If the question is genuinely outside what this agent connects to
  (marketing spend, a competitor's numbers), that is the agent working
  correctly - see `docs/safety.md`.

## The digest export never appears

- `mode` must be `live` - see `workflows/90-go-live.md`. In `shadow` the
  questions still answer, the export just never writes.
- Check `systems.sheets.adapter` and, for `google`, that
  `GOOGLE_SERVICE_ACCOUNT_FILE` and `GOOGLE_SHEET_ID` are set and the
  service account has Editor access to the sheet.

## `python3 tools/*.py` says `ModuleNotFoundError: No module named 'core'`

You ran it with a Python that is not the repo's virtualenv, or from outside
the repo root. Use `make run` / `make doctor` / etc. (they call
`.venv/bin/python` for you), or run `.venv/bin/python tools/run.py`
directly from the repo root.

## Still stuck

`data/logs/*.jsonl` has every decision the agent made, in order, with a run
id. `python3 tools/review.py show <id>` has the full event trail for one
question. If neither explains it, that is a real bug - describe exactly
what you ran and what you expected, and ask.
