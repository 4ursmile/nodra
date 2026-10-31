# Contributing

Thank you for helping. Nodra is community maintained: there is no server and no account, so a contribution is a pull request to this repository (or to your own package source, see [docs/sources.md](docs/sources.md)).

## Setup

```sh
git clone <your-git-url> nodra && cd nodra
python3 install.py          # or run from the checkout: PYTHONPATH=. python3 -m nodra.cli --help
```

Rules for all code: the CLI (`nodra/`) and the chat server stay standard-library only and Python 3.9 compatible; no network calls except git, the Anthropic API / Claude Code and the existing sandboxed preview CDN; no telemetry of any kind; never write the old product name back into the code.

## Add or fix a package

1. Create it: `nodra dev init packages/my-pkg --type skill --name my-pkg --description "..."` (types: skill, agent, mcp, tool, setup, node, workflow, bot, service). Or edit an existing folder in `packages/`.
2. Fill in `nodra.toml`, `README.md` and the component files. Reference: [docs/manifest.md](docs/manifest.md), [docs/packages.md](docs/packages.md), [docs/packages-examples.md](docs/packages-examples.md).
3. No secrets, no absolute paths, no `[git]` table. Declare external commands and OS limits under `[requires]`.
4. Check it: `nodra dev validate packages/my-pkg`, then try it for real: `nodra install packages/my-pkg --yes`, use it, `nodra uninstall my-pkg --force`.
5. Pack it if you want to test the zip path: `nodra dev pack packages/my-pkg -o /tmp/my-pkg.zip`.

## Add or fix a node

A node package has `nodes/<id>.node.json` plus a program; protocol, fields, secrets and credentials are in [docs/nodes.md](docs/nodes.md). Test the program with a sample stdin document (the last stdout line is the JSON result), add a unittest next to the package or under `tests/`, then validate and install as above.

## Add or fix an MCP server

Declare it with `[[mcp_servers]]` and `${PKG}` paths ([docs/mcp.md](docs/mcp.md)). Pipe `initialize`, `tools/list` and `tools/call` messages into the server in a unittest, and check `nodra install ... --tool claude` registers it.

## Versions and updates

`nodra update --check` offers a package when the version in the source is newer than the installed one. So **bump `version` in `nodra.toml` for every change a user should receive** (fix: patch, new feature: minor, breaking change: major; versions look like `1.2.3`, with optional `rc1`/`dev` suffixes). A change without a bump never reaches existing users. If a package depends on a newer version of another, raise the constraint in `[requires] packages`.

## Marketplace file

Packages with skills, agents, slash commands or MCP servers are listed in `.claude-plugin/marketplace.json` for Claude Code. After you add such a package or change its name, description or version run:

```sh
nodra dev marketplace          # rewrites the file
nodra dev marketplace --check  # exits 1 when it is stale (CI runs this)
```

and commit the result.

## Tests

```sh
NODRA_HOME=$(mktemp -d) python3 -m unittest discover -s tests -t .
node --check chat/ui/static/app.js     # and the other chat/ui/static/*.js you touched
```

`NODRA_HOME` must point at a temporary directory: no test may touch your real `~/.nodra` or `~/.claude`, or a real remote. unittest only, no pytest. New CLI behaviour needs a test; a new `--json` `data` shape needs a case in `tests/test_json_output.py`.

## Changing the CLI

A new or changed command touches `nodra/cli/main.py` (parser registration and handler), `docs/cli.md` and the CLI section of `packages/nodra-guide/skills/nodra-guide/offline.md`. A new manifest field touches `nodra/core/manifest.py` (`normalize`), `docs/manifest.md`, the `offline.md` manifest section and the templates in `nodra/core/templates.py`.

## Pull request flow

1. Fork, branch from `main`, keep the change focused (one package or one feature).
2. Run the tests, `nodra dev validate` for packages you touched and `nodra dev marketplace --check`.
3. Search your diff: `rg -i 'telemetry|policy guard|/api/v1'` must find nothing new.
4. Open the pull request with what changed and how you tested it. Mention version bumps.
