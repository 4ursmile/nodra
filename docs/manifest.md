# Manifest reference

Every Nodra package is a folder with an `nodra.toml` manifest at its root. `nodra dev init` creates a starter file and `nodra dev validate` checks it. The CLI parses the TOML and normalizes known fields (`nodra/core/manifest.py`, `normalize`); fields not described below are not necessarily preserved. Packages are found through [sources](sources.md): a source is a folder or git repository that holds package folders (by default `packages/<name>/nodra.toml`).

## Package metadata

`[package]` is required. `name` and `version` must be present and valid; other metadata fields have defaults.

| Field | Default | Meaning |
| --- | --- | --- |
| `name` | required | Canonical package name. Names are trimmed, lowercased, and runs of `-`, `_`, or `.` are converted to `-`. The normalized name must be 1–64 characters and start and end with a lowercase letter or digit. |
| `version` | required | Version string, such as `1.2.0` or `1.2.0rc1`. See [version rules](#versions-and-constraints). |
| `type` | `tool` | One of `skill`, `agent`, `mcp`, `tool`, `setup`, `node` (Works nodes for the Nodra chat: `nodes/*.node.json` + program; see [nodes.md](nodes.md)), `workflow` (a shared Works graph: `works/*.work.json`, no components; see [nodes.md](nodes.md)), or `bot` / `service` (see [bots.md](bots.md): `[bot]`/`[service]` run, restart, schedule, `[[bot.env]]`/`[[service.env]]`; started by `nodra run`). `mcp` packages declare [MCP servers](mcp.md). |
| `description` | `""` | Short package description. |
| `tags` | `[]` | Tags are converted to lowercase strings. |
| `readme` | `"README.md"` | Path of the README inside the package; lint warns if the file is missing. When the field is not usable, the first README found in the package root (`README.md`, `readme.md`, `Readme.md`, `README.markdown`, or `README`) is shown instead. |
| `license` | `""` | License identifier or text. |
| `authors` | `[]` | Who made the package, shown by `nodra info` and in the chat's Packages page. Each entry is `"Name"`, `"Name <email>"`, or a table `{ name = "Name", email = "...", url = "https://..." }`. `nodra dev init` fills it with your OS user name. |

Example:

```toml
[package]
name = "git-helper"
version = "1.0.0"
type = "tool"
description = "Small git workflow helpers"
tags = ["git", "workflow"]
readme = "README.md"
license = "MIT"
authors = ["Ada Lovelace <ada@example.com>"]
```

## Where the package comes from

There is no `[git]` table: a package does not say where it lives. A source (a folder or git repository, see [sources.md](sources.md)) lists the packages it holds, and `nodra install NAME` copies the folder into `~/.nodra/packages/NAME`. `nodra.toml` files that still carry a `[git]` table are accepted and the table is ignored.

## Requirements and Python dependencies

`[requires]` is optional. The installer warns if a required command is missing, recursively installs package dependencies (found through your sources), and checks supported operating systems.

```toml
[requires]
commands = [
  { name = "git", hint = "Install Git from your system package manager" },
  "jq",
]
packages = ["common-lib>=1.0,<2"]
os = ["macos", "linux"]
```

- `commands`: command names as strings or objects with `name` and optional `hint`.
- `packages`: package names, optionally followed by version constraints.
- `os`: zero or more of `macos`, `linux`, and `windows`. An empty list means no OS restriction.

Python dependencies are installed into a package-specific virtual environment (`~/.nodra/venvs/<name>`) if any of these fields is set:

```toml
[python]
requires = ["requests>=2"]
requirements_file = "requirements.txt"
install = false
```

`requires` is a list passed to pip, installed first. `requirements_file` names a file inside the extracted package. `install` (bool, default `false`) makes the package install itself: after the requirements, the installer runs `pip install` of the package folder (non-editable), so the package's own `pyproject.toml` is installed.

- Use `requires` when the package only needs other libraries.
- Use `install = true` when the package ships a `pyproject.toml` with console scripts (`[project.scripts]`, or `[tool.poetry.scripts]`). Each script is linked as a shim in `~/.nodra/bin`, so it runs directly from PATH using the venv. `nodra uninstall` removes the shims and the venv.
- The package folder must contain `pyproject.toml`. Lint reports "[python] install = true needs a pyproject.toml in the package folder", and an install without one fails with a clear error. If pip fails, the venv is removed and the install fails.
- `nodra.toml` stays the source of truth for version and description; `nodra dev doctor` keeps `pyproject.toml` in step with them. The `name` may differ on purpose (package name `my-pkg`, Python name `my_pkg`, since `-` is not valid in an import), so it is never synced or compared.

```toml
[package]
name = "my-tool"
version = "0.1.0"
type = "tool"
description = "..."

[python]
install = true
requires = ["requests"]   # optional extras installed first
```


## Skills, agents, and MCP servers

Each component section is an array of tables. Paths are relative to the package root.

```toml
[[skills]]
name = "git-helper"
path = "skills/git-helper"

[[agents]]
name = "reviewer"
path = "agents/reviewer.md"

[[mcp_servers]]
name = "repo-tools"
command = "python3"
args = ["${PKG}/server.py"]
env = { LOG_LEVEL = "info" }
```

Slash commands are markdown prompts, one file each, registered with Claude Code (`~/.claude/commands/<name>.md`), Codex and OpenCode on install:

```toml
[[commands]]
name = "release-notes"
path = "commands/release-notes.md"     # the prompt; $ARGUMENTS is replaced with what follows /release-notes
```

The chat also reads `slash/<name>.slash.json` (`{name, description, prompt}`) from installed packages for its own `/` menu; see [nodes.md](nodes.md).

MCP server entries provide `name`, `command`, optional `args` (default `[]`), and optional `env` (default `{}`). The `${PKG}` variable is replaced with the installed package directory in `args`. A server that needs pip libraries uses `[python] install = true` and a console script as its `command` (see [mcp.md](mcp.md#servers-with-python-dependencies)). See [mcp.md](mcp.md) for how servers are registered with Claude Code, Codex and OpenCode.

## Binaries and scripts

`[bin]` maps a command name to a path inside the package. The installer creates a shim under the CLI's `bin/` directory.

```toml
[bin]
repo-report = "bin/repo_report.py"
```

OS-specific scripts use `install_<os>` and `uninstall_<os>` keys, where `<os>` is `macos`, `linux`, or `windows`:

```toml
[scripts]
install_macos = "./scripts/install-macos.sh"
uninstall_macos = "./scripts/uninstall-macos.sh"
```

The install script asks for confirmation unless install is run with `--yes`. The uninstall script is run during uninstall. These are shell commands executed from the package directory.

## Setup profiles

`[setup]` can contain one or more `[[setup.steps]]` records. Each kind asks for confirmation unless the user runs installation with `--yes`. `${HOME}` and `${PKG}` are substituted in supported string values; paths also expand `~`.

```toml
[[setup.steps]]
kind = "env"
name = "MY_TOOL_HOME"
value = "${PKG}"

[[setup.steps]]
kind = "json_merge"
path = "${HOME}/.config/my-tool/settings.json"
data = { packages = ["${PKG}"] }

[[setup.steps]]
kind = "file"
path = "${HOME}/.config/my-tool/managed.txt"
content = "Package: ${PKG}\n"
mode = "600"

[[setup.steps]]
kind = "file"
path = "${HOME}/.config/my-tool/defaults.json"
source = "config/defaults.json"

[[setup.steps]]
kind = "block"
path = "${HOME}/.config/my-tool/config.toml"
id = "my-entry"
content = "# managed by Nodra"

[[setup.steps]]
kind = "command"
run = "${PKG}/scripts/setup.sh"
undo = "${PKG}/scripts/teardown.sh"
```

| Kind | Fields used by the installer | Behavior |
| --- | --- | --- |
| `env` | `name`, `value` | Adds a managed `export NAME="value"` block to `.zshrc` and to `.bashrc` if it exists. |
| `json_merge` | `path`, `data` | Deep-merges objects into a JSON file; appends only list items not already present. Backs up existing content for uninstall. |
| `file` | `path`, `content` or `source`, optional `mode` | Writes content, or copies text from a source file within the package. Existing content is backed up. `mode` is parsed as an octal string, such as `"600"`. |
| `block` | `path`, optional `id`, `content` | Adds or replaces a Nodra managed text block in a file. The default ID is the step index. |
| `command` | `run`, optional `undo` | Runs a shell command. An `undo` shell command is recorded for uninstall. |

The setup table itself is passed through by manifest normalization. The parser checks that each step kind is one of the five values above, but does not validate every required kind-specific field or its type in advance. Missing or invalid fields can fail during installation. If applying a sequence fails, previously recorded steps are reverted in reverse order where possible.

## Full example

```toml
[package]
name = "git-helper"
version = "1.0.0"
type = "tool"
description = "Git workflow commands and agent helpers"
tags = ["git", "workflow"]
readme = "README.md"
license = "MIT"

[requires]
commands = [{ name = "git", hint = "Install Git first" }]
packages = []
os = ["macos", "linux"]

[python]
requires = []
requirements_file = ""
install = false

[[skills]]
name = "git-helper"
path = "skills/git-helper"

[[agents]]
name = "reviewer"
path = "agents/reviewer.md"

[[mcp_servers]]
name = "repo-tools"
command = "python3"
args = ["${PKG}/server.py"]
env = { LOG_LEVEL = "info" }

[bin]
repo-report = "bin/repo_report.py"

[scripts]
install_macos = "./scripts/install-macos.sh"
uninstall_macos = "./scripts/uninstall-macos.sh"

[[setup.steps]]
kind = "block"
path = "${HOME}/.config/git-helper/README.txt"
content = "Managed by Nodra. Package files: ${PKG}"
```

## Versions and constraints

Version parsing accepts an optional `v`, dotted numeric components, and an optional `a`, `b`, `rc`, or `dev` prerelease suffix with optional digits. Examples include `v1.2.0`, `1.2`, `1.2.0rc1`, and `2.0dev`.

Resolver constraints are comma-separated comparisons using `==`, `!=`, `>=`, `<=`, `>`, `<`, or `~=`. An omitted operator means `==`. Empty string and `*` match any version. For example:

```text
>=1.0,<2
~=1.4
```

The `~=` implementation uses the parsed dotted numeric components to compare the shared prefix. `nodra update --check` compares the installed version with the version in the source, so **bump `version` for every change you want users to receive** (see [CONTRIBUTING.md](../CONTRIBUTING.md)). `nodra dev publish --bump` supports `major`, `minor`, and `patch`.
