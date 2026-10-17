"""The accounting product (docs/73, docs/74): a FastAPI backend over Postgres, durable background jobs, a document store
and the existing evidence engine (ops/) run as tracked jobs, with a React/TypeScript review workspace (web/).

    .venv/bin/python -m product migrate      apply the database migrations
    .venv/bin/python -m product serve        the API and the built web app on http://127.0.0.1:8780
    .venv/bin/python -m product worker       the background job worker
    .venv/bin/python -m product seed-demo    a clearly labeled synthetic demonstration client

A small bookkeeping firm was the first operating user. QuickBooks stays the system of record: the product reads files
(source records and QuickBooks exports) and proposes change sets; nothing is posted from here.
"""
