"""Cleaning raw values from client exports: dates, money, yes/no. Unknown stays unknown (None), never zero.

Every parser returns (value, problem). A problem is a short reason the raw text couldn't be read with certainty; the row
keeps its original text and the problem becomes an intake exception instead of a guess.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

BLANK = {"", "-", "--", "n/a", "na", "none", "null", "unknown", "?"}
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def blank(raw) -> bool:
    return raw is None or str(raw).strip().lower() in BLANK


def _mk(y, m, d):
    y = int(y)
    y = y + 2000 if y < 100 else y
    try:
        return date(y, int(m), int(d)).isoformat()
    except ValueError:
        return None


def parse_date(raw, order="mdy"):
    """'2025-01-19', '01/19/2025', '1/19/25', 'Jan 19, 2025', '19-Jan-2025', '2025-01-19T08:00:00-05:00', '20250119'.

    A slash date whose order can't be told (both parts <= 12) follows the client's declared `order` ('mdy' for US
    exports). With no declared order (an unknown source) such a date is a problem, never a guess.
    """
    if blank(raw):
        return None, None
    s = str(raw).strip()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$", s)
    if m:
        v = _mk(*m.groups())
        return (v, None) if v else (None, f"impossible date {s!r}")
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$", s)
    if m:
        a, b, y = m.groups()
        if int(a) > 12 and int(b) <= 12:
            order = "dmy"
        elif int(b) > 12 and int(a) <= 12:
            order = "mdy"
        elif order is None and a != b:
            return None, f"ambiguous date {s!r} (day-first or month-first?)"
        v = _mk(y, a, b) if order == "mdy" else _mk(y, b, a)
        return (v, None) if v else (None, f"impossible date {s!r}")
    m = re.match(r"^(\d{8})$", s)
    if m:
        v = _mk(s[:4], s[4:6], s[6:])
        return (v, None) if v else (None, f"impossible date {s!r}")
    m = re.match(r"^([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4})$", s) or re.match(r"^(\d{1,2})[ -]([A-Za-z]{3})[a-z]*[ -](\d{2,4})$", s)
    if m:
        g = m.groups()
        mon, d, y = (g[0], g[1], g[2]) if g[0].isalpha() else (g[1], g[0], g[2])
        if mon.lower() in MONTHS:
            v = _mk(y, MONTHS[mon.lower()], d)
            return (v, None) if v else (None, f"impossible date {s!r}")
    return None, f"unreadable date {s!r}"


def parse_datetime(raw):
    """ISO local or offset timestamp -> (iso string as given, problem). Kept as text; offsets are preserved."""
    if blank(raw):
        return None, None
    s = str(raw).strip()
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return s, None
    except ValueError:
        return None, f"unreadable time {s!r}"


def parse_money(raw, unit="dollars"):
    """Money -> integer cents. unit='cents' reads integers as cents ('12345' -> 12345); 'dollars' reads '$1,234.56',
    '(12.00)', '-12', '12.00-', '1 234,56' is refused (ambiguous). Never rounds: a third decimal is a problem."""
    if blank(raw):
        return None, None
    s = str(raw).strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.endswith("-") and not s.startswith("-"):
        neg, s = True, s[:-1]
    if s.upper().endswith((" CR", " DR")):
        neg, s = s.upper().endswith(" CR"), s[:-3]
    s = s.replace("$", "").replace("USD", "").replace(" ", "")
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    if s.startswith("+"):
        s = s[1:]
    if "," in s and "." in s and s.rfind(",") > s.rfind("."):
        return None, f"ambiguous amount {raw!r} (European format?)"
    if "," in s and "." not in s and re.search(r",\d{2}$", s):
        return None, f"ambiguous amount {raw!r} (comma decimal?)"
    s = s.replace(",", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None, f"unreadable amount {raw!r}"
    if unit == "cents":
        if d != d.to_integral_value():
            return None, f"cents column holds a fraction {raw!r}"
        c = int(d)
    else:
        c = d * 100
        if c != c.to_integral_value():
            return None, f"more than two decimals {raw!r}"
        c = int(c)
    return (-c if neg else c), None


def parse_int(raw):
    if blank(raw):
        return None, None
    try:
        return int(Decimal(str(raw).strip().replace(",", ""))), None
    except InvalidOperation:
        return None, f"not a number {raw!r}"


def parse_bool(raw):
    if blank(raw):
        return None, None
    s = str(raw).strip().lower()
    if s in ("yes", "y", "true", "t", "1", "approved", "complete", "completed"):
        return True, None
    if s in ("no", "n", "false", "f", "0", "pending", "unapproved"):
        return False, None
    return None, f"not yes/no {raw!r}"


def parse_number(raw):
    """A quantity: '14514.95584', '10', '1,250.5' -> int when whole, else float. Never money."""
    if blank(raw):
        return None, None
    s = str(raw).strip().replace(",", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None, f"unreadable number {raw!r}"
    return (int(d) if d == d.to_integral_value() else float(d)), None
