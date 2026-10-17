"""Tie a bank or card statement to the ledger's own register, line by line, as a bookkeeper does on QuickBooks' Reconcile
screen: every statement line is found in the register (or is missing from it), and every register entry is on a statement
(or is still outstanding, or was never on one).

Matching, in order, each step only over what's still unmatched:
  0. a check: the same check number and the same amount, whatever the dates (a check clears when it's cashed);
  1. the same amount on the same day;
  2. the same amount within a few days (a check or a bill payment: within weeks, since a check clears late), the
     nearest day first, then the most words in common;
  3. a register entry equal to two to six statement lines (a deposit of several receipts), or one statement line equal
     to two to four register entries (one transfer that pays several bills), within the same few days.
Matching runs over every statement held through the month, so a line matched in an earlier month is never reused."""
import re
from datetime import date
from itertools import combinations

NEAR_DAYS = 5
CHECK_DAYS = 45
GROUP_DAYS = 3


def _days(a, b):
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _words(text):
    return {w for w in re.findall(r"[a-z]{3,}", str(text or "").lower())}


def register(lines, account):
    """The account's register: one entry per transaction (a transaction can touch the account on several lines)."""
    by = {}
    for x in lines:
        if x["account"] != account:
            continue
        e = by.setdefault(x["txn_id"], {"txn_id": x["txn_id"], "entity": x["entity"], "date": x["date"], "cents": 0,
                                        "doc_number": x.get("doc_number"), "memo": x.get("memo"), "payee": x.get("payee")})
        e["cents"] += x["cents"]
    return sorted((e for e in by.values() if e["cents"]), key=lambda e: (e["date"], str(e["txn_id"])))


def _text(e):
    return " ".join(str(e.get(k) or "") for k in ("memo", "payee", "doc_number", "description", "reference"))


CHECK_NO = re.compile(r"\b(?:check|chk|ck|cheque)\s*(?:no\.?|number|#)?\s*#?\s*(\d{3,7})\b", re.I)


def check_number(x):
    """A statement line's check number (its reference, or 'CHECK 1234' in the description), or a register entry's
    (its document number when that's all digits)."""
    if "line_id" in x:
        ref = str(x.get("reference") or "").strip()
        if ref.isdigit() and re.search(r"check|chk|\bck\b", str(x.get("description") or ""), re.I):
            return ref.lstrip("0")
        m = CHECK_NO.search(str(x.get("description") or ""))
        return m.group(1).lstrip("0") if m else None
    doc = str(x.get("doc_number") or "").strip()
    return doc.lstrip("0") if doc.isdigit() and len(doc) >= 3 else None


def _late_clearing(e):
    return e.get("entity") in ("BillPayment", "Purchase") and bool(e.get("doc_number"))


def match(stmt, reg):
    """stmt: [{line_id, date, amount, description}], reg: register(). Returns {pairs: [{lines: [...], txns: [...]}],
    statement_only: [...], register_only: [...]}."""
    left_s = sorted(stmt, key=lambda s: (s["date"], str(s["line_id"])))
    left_r = list(reg)
    pairs = []
    used_s, used_r = set(), set()

    def take(ss, rr):
        pairs.append({"lines": [s["line_id"] for s in ss], "txns": [r["txn_id"] for r in rr],
                      "amount": sum(s["amount"] for s in ss), "date": ss[0]["date"]})
        used_s.update(s["line_id"] for s in ss)
        used_r.update(r["txn_id"] for r in rr)

    by_no = {}
    for r in left_r:
        n = check_number(r)
        if n:
            by_no.setdefault((n, r["cents"]), []).append(r)
    for s in left_s:
        n = check_number(s)
        hits = [r for r in by_no.get((n, s["amount"]), []) if r["txn_id"] not in used_r] if n else []
        if len(hits) == 1:
            take([s], hits)
    for window in (0, None):
        for s in left_s:
            if s["line_id"] in used_s:
                continue
            best = None
            for r in left_r:
                if r["txn_id"] in used_r or r["cents"] != s["amount"]:
                    continue
                d = _days(s["date"], r["date"])
                limit = 0 if window == 0 else (CHECK_DAYS if _late_clearing(r) else NEAR_DAYS)
                if d > limit:
                    continue
                score = (d, -len(_words(s.get("description")) & _words(_text(r))), str(r["txn_id"]))
                if best is None or score < best[0]:
                    best = (score, r)
            if best:
                take([s], [best[1]])
    # several statement lines to one register entry (a deposit of several receipts), and the other way round
    for r in left_r:
        if r["txn_id"] in used_r:
            continue
        near = [s for s in left_s if s["line_id"] not in used_s and _days(s["date"], r["date"]) <= GROUP_DAYS
                and (s["amount"] > 0) == (r["cents"] > 0)][:14]
        hit = next((c for n in range(2, min(6, len(near)) + 1) for c in combinations(near, n) if sum(s["amount"] for s in c) == r["cents"]), None)
        if hit:
            take(list(hit), [r])
    for s in left_s:
        if s["line_id"] in used_s:
            continue
        near = [r for r in left_r if r["txn_id"] not in used_r and _days(s["date"], r["date"]) <= GROUP_DAYS
                and (s["amount"] > 0) == (r["cents"] > 0)][:12]
        hit = next((c for n in range(2, min(4, len(near)) + 1) for c in combinations(near, n) if sum(r["cents"] for r in c) == s["amount"]), None)
        if hit:
            take([s], list(hit))
    return {"pairs": pairs, "statement_only": [s for s in left_s if s["line_id"] not in used_s],
            "register_only": [r for r in left_r if r["txn_id"] not in used_r]}


def reconcile(account, statement, ledger_balance, matched, books_start=None):
    """The reconciliation in the standard form, at the statement's end date.

    statement: {start, end, opening, closing} (debit-positive), ledger_balance: the ledger's balance at the end date,
    matched: match() over every statement held for the account. Items dated after the statement's end belong to the next
    statement and are left out."""
    end = statement["end"]
    outstanding = [r for r in matched["register_only"] if r["date"] <= end and (books_start is None or r["date"] >= books_start)]
    unrecorded = [s for s in matched["statement_only"] if s["date"] <= end and (statement.get("start") or "0") <= s["date"]]
    adjusted_bank = statement["closing"] + sum(r["cents"] for r in outstanding)
    adjusted_books = ledger_balance + sum(s["amount"] for s in unrecorded)
    return {"account": account, "as_of": end, "statement_closing": statement["closing"], "statement_opening": statement.get("opening"),
            "ledger_balance": ledger_balance, "outstanding": outstanding, "unrecorded": unrecorded,
            "adjusted_bank": adjusted_bank, "adjusted_books": adjusted_books, "difference": adjusted_books - adjusted_bank,
            "matched": sum(1 for p in matched["pairs"] if p["date"] <= end and p["date"] >= (statement.get("start") or "0"))}
