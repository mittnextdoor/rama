"""Is this ledger-layout table an opening trial balance? One rule, used by the agents' intake (ops/intake/store.py), the
workspace's file check (product/intakecheck.py) and onboarding readiness (product/onboarding.py), so they can't disagree
(docs/92 §4, 0.1).

A table of ledger lines is an opening trial balance when a person says so, or when it shows it, all of:
  - every line carries one date (the balances as of that day);
  - debits equal credits (it balances);
  - something says "opening": the object type, the source, the memo, the event id, the file's name or its title
    ("opening", "predecessor", "beginning balance", "balance forward").
A table that dates every line on one day and balances, but says nothing of opening, is a *candidate*: it's offered to a
person ("This is the opening trial balance as of …"), never assumed. The QuickBooks trial balance report reader already
marks its rows "Opening" (ops/intake/qbo_reports.py)."""
import re

MARKER = re.compile(r"(?i)\bopening\b|opening[_ -]?(tb|trial|balance)|predecessor|beginning[_ -]?balance|balance[_ -]?forward|"
                    r"\bobe\b|opening balance equity")


def examine(recs, filename="", title="", as_of=None):
    """recs: normalized gl_line records (date, account, amount; object_type, source_id, memo, event_id when the file has
    them). Returns a dict: verdict ("opening" | "candidate" | None), as_of, debits_cents, credits_cents, balanced,
    accounts, marker (what said "opening", if anything), why (when it isn't one)."""
    rows = [r for r in recs if r.get("account") is not None and r.get("amount") is not None]
    out = {"verdict": None, "as_of": None, "debits_cents": 0, "credits_cents": 0, "balanced": False, "accounts": 0, "marker": None, "why": None}
    if not rows:
        out["why"] = "it has no ledger lines with an account and an amount"
        return out
    dates = {r.get("date") for r in rows}
    out["debits_cents"] = sum(r["amount"] for r in rows if r["amount"] > 0)
    out["credits_cents"] = -sum(r["amount"] for r in rows if r["amount"] < 0)
    out["balanced"] = out["debits_cents"] == out["credits_cents"]
    out["accounts"] = len({str(r["account"]) for r in rows})
    if dates == {None} or all(r.get("_undated") for r in rows):   # no date of its own (a person may give one, as_of)
        seen = {}
        for r in rows:
            seen[str(r["account"])] = seen.get(str(r["account"]), 0) + 1
        twice = sorted(((n, a) for a, n in seen.items() if n > 1), reverse=True)
        if twice:                                          # one position lists each account once: this is several (a month each, say)
            n, a = twice[0]
            out["why"] = (f"account {a} appears {n} times with no date to tell them apart: the file holds several balances for each "
                          "account (a trial balance for each month, say), not one opening position")
            return out
    if dates == {None}:
        if as_of is None:
            out["undated"] = True
            if out["balanced"]:
                out["verdict"] = "candidate"
            else:
                out["why"] = (f"it doesn't balance: debits {out['debits_cents'] / 100:,.2f}, credits {out['credits_cents'] / 100:,.2f} "
                              f"(difference {(out['debits_cents'] - out['credits_cents']) / 100:,.2f})")
            return out
        dates = {as_of}
    if len(dates) != 1 or None in dates:
        out["why"] = f"its lines carry {len(dates - {None})} different dates" if None not in dates else "some lines have no date"
        return out
    out["as_of"] = next(iter(dates))
    for r in rows:
        if (r.get("object_type") or "").lower() == "opening":
            out["marker"] = "the object type says Opening"
            break
    if out["marker"] is None:
        for field, label in (("source_id", "source"), ("memo", "memo"), ("event_id", "event id"), ("description", "description")):
            hit = next((r.get(field) for r in rows if r.get(field) and MARKER.search(str(r.get(field)))), None)
            if hit:
                out["marker"] = f"its {label} says {str(hit)[:40]!r}"
                break
    if out["marker"] is None and MARKER.search(re.sub(r"[_.-]", " ", f"{filename} {title or ''}")):
        out["marker"] = f"its name ({filename}) says opening"
    if not out["balanced"]:
        out["why"] = (f"it doesn't balance: debits {out['debits_cents'] / 100:,.2f}, credits {out['credits_cents'] / 100:,.2f} "
                      f"(difference {(out['debits_cents'] - out['credits_cents']) / 100:,.2f})")
        return out
    out["verdict"] = "opening" if out["marker"] else "candidate"
    return out


def mark(recs):
    """Mark a recognized or designated opening trial balance's lines as the engine's opening balances. The file's own
    object type, if it had one, is kept beside it."""
    for r in recs:
        if (r.get("object_type") or "") != "Opening":
            if r.get("object_type"):
                r["object_type_original"] = r["object_type"]
            r["object_type"] = "Opening"
    return recs
