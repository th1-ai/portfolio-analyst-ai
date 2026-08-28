# Workflow: shadow to live

Objective: decide, together with the hotel, whether to let the morning
digest actually export - and make the change safely if so.

This is the hotel's decision, never yours. Answering questions works exactly
the same in both modes (see `docs/how-it-works.md` "Modes") - the only thing
`mode: live` changes for this agent is whether the digest export runs.

## Checklist

- [ ] `make doctor` is clean (no `FAIL` lines). `warn` on `mode` is expected
      until you flip it.
- [ ] `config/hotel.yaml` has the real property name, currency and
      languages, and `knowledge/property.md` + `knowledge/faq.md` exist and
      are accurate (not the shipped Hotel Aurora examples).
- [ ] `data/imports/financial_daily.csv` exists, or the hotel has decided to
      run on the bundled demo figures for now (unusual, but not unsafe -
      `get_financial_summary` just answers with the invented Hotel Aurora
      numbers until a real export is connected).
- [ ] A few days of real `--question` asks, or a few `--digest` dry runs,
      have gone through and the hotel is happy with the answer quality and
      what escalates to `needs_human`.
- [ ] The hotel has decided who receives the digest export
      (`data/exports/digest_reports.csv`, or a shared Google Sheet if
      `systems.sheets.adapter: google` is configured).

## Making the change

1. Edit `config/hotel.yaml`:
   ```yaml
   mode: live
   ```
2. `review.require_approval_for` does not list `sheets_write` by default -
   the digest export runs straight through once live, without a per-day
   approval step. Add `sheets_write` to that list first if the hotel wants
   a person to approve each morning's digest before it lands on disk.
3. Run `make doctor` again to confirm.
4. Run one digest pass by hand and check the export:
   ```bash
   make run ARGS="--digest"
   cat data/exports/digest_reports.csv
   ```
5. Tell the hotel exactly what just changed: from now on, the scheduled
   digest (`workflows/16-digest.md`) writes its answers to
   `data/exports/digest_reports.csv` (or the configured Google Sheet)
   automatically. Nothing about how a question is answered is different -
   there is still no tool anywhere in this agent that can change a rate, a
   booking, or a setting (see `docs/safety.md`).

## Going back to shadow

```yaml
mode: shadow
```
in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env` for one run.
Either stops the digest export on the next pass, mid-schedule, with no
other change - questions keep answering exactly as before.
