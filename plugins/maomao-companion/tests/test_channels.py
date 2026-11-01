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
from maomao_companion.channels import ChannelContext, channel_key
from maomao_companion.budget import OutboundBudget, BudgetedEmbeddings


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"HERMES_HOME": self.temp.name}); self.env.start()
        self.h = Path(self.temp.name)
        self.root = self.h/"state/maomao-companion"; self.root.mkdir(parents=True)
        self.targets = [{"platform": "qqbot", "chat_id": "group-"+x, "chat_type": "group"} for x in ("a", "b")]
        self.targets += [{"platform": "telegram", "chat_id": "tg", "chat_type": "dm", "user_id": "owner"}]
        (self.root/"config.json").write_text(json.dumps({"enabled": True, "channels": self.targets, "context": {"enabled": True, "allowed_models": ["ordinary"]}}))
        (self.h/"sessions").mkdir()
        (self.h/"sessions/sessions.json").write_text(json.dumps({"key"+str(i): {"session_id": "s"+str(i), "origin": target} for i,target in enumerate(self.targets)}))
        self.channels = [ChannelContext(SimpleNamespace(), t) for t in self.targets]

    def tearDown(self):
        for c in self.channels: c.close()
        self.env.stop(); self.temp.cleanup()

    def start(self, index, actor="alice", text="我喜欢种花"):
        channel = self.channels[index]
        channel.incoming(session_key="key"+str(index), source={**self.targets[index], "user_id": actor}, message_id="msg", text=text)
        return channel.before(session_id="s"+str(index), turn_id="turn", platform=self.targets[index]["platform"], model="ordinary")

    def test_each_group_and_telegram_have_separate_files(self):
        self.start(0); self.start(1); self.start(2, "owner")
        paths = [c.store.path for c in self.channels]
        self.assertEqual(len(set(paths)), 3)
        self.assertTrue(all(p.parent.name == channel_key(t) for p,t in zip(paths,self.targets)))
        self.assertNotIn(self.root/"dialogue.sqlite3", paths)

    def test_one_group_cannot_resolve_another_session(self):
        self.assertIsNone(self.channels[0].resolve("s1", "qqbot"))
        self.assertFalse(self.channels[0].gate("key1", "s1"))

    def test_group_members_preferences_not_owner_preferences(self):
        self.start(0)
        c = self.channels[0]
        self.assertEqual(c.store.context(channel_key(self.targets[0]), "种花")["user_preferences"], [])
        self.assertIn("群成员", c.store.turn(channel_key(self.targets[0]), "turn")["user_text"])

    def test_telegram_requires_matching_private_user(self):
        self.assertIsNone(self.start(2, "other"))
        self.assertFalse(self.channels[2].root.exists())

    def test_unapproved_model_cannot_access_channel_notes(self):
        c = self.channels[0]
        c.incoming(session_key="key0", source={**self.targets[0], "user_id": "alice"}, message_id="m", text="hello")
        self.assertIsNone(c.before(session_id="s0",turn_id="t",platform="qqbot",model="private"))
        self.assertFalse(c.root.exists())

    def test_memory_and_meme_calls_share_one_atomic_budget(self):
        path=self.root/"outbound.sqlite3"
        client=SimpleNamespace(model="synthetic",dimensions=2,embed=lambda texts:[[1.,0.]])
        memory=BudgetedEmbeddings(client,OutboundBudget(path,limit=2),"group-a")
        memes=BudgetedEmbeddings(client,OutboundBudget(path,limit=2),"group-a")
        memory.embed(["memory"]); memes.embed(["meme"])
        with self.assertRaises(PermissionError): memory.embed(["third"])
        other=BudgetedEmbeddings(client,OutboundBudget(path,limit=2),"group-b")
        self.assertEqual(other.embed(["independent"]),[[1.,0.]])

    def test_group_episode_keeps_original_speaker(self):
        self.start(0)
        c=self.channels[0]; scope=channel_key(self.targets[0])
        self.assertTrue(c.store.apply_analysis(scope,"turn",{"topic":"种花","status":"open","summary":"该成员喜欢种花","quote":"我喜欢种花","mood":"curious","intensity":1}))
        actor=c.store.turn(scope,"turn")["user_text"].split("]")[0].split()[-1]
        episode=c.store.memory_documents(scope)[0]["record"]
        self.assertEqual(episode["speaker_id"],actor)
        self.assertEqual(c.store.context(scope,"种花")["topic"]["speaker_id"],actor)

    def test_same_channel_alias_uses_the_admitted_event_key(self):
        p=self.h/"sessions/sessions.json"; rows=json.loads(p.read_text())
        rows["old-alias"]=rows["key0"]; p.write_text(json.dumps(rows))
        self.assertIsNotNone(self.start(0))
        self.assertEqual(next(iter(self.channels[0].active.values()))["session_key"],"key0")
