# nodra-package

Skill for Claude Code, Codex and OpenCode that turns a new or existing project into a valid Nodra package: it picks the package type, restructures the files, writes `nodra.toml`, then runs `nodra dev validate` and `nodra dev pack` and tells you how to share the result (copy the folder into the `packages/` folder of a package source, or push it to your own source repository). It never pushes without your OK. A folder that should hold several packages is set up with `nodra dev init --mono`.

```sh
nodra install nodra-package
nodra uninstall nodra-package --force
```

Then, inside the project, ask: "package this project for Nodra".
