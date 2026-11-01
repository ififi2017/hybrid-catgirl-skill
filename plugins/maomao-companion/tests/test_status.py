import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maomao_companion.status import StatusLookup,private_owner,provider_status


class FakeResponse:
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):return json.dumps({'data':self.data}).encode()


class FakeOpen:
    def __init__(self):self.urls=[]
    def open(self,request,timeout):
        self.urls.append(request.full_url)
        return FakeResponse({'total_credits':10,'total_usage':4} if request.full_url.endswith('/credits') else {'limit':10,'limit_remaining':3.5})


class StatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.owner=SimpleNamespace(platform='feishu',chat_type='dm',chat_id='chat',user_id='owner',user_id_alt=None)
        cfg=self.root/'state/maomao-companion/config.json';cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({'target':{'platform':'feishu','chat_type':'dm','chat_id':'chat','user_id':'owner'}}))
        self.sent=[]
        async def send(chat,text,reply_to=None):self.sent.append((chat,text,reply_to))
        async def native(event):return '模型：test-model\n上下文：10 / 100'
        self.gateway=SimpleNamespace(_is_user_authorized_for_source=lambda s:True,_delivery_adapter_for=lambda s:SimpleNamespace(send=send),_handle_status_command=native)
        self.lookup=StatusLookup(self.root)
    def tearDown(self):self.lookup.close();self.tmp.cleanup()
    def test_owner_binding_requires_same_platform_and_private_conversation(self):
        self.assertTrue(private_owner(self.root,self.owner))
        for source in (SimpleNamespace(**{**vars(self.owner),'user_id':'other'}),SimpleNamespace(**{**vars(self.owner),'chat_type':'group'}),SimpleNamespace(**{**vars(self.owner),'platform':'telegram'})):
            self.assertFalse(private_owner(self.root,source))
    def test_provider_limit_and_credit_are_distinct_and_hide_credentials(self):
        opener=FakeOpen();result=provider_status('test-key','test-admin',opener)
        self.assertIn('密钥剩余额度：$3.5000',result);self.assertIn('账户余额：$6.0000',result)
        self.assertNotIn('test-key',result);self.assertNotIn('test-admin',result)
        self.assertEqual(opener.urls,['https://openrouter.ai/api/v1/key','https://openrouter.ai/api/v1/credits'])
        opener=FakeOpen();result=provider_status('test-key','',opener)
        self.assertIn('账户余额：$6.0000',result)
        self.assertEqual(len(opener.urls),2)
    async def test_owner_private_status_uses_native_session_and_account(self):
        event=SimpleNamespace(text='/status',source=self.owner,message_id='m',internal=False)
        with patch('maomao_companion.status.provider_status',return_value='合成额度') as probe:
            result=self.lookup.hook(event=event,gateway=self.gateway)
            self.assertEqual(result['action'],'skip');await asyncio.gather(*list(self.lookup.tasks))
            probe.assert_called_once();self.assertIn('模型：test-model',self.sent[0][1]);self.assertIn('合成额度',self.sent[0][1])
    async def test_group_never_calls_provider_or_exposes_account(self):
        source=SimpleNamespace(platform='qqbot',chat_type='group',chat_id='group',user_id='owner',user_id_alt=None)
        event=SimpleNamespace(text='/status',source=source,message_id='m',internal=False)
        with patch('maomao_companion.status.provider_status') as probe:
            self.lookup.hook(event=event,gateway=self.gateway);await asyncio.gather(*list(self.lookup.tasks))
            probe.assert_not_called();self.assertIn('仅已绑定主人的私聊',self.sent[0][1])
    async def test_unauthorized_or_argument_never_send(self):
        event=SimpleNamespace(text='/status other',source=self.owner,message_id='m',internal=False)
        self.assertIsNone(self.lookup.hook(event=event,gateway=self.gateway))
        event.text='/status';self.gateway._is_user_authorized_for_source=lambda s:False
        self.assertIsNone(self.lookup.hook(event=event,gateway=self.gateway));self.assertEqual(self.sent,[])
