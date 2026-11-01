import concurrent.futures
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maomao_companion.contact import ContactLedger, Policy, digest
from maomao_companion.legacy import install
from maomao_companion.dialogue import DialogueStore


class ContactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = ContactLedger(Path(self.temp.name)/"contacts.sqlite3")
        self.scope = self.ledger.scope("fake", "chat", "owner")
        self.now = datetime(2026, 11, 1, 12, tzinfo=ZoneInfo("Asia/Taipei")).timestamp()

    def tearDown(self):
        self.temp.cleanup()

    def send(self, source="lonely", now=None, text="first"):
        at = self.now if now is None else now
        ticket = self.ledger.reserve(self.scope, source, text, digest(text), at)
        self.ledger.dispatch(ticket, at)
        self.ledger.finish(ticket, "sent", at)
        return ticket

    def test_sources_share_one_cooldown(self):
        self.send()
        for source in ("activity", "reminder"):
            with self.assertRaisesRegex(PermissionError, "cooldown"):
                self.ledger.reserve(self.scope, source, source, digest(source), self.now+60)

    def test_group_contact_is_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.scope("fake", "group", "owner", "group")

    def test_no_cross_scope_cooldown(self):
        self.send()
        other = self.ledger.scope("fake", "other", "owner")
        self.assertTrue(self.ledger.check(other, self.now)["allowed"])

    def test_same_message_does_not_refresh_last_activity(self):
        self.ledger.incoming(self.scope, "m1", self.now-6000)
        self.ledger.incoming(self.scope, "m1", self.now)
        self.assertTrue(self.ledger.check(self.scope, self.now)["allowed"])

    def test_owner_returns_during_generation_cancels_dispatch(self):
        ticket = self.ledger.reserve(self.scope, "lonely", "one", "hash", self.now)
        self.ledger.incoming(self.scope, "new", self.now+1)
        with self.assertRaisesRegex(PermissionError, "recent_chat"):
            self.ledger.dispatch(ticket, self.now+2)
        with self.ledger.transaction() as db:
            self.assertEqual(db.execute("SELECT status FROM contacts WHERE id=?", (ticket,)).fetchone()[0], "cancelled")

    def test_reserved_ticket_counts_against_concurrent_senders(self):
        def attempt(n):
            try:
                return self.ledger.reserve(self.scope, "lonely", str(n), str(n), self.now)
            except PermissionError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))
        self.assertEqual(sum(bool(x) for x in results), 1)

    def test_unknown_delivery_cannot_be_retried_with_new_id(self):
        ticket = self.ledger.reserve(self.scope, "activity", "one", "same", self.now)
        self.ledger.dispatch(ticket, self.now)
        self.ledger.finish(ticket, "uncertain", self.now)
        with self.assertRaisesRegex(PermissionError, "duplicate_content"):
            self.ledger.reserve(self.scope, "activity", "two", "same", self.now+86400*3)

    def test_expired_pre_dispatch_reservation_releases_capacity(self):
        self.ledger.reserve(self.scope, "lonely", "one", "one", self.now)
        self.assertTrue(self.ledger.check(self.scope, self.now+301)["allowed"])

    def test_expired_dispatch_keeps_conservative_charge(self):
        ticket = self.ledger.reserve(self.scope, "lonely", "one", "one", self.now)
        self.ledger.dispatch(ticket, self.now)
        self.assertEqual(self.ledger.check(self.scope, self.now+301)["daily_used"], 1)
        with self.ledger.transaction() as db:
            self.assertEqual(db.execute("SELECT status FROM contacts WHERE id=?", (ticket,)).fetchone()[0], "uncertain")

    def test_goodnight_crosses_midnight_until_eight(self):
        night = self.now+9*3600
        self.ledger.goodnight(self.scope, night)
        self.assertEqual(self.ledger.check(self.scope, night+60)["reason"], "goodnight")
        self.assertTrue(self.ledger.check(self.scope, self.now+20*3600)["allowed"])

    def test_dnd_uses_configured_timezone(self):
        self.assertEqual(self.ledger.check(self.scope, self.now+12*3600)["reason"], "dnd")

    def test_future_activity_does_not_allow_clock_rollback_bypass(self):
        self.ledger.incoming(self.scope, "m", self.now+100)
        self.assertFalse(self.ledger.check(self.scope, self.now)["allowed"])

    def test_unanswered_six_stage_backoff_and_stop(self):
        entries = [{"time": self.now-(6-n)*86400, "fingerprint": str(n)} for n in range(6)]
        self.ledger.import_sent(self.scope, entries)
        result = self.ledger.check(self.scope, self.now)
        self.assertEqual(result["reason"], "waiting_for_reply")
        self.assertEqual(result["stage"], "最后留言")
        self.ledger.incoming(self.scope, "returned", self.now)
        result = self.ledger.check(self.scope, self.now+86400)
        self.assertEqual(result["unanswered"], 0)
        self.assertTrue(result["allowed"])

    def test_daily_budget_is_shared(self):
        ledger = ContactLedger(self.ledger.path, Policy(daily_limit=1))
        self.send()
        self.assertEqual(ledger.check(self.scope, self.now+5*3600)["reason"], "daily_limit")

    def test_import_legacy_is_idempotent_and_stores_no_bodies(self):
        entry = {"time": self.now-86400, "fingerprint": digest("synthetic secret")}
        self.ledger.import_sent(self.scope, [entry, entry])
        with self.ledger.transaction() as db:
            rows = db.execute("SELECT * FROM contacts").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertNotIn("synthetic secret", json.dumps([dict(r) for r in rows]))

    def legacy_namespace(self):
        sent, recorded = [], []
        namespace = {"FEISHU_HOME_CHANNEL": "chat", "precheck": lambda state, now: None,
                     "send_feishu_message": lambda message, chat_id=None: (sent.append(message) is None, "ok"),
                     "set_dnd_goodnight": lambda: "ok", "effective_last_interaction": lambda state: None,
                     "proactive_history": lambda state: [], "load_state": lambda: {},
                     "smart_check": lambda: {"send": True, "fallback_message": "hello"},
                     "record_proactive_sent": recorded.append, "save_last_proactive": lambda m: None}
        return namespace, sent, recorded

    def configured(self):
        return self.ledger, {"platform": "feishu", "chat_id": "chat"}, self.scope

    def test_legacy_blocks_concurrent_source_before_network(self):
        namespace, sent, _ = self.legacy_namespace()
        install(namespace)
        with patch("maomao_companion.legacy.configured", return_value=self.configured()), patch("time.time", return_value=self.now):
            self.send("activity")
            self.assertFalse(namespace["send_feishu_message"]("hello")[0])
        self.assertEqual(sent, [])

    def test_legacy_success_records_once_and_install_is_idempotent(self):
        namespace, sent, recorded = self.legacy_namespace()
        install(namespace)
        first = namespace["send_feishu_message"]
        install(namespace)
        self.assertIs(namespace["send_feishu_message"], first)
        with patch("maomao_companion.legacy.configured", return_value=self.configured()), patch("time.time", return_value=self.now):
            self.assertTrue(namespace["check_and_trigger"]()["sent"])
            self.assertEqual(self.ledger.check(self.scope, self.now)["daily_used"], 1)
        self.assertEqual(sent, ["hello"])
        self.assertEqual(recorded, ["hello"])

    def test_legacy_failure_remains_unknown(self):
        namespace, _, recorded = self.legacy_namespace()
        namespace["send_feishu_message"] = lambda *args: (False, "timeout")
        install(namespace)
        with patch("maomao_companion.legacy.configured", return_value=self.configured()), patch("time.time", return_value=self.now):
            self.assertFalse(namespace["check_and_trigger"]()["sent"])
            self.assertEqual(self.ledger.check(self.scope, self.now)["daily_used"], 1)
        self.assertEqual(recorded, [])

    def test_wrong_configured_target_never_sends(self):
        namespace, sent, _ = self.legacy_namespace()
        install(namespace)
        cfg = self.ledger, {"platform": "feishu", "chat_id": "different"}, self.scope
        with patch("maomao_companion.legacy.configured", return_value=cfg):
            self.assertFalse(namespace["send_feishu_message"]("hello")[0])
        self.assertFalse(sent)

    def test_recent_context_never_falls_back_to_cross_channel_archives(self):
        namespace, _, _ = self.legacy_namespace()
        namespace["get_recent_session_context"] = lambda **kw: [{"text":"foreign sentinel"}]
        path=Path(self.temp.name)/"state/maomao-companion/dialogue.sqlite3"
        store=DialogueStore(path)
        store.begin(self.scope,"stale","stale sentinel",self.now-3*86400)
        store.begin(self.scope,"own","own ordinary note",self.now)
        store.begin("foreign","other","foreign sentinel",self.now)
        install(namespace)
        with patch("maomao_companion.legacy.configured",return_value=self.configured()), patch("maomao_companion.legacy.home",return_value=Path(self.temp.name)), patch("time.time",return_value=self.now):
            text=json.dumps(namespace["get_recent_session_context"]())
        self.assertIn("own ordinary note",text)
        self.assertNotIn("foreign sentinel",text)
        self.assertNotIn("stale sentinel",text)

    def test_package_excludes_private_runtime_and_unlisted_files(self):
        spec = importlib.util.spec_from_file_location("public_pack", ROOT/"tools/package_public.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fake_root = Path(self.temp.name)/"package"
        for name in module.FILES:
            p = fake_root/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("public fixture")
        (fake_root/"private").mkdir()
        (fake_root/"private"/"secret.py").write_text("DO_NOT_EXPORT")
        (fake_root/".env").write_text("DO_NOT_EXPORT")
        (fake_root/"runtime.sqlite3").write_text("DO_NOT_EXPORT")
        module.ROOT = fake_root.resolve()
        archive = module.package(Path(self.temp.name)/"public.zip")
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(len(bundle.namelist()), len(module.FILES))
            self.assertTrue(all(b"DO_NOT_EXPORT" not in bundle.read(name) for name in bundle.namelist()))

    def test_public_hook_only_observes_matching_admitted_private_owner(self):
        spec = importlib.util.spec_from_file_location("companion_hook_test", ROOT/"__init__.py", submodule_search_locations=[str(ROOT)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        callbacks = {}
        ctx = type("Context", (), {"register_hook": lambda self, name, fn: callbacks.setdefault(name, []).append(fn)})()
        with patch.dict("os.environ", {"HERMES_HOME": self.temp.name}):
            module.register(ctx)
        hook = next(fn for fn in callbacks["post_gateway_admission"] if fn.__name__ == "incoming")
        target = {"platform": "feishu", "chat_id": "chat", "user_id": "owner", "chat_type": "dm"}
        cfg = self.ledger, target, self.scope
        with patch.object(module, "configured", return_value=cfg), patch("time.time", return_value=self.now):
            hook(source={**target, "chat_type": "group"}, message_id="group", text="private sentinel")
            hook(source={**target, "user_id": "other"}, message_id="other", text="private sentinel")
            self.assertTrue(self.ledger.check(self.scope, self.now)["allowed"])
            hook(source=target, message_id="owner", text="private sentinel")
            self.assertEqual(self.ledger.check(self.scope, self.now)["reason"], "recent_chat")
        with self.ledger.transaction() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM incoming")]
            self.assertEqual(len(rows), 1)
            self.assertNotIn("private sentinel", json.dumps(rows))

    def test_no_runtime_config_preserves_original_sender(self):
        namespace, sent, _ = self.legacy_namespace()
        install(namespace)
        with patch("maomao_companion.legacy.configured", return_value=None):
            self.assertTrue(namespace["send_feishu_message"]("normal")[0])
        self.assertEqual(sent, ["normal"])

    def test_package_rejects_symlinked_allowlisted_source(self):
        spec = importlib.util.spec_from_file_location("public_pack_symlink", ROOT/"tools/package_public.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fake_root = Path(self.temp.name)/"symlink-package"
        fake_root.mkdir()
        secret = Path(self.temp.name)/"outside.py"
        secret.write_text("DO_NOT_EXPORT")
        (fake_root/"__init__.py").symlink_to(secret)
        module.ROOT = fake_root.resolve()
        with self.assertRaises(ValueError):
            module.package(Path(self.temp.name)/"rejected.zip")


if __name__ == "__main__":
    unittest.main()
