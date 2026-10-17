"""Bob's month-end close at the engine level, for the evaluation runner and anything else without the product database:
the same loop product/nativeclose.run_job runs for a client (read the ledger, read the evidence, tie and check, ask the
classifier about the unexplained, apply the fixes Bob can cite, read again, up to MAX_ROUNDS), on an adapter and an
engine scope. Deterministic code does every calculation; the model only ever suggests an account, with citations.

close_month() never sees an expectation: the verifier (bob/eval/expect.py) runs afterwards on what it returns."""
from ops.native import checks, evidence, fixes, read
from ops.native.reconcile import register
from product.nativeclose import MAX_ATTEMPTS, MAX_ROUNDS, _already_there
from . import classify
from . import trace as BT


def _evidence(scope, period):
    return {"statements": evidence.statements(scope), "lines": evidence.lines(scope), "client_chart": evidence.client_chart(scope),
            "lenders": evidence.lender_statements(scope, period), "payroll": evidence.payroll(scope, period)}


def _check(ad, scope, inputs, period, label):
    with BT.step(f"read_ledger {label}", "tool", {"period": period, "read_from": inputs["books_start"]}) as st:
        snap = read.snapshot(ad, period, read_from=inputs["books_start"])
        st.out({"fingerprint": snap["fingerprint"], "lines": len(snap["lines"]), "accounts": len(snap["chart"]),
                "open_invoices": len(snap.get("open_invoices") or []), "open_bills": len(snap.get("open_bills") or [])})
    with BT.step(f"read_documents {label}", "retrieval", {"period": period}) as st:
        ev = _evidence(scope, period)
        st.out({"statements": [{"ref": s["ref"], "end": s["end"], "closing": s["closing"]} for s in ev["statements"]],
                "lines": {k: len(v) for k, v in ev["lines"].items()}, "payroll_runs": len(ev["payroll"]), "lender_statements": len(ev["lenders"])})
    with BT.step(f"tie_and_check {label}", "chain", {"statements": len(ev["statements"]), "rules": len(inputs["rules"]), "schedules": len(inputs["schedules"])}) as st:
        res = checks.run(snap, ev, account_map=inputs["account_map"], books_start=inputs["books_start"], rules=inputs["rules"], schedules=inputs["schedules"])
        st.out({"findings": len(res["findings"]), "blockers": sum(1 for f in res["findings"] if f["severity"] == "blocker"),
                "reconciliations": {r["account"]: r["difference"] for r in res["recons"]}, "auto_fixes": sum(1 for f in res["findings"] if (f.get("fix") or {}).get("auto")),
                "workpapers": {k: sum(1 for w in res.get("workpapers") or [] if w["status"] == k) for k in ("tied", "exception", "unsupported", "excused", "info")}})
    return snap, res


def close_month(ad, scope, inputs, *, may_write=True, ask_model=True, client_code="BOB"):
    """Returns {first, final, snapshot, statements, applied, failed, model_called, rounds}."""
    period = inputs["period"]
    snap, res = _check(ad, scope, inputs, period, "initial")
    first = {"findings": [dict(f) for f in res["findings"]], "recons": res["recons"]}
    model_called = False
    if ask_model and classify.available()[0]:
        model_called = True
        classify.ask(snap, res, rules=inputs["rules"], month=period)
    applied, failed, tried = [], [], {}
    rounds = 0
    for _ in range(MAX_ROUNDS):
        todo = []
        for f in res["findings"]:
            fx = f.get("fix")
            if not fx or not fx.get("auto") or not may_write:
                continue
            state = tried.get(f["key"])
            if state == "done":
                continue
            if isinstance(state, int) and state >= MAX_ATTEMPTS:     # tried enough: a person decides, with the error shown
                f["fix"] = dict(fx, auto=False)
                f["who"] = "reviewer"
                continue
            fx = dict(fx, _register_ids=[r["txn_id"] for r in register(snap["lines"], fx.get("account"))] if fx.get("account") else [])
            todo.append((f, fx))
        if not todo:
            break
        rounds += 1
        for f, fx in todo:
            with BT.step(f"apply_fix {fx['kind']}", "tool", {"kind": fx["kind"], "account": fx.get("account"), "to": fx.get("to"), "from": fx.get("from"),
                                                             "line": fx.get("line"), "txn_id": fx.get("txn_id"), "citations": fx.get("citations"), "why": fx.get("why")}) as st:
                try:
                    if _already_there(ad, fx):
                        raise fixes.FixError("QuickBooks already has an entry for this line now: nothing sent")
                    out = fixes.apply(ad, fx, client_code)
                except Exception as e:                    # noqa: BLE001  (recorded; the finding stays open for a person)
                    tried[f["key"]] = (tried.get(f["key"]) or 0) + 1
                    failed.append({"key": f["key"], "kind": fx["kind"], "error": str(e)[:500]})
                    st.error(str(e))
                    continue
                tried[f["key"]] = "done"
                applied.append({"key": f["key"], "check": f["check"], "kind": fx["kind"], "to": fx.get("to"), "account": fx.get("account"),
                                "line": fx.get("line"), "citations": fx.get("citations") or [], "model": bool(fx.get("model")),
                                "entity": out["entity"], "external_id": out["external_id"], "effect": out["effect"]})
                st.out({"entity": out["entity"], "external_id": out["external_id"], "effect": out["effect"]})
        snap, res = _check(ad, scope, inputs, period, f"after round {rounds}")
    with BT.step("prepare_statements", "tool", {"period": period}) as st:
        statements = read.statements(snap)
        bs = statements["balance_sheet"]
        st.out({"net_income": statements["profit_and_loss"]["net_month"], "total_assets": bs["total_assets"],
                "balances": bs["total_assets"] == bs["total_liabilities"] + bs["total_equity"]})
    return {"first": first, "final": res, "snapshot": snap, "statements": statements, "applied": applied, "failed": failed,
            "model_called": model_called, "rounds": rounds}
