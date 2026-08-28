# Workflow: asking a question

Objective: get a real answer from the Analyst, and see how it worked it out.

## Inputs

- A configured `systems.pms.adapter` (`mock` by default - see
  `workflows/00-setup.md` step 5 to connect a real PMS).
- `data/imports/financial_daily.csv`, if you have connected real financial
  data (optional - falls back to the bundled fixture).
- `knowledge/property.md` and `knowledge/faq.md`, filled in with your own
  property's facts (optional for now - falls back to the bundled fixture).

## Steps

1. **Ask one question.**
   ```bash
   make run ARGS='--question "How are we doing this month?"'
   ```
   or, equivalently and more readably for a longer question:
   ```bash
   python3 tools/run.py --once --question "Who is arriving today?"
   ```
   Each question runs the bounded tool loop (`tools/tool_loop.py`): the
   model decides which of the seven tools in `tools/toolkit.py` to call,
   sees the results, and either calls more tools or gives its final answer -
   see `docs/how-it-works.md` for the full mechanics. The first line
   printed is always `question id: ask-<day>-<hash>` - that id is derived
   from the question's own wording (normalized: trimmed, lower-cased,
   whitespace-collapsed) plus today's date, not a random number, so
   **re-running the exact same command later resumes this same question**
   instead of starting a new one.

2. **If `llm.provider` is `interactive`,** the run parks a prompt in
   `data/pending/` and stops (see the exit-code note below). Read
   `*.prompt.md` - it shows you the full system prompt, the tool list, and
   the conversation so far. Work out the step (call a tool, or answer),
   write it as JSON to the matching `*.answer.json` exactly matching the
   schema shown, and run the exact same command again (same question text,
   same `--as-of` if you used one). This may happen more than once per
   question - one round per tool call, plus one for the final answer - and
   each round only ever pends once: a round you have already answered is
   replayed from the item's own record on every later restart, with no new
   model call and no re-running of that round's tools, so you never have to
   supply the same answer twice (`tools/tool_loop.py`'s round cache).
   Exit code: `python3 tools/run.py --once --question "..."` exits 3
   directly. Through `make run ARGS='...'`, `make` itself exits with its
   own generic failure code (2) and separately prints the real one, e.g.
   `make: *** [run] Error 3` - read the `3` in that line, not `make`'s own
   `$?`. If you ever need to continue a specific pending question by id
   instead of by re-typing its exact wording (e.g. after rewording it, or
   across midnight), pass `--resume <id>` with the id printed in step 1.

3. **Read the answer.** A clean answer prints straight to the terminal.
   The question's `items` row goes straight to `skipped` (nothing to
   review - it was already delivered) unless it included a report
   (`generate_report`), in which case it goes to `pending_review` so
   someone looks it over before `tools/review.py send` can export it.

4. **If it could not answer,** it prints nothing useful and the exit code is
   still 0 (this is not an error - it is the agent doing exactly what
   `docs/safety.md` says it should: never guess). The question is now
   `needs_human` - `workflows/80-review.md` covers what to do with it.

5. **See everything the agent has answered.**
   ```bash
   make report
   ```

## Edge cases

- **A question outside the connected data** (marketing spend, ROAS, a
  competitor's numbers - anything `tools/toolkit.py` has no tool for). The
  Analyst tries what it can (usually `search_knowledge_base` a few
  different ways), finds nothing, and escalates rather than guessing - see
  `fixtures/inbound/question-05-marketing-spend.json` for exactly this case
  played out with the `mock` provider.
- **A model answer that does not match its schema.** `core.llm` raises
  `LLMSchemaError` rather than accept a bad answer; the question is queued
  as `needs_human` with the error recorded, instead of guessing.
- **The daily question cap is reached** (`rate_limit.max_questions_per_day`
  in `config/agent.yaml`, default 200). The question is queued as
  `needs_human` with a plain quota message - raise the cap or wait until
  tomorrow. This is a local safety rail, not a real outage.
- **You ask the exact same wording again the same day.** Same normalized
  text, same day means the same id (`tools/engine.py:question_external_id`)
  - the same behaviour the scheduled digest already had per question (see
  `workflows/16-digest.md`). If it already has a clean answer, you get
  "Already answered - use a fresh question to ask again," not a re-run. If
  it is still pending an `interactive` answer, you resume it, per step 2
  above. To force a genuinely new question with the same wording, change
  the wording (even a word) or wait until tomorrow, or pass `--resume` with
  a fresh id you make up.
