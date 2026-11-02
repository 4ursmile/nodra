"""`nodra work`: the chat's Works engine from a terminal (nodra/cli/workcmd.py -> chat/ui/server.py --works)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cli(home, *argv, cwd=None):
    env = dict(os.environ, NODRA_HOME=home, PYTHONPATH=ROOT, NODRA_ROOT=ROOT)
    env.pop("NODRA_JSON", None)
    return subprocess.run([sys.executable, "-m", "nodra.cli"] + list(argv), cwd=cwd or ROOT, env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=120)


class WorkCommand(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_list_import_and_run_from_the_terminal(self):
        p = cli(self.home, "--json", "work", "list")
        doc = json.loads(p.stdout)
        self.assertTrue(doc["ok"], p.stdout + p.stderr)
        self.assertEqual(doc["data"]["works"], [])
        here = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, here, True)
        work = {"title": "Steps", "nodes": [{"id": "a", "type": "start.manual", "x": 0, "y": 0, "config": {"inputs": "day"}},
                                            {"id": "p", "type": "code.python", "x": 1, "y": 0,
                                             "config": {"code": "# %% one\nn = 2\n# %% two\nresult['n'] = n * 3\nresult['day'] = data.get('day')\n"}},
                                            {"id": "o", "type": "flow.output", "x": 2, "y": 0, "config": {}}],
                "edges": [{"from": "a", "to": "p"}, {"from": "p", "to": "o"}]}
        with open(os.path.join(here, "steps.work.json"), "w") as f:
            json.dump(work, f)
        p = cli(self.home, "work", "import", "steps.work.json", cwd=here)              # a relative path is read from where the command is typed
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        works = json.loads(cli(self.home, "--json", "work", "list").stdout)["data"]["works"]
        self.assertEqual([w["title"] for w in works], ["Steps"])
        self.assertFalse(works[0]["enabled"])
        p = cli(self.home, "work", "run", "Steps", "--input", "day=2026-11-02", "-q")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('"n": 6', p.stdout)
        self.assertIn("2026-11-02", p.stdout)

    def test_lib_prints_the_vault_folder(self):
        p = cli(self.home, "work", "lib")
        self.assertEqual(p.returncode, 0, p.stderr)
        lib = p.stdout.strip().splitlines()[-1]
        self.assertTrue(os.path.isfile(os.path.join(lib, "nodra_vault", "__init__.py")))
        self.assertTrue(os.path.isfile(os.path.join(lib, "nodra_data", "__init__.py")))

    def test_serve_bg_is_a_separate_inplace_run(self):
        from nodra.cli import workcmd
        with mock.patch.dict(os.environ, {"NODRA_HOME": self.home}), mock.patch.object(workcmd.runs, "start_inplace", return_value=0) as st:
            self.assertEqual(workcmd._serve_bg(["serve", "--bg", "--hooks", "9001"]), 0)
        rid, bot, folder = st.call_args[0]
        self.assertEqual((rid, bot), ("nodra-works", "nodra-chat"))
        self.assertEqual(folder, os.path.join(ROOT, "chat"))
        self.assertEqual(st.call_args[1], {"args": ["--works", "serve", "--hooks", "9001"], "restart": "always"})


if __name__ == "__main__":
    unittest.main()
