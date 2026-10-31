"""The package registry: every package of every source (see sources.py), with version resolution and dependency planning.

A catalog entry is the newest version's row plus all versions:
  {"name", "type", "description", "tags", "latest_version", "source", "versions": [{"version", "source", "rev", "dir", "manifest", "requires",
   "synthetic"}]}
When several sources offer the same name and version, the first source wins (core first, then the order in config.json)."""
import contextlib
import os
import shutil
import tempfile

from ..core import archive, manifest as M, naming, version as V
from ..core.errors import NodraError
from . import sources


_SESSION = None         # catalog cache while a plan / update check runs (one read of every source instead of one per package)
_LOCAL = {}             # packages given as a folder or zip for the current install: name -> candidate


def reset():
    global _SESSION
    _SESSION = None


@contextlib.contextmanager
def session():
    global _SESSION
    keep = _SESSION
    _SESSION = catalog() if keep is None else keep
    try:
        yield
    finally:
        _SESSION = keep


def catalog():
    """{name: entry} over all sources (no network)."""
    if _SESSION is not None:
        return _SESSION
    cands = list(_LOCAL.values())             # a folder or zip given to `install` wins over a source that has the same version
    for s in sources.sources():
        cands += sources.packages(s)
    out = {}
    for c in cands:
        e = out.setdefault(c["name"], {"name": c["name"], "versions": []})
        if any(v["version"] == c["version"] for v in e["versions"]):
            continue
        e["versions"].append({k: c.get(k) for k in ("version", "source", "rev", "dir", "manifest", "requires", "synthetic", "raw", "type")})
    for e in out.values():
        top = V.latest([v["version"] for v in e["versions"]])
        v = next(v for v in e["versions"] if v["version"] == top)
        m = v["manifest"]["package"]
        e.update(type=m["type"], description=m["description"], tags=list(m["tags"]), latest_version=top, source=v["source"])
    return out


def get(name):
    p = catalog().get(naming.normalize(name))
    if not p:
        raise NodraError("package '%s' is not in any source (nodra search)" % name)
    return p


def installed_view(installed):
    return {naming.normalize(k): v for k, v in (installed or {}).items()}


def search(term="", kind=None, installed=None):
    """Matches on name, description and tags. Each row: name, version, type, description, tags, source, installed, installed_version."""
    words = (term or "").lower().split()
    have = installed_view(installed)
    out = []
    for p in catalog().values():
        if kind and p["type"] != kind:
            continue
        hay = " ".join([p["name"], p.get("description") or "", " ".join(p.get("tags") or [])]).lower()
        if all(w in hay for w in words):
            rec = have.get(p["name"])
            out.append({"name": p["name"], "version": p["latest_version"], "latest_version": p["latest_version"], "type": p["type"],
                        "description": p["description"], "tags": p["tags"], "source": p["source"],
                        "installed": rec is not None, "installed_version": rec})
    return sorted(out, key=lambda r: r["name"])


def versions(p):
    return [v["version"] for v in p.get("versions") or []] or ([p["latest_version"]] if p.get("latest_version") else [])


def pick(p, spec=""):
    ok = [v for v in versions(p) if V.satisfies(v, spec or "")]
    if not ok:
        raise NodraError("no version of %s satisfies '%s' (have: %s)" % (p["name"], spec, ", ".join(versions(p)) or "none"))
    return V.latest(ok)


def current_os():
    import platform
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system(), "linux")


def requires_of(p, ver):
    v = next((v for v in p.get("versions") or [] if v["version"] == ver), {})
    r = v.get("requires") or {}
    return {"os": list(r.get("os") or []), "commands": list(r.get("commands") or []), "packages": list(r.get("packages") or [])}


def resolve(name, spec=""):
    p = get(name)
    ver = pick(p, spec)
    v = next(v for v in p["versions"] if v["version"] == ver)
    return {"name": naming.normalize(p["name"]), "version": ver, "manifest": v["manifest"], "requires": requires_of(p, ver), "type": v["manifest"]["package"]["type"],
            "source": v["source"], "rev": v.get("rev"), "dir": v["dir"], "synthetic": bool(v.get("synthetic")), "raw": v.get("raw"), "sha256": ""}


def plan(roots, installed=None):
    """Dependency-first list of resolved packages. Constraints from every dependent are combined, so a package
    shared by two others gets one version that satisfies both; a conflict names who required what.
    Installed packages that already satisfy their constraints are left out."""
    with session():
        return _plan(roots, installed)


def _plan(roots, installed):
    have = {naming.normalize(k): str(v) for k, v in (installed or {}).items()}
    need, chosen, queue, rootset = {}, {}, [], set()

    def add(name, spec, by):
        n = naming.normalize(str(name))
        need.setdefault(n, []).append((str(spec or "").strip(), by))
        queue.append(n)
        return n

    for x in roots:
        rootset.add(add(x["name"], x.get("spec"), None))
    steps = 0
    while queue:
        steps += 1
        if steps > 5000:
            raise NodraError("dependency graph is too large")
        name = queue.pop(0)
        spec = ",".join(sp for sp, _ in need[name] if sp)
        cur = chosen.get(name)
        if cur and V.satisfies(cur["version"], spec):
            continue
        if name not in rootset and name in have and V.satisfies(have[name], spec):
            chosen[name] = {"keep": True, "version": have[name]}
            continue
        p = get(name)
        ok = [v for v in versions(p) if V.satisfies(v, spec)]
        if not ok:
            by = ", ".join(sorted({b for _, b in need[name] if b})) or "your request"
            raise NodraError("no version of %s satisfies '%s' (required by %s)" % (name, spec or "*", by))
        ver = V.latest(ok)
        for k in need:                  # a re-pick drops the constraints the previous pick contributed
            need[k] = [(sp, b) for sp, b in need[k] if b != name]
        r = resolve(name, "==" + ver)
        if r["requires"]["os"] and current_os() not in r["requires"]["os"]:
            raise NodraError("%s supports only: %s" % (name, ", ".join(r["requires"]["os"])))
        chosen[name] = r
        for dep in r["requires"]["packages"]:
            dn, ds = V.split_spec(dep)
            add(dn, ds, name)
    out, done = [], set()

    def visit(n):
        c = chosen.get(n)
        if n in done or not c or c.get("keep"):
            return
        done.add(n)
        for dep in c["requires"]["packages"]:
            visit(naming.normalize(V.split_spec(dep)[0]))
        out.append(dict(c, root=n in rootset))

    for n in sorted(rootset):
        visit(n)
    return out


# ------------------------------------------------------------------------------------------------ updates

def updates(installed_records, names=None, constraint=lambda n: ""):
    """Installed packages whose sources offer a newer version -> [{"name", "installed", "available", "source"}].
    A package that is in no source (installed from a folder or zip) is skipped."""
    out = []
    with session():
        for n, r in sorted(installed_records.items()):
            if names and n not in names:
                continue
            try:
                got = resolve(n, constraint(n))
            except NodraError:
                continue
            if V.compare(got["version"], r["version"]) > 0:
                out.append({"name": n, "installed": r["version"], "available": got["version"], "source": got["source"]})
    return out


# ------------------------------------------------------------------------------------------------ checkout

def checkout(r, dest):
    """Copy a resolved package into `dest` (no .git, no caches); a plugin gets its generated nodra.toml. -> the source's rev (or None)."""
    src = r.get("dir")
    if not src or not os.path.isdir(src):
        raise NodraError("%s: its source folder is gone (%s); run: nodra source update" % (r["name"], src))
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", "node_modules"), symlinks=True)
    if r.get("synthetic"):
        with open(os.path.join(dest, "nodra.toml"), "w", encoding="utf-8") as f:
            f.write(sources.to_toml(r["raw"]))
    return r.get("rev")


def prefetch(pkgs, base, workers=None):
    """Copy every package of a plan into `base` -> {name: (folder, None) | (None, error)}. Local copies are quick; no threads needed."""
    out = {}
    for r in pkgs:
        dest = os.path.join(base, r["name"])
        try:
            r["rev"] = checkout(r, dest)
            out[r["name"]] = (dest, None)
        except Exception as e:                   # reported when that package's turn comes; the others carry on
            out[r["name"]] = (None, e)
    return out


# ------------------------------------------------------------------------------------------------ folders and zips

def _package_root(folder, depth=2):
    """The folder with the nodra.toml: `folder` itself, or the single package folder one or two levels below it (a zip of a folder)."""
    if os.path.isfile(os.path.join(folder, "nodra.toml")):
        return folder
    if depth == 0:
        return None
    subs = [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if os.path.isdir(os.path.join(folder, n)) and not n.startswith((".", "__"))]
    found = [s for s in subs if os.path.isfile(os.path.join(s, "nodra.toml"))]
    if len(found) > 1:
        raise NodraError("%s holds several packages (%s); install one folder at a time" % (folder, ", ".join(os.path.basename(s) for s in found)))
    if found:
        return found[0]
    return _package_root(subs[0], depth - 1) if len(subs) == 1 else None


def local_package(path, tmp=None):
    """Read a package from a folder or a .zip -> a resolved dict like resolve() (source "folder" / "zip"), or raises.
    A zip is extracted into `tmp` (the caller deletes it)."""
    path = os.path.abspath(os.path.expanduser(path))
    kind = "folder"
    if os.path.isfile(path):
        if not path.lower().endswith((".zip", ".tar.gz", ".tgz")):
            raise NodraError("%s is not a .zip or .tar.gz file" % path)
        if tmp is None:
            raise NodraError("internal: no scratch folder for the zip")
        try:
            archive.safe_extract(path, os.path.join(tmp, "x"))
        except Exception as e:
            raise NodraError("cannot read %s: %s" % (path, e))
        path, kind = os.path.join(tmp, "x"), "zip"
    if not os.path.isdir(path):
        raise NodraError("%s is not a package folder or .zip" % path)
    root = _package_root(path)
    if not root:
        raise NodraError("no nodra.toml in %s (is it a package? see: nodra dev init)" % path)
    try:
        with open(os.path.join(root, "nodra.toml"), encoding="utf-8") as f:
            m = M.parse(f.read())
    except (OSError, ValueError) as e:
        raise NodraError("%s: %s" % (os.path.join(root, "nodra.toml"), e))
    p = m["package"]
    return {"name": p["name"], "version": p["version"], "manifest": m, "type": p["type"], "source": kind, "rev": None, "dir": root,
            "synthetic": False, "raw": None, "sha256": "",
            "requires": {"os": list(m["requires"]["os"]), "commands": list(m["requires"]["commands"]), "packages": list(m["requires"]["packages"])}}


@contextlib.contextmanager
def with_local(cand):
    """Make a folder/zip package known to catalog() / plan() for the duration of one install."""
    c = {"name": cand["name"], "version": cand["version"], "dir": cand["dir"], "source": cand["source"], "rev": None, "manifest": cand["manifest"],
         "synthetic": False, "requires": cand["requires"], "type": cand["type"]}
    _LOCAL[cand["name"]] = c
    try:
        yield
    finally:
        _LOCAL.pop(cand["name"], None)


def tempdir():
    return tempfile.mkdtemp(prefix="nodra-")
