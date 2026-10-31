"""Copying a resolved plan out of the sources, and installing several packages with one failing."""
import os
import unittest
from unittest import mock

from nodra.cli import installer, registry
from nodra.core.errors import NodraError

from .support import Env, make_pkg, run


class PrefetchTest(unittest.TestCase):
    def test_every_package_of_a_plan_is_copied_without_git_or_caches(self):
        with Env() as e:
            for n in ("one", "two", "three"):
                d = make_pkg(e.packages, n)
                os.makedirs(os.path.join(d, ".git"))
                os.makedirs(os.path.join(d, "__pycache__"))
            plan = registry.plan([{"name": n, "spec": ""} for n in ("one", "two", "three")], {})
            out = registry.prefetch(plan, os.path.join(e.T, "dl"))
            self.assertEqual(sorted(out), ["one", "three", "two"])
            for n in out:
                folder, err = out[n]
                self.assertIsNone(err)
                self.assertTrue(os.path.isfile(os.path.join(folder, "nodra.toml")))
                self.assertFalse(os.path.exists(os.path.join(folder, ".git")))
                self.assertFalse(os.path.exists(os.path.join(folder, "__pycache__")))
            self.assertEqual({p["name"]: p["source"] for p in plan}, {"one": "core", "two": "core", "three": "core"})

    def test_one_failure_does_not_stop_others(self):
        with Env() as e:
            make_pkg(e.packages, "good")
            plan = registry.plan([{"name": "good", "spec": ""}], {})
            plan.append({"name": "gone", "version": "1", "dir": os.path.join(e.T, "missing"), "source": "x"})
            out = registry.prefetch(plan, os.path.join(e.T, "dl"))
            self.assertIsNone(out["good"][1])
            self.assertIsInstance(out["gone"][1], NodraError)


class InstallManyTest(unittest.TestCase):
    def test_one_plan_and_bad_name_skipped(self):
        seen = []

        def fake_plan(roots, have=None):
            names = [x["name"] for x in roots]
            if "bad" in names:
                raise NodraError("no such package")
            seen.append(names)
            return [{"name": n, "version": "1"} for n in names]

        with mock.patch.object(installer, "plan", fake_plan), \
                mock.patch.object(installer, "state", lambda: {"packages": {}}), \
                mock.patch.object(installer, "installed_versions", lambda st=None: {}), \
                mock.patch.object(installer, "install_plan", lambda pkgs, *a, **k: pkgs), \
                mock.patch.object(installer, "_finish", lambda *a, **k: None):
            failed = installer.install_many([("a", ""), ("bad", ""), ("b", "")])
        self.assertEqual([n for n, _ in failed], ["bad"])
        self.assertEqual(seen[-1], ["a", "b"])

    def test_cli_installs_the_good_ones_and_fails_on_the_bad(self):
        with Env() as e:
            make_pkg(e.packages, "a")
            make_pkg(e.packages, "b")
            rc, out = run("install", "a", "nope", "b", "--yes", "--tool", "claude")
            self.assertEqual(rc, 1)
            self.assertEqual(sorted(installer.state()["packages"]), ["a", "b"])
            self.assertIn("nope", out)


class InstallPlanKeepsGoingTest(unittest.TestCase):
    """One failing package must not stop the others."""

    def test_failure_does_not_skip_later_packages(self):
        pkgs = [{"name": n, "version": "1", "requires": {"packages": deps}}
                for n, deps in (("a", []), ("bad", []), ("c", []), ("needs-bad", ["bad"]))]
        got = []

        def fake_one(r, yes, tools, requested, archive_path=None):
            if r["name"] == "bad":
                raise NodraError("boom")
            got.append(r["name"])

        with mock.patch.object(installer, "_install_one", fake_one), \
                mock.patch.object(installer.registry, "prefetch", lambda p, td: {}):
            with self.assertRaises(NodraError) as cm:
                installer.install_plan(pkgs, True, None, roots=["a", "bad", "c", "needs-bad"])
        self.assertEqual(got, ["a", "c"])
        self.assertIn("bad", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
