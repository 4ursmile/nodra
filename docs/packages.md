# Creating and sharing packages

A Nodra package is a folder with an `nodra.toml` and the files it installs: skills, agents, MCP servers, Works nodes, bots, services, command line tools or setup steps. You share it by putting the folder in a **source**: a `packages/` folder of a git repository or a plain folder (see [sources.md](sources.md)). There is no account and no upload; anybody who adds your source can install the package.

## The 60-second path

```sh
nodra dev init ./my-tool --type tool --name my-tool --description "A short description"
cd my-tool
# TODO: edit nodra.toml, README.md, and the component or executable files.
nodra dev validate
nodra install .            # test it from the folder
nodra uninstall my-tool --force
```

Install can ask before running the OS-specific install script and before registering components with detected coding tools. Test those changes, then remove them with `uninstall`.

To share it, do one of these:

1. **Copy it into a source.** Put the folder in the `packages/` directory of a git repository (your own, or a clone of a community repository), commit, push, and open a pull request if it is someone else's. People who have that repository as a source get it with `nodra install my-tool`.
2. **Hand over a zip.** `nodra dev pack ./my-tool -o my-tool.zip` makes a zip (skipping `.git`, `__pycache__` and `.venv`). Anyone can `nodra install my-tool.zip`, or import it in the chat's Packages page.
3. **Your own source repository.** Create a repository with the layout `packages/<name>/nodra.toml`, push it, and tell users to run `nodra source add mine <your-git-url>`.

For a new release, edit the files, **bump `version`** in `nodra.toml` and push. `nodra update --check` compares the installed version with the one in the source, so an unchanged version is never offered as an update. `nodra dev publish --bump patch` (or `minor` / `major`) bumps the version, commits and pushes in one step (it is `git commit` + `git push`, nothing else).

### Several packages in one repository

Keep related packages side by side, each in its own folder with its own `nodra.toml`:

```
packages/
  nodra-guide/nodra.toml
  nodra-package/nodra.toml
```

```sh
nodra dev init packages --mono --packages "nodra-guide,nodra-package:skill"   # NAME or NAME:TYPE
nodra dev init packages --sub --name another-pkg                               # add one more
nodra dev list packages          # packages and versions
nodra dev validate packages      # checks every package
nodra dev tree packages          # packages and repository status
nodra dev publish packages --only nodra-guide --bump patch
```

`nodra dev init` refuses to create a package inside another package, or above existing packages. A package folder that carries its own `.git` inside another repository is resolved with `nodra dev tree-solve [PATH] --nested merge|keep`. `nodra dev doctor [PATH]` checks the repository and keeps a `pyproject.toml` (if any) in step with `version` and `description` (`--check` only reports).

### Marketplace file

Packages that carry skills, agents, slash commands or MCP servers are also listed in `.claude-plugin/marketplace.json` so Claude Code can install them directly. After adding or changing such a package in this repository run `nodra dev marketplace` (and `nodra dev marketplace --check` in CI). See [sources.md](sources.md).

## Let your assistant package it for you

`nodra-package` is a skill package in this repository. It works with Claude Code, Codex and OpenCode and handles both new and existing projects: it picks the package type, restructures files into the standard layout, writes `nodra.toml`, creates install/uninstall scripts where needed, and runs `nodra dev validate` and `nodra dev pack`. It finishes by telling you where to copy the folder, and does not push anything without your OK.

```sh
nodra install nodra-package
```

Then, inside the project, ask: "package this project for Nodra".

## Assistant packaging workflow

The `nodra-package` skill follows these steps. Work in the project root.

### Step 1: Detect the situation

- `nodra.toml` exists: existing package. Run `nodra dev validate`, fix every error and warning, go to step 5.
- No `nodra.toml`, folder has code/skills/agents: **existing project**, follow step 3.
- Empty or new folder: **new project**. Pick a type (step 2) and run `nodra dev init . --type <type> --name <name>`.
- The folder should hold several packages: `nodra dev init . --mono --packages "a,b:mcp"`, then `nodra dev tree`. Never create a package inside another package.

### Step 2: Choose the package type

| type | use when | required |
| --- | --- | --- |
| skill | instructions the assistant loads on demand | `[[skills]]` + `skills/<name>/SKILL.md` |
| agent | a delegated sub-agent prompt | `[[agents]]` + `agents/<name>.md` |
| mcp | an MCP server the assistant can call | `[[mcp_servers]]` (see [mcp.md](mcp.md)) |
| tool | a command line program | `[bin]` + install scripts |
| setup | changes env/config on the machine, or plain data | `[[setup.steps]]`, or just files |
| node | Works nodes for the chat | `nodes/*.node.json` + program (see [nodes.md](nodes.md)) |
| workflow | a shared Works graph | `works/*.work.json` |
| bot / service | a long-running program started by `nodra run` | `[bot]` / `[service]` (see [bots.md](bots.md)) |

One package may combine sections (for example skill + tool); `type` is the main purpose.

### Step 3: Restructure an existing project

Do not move user code blindly: show the planned moves, then apply them (use `git mv` in a repo).

```
<project>/
  nodra.toml
  README.md
  skills/<name>/SKILL.md    # + optional reference files next to it
  agents/<name>.md
  server/ or bin/           # MCP server / executables
  scripts/install.sh  install.ps1  uninstall.sh  uninstall.ps1
  .gitignore
```

- Existing `.claude/skills/*`, `.claude/agents/*.md`, `.codex/skills/*`: copy into `skills/` and `agents/` and list each in `nodra.toml`.
- Existing MCP config (`.mcp.json`, `mcpServers`): becomes `[[mcp_servers]]`; use `${PKG}` for paths inside the package, never absolute paths or secrets.
- Remove build output, `.env`, credentials, `node_modules`, virtualenvs from the package.

### Step 4: Write `nodra.toml` and the files

Field reference: [manifest.md](manifest.md). Quality rules:

- SKILL.md: front matter `name` (matches the folder) and a `description` that starts with "Use when ..."; body under about 500 lines, long references in sibling files.
- Agent .md: front matter `name`, `description`, optional `tools`.
- Scripts: idempotent, no `sudo`, no admin rights, POSIX `sh` + PowerShell twin; print what they do. `chmod +x` shell scripts and executables.
- Every `path` in the manifest must exist and stay inside the project. Declare every external command under `[requires]`.
- Python: `[python] requires` is for pip dependencies only. Set `install = true` only when the package ships a `pyproject.toml` with `[project.scripts]` console scripts.
- README: install line (`nodra install <name>`), what it does, a usage example, uninstall line.
- No secrets, tokens, or machine-specific paths anywhere in the package.
- Setup steps (`env`, `json_merge`, `file`, `block`, `command`) are shown to the user and reversible; prefer `file`/`json_merge`/`block` over `command`.

### Step 5: Validate, pack, share

```sh
nodra dev validate     # fix all errors; treat warnings as TODOs
nodra dev pack .       # my-tool-0.1.0.zip (or -o OUT.zip)
nodra install .        # test the install
nodra uninstall my-tool --force
```

Then copy the folder into the `packages/` folder of a source, or push it to your own source repository. Finish by reporting: package name/version/type, files moved, warnings left, and the install command `nodra install <name>`.

## Choosing a package type

| Type | Use it for | Registered where | Scaffold | Install scripts? |
| --- | --- | --- | --- | --- |
| `skill` | Reusable instructions for an assistant | Claude Code, Codex and OpenCode skill directories | `--type skill` | No |
| `agent` | A specialized agent prompt | Claude Code agents, Codex custom prompts, OpenCode agents | `--type agent` | No |
| `mcp` | A stdio MCP server | Claude Code, Codex and OpenCode MCP configuration | `--type mcp` | OS-specific examples |
| `tool` | An executable command | A shim under the Nodra CLI bin directory | `--type tool` | OS-specific examples |
| `setup` | Reversible configuration changes, or plain data files | User shell config, JSON/text files, optional commands | `--type setup` | No; use `[[setup.steps]]` |
| `node` | Works nodes | The chat's Add node list | `--type node` | No |
| `workflow` | A shared Works graph | The chat's Works page | `--type workflow` | No |
| `bot`, `service` | Long-running programs | `nodra run NAME` | `--type bot`, `--type service` | No |

Registration only happens for manifest component declarations (`[[skills]]`, `[[agents]]`, `[[mcp_servers]]`). A package's `type` does not itself register a component.

## Project layouts

These are the file trees `nodra dev init` writes for `--name my-<type>`.

```text
skill:    .gitignore README.md nodra.toml skills/my-skill/SKILL.md
agent:    .gitignore README.md nodra.toml agents/my-agent.md
bot:      .gitignore README.md nodra.toml bot/run.py
mcp:      .gitignore README.md nodra.toml server/server.py scripts/install.{sh,ps1} scripts/uninstall.{sh,ps1}
tool:     .gitignore README.md nodra.toml bin/my-tool.py scripts/install.{sh,ps1} scripts/uninstall.{sh,ps1}
setup:    .gitignore README.md nodra.toml
node:     .gitignore README.md nodra.toml nodes/my-node.node.json nodes/my_node.py
workflow: .gitignore README.md nodra.toml works/my-flow.work.json
```

- A skill's `SKILL.md` starts with YAML front matter for `name` and `description`.
- The MCP starter is a minimal standard-library JSON-RPC server over stdio.
- Full guides: [bots.md](bots.md) for bots and services, [nodes.md](nodes.md) for nodes and workflows, [mcp.md](mcp.md) for MCP servers.

## The manifest

`nodra.toml` describes package metadata, dependencies, components, scripts, binaries and setup steps. The templates start with:

```toml
[package]
name = "my-tool"
version = "0.1.0"                 # bump it for every release so `nodra update --check` sees it
type = "tool"                     # skill | agent | mcp | tool | setup | node | workflow | bot | service
description = "A short description"
tags = []                         # lowercase words people search for
readme = "README.md"
license = "MIT"
authors = []                      # "Ada Lovelace <ada@example.com>" or {name, email, url}

[requires]
commands = []                     # e.g. [{name = "git", hint = "brew install git"}]
packages = []                     # other Nodra packages this needs, e.g. ["base-tools>=1.0"]
os = []                           # empty = all. Or any of: "macos", "linux", "windows"
```

See [manifest.md](manifest.md) for every field, defaults, versions and setup steps.

## Install and uninstall scripts

Scripts let a package perform external setup that cannot be expressed as file placement, component registration or setup steps. Skills and setup profiles generally do not need them. The validator warns if an `agent`, `mcp` or `tool` has no `[bin]`, `[[agents]]` or `[[mcp_servers]]` entry and lacks install scripts for supported operating systems.

```toml
[scripts]
install_macos = "scripts/install.sh"
install_linux = "scripts/install.sh"
install_windows = "scripts/install.ps1"
uninstall_macos = "scripts/uninstall.sh"
uninstall_linux = "scripts/uninstall.sh"
uninstall_windows = "scripts/uninstall.ps1"
```

An entry is either a script path inside the package or an inline shell command. A path ending in `.sh` runs with `sh`, `.ps1` with PowerShell, `.cmd` or `.bat` with `cmd`, and `.py` with the current Python. Paths must stay inside the package and contain no spaces. The installer runs scripts with the package directory as working directory and sets `NODRA_PACKAGE_DIR`. Unless the user passes `--yes`, installation asks for approval first.

Good scripts are idempotent, do not use `sudo`, avoid unexpected network activity, print what they do, and exit nonzero if required work fails. Nodra removes package files and registered integrations itself; scripts should only undo their own external changes. Example `scripts/install.sh`:

```sh
#!/bin/sh
set -eu
echo "my-tool: checking myformatter"
if ! command -v myformatter >/dev/null 2>&1; then
  echo "myformatter is required. Install it with your system package manager, then retry." >&2
  exit 1
fi
```

And `scripts/install.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
Write-Host "my-tool: checking myformatter"
if (-not (Get-Command myformatter -ErrorAction SilentlyContinue)) {
  Write-Error 'myformatter is required. Install it with your package manager, then retry.'
  exit 1
}
```

## Binaries and registered components

A `[bin]` mapping creates a launcher in the Nodra `bin/` directory (an executable shell shim on POSIX, a `.cmd` shim on Windows). The target must be a file inside the package. Python targets run through the package virtual environment when `[python]` created one.

```toml
[bin]
my-tool = "bin/my-tool.py"

[[mcp_servers]]
name = "my-server"
command = "python3"
args = ["${PKG}/server/server.py"]

[[skills]]
name = "my-skill"
path = "skills/my-skill"

[[agents]]
name = "my-agent"
path = "agents/my-agent.md"
```

Claude Code, Codex and OpenCode are supported. Codex installs agent files as custom prompts. See [cli.md](cli.md#supported-tools-and-install-locations) for exact locations.

## Requirements and Python

```toml
[requires]
commands = [{ name = "myformatter", hint = "Install myformatter with your system package manager" }]
packages = ["shared-helper>=1.2,<2"]
os = ["macos", "linux", "windows"]

[python]
requires = ["requests>=2"]
requirements_file = "requirements.txt"
install = false
```

The installer reports missing commands but does not install them. Package dependencies are resolved through your sources and installed first. `[python]` creates `~/.nodra/venvs/<name>`; `install = true` also pip-installs the package folder (it needs a `pyproject.toml`; its `[project.scripts]` commands are linked into `~/.nodra/bin`).

## Versioning and updates

Bump `version` for every release. Dependency constraints accept `==`, `!=`, `>=`, `<=`, `>`, `<`, `~=`, comma-separated; an omitted operator means equality, `*` matches anything (see [manifest.md](manifest.md#versions-and-constraints)).

```toml
[requires]
packages = ["shared-helper>=1.0,<2", "exact-helper==2.1"]
```

`nodra lock` writes `nodra.lock` with the exact version and source revision of every installed package; `nodra sync` reinstalls exactly that.

## Pre-share checklist

- [ ] Valid, unique package name and a new version.
- [ ] No scaffold placeholders left in prompts, scripts and README.
- [ ] Every component and script path exists inside the project.
- [ ] Supported operating systems and required commands declared accurately.
- [ ] Scripts and setup commands reviewed for side effects; no elevated privileges, no unexpected networking.
- [ ] `nodra dev validate` clean; every warning reviewed.
- [ ] `nodra install .` and `nodra uninstall NAME --force` tested on the systems you claim.
- [ ] If the package has skills, agents or MCP servers and lives in this repository: `nodra dev marketplace`.
- [ ] No secrets or local build artifacts in the folder.

## Troubleshooting

| Message or symptom | Meaning and next step |
| --- | --- |
| `nodra update --check` shows nothing after a change | The version was not bumped. Edit `version` in `nodra.toml`. |
| `git is not installed` | Git sources are skipped. Install git, or use a local folder source / zip. |
| `script not found in package: <path>` | A script path is missing. Include it or correct the manifest. |
| `script path escapes the package: <path>` | Use an in-package relative path. |
| `[bin] <command> points outside the package or to a missing file` | Fix the `[bin]` path. |
| `skill '<name>' has no SKILL.md in <path>` | A declared skill directory must contain `SKILL.md`. |
| `type="mcp" needs at least one [[mcp_servers]] entry` | Add an MCP server declaration. |
| `every [[skills]] entry needs a name` | Add a non-empty `name` (same for agents and MCP servers). |
| `duplicate name in [[skills]]` | Component names must be unique within their table. |
| `[[mcp_servers]] '<name>' needs a command` | Set a command. |
| `package.description is empty` (warning) | Add a description. |
| `README '<path>' not found` (warning) | Add the README or correct `package.readme`. |
| `[python] install = true needs a pyproject.toml in the package folder` | Add a `pyproject.toml` with `[project.scripts]`, or set `install = false`. |
| `1 problem(s) in the project` | Fix the `error:` lines printed above it, run `nodra dev validate` again. |

TOML parsing and manifest normalization errors also stop `validate`; their text names the missing or invalid field: missing `[package]`, invalid name/version/type, unknown setup-step kind, invalid `[scripts]` key, missing or duplicate component name, missing MCP command, or unsupported `requires.os` value.
