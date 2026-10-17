"""RAMA Credit Fund I: a synthetic private debt fund lending to AI infrastructure. Six loans; L2 is the borrower RAMA
closes (its figures come from the closed books and the lender's statement); L1 and L3-L6 are synthetic stand-ins tied to
their public proxies (their figures are the fund's loan tape, not a RAMA close). One LP's policy limits, entered by the LP.
Every figure here is synthetic."""
from . import borrower as B
from . import metrics as MX

FUND = {"name": "RAMA Credit Fund I", "strategy": "Private credit: AI infrastructure", "vintage": 2025, "currency": "USD",
        "commitments_usd_m": 2000.0, "synthetic": True}

# the loan tape for the stand-ins (synthetic); L2's balance and earnings come from the close
STAND_INS = [
    {"loan": "L1", "borrower": "Summit Data Campus LLC", "kind": "Tenant-backed data center", "proxy": None, "principal_usd_m": 420.0,
     "cash_rate": 0.095, "pik_rate": 0.0, "maturity": "2029-03-31", "tenants": [{"tenant": "Hyperscaler tenant (proxy ORCL)", "proxy": "ORCL", "share": 1.0}],
     "covenants": {"min_dscr_x": 1.25}, "tests": {"dscr_x": 1.62}, "gp_grade": "performing"},
    {"loan": "L3", "borrower": "Aurora GPU Cloud B.V.", "kind": "Neocloud", "proxy": "NBIS", "principal_usd_m": 310.0,
     "cash_rate": 0.09, "pik_rate": 0.02, "maturity": "2027-06-30", "tenants": [{"tenant": "Hyperscaler tenant (proxy MSFT)", "proxy": "MSFT", "share": 0.7},
                                                                              {"tenant": "Enterprise customers", "proxy": None, "share": 0.3}],
     "covenants": {"max_net_debt_ebitda_x": 6.0}, "tests": {"net_debt_ebitda_x": 4.9}, "gp_grade": "performing", "pik_to_date_usd_m": 7.75},
    {"loan": "L4", "borrower": "Mesa Digital Campus LLC", "kind": "Developer (construction)", "proxy": "APLD", "principal_usd_m": 260.0,
     "cash_rate": 0.10, "pik_rate": 0.0, "maturity": "2028-09-30", "tenants": [{"tenant": "Hyperscaler tenant (proxy META)", "proxy": "META", "share": 1.0}],
     "covenants": {"max_ltc": 0.75}, "tests": {"ltc": 0.71}, "gp_grade": "performing", "non_accrual_since": "2026-09-01"},
    {"loan": "L5", "borrower": "Keystone Colocation Holdings", "kind": "Stabilized operator", "proxy": "DLR", "principal_usd_m": 380.0,
     "cash_rate": 0.085, "pik_rate": 0.0, "maturity": "2030-12-31", "tenants": [{"tenant": "Hyperscaler tenant (proxy MSFT)", "proxy": "MSFT", "share": 0.4},
                                                                              {"tenant": "Hyperscaler tenant (proxy AMZN)", "proxy": "AMZN", "share": 0.3},
                                                                              {"tenant": "Hyperscaler tenant (proxy GOOGL)", "proxy": "GOOGL", "share": 0.3}],
     "covenants": {"max_net_debt_ebitda_x": 6.5}, "tests": {"net_debt_ebitda_x": 5.1}, "gp_grade": "performing"},
    {"loan": "L6", "borrower": "Riverbend Build-to-Suit LLC", "kind": "Tenant-backed build-to-suit", "proxy": None, "principal_usd_m": 330.0,
     "cash_rate": 0.09, "pik_rate": 0.0, "maturity": "2031-06-30", "tenants": [{"tenant": "Hyperscaler tenant (proxy GOOGL)", "proxy": "GOOGL", "share": 1.0}],
     "covenants": {"min_dscr_x": 1.30}, "tests": {"dscr_x": 1.71}, "gp_grade": "performing"},
]

FACILITY = {"lender": "Subscription and NAV facility (synthetic)", "drawn_usd_m": 690.0, "borrowing_base_usd_m": 780.0,
            "source": "Fund's facility statement, 30 Sep 2026 (synthetic)"}
FUND_CASH_USD_M = 85.0

LP = {"id": "LP-HSTP", "name": "Hudson State Teachers' Pension (synthetic LP)", "commitment_usd_m": 250.0, "unfunded_usd_m": 95.0,
      "policy": {"pik_nonaccrual_watch": 0.05, "single_tenant_cap": 0.25, "liquidity_floor_usd_m": 40.0,
                 "entered_by": "LP", "entered_on": "2026-07-01"},
      "pacing": {"call_rate_12m": 0.60, "expected_distributions_12m_usd_m": 12.0,
                 "source": "GP's capital call pacing guidance, Q3 2026 letter (synthetic)"}}

# the six loans' public proxies for the tenants and borrowers
L2_TENANT_PROXY = {"Hyperscaler Tenant A": "ORCL", "Hyperscaler Tenant B": "MSFT", "Enterprise customers": None}


def build(metrics):
    """The fund's loans with L2 from the closed books."""
    k = MX.by_key(metrics) if metrics else {}
    l2_principal = (k.get("l2_principal_lender") or {}).get("value") or 600.0
    tenants = [{"tenant": f"{t['tenant']}" + (f" (proxy {t['proxy']})" if t["proxy"] else ""), "proxy": t["proxy"], "share": t["share"]}
               for t in (metrics or {}).get("tenant_mix") or []] or [{"tenant": "Hyperscaler Tenant A (proxy ORCL)", "proxy": "ORCL", "share": 0.6}]
    terms = B.LOAN_TERMS
    l2 = {"loan": "L2", "borrower": B.LEGAL_NAME, "kind": "Neocloud (GPU cloud)", "proxy": B.PROXY, "principal_usd_m": l2_principal,
          "cash_rate": terms["cash_rate"], "pik_rate": terms["pik_rate"], "maturity": terms["maturity"], "tenants": tenants,
          "covenants": dict(terms["covenants"]),
          "tests": {"net_debt_ebitda_x": (k.get("net_debt_ebitda_x") or {}).get("value"), "ebitda_interest_x": (k.get("ebitda_interest_x") or {}).get("value")},
          "tests_verified": {"net_debt_ebitda_x": (k.get("net_debt_ebitda_x") or {}).get("verified", False),
                             "ebitda_interest_x": (k.get("ebitda_interest_x") or {}).get("verified", False)},
          "collateral": terms["collateral"], "gp_grade": terms["gp_internal_grade"], "closed_by_rama": True,
          "pik_to_date_usd_m": (k.get("l2_pik_to_date") or {}).get("value") or 0.0,
          "source": f"RAMA close of {B.LEGAL_NAME}, {B.PERIOD}; lender statement L2"}
    loans = []
    for s in STAND_INS[:1] + [l2] + STAND_INS[1:]:
        x = dict(s)
        x.setdefault("closed_by_rama", False)
        x.setdefault("source", "Fund loan tape, 30 Sep 2026 (synthetic stand-in)")
        x.setdefault("tests_verified", {})
        x.setdefault("pik_to_date_usd_m", 0.0)
        x.setdefault("non_accrual_since", None)
        x["cash_interest_month_usd_m"] = round(x["principal_usd_m"] * x["cash_rate"] / 12, 3)
        x["pik_month_usd_m"] = round(x["principal_usd_m"] * x["pik_rate"] / 12, 3)
        loans.append(x)
    total = round(sum(x["principal_usd_m"] for x in loans), 3)
    nav = round(total + FUND_CASH_USD_M - FACILITY["drawn_usd_m"], 3)
    return {"fund": FUND, "loans": loans, "loans_total_usd_m": total, "nav_usd_m": nav, "facility": FACILITY,
            "cash_usd_m": FUND_CASH_USD_M, "lp": LP}
