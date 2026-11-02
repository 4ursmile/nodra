"""`nodra work ...`: Works (the chat's node workflows) from a terminal, for servers without the chat page.

The engine lives in the chat of this checkout (<root>/chat), so this command only hands its arguments to it: `chat/ui/server.py --works ...`
with the same interpreter, .env and NODRA_* environment `nodra chat` uses (every subcommand is in chat/ui/nodraui/workscli.py).
`nodra work serve --bg` keeps the scheduler running under the run supervisor as the run `nodra-works` (restart always, log in
~/.nodra/runs/nodra-works.log). Only one process fires cron / package triggers (the chat or the serve run), so starting both never runs a
schedule twice."""
import json
import os
import subprocess

from ..core.errors import NodraError
from . import chat, installer, runs, ui

SERVE_RUN = "nodra-works"


def _folder():
    """The chat folder, with its service home (~/.nodra/services/nodra-chat/.env) made the way `nodra chat` makes it."""
    d = chat.folder()
    installer.write_bot_files(chat.NAME, installer.inplace_bot(chat.NAME, d)[1], d)
    return d


def _serve_bg(rest):
    """`nodra work serve --bg [--hooks PORT]`: the scheduler as a supervised background run of the chat folder."""
    args = ["--works", "serve"] + [x for x in rest[1:] if x not in ("--bg", "--background")]
    return runs.start_inplace(runs.rid_of(SERVE_RUN), chat.NAME, _folder(), args=args, restart="always")


def cli(a):
    rest = list(a.rest or [])
    if rest[:1] == ["--"]:
        rest = rest[1:]
    folder = _folder()
    if rest[:1] == ["serve"] and any(x in rest for x in ("--bg", "--background")):
        code = _serve_bg(rest)
        if code:
            raise SystemExit(code)
        ui.result({"run": SERVE_RUN, "started": True})
        ui.good("Works scheduler started in the background as %s (log: nodra run logs %s -f)" % (SERVE_RUN, SERVE_RUN))
        return 0
    want_json = ui.JSON or "--json" in rest
    rest = [x for x in rest if x != "--json"]
    cmd, shell, _home, env = installer.bot_command(chat.NAME, ["--works"] + (["--json"] if want_json else []) + rest, inplace=folder)
    here = os.getcwd()                                                    # FILE / -o DIR arguments are relative to where the command was typed
    if not want_json:
        code = subprocess.call(cmd, shell=shell, cwd=here, env=env)
        if code:
            raise SystemExit(code)
        return 0
    p = subprocess.run(cmd, shell=shell, cwd=here, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       encoding="utf-8", errors="replace")
    try:
        doc = json.loads(p.stdout or "{}")
    except ValueError:
        doc = {"output": p.stdout}
    if isinstance(doc, dict) and doc.get("error"):
        raise NodraError(doc["error"])
    if p.returncode:
        tail = (p.stderr or "").strip().splitlines()
        raise NodraError(tail[-1] if tail else "nodra work failed (exit %s)" % p.returncode)
    ui.result(doc)
    return 0
