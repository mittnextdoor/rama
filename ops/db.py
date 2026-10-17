"""Fulfillment database (SQLite, WAL). Real client data: data/ops/ops.sqlite3, never committed, never reset.

Every client-owned table carries client_id, and all access goes through Scope, which adds the client filter itself,
so one client's records can't be read or changed through another client's context.
Money is integer cents. Amount sign convention for statement lines (same as app/ledger.py): positive = money into the
account (deposit, card payment or refund), negative = money out (payment, card charge).
"""
import os
import sqlite3
from contextlib import contextmanager

DEFAULT_PATH = os.environ.get("OPS_DB", os.path.join(os.path.dirname(__file__), "..", "data", "ops", "ops.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, legal_name TEXT NOT NULL, entity_type TEXT, activity TEXT,
  basis TEXT NOT NULL DEFAULT 'cash', cleanup_start TEXT NOT NULL, cleanup_end TEXT NOT NULL, service_start TEXT NOT NULL,
  fiscal_year_end TEXT NOT NULL DEFAULT '12-31', mode TEXT NOT NULL DEFAULT 'simulation', qbo_realm TEXT,
  qbo_env TEXT NOT NULL DEFAULT 'production', industry TEXT NOT NULL DEFAULT 'service', profile_json TEXT NOT NULL DEFAULT '{}',
  capitalization_threshold_cents INTEGER NOT NULL DEFAULT 250000, receipt_threshold_cents INTEGER NOT NULL DEFAULT 7500,
  auto_post_rules INTEGER NOT NULL DEFAULT 0, portal_token TEXT UNIQUE, phase TEXT NOT NULL DEFAULT 'A_client_file',
  synthetic INTEGER NOT NULL DEFAULT 0, estimate_minutes INTEGER, fee_cents INTEGER, created_at TEXT NOT NULL,
  CHECK (mode IN ('simulation','prepare','execute')), CHECK (basis IN ('cash','accrual')), CHECK (qbo_env IN ('sandbox','production'))
);

-- Bank, card, loan, processor, payroll and software the client uses; discovered accounts start as 'discovered'.
CREATE TABLE IF NOT EXISTS systems (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), kind TEXT NOT NULL, name TEXT NOT NULL,
  institution TEXT, last4 TEXT, opened TEXT, closed TEXT, status TEXT NOT NULL DEFAULT 'confirmed',
  qbo_account TEXT, statement_cycle_day INTEGER, discovered_from TEXT, notes TEXT, role TEXT, created_at TEXT NOT NULL,
  CHECK (kind IN ('bank','card','loan','processor','payroll','software','personal','other')),
  CHECK (status IN ('confirmed','discovered','excluded'))
);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), topic TEXT NOT NULL, question TEXT NOT NULL,
  needs TEXT NOT NULL DEFAULT 'owner', status TEXT NOT NULL DEFAULT 'open', decision TEXT, decided_by TEXT, decided_at TEXT,
  evidence TEXT, created_at TEXT NOT NULL, UNIQUE (client_id, topic)
);

CREATE TABLE IF NOT EXISTS deadlines (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), name TEXT NOT NULL, due TEXT NOT NULL,
  depends_on TEXT, status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), sha256 TEXT NOT NULL, filename TEXT NOT NULL,
  path TEXT NOT NULL, size INTEGER NOT NULL, kind TEXT, system_id INTEGER REFERENCES systems(id), period_start TEXT, period_end TEXT,
  status TEXT NOT NULL DEFAULT 'received', problem TEXT, uploaded_by TEXT NOT NULL, received_at TEXT NOT NULL, meta_json TEXT,
  UNIQUE (client_id, sha256)
);

CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), item_key TEXT NOT NULL, system_id INTEGER,
  period TEXT, description TEXT NOT NULL, purpose TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', requested_at TEXT NOT NULL,
  due TEXT, last_reminder TEXT, document_id INTEGER, UNIQUE (client_id, item_key)
);

CREATE TABLE IF NOT EXISTS statements (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), system_id INTEGER NOT NULL REFERENCES systems(id),
  document_id INTEGER NOT NULL REFERENCES documents(id), period_start TEXT NOT NULL, period_end TEXT NOT NULL,
  opening_cents INTEGER NOT NULL, closing_cents INTEGER NOT NULL, lines INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'valid',
  UNIQUE (client_id, system_id, period_end)
);

-- Normalized, immutable lines from every source. Exact re-imports of a file are skipped (document unique by sha256).
CREATE TABLE IF NOT EXISTS source_lines (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), system_id INTEGER REFERENCES systems(id),
  document_id INTEGER NOT NULL REFERENCES documents(id), line_no INTEGER NOT NULL, source_kind TEXT NOT NULL,
  date TEXT NOT NULL, amount_cents INTEGER NOT NULL, description TEXT NOT NULL, ref TEXT, extra_json TEXT,
  fingerprint TEXT NOT NULL, duplicate_of INTEGER REFERENCES source_lines(id), created_at TEXT NOT NULL,
  UNIQUE (document_id, line_no)
);

-- Accounting events to be posted: one per kept statement/export line, plus derived events (processor settlements,
-- opening balances, expenses paid personally). Treatment is proposed here; balances live in QuickBooks.
CREATE TABLE IF NOT EXISTS txns (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), system_id INTEGER REFERENCES systems(id),
  source_line_id INTEGER REFERENCES source_lines(id), date TEXT NOT NULL, amount_cents INTEGER NOT NULL, description TEXT NOT NULL,
  counterparty TEXT, treatment TEXT, account TEXT, splits_json TEXT, status TEXT NOT NULL DEFAULT 'staged', reason TEXT,
  proposed_by TEXT, rule_id INTEGER, needs_review INTEGER NOT NULL DEFAULT 1, match_id INTEGER, approved_by TEXT, approved_at TEXT,
  approval_hash TEXT, post_batch_id INTEGER, qbo_ref TEXT, period TEXT NOT NULL, derived_key TEXT, created_at TEXT NOT NULL,
  UNIQUE (client_id, derived_key), CHECK (status IN ('staged','proposed','question','approved','posted','excluded','blocked'))
);

CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), kind TEXT NOT NULL, a_txn INTEGER, b_txn INTEGER,
  detail_json TEXT, status TEXT NOT NULL DEFAULT 'proposed', created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), document_id INTEGER NOT NULL REFERENCES documents(id),
  date TEXT, vendor TEXT, total_cents INTEGER, paid_with TEXT, txn_id INTEGER, status TEXT NOT NULL DEFAULT 'unmatched'
);

CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), pattern TEXT NOT NULL, treatment TEXT NOT NULL,
  account TEXT, direction TEXT NOT NULL DEFAULT 'any', status TEXT NOT NULL DEFAULT 'draft', approved_by TEXT, version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coa (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), name TEXT NOT NULL, type TEXT NOT NULL,
  purpose TEXT, status TEXT NOT NULL DEFAULT 'proposed', qbo_ref TEXT, UNIQUE (client_id, name)
);

CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), batch INTEGER, topic TEXT NOT NULL,
  text TEXT NOT NULL, why TEXT NOT NULL, txn_ids_json TEXT NOT NULL DEFAULT '[]', choices_json TEXT, status TEXT NOT NULL DEFAULT 'open',
  asked_at TEXT, followup_at TEXT, answer TEXT, answer_doc INTEGER, answered_at TEXT, decision TEXT, decided_by TEXT, decided_at TEXT,
  dedupe_key TEXT UNIQUE, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opening_balances (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), account TEXT NOT NULL, as_of TEXT NOT NULL,
  amount_cents INTEGER NOT NULL, evidence TEXT NOT NULL, support TEXT NOT NULL, note TEXT, status TEXT NOT NULL DEFAULT 'proposed',
  UNIQUE (client_id, account), CHECK (support IN ('statement','lender','return_only','none'))
);

CREATE TABLE IF NOT EXISTS reconciliations (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), system_id INTEGER NOT NULL REFERENCES systems(id),
  statement_id INTEGER NOT NULL REFERENCES statements(id), period_end TEXT NOT NULL, statement_cents INTEGER NOT NULL,
  books_cents INTEGER, difference_cents INTEGER, unposted_json TEXT, extra_json TEXT, status TEXT NOT NULL, qbo_evidence TEXT,
  computed_at TEXT NOT NULL, UNIQUE (client_id, statement_id)
);

CREATE TABLE IF NOT EXISTS schedules (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), kind TEXT NOT NULL, as_of TEXT NOT NULL,
  data_json TEXT NOT NULL, books_cents INTEGER, support_cents INTEGER, status TEXT NOT NULL, UNIQUE (client_id, kind, as_of)
);

CREATE TABLE IF NOT EXISTS exceptions (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), code TEXT NOT NULL, severity TEXT NOT NULL,
  ref TEXT, message TEXT NOT NULL, needs TEXT NOT NULL DEFAULT 'owner', status TEXT NOT NULL DEFAULT 'open', resolution TEXT,
  resolved_by TEXT, created_at TEXT NOT NULL, resolved_at TEXT, UNIQUE (client_id, code, ref),
  CHECK (severity IN ('blocker','review','info')), CHECK (status IN ('open','resolved','limitation'))
);

CREATE TABLE IF NOT EXISTS post_batches (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), status TEXT NOT NULL, content_hash TEXT NOT NULL,
  txn_ids_json TEXT NOT NULL, approved_by TEXT, approved_at TEXT, result_json TEXT, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_items (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), batch_id INTEGER NOT NULL REFERENCES post_batches(id),
  txn_id INTEGER NOT NULL, request_id TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  qbo_ref TEXT, error TEXT, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), scope TEXT NOT NULL, state TEXT NOT NULL,
  content_hash TEXT, reviewer TEXT, reviewed_at TEXT, delivered_at TEXT, closed_at TEXT, reopened_reason TEXT, version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, CHECK (state IN ('draft','reviewed','delivered','closed'))
);

CREATE TABLE IF NOT EXISTS deliverables (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), review_id INTEGER, scope TEXT NOT NULL, kind TEXT NOT NULL,
  version INTEGER NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS close_tasks (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), period TEXT NOT NULL, step TEXT NOT NULL, due TEXT NOT NULL,
  owner TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', UNIQUE (client_id, period, step)
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), worker TEXT NOT NULL, kind TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}', idem_key TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3, result_json TEXT, error TEXT, evidence_json TEXT, cost_micros INTEGER NOT NULL DEFAULT 0,
  tokens INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  CHECK (status IN ('queued','running','done','failed','blocked'))
);

CREATE TABLE IF NOT EXISTS effort (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), who TEXT NOT NULL, minutes INTEGER NOT NULL DEFAULT 0,
  cost_micros INTEGER NOT NULL DEFAULT 0, task TEXT NOT NULL, at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, client_id INTEGER, actor TEXT NOT NULL, action TEXT NOT NULL, ref TEXT, detail TEXT, at TEXT NOT NULL
);

-- Universal intake (ops/intake): each client file's layout, and every row converted to a standard record.
CREATE TABLE IF NOT EXISTS intake_layouts (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), fingerprint TEXT NOT NULL, rtype TEXT,
  colmap_json TEXT NOT NULL, headers_json TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, approved_by TEXT,
  created_at TEXT NOT NULL, UNIQUE (client_id, fingerprint), CHECK (status IN ('approved','proposed','rejected'))
);
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), document_id INTEGER NOT NULL REFERENCES documents(id),
  row_no INTEGER NOT NULL, rtype TEXT NOT NULL, rid TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, date TEXT, period TEXT,
  data_json TEXT NOT NULL, raw_json TEXT, status TEXT NOT NULL DEFAULT 'active', note TEXT, stage TEXT, related INTEGER,
  created_at TEXT NOT NULL, UNIQUE (document_id, row_no),
  CHECK (status IN ('active','superseded','duplicate','quarantined','invalid','conflict','evidence'))
);
CREATE INDEX IF NOT EXISTS records_rid ON records (client_id, rtype, rid);
CREATE INDEX IF NOT EXISTS records_period ON records (client_id, period, rtype);

-- Supervised review (ops/review): work items per checkpoint and period, review rounds by level, findings, hash-bound
-- approvals, events that trigger review, per-operation execution records, and the controlled knowledge base.
CREATE TABLE IF NOT EXISTS work_items (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), period TEXT NOT NULL, checkpoint TEXT NOT NULL,
  title TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, content_hash TEXT NOT NULL, artifact_json TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'in_progress', associate TEXT NOT NULL, rounds INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (client_id, period, checkpoint)
);
CREATE TABLE IF NOT EXISTS review_rounds (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), work_item_id INTEGER NOT NULL REFERENCES work_items(id),
  version INTEGER NOT NULL, content_hash TEXT NOT NULL, level TEXT NOT NULL, reviewer TEXT NOT NULL, method TEXT NOT NULL,
  checklist_version TEXT NOT NULL, evidence_json TEXT NOT NULL, checks_json TEXT NOT NULL, decision TEXT NOT NULL, decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_findings (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), work_item_id INTEGER NOT NULL REFERENCES work_items(id),
  round_id INTEGER, level TEXT NOT NULL, check_id TEXT NOT NULL, severity TEXT NOT NULL, problem TEXT NOT NULL, evidence TEXT NOT NULL,
  expected TEXT NOT NULL, impact TEXT NOT NULL, responsible TEXT NOT NULL, remediation TEXT NOT NULL, verification TEXT NOT NULL,
  missed_by TEXT, status TEXT NOT NULL DEFAULT 'open', rounds_open INTEGER NOT NULL DEFAULT 1, response TEXT, verified_by TEXT,
  verified_at TEXT, created_at TEXT NOT NULL, UNIQUE (client_id, work_item_id, check_id, evidence),
  CHECK (severity IN ('blocker','major','minor','info')), CHECK (status IN ('open','closed','escalated','accepted'))
);
CREATE TABLE IF NOT EXISTS review_approvals (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), work_item_id INTEGER NOT NULL REFERENCES work_items(id),
  level TEXT NOT NULL, action TEXT NOT NULL, content_hash TEXT NOT NULL, approver TEXT NOT NULL, note TEXT,
  created_at TEXT NOT NULL, revoked_at TEXT, revoke_reason TEXT
);
CREATE TABLE IF NOT EXISTS review_events (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), period TEXT, kind TEXT NOT NULL, ref TEXT,
  detail_json TEXT, created_at TEXT NOT NULL, handled_at TEXT
);
CREATE TABLE IF NOT EXISTS executions (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), period TEXT, work_item_id INTEGER, request_id TEXT NOT NULL,
  entity TEXT NOT NULL, ref TEXT NOT NULL, status TEXT NOT NULL, qbo_id TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (client_id, request_id), CHECK (status IN ('intent','confirmed','uncertain','failed'))
);
CREATE TABLE IF NOT EXISTS manifests (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), period TEXT NOT NULL, hash TEXT NOT NULL,
  manifest_json TEXT NOT NULL, created_at TEXT NOT NULL, verified_at TEXT, UNIQUE (client_id, hash)
);
CREATE TRIGGER IF NOT EXISTS manifests_immutable BEFORE UPDATE OF client_id, period, hash, manifest_json ON manifests
BEGIN SELECT RAISE(ABORT, 'a posting manifest is immutable: a changed plan is a new manifest'); END;
CREATE TABLE IF NOT EXISTS knowledge (
  id INTEGER PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
  source TEXT, applies_from TEXT, version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'proposed', proposed_by TEXT NOT NULL,
  approved_by TEXT, regression_test TEXT, created_at TEXT NOT NULL, decided_at TEXT, UNIQUE (scope, key, version),
  CHECK (status IN ('proposed','approved','rejected','retired'))
);

-- Simulated QuickBooks company (development and demos only; the live adapter talks to QuickBooks instead).
CREATE TABLE IF NOT EXISTS sim_qbo_accounts (
  realm TEXT NOT NULL, id INTEGER NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL, PRIMARY KEY (realm, id), UNIQUE (realm, name)
);
CREATE TABLE IF NOT EXISTS sim_qbo_txns (
  realm TEXT NOT NULL, id INTEGER NOT NULL, entity TEXT NOT NULL, request_id TEXT NOT NULL, date TEXT NOT NULL, doc_json TEXT NOT NULL,
  PRIMARY KEY (realm, id), UNIQUE (realm, request_id)
);
CREATE TABLE IF NOT EXISTS sim_qbo_names (
  realm TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, id INTEGER NOT NULL, data_json TEXT, PRIMARY KEY (realm, kind, name)
);
-- The content each posted books entry had when it was posted: a later version of the books that changes an entry
-- (new evidence reclassifies it) is found by comparing signatures, and the entry is replaced in QuickBooks.
CREATE TABLE IF NOT EXISTS native_sigs (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), realm TEXT, key TEXT NOT NULL, period TEXT NOT NULL,
  sig TEXT NOT NULL, lines_json TEXT, created_at TEXT NOT NULL, UNIQUE (client_id, realm, key)
);
-- What the native writer created in QuickBooks for each books entry (links payments to invoices, bill payments to bills).
CREATE TABLE IF NOT EXISTS native_posts (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id), ref TEXT NOT NULL, entity TEXT NOT NULL,
  qbo_id TEXT NOT NULL, request_id TEXT NOT NULL, realm TEXT, created_at TEXT NOT NULL, UNIQUE (client_id, realm, ref, entity)
);
CREATE TABLE IF NOT EXISTS sim_qbo_lines (
  realm TEXT NOT NULL, txn_id INTEGER NOT NULL, account TEXT NOT NULL, amount_cents INTEGER NOT NULL, memo TEXT
);
-- The simulated company's settings QuickBooks keeps in Preferences (the closing date: AccountingInfoPrefs.BookCloseDate).
CREATE TABLE IF NOT EXISTS sim_qbo_prefs (
  realm TEXT NOT NULL, key TEXT NOT NULL, value TEXT, PRIMARY KEY (realm, key)
);
"""


def connect(path=None) -> sqlite3.Connection:
    path = path or DEFAULT_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    migrations = (("clients", "qbo_env", "TEXT NOT NULL DEFAULT 'production'"),   # databases created before these columns
                  ("clients", "industry", "TEXT NOT NULL DEFAULT 'service'"), ("clients", "profile_json", "TEXT NOT NULL DEFAULT '{}'"),
                  ("systems", "role", "TEXT"), ("reviews", "snapshot_json", "TEXT"), ("txns", "plan_json", "TEXT"))
    _per_client_txn_keys(conn)
    for table, col, decl in migrations:
        if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    return conn


def _per_client_txn_keys(conn):
    """Databases created when a derived key was unique across all clients (two clients with an invoice of the same
    number collided): rebuilt so it's unique per client. Nothing references txns, and every row is kept."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='txns'").fetchone()
    if not row or "derived_key TEXT UNIQUE" not in row[0]:
        return
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(txns)")]
    create = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS txns ("):]
    create = create[:create.index(");") + 2].replace("IF NOT EXISTS txns", "txns")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        conn.execute("ALTER TABLE txns RENAME TO txns_before_client_keys")
        conn.execute(create)
        have = {r["name"] for r in conn.execute("PRAGMA table_info(txns)")}
        for c in cols:
            if c not in have:
                conn.execute(f"ALTER TABLE txns ADD COLUMN {c} TEXT")
        listed = ", ".join(cols)
        conn.execute(f"INSERT INTO txns ({listed}) SELECT {listed} FROM txns_before_client_keys")
        conn.execute("DROP TABLE txns_before_client_keys")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


@contextmanager
def tx(conn):
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


class Scope:
    """All reads and writes for one client. The client filter is added here, never by the caller."""

    def __init__(self, conn, client_id):
        self.conn, self.cid = conn, int(client_id)
        if conn.execute("SELECT 1 FROM clients WHERE id=?", (self.cid,)).fetchone() is None:
            raise LookupError(f"no client {client_id}")

    def all(self, table, where="1=1", params=(), order="id"):
        return self.conn.execute(f"SELECT * FROM {table} WHERE client_id=? AND ({where}) ORDER BY {order}", (self.cid, *params)).fetchall()

    def one(self, table, row_id):
        return self.conn.execute(f"SELECT * FROM {table} WHERE client_id=? AND id=?", (self.cid, row_id)).fetchone()

    def first(self, table, where, params=()):
        return self.conn.execute(f"SELECT * FROM {table} WHERE client_id=? AND ({where}) ORDER BY id LIMIT 1", (self.cid, *params)).fetchone()

    def count(self, table, where="1=1", params=()):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE client_id=? AND ({where})", (self.cid, *params)).fetchone()[0]

    def insert(self, table, **cols):
        cols["client_id"] = self.cid
        keys = ",".join(cols)
        cur = self.conn.execute(f"INSERT INTO {table} ({keys}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        return cur.lastrowid

    def insert_ignore(self, table, **cols):
        cols["client_id"] = self.cid
        keys = ",".join(cols)
        cur = self.conn.execute(f"INSERT OR IGNORE INTO {table} ({keys}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        return cur.lastrowid if cur.rowcount else None

    def update(self, table, row_id, **cols):
        sets = ",".join(f"{k}=?" for k in cols)
        cur = self.conn.execute(f"UPDATE {table} SET {sets} WHERE client_id=? AND id=?", (*cols.values(), self.cid, row_id))
        if cur.rowcount != 1:
            raise LookupError(f"{table} {row_id} not found for client {self.cid}")
