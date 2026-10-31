"""Keeps the chat app current. The chat is not a package: it is the checkout it runs from. A thread asks `nodra upgrade --check` every
UI_UPDATE_MINUTES (default 60, first a minute after start); when the checkout is behind its git remote and NOTHING is running (no chat
answering, no work run, no install terminal) for IDLE_FOR seconds, it runs `nodra upgrade --no-restart` and restarts the chat.
Pref `auto_update`: on (default) | notify (only say so) | off. The same round also checks the packages (`nodra update --check`); with pref
`auto_update_packages` they are updated too, also only when idle. A restart is a clean exit under `nodra chat` / `nodra run` (the supervisor
starts the service again, restart = always) and an in-place exec otherwise; the key and port stay, so open pages reconnect and see the new
BUILD. A failed pull (no network, local changes in the checkout) is not retried until the remote moves on or someone presses Check."""
import hashlib
import os
import sys
import threading
import time

from . import chat, freechat, nodra as A, store, term

IDLE_FOR = int(os.environ.get("UI_UPDATE_IDLE") or 60)
UI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
state = {"checked": 0.0, "behind": False, "current": "", "latest": "", "git": None, "message": "", "error": "", "stage": "", "stage_at": 0.0,
         "waiting": "", "failed": "", "pending_restart": False, "packages": [], "packages_checked": 0.0, "packages_error": "", "build": ""}
_ctl = {"engine": None, "restart": None}
_lock = threading.Lock()                    # one CLI round (check or apply) at a time
_now = threading.Event()                    # "check now" from the Settings card


def build_id(root=UI_DIR):
    """Fingerprint of the code this process serves (names, sizes, mtimes of server.py, nodraui/*.py, static/*): a page that loaded another
    build knows the app was updated under it."""
    h = hashlib.sha1()
    for sub in ("", "nodraui", "static"):
        d = os.path.join(root, sub)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.endswith((".py", ".js", ".css", ".html")):
                continue
            try:
                st = os.stat(os.path.join(d, n))
            except OSError:
                continue
            h.update(("%s/%s:%d:%d\n" % (sub, n, st.st_size, int(st.st_mtime))).encode("utf-8"))
    return h.hexdigest()[:12]


state["build"] = build_id()


def every():
    try:
        return max(int(os.environ.get("UI_UPDATE_MINUTES") or 60), 5) * 60
    except ValueError:
        return 3600


def mode():
    m = store.prefs().get("auto_update", "on")
    return m if m in ("on", "notify", "off") else "on"


def busy(engine=None):
    """Why a restart now would cut something off ('' = nothing is running)."""
    engine = engine if engine is not None else _ctl["engine"]
    with chat.plock:
        if any(not r.done for r in chat.runs.values()):
            return "a chat is answering"
    with freechat.lock:
        if freechat.live:
            return "a free chat is answering"
    if engine is not None and getattr(engine, "running", 0):
        return "a work is running"
    with term.lock:
        if any(t.code is None and not getattr(t, "shell", False) for t in term.terms.values()):      # chat shells do not count, installs do
            return "an install is running"
    return ""


def stage(name):
    """Progress step shown in the app: '' | checking | waiting | updating | restarting | error."""
    state.update(stage=name, stage_at=time.time())


def check(packages=True):
    """`nodra upgrade --check` (+ `nodra update --check`). Fills state; -> True when the checkout is behind."""
    with _lock:
        if state["stage"] in ("", "error", "waiting"):
            stage("checking")
        try:
            doc = A.run(["upgrade", "--check"], timeout=120)
            d = doc.get("data") if isinstance(doc.get("data"), dict) else {}
            latest = str(d.get("latest") or "")[:80]
            if latest and latest != state["latest"]:
                state["failed"] = ""                                  # the remote moved on: a pull that failed before may work now
            state.update(error=str(d.get("error") or "")[:300], checked=time.time(), behind=bool(d.get("behind")), git=d.get("git"),
                         current=str(d.get("current") or "")[:80], latest=latest, message=str(d.get("message") or doc.get("output") or "").strip()[:400])
        except Exception as e:
            state.update(error=str(e)[:300], checked=time.time())
        if packages:
            try:
                rows = (A.run(["update", "--check"], timeout=300).get("data") or {}).get("updates") or []
                state.update(packages=[{"name": str(r.get("name")), "installed": str(r.get("installed") or ""), "available": str(r.get("available") or ""),
                                        "source": str(r.get("source") or "")} for r in rows if isinstance(r, dict) and r.get("name")][:100],
                             packages_checked=time.time(), packages_error="")
            except Exception as e:
                state.update(packages_error=str(e)[:300], packages_checked=time.time())
        if state["stage"] == "checking":
            stage("")
        return state["behind"]


def _restart_when_idle(force=False):
    """Restart now unless something runs (then the loop retries). -> True when it restarted."""
    why = "" if force else busy()
    if why:
        state.update(pending_restart=True, waiting="restart postponed: " + why)
        stage("waiting")
        return False
    state.update(pending_restart=False, waiting="")
    stage("restarting")
    time.sleep(1)                                                     # the HTTP reply / last poll gets out first
    if _ctl["restart"]:
        _ctl["restart"]()
    return True


def apply(force=False):
    """Pull and restart. Only when idle unless `force`; -> True when it restarted."""
    why = "" if force else busy()
    if why:
        state["waiting"] = why
        stage("waiting")
        return False
    with _lock:
        state["waiting"] = ""
        stage("updating")
        try:
            doc = A.run(["upgrade", "--no-restart"], timeout=1800)
        except Exception as e:
            state.update(error="update failed: %s" % str(e)[:300], failed=state["latest"] or "?")
            stage("error")
            return False
        d = doc.get("data") if isinstance(doc.get("data"), dict) else {}
        state.update(error="", failed="", behind=False, current=str(d.get("current") or state["current"])[:80],
                     message=str(d.get("message") or "updated").strip()[:400])
    return _restart_when_idle(force)


def update_packages(force=False):
    """`nodra update` for every package with a newer version. -> True when it ran."""
    if not force and busy():
        return False
    with _lock:
        try:
            A.run(["update"], timeout=1800)
            state.update(packages=[], packages_error="")
        except Exception as e:
            state["packages_error"] = "package update failed: %s" % str(e)[:300]
            return False
        finally:
            A.invalidate()                                            # new nodes / MCP servers / slash commands show up without a restart
    return True


def loop():
    time.sleep(float(os.environ.get("UI_UPDATE_FIRST", "60")))     # let the first page load in peace
    idle_since = 0.0
    while True:
        m = mode()
        if _now.is_set() or m != "off" and time.time() - state["checked"] >= every():
            _now.clear()
            check()
        if state["pending_restart"]:
            _restart_when_idle()
        elif m == "on" and (state["behind"] and not state["failed"] or state["packages"] and store.prefs().get("auto_update_packages")):
            why = busy()
            if why:
                idle_since = 0.0
                state["waiting"] = why
                if state["stage"] in ("", "waiting"):
                    stage("waiting")
            else:
                idle_since = idle_since or time.time()
                if time.time() - idle_since >= IDLE_FOR:
                    idle_since = 0.0
                    if state["packages"] and store.prefs().get("auto_update_packages"):
                        update_packages()
                    if state["behind"] and not state["failed"] and apply():
                        return
                    if state["stage"] == "waiting":
                        stage("")
        else:
            idle_since = 0.0
            if state["stage"] == "waiting":
                state["waiting"] = ""
                stage("")
        _now.wait(15)


def check_now(wait=60.0):
    """Check now (also when auto update is off) and wait for it, at most WAIT seconds. -> True when it finished."""
    th = threading.Thread(target=check, daemon=True, name="ui-update-check")
    th.start()
    th.join(wait)
    return not th.is_alive()


def act(what):
    """Settings buttons, run in a thread so the HTTP reply goes out first. what = 'update' (pull + restart now, even when busy) |
    'restart' | 'packages' (update every package now). -> '' or why nothing was started."""
    if state["stage"] in ("updating", "restarting"):
        return "already in progress"
    if what == "update":
        target = lambda: apply(force=True)
    elif what == "packages":
        target = lambda: update_packages(force=True)
    else:
        target = lambda: _restart_when_idle(force=True)
    threading.Thread(target=target, daemon=True, name="ui-update-act").start()
    return ""


def status():
    return dict(state, mode=mode(), auto_packages=bool(store.prefs().get("auto_update_packages")))


def restarter(srv, engine):
    """The function that restarts the chat: leave to the supervisor of `nodra run`, else exec this program again in place."""
    def go():
        engine.shutdown()
        if os.environ.get("NODRA_RUN_ID"):
            os._exit(0)
        try:
            srv.server_close()
        except OSError:
            pass
        os.environ["UI_OPEN"] = "0"                       # same address and key: no new browser tab
        os.execv(sys.executable, [sys.executable] + sys.argv)
    return go


def start(restart, engine=None, background=True):
    _ctl.update(restart=restart, engine=engine)
    if background and os.environ.get("UI_UPDATE_MINUTES") != "0":
        threading.Thread(target=loop, daemon=True, name="ui-selfupdate").start()
