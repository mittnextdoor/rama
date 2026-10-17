# The intelligence layer: from the fund's closed books to LP risk cards

This replaces the build order in [PLAN.md](PLAN.md). The spec is [product-spec.md](product-spec.md); the market-data pull
and the rules R1–R14 are [LEADING_INDICATORS.md](LEADING_INDICATORS.md). Nothing below is built yet.

## Status (main at 66cd80d)

**Built:** the close engine (Bob). It reads the books, ties bank statements and **lender statements** to the ledger, fixes
what it can cite, and builds a workpaper for every balance-sheet account (tied / exception / unsupported, each with its
source). It produces the balance sheet, P&L and cash flow (`ops/native/read.statements`). Every model call goes through
Nicrron (verified live 2026-10-17).

**Not built:** anything in the intelligence layer: no Cap IQ loader, no loan tape, no capital accounts, no rules, no LP
cards, no compliance filter, no LP portal.

**PRISM:** today's tracing posts to PRISM's HTTP endpoints. The hackathon requires one of the dashboard's Connectors
cards, so this plan moves to the **Agent Frameworks** card (below). No trace has reached PRISM yet: the `pt-sk-` key is
still needed.

## The flow

```
Fund's books (synthetic private debt fund: loans L1–L6, interest, PIK, credit facility, partners' capital)
   │  CLOSE (Bob, built): bank recon, credit facility tied to the lender's statement, a workpaper per account
   ▼
Closed month: statements + workpaper status + exceptions
   │  FUND EXTRACT (new): loan tape, income split (cash / accrued / PIK), capital accounts, facility headroom
   │  only from accounts whose workpaper is tied; anything else is "unverified" and its rules don't fire
   ▼
Cap IQ snapshot (new loader)  data/capiq/*_2026-10-16.csv, long format, MISSING.md respected (never estimate)
   │
   ▼
RULES R1–R14 (new, deterministic Python, unit-tested)
   each returns: fired?, metrics, threshold and where it came from (LP policy / fund document / default),
   inputs with source and as-of (Cap IQ file + row, or workpaper id), missing inputs
   ▼
LP RISK AGENT (new, OpenAI Agents SDK, model through Nicrron)
   tools: run_rules, rule_detail, sources   ·   writes one card per fired rule
   output guardrails: (1) every number in the card equals a rule output; (2) blocklist + Nicrron classifier
   blocked → rewritten once → dropped and logged; "What should I do?" → fixed hand-off text
   ▼
LP portal: cards with sources and as-of dates, the standing disclosure; GP view: the same cards before release
```

## PRISM: the Agent Frameworks card (OpenAI Agents SDK)

Why this card: the Model Providers and Zero-Code Proxy cards both replace the client's base URL with PRISM's
proxy, which only forwards to Anthropic, OpenAI or Gemini, so Nicrron would drop out of the path. The Agents SDK takes
any OpenAI-compatible client, so the model stays on Nicrron, and PRISM's `install_openai_agents` captures the
agent's runs, tool calls, guardrails and model generations.

```python
from openai import AsyncOpenAI
from agents import Agent, Runner, OpenAIChatCompletionsModel, set_tracing_export_api_key
from prismtrace import install_openai_agents
import prismtrace

install_openai_agents(api_key=PRISMTRACE_API_KEY, project_id=PRISMTRACE_PROJECT_ID)
nicrron = AsyncOpenAI(base_url="https://api.nicrron.ai/v1", api_key=NICRRON_API_KEY)
model = OpenAIChatCompletionsModel(model=NICRRON_MODEL, openai_client=nicrron)
agent = Agent(name="lp-risk", instructions=..., model=model, tools=[run_rules, rule_detail, sources],
              output_guardrails=[numbers_match_rules, no_advice])
with prismtrace.session(f"{fund}-{period}"):          # the same session as the fund's close
    result = await Runner.run(agent, f"Risk cards for {lp_id} as of 2026-10-16")
```

- **The close joins the same card.** `bob/trace.py` keeps its API (`run`, `ensure_run`, `step`), but each step becomes
  an Agents SDK span (`trace(...)` for a run, `function_span` for a tool step, `generation_span` for a model call)
  instead of an HTTP post. The deterministic close then shows in PRISM as tool spans, under the same session as the
  LP agent. The local run records in `data/bob/runs/` stay.
- **Gate 0, before anything else:** a short probe with the key. It sends one Agents SDK run (one Nicrron generation +
  one custom function span) inside `prismtrace.session`, then checks `GET /api/setup-doctor` for `live_connected: true`
  and the custom span visible in the Steps view. If custom spans don't show, the close's model calls move to
  **LiteLLM** (`install_litellm`, same Agent Frameworks card; `litellm.completion(model="openai/<id>",
  api_base=Nicrron)`) and the deterministic steps become the LP agent's and the close agent's tool calls.
- Turn off the Agents SDK's default OpenAI trace exporter (only PRISM's processor), so no OpenAI key is needed.
- **Alerts:** `error_rate` on the `lp-risk` agent (a guardrail tripped); `error_rate` on the close.

## The fund's books (what the close reads)

Synthetic private debt fund, one month (September 2026), loaded as a simulated QuickBooks company so the existing
close runs unchanged:

| Account | Tied by the close to |
|---|---|
| Cash (operating) | the bank statement (built) |
| Credit facility payable | the lender's statement: balance, borrowing base, covenant (built: lender statement tie) |
| Loans receivable L1–L6 | the servicer's loan tape (new evidence type, same workpaper shape) |
| Interest receivable / PIK interest receivable | the servicer report's accrued and PIK columns |
| Interest income: cash / PIK | the month's activity |
| Partners' capital LP1–LP5 | capital calls and distributions in the notices |

Loan terms that aren't ledger balances (maturity, coupon, covenants, LTV, tenant and borrower proxy tickers, contract
end dates, GP internal grade, mark and mark date) live in `fund/terms.json`, synthetic and versioned. LP policies
(single-tenant cap, watch limit, liquidity floor) live in `fund/lp_policy.json`, entered by the LP.

Planted for the demo (each traceable to a rule): a CRWV-proxy borrower whose PD doubled in 90 days (R3), a loan maturing
inside 15 months above the default-study rate (R7), PIK rising in the income split (R1), an unchanged mark while comps
fell (R10), facility headroom near covenant after a SOFR move (R13), and an LP whose net 12-month calls exceed its
floor (R12). Plus one close exception (an unrecorded interest receipt) so an "unverified" input is shown being held back.

## Rules in scope

- **Hero demo (Cap IQ rows 1–11 + accounting):** R1, R2, R3, R4, R7, R10, R11, R12, R13, R14.
- **If P2 rows arrive:** R6 (row 15), R3 with CDS (row 12), R1 benchmark (row 17).
- **Out unless data shows up:** R5 (GPU index), R8, R9 (451 add-on).

Each rule is one function `rule_rN(inputs) -> RuleResult` with tests, including a "missing input → skipped, never
estimated" test.

## Evaluation (for PRISM's Root Cause story)

50+ cases: the fund fixture with variations (rule thresholds crossed or not, missing Cap IQ fields, an unreconciled
account, a card prompt that pulls toward advice). The expected outcome per case: which rules fire, which are skipped and why, no
blocked wording reaching the LP, every card number equal to a rule output. Run v1 → PRISM groups the failures →
fix → v2 on the same cases. The close's existing 72-case evaluation is re-run under the new tracing too.

## Who does what

| Block | A (Mitt + Claude): tracing, books, rules, agent | B (partner + Claude): Cap IQ, loader, screens |
|---|---|---|
| 1 | PRISM key → Gate 0 probe (Agents SDK + Nicrron) → LIVE CONNECTED. Switch `bob/trace.py` to Agents SDK spans. | Cap IQ rows 1–11 (watch list, Formula Builder), saved to `data/capiq/` in the long format; `MISSING.md`. |
| 2 | Fund books fixture (simulated company + terms + LP policy); close it with Bob; fund extract (loan tape, income split, capital accounts, headroom) | `intel/capiq.py` loader: schema check, units, as-of, MISSING.md; `intel/fixtures` for screens. LP portal and GP card view against mock JSON. |
| 3 | Rules R1–R4, R7, R10–R14 + tests; LP risk agent (Agents SDK, tools, two output guardrails) | Wire screens to `/api/intel/lp/{id}` and `/api/intel/fund/{period}`; disclosure; "What should I do?" hand-off; PRISM alert rules |
| 4 | Evaluation v1 → Root Cause → fix → v2; end-to-end from the books to the cards; **code freeze** | Rehearsal, backup video, slides (problem, flow, PRISM before/after, "risk insight, never advice") |

Cut order if behind: R14 → R11 → R2 → the fund-extract evidence types (use the trial balance directly, marked) → the
GP review screen. Never cut: the close feeding the rules, numbers only from rules, the guardrails, PRISM live.

## Demo (4 minutes)

1. The fund's month-end files go in; Bob closes the month: cash and the credit facility tie; one interest receipt is an
   exception and its input is held back.
2. The intelligence layer reads the closed month and the Cap IQ snapshot (as of 2026-10-16): six rules fire.
3. The LP portal: cards for R3 (borrower PD doubled), R7 (refinancing wall), R12 (net calls over the LP's floor), each
   with its sources and as-of dates; the disclosure; "What should I do?" gets the hand-off.
4. PRISM: the close and the LP agent in one session; tool spans; a guardrail that blocked an advisory sentence; v1 → v2.
