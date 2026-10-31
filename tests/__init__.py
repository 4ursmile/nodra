"""Test-suite guard: no test may touch the real ~/.nodra, ~/.claude or a real git remote.

HOME and NODRA_HOME point at a scratch folder for the whole run, and git never waits for a person. Tests that need their own folders set
NODRA_HOME (and HOME) themselves for their duration; git sources in tests are bare repositories in a temp dir.
"""
import atexit
import os
import shutil
import tempfile

_SCRATCH = tempfile.mkdtemp(prefix="nodra-tests-")
atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
os.environ["HOME"] = os.environ["USERPROFILE"] = os.path.join(_SCRATCH, "home")
os.environ["NODRA_HOME"] = os.path.join(_SCRATCH, "home", ".nodra")
os.makedirs(os.environ["HOME"], exist_ok=True)
for _k in ("ZDOTDIR", "NODRA_ROOT", "NODRA_CLI", "NODRA_JSON"):
    os.environ.pop(_k, None)

# A test git call must never wait for a person. Run from an IDE terminal, git inherits the IDE's GUI askpass (VS Code: GIT_ASKPASS +
# VSCODE_GIT_*), which opens a login dialog nobody answers.
for _k in [k for k in os.environ if k.startswith("VSCODE_GIT_")]:
    del os.environ[_k]
os.environ["GIT_ASKPASS"] = os.environ["SSH_ASKPASS"] = "true"
os.environ["GIT_TERMINAL_PROMPT"] = "0"
os.environ.setdefault("GIT_AUTHOR_NAME", "t")
os.environ.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
os.environ.setdefault("GIT_COMMITTER_NAME", "t")
os.environ.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
