"""Layout agent: works out an unfamiliar file's columns the way a bookkeeper would, from the header wording and from what
the values actually look like, and proposes a mapping to a standard record type.

  propose(table) -> Proposal(rtype, colmap, confidence, notes, value_problems)

Header evidence: similarity of each header to every known spelling of a field (word overlap and character similarity,
so "Bill No.", "Supplier Inv #" and "Amt (USD)" still land on the right fields).
Value evidence: a column only maps to a field whose kind its values fit (dates parse as dates, amounts as money, ids
look like ids, yes/no as yes/no), so a "Date" header over amounts is refused.
Confidence is high only when every field the record type can't do without is mapped and nearly every column is
explained; high-confidence proposals are applied and shown to the owner, anything less waits for the owner.

An AI model can be asked for a second opinion only when the client file allows it (profile ai_assist) and a key is
configured; it is off by default and never needed for the deterministic path.
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import layouts as L
from .values import blank, parse_bool, parse_date, parse_datetime, parse_money

ABBREV = {"no": "number", "num": "number", "nbr": "number", "#": "number", "amt": "amount", "dt": "date", "desc": "description",
          "inv": "invoice", "cust": "customer", "vend": "vendor", "supp": "supplier", "qty": "quantity", "ref": "reference",
          "acct": "account", "pmt": "payment", "pymt": "payment", "txn": "transaction", "trx": "transaction", "tot": "total",
          "emp": "employee", "hrs": "hours", "usd": "", "id": "id"}


WEAK_MONEY_NAME = 0.6                     # below this, a money column's (or an essential field's) name is too unlike the field to map it unasked


@dataclass
class Proposal:
    rtype: str | None
    colmap: dict = field(default_factory=dict)
    confidence: float = 0.0
    notes: list = field(default_factory=list)
    value_problems: list = field(default_factory=list)
    date_order: str | None = None

    rows_checked: int = 0

    @property
    def high(self):
        return self.rtype is not None and self.confidence >= 0.8 and not self.value_problems


def _words(h):
    h = str(h).lower().replace("#", " number ")
    toks = [t for t in re.split(r"[^a-z0-9]+", h) if t]
    return [ABBREV.get(t, t) for t in toks if ABBREV.get(t, t)]


def _sim(header, alias):
    a, b = _words(header), alias.split("_")
    if not a:
        return 0.0
    overlap = len(set(a) & set(b)) / max(len(set(a) | set(b)), 1)
    chars = SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    return max(overlap, chars * 0.9)


def _kind_fit(kind, values):
    """Share of non-blank sample values that fit a field kind (1.0 = all fit)."""
    vals = [v for v in values if not blank(v)]
    if not vals:
        return 0.5                                          # an empty column fits anything, weakly
    ok = 0
    for v in vals:
        if kind == "date":
            ok += parse_date(v)[0] is not None
        elif kind == "time":
            ok += parse_datetime(v)[0] is not None
        elif kind == "money":
            ok += parse_money(v)[0] is not None
        elif kind == "int":
            ok += bool(re.fullmatch(r"-?\d+", str(v).strip()))
        elif kind == "bool":
            ok += parse_bool(v)[0] is not None
        elif kind == "id":
            ok += bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/#:-]*", str(v).strip())) and len(str(v)) <= 64
        else:
            ok += 1
    return ok / len(vals)


def _date_order(values):
    """'dmy' or 'mdy' when a slash-date column says so (a first part over 12), else None (ambiguous)."""
    first, second = False, False
    for v in values:
        m = re.match(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}\s*$", str(v))
        if m:
            first |= int(m.group(1)) > 12
            second |= int(m.group(2)) > 12
    return "dmy" if first and not second else "mdy" if second and not first else None


_ALIASES = {}


def _named_for(header):
    """The fields a column's exact name is a known spelling of (empty when the name isn't one exactly)."""
    if not _ALIASES:
        for f, aliases in L.FIELD_ALIASES.items():
            for a in (f, *aliases):
                _ALIASES.setdefault(re.sub(r"[^a-z0-9]+", "_", str(a).lower()).strip("_"), set()).add(f)
    return _ALIASES.get(re.sub(r"[^a-z0-9]+", "_", str(header).lower()).strip("_"), set())


def propose(table, sample=50, date_order=None):
    """date_order: the client's declared format ('mdy' for US exports), used when the file itself doesn't settle it."""
    headers = table.headers
    cols = {h: [r.get(h) for r in table.rows[:sample]] for h in headers}
    best = None
    for rtype, (req, opt, _) in L.TYPES.items():
        if not L.type_evidence(rtype, table.headers, table.name):
            continue
        fields = list(dict.fromkeys((*req, *opt)))
        cands = []
        for f in fields:
            kind = L.kind_of(f)
            for h in headers:
                name = max(_sim(h, a) for a in L.FIELD_ALIASES.get(f, [f]))
                if name < 0.45:
                    continue
                fit = _kind_fit(kind, cols[h])
                if fit < 0.9:
                    continue
                cands.append((name * (0.6 + 0.4 * fit), f, h, name))
        cands.sort(reverse=True)
        colmap, used, names = {}, set(), {}
        for score, f, h, name in cands:
            if f in colmap or h in used:
                continue
            colmap[f] = (h, score)
            names[f] = name
            used.add(h)
        must = L.MUST.get(rtype, req)
        amount_ok = "amount" not in must or "amount" in colmap or ("debit" in colmap and "credit" in colmap)
        missing = [f for f in must if f not in colmap and not (f == "amount" and amount_ok)]
        if missing:
            continue
        coverage = len(used) / max(len(headers), 1)
        quality = sum(s for _, s in colmap.values()) / max(len(colmap), 1)
        conf = round(min(1.0, 0.55 * coverage + 0.45 * quality), 3)
        # an amount taken from a column whose name only loosely resembles the field ("earned_release_cents" as tax) is a
        # guess: it's shown to the owner, never applied on its own. So is a field every row needs (the record's own id,
        # its date) taken from a loosely named column: text accepts any values, so only the name says it's that field
        # ("Notes" as an invoice number, "policy_id" as a warranty claim). A person maps those (product/mappings.py).
        loose = [f"{colmap[f][0]} as {f}" for f, n in names.items()
                 if n < WEAK_MONEY_NAME and (L.kind_of(f) == "money" or f in must)]
        # a column named exactly as another record's identifier ("vendor_id" taken as the tenant, "bill_id" as an invoice
        # number) belongs to a different record type: the proposal is shown, never applied on its own (docs/92 §4, 4.1)
        loose += [f"{h} as {f}" for f, (h, _) in colmap.items()
                  if (ids := {x for x in _named_for(h) if L.kind_of(x) == "id"}) and f not in ids]
        if loose:
            conf = min(conf, 0.79)
        key = (conf, len(colmap))
        if best is None or key > best[0]:
            best = (key, rtype, {f: h for f, (h, _) in colmap.items()}, conf, [h for h in headers if h not in used], loose)
    if best is None:
        return Proposal(None, notes=["no record type's essential fields could be found in these columns"])
    _, rtype, colmap, conf, unused, loose = best
    p = Proposal(rtype, colmap, conf)
    if loose:
        p.notes.append("columns matched only loosely by name: " + ", ".join(loose))
    if unused:
        p.notes.append(f"columns not used: {', '.join(unused)}")
    # the evidence for the record type came from a sample; the checks below read every row, so one bad value deep in
    # the file (a date that can't be month-first, an amount in another currency) keeps the mapping from being applied
    cols = {h: [r.get(h) for r in table.rows] for h in headers}
    p.rows_checked = len(table.rows)
    date_cols = [h for f, h in colmap.items() if L.kind_of(f) == "date"]
    orders = {o for o in (_date_order(cols[h]) for h in date_cols) if o}
    if len(orders) > 1:
        p.value_problems.append("date columns disagree on day-first vs month-first")
    p.date_order = next(iter(orders)) if len(orders) == 1 else date_order
    if p.date_order and not orders:
        p.notes.append(f"dates read as {p.date_order} (the client's declared format)")
    for f, h in colmap.items():
        k = L.kind_of(f)
        if k == "date" and p.date_order is None:
            ambiguous = [v for v in cols[h] if re.match(r"^\s*\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\s*$", str(v or ""))]
            if ambiguous:
                p.value_problems.append(f"{h}: dates like {ambiguous[0]!r} could be day-first or month-first")
        if k == "money":
            bad = [(i, v) for i, v in enumerate(cols[h], 1) if not blank(v) and parse_money(v)[0] is None]
            if bad:
                p.value_problems.append(f"{h}: {len(bad)} amount(s) like {bad[0][1]!r} (row {bad[0][0]}) can't be read with certainty")
            cur = {m.group(0).upper() for v in cols[h] if not blank(v) for m in [re.search(r"(?i)\b(USD|CAD|EUR|GBP|AUD|MXN)\b|[€£¥]", str(v))] if m}
            if len(cur) > 1 or (cur and cur - {"USD"}):
                p.value_problems.append(f"{h}: amounts in {', '.join(sorted(cur))}: the currency has to be confirmed before they're used")
        elif k in ("date", "time"):
            bad = [(i, v) for i, v in enumerate(cols[h], 1) if not blank(v) and (parse_date(v)[0] if k == "date" else parse_datetime(v)[0]) is None]
            if bad:
                p.value_problems.append(f"{h}: {len(bad)} value(s) like {bad[0][1]!r} (row {bad[0][0]}) aren't dates")
        must = L.MUST.get(rtype, ())
        if f in must:
            gaps = sum(1 for v in cols[h] if blank(v))
            if gaps:
                p.notes.append(f"{h}: {gaps} row(s) blank in a field every row needs (those rows are set aside, with the reason)")
    return p
