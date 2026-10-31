"""`nodra source ...` and `nodra update`: where packages come from, and keeping installed packages current."""
from ..core.errors import NodraError
from . import gitx, installer, registry, sources, ui


def _rows():
    out = []
    for s in sources.sources():
        n = len(sources.packages(s)) if s["dir"] else 0
        out.append(sources.public_view(s, n))
    return out


def _fetch_all(only=None, quiet=False):
    """Refresh the git sources (all, or the one named). -> [{"name", "changed", "rev", "error"}]. Without git: one hint, nothing fetched."""
    todo = [s for s in sources.sources() if s["kind"] == "git" or (s["kind"] == "marketplace" and sources.is_git_url(s["url"]))]
    if only:
        todo = [s for s in todo if s["name"] == only]
    if todo and not gitx.available():
        if not quiet:
            ui.note(sources.NO_GIT_HINT)
        return [{"name": s["name"], "changed": False, "rev": None, "error": "git is not installed"} for s in todo]
    out = []
    for s in todo:
        with ui.Spinner("Fetching source %s" % s["name"]) as sp:
            r = sources.fetch(s)
            if r["error"]:
                sp.problem("%s: %s" % (s["name"], r["error"].splitlines()[0] if r["error"] else "failed"))
            else:
                sp.text("%s %s" % (s["name"], "updated" if r["changed"] else "is up to date"))
        out.append(r)
    registry.reset()
    return out


def cmd_source(a):
    act = a.action or "list"
    if act == "list":
        rows = _rows()
        ui.result({"sources": rows})
        if not ui.JSON:
            ui.out()
            ui.table(["NAME", "KIND", "PACKAGES", "WHERE", "STATUS"],
                     [[ui.bold(r["name"]), r["kind"], str(r["packages"]), r["url"] + (" @ " + r["branch"] if r["branch"] else ""),
                       ui.ok("ok") if r["ok"] else ui.warn(r["error"])] for r in rows])
            for r in rows:
                if r["hint"]:
                    ui.info("%s: %s" % (r["name"], r["hint"]))
            ui.out()
            ui.info("add one: nodra source add NAME URL     refresh git sources: nodra source update")
        return
    if act == "add":
        if not (a.name and a.url):
            raise ValueError("usage: nodra source add NAME URL [--branch B] [--path P]")
        name = sources.add(a.name, a.url, a.branch or "", a.path or "")
        registry.reset()
        ui.good("source %s added" % name)
        fetched = _fetch_all(name) if sources.is_git_url(a.url) else []
        view = next(r for r in _rows() if r["name"] == name)
        ui.result({"added": name, "source": view, "fetched": fetched})
        if view["ok"]:
            ui.info("%d package(s) found" % view["packages"])
        elif view["hint"]:
            ui.note(view["hint"])
        return
    if act == "remove":
        if not a.name:
            raise ValueError("usage: nodra source remove NAME")
        name = sources.remove(a.name)
        registry.reset()
        ui.result({"removed": name})
        ui.good("source %s removed (packages already installed from it stay)" % name)
        return
    if act == "update":
        if a.name:
            sources.get(a.name)                                  # unknown name: say so
        res = _fetch_all(a.name)
        ui.result({"fetched": res})
        bad = [r for r in res if r["error"]]
        if a.name and bad:
            raise NodraError("%s: %s" % (a.name, bad[0]["error"]))
        if not res:
            ui.info("nothing to fetch: only git sources are refreshed (folders and core are read live)")
        for r in res:
            if r["error"]:
                ui.note("%s: %s" % (r["name"], r["error"].splitlines()[0]))
        return
    raise ValueError("source: list, add, remove or update")


def cmd_update(a):
    names = [n.lower() for n in (a.names or [])]
    fetched = [] if a.no_fetch else _fetch_all(quiet=ui.JSON)
    st = installer.state()
    have = {n: r for n, r in st["packages"].items() if installer.enabled(r) and (not names or n in names)}
    for n in names:
        if n not in st["packages"]:
            raise NodraError("%s is not installed (nodra install %s)" % (n, n))
    ups = registry.updates(have, constraint=lambda n: installer.constraint_on(st, n))
    if a.check:
        ui.result({"updates": ups, "fetched": fetched})
        if not ups:
            return ui.good("everything is current")
        ui.out()
        ui.table(["NAME", "INSTALLED", "AVAILABLE", "SOURCE"], [[ui.bold(u["name"]), u["installed"], u["available"], u["source"]] for u in ups])
        ui.out()
        return ui.info("apply with: nodra update")
    if not have:
        ui.result({"updates": [], "updated": [], "fetched": fetched})
        return ui.note("No matching installed packages.")
    done, failed = [], []
    for u in ups:
        ui.step("updating %s %s %s %s" % (u["name"], u["installed"], ui.ARROW, u["available"]))
        try:
            installer.install(u["name"], installer.constraint_on(installer.state(), u["name"]), True, None)
            done.append({"name": u["name"], "from": u["installed"], "to": u["available"], "source": u["source"]})
        except (NodraError, ValueError, OSError) as e:
            failed.append({"name": u["name"], "error": str(e)})
            ui.bad("%s: %s" % (u["name"], e))
    ui.result({"updates": [], "updated": done, "failed": failed, "fetched": fetched})
    if failed:
        raise ValueError("%d of %d update(s) failed" % (len(failed), len(ups)))
    ui.celebrate("%d updated" % len(done)) if done else ui.info("everything is current")
