import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maomao_companion import authorization as auth


class StandaloneAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.user={'platform':'feishu','chat_type':'dm','chat_id':'chat-a','user_id':'alice'}
        self.cfg={'enabled':True,'authorization':{'mode':'standalone'},'target':self.user}
        (self.root/'sessions').mkdir();(self.root/'sessions/sessions.json').write_text(json.dumps({'key':{'session_id':'sid','origin':self.user}}))
    def tearDown(self):self.tmp.cleanup()
    def test_requires_explicit_mode_matching_admission_and_current_session(self):
        self.assertFalse(auth.allowed(self.root,self.cfg,'key','sid',now=100))
        self.assertFalse(auth.admit(self.root,{**self.cfg,'authorization':{}},'key',self.user,now=100))
        self.assertFalse(auth.admit(self.root,self.cfg,'key',{**self.user,'chat_type':'group'},now=100))
        self.assertFalse(auth.admit(self.root,self.cfg,'key',{**self.user,'user_id':'other'},now=100))
        self.assertTrue(auth.admit(self.root,self.cfg,'key',self.user,now=100))
        self.assertTrue(auth.allowed(self.root,self.cfg,'key','sid',now=101))
        self.assertFalse(auth.allowed(self.root,self.cfg,'key','other',now=101))
        self.assertFalse(auth.allowed(self.root,self.cfg,'key','sid',now=401))
        self.assertFalse(auth.allowed(self.root,{**self.cfg,'enabled':False},'key','sid',now=101))
        self.assertFalse(auth.allowed(self.root,{**self.cfg,'authorization':None},'key','sid',now=101))
    def test_profile_and_origin_do_not_cross(self):
        auth.admit(self.root,self.cfg,'key',self.user,now=100)
        self.assertFalse(auth.allowed(self.root/'other',self.cfg,'key','sid',now=101))
        (self.root/'sessions/sessions.json').write_text(json.dumps({'key':{'session_id':'sid','origin':{**self.user,'chat_id':'other'}}}))
        self.assertFalse(auth.allowed(self.root,self.cfg,'key','sid',now=101))
    def test_standalone_never_overrides_an_existing_host_policy(self):
        auth.admit(self.root,self.cfg,'key',self.user,now=100)
        path=self.root/'state/maomao-companion/session-policy.json'
        path.parent.mkdir(parents=True);path.write_text('{}')
        self.assertFalse(auth.allowed(self.root,self.cfg,'key','sid',now=101))
        self.assertFalse(auth.admit(self.root,self.cfg,'key',self.user,now=101))
    def test_distinct_import_names_share_same_process_lease(self):
        spec=importlib.util.spec_from_file_location('independent_authorization',Path(auth.__file__))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        auth.admit(self.root,self.cfg,'key',self.user,now=100)
        self.assertTrue(module.allowed(self.root,self.cfg,'key','sid',now=101))

    def test_registered_admission_hook_enables_normal_memory_for_bound_session(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        root=Path(auth.__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('standalone_hook_test',root/'__init__.py',submodule_search_locations=[str(root)])
        plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=plugin;spec.loader.exec_module(plugin)
        configdir=self.root/'state/maomao-companion';configdir.mkdir(parents=True)
        cfg={**self.cfg,'context':{'enabled':True,'allowed_models':['ordinary']}}
        (configdir/'config.json').write_text(json.dumps(cfg))
        hooks={};closers=[]
        ctx=SimpleNamespace(register_hook=lambda name,fn:hooks.setdefault(name,[]).append(fn),register_tool=lambda **kw:None,on_unload=closers.append)
        with patch.dict('os.environ',{'HERMES_HOME':str(self.root)}):
            try:
                plugin.register(ctx)
                for hook in hooks['post_gateway_admission']:
                    hook(session_key='key',source=self.user,message_id='message',text='synthetic')
                from maomao_companion.context import CompanionContext
                independently_imported=CompanionContext(ctx)
                self.assertTrue(independently_imported.allowed({'session_key':'key','session_id':'sid','model':'ordinary'}))
                self.assertFalse(independently_imported.allowed({'session_key':'key','session_id':'sid','model':'unapproved'}))
                independently_imported.close()
            finally:
                for close in closers:close()
