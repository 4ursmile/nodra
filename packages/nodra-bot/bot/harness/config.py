"""Everything the harness knows about its surroundings comes from the environment `nodra run` sets."""
import os

HOME = os.environ.get("NODRA_BOT_HOME") or os.getcwd()          # ~/.nodra/bots/<name>: .env, mcp.json, cron.json, ext/, history
PKG = os.environ.get("NODRA_BOT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE = os.environ.get("NODRA_KNOWLEDGE_DIR") or os.path.join(HOME, "knowledge")
MCP_JSON = os.environ.get("NODRA_BOT_MCP") or os.path.join(HOME, "mcp.json")
ENV_FILE = os.environ.get("NODRA_BOT_ENV") or os.path.join(HOME, ".env")
MODEL = os.environ.get("BOT_MODEL") or "claude-sonnet-5-5"
SKILL_DIRS = [d for d in os.environ.get("NODRA_SKILL_DIRS", "").split(os.pathsep) if d]
HARNESS = os.environ.get("BOT_HARNESS") or "builtin"
MAX_TURNS = int(os.environ.get("BOT_MAX_TURNS") or 12)
