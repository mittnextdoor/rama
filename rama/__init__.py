"""RAMA: from a portfolio company's books to approved LP risk intelligence.

borrower.py   the synthetic borrower's books and source files (Helios Compute LLC, public proxy CRWV)
close.py      the month-end close on those books (Bob's engine), traced
metrics.py    verified borrower metrics from the closed month (only from tied evidence)
fund.py       the synthetic private debt fund (loans L1-L6, LPs, facility); L2 is the closed borrower
capiq.py      the Cap IQ Pro screen snapshot loader (licensed data, never committed)
rules.py      the leading-indicator rules R1-R14, deterministic
cards.py      the card agent (OpenAI Agents SDK through Nicrron) and its guardrails
pipeline.py   the workflow state: close -> intelligence -> approval -> destination
tracing.py    PRISM (Agent Frameworks card: OpenAI Agents SDK) and the local run records
api.py        the HTTP API and the web app
"""
VERSION = "rama-1"
AS_OF = "2026-10-16"
PERIOD = "2026-09"
