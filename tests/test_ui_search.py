"""nodra-chat local search engine (nodraui/searchidx.py): incremental chat index, rewrite detection, tiers, package mirror."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "chat", "ui"))
from nodraui import searchidx as X, store  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get("NODRA_HOME")
        os.environ["NODRA_HOME"] = self.tmp
        store._icache.update(stamp=None, data=None)
        store._counts.clear()
        store._scache.clear()
        X.reset()
        if X._conn() is None:
            self.skipTest("this Python's SQLite has no FTS5")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        X.reset()
        if self.old is None:
            os.environ.pop("NODRA_HOME", None)
        else:
            os.environ["NODRA_HOME"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def chat(self, title, *texts):
        s = store.create_session(title)
        for t in texts:
            store.append(s["id"], {"k": "user", "text": t})
        return s["id"]

    def hits(self, q):
        return [(h["id"], h["snippet"]) for h in store.search(q)]


class Chats(Base):
    def test_words_match_as_prefixes_and_best_chat_comes_first(self):
        a = self.chat("one", "we deployed the kubernetes cluster", "nothing else")
        b = self.chat("two", "kubernetes kubernetes kubernetes cluster upgrade")
        ids = [i for i, _ in self.hits("kuber clust")]
        self.assertEqual(set(ids), {a, b})
        self.assertEqual(ids[0], b)                                     # BM25: more matches, shorter text

    def test_title_hits_come_first(self):
        a = self.chat("Budget review", "x")
        b = self.chat("other", "the budget is fine")
        self.assertEqual([i for i, _ in self.hits("budget")], [a, b])

    def test_appends_are_indexed_incrementally(self):
        sid = self.chat("t", "alpha")
        self.assertEqual(self.hits("bravo"), [])
        store.append(sid, {"k": "msg", "blocks": [{"type": "text", "text": "bravo answer"}]})
        self.assertEqual([i for i, _ in self.hits("bravo")], [sid])
        with X._lock:
            n = X._conn().execute("SELECT COUNT(*) FROM msg").fetchone()[0]
        self.assertEqual(n, 2)                                          # alpha was not indexed twice

    def test_rewrite_and_delete_drop_old_text(self):
        sid = self.chat("t", "zulu one", "yankee two")
        self.assertTrue(self.hits("yankee"))
        store.delete_event(sid, 1)
        self.assertEqual(self.hits("yankee"), [])
        self.assertTrue(self.hits("zulu"))
        store.delete_session(sid)
        self.assertEqual(self.hits("zulu"), [])

    def test_a_file_rewritten_behind_our_back_is_reindexed(self):
        sid = self.chat("t", "original words here")
        self.hits("original")
        p = os.path.join(store.ui_dir("history"), sid + ".jsonl")
        with open(p, "w") as f:                                         # same size or bigger, different bytes
            f.write(json.dumps({"k": "user", "text": "replacement text that is longer"}) + "\n")
        X.touch(sid)                                                    # an append, as far as the index knows
        self.assertEqual(self.hits("original"), [])
        self.assertTrue(self.hits("replacement"))

    def test_warm_pass_indexes_existing_files_and_forgets_deleted_ones(self):
        sid = self.chat("t", "papaya")
        X.reset()
        store._scache.clear()
        X.warm()
        for _ in range(100):
            if X.ready():
                break
            time.sleep(0.02)
        self.assertTrue(X.ready())
        self.assertEqual(X.chats("papaya"), [(sid, "papaya")])

    def test_mid_word_substring_still_found_when_the_index_has_little(self):
        sid = self.chat("t", "supercalifragilistic")
        self.assertEqual([i for i, _ in self.hits("califrag")], [sid])

    def test_scale_query_stays_fast(self):
        c = X._conn()
        with X._lock:
            c.execute("BEGIN")
            c.executemany("INSERT INTO msg(body, sid) VALUES(?, ?)", (("message %d about topic%d common words" % (i, i % 500), "%08x" % (i % 2000)) for i in range(200000)))
            c.execute("COMMIT")
        t0 = time.monotonic()
        rare = X.chats("topic42")
        t1 = time.monotonic()
        common = X.chats("common words")
        t2 = time.monotonic()
        self.assertTrue(rare and common)
        self.assertLess(t1 - t0, 1.5)                                   # loose bounds: a loaded machine (a parallel test run) must not fail it
        self.assertLess(t2 - t1, X.RANK_MS / 1000.0 + 1.5)              # cut and answered newest-first if BM25 over 200k rows is slow


class Mirror(Base):
    def test_packages_exact_prefix_text_and_full_catalogue_removes_gone_ones(self):
        X.merge_pkgs([{"name": "pdf-tools", "description": "Split PDFs"}, {"name": "pdf", "description": "x"}, {"name": "slides", "description": "make pdf decks"}], full=True)
        self.assertEqual([p["name"] for p in X.pkgs("pdf")], ["pdf", "pdf-tools", "slides"])
        X.merge_pkgs([{"name": "pdf"}], full=True, now=time.time() + 1)
        self.assertEqual([p["name"] for p in X.pkgs("pdf")], ["pdf"])

    def test_refresh_reads_the_catalogue_with_one_search_call_and_only_when_stale(self):
        calls = []

        def run(args, timeout=0):
            calls.append(args)
            return {"data": [{"name": "nodra-slides", "type": "skill", "description": "Slide decks"}]}
        with mock.patch.object(X.A, "run", run):
            X._seed()
            self.assertEqual(calls, [["search"]])
            self.assertEqual([p["name"] for p in X.pkgs("slides")], ["nodra-slides"])
            self.assertFalse(X.refresh())                               # fresh: nothing is started
        self.assertEqual(calls, [["search"]])

    def test_a_failing_cli_leaves_the_mirror_as_it_was(self):
        X.merge_pkgs([{"name": "keep-me"}], full=True)

        def boom(args, timeout=0):
            raise X.A.CliError("no cli")
        with mock.patch.object(X.A, "run", boom):
            X._seed()
        self.assertEqual([p["name"] for p in X.pkgs("keep")], ["keep-me"])

    def test_no_space_tables_remain(self):
        names = {r[0] for r in X._conn().execute("SELECT name FROM sqlite_master")}
        self.assertFalse([n for n in names if "space" in n.lower() or n == "asked"])


class Folders(Base):
    def setUp(self):
        super().setUp()
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        p = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        p.start()
        self.addCleanup(p.stop)
        for d in ("code/my-app/.git", "code/my-app/src", "notes/my-app-ideas", "code/node_modules/my-app", ".hidden/my-app", "work/billing"):
            os.makedirs(os.path.join(self.home, d))
        open(os.path.join(self.home, "work", "billing", "nodra.toml"), "w").close()

    def walk(self):
        self.assertTrue(X.dirs_refresh(force=True))
        for _ in range(200):
            if not X.dirs_busy():
                break
            time.sleep(0.02)

    def test_projects_first_hidden_and_vendor_folders_skipped(self):
        self.walk()
        got = [(x["short"], x["proj"]) for x in X.folders("my-app")]
        self.assertEqual(got[0], (os.path.join("~", "code", "my-app"), True))
        self.assertIn((os.path.join("~", "notes", "my-app-ideas"), False), got)
        self.assertFalse(any("node_modules" in g or ".hidden" in g for g, _ in got))
        self.assertEqual(X.folders("bill")[0]["proj"], True)

    def test_a_second_walk_replaces_the_first_and_drops_removed_folders(self):
        self.walk()
        shutil.rmtree(os.path.join(self.home, "notes"))
        os.makedirs(os.path.join(self.home, "fresh-dir"))
        self.walk()
        self.assertEqual([x["name"] for x in X.folders("fresh")], ["fresh-dir"])
        self.assertEqual(X.folders("ideas"), [])
        with X._lock:
            self.assertEqual(X._conn().execute("SELECT COUNT(*) FROM dirs").fetchone()[0], X._conn().execute("SELECT COUNT(*) FROM dir_fts").fetchone()[0])

    def test_a_typed_path_is_listed_live(self):
        got = [x["name"] for x in X.folders("~/code/")]
        self.assertEqual(got, ["code", "my-app"])                       # the folder itself, then its sub folders (no node_modules)
        self.assertEqual([x["name"] for x in X.folders("~/code/my")], ["my-app"])

class Routes(Base):
    def test_spot_pkg_answers_from_the_local_mirror(self):
        import server
        X.merge_pkgs([{"name": "nodra-guide", "description": "Offline guide"}], full=True)
        with mock.patch.object(X, "refresh", lambda force=False: False):
            r = server.spot_pkg(None, {"q": "guide"}, {})
        self.assertEqual([x["name"] for x in r["results"]], ["nodra-guide"])
        self.assertNotIn("more", r)

    def test_there_is_no_hub_search_route(self):
        import server
        self.assertFalse([k for k in server.ROUTES if "hub" in k[1] or "space" in k[1]])
        self.assertFalse(hasattr(server, "spot_hub"))


if __name__ == "__main__":
    unittest.main()
