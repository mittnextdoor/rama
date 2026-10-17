"""Per-agent settings (config/agents.json, or NHB_AGENT_CONFIG). Secrets aren't here: only the name of the variable or
Keychain item that holds each agent's key."""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PATH = os.path.join(ROOT, "config", "agents.json")
INSTRUCTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instructions")
KEYS = ("enabled", "provider", "model", "escalation_model", "credential_env", "max_input_tokens", "max_output_tokens", "per_task_token_budget",
        "monthly_token_budget", "timeout_seconds", "max_retries", "temperature", "confidence_threshold", "batch_size", "data_kinds",
        "prices_per_million_tokens", "context_tools", "may", "purpose", "wired", "max_steps", "effort")


def _raw():
    with open(os.environ.get("NHB_AGENT_CONFIG") or DEFAULT_PATH, encoding="utf-8") as f:
        return json.load(f)


def agent(name):
    raw = _raw()
    if name not in raw["agents"]:
        raise KeyError(f"no agent {name!r} in the agent configuration")
    cfg = {**raw["defaults"], **raw["agents"][name], "name": name}
    unknown = set(cfg) - set(KEYS) - {"name"}
    if unknown:
        raise ValueError(f"agent {name}: unknown settings {sorted(unknown)}")
    if os.environ.get(f"NHB_AGENT_{name.upper()}_ENABLED") in ("0", "1"):     # an environment override, for one machine
        cfg["enabled"] = os.environ[f"NHB_AGENT_{name.upper()}_ENABLED"] == "1"
    if os.environ.get(f"NHB_AGENT_{name.upper()}_MODEL"):
        cfg["model"] = os.environ[f"NHB_AGENT_{name.upper()}_MODEL"]
    cfg.setdefault("wired", True)
    return cfg


def names():
    return list(_raw()["agents"])


def instructions(name):
    path = os.path.join(INSTRUCTIONS, f"{name}.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def version(name, schema):
    """The agent's version: its instructions, its output schema and the settings that change its answers."""
    cfg = agent(name)
    h = hashlib.sha256()
    h.update(instructions(name).encode())
    h.update(json.dumps(schema, sort_keys=True).encode())
    h.update(json.dumps({k: cfg.get(k) for k in ("model", "temperature", "confidence_threshold", "max_output_tokens")}, sort_keys=True).encode())
    return h.hexdigest()[:16]
