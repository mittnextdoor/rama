"""The demo path through the product (MONEY TALKS 2): pick a synthetic scenario, load its source package into a new demo
client, and Bob runs the month in the existing workspace (Close tab: progress; Review tab: the workbench, the agents'
changes, the workpapers; Reports tab: the statements and the package). Every run's PRISM record is read back here.

Nothing here is new accounting: the scenarios are bob/eval/fixtures.py's, loaded exactly as a firm loads a client
(workflow.add_client, the onboarding choices, the client's statements as uploads). The company is simulated QuickBooks on
this machine; writes to a real company stay off."""
import os

from product import auth, db, engine, jobs, service, workflow
from product.errors import Conflict, Invalid
from . import config
from . import trace as BT
from .eval import fixtures


def scenarios():
    """The case list with each plant's one-line description."""
    out = []
    for c in fixtures.cases():
        out.append({"id": c["id"], "plants": [{"name": n, "about": " ".join((fixtures.PLANTS[n].__doc__ or "").strip().split())} for n in c["plants"]]})
    return out


def status():
    """What the demo environment has: hackathon mode, the model route, PRISM."""
    from product.reasoning import config as rconfig, secrets
    n, p = config.nicrron(), config.prism()
    cls = rconfig.agent("classifier")
    return {"hackathon": config.hackathon(), "bob_version": __import__("bob").VERSION,
            "nicrron": {"base_url": n["base_url"], "model": n["model"], "structured": n["structured"], "key": bool(n["key"]),
                        "classifier_enabled": bool(cls.get("enabled")), "classifier_key": secrets.credential(cls)[0] is not None},
            "prism": {"host": p["host"], "project_id": p["project_id"], "key": bool(p["key"]), "configured": p["configured"],
                      "agent_id": p["agent_id"], "runs_dir": config.runs_dir()},
            "fixture": {"id": fixtures.FIXTURE_ID, "version": fixtures.FIXTURE_VERSION, "cases": len(fixtures.cases())}}


def load(conn, ident, scenario_id, name=None):
    """Create a demo client for the scenario, connect a simulated QuickBooks company seeded with its books, upload its
    statements (January, then February) and let the agents run. Returns the client and where to look."""
    auth.require(ident, "manage_clients")
    case = next((c for c in fixtures.cases() if c["id"] == scenario_id), None)
    if case is None:
        raise Invalid("unknown scenario", field="scenario")
    short = "".join(w[0] for w in case["plants"])[:3].upper() or "BOB"
    n = conn.execute("SELECT count(*) AS n FROM clients WHERE firm_id=%s AND legal_name LIKE 'Bob demo%%'", (ident.firm_id,)).fetchone()["n"]
    legal = name or f"Bob demo {n + 1}: {', '.join(case['plants'])}"[:120]
    made = workflow.add_client(conn, ident, legal_name=legal, code=f"BOB{short}{n + 1}"[:8], data_kind="demo", first_month=fixtures.PERIOD)
    cid = made["id"]
    workflow.onboarding_choose(conn, ident, cid, "basis:accrual")
    workflow.onboarding_choose(conn, ident, cid, "fye:12-31")
    workflow.onboarding_choose(conn, ident, cid, "connect:simulated")
    conn.commit()
    with BT.step("load_source_package", "tool", {"scenario": case["id"], "plants": case["plants"]}) as st:
        c = conn.execute("SELECT * FROM clients WHERE id=%s", (cid,)).fetchone()
        econn, _ = engine.open_engine(engine.workspace(conn, c))
        try:
            from ops.qbo import SimulatedQBO
            files, extra = fixtures.source_package(case)(SimulatedQBO(econn, realm=f"SIM-{made['code']}"))
        finally:
            econn.close()
        st.out({"files": [f[1] for f in files], "schedules": len(extra["schedules"]), "rules": len(extra["rules"])})
    for r in extra["rules"]:                              # the owner's standing instruction (Netflix is personal)
        conn.execute("INSERT INTO native_rules (firm_id, client_id, pattern, account, reason, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
                     (ident.firm_id, cid, r["pattern"], r["account"], "demo scenario: the owner's standing instruction", ident.user_id))
    jan = [(nm, data) for m, nm, data in files if m == "2026-01"]
    feb = [(nm, data) for m, nm, data in files if m != "2026-01"]
    workflow.upload(conn, ident, cid, jan)                # the opening statements: onboarding proves where the books start
    conn.commit()
    jobs.drain(limit=20)
    try:                                                  # savings has no January lines to infer it from: the fixture's account map says what it is
        workflow.onboarding_choose(conn, ident, cid, "openmap:1010:Savings")
    except (Invalid, Conflict):
        pass                                              # already settled (or onboarding moved on): nothing to map
    conn.commit()
    jobs.drain(limit=20)
    for s in extra["schedules"]:                          # the approved prepaid schedule the case assumes
        _schedule(conn, ident, cid, s)
    conn.commit()
    workflow.upload(conn, ident, cid, feb, month=fixtures.PERIOD)     # February: the agents start by themselves
    conn.commit()
    return {"client_id": cid, "code": made["code"], "period_id": made["period_id"], "scenario": case["id"],
            "open": f"/firm/client/?id={cid}", "review": f"/firm/client/?id={cid}&tab=review"}


def _schedule(conn, ident, cid, s):
    from product import schedules as sch
    try:
        row = sch.propose(conn, ident, cid, kind="prepaid", debit_account=s["debit"], credit_account=s["credit"], monthly_cents=s["monthly_cents"],
                          start="2026-01", end="2026-12", total_cents=s["monthly_cents"] * 12, support="demo scenario: the annual insurance policy, 1,200.00 paid 2025-12-31")
        conn.execute("UPDATE schedules SET status='approved', approved_by=%s, approved_at=now() WHERE id=%s", (ident.user_id, row["id"]))
    except Exception as e:                                # noqa: BLE001  (the chart isn't read yet: the schedule is then a reviewer's step)
        service.event(conn, ident, "demo_schedule_skipped", client_id=cid, object_type="client", object_id=cid, detail={"why": str(e)[:300]})


def runs(conn, ident, client_id=None, limit=50):
    """The recorded Bob runs (bob/trace.py), newest first, for one client or the firm; each with PRISM's answer."""
    rows = BT.runs(limit=500)
    if client_id is not None:
        service.client(conn, ident, client_id)
        rows = [r for r in rows if (r.get("meta") or {}).get("client_id") == client_id]
    out = []
    for r in rows[:limit]:
        pr = r.get("prism") or {}
        out.append({"run_id": r["run_id"], "kind": r["kind"], "started": r["started"], "status": r["status"], "output": r.get("output"),
                    "session_id": r["session_id"], "steps": len(r["steps"]), "tool_calls": sum(1 for s in r["steps"] if s["step_type"] == "tool_call"),
                    "llm_calls": sum(1 for s in r["steps"] if s["step_type"] == "reasoning" and s.get("token_count") is not None),
                    "errors": sum(1 for s in r["steps"] if s["status"] == "error"), "latency_ms": r["latency_ms"], "models": r.get("models"),
                    "meta": {k: v for k, v in (r.get("meta") or {}).items() if k in ("client_code", "month", "case_id", "plants", "passed", "ties", "changed", "blockers")},
                    "prism": {"sent": pr.get("sent"), "received": pr.get("received"), "trace_id": ((pr.get("trace") or {}).get("body") or {}).get("id"),
                              "trace_status": (pr.get("trace") or {}).get("status"), "spans_status": (pr.get("spans") or {}).get("status"),
                              "trajectory_status": (pr.get("trajectory") or {}).get("status"), "trajectory_id": ((pr.get("trajectory") or {}).get("body") or {}).get("id")}})
    return {"runs": out, "prism": {k: v for k, v in config.prism().items() if k != "key"}}


def run_detail(run_id):
    if not run_id.startswith("bob-") or "/" in run_id or ".." in run_id:
        raise Invalid("unknown run")
    try:
        return BT.load(run_id)
    except OSError:
        raise Invalid("unknown run") from None


def evaluation():
    """The recorded evaluation batches (bob/eval/results/): baseline against v2, with the failure clusters."""
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bob", "eval", "results")
    out = []
    if os.path.isdir(d):
        import json
        for name in sorted(os.listdir(d)):
            if name.endswith(".json"):
                with open(os.path.join(d, name), encoding="utf-8") as f:
                    b = json.load(f)
                out.append({k: b[k] for k in ("batch", "tag", "bob_version", "fixture", "at", "cases", "passed", "failed", "unresolved_exceptions", "writes",
                                             "model_called", "prism_received", "clusters")}
                           | {"failed_cases": [{"case": r["case"], "problems": r["problems"], "run_id": r["run_id"]} for r in b["results"] if not r["passed"]],
                              "results": [{"case": r["case"], "passed": r["passed"], "writes": len(r["writes"]), "steps": r["steps"],
                                           "unresolved": sum(r["unresolved"].values()), "run_id": r["run_id"]} for r in b["results"]]})
    return {"batches": out}
