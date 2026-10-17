"""API keys, server-side only: an environment variable (servers, tests), or the macOS Keychain (service nhb-product,
account = the variable's name) on this Mac. A key is never written to a log, a decision record, a prompt or a response
to the browser; status() says only where a key was found."""
import os
import re
import subprocess

SERVICE = "nhb-product"
KEY_SHAPE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,200}$")
NICRRON_KEY_SHAPE = re.compile(r"^sk-af-[A-Za-z0-9_\-]{10,200}$")
_MEMORY = {}                                              # tests (NHB_NO_KEYCHAIN=1): keys stored here, never on disk


def _keychain(name):
    if name in _MEMORY:
        return _MEMORY[name]
    if os.environ.get("NHB_NO_KEYCHAIN") == "1":
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def expects(cfg):
    """The variable an agent's key is expected in: NICRRON_API_KEY in hackathon mode, else its own."""
    from bob import config as bobconfig
    return "NICRRON_API_KEY" if bobconfig.hackathon() else cfg.get("credential_env")


def credential(cfg):
    """(key, source) for an agent: its own variable first, then the shared default variable, then the Keychain. In
    hackathon mode (BOB_HACKATHON=1) only NICRRON_API_KEY counts: an Anthropic key never reaches Nicrron, and no agent
    quietly uses a direct provider."""
    from bob import config as bobconfig
    if bobconfig.hackathon():
        k = os.environ.get("NICRRON_API_KEY") or _keychain("NICRRON_API_KEY")
        return (k, "environment (NICRRON_API_KEY)" if os.environ.get("NICRRON_API_KEY") else f"Keychain ({SERVICE}/NICRRON_API_KEY)") if k else (None, None)
    names = [cfg.get("credential_env")] + (["NHB_ANTHROPIC_API_KEY"] if cfg.get("credential_env") != "NHB_ANTHROPIC_API_KEY" else [])
    for n in [x for x in names if x]:
        if os.environ.get(n):
            return os.environ[n], f"environment ({n})"
    for n in [x for x in names if x]:
        k = _keychain(n)
        if k:
            return k, f"Keychain ({SERVICE}/{n})"
    return None, None


def store(name, key):
    """Keep an API key in this Mac's Keychain (service nhb-product, account = the variable's name), replacing one there.
    The key goes to the security tool on its standard input, never on a command line another process could read."""
    from ..errors import Invalid
    key = (key or "").strip()
    if not (KEY_SHAPE.match(key) or (name == "NICRRON_API_KEY" and NICRRON_KEY_SHAPE.match(key))):
        raise Invalid("That doesn't look like an API key (Anthropic keys start with sk-ant-, Nicrron keys with sk-af-).", field="key")
    if not re.match(r"^[A-Z0-9_]+$", name or ""):
        raise Invalid("unknown key name")
    if os.environ.get("NHB_NO_KEYCHAIN") == "1":
        _MEMORY[name] = key
        return
    r = subprocess.run(["security", "-i"], input=f"add-generic-password -U -s {SERVICE} -a {name} -w {key}\n", capture_output=True, text=True,
                       timeout=10)
    if r.returncode != 0 or _keychain(name) != key:
        raise RuntimeError("the key couldn't be stored in the Keychain")


def remove(name):
    _MEMORY.pop(name, None)
    if os.environ.get("NHB_NO_KEYCHAIN") != "1" and re.match(r"^[A-Z0-9_]+$", name or ""):
        subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", name], capture_output=True, text=True, timeout=10)


def status(cfg):
    _, source = credential(cfg)
    return {"configured": source is not None, "source": source, "expects": expects(cfg)}


def redact(text, cfg=None):
    """Remove a key from text that might be logged (an error message from a provider, say)."""
    out = str(text or "")
    key, _ = credential(cfg) if cfg else (None, None)
    if key:
        out = out.replace(key, "[redacted]")
    return re.sub(r"sk-(?:ant|af)-[A-Za-z0-9_\-]{8,}", "[redacted]", out)
