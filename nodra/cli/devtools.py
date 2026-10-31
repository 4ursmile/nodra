"""`nodra dev pack` (a package folder -> .zip) and `nodra dev marketplace` (<root>/.claude-plugin/marketplace.json)."""
import getpass
import json
import os
import re
import subprocess
import zipfile

from ..core import ignore, manifest as M
from ..core.errors import NodraError
from . import paths, sources, ui

MARKET_NAME = "nodra"
MARKET_OWNER = {"name": "Nodra community"}


def pack(root, out=None):
    """Zip one package folder (nodra.toml at the zip root). `.git`, `__pycache__`, `.venv`, `node_modules`, `dist` and ignored files are
    left out. -> {"file", "name", "version", "files", "size"}"""
    with open(os.path.join(root, "nodra.toml"), encoding="utf-8") as f:
        m = M.parse(f.read())
    pkg = m["package"]
    dest = os.path.abspath(out or "%s-%s.zip" % (pkg["name"], pkg["version"]))
    if os.path.isdir(dest):
        dest = os.path.join(dest, "%s-%s.zip" % (pkg["name"], pkg["version"]))
    files = [f for f in ignore.list_files(root) if os.path.abspath(os.path.join(root, f)) != dest]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):
            info = zipfile.ZipInfo(f, date_time=(1980, 1, 1, 0, 0, 0))          # same files, same bytes
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if os.access(os.path.join(root, f), os.X_OK) else 0o644) << 16
            with open(os.path.join(root, f), "rb") as fh:
                z.writestr(info, fh.read())
    return {"file": dest, "name": pkg["name"], "version": pkg["version"], "files": len(files), "size": os.path.getsize(dest)}


def dev_pack(a):
    out = pack(os.path.abspath(a.path), getattr(a, "output", None))
    ui.result(out)
    ui.good("packed %s %s: %d files, %s" % (out["name"], out["version"], out["files"], ui.human(out["size"])))
    ui.info("install it anywhere with: nodra install %s" % out["file"])
    return out["file"]


# ------------------------------------------------------------------------------------------------ marketplace

def plugin_entry(folder_rel, m):
    """The marketplace entry of one package: name, source, description, version. Claude Code finds skills/<name>/SKILL.md, agents/<name>.md and
    commands/<name>.md by itself; a package that keeps them elsewhere gets an explicit list, and MCP servers (which live in nodra.toml, not in a
    .mcp.json) are listed inline."""
    p = m["package"]
    e = {"name": p["name"], "source": "./" + folder_rel.replace(os.sep, "/"), "description": p["description"], "version": p["version"]}
    for key, fmt in (("skills", "skills/%s"), ("agents", "agents/%s.md"), ("commands", "commands/%s.md")):
        if any(x["path"].strip("/") != fmt % x["name"] for x in m[key]):
            e[key] = ["./" + x["path"].strip("/") for x in m[key]]
    if m["mcp_servers"] and p["type"] not in M.RUNNABLE:
        e["mcpServers"] = {s["name"]: {k: v for k, v in (
            ("command", s["command"].replace("${PKG}", "${CLAUDE_PLUGIN_ROOT}")),
            ("args", [x.replace("${PKG}", "${CLAUDE_PLUGIN_ROOT}") for x in s.get("args", [])]),
            ("env", s.get("env") or None)) if v not in (None, [], {})} for s in m["mcp_servers"]}
    return e


def _identity(root):
    """Marketplace name and owner: kept from an existing marketplace.json (authors may edit them), else this checkout's 'nodra' for the core
    repository, else the folder name and the git user (or OS user), so a community repository never claims the core marketplace name."""
    try:
        with open(os.path.join(root, sources.MARKET), encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old.get("name"), str) and old["name"] and isinstance(old.get("owner"), dict) and old["owner"].get("name"):
            return old["name"], old["owner"]
    except (OSError, ValueError, AttributeError):
        pass
    if os.path.realpath(root) == os.path.realpath(paths.root()):
        return MARKET_NAME, MARKET_OWNER
    name = re.sub(r"[^a-z0-9]+", "-", os.path.basename(os.path.realpath(root)).lower()).strip("-") or "packages"
    who = ""
    try:
        who = subprocess.run(["git", "config", "user.name"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return name, {"name": who or getpass.getuser()}


def build_marketplace(root):
    core = dict(sources.core_source(), dir=root)
    entries = []
    for c in sources.packages(core):
        if c.get("synthetic"):
            continue
        m = c["manifest"]
        has = m["skills"] or m["agents"] or m["commands"] or (m["mcp_servers"] and m["package"]["type"] not in M.RUNNABLE)
        if has:
            entries.append(plugin_entry(os.path.relpath(c["dir"], root), m))
    name, owner = _identity(root)
    return {"name": name, "owner": owner, "plugins": sorted(entries, key=lambda e: e["name"])}


def render(doc):
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def dev_marketplace(a):
    root = os.path.abspath(a.path) if a.path else paths.root()
    target = os.path.join(root, sources.MARKET)
    doc = build_marketplace(root)
    text = render(doc)
    try:
        with open(target, encoding="utf-8") as f:
            same = f.read() == text
    except OSError:
        same = False
    data = {"file": target, "plugins": [e["name"] for e in doc["plugins"]], "stale": not same}
    ui.result(data)
    if a.check:
        if not same:
            raise NodraError("%s is out of date (or missing); run: nodra dev marketplace" % target)
        return ui.good("%s is up to date (%d plugins)" % (target, len(doc["plugins"])))
    if not same:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    data["stale"] = False
    ui.result(data)
    ui.good("%s %s (%d plugins)" % ("wrote" if not same else "already up to date:", target, len(doc["plugins"])))
