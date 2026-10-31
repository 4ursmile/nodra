"""`nodra statusline`: lets the chat show your Claude subscription limits. Claude Code gives its status line command a JSON document on
stdin, and for subscribers it holds `rate_limits` (five_hour / seven_day: used_percentage, resets_at). This command is that status line:
it keeps the `rate_limits` block in ~/.nodra/ui/limits-statusline.json and then prints what your previous status line printed (it runs
that command with the same input), or a short default. It never fails the status line: any error just prints the default.

  nodra statusline install    set statusLine in ~/.claude/settings.json to this command (the previous one is kept and still runs)
  nodra statusline remove     put the previous statusLine back
  nodra statusline status     is it installed?

Opt-in only; it reads nothing but what Claude Code passes to every status line, and sends nothing anywhere."""
import json
import os
import subprocess
import sys
import time

from ..core.errors import NodraError
from . import paths, ui

MARK = " statusline"
LIMITS = ("ui", "limits-statusline.json")
PREV = "statusline-prev.json"


def _claude_settings():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "settings.json")


def _shim():
    b = paths.p("bin", "nodra.cmd" if os.name == "nt" else "nodra")
    if not os.path.isfile(b):
        raise NodraError("no nodra command at %s; run python3 install.py in the repository first" % b)
    return ('"%s"' % b if " " in b else b) + MARK


def _ours(sl):
    return isinstance(sl, dict) and str(sl.get("command") or "").replace('"', "").endswith(paths.p("bin", "nodra.cmd" if os.name == "nt" else "nodra") + MARK)


def _read_settings():
    f = _claude_settings()
    try:
        with open(f, encoding="utf-8-sig") as fh:
            text = fh.read()
    except FileNotFoundError:
        return f, {}
    try:
        d = json.loads(text) if text.strip() else {}
    except ValueError:
        raise NodraError("%s is not plain JSON (comments?); add the status line by hand: \"statusLine\": {\"type\": \"command\", \"command\": %s}"
                         % (f, json.dumps(_shim())))
    if not isinstance(d, dict):
        raise NodraError("%s does not hold a JSON object" % f)
    return f, d


def _write_settings(f, d):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".nodra.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(d, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, f)


def status():
    f, d = _read_settings()
    prev = paths.load(PREV, {}).get("statusLine")
    return {"installed": _ours(d.get("statusLine")), "settings": f, "previous": prev, "limits_file": paths.p(*LIMITS)}


def install():
    f, d = _read_settings()
    cur = d.get("statusLine")
    if not _ours(cur):
        paths.save(PREV, {"statusLine": cur})                  # None when there was none
        new = {"type": "command", "command": _shim()}
        if isinstance(cur, dict) and "padding" in cur:
            new["padding"] = cur["padding"]
        d["statusLine"] = new
        _write_settings(f, d)
    return status()


def remove():
    f, d = _read_settings()
    if _ours(d.get("statusLine")):
        prev = paths.load(PREV, {}).get("statusLine")
        if prev:
            d["statusLine"] = prev
        else:
            d.pop("statusLine", None)
        _write_settings(f, d)
    try:
        os.remove(paths.p(PREV))
    except OSError:
        pass
    return status()


def _keep(doc):
    rl = doc.get("rate_limits") if isinstance(doc, dict) else None
    if not isinstance(rl, dict) or not rl:
        return
    out = paths.p(*LIMITS)
    try:
        with open(out, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("rate_limits") == rl and time.time() - float(old.get("at") or 0) < 60:
            return                                              # unchanged and fresh: no write on every redraw
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".%d.tmp" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"at": time.time(), "rate_limits": rl}, f)
    os.replace(tmp, out)


def _default(doc):
    try:
        model = doc.get("model") if isinstance(doc, dict) else None
        parts = [str((model.get("display_name") if isinstance(model, dict) else model) or "Claude")]
        rl = doc.get("rate_limits") if isinstance(doc, dict) else None
        for k, label in (("five_hour", "5h"), ("seven_day", "week")):
            w = rl.get(k) if isinstance(rl, dict) else None
            if isinstance(w, dict) and w.get("used_percentage") is not None:
                parts.append("%s %d%%" % (label, round(float(w["used_percentage"]))))
        return " · ".join(parts)
    except Exception:                                           # whatever Claude Code sends, the status line still prints
        return "Claude"


def bridge(stdin=None, stdout=None):
    """The status line itself. Always prints something and returns 0."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    raw, doc = "", {}
    try:
        raw = stdin.read(2_000_000)
        doc = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError):
        pass
    try:
        _keep(doc)
    except Exception:                                           # a status line must never break: the limits just are not kept this time
        pass
    prev = paths.load(PREV, {}).get("statusLine")
    if isinstance(prev, dict) and prev.get("command") and not _ours(prev):
        try:
            r = subprocess.run(prev["command"], shell=True, input=raw, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            if r.stdout:
                stdout.write(r.stdout)
                return 0
        except (OSError, subprocess.SubprocessError):
            pass
    stdout.write(_default(doc) + "\n")
    return 0


def cmd_statusline(a):
    act = getattr(a, "action", None)
    if not act:
        return bridge()
    if act == "install":
        d = install()
        ui.result(d)
        ui.good("Claude Code's status line now also keeps your subscription limits for the chat (%s)" % d["settings"])
        ui.info("your previous status line still shows; undo with: nodra statusline remove")
    elif act == "remove":
        d = remove()
        ui.result(d)
        ui.good("status line restored (%s)" % d["settings"])
    elif act == "status":
        d = status()
        ui.result(d)
        ui.out("installed: %s  (%s)" % ("yes" if d["installed"] else "no", d["settings"]))
    else:
        raise ValueError("statusline: install, remove or status")
