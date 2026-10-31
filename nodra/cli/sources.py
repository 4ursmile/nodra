"""Sources: folders and git repos that contain packages.

A source holds packages as `<source>/<path>/*/nodra.toml` (`path` defaults to `packages`), a root `nodra.toml`, and plugins listed in a Claude
Code `.claude-plugin/marketplace.json` (these become synthetic packages). The built-in source `core` is `<root>/packages` of this checkout.
Extra sources live in ~/.nodra/config.json under "sources": [{"name", "url", "branch", "path"}]; `url` is a git URL or a local folder.
Git sources are cloned shallow to ~/.nodra/sources/<name>. git is optional: without it git sources are skipped with a hint."""
import json
import os
import re
import shutil

from ..core import manifest as M, naming, version as V
from ..core.errors import NodraError
from . import gitx, paths

CORE = "core"
DEFAULT_PATH = "packages"
MARKET = os.path.join(".claude-plugin", "marketplace.json")
NO_GIT_HINT = "git is not installed: this source is skipped (install git, or use a local folder / zip instead)"
URL_SCHEMES = ("http://", "https://", "ssh://", "git://", "file://", "git+")


class SourceError(NodraError):
    pass


# ------------------------------------------------------------------------------------------------ configuration

def clean_name(name):
    n = naming.normalize(str(name or ""))
    if not n or not re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", n):
        raise ValueError("source name: lowercase letters, digits and - (max 41), e.g. 'my-team'")
    if n == CORE:
        raise ValueError("'core' is the built-in source and cannot be changed")
    return n


def configured():
    """The extra sources saved in config.json (invalid rows are ignored)."""
    out = []
    for s in paths.config().get("sources") or []:
        if isinstance(s, dict) and s.get("name") and s.get("url"):
            out.append({"name": str(s["name"]), "url": str(s["url"]), "branch": str(s.get("branch") or ""),
                        "path": str(s["path"]) if s.get("path") not in (None,) else ""})
    return out


def _save(rows):
    c = paths.load("config.json", {})
    c["sources"] = rows
    paths.save("config.json", c)


def add(name, url, branch="", path=""):
    n = clean_name(name)
    url = str(url or "").strip()
    if not url:
        raise ValueError("give the git URL or the folder of the source")
    if any(s["name"] == n for s in configured()):
        raise ValueError("a source named %s exists already (nodra source remove %s)" % (n, n))
    if not is_git_url(url):
        url = os.path.abspath(os.path.expanduser(url))
        if not os.path.isdir(url):
            raise ValueError("%s is not a folder and does not look like a git URL" % url)
    _save(configured() + [{"name": n, "url": url, "branch": branch or "", "path": path or ""}])
    return n


def remove(name):
    n = clean_name(name)
    rows = configured()
    if not any(s["name"] == n for s in rows):
        raise ValueError("no source named %s (nodra source list)" % n)
    _save([s for s in rows if s["name"] != n])
    shutil.rmtree(clone_dir(n), ignore_errors=True)
    shutil.rmtree(plugin_root(n), ignore_errors=True)
    return n


def is_bare_repo(d):
    return os.path.isfile(os.path.join(d, "HEAD")) and os.path.isdir(os.path.join(d, "objects"))


def is_git_url(url):
    """A remote (or bare repository) that must be cloned. A plain folder is a local source, used where it is."""
    u = os.path.expanduser(str(url or "").strip())
    if u.startswith(URL_SCHEMES) or re.match(r"^[\w.-]+@[\w.-]+:", u):
        return True
    return os.path.isdir(u) and is_bare_repo(u)


def clone_dir(name):
    return paths.p("sources", name)


def plugin_root(name):
    return paths.p("sources", "_plugins", name)


# ------------------------------------------------------------------------------------------------ git

def _head(d):
    if not (d and gitx.available() and os.path.exists(os.path.join(d, ".git"))):
        return None
    try:
        return gitx.run(["rev-parse", "HEAD"], cwd=d, check=False) or None
    except Exception:
        return None


def clone(url, dest, branch="", timeout=300):
    """Shallow clone `url` into `dest` (replacing a broken one). -> head sha."""
    from . import access
    if not gitx.available():
        raise SourceError(gitx.NO_GIT)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    args = ["clone", "--depth", "1", "--quiet"] + (["--branch", branch] if branch else []) + [url, dest]
    try:
        access.with_access(url, lambda: gitx.run(args, timeout=timeout))
    except gitx.GitError as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise SourceError(str(e))
    return _head(dest)


def pull(dest, url, branch="", timeout=300):
    """Bring a shallow clone to the remote's newest commit. -> (old sha, new sha)."""
    from . import access
    if not gitx.available():
        raise SourceError(gitx.NO_GIT)
    old = _head(dest)
    ref = branch or "HEAD"
    try:
        access.with_access(url, lambda: gitx.run(["fetch", "--depth", "1", "--quiet", "origin", ref], cwd=dest, timeout=timeout))
        gitx.run(["reset", "--hard", "--quiet", "FETCH_HEAD"], cwd=dest)
    except gitx.GitError as e:
        raise SourceError(str(e))
    return old, _head(dest)


def fetch(src):
    """Refresh one git source (clone it the first time). -> {"name", "changed", "rev", "error"}."""
    out = {"name": src["name"], "changed": False, "rev": None, "error": ""}
    if src.get("kind") != "git":
        return out
    d = clone_dir(src["name"])
    try:
        if os.path.isdir(os.path.join(d, ".git")):
            old, new = pull(d, src["url"], src.get("branch") or "")
            out.update(changed=old != new, rev=new)
        else:
            out.update(changed=True, rev=clone(src["url"], d, src.get("branch") or ""))
        fetch_plugins(src)
    except NodraError as e:
        out["error"] = str(e)
    return out


# ------------------------------------------------------------------------------------------------ describing sources

def core_source():
    return {"name": CORE, "url": paths.root(), "branch": "", "path": DEFAULT_PATH, "kind": "core"}


def sources(rev=True):
    """Every source with its local folder resolved: [{name, url, branch, path, kind, dir, ok, error, hint, rev}]. Never fetches."""
    out = []
    for s in [core_source()] + configured():
        s = dict(s, dir=None, ok=True, error="", hint="", rev=None)
        if s["name"] == CORE:
            s["dir"] = s["url"]
        elif is_git_url(s["url"]):
            s["kind"] = "git"
            d = clone_dir(s["name"])
            if os.path.isdir(os.path.join(d, ".git")):
                s["dir"] = d
            elif not gitx.available():
                s.update(ok=False, error="git is not installed", hint=NO_GIT_HINT)
            else:
                s.update(ok=False, error="not fetched yet", hint="run: nodra source update %s" % s["name"])
        else:
            s["kind"] = "folder"
            d = os.path.abspath(os.path.expanduser(s["url"]))
            if os.path.isdir(d):
                s["dir"] = d
            else:
                s.update(ok=False, error="folder not found: %s" % d, hint="fix it: nodra source remove %s" % s["name"])
        if s["dir"]:
            if rev:
                s["rev"] = _head(s["dir"])
            if s["name"] != CORE and os.path.isfile(os.path.join(s["dir"], MARKET)) and not has_packages(s):
                s["kind"] = "marketplace"
        out.append(s)
    return out


def get(name):
    for s in sources():
        if s["name"] == name:
            return s
    raise ValueError("no source named %s (nodra source list)" % name)


def pkg_root(src):
    sub = src.get("path")
    if not sub and src["name"] != CORE and not os.path.isdir(os.path.join(src["dir"], DEFAULT_PATH)):
        return os.path.normpath(src["dir"])                  # no packages/ folder and no path given: the folder itself holds the packages
    return os.path.normpath(os.path.join(src["dir"], sub or DEFAULT_PATH))


def has_packages(src):
    return any(not p.get("synthetic") for p in _native(src))


def public_view(s, count=None):
    d = {k: s.get(k) for k in ("name", "url", "branch", "path", "kind", "ok", "error", "hint", "rev")}
    d["dir"] = s.get("dir")
    if count is not None:
        d["packages"] = count
    return d


# ------------------------------------------------------------------------------------------------ discovery

def _read_manifest(folder):
    f = os.path.join(folder, "nodra.toml")
    with open(f, encoding="utf-8") as fh:
        return M.parse(fh.read())


def _candidate(src, folder, m, synthetic=False):
    p = m["package"]
    return {"name": p["name"], "version": p["version"], "type": p["type"], "description": p["description"], "tags": list(p["tags"]),
            "dir": folder, "source": src["name"], "rev": src.get("rev"), "manifest": m, "synthetic": synthetic,
            "requires": {"os": list(m["requires"]["os"]), "commands": list(m["requires"]["commands"]),
                         "packages": list(m["requires"]["packages"])}}


def _native(src):
    """Packages with a nodra.toml: the root one and `<path>/*/nodra.toml`. A broken manifest is skipped, not fatal."""
    out, seen = [], set()
    d = src.get("dir")
    if not d or not os.path.isdir(d):
        return out
    folders = [d]
    root = pkg_root(src)
    if os.path.isdir(root):
        folders += [os.path.join(root, n) for n in sorted(os.listdir(root))]
    for f in folders:
        if f in seen or not os.path.isfile(os.path.join(f, "nodra.toml")):
            continue
        seen.add(f)
        try:
            out.append(_candidate(src, f, _read_manifest(f)))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def plugin_dir(src, entry):
    """Local folder of a marketplace entry, or (None, reason). Relative sources live in the marketplace repo; git sources are cloned by
    `source update` into ~/.nodra/sources/_plugins/<source>/<plugin>."""
    s = entry.get("source")
    market = read_json(os.path.join(src["dir"], MARKET))
    base = ((market.get("metadata") or {}).get("pluginRoot") or "") if isinstance(market.get("metadata"), dict) else ""
    if isinstance(s, str) and not s.startswith(URL_SCHEMES):
        full = os.path.normpath(os.path.join(src["dir"], base, s))
        inside = os.path.realpath(full).startswith(os.path.realpath(src["dir"]))
        return (full, "") if inside and os.path.isdir(full) else (None, "folder %s not found" % s)
    url, ref = plugin_git(s)
    if not url:
        return None, "unsupported plugin source"
    d = os.path.join(plugin_root(src["name"]), clean_plugin(entry.get("name")))
    if os.path.isdir(os.path.join(d, ".git")):
        return d, ""
    return None, ("git is not installed" if not gitx.available() else "not fetched yet (nodra source update %s)" % src["name"])


def clean_plugin(n):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(n or "plugin")).strip("-.") or "plugin"


def plugin_git(s):
    """(url, ref) of a git plugin source: {"source": "github", "repo": "o/r"}, {"source": "url", "url": ...}, or a url string."""
    if isinstance(s, str) and s.startswith(URL_SCHEMES):
        return s, ""
    if isinstance(s, dict):
        ref = str(s.get("ref") or "")
        if s.get("source") == "github" and s.get("repo"):
            return "https://github.com/%s.git" % s["repo"], ref
        if s.get("url"):
            return str(s["url"]), ref
    return "", ""


def fetch_plugins(src):
    """Clone/refresh the git-sourced plugins of a marketplace source. Quietly skipped without git."""
    if not src.get("dir") or not gitx.available():
        return
    market = read_json(os.path.join(src["dir"], MARKET))
    for e in market.get("plugins") or []:
        if not isinstance(e, dict) or isinstance(e.get("source"), str) and not e["source"].startswith(URL_SCHEMES):
            continue
        url, ref = plugin_git(e.get("source"))
        if not url:
            continue
        d = os.path.join(plugin_root(src["name"]), clean_plugin(e.get("name")))
        try:
            if os.path.isdir(os.path.join(d, ".git")):
                pull(d, url, ref)
            else:
                clone(url, d, ref)
        except NodraError:
            continue


def _skills(folder):
    out = []
    sd = os.path.join(folder, "skills")
    for n in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
        if os.path.isfile(os.path.join(sd, n, "SKILL.md")):
            out.append({"name": n, "path": "skills/" + n})
    return out


def _mds(folder, sub):
    d = os.path.join(folder, sub)
    return [{"name": f[:-3], "path": sub + "/" + f} for f in (sorted(os.listdir(d)) if os.path.isdir(d) else [])
            if f.endswith(".md") and os.path.isfile(os.path.join(d, f))]


def _expand(v):
    return v.replace("${CLAUDE_PLUGIN_ROOT}", "${PKG}") if isinstance(v, str) else v


def _mcp(folder, plugin_json, entry):
    """MCP servers of a plugin: .mcp.json, or inline `mcpServers` in plugin.json / the marketplace entry."""
    raw = {}
    mj = read_json(os.path.join(folder, ".mcp.json"))
    raw.update(mj.get("mcpServers") if isinstance(mj.get("mcpServers"), dict) else mj)
    for src in (plugin_json, entry):
        if isinstance(src.get("mcpServers"), dict):
            raw.update(src["mcpServers"])
    out = []
    for name, v in raw.items():
        if isinstance(v, dict) and v.get("command"):
            out.append({"name": clean_plugin(name), "command": _expand(str(v["command"])), "args": [_expand(str(a)) for a in v.get("args") or []],
                        "env": {str(k): _expand(str(x)) for k, x in (v.get("env") or {}).items()} if isinstance(v.get("env"), dict) else {}})
    return out


def synthetic(src, folder, entry):
    """A Claude Code plugin folder as a package (skills/*/SKILL.md, agents/*.md, commands/*.md, .mcp.json). None when it holds nothing we can register."""
    pj = read_json(os.path.join(folder, ".claude-plugin", "plugin.json"))
    name = naming.normalize(str(entry.get("name") or pj.get("name") or os.path.basename(folder)))
    try:
        naming.validate(name)
        ver = str(entry.get("version") or pj.get("version") or "0.0.0")
        V.parse(ver)
    except ValueError:
        return None
    skills, agents, commands, mcp = _skills(folder), _mds(folder, "agents"), _mds(folder, "commands"), _mcp(folder, pj, entry)
    if not (skills or agents or commands or mcp):
        return None
    kind = "mcp" if mcp and not (skills or agents) else "agent" if agents and not skills else "skill"
    tags = [str(t).lower() for t in (entry.get("tags") or entry.get("keywords") or pj.get("keywords") or []) if isinstance(t, str)]
    if entry.get("category"):
        tags.append(str(entry["category"]).lower())
    raw = {"package": {"name": name, "version": ver, "type": kind, "tags": tags, "readme": "README.md",
                       "description": str(entry.get("description") or pj.get("description") or "")},
           "skills": skills, "agents": agents, "commands": commands, "mcp_servers": mcp}
    try:
        m = M.normalize(raw)
    except ValueError:
        return None
    c = _candidate(src, folder, m, synthetic=True)
    c["raw"] = raw
    return c


def marketplace_packages(src, skip_dirs=()):
    out = []
    d = src.get("dir")
    market = read_json(os.path.join(d, MARKET)) if d else {}
    for e in market.get("plugins") or []:
        if not isinstance(e, dict):
            continue
        folder, why = plugin_dir(src, e)
        if not folder or os.path.realpath(folder) in skip_dirs or os.path.isfile(os.path.join(folder, "nodra.toml")):
            continue
        c = synthetic(src, folder, e)
        if c:
            out.append(c)
    return out


def packages(src):
    """Every package of a source (native first, then marketplace plugins that are not already a native package)."""
    if not src.get("dir"):
        return []
    nat = _native(src)
    skip = {os.path.realpath(c["dir"]) for c in nat}
    return nat + marketplace_packages(src, skip)


# ------------------------------------------------------------------------------------------------ synthetic nodra.toml

def _q(v):
    return json.dumps(v, ensure_ascii=False)


def _kv(k, v):
    if isinstance(v, dict):
        return "%s = { %s }" % (k, ", ".join("%s = %s" % (_q(a), _q(b)) for a, b in v.items()))
    return "%s = %s" % (k, _q(v))


def to_toml(raw):
    """nodra.toml text for a synthetic package (the `raw` dict built by synthetic())."""
    p = raw["package"]
    lines = ["# generated by nodra from a Claude Code plugin", "[package]"] + [_kv(k, p[k]) for k in ("name", "version", "type", "description", "tags")]
    for table in ("skills", "agents", "commands"):
        for x in raw.get(table) or []:
            lines += ["", "[[%s]]" % table, _kv("name", x["name"]), _kv("path", x["path"])]
    for x in raw.get("mcp_servers") or []:
        lines += ["", "[[mcp_servers]]", _kv("name", x["name"]), _kv("command", x["command"]), _kv("args", x["args"])]
        if x.get("env"):
            lines.append(_kv("env", x["env"]))
    return "\n".join(lines) + "\n"
