"""Export, download and import a chat. stdlib only.

A chat leaves as ONE bundle (`format = "nodra-chat"`): title, settings, the stored history rows and, if asked, the small text files of its
working folder. Three carriers hold the same bundle:
  * `.nodrachat.json` - the bundle itself;
  * `.html`           - a readable transcript page that carries the bundle in `<script type="application/json" id="nodra-chat">`;
  * `.zip`            - `chat.html`, `chat.nodrachat.json` (no files inside) and `files/` (the working folder's files as they are).
Importing reads any of the three. Imported text is DATA: it is never executed, and files are written only inside the new chat's folder.
"""
import base64
import html
import io
import json
import os
import re
import time
import zipfile

FORMAT = "nodra-chat"
VERSION = 1
MAX_BYTES = 40 * 1024 * 1024                    # whole bundle, as text
FILE_MAX = 512 * 1024                           # one working-folder file
FILES_MAX = 4 * 1024 * 1024                     # all of them together
FILES_COUNT = 200
TEXT_EXT = {".md", ".txt", ".py", ".js", ".ts", ".json", ".html", ".css", ".csv", ".svg", ".yml", ".yaml", ".toml", ".sh", ".sql", ".xml", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".h", ".cpp"}
KEEP = ("model", "effort", "mode", "engine")
BLOCK = re.compile(r'<script[^>]*\bid="nodra-chat"[^>]*>(.*?)</script>', re.S | re.I)


def build(s, rows, folder=None, tree=None):
    """Bundle of chat S (a store session) with its history ROWS (dicts). FOLDER + TREE = include the small text files of the working folder."""
    b = {"format": FORMAT, "version": VERSION, "exported": int(time.time()), "title": s.get("title") or "Chat",
         "settings": {k: s.get(k) or "" for k in KEEP}, "soul": s.get("soul"), "rows": rows, "files": []}
    if folder and tree:
        total = 0
        for rel in tree:
            ext = os.path.splitext(rel)[1].lower()
            full = os.path.join(folder, rel)
            if ext not in TEXT_EXT or len(b["files"]) >= FILES_COUNT or ".git" in rel.split("/") or os.path.islink(full):
                continue
            try:
                if os.path.getsize(full) > FILE_MAX or total + os.path.getsize(full) > FILES_MAX:
                    continue
                with open(full, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            total += len(data)
            b["files"].append({"path": rel, "b64": base64.b64encode(data).decode("ascii")})
    return b


def to_json(b):
    return json.dumps(b, ensure_ascii=False, indent=1)


def _texts(row):
    """(role, text) of a stored row, or None: only what a reader of the page wants to see."""
    k = row.get("k")
    if k == "user":
        return "You", str(row.get("text", ""))
    if k == "msg":
        bl = [x for x in row.get("blocks") or [] if isinstance(x, dict)]
        t = "\n".join(x.get("text", "") for x in bl if x.get("type") == "text")
        tools = sorted({str(x.get("name")) for x in bl if x.get("type") == "tool"})
        if t or tools:
            return "Assistant", t + ("\n\n[tools: %s]" % ", ".join(tools) if tools else "")
    return None


def to_html(b):
    """Readable, script-free page of the bundle (all text escaped) that also carries the bundle for a later import."""
    items = []
    for row in b.get("rows") or []:
        if isinstance(row, dict):
            r = _texts(row)
            if r:
                who, text = r
                items.append('<section class="%s"><h2>%s</h2><div>%s</div></section>' % ("me" if who == "You" else "ai", who, html.escape(text)))
    payload = json.dumps(b, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    nf = len(b.get("files") or [])
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title><style>:root{color-scheme:light dark;--bg:#fff;--fg:#1d1d1f;--mut:#6e6e73;--card:#f5f5f7;--acc:#d97757}"
            "@media(prefers-color-scheme:dark){:root{--bg:#1c1c1e;--fg:#f5f5f7;--mut:#98989d;--card:#2c2c2e}}"
            "body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,system-ui,sans-serif}main{max-width:760px;margin:0 auto;padding:32px 20px 64px}"
            "h1{font-size:24px;margin:0 0 4px}p.m{color:var(--mut);margin:0 0 24px;font-size:14px}section{margin:0 0 16px;padding:14px 16px;border-radius:14px;background:var(--card)}"
            "section.me{border-left:3px solid var(--acc)}h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 6px}"
            "section div{white-space:pre-wrap;word-wrap:break-word}</style></head><body><main><h1>%s</h1><p class=\"m\">%d messages%s &middot; "
            "exported from Nodra &middot; import it with Chats &rarr; Import</p>%s</main>"
            "<script type=\"application/json\" id=\"nodra-chat\">%s</script></body></html>"
            % (html.escape(b.get("title") or "Chat"), html.escape(b.get("title") or "Chat"), len(items), (", %d files" % nf) if nf else "", "\n".join(items), payload))


def parse(data):
    """Bundle from a pasted/uploaded `.json`, the exported `.html` page or a chat `.zip`. ValueError with a plain message when it is none."""
    if isinstance(data, str) and data[:2] == "PK":
        data = data.encode("latin-1", "replace")
    if isinstance(data, bytes) and data[:4] == b"PK\x03\x04":
        data = _from_zip(data)
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    if len(data) > MAX_BYTES * 2:
        raise ValueError("too big to be a chat (over 40 MB)")
    t = data.strip()
    if not t.startswith("{"):
        m = BLOCK.search(t)
        if not m:
            raise ValueError("this is not an exported chat (no chat data found)")
        t = m.group(1).strip()
    try:
        b = json.loads(t)
    except ValueError:
        raise ValueError("the chat data is damaged")
    if not isinstance(b, dict) or b.get("format") != FORMAT:
        raise ValueError("this is not an exported chat")
    if int(b.get("version") or 0) > VERSION:
        raise ValueError("made by a newer Nodra: update it first")
    rows = [r for r in b.get("rows") or [] if isinstance(r, dict)]
    files = [f for f in b.get("files") or [] if isinstance(f, dict) and isinstance(f.get("path"), str) and isinstance(f.get("b64"), str)]
    return {"title": str(b.get("title") or "Imported chat")[:120], "settings": b.get("settings") if isinstance(b.get("settings"), dict) else {},
            "soul": b.get("soul") if isinstance(b.get("soul"), str) else None, "rows": rows, "files": files[:FILES_COUNT]}


ZIP_FILE_MAX = 20 * 1024 * 1024
ZIP_FILES_MAX = 100 * 1024 * 1024
ZIP_COUNT = 2000


def to_zip(b, folder=None, tree=None):
    """Zip bytes: chat.html, chat.nodrachat.json (the bundle without files) and files/<path> (the working folder as it is, when given)."""
    bare = dict(b, files=[])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("chat.html", to_html(bare))
        z.writestr("chat.nodrachat.json", to_json(bare))
        total = n = 0
        for rel in (tree or []) if folder else []:
            full = os.path.join(folder, rel)
            parts = rel.split("/")
            if ".git" in parts or "node_modules" in parts or os.path.islink(full) or not os.path.isfile(full) or ".." in parts:
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > ZIP_FILE_MAX or total + size > ZIP_FILES_MAX or n >= ZIP_COUNT:
                continue
            total += size
            n += 1
            z.write(full, "files/" + rel)
    return buf.getvalue()


def _from_zip(data):
    """Bundle text of a chat zip, with the files/ entries folded into the bundle (size capped)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("this zip is damaged")
    names = z.namelist()
    jn = next((n for n in names if n.endswith(".nodrachat.json") and "/" not in n.strip("/")), None)
    hn = next((n for n in names if n == "chat.html"), None)
    if not jn and not hn:
        raise ValueError("this zip has no chat.nodrachat.json or chat.html")
    try:
        b = json.loads(z.read(jn).decode("utf-8")) if jn else json.loads(BLOCK.search(z.read(hn).decode("utf-8", "replace")).group(1))
    except (ValueError, AttributeError):
        raise ValueError("the chat data is damaged")
    if not isinstance(b, dict):
        raise ValueError("this is not an exported chat")
    files, total = [f for f in (b.get("files") or []) if isinstance(f, dict)], 0
    for i in z.infolist():
        if not i.filename.startswith("files/") or i.is_dir() or len(files) >= ZIP_COUNT:
            continue
        rel = i.filename[6:]
        if not rel or ".." in rel.split("/") or rel.startswith("/") or i.file_size > FILE_MAX_IMPORT or total + i.file_size > MAX_BYTES // 2:
            continue
        total += i.file_size
        files.append({"path": rel, "b64": base64.b64encode(z.read(i)).decode("ascii")})
    b["files"] = files
    return json.dumps(b)


FILE_MAX_IMPORT = ZIP_FILE_MAX
