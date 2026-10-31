import os
import tempfile
import unittest
from unittest import mock

from nodra.cli import installer, knowledge, paths
from nodra.core import manifest as M, templates
PACKAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages")
BOT = os.path.join(PACKAGES, "nodra-bot")


class BotTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.dict(os.environ, {"NODRA_HOME": self.d})
        p.start()
        self.addCleanup(p.stop)

    def test_manifest_and_lint(self):
        m = M.parse(open(os.path.join(BOT, "nodra.toml"), encoding="utf-8").read())
        self.assertEqual(m["package"]["type"], "bot")
        self.assertEqual(m["bot"]["run"], "bot/run.py")
        self.assertEqual([e["name"] for e in m["bot"]["env"]], ["ANTHROPIC_API_KEY", "BOT_MODEL", "BOT_HARNESS"])
        self.assertEqual(M.lint(m, BOT)[0], [])
        bad = M.parse('[package]\nname="x-bot"\nversion="1.0.0"\ntype="bot"\n[bot]\nenv = [{name="1bad"}, "OK_NAME", 5]\n')
        self.assertEqual([e["name"] for e in bad["bot"]["env"]], ["OK_NAME"])
        self.assertTrue(M.lint(bad, self.d)[0])

    def test_template_renders_valid_bot(self):
        text, files, execs = templates.render("bot", "demo-bot")
        m = M.parse(text)
        root = tempfile.mkdtemp()
        for p, c in files.items():
            os.makedirs(os.path.dirname(os.path.join(root, p)), exist_ok=True)
            open(os.path.join(root, p), "w").write(c)
        self.assertEqual(M.lint(m, root)[0], [])
        self.assertIn("bot/run.py", execs)

    def test_env_file_kept_and_missing_required_blocks_run(self):
        m = M.parse(open(os.path.join(BOT, "nodra.toml"), encoding="utf-8").read())
        installer.write_bot_files("nodra-bot", m, BOT)
        envf = os.path.join(paths.p("bots", "nodra-bot"), ".env")
        open(envf, "a").write("# mine\n")
        installer.write_bot_files("nodra-bot", m, BOT)
        self.assertIn("# mine", open(envf).read())
        self.assertIn("ANTHROPIC_API_KEY", installer.read_env(envf))
        self.assertTrue(os.path.isfile(os.path.join(paths.p("bots", "nodra-bot"), "mcp.json")))

    def test_knowledge_names(self):
        for bad in ("../x", "A b", ""):
            with self.assertRaises(ValueError):
                knowledge._file(bad)
        self.assertTrue(knowledge._file("soul")[1].endswith("soul.md"))

    def test_cron_due(self):
        import sys
        sys.path.insert(0, os.path.join(BOT, "bot"))
        from harness import cron
        self.assertTrue(cron.due({"when": "every 5m"}, 1000, 600))
        self.assertFalse(cron.due({"when": "every 5m"}, 1000, 800))
        self.assertFalse(cron.due({"when": "nonsense"}, 1000, 0))


class HarnessTest(unittest.TestCase):
    """memory store + executor layer of the sample bot (imported straight from the package)."""
    def setUp(self):
        import importlib, sys
        self.home = tempfile.mkdtemp()
        env = {"NODRA_BOT_HOME": self.home, "NODRA_KNOWLEDGE_DIR": os.path.join(self.home, "k"), "NODRA_BOT_MCP": os.path.join(self.home, "mcp.json"),
               "NODRA_BOT_DIR": self.home, "BOT_HARNESS": "builtin"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        sys.path.insert(0, os.path.join(BOT, "bot"))
        self.addCleanup(sys.path.remove, os.path.join(BOT, "bot"))
        for m in [m for m in sys.modules if m == "harness" or m.startswith("harness.")]:
            del sys.modules[m]
        self.H = importlib.import_module("harness.agent")
        self.mem = importlib.import_module("harness.memory")
        self.ex = importlib.import_module("harness.executors")

    def test_store_facts_recall_forget_compact(self):
        st = self.mem.Store()
        self.assertEqual(st.remember("The user prefers tabs over spaces"), "remembered")
        self.assertEqual(st.remember("the user prefers TABS over spaces"), "already known")
        st.remember("Project deadline is Friday")
        self.assertEqual([r["text"] for r in st.recall("what about tabs?")], ["The user prefers tabs over spaces"])
        self.assertIn("Project deadline", st.prompt_block("deadline"))
        self.assertEqual(st.forget("deadline"), "forgot 1")
        for i in range(25):
            st.log("user", "q%d" % i)
            st.log("assistant", "a%d" % i)
        self.assertTrue(st.compact(lambda t: "SUMMARY", keep=10, limit=40))
        self.assertEqual(st.summary(), "SUMMARY")
        rows = st.recent(100)
        self.assertEqual(rows[0]["role"], "user")
        self.assertLessEqual(len(rows), 10)

    def test_executor_custom_harness_manages_memory(self):
        a = self.H.Agent()
        a.bot.executors["echo"] = lambda text, system: "pong\nREMEMBER: likes tea\n"
        a.executor = self.ex.make(a, "echo")
        self.assertEqual(a.ask("ping"), "pong")
        self.assertEqual([r["text"] for r in a.memory.facts()], ["likes tea"])
        self.assertEqual([r["role"] for r in a.memory.recent()], ["user", "assistant"])
        self.assertIn("likes tea", a.system("", "tea"))

    def test_command_harness_and_unknown(self):
        a = self.H.Agent()
        with mock.patch.dict(os.environ, {"BOT_HARNESS_CMD": "cat"}):
            self.assertEqual(self.ex.make(a, "command").ask("hello", keep=False), "hello")
        with self.assertRaises(RuntimeError):
            self.ex.make(a, "nope")
        with mock.patch.object(self.ex.shutil, "which", return_value=None), self.assertRaises(RuntimeError):
            self.ex.make(a, "claude").ask("x", keep=False)

    def test_builtin_loop_with_fake_model(self):
        llm = __import__("harness.llm", fromlist=["x"])
        seq = [{"stop": "tool_use", "content": [{"type": "tool_use", "id": "1", "name": "remember", "input": {"text": "name is Bao"}}]},
               {"stop": "end_turn", "content": [{"type": "text", "text": "done"}]}]
        with mock.patch.object(llm, "complete", side_effect=seq):
            a = self.H.Agent()
            self.assertEqual(a.ask("remember my name"), "done")
        self.assertEqual([r["text"] for r in a.memory.facts()], ["name is Bao"])


TEAMS = os.path.join(PACKAGES, "nodra-teams-bot")


class TeamsBotTest(unittest.TestCase):
    def setUp(self):
        import importlib, sys
        self.home = tempfile.mkdtemp()
        env = {"NODRA_BOT_HOME": self.home, "NODRA_KNOWLEDGE_DIR": os.path.join(self.home, "k"), "NODRA_BOT_MCP": os.path.join(self.home, "mcp.json"),
               "NODRA_BOT_DIR": TEAMS, "BOT_HARNESS": "builtin", "NODRA_PACKAGE_DIRS": os.path.join("x", "nodra-bot"), "NODRA_BASE_BOT": os.path.join(BOT, "bot")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        paths_ = [os.path.join(TEAMS, "bot"), os.path.join(BOT, "bot")]
        sys.path[:0] = paths_
        self.addCleanup(lambda: [sys.path.remove(x) for x in paths_])
        for m in [m for m in sys.modules if m.split(".")[0] in ("harness", "teamsbot")]:
            del sys.modules[m]
        self.core = importlib.import_module("teamsbot.core")
        self.app = importlib.import_module("teamsbot.app")
        self.base = importlib.import_module("teamsbot.base")

    def test_manifest(self):
        m = M.parse(open(os.path.join(TEAMS, "nodra.toml"), encoding="utf-8").read())
        self.assertEqual(m["package"]["type"], "bot")
        self.assertEqual(m["requires"]["packages"], ["nodra-bot>=1.1.0"])
        self.assertIn("microsoft-teams-apps", m["python"]["requires"])
        self.assertEqual(M.lint(m, TEAMS)[0], [])
        self.assertTrue(all(not e["required"] for e in m["bot"]["env"]))
        for t in ("general", "helpdesk", "standup", "meeting-notes"):
            self.assertTrue(os.path.isfile(os.path.join(TEAMS, "bot", "tasks", t + ".md")), t)

    def test_base_bot_found(self):
        self.assertTrue(self.base.base_bot_dir().endswith(os.path.join("nodra-bot", "bot")))
        with mock.patch.dict(os.environ, {"NODRA_BASE_BOT": "", "NODRA_PACKAGE_DIRS": "", "NODRA_HOME": self.home}), self.assertRaises(SystemExit):
            self.base.base_bot_dir()

    def test_clean_and_allow_list(self):
        c = self.core
        self.assertEqual(c.clean("<at>Bot</at> hello\nworld"), "hello\nworld")
        self.assertEqual(c.clean("&nbsp;<at>Bot</at>"), "")
        self.assertTrue(c.allowed({"name": "x"}, ""))
        self.assertTrue(c.allowed({"name": "Bob", "id": "1"}, "ada@x.org, bob"))
        self.assertFalse(c.allowed({"name": "Eve", "id": "9"}, "ada@x.org,bob"))
        self.assertFalse(c.allowed({}, "bob"))

    def test_task_selection_and_override(self):
        with mock.patch.dict(os.environ, {"TEAMS_TASK": "helpdesk"}):
            self.assertIn("helpdesk", self.core.task_text())
        with mock.patch.dict(os.environ, {"TEAMS_TASK": "../../etc/passwd"}):
            self.assertIn("team assistant", self.core.task_text())          # sanitised -> general
        open(os.path.join(self.home, "task.md"), "w").write("MY TASK")
        self.assertEqual(self.core.task_text(), "MY TASK")

    def test_router_per_chat_memory_commands_and_allow(self):
        agent, router = self.app.build()
        seen = []
        agent.bot.executors["fake"] = lambda text, system: (seen.append((text, system)), "ok\nREMEMBER: " + text[:20])[1]
        agent.executor = __import__("harness.executors", fromlist=["x"]).make(agent, "fake")
        who = {"id": "1", "name": "Ada"}
        self.assertTrue(router.handle("chatA", who, "<at>Bot</at> deploy friday").startswith("ok"))
        self.assertIn("Ada: deploy friday", seen[0][0])
        self.assertIn("team assistant", seen[0][1])
        self.assertEqual(len(router.store("chatA").facts()), 1)
        self.assertEqual(router.store("chatB").facts(), [])
        self.assertIn("deploy friday", router.handle("chatA", who, "/memory"))
        self.assertIn("not remembered", router.handle("chatB", who, "/memory"))
        self.assertIn("/reset", router.handle("chatA", who, "/help"))
        self.assertIn("Ada", router.handle("chatA", who, "/whoami"))
        self.assertIn("team assistant", router.handle("chatA", who, "/about"))
        router.handle("chatA", who, "/reset")
        self.assertEqual(router.store("chatA").recent(), [])
        with mock.patch.dict(os.environ, {"TEAMS_ALLOWED": "bob"}):
            self.assertIn("allow-list", router.handle("chatA", who, "hi"))
        self.assertIn("Send me", router.handle("chatA", who, "<at>Bot</at>"))

    def test_extension_command_and_tool(self):
        os.makedirs(os.path.join(self.home, "ext"))
        import shutil
        shutil.copy(os.path.join(TEAMS, "bot", "ext_examples", "helpdesk.py"), os.path.join(self.home, "ext", "helpdesk.py"))
        agent, router = self.app.build()
        self.assertIn("open_ticket", [t["name"] for t in agent.tool_specs()])
        self.assertIn("ticket opened: printer", router.handle("c", {"name": "Ada"}, "/ticket printer"))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "tickets.jsonl")))
        self.assertIn("/ticket", router.handle("c", {"name": "Ada"}, "/help"))

    def test_serve_requires_credentials(self):
        agent, router = self.app.build()
        with mock.patch.dict(os.environ, {"CLIENT_ID": "", "CLIENT_SECRET": "", "TEAMS_LOCAL": ""}), self.assertRaises(SystemExit):
            self.app.serve(router)
        self.app.info(agent, router)

    def test_sender_of_is_defensive(self):
        class F: id, name, aad_object_id = "u1", "Ada", "aad1"
        class A: from_ = F()
        self.assertEqual(self.app.sender_of(A())["aad_id"], "aad1")
        self.assertEqual(self.app.sender_of(object())["id"], "")


    def test_background_task_posts_only_the_result(self):
        agent, router = self.app.build()
        posted, seen = [], []
        router.notify = lambda conv, text: posted.append((conv, text))
        agent.bot.executors["fake"] = lambda text, system: (seen.append((text, system)), "RESULT 42\nREMEMBER: not stored")[1]
        with mock.patch.dict(os.environ, {"TEAMS_TASK_HARNESS": "fake"}):
            ack = router.handle("chatA", {"name": "Ada"}, "/task compute the answer")
            self.assertIn("Task #1 started", ack)
            self.assertEqual(posted, [])                                      # nothing but the ack until the job ends
            router.jobs.wait(10)
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0][0], "chatA")
        self.assertIn("Task #1 done", posted[0][1])
        self.assertIn("RESULT 42", posted[0][1])
        self.assertNotIn("REMEMBER", posted[0][1])
        self.assertIn("background task", seen[0][1])
        self.assertEqual(seen[0][0], "compute the answer")
        self.assertIn("#1 **done**", router.handle("chatA", {"name": "Ada"}, "/tasks"))
        self.assertIn("No tasks", router.handle("chatB", {"name": "Ada"}, "/tasks"))
        self.assertIn("Usage", router.handle("chatA", {"name": "Ada"}, "/task"))

    def test_background_task_failure_limit_and_restart(self):
        import threading
        agent, router = self.app.build()
        posted = []
        router.notify = lambda conv, text: posted.append(text)
        gate = threading.Event()
        agent.bot.executors["slow"] = lambda text, system: (gate.wait(5), "late")[1]
        def boom(text, system): raise RuntimeError("no luck")
        agent.bot.executors["boom"] = boom
        with mock.patch.dict(os.environ, {"TEAMS_TASK_HARNESS": "slow", "TEAMS_TASK_MAX": "1"}):
            router.jobs.slots = threading.BoundedSemaphore(1)
            router.handle("c", {}, "/task one")
            self.assertIn("maximum", router.handle("c", {}, "/task two"))
            gate.set()
            router.jobs.wait(10)
        with mock.patch.dict(os.environ, {"TEAMS_TASK_HARNESS": "boom"}):
            router.handle("c", {}, "/task three")
            router.jobs.wait(10)
        self.assertTrue(any("failed" in m and "no luck" in m for m in posted))
        j = router.jobs.all()[-1]
        j.update(state="running")
        router.jobs._save(j)
        again = self.core.Jobs(router)
        self.assertEqual(again.all()[-1]["state"], "interrupted")

    def test_missing_task_cli_falls_back_to_bot_harness(self):
        agent, router = self.app.build()
        with mock.patch.dict(os.environ, {"TEAMS_TASK_HARNESS": "claude"}), mock.patch("shutil.which", return_value=None):
            self.assertEqual(router.jobs.harness().name, "builtin")


class OnboardTest(unittest.TestCase):
    """nodra-teams-bot/bot/onboard.py driven against a fake `teams` CLI (no network, no Microsoft account)."""
    FAKE = r"""#!/bin/sh
state="$FAKE_DIR/state"
case "$1" in
  status) if [ -f "$state" ]; then echo '{"loggedIn": true, "username": "a@b.c"}'; else echo '{"loggedIn": false}'; fi ;;
  login) touch "$state" ;;
  app)
    [ "$FAKE_FAIL" = 1 ] && exit 3
    while [ $# -gt 0 ]; do [ "$1" = "--env" ] && f="$2"; [ "$1" = "--name" ] && n="$2"; [ "$1" = "--endpoint" ] && e="$2"; shift; done
    printf 'CLIENT_ID=cid-123456789\nCLIENT_SECRET=sec-xyz\nTENANT_ID=ten-1\n' > "$f"
    echo "$n|$e" > "$FAKE_DIR/args" ;;
esac
"""

    def setUp(self):
        import importlib.util
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "bin"))
        t = os.path.join(self.d, "bin", "teams")
        open(t, "w").write(self.FAKE)
        os.chmod(t, 0o755)
        self.envf = os.path.join(self.d, ".env")
        open(self.envf, "w").write("# my file\nTEAMS_TASK=general\nCLIENT_ID=\nKEEP=1\n")
        env = {"PATH": os.path.join(self.d, "bin") + os.pathsep + os.environ["PATH"], "FAKE_DIR": self.d, "NODRA_BOT_ENV": self.envf, "FAKE_FAIL": "0"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        spec = importlib.util.spec_from_file_location("onboard_t", os.path.join(TEAMS, "bot", "onboard.py"))
        self.ob = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ob)

    def answers(self, *a):
        return mock.patch("builtins.input", side_effect=list(a))

    def test_full_flow_creates_credentials_and_keeps_other_lines(self):
        with self.answers("My Bot", "https://x.devtunnels.ms/api/messages", "helpdesk", "ada@x.org"):
            self.assertEqual(self.ob.main(), 0)
        env = self.ob.parse_env(self.envf)
        self.assertEqual((env["CLIENT_ID"], env["CLIENT_SECRET"], env["TENANT_ID"]), ("cid-123456789", "sec-xyz", "ten-1"))
        self.assertEqual((env["TEAMS_TASK"], env["TEAMS_ALLOWED"], env["KEEP"]), ("helpdesk", "ada@x.org", "1"))
        self.assertIn("# my file", open(self.envf).read())
        self.assertEqual(open(os.path.join(self.d, "args")).read().strip(), "My Bot|https://x.devtunnels.ms/api/messages")
        self.assertTrue(os.path.exists(os.path.join(self.d, "state")))                    # it logged in first
        self.assertEqual(oct(os.stat(self.envf).st_mode & 0o777), "0o600")

    def test_http_endpoint_ignored_and_failure_keeps_env(self):
        with self.answers("Bot", "http://insecure", "", ""):
            self.ob.main()
        self.assertEqual(open(os.path.join(self.d, "args")).read().strip(), "Bot|")
        open(self.envf, "w").write("CLIENT_ID=\n")
        with mock.patch.dict(os.environ, {"FAKE_FAIL": "1"}), self.answers("Bot", ""):
            self.assertEqual(self.ob.main(), 1)
        self.assertEqual(self.ob.parse_env(self.envf)["CLIENT_ID"], "")

    def test_existing_credentials_are_kept_unless_asked(self):
        open(self.envf, "w").write("CLIENT_ID=old-id-12345\nCLIENT_SECRET=old\n")
        with self.answers("n", "general", ""):
            self.assertEqual(self.ob.main(), 0)
        self.assertEqual(self.ob.parse_env(self.envf)["CLIENT_ID"], "old-id-12345")
        self.assertFalse(os.path.exists(os.path.join(self.d, "args")))

    def test_missing_cli_without_node_explains(self):
        with mock.patch.object(self.ob.shutil, "which", return_value=None):
            self.assertIsNone(self.ob.find_teams())

    def test_installer_hook_is_optional(self):
        rec = {"path": TEAMS, "bot_home": self.d, "components": ["bot:nodra-teams-bot"]}
        m = M.parse(open(os.path.join(TEAMS, "nodra.toml"), encoding="utf-8").read())
        self.assertEqual(m["bot"]["onboard"], "bot/onboard.py")
        self.assertEqual(M.lint(m, TEAMS)[0], [])
        with mock.patch.object(installer, "bots", return_value={"nodra-teams-bot": (rec, m)}):
            with mock.patch.object(installer.subprocess, "call", return_value=0) as call:
                self.assertFalse(installer.onboard("nodra-teams-bot", assume_yes=True))            # --yes: never interactive, only a hint
                call.assert_not_called()
                with mock.patch.object(installer.ui, "INTERACTIVE", True), mock.patch.object(installer.ui, "_ask", return_value="n"):
                    self.assertFalse(installer.onboard("nodra-teams-bot"))                         # declined: nothing runs
                call.assert_not_called()
                self.assertTrue(installer.onboard("nodra-teams-bot", force=True))
                self.assertEqual(call.call_args[1]["env"]["NODRA_BOT_ENV"], os.path.join(self.d, ".env"))
        m2 = dict(m, bot=dict(m["bot"], onboard=""))
        with mock.patch.object(installer, "bots", return_value={"x": (rec, m2)}):
            self.assertFalse(installer.onboard("x"))
            with self.assertRaises(Exception):
                installer.onboard("x", force=True)
