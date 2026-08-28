# Workflow: the morning digest

Objective: run the standing list of questions in `config/agent.yaml:
digest.questions` and export the answers, so an owner has a briefing waiting
without asking for it.

Ported from the source system's scheduled-reports job - see
`specs/portfolio-analyst-ai.md` and `docs/how-it-works.md`.

## Inputs

- `config/agent.yaml: digest.questions` - the standing list. Edit it to
  whatever your own managers actually want to see first thing; the shipped
  default is six questions covering financial performance, arrivals,
  departures, guest emails needing attention, a 30-day forecast, and a
  weekly KPI report.
- `mode` in `config/hotel.yaml` - the export only runs in `live` (see
  `docs/safety.md`).

## Steps

1. **Run it once by hand.**
   ```bash
   make run ARGS="--digest"
   ```
   This asks every question in `digest.questions`, in order, exactly the
   same way `workflows/10-ask.md` asks one - each becomes its own `items`
   row, so `make review` and `make report` see digest questions and ad-hoc
   ones side by side.

2. **In `mode: shadow` (the default), nothing is exported.** You will see
   the same per-question output as an ad-hoc run, and then a note that the
   export was blocked - this is the global kill switch working as intended,
   not a bug. Read the answers straight from the terminal or `make report`.

3. **In `mode: live`,** the six answers are appended as one row each to
   `data/exports/digest_reports.csv` (`date, question, status, answer`),
   through the Sheets adapter's guarded `sheets_write` action. Switch
   `systems.sheets.adapter` to `google` in `config/hotel.yaml` if you want
   this landing in a shared spreadsheet instead of a local file - see
   `docs/integrations.md`.

4. **Schedule it.**
   ```bash
   python3 tools/schedule.py --all
   ```
   prints the cron/launchd/systemd snippet for the `digest` job in
   `config/agent.yaml: schedule:`, with `tools/run.py --once --digest`
   already filled in as the command, and your own machine's absolute paths
   - paste it where the snippet's header says. `scheduler/crontab.example`
   and the other `scheduler/*.example` files already show this same job
   with a placeholder path (`/path/to/portfolio-analyst-ai`); `--all` saves
   you swapping that placeholder for the real one by hand.

5. **Keep it running without a system scheduler.**
   ```bash
   python3 tools/run.py --watch --digest
   ```
   loops on the interval in `config/agent.yaml: schedule.digest.cadence`
   (default every 24 hours) until you stop it. Fine for a laptop that stays
   on; a real cron/launchd/systemd job (step 4) survives a reboot.

## Edge cases

- **Running the digest twice the same day.** Each question's id is
  `digest-<date>-<index>`, stable for the day, so a second run the same day
  answers the same six ids again - the earlier ones already left `new`
  (see `docs/how-it-works.md` "Idempotency"), so the second run is a no-op
  per question and the export step still runs (it does not check whether
  today's rows already exist - a repeated manual run adds a repeated row,
  which is fine for an audit trail).
- **`digest.questions` is empty.** The run prints a warning to
  `data/logs/*.jsonl` and does nothing else - not an error, just nothing to
  do.
- **The export fails** (a full disk, a bad Google Sheets credential). The
  digest's own questions are still answered and logged; only the export
  step is affected, and it fails loud rather than silently.
