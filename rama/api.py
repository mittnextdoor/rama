"""RAMA's HTTP API and web app. Run: .venv/bin/python -m rama.api [--port 8810]"""
import argparse
import os

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import borrower as B
from . import capiq, cards as C, close as CL, pipeline as P, tracing

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
app = FastAPI(title="RAMA", docs_url=None, redoc_url=None)


def _err(e, code=400):
    raise HTTPException(code, f"{type(e).__name__}: {e}")


@app.get("/api/state")
def state():
    s = P.load()
    if s.get("fund") is None and s.get("metrics"):          # the fund view as soon as the close gives L2's figures
        from . import fund as F
        s["fund"] = F.build(s["metrics"])
        s["fund_preview"] = True
    return JSONResponse({**s, "company": {"code": B.CODE, "name": B.LEGAL_NAME, "proxy": B.PROXY, "loan": B.LOAN_ID, "period": B.PERIOD},
                         "capiq": capiq.describe(), "disclosure": C.DISCLOSURE, "handoff": C.HANDOFF})


@app.post("/api/reset")
def reset():
    s = P.load()
    if s.get("busy"):
        _err(RuntimeError(f"busy: {s['busy']['task']}"), 409)
    P.reset()
    return {"ok": True}


@app.post("/api/close/run")
def close_run():
    try:
        P.run_close()
    except RuntimeError as e:
        _err(e, 409)
    return {"ok": True}


@app.post("/api/close/resolve")
def close_resolve(body: dict = Body(...)):
    try:
        P.resolve(body["key"], body["decision"])
    except KeyError as e:
        _err(e, 404)
    except RuntimeError as e:
        _err(e, 409)
    return {"ok": True}


@app.get("/api/close/files")
def close_files():
    try:
        return {"files": CL.source_files()}
    except Exception as e:                                # noqa: BLE001
        _err(e, 409)


@app.post("/api/intel/run")
def intel_run():
    try:
        P.run_intel()
    except RuntimeError as e:
        _err(e, 409)
    return {"ok": True}


@app.post("/api/cards/{card_id}/{decision}")
def card_review(card_id: str, decision: str, body: dict = Body(default={})):
    if decision not in ("approve", "reject", "reset"):
        _err(ValueError("decision is approve, reject or reset"))
    try:
        return P.review_card(card_id, decision, (body or {}).get("note"))
    except StopIteration:
        _err(KeyError(card_id), 404)
    except ValueError as e:
        _err(e)


@app.post("/api/package/approve")
def package_approve(body: dict = Body(default={})):
    return P.approve_package((body or {}).get("note"))


@app.post("/api/guardrail/test")
def guardrail(body: dict = Body(default={})):
    try:
        return P.guardrail_test((body or {}).get("text"))
    except Exception as e:                                # noqa: BLE001
        _err(e)


@app.get("/api/prism")
def prism():
    return {"doctor": tracing.doctor(), "session": CL.SESSION, "integration": "Agent Frameworks: OpenAI Agents SDK (prismtrace install)",
            "dashboard": "https://prism.blockconvey.com"}


@app.get("/api/runs/{run_id}")
def run_record(run_id: str):
    from bob import trace as BT
    try:
        rec = BT.load(run_id)
    except OSError as e:
        _err(e, 404)
    return {k: rec.get(k) for k in ("run_id", "kind", "task", "session_id", "agent_id", "started", "latency_ms", "status", "output", "models", "steps")}


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"), headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=WEB), name="web")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("RAMA_PORT") or 8810))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    tracing.install()
    import uvicorn
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
