import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memes import MemeStore, image_input, local_media_allowed, group_key
from maomao_companion.library import collection_reply
from identity import group_for_session, conversation_for_session
from faces import face_text


class MemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root/"synthetic.png"
        im = Image.new("RGB", (120, 120), "white")
        draw = ImageDraw.Draw(im); draw.ellipse((20,20,100,100), fill="yellow"); draw.arc((30,40,90,90),0,180,fill="black",width=5)
        im.save(self.image)
        self.result = {"description": "黄色笑脸，表达开心赞同", "text": "好耶", "category": "开心", "is_meme": True, "confidence": .95, "personal_or_sensitive": False}
        self.store = MemeStore(self.root/"library", "group-a")

    def tearDown(self):
        self.temp.cleanup()

    def test_explicit_meme_collected_and_original_bytes_preserved(self):
        row = self.store.remember(self.image, self.result, explicit=True)
        self.assertEqual(Path(row["path"]).read_bytes(), self.image.read_bytes())
        self.assertEqual(self.store.search("开心")[0]["id"], row["id"])

    def test_ordinary_image_requires_repetition_and_meme_judgment(self):
        self.assertIsNone(self.store.remember(self.image,self.result)["path"])
        self.assertTrue(self.store.remember(self.image,self.result)["path"])
        self.assertEqual(len(self.store.search("开心")), 1)

    def test_photo_personal_and_low_confidence_not_collected(self):
        self.assertIsNone(self.store.remember(self.image,{**self.result,"personal_or_sensitive":True},explicit=True))
        for change in ({"is_meme":False}, {"confidence":.3}):
            self.assertIsNone(self.store.remember(self.image,{**self.result,**change},explicit=True)["path"])
        self.assertEqual(self.store.search("开心"), [])

    def test_explicit_sticker_threshold_and_operator_recheck_preserve_receipt(self):
        first=self.store.remember(self.image,{**self.result,"confidence":.82})
        self.assertFalse(first["eligible"]);self.assertIsNone(first["path"])
        repaired=self.store.remember(self.image,{**self.result,"confidence":.82},explicit=True,count_sighting=False)
        self.assertTrue(repaired["eligible"]);self.assertTrue(repaired["path"])
        self.assertEqual(repaired["seen"],1)
        self.assertEqual(repaired["last_seen"],first["last_seen"])
        self.assertTrue(self.store.search("开心"))

    def test_reason_cached_once_and_only_new_collection_triggers_notice(self):
        first=self.store.remember(self.image,{**self.result,'steal_reason':'这个憋笑脸拿来看热闹正合适'})
        self.assertFalse(first['newly_collected'])
        self.assertEqual(self.store.known(first['id'])['steal_reason'],'这个憋笑脸拿来看热闹正合适')
        second=self.store.remember(self.image,self.result)
        self.assertTrue(second['newly_collected'])
        self.assertTrue(self.store.claim_collection_notice(second['id'],now=1000))
        self.assertFalse(self.store.claim_collection_notice(second['id'],now=1100))
        repeated=self.store.remember(self.image,self.result,explicit=True)
        self.assertFalse(repeated['newly_collected'])
        self.assertIn('看热闹',collection_reply(second['steal_reason']))
        self.assertNotIn('@everyone',collection_reply('@everyone 看这里'))

    def test_collection_notices_throttle_a_burst_without_late_repeat(self):
        row=self.store.remember(self.image,self.result,explicit=True)
        self.assertTrue(self.store.claim_collection_notice(row['id'],now=1000))
        source=self.root/'another.png';Image.new('RGB',(120,120),'green').save(source)
        other=self.store.remember(source,{**self.result,'text':'另一张'},explicit=True)
        self.assertTrue(other['newly_collected'])
        self.assertFalse(self.store.claim_collection_notice(other['id'],now=1001))
        self.assertFalse(self.store.claim_collection_notice(other['id'],now=1100))

    def test_uncollected_image_does_not_get_a_collection_notice(self):
        row=self.store.remember(self.image,{**self.result,'is_meme':False},explicit=True)
        self.assertFalse(self.store.claim_collection_notice(row['id']))

    def test_collection_state_is_visible_without_changing_receipt_time(self):
        self.store.observe_message('receipt','alice','[图片]')
        before=self.store.conversation_context()[0]['observed']
        row=self.store.remember(self.image,{**self.result,'steal_reason':'拿来庆祝正合适'},explicit=True)
        self.store.annotate_collection('receipt',row['id'],True)
        context=self.store.conversation_context()[0]
        self.assertEqual(context['observed'],before)
        self.assertIn('notice_sent',context['text'])
        self.assertIn('拿来庆祝',context['text'])

    def test_operator_seed_does_not_announce_a_new_collection(self):
        row=self.store.remember(self.image,self.result,explicit=True,count_sighting=False)
        self.assertTrue(row['path']);self.assertFalse(row['newly_collected'])

    def test_group_libraries_are_physically_separate(self):
        self.store.remember(self.image,self.result,explicit=True)
        other = MemeStore(self.root/"library", "group-b")
        self.assertNotEqual(self.store.path, other.path)
        self.assertEqual(other.search("开心"), [])

    def test_auto_sticker_claim_is_atomic_and_cannot_repeat(self):
        row=self.store.remember(self.image,self.result,explicit=True)
        self.assertTrue(self.store.claim(row["path"]))
        self.assertFalse(self.store.claim(row["path"]))
        self.assertEqual(self.store.search("开心"),[])

    def test_accepted_send_has_repeat_cooldown(self):
        row = self.store.remember(self.image,self.result,explicit=True)
        self.store.sent(row["path"])
        self.assertEqual(self.store.search("开心"), [])

    def test_no_match_does_not_force_random_meme(self):
        self.store.remember(self.image,self.result,explicit=True)
        self.assertEqual(self.store.search("晚安"), [])

    def test_semantic_search_and_provider_failure_keyword_fallback(self):
        vectors = SimpleNamespace(model="test", embed=lambda texts,**kw:[[1.,0.] for t in texts])
        self.store.remember(self.image,self.result,explicit=True,embedder=vectors)
        self.assertEqual(len(self.store.search("心情特别好",vectors)),1)
        def fail(*args): raise TimeoutError()
        vectors.embed = fail
        self.assertEqual(len(self.store.search("开心",vectors)),1)

    def test_budget_is_persistent(self):
        self.assertTrue(self.store.reserve("vision",1))
        self.assertFalse(MemeStore(self.root/"library","group-a").reserve("vision",1))

    def test_animated_gif_retains_animation_and_vision_has_multiple_frames(self):
        gif = self.root/"synthetic.gif"
        Image.new("RGB",(64,64),"red").save(gif,save_all=True,append_images=[Image.new("RGB",(64,64),"blue")],duration=100,loop=0)
        thumb,ext,_ = image_input(gif)
        self.assertEqual(Image.open(io.BytesIO(thumb)).size,(512,512))
        row = self.store.remember(gif,self.result,explicit=True)
        with Image.open(row["path"]) as stored:
            self.assertEqual(stored.n_frames,2)

    def test_near_duplicate_same_caption_not_second_sticker(self):
        self.store.remember(self.image,self.result,explicit=True)
        im = Image.open(self.image); im.save(self.root/"different.png",compress_level=1)
        row = self.store.remember(self.root/"different.png",self.result,explicit=True)
        if row["id"] != hashlib.sha256(self.image.read_bytes()).hexdigest():
            self.assertIsNone(row["path"])

    def test_transport_never_imports_builtin_qq_adapter(self):
        for path in (ROOT/"transport").glob("*.py"):
            self.assertNotIn("gateway.platforms.qqbot",path.read_text())

    def test_unmentioned_messages_persist_without_duplicate_replay(self):
        self.store.observe_message("m1","alice","今天看到一只鸟")
        self.store.observe_message("m1","alice","changed on replay")
        rows = MemeStore(self.root/"library","group-a").conversation_context()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["text"],"今天看到一只鸟")
        self.assertNotEqual(rows[0]["speaker"],"alice")
        self.assertEqual(MemeStore(self.root/"library","group-b").conversation_context(),[])

    def test_outbound_media_cannot_read_another_group_or_private_file(self):
        home=self.root/"home"
        self.assertTrue(local_media_allowed(home,"a",home/"state/maomao-qq/groups"/group_key("a")/"cat.png"))
        self.assertTrue(local_media_allowed(home,"a",home/"stickers/512/A2.png"))
        self.assertFalse(local_media_allowed(home,"a",home/"state/maomao-qq/groups"/group_key("b")/"cat.png"))
        self.assertFalse(local_media_allowed(home,"a",home.parent/"private/memory.png"))

    def test_same_group_session_aliases_resolve_once(self):
        row={"session_id":"s","origin":{"platform":"qqbot","chat_type":"group","chat_id":"a"}}
        self.assertEqual(group_for_session({"old":row,"new":row},"s"),"a")

    def test_cross_group_ambiguous_session_still_denied(self):
        rows={k:{"session_id":"s","origin":{"platform":"qqbot","chat_type":"group","chat_id":k}} for k in ("a","b")}
        with self.assertRaises(ValueError): group_for_session(rows,"s")

    def test_platform_face_label_is_decoded_without_claiming_vision(self):
        import base64
        value=base64.b64encode(json.dumps({"text":"[给你一拳]"},ensure_ascii=False).encode()).decode()
        tag='<faceType=4,faceId="",ext="'+value+'">'
        decoded=face_text(tag)
        self.assertIn("给你一拳",decoded);self.assertIn("未附原图",decoded)
        self.assertNotIn(value,decoded)
        self.assertNotIn("未附原图",face_text(tag,True))
        self.assertNotIn("faceType",face_text('<faceType=6,faceId="0",ext="bad!">'))

    def test_qq_dm_gallery_identity_is_distinct_from_group(self):
        dm={"session_id":"s","origin":{"platform":"qqbot","chat_type":"dm","chat_id":"a"}}
        self.assertEqual(conversation_for_session({"one":dm},"s")["library_key"],"dm:a")
        group={"session_id":"s","origin":{"platform":"qqbot","chat_type":"group","chat_id":"a"}}
        with self.assertRaises(ValueError): conversation_for_session({"one":dm,"two":group},"s")

    def test_private_or_missing_session_cannot_select_group(self):
        row={"session_id":"s","origin":{"platform":"telegram","chat_type":"dm","chat_id":"a"}}
        for rows,sid in [({"a":row},"s"),({},"s"),({},None)]:
            with self.assertRaises(ValueError): group_for_session(rows,sid)

    def test_background_caption_keeps_original_timestamp(self):
        self.assertTrue(self.store.observe_message("image1","alice","[图片]"))
        self.assertFalse(self.store.observe_message("image1","alice","[图片]"))
        original=self.store.conversation_context()[0]["observed"]
        self.store.annotate_image("image1","[图片]","一只开心的猫")
        result=self.store.conversation_context()[0]
        self.assertEqual(result["observed"],original)
        self.assertIn("开心的猫",result["text"])

    def test_semantic_query_cache_avoids_repeating_external_calls(self):
        calls=[]
        def embed(texts,**kwargs):
            calls.append(kwargs.get("timeout")); return [[1.,0.] for t in texts]
        client=SimpleNamespace(model="synthetic",embed=embed)
        self.store.remember(self.image,self.result,explicit=True,embedder=client)
        calls.clear()
        self.assertTrue(self.store.search("特别开心",client))
        self.assertTrue(self.store.search("特别开心",client))
        self.assertEqual(calls,[2])


if __name__ == "__main__":
    unittest.main()
