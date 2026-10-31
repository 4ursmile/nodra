"""CLI package management over folder sources: dependency resolve, enable/disable, tree, lock, sync."""
import json
import os
import unittest

from nodra.cli import installer
from nodra.core.errors import NodraError

from .support import Env, make_pkg, run


class CliManage(unittest.TestCase):
    def test_all(self):
        with Env() as e:
            a, b, c = (os.path.join(e.T, x) for x in "abc")
            for n, v, d in [("base", "1.0.0", []), ("left", "1.0.0", ["base>=1,<2"]), ("right", "1.0.0", ["base>=1.2,<3"]), ("top", "1.0.0", ["left", "right"]),
                            ("solo", "1.0.0", []), ("bad", "1.0.0", ["base>=3"]), ("clash-a", "1.0.0", ["base<1.2"]), ("clash-b", "1.0.0", ["base>=1.5"]),
                            ("clash", "1.0.0", ["clash-a", "clash-b"])]:
                make_pkg(a, n, v, d)
            make_pkg(b, "base", "1.5.0")                      # versions of one package come from different sources
            make_pkg(c, "base", "2.0.0")
            for name, d in (("sa", a), ("sb", b), ("sc", c)):
                self.assertEqual(run("source", "add", name, d)[0], 0)
            st = lambda: installer.state()["packages"]
            # one-round-trip diamond resolve picks base 1.5.0 (satisfies both)
            pk = installer.plan([{"name": "top", "spec": ""}], {})
            self.assertEqual([p["name"] for p in pk], ["base", "left", "right", "top"])
            self.assertEqual(pk[0]["version"], "1.5.0")
            # conflict reports who requires what
            with self.assertRaises(NodraError) as cx:
                installer.plan([{"name": "clash", "spec": ""}], {})
            self.assertIn("base", str(cx.exception))
            self.assertIn("clash-", str(cx.exception))
            with self.assertRaises(NodraError) as cx:
                installer.plan([{"name": "bad", "spec": ""}], {})
            self.assertIn("no version of base", str(cx.exception))
            # install with deps
            rc, o = run("install", "top", "--yes", "--tool", "claude")
            self.assertEqual(rc, 0, o)
            s = st()
            self.assertEqual(set(s), {"base", "left", "right", "top"})
            self.assertTrue(s["top"]["requested"])
            self.assertFalse(s["base"].get("requested"))
            self.assertEqual((s["base"]["version"], s["base"]["source"]), ("1.5.0", "sb"))
            self.assertTrue(e.skill("base") and e.skill("top"))
            rc, o = run("tree")
            self.assertIn("top", o)
            self.assertIn("├─", o)
            rc, o = run("tree", "top", "--remote")
            self.assertIn("(installed)", o)
            # disable guarded by dependents
            rc, o = run("disable", "base")
            self.assertEqual(rc, 1)
            self.assertIn("needed by", o)
            rc, o = run("disable", "top")
            self.assertEqual(rc, 0, o)
            self.assertFalse(e.skill("top"))
            self.assertTrue(os.path.isdir(st()["top"]["path"]))
            self.assertFalse(st()["top"]["enabled"])
            rc, o = run("list")
            self.assertIn("disabled", o)
            rc, o = run("list", "--plain")
            self.assertEqual(rc, 0)
            self.assertTrue(all(len(x.split()) == 2 for x in o.splitlines()) and o.splitlines(), o)      # "name version", nothing else
            rc, o = run("list", "--name-only")
            self.assertIn("top", o.splitlines())
            # install again == enable (files already here)
            rc, o = run("install", "top", "--yes", "--tool", "claude")
            self.assertEqual(rc, 0, o)
            self.assertIn("enabled", o)
            self.assertTrue(e.skill("top"))
            self.assertTrue(st()["top"]["enabled"])
            # enable pulls disabled deps first
            run("disable", "top")
            run("disable", "left")
            run("disable", "right")
            rc, o = run("disable", "base")
            self.assertEqual(rc, 0, o)
            rc, o = run("enable", "top", "--yes", "--tool", "claude")
            self.assertEqual(rc, 0, o)
            self.assertTrue(all(st()[n]["enabled"] for n in ("base", "left", "right", "top")))
            # update skips disabled
            run("disable", "top")
            rc, o = run("update", "--no-fetch")
            self.assertNotIn("top", o)
            run("enable", "--all", "--yes", "--tool", "claude")
            # lock
            lf = os.path.join(e.T, "nodra.lock")
            rc, o = run("lock", "-f", lf)
            self.assertEqual(rc, 0, o)
            with open(lf) as f:
                lock = json.load(f)
            self.assertEqual([x["name"] for x in lock["packages"]][-1], "top")
            self.assertEqual(set(lock), {"lockfile_version", "packages"})
            self.assertEqual(run("lock", "-f", lf, "--check")[0], 0)
            # drift: extra package + lock check fails
            run("install", "solo", "--yes", "--tool", "claude")
            self.assertEqual(run("lock", "-f", lf, "--check")[0], 1)
            rc, o = run("sync", "-f", lf, "--check")
            self.assertEqual(rc, 0, o)                                                   # extras alone do not fail check
            rc, o = run("sync", "-f", lf, "--yes", "--prune", "--tool", "claude")
            self.assertEqual(rc, 0, o)
            self.assertNotIn("solo", st())
            # simulate a fresh machine: wipe state and files, sync restores the same set and enabled flags
            for n in list(st()):
                installer.uninstall(n, quiet=True)
            self.assertEqual(st(), {})
            rc, o = run("sync", "-f", lf, "--yes", "--tool", "claude")
            self.assertEqual(rc, 0, o)
            s = st()
            self.assertEqual({n: r["version"] for n, r in s.items()}, {x["name"]: x["version"] for x in lock["packages"]})
            self.assertTrue(s["top"]["requested"] and not s["base"]["requested"])
            # a lock naming a version no source offers is refused, nothing is installed
            for n in list(st()):
                installer.uninstall(n, quiet=True)
            lock["packages"][0]["version"] = "9.9.9"
            with open(lf, "w") as f:
                json.dump(lock, f)
            rc, o = run("sync", "-f", lf, "--yes", "--tool", "claude")
            self.assertEqual(rc, 1)
            self.assertEqual(st(), {})                                                   # the refused sync installed nothing
            rc, o = run("install", "top", "--yes", "--tool", "claude")
            self.assertEqual(rc, 0, o)
            # uninstall of a dependency warns
            rc, o = run("uninstall", "base", "--force")
            self.assertEqual(rc, 0)
            self.assertIn("still needed by", o)


if __name__ == "__main__":
    unittest.main()
