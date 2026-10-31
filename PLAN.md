# Nodra migration plan

Nodra is an offline, community-maintained local chat (Claude Code harness + free chat), Works (node workflows), and a package
manager for skills, agents, MCP servers, nodes, bots and services. It was split out of a hub product. **There is no server, no
hub account, no telemetry, no usage collection, no policy guard.** The only network use is: `git` for package sources and
self-upgrade (optional), Anthropic API / Claude Code for chat, and whatever a user's node or MCP server does.

Baseline (already done): files copied from the old project and every `aihub` spelling renamed to `nodra` (`AIHUB_` -> `NODRA_`,
`aihubui` -> `nodraui`, `aihub.toml` -> `nodra.toml`, `~/.aihub` -> `~/.nodra`, old UI package -> `nodra-chat`). The code compiles
and `python3 -m nodra.cli --help` runs, but still contains every hub feature. **Nothing may reintroduce the word "aihub".**

## Target layout

```
<root>/                     the git repo (users clone it, or download its zip)
  install.py                python-only installer: shim ~/.nodra/bin/nodra (+ nodra.cmd on Windows), PATH, root in config
  nodra/                    the CLI (stdlib only, Python 3.9+)   -> lane A
    cli/  core/
  chat/                     the chat app, runs in place from the checkout   -> lane B
    nodra.toml              type = "service", name = "nodra-chat"
    ui/server.py  ui/nodraui/  ui/static/  ui/nodes/  ui/samples/
  packages/                 every installable package, one folder each      -> lane C
    nodra-guide nodra-package nodra-knowledge nodra-slides nodra-prices
    nodra-nodes-teams nodra-nodes-discord nodra-nodes-outlook nodra-bot nodra-teams-bot
  .claude-plugin/marketplace.json   Claude Code marketplace view of the skill/agent/MCP packages   -> lane C (generator: lane A)
  docs/                     cli.md manifest.md packages.md packages-examples.md nodes.md mcp.md bots.md extending.md sources.md
  tests/                    unittest only, no pytest
  README.md CONTRIBUTING.md CLAUDE.md
```

## Core concepts (all lanes must agree)

**Source** = a folder or a git repo that contains packages. Packages are found as `<source>/<path>/*/nodra.toml` (`path`
defaults to `packages`), plus a root `nodra.toml`, plus plugins listed in a Claude Code `.claude-plugin/marketplace.json`.
- Built-in source `core` = `<root>/packages` (the checkout itself). Always present, cannot be removed.
- More sources live in `~/.nodra/config.json` under `"sources": [{"name","url","branch","path"}]`; `url` is a git URL or a local
  path. Git sources are cloned to `~/.nodra/sources/<name>` (shallow), refreshed by `nodra source update` / `nodra update`.
- **git is optional.** Without git, git sources are skipped with a hint; local folders, the core source, zip and folder installs
  all still work. Python is the only hard requirement (plus Claude Code for Claude chats).
- Marketplace plugins: entries with a relative `source` (`./plugins/x`) or a git source (only if git exists). A plugin becomes a
  synthetic package: `skills/*/SKILL.md` -> skills, `agents/*.md` -> agents, `commands/*.md` -> slash commands, `.mcp.json` ->
  MCP servers. Name and version come from the marketplace entry or `.claude-plugin/plugin.json`.

**Install** copies a package folder into `~/.nodra/packages/<name>`, makes `~/.nodra/venvs/<name>` if `[python]` is set,
registers components with Claude Code / Codex / OpenCode exactly as today (`integrations.py`), and records
`{version, source, rev, path, enabled}` in `~/.nodra/state.json` (`rev` = git sha of the source checkout or null).
`nodra install` also accepts a folder path or a `.zip` of a package (used by the chat's import).

**Update**: `nodra update --check` refreshes git sources (unless `--no-fetch`) and lists installed packages whose source
version is newer (`core/version.py`). `nodra update [NAME...]` reinstalls them. The chat itself is not a package; it updates
with the checkout: `nodra upgrade [--check]` = `git pull --ff-only` in `<root>` when it is a git repo (prints how to re-download
the zip otherwise), then restarts the chat service if it was running.

## CLI contract (lane A implements, lane B consumes, lane C documents)

Kept (offline): `config`, `search [q] [--type T]` (available packages over all sources, each row has `installed` and
`installed_version`), `info NAME`, `install NAME|PATH|ZIP [--yes] [--tool T]`, `uninstall NAME --force`, `list`,
`enable NAME --yes`, `disable NAME`, `tree`, `lock`, `sync`, `update [NAME...] [--check] [--no-fetch]`, `doctor` (local checks
only: python, git presence, sources, tools detected), `welcome` (local only), `vault ...`, `credential` (hidden),
`run ...` (supervisor, minus hub reporting), `onboard`, `knowledge list|path|edit|get` and `soul` (local files
`~/.nodra/knowledge`), `usage` (local Claude/Codex logs priced by the installed `nodra-prices` package, falling back to
`<root>/packages/nodra-prices/prices.json`), `self-uninstall`, `dev init|validate|build|list|tree|doctor|tree-solve`.
`dev publish` = git commit + push only (no hub report, no `-i`).

New: `source list|add NAME URL [--branch B] [--path P]|remove NAME|update [NAME]`; `upgrade [--check]`;
`chat [start|stop|restart|status|open]` (runs `<root>/chat` in place through the run supervisor, prints/opens the URL from
`~/.nodra/ui/url.txt`); `dev pack DIR [-o OUT.zip]` (zip one package, skipping `.git`, `__pycache__`, `.venv`);
`dev marketplace [--check]` (writes/validates `<root>/.claude-plugin/marketplace.json` from `packages/*` that have skills, agents,
slash commands or MCP servers; `--check` exits 1 if stale).

Removed entirely (handlers, parser entries, modules, docs, tests): `login logout password register admin unpublish space
flush usage-sync policy hook hooks auto-update skill dev index dev stats`, `install -i/--from archive`, `download` archive mode,
`knowledge pull/push/share/...`. Modules to delete: `telemetry.py` (move `self_cmd` first), `policy.py`, `usagesync.py`,
`identity.py` (use the OS user name), `admin.py`, `spaces.py`, `updater.py` (replaced by `upgrade`), `remote_config.py` (keep
`with_access`/`NO_PROMPT`/`is_auth_error`/`store_git` in a small module), `api.py` (keep `ApiError` as `NodraError` in core),
`hooks.py`, and the hub reader in `registry.py`. `integrations.py` loses hook/plugin-js install. The run supervisor loses
`hub_on`/`_reporter`. `core/defaults.json` loses index/telemetry/tls entries.

`--json` envelope: unchanged shape `{schema:1, ok, command, exit, error, hint, data, output, messages, changes, context}`, but
`context` = `{cli_version, home, root, sources:[{name,url,kind,ok}], git:true|false}`. No `hub`, `signed_in`, `username`,
`client_id`.

Service env set by the CLI for the chat and every service/node: `NODRA_HOME`, `NODRA_ROOT`, `NODRA_CLI` (argv JSON or path the
chat uses to call the CLI; must work from a raw checkout: `[python, "-m", "nodra.cli"]` with `PYTHONPATH=<root>`).

## Chat changes (lane B)

1. **No hub.** Remove: hub login/logout (routes, Settings card, sidebar account button, `signed_in` gating), `brand` hub fetch
   (keep a local accent only), Spaces (`space.js`, `spaces/*` routes, `nodes/space_publish.py`, `@space:` sources, hub search
   mirror parts of `searchidx.py`, Spotlight hub links, `online_search` pref), knowledge push/pull/rm via CLI (notes are local
   files only), `hubusage.py` telemetry (`use()`/`kick()`; keep a purely local token log only if the Usage page reads it),
   Publish button / `PublishSteps` / `dev publish` terminals, `NODRA_NO_GUARD` env. `auth.py` (Claude `apiKeyHelper` sign-in) stays.
2. **Share = download.**
   - Chat share menu: Download chat (`.nodrachat.json`), Download page (`.html`, bundle embedded), Download zip (`chat.html`,
     `chat.nodrachat.json`, `files/`). Import accepts file upload or paste of `.json`, `.html` or `.zip`.
   - Single file share (Files changed card, canvas): downloads directly; `.html` is inlined into one self-contained file with
     `spacebundle.stage` (rename the module to `bundle.py`). Folder share: zip download (skip `.git`, `node_modules`, size cap).
   - Block/element share: direct download (HTML snapshot; SVG for svg blocks).
   - Downloads use `Content-Disposition: attachment` and keep every existing key/Host/Origin check.
3. **Works import/export.** Works editor Share -> Download work (`.work.json`, secrets blanked, logins reduced to kind) or
   Download package (`.zip` of a `type = "workflow"` package with `nodra.toml`, built in memory). Workflows dialog: Import file
   (`.work.json` or `.zip`), Samples, Installed workflow packages, Available (from `nodra search --type workflow`). Local nodes:
   Export zip / Import zip. No "find on hub".
4. **Theme.** Settings > Appearance: System / Light / Dark, pref `theme` in `store.PREF_DEFAULTS` + `save_prefs` validation.
   `<html data-theme>` set before first paint (inline script + localStorage cache in try/catch). CSS: dark tokens apply under
   `@media (prefers-color-scheme: dark) { :root:not([data-theme=light]) {...} }` and `:root[data-theme=dark] {...}`.
   `matchMedia` checks in `app.js`, `diagram.js`, `term.js` use one `isDark()` helper and re-render on change.
5. **Packages page.** Installed / Available (all sources) / Updates (Check for updates -> `update --check`; Update; Update all).
   Install / uninstall / enable / disable as today. Settings gets a Sources card (list/add/remove/update) and an Update card
   for the app (`upgrade --check` / `upgrade`), replacing `selfupdate.py`'s package-based logic.
6. Keep everything else: Claude Code chat, free chat, MCP, canvas, terminals, knowledge/soul (local), Works engine, saved nodes,
   credentials, secrets, usage page (local), slides/export, search of local chats.

## Packages, docs, marketplace (lane C)

- Every `packages/*/nodra.toml`: drop `[git]`, fix descriptions/text that mention a hub, publishing to a hub, telemetry or policy.
- `nodra-guide`: offline-first skill. `offline.md` becomes the self-contained full guide (install, sources, packages, CLI,
  chat, Works nodes, MCP, bots/services, marketplace). No hub API fetches.
- `nodra-package`: package a project for Nodra; finish with "copy into `packages/` of a source or push to your source repo",
  `nodra dev validate`, `nodra dev pack`. No hub publish.
- `nodra-knowledge`: local notes only (`~/.nodra/knowledge`, `nodra knowledge list|get|edit|path`).
- `nodra-bot`, `nodra-teams-bot`: replace knowledge push/pull and `dev publish` wording with the local flow.
- Docs as listed in the layout; `nodes.md` (from the Works node guide) and a new `mcp.md` get the most care: they are what
  community developers read. `sources.md` covers sources, updates and the Claude Code marketplace (both directions).
- Root `README.md` = install guide (clone + `python3 install.py`; zip download without git; Windows), quick start
  (`nodra chat`), updating, community sources, layout. `CONTRIBUTING.md`, `CLAUDE.md` (map + rules below).
- `.claude-plugin/marketplace.json` (hand-written now, lane A's `dev marketplace` must reproduce it).

## Rules

- CLI and `nodra/core` stay stdlib-only and Python 3.9 compatible. The chat server stays stdlib-only.
- No network calls except git (sources, upgrade), the Anthropic API/Claude Code, OSM map tiles and jsDelivr inside sandboxed
  previews (existing CSP). No telemetry of any kind.
- `rg -i 'aihub|ai hub|agentforce|telemetry|policy guard|signed_in|/api/v1'` over the repo (excluding `chat/ui/static/vendor/`)
  must come back empty or only with justified hits, which you report.
- `node --check` must pass for every `chat/ui/static/*.js` after edits (node 22 is on PATH).
- Tests: `python3 -m unittest discover -s tests -t .` with `NODRA_HOME` pointed at a temp dir; no test may touch a real
  remote or the real `~/.nodra` / `~/.claude`.
- Delete `__pycache__` before finishing. Do not run `git init` or commit.
