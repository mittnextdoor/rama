"""QuickBooks Online report exports (CSV or Excel) read as the books as recorded (docs/74, B-5).

QuickBooks stays the system of record; until its API is approved for a client, the firm exports reports and uploads
them. Recognized by the report's own title and column headings, never by the file's name:

  Journal                  every transaction with all its lines, debits and credits: read exactly. The preferred export.
  General Ledger           (and Transaction Detail by Account) lines listed under each account; read when it carries
                           Debit and Credit columns, or an Amount column whose lines balance as debits-positive within
                           every transaction. Lines are grouped back into transactions by date, type, number and name;
                           a group that doesn't balance is set aside, never forced.
  Trial Balance            account balances at a date: the opening balances when uploaded with the handover files.
  Transaction List         refused with the reason: it carries one line per transaction, so split transactions can't be
                           rebuilt. The Journal is asked for instead.

Each transaction gets an id from its own content (date, type, number, name and lines), so the same transaction in a
later export is recognized as the same one. A newer export of a ledger report replaces the earlier export's lines for
the dates it covers (ops/intake/store.py), so a transaction edited in QuickBooks between exports isn't counted twice.

Nothing here guesses: an amount, date or sign convention that can't be read with certainty leaves the row out and says
why."""
import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

TITLES = {
    "journal": ("journal",),
    "general_ledger": ("general ledger", "transaction detail by account"),
    "trial_balance": ("trial balance",),
    "transaction_list": ("transaction list by date", "transaction list", "transaction report"),
}
LEDGER = ("journal", "general_ledger")
COLS = {
    "date": ("date", "transaction date", "txn date"),
    "type": ("transaction type", "type", "txn type"),
    "num": ("num", "no.", "no", "number", "ref no.", "ref no", "ref #"),
    "name": ("name", "payee", "customer/vendor"),
    "memo": ("memo/description", "memo", "description", "line description"),
    "account": ("account", "account name", "account full name", "full name"),
    "account_number": ("account #", "account number", "acct #", "account no."),
    "split": ("split", "split account"),
    "dimension": ("class", "location", "department", "project", "customer:job"),
    "debit": ("debit",),
    "credit": ("credit",),
    "amount": ("amount",),
    "balance": ("balance",),
}
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september",
                                       "october", "november", "december"), 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})


def _cell(v):
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def _key(v):
    return _cell(v).lower().rstrip(":")


def cents(v):
    """'1,800.00', '-1,800.00', '(1,800.00)', '$1,800.00', '1800' -> cents; '' -> None; unreadable -> ValueError."""
    s = _cell(v)
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.endswith("-")
    s = s.strip("()").replace("$", "").replace(",", "").replace(" ", "").strip("-")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"amount {v!r} isn't a number")
    c = d * 100
    if c != c.to_integral_value():
        raise ValueError(f"amount {v!r} has fractions of a cent")
    return -int(c) if neg else int(c)


def day(v):
    """'01/05/2025', '1/5/2025', '2025-01-05' or an Excel date number -> ISO date; anything else -> None."""
    s = _cell(v)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        if re.fullmatch(r"\d{5}(\.0+)?", s) and 30000 < float(s) < 60000:      # an Excel date number
            return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
    except ValueError:
        return None
    return None


def _range(text):
    """A report's date line -> (start, end) ISO dates, when it states them: 'January 1-31, 2025', 'January 2025',
    'January 1 - March 31, 2025', 'As of January 31, 2025', '01/01/2025 - 01/31/2025'."""
    t = _key(text).replace("–", "-").replace("—", "-")
    m = re.fullmatch(r"(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})", t)
    if m:
        return day(m.group(1)), day(m.group(2))
    m = re.fullmatch(r"as of ([a-z]+) (\d{1,2}), (\d{4})", t)
    if m and m.group(1) in MONTHS:
        d = date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))).isoformat()
        return d, d
    m = re.fullmatch(r"([a-z]+) (\d{1,2})\s*-\s*(?:([a-z]+) )?(\d{1,2}), (\d{4})", t)
    if m and m.group(1) in MONTHS and (m.group(3) or m.group(1)) in MONTHS:
        y = int(m.group(5))
        return (date(y, MONTHS[m.group(1)], int(m.group(2))).isoformat(),
                date(y, MONTHS[m.group(3) or m.group(1)], int(m.group(4))).isoformat())
    m = re.fullmatch(r"([a-z]+),? (\d{4})", t)
    if m and m.group(1) in MONTHS:
        y, mo = int(m.group(2)), MONTHS[m.group(1)]
        end = date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
        return date(y, mo, 1).isoformat(), end.isoformat()
    return None


def detect(grid):
    """(report kind, title row index, header row index, {field: column}, (start, end) or None), or None if the grid
    isn't a QuickBooks report."""
    rows = [[_cell(c) for c in r] for r in grid[:12]]
    kind, title_at, period = None, None, None
    for i, r in enumerate(rows[:6]):
        filled = [c for c in r if c]
        if len(filled) == 1:
            k = _key(filled[0])
            for rk, names in TITLES.items():
                if k in names and kind is None:
                    kind, title_at = rk, i
            if period is None and _range(filled[0]):
                period = _range(filled[0])
    if kind is None:
        return None
    for i in range(title_at + 1, len(rows)):
        cols = {}
        for j, c in enumerate(rows[i]):
            for f, names in COLS.items():
                if _key(c) in names and f not in cols:
                    cols[f] = j
        money = ("debit" in cols and "credit" in cols) or "amount" in cols
        if money and ("date" in cols or kind == "trial_balance"):
            return kind, title_at, i, cols, period
    return None


def _event_id(kind, date_, typ, num, name, lines, seen):
    h = hashlib.sha256(repr((date_, typ, num, name, sorted(lines))).encode()).hexdigest()[:12]
    seen[h] = seen.get(h, 0) + 1
    return f"QB-{h}" + (f"-{seen[h]}" if seen[h] > 1 else "")


def read(grid):
    """A QuickBooks report grid -> {kind, period, rows: [ledger line dicts], problems: [str]}; None if it isn't one.
    Ledger line: event_id, date, object_type, source_id, memo, account, amount_cents, dimension."""
    found = detect(grid)
    if found is None:
        return None
    kind, _, h, cols, period = found
    body = [[_cell(c) for c in r] for r in grid[h + 1:]]

    def get(r, f):
        j = cols.get(f)
        return r[j] if j is not None and j < len(r) else ""

    out = {"kind": kind, "period": period, "rows": [], "problems": []}
    if kind == "transaction_list":
        out["problems"].append("A Transaction List has one line per transaction, so split transactions can't be rebuilt "
                               "from it. Export the Journal report for the same dates instead.")
        return out
    if kind == "trial_balance":
        as_of = period[1] if period else None
        if as_of is None:
            out["problems"].append("The trial balance doesn't state its date ('As of ...'), so it can't be used as opening balances.")
            return out
        lines = []
        for i, r in enumerate(body, h + 2):
            name = r[0] if r else ""
            if not name or _key(name) == "total" or _key(name).startswith("total "):
                continue
            try:
                d, c = cents(get(r, "debit")), cents(get(r, "credit"))
            except ValueError as e:
                out["problems"].append(f"row {i}: {e}")
                continue
            if d is None and c is None:
                continue
            lines.append({"account": get(r, "account_number") or name, "amount_cents": (d or 0) - (c or 0)})
        if sum(x["amount_cents"] for x in lines):
            out["problems"].append(f"The trial balance doesn't balance (debits less credits = {sum(x['amount_cents'] for x in lines)} "
                                   "cents); it wasn't used.")
            return out
        out["rows"] = [{"event_id": f"QB-OPENING-{as_of}", "date": as_of, "object_type": "Opening",
                        "source_id": "QuickBooks trial balance", "memo": None, "account": x["account"],
                        "amount_cents": x["amount_cents"], "dimension": None} for x in lines]
        return out

    def amount(r):
        if "debit" in cols:
            d, c = cents(get(r, "debit")), cents(get(r, "credit"))
            return None if d is None and c is None else (d or 0) - (c or 0)
        return cents(get(r, "amount"))

    def account_of(r, section):
        num, name = get(r, "account_number"), get(r, "account") or section
        return f"{num} {name}".strip() if num and name and not name.startswith(num) else (num or name)

    txns, seen = [], {}
    if kind == "journal":
        cur, head = None, None
        for i, r in enumerate(body, h + 2):
            if not any(r):
                cur = None
                continue
            acct = account_of(r, "")
            try:
                amt = amount(r)
            except ValueError as e:
                out["problems"].append(f"row {i}: {e}")
                if cur is not None:
                    cur["bad"] = True
                continue
            if not acct:                                   # the transaction's total row (or a report total)
                cur = None
                continue
            d = day(get(r, "date"))
            key = (d, get(r, "type"), get(r, "num"), get(r, "name")) if d else None
            if cur is None or (key and key != head):
                if d is None and cur is None:
                    out["problems"].append(f"row {i}: a line with no transaction date before it; left out")
                    continue
                head = key
                cur = {"date": d, "type": key[1], "num": key[2], "name": key[3], "lines": [], "rows": [], "bad": False}
                txns.append(cur)
            if amt:
                cur["lines"].append((acct, amt, get(r, "dimension") or None, get(r, "memo") or None))
                cur["rows"].append(i)
    else:                                                  # general ledger: lines under each account's heading
        section, groups = "", {}
        for i, r in enumerate(body, h + 2):
            if not any(r):
                continue
            first = next((c for c in r if c), "")
            d = day(get(r, "date"))
            if d is None:
                k = _key(first)
                if not (k.startswith("total") or k.startswith("beginning balance")) and sum(1 for c in r if c) == 1:
                    section = first                         # an account heading
                continue
            try:
                amt = amount(r)
            except ValueError as e:
                out["problems"].append(f"row {i}: {e}")
                continue
            if not amt:
                continue
            key = (d, get(r, "type"), get(r, "num"), get(r, "name"))
            g = groups.setdefault(key, {"date": d, "type": key[1], "num": key[2], "name": key[3], "lines": [], "rows": [], "bad": False})
            g["lines"].append((account_of(r, section), amt, get(r, "dimension") or None, get(r, "memo") or None))
            g["rows"].append(i)
        txns = list(groups.values())
        multi = [t for t in txns if len(t["lines"]) >= 2]
        balanced = [t for t in multi if not sum(x[1] for x in t["lines"])]
        if txns and "debit" not in cols and len(balanced) * 2 <= len(multi or [None]):   # most must balance as debits-positive
            out["problems"].append("This General Ledger's Amount column doesn't balance as debits and credits within its "
                                   "transactions, so its signs can't be read with certainty. Export the Journal report instead.")
            return out
    for t in txns:
        total = sum(x[1] for x in t["lines"])
        if t["bad"] or total or not t["lines"]:
            if t["lines"]:
                out["problems"].append(f"rows {t['rows'][0]}-{t['rows'][-1]}: the transaction on {t['date']} "
                                       f"({t['type'] or 'no type'} {t['num']}) doesn't balance or has an unreadable line; left out")
            continue
        eid = _event_id(kind, t["date"], t["type"], t["num"], t["name"], [(a, c) for a, c, _, _ in t["lines"]], seen)
        for acct, amt, dim, memo in t["lines"]:
            out["rows"].append({"event_id": eid, "date": t["date"], "object_type": t["type"] or None,
                                "source_id": t["num"] or t["name"] or None,
                                "memo": " · ".join(x for x in (t["name"], memo) if x) or None,
                                "account": acct, "amount_cents": amt, "dimension": dim})
    if not out["period"] and out["rows"]:
        ds = sorted(r["date"] for r in out["rows"])
        out["period"] = (ds[0], ds[-1])
    return out


def resolve(chart, ref):
    """An account as a QuickBooks report names it ('6000 Rent', 'Rent', 'Utilities:Electric', '6000') -> the chart's
    account number, when exactly one account matches; otherwise None."""
    ref = _cell(ref)
    by_num = {str(a["account"]): a for a in chart}
    if ref in by_num:
        return ref
    m = re.match(r"^(\d{3,8})\b", ref)
    if m and m.group(1) in by_num:
        return m.group(1)

    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()
    for candidate in (ref, ref.split(":")[-1], re.sub(r"^\d{3,8}\s*[·\-]?\s*", "", ref)):
        hits = [n for n, a in by_num.items() if norm(a.get("account_name")) == norm(candidate) or norm(f"{n} {a.get('account_name')}") == norm(candidate)]
        if len(hits) == 1:
            return hits[0]
    return None
