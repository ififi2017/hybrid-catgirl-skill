"""Optional OpenRouter embeddings. No secrets, text logs or arbitrary endpoints."""
from __future__ import annotations

import concurrent.futures
import contextvars
import hashlib
import json
import math
import threading
import time
import urllib.request
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

MODELS = {"qwen/qwen3-embedding-8b", "baai/bge-m3"}


def signature(text):
    return hashlib.sha256(text.encode()).hexdigest()


def normalized(vector, dimensions):
    if not isinstance(vector, list) or len(vector) != dimensions or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
        raise ValueError("invalid embedding vector")
    norm = math.sqrt(sum(x*x for x in vector))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("empty embedding vector")
    return [x/norm for x in vector]


def host_key(model):
    # Official resolver honors configured profile and credential pools. Never borrow a key
    # from an unrelated custom endpoint, and never persist or print the runtime object.
    from hermes_cli.runtime_provider import resolve_runtime_provider
    runtime = resolve_runtime_provider(requested="openrouter", target_model=model)
    if runtime.get("provider") != "openrouter" or urlparse(runtime.get("base_url", "")).hostname != "openrouter.ai":
        raise PermissionError("canonical OpenRouter account required")
    key = runtime.get("api_key")
    if not isinstance(key, str) or not key:
        raise PermissionError("OpenRouter credential unavailable")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise PermissionError("embedding redirects are disabled")


class OpenRouterEmbeddings:
    def __init__(self, model="qwen/qwen3-embedding-8b", dimensions=1024, key_provider=host_key):
        if model not in MODELS or type(dimensions) is not int or dimensions != 1024:
            raise ValueError("unsupported embedding model/dimensions")
        self.model, self.dimensions, self.key_provider = model, dimensions, key_provider

    def embed(self, texts, query=False, timeout=10):
        if not isinstance(texts, list) or not 1 <= len(texts) <= 16 or any(not isinstance(t, str) or not t.strip() or len(t) > 600 for t in texts):
            raise ValueError("embedding input exceeds bounds")
        inputs = texts
        if query and self.model.startswith("qwen/"):
            inputs = ["Instruct: Retrieve relevant personal preferences and past conversation notes for the user query.\nQuery: "+t for t in texts]
        payload = {"model": self.model, "input": inputs, "dimensions": self.dimensions, "encoding_format": "float",
                   "provider": {"only": ["DeepInfra"], "data_collection": "deny", "max_price": {"prompt": 0.02}}}
        request = urllib.request.Request("https://openrouter.ai/api/v1/embeddings", data=json.dumps(payload).encode(),
                    headers={"Authorization": "Bearer "+self.key_provider(self.model), "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("embedding response too large")
            result = json.loads(raw)
            if str(result.get("model", "")).lower() != self.model.lower():
                raise ValueError("embedding model mismatch")
            rows = result["data"]
            if not isinstance(rows, list) or len(rows) != len(texts) or any(not isinstance(r, dict) or type(r.get("index")) is not int for r in rows) or sorted(r.get("index") for r in rows) != list(range(len(texts))):
                raise ValueError("embedding response indices mismatch")
            return [normalized(row["embedding"], self.dimensions) for row in sorted(rows, key=lambda r: r["index"])]
        except Exception:
            # Provider errors may contain submitted text/headers. Expose a fixed error only.
            raise RuntimeError("embedding request unavailable") from None


class SemanticMemory:
    def __init__(self, store, client, allowed, query_seconds=2, threshold=0.5, daily_limit=200):
        self.store, self.client, self.allowed = store, client, allowed
        if not 0 < query_seconds <= 3 or not 0 <= threshold <= 1 or not 1 <= daily_limit <= 500:
            raise ValueError("invalid semantic retrieval limits")
        self.query_seconds, self.threshold, self.daily_limit = query_seconds, threshold, daily_limit
        self.closed = False
        self.lock = threading.Lock()
        self.future = None
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="companion-query")
        with store.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memory_vectors(
                  scope TEXT NOT NULL,id TEXT NOT NULL,model TEXT NOT NULL,dimensions INTEGER NOT NULL,
                  signature TEXT NOT NULL,vector TEXT NOT NULL,updated REAL NOT NULL,
                  PRIMARY KEY(scope,id,model,dimensions));
                CREATE TABLE IF NOT EXISTS query_vectors(
                  scope TEXT NOT NULL,id TEXT NOT NULL,model TEXT NOT NULL,dimensions INTEGER NOT NULL,
                  vector TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(scope,id,model,dimensions));
                CREATE TABLE IF NOT EXISTS embedding_calls(scope TEXT NOT NULL,day TEXT NOT NULL,created REAL NOT NULL);
            """)

    def _allowed(self, job):
        return not self.closed and self.allowed(job)

    def _reserve_call(self, scope):
        now = time.time()
        day = datetime.fromtimestamp(now, ZoneInfo("Asia/Taipei")).date().isoformat()
        with self.store.db() as db:
            db.execute("DELETE FROM embedding_calls WHERE created<?", (now-7*86400,))
            used = db.execute("SELECT count(*) FROM embedding_calls WHERE scope=? AND day=?", (scope, day)).fetchone()[0]
            if used >= self.daily_limit:
                raise PermissionError("daily embedding budget exhausted")
            db.execute("INSERT INTO embedding_calls VALUES(?,?,?)", (scope, day, now))

    def _vectors(self, scope):
        with self.store.db() as db:
            return {r["id"]: dict(r) for r in db.execute("SELECT * FROM memory_vectors WHERE scope=? AND model=? AND dimensions=?", (scope, self.client.model, self.client.dimensions))}

    def index(self, job, historical_only=False):
        if not self._allowed(job) or (not historical_only and not self.store.current(job["scope"], job["version"])):
            return 0
        docs = self.store.memory_documents(job["scope"])
        existing = self._vectors(job["scope"])
        missing = [doc for doc in docs if doc["id"] not in existing or existing[doc["id"]]["signature"] != signature(doc["text"])][:16]
        if historical_only:
            missing = [doc for doc in missing if doc["kind"] == "historical_note"]
        # Remove expired/superseded records even if no network call is needed.
        current = {doc["id"]: signature(doc["text"]) for doc in docs}
        with self.store.db() as db:
            for key, row in existing.items():
                if current.get(key) != row["signature"]:
                    db.execute("DELETE FROM memory_vectors WHERE scope=? AND id=? AND model=? AND dimensions=?", (job["scope"], key, self.client.model, self.client.dimensions))
        if not missing or not self._allowed(job):
            return 0
        self._reserve_call(job["scope"])
        vectors = self.client.embed([doc["text"][:600] for doc in missing])
        if not self._allowed(job):
            return 0
        current = {doc["id"]: signature(doc["text"]) for doc in self.store.memory_documents(job["scope"])}
        count = 0
        with self.store.db() as db:
            for doc, vector in zip(missing, vectors):
                if current.get(doc["id"]) != signature(doc["text"]):
                    continue
                vector = normalized(vector, self.client.dimensions)
                db.execute("INSERT OR REPLACE INTO memory_vectors VALUES(?,?,?,?,?,?,?)", (job["scope"], doc["id"], self.client.model, self.client.dimensions, signature(doc["text"]), json.dumps(vector), time.time()))
                count += 1
        return count

    def _cached_query(self, scope, query):
        with self.store.db() as db:
            row = db.execute("SELECT vector FROM query_vectors WHERE scope=? AND id=? AND model=? AND dimensions=? AND updated>?", (scope, signature(query), self.client.model, self.client.dimensions, time.time()-86400)).fetchone()
        return normalized(json.loads(row[0]), self.client.dimensions) if row else None

    def _query(self, job, query):
        if not self._allowed(job):
            return None
        self._reserve_call(job["scope"])
        vector = self.client.embed([query], query=True, timeout=5)[0]
        vector = normalized(vector, self.client.dimensions)
        if not self._allowed(job):
            return None
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO query_vectors VALUES(?,?,?,?,?,?)", (job["scope"], signature(query), self.client.model, self.client.dimensions, json.dumps(vector), time.time()))
            db.execute("DELETE FROM query_vectors WHERE scope=? AND rowid NOT IN (SELECT rowid FROM query_vectors WHERE scope=? ORDER BY updated DESC LIMIT 64)", (job["scope"], job["scope"]))
        return vector

    def recall(self, job, query):
        if not self._allowed(job):
            return []
        query = str(query).strip()[:300]
        if not query:
            return []
        docs = {doc["id"]: doc for doc in self.store.memory_documents(job["scope"])}
        rows = [row for key, row in self._vectors(job["scope"]).items() if key in docs and row["signature"] == signature(docs[key]["text"])]
        if not rows:
            return []
        vector = self._cached_query(job["scope"], query)
        if vector is None:
            with self.lock:
                # No unbounded queue when a provider is slow. Later queries immediately fall back.
                if self.future is not None and not self.future.done():
                    return []
                context = contextvars.copy_context()
                self.future = self.pool.submit(context.run, self._query, job, query)
                future = self.future
            try:
                vector = future.result(timeout=self.query_seconds)
            except Exception:
                return []
        if vector is None or not self._allowed(job) or not self.store.current(job["scope"], job["version"]):
            return []
        scored = []
        for row in rows:
            embedded = normalized(json.loads(row["vector"]), self.client.dimensions)
            score = sum(a*b for a,b in zip(vector, embedded))
            if score >= self.threshold:
                scored.append((score, docs[row["id"]]))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        if not scored:
            return []
        # A much weaker second hit should not pull unrelated memories into the reply.
        return [{"kind": doc["kind"], **doc["record"]} for score,doc in scored[:3] if score >= scored[0][0]-0.08]

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
