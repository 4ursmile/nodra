"""`nodra --json CMD` / `CMD --json` / NODRA_JSON=1: one JSON document per command, human output unchanged, a `context` without secrets."""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from nodra.cli import main

from .support import Env, KeepUi, make_pkg, run, run_json


class Json(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.env.__enter__()
        self.addCleanup(self.env.__exit__)
        self.home = os.path.join(self.env.home, ".nodra")
        os.makedirs(self.home)
        self.keep = KeepUi()
        self.keep.__enter__()
        self.addCleanup(self.keep.__exit__)
        with open(os.path.join(self.home, "config.json"), "w") as f:
            json.dump({"client_secret": "k-SECRET", "ca_bundle": "/x/ca.pem"}, f)
        os.makedirs(os.path.join(self.home, "packages", "demo"))
        with open(os.path.join(self.home, "state.json"), "w") as f:
            json.dump({"packages": {"demo": {"path": os.path.join(self.home, "packages", "demo"), "version": "1.2.0", "components": ["skill:demo"]}}}, f)

    def run_cli(self, *argv, stdin=""):
        """-> (exit code, stdout text). Child-process output of the command goes to stderr in JSON mode, so stdout is captured at fd level."""
        out = tempfile.TemporaryFile(mode="w+")
        keep = os.dup(1)
        sys.stdout.flush()
        os.dup2(out.fileno(), 1)
        try:
            with mock.patch.object(sys, "stdin", io.StringIO(stdin)), mock.patch.object(sys, "stdout", os.fdopen(os.dup(1), "w")):
                code = main.main(list(argv))
                sys.stdout.flush()
        finally:
            os.dup2(keep, 1)
            os.close(keep)
        out.seek(0)
        return code, out.read()

    def doc(self, *argv, **kw):
        code, text = self.run_cli(*argv, **kw)
        self.assertNotIn("SECRET", text)
        d = json.loads(text)                                  # exactly one document, nothing else on stdout
        self.assertEqual(code, d["exit"])
        self.assertEqual(set(d), {"schema", "ok", "command", "exit", "error", "hint", "data", "output", "messages", "changes", "context"})
        return d

    def test_list_three_ways(self):
        for argv in (("list", "--json"), ("--json", "list")):
            d = self.doc(*argv)
            self.assertEqual((d["ok"], d["command"]), (True, "list"))
            self.assertEqual([(p["name"], p["version"], p["enabled"]) for p in d["data"]], [("demo", "1.2.0", True)])
        with mock.patch.dict(os.environ, {"NODRA_JSON": "1"}):
            self.assertEqual(self.doc("list")["data"][0]["name"], "demo")

    def test_context_has_the_new_shape_and_no_account_fields(self):
        c = self.doc("--json", "list")["context"]
        self.assertEqual(set(c), {"cli_version", "home", "root", "sources", "git"})
        self.assertEqual((c["home"], c["root"], c["git"]), (self.home, self.env.root, True))
        self.assertEqual(c["sources"], [{"name": "core", "url": self.env.root, "kind": "core", "ok": True}])
        self.assertEqual(self.doc("--json", "list")["context"]["cli_version"], c["cli_version"])
        make_pkg(os.path.join(self.env.T, "extra"), "e1")
        self.assertEqual(run("source", "add", "extra", os.path.join(self.env.T, "extra"))[0], 0)
        self.assertEqual([(s["name"], s["kind"], s["ok"]) for s in self.doc("list", "--json")["context"]["sources"]], [("core", "core", True), ("extra", "folder", True)])
        with mock.patch.object(main.gitx, "available", lambda: False):
            self.assertFalse(self.doc("list", "--json")["context"]["git"])

    def test_human_and_plain_output_unchanged(self):
        self.assertEqual(run("list", "--plain"), (0, "demo 1.2.0\n"))
        code, text = run("list")
        self.assertIn("demo", text)
        self.assertRaises(ValueError, json.loads, text)

    def test_config_never_shows_secrets(self):
        d = self.doc("--json", "config")
        self.assertEqual((d["data"]["client_secret"], d["data"]["ca_bundle"]), ("set", "/x/ca.pem"))
        d = self.doc("config", "set", "my_token", "t-SECRET", "--json")
        self.assertEqual(d["data"]["my_token"], "set")
        self.assertNotIn("t-SECRET", json.dumps(d["messages"]))

    def test_errors_are_documents(self):
        d = self.doc("--json", "bogus-command")
        self.assertEqual((d["ok"], d["exit"]), (False, 2))
        self.assertIn("invalid choice", d["error"])
        d = self.doc("list", "--json", "--nope")
        self.assertIn("unrecognized", d["error"])
        d = self.doc("--json", "info", "no-such-package")
        self.assertEqual((d["ok"], d["exit"]), (False, 1))
        self.assertIn("not in any source", d["error"])
        for gone in ("login", "logout", "register", "password", "admin", "hooks", "hook", "flush", "usage-sync", "space", "unpublish", "download", "skill", "auto-update", "setup"):
            self.assertEqual(self.doc("--json", gone)["exit"], 2, gone)

    def test_destructive_commands_are_not_auto_confirmed(self):
        d = self.doc("--json", "self-uninstall")
        self.assertTrue(os.path.isdir(self.home))
        self.assertIn("nothing changed", json.dumps(d["messages"]))

    def test_changes_report_what_a_command_did(self):
        def uninstall(name, quiet=False):
            with open(os.path.join(self.home, "state.json"), "w") as f:
                json.dump({"packages": {}}, f)
        with mock.patch.object(main.installer, "uninstall", uninstall):
            d = self.doc("uninstall", "demo", "--json")
        self.assertEqual(d["changes"], {"removed": [{"name": "demo", "version": "1.2.0"}]})

    def test_vault_list_shows_hosts_not_secrets(self):
        with open(os.path.join(self.home, "vault.json"), "w") as f:
            json.dump({"git.example.com": {"scheme": "https", "username": "ann"}}, f)
        from nodra.cli import vault
        with mock.patch.object(vault, "_secret", lambda h: {"username": "ann", "password": "pw-SECRET"}):
            d = self.doc("vault", "list", "--json")
        self.assertEqual(d["data"]["remotes"], [{"host": "git.example.com", "scheme": "https", "username": "ann", "login": "stored"}])


class ChatContract(unittest.TestCase):
    """The commands the chat calls return useful `data` under --json."""

    def setUp(self):
        self.env = Env()
        self.env.__enter__()
        self.addCleanup(self.env.__exit__)
        self.src = os.path.join(self.env.T, "src")
        make_pkg(self.env.packages, "alpha", "1.0.0")
        make_pkg(self.env.packages, "wf-demo", "0.3.0", kind="skill")
        make_pkg(self.src, "beta", "2.0.0", ["alpha"])

    def test_search_rows(self):
        run("source", "add", "team", self.src)
        self.assertEqual(run("install", "alpha", "--yes", "--tool", "claude")[0], 0)
        rows = run_json("search")["data"]
        self.assertEqual([r["name"] for r in rows], ["alpha", "beta", "wf-demo"])
        a, b = rows[0], rows[1]
        self.assertEqual(set(a), {"name", "version", "latest_version", "type", "description", "tags", "source", "installed", "installed_version"})
        self.assertEqual((a["version"], a["type"], a["tags"], a["source"], a["installed"], a["installed_version"]), ("1.0.0", "skill", ["demo"], "core", True, "1.0.0"))
        self.assertEqual((b["source"], b["installed"], b["installed_version"]), ("team", False, None))
        self.assertEqual([r["name"] for r in run_json("search", "beta")["data"]], ["beta"])
        self.assertEqual([r["name"] for r in run_json("search", "--type", "node")["data"]], [])

    def test_info_list_and_update_check_shapes(self):
        d = run_json("info", "alpha")["data"]
        for k in ("name", "version", "type", "description", "tags", "source", "versions", "components", "requires", "readme", "installed", "installed_version"):
            self.assertIn(k, d)
        self.assertEqual((d["components"], d["versions"], d["installed"]), (["skill:alpha"], [{"version": "1.0.0", "source": "core"}], False))
        self.assertEqual(run_json("update", "--check")["data"]["updates"], [])
        self.assertEqual(run_json("source", "list")["data"]["sources"][0]["kind"], "core")
        self.assertEqual(run_json("list")["data"], [])

    def test_install_data_and_failure(self):
        d = run_json("install", "alpha", "--yes", "--tool", "claude")
        self.assertEqual(d["data"]["installed"], [{"name": "alpha", "version": "1.0.0", "source": "core"}])
        self.assertEqual(d["changes"], {"installed": [{"name": "alpha", "version": "1.0.0"}]})
        d = run_json("install", "nope", "--yes")
        self.assertFalse(d["ok"])

    def test_knowledge_and_doctor_data(self):
        self.assertEqual(run_json("knowledge", "edit", "soul")["data"]["name"], "soul")
        self.assertEqual([n["name"] for n in run_json("knowledge", "list")["data"]["notes"]], ["soul"])
        self.assertIn("persona", run_json("knowledge", "get", "soul")["data"]["body"].lower() + "persona")
        d = run_json("doctor")["data"]
        self.assertTrue({"checks", "python", "git", "packages", "sources"} <= set(d))


if __name__ == "__main__":
    unittest.main()
