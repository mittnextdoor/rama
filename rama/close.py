"""The borrower's month-end close: Bob's engine on the borrower's books, traced as tools in the month's PRISM session.

The workspace is one engine file (SQLite) and the source files under data/rama/work/. A reviewer's decision on an
exception (post the entry the lender's statement supports; book an unexplained line to an account they choose) is posted
to the ledger with its citation and the month is closed again."""
import csv
import io
import json
import os
import shutil

from . import borrower as B
from . import tracing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.environ.get("RAMA_WORK") or os.path.join(ROOT, "data", "rama", "work")
SESSION = f"{B.CODE.lower()}-{B.PERIOD}"


def _engine():
    os.environ["OPS_FILES"] = os.path.join(WORK, "files")
    from ops import db as edb
    return edb


def _open():
    edb = _engine()
    from ops.qbo import SimulatedQBO
    econn = edb.connect(os.path.join(WORK, "engine.sqlite3"))
    cid = econn.execute("SELECT id FROM clients WHERE code=?", (B.CODE,)).fetchone()["id"]
    return econn, edb.Scope(econn, cid), SimulatedQBO(econn, realm="SIM-HELIOS")


def reset():
    """A fresh workspace: the borrower's books seeded, its source files stored and read. Returns the files list."""
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    edb = _engine()
    from ops.clientfile import open_client
    from ops.documents import ingest
    from ops.intake.store import convert
    from ops.qbo import SimulatedQBO
    econn = edb.connect(os.path.join(WORK, "engine.sqlite3"))
    cid = open_client(econn, code=B.CODE, legal_name=B.LEGAL_NAME, entity_type="llc_multi", activity="gpu cloud and data centers",
                      cleanup_start="2025-01-01", cleanup_end="2025-12-31", service_start=B.BOOKS_START, systems=[], basis="accrual",
                      synthetic=True, industry="service", intake={"engine": "evidence"}, mode="simulation", actor="rama")
    scope = edb.Scope(econn, cid)
    ad = SimulatedQBO(econn, realm="SIM-HELIOS")
    files = []
    for month, name, data in B.seed(ad):
        doc, _ = ingest(scope, data, name, "rama", meta={"stage": f"{month}/initial"})
        convert(scope, doc)
        files.append({"month": month, "name": name, "bytes": len(data)})
    with open(os.path.join(WORK, "files.json"), "w") as f:
        json.dump(files, f)
    econn.close()
    return files


def source_files():
    """The source package as the reviewer sees it: each file and its rows."""
    out = []
    folder = os.path.join(WORK, "files")
    econn, scope, _ = _open()
    try:
        for d in econn.execute("SELECT id, filename, path FROM documents ORDER BY id"):
            rows = []
            try:
                with open(d["path"], "rb") as f:
                    raw = f.read()
                if d["filename"].endswith(".csv"):
                    rows = list(csv.DictReader(io.StringIO(raw.decode())))
                else:
                    rows = [json.loads(raw)]
            except (OSError, ValueError):
                pass
            out.append({"id": d["id"], "name": d["filename"], "rows": rows})
    finally:
        econn.close()
    del folder
    return out


def lender_statements(scope, period):
    """The lenders' loan statements (kept by the intake as reference tables) for the month:
    [{loan, date, closing_principal, interest, pik, record}]."""
    out = []
    for r in scope.conn.execute("SELECT id, data_json FROM records WHERE client_id=? AND rtype='facts'", (scope.cid,)):
        data = json.loads(r["data_json"])
        for row in data.get("rows") or []:
            if not isinstance(row, dict) or not row.get("loan_id") or not str(row.get("date") or "").startswith(period):
                continue
            out.append({"loan": str(row["loan_id"]), "date": row["date"], "closing_principal": int(row["closing_principal_cents"]),
                        "interest": int(row.get("interest_paid_cents") or 0), "pik": int(row.get("pik_capitalized_cents") or 0),
                        "pik_to_date": int(row.get("pik_capitalized_to_date_cents") or 0),
                        "opening_principal": int(row.get("opening_principal_cents") or 0), "record": r["id"], "file": data.get("filename")})
    return out


def notices(scope, period):
    """The borrower's PIK election notices for the month: [{loan, election_date, accrued, cash, pik, record, file, page}]."""
    out = []
    for r in scope.conn.execute("SELECT id, data_json FROM records WHERE client_id=? AND rtype='facts'", (scope.cid,)):
        data = json.loads(r["data_json"])
        for row in data.get("rows") or []:
            if not isinstance(row, dict) or not row.get("election_date") or row.get("period") != period:
                continue
            out.append({"loan": str(row["loan_id"]), "election_date": row["election_date"], "accrued": int(row["interest_accrued_cents"]),
                        "cash": int(row["cash_paid_cents"]), "pik": int(row["pik_capitalized_cents"]), "record": r["id"],
                        "file": data.get("filename"), "page": int(row.get("notice_page") or 1)})
    return out


def _pik_split(final, scope, period):
    """A ledger interest entry outstanding against the bank, a smaller wire to the same lender unrecorded, and the
    difference equal to the PIK the borrower's election notice says was capitalized: one finding, with the entry the
    evidence supports (the cash part as paid, the PIK part added to the loan), for a person to accept."""
    for n in notices(scope, period):
        acct = B.ACCOUNT_MAP.get(n["loan"])
        wire = next((f for f in final["findings"] if f["check"] == "unrecorded" and "RAMA CREDIT FUND" in (f.get("fix") or {}).get("line", {}).get("description", "")
                     and abs(int(f["amount_cents"])) == n["cash"]), None)
        recon = next((r for r in final["recons"] if r["account"] == B.OPERATING), None)
        entry = next((o for o in (recon or {}).get("outstanding") or [] if abs(int(o.get("cents") or o.get("amount") or 0)) == n["accrued"]), None) if recon else None
        if not (wire and entry):
            continue
        lender = next((f for f in final["findings"] if f["check"] == "lender_difference" and n["loan"] in f["key"]), None)
        txn = str(entry.get("txn_id") or entry.get("txn") or "")
        fix = {"kind": "pik_split", "entity": entry.get("entity") or "Purchase", "txn_id": txn, "account": B.OPERATING, "loan_account": acct,
               "accrued_cents": n["accrued"], "cash_cents": n["cash"], "pik_cents": n["pik"], "date": wire["fix"]["line"]["date"], "line": wire["fix"]["line"],
               "citations": [f"line:{wire['fix']['line']['line_id']}", f"record:{n['record']}"] + ([f"record:{lender['refs'][0].split(':')[1]}"] if lender and lender.get("refs") else []),
               "why": f"the PIK election notice of {n['election_date']} (p.{n['page']}) says {n['pik'] / 1e8:,.2f}M was paid in kind", "auto": False}
        f = {"key": f"pik_split:{n['loan']}:{period}", "check": "pik_split", "severity": "blocker",
             "title": f"{B.OPERATING}: interest on {n['loan']} booked as {n['accrued'] / 1e8:,.2f}M paid in cash; the bank shows a {n['cash'] / 1e8:,.2f}M wire",
             "detail": (f"The difference, {n['pik'] / 1e8:,.2f}M, matches the borrower's PIK election notice dated {n['election_date']} ({n['file']}, p.{n['page']}): "
                        f"that part was paid in kind and added to the loan. Proposed: record the wire as the cash interest and {n['pik'] / 1e8:,.2f}M as PIK capitalized to {acct}."),
             "account": B.OPERATING, "amount_cents": -n["pik"], "refs": fix["citations"], "fix": fix, "who": "reviewer"}
        final["findings"] = [x for x in final["findings"] if x is not wire and x is not lender] + [f]
    return final


def _inputs():
    return {"period": B.PERIOD, "account_map": B.ACCOUNT_MAP, "schedules": B.SCHEDULES, "rules": [], "books_start": B.BOOKS_START}


def _clean(x):
    """Engine text shown to people: the agents' tag is RAMA's."""
    if isinstance(x, str):
        for a, b in (("NHB: ", "RAMA: "), ("NHB schedule", "RAMA schedule"), ("isn't in QuickBooks", "isn't in the books"),
                     ("QuickBooks has", "the books have"), ("QuickBooks already", "The books already"), ("QuickBooks", "the books")):
            x = x.replace(a, b)
        return x
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    return x


def run(*, ask_model=True, label="close"):
    """Close the month. Returns the close record (JSON-ready)."""
    from bob import engine
    from ops.native import evidence
    econn, scope, ad = _open()
    original = evidence.lender_statements
    evidence.lender_statements = lambda sc, period: [dict(x) for x in lender_statements(sc, period)]
    try:
        task = (f"Close {B.PERIOD} for {B.LEGAL_NAME} (synthetic borrower, loan {B.LOAN_ID}): tie the bank statements and the lenders' "
                "statements to the books, record what the evidence supports, build the workpapers, leave the rest for a person.")
        with tracing.session(SESSION, "RAMA close", agent_id="rama-close", kind="close", task=task,
                             meta={"company": B.CODE, "period": B.PERIOD, "label": label}) as r:
            with tracing.step("read_source_package", "retrieval", {"company": B.CODE, "period": B.PERIOD}) as st:
                with open(os.path.join(WORK, "files.json")) as fh:
                    files = json.load(fh)
                st.out({"files": [f["name"] for f in files]})
            result = engine.close_month(ad, scope, _inputs(), ask_model=ask_model, client_code="RAMA")
            final = result["final"]
            with tracing.step("match_pik_election_notice", "tool", {"period": B.PERIOD}) as st:
                _pik_split(final, scope, B.PERIOD)
                st.out({"pik_split": [f["key"] for f in final["findings"] if f["check"] == "pik_split"]})
            blockers = [f for f in final["findings"] if f["severity"] == "blocker"]
            papers = final.get("workpapers") or []
            ties = sum(1 for x in final["recons"] if x["difference"] == 0)
            summary = (f"{B.LEGAL_NAME} {B.PERIOD}: {ties} of {len(final['recons'])} bank accounts tie; {len(result['applied'])} change(s) made "
                       f"with citations; {len(blockers)} blocker(s) left for a person; {sum(1 for p in papers if p['status'] == 'tied')} of "
                       f"{len(papers)} workpapers tied.")
            rec = r.finish(summary, status="success")
        lenders = lender_statements(scope, B.PERIOD)
        out = {"company": {"code": B.CODE, "name": B.LEGAL_NAME, "proxy": B.PROXY, "loan": B.LOAN_ID, "period": B.PERIOD},
               "first": result["first"], "final": {"findings": final["findings"], "recons": final["recons"], "workpapers": papers},
               "applied": result["applied"], "failed": result["failed"], "statements": result["statements"], "lenders": lenders,
               "notices": notices(scope, B.PERIOD),
               "model_called": result["model_called"], "rounds": result["rounds"], "run_id": rec["run_id"], "summary": summary,
               "steps": rec["steps"], "session": SESSION}
        return _clean(json.loads(json.dumps(out, default=str)))
    finally:
        evidence.lender_statements = original
        econn.close()


def resolve(finding, decision):
    """A person's decision on one exception, posted to the books with its citation. decision:
    {"action": "post_lender_entry"} for a lender difference (the entry the lender's statement supports), or
    {"action": "book_line", "account": <name>} for an unrecorded statement line, or {"action": "leave_open", "note": ...}."""
    from ops.native import fixes
    econn, scope, ad = _open()
    try:
        with tracing.session(SESSION, "RAMA review decision", agent_id="rama-review", kind="review",
                             task=f"Reviewer decision on {finding['key']}: {decision.get('action')}", meta={"finding": finding["key"]}) as r:
            with tracing.step(f"reviewer_decision {decision.get('action')}", "tool", {"finding": finding["key"], "decision": decision}) as st:
                if decision["action"] == "post_lender_entry":
                    stmts = lender_statements(scope, B.PERIOD)
                    parts = finding["key"].split(":")
                    stmt = next(x for x in stmts if x["loan"] in parts)
                    loan = stmt["loan"]
                    acct = B.ACCOUNT_MAP.get(loan)
                    diff = int(finding["amount_cents"])               # books - lender (books show less owed: negative)
                    if diff >= 0:
                        raise ValueError("the books already owe at least what the lender says: nothing to post")
                    lines = [("Interest Expense - PIK", -diff), (acct, diff)]
                    fx = {"kind": "journal", "lines": [[a, c] for a, c in lines], "date": stmt["date"],
                          "memo": f"PIK interest capitalized per lender statement {loan} {stmt['date']} (record {stmt['record']})",
                          "citations": [f"record:{stmt['record']}"]}
                    from tests.native_company import _je
                    entity, doc = _je(stmt["date"], f"RAMA: {fx['memo']}", lines)
                    tid = ad.create(entity, doc, f"rama-review-{finding['key']}")
                    st.out({"posted": "JournalEntry", "id": tid, "lines": fx["lines"], "citations": fx["citations"]})
                elif decision["action"] == "accept_pik_split":
                    fx = finding["fix"]
                    from tests.native_company import _je, _purchase
                    ad.delete(fx["entity"], fx["txn_id"])
                    p_entity, p_doc = _purchase(B.OPERATING, "Interest Expense", fx["cash_cents"], fx["date"], f"RAMA: L2 September cash interest per bank line {fx['line']['line_id']}")
                    cash_id = ad.create(p_entity, p_doc, f"rama-review-{finding['key']}-cash")
                    j_entity, j_doc = _je(fx["date"], f"RAMA: PIK interest capitalized per election notice (record {fx['citations'][1].split(':')[1]})",
                                          [("Interest Expense - PIK", fx["pik_cents"]), (fx["loan_account"], -fx["pik_cents"])])
                    pik_id = ad.create(j_entity, j_doc, f"rama-review-{finding['key']}-pik")
                    st.out({"replaced": fx["txn_id"], "posted": {"cash": cash_id, "pik": pik_id}, "cash_cents": fx["cash_cents"], "pik_cents": fx["pik_cents"],
                            "citations": fx["citations"]})
                elif decision["action"] == "book_line":
                    fx = dict(finding["fix"], to=decision["account"], auto=True, citations=finding.get("refs") or [],
                              why=f"a reviewer chose {decision['account']}" + (f": {decision['note']}" if decision.get("note") else ""))
                    out = fixes.apply(ad, fx, "RAMA")
                    st.out({"posted": out["entity"], "id": out["external_id"], "effect": out["effect"], "citations": fx["citations"]})
                else:
                    st.out({"left_open": True, "note": decision.get("note")})
            r.finish(f"Reviewer decision on {finding['key']}: {decision.get('action')}", status="success")
    finally:
        econn.close()
