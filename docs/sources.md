# Sources, updates and the Claude Code marketplace

A **source** is a place where packages live: a folder or a git repository. Nodra has no central server. What you can install is whatever your sources contain.

## What counts as a package in a source

For a source with root `R` and `path` (default `packages`), Nodra finds:

1. `R/<path>/*/nodra.toml`: one package per sub folder.
2. A `nodra.toml` at `R` itself (a single-package repository).
3. Plugins listed in `R/.claude-plugin/marketplace.json` (a Claude Code marketplace, see below).

The built-in source **`core`** is `<root>/packages`, the checkout you installed Nodra from. It is always present and cannot be removed.

## Manage sources

```sh
nodra source list
nodra source add community https://example.com/team/nodra-packages.git
nodra source add work https://example.com/team/tools.git --branch main --path packages
nodra source add local ~/my-packages                    # a plain folder works too
nodra source update [NAME]                              # refresh git sources
nodra source remove community
```

Sources are stored in `~/.nodra/config.json`:

```json
{"sources": [{"name": "community", "url": "https://example.com/team/nodra-packages.git", "branch": "main", "path": "packages"}]}
```

`url` is a git URL or a local path. Git sources are cloned shallowly to `~/.nodra/sources/<name>` and refreshed by `nodra source update` and `nodra update`. Private repositories use your normal git login, or one stored with `nodra vault add`. Once a source is added, `nodra search` and `nodra install` see its packages like any other. If two sources hold the same package name, the first source in `nodra source list` wins and `core` comes first.

### Community sources

Anyone can publish a source: a git repository with `packages/<name>/nodra.toml` folders (see [packages.md](packages.md)). Share its URL; users run `nodra source add NAME URL`. **A package can run install scripts and start programs, so only add sources you trust**; `nodra install` shows what a package will do and asks first, and `nodra info NAME` shows its components and scripts before you install.

## git is optional

Python is the only hard requirement. Without git:

- git sources are skipped, with a hint that names the missing tool;
- the `core` source, local folder sources, `nodra install ./folder` and `nodra install pkg.zip` keep working;
- `nodra upgrade` cannot pull. If the checkout is not a git repository it prints how to re-download the repository zip and replace the folder.

`nodra doctor` reports whether git is present and whether each source is reachable.

## Updates

```sh
nodra update --check            # refresh git sources, list installed packages whose source has a newer version
nodra update --check --no-fetch # compare against what is already on disk
nodra update                    # reinstall every package that has a newer version
nodra update my-skill other     # only these
nodra upgrade --check           # is there a newer Nodra (the checkout itself)?
nodra upgrade                   # git pull --ff-only in <root>, then restart the chat if it was running
```

A package is updated when the **version** in its source's `nodra.toml` is newer than the installed one, so package authors must bump `version` for every change (see [../CONTRIBUTING.md](../CONTRIBUTING.md)). `nodra update` never moves a package outside the range its enabled dependents allow, and skips disabled packages.

The chat app itself is not a package: it lives in `<root>/chat` and runs in place, so `nodra upgrade` updates it together with the CLI and the `core` packages. The chat's Packages page has the same three views: Installed, Available (all sources) and Updates, and Settings has a Sources card and an update card for the app.

The chat also keeps itself current: every hour (`UI_UPDATE_MINUTES`) it runs `nodra upgrade --check`, and when the checkout is behind it waits until nothing runs (no chat answering, no work, no install) for a minute, pulls with `nodra upgrade --no-restart` and restarts. The key and port stay, so open pages reconnect and show **Reload** for the new version. Settings > Nodra app > *Automatic updates*: **Update and restart when idle** (default), **Only tell me** (a bar says an update is waiting) or **Off**; *Also update packages* runs `nodra update` the same way (off by default; the Updates count is shown either way). A pull that fails (no network, local changes that conflict) is retried only after the remote moves on or you press Check.

`nodra lock` and `nodra sync` pin the exact version and source revision of installed packages, so a team gets the same set on every machine.

## The Claude Code marketplace, both ways

Claude Code can install plugins from a "marketplace": a repository with `.claude-plugin/marketplace.json`. Nodra works with that format in both directions.

### This repository is a marketplace

`.claude-plugin/marketplace.json` lists the packages of `packages/` that carry skills, agents, slash commands or MCP servers (not bots, nodes or data packages). In Claude Code:

```
/plugin marketplace add <owner>/<repo>
/plugin install nodra-guide@nodra
```

(or the git URL instead of `<owner>/<repo>`). Claude Code then installs those plugins itself, without Nodra. The skill folders `skills/<name>/SKILL.md` are already the layout Claude Code expects, so the package folder is also the plugin folder.

The file is generated:

```sh
nodra dev marketplace           # (re)write .claude-plugin/marketplace.json from packages/*
nodra dev marketplace --check   # exit 1 when it is stale (use it in CI)
```

Format:

```json
{
  "name": "nodra",
  "owner": {"name": "Nodra community"},
  "plugins": [
    {"name": "nodra-guide", "source": "./packages/nodra-guide", "description": "...", "version": "2.5.0"}
  ]
}
```

Run `nodra dev marketplace` after changing a package's description, version or components, and commit the result.

### Nodra reads other marketplaces

Add any repository that has a `.claude-plugin/marketplace.json` as a source:

```sh
nodra source add some-plugins https://github.com/someone/claude-plugins.git
nodra search --type skill
nodra install some-plugin
```

Each plugin entry becomes a synthetic package:

| In the plugin folder | Becomes |
| --- | --- |
| `skills/*/SKILL.md` | skills |
| `agents/*.md` | agents |
| `commands/*.md` | slash commands |
| `.mcp.json` | MCP servers |

The package name and version come from the marketplace entry (or the plugin's `.claude-plugin/plugin.json`). Entries with a relative `source` (`./plugins/x`) are read from the cloned or local folder. Entries whose `source` is a git repository are fetched only when git is available. Install, update, enable, disable and uninstall work exactly like for native packages, and the components are registered with Claude Code, Codex and OpenCode.
