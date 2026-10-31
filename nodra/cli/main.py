import argparse
import functools
import getpass
import json
import os
import re
import sys

from ..core import archive, ignore, manifest as M, naming, pysync, version as V
from ..core.errors import NodraError
from . import gitx, installer, paths, publish as pub, registry, sources, ui, workspace as ws
from .installer import _spec



def cmd_config(a):
    c = paths.load("config.json", {})
    if a.action == "set":
        if not (a.key and a.value is not None):
            raise ValueError("usage: nodra config set <key> <value>")
        c[a.key] = a.value
        paths.save("config.json", c)
        ui.good("%s = %s" % (a.key, "set" if ui.JSON and SECRET_KEY.search(a.key) else a.value))
    cfg = paths.config()
    ui.result(masked(cfg))
    if ui.JSON:
        return
    if a.action != "set" or not ui.TTY:
        print(json.dumps(cfg, indent=2))


SECRET_KEY = re.compile(r"token|secret|passw|credential|api_?key", re.I)


def masked(v):
    """A copy safe to print as JSON: any value under a key that looks secret becomes "set" (or "" when empty)."""
    if isinstance(v, dict):
        return {k: ("set" if x else "") if SECRET_KEY.search(str(k)) and not isinstance(x, (dict, list, bool)) else masked(x) for k, x in v.items()}
    if isinstance(v, list):
        return [masked(x) for x in v]
    return v


def _plain(a):
    """--plain / --name-only: bare lines on stdout for scripts and assistants (no spinner, colors, table or hints)."""
    return bool(getattr(a, "plain", False) or getattr(a, "name_only", False))


def _plain_line(a, name, version):
    return name if getattr(a, "name_only", False) else "%s %s" % (name, version or "-")


def cmd_search(a):
    rows = registry.search(a.term, kind=a.type, installed=installer.installed_versions())
    ui.result(rows)
    if ui.JSON:
        return
    if _plain(a):
        for p in rows:
            print(_plain_line(a, p["name"], p["version"]))
        return
    if not rows:
        ui.note("Nothing matches '%s'." % a.term if a.term else "No packages found.")
        ui.info("add a source with more packages: nodra source add NAME URL")
        return
    ui.out()
    ui.table(["NAME", "TYPE", "VERSION", "SOURCE", "DESCRIPTION"],
             [[ui.bold(ui.highlight(p["name"], a.term)), ui.badge(p["type"]), p["version"] + (ui.dim(" (installed)") if p["installed"] else ""),
               p["source"], ui.highlight((p["description"] or "").replace("\n", " "), a.term)] for p in rows[:60]])
    ui.out()
    if len(rows) > 60:
        ui.info("showing 60 of %d; narrow the search" % len(rows))
    ui.info("install one with: nodra install <name>      details: nodra info <name>")


INSTALLED_KEYS = ("version", "type", "description", "components", "path", "bot_home", "venv", "rev", "source", "tools", "shims")


def installed_view(n, r):
    return masked(dict({k: r[k] for k in INSTALLED_KEYS if k in r}, name=n, enabled=installer.enabled(r)))


def _readme(folder, rel):
    try:
        with open(os.path.join(folder, rel or "README.md"), encoding="utf-8", errors="replace") as f:
            return f.read(20000)
    except OSError:
        return ""


def info_of(name):
    """Everything `nodra info` knows about a package: the newest version's row, all versions, what it adds, what it needs."""
    d = registry.get(name)
    top = next(v for v in d["versions"] if v["version"] == d["latest_version"])
    m = top["manifest"]
    rec = installer.state()["packages"].get(d["name"])
    comps = (["skill:" + x["name"] for x in m["skills"]] + ["agent:" + x["name"] for x in m["agents"]] + ["command:" + x["name"] for x in m["commands"]]
             + ["mcp:" + x["name"] for x in m["mcp_servers"]])
    return {"name": d["name"], "version": d["latest_version"], "latest_version": d["latest_version"], "type": d["type"], "description": d["description"],
            "tags": d["tags"], "source": d["source"], "rev": top.get("rev"), "components": comps, "requires": registry.requires_of(d, d["latest_version"]),
            "versions": [{"version": v["version"], "source": v["source"]} for v in sorted(d["versions"], key=lambda v: V.parse(v["version"]), reverse=True)],
            "readme": _readme(top["dir"], m["package"]["readme"]), "authors": m["package"]["authors"], "license": m["package"]["license"],
            "installed": rec is not None, "installed_version": rec["version"] if rec else None, "enabled": installer.enabled(rec) if rec else None}


def cmd_info(a):
    d = info_of(a.name)
    ui.result(d)
    if ui.JSON:
        return
    if not ui.TTY:
        print(json.dumps({k: v for k, v in d.items() if k != "readme"}, indent=2))
        return
    meta = ["%s  v%s" % (ui.badge(d["type"]), d["version"]), "from " + d["source"]]
    lines = [d["description"] or "No description", "", ui.dim("  |  ").join(meta)]
    if d["tags"]:
        lines.append(ui.dim("tags: ") + ", ".join(d["tags"]))
    if d["components"]:
        lines.append(ui.dim("adds: ") + ", ".join(d["components"]))
    vs = d["versions"]
    if len(vs) > 1:
        lines.append(ui.dim("versions: ") + ", ".join(v["version"] for v in vs[:6]) + (" ..." if len(vs) > 6 else ""))
    if d["requires"]["packages"]:
        lines.append(ui.dim("needs: ") + ", ".join(d["requires"]["packages"]))
    if d["installed"]:
        lines.append(ui.dim("installed: ") + d["installed_version"])
    ui.out()
    ui.card(d["name"], lines, ui.dim("install  ") + ui.code("nodra install " + d["name"]))


def read_requirements(path, _seen=()):
    """Lines of a pip-style requirements file: one `name[<spec>]` per line, `#` comments, blank lines and `-r other.txt` honored."""
    path = os.path.abspath(path)
    if path in _seen:
        raise ValueError("%s includes itself through -r" % path)
    try:
        lines = open(path, encoding="utf-8-sig").read().splitlines()
    except OSError as e:
        raise ValueError("cannot read %s: %s" % (path, e.strerror or e))
    out = []
    for ln in lines:
        ln = re.split(r"(?:^|\s)#", ln, 1)[0].strip()
        if not ln:
            continue
        if ln.startswith(("-r ", "-r=", "--requirement")):
            ref = ln.split(None, 1)[1] if " " in ln else ln.split("=", 1)[1]
            out += read_requirements(os.path.join(os.path.dirname(path), ref.strip()), _seen + (path,))
        elif ln.startswith("-"):
            raise ValueError("%s: unsupported option %r (only package names and -r are read)" % (path, ln))
        else:
            out.append(ln)
    return out


def cmd_install(a):
    """Install several packages (names, folders, .zip files and/or -r files); one failing package never stops the rest."""
    specs = list(a.name or [])
    for f in a.requirement or []:
        specs += read_requirements(f)
    if not specs:
        raise ValueError("nothing to install: give package names, a folder or .zip, or -r requirements.txt")
    specs = list(dict.fromkeys(specs))               # same line twice installs once
    ui.out()
    known = set(registry.catalog())
    paths_, names = [s for s in specs if installer.looks_like_path(s, known)], [s for s in specs if not installer.looks_like_path(s, known)]
    if getattr(a, "upgrade", False):
        names = _only_newer(names)
    failed, done = [], []
    for p in paths_:
        try:
            done.append(installer.install_path(p, a.yes, a.tool))
        except (NodraError, ValueError, OSError) as e:
            failed.append((p, e))
            ui.bad("%s: %s" % (p, e))
    if len(names) == 1 and not paths_:
        n, sp = _spec(names[0])
        installer.install(n, sp, a.yes, a.tool)
        done.append(naming.normalize(n))
    elif names:
        failed += installer.install_many([_spec(s) for s in names], a.yes, a.tool)    # one plan
        done += [naming.normalize(_spec(s)[0]) for s in names if naming.normalize(_spec(s)[0]) in installer.state()["packages"]]
    ui.result({"installed": [dict(name=n, version=installer.state()["packages"][n]["version"], source=installer.state()["packages"][n].get("source"))
                             for n in dict.fromkeys(done) if n in installer.state()["packages"]],
               "failed": [{"name": n, "error": str(e)} for n, e in failed]})
    for n, e in failed:
        if n not in paths_:
            ui.bad("%s: %s" % (n, e))
    if failed:
        raise ValueError("%d of %d package(s) not installed: %s" % (len(failed), len(specs), ", ".join(n for n, _ in failed)))


def _only_newer(specs):
    """`install -u`: drop installed packages that already have the latest version the constraint allows (not installed = keep)."""
    st = installer.state()["packages"]
    keep = []
    for s in specs:
        n, sp = _spec(s)
        r = st.get(naming.normalize(n)) or st.get(n)
        if not r:
            keep.append(s)
            continue
        latest = registry.resolve(n, sp)["version"]
        if V.compare(latest, r["version"]) > 0:
            keep.append(s)
        else:
            ui.info("%s is up to date (%s)" % (n, r["version"]))
    return keep


def cmd_uninstall(a):
    users = installer.dependents(installer.state(), naming.normalize(a.name), only_enabled=False)
    if users and not a.force and ui.INTERACTIVE and not ui.confirm("%s is needed by %s. Remove anyway?" % (a.name, ", ".join(users)), False):
        ui.info("nothing changed")
        return
    installer.uninstall(a.name)



def _rc_files():
    home = os.path.expanduser("~")
    return [os.path.join(os.environ.get("ZDOTDIR") or home, ".zshrc"), os.path.join(home, ".bash_profile"), os.path.join(home, ".bashrc"),
            os.path.join(home, ".profile"), os.path.join(home, ".config", "fish", "config.fish")]


def cmd_self_uninstall(a):
    """Remove nodra's own files from this machine: installed packages, the PATH line install.py added, and ~/.nodra. The checkout stays."""
    import re
    home = paths.HOME()
    pk = sorted(installer.state()["packages"])
    rc = [f for f in _rc_files() if os.path.isfile(f) and "# >>> nodra" in open(f, encoding="utf-8", errors="replace").read()]
    ui.out()
    ui.out("  This removes nodra's data from this machine:")
    ui.out("    - %d installed package(s)%s" % (len(pk), ": " + ", ".join(pk[:6]) + (" ..." if len(pk) > 6 else "") if pk else ""))
    ui.out("    - running bots and services (nodra run, the chat) are stopped first")
    ui.out("    - the PATH line in %s" % (", ".join(rc) if rc else "your shell config (none found)"))
    ui.out("    - %s (settings, sources, the nodra command)" % home)
    ui.out("  " + ui.dim("The checkout you cloned or unzipped is not touched; delete that folder yourself."))
    if not a.yes and not (ui.INTERACTIVE and ui.confirm("Remove nodra?", False)):
        return ui.info("nothing changed (pass --yes to skip this question)")
    from . import runs
    runs.stop_all()                 # supervised bots and services end before their files and ~/.nodra go away
    for n in pk:
        try:
            installer.uninstall(n, quiet=True)
            ui.good("removed package %s" % n)
        except (NodraError, OSError) as e:
            ui.note("could not remove %s: %s" % (n, e))
    try:
        from . import credhelper
        credhelper.unregister()
    except Exception:
        pass
    for f in rc:
        try:
            text = open(f, encoding="utf-8").read()
            new = re.sub(r"\n?# >>> nodra\n.*?# <<< nodra\n?", "", text, flags=re.S)
            open(f, "w", encoding="utf-8", newline="").write(new)
            ui.good("cleaned PATH in %s" % f)
        except OSError as e:
            ui.note("could not edit %s: %s" % (f, e))
    if os.name == "nt":
        ui.note("Windows: remove %s from your user PATH (System > Environment Variables); the folder is deleted below if it is not in use" % os.path.join(home, "bin"))
    gitx.rmtree(home)
    ui.result({"removed": not os.path.exists(home), "home": home})
    ui.celebrate("nodra removed" if not os.path.exists(home) else "nodra removed, except %s (still in use; delete it by hand)" % home)
    ui.info("open a new terminal so PATH is refreshed")



def cmd_list(a):
    pk = installer.state()["packages"]
    if ui.JSON:
        return ui.result([installed_view(n, r) for n, r in sorted(pk.items())])
    if _plain(a):
        for n, r in sorted(pk.items()):
            print(_plain_line(a, n, r["version"]))
        return
    if not pk:
        ui.note("Nothing installed yet.")
        ui.info("find something with: nodra search")
        return
    ui.out()
    ui.table(["NAME", "VERSION", "STATUS", "ADDS"],
             [[ui.bold(n), r["version"], ui.ok("enabled") if installer.enabled(r) else ui.warn("disabled"),
               ", ".join(r.get("components", [])) or "-"] for n, r in sorted(pk.items())])
    ui.out()
    off = sum(1 for r in pk.values() if not installer.enabled(r))
    ui.info("%d installed%s. update all with: nodra update" % (len(pk), ", %d disabled" % off if off else ""))



def cmd_run(a):
    """Bots as supervised processes (background by default). Without a target: the installed bots and the runs on this machine."""
    from . import runs
    if not a.target:
        found = installer.bots()
        if len(found) == 1 and not runs.all_runs():
            a.target = next(iter(found))
        else:
            ui.out()
            if not found:
                ui.note("No bots or services installed. Try: nodra install nodra-bot")
            else:
                ui.table(["NAME", "TYPE", "SETTINGS"], [[ui.bold(n), installer.runnable_kind(n, r) or "bot", os.path.join(r.get("bot_home", ""), ".env")]
                                                        for n, (r, _) in sorted(found.items())])
                ui.info("run one with: nodra run NAME   (--fg: in this terminal)")
            if runs.all_runs():
                runs.cmd_list(a)
            return
    if a.target not in ("_supervise",) + RUN_ACTIONS:
        a.target = naming.normalize(a.target)
    return runs.cli(a)


RUN_ACTIONS = ("start", "stop", "quit", "kill", "restart", "pause", "list", "ls", "ps", "logs", "log", "listen", "attach", "set", "rm", "remove", "status", "show")


def cmd_onboard(a):
    """Optional guided credential setup of an installed bot (runs the bot's own onboarding script)."""
    found = installer.bots()
    name = a.name and naming.normalize(a.name)
    if not name:
        withs = [n for n, (_, mm) in found.items() if M.runnable(mm)["onboard"]]
        if len(withs) != 1:
            ui.out()
            ui.info("bots/services with guided setup: %s" % (", ".join(withs) or "none"))
            ui.info("run one with: nodra onboard NAME")
            return
        name = withs[0]
    ui.out()
    installer.onboard(name, force=True)



def cmd_knowledge(a):
    from . import knowledge
    knowledge.cli(a)


def cmd_soul(a):
    """Shortcut for `nodra knowledge get soul`: print the persona note."""
    from . import knowledge
    print(knowledge.get("soul"), end="")



def cmd_enable(a):
    ui.out()
    names = sorted(installer.state()["packages"]) if a.all else a.names
    if not names:
        raise ValueError("name a package, or use --all")
    for n in names:
        if a.all and installer.enabled(installer.state()["packages"][n]):
            continue
        installer.enable(n, a.yes, a.tool)


def cmd_disable(a):
    ui.out()
    st = installer.state()["packages"]
    names = a.names
    if a.all:
        names = [n for n, r in st.items() if installer.enabled(r)]
        a.force = True
    if not names:
        raise ValueError("name a package, or use --all")
    for n in names:
        installer.disable(n, a.force)


def cmd_tree(a):
    ui.out()
    if a.remote:
        if not a.name:
            raise ValueError("--remote needs a package name")
        n, s = _spec(a.name)
        with ui.Spinner("Resolving %s" % n):
            lines, pkgs = installer.remote_tree(n, s)
        for l in lines:
            ui.out("  " + l)
        ui.out()
        ui.info("%d package%s, %s" % (len(pkgs), "" if len(pkgs) == 1 else "s", ui.human(sum(p.get("size", 0) for p in pkgs))))
        return
    lines = installer.local_tree(a.name)
    if not lines:
        ui.note("Nothing installed yet.")
        return
    for l in lines:
        ui.out("  " + l)
    if a.name:
        users = installer.dependents(installer.state(), naming.normalize(a.name), only_enabled=False)
        if users:
            ui.out()
            ui.info("needed by: " + ", ".join(users))


def cmd_lock(a):
    lock = installer.make_lock()
    if not lock["packages"]:
        raise ValueError("nothing installed, so there is nothing to lock")
    text = json.dumps(lock, indent=2) + "\n"
    ui.result({"file": os.path.abspath(a.file), "lock": lock})
    if a.check:
        try:
            same = open(a.file, encoding="utf-8").read() == text
        except OSError:
            raise ValueError("%s does not exist (create it with: nodra lock)" % a.file)
        if not same:
            raise ValueError("%s is out of date; run: nodra lock" % a.file)
        ui.good("%s is up to date (%d packages)" % (a.file, len(lock["packages"])))
        return
    with open(a.file, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    ui.good("Locked %d packages to %s" % (len(lock["packages"]), a.file))
    ui.info("commit it; on another machine run: nodra sync")


def cmd_sync(a):
    lock = installer.read_lock(a.file)
    ui.out()
    with ui.Spinner("Resolving %d locked packages" % len(lock["packages"])):
        pkgs, todo, flips, extras, want = installer.sync_actions(lock)
    if not todo and not flips and not (extras and a.prune):
        ui.good("Already in sync with %s (%d packages)" % (a.file, len(pkgs)))
        if extras:
            ui.info("not in the lock file: %s (use --prune to remove)" % ", ".join(extras))
        return
    for p in todo:
        ui.step("install %s %s" % (p["name"], p["version"]))
    for n, on in flips:
        ui.step("%s %s" % ("enable" if on else "disable", n))
    if extras:
        (ui.step if a.prune else ui.info)("%s: %s" % ("remove" if a.prune else "not in the lock file", ", ".join(extras)))
    if a.check:
        raise ValueError("not in sync with %s" % a.file)
    if not a.yes and not ui.confirm("Apply these changes?", True):
        ui.info("nothing changed")
        return
    roots = [n for n, x in want.items() if x.get("requested")] or list(want)
    installer.install_plan(todo, a.yes, a.tool, roots=roots)
    st = installer.state()["packages"]
    for n, x in want.items():                 # restore requested/enabled flags exactly as locked
        if n in st:
            s2 = installer.state()
            s2["packages"][n]["requested"] = bool(x.get("requested"))
            installer.save_state(s2)
    for n, on in sorted(flips + [(n, x.get("enabled", True)) for n, x in want.items() if n in {p["name"] for p in todo}]):
        cur = installer.state()["packages"].get(n)
        if not cur or installer.enabled(cur) == on:
            continue
        (installer.enable(n, a.yes, a.tool) if on else installer.disable(n, True))
    if a.prune:
        for n in extras:
            installer.uninstall(n)
    ui.celebrate("in sync with %s" % a.file)



def cmd_doctor(a):
    """Local checks only: python, git, sources, AI tools, installed packages, the chat folder."""
    import shutil
    from . import integrations
    checks = []

    def check(name, ok, detail, hint=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "hint": hint})
        (ui.good if ok else ui.note)("%s: %s%s" % (name, detail, "  (%s)" % hint if hint and not ok else ""))

    ui.heading("nodra doctor")
    check("python", sys.version_info >= (3, 9), "%s (%s)" % (sys.version.split()[0], sys.executable), "Python 3.9 or newer is needed")
    git = shutil.which("git")
    check("git", git, git or "not found", "optional: needed for git sources and 'nodra upgrade'; folders, the core packages and zips work without it")
    for s in sources.sources():
        check("source %s" % s["name"], s["ok"], "%s (%s)" % (s["kind"], s["url"]), s.get("hint") or s.get("error"))
    tools = integrations.detected()
    check("AI tools", tools, ", ".join(t.label for t in tools) or "none found", "install Claude Code, Codex or OpenCode to register skills, agents and MCP servers")
    chat = os.path.isfile(os.path.join(paths.root(), "chat", "nodra.toml"))
    check("chat", chat, os.path.join(paths.root(), "chat") if chat else "chat folder missing", "re-download the repository")
    claude = shutil.which("claude")
    check("claude code", claude, claude or "not found", "optional: the chat uses it for Claude chats (free chat works with an API key)")
    n = len(installer.state()["packages"])
    check("packages", True, "%d installed" % n)
    ui.result({"checks": checks, "python": sys.version.split()[0], "git": bool(git), "packages": n, "home": paths.HOME(), "root": paths.root(),
               "tools": [t.name for t in tools], "sources": [sources.public_view(s) for s in sources.sources()]})


def cmd_welcome(a):
    """First-run tour. Local only: looks at what is installed on this machine and says what to do next."""
    from . import integrations
    ui.banner()
    ui.heading("Welcome to Nodra")
    tools = integrations.detected()
    ui.good("Found: " + ", ".join(t.label for t in tools) if tools else "No AI tools detected yet (Claude Code, Codex, OpenCode); the chat still works")
    (ui.good if gitx.available() else ui.note)("git: %s" % ("found" if gitx.available() else "not found (optional: needed for git sources and nodra upgrade)"))
    _mark_welcomed()
    ui.result({"tools": [t.name for t in tools], "git": gitx.available()})
    ui.celebrate("All set")
    ui.out()
    ui.out("  " + ui.dim("Try these next"))
    for cmd, why in (("nodra chat", "start the local chat and open it in your browser"), ("nodra search", "browse the packages"),
                     ("nodra install <name>", "add a skill, agent or MCP server"), ("nodra source add NAME URL", "add a community source"),
                     ("nodra dev init", "start your own package")):
        ui.out("    %s  %s" % (ui.accent("%-26s" % cmd), ui.dim(why)))
    ui.out()


def _mark_welcomed():
    try:
        paths.ensure()
        open(paths.p(".welcomed"), "w").close()
    except OSError:
        pass


def cmd_menu():
    """Bare `nodra` on a terminal."""
    from . import chat, sourcecmds, upgrade
    ui.banner()
    while True:
        choice = ui.select("What would you like to do?", [
            ("chat", "Open the chat"), ("search", "Search packages"), ("list", "Installed packages"), ("update", "Update installed packages"),
            ("upgrade", "Upgrade nodra itself"), ("usage", "Usage, cost and cache per tool"), ("doctor", "Check my setup"),
            ("init", "Start a new package"), ("exit", "Exit")])
        if choice in (None, "exit"):
            return
        ui.out()
        try:
            if choice == "chat":
                chat.cmd_chat(argparse.Namespace(action="open", fg=False))
            elif choice == "search":
                cmd_search(argparse.Namespace(term=input("  search for (blank = all): ").strip(), type=None, plain=False, name_only=False))
            elif choice == "list":
                cmd_list(argparse.Namespace(plain=False, name_only=False))
            elif choice == "update":
                sourcecmds.cmd_update(argparse.Namespace(names=[], check=False, no_fetch=False))
            elif choice == "upgrade":
                upgrade.cmd_upgrade(argparse.Namespace(check=False, no_restart=False))
            elif choice == "usage":
                from . import usage
                recs, meta = usage.load(usage.TOOLS, ui)
                usage.interactive(usage.report(usage.TOOLS, 30, recs=recs), ui, meta, refilter=lambda m, d: usage.report(usage.TOOLS, d, model=m, recs=recs))
            elif choice == "doctor":
                cmd_doctor(None)
            elif choice == "init":
                dev_init(argparse.Namespace(path=".", name=None, type="skill", description=None, force=False, sub=False, mono=False, wizard=False))
        except (NodraError, ValueError, KeyError) as e:
            ui.error(e, ui.hint_for(e))
        ui.out()



def cmd_usage(a):
    from . import usage
    tools = tuple(a.tool) if a.tool else usage.TOOLS
    tty = sys.stdin.isatty() and sys.stdout.isatty()
    recs, meta = usage.load(tools, ui, quiet=bool(a.json or a.plain or not tty))
    rep = usage.report(tools, a.days, model=a.model, recs=recs)
    p = usage.pick(rep, a.days)                           # the window --days selects (all time when 0)
    if a.session or a.sessions or a.tips:
        usage_rates = {}
        ss = usage.sessions_of(p["recs"], meta)
        if a.find:
            ss = usage.find_sessions(ss, a.find)
        if a.json:
            body = {"tips": usage.tips(ss)} if a.tips else {"sessions": [dict({k: v for k, v in s.items() if k not in ("reqs", "notes", "text")}, flags=usage.flags_of(s))
                                                                            for s in usage.sort_sessions(ss, a.sort)]}
            if a.session:       # additive: flags (counts), series (time, context, output, cost, flags per request), tips for this session alone
                body = {"sessions": [dict(s, notes=usage.notes_of(s), flags=usage.flags_of(s), series=usage.series_of(s, usage_rates), tips=usage.tips([s]))
                                     for s in usage.find_sessions(ss, a.session)]}
            print(json.dumps(body, default=lambda o: sorted(o)))
            return 0
        if a.tips:
            ui.heading("Efficiency tips  %s" % ui.dim(p["period"]))
            usage.show_tips(usage.tips(ss), ui)
        elif a.session:
            hit = usage.find_sessions(ss, a.session)
            if not hit:
                ui.error("no session matches %r in %s" % (a.session, p["period"].lower()), "list them: nodra usage --sessions")
                return 1
            for s in usage.sort_sessions(hit, a.sort)[:1 if len(hit) == 1 else 5]:
                usage.show_session(s, ui)
            if len(hit) > 5:
                ui.info("%d sessions match, showing 5; use a longer id" % len(hit))
        else:
            ui.heading("Sessions  %s" % ui.dim("%s, sorted by %s" % (p["period"].lower(), a.sort)))
            usage.show_sessions(usage.sort_sessions(ss, a.sort), ui, a.top)
        return 0
    if a.json:
        print(json.dumps([{k: v for k, v in dict(p, by_model=[dict(x, name="/".join(x["name"])) for x in p["by_model"]]).items() if k != "recs"} for p in rep],
                         default=lambda o: sorted(o)))
        return 0
    if not a.plain and not a.by_day and tty:
        usage.interactive(rep, ui, meta, refilter=lambda m, d: usage.report(tools, d, model=m, recs=recs), start="summary", days=a.days)
    else:
        usage.show(rep, ui, a.by_day)
    return 0



def cmd_credential(a):
    """Git credential helper protocol (get/store/erase on stdin). Registered by `nodra vault`; not meant to be typed."""
    from . import credhelper
    return credhelper.run(a.action)


def cmd_vault(a):
    """Manage the git hosts your sources live on, and their stored logins (interactive on a terminal)."""
    from . import vault
    rc = vault.run(a)
    if rc:
        raise SystemExit(rc)           # `vault test` fails the shell when a login does not work



# ---- dev
def _root(a): return os.path.abspath(a.path)


def _init_conflicts(a, d, name):
    """A package folder must not sit inside another package (the parent's archive would swallow it) nor above others (it would
    swallow them). Returns the folder to create the package in: `d`, or a better one the user picked. Raises with a ready-to-run suggestion."""
    if os.path.exists(os.path.join(d, "nodra.toml")) and not a.force:
        return d                                       # re-init of this very package: handled further down (keeps the manifest)
    rel = lambda p: os.path.relpath(p) if os.path.abspath(p).startswith(os.getcwd()) else p
    parent = pub.enclosing(d)
    if parent:
        sib = os.path.join(os.path.dirname(parent), name)
        msg = "%s is inside the package at %s (its archive would include this one)" % (rel(d), rel(parent))
        if os.path.exists(sib):
            raise ValueError("%s; use another name, or move the package out of it" % msg)
        if ui.INTERACTIVE and ui.select("%s. Where should %s go?" % (msg, name), [(sib, "next to it: %s" % rel(sib)), (None, "cancel")]):
            return sib
        raise ValueError("%s. Create it beside instead: nodra dev init %s --name %s" % (msg, rel(os.path.dirname(parent)) or ".", name)
                         + (" --sub" if os.path.dirname(parent) else ""))
    below = [p for p in pub.discover(d) if p != d] if os.path.isdir(d) else []
    if below:
        inner = os.path.join(d, name)
        msg = "%s already holds package(s) below it (%s); a package here would swallow them" % (rel(d), ", ".join(sorted(os.path.basename(p) for p in below)[:4]))
        if not os.path.exists(inner) and ui.INTERACTIVE and ui.select("%s. Create %s as its own folder instead?" % (msg, name),
                                                                        [(inner, "yes: %s" % rel(inner)), (None, "cancel")]):
            return inner
        raise ValueError("%s. Make it a sibling: nodra dev init %s --sub --name %s" % (msg, rel(d) or ".", name))
    return d


def _init_mono(a):
    """One repository, several packages. Existing packages below PATH are kept;
    new ones come from --packages "a,b:mcp" (name or name:type) or are asked for."""
    from ..core import naming
    root = _root(a)
    specs = [x.strip() for v in (a.packages or []) for x in v.split(",") if x.strip()]
    adopt = list(getattr(a, "adopt", None) or [])
    if not specs and not adopt and ui.INTERACTIVE:
        raw = input("  packages to create, comma separated (name or name:type, blank for none): ").strip()
        specs = [x.strip() for x in raw.split(",") if x.strip()]
    plan = []
    for s in specs:
        n, _, t = s.partition(":")
        t = t or a.type
        if t not in M.TYPES:
            raise ValueError("%r: type must be one of %s" % (s, ", ".join(M.TYPES)))
        plan.append((naming.validate(n), t))
    if len({n for n, _ in plan}) != len(plan):
        raise ValueError("--packages lists the same name twice")
    have = {os.path.basename(p): p for p in pub.discover(root)} if os.path.isdir(root) else {}
    clash = [n for n, _ in plan if n in have and have[n] != os.path.join(root, n)]
    if clash:
        raise ValueError("%s already exists elsewhere in this workspace (%s)" % (", ".join(clash), ", ".join(have[n] for n in clash)))
    if os.path.isfile(os.path.join(root, "nodra.toml")):
        raise ValueError("%s is itself a package; a monorepo folder holds packages in sub folders. Pick a parent folder" % root)
    ws.ensure_repo(root, a.remote or "", a.branch or "main")
    for n in adopt:                                         # existing sub folders become packages in place
        q = os.path.join(root, n)
        if not os.path.isdir(q):
            raise ValueError("%s is not a folder below %s" % (n, root))
        dev_init(argparse.Namespace(**dict(vars(a), path=q, name=naming.validate(n.lower().replace("_", "-")), sub=False, mono=False,
                                           wizard=False, force=False, _mono_member=True)))
    for n, t in plan:
        if n in have:
            ui.note("%s already exists; keeping it" % n)
            continue
        dev_init(argparse.Namespace(**dict(vars(a), path=root, name=n, type=t, sub=True, mono=False, wizard=False, force=False, _mono_member=True)))
    dirs = pub.discover(root)
    ui.celebrate("Monorepo ready: %d package(s)" % len(dirs))
    ws.show_tree(root, ws.inspect(root, dirs))
    ui.info("publish everything:  nodra dev publish %s        one package:  nodra dev publish %s --only NAME" % (a.path, a.path))


def _ask_text(label, default=""):
    ans = ui._ask("  %s %s %s " % (ui.accent("?"), label, ui.dim("[%s]" % default) if default else "")).strip()
    return ans or default


def _ask_type(default="skill"):
    types = list(M.TYPES)
    return ui.select("Package type?", [(t, t) for t in [default] + [x for x in types if x != default]]) or default


def _subdirs(root):
    """Folders directly below root that could become packages: not hidden, not build output, not already packages."""
    out = []
    for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        q = os.path.join(root, n)
        if (os.path.isdir(q) and not n.startswith(".") and n not in pub.SKIP_DIRS
                and not os.path.exists(os.path.join(q, "nodra.toml")) and not pub.discover(q, 3)):
            out.append(n)
    return out


def _init_wizard(a):
    """`dev init -w`: ask what to make of PATH, then run the same code paths the flags use."""
    from ..core import naming
    if not ui.INTERACTIVE:
        raise ValueError("--wizard needs a terminal; pass --mono / --sub / --name / --type instead")
    root = _root(a)
    here = os.path.basename(root).lower().replace("_", "-")
    ui.heading("nodra dev init wizard")
    ui.info("folder: %s" % root)
    mode = ui.select("What should this folder become?", [
        ("single", "One package: this folder is the package"),
        ("mono", "A monorepo: this folder is one git repository, each sub folder a package"),
        ("sub", "Add one more package inside this workspace (new sub folder)")])
    if not mode:
        raise ValueError("cancelled")
    ns = dict(vars(a), wizard=False)
    if mode == "single":
        name = _ask_text("Package name?", naming.validate(here) if _valid(naming, here) else "")
        ns.update(name=name, type=_ask_type(a.type), description=_ask_text("Description?", a.description or ""), sub=False, mono=False)
        return dev_init(argparse.Namespace(**ns))
    if mode == "sub":
        name = _ask_text("New package name?")
        ns.update(name=name, type=_ask_type(a.type), description=_ask_text("Description?", a.description or ""), sub=True, mono=False)
        return dev_init(argparse.Namespace(**ns))
    adopt = []
    subs = _subdirs(root)
    if subs:
        adopt = ui.select("Turn which existing sub folders into packages?", [(n, n) for n in subs], multi=True, preset=tuple(subs))
    packages = []
    if ui.confirm("Create new (empty) packages as well?", default=not adopt):
        raw = _ask_text("New packages, comma separated (name or name:type)?")
        packages = [raw] if raw else []
    kind = a.type
    if adopt:
        kind = _ask_type(a.type)
        ui.info("existing sub folders become '%s' packages (change each type in its nodra.toml)" % kind)
    remote = a.remote or _ask_text("Git remote URL for the whole repository (blank to set later)?", "")
    branch = a.branch or _ask_text("Branch?", "main")
    ns.update(mono=True, packages=packages, adopt=adopt, remote=remote or None, branch=branch, type=kind)
    return _init_mono(argparse.Namespace(**ns))


def _valid(naming, n):
    try:
        naming.validate(n)
        return True
    except ValueError:
        return False


def dev_init(a):
    if getattr(a, "wizard", False):
        return _init_wizard(a)
    if getattr(a, "mono", False):
        return _init_mono(a)
    from ..core import templates
    d = _root(a)
    from ..core import naming
    if a.sub:                                          # PATH is a workspace folder: the package gets its own folder inside it
        if not a.name:
            raise ValueError("--sub needs --name: the package is created in PATH/<name>")
        d = os.path.join(d, naming.validate(a.name))
    name = naming.validate(a.name or os.path.basename(d).lower().replace("_", "-"))
    d = _init_conflicts(a, d, name)
    os.makedirs(d, exist_ok=True)
    if getattr(a, "_mono_member", False):
        pass                                           # the workspace repository was set up once by --mono
    f = os.path.join(d, "nodra.toml")
    existing = os.path.exists(f) and not a.force
    made = []
    if not existing:
        try:
            who = getpass.getuser()                   # the OS user name
        except Exception:
            who = os.path.basename(os.path.expanduser("~")) or "unknown"
        manifest, files, execs = templates.render(a.type, name, a.description or "", [who])
        with open(f, "w") as fh:
            fh.write(manifest)
        made.append("nodra.toml")
    else:
        files, execs = {}, set()
        ui.note("nodra.toml already exists; keeping it (use --force to regenerate starter files)")
    for rel, content in files.items():
        p = os.path.join(d, rel)
        if os.path.exists(p) and not a.force:
            continue
        os.makedirs(os.path.dirname(p) or d, exist_ok=True)
        with open(p, "w", newline="\n") as fh:
            fh.write(content)
        if rel in execs:
            os.chmod(p, 0o755)
        made.append(rel)
    if pub.ensure_gitignore(d):
        made.append(".gitignore")
    ui.celebrate("Project ready: %s" % name)
    ui.tree(d, made)
    ui.out()
    ui.info("next: edit the files, then  nodra dev validate  &&  nodra dev pack   (or nodra dev publish to git-push it)")


def _load(a):
    with open(os.path.join(_root(a), "nodra.toml")) as f:
        return M.parse(f.read())


def dev_validate(a, quiet=False):
    m = _load(a)
    errs, warns = M.lint(m, _root(a))
    nested = []
    for n in sorted(os.listdir(_root(a))):                # packages below this one would ship inside its archive
        q = os.path.join(_root(a), n)
        if os.path.isdir(q) and not n.startswith(".") and n not in pub.SKIP_DIRS:
            nested += pub.discover(q, 3)
    if nested:
        warns.append("this package folder also contains other packages (%s); their files ship inside this one. Move them beside it"
                     % ", ".join(os.path.relpath(p, _root(a)) for p in nested[:3]))
    for f, got, v in pysync.check(_root(a), pysync.want(m)):
        errs.append("pyproject.toml %s %r does not match nodra.toml %r (fix with: nodra dev doctor)" % (f, got, v))
    for w in warns:
        ui.note(w)
    for e in errs:
        ui.bad(e)
    if errs:
        raise ValueError("%d problem(s) in the project; fix them and run `nodra dev validate` again" % len(errs))
    if not quiet:
        ui.good("%s %s (%s) looks good" % (m["package"]["name"], m["package"]["version"], m["package"]["type"]))
    return m


def dev_build(a):
    m = dev_validate(a, quiet=True)
    out = os.path.join(_root(a), "dist")
    os.makedirs(out, exist_ok=True)
    dest = os.path.join(out, "%s-%s.tar.gz" % (m["package"]["name"], m["package"]["version"]))
    files = [f for f in ignore.list_files(_root(a)) if not f.startswith("dist/")]
    with ui.Spinner("Packing %d files" % len(files)):
        archive.build(_root(a), files, dest)
    ui.good("Built %s" % dest)
    return dest


def _projects(a):
    """Package folders this command works on. PATH is a package (has nodra.toml) or a workspace folder holding several;
    --only NAME narrows a workspace to some (matched on folder name, relative path or package name)."""
    root = _root(a)
    found = pub.discover(root)
    if not found:
        raise ValueError("no nodra.toml in %s or the folders below it; run `nodra dev init <folder>` to start a package" % root)
    only = [x.strip().strip("/") for v in (getattr(a, "only", None) or []) for x in v.split(",") if x.strip()]
    if not only:
        return found
    def names(d):
        try:
            pkg = M.parse(open(os.path.join(d, "nodra.toml"), encoding="utf-8").read())["package"]["name"]
        except (OSError, ValueError, KeyError):
            pkg = ""
        return {os.path.basename(d), os.path.relpath(d, root).replace(os.sep, "/"), pkg}
    picked = [d for d in found if names(d) & set(only)]
    missing = [x for x in only if not any(x in names(d) for d in found)]
    if missing:
        raise ValueError("no package matches %s; found: %s" % (", ".join(missing), ", ".join(sorted(os.path.basename(d) for d in found))))
    return picked


def _label(a, d):
    return os.path.relpath(d, _root(a)).replace(os.sep, "/") if d != _root(a) else os.path.basename(d)


def _each(fn):
    """Run a single-package dev command on every package the PATH / --only selection covers; report failures at the end."""
    @functools.wraps(fn)
    def run(a):
        roots = _projects(a)
        if len(roots) == 1:
            return fn(argparse.Namespace(**dict(vars(a), path=roots[0])))
        failed = []
        for d in roots:
            ui.out()
            ui.info("== %s" % _label(a, d))
            try:
                fn(argparse.Namespace(**dict(vars(a), path=d)))
            except (NodraError, ValueError, KeyError, OSError) as e:
                ui.bad(str(e))
                failed.append(_label(a, d))
        if failed:
            raise ValueError("%d of %d packages failed: %s" % (len(failed), len(roots), ", ".join(failed)))
    return run


def dev_list(a):
    """The packages in this workspace, with their version and whether they have unpublished changes."""
    for d in _projects(a):
        try:
            pkg = M.parse(open(os.path.join(d, "nodra.toml"), encoding="utf-8").read())["package"]
        except (OSError, ValueError) as e:
            ui.bad("%s: %s" % (_label(a, d), e))
            continue
        dirty = pub.toplevel(d) and gitx.run(["status", "--porcelain", "--", "."], cwd=d)
        ui.out("  %-24s %-9s %-6s %s%s" % (pkg["name"], pkg["version"], pkg["type"], _label(a, d), "  " + ui.dim("(uncommitted changes)") if dirty else ""))


def dev_tree(a):
    """The workspace as a tree: each package and the repository it lives in."""
    roots = _projects(a)
    recs = ws.inspect(_root(a), roots)
    bad = ws.show_tree(_root(a), recs)
    if not bad:
        ui.out()
        ui.good("%d package(s), everything in sync" % len(recs))


def dev_doctor(a):
    """Check the workspace: pyproject.toml follows nodra.toml (version, description), names are unique, no nested repositories.
    Fixes the pyproject drift unless --check."""
    root = _root(a)
    dirs = _projects(a)
    ui.out()
    stuck = pydrift = 0
    recs = ws.inspect(root, dirs)
    for rec in recs:
        d = rec["dir"]
        for code, text in ws.blocking(rec):
            ui.bad("%s  %s" % (rec["name"], text))
            stuck += 1
        try:
            want = pysync.want(_load(argparse.Namespace(**dict(vars(a), path=d))))
            for f, got, v in (pysync.check if a.check else pysync.sync)(d, want):
                (ui.note if a.check else ui.good)("%s  pyproject.toml %s %r -> %r%s" % (rec["name"], f, got, v, "  (would change)" if a.check else ""))
                pydrift += 1
        except (OSError, ValueError, KeyError) as e:
            ui.bad("%s: pyproject.toml: %s" % (os.path.basename(d), e))
            stuck += 1
    ui.result({"packages": [{"name": r["name"], "version": r["version"], "type": r["type"], "problems": [t for _, t in r["problems"]]} for r in recs],
               "pyproject_changes": pydrift})
    if not stuck and not pydrift:
        ui.good("%d package(s), nothing to fix" % len(recs))
    ui.out()
    if stuck:
        ui.info("nested repositories:  nodra dev tree-solve      overview:  nodra dev tree")
        raise ValueError("%d problem(s) need your decision" % stuck)
    if pydrift and a.check:
        raise ValueError("pyproject.toml differs from nodra.toml; run `nodra dev doctor` to fix it")


def dev_tree_solve(a):
    """Resolve nested repositories. Asks per folder on a terminal; --nested merge|keep answers for all."""
    root = _root(a)
    dirs = _projects(a)
    resolved, left = ws.solve(root, dirs, mode=a.nested, remote=a.remote)
    ui.out()
    if left:
        raise ValueError("%d problem(s) still open; see `nodra dev tree`" % left)
    ui.good("workspace is clean" if not resolved else "resolved %d nested repositor%s" % (resolved, "y" if resolved == 1 else "ies"))


def _bump_version(path, part):
    """Raise `version` in the [package] table of nodra.toml (any spacing, single or double quotes). -> (old, new)."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    head = re.search(r"^[ \t]*\[package\][ \t]*(?:#.*)?$", text, re.M)
    start = head.end() if head else 0
    nxt = re.search(r"^[ \t]*\[", text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    found = []

    def sub(m):
        found.append(m.group(3))
        return m.group(1) + m.group(2) + V.bump(m.group(3), part) + m.group(2)
    body = re.sub(r"^([ \t]*version[ \t]*=[ \t]*)(['\"])([^'\"\n]*)\2", sub, text[start:end], count=1, flags=re.M)
    if not found:
        raise ValueError('cannot bump: no  version = "..."  line in the [package] table of %s' % path)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text[:start] + body + text[end:])
    return found[0], V.bump(found[0], part)


def _bump_and_sync(a, d, label, with_path):
    """--bump (rewrites the version in nodra.toml), then pyproject.toml follows nodra.toml."""
    if a.bump:
        old, new = _bump_version(os.path.join(d, "nodra.toml"), a.bump)
        ui.good("%s: version %s -> %s" % (label, old, new))
    for f, got, v in pysync.sync(d, pysync.want(_load(with_path(d)))):
        ui.good("%s: pyproject.toml %s %r -> %r" % (label, f, got, v))


def dev_publish(a):
    """Publish each selected package on its own: a problem in one is reported and skipped, the others still go out."""
    roots = _projects(a)
    top_root = _root(a)
    if len(roots) > 1 and not a.only:
        roots = ui.select("Publish which packages?", [(d, _label(a, d)) for d in roots], multi=True, preset=tuple(roots))
        if not roots:
            return ui.note("nothing selected")
    with_path = lambda d: argparse.Namespace(**dict(vars(a), path=d))
    failed, ready = [], []
    for n, d in enumerate(roots, 1):                 # phase 1: prepare. Nothing is pushed yet
        label = _label(a, d)
        tag = "[%d/%d] " % (n, len(roots)) if len(roots) > 1 else ""
        sp = ui.Spinner("%sPreparing %s" % (tag, label))
        sp.__enter__()
        try:
            block = ws.blocking(ws.inspect_package(d, top_root))
            if block:
                raise ValueError("%s (fix with: nodra dev tree-solve)" % block[0][1])
            _bump_and_sync(a, d, label, with_path)               # --bump, then pyproject.toml follows nodra.toml
            m = dev_validate(with_path(d), quiet=True)
            sp.text("%sStaging %s" % (tag, label))
            ready.append((d, pub.publish(d, m, push_now=False, commit_now=False)))      # staged only: one commit per repository below
            sp.text("%sPrepared %s" % (tag, label))
            sp.__exit__(None, None, None)
        except (NodraError, ValueError, KeyError, OSError, gitx.GitError) as e:
            sp.text("%s: %s" % (label, e))
            sp.__exit__(ValueError, e, None)
            failed.append(label)
    pushed = []
    repos = {}
    for d, info in ready:
        repos.setdefault(pub.toplevel(d), []).append((d, info))
    for top, items in repos.items():                 # phase 2: ONE commit and one push per repository
        try:
            with ui.Spinner("Committing %s" % ", ".join(i["package"] for _, i in items)):
                pub.commit_staged(top, items)
            pub.push(items[0][0])
            pushed += items
        except (gitx.GitError, ValueError) as e:
            ui.bad("push to %s failed: %s" % (gitx.redact_url(items[0][1].get("remote") or "origin"), e))
            failed += [_label(a, d) for d, _ in items]
    for d, info in pushed:
        ui.celebrate("Published %s %s" % (info["package"], info["version"]))
        if info.get("remote"):
            ui.info("repo:    %s @ %s (%s)" % (info["remote"], info["branch"], info["commit"][:8]))
        ui.info("others install it with: nodra source add NAME %s   then   nodra install %s" % (info.get("remote") or "<repo url>", info["package"]))
    ui.result({"published": [{"package": i["package"], "version": i["version"], "commit": i["commit"], "remote": i.get("remote")} for _, i in pushed],
               "failed": failed})
    if failed:
        raise ValueError("%d of %d package(s) not published: %s%s" % (len(failed), len(roots), ", ".join(failed),
                                                                 "; the other %d went out" % len(pushed) if pushed else ""))


class _CommandGroupAction(argparse.Action):
    def __init__(self, title, actions):
        super().__init__([], title, nargs=0, metavar=title, help=None)
        self.actions = actions

    def _get_subactions(self):
        return self.actions


class _GroupedSubParsersAction(argparse._SubParsersAction):
    def _get_subactions(self):
        groups = getattr(self, "command_groups", None)
        if not groups:
            return super()._get_subactions()
        by_name = {action.dest: action for action in self._choices_actions}
        return [_CommandGroupAction(title, [by_name[name] for name in names])
                for title, names in groups]


def build_parser():
    class HelpFormatter(argparse.RawDescriptionHelpFormatter):
        pass

    ap = argparse.ArgumentParser(
        prog="nodra", formatter_class=HelpFormatter,
        description=("Nodra: a local chat, Works (node workflows) and a package manager for skills, agents, MCP servers, nodes, bots and services. "
                     "Everything runs on this machine; packages come from folders and git repositories (sources)."),
        epilog=("Examples:\n"
                "  nodra chat\n"
                "  nodra search sql\n"
                "  nodra install my-skill\n"
                "  nodra install ./my-package  |  nodra install pkg.zip\n"
                "  nodra source add team https://git.example.com/team/nodra-packages.git\n"
                "  nodra update --check\n\n"
                "Settings: ~/.nodra/config.json (or $NODRA_HOME). Docs: docs/cli.md in the repository."))
    from ..core.release import VERSION as _V
    ap.add_argument("-v", "--version", action="version", version="nodra %s" % _V)
    ap.add_argument("--json", dest="json_out", action="store_true", help="Any command: one JSON document on stdout (same as the command's own --json, or NODRA_JSON=1).")
    ap.register("action", "parsers", _GroupedSubParsersAction)
    sp = ap.add_subparsers(dest="cmd", metavar="command")
    sp.command_groups = [
        ("Chat", ["chat"]),
        ("Discover", ["search", "info", "source"]),
        ("Install", ["install", "uninstall", "update", "list"]),
        ("Manage", ["enable", "disable", "tree", "lock", "sync"]),
        ("Develop", ["dev"]),
        ("Setup and maintenance", ["config", "vault", "run", "onboard", "knowledge", "soul", "usage", "welcome", "doctor", "version", "upgrade", "self-uninstall"]),
    ]

    def add(name, fn, help, description, epilog, *args):
        p = sp.add_parser(name, help=help, description=description, epilog=epilog,
                          formatter_class=HelpFormatter)
        for a in args:
            p.add_argument(*a[0], **a[1])
        if not any("--json" in a[0] for a in args):
            p.add_argument("--json", action="store_true", help=JSON_HELP)
        p.set_defaults(fn=fn)
        return p

    arg = lambda *n, **k: (n, k)
    PLAIN = (arg("--plain", action="store_true", help="One 'name version' line per package, nothing else (for scripts)."),
             arg("--name-only", action="store_true", help="One package name per line, nothing else (implies --plain)."))
    TOOL = arg("--tool", action="append", metavar="TOOL", help="Register components with this tool; repeat to select multiple (claude, codex, or opencode).")
    from . import chat as chatcmd, sourcecmds, statusline, upgrade as upg
    add("chat", chatcmd.cmd_chat, "Start the local chat (start, stop, restart, status, open).",
        "Run the chat app of this checkout (chat/) in the background through the run supervisor and open it in your browser. It listens on 127.0.0.1 only; "
        "its address is in ~/.nodra/ui/url.txt. Logs: nodra run logs nodra-chat -f.",
        "Examples:\n  nodra chat\n  nodra chat status\n  nodra chat restart\n  nodra chat stop",
        arg("action", nargs="?", default="start", choices=["start", "stop", "restart", "status", "open"], help="Default: start."),
        arg("--fg", "--foreground", dest="fg", action="store_true", help="start: run in this terminal (Ctrl-C stops it)."))
    add("config", cmd_config, "Show or change CLI configuration.",
        "Print the current configuration (~/.nodra/config.json), or set a value. Sources are managed with 'nodra source'.",
        "Examples:\n  nodra config\n  nodra config set ca_bundle /path/ca.pem",
        arg("action", nargs="?", default="show", metavar="ACTION", help="'show' (default) or 'set'."),
        arg("key", nargs="?", metavar="KEY", help="Configuration key to change when ACTION is 'set'."),
        arg("value", nargs="?", metavar="VALUE", help="New value for KEY when ACTION is 'set'."))
    add("search", cmd_search, "Search the packages of all sources.",
        "Search package names, descriptions and tags over every source (core, folders, git repositories, Claude Code marketplaces). Omitting TERM lists everything. "
        "Each row says whether the package is installed.",
        "Examples:\n  nodra search sql\n  nodra search --type workflow\n  nodra search --plain",
        arg("term", nargs="?", default="", metavar="TERM", help="Words to search for; omit to list everything."),
        arg("--type", metavar="TYPE", choices=list(M.TYPES), help="Only this package type (skill, agent, mcp, tool, setup, bot, service, workflow, node)."),
        *PLAIN)
    add("info", cmd_info, "Show package details and available versions.",
        "Show a package's description, type, newest version, source, what it adds, what it needs, and every version the sources offer.",
        "Examples:\n  nodra info nodra-guide",
        arg("name", metavar="PACKAGE", help="Package name."))
    add("install", cmd_install, "Install a package and register its components.",
        "Install a skill, agent, MCP server, tool, bot, service, workflow or node package. PACKAGE is a name from a source, a folder with a nodra.toml, or a .zip of one. "
        "Version constraints use comparison operators, for example 'name>=1.0' or 'name>=1.0,<2' (quote them). Dependencies are installed first.",
        "Examples:\n  nodra install my-skill\n  nodra install \"my-skill>=1.2\"\n  nodra install ./my-package\n  nodra install my-package-1.0.0.zip\n  nodra install -r requirements.txt --yes",
        arg("name", nargs="*", metavar="PACKAGE[<SPEC>]|PATH", help="Package names (optionally with a version constraint), folders or .zip files."),
        arg("-r", "--requirement", action="append", metavar="FILE", help="Install every package listed in FILE (one per line, # comments, nested -r); repeatable."),
        arg("-y", "--yes", action="store_true", help="Skip install-script and tool-registration prompts; use detected tools unless --tool is given."),
        TOOL,
        arg("-u", "--upgrade", action="store_true", help="Skip packages already at the newest allowed version."))
    add("uninstall", cmd_uninstall, "Remove an installed package and undo its changes.",
        "Remove the named installed package, its files and virtual environment, and revert recorded tool registrations and setup changes.",
        "Example:\n  nodra uninstall my-skill",
        arg("name", metavar="PACKAGE", help="Name of the installed package to remove."),
        arg("--force", action="store_true", help="Do not ask when other packages depend on it."))
    add("list", cmd_list, "List installed packages.",
        "Show each installed package, its version and the components it adds to your AI tools.",
        "Examples:\n  nodra list\n  nodra list --plain\n  nodra list --name-only",
        *PLAIN)
    add("update", sourcecmds.cmd_update, "Update installed packages to newer versions.",
        "Refresh the git sources (unless --no-fetch), then install newer versions of installed packages. With names, only those. "
        "--check only lists what would change. A package installed from a folder or zip has no source to update from.",
        "Examples:\n  nodra update --check\n  nodra update\n  nodra update my-skill --no-fetch",
        arg("names", nargs="*", metavar="PACKAGE", help="Installed packages to update; omit for all."),
        arg("--check", action="store_true", help="Only list the updates (name, installed, available, source)."),
        arg("--no-fetch", action="store_true", help="Do not refresh git sources first (offline)."))
    add("source", sourcecmds.cmd_source, "List, add, remove or refresh package sources.",
        "A source is a folder or a git repository that holds packages (packages/*/nodra.toml) or a Claude Code marketplace "
        "(.claude-plugin/marketplace.json). 'core' is this checkout and always exists. Git sources are cloned shallow to ~/.nodra/sources/NAME. "
        "Without git, git sources are skipped; folders keep working.",
        "Examples:\n  nodra source list\n  nodra source add team https://git.example.com/team/pkgs.git --branch main\n  nodra source add mine ~/my-packages\n"
        "  nodra source update\n  nodra source remove team",
        arg("action", nargs="?", default="list", choices=["list", "add", "remove", "update"], help="Default: list."),
        arg("name", nargs="?", metavar="NAME", help="Source name."),
        arg("url", nargs="?", metavar="URL", help="add: git URL or local folder."),
        arg("--branch", metavar="B", help="add: git branch (default: the repository's default)."),
        arg("--path", metavar="P", help="add: folder inside the source that holds the packages (default: packages)."))
    add("enable", cmd_enable, "Switch a disabled package back on.",
        "Re-register an installed but disabled package with your AI tools and put its commands back on PATH. Uses the files already on disk, so it works offline. Disabled dependencies are enabled first. 'nodra install' on a disabled package does the same.",
        "Examples:\n  nodra enable my-skill\n  nodra enable --all",
        arg("names", nargs="*", metavar="PACKAGE", help="Installed package(s) to enable."),
        arg("--all", action="store_true", help="Enable every disabled package."),
        arg("-y", "--yes", action="store_true", help="Skip prompts; register with all detected tools."),
        TOOL)
    add("disable", cmd_disable, "Switch a package off without removing it.",
        "Remove a package's skills, agents and MCP servers from your AI tools, undo its setup steps, and take its commands off PATH. The files stay, so 'nodra enable' is instant. Refuses while an enabled package depends on it unless --force.",
        "Examples:\n  nodra disable my-skill\n  nodra disable --all",
        arg("names", nargs="*", metavar="PACKAGE", help="Installed package(s) to disable."),
        arg("--all", action="store_true", help="Disable every enabled package."),
        arg("--force", action="store_true", help="Disable even if other enabled packages depend on it."))
    add("tree", cmd_tree, "Show the dependency tree.",
        "Print installed packages and what they depend on. With a package name, show just that package; with --remote, resolve it over the sources and show what installing it would add (new / already installed).",
        "Examples:\n  nodra tree\n  nodra tree my-skill\n  nodra tree \"my-skill>=1.2\" --remote",
        arg("name", nargs="?", metavar="PACKAGE", help="Package (with --remote, optionally with a version constraint)."),
        arg("--remote", action="store_true", help="Resolve over the sources instead of reading what is installed."))
    add("lock", cmd_lock, "Write a lock file of the exact installed versions.",
        "Record every installed package with its exact version, source revision, dependencies and enabled state in nodra.lock (JSON). Commit it so a teammate or CI can reproduce the same set with 'nodra sync'.",
        "Examples:\n  nodra lock\n  nodra lock --check",
        arg("-f", "--file", default="nodra.lock", metavar="FILE", help="Lock file path (default: nodra.lock)."),
        arg("--check", action="store_true", help="Do not write; fail if the file does not match what is installed."))
    add("sync", cmd_sync, "Make this machine match a lock file.",
        "Install the exact versions in the lock file, enable or disable packages as locked, and optionally remove packages that are not in it. The sources must offer those versions.",
        "Examples:\n  nodra sync\n  nodra sync --check\n  nodra sync --yes --prune",
        arg("-f", "--file", default="nodra.lock", metavar="FILE", help="Lock file path (default: nodra.lock)."),
        arg("--check", action="store_true", help="Only report differences; exit 1 if not in sync."),
        arg("--prune", action="store_true", help="Also uninstall packages that are not in the lock file."),
        arg("-y", "--yes", action="store_true", help="Do not ask before applying; use detected tools."),
        TOOL)
    add("doctor", cmd_doctor, "Check this machine: python, git, sources, AI tools.",
        "Local checks only: Python version, whether git is installed, whether every source can be read, which AI tools are detected, how many packages are installed, and whether the chat folder is there.",
        "Example:\n  nodra doctor")
    add("statusline", statusline.cmd_statusline, "Show Claude subscription limits in the chat (Claude Code status line bridge).",
        "Without an action this IS a Claude Code status line: it keeps the rate_limits Claude Code passes to status lines (5-hour and weekly use, "
        "for Claude subscribers) in ~/.nodra/ui/limits-statusline.json for the chat's Usage page, then prints your previous status line. "
        "install / remove set or restore statusLine in ~/.claude/settings.json. Opt-in; nothing is sent anywhere.",
        "Examples:\n  nodra statusline install\n  nodra statusline status\n  nodra statusline remove",
        arg("action", nargs="?", default=None, choices=["install", "remove", "status"], help="Omit to run as the status line."))
    add("version", upg.cmd_version, "Show the nodra version.", "Print the version and the checkout this CLI runs from.", "Example:\n  nodra version")
    add("upgrade", upg.cmd_upgrade, "Update nodra itself (git pull of this checkout) and restart the chat.",
        "Fast-forward this checkout to the newest commit of its git remote, then restart the chat if it is running. A copy without git (a downloaded zip) cannot update itself; it says how to refresh it. "
        "--check only reports whether a newer version exists.",
        "Examples:\n  nodra upgrade --check\n  nodra upgrade\n  nodra upgrade --no-restart",
        arg("--check", action="store_true", help="Only report whether the checkout is behind its remote."),
        arg("--no-restart", action="store_true", help="Pull only; leave the running chat alone (the chat uses this to restart itself once idle)."))
    add("welcome", cmd_welcome, "First-run tour: what was found and what to try.",
        "Look at this machine (AI tools, git) and print the next steps. Local only.",
        "Examples:\n  nodra welcome",
        arg("-y", "--yes", action="store_true", help="Accepted for scripts; the tour never asks anything."))
    add("vault", cmd_vault, "Add, edit or remove git hosts and their logins.",
        "Manage the git hosts your sources live on. Logins go to the git credential helper (Keychain, DPAPI, Secret Service or a 0600 file); vault.json keeps only host and user name. On a terminal, bare 'nodra vault' opens a menu and missing values are prompted for (token hidden).",
        "Examples:\n  nodra vault\n  nodra vault add https://git.example.com --user sam\n  nodra vault test https://git.example.com\n  printf %s \"$TOKEN\" | nodra vault edit git.example.com --token-stdin\n  nodra vault remove git.example.com --yes",
        arg("action", nargs="?", choices=["list", "add", "edit", "remove", "test"], help="Default: menu on a terminal, else list. test: check that a stored login reaches its host."),
        arg("remote", nargs="?", metavar="REMOTE", help="Git URL or host (add: URL; edit/remove: host)."),
        arg("--user", metavar="NAME", help="Git user name."),
        arg("--token-stdin", action="store_true", help="Read the token/password from standard input."),
        arg("-y", "--yes", action="store_true", help="Do not ask before removing."))
    add("run", cmd_run, "Run bots and services in the background: start, stop, list, logs, schedule.",
        "Start a bot or service package (type bot or service; a service restarts always by default, or as its [service] restart / schedule says) under a small supervisor, in the background by default: its output goes to ~/.nodra/runs/NAME.log, it restarts on failure (--restart) or runs on a schedule (--schedule). The chat itself is started with 'nodra chat'.",
        "Examples:\n  nodra run nodra-bot -- --cron\n  nodra run nodra-bot --fg\n  nodra run nodra-bot --name digest --schedule '0 8 * * 1-5' -- --once 'summarize yesterday'\n  nodra run list\n  nodra run logs digest -f\n  nodra run set digest --schedule 2h --restart on-failure\n  nodra run stop --all",
        arg("target", nargs="?", metavar="BOT|ACTION", help="Installed bot or service to start, or an action: start, stop, pause, restart, list, logs, listen, set, status, rm."),
        arg("args", nargs="*", metavar="ARG", help="Run name for an action; for a start, passed to the bot (put -- before options)."),
        arg("--name", metavar="NAME", help="Name of the run (default: the bot name); start the same bot several times under different names."),
        arg("--fg", "--foreground", dest="fg", action="store_true", help="Run in this terminal (stdin attached, output shown and logged); Ctrl-C stops it."),
        arg("--schedule", metavar="WHEN", help="Run on a schedule: seconds, 30s/5m/2h/1d, or a cron expression ('0 8 * * 1-5'). With set: '' removes it."),
        arg("--restart", choices=["no", "on-failure", "always"], help="Restart rule when the bot ends (default: the package's [bot]/[service] restart, else on-failure (service: always); no with --schedule or --fg)."),
        arg("--venv", metavar="PATH", help="Run with this virtualenv (its python, VIRTUAL_ENV, its bin first on PATH). Remembered for the package, also for restarts; 'default' clears it. Without it: .venv/venv in the bot or package folder, the package's own venv, then nodra's python."),
        arg("--python", metavar="PATH", help="Run with this python interpreter (remembered like --venv)."),
        arg("-f", "--follow", action="store_true", help="logs: keep printing new output (Ctrl-C stops)."),
        arg("-n", "--lines", type=int, default=40, metavar="N", help="logs: lines to show (default 40)."),
        arg("--all", action="store_true", help="stop: every running run."),
        arg("--clear-args", action="store_true", help="set: remove the saved bot arguments."),
        arg("--force", action="store_true", help="rm: stop it first if it runs."),
        arg("--json", action="store_true", help="list/status: JSON output."))
    add("onboard", cmd_onboard, "Optional guided credential setup for an installed bot.",
        "Runs the bot's own onboarding script (for example the Teams bot signs you in with the Teams Developer CLI and writes CLIENT_ID, CLIENT_SECRET and TENANT_ID into the bot's .env).",
        "Examples:\n  nodra onboard\n  nodra onboard nodra-teams-bot",
        arg("name", nargs="?", metavar="BOT", help="Installed bot; optional when only one has guided setup."))
    add("knowledge", cmd_knowledge, "Your personal notes and bot persona (soul): local markdown files.",
        "Notes are markdown files in ~/.nodra/knowledge. 'soul' is the persona bots load first. Nothing is synced anywhere.",
        "Examples:\n  nodra knowledge get soul\n  nodra knowledge edit soul\n  nodra knowledge list\n  nodra knowledge path",
        arg("action", nargs="?", default="list", choices=["list", "get", "edit", "path"], help="Default: list."),
        arg("name", nargs="?", metavar="NOTE", help="Note name (get/edit)."))
    add("soul", cmd_soul, "Print your soul (persona) note.",
        "Shortcut for 'nodra knowledge get soul': the persona note, written to stdout so an assistant or script can read it.",
        "Examples:\n  nodra soul\n  nodra soul > soul.md")
    add("credential", cmd_credential, "Git credential helper used for your source hosts.",
        "Speaks git's credential protocol so a login you type once is remembered: macOS Keychain, Windows DPAPI, Linux Secret Service, else a private 0600 file. 'nodra vault' registers it for your hosts only; you never call it yourself.",
        "Example:\n  git config --global --get-all credential.https://git.example.com.helper",
        arg("action", choices=["get", "store", "erase"], help="Credential protocol action."))
    add("usage", cmd_usage, "Local usage report per AI tool: sessions, models, tokens, cache and estimated cost.",
        "Read the session logs of the AI tools on this machine (Claude Code ~/.claude/projects, Codex ~/.codex/sessions) and show sessions, requests, tokens, cache use and an ESTIMATED price for today, the last N days and all time, by tool and by model. Purely local: nothing is sent anywhere. Prices come from the nodra-prices package.",
        "Examples:\n  nodra usage\n  nodra usage --days 7 --sessions\n  nodra usage --session 3f9a1c2b\n  nodra usage --tips --days 14\n  nodra usage --by-day --days 14\n  nodra usage --tool claude --days 7 --plain\n  nodra usage --json",
        arg("--tool", action="append", choices=["claude", "codex", "nodra-chat"], help="Only this tool (repeatable)."),
        arg("--days", type=int, default=30, help="Last N days: one of the windows (with today, this month and all time), and the window of --sessions/--session/--tips (default 30, 0 = all time). In the full screen view press n to type another number."),
        arg("--sessions", action="store_true", help="List sessions (last used, tool, project, requests, peak context, cache hit, cost, title) and exit."),
        arg("--session", metavar="ID_OR_TEXT", help="Show one session: totals, context per request and cache rebuild flags. Matches an id (the last 8 characters are enough), title or folder."),
        arg("--tips", action="store_true", help="Efficiency suggestions from your own usage (cold cache rebuilds, huge context, low cache hit, model choice)."),
        arg("--find", metavar="TEXT", help="With --sessions/--tips: only sessions whose id, title, folder, tool or model contains TEXT."),
        arg("--sort", choices=["recent", "cost", "ctx", "requests"], default="recent", help="Order of --sessions (default recent)."),
        arg("--top", type=int, default=30, help="Rows shown by --sessions (default 30, 0 = all)."),
        arg("--model", help="Case-insensitive regex on 'tool model', e.g. 'opus|gpt' (in the interactive view type /regex)."),
        arg("--by-day", action="store_true", help="One row per day instead of by tool and model."),
        arg("--plain", action="store_true", help="Print every period and exit (default in a terminal is a full screen view: arrows and mouse, 1-4 period, n custom days, m summary, s sessions, d days, t tips, / model filter, f find, q quit)."),
        arg("--json", action="store_true", help="Machine readable output (includes by_day)."))
    add("self-uninstall", cmd_self_uninstall, "Remove nodra's data from this machine.",
        "Uninstall every installed package, delete the PATH line that install.py added to your shell config, and delete the nodra folder (~/.nodra, or $NODRA_HOME). Asks first unless --yes. The checkout you cloned stays.",
        "Examples:\n  nodra self-uninstall\n  nodra self-uninstall --yes",
        arg("-y", "--yes", action="store_true", help="Do not ask for confirmation."))

    dev = sp.add_parser("dev", help="Create, validate, pack and publish packages of your own.",
                        description="Develop a Nodra package from a nodra.toml project: generate starter files, lint the manifest, build or zip it, push it to git, and keep a Claude Code marketplace file.",
                        epilog="Examples:\n  nodra dev init . --type skill --name my-skill\n  nodra dev validate\n  nodra dev pack ./my-skill -o my-skill.zip\n  nodra dev publish --bump patch\n  nodra dev marketplace --check",
                        formatter_class=HelpFormatter)
    ds = dev.add_subparsers(dest="dcmd", required=True, metavar="command")
    from . import devtools
    dev_commands = [
        ("init", dev_init, "Create starter files for a package project.",
         "Create a nodra.toml manifest and starter files for the selected package type in PATH. Existing generated files are left alone unless --force is used; --force overwrites generated starter files.",
         "Examples:\n  nodra dev init . --type skill --name my-skill\n  nodra dev init ./server --type mcp --description \"Example MCP server\"\n  nodra dev init packages --sub --name my-skill   (-> packages/my-skill, next to the other packages)",
         [arg("--name", metavar="NAME", help="Package name (default: derived from the project directory)."),
          arg("--type", default="skill", choices=list(M.TYPES), metavar="TYPE", help="Starter package type (default: skill)."),
          arg("--description", metavar="TEXT", help="Starter package description."),
          arg("--sub", action="store_true", help="Create the package in its own folder PATH/NAME, for a folder that holds several packages (needs --name)."),
          arg("--mono", action="store_true", help="PATH becomes one git repository holding several packages (see --packages). Packages already below PATH are kept."),
          arg("--packages", action="append", metavar="LIST", help="With --mono: packages to create, comma separated, each NAME or NAME:TYPE (e.g. --packages guide,tools:mcp)."),
          arg("--remote", metavar="URL", help="With --mono: git remote for the whole repository (asked once when omitted)."),
          arg("--branch", metavar="BRANCH", help="With --mono: branch to publish (default: main)."),
          arg("-w", "--wizard", action="store_true", help="Interactive setup wizard: choose one package, a monorepo (and which sub folders become packages), or a new package in this workspace."),
          arg("--force", action="store_true", help="Overwrite generated starter files that already exist.")]),
        ("validate", dev_validate, "Validate and lint the package project.",
         "Parse and normalize PATH/nodra.toml, then lint the manifest and referenced package files. Report warnings and fail if validation errors are found.",
         "Example:\n  nodra dev validate ./my-skill", []),
        ("build", dev_build, "Validate and build a package archive (.tar.gz).",
         "Validate the project, collect files selected by the project's ignore rules, and write a versioned .tar.gz archive under PATH/dist/. For a file you can install anywhere, use 'nodra dev pack'.",
         "Example:\n  nodra dev build ./my-skill", []),
        ("pack", devtools.dev_pack, "Zip one package so anyone can 'nodra install' it.",
         "Zip the package folder PATH (nodra.toml at the zip root; .git, __pycache__, .venv, node_modules, dist and ignored files are skipped). The zip installs with 'nodra install FILE.zip' and imports in the chat.",
         "Examples:\n  nodra dev pack ./my-skill\n  nodra dev pack ./my-skill -o /tmp/my-skill.zip",
         [arg("-o", "--output", metavar="OUT.zip", help="Zip file to write (default: NAME-VERSION.zip in the current folder).")]),
        ("marketplace", devtools.dev_marketplace, "Write the Claude Code marketplace file of this repository.",
         "Generate <root>/.claude-plugin/marketplace.json from the packages/ that have skills, agents, slash commands or MCP servers, so Claude Code users can add this repository as a marketplace. "
         "--check writes nothing and exits 1 when the file is stale.",
         "Examples:\n  nodra dev marketplace\n  nodra dev marketplace --check",
         [arg("--check", action="store_true", help="Only compare; exit 1 if the file is missing or stale.")]),
        ("publish", dev_publish, "Publish a package: git commit and push.",
         "Optionally bump the version in nodra.toml, validate the package, commit it and push the repository it lives in (a repository is created when there is none). Others add that repository as a source.",
         "Examples:\n  nodra dev publish\n  nodra dev publish --bump patch",
         [arg("--bump", choices=["major", "minor", "patch"], metavar="PART", help="Increment this version part before publishing (major/minor/patch; lower parts reset).")]),
        ("tree", dev_tree, "Show the packages here as a tree, with repository status.",
         "Show every package below PATH (or the one in PATH) with its version and type, and the git repository it belongs to. Lists what to fix and the command that fixes it.",
         "Example:\n  nodra dev tree ./packages", []),
        ("doctor", dev_doctor, "Check the workspace and keep pyproject.toml in step with nodra.toml.",
         "For the package in PATH, or every package below it: pyproject.toml version and description follow nodra.toml, package names are unique, and no package folder hides a nested git repository. Problems it cannot decide for you are listed.",
         "Examples:\n  nodra dev doctor\n  nodra dev doctor ./packages\n  nodra dev doctor --check",
         [arg("--check", action="store_true", help="Only report what would change; exit with an error if anything is out of date.")]),
        ("tree-solve", dev_tree_solve, "Resolve nested git repositories in the workspace.",
         "Find package folders that hold their own .git inside another repository (the outer repository cannot publish those files) and resolve them. `merge` folds the folder into the outer repository and moves its old .git to ~/.nodra/backups; `keep` leaves it a separate repository and makes the outer one ignore it. On a terminal it asks per folder.",
         "Examples:\n  nodra dev tree-solve\n  nodra dev tree-solve --nested merge",
         [arg("--nested", choices=["merge", "keep"], metavar="MODE", help="Answer for every nested repository: merge or keep."),
          arg("--remote", metavar="URL", help="Also set the outer repository's origin to this URL.")]),
        ("list", dev_list, "List the packages in this folder.",
         "Show every package (folder with a nodra.toml) in PATH or below it, with its version and whether it has uncommitted changes. Use the names with --only.",
         "Example:\n  nodra dev list ./packages", []),
    ]
    for n, fn, help, description, epilog, extra in dev_commands:
        p = ds.add_parser(n, help=help, description=description, epilog=epilog,
                          formatter_class=HelpFormatter)
        p.add_argument("path", nargs="?", default=None if n == "marketplace" else ".", metavar="PATH",
                       help="Package directory containing nodra.toml, or a folder holding several packages (default: current directory)." if n != "marketplace"
                       else "Repository root (default: the checkout this CLI runs from).")
        for e in extra:
            p.add_argument(*e[0], **e[1])
        if not any("--json" in e[0] for e in extra):
            p.add_argument("--json", action="store_true", help=JSON_HELP)
        if n not in ("init", "list", "marketplace"):
            p.add_argument("--only", action="append", metavar="NAME", help="In a folder of several packages, work on just these (folder or package name; repeat or comma-separate).")
        p.set_defaults(fn=fn if n in ("init", "list", "publish", "tree", "doctor", "tree-solve", "marketplace") else _each(fn))
    return ap


JSON_HELP = "Print one JSON document on stdout: {ok, command, data, messages, changes, context, error, hint} (docs/cli.md, JSON output)."
NO_ENVELOPE = ("credential",)                                     # git reads these streams itself
NATIVE_JSON = ("usage",)                                          # its own --json keeps its own shape; `nodra --json usage` wraps it
JSON_SCHEMA = 1


def json_wanted(a):
    if not getattr(a, "cmd", None) or a.cmd in NO_ENVELOPE or a.cmd == "run" and getattr(a, "target", None) == "_supervise":
        return False
    if getattr(a, "json_out", False) or (os.environ.get("NODRA_JSON") or "").lower() in ("1", "true", "yes", "on"):
        return True
    return bool(getattr(a, "json", False)) and a.cmd not in NATIVE_JSON


def _context():
    """Where we are: the CLI version, NODRA_HOME, the checkout, the sources and whether git exists. No secrets."""
    from ..core.release import VERSION
    try:
        srcs = [{"name": s["name"], "url": s["url"], "kind": s["kind"], "ok": s["ok"]} for s in sources.sources(rev=False)]
    except Exception:
        srcs = []
    return {"cli_version": VERSION, "home": paths.HOME(), "root": paths.root(), "sources": srcs, "git": gitx.available()}


def _pkg_snapshot():
    try:
        return {n: (r.get("version"), installer.enabled(r)) for n, r in installer.state()["packages"].items()}
    except Exception:
        return {}


def _changes(before, after):
    out = {"installed": [], "removed": [], "updated": [], "enabled": [], "disabled": []}
    for n, (v, on) in sorted(after.items()):
        if n not in before:
            out["installed"].append({"name": n, "version": v})
        else:
            v0, on0 = before[n]
            if v != v0:
                out["updated"].append({"name": n, "from": v0, "to": v})
            if on != on0:
                out["enabled" if on else "disabled"].append(n)
    out["removed"] = [{"name": n, "version": before[n][0]} for n in sorted(before) if n not in after]
    return {k: v for k, v in out.items() if v}


def _json_envelope(a, body):
    """Run body() with nothing reaching stdout but ONE JSON document. ui lines are recorded; stray prints are captured (and parsed as the
    data when they are JSON, e.g. `run list`); child processes (install scripts, git, pip) write to stderr instead of stdout."""
    import io
    ui.json_mode()
    if hasattr(a, "json"):
        a.json = True                       # commands with their own JSON output use it; welcome stays quiet
    # never forced to --yes: without a terminal each command takes its safe non-interactive default (self-uninstall refuses, ...)
    sys.stdout.flush()
    real = os.dup(1)
    os.dup2(2, 1)
    cap, keep = io.StringIO(), sys.stdout
    sys.stdout = cap
    before = _pkg_snapshot()
    sub = next((getattr(a, k) for k in ("dcmd", "action", "target", "area") if isinstance(getattr(a, k, None), str)), None)
    env = {"schema": JSON_SCHEMA, "ok": True, "command": a.cmd + (" " + sub if sub else ""), "exit": 0, "error": None, "hint": None}
    try:
        body()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if not isinstance(e.code, (int, type(None))):
            env["error"] = str(e.code)
        env.update(exit=code, ok=code == 0)
    except (NodraError, ValueError, KeyError, OSError) as e:
        env.update(ok=False, exit=1, error=str(e), hint=ui.hint_for(e))
    except KeyboardInterrupt:
        env.update(ok=False, exit=130, error="interrupted")
    except Exception as e:                  # a bug must still produce a document the UI can read
        env.update(ok=False, exit=1, error="%s: %s" % (type(e).__name__, e))
    finally:
        sys.stdout = keep
        os.dup2(real, 1)
        os.close(real)
    if ui.DATA.get("error") and env["ok"]:
        env.update(ok=False, exit=env["exit"] or 1)
    env["error"] = env["error"] or ui.DATA.get("error")
    env["hint"] = env["hint"] or ui.DATA.get("hint")
    text = cap.getvalue()
    data = ui.DATA.get("data")
    if "data" not in ui.DATA and text.strip():
        try:
            data = json.loads(text)
            text = ""
        except ValueError:
            pass
    env.update(data=masked(data), output=text or None, messages=list(ui.LOG), changes=_changes(before, _pkg_snapshot()), context=_context())
    _emit_json(env)
    return env["exit"]


def _emit_json(env):
    sys.stdout.write(json.dumps(env, indent=2, default=str) + "\n")
    sys.stdout.flush()
    return env["exit"]


def _json_argv(argv):
    args = sys.argv[1:] if argv is None else list(argv)
    return "--json" in args[:args.index("--")] if "--" in args else "--json" in args or \
        (os.environ.get("NODRA_JSON") or "").lower() in ("1", "true", "yes", "on")


def main(argv=None):
    ap = build_parser()
    if _json_argv(argv):
        import io
        err, keep = io.StringIO(), sys.stderr
        sys.stderr = err
        try:
            a = ap.parse_args(argv)
        except SystemExit as e:           # bad command line: still one JSON document (help text with --help)
            sys.stderr = keep
            if not e.code:
                return 0
            msg = [x for x in err.getvalue().splitlines() if x.strip()]
            _emit_json({"schema": JSON_SCHEMA, "ok": False, "command": None, "exit": 2, "error": (msg[-1] if msg else "bad arguments").split("error: ", 1)[-1],
                        "hint": "nodra CMD --help", "data": None, "output": err.getvalue() or None, "messages": [], "changes": {}, "context": _context()})
            return 2
        finally:
            sys.stderr = keep
    else:
        a = ap.parse_args(argv)
    from . import tls
    if json_wanted(a):
        def body():
            code = _main(a, ap, tls)
            if code:
                raise SystemExit(code)
        return _json_envelope(a, body)
    return _main(a, ap, tls)


def _main(a, ap, tls):
    try:
        if not getattr(a, "cmd", None):
            if not ui.INTERACTIVE:
                ap.print_help()
                return 0
            if not os.path.exists(paths.p(".welcomed")):
                cmd_welcome(argparse.Namespace(yes=False))
                return 0
            cmd_menu()
            return 0
        if a.cmd == "credential" or a.cmd == "run" and a.target == "_supervise":
            return a.fn(a)              # git calls this on every fetch / the detached supervisor: nothing else runs
        tls.warn_if_insecure()
        a.fn(a)
    except (NodraError, ValueError, KeyError, OSError) as e:
        ui.error(e, ui.hint_for(e))
        return 1
    except KeyboardInterrupt:
        ui._cursor(True)
        sys.stdout.write("\n")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
