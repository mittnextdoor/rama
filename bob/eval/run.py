"""The repeatable runner: python -m bob.eval.run --tag baseline [--only name] [--limit N] [--no-model] [--no-prism]

Builds every case (bob/eval/fixtures.py), runs Bob on it (bob/engine.py) as one traced run, verifies the outcome against
the author's expectations (bob/eval/expect.py), and writes the batch to bob/eval/results/<tag>-<bob version>.json with a
Markdown summary beside it. Each case's run goes to PRISM (when configured) with session_id = the batch id, the fixture id
and version, Bob's version, and final_status error when the case failed, so a cluster of failures with one cause shows up
in PRISM's Root Cause view and the v2 batch on the same inputs shows them gone."""
import argparse
import json
import os
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from bob import VERSION, config  # noqa: E402
from bob import classify, engine  # noqa: E402
from bob import trace as BT  # noqa: E402
from bob.eval import expect, fixtures  # noqa: E402

RESULTS = os.path.join(ROOT, "bob", "eval", "results")


def run_case(case, batch_id, *, ask_model=True, keep=False):
    econn, scope, ad, inputs, exp, folder = fixtures.build(case)
    try:
        task = (f"Close {inputs['period']} for case {case['id']} (plants: {', '.join(case['plants'])}): tie the bank and card statements to "
                "QuickBooks, fix what can be cited, build the workpapers, leave the rest for a person.")
        from rama import tracing as RT
        with RT.sdk_trace(f"Bob eval {case['id']}", batch_id, {"case": case["id"], "agent_id": "bob-close", "version": VERSION}), \
             BT.run(kind="eval", task=task, session_id=batch_id, fixture={"id": fixtures.FIXTURE_ID, "version": fixtures.FIXTURE_VERSION, "case": case["id"]},
                    meta={"case_id": case["id"], "plants": case["plants"], "batch": batch_id}, agent_id="bob-close", agent_name="Bob close") as r:
            t0 = time.monotonic()
            result = engine.close_month(ad, scope, inputs, ask_model=ask_model)
            with BT.step("verify_expected_outcome", "tool", {"case": case["id"], "checked": ["findings", "writes", "ties", "open exceptions", "invariants"]}) as st:
                problems = expect.verify(result, exp)
                left = expect.unresolved(result["final"])
                st.out({"passed": not problems, "problems": problems, "unresolved_exceptions": left})
                if problems:
                    st.error("; ".join(problems)[:1000])
            ties = {x["account"]: x["difference"] for x in result["final"]["recons"]}
            r.meta.update(passed=not problems, problems=len(problems), unresolved=sum(left.values()), writes=len(result["applied"]), ties=ties)
            papers = result["final"].get("workpapers") or []
            summary = (f"Case {case['id']}: {'PASS' if not problems else 'FAIL'}. {sum(1 for d in ties.values() if d == 0)} of {len(ties)} accounts tie; "
                       f"{len(result['applied'])} changes made with citations; {sum(left.values())} exceptions left for a person; "
                       f"{sum(1 for p in papers if p['status'] == 'tied')} of {len(papers)} workpapers tied."
                       + (" Problems: " + " | ".join(problems) if problems else ""))
            rec = r.finish(summary, status="success" if not problems else "error")
            return {"case": case["id"], "plants": case["plants"], "passed": not problems, "problems": problems, "unresolved": left,
                    "writes": [{k: a.get(k) for k in ("kind", "to", "account", "check", "model")} for a in result["applied"]],
                    "failed_fixes": result["failed"], "ties": ties, "model_called": result["model_called"], "rounds": result["rounds"],
                    "workpapers": Counter(p["status"] for p in papers), "seconds": round(time.monotonic() - t0, 2), "run_id": r.id,
                    "prism": {"received": (rec.get("prism") or {}).get("received"), "trace": ((rec.get("prism") or {}).get("trace") or {}).get("status")},
                    "steps": len(r.steps), "tool_calls": sum(1 for s in r.steps if s["step_type"] == "tool_call")}
    finally:
        econn.close()
        if not keep:
            shutil.rmtree(folder, ignore_errors=True)


def cluster(results):
    """Failures grouped by the rule broken (the text before the first colon of each problem)."""
    by = {}
    for r in results:
        for p in r["problems"]:
            key = p.split(":")[0].strip()
            if key.endswith("doesn't tie") or key.endswith("wasn't reconciled"):
                key = "an account doesn't tie"
            by.setdefault(key, []).append(r["case"])
    return {k: sorted(set(v)) for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))}


def main(argv=None):
    config.load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True, help="baseline, v2, ...")
    ap.add_argument("--only", action="append", help="run only cases whose id contains this (repeatable)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-model", action="store_true", help="don't ask the classifier even if it's configured")
    ap.add_argument("--no-prism", action="store_true", help="record locally only")
    ap.add_argument("--keep", action="store_true", help="keep each case's folder")
    a = ap.parse_args(argv)
    if a.no_prism:
        os.environ.pop("PRISM_API_KEY", None)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_id = f"eval-{a.tag}-{VERSION}-{stamp}"
    cases = fixtures.cases()
    if a.only:
        cases = [c for c in cases if any(o in c["id"] for o in a.only)]
    if a.limit:
        cases = cases[:a.limit]
    print(f"batch {batch_id}: {len(cases)} cases, fixture {fixtures.FIXTURE_ID} {fixtures.FIXTURE_VERSION}, Bob {VERSION}, "
          f"model {'off' if a.no_model else ('on' if classify.available()[0] else 'not configured: ' + str(classify.available()[1]))}, "
          f"PRISM {'on' if config.prism()['configured'] else 'off (recording locally)'}", flush=True)
    results = []
    for i, c in enumerate(cases, 1):
        r = run_case(c, batch_id, ask_model=not a.no_model, keep=a.keep)
        results.append(r)
        print(f"  {i:2d}/{len(cases)} {'PASS' if r['passed'] else 'FAIL'} {c['id']}" + ("" if r["passed"] else " — " + "; ".join(r["problems"])[:300]), flush=True)
    passed = sum(1 for r in results if r["passed"])
    out = {"batch": batch_id, "tag": a.tag, "bob_version": VERSION, "fixture": {"id": fixtures.FIXTURE_ID, "version": fixtures.FIXTURE_VERSION},
           "at": stamp, "cases": len(results), "passed": passed, "failed": len(results) - passed,
           "model_called": sum(1 for r in results if r["model_called"]), "prism_received": sum(1 for r in results if (r["prism"] or {}).get("received")),
           "unresolved_exceptions": sum(sum(r["unresolved"].values()) for r in results), "writes": sum(len(r["writes"]) for r in results),
           "clusters": cluster(results), "results": results}
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, f"{a.tag}-{VERSION}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    with open(path[:-5] + ".md", "w", encoding="utf-8") as f:
        f.write(markdown(out))
    print(f"\n{passed}/{len(results)} passed; {out['unresolved_exceptions']} exceptions left for a person across the batch; "
          f"{out['writes']} changes made; PRISM received {out['prism_received']}/{len(results)} runs.\nresults: {path}")
    for k, v in out["clusters"].items():
        print(f"  cluster ({len(v)}): {k}: {', '.join(v[:6])}{'…' if len(v) > 6 else ''}")
    return 0


def markdown(out):
    lines = [f"# Bob evaluation: {out['tag']} ({out['bob_version']})", "",
             f"Batch `{out['batch']}` on fixture `{out['fixture']['id']}` version `{out['fixture']['version']}`, {out['at']}.", "",
             f"- Cases: {out['cases']}, passed {out['passed']}, failed {out['failed']}",
             f"- Exceptions left for a person across the batch: {out['unresolved_exceptions']}",
             f"- Changes Bob made (all cited): {out['writes']}",
             f"- Runs where the model was asked: {out['model_called']}; runs PRISM confirmed receiving: {out['prism_received']}", ""]
    if out["clusters"]:
        lines += ["## Failure clusters (by the rule broken)", ""]
        for k, v in out["clusters"].items():
            lines.append(f"- **{k}** ({len(v)}): {', '.join(v)}")
        lines.append("")
    lines += ["## Cases", "", "| Case | Result | Writes | Ties | Exceptions left | Steps | PRISM run |", "|---|---|---|---|---|---|---|"]
    for r in out["results"]:
        ties = ", ".join(f"{k} {v}" for k, v in r["ties"].items())
        lines.append(f"| {r['case']} | {'pass' if r['passed'] else 'FAIL: ' + '; '.join(r['problems'])[:160]} | {', '.join(w['kind'] for w in r['writes']) or '—'} | "
                     f"{ties} | {sum(r['unresolved'].values())} | {r['steps']} | `{r['run_id']}` |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
