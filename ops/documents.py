"""Document intake. Originals are stored unchanged, content-addressed (sha256), per client, under data/ops/files/.

Uploaded files are untrusted data. Nothing in a file can change permissions, recipients or accounting decisions; text
that looks like instructions is flagged for the owner and otherwise ignored. The same file uploaded twice is one record.
"""
import json
import os
import re

from .core import audit, iso, raise_exception, sha256_bytes

FILES_ROOT = os.environ.get("OPS_FILES", os.path.join(os.path.dirname(__file__), "..", "data", "ops", "files"))
INSTRUCTION_LIKE = re.compile(r"(ignore (all|previous|prior) instructions|you are (an|a) (ai|assistant)|approve all|"
                              r"send (the|all) (statements|files|records) to|change the (bank|account|routing))", re.I)
MAX_BYTES = 25 * 1024 * 1024


def sniff(name: str, data: bytes) -> tuple[str, str | None]:
    """(kind, text). Kind decides the extractor; text is None for binary files that need OCR."""
    if data[:4] == b"%PDF":
        return "pdf", None
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or name.lower().endswith((".heic", ".jpg", ".jpeg", ".png")):
        return "image", None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "unknown", None
    head = text[:400].upper()
    first = text.splitlines()[0].lower() if text.strip() else ""
    if "ACCOUNT STATEMENT" in head or "CARD STATEMENT" in head:
        return "statement", text
    if "LOAN STATEMENT" in head:
        return "loan_statement", text
    if head.startswith("RECEIPT") or "\nRECEIPT" in head[:40]:
        return "receipt", text
    if "PRIOR RETURN SUMMARY" in head:
        return "prior_return", text
    if "PREPARER WORKSHEET" in head:
        return "preparer_worksheet", text
    if "payout id" in first and "net" in first:
        return "processor_csv", text
    if first.startswith("date,") and ("amount" in first or ("debit" in first and "credit" in first)):
        return "bank_csv", text
    if "PAYROLL REGISTER" in head:
        return "payroll_register", text
    if "FIELD SYSTEM MONTHLY SUMMARY" in head:
        return "field_summary", text
    if head.startswith("ST-8 LOG") or "\nST-8 LOG" in head[:40]:
        return "st8_log", text
    if "DISTRIBUTOR STATEMENT" in head:
        return "distributor_statement", text
    if "PMS MONTHLY REVENUE SUMMARY" in head:
        return "pms_summary", text
    if "TAX RETURN FILED" in head:
        return "tax_return", text
    if "CASH PAID-OUT LOG" in head:
        return "paid_out_log", text
    if "BUSINESS EXPENSES PAID PERSONALLY" in head:
        return "personal_business_list", text
    return "unknown", text


def ingest(scope, data: bytes, filename: str, uploaded_by: str, system_id=None, meta=None):
    """Store one file. Returns (document_id, created). A second upload of identical bytes returns the first record."""
    if len(data) > MAX_BYTES:
        raise ValueError("file too large (25 MB limit)")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename))[:120] or "upload"
    digest = sha256_bytes(data)
    existing = scope.first("documents", "sha256=?", (digest,))
    if existing:
        audit(scope.conn, scope.cid, uploaded_by, "duplicate_upload", f"doc:{existing['id']}", {"filename": filename})
        if safe != existing["filename"] and len(data) > 64:          # a renamed copy of a file already received
            raise_exception(scope, "duplicate_attachment", "info", f"{safe} is the same file as {existing['filename']} "
                            "(identical contents): kept once as evidence, its transactions counted once.", ref=f"doc:{existing['id']}:{safe[:60]}")
        return existing["id"], False
    code = scope.conn.execute("SELECT code FROM clients WHERE id=?", (scope.cid,)).fetchone()["code"]
    folder = os.path.join(FILES_ROOT, code, digest[:2])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{digest[:16]}-{safe}")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    kind, text = sniff(safe, data)
    doc_id = scope.insert("documents", sha256=digest, filename=safe, path=path, size=len(data), kind=kind, system_id=system_id,
                          status="received", uploaded_by=uploaded_by, received_at=iso(),
                          meta_json=json.dumps(meta) if meta else None)
    if text and INSTRUCTION_LIKE.search(text):
        raise_exception(scope, "document_instructions", "review", f"{safe} contains text that reads like instructions "
                        "(e.g. to approve or send records). It was treated as data only; check the file is genuine.", ref=f"doc:{doc_id}")
    audit(scope.conn, scope.cid, uploaded_by, "document_received", f"doc:{doc_id}", {"filename": safe, "kind": kind})
    return doc_id, True


def read_text(doc) -> str | None:
    with open(doc["path"], "rb") as f:
        data = f.read()
    return sniff(doc["filename"], data)[1]
