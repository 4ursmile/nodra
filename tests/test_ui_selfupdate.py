"""nodra-chat auto update: idle gating, one try per remote version, postponed restarts, package updates, prefs and the build fingerprint.
The CLI is replaced by a recorder; nothing is pulled and nothing restarts for real."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "chat", "ui"))
from nodraui import chat, nodra as A, selfupdate as SU, store, term  # noqa: E402


class FakeCli:
    def __init__(self, behind=True, latest="bbbb", fail_pull=False, packages=()):
        self.calls, self.behind, self.latest, self.fail_pull, self.packages = [], behind, latest, fail_pull, list(packages)

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if args == ["upgrade", "--check"]:
            return {"ok": True, "data": {"git": True, "behind": self.behind, "current": "aaaa", "latest": self.latest, "message": "m"}}
        if args == ["upgrade", "--no-restart"]:
            if self.fail_pull:
                raise A.CliError("git pull failed")
            return {"ok": True, "data": {"updated": True, "current": self.latest, "message": "updated"}}
        if args == ["update", "--check"]:
            return {"ok": True, "data": {"updates": [{"name": n, "installed": "1.0.0", "available": "1.1.0", "source": "core"} for n in self.packages]}}
        if args == ["update"]:
            return {"ok": True, "data": {"updated": [{"name": n} for n in self.packages]}}
        raise AssertionError(args)


class SelfUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"NODRA_HOME": self.tmp, "HOME": self.tmp})
        self.env.start()
        self.saved = dict(SU.state)
        SU.state.update(checked=0.0, behind=False, latest="", failed="", stage="", waiting="", pending_restart=False, packages=[])
        self.restarts = []
        SU._ctl.update(restart=lambda: self.restarts.append(1), engine=None)
        self.sleep = mock.patch.object(SU.time, "sleep", lambda s: None)
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.env.stop()
        SU.state.clear()
        SU.state.update(self.saved)
        with chat.plock:
            chat.runs.pop("busy-test", None)

    def run_with(self, cli):
        return mock.patch.object(A, "run", cli)

    def test_check_reads_upgrade_and_packages(self):
        cli = FakeCli(packages=["alpha"])
        with self.run_with(cli):
            self.assertTrue(SU.check())
        self.assertEqual(SU.state["latest"], "bbbb")
        self.assertEqual([p["name"] for p in SU.state["packages"]], ["alpha"])
        self.assertEqual(cli.calls, [["upgrade", "--check"], ["update", "--check"]])

    def test_apply_pulls_without_cli_restart_then_restarts_once(self):
        cli = FakeCli()
        with self.run_with(cli):
            SU.check(packages=False)
            self.assertTrue(SU.apply())
        self.assertIn(["upgrade", "--no-restart"], cli.calls)
        self.assertEqual(self.restarts, [1])
        self.assertFalse(SU.state["behind"])

    def test_busy_chat_blocks_the_update(self):
        class R:
            done = False
        with chat.plock:
            chat.runs["busy-test"] = R()
        cli = FakeCli()
        with self.run_with(cli):
            SU.check(packages=False)
            self.assertFalse(SU.apply())
        self.assertEqual(SU.state["waiting"], "a chat is answering")
        self.assertNotIn(["upgrade", "--no-restart"], cli.calls)
        self.assertEqual(self.restarts, [])

    def test_restart_is_postponed_when_work_starts_during_the_pull(self):
        class Engine:
            running = 0
        eng = Engine()
        SU._ctl["engine"] = eng
        cli = FakeCli()

        def run(args, **kw):
            out = cli(args, **kw)
            if args == ["upgrade", "--no-restart"]:
                eng.running = 1                                  # a work run starts while git pulls
            return out
        with self.run_with(run):
            SU.check(packages=False)
            self.assertFalse(SU.apply())
        self.assertTrue(SU.state["pending_restart"])
        self.assertEqual(self.restarts, [])
        eng.running = 0
        self.assertTrue(SU._restart_when_idle())
        self.assertEqual(self.restarts, [1])

    def test_failed_pull_is_not_retried_until_the_remote_moves(self):
        cli = FakeCli(fail_pull=True)
        with self.run_with(cli):
            SU.check(packages=False)
            self.assertFalse(SU.apply())
            self.assertEqual(SU.state["failed"], "bbbb")
            self.assertEqual(SU.state["stage"], "error")
            SU.check(packages=False)                             # same remote commit: still marked failed
            self.assertEqual(SU.state["failed"], "bbbb")
            cli.latest = "cccc"
            SU.check(packages=False)                             # a newer commit: try again
            self.assertEqual(SU.state["failed"], "")

    def test_install_terminal_counts_as_busy_but_chat_shell_does_not(self):
        class T:
            code, shell = None, True
        with term.lock:
            term.terms["t-shell"] = T()
        try:
            self.assertEqual(SU.busy(), "")
            T.shell = False
            self.assertEqual(SU.busy(), "an install is running")
        finally:
            with term.lock:
                term.terms.pop("t-shell", None)

    def test_update_packages_refreshes_the_catalogue(self):
        cli = FakeCli(packages=["alpha"])
        with self.run_with(cli), mock.patch.object(A, "invalidate") as inv:
            SU.state["packages"] = [{"name": "alpha"}]
            self.assertTrue(SU.update_packages())
        self.assertIn(["update"], cli.calls)
        inv.assert_called_once()
        self.assertEqual(SU.state["packages"], [])

    def test_prefs(self):
        self.assertEqual(store.prefs()["auto_update"], "on")
        self.assertFalse(store.prefs()["auto_update_packages"])
        store.save_prefs({"auto_update": "notify", "auto_update_packages": True})
        self.assertEqual(SU.status()["mode"], "notify")
        self.assertTrue(SU.status()["auto_packages"])
        with self.assertRaises(ValueError):
            store.save_prefs({"auto_update": "sometimes"})

    def test_build_id_follows_the_code(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "static"))
        f = os.path.join(d, "static", "app.js")
        with open(f, "w") as fh:
            fh.write("a")
        one = SU.build_id(d)
        self.assertEqual(one, SU.build_id(d))
        with open(f, "w") as fh:
            fh.write("ab")
        os.utime(f, (time.time() + 5, time.time() + 5))
        self.assertNotEqual(one, SU.build_id(d))
        self.assertTrue(SU.state["build"])


if __name__ == "__main__":
    unittest.main()
