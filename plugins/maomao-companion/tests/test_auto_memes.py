import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maomao_companion.auto_memes import AutoMemes
from maomao_companion.library import MemeStore

class AutoMemeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.now=1000
        (self.root/'sessions').mkdir()
        self.source={'platform':'qqbot','chat_type':'group','chat_id':'group-a'}
        (self.root/'sessions/sessions.json').write_text(json.dumps({'k':{'session_id':'s','origin':self.source}}))
        self.hooks={};self.calls=0;self.allow=True;self.selection='image-id';self.sent=[]
        self.file=self.root/'library/image.png';self.file.parent.mkdir();self.file.write_bytes(b'fake')
        self.claims=0
        def claim(path):self.claims+=1;return self.claims==1
        self.store=SimpleNamespace(path=self.root/'library/library.db',root=self.root/'library',search=lambda *args:[{'id':'image-id','description':'开心猫猫','category':'开心','media':'MEDIA:'+str(self.file),'score':.8}],claim=claim)
        def judge(**kwargs):
            self.assertIsInstance(kwargs['input'],list)
            self.assertEqual(kwargs['input'][0]['type'],'text')
            self.calls+=1;return SimpleNamespace(parsed={'choice':self.selection})
        ctx=SimpleNamespace(llm=SimpleNamespace(complete_structured=judge),register_hook=lambda n,f:self.hooks.setdefault(n,[]).append(f))
        self.auto=AutoMemes(ctx,self.root,lambda s:self.store,lambda s:None,lambda s:s['platform']=='qqbot',lambda *args:self.allow,clock=lambda:self.now)
        self.adapter=SimpleNamespace(send_image_file=self.image)
        self.result=SimpleNamespace(success=True)
    async def asyncTearDown(self):
        self.auto.close()
        if self.auto.tasks:await asyncio.gather(*self.auto.tasks,return_exceptions=True)
        self.tmp.cleanup()
    async def image(self,*args,**kwargs):self.sent.append((args,kwargs));return SimpleNamespace(success=True)
    def prepare(self,anchor='m',turn='t',reply='好耶<|bubble|>猫猫开心'):
        self.auto.delivery.admit('qqbot','group-a',anchor,'好耶')
        self.auto.admission(source=self.source,message_id=anchor,text='好耶',session_key='k')
        self.auto.before(session_id='s',turn_id=turn,model='ordinary',platform='qqbot')
        self.auto.after(session_id='s',turn_id=turn,assistant_response=reply)
        return reply
    async def drain(self):
        async def fast(*args):pass
        with patch('asyncio.sleep',fast):
            if self.auto.tasks:await asyncio.gather(*list(self.auto.tasks))
    async def test_only_after_complete_successful_delivery_and_once(self):
        reply=self.prepare()
        self.assertEqual(self.calls,0)
        self.auto.after_send(self.adapter,'qqbot','group-a','m','好耶',self.result)
        self.assertFalse(self.auto.tasks)
        self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,self.result)
        self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,self.result)
        await self.drain()
        self.assertEqual(self.calls,1);self.assertEqual(len(self.sent),1)
        self.assertEqual(self.sent[0][1]['reply_to'],'m')
    async def test_model_can_decline_or_return_invalid_id(self):
        for i,choice in enumerate(('none','invented-path')):
            self.selection=choice;reply=self.prepare(str(i),str(i))
            self.auto.after_send(self.adapter,'qqbot','group-a',str(i),reply,self.result);await self.drain()
        self.assertEqual(self.sent,[]);self.assertEqual(self.claims,0)
    async def test_failed_text_or_existing_media_never_appends(self):
        reply=self.prepare();self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,SimpleNamespace(success=False));await self.drain()
        self.prepare('n','n','hello\nMEDIA:/existing.png')
        self.auto.after_send(self.adapter,'qqbot','group-a','n','hello',self.result);await self.drain()
        self.assertEqual(self.calls,0)
    async def test_media_tool_already_handled_turn(self):
        self.auto.delivery.admit('qqbot','group-a','m','hi')
        self.auto.admission(source=self.source,message_id='m',text='hi',session_key='k')
        self.auto.before(session_id='s',turn_id='t',model='ordinary',platform='qqbot')
        self.auto.tool(tool_name='text_to_speech',session_id='s',turn_id='t')
        self.auto.after(session_id='s',turn_id='t',assistant_response='hi')
        self.auto.after_send(self.adapter,'qqbot','group-a','m','hi',self.result);await self.drain()
        self.assertEqual(self.calls,0)
    async def test_new_message_during_judgment_cancels_stale_image(self):
        def delayed(**kwargs):
            self.auto.delivery.admit('qqbot','group-a','new','new message')
            return SimpleNamespace(parsed={'choice':'image-id'})
        self.auto.ctx.llm.complete_structured=delayed;reply=self.prepare()
        self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,self.result);await self.drain()
        self.assertEqual(self.sent,[])
    async def test_privacy_switch_blocks_judgment_and_sending(self):
        reply=self.prepare();self.allow=False
        self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,self.result);await self.drain()
        self.assertEqual(self.calls,0)
    async def test_passive_budget_exhausted(self):
        reply=self.prepare()
        for i in range(5):self.auto.delivery.reserve('qqbot','group-a','m',{'content':str(i)})
        self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,self.result);await self.drain()
        self.assertEqual(self.calls,0)
    async def test_cooldown_and_empty_library_skip_request(self):
        reply=self.prepare();self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,self.result);await self.drain()
        reply=self.prepare('n','n');self.auto.after_send(self.adapter,'qqbot','group-a','n',reply,self.result);await self.drain()
        self.assertEqual(self.calls,1)
        self.now+=46;self.store.search=lambda *args:[]
        reply=self.prepare('p','p');self.auto.after_send(self.adapter,'qqbot','group-a','p',reply,self.result);await self.drain()
        self.assertEqual(self.calls,1)
    async def test_original_public_512_stickers_are_allowed(self):
        path=self.root/'stickers/512/A2.png';path.parent.mkdir(parents=True);path.write_bytes(b'public')
        self.store.search=lambda *args:[{'id':'image-id','description':'public','category':'赞同','media':'MEDIA:'+str(path),'score':1}]
        reply=self.prepare();self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,self.result);await self.drain()
        self.assertEqual(len(self.sent),1)

    async def test_candidate_path_cannot_escape_gallery(self):
        self.store.search=lambda *args:[{'id':'image-id','description':'fake','category':'其他','media':'MEDIA:/outside/private.png','score':1}]
        reply=self.prepare();self.auto.after_send(self.adapter,'qqbot','group-a','m',reply,self.result);await self.drain()
        self.assertEqual(self.sent,[])
