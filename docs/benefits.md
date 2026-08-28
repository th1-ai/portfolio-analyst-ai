# The business case

## What the roster promises

- **does** - "A natural-language analyst over your whole portfolio's data.
  Ask it anything ... and it queries the connected data sources, runs its
  own analysis scripts, renders charts in the chat, and produces board-ready
  PDFs on demand."
- **output** - "Any portfolio question answered in seconds, with charts and
  exportable PDFs; live today across a multi-property portfolio."
- **roi** - **-80%** on "Time to answer a data question" (labor).

See `docs/how-it-works.md` "Design decisions" for exactly where this
template narrows those claims to what it can honestly do (single property,
no ROAS/marketing data, Markdown/CSV export rather than a rendered PDF).

## What to measure

`tools/report.py` (`make report`) reads straight from `data/agent.db`:

- **Volume**: questions asked, by status right now.
- **Answered cleanly %**: share that reached `skipped` - a plain answer
  with nothing to export, no human needed at all - the number behind
  "answered in seconds". A report-bearing answer (`pending_review`, then
  `sent` once approved) is not counted here even once a person approves it
  unchanged - a human still looked at it. A number well under 100% is a
  signal to fill in `knowledge/` or add a CSV export, not a bug.
- **Average tool calls per question**: a cheap, well-connected question
  should trend toward one or two round trips. A rising average over time is
  worth a look - either the questions are getting harder, or a knowledge gap
  is making the model search repeatedly before giving up.
- **Time to answer**: average seconds from a question being asked to it
  reaching a terminal status - the number behind the roster's "-80%" claim,
  measured against however long the same question used to take a person
  with ten dashboard logins.
- **Spend**: `core.llm.complete()` records usage and cost to the `events`
  table on every round trip, whenever the provider is `anthropic` or
  `claude-code`; zero for `mock`/`interactive`.

## Honest caveats

- Every number the Analyst states came from a tool call - see the data
  truthfulness clause in `prompts/ask.md`. It will say "I don't have that
  connected" rather than guess, and `fixtures/inbound/question-05-marketing-spend.json`
  is a worked example of exactly that.
- It reports and explains. There is no tool anywhere in this agent that can
  change a rate, a booking or a setting - see `docs/safety.md`.
- The ROI is in the two-minute conversation replacing a spreadsheet pull or
  a wait on the accountant, not in replacing anyone's judgement about what
  to do with the answer.
