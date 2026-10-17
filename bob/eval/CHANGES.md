# Bob: what changed between versions, and why

Each version is a change to Bob's accounting behaviour, made after a baseline batch showed a recurring cause and measured
again on the same inputs. Integration work (Nicrron, PRISM, the harness) is not a version: it changes nothing Bob decides.
`BOB_V1=1` replays v1's behaviour so the baseline can be reproduced on the same fixture (for PRISM, for a reviewer).

## v1 (baseline, `bob/eval/results/baseline-v1.json`)

The ledger-native close as it stood on 2026-10-17, fixture `bob-close-synthetic` version `2026-10-17.1`, 72 cases: 59 passed.

Two clusters, both real:

1. **A statement imported twice was recorded twice** (7 cases: `duplicate_import*` and every combination with them). The bank's
   file carried one line twice, so its lines no longer added up to its own closing balance. Bob raised that (`statement_incomplete`)
   and then still treated the second copy as a line missing from QuickBooks and recorded it, with a citation from the ledger's
   history. The write created a reconciliation difference of exactly that amount, which Bob then flagged as a second exception.
   Money operations impact: a transaction that never happened, posted to the books on the agents' own authority.
2. **A known vendor described differently wasn't recognised** (6 cases: `refund_unrecorded`, `refund_unrecorded_fuel`,
   `vendor_description_varies` and combinations). The history key is the first three words of the description, so
   "HOME DEPOT RETURN 4471" never met the months of "POS DBT HOME DEPOT 4471" booked to Materials. The refund, and an online order,
   waited for a person although the books themselves said where they go.

## v2 (`bob/eval/results/v2-v2.json`): 72 of 72 on the same inputs

1. `ops/native/checks.run`: when a statement's lines are off from its closing balance by exactly one line that appears more than
   once in the file (same date, amount and description), the extra copy is set aside before anything is matched, and the finding
   says so: "the statement file has a line twice ... the statement was imported twice. The extra copy is no transaction and is set
   aside; the account is reconciled on the rest." Nothing is recorded for it; the account ties; the client is asked for the
   statement once. A file that is short by lines that aren't duplicates is still raised as before.
2. `ops/native/checks.classify`: when the description's full key has no history, the vendor's name without this month's extra
   words is tried (never fewer than two words), under the same rule as before: at least two earlier lines, all to one account,
   cited by transaction. The finding says which key matched and what the line reads.

Nothing else moved. The expectations (`bob/eval/fixtures.py`) are the same file for both batches.
