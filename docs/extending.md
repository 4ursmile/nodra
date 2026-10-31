# Building on Nodra

This page is for developers who build **on top of** Nodra: a local web UI, a desktop app, an IDE panel, a script or an AI agent that manages packages, sources and bots for the user. It describes what Nodra exposes, the contract each surface keeps, and the rules that keep such a tool safe.

| Surface | Use it for | Contract |
| --- | --- | --- |
| **CLI JSON output** (`nodra --json CMD`) | Everything on the user's machine: search, install, uninstall, update, sources, vault, bots, knowledge, config | One JSON document per command ([below](#the-json-contract)) |
| **Packages** (`nodra.toml`) | Shipping your tool to other people: a skill, agent, MCP server, node, tool, setup or bot | [manifest](manifest.md), [packages](packages.md), [bots](bots.md), [nodes](nodes.md), [mcp](mcp.md) |
| **`nodra run`** | Keeping a long-lived program (your server, a bot) running in the background, with logs, restarts and a schedule | [cli](cli.md) "Bots, services and knowledge" |

A local tool should use the **CLI**, not reimplement it: the CLI already knows the sources, the git logins, the install locations of every AI tool and the state of installed packages. Calling it keeps your tool and the terminal in the same state. There is no server and no HTTP API: everything is the CLI and files in `~/.nodra`.

## The JSON contract

Any command prints one JSON document on stdout when JSON output is asked for in any of these ways:

```sh
nodra --json list                 # global flag, before the command
nodra list --json                 # the command's own flag
NODRA_JSON=1 nodra list           # environment, for a whole process tree
```

Without one of them nothing changes: human output, `--plain` and `--name-only` keep their shapes. (`nodra usage --json` keeps its own report shape; `nodra --json usage` wraps it like every other command.)

### The document

```json
{
  "schema": 1,
  "ok": true,
  "command": "install",
  "exit": 0,
  "error": null,
  "hint": null,
  "data": {"failed": []},
  "output": null,
  "messages": [{"level": "good", "text": "my-skill 1.2.0 installed"}],
  "changes": {"installed": [{"name": "my-skill", "version": "1.2.0"}]},
  "context": {"cli_version": "1.0.0", "home": "/Users/sam/.nodra", "root": "/Users/sam/nodra",
              "sources": [{"name": "core", "url": "/Users/sam/nodra/packages", "kind": "folder", "ok": true},
                          {"name": "community", "url": "https://example.com/team/nodra-packages.git", "kind": "git", "ok": true}],
              "git": true}
}
```

| Field | Meaning |
| --- | --- |
| `schema` | Version of this contract. New fields may be added within a version; a field is never removed or changes meaning without a new number. |
| `ok`, `exit` | Success, and the process exit code (also the real exit code). 0 = ok, 1 = failed, 2 = bad command line, 130 = interrupted. |
| `command` | The command and its sub-action (`vault list`, `run stop`, `source add`). `null` when the command line could not be parsed. |
| `error`, `hint` | One-line error and, when known, what to do. |
| `data` | The structured answer (table below). `null` for commands that only report what they did. |
| `output` | Text the command printed that is not JSON (for example `nodra knowledge get NOTE` prints the note). `null` when empty. |
| `messages` | What a person would have seen, in order: `{level, text}` with level `step`, `good`, `bad`, `note`, `info`, `heading`, `done` or `text`. Plain text, no colour codes. |
| `changes` | Installed packages before vs after the command: `installed`, `removed`, `updated` (`from`, `to`), `enabled`, `disabled`. Keys appear only when something changed. Refresh your package list when it is not empty. |
| `context` | `{cli_version, home, root, sources: [{name, url, kind, ok}], git: true or false}`: the CLI version, the Nodra home, the checkout folder, every source with its kind (`folder`, `git`, `marketplace`) and whether it is reachable, and whether git is installed. |

### Data per command

| Command | `data` |
| --- | --- |
| `search [TERM]` | Every matching package of every source (`name`, `type`, `version`, `description`, `tags`, `source`, `installed`, `installed_version`, ...). |
| `info NAME` | The package entry plus its components. |
| `list` | Installed packages: `name`, `version`, `enabled`, `components`, `path`, `source`, `rev`, and where present `type`, `bot_home`, `venv`, `tools`, `shims`. |
| `install ...` | Several packages: `{"failed": [{name, error}]}`. What was installed is always in `changes`; a single package that fails gives `ok: false` and its `error`. |
| `uninstall`, `update`, `enable`, `disable`, `sync` | See `changes`. `update --check` lists the packages with a newer version. |
| `source list` | The sources with `name`, `url`, `branch`, `path`, `kind`, `ok`. |
| `config [show]`, `config set K V` | The configuration, secrets masked. |
| `upgrade --check` | Whether a newer Nodra is available and why not, when it is not possible. |
| `vault [list]` | `{backend, remotes: [{host, scheme, username, login: stored or missing}]}`. |
| `vault test [REMOTE]` | `[{host, url, username, login, reachable}]`. |
| `run list`, `run status NAME` | The runs (`id`, `bot`, `args`, `schedule`, `restart`, `status`, `pid`, `runs`, `last_exit`, `state`, `alive`, ...). |
| `chat status` | Whether the chat runs and its URL. |
| `lock` | `{file, lock}`: the lock file path and its content. |
| `knowledge list` | The notes. `knowledge get NOTE` puts the body in `output`. |
| `usage` | The usage report. |
| Anything else | `null`; read `messages` and `changes`. |

Adding `data` to more commands is additive (schema stays 1); treat a `null` `data` as "nothing structured yet", not as an error.

### Rules JSON mode follows

- **stdout holds the document and nothing else.** Programs the command starts (install scripts, git, pip) write to stderr.
- **No prompts.** JSON mode is non-interactive. A command that would ask takes its safe default, usually *do nothing* (for example `self-uninstall` refuses). Pass `--yes` when the user really confirmed in your UI. JSON mode never adds `--yes` for you.
- **Secrets come in on stdin, never on the command line** (argv is visible to every process on the machine):

  ```sh
  printf '%s' "$TOKEN" | nodra vault add https://git.example.com --user sam --token-stdin --json
  ```

- **Secrets never come out.** Config values under keys that look secret (`token`, `secret`, `password`, `credential`, `api_key`) read `"set"`; the vault reports `login: "stored"`.
- **A bad command line is still a document** (`ok: false`, `exit: 2`, the argparse message in `error`). `--help` prints help text, not JSON.

## Shared state

A UI that calls the CLI **shares its state**; it must not keep its own copy of anything:

| State | Lives in | Shared how |
| --- | --- | --- |
| Settings and sources | `~/.nodra/config.json` | `nodra config [set]`, `nodra source ...` |
| Git logins | The OS credential store (Keychain, DPAPI, Secret Service, else a 0600 file); host list in `~/.nodra/vault.json` | `nodra vault ...`. git itself uses the same entries through Nodra's credential helper. |
| Installed packages | `~/.nodra/state.json` and `~/.nodra/packages/` | `nodra list`, plus `changes` in every reply. |
| Bots and services | `~/.nodra/runs/` | `nodra run ...`. |
| Notes | `~/.nodra/knowledge/*.md` | `nodra knowledge ...`, or read the files. |

If several programs use one machine account, set `NODRA_HOME` the same way for all of them, or they see different states. Programs started by the CLI (the chat, services, nodes) receive `NODRA_HOME`, `NODRA_ROOT` and `NODRA_CLI`; `NODRA_CLI` is the command to call the CLI with (a JSON argv list or a path), and works from a raw checkout (`[python, "-m", "nodra.cli"]` with `PYTHONPATH=<root>`).

## Calling the CLI from your code

Python (stdlib):

```python
import json, subprocess

def nodra(*args, stdin=None):
    p = subprocess.run(["nodra", "--json", *args], input=stdin, capture_output=True, text=True)
    doc = json.loads(p.stdout)                 # always one document, also on failure
    if not doc["ok"]:
        raise RuntimeError(doc["error"] + (" (" + doc["hint"] + ")" if doc["hint"] else ""))
    return doc

pkgs = nodra("search", "sql")["data"]
nodra("install", "sql-helper", "--yes")
```

Node:

```js
import { execFile } from "node:child_process";
const nodra = (args, input) => new Promise((ok, bad) => {
  const p = execFile("nodra", ["--json", ...args], (err, stdout) => {
    try { const d = JSON.parse(stdout); d.ok ? ok(d) : bad(new Error(d.error)); } catch (e) { bad(err || e); }
  });
  if (input != null) { p.stdin.end(input); } else { p.stdin.end(); }
});
```

Always pass arguments as a list (`execFile`, `subprocess.run([...])`), never through a shell: package names, hosts and notes come from users and from third-party sources.

## A local web UI

The Nodra chat (`chat/` in this repository, `nodra chat`) is a complete example of a local UI built this way: it calls `nodra --json ...` for every package action and renders `data`, `messages` and `changes`. To build your own:

1. Ship it as a **service** package so `nodra run` manages it: `[service] run = "ui/server.py"`, plus `[[service.env]]` entries for its port. `nodra run NAME` starts it in the background with a log and restart on failure; `nodra run stop NAME` stops it.
2. **Lock it down.** It controls installs and the user's git logins:
   - listen on `127.0.0.1` only, never `0.0.0.0`;
   - generate a random token at start, open the browser with it, and require it on every request (a cookie or header, not only in the URL);
   - reject requests whose `Origin`/`Host` is not your own address (DNS-rebinding and cross-site requests);
   - keep secrets in memory only for the one command that needs them, and send them on stdin.
3. Use the standard library where you can (`http.server`, `json`, `subprocess`); declare anything else in `[python] requires`.

### A terminal inside the web UI

A built-in terminal works well with Nodra, if it is a **real terminal**: run the shell or `nodra` in a pseudo-terminal (Python's `pty` on macOS and Linux, ConPTY on Windows), stream it over a WebSocket to xterm.js, pass the browser size on resize and set `TERM=xterm-256color`. With a PTY the CLI behaves as in a normal terminal (colours, arrow-key menus, hidden prompts, `nodra usage`); with plain pipes it switches to non-interactive mode. Use pipes for `--json` calls and a PTY for the terminal. A terminal is a remote shell: everything under "A local web UI" applies twice over, plus an origin check on the WebSocket upgrade and no "share this terminal" feature.

## Keeping the contract when you change Nodra

For contributors:

- Print through `ui.*` (`ui.good`, `ui.note`, `ui.table`, ...), never `print()`, unless it is the command's own data output. In JSON mode the `ui` calls become `messages`.
- Give a command structured output with `ui.result(data)`, before printing for people. It does nothing in human mode.
- Never pass a secret to `ui.*` or `ui.result`.
- New prompts must check `ui.INTERACTIVE` (false in JSON mode) and offer a non-interactive path: a flag, or a `--*-stdin` for secrets.
- Add a case to `tests/test_json_output.py` for any new `data` shape: the document parses, has every field and contains no secret.
