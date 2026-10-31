"""Tool adapters (Claude Code, Codex, OpenCode). Every mutation returns a revert record."""
import contextlib
import json
import os
import re
import shutil
import time
import uuid

HOME = lambda: os.path.expanduser("~")
MARK = "nodra"


# ---------------------------------------------------------------- file helpers
def _copy(src, dst):
    if os.path.isdir(src):
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return {"op": "rm", "path": dst}


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError:
        raise ValueError("%s is not valid JSON; refusing to modify it" % path)


def _write_json(path, d):
    """Atomic write. The temp name is unique per writer: two hook processes verifying at the same moment used to share `<file>.nodra.tmp`,
    so one's os.replace pulled the file from under the other (FileNotFoundError) or a reader saw half of it (JSONDecodeError)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.nodra.%d.%s.tmp" % (path, os.getpid(), uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w") as f:
            json.dump(d, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def locked(path, wait=2.0, stale=30.0):
    """Cross-process lock around read-modify-write of one settings file (O_EXCL lock file). Held only for the few milliseconds of an edit.
    Never blocks the agent: after `wait` seconds it goes ahead without the lock (the atomic write above still keeps the file valid), and a
    lock older than `stale` seconds belongs to a dead process and is taken over."""
    lock, have, end = path + ".nodra.lock", False, time.time() + wait
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        pass
    while True:
        try:
            os.close(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            have = True
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > stale:
                    os.remove(lock)
                    continue
            except OSError:
                pass
            if time.time() >= end:
                break
            time.sleep(0.01)
        except OSError:
            break
    try:
        yield have
    finally:
        if have:
            try:
                os.remove(lock)
            except OSError:
                pass


def block_begin(i): return "# >>> nodra:%s" % i
def block_end(i): return "# <<< nodra:%s" % i


def add_block(path, bid, text):
    """Insert/replace a managed text block (idempotent)."""
    cur = open(path).read() if os.path.exists(path) else ""
    cur = remove_block_text(cur, bid)
    if cur and not cur.endswith("\n"):
        cur += "\n"
    cur += "%s\n%s\n%s\n" % (block_begin(bid), text.rstrip("\n"), block_end(bid))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(cur)
    return {"op": "block", "path": path, "id": bid}


def remove_block_text(text, bid):
    pat = re.compile(r"\n?%s\n.*?%s\n?" % (re.escape(block_begin(bid)), re.escape(block_end(bid))), re.S)
    return pat.sub("\n", text).lstrip("\n") if pat.search(text) else text


def revert(rec):
    if not rec:
        return
    op = rec["op"]
    try:
        if op == "rm":
            p = rec["path"]
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.path.exists(p) and os.remove(p))
        elif op == "json_key":
            d = _read_json(rec["path"])
            tgt = d
            for k in rec["key"].split("."):
                tgt = tgt.get(k, {})
            if rec.get("prev") is None:
                tgt.pop(rec["name"], None)
            else:
                tgt[rec["name"]] = rec["prev"]
            _write_json(rec["path"], d)
        elif op == "block":
            if os.path.exists(rec["path"]):
                t = remove_block_text(open(rec["path"]).read(), rec["id"])
                open(rec["path"], "w").write(t)
        elif op == "restore":  # backup written by setup profiles
            if os.path.exists(rec["backup"]):
                shutil.copy2(rec["backup"], rec["path"])
            elif os.path.exists(rec["path"]):
                os.remove(rec["path"])
            d = rec.get("rmdir")                      # a folder this install created: remove it, but only if nothing else is in it
            while d and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                break
    except Exception:
        pass


def _json_key(path, key, name, value):
    d = _read_json(path)
    tgt = d
    for k in key.split("."):
        tgt = tgt.setdefault(k, {})
    prev = tgt.get(name)
    tgt[name] = value
    _write_json(path, d)
    return {"op": "json_key", "path": path, "key": key, "name": name, "prev": prev}


# ---------------------------------------------------------------- adapters
class Tool(object):
    name = ""
    label = ""
    def detect(self): return False
    def add_skill(self, name, src): return None
    def add_agent(self, name, src): return None
    def add_mcp(self, name, spec): return None          # spec: {command,args,env}
    def add_command(self, name, src): return None       # a slash command (markdown file)


class ClaudeCode(Tool):
    name, label = "claude", "Claude Code"
    def __init__(self): self.d = lambda *a: os.path.join(HOME(), ".claude", *a)
    def detect(self): return os.path.isdir(self.d()) or bool(shutil.which("claude"))
    def add_skill(self, name, src): return _copy(src, self.d("skills", name))
    def add_agent(self, name, src): return _copy(src, self.d("agents", name + ".md"))
    def add_command(self, name, src): return _copy(src, self.d("commands", name + ".md"))
    def add_mcp(self, name, spec):
        v = {"type": "stdio", "command": spec["command"], "args": spec.get("args", []), "env": spec.get("env", {})}
        return _json_key(os.path.join(HOME(), ".claude.json"), "mcpServers", name, v)

class Codex(Tool):
    """Skills -> ~/.codex/skills. MCP -> managed [mcp_servers.X] block in ~/.codex/config.toml.
    Commands and agents become custom prompts."""
    name, label = "codex", "Codex"
    def __init__(self): self.d = lambda *a: os.path.join(os.environ.get("CODEX_HOME") or os.path.join(HOME(), ".codex"), *a)
    def detect(self): return os.path.isdir(self.d()) or bool(shutil.which("codex"))
    def add_skill(self, name, src): return _copy(src, self.d("skills", name))
    def add_agent(self, name, src):  # no native agent concept; expose as a custom prompt
        return _copy(src, self.d("prompts", name + ".md"))
    def add_command(self, name, src): return _copy(src, self.d("prompts", name + ".md"))

    def add_mcp(self, name, spec):
        cfg = self.d("config.toml")
        if os.path.exists(cfg) and re.search(r"^\[mcp_servers\.%s\]" % re.escape(name), re.sub(
                r"%s.*?%s" % (re.escape(block_begin("mcp:" + name)), re.escape(block_end("mcp:" + name))), "",
                open(cfg).read(), flags=re.S), re.M):
            raise ValueError("~/.codex/config.toml already defines [mcp_servers.%s]; not overwriting" % name)
        lines = ["[mcp_servers.%s]" % name, "command = %s" % json.dumps(spec["command"]),
                 "args = %s" % json.dumps(spec.get("args", []))]
        if spec.get("env"):
            lines.append("env = { %s }" % ", ".join("%s = %s" % (json.dumps(k), json.dumps(v)) for k, v in spec["env"].items()))
        return add_block(cfg, "mcp:" + name, "\n".join(lines))


class OpenCode(Tool):
    """Skills -> skill/, agents -> agent/, commands -> command/, MCP -> opencode.json `mcp`."""
    name, label = "opencode", "OpenCode"
    def __init__(self): self.d = lambda *a: os.path.join(HOME(), ".config", "opencode", *a)
    def detect(self): return os.path.isdir(self.d()) or bool(shutil.which("opencode"))
    def add_skill(self, name, src): return _copy(src, self.d("skill", name))
    def add_agent(self, name, src): return _copy(src, self.d("agent", name + ".md"))
    def add_command(self, name, src): return _copy(src, self.d("command", name + ".md"))
    def add_mcp(self, name, spec):
        v = {"type": "local", "command": [spec["command"]] + list(spec.get("args", [])), "enabled": True}
        if spec.get("env"):
            v["environment"] = spec["env"]
        return _json_key(self.d("opencode.json"), "mcp", name, v)

TOOLS = {t.name: t for t in (ClaudeCode(), Codex(), OpenCode())}


def detected():
    return [t for t in TOOLS.values() if t.detect()]
