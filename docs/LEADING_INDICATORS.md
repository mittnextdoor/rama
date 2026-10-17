# Leading Indicators — Capital IQ Pro Pull Spec (LP Risk Intelligence Layer)

As of: 2026-10-17 · Snapshot date for all pulls: **2026-10-16** (last full trading day)

## Purpose

Deterministic list of the market data we pull from S&P Capital IQ Pro to feed the LP risk insights agent. Combined with the fund accounting data from our close engine (capital accounts, loan tape, income split, LP policy limits), these inputs drive 14 fixed rules (R1–R14). The model only phrases rule outputs; it never computes numbers or gives investment advice.

Demo context: an LP in a synthetic private debt fund lending to AI infrastructure (data center developers, neoclouds, hyperscaler-leased facilities). The loan tape is synthetic; each synthetic borrower/tenant maps to one real public proxy below.

## Entity universe (17 tickers, fixed)

| Group | Tickers | Role |
|---|---|---|
| Tenants (T) | ORCL, MSFT, META, AMZN, GOOGL | Hyperscaler tenant proxies (loans L1, L6) |
| Borrowers (B) | CRWV, NBIS, APLD | Neocloud / developer borrower proxies (L2–L4) |
| Operators (O) | EQIX, DLR | Stabilized operator proxies (L5) and valuation comps |
| Chips (C) | NVDA, AMD | GPU product cadence / collateral obsolescence |
| BDC benchmark (P) | ARCC, OBDC, BXSL, FSK, MAIN | Public proxy for private credit stress |
| Macro (M, not companies) | UST 2y, 5y, 10y; SOFR | Rates regime |

Paste list for the Capital IQ Pro watch list "LP demo universe":

```
ORCL
MSFT
META
AMZN
GOOGL
CRWV
NBIS
APLD
EQIX
DLR
NVDA
AMD
ARCC
OBDC
BXSL
FSK
MAIN
```

## File rules

- **Location and name:** `data/capiq/<file>_2026-10-16.csv`
- **History window:** daily series 2025-10-01 → 2026-10-16; quarterly series = last 8 reported quarters
- **Format (long):** `ciq_id, ticker, company_name, date, field, value, unit, source_dataset`
- **Units:** spreads in bp; probabilities of default in %; money in USD millions; ratios as decimals
- **Missing data:** log in `data/capiq/MISSING.md` as `file | ticker | field | reason`. Rules skip missing inputs; never estimate.
- **Licensing:** pulled under our own S&P license. Keep `data/capiq/` in `.gitignore`; show derived cards, not raw S&P tables, in the public demo.

## Pull checklist

Priority: **P1** = needed for the hero demo · **P2** = sharpens cards · **P3** = if time allows

| # | File | Entities | Fields | Range | Feeds rules | Priority | Status |
|---|---|---|---|---|---|---|---|
| 1 | `entity_master` | T, B, O, C, P | Capital IQ company ID, ticker, legal name, ultimate parent, LEI, industry, country | Current | All joins | P1 | [ ] |
| 2 | `ratings_history` | T, B, O | S&P LT issuer rating, outlook, CreditWatch, action date, action type | Since 2024-01-01 | R3, R7, R11 | P1 | [ ] |
| 3 | `pd_market_signals_daily` | T, B, O, C | PD Model Market Signals 1-year PD | Daily, 12 mo | R3, R7, R11 | P1 | [ ] |
| 4 | `credit_scores_monthly` | T, B, O | RiskGauge score + implied PD; PD Model Fundamentals PD; CreditModel score | Month-end, 12 mo | R3, R11 | P1 | [ ] |
| 5 | `equity_daily` | T, B, O, C, P | Close, total return, market cap, 30-day volatility | Daily, 12 mo | R10, R3 context | P1 | [ ] |
| 6 | `key_developments` | T, B, O, C | Date, event type, headline, source link | 2026-04-01 → as-of | R4 | P1 | [ ] |
| 7 | `financials_quarterly` | T, B, O | Revenue, EBITDA, capex, CFO, FCF, total debt, cash, interest expense, net debt/EBITDA, EBITDA/interest, operating lease liabilities | Last 8 qtrs | R6, R7, tenant capacity | P1 | [ ] |
| 8 | `capital_structure` | B, O, ORCL | Per instrument: type, amount outstanding, coupon, maturity, secured/unsecured, facility type | Current | R7 | P1 | [ ] |
| 9 | `debt_maturities` | B, O, ORCL | Principal due by year: 2026, 2027, 2028, 2029, 2030, 2031+ | Current | R7 | P1 | [ ] |
| 10 | `rates_daily` | M | UST 2y, 5y, 10y yields; SOFR | Daily, 12 mo | R13, scenarios | P1 | [ ] |
| 11 | `default_study` | S&P Global Ratings | 1-year default rate by rating (AAA → CCC/C); avg recovery by debt type | Latest annual | R7 thresholds | P1 | [ ] |
| 12 | `cds_daily` | T (B if quoted) | 5-year CDS mid spread | Daily, 12 mo | R3 | P2 | [ ] |
| 13 | `bond_spreads_daily` | T, B | Per bond: ID, coupon, maturity, price, YTW, spread to Treasuries | Daily, 12 mo | R3, R10 | P2 | [ ] |
| 14 | `lease_commitments` | T | Operating lease liabilities; leases signed not yet commenced; purchase obligations | Last 4 qtrs | R2, R3 context | P2 | [ ] |
| 15 | `backlog_kpis` | B | RPO/backlog, contracted revenue, utilization, MW contracted & online | Last 8 qtrs | R6 | P2 | [ ] |
| 16 | `estimates` | T, B, C | Consensus FY26/FY27 capex, revenue, EBITDA; 90-day revision | Today + 90 days ago | R3 context | P2 | [ ] |
| 17 | `bdc_quarterly` | P | Non-accruals % at cost and FV; PIK % of investment income; NAV/share; price/NAV | Last 8 qtrs | R1 benchmark | P2 | [ ] |
| 18 | `dc_markets_451` | 3 collateral markets | Capacity MW, utilization %, under-construction MW, planned MW | Last 8 qtrs | R9 | P2 (451 add-on) | [ ] |
| 19 | `dc_facilities_451` | B and O facilities in those markets | Facility ID, owner, type, MW, status | Current | R8, R9 | P3 (451 add-on) | [ ] |
| 20 | `power_proximity` | Same 3 markets | Plants/projects within 25 mi: MW, fuel, status; regional power price forecast | Current | R8 | P3 | [ ] |
| 21 | `transcripts` | T, B | Last 2 earnings call transcripts | Last 2 qtrs | Card citations only | P3 | [ ] |

**Not from Capital IQ:** GPU rental index (H100/H200 on-demand and contract rates) for R5 — public tracker, labeled non-S&P. Loan tape and LP policy limits — synthetic, from our close engine.

**Order of work:** rows 1–11 first (covers R3, R4, R7, R10, R11 + thresholds). Then 12–17, then 18–21.

## How to pull (Capital IQ Pro)

Menu labels vary by version/license. If a menu isn't visible, use the top search bar; if still missing, it's likely unlicensed → log in `MISSING.md`.

**Setup:** create watch list "LP demo universe" (17 tickers above) · open the Excel plug-in and use **Formula Builder** to find fields by name · one Excel tab per file, saved as CSV · record the exact Capital IQ field/dataset name in `source_dataset`.

| # | Method | Steps |
|---|---|---|
| 1 | Screener | Company screen → list = LP demo universe → columns: company ID, ticker, name, ultimate parent, LEI, industry, country → download |
| 2 | Company page / Excel | Credit → Ratings → S&P issuer credit rating history → export (per ticker). Or Formula Builder "issuer credit rating" + "rating date" |
| 3 | Excel | Formula Builder "PD Model Market Signals" → 1-yr PD → daily 2025-10-01 → 2026-10-16. Fallback: Credit Analytics page → chart → export |
| 4 | Excel | Formula Builder "RiskGauge", "PD Model Fundamentals", "CreditModel" → month-ends, 12 mo |
| 5 | Excel / charting | Close, total return, market cap, 30-day volatility, daily |
| 6 | Screener (events) | Key Developments screen → list = LP demo universe → 2026-04-01 → as-of → all types → download |
| 7 | Company page / Screener | Financials → IS / BS / CF → quarterly → 8 periods → Excel; ratios page for leverage/coverage |
| 8 | Company page | Capital Structure → debt details → export instruments |
| 9 | Company page / filings | Capital Structure → maturity schedule; fallback: 10-K long-term debt note |
| 10 | Markets / econ data | Search "U.S. Treasury 2/5/10 year", "SOFR" → export. Fallback: FRED |
| 11 | Research (RatingsDirect) | Search "Annual Global Corporate Default And Rating Transition Study" → copy 1-yr default rates by rating; recovery study for recoveries |
| 12 | Company page / Excel | Fixed Income / Credit → CDS 5Y → export; or Formula Builder "CDS 5 year" |
| 13 | Company page | Fixed Income → pick 1–2 liquid senior bonds per issuer → pricing history → export |
| 14 | Filings | Latest 10-Q/10-K → search "lease", "purchase obligations" → copy amounts + page ref |
| 15 | Financials KPIs / filings | Segment/KPI data (Visible Alpha if licensed); fallback filings "remaining performance obligations", "backlog" |
| 16 | Company page | Estimates → consensus FY26/FY27 → capex, revenue, EBITDA; revisions view for 90-day change |
| 17 | Filings / Screener | BDC 10-Qs → "non-accrual", "payment-in-kind"; NAV/share from balance sheet; price/NAV = price ÷ NAV |
| 18 | 451 Data Center Research | Market data / Screener Data Center folder → 3 markets → capacity, utilization, pipeline → export |
| 19 | 451 Data Center Research | Facility screen or mapping tool → owners = B, O; 3 markets → export |
| 20 | Energy data / map | Power plant screen by state/county; map 25-mile radius; regional power forecast |
| 21 | Company page | Events → Transcripts → last 2 calls → download |

Tip: pull row 3 for one ticker first, check date format and PD units, fix the template, then fill the rest.

## What each indicator feeds (rules R1–R14)

Thresholds come only from the LP's policy, the fund's documents (covenants), or an LP-editable default (marked "default").

| Rule | Uses market data | Uses fund accounting | Fires when |
|---|---|---|---|
| R1 Income quality | Row 17 (benchmark) | PIK, non-accruals, cash vs. accrued interest, fund NAV | PIK + non-accrual ÷ NAV > LP watch limit, or cash ÷ accrued < 90% (default) |
| R2 Tenant concentration | Rows 1, 14 | Loan tenants, LP ownership share | Any tenant > LP single-tenant cap |
| R3 Tenant credit drift | Rows 2, 3, 4, 12, 13 | Loan → tenant map | PD ≥ 2x in 90 days, CDS +50 bp, or negative rating action (defaults) |
| R4 Tenant / project event | Row 6 (+ 20 for power events) | Loan → tenant / borrower / facility map | Force majeure, lease amendment, delay, missed payment, PIK election |
| R5 GPU collateral LTV | GPU rental index (non-S&P) | Drawn principal, appraisal, LTV covenant | Re-estimated LTV > covenant, or > 80% (default) |
| R6 Contract cover | Rows 7, 15 | Loan maturity, contract end dates | Uncovered term > 12 months (default) |
| R7 Refinancing wall | Rows 2, 3, 8, 9, 11 | Loan maturities, principal | Maturing ≤ 15 months with PD above S&P default-study rate for its rating band |
| R8 Power / construction delay | Rows 6, 19, 20 | Construction loans, commencement dates | Power shortfall flag or permit/pipeline event |
| R9 Market supply pressure | Rows 18, 19 | Collateral market | Pipeline ÷ existing capacity in top quartile of last 3 years (default) |
| R10 Valuation gap | Rows 5, 13 | GP marks, mark date | Comps move > 5% of mark since mark date, mark unchanged (default) |
| R11 Rating divergence | Rows 2, 3, 4 | GP internal risk grade | PD worse by ≥ 2 bands while internal grade unchanged |
| R12 LP liquidity | — | Unfunded, call pacing, distributions, LP liquidity floor | Net 12-month calls > LP floor |
| R13 Fund leverage headroom | Row 10 | Facility balance, borrowing base, covenants | Headroom < 15% (default) |
| R14 Covenant headroom | — | Covenant tests per loan | Headroom < 10% (default) |

## Guardrails (risk insight, never investment advice)

- Cards describe exposure, compare it to the LP's own limits, and show conditional scenarios ("if X, then Y"). Never: buy / sell / hold / commit / redeem / rebalance / reduce / increase, rankings of funds or products, or point forecasts of returns.
- Every number in a card must match a rule output; every card cites its sources and as-of dates.
- Language blocklist + classifier check on every card; blocked cards are rewritten once, then dropped. All checks traced in PRISM.
- "What should I do?" → fixed hand-off: risk analysis only; decisions sit with the LP and its advisers; show the GP's IR contact.
- Standing disclosure: "Risk analytics based on your fund's reported data and third-party market data as of the dates shown. Estimates depend on stated assumptions. Not investment advice."
