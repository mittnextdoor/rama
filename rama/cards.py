"""The card writer: one OpenAI Agents SDK run per fired rule, the model reached through Nicrron. The agent fetches the
rule's facts with a tool (figures already formatted by code) and words one card. Two output guardrails check every card:

  numbers_match_rule  every number in the card is one of the rule's computed figures, thresholds or dates;
  no_investment_advice a blocklist of prescriptive words, then a classifier agent (also through Nicrron) that confirms
                       the card only describes exposure.

A card that trips a guardrail is rewritten once with the reasons; if it trips again it is dropped and logged. The model
never computes: every figure on a card comes from rules.py."""
import asyncio
import json
import os
import re

from bob import config as bob_config

DISCLOSURE = ("Risk analytics based on your fund's reported data and third-party market data as of the dates shown. "
              "Estimates depend on stated assumptions. Not investment advice.")
HANDOFF = ("RAMA provides risk analysis only. Decisions about this investment sit with you and your advisers; for questions "
           "about the fund, contact the GP's investor relations team.")
BLOCKLIST = re.compile(r"\b(should|shouldn't|recommend\w*|advis\w*|buy|sell|hold|holding off|commit|redeem\w*|rebalanc\w*|reduce|increase|"
                       r"trim|exit|divest\w*|overweight|underweight|consider|must|ought|opportunit\w*|attractive|undervalued|overvalued)\b", re.I)
NUM = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _usd(x):
    return f"${x:,.1f}M"


def _x(v):
    return f"{v:.2f}x"


def facts(rule):
    """The rule's figures as display strings (the only numbers a card may use), per rule."""
    f, t = rule["figures"], rule["threshold"]
    rid = rule["id"]
    out = []
    add = lambda label, val: out.append({"label": label, "value": val})     # noqa: E731
    if rid == "R1":
        add("PIK capitalized to date, all loans", _usd(f["pik_capitalized_usd_m"]))
        add("Loans on non-accrual", (", ".join(f["non_accrual_loans"]) or "none") + f" ({_usd(f['non_accrual_usd_m'])})")
        add("Fund NAV", _usd(f["nav_usd_m"]))
        add("PIK + non-accrual as a share of NAV", _pct(f["ratio_of_nav"]))
        add("LP's PIK / non-accrual watch limit", _pct(t["pik_nonaccrual_watch"], 0))
    elif rid == "R2":
        add("Largest look-through tenant", f["top_tenant"])
        add("Look-through exposure", _usd(f["look_through_usd_m"]))
        add("Share of fund loans", _pct(f["share_of_loans"]))
        add("LP's single-tenant cap", _pct(t["single_tenant_cap"], 0))
    elif rid == "R3":
        add("Tenant proxy", rule["subject"].replace("Tenant proxy ", ""))
        add("S&P issuer rating", f.get("rating"))
        add("Outlook", f.get("outlook"))
        add("Last rating action", f"{f.get('last_action')} on {f.get('action_date')}")
        add("Days since the action", str(f.get("days_since_action")))
        add("Fund look-through exposure to this tenant", _usd(f.get("exposure_usd_m") or 0))
        add("Share of fund loans", _pct(f.get("share_of_loans") or 0))
        add("Window (default)", f"{t['window_days']} days")
    elif rid == "R4":
        ev = f["events"][0]
        add("Event", ev["headline"])
        add("Date", ev["date"])
        add("Category", ev["category"])
        add("Fund look-through exposure to this tenant", _usd(ev["exposure_usd_m"]))
        add("Loans", ", ".join(ev["loans"]))
    elif rid == "R5":
        add("Loan L2 drawn principal", _usd(f["drawn_usd_m"]))
        add("Re-estimated GPU collateral value", _usd(f["re_estimated_value_usd_m"]))
        add("Re-estimated LTV", _pct(f["ltv"]))
        add("LTV at origination", _pct(t["ltv_at_origination"], 0))
        add("LTV covenant", _pct(t["ltv_covenant"], 0))
        add("H100 rental midpoint now", f"${f['rate_now_mid_usd_hr']:.2f}/hr")
        add("Rental rate at appraisal", f"${f['rate_at_appraisal_usd_hr']:.2f}/hr")
    elif rid == "R7":
        for r in [x for x in f["loans"] if x.get("fires")]:
            add(f"Loan {r['loan']} (proxy {r['proxy']}) months to maturity", f"{r['months_to_maturity']}")
            add(f"Loan {r['loan']} proxy stress", "; ".join(r["stress"]))
            add(f"Loan {r['loan']} principal", _usd(r["principal_usd_m"]))
            bv = r.get("borrower_verified")
            if bv and bv.get("net_debt_ebitda_x") is not None:
                add(f"Loan {r['loan']} borrower net debt/EBITDA (RAMA close, run-rate)" + ("" if bv["verified"] else " (not yet verified)"),
                    _x(bv["net_debt_ebitda_x"]))
        add("Maturity window (default)", f"{t['maturity_months']} months")
    elif rid == "R11":
        for d in f["divergent"]:
            add(f"Loan {d['loan']} (proxy {d['proxy']})", f"S&P {d['external']}; GP grade {d['gp_grade']}")
        add("Loans affected", str(f["count"]))
        add("Principal affected", _usd(f["exposure_usd_m"]))
    elif rid == "R12":
        add("Unfunded commitment", _usd(f["unfunded_usd_m"]))
        add("Expected calls, next 12 months", _usd(f["calls_12m_usd_m"]))
        add("Expected distributions, next 12 months", _usd(f["distributions_12m_usd_m"]))
        add("Net calls, next 12 months", _usd(f["net_calls_12m_usd_m"]))
        add("LP's liquidity floor", _usd(t["liquidity_floor_usd_m"]))
    elif rid == "R13":
        add("Facility drawn", _usd(f["drawn_usd_m"]))
        add("Borrowing base", _usd(f["borrowing_base_usd_m"]))
        add("Headroom", _pct(f["headroom"]))
        add("Headroom floor (default)", _pct(t["headroom_min"], 0))
    elif rid == "R14":
        for x in [x for x in f["tests"] if x["headroom"] < t["headroom_min"] and x["verified"] is not False][:3]:
            add(f"Loan {x['loan']} {x['test']}", f"{_x(x['actual_x'])} against {_x(x['limit_x'])}")
            add(f"Loan {x['loan']} {x['test']} headroom", _pct(x["headroom"]))
        add("Headroom floor (default)", _pct(t["headroom_min"], 0))
    return out


def allowed_numbers(rule):
    text = " ".join([rule["id"], rule["name"], rule["subject"]] + [f"{x['label']} {x['value']}" for x in facts(rule)]
                    + [f"{i.get('label', '')} {i.get('as_of', '')}" for i in rule["inputs"]])
    return {n.replace(",", "") for n in NUM.findall(text)}


def check_numbers(text, rule):
    allowed = allowed_numbers(rule)
    bad = sorted({n for n in (x.replace(",", "") for x in NUM.findall(text)) if n not in allowed})
    return bad


def _model():
    from openai import AsyncOpenAI
    from agents import OpenAIChatCompletionsModel
    bob_config.load_dotenv()
    n = bob_config.nicrron()
    if not n["key"]:
        raise RuntimeError("NICRRON_API_KEY is not set")
    return OpenAIChatCompletionsModel(model=n["model"], openai_client=AsyncOpenAI(base_url=n["base_url"], api_key=n["key"])), n["model"]


WRITER_INSTRUCTIONS = """You write one risk card for a limited partner (LP) of a private credit fund.
Call the get_rule_facts tool first. Use only the facts it returns, copying every number exactly as written (same digits,
same units). Never calculate, round or estimate anything yourself.
Describe exposure and how it compares with the threshold. A conditional "if ..., then ..." statement is allowed only
when both parts are facts. Never tell the reader what to do: no recommendations, no buy/sell/hold/commit/redeem/rebalance/
reduce/increase, no "should" or "consider", no forecasts of returns, no rankings of funds or products.
Answer with JSON only: {"title": "<sentence case, at most 8 words, no rule number, never the word 'fired'>",
"body": "<two or three plain sentences; do not list sources, they are shown beside the card>"}"""

COMPLIANCE_INSTRUCTIONS = """You check one risk card shown to an investor. Answer with JSON only:
{"descriptive": true|false, "reason": "<short>"}. "descriptive" is false if the card recommends, suggests or implies any
action (buying, selling, holding, committing, redeeming, rebalancing, reducing, increasing, considering an action), ranks
funds or products, or forecasts returns. Describing exposure, thresholds and conditional consequences is descriptive."""


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("the answer had no JSON object")
    return json.loads(m.group(0))


async def _classify(text, model):
    from agents import Agent, Runner
    agent = Agent(name="rama-compliance", instructions=COMPLIANCE_INSTRUCTIONS, model=model)
    r = await Runner.run(agent, text)
    try:
        d = _parse(r.final_output)
        return bool(d.get("descriptive")), str(d.get("reason") or "")[:200]
    except (ValueError, json.JSONDecodeError):
        return False, "the compliance check didn't answer in the expected form"


async def check_card(card_text, rule, model):
    """[(check, passed, detail)] for one card's text: numbers, blocklist, classifier."""
    out = []
    bad = check_numbers(card_text, rule) if rule else []
    out.append(("numbers_match_rule", not bad, ("numbers not computed by the rule: " + ", ".join(bad)) if bad else "every number is a rule output"))
    hits = sorted({m.group(0).lower() for m in BLOCKLIST.finditer(card_text)})
    out.append(("advice_blocklist", not hits, ("prescriptive words: " + ", ".join(hits)) if hits else "no prescriptive words"))
    ok, why = await _classify(card_text, model)
    out.append(("advice_classifier", ok, why or ("descriptive" if ok else "not descriptive")))
    return out


async def _write_one(rule, model, model_id):
    from agents import Agent, Runner, function_tool, GuardrailFunctionOutput, output_guardrail
    from agents.exceptions import OutputGuardrailTripwireTriggered
    rule_facts = facts(rule)

    @function_tool
    def get_rule_facts() -> str:
        """The rule's computed facts, thresholds, sources and as-of dates."""
        return json.dumps({"rule": f"{rule['id']} {rule['name']}", "subject": rule["subject"], "status": rule["status"],
                           "facts": rule_facts, "sources": [f"{i['source']} (as of {i['as_of']})" for i in rule["inputs"]],
                           "detail": rule.get("detail") or ""})

    checks_seen = []

    @output_guardrail(name="numbers_and_no_advice")
    async def guard(ctx, agent, output) -> GuardrailFunctionOutput:
        try:
            d = _parse(output if isinstance(output, str) else str(output))
            text = f"{d.get('title', '')}. {d.get('body', '')}"
        except (ValueError, json.JSONDecodeError):
            checks_seen.append([("format", False, "not JSON")])
            return GuardrailFunctionOutput(output_info={"format": "not JSON"}, tripwire_triggered=True)
        res = await check_card(text, rule, model)
        checks_seen.append(res)
        return GuardrailFunctionOutput(output_info={c: {"passed": p, "detail": x} for c, p, x in res},
                                       tripwire_triggered=not all(p for _, p, _ in res))

    agent = Agent(name="rama-card-writer", instructions=WRITER_INSTRUCTIONS, model=model, tools=[get_rule_facts], output_guardrails=[guard])
    prompt = f"Write the card for rule {rule['id']} ({rule['name']}) about {rule['subject']}."
    attempts, status = 0, "passed"
    for attempt in (1, 2):
        attempts = attempt
        try:
            r = await Runner.run(agent, prompt, max_turns=4)
            d = _parse(r.final_output)
            return {"title": d["title"].strip(), "body": d["body"].strip(), "attempts": attempts, "model": model_id,
                    "compliance": {"status": "passed" if attempt == 1 else "rewritten",
                                   "checks": [{"check": c, "passed": p, "detail": x} for c, p, x in checks_seen[-1]] if checks_seen else []}}
        except OutputGuardrailTripwireTriggered:
            last = checks_seen[-1] if checks_seen else []
            reasons = [x for _, p, x in last if not p]
            prompt = (f"Write the card for rule {rule['id']} ({rule['name']}) about {rule['subject']}. Your previous card was "
                      f"rejected: {'; '.join(reasons)}. Fix only that.")
            status = "blocked"
        except Exception as e:                            # noqa: BLE001  (a model failure: the card isn't published)
            return {"title": None, "body": None, "attempts": attempts, "model": model_id,
                    "compliance": {"status": "failed", "checks": [{"check": "model", "passed": False, "detail": f"{type(e).__name__}: {e}"[:300]}]}}
    last = checks_seen[-1] if checks_seen else []
    return {"title": None, "body": None, "attempts": attempts, "model": model_id,
            "compliance": {"status": status, "checks": [{"check": c, "passed": p, "detail": x} for c, p, x in last]}}


def write_cards(rules):
    """One card per fired rule. Returns [card]; dropped cards are kept with compliance status "blocked"/"failed"."""
    model, model_id = _model()
    fired = [r for r in rules if r["status"] == "fired"]

    async def main():
        return await asyncio.gather(*(_write_one(r, model, model_id) for r in fired))

    written = asyncio.run(main())
    cards = []
    for r, w in zip(fired, written):
        cards.append({"id": f"card-{r['id'].lower()}", "rule_id": r["id"], "rule_name": r["name"], "subject": r["subject"],
                      "title": w["title"], "body": w["body"], "facts": facts(r), "threshold": r["threshold"], "sources": r["inputs"],
                      "loans": r["loans"], "exposure_usd_m": r["exposure_usd_m"], "missing": r["missing"], "detail": r["detail"],
                      "model": w["model"], "attempts": w["attempts"], "compliance": w["compliance"],
                      "publishable": w["title"] is not None and w["compliance"]["status"] in ("passed", "rewritten"),
                      "review": {"status": "pending", "by": None, "at": None, "note": None}})
    return cards


def guardrail_test(text, rule):
    """A controlled test: run the same checks on a given sentence (an advisory one is blocked)."""
    model, _ = _model()
    return asyncio.run(check_card(text, rule, model))


def disclosure():
    return {"disclosure": DISCLOSURE, "handoff": HANDOFF}


del os
