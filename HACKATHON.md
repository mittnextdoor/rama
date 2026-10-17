# Bob at MONEY TALKS 2: setup, what's verified, the demo, and what's left for you

Written 2026-10-17 from the state of this repository. Everything marked **verified** was run here; everything marked
**outstanding** needs a credential or a dashboard this build didn't have. Nothing below claims PRISM or Nicrron received
anything: no key was available during the build, and the code never says "received" without an HTTP 2xx and an id.

## 1. What the repository is, and what was reused

| Layer | What it is | Reused as is? |
|---|---|---|
| Engine `ops/native/` | read (snapshot, fingerprint), reconcile (statement ↔ register matching), evidence (statements, lender statements, payroll from the intake), checks (unrecorded lines, duplicates, uncategorized, the client's own messy entries, patterns, schedules, continuity, flux), fixes (one verified QuickBooks transaction per fix, read back), workpapers (every balance-sheet account, cash flow) | Yes. Two targeted changes in `checks.py` for v2 (`bob/eval/CHANGES.md`); one hook file `ops/native/trace.py` |
| Adapter `ops/qbo.py` | `SimulatedQBO` (a QuickBooks company on disk) and `LiveQBO` (Intuit's API) | Yes; the demo uses the simulated company, live posting stays off |
| Product `product/` | FastAPI on Postgres: clients, months, jobs and the worker, the close (`nativeclose.py`), the workflow and review screens' API, reasoning agents (`product/reasoning/`: Anthropic provider, runner with gates, cache, retries, validation) | Yes; `providers.py` gains `NicrronProvider` and the hackathon switch; `nativeclose.py` is traced; six read-only `/api/bob/*` routes |
| Web `web/` | Next.js static export served by the API: the firm workspace, the client workspace (Close, Documents, Ledger, Reconciliations, Schedules, Review, Reports), the review workbench | Yes; one new page `web/app/firm/bob/` and a nav entry |
| Tests | The Python suite on a disposable Postgres database; Playwright browser tests | Yes; the practice's website and acquisition tests were removed with their code |

The strongest end-to-end workflow is the **ledger-native monthly close with the balance-sheet workpapers**: that is what Bob
runs. The rebuild engine (`ops/books/`) is frozen and not part of the demo.

## 2. Setup

Requirements: PostgreSQL (a local server with `createdb`), Python 3.12+ (built on 3.14), Node 20+.

```
git clone <this repository> && cd bob
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
createdb nhb_cc_bob
cp .env.example .env            # keys go here, never in the repository
(cd web && npm ci && NEXT_PUBLIC_BRAND=Bob npx next build)
.venv/bin/python scripts/bob_dev.py reset
.venv/bin/python scripts/bob_dev.py serve          # http://127.0.0.1:8790/firm/bob/
```

`scripts/bob_dev.py` reads `.env`, refuses any database not named `nhb_cc_*`, runs the API with an in-process worker and sets
`BOB_RUNS_DIR` under the demo folder. Port: `--port 8791` if 8790 is taken.

Environment (see `.env.example`):

| Variable | Meaning |
|---|---|
| `BOB_HACKATHON=1` | Hackathon mode: every agent through Nicrron with `NICRRON_API_KEY`; an Anthropic key is never used as a stand-in; no direct provider call |
| `NICRRON_API_KEY`, `NICRRON_MODEL`, `NICRRON_BASE_URL` | The key (`sk-af-…`), the model id for agents whose configured model is an Anthropic id (default `anthropic/claude-haiku-5-5`; any id from nicrron.ai/docs/models or `nicrron/auto`), the endpoint |
| `NICRRON_STRUCTURED` | How the agents' JSON answer is asked for: `prompt` (default: schema in the system prompt, JSON parsed and validated by code), `json_schema` (OpenAI `response_format` strict), `json_object` |
| `PRISM_API_KEY`, `PRISM_PROJECT_ID`, `PRISM_HOST` | PRISM's key (`pt-sk-…`, header `X-PRISMtrace-Key`), the project UUID (Settings → Project), the host |
| `PRISM_AGENT_ID`, `PRISM_AGENT_NAME` | The stable agent identity (`bob-close`) alert rules scope to, and its display name |
| `BOB_RUNS_DIR` | Where each run's record is written (default `data/bob/runs/`, ignored by git) |
| `BOB_V1=1` | Replays Bob v1's accounting behaviour (to reproduce the baseline batch) |

Tests: `NHB_PRODUCT_TEST_DATABASE_URL=postgresql:///nhb_cc_tests .venv/bin/python -m unittest discover -s tests -t .` after
`createdb nhb_cc_tests` (the suite refuses any other database; a missing one silently skips the product tests).

## 3. How the integrations work

### Nicrron (`product/reasoning/providers.py`)

- `provider(name)` returns `NicrronProvider` for every agent when `BOB_HACKATHON=1`, whatever `config/agents.json` names;
  `secrets.credential()` then only ever returns `NICRRON_API_KEY`. Off, the product behaves as before (Anthropic, per-agent keys).
- `complete()` posts OpenAI chat completions (`model`, `messages`, `max_tokens`, `temperature`) and parses the JSON object in
  the answer; `converse()` translates the assistant's Anthropic content blocks (text, tool_use, tool_result) to OpenAI
  `tools`/`tool_calls` and back. Retries are the runner's (bounded, on 429/5xx/timeouts with retry-after); a cut-off answer or a
  refusal stops. Every call, including each failed attempt, is an `llm` step of the current run with model and tokens.
- Streaming isn't used anywhere in the product (every agent answers in one structured message), so none was added.
- Nicrron's documented caching (temperature 0 → cached answer, `X-Nicrron-Cache: HIT`) applies to the classifier (temperature 0).

### PRISM (`bob/trace.py`)

- A run opens around a workflow (`trace.run(...)`), each real step inside is `trace.step(name, kind, input)` with `out()` /
  `error()`; the engine reports its own steps through the `ops/native/trace.py` hook. Kinds used: `tool`, `llm`, `agent`,
  `chain`, `retrieval` (the values the official SDK emits).
- `finish()` writes the run's record locally, then (when configured) posts three documented payloads from a background thread
  and waits for them: `POST /api/traces` (trace_id = run id, session_id, agent_id, model, latency, tokens, metadata with
  fixture id/version, Bob's version, step and error counts), `POST /api/spans/ingest` (every step with parent, times, status,
  error_message, model and tokens) and `POST /api/trajectories` (the SDK's trajectory shape, `final_status` success|error).
  Each answer's status and body are kept on the run; "received" is true only when all three stored (2xx) with an id.
- `python -m bob.trace verify` prints `CREDENTIAL OK|FAIL` from the handshake and `LIVE CONNECTED|WAITING FOR LIVE` from the
  setup doctor, the two lines PRISM's own verifier prints.
- What a close reports, in order: `read_documents` (retrieval) · `read_ledger` · `tie_and_check` (chain) containing
  `match_statement <account>` ×n, `reconcile <account>` ×n, `rematch_client_entries`, `check_ledger`, `build_workpapers` ·
  `classify_unexplained_lines` (agent, with its `llm` child) when the model is asked · `apply_fix <kind>` per fix (error status
  when a fix didn't take) · re-reads after each round · `ask_client_for_missing_statements` / `prepare_statements` · the
  evaluation's `verify_expected_outcome`. A clean demo run is 14 spans with 12 tool calls; nothing is added to pad the count.

## 4. The evaluation (`bob/eval/`)

- `fixtures.py`: one company, January clean, February with plants. 40 plants: net settlements and processor fees, refunds
  (recorded and not), timing differences (outstanding check, deposit in transit, stale check), duplicate imports (three
  variants), missing support, wrong-period statement, opening-balance discrepancy, amount and date differences, the wrong bank
  account, undeposited funds, invoice payments (named, unnamed, partial), payroll at net, revenue counted twice, a bill paid
  as an expense, a card payment expensed, personal charges, an unexplained interest line, a missing savings statement. 72 cases:
  each plant alone plus 32 combinations drawn with a fixed seed. Each plant writes its expectation before Bob looks: the findings
  to raise (check, fix kind, account, whether Bob may act alone), the writes allowed, forbidden writes, the accounts that must
  tie or the difference that must remain, the blockers that must stay open for a person. Bob never imports this module.
- `expect.py`: the verifier. Correctness, cited writes, ties, exceptions left, invariants (the balance sheet balances; a failed
  fix is reported, never retried forever). Not HTTP success.
- `run.py`: `python -m bob.eval.run --tag <name> [--only <substring>] [--limit N] [--no-model] [--no-prism]`. One run per case,
  `session_id` = the batch id, `final_status` error on a failure, the fixture id and version on every record. Writes
  `bob/eval/results/<tag>-<version>.json` and `.md`.

Results on the same 72 inputs (fixture `bob-close-synthetic` `2026-10-17.1`):

| Batch | Bob | Passed | Exceptions left for a person | Changes made (all cited) |
|---|---|---|---|---|
| `baseline-v1` | v1 | 59 / 72 | 76 | 45 |
| `v2-v2` | v2 | 72 / 72 | 66 | 44 |

The baseline's clusters, both real and neither planted to fail:

1. **A statement imported twice was recorded twice** (7 runs): the file's lines no longer footed to its closing balance; Bob raised
   that and still recorded the second copy as a missing line, creating a reconciliation difference it then flagged. Fix: the extra
   copy is set aside before matching and the finding says the file was imported twice; the account ties on the rest.
2. **A known vendor described differently wasn't recognised** (6 runs): "HOME DEPOT RETURN 4471" never met the months of
   "POS DBT HOME DEPOT 4471". Fix: the vendor's name without the month's extra words is tried, under the same two-earlier-lines rule.

Details and the exact code: `bob/eval/CHANGES.md`. The baseline batch was committed before the fix; `BOB_V1=1` reproduces it.

## 5. Requirements checklist

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Nicrron: all hackathon-workflow model calls through `api.nicrron.ai/v1`, server-side key, configurable model | **Verified locally** (tests against a fake endpoint: request shape, key, model mapping, JSON parsing, retries, refusal, tool translation; 14 tests in `tests/test_bob.py`) · **Outstanding live**: one real call with a key (model availability, `NICRRON_STRUCTURED` mode that the chosen model accepts) | `product/reasoning/providers.py`, `tests/test_bob.py` |
| 2 | Hackathon mode has no silent fallback to a direct provider; the original provider works outside it | **Verified** | `test_hackathon_mode_routes_every_agent_through_nicrron_with_its_own_key`, `test_outside_hackathon_mode_the_configured_provider_is_used` |
| 3 | PRISM integration that captures tool-level execution, not only model responses | **Verified locally** (spans and trajectory with tool steps; delivery recorded, never claimed) · **Outstanding live**: `python -m bob.trace verify`, then one run visible in the dashboard | `bob/trace.py`, `TraceTests` |
| 4 | Instrumented: model calls, document extraction/retrieval, accounting tools, validation checks, workpaper generation, errors and retries | **Verified** (see the step list in §3) | `EvalTests.test_the_engine_reports_its_steps…` |
| 5 | Consistent session/run ids; executions distinguished; fixture id and version recorded | **Verified** (run id = trace id = trajectory request id; session per client month or per batch; fixture on trace metadata, spans metadata and the local record) | `test_payloads_carry_the_documented_fields…` |
| 6 | One real workflow in PRISM's Steps tab with 6+ meaningful steps and visible tool calls | **Outstanding live** (locally: a clean close is 14 spans / 12 tool calls; an evaluation case 15 / 13) | `data/bob/runs/*.json` after a run; `/firm/bob/` |
| 7 | An alert configured for a meaningful condition, firing on a real run | **Outstanding** (dashboard only: PRISM documents no alerts API) · see §7 | |
| 8 | A PRISM Intelligence cluster of 3+ failed runs with a shared cause, then v2 not failing on the same inputs | **Verified locally** (two clusters of 7 and 6 failed runs, both gone in v2 on identical inputs) · **Outstanding live**: send both batches and run Root Cause (costs credits) | `bob/eval/results/`, `bob/eval/CHANGES.md` |
| 9 | 50+ agent runs before fixing; baseline preserved before changing accounting behaviour | **Verified** (72 cases; the baseline is the first commit, the fix the second) | git history |
| 10 | Repeatable runner, 50+ synthetic cases, independently defined expected outcomes, out of the agent's context | **Verified** | `bob/eval/` |
| 11 | Correctness and unresolved exceptions tracked, not HTTP success | **Verified** | `bob/eval/expect.py` |
| 12 | Workpapers: reconciliation and schedules, source references, proposed entries with rationale, unresolved exceptions, review status | **Verified** (the product's Review tab and package: every balance-sheet account's roll-forward and support; each change with its citations and why; open items; accept / not right; DRAFT until closed) | `ops/native/workpapers.py`, `product/packagedoc.py`, `docs/hackathon/bob-review.png` |
| 13 | Deterministic arithmetic; the model can't force a balance; missing evidence stays an exception; synthetic data; live posting off | **Verified** (`opening_balance_discrepancy` keeps its difference; `missing_support_prepaid` stays "no support"; the demo company is simulated; `LiveQBO` isn't connected) | `bob/eval/fixtures.py` |
| 14 | Demo path: entity and period → source package → run → workpapers and evidence → discrepancies and proposed entries → PRISM run and improvement evidence | **Verified** on the local server (`POST /api/bob/demo` created a client, Bob ran, 3/3 accounts tied, the duplicate flagged) | `/firm/bob/`, `docs/hackathon/*.png` |
| 15 | `.env.example` placeholders only; setup and run instructions; fixtures and runner; this checklist; demo script; account actions | **Verified** | this file, `.env.example`, `README.md` |
| 16 | No secrets committed or printed | **Verified** (keys only in headers; `secrets.redact` covers `sk-af-`; `.env` ignored) | |
| 17 | Full test suite still passes | **Verified**: 749 tests OK (3 skipped) on the pruned tree (`nhb_cc_bobtests2`); `npx tsc --noEmit` and `next build` pass | |

Known limitations, stated plainly:

- `POST /api/trajectories` is what the official `prismtrace` SDK 0.5.3 submits (read from its source), but it isn't on the public
  docs page; if it's refused, the trace and spans still stand on their own and the record will show the status.
- The allowed `status` values for spans and the trace-level failure signal aren't documented. Failure is expressed four ways:
  span `status: "error"` with `error_message`, trajectory `final_status: "error"`, `metadata.status: "error"` on the trace, and an
  output message that starts with `Case …: FAIL`. Which of these Root Cause clusters on is for the live check.
- The demo's prepaid schedule is approved after the first read of the chart; when that order fails the Prepaid Insurance
  workpaper shows "no support" (as in the screenshot) and the schedule is proposed from the Schedules tab. Scenarios without a
  schedule are unaffected.
- The classifier (the only model step in a close) runs only with a key. Without one, a close is fully deterministic and PRISM
  sees `model: "none"` and no `llm` span; the eval marks `model_called: false`.

## 6. Demo script (about six minutes)

1. **The task.** Open `/firm/bob/`. Status strip: Bob v2, model route Nicrron, PRISM on. Pick `single-duplicate_import`:
   "the bank's export was imported twice; the file's lines no longer add up to the bank's own closing balance."
   Click **Load package and run Bob**. Open the month (Close tab): Bob imports the files, reads QuickBooks, reconciles, builds the
   workpapers.
2. **The workpapers.** Review tab: 3 of 3 accounts reconciled; the balance-sheet workpapers with opening + activity = closing and
   each account's support (the bank statement to 02/28, the open invoice behind A/R); the cash flow; the draft package (PDF).
   Click Checking's workpaper: the roll-forward, the statement, the one item it needs a person for.
3. **The failure (v1).** Show the evaluation panel: baseline 59/72. Open the cluster "forbidden write": seven runs where Bob
   recorded the duplicated line, then flagged the reconciliation difference it had made. Open one run: the `apply_fix create`
   step with its citation, then `reconcile Checking` with difference −288.00, then `verify_expected_outcome` in error. In PRISM:
   the same seven traces in the batch's session, Root Cause's cluster.
4. **The alert.** The rule on `bob-close` (§7) and the alert it raised on the batch's slow or failed runs.
5. **The fix (v2).** `bob/eval/CHANGES.md`: the extra copy is set aside before matching; the finding now reads "the statement file
   has a line twice … imported twice … the account is reconciled on the rest." v2: 72/72 on the same inputs, 44 changes all
   cited, 66 exceptions left for people on purpose (unknown payees, a payment a person applies, a missing statement, an opening
   balance the bank and the books disagree on). In PRISM: the v2 session with the same case ids, no failed runs.
6. **The model in its place.** Load `single-missing_unknown_payee`: a Zelle to a person. The classifier (through Nicrron) is
   asked, with the chart and the ledger's history; its `llm` step shows the model, tokens and the answer; without support it
   stays a question for the reviewer, and the account still ties with the line listed as unrecorded. Nothing is posted on a guess.

## 7. Account and dashboard actions only you can do

1. **Nicrron:** create the key at nicrron.ai, put it in `.env` as `NICRRON_API_KEY`. Then one real call:
   `BOB_HACKATHON=1 .venv/bin/python -m bob.eval.run --tag live-check --only single-missing_unknown_payee --no-prism` and read the
   `llm` step in the run's record. If the gateway answers 400 about `response_format`, set `NICRRON_STRUCTURED=prompt` (the
   default) or try `json_object`; if the model id is refused, pick one from nicrron.ai/docs/models.
2. **PRISM:** sign in at prism.blockconvey.com, create a project, copy its project id (Settings → Project) and an API key with the
   `ingest` scope (and `read` for the doctor). Put both in `.env`. Run `.venv/bin/python -m bob.trace verify`: it must print
   `CREDENTIAL OK`. Then one real run (`python -m bob.eval.run --tag live-check --limit 1`), then `verify` again until it prints
   `LIVE CONNECTED`. Open the project's Agent Runs / traces view and confirm the run's steps and tool calls are visible.
3. **The baseline in PRISM:** `BOB_V1=1 .venv/bin/python -m bob.eval.run --tag baseline` (72 runs, 13 failed), then
   `.venv/bin/python -m bob.eval.run --tag v2` (72 runs, none failed). Then run Root Cause on the project (5 credits) and confirm a
   cluster of at least three of the baseline's failed runs. If PRISM clusters on something other than our error signals (§5,
   limitations), tell me what it keyed on and I'll adjust the payload.
4. **The alert:** in the Alerts page create a rule scoped to agent `bob-close` (it must have carried a trace first). The two
   candidates whose metric we control: `latency` **Above 1000** (a close that waits on the model crosses it; the deterministic
   cases don't), or `error_rate` **Above 5** if the failed runs count there (their traces do carry an output; whether PRISM counts
   them is the live check). Set a severity and your e-mail, re-run a scenario with the classifier on, and screenshot the fired
   alert for the demo.
5. **Credits:** Agent Intelligence's narrative and Root Cause runs spend credits; check the project's balance before the demo.

## 8. Where things are

- `bob/`: `config.py` (environment), `trace.py` (PRISM, runs, verify), `engine.py` (Bob's loop at the engine level), `classify.py`
  (the classifier adapter without the database), `demo.py` (the product's demo path), `eval/` (fixtures, verifier, runner,
  results, CHANGES).
- `product/reasoning/providers.py` (`NicrronProvider`, the hackathon switch), `product/reasoning/secrets.py` (the key),
  `product/nativeclose.py` (the traced close), `product/api.py` (`/api/bob/*`), `ops/native/checks.py` (v2's two changes),
  `ops/native/trace.py` (the hook).
- `web/app/firm/bob/page.tsx` (the demo page), `web/components/firm/Shell.tsx` (nav entry, `NEXT_PUBLIC_BRAND`).
- `scripts/bob_dev.py`, `.env.example`, `requirements.txt`, `tests/test_bob.py`, `docs/hackathon/*.png`.
