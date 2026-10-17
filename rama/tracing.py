"""PRISM through its Agent Frameworks card: the OpenAI Agents SDK, with PRISM's tracing processor as the only processor
(no OpenAI exporter, no OpenAI key). Every model call goes to Nicrron.

- Agents built with the SDK (the card writer, the compliance check) are traced by the SDK itself.
- The deterministic steps (the close engine's tools, the rules, approval, publication) are recorded with bob.trace for the
  local run record, and mirrored here as SDK function spans; model calls made by the engine's provider become generation
  spans. All of a month's work shares one PRISM session: "<company>-<period>"."""
import contextlib
import json
import os
import threading

from bob import config as bob_config
from bob import trace as BT

_lock = threading.Lock()
_processor = None


def _text(x, limit=4000):
    if x is None:
        return ""
    s = x if isinstance(x, str) else json.dumps(x, default=str, sort_keys=True)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def install():
    """Register PRISM's processor once (idempotent). Returns (installed, why)."""
    global _processor
    bob_config.load_dotenv()
    os.environ["BOB_TRACE_HTTP"] = "0"                    # PRISM gets the Agent Frameworks traces only, not bob.trace's HTTP posts
    key, project = os.environ.get("PRISMTRACE_API_KEY"), os.environ.get("PRISMTRACE_PROJECT_ID")
    with _lock:
        if _processor is not None:
            return True, "installed"
        from agents import set_trace_processors
        if not (key and project):
            set_trace_processors([])
            return False, "PRISMTRACE_API_KEY / PRISMTRACE_PROJECT_ID not set: runs are kept locally only"
        from prismtrace import PRISMtraceTracingProcessor
        _processor = _Queued(PRISMtraceTracingProcessor(api_key=key, project_id=project, agent_name="rama"))
        set_trace_processors([_processor])
        BT.set_mirror(_Mirror())
        return True, "installed"


def flush(wait=False):
    """Delivery runs in the background; wait=True blocks until every queued span is posted."""
    if _processor is not None and wait:
        try:
            _processor.force_flush()
        except Exception:                                 # noqa: BLE001  (delivery is best effort; the local record stands)
            pass


class _Queued:
    """PRISM's processor posts each span over HTTP when it ends, on the caller's thread; queued here so the agents and
    the engine never wait on delivery. Trace starts stay synchronous (they only record the trace's session)."""

    def __init__(self, inner):
        import queue
        self.inner, self.q = inner, queue.Queue()
        threading.Thread(target=self._work, name="rama-prism", daemon=True).start()

    def _work(self):
        while True:
            fn, arg = self.q.get()
            try:
                fn(arg)
            except Exception:                             # noqa: BLE001  (best effort; the local record stands)
                pass
            finally:
                self.q.task_done()

    def on_trace_start(self, trace):
        self.inner.on_trace_start(trace)

    def on_trace_end(self, trace):
        self.q.put((self.inner.on_trace_end, trace))

    def on_span_start(self, span):
        pass

    def on_span_end(self, span):
        self.q.put((self.inner.on_span_end, span))

    def shutdown(self):
        self.force_flush()

    def force_flush(self):
        self.q.join()


class _Mirror:
    """bob.trace steps -> Agents SDK spans (function for tools/retrieval/chain, generation for llm)."""

    def start(self, name, kind, input):
        from agents.tracing import function_span, generation_span
        if kind == "llm":
            msgs = (input or {}).get("messages") if isinstance(input, dict) else None
            sp = generation_span(input=[{"role": str(m.get("role", "user")), "content": _text(m.get("content"))} for m in msgs or []]
                                 or [{"role": "user", "content": _text(input)}])
        else:
            sp = function_span(name=name, input=_text(input))
        sp.start(mark_as_current=True)
        return sp

    def end(self, sp, step):
        try:
            data = sp.span_data
            if step.kind == "llm":
                data.model = step.model
                data.output = [{"role": "assistant", "content": _text(step.output)}]
                data.usage = {"input_tokens": step.tokens_in or 0, "output_tokens": step.tokens_out or 0}
            else:
                data.output = _text(step.output if step.output is not None else step.err)
            if step.status == "error":
                from agents.tracing import SpanError
                sp.set_error(SpanError(message=str(step.err or "error")[:500], data=None))
        finally:
            sp.finish(reset_current=True)


@contextlib.contextmanager
def session(session_id, workflow, *, agent_id, kind, task, meta=None):
    """One traced piece of work: a local bob.trace run (the record kept on disk) inside an Agents SDK trace, inside
    PRISM's session. Yields the bob.trace run; the caller finishes it with r.finish(sentence, status)."""
    install()
    import prismtrace
    from agents import trace as sdk_trace
    with prismtrace.session(session_id):
        with sdk_trace(workflow, group_id=session_id, metadata={"agent_id": agent_id, "kind": kind}):
            with BT.run(kind=kind, task=task, session_id=session_id, agent_id=agent_id, agent_name=agent_id, meta=meta) as r:
                yield r
    flush()


def step(name, kind="tool", input=None):
    return BT.step(name, kind, input)


def doctor():
    """PRISM's own view of the project: live_connected, app_connected, blocked_step, trace counts."""
    bob_config.load_dotenv()
    key, project = os.environ.get("PRISMTRACE_API_KEY"), os.environ.get("PRISMTRACE_PROJECT_ID")
    host = (os.environ.get("PRISMTRACE_HOST") or "https://prism.blockconvey.com").rstrip("/")
    if not (key and project):
        return {"configured": False}
    import urllib.request
    req = urllib.request.Request(f"{host}/api/setup-doctor?project_id={project}", headers={"X-PRISMtrace-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
    except Exception as e:                                # noqa: BLE001
        return {"configured": True, "error": f"{type(e).__name__}: {e}"[:200]}
    return {"configured": True, "project_id": project, "host": host, **{k: d.get(k) for k in
            ("live_connected", "app_connected", "blocked_step", "overall", "live_trace_count", "app_trace_count")}}
