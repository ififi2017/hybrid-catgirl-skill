import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('qq_engagement_test',Path(__file__).resolve().parents[1]/'engagement.py')
engagement=importlib.util.module_from_spec(spec);spec.loader.exec_module(engagement)


class EngagementTests(unittest.IsolatedAsyncioTestCase):
    def test_opt_in_and_exact_group(self):
        self.assertFalse(engagement.enabled({},'g'))
        cfg={'autonomous':{'enabled':True,'groups':['g'],'group_messages_to_model':True}}
        self.assertTrue(engagement.enabled(cfg,'g'));self.assertFalse(engagement.enabled(cfg,'other'))
        cfg['autonomous']['group_messages_to_model']=False;self.assertFalse(engagement.enabled(cfg,'g'))
    async def test_model_receives_bounded_data_and_stale_result_is_dropped(self):
        calls=[]
        class Model:
            def complete_structured(self,**kw):calls.append(kw);return SimpleNamespace(parsed={'reply':True})
        bot=engagement.Engagement(SimpleNamespace(llm=Model()),clock=lambda:1000)
        v=bot.received('g','m','user')
        async def fast(_):pass
        with patch.object(engagement.asyncio,'sleep',fast):
            self.assertTrue(await bot.decide('g','m','user','hello',v,[{'text':'hello','observed':999}]))
            self.assertFalse(await bot.decide('g','m','user','hello',v-1,[]))
            self.assertFalse(await bot.decide('g','m','user','hello',v,[],authorized=lambda:False))
        self.assertEqual(len(calls),1)
        self.assertNotIn('user',calls[0]['input'][0]['text']);self.assertNotIn('group_id',calls[0]['input'][0]['text'])
    async def test_only_actual_same_recipient_reply_enables_followup(self):
        bot=engagement.Engagement(SimpleNamespace(),clock=lambda:1000)
        bot.received('g','m','alice');bot.sent('g','m','hello')
        bot.clock=lambda:1005
        self.assertEqual(bot.permitted('g','alice'),(True,True))
        bot.state('g')['starts']=[1000]
        self.assertEqual(bot.permitted('g','bob'),(False,False))
        bot.state('g')['checks']=[1000]*60
        self.assertEqual(bot.permitted('g','alice'),(False,True))
    async def test_new_message_discards_inflight_result(self):
        import asyncio, threading
        started=threading.Event();release=threading.Event()
        class Model:
            def complete_structured(self,**kwargs):
                started.set();release.wait(2);return SimpleNamespace(parsed={'reply':True})
        bot=engagement.Engagement(SimpleNamespace(llm=Model()),clock=lambda:1000)
        old=bot.received('g','first','alice')
        real_sleep=asyncio.sleep
        async def fast(_):await real_sleep(0)
        with patch.object(engagement.asyncio,'sleep',fast):
            pending=asyncio.create_task(bot.decide('g','first','alice','one',old,[]))
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            latest=bot.received('g','second','alice');release.set()
            self.assertFalse(await pending)
            self.assertTrue(await bot.decide('g','second','alice','two',latest,[]))
