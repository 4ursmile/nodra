# Nodra

Nodra is an offline, community-maintained toolkit for working with AI on your own machine:

- **Local chat**: a browser app that runs on your computer, with Claude Code chats and a free chat (direct Anthropic API), canvas, terminals, notes and a usage page.
- **Works**: build workflows out of nodes (start, Claude task, filters, HTTP, files, mail, your own nodes) and run them from a schedule, a webhook, a message or a chat.
- **Package manager**: install skills, agents, MCP servers, Works nodes, bots and services from sources you choose (this repository, a community repository, a folder), and register them with Claude Code, Codex and OpenCode.

No account, no server, no telemetry. The only network use is `git` (package sources and `nodra upgrade`, optional), Claude Code or the Anthropic API for chat, and whatever your own nodes and MCP servers do.

## Requirements

- Python 3.9 or newer (the only hard requirement; Nodra uses only the standard library)
- [Claude Code](https://claude.com/claude-code) for Claude chats: sign in with your Claude subscription (Pro/Max) or an API key. With a subscription, Nodra keeps API keys out of Claude Code (Settings > Claude login) and the Usage page shows your 5-hour and weekly limits
- an `ANTHROPIC_API_KEY` only for the free chat (it calls the API directly; a subscription cannot be used there)
- git is optional (see below)

## Install

With git (macOS, Linux, Windows):

```sh
git clone <your-git-url> nodra
cd nodra
python3 install.py          # Windows: py install.py
```

Without git: download the repository as a zip, unzip it, open a terminal in the folder and run `python3 install.py` (Windows: `py install.py`).

The installer adds a `nodra` command at `~/.nodra/bin` (and `nodra.cmd` on Windows), puts that folder on your PATH with one marked block in your shell profile (`NODRA_NO_MODIFY_PATH=1` skips this) and remembers where the repository is. Open a new terminal afterwards. If `nodra` is still not found, run `~/.nodra/bin/nodra` (Windows: `%USERPROFILE%\.nodra\bin\nodra.cmd`).

`<your-git-url>` above is a placeholder for the URL of this repository.

## Quick start

```sh
nodra chat                 # starts the chat and opens it in your browser
nodra welcome              # optional: set up your AI tools (installs the nodra-guide and nodra-package skills)
nodra search               # packages you can install
nodra install nodra-slides
```

`nodra chat stop`, `nodra chat restart` and `nodra chat status` manage the background service; its log is `nodra run logs nodra-chat`.

## Updating

```sh
nodra upgrade --check      # is there a newer Nodra? (needs git)
nodra upgrade              # git pull --ff-only in this folder, then restart the chat if it was running
nodra update --check       # which installed packages have a newer version in their source
nodra update               # install them (or: nodra update NAME)
```

The chat updates itself the same way when it is idle (Settings > Nodra app > Automatic updates: on, only tell me, or off; packages too if you tick it). Without git, download the new zip and replace the folder (your packages, notes and settings are in `~/.nodra` and stay).

## Add community sources

A source is a folder or git repository with `packages/<name>/nodra.toml` folders:

```sh
nodra source add community https://example.com/team/nodra-packages.git
nodra source list
nodra search --type skill
nodra install some-package
```

Only add sources you trust: a package can run an install script and start programs, and Nodra asks before it does. Details in [docs/sources.md](docs/sources.md).

## Claude Code marketplace

This repository is also a Claude Code marketplace for its skill and agent packages:

```
/plugin marketplace add <owner>/<repo>
/plugin install nodra-guide@nodra
```

And the other way round: `nodra source add NAME URL` accepts any repository with a `.claude-plugin/marketplace.json`, so Claude Code plugins show up in `nodra search`.

## Layout

```
install.py            installer (shim, PATH, root in config)
nodra/                the CLI (cli/, core/), standard library only
chat/                 the chat app; runs in place from the checkout (ui/server.py, ui/static, ui/nodes, ui/samples)
packages/             installable packages, one folder each
  nodra-guide  nodra-package  nodra-knowledge  nodra-slides  nodra-prices
  nodra-nodes-teams  nodra-nodes-discord  nodra-nodes-outlook  nodra-bot  nodra-teams-bot
.claude-plugin/       marketplace.json for Claude Code
docs/                 reference documentation
tests/                unittest suite
```

## Documentation

| | |
| --- | --- |
| [docs/cli.md](docs/cli.md) | every command and flag, JSON output |
| [docs/sources.md](docs/sources.md) | sources, updates, upgrading, the Claude Code marketplace |
| [docs/packages.md](docs/packages.md), [docs/packages-examples.md](docs/packages-examples.md) | create and share a package, worked examples |
| [docs/manifest.md](docs/manifest.md) | `nodra.toml` reference |
| [docs/nodes.md](docs/nodes.md) | write Works nodes |
| [docs/mcp.md](docs/mcp.md) | write and test an MCP server |
| [docs/bots.md](docs/bots.md) | bots and services, `nodra run` |
| [docs/extending.md](docs/extending.md) | build on the CLI's JSON contract |

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Working with an AI assistant on this repository: [CLAUDE.md](CLAUDE.md).
