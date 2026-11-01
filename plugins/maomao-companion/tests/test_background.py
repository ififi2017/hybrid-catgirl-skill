import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maomao_companion.background import BackgroundRunner, TOPICS
from maomao_companion.contact import ContactLedger
from maomao_companion.life import LifeStore
from maomao_companion.dialogue import DialogueStore

PAGE = "Synthetic public plantwatching article: stay quiet and never disturb a nesting plant."


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.h = Path(self.temp.name)
        self.root = self.h/"state/maomao-companion"; self.root.mkdir(parents=True)
        self.target = {"platform": "feishu", "chat_type": "dm", "chat_id": "test-chat", "user_id": "test-owner"}
        (self.root/"config.json").write_text(json.dumps({"enabled": True, "target": self.target, "background": {"enabled": True}}))
        (self.h/"sessions").mkdir()
        (self.h/"sessions/sessions.json").write_text(json.dumps({"key": {"session_id": "sid", "origin": self.target}}))
        self.policy()
        self.now = datetime(2026, 11, 1, 12, tzinfo=ZoneInfo("Asia/Taipei")).timestamp()
        self.calls = []
        self.llm = SimpleNamespace(complete_structured=lambda **kw: SimpleNamespace(parsed={"summary": "园艺应保持距离", "quote": "stay quiet", "interesting": True}))
        self.runner = BackgroundRunner(self.root, self.search, self.extract, self.llm, clock=lambda: self.now)
        self.scope = ContactLedger.scope("feishu", "test-chat", "test-owner", "dm")

    def tearDown(self):
        self.temp.cleanup()

    def policy(self, **kwargs):
        (self.root/"session-policy.json").write_text(json.dumps({"key": {"blocked": False, "background_allowed": True, "session_id": "sid", **kwargs}}))

    def search(self, query):
        self.calls.append(query)
        return {"success": True, "data": {"web": [{"url": "https://example.org/plants", "description": PAGE}]}}

    def extract(self, urls):
        return {"results": [{"url": urls[0], "content": PAGE, "error": None}]}

    def test_actual_bounded_browsing_records_and_shares_only_evidence(self):
        self.assertEqual(self.runner.run()["action"], "read")
        db = LifeStore(self.root/"life.sqlite3")
        shares = db.shareable(self.scope, now=self.now)
        self.assertEqual(len(shares), 1)
        self.assertIn("stay quiet", shares[0]["quote"])
        self.assertEqual(self.runner.run()["reason"], "budget_or_cooldown")
        db.shared(self.scope, "ordinary chat")
        self.assertEqual(len(db.shareable(self.scope, now=self.now)), 1)
        db.shared(self.scope, "读到了 "+shares[0]["url"])
        self.assertEqual(db.shareable(self.scope, now=self.now), [])
        self.assertEqual(len(self.calls), 1)
        self.assertIn(self.calls[0], TOPICS)

    def test_private_or_missing_permission_makes_no_requests(self):
        for patch in ({"blocked": True}, {"background_allowed": False}, {"session_id": "wrong"}):
            self.policy(**patch)
            self.assertEqual(self.runner.run()["action"], "rest")
        self.assertEqual(self.calls, [])

    def test_recent_chat_and_dnd_do_not_browse(self):
        ContactLedger(self.root/"contacts.sqlite3").incoming(self.scope, "m", self.now-60)
        self.assertEqual(self.runner.run()["action"], "rest")
        self.now += 12*3600
        self.assertEqual(self.runner.run()["action"], "rest")
        self.assertEqual(self.calls, [])

    def test_goodnight_stops_background_reading(self):
        ContactLedger(self.root/"contacts.sqlite3").goodnight(self.scope,self.now)
        self.assertEqual(self.runner.run()["action"], "rest")
        self.assertEqual(self.calls, [])

    def test_mode_switch_while_reading_does_not_record_experience(self):
        def read(urls):
            self.policy(blocked=True)
            return self.extract(urls)
        self.runner.extract = read
        self.assertEqual(self.runner.run()["action"], "rest")
        self.assertEqual(LifeStore(self.root/"life.sqlite3").shareable(self.scope), [])

    def test_private_foreground_goal_never_becomes_a_search(self):
        db = LifeStore(self.root/"life.sqlite3")
        db.create(self.scope, "私人地点及账号", "private", "secret", "r")
        self.assertEqual(self.runner.run()["action"], "rest")
        self.assertEqual(self.calls, [])

    def test_model_cannot_invent_source_quote(self):
        self.llm.complete_structured = lambda **kw: SimpleNamespace(parsed={"summary": "invented", "quote": "not on page", "interesting": True})
        self.assertEqual(self.runner.run()["action"], "rest")
        self.assertEqual(LifeStore(self.root/"life.sqlite3").shareable(self.scope), [])

    def test_reviewed_old_notes_keep_source_and_unknown_occurrence_time(self):
        db = DialogueStore(self.root/"dialogue.sqlite3")
        notes = [{"quote": "喜欢原创短篇作品", "source": "legacy/MEMORY.md#reviewed-section"}]
        db.import_notes("feishu", notes); db.import_notes("feishu", notes)
        self.assertEqual(len(db.memory_documents("feishu")), 1)
        self.assertEqual(db.memory_documents("qq"), [])
        self.assertIsNone(db.memory_documents("feishu")[0]["record"]["occurred_at"])
