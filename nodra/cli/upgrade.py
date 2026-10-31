"""`nodra upgrade`: bring this checkout to the newest commit of its git remote, then restart the chat if it runs.
The app is not a package: it is the checkout it runs from. A copy without git (a downloaded zip) cannot update itself; it says how to refresh it."""
import os

from ..core.errors import NodraError
from ..core.release import VERSION
from . import gitx, paths, runs, ui

NOT_GIT = ("this copy of nodra is not a git checkout, so it cannot update itself. Download the repository zip again and unzip it over this "
           "folder (then run: python3 install.py), or use 'git clone' next time")


def _is_checkout():
    return os.path.exists(os.path.join(paths.root(), ".git"))


def _git(args, check=True):
    return gitx.run(args, cwd=paths.root(), check=check)


def _short(sha):
    return (sha or "")[:8]


def status(fetch=True):
    """-> {"git", "behind", "current", "latest", "version", "branch", "commits", "message"} without changing anything."""
    d = {"git": False, "behind": False, "current": VERSION, "latest": VERSION, "version": VERSION, "branch": "", "commits": 0, "message": ""}
    if not gitx.available():
        d["message"] = "git is not installed, so nodra cannot check for updates. Install git, or download the repository zip again."
        return d
    if not _is_checkout():
        d["message"] = NOT_GIT
        return d
    d["git"] = True
    try:
        d["current"] = _short(_git(["rev-parse", "HEAD"]))
        d["branch"] = _git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
        up = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False)
        if not up:
            d["message"] = "this checkout tracks no remote branch (git branch --set-upstream-to=origin/main); nothing to compare with"
            return d
        if fetch:
            _git(["fetch", "--quiet", up.split("/", 1)[0]])
        d["latest"] = _short(_git(["rev-parse", "@{u}"]))
        d["commits"] = int(_git(["rev-list", "--count", "HEAD..@{u}"]) or 0)
    except gitx.GitError as e:
        d["message"] = "cannot reach the remote: %s" % e
        d["error"] = str(e)
        return d
    d["behind"] = d["commits"] > 0
    d["message"] = "%d new commit(s) on %s: run nodra upgrade" % (d["commits"], up) if d["behind"] else "nodra is up to date (%s)" % d["current"]
    return d


def cmd_upgrade(a):
    d = status(fetch=True)
    if a.check:
        ui.result(d)
        (ui.note if d["behind"] else ui.good)(d["message"]) if d["git"] else ui.note(d["message"])
        return
    if not d["git"]:
        raise NodraError(d["message"])
    if d.get("error"):
        raise NodraError(d["message"])
    if not d["behind"]:
        ui.result(dict(d, updated=False, restarted=False))
        return ui.good(d["message"])
    old = d["current"]
    with ui.Spinner("Updating %s" % paths.root()):
        try:
            _git(["pull", "--ff-only", "--quiet"])
        except gitx.GitError as e:
            raise NodraError("git pull failed: %s (local changes in the checkout? commit or stash them, then try again)" % e)
    new = _short(_git(["rev-parse", "HEAD"]))
    restarted = False if getattr(a, "no_restart", False) else restart_chat()
    ui.result(dict(d, updated=True, behind=False, current=new, previous=old, restarted=restarted, message="updated %s -> %s" % (old, new)))
    ui.celebrate("updated %s %s %s" % (old, ui.ARROW, new))
    if not getattr(a, "no_restart", False):
        ui.info("the chat was restarted" if restarted else "start the chat with: nodra chat")


def restart_chat():
    """Restart the chat service when it runs, so it serves the new code. -> True when a restart was requested."""
    r = runs.load(runs.rid_of("nodra-chat"))
    if r and runs.alive(r):
        runs.control(r["id"], "restart")
        return True
    return False


def cmd_version(a):
    ui.result({"version": VERSION, "root": paths.root()})
    ui.out("nodra %s  (%s)" % (VERSION, paths.root()))
