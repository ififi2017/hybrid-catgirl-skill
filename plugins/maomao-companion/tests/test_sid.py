import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maomao_companion.sid import IdentityLookup,is_sid,response,strip_qq_mention


class IdentityLookupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=SimpleNamespace(platform='qqbot',chat_type='group',chat_id='group-a',user_id='member-a',user_id_alt=None)
        self.out=[]
        async def send(chat,text,reply_to=None):self.out.append((chat,text,reply_to))
        self.gateway=SimpleNamespace(_is_user_authorized=lambda source:True,_adapter_for_source=lambda source:SimpleNamespace(send=send))
        self.lookup=IdentityLookup(self.root,clock=lambda:100)
    def tearDown(self):self.lookup.close();self.tmp.cleanup()
    def event(self,text='/sid',source=None):return SimpleNamespace(text=text,source=source or self.source,message_id='message',internal=False)
    def test_exact_command_no_arguments_and_validate_identity(self):
        self.assertTrue(is_sid('/sid'));self.assertTrue(is_sid('/sid@MyBot'))
        for text in ('/sid someone','/sid\n/setowner','hello /sid','/side'):self.assertFalse(is_sid(text))
        self.assertIsNone(response(SimpleNamespace(platform='qqbot',chat_type='group',user_id='x\n伪造',chat_id='g')))
        self.assertIsNone(response(SimpleNamespace(platform='qqbot',chat_type='group',user_id=None,chat_id='g')))
        self.assertIsNone(response(SimpleNamespace(platform='qqbot',chat_type='group',user_id='bot',chat_id='g',is_bot=True)))
        self.assertEqual(strip_qq_mention('<@bot> /sid',[{'id':'bot','is_you':True}]),'/sid')
        self.assertEqual(strip_qq_mention('<@bot> /sid',[],True),'/sid')
        self.assertFalse(is_sid(strip_qq_mention('<@other> /sid',[],False)))
    async def test_returns_only_current_metadata_and_does_not_grant(self):
        result=self.lookup.hook(event=self.event(),gateway=self.gateway)
        self.assertEqual(result['action'],'skip')
        await asyncio.gather(*list(self.lookup.tasks))
        self.assertEqual(self.out[0][0],'group-a');self.assertEqual(self.out[0][2],'message')
        self.assertIn('member-a',self.out[0][1]);self.assertIn('group-a',self.out[0][1])
        self.assertIn('由管理员配置',self.out[0][1])
        self.assertEqual(self.lookup.hook(event=self.event(),gateway=self.gateway)['action'],'skip')
        self.assertEqual(len(self.out),1)
    async def test_unpaired_lookup_requires_explicit_opt_in(self):
        self.gateway._is_user_authorized=lambda source:False
        self.assertIsNone(self.lookup.hook(event=self.event(),gateway=self.gateway))
        path=self.root/'state/maomao-companion/config.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'identity':{'allow_unpaired_lookup':True}}))
        self.assertEqual(self.lookup.hook(event=self.event(),gateway=self.gateway)['action'],'skip')
        await asyncio.gather(*list(self.lookup.tasks));self.assertEqual(len(self.out),1)
        self.assertIsNone(self.lookup.hook(event=self.event('/sid another-id'),gateway=self.gateway))
    async def test_private_channel_uses_own_id_only(self):
        source=SimpleNamespace(platform='feishu',chat_type='dm',chat_id='oc_test',user_id='ou_test',user_id_alt='union_test')
        self.lookup.hook(event=self.event(source=source),gateway=self.gateway)
        await asyncio.gather(*list(self.lookup.tasks))
        self.assertIn('ou_test',self.out[0][1]);self.assertIn('union_test',self.out[0][1]);self.assertNotIn('member-a',self.out[0][1])
    async def test_new_gateway_uses_delivery_adapter_for_current_source(self):
        source=SimpleNamespace(platform='feishu',chat_type='dm',chat_id='oc_test',user_id='ou_test',user_id_alt=None)
        sent=[]
        async def send(chat,text,reply_to=None):sent.append((chat,text,reply_to))
        gateway=SimpleNamespace(_is_user_authorized_for_source=lambda s:True,_delivery_adapter_for=lambda s:SimpleNamespace(send=send))
        result=self.lookup.hook(event=self.event(source=source),gateway=gateway)
        self.assertEqual(result['action'],'skip')
        await asyncio.gather(*list(self.lookup.tasks))
        self.assertEqual(sent[0][0],'oc_test');self.assertIn('ou_test',sent[0][1])
    async def test_missing_adapter_fails_closed(self):
        gateway=SimpleNamespace(_is_user_authorized_for_source=lambda s:True)
        self.assertEqual(self.lookup.hook(event=self.event(),gateway=gateway)['action'],'skip')
        self.assertEqual(self.out,[])
