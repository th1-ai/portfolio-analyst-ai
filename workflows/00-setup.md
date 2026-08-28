# Workflow: first-run setup

Objective: get Portfolio Analyst AI from a fresh clone to a working demo,
then to real config, in one sitting.

## Steps

1. **Install and check.**
   ```bash
   make setup
   make doctor
   ```
   `make setup` creates the virtualenv, installs `requirements.txt`, and
   copies `.env.example` -> `.env` and every `config/*.example.yaml` ->
   `config/*.yaml` (only if those files do not exist yet - it never
   overwrites your own copies). `make doctor` will show a `FAIL` on "hotel
   identity" right after setup - that is expected, it means the property
   name is still the shipped placeholder "Hotel Aurora". Everything else
   should be `ok` or `warn`.

2. **Run the demo.** No credentials needed.
   ```bash
   make demo
   ```
   Expect to see 5 sample questions answered (one of them deliberately
   unanswerable - see step 2 below) and the line `DEMO OK — 5 items
   processed, 5 drafted, 0 sent (shadow)`. If you do not see that, stop and
   read `workflows/99-troubleshooting.md` before going further.

3. **Fill in the property.** Edit `config/hotel.yaml` (name, address,
   currency, languages). Then:
   ```bash
   cp knowledge/property.example.md knowledge/property.md
   cp knowledge/faq.example.md      knowledge/faq.md
   ```
   Replace the Hotel Aurora content with your own property's facts -
   `search_knowledge_base` answers property questions straight from these
   files. See `knowledge/README.md` for how to write it well.

4. **Connect your financial data (optional for now).** `get_financial_summary`
   and `run_forecast` read `data/imports/financial_daily.csv` if it exists,
   falling back to the bundled Hotel Aurora fixture otherwise. See
   `docs/integrations.md` for the exact columns.

5. **Connect a real PMS (optional for now).** `systems.pms.adapter` in
   `config/hotel.yaml` starts as `mock`, which only ever sees the bundled
   fixture reservations. `docs/integrations.md` covers `csv` (works with any
   PMS) and `cloudbeds`. Run `make doctor` after changing it.

6. **Pick how the Analyst thinks.** `config/hotel.yaml`'s `llm.provider`
   starts as `interactive` - it asks you, in this Claude Code session,
   instead of calling a model. That costs nothing extra and is the best way
   to see how it reasons through a question before you point it at your
   real subscription's usage. `docs/how-it-works.md` and `docs/safety.md`
   explain the other three providers (`mock`, `claude-code`, `anthropic`)
   and when to move to one of them.

7. **Re-check.**
   ```bash
   make doctor
   ```
   Once the property name is real and `knowledge/property.md` exists, the
   "hotel identity" and "knowledge" lines turn green. Move on to
   `workflows/10-ask.md` to ask a real question.
