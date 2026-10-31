---
name: nodra-guide
description: Use when the user asks how to use Nodra (the nodra CLI, chat, Works nodes, MCP servers, bots; install, search, update or package things; add a package source) or wants a project set up for a specific case that is not covered by a fixed recipe.
---

# Nodra guide (offline first)

Nodra is an offline, community-maintained local chat, Works (node workflows) and package manager. There is no server, no account and no telemetry. Answer from the documents below, not from memory.

## 0. Find the CLI

Run `nodra version`. If the shell says `nodra: command not found` (common on Windows right after install, or in Git Bash, which cannot run `.cmd` files), use the full path for every command:

- macOS / Linux / Git Bash: `~/.nodra/bin/nodra`
- Windows PowerShell / cmd: `%USERPROFILE%\.nodra\bin\nodra.cmd`
- Last resort: `python3 -m nodra.cli` with `PYTHONPATH` set to the Nodra checkout (Windows: `py -3 ...`)

If none exists, Nodra is not installed: ask the user to clone the repository and run `python3 install.py` in it (Windows: `py install.py`), or download the repository zip, unzip it and run the same.

## 1. Read the docs

1. `offline.md` next to this SKILL.md is the self-contained guide: install, sources, packages, CLI, chat, Works nodes, MCP, bots, marketplace. Read it first.
2. If the user has the Nodra repository, `nodra config` prints its folder under `root`. Its `docs/` folder holds the full reference and wins over `offline.md` when they differ:

| file in `<root>/docs` | read it for |
| --- | --- |
| `cli.md` | every `nodra` command and flag, tool install locations, the JSON output |
| `manifest.md` | `nodra.toml` fields, setup steps, scripts, requirements, versions |
| `packages.md`, `packages-examples.md` | project layouts per package type, sharing a package, worked examples |
| `nodes.md` | writing Works nodes: the stdin/stdout protocol, triggers, secrets, credentials |
| `mcp.md` | writing and testing an MCP server, how install registers it, the chat's MCP page |
| `bots.md` | chat bots (`type = "bot"`) and services (`type = "service"`), `nodra run`, `.env` settings |
| `sources.md` | package sources, updates, `nodra upgrade`, the Claude Code marketplace |
| `extending.md` | building a UI or script on the CLI JSON contract (`nodra --json`) |

Read only what the task needs, and cite the file you relied on when you explain a choice.

## 2. Pick the workflow

- **Use packages**: `nodra search`, `info`, `install`, `update --check`, `update`, `uninstall`, `enable/disable`, `lock/sync`. Take exact flags from `offline.md` or `cli.md` and run them. Confirm with the user before installing anything that runs scripts.
- **Add a source of packages**: `nodra source add NAME URL` (a git repository or a folder). Only add sources the user trusts; packages can run scripts.
- **Update Nodra itself**: `nodra upgrade --check`, then `nodra upgrade`.
- **Package a project**: if the `nodra-package` skill is installed, follow it; otherwise follow `packages.md` and `manifest.md`, or the packaging section of `offline.md`. Sharing means copying the folder into a source's `packages/` or pushing it to the user's own source repository. `nodra dev validate` and `nodra dev pack` check and bundle it.
- **Works nodes**: read `nodes.md` (or the Works section of `offline.md`) and start from `nodra dev init ./name --type node --name name`.
- **MCP server**: read `mcp.md`; start from `nodra dev init ./name --type mcp --name name`.
- **Several packages in one folder**: `nodra dev init . --mono --packages "a,b:mcp"`, then `nodra dev tree` and `nodra dev validate`.
- **Remove Nodra**: `nodra self-uninstall` (asks first; `--yes` skips the question).

## 3. Rules

- If the docs and this skill disagree, the docs win.
- Never delete, push or change a user's source repositories without the user's explicit OK.
- Never put tokens or secrets into files you create.
- If a command the docs mention is missing from `nodra --help`, trust `--help` and say so.
