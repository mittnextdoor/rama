"""Any client file -> tables -> recognized layout -> standard records (dicts), with the original row kept beside each.

Readers: CSV/TSV/semicolon/pipe (header row found even under report titles), Excel .xlsx/.xlsm (standard library
zip/XML: every sheet, hidden ones flagged, macros never run), JSON (one object = one control record; a list = rows;
nested objects flattened), JSON lines / NDJSON, OFX bank downloads (statement lines plus the statement balance), SQLite
database extracts (one table per database table), XML exports (repeated records, nested elements flattened), HTML
reports (each <table>, with the page's notes), fixed-width text reports (columns from the header's positions),
iCalendar service records (one row per event), email (.eml: the body, sender and date, and each attachment read as its
own file with where it came from), PDFs (their text; a text layer the standard reader can't decode is read through
PDFKit; a scan is read by OCR, ops/ocr.py), photos (read by OCR; kept as evidence), plain text and Markdown.

What a file is comes from its bytes, never its name: a renamed CSV is still read as CSV, and a .xlsx that is really a
Word file is refused. A file that can't be read says why (UnreadableFile): protected (a password), corrupt, unsupported
(an old .xls, a .docx, an archive), or over a limit (pages, expansion, rows). Nothing in a file is ever executed.

Units: a header ending in _cents or _minor is integer cents; a report that states "integer cents" / "amounts in cents",
or a fixed-width report with any *_CENTS column, is read in cents throughout. Everything else is dollars.
"""
import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

from ..pdftext import pdf_text
from . import layouts as L
from . import qbo_reports
from .values import blank, parse_bool, parse_date, parse_datetime, parse_int, parse_money, parse_number


MAX_SHEET_ROWS = 200_000                # a sheet longer than this is refused, not truncated
MAX_ZIP_MEMBERS = 5_000
MAX_ZIP_EXPANDED = 200 * 1024 * 1024    # a workbook expanding past this (or 200x its size) is refused: a zip bomb guard
MAX_ATTACHMENTS = 50
MONTH_FIELDS = {"in_service", "coverage_start", "coverage_end", "service_start", "service_end"}   # fields a month alone can state
EXTRACTOR = "nhb-intake/2026-10-16.10"   # a person's file role closes its layout question; retainage on invoices; statement line references; payroll withholding and employer tax


class UnreadableFile(Exception):
    """A file that can't be read, and why: protected (a password), corrupt, unsupported (a format with no reader here),
    or limit (too many pages, rows, or an archive that expands too far)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def detect(name, data):
    """What the bytes are (not what the name says): pdf, xlsx, docx, pptx, odf, zip, ole_encrypted, xls, doc, ole, png,
    jpeg, heic, tiff, gif, webp, sqlite, eml, ofx, json, xml, html, ics, text, binary."""
    head = data[:16]
    if data[:5] == b"%PDF-" or b"%PDF-" in data[:1024]:
        return "pdf"
    if data[:2] == b"PK":
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "zip_corrupt"
        if "xl/workbook.xml" in names or any(n.startswith("xl/worksheets/") for n in names):
            return "xlsx"
        if "word/document.xml" in names:
            return "docx"
        if "ppt/presentation.xml" in names:
            return "pptx"
        if "mimetype" in names or "content.xml" in names:
            return "odf"
        return "zip"
    if head[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        u = lambda t: t.encode("utf-16-le")                # noqa: E731
        if u("EncryptedPackage") in data[:65536] or u("EncryptionInfo") in data[:65536]:
            return "ole_encrypted"
        if u("Workbook") in data or u("Book") in data:
            return "xls"
        if u("WordDocument") in data:
            return "doc"
        return "ole"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc", b"ftypmsf1"):
        return "heic"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if head == b"SQLite format 3\x00":
        return "sqlite"
    if b"\x00" in data[:4096] and not data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "binary"
    low = name.lower()
    text = data[:2000].decode("utf-8", "replace").lstrip("\ufeff").lstrip()
    if low.endswith(".eml") or re.match(r"(?i)(from|received|return-path|message-id|mime-version): ", text[:200]):
        return "eml"
    if "<OFX>" in text[:400] or text.startswith("OFXHEADER"):
        return "ofx"
    if text[:1] in ("{", "["):
        return "json"
    if re.match(r"(?i)<!doctype html|<html", text):
        return "html"
    if text.startswith("<?xml") or text.startswith("<"):
        return "xml"
    if text.startswith("BEGIN:VCALENDAR"):
        return "ics"
    return "text"


UNSUPPORTED = {"docx": "a Word document: send it as a PDF", "pptx": "a PowerPoint file: send it as a PDF",
               "odf": "an OpenDocument file: save it as .xlsx, CSV or PDF", "zip": "a zip archive: upload the files inside it",
               "xls": "an old Excel workbook (.xls): save it as .xlsx or CSV", "doc": "an old Word document (.doc): send it as a PDF",
               "ole": "an old Office file: save it as .xlsx, CSV or PDF", "gif": "a GIF image: send a photo (JPEG, PNG or HEIC) or a PDF",
               "webp": "a WebP image: send a JPEG, PNG or PDF", "binary": "a binary file with no reader here"}


def refuse_unreadable(kind):
    """UnreadableFile for a detected type nothing reads, or None."""
    if kind == "ole_encrypted":
        return UnreadableFile("protected", "a password-protected Office file: ask the client for an unprotected copy (or the "
                                           "password, through the secure request)")
    if kind == "zip_corrupt":
        return UnreadableFile("corrupt", "a damaged file (an incomplete zip): ask for it again")
    if kind in UNSUPPORTED:
        return UnreadableFile("unsupported", UNSUPPORTED[kind])
    return None


_OCR_WHY = {}


def _ocr(data, kind):
    """OCR (or PDFKit's text layer) result, or None when no engine is available (the reason is kept)."""
    from .. import ocr
    try:
        return ocr.recognize(data, kind)
    except ocr.OCRUnavailable as e:
        _OCR_WHY["last"] = str(e)
        return None


def _pdf_encrypted(data):
    tail = data[-4096:] if len(data) > 4096 else data
    return b"/Encrypt" in tail or re.search(rb"trailer\s*<<[^>]*/Encrypt", data[-65536:]) is not None


@dataclass
class Table:
    name: str
    headers: list
    rows: list                      # list of dicts header -> raw text
    source: str = "csv"             # csv | xlsx | json | pdf | text | image
    text: str = ""                  # full text (pdf/text)
    empty_marker: bool = False      # a file that says "no rows"
    units: object = None            # "cents" when the whole report states integer cents, or {column: unit} per value
    meta: dict = field(default_factory=dict)   # document-level facts (statement account, period, sender, date ...)


@dataclass
class Layout:
    rtype: str | None
    colmap: dict = field(default_factory=dict)     # canonical -> header
    unknown: list = field(default_factory=list)    # headers not used
    missing: list = field(default_factory=list)    # required fields not found
    how: str = "registry"                          # registry | client | filename | none
    fingerprint: str = ""


def fingerprint(headers) -> str:
    return hashlib.sha256("|".join(sorted(L.norm_header(h) for h in headers)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- readers

def _zip_limits(z):
    infos = z.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise UnreadableFile("limit", f"the file holds {len(infos)} parts (limit {MAX_ZIP_MEMBERS})")
    total = sum(i.file_size for i in infos)
    packed = sum(i.compress_size for i in infos) or 1
    if total > MAX_ZIP_EXPANDED or (total > 10 * 1024 * 1024 and total / packed > 200):
        raise UnreadableFile("limit", "the workbook expands far beyond its size; refused (a guard against zip bombs)")


def _xlsx_sheets(data: bytes):
    """[(sheet name, state, rows)] for every sheet in workbook order, and whether the workbook carries macros (never run:
    only the cell values are read)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        _zip_limits(z)
        names = set(z.namelist())
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        targets = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for r in ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels")):
                t = r.get("Target") or ""
                targets[r.get("Id")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
        order = []
        if "xl/workbook.xml" in names:
            for sh in ElementTree.fromstring(z.read("xl/workbook.xml")).iter("{%s}sheet" % ns["m"]):
                order.append((sh.get("name"), sh.get("state") or "visible", targets.get(sh.get(rns))))
        if not order:                                       # no workbook index: every worksheet part, in name order
            order = [(n.rsplit("/", 1)[-1], "visible", n) for n in sorted(names) if n.startswith("xl/worksheets/sheet")]
        out = []
        for sname, state, part in order:
            if not part or part not in names:
                continue
            rows = []
            for row in ElementTree.fromstring(z.read(part)).iter("{%s}row" % ns["m"]):
                cells = {}
                for c in row.findall("m:c", ns):
                    col = re.match(r"[A-Z]+", c.get("r") or "A").group(0)
                    idx = 0
                    for ch in col:
                        idx = idx * 26 + ord(ch) - 64
                    v = c.find("m:v", ns)
                    t = c.get("t")
                    if t == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                    else:
                        val = v.text if v is not None else ""
                    cells[idx - 1] = val
                if cells:
                    rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
                    if len(rows) > MAX_SHEET_ROWS:
                        raise UnreadableFile("limit", f"sheet {sname!r} has more than {MAX_SHEET_ROWS:,} rows")
            out.append((sname, state, rows))
        return out, "xl/vbaProject.bin" in names
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError, IndexError) as e:
        raise UnreadableFile("corrupt", f"the workbook is damaged ({type(e).__name__}): ask for it again") from None


def _xlsx_rows(data: bytes):
    """The first sheet's rows (older callers)."""
    sheets, _ = _xlsx_sheets(data)
    return sheets[0][2] if sheets else []


def _header_row(rows):
    """Index of the row that looks most like a header: the most cells matching known column names."""
    known = {a for aliases in L.FIELD_ALIASES.values() for a in aliases}
    best, best_i = 0, 0
    for i, r in enumerate(rows[:15]):
        score = sum(1 for c in r if L.norm_header(c) in known)
        if score > best:
            best, best_i = score, i
    return best_i


EMPTY_WORDS = ("no_rows", "no_data", "none", "empty", "no_activity", "no_transactions", "nothing_to_report")


def _grid_to_table(name, grid, source):
    grid = [r for r in grid if any(str(c).strip() for c in r)]
    if not grid:
        return Table(name, [], [], source, empty_marker=True)
    if len(grid) == 1 and len(grid[0]) == 1 and L.norm_header(grid[0][0]) in EMPTY_WORDS:
        return Table(name, [], [], source, empty_marker=True)
    h = _header_row(grid)
    headers = [str(c).strip() for c in grid[h]]
    rows = []
    for r in grid[h + 1:]:
        rows.append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers)) if headers[i]})
    return Table(name, [x for x in headers if x], rows, source)


def flatten(obj, prefix="", keep_lists=False):
    """{'money': {'net_minor': 1}} -> {'money_net_minor': 1}. Lists of values are joined (kept as lists for a one-object
    control document); lists of objects kept as JSON."""
    out = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "_", keep_lists))
        elif isinstance(v, list) and keep_lists:
            out[key] = v
        elif isinstance(v, list):
            out[key] = json.dumps(v) if any(isinstance(x, (dict, list)) for x in v) else ";".join(str(x) for x in v)
        else:
            out[key] = v
    return out


def _rows_table(name, rows, source, **kw):
    rows = [flatten(r) for r in rows]
    headers = list(dict.fromkeys(k for r in rows for k in r))
    return Table(name, headers, rows, source, empty_marker=not rows, **kw)


def _states_cents(text):
    return bool(re.search(r"(?i)(integer cents|amounts?(?: are)?(?: in)? (?:explicit |integer )?cents|in cents\b|explicit cents)", text or ""))


def _ofx(name, text):
    """OFX / QFX bank download (SGML or XML): the statement's transactions and its ledger balance."""
    def tag(block, t):
        m = re.search(rf"<{t}>([^<\r\n]*)", block)
        return m.group(1).strip() if m else None

    def d(v):
        return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if v and re.match(r"\d{8}", v) else v
    tables = []
    for stmt in re.findall(r"<STMTRS>(.*?)</STMTRS>", text, re.S) or re.findall(r"<CCSTMTRS>(.*?)</CCSTMTRS>", text, re.S) or [text]:
        acct = tag(stmt, "ACCTID")
        rows = []
        for t in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", stmt, re.S):
            rows.append({"account": acct, "date": d(tag(t, "DTPOSTED")), "amount": tag(t, "TRNAMT"), "line_id": tag(t, "FITID"),
                         "description": tag(t, "MEMO") or tag(t, "NAME"), "transaction_kind": tag(t, "TRNTYPE"),
                         "check_number": tag(t, "CHECKNUM")})
        meta = {"account": acct, "coverage_start": d(tag(stmt, "DTSTART")), "coverage_end": d(tag(stmt, "DTEND")),
                "closing": tag(re.search(r"<LEDGERBAL>(.*?)(?:</LEDGERBAL>|$)", stmt, re.S).group(1), "BALAMT")
                if "<LEDGERBAL>" in stmt else None, "currency": tag(stmt, "CURDEF")}
        tables.append(Table(name, ["account", "date", "amount", "line_id", "description", "transaction_kind", "check_number"], rows,
                            "ofx", empty_marker=not rows, meta=meta))
    return tables


def _sqlite(name, data):
    import os
    import sqlite3
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    try:
        os.write(fd, data)
        os.close(fd)
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        out = []
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rootpage"):
            cur = con.execute(f'SELECT * FROM "{t}"')
            headers = [c[0] for c in cur.description]
            rows = [{h: ("" if v is None else str(v)) for h, v in zip(headers, r)} for r in cur]
            out.append(Table(f"{name}:{t}", headers, rows, "sqlite", empty_marker=not rows, meta={"table": t}))
        con.close()
        return out
    finally:
        os.remove(path)


def _xml(name, text):
    """Repeated child records of the root (or of the first element that repeats) -> rows; nested elements flattened.
    The root's attributes (currency, units) are document facts."""
    root = ElementTree.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    raw = text if isinstance(text, str) else text.decode("utf-8", "replace")
    prefixes = {uri: p for p, uri in re.findall(r'xmlns:([A-Za-z_][\w.-]*)="([^"]+)"', raw)}
    units = {}

    def local(t):
        return t.split("}", 1)[-1]

    def ns(t):
        return t[1:].split("}", 1)[0] if t.startswith("{") else None

    def to_dict(el):
        kids = list(el)
        if not kids:
            return (el.text or "").strip()
        out = {local(k): v for k, v in el.attrib.items()}
        # the same name in two namespaces is two different fields (a posting date and a service date): keep both,
        # named by their namespace prefix, never joined into one value
        clash = {local(c.tag) for c in kids if len({ns(x.tag) for x in kids if local(x.tag) == local(c.tag)}) > 1}
        for c in kids:
            v = to_dict(c)
            k = local(c.tag)
            if k in clash and ns(c.tag):
                k = f"{prefixes.get(ns(c.tag), ns(c.tag).rsplit('/', 1)[-1].rsplit(':', 1)[-1])}_{k}"
            if k in out:                                   # a repeated child: keep them all
                out[k] = (out[k] if isinstance(out[k], list) else [out[k]]) + [v]
            else:
                out[k] = v
            if not list(c) and c.attrib:                   # a value's own attributes (currency, unit) stay with it
                for a, av in c.attrib.items():
                    out[f"{k}_{local(a)}"] = av
                    if local(a) in ("unit", "units") and "cent" in av.lower():
                        units[k] = "cents"
        return out
    node = root
    while len(node) == 1 and len(list(node[0])) and len({local(c.tag) for c in node[0]}) == 1 and len(node[0]) > 1:
        node = node[0]
    kids = list(node)
    meta = {local(k): v for k, v in root.attrib.items()}
    if not kids and not (node.text or "").strip():
        return [Table(name, [], [], "xml", empty_marker=True, meta=meta)]      # an export with no records
    if kids and all(len(list(k)) for k in kids):
        rows = [to_dict(k) for k in kids]
        rows = [r if isinstance(r, dict) else {"value": r} for r in rows]
        doc_units = "cents" if _states_cents(text) else None
        return [_rows_table(name, rows, "xml", meta=meta, units=dict(units, **({"*": doc_units} if doc_units else {})) if units else doc_units)]
    return [_rows_table(name, [to_dict(node) if isinstance(to_dict(node), dict) else {"value": to_dict(node)}], "xml", meta=meta)]


class _HTML:
    """Tables (a header row of <th> cells or a <thead>, then data rows) and the page's text outside tables."""
    def __init__(self, text):
        from html.parser import HTMLParser
        self.tables, self.notes, self.title = [], [], None
        outer = self

        class P(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.cell = self.row = self.table = None
                self.stack, self.thead, self.row_th = [], False, False

            def handle_starttag(self, tag, attrs):
                self.stack.append(tag)
                if tag == "table":
                    self.table = {"head": [], "rows": []}
                elif tag == "thead":
                    self.thead = True
                elif tag == "tr" and self.table is not None:
                    self.row, self.row_th = [], False
                elif tag in ("td", "th") and self.row is not None:
                    self.cell = []
                    self.row_th = self.row_th or tag == "th"

            def handle_endtag(self, tag):
                if self.stack and self.stack[-1] == tag:
                    self.stack.pop()
                if tag in ("td", "th") and self.cell is not None:
                    self.row.append(" ".join("".join(self.cell).split()))
                    self.cell = None
                elif tag == "tr" and self.row is not None:
                    if (self.thead or self.row_th) and not self.table["head"]:
                        self.table["head"] = self.row
                    else:
                        self.table["rows"].append(self.row)
                    self.row = None
                elif tag == "thead":
                    self.thead = False
                elif tag == "table" and self.table is not None:
                    outer.tables.append(self.table)
                    self.table = None

            def handle_data(self, data):
                if self.cell is not None:
                    self.cell.append(data)
                elif self.table is None and data.strip():
                    if self.stack and self.stack[-1] == "title":
                        outer.title = data.strip()
                    elif not self.stack or self.stack[-1] not in ("script", "style"):
                        outer.notes.append(data.strip())
        P().feed(text)


def _html(name, text):
    h = _HTML(text)
    notes = " ".join(n for n in h.notes if n != h.title)
    cents = _states_cents(notes)
    out = []
    for t in h.tables:
        head = t["head"] or (t["rows"].pop(0) if t["rows"] else [])
        rows = [{head[i]: (r[i] if i < len(r) else "") for i in range(len(head)) if head[i]} for r in t["rows"]]
        out.append(Table(name, [x for x in head if x], rows, "html", empty_marker=not rows, text=notes,
                         units="cents" if cents else None, meta={"title": h.title}))
    return out or [Table(name, [], [], "text", text=notes)]


def _fixed_width(name, text):
    """A text report with a header row of column names over aligned data (fields may touch): each column runs from its
    header word to the next. Rows end at the first line that isn't data (a trailer note)."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        toks = list(re.finditer(r"[A-Z][A-Z0-9_]+", ln))
        if len(toks) < 3 or ln.strip() != ln.strip().upper() or len("".join(t.group(0) for t in toks)) < len(ln.replace(" ", "")) * 0.9:
            continue
        nxt = next((l for l in lines[i + 1:] if l.strip()), "")
        if sum(ch.isdigit() for ch in nxt) < len(nxt.replace(" ", "")) * 0.5:
            continue
        starts = [t.start() for t in toks] + [None]
        heads = [t.group(0) for t in toks]
        rows, trailer = [], []
        for ln2 in lines[i + 1:]:
            if not ln2.strip():
                continue
            if trailer or sum(ch.isdigit() for ch in ln2) < len(ln2.replace(" ", "")) * 0.5:
                trailer.append(ln2.strip())
                continue
            rows.append({h: ln2[starts[j]:starts[j + 1]].strip() for j, h in enumerate(heads)})
        pre = "\n".join(lines[:i])
        cents = _states_cents(pre) or any(h.upper().endswith("CENTS") for h in heads)
        return Table(name, heads, rows, "fixed", text="\n".join([pre] + trailer).strip(), units="cents" if cents else None,
                     empty_marker=not rows)
    return None


def _ics(name, text):
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    rows = []
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded, re.S):
        r = {}
        for ln in ev.strip().splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                k = k.split(";", 1)[0].lower().replace("-", "_")
                if k in ("dtstart", "dtend", "dtstamp") and re.match(r"\d{8}", v):
                    v = f"{v[:4]}-{v[4:6]}-{v[6:8]}" + (f"T{v[9:11]}:{v[11:13]}:{v[13:15]}" + ("+00:00" if v.endswith("Z") else "")
                                                         if "T" in v else "")
                r[k] = v.strip()
        rows.append(r)
    return [_rows_table(name, rows, "ics")]


def _eml(name, data, depth=0):
    """The message (its body, sender, date and subject), then each attachment read as the file it is, with where it
    came from. An attachment that can't be read says why; the message and its other attachments are still read."""
    import email
    from email import policy
    m = email.message_from_bytes(data, policy=policy.default)
    body = m.get_body(preferencelist=("plain", "html"))
    try:
        text = body.get_content() if body is not None else ""
    except (LookupError, ValueError):
        text = ""
    if body is not None and body.get_content_type() == "text/html":
        text = " ".join(_HTML(text).notes) or re.sub(r"<[^>]+>", " ", text)
    from email.utils import parsedate_to_datetime
    try:
        sent = parsedate_to_datetime(m["Date"]).date().isoformat() if m["Date"] else None
    except (TypeError, ValueError):
        sent = None
    meta = {"from": m["From"], "to": m["To"], "subject": m["Subject"], "sent": sent, "message_id": m["Message-ID"], "attachments": []}
    tables = [Table(name, [], [], "text", text=f"Subject: {m['Subject'] or ''}\n\n{(text or '').strip()}", meta=meta)]
    if depth >= 2:
        return tables
    for n, part in enumerate(m.iter_attachments(), 1):
        if n > MAX_ATTACHMENTS:
            meta["attachments"].append({"filename": None, "skipped": f"more than {MAX_ATTACHMENTS} attachments"})
            break
        fn = re.sub(r"[^A-Za-z0-9._ -]", "_", (part.get_filename() or f"attachment-{n}").split("/")[-1])[:120]
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        digest = hashlib.sha256(payload).hexdigest()
        meta["attachments"].append({"filename": fn, "bytes": len(payload), "sha256": digest})
        try:
            sub = read_tables(fn, payload, _depth=depth + 1)
        except UnreadableFile as e:
            sub = [Table(fn, [], [], "unreadable", text=str(e), meta={"unreadable": e.kind})]
        for t in sub:
            t.meta.update(attachment=fn, attachment_of=name, attachment_sha256=digest)
            tables.append(t)
    return tables


def image_size(data: bytes):
    """(width, height) of a JPEG or PNG from its header, or None. The picture itself isn't read."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker, seg = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):   # start of frame
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + seg
    return None


def read_tables(name: str, data: bytes, _depth=0) -> list:
    low = name.lower()
    kind = detect(name, data)
    refused = refuse_unreadable(kind)
    if refused:
        raise refused
    if kind == "pdf":
        if _pdf_encrypted(data):
            raise UnreadableFile("protected", "a password-protected PDF: ask the client for an unprotected copy (or the password, "
                                              "through the secure request)")
        text = pdf_text(data)
        if text.strip():
            return [Table(name, [], [], "pdf", text=text, meta={"extracted_by": "pdf-text"})]
        layer = _ocr(data, "pdftext")                      # fonts the standard reader can't decode (Chrome, Word): PDFKit
        if layer is not None and layer.get("error") == "password_protected":
            raise UnreadableFile("protected", "a password-protected PDF: ask the client for an unprotected copy")
        from .. import ocr as _o
        if layer is not None and _o.text_of(layer).strip():
            return [Table(name, [], [], "pdf", text=_o.text_of(layer), meta={"extracted_by": "pdfkit-text", "ocr": _o.summary(layer)})]
        res = _ocr(data, "pdf")                            # a scan: each page rendered and recognized
        if res is None:
            return [Table(name, [], [], "pdf", text="", meta={"ocr_unavailable": _OCR_WHY.get("last")})]
        if res.get("error") == "too_many_pages":
            raise UnreadableFile("limit", f"more than {_o.MAX_PAGES} pages: send the months separately")
        if res.get("error"):
            raise UnreadableFile("corrupt" if res["error"] == "unreadable" else "protected", f"the PDF couldn't be opened ({res['error']})")
        return [Table(name, [], [], "ocr", text=_o.text_of(res), meta={"kind": "pdf", "ocr": _o.summary(res), "ocr_result": res})]
    if kind == "xlsx":
        sheets, macros = _xlsx_sheets(data)
        out = []
        for sname, state, rows in sheets:
            if not any(any(str(c).strip() for c in r) for r in rows):
                continue
            t = _grid(name, rows, "xlsx")
            t.meta.update(sheet=sname, sheet_state=state, macros_ignored=macros, sheets=[x[0] for x in sheets])
            out.append(t)
        return out or [Table(name, [], [], "xlsx", empty_marker=True, meta={"sheets": [x[0] for x in sheets], "macros_ignored": macros})]
    if kind in ("png", "jpeg", "heic", "tiff") or (kind == "binary" and low.endswith((".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"))):
        size = image_size(data)
        meta = {"width": size[0], "height": size[1]} if size else {}
        from .. import ocr as _o
        res = _ocr(data, "image")
        if res is not None and _o.text_of(res).strip():
            return [Table(name, [], [], "ocr", text=_o.text_of(res), meta={**meta, "kind": "image", "ocr": _o.summary(res), "ocr_result": res})]
        meta["ocr"] = _o.summary(res) if res is not None else {"unavailable": _OCR_WHY.get("last")}
        return [Table(name, [], [], "image", meta=meta)]
    if data[:16] == b"SQLite format 3\x00":
        return _sqlite(name, data)
    if kind == "eml":
        return _eml(name, data, _depth)
    text = data.decode("utf-8-sig", errors="replace")
    head = text.lstrip()[:400]
    if low.endswith((".ofx", ".qfx")) or "<OFX>" in head or head.startswith("OFXHEADER"):
        return _ofx(name, text)
    if low.endswith((".jsonl", ".ndjson")) or (text.lstrip()[:1] == "{" and "\n{" in text.strip() and not low.endswith(".json")):
        rows, bad = [], 0
        for ln in text.splitlines():
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    bad += 1
        if rows and not bad:
            return [_rows_table(name, [r for r in rows if isinstance(r, dict)], "json")]
    if low.endswith(".json") or text.lstrip()[:1] in ("{", "["):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return [Table(name, [], [], "text", text=text)]
        if isinstance(obj, dict):
            lists = {k: v for k, v in obj.items() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)}
            if len(lists) == 1:                            # {"period": ..., "rows": [...]}: the rows, with the header facts
                (k, rows), = lists.items()
                facts = {kk: vv for kk, vv in obj.items() if kk != k and not isinstance(vv, (list, dict))}
                return [_rows_table(name, [dict(facts, **r) for r in rows], "json")]
            f = flatten(obj, keep_lists=True)
            return [Table(name, list(f), [f], "json")]
        if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
            return [_rows_table(name, obj, "json")]
        return [Table(name, [], [], "json", empty_marker=not obj)]
    if low.endswith((".xml",)) or head.startswith("<?xml") and "<OFX>" not in head:
        try:
            return _xml(name, text)
        except ElementTree.ParseError:
            return [Table(name, [], [], "text", text=text)]
    if low.endswith((".html", ".htm")) or re.match(r"(?i)<!doctype html|<html", head):
        return _html(name, text)
    if low.endswith(".ics") or head.startswith("BEGIN:VCALENDAR"):
        return _ics(name, text)
    if low.endswith((".txt", ".prn", ".dat", ".rpt")):
        fw = _fixed_width(name, text)
        if fw is not None:
            return [fw]
    if low.endswith((".txt", ".md", ".eml", ".markdown")):
        return [Table(name, [], [], "text", text=text)]
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    grid = list(csv.reader(io.StringIO(text), dialect))
    return [_grid(name, grid, "csv")]


QBO_HEADERS = ["event_id", "date", "object_type", "source_id", "memo", "account", "amount_cents", "dimension"]


def _grid(name, grid, source):
    """A spreadsheet grid -> its table; a QuickBooks report export becomes ledger lines (ops/intake/qbo_reports.py)."""
    q = qbo_reports.read(grid)
    if q is None:
        return _grid_to_table(name, grid, source)
    rows = [{k: ("" if r[k] is None else str(r[k])) for k in QBO_HEADERS} for r in q["rows"]]
    return Table(name, QBO_HEADERS if rows else [], rows, source, empty_marker=not rows and not q["problems"],
                 meta={"qbo_report": q["kind"], "qbo_period": q["period"], "qbo_problems": q["problems"]})


# ---------------------------------------------------------------- recognition

def _match(rtype, headers):
    req, opt, _ = L.TYPES[rtype]
    normed = {L.norm_header(h): h for h in headers}
    used, colmap = set(), {}
    for f in (*req, *opt):
        for alias in L.FIELD_ALIASES.get(f, [f]):
            h = normed.get(alias)
            if h is not None and h not in used:
                colmap[f] = h
                used.add(h)
                break
    missing = [f for f in req if f not in colmap]
    if rtype in ("gl_line", "bank_line", "trial_balance") and "amount" in missing and "debit" in colmap and "credit" in colmap:
        missing.remove("amount")
    for f, parts in L.DERIVED.get(rtype, {}).items():   # an identity built from other columns the file has
        if f in missing and parts[0] in colmap and any(x in colmap for x in parts[1:]):
            missing.remove(f)
    if "coverage_end" in missing and L.STATEMENT_TYPES.get(rtype) in colmap:   # a statement month gives its dates
        missing.remove("coverage_end")
    return colmap, missing, [h for h in headers if h not in used]


def recognize(table: Table, known_layouts=None) -> Layout:
    """Pick the record type whose fields explain the most of the file's columns. `known_layouts` are the client's
    approved mappings {fingerprint: (rtype, colmap)}, which win over the registry."""
    fp = fingerprint(table.headers) if table.headers else ""
    if known_layouts and fp in known_layouts:
        rtype, colmap = known_layouts[fp]
        return Layout(rtype, colmap, [h for h in table.headers if h not in colmap.values()], [], "client", fp)
    for e in L.learned():                                # promoted from people's approvals (product/learning.py)
        if e["fingerprint"] == fp:
            rtype = e["record_type"] if e["kind"] == "mapping" else f"role:{e['role']}"
            colmap = {k: v for k, v in (e.get("columns") or {}).items() if isinstance(v, str) and v in table.headers}
            if e.get("kind") == "mapping" and e.get("rules"):
                colmap["__rules"] = e["rules"]
            return Layout(rtype, colmap, [h for h in table.headers if h not in colmap.values()], [], "learned", fp)
    if table.source in ("json", "xml") and len(table.rows) == 1:
        keys = {L.norm_header(k) for k in table.headers}
        for rtype, need in [*L.JSON_TYPES.items(), *((t, alt) for t, alts in L.JSON_ALTERNATES.items() for alt in alts)]:
            if need <= keys:
                return Layout(rtype, {k: k for k in table.headers}, [], [], "registry", fp)
    if table.empty_marker or not table.headers:
        hint = L.hint_for(table.name) if table.source in ("csv", "xlsx", "json") else None
        return Layout(hint, {}, [], [], "filename" if hint else "none", fp)
    hint = L.hint_for(table.name)
    best = None
    for rtype in L.TYPES:
        if not L.type_evidence(rtype, table.headers, table.name):
            continue
        colmap, missing, unknown = _match(rtype, table.headers)
        if missing:
            continue
        score = (len(colmap) / max(1, len(table.headers)), rtype == hint, len(colmap))
        if best is None or score > best[0]:
            best = (score, rtype, colmap, unknown)
    if best is None:
        auto = L.auto_role(table.headers)                   # a list or a schedule (docs/92 §4, 1.4)
        if auto:
            return Layout(f"role:{auto[0]}", {}, list(table.headers), [], "registry", fp)
        # nearest miss, so the owner can be shown what's missing
        near = max(L.TYPES, key=lambda t: len(_match(t, table.headers)[0]))
        colmap, missing, unknown = _match(near, table.headers)
        return Layout(None, colmap, unknown, missing, "none", fp)
    _, rtype, colmap, unknown = best
    return Layout(rtype, colmap, unknown, [], "registry", fp)


# ---------------------------------------------------------------- normalization

def _unit(header, units=None):
    """units: "cents" for a whole report, or {column: unit} when the source says so per value (an XML unit attribute)."""
    h = L.norm_header(header)
    if isinstance(units, dict):
        units = units.get(header) or units.get("*")
    return "cents" if units == "cents" or "cents" in h or h.endswith("minor") else "dollars"


RULE_KEYS = ("negate", "units", "date_order", "constants")


def check_rules(rtype, rules):
    """Problems with a mapping's value rules (docs/92 §4, 1.2), as {key: message}; empty when they're usable."""
    bad = {}
    if not isinstance(rules, dict):
        return {"rules": "the rules are a set of named choices"}
    for k in rules:
        if k not in RULE_KEYS:
            bad[k] = f"{k} isn't a value rule"
    fields = set(L.TYPES.get(rtype, ((), (), ()))[0]) | set(L.TYPES.get(rtype, ((), (), ()))[1])
    for f in rules.get("negate") or []:
        if f not in fields or L.kind_of(f) != "money":
            bad["negate"] = f"{f.replace('_', ' ')} isn't an amount of this record type"
    if rules.get("units") not in (None, "dollars", "cents"):
        bad["units"] = "amounts are in dollars or in cents"
    if rules.get("date_order") not in (None, "mdy", "dmy", "ymd"):
        bad["date_order"] = "dates are month-day-year, day-month-year or year-month-day"
    for f, v in (rules.get("constants") or {}).items():
        if f not in fields:
            bad["constants"] = f"{f.replace('_', ' ')} isn't a field of this record type"
        elif v is None or not str(v).strip():
            bad["constants"] = f"say the value for {f.replace('_', ' ')}"
    return bad


def normalize_row(rtype, colmap, raw: dict, date_order="mdy", units=None, rules=None):
    """(record dict, problems). The record has canonical fields only; `raw` is kept separately by the caller.

    rules (docs/92 §4, 1.2), from a person's mapping or a learned layout (colmap["__rules"] when stored with the layout):
      negate     amount fields written with the opposite sign (a card export with purchases positive, say)
      units      "dollars" or "cents" for amounts whose column name doesn't say
      date_order "mdy", "dmy" or "ymd" when the file's dates are written another way than the client's default
      constants  a value every row has but the file doesn't carry ({"account": "2100"} for one card's export)"""
    rules = rules if rules is not None else (colmap.get("__rules") or {})
    colmap = {k: v for k, v in colmap.items() if not k.startswith("__")}
    if rules:
        raw = dict(raw)
        for f, v in (rules.get("constants") or {}).items():
            raw[f"__const_{f}"] = str(v)
            colmap[f] = f"__const_{f}"
        date_order = rules.get("date_order") or date_order
        if rules.get("units") == "cents":
            units = "cents"
        elif rules.get("units") == "dollars" and not isinstance(units, dict):
            units = {"*": "dollars"}
    rec, problems = {}, []
    for f, h in colmap.items():
        v = raw.get(h)
        k = L.kind_of(f)
        if k == "money":
            val, p = parse_money(v, _unit(h, units))
            cur = str(raw.get(f"{h}_currency") or "").strip().upper()
            if val is not None and cur and cur != "USD":        # another currency: never read as dollars
                val, p = None, f"amount in {cur}, not USD; needs a conversion or a mapping"
        elif k == "date":
            if f in MONTH_FIELDS and isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}", v.strip()):
                v = v.strip() + "-01"                     # a month ("2025-02" in service): its first day
            val, p = parse_date(v, date_order)
        elif k == "time":
            val, p = parse_datetime(v)
        elif k == "int":
            val, p = parse_int(v)
        elif k == "number":
            val, p = parse_number(v)
        elif k == "bool":
            val, p = parse_bool(v)
        elif k == "list":
            val = [x.strip() for x in re.split(r"[;|,]", str(v)) if x.strip()] if not blank(v) else []
            p = None
        else:
            val, p = (None if blank(v) else str(v).strip()), None
        rec[f] = val
        if p:
            problems.append(f"{h}: {p}")
    for f, parts in L.DERIVED.get(rtype, {}).items():
        if rec.get(f) is None and rec.get(parts[0]) is not None and any(rec.get(x) is not None for x in parts[1:]):
            rec[f] = "|".join(str(rec[x]) for x in parts if rec.get(x) is not None)
    if "amount" not in rec and ("debit" in rec or "credit" in rec):
        d, c = rec.get("debit") or 0, rec.get("credit") or 0
        if rec.get("debit") is None and rec.get("credit") is None:
            rec["amount"] = None
        else:
            rec["amount"] = d - c if rtype in ("gl_line", "trial_balance") else c - d
    for f in rules.get("negate") or []:
        if isinstance(rec.get(f), (int, float)):
            rec[f] = -rec[f]
    if rtype in L.STATEMENT_TYPES:
        _statement_summary(rtype, colmap, rec, problems)
    return rec, problems


def _statement_summary(rtype, colmap, rec, problems):
    """A statement summary row: a statement month ('2025-01', '01/2025') gives the period's first and last days; the
    bank arithmetic is checked (opening + deposits - withdrawals = closing); a card cycle carries start/end as its
    JSON form does."""
    per = rec.get("statement_period")
    if per and not rec.get("coverage_end"):
        m = re.fullmatch(r"(\d{4})-(\d{1,2})|(\d{1,2})/(\d{4})", str(per).strip())
        if m and 1 <= int(m.group(2) or m.group(3)) <= 12:
            from ..core import month_bounds
            a, b = month_bounds(f"{m.group(1) or m.group(4)}-{int(m.group(2) or m.group(3)):02d}")
            rec["coverage_start"] = rec.get("coverage_start") or a.isoformat()
            rec["coverage_end"] = b.isoformat()
        else:
            problems.append(f"{colmap.get('statement_period')}: {per!r} isn't a statement month (YYYY-MM or MM/YYYY)")
    if rtype == "statement_control" and None not in (rec.get("opening_cents"), rec.get("closing_cents")) and \
            (rec.get("total_deposits") is not None or rec.get("total_withdrawals") is not None):
        want = rec["opening_cents"] + (rec.get("total_deposits") or 0) - abs(rec.get("total_withdrawals") or 0)
        if want != rec["closing_cents"]:
            problems.append(f"{colmap.get('closing_cents')}: opening {rec['opening_cents'] / 100:,.2f} + deposits - withdrawals = "
                            f"{want / 100:,.2f}, but the closing balance is {rec['closing_cents'] / 100:,.2f}")
    if rtype == "card_cycle_control":
        rec["start"], rec["end"] = rec.get("coverage_start"), rec.get("coverage_end")


def json_record(rtype, obj):
    """Control JSON objects keep their own keys; *_cents keys are integer cents already. A statement control given by
    period ('2025-01') gets that month's coverage dates."""
    rec = {L.norm_header(k): v for k, v in obj.items()}
    if rtype == "statement_control" and rec.get("period") and not rec.get("coverage_end"):
        from ..core import month_bounds
        a, b = month_bounds(str(rec["period"])[:7])
        rec.setdefault("coverage_start", a.isoformat())
        rec["coverage_end"] = b.isoformat()
    if rtype == "client_profile":
        rec.setdefault("tenant_id", rec.get("entity_id"))
    return rec
