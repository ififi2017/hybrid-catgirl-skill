"""Optional compatibility bridge; install into the existing scheduler's module namespace.

The existing generator, persona, credentials and scheduler stay outside this package.
Normal replies never call this adapter. It guards only its configured private target.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .contact import digest
from .runtime import configured
from .runtime import home
from .life import LifeStore
from .dialogue import DialogueStore


def install(namespace):
    if namespace.get("_companion_installed"):
        return
    original_check = namespace["precheck"]
    original_send = namespace["send_feishu_message"]
    original_goodnight = namespace["set_dnd_goodnight"]
    original_smart = namespace["smart_check"]

    def recent_context(max_sessions=3):
        # Do not let a legacy JSONL fallback scan archived QQ/Telegram or private turns.
        current = configured()
        path = home()/"state/maomao-companion/dialogue.sqlite3"
        if not current or not path.exists():
            return []
        try:
            import time
            store = DialogueStore(path)
            with store.db() as db:
                rows = db.execute("SELECT user_text,assistant_text,received FROM turns WHERE scope=? AND received>=? ORDER BY received DESC LIMIT 6", (current[2], time.time()-48*3600)).fetchall()
            if not rows:
                return []
            messages = []
            for row in reversed(rows):
                messages.append({"role": "user", "content": row["user_text"][:200]})
                if row["assistant_text"]:
                    messages.append({"role": "assistant", "content": row["assistant_text"][:200], "meaning": "generated text; delivery unknown"})
            return [{"source": "scoped ordinary Feishu store", "last_active": rows[0]["received"], "messages": messages[-6:]}]
        except Exception:
            return []

    def smart_check():
        result = original_smart()
        current = configured()
        path = home()/"state/maomao-companion/life.sqlite3"
        if result.get("send") and current and path.exists():
            result["real_activity"] = LifeStore(path).shareable(current[2])
            result["real_activity_rule"] = "有相关真实阅读成果时可自然分享，并附来源URL；这是读到的资料，不是亲身经历。没有成果就普通陪伴，不编造浏览。"
        return result

    def sync(state):
        current = configured()
        if current is None:
            return None
        ledger, target, scope = current
        if target["platform"] != "feishu" or target["chat_id"] != namespace.get("FEISHU_HOME_CHANNEL"):
            raise PermissionError("configured recipient does not match existing sender")
        last = namespace["effective_last_interaction"](state)
        tz = ZoneInfo(ledger.policy.timezone)
        if last:
            stamp = (last if last.tzinfo else last.replace(tzinfo=tz)).timestamp()
            ledger.incoming(scope, "legacy:"+str(stamp), stamp)
        entries = []
        for item in namespace["proactive_history"](state):
            dt = datetime.fromisoformat(item["time"])
            at = (dt if dt.tzinfo else dt.replace(tzinfo=tz)).timestamp()
            entries.append({"time": at, "fingerprint": digest(item.get("message", ""))})
        # Preserve prior history once at activation. Later sends already have tickets.
        with ledger.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS migration(scope TEXT PRIMARY KEY)")
            exists = db.execute("SELECT 1 FROM migration WHERE scope=?", (scope,)).fetchone()
            if not exists:
                # Import in the same transaction: simultaneous cron/gateway reads cannot double-import.
                for entry in entries:
                    key = digest(["legacy", scope, entry["time"], entry["fingerprint"]])
                    at = entry["time"]
                    db.execute("INSERT OR IGNORE INTO contacts VALUES(?,?,?,?,?,?,?,?,?)",
                               (key, scope, "lonely", entry["fingerprint"], at, at, at, at, "sent"))
                db.execute("INSERT INTO migration VALUES(?)", (scope,))
        return current

    def precheck(state, now):
        skip = original_check(state, now)
        if skip:
            return skip
        try:
            current = sync(state)
            if current:
                ledger, _, scope = current
                decision = ledger.check(scope)
                if not decision["allowed"]:
                    return {"reason": "companion_"+decision["reason"]}
        except Exception:
            # Once configured, a failed coordination check must not send unaccounted messages.
            return {"reason": "companion_unavailable"}
        return None

    def send(message, chat_id=None):
        if chat_id and chat_id != namespace.get("FEISHU_HOME_CHANNEL"):
            return original_send(message, chat_id)
        ticket = None
        ledger = None
        try:
            current = sync(namespace["load_state"]())
            if current:
                ledger, _, scope = current
                # Recheck original mode/DND/cooldown, but generation's pending marker is ours.
                state = dict(namespace["load_state"]())
                state.pop("pending", None)
                skip = original_check(state, datetime.now())
                if skip:
                    return False, "companion_"+skip["reason"]
                ticket = ledger.reserve(scope, "lonely", uuid.uuid4().hex, digest(message))
                ledger.dispatch(ticket)
            result = original_send(message, chat_id)
        except Exception:
            if ledger and ticket:
                ledger.finish(ticket, "uncertain")
            return False, "主动联系暂未能完成，不会自动补发相同内容"
        if ledger and ticket:
            ledger.finish(ticket, "sent" if result[0] is True else "uncertain")
        path = home()/"state/maomao-companion/life.sqlite3"
        if result[0] is True and current and path.exists():
            LifeStore(path).shared(current[2], message)
        return result

    def goodnight():
        result = original_goodnight()
        current = configured()
        if current:
            ledger, _, scope = current
            ledger.goodnight(scope)
        return result

    def check_and_trigger():
        # The older fallback used to count/schedule before sending. Use the same
        # check -> send -> acknowledge path as smart cron, without creating a timer.
        context = namespace["smart_check"]()
        if not context.get("send"):
            return context
        message = context.get("fallback_message") or namespace["generate_proactive_message"]()
        success, result = send(message)
        if success:
            namespace["record_proactive_sent"](message)
            namespace["save_last_proactive"](message)
        return {"send": True, "sent": success, "message": message,
                "target_platform": "feishu", "send_result": result}

    namespace.update(precheck=precheck, send_feishu_message=send,
                     set_dnd_goodnight=goodnight, smart_check=smart_check, check_and_trigger=check_and_trigger,
                     _companion_installed=True)
    if "get_recent_session_context" in namespace:
        namespace["get_recent_session_context"] = recent_context
