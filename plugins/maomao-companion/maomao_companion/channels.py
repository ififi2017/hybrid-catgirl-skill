"""Per-channel adapter. Separate databases; never reads another profile's files."""
import hashlib
import json
import time

from .context import CompanionContext
from .dialogue import SPEAKER


def channel_key(target):
    fields = [target.get(k, "") for k in ("platform", "chat_type", "chat_id", "user_id")]
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


class ChannelContext(CompanionContext):
    def __init__(self, ctx, target):
        super().__init__(ctx)
        self.config_root = self.root
        self.target = dict(target)
        self.root = self.root/"channels"/target["platform"]/channel_key(target)

    def config(self):
        try:
            cfg = json.loads((self.config_root/"config.json").read_text())
            if cfg.get("enabled") is not True or self.target not in cfg.get("channels", []):
                return None
            context = cfg.get("context", {})
            if context.get("enabled") is not True:
                return None
            return {**cfg, "target": self.target, "private_members": [self.target], "context": context, "life": {"enabled": False}}
        except (OSError, ValueError, TypeError):
            return None

    @staticmethod
    def matches(source, target):
        return (isinstance(source, dict) and all(source.get(k) == target.get(k) for k in ("platform", "chat_id", "chat_type"))
                and (target.get("chat_type") == "group" or target.get("user_id") in {source.get("user_id"), source.get("user_id_alt")}))

    def resolve(self, session_id, platform):
        cfg = self.config()
        if not cfg or platform != self.target["platform"] or not session_id:
            return None
        try:
            entries = json.loads((self.config_root.parent.parent/"sessions/sessions.json").read_text())
            found = [key for key, row in entries.items() if isinstance(row, dict) and row.get("session_id") == session_id
                     and self.matches(row.get("origin") or row.get("source"), self.target)]
        except (OSError, ValueError, TypeError):
            return None
        if len(found) > 1:
            # The admitted key determines the current actor when host aliases share a SID.
            # Never guess between two concurrently admitted events.
            with self.lock:
                found = [key for key in found if key in self.pending]
        return (found[0], channel_key(self.target)) if len(found) == 1 else None

    def gate(self, session_key, session_id=None):
        # Public QQ lives in a dedicated profile without private extensions or global files.
        # Metadata must still resolve exactly; text never selects a database or a recipient.
        try:
            rows = json.loads((self.config_root.parent.parent/"sessions/sessions.json").read_text())
            row = rows.get(session_key, {})
            return bool(self.config() and self.matches(row.get("origin") or row.get("source"), self.target)
                        and (session_id is None or row.get("session_id") == session_id))
        except (OSError, ValueError, TypeError):
            return False

    def embedding_scope(self, target):
        return channel_key(target)

    def decorate_context(self, context, text):
        if self.target["chat_type"] == "group":
            speaker = SPEAKER.match(text)
            context["current_speaker"] = speaker[1] if speaker else None
            context["channel_type"] = "group"

    def incoming(self, source=None, text="", **kwargs):
        if self.target["chat_type"] == "group" and isinstance(source, dict):
            # Prevent preferences from different people becoming the owner's shared preference.
            actor = hashlib.sha256(str(source.get("user_id", "unknown")).encode()).hexdigest()[:12]
            text = "[群成员 "+actor+"] "+str(text)
        return super().incoming(source=source, text=text, **kwargs)
