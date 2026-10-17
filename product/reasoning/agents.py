"""The reasoning agents: what each one is given (only the records it needs), the shape of its answer, the deterministic
checks its answer must pass, and what a person's acceptance does. None of them posts, pays, approves or releases.

  classifier        a held bank or card line (nothing explained it) -> a suggested account, cited, with its confidence;
                    accepted: a one-line decision rule (product/decisions.py), which the engine books on the next run
  reviewer          the month's figures the deterministic checks flagged -> observations and questions for the reviewer;
                    accepted: recorded as reviewed (it changes nothing in the books)
  client_questions  the month's open requests -> a plain-language draft to the client; accepted: a drafted message
                    (product/requests.py); sending stays off
  layout_mapper     a table no built-in, learned or client layout reads (its columns and first rows) -> what the rows are and which
                    column is which field, or what the file is if it isn't records; checked against every row before a person
                    sees it; accepted: the client's column mapping (or file role), which the firm learns, so the next file
                    with the same columns is read without asking the model again (product/layoutagent.py)"""
import json
import re

from . import config

ITEM_LIMIT = 25


def _numbers(text):
    """Digit groups of three or more in a text (amounts, account numbers), normalized: what an answer may only repeat."""
    return {re.sub(r"[,]", "", m).split(".")[0].lstrip("0") or "0" for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "") if len(re.sub(r"\D", "", m)) >= 3}


def _unsupported_numbers(texts, context):
    have = _numbers(json.dumps(context))
    have |= {str(abs(int(x)) // 100) for x in re.findall(r"-?\d{3,}", json.dumps(context))}   # cents also as whole dollars
    out = []
    for t in texts:
        out += [n for n in _numbers(t) if n not in have]
    return out


# ------------------------------------------------------------------ classifier
class Classifier:
    name = "classifier"
    tool = "record_suggestions"
    batched = True
    schema = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
        "type": "array", "minItems": 1, "maxItems": ITEM_LIMIT, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "decision", "account", "confidence", "evidence_ids", "rationale", "uncertainty", "question_for_client"],
            "properties": {"id": {"type": "string"}, "decision": {"enum": ["propose", "insufficient_information"]},
                           "account": {"type": ["string", "null"]}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                           "evidence_ids": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "string"}},
                           "rationale": {"type": "string", "maxLength": 400}, "uncertainty": {"type": ["string", "null"], "maxLength": 300},
                           "question_for_client": {"type": ["string", "null"], "maxLength": 300}}}}}}

    def subjects(self, conn, c, p):
        """Held lines a person would otherwise categorize from scratch (nothing explained them, or the chart and the books
        disagree), and lines booked only on a word in their description (a second opinion on the guess). Each needs its
        statement row (evidence) to be sent."""
        rows = conn.execute("SELECT e.id, e.message, e.run_id FROM exceptions e WHERE e.period_id=%s AND e.status='open' AND "
                            "((e.code='held_entry' AND (e.message LIKE %s OR e.message LIKE %s)) OR e.code='keyword_guess') ORDER BY e.id",
                            (p["id"], "%nothing says what this is%", "%the chart suggests%")).fetchall()
        return [("exception", str(r["id"])) for r in rows]

    def context(self, conn, c, p, refs):
        items, missing = [], []
        for ref in refs:
            ev = conn.execute("SELECT excerpt, row_no, record_type FROM evidence_links WHERE subject_type='exception' AND subject_id=%s "
                              "AND record_type='bank_line' ORDER BY id LIMIT 1", (int(ref),)).fetchone()
            if ev is None:
                missing.append(ref)
                continue
            x = ev["excerpt"] or {}
            item = {"id": f"x{ref}", "line": {"date": x.get("date"), "amount_cents": x.get("amount"), "description": x.get("description"),
                                              "statement_account": x.get("account"), "line_id": x.get("line_id")}}
            guess = conn.execute("SELECT cl.account FROM exceptions e JOIN change_sets cs ON cs.period_id=e.period_id AND cs.status<>'superseded' "
                                 "JOIN change_lines cl ON cl.change_set_id=cs.id AND cl.correction_key=split_part(e.ref, ':', 2) "
                                 "WHERE e.id=%s AND e.code='keyword_guess' AND cl.account<>%s LIMIT 1", (int(ref), str(x.get("account")))).fetchone()
            if guess:                                      # booked on a keyword only: the model is asked whether that's right
                item["booked_on_a_keyword_to"] = guess["account"]
            items.append(item)
        run = conn.execute("SELECT statements FROM runs WHERE period_id=%s AND statements <> '{}'::jsonb ORDER BY id DESC LIMIT 1", (p["id"],)).fetchone()
        accounts = ((run or {}).get("statements") or {}).get("accounts") or []
        cash = {r["account"] for r in conn.execute("SELECT DISTINCT account FROM reconciliations WHERE client_id=%s", (c["id"],)).fetchall()}
        cash |= {str(i["line"]["statement_account"]) for i in items if i["line"]["statement_account"]}
        chart = [{"id": f"chart:{a['account']}", "account": a["account"], "name": a["name"], "type": a["type"]} for a in accounts
                 if a["account"] not in cash]
        rules = [{"id": f"rule:{r['rule_key']}", "match": r["match"], "account": r["treatment"].get("account")} for r in conn.execute(
            "SELECT rule_key, match, treatment FROM decision_rules WHERE client_id=%s AND status='approved' ORDER BY id LIMIT 20", (c["id"],)).fetchall()]
        from .. import knowledge
        words = " ".join(str(i["line"].get("description") or "") for i in items)
        # the firm's memory: how lines like these were decided before, for this client first, then across the firm
        history = []
        for r in conn.execute("SELECT d.rule_key, d.match, d.treatment, d.client_id = %s AS own FROM decision_rules d WHERE d.firm_id=%s "
                              "AND d.status='approved' AND (d.match ? 'description' OR d.match ? 'pattern') ORDER BY (d.client_id = %s) DESC, d.id DESC LIMIT 200",
                              (c["id"], c["firm_id"], c["id"])).fetchall():
            m = r["match"] or {}
            said = str(m.get("description") or m.get("pattern") or "")
            if set(knowledge._words(said)) & set(knowledge._words(words)):
                history.append({"id": f"history:{r['rule_key']}", "matched": said[:120], "account": (r["treatment"] or {}).get("account"),
                                "this_client": bool(r["own"])})
            if len(history) >= 8:
                break
        basis = knowledge.client_basis(conn, c["id"])
        ctx = {"client": c["legal_name"], "month": p["label"], "basis": basis or "unknown", "items": items, "chart": chart, "rules": rules,
               "cash_accounts": sorted(cash), "history": history,
               "firm_rules": knowledge.basis_rules(conn, c["id"]),
               "guidance": knowledge.for_client(conn, c["id"], words, k=4) if words.strip() else []}
        return ctx, missing

    def evidence_ids(self, ctx):
        return {i["id"] for i in ctx["items"]} | {a["id"] for a in ctx["chart"]} | {r["id"] for r in ctx["rules"]} | \
            {h["id"] for h in ctx.get("history") or []} | {g["id"] for g in ctx.get("firm_rules") or []} | {g["id"] for g in ctx.get("guidance") or []}

    def check(self, output, ctx, cfg):
        """Per item: (problems, escalate?). Deterministic: the account exists and isn't a cash account; evidence is cited
        from what was given, including the line itself; low confidence or not enough information goes up."""
        chart = {a["account"] for a in ctx["chart"]}
        ids = self.evidence_ids(ctx)
        given = {i["id"] for i in ctx["items"]}
        seen, out = set(), {}
        for it in output["items"]:
            probs = []
            if it["id"] not in given or it["id"] in seen:
                probs.append(f"{it['id']}: not one of the items asked about, or answered twice")
            seen.add(it["id"])
            if it["decision"] == "propose":
                if not it["account"]:
                    probs.append("proposes no account")
                elif it["account"] not in chart:
                    probs.append(f"account {it['account']} isn't in the client's chart (or is a cash account)")
            if not set(it["evidence_ids"]) <= ids:
                probs.append(f"cites evidence it wasn't given: {sorted(set(it['evidence_ids']) - ids)}")
            if it["id"] not in it["evidence_ids"]:
                probs.append("doesn't cite the transaction itself")
            low = it["decision"] != "propose" or it["confidence"] < cfg["confidence_threshold"]
            out[it["id"]] = (probs, bool(probs) or low)
        for missing in given - seen:
            out[missing] = (["not answered"], True)
        return out

    def accept(self, conn, ident, decision, task, choice):
        """A person accepts the suggestion (or picks another account): a one-line rule, approved by them; the engine books
        the line on the next run. Returns the effect."""
        from .. import decisions
        item = decision["output"]
        account = (choice or {}).get("account") or item.get("account")
        if not account:
            raise ValueError("choose an account")
        ev = conn.execute("SELECT excerpt FROM evidence_links WHERE subject_type='exception' AND subject_id=%s AND record_type='bank_line' LIMIT 1",
                          (int(task["subject_ref"]),)).fetchone()
        line_id = ((ev or {}).get("excerpt") or {}).get("line_id")
        if not line_id:
            raise ValueError("the line has no line id to decide it by")
        rule = decisions.propose(conn, ident, task["client_id"], scope="item", match={"line_id": line_id}, treatment={"account": account},
                                 reason=f"Accepted the classifier's suggestion (decision {decision['id']}): {item.get('rationale', '')[:300]}",
                                 source_exception_id=int(task["subject_ref"]))
        decisions.approve(conn, ident, rule["id"], note="accepted from the classifier's suggestion")
        return {"rule": rule["rule_key"], "account": account, "line_id": line_id}


# ------------------------------------------------------------------ reviewer
class Reviewer:
    name = "reviewer"
    tool = "record_observations"
    batched = False
    schema = {"type": "object", "additionalProperties": False, "required": ["overall", "observations", "uncertainty"], "properties": {
        "overall": {"enum": ["no_concerns", "questions"]},
        "observations": {"type": "array", "maxItems": 10, "items": {"type": "object", "additionalProperties": False,
                                                                     "required": ["flag_id", "observation", "question", "severity"],
                                                                     "properties": {"flag_id": {"type": "string"},
                                                                                    "observation": {"type": "string", "maxLength": 400},
                                                                                    "question": {"type": "string", "maxLength": 300},
                                                                                    "severity": {"enum": ["info", "review"]}}}},
        "uncertainty": {"type": ["string", "null"], "maxLength": 300}}}

    def flags(self, conn, c, p):
        """Deterministic first: only figures that look unusual go to the model (and none at all when nothing does)."""
        from .. import auth, service
        owner = conn.execute("SELECT * FROM users WHERE firm_id=%s AND role='owner' ORDER BY id LIMIT 1", (c["firm_id"],)).fetchone()
        ident = auth.Identity(owner["id"], owner["firm_id"], owner["role"], owner["email"], owner["name"])
        st = service.statements(conn, ident, c["id"], p["id"])
        if not st.get("available"):
            return []
        out = []
        pl = st["profit_and_loss"]
        for sec in pl["sections"]:
            for r in sec["rows"]:
                if sec["key"] in ("expense", "cost_of_sales", "other_expense") and r["month_cents"] < 0:
                    out.append({"why": "an expense with a credit (negative) amount this month", "account": r["account"], "name": r["name"],
                                "month_cents": r["month_cents"]})
                if sec["key"] in ("revenue", "other_income") and r["month_cents"] < 0:
                    out.append({"why": "income with a debit (negative) amount this month", "account": r["account"], "name": r["name"],
                                "month_cents": r["month_cents"]})
                rec, chg = r["recorded_month_cents"], r["change_month_cents"]
                if chg and abs(chg) >= 50000 and (not rec or abs(chg) * 4 >= abs(rec)):
                    out.append({"why": "the proposed changes move this account by a quarter or more", "account": r["account"], "name": r["name"],
                                "recorded_cents": rec, "change_cents": chg, "month_cents": r["month_cents"]})
        rev = pl["month"]["revenue"]
        if rev > 0 and (pl["month"]["gross_profit"] < 0 or pl["month"]["net_income"] < -rev):
            out.append({"why": "a gross loss, or a net loss larger than revenue", "revenue_cents": rev, "gross_profit_cents": pl["month"]["gross_profit"],
                        "net_income_cents": pl["month"]["net_income"]})
        for i, f in enumerate(out, 1):
            f["id"] = f"flag:{i}"
        return out

    def subjects(self, conn, c, p):
        return [("month", str(p["id"]))]

    def context(self, conn, c, p, refs):
        flags = self.flags(conn, c, p)
        findings = [{"code": e["code"], "severity": e["severity"], "message": e["message"][:200]} for e in conn.execute(
            "SELECT code, severity, message FROM exceptions WHERE period_id=%s AND status='open' ORDER BY id LIMIT 15", (p["id"],)).fetchall()]
        return {"client": c["legal_name"], "month": p["label"], "flags": flags, "open_findings": findings}, ([] if flags else ["nothing flagged"])

    def evidence_ids(self, ctx):
        return {f["id"] for f in ctx["flags"]}

    def check(self, output, ctx, cfg):
        probs = []
        ids = self.evidence_ids(ctx)
        for o in output["observations"]:
            if o["flag_id"] not in ids:
                probs.append(f"cites {o['flag_id']}, which wasn't flagged")
        bad = _unsupported_numbers([o["observation"] + " " + o["question"] for o in output["observations"]], ctx)
        if bad:
            probs.append(f"uses numbers that aren't in the data: {sorted(set(bad))[:5]}")
        if output["overall"] == "questions" and not output["observations"]:
            probs.append("says there are questions but gives none")
        return {"month": (probs, bool(probs))}

    def accept(self, conn, ident, decision, task, choice):
        return {"reviewed": True, "changes_to_books": None}


# ------------------------------------------------------------------ client questions
class ClientQuestions:
    name = "client_questions"
    tool = "record_draft"
    batched = False
    schema = {"type": "object", "additionalProperties": False, "required": ["subject", "items", "closing"], "properties": {
        "subject": {"type": "string", "maxLength": 120},
        "items": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "additionalProperties": False,
                                                                           "required": ["request_id", "question"],
                                                                           "properties": {"request_id": {"type": "string"},
                                                                                          "question": {"type": "string", "maxLength": 400}}}},
        "closing": {"type": "string", "maxLength": 300}}}

    def subjects(self, conn, c, p):
        return [("requests", str(p["id"]))]

    def context(self, conn, c, p, refs):
        reqs = conn.execute("SELECT id, what, why, blocking FROM client_requests WHERE period_id=%s AND status='open' AND duplicate_of IS NULL "
                            "AND answered_by_role='client' ORDER BY id", (p["id"],)).fetchall()
        items = [{"id": f"req:{r['id']}", "what": r["what"], "why": r["why"], "holds_the_close": r["blocking"]} for r in reqs]
        return {"client": c["legal_name"], "month": p["label"], "requests": items}, ([] if items else ["no open requests"])

    def evidence_ids(self, ctx):
        return {r["id"] for r in ctx["requests"]}

    def check(self, output, ctx, cfg):
        probs = []
        want = self.evidence_ids(ctx)
        got = [i["request_id"] for i in output["items"]]
        if sorted(got) != sorted(want):
            probs.append(f"must cover each open request exactly once: missing {sorted(want - set(got))}, extra {sorted(set(got) - want)}")
        bad = _unsupported_numbers([output["subject"], output["closing"]] + [i["question"] for i in output["items"]], ctx)
        if bad:
            probs.append(f"uses numbers that aren't in the requests: {sorted(set(bad))[:5]}")
        return {"requests": (probs, bool(probs))}

    def accept(self, conn, ident, decision, task, choice):
        out = decision["output"]
        body = "\n".join([f"{out['subject']}\n"] + [f"{n}. {i['question']}" for n, i in enumerate(out["items"], 1)] + ["", out["closing"],
                         "", f"(Drafted with model assistance; reviewed by {ident.name}.)"])
        ids = [int(i["request_id"].split(":")[1]) for i in out["items"]]
        m = conn.execute("INSERT INTO request_messages (firm_id, client_id, period_id, request_ids, body, created_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                         (ident.firm_id, task["client_id"], task["period_id"], ids, body, ident.user_id)).fetchone()
        return {"request_message": m["id"], "sent": False}


# ------------------------------------------------------------------ layout mapper
ROLES = ("list", "schedule", "evidence", "brief", "not_used")
LIST_KINDS = ("vendors", "customers", "employees", "projects", "other")
SAMPLE_ROWS = 8


class LayoutMapper:
    """One table at a time (subject "document", ref "<document id>:<sheet>"): its columns, its first rows and what the
    agents can read. The answer is checked by the same code a person's mapping is (product/mappings.evaluate) against
    every row of the file: a mapping that sets rows aside, or misses a field every row needs, goes to the escalation model,
    then to a person, never through."""
    name = "layout_mapper"
    tool = "propose_layout"
    batched = False
    schema = {"type": "object", "additionalProperties": False,
              "required": ["kind", "record_type", "role", "list_kind", "columns", "negate", "units", "date_order", "constants", "confidence",
                           "rationale", "uncertainty"],
              "properties": {
                  "kind": {"enum": ["records", "role", "unknown"]},
                  "record_type": {"type": "string", "maxLength": 40},
                  "role": {"enum": list(ROLES) + ["none"]},
                  "list_kind": {"enum": list(LIST_KINDS) + ["none"]},
                  "columns": {"type": "array", "maxItems": 40, "items": {"type": "object", "additionalProperties": False, "required": ["field", "column"],
                                                                          "properties": {"field": {"type": "string"}, "column": {"type": "string"}}}},
                  "negate": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
                  "units": {"enum": ["as_written", "dollars", "cents"]},
                  "date_order": {"enum": ["mdy", "dmy", "ymd"]},
                  "constants": {"type": "array", "maxItems": 5, "items": {"type": "object", "additionalProperties": False, "required": ["field", "value"],
                                                                          "properties": {"field": {"type": "string"}, "value": {"type": "string", "maxLength": 60}}}},
                  "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                  "rationale": {"type": "string", "maxLength": 400},
                  "uncertainty": {"type": ["string", "null"], "maxLength": 300}}}

    def __init__(self):
        self._tables = {}                                 # (file, columns) -> the table, for checking the answer against every row

    def subjects(self, conn, c, p):
        return []                                         # planned per file by product/layoutagent.py, not per month

    def table(self, conn, ref):
        """The document and the table a ref names (the mapping screen's sheet numbering)."""
        from .. import mappings, storage
        doc_id, _, sheet = ref.partition(":")
        d = conn.execute("SELECT * FROM documents WHERE id=%s", (int(doc_id),)).fetchone()
        if d is None:
            return None, None
        tables = mappings._tables(d["filename"], storage.store().get(d["storage_key"]))
        i = int(sheet or 0)
        return d, (tables[i] if 0 <= i < len(tables) else None)

    def context(self, conn, c, p, refs):
        from ops.intake import layouts as L
        from .. import mappings
        d, t = self.table(conn, refs[0])
        if t is None or not t.headers or not t.rows:
            return {}, [f"{refs[0]}: no table with rows"]
        self._tables[(d["filename"], tuple(t.headers))] = t
        cut = lambda v: "" if v is None else str(v)[:60]  # noqa: E731
        types = [{"record_type": r["record_type"], "label": r["label"], "required": [f["field"] for f in r["fields"] if f["required"]],
                  "every_row_needs": [f["field"] for f in r["fields"] if f["every_row"] and not f["required"]],
                  "optional": [f["field"] for f in r["fields"] if not f["required"] and not f["every_row"]]} for r in mappings.catalogue()]
        return {"file": d["filename"], "sheet": t.meta.get("sheet") or t.meta.get("table") or t.name, "columns": list(t.headers),
                "rows_total": len(t.rows), "first_rows": [{h: cut(r.get(h)) for h in t.headers} for r in t.rows[:SAMPLE_ROWS]],
                "amounts": "integer cents (the column names say so)" if t.units == "cents" else "as written",
                "record_types": types, "roles": {"list": "a list of vendors, customers, employees or projects (names and terms)",
                                                 "schedule": "a schedule or agreement (loan, insurance, cost certificates)",
                                                 "evidence": "supporting evidence for other lines (approvals, receipts), never booked itself",
                                                 "brief": "the client's brief or policies", "not_used": "nothing to read from it"},
                "list_kinds": list(LIST_KINDS), "money_fields": sorted({f for r in types for f in r["required"] + r["optional"] + r["every_row_needs"]
                                                                        if L.kind_of(f) == "money"})}, []

    @staticmethod
    def mapping(output):
        """The answer as a mapping body (product/mappings.py): record type, columns, value rules."""
        rules = {}
        if output.get("negate"):
            rules["negate"] = list(output["negate"])
        if output.get("units") in ("dollars", "cents"):
            rules["units"] = output["units"]
        if output.get("date_order") in ("dmy", "ymd"):
            rules["date_order"] = output["date_order"]
        if output.get("constants"):
            rules["constants"] = {x["field"]: x["value"] for x in output["constants"]}
        return {"record_type": output.get("record_type"), "columns": {x["field"]: x["column"] for x in output.get("columns") or []}, "rules": rules}

    def check(self, output, ctx, cfg):
        """Deterministic: a known record type, the file's own columns, every row read (none set aside, nothing every row
        needs left out); or a known role. Low confidence, "unknown" or any problem goes up."""
        from .. import mappings
        from ..errors import ProductError
        probs = []
        if output["kind"] == "records":
            t = self._tables.get((ctx.get("file"), tuple(ctx.get("columns") or ())))
            try:
                m = self.mapping(output)
                r = mappings.evaluate(t, m["record_type"], m["columns"], rules=m["rules"])
                if r["missing"]:
                    probs.append("no column for " + ", ".join(x["label"] for x in r["missing"]))
                if r["rows_set_aside"]:
                    probs.append(f"{r['rows_set_aside']} of {r['rows_total']} row(s) would be set aside (row {r['set_aside'][0]['row']}: {r['set_aside'][0]['why']})")
                if not r["rows_readable"]:
                    probs.append("no row can be read")
            except ProductError as e:
                probs.append(str(e))
            except Exception as e:                        # noqa: BLE001  (a malformed answer is the model's problem, said)
                probs.append(f"the mapping can't be applied: {e}")
        elif output["kind"] == "role":
            if output["role"] == "none":
                probs.append("says it's a role but names none")
            if output["role"] == "list" and output["list_kind"] == "none":
                probs.append("says it's a list but not of what")
        else:
            probs.append("couldn't say what the file is")
        low = output["kind"] == "unknown" or output["confidence"] < cfg["confidence_threshold"]
        return {"document": (probs, bool(probs) or low)}

    def accept(self, conn, ident, decision, task, choice):
        """A person approves the proposal: the client's column mapping (or the file's role, for every file with these
        columns). The firm learns it either way (product/learning.py)."""
        from .. import fileroles, mappings
        out = decision["output"]
        doc_id, _, sheet = task["subject_ref"].partition(":")
        if out["kind"] == "records":
            body = {**self.mapping(out), "sheet": int(sheet or 0), "from_agent": True}
            r = mappings.approve(conn, ident, int(doc_id), body)
            return {"mapping": (r.get("mapping") or {}).get("id"), "record_type": body["record_type"]}
        if out["kind"] == "role":
            fileroles.set_role(conn, ident, int(doc_id), out["role"], scope="layout", list_kind=out["list_kind"] if out["role"] == "list" else None,
                               reason=f"proposed by the layout agent (decision {decision['id']})")
            return {"role": out["role"]}
        raise ValueError("the agent didn't say what the file is")


# ------------------------------------------------------------------ onboarding reader
TEXT_LIMIT = 14000


class OnboardingReader:
    """One document's text (a brief, an engagement letter, a policy, an email) -> the accounting basis, entity type and
    fiscal year-end it states, each with the sentence that states it. Asked only when the patterns in
    product/onboardagent.py find nothing. Checked: each value is one the fact allows, and its quote is in the document word
    for word; a person confirms each fact (product/onboardagent.py)."""
    name = "onboarding"
    tool = "record_facts"
    batched = False
    schema = {"type": "object", "additionalProperties": False, "required": ["facts", "confidence", "uncertainty"], "properties": {
        "facts": {"type": "array", "maxItems": 3, "items": {"type": "object", "additionalProperties": False, "required": ["fact", "value", "quote"],
                                                             "properties": {"fact": {"enum": ["basis", "entity_type", "fiscal_year_end"]},
                                                                            "value": {"type": "string", "maxLength": 40},
                                                                            "quote": {"type": "string", "maxLength": 300}}}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "uncertainty": {"type": ["string", "null"], "maxLength": 300}}}

    def subjects(self, conn, c, p):
        return []                                         # planned per document by product/onboardagent.py

    def context(self, conn, c, p, refs):
        from .. import facts
        from ..onboardagent import document_text
        d = conn.execute("SELECT id, filename FROM documents WHERE id=%s AND client_id=%s", (int(refs[0]), c["id"])).fetchone()
        if d is None:
            return {}, [f"{refs[0]}: not this client's document"]
        text = document_text(conn, d)
        if not text.strip():
            return {}, [f"{d['filename']}: no text"]
        return {"file": d["filename"], "text": text[:TEXT_LIMIT],
                "facts": {"basis": list(facts.FACTS["basis"]["values"]), "entity_type": list(facts.ENTITY_TYPES),
                          "fiscal_year_end": "MM-DD, the last day of the fiscal year"}}, []

    def check(self, output, ctx, cfg):
        from .. import facts
        from ..errors import Invalid
        probs = []
        squash = lambda t: re.sub(r"\s+", " ", str(t or "")).strip().lower()   # noqa: E731
        text = squash(ctx.get("text"))
        seen = set()
        for f in output["facts"]:
            try:
                facts._check(f["fact"], f["value"])
            except Invalid as e:
                probs.append(f"{f['fact']}: {e}")
            if len(squash(f["quote"])) < 8 or squash(f["quote"]) not in text:
                probs.append(f"{f['fact']}: its quote isn't in the document word for word")
            if f["fact"] in seen:
                probs.append(f"{f['fact']} given twice")
            seen.add(f["fact"])
        low = not output["facts"] or output["confidence"] < cfg["confidence_threshold"]
        return {"document": (probs, bool(probs) or low)}

    def accept(self, conn, ident, decision, task, choice):
        raise ValueError("decided in the onboarding: each fact is confirmed there (product/onboardagent.py)")


AGENTS = {a.name: a for a in (Classifier(), Reviewer(), ClientQuestions(), LayoutMapper(), OnboardingReader())}


def get(name):
    if name not in AGENTS:
        cfg = config.agent(name)                          # raises for an unknown name
        raise LookupError(f"agent {name} is defined but not wired ({cfg.get('purpose')})")
    return AGENTS[name]
