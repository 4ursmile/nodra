# Nodra repository guide

Nodra = offline local chat + Works (node workflows) + package manager for skills, agents, MCP servers, nodes, bots and services. No server, no account, no telemetry.

## Layout

```
install.py                python-only installer: ~/.nodra/bin/nodra shim, PATH block, root in config
nodra/cli/                CLI: main.py (parser + handlers), installer.py, integrations.py (Claude/Codex/OpenCode), registry.py (sources),
                          runs.py (nodra run supervisor), vault.py, usage.py, ui.py (output + JSON envelope), ...
nodra/core/               manifest.py (normalize), templates.py (dev init), version.py, defaults.json, toml_lite.py, ...
chat/                     chat app, runs in place: nodra.toml (service nodra-chat), ui/server.py, ui/nodraui/, ui/static/, ui/nodes/, ui/samples/
packages/<name>/          installable packages (nodra.toml each): nodra-guide nodra-package nodra-knowledge nodra-slides nodra-prices
                          nodra-nodes-teams nodra-nodes-discord nodra-nodes-outlook nodra-bot nodra-teams-bot
.claude-plugin/marketplace.json   Claude Code marketplace view of packages with skills/agents/MCP (generated: nodra dev marketplace)
docs/                     cli manifest packages packages-examples nodes mcp bots sources extending (.md)
tests/                    unittest only
PLAN.md                   the migration contract (concepts, CLI contract, chat changes)
```

State lives in `~/.nodra` (`NODRA_HOME` moves it): `config.json` (sources), `state.json` (installed), `packages/`, `sources/`, `venvs/`, `ui/`, `knowledge/`.

## Commands

```sh
python3 install.py                                  # install the shim (Windows: py install.py)
PYTHONPATH=. python3 -m nodra.cli --help            # run the CLI from the checkout
nodra chat                                          # start the chat (runs <root>/chat in place)
NODRA_HOME=$(mktemp -d) python3 -m unittest discover -s tests -t .
node --check chat/ui/static/app.js                  # every chat/ui/static/*.js you edit
nodra dev validate packages/<name>                  # lint a package
nodra dev marketplace --check                       # marketplace.json up to date?
```

## Rules

- CLI and `nodra/core` are stdlib-only and Python 3.9 compatible. The chat server is stdlib-only too.
- No network calls except git (sources, upgrade), the Anthropic API / Claude Code, OSM tiles and jsDelivr inside sandboxed previews (existing CSP). No telemetry, no usage collection, no policy guard, no hub or account concepts.
- Never write the old product name back (`rg -i 'aihub|ai hub|agentforce|telemetry|policy guard|signed_in|/api/v1'` over the repo, excluding `chat/ui/static/vendor/`, must be empty or justified).
- `git` is optional: every git path must degrade to a hint, never a crash; folders, zips and `core` always work.
- Tests: `unittest` only, `NODRA_HOME` pointing at a temp dir; no test touches the real `~/.nodra`, `~/.claude` or a remote.
- Delete `__pycache__` before finishing. Do not `git init` or commit unless asked.

## When you change X, also change Y

| Change | Also touch |
| --- | --- |
| A CLI command or flag | `nodra/cli/main.py` (parser registration and handler), `docs/cli.md`, `packages/nodra-guide/skills/nodra-guide/offline.md`, tests |
| A `--json` `data` shape or the envelope/context | `docs/extending.md`, `docs/cli.md`, `tests/test_json_output.py`, the chat's `nodraui/nodra.py` consumer |
| A manifest field | `nodra/core/manifest.py` (`normalize`), `docs/manifest.md`, `offline.md` manifest section, `nodra/core/templates.py`, validator in `nodra/cli/` |
| A package (version, description, skills/agents/MCP) | its `nodra.toml` (bump `version`), `nodra dev marketplace`, its README |
| A Works node protocol or builtin node | `docs/nodes.md`, `offline.md` section 10, `chat/ui/nodraui/works.py`, `chat/ui/nodes/` |
| MCP registration (`integrations.py`) or the chat's MCP page | `docs/mcp.md`, `offline.md` section 9 |
| Sources, update or upgrade behaviour | `docs/sources.md`, README "Updating", `docs/cli.md` |
| A bot or service behaviour | `docs/bots.md`, the package README, `packages/nodra-bot` tests |

## Conventions

- Print through `ui.*` in the CLI (so JSON mode gets `messages`); give data via `ui.result(data)`; secrets never go to `ui.*`; prompts must check `ui.INTERACTIVE`.
- Package versions drive updates: bump `version` in `nodra.toml` for every user-visible change.
- Docs use `<your-git-url>` as the placeholder for this repository's URL.
- Skills: `SKILL.md` front matter `name` equals the folder; `description` starts with "Use when".
