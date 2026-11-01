"""One atomic embedding budget shared by memory and memes in a channel."""
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class OutboundBudget:
    def __init__(self, path, limit=200):
        self.path, self.limit = Path(path), limit
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def reserve(self, scope):
        now = time.time()
        day = datetime.fromtimestamp(now, ZoneInfo("Asia/Taipei")).date().isoformat()
        db = sqlite3.connect(self.path, timeout=3)
        try:
            db.execute("CREATE TABLE IF NOT EXISTS calls(scope TEXT NOT NULL,day TEXT NOT NULL,created REAL NOT NULL)")
            db.commit(); db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM calls WHERE created<?", (now-7*86400,))
            count = db.execute("SELECT count(*) FROM calls WHERE scope=? AND day=?", (scope, day)).fetchone()[0]
            if count >= self.limit:
                raise PermissionError("shared channel embedding budget exhausted")
            db.execute("INSERT INTO calls VALUES(?,?,?)", (scope, day, now)); db.commit()
        finally:
            db.close()
        self.path.chmod(0o600)


class BudgetedEmbeddings:
    def __init__(self, client, budget, scope):
        self.client, self.budget, self.scope = client, budget, scope
        self.model, self.dimensions = client.model, client.dimensions

    def embed(self, *args, **kwargs):
        self.budget.reserve(self.scope)
        return self.client.embed(*args, **kwargs)
