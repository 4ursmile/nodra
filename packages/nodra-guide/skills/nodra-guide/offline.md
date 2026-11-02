# Nodra guide (self-contained)

Nodra is an offline, community-maintained local chat (Claude Code harness plus a free chat), Works (node workflows) and a package manager for skills, agents, MCP servers, nodes, bots and services. No server, no account, no telemetry. The only network use is `git` (package sources, `nodra upgrade`, optional), the Anthropic API or Claude Code (chat), and whatever a user's own node or MCP server does. This file is the complete guide; the repository's `docs/` folder holds the same material in more detail (`cli.md`, `manifest.md`, `packages.md`, `nodes.md`, `mcp.md`, `bots.md`, `sources.md`, `extending.md`).

## 1. Core model

- **Root**: the repository checkout (a git clone or an unzipped download). It holds `nodra/` (the CLI, stdlib only, Python 3.9+), `chat/` (the chat app, runs in place), `packages/` (installable packages) and `docs/`.
- **Source**: a folder or git repository holding packages. Packages are found as `<source>/<path>/*/nodra.toml` (`path` defaults to `packages`), plus a root `nodra.toml`, plus plugins listed in a Claude Code `.claude-plugin/marketplace.json`. The built-in source `core` is `<root>/packages`; it cannot be removed. More sources are in `~/.nodra/config.json` and cloned (shallow) to `~/.nodra/sources/<name>`.
- **Install** copies a package folder to `~/.nodra/packages/<name>`, builds `~/.nodra/venvs/<name>` if the manifest has `[python]`, registers skills, agents and MCP servers with Claude Code, Codex and OpenCode, and records `{version, source, rev, path, enabled}` in `~/.nodra/state.json`.
- **Update** compares the installed version with the version in the source; bump `version` in `nodra.toml` for every change. The chat itself updates with the checkout (`nodra upgrade`).
- **git is optional.** Without git, git sources are skipped with a hint; the core source, folder sources, zips and folder installs work.

## 2. Install Nodra

- Clone and install: `git clone <your-git-url> nodra && cd nodra && python3 install.py` (Windows: `py install.py`).
- Without git: download the repository zip, unzip it, run `python3 install.py` inside.
- The installer writes `~/.nodra/bin/nodra` (and `nodra.cmd` on Windows), adds `~/.nodra/bin` to PATH with one marked block in the shell profile (`NODRA_NO_MODIFY_PATH=1` skips that) and stores the root in `~/.nodra/config.json`. Open a new terminal afterwards.
- If `nodra` is not on PATH yet, use the full path: `~/.nodra/bin/nodra` (macOS, Linux, Git Bash), `%USERPROFILE%\.nodra\bin\nodra.cmd` (Windows).
- Chat: `nodra chat` starts the chat from `<root>/chat` and opens the browser. Claude chats need Claude Code; the free chat needs `ANTHROPIC_API_KEY`.
- `nodra welcome` offers first-time setup for the detected AI tools (installs `nodra-guide` and `nodra-package`). `nodra doctor` runs local checks only: python, git presence, sources, tools detected.

## 3. Configuration

Settings resolve in this order: environment variables, `~/.nodra/config.json` (`nodra config set <key> <value>`), then `nodra/core/defaults.json`. `nodra config` prints them.

| Variable | Meaning |
| --- | --- |
| `NODRA_HOME` | Move the state directory from `~/.nodra` |
| `NODRA_ROOT` | The checkout folder (set for the chat, services and nodes) |
| `NODRA_CLI` | Command the chat/services use to call the CLI (works from a raw checkout) |
| `NODRA_JSON=1` | JSON output for every command |
| `NODRA_NO_MODIFY_PATH=1` | Installer: do not edit shell profiles |
| `NODRA_GIT_PROXY`, `NODRA_CA_BUNDLE` | Passed to git |

```text
~/.nodra/
  config.json    settings, sources, root
  state.json     installed packages
  packages/<name>/   installed files        sources/<name>/   git source clones
  venvs/<name>/      per-package Python     bin/              nodra and package shims
  backups/<name>/    setup-step backups     bots/ services/   per-bot .env and memory
  runs/              supervisor state, logs knowledge/        your notes (soul.md, ...)
  ui/                the chat: works, runs, secrets.bin, prefs.json, url.txt
  prices.json        optional: your own model prices
```

## 4. Commands

```sh
nodra search [TERM] [--type T] [--plain|--name-only]
nodra info NAME
nodra install NAME|./folder|pkg.zip [--yes] [--tool claude --tool opencode]
nodra install a b "c>=1.0"          # several; one failing never stops the rest
nodra list
nodra update --check [--no-fetch]   # newer versions in the sources
nodra update [NAME...]
nodra uninstall NAME --force
nodra disable NAME ; nodra enable NAME --yes
nodra tree [NAME] ; nodra tree "NAME>=1.2" --remote
nodra lock [--check] ; nodra sync [--check|--prune|--yes]

nodra source list | add NAME URL [--branch B] [--path P] | remove NAME | update [NAME]
nodra upgrade [--check]             # git pull --ff-only in the root, restart the chat if it ran
nodra upgrade --no-restart          # pull only; the chat auto-updates itself this way when idle (Settings > Nodra app)
nodra statusline install|remove     # opt-in: subscription 5-hour/weekly limits from Claude Code sessions on the Usage page
nodra chat [start|stop|restart|status|open]
nodra work list | show W | pull PKG | import FILE | export W [-o DIR] | setup W [--creds FILE] [--env NAME] | set W NODE k=v ...
nodra work run W [--input k=v] | runs W | logs W | enable W | disable W | serve [--bg] | cred ... | env check|install W | lib | rm W
                                    # Works without the chat page (servers); same files as the chat; see docs/cli.md

nodra run [BOT] [-- ARGS]           # start an installed bot/service in the background
nodra run BOT --fg | --name N | --schedule 5m|'0 8 * * *' | --restart no|on-failure|always | --venv PATH | --python PATH
nodra run list | logs N [-f] | listen N | stop N|--all | pause N | start N | restart N | set N ... | status N | rm N
nodra onboard [BOT]                 # optional guided credential setup ([bot] onboard)
nodra knowledge list | get NOTE | path | edit NOTE ; nodra soul     # local notes in ~/.nodra/knowledge
nodra usage [--tool claude|codex|nodra-chat] [--days N] [--by-day] [--sessions] [--tips] [--plain] [--json]
nodra vault ; nodra vault add URL --user NAME [--token-stdin] ; nodra vault test [URL|HOST]
nodra config ; nodra config set KEY VALUE
nodra doctor ; nodra welcome ; nodra version ; nodra self-uninstall [--yes]
nodra --json CMD ... | CMD --json | NODRA_JSON=1     # ONE JSON document, see section 12
```

Constraints: `name>=1.2`, `name==1.2.0`, `name>=1.0,<2`, `~=1.4`; an omitted operator means `==`; empty or `*` matches anything.

- `install` walks the dependency graph (dependencies first); constraints from every dependent are combined and a conflict names the package and who requires it. When stdin is closed, prompts count as "no": use `--yes` in scripts and CI.
- `install` on a disabled package enables it, unless the source has a newer version (then it updates).
- `disable` refuses while an enabled package depends on it (`--force` overrides). `update` skips disabled packages and never leaves the range an enabled dependent allows.
- `lock` records exact version, source revision, dependencies, `requested`, `enabled`. `sync` reinstalls exactly that.
- `usage` reads Claude Code and Codex logs on this machine and prices them from `~/.nodra/prices.json`, then the installed `nodra-prices` package, then `<root>/packages/nodra-prices/prices.json`. Nothing leaves the machine.
- `self-uninstall` removes packages, the PATH block and `~/.nodra`; the checkout is yours to delete.

Developer commands (`nodra dev`, run in a package folder or pass its path):

```sh
nodra dev init ./my-pkg --type skill|agent|mcp|tool|setup|node|workflow|bot|service --name my-pkg --description "..."
nodra dev init . --mono --packages "a,b:mcp"     # one repository, one package per sub folder
nodra dev init . --sub --name new-pkg            # add a package to a workspace folder
nodra dev init -w .                              # interactive wizard (terminal only)
nodra dev list . ; nodra dev tree .
nodra dev validate . [--only NAME]
nodra dev build PATH                             # dist/<name>-<version>.tar.gz
nodra dev pack DIR [-o OUT.zip]                  # zip one package; `nodra install OUT.zip` installs it
nodra dev marketplace [--check]                  # write/validate <root>/.claude-plugin/marketplace.json
nodra dev publish [PATH] [--bump patch|minor|major]   # git commit + git push, nothing else
nodra dev doctor [PATH] [--check] ; nodra dev tree-solve [PATH] [--nested merge|keep]
```

## 5. Sources and the Claude Code marketplace

- Add a community source: `nodra source add NAME <git-url-or-folder>`; list with `nodra source list`; refresh with `nodra source update` or `nodra update`. Only add sources you trust, since packages can run scripts.
- A source repository needs `packages/<name>/nodra.toml` folders (or set `--path`). Duplicate names: the first source wins; `core` is first.
- **This repository is a Claude Code marketplace**: `/plugin marketplace add <owner>/<repo>` then `/plugin install nodra-guide@nodra`. `.claude-plugin/marketplace.json` lists packages that have skills, agents, slash commands or MCP servers; `nodra dev marketplace` regenerates it, `--check` fails when stale.
- **Nodra reads other marketplaces**: add any repository that has `.claude-plugin/marketplace.json` as a source. Each plugin becomes a package: `skills/*/SKILL.md` become skills, `agents/*.md` agents, `commands/*.md` slash commands, `.mcp.json` MCP servers. Name and version come from the marketplace entry or the plugin's `.claude-plugin/plugin.json`. Plugins with a git `source` need git.

## 6. Tools and install locations

Nodra detects Claude Code, Codex and OpenCode when their config directory exists or their executable is on PATH. Interactive install asks which tools to use; with `--yes`, all detected tools unless `--tool` restricts.

| Tool | Skills | Agents | MCP registration |
| --- | --- | --- | --- |
| Claude Code | `~/.claude/skills/<name>/` | `~/.claude/agents/<name>.md` | `mcpServers` in `~/.claude.json` |
| Codex | `${CODEX_HOME:-~/.codex}/skills/<name>/` | custom prompt `${CODEX_HOME:-~/.codex}/prompts/<name>.md` | `[mcp_servers.<name>]` in `${CODEX_HOME:-~/.codex}/config.toml` (never overwrites yours) |
| OpenCode | `~/.config/opencode/skill/<name>/` | `~/.config/opencode/agent/<name>.md` | `mcp` entry in `~/.config/opencode/opencode.json` |

Codex has no native agent format, so agents become custom prompts. Install prompts: the CLI asks before running a platform install script and before registering components; `--yes` skips these.

## 7. Packaging a project, step by step

A package is a folder with `nodra.toml`. You share it by copying the folder into a source's `packages/` (push, or open a pull request to a community repository), or by handing out the zip from `nodra dev pack`. No account, no upload.

**Step 1. Detect.** `nodra.toml` exists: `nodra dev validate`, fix everything, go to step 5. Existing project without one: restructure (step 3). Empty folder: `nodra dev init ./my-pkg --type <type> --name <name> --description "..."`.

**Step 2. Type.**

| type | use when | required |
| --- | --- | --- |
| skill | instructions the assistant loads on demand | `[[skills]]` and `skills/<name>/SKILL.md` |
| agent | a delegated sub-agent prompt | `[[agents]]` and `agents/<name>.md` |
| mcp | an MCP server the assistant calls | `[[mcp_servers]]` (section 9) |
| tool | a command-line program | `[bin]` and install scripts |
| setup | changes environment/config, or plain data | `[[setup.steps]]` or just files |
| node | Works nodes for the chat | `nodes/*.node.json` + program (section 8) |
| workflow | a shared Works graph | `works/*.work.json` |
| bot / service | long-running program started by `nodra run` | `[bot]` / `[service]` (section 10) |

One package may combine sections; `type` is the main purpose. Registration happens only for `[[skills]]`, `[[agents]]`, `[[mcp_servers]]`.

**Step 3. Restructure.**

```text
<project>/
  nodra.toml
  README.md
  skills/<name>/SKILL.md    # plus optional reference files next to it
  agents/<name>.md
  server/ or bin/           # MCP server or executables
  scripts/install.sh  install.ps1  uninstall.sh  uninstall.ps1
  .gitignore
```

`.claude/skills/*`, `.claude/agents/*.md`, `.codex/skills/*` are copied into `skills/` and `agents/` and listed in `nodra.toml`. MCP config (`.mcp.json`, `mcpServers`) becomes `[[mcp_servers]]`; use `${PKG}` for paths inside the package, never absolute paths or secrets. Remove build output, `.env`, credentials, `node_modules` and virtualenvs.

**Step 4. Write.** SKILL.md has front matter `name` (matches the folder) and a `description` that starts with "Use when ..."; body under about 500 lines, long references in sibling files. Agent .md has `name`, `description`, optional `tools`. Scripts are idempotent, never need `sudo`, come as POSIX `sh` plus a PowerShell twin, print what they do. Every manifest path exists inside the project. Declare every external command under `[requires]`. README: install line, what it does, an example, uninstall line. No secrets or machine-specific paths.

**Step 5. Validate, pack, share.**

```sh
nodra dev validate
nodra dev pack .                 # my-pkg-0.1.0.zip
nodra install .                  # test; then: nodra uninstall my-pkg --force
```

Then copy the folder into `packages/` of a source, or push it to your own source repository (`nodra dev publish --bump patch` is `git commit` + `git push` of the package repository). For this repository also run `nodra dev marketplace`. **Bump `version` for every change**, or `nodra update --check` will not see it. Final report: package name, version, type, files moved, warnings left, and `nodra install <name>`.

## 8. Manifest (`nodra.toml`)

```toml
[package]
name = "my-tool"              # lowercase; runs of - _ . become -; 1 to 64 chars; starts and ends with letter or digit
version = "0.1.0"
type = "tool"                 # skill | agent | mcp | tool | setup | node | workflow | bot | service (default tool)
description = "A short description"
tags = []
readme = "README.md"
license = "MIT"
authors = ["Ada Lovelace <ada@example.com>"]   # "Name", "Name <email>" or {name, email, url}

[requires]
commands = [{ name = "git", hint = "Install Git first" }, "jq"]
packages = ["shared-helper>=1.2,<2"]   # other Nodra packages
os = ["macos", "linux", "windows"]     # empty = all

[python]                      # optional: creates ~/.nodra/venvs/<name>
install = false               # true: also pip-install the package folder (needs pyproject.toml; [project.scripts] become commands)
requires = ["requests>=2"]
requirements_file = "requirements.txt"

[[skills]]
name = "my-skill"
path = "skills/my-skill"

[[agents]]
name = "my-agent"
path = "agents/my-agent.md"

[[mcp_servers]]
name = "my-server"
command = "python3"
args = ["${PKG}/server/server.py"]   # ${PKG} = installed package directory
env = {}

[bin]
my-tool = "bin/my-tool.py"    # shim in ~/.nodra/bin; target must be inside the package

[scripts]
install_macos = "scripts/install.sh"
install_linux = "scripts/install.sh"
install_windows = "scripts/install.ps1"
uninstall_macos = "scripts/uninstall.sh"
uninstall_linux = "scripts/uninstall.sh"
uninstall_windows = "scripts/uninstall.ps1"

[[setup.steps]]
kind = "env"
name = "MY_TOOL_HOME"
value = "${HOME}/.my-tool"
```

Rules: only `install_`/`uninstall_` + `macos|linux|windows` script keys exist. A script value is a path inside the package or an inline command (`.sh` runs with `sh`, `.ps1` with PowerShell, `.cmd`/`.bat` with `cmd`, `.py` with Python; no spaces in paths). Scripts run in the package folder with `NODRA_PACKAGE_DIR` set; uninstall runs the uninstall script without a prompt and a nonzero exit does not stop removal. `${HOME}` and `${PKG}` are substituted in setup and MCP strings; paths expand `~`. There is no `[git]` table: a source says where packages are.

Setup step kinds (only these five): `env` (`name`, `value`: managed export block in `.zshrc`/`.bashrc`), `json_merge` (`path`, `data`: deep merge, backed up), `file` (`path`, `content` or `source`, optional octal `mode`; backed up), `block` (`path`, optional `id`, `content`: managed text block), `command` (`run`, optional `undo`). Every step asks unless `--yes`; recorded changes are reverted on uninstall and earlier steps roll back if one fails. Prefer `file`, `json_merge`, `block` over `command`; never put credentials in steps.

Versions: optional `v`, dotted numbers, optional `a`, `b`, `rc`, `dev` suffix (`1.2`, `v1.2.0`, `1.2.0rc1`, `2.0dev`). Constraints: `==`, `!=`, `>=`, `<=`, `>`, `<`, `~=`, comma-separated.

Validator warnings: an agent, mcp or tool with no `[bin]`, `[[agents]]` or `[[mcp_servers]]` and no install script for a claimed OS; a skill or agent type with no matching entry; empty description; missing README. `[python] install = true` without `pyproject.toml` is an error.

## 9. MCP servers

An MCP server is a local child process that an AI tool starts and talks to over stdin/stdout (newline-delimited JSON-RPC 2.0). Declare it with `[[mcp_servers]]` and `nodra install` registers it with each chosen tool (section 6); `nodra uninstall` removes exactly that; `disable`/`enable` toggle it. A bot's own `[[mcp_servers]]` are used only by that bot.

Minimal stdlib server (`server/server.py`):

```python
import json, sys

TOOLS = [{"name": "add", "description": "Add two numbers.",
          "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}}]

def reply(i, result=None, error=None):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i, **({"error": error} if error else {"result": result})}) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    if not line.strip():
        continue
    m = json.loads(line)
    i, method, p = m.get("id"), m.get("method"), m.get("params") or {}
    if i is None:
        continue                                   # notification: no reply
    if method == "initialize":
        reply(i, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "demo", "version": "0.1.0"}})
    elif method == "tools/list":
        reply(i, {"tools": TOOLS})
    elif method == "tools/call":
        a = p.get("arguments") or {}
        reply(i, {"content": [{"type": "text", "text": str(a["a"] + a["b"])}], "isError": False})
    else:
        reply(i, error={"code": -32601, "message": "method not found"})
```

Rules: stdout carries only protocol lines (logs go to stderr); a failing tool returns `isError: true`; no secrets in `env`; use `${PKG}` for paths. Test by piping the four messages (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`) into the script, then `nodra install ./folder --yes --tool claude` and `claude mcp list`. Servers needing pip libraries: `[python] requires` builds the venv, but `command` is not rewritten to it; use `[python] install = true` with a `pyproject.toml` console script and `command = "<script-name>"` (a shim in `~/.nodra/bin`). Node servers: `command = "npx"`, `args = ["-y", "@scope/server"]`, `[requires] commands = ["npx"]`.

In the chat: Claude chats see every server registered with Claude Code. Free chat (direct API, `ANTHROPIC_API_KEY`) runs its own tool loop over stdio servers from enabled packages, the chat's own list (`~/.nodra/ui/mcp.json`) and Claude Code's user servers. MCP servers page > Free chat tools: *Allowed* master switch, *On in new chats*, *Test / Retry* (shows tools or the error), a switch per tool. State: `~/.nodra/ui/mcp_state.json`. The model has an `nodra_mcp` tool (`status`, `retry`, `enable`, `disable`).

## 10. Works nodes

A **Work** is a graph in the chat's Works editor: a Start node produces an event, its text flows along edges through action nodes. Built-ins: `start.manual`, `start.cron`, `start.webhook`, `ai.claude`, `ai.free`, `flow.filter`, `flow.template`, `flow.output`, `flow.memory`, `flow.loop`/`flow.endloop`, `io.read_file`, `io.request`, `io.path`, `git.read`, `git.pull`, `send.smtp`, `code.python` (`# %% name` lines = steps in one namespace), `db.sql` (SQLAlchemy: PostgreSQL, SQL Server, Oracle, Trino, MySQL, SQLite, DuckDB; native / pandas / polars; Write table), `db.trino` (stdlib HTTP, no driver), `etl.spark` (PySpark steps, session or spark-submit, s3a buckets from an `s3` set). Templates: `{{input}}`, `{{trigger}}`, `{{data.key}}`, `{{in.1}}`, `{{run.dir}}`, `{{node.dir}}`. Every trigger has a `filter` regex tested before a run exists.

A node package (`type = "node"`) has `nodes/<id>.node.json` and the program it runs:

```json
{"id": "shout", "title": "Shout", "kind": "action", "group": "Text",
 "description": "Upper-cases the text.",
 "run": ["{python}", "nodes/shout.py"], "timeout": 20,
 "fields": [{"name": "suffix", "label": "Suffix", "type": "text", "default": "!"}],
 "inputs": [{"name": "input", "type": "text", "required": true}],
 "outputs": [{"name": "text", "type": "text"}, {"name": "length", "type": "text", "example": "6"}]}
```

`kind` is `trigger` or `action`; the node type is `pkg:<package>/<id>`. `run` is a list (`{python}` = the chat's interpreter, or the package venv's when `[python]` is set; `{pkg}` = the package folder; cwd = the package folder). `fields[].type`: `text`, `textarea`, `number`, `checkbox`, `select` (+`options`), `password`, `model`, `effort`, `mode`, `code` (+`lang`: colour editor with Expand / Run), `env` (the node's Python environment; `{python}` becomes it); also `label`, `default`, `required`, `help`, `secret`, `assist`. `password`/`secret` fields are stored encrypted and arrive in the stdin document, never in argv or env. `templated` lists fields where `{{...}}` is expanded before the program starts; `takes` lists fields filled from `{{data.<name>}}` of earlier nodes when empty. `credential: {"kind": "teams", "map": {...}}` plus `nodes/<name>.cred.json` shares a credential set between nodes (a field may be `"type": "list"` of entries, like the builtin `s3` buckets). `"vault": true` lets the program read the sets granted to its node with `import nodra_vault` (`vault.bucket("raw").uri("x.csv")`, `vault.credential("db")["password"]`); `import nodra_data` gives SQLAlchemy engines from a `sql` set. `"packages": ["pandas>=2"]` lists pip packages: the node's **Environment** box checks its Python and installs what is missing (managed envs in `~/.nodra/ui/envs/NAME`). **Magic ask** on every node: describe it, a model (API key, else `claude -p` without tools) proposes field values and code; nothing changes until Apply; it never sees secrets. Code fields expand full screen with **Run** / **Run selection** (unsaved settings, real run; results in `~/.nodra/ui/runs/try/`).

**Action protocol.** The program reads ONE JSON document on stdin and prints ONE JSON line last on stdout:

```python
import json, sys
req = json.load(sys.stdin)            # {"config": {...}, "input": "...", "inputs": [...], "run": {...}, "workdir": "..."}
text = str(req.get("input") or "").upper() + str((req.get("config") or {}).get("suffix") or "")
print(json.dumps({"ok": True, "output": text, "data": {"length": len(text)}, "log": "done"}))
```

`{"ok": false, "error": "why"}` or a non-zero exit fails the node; `{"output": {"skip": true}}` ends the branch quietly. Test: `echo '{"config":{"suffix":"!"},"input":"hi"}' | python3 nodes/shout.py`.

**Trigger protocol.** Started when the work is switched On, restarted after crashes. It reads ONE JSON line (`{"config": {...}, "run": {"work","node"}}`) and prints one flushed line per event: `{"event": {"text": "...", "data": {...}}}`. Listen on `127.0.0.1` only; treat message bodies as untrusted input.

Standard data keys: mail `to cc bcc subject body attachments from received message_id`; files `path paths`; HTTP `status json`; loop `item index total`. Examples in this repository: `packages/nodra-nodes-teams`, `nodra-nodes-discord`, `nodra-nodes-outlook` (Windows). Package slash commands: `slash/<name>.slash.json` = `{"name","description","prompt"}` with `$ARGUMENTS`.

## 11. Bots and services

`type = "bot"` (or `"service"`) packages run under `nodra run`. `[bot] run = "bot/run.py"` (a file inside the package), optional `title`, `onboard`, and one `[[bot.env]]` per setting (`name`, `hint`, `required`, `secret`, `default`). Services use `[service]` with `run`, `restart` (no|on-failure|always, default always), optional `schedule` and `unique = true`, and `[[service.env]]`. `nodra install` creates `~/.nodra/bots/<name>/.env` (services: `~/.nodra/services/<name>/.env`, 0600) and prints it; fill it in, then `nodra run <name>`. Never put keys in the package. The bot receives its settings as environment variables plus `NODRA_BOT_DIR`, `NODRA_BOT_HOME`, `NODRA_BOT_ENV`, `NODRA_BOT_MCP`, `NODRA_KNOWLEDGE_DIR`, `NODRA_SKILL_DIRS`, `NODRA_PACKAGE_DIRS`; arguments after `--` go to the program (`-- --info`, `-- --once "question"`). Sample bots: `nodra-bot` (harnesses `builtin`, `claude`, `codex`, `command`; memory; cron; extensions in `~/.nodra/bots/<name>/ext/*.py`) and `nodra-teams-bot`. Notes (`~/.nodra/knowledge/*.md`, `soul.md` = persona) are local files edited with `nodra knowledge edit`.

## 12. JSON output for scripts and UIs

`nodra --json CMD` prints one document: `{schema:1, ok, command, exit, error, hint, data, output, messages, changes, context}`. `context` = `{cli_version, home, root, sources:[{name,url,kind,ok}], git}`. No prompts in JSON mode (pass `--yes` yourself), stdout holds only the document, secrets go in on stdin (`vault add --token-stdin`) and never come out, and `changes` lists installed/removed/updated/enabled/disabled packages. Pass arguments as a list, never through a shell.

## 13. Troubleshooting

| Message or symptom | Fix |
| --- | --- |
| `nodra: command not found` | Open a new terminal, or use the full path (section 2) |
| `git is not installed` / source skipped | Install git, or use folder sources, zips and `core` |
| `update --check` sees no change | Bump `version` in the source's `nodra.toml` |
| `script not found in package: <path>` / `script path escapes the package` | Include the script, use an in-package relative path |
| `[bin] <cmd> points outside the package or to a missing file` | Fix the `[bin]` path |
| `skill '<name>' has no SKILL.md` | The skill folder must contain `SKILL.md` |
| `type="mcp" needs at least one [[mcp_servers]] entry` | Add an MCP server |
| `every [[skills]] entry needs a name` / `duplicate name in [[skills]]` | Add unique names (same for agents and MCP servers) |
| `[[mcp_servers]] '<name>' needs a command` | Set `command` |
| `[python] install = true needs a pyproject.toml in the package folder` | Add a `pyproject.toml`, or set `install = false` |
| Prompt in CI hangs or install skipped | stdin is closed and counts as "no"; use `--yes` |
| Codex MCP name already defined | `config.toml` has `[mcp_servers.<name>]` already; Nodra will not overwrite it |
| Chat does not open | `nodra chat status`, `nodra run logs nodra-chat`, then `nodra chat restart` |
