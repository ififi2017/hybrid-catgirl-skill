import contextvars
import io
import json
import math
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maomao_companion.dialogue import DialogueStore
from maomao_companion.analysis import Analyzer
from maomao_companion.embeddings import OpenRouterEmbeddings, SemanticMemory, normalized


class FakeClient:
    model = "qwen/qwen3-embedding-8b"
    dimensions = 2

    def __init__(self):
        self.calls = []

    def embed(self, texts, query=False, timeout=10):
        self.calls.append((list(texts), query))
        return [[1.,0.] if any(s in text for s in ("种花", "长焦", "羽毛")) else [0.,1.] if "咖啡" in text else [-1.,-1.] for text in texts]


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DialogueStore(Path(self.temp.name)/"ordinary.sqlite3")
        self.client = FakeClient()
        self.allowed = True
        self.memory = SemanticMemory(self.store, self.client, lambda job: self.allowed, query_seconds=0.1)
        self.job = {"scope": "A", "turn_id": "t1", "version": 1}
        self.store.begin("A", "t1", "我喜欢种花", time.time())

    def tearDown(self):
        self.memory.close()
        self.memory.pool.shutdown(wait=True)
        self.temp.cleanup()

    def test_synonym_query_recalls_preference_without_exact_keyword(self):
        self.assertEqual(self.memory.index(self.job), 1)
        self.assertEqual(self.store.context("A", "想买长焦镜头")["user_preferences"], [])
        hits = self.memory.recall(self.job, "想买长焦镜头")
        self.assertEqual(hits[0]["topic"], "种花")
        self.assertEqual(hits[0]["polarity"], 1)

    def test_unrelated_query_returns_no_memories(self):
        self.memory.index(self.job)
        self.assertEqual(self.memory.recall(self.job, "微积分"), [])

    def test_indexing_is_incremental(self):
        self.memory.index(self.job)
        self.assertEqual(self.memory.index(self.job), 0)
        self.assertEqual(len(self.client.calls), 1)

    def test_query_vector_is_cached(self):
        self.memory.index(self.job)
        self.memory.recall(self.job, "长焦")
        self.memory.recall(self.job, "长焦")
        self.assertEqual(sum(query for _,query in self.client.calls), 1)

    def test_no_cross_scope_vectors_or_network_request(self):
        self.memory.index(self.job)
        calls = len(self.client.calls)
        self.assertEqual(self.memory.recall({**self.job, "scope": "B"}, "长焦"), [])
        self.assertEqual(len(self.client.calls), calls)

    def test_private_guard_prevents_all_embedding_calls(self):
        self.allowed = False
        self.assertEqual(self.memory.index(self.job), 0)
        self.assertEqual(self.memory.recall(self.job, "长焦"), [])
        self.assertEqual(self.client.calls, [])

    def test_privacy_switch_during_index_drops_vectors(self):
        original = self.client.embed
        def blocked(*args, **kwargs):
            self.allowed = False
            return original(*args, **kwargs)
        self.client.embed = blocked
        self.assertEqual(self.memory.index(self.job), 0)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM memory_vectors").fetchone()[0], 0)

    def test_privacy_switch_during_query_drops_result_and_cache(self):
        self.memory.index(self.job)
        original = self.client.embed
        def blocked(*args, **kwargs):
            self.allowed = False
            return original(*args, **kwargs)
        self.client.embed = blocked
        self.assertEqual(self.memory.recall(self.job, "长焦"), [])
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM query_vectors").fetchone()[0], 0)

    def test_corrected_fact_never_uses_old_vector(self):
        self.memory.index(self.job)
        self.store.begin("A", "t2", "我不喜欢种花", time.time())
        job = {**self.job, "turn_id": "t2", "version": 2}
        self.assertEqual(self.memory.recall(job, "长焦"), [])
        self.memory.index(job)
        self.assertEqual(self.memory.recall(job, "长焦")[0]["polarity"], -1)

    def test_old_model_vectors_are_not_reused(self):
        self.memory.index(self.job)
        self.client.model = "baai/bge-m3"
        self.assertEqual(self.memory.recall(self.job, "长焦"), [])

    def test_unknown_corpus_does_not_embed_user_query(self):
        with self.store.db() as db:
            db.execute("DELETE FROM facts")
        self.assertEqual(self.memory.recall(self.job, "长焦"), [])
        self.assertEqual(self.client.calls, [])

    def test_daily_api_limit_is_enforced(self):
        self.memory.daily_limit = 1
        self.memory.index(self.job)
        self.assertEqual(self.memory.recall(self.job, "长焦"), [])
        self.assertEqual(len(self.client.calls), 1)

    def test_timeout_falls_back_without_waiting_for_network(self):
        self.memory.index(self.job)
        started, release = threading.Event(), threading.Event()
        original = self.client.embed
        def slow(*args, **kwargs):
            started.set()
            release.wait(timeout=2)
            return original(*args, **kwargs)
        self.client.embed = slow
        try:
            before = time.monotonic()
            self.assertEqual(self.memory.recall(self.job, "长焦"), [])
            self.assertLess(time.monotonic()-before, 0.7)
            self.assertTrue(started.is_set())
            self.assertEqual(self.memory.recall(self.job, "另一支长焦"), [])
        finally:
            release.set()

    def test_stale_turn_query_cannot_supply_context(self):
        self.memory.index(self.job)
        self.store.begin("A", "t2", "新的话题", time.time())
        self.assertEqual(self.memory.recall(self.job, "长焦"), [])

    def test_malformed_vectors_are_rejected(self):
        for vector in ([], [0.,0.], [True,0.], [float('nan'),1.], [float('inf'),1.]):
            with self.assertRaises(ValueError):
                normalized(vector, 2)

    def test_recent_episode_has_time_and_source(self):
        self.store.begin("A", "t2", "种花的计划先搁置", time.time())
        data = {"topic":"种花","status":"paused","summary":"用户暂时搁置种花计划","quote":"种花的计划先搁置","mood":"calm","intensity":0}
        self.assertTrue(self.store.apply_analysis("A", "t2", data))
        job = {**self.job, "turn_id":"t2", "version":2}
        self.memory.index(job)
        hits = self.memory.recall(job, "长焦")
        episode = next(hit for hit in hits if hit["kind"]=="episode")
        self.assertEqual(episode["source_id"], "t2")
        self.assertIn("occurred_at", episode)


class TransportTests(unittest.TestCase):
    def test_provider_response_is_normalized_and_qwen_query_has_instruction(self):
        seen = []
        payload = {"model":"Qwen/Qwen3-Embedding-8B","data":[{"index":0,"embedding":[1.]*1024}]}
        def open_request(request, **kwargs):
            seen.append(json.loads(request.data))
            return io.BytesIO(json.dumps(payload).encode())
        client = OpenRouterEmbeddings(key_provider=lambda model:"synthetic-key")
        with patch("urllib.request.build_opener", return_value=SimpleNamespace(open=open_request)):
            vector = client.embed(["长焦"], query=True)[0]
        self.assertTrue(seen[0]["input"][0].startswith("Instruct:"))
        self.assertAlmostEqual(sum(v*v for v in vector), 1.)
        self.assertEqual(seen[0]["provider"]["data_collection"], "deny")

    def test_remote_error_text_is_not_exposed(self):
        client = OpenRouterEmbeddings(key_provider=lambda model:"synthetic-key")
        with patch("urllib.request.build_opener", return_value=SimpleNamespace(open=lambda *a,**k:(_ for _ in ()).throw(ValueError("SECRET_SENTINEL")))):
            with self.assertRaisesRegex(RuntimeError, "embedding request unavailable") as error:
                client.embed(["synthetic"])
        self.assertNotIn("SECRET_SENTINEL", str(error.exception))

    def test_response_indices_must_match_batch(self):
        response = {"model":"qwen/qwen3-embedding-8b","data":[{"index":1,"embedding":[1.]*1024}]}
        client = OpenRouterEmbeddings(key_provider=lambda model:"synthetic-key")
        with patch("urllib.request.build_opener", return_value=SimpleNamespace(open=lambda *a,**k:io.BytesIO(json.dumps(response).encode()))):
            with self.assertRaises(RuntimeError):
                client.embed(["synthetic"])

    def test_background_analysis_preserves_profile_context(self):
        profile = contextvars.ContextVar("synthetic_profile", default="wrong")
        observed = []
        done = threading.Event()
        analyzer = Analyzer(None, None, lambda job:True)
        analyzer.process = lambda job: (observed.append(profile.get()), done.set())
        token = profile.set("correct")
        try:
            analyzer.submit({})
        finally:
            profile.reset(token)
        try:
            self.assertTrue(done.wait(timeout=1))
            self.assertEqual(observed, ["correct"])
        finally:
            analyzer.close()
            analyzer.thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
