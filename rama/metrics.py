"""The borrower's indicators from its closed month, each with whether its evidence is verified and where it came from.

A figure is "verified" only when the evidence behind it tied in the close: cash when every bank account reconciles,
debt when the loan's workpaper ties to the lender's statement, earnings when the bank accounts tie and no statement line
is left unrecorded. An unverified figure is shown, labelled, and held back from the rules that need it."""
from . import borrower as B

M = 100_000_000
EBITDA_EXCLUDE = {"Depreciation", "Interest Expense", "Interest Expense - PIK"}


def _usd_m(cents):
    return round(cents / M, 3)


def compute(close, accepted=()):
    """accepted: finding keys a reviewer left open on purpose (an unsupported line too small to matter): they stay
    visible as exceptions but don't hold the figures back."""
    st = close["statements"]
    pl = st["profit_and_loss"]
    final = close["final"]
    recons = {r["account"]: r for r in final["recons"]}
    papers = {w["account"]: w for w in final["workpapers"]}
    open_lines = [f for f in final["findings"] if f["check"] in ("unrecorded", "pik_split") and f["key"] not in set(accepted)]
    lender_open = [f for f in final["findings"] if f["check"] in ("lender_difference", "lender_statement_missing", "lender_unmapped")]
    banks_tie = bool(recons) and all(r["difference"] == 0 for r in recons.values())

    revenue = sum(r["month"] for r in pl["income"] if r["type"] == "Income")
    opex = sum(r["month"] for r in pl["expenses"] if r["account"] not in EBITDA_EXCLUDE)
    ebitda = revenue - opex
    interest_cash = sum(r["month"] for r in pl["expenses"] if r["account"] == "Interest Expense")
    interest_pik = sum(r["month"] for r in pl["expenses"] if r["account"] == "Interest Expense - PIK")
    cash = sum(r["statement_closing"] for r in recons.values())
    debt_accounts = [B.TERM_LOAN, B.VENDOR_LOAN]
    debt = sum(-papers[a]["closing"] for a in debt_accounts if a in papers)
    lender = {x["loan"]: x for x in close.get("lenders") or []}
    l2 = lender.get(B.LOAN_ID)
    debt_tied = all(papers.get(a, {}).get("status") == "tied" for a in debt_accounts)
    earnings_ok = banks_tie and not open_lines
    interest_ok = earnings_ok and not lender_open

    ebitda_run = ebitda * 12
    net_debt = debt - cash
    total_interest = interest_cash + interest_pik
    ref_bank = [f"statement:{a}" for a in recons]
    ref_debt = [f"lender statement {x['loan']} {x['date']} (record {x['record']})" for x in lender.values()]

    def m(key, label, value, unit, verified, source, why=None):
        return {"key": key, "label": label, "value": value, "unit": unit, "verified": bool(verified), "source": source,
                "held_because": None if verified else why}

    tenants = {}
    for line in close.get("_september_lines") or []:
        for pat, t in B.TENANTS.items():
            if pat in line["description"] and line["amount_cents"] > 0:
                tenants.setdefault(t["tenant"], {"tenant": t["tenant"], "proxy": t["proxy"], "cents": 0})["cents"] += line["amount_cents"]
    tot = sum(t["cents"] for t in tenants.values()) or 1
    tenant_mix = [{"tenant": t["tenant"], "proxy": t["proxy"], "share": round(t["cents"] / tot, 4), "usd_m": _usd_m(t["cents"])}
                  for t in sorted(tenants.values(), key=lambda t: -t["cents"])]

    out = [
        m("revenue_month", "Revenue (September)", _usd_m(revenue), "USD m", earnings_ok, ref_bank,
          "a bank line is still unrecorded" if banks_tie else "a bank account doesn't tie"),
        m("ebitda_month", "EBITDA (September)", _usd_m(ebitda), "USD m", earnings_ok, ref_bank,
          "a bank line is still unrecorded, so expenses may be incomplete"),
        m("ebitda_run_rate", "EBITDA run-rate (September x 12)", _usd_m(ebitda_run), "USD m", earnings_ok, ref_bank,
          "depends on September EBITDA"),
        m("cash", "Cash (bank statements, 30 Sep)", _usd_m(cash), "USD m", banks_tie, ref_bank, "a bank account doesn't tie"),
        m("debt", "Debt (L2 + VF1, per books)", _usd_m(debt), "USD m", debt_tied, ref_debt,
          "a loan balance doesn't tie to its lender's statement"),
        m("l2_principal_lender", "Loan L2 principal (lender statement)", _usd_m(l2["closing_principal"]) if l2 else None, "USD m",
          bool(l2), ref_debt, "no lender statement"),
        m("interest_month", "Interest expense incl. PIK (September)", _usd_m(total_interest), "USD m", interest_ok, ref_bank + ref_debt,
          "interest isn't complete until the lender's statement ties"),
        m("l2_pik_to_date", "PIK capitalized on L2 to date (lender statement)", _usd_m(l2["pik_to_date"]) if l2 else None, "USD m", bool(l2), ref_debt,
          "no lender statement"),
        m("pik_share", "PIK share of L2 interest (lender statement)",
          round(l2["pik"] / (l2["pik"] + l2["interest"]), 4) if l2 and (l2["pik"] + l2["interest"]) else None, "ratio", bool(l2), ref_debt,
          "no lender statement"),
        m("net_debt_ebitda_x", "Net debt / EBITDA (run-rate)", round(net_debt / ebitda_run, 3) if ebitda_run > 0 else None, "x",
          earnings_ok and debt_tied, ref_bank + ref_debt, "earnings or debt not verified"),
        m("ebitda_interest_x", "EBITDA / interest (September)", round(ebitda / total_interest, 3) if total_interest else None, "x",
          interest_ok and debt_tied, ref_bank + ref_debt, "earnings, interest or debt not verified"),
    ]
    return {"company": close["company"], "period": B.PERIOD, "metrics": out, "tenant_mix": tenant_mix,
            "verified_count": sum(1 for x in out if x["verified"]), "total": len(out)}


def by_key(metrics):
    return {x["key"]: x for x in metrics["metrics"]}
