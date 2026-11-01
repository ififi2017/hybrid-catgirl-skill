import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maomao_companion.context import CompanionContext
from maomao_companion.life import LifeStore, public_url

PAGE = "A synthetic public article explains gardening: focus on the eye and keep a quiet distance."
QUOTE = "focus on the eye"


def extracted(content=PAGE, url="https://example.org/plants"):
    # Actual Hermes web_extract projection, not a hypothetical API envelope.
    return {"results": [{"url": url, "title": "Plants", "content": content, "error": None}]}


class LifeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"life.sqlite3"
        self.db = LifeStore(self.path)
        self.goal = self.db.create("A", "种花学习", "读一篇公开文章并提炼方法", "阅读公开文章", "request")
        self.gid = self.goal["id"]

    def tearDown(self):
        self.temp.cleanup()

    def read(self, turn="t", content=PAGE, tool="web_extract", result=None):
        self.db.select("A", self.gid, turn)
        return self.db.observe("A", self.gid, turn, tool, "call-"+turn,
                               extracted(content) if result is None else result, "ok")

    def test_persistence_and_idempotent_creation(self):
        self.assertEqual(LifeStore(self.path).goal("A", self.gid), self.goal)
        self.assertEqual(self.db.create("A", self.goal["title"], self.goal["done_when"], self.goal["next_step"], "request"), self.goal)
        with self.assertRaises(ValueError):
            self.db.create("A", "changed", "changed", "changed", "request")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_active_goal_limit(self):
        for n in range(7):
            self.db.create("A", str(n), "read", "search", str(n))
        with self.assertRaises(ValueError):
            self.db.create("A", "ninth", "read", "search", "extra")

    def test_scope_isolation(self):
        self.read()
        self.assertEqual(self.db.goals("B"), [])
        self.assertEqual(self.db.sources("B"), [])
        with self.assertRaises(ValueError):
            self.db.select("B", self.gid, "t")

    def test_evidence_requires_selected_goal_and_successful_tool(self):
        self.assertEqual(self.db.observe("A", self.gid, "t", "web_extract", "call", extracted(), "ok"), [])
        self.db.select("A", self.gid, "t")
        for tool, status, cid in [("terminal", "ok", "call"), ("web_extract", "error", "call"), ("web_extract", "ok", "")]:
            self.assertEqual(self.db.observe("A", self.gid, "t", tool, cid, extracted(), status), [])

    def test_malformed_results_and_private_urls_not_recorded(self):
        self.db.select("A", self.gid, "t")
        for result in [None, [], "not json", {"data": []}, {"error": "failed"}, {"success": False}, {"results": {}},
                       extracted(url="http://127.0.0.1/"), extracted(url="https://example.org/?token=secret"),
                       {"results": [{**extracted()["results"][0], "error": "denied"}]}]:
            for tool in ("web_extract", "web_search"):
                self.assertEqual(self.db.observe("A", self.gid, "t", tool, "call", result, "ok"), [])

    def test_public_urls_reject_local_credentials_and_tokens(self):
        for url in ("file:///tmp/a", "http://localhost./", "http://10.0.0.1/", "http://[::1]/", "https://user:pass@example.org/", "http://service.internal/", "https://example.org/?api_key=x"):
            self.assertFalse(public_url(url), url)
        self.assertTrue(public_url("https://example.org/article"))

    def test_search_is_not_read_evidence_for_completion_or_interest(self):
        sid = self.read(tool="web_search", result={"success": True, "data": {"web": [{"url": "https://example.org/plants", "description": PAGE}]}})[0]
        self.assertEqual(self.db.sources("A")[0]["kind"], "search")
        with self.assertRaises(ValueError):
            self.db.update("A", self.gid, 1, "completed", evidence_id=sid, quote=QUOTE)
        with self.assertRaises(ValueError):
            self.db.interest("A", sid, "种花", 1, QUOTE)
        self.db.finish_attempt("A", "t")
        with self.db.db() as sql:
            self.assertEqual(sql.execute("SELECT status FROM attempts").fetchone()[0], "no_progress")

    def test_completion_requires_matching_goal_scope_and_quote(self):
        sid = self.read()[0]
        other = self.db.create("A", "other", "read", "read", "other")
        for scope, gid, quote in [("B", self.gid, QUOTE), ("A", other["id"], QUOTE), ("A", self.gid, "invented quote")]:
            with self.assertRaises(ValueError):
                self.db.update(scope, gid, 1, "completed", evidence_id=sid, quote=quote)
        updated = self.db.update("A", self.gid, 1, "completed", evidence_id=sid, quote=QUOTE)
        self.assertEqual(updated["status"], "completed")
        with self.assertRaises(ValueError):
            self.db.update("A", self.gid, 2, "ready")

    def test_revision_conflict_and_pause_are_respected(self):
        self.db.update("A", self.gid, 1, "paused")
        self.assertEqual(self.db.plan("A")["action"], "rest")
        with self.assertRaises(ValueError):
            self.db.update("A", self.gid, 1, "ready")
        self.db.update("A", self.gid, 2, "ready")
        self.assertEqual(self.db.plan("A")["goal_id"], self.gid)

    def test_plan_is_pure_and_no_progress_has_cooldown(self):
        for _ in range(3):
            self.assertEqual(self.db.plan("A")["action"], "continue")
        with self.db.db() as sql:
            self.assertEqual(sql.execute("SELECT count(*) FROM attempts").fetchone()[0], 0)
        for turn in ("t1", "t2"):
            self.db.select("A", self.gid, turn)
            self.db.finish_attempt("A", turn)
        self.assertEqual(self.db.plan("A")["action"], "rest")
        self.assertEqual(self.db.plan("A", time.time()+4*3600)["action"], "continue")
        self.read("t3")
        self.assertEqual(self.db.plan("A")["action"], "continue")

    def test_duplicate_reads_do_not_manufacture_new_progress(self):
        sid = self.read("t0")[0]
        self.db.finish_attempt("A", "t0")
        for turn in ("t1", "t2"):
            self.assertEqual(self.read(turn), [sid])
            self.db.finish_attempt("A", turn)
        self.assertEqual(len(self.db.sources("A")), 1)
        self.assertEqual(self.db.plan("A")["action"], "rest")

    def test_one_goal_per_turn_and_interruption_not_failure(self):
        self.db.select("A", self.gid, "t")
        other = self.db.create("A", "other", "read", "read", "other")
        with self.assertRaises(ValueError):
            self.db.select("A", other["id"], "t")
        self.db.interrupt("A", "t")
        self.db.finish_attempt("A", "t")
        with self.db.db() as sql:
            self.assertEqual(sql.execute("SELECT status FROM attempts").fetchone()[0], "interrupted")

    def test_agent_interests_attributed_deduplicated_and_decay(self):
        sid = self.read()[0]
        self.db.interest("A", sid, "种花", 1, QUOTE)
        self.db.interest("A", sid, "种花", 1, QUOTE)
        items = self.db.interests("A")
        self.assertEqual(items[0]["subject"], "agent")
        self.assertEqual(items[0]["source_ids"], [sid])
        self.assertAlmostEqual(items[0]["score"], 1., places=4)
        self.assertAlmostEqual(self.db.interests("A", time.time()+60*86400)[0]["score"], .5, places=4)
        self.assertEqual(self.db.interests("B"), [])
        with self.assertRaises(ValueError):
            self.db.interest("B", sid, "种花", 1, QUOTE)


class LifeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HERMES_HOME": self.temp.name})
        self.env.start()
        self.root = Path(self.temp.name)/"state/maomao-companion"
        self.root.mkdir(parents=True)
        self.target = {"platform": "fake", "chat_id": "chat", "user_id": "owner", "chat_type": "dm"}
        self.config = {"enabled": True, "target": self.target, "context": {"enabled": True, "allowed_models": ["ordinary"]}, "life": {"enabled": True}}
        (self.root/"config.json").write_text(json.dumps(self.config))
        sessions = Path(self.temp.name)/"sessions"
        sessions.mkdir()
        (sessions/"sessions.json").write_text(json.dumps({"key": {"session_id": "sid", "origin": self.target}}))
        self.guard()
        self.c = CompanionContext(SimpleNamespace())

    def tearDown(self):
        self.c.close()
        self.env.stop()
        self.temp.cleanup()

    def guard(self, blocked=False):
        (self.root/"session-policy.json").write_text(json.dumps({"key": {"blocked": blocked, "session_id": "sid", "updated": time.time()}}))

    def start(self, turn="t", model="ordinary"):
        self.c.incoming(session_key="key", source=self.target, message_id="message-"+turn, text="一起学种花")
        return self.c.before(session_id="sid", turn_id=turn, model=model, platform="fake")

    def call(self, action, sid="sid", **args):
        return json.loads(self.c.life.handler({"action": action, **args}, session_id=sid))

    def select(self):
        self.start()
        goal = self.call("create_goal", title="种花", done_when="读文章", next_step="读公开文章")["result"]
        self.call("select_goal", goal_id=goal["id"])
        return goal

    def observe(self, **kwargs):
        self.c.life.observe(tool_name="web_extract", result=extracted(), session_id="sid", turn_id="t", tool_call_id="call", status="ok", **kwargs)

    def test_tool_denied_without_admitted_ordinary_turn(self):
        self.assertIn("error", self.call("status"))
        self.start(model="private")
        self.assertIn("error", self.call("status"))
        self.assertFalse((self.root/"life.sqlite3").exists())

    def test_model_cannot_supply_identity_or_arbitrary_evidence(self):
        self.start()
        for extra in ({"scope": "other"}, {"session_id": "other"}, {"model": "ordinary"}, {"result": extracted()}):
            self.assertIn("error", self.call("status", **extra))
        self.assertIn("error", self.call("observe", evidence_id="invented"))
        self.assertIn("error", self.call("status", sid="other"))

    def test_native_observer_pipeline_and_own_interest(self):
        goal = self.select()
        self.observe()
        source = self.call("recall", goal_id=goal["id"])["result"]["sources"][0]
        self.assertEqual(source["kind"], "read")
        interest = self.call("add_interest", evidence_id=source["id"], topic="种花", polarity=1, quote=QUOTE)
        self.assertEqual(interest["result"]["agent_interests"][0]["subject"], "agent")
        done = self.call("update_goal", goal_id=goal["id"], revision=1, status="completed", evidence_id=source["id"], quote=QUOTE)
        self.assertEqual(done["result"]["status"], "completed")
        self.assertEqual(self.c.store.context(next(iter(self.c.active.values()))["scope"], "种花")["user_preferences"], [])

    def test_mode_switch_blocks_reads_writes_and_late_observations(self):
        self.select()
        self.guard(blocked=True)
        self.observe()
        self.assertIn("error", self.call("status"))
        self.guard()
        self.assertEqual(self.call("recall")["result"]["sources"], [])

    def test_wrong_turn_observer_not_attached_to_current_goal(self):
        self.select()
        self.c.life.observe(tool_name="web_extract", result=extracted(), session_id="sid", turn_id="other", tool_call_id="call", status="ok")
        self.assertEqual(self.call("recall")["result"]["sources"], [])

    def test_unload_and_interrupted_turn_do_not_fake_failed_attempts(self):
        self.select()
        scope = next(iter(self.c.active.values()))["scope"]
        self.start(turn="t2")
        with self.c.life.store.db() as sql:
            self.assertEqual(sql.execute("SELECT status FROM attempts WHERE scope=?", (scope,)).fetchone()[0], "interrupted")
        self.c.close()
        self.assertIn("error", self.call("status"))

    def test_finish_records_progress_without_requiring_analysis(self):
        self.select()
        self.observe()
        scope = next(iter(self.c.active.values()))["scope"]
        self.c.analyzer = SimpleNamespace(submit=lambda job: None, close=lambda: None)
        self.c.after(session_id="sid", turn_id="t", assistant_response="读到了这些方法")
        with self.c.life.store.db() as sql:
            self.assertEqual(sql.execute("SELECT status FROM attempts WHERE scope=?", (scope,)).fetchone()[0], "progress")
        self.assertIn("error", self.call("status"))

    def test_disabled_feature_creates_no_life_database(self):
        self.config["life"]["enabled"] = False
        (self.root/"config.json").write_text(json.dumps(self.config))
        self.start()
        self.assertFalse((self.root/"life.sqlite3").exists())
        self.assertIn("error", self.call("status"))

    def test_later_turn_receives_persistent_intentions_without_experience_claim(self):
        goal = self.select()
        context = self.start(turn="t2")["context"]
        self.assertIn(goal["id"], context)
        self.assertIn("目标与安排是意图", context)
        self.assertIn("decision_only", context)


if __name__ == "__main__":
    unittest.main()
