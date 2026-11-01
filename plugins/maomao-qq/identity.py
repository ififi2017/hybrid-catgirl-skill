"""Resolve trusted host session aliases without accepting a model-selected group."""
import sqlite3
import time
from pathlib import Path


def recent_group_replies(root, group, now=None):
    """Trusted delivered text, scoped to this QQ group, including former per-user sessions."""
    if not group or group.startswith("dm:"):
        return []
    try:
        with sqlite3.connect((Path(root)/"state.db").resolve().as_uri()+"?mode=ro", uri=True, timeout=1) as db:
            rows=db.execute("SELECT content,created_at FROM delivery_obligations WHERE platform='qqbot' AND chat_id=? AND state='delivered' AND created_at>=? AND created_at<=? ORDER BY created_at DESC LIMIT 8",(group,(now or time.time())-1800,now or time.time())).fetchall()
        return [{"role":"assistant","text":"\n".join(line for line in text.splitlines() if not line.startswith("MEDIA:"))[:1200],"sent_at":stamp} for text,stamp in reversed(rows) if text]
    except (OSError,sqlite3.Error):
        return []


def conversation_for_session(sessions, session_id):
    if not isinstance(sessions, dict) or not session_id:
        raise ValueError("trusted session required")
    identities = set()
    for row in sessions.values():
        if not isinstance(row, dict) or row.get("session_id") != session_id:
            continue
        source = row.get("origin") or row.get("source") or {}
        if not isinstance(source, dict):
            raise ValueError("incomplete session identity")
        values = tuple(source.get(k) for k in ("platform", "chat_type", "chat_id"))
        if not all(isinstance(v, str) and v for v in values):
            raise ValueError("incomplete session identity")
        identities.add(values)
    if len(identities) != 1:
        raise ValueError("ambiguous session identity")
    platform, kind, group = next(iter(identities))
    if platform != "qqbot" or kind not in {"group","dm"}:
        raise ValueError("only available in a QQ conversation")
    return {"platform":platform,"chat_type":kind,"chat_id":group,
            "library_key":group if kind=="group" else "dm:"+group}


def group_for_session(sessions,session_id):
    source=conversation_for_session(sessions,session_id)
    if source["chat_type"]!="group": raise ValueError("QQ group required")
    return source["chat_id"]
