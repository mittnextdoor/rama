"""What each result was built from, and when it stops being current (docs/82 §6).

Statements, reconciliations, review packages and settlement bridges are artifacts. Each records its inputs (the run,
the admitted documents, the facts in force, the approved package, the engine's version) and their hash. When an input
changes (late evidence, a reopened month, a changed fact) the artifact is marked stale with the reason and the work
event that caused it; a newer one supersedes it. Old versions are kept: a stale one is never shown, or downloaded, as
current."""
import hashlib
import json

from . import db

KINDS = ("statements", "reconciliations", "review_package", "settlement_bridge", "year_end_package")


def _hash(inputs):
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def documents_for(conn, client_id, period_id):
    return [r["sha256"] for r in conn.execute(
        "SELECT sha256 FROM documents WHERE client_id=%s AND (period_id IS NULL OR period_id=%s) AND admission='admitted' ORDER BY sha256",
        (client_id, period_id)).fetchall()]


def register(conn, c, p, kind, inputs, run_id=None, ref_id=None):
    """A new current artifact; the previous current one of the same kind for the month is superseded by it."""
    assert kind in KINDS
    v = conn.execute("SELECT COALESCE(max(version), 0) + 1 AS v FROM artifacts WHERE period_id=%s AND kind=%s", (p["id"], kind)).fetchone()["v"]
    row = conn.execute("INSERT INTO artifacts (firm_id, client_id, period_id, kind, version, run_id, ref_id, inputs, inputs_hash) "
                       "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                       (c["firm_id"], c["id"], p["id"], kind, v, run_id, ref_id, db.jsonb(json.loads(json.dumps(inputs, default=str))),
                        _hash(inputs))).fetchone()
    conn.execute("UPDATE artifacts SET status='superseded', superseded_by=%s WHERE period_id=%s AND kind=%s AND id<>%s AND status<>'superseded'",
                 (row["id"], p["id"], kind, row["id"]))
    return row


def mark_stale(conn, client_id, period_ids, reason, event_id=None):
    """Every current artifact of these months becomes stale, with the reason. Returns how many."""
    if not period_ids:
        return 0
    rows = conn.execute("UPDATE artifacts SET status='stale', stale_reason=%s, stale_event_id=%s WHERE client_id=%s AND period_id = ANY(%s) "
                        "AND status='current' RETURNING id", (reason, event_id, client_id, list(period_ids))).fetchall()
    return len(rows)


def months_from(conn, client_id, label):
    """This month and every later one: what a change here can reach when the dependencies aren't known (opening balances
    roll forward, so later months are treated as affected)."""
    return [r["id"] for r in conn.execute("SELECT id FROM periods WHERE client_id=%s AND label>=%s", (client_id, label)).fetchall()]


def facts_changed(conn, ident, c, fact, effective_from):
    """A confirmed fact changed: every month it reaches is affected (all of them when it has no effective date)."""
    label = effective_from.strftime("%Y-%m") if effective_from else "0000-00"
    ev = conn.execute("SELECT max(id) AS id FROM work_events WHERE client_id=%s", (c["id"],)).fetchone()["id"]
    return mark_stale(conn, c["id"], months_from(conn, c["id"], label), f"{fact} changed (confirmed by {ident.name})", ev)


def status_for(conn, period_id, kind):
    """The latest artifact of a kind for the month: current, stale (with why) or none yet."""
    return conn.execute("SELECT a.id, a.kind, a.version, a.status, a.stale_reason, a.created_at, a.run_id, a.ref_id, a.inputs_hash "
                        "FROM artifacts a WHERE a.period_id=%s AND a.kind=%s ORDER BY a.version DESC LIMIT 1", (period_id, kind)).fetchone()


def for_period(conn, period_id):
    return conn.execute("SELECT id, kind, version, status, stale_reason, created_at, run_id, ref_id, superseded_by FROM artifacts "
                        "WHERE period_id=%s ORDER BY kind, version DESC", (period_id,)).fetchall()
