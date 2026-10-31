"""install.py (the python-only installer at the repository root) into a scratch HOME / NODRA_HOME."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, "install.py")


def load():
    spec = importlib.util.spec_from_file_location("nodra_install_py", INSTALL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class InstallPy(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.home = os.path.join(self.t, "home")
        self.nh = os.path.join(self.t, "nodra-home")
        os.makedirs(self.home)
        self.env = dict(os.environ, HOME=self.home, USERPROFILE=self.home, NODRA_HOME=self.nh, SHELL="/bin/zsh")
        self.env.pop("ZDOTDIR", None)
        self.env.pop("PYTHONPATH", None)
        self.env["PATH"] = "/usr/bin:/bin"
        self.rc = os.path.join(self.home, ".zshrc")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.t, ignore_errors=True)

    def run_install(self, *args):
        return subprocess.run([sys.executable, INSTALL] + list(args), env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)

    def test_yes_writes_the_shim_config_and_path_block(self):
        open(self.rc, "w").write("export A=1\n")
        r = self.run_install("--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        shim = os.path.join(self.nh, "bin", "nodra")
        self.assertTrue(os.access(shim, os.X_OK))
        body = open(shim).read()
        self.assertIn(ROOT, body)
        self.assertIn("-m nodra.cli", body)
        self.assertEqual(json.load(open(os.path.join(self.nh, "config.json")))["root"], ROOT)
        rc = open(self.rc).read()
        self.assertIn("# >>> nodra\nexport PATH=\"%s:$PATH\"\n# <<< nodra" % os.path.join(self.nh, "bin"), rc)
        self.assertTrue(rc.startswith("export A=1\n"))
        # the installed command runs from any folder, with a scratch NODRA_HOME
        out = subprocess.run([shim, "--version"], env=self.env, cwd=self.t, capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "nodra 1.0.0"))
        out = subprocess.run([shim, "--json", "source", "list"], env=self.env, cwd=self.t, capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout)["context"]["home"], self.nh)

    def test_idempotent(self):
        open(self.rc, "w").write("export A=1\n")
        self.run_install("--yes")
        first = (open(self.rc).read(), open(os.path.join(self.nh, "bin", "nodra")).read(), open(os.path.join(self.nh, "config.json")).read())
        self.assertEqual(self.run_install("--yes").returncode, 0)
        self.assertEqual((open(self.rc).read(), open(os.path.join(self.nh, "bin", "nodra")).read(), open(os.path.join(self.nh, "config.json")).read()), first)
        self.assertEqual(open(self.rc).read().count("# >>> nodra"), 1)

    def test_no_path_and_no_terminal_never_touch_the_shell_config(self):
        for args in (("--no-path",), ()):                       # without --yes and without a terminal nothing is asked, so nothing is changed
            r = self.run_install(*args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse(os.path.exists(self.rc), args)
            self.assertIn(os.path.join(self.nh, "bin"), r.stdout)
            self.assertTrue(os.path.exists(os.path.join(self.nh, "bin", "nodra")))

    def test_asks_before_adding_the_path_line(self):
        m = load()
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(m, "ask", return_value=False) as ask:
            m.setup_path()
            self.assertEqual(ask.call_count, 1)
            self.assertFalse(os.path.exists(self.rc))
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(m, "ask", return_value=True):
            m.setup_path()
            self.assertIn("# >>> nodra", open(self.rc).read())

    def test_fish_and_bash_targets(self):
        m = load()
        with mock.patch.dict(os.environ, dict(self.env, SHELL="/usr/bin/fish"), clear=True):
            f, flavour = m.rc_file()
            self.assertTrue(f.endswith(os.path.join(".config", "fish", "config.fish")))
            self.assertIn("fish_add_path", m.path_block(flavour))
        with mock.patch.dict(os.environ, dict(self.env, SHELL="/bin/bash"), clear=True), mock.patch.object(sys, "platform", "linux"):
            self.assertTrue(m.rc_file()[0].endswith(".bashrc"))

    def test_uninstall_removes_shim_and_block_only(self):
        open(self.rc, "w").write("export A=1\n\nexport B=2\n")
        self.run_install("--yes")
        os.makedirs(os.path.join(self.nh, "packages", "keep"))
        r = self.run_install("--uninstall")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.nh, "bin", "nodra")))
        self.assertEqual(open(self.rc).read(), "export A=1\n\nexport B=2\n")
        self.assertNotIn("root", json.load(open(os.path.join(self.nh, "config.json"))))
        self.assertTrue(os.path.isdir(os.path.join(self.nh, "packages", "keep")))      # your data stays
        self.assertEqual(self.run_install("--uninstall").returncode, 0)                 # again: nothing to do, still fine

    def test_already_on_path_is_left_alone(self):
        m = load()
        env = dict(self.env, PATH=os.path.join(self.nh, "bin") + os.pathsep + "/usr/bin")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(m.on_path())
            self.assertIsNone(m.setup_path())
        self.assertFalse(os.path.exists(self.rc))

    def test_windows_shim_bodies(self):
        m = load()
        self.assertIn('set "PYTHONPATH=C:\\nodra;%PYTHONPATH%"', m.cmd_body("C:\\nodra", "C:\\Py\\python.exe"))
        self.assertIn('"C:\\Py\\python.exe" -m nodra.cli %*', m.cmd_body("C:\\nodra", "C:\\Py\\python.exe"))
        self.assertIn("C:/nodra", m.sh_body("C:\\nodra", "C:\\Py\\python.exe"))                # Git Bash wants forward slashes

    def test_needs_python_39_and_the_repository(self):
        m = load()
        with mock.patch.object(m.sys, "version_info", (3, 8, 0)), self.assertRaises(SystemExit):
            m.check_python()


if __name__ == "__main__":
    unittest.main()
