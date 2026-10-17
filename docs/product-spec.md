# Agentic Fund Accounting + LP Risk Intelligence — Product Spec

Oct 17, 2026 · @mit. This is the reference document for the project; the PDF it was written in is the same text.

## Problem statement

Private fund books are closed by hand, and LPs make risk decisions on data that is one to two quarters stale.

**For fund managers (GPs, fund CFOs, controllers, fund administrators):** the monthly close is a spreadsheet process. Staff pull
bank and custodian statements, tie them to the general ledger, allocate income, expenses and fees to each investor's capital
account, and build workpapers for auditors. It is slow, error-prone, and depends on a few people who know where everything lives.
Audit season becomes a scramble to reconstruct support after the fact.

**For limited partners (pensions, endowments, foundations, family offices, fund-of-funds):** private market exposure is visible only
through quarterly statements that arrive 45 to 90+ days after quarter end, with NAVs that lag public markets further still. When
public markets move, an LP cannot see how their real allocation, liquidity needs and concentration have shifted until months
later. The data that would tell them (capital accounts, unfunded commitments, call and distribution pacing) sits in each GP's
books, disconnected from market data.

**The gap:** the accounting system holds the most predictive data about an LP's position, and nobody connects it to live market
signals.

> **Problem statement (one paragraph):** Fund managers close their books with manual, spreadsheet-driven processes, and LPs see
> their private markets exposure only through quarterly statements that lag reality by months. When public markets move, LPs
> can't tell how their allocation, liquidity needs and concentration have shifted until long after the fact, so risk decisions
> are made on stale data. We automate the monthly close end to end and turn the resulting investor-level accounting data,
> combined with live public market signals, into a current, portfolio-specific risk view for every LP.

## Solution and positioning

One platform, two layers: an agentic close engine for GPs, and a risk insights layer for LPs built on the data the close produces.

1. **Close engine (GP side).** The fund uploads or connects its books, bank and custodian statements, and investor register.
   Agents map, reconcile and allocate; a deterministic calculation engine computes every number; the platform outputs
   reconciliations, investor capital account statements and audit-ready workpapers each month.
2. **LP risk insights (LP side).** The closed, investor-level data is combined with public market signals to show each LP their
   current estimated exposure, liquidity runway, concentration and stress scenarios, measured against the LP's own policy targets.

**Positioning: insights, not advice.** The product is portfolio risk analytics. It describes exposure, measures it against the
user's own rules, and shows consequences under scenarios. It never tells an LP to buy, sell, commit to or redeem from any fund or
security, and never ranks investment products. Any conversation about what to do next happens between the LP and the GP's
investor relations team (usually a registered adviser), outside the tool.

**Why us:** the insight layer depends on monthly, investor-level accounting data that only the fund's books hold. Public-data
analytics vendors can't replicate it; accounting tools don't use it.

## Users and buyers

The GP's fund CFO buys the product; the LP is the end user of the insight layer, delivered through the GP's portal.

| Persona | Role in product | What they need | Pays? |
|---|---|---|---|
| Fund CFO / controller | Buyer, primary user of close engine | Faster close, fewer errors, clean audit | Yes (core subscription) |
| Fund accountant / admin staff | Daily user | Exceptions queue, mapping review, workpaper sign-off | No |
| GP investor relations | Buyer of insight layer | LP retention, earlier read on LP liquidity stress, better LP conversations | Yes (add-on per LP seat or per fund) |
| LP portfolio / risk team | End user of insights | Current exposure, liquidity runway, concentration vs. own targets | No at launch; later a paid cross-GP view |
| External auditor | Recipient of workpapers | Tick-marked support tied to source documents | No |

Start with emerging and mid-size managers (roughly $100M to $2B AUM) who run the close in-house or with a thin administrator,
since they feel the pain most and buy fastest.

## Product modules

Five modules: ingestion, close engine, workpaper builder, signal layer and LP insights portal.

### 1. Ingestion

- Upload trial balance / GL export (CSV, Excel), bank and custodian statements (PDF, CSV), capital call and distribution notices,
  investor register and commitments.
- Later: direct connectors to accounting systems (QuickBooks, NetSuite, Investran-style fund ledgers), bank feeds and
  administrator portals.
- Agent classifies each document, extracts fields, and maps GL accounts to a standard fund chart of accounts. Low-confidence
  mappings go to a human review queue.

### 2. Close engine

A fixed monthly checklist the agents run, each step producing an output and an exception list:

1. **Cash reconciliation:** bank and custodian balances vs. GL cash; unmatched items flagged.
2. **Investment reconciliation:** positions and cost basis vs. custodian / portfolio company records.
3. **Capital activity:** calls and distributions in the GL vs. notices sent, by investor.
4. **Accruals:** management fees (on commitments or invested capital, with offsets), fund expenses, interest.
5. **Investor allocations:** income, expense, realized and unrealized gains allocated pro rata to capital accounts, honoring
   side letters and excused investors.
6. **Carried interest accrual:** hypothetical liquidation through the waterfall (return of capital, preferred return, catch-up,
   split).
7. **NAV and capital account roll-forward:** beginning balance + contributions − distributions ± allocations = ending balance,
   for every investor.
8. **Variance analysis:** month-over-month flux on key lines with agent-drafted explanations.

### 3. Workpaper builder

- One workpaper per checklist step: lead schedule, supporting detail, tick-marks linking every number to its source document and page.
- Preparer / reviewer sign-off fields with timestamps; exceptions must be cleared or explained before sign-off.
- Export as PDF and Excel binder in the format auditors expect for PBC requests.

### 4. Signal layer

- **Public market data:** index levels and returns, sector ETFs, public comparables for portfolio companies, credit spreads, rates.
- **Regulatory filings:** 13F holdings (institutional positioning, crowding), Form D (fundraising), Form ADV (manager changes),
  FINRA short interest.
- **LP-side public disclosures:** public pension board minutes, asset allocation reviews and commitment approvals.
- **Licensed data (customer-entitled only):** PitchBook, Bloomberg, Preqin, accessed through the customer's own license.

### 5. LP insights portal

Each LP sees only their own position, refreshed monthly after close and marked to market daily where possible:

| Insight | Accounting input | Market input | Example output |
|---|---|---|---|
| Estimated current allocation | Last reported NAVs | Public comps / index moves since mark date | "Estimated private equity weight 23.8%, vs. 21.5% reported" |
| Denominator drift | Private NAV, commitments | Public book value, drawdown scenarios | "At −15% public equities, PE weight reaches 26.1% vs. your 20% target" |
| Capital call stress | Unfunded commitments, call pacing by fund | Stress scenarios, credit spreads | "Calls over next 4 quarters: $38M base, $52M stressed" |
| Distribution shortfall | DPI, distribution history | Exit volumes, IPO / M&A activity | "Expected distributions 40% below 3-year average" |
| Liquidity runway | Calls minus distributions | Scenario-adjusted exits | "Net cash need exceeds your liquidity floor in Q3 under stress" |
| Hidden concentration | Look-through holdings across funds | Sector / factor exposure | "Software is 31% of look-through exposure across 4 funds" |
| Valuation gap | Portfolio company marks | Public comparable moves | "Comparables down 12% since last mark" |

Example outputs are illustrative placeholders, not real figures.

## Technical architecture

Five layers: inputs, an agent layer, a deterministic calc engine, a tenant-isolated data store, and two front ends.

```
GP books and documents                      Market and filing data
(trial balance, bank/custodian statements,  (index and comparable prices, credit spreads,
 capital notices, investor register)         SEC EDGAR 13F and Form D, licensed feeds)
            │                                            │
            ▼                                            ▼
Agent layer (Claude with tool use; humans approve)
  Close agents: intake, GL mapping, recons, workpaper writer, orchestrator
  Signal collector: prices, spreads, EDGAR filings, licensed feeds (customer's)
  Insight writer: plain-language risk cards, compliance filter on wording
            │ typed tool calls and results
            ▼
Deterministic calc engine (Python, unit-tested)
  Recons, fees, pro rata allocations, waterfall, capital roll-forward, NAV estimates, scenarios
  Agents may only report numbers this engine returns
            │ reads and writes
            ▼
Postgres and document store
  Tenant-isolated funds, investors, GL, capital accounts, market signals, LP policy targets
  Every number links to its source document; periods lock after close
            │                                            │
            ▼                                            ▼
GP close workspace                          LP insights portal
  Recons, exception queue, sign-off           Allocation, liquidity, concentration
  Audit-ready workpapers (PDF, Excel)         Scenarios vs. the LP's own targets
```

Agents never compute; they call the engine's typed functions and report what it returns, and every stored number links back to
a source document.

| Layer | Component | Production choice | Hackathon choice |
|---|---|---|---|
| Front end | GP close workspace, LP insights portal | Next.js, TypeScript, role-based views | Next.js + Tailwind + shadcn/ui, Recharts |
| API | REST + background jobs | FastAPI, Celery or Temporal for the close workflow | FastAPI, synchronous runs |
| Agents | Orchestrator + specialist agents | Claude API with tool use, prompt caching, eval suite per agent | One orchestrator prompt with typed tools |
| Calc engine | Recons, fees, allocations, waterfall, NAV estimates, scenarios | Python package, property-based tests, versioned fund terms | Python functions + pytest |
| Document processing | Classification, extraction, workpaper rendering | OCR for scans, PDF parser, structured extraction with confidence scores | pdfplumber + Claude extraction, WeasyPrint |
| Data | Relational store, file store, audit log | Postgres with row-level security, S3, append-only event log | Supabase Postgres + storage |
| Signals | Market data, filings, licensed feeds | Licensed market data API, SEC EDGAR, entitlement-aware vendor connectors | Free price API, EDGAR JSON |
| Security | Auth, isolation, compliance | SSO, encryption, SOC 2 / SOC 1 | Supabase auth, demo tenants |

## Data model

Twelve core tables in Postgres; every computed number links back to the source rows and documents that produced it.

| Table | Key fields | Notes |
|---|---|---|
| `fund` | id, name, vintage, strategy, currency, fee_terms, waterfall_terms | Terms stored as structured JSON the calc engine reads |
| `investor` | id, name, type, tax_status | One record per LP entity |
| `commitment` | fund_id, investor_id, amount, side_letter_terms | Drives pro rata share and fee basis |
| `gl_account` | fund_id, code, name, mapped_standard_account, mapping_confidence | Agent-proposed mapping + human approval |
| `journal_entry` | fund_id, date, account, amount, source_document_id | Immutable once period is locked |
| `source_document` | id, type, file_uri, hash, extracted_fields | Every number traces to a document and page |
| `capital_activity` | fund_id, investor_id, type (call / distribution), date, amount | Reconciled to notices |
| `position` | fund_id, company, cost, fair_value, mark_date, sector, public_comp_tickers | Comp tickers feed the valuation gap insight |
| `period_close` | fund_id, period, status, locked_at, reviewer | Draft → in review → locked |
| `recon_result` | close_id, step, expected, actual, difference, status, explanation | One row per reconciliation check |
| `capital_account` | close_id, investor_id, beginning, contributions, distributions, allocations, carry, ending | The core LP data asset |
| `market_signal` / `lp_policy` | ticker / series, date, value; investor_id, target weights, liquidity floor, concentration limits | Signals are shared reference data; policy targets are entered by the LP |

**Isolation:** each GP is a separate tenant (row-level security keyed on tenant_id). An LP's view joins only their own capital
accounts across the funds where they are invested and the GP has enabled sharing.

## Agent design and guardrails

Agents read, map, explain and draft; deterministic code computes every number; humans approve every locked output.

| Agent | Job | Tools it calls | Output | Human checkpoint |
|---|---|---|---|---|
| Orchestrator | Runs the monthly close checklist, routes work, tracks status | All agents, close state machine | Close status, exception queue | Starts and locks the close |
| Document intake | Classify and extract fields from statements and notices | OCR / PDF parser, schema validator | `source_document` rows with confidence scores | Review fields below confidence threshold |
| GL mapper | Map client accounts to the standard fund chart | Chart-of-accounts lookup, prior mappings | Proposed mappings | Approve new or changed mappings |
| Reconciler | Run each recon step, match items, investigate breaks | Calc engine, matching functions, document search | `recon_result` rows + break explanations | Clear or accept each break |
| Workpaper writer | Assemble schedules, tick-marks, narrative | Template renderer, calc engine outputs | PDF / Excel workpapers | Preparer and reviewer sign-off |
| Signal collector | Pull and normalize market and filing data on schedule | Market data APIs, EDGAR, licensed connectors | `market_signal` rows | None (reference data), monitored for gaps |
| Insight writer | Turn calc engine risk metrics into plain-language insight cards | Risk metric functions, LP policy, compliance filter | Insight cards per LP | GP IR can review before release |

**Guardrails:**

- **No LLM math.** Agents call typed functions (`compute_management_fee`, `run_waterfall`, `allocate_pro_rata`,
  `estimate_current_nav`) and may only report numbers those functions return. Outputs are validated so any number in agent text
  must match a function result.
- **Evidence required.** Every reconciliation explanation and workpaper line cites a source document id and page.
- **Period locking.** Once a close is locked, journal entries and capital accounts are immutable; corrections post as adjustments
  in the next period with an audit trail.
- **Compliance filter on insights.** A rules layer blocks prescriptive language ("should", "recommend", "buy", "sell",
  "rebalance into", fund or product names as suggestions) and a classifier checks each insight card is descriptive. Blocked cards
  are rewritten or dropped and logged.
- **Full logging.** Every agent prompt, tool call, output and human decision is stored for audit and regulatory review.

## Compliance and data rights

The insight layer stays outside the investment adviser definition by being descriptive, measured against the LP's own targets,
and free of transaction-based compensation; securities counsel should confirm before launch.

**Investment advice boundary**

- Describe exposure and consequences; never recommend actions or rank funds, securities or vehicles.
- Measure deviations against policy targets the LP enters, not targets the product sets.
- No fees tied to any secondary sale, commitment or transaction that follows an insight.
- Route any "what should we do" conversation to the GP's IR team (registered adviser) outside the tool, under the GP's own disclosures.
- Standard disclosure on every insight view: analytics only, estimates based on stated assumptions, not investment advice.

**Data rights**

- **LP data in GP books:** governed by the LPA and side letters. GP must enable LP portal sharing; each LP sees only their own
  accounts. No cross-GP pooling of identifiable LP data.
- **Licensed data (PitchBook, Bloomberg, Preqin):** used only through the customer's own entitlement, inside that customer's
  tenant, with no redistribution or cross-customer derived data. Confirm each vendor's terms on AI processing before building the
  connector.
- **Public data:** SEC EDGAR filings and public pension documents are public, but respect EDGAR's fair access rules (declared
  user agent, rate limits).

**Security:** SOC 2 Type II for the platform, and SOC 1 Type II once fund administrators or auditors rely on the close outputs.
Encryption at rest and in transit, SSO, role-based access, tenant isolation.

## Hackathon MVP

Build one end-to-end slice in 24 to 48 hours: upload a fund's month-end files, get a reconciled close and a workpaper, then see
three live risk insights for one LP.

**Demo name idea:** "Close to Insight": from raw books to an LP risk view in under five minutes.

### Scope: in and out

| In the MVP | Out (say "on the roadmap" if asked) |
|---|---|
| One synthetic PE fund, 5 LPs, 8 portfolio companies, one month | Multiple funds, multi-currency, real client data |
| Uploads: trial balance CSV, bank statement PDF, capital call notices, investor register | Live accounting / bank connectors |
| 3 recon steps: cash, capital activity, capital account roll-forward | Full 8-step close, carry waterfall, side letters |
| Management fee calc (on commitments, flat %) | Fee offsets, tiered fees |
| 1 workpaper PDF with tick-marks linking to source docs | Full audit binder, reviewer workflow |
| LP view with 3 insights: estimated current allocation, denominator drift scenario, capital call stress | Concentration look-through, distribution forecasts, licensed data |
| Free public data: index / comp prices, one 13F pull from EDGAR for context | Bloomberg / PitchBook connectors |
| Compliance filter on insight text | Formal compliance review |

### Tech stack

- **Frontend:** Next.js + Tailwind + shadcn/ui; Recharts for the scenario charts.
- **Backend:** Python FastAPI; pandas for calcs; Pydantic models for every tool input and output.
- **Database:** Postgres (Supabase for speed) or SQLite if time is tight.
- **Agents:** Claude API with tool use. One orchestrator prompt with typed tools; no agent framework needed.
- **Documents:** pdfplumber for text PDFs; Claude for field extraction into a Pydantic schema; WeasyPrint or ReportLab to render
  the workpaper PDF.
- **Market data:** a free price API or yfinance for index and comparable prices (check terms for demo use); SEC EDGAR JSON
  endpoints for one 13F.
- **Deploy:** Vercel (frontend) + Render or Fly.io (API).

### Tools the agent can call

```
extract_document(file_id) -> fields + confidence
map_gl_accounts(trial_balance) -> proposed mappings
reconcile_cash(gl_cash, bank_statement) -> matched, unmatched, difference
reconcile_capital_activity(gl_entries, notices) -> breaks by investor
compute_management_fee(fund_terms, commitments, period) -> fee by investor
roll_forward_capital_accounts(period) -> beginning, activity, ending by investor
render_workpaper(step, results, sources) -> pdf_uri
estimate_current_nav(positions, comp_prices) -> estimated NAV, change since mark
run_scenario(lp_id, public_shock_pct) -> allocation vs targets, call stress
```

All math lives in these Python functions with unit tests. The agent orchestrates, explains breaks and writes the narrative.

### Build plan (24-hour version)

| Hours | Workstream A (backend / agents) | Workstream B (frontend / data) |
|---|---|---|
| 0 to 3 | Schema, synthetic fund generator with 2 planted breaks | Repo, UI shell, upload page |
| 3 to 8 | Calc functions + tests (recons, fee, roll-forward) | Close dashboard: checklist, status, exception list |
| 8 to 12 | Agent loop with tools; document extraction | Workpaper viewer with clickable tick-marks |
| 12 to 16 | Workpaper PDF render; market data + EDGAR pull | LP portal: allocation card, scenario slider, call stress chart |
| 16 to 20 | Insight writer + compliance filter; NAV estimate | Policy target input; polish |
| 20 to 24 | End-to-end run, fix bugs, seed demo, rehearse | Pitch slides, recording backup video |

With 48 hours, add the concentration look-through insight and a second fund so the LP view aggregates across funds.

### Demo script (4 minutes)

1. **Problem (30 s):** a controller spends 10 days a month in spreadsheets; LPs see their exposure a quarter late.
2. **Upload (30 s):** drop the month's files into the fund.
3. **Close runs (60 s):** checklist ticks through live; the agent flags the two planted breaks (an unrecorded wire, a capital call
   booked to the wrong LP) and explains each with the source document.
4. **Workpaper (30 s):** open the PDF; click a tick-mark to jump to the bank statement line.
5. **LP view (60 s):** switch to an LP's portal. Show estimated current allocation vs. reported, then drag the scenario slider to
   −15% public equities and watch the PE weight cross the LP's own 20% target and the call stress chart move.
6. **Close (30 s):** "Every number comes from tested code, every insight is descriptive and measured against the LP's own rules,
   and only the fund's books can produce this view."

### Judging risks and mitigations

- **Live demo fails:** pre-run the close and keep a recorded video.
- **"Is this investment advice?":** have the one-line answer ready (descriptive analytics against the LP's own targets, no
  recommendations, no transaction fees).
- **"Where does the data come from?":** synthetic fund data, public market prices, SEC EDGAR; licensed data is roadmap, under the
  customer's own license.

## Roadmap and open questions

Sell the close engine first; the insight layer becomes valuable once enough funds close on the platform.

1. **Phase 1, close engine:** full 8-step close for PE and VC funds, carry waterfall, side letters, auditor-ready binders. Design
   partners: 3 to 5 emerging managers. Gate: one clean audit cycle using platform workpapers.
2. **Phase 2, LP insights in the GP portal:** the seven insights, scenario tool, IR review queue. Gate: securities counsel sign-off
   on the insight design.
3. **Phase 3, data depth:** connectors to accounting systems, administrators and banks; entitlement-aware PitchBook / Bloomberg /
   Preqin connectors; public pension disclosure parser.
4. **Phase 4, cross-GP LP view:** an LP sees all their funds across every GP on the platform, with GP consent. This is the network
   effect and the largest prize.
5. **Phase 5, adjacent strategies:** private credit, real estate, fund-of-funds and secondaries funds.

**Open questions**

- [ ] Sell direct to GPs, or partner with fund administrators who run closes for many GPs?
- [ ] Does the LP see insights in the GP's portal only, or in a standalone LP view across GPs?
- [ ] Pricing: per fund per month, per AUM tier, or per LP seat for the insight layer?
- [ ] Which licensed data vendors permit AI processing under existing customer licenses?
- [ ] Is a registered adviser affiliate ever needed, or can the product stay purely analytics?
