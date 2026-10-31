"""Local token log for free chat. Claude Code turns are already in Claude's own session logs; free chat talks to the API directly,
so `note()` appends one line (numbers and the model name only) to ~/.nodra/ui/usage.jsonl, which `nodra usage` reads. Nothing leaves
this machine. Never raises."""
import json
import os
import time

from . import nodra as A


def log_path():
    return os.path.join(A.HOME(), "ui", "usage.jsonl")


def note(sid, engine, model, u):
    """Free chat only: record the turn."""
    try:
        if engine == "free" and u and any(int(u.get(k) or 0) for k in ("input", "output", "cache_read", "cache_write")):
            os.makedirs(os.path.dirname(log_path()), exist_ok=True)
            line = {"ts": time.time(), "session": str(sid), "model": str(model or "unknown")[:128]}
            for k in ("input", "output", "cache_read", "cache_write"):
                line[k] = max(0, int(u.get(k) or 0))
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(line, separators=(",", ":")) + "\n")
    except (OSError, TypeError, ValueError):
        pass
