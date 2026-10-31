"""`nodra knowledge`: personal notes (markdown files in ~/.nodra/knowledge) for bots and tools.
`soul.md` is the persona every bot loads first. Stdlib only."""
import os
import re
import subprocess

from . import paths, ui

NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SOUL = "# Soul\n\nWho the assistant is for me: tone, language, what to always / never do.\n\n- Be brief and concrete.\n- Ask before anything destructive.\n"


def folder():
    return paths.ensure("knowledge")


def _file(name):
    n = name[:-3] if name.endswith(".md") else name
    if not NAME.match(n):
        raise ValueError("note name: lowercase letters, digits, . _ - (max 64)")
    return n, os.path.join(folder(), n + ".md")


def local():
    return sorted(f[:-3] for f in os.listdir(folder()) if f.endswith(".md"))


def get(name):
    """Body of a note, printed as is."""
    n, p = _file(name)
    if not os.path.isfile(p):
        raise ValueError("no note '%s' (nodra knowledge list)" % name)
    with open(p, encoding="utf-8") as f:
        return f.read()


def cli(a):
    act = a.action
    if act == "get":
        if not a.name:
            raise ValueError("name the note: nodra knowledge get soul")
        body = get(a.name)
        ui.result({"name": _file(a.name)[0], "body": body})
        print(body, end="" if body.endswith("\n") else "\n")          # plain stdout: pipe it into a prompt or a file
        return
    ui.out()
    if act == "path":
        ui.result({"path": folder()})
        ui.out(folder())
    elif act == "list":
        names = local()
        ui.result({"folder": folder(), "notes": [{"name": n, "path": os.path.join(folder(), n + ".md")} for n in names]})
        if not names:
            ui.info("no notes yet. create one: nodra knowledge edit soul")
        else:
            ui.table(["NOTE"], [[ui.bold(n)] for n in names])
        ui.info("folder: " + folder())
    elif act == "edit":
        if not a.name:
            raise ValueError("name the note: nodra knowledge edit soul")
        n, p = _file(a.name)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write(SOUL if n == "soul" else "# %s\n\n" % n)
        ui.result({"name": n, "path": p})
        ed = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if ed and ui.INTERACTIVE:
            subprocess.call(ed.split() + [p])
        else:
            ui.info("edit this file:")
            ui.out(p)
