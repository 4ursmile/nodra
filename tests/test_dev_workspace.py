import os
import subprocess
import tempfile
import unittest
from unittest import mock

from nodra.cli import main as cli, publish as pub, ui



def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Workspace(unittest.TestCase):
    def setUp(self):
        t = tempfile.mkdtemp()
        self.bare, self.w = os.path.join(t, "r.git"), os.path.join(t, "work")
        os.makedirs(self.bare); os.makedirs(self.w)
        git("init", "-q", "--bare", "-b", "main", cwd=self.bare)
        git("init", "-q", "-b", "main", cwd=self.w)
        git("remote", "add", "origin", self.bare, cwd=self.w)
        git("config", "user.email", "a@b.c", cwd=self.w); git("config", "user.name", "t", cwd=self.w)
        self._state = ui.INTERACTIVE
        ui.INTERACTIVE = False
        for n in ("one", "two"):
            cli.main(["dev", "init", os.path.join(self.w, "builtin", n), "--type", "skill", "--name", n])
        self.ws = os.path.join(self.w, "builtin")

    def tearDown(self):
        ui.INTERACTIVE = self._state

    def log(self):
        return git("log", "--format=%s", cwd=self.bare).splitlines()

    def test_discover_finds_packages_and_stops_at_a_manifest(self):
        self.assertEqual([os.path.basename(d) for d in pub.discover(self.ws)], ["one", "two"])
        one = os.path.join(self.ws, "one")
        self.assertEqual(pub.discover(one), [one])

    def test_publish_only_one_then_all(self):
        self.assertEqual(cli.main(["dev", "publish", self.ws, "--only", "one"]), 0)
        self.assertEqual(self.log(), ["publish one 0.1.0"])
        cli.main(["dev", "publish", self.ws])
        self.assertEqual(self.log(), ["publish two 0.1.0", "publish one 0.1.0"])      # one commit per publish run (only changed packages named), one push

    def test_unknown_name_is_an_error(self):
        self.assertEqual(cli.main(["dev", "validate", self.ws, "--only", "nope"]), 1)

    def test_a_broken_package_is_reported_and_the_others_still_go_out(self):
        os.remove(os.path.join(self.ws, "two", "skills", "two", "SKILL.md"))
        self.assertEqual(cli.main(["dev", "publish", self.ws]), 1)
        self.assertEqual(self.log(), ["publish one 0.1.0"])


class InitConflicts(unittest.TestCase):
    def setUp(self):
        self.ws = os.path.join(tempfile.mkdtemp(), "builtin")
        self._state = ui.INTERACTIVE
        ui.INTERACTIVE = False
        self.assertEqual(cli.main(["dev", "init", os.path.join(self.ws, "one"), "--name", "one"]), 0)

    def tearDown(self):
        ui.INTERACTIVE = self._state

    def test_nested_inside_a_package_is_refused(self):
        self.assertEqual(cli.main(["dev", "init", os.path.join(self.ws, "one", "inner"), "--name", "inner"]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "one", "inner")))

    def test_above_existing_packages_is_refused(self):
        self.assertEqual(cli.main(["dev", "init", self.ws, "--name", "top"]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "nodra.toml")))

    def test_sub_creates_a_sibling_and_needs_a_name(self):
        self.assertEqual(cli.main(["dev", "init", self.ws, "--sub"]), 1)
        self.assertEqual(cli.main(["dev", "init", self.ws, "--sub", "--name", "two"]), 0)
        self.assertEqual(sorted(os.listdir(self.ws)), ["one", "two"])

    def test_reinit_of_the_same_package_is_not_a_conflict(self):
        self.assertEqual(cli.main(["dev", "init", os.path.join(self.ws, "one"), "--name", "one"]), 0)

    def test_validate_warns_when_a_package_contains_another(self):
        os.makedirs(os.path.join(self.ws, "one", "deep"))
        self.assertEqual(cli.main(["dev", "init", os.path.join(self.ws, "one", "deep"), "--name", "deep", "--force"]), 1)


class SelfUninstall(unittest.TestCase):
    def test_removes_home_and_only_the_path_block(self):
        t = tempfile.mkdtemp()
        rc = os.path.join(t, ".zshrc")
        open(rc, "w").write('export A=1\n\n# >>> nodra\nexport PATH="$HOME/.nodra/bin:$PATH"\n# <<< nodra\nexport B=2\n')
        home = os.path.join(t, "nodra-home")
        os.makedirs(os.path.join(home, "bin"))
        env = {k: os.environ.get(k) for k in ("HOME", "ZDOTDIR", "NODRA_HOME")}
        os.environ.update(HOME=t, ZDOTDIR=t, NODRA_HOME=home)
        try:
            self.assertEqual(cli.main(["self-uninstall", "--yes"]), 0)
        finally:
            for k, v in env.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertFalse(os.path.exists(home))
        self.assertEqual(open(rc).read().split(), ["export", "A=1", "export", "B=2"])


class Monorepo(unittest.TestCase):
    def setUp(self):
        t = tempfile.mkdtemp()
        self.t, self.bare = t, os.path.join(t, "r.git")
        self.w = os.path.join(t, "mono")
        os.makedirs(self.bare)
        git("init", "-q", "--bare", "-b", "main", cwd=self.bare)
        self._state = ui.INTERACTIVE
        ui.INTERACTIVE = False
        self.assertEqual(cli.main(["dev", "init", self.w, "--mono", "--packages", "guide,tools:mcp", "--remote", self.bare]), 0)
        git("config", "user.email", "a@b.c", cwd=self.w); git("config", "user.name", "t", cwd=self.w)

    def tearDown(self):
        ui.INTERACTIVE = self._state

    def test_mono_init_creates_one_repo_and_no_git_tables(self):
        self.assertEqual(sorted(n for n in os.listdir(self.w) if not n.startswith(".")), ["guide", "tools"])
        self.assertFalse(os.path.exists(os.path.join(self.w, "guide", ".git")))
        self.assertEqual(git("remote", "get-url", "origin", cwd=self.w), self.bare)
        for n in ("guide", "tools"):
            self.assertNotIn("[git]", open(os.path.join(self.w, n, "nodra.toml")).read())

    def test_mono_init_keeps_existing_packages(self):
        other = os.path.join(self.t, "r2.git"); os.makedirs(other); git("init", "-q", "--bare", "-b", "main", cwd=other)
        self.assertEqual(cli.main(["dev", "init", self.w, "--mono", "--packages", "extra", "--remote", other]), 0)
        self.assertEqual(sorted(n for n in os.listdir(self.w) if not n.startswith(".")), ["extra", "guide", "tools"])
        self.assertEqual(git("remote", "get-url", "origin", cwd=self.w), other)
        self.assertTrue(os.path.exists(os.path.join(self.w, "guide", "skills", "guide", "SKILL.md")))

    def test_doctor_syncs_pyproject_and_flags_duplicates(self):
        py = os.path.join(self.w, "guide", "pyproject.toml")
        open(py, "w").write('[project]\nname = "guide"\nversion = "9.9.9"\n')
        self.assertEqual(cli.main(["dev", "doctor", self.w, "--check"]), 1)             # out of date, nothing written
        self.assertIn("9.9.9", open(py).read())
        self.assertEqual(cli.main(["dev", "doctor", self.w]), 0)
        self.assertIn('version = "0.1.0"', open(py).read())
        self.assertEqual(cli.main(["dev", "doctor", self.w, "--check"]), 0)
        os.makedirs(os.path.join(self.w, "copy"))
        open(os.path.join(self.w, "copy", "nodra.toml"), "w").write(open(os.path.join(self.w, "guide", "nodra.toml")).read())
        self.assertEqual(cli.main(["dev", "doctor", self.w]), 1)                        # the same package name twice

    def test_tree_runs_and_reports(self):
        self.assertEqual(cli.main(["dev", "tree", self.w]), 0)

    def _nest(self):
        inner = os.path.join(self.w, "tools")
        git("init", "-q", "-b", "main", cwd=inner)
        git("config", "user.email", "a@b.c", cwd=inner); git("config", "user.name", "t", cwd=inner)
        return inner

    def test_tree_solve_merge_moves_dot_git_away_and_publishes(self):
        inner = self._nest()
        self.assertEqual(cli.main(["dev", "doctor", self.w]), 1)                       # a nested repo is a decision, not an auto-fix
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"NODRA_HOME": home}):
            self.assertEqual(cli.main(["dev", "tree-solve", self.w, "--nested", "merge"]), 0)
        self.assertFalse(os.path.exists(os.path.join(inner, ".git")))
        self.assertTrue(any(n.startswith("git-tools") for n in os.listdir(os.path.join(home, "backups"))))
        self.assertEqual(cli.main(["dev", "publish", self.w]), 0)
        self.assertEqual(git("log", "--format=%s", cwd=self.bare).splitlines(), ["publish 2 packages"])      # ONE commit for the whole monorepo
        body = git("log", "-1", "--format=%b", cwd=self.bare)
        self.assertIn("- guide 0.1.0", body); self.assertIn("- tools 0.1.0", body)

    def test_publish_twice_makes_no_second_commit(self):
        self.assertEqual(cli.main(["dev", "publish", self.w]), 0)
        head = git("rev-parse", "main", cwd=self.bare)
        self.assertEqual(cli.main(["dev", "publish", self.w]), 0)                      # nothing changed: no new commit, same head
        self.assertEqual(git("rev-list", "--count", "main", cwd=self.bare), "1")
        self.assertEqual(git("rev-parse", "main", cwd=self.bare), head)

    def test_publish_json_lists_what_went_out(self):
        from .support import run_json
        d = run_json("dev", "publish", self.w)
        self.assertTrue(d["ok"], d)
        self.assertEqual(sorted(p["package"] for p in d["data"]["published"]), ["guide", "tools"])

    def test_tree_solve_keep_leaves_the_inner_repo_and_outer_ignores_it(self):
        inner = self._nest()
        self.assertEqual(cli.main(["dev", "tree-solve", self.w, "--nested", "keep"]), 0)
        self.assertTrue(os.path.isdir(os.path.join(inner, ".git")))
        self.assertIn("tools", git("status", "--porcelain", "--ignored", cwd=self.w))
        self.assertNotIn("?? tools/", git("status", "--porcelain", cwd=self.w))

    def test_one_broken_package_does_not_stop_the_others(self):
        os.remove(os.path.join(self.w, "tools", "skills", "tools", "SKILL.md")) if os.path.exists(os.path.join(self.w, "tools", "skills")) else \
            open(os.path.join(self.w, "tools", "nodra.toml"), "a").write("\n[[skills]]\nname = \"x\"\npath = \"nope\"\n")
        self.assertEqual(cli.main(["dev", "publish", self.w]), 1)                      # reports the failure...
        self.assertEqual(git("log", "--format=%s", cwd=self.bare).splitlines(), ["publish guide 0.1.0"])   # ...but guide went out


class WizardAdopt(unittest.TestCase):
    def test_mono_adopts_existing_subfolders(self):
        import argparse, tempfile
        from nodra.cli import main as m
        with tempfile.TemporaryDirectory() as t:
            for n in ("alpha", "beta"):
                os.makedirs(os.path.join(t, n))
            ns = argparse.Namespace(path=t, name=None, type="skill", description=None, sub=False, mono=True, packages=[],
                                    adopt=["alpha"], remote=None, branch="main", wizard=False, force=False)
            m.dev_init(ns)
            self.assertTrue(os.path.exists(os.path.join(t, "alpha", "nodra.toml")))
            self.assertFalse(os.path.exists(os.path.join(t, "beta", "nodra.toml")))

    def test_wizard_needs_terminal(self):
        import argparse
        from nodra.cli import main as m
        with self.assertRaises(ValueError):
            m._init_wizard(argparse.Namespace(path=".", type="skill", description=None, remote=None, branch=None))


if __name__ == "__main__":
    unittest.main()
