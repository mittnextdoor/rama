"""Small shared helpers: time (the same freezable clock as acq/), money parsing, hashing, months and the audit log."""
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from acq import clock

now = clock.now
iso = clock.iso


def cents(text) -> int:
    """'1,234.56' / '(12.00)' / '-12' / '$5' -> integer cents. Raises ValueError on anything else (no silent zeros)."""
    if isinstance(text, int):
        return text * 100
    s = str(text).strip().replace("$", "").replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not an amount: {text!r}") from None
    c = int((d * 100).to_integral_value())
    if d * 100 != c:
        raise ValueError(f"more than two decimals: {text!r}")
    return -c if neg else c


def money(c: int | None) -> str:
    if c is None:
        return "—"
    return f"-${abs(c) / 100:,.2f}" if c < 0 else f"${c / 100:,.2f}"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def content_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def norm_desc(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s.upper())).strip()


def fingerprint(system_id, d: str, amount: int, desc: str) -> str:
    return f"{system_id}|{d}|{amount}|{norm_desc(desc)}"


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start[:7].split("-"))
    ey, em = map(int, end[:7].split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_bounds(period: str) -> tuple[date, date]:
    y, m = map(int, period.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return first, nxt - timedelta(days=1)


def period_of(d: str) -> str:
    return d[:7]


def audit(conn, client_id, actor, action, ref=None, detail=None):
    conn.execute("INSERT INTO audit (client_id, actor, action, ref, detail, at) VALUES (?,?,?,?,?,?)",
                 (client_id, actor, action, ref, json.dumps(detail, default=str) if detail is not None else None, iso()))


def raise_exception(scope, code, severity, message, ref=None, needs="owner"):
    """Open (or keep open) one exception per (code, ref). Returns True when it's new."""
    new = scope.insert_ignore("exceptions", code=code, severity=severity, ref=ref, message=message, needs=needs, created_at=iso())
    if not new:
        row = scope.first("exceptions", "code=? AND IFNULL(ref,'')=IFNULL(?,'')", (code, ref))
        if row is None:
            return False
        if row["status"] == "resolved":                   # the condition holds again
            scope.update("exceptions", row["id"], status="open", message=message, severity=severity, resolution=None, resolved_at=None)
            return True
        if row["severity"] != severity and row["status"] == "open":   # the rules now weigh it differently: the current weight
            scope.update("exceptions", row["id"], severity=severity)
        if row["message"] != message:
            if row["status"] == "limitation":             # accepted on facts that have since changed: the owner looks again
                scope.update("exceptions", row["id"], status="open", message=message,
                             resolution=f"reopened: the facts changed after it was accepted ({row['resolution']})", resolved_at=None)
                return True
            scope.update("exceptions", row["id"], message=message)
    return bool(new)


def clear_exception(scope, code, ref=None, resolution="no longer applies", actor="system"):
    row = scope.first("exceptions", "code=? AND IFNULL(ref,'')=IFNULL(?,'') AND status='open'", (code, ref))
    if row:
        scope.update("exceptions", row["id"], status="resolved", resolution=resolution, resolved_by=actor, resolved_at=iso())
