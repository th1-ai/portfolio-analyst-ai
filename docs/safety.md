# Guardrails and safety

Portfolio Analyst AI answers questions about your own data. It has no tool
that can change anything - no PMS write, no rate change, no guest message,
no payment. Everything below is built in, not optional.

## The structural guarantee

"It doesn't change rates or settings" (the roster's own words) is not a
prompt instruction here - it is enforced by what tools exist. Read
`tools/toolkit.py:TOOL_SPECS`: seven tools, every one of them a read or a
pure computation. There is no eighth tool a model could reach for to write
anything. Compare this to a guest-facing agent in this family, where the
same guarantee depends on `mode: shadow` and the review queue; this agent
does not need either of those to stay read-only, though it still ships with
both (see below), because the one thing it *can* produce - a digest export -
still goes through the family's normal write guard.

## The two modes

| Mode | What happens |
|---|---|
| `shadow` (default) | The Analyst answers every question exactly the same way. The only difference: the morning digest's CSV export never runs, and `data/exports/` stays untouched. |
| `live` | The digest export runs. Nothing about how a question is answered changes at all - see `docs/how-it-works.md` "Modes". |

`mode` lives in `config/hotel.yaml`. It is a global kill switch, same as
every other repo in this family: flipping it back to `shadow` stops the
digest export immediately, mid-schedule, with no other change.

Two more brakes, also shared with the rest of the family:

- `make run ARGS="--dry-run"` computes the identical answer and writes
  nothing at all - no `items` row, no event log, no export. Safe to repeat.
- `review.require_approval_for` in `config/hotel.yaml` lists the actions
  that need a human even in live mode. `sheets_write` (the digest export) is
  not on that list by default - add it if you want a person to approve each
  morning's digest before it lands on disk.

## The review queue

Most plain-text questions never reach this queue: a clean answer with
nothing to export goes straight to `skipped` (see `docs/how-it-works.md`).
Two things do land here: a question that produced a report
(`pending_review` - a person should look it over before it counts as an
audited answer), and a question the tool loop genuinely could not answer
(`needs_human`).

```bash
make review                       # what is waiting
python3 tools/review.py show <id>  # the question, what was tried, and why it stopped
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --body-file my-answer.txt
python3 tools/review.py reject <id> --reason "out of scope"
python3 tools/review.py send       # export approved/edited answers to data/exports/
```

Only `tools/review.py` can write `approved`, `edited` or `rejected`; only
`tools/review.py send` can write `sending`/`sent`. Once an item reaches
`needs_human`, the shared state machine (`core/store.py`) only lets a human
move it forward - the Analyst will never silently retry it in the
background and overwrite a person's decision.

## What the agent will never do

- Change a rate, a room status, a reservation, or anything else in your PMS
  - there is no write method anywhere in this agent's tool set.
- Send a guest, or anyone outside the person asking, a message on its own -
  there is no email or messaging adapter in this agent's own code path at
  all (`make doctor` shows those adapters as healthy because the check is
  shared across the family, not because this agent uses them - see
  `docs/integrations.md`).
- Take a payment, issue a refund, or move money.
- State a number that did not come from a tool call. When a fact or a
  figure is not in the connected data, it says so plainly instead of
  estimating - see the data truthfulness clause in `prompts/ask.md`, and
  `fixtures/inbound/question-05-marketing-spend.json` for a worked example
  of exactly that (see `docs/how-it-works.md` point 2 under "Design
  decisions").
- Answer forever. `tool_loop.max_rounds` (default 6, `config/agent.yaml`)
  forces a stop; a question that never reaches a clean answer within that
  budget escalates to `needs_human` rather than looping.
- Answer past its local daily cap. `rate_limit.max_questions_per_day`
  (default 200, `config/agent.yaml`) queues anything past the cap as
  `needs_human` with a plain quota message. This check fails OPEN: a bug in
  the counter itself never blocks a real question.

## Who this agent talks to

The person asking is your own staff (an owner or manager), never a guest.
The `hotel.languages` reply-language guardrail that guest-facing agents in
this family enforce does not apply here structurally, because this agent
never writes to anyone at all - if a manager copies an Analyst answer into a
guest-facing reply themselves, that reply's own agent (or their own
judgement) is what should apply that guardrail, not this one.

## Data handling

**What leaves your machine.** With `llm.provider: anthropic` or
`claude-code`, the prompt goes to Anthropic. That prompt contains the
question and whatever tool results the model asked for - property facts,
reservation summaries, financial figures - never raw guest PII beyond what
is already in `fixtures/hotel/guest_emails.json`'s columns (`from_name`,
`subject`, a short summary - no message bodies). With `llm.provider: mock`
or `interactive`, nothing leaves the machine at all.

**What is stored, and where.** Everything lives in `data/` inside this
folder: `agent.db` (SQLite - every question, answer and tool call),
`logs/*.jsonl`, `exports/`. `data/` is gitignored. There is no cloud service
behind this repo and no telemetry.

**Retention.** `privacy.retention_days` (default 365) is how long processed
items stay in the database. Deleting `data/agent.db` deletes every question
this agent has ever answered.

## Telling people they are talking to AI

The EU AI Act (Article 50) requires that a person is told when they are
interacting with an AI system, unless it is obvious. For this agent that is
close to automatically satisfied: the person asking opens a terminal and
types `--question "..."`, or reads a digest explicitly labelled as the
Analyst's - there is no ambiguity that software answered. Where this still
matters: if you build a chat interface on top of this agent for people other
than the owner/GM (a board member, an investor), tell them plainly, the same
way any other agent in this family does for guests.

## Subscription or API: an honest note

Two ways to pay for the reasoning:

**Your Claude Code subscription** (`llm.provider: claude-code` or
`interactive`). Flat monthly cost, no per-question billing. A handful of
scheduled digest runs a day plus ad-hoc questions is a normal way to use a
personal subscription; automated use is still subject to Anthropic's usage
policy and rate limits - read the terms and decide for yourself.

**The Anthropic API** (`llm.provider: anthropic`). Pay per token, proper
rate limits, usage you can attribute. `make report` shows what you are
spending either way.

Start on the subscription while you are learning what the Analyst answers
well. Move to the API once questions are a normal part of how the portfolio
runs.

## If something goes wrong

1. `mode: shadow` in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env`.
   The digest export stops on the next pass; questions keep answering
   exactly as before (there was never anything to stop there).
2. Remove the schedule (`crontab -e`, `launchctl unload`, or
   `systemctl disable --now <slug>.timer`).
3. `make doctor` to see what the agent thinks its state is.
4. `data/logs/*.jsonl` has every decision, with the run id, in order.
