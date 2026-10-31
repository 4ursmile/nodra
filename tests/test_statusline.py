"""`nodra statusline`: install keeps the previous status line and remove restores it; the bridge keeps rate_limits for the chat, runs the
previous command with the same input, prints a default otherwise, and never fails. Temp HOME / NODRA_HOME, fake ~/.claude."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from nodra.cli import statusline as SL  # noqa: E402
from nodra.core.errors import NodraError  # noqa: E402


class StatusLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.nh = os.path.join(self.home, ".nodra")
        os.makedirs(os.path.join(self.nh, "bin"))
        open(os.path.join(self.nh, "bin", "nodra"), "w").close()
        self.env = mock.patch.dict(os.environ, {"HOME": self.home, "NODRA_HOME": self.nh, "USERPROFILE": self.home})
        self.env.start()
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.settings = os.path.join(self.home, ".claude", "settings.json")
        os.makedirs(os.path.dirname(self.settings))

    def tearDown(self):
        self.env.stop()

    def write(self, d):
        with open(self.settings, "w") as f:
            json.dump(d, f)

    def read(self):
        with open(self.settings) as f:
            return json.load(f)

    def test_install_and_remove_keep_the_previous_line(self):
        self.write({"model": "opus", "statusLine": {"type": "command", "command": "echo MINE", "padding": 2}})
        d = SL.install()
        self.assertTrue(d["installed"])
        sl = self.read()["statusLine"]
        self.assertTrue(sl["command"].endswith("nodra statusline"))
        self.assertEqual((sl["padding"], self.read()["model"]), (2, "opus"))
        SL.install()                                                      # twice: still the original kept, not ourselves
        self.assertEqual(d["previous"]["command"], "echo MINE")
        self.assertEqual(SL.status()["previous"]["command"], "echo MINE")
        SL.remove()
        self.assertEqual(self.read()["statusLine"], {"type": "command", "command": "echo MINE", "padding": 2})
        self.assertFalse(SL.status()["installed"])

    def test_no_previous_line_is_removed_again(self):
        self.write({})
        SL.install()
        SL.remove()
        self.assertNotIn("statusLine", self.read())

    def test_settings_with_comments_are_not_rewritten(self):
        with open(self.settings, "w") as f:
            f.write('{ // mine\n "model": "opus" }')
        with self.assertRaises(NodraError):
            SL.install()
        with open(self.settings) as f:
            self.assertIn("// mine", f.read())

    def run_bridge(self, doc):
        out = io.StringIO()
        self.assertEqual(SL.bridge(io.StringIO(doc if isinstance(doc, str) else json.dumps(doc)), out), 0)
        return out.getvalue()

    def test_bridge_keeps_limits_and_prints_a_default(self):
        now = time.time()
        doc = {"model": {"display_name": "Opus"}, "rate_limits": {"five_hour": {"used_percentage": 42.4, "resets_at": now + 600},
                                                                  "seven_day": {"used_percentage": 18, "resets_at": now + 9000}}}
        self.assertEqual(self.run_bridge(doc).strip(), "Opus · 5h 42% · week 18%")
        with open(os.path.join(self.nh, "ui", "limits-statusline.json")) as f:
            kept = json.load(f)
        self.assertEqual(kept["rate_limits"]["five_hour"]["used_percentage"], 42.4)

    def test_bridge_runs_the_previous_line_with_the_same_input(self):
        self.write({"statusLine": {"type": "command", "command": "%s -c \"import sys,json; print('P:' + json.load(sys.stdin)['model']['display_name'])\"" % sys.executable}})
        SL.install()
        self.assertEqual(self.run_bridge({"model": {"display_name": "Sonnet"}}).strip(), "P:Sonnet")

    def test_bridge_never_fails(self):
        self.assertIn("Claude", self.run_bridge("not json"))
        self.assertIn("Claude", self.run_bridge(""))
        self.assertIn("Claude", self.run_bridge({"rate_limits": "weird"}))

    def test_entry_fast_path(self):
        env = dict(os.environ, PYTHONPATH=ROOT)
        r = subprocess.run([sys.executable, "-m", "nodra.cli", "statusline"], input=json.dumps({"model": {"display_name": "Haiku"}}),
                           capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "Haiku"))


if __name__ == "__main__":
    unittest.main()
