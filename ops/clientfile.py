"""Phase A: the operational client file, and Phase B: the client-specific records request.

open_client() is the "first day after signing" automation: it creates the client record, the systems it knows about,
the accounting decisions that must be made (open until the owner decides), key deadlines, the portal link and the
records request built from the client's actual accounts. Nothing is sent to the client from here.
"""
import json
import secrets

from . import db
from .core import iso, months, raise_exception

# Decisions every cleanup needs. The system never assumes these; they stay open until the owner records a decision.
DECISIONS = (
    ("basis", "Cash or accrual basis for the books and reports?", "owner"),
    ("capitalization", "Capitalization threshold: purchases at or above this amount are reviewed as possible fixed assets.", "owner"),
    ("opening_equity", "How opening-balance equity is split between owners' capital accounts once opening balances are supported.", "preparer"),
    ("fixed_assets_prior", "Depreciation schedule for assets on the prior return (the preparer usually holds it).", "preparer"),
    ("owner_pay", "How owners take money out (draws/distributions/guaranteed payments) and how personal spending is recorded.", "owner"),
    ("receipt_policy", "Receipt threshold and what happens when a receipt can't be found (client explanation vs. limitation).", "owner"),
)

# What each record is for. Shown to the client in plain language and to the owner in the matrix.
PURPOSE = {
    "bank": "Monthly statements prove every transaction and the starting and ending balance; we reconcile to them.",
    "card": "Monthly statements show every charge, refund and payment and the balance owed; we reconcile to them.",
    "loan": "Lender statements split each payment into principal and interest and prove the balance owed.",
    "processor": "Payout reports split each deposit into sales, refunds, chargebacks and fees; bank deposits alone understate sales.",
    "payroll": "Payroll registers and liability reports show gross wages, withholdings and employer taxes behind the net pay.",
    "prior_return": "The last filed return shows the reported starting position (balance sheet) and depreciation history.",
    "prior_books": "Any prior bookkeeping file or spreadsheet, so we don't redo work or miss balances.",
    "loan_agreement": "The loan agreement confirms the amount, rate, terms and anything financed (equipment).",
    "receipts": "Receipts support purchases over the receipt threshold and show what large purchases were.",
    "personal_business": "Business expenses you paid personally, so they can be recorded as your contribution to the business.",
    "distributor": "The distributor's statement shows equipment and parts bought on account and the return, warranty and rebate credits.",
}


def open_client(conn, *, code, legal_name, entity_type, activity, cleanup_start, cleanup_end, service_start, systems,
                basis=None, synthetic=False, mode="simulation", estimate_minutes=None, fee_cents=None, actor="owner",
                industry="service", intake=None):
    """Create the client file. systems: [{kind, name, institution, last4, opened, statement_cycle_day, role}].
    industry picks the profile (ops/industries.py); intake holds the intake answers (docs/ops-templates/intake-questionnaire.md)."""
    from .industries import PROFILES
    if service_start <= cleanup_end:
        raise ValueError("monthly service must start after the cleanup period ends (no overlap)")
    if industry not in PROFILES:
        raise ValueError(f"unknown industry {industry!r}: one of {', '.join(PROFILES)}")
    with db.tx(conn):
        cid = conn.execute(
            "INSERT INTO clients (code, legal_name, entity_type, activity, basis, cleanup_start, cleanup_end, service_start, mode, "
            "portal_token, synthetic, estimate_minutes, fee_cents, industry, profile_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, legal_name, entity_type, activity, basis or "cash", cleanup_start, cleanup_end, service_start, mode,
             secrets.token_urlsafe(24), int(synthetic), estimate_minutes, fee_cents, industry, json.dumps(intake or {}), iso())).lastrowid
        s = db.Scope(conn, cid)
        for sy in systems:
            s.insert("systems", kind=sy["kind"], name=sy["name"], institution=sy.get("institution"), last4=sy.get("last4"),
                     opened=sy.get("opened"), closed=sy.get("closed"), statement_cycle_day=sy.get("statement_cycle_day"),
                     role=sy.get("role"), status="confirmed", created_at=iso())
        for topic, q, needs in DECISIONS + tuple(PROFILES[industry]["decisions"]):
            decided = topic == "basis" and basis
            s.insert("decisions", topic=topic, question=q, needs=needs, status="decided" if decided else "open",
                     decision=basis if decided else None, decided_by=actor if decided else None, decided_at=iso() if decided else None,
                     created_at=iso())
        s.insert("deadlines", name="Records complete (target)", due=_plus_days(iso()[:10], 14))
        s.insert("deadlines", name="First recurring month closes", due=_plus_days(service_start[:10], 45), depends_on="cleanup delivered")
        build_requests(s)
        conn.execute("INSERT INTO audit (client_id, actor, action, detail, at) VALUES (?,?,?,?,?)", (cid, actor, "client_opened", legal_name, iso()))
    return cid


def _plus_days(d, n):
    from datetime import date, timedelta
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def statement_months(scope, system, for_requests=False):
    """Months whose statements are needed for the cleanup. For requests, cards cycling mid-month also need the first
    statement after the cleanup ends, because it holds the charges between the last cycle date and the cleanup end;
    that month itself belongs to the first recurring close, so the cleanup matrix doesn't include it."""
    c = scope.conn.execute("SELECT * FROM clients WHERE id=?", (scope.cid,)).fetchone()
    start = max(c["cleanup_start"], system["opened"] or c["cleanup_start"])
    started = scope.conn.execute("SELECT MAX(period) FROM close_tasks WHERE client_id=?", (scope.cid,)).fetchone()[0]
    end = max(c["cleanup_end"], started + "-28") if started else c["cleanup_end"]      # plus any recurring months started
    ms = months(start, end)
    if for_requests and not started:
        from .industries import profile
        cycles = system["statement_cycle_day"] and system["statement_cycle_day"] < 28
        in_transit = profile(scope)["revenue_source"] == "pms" and system["kind"] == "bank"   # proves year-end deposits in transit
        if cycles or in_transit:
            ms.append(months(c["cleanup_end"], c["service_start"])[-1])
    return ms


def build_requests(scope):
    """(Re)build the records request from the client's systems. Idempotent: existing items keep their status."""
    c = scope.conn.execute("SELECT * FROM clients WHERE id=?", (scope.cid,)).fetchone()
    n = 0
    for sy in scope.all("systems", "status!='excluded' AND (kind IN ('bank','card','loan','processor','payroll') OR role='distributor')"):
        for m in statement_months(scope, sy, for_requests=True):
            label = "account statement and credit memos" if sy["role"] == "distributor" else {
                "bank": "statement", "card": "statement", "loan": "lender statement", "payroll": "payroll register and liability report",
                "processor": "funding report" if sy["role"] == "lender" else "payout report"}[sy["kind"]]
            n += bool(scope.insert_ignore("requests", item_key=f"{sy['kind']}:{sy['id']}:{m}", system_id=sy["id"], period=m,
                                          description=f"{sy['name']} ({sy['institution'] or ''} …{sy['last4'] or ''}) {label} for {m}",
                                          purpose=PURPOSE.get("distributor" if sy["role"] == "distributor" else sy["kind"]), requested_at=iso()))
        if sy["kind"] == "loan":
            n += bool(scope.insert_ignore("requests", item_key=f"loan_agreement:{sy['id']}", system_id=sy["id"],
                                          description=f"{sy['name']} loan agreement and payoff/amortization schedule",
                                          purpose=PURPOSE["loan_agreement"], requested_at=iso()))
    from .industries import profile
    ms = months(c["cleanup_start"], c["cleanup_end"])
    for key, desc, purpose, freq in profile(scope)["requests"]:
        periods = ms if freq == "monthly" else sorted({f"{m[:4]}-Q{(int(m[5:]) - 1) // 3 + 1}" for m in ms}) if freq == "quarterly" else [ms[-1][:4]]
        for p in periods:
            n += bool(scope.insert_ignore("requests", item_key=f"{key}:{p}", period=p, description=f"{desc}: {p}", purpose=purpose,
                                          requested_at=iso()))
    year = int(c["cleanup_start"][:4]) - 1
    for key, desc, purpose in ((f"prior_return:{year}", f"{year} business tax return as filed (all pages and schedules)", PURPOSE["prior_return"]),
                               ("prior_books", "Any earlier bookkeeping file, spreadsheet or accountant schedules", PURPOSE["prior_books"]),
                               ("personal_business", "Receipts or a list of business purchases paid with personal cards or cash", PURPOSE["personal_business"])):
        n += bool(scope.insert_ignore("requests", item_key=key, description=desc, purpose=purpose, requested_at=iso()))
    return n


def add_discovered_system(scope, *, kind, name, last4, discovered_from, actor="agent:records"):
    """A newly found account (e.g. transfers to an unknown account number). It joins the matrix as 'discovered' and
    raises a question; requests are only built once the owner confirms it belongs in scope."""
    existing = scope.first("systems", "last4=?", (last4,))
    if existing:
        return existing["id"], False
    sid = scope.insert("systems", kind=kind, name=name, last4=last4, status="discovered", discovered_from=discovered_from, created_at=iso())
    raise_exception(scope, "account_discovered", "blocker", f"Account ending {last4} appears in the records ({discovered_from}) "
                    "but isn't in the client file. Is it a business account (in scope) or personal?", ref=f"system:{sid}", needs="client")
    scope.conn.execute("INSERT INTO audit (client_id, actor, action, ref, at) VALUES (?,?,?,?,?)", (scope.cid, actor, "system_discovered", f"system:{sid}", iso()))
    return sid, True
