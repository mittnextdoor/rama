"""The ledger-native close (docs/100): QuickBooks is the books.

The agents read the client's ledger into a dated snapshot (read.py), tie each bank and card statement to the ledger's
own register (reconcile.py), run the close checks against the client's evidence (checks.py), and fix what's wrong in the
ledger itself with small, verified writes (fixes.py). Nothing here rebuilds a second set of books: every figure is the
ledger's, read through the adapter (ops/qbo: the simulated company on this Mac, or QuickBooks Online), so another ledger
plugs in by giving the same reads and writes.

Amounts are integer cents, debit-positive (an asset's balance is positive, a liability's negative); a statement line's
amount is its effect on the account in the same sense (money into a bank account is positive, a card charge negative)."""
