"""The client's evidence for the close, as the intake read it from their files: bank and card statements (each a control
with its opening and closing balance, and its lines), lender statements, and the client's own lists.

Statements name accounts the client's way ("1000", "****4417", "2100"); the ledger names them its own way ("Checking",
"1000 Operating checking"). account_for() settles which ledger account a statement is, from a person's account map first,
then the account number, the name, or the last four digits, and says so when it can't."""
import re

from ..intake.store import active


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _last4(s):
    m = re.search(r"(\d{4})\D*$", str(s or ""))
    return m.group(1) if m else None


def account_for(ref, chart, account_map=None, client_names=None):
    """The ledger account (name) a statement's account reference is, or None. chart: the ledger's chart (read.snapshot),
    account_map: {client account: ledger account name} a person or onboarding settled, client_names: {client account:
    its name in the client's chart}."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    cands = [a for a in chart if a["type"] in ("Bank", "Credit Card") or (a.get("classification") in ("Asset", "Liability")
                                                                          and "clearing" not in a["name"].lower())]
    names = {a["name"] for a in cands}
    mapped = (account_map or {}).get(ref)
    if mapped in names:
        return mapped
    hits = [a["name"] for a in cands if str(a.get("number") or "") == ref or a["name"] == ref or a["name"].startswith(ref + " ")]
    if len(hits) == 1:
        return hits[0]
    own = (client_names or {}).get(ref)
    if own:
        hits = [a["name"] for a in cands if _norm(a["name"]) == _norm(own)]
        if len(hits) == 1:
            return hits[0]
    four = _last4(ref)
    if four:
        hits = [a["name"] for a in cands if a["type"] in ("Bank", "Credit Card") and _last4(a["name"]) == four]
        if len(hits) == 1:
            return hits[0]
    return None


def statements(scope):
    """[{ref, start, end, opening, closing, kind}] for every bank and card statement held, debit-positive (a card's
    balance owed is negative)."""
    out = []
    for c in active(scope, "statement_control"):
        if c.get("account") and c.get("coverage_end") and c.get("closing_cents") is not None:
            out.append({"ref": str(c["account"]), "start": c.get("coverage_start"), "end": c["coverage_end"],
                        "opening": c.get("opening_cents"), "closing": c["closing_cents"], "kind": "bank", "record": c["_id"]})
    for c in active(scope, "card_cycle_control"):
        end = c.get("end") or c.get("coverage_end")
        if end and c.get("closing_liability_cents") is not None:
            op = c.get("opening_liability_cents")
            out.append({"ref": str(c.get("account") or ""), "start": c.get("start") or c.get("coverage_start"), "end": end,
                        "opening": -op if op is not None else None, "closing": -c["closing_liability_cents"], "kind": "card", "record": c["_id"]})
    return sorted(out, key=lambda s: (s["ref"], s["end"]))


def lines(scope):
    """{statement account ref: [{line_id, date, amount, description, reference}]}."""
    out = {}
    for ln in active(scope, "bank_line"):
        if not ln.get("date") or ln.get("amount") is None:
            continue
        out.setdefault(str(ln.get("account") or ""), []).append({
            "line_id": str(ln.get("line_id") or f"r{ln['_id']}"), "date": ln["date"], "amount": int(ln["amount"]),
            "description": ln.get("description"), "reference": ln.get("reference"), "record": ln["_id"]})
    return out


def client_chart(scope):
    return {str(a["account"]): a.get("account_name") or "" for a in active(scope, "chart")}


def lender_statements(scope, period):
    """Loan and line-of-credit statements dated in the month: [{loan, date, closing_principal, interest, payment}]."""
    out = []
    for rtype in ("schedule", "loan_activity", "reference"):
        for r in active(scope, rtype):
            loan = r.get("loan_id") or r.get("facility_id")
            if not loan or r.get("closing_principal_cents") is None or not str(r.get("date") or "").startswith(period):
                continue
            out.append({"loan": str(loan), "date": r["date"], "closing_principal": int(r["closing_principal_cents"]),
                        "interest": r.get("interest_paid_cents"), "record": r["_id"]})
    return out


def payroll(scope, period):
    """The month's payroll runs from the payroll register: [{run, date, gross, net, withheld, employer, record}] (cents)."""
    out = []
    for r in active(scope, "payroll_run"):
        if not str(r.get("date") or "").startswith(period) or r.get("gross_pay") is None:
            continue
        out.append({"run": str(r.get("run_id")), "date": r["date"], "gross": int(r["gross_pay"]), "net": int(r.get("net") or 0),
                    "withheld": int(r.get("employee_withheld") or 0), "employer": int(r.get("employer_burden") or 0), "record": r["_id"]})
    return out
