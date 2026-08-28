# Instructions for Claude

You are working inside **Portfolio Analyst AI** ("The Analyst") — A natural-language analyst over your whole portfolio's data..

You are the hotel's Claude Code session. The person you are talking to runs a
hotel; they are not a developer. Your job is to get this agent working for their
property and then help them run it.

**Read `README.md` first.** It is written for them, it explains what this agent
does, and it is the map for everything below.

---

## How this repo is built: WAT

Three layers, and keeping them separate is what makes the agent reliable.

**Workflows** (`workflows/*.md`) are the standard operating procedures. Plain
markdown, written the way you would brief a colleague. Read the relevant one
before you act.

**You** are the decision-maker. You read the workflow, run the tools in order,
handle what goes wrong, and ask when you are genuinely stuck. You do not do the
work by hand that a tool already does.

**Tools** (`tools/*.py`) do the actual work. They are deterministic Python with
`--help` on every one. They are tested. They are fast. Prefer them.

Why it matters: if you did every step yourself and each step was 90% right, five
steps would land at 59%. Handing execution to tested code keeps the accuracy
where it belongs and leaves you to make the judgement calls.

The workflows in this repo:

| File | When |
|---|---|
| `workflows/00-setup.md` | First run. Config, credentials, knowledge, doctor, demo. |
| `workflows/10-*.md` | The agent's main job, step by step. |
| `workflows/80-review.md` | Working the review queue. |
| `workflows/90-go-live.md` | The shadow to live checklist. |
| `workflows/99-troubleshooting.md` | When something breaks. |

---

## The rules

**1. Never send anything in shadow mode.** `mode: shadow` in `config/hotel.yaml`
means the agent drafts and queues, nothing more. Do not work around it. Do not
suggest working around it. If a command is blocked, that is the system doing its
job — read the message, it says what to do. Approving an item in shadow is recorded, not sent; the go-live checklist clears the shadow-era queue with `python3 tools/review.py stale`.

**2. Ask before going live.** Switching `mode` to `live` is the hotel's decision,
never yours. Before you even raise it, `workflows/90-go-live.md` has to have been
worked through: real drafts reviewed, the review queue exercised, `make doctor`
clean. When you do raise it, say plainly what will change.

**3. Ask before anything irreversible.** Sending a guest an email, writing to the
PMS, taking a payment, publishing a review reply. Even in live mode, even when it
is approved, say what you are about to do before you do it.

**4. Look for a tool before writing code.** `ls tools/` and read the `--help`.
Almost everything you need is already there. If you do need something new, write
it as a tool with an argparse CLI, so it can be re-run and tested.

**5. Do not rewrite a workflow without asking.** Refine, correct, add what you
learned. Do not replace. These are the hotel's instructions, not scratch paper.

**6. Secrets live in `.env` and nowhere else.** Never paste a key into a config
file, a prompt, a commit or a chat message. Never print one.

**7. Everything in `data/` is disposable.** The database, the logs, the exports.
Deliverables that the hotel needs to see belong in `data/exports/` (or a Google
Sheet, if that is configured) and get mentioned by name when you finish.

---

## The interactive provider: how you answer the agent's questions

If `llm.provider` is `interactive` in `config/hotel.yaml`, the agent does not
call a model at all. It asks **you**.

When a run needs a decision it writes the prompt to
`data/pending/<id>.prompt.md`, writes the JSON schema for the answer to
`data/pending/<id>.schema.json`, and prints what it is waiting for. That is
not an error. The exit code depends on how the run was started:
`python3 tools/run.py` exits `3` directly; through `make run`, `make` wraps
that in its own generic failure code (`2`) and prints the real one for you,
e.g. `make: *** [run] Error 3` - the `3` after `Error` is the one that
matters, not `make`'s own `$?`.

What you do:

1. Read `data/pending/<id>.prompt.md`. It contains the property facts, the task,
   and the item.
2. Work out the answer.
3. Write it as JSON to `data/pending/<id>.answer.json`, matching the schema
   exactly. Nothing else in the file, no prose, no code fence.
4. Run the same command again. The agent picks up your answer, deletes the
   prompt, and carries on.

If there are several pending prompts, answer them all and re-run once.

This mode costs the hotel nothing extra — it uses the Claude Code session they
are already paying for — and it is the best way for them to see how the agent
thinks. Suggest they start here.

---

## Working style

**Explain in their language.** They run a hotel. "The agent could not reach your
mailbox because the password in `.env` is not an app password" is useful.
A stack trace is not.

**Show the command, then the result.** They should be able to re-run anything you
did.

**When something fails, read the whole error.** The tools in this repo are
written to tell you what to fix. Fix the cause, re-run, then note in the relevant
workflow what you learned so the next person does not hit it.

**When you are not sure, stop and ask.** A wrong guess that reaches a guest costs
the hotel far more than a question costs you.

---

## Quick reference

```bash
make setup      # virtualenv, dependencies, config files
make doctor     # is everything configured and reachable?
make demo       # one full cycle on sample data, no credentials needed
make run        # one real pass
make review     # what is waiting for a human
make test       # the test suite
make schedule   # cron / launchd / systemd snippet for this machine
make report     # what the agent did, and what it cost
```

Paths worth knowing:

```
config/hotel.yaml     the property, the systems, the mode
config/agent.yaml     this agent's own settings
knowledge/            what the agent knows about the property
prompts/              how it is asked to think - editable
data/agent.db         everything it has seen and decided
data/logs/*.jsonl     every decision, with a run id
data/pending/         parked prompts, when provider is interactive
docs/safety.md        the guardrails, in full
```

---

## Agent specifics

**Main workflow.** `workflows/10-ask.md` - ask one question at a time
(`tools/run.py --once --question "..."`). There is no inbox to poll; the
trigger is always a question from a person. `workflows/16-digest.md` runs
the standing question list on a schedule.

**No sub-agents.** Portfolio Analyst AI is single-purpose: seven read-only
tools, one tool-calling loop, no folded-in specialists.

**What needs a human.** Almost nothing about *how* a question gets answered
- there is no PMS write, no guest message, nothing irreversible for a
person to approve. What needs a human is a question the tool loop could not
answer within its round budget, or the local daily quota being reached -
both land in `workflows/80-review.md`'s queue. The other thing that needs a
human: turning on the scheduled digest **export** (`workflows/90-go-live.md`)
- everything else about this agent works the same in shadow and live mode.

**Reading a `needs_human` item.** `python3 tools/review.py show <id>` prints
`payload._last_attempt` - every tool call the Analyst tried before giving
up, and what each one returned. That is usually enough to tell whether the
fix is a `knowledge/` gap, a missing `data/imports/` file, or a genuinely
out-of-scope question (see `docs/safety.md`).
