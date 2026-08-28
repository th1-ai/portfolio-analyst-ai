# Connecting your systems

Every connector in this repo is one of three things, and the table says which.

| Badge | Means |
|---|---|
| **built** | Written against the real API and tested against it. |
| **universal** | Works with any system through a common protocol: IMAP/SMTP, CSV, a webhook. |
| **stub** | Interface only. Calling it raises a clear error with a recipe for adding it. |

Check what is actually working on your machine at any time:

```bash
make doctor
```

`make doctor` prints a line for all four `core/adapters` families (PMS,
email, messaging, sheets) - that check is shared by every repo in this
family. Portfolio Analyst AI only actually uses two of them: **PMS** (read
only - reservations, arrivals, departures) and **Sheets** (the digest
export). The email and messaging lines will show green on a fresh clone
because the `mock` adapter always works, not because this agent reads your
mailbox or sends WhatsApp - it does neither.

## What this agent actually reads

Four things feed the seven tools in `tools/toolkit.py`. Three of them are
CSV-first by design (see `docs/how-it-works.md` "Design decisions" point 8):
`core/adapters/base.py` has no daily-ledger, cross-agent or fleet-telemetry
interface, so this repo reads a CSV export the same way
`core/adapters/pms_csv.py` does for a PMS, rather than inventing an adapter
this repo cannot connect to anything real.

### PMS - `systems.pms.adapter` in `config/hotel.yaml`

Used by `list_reservations` (arrivals, departures, in-house, upcoming,
recent). Read only - there is no PMS-write tool in this agent at all.

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `mock` | universal | nothing | Reads `fixtures/hotel/reservations.json`. What `make demo` uses. |
| `csv` | universal | a CSV export | Reads `data/imports/*.csv`. **Start here.** Works with any PMS. |
| `cloudbeds` | built | `CLOUDBEDS_CLIENT_ID`, `CLOUDBEDS_CLIENT_SECRET`, `CLOUDBEDS_REFRESH_TOKEN`, `CLOUDBEDS_PROPERTY_ID` | Live reads. |
| `cli` | universal | `PMS_CLI_COMMAND`, `PMS_CLI_PROFILE` | Bridges to a vendor command line tool. |

### Financial ledger - `data/imports/financial_daily.csv`

Used by `get_financial_summary` and `run_forecast`. Not a `core/adapters`
family - there is nothing in `core/` to register, just a CSV your accounting
system (or a spreadsheet export) can produce. Columns: `date, revenue_rooms,
revenue_fnb, revenue_other, costs_total, occupancy_pct, adr,
rooms_available`. One row per day. Falls back to
`fixtures/hotel/financial_daily.json` (the invented Hotel Aurora, two years
of daily data) when the CSV is absent - see `tools/data.py:load_financial_daily`.
**Without this file, `get_financial_summary`/`run_forecast` never answer
from the bundled fixture as if it were your real ledger** - they return
`"connected": false` and a plain-language "not connected" message instead,
same as guest emails and the agent fleet below. Connect
`data/imports/financial_daily.csv` in `workflows/00-setup.md` step 5 before
asking a real money question.

### Guest email snapshot - `data/imports/guest_emails.csv`

Used by `list_pending_emails`. Columns: `id, from_name, subject,
classification, confidence, status, summary, received_at`. A real portfolio
running Front Desk AI or a similar guest-comms agent alongside this one
would export this from that agent's own database on a schedule; this repo
has no hidden dependency on another repo's tables. **Without this file,
`list_pending_emails` never falls back to the bundled fixture as if it were
your real inbox** - it returns `"connected": false` and a plain-language
"not connected" message instead, and `prompts/ask.md`'s DATA TRUTHFULNESS
rule tells the model to say exactly that rather than guess or borrow the
sample data (`fixtures/hotel/guest_emails.json`, the invented Hotel Aurora's
mail, only feeds `make demo` and the tests, never a real property's answer).

### Agent fleet snapshot - `data/imports/agents_fleet.csv`

Used by `get_agent_status`. Columns: `slug, name, nickname, status,
runs_today, runs_30d, success_rate, last_run_at`. Hand-maintained or
exported from wherever you track your own fleet of agents. Same rule as
guest emails above: without this file, `get_agent_status` returns
`"connected": false` and says so, rather than answering from
`fixtures/hotel/agents_fleet.json`'s invented agents.

### Knowledge base - `knowledge/*.md`

Used by `search_knowledge_base`. Every real (non-example) file in
`knowledge/`, plus the bundled `fixtures/hotel/*.md`, split into `##`
sections and ranked by keyword overlap - see
`tools/data.py:knowledge_passages`. No RPC, no external search service.

### Sheets - `systems.sheets.adapter`

Used by `workflows/16-digest.md` (`tools/run.py --once --digest`) to export
the morning briefing, and by `tools/review.py send` to export an
approved/edited answer to the record.

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `csv` | universal | nothing | Writes `data/exports/digest_reports.csv` and `data/exports/answered_questions.csv`. |
| `google` | built | `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE` | A live shared spreadsheet. |

### Not used at all by this agent

<a id="email"></a>

**Email.** Portfolio Analyst AI has no tool that reads or sends email -
`list_pending_emails` reads a CSV snapshot (see "Guest email snapshot"
above), not a mailbox. If `make doctor` shows a FAIL on the email adapter,
that only happens once you set `systems.email.adapter` in `config/hotel.yaml`
to something real (`gmail`, `imap`) - this agent never asks you to, and
never touches the result either way. `core/adapters/email_gmail.py` and
`core/adapters/email_imap.py`'s own fix hints (`docs/integrations.md#email`)
point here: connecting a real mailbox is for another agent in this family
(Front Desk AI, say) that actually reads guest mail. If you filled in your
mailbox anyway while copying `hotel.yaml` across your agent family (it is
meant to be shared, per `workflows/00-setup.md`), either fix the `.env`
credentials the fix hint names, or set `systems.email.adapter: mock` back -
Portfolio Analyst AI runs exactly the same either way.

<a id="messaging"></a>

**Messaging.** Same story as email, one paragraph up: no tool here reads or
sends a WhatsApp/SMS message. `core/adapters/messaging_unipile.py`'s fix
hint (`docs/integrations.md#messaging`) is for an agent that does.

`pos`, `accounting`, `reviews`, `calendar`, `payments`, `procurement` and
`locks` are also **stubs** in `core/adapters/`, for the same reason: this
agent has no tool that would call any of them. If your own workflow needs
one (a `get_marketing_summary` tool, say, once you have a real ad-spend
export), the five-step recipe below still applies.

## Implement your own

<a id="implement-your-own"></a>

The interface is small on purpose, and your Claude Code session can do this
with you in an afternoon. Open `claude` in this folder and paste:

> Read `docs/integrations.md#implement-your-own` and `core/adapters/base.py`.
> I need a PMS adapter for **<your system>**. Its API docs are at **<url>**
> and I have credentials in `.env` as `<VAR names>`. Copy
> `core/adapters/pms_csv.py` as the shape, implement `ping`, `capabilities`
> and the read methods first, register it in `core/adapters/__init__.py`,
> and stop before the write methods so I can check the reads with
> `make doctor`.

### The five steps

**1. Copy the closest existing adapter.** `core/adapters/pms_csv.py` for a
PMS, `sheets_csv.py` for a reporting target.

**2. Implement `ping()` and `capabilities()` first.**

```python
def ping(self) -> HealthCheck:
    """Never raises. Returns ok=False with a fix_hint a hotel can act on."""

def capabilities(self) -> set[str]:
    """The method names that actually do something on this adapter."""
```

`make doctor` reads both.

**3. Implement the reads.** Map the vendor's fields onto the dataclasses in
`core/adapters/base.py` (`Reservation`, `RoomType`, `RateRow` for a PMS).
Put anything you do not map into `.extra` rather than dropping it. Dates are
ISO `YYYY-MM-DD`. Money is a float in the hotel's currency.

**4. Implement the writes, each with the guard - and add a new tool.** A new
data source this agent should reason over needs a matching entry in
`tools/toolkit.py:TOOL_SPECS` and a function in `TOOL_FUNCS`, following the
shape of the seven already there. If it ever needs to write anything (most
of this agent's own tools never do), decorate it:

```python
from core.adapters.base import guarded_write

@guarded_write("pms_write")
def add_note(self, reservation_id: str, text: str) -> dict:
    ...
```

The decorator is not optional. Without it your adapter can write while the
agent is in shadow mode, which defeats the entire safety model.

**5. Register it.** One line in `core/adapters/__init__.py`:

```python
REGISTRY["pms"]["yoursystem"] = "core.adapters.pms_yoursystem:YourSystemPMS"
```

Then set `systems.pms.adapter: yoursystem` in `config/hotel.yaml` and run
`make doctor`.

### Rules that matter

- **`ping()` never raises.** It returns `HealthCheck(ok=False, ...)` with a hint.
- **Every write is decorated.** No exceptions.
- **Never log a credential.** `core/log.py` masks anything whose key looks
  like a secret, but do not rely on it.
- **Write a test.** Copy `tests/test_pa_toolkit.py`. It should run with no
  network: feed your tool a `ToolContext`, check the dict that comes back.

### `core/` is shared

`core/` is identical in all 28 agents in this family. If you change
something in `core/`, keep it generic - a Portfolio-Analyst-specific tweak
belongs in `tools/`, not in the shared runtime.
