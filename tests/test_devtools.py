"""`nodra dev pack` and `nodra dev marketplace`."""
import json
import os
import unittest
import zipfile

from nodra.cli import devtools

from .support import Env, make_pkg, run, run_json, set_version


class Pack(unittest.TestCase):
    def test_zip_has_nodra_toml_at_the_root_and_skips_junk(self):
        with Env() as e:
            d = make_pkg(e.T, "zp", "1.4.0")
            for junk in (".git/config", "__pycache__/x.pyc", ".venv/bin/python", "node_modules/m/i.js", "dist/old.tar.gz", "sub/__pycache__/y.pyc"):
                p = os.path.join(d, junk)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "w").write("x")
            open(os.path.join(d, ".gitignore"), "w").write("secret.txt\n")
            open(os.path.join(d, "secret.txt"), "w").write("s")
            out = os.path.join(e.T, "o", "zp.zip")
            doc = run_json("dev", "pack", d, "-o", out)
            self.assertTrue(doc["ok"], doc)
            self.assertEqual((doc["data"]["name"], doc["data"]["version"], doc["data"]["file"]), ("zp", "1.4.0", out))
            names = sorted(zipfile.ZipFile(out).namelist())
            self.assertIn("nodra.toml", names)
            self.assertIn("skills/zp/SKILL.md", names)
            self.assertEqual([n for n in names if n.startswith((".git/", "__pycache__", ".venv", "node_modules", "dist")) or "__pycache__" in n or n == "secret.txt"], [])
            self.assertEqual(doc["data"]["files"], len(names))
            before = open(out, "rb").read()
            run("dev", "pack", d, "-o", out)
            self.assertEqual(open(out, "rb").read(), before)                      # same files, same bytes

    def test_default_name_in_the_current_folder_and_output_folder(self):
        with Env() as e:
            d = make_pkg(e.T, "dn", "0.1.0")
            keep = os.getcwd()
            os.chdir(e.T)
            try:
                self.assertEqual(run("dev", "pack", d)[0], 0)
            finally:
                os.chdir(keep)
            self.assertTrue(os.path.isfile(os.path.join(e.T, "dn-0.1.0.zip")))
            os.makedirs(os.path.join(e.T, "outdir"))
            self.assertEqual(run("dev", "pack", d, "-o", os.path.join(e.T, "outdir"))[0], 0)
            self.assertTrue(os.path.isfile(os.path.join(e.T, "outdir", "dn-0.1.0.zip")))

    def test_not_a_package(self):
        with Env() as e:
            self.assertEqual(run("dev", "pack", e.T)[0], 1)


class MarketplaceFile(unittest.TestCase):
    def repo(self, e):
        make_pkg(e.packages, "skilly", "1.0.0")
        d = make_pkg(e.packages, "agenty", "2.0.0", extra='[[agents]]\nname = "ag"\npath = "agents/ag.md"\n')
        os.makedirs(os.path.join(d, "agents"))
        open(os.path.join(d, "agents", "ag.md"), "w").write("---\nname: ag\n---\nhi\n")
        mcp = make_pkg(e.packages, "mcpy", "1.0.0", kind="mcp", extra='[[mcp_servers]]\nname = "srv"\ncommand = "node"\nargs = ["${PKG}/s.js"]\n')
        open(os.path.join(mcp, "s.js"), "w").write("//")
        pr = os.path.join(e.packages, "prices")
        os.makedirs(pr)
        open(os.path.join(pr, "nodra.toml"), "w").write('[package]\nname="prices"\nversion="1.0.0"\ntype="setup"\ndescription="d"\n')       # nothing for Claude Code
        bot = os.path.join(e.packages, "botty")
        os.makedirs(os.path.join(bot, "bot"))
        open(os.path.join(bot, "nodra.toml"), "w").write('[package]\nname="botty"\nversion="1.0.0"\ntype="bot"\ndescription="d"\n[bot]\nrun="bot/run.py"\n'
                                                         '[[mcp_servers]]\nname="b"\ncommand="x"\n')                                       # a bot's MCP servers are its own
        open(os.path.join(bot, "bot", "run.py"), "w").write("")

    def test_write_check_and_stale(self):
        with Env() as e:
            self.repo(e)
            f = os.path.join(e.root, ".claude-plugin", "marketplace.json")
            d = run_json("dev", "marketplace", "--check")
            self.assertFalse(d["ok"])                                             # missing file = stale
            self.assertTrue(d["data"]["stale"])
            d = run_json("dev", "marketplace")
            self.assertTrue(d["ok"], d)
            self.assertEqual(d["data"]["plugins"], ["agenty", "mcpy", "skilly"])
            doc = json.load(open(f))
            self.assertEqual((doc["name"], [p["name"] for p in doc["plugins"]]), ("nodra", ["agenty", "mcpy", "skilly"]))
            by = {p["name"]: p for p in doc["plugins"]}
            self.assertEqual(by["skilly"]["source"], "./packages/skilly")
            self.assertEqual(by["skilly"], {"name": "skilly", "source": "./packages/skilly", "description": "skilly package", "version": "1.0.0"})
            self.assertNotIn("agents", by["agenty"])                                  # conventional layout: Claude Code finds it itself
            self.assertEqual(by["mcpy"]["mcpServers"], {"srv": {"command": "node", "args": ["${CLAUDE_PLUGIN_ROOT}/s.js"]}})
            self.assertNotIn("prices", by)
            self.assertNotIn("botty", by)
            self.assertTrue(run_json("dev", "marketplace", "--check")["ok"])
            self.assertEqual(open(f).read(), devtools.render(devtools.build_marketplace(e.root)))      # deterministic
            set_version(os.path.join(e.packages, "skilly"), "1.0.1")
            d = run_json("dev", "marketplace", "--check")
            self.assertFalse(d["ok"])
            self.assertEqual(run("dev", "marketplace", "--check")[0], 1)
            self.assertEqual(run("dev", "marketplace")[0], 0)
            self.assertEqual(run("dev", "marketplace", "--check")[0], 0)

    def test_unconventional_layouts_get_explicit_lists(self):
        with Env() as e:
            d = make_pkg(e.packages, "odd", "1.0.0", extra='[[agents]]\nname = "ag"\npath = "stuff/agent-file.md"\n')
            os.makedirs(os.path.join(d, "stuff"))
            open(os.path.join(d, "stuff", "agent-file.md"), "w").write("x")
            self.assertEqual(run("dev", "marketplace")[0], 0)
            doc = json.load(open(os.path.join(e.root, ".claude-plugin", "marketplace.json")))
            self.assertEqual(doc["plugins"][0]["agents"], ["./stuff/agent-file.md"])

    def test_the_file_is_read_back_by_core_without_duplicates(self):
        with Env() as e:
            self.repo(e)
            run("dev", "marketplace")
            names = [p["name"] for p in __import__("nodra.cli.registry", fromlist=["x"]).search("")]
            self.assertEqual(sorted(names), ["agenty", "botty", "mcpy", "prices", "skilly"])         # entries that point at real packages add nothing

    def test_the_real_checkout_file_is_current(self):
        real = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isfile(os.path.join(real, ".claude-plugin", "marketplace.json")):
            self.skipTest("no marketplace file in this checkout yet")
        self.assertEqual(run("dev", "marketplace", "--check", real)[0], 0, "run: python3 -m nodra.cli dev marketplace")


if __name__ == "__main__":
    unittest.main()
