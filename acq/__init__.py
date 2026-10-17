"""Two small helpers the close engine still imports (a freezable clock).

One orchestrator and specialised agents (prospecting, outreach, conversation and booking, sales follow-through,
growth, Google Ads, Yelp Ads, Meta Ads and Facebook/Instagram engagement) working against one SQLite database.

Runtime: `python3 -m acq worker` (durable jobs, scheduler, event ingestion) and `python3 -m acq panel` (control
panel on 127.0.0.1). Every external action passes deterministic guards (acq/guard.py) and is recorded with an
idempotency key (acq/jobs.py). The operating authority (acq/authority.json) must be approved by the owner before any
live sending or spending; see docs/33-acquisition-agents.md.
"""
