"""Every run of Bob, step by step, to PRISM by Block Convey (blockconvey.com/docs, read 2026-10-17), over the documented
HTTP endpoints with the X-PRISMtrace-Key header:

  - POST /api/traces         one record per run: the task given, the outcome, the model, latency, tokens, session_id,
                             agent_id, trace_id (our run id; re-sending returns the existing trace) and metadata;
  - POST /api/spans/ingest   the run's steps as spans (name, span_type tool|llm|agent|chain, parent_span_id, times,
                             input_text, output_text, status, error_message, model, tokens): the trajectory PRISM shows;
  - POST /api/trajectories   the same steps as an ordered trajectory with final_status success|error, the shape the
                             official prismtrace SDK (0.5.3, ClaudeAgentTracer) submits beside its spans;
  - POST /api/setup-doctor/handshake and GET /api/setup-doctor: proving the credential and the pipeline (verify()).

Identifiers travel with the run: run_id (= trace_id = the trajectory's request_id), session_id (one per client month,
or one per evaluation batch), the fixture id and version, and Bob's version. A span's status is "ok" or "error" with the
exception's text; a failed attempt (a provider retry, a fix that didn't take) is its own span, so retries are visible.

Without PRISM_API_KEY and PRISM_PROJECT_ID nothing is sent, and every run is still written to data/bob/runs/<run_id>.json
with its steps; with them, the file also carries PRISM's answers (the stored trace's id), which is the only proof a run
was received. Delivery runs on a background thread; finish() waits for it (bounded) so a job's record is complete."""
import contextlib
import contextvars
import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime, timezone

from ops.native import trace as engine_hook
from . import VERSION, config

_run = contextvars.ContextVar("bob_run", default=None)
_span = contextvars.ContextVar("bob_span", default=None)
TEXT_LIMIT = 4000
RETRY_STATUSES = (408, 429, 500, 502, 503, 504)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(x):
    if x is None:
        return None
    s = x if isinstance(x, str) else json.dumps(x, default=str, sort_keys=True)
    return s if len(s) <= TEXT_LIMIT else s[:TEXT_LIMIT - 1] + "…"


class Step:
    def __init__(self, run, name, kind, input, parent):
        self.run, self.name, self.kind, self.parent = run, name, kind, parent
        self.id = uuid.uuid4().hex[:16]
        self.t0, self.started = time.monotonic(), _now()
        self.input, self.output, self.status, self.err = input, None, "ok", None
        self.model, self.tokens_in, self.tokens_out, self.meta = None, None, None, {}

    def out(self, output=None, **meta):
        self.output = output
        self.meta.update(meta)

    def error(self, message):
        self.status, self.err = "error", str(message)[:1000]

    def llm(self, model, tokens_in=0, tokens_out=0):
        self.model, self.tokens_in, self.tokens_out = model, int(tokens_in or 0), int(tokens_out or 0)

    def span(self):
        ms = int((time.monotonic() - self.t0) * 1000)
        s = {"span_id": self.id, "parent_span_id": self.parent, "name": self.name, "span_type": self.kind, "start_time": self.started,
             "end_time": _now(), "duration_ms": ms, "input_text": _text(self.input), "output_text": _text(self.output), "status": self.status}
        if self.err:
            s["error_message"] = self.err
        if self.model:
            s.update(model=self.model, token_count_input=self.tokens_in, token_count_output=self.tokens_out)
        if self.meta:
            s["metadata"] = self.meta
        return s


class Run:
    """One execution of a workflow. Use run() to open one; inside it, step() records each real step."""

    def __init__(self, *, kind, task, session_id, fixture=None, meta=None, agent_id=None, agent_name=None):
        self.id = f"bob-{kind}-{uuid.uuid4().hex[:12]}"
        self.agent_id, self.agent_name = agent_id, agent_name   # None: PRISM_AGENT_ID / PRISM_AGENT_NAME
        self.kind, self.task, self.session_id = kind, task, session_id
        self.fixture = fixture or {}
        self.meta = dict(meta or {})
        self.started, self.t0 = _now(), time.monotonic()
        self.spans, self.steps = [], []
        self.models, self.tokens_in, self.tokens_out = [], 0, 0
        self.delivery, self.outcome, self.output = {}, None, None

    def record(self, step):
        self.spans.append(step.span())
        kind = {"llm": "reasoning", "chain": "reasoning", "agent": "reasoning"}.get(step.kind, "tool_call")
        t = {"step_type": kind, "label": step.name, "input_summary": _text(step.input)[:400] if step.input is not None else None,
             "output_summary": (_text(step.output) or "")[:400] or (step.err or ""), "duration_ms": step.span()["duration_ms"],
             "status": "success" if step.status == "ok" else "error"}
        if kind == "tool_call":
            t["tool_name"] = step.name.split(" ")[0]
        if step.model:
            t["token_count"] = step.tokens_in + step.tokens_out
            self.models.append(step.model)
            self.tokens_in += step.tokens_in
            self.tokens_out += step.tokens_out
        self.steps.append(t)

    def finish(self, output, status="success", wait=20.0):
        """The run's outcome: status success or error, output a sentence a person can read. Sends everything to PRISM
        (when configured) and writes the run's record. Returns the record. wait=0 returns at once (a request path): the
        delivery thread rewrites the record with PRISM's answers."""
        self.outcome, self.output = status, output
        self.steps.append({"step_type": "final_answer", "label": "outcome", "output_summary": _text(output)[:400], "duration_ms": 0,
                           "status": "success" if status == "success" else "error"})
        if not config.prism()["configured"]:
            self.delivery = {"sent": False, "why": "PRISMTRACE_API_KEY (or PRISM_API_KEY) and PRISMTRACE_PROJECT_ID aren't set"}
        rec = self.record_dict()
        _write(rec)
        if config.prism()["configured"]:
            done = threading.Event()
            _queue.put((self, done))
            _ensure_worker()
            done.wait(wait)
            rec = self.record_dict()
            _write(rec)
        return rec

    def record_dict(self):
        ms = int((time.monotonic() - self.t0) * 1000)
        return {"run_id": self.id, "kind": self.kind, "task": self.task, "session_id": self.session_id, "fixture": self.fixture,
                "agent_id": self.agent_id or config.prism()["agent_id"],
                "bob_version": VERSION, "started": self.started, "latency_ms": ms, "status": self.outcome, "output": self.output,
                "models": sorted(set(self.models)), "token_count_input": self.tokens_in, "token_count_output": self.tokens_out,
                "meta": self.meta, "steps": self.steps, "spans": self.spans, "prism": self.delivery}

    # ---- the three payloads, exactly the documented fields
    def trace_payload(self, p):
        return {"project_id": p["project_id"], "model": self.models[0] if self.models else "none", "trace_id": self.id,
                "input_messages": [{"role": "user", "content": self.task}], "output_message": self.output or "",
                "latency_ms": int((time.monotonic() - self.t0) * 1000), "token_count_input": self.tokens_in, "token_count_output": self.tokens_out,
                "session_id": self.session_id, "agent_id": self.agent_id or p["agent_id"], "agent_name": self.agent_name or p["agent_name"],
                "metadata": {**self.meta, "run_id": self.id, "kind": self.kind, "status": self.outcome, "bob_version": VERSION,
                             "fixture_id": self.fixture.get("id"), "fixture_version": self.fixture.get("version"), "steps": len(self.steps),
                             "tool_calls": sum(1 for s in self.steps if s["step_type"] == "tool_call"),
                             "errors": sum(1 for s in self.steps if s["status"] == "error")}}

    def spans_payload(self, p):
        return {"trace_id": self.id, "project_id": p["project_id"], "session_id": self.session_id, "spans": self.spans,
                "metadata": {"run_id": self.id, "bob_version": VERSION, "fixture_id": self.fixture.get("id"), "fixture_version": self.fixture.get("version")}}

    def trajectory_payload(self, p):
        return {"project_id": p["project_id"], "conversation_id": self.session_id, "request_id": self.id, "agent_id": self.agent_id or p["agent_id"],
                "agent_name": self.agent_name or p["agent_name"], "steps": self.steps, "total_duration_ms": sum(s.get("duration_ms") or 0 for s in self.steps),
                "final_status": "success" if self.outcome == "success" else "error", "model": self.models[0] if self.models else None}


# ------------------------------------------------------------------ opening runs and steps
def current():
    return _run.get()


@contextlib.contextmanager
def run(*, kind, task, session_id, fixture=None, meta=None, agent_id=None, agent_name=None):
    """Open a run for the code inside, which calls r.finish(sentence, status) at its end; an exception that escapes
    finishes the run as an error and is re-raised."""
    r = Run(kind=kind, task=task, session_id=session_id, fixture=fixture, meta=meta, agent_id=agent_id, agent_name=agent_name)
    tok = _run.set(r)
    try:
        yield r
    except BaseException as e:                            # noqa: BLE001  (recorded, then re-raised)
        if r.outcome is None:
            r.finish(f"{type(e).__name__}: {str(e)[:500]}", status="error")
        raise
    finally:
        _run.reset(tok)


@contextlib.contextmanager
def ensure_run(*, kind, task, session_id, agent_id=None, agent_name=None, meta=None, wait=0.0):
    """For an agent that can be called on its own (an assistant turn, an agent job, the instruction agent): inside a
    run already open (a close, an evaluation case) its steps join that run; otherwise it gets a run of its own, finished
    as success unless the code inside calls r.finish itself (an escaping exception finishes it as an error)."""
    outer = _run.get()
    if outer is not None:
        yield outer
        return
    with run(kind=kind, task=task, session_id=session_id, meta=meta, agent_id=agent_id, agent_name=agent_name) as r:
        r.wait = wait
        yield r
        if r.outcome is None:
            r.finish(f"{kind} finished", status="success", wait=wait)


@contextlib.contextmanager
def step(name, kind="tool", input=None):
    """One real step of the current run (a no-op without one). On an exception the step is recorded as an error and
    the exception re-raised; a failure the code handles itself is marked with s.error(message)."""
    r = _run.get()
    if r is None:                                         # nothing to join: see ensure_run for agents called on their own
        yield engine_hook._Nop()
        return
    s = Step(r, name, kind, input, _span.get())
    tok = _span.set(s.id)
    m = _mirror.start(name, kind, input) if _mirror else None
    try:
        yield s
    except BaseException as e:                            # noqa: BLE001
        s.error(f"{type(e).__name__}: {e}")
        raise
    finally:
        _span.reset(tok)
        r.record(s)
        if m is not None:
            _mirror.end(m, s)


_mirror = None


def set_mirror(mirror):
    """Another tracer every step is also reported to (RAMA: an OpenAI Agents SDK span per step, which PRISM's Agent
    Frameworks integration receives). mirror.start(name, kind, input) -> handle; mirror.end(handle, step)."""
    global _mirror
    _mirror = mirror


engine_hook.install(step)                                 # the engine's own steps (ops/native) join the current run


# ------------------------------------------------------------------ delivery
_queue = queue.Queue()
_worker = None
_lock = threading.Lock()


def _ensure_worker():
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_deliver_forever, name="bob-prism", daemon=True)
            _worker.start()


def _deliver_forever():
    while True:
        r, done = _queue.get()
        try:
            deliver(r)
            _write(r.record_dict())                       # the record carries PRISM's answers even when finish didn't wait
        except Exception:                                 # noqa: BLE001  (a delivery failure must not stop the thread)
            pass
        finally:
            done.set()


def post(path, payload, p=None, attempts=3):
    """One POST to PRISM: {status, body} or {status: None, error}. 429 and 5xx are retried with backoff; the key is
    only ever in the header."""
    import urllib.error
    import urllib.request
    p = p or config.prism()
    req = urllib.request.Request(p["host"] + path, method="POST", data=json.dumps(payload, default=str).encode(),
                                 headers={"X-PRISMtrace-Key": p["key"] or "", "Content-Type": "application/json"})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=p["timeout"]) as resp:
                raw = resp.read()
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    body = {"raw": raw[:500].decode(errors="replace")}
                return {"status": resp.status, "body": body, "attempts": i + 1,
                        "plan_warning": resp.headers.get("X-PRISMtrace-Plan-Warning")}
        except urllib.error.HTTPError as e:
            body = e.read()[:1000].decode(errors="replace")
            if e.code in RETRY_STATUSES and i + 1 < attempts:
                time.sleep(min(2 ** i, 8))
                continue
            return {"status": e.code, "error": body, "attempts": i + 1}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if i + 1 < attempts:
                time.sleep(min(2 ** i, 8))
                continue
            return {"status": None, "error": f"{type(e).__name__}: {e}", "attempts": i + 1}


def get(path, p=None):
    import urllib.error
    import urllib.request
    p = p or config.prism()
    req = urllib.request.Request(p["host"] + path, headers={"X-PRISMtrace-Key": p["key"] or ""})
    try:
        with urllib.request.urlopen(req, timeout=p["timeout"]) as resp:
            return {"status": resp.status, "body": json.loads(resp.read() or b"{}")}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read()[:1000].decode(errors="replace")}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"status": None, "error": f"{type(e).__name__}: {e}"}


def deliver(r):
    """Send one run's three records; what PRISM answered is kept on the run."""
    p = config.prism()
    if not p["configured"]:
        r.delivery = {"sent": False, "why": "PRISMTRACE_API_KEY (or PRISM_API_KEY) and PRISMTRACE_PROJECT_ID aren't set"}
        return r.delivery
    r.delivery = {"sent": True, "host": p["host"], "project_id": p["project_id"], "at": _now(),
                  "trace": post("/api/traces", r.trace_payload(p), p),
                  "spans": post("/api/spans/ingest", r.spans_payload(p), p),
                  "trajectory": post("/api/trajectories", r.trajectory_payload(p), p)}
    r.delivery["received"] = all((r.delivery[k].get("status") or 0) < 300 and r.delivery[k].get("status") for k in ("trace", "spans", "trajectory"))
    return r.delivery


def _write(rec):
    d = config.runs_dir()
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f"{rec['run_id']}.json.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, default=str)
    os.replace(tmp, os.path.join(d, rec["run_id"] + ".json"))


def runs(limit=200, session_id=None, kind=None):
    """The recorded runs, newest first, without their spans."""
    d = config.runs_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d), reverse=True):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if (session_id and rec.get("session_id") != session_id) or (kind and rec.get("kind") != kind):
            continue
        out.append({k: v for k, v in rec.items() if k != "spans"})
    out.sort(key=lambda r: r.get("started") or "", reverse=True)
    return out[:limit]


def load(run_id):
    path = os.path.join(config.runs_dir(), run_id + ".json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ proving the credential (python -m bob.trace verify)
def verify(send_test_trace=False):
    """CREDENTIAL OK|FAIL from the handshake, then the setup doctor's live_connected and blocked_step. Prints both lines
    the way the official SDK's verifier does, and returns the two payloads."""
    p = config.prism()
    if not p["configured"]:
        print("CREDENTIAL FAIL — PRISMTRACE_API_KEY (or PRISM_API_KEY) and PRISMTRACE_PROJECT_ID aren't set")
        print("WAITING FOR LIVE — credential not verified")
        return {"credential": False, "live": False}
    hs = post("/api/setup-doctor/handshake", {"project_id": p["project_id"], "send_test_trace": bool(send_test_trace), "client": "bob.trace"}, p, attempts=1)
    ok = hs.get("status") == 200
    print(f"CREDENTIAL {'OK' if ok else 'FAIL'} — HTTP {hs.get('status')}: {json.dumps(hs.get('body') or hs.get('error'))[:300]}")
    doc = get(f"/api/setup-doctor?project_id={p['project_id']}", p) if ok else {}
    live = bool((doc.get("body") or {}).get("live_connected"))
    print(f"{'LIVE CONNECTED' if live else 'WAITING FOR LIVE'} — {json.dumps(doc.get('body') or doc.get('error'))[:400]}")
    return {"credential": ok, "handshake": hs, "doctor": doc, "live": live}


if __name__ == "__main__":
    import sys
    config.load_dotenv()
    if sys.argv[1:2] == ["verify"]:
        out = verify(send_test_trace="--test-trace" in sys.argv)
        sys.exit(0 if out["credential"] else 2)
    if sys.argv[1:2] == ["runs"]:
        for r in runs(limit=int(sys.argv[2]) if sys.argv[2:] else 20):
            print(r["started"], r["run_id"], r["status"], len(r["steps"]), "steps", (r.get("prism") or {}).get("received"), r.get("output", "")[:80])
        sys.exit(0)
    print(__doc__)
