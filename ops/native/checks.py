"""The close checks (docs/100 §3, step 2): the ledger, as read, against the client's evidence.

Each finding says what's wrong, shows its evidence, and carries its fix when the fix is bounded:
  create        a statement line the ledger doesn't have: a deposit, an expense or card charge, or a card refund
  transfer      the same money leaving one of the client's accounts and arriving in another
  receive       a deposit that pays an open invoice (a payment applied to it)
  pay_bill      a payment out that pays an open bill (a bill payment applied to it)
  recategorize  a transaction sitting in Uncategorized, Ask My Accountant or a suspense account
  journal       a schedule's monthly entry (an approved prepaid, accrual or depreciation schedule) not yet booked
  delete        a duplicate the statement shows was entered twice (only ever on a person's word)
A fix is `auto` when it cites its support (a rule, the ledger's own history, an approved schedule, both statements of a
transfer, the invoice or bill it pays); the agents make those themselves. Everything else waits for a person, with the
agents' suggestion.

Severity: blocker (the month can't be signed off), review (a person looks), info (in the package)."""
import os
import re
from collections import Counter, defaultdict
from itertools import combinations

from . import read, reconcile, trace

UNCATEGORIZED = re.compile(r"uncategori[sz]ed|ask my accountant|suspense|unclassified", re.I)
CLEARING = re.compile(r"undeposited|clearing", re.I)
CONTRA = re.compile(r"accumulated|allowance|contra|depreciation", re.I)
STALE_DAYS = 45
FLUX_FLOOR = 100000                     # $1,000
FLUX_SHARE = 0.30


def _f(check, key, severity, title, detail, *, account=None, amount=0, refs=(), fix=None, who="agent"):
    return {"key": f"{check}:{key}", "check": check, "severity": severity, "title": title, "detail": detail, "account": account,
            "amount_cents": int(amount or 0), "refs": list(refs), "fix": fix, "who": who}


def _m(c):
    """An amount as an accountant writes it: 1,234.50, and (1,234.50) when negative."""
    return f"({abs(c) / 100:,.2f})" if c < 0 else f"{c / 100:,.2f}"


def _d(day):
    return f"{day[5:7]}/{day[8:10]}/{day[:4]}" if day and len(day) >= 10 else (day or "")


def _key(text):
    """The words that identify who a bank line is with: 'ACH PMT HOME DEPOT 4471' -> 'home depot'."""
    ws = [w for w in re.findall(r"[a-z]{2,}", str(text or "").lower()) if w not in {"ach", "pmt", "pos", "dbt", "debit", "credit", "card",
                                                                                     "purchase", "payment", "the", "inc", "llc", "web", "ppd", "ccd"}]
    seen = []
    for w in ws:
        if w not in seen:
            seen.append(w)
    return " ".join(seen[:3])


def _v1():
    """BOB_V1=1 replays Bob's v1 behaviour (bob/eval/CHANGES.md): the baseline batch can be reproduced against the same inputs."""
    return os.environ.get("BOB_V1") == "1"


def _twice(lines, amount):
    """The statement lines of one date, amount and description that appear more than once, when their amount is the one
    the statement is off by (an import run twice), else []."""
    by = defaultdict(list)
    for ln in lines:
        by[(ln["date"], ln["amount"], str(ln.get("description") or "").strip().lower())].append(ln)
    for (_d_, amt, _t), xs in by.items():
        if len(xs) > 1 and amt * (len(xs) - 1) == amount:
            return xs
    return []


# ------------------------------------------------------------------ what the ledger itself teaches
def history(snap, recons_input):
    """{description key: Counter(account)} from statement lines already matched to the ledger: the account the other
    side of each matched transaction went to. This is how the client's books were kept, cited by transaction id."""
    t = read.types(snap)
    by_txn = defaultdict(list)
    for x in snap["lines"]:
        by_txn[x["txn_id"]].append(x)
    out = defaultdict(Counter)
    cites = defaultdict(list)
    for bank, (stmt_lines, matched) in recons_input.items():
        desc = {s["line_id"]: s.get("description") for s in stmt_lines}
        for p in matched["pairs"]:
            if len(p["lines"]) != 1 or len(p["txns"]) != 1:
                continue
            others = [x["account"] for x in by_txn[p["txns"][0]] if x["account"] != bank and t.get(x["account"]) not in ("Bank", "Credit Card")
                      and not UNCATEGORIZED.search(x["account"])]      # a held line teaches nothing about where lines like it go
            if len(set(others)) == 1:
                k = _key(desc.get(p["lines"][0]))
                if k:
                    out[k][others[0]] += 1
                    cites[(k, others[0])].append(p["txns"][0])
    return out, cites


def classify(line, hist, cites, rules, chart_names):
    """(account, citations, why) for a statement line, or (None, [], why). Rules first (a person's word), then the
    ledger's own history when it's consistent (at least two earlier lines, all to one account)."""
    text = str(line.get("description") or "")
    for r in rules:
        try:
            hit = re.search(r["pattern"], text, re.I) if r.get("regex") else r["pattern"].lower() in text.lower()
        except re.error:
            hit = False
        if hit and r["account"] in chart_names and (r.get("sign") in (None, 0) or (r["sign"] > 0) == (line["amount"] > 0)):
            return r["account"], [f"rule:{r['id']}"], f"the rule \"{r['pattern']}\" says {r['account']}"
    k = _key(text)
    ws = k.split()
    # the key as it is, then the vendor's name without the extra words this month's description carries ("HOME DEPOT RETURN
    # 4471" after months of "POS DBT HOME DEPOT 4471", a refund or an online order): never fewer than two words
    keys = [k] + ([" ".join(ws[:n]) for n in range(len(ws) - 1, 1, -1)] if not _v1() else [])
    for key in keys:
        seen = hist.get(key) or Counter()
        if len(seen) == 1:
            acct, n = next(iter(seen.items()))
            if n >= 2 and acct in chart_names:
                ids = cites[(key, acct)][:5]
                how = f"the ledger booked {n} earlier \"{key}\" lines to {acct}" + (f" (this line reads \"{k}\")" if key != k else "")
                return acct, [f"ledger:{i}" for i in ids], how
        if len(seen) > 1:
            return None, [], f"earlier \"{key}\" lines went to {', '.join(sorted(seen))}: a person decides"
    return None, [], "nothing in the rules or the ledger's history says what this is"


# ------------------------------------------------------------------ the checks
def owner_accounts(t):
    """(draw, contribution): the owner's equity accounts for personal money out and in, by name; the owner's equity
    account itself when there's no separate one."""
    eq = [a for a, typ in t.items() if typ == "Equity" and not re.search(r"retained|opening balance", a, re.I)]
    draw = next((a for a in eq if re.search(r"draw|distribution", a, re.I)), None)
    contrib = next((a for a in eq if re.search(r"contribution|investment|capital|paid.in", a, re.I)), None)
    base = next((a for a in eq if re.search(r"owner|member|equity", a, re.I)), eq[0] if eq else None)
    return draw or base, contrib or base


PERSONAL = "__personal__"                                 # a person's instruction: lines like this are personal (left out)


TAG = "NHB: statement line"                                # the note on every entry the agents record from a statement line


def run(snap, ev, *, account_map=None, excused=(), books_start=None, rules=(), schedules=(), continuity=None, personal=(), offbook=(),
        auto_add=()):
    """ev: {statements, lines, client_chart, lenders} (evidence.py). Returns {findings, recons, unmapped}.

    personal: the client's QuickBooks accounts that are personal accounts the business runs through (each line is
    business, or the owner's draw or contribution); offbook: statement accounts that are personal and not in QuickBooks
    at all (only their business lines are recorded, as paid or received by the owner)."""
    t = read.types(snap)
    names = set(t)
    personal, offbook = set(personal), {str(r) for r in offbook}
    draw, contrib = owner_accounts(t)
    off_findings = _offbook(snap, ev, offbook, t, rules, draw, contrib)
    ev = dict(ev, statements=[s for s in ev["statements"] if str(s["ref"]) not in offbook],
              lines={r: ls for r, ls in ev["lines"].items() if str(r) not in offbook})
    findings, recons = [], []
    stmts_by = defaultdict(list)
    unmapped = set()
    account_map = dict(account_map or {})
    refs = {s["ref"] for s in ev["statements"]} | {r for r in ev["lines"] if r}
    for ref in sorted(refs):
        if _resolve(ref, snap, account_map, ev) is None:
            got = infer_account(ev["lines"].get(ref) or [], snap, taken=set(account_map.values()))
            if got:
                account_map[ref] = got["account"]
                findings.append(_f("statement_mapped", ref, "info", f"Statement account {ref} is QuickBooks {got['account']}",
                                   f"{got['matched']} of its {got['lines']} lines are in {got['account']}'s register on the same day for the same "
                                   f"amount, and no other account comes close. Change it in the client's account map if that's wrong.",
                                   account=got["account"]))
    for s in ev["statements"]:
        acct = _resolve(s["ref"], snap, account_map, ev)
        if acct is None:
            unmapped.add(s["ref"])
            continue
        stmts_by[acct].append(s)
    lines_by = defaultdict(list)
    for ref, ls in ev["lines"].items():
        acct = _resolve(ref, snap, account_map, ev)
        if acct is None:
            if ref:
                unmapped.add(ref)
            continue
        lines_by[acct] += ls
    for ref in sorted(unmapped):
        findings.append(_f("statement_unmapped", ref, "blocker", f"Which QuickBooks account is statement account {ref}?",
                           f"The client's statements name account {ref}, and no QuickBooks bank or card account matches it by the "
                           "account map, number, name, last four digits or its lines. Choose the account.",
                           fix={"kind": "map_account", "ref": ref, "to": None, "auto": False}, who="reviewer"))
    # a statement file that carries one line twice (an import run twice) is off from its own closing balance by exactly
    # that line: the second copy is no transaction, so it's set aside before anything is matched, and said (below)
    twice_by = {}
    if not _v1():
        for acct, ss in stmts_by.items():
            for s in ss:
                if s.get("opening") is None:
                    continue
                lines_in = [ln for ln in lines_by[acct] if (s["start"] or "0") <= ln["date"] <= s["end"]]
                gap = s["closing"] - s["opening"] - sum(ln["amount"] for ln in lines_in)
                twice = _twice(lines_in, -gap) if gap else []
                if twice:
                    extra = {x["line_id"] for x in twice[1:]}
                    lines_by[acct] = [ln for ln in lines_by[acct] if ln["line_id"] not in extra]
                    twice_by[(acct, s["end"])] = twice
    # register and statements, matched over everything held through the month
    matched_by, recon_in = {}, {}
    period_end = snap["end"]
    for acct in sorted(set(stmts_by) | set(lines_by)):
        first = min([s["start"] or s["end"] for s in stmts_by[acct]] + [ln["date"] for ln in lines_by[acct]] or [snap["start"]])
        start = max(first, books_start or first)
        stmt_lines = [ln for ln in lines_by[acct] if start <= ln["date"] <= period_end]
        reg = [r for r in reconcile.register(snap["lines"], acct) if r["date"] >= start]
        with trace.step(f"match_statement {acct}", "tool", {"account": acct, "statement_lines": len(stmt_lines), "register_entries": len(reg), "from": start}) as st:
            m = reconcile.match(stmt_lines, reg)
            st.out({"pairs": len(m["pairs"]), "statement_only": len(m["statement_only"]), "register_only": len(m["register_only"])})
        matched_by[acct], recon_in[acct] = (m, start), (stmt_lines, m)
    hist, cites = history(snap, recon_in)
    open_inv, open_bill = snap.get("open_invoices") or [], snap.get("open_bills") or []
    per = {}
    for acct in sorted(matched_by):
        m, start = matched_by[acct]
        month_stmts = [s for s in stmts_by[acct] if s["end"][:7] == snap["period"]]
        if not month_stmts:
            if acct not in excused:
                findings.append(_f("statement_missing", acct, "blocker", f"No {snap['period']} statement for {acct}",
                                   f"{acct} can't be proved without the month's statement. Ask the client for it, or record that the "
                                   "account has no statement.", account=acct, who="client"))
            continue
        s = month_stmts[-1]
        lines_in = [ln for ln in lines_by[acct] if (s["start"] or "0") <= ln["date"] <= s["end"]]
        twice = twice_by.get((acct, s["end"]))
        if twice:
            amt = twice[0]["amount"] * (len(twice) - 1)
            findings.append(_f("statement_incomplete", f"{acct}:{s['end']}", "blocker", f"{acct}: the statement file has a line twice",
                               f"The file's lines add up to {_m(amt)} more than the statement's closing balance {_m(s['closing'])}, and "
                               f"\"{twice[0].get('description') or 'a line'}\" on {_d(twice[0]['date'])} for {_m(abs(twice[0]['amount']))} appears "
                               f"{len(twice)} times in it (lines {', '.join(x['line_id'] for x in twice)}): the statement was imported twice. The extra "
                               "copy is no transaction and is set aside; the account is reconciled on the rest. Ask the client for the statement once.",
                               account=acct, amount=amt, refs=[f"line:{x['line_id']}" for x in twice], who="client"))
        elif s.get("opening") is not None and lines_in and s["opening"] + sum(ln["amount"] for ln in lines_in) != s["closing"]:
            findings.append(_f("statement_incomplete", f"{acct}:{s['end']}", "blocker", f"{acct}: the statement's lines don't add up",
                               f"Opening {_m(s['opening'])} plus the lines ({_m(sum(ln['amount'] for ln in lines_in))}) isn't the closing "
                               f"balance {_m(s['closing'])}: some lines are missing from the file. Ask the client for the full statement.",
                               account=acct, amount=s["closing"] - s["opening"] - sum(ln["amount"] for ln in lines_in), who="client"))
        bal = read.balance_at(snap, acct, s["end"])
        with trace.step(f"reconcile {acct}", "tool", {"account": acct, "statement_closing": s["closing"], "ledger_balance": bal, "as_of": s["end"]}) as st:
            rec = reconcile.reconcile(acct, s, bal, m, books_start=start)
            st.out({"difference": rec["difference"], "outstanding": len(rec["outstanding"]), "unrecorded": len(rec["unrecorded"]),
                    "adjusted_bank": rec["adjusted_bank"], "adjusted_books": rec["adjusted_books"]})
        rec["statement_record"] = s.get("record")
        rec["kind"] = s["kind"]
        recons.append(rec)
        per[acct] = (rec, s, m, bal)
    # what a bookkeeper matches on the Reconcile screen once the entry is put right: a date a few days off, the wrong
    # bank account, a processor's fee withheld, payments waiting in Undeposited Funds, a few cents or swapped digits
    with trace.step("rematch_client_entries", "tool", {"accounts": sorted(per)}) as st:
        fixed, used_lines, used_txns = _rematch(per, snap, t)
        st.out({"fixes": [f["fix"]["kind"] for f in fixed if f.get("fix")]})
    findings += fixed
    taken = set(used_lines)
    for acct in sorted(per):
        rec, s, m, bal = per[acct]
        # statement lines the ledger doesn't have
        for ln in rec["unrecorded"]:
            if ln["line_id"] in taken:
                continue
            f = _unrecorded(ln, acct, snap, t, names, matched_by, lines_by, hist, cites, rules, open_inv, open_bill, taken)
            if acct in auto_add and f["fix"] and f["fix"].get("auto"):   # QuickBooks' bank rules add this account's lines themselves
                f["fix"] = dict(f["fix"], auto=False, why=(f["fix"].get("why") or "") + "; QuickBooks' bank rules add this account's lines by "
                                "themselves, so it may arrive on its own: a person confirms before it's recorded")
                f["who"] = "reviewer"
            if acct in personal and f["fix"] and f["fix"]["kind"] == "create":
                owner = draw if ln["amount"] < 0 else contrib
                f["fix"]["owner"] = owner                  # a personal account: its first choice is the owner's own
                if not f["fix"].get("to"):
                    f["detail"] = (f"{acct} is a personal account the business runs through. Personal ({owner}), or a business account? "
                                   + f["detail"])
            findings.append(f)
        # ledger entries never on a statement
        for r in rec["outstanding"]:
            if r["txn_id"] in used_txns:
                continue
            age = (_date(s["end"]) - _date(r["date"])).days
            twin = next((p for p in m["pairs"] if p["amount"] == r["cents"] and abs((_date(p["date"]) - _date(r["date"])).days) <= 3), None)
            if twin:
                # the bank feed added a line the agents had already recorded (or the other way round): the agents' own entry
                # is the one to remove, since the feed's is the one QuickBooks keeps matched to the bank
                tagged = lambda x: TAG in str(x.get("memo") or "") + str(x.get("line_memo") or "")      # noqa: E731
                twins = [x for x in snap["lines"] if x["account"] == acct and str(x["txn_id"]) in {str(t) for t in twin["txns"]}]
                mine = any(tagged(x) for x in snap["lines"] if str(x["txn_id"]) == str(r["txn_id"]))
                o = ({"entity": r["entity"], "txn_id": r["txn_id"]} if mine and not any(tagged(x) for x in twins) else
                     next((x for x in twins if tagged(x)), None) if not mine else None)
                if o is not None:
                    feed = twins[0] if mine else r
                    findings.append(_f("possible_duplicate", f"{acct}:{r['txn_id']}", "blocker",
                                       f"{acct}: {_m(abs(r['cents']))} on {_d(r['date'])} is in QuickBooks twice (the bank feed and the agents)",
                                       f"The statement shows it once. QuickBooks has the bank feed's {feed['entity']} {feed['txn_id']} and the agents' own "
                                       f"{o['entity']} {o['txn_id']}. The agents' copy is removed; the feed's stays matched to the bank.",
                                       account=acct, amount=r["cents"], refs=[f"ledger:{r['txn_id']}", f"ledger:{o['txn_id']}"],
                                       fix={"kind": "delete", "entity": o["entity"], "txn_id": o["txn_id"], "auto": False,
                                            "why": "the agents' own entry, duplicated by the bank feed"}, who="reviewer"))
                    continue
                findings.append(_f("possible_duplicate", f"{acct}:{r['txn_id']}", "blocker", f"{acct}: {_m(abs(r['cents']))} on {_d(r['date'])} looks entered twice",
                                   f"The statement shows this amount once, and the ledger has it twice: QuickBooks {r['entity']} {r['txn_id']} "
                                   f"and the one matched to statement line {', '.join(twin['lines'])}. Delete the duplicate if that's right.",
                                   account=acct, amount=r["cents"], refs=[f"ledger:{r['txn_id']}"] + [f"line:{x}" for x in twin["lines"]],
                                   fix={"kind": "delete", "entity": r["entity"], "txn_id": r["txn_id"], "auto": False}, who="reviewer"))
            elif age > STALE_DAYS:
                findings.append(_f("not_on_statement", f"{acct}:{r['txn_id']}", "review", f"{acct}: {_m(r['cents'])} from {_d(r['date'])} isn't on any statement",
                                   f"QuickBooks {r['entity']} {r['txn_id']} ({r.get('payee') or r.get('memo') or 'no description'}) has been in the "
                                   f"ledger {age} days and no statement shows it. It may be a stale check to void, or an entry that never happened.",
                                   account=acct, amount=r["cents"], refs=[f"ledger:{r['txn_id']}"], who="reviewer"))
        unexplained = rec["difference"]
        if unexplained:
            findings.append(_f("reconciliation_difference", f"{acct}:{s['end']}", "blocker", f"{acct} doesn't reconcile by {_m(unexplained)}",
                               f"At {s['end']}: the ledger {_m(bal)}, plus the statement lines not in it, is {_m(rec['adjusted_books'])}; the "
                               f"statement {_m(s['closing'])}, plus the ledger's items not yet on it, is {_m(rec['adjusted_bank'])}. Nothing "
                               "listed explains the difference: an opening balance, a changed amount, or an entry dated outside the statement.",
                               account=acct, amount=unexplained, who="reviewer"))
    said = {}
    for acct, (stmt_lines, m) in recon_in.items():
        desc = {x["line_id"]: x.get("description") for x in stmt_lines}
        for p in m["pairs"]:
            for tid in p["txns"]:
                said[tid] = " ".join(str(desc.get(i) or "") for i in p["lines"])
    findings += off_findings
    with trace.step("check_ledger", "tool", {"period": snap["period"], "accounts": len(t), "schedules": len(schedules or ())}) as st:
        n0 = len(findings)
        findings += _patterns(snap, t, said, rules, personal, draw, contrib, {f["refs"][0] for f in findings if f["refs"]})
        findings += _payroll(snap, t, ev.get("payroll") or [])
        findings += _uncategorized(snap, t, hist, cites, rules, names, said)
        findings += _clearing(snap, t)
        findings += _signs(snap, t)
        findings += _receivables(snap, t)
        findings += _lenders(snap, t, ev.get("lenders") or [], account_map)
        findings += _schedules(snap, t, schedules)
        findings += _continuity(continuity, snap)
        findings += _flux(snap, t)
        st.out({"findings": sorted({f["check"] for f in findings[n0:]}), "count": len(findings) - n0})
    excused_with_activity = [a for a in excused if snap["tb"].get(a)]
    for a in excused_with_activity:
        findings.append(_f("no_statement_account", a, "info", f"{a} has no statement (recorded by a person)",
                           f"{a} holds {_m(snap['tb'][a])}; a person recorded that it has no statement, so it isn't reconciled.", account=a))
    # every balance-sheet account's workpaper: opening + activity = closing, and what supports the closing balance
    from . import workpapers
    with trace.step("build_workpapers", "tool", {"accounts": len([a for a in t if t[a] not in read.PL]), "reconciliations": len(recons)}) as st:
        papers, more = workpapers.build(snap, t, recons, ev, schedules, findings, excused=excused)
        st.out({"papers": len(papers), "status": {k: sum(1 for p in papers if p["status"] == k) for k in ("tied", "exception", "unsupported", "excused", "info")},
                "new_findings": [f["check"] for f in more]})
    findings += more
    return {"findings": findings, "recons": recons, "unmapped": sorted(unmapped), "workpapers": papers}


def infer_account(stmt_lines, snap, taken=()):
    """The bank or card account whose register holds most of a statement's lines (same day, same amount): at least three,
    and at least half of them, and clearly more than any other account. Otherwise None: a person says."""
    if not stmt_lines:
        return None
    t = read.types(snap)
    keys = Counter((ln["date"], ln["amount"]) for ln in stmt_lines)
    score = {}
    for acct in (a for a, typ in t.items() if typ in ("Bank", "Credit Card") and a not in taken):
        have = Counter((r["date"], r["cents"]) for r in reconcile.register(snap["lines"], acct))
        score[acct] = sum(min(n, have[k]) for k, n in keys.items())
    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    if not ranked:
        return None
    best, n = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if n >= 3 and n * 2 >= len(stmt_lines) and n >= 2 * second + 1:
        return {"account": best, "matched": n, "lines": len(stmt_lines)}
    return None


def _offbook(snap, ev, offbook, t, rules, draw, contrib):
    """A personal account that isn't in QuickBooks: each of the month's lines is recorded as paid (or received) by the owner
    when it's business, or left out when it's personal. A line already recorded carries its line id in the entry's memo."""
    out = []
    if not offbook:
        return out
    recorded = " ".join(str(x.get(k) or "") for x in snap["lines"] for k in ("memo", "line_memo"))
    hist, cites = history(snap, {})
    names = {a for a, typ in t.items() if typ not in ("Bank", "Credit Card")}
    for ref in sorted(offbook):
        for ln in ev["lines"].get(ref) or []:
            if not (snap["start"] <= ln["date"] <= snap["end"]) or f"statement line {ln['line_id']}" in recorded:
                continue
            text = str(ln.get("description") or "")
            said = next((r for r in rules if r["account"] == PERSONAL and (r["pattern"].lower() in text.lower())), None)
            what = f"{ref} (personal): {_d(ln['date'])} {text}, {_m(abs(ln['amount']))} {'in' if ln['amount'] > 0 else 'out'}"
            if said:
                out.append(_f("offbook_line", ln["line_id"], "info", f"{what}: personal, left out", f"Your instruction \"{said['pattern']}\" says it's personal.",
                              account=None, amount=ln["amount"], refs=[f"line:{ln['line_id']}", f"rule:{said['id']}"]))
                continue
            acct, cs, why = classify(ln, hist, cites, [r for r in rules if r["account"] != PERSONAL], names)
            owner = contrib if ln["amount"] < 0 else draw
            fix = {"kind": "owner_paid", "line": ln, "account": None, "to": acct, "owner": owner, "auto": bool(acct and cs),
                   "citations": [f"line:{ln['line_id']}"] + cs, "why": why}
            out.append(_f("offbook_line", ln["line_id"], "blocker", f"{what}: business or personal?",
                          (f"The agents will record it to {acct}, paid by the owner ({owner}): {why}." if acct else
                           f"A personal account that isn't in QuickBooks: a business line is recorded as paid by the owner ({owner}); a personal "
                           "one is left out. " + why + "."), account=None, amount=ln["amount"], refs=[f"line:{ln['line_id']}"], fix=fix,
                          who="agent" if fix["auto"] else "reviewer"))
    return out


def _date(d):
    from datetime import date
    return date.fromisoformat(d)


def _resolve(ref, snap, account_map, ev):
    from .evidence import account_for
    return account_for(ref, snap["chart"], account_map, ev.get("client_chart"))


DRIFT_DAYS = 10                                           # an entry dated this far from its statement line is the same one, misdated
FEE_SHARE, FEE_FLOOR = 0.04, 100                          # a processor withholds at most about 4% plus a dollar
UF_DAYS = 31                                              # payments wait in Undeposited Funds at most a month before the deposit
FEE_WORDS = re.compile(r"merchant|processing|card fee|stripe|square|paypal|clover|toast|shopify", re.I)


def fee_account(t):
    """The expense account processors' fees go to, by name: a merchant or processing fees account first, else bank fees."""
    exp = [a for a, typ in sorted(t.items()) if typ in ("Expense", "Other Expense", "Cost of Goods Sold")]
    return (next((a for a in exp if FEE_WORDS.search(a)), None) or
            next((a for a in exp if re.search(r"bank (service )?(fee|charge)|service charge", a, re.I)), None))


def _fee_ok(gross, net):
    return 0 < gross - net <= FEE_SHARE * gross + FEE_FLOOR


def _transposed(a, b):
    a, b = str(abs(a)), str(abs(b))
    return a != b and sorted(a) == sorted(b) and (int(a) - int(b)) % 9 == 0


def _rematch(per, snap, t):
    """Statement lines and ledger entries that are the same money but don't match as they stand, each with the change to
    the entry that makes them match (decision 6: the client's entry is put right, never a second one made):
      date_drift        the same amount and words, up to ten days apart: the entry's date moves to the statement's
      wrong_account     a line missing from one account, its entry in another account whose statement doesn't show it
      undeposited       payments waiting in Undeposited Funds that add up to a bank deposit: a deposit that takes them
      processor_fee     a deposit a few percent below the sale or payment recorded: the fee withheld is recorded
      amount_difference the same entry a few cents (or two swapped digits) off: the amount is corrected, on a person's word
    Returns (findings, statement line ids used, ledger transaction ids used)."""
    out, used_s, used_r, used_u = [], set(), set(), set()
    closed = snap.get("close_date") or ""
    fee_to = fee_account(t)
    lines_of = defaultdict(list)
    for x in snap["lines"]:
        lines_of[str(x["txn_id"])].append(x)
    U = {a: rec["unrecorded"] for a, (rec, *_) in per.items()}
    O = {a: rec["outstanding"] for a, (rec, *_) in per.items()}

    def free_s(a):
        return [s for s in U[a] if s["line_id"] not in used_s]

    def free_r(a):
        return [r for r in O[a] if r["txn_id"] not in used_r]

    def words(s, r):
        return len(reconcile._words(s.get("description")) & reconcile._words(reconcile._text(r)))

    def add(check, a, s, r, title, detail, fix, severity="blocker"):
        used_s.add(s["line_id"])
        if r is not None:
            used_r.add(r["txn_id"])
        refs = [f"line:{s['line_id']}"] + ([f"ledger:{r['txn_id']}"] if r is not None else [])
        if fix:
            fix = {"line": s, **fix, "citations": refs + list(fix.get("citations") or [])}
        out.append(_f(check, f"{a}:{s['line_id']}", severity, title, detail, account=a, amount=s["amount"], refs=refs, fix=fix,
                      who="agent" if fix and fix.get("auto") else "reviewer"))

    def is_closed(*days):
        return bool(closed) and any(d <= closed for d in days)
    # the same amount, a few more days apart than the matcher allows, with the same words (or check number)
    for a in sorted(per):
        for s in free_s(a):
            near = [r for r in free_r(a) if r["cents"] == s["amount"] and reconcile.NEAR_DAYS < reconcile._days(s["date"], r["date"]) <= DRIFT_DAYS
                    and (words(s, r) or (reconcile.check_number(s) and reconcile.check_number(s) == reconcile.check_number(r)))]
            if not near:
                continue
            r = min(near, key=lambda r: (reconcile._days(s["date"], r["date"]), -words(s, r)))
            title = f"{a}: {_m(abs(s['amount']))} is dated {_d(r['date'])} in QuickBooks and {_d(s['date'])} on the statement"
            if is_closed(s["date"], r["date"]):
                add("date_drift", a, s, r, title, f"QuickBooks {r['entity']} {r['txn_id']} is the statement's line, misdated; the books are closed "
                    f"through {_d(closed)}, so the date can't be changed without reopening that month.", None, severity="review")
                continue
            add("date_drift", a, s, r, title,
                f"QuickBooks {r['entity']} {r['txn_id']} ({r.get('payee') or r.get('memo') or 'no description'}) is the same amount with the same "
                f"words, {reconcile._days(s['date'], r['date'])} days from the statement's date. The agents move its date to {_d(s['date'])}.",
                {"kind": "redate", "entity": r["entity"], "txn_id": r["txn_id"], "account": a, "date": s["date"], "from_date": r["date"],
                 "auto": len(near) == 1 and s["date"][:7] == r["date"][:7],
                 "why": f"the same amount and words, {reconcile._days(s['date'], r['date'])} days apart: the entry was misdated"})
    # recorded in the wrong bank or card account: that account's statement doesn't show it, this one's does
    movable = {"Purchase", "Deposit", "Payment", "SalesReceipt", "BillPayment"}
    for a in sorted(per):
        for s in free_s(a):
            near = [(b, r) for b in sorted(per) if b != a for r in free_r(b) if r["cents"] == s["amount"] and r["entity"] in movable
                    and reconcile._days(s["date"], r["date"]) <= reconcile.NEAR_DAYS
                    and not (t.get(a) == "Credit Card" and r["entity"] in ("Deposit", "Payment", "SalesReceipt"))]
            if not near:
                continue
            b, r = min(near, key=lambda br: (reconcile._days(s["date"], br[1]["date"]), -words(s, br[1])))
            title = f"{_m(abs(s['amount']))} on {_d(s['date'])} is on the {a} statement but recorded in {b}"
            if is_closed(r["date"]):
                add("wrong_account", a, s, r, title, f"QuickBooks {r['entity']} {r['txn_id']} is in {b}, whose statement doesn't show it; the books "
                    f"are closed through {_d(closed)}, so it can't be moved without reopening that month.", None, severity="review")
                continue
            add("wrong_account", a, s, r, title,
                f"QuickBooks {r['entity']} {r['txn_id']} ({r.get('payee') or r.get('memo') or 'no description'}) is in {b}, and {b}'s statement doesn't "
                f"show it; the {a} statement does. The agents move it to {a}.",
                {"kind": "rebank", "entity": r["entity"], "txn_id": r["txn_id"], "from": b, "to": a, "account": a, "auto": len(near) == 1,
                 "why": f"the {a} statement shows it and {b}'s doesn't"})
    # a card payment from the bank booked as an expense: the card's statement shows the payment arriving
    pl_types = ("Expense", "Other Expense", "Cost of Goods Sold")
    for a in sorted(per):
        if t.get(a) != "Credit Card":
            continue
        for s in free_s(a):
            if s["amount"] <= 0:
                continue
            near = []
            for tid, xs in lines_of.items():
                bank = [x for x in xs if t.get(x["account"]) == "Bank"]
                rest = [x for x in xs if t.get(x["account"]) != "Bank"]
                if (len(bank) == 1 and bank[0]["entity"] == "Purchase" and bank[0]["cents"] == -s["amount"] and rest
                        and all(t.get(x["account"]) in pl_types for x in rest) and reconcile._days(s["date"], bank[0]["date"]) <= reconcile.NEAR_DAYS
                        and tid not in used_r):
                    near.append(bank[0])
            if len(near) != 1:
                continue
            x = near[0]
            used_r.add(x["txn_id"])
            wrong = sorted({y["account"] for y in lines_of[str(x["txn_id"])] if y["account"] != x["account"]})
            add("card_payment_expensed", a, s, None, f"The {_m(s['amount'])} payment to {a} on {_d(s['date'])} is booked as an expense",
                f"QuickBooks Purchase {x['txn_id']} pays {_m(s['amount'])} from {x['account']} to {', '.join(wrong)}; the {a} statement shows it arriving "
                f"as a payment. A card payment moves money between the client's own accounts: the agents replace it with a transfer from "
                f"{x['account']} to {a}.",
                {"kind": "replace", "delete": {"entity": "Purchase", "txn_id": x["txn_id"]},
                 "create": {"kind": "transfer", "from": x["account"], "to": a, "amount": s["amount"], "date": x["date"],
                            "citations": [f"line:{s['line_id']}", f"ledger:{x['txn_id']}"]},
                 "account": x["account"], "to": a, "auto": False, "citations": [f"ledger:{x['txn_id']}"],
                 "why": f"the {a} statement shows the payment arriving; an expense of {', '.join(wrong)} isn't what it was"})
    # Undeposited Funds: payments waiting there that add up to a bank deposit (exactly, then with a fee withheld)
    waiting = [u for u in snap.get("undeposited") or []]

    def uf_combos(s, exact):
        pool = sorted((u for u in waiting if (u["entity"], u["id"]) not in used_u and u["date"] <= s["date"]
                       and reconcile._days(s["date"], u["date"]) <= UF_DAYS), key=lambda u: (u["date"], u["id"]), reverse=True)[:14]
        hits = []
        for n in range(1, min(6, len(pool)) + 1):
            for c in combinations(pool, n):
                total = sum(u["amount"] for u in c)
                if total == s["amount"] if exact else _fee_ok(total, s["amount"]):
                    hits.append(c)
                    if len(hits) > 3:
                        return hits
        return hits

    def deposit_from_uf(exact):
        for a in sorted(per):
            if t.get(a) != "Bank":
                continue
            for s in free_s(a):
                if s["amount"] <= 0:
                    continue
                hits = uf_combos(s, exact)
                if not hits:
                    continue
                best = min(hits, key=lambda c: (sum(u["amount"] for u in c) - s["amount"], len(c)))
                fee = sum(u["amount"] for u in best) - s["amount"]
                same = [c for c in hits if sum(u["amount"] for u in c) - s["amount"] == fee]
                used_u.update((u["entity"], u["id"]) for u in best)
                who = "; ".join(f"{u['name'] or u['entity']} {_m(u['amount'])} ({_d(u['date'])})" for u in best)
                add("undeposited", a, s, None,
                    f"{a}: the {_m(s['amount'])} deposit on {_d(s['date'])} is {len(best)} payment{'s' if len(best) > 1 else ''} waiting in Undeposited Funds",
                    f"Waiting in Undeposited Funds: {who}." + (f" Together they're {_m(fee)} more than the deposit: the processor's fee, recorded to "
                                                              f"{fee_to or 'a fees account you choose'}." if fee else "")
                    + " The agents make the deposit in QuickBooks that takes them.",
                    {"kind": "deposit", "account": a, "date": s["date"], "fee": fee, "fee_account": fee_to if fee else None,
                     "items": [{"entity": u["entity"], "id": u["id"], "amount": u["amount"], "name": u["name"], "date": u["date"]} for u in best],
                     "auto": len(same) == 1 and (not fee or bool(fee_to)),
                     "citations": [f"ledger:{u['id']}" for u in best],
                     "why": ("the payments waiting in Undeposited Funds add up to the deposit" if not fee else
                             f"the payments waiting add up to the deposit plus a {_m(fee)} fee")})
    deposit_from_uf(True)
    # a deposit below the sale or payment recorded for it: the processor kept its fee
    for a in sorted(per):
        for s in free_s(a):
            if s["amount"] <= 0:
                continue
            near = [r for r in free_r(a) if r["entity"] in ("Deposit", "Payment", "SalesReceipt") and r["cents"] > s["amount"]
                    and _fee_ok(r["cents"], s["amount"]) and reconcile._days(s["date"], r["date"]) <= (reconcile.NEAR_DAYS if r["entity"] == "Deposit" else 3)]
            if not near:
                continue
            r = min(near, key=lambda r: (r["cents"] - s["amount"], reconcile._days(s["date"], r["date"])))
            fee = r["cents"] - s["amount"]
            add("processor_fee", a, s, r, f"{a}: {_m(s['amount'])} arrived for the {_m(r['cents'])} recorded on {_d(r['date'])}",
                f"QuickBooks {r['entity']} {r['txn_id']} ({r.get('payee') or r.get('memo') or 'no description'}) has {_m(r['cents'])}; the bank received "
                f"{_m(s['amount'])}. The {_m(fee)} ({100 * fee / r['cents']:.1f}%) is the processor's fee, recorded to {fee_to or 'a fees account you choose'}.",
                {"kind": "fee", "entity": r["entity"], "txn_id": r["txn_id"], "account": a, "date": r["date"], "fee": fee, "fee_account": fee_to,
                 "auto": len(near) == 1 and bool(fee_to), "why": f"the deposit is {_m(fee)} below what was recorded: a processor's fee"})
    deposit_from_uf(False)
    # a few cents off, or two digits swapped: the amount is corrected, only on a person's word
    for a in sorted(per):
        for s in free_s(a):
            near = [r for r in free_r(a) if (r["cents"] > 0) == (s["amount"] > 0) and r["cents"] != s["amount"]
                    and (abs(r["cents"] - s["amount"]) < 100 or _transposed(r["cents"], s["amount"]))
                    and (reconcile._days(s["date"], r["date"]) <= reconcile.NEAR_DAYS
                         or (reconcile.check_number(s) and reconcile.check_number(s) == reconcile.check_number(r)))]
            if not near:
                continue
            r = min(near, key=lambda r: (abs(r["cents"] - s["amount"]), reconcile._days(s["date"], r["date"])))
            others = [x for x in lines_of[str(r["txn_id"])] if x["account"] != a]
            simple = r["entity"] in ("Purchase", "Deposit", "Transfer") and len(others) == 1
            how = "two digits swapped" if _transposed(r["cents"], s["amount"]) else f"{_m(abs(r['cents'] - s['amount']))} off"
            title = f"{a}: {_m(abs(r['cents']))} in QuickBooks, {_m(abs(s['amount']))} on the statement ({how})"
            fix = ({"kind": "reamount", "entity": r["entity"], "txn_id": r["txn_id"], "account": a, "from_cents": r["cents"], "to_cents": s["amount"],
                    "auto": False, "why": f"the statement shows {_m(abs(s['amount']))}: {how}"} if simple and not is_closed(r["date"]) else None)
            add("amount_difference", a, s, r, title,
                f"QuickBooks {r['entity']} {r['txn_id']} ({r.get('payee') or r.get('memo') or 'no description'}) is the statement's line with a different amount. "
                + ("Correct the amount to the statement's if that's right." if fix else
                   "It has several lines (or the month is closed), so the amount is corrected in QuickBooks by hand."),
                fix, severity="blocker")
    return out, used_s, used_r


def _unrecorded(ln, acct, snap, t, names, matched_by, lines_by, hist, cites, rules, open_inv, open_bill, taken):
    """One statement line the ledger doesn't have, with its fix."""
    taken.add(ln["line_id"])
    base = dict(line=ln, account=acct)
    ref = [f"line:{ln['line_id']}"]
    what = (f"{acct}: {_d(ln['date'])} {ln.get('description') or ''}, {_m(abs(ln['amount']))} {'in' if ln['amount'] > 0 else 'out'}, "
            "isn't in QuickBooks")
    # the other half of a transfer between the client's own accounts
    for other, (m2, _) in matched_by.items():
        if other == acct:
            continue
        for o in m2["statement_only"]:
            if o["line_id"] not in taken and o["amount"] == -ln["amount"] and abs((_date(o["date"]) - _date(ln["date"])).days) <= 3:
                taken.add(o["line_id"])
                frm, to = (acct, other) if ln["amount"] < 0 else (other, acct)
                return _f("unrecorded", ln["line_id"], "blocker", f"Transfer of {_m(abs(ln['amount']))} from {frm} to {to} isn't in QuickBooks",
                          f"Both statements show it: {acct} line {ln['line_id']} and {other} line {o['line_id']}.", account=acct,
                          amount=ln["amount"], refs=ref + [f"line:{o['line_id']}"],
                          fix={"kind": "transfer", "from": frm, "to": to, "amount": abs(ln["amount"]), "date": min(ln["date"], o["date"]),
                               "lines": [ln["line_id"], o["line_id"]], "auto": True, "citations": ref + [f"line:{o['line_id']}"],
                               "why": "both statements show the same money moving between the client's own accounts"})
    words = set(re.findall(r"[a-z0-9-]{3,}", str(ln.get("description") or "").lower() + " " + str(ln.get("reference") or "").lower()))
    pool, kind = (open_inv, "receive") if ln["amount"] > 0 else (open_bill, "pay_bill")
    if t.get(acct) == "Credit Card" and ln["amount"] > 0:
        pool = []                                          # a card credit is a refund, not a customer paying an invoice
    same = [o for o in pool if o["open"] == abs(ln["amount"])]
    named = [o for o in same if (o.get("number") and o["number"].lower() in words) or
             (o.get("name") and set(re.findall(r"[a-z]{3,}", o["name"].lower())) & words)]
    hit = named[0] if len(named) == 1 else (same[0] if len(same) == 1 else None)
    if hit:
        doc = "invoice" if kind == "receive" else "bill"
        return _f("unrecorded", ln["line_id"], "blocker", what,
                  f"It pays open {doc} {hit.get('number') or hit['id']} ({hit.get('name') or 'no name'}, {_m(hit['open'])} due).",
                  account=acct, amount=ln["amount"], refs=ref + [f"ledger:{hit['id']}"],
                  fix={**base, "kind": kind, "item": hit, "auto": bool(named), "citations": ref + [f"ledger:{hit['id']}"],
                       "why": (f"the line names {doc} {hit.get('number') or hit.get('name')}" if named else
                               f"the only open {doc} for exactly this amount: a person confirms")})
    mine = next((r for r in rules if r["account"] == PERSONAL and r["pattern"].lower() in str(ln.get("description") or "").lower()), None)
    if mine:                                               # the owner's, by a person's instruction: the owner's draw or contribution
        draw, contrib = owner_accounts(t)
        owner = draw if ln["amount"] < 0 else contrib
        if owner:
            return _f("unrecorded", ln["line_id"], "blocker", what, f"Your instruction \"{mine['pattern']}\" says it's personal: the agents record it to {owner}.",
                      account=acct, amount=ln["amount"], refs=ref + [f"rule:{mine['id']}"],
                      fix={**base, "kind": "create", "to": owner, "auto": True, "citations": ref + [f"rule:{mine['id']}"],
                           "why": f"the instruction \"{mine['pattern']}\" says it's the owner's"})
    acct_for, why_cites, why = classify(ln, hist, cites, rules, names - {acct})
    if acct_for and t.get(acct_for) in ("Bank", "Credit Card"):
        acct_for = None
    fix = {**base, "kind": "create", "to": acct_for, "auto": bool(acct_for and why_cites), "citations": ref + why_cites, "why": why}
    return _f("unrecorded", ln["line_id"], "blocker", what,
              (f"The agents will record it to {acct_for}: {why}." if acct_for else f"Which account? {why}."),
              account=acct, amount=ln["amount"], refs=ref, fix=fix, who="agent" if acct_for else "reviewer")


def _words3(text):
    return set(re.findall(r"[a-z0-9][a-z0-9-]{2,}", str(text or "").lower())) - {"inc", "llc", "the", "and", "deposit", "payment", "mobile", "online"}


def _patterns(snap, t, said, rules, personal, draw, contrib, already):
    """The usual ways a client's own books go wrong, each with the change that puts it right (docs/102 step 5):
      revenue_twice     a deposit booked straight to income for an invoice that's still open (the invoice and the deposit
                        both count the sale): the deposit is replaced by a payment applied to the invoice
      bill_paid_as_expense  an expense for a bill that's still open (the bill and the expense both count the cost): the
                        expense is replaced by a bill payment applied to the bill
      personal_in_business  an expense a person's instruction says is the owner's: moved to the owner's draw
    A replacement deletes the client's entry, so it's always a person's click."""
    out = []
    by_txn = defaultdict(list)
    for x in snap["lines"]:
        by_txn[str(x["txn_id"])].append(x)
    income = {a for a, typ in t.items() if typ in ("Income", "Other Income")}
    costs = {a for a, typ in t.items() if typ in ("Expense", "Other Expense", "Cost of Goods Sold")}
    cash = {a for a, typ in t.items() if typ in ("Bank", "Credit Card")}

    def text(tid, xs):
        return " ".join([said.get(tid) or ""] + [str(x.get(k) or "") for x in xs for k in ("payee", "memo", "line_memo", "doc_number")])

    def named(item, words):
        return (item.get("number") and item["number"].lower() in words) or bool(item.get("name") and _words3(item["name"]) & words)
    taken_inv, taken_bill = set(), set()
    for tid, xs in sorted(by_txn.items(), key=lambda kv: kv[1][0]["date"]):
        if f"ledger:{tid}" in already:
            continue
        bank = [x for x in xs if x["account"] in cash]
        rest = [x for x in xs if x["account"] not in cash]
        if len(bank) != 1 or not rest:
            continue
        b, words = bank[0], _words3(text(tid, xs))
        if b["entity"] == "Deposit" and b["cents"] > 0 and all(x["account"] in income for x in rest) and t.get(b["account"]) == "Bank":
            hits = [o for o in snap.get("open_invoices") or [] if o["open"] == b["cents"] and o["id"] not in taken_inv
                    and (o.get("date") or "") <= b["date"] and named(o, words)]
            if len(hits) == 1:
                o = hits[0]
                taken_inv.add(o["id"])
                out.append(_f("revenue_twice", f"{tid}:{o['id']}", "blocker",
                              f"{_m(b['cents'])} deposited on {_d(b['date'])} is booked to {', '.join(sorted({x['account'] for x in rest}))}, and invoice "
                              f"{o.get('number') or o['id']} is still open",
                              f"QuickBooks Deposit {tid} records the money as income, and invoice {o.get('number') or o['id']} ({o.get('name') or ''}, "
                              f"{_m(o['open'])}) already counted the sale, so revenue is counted twice and the invoice looks unpaid. The agents replace "
                              f"the deposit with a payment applied to the invoice, into {b['account']} on the same day.",
                              account=b["account"], amount=b["cents"], refs=[f"ledger:{tid}", f"ledger:{o['id']}"], who="reviewer",
                              fix={"kind": "replace", "delete": {"entity": "Deposit", "txn_id": tid},
                                   "create": {"kind": "receive", "account": b["account"], "item": o,
                                              "line": {"date": b["date"], "amount": b["cents"], "line_id": f"ledger-{tid}"},
                                              "citations": [f"ledger:{tid}", f"ledger:{o['id']}"]},
                                   "account": b["account"], "auto": False, "citations": [f"ledger:{tid}", f"ledger:{o['id']}"],
                                   "why": f"the deposit pays invoice {o.get('number') or o['id']}, which is still open"}))
                continue
        if b["entity"] == "Purchase" and b["cents"] < 0 and all(x["account"] in costs for x in rest):
            hits = [o for o in snap.get("open_bills") or [] if o["open"] == -b["cents"] and o["id"] not in taken_bill
                    and (o.get("date") or "") <= b["date"] and named(o, words)]
            if len(hits) == 1:
                o = hits[0]
                taken_bill.add(o["id"])
                out.append(_f("bill_paid_as_expense", f"{tid}:{o['id']}", "blocker",
                              f"{_m(-b['cents'])} paid on {_d(b['date'])} is booked as an expense, and bill {o.get('number') or o['id']} is still open",
                              f"QuickBooks Purchase {tid} records the payment to {o.get('name') or 'the supplier'} as {', '.join(sorted({x['account'] for x in rest}))}, "
                              f"and the bill already counted the cost, so it's counted twice and the bill looks unpaid. The agents replace the "
                              f"expense with a bill payment applied to the bill, from {b['account']} on the same day.",
                              account=b["account"], amount=b["cents"], refs=[f"ledger:{tid}", f"ledger:{o['id']}"], who="reviewer",
                              fix={"kind": "replace", "delete": {"entity": "Purchase", "txn_id": tid},
                                   "create": {"kind": "pay_bill", "account": b["account"], "item": o,
                                              "line": {"date": b["date"], "amount": b["cents"], "line_id": f"ledger-{tid}"},
                                              "citations": [f"ledger:{tid}", f"ledger:{o['id']}"]},
                                   "account": b["account"], "auto": False, "citations": [f"ledger:{tid}", f"ledger:{o['id']}"],
                                   "why": f"the payment is bill {o.get('number') or o['id']}, which is still open"}))
                continue
        if b["account"] not in personal and b["date"] >= snap["start"]:
            mine = next((r for r in rules if r["account"] == PERSONAL and r["pattern"].lower() in text(tid, xs).lower()), None)
            owner = draw if b["cents"] < 0 else contrib
            spent = [x for x in rest if x["account"] in costs | income]
            if mine and owner and spent and len({x["account"] for x in spent}) == 1:
                frm = spent[0]["account"]
                out.append(_f("personal_in_business", f"{tid}:{frm}", "blocker", f"{_m(abs(b['cents']))} on {_d(b['date'])} in {frm} is the owner's",
                              f"QuickBooks {b['entity']} {tid} ({text(tid, xs).strip()[:80]}): your instruction \"{mine['pattern']}\" says it's personal. "
                              f"The agents move it to {owner}.", account=frm, amount=spent[0]["cents"], refs=[f"ledger:{tid}", f"rule:{mine['id']}"],
                              fix={"kind": "recategorize", "entity": b["entity"], "txn_id": tid, "from": frm, "to": owner, "auto": True,
                                   "citations": [f"ledger:{tid}", f"rule:{mine['id']}"], "why": f"the instruction \"{mine['pattern']}\" says it's the owner's"}))
    return out


WAGES = re.compile(r"wage|salar|payroll(?! tax)|compensation", re.I)
PAYROLL_TAX = re.compile(r"payroll tax|employer tax|fica|futa|suta", re.I)


def _payroll(snap, t, runs):
    """Payroll booked at net pay (docs/102 step 5): the register says gross wages, but the wage accounts carry only what
    reached the employees' banks. The employees' withholding belongs in wages too: moved from where the tax payments went
    (payroll tax expense), or added with the liability when the taxes aren't paid yet."""
    if not runs:
        return []
    act = read.month_activity(snap)
    wages = [a for a, typ in t.items() if typ in ("Expense", "Cost of Goods Sold") and WAGES.search(a) and not PAYROLL_TAX.search(a)]
    taxes = [a for a, typ in t.items() if typ in ("Expense", "Cost of Goods Sold") and PAYROLL_TAX.search(a)]
    owed = [a for a, typ in t.items() if typ == "Other Current Liability" and re.search(r"payroll", a, re.I)]
    gross, net = sum(r["gross"] for r in runs), sum(r["net"] for r in runs)
    withheld, employer = sum(r["withheld"] for r in runs), sum(r["employer"] for r in runs)
    booked = sum(act.get(a, 0) for a in wages)
    refs = [f"record:{r['record']}" for r in runs]
    if not wages or not net or abs(booked - net) > max(100, net // 100) or booked >= gross:
        return []                                          # booked at gross (or not booked at all): nothing to gross up
    w = max(wages, key=lambda a: act.get(a, 0))
    lines, how = None, None
    tax_booked = sum(act.get(a, 0) for a in taxes)
    if taxes and tax_booked >= withheld + employer - 100:
        tx = max(taxes, key=lambda a: act.get(a, 0))
        lines = [{"account": w, "cents": gross - booked}, {"account": tx, "cents": -(gross - booked)}]
        how = f"the employees' withholding ({_m(gross - booked)}) is in {tx} with the employer's tax: it moves to {w}"
    elif owed:
        lines = [{"account": w, "cents": gross - booked}] + ([{"account": taxes[0], "cents": employer}] if taxes and employer else []) + \
                [{"account": owed[0], "cents": -(gross - booked) - (employer if taxes and employer else 0)}]
        how = f"wages are grossed up by {_m(gross - booked)}" + (f" and the employer's tax {_m(employer)} added" if taxes and employer else "") + \
              f", owed in {owed[0]} until paid"
    return [_f("payroll_net", snap["period"], "blocker", f"Payroll is booked at net pay: {_m(booked)} in {w}, the register says {_m(gross)} gross",
               f"The payroll register for {snap['period']}: gross {_m(gross)}, net {_m(net)}, withheld {_m(withheld)}, employer tax {_m(employer)}. "
               + (f"The agents' entry: {how}." if lines else "QuickBooks has no payroll liability or payroll tax account to put the difference in: add one."),
               account=w, amount=gross - booked, refs=refs, who="reviewer",
               fix={"kind": "journal", "date": snap["end"], "memo": f"NHB: payroll {snap['period']} grossed up to the register", "lines": lines,
                    "auto": False, "citations": refs, "why": how} if lines else None)]


def _uncategorized(snap, t, hist, cites, rules, names, said=None):
    out = []
    held = [a for a in t if UNCATEGORIZED.search(a)]
    for x in snap["lines"]:
        if x["account"] not in held or x["date"] < snap["start"]:
            continue
        text = (said or {}).get(x["txn_id"]) or " ".join(str(v or "") for v in (x.get("payee"), x.get("memo"), x.get("line_memo")))
        line = {"description": text, "amount": -x["cents"]}
        to, cs, why = classify(line, hist, cites, rules, {n for n in names if n not in held and t.get(n) not in ("Bank", "Credit Card")})
        out.append(_f("uncategorized", f"{x['txn_id']}:{x['account']}", "blocker", f"{_m(abs(x['cents']))} on {_d(x['date'])} is in {x['account']}",
                      f"QuickBooks {x['entity']} {x['txn_id']} ({line['description'].strip() or 'no description'}). "
                      + (f"The agents will move it to {to}: {why}." if to else f"Which account? {why}."),
                      account=x["account"], amount=x["cents"], refs=[f"ledger:{x['txn_id']}"],
                      fix={"kind": "recategorize", "entity": x["entity"], "txn_id": x["txn_id"], "from": x["account"], "to": to,
                           "auto": bool(to and cs), "citations": [f"ledger:{x['txn_id']}"] + cs, "why": why},
                      who="agent" if to else "reviewer"))
    obe = [a for a in t if "opening balance equity" in a.lower() and snap["tb"].get(a)]
    for a in obe:
        out.append(_f("opening_balance_equity", a, "review", f"{a} holds {_m(-snap['tb'][a])}",
                      "QuickBooks puts an account's opening balance here when it's entered with the account. It belongs in the owner's "
                      "equity or retained earnings once the opening balances are proved.", account=a, amount=snap["tb"][a], who="reviewer"))
    return out


def _clearing(snap, t):
    out = []
    for a, v in snap["tb"].items():
        if not v or not CLEARING.search(a) or t.get(a) in ("Income", "Expense"):
            continue
        old = [x for x in snap["lines"] if x["account"] == a and x["cents"] > 0 and (_date(snap["end"]) - _date(x["date"])).days > 10]
        out.append(_f("clearing_balance", a, "review", f"{a} holds {_m(v)} at {_d(snap['end'])}",
                      f"A clearing account should be empty once the money settles. {len(old)} entr{'y' if len(old) == 1 else 'ies'} in it are "
                      "more than 10 days old: payments not yet deposited, or settlements recorded elsewhere.", account=a, amount=v,
                      refs=[f"ledger:{x['txn_id']}" for x in old[:10]], who="reviewer"))
    return out


def _signs(snap, t):
    out = []
    for a, v in snap["tb"].items():
        typ = t.get(a)
        cls = {"Bank": 1, "Accounts Receivable": 1, "Other Current Asset": 1, "Fixed Asset": 1, "Accounts Payable": -1,
               "Credit Card": -1, "Other Current Liability": -1, "Long Term Liability": -1}.get(typ)
        if cls and v and (v > 0) != (cls > 0) and not CONTRA.search(a):
            out.append(_f("unusual_balance", a, "review", f"{a} has a {'credit' if v < 0 else 'debit'} balance of {_m(abs(v))}",
                          f"A {typ.lower()} account normally has a {'debit' if cls > 0 else 'credit'} balance: an overdraft, a payment "
                          "recorded twice, or an entry to the wrong account.", account=a, amount=v, who="reviewer"))
    return out


def _receivables(snap, t):
    out = []
    for typ, items, word in (("Accounts Receivable", snap.get("open_invoices") or [], "invoice"), ("Accounts Payable", snap.get("open_bills") or [], "bill")):
        old = [o for o in items if o.get("due") and (_date(snap["end"]) - _date(o["due"])).days > 90]
        if old:
            out.append(_f("old_open_items", typ, "info", f"{len(old)} {word}s more than 90 days past due ({_m(sum(o['open'] for o in old))})",
                          f"Open {word}s past due over 90 days: " + "; ".join(f"{o.get('number') or o['id']} {o.get('name') or ''} {_m(o['open'])}"
                                                                         for o in old[:8]) + ". Collectible (or payable) still?",
                          amount=sum(o["open"] for o in old), refs=[f"ledger:{o['id']}" for o in old[:20]], who="reviewer"))
    return out


def _lenders(snap, t, lenders, account_map):
    out = []
    liab = [a for a, typ in t.items() if typ in ("Long Term Liability", "Other Current Liability")]
    for s in lenders:
        acct = (account_map or {}).get(s["loan"])
        if acct not in t:
            hits = [a for a in liab if s["loan"].lower() in a.lower()]
            acct = hits[0] if len(hits) == 1 else None
        if acct is None:
            out.append(_f("lender_unmapped", s["loan"], "review", f"Which QuickBooks account holds {s['loan']}?",
                          f"The lender's statement for {s['loan']} shows {_m(s['closing_principal'])} owed at {s['date']}, and no liability "
                          "account names it. Match it in the client's account map.", amount=s["closing_principal"], who="reviewer"))
            continue
        owed = -read.balance_at(snap, acct, s["date"])
        if owed != s["closing_principal"]:
            out.append(_f("lender_difference", f"{s['loan']}:{s['date']}", "blocker", f"{acct} is {_m(owed - s['closing_principal'])} off the lender's statement",
                          f"The lender says {_m(s['closing_principal'])} is owed at {s['date']}; QuickBooks has {_m(owed)}. Usually a payment booked "
                          "entirely to the loan (the interest belongs in interest expense) or a missing draw.", account=acct,
                          amount=owed - s["closing_principal"], refs=[f"record:{s['record']}"], who="reviewer"))
    return out


def _schedules(snap, t, schedules):
    """An approved schedule's entry for the month, when the ledger doesn't have it yet (found by its note)."""
    out = []
    notes = {str(x.get("memo") or "") for x in snap["lines"] if x["date"] >= snap["start"]}
    for s in schedules:
        if not (s["debit"] in t and s["credit"] in t):
            out.append(_f("schedule_unmapped", s["key"], "review", f"Schedule {s['label']}: its accounts aren't in QuickBooks",
                          f"The schedule books {s['debit']} / {s['credit']}; match them to QuickBooks accounts.", who="reviewer"))
            continue
        tag = f"NHB schedule {s['key']} {snap['period']}"
        if any(tag in n for n in notes):
            mine = [x for x in snap["lines"] if x["date"] >= snap["start"] and tag in str(x.get("memo") or "")]
            got = {}
            for x in mine:
                got[x["account"]] = got.get(x["account"], 0) + x["cents"]
            want = {s["debit"]: s["monthly_cents"], s["credit"]: -s["monthly_cents"]}
            if {a: v for a, v in got.items() if v} != want:                       # the note is there; the entry isn't the schedule's
                out.append(_f("schedule_mismatch", f"{s['key']}:{snap['period']}", "blocker",
                              f"{s['label']}: the {snap['period']} entry doesn't match the schedule",
                              f"The entry carrying the schedule's note posts " + "; ".join(f"{a} {_m(v)}" for a, v in sorted(got.items())) +
                              f". The approved schedule books {_m(s['monthly_cents'])} to {s['debit']} from {s['credit']}. Correct the entry in QuickBooks, "
                              "or the schedule.", account=s["debit"], amount=s["monthly_cents"] - got.get(s["debit"], 0),
                              refs=[f"ledger:{x['txn_id']}" for x in mine[:10]] + [f"schedule:{s['key']}"], who="reviewer"))
            continue
        out.append(_f("schedule_entry", f"{s['key']}:{snap['period']}", "blocker", f"{s['label']}: {snap['period']} entry not booked",
                      f"The approved schedule books {_m(s['monthly_cents'])} a month to {s['debit']} from {s['credit']}.",
                      account=s["debit"], amount=s["monthly_cents"],
                      fix={"kind": "journal", "date": snap["end"], "memo": tag, "auto": True, "citations": [f"schedule:{s['key']}"],
                           "why": "an approved schedule", "lines": [{"account": s["debit"], "cents": s["monthly_cents"]},
                                                                     {"account": s["credit"], "cents": -s["monthly_cents"]}]}))
    return out


def _continuity(c, snap=None):
    """The last closed month as QuickBooks has it now, against what was signed off (docs/102 step 5, decision 7). A change
    is reversed by one entry in the open month (the signed-off month stays as it was sent: c["reversed"] holds what earlier
    reversals put back), or the month is reopened."""
    if not c:
        return []
    rev = c.get("reversed") or {}
    accts = sorted(set(c["signed_tb"]) | set(c["now_tb"]) | set(rev))
    diffs = {a: c["now_tb"].get(a, 0) - c["signed_tb"].get(a, 0) + rev.get(a, 0) for a in accts}
    diffs = {a: d for a, d in diffs.items() if d}
    if not diffs:
        return []
    if snap is not None and sum(diffs.values()) == 0 and (not snap.get("close_date") or snap["start"] > snap["close_date"]):
        t = read.types(snap)
        re_name = next((a for a, typ in t.items() if typ == "Equity" and "retained" in a.lower()), None)
        new_year = snap["fy_start"] > c["as_of"]           # last year's income and expense are in Retained Earnings now
        lines = defaultdict(int)
        for a, d in diffs.items():
            lines[re_name if new_year and t.get(a) in read.PL and re_name else a] -= d
        lines = [{"account": a, "cents": v} for a, v in lines.items() if v]
        return [_f("closed_month_changed", c["as_of"], "blocker", f"{c['period']} was changed in QuickBooks after it was signed off",
                   "Changed since the sign-off: " + "; ".join(f"{a} {_m(d)}" for a, d in diffs.items()) + ". The agents' entry reverses it on "
                   f"{_d(snap['start'])}, so {c['period']} stays as it was sent; or reopen {c['period']} if the change is right.",
                   amount=sum(abs(d) for d in diffs.values()) // 2, refs=[f"signoff:{c['period']}"], who="reviewer",
                   fix={"kind": "journal", "date": snap["start"], "memo": f"NHB: reverses the change made to closed {c['period']}"[:200],
                        "lines": lines, "auto": False, "citations": [f"signoff:{c['period']}"], "reverses": diffs,
                        "why": f"{c['period']} was signed off; the change to it is reversed in the open month"})] if lines else []
    return [_f("changed_after_signoff", f"{c['as_of']}:{a}", "blocker", f"{a} changed by {_m(d)} after {c['period']} was signed off",
               f"At {c['as_of']} QuickBooks now has {_m(c['now_tb'].get(a, 0))}; the signed-off books had {_m(c['signed_tb'].get(a, 0))}. "
               "Someone changed a closed month: find the change in QuickBooks' audit log and reverse it, or reopen that month.",
               account=a, amount=d, who="reviewer") for a, d in diffs.items()]


def _flux(snap, t):
    out = []
    act = read.month_activity(snap)
    prior = {}
    for x in snap["lines"]:
        if x["date"] < snap["start"] and t.get(x["account"]) in read.PL:
            prior.setdefault(x["account"], Counter())[x["date"][:7]] += x["cents"]
    for a, v in act.items():
        if t.get(a) not in read.PL:
            continue
        months = prior.get(a) or {}
        base = round(sum(months.values()) / len(months)) if months else 0
        if abs(v - base) >= FLUX_FLOOR and (not base or abs(v - base) >= FLUX_SHARE * abs(base)):
            top = sorted((x for x in snap["lines"] if x["account"] == a and x["date"] >= snap["start"]), key=lambda x: -abs(x["cents"]))[:3]
            out.append(_f("flux", a, "info", f"{a}: {_m(abs(v))} this month against about {_m(abs(base))} before",
                          "Largest this month: " + "; ".join(f"{_d(x['date'])} {x.get('payee') or x.get('memo') or x['entity']} {_m(abs(x['cents']))}"
                                                             for x in top) + ".", account=a, amount=v - base,
                          refs=[f"ledger:{x['txn_id']}" for x in top]))
    return out
