"""Which login Claude Code uses, so a Claude subscription wins over an API key when both are there.

`claude auth status --json` (run with the API key variables removed, so it reports the login underneath them) says
{loggedIn, authMethod, apiProvider}. authMethod "claude.ai" (a /login with a Claude account) and "oauth_token" (`claude setup-token`) are a
subscription; "api_key", "api_key_helper", "third_party" (Bedrock, Vertex, ...) and "none" are not. Claude Code also says "oauth_token"
for an ANTHROPIC_AUTH_TOKEN (a gateway's bearer token), and it reads the `env` block of its settings.json itself, so a custom
ANTHROPIC_BASE_URL (process or settings env) or a token in that env block means "gateway", never "subscription".

Pref `claude_auth`: "auto" (default) drops ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN from every Claude Code run while a subscription login
exists, whether they came from Settings > Encrypted secrets or from the environment the chat started in; "key" passes them as before.
Free chat is not affected: it talks to the Messages API and always needs a key. A custom ANTHROPIC_BASE_URL (a gateway) keeps the keys."""
import json
import os
import shutil
import subprocess
import threading
import time

from . import auth, store

SUB_METHODS = ("claude.ai", "oauth_token")
KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
TTL = 300
_lock = threading.Lock()
_state = {"checked": 0.0, "status": None}


def _probe():
    exe = shutil.which("claude")
    if not exe:
        return {"ok": False, "logged_in": False, "method": "", "provider": "", "gateway": False, "subscription": False, "error": "Claude Code is not installed"}
    env = {k: v for k, v in os.environ.items() if k not in KEY_VARS}
    try:
        r = subprocess.run([exe, "auth", "status", "--json"], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=20, stdin=subprocess.DEVNULL)
        d = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"ok": False, "logged_in": False, "method": "", "provider": "", "gateway": False, "subscription": False, "error": "claude auth status: %s" % str(e)[:200]}
    if not isinstance(d, dict):
        d = {}
    method = str(d.get("authMethod") or "none")
    logged = bool(d.get("loggedIn"))
    senv = (auth._settings().get("env") or {})
    gateway = _gateway(os.environ) or _gateway(senv)
    token_in_settings = any(senv.get(k) for k in KEY_VARS)
    sub = logged and not gateway and (method == "claude.ai" or method == "oauth_token" and not token_in_settings)
    return {"ok": True, "logged_in": logged, "method": method, "provider": str(d.get("apiProvider") or ""), "gateway": gateway,
            "subscription": sub, "error": ""}


def status(fresh=False):
    """-> {ok, logged_in, method, provider, subscription, error, checked}; cached TTL seconds."""
    with _lock:
        if fresh or not _state["status"] or time.time() - _state["checked"] > TTL:
            _state.update(status=_probe(), checked=time.time())
        return dict(_state["status"], checked=_state["checked"])


def warm():
    threading.Thread(target=status, daemon=True, name="claude-auth-warm").start()


def mode():
    m = store.prefs().get("claude_auth", "auto")
    return m if m in ("auto", "key") else "auto"


def _gateway(env):
    base = str(env.get("ANTHROPIC_BASE_URL") or "").strip().lower()
    return bool(base) and "://api.anthropic.com" not in base


def child_env(env):
    """The environment for a Claude Code process: without the API key variables while a subscription login should win. Changes ENV in place
    and returns it."""
    if mode() == "auto" and not _gateway(env) and any(env.get(k) for k in KEY_VARS) and status().get("subscription"):
        for k in KEY_VARS:
            env.pop(k, None)
    return env


def view():
    """For Settings and the Usage page: the login and what the chat does with keys."""
    s = status()
    s["mode"] = mode()
    return s
