"""`nodra run` supervisor (background/foreground, restart, schedule, controls) and `nodra chat` (a service run in place)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from nodra.cli import runs
from nodra.core.errors import NodraError
from nodra.core.schedule import parse_schedule

BOT = '''import os, sys, time
n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
for i in range(n):
    print("tick", i, os.environ.get("NODRA_RUN_NAME"), flush=True)
    time.sleep(0.1)
sys.exit(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
'''


def fake_bot(home, name="tick-bot"):
    pkg = os.path.join(home, "packages", name)
    os.makedirs(os.path.join(pkg, "bot"))
    os.makedirs(os.path.join(home, "bots", name))
    with open(os.path.join(pkg, "nodra.toml"), "w") as f:
        f.write('[package]\nname = "%s"\nversion = "1.0.0"\ntype = "bot"\ndescription = "t"\n[bot]\nrun = "bot/run.py"\n' % name)
    with open(os.path.join(pkg, "bot", "run.py"), "w") as f:
        f.write(BOT)
    with open(os.path.join(home, "state.json"), "w") as f:
        json.dump({"packages": {name: {"path": pkg, "components": ["bot:" + name], "version": "1.0.0", "bot_home": os.path.join(home, "bots", name)}}}, f)


def until(fn, secs=10):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    return fn()


class Home(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        p = mock.patch.dict(os.environ, {"NODRA_HOME": self.home})
        p.start()
        self.addCleanup(p.stop)
        fake_bot(self.home)

    def spec(self, rid="t", args=(), schedule="", restart="no"):
        r = runs.new_spec(rid, rid, "tick-bot", list(args), schedule, restart, False)
        runs._save(r)
        return r

    def supervise(self, rid):
        s = runs.Supervisor(rid)
        t = threading.Thread(target=s.run, daemon=True)
        t.start()
        self.addCleanup(lambda: (setattr(s, "quit", True), t.join(15)))
        return s, t


class Supervise(Home):
    def test_foreground_exit_code_and_log(self):
        self.spec("fg", ["3", "4"])
        with mock.patch.object(sys, "stdout", mock.MagicMock()):
            code = runs.Supervisor("fg", fg=True).run()
        self.assertEqual(code, 4)
        r = runs.load("fg")
        self.assertEqual((r["status"], r["runs"], r["last_exit"], runs.alive(r)), ("failed", 1, 4, False))
        log = "\n".join(runs.tail("fg", 50))
        self.assertIn("tick 2 fg", log)
        self.assertIn("exited with code 4", log)

    def test_on_failure_restarts_with_backoff(self):
        self.spec("bad", ["1", "3"], restart="on-failure")
        with mock.patch.object(runs, "BACKOFF_MIN", 0.2):
            s, t = self.supervise("bad")
            until(lambda: (runs.load("bad") or {}).get("runs", 0) >= 3 or s.r.get("runs", 0) >= 3)
        self.assertGreaterEqual(s.r["runs"], 3)
        self.assertGreater(s.backoff, 0.2)                      # doubled after each failure

    def test_interval_schedule_runs_again(self):
        self.spec("sch", ["1"], schedule="10")
        with mock.patch.object(runs, "next_delay", lambda *a: 0.3):
            s, t = self.supervise("sch")
            until(lambda: s.r.get("runs", 0) >= 2)
        self.assertGreaterEqual(s.r["runs"], 2)
        self.assertEqual(s.r["last_exit"], 0)

    def test_controls_stop_start_set_restart_quit(self):
        self.spec("c", ["100000"], restart="on-failure")
        s, t = self.supervise("c")
        self.assertTrue(until(lambda: s.r.get("status") == "running"))
        runs.control("c", "stop")
        self.assertTrue(until(lambda: s.r.get("status") == "stopped" and s.child is None))
        self.assertTrue(s.paused)
        runs.control("c", "set", args=["100000", "0"], restart="always", schedule="")
        runs.control("c", "start")
        self.assertTrue(until(lambda: s.r.get("status") == "running" and s.r.get("runs") == 2))
        self.assertEqual((s.r["args"], s.r["restart"]), (["100000", "0"], "always"))
        pid = s.child.pid
        runs.control("c", "restart")
        self.assertTrue(until(lambda: s.child is not None and s.child.pid != pid and s.r.get("runs") == 3))
        runs.control("c", "set", schedule="bad")                # refused, noted in the log, nothing changes
        runs.control("c", "quit")
        t.join(15)
        self.assertFalse(t.is_alive())
        r = runs.load("c")
        self.assertFalse(runs.alive(r))
        self.assertEqual(r["schedule"], "")
        self.assertIn("setting refused", "\n".join(runs.tail("c", 80)))

    def test_set_restart_no_cancels_a_pending_restart(self):
        self.spec("p", ["1", "2"], restart="on-failure")
        with mock.patch.object(runs, "BACKOFF_MIN", 30):
            s, t = self.supervise("p")
            self.assertTrue(until(lambda: s.r.get("status") == "waiting"))
            runs.control("p", "set", restart="no")
            self.assertTrue(until(lambda: s.r.get("status") == "failed"))
        self.assertIsNone(s.due)

class Commands(Home):
    """The real CLI: a detached supervisor, list, logs, set, stop, rm."""
    def cli(self, *argv):
        from nodra.cli import main
        from .support import KeepUi
        with KeepUi():
            return main.main(list(argv))

    def test_background_start_list_stop_rm(self):
        self.assertEqual(self.cli("run", "tick-bot", "--name", "bg", "--", "100000"), 0)
        r = runs.load("bg")
        self.assertTrue(runs.alive(r))
        self.assertEqual(runs.status_of(r), "running")
        self.assertEqual(r["restart"], "on-failure")
        self.assertEqual(self.cli("run", "tick-bot", "--name", "bg"), 1)      # the same name twice
        self.assertEqual(self.cli("run", "set", "bg", "--schedule", "1h"), 0)
        self.assertTrue(until(lambda: runs.load("bg").get("schedule") == "1h"))
        self.assertEqual(self.cli("run", "list", "--json"), 0)
        self.assertEqual(self.cli("run", "stop", "bg"), 0)
        r = runs.load("bg")
        self.assertFalse(runs.alive(r))
        self.assertEqual(runs.status_of(r), "stopped")
        self.assertEqual(self.cli("run", "rm", "bg"), 0)
        self.assertIsNone(runs.load("bg"))

    def test_a_bot_that_ends_at_once_is_reported(self):
        with self.assertRaises(SystemExit) as e:
            self.cli("run", "tick-bot", "--name", "quick", "--restart", "no", "--", "1", "5")
        self.assertEqual(e.exception.code, 1)
        r = runs.load("quick")
        self.assertEqual((runs.status_of(r), r["last_exit"]), ("failed", 5))


class Schedule(unittest.TestCase):
    def test_shorthand_and_limits(self):
        self.assertEqual(parse_schedule("5m"), ("every", 300))
        self.assertEqual(parse_schedule("every 2h"), ("every", 7200))
        self.assertEqual(parse_schedule("2d", 10, 7 * 86400), ("every", 172800))
        with self.assertRaises(ValueError):
            parse_schedule("2d")                                # without a wider limit a schedule stays within a day
        self.assertEqual(runs.check_schedule(""), "")
        with self.assertRaises(ValueError):
            runs.check_schedule("1s")


class ServiceType(unittest.TestCase):
    """type = "service": same runner as a bot, own home folder and NODRA_SERVICE_* variables, restart always by default."""
    def setUp(self):
        self.home = tempfile.mkdtemp()
        p = mock.patch.dict(os.environ, {"NODRA_HOME": self.home})
        p.start()
        self.addCleanup(p.stop)

    def test_manifest_lint_and_template(self):
        from nodra.core import manifest as M, templates
        m = M.parse('[package]\nname="web-svc"\nversion="1.0.0"\ntype="service"\n[service]\nrun="svc.py"\nrestart="bogus"\n')
        self.assertEqual((M.runnable(m)["run"], M.runnable(m)["restart"]), ("svc.py", "always"))
        self.assertEqual(M.parse('[package]\nname="b"\nversion="1.0.0"\ntype="bot"\n[bot]\nrun="x.py"\n')["bot"]["restart"], "")
        d = tempfile.mkdtemp()
        errs, _ = M.lint(M.parse('[package]\nname="s"\nversion="1.0.0"\ntype="service"\n'), d)
        self.assertTrue(any("[service] run" in e for e in errs))
        text, files, execs = templates.render("service", "web-svc")
        for rel, body in files.items():
            os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
            open(os.path.join(d, rel), "w").write(body)
        m = M.parse(text)
        self.assertEqual(M.lint(m, d)[0], [])
        self.assertEqual(m["service"]["env"][0]["default"], "8080")

    def test_page_service_address_is_shown_and_opened_when_already_running(self):
        from nodra.core import manifest as M
        from nodra.cli import ui
        m = M.parse('[package]\nname="pg"\nversion="1.0.0"\ntype="service"\n[service]\nrun="s.py"\nunique=true\nurl_file="ui/url.txt"\n')
        self.assertEqual(M.runnable(m)["url_file"], "ui/url.txt")
        for bad in ("../x", "/etc/passwd", "a/../../b"):
            m["service"]["url_file"] = M._url_file(bad)
            self.assertEqual(m["service"]["url_file"], "")
        m["service"]["url_file"] = "ui/url.txt"
        self.assertFalse(runs.show_link(m))                                             # no address file yet
        os.makedirs(os.path.join(self.home, "ui"))
        with open(os.path.join(self.home, "ui", "url.txt"), "w") as f:
            f.write("http://127.0.0.1:8765/?t=KEY\n")
        with mock.patch.object(ui, "INTERACTIVE", True), mock.patch.object(runs, "open_url", return_value=True) as op:
            self.assertTrue(runs.show_link(m))
            op.assert_called_once_with("http://127.0.0.1:8765/?t=KEY")
        with mock.patch.object(ui, "INTERACTIVE", False), mock.patch.object(runs, "open_url") as op:
            self.assertTrue(runs.show_link(m))                                          # not a terminal: shown, not opened
            op.assert_not_called()

    def test_installed_service_runs_with_its_own_env(self):
        from nodra.cli import installer
        from nodra.core import manifest as M
        pkg = os.path.join(self.home, "packages", "web-svc")
        os.makedirs(pkg)
        open(os.path.join(pkg, "nodra.toml"), "w").write(
            '[package]\nname="web-svc"\nversion="1.0.0"\ntype="service"\n[service]\nrun="run.py"\n[[service.env]]\nname="PORT"\ndefault="9000"\n')
        open(os.path.join(pkg, "run.py"), "w").write("print('up')\n")
        m = M.parse(open(os.path.join(pkg, "nodra.toml")).read())
        rec = {"path": pkg, "version": "1.0.0"}
        with mock.patch.object(installer.integrations, "detected", return_value=[]):
            installer._activate(rec, m, pkg, [], True, "web-svc")
        self.assertEqual(rec["components"], ["service:web-svc"])
        self.assertEqual(rec["bot_home"], os.path.join(self.home, "services", "web-svc"))
        self.assertIn("PORT=9000", open(os.path.join(rec["bot_home"], ".env")).read())
        with open(os.path.join(self.home, "state.json"), "w") as f:
            json.dump({"packages": {"web-svc": rec}}, f)
        self.assertIn("web-svc", installer.bots())
        cmd, shell, cwd, env = installer.bot_command("web-svc", ["--x"])
        self.assertEqual((cwd, env["PORT"], env["NODRA_SERVICE"], env["NODRA_SERVICE_HOME"]), (rec["bot_home"], "9000", "web-svc", rec["bot_home"]))
        self.assertEqual(cmd[-1], "--x")
        a = mock.Mock(name=None, fg=True, schedule=None, restart=None)
        a.name = None
        with mock.patch.object(runs, "launch", side_effect=lambda r, fg=False: r) as launch:
            runs.start("web-svc", [], a)
        self.assertEqual(launch.call_args[0][0]["restart"], "no")       # --fg: no restart
        a.fg = False
        with mock.patch.object(runs, "launch", side_effect=lambda r, fg=False: r) as launch:
            runs.start("web-svc", [], a)
        self.assertEqual(launch.call_args[0][0]["restart"], "always")   # the [service] default

    def test_unique_allows_one_run_at_a_time(self):
        from nodra.core import manifest as M
        self.assertIs(M.parse('[package]\nname="s"\nversion="1.0.0"\ntype="service"\n[service]\nrun="r.py"\nunique=true\n')["service"]["unique"], True)
        self.assertIs(M.parse('[package]\nname="s"\nversion="1.0.0"\ntype="service"\n[service]\nrun="r.py"\nunique="yes"\n')["service"]["unique"], False)
        pkg = os.path.join(self.home, "packages", "one-svc")
        os.makedirs(pkg)
        open(os.path.join(pkg, "nodra.toml"), "w").write('[package]\nname="one-svc"\nversion="1.0.0"\ntype="service"\n[service]\nrun="run.py"\nunique=true\n')
        open(os.path.join(pkg, "run.py"), "w").write("print('up')\n")
        with open(os.path.join(self.home, "state.json"), "w") as f:
            json.dump({"packages": {"one-svc": {"path": pkg, "version": "1.0.0", "components": ["service:one-svc"],
                                                 "bot_home": os.path.join(self.home, "services", "one-svc")}}}, f)
        first = runs.new_spec("one-svc", "one-svc", "one-svc", [], "", "always", False)
        runs._save(dict(first, sup_pid=os.getpid(), beat=time.time(), status="running"))
        a = mock.Mock(fg=False, schedule=None, restart=None)
        a.name = "second"
        with mock.patch.object(runs, "launch", side_effect=lambda r, fg=False: 0) as launch:
            with self.assertRaises(NodraError) as e:
                runs.start("one-svc", [], a)
            self.assertIn("only one run", str(e.exception))
            runs._save(dict(first, sup_pid=None, beat=0, status="stopped"))      # the first one ended: a second name is fine now
            runs.start("one-svc", [], a)
        self.assertEqual(launch.call_count, 1)


class VenvChoice(Home):
    """`nodra run --venv/--python`: replaces the interpreter, remembered per package, survives the supervisor's rebuild of the command."""

    def fake_venv(self, name="ve"):
        d = os.path.join(tempfile.mkdtemp(), name)
        os.makedirs(os.path.join(d, "Scripts" if os.name == "nt" else "bin"))
        py = os.path.join(d, "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")
        os.symlink(sys.executable, py)
        return d, py

    def cmd(self):
        from nodra.cli import installer
        return installer.bot_command("tick-bot")

    def test_order_flag_remembered_autodetect_default(self):
        from nodra.cli import installer
        cmd, _, _, env = self.cmd()
        self.assertEqual(cmd[0], sys.executable)                                  # nothing set: nodra's python
        auto, autopy = self.fake_venv()
        os.rename(auto, os.path.join(self.home, "bots", "tick-bot", ".venv"))
        cmd, _, _, env = self.cmd()
        self.assertIn(os.path.join(".venv"), cmd[0])                               # auto-detected in the bot home
        d, py = self.fake_venv()
        installer.remember_venv("tick-bot", installer.check_venv(venv=d))
        cmd, _, _, env = self.cmd()
        self.assertEqual(cmd[0], py)                                              # remembered beats auto-detect
        self.assertEqual(env["VIRTUAL_ENV"], d)
        self.assertTrue(env["PATH"].startswith(os.path.dirname(py) + os.pathsep))
        d2, py2 = self.fake_venv("other")
        cmd, *_ = installer.bot_command("tick-bot", override=installer.check_venv(venv=d2))
        self.assertEqual(cmd[0], py2)                                             # explicit beats remembered
        installer.remember_venv("tick-bot", None)
        self.assertIn(".venv", self.cmd()[0][0])

    def test_bad_paths_are_errors(self):
        from nodra.cli import installer
        with self.assertRaises(NodraError):
            installer.check_venv(venv=os.path.join(self.home, "nope"))
        with self.assertRaises(NodraError):
            installer.check_venv(venv=self.home)                                   # a folder without a python
        with self.assertRaises(NodraError):
            installer.check_venv(python=os.path.join(self.home, "nopython"))

    def test_cli_remembers_and_list_shows_it(self):
        d, py = self.fake_venv("myenv")
        self.assertEqual(Commands.cli(self, "run", "tick-bot", "--name", "v1", "--venv", d, "--", "100000"), 0)
        self.addCleanup(lambda: Commands.cli(self, "run", "stop", "--all"))
        self.assertEqual(self.cmd()[0][0], py)
        self.assertEqual(runs.venv_of(runs.load("v1"))["venv"], d)
        self.assertEqual(Commands.cli(self, "run", "list", "--json"), 0)
        self.assertEqual(Commands.cli(self, "run", "stop", "v1"), 0)
        self.assertEqual(Commands.cli(self, "run", "tick-bot", "--name", "v1", "--venv", "default", "--", "100000"), 0)
        self.assertEqual(self.cmd()[0][0], sys.executable)
        self.assertEqual(Commands.cli(self, "run", "tick-bot", "--name", "v2", "--venv", os.path.join(self.home, "missing")), 1)


class ChatInPlace(unittest.TestCase):
    """`nodra chat`: <root>/chat/nodra.toml runs where it is, with NODRA_HOME / NODRA_ROOT / NODRA_CLI set and a raw checkout importable."""
    SERVER = ('''import json, os, subprocess, sys, time
home = os.environ["NODRA_HOME"]
os.makedirs(os.path.join(home, "ui"), exist_ok=True)
cli = json.loads(os.environ["NODRA_CLI"])
r = subprocess.run(cli + ["--version"], capture_output=True, text=True, env=dict(os.environ))     # the raw checkout must be importable from here
open(os.path.join(home, "ui", "url.txt"), "w").write("http://127.0.0.1:8765/?t=K\\n")
open(os.path.join(home, "ui", "seen.json"), "w").write(json.dumps({"root": os.environ["NODRA_ROOT"], "cli": cli, "version": r.stdout.strip(), "rc": r.returncode}))
time.sleep(60)
''')

    def setUp(self):
        from .support import Env
        self.env = Env()
        self.env.__enter__()
        self.addCleanup(self.env.__exit__)
        chat = os.path.join(self.env.root, "chat")
        os.makedirs(chat)
        with open(os.path.join(chat, "nodra.toml"), "w") as f:
            f.write('[package]\nname="nodra-chat"\nversion="1.0.0"\ntype="service"\n[service]\nrun="server.py"\nunique=true\nurl_file="ui/url.txt"\n')
        with open(os.path.join(chat, "server.py"), "w") as f:
            f.write(self.SERVER)
        # the checkout must be importable by the supervisor and the service: put a copy of the package next to the fake chat
        import shutil
        real = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shutil.copytree(os.path.join(real, "nodra"), os.path.join(self.env.root, "nodra"), ignore=shutil.ignore_patterns("__pycache__"))
        self.root_py = os.environ.get("PYTHONPATH")
        os.environ.pop("PYTHONPATH", None)
        self.addCleanup(lambda: self.root_py and os.environ.__setitem__("PYTHONPATH", self.root_py))

    def test_start_status_restart_stop(self):
        from .support import run, run_json
        d = run_json("chat", "status")
        self.assertFalse(d["data"]["running"])
        self.assertEqual(run("chat")[0], 0)
        self.addCleanup(lambda: run("chat", "stop"))
        st = until(lambda: (lambda x: x if x["data"]["running"] and x["data"]["url"] else None)(run_json("chat", "status")))
        self.assertTrue(st["data"]["running"])
        self.assertEqual(st["data"]["url"], "http://127.0.0.1:8765/?t=K")
        self.assertEqual(st["data"]["name"], "nodra-chat")
        seen = until(lambda: json.load(open(os.path.join(self.env.home, ".nodra", "ui", "seen.json"))) if os.path.exists(os.path.join(self.env.home, ".nodra", "ui", "seen.json")) else None)
        self.assertEqual(seen["root"], self.env.root)
        self.assertEqual(seen["cli"][1:], ["-m", "nodra.cli"])
        self.assertEqual((seen["rc"], seen["version"]), (0, "nodra 1.0.0"))
        self.assertEqual(run("chat")[0], 0)                                   # already running: says so, changes nothing
        pid = st["data"]["pid"]
        self.assertEqual(run("chat", "restart")[0], 0)
        st2 = until(lambda: (lambda x: x if x["data"]["running"] and x["data"]["pid"] not in (None, pid) else None)(run_json("chat", "status")))
        self.assertNotEqual(st2["data"]["pid"], pid)
        self.assertEqual(run("chat", "stop")[0], 0)
        self.assertFalse(run_json("chat", "status")["data"]["running"])
        self.assertTrue(any(r["bot"] == "nodra-chat" and r["inplace"].endswith("chat") for r in runs.all_runs()))

    def test_missing_chat_folder_is_an_error(self):
        import shutil
        from .support import run_json
        shutil.rmtree(os.path.join(self.env.root, "chat"))
        d = run_json("chat", "start")
        self.assertFalse(d["ok"])
        self.assertIn("no chat", d["error"])


if __name__ == "__main__":
    unittest.main()
