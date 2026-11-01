import concurrent.futures
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maomao_companion.delivery import DeliveryLedger,bubbles,voice_requested,message_ids,response_metadata

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=1000
        self.db=DeliveryLedger(Path(self.tmp.name)/'delivery.db',clock=lambda:self.now)
        self.db.admit('qqbot','g','m','请用语音回复')
    def tearDown(self): self.tmp.cleanup()
    def test_explicit_voice_only(self):
        for value in ('请用语音回复','念给我听','发条语音','语音回答一下','能不能用语音说一句','可不可以发语音','不要文字，用语音回复','能不能语音','可以语音吗'): self.assertTrue(voice_requested(value),value)
        for value in ('[语音]','不要语音回复','如果能发语音就好了','`发语音`','你的声音很好听','不能发语音','能不能不要发语音','可不可以不用语音'): self.assertFalse(voice_requested(value),value)
        self.assertTrue(self.db.voice_allowed('qqbot','g','m'))
        self.db.admit('qqbot','g','next','普通消息')
        self.assertFalse(self.db.voice_allowed('qqbot','g','m'))
    def test_collection_receipt_does_not_replace_active_admission_or_voice(self):
        self.db.note_receipt('qqbot','g','new-image')
        self.assertEqual(self.db.current('qqbot','g')['anchor'],'m')
        self.assertTrue(self.db.voice_allowed('qqbot','g','m'))
        ticket,_=self.db.reserve('qqbot','g','new-image',{'content':'偷走啦'})
        self.assertEqual(ticket['seq'],1)
        self.assertEqual(self.db.remaining('qqbot','g','new-image'),4)
        self.assertEqual(self.db.current('qqbot','g')['anchor'],'m')

    def test_receipt_uses_original_timestamp_even_when_admission_is_later(self):
        self.db.note_receipt('qqbot','g','image')
        self.now+=301
        self.db.admit('qqbot','g','image','hello')
        with self.assertRaises(PermissionError):self.db.reserve('qqbot','g','image',{'content':'too late'})

    def test_current_own_text_corrects_quote_without_creating_authority(self):
        received=self.db.current('qqbot','g')['received']
        self.assertTrue(self.db.correct_voice('qqbot','g','m','好，明白了'))
        self.assertFalse(self.db.voice_allowed('qqbot','g','m'))
        self.assertTrue(self.db.correct_voice('qqbot','g','m','能不能用语音说一句'))
        self.assertTrue(self.db.voice_allowed('qqbot','g','m'))
        self.assertEqual(self.db.current('qqbot','g')['received'],received)
        self.assertFalse(self.db.correct_voice('qqbot','another-chat','m','请发语音'))
        self.assertIsNone(self.db.current('qqbot','another-chat'))

    def test_code_and_information_preserved(self):
        self.assertEqual(bubbles('a<|bubble|>b<|bubble|>c',2),['a','b\n\nc'])
        self.assertEqual(len(bubbles('```\na\n\nb\n```')),1)
        self.assertEqual(bubbles('a\n\nb'),['a','b'])
    def test_shared_media_budget_and_idempotency(self):
        ticket,fresh=self.db.reserve('qqbot','g','m',{'content':'x','msg_seq':99},limit=2)
        self.assertTrue(fresh);self.db.finish(ticket,True,'sent-id')
        again,fresh=self.db.reserve('qqbot','g','m',{'content':'x','msg_seq':123},limit=2)
        self.assertFalse(fresh);self.assertEqual(again['message_id'],'sent-id')
        image,_=self.db.reserve('qqbot','g','m',{'media':{'file_info':'one'}},limit=2)
        self.assertEqual(image['seq'],2);self.db.finish(image,False)
        with self.assertRaises(PermissionError): self.db.reserve('qqbot','g','m',{'content':'extra'},limit=2)
    def test_atomic_parallel_limit(self):
        def reserve(i):
            try: return self.db.reserve('qqbot','g','m',{'content':str(i)})[0]['seq']
            except PermissionError: return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: values=list(pool.map(reserve,range(8)))
        self.assertEqual(sorted(v for v in values if v),[1,2,3,4,5])
    def test_expired_and_wrong_anchor(self):
        self.now+=301
        with self.assertRaises(PermissionError): self.db.reserve('qqbot','g','m',{'content':'x'})
        self.assertFalse(self.db.voice_allowed('qqbot','other'))
    def test_artifact_grant_is_scoped(self):
        path=Path(self.tmp.name)/'generated.png';path.write_bytes(b'dummy')
        self.db.grant_artifact('qqbot','g','m',path)
        self.assertTrue(self.db.artifact_allowed('qqbot','g','m',path))
        self.assertFalse(self.db.artifact_allowed('qqbot','other','m',path))
        self.now+=601;self.assertFalse(self.db.artifact_allowed('qqbot','g','m',path))

class ToolBoundaryTests(unittest.TestCase):
    def test_qq_reference_and_output_paths_stay_in_conversation(self):
        import importlib.util,json,os
        from unittest.mock import patch
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'HERMES_HOME':folder}):
            home=Path(folder);(home/'sessions').mkdir()
            (home/'sessions/sessions.json').write_text(json.dumps({'key':{'session_id':'sid','origin':{'platform':'qqbot','chat_id':'group-a','chat_type':'group'}}}))
            spec=importlib.util.spec_from_file_location('media_boundary_plugin',root/'__init__.py',submodule_search_locations=[str(root)])
            mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
            hooks={}
            class Context:
                def register_hook(self,name,fn): hooks.setdefault(name,[]).append(fn)
            mod.register(Context())
            admit=next(f for f in hooks['post_gateway_admission'] if f.__name__=='delivery_admission')
            admit(source={'platform':'qqbot','chat_id':'group-a'},message_id='m',text='请用语音回复')
            image_gate=next(f for f in hooks['pre_tool_call'] if f.__name__=='image_reference_gate')
            voice_gate=next(f for f in hooks['pre_tool_call'] if f.__name__=='voice_gate')
            self.assertEqual(image_gate(tool_name='image_generate',args={'image_url':str(home/'private/photo.png')},session_id='sid')['action'],'block')
            self.assertIsNone(image_gate(tool_name='image_generate',args={'image_url':'https://example.org/user-image.png'},session_id='sid'))
            self.assertEqual(voice_gate(tool_name='text_to_speech',args={'output_path':str(home/'private/overwrite.mp3')},session_id='sid')['action'],'block')
            self.assertIsNone(voice_gate(tool_name='text_to_speech',args={},session_id='sid'))


class ResponseMetadataTests(unittest.TestCase):
    def test_sdk_response_object_and_duplicate_id(self):
        from types import SimpleNamespace as N
        result=N(raw_response=N(data=N(message_id="sdk-id")),message_id="sdk-id")
        self.assertEqual(message_ids(result),["sdk-id"])
        self.assertEqual(response_metadata(result),{"message_ids":["sdk-id"]})
    def test_create_response_missing_data_keeps_send_result_id(self):
        from types import SimpleNamespace as N
        self.assertEqual(message_ids(N(raw_response=N(data=None),message_id="created")),["created"])
    def test_telegram_all_ids_and_continuations_preserved(self):
        from types import SimpleNamespace as N
        result=N(raw_response={"message_ids":["first","second"],"partial_overflow":True},message_id="first",continuation_message_ids=["third"])
        self.assertEqual(message_ids(result),["first","second","third"])
        self.assertTrue(response_metadata(result)["partial_overflow"])
    def test_scalar_metadata_does_not_crash_or_split_id(self):
        from types import SimpleNamespace as N
        self.assertEqual(message_ids(N(raw_response="not-a-dict",message_id="id")),["id"])
        self.assertEqual(message_ids(N(raw_response={"message_ids":"whole-id"},message_id=None)),["whole-id"])


class VoiceContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=1000
        self.db=DeliveryLedger(Path(self.tmp.name)/'voice.db',clock=lambda:self.now)
        self.db.admit('qqbot','g','first','请用语音回复',actor='alice')
    def tearDown(self):self.tmp.cleanup()
    def test_same_speaker_language_followup_and_repeat(self):
        self.now+=208
        self.db.admit('qqbot','g','japanese','用英语再来一下',actor='alice')
        self.assertTrue(self.db.voice_allowed('qqbot','g','japanese'))
        self.db.correct_voice('qqbot','g','japanese','用英语再来一下')
        self.assertTrue(self.db.voice_allowed('qqbot','g','japanese'))
        self.db.admit('qqbot','g','repeat','再说一遍',actor='alice')
        self.assertTrue(self.db.voice_allowed('qqbot','g','repeat'))
        self.assertEqual(self.db.voice_language('qqbot','g','repeat'),'en')
        self.db.admit('qqbot','g','tone','再凶一点',actor='alice')
        self.assertTrue(self.db.voice_allowed('qqbot','g','tone'))
    def test_other_person_and_other_group_do_not_inherit(self):
        self.db.admit('qqbot','g','bob','用英语再来一下',actor='bob')
        self.assertFalse(self.db.voice_allowed('qqbot','g','bob'))
        self.db.admit('qqbot','other','x','再来一遍',actor='alice')
        self.assertFalse(self.db.voice_allowed('qqbot','other','x'))
    def test_normal_message_breaks_voice_continuation(self):
        self.db.admit('qqbot','g','normal','好耶',actor='alice')
        self.assertFalse(self.db.voice_allowed('qqbot','g'))
        self.db.admit('qqbot','g','later','再来一遍',actor='alice')
        self.assertFalse(self.db.voice_allowed('qqbot','g'))
    def test_explicit_text_request_and_no_actor_do_not_inherit(self):
        self.db.admit('qqbot','g','text','用文字再来一遍',actor='alice')
        self.assertFalse(self.db.voice_allowed('qqbot','g'))
        self.db.admit('qqbot','g','anonymous','用英语再来一下')
        self.assertFalse(self.db.voice_allowed('qqbot','g'))
    def test_time_limit_and_ordinary_translation_question(self):
        self.now+=3601
        self.db.admit('qqbot','g','late','再来一遍',actor='alice')
        self.assertFalse(self.db.voice_allowed('qqbot','g'))
        self.db.admit('qqbot','g','explicit','发语音',actor='alice')
        self.db.admit('qqbot','g','question','这句话日语怎么说',actor='alice')
        self.assertFalse(self.db.voice_allowed('qqbot','g'))


class SpeechVoiceTests(unittest.TestCase):
    def test_chinese_voice_preserved_and_foreign_voice_selected(self):
        from unittest.mock import patch
        from maomao_companion.providers import speech_voice,VOICE
        with patch.dict('os.environ',{'MAOMAO_MULTILINGUAL_VOICE':'longanfengyue_v3.1'}):
            self.assertEqual(speech_voice('主人你好呀'),VOICE)
            self.assertEqual(speech_voice('おはようございます'),'longanfengyue_v3.1')
            self.assertEqual(speech_voice('Good morning'),'longanfengyue_v3.1')
    def test_latest_positive_language_choice(self):
        from maomao_companion.delivery import requested_language
        self.assertEqual(requested_language('不要中文，换成日语'),'ja')
        self.assertEqual(requested_language('不用日语，换成中文'),'zh')
