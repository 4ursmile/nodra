"""install from a name, a folder and a .zip; update --check / update from folder and git sources; source and rev are recorded."""
import os
import unittest

from nodra.cli import installer, sources
from nodra.core import version as V

from .support import Env, bare_repo, git, make_pkg, run, run_json, set_version


class InstallForms(unittest.TestCase):
    def test_install_from_name_folder_and_zip(self):
        with Env() as e:
            make_pkg(e.packages, "by-name", "1.0.0")
            mine = make_pkg(os.path.join(e.T, "mine"), "from-folder", "0.2.0", ["by-name>=1"])
            self.assertEqual(run("install", "by-name", "--yes", "--tool", "claude")[0], 0)
            st = installer.state()["packages"]
            self.assertEqual((st["by-name"]["source"], st["by-name"]["rev"], st["by-name"]["version"]), ("core", None, "1.0.0"))
            self.assertTrue(e.skill("by-name"))
            # a folder
            d = run_json("install", mine, "--yes", "--tool", "claude")
            self.assertTrue(d["ok"], d)
            st = installer.state()["packages"]
            self.assertEqual((st["from-folder"]["source"], st["from-folder"]["version"]), ("folder", "0.2.0"))
            self.assertEqual(st["from-folder"]["deps"], ["by-name>=1"])
            self.assertEqual(d["data"]["installed"], [{"name": "from-folder", "version": "0.2.0", "source": "folder"}])
            self.assertTrue(e.skill("from-folder"))
            # a zip made by `dev pack`, installed under a new version, in a clean home
            set_version(mine, "0.3.0")
            z = os.path.join(e.T, "out", "ff.zip")
            self.assertEqual(run("dev", "pack", mine, "-o", z)[0], 0)
            self.assertEqual(run("uninstall", "from-folder", "--force")[0], 0)
            self.assertEqual(run("install", z, "--yes", "--tool", "claude")[0], 0)
            st = installer.state()["packages"]
            self.assertEqual((st["from-folder"]["source"], st["from-folder"]["version"]), ("zip", "0.3.0"))
            self.assertTrue(os.path.isfile(os.path.join(st["from-folder"]["path"], "skills", "from-folder", "SKILL.md")))
            self.assertEqual(sources.sources()[0]["dir"], e.root)                  # the zip's scratch folder is gone, core untouched

    def test_folder_dependencies_come_from_the_sources_and_missing_ones_fail(self):
        with Env() as e:
            lonely = make_pkg(os.path.join(e.T, "mine"), "lonely", "1.0.0", ["nobody-has-this"])
            rc, out = run("install", lonely, "--yes")
            self.assertEqual(rc, 1)
            self.assertIn("nobody-has-this", out)
            self.assertEqual(installer.state()["packages"], {})

    def test_bad_inputs(self):
        with Env() as e:
            open(os.path.join(e.T, "x.txt"), "w").write("x")
            os.makedirs(os.path.join(e.T, "empty"))
            for arg in (os.path.join(e.T, "x.txt"), os.path.join(e.T, "empty"), os.path.join(e.T, "missing.zip")):
                self.assertEqual(run("install", arg, "--yes")[0], 1, arg)
            import zipfile
            z = os.path.join(e.T, "evil.zip")
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("../escape.txt", "x")
            self.assertEqual(run("install", z, "--yes")[0], 1)
            self.assertFalse(os.path.exists(os.path.join(e.T, "escape.txt")))

    def test_zip_with_a_top_folder_works(self):
        with Env() as e:
            import zipfile
            d = make_pkg(os.path.join(e.T, "w"), "zipped", "1.0.0")
            z = os.path.join(e.T, "z.zip")
            with zipfile.ZipFile(z, "w") as zf:
                for base, _, files in os.walk(d):
                    for f in files:
                        full = os.path.join(base, f)
                        zf.write(full, os.path.join("zipped-1.0.0", os.path.relpath(full, d)))
            self.assertEqual(run("install", z, "--yes", "--tool", "claude")[0], 0)
            self.assertEqual(installer.state()["packages"]["zipped"]["source"], "zip")


class Updates(unittest.TestCase):
    def test_folder_source_update_check_and_update(self):
        with Env() as e:
            src = os.path.join(e.T, "src")
            p = make_pkg(src, "up", "1.0.0")
            run("source", "add", "s", src)
            run("install", "up", "--yes", "--tool", "claude")
            self.assertEqual(run_json("update", "--check")["data"]["updates"], [])
            set_version(p, "1.1.0")
            d = run_json("update", "--check")
            self.assertEqual(d["data"]["updates"], [{"name": "up", "installed": "1.0.0", "available": "1.1.0", "source": "s"}])
            self.assertEqual(installer.state()["packages"]["up"]["version"], "1.0.0")        # --check changes nothing
            d = run_json("update", "--no-fetch")
            self.assertTrue(d["ok"], d)
            self.assertEqual(d["data"]["updated"], [{"name": "up", "from": "1.0.0", "to": "1.1.0", "source": "s"}])
            self.assertEqual(d["changes"], {"updated": [{"name": "up", "from": "1.0.0", "to": "1.1.0"}]})
            self.assertEqual(installer.state()["packages"]["up"]["version"], "1.1.0")
            self.assertEqual(run_json("update", "--check")["data"]["updates"], [])

    def test_git_source_update_after_a_new_commit(self):
        with Env() as e:
            bare, work = bare_repo(e.T, packages=[("gp", "1.0.0", []), ("other", "1.0.0", [])])
            self.assertEqual(run("source", "add", "team", bare)[0], 0)
            self.assertEqual(run("install", "gp", "other", "--yes", "--tool", "claude")[0], 0)
            first = git(work, "rev-parse", "HEAD")
            self.assertEqual(installer.state()["packages"]["gp"]["rev"], first)
            self.assertEqual(run_json("update", "--check")["data"]["updates"], [])
            # upstream bumps one package and pushes
            set_version(os.path.join(work, "packages", "gp"), "1.1.0")
            git(work, "add", "-A")
            git(work, "commit", "-q", "-m", "bump gp")
            git(work, "push", "-q", "origin", "main")
            second = git(work, "rev-parse", "HEAD")
            # --no-fetch does not see it; the default fetches
            self.assertEqual(run_json("update", "--check", "--no-fetch")["data"]["updates"], [])
            d = run_json("update", "--check")
            self.assertEqual(d["data"]["updates"], [{"name": "gp", "installed": "1.0.0", "available": "1.1.0", "source": "team"}])
            self.assertTrue(d["data"]["fetched"][0]["changed"])
            self.assertEqual(sources.get("team")["rev"], second)
            d = run_json("update", "--no-fetch")
            self.assertEqual([u["name"] for u in d["data"]["updated"]], ["gp"])
            rec = installer.state()["packages"]
            self.assertEqual((rec["gp"]["version"], rec["gp"]["rev"], rec["other"]["rev"]), ("1.1.0", second, first))
            self.assertEqual(run_json("update", "--check")["data"]["updates"], [])

    def test_update_named_and_constraints_from_dependents(self):
        with Env() as e:
            src = os.path.join(e.T, "src")
            base = make_pkg(src, "base", "1.0.0")
            make_pkg(src, "app", "1.0.0", ["base<2"])
            run("source", "add", "s", src)
            run("install", "app", "--yes", "--tool", "claude")
            set_version(base, "2.0.0")                                                       # newer than app allows
            self.assertEqual(run_json("update", "--check")["data"]["updates"], [])
            set_version(base, "1.5.0")
            self.assertEqual([u["name"] for u in run_json("update", "--check")["data"]["updates"]], ["base"])
            self.assertEqual(run("update", "nope", "--no-fetch")[0], 1)
            self.assertEqual(run_json("update", "app", "--check")["data"]["updates"], [])

    def test_folder_installed_packages_have_no_source_to_update(self):
        with Env() as e:
            mine = make_pkg(os.path.join(e.T, "mine"), "solo", "1.0.0")
            run("install", mine, "--yes", "--tool", "claude")
            set_version(mine, "2.0.0")
            self.assertEqual(run_json("update", "--check")["data"]["updates"], [])
            self.assertEqual(run("update", "--no-fetch")[0], 0)

    def test_version_helpers_still_order_correctly(self):
        self.assertTrue(V.compare("1.10.0", "1.9.0") > 0)


if __name__ == "__main__":
    unittest.main()
