"""Shared helpers for the CLI tests: temp NODRA_HOME / HOME / NODRA_ROOT, package folders, bare git repositories."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
from unittest import mock

from nodra.cli import main, ui

UI_FLAGS = ("JSON", "TTY", "COLOR", "FANCY", "INTERACTIVE")


class KeepUi:
    """`--json` switches the terminal flags of ui for the rest of the process; a test that runs it puts them back."""
    def __enter__(self):
        self.saved = {k: getattr(ui, k) for k in UI_FLAGS}
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            setattr(ui, k, v)
        del ui.LOG[:]
        ui.DATA.clear()


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t"] + list(a), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def run(*argv):
    """-> (exit code, output). Output of the command goes to one buffer."""
    b = io.StringIO()
    with KeepUi(), contextlib.redirect_stdout(b), contextlib.redirect_stderr(b):
        rc = main.main(list(argv))
    return rc, b.getvalue()


def run_json(*argv):
    """-> the JSON document of `nodra --json ARGV` (exactly one document on stdout)."""
    out = tempfile.TemporaryFile(mode="w+")
    import sys
    keep = os.dup(1)
    sys.stdout.flush()
    os.dup2(out.fileno(), 1)
    try:
        with KeepUi(), mock.patch.object(sys, "stdout", os.fdopen(os.dup(1), "w")):
            code = main.main(["--json"] + list(argv))
            sys.stdout.flush()
    finally:
        os.dup2(keep, 1)
        os.close(keep)
    out.seek(0)
    d = json.loads(out.read())
    assert code == d["exit"], (code, d)
    return d


def make_pkg(parent, name, version="1.0.0", deps=(), kind="skill", extra=""):
    """A skill package folder `parent/name` with nodra.toml, one skill and a README."""
    d = os.path.join(parent, name)
    os.makedirs(os.path.join(d, "skills", name), exist_ok=True)
    with open(os.path.join(d, "nodra.toml"), "w") as f:
        f.write('[package]\nname = "%s"\nversion = "%s"\ntype = "%s"\ndescription = "%s package"\ntags = ["demo"]\n[requires]\npackages = %s\n'
                '[[skills]]\nname = "%s"\npath = "skills/%s"\n%s' % (name, version, kind, name, json.dumps(list(deps)), name, name, extra))
    with open(os.path.join(d, "skills", name, "SKILL.md"), "w") as f:
        f.write("---\nname: %s\ndescription: Use when x\n---\nhi\n" % name)
    with open(os.path.join(d, "README.md"), "w") as f:
        f.write("# %s\n" % name)
    return d


def set_version(pkg_dir, version):
    p = os.path.join(pkg_dir, "nodra.toml")
    with open(p) as f:
        t = f.read()
    import re
    with open(p, "w") as f:
        f.write(re.sub(r'(?m)^version = "[^"]*"', 'version = "%s"' % version, t, count=1))


class Env:
    """Context manager: scratch HOME, NODRA_HOME and an empty checkout (NODRA_ROOT) so `core` holds only what a test puts there."""

    def __init__(self):
        self.T = tempfile.mkdtemp(prefix="nodra-t-")
        self.home = os.path.join(self.T, "home")
        self.root = os.path.join(self.T, "root")
        os.makedirs(os.path.join(self.root, "packages"))
        os.makedirs(os.path.join(self.home, ".claude"))
        self.patch = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home, "NODRA_HOME": os.path.join(self.home, ".nodra"),
                                                  "NODRA_ROOT": self.root})

    def __enter__(self):
        self.patch.start()
        return self

    def __exit__(self, *a):
        self.patch.stop()
        shutil.rmtree(self.T, ignore_errors=True)

    @property
    def packages(self):
        return os.path.join(self.root, "packages")

    def skill(self, n):
        return os.path.exists(os.path.join(self.home, ".claude", "skills", n))


def bare_repo(parent, name="src.git", packages=()):
    """A bare git repository whose `main` holds packages/<name> for each (name, version, deps). -> (bare path, work path)."""
    bare, work = os.path.join(parent, name), os.path.join(parent, name + ".work")
    os.makedirs(bare)
    git(bare, "init", "-q", "--bare", "-b", "main")
    os.makedirs(work)
    git(work, "init", "-q", "-b", "main")
    git(work, "remote", "add", "origin", bare)
    for n, v, deps in packages:
        make_pkg(os.path.join(work, "packages"), n, v, deps)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "first")
    git(work, "push", "-q", "origin", "main")
    return bare, work
