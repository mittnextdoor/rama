"""Client fulfillment: what happens after a client signs and pays (docs/49).

QuickBooks Online is the accounting system of record. This package holds everything around it: the client file,
original records, the account-by-month completeness matrix, normalized source lines, proposed treatments, client
questions, reconciliation workpapers, review states, deliverables and the agent job history. Posted balances and
classifications live in QuickBooks (or in the simulated QuickBooks during development); this database keeps only the
proposal, the approval and the QuickBooks reference for each posted item.

Real client data lives in data/ops/ (ignored by Git), separate from the marketing database in data/acq/.
"""
