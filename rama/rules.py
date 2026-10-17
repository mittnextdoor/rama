"""The leading-indicator rules R1-R14 (docs/LEADING_INDICATORS.md). Deterministic: each returns its status, the figures
it computed, the threshold and where the threshold came from, and the inputs with their sources and as-of dates. A rule
whose inputs are missing or unverified says so ("not evaluated" / "held") and never estimates.

Statuses: fired (threshold crossed), clear (evaluated, not crossed), held (inputs exist but aren't verified by the close),
not_evaluated (inputs not available)."""
from datetime import date

from . import borrower as B
from . import capiq

AS_OF = capiq.AS_OF
SCALE = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D"]
NEGATIVE_ACTIONS = ("Downgrade",)
DEFAULTS = {"r3_window_days": 120, "r3_floor_rating": "BBB-", "r5_ltv": 0.80, "r7_leverage_x": 6.0, "r7_coverage_x": 2.5,
            "r7_maturity_months": 15, "r13_headroom": 0.15, "r14_headroom": 0.10, "r1_cash_vs_accrued": 0.90}

# cited facts outside Capital IQ (LEADING_INDICATORS.md): kept with their source, never presented as S&P data
EVENTS = [{"date": "2026-09-24", "proxy": "ORCL", "category": "Force majeure",
           "headline": "Oracle force majeure notice on Project Jupiter", "source": "Bloomberg / Reuters (as cited in RAMA's event register)"}]
GPU_INDEX = {"label": "On-demand H100 rental rate (non-S&P)", "peak_2024_usd_hr": [8.0, 10.0], "q2_2026_usd_hr": [1.80, 3.50],
             "source": "Spheron, citing SemiAnalysis (public tracker; not S&P data)", "as_of": "2026-06-30"}


def _days(d):
    return (date.fromisoformat(AS_OF) - date.fromisoformat(d)).days


def _months_to(d):
    a, b = date.fromisoformat(AS_OF), date.fromisoformat(d)
    return round((b - a).days / 30.4375, 1)


def _worse_or_equal(r, floor):
    return r in SCALE and SCALE.index(r) >= SCALE.index(floor)


def _src_capiq(field):
    return {"source": f"{capiq.RATINGS_SOURCE if field.startswith('sp_') else capiq.SOURCE} ({field})", "as_of": AS_OF}


def _rule(rid, name, status, *, subject, figures=None, threshold=None, inputs=None, detail="", missing=None, exposure_usd_m=None, loans=None):
    return {"id": rid, "name": name, "status": status, "subject": subject, "figures": figures or {}, "threshold": threshold or {},
            "inputs": inputs or [], "detail": detail, "missing": missing or [], "exposure_usd_m": exposure_usd_m, "loans": loans or []}


def evaluate(fund, metrics, cap):
    loans = {x["loan"]: x for x in fund["loans"]}
    total = fund["loans_total_usd_m"]
    lp = fund["lp"]
    out = []

    # R1 income quality (fund accounting)
    pik_cap = round(sum(x["pik_to_date_usd_m"] for x in fund["loans"]), 3)
    non_accrual = [x for x in fund["loans"] if x.get("non_accrual_since")]
    na = round(sum(x["principal_usd_m"] for x in non_accrual), 3)
    nav = fund["nav_usd_m"]
    ratio = round((pik_cap + na) / nav, 4)
    lim = lp["policy"]["pik_nonaccrual_watch"]
    out.append(_rule("R1", "Income quality", "fired" if ratio > lim else "clear",
                     subject="PIK and non-accrual against fund NAV, 30 Sep 2026",
                     figures={"ratio_of_nav": ratio, "pik_capitalized_usd_m": pik_cap, "non_accrual_usd_m": na, "nav_usd_m": nav,
                              "non_accrual_loans": [x["loan"] for x in non_accrual],
                              "pik_by_loan": {x["loan"]: x["pik_to_date_usd_m"] for x in fund["loans"] if x["pik_to_date_usd_m"]}},
                     threshold={"pik_nonaccrual_watch": lim, "basis": "LP policy (entered 2026-07-01)"},
                     inputs=[{"label": "L2 PIK capitalized to date", "source": "Lender statement L2, 30 Sep 2026, and the PIK election notice (RAMA close)", "as_of": "2026-09-30"},
                             {"label": "Other loans' PIK and non-accrual status", "source": "Fund loan tape (synthetic stand-ins)", "as_of": "2026-09-30"},
                             {"label": "Fund NAV", "source": "Fund records: loans + cash - facility (synthetic)", "as_of": "2026-09-30"}],
                     exposure_usd_m=round(pik_cap + na, 3),
                     loans=sorted({x["loan"] for x in fund["loans"] if x["pik_to_date_usd_m"]} | {x["loan"] for x in non_accrual})))

    # R2 tenant concentration (look-through)
    by_tenant = {}
    for x in fund["loans"]:
        for t in x["tenants"]:
            key = t["proxy"] or t["tenant"]
            by_tenant.setdefault(key, {"usd_m": 0.0, "loans": []})
            by_tenant[key]["usd_m"] += x["principal_usd_m"] * t["share"]
            by_tenant[key]["loans"].append(x["loan"])
    top = max(by_tenant.items(), key=lambda kv: kv[1]["usd_m"])
    cap_ = lp["policy"]["single_tenant_cap"]
    top_share = round(top[1]["usd_m"] / total, 4)
    out.append(_rule("R2", "Tenant concentration", "fired" if top_share > cap_ else "clear", subject=f"Tenant proxy {top[0]}",
                     figures={"top_tenant": top[0], "look_through_usd_m": round(top[1]["usd_m"], 3), "share_of_loans": top_share,
                              "by_tenant": {k: round(v["usd_m"] / total, 4) for k, v in sorted(by_tenant.items(), key=lambda kv: -kv[1]["usd_m"])}},
                     threshold={"single_tenant_cap": cap_, "basis": "LP policy (entered 2026-07-01)"},
                     inputs=[{"label": "L2 tenant mix", "source": "Borrower bank statement receipts, September 2026 (RAMA close)", "as_of": "2026-09-30"},
                             {"label": "Other loans' tenants", "source": "Fund loan tape (synthetic stand-ins)", "as_of": "2026-09-30"}],
                     exposure_usd_m=round(top[1]["usd_m"], 3), loans=sorted(set(top[1]["loans"]))))

    # R3 tenant credit drift
    tenant_proxies = sorted({t["proxy"] for x in fund["loans"] for t in x["tenants"] if t["proxy"]})
    if not cap:
        out.append(_rule("R3", "Tenant credit drift", "not_evaluated", subject="Tenant proxies", missing=["Cap IQ screen snapshot"]))
    else:
        hits = []
        for p in tenant_proxies:
            row = cap.get(p)
            if not row:
                continue
            recent = row["sp_last_action"] in NEGATIVE_ACTIONS and row["sp_last_action_date"] and _days(row["sp_last_action_date"]) <= DEFAULTS["r3_window_days"]
            neg_outlook = row["sp_outlook"] in ("Negative", "Watch Neg", "CreditWatch Negative")
            low = _worse_or_equal(row["sp_rating"], DEFAULTS["r3_floor_rating"])
            if recent or neg_outlook or low:
                exp = by_tenant.get(p, {"usd_m": 0.0, "loans": []})
                hits.append({"proxy": p, "rating": row["sp_rating"], "outlook": row["sp_outlook"], "action": row["sp_last_action"],
                             "action_date": row["sp_last_action_date"], "days_since_action": _days(row["sp_last_action_date"]) if row["sp_last_action_date"] else None,
                             "exposure_usd_m": round(exp["usd_m"], 3), "loans": sorted(set(exp["loans"])),
                             "why": [w for w, c in (("downgrade within window", recent), ("negative outlook", neg_outlook), ("rated BBB- or lower", low)) if c]})
        h = hits[0] if hits else None
        out.append(_rule("R3", "Tenant credit drift", "fired" if hits else "clear", subject=f"Tenant proxy {h['proxy']}" if h else "Tenant proxies",
                         figures={"hits": hits, **({"rating": h["rating"], "outlook": h["outlook"], "last_action": h["action"],
                                                     "action_date": h["action_date"], "days_since_action": h["days_since_action"],
                                                     "exposure_usd_m": h["exposure_usd_m"], "share_of_loans": round(h["exposure_usd_m"] / total, 4)} if h else {})},
                         threshold={"window_days": DEFAULTS["r3_window_days"], "rating_floor": DEFAULTS["r3_floor_rating"], "basis": "default (LP-editable)"},
                         inputs=[{"label": "S&P issuer rating, outlook, last action", **_src_capiq("sp_rating")}],
                         missing=["PD Model Market Signals (not in license)", "rating 90 days ago (not pulled)"],
                         exposure_usd_m=h["exposure_usd_m"] if h else None, loans=h["loans"] if h else []))

    # R4 tenant / project events (cited register; Key Developments not pulled)
    ev_hits = [dict(e, exposure_usd_m=round(by_tenant.get(e["proxy"], {"usd_m": 0})["usd_m"], 3),
                    loans=sorted(set(by_tenant.get(e["proxy"], {"loans": []})["loans"]))) for e in EVENTS if e["proxy"] in by_tenant]
    e = ev_hits[0] if ev_hits else None
    out.append(_rule("R4", "Tenant / project event", "fired" if ev_hits else "clear", subject=f"Tenant proxy {e['proxy']}" if e else "Tenants",
                     figures={"events": ev_hits, **({"event_date": e["date"], "category": e["category"], "exposure_usd_m": e["exposure_usd_m"]} if e else {})},
                     threshold={"categories": "force majeure, lease amendment, delay, financing stress, rating action", "basis": "default"},
                     inputs=[{"label": e["headline"] if e else "event register", "source": e["source"] if e else "RAMA event register", "as_of": e["date"] if e else AS_OF}],
                     missing=["Key Developments screen (not pulled)"], exposure_usd_m=e["exposure_usd_m"] if e else None, loans=e["loans"] if e else []))

    # R5 GPU collateral LTV (non-S&P index)
    l2 = loans["L2"]
    col = l2["collateral"]
    now_mid = sum(GPU_INDEX["q2_2026_usd_hr"]) / 2
    value = round(col["appraisal_usd_m"] * now_mid / col["rental_rate_at_appraisal_usd_hr"], 3)
    ltv = round(l2["principal_usd_m"] / value, 4)
    lim5 = col["ltv_at_origination"]
    out.append(_rule("R5", "GPU collateral LTV", "fired" if ltv > lim5 else "clear", subject="Loan L2 collateral (GPU fleet)",
                     figures={"drawn_usd_m": l2["principal_usd_m"], "appraisal_usd_m": col["appraisal_usd_m"],
                              "rate_at_appraisal_usd_hr": col["rental_rate_at_appraisal_usd_hr"], "rate_now_mid_usd_hr": now_mid,
                              "re_estimated_value_usd_m": value, "ltv": ltv, "ltv_at_origination": col["ltv_at_origination"]},
                     threshold={"ltv_at_origination": col["ltv_at_origination"], "basis": "loan file: LTV at origination (synthetic)",
                                "ltv_covenant": col["ltv_covenant"]},
                     inputs=[{"label": GPU_INDEX["label"], "source": GPU_INDEX["source"], "as_of": GPU_INDEX["as_of"]},
                             {"label": "Drawn principal", "source": "Lender statement L2 (RAMA close)", "as_of": "2026-09-30"},
                             {"label": "Appraisal", "source": "Loan file (synthetic)", "as_of": col["appraisal_date"]}],
                     detail="Assumption: collateral value moves in proportion to the rental rate midpoint.", exposure_usd_m=l2["principal_usd_m"], loans=["L2"]))

    out.append(_rule("R6", "Contract cover", "not_evaluated", subject="Borrower contracts", missing=["backlog / RPO KPIs (not pulled)"]))

    # R7 refinancing / leverage stress (borrower proxies + the RAMA-verified borrower)
    hits, rows = [], []
    for x in fund["loans"]:
        p = x["proxy"]
        if p not in ("CRWV", "NBIS", "APLD"):
            continue
        row = (cap or {}).get(p)
        if not row:
            rows.append({"loan": x["loan"], "proxy": p, "status": "not_evaluated"})
            continue
        lev, cov = row["net_debt_ebitda_x"], row["ebitda_interest_x"]
        neg_ebitda = row["ebitda_ltm_usd_m"] is not None and row["ebitda_ltm_usd_m"] < 0
        stress = [w for w, c in ((f"net debt/EBITDA {lev:.2f}x > {DEFAULTS['r7_leverage_x']}x" if lev is not None else "", lev is not None and lev > DEFAULTS["r7_leverage_x"]),
                                 (f"EBITDA/interest {cov:.2f}x < {DEFAULTS['r7_coverage_x']}x" if cov is not None else "", cov is not None and cov < DEFAULTS["r7_coverage_x"]),
                                 ("not rated", row["sp_rating"] == "NR"), ("negative LTM EBITDA", neg_ebitda)) if c]
        months = _months_to(x["maturity"])
        verified = None
        if x.get("closed_by_rama"):
            v = x["tests"].get("net_debt_ebitda_x")
            verified = {"net_debt_ebitda_x": v, "verified": x["tests_verified"].get("net_debt_ebitda_x", False)}
        r = {"loan": x["loan"], "proxy": p, "rating": row["sp_rating"], "net_debt_ebitda_x": lev, "ebitda_interest_x": cov,
             "raw": {k: row["_raw"][k] for k in ("net_debt_ebitda_x", "ebitda_interest_x")}, "stress": stress, "maturity": x["maturity"],
             "months_to_maturity": months, "principal_usd_m": x["principal_usd_m"], "borrower_verified": verified,
             "fires": bool(stress) and months <= DEFAULTS["r7_maturity_months"]}
        rows.append(r)
        if r["fires"]:
            hits.append(r)
    h = next((r for r in hits if r["loan"] == "L2"), hits[0] if hits else None)
    out.append(_rule("R7", "Refinancing / leverage stress", "fired" if hits else "clear", subject=f"Loan {h['loan']} (proxy {h['proxy']})" if h else "Borrower loans",
                     figures={"loans": rows, **({"proxy_net_debt_ebitda_x": h["net_debt_ebitda_x"], "proxy_ebitda_interest_x": h["ebitda_interest_x"],
                                                  "months_to_maturity": h["months_to_maturity"], "principal_usd_m": h["principal_usd_m"],
                                                  "exposure_usd_m": round(sum(r["principal_usd_m"] for r in hits), 3)} if h else {})},
                     threshold={"leverage_x": DEFAULTS["r7_leverage_x"], "coverage_x": DEFAULTS["r7_coverage_x"], "maturity_months": DEFAULTS["r7_maturity_months"],
                                "basis": "default (LP-editable)"},
                     inputs=[{"label": "Net debt/EBITDA, EBITDA/interest (LTM), rating", **_src_capiq("net_debt_ebitda_x")},
                             {"label": "Loan maturities", "source": "Fund loan tape (synthetic)", "as_of": "2026-09-30"}],
                     missing=["debt maturity schedules (not pulled)", "default study (optional, not pulled)"],
                     exposure_usd_m=round(sum(r["principal_usd_m"] for r in hits), 3) if hits else None, loans=[r["loan"] for r in hits]))

    out.append(_rule("R8", "Power / construction delay", "not_evaluated", subject="Construction loans", missing=["451 facility and power data (not pulled)"]))
    out.append(_rule("R9", "Market supply pressure", "not_evaluated", subject="Collateral markets", missing=["451 data center market data (not pulled)"]))
    out.append(_rule("R10", "Valuation gap", "not_evaluated", subject="GP marks vs comparables", missing=["price history (not pulled)"]))

    # R11 rating divergence
    div = []
    for x in fund["loans"]:
        row = (cap or {}).get(x["proxy"]) if x["proxy"] else None
        if not row:
            continue
        r = row["sp_rating"]
        weak = r == "NR" or _worse_or_equal(r, "B+")
        if weak and x["gp_grade"] == "performing":
            div.append({"loan": x["loan"], "proxy": x["proxy"], "external": r, "gp_grade": x["gp_grade"], "principal_usd_m": x["principal_usd_m"]})
    out.append(_rule("R11", "Rating divergence", "fired" if div else "clear", subject=f"{len(div)} loan(s)" if div else "Loans",
                     figures={"divergent": div, "count": len(div), "exposure_usd_m": round(sum(d["principal_usd_m"] for d in div), 3)},
                     threshold={"external_at_or_below": "B+ or not rated", "while_gp_grade": "performing", "basis": "default (LP-editable)"},
                     inputs=[{"label": "S&P issuer ratings of borrower proxies", **_src_capiq("sp_rating")},
                             {"label": "GP internal grades", "source": "Fund loan tape (synthetic)", "as_of": "2026-09-30"}],
                     missing=["PD Model Market Signals (not in license)"], exposure_usd_m=round(sum(d["principal_usd_m"] for d in div), 3) if div else None,
                     loans=[d["loan"] for d in div]))

    # R12 LP liquidity
    calls = round(lp["unfunded_usd_m"] * lp["pacing"]["call_rate_12m"], 3)
    net = round(calls - lp["pacing"]["expected_distributions_12m_usd_m"], 3)
    floor = lp["policy"]["liquidity_floor_usd_m"]
    out.append(_rule("R12", "LP liquidity", "fired" if net > floor else "clear", subject=lp["name"],
                     figures={"unfunded_usd_m": lp["unfunded_usd_m"], "calls_12m_usd_m": calls, "distributions_12m_usd_m": lp["pacing"]["expected_distributions_12m_usd_m"],
                              "net_calls_12m_usd_m": net},
                     threshold={"liquidity_floor_usd_m": floor, "basis": "LP policy (entered 2026-07-01)"},
                     inputs=[{"label": "Unfunded commitment", "source": "LP capital account (synthetic)", "as_of": "2026-09-30"},
                             {"label": "Call pacing", "source": lp["pacing"]["source"], "as_of": "2026-09-30"}]))

    # R13 fund leverage headroom
    fac = fund["facility"]
    head = round((fac["borrowing_base_usd_m"] - fac["drawn_usd_m"]) / fac["borrowing_base_usd_m"], 4)
    out.append(_rule("R13", "Fund leverage headroom", "fired" if head < DEFAULTS["r13_headroom"] else "clear", subject="Fund facility",
                     figures={"drawn_usd_m": fac["drawn_usd_m"], "borrowing_base_usd_m": fac["borrowing_base_usd_m"], "headroom": head},
                     threshold={"headroom_min": DEFAULTS["r13_headroom"], "basis": "default (LP-editable)"},
                     inputs=[{"label": "Facility balance and borrowing base", "source": fac["source"], "as_of": "2026-09-30"}],
                     missing=["rates (UST, SOFR) for a rate scenario (not pulled)"]))

    # R14 covenant headroom (L2 from the RAMA close; held while its inputs aren't verified)
    l2t, l2v = l2["tests"], l2["tests_verified"]
    lev, cov = l2t.get("net_debt_ebitda_x"), l2t.get("ebitda_interest_x")
    cv = l2["covenants"]
    tests = []
    if lev is not None:
        tests.append({"loan": "L2", "test": "max net debt/EBITDA", "actual_x": lev, "limit_x": cv["max_net_debt_ebitda_x"],
                      "headroom": round((cv["max_net_debt_ebitda_x"] - lev) / cv["max_net_debt_ebitda_x"], 4), "verified": l2v.get("net_debt_ebitda_x", False)})
    if cov is not None:
        tests.append({"loan": "L2", "test": "min EBITDA/interest", "actual_x": cov, "limit_x": cv["min_ebitda_interest_x"],
                      "headroom": round((cov - cv["min_ebitda_interest_x"]) / cv["min_ebitda_interest_x"], 4), "verified": l2v.get("ebitda_interest_x", False)})
    for x in fund["loans"]:
        if x.get("closed_by_rama"):
            continue
        for ck, lim14 in x["covenants"].items():
            actual = next(iter(x["tests"].values()))
            hr = (lim14 - actual) / lim14 if ck.startswith("max") else (actual - lim14) / lim14
            tests.append({"loan": x["loan"], "test": ck.replace("_", " "), "actual_x": actual, "limit_x": lim14, "headroom": round(hr, 4), "verified": None})
    unverified = [t for t in tests if t["verified"] is False]
    tight = [t for t in tests if t["headroom"] < DEFAULTS["r14_headroom"] and t["verified"] is not False]
    status = "fired" if tight else ("held" if unverified else "clear")
    t0 = tight[0] if tight else (unverified[0] if unverified else None)
    out.append(_rule("R14", "Covenant headroom", status, subject=f"Loan {t0['loan']}: {t0['test']}" if t0 else "Loan covenants",
                     figures={"tests": tests, **({"actual_x": t0["actual_x"], "limit_x": t0["limit_x"], "headroom": t0["headroom"]} if t0 else {})},
                     threshold={"headroom_min": DEFAULTS["r14_headroom"], "basis": "default (LP-editable); covenant levels from the credit agreement"},
                     inputs=[{"label": "L2 net debt/EBITDA and coverage", "source": f"RAMA close of {B.LEGAL_NAME}, {B.PERIOD}", "as_of": "2026-09-30"},
                             {"label": "Other loans' covenant tests", "source": "Fund loan tape (synthetic stand-ins)", "as_of": "2026-09-30"}],
                     detail=("Held: L2's covenant inputs aren't verified by the close yet." if status == "held" else ""),
                     loans=sorted({t["loan"] for t in tight}) or ([t0["loan"]] if t0 else [])))
    return out
