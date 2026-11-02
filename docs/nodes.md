# Writing nodes for Nodra Works

A **Work** is a graph in the Works editor of the Nodra chat: a *Start* node produces an event, the event text flows along the edges through *action* nodes, and the run ends. You can add your own nodes by shipping them in an ordinary Nodra package. Install the package and its nodes appear in the editor's **Add node** list, grouped under the group you chose.

Everything here runs on your machine. A node is just a program: the engine starts it, sends one JSON document on stdin and reads one JSON line from stdout. No account, no server, no network unless your node makes a call itself.

Before writing a node, check whether you need one:

| You want to... | Use |
| --- | --- |
| Ask an LLM, summarise, classify, write a file, send a mail, call an MCP tool | The built-in **Claude task** node. Pick the model, effort and permission mode on the node. It runs Claude Code, so every skill, agent and MCP server Nodra installed is available. A skill such as "send mail" makes a node unnecessary. |
| Start from a cron schedule, a webhook call or a button | Built-in **Start: schedule / webhook / manual**. |
| Keep only matching text | Built-in **Filter (regex)**, or the **filter** field every Start node has. |
| Listen to something that is not a webhook (a chat, a queue, a file) or call a service deterministically, with no LLM | **A package node** (this guide). |

## A minimal working node (5 minutes)

Scaffold it, or create the two files by hand:

```sh
nodra dev init ./shout --type node --name shout --description "Upper-case the text"
```

```
shout/
  nodra.toml
  README.md
  nodes/
    shout.node.json
    shout.py
```

`nodra.toml`:

```toml
[package]
name = "shout"
version = "0.1.0"
type = "node"
description = "Upper-case the text that flows through"
readme = "README.md"
license = "MIT"
```

`nodes/shout.node.json`:

```json
{
  "id": "shout",
  "title": "Shout",
  "kind": "action",
  "group": "Text",
  "description": "Upper-cases the incoming text and appends a suffix.",
  "run": ["{python}", "nodes/shout.py"],
  "timeout": 20,
  "fields": [
    {"name": "suffix", "label": "Suffix", "type": "text", "default": "!"}
  ],
  "inputs": [{"name": "input", "type": "text", "desc": "text to shout", "required": true}],
  "outputs": [
    {"name": "text", "type": "text", "desc": "the shouted text"},
    {"name": "length", "type": "text", "desc": "number of characters", "example": "12"}
  ]
}
```

`nodes/shout.py` (reads one JSON document on stdin, prints one JSON line last):

```python
import json
import sys

req = json.load(sys.stdin)
cfg = req.get("config") or {}
text = str(req.get("input") or "")
out = text.upper() + str(cfg.get("suffix") or "")
print(json.dumps({"ok": True, "output": out, "data": {"length": len(out)}, "log": "shouted %d chars" % len(text)}))
```

Test it without the chat, exactly as the engine would call it:

```sh
echo '{"config":{"suffix":"!"},"input":"hello"}' | python3 nodes/shout.py
# {"ok": true, "output": "HELLO!", "data": {"length": 6}, "log": "shouted 5 chars"}
nodra dev validate ./shout
nodra install ./shout --yes
```

Open Works > Add node: **Shout** is in the group *Text*. Its type is `pkg:shout/shout`. You can also build a node inside the chat (Works > Nodes > *New node*, saved under `~/.nodra/ui/nodes/<id>/`, type `pkg:local/<id>`); to hand it to someone else, put its files in a package like the one above.

## The built-in nodes

| Type | Kind | What it does |
| --- | --- | --- |
| `start.manual` | trigger | The Run button. |
| `start.cron` | trigger | `schedule` = cron (`0 8 * * 1-5`) or interval (`30s`, `5m`, `2h`, `1d`, minimum 10 s); optional event `text`. Fires only while the work is **On** and the chat service runs; missed times are not replayed. |
| `start.webhook` | trigger | `POST http://127.0.0.1:PORT/hook/<work>/<node>/<token>` with plain text or `{"text": "...", "data": {...}}`. Local only; the URL is shown in the node's panel. |
| `ai.claude` | action | Prompt with `{{input}}` (text from the previous node), `{{trigger}}` (the event text) and `{{data.key}}`. Model, effort, permission mode. All Claude nodes of one run share one chat (context and prompt cache carry over) unless `fresh` is ticked. Unattended runs use *Accept edits* by default; a tool that would need approval is denied. |
| `ai.free` | action | Free chat: a direct API call (no Claude Code), optional MCP servers (tool loop). See [mcp.md](mcp.md). |
| `flow.filter` | action | Regex on the incoming text. No match: this branch ends. `invert` flips it. |
| `flow.template` | action | New text from `{{input}}`, `{{trigger}}`, `{{data.key}}`. |
| `flow.output` | action | The answer of the work (heading + markdown template). |
| `flow.memory` | action | Adds remembered context: this work's earlier runs, the last messages of a chat, or another work's runs. |
| `flow.loop` / `flow.endloop` | action | Repeat the nodes in between once per item of a list (see Loop below). |
| `io.read_file` | action | Read a local text file or list a folder. Refuses key, secret and `.env` files, `~/.ssh`, `~/.aws`, `~/.gnupg`, most of `~/.nodra`, Claude settings. |
| `io.request` | action | HTTP GET/POST/PUT/PATCH/DELETE/HEAD with headers and body; optional *Pick* (`a.b.0.c`) from a JSON answer. Output data: `status`, `json`. |
| `io.path` | action | Check that local files / folders / `*` patterns exist and output the path(s). |
| `git.read`, `git.pull` | action | Read a file or folder of a remote https repository, or clone/update it into `~/.nodra/workingspace/data/git/NAME`. Uses logins saved with `nodra vault`. |
| `send.smtp` | action | Send mail through any SMTP server (stdlib only), save an IMAP draft, or write an `.eml` file. |
| `code.python` | action | One typed Python function (see below). |

Every **trigger** also has a `filter` field: a case-insensitive regex tested against the event text **before a run is created**. An event that does not match never starts anything. Your trigger code does not need to implement this, send everything.

## Prompt help: suggest and highlight

A text field lists what it may suggest in `"assist"` (any of `input`, `data`, `file`, `skill`), in a `*.node.json` field or in the node form:

| Value | Typing | Suggests / highlights |
| --- | --- | --- |
| `input` | `{{` | `{{input}}` (text of the node(s) connected before this one), `{{trigger}}` |
| `data` | `{{` | `{{data.key}}` for the inputs of a Start: manual and the keys that upstream nodes list in `"outputs"` |
| `file` | `@` | files and folders under your home folder (names only), highlighted as `@path` |
| `skill` | `/` | skills, commands and package slash commands |

Without `assist`, a textarea or a `templated` field gets `input` + `data`; the prompt of Claude task and Free chat gets all four.

## How data flows between nodes

Every node hands on `{text, data}`. `text` is a string; `data` is a dict (only pointer, trigger and package nodes fill it: `path`, `status`, your Start inputs). The editor shows, for the selected node, what it **Receives**, what it **Produces** and what it **Needs**.

- **One parent**: `{{input}}` is that parent's text.
- **Several parents** (a join): the node waits for ALL of them. `{{input}}` is their texts one after another, each under `## From <node name>`, in the order the lines were drawn. `{{in.1}}`, `{{in.2}}` (same order) or `{{in.<node name>}}` (lower case, other characters `_`) is ONE parent's text. `{{data.x}}` merges the parents' data; on the same key the later parent wins.
- **Claude prompt**: if the prompt contains `{{input}}` or an `{{in.x}}`, you place the text yourself. If it contains none, the engine puts `Input: <text>` before `Task: <prompt>`.
- **Claude to a file node**: Claude only answers with text. A node after it takes the path from the LAST line of that text that names an existing file or folder (`OUTPUT: /full/path`), or from the `path` data of a pointer node, or from its own File field.
- **Parallel branches**: nodes that do not depend on each other run at the same time (at most 4 per run); a node starts when all its parents are done.
- **Input / output schema.** A node declares ONE explicit contract: `"inputs": [{"name","type","desc","required"}]` and `"outputs": [{"name","type","desc","example"}]` (`type` = `text|path|json|url`). The output called `text` is what the next node gets as `{{input}}`; every other output is `{{data.name}}`. An input called `input` is the text of the parent; other names are standard keys taken from the node before (`takes`) or a settings field. The editor shows **Takes / Gives** and warns about a `{{data.x}}` that no node before it declares. Older keys still work as a fallback: `"out"`/`"out_note"`, `"outputs": ["path"]`, `"needs"`/`"needs_note"`.
- **Working folder.** Every run has ONE folder, `~/.nodra/ui/runs/<work>/<run>/work/`, with a sub folder per node. `{{run.dir}}` and `{{node.dir}}` are template variables; a program gets `workdir` and `run.dir` / `run.node_dir` in its stdin JSON, and `NODRA_RUN_DIR` / `NODRA_NODE_DIR` in its environment.
- **Logs.** Every node execution writes `runs/<work>/<run>/<node>.log` (command, stdout, `[err]` stderr lines, exit code; capped at 1 MB; secret values replaced by `***`). A program is judged finished when it EXITS.

## Layout of a node package

Use `type = "node"` (`nodra dev init ./my-node --type node --name my-node` writes a working starter; `nodra dev validate` checks each `nodes/*.node.json`). Any other package type with a `nodes/` folder also works. Put one JSON file per node in `nodes/` and the program it runs next to it:

```
nodra-nodes-teams/
  nodra.toml
  nodes/
    teams-message.node.json     # trigger
    teams_message.py
    teams-send.node.json        # action
    teams_send.py
    teams.cred.json             # credential kind (optional)
```

Complete, tested examples live in this repository: [`packages/nodra-nodes-teams`](../packages/nodra-nodes-teams), [`packages/nodra-nodes-discord`](../packages/nodra-nodes-discord) (a gateway trigger with its own Python venv) and [`packages/nodra-nodes-outlook`](../packages/nodra-nodes-outlook) (Windows only). The editor reads the catalogue from the installed packages (`nodra list`), refreshing every 10 s.

### `*.node.json`

```json
{
  "id": "teams-send",
  "title": "Send to Teams",
  "kind": "action",
  "group": "Teams",
  "description": "Posts a message to a Teams channel.",
  "run": ["{python}", "nodes/teams_send.py"],
  "timeout": 30,
  "fields": [
    {"name": "webhook_url", "label": "Webhook URL", "type": "password", "required": true},
    {"name": "text", "label": "Message", "type": "textarea", "default": "{{input}}"}
  ]
}
```

| Key | Meaning |
| --- | --- |
| `id` | Lowercase letters, digits, `. _ -`. The node type is `pkg:<package>/<id>`. |
| `kind` | `trigger` (starts runs, no input) or `action`. |
| `group`, `title`, `description` | Where it appears in **Add node** and what the panel shows. |
| `guide` | Optional text shown above the settings ("How to set this up"). |
| `run` | The command as a list, never a shell string. `{python}` = the interpreter running the chat, or the package's own venv python when `nodra.toml` has a `[python]` table; `{pkg}` = your package folder. The working directory is the package folder. |
| `timeout` | Seconds for an action (5..3600, default 120). Triggers run until stopped. |
| `inputs`, `outputs` | The I/O schema. Optional, but fill it in: it drives the editor and the prompt suggestions. |
| `takes` | Field names that are filled from `{{data.<same name>}}` of the nodes before when the field is empty (see Node contract). |
| `templated` | Fields in which `{{input}}`, `{{trigger}}`, `{{data.key}}` are expanded before the program starts. |
| `credential` | Which credential kind this node uses (see Credentials). |
| `vault` | `true`: the program may read the credential sets granted to its node (`nodra_vault`, see below). Off by default. |
| `packages` | pip packages the program needs, e.g. `["pandas>=2", "openpyxl"]`. The node's Environment box checks and installs them (see "Python environments"). |
| `fields` | The settings form. `type`: `text`, `textarea`, `number`, `checkbox`, `select` (+ `options`), `password`, `model`, `effort`, `mode`, `code` (+ `lang`: `python`, `sql`, `json` ...: the colour editor with Expand), `env` (the Python environment the program runs with: `{python}` becomes that interpreter). Also `label`, `default`, `required`, `help`, `secret`, `assist`. |

Malformed node files are ignored silently, so check the node shows up in the editor (and run `nodra dev validate`).

**Secrets.** A field with `"type": "password"` or `"secret": true` is stored encrypted (`~/.nodra/ui/secrets.bin`, key `~/.nodra/ui/.key`), the work file keeps only a marker, the editor never shows the value again, and your program receives the real value in the stdin document (never on the command line, never in the environment). A node must not log it.

### Action nodes: one request, one answer

The program is started for each run. It reads **one JSON document** from stdin:

```json
{"config": {"webhook_url": "https://...", "text": "{{input}}"},
 "input": "text of the previous node(s), joined",
 "inputs": [{"text": "...", "data": {"from": "alice"}}],
 "run": {"id": "20261028110105-fb1517", "work": "8e24267e", "node": "n1a2b",
         "dir": "/Users/me/.nodra/ui/runs/8e24267e/20261028110105-fb1517/work",
         "node_dir": "/Users/me/.nodra/ui/runs/8e24267e/20261028110105-fb1517/work/n1a2b"},
 "workdir": "/Users/me/.nodra/ui/runs/8e24267e/20261028110105-fb1517/work"}
```

and prints **one JSON line** as the last thing on stdout:

```json
{"ok": true, "output": "text for the next node", "data": {"id": 42}, "log": "HTTP 200"}
```

- `output` is a string or a JSON value (stringified for downstream). `data` is a dict that travels along as `{{data.key}}`.
- `{"ok": false, "error": "why"}` or a non-zero exit fails the node: the branch stops and the run is `failed`. Write diagnostics to stderr.
- `{"output": {"skip": true}}` ends the branch quietly (like a filter that did not match).
- Template placeholders inside your own `config` values (`{{input}}`) are **not** expanded for you unless the node lists those fields in `"templated": ["to", "subject"]`; otherwise do it in the program.
- `workdir` is the run folder; relative paths start there, and files written there show under Files in the run view.
- stdin of a program you start yourself is `/dev/null` unless you pass it data (a CLI that waits for input would hang); send its output to files or pipes you read until it EXITS.
- Stop (Works > Running now, or the run view) kills your program's process group: do not detach children you need.

### Trigger nodes: a process that stays up

A trigger program is started when the work is switched **On** and stopped when it is switched off, edited, or deleted. A crash restarts it after 30 s, doubling to 15 minutes. It reads **one line of JSON** from stdin (`{"config": {...}, "run": {"work", "node"}}`) and then prints **one JSON line per event** on stdout, flushed:

```json
{"event": {"text": "deploy prod", "data": {"from": "alice", "chat": "ops"}}}
```

For each line the chat applies the trigger's `filter` regex to `text`, and if it matches, queues a run (runs of one work execute one after the other, 50 queued at most). Everything else on stdout is ignored; stderr is discarded.

A minimal trigger that fires every N seconds (`nodes/tick.node.json` with `"kind": "trigger"`, `"run": ["{python}", "nodes/tick.py"]` and a number field `every`):

```python
import json
import sys
import time

cfg = json.loads(sys.stdin.readline())["config"]
every = max(5, int(cfg.get("every") or 60))
n = 0
while True:
    n += 1
    print(json.dumps({"event": {"text": "tick %d" % n, "data": {"n": n}}}), flush=True)
    time.sleep(every)
```

Test a trigger by piping one line and reading what it prints:

```sh
echo '{"config":{"every":5},"run":{"work":"w","node":"n"}}' | python3 nodes/tick.py
```

### Example: start from a Teams message (regex first), then send to Teams

1. `nodra install nodra-nodes-teams`.
2. New work: **Start: Teams message** (port `8791`, filter `^deploy `) connected to **Claude task** (prompt: `Plan the rollout for: {{input}}`, model `sonnet`) connected to **Send to Teams** (paste the channel's Workflows webhook URL; it is encrypted).
3. Switch the work **On**.
4. Point your Teams bot at the trigger. The node only listens on `127.0.0.1` and accepts `POST /message` with `{"from", "chat", "text"}`. Test by hand:

```sh
curl -s -X POST http://127.0.0.1:8791/message -d '{"from":"alice","chat":"ops","text":"deploy prod now"}'   # {"taken": true}  -> a run starts
curl -s -X POST http://127.0.0.1:8791/message -d '{"from":"alice","chat":"ops","text":"lunch?"}'          # dropped by the filter, no run
```

Filtering happens in layers, cheapest first: the node's own settings inside your process, then the trigger's `filter` regex before a run exists, then **Filter** nodes inside the graph.

### Credentials: one set for several nodes

A **credential set** is a named group of fields (for example `teams`: tenant, client id, client secret, Workflows URL, listener secret) that any number of nodes share. Sets live in Settings > Credentials (metadata `~/.nodra/ui/credentials.json`, secret values only in the encrypted box; no API ever returns a secret, only "stored"). A node picks one in its settings; a field typed on the node still wins. Merge order: **node field > credential set > saved node > default** (an empty node field inherits). Triggers get the merged values like other secrets and restart when the set is edited.

A package declares what its nodes take:

- A kind definition, `nodes/<name>.cred.json`: `{"kind": "teams", "title": "Microsoft Teams", "hint": "...", "fields": [{"name": "tenant_id", "label": "Tenant ID"}, {"name": "client_secret", "label": "Client secret", "secret": true}]}`. Settings > Credentials then offers to create one set for the installed package. Built-in kinds: `teams`, `smtp`, `git`, `http`, `s3`, `trino`, `sql`, `generic` (free key/values). `s3` and `trino` are described under "Lists of entries" below.
- In each `*.node.json`: `"credential": {"kind": "teams", "map": {"webhook_url": "webhook_url"}}`. `map` is `{set field: node field}`; without it the set fields with the same name as a node field are used. Several nodes (receive + send) can point at the same kind.

Git nodes have `username` / `token` fields (or the `git` set): they replace the Vault login for that call only. `io.request` takes the `http` set and `send.smtp` the `smtp` set. Exporting a work keeps only `credential_kind` / `credential_name` on each node, never values. Chat node cards (`@node:`) do not use sets.

### Lists of entries: S3 buckets and Trino

A credential kind field may be a **list** of entries instead of one value: `"type": "list"`, `"items"` = the fields of one entry, `"key"` = the entry field that names it. A package kind can use one too (`nodes/<name>.cred.json`):

```json
{"kind": "lake", "title": "Data lake", "fields": [
  {"name": "buckets", "label": "Buckets", "type": "list", "key": "name",
   "items": [{"name": "name", "label": "Name"}, {"name": "secret_key", "label": "Secret key", "secret": true}]}
]}
```

Two builtin kinds:

- `s3` "Object storage (S3 / MinIO / R2)": field `buckets`, one entry per bucket: `name` (how code refers to it, required), `bucket`, `endpoint_url` (empty = AWS), `region`, `access_key` (public), `secret_key` (secret), `path_style` (true for MinIO; on by default when an endpoint other than AWS is set).
- `trino`: `host`, `port`, `http_scheme` (`https` or `http`), `user`, `password` (secret), `catalog`, `schema`, `verify` (`true` or `false`). The Trino SQL node uses it.

- Secrets inside each entry are encrypted like any other secret (box key `cred:<set>:<field>:<entry id>:<entry field>`). Removing an entry removes its secrets too.
- A `generic` set may hold lists of entries too; keys that look like secrets inside an entry are encrypted.
- Settings > Credentials shows one card per entry (**Add** and remove). **Fill in from JSON** pastes a document into the set; nothing is saved until you press Save. The importer also reads other names: for a bucket, `public`, `public_key` or `access_key_id` become `access_key`; `secret`, `secret_access_key` or `aws_secret_access_key` become `secret_key`; `endpoint` or `url` become `endpoint_url`; `bucket_name` becomes `bucket`. A list may be given as an object keyed by entry name (`{"raw": {...}, "lake": {...}}`), and a kind with a single list field also takes the bare list.

### Node contract: inputs and outputs (standard keys)

To make nodes combine without glue, follow these conventions:

| Part | Rule |
| --- | --- |
| **Input** | `config` (the node's own fields), `input` / `inputs` (text and `data` of the parents), `workdir`. Declare each setting as a field; give it a `help` that says what an empty value does. |
| **`takes`** | `"takes": ["to", "subject", "body"]`: when such a field is EMPTY, the engine fills it from `{{data.<same name>}}` of the nodes before (a list becomes one value per line). This is how a Loop over `[{"to": ..., "subject": ...}]` drives a node without any `{{data.x}}` typed into fields. Secret fields are never filled. |
| **`templated`** | Fields in which `{{input}}`, `{{trigger}}`, `{{data.key}}` are expanded before the program starts. |
| **Output** | `output` (text for the next node), `data` (a dict that travels as `{{data.key}}`), `log`. List the keys in `"outputs"` so the editor suggests them. |
| **Standard data keys** | Mail: `to`, `cc`, `bcc`, `subject`, `body`, `attachments` (a list of file paths); mail triggers also give `from`, `from_name`, `received`, `message_id`. Files and repos: `path` (one pointer), `paths`. HTTP: `status`, `json`. Loop: `item`, `index`, `total`. Use these names so nodes of different packages fit together. |
| **Environment** | A node that needs libraries declares `[python] requires` in `nodra.toml`; the node then runs with the package's own venv. An OS limit goes in `[requires] os = [...]` so the install refuses other systems. A program still checks for what it needs and fails with the fix in `error`. |
| **Errors** | `{"ok": false, "error": "what to do"}`. Never include a secret. |

### Rules for good nodes

- Do one thing, take everything from `config` and `input`, and keep no state between calls (a trigger may keep state while it runs).
- Listen on `127.0.0.1` only. A trigger that opens a network port to other machines turns a message into remote control of the work.
- Validate untrusted text (message bodies are input from other people): never put `input` into a shell command or a file path unchecked. Hand it to Claude only as data in the prompt.
- Use `timeout`, exit non-zero on failure, and print nothing secret.
- Add a test: run your program with a sample stdin and assert on the last stdout line (see the unittest in the next section).

### Testing a node

```python
# tests/test_shout.py
import json, subprocess, sys, unittest

class ShoutTest(unittest.TestCase):
    def test_upper(self):
        p = subprocess.run([sys.executable, "nodes/shout.py"], input=json.dumps({"config": {"suffix": "!"}, "input": "hi"}),
                           capture_output=True, text=True, timeout=20)
        last = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertTrue(last["ok"])
        self.assertEqual(last["output"], "HI!")

if __name__ == "__main__":
    unittest.main()
```

Then `nodra dev validate`, `nodra install ./my-node --yes`, and add the node in a work to see it end to end.

## Data nodes

URL, header, body, path and ref fields of `io.request`, `io.read_file` and `git.read` are templated (`{{input}}`, `{{trigger}}`, `{{data.key}}`). `git.read` uses the git logins you saved with `nodra vault`: nodra's own git credential helper answers git exactly as in your terminal; no token is put in the URL or the work. Pointer nodes (`git.pull`, `io.path`) pass a path, never the content, so large files never go through a prompt; `ai.claude` gets the folders with `--add-dir` and opens the files itself. End a Claude node that creates a file with `OUTPUT: /full/path`.

## Trino SQL (`db.trino`)

Runs SQL on Trino (or Presto) over its HTTP protocol. Stdlib only: nothing to install. Group **Data**.

- **Statements.** Several statements separated by `;` run one after another in ONE session, so `USE`, `SET SESSION`, `START TRANSACTION` and `PREPARE` carry over, as in the Trino CLI. A `;` inside quotes or comments does not split. A line `-- %% name` names the next statement; otherwise its first three words are the name. Each statement is a step in the node log (`step 2/3 name: ok (0.4s, 25 rows)`). The LAST statement that returns rows is the result.
- **Result as.** `table` (markdown, the first **Max rows**, default 1000), `json`, `csv`, or `path`: ALL rows are streamed to a file in the node's folder (format `csv`, `json` or `jsonl`, name from **File name**) and the next node gets the path. Use `path` for big results.
- **Data for later nodes.** `{{data.columns}}`, `{{data.rows}}` (up to Max rows, as objects), `{{data.row_count}}`, `{{data.truncated}}`, `{{data.path}}`, `{{data.steps}}`.
- **Login.** The `trino` credential set (see "Lists of entries"). A field typed on the node overrides the set. A password is only sent over https: http with a password is an error.
- **Timeouts.** 502, 503 and 504 are retried. The **Timeout** field (default 600 s) also cancels the query on the cluster.
- **Text in the SQL.** `{{input}}` and `{{data.x}}` are pasted into the SQL as they are. Quote values yourself, and never paste untrusted text into a statement.

```sql
USE hive.sales;
-- %% daily orders
SELECT order_day, count(*) AS orders FROM orders WHERE order_day = DATE '{{data.day}}' GROUP BY order_day
```

## SQL database (`db.sql`, SQLAlchemy)

SQL on any database SQLAlchemy reaches. Group **Data**. The Trino node above stays for Trino without any driver.

- **Database** (driver): `postgresql` (psycopg), `mssql` (pymssql), `mssql-odbc` (pyodbc; also needs Microsoft's ODBC Driver 18 on the system), `oracle` (oracledb thin mode, no Oracle client), `trino`, `mysql` (pymysql), `sqlite` (nothing to install), `duckdb` (duckdb-engine), or `other` with a full **SQLAlchemy URL**.
- **Login.** A `sql` credential set (driver, host, port, user, password, database, options, url), or the node's fields; a typed field wins. **Database** is the service name for Oracle, the file for SQLite / DuckDB, `catalog/schema` for Trino. **Options** = extra URL parameters (`sslmode=require&...`). Password and URL are secret fields.
- **Read and write with.** `native` (SQLAlchemy rows, nothing extra to install), `pandas` or `polars`. The frame library reads the LAST query (SELECT, WITH, SHOW ...) and writes **Write table**; earlier statements run through SQLAlchemy.
- **Statements.** Split on `;` outside quotes and comments, `-- %% name` names one (same as the Trino node). They run on ONE connection, each committed; a failing one is rolled back and stops the node with its step name.
- **Result as.** `table` (markdown), `json`, `csv` or `path`: a `csv`, `json`, `jsonl` or `parquet` file in the node folder (native csv / json / jsonl are streamed; parquet needs pyarrow, or polars).
- **Write table.** When set, the rows coming in are written into that table BEFORE the SQL runs: `{{data.rows}}` of the node before, a JSON list as the input, or a csv / json / jsonl / parquet path (`{{data.path}}` or the input). **When the table exists**: `append`, `replace` or `fail`. Native writing creates a missing table from the values (integer, float, boolean, date, text).
- **Data for later nodes.** `{{data.rows}}`, `{{data.columns}}`, `{{data.row_count}}`, `{{data.truncated}}`, `{{data.path}}`, `{{data.written}}`, `{{data.steps}}`, `{{data.dtypes}}` (frames).
- **Imports are lazy.** Nothing beyond the stdlib is imported until it is needed. A missing package fails the node with the exact command, e.g. `.../envs/data/bin/python -m pip install oracledb`.

The same in your own Python code (any code node, or a script with `PYTHONPATH=$(nodra work lib)`):

```python
import nodra_data as ad
eng = ad.engine("warehouse")                    # a 'sql' credential set granted to the node, a SQLAlchemy URL, or a dict of fields
df = ad.read_sql("select * from orders where day = :d", eng, frame="polars", params={"d": data["day"]})
ad.write(df, "orders_copy", eng, if_exists="replace")
pd = ad.need("pandas")                          # lazy import; raises ad.Missing with the pip command
```

## Python environments of code nodes

`code.python`, `db.sql`, `etl.spark` (and package nodes with an `env` field or `packages`) show an **Environment** box in the Inspector:

- **Which Python.** Empty = the UI's Python (Spark: `$PYSPARK_PYTHON` first). A NAME, e.g. `data` or `spark` = a separate environment in `~/.nodra/ui/envs/<name>`, created on the first install and shared by every node that names it. Or a path to a python or a venv folder. The node's program runs with that interpreter.
- **What it needs.** From the settings (SQL: sqlalchemy, the driver of the chosen database, pandas / polars when picked, pyarrow for parquet; Spark: pyspark, plus Java), from the code's imports (the stdlib and `nodra_vault` / `nodra_data` are skipped) and from a package node's `packages`. The check runs a tiny probe in that Python (nothing is imported) and shows each package with its version.
- **Install.** One click installs what is missing (`python -m pip install`, or `uv pip` when the env has no pip; the log streams in the box). The box also shows the one command to run yourself, and `nodra work env install <work>` for the whole work. Java is never installed for you: the box shows the command for your system (`brew install openjdk@17`, `apt install openjdk-17-jre-headless`, `winget install Microsoft.OpenJDK.17`).
- A Python that refuses pip (a system Python marked EXTERNALLY-MANAGED) is reported: pick **New environment…**. Only package names pass (an optional `[extra]` and version); options, URLs and paths are refused.

## Magic ask

Every node with settings has a **Magic ask** box at the top of its settings. Describe what the node should do ("orders per country from Oracle for {{data.day}}, read with polars"): a model fills in the fields, code and SQL included, and shows what it would change. Nothing changes until **Apply** (one undo step). In the large code editor the same box changes only that field, and can focus on the selected lines.

- It knows the node's guide, its fields and their current values, the `{{data.x}}` keys of the nodes before it and the last run of the node (so "fix the error" works).
- It never receives secret fields, credential sets or the vault, and it never fills secret fields or the environment.
- Its answer is checked: unknown fields, a select value that is not an option, and non-numbers are dropped and listed.
- Model: a direct API call (the Free chat credentials) when an API key is set, else a one-shot `claude -p` without tools.

## Code editor: run and preview

Code fields use the colour editor (undo / redo, find and replace, Tab indents) in the Inspector. **Expand** opens it full screen, with Magic ask on top and, for nodes that run a program, **Run** (Cmd/Ctrl+Enter) and **Run selection** (Shift+Cmd/Ctrl+Enter: only the selected text, e.g. one SQL statement). Long text fields (Spark settings, headers ...) have **Expand** too, without Run.

- Run uses the settings as they are in the editor, saved or not, with the stored secrets, credential set, saved node and granted sets of the node, exactly like a real run. It runs for real: a SQL write writes, a mail node sends.
- The **Input** tab sets `{{input}}` (taken from the last run of the node when there is one) and `{{data.x}}` (a JSON object). **Max rows** is capped at 500 for a preview.
- **Result** shows tables for row lists (`rows`, Spark `preview` ...), the rest of the data as JSON, the text output, and files written. **Log** streams the node log; Stop ends it.
- These runs live in `~/.nodra/ui/runs/try/` (the newest 30 are kept) and never appear in a work's history.

## Spark job (`etl.spark`)

PySpark code in steps, on a Spark cluster or a local Spark. Group **Code**.

- **Mode.** `session` builds a SparkSession in the node. **Master** is `local[*]` (default), `spark://host:7077`, `yarn` or `k8s://...`. `spark-submit` hands the job to `spark-submit`, found through `SPARK_HOME` or `PATH`, or through the **spark-submit path** field.
- **Python.** The node's **Python environment** (see "Python environments"), else `$PYSPARK_PYTHON`, else the UI's Python. The Environment box checks pyspark and Java; when pyspark is missing the node fails and prints the pip command to run.
- **Storage.** Pick an `s3` credential set. EVERY bucket of it is configured for `s3a://`, one by one (Hadoop `fs.s3a.bucket.<bucket>.endpoint`, `access.key`, `secret.key`, `path.style.access`, `endpoint.region`). The job sets them itself, so no key is on a command line.
- **Packages.** `auto` (default) adds the `org.apache.hadoop:hadoop-aws` version that matches the Hadoop bundled with your pyspark (session mode, when buckets are granted). Empty = none. Or give Maven coordinates.
- **Spark settings.** `key=value` per line. Never put a secret here.
- **Code.** Split into steps with `# %%` lines, as in `code.python`. The steps see `spark`, `sc`, `s3a(bucket_name, path)` (gives `s3a://bucket/path`), `buckets` (name -> bucket), `vault`, `data` (data of the nodes before, plus the Arguments JSON field), `inputs`, `text`, `workdir` and `result`. A dict in `result` is the node's output; a DataFrame in it becomes its first **Max rows** rows.
- **Output.** `{{data.<key>}}` for each key of `result`, plus `{{data.steps}}`.
- **Stop.** Stop, and the **Timeout** (default 1800 s), also end the JVM.

## Python function node (`code.python`)

Write one function in the node's code box. Its argument and its return must be typed as a pydantic `BaseModel` or a `dict` / `Dict[...]` / `TypedDict`; the node refuses anything else with a message that says what to annotate.

```python
from pydantic import BaseModel

class In(BaseModel):
    text: str
    times: int = 2

class Out(BaseModel):
    result: str

def main(args: In) -> Out:
    return Out(result=args.text * args.times)
```

- Entry point: `main`, else `run`, else the last function defined. One argument at most.
- Input is parsed for you: `data` of the nodes before, then the input text when it is a JSON object, then the optional **Arguments** JSON field.
- Output: the return becomes JSON text; every top-level key is `{{data.key}}` for later nodes. `print()` goes to the run log.
- Runs with the chat's Python in its own process (timeout field, default 60 s, max 3600). A missing module is reported with the pip command.

**Several steps.** `# %% name` lines split the code into steps (cells, as in Jupyter or VS Code). The steps run in order in ONE namespace, each timed in the log. The first failing step stops the run, and the log names it with its line number. The steps see `data`, `inputs`, `text`, `workdir`, `vault` and `result` (a dict = the node's output). If the steps define `main(args)` or `run(args)`, it is still called afterwards with the typed contract. Code without `# %%` works exactly as before.

```python
# %% extract
rows = data.get("rows") or []
# %% transform
total = sum(r["n"] for r in rows)
# %% load
result["total"] = total
```

## nodra_vault: logins and buckets in node code

`nodra_vault` is a stdlib-only Python module. Every node program gets it on `PYTHONPATH`; `nodra work lib` prints its folder.

```python
import nodra_vault as vault
raw = vault.bucket("raw")                 # entry name or bucket name
raw.uri("in/*.csv")                       # s3a://raw-data/in/*.csv  (raw.uri(p, "s3") for s3://)
pd.read_csv(raw.uri("x.csv", "s3"), storage_options=raw.storage_options())
raw.boto3().list_objects_v2(Bucket=raw.bucket)   # needs boto3
raw.env()                                 # AWS_* variables
vault.s3a_conf()                          # spark.hadoop.fs.s3a.bucket.* for every visible bucket
db = vault.credential("warehouse")        # by name or id: db["password"], db.kind, db.name
vault.sets(kind="s3"); vault.info()       # what this code can see (no values)
vault.git_login("github.com")             # outside node runs only: the nodra Vault login of a git host
```

- **What a node sees.** Only the sets GRANTED to that node: its own credential set, plus the ones ticked under **Code may read (nodra_vault)** in the node's settings (work file field `vault: [set ids]`). Nodes that can get grants: Python, Spark, Trino, and package nodes with `"vault": true` in their `*.node.json`.
- **Handover.** Granted sets go to the program in a private 0600 temp file (`NODRA_VAULT_FILE`), deleted when the node ends. Their secrets are masked in the node log.
- **Git logins** are not readable from a node run. Outside a node run, in your own scripts (`PYTHONPATH=$(nodra work lib) python my_etl.py`), every set on the machine is readable.
- `repr()` and `print()` of a set or bucket show `***` for secrets.
- This is least privilege for honest code, **not a sandbox**. A shared work's code runs as you, so read it before you switch it on.

## Memory, history and Output

- **Memory** (`flow.memory`): `source` = `work` (this work's earlier runs), `chat` (the last messages of a chat) or `other` (another work's runs); `limit` items (1-50), `chars` cap, `mode` = prepend or memory only. A Memory block that an earlier run added to its result is cut out again, so memory does not snowball.
- **History limit**: the Works toolbar has a *History* number (1-500, default 40): older runs are deleted, and Memory nodes only see what is kept.
- **Inputs of a work.** The *Start: manual* node has an **Inputs** field, one input per line: `name|Label|type|options or default|*` (types `text`, `textarea`, `number`, `select` with comma separated options, `checkbox`; `*` = required). Example: `topic|Topic|text||*` and `level|Level|select|easy,hard`. Later nodes read `{{data.topic}}`.
- **Output.** Add an **Output** node (heading + markdown template with `{{input}}`, `{{data.x}}`). Its text is the work's answer; without one the last text any node produced is used.
- **Run a work from a chat.** Type `/` in a chat: every work is listed as `/work:<title>`. Pick one and add the text that should start it; the form for the inputs appears when there are any.

## Loop and End loop

`flow.loop` repeats every node after it once per item of a list, one item after the other:

- **The list**: field *The list* (default `{{input}}`), written as `lines`, `comma`, `regex` (separator) or `json` (a list of strings or objects). Repeated items are skipped unless unticked. `limit` (default 100, max 1000), `delay` between items, `on_error` = `stop` (default) or `continue`.
- **Inside a pass**: `{{input}}` and `{{data.item}}` = the item, `{{data.index}}` (from 1), `{{data.total}}`. An object item also puts its keys in `{{data.<key>}}`, so `[{"to": "a@x.com", "body": "Hi A"}]` feeds a mail node through `takes`.
- **End loop (collect)** runs ONCE after the last pass: `{{input}}` = the last text of each pass joined, `{{data.results}}`, `{{data.count}}`, `{{data.failed}}`.
- Not supported: a loop inside a loop. Passes run in order.

## Saved nodes

Works > **Saved nodes** is where you set a node up once (a mail server with its login, an HTTP API with its token, a Claude task with a fixed prompt) and give it a name. In a work's Inspector, **Save as saved node** keeps the current node's settings (stored logins included).

- **Use it as it is**: Add node > *Saved nodes* puts a node `{"type": <type>, "preset": <id>, "config": {}}` on the canvas. Each field it leaves empty takes the saved node's value at run time, so editing the saved node changes every work that uses it.
- **Change it for one work**: type in a field of that node (marked *saved* while it inherits; *reset* goes back). **Detach** copies the settings into the node and drops the link.
- **Storage**: `~/.nodra/ui/presets.json`; secret values in the encrypted box. A deleted saved node makes the node fail with "was deleted" until you pick another one.
- Exporting a work writes the saved node's settings into the file and drops the link; logins never leave the machine.

## Workflows as packages

Package type `workflow`: no code, just `works/*.work.json` (the work without its id; it is added switched off). Works editor > **Download** saves either the single work (`<name>.work.json`) or a package zip (`nodra.toml`, `README.md`, `works/<name>.work.json`), with every secret field emptied, logins reduced to their kind and any `pkg:` node packages listed under `[requires] packages`. Unzip the package into a source's `packages/` (see [packages.md](packages.md)), or install it with `nodra install <file.zip>` (Packages > From zip in the chat). To import, use Works > *Workflows* > **Import file** (a `.work.json` or a workflow zip), or pick from *Samples*, *Installed* or *Available*; fill in the secret fields yourself. Local nodes export and import the same way, as zips, from the Nodes dialog. Risky nodes (files, web requests, git, Claude with checks bypassed, node packages) are listed when someone adds a workflow, which always arrives switched off.

## Running a node from a chat

Type `@node:<type>` in a chat (the `@` menu lists every action node that has a program). The assistant is told the node's fields: it fills them from your message, asks for only the missing required ones with a form, and then answers with a ```node block. The card shows the values (editable), secret fields as password boxes (used for that run only, never sent to the model), and an **Approve and run** button: nothing runs until you approve it, except in **bypass** permission mode. The output appears in the card and goes back to the chat so the assistant can continue. `@work:<id>` works the same for a workflow. Runs are recorded in `~/.nodra/ui/runs/chat/` (secret values left out) and listed on the Works page under **Runs from chats**. Trigger, Claude and flow nodes are not runnable on their own.

## Sharing a work: no credentials, its files come along

- **Export** (Download in the chat, or `nodra work export W -o DIR`) writes `<name>.work.json` and a `<name>.files/` folder. It removes secret values, credential set links (kept as `credential_kind` / `credential_name`), code grants (kept as `vault_kinds: [{kind, name}]`) and machine folders: a Claude node's working folder is left empty with `folder_hint` = the folder's name, so the installer is asked for one. Saved nodes are written in with their non-secret settings.
- **Files come along.** Files that prompts and fields mention are copied into `<name>.files/` and rewritten to `@file:{{work.files}}/<name>`: `@file:` and `@folder:` (absolute, or relative to the node's working folder), `@knowledge:` notes (snapshotted as `knowledge-<name>.md`; `--no-notes` leaves them out) and mail `attachments` lines.
- **Never bundled:** private paths (keys, `.env`, `~/.ssh`, `~/.nodra` except `workingspace` and `knowledge`), files over 5 MB, folders beyond 200 files or 20 MB, and files outside your home folder. The skipped ones are listed.
- **On import** the files go to `~/.nodra/workingspace/works/<work id>/files/`, which is `{{work.files}}` in prompts and fields. Claude and Free chat nodes read `@file:` and `@folder:` mentions in their prompts too, and a Claude node may open the work's files folder.
- **Python environments travel as requirements.** A code node carries `requires` (the pip packages its settings and code need). A managed environment NAME (`data`) is kept and made on the other machine by the first install; a path to a python of your machine is dropped (`env_hint` keeps its name).
- **Credentials on import** are bound by kind: the set with the same name first, else the only set of that kind, for the node's set and for its code grants. What is still missing is listed as `needs`: `credential`, `vault`, `folder`, `secret`, `env` (packages to install, with the command) or `system` (Java for Spark). `nodra work setup W` offers to install the packages (in a terminal; from a script only with `--install` or `--env NAME`), and `nodra work env install W [--env data]` does it in one command.

## Installs that ask questions

The install dialog opens a terminal by default. It runs `nodra install NAME` in a pseudo-terminal, so an install script that asks something on stdin can be answered in the page. Windows has no pty: untick *Open a terminal* there.

## Slash commands from packages

Typing `/` in the chat composer opens a menu with the chat's own commands (`/compact`, `/btw`, `/clear`, `/model`, `/effort`, `/mode`, `/context`, `/canvas`), everything Claude Code knows, and commands from installed Nodra packages. A package adds one with a file `slash/<name>.slash.json`:

```json
{"name": "standup", "description": "Summarise yesterday's work", "prompt": "Summarise what I did yesterday from git log. Focus: $ARGUMENTS"}
```

`/standup backend` sends the `prompt` with `$ARGUMENTS` replaced by `backend`. `name` is letters, digits, `. _ - :`; `prompt` is at most 8000 characters. A package command never runs code: it only expands to a prompt. (A command that needs code is a Works node.)

## Slides, documents and themes

Claude writes one `.html` file; the canvas (Files > click the file) recognises it and shows it natively.

| Kind | Marker | Shown as | Export |
| --- | --- | --- | --- |
| Slides | `<meta name="nodra-kind" content="slides">` or `<section class="slide">` blocks (1280x720 px each) | one slide at a time, scaled to fit | PowerPoint `.pptx`, PDF, HTML |
| Document | `<meta name="nodra-kind" content="doc">` or `<article class="doc">` | a page | Word `.docx`, PDF (A4), Markdown, HTML |

The `nodra-slides` package teaches Claude the format. **Themes** (Settings > Themes): name, six colours and two fonts, plus notes for Claude; import from a PowerPoint reads its theme in the browser. Mention one in a chat with `@theme:<id>`.

## Run works without the chat (`nodra work`)

`nodra work` is the Works engine on the command line, for a terminal or a server. It uses the same files as the chat, so a work designed in the chat runs here, and a work made here opens in the chat. It runs the chat folder of this checkout (`chat/`), so nothing else needs installing. Every command is in [cli.md](cli.md).

Run a shared workflow on a server:

1. Clone (or unzip) Nodra and run `python3 install.py`.
2. `nodra work pull workflow-sales-etl` installs that workflow package from your sources and adds its works, switched off (or `nodra work import FILE.work.json`).
3. `nodra work setup sales-etl --creds creds.json --env data` fills in its credential sets, folders and secret fields (or answer the prompts; `nodra work cred template s3` prints a skeleton), then installs the Python packages its SQL / Spark / Python nodes need into the environment `data`.
4. `nodra work run sales-etl --input day=2026-10-31` tries one run with a live step log. Then `nodra work enable sales-etl && nodra work serve --bg` fires its triggers in the background.

Only ONE process on a machine fires cron and package triggers: the chat or `nodra work serve`, never both. The lease is `~/.nodra/ui/scheduler.json`, and the Works page says when `nodra work serve` holds it. `serve --bg` runs as the supervised service `nodra-works` (`nodra run logs nodra-works -f`, `nodra run stop nodra-works`). Manual runs, chat cards and `nodra work run` run in whatever process starts them.

## Where things are stored

| What | Where |
| --- | --- |
| Works | `~/.nodra/ui/works/<id>.json` (nodes, edges, `enabled`; secrets replaced by a marker) |
| Runs | `~/.nodra/ui/runs/<work>/<run>.json`, last 40 per work |
| Credential sets | `~/.nodra/ui/credentials.json` (values in `secrets.bin`) |
| Node secrets | `~/.nodra/ui/secrets.bin` (encrypted), key `~/.nodra/ui/.key` (0600) |
| Saved nodes | `~/.nodra/ui/presets.json` |
| Preferences | `~/.nodra/ui/prefs.json` |
| Webhook key | `~/.nodra/ui/.hooks.key` (0600); tokens survive restarts |
| A run's chat and files | `~/.nodra/workingspace/sessions/<id>` |
| Files of a shared work | `~/.nodra/workingspace/works/<work id>/files/` (`{{work.files}}`) |
| Who fires triggers (lease) | `~/.nodra/ui/scheduler.json` (the chat or `nodra work serve`) |

## Claude sign-in with an `apiKeyHelper`

If `~/.claude/settings.json` sets `apiKeyHelper` (a command that prints a key, often after an OAuth sign-in whose token the helper stores itself), Claude Code runs it on its own. The chat adds a check before every chat turn and every Claude node: if the helper fails, the chat shows **Sign in** (Settings has the same). The key the helper prints is never stored, logged or sent to the browser. A helper that needs a real terminal must be run there once.

## Free chat and MCP servers

Free chat can use stdio MCP servers; see [mcp.md](mcp.md) for writing one and for the MCP page in the chat.
