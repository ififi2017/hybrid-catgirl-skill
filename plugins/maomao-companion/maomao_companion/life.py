"""Persistent agent goals and observed public sources, without a scheduler or executor."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import time
import uuid
from urllib.parse import urlsplit

from .dialogue import DialogueStore


def text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("missing or oversized text")
    return value.strip()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def public_url(value):
    if not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").rstrip(".")
        if parts.scheme not in {"https", "http"} or not host or parts.username or parts.password:
            return False
        if host in {"localhost", "metadata.google.internal"} or host.endswith((".local", ".internal", ".localhost")):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if "." not in host or host.isdigit():
                return False
        return not any(token in parts.query.lower() for token in ("token=", "api_key=", "secret=", "signature=", "password="))
    except ValueError:
        return False


class LifeStore(DialogueStore):
    """Reuse the connection helper, not the ordinary-chat tables or their content."""
    def __init__(self, path):
        from pathlib import Path
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS goals(
                  scope TEXT NOT NULL,id TEXT NOT NULL,title TEXT NOT NULL,done_when TEXT NOT NULL,
                  next_step TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL,
                  request_key TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
                  PRIMARY KEY(scope,id),UNIQUE(scope,request_key));
                CREATE TABLE IF NOT EXISTS sources(
                  scope TEXT NOT NULL,id TEXT NOT NULL,goal_id TEXT NOT NULL,kind TEXT NOT NULL,
                  tool TEXT NOT NULL,url TEXT NOT NULL,excerpt TEXT NOT NULL,fingerprint TEXT NOT NULL,
                  tool_call_id TEXT NOT NULL,created REAL NOT NULL,
                  PRIMARY KEY(scope,id),UNIQUE(scope,goal_id,fingerprint));
                CREATE TABLE IF NOT EXISTS attempts(
                  scope TEXT NOT NULL,turn_id TEXT NOT NULL,goal_id TEXT NOT NULL,
                  baseline TEXT NOT NULL,status TEXT NOT NULL,started REAL NOT NULL,finished REAL,
                  PRIMARY KEY(scope,turn_id));
                CREATE TABLE IF NOT EXISTS completions(
                  scope TEXT NOT NULL,goal_id TEXT NOT NULL,source_id TEXT NOT NULL,quote TEXT NOT NULL,
                  created REAL NOT NULL,PRIMARY KEY(scope,goal_id));
                CREATE TABLE IF NOT EXISTS interests(
                  scope TEXT NOT NULL,topic TEXT NOT NULL,polarity INTEGER NOT NULL,source_id TEXT NOT NULL,
                  source_fingerprint TEXT NOT NULL,reason TEXT NOT NULL,created REAL NOT NULL,
                  PRIMARY KEY(scope,topic,source_fingerprint));
                CREATE TABLE IF NOT EXISTS experiences(
                  scope TEXT NOT NULL,id TEXT NOT NULL,source_id TEXT NOT NULL,summary TEXT NOT NULL,
                  quote TEXT NOT NULL,created REAL NOT NULL,shared REAL,
                  PRIMARY KEY(scope,id),UNIQUE(scope,source_id));
            """)
        self.path.chmod(0o600)

    def goals(self, scope):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM goals WHERE scope=? ORDER BY updated DESC,id LIMIT 100", (scope,))]

    def goal(self, scope, goal_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM goals WHERE scope=? AND id=?", (scope, goal_id)).fetchone()
            return dict(row) if row else None

    def create(self, scope, title, done_when, next_step, request_key):
        title, done_when, next_step = text(title, 120), text(done_when, 300), text(next_step, 300)
        request_key = text(request_key, 200)
        with self.db() as db:
            old = db.execute("SELECT * FROM goals WHERE scope=? AND request_key=?", (scope, request_key)).fetchone()
            if old:
                if (old["title"], old["done_when"], old["next_step"]) != (title, done_when, next_step):
                    raise ValueError("request reused with changed goal")
                return dict(old)
            if db.execute("SELECT count(*) FROM goals WHERE scope=? AND status IN ('ready','paused')", (scope,)).fetchone()[0] >= 8:
                raise ValueError("finish or cancel an existing goal first")
            if db.execute("SELECT count(*) FROM goals WHERE scope=?", (scope,)).fetchone()[0] >= 100:
                raise ValueError("goal history limit reached")
            gid, now = uuid.uuid4().hex, time.time()
            db.execute("INSERT INTO goals VALUES(?,?,?,?,?,'ready',1,?,?,?)", (scope, gid, title, done_when, next_step, request_key, now, now))
        return self.goal(scope, gid)

    def _progress(self, db, scope, goal_id):
        return fingerprint([r[0] for r in db.execute("SELECT fingerprint FROM sources WHERE scope=? AND goal_id=? AND kind='read' ORDER BY fingerprint", (scope, goal_id))])

    def select(self, scope, goal_id, turn_id):
        with self.db() as db:
            # The planner only looks back three hours. Bound abandoned/repeated attempts.
            db.execute("UPDATE attempts SET status='interrupted',finished=? WHERE scope=? AND status='selected' AND started<?", (time.time(), scope, time.time()-86400))
            db.execute("DELETE FROM attempts WHERE scope=? AND finished<?", (scope, time.time()-3*86400))
            goal = db.execute("SELECT * FROM goals WHERE scope=? AND id=?", (scope, goal_id)).fetchone()
            if not goal or goal["status"] not in {"ready", "paused"}:
                raise ValueError("goal is unavailable in this private scope")
            existing = db.execute("SELECT * FROM attempts WHERE scope=? AND turn_id=?", (scope, turn_id)).fetchone()
            if existing:
                if existing["goal_id"] != goal_id or existing["status"] != "selected":
                    raise ValueError("turn already selected or finished another goal")
                return dict(goal)
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,NULL)", (scope, turn_id, goal_id, self._progress(db, scope, goal_id), "selected", time.time()))
        return dict(goal)

    def update(self, scope, goal_id, revision, status, next_step=None, evidence_id="", quote=""):
        if type(revision) is not int or not isinstance(status, str) or status not in {"ready", "paused", "completed", "cancelled"}:
            raise ValueError("invalid goal revision or status")
        if next_step is not None:
            next_step = text(next_step, 300)
        with self.db() as db:
            row = db.execute("SELECT * FROM goals WHERE scope=? AND id=?", (scope, goal_id)).fetchone()
            if not row or row["revision"] != revision:
                raise ValueError("read the current goal revision before updating")
            if row["status"] in {"completed", "cancelled"}:
                raise ValueError("finished goals are immutable")
            if status == "completed":
                source = db.execute("SELECT * FROM sources WHERE scope=? AND goal_id=? AND id=? AND kind='read'", (scope, goal_id, evidence_id)).fetchone()
                quote = text(quote, 300)
                if not source or quote not in source["excerpt"]:
                    raise ValueError("completion needs a quote from an observed page under this goal")
                db.execute("INSERT INTO completions VALUES(?,?,?,?,?)", (scope, goal_id, evidence_id, quote, time.time()))
            db.execute("UPDATE goals SET status=?,next_step=?,revision=revision+1,updated=? WHERE scope=? AND id=?", (status, next_step or row["next_step"], time.time(), scope, goal_id))
        return self.goal(scope, goal_id)

    def observe(self, scope, goal_id, turn_id, tool, tool_call_id, result, status):
        """Host hook only. Not exposed as a tool accepting model-written evidence."""
        if tool not in {"web_search", "web_extract"} or status != "ok" or not tool_call_id:
            return []
        if isinstance(result, str):
            if len(result) > 200_000:
                return []
            try:
                result = json.loads(result)
            except ValueError:
                return []
        if not isinstance(result, dict) or result.get("error") or result.get("success") is False:
            return []
        if tool == "web_search":
            data = result.get("data")
            rows = data.get("web", []) if isinstance(data, dict) else []
        else:
            rows = result.get("results", [])
        if not isinstance(rows, list):
            return []
        added = []
        with self.db() as db:
            attempt = db.execute("SELECT * FROM attempts WHERE scope=? AND turn_id=? AND goal_id=? AND status='selected'", (scope, turn_id, goal_id)).fetchone()
            goal = db.execute("SELECT status FROM goals WHERE scope=? AND id=?", (scope, goal_id)).fetchone()
            if not attempt or not goal or goal[0] not in {"ready", "paused"}:
                return []
            count = db.execute("SELECT count(*) FROM sources WHERE scope=? AND goal_id=?", (scope, goal_id)).fetchone()[0]
            for entry in rows[:5]:
                if count >= 100 or not isinstance(entry, dict) or entry.get("error") or entry.get("success") is False or entry.get("blocked_by_policy"):
                    continue
                url = entry.get("url")
                if not public_url(url):
                    continue
                value = entry.get("description", "") if tool == "web_search" else next((entry[k] for k in ("markdown", "text", "content") if isinstance(entry.get(k), str)), "")
                if not isinstance(value, str) or len(value.strip()) < 30:
                    continue
                excerpt = value.strip()[:1200]
                kind = "search" if tool == "web_search" else "read"
                sig = fingerprint([kind, url, excerpt])
                existing = db.execute("SELECT id FROM sources WHERE scope=? AND goal_id=? AND fingerprint=?", (scope, goal_id, sig)).fetchone()
                if existing:
                    added.append(existing[0])
                    continue
                sid = uuid.uuid4().hex
                db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)", (scope, sid, goal_id, kind, tool, url, excerpt, sig, str(tool_call_id)[:200], time.time()))
                added.append(sid)
                count += 1
        return added

    def sources(self, scope, goal_id=None):
        with self.db() as db:
            sql = "SELECT id,goal_id,kind,tool,url,excerpt,created FROM sources WHERE scope=?"
            values = [scope]
            if goal_id:
                sql += " AND goal_id=?"
                values.append(goal_id)
            return [dict(r) for r in db.execute(sql+" ORDER BY created DESC,id LIMIT 8", values)]

    def finish_attempt(self, scope, turn_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM attempts WHERE scope=? AND turn_id=? AND status='selected'", (scope, turn_id)).fetchone()
            if row:
                status = "progress" if row["baseline"] != self._progress(db, scope, row["goal_id"]) else "no_progress"
                db.execute("UPDATE attempts SET status=?,finished=? WHERE scope=? AND turn_id=?", (status, time.time(), scope, turn_id))

    def interrupt(self, scope, turn_id):
        # Reload/cancellation isn't proof that work failed or that the agent rested.
        with self.db() as db:
            db.execute("UPDATE attempts SET status='interrupted',finished=? WHERE scope=? AND turn_id=? AND status='selected'", (time.time(), scope, turn_id))

    def interest(self, scope, evidence_id, topic, polarity, quote):
        topic, quote = text(topic, 80), text(quote, 300)
        if type(polarity) is not int or polarity not in {-1, 1}:
            raise ValueError("interest polarity must be -1 or 1")
        with self.db() as db:
            source = db.execute("SELECT * FROM sources WHERE scope=? AND id=? AND kind='read'", (scope, evidence_id)).fetchone()
            if not source or quote not in source["excerpt"]:
                raise ValueError("agent interest needs an observed page and a real quote")
            if db.execute("SELECT count(*) FROM interests WHERE scope=?", (scope,)).fetchone()[0] >= 500:
                raise ValueError("interest history limit reached")
            db.execute("INSERT INTO interests VALUES(?,?,?,?,?,?,?) ON CONFLICT(scope,topic,source_fingerprint) DO UPDATE SET polarity=excluded.polarity,reason=excluded.reason", (scope, topic, polarity, evidence_id, source["fingerprint"], quote, time.time()))

    def interests(self, scope, now=None):
        now = time.time() if now is None else now
        with self.db() as db:
            rows = db.execute("SELECT * FROM interests WHERE scope=? ORDER BY created DESC", (scope,)).fetchall()
        topics = {}
        for row in rows:
            item = topics.setdefault(row["topic"], {"topic": row["topic"], "subject": "agent", "score": 0., "source_ids": []})
            item["score"] += row["polarity"] * 0.5**(max(0, now-row["created"])/(60*86400))
            item["source_ids"].append(row["source_id"])
        return sorted(topics.values(), key=lambda row: (-row["score"], row["topic"]))[:8]

    def plan(self, scope, now=None):
        """Selection is intention, not execution. Merely asking never consumes an attempt."""
        now = time.time() if now is None else now
        candidates, excluded = [], []
        interests = self.interests(scope, now)
        for goal in self.goals(scope):
            if goal["status"] != "ready":
                continue
            with self.db() as db:
                sig = self._progress(db, scope, goal["id"])
                attempts = db.execute("SELECT * FROM attempts WHERE scope=? AND goal_id=? AND finished>? ORDER BY finished DESC LIMIT 3", (scope, goal["id"], now-3*3600)).fetchall()
            if sum(a["status"] == "no_progress" and a["baseline"] == sig for a in attempts) >= 2:
                excluded.append({"goal_id": goal["id"], "reason": "two_attempts_without_new_read_evidence"})
                continue
            bonus = 8 if any(i["score"] > 0 and i["topic"] in goal["title"]+goal["next_step"] for i in interests) else 0
            candidates.append((60+min(12,int(max(0,now-goal["updated"])/3600))+bonus,goal))
        candidates.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        if candidates:
            score, goal = candidates[0]
            return {"action": "continue", "goal_id": goal["id"], "next_step": goal["next_step"], "score": score, "decision_only": True, "excluded": excluded}
        return {"action": "rest", "decision_only": True, "reason": "no_ready_goal_or_no_new_progress", "excluded": excluded}

    def context(self, scope):
        return {"goals": [g for g in self.goals(scope) if g["status"] in {"ready", "paused"}][:3],
                "agent_interests": self.interests(scope), "plan": self.plan(scope),
                "meaning": "目标与安排是意图；工具来源是实际观察，不等于已独立核实；不是主人偏好。"}

    def experience(self, scope, source_id, summary, quote):
        summary, quote = text(summary, 300), text(quote, 300)
        with self.db() as db:
            source = db.execute("SELECT * FROM sources WHERE scope=? AND id=? AND kind='read'", (scope, source_id)).fetchone()
            if not source or quote not in source["excerpt"]:
                raise ValueError("experience requires a real read source and exact quote")
            db.execute("INSERT OR IGNORE INTO experiences VALUES(?,?,?,?,?,?,NULL)", (scope, fingerprint([scope, source_id]), source_id, summary, quote, time.time()))

    def shareable(self, scope, now=None):
        now = time.time() if now is None else now
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT e.id,e.summary,e.quote,e.created,s.url FROM experiences e JOIN sources s ON e.scope=s.scope AND e.source_id=s.id WHERE e.scope=? AND e.shared IS NULL AND e.created>? ORDER BY e.created DESC LIMIT 2", (scope, now-7*86400))]

    def shared(self, scope, message):
        # Only an accepted send with the actual source link acknowledges an activity share.
        with self.db() as db:
            for row in db.execute("SELECT e.id,s.url FROM experiences e JOIN sources s ON e.scope=s.scope AND e.source_id=s.id WHERE e.scope=? AND e.shared IS NULL", (scope,)).fetchall():
                if row["url"] in message:
                    db.execute("UPDATE experiences SET shared=? WHERE scope=? AND id=?", (time.time(), scope, row["id"]))
