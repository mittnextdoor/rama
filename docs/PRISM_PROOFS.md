# The three PRISM proofs, as RAMA meets them (Money Operations track)

What the track asks: a session with 6+ tool steps, an alert firing on a real run, and a Root Cause cluster of 3+ failed
runs with its cause, then v2 on the same inputs no longer failing. "The failure, the fix, and the alert that would have
caught it." Below: what we did, what PRISM holds, and what to put on screen. Say "we ran this" only for the rows marked
**ran**; the honesty rule in the guardrail scripts applies.

## Proof 1 · Sessions: one run, every tool call (6+ steps)  — ran

**What we did.** Every RAMA agent is traced through PRISM's Agent Frameworks integration (OpenAI Agents SDK,
`prismtrace` processor as the only trace processor). The deterministic close engine's steps are mirrored as SDK
function spans, so PRISM sees the whole month, not only the model calls. One PRISM session per company-month:
`helios-2026-09`.

**What PRISM holds** (agent `rama`, model route `openai-agents:generation:anthropic/claude-haiku-5-5`, via Nicrron):

| Run | Steps PRISM shows | What they are |
|---|---|---|
| `close` | 16 | read_source_package → read_ledger → read_documents → tie_and_check (match_statement ×2, reconcile ×2, rematch, check_ledger, build_workpapers) → match_pik_election_notice → classifier call (llm) → apply_fix create → re-read → prepare_statements |
| `intelligence` | 20 | read_closed_books → load_capiq_snapshot → build_fund_view → evaluate_rules → rule R1 … rule R14 (one step each) → card writer runs (10 agents, each with its tool call and two guardrails) → card_guardrails |
| `review` / `approval` / `publish` | 1–3 each | the reviewer's decision, the approvals, the release |

**On screen:** Traces → filter agent `rama` → the intelligence run. The Steps list shows the rule steps by name and the
generation steps with the Nicrron-routed model id. (It's in the film at 3:20, scene 11, first window.)

## Proof 2 · Alert: set on something that matters, firing on a real run  — rule created; firing to confirm

**What matters in this workflow.** Two things: a model call that stalls (the card writer waits on the model; a slow
close holds the whole month), and a guardrail block (a card tried to give advice). PRISM's documented metrics are
`latency`, `error_rate` (traces with no output), `traces_per_hour`, `guardrail_blocks` (PRISM's own proxy guardrail,
not ours) and two scoring metrics.

**The rule:** scoped to agent `rama`, metric **latency**, condition **Above 1000** ms. A card-writer generation
through Nicrron takes 1–3 s, so a real intelligence run crosses it.

**What we found and fixed on the way (worth saying out loud).** PRISM's Agents SDK processor read every span's
duration as **0 ms**: it expects numeric timestamps and the SDK gives ISO strings, so the agent fleet showed "0ms"
for every trace and the rule could never fire. RAMA's tracer now parses the timestamps (`rama/tracing.py`,
`_Timed`), and the runs sent after 16:05 on 17 Oct carry real durations.

**On screen:** Alerts → the fired alert on `rama` (latency above 1000 ms) → open the trace: a card-writer generation.
If it hasn't fired, run Build indicators once in RAMA and refresh Alerts.

## Proof 3 · Root Cause: 3+ failed runs with a cause, then v2 not failing on the same inputs  — batches sent; cluster to run

**The failure.** Bob, RAMA's close engine, has a 72-case synthetic evaluation (`bob/eval/`): one company, 40 planted
ways books and statements go wrong, 72 cases (each plant alone plus 32 fixed-seed combinations). Each case writes its
expected outcome before the engine looks; the verifier checks correctness, cited writes, ties and exceptions, never
HTTP success. Version 1 passed **59 of 72**. The failures formed two groups, neither planted to fail:

1. **A statement imported twice was recorded twice** (7 runs). The file's lines no longer footed to the bank's own
   closing balance; v1 raised that and *still* recorded the second copy as a missing line, creating a reconciliation
   difference it then flagged. A forbidden write.
2. **A known vendor described differently wasn't recognised** (6 runs). "HOME DEPOT RETURN 4471" never met the months
   of "POS DBT HOME DEPOT 4471", so a line the ledger's history explained was left for a person.

**The fix** (`bob/eval/CHANGES.md`, two targeted changes in `ops/native/checks.py`): the extra copy is set aside
before matching and the finding says the file was imported twice; the vendor's name without the month's extra words is
tried under the same two-earlier-lines rule. Version 2 on the same 72 inputs: **72 of 72**, 44 changes all cited,
66 exceptions left for people on purpose.

**What PRISM holds** (sent 17 Oct 2026, 16:06–17:25; PRISM's trace count rose from about 1,600 to 5,117):

| Batch | PRISM session | Result |
|---|---|---|
| v1 baseline (`BOB_V1=1`) | `eval-baseline-prism-v2-20261017T200635Z` | 59 / 72; 13 failed: duplicate import ×7, vendor description ×6 |
| v2, same 72 inputs | `eval-v2-prism-v2-20261017T204533Z` | 72 / 72; 44 changes, all cited; 66 exceptions left on purpose |

Each case is one Agents SDK trace with its steps; a failed case ends with a `verify_expected_outcome` step in error and
an output that starts `Case …: FAIL`.

**On screen:** Root Cause → run it on the baseline session (costs credits) → the cluster of the duplicate-import
failures and its explanation; then Sessions → the v2 session, same case ids, no failures. Show `bob/eval/CHANGES.md`
beside it. If PRISM's clustering keys on something other than the FAIL output, say so and show the local results
(`bob/eval/results/baseline-v1.md`, `v2-v2.md`), which are the same data.

## The demo line

"The failure: our close engine recorded a bank line twice when a statement was imported twice, and flagged its own
difference. The fix: set the extra copy aside before matching. The proof: 59 of 72 became 72 of 72 on the same inputs,
every run traced in PRISM, with an alert on the agent that would have paged us the moment a model call stalled."

## Honesty notes

- The RAMA intelligence layer has no separate before/after evaluation yet; the 72-case result is the **close engine's**.
  Don't present it as intelligence accuracy.
- The guardrail block on an advisory sentence is real (the trace is in PRISM: `"descriptive": false`, the reason recorded);
  it is a blocked output, not a failed tool call, so it doesn't count under PRISM's `error_rate`.
- The destination is a demonstration; there is no live Chronograph connection.
