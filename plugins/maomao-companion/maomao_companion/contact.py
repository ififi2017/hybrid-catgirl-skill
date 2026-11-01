"""One persistent ledger for optional contact from independently scheduled sources.

The caller owns authentication and delivery. A reservation is not a sent message.
Message bodies never enter this database. Public/group scopes cannot initiate contact.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


STAGES = (
    ("想你了", 120, 4), ("换个话头", 100, 6),
    ("自己找乐子", 80, 8), ("小声报平安", 60, 12),
    ("安静陪着", 40, 24), ("最后留言", 50, 24),
)
SOURCES = {"lonely", "activity", "reminder"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def epoch(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid time")
    return value


@dataclass(frozen=True)
class Policy:
    timezone: str = "Asia/Taipei"
    daily_limit: int = 10
    quiet_minutes: int = 75
    cooldown_hours: float = 4
    stop_after: int = 6
    dnd_start: int = 23
    dnd_end: int = 8
    reservation_seconds: int = 300

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if not (0 <= self.daily_limit <= 100 and 0 <= self.quiet_minutes <= 1440
                and 0 < self.cooldown_hours <= 168 and 1 <= self.stop_after <= len(STAGES)
                and 0 <= self.dnd_start <= 23 and 0 <= self.dnd_end <= 23
                and 10 <= self.reservation_seconds <= 3600):
            raise ValueError("invalid contact policy")


class ContactLedger:
    def __init__(self, path, policy=None):
        self.path, self.policy = Path(path), policy or Policy()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS incoming(
                    scope TEXT NOT NULL, id TEXT NOT NULL, received REAL NOT NULL,
                    PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS contacts(
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, source TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
                    dispatched REAL, finished REAL, status TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS contact_scope ON contacts(scope,created);
                CREATE TABLE IF NOT EXISTS quiet(scope TEXT PRIMARY KEY, until REAL NOT NULL);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        # Each hook/CLI process owns its connection; SQLite serializes reservations.
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
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

    @staticmethod
    def scope(platform, chat_id, user_id, chat_type="dm"):
        if chat_type != "dm" or not all(isinstance(v, str) and v for v in (platform, chat_id, user_id)):
            raise ValueError("optional contact needs a configured private recipient")
        # The database lives in one Hermes profile; identities remain profile-local.
        return digest([platform, chat_id, user_id, chat_type])

    def incoming(self, scope, message_id, now=None):
        if not message_id:
            return
        now = epoch(time.time() if now is None else now)
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO incoming VALUES(?,?,?)", (scope, str(message_id), now))

    def goodnight(self, scope, now=None):
        now = epoch(time.time() if now is None else now)
        local = datetime.fromtimestamp(now, ZoneInfo(self.policy.timezone))
        wake = local.replace(hour=self.policy.dnd_end, minute=0, second=0, microsecond=0)
        if wake <= local:
            wake += timedelta(days=1)
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO quiet VALUES(?,?)", (scope, wake.timestamp()))

    def import_sent(self, scope, entries):
        """Import acknowledged legacy history once, without importing message bodies."""
        with self.transaction() as db:
            for entry in entries:
                at, fingerprint = epoch(entry["time"]), entry["fingerprint"]
                key = digest(["legacy", scope, at, fingerprint])
                db.execute("INSERT OR IGNORE INTO contacts VALUES(?,?,?,?,?,?,?,?,?)",
                           (key, scope, "lonely", fingerprint, at, at, at, at, "sent"))

    def _state(self, db, scope, now):
        p = self.policy
        # A crash before dispatch frees the slot; possible sends keep their charge.
        db.execute("UPDATE contacts SET status='cancelled' WHERE status='reserved' AND expires<=?", (now,))
        db.execute("UPDATE contacts SET status='uncertain',finished=expires WHERE status='dispatching' AND expires<=?", (now,))
        last_in = db.execute("SELECT coalesce(max(received),0) FROM incoming WHERE scope=?", (scope,)).fetchone()[0]
        rows = db.execute("SELECT * FROM contacts WHERE scope=? AND status IN ('sent','uncertain','dispatching','reserved')", (scope,)).fetchall()
        local = datetime.fromtimestamp(now, ZoneInfo(p.timezone))
        day = local.date()
        used = sum(datetime.fromtimestamp(r["dispatched"] or r["created"], local.tzinfo).date() == day for r in rows)
        sent = [r for r in rows if r["status"] != "reserved"]
        unanswered = sum((r["dispatched"] or r["created"]) > last_in for r in sent)
        latest = max((r["dispatched"] or r["created"] for r in sent), default=0)
        stage = STAGES[min(unanswered, len(STAGES)-1)]
        # Backoff is shared by every optional source; it cannot be bypassed by renaming it.
        wait = max(p.cooldown_hours, STAGES[min(max(unanswered-1, 0), len(STAGES)-1)][2]) * 3600
        quiet = db.execute("SELECT until FROM quiet WHERE scope=?", (scope,)).fetchone()
        hour = local.hour
        in_dnd = (p.dnd_start == p.dnd_end or
                  (p.dnd_start < p.dnd_end and p.dnd_start <= hour < p.dnd_end) or
                  (p.dnd_start > p.dnd_end and (hour >= p.dnd_start or hour < p.dnd_end)))
        reason = ("goodnight" if quiet and now < quiet[0] else
                  "dnd" if in_dnd else
                  "future_activity" if last_in > now or any(r["created"] > now for r in rows) else
                  "recent_chat" if last_in and now-last_in < p.quiet_minutes*60 else
                  "pending" if any(r["status"] in {"reserved", "dispatching"} for r in rows) else
                  "daily_limit" if used >= p.daily_limit else
                  "waiting_for_reply" if unanswered >= p.stop_after else
                  "cooldown" if latest and now-latest < wait else "")
        return {"allowed": not reason, "reason": reason, "daily_used": used,
                "unanswered": unanswered, "stage": stage[0], "max_chars": stage[1],
                "next_interval_hours": stage[2], "last_incoming": last_in}

    def check(self, scope, now=None):
        now = epoch(time.time() if now is None else now)
        with self.transaction() as db:
            return self._state(db, scope, now)

    def reserve(self, scope, source, request_id, fingerprint, now=None):
        if source not in SOURCES or not request_id or not fingerprint:
            raise ValueError("invalid optional contact")
        now = epoch(time.time() if now is None else now)
        key = digest([scope, source, request_id])
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM contacts WHERE id=?", (key,)).fetchone():
                raise PermissionError("duplicate_request")
            state = self._state(db, scope, now)
            if not state["allowed"]:
                raise PermissionError(state["reason"])
            if db.execute("SELECT 1 FROM contacts WHERE scope=? AND fingerprint=? AND status IN ('sent','uncertain','dispatching') AND (created>? OR status='uncertain')", (scope, fingerprint, now-86400)).fetchone():
                raise PermissionError("duplicate_content")
            db.execute("INSERT INTO contacts VALUES(?,?,?,?,?,?,NULL,NULL,'reserved')",
                       (key, scope, source, fingerprint, now, now+self.policy.reservation_seconds))
        return key

    def dispatch(self, ticket, now=None):
        now = epoch(time.time() if now is None else now)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM contacts WHERE id=?", (ticket,)).fetchone()
            if not row or row["status"] != "reserved" or now >= row["expires"]:
                raise PermissionError("reservation_expired")
            # Exclude this ticket while rechecking all other guards.
            db.execute("UPDATE contacts SET status='checking' WHERE id=?", (ticket,))
            state = self._state(db, row["scope"], now)
            if not state["allowed"]:
                db.execute("UPDATE contacts SET status='cancelled',finished=? WHERE id=?", (now, ticket))
                error = state["reason"]
            else:
                db.execute("UPDATE contacts SET status='dispatching',dispatched=? WHERE id=?", (now, ticket))
                error = None
        if error:
            raise PermissionError(error)

    def finish(self, ticket, outcome, now=None):
        if outcome not in {"sent", "uncertain", "cancelled"}:
            raise ValueError("invalid outcome")
        now = epoch(time.time() if now is None else now)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM contacts WHERE id=?", (ticket,)).fetchone()
            if not row or row["status"] not in {"reserved", "dispatching"}:
                return
            status = ("cancelled" if row["dispatched"] is None else
                      "uncertain" if outcome == "cancelled" else outcome)
            db.execute("UPDATE contacts SET status=?,finished=? WHERE id=?", (status, now, ticket))
