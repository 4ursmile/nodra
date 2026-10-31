"""`nodra upgrade [--check]` on a temp git checkout (a clone of a temp bare repository); a copy without git says how to refresh."""
import os
import shutil
import unittest
from unittest import mock

from nodra.cli import gitx
from nodra.core.release import VERSION

from .support import Env, git, run, run_json


class Upgrade(unittest.TestCase):
    def checkout(self, e):
        """<T>/up.git (bare) <- <T>/seed (pushes) ; <T>/root is a clone of it = the app checkout."""
        bare, seed = os.path.join(e.T, "up.git"), os.path.join(e.T, "seed")
        os.makedirs(bare)
        git(bare, "init", "-q", "--bare", "-b", "main")
        os.makedirs(seed)
        git(seed, "init", "-q", "-b", "main")
        git(seed, "remote", "add", "origin", bare)
        open(os.path.join(seed, "a.txt"), "w").write("1")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "one")
        git(seed, "push", "-q", "origin", "main")
        shutil.rmtree(e.root)
        git(e.T, "clone", "-q", bare, e.root)
        return seed

    def push(self, seed, text):
        open(os.path.join(seed, "a.txt"), "w").write(text)
        git(seed, "commit", "-q", "-am", text)
        git(seed, "push", "-q", "origin", "main")

    def test_check_then_upgrade(self):
        with Env() as e:
            seed = self.checkout(e)
            d = run_json("upgrade", "--check")["data"]
            self.assertEqual((d["git"], d["behind"], d["commits"], d["version"]), (True, False, 0, VERSION))
            self.assertEqual(d["current"], d["latest"])
            self.assertEqual(d["current"], git(e.root, "rev-parse", "--short=8", "HEAD"))
            self.push(seed, "2")
            self.push(seed, "3")
            d = run_json("upgrade", "--check")["data"]
            self.assertEqual((d["behind"], d["commits"]), (True, 2))
            self.assertEqual(d["latest"], git(seed, "rev-parse", "--short=8", "HEAD"))
            self.assertIn("nodra upgrade", d["message"])
            self.assertEqual(open(os.path.join(e.root, "a.txt")).read(), "1")                # --check pulls nothing
            d = run_json("upgrade")
            self.assertTrue(d["ok"], d)
            self.assertEqual((d["data"]["updated"], d["data"]["behind"], d["data"]["restarted"]), (True, False, False))
            self.assertEqual(open(os.path.join(e.root, "a.txt")).read(), "3")
            self.assertFalse(run_json("upgrade", "--check")["data"]["behind"])
            self.assertEqual(run_json("upgrade")["data"]["updated"], False)

    def test_upgrade_restarts_a_running_chat(self):
        with Env() as e:
            self.checkout(e)
            self.push(os.path.join(e.T, "seed"), "2")
            from nodra.cli import runs
            runs._save(dict(runs.new_spec("nodra-chat", "nodra-chat", "nodra-chat", [], "", "always"), sup_pid=os.getpid(), beat=__import__("time").time(), status="running"))
            d = run_json("upgrade")
            self.assertTrue(d["data"]["restarted"])
            self.assertIn('"restart"', open(runs._f("nodra-chat", ".ctl")).read())

    def test_no_restart_leaves_the_running_chat_alone(self):
        with Env() as e:
            self.checkout(e)
            self.push(os.path.join(e.T, "seed"), "2")
            from nodra.cli import runs
            runs._save(dict(runs.new_spec("nodra-chat", "nodra-chat", "nodra-chat", [], "", "always"), sup_pid=os.getpid(), beat=__import__("time").time(), status="running"))
            d = run_json("upgrade", "--no-restart")
            self.assertEqual((d["data"]["updated"], d["data"]["restarted"]), (True, False))
            self.assertEqual(open(os.path.join(e.root, "a.txt")).read(), "2")
            self.assertFalse(os.path.exists(runs._f("nodra-chat", ".ctl")))

    def test_diverged_checkout_is_a_clear_error(self):
        with Env() as e:
            seed = self.checkout(e)
            open(os.path.join(e.root, "a.txt"), "w").write("local")
            git(e.root, "commit", "-q", "-am", "local change")
            self.push(seed, "remote change")
            d = run_json("upgrade")
            self.assertFalse(d["ok"])
            self.assertIn("git pull failed", d["error"])

    def test_a_copy_without_git_cannot_update_itself(self):
        with Env() as e:                                                   # root has no .git: a downloaded zip
            d = run_json("upgrade", "--check")
            self.assertTrue(d["ok"])
            self.assertEqual((d["data"]["git"], d["data"]["behind"]), (False, False))
            self.assertIn("zip", d["data"]["message"])
            d = run_json("upgrade")
            self.assertFalse(d["ok"])
            self.assertIn("not a git checkout", d["error"])

    def test_git_program_missing(self):
        with Env() as e:
            self.checkout(e)
            with mock.patch.object(gitx, "available", lambda: False):
                d = run_json("upgrade", "--check")
                self.assertEqual((d["ok"], d["data"]["git"]), (True, False))
                self.assertIn("git is not installed", d["data"]["message"])

    def test_no_upstream_or_unreachable_remote(self):
        with Env() as e:
            self.checkout(e)
            git(e.root, "remote", "set-url", "origin", os.path.join(e.T, "gone.git"))
            d = run_json("upgrade", "--check")
            self.assertTrue(d["ok"])
            self.assertIn("cannot reach", d["data"]["message"])
            self.assertEqual(run("upgrade")[0], 1)


if __name__ == "__main__":
    unittest.main()
