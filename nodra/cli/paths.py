import json
import os
import sys

HOME = lambda: os.environ.get("NODRA_HOME") or os.path.join(os.path.expanduser("~"), ".nodra")


def p(*a):
    d = os.path.join(HOME(), *a)
    return d


def ensure(*a):
    d = p(*a)
    os.makedirs(d, exist_ok=True)
    return d


def load(name, default):
    try:
        with open(p(name)) as f:
            return json.load(f)
    except Exception:
        return default


def save(name, data, private=False):
    ensure()
    tmp = p(name) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, p(name))


def config():
    return load("config.json", {})


def root():
    """The checkout this CLI runs from (the folder that holds `nodra/`, `packages/` and `chat/`). NODRA_ROOT overrides it."""
    r = os.environ.get("NODRA_ROOT")
    if r and os.path.isdir(r):
        return os.path.abspath(r)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def self_cmd():
    """Command (list) that runs this CLI again. Always `python -m nodra.cli`; pair it with cli_env() so a raw checkout is importable."""
    return [sys.executable, "-m", "nodra.cli"]


def cli_env(env=None):
    """Environment for a process that runs the CLI or a service: NODRA_HOME, NODRA_ROOT, NODRA_CLI set and the checkout on PYTHONPATH."""
    e = dict(os.environ if env is None else env)
    r = root()
    e["NODRA_HOME"], e["NODRA_ROOT"] = HOME(), r
    e["NODRA_CLI"] = json.dumps(self_cmd())
    e["PYTHONPATH"] = r + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    return e
