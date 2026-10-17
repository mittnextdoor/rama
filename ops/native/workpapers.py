"""Workpapers for every balance-sheet account, from QuickBooks' own figures (docs/103 WP6; owner, 2026-10-17: "work through
all the workpapers": the books are correct and reconciled in QuickBooks, and the software reflects that).

Each workpaper is one account's roll-forward for the month, opening + activity = closing, with what supports the closing
balance and a status that says whether that support ties:

  tied         the support agrees with QuickBooks (a statement, the open invoices or bills, the payments waiting in
               Undeposited Funds, an approved schedule's entry, the lender's statement, or an equity account's own movement)
  exception    there is support and it disagrees: the difference is an open item
  unsupported  a balance with nothing behind it in the evidence (no statement, no schedule, no lender statement): an
               open item asks a person what supports it, or asks the client for the evidence
  excused      a person recorded that the account has no statement
  info         an account whose own movement is its support (equity, Retained Earnings with no activity), or a zero
               balance with no activity

The paper also lists the month's lines, so a reviewer can see what moved. A paper the reviewer doesn't accept becomes a
review item (product/workflow.workpaper_review). Nothing here writes to QuickBooks."""
import re
from collections import defaultdict

from . import read

LOAN = re.compile(r"loan|note payable|notes payable|line of credit|financing|mortgage|lease liab|sba|eidl|ppp", re.I)
PAYROLL_LIAB = re.compile(r"payroll|wage|withh|401|garnish|fica|futa|suta|direct deposit", re.I)
TAX_LIAB = re.compile(r"sales tax|use tax|tax payable|tax liab", re.I)
DEFERRED = re.compile(r"deferred|unearned|customer deposit|retainer", re.I)
PREPAID = re.compile(r"prepaid|prepay", re.I)
ACCUM = re.compile(r"accumulated|accum\.? dep", re.I)
CLEARING = re.compile(r"undeposited|clearing|suspense", re.I)
RETAINED = re.compile(r"retained", re.I)
OBE = re.compile(r"opening balance equity", re.I)
BUCKETS = ((0, "Current"), (30, "1–30 days"), (60, "31–60 days"), (90, "61–90 days"), (10 ** 6, "Over 90 days"))


def _m(c):
    return f"({abs(c) / 100:,.2f})" if c < 0 else f"{c / 100:,.2f}"


def _d(day):
    return f"{day[5:7]}/{day[8:10]}/{day[:4]}" if day and len(day) >= 10 else (day or "")


def kind_of(name, typ):
    """What sort of balance this is, from QuickBooks' account type and the account's name."""
    if typ == "Bank":
        return "bank"
    if typ == "Credit Card":
        return "card"
    if typ == "Accounts Receivable":
        return "receivable"
    if typ == "Accounts Payable":
        return "payable"
    if typ == "Fixed Asset":
        return "accumulated_depreciation" if ACCUM.search(name) else "fixed_asset"
    if typ == "Equity":
        return "opening_balance_equity" if OBE.search(name) else "retained_earnings" if RETAINED.search(name) else "equity"
    if typ in ("Other Current Asset", "Other Asset"):
        if CLEARING.search(name):
            return "clearing"
        if PREPAID.search(name):
            return "prepaid"
        return "other_asset"
    if typ in ("Other Current Liability", "Long Term Liability"):
        if LOAN.search(name):
            return "loan"
        if PAYROLL_LIAB.search(name):
            return "payroll_liability"
        if TAX_LIAB.search(name):
            return "tax_liability"
        if DEFERRED.search(name):
            return "deferred_revenue"
        return "other_liability"
    return "other"


def _aging(items, as_of):
    out = {label: 0 for _, label in BUCKETS}
    for o in items:
        due = o.get("due") or o.get("date")
        days = (read.date.fromisoformat(as_of) - read.date.fromisoformat(due)).days if due else 0
        for limit, label in BUCKETS:
            if days <= limit:
                out[label] += o["open"]
                break
    return [{"bucket": label, "cents": v} for _, label in BUCKETS for v in [out[label]]]


def build(snap, t, recons, ev, schedules, findings, excused=()):
    """(papers, new findings). recons: the month's reconciliations (checks.run); schedules: the approved schedules in force
    (debit, credit, monthly_cents, key, label); findings: the checks' findings so far (a paper points at the ones about its
    account and raises none of its own where one already says it)."""
    papers, out = [], []
    lines_of = defaultdict(list)
    for x in snap["lines"]:
        if snap["start"] <= x["date"] <= snap["end"]:
            lines_of[x["account"]].append(x)
    by_acct_findings = defaultdict(list)
    for f in findings:
        if f.get("account"):
            by_acct_findings[f["account"]].append(f)
    by_acct_findings["__all__"] = list(findings)
    recon_by = {r["account"]: r for r in recons or []}
    lenders = {str(s["loan"]).lower(): s for s in (ev or {}).get("lenders") or []}
    payroll = (ev or {}).get("payroll") or []
    sched_by = defaultdict(list)
    for s in schedules or []:
        sched_by[s["debit"]].append((s, 1))
        sched_by[s["credit"]].append((s, -1))
    waiting = snap.get("undeposited") or []
    accounts = sorted(a for a in set(snap["tb"]) | set(snap["prior_tb"]) | set(lines_of) if t.get(a) and t[a] not in read.PL)
    for a in accounts:
        typ, kind = t[a], kind_of(a, t[a])
        opening, closing = snap["prior_tb"].get(a, 0), snap["tb"].get(a, 0)
        rows = sorted(lines_of.get(a) or [], key=lambda x: (x["date"], str(x["txn_id"])))
        moved = sum(x["cents"] for x in rows)
        paper = {"account": a, "type": typ, "kind": kind, "opening": opening, "closing": closing, "moved": moved,
                 "activity": {"debits": sum(x["cents"] for x in rows if x["cents"] > 0), "credits": -sum(x["cents"] for x in rows if x["cents"] < 0),
                              "count": len(rows)},
                 "rows": [{"date": x["date"], "entity": x["entity"], "txn": str(x["txn_id"]), "what": x.get("payee") or x.get("line_memo") or x.get("memo") or "",
                           "cents": x["cents"], "doc": x.get("doc_number")} for x in rows[:400]],
                 "rollforward": [{"label": f"Balance at {_d(read._day_before(snap['start']))}", "cents": opening}],
                 "support": None, "status": "info", "detail": "", "findings": [f["key"] for f in by_acct_findings.get(a, [])]}
        if opening + moved != closing and not (kind == "retained_earnings" and snap.get("fy_start") != snap.get("prior_fy_start")):
            gap = closing - opening - moved
            paper.update(status="exception", support="QuickBooks' own register",
                         detail=f"The lines read for the month move the account by {_m(moved)}, but QuickBooks' balances moved by {_m(closing - opening)}: "
                                f"{_m(gap)} isn't in the register as read (a transaction dated outside the month that changed a balance, or a line the read "
                                "missed). The agents read the account again before anything else relies on it.")
            out.append(_f("ledger_gap", a, "review", f"{a}: QuickBooks' balance moved {_m(gap)} more than its register shows",
                          paper["detail"], account=a, amount=gap, who="reviewer"))
            paper["rollforward"] += [{"label": "Register activity", "cents": moved}, {"label": "Not in the register as read", "cents": gap}]
        else:
            paper["rollforward"].append({"label": "Debits" if kind in ("bank", "receivable", "fixed_asset", "prepaid", "other_asset", "clearing") else "Decreases",
                                         "cents": paper["activity"]["debits"]})
            paper["rollforward"].append({"label": "Credits" if kind in ("bank", "receivable", "fixed_asset", "prepaid", "other_asset", "clearing") else "Increases",
                                         "cents": -paper["activity"]["credits"]})
        paper["rollforward"].append({"label": f"Balance at {_d(snap['end'])}", "cents": closing})
        if paper["status"] != "exception":
            _support(paper, a, kind, snap, recon_by, lenders, payroll, sched_by, waiting, by_acct_findings, excused, out, t)
        papers.append(paper)
    return papers, out


def _f(check, key, severity, title, detail, *, account=None, amount=0, refs=(), fix=None, who="reviewer"):
    return {"key": f"{check}:{key}", "check": check, "severity": severity, "title": title, "detail": detail, "account": account,
            "amount_cents": int(amount or 0), "refs": list(refs), "fix": fix, "who": who}


def _support(p, a, kind, snap, recon_by, lenders, payroll, sched_by, waiting, by_acct, excused, out, t):
    closing, opening, rows = p["closing"], p["opening"], p["rows"]
    mine = by_acct.get(a, [])
    open_mine = [f for f in mine if f["severity"] != "info"]
    if kind in ("bank", "card"):
        r = recon_by.get(a)
        if r is not None:
            p["support"] = f"{'Card' if kind == 'card' else 'Bank'} statement to {_d(r['as_of'])}: {_m(r['statement_closing'])}"
            p["reconciliation"] = {"statement_closing": r["statement_closing"], "outstanding": sum(x["cents"] for x in r["outstanding"]),
                                   "unrecorded": sum(x["amount"] for x in r["unrecorded"]), "difference": r["difference"], "matched": r["matched"]}
            if r["difference"] == 0 and not r["unrecorded"]:
                p.update(status="tied", detail=f"Reconciled to the statement: {r['matched']} lines matched"
                         + (f", {len(r['outstanding'])} outstanding ({_m(sum(x['cents'] for x in r['outstanding']))})" if r["outstanding"] else "") + ".")
            else:
                p.update(status="exception", detail=f"The statement and QuickBooks differ by {_m(r['difference'])}" + (f"; {len(r['unrecorded'])} statement lines aren't in QuickBooks yet" if r["unrecorded"] else "") + ".")
        elif a in excused:
            p.update(status="excused", support="No statement (a person recorded it)", detail="Petty cash or a closed account: not reconciled.")
        else:
            p.update(status="unsupported", support="No statement for the month", detail="The month's statement hasn't been received, so the balance isn't proved.")
        return
    if kind in ("receivable", "payable"):
        items = snap.get("open_invoices" if kind == "receivable" else "open_bills") or []
        total = sum(o["open"] for o in items)
        want = closing if kind == "receivable" else -closing
        p["support"] = f"{len(items)} open {'invoice' if kind == 'receivable' else 'bill'}{'s' if len(items) != 1 else ''}: {_m(total)}"
        p["aging"] = _aging(items, snap["end"])
        credits = [o for o in items if o["open"] < 0]
        p["detail_items"] = [{"id": o["id"], "number": o.get("number"), "name": o.get("name"), "date": o.get("date"), "due": o.get("due"), "open": o["open"]}
                             for o in sorted(items, key=lambda o: o.get("due") or o.get("date") or "")[:300]]
        if total == want:
            p.update(status="tied", detail=f"The open {'invoices' if kind == 'receivable' else 'bills'} add up to the balance." + (f" {len(credits)} with a credit balance (an overpayment or a deposit) to look at." if credits else ""))
            if credits:
                p["status"] = "exception"
                out.append(_f(f"{'ar' if kind == 'receivable' else 'ap'}_credit_balance", a, "review",
                              f"{a}: {len(credits)} {'customer' if kind == 'receivable' else 'supplier'}{'s' if len(credits) != 1 else ''} with a credit balance ({_m(sum(o['open'] for o in credits))})",
                              "An overpayment, an unapplied payment or a deposit: " + "; ".join(f"{o.get('number') or o['id']} {o.get('name') or ''} {_m(o['open'])}" for o in credits[:8])
                              + ". Apply it, refund it, or leave it with a reason.", account=a, amount=sum(o["open"] for o in credits), refs=[f"ledger:{o['id']}" for o in credits[:20]]))
        else:
            diff = want - total
            p.update(status="exception", detail=f"The open {'invoices' if kind == 'receivable' else 'bills'} ({_m(total)}) don't add up to the balance ({_m(want)}): {_m(diff)} unexplained.")
            out.append(_f(f"{'ar' if kind == 'receivable' else 'ap'}_detail_difference", f"{a}:{snap['end']}", "review",
                          f"{a}: the open {'invoices' if kind == 'receivable' else 'bills'} are {_m(diff)} off the balance",
                          f"QuickBooks' {a} balance is {_m(want)}; its open {'invoices' if kind == 'receivable' else 'bills'} add up to {_m(total)}. A journal entry "
                          f"posted straight to {a}, an item dated after the month end, or a {'payment' if kind == 'receivable' else 'bill payment'} not applied "
                          "to its document. Find it in QuickBooks' aging report.", account=a, amount=diff))
        return
    if kind == "clearing":
        held = sum(u["amount"] for u in waiting) if CLEARING.search(a) and "undeposited" in a.lower() else None
        if closing == 0:
            p.update(status="tied", support="Nothing waiting", detail="Cleared: the balance is zero at the month end.")
        elif held is not None and held == closing:
            p.update(status="tied", support=f"{len(waiting)} payment{'s' if len(waiting) != 1 else ''} waiting to be deposited: {_m(held)}",
                     detail="Every dollar in it is a payment received that no deposit has taken yet: " + "; ".join(f"{u.get('name') or u['entity']} {_m(u['amount'])} ({_d(u['date'])})" for u in waiting[:8]) + ".")
            p["detail_items"] = [{"id": u["id"], "number": u.get("number"), "name": u.get("name"), "date": u["date"], "open": u["amount"]} for u in waiting[:300]]
        else:
            p.update(status="exception", support=f"Payments waiting: {_m(held)}" if held is not None else "A clearing account",
                     detail=(f"The balance {_m(closing)} isn't the payments waiting ({_m(held)}): {_m(closing - held)} is something else." if held is not None else
                             f"A clearing account should be empty once the money settles; it holds {_m(closing)}."))
        return
    scheds = sched_by.get(a) or []
    if kind in ("prepaid", "accumulated_depreciation", "deferred_revenue", "other_asset", "other_liability", "fixed_asset") and scheds:
        expected = sum(sign * s["monthly_cents"] for s, sign in scheds)
        tagged = [x for x in rows if "NHB schedule" in str(x.get("what") or "") or any(f"NHB schedule {s['key']}" in str(x.get("what") or "") for s, _ in scheds)]
        booked = sum(x["cents"] for x in tagged)
        others = [x for x in rows if x not in tagged]
        p["support"] = ", ".join(f"schedule {s['label']} ({_m(sign * s['monthly_cents'])} a month)" for s, sign in scheds)
        p["rollforward"] = [p["rollforward"][0], {"label": "Additions and other entries", "cents": sum(x["cents"] for x in others)},
                            {"label": "Schedule entries this month", "cents": booked}, p["rollforward"][-1]]
        if booked == expected:
            p.update(status="tied", detail="The month's schedule entries agree with the approved schedules." + (f" {len(others)} other entr{'y' if len(others) == 1 else 'ies'} ({_m(sum(x['cents'] for x in others))}): new additions to put on a schedule." if others else ""))
            if others and kind in ("prepaid", "deferred_revenue"):
                p["status"] = "exception"
                out.append(_f("schedule_addition", f"{a}:{snap['end']}", "review", f"{a}: {_m(abs(sum(x['cents'] for x in others)))} added this month isn't on a schedule",
                              "New prepayments or deposits need their own schedule (coverage dates, monthly amount) so next month's entry is booked: "
                              + "; ".join(f"{_d(x['date'])} {x['what']} {_m(x['cents'])}" for x in others[:6]) + ".", account=a,
                              amount=sum(x["cents"] for x in others), refs=[f"ledger:{x['txn']}" for x in others[:20]]))
        elif booked == 0 and any(f["check"] == "schedule_entry" and any(f["key"].startswith(f"schedule_entry:{s['key']}:") for s, _ in scheds)
                                 for f in by_acct.get("__all__", [])):
            p.update(status="exception", detail="The month's schedule entry isn't booked yet (the agents book it).")
            p["findings"] = sorted(set(p["findings"]) | {f["key"] for f in by_acct["__all__"] if f["check"] == "schedule_entry"
                                                         and any(f["key"].startswith(f"schedule_entry:{s['key']}:") for s, _ in scheds)})
        else:
            p.update(status="exception", detail=f"Schedule entries this month {_m(booked)}; the approved schedules say {_m(expected)}.")
            said = {f["key"] for f in by_acct["__all__"] if f["check"] == "schedule_mismatch" and any(f["key"].startswith(f"schedule_mismatch:{s['key']}:") for s, _ in scheds)}
            if said:
                p["findings"] = sorted(set(p["findings"]) | said)
            else:
                out.append(_f("schedule_mismatch", f"{a}:{snap['end']}", "blocker", f"{a}: the schedule entries booked ({_m(booked)}) aren't what the schedules say ({_m(expected)})",
                              "An entry carries a schedule's note but not its amount or account, or a schedule was booked twice. Correct the entry in QuickBooks, or the schedule.",
                              account=a, amount=expected - booked, refs=[f"ledger:{x['txn']}" for x in tagged[:20]]))
        return
    if kind == "loan":
        s = next((v for k, v in lenders.items() if k in a.lower() or a.lower() in k), None)
        if s is None and len(lenders) == 1 and sum(1 for b in snap["tb"] if kind_of(b, t.get(b, "")) == "loan") == 1:
            s = next(iter(lenders.values()))
        p["rollforward"] = [p["rollforward"][0], {"label": "Draws and interest added", "cents": -p["activity"]["credits"]},
                            {"label": "Principal paid", "cents": p["activity"]["debits"]}, p["rollforward"][-1]]
        if s is not None:
            p["support"] = f"Lender statement {_d(s['date'])}: {_m(s['closing_principal'])} owed"
            if -closing == s["closing_principal"]:
                p.update(status="tied", detail="QuickBooks agrees with the lender's statement.")
            else:
                p.update(status="exception", detail=f"QuickBooks shows {_m(-closing)} owed; the lender says {_m(s['closing_principal'])}.")
        elif closing or rows:
            p.update(status="unsupported", support="No lender statement for the month",
                     detail=f"{_m(-closing)} owed at the month end with no lender statement to prove it; the interest split can't be checked either.")
            if not any(f["check"] == "lender_statement_missing" for f in mine):
                out.append(_f("lender_statement_missing", f"{a}:{snap['period']}", "review", f"No {snap['period']} lender statement for {a}",
                              f"The balance ({_m(-closing)}) and this month's interest can't be proved without the lender's statement. Ask the client for it.",
                              account=a, amount=closing, who="client"))
        else:
            p.update(status="info", support="No balance", detail="Nothing owed.")
        return
    if kind == "payroll_liability":
        if payroll:
            g, w, e = sum(r["gross"] for r in payroll), sum(r["withheld"] for r in payroll), sum(r["employer"] for r in payroll)
            p["support"] = f"Payroll register: gross {_m(g)}, withheld {_m(w)}, employer tax {_m(e)}"
            if closing == 0:
                p.update(status="tied", detail="Everything withheld and owed was paid by the month end.")
            else:
                p.update(status="exception", detail=f"{_m(-closing)} still owed at the month end: taxes or deductions not yet remitted, or a payroll "
                                                     "entry out of step with the register.")
        elif closing or rows:
            p.update(status="unsupported", support="No payroll register for the month", detail=f"{_m(-closing)} owed with no payroll register behind it.")
            if not any(f["check"] == "unsupported_balance" for f in mine):
                out.append(_unsupported(a, closing, "the month's payroll register (gross, withholding, employer tax, net)", snap))
        else:
            p.update(status="info", support="No balance")
        return
    if kind in ("equity", "retained_earnings", "opening_balance_equity"):
        p["support"] = "The account's own movement"
        if kind == "retained_earnings":
            within = [x for x in rows if x["date"] >= snap["fy_start"]]
            if within:
                p.update(status="exception", detail=f"{len(within)} entr{'y' if len(within) == 1 else 'ies'} posted to Retained Earnings this month: {_m(sum(x['cents'] for x in within))}. "
                                                     "Nothing posts there during the year except a prior-year correction a person meant.")
                out.append(_f("retained_earnings_activity", f"{a}:{snap['period']}", "review", f"{a}: {_m(sum(x['cents'] for x in within))} posted this month",
                              p["detail"], account=a, amount=sum(x["cents"] for x in within), refs=[f"ledger:{x['txn']}" for x in within[:20]]))
            else:
                p.update(status="info", detail="No entries this month, as expected.")
        elif kind == "opening_balance_equity":
            p.update(status="exception" if closing else "info", detail="Holds a balance: it belongs in the owner's equity or retained earnings once the opening is proved." if closing else "Empty.")
        else:
            p.update(status="info", detail=f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'} this month: the owner's contributions, draws and the lines recorded as paid by the owner.")
        return
    # anything else with a balance and nothing behind it
    if kind == "fixed_asset":
        adds = [x for x in rows if x["cents"] > 0]
        if adds:
            p.update(status="exception", support="Purchase evidence and a depreciation schedule", detail=f"{len(adds)} addition{'s' if len(adds) != 1 else ''} this month ({_m(sum(x['cents'] for x in adds))}): each needs its invoice and a depreciation schedule.")
            out.append(_f("asset_addition", f"{a}:{snap['end']}", "review", f"{a}: {_m(sum(x['cents'] for x in adds))} of additions need a depreciation schedule",
                          "; ".join(f"{_d(x['date'])} {x['what']} {_m(x['cents'])}" for x in adds[:6]) + ". Propose the schedule (cost, placed in service, life) in the Client file.",
                          account=a, amount=sum(x["cents"] for x in adds), refs=[f"ledger:{x['txn']}" for x in adds[:20]]))
        else:
            p.update(status="info" if not closing else "tied", support="The asset register" if closing else None, detail="No additions or disposals this month." if closing else "No balance.")
        return
    if closing == 0 and not rows:
        p.update(status="info", support="No balance", detail="Nothing in it.")
        return
    p.update(status="unsupported", support="Nothing in the evidence",
             detail=f"{_m(abs(closing))} at the month end with no schedule, statement or document behind it. Say what supports it, or ask the client.")
    if not any(f["check"] == "unsupported_balance" for f in mine):
        out.append(_unsupported(a, closing, "a schedule, a statement or a document", snap))


def _unsupported(a, closing, what, snap):
    return _f("unsupported_balance", f"{a}:{snap['period']}", "review", f"{a}: {_m(abs(closing))} with nothing to support it",
              f"The balance has no evidence behind it: {what}. Say what supports it (it's kept with the workpaper), or ask the client.",
              account=a, amount=closing, who="reviewer")


# ------------------------------------------------------------------ the cash flow statement (indirect method, from the balances)
OPERATING = ("receivable", "payable", "clearing", "prepaid", "other_asset", "other_liability", "payroll_liability", "tax_liability", "deferred_revenue",
             "card", "accumulated_depreciation")
INVESTING = ("fixed_asset",)
FINANCING = ("loan", "equity", "opening_balance_equity", "retained_earnings")


def cash_flow(snap, t, statements):
    """Net income, then the change in every non-cash balance-sheet account, grouped: operating, investing, financing. The
    change in cash it arrives at is checked against the bank accounts' own movement."""
    pl = statements["profit_and_loss"]
    groups = {"operating": [], "investing": [], "financing": []}
    cash = 0
    for a in sorted(set(snap["tb"]) | set(snap["prior_tb"])):
        typ = t.get(a)
        if not typ or typ in read.PL:
            continue
        change = snap["tb"].get(a, 0) - snap["prior_tb"].get(a, 0)
        kind = kind_of(a, typ)
        if kind == "bank":
            cash += change
            continue
        if not change:
            continue
        if kind == "retained_earnings" and snap.get("fy_start") != snap.get("prior_fy_start"):
            continue                                   # the year's roll of last year's profit, not a cash movement
        row = {"account": a, "cents": -change}         # an asset rising uses cash; a liability or equity rising provides it
        (groups["operating"] if kind in OPERATING else groups["investing"] if kind in INVESTING else groups["financing"]).append(row)
    net = pl["net_month"]
    op = net + sum(r["cents"] for r in groups["operating"])
    inv = sum(r["cents"] for r in groups["investing"])
    fin = sum(r["cents"] for r in groups["financing"])
    return {"net_income": net, "operating": groups["operating"], "operating_total": op, "investing": groups["investing"], "investing_total": inv,
            "financing": groups["financing"], "financing_total": fin, "net_change": op + inv + fin, "cash_change": cash,
            "ties": op + inv + fin == cash, "cash_opening": sum(v for a, v in snap["prior_tb"].items() if t.get(a) == "Bank"),
            "cash_closing": sum(v for a, v in snap["tb"].items() if t.get(a) == "Bank")}
