"""Locate the base bot's code folder (<nodra-bot>/bot, the one holding harness/). `nodra run` lists installed packages in NODRA_PACKAGE_DIRS."""
import os


def base_bot_dir():
    cands = [os.environ.get("NODRA_BASE_BOT", "")]
    cands += [os.path.join(d, "bot") for d in os.environ.get("NODRA_PACKAGE_DIRS", "").split(os.pathsep)
              if d and os.path.basename(d.rstrip("/\\")) == "nodra-bot"]
    home = os.environ.get("NODRA_HOME") or os.path.join(os.path.expanduser("~"), ".nodra")
    cands.append(os.path.join(home, "packages", "nodra-bot", "bot"))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "harness", "__init__.py")):
            return c
    raise SystemExit("the base bot is missing. Install it with: nodra install nodra-bot   (or point NODRA_BASE_BOT at its bot/ folder)")
