"""Host-only configuration. Public packages contain neither recipients nor runtime data."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .contact import ContactLedger, Policy


def home():
    return Path(os.environ.get("HERMES_HOME", str(Path.home()/".hermes")))


def configured():
    root = home()/"state"/"maomao-companion"
    try:
        cfg = json.loads((root/"config.json").read_text())
    except FileNotFoundError:
        return None
    if cfg.get("enabled") is not True:
        return None
    target = cfg["target"]
    scope = ContactLedger.scope(target["platform"], target["chat_id"], target["user_id"], target["chat_type"])
    return ContactLedger(root/"contacts.sqlite3", Policy(**cfg.get("policy", {}))), target, scope
