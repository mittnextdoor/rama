# Close to Insight: the 4-hour build plan (MONEY TALKS 2)

> **Superseded for build order by [INTELLIGENCE.md](INTELLIGENCE.md)** (2026-10-17): the demo is a private debt fund, the LP layer runs rules R1–R14 from [LEADING_INDICATORS.md](LEADING_INDICATORS.md), and PRISM uses the Agent Frameworks card.

The product spec is [product-spec.md](product-spec.md); the codebase context is [../CLAUDE.md](../CLAUDE.md) and
[../HACKATHON.md](../HACKATHON.md). This file is how we split the build. Nothing in it is built yet.

## Where we start

The team repo's `main` already has, tested:

- **Nicrron** for every model call: `product/reasoning/providers.py` (`NicrronProvider`, standalone, OpenAI-style chat
  completions with tool calls). `BOB_HACKATHON=1` sends every agent through `api.nicrron.ai/v1`, with no direct-provider fallback.
- **PRISM by Block Convey** run tracing: `bob/trace.py` (`trace.run(...)`, `trace.step(name, kind, input)`, traces + spans +
  trajectory, `python -m bob.trace verify`). It says "received" only on a 2xx with an id.
- **An evaluation harness pattern:** `bob/eval/` (synthetic cases, expectations kept away from the agent, runner, v1 baseline vs v2).
- **The web shell** at `/firm/` (Next.js static export) and a review/workpaper design we can copy.

Not yet tested live: no Nicrron or PRISM call has been made with real keys (`HACKATHON.md` §7).

**What's missing for the spec:** capital accounts for each investor, capital calls and distributions checked against their
notices, management fees, pro rata allocations, the LP portal, market signals and the compliance filter.

**Git:** branches `a/engine` and `b/portal`; merge to `main` at the 1:20 and 3:10 marks.

## Architecture

A new `fund/` package with its own small FastAPI app and **no database**: fixtures and run records are JSON files on disk.
That means no Postgres to set up and no migration to fail during the demo. Reused unchanged: `NicrronProvider`, the evaluation
runner pattern and the `/firm/` shell. One small change: `bob/trace.py` takes a per-run agent id, so PRISM shows two agents.

```
fund/
  models.py      Pydantic: Fund, Investor, Commitment, Notice, Position, CapitalAccount, LPPolicy, and the API responses
  synth.py       Fund III: $500M, 5 synthetic LPs, 8 synthetic portfolio companies, each mapped to real public comparables
  calc.py        the typed tools (below); every number comes from here; pytest
  signals.py     Cap IQ snapshot loader (with its as-of date) + one EDGAR 13F
  agents.py      orchestrator through Nicrron with tool calls; notice intake; break explainer; insight writer
  compliance.py  word rules + a model check of each insight card
  workpaper.py   HTML/PDF with tick-mark anchors to the source document and line
  api.py         /api/fund/close/run, /close/{id}, /workpaper/{id}, /lp/{id}, /lp/{id}/scenario, /eval
  eval/          60+ cases, expectations, runner (Bob's pattern)
```

**The tools** (all in `calc.py`, all tested; agents call them and may only report what they return):
`reconcile_cash`, `reconcile_capital_activity`, `compute_management_fee` (on commitments, flat %), `allocate_pro_rata`,
`roll_forward_capital_accounts`, `estimate_current_nav`, `run_scenario`.

**How the insight figures are worked out** (code computes them; the model only phrases them):

- **NAV estimate:** each company's last mark × (its comparables' EV/EBITDA now ÷ at the mark date).
- **Denominator drift:** shock the LP's public book by x%, then recompute their private equity weight against the target the
  LP entered.
- **Capital call stress:** the Takahashi–Alexander (Yale) model on unfunded commitments, with a base and a stressed call rate.

## Cap IQ Pro

Default: CSV exports (Excel plug-in or screener) into `data/capiq/` (git ignores `data/`), loaded as a dated snapshot. If we
have API access, it slots into `signals.py` the same way.

What to pull:

1. Daily prices for the last 12 months: S&P 500, Russell 2000, Nasdaq, the sector ETFs, and 2–3 public comparables for each of
   the 8 portfolio companies (e.g. software, healthcare services, industrials).
2. EV/EBITDA and EV/Revenue for those comparables at the mark date (Sept 30) and today.
3. The high-yield spread and the 10-year yield if Cap IQ has them; otherwise FRED.
4. Stretch: PE-backed M&A and IPO volumes, for distribution pacing.

**Licence guardrail:** raw Cap IQ data never goes to a model and never goes into git. The model sees only figures the code
computed. That is also our answer to the spec's open question on licensed data and AI processing.

## Nicrron and PRISM

**Nicrron handles every model call:** the orchestrator, extracting the capital call notice PDFs, account mapping, explaining
reconciliation breaks, the insight writer and the compliance check. Pinned model id and temperature 0 for evaluation runs.

**PRISM: two agents.**

- **`fund-close`**, one trace per fund-month. Spans: `extract_document` (each notice), `map_gl_accounts`, `reconcile_cash`,
  `reconcile_capital_activity`, `compute_management_fee`, `allocate_pro_rata`, `roll_forward_capital_accounts`,
  `explain_break` (each break), `render_workpaper`, `verify_expected_outcome`.
- **`lp-insights`**, one trace per LP refresh. Spans: `load_signals`, `estimate_current_nav`, `run_scenario`, `write_insight`,
  `compliance_filter` (a blocked card ends this span with an error status).

**Alert rules:** `error_rate` on `fund-close`; `error_rate` on `lp-insights` (fires when the compliance filter blocks a card);
`latency` as a backup.

**The improvement story:** run 60+ cases through v1 and keep that baseline → PRISM Root Cause on the failed runs → fix the
cause → run v2 on the same inputs.

The cases plant: an unrecorded wire, a call booked to the wrong LP, a fee on the wrong basis, a notice whose total doesn't
match its lines, a distribution posted twice, an excused LP, and variants of an LP's name. Likely real failures in v1: exact
name matching ("CalPERS" vs "California Public Employees' Retirement System") and prescriptive wording from the first insight
prompt. We write v1 straightforwardly and report whatever actually fails; nothing is planted to fail.

## Who does what

- **A (Mitt + a Claude session):** engine, agents, PRISM, evaluation.
- **B (partner + a Claude session):** Cap IQ data, front end, demo.

| Time | A | B |
|---|---|---|
| 0:00–0:20 | Fresh clone; `.env` keys; `python -m bob.trace verify` shows LIVE CONNECTED; one Nicrron call answers. Write `fund/models.py` first: it's the contract B builds against. | Start the Cap IQ exports; add `recharts`, `pdfplumber`, `reportlab`. |
| 0:20–1:20 | `synth.py` and the source files (trial balance CSV, bank CSV, 2 notice PDFs, investor register); `calc.py` with tests. | `signals.py` reading the Cap IQ CSVs; against mock JSON, the `/firm/fund/` close checklist and the `/lp/` portal: allocation card, shock slider, call stress chart, policy targets, the "not investment advice" notice. |
| 1:20–2:20 | Orchestrator loop through Nicrron; notice extraction; break explanations citing their source; PRISM spans; `api.py`. | Wire the screens to the API; the workpaper viewer (a tick-mark opens the source line); the PDF export. **First merge to `main`.** |
| 2:20–3:10 | `fund/eval` with 60+ cases; v1 batch to PRISM → Root Cause → fix → v2 batch. | Insight writer, compliance filter and `lp-insights` traces; alert rules in PRISM, fired once on a real run and screenshotted. |
| 3:10–3:30 | Final merge, then **code freeze**. Run end to end from a clean start; seed the demo state. | Same. |
| 3:30–4:00 | Two rehearsals of the 4-minute demo script (spec). | Backup video; slides (problem, architecture, PRISM before/after, "insights, not advice"); update the `HACKATHON.md` checklist. |

**Cut in this order if we fall behind:** EDGAR 13F → PDF parsing of the bank statement (use the CSV) → Excel export → the
account mapper (use a fixed map) → the third insight (keep allocation and scenario).

**Never cut:** PRISM traces, the v1→v2 evaluation, the compliance filter, "every number from code."

## Rules (from CLAUDE.md, short version)

- No LLM math: agents call the typed tools and report only what they return.
- Every number on screen cites its source (document and line, or engine function).
- Insights, never advice: describe exposure against the LP's own targets; no "should", "recommend", "buy", "sell", "rebalance".
- Keys only in `.env` (ignored). Synthetic data only. Cap IQ data stays out of git and out of model prompts.

## Still open

1. Cap IQ access: Excel or screener exports, or the API?
2. Nicrron key and PRISM project id and key: needed before the 0:20 mark.
