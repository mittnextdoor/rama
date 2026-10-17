"""The verifier: what Bob did against what the case author wrote down (bob/eval/fixtures.py). It judges correctness and
the exceptions Bob left for a person, never HTTP success. Every mismatch is a sentence naming the rule broken, so a batch's
failures can be grouped by cause."""


def _match(f, want):
    fx = f.get("fix") or {}
    if f["check"] != want["check"]:
        return False
    for k, v in want.items():
        if k == "check":
            continue
        if k == "who":
            if f.get("who") != v:
                return False
        elif k in ("kind", "to", "auto"):
            if fx.get(k) != v:
                return False
    return True


def verify(result, exp):
    """[problems]: empty means the case passed."""
    problems = []
    first, final, applied = result["first"]["findings"], result["final"], result["applied"]
    # 1. the findings a careful bookkeeper raises on the first read
    for want in exp["findings"]:
        if not any(_match(f, want) for f in first):
            near = [f for f in first if f["check"] == want["check"]]
            got = (" (raised as " + ", ".join(f"{(f.get('fix') or {}).get('kind')} to {(f.get('fix') or {}).get('to')} auto={(f.get('fix') or {}).get('auto')} who={f['who']}"
                                                for f in near[:3]) + ")") if near else " (not raised at all)"
            problems.append(f"missing finding: {want}{got}")
    # 2. what Bob wrote on its own: exactly the expected kinds, every one cited; model suggestions allowed only where the author said so
    allowed_model = set(exp.get("model_may_book") or [])
    deterministic = []
    for a in applied:
        desc = str((a.get("line") or {}).get("description") or "")
        if a.get("model") and desc in allowed_model:
            continue
        deterministic.append(a)
        if not a.get("citations"):
            problems.append(f"uncited write: {a['kind']} to {a.get('to')} ({desc})")
    got, want = sorted(a["kind"] for a in deterministic), sorted(exp["writes"])
    if got != want:
        problems.append(f"writes: Bob made {got}, expected {want}")
    for forbid in exp.get("forbid_writes") or []:
        for a in applied:
            desc = str((a.get("line") or {}).get("description") or "")
            if a["kind"] == forbid["kind"] and (not forbid.get("to") or a.get("to") == forbid["to"]) and (not forbid.get("description") or desc == forbid["description"]):
                problems.append(f"forbidden write: {a['kind']} to {a.get('to')} for '{desc}'")
    # 3. the accounts that must tie after Bob's changes, and the differences that must stay (never forced to balance)
    diffs = {r["account"]: r["difference"] for r in final["recons"]}
    for acct in exp["ties"]:
        if acct not in diffs:
            problems.append(f"{acct} wasn't reconciled")
        elif diffs[acct] != 0:
            problems.append(f"{acct} doesn't tie: difference {diffs[acct]} cents")
    for acct, d in (exp.get("difference") or {}).items():
        if diffs.get(acct) != d:
            problems.append(f"{acct}: expected a reconciliation difference of {d} cents to remain, got {diffs.get(acct)}")
    # 4. the exceptions left for a person: exactly the expected blockers, by check
    open_blockers = sorted({f["check"] for f in final["findings"] if f["severity"] == "blocker"})
    if open_blockers != sorted(exp["open"]):
        problems.append(f"open blockers after Bob: {open_blockers}, expected {sorted(exp['open'])}")
    reviews = {f["check"] for f in final["findings"] if f["severity"] == "review"}
    for check in exp.get("review") or []:
        if check not in reviews:
            problems.append(f"missing review item after Bob: {check}")
    # 5. invariants: the statements balance; a failed fix is a person's now, not a silent retry forever
    bs = result["statements"]["balance_sheet"]
    if bs["total_assets"] != bs["total_liabilities"] + bs["total_equity"]:
        problems.append("the balance sheet doesn't balance")
    for f in result["failed"]:
        problems.append(f"fix failed: {f['kind']} ({f['error'][:120]})")
    return problems


def unresolved(final):
    """What a person still has to look at: blockers and review items, by check."""
    out = {}
    for f in final["findings"]:
        if f["severity"] in ("blocker", "review"):
            out[f["check"]] = out.get(f["check"], 0) + 1
    return out
