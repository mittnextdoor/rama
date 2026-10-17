"""A hook for whoever watches the engine work (bob/trace.py: PRISM in the hackathon build). The engine reports each real
step it takes (an account's matching and reconciliation, the ledger checks, the workpapers) through step(); with nothing
installed, step() yields a no-op and costs nothing. The engine never imports the watcher."""
import contextlib

_hook = None


def install(fn):
    """fn(name, kind, input) -> a context manager yielding an object with out(dict) and error(str). None uninstalls."""
    global _hook
    _hook = fn


class _Nop:
    def out(self, *_a, **_k):
        pass

    def error(self, *_a, **_k):
        pass

    def llm(self, *_a, **_k):
        pass


@contextlib.contextmanager
def step(name, kind="tool", input=None):
    if _hook is None:
        yield _Nop()
        return
    with _hook(name, kind, input) as s:
        yield s
