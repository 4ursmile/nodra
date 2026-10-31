# Package examples

Worked examples for each package type. Every starter comes from `nodra dev init` and passes `nodra dev validate`; replace the generated placeholder content before sharing. To share a finished package, copy its folder into the `packages/` folder of a source and push (see [packages.md](packages.md) and [sources.md](sources.md)). Test each one locally first with `nodra install ./folder --yes`.

## Skill package

```sh
nodra dev init ./release-notes --type skill --name release-notes --description "Instructions for writing release notes"
cd release-notes
nodra dev validate
```

Generated files:

```text
.gitignore
README.md
nodra.toml
skills/release-notes/SKILL.md
```

The manifest registers the skill:

```toml
[[skills]]
name = "release-notes"
path = "skills/release-notes"
```

Replace the placeholder in `skills/release-notes/SKILL.md`: keep the YAML front matter (`description` starts with "Use when ...") and write concrete triggers, steps and expected output. During `nodra install release-notes` the CLI asks which detected tools (Claude Code, Codex, OpenCode) should receive the skill. Because it has skills, the package also appears in the Claude Code marketplace file after `nodra dev marketplace`.

## MCP server package

```sh
nodra dev init ./echo-mcp --type mcp --name echo-mcp --description "A small stdio echo MCP server"
cd echo-mcp
nodra dev validate
```

Generated files: `.gitignore`, `README.md`, `nodra.toml`, `server/server.py`, and `scripts/install.{sh,ps1}`, `scripts/uninstall.{sh,ps1}`. The manifest's MCP and script sections:

```toml
[[mcp_servers]]
name = "echo-mcp"
command = "python3"
args = ["${PKG}/server/server.py"]
env = {}

[scripts]
install_macos = "scripts/install.sh"
install_linux = "scripts/install.sh"
install_windows = "scripts/install.ps1"
uninstall_macos = "scripts/uninstall.sh"
uninstall_linux = "scripts/uninstall.sh"
uninstall_windows = "scripts/uninstall.ps1"
```

`server/server.py` is a minimal standard-library JSON-RPC-over-stdio server with an `echo` tool. Replace it with your implementation. On install, Nodra replaces `${PKG}` with the installed package directory and registers the server with the detected tools. The full guide, including a worked example and how to test it, is [mcp.md](mcp.md).

## Cross-platform command-line tool

```sh
nodra dev init ./greet-tool --type tool --name greet-tool --description "Print a greeting"
cd greet-tool
nodra dev validate
```

Generated files: `.gitignore`, `README.md`, `nodra.toml`, `bin/greet-tool.py`, and the four install/uninstall scripts. The manifest maps the command and selects the scripts:

```toml
[bin]
greet-tool = "bin/greet-tool.py"
```

The installer creates `greet-tool` in `~/.nodra/bin` (a shell shim on POSIX, `greet-tool.cmd` on Windows). The generated scripts only print a message; edit them if the command needs an outside prerequisite, for example:

```sh
#!/bin/sh
set -eu
echo "greet-tool: checking myformatter"
if ! command -v myformatter >/dev/null 2>&1; then
  echo "myformatter is required. Install it with your system package manager, then retry." >&2
  exit 1
fi
```

```powershell
$ErrorActionPreference = 'Stop'
Write-Host "greet-tool: checking myformatter"
if (-not (Get-Command myformatter -ErrorAction SilentlyContinue)) {
  Write-Error 'myformatter is required. Install it with your package manager, then retry.'
  exit 1
}
```

Scripts run with the package directory as working directory and `NODRA_PACKAGE_DIR` set. Installation asks before running them unless `--yes` is given. Uninstall runs the matching uninstall script, removes the shim, the package directory and any package virtual environment.

## Setup profile

```sh
nodra dev init ./editor-basics --type setup --name editor-basics --description "Basic editor environment setup"
cd editor-basics
nodra dev validate
```

The manifest contains an `env` step and a `file` step:

```toml
[[setup.steps]]
kind = "env"
name = "EDITOR_BASICS_HOME"
value = "${HOME}/.editor-basics"

[[setup.steps]]
kind = "file"
path = "${HOME}/.editor-basics/config.txt"
content = "package=${PKG}\n"
```

Edit the values and describe their effects in `README.md`. Never put credentials in a profile. Nodra asks before each step unless `--yes` is given. The `env` step adds a managed export block to `~/.zshrc` (and `~/.bashrc` if it exists); the `file` step saves a backup when it replaces a file. On uninstall Nodra removes its blocks and restores the previous content.

A `setup` package can also be plain data with no steps at all: `nodra-prices` is just a `prices.json` that `nodra usage` reads.

## Works node package

```sh
nodra dev init ./shout --type node --name shout --description "Upper-case text"
```

Writes `nodes/shout.node.json` and `nodes/shout.py`. The complete walkthrough, with the stdin/stdout protocol, a trigger example and tests, is [nodes.md](nodes.md).

## Bot or service

```sh
nodra dev init ./my-bot --type bot --name my-bot
```

Set `[bot] run = "bot/run.py"`, declare each setting as `[[bot.env]]`, install, fill `~/.nodra/bots/my-bot/.env` and start it with `nodra run my-bot`. See [bots.md](bots.md).

## Sharing any of them

```sh
nodra dev validate ./folder
nodra dev pack ./folder -o folder.zip      # a zip anybody can `nodra install`
cp -R ./folder /path/to/source-repo/packages/   # or into your own source, then commit and push
nodra dev marketplace                       # in this repository, when the package has skills/agents/MCP
```
