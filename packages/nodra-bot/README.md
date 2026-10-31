# nodra-bot

Sample chat bot for Nodra. Install it, put your key in the settings file, run it.

```sh
nodra install nodra-bot
# edit the file the installer printed (~/.nodra/bots/nodra-bot/.env): ANTHROPIC_API_KEY=...
nodra knowledge edit soul        # who the bot is for you
nodra run nodra-bot --fg         # chat in this terminal;  nodra run nodra-bot --fg -- --once "question"
nodra run nodra-bot -- --cron     # scheduled prompts in the background (nodra run list / logs nodra-bot -f / stop nodra-bot)
```

## Layout

| Path | Role |
| --- | --- |
| `bot/run.py` | entry point (`[bot] run`) |
| `bot/harness/agent.py` | system prompt, builtin tool loop, note/memory/skill tools |
| `bot/harness/executors.py` | execute layer: picks the harness from `BOT_HARNESS` (see below) |
| `bot/harness/memory.py` | soul + knowledge notes (`~/.nodra/knowledge`), and the bot's own store in `~/.nodra/bots/nodra-bot/memory/` |
| `bot/harness/skills.py` | skills of every installed package (`NODRA_SKILL_DIRS`), loaded on demand |
| `bot/harness/mcp.py` | MCP servers from `~/.nodra/bots/nodra-bot/mcp.json` (built from this package's `[[mcp_servers]]`) |
| `bot/harness/cron.py` | scheduled prompts: `cron.json` next to `.env`, then `-- --cron` |
| `bot/harness/ext.py` | extensions: any `*.py` with `register(bot)` in `~/.nodra/bots/nodra-bot/ext/` |
| `bot/harness/llm.py` | model API for the builtin harness; swap it for another provider |

`BOT_HARNESS` in `.env`: `builtin` (default, needs `ANTHROPIC_API_KEY`) | `claude` (`claude -p`) | `codex` (`codex exec`) | `command` (`BOT_HARNESS_CMD`) | a name from an extension (`bot.executor`).

Your files in `~/.nodra/bots/nodra-bot/` (`.env`, `cron.json`, `ext/`, `memory/`) are never overwritten by updates.
`-- --info` shows what the bot sees, `-- --memory` what it remembers. Docs: `docs/bots.md` in the Nodra repository.
