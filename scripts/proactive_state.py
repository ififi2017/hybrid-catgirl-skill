#!/usr/bin/env python3
"""Small, dependency-free helpers for proactive reminder state."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_SESSION_GLOB = "session_*.json"
DEFAULT_TRANSCRIPT_GLOB = "*.jsonl"


def latest_user_activity(
    sessions_dir: str | os.PathLike[str],
    *,
    state_time: datetime | None = None,
    session_glob: str = DEFAULT_SESSION_GLOB,
    transcript_glob: str = DEFAULT_TRANSCRIPT_GLOB,
) -> datetime | None:
    """Return newest non-cron activity, preferring live session JSON mtime."""
    root = Path(sessions_dir).expanduser()
    candidates = [p for p in root.glob(session_glob) if "cron_" not in p.name]
    if not candidates:
        candidates = [p for p in root.glob(transcript_glob) if "cron_" not in p.name]
    session_time = None
    if candidates:
        session_time = datetime.fromtimestamp(max(p.stat().st_mtime for p in candidates))
    if state_time and session_time:
        return max(state_time, session_time)
    return state_time or session_time


def effective_last_activity(
    sessions_dir: str | os.PathLike[str], state_timestamp: str | None
) -> datetime | None:
    """Combine a stored ISO timestamp with live session activity."""
    state_time = datetime.fromisoformat(state_timestamp) if state_timestamp else None
    return latest_user_activity(sessions_dir, state_time=state_time)


def minutes_since(timestamp: datetime | None, *, now: datetime | None = None) -> float | None:
    """Return elapsed minutes, or None when there is no timestamp."""
    if timestamp is None:
        return None
    reference = now or datetime.now()
    return (reference - timestamp).total_seconds() / 60


def reserve_slot(
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    interval_minutes: int = 240,
    count_key: str = "proactive_count_today",
) -> dict[str, Any]:
    """Reserve a proactive message before generating or sending it."""
    now = now or datetime.now()
    count = int(state.get(count_key, 0)) + 1
    state[count_key] = count
    state["last_proactive_time"] = now.isoformat()
    state["next_proactive_time"] = (
        now + timedelta(minutes=interval_minutes)
    ).isoformat()
    return state


def normalize_message(message: str) -> str:
    """Convert shell-passed escaped newlines and tabs into real characters."""
    return message.replace("\\n", "\n").replace("\\t", "\t")


def append_message(
    history: dict[str, Any],
    role: str,
    content: str,
    *,
    now: datetime | None = None,
    max_messages: int = 50,
) -> dict[str, Any]:
    """Append a bounded chat-history entry."""
    history.setdefault("messages", []).append({
        "role": role,
        "content": normalize_message(content),
        "time": (now or datetime.now()).isoformat(),
    })
    history["messages"] = history["messages"][-max_messages:]
    return history


if __name__ == "__main__":
    print("Import helpers from this module.")
