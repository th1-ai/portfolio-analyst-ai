---
name: portfolio-analyst-ai
description: Run Portfolio Analyst AI ("The Analyst") — a natural-language analyst over your property's connected data. Use when the user asks to run the agent, ask it a question, check what is waiting for review, approve or reject a draft, or asks how the agent is doing. Trigger phrases: "run The Analyst", "/portfolio-analyst-ai", "ask the Analyst", "check the queue", "what is waiting for me", "approve that draft".
---

# Portfolio Analyst AI

Answers a question from the property's own connected data and works its
review queue. Everything happens from the repo root; every command below
exists and works.

## Before anything else

Read `README.md` if you have not this session, and `workflows/10-ask.md` for
the main loop. If the user has never run this agent, start at
`workflows/00-setup.md` instead and walk them through it.

## The loop

**1. Check the agent is healthy.**

```bash
make doctor
```

Any `FAIL` line has a fix hint. Fix it before going further. `WARN` lines
are worth mentioning but do not stop the run.

**2. Ask the question.**

```bash
make run ARGS='--question "How are we doing this month?"'
make run ARGS='--question "..." --dry-run'   # compute the answer, write nothing
```

If `llm.provider` is `interactive`, the run will stop with exit code 3 and
park a prompt in `data/pending/`. That is expected, and may happen more than
once per question - one round per tool call, plus one for the final answer.
Read each `*.prompt.md`, write your answer as JSON to the matching
`*.answer.json` following the schema exactly, then run the same command
again.

**3. Give the answer in plain language.** The reply prints straight to the
terminal - read it back to the user in their own words, not as raw JSON.

**4. If it could not answer,** show what is waiting.

```bash
make review
python3 tools/review.py show <id>
```

`payload._last_attempt` shows exactly which tools were tried and what came
back - explain why it stopped, not just that it did.

**5. Act on their decision, if it needed one.**

```bash
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --body-file <path>
python3 tools/review.py reject <id> --reason "<why>"
```

**6. Report.**

```bash
make report
```

## The morning digest

```bash
make run ARGS="--digest"
```

Asks the standing question list in `config/agent.yaml: digest.questions`.
See `workflows/16-digest.md` before turning on the schedule.

## Rules

- **Nothing here ever writes to the PMS, sends a guest a message, or moves
  money** - there is no tool in this agent that can. The only write at all
  is the digest export, and it is blocked entirely in `mode: shadow`.
- **Going live is the hotel's decision.** Only raise it after
  `workflows/90-go-live.md` has been worked through.
- **Never print or paste a credential.**
- If a run fails, read the whole error, fix the cause, re-run, and note what
  you learned in `workflows/99-troubleshooting.md`.
