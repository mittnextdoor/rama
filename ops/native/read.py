"""Read the ledger into a snapshot: everything the close looks at, as of one moment, with a fingerprint.

A reviewer signs the month on a snapshot's fingerprint. A later read that differs (someone edited QuickBooks, a sync
arrived late) has a different fingerprint, so a sign-off can never silently cover books it didn't see."""
import calendar
import hashlib
import json
from datetime import date, timedelta

BANKISH = {"Bank", "Credit Card"}
PL = {"Income", "Other Income", "Cost of Goods Sold", "Expense", "Other Expense"}
LOOKBACK_DAYS = 92                 # register lines read before the month, so earlier outstanding items are seen


def month_bounds(period):
    y, m = int(period[:4]), int(period[5:7])
    return f"{period}-01", f"{period}-{calendar.monthrange(y, m)[1]:02d}"


def fy_start(as_of, first_month=1):
    y = int(as_of[:4]) - (1 if int(as_of[5:7]) < first_month else 0)
    return f"{y}-{first_month:02d}-01"


def _day_before(d):
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def fingerprint(snap):
    # what the sign-off stands on: the balances, the closing date, every line of the month (with its date and number), and
    # the open invoices, bills and undeposited payments (docs/104 A02: a date change or an application must invalidate it)
    body = {"tb": snap["tb"], "close_date": snap.get("close_date"),
            "month": sorted((x["txn_id"], x["account"], x["cents"], x["date"], x.get("doc_number") or "") for x in snap["lines"] if x["date"] >= snap["start"]),
            "open": sorted((k, o["id"], o["open"]) for k in ("open_invoices", "open_bills") for o in snap.get(k) or []),
            "undeposited": sorted((u["entity"], u["id"], u["amount"]) for u in snap.get("undeposited") or [])}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def snapshot(adapter, period, *, first_month=1, read_from=None):
    """The month as the ledger has it. read_from: the earliest day register lines are needed from (the first statement
    the close ties); by default a quarter before the month."""
    start, end = month_bounds(period)
    prior_end = _day_before(start)
    read_from = min(read_from or start, (date.fromisoformat(start) - timedelta(days=LOOKBACK_DAYS)).isoformat())
    chart = adapter.chart()
    lines = adapter.gl_lines(read_from, end)
    snap = {
        "period": period, "start": start, "end": end, "read_from": read_from,
        "fy_start": fy_start(end, first_month), "prior_fy_start": fy_start(prior_end, first_month), "basis": getattr(adapter, "method", None),
        "chart": chart,
        "tb": adapter.trial_balance(end, fy_start(end, first_month)),
        "prior_tb": adapter.trial_balance(prior_end, fy_start(prior_end, first_month)),
        "lines": lines,
        "open_invoices": adapter.open_items("Invoice", end),
        "open_bills": adapter.open_items("Bill", end),
        "undeposited": adapter.undeposited(end) if hasattr(adapter, "undeposited") else [],
        "close_date": adapter.close_date(),
        "source": getattr(adapter, "label", "ledger"),
    }
    snap["fingerprint"] = fingerprint(snap)
    return snap


def types(snap):
    return {a["name"]: a["type"] for a in snap["chart"]}


def balance_at(snap, account, day):
    """An account's balance at a day inside the read window: the month-end balance less what came after the day."""
    after = sum(x["cents"] for x in snap["lines"] if x["account"] == account and x["date"] > day)
    return snap["tb"].get(account, 0) - after


def month_activity(snap):
    """{account: debit-positive change in the month} (income and expense: the month's amounts)."""
    t = types(snap)
    out = {}
    first_month = snap.get("fy_start") != snap.get("prior_fy_start")
    for a in set(snap["tb"]) | set(snap["prior_tb"]):
        if t.get(a) in PL and first_month:
            out[a] = snap["tb"].get(a, 0)                  # the first month of the fiscal year: year to date is the month
        else:
            out[a] = snap["tb"].get(a, 0) - snap["prior_tb"].get(a, 0)
    return {a: v for a, v in out.items() if v}


def statements(snap):
    """Balance sheet and profit and loss, as the ledger reports them (cents, each in its natural sign)."""
    t = types(snap)
    act = month_activity(snap)
    groups = {"Asset": [], "Liability": [], "Equity": []}
    cls = {a["name"]: a.get("classification") for a in snap["chart"]}
    for a, v in sorted(snap["tb"].items()):
        if t.get(a) in PL:
            continue
        c = cls.get(a) or ("Asset" if v > 0 else "Liability")
        groups.setdefault(c, []).append({"account": a, "type": t.get(a), "amount": v if c == "Asset" else -v})
    ytd_income = -sum(v for a, v in snap["tb"].items() if t.get(a) in PL)
    groups["Equity"].append({"account": "Net income (year to date)", "type": "Equity", "amount": ytd_income})
    pl = []
    for a in sorted(a for a in set(act) | {a for a in snap["tb"] if t.get(a) in PL} if t.get(a) in PL):
        sign = -1 if t[a] in ("Income", "Other Income") else 1
        pl.append({"account": a, "type": t[a], "month": sign * act.get(a, 0), "ytd": sign * snap["tb"].get(a, 0)})
    tot = lambda rows: sum(r["amount"] for r in rows)                                   # noqa: E731
    inc = [r for r in pl if r["type"] in ("Income", "Other Income")]
    cost = [r for r in pl if r["type"] not in ("Income", "Other Income")]
    out = {"balance_sheet": {"assets": groups["Asset"], "liabilities": groups["Liability"], "equity": groups["Equity"],
                             "total_assets": tot(groups["Asset"]), "total_liabilities": tot(groups["Liability"]),
                             "total_equity": tot(groups["Equity"])},
           "profit_and_loss": {"income": inc, "expenses": cost,
                               "net_month": sum(r["month"] for r in inc) - sum(r["month"] for r in cost),
                               "net_ytd": sum(r["ytd"] for r in inc) - sum(r["ytd"] for r in cost)}}
    from . import workpapers
    out["cash_flow"] = workpapers.cash_flow(snap, t, out)
    return out


def refresh(adapter, prev, accounts):
    """The snapshot again after a few known changes: the trial balances, open items and closing date read anew, and the
    register re-read only for the accounts the changes touched (a real company has hundreds of accounts: docs/102,
    decision 4). The sign-off always compares with a full read, so a refresh can never be what gets signed blind."""
    accounts = {a for a in accounts if a}
    keep = [x for x in prev["lines"] if x["account"] not in accounts]
    snap = dict(prev, tb=adapter.trial_balance(prev["end"], prev["fy_start"]),
                prior_tb=adapter.trial_balance(_day_before(prev["start"]), prev["prior_fy_start"]),
                lines=keep + adapter.gl_lines(prev["read_from"], prev["end"], accounts),
                open_invoices=adapter.open_items("Invoice", prev["end"]), open_bills=adapter.open_items("Bill", prev["end"]),
                undeposited=adapter.undeposited(prev["end"]) if hasattr(adapter, "undeposited") else [],
                close_date=adapter.close_date(), chart=adapter.chart())
    snap["lines"].sort(key=lambda x: (x["date"], str(x["txn_id"])))
    snap["fingerprint"] = fingerprint(snap)
    snap["refreshed"] = sorted(accounts)
    return snap
