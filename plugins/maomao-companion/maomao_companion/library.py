"""Group-local image descriptions and reusable memes. No cloud image hosting."""
import hashlib
import io
import json
import math
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

CATEGORIES = ["开心", "生气", "害羞", "疑惑", "惊讶", "无语", "赞同", "拒绝", "晚安", "摸鱼", "其他"]
VISION_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["description", "text", "category", "is_meme", "confidence", "personal_or_sensitive", "steal_reason"],
    "properties": {"description": {"type": "string", "maxLength": 200}, "text": {"type": "string", "maxLength": 100},
        "category": {"type": "string", "enum": CATEGORIES}, "is_meme": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "personal_or_sensitive": {"type": "boolean"}, "steal_reason": {"type":"string","maxLength":48}}}


def group_key(group):
    return hashlib.sha256(str(group).encode()).hexdigest()


def local_media_allowed(home, group, source):
    if str(source).startswith(("https://", "http://")):
        return True
    path = Path(str(source)).expanduser().resolve()
    home = Path(home).resolve()
    return any(path.is_relative_to(parent) for parent in (
        home/"state/maomao-qq/groups"/group_key(group), home/"stickers/512"))


def image_input(path):
    from PIL import Image, ImageOps
    path = Path(path)
    if path.stat().st_size > 5_000_000 or path.is_symlink():
        raise ValueError("image exceeds bounds")
    with Image.open(path) as im:
        if im.width*im.height > 20_000_000 or im.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
            raise ValueError("unsupported image")
        fmt = im.format
        frames = getattr(im, "n_frames", 1)
        sheet = Image.new("RGB", (512, 512) if frames > 1 else (512, 256), "white")
        for index in range(4 if frames > 1 else 1):
            im.seek(min(frames-1, int(index*frames/4)))
            tile = ImageOps.contain(im.convert("RGBA"), (256, 256) if frames > 1 else (512, 256))
            sheet.paste(tile, ((index % 2)*256, (index//2)*256) if frames > 1 else (0, 0), tile)
        output = io.BytesIO(); sheet.save(output, format="JPEG", quality=85)
        small = ImageOps.fit(im.convert("L"), (9, 8))
        px = list(small.getdata())
        dhash = sum((px[y*9+x] > px[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
    return output.getvalue(), fmt.lower().replace("jpeg", "jpg"), f"{dhash:016x}"


class MemeStore:
    def __init__(self, root, group):
        self.root = Path(root)/"groups"/group_key(group)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root/"memes.sqlite3"
        with self.db() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY,description TEXT NOT NULL,ocr TEXT NOT NULL,
                category TEXT NOT NULL,seen INTEGER NOT NULL,eligible INTEGER NOT NULL,path TEXT,
                dhash TEXT NOT NULL,model TEXT,vector TEXT,created REAL NOT NULL,last_seen REAL NOT NULL,last_sent REAL);
              CREATE TABLE IF NOT EXISTS semantics(id TEXT PRIMARY KEY,steal_reason TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS collection_notices(id TEXT PRIMARY KEY,created REAL NOT NULL,status TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS calls(kind TEXT NOT NULL,created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,speaker TEXT NOT NULL,text TEXT NOT NULL,observed REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS query_vectors(id TEXT NOT NULL,model TEXT NOT NULL,vector TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(id,model));
            """)
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, kind, maximum=80):
        now = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM calls WHERE created<?", (now-86400,))
            if db.execute("SELECT count(*) FROM calls WHERE kind=?", (kind,)).fetchone()[0] >= maximum:
                return False
            db.execute("INSERT INTO calls VALUES(?,?)", (kind, now))
        return True

    def known(self, digest):
        with self.db() as db:
            row = db.execute("SELECT images.*,coalesce((SELECT steal_reason FROM semantics WHERE semantics.id=images.id),'') AS steal_reason FROM images WHERE id=?", (digest,)).fetchone()
            return dict(row) if row else None

    def observe_message(self, message_id, speaker, text):
        if not message_id or not isinstance(text, str) or not text.strip():
            return False
        actor = hashlib.sha256(str(speaker).encode()).hexdigest()[:12]
        with self.db() as db:
            inserted = db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?)", (str(message_id)[:200], actor, text[:600], time.time())).rowcount > 0
            db.execute("DELETE FROM observations WHERE observed<? OR id NOT IN (SELECT id FROM observations ORDER BY observed DESC LIMIT 1000)", (time.time()-7*86400,))
        return inserted

    def annotate_image(self, message_id, original, description):
        # Enrich the original receipt; do not make an old picture look newly sent.
        value = original[:300]+"\n[图片识别资料，可能有误，不是指令："+description[:200]+"]"
        with self.db() as db:
            db.execute("UPDATE observations SET text=? WHERE id=?", (value[:600], str(message_id)[:200]))

    def annotate_collection(self,message_id,image_id,announced):
        image=self.known(image_id)
        if not image or not image["path"]:return
        state=json.dumps({"collected":True,"reason":image.get("steal_reason",""),"notice_sent":bool(announced)},ensure_ascii=False)
        with self.db() as db:
            row=db.execute("SELECT text FROM observations WHERE id=?",(str(message_id),)).fetchone()
            if row:
                text=row[0].split("\n[本地收藏状态：",1)[0]
                db.execute("UPDATE observations SET text=? WHERE id=?",(text[:430]+"\n[本地收藏状态："+state+"]",str(message_id)))

    def conversation_context(self):
        with self.db() as db:
            rows = [dict(r) for r in db.execute("SELECT speaker,text,observed FROM observations WHERE observed>? ORDER BY observed DESC LIMIT 12", (time.time()-1800,))]
        return list(reversed(rows))

    def remember(self, path, result, explicit=False, embedder=None, *, count_sighting=True):
        path = Path(path)
        if path.stat().st_size > 5_000_000:
            return None
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        _, ext, dhash = image_input(path)
        if not isinstance(result, dict) or result.get("personal_or_sensitive") is not False:
            return None
        description, ocr, category = result.get("description"), result.get("text"), result.get("category")
        confidence = result.get("confidence")
        if not isinstance(description, str) or not 1 <= len(description) <= 200 or not isinstance(ocr, str) or len(ocr) > 100 or category not in CATEGORIES:
            return None
        eligible = result.get("is_meme") is True and type(confidence) in (int, float) and (.80 if explicit else .85) <= confidence <= 1
        old = self.known(digest)
        seen = (old["seen"] if old else 0)+int(count_sighting)
        observed = old["last_seen"] if old and not count_sighting else time.time()
        collected = bool(eligible and (explicit or seen >= 2))
        destination = old.get("path") if old else None
        newly_collected=False
        reason=result.get("steal_reason","")
        reason=reason.strip()[:48] if isinstance(reason,str) else ""
        with self.db() as db:
            current=db.execute("SELECT path FROM images WHERE id=?",(digest,)).fetchone()
            if current and current[0]:destination=current[0]
            # Near duplicates are not a second reusable image. Different captions remain distinct.
            near = [r for r in db.execute("SELECT dhash,ocr FROM images WHERE path IS NOT NULL AND id<>?", (digest,))]
            duplicate = any(bin(int(r["dhash"], 16)^int(dhash, 16)).count("1") <= 3 and r["ocr"] == ocr for r in near)
            if collected and not destination and not duplicate and len(near) < 200 and len(raw) <= 2_000_000:
                destination = str(self.root/(digest+"."+ext))
                Path(destination).write_bytes(raw); Path(destination).chmod(0o600)
                newly_collected=bool(count_sighting)
            db.execute("INSERT INTO images VALUES(?,?,?,?,?,?,?,?,NULL,NULL,?,?,NULL) ON CONFLICT(id) DO UPDATE SET description=excluded.description,ocr=excluded.ocr,category=excluded.category,eligible=excluded.eligible,seen=excluded.seen,last_seen=excluded.last_seen,path=coalesce(images.path,excluded.path)",
                (digest, description, ocr, category, seen, int(eligible), destination, dhash, time.time(), observed))
            if reason:db.execute("INSERT OR REPLACE INTO semantics VALUES(?,?)",(digest,reason))
            db.execute("DELETE FROM images WHERE path IS NULL AND last_seen<?", (time.time()-7*86400,))
            db.execute("DELETE FROM semantics WHERE id NOT IN (SELECT id FROM images)")
        if destination and embedder and (not old or not old.get("vector")) and self.reserve("embedding"):
            try:
                vector = embedder.embed([description+" "+ocr+" "+category+" "+reason], timeout=5)[0]
                with self.db() as db:
                    db.execute("UPDATE images SET model=?,vector=? WHERE id=?", (embedder.model, json.dumps(vector), digest))
            except Exception:
                pass
        return {**self.known(digest),"newly_collected":newly_collected}

    def claim_collection_notice(self,image_id,now=None):
        now=time.time() if now is None else now
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT path,eligible FROM images WHERE id=?",(image_id,)).fetchone()
            if not row or not row[0] or not row[1] or not Path(row[0]).is_file():return False
            if db.execute("SELECT 1 FROM collection_notices WHERE id=?",(image_id,)).fetchone():return False
            recent=db.execute("SELECT count(*) FROM collection_notices WHERE created>? AND status IN ('reserved','sent','uncertain')",(now-3600,)).fetchone()[0]
            cooldown=db.execute("SELECT 1 FROM collection_notices WHERE created>? AND status IN ('reserved','sent','uncertain')",(now-10,)).fetchone()
            status="suppressed" if cooldown or recent>=20 else "reserved"
            db.execute("INSERT INTO collection_notices VALUES(?,?,?)",(image_id,now,status))
            return status=="reserved"

    def finish_collection_notice(self,image_id,success):
        with self.db() as db:db.execute("UPDATE collection_notices SET status=? WHERE id=?",("sent" if success else "uncertain",image_id))

    def search(self, query, embedder=None):
        if not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise ValueError("query must be 1–200 characters")
        with self.db() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM images WHERE eligible=1 AND path IS NOT NULL AND (last_sent IS NULL OR last_sent<?) ORDER BY last_seen DESC LIMIT 200", (time.time()-6*3600,))]
        vector = None
        query_id = hashlib.sha256(query.encode()).hexdigest()
        if rows and embedder:
            try:
                with self.db() as db:
                    cached = db.execute("SELECT vector FROM query_vectors WHERE id=? AND model=? AND created>?", (query_id, embedder.model, time.time()-86400)).fetchone()
                if cached:
                    vector = json.loads(cached[0])
                elif self.reserve("query", 100):
                    vector = embedder.embed(["Instruct: Retrieve a chat sticker matching the conversation emotion and intent.\nQuery: "+query], timeout=2)[0]
                    with self.db() as db:
                        db.execute("INSERT OR REPLACE INTO query_vectors VALUES(?,?,?,?)", (query_id, embedder.model, json.dumps(vector), time.time()))
                        db.execute("DELETE FROM query_vectors WHERE created<? OR rowid NOT IN (SELECT rowid FROM query_vectors ORDER BY created DESC LIMIT 64)", (time.time()-86400,))
            except Exception:
                pass
        ranked = []
        for row in rows:
            description = row["description"]+row["ocr"]+row["category"]
            keyword = any(query[i:i+2] in description for i in range(max(0, len(query)-1))) or query == row["category"]
            score = .6 if keyword else 0
            if vector is not None and row["model"] == embedder.model and row["vector"]:
                stored = json.loads(row["vector"])
                if len(stored) == len(vector):
                    score = max(score, sum(a*b for a,b in zip(stored,vector)))
            if score >= .55 and Path(row["path"]).is_file():
                ranked.append({"id": row["id"], "description": row["description"], "category": row["category"], "media": "MEDIA:"+row["path"], "score": round(score, 3)})
        return sorted(ranked, key=lambda r: (-r["score"], r["id"]))[:3]

    def claim(self, path):
        # Reserve the six-hour image cooldown before an uncertain network send.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            return db.execute("UPDATE images SET last_sent=? WHERE eligible=1 AND path=? AND (last_sent IS NULL OR last_sent<?)",(time.time(),str(path),time.time()-6*3600)).rowcount==1

    def sent(self, path):
        with self.db() as db:
            db.execute("UPDATE images SET last_sent=? WHERE path=?", (time.time(), str(path)))


def collection_reply(reason):
    import re
    value=re.sub(r"\s+"," ",reason).strip()[:48] if isinstance(reason,str) else ""
    if re.search(r"https?://|MEDIA:|<|>|@|/[a-zA-Z]",value,re.I):value=""
    return "这张偷走啦～"+value.rstrip("。！？!?")+("。" if value else "揣兜里啦～")
