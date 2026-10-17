"""The workflow and its state: reset -> close (+ reviewer decisions) -> intelligence (metrics, fund view, rules, cards)
-> review (each card, or the package) -> publication to the demonstration destination. Only approved, publishable cards
are published. State is one JSON file under data/rama/; long steps run on a worker thread and the screen polls."""
import json
import os
import threading
import time
import traceback
from datetime import datetime, timezone

from . import borrower as B
from . import capiq, cards as C, close as CL, fund as F, metrics as MX, rules as R, tracing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.environ.get("RAMA_STATE") or os.path.join(ROOT, "data", "rama", "state.json")
_lock = threading.RLock()
DESTINATION_LABEL = "Demonstration destination — no live Chronograph connection."
REVIEWER = "Fund reviewer (demo)"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _blank():
    return {"stage": "ready", "busy": None, "error": None, "close": None, "metrics": None, "fund": None, "rules": None, "cards": [], "accepted": [],
            "package": {"status": "pending", "by": None, "at": None}, "destination": {"published": [], "at": None, "label": DESTINATION_LABEL},
            "events": [], "runs": [], "guardrail_tests": [], "session": CL.SESSION, "created": _now()}


def load():
    with _lock:
        try:
            with open(STATE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return _blank()


def save(s):
    with _lock:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, default=str)
        os.replace(tmp, STATE)


def _event(s, kind, text, **extra):
    s["events"].insert(0, {"at": _now(), "kind": kind, "text": text, **extra})
    s["events"] = s["events"][:80]


def _background(name, fn):
    s = load()
    if s.get("busy"):
        raise RuntimeError(f"busy: {s['busy']['task']}")
    s["busy"], s["error"] = {"task": name, "since": _now()}, None
    save(s)

    def work():
        try:
            fn()
        except Exception as e:                            # noqa: BLE001  (shown on screen; the state stays consistent)
            s2 = load()
            s2["error"] = {"task": name, "message": f"{type(e).__name__}: {e}"[:600], "trace": traceback.format_exc()[-1500:]}
            _event(s2, "error", f"{name} failed: {type(e).__name__}: {e}"[:300])
            save(s2)
        finally:
            s3 = load()
            s3["busy"] = None
            save(s3)
    threading.Thread(target=work, name=f"rama-{name}", daemon=True).start()


# ------------------------------------------------------------------ steps
def reset():
    files = CL.reset()
    s = _blank()
    s["stage"] = "books_loaded"
    s["source_files"] = files
    _event(s, "reset", f"Source package loaded for {B.LEGAL_NAME} ({B.PERIOD}): {len(files)} files")
    save(s)
    return s


def _september_lines():
    for f in CL.source_files():
        if f["name"] == f"statement_1000_lines_{B.PERIOD}.csv":
            return [{"description": r["description"], "amount_cents": int(r["amount_cents"]), "date": r["date"], "line_id": r["line_id"]} for r in f["rows"]]
    return []


def _do_close(label):
    t0 = time.monotonic()
    rec = CL.run(ask_model=True, label=label)
    rec["_september_lines"] = _september_lines()
    rec["seconds"] = round(time.monotonic() - t0, 2)
    s = load()
    s["close"] = rec
    s["metrics"] = MX.compute(rec, accepted=s.get("accepted") or [])
    s["stage"] = "closed"
    s["runs"].insert(0, {"run_id": rec["run_id"], "kind": "close", "at": _now(), "summary": rec["summary"], "steps": len(rec["steps"])})
    _event(s, "close", rec["summary"], run_id=rec["run_id"])
    for a in rec["applied"]:
        _event(s, "fix", f"Recorded {a['line']['description'] if a.get('line') else a['kind']} to {a.get('to')} with citations {', '.join(a['citations'])}")
    # intelligence built earlier is now stale
    if s.get("rules"):
        s["rules"], s["cards"], s["package"] = None, [], {"status": "pending", "by": None, "at": None}
        _event(s, "stale", "The close changed: intelligence will be rebuilt from the new close")
    save(s)


def run_close():
    if not os.path.exists(os.path.join(CL.WORK, "engine.sqlite3")):
        reset()
    _background("close", lambda: _do_close("close"))


def resolve(key, decision):
    s = load()
    f = next((x for x in (s.get("close") or {}).get("final", {}).get("findings", []) if x["key"] == key), None)
    if not f:
        raise KeyError(key)

    def go():
        CL.resolve(f, decision)
        s2 = load()
        if decision.get("action") == "leave_open":
            s2.setdefault("accepted", []).append(key)
        _event(s2, "review", f"Reviewer: {decision.get('action')} on {f['title']}")
        save(s2)
        _do_close(f"after decision on {key}")
    _background("resolve", go)


def _do_intel():
    s = load()
    if not s.get("close"):
        raise RuntimeError("close the month first")
    task = (f"Leading indicators for {F.FUND['name']} from the closed month of {B.LEGAL_NAME} ({B.PERIOD}) and the Cap IQ snapshot "
            f"as of {capiq.AS_OF}: compute rules R1-R14, word cards for the fired rules, check every card.")
    with tracing.session(CL.SESSION, "RAMA intelligence", agent_id="rama-intel", kind="intelligence", task=task,
                         meta={"fund": F.FUND["name"], "as_of": capiq.AS_OF}) as r:
        with tracing.step("read_closed_books", "retrieval", {"company": B.CODE, "period": B.PERIOD, "close_run": s["close"]["run_id"]}) as st:
            m = MX.compute(s["close"], accepted=s.get("accepted") or [])
            st.out({x["key"]: {"value": x["value"], "verified": x["verified"]} for x in m["metrics"]})
        with tracing.step("load_capiq_snapshot", "retrieval", capiq.describe()) as st:
            cap = capiq.load()
            st.out({"companies": sorted(cap), "as_of": capiq.AS_OF})
        with tracing.step("build_fund_view", "tool", {"fund": F.FUND["name"]}) as st:
            fund = F.build(m)
            st.out({"loans": [(x["loan"], x["principal_usd_m"], x["closed_by_rama"]) for x in fund["loans"]], "nav_usd_m": fund["nav_usd_m"]})
        with tracing.step("evaluate_rules", "chain", {"rules": "R1-R14"}) as st:
            rules = R.evaluate(fund, m, cap)
            for rule in rules:
                with tracing.step(f"rule {rule['id']} {rule['name']}", "tool", {"subject": rule["subject"]}) as st2:
                    st2.out({"status": rule["status"], "figures": {k: v for k, v in rule["figures"].items() if not isinstance(v, (list, dict))},
                             "missing": rule["missing"]})
            st.out({x["id"]: x["status"] for x in rules})
        cards = C.write_cards(rules)
        with tracing.step("card_guardrails", "tool", {"cards": len(cards)}) as st:
            st.out({c["rule_id"]: c["compliance"]["status"] for c in cards})
            if any(c["compliance"]["status"] in ("blocked", "failed") for c in cards):
                st.error("a card was blocked or failed and was dropped: " + ", ".join(c["rule_id"] for c in cards if not c["publishable"]))
        fired = [x["id"] for x in rules if x["status"] == "fired"]
        summary = (f"{len(fired)} of 14 rules fired ({', '.join(fired)}); {sum(1 for c in cards if c['publishable'])} card(s) ready for review; "
                   f"{sum(1 for x in rules if x['status'] == 'not_evaluated')} not evaluated for missing data; "
                   f"{sum(1 for x in rules if x['status'] == 'held')} held for unverified inputs.")
        rec = r.finish(summary, status="success")
    s = load()
    s.update(metrics=m, fund=fund, rules=rules, cards=cards, stage="intelligence", package={"status": "pending", "by": None, "at": None})
    s["runs"].insert(0, {"run_id": rec["run_id"], "kind": "intelligence", "at": _now(), "summary": summary, "steps": len(rec["steps"])})
    _event(s, "intelligence", summary, run_id=rec["run_id"])
    save(s)


def run_intel():
    _background("intelligence", _do_intel)


def review_card(card_id, decision, note=None):
    with _lock:
        s = load()
        c = next(x for x in s["cards"] if x["id"] == card_id)
        if decision == "approve" and not c["publishable"]:
            raise ValueError("this card was blocked by the guardrails and can't be published")
        c["review"] = {"status": "approved" if decision == "approve" else "rejected" if decision == "reject" else "pending",
                       "by": REVIEWER, "at": _now(), "note": note}
        _event(s, "review", f"{c['rule_id']} {c['rule_name']}: {c['review']['status']}" + (f" ({note})" if note else ""))
        save(s)
    _trace_review([card_id], decision)
    return c


def approve_package(note=None):
    with _lock:
        s = load()
        ids = []
        for c in s["cards"]:
            if c["publishable"] and c["review"]["status"] == "pending":
                c["review"] = {"status": "approved", "by": REVIEWER, "at": _now(), "note": note or "approved with the package"}
                ids.append(c["id"])
        s["package"] = {"status": "approved", "by": REVIEWER, "at": _now(), "note": note}
        _event(s, "package", f"Package approved by {REVIEWER}: {len(ids)} card(s) approved with it; "
               f"{sum(1 for c in s['cards'] if c['review']['status'] == 'rejected')} rejected card(s) stay out")
        save(s)
    _trace_review(ids, "approve_package")
    return publish()


def _trace_review(ids, decision):
    with tracing.session(CL.SESSION, "RAMA approval", agent_id="rama-review", kind="approval", task=f"Reviewer {decision}: {', '.join(ids) or 'none'}") as r:
        with tracing.step(f"reviewer_{decision}", "tool", {"cards": ids, "reviewer": REVIEWER}) as st:
            st.out({"cards": ids})
        r.finish(f"Reviewer {decision}: {len(ids)} card(s)", status="success")


def publish():
    with _lock:
        s = load()
        ready = [c for c in s["cards"] if c["review"]["status"] == "approved" and c["publishable"]]
        fund = s.get("fund") or {}
        s["destination"] = {"label": DESTINATION_LABEL, "at": _now(), "published": [
            {k: c[k] for k in ("id", "rule_id", "rule_name", "subject", "title", "body", "facts", "sources", "loans", "exposure_usd_m")} for c in ready],
            "fund": {"name": (fund.get("fund") or {}).get("name"), "nav_usd_m": fund.get("nav_usd_m"), "loans_total_usd_m": fund.get("loans_total_usd_m"),
                     "loans": [{k: x[k] for k in ("loan", "borrower", "proxy", "principal_usd_m", "maturity", "closed_by_rama")} for x in fund.get("loans") or []]},
            "lp": (fund.get("lp") or {}).get("name"), "disclosure": C.DISCLOSURE, "as_of": capiq.AS_OF, "period": B.PERIOD}
        s["stage"] = "published"
        _event(s, "publish", f"{len(ready)} approved card(s) sent to the demonstration destination (no live Chronograph connection)")
        save(s)
    with tracing.session(CL.SESSION, "RAMA publication", agent_id="rama-publish", kind="publish", task="Publish approved cards to the demonstration destination") as r:
        with tracing.step("publish_to_destination", "tool", {"destination": "Chronograph-style demonstration destination", "live_connection": False}) as st:
            st.out({"cards": [c["id"] for c in ready]})
        r.finish(f"{len(ready)} approved card(s) published to the demonstration destination", status="success")
    return s["destination"]


def guardrail_test(text=None):
    s = load()
    rule = next((x for x in s.get("rules") or [] if x["status"] == "fired"), None)
    text = text or "Oracle exposure is above your cap, so you should reduce your commitment and rebalance into safer funds."
    with tracing.session(CL.SESSION, "RAMA guardrail test", agent_id="rama-intel", kind="guardrail_test", task=f"Controlled guardrail test: {text}") as r:
        with tracing.step("guardrail_test", "tool", {"text": text}) as st:
            res = C.guardrail_test(text, rule)
            blocked = not all(p for _, p, _ in res)
            st.out({"blocked": blocked, "checks": res})
            if blocked:
                st.error("blocked: " + "; ".join(d for _, p, d in res if not p))
        r.finish(("Blocked: " if blocked else "Passed: ") + text[:200], status="error" if blocked else "success")
    s = load()
    s["guardrail_tests"].insert(0, {"at": _now(), "text": text, "blocked": blocked, "checks": [{"check": c, "passed": p, "detail": d} for c, p, d in res]})
    _event(s, "guardrail", ("Guardrail test blocked an advisory sentence" if blocked else "Guardrail test passed a sentence"))
    save(s)
    return s["guardrail_tests"][0]
