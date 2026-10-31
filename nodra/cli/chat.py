"""`nodra chat [start|stop|restart|status|open]`: run the chat app of this checkout (<root>/chat/nodra.toml, a [service]) where it is, through
the run supervisor. Nothing is installed or copied. The service gets NODRA_HOME, NODRA_ROOT and NODRA_CLI, so it works from a raw checkout."""
import os
import webbrowser

from ..core.errors import NodraError
from . import installer, paths, runs, ui

NAME = "nodra-chat"


def folder():
    d = os.path.join(paths.root(), "chat")
    if not os.path.isfile(os.path.join(d, "nodra.toml")):
        raise NodraError("no chat in this checkout (%s has no nodra.toml); is this the whole repository?" % d)
    return d


def url():
    """The address the chat wrote to ~/.nodra/ui/url.txt, or None."""
    try:
        with open(paths.p("ui", "url.txt"), encoding="utf-8") as f:
            u = f.read().strip()
    except OSError:
        return None
    return u if u.startswith(("http://127.0.0.1", "http://localhost", "https://")) else None


def state():
    r = runs.load(NAME)
    live = bool(r and runs.alive(r))
    st = runs.status_of(r) if r else "stopped"
    return {"name": NAME, "running": live and st in ("running", "starting", "waiting"), "state": st, "pid": (r or {}).get("pid") if live else None,
            "url": url() if live else None, "folder": os.path.join(paths.root(), "chat"), "log": runs._f(NAME, ".log")}


def start(fg=False):
    d = folder()
    r = runs.load(NAME)
    if r and runs.alive(r) and not fg:
        s = state()
        ui.result(dict(s, started=False))
        ui.note("the chat is already running%s" % (": " + s["url"] if s["url"] else ""))
        return 0
    inst, m = installer.inplace_bot(NAME, d)
    installer.write_bot_files(NAME, m, d)                 # ~/.nodra/services/nodra-chat/.env (settings; never overwritten)
    code = runs.start_inplace(runs.rid_of(NAME), NAME, d, fg=fg)
    if code == 0 and not fg:
        runs.show_link(m, open_it=False, since=0)
        ui.result(dict(state(), started=True))
    return code


def stop():
    r = runs.load(NAME)
    if not (r and runs.alive(r)):
        ui.result(dict(state(), stopped=False))
        return ui.info("the chat is not running")
    runs.stop(NAME, r)
    ui.result(dict(state(), stopped=True))


def cmd_chat(a):
    act = a.action or "start"
    if act == "start":
        code = start(fg=a.fg)
        if code:
            raise SystemExit(code)
    elif act == "stop":
        stop()
    elif act == "restart":
        r = runs.load(NAME)
        if r and runs.alive(r):
            runs.stop(NAME, r, quiet=True)
        code = start()
        if code:
            raise SystemExit(code)
    elif act == "status":
        s = state()
        ui.result(s)
        ui.good("the chat is running%s (pid %s)" % (": " + s["url"] if s["url"] else "", s["pid"])) if s["running"] else ui.info("the chat is not running (start it: nodra chat)")
    elif act == "open":
        s = state()
        if not s["running"]:
            if start():
                raise SystemExit(1)
            s = state()
        ui.result(s)
        if not s["url"]:
            raise NodraError("the chat is running but has not written its address yet; try again in a moment (log: %s)" % s["log"])
        ui.good("open: " + s["url"])
        if not ui.JSON:
            webbrowser.open(s["url"])
    else:
        raise ValueError("chat: start, stop, restart, status or open")
