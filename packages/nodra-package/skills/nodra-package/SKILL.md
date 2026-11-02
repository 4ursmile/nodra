---
name: nodra-package
description: Use when the user wants to create, convert, restructure, validate or pack a project as a Nodra package (nodra.toml, skills, agents, MCP servers, Works nodes, bots, tools, setup profiles), new or existing, ready to copy into a package source.
---

# Nodra packaging

Turn a project into a valid Nodra package, then show the user how to share it. Work in the project root. Never push, commit or copy into another repository without the user's OK.

## 0. Find the CLI

Run `nodra version`. If the shell says `nodra: command not found` (common on Windows right after install, or in Git Bash, which cannot run `.cmd` files), use the full path for every command:

- macOS / Linux / Git Bash: `~/.nodra/bin/nodra`
- Windows PowerShell / cmd: `%USERPROFILE%\.nodra\bin\nodra.cmd`

If none exists, Nodra is not installed: ask the user to run `python3 install.py` (Windows: `py install.py`) in their Nodra checkout.

## 1. Read the references

The `nodra-guide` skill (if installed) has `offline.md`, a self-contained guide with the manifest and packaging steps. If the user has the Nodra repository (`nodra config` prints `root`), its `docs/packages.md`, `docs/manifest.md`, `docs/packages-examples.md`, `docs/nodes.md`, `docs/mcp.md` and `docs/bots.md` are the full reference. If they disagree with this skill, the docs win.

## 2. Do the five steps

1. **Detect the situation.** `nodra.toml` exists: run `nodra dev validate` and fix everything. A project without one: restructure it. An empty folder: `nodra dev init . --type <type> --name <name> --description "..."`.
2. **Choose the type**: skill, agent, mcp, tool, setup, node, workflow, bot or service.
3. **Restructure.** Show the planned moves first (use `git mv` in a repo). Standard layout: `nodra.toml`, `README.md`, `skills/<name>/SKILL.md`, `agents/<name>.md`, `server/` or `bin/`, `scripts/install.sh|ps1`, `scripts/uninstall.sh|ps1`, `.gitignore`. Copy `.claude/skills/*`, `.claude/agents/*.md`, `.codex/skills/*` into `skills/` and `agents/` and list each in `nodra.toml`. Turn MCP config (`.mcp.json`) into `[[mcp_servers]]` with `${PKG}` paths. Leave out build output, `.env`, credentials, `node_modules` and virtualenvs.
4. **Write `nodra.toml` and the files.** SKILL.md needs front matter `name` (same as the folder) and a `description` starting with "Use when ...". Declare external commands under `[requires]`. No secrets or absolute paths. Scripts are idempotent, never need `sudo`, and come as POSIX `sh` plus PowerShell.
5. **Validate, pack, share** (below).

**type = bot.** `nodra dev init . --type bot --name <name>`. It needs `[bot] run = "bot/run.py"` (a file inside the package that `nodra run` starts), optional `title`, and one `[[bot.env]]` entry per setting (`name`, `hint`, `required`, `secret`, `default`). Optional: `[[mcp_servers]]` (used only by the bot), `[python] requires`. Never put keys in the package; users fill `~/.nodra/bots/<name>/.env`. Guide: `docs/bots.md`.

**type = node (Works nodes).** `nodra dev init . --type node --name <name>` creates `nodes/<name>.node.json` plus `nodes/<name>.py` (stdin JSON in, one JSON line out). Secret fields use `"type": "password"`. Guide: `docs/nodes.md`.

**type = workflow (a shared Works graph).** `nodra dev init . --type workflow --name <name>` creates `works/<name>.work.json`. No code, no install script. List node packages it needs under `[requires] packages`; never put secrets in the file. Files the prompts mention go in `works/<name>.files/` (referenced as `@file:{{work.files}}/<file>`); credential sets travel as kinds only (`credential_kind`, `vault_kinds`). Installers can run it without the chat: `nodra work pull <name>`, `nodra work setup <work>`, `nodra work run <work>` or `nodra work serve --bg`.

**type = service (long-running program).** `nodra dev init . --type service --name <name>`. Same shape as a bot, table `[service]`: `run` (required), `title`, `onboard`, `[[service.env]]`, `restart` (no|on-failure|always, default always), optional `schedule` and `unique = true`. Settings go in `~/.nodra/services/<name>/.env`.

**type = mcp.** `nodra dev init . --type mcp --name <name>` writes a working stdlib stdio server. Guide: `docs/mcp.md`.

**Several packages in one folder.** `nodra dev init . --mono --packages "name1,name2:mcp"` (each `NAME` or `NAME:TYPE`), then `nodra dev tree` and `nodra dev validate`. Never create a package inside another package. Use `--only NAME` to work on one.

**Python packages.** `[python] requires` lists pip dependencies only. Set `[python] install = true` only when the package ships a `pyproject.toml` with console scripts (`[project.scripts]`).

## 3. Validate, pack, share

```sh
nodra dev validate            # fix every error; treat warnings as TODOs
nodra dev pack .              # writes <name>-<version>.zip (or -o OUT.zip)
nodra install . --yes         # test the install, then: nodra uninstall <name> --force
```

Then tell the user the options and let them choose:

- **Copy the folder into `packages/` of a source** (their own source repository, or a clone of a community one), commit and push, or open a pull request. People who add that source (`nodra source add NAME URL`) can `nodra install <name>`. In the Nodra repository itself also run `nodra dev marketplace` when the package has skills, agents or MCP servers.
- **Hand over the zip**: `nodra install <name>-<version>.zip`.
- **Their own repo as a source**: `packages/<name>/nodra.toml` layout; `nodra dev publish --bump patch` is just a git commit and push.

Bump `version` in `nodra.toml` for every later change, or `nodra update --check` will not offer it.

Finish by reporting: package name, version and type; files moved; warnings left; and the install command `nodra install <name>`.
