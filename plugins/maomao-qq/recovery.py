"""Keep transport recovery out of chat text without defeating fragment idempotency."""
import hashlib
import time

MARKERS = (
    "♻️ Recovered reply — the gateway restarted during delivery, so this may be a duplicate:\n\n",
    "♻️ Recovered reply — the messaging platform reconnected after the original delivery failed, so this may be a duplicate:\n\n",
    "♻️ Recovered reply — the messaging platform's rate limit refused the original, so part of it may already have arrived above:\n\n",
)


def recovery_body(content):
    for marker in MARKERS:
        if isinstance(content, str) and content.startswith(marker):
            return content[len(marker):], True
    return content, False


def planned_maximum(ledger, chat, anchor, content, maximum):
    """Persist only a digest and split count, so replay has the original fingerprints."""
    digest = hashlib.sha256(content.encode()).hexdigest()
    with ledger.db() as db:
        db.execute("CREATE TABLE IF NOT EXISTS qq_bubble_plans(chat TEXT,anchor TEXT,digest TEXT,maximum INTEGER,created REAL,PRIMARY KEY(chat,anchor,digest))")
        db.execute("DELETE FROM qq_bubble_plans WHERE created<?", (time.time()-7*86400,))
        db.execute("INSERT OR IGNORE INTO qq_bubble_plans VALUES(?,?,?,?,?)", (str(chat),str(anchor),digest,maximum,time.time()))
        row = db.execute("SELECT maximum FROM qq_bubble_plans WHERE chat=? AND anchor=? AND digest=?", (str(chat),str(anchor),digest)).fetchone()
        return int(row[0])


def recovery_anchor(ledger, chat, content):
    digest=hashlib.sha256(content.encode()).hexdigest()
    with ledger.db() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='qq_bubble_plans'").fetchone()
        if not exists:return None
        rows=db.execute("SELECT DISTINCT anchor FROM qq_bubble_plans WHERE chat=? AND digest=?",(str(chat),digest)).fetchall()
        return str(rows[0][0]) if len(rows)==1 else None
