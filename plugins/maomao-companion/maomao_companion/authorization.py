"""Ephemeral standalone DM consent tied to trusted gateway admission."""
import json
import sys
import threading
import time
from types import ModuleType
from pathlib import Path

_new_shared=ModuleType('_maomao_public_authorization_state')
_new_shared.leases={}
_new_shared.lock=threading.Lock()
_shared=sys.modules.setdefault(_new_shared.__name__,_new_shared)
_leases = _shared.leases
_lock = _shared.lock
TTL = 300


def standalone(cfg):
    auth=cfg.get('authorization') if isinstance(cfg,dict) else None
    return isinstance(auth,dict) and auth.get('mode')=='standalone'


def matches(source, target):
    return (isinstance(source, dict) and isinstance(target, dict)
            and source.get('platform') in {'feishu', 'telegram'}
            and source.get('chat_type') == target.get('chat_type') == 'dm'
            and all(source.get(k) and source.get(k) == target.get(k) for k in ('platform', 'chat_id'))
            and bool(target.get('user_id'))
            and target['user_id'] in {source.get('user_id'), source.get('user_id_alt')})


def admit(root, cfg, session_key, source, now=None):
    now=time.time() if now is None else now
    if not isinstance(cfg,dict) or cfg.get('enabled') is not True or not standalone(cfg):return False
    if (Path(root)/'state/maomao-companion/session-policy.json').exists():return False
    members=cfg.get('private_members') or [cfg.get('target')]
    if not session_key or not isinstance(members,list) or not any(matches(source,t) for t in members):return False
    key=(str(Path(root).resolve()),str(session_key))
    with _lock:
        _leases[key]=(dict(source),now)
        for k,v in list(_leases.items()):
            if now-v[1]>TTL:_leases.pop(k,None)
        while len(_leases)>256:_leases.pop(next(iter(_leases)))
    return True


def allowed(root, cfg, session_key, session_id=None, now=None):
    now=time.time() if now is None else now
    if not isinstance(cfg,dict) or cfg.get('enabled') is not True or not standalone(cfg):return False
    if (Path(root)/'state/maomao-companion/session-policy.json').exists():return False
    with _lock:lease=_leases.get((str(Path(root).resolve()),str(session_key)))
    if not lease or not 0<=now-lease[1]<=TTL:return False
    members=cfg.get('private_members') or [cfg.get('target')]
    if not isinstance(members,list) or not any(matches(lease[0],t) for t in members):return False
    if session_id is None:return True
    try:
        entries=json.loads((Path(root)/'sessions/sessions.json').read_text())
        row=entries[session_key];origin=row.get('origin') or row.get('source') or {}
        return row.get('session_id')==session_id and any(matches(origin,t) and matches(lease[0],t) for t in members)
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return False
