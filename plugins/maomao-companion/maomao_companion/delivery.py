"""Natural message bubbles, explicit voice consent and passive-reply accounting."""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

BUBBLE = "<|bubble|>"
VOICE_YES = re.compile(r"(?:用|发|来|给我|回|回复|说|读|念|播).{0,8}(?:语音|音频)|(?:语音|音频).{0,8}(?:回复|回答|说|读|念|发)|(?:念|读)给我听|/voice\s+(?:on|tts)|(?:能不能|可不可以|能否|可否)(?:直接)?(?:语音|音频)|(?:可以|能)(?:语音|音频)(?:吗|么)", re.I)
VOICE_NO = re.compile(r"(?:不要|不用|不需要|不必|禁止|不能|别|不)(?:(?:再|用|发|回复|发送|给我|自动|任何|听)|\s){0,4}(?:语音|音频)|/voice\s+off|(?:如果|假如|比如|例如).{0,12}(?:语音|音频)", re.I)
HINT = ("短聊天可自然分成2—4条，简单回答一条即可；用 <|bubble|> 分隔独立消息，"
        "不要为了凑条数重复意思。长解释、代码、表格保持完整。没有事实依据，不编造用户最近加班、"
        "不回消息等经历。只有用户本轮明确要求语音才可调用text_to_speech；收到语音不代表要求语音回复。"
        "图片/表情最多配一张，QQ文字与媒体合计不超过被动回复额度。"
        "自动表情收藏成功会单独发带理由的提示；没有成功记录时不宣称已收藏，已发提示不重复。")


def voice_requested(text):
    if not isinstance(text, str):
        return False
    value = re.sub(r"```[\s\S]*?```|`[^`]*`", "", text).strip()
    requested=bool(VOICE_YES.search(value))
    # Negative words inside affirmative permission questions are not refusals.
    value=value.replace("能不能","能").replace("可不可以","可以").replace("会不会","会")
    return bool(requested and not VOICE_NO.search(value))


def requested_language(text):
    aliases={"中文":"zh","汉语":"zh","普通话":"zh","日语":"ja","日文":"ja","英语":"en","英文":"en","韩语":"ko","韩文":"ko","法语":"fr","德语":"de"}
    value=str(text or "")
    matches=[m for m in re.finditer("|".join(aliases),value) if not re.search(r"不要|不用|别用|不是",value[max(0,m.start()-3):m.start()])]
    return aliases[matches[-1].group()] if matches else ""


def voice_followup(text):
    if not isinstance(text,str):return False
    value=re.sub(r"```[\s\S]*?```|`[^`]*`","",text).strip()
    value=value.replace("能不能","能").replace("可不可以","可以")
    if VOICE_NO.search(value):return False
    if re.search(r"文字|文本|打字|图片|表情|照片|视频|文件|不要再|不用再|别再|停下|算了",value):return False
    languages=r"日语|日文|英语|英文|中文|汉语|韩语|法语|德语|俄语|粤语|四川话|东北话|河南话"
    return bool(re.search(r"(?:再)?(?:温柔|凶|慢|快|大声|小声|轻)(?:一点|点|一些)|再来(?:点|一遍|一下|一次|一句|一段|一个|[～~。！!？?\s]*$)|再(?:说|读|念|讲)(?:一遍|一下|一次|一句|一段)|重新(?:说|读|念)|(?:换成|改成|用)(?:"+languages+r")(?:再|说|读|念|讲|[～~。！!？?\s]*$)|(?:说|读|念|语速|声音|语气).{0,4}(?:慢一点|快一点|轻一点|温柔一点|凶一点|大声点|小声点)",value))


def bubbles(text, maximum=4):
    if not isinstance(text, str) or not text.strip():
        return []
    if "```" in text:
        return [text.replace(BUBBLE, "\n\n").strip()]
    if BUBBLE in text:
        parts = [p.strip() for p in text.split(BUBBLE) if p.strip()]
    elif len(text) <= 900 and not re.search(r"(?m)^\s*(?:[-*+]\s|\d+[.)]\s|\|)", text):
        parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    else:
        return [text.strip()]
    if len(parts) > maximum:
        parts = parts[:maximum-1]+["\n\n".join(parts[maximum-1:])]
    return parts


class DeliveryLedger:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS admissions(platform TEXT NOT NULL,chat TEXT NOT NULL,
                anchor TEXT NOT NULL,received REAL NOT NULL,voice INTEGER NOT NULL,
                PRIMARY KEY(platform,chat,anchor));
              CREATE TABLE IF NOT EXISTS passive_receipts(platform TEXT,chat TEXT,anchor TEXT,received REAL NOT NULL,
                PRIMARY KEY(platform,chat,anchor));
              CREATE TABLE IF NOT EXISTS admission_context(platform TEXT,chat TEXT,anchor TEXT,actor TEXT NOT NULL,prior_anchor TEXT NOT NULL,language TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(platform,chat,anchor));
              CREATE TABLE IF NOT EXISTS artifacts(platform TEXT,chat TEXT,anchor TEXT,path TEXT,created REAL,
                PRIMARY KEY(platform,chat,anchor,path));
              CREATE TABLE IF NOT EXISTS sends(platform TEXT NOT NULL,chat TEXT NOT NULL,anchor TEXT NOT NULL,
                digest TEXT NOT NULL,seq INTEGER NOT NULL,status TEXT NOT NULL,message_id TEXT NOT NULL,
                created REAL NOT NULL,PRIMARY KEY(platform,chat,anchor,digest));
            """)
            if "language" not in {row[1] for row in db.execute("PRAGMA table_info(admission_context)")}:
                db.execute("ALTER TABLE admission_context ADD COLUMN language TEXT NOT NULL DEFAULT ''")
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=3,isolation_level=None); db.row_factory=sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL"); db.execute("BEGIN IMMEDIATE")
            yield db
            if db.in_transaction: db.execute("COMMIT")
        except BaseException:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        finally: db.close()

    def note_receipt(self,platform,chat,anchor):
        if not anchor:return
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO passive_receipts VALUES(?,?,?,?)",(platform,str(chat),str(anchor),self.clock()))
            db.execute("DELETE FROM passive_receipts WHERE received<?",(self.clock()-86400,))

    def remaining(self,platform,chat,anchor,limit=5):
        with self.db() as db:
            count=db.execute("SELECT count(*) FROM sends WHERE platform=? AND chat=? AND anchor=?",(platform,str(chat),str(anchor))).fetchone()[0]
        return max(0,limit-count)

    def _voice_permission(self,db,platform,chat,anchor,text,received):
        if voice_requested(text):return True
        if not voice_followup(text):return False
        meta=db.execute("SELECT actor,prior_anchor FROM admission_context WHERE platform=? AND chat=? AND anchor=?",(platform,chat,anchor)).fetchone()
        if not meta or not meta["actor"] or not meta["prior_anchor"]:return False
        prior=db.execute("SELECT a.voice,a.received,c.actor FROM admissions a JOIN admission_context c USING(platform,chat,anchor) WHERE a.platform=? AND a.chat=? AND a.anchor=?",(platform,chat,meta["prior_anchor"])).fetchone()
        return bool(prior and prior["voice"] and prior["actor"]==meta["actor"] and 0<=received-prior["received"]<=3600)

    def _voice_language(self,db,platform,chat,anchor,text):
        language=requested_language(text)
        if language or not voice_followup(text):return language
        row=db.execute("SELECT prior.language FROM admission_context own JOIN admission_context prior ON prior.platform=own.platform AND prior.chat=own.chat AND prior.anchor=own.prior_anchor AND prior.actor=own.actor WHERE own.platform=? AND own.chat=? AND own.anchor=?",(platform,chat,anchor)).fetchone()
        return row[0] if row else ""

    def voice_language(self,platform,chat,anchor=None):
        if not self.voice_allowed(platform,chat,anchor):return ""
        current=self.current(platform,str(chat))
        with self.db() as db:
            row=db.execute("SELECT language FROM admission_context WHERE platform=? AND chat=? AND anchor=?",(platform,str(chat),current["anchor"])).fetchone()
        return row[0] if row else ""

    def admit(self, platform, chat, anchor, text, actor=""):
        if not all(isinstance(v,str) and v for v in (platform,chat,anchor)):return
        actor=hashlib.sha256(str(actor).encode()).hexdigest()[:12] if actor else ""
        with self.db() as db:
            prior=db.execute("SELECT anchor FROM admissions WHERE platform=? AND chat=? ORDER BY received DESC,rowid DESC LIMIT 1",(platform,chat)).fetchone()
            inserted=db.execute("INSERT OR IGNORE INTO admissions VALUES(?,?,?,?,0)",(platform,chat,anchor,self.clock())).rowcount
            if inserted:
                db.execute("INSERT INTO admission_context(platform,chat,anchor,actor,prior_anchor,language) VALUES(?,?,?,?,?,'')",(platform,chat,anchor,actor,prior["anchor"] if prior else ""))
                permission=self._voice_permission(db,platform,chat,anchor,text,self.clock())
                language=self._voice_language(db,platform,chat,anchor,text)
                db.execute("UPDATE admission_context SET language=? WHERE platform=? AND chat=? AND anchor=?",(language,platform,chat,anchor))
                db.execute("UPDATE admissions SET voice=? WHERE platform=? AND chat=? AND anchor=?",(int(permission),platform,chat,anchor))
            db.execute("DELETE FROM admissions WHERE received<?",(self.clock()-86400,))
            db.execute("DELETE FROM admission_context WHERE NOT EXISTS(SELECT 1 FROM admissions a WHERE a.platform=admission_context.platform AND a.chat=admission_context.chat AND a.anchor=admission_context.anchor)")
            db.execute("DELETE FROM sends WHERE created<?",(self.clock()-86400,))

    def correct_voice(self,platform,chat,anchor,own_text):
        # Re-evaluate only this admitted body's intent, not its quoted context.
        with self.db() as db:
            row=db.execute("SELECT received FROM admissions WHERE platform=? AND chat=? AND anchor=?",(platform,str(chat),str(anchor))).fetchone()
            if not row or not 0<=self.clock()-row["received"]<=600:return False
            permission=self._voice_permission(db,platform,str(chat),str(anchor),own_text,row["received"])
            language=self._voice_language(db,platform,str(chat),str(anchor),own_text)
            db.execute("UPDATE admission_context SET language=? WHERE platform=? AND chat=? AND anchor=?",(language,platform,str(chat),str(anchor)))
            db.execute("UPDATE admissions SET voice=? WHERE platform=? AND chat=? AND anchor=?",(int(permission),platform,str(chat),str(anchor)))
            return True

    def current(self, platform, chat):
        with self.db() as db:
            row=db.execute("SELECT * FROM admissions WHERE platform=? AND chat=? ORDER BY received DESC,rowid DESC LIMIT 1", (platform,str(chat))).fetchone()
        return dict(row) if row else None

    def voice_allowed(self, platform, chat, anchor=None):
        row=self.current(platform,str(chat))
        return bool(row and row["voice"] and 0 <= self.clock()-row["received"] <= 600
                    and (anchor is None or str(anchor)==row["anchor"]))

    def grant_artifact(self,platform,chat,anchor,path):
        path=Path(path).resolve()
        if not path.is_file(): return
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?)",(platform,str(chat),str(anchor),str(path),self.clock()))
            db.execute("DELETE FROM artifacts WHERE created<?",(self.clock()-600,))

    def artifact_allowed(self,platform,chat,anchor,path):
        if not anchor: return False
        with self.db() as db:
            row=db.execute("SELECT created FROM artifacts WHERE platform=? AND chat=? AND anchor=? AND path=?",(platform,str(chat),str(anchor),str(Path(path).resolve()))).fetchone()
        return bool(row and 0<=self.clock()-row[0]<=600)

    def reserve(self, platform, chat, anchor, body, limit=5, window=300):
        # Retries reuse the same operation fingerprint and never consume another passive slot.
        clean={k:v for k,v in body.items() if k != "msg_seq"}
        digest=hashlib.sha256(json.dumps(clean,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        now=self.clock()
        with self.db() as db:
            prior=db.execute("SELECT * FROM sends WHERE platform=? AND chat=? AND anchor=? AND digest=?", (platform,chat,anchor,digest)).fetchone()
            if prior: return dict(prior),False
            event=db.execute("SELECT received FROM admissions WHERE platform=? AND chat=? AND anchor=?", (platform,chat,anchor)).fetchone()
            receipt=db.execute("SELECT received FROM passive_receipts WHERE platform=? AND chat=? AND anchor=?",(platform,chat,anchor)).fetchone()
            received=min([row[0] for row in (event,receipt) if row]) if event or receipt else None
            if received is None or not 0 <= now-received <= window:
                raise PermissionError("passive reply anchor unavailable or expired")
            count=db.execute("SELECT count(*) FROM sends WHERE platform=? AND chat=? AND anchor=?", (platform,chat,anchor)).fetchone()[0]
            if count >= limit: raise PermissionError("passive reply budget exhausted")
            seq=count+1
            db.execute("INSERT INTO sends VALUES(?,?,?,?,?,'reserved','',?)", (platform,chat,anchor,digest,seq,now))
            return {"platform":platform,"chat":chat,"anchor":anchor,"digest":digest,"seq":seq,"status":"reserved"},True

    def finish(self, ticket, success, message_id=""):
        with self.db() as db:
            db.execute("UPDATE sends SET status=?,message_id=? WHERE platform=? AND chat=? AND anchor=? AND digest=?", ("sent" if success else "uncertain",str(message_id),ticket["platform"],ticket["chat"],ticket["anchor"],ticket["digest"]))


def session_source(root, session_id):
    try:
        rows=json.loads((Path(root)/"sessions/sessions.json").read_text())
        sources=[r.get("origin") or r.get("source") or {} for r in rows.values() if isinstance(r,dict) and r.get("session_id")==session_id]
        identities={(s.get("platform"),s.get("chat_type"),s.get("chat_id")) for s in sources if isinstance(s,dict)}
        if len(identities)!=1: return None
        platform,kind,chat=next(iter(identities))
        return {"platform":platform,"chat_type":kind,"chat_id":chat}
    except (OSError,ValueError,TypeError): return None


def response_metadata(result):
    """Native adapters return either mappings or SDK response objects."""
    from collections.abc import Mapping
    raw=getattr(result,"raw_response",None)
    if isinstance(raw,Mapping):return dict(raw)
    data=getattr(raw,"data",None)
    message_id=getattr(data,"message_id",None) or getattr(getattr(data,"message",None),"message_id",None)
    return {"message_ids":[str(message_id)]} if message_id else {}


def message_ids(result):
    raw=response_metadata(result)
    values=raw.get("message_ids") or raw.get("delivered_message_ids") or []
    values=list(values) if isinstance(values,(tuple,list)) else [values]
    if getattr(result,"message_id",None):values.append(result.message_id)
    extra=getattr(result,"continuation_message_ids",None) or raw.get("continuation_message_ids") or []
    values.extend(extra if isinstance(extra,(tuple,list)) else [extra])
    return list(dict.fromkeys(str(x) for x in values if x))
