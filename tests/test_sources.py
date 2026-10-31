"""Sources: core, folders, git (a temp bare repository), git missing, Claude Code marketplaces."""
import json
import os
import unittest
from unittest import mock

from nodra.cli import gitx, installer, registry, sources
from nodra.core import manifest as M

from .support import Env, bare_repo, git, make_pkg, run, run_json


def rows():
    return {r["name"]: r for r in run_json("source", "list")["data"]["sources"]}


class Core(unittest.TestCase):
    def test_core_is_always_there_and_cannot_be_changed(self):
        with Env() as e:
            make_pkg(e.packages, "alpha")
            r = rows()
            self.assertEqual((r["core"]["kind"], r["core"]["ok"], r["core"]["packages"], r["core"]["url"]), ("core", True, 1, e.root))
            for argv in (("source", "remove", "core"), ("source", "add", "core", e.T)):
                self.assertEqual(run(*argv)[0], 1)
            self.assertEqual([p["name"] for p in registry.search("")], ["alpha"])

    def test_the_real_checkout_core_holds_the_repo_packages(self):
        names = {p["name"] for p in registry.search("")}
        self.assertTrue({"nodra-guide", "nodra-package"} <= names, names)


class Folder(unittest.TestCase):
    def test_folder_with_packages_dir_or_flat(self):
        with Env() as e:
            flat, nested = os.path.join(e.T, "flat"), os.path.join(e.T, "nested")
            make_pkg(flat, "f1")
            make_pkg(os.path.join(nested, "packages"), "n1")
            make_pkg(os.path.join(nested, "other"), "n2")
            self.assertEqual(run("source", "add", "flat", flat)[0], 0)
            self.assertEqual(run("source", "add", "nested", nested)[0], 0)
            self.assertEqual(run("source", "add", "other", nested, "--path", "other")[0], 0)
            got = {p["name"]: p["source"] for p in registry.search("")}
            self.assertEqual(got, {"f1": "flat", "n1": "nested", "n2": "other"})
            r = rows()
            self.assertEqual((r["flat"]["kind"], r["flat"]["ok"], r["flat"]["packages"]), ("folder", True, 1))
            self.assertEqual(r["other"]["path"], "other")

    def test_missing_folder_is_reported_not_fatal(self):
        with Env() as e:
            d = os.path.join(e.T, "gone")
            os.makedirs(d)
            make_pkg(d, "x")
            run("source", "add", "gone", d)
            import shutil
            shutil.rmtree(d)
            r = rows()["gone"]
            self.assertFalse(r["ok"])
            self.assertIn("not found", r["error"])
            self.assertEqual(registry.search(""), [])
            self.assertEqual(run("search")[0], 0)

    def test_add_validates_and_remove_works(self):
        with Env() as e:
            self.assertEqual(run("source", "add", "Bad Name!", e.T)[0], 1)
            self.assertEqual(run("source", "add", "x", os.path.join(e.T, "nope"))[0], 1)
            self.assertEqual(run("source", "add", "ok", e.T)[0], 0)
            self.assertEqual(run("source", "add", "ok", e.T)[0], 1)                   # twice
            self.assertEqual(run("source", "remove", "ok")[0], 0)
            self.assertEqual(run("source", "remove", "ok")[0], 1)
            self.assertEqual(list(rows()), ["core"])

    def test_same_version_in_two_sources_first_wins_newer_wins_over_older(self):
        with Env() as e:
            a, b = os.path.join(e.T, "a"), os.path.join(e.T, "b")
            make_pkg(e.packages, "dup", "1.0.0")
            make_pkg(a, "dup", "1.0.0")
            make_pkg(b, "dup", "1.2.0")
            run("source", "add", "a", a)
            run("source", "add", "b", b)
            p = registry.get("dup")
            self.assertEqual((p["latest_version"], p["source"]), ("1.2.0", "b"))
            self.assertEqual([(v["version"], v["source"]) for v in p["versions"]], [("1.0.0", "core"), ("1.2.0", "b")])
            self.assertEqual(registry.resolve("dup", "<1.2")["source"], "core")


class Git(unittest.TestCase):
    def test_bare_repo_is_cloned_shallow_and_searched(self):
        with Env() as e:
            bare, work = bare_repo(e.T, packages=[("gp", "1.0.0", []), ("gq", "0.5.0", [])])
            d = run_json("source", "add", "team", bare, "--branch", "main")
            self.assertTrue(d["ok"], d)
            self.assertEqual(d["data"]["source"]["kind"], "git")
            self.assertEqual(d["data"]["source"]["packages"], 2)
            clone = sources.clone_dir("team")
            self.assertTrue(os.path.isdir(os.path.join(clone, ".git")))
            self.assertEqual(git(clone, "rev-list", "--count", "HEAD"), "1")
            r = rows()["team"]
            self.assertEqual((r["kind"], r["ok"], r["packages"]), ("git", True, 2))
            self.assertEqual(r["rev"], git(work, "rev-parse", "HEAD"))
            self.assertEqual({p["name"]: p["source"] for p in registry.search("")}, {"gp": "team", "gq": "team"})
            self.assertEqual(run("install", "gp", "--yes", "--tool", "claude")[0], 0)
            rec = installer.state()["packages"]["gp"]
            self.assertEqual((rec["source"], rec["rev"], rec["version"]), ("team", git(work, "rev-parse", "HEAD"), "1.0.0"))
            self.assertEqual(run("source", "remove", "team")[0], 0)
            self.assertFalse(os.path.exists(clone))

    def test_file_url_and_branch(self):
        with Env() as e:
            bare, work = bare_repo(e.T, packages=[("gp", "1.0.0", [])])
            git(work, "checkout", "-q", "-b", "next")
            make_pkg(os.path.join(work, "packages"), "only-next")
            git(work, "add", "-A")
            git(work, "commit", "-q", "-m", "n")
            git(work, "push", "-q", "origin", "next")
            self.assertEqual(run("source", "add", "nx", "file://" + bare, "--branch", "next")[0], 0)
            self.assertEqual(sorted(p["name"] for p in registry.search("")), ["gp", "only-next"])

    def test_git_missing_degrades_cleanly(self):
        with Env() as e:
            bare, _ = bare_repo(e.T, packages=[("gp", "1.0.0", [])])
            make_pkg(e.packages, "local-one")
            with mock.patch.object(gitx, "available", lambda: False):
                d = run_json("source", "add", "team", bare)
                self.assertTrue(d["ok"], d)                                          # saved; just not usable yet
                self.assertFalse(d["data"]["source"]["ok"])
                self.assertIn("git is not installed", d["data"]["source"]["error"])
                self.assertIn("skipped", d["data"]["source"]["hint"])
                self.assertEqual([p["name"] for p in registry.search("")], ["local-one"])      # core and folders keep working
                self.assertEqual(run("install", "local-one", "--yes", "--tool", "claude")[0], 0)
                d = run_json("source", "update")
                self.assertTrue(d["ok"])
                self.assertEqual(d["data"]["fetched"][0]["error"], "git is not installed")
                d = run_json("update", "--check")
                self.assertTrue(d["ok"], d)
                self.assertFalse(d["context"]["git"])
                self.assertTrue(run_json("doctor")["ok"])
                self.assertEqual(run_json("upgrade", "--check")["data"]["git"], False)
            self.assertFalse(sources.sources()[1]["ok"])                              # not cloned, git back: the hint says how
            self.assertIn("nodra source update", sources.sources()[1]["hint"])

    def test_unreachable_git_source_is_an_error_row_not_a_crash(self):
        with Env() as e:
            make_pkg(e.packages, "local-one")
            d = run_json("source", "add", "bad", os.path.join(e.T, "no-such.git"))
            self.assertFalse(d["ok"])                                                # neither a folder nor a git URL: refused, nothing saved
            self.assertEqual(list(rows()), ["core"])
            self.assertEqual(run("source", "add", "bad", "https://127.0.0.1:9/none.git")[0], 0)
            r = rows()["bad"]
            self.assertFalse(r["ok"])
            self.assertEqual([p["name"] for p in registry.search("")], ["local-one"])


class Marketplace(unittest.TestCase):
    def plugin_repo(self, parent):
        root = os.path.join(parent, "mkt")
        for p in ("alpha", "beta"):
            os.makedirs(os.path.join(root, "plugins", p, "skills", p + "-skill"))
            with open(os.path.join(root, "plugins", p, "skills", p + "-skill", "SKILL.md"), "w") as f:
                f.write("---\nname: %s-skill\ndescription: x\n---\nhi\n" % p)
        os.makedirs(os.path.join(root, "plugins", "alpha", "agents"))
        open(os.path.join(root, "plugins", "alpha", "agents", "helper.md"), "w").write("---\nname: helper\n---\nhi\n")
        os.makedirs(os.path.join(root, "plugins", "alpha", "commands"))
        open(os.path.join(root, "plugins", "alpha", "commands", "ship.md"), "w").write("Ship it\n")
        open(os.path.join(root, "plugins", "alpha", ".mcp.json"), "w").write(json.dumps(
            {"mcpServers": {"tool": {"command": "node", "args": ["${CLAUDE_PLUGIN_ROOT}/server.js"], "env": {"K": "v"}}}}))
        os.makedirs(os.path.join(root, "plugins", "empty"))
        os.makedirs(os.path.join(root, ".claude-plugin"))
        with open(os.path.join(root, ".claude-plugin", "marketplace.json"), "w") as f:
            json.dump({"name": "m", "owner": {"name": "o"}, "plugins": [
                {"name": "alpha", "source": "./plugins/alpha", "description": "Alpha plugin", "version": "1.2.0", "category": "dev", "tags": ["x"]},
                {"name": "beta", "source": "./plugins/beta"},
                {"name": "empty", "source": "./plugins/empty"},
                {"name": "remote", "source": {"source": "github", "repo": "owner/none"}},
                {"name": "missing", "source": "./plugins/not-there"}]}, f)
        return root

    def test_plugins_become_synthetic_packages_and_install(self):
        with Env() as e:
            root = self.plugin_repo(e.T)
            self.assertEqual(run("source", "add", "mkt", root)[0], 0)
            r = rows()["mkt"]
            self.assertEqual((r["kind"], r["ok"], r["packages"]), ("marketplace", True, 2))     # empty, remote (not fetched) and missing are skipped
            cat = {p["name"]: p for p in registry.search("")}
            self.assertEqual((cat["alpha"]["version"], cat["alpha"]["type"], cat["alpha"]["description"]), ("1.2.0", "skill", "Alpha plugin"))
            self.assertEqual(sorted(cat["alpha"]["tags"]), ["dev", "x"])
            self.assertEqual(cat["beta"]["version"], "0.0.0")
            info = run_json("info", "alpha")["data"]
            self.assertEqual(info["components"], ["skill:alpha-skill", "agent:helper", "command:ship", "mcp:tool"])
            self.assertEqual(run("install", "alpha", "--yes", "--tool", "claude")[0], 0)
            rec = installer.state()["packages"]["alpha"]
            self.assertEqual(rec["source"], "mkt")
            m = M.parse(open(os.path.join(rec["path"], "nodra.toml")).read())             # the generated manifest of the installed copy
            self.assertEqual([x["name"] for x in m["skills"]], ["alpha-skill"])
            self.assertEqual(m["mcp_servers"][0]["args"], ["${PKG}/server.js"])
            home = e.home
            self.assertTrue(os.path.isdir(os.path.join(home, ".claude", "skills", "alpha-skill")))
            self.assertTrue(os.path.isfile(os.path.join(home, ".claude", "agents", "helper.md")))
            self.assertTrue(os.path.isfile(os.path.join(home, ".claude", "commands", "ship.md")))
            cj = json.load(open(os.path.join(home, ".claude.json")))
            self.assertEqual(cj["mcpServers"]["tool"]["args"], [os.path.join(rec["path"], "server.js")])
            self.assertEqual(run("uninstall", "alpha", "--force")[0], 0)
            self.assertFalse(os.path.exists(os.path.join(home, ".claude", "commands", "ship.md")))

    def test_marketplace_in_a_git_repo(self):
        with Env() as e:
            root = self.plugin_repo(e.T)
            git(root, "init", "-q", "-b", "main")
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "x")
            self.assertEqual(run("source", "add", "gm", "file://" + root)[0], 0)
            r = rows()["gm"]
            self.assertEqual((r["kind"], r["packages"]), ("marketplace", 2))


if __name__ == "__main__":
    unittest.main()
