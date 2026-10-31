# MCP servers

An MCP (Model Context Protocol) server gives an AI tool extra tools to call: query a database, read a ticket system, run a calculator. In Nodra an MCP server is just part of a package. Declare it in `nodra.toml`, and `nodra install` registers it with Claude Code, Codex and OpenCode; the Nodra chat can use it in **Free chat** and lists it on its **MCP servers** page. Nothing is hosted anywhere: the AI tool starts your server as a local child process and talks to it over stdin/stdout.

## Declare a server

In the package's `nodra.toml` (type `mcp`, or any type that also ships a server):

```toml
[package]
name = "mcp-demo"
version = "0.1.0"
type = "mcp"
description = "Tiny demo MCP server (add, word_count)"
readme = "README.md"
license = "MIT"

[[mcp_servers]]
name = "mcp-demo"
command = "python3"
args = ["${PKG}/server/server.py"]
env = { LOG_LEVEL = "info" }
```

| Field | Meaning |
| --- | --- |
| `name` | Server name in the tools' configuration. Unique per table; keep it short, lowercase. |
| `command` | The program to start. It must exist on every OS the package claims (`[requires] commands`, `os`). |
| `args` | Arguments. `${PKG}` becomes the installed package folder (`~/.nodra/packages/<name>`), so the server file is found wherever the package lives. Never hard-code absolute paths. |
| `env` | Extra environment variables. No secrets: a package is shared with other people. |

A package with `type = "mcp"` must have at least one `[[mcp_servers]]` entry (`nodra dev validate` checks this). The `nodra dev init ./my-server --type mcp --name my-server` scaffold writes a working server and install scripts.

## What install does

`nodra install NAME` asks which detected tools should get the server (`--yes` takes all detected, `--tool claude` restricts) and writes an entry in each:

| Tool | Where the entry goes |
| --- | --- |
| Claude Code | `mcpServers.<name>` in `~/.claude.json`: `{"type": "stdio", "command", "args", "env"}` |
| Codex | a managed `[mcp_servers.<name>]` block in `${CODEX_HOME:-~/.codex}/config.toml`. If you already defined that name by hand, Nodra refuses to overwrite it and says so. |
| OpenCode | `mcp.<name>` in `~/.config/opencode/opencode.json`: `{"type": "local", "command": [command, ...args], "enabled": true}` |

`nodra uninstall NAME --force` removes exactly what was added; `nodra disable NAME` removes the entries but keeps the files; `nodra enable NAME` puts them back. Restart the tool (or start a new Claude Code session) to pick up a change. Servers of a **bot** package are not registered with any tool: they are used only by that bot (`~/.nodra/bots/NAME/mcp.json`).

## A worked example in plain Python

Layout:

```
mcp-demo/
  nodra.toml
  README.md
  server/server.py
  tests/test_server.py
```

`server/server.py` speaks newline-delimited JSON-RPC 2.0 on stdin/stdout. It needs only the standard library:

```python
#!/usr/bin/env python3
"""Minimal MCP server over stdio (standard library only).

Protocol: newline-delimited JSON-RPC 2.0 on stdin/stdout. Never print anything else on stdout
(logs go to stderr), or the client loses sync.
"""
import json
import sys

PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "add",
        "description": "Add two numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "word_count",
        "description": "Count the words in a text.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


def call(name, args):
    if name == "add":
        return str(args["a"] + args["b"])
    if name == "word_count":
        return str(len(str(args["text"]).split()))
    raise KeyError(name)


def reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def handle(msg):
    method, msg_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if msg_id is None:                      # a notification (e.g. notifications/initialized): no reply
        return
    if method == "initialize":
        reply(msg_id, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                       "serverInfo": {"name": "mcp-demo", "version": "0.1.0"}})
    elif method == "tools/list":
        reply(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        try:
            text = call(params.get("name"), params.get("arguments") or {})
            reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:              # a tool failure is a result, not a protocol error
            reply(msg_id, {"content": [{"type": "text", "text": "error: %s" % e}], "isError": True})
    elif method == "ping":
        reply(msg_id, {})
    else:
        reply(msg_id, error={"code": -32601, "message": "method not found: %s" % method})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            handle(json.loads(line))
        except Exception as e:
            sys.stderr.write("bad message: %s\n" % e)


if __name__ == "__main__":
    main()
```

The rules that matter:

- **stdout is the protocol.** One JSON object per line. Print logs and tracebacks to **stderr**. A stray `print()` breaks the client.
- Answer `initialize` (with your `protocolVersion`, `capabilities` and `serverInfo`), `tools/list` and `tools/call`. Do not reply to notifications (messages without an `id`, such as `notifications/initialized`).
- A failing tool returns `{"content": [...], "isError": true}`; reserve JSON-RPC `error` objects for protocol problems.
- Tool input is described with a JSON Schema in `inputSchema`; the model reads `description` to decide when to call it, so write it for the model.
- Keep tools small and deterministic, validate arguments, and never run shell commands built from model-provided text unchecked.

## Test it

Without any AI tool, pipe the messages in by hand:

```sh
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}' \
               '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
               '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
               '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"add","arguments":{"a":2,"b":3}}}' \
  | python3 server/server.py
```

Or as a unit test (`python3 -m unittest discover -s tests`):

```python
import json
import os
import subprocess
import sys
import unittest

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server", "server.py")


def talk(*messages):
    """Send JSON-RPC messages, one per line, and return the replies."""
    p = subprocess.run([sys.executable, SERVER], input="\n".join(json.dumps(m) for m in messages) + "\n",
                       capture_output=True, text=True, timeout=20)
    return [json.loads(x) for x in p.stdout.splitlines()]


class ServerTest(unittest.TestCase):
    def test_tools(self):
        out = talk(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "add", "arguments": {"a": 2, "b": 3}}},
        )
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "mcp-demo")
        self.assertEqual([t["name"] for t in out[1]["result"]["tools"]], ["add", "word_count"])
        self.assertEqual(out[2]["result"]["content"][0]["text"], "5")


if __name__ == "__main__":
    unittest.main()
```

Then the end-to-end check:

```sh
nodra dev validate ./mcp-demo
nodra install ./mcp-demo --yes --tool claude
claude mcp list            # mcp-demo should be listed (Claude Code CLI)
nodra uninstall mcp-demo --force
```

In Claude Code, ask "use the mcp-demo tool to add 2 and 3". The official MCP Inspector (`npx @modelcontextprotocol/inspector python3 server/server.py`) is another good way to poke at a server, if you have Node.

## Servers with Python dependencies

`${PKG}`-relative `python3` is fine for standard-library servers. If your server needs pip libraries (for example the `mcp` SDK or `requests`), list them under `[python]`; Nodra builds `~/.nodra/venvs/<name>` at install:

```toml
[python]
requires = ["mcp>=1.0"]
```

The venv interpreter is not substituted into `command` by itself, so give the tools a launcher that uses it. The reliable way is to make the package pip-installable with a console script: add a `pyproject.toml` with `[project.scripts] mcp-demo-server = "server:main"`, set `[python] install = true`, and use the command name:

```toml
[python]
requires = ["mcp>=1.0"]
install = true

[[mcp_servers]]
name = "mcp-demo"
command = "mcp-demo-server"      # shim in ~/.nodra/bin, runs inside the package venv
args = []
```

`~/.nodra/bin` must be on the `PATH` of the tool that starts the server (the installer adds it to your shell profile; GUI apps may need a restart). A shell or Python launcher under `${PKG}` that execs the venv python works as well. Node servers work the same way: `command = "npx"`, `args = ["-y", "@scope/server"]`, and declare `[requires] commands = ["npx"]`.

## Using servers in the Nodra chat

- **Claude chats** run Claude Code, which reads `~/.claude.json`, so every server installed for Claude Code is available there with no extra step.
- **Free chat** (a direct Anthropic API call, `ANTHROPIC_API_KEY`) has its own tool loop and can use stdio MCP servers from three places: servers of enabled installed packages (with `${PKG}` filled in), the chat's own list (`~/.nodra/ui/mcp.json`, edited on the MCP page) and Claude Code's user servers in `~/.claude.json`.
- **MCP servers page > Free chat tools**: *Allowed* is the master switch; *On in new chats* ticks a server automatically the first time a chat switches to Free chat; *Test / Retry* starts the server, lists its tools and shows the error text when it fails; a switch per tool hides it from the model. The state is stored in `~/.nodra/ui/mcp_state.json`; the engine menu of a chat ticks servers for that chat.
- The model also has a tool `nodra_mcp` (`status`, `retry`, `enable`, `disable`), so you can say "the github server failed, try again" or "turn off the delete tools of filesystem" in a chat. A server switched off on the MCP page cannot be re-enabled by the model.
- Works can call an MCP server too: the **Free chat** node (`ai.free`) takes a list of servers, and a **Claude task** node uses whatever Claude Code has.
- The chat starts servers with your home folder as working directory and the server's `env` on top of its own environment; it speaks `initialize`, `notifications/initialized`, `tools/list` and `tools/call` and follows `nextCursor` paging.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Test shows "cannot start python3" | The `command` is not on `PATH` for the chat. Use the full path, a console-script shim, or fix `[requires] commands`. |
| Test hangs, then times out | The server never answered `initialize`. Something wrote to stdout before the JSON, or it waits on stdin in a different framing (Content-Length headers instead of one JSON per line). |
| Tools show up in Claude Code but not in Free chat | Check the MCP page: *Allowed*, the server's switch and per-tool switches. |
| `[mcp_servers.NAME]` already defined (Codex) | You defined it by hand. Rename the server in `nodra.toml` or remove your block. |
| Server missing after install | Restart the tool. Check `nodra list` shows the package enabled and `claude mcp list` / `~/.claude.json` has the entry. |
