#!/usr/bin/env python3
"""Entry point (`nodra run nodra-teams-bot`). Finds the installed base bot (nodra-bot), puts its harness on the path, then starts the Teams app.
Usage: nodra run nodra-teams-bot [-- --info | --try "message"]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from teamsbot.base import base_bot_dir  # noqa: E402  (no harness import yet)

sys.path.insert(0, base_bot_dir())

from teamsbot.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
