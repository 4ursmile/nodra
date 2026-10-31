"""nodra-chat: a chat is exported to a bundle (json, readable html or zip) and imported back as a new chat."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "chat", "ui")
sys.path.insert(0, UI)
from nodraui import chatshare  # noqa: E402

ROWS = [{"k": "user", "text": "hello <b>there</b>"}, {"k": "msg", "blocks": [{"type": "text", "text": "hi & welcome"}, {"type": "tool", "name": "Read"}]}]


class Bundle(unittest.TestCase):
    def bundle(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "a.py"), "w") as f:
            f.write("print(1)\n")
        with open(os.path.join(d, "b.bin"), "wb") as f:
            f.write(b"\0\1")
        return chatshare.build({"title": "T", "engine": "claude"}, ROWS, d, ["a.py", "b.bin"])

    def test_only_text_files_travel(self):
        self.assertEqual([f["path"] for f in self.bundle()["files"]], ["a.py"])

    def test_json_and_html_carry_the_same_bundle(self):
        b = self.bundle()
        for text in (chatshare.to_json(b), chatshare.to_html(b)):
            p = chatshare.parse(text)
            self.assertEqual(p["rows"], ROWS)
            self.assertEqual(p["title"], "T")

    def test_page_is_escaped_and_cannot_close_the_data_block(self):
        page = chatshare.to_html(chatshare.build({"title": "</script><i>"}, [{"k": "user", "text": "</script><script>alert(1)</script>"}]))
        self.assertNotIn("<script>alert", page)
        self.assertEqual(page.count("<script"), 1)
        self.assertEqual(chatshare.parse(page)["rows"][0]["text"], "</script><script>alert(1)</script>")

    def test_garbage_is_refused_with_a_message(self):
        for bad in ("hello", "{}", json.dumps({"format": "other"}), "<html></html>", json.dumps({"format": "nodra-chat", "version": 99})):
            with self.assertRaises(ValueError):
                chatshare.parse(bad)

    def test_zip_holds_page_json_and_the_folder_files_and_imports_back(self):
        import io
        import zipfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "sub"))
        with open(os.path.join(d, "sub", "x.bin"), "wb") as f:
            f.write(b"\0\1\2")
        with open(os.path.join(d, "a.py"), "w") as f:
            f.write("print(1)\n")
        data = chatshare.to_zip(chatshare.build({"title": "T", "engine": "claude"}, ROWS), d, ["a.py", "sub/x.bin"])
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(sorted(z.namelist()), ["chat.html", "chat.nodrachat.json", "files/a.py", "files/sub/x.bin"])
        self.assertEqual(json.loads(z.read("chat.nodrachat.json"))["files"], [])               # the files are not duplicated inside the json
        self.assertIn('id="nodra-chat"', z.read("chat.html").decode())
        p = chatshare.parse(data)
        self.assertEqual((p["title"], p["rows"]), ("T", ROWS))
        import base64
        self.assertEqual(sorted((f["path"], base64.b64decode(f["b64"])) for f in p["files"]), [("a.py", b"print(1)\n"), ("sub/x.bin", b"\0\1\2")])

    def test_zip_import_refuses_paths_that_climb_out_and_damaged_zips(self):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("chat.nodrachat.json", chatshare.to_json(chatshare.build({"title": "T"}, ROWS)))
            z.writestr("files/../evil.txt", "x")
            z.writestr("files/ok.txt", "y")
        self.assertEqual([f["path"] for f in chatshare.parse(buf.getvalue())["files"]], ["ok.txt"])
        with self.assertRaises(ValueError):
            chatshare.parse(b"PK\x03\x04 not really a zip")
        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w") as z:
            z.writestr("readme.txt", "no chat here")
        with self.assertRaises(ValueError):
            chatshare.parse(empty.getvalue())

    def test_the_embedded_script_id_and_extension(self):
        page = chatshare.to_html(chatshare.build({"title": "T"}, ROWS))
        self.assertIn('<script type="application/json" id="nodra-chat">', page)
        self.assertEqual(chatshare.FORMAT, "nodra-chat")


if __name__ == "__main__":
    unittest.main()
