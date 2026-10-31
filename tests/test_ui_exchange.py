"""nodra-chat: share = download (chat json/html/zip, files, folders), works and nodes as files, packages / updates / sources through a
stubbed CLI, theme pref validation, and nothing left of hub / spaces / login. Temp NODRA_HOME and HOME; no real CLI, no network."""
import base64
import io
import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT = os.path.join(ROOT, "chat")
UI = os.path.join(CHAT, "ui")
sys.path.insert(0, UI)
from nodraui import nodra as A, secretbox, store, works as W  # noqa: E402

REAL_RUN = A.run                      # other test modules leave A.run patched

FAKE_CLI = textwrap.dedent('''\
    import json, os, sys
    argv = sys.argv[1:]
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(argv) + "\\n")
    assert argv[0] == "--json"
    a = argv[1:]
    ctx = {"cli_version": "9", "home": "/x", "root": "/r", "sources": [{"name": "core", "url": "/r/packages", "kind": "folder", "ok": True}], "git": True}

    def out(data=None, output="", ok=True, error=None):
        print(json.dumps({"schema": 1, "ok": ok, "command": a[0], "exit": 0 if ok else 1, "error": error, "hint": None, "data": data,
                          "output": output, "messages": [{"level": "good", "text": "done"}], "changes": [], "context": ctx}))
        sys.exit(0 if ok else 1)
    c = a[0]
    if c == "list":
        out([{"name": "alpha", "version": "1.0.0", "enabled": True, "type": "skill", "components": ["skill:alpha"], "path": os.environ.get("FAKE_PKG", "/nowhere")}])
    elif c == "search":
        typ = a[a.index("--type") + 1] if "--type" in a else ""
        rows = [{"name": "alpha", "type": "skill", "description": "A skill", "latest_version": "1.1.0", "installed": True, "installed_version": "1.0.0", "source": "core"},
                {"name": "wf-demo", "type": "workflow", "description": "A workflow", "latest_version": "0.1.0", "installed": False, "installed_version": None, "source": "extra"}]
        out([r for r in rows if not typ or r["type"] == typ])
    elif c == "update" and "--check" in a:
        out([{"name": "alpha", "installed_version": "1.0.0", "latest_version": "1.1.0", "source": "core"}])
    elif c == "update":
        out({"updated": a[1:]})
    elif c == "source" and a[1] == "list":
        out([{"name": "core", "url": "/r/packages", "builtin": True, "ok": True}, {"name": "extra", "url": "https://example.com/x.git", "branch": "main", "path": "packages", "ok": True}])
    elif c == "source":
        out({"source": a[1:]})
    elif c == "upgrade" and "--check" in a:
        out({"behind": True, "current": "1.0.0", "latest": "1.0.1", "git": True}, "1 commit behind")
    elif c == "upgrade":
        out({}, "updated")
    elif c == "install":
        if a[1].endswith(".zip"):
            open(os.environ["FAKE_LOG"] + ".zip", "wb").write(open(a[1], "rb").read())
        out({"installed": [a[1]]})
    else:
        out(None, error="unknown command " + c, ok=False)
''')


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        from http.server import ThreadingHTTPServer
        cls.tmp = tempfile.mkdtemp()
        cls.home = tempfile.mkdtemp()
        cls.patch = mock.patch.dict(os.environ, {"NODRA_HOME": cls.tmp, "HOME": cls.home, "USERPROFILE": cls.home})
        cls.patch.start()
        cls.fake = os.path.join(tempfile.mkdtemp(), "fake_nodra.py")
        with open(cls.fake, "w") as f:
            f.write(FAKE_CLI)
        cls.log = os.path.join(cls.tmp, "cli.log")
        os.environ.update(NODRA_CLI=json.dumps([sys.executable, cls.fake]), FAKE_LOG=cls.log)
        cls.pkg = tempfile.mkdtemp()
        os.environ["FAKE_PKG"] = cls.pkg
        server.BOX = secretbox.Box(cls.tmp)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        server.ADDR["port"] = cls.srv.server_address[1]
        cls.port, cls.server = server.ADDR["port"], server
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.patch.stop()

    def setUp(self):
        self.addCleanup(setattr, A, "run", A.run)
        A.run = REAL_RUN
        A.invalidate()
        open(self.log, "w").close()
        W._cat.update(t=0.0, v={})

    # ---- plumbing
    def head(self, **extra):
        return dict({"Cookie": "nodra_ui=" + self.server.TOKEN, "X-Nodra-UI": "1", "Content-Type": "application/json"}, **extra)

    def raw(self, method, path, obj=None, headers=None):
        data = json.dumps(obj).encode() if obj is not None else None
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method, headers=self.head() if headers is None else headers)
        try:
            with urllib.request.urlopen(r) as x:
                return x.status, x.read(), x.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def api(self, method, path, obj=None):
        c, body, h = self.raw(method, "/api/" + path, obj)
        return c, json.loads(body or b"{}")

    def calls(self):
        with open(self.log) as f:
            return [json.loads(x)[1:] for x in f.read().splitlines() if x.strip()]

    def chat(self, files=None):
        s = store.create_session("Report chat")
        store.write_rows(s["id"], [json.dumps({"k": "user", "text": "hello <b>there</b>"}), json.dumps({"k": "msg", "blocks": [{"type": "text", "text": "hi & welcome"}]})])
        d = store.session_dir(s["id"])
        os.makedirs(d, exist_ok=True)
        for name, data in (files or {}).items():
            p = os.path.join(d, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data if isinstance(data, bytes) else data.encode())
        return s["id"], d

    def download(self, path):
        c, body, h = self.raw("GET", "/api/" + path)
        self.assertEqual(c, 200, body[:200])
        self.assertTrue(h["Content-Disposition"].startswith("attachment;"), h["Content-Disposition"])
        self.assertIn("sandbox", h["Content-Security-Policy"])
        return body, h

    def import_chat(self, body, **extra):
        c, d = self.api("POST", "sessions/import", dict({"b64": base64.b64encode(body).decode()}, **extra))
        self.assertEqual(c, 200, d)
        return d

    # ---- chat export / import
    def test_chat_downloads_json_html_zip_and_each_imports_back(self):
        sid, _ = self.chat({"notes/a.txt": "alpha", "img.bin": b"\0\1\2"})
        for fmt, ext in (("json", ".nodrachat.json"), ("html", ".html"), ("zip", ".zip")):
            body, h = self.download("sessions/export?id=%s&format=%s&files=1" % (sid, fmt))
            self.assertIn("Report-chat" + ext, h["Content-Disposition"])
            d = self.import_chat(body)
            self.assertEqual(d["messages"], 2, fmt)
            s = d["session"]
            self.assertEqual(s["title"], "Report chat")
            hist = store.history(s["id"])
            self.assertEqual(hist[0]["text"], "hello <b>there</b>")
            self.assertTrue(d["files"] >= 1, fmt)
            self.assertEqual(open(os.path.join(store.session_dir(s["id"]), "notes", "a.txt")).read(), "alpha")
        zbody, _ = self.download("sessions/export?id=%s&format=zip&files=1" % sid)
        names = zipfile.ZipFile(io.BytesIO(zbody)).namelist()
        self.assertEqual(sorted(names), ["chat.html", "chat.nodrachat.json", "files/img.bin", "files/notes/a.txt"])
        body, _ = self.download("sessions/export?id=%s&format=html" % sid)
        self.assertIn(b'id="nodra-chat"', body)
        body, _ = self.download("sessions/export?id=%s&format=json" % sid)
        self.assertEqual(json.loads(body)["format"], "nodra-chat")

    def test_chat_import_from_pasted_text_and_refuses_garbage(self):
        sid, _ = self.chat()
        body, _ = self.download("sessions/export?id=%s&format=json" % sid)
        c, d = self.api("POST", "sessions/import", {"text": body.decode()})
        self.assertEqual((c, d["messages"]), (200, 2))
        for bad in ({"text": "hello"}, {"b64": base64.b64encode(b"PK\x03\x04junk").decode()}, {}, {"link": "alice@design"}):
            c, d = self.api("POST", "sessions/import", bad)
            self.assertEqual(c, 400, bad)

    def test_downloads_keep_the_key_host_and_origin_checks(self):
        sid, _ = self.chat()
        url = "/api/sessions/export?id=%s&format=json" % sid
        self.assertEqual(self.raw("GET", url, headers={})[0], 401)                                       # no key cookie
        self.assertEqual(self.raw("GET", url, headers={"Cookie": "nodra_ui=wrong"})[0], 401)
        self.assertEqual(self.raw("GET", url, headers=self.head(Host="evil.example"))[0], 403)           # DNS rebinding
        self.assertEqual(self.raw("GET", url, headers=self.head(Origin="http://evil.example"))[0], 403)  # cross-site
        c, body, _ = self.raw("POST", "/api/works/export", {"id": "x"}, headers={"Cookie": "nodra_ui=" + self.server.TOKEN, "Content-Type": "application/json"})
        self.assertEqual(c, 403)                                                                         # writes need the custom header

    # ---- files and folders
    def test_single_html_download_is_one_self_contained_file(self):
        sid, d = self.chat({"report.html": '<html><head><link rel="stylesheet" href="s.css"></head><body><img src="logo.png"><script src="app.js"></script></body></html>',
                            "s.css": "body{color:red}", "app.js": "var x = fetch('rows.csv')", "logo.png": b"PNGDATA", "rows.csv": "a,b\n1,2\n"})
        body, h = self.download("files/download?id=%s&path=report.html" % sid)
        text = body.decode()
        self.assertIn("report.html", h["Content-Disposition"])
        self.assertNotIn('href="s.css"', text)
        self.assertNotIn('src="app.js"', text)
        self.assertIn("body{color:red}", text)
        self.assertIn("data:image/png;base64,", text)
        self.assertIn('"rows.csv":["text/csv"', text)
        self.assertTrue(os.path.isfile(os.path.join(d, "s.css")))                                       # the chat's own files are untouched

    def test_plain_file_download_and_path_rules(self):
        sid, d = self.chat({"data.csv": "a,b\n", "sub/.git/config": "secret", ".git/HEAD": "x"})
        body, h = self.download("files/download?id=%s&path=data.csv" % sid)
        self.assertEqual(body, b"a,b\n")
        self.assertIn("attachment", h["Content-Disposition"])
        for bad in ("../../etc/passwd", "/etc/passwd", ".git/HEAD", "sub/.git/config", "nope.txt"):
            c, _ = self.api("GET", "files/download?id=%s&path=%s" % (sid, bad))
            self.assertEqual(c, 404, bad)

    def test_folder_download_is_a_zip_without_git_or_node_modules(self):
        sid, d = self.chat({"site/index.html": "<h1>x</h1>", "site/a/b.txt": "b", "site/.git/config": "g", "site/node_modules/x/y.js": "n", "other.txt": "o"})
        body, h = self.download("files/download?id=%s&path=site" % sid)
        self.assertIn("site.zip", h["Content-Disposition"])
        self.assertEqual(sorted(zipfile.ZipFile(io.BytesIO(body)).namelist()), ["a/b.txt", "index.html"])
        body, _ = self.download("files/download?id=%s&path=" % sid)                                      # the whole working folder
        names = zipfile.ZipFile(io.BytesIO(body)).namelist()
        self.assertIn("other.txt", names)
        self.assertFalse([n for n in names if ".git" in n or "node_modules" in n])

    def test_folder_zip_has_a_size_cap(self):
        from nodraui import bundle
        d = tempfile.mkdtemp()
        for i in range(3):
            with open(os.path.join(d, "f%d" % i), "wb") as f:
                f.write(b"x" * 1000)
        with mock.patch.object(bundle, "ZIP_MAX", 2500):
            with self.assertRaises(ValueError):
                bundle.zip_folder(d)

    # ---- works
    def make_work(self):
        c = W.save_credential({"kind": "teams", "name": "Team", "config": {"webhook_url": "https://hook/secret-url"}}, self.server.BOX)
        w = store.clean_work({"title": "Mail report", "description": "d", "nodes": [{"id": "s", "type": "start.manual"},
                              {"id": "t", "type": "send.teams", "credential": c["id"], "config": {"text": "hi", "webhook_url": "https://hook/typed-secret"}}],
                              "edges": [{"from": "s", "to": "t"}]})
        return store.save_work(w), c

    def test_work_downloads_as_work_json_and_as_a_package_zip_then_imports(self):
        w, c = self.make_work()
        body, h = self.download_post("works/export", {"id": w["id"], "format": "json"})
        self.assertIn("mail-report.work.json", h["Content-Disposition"])
        doc = json.loads(body)
        self.assertNotIn("id", doc)
        self.assertFalse(doc["enabled"])
        node = next(n for n in doc["nodes"] if n["id"] == "t")
        self.assertEqual((node["credential_kind"], node["config"]["webhook_url"]), ("teams", ""))      # secret blanked, login reduced to its kind
        self.assertNotIn("secret-url", body.decode())
        self.assertNotIn("typed-secret", body.decode())
        zbody, zh = self.download_post("works/export", {"id": w["id"], "format": "zip", "name": "wf-mail", "version": "1.2.3"})
        self.assertIn("wf-mail-1.2.3.zip", zh["Content-Disposition"])
        z = zipfile.ZipFile(io.BytesIO(zbody))
        self.assertEqual(sorted(z.namelist()), ["README.md", "nodra.toml", "works/mail-report.work.json"])
        toml = z.read("nodra.toml").decode()
        self.assertIn('type = "workflow"', toml)
        self.assertIn('name = "wf-mail"', toml)
        everything = "".join(z.read(n).decode() for n in z.namelist())
        self.assertNotIn("secret-url", everything)
        self.assertNotIn("typed-secret", everything)
        for blob in (body, zbody):
            before = len(store.works())
            c2, d = self.api("POST", "works/import-file", {"b64": base64.b64encode(blob).decode(), "name": "x"})
            self.assertEqual(c2, 200, d)
            self.assertFalse(d["work"]["enabled"])
            self.assertEqual(len(store.works()), before + 1)
            self.assertEqual(d["needs_credentials"][0]["kind"], "teams") if not d["work"]["nodes"][1].get("credential") else None
        c2, d = self.api("POST", "works/import-file", {"b64": base64.b64encode(b"not json").decode()})
        self.assertEqual(c2, 400)
        c2, d = self.api("POST", "works/import-file", {"text": json.dumps({"title": "x"})})
        self.assertEqual(c2, 400)                                                                        # no nodes: not a work

    def download_post(self, path, obj):
        c, body, h = self.raw("POST", "/api/" + path, obj)
        self.assertEqual(c, 200, body[:300])
        self.assertTrue(h["Content-Disposition"].startswith("attachment;"))
        return body, h

    def test_work_zip_import_refuses_unsafe_or_empty_zips(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("README.md", "nothing")
        c, d = self.api("POST", "works/import-file", {"b64": base64.b64encode(buf.getvalue()).decode()})
        self.assertEqual(c, 400)
        self.assertIn("no .work.json", d["error"])

    # ---- local nodes
    def test_local_node_exports_and_imports_as_a_zip(self):
        node = {"id": "shout", "title": "Shout", "kind": "action", "group": "Mine", "fields": [{"name": "text", "type": "textarea", "default": "{{input}}"}], "outputs": []}
        c, d = self.api("POST", "nodes/save", {"node": node, "code": self.server.NODE_STARTER + "# marker-xyz\n"})
        self.assertEqual((c, d["type"]), (200, "pkg:local/shout"))
        body, h = self.download_post("nodes/export", {"id": "shout", "name": "nodra-node-shout", "version": "0.2.0"})
        z = zipfile.ZipFile(io.BytesIO(body))
        self.assertEqual(sorted(z.namelist()), ["README.md", "nodes/shout.node.json", "nodes/shout.py", "nodra.toml"])
        self.assertIn('type = "node"', z.read("nodra.toml").decode())
        self.api("POST", "nodes/delete", {"id": "shout"})
        self.assertNotIn("pkg:local/shout", W.catalogue(force=True))
        c, d = self.api("POST", "nodes/import", {"b64": base64.b64encode(body).decode()})
        self.assertEqual((c, d["nodes"][0]["id"], d["nodes"][0]["replaced"]), (200, "shout", False))
        self.assertIn("pkg:local/shout", W.catalogue(force=True))
        c, d = self.api("GET", "nodes/local")
        self.assertIn("marker-xyz", next(n for n in d["nodes"] if n["id"] == "shout")["code"])
        c, d = self.api("POST", "nodes/import", {"b64": base64.b64encode(body).decode()})
        self.assertTrue(d["nodes"][0]["replaced"])
        c, d = self.api("POST", "nodes/import", {"b64": base64.b64encode(b"not a zip").decode()})
        self.assertEqual(c, 400)
        self.api("POST", "nodes/delete", {"id": "shout"})

    # ---- prefs
    def test_theme_pref_over_http(self):
        c, d = self.api("GET", "prefs")
        self.assertEqual(d["prefs"]["theme"], "system")
        c, d = self.api("PUT", "prefs", {"theme": "dark"})
        self.assertEqual((c, d["prefs"]["theme"]), (200, "dark"))
        c, d = self.api("PUT", "prefs", {"theme": "purple-rain"})
        self.assertEqual(c, 400)
        self.assertEqual(self.api("GET", "prefs")[1]["prefs"]["theme"], "dark")
        self.api("PUT", "prefs", {"theme": "system"})

    # ---- packages, updates, sources through the stubbed CLI
    def test_packages_search_updates_and_sources_use_the_cli_contract(self):
        c, d = self.api("GET", "packages")
        self.assertEqual((c, d["packages"][0]["name"]), (200, "alpha"))
        self.assertNotIn("hub", json.dumps(d["context"]))
        c, d = self.api("GET", "search?q=demo&type=workflow")
        self.assertEqual([r["name"] for r in d["results"]], ["wf-demo"])
        self.assertIn(["search", "demo", "--type", "workflow"], self.calls())
        self.assertEqual(self.api("GET", "search?type=bad%20type")[0], 400)
        c, d = self.api("POST", "updates/check", {})
        self.assertEqual(d["updates"], [{"name": "alpha", "installed": "1.0.0", "latest": "1.1.0", "source": "core"}])
        self.assertIn(["update", "--check"], self.calls())
        self.api("POST", "updates/check", {"fetch": False})
        self.assertIn(["update", "--check", "--no-fetch"], self.calls())
        self.api("POST", "update", {"names": ["alpha"]})
        self.api("POST", "update", {})
        self.assertIn(["update", "alpha"], self.calls())
        self.assertIn(["update"], self.calls())
        c, d = self.api("GET", "sources")
        self.assertEqual([s["name"] for s in d["sources"]], ["core", "extra"])
        c, d = self.api("POST", "sources/add", {"name": "mine", "url": "https://example.com/m.git", "branch": "dev", "path": "pkgs"})
        self.assertEqual(c, 200)
        self.assertIn(["source", "add", "mine", "https://example.com/m.git", "--branch", "dev", "--path", "pkgs"], self.calls())
        self.api("POST", "sources/update", {"name": "mine"})
        self.api("POST", "sources/update", {})
        self.api("POST", "sources/remove", {"name": "mine"})
        self.assertTrue({("source", "update", "mine"), ("source", "update"), ("source", "remove", "mine")} <= {tuple(x) for x in self.calls()})
        for bad in ({"name": "-x", "url": "u"}, {"name": "ok", "url": "--evil"}, {"name": "ok", "url": "u", "branch": "a b"}, {"name": "ok", "url": "u", "path": "../x"}, {"name": "", "url": "u"}):
            self.assertEqual(self.api("POST", "sources/add", bad)[0], 400, bad)
        self.assertEqual(self.api("POST", "sources/remove", {"name": "../x"})[0], 400)

    def test_app_upgrade_routes(self):
        c, d = self.api("POST", "upgrade/check", {})
        self.assertEqual((c, d["update"]["behind"], d["update"]["latest"]), (200, True, "1.0.1"))
        self.assertIn(["upgrade", "--check"], self.calls())

    def test_install_from_an_uploaded_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("nodra.toml", '[package]\nname = "p"\nversion = "1.0.0"\ntype = "skill"\n')
        c, d = self.api("POST", "install/file", {"b64": base64.b64encode(buf.getvalue()).decode(), "name": "p.zip"})
        self.assertEqual(c, 200, d)
        self.assertTrue(any(x[0] == "install" and x[1].endswith(".zip") and "--yes" in x for x in self.calls()))
        with open(self.log + ".zip", "rb") as f:
            self.assertEqual(f.read(), buf.getvalue())
        self.assertEqual(self.api("POST", "install/file", {"b64": base64.b64encode(b"nope").decode()})[0], 400)

    def test_boot_works_without_the_cli(self):
        with mock.patch.dict(os.environ, {"NODRA_CLI": "/definitely/not/a/cli"}):
            A.invalidate()
            c, d = self.api("GET", "boot")
        self.assertEqual(c, 200)
        self.assertFalse(d["cli"]["ok"])
        self.assertIn("models", d)
        self.assertEqual(d["prefs"]["theme"], "system")
        A.invalidate()
        c, d = self.api("GET", "boot")
        self.assertTrue(d["cli"]["ok"])


class Wrapper(unittest.TestCase):
    def test_nodra_cli_is_a_json_argv_a_path_or_falls_back(self):
        with mock.patch.dict(os.environ, {"NODRA_CLI": json.dumps(["python3", "-m", "x y"])}):
            self.assertEqual(A.command(), ["python3", "-m", "x y"])
        with mock.patch.dict(os.environ, {"NODRA_CLI": "/opt/my tools/nodra"}):
            self.assertEqual(A.command(), ["/opt/my tools/nodra"])                                       # a path, even with spaces
        env = dict(os.environ)
        env.pop("NODRA_CLI", None)
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.dict(os.environ, {"NODRA_HOME": home}), mock.patch.object(A.shutil, "which", return_value=None):
            self.assertEqual(A.command(), [sys.executable, "-m", "nodra.cli"])                           # nothing installed: the checkout
            os.makedirs(os.path.join(home, "bin"))
            shim = os.path.join(home, "bin", "nodra")
            open(shim, "w").close()
            self.assertEqual(A.command(), [shim])
        with mock.patch.dict(os.environ, {"NODRA_ROOT": ROOT}):
            e = A.cli_env()
            self.assertIn(ROOT, e["PYTHONPATH"].split(os.pathsep))
            self.assertEqual((e["NODRA_ROOT"], e["NODRA_JSON"]), (ROOT, "1"))
            self.assertNotIn("NODRA_JSON", A.cli_env(machine=False)) if "NODRA_JSON" not in os.environ else None


class NoHub(unittest.TestCase):
    """Nothing of the hub, spaces, login or telemetry is left in routes, modules or the page's code."""
    FORBIDDEN_ROUTES = re.compile(r"hub|space|login$|logout|brand|share|publish|telemetry|usage-sync|policy", re.I)

    def test_no_route_mentions_them(self):
        import server
        bad = [k for k in server.ROUTES if self.FORBIDDEN_ROUTES.search(k[1]) and k[1] != "auth/login"]       # auth/login = Claude's apiKeyHelper sign-in
        self.assertEqual(bad, [])
        self.assertIn(("POST", "auth/login"), server.ROUTES)

    def test_files_and_modules_are_gone(self):
        for rel in ("ui/static/space.js", "ui/nodes/space_publish.py", "ui/nodraui/hubusage.py", "ui/nodraui/spacebundle.py"):
            self.assertFalse(os.path.exists(os.path.join(CHAT, rel)), rel)
        for rel in ("ui/nodraui/bundle.py", "ui/nodraui/uselog.py", "ui/static/theme.js", "ui/static/theme-init.js"):
            self.assertTrue(os.path.isfile(os.path.join(CHAT, rel)), rel)

    def test_the_page_code_has_no_hub_account_spaces_or_login_calls(self):
        bad = re.compile(r"signed_in|hub_configured|\"login\"|\"logout\"|spot/hub|space\.js|spaces/publish|sessions/share|\bhubusage\b|online_search|policy guard|\.hub\b|@space|\ba Space\b|Spaces? (on|to) the hub|Share to a Space", re.I)
        static = os.path.join(UI, "static")
        for fn in sorted(os.listdir(static)):
            if fn.endswith((".js", ".html", ".css")):
                with open(os.path.join(static, fn), encoding="utf-8") as f:
                    hits = [m.group(0) for m in bad.finditer(f.read())]
                self.assertEqual(hits, [], fn)

    def test_the_server_and_modules_never_name_a_hub(self):
        bad = re.compile(r"\bhub\b|signed_in|telemetry|NO_GUARD|aihub|usage-sync|\"space\"|space publish", re.I)
        files = [os.path.join(UI, "server.py")] + [os.path.join(UI, "nodraui", f) for f in os.listdir(os.path.join(UI, "nodraui")) if f.endswith(".py")]
        for p in files:
            with open(p, encoding="utf-8") as f:
                hits = [m.group(0) for m in bad.finditer(f.read())]
            self.assertEqual(hits, [], p)

    def test_every_page_script_parses(self):
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        static = os.path.join(UI, "static")
        for fn in sorted(os.listdir(static)):
            if fn.endswith(".js"):
                r = subprocess.run([node, "--check", os.path.join(static, fn)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, fn + ": " + r.stderr[:300])


if __name__ == "__main__":
    unittest.main()
