"""Hackathon settings, all from the server's environment (.env.example lists them). Nothing here holds a secret.

BOB_HACKATHON=1 turns hackathon mode on: every reasoning agent's model call goes through Nicrron's OpenAI-compatible
endpoint with the NICRRON_API_KEY, whatever provider config/agents.json names, and never through a direct provider call.
Off, the product behaves as before (Anthropic's API with the agents' own keys)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_dotenv(path=os.path.join(ROOT, ".env")):
    """The repository's .env (never committed), loaded by the command-line tools only (bob.trace, bob.eval.run), never on
    import, so the test suite's environment stays its own. A variable already in the environment wins."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


NICRRON_DEFAULT_BASE = "https://api.nicrron.ai/v1"
NICRRON_DEFAULT_MODEL = "anthropic/claude-haiku-5-5"      # nicrron.ai/docs/models; pinned rather than nicrron/auto so runs are comparable
PRISM_DEFAULT_HOST = "https://prism.blockconvey.com"
STRUCTURED_MODES = ("prompt", "json_schema", "json_object")


def hackathon():
    return os.environ.get("BOB_HACKATHON") == "1"


def nicrron():
    """The Nicrron settings: base URL, the key (or None), the model used for an agent whose configured model isn't a
    Nicrron model id, and how structured output is asked for."""
    mode = (os.environ.get("NICRRON_STRUCTURED") or "prompt").strip().lower()
    if mode not in STRUCTURED_MODES:
        raise ValueError(f"NICRRON_STRUCTURED must be one of {STRUCTURED_MODES}, not {mode!r}")
    return {"base_url": (os.environ.get("NICRRON_BASE_URL") or NICRRON_DEFAULT_BASE).rstrip("/"),
            "key": os.environ.get("NICRRON_API_KEY") or None,
            "model": os.environ.get("NICRRON_MODEL") or NICRRON_DEFAULT_MODEL,
            "structured": mode}


def prism():
    """The PRISM settings. configured is False without a key and a project id: runs are then kept locally only. PRISM's
    documented names (PRISMTRACE_API_KEY, PRISMTRACE_PROJECT_ID, PRISMTRACE_HOST) and the older PRISM_* names both work."""
    def var(name):
        return os.environ.get("PRISMTRACE_" + name) or os.environ.get("PRISM_" + name) or None
    key, project = var("API_KEY"), var("PROJECT_ID")
    return {"host": (var("HOST") or PRISM_DEFAULT_HOST).rstrip("/"), "key": key, "project_id": project,
            "agent_id": os.environ.get("PRISM_AGENT_ID") or "bob-close", "agent_name": os.environ.get("PRISM_AGENT_NAME") or "Bob",
            "configured": bool(key and project) and os.environ.get("BOB_TRACE_HTTP", "1") != "0", "timeout": float(os.environ.get("PRISM_TIMEOUT_SECONDS") or 15)}


def runs_dir():
    """Where every run's record is written (the spans, the steps, PRISM's answers), with or without PRISM."""
    return os.environ.get("BOB_RUNS_DIR") or os.path.join(ROOT, "data", "bob", "runs")
