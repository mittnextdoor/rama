# RAMA — from a borrower's books to reviewed LP risk intelligence

Built at **MONEY TALKS 2** (Block Convey, New York, 17 October 2026), Money Operations track.

RAMA closes a portfolio company's month with agents, verifies every figure against its source, combines the verified
accounting with dated market evidence (S&P Capital IQ Pro), computes fourteen fixed leading-indicator rules, words one
risk card per fired rule, checks every card against two guardrails, and releases only what a person approves to an
LP reporting view. Every model call goes through **Nicrron**; every run is traced to **PRISM by Block Convey** through
its Agent Frameworks integration (OpenAI Agents SDK).

Insights, never advice. Deterministic code computes every number; the model only words what the rules computed.

## The demo path

1. **Close** — the agents close Helios Compute's September (a synthetic AI-infrastructure borrower; CoreWeave is its
   public proxy for market data only). They tie the bank and lender statements, record what the evidence supports with
   citations, and hold two items for a person: interest booked as paid in cash while the bank shows a smaller wire (the
   borrower's PIK election notice explains the gap), and a small fee nothing supports (it stays an exception).
2. **Intelligence** — verified figures plus the Cap IQ snapshot feed rules R1–R14. Ten fire; four are "not evaluated"
   because their data wasn't pulled (nothing is estimated). Each indicator is drawn from its own figures, with what-if
   sliders that are always labelled scenario, never rule output.
3. **Review & release** — one card per fired rule, written by an agent through Nicrron and checked by two output
   guardrails (every number must be a rule output; no advice: a blocklist plus a classifier). Approve cards or the
   package; the release carries only approved cards.
4. **Destination** — a Chronograph-style LP view, labelled "Demonstration destination — no live Chronograph connection".
5. **Execution** — PRISM's own status for the project and every run's steps.

## Run it

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # NICRRON_API_KEY, PRISMTRACE_API_KEY, PRISMTRACE_PROJECT_ID
# put the Cap IQ screen export at data/capiq/screen_snapshot_2026-10-16.xlsx (licensed; data/ is gitignored)
.venv/bin/python -m rama.api --port 8810      # http://127.0.0.1:8810
```

No database server is needed: the close runs on a local SQLite engine file and the workflow state is a JSON file,
both under `data/`. Tests: `.venv/bin/python -m unittest tests.test_rama tests.test_bob`.

## Where things are

| Piece | Where |
|---|---|
| RAMA: borrower books, close, metrics, fund, Cap IQ loader, rules, cards, pipeline, PRISM tracing, API, web app | `rama/` |
| The close engine (reconciliation, evidence, checks, fixes, workpapers) and the simulated ledger | `ops/native/`, `ops/qbo.py`, `ops/intake/` |
| Model providers (Nicrron), the agent runner's config and prompts | `product/reasoning/` |
| Bob: the earlier close-only build, its 72-case evaluation and PRISM tracing | `bob/`, `HACKATHON.md` |
| The product spec, the leading-indicator rules and the plans | `docs/` |
| The demo film (Remotion composition, capture script, shot list, narration) | `video/`, `docs/RAMA_FILM.md` |

## What is synthetic, what is real

- Synthetic: the borrower's books and statements, the lenders' statements, the fund's other loans, the facility, the LP
  and its policy. Nothing here is a real company's accounting.
- Real: the S&P Capital IQ Pro screen of 12 public companies (ratings, leverage, coverage, as of 2026-10-16), shown as
  derived signals; the file itself is licensed and not in the repository.
- Cited, outside S&P: the H100 rental index (Spheron, citing SemiAnalysis) and one public event (Bloomberg / Reuters).

Standing disclosure on every insight view: risk analytics based on the fund's reported data and third-party market
data as of the dates shown; estimates depend on stated assumptions; not investment advice.
