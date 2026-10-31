"""Claude subscription limits (the 5-hour window and the weekly ones), as Claude Code reports them. Two sources, both Claude Code's own:

  * `rate_limit_event` in the stream of a chat or work run (sent when a limit is near or reached): note_event().
  * the `rate_limits` block Claude Code gives its status line command in interactive sessions (`nodra statusline`, opt-in, see
    nodra/cli/statusline.py), which the CLI writes to ~/.nodra/ui/limits-statusline.json: read here, newest value per window wins.

Nothing is fetched and no token is read: when no Claude Code session has reported a window, it is simply not shown. A window whose
reset time has passed is dropped (it starts again from zero)."""
import json
import os
import threading
import time

from . import store

LABELS = {"five_hour": "5-hour window", "seven_day": "Week", "seven_day_opus": "Week (Opus)", "seven_day_sonnet": "Week (Sonnet)",
          "seven_day_overage_included": "Week (with extra usage)", "overage": "Extra usage"}
ORDER = list(LABELS)
WARN_AT = 80
_lock = threading.Lock()


def _file(name="limits.json"):
    return os.path.join(store.ui_dir(), name)


def _load(name="limits.json"):
    try:
        with open(_file(name), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(u, fraction=True):
    """rate_limit_event utilization is a fraction (0..1); the status line already gives percent."""
    u = _num(u)
    if u is None:
        return None
    return round(u * 100 if fraction and u <= 1.0 else u, 1)


def _when(v):
    v = _num(v)
    if v is None:
        return None
    return v / 1000 if v > 1e11 else v                                # milliseconds -> seconds


def note_event(info, source="chat"):
    """Record a rate_limit_event's rate_limit_info. -> a small summary for the chat ({status, window, pct, resets_at}) or None."""
    if not isinstance(info, dict):
        return None
    now, wins = time.time(), {}
    for k, w in (info.get("unifiedWindows") or {}).items():
        if isinstance(w, dict) and k in LABELS:
            wins[k] = {"pct": _pct(w.get("utilization")), "resets_at": _when(w.get("resetsAt")), "status": str(w.get("status") or "")}
    kind = info.get("rateLimitType") if info.get("rateLimitType") in LABELS else None
    if kind and (kind not in wins or wins[kind]["pct"] is None):
        wins[kind] = {"pct": _pct(info.get("utilization")), "resets_at": _when(info.get("resetsAt")), "status": str(info.get("status") or "")}
    status = str(info.get("status") or "")
    with _lock:
        d = _load()
        cur = d.get("windows") if isinstance(d.get("windows"), dict) else {}
        for k, w in wins.items():
            cur[k] = dict(w, seen=now, source=source)
        d.update(windows=cur, status=status, status_at=now, error_code=str(info.get("errorCode") or ""),
                 resets_at=_when(info.get("resetsAt")), kind=kind or "")
        store._write(_file(), d)
    main = wins.get(kind) or next(iter(wins.values()), {}) if wins else {}
    return {"status": status, "window": kind or "", "pct": (main or {}).get("pct"), "resets_at": (main or {}).get("resets_at") or _when(info.get("resetsAt"))}


def note_statusline(rate_limits, now=None):
    """The `rate_limits` block of Claude Code's status line input -> the windows it names (used_percentage is already a percent)."""
    out = {}
    for k, w in (rate_limits or {}).items():
        if isinstance(w, dict) and k in LABELS:
            out[k] = {"pct": _pct(w.get("used_percentage"), fraction=False), "resets_at": _when(w.get("resets_at")), "status": "",
                      "seen": now or time.time(), "source": "claude code"}
    return out


def windows():
    """Every window still in its period, newest report per window: [{id, label, pct, resets_at, status, seen, source}]."""
    now = time.time()
    merged = {}
    for name, conv in (("limits.json", None), ("limits-statusline.json", note_statusline)):
        d = _load(name)
        wins = conv(d.get("rate_limits"), _num(d.get("at"))) if conv else (d.get("windows") or {})
        for k, w in wins.items():
            if not isinstance(w, dict) or k not in LABELS:
                continue
            if w.get("resets_at") and w["resets_at"] < now:
                continue
            if k not in merged or (w.get("seen") or 0) > (merged[k].get("seen") or 0):
                merged[k] = w
    return [dict(merged[k], id=k, label=LABELS[k]) for k in ORDER if k in merged]


def state():
    """The page's view: windows plus the last status Claude Code reported (rejected = the subscription stops answering until resets_at)."""
    d = _load()
    st = d.get("status") if d.get("resets_at") and d["resets_at"] > time.time() else ""
    return {"windows": windows(), "status": st or "", "error_code": d.get("error_code") or "" if st else "", "resets_at": d.get("resets_at") if st else None}


def chat_note(lim):
    """A line for the chat when Claude Code says a limit is near or reached ('' while all is fine)."""
    if not lim or lim.get("status") not in ("allowed_warning", "rejected"):
        return ""
    what = LABELS.get(lim.get("window") or "", "subscription").lower()
    when = " Resets in %s." % _in(lim["resets_at"]) if lim.get("resets_at") else ""
    if lim["status"] == "rejected":
        return "Claude %s limit reached.%s" % (what, when)
    return "Claude %s: %s used.%s" % (what, "%d%%" % lim["pct"] if lim.get("pct") is not None else "most of it", when)


def _in(t):
    s = max(0, int((t or 0) - time.time()))
    return "%d h %02d min" % (s // 3600, s % 3600 // 60) if s >= 3600 else "%d min" % max(1, s // 60)


def alerts():
    """Usage banner entries: a window at WARN_AT% or more, or a limit reached."""
    out, s = [], state()
    for w in s["windows"]:
        pct = w.get("pct")
        if pct is None:
            continue
        if pct >= 100 or w.get("status") == "rejected":
            out.append({"id": "sub:" + w["id"], "level": "over", "title": "Claude %s: limit reached" % w["label"].lower(),
                        "text": "Claude Code chats wait until it resets%s." % (" in " + _in(w["resets_at"]) if w.get("resets_at") else ""), "pct": pct})
        elif pct >= WARN_AT:
            out.append({"id": "sub:%s:%d" % (w["id"], pct // 10 * 10), "level": "warn", "title": "Claude %s: %d%% used" % (w["label"].lower(), pct),
                        "text": "Resets in %s." % _in(w["resets_at"]) if w.get("resets_at") else "", "pct": pct})
    if s["status"] == "rejected" and not any(a["level"] == "over" for a in out):
        out.append({"id": "sub:rejected", "level": "over", "title": "Claude subscription limit reached",
                    "text": ("You need usage credits to continue." if s["error_code"] == "credits_required" else
                             "Claude Code chats wait until it resets%s." % (" in " + _in(s["resets_at"]) if s.get("resets_at") else ""))})
    return out
