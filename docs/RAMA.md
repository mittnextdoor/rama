# RAMA: from a borrower's books to approved LP risk intelligence

Built 2026-10-17 for MONEY TALKS 2. Everything here runs today on synthetic data; the Chronograph destination is a
demonstration (no live connection).

## Run it

```
cp .env.example .env          # NICRRON_API_KEY, PRISMTRACE_API_KEY, PRISMTRACE_PROJECT_ID (never commit .env)
.venv/bin/pip install -r requirements.txt
# put the Cap IQ screen export at data/capiq/screen_snapshot_2026-10-16.xlsx (licensed; data/ is gitignored)
.venv/bin/python -m rama.api --port 8810      # http://127.0.0.1:8810
```

No database server is needed: the close runs on a local SQLite engine file under `data/rama/work/`, and the workflow
state is `data/rama/state.json`. The gear icon (top right) resets the scenario.

## The demo path (what each screen does)

1. **Dashboard** (Vision UI layout): fund loans, borrower EBITDA (verified or held), indicators fired, cards released;
   close confidence; risk signals; cash tied to the bank statements; fund exposure; the six loans; activity.
2. **Close**: *Run the close*. RAMA's agents (Bob's engine) read Helios Compute's books, tie the operating and reserve
   accounts to the bank statements and both loans to the lenders' statements, record the missing Gridline power payment
   (a known vendor, cited to the statement line and three ledger entries) and ask the classifier (through Nicrron) about
   the unexplained Atlas wire. Two blockers wait for a person:
   - *Post entry per lender statement*: September's PIK ($1.75M) the books never capitalized;
   - *Book line*: the Atlas wire to an account the reviewer chooses, with its support.
   Each decision is posted with its citation and the month is closed again. Click a workpaper for the evidence reveal:
   the financial result, the workpaper's activity and the supporting statement side by side.
3. **Intelligence**: verified accounting (only tied evidence) + the Cap IQ snapshot (12 companies, as of 2026-10-16)
   + the labelled non-S&P inputs. *Build indicators* runs rules R1-R14: 10 fire, 4 are "not evaluated" because their
   data wasn't pulled (never estimated). Click a rule for its figures, threshold (LP policy / fund document / default)
   and sources with as-of dates.
4. **Review & release**: one card per fired rule, worded by the card agent (OpenAI Agents SDK, model through Nicrron),
   each checked by two output guardrails (every number is a rule output; no advice: blocklist + a Nicrron classifier).
   *Explain* expands a card into its facts, threshold, sources and checks. Approve or reject cards one by one, or
   *Approve package & release*: the amber line carries the approved cards to the destination. The guardrail test blocks
   an advisory sentence and logs it.
5. **Chronograph** (demonstration destination, labelled): the LP's monitoring view with the fund's holdings and the
   approved risk notes; "What should I do?" gets the fixed hand-off.
6. **Execution · PRISM**: the setup doctor (live_connected), the session's runs and each run's steps.

## How it is built

| Piece | Where |
|---|---|
| Borrower books and source files (synthetic; proxy CRWV) | `rama/borrower.py` |
| Close (Bob's engine), lender statements, reviewer decisions | `rama/close.py` |
| Verified metrics (held until evidence ties) | `rama/metrics.py` |
| Fund: L1-L6, facility, LP policy (L2 from the close) | `rama/fund.py` |
| Cap IQ snapshot loader (xlsx/csv, NM/NA/NR non-numeric) | `rama/capiq.py` |
| Rules R1-R14 (deterministic) | `rama/rules.py` |
| Card agent + guardrails (Agents SDK via Nicrron) | `rama/cards.py` |
| Workflow state, approval, publication | `rama/pipeline.py` |
| PRISM (Agent Frameworks card) and run records | `rama/tracing.py` |
| API + web app (vanilla JS, ApexCharts vendored) | `rama/api.py`, `rama/web/` |
| Tests (no model or network calls) | `tests/test_rama.py` |

**PRISM:** PRISM's `PRISMtraceTracingProcessor` is the Agents SDK's only trace processor (queued so nothing waits on
delivery). Agent runs, generations, tool calls and guardrails are traced by the SDK; the close engine's steps, the rules,
reviewer decisions, approval and publication are mirrored as SDK function spans. Everything for the month shares the
session `helios-2026-09`. The direct HTTP posting from `bob/trace.py` is off for RAMA (`BOB_TRACE_HTTP=0`).

**Nicrron:** every model call: the close's classifier (`NicrronProvider`), the card writer and the compliance check
(`OpenAIChatCompletionsModel` with Nicrron's OpenAI-compatible endpoint).

## What is synthetic, what is real

- Synthetic: Helios Compute's books and statements, the lenders' statements, loans L1 and L3-L6, the facility, the LP
  and its policy. Helios is not CoreWeave; CRWV is its public proxy for market data only.
- Real: the Cap IQ Pro screen (12 companies, as of 2026-10-16), shown as derived signals, never raw tables.
- Cited, outside S&P: the H100 rental index (Spheron, citing SemiAnalysis) and the Oracle Project Jupiter force-majeure
  event (Bloomberg / Reuters, as cited in the event register). Add the article links before publishing the demo.
