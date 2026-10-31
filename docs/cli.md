# CLI guide

`nodra` is a standard-library Python program (Python 3.9+). Everything it does is local: it reads your sources, copies packages, registers them with your AI tools and starts the chat. The only network use is `git` for package sources and for `nodra upgrade`, and only when git is installed.

```
nodra [--json] COMMAND [ARGS]
```

`nodra` without a command opens a small menu in a terminal. `nodra --help` and `nodra COMMAND --help` list every flag.

## Install and configure

`python3 install.py` in the repository (Windows: `py install.py`) writes a shim `~/.nodra/bin/nodra` (plus `nodra.cmd` on Windows), adds `~/.nodra/bin` to your PATH with one marked block in your shell profile, and records the repository folder as the Nodra root in `~/.nodra/config.json`. Set `NODRA_NO_MODIFY_PATH=1` to skip the PATH change. If `nodra` is not found yet, open a new terminal or use the full path: `~/.nodra/bin/nodra` (macOS, Linux, Git Bash) or `%USERPROFILE%\.nodra\bin\nodra.cmd` (Windows).

```sh
nodra config                       # print settings as JSON
nodra config set <key> <value>
nodra doctor                       # local checks: python, git present?, sources reachable, AI tools detected
nodra welcome                      # first-time setup for detected tools (installs nodra-guide and nodra-package)
```

Settings resolve in this order: environment variables, then `~/.nodra/config.json`. Environment: `NODRA_HOME` moves the state directory from `~/.nodra`; `NODRA_ROOT` points at the checkout; `NODRA_JSON=1` turns on JSON output; `NODRA_GIT_PROXY` and `NODRA_CA_BUNDLE` are passed to git.

## Common commands

```sh
nodra search [TERM] [--type T]      # available packages from every source; each row says if it is installed
nodra search TERM --plain|--name-only
nodra info NAME                     # metadata, components, source, installed version
nodra install NAME                  # find it in the sources, copy it, register it
nodra install ./folder              # a package folder
nodra install pkg.zip               # a zip made by `nodra dev pack`
nodra install a b "c>=1.0"          # several at once; one failing never stops the rest
nodra install NAME --yes            # skip confirmations (needed when stdin is closed)
nodra install NAME --tool claude --tool opencode   # only these tools
nodra list                          # installed names, versions, enabled status
nodra update --check [--no-fetch]   # refresh git sources, list installed packages with a newer version
nodra update [NAME...]              # reinstall the newer ones
nodra uninstall NAME --force        # remove files, revert integrations and setup changes
nodra disable NAME                  # keep files, remove from tools and PATH
nodra enable NAME --yes
nodra tree [NAME]                   # dependency tree
nodra lock [--check]                # write nodra.lock (commit it)
nodra sync [--check|--prune|--yes]  # install exactly what nodra.lock says
```

Constraints accepted in names: `name>=1.2`, `name==1.2.0`, `name>=1.0,<2`, `name~=1.4`. An omitted operator means `==`.

- `install` walks the dependency graph (dependencies first); constraints from every dependent are combined and a conflict names the package and who requires it. Prompts count as "no" when stdin is closed, so use `--yes` in scripts and CI.
- `install` on a disabled package enables it, unless the source has a newer version (then it updates).
- `disable` refuses while an enabled package depends on it (`--force` overrides). `update` skips disabled packages and never moves a package outside the range its enabled dependents allow.
- `lock` records exact version, source revision (git sha, when the source is a git checkout), dependencies, `requested` and `enabled` for each package. `sync` reinstalls that on another machine and stops if a locked version can no longer be found.
- With `[python]` set in the manifest, install creates `~/.nodra/venvs/<name>`. `uninstall` removes the venv, shims and registrations.

## Sources and upgrading

```sh
nodra source list
nodra source add NAME URL [--branch B] [--path P]   # URL = git URL or a local folder; --path default packages
nodra source remove NAME
nodra source update [NAME]          # git pull the shallow clone in ~/.nodra/sources/NAME
nodra upgrade [--check]             # update the Nodra checkout itself (git pull --ff-only), restart the chat if it ran
nodra upgrade --no-restart          # pull only (the chat's own auto update uses this and restarts when idle)
nodra statusline install|remove|status   # opt-in: Claude Code's status line also keeps your subscription limits for the chat
```

The built-in source `core` is `<root>/packages` and cannot be removed. Without git, git sources are skipped with a hint; folder sources, `core`, zips and folders still work. `nodra upgrade` in a checkout that is not a git repository prints how to download and replace the zip. See [sources.md](sources.md).

## The chat

```sh
nodra chat [start|stop|restart|status|open]
```

Runs `<root>/chat` in place through the `nodra run` supervisor (service name `nodra-chat`) and prints or opens the URL from `~/.nodra/ui/url.txt`. `nodra chat` alone starts it if needed and opens the browser. Logs: `nodra run logs nodra-chat`.

## Bots, services and knowledge

```sh
nodra install nodra-bot          # prints: source folder, settings file (.env), how to run
nodra onboard [BOT]              # optional guided credential setup of a bot that has one ([bot] onboard)
nodra run BOT [-- ARGS]          # start an installed bot or service IN THE BACKGROUND (supervisor, log)
nodra run BOT --fg               # in this terminal instead (needed for an interactive chat); Ctrl-C stops it
nodra run BOT --name N --schedule '0 8 * * 1-5' --restart no -- --once "digest"
nodra run BOT --venv PATH|--python PATH   # run with that virtualenv / interpreter; remembered per package; --venv default clears
nodra run list | status N        # every run on this machine (--json)
nodra run logs N [-f] [-n 40]    # its output; `listen N` = logs -f
nodra run stop N | --all         # end it (and its supervisor); pause N = stop the bot, keep the supervisor
nodra run start N | restart N    # start a saved run again with its saved settings
nodra run set N --schedule 2h --restart on-failure [-- NEW ARGS] | --clear-args
nodra run rm N [--force]
nodra knowledge list | get NOTE | path | edit NOTE   # personal notes: ~/.nodra/knowledge/NOTE.md
nodra soul                       # shortcut for: nodra knowledge get soul
```

`nodra run` loads `~/.nodra/bots/NAME/.env` (services: `~/.nodra/services/NAME/.env`), refuses to start when a required `[[bot.env]]` value is empty (and prints the file to edit) and gives the bot its knowledge folder, skill folders and own MCP list. **Background runs:** every start goes through a small supervisor that keeps `~/.nodra/runs/ID.json` (state and heartbeat), writes all output to `ID.log` (rotated at 5 MB) and reads requests from `ID.ctl`. `--restart` is `on-failure` (default; 2 s backoff doubling to 5 min), `always` (the default for services) or `no` (default with `--schedule` or `--fg`). `--schedule` takes seconds, `30s`/`5m`/`2h`/`1d` (10 s to 7 days) or a 5-field cron expression in local time. Bot flags go after `--`: `-- --info`, `-- --once "question"`, `-- --memory`, `-- --cron`. See [bots.md](bots.md).

Notes are plain markdown files in `~/.nodra/knowledge`; there is nothing to sync. `soul.md` is your persona note, loaded first by bots and chats.

## Local usage report (`nodra usage`)

`nodra usage [--tool claude|codex|nodra-chat] [--days N] [--model REGEX] [--sessions | --session ID | --tips] [--find TEXT] [--sort recent|cost|ctx|requests] [--top N] [--by-day] [--plain] [--json]` reads the session logs the AI tools keep on this machine (Claude Code `~/.claude/projects/**/*.jsonl`, Codex `~/.codex/sessions/**/*.jsonl`, and the Free chat turns of the Nodra chat) and prints sessions, requests, input / output / cache-write / cache-read tokens, the cache hit rate and an **estimated** cost by tool and model, for today, this month, the last N days and all time. In a terminal it opens a full-screen browser (Summary, Sessions, Days, Tips; arrows, mouse, `n` types another number of days, `Enter` opens a session). `--tips` suggests savings from your own usage (cold cache rebuilds, huge contexts, low cache hit rates, expensive models on short replies). Nothing leaves the machine.

Prices come from `~/.nodra/prices.json` (yours), then the installed `nodra-prices` package, then `<root>/packages/nodra-prices/prices.json`. Keys in your own file match a model name as a case-insensitive substring (separators ` _ . / :` count as `-`, the longest key wins); `nodra-prices` patterns are regexes tried against the raw and normalized name. `--model` is a case-insensitive regex.

## Vault (git logins)

```sh
nodra vault                          # menu: add/edit/remove git remotes and logins
nodra vault add URL --user NAME      # token via prompt or --token-stdin
nodra vault test [URL|HOST]          # does the stored login reach the host?
```

Logins are kept in the OS credential store (macOS Keychain, Windows DPAPI, Linux Secret Service, else a 0600 file); the host list is `~/.nodra/vault.json`. `nodra credential` is the git credential helper that answers git with them; it is registered by `vault add` for the hosts you list, nothing else. Use it for private source repositories and for `git.read` nodes.

## Enable, disable, tree, lock and sync

`nodra disable my-skill` keeps the files but removes everything visible to your tools. `nodra enable my-skill` enables disabled dependencies first. `nodra tree` shows installed packages and what they need; `nodra tree my-skill` shows one package and which packages need it; `nodra tree "my-skill>=1.2" --remote` resolves against your sources without installing. `nodra lock -f PATH` writes another file; `sync --check` exits 1 if the machine would change.

## Supported tools and install locations

The CLI detects Claude Code, Codex and OpenCode when their configuration directory exists or their executable is on `PATH`. With interactive installation it asks which detected tools should receive package components. With `--yes`, all detected tools are selected unless `--tool` restricts them.

| Tool | Skills | Agents | MCP server registration |
| --- | --- | --- | --- |
| Claude Code | `~/.claude/skills/<name>/` | `~/.claude/agents/<name>.md` | `mcpServers` in `~/.claude.json` |
| Codex | `${CODEX_HOME:-~/.codex}/skills/<name>/` | Custom prompt in `${CODEX_HOME:-~/.codex}/prompts/<name>.md` | Managed `[mcp_servers.<name>]` section in `${CODEX_HOME:-~/.codex}/config.toml` |
| OpenCode | `~/.config/opencode/skill/<name>/` | `~/.config/opencode/agent/<name>.md` | `mcp` entry in `~/.config/opencode/opencode.json` |

Codex has no native agent format, so agent files are installed as custom prompts. Slash commands from a package (`slash/*.slash.json`) are used by the Nodra chat. Nodra installs nothing into any tool's settings other than these entries.

## Package development (`nodra dev`)

```sh
nodra dev init ./my-package --type skill --name my-package --description "A short description"
nodra dev init . --mono --packages "a,b:mcp"      # one repository, one package per sub folder
nodra dev init . --sub --name new-pkg             # add a package to a workspace folder
nodra dev init -w .                               # interactive wizard (terminal only)
nodra dev list [PATH]                             # packages and versions
nodra dev tree [PATH]                             # packages and repository status
nodra dev validate [PATH] [--only NAME]           # parse the manifest and lint referenced files
nodra dev build [PATH]                            # dist/<name>-<version>.tar.gz
nodra dev pack DIR [-o OUT.zip]                   # zip one package (skips .git, __pycache__, .venv); installable with `nodra install OUT.zip`
nodra dev marketplace [--check]                   # write/validate <root>/.claude-plugin/marketplace.json
nodra dev publish [PATH] [--bump patch|minor|major] [--only NAME]   # git commit + git push of the package repository, nothing else
nodra dev doctor [PATH] [--check]                 # repository checks; syncs version/description into pyproject.toml
nodra dev tree-solve [PATH] [--nested merge|keep] # resolve a package folder that has its own .git
```

`--type` is `skill|agent|mcp|tool|setup|node|workflow|bot|service`. `dev init` keeps an existing `nodra.toml`; `--force` overwrites the starter files it generates. `nodra dev` commands also accept a folder holding several packages and `--only NAME` (folder name, relative path or package name; repeatable or comma-separated). `dev marketplace` lists the packages under `<root>/packages` that have skills, agents, slash commands or MCP servers; `--check` exits 1 when the file is stale. See [packages.md](packages.md) and [manifest.md](manifest.md).

## JSON output (for UIs, scripts and agents)

`nodra --json CMD ...`, `nodra CMD --json` or `NODRA_JSON=1` make any command print exactly one JSON document and never prompt. The envelope:

```json
{"schema": 1, "ok": true, "command": "install", "exit": 0, "error": null, "hint": null,
 "data": null, "output": null, "messages": [], "changes": {},
 "context": {"cli_version": "1.0.0", "home": "/Users/me/.nodra", "root": "/Users/me/nodra",
             "sources": [{"name": "core", "url": "/Users/me/nodra/packages", "kind": "folder", "ok": true}], "git": true}}
```

`context` is `{cli_version, home, root, sources: [{name, url, kind, ok}], git: true|false}`. The full contract, the `data` per command and the rules are in [extending.md](extending.md).

## Local files

The default home is `~/.nodra`; set `NODRA_HOME` to override it.

```text
~/.nodra/
  config.json          settings, sources, the Nodra root
  state.json           installed packages (version, source, rev, path, enabled)
  packages/<name>/     installed package files
  sources/<name>/      shallow clones of git sources
  venvs/<name>/        per-package Python environments
  bin/                 the nodra shim and package command shims
  backups/<name>/      setup-step backups
  bots/ services/      per-bot and per-service settings (.env) and memory
  runs/                supervisor state and logs
  knowledge/           your notes (soul.md, ...)
  ui/                  the chat: works, runs, secrets.bin, prefs.json, url.txt
  prices.json          optional: your own model prices
```

## Built-in skills

`nodra-guide` (how to use Nodra: it reads the bundled offline guide and, when you have the repository, its `docs/` folder) and `nodra-package` (turns a project into a valid package) are ordinary packages in `packages/`, not code in the CLI. `nodra welcome` installs both for detected tools; remove them with `nodra uninstall nodra-guide nodra-package --force`.

## Removing Nodra

`nodra self-uninstall [--yes]` removes every installed package, the PATH block the installer added and `~/.nodra` (or `$NODRA_HOME`). It asks first unless `--yes`. The repository folder itself is yours to delete.

## Exit codes

0 = ok, 1 = failed, 2 = bad command line, 130 = interrupted.
