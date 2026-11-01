"""Scoped ordinary-chat state. Never import private memories or legacy transcripts."""
from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

MOODS = {"calm", "happy", "curious", "concerned", "playful", "tired"}
STATES = {"open", "resolved", "paused"}
# Anchored, attributable statements only. Questions, conditionals and quoted code do not qualify.
PREFERENCE = re.compile(r"^我(更喜欢|不喜欢|喜欢|讨厌)([^\n。！？!?]{1,60})[。！!～~]?$")
SPEAKER = re.compile(r"^\[群成员 ([0-9a-f]{12})\] ")


class DialogueStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS turns(
                  scope TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                  user_text TEXT NOT NULL, assistant_text TEXT NOT NULL,
                  received REAL NOT NULL, analysis TEXT,
                  PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS dialogue_state(
                  scope TEXT PRIMARY KEY, version INTEGER NOT NULL,
                  topic TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
                  mood TEXT NOT NULL, intensity INTEGER NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS facts(
                  scope TEXT NOT NULL, topic TEXT NOT NULL, polarity INTEGER NOT NULL,
                  quote TEXT NOT NULL, source_id TEXT NOT NULL, updated REAL NOT NULL,
                  PRIMARY KEY(scope,topic));
                CREATE TABLE IF NOT EXISTS historical_notes(
                  scope TEXT NOT NULL,id TEXT NOT NULL,quote TEXT NOT NULL,source TEXT NOT NULL,
                  imported REAL NOT NULL,PRIMARY KEY(scope,id));
            """)
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            if db.in_transaction:
                db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def begin(self, scope, turn_id, user_text, received):
        text = str(user_text).strip()[:2000]
        if not turn_id or not text or text.startswith("/"):
            return None
        with self.db() as db:
            old = db.execute("SELECT * FROM turns WHERE scope=? AND id=?", (scope, turn_id)).fetchone()
            if old:
                return dict(old)
            current = db.execute("SELECT version FROM dialogue_state WHERE scope=?", (scope,)).fetchone()
            version = (current[0] if current else 0)+1
            db.execute("INSERT INTO dialogue_state VALUES(?,?,'','open','','calm',0,?) ON CONFLICT(scope) DO UPDATE SET version=excluded.version", (scope, version, received))
            db.execute("INSERT INTO turns VALUES(?,?,?,?,?,?,NULL)", (scope, turn_id, version, text, "", received))
            match = PREFERENCE.fullmatch(text)
            if match:
                topic = match[2].strip()
                if topic and not any(x in topic for x in ("吗", "么", "如果", "的话", "是不是", "`", "http", "忽略", "指令", "系统")):
                    polarity = -1 if match[1] in {"不喜欢", "讨厌"} else 1
                    db.execute("INSERT INTO facts VALUES(?,?,?,?,?,?) ON CONFLICT(scope,topic) DO UPDATE SET polarity=excluded.polarity,quote=excluded.quote,source_id=excluded.source_id,updated=excluded.updated", (scope, topic, polarity, text, turn_id, received))
            # Bounded ordinary chat retention; stable facts remain separately attributable.
            db.execute("DELETE FROM turns WHERE scope=? AND received<?", (scope, received-7*86400))
            db.execute("DELETE FROM turns WHERE scope=? AND id NOT IN (SELECT id FROM turns WHERE scope=? ORDER BY received DESC,version DESC LIMIT 100)", (scope, scope))
            db.execute("DELETE FROM facts WHERE scope=? AND topic NOT IN (SELECT topic FROM facts WHERE scope=? ORDER BY updated DESC LIMIT 100)", (scope, scope))
            return dict(db.execute("SELECT * FROM turns WHERE scope=? AND id=?", (scope, turn_id)).fetchone())

    def turn(self, scope, turn_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM turns WHERE scope=? AND id=?", (scope, turn_id)).fetchone()
            return dict(row) if row else None

    def finish(self, scope, turn_id, assistant_text):
        with self.db() as db:
            db.execute("UPDATE turns SET assistant_text=? WHERE scope=? AND id=? AND assistant_text=''", (str(assistant_text)[:2000], scope, turn_id))

    def current(self, scope, version):
        with self.db() as db:
            row = db.execute("SELECT version FROM dialogue_state WHERE scope=?", (scope,)).fetchone()
            return bool(row and row[0] == version)

    def apply_analysis(self, scope, turn_id, result, now=None):
        now = time.time() if now is None else now
        if not isinstance(result, dict) or set(result) != {"topic", "status", "summary", "quote", "mood", "intensity"}:
            return False
        if not isinstance(result["status"], str) or not isinstance(result["mood"], str) or result["status"] not in STATES or result["mood"] not in MOODS or type(result["intensity"]) is not int or not 0 <= result["intensity"] <= 3:
            return False
        if any(not isinstance(result[k], str) or len(result[k]) > size for k, size in (("topic", 60), ("summary", 160), ("quote", 100))):
            return False
        with self.db() as db:
            turn = db.execute("SELECT * FROM turns WHERE scope=? AND id=?", (scope, turn_id)).fetchone()
            state = db.execute("SELECT * FROM dialogue_state WHERE scope=?", (scope,)).fetchone()
            if not turn or not state or turn["analysis"] is not None or turn["version"] != state["version"]:
                return False
            if not result["quote"] or result["quote"] not in turn["user_text"]:
                return False
            # A mood can move one step per turn, rather than jumping to a maximum.
            previous = state["intensity"] if now-state["updated"] < 7200 else 0
            intensity = min(result["intensity"], previous+1)
            db.execute("UPDATE dialogue_state SET topic=?,status=?,summary=?,mood=?,intensity=?,updated=? WHERE scope=? AND version=?", (result["topic"], result["status"], result["summary"], result["mood"], intensity, now, scope, turn["version"]))
            db.execute("UPDATE turns SET analysis=? WHERE scope=? AND id=?", (json.dumps(result, ensure_ascii=False), scope, turn_id))
            return True

    def context(self, scope, query, now=None):
        now = time.time() if now is None else now
        with self.db() as db:
            row = db.execute("SELECT * FROM dialogue_state WHERE scope=?", (scope,)).fetchone()
            state = dict(row) if row else None
            facts = [dict(r) for r in db.execute("SELECT topic,polarity,quote,updated FROM facts WHERE scope=? ORDER BY updated DESC LIMIT 100", (scope,))]
            previous = db.execute("SELECT user_text FROM turns WHERE scope=? AND analysis IS NOT NULL ORDER BY received DESC,version DESC LIMIT 1", (scope,)).fetchone()
        # A small exact/subphrase retriever, explicitly not a vector-memory engine.
        query = str(query)[:2000]
        relevant = [f for f in facts if f["topic"] in query or any(query[i:i+2] in f["topic"] for i in range(max(0, len(query)-1)) if query[i:i+2].strip())][:3]
        if not relevant and any(cue in query for cue in ("我喜欢什么", "我的偏好", "记得我", "我的喜好")):
            relevant = facts[:3]
        data = {"user_preferences": relevant, "topic": None, "mood": "calm", "intensity": 0}
        if state:
            age = max(0, now-state["updated"])
            data["fresh_start"] = age >= 900
            if age < 900:
                data["topic"] = {k: state[k] for k in ("topic", "status", "summary")}
                speaker = SPEAKER.match(previous[0]) if previous else None
                if speaker:
                    data["topic"]["speaker_id"] = speaker[1]
            if age < 7200:
                data.update(mood=state["mood"], intensity=max(0, state["intensity"]-int(age//1800)))
        return data

    def import_notes(self, scope, notes):
        """Operator-reviewed ordinary legacy notes, never an implicit global-file scan."""
        if not isinstance(notes, list) or len(notes) > 100:
            raise ValueError("bounded, reviewed notes required")
        with self.db() as db:
            for item in notes:
                quote, source = item.get("quote"), item.get("source")
                if not isinstance(quote, str) or not 1 <= len(quote) <= 600 or not isinstance(source, str) or not 1 <= len(source) <= 200:
                    raise ValueError("invalid historical note")
                nid = hashlib.sha256((source+"\0"+quote).encode()).hexdigest()
                db.execute("INSERT OR IGNORE INTO historical_notes VALUES(?,?,?,?,?)", (scope, nid, quote, source, time.time()))
            db.execute("DELETE FROM historical_notes WHERE scope=? AND id NOT IN (SELECT id FROM historical_notes WHERE scope=? ORDER BY imported DESC LIMIT 100)", (scope, scope))

    def memory_documents(self, scope, now=None):
        """Current ordinary records plus explicitly reviewed scoped historical notes."""
        now = time.time() if now is None else now
        with self.db() as db:
            facts = [dict(r) for r in db.execute("SELECT topic,polarity,quote,source_id,updated FROM facts WHERE scope=? ORDER BY updated DESC LIMIT 100", (scope,))]
            turns = [dict(r) for r in db.execute("SELECT id,analysis,received,user_text FROM turns WHERE scope=? AND analysis IS NOT NULL AND received>=? ORDER BY received DESC LIMIT 100", (scope, now-7*86400))]
            history = [dict(r) for r in db.execute("SELECT * FROM historical_notes WHERE scope=? ORDER BY imported DESC LIMIT 100", (scope,))]
        docs = []
        for note in history:
            docs.append({"id": "legacy:"+note["id"], "kind": "historical_note", "text": note["quote"],
                         "record": {"quote": note["quote"], "source": note["source"], "occurred_at": None,
                                    "imported_at": note["imported"], "meaning": "旧资料，原发生时间未知，不代表今天。"}})
        for fact in facts:
            docs.append({"id": "fact:"+fact["topic"], "kind": "preference", "text": fact["quote"], "record": fact})
        for turn in turns:
            analysis = json.loads(turn["analysis"])
            record = {k: analysis[k] for k in ("topic", "status", "summary", "quote")}
            record.update(source_id=turn["id"], occurred_at=turn["received"])
            speaker = SPEAKER.match(turn["user_text"])
            if speaker:
                record["speaker_id"] = speaker[1]
            docs.append({"id": "turn:"+turn["id"], "kind": "episode", "text": analysis["topic"]+"。"+analysis["quote"]+"。"+analysis["summary"], "record": record})
        return docs
