# Workflow: working the review queue

Objective: turn a question the Analyst could not answer into a decision -
approve, edit, or reject - and, once approved, export it for the record.

Most questions never reach this queue - a clean answer needs nobody (see
`docs/how-it-works.md`). What lands here is a question the tool loop ran out
of rounds on, or where the model's answer did not match its schema.

## Steps

1. **See what is waiting.**
   ```bash
   make review
   ```
   Each line shows the question id, its status (always `needs_human` for
   this agent - see `docs/how-it-works.md`), and the question text.

2. **Read one in full.**
   ```bash
   python3 tools/review.py show <id>
   ```
   This prints the original question, `payload._last_attempt` (every tool
   call the Analyst tried before giving up, and what each one returned),
   and the full event history. Summarise it for the person in plain
   language - what they asked, what the Analyst tried, why it stopped - do
   not paste the raw JSON at them.

3. **Decide.**
   ```bash
   python3 tools/review.py approve <id>
   python3 tools/review.py edit <id> --body-file my-answer.txt
   python3 tools/review.py reject <id> --reason "out of scope for this agent"
   ```
   `approve` records that no answer is needed (or that you have answered it
   yourself outside this system) but still queues the item for export as an
   audit row. `edit` writes your own answer as the record - useful when the
   Analyst's `knowledge/` is missing the fact it needed; if you fix the fact
   in `knowledge/property.md` or `data/imports/`, a similar question next
   time should not repeat the escalation.

4. **Export what was approved.**
   ```bash
   python3 tools/review.py send
   ```
   Claims everything `approved`/`edited`, appends one row each to
   `data/exports/answered_questions.csv`, and marks them `sent`. In `mode:
   shadow` this is blocked entirely for anything not just approved by you -
   see `core/review.py`; nothing else can ever export while shadow is on.

5. **A failed export.** `send` marks the item `failed` with the error
   attached.
   ```bash
   python3 tools/review.py retry <id>
   ```
   re-queues it for another export attempt once you have fixed the cause
   (usually a Google Sheets credential, or a full disk - `make doctor` says
   which). This retries the **export**, not the question - the answer text
   is already decided and unchanged.

## Rules

- Only `tools/review.py` writes `approved` / `edited` / `rejected`.
- Once a question is `needs_human`, only a person moves it forward - the
  Analyst will never quietly retry the same question in the background and
  overwrite your decision (see `docs/how-it-works.md` "Idempotency").
- If the same kind of question keeps escalating, that is a signal to fill in
  `knowledge/`, connect `data/imports/financial_daily.csv`, or accept the
  limit and say so plainly to whoever keeps asking - not to loosen anything
  in this queue.
