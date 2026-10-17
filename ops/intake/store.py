"""Loading a client file: keep the original, convert every row to a standard record, and check each one on the way in.

On the way in:
  * the same bytes twice (a re-sent or renamed attachment) is one document, loaded once;
  * rows for another company (tenant/realm not this client's) are quarantined and never used;
  * a value that can't be read with certainty makes the row invalid (kept, with the reason) instead of being guessed;
  * the same record again (same identity and version) is a duplicate; a higher version supersedes the older one;
    the same version with different content is a conflict for the owner.
Records are data, never instructions: text that reads like instructions is flagged and otherwise ignored.
"""
import json
import re

from ..core import audit, clear_exception, iso, raise_exception
from ..documents import INSTRUCTION_LIKE, ingest
from . import layouts as L
from . import opening, qbo_reports
from .read import json_record, normalize_row, read_tables, recognize
from .values import parse_date, parse_money

CONTROL_TYPES = set(L.JSON_TYPES)
STATUS_FIELDS = {"approved", "status", "completed"}
# where a value came from, not what it is: never part of a record's identity or of whether two copies are the same
PROVENANCE = {"_file", "_sheet", "_attachment", "_extracted_by", "_ocr_fields", "text"}


def profile(scope):
    row = scope.conn.execute("SELECT profile_json FROM clients WHERE id=?", (scope.cid,)).fetchone()
    return json.loads(row["profile_json"] or "{}")


def identity(scope):
    ident = profile(scope).get("source_identity") or {}
    return {k: set(v if isinstance(v, list) else [v]) for k, v in ident.items() if v}


def known_layouts(scope, people_only=False):
    """The client's approved mappings {fingerprint: (rtype, colmap)}: a person's, and (unless people_only) the ones the
    layout reader applied by itself ("agent")."""
    where = "status='approved' AND source NOT IN ('registry','agent')" if people_only else "status='approved' AND source!='registry'"
    return {r["fingerprint"]: (r["rtype"], json.loads(r["colmap_json"])) for r in scope.all("intake_layouts", where)}


# ---------------------------------------------------------------- identity of a record

def _rid(rtype, rec, occ):
    if rtype in CONTROL_TYPES:
        key = {"statement_control": ("account", "coverage_end"), "card_cycle_control": ("end",), "coverage": ("month",),
               "ap_control": ("period",), "field_summary": ("period",), "native_recon": ("period", "accounts")}.get(rtype, ())
        return "|".join(str(rec.get(k, "")) for k in key) or rtype
    if rtype == "receipt":
        return rec.get("reference") or f"{rec.get('vendor')}|{rec.get('date')}|{rec.get('total')}"
    if rtype in ("image", "support", "correspondence"):
        return rec["sha256"]
    if rtype == "facts":
        return f"{rec['sha256']}|{rec.get('table', 0)}"
    ids = L.TYPES.get(rtype, ((), (), ()))[2]
    vals = [rec.get(f) for f in ids]
    if rtype == "gl_line":
        return f"{rec.get('event_id')}|{rec.get('account')}|{rec.get('dimension') or ''}|{rec.get('amount')}|{occ}"
    if rtype == "bank_line" and not rec.get("line_id"):
        desc = re.sub(r"\s+", " ", str(rec.get("description") or "")).strip().upper()
        return f"{rec.get('account')}|{rec.get('date')}|{rec.get('amount')}|{desc}|{occ}"
    if any(v is None for v in vals):
        return None
    return "|".join(str(v) for v in vals)


def _period(rtype, rec):
    if rtype in CONTROL_TYPES:
        for k in ("period", "month"):
            if rec.get(k):
                return str(rec[k])[:7]
        for k in ("coverage_end", "end"):
            if rec.get(k):
                return str(rec[k])[:7]
        return None
    d = rec.get("date") or rec.get("service_date") or rec.get("signed_date")
    return d[:7] if isinstance(d, str) and re.match(r"\d{4}-\d{2}", d) else None


FACTS_MAX_ROWS = 25          # a small table no layout fits is reference facts (an agreement, a notice); larger is data

# what a person (or the client's approved layouts) can say a file is, other than records to book (docs/92 §4, 1.1 and 1.3):
#   list       vendors, customers, employees, projects: kept for their names and terms
#   schedule   an agreement or schedule (a loan, insurance, cost certificates): kept for the rules that read such terms
#   evidence   supporting evidence (approvals, receipts): kept beside the lines it supports, never booked itself
#   brief      the client's brief or policies: kept as correspondence
#   not_used   kept as the file, nothing read from it
NON_RECORD_ROLES = ("list", "schedule", "evidence", "brief", "not_used")


def resolve_account(scope, ref):
    """A statement's account reference ('DEMO-1000', '****1000', '1000') -> the chart account it names, when exactly one
    chart account matches; otherwise the reference as given (and the close asks)."""
    if ref is None:
        return None
    chart = {str(r["account"]) for r in active(scope, "chart")}
    ref = str(ref).strip()
    if ref in chart:
        return ref
    m = re.search(r"(\d{3,8})$", ref)
    hits = [a for a in chart if m and (m.group(1) == a or m.group(1).endswith(a) and len(a) >= 4)]
    return hits[0] if len(hits) == 1 else ref


# ---------------------------------------------------------------- PDFs and text

def _pdf_record(text):
    """(rtype, record) for a PDF with text: a receipt, a statement summary, or a support document."""
    t = text or ""
    low = t.lower()
    money = r"(-?\(?\$?[\d,]+\.\d{2}\)?)"
    if re.search(r"receipt|supplier original|invoice\s+\S+", low) and re.search(r"total\s*" + money, t, re.I):
        rec = {"vendor": None, "reference": None, "date": None, "total": None, "lines": [], "payment": None, "deliver_to": None}
        for line in t.splitlines():
            s = line.strip()
            m = re.match(r"(?i)(supplier|vendor|merchant)\s+(.+)$", s)
            if m and not rec["vendor"]:
                rec["vendor"] = m.group(2).strip()
                continue
            m = re.match(r"(?i)(reference|invoice)\s+(\S+)$", s)
            if m:
                rec["reference"] = rec["reference"] or m.group(2)
                continue
            m = re.match(r"(?i)date\s+(\S+)$", s)
            if m and not rec["date"]:
                rec["date"] = parse_date(m.group(1))[0]
                continue
            m = re.match(r"(?i)deliver to\s+(\S+)$", s)
            if m:
                rec["deliver_to"] = m.group(1)
                continue
            m = re.match(r"(?i)payment:?\s+(.+)$", s)
            if m:
                rec["payment"] = m.group(1).strip()
                continue
            m = re.match(r"(?i)(?:usd\s+)?total\s+" + money + r"$", s)
            if m:
                rec["total"] = parse_money(m.group(1))[0]
                continue
            m = re.match(r"(.+?)\s+" + money + r"$", s)
            if m and not re.match(r"(?i)(opening|closing)", s):
                rec["lines"].append({"label": m.group(1).strip(), "amount": parse_money(m.group(2))[0]})
        return "receipt", rec
    m_open = re.search(r"(?i)(opening|beginning)(?: balance| liability)?(?: usd)?\s+" + money, t)
    m_close = re.search(r"(?i)(closing|ending)(?: balance| liability)?(?: usd)?\s+" + money, t)
    if m_open and m_close:
        rec = {"opening_cents": parse_money(m_open.group(2))[0], "closing_cents": parse_money(m_close.group(2))[0], "source": "pdf"}
        cov = re.search(r"(?i)(?:coverage|cycle|statement period)\s+(\S+)\s+(?:through|to|-)\s+(\S+)", t)
        if cov:
            rec["coverage_start"], rec["coverage_end"] = parse_date(cov.group(1))[0], parse_date(cov.group(2))[0]
        acct = re.search(r"(?i)account\s+(\d+)", t)
        cnt = re.search(r"(?i)transaction count\s+(\d+)", t)
        if cnt:
            rec["row_count"] = int(cnt.group(1))
        if "liability" in m_open.group(0).lower():            # card cycle: liability-positive balances
            return "card_cycle_control", {"start": rec.get("coverage_start"), "end": rec.get("coverage_end"),
                                          "opening_liability_cents": rec["opening_cents"],
                                          "closing_liability_cents": rec["closing_cents"], "source": "pdf"}
        if acct:
            rec["account"] = acct.group(1)
        return "statement_control", rec
    return "support", {}


# ---------------------------------------------------------------- loading

# reference records a client's handover often states twice (the chart, the asset register: a CSV and the opening package's
# sheet): the same when everything both state agrees; one may carry detail the other doesn't (QA audit)
REFERENCE_TYPES = {"chart", "asset"}
TYPE_CLASS = {"bank": "asset", "accounts receivable": "asset", "other current asset": "asset", "current asset": "asset",
              "fixed asset": "asset", "other asset": "asset", "accounts payable": "liability", "credit card": "liability",
              "other current liability": "liability", "long term liability": "liability", "income": "revenue",
              "cost of goods sold": "expense", "cost of sales": "expense", "other expense": "expense", "other income": "revenue"}


def _same(rtype, a, b):
    if rtype in CONTROL_TYPES:                         # a PDF summary and its JSON agree on the keys they share
        shared = (set(a) & set(b)) - {"source"} - PROVENANCE
        return all(a[k] == b[k] for k in shared)
    if rtype in REFERENCE_TYPES:
        shared = {k for k in (set(a) & set(b)) - {"source"} - PROVENANCE if a[k] not in (None, "") and b[k] not in (None, "")}
        def norm(k, v):
            v = str(v).strip().lower()
            return TYPE_CLASS.get(v, v) if k == "account_type" else v
        return all(norm(k, a[k]) == norm(k, b[k]) for k in shared)
    return {k: v for k, v in a.items() if k not in PROVENANCE} == {k: v for k, v in b.items() if k not in PROVENANCE}


def _ocr_gate(scope, doc_id, filename, rtype, rec, table):
    """A figure read by OCR is used only when the line it came from was read with confidence; below that it's left
    unknown and the document is kept as evidence only. OCR confidence never authorizes anything by itself: every
    OCR-read record says so, and its figures still have to agree with the statement lines and the books."""
    from .. import ocr
    res = table.meta.get("ocr_result") or {}
    keys = {"receipt": ("total",), "statement_control": ("opening_cents", "closing_cents"),
            "card_cycle_control": ("opening_liability_cents", "closing_liability_cents")}.get(rtype, ())
    fields, low = [], []
    for k in keys:
        v = rec.get(k)
        if v is None:
            continue
        hit = ocr.confidence_of(res, f"{abs(v) / 100:.2f}")
        conf = hit["confidence"] if hit else None
        fields.append({"field": k, "value": v, "confidence": conf, "page": hit["page"] if hit else None, "box": hit["box"] if hit else None})
        if conf is None or conf < ocr.LOW:
            low.append(k)
    rec["_extracted_by"] = f"ocr:{(table.meta.get('ocr') or {}).get('version')}"
    rec["_ocr_fields"] = fields
    if low:
        raise_exception(scope, "ocr_uncertain", "review", f"{filename}: read by OCR, but {', '.join(low)} couldn't be read with certainty, "
                        "so it's kept as evidence only. Ask for a clearer copy or the original export.", ref=f"doc:{doc_id}")
        return "support", {"text": rec.get("text"), "ocr_unreadable": low, "_ocr_fields": fields, "_extracted_by": rec["_extracted_by"]}
    if fields:
        lowest = min(f["confidence"] for f in fields)
        raise_exception(scope, "ocr_read", "info" if lowest >= 0.9 else "review", f"{filename}: read by OCR (the lowest confidence on a "
                        f"figure was {lowest:.0%}). Check the figures against the image before relying on them.", ref=f"doc:{doc_id}")
    return rtype, rec


def _photo_fields(table):
    """What a photo says, read by OCR, as evidence: vendor, reference, date, total and lines, each with the confidence
    of the line it came from. Not a record the books use: the bills and statements are."""
    from .. import ocr
    rtype, rec = _pdf_record(table.text)
    if rtype != "receipt":
        return None
    res = table.meta.get("ocr_result") or {}
    out = {}
    for k in ("vendor", "reference", "date", "total"):
        v = rec.get(k)
        if v is None:
            continue
        needle = f"{abs(v) / 100:.2f}" if k == "total" else (v[5:7] + "/" + v[8:10] if k == "date" and len(str(v)) == 10 else v)
        hit = ocr.confidence_of(res, needle)
        out[k] = {"value": v, "confidence": hit["confidence"] if hit else None, "page": hit["page"] if hit else None}
    out["lines"] = rec.get("lines") or []
    return out


def _insert(scope, doc_id, row_no, rtype, rid, version, rec, raw, stage, status="active", note=None):
    return scope.insert("records", document_id=doc_id, row_no=row_no, rtype=rtype, rid=rid or f"row:{doc_id}:{row_no}",
                        version=version, date=rec.get("date"), period=_period(rtype, rec), data_json=json.dumps(rec, default=str),
                        raw_json=json.dumps(raw, default=str) if raw is not None else None, status=status, note=note, stage=stage,
                        created_at=iso())


def _place(scope, doc_id, row_no, rtype, rec, raw, stage, occ, counts):
    """Insert one record with the duplicate/version/conflict rules. Returns its status."""
    rid = _rid(rtype, rec, occ)
    version = rec.get("version") or 1
    if rid is None:
        _insert(scope, doc_id, row_no, rtype, None, version, rec, raw, stage, "invalid", "missing the identifying field(s)")
        return "invalid"
    prior = scope.first("records", "rtype=? AND rid=? AND status IN ('active','conflict')", (rtype, rid))
    if prior is None:
        _insert(scope, doc_id, row_no, rtype, rid, version, rec, raw, stage)
        return "active"
    old = json.loads(prior["data_json"])
    if _same(rtype, old, rec) and prior["version"] == version:
        clear_exception(scope, "record_conflict", f"{rtype}:{rid}", resolution="read again: the two records agree")
        if rtype in REFERENCE_TYPES:                      # the detail only the newer file states is kept with the record
            extra = {k: v for k, v in rec.items() if k not in PROVENANCE and v not in (None, "") and old.get(k) in (None, "")}
            if extra and prior["status"] == "active":
                scope.update("records", prior["id"], data_json=json.dumps({**old, **extra}))
        if rtype in CONTROL_TYPES and len(rec) > len(old):  # keep the richer copy active
            new = _insert(scope, doc_id, row_no, rtype, rid, version, rec, raw, stage)
            scope.update("records", prior["id"], status="duplicate", related=new, note=f"same as record {new}")
            return "active"
        _insert(scope, doc_id, row_no, rtype, rid, version, rec, raw, stage, "duplicate", f"same as record {prior['id']}")
        return "duplicate"
    # a correction the client sends back: fills blanks the first copy left, and may approve or complete it
    filled = [k for k, v in old.items() if v is None and rec.get(k) is not None]
    fills = prior["version"] == version and bool(filled) and all(
        v is None or rec.get(k) == v or k in STATUS_FIELDS for k, v in old.items() if k not in PROVENANCE)
    if rtype in CONTROL_TYPES or rtype == "receipt" or version > prior["version"] or fills:
        new = _insert(scope, doc_id, row_no, rtype, rid, version, rec, raw, stage)
        scope.update("records", prior["id"], status="superseded", related=new,
                     note=f"replaced by record {new}" + (f" (version {version})" if version != prior["version"] else
                                                         " (completes blank fields)" if fills else " (later copy)"))
        return "superseded_prior"
    if version < prior["version"]:
        _insert(scope, doc_id, row_no, rtype, rid, version, rec, raw, stage, "superseded",
                f"older version ({version}) than record {prior['id']} ({prior['version']})")
        return "stale"
    _insert(scope, doc_id, row_no, rtype, rid, version, rec, raw, stage, "conflict",
            f"same identity and version as record {prior['id']} but different content")
    raise_exception(scope, "record_conflict", "review", f"Two different {rtype} records claim to be {rid} version {version} "
                    f"(records {prior['id']} and the new one). Which is right?", ref=f"{rtype}:{rid}")
    return "conflict"


def _agent_layout(scope, table, lay, filename, doc_id, order, quiet=False):
    """The layout agent's proposal for a layout the registry doesn't know. Applied when it's certain (and shown to the
    owner); otherwise saved as a proposal and the file waits."""
    from .mapper import propose
    from .read import Layout
    p = propose(table, date_order=order)
    detail = (f"{filename}: read as {p.rtype} ({', '.join(f'{f}<-{h}' for f, h in p.colmap.items())}); confidence "
              f"{p.confidence:.0%}" + (f"; {'; '.join(p.notes)}" if p.notes else ""))
    if p.high:
        scope.insert_ignore("intake_layouts", fingerprint=lay.fingerprint, rtype=p.rtype, colmap_json=json.dumps(p.colmap),
                            headers_json=json.dumps(table.headers), status="approved", source="agent", created_at=iso())
        raise_exception(scope, "layout_mapped_by_agent", "info", detail + ". Check the mapping; it's used for this layout "
                        "from now on.", ref=f"doc:{doc_id}")
        return Layout(p.rtype, p.colmap, [h for h in table.headers if h not in p.colmap.values()], [], "agent", lay.fingerprint)
    if p.rtype and not quiet:
        scope.insert_ignore("intake_layouts", fingerprint=lay.fingerprint, rtype=p.rtype, colmap_json=json.dumps(p.colmap),
                            headers_json=json.dumps(table.headers), status="proposed", source="agent", created_at=iso())
        lay.missing = [f"(proposed: {detail}; needs your check: {'; '.join(p.value_problems) or 'low confidence'})"]
    return lay


def _qbo_rows(scope, table, rows, filename, doc_id, stage):
    """A QuickBooks report's ledger lines (ops/intake/qbo_reports.py): accounts named as QuickBooks names them are
    resolved to the chart; a transaction with an account the chart doesn't have is set aside whole, with the reason;
    a trial balance is opening balances only when it comes with the handover files; and a newer ledger export replaces
    the earlier export's lines for the dates it covers."""
    kind = table.meta["qbo_report"]
    if kind == "trial_balance" and stage != "handover":
        raise_exception(scope, "qbo_report", "info", f"{filename}: a QuickBooks trial balance for a month is kept as evidence. It "
                        "becomes opening balances only when uploaded with the handover files; checking the books against it "
                        "isn't built yet.", ref=f"doc:{doc_id}")
        return []
    chart = active(scope, "chart")
    unknown, bad_events = set(), set()
    for rec, problems in rows:
        rec["_qbo"] = kind
        acct = qbo_reports.resolve(chart, rec.get("account")) if rec.get("account") is not None else None
        if acct is None:
            unknown.add(str(rec.get("account")))
            bad_events.add(rec.get("event_id"))
        else:
            rec["account_ref"], rec["account"] = rec["account"], acct
    for rec, problems in rows:
        if rec.get("event_id") in bad_events:
            problems.append(f"account: a line names an account the chart doesn't have ({', '.join(sorted(unknown))[:200]}); "
                            "the whole transaction waits until the account is in the chart")
    if unknown:
        raise_exception(scope, "qbo_unknown_account", "review", f"{filename}: {len(bad_events)} transaction(s) name accounts that "
                        f"aren't in the client's chart: {', '.join(sorted(unknown))[:300]}. Add them to the chart (or confirm "
                        "the chart) and upload the export again.", ref=f"doc:{doc_id}")
    period = table.meta.get("qbo_period")
    if kind in qbo_reports.LEDGER and period:
        replaced = 0
        for r in scope.all("records", "rtype='gl_line' AND status='active' AND document_id<>? AND date BETWEEN ? AND ?",
                           (doc_id, period[0], period[1])):
            if json.loads(r["data_json"]).get("_qbo") in qbo_reports.LEDGER:
                scope.update("records", r["id"], status="superseded",
                             note=f"replaced by the newer QuickBooks export {filename} (document {doc_id})")
                replaced += 1
        if replaced:
            raise_exception(scope, "qbo_export_replaced", "info", f"{filename} replaces {replaced} line(s) of an earlier QuickBooks "
                            f"export for {period[0]} to {period[1]}.", ref=f"doc:{doc_id}")
    return rows


def _single_account_extract(rows):
    """True when a ledger-layout file holds one account's side of each entry (a card or bank activity listing), not
    whole balanced entries."""
    accts = {r.get("account") for r, _ in rows}
    if len(accts) != 1:
        return False
    sums = {}
    for r, _ in rows:
        sums[r.get("event_id")] = sums.get(r.get("event_id"), 0) + (r.get("amount") or 0)
    return any(v for v in sums.values())


def load(scope, filename, data, actor="agent:intake", stage="initial"):
    """Store one file and convert it. Returns a summary. Loading the same bytes again changes nothing."""
    doc_id, created = ingest(scope, data, filename, actor)
    if not created:
        return {"document": doc_id, "filename": filename, "already_loaded": True}
    return convert(scope, doc_id, actor, stage)


def stage_of(scope, doc):
    meta = json.loads(doc["meta_json"] or "{}")
    return meta.get("stage", "uploaded")


def _keep_as(scope, doc_id, base, table, filename, stage, role):
    """A table a person (or an approved layout) said isn't records to book: kept for what it is, with its role."""
    if role == "not_used":
        return
    sha = scope.one("documents", doc_id)["sha256"]
    n = sum(1 for _ in scope.all("records", "document_id=? AND rtype='facts'", (doc_id,)))
    rec = {"sha256": sha, "filename": filename, "table": n, "title": table.meta.get("title") or table.meta.get("table") or table.meta.get("sheet"),
           "text": table.text[:5000], "units": table.units, "rows": table.rows[:5000], "headers": table.headers, "role": role}
    _insert(scope, doc_id, base + 900_000 + n, "facts", f"{sha}|{n}", 1, rec, None, stage, "evidence")


def convert(scope, doc_id, actor="agent:intake", stage=None):
    """Convert one stored document (status 'received' or 'needs_mapping') into standard records."""
    doc = scope.one("documents", doc_id)
    filename = doc["filename"]
    doc_role = json.loads(doc["meta_json"] or "{}").get("role")    # a person's word on this one file (docs/92 §4, 0.1 and 1.1)
    from .read import EXTRACTOR                     # which reader read it: a later reader reads it again (product/engine.py)
    scope.update("documents", doc_id, meta_json=json.dumps({**json.loads(doc["meta_json"] or "{}"), "read_by": EXTRACTOR}))
    with open(doc["path"], "rb") as f:
        data = f.read()
    stage = stage or stage_of(scope, doc)
    ident = identity(scope)
    order = profile(scope).get("date_order", "mdy")
    counts = {"active": 0, "duplicate": 0, "quarantined": 0, "invalid": 0, "superseded_prior": 0, "stale": 0, "conflict": 0}
    summary = {"document": doc_id, "filename": filename, "rtype": None, "rows": 0, "counts": counts, "problems": []}
    for ti, table in enumerate(read_tables(filename, data)):
        base = ti * 1_000_000                              # row numbers stay unique across a file's tables
        att = table.meta.get("attachment")
        label = f"{filename} (attachment {att})" if att else filename
        if table.source == "unreadable":                   # an attachment that can't be read: said, and the rest goes on
            raise_exception(scope, "attachment_unreadable", "review", f"{label} couldn't be read: {table.text}.", ref=f"doc:{doc_id}:{att}")
            summary["problems"].append(f"{att}: {table.text}")
            continue
        if table.source in ("pdf", "text", "image", "ocr"):
            sha = table.meta.get("attachment_sha256") or scope.one("documents", doc_id)["sha256"]
            if table.source == "pdf":
                rtype, rec = _pdf_record(table.text)
                rec["text"] = table.text[:20000]
                if table.meta.get("extracted_by") == "pdfkit-text":
                    rec["_extracted_by"] = "pdfkit-text"
            elif table.source == "ocr" and table.meta.get("kind") == "pdf":
                rtype, rec = _pdf_record(table.text)
                rec["text"] = table.text[:20000]
                rtype, rec = _ocr_gate(scope, doc_id, label, rtype, rec, table)
            elif table.source == "text":
                rtype, rec = "correspondence", {"text": table.text[:20000]}
                if table.meta.get("sent"):                 # an email: its date, sender and subject are evidence too
                    rec.update(date=table.meta["sent"], subject=table.meta.get("subject"), sender=table.meta.get("from"))
                    names = [a.get("filename") for a in table.meta.get("attachments") or [] if a.get("filename")]
                    if names:
                        rec["attachments"] = names
            else:                                          # a photo: kept as evidence; what OCR read rides along with it
                rtype, rec = "image", {k: v for k, v in table.meta.items() if k in ("width", "height")}
                if table.source == "ocr":
                    rec.update(text=table.text[:20000], ocr=table.meta.get("ocr"), extracted=_photo_fields(table),
                               _extracted_by=f"ocr:{(table.meta.get('ocr') or {}).get('version')}")
            rec.update(sha256=sha, filename=att or filename)
            if att:
                rec["_attachment"] = att
            if table.text and INSTRUCTION_LIKE.search(table.text):
                raise_exception(scope, "document_instructions", "review", f"{label} contains text that reads like "
                                "instructions. It was treated as data only; check the file is genuine.", ref=f"doc:{doc_id}")
            status = "evidence" if rtype in ("support", "correspondence", "image") else "active"
            if status == "evidence":
                _insert(scope, doc_id, base, rtype, sha, 1, rec, None, stage, "evidence")
                counts["active"] += 1
            else:
                counts[_place(scope, doc_id, base, rtype, rec, None, stage, 0, counts)] += 1
            summary["rtype"] = summary["rtype"] if att and summary["rtype"] else rtype
            continue
        if table.source == "ofx" and table.meta.get("closing") is not None:
            rec = {"account": resolve_account(scope, table.meta["account"]), "account_ref": table.meta["account"],
                   "coverage_start": table.meta.get("coverage_start"), "coverage_end": table.meta.get("coverage_end"),
                   "closing_cents": parse_money(table.meta["closing"])[0], "row_count": len(table.rows), "source": "ofx"}
            counts[_place(scope, doc_id, base, "statement_control", rec, table.meta, stage, 0, counts)] += 1
        if table.meta.get("qbo_report"):
            for prob in table.meta.get("qbo_problems") or []:
                raise_exception(scope, "qbo_report", "review", f"{filename} (QuickBooks {table.meta['qbo_report'].replace('_', ' ')}): "
                                f"{prob}", ref=f"doc:{doc_id}")
            if not table.rows:
                summary["rtype"] = "qbo_report"
                continue
        lay = recognize(table, known_layouts(scope, people_only=True))   # a person's approved mapping wins over everything
        if lay.rtype is None:                             # the reader's own earlier guess only where the registry can't read it:
            lay = recognize(table, known_layouts(scope))  # an improved registry corrects it (QA audit)
        role = doc_role if doc_role in NON_RECORD_ROLES else lay.rtype[5:] if (lay.rtype or "").startswith("role:") else None
        if role in NON_RECORD_ROLES:
            _keep_as(scope, doc_id, base, table, filename, stage, role)
            clear_exception(scope, "intake_unrecognized", f"doc:{doc_id}", resolution=f"read as {role} (a person's decision)")
            counts["active"] += role != "not_used"
            summary["rtype"] = summary["rtype"] or f"role:{role}"
            continue
        if lay.rtype is not None and lay.how in ("registry", "learned", "client"):   # read now: what asked about it no longer applies
            clear_exception(scope, "intake_unrecognized", f"doc:{doc_id}", resolution=f"read as {lay.rtype}")
            clear_exception(scope, "layout_mapped_by_agent", f"doc:{doc_id}", resolution=f"read by the registry as {lay.rtype}")
        if lay.rtype is None and table.headers and not table.empty_marker:
            small = len(table.rows) <= FACTS_MAX_ROWS and not L.monetary_table(table.headers)
            lay = _agent_layout(scope, table, lay, filename, doc_id, order, quiet=small)
            if small and lay.how != "agent":
                lay.rtype = None                           # not placed with confidence: reference facts, below
        if lay.rtype is None and not table.rows:
            continue                                       # an empty export: nothing to record
        if lay.rtype is None and table.headers and len(table.rows) <= FACTS_MAX_ROWS and not L.monetary_table(table.headers):
            # an agreement, notice or reference table: kept as facts for the rules that read such terms; the head
            # senior lists any facts no rule used
            sha = scope.one("documents", doc_id)["sha256"]
            n = sum(1 for _ in scope.all("records", "document_id=? AND rtype='facts'", (doc_id,)))
            rec = {"sha256": sha, "filename": filename, "table": n, "title": table.meta.get("title") or table.meta.get("table"),
                   "text": table.text[:5000], "units": table.units, "rows": table.rows, "headers": table.headers}
            _insert(scope, doc_id, base + 900_000 + n, "facts", f"{sha}|{n}", 1, rec, None, stage, "evidence")
            counts["active"] += 1
            summary["rtype"] = summary["rtype"] or "facts"
            continue
        summary["rtype"] = lay.rtype
        if lay.rtype is None:
            scope.insert_ignore("intake_layouts", fingerprint=lay.fingerprint, rtype=None, colmap_json=json.dumps(lay.colmap),
                                headers_json=json.dumps(table.headers), status="proposed", source="agent", created_at=iso())
            raise_exception(scope, "intake_unrecognized", "review", f"{filename}: the columns ({', '.join(table.headers[:12])}) "
                            f"don't match a known layout ({'; '.join(lay.missing) or 'no record type fits'}). Map the "
                            "columns once and this layout is recognized from then on.", ref=f"doc:{doc_id}")
            scope.update("documents", doc_id, status="needs_mapping", kind="intake:unrecognized")
            if len(read_tables(filename, data)) == 1:
                return summary
            summary["unmapped_tables"] = summary.get("unmapped_tables", 0) + 1
            continue
        scope.insert_ignore("intake_layouts", fingerprint=lay.fingerprint, rtype=lay.rtype, colmap_json=json.dumps(lay.colmap),
                            headers_json=json.dumps(table.headers), status="approved", source=lay.how, created_at=iso())
        wrong, bad = {}, []
        own_keys = table.source in ("json", "xml") and lay.rtype in CONTROL_TYPES
        if own_keys:
            rows = [(json_record(lay.rtype, table.rows[0]), [])]
            if rows[0][0].get("account") is not None:
                rows[0][0]["account"] = resolve_account(scope, rows[0][0]["account"])
        else:
            rows = [normalize_row(lay.rtype, lay.colmap, r, order, table.units) for r in table.rows]
            if table.meta.get("qbo_report"):
                rows = _qbo_rows(scope, table, rows, filename, doc_id, stage)
            if lay.rtype in ("bank_line", "statement_control"):
                for r, _ in rows:
                    if r.get("account") is not None:
                        acct = resolve_account(scope, r["account"])
                        if acct != r["account"]:
                            r["account_ref"], r["account"] = r["account"], acct
            if lay.rtype == "trial_balance" and doc_role == "opening_balances":
                # a trial balance a person said is the opening balances, as of the date they gave: the engine's opening lines
                as_of = (json.loads(doc["meta_json"] or "{}").get("role_detail") or {}).get("as_of")
                rows = [({"event_id": f"OPENING-{r.get('date') or as_of}", "date": r.get("date") or as_of, "account": r.get("account"),
                          "amount": r.get("amount"), "memo": r.get("account_name") or "opening trial balance", "source_id": "OPENING",
                          **({"_undated": True} if not r.get("date") else {})}, p)
                        for r, p in rows]
                lay.rtype = summary["rtype"] = "gl_line"
            taken_as_opening = False
            if lay.rtype == "gl_line" and not table.meta.get("qbo_report"):
                # an opening trial balance, recognized or designated, is the engine's opening balances (ops/intake/opening.py)
                exam = opening.examine([r for r, _ in rows], filename, table.meta.get("title") or "",
                                       (json.loads(doc["meta_json"] or "{}").get("role_detail") or {}).get("as_of") if doc_role == "opening_balances" else None)
                for r, _ in rows:
                    r.pop("_undated", None)                # only for the rule above: never stored
                if doc_role == "opening_balances" or exam["verdict"] == "opening":
                    if exam["as_of"] and exam["balanced"]:
                        opening.mark([r for r, _ in rows])
                        taken_as_opening = True
                        summary["opening"] = {k: exam[k] for k in ("as_of", "debits_cents", "credits_cents", "accounts", "marker")}
                    else:
                        raise_exception(scope, "opening_tb_unusable", "blocker", f"{filename} was taken as the opening trial balance, but "
                                        f"{exam['why']}. Ask the client for the balanced trial balance as of the opening date.",
                                        ref=f"doc:{doc_id}")
            # one account's ledger extract is its statement, even when it starts with its own opening line (a card's
            # cycle lines do); only a file taken as the opening trial balance itself stays ledger lines
            if lay.rtype == "gl_line" and not table.meta.get("qbo_report") and _single_account_extract(rows) and not taken_as_opening:
                lay.rtype = summary["rtype"] = "bank_line"      # one account's activity in ledger layout = its statement
                rows = [({"line_id": f"{r['event_id']}-{r['account']}", "date": r.get("date"), "account": r.get("account"),
                          "description": r.get("source_id") or r.get("memo"), "amount": r.get("amount"),
                          "tenant_id": r.get("tenant_id"), "realm_id": r.get("realm_id")}, p) for r, p in rows]
        must = L.MUST.get(lay.rtype, ())
        if own_keys:                                       # a control document keeps its own keys
            must = tuple(L.CONTROL_KEYS.get(lay.rtype, {}).get(f, f) for f in must)
        occ = {}
        for i, ((rec, problems), raw) in enumerate(zip(rows, table.rows), base + 1):
            summary["rows"] += 1
            rec["_file"] = filename
            if table.meta.get("sheet"):
                rec["_sheet"] = table.meta["sheet"]
            if table.meta.get("attachment"):
                rec["_attachment"] = table.meta["attachment"]
            key = _rid(lay.rtype, rec, 0)
            occ[key] = occ.get(key, 0) + 1
            other = [f"{k}={rec.get(k)}" for k in ("tenant_id", "realm_id") if k in ident and rec.get(k) and rec[k] not in ident[k]]
            if other:
                qrid = _rid(lay.rtype, rec, occ[key])
                seen = scope.first("records", "rtype=? AND rid=? AND status='quarantined'", (lay.rtype, qrid))
                if seen and _same(lay.rtype, json.loads(seen["data_json"]), rec):
                    _insert(scope, doc_id, i, lay.rtype, qrid, rec.get("version") or 1, rec, raw, stage, "duplicate",
                            f"same other-company row as record {seen['id']}")
                    counts["duplicate"] += 1
                    continue
                _insert(scope, doc_id, i, lay.rtype, qrid, rec.get("version") or 1, rec, raw, stage,
                        "quarantined", "belongs to another company: " + ", ".join(other))
                counts["quarantined"] += 1
                wrong[", ".join(other)] = wrong.get(", ".join(other), 0) + 1
                continue
            gaps = [f for f in must if rec.get(f) is None]
            must_headers = {lay.colmap.get(f) for f in must}
            hard = [p for p in problems if p.split(":")[0] in must_headers]
            soft = [p for p in problems if p not in hard]
            if soft and not hard and not gaps:            # an optional field we can't read stays unknown, the row is kept
                rec["_unreadable"] = soft
                summary["problems"].extend(f"row {i}: {p} (kept; field left unknown)" for p in soft)
                problems = []
            if problems or gaps:
                why = "; ".join(problems + [f"{g} is blank" for g in gaps])
                _insert(scope, doc_id, i, lay.rtype, _rid(lay.rtype, rec, occ[key]), rec.get("version") or 1, rec, raw, stage,
                        "invalid", why)
                counts["invalid"] += 1
                bad.append(f"row {i}: {why}")
                continue
            counts[_place(scope, doc_id, i, lay.rtype, rec, raw, stage, occ[key], counts)] += 1
        if wrong:
            raise_exception(scope, "wrong_tenant", "review", f"{filename}: {sum(wrong.values())} row(s) belong to another "
                            f"company ({'; '.join(wrong)}). Quarantined and not used.", ref=f"doc:{doc_id}")
        soft = [p for p in summary["problems"] if p.endswith("(kept; field left unknown)")]
        if soft:
            raise_exception(scope, "unreadable_value", "info", f"{filename}: {len(soft)} value(s) couldn't be read and were left "
                            f"unknown (rows kept): {'; '.join(soft[:5])}", ref=f"doc:{doc_id}")
        else:                                             # read again cleanly (an improved reader): the earlier note no longer applies
            clear_exception(scope, "unreadable_value", f"doc:{doc_id}", resolution="read again: every value read")
        if not bad:
            clear_exception(scope, "unreadable_rows", f"doc:{doc_id}", resolution="read again: every row read")
        if bad:
            summary["problems"] = summary["problems"] + bad
            raise_exception(scope, "unreadable_rows", "review", f"{filename}: {len(bad)} row(s) couldn't be read with "
                            f"certainty and weren't used: {'; '.join(bad[:5])}", ref=f"doc:{doc_id}")
    periods = [r["period"] for r in scope.all("records", "document_id=? AND period IS NOT NULL", (doc_id,))]
    if summary.get("unmapped_tables"):
        return summary
    scope.update("documents", doc_id, status="intake", kind=f"intake:{summary['rtype']}",
                 period_start=min(periods) if periods else None, period_end=max(periods) if periods else None)
    audit(scope.conn, scope.cid, actor, "intake_loaded", f"doc:{doc_id}", {k: v for k, v in summary.items() if k != "problems"})
    return summary


def approve_role(scope, fingerprint, role, actor):
    """A person said every file with these columns is a list, a schedule, supporting evidence, the client's brief, or not
    used: kept for what it is from now on, never booked (docs/92 §4, 1.1)."""
    if role not in NON_RECORD_ROLES:
        raise ValueError(f"unknown file role {role!r}")
    row = scope.first("intake_layouts", "fingerprint=?", (fingerprint,))
    if row:
        scope.update("intake_layouts", row["id"], rtype=f"role:{role}", colmap_json="{}", status="approved", source="owner", approved_by=actor)
    else:
        scope.insert("intake_layouts", fingerprint=fingerprint, rtype=f"role:{role}", colmap_json="{}", headers_json="[]",
                     status="approved", source="owner", approved_by=actor, created_at=iso())
    audit(scope.conn, scope.cid, actor, "layout_role_approved", fingerprint, {"role": role})


def approve_layout(scope, fingerprint, rtype, colmap, actor):
    """The owner's column mapping for a layout the registry couldn't place. Used for that client's files from now on."""
    if rtype not in L.TYPES:
        raise ValueError(f"unknown record type {rtype!r}")
    missing = L.mapping_gaps(rtype, colmap)
    if missing:
        raise ValueError(f"mapping leaves required fields unmapped: {', '.join(missing)}")
    row = scope.first("intake_layouts", "fingerprint=?", (fingerprint,))
    if row:
        scope.update("intake_layouts", row["id"], rtype=rtype, colmap_json=json.dumps(colmap), status="approved", source="owner",
                     approved_by=actor)
    else:
        scope.insert("intake_layouts", fingerprint=fingerprint, rtype=rtype, colmap_json=json.dumps(colmap), headers_json="[]",
                     status="approved", source="owner", approved_by=actor, created_at=iso())
    audit(scope.conn, scope.cid, actor, "layout_approved", fingerprint, {"rtype": rtype, "colmap": colmap})


def active(scope, rtype, where="1=1", params=()):
    """Active records of one type, as dicts with their record id."""
    out = []
    for r in scope.all("records", f"rtype=? AND status='active' AND ({where})", (rtype, *params)):
        d = json.loads(r["data_json"])
        d["_id"], d["_period"], d["_doc"], d["_stage"] = r["id"], r["period"], r["document_id"], r["stage"]
        out.append(d)
    return out
