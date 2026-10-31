"""nodra-chat with a Claude subscription: the login check (`claude auth status`, faked), API keys kept out of Claude Code runs while a
subscription login exists, and the 5-hour / weekly limits from rate_limit_event and the status line bridge file. No real Claude Code."""
import json
import os
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "chat", "ui"))
from nodraui import chat, claudeauth as CA, limits as L, store  # noqa: E402

FAKE_CLAUDE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    if sys.argv[1:3] == ["auth", "status"]:
        method = os.environ.get("FAKE_METHOD", "claude.ai")
        if os.environ.get("ANTHROPIC_API_KEY"):
            method = "api_key"                    # what Claude Code reports when a key is in its environment
        print(json.dumps({"loggedIn": method != "none", "authMethod": method, "apiProvider": "firstParty"}))
''')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        bin_ = os.path.join(self.tmp, "bin")
        os.makedirs(bin_)
        exe = os.path.join(bin_, "claude")
        with open(exe, "w") as f:
            f.write(FAKE_CLAUDE)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        self.env = mock.patch.dict(os.environ, {"NODRA_HOME": self.tmp, "HOME": self.tmp, "PATH": bin_ + os.pathsep + os.environ.get("PATH", "")})
        self.env.start()
        os.environ.pop("ANTHROPIC_BASE_URL", None)
        CA._state.update(checked=0.0, status=None)

    def tearDown(self):
        self.env.stop()
        CA._state.update(checked=0.0, status=None)


class Login(Base):
    def test_subscription_is_seen_under_an_api_key(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        s = CA.status()
        self.assertTrue(s["ok"])
        self.assertEqual((s["method"], s["subscription"]), ("claude.ai", True))     # probed without the key

    def test_setup_token_counts_as_subscription_but_api_key_and_cloud_do_not(self):
        for method, sub in (("oauth_token", True), ("api_key", False), ("api_key_helper", False), ("third_party", False), ("none", False)):
            os.environ["FAKE_METHOD"] = method
            self.assertEqual(CA.status(fresh=True)["subscription"], sub, method)

    def claude_settings(self, env):
        d = os.path.join(self.tmp, ".claude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "settings.json"), "w") as f:
            json.dump({"env": env}, f)

    def test_a_gateway_is_never_a_subscription(self):
        os.environ["FAKE_METHOD"] = "oauth_token"
        self.claude_settings({"ANTHROPIC_BASE_URL": "https://llm-gateway.example.com"})
        s = CA.status(fresh=True)
        self.assertEqual((s["gateway"], s["subscription"]), (True, False))
        self.claude_settings({"ANTHROPIC_AUTH_TOKEN": "gw-token"})              # oauth_token that is really a bearer token in Claude's env
        self.assertFalse(CA.status(fresh=True)["subscription"])
        self.claude_settings({})
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"          # the default address is not a gateway
        self.assertTrue(CA.status(fresh=True)["subscription"])

    def test_status_is_cached(self):
        CA.status()
        os.environ["FAKE_METHOD"] = "none"
        self.assertTrue(CA.status()["subscription"])
        self.assertFalse(CA.status(fresh=True)["subscription"])

    def test_no_claude_installed(self):
        os.environ["PATH"] = self.tmp                                    # no claude there
        s = CA.status(fresh=True)
        self.assertEqual((s["ok"], s["subscription"]), (False, False))
        self.assertIn("not installed", s["error"])


class KeysStayOut(Base):
    def env_with_keys(self):
        return {"ANTHROPIC_API_KEY": "sk-a", "ANTHROPIC_AUTH_TOKEN": "tok", "OTHER": "1"}

    def test_auto_drops_keys_when_subscribed(self):
        e = CA.child_env(self.env_with_keys())
        self.assertNotIn("ANTHROPIC_API_KEY", e)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", e)
        self.assertEqual(e["OTHER"], "1")

    def test_key_mode_and_no_subscription_and_gateways_keep_them(self):
        store.save_prefs({"claude_auth": "key"})
        self.assertIn("ANTHROPIC_API_KEY", CA.child_env(self.env_with_keys()))
        store.save_prefs({"claude_auth": "auto"})
        e = dict(self.env_with_keys(), ANTHROPIC_BASE_URL="https://gateway.example.com")
        self.assertIn("ANTHROPIC_API_KEY", CA.child_env(e))
        os.environ["FAKE_METHOD"] = "none"
        CA.status(fresh=True)
        self.assertIn("ANTHROPIC_API_KEY", CA.child_env(self.env_with_keys()))

    def test_pref_is_validated(self):
        self.assertEqual(store.prefs()["claude_auth"], "auto")
        with self.assertRaises(ValueError):
            store.save_prefs({"claude_auth": "sometimes"})

    def test_btw_side_question_runs_claude_without_the_key(self):
        seen = {}

        def run(cmd, **kw):
            seen["env"] = kw.get("env")
            class R:
                returncode, stdout, stderr = 0, json.dumps({"result": "fine", "usage": {}}), ""
            return R()
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        self.assertTrue(CA.status()["subscription"])                        # probe now: the patch below replaces subprocess.run everywhere
        sess = store.create_session()
        with mock.patch.object(chat.subprocess, "run", run):
            try:
                chat.btw(sess, "quick question")
            except Exception:
                pass
        self.assertIn("env", seen)
        self.assertFalse("ANTHROPIC_API_KEY" in seen["env"] or "ANTHROPIC_AUTH_TOKEN" in seen["env"], "a key reached claude")   # never print the env


class Limits(Base):
    def test_event_with_windows_is_kept_as_percent(self):
        now = time.time()
        lim = L.note_event({"status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.86, "resetsAt": int(now + 3600),
                            "unifiedWindows": {"five_hour": {"utilization": 0.86, "resetsAt": int(now + 3600)},
                                               "seven_day": {"utilization": 0.4, "resetsAt": int(now + 86400 * 3)}}})
        self.assertEqual((lim["window"], lim["pct"]), ("five_hour", 86.0))
        w = {x["id"]: x for x in L.windows()}
        self.assertEqual((w["five_hour"]["pct"], w["seven_day"]["pct"]), (86.0, 40.0))
        self.assertEqual(w["five_hour"]["label"], "5-hour window")
        self.assertIn("86%", L.chat_note(lim))
        a = L.alerts()
        self.assertEqual([x["level"] for x in a], ["warn"])
        self.assertIn("5-hour", a[0]["title"])

    def test_rejected_and_credits(self):
        now = time.time()
        lim = L.note_event({"status": "rejected", "resetsAt": int(now + 600), "errorCode": "credits_required"})
        self.assertIn("limit reached", L.chat_note(lim))
        self.assertEqual(L.alerts()[0]["level"], "over")
        self.assertIn("credits", L.alerts()[0]["text"])

    def test_allowed_is_quiet_and_expired_windows_drop(self):
        lim = L.note_event({"status": "allowed", "rateLimitType": "seven_day", "utilization": 0.1, "resetsAt": int(time.time() - 5)})
        self.assertEqual(L.chat_note(lim), "")
        self.assertEqual(L.windows(), [])
        self.assertEqual(L.alerts(), [])

    def test_status_line_file_merges_and_newest_wins(self):
        now = time.time()
        L.note_event({"status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.9, "resetsAt": int(now + 3600)})
        with open(os.path.join(store.ui_dir(), "limits-statusline.json"), "w") as f:
            json.dump({"at": now + 5, "rate_limits": {"five_hour": {"used_percentage": 91.5, "resets_at": now + 3600},
                                                      "seven_day": {"used_percentage": 20, "resets_at": now + 86400}}}, f)
        w = {x["id"]: x for x in L.windows()}
        self.assertEqual((w["five_hour"]["pct"], w["five_hour"]["source"]), (91.5, "claude code"))
        self.assertEqual(w["seven_day"]["pct"], 20.0)

    def test_junk_is_ignored(self):
        self.assertIsNone(L.note_event(None))
        self.assertIsNone(L.note_event("x"))
        L.note_event({"status": "allowed", "rateLimitType": "nonsense", "utilization": "a lot"})
        self.assertEqual(L.windows(), [])


if __name__ == "__main__":
    unittest.main()
