"""Real QQ adapter pipeline with synthetic events and no network."""
import asyncio,importlib.util,json,os,sys,tempfile
from pathlib import Path
from types import MethodType,SimpleNamespace
from unittest.mock import patch
from gateway.config import PlatformConfig

async def main():
 with tempfile.TemporaryDirectory() as folder:
  os.environ['HERMES_HOME']=folder;root=Path(folder);stage=Path(__file__).resolve().parents[2]
  sys.path.insert(0,str(stage/'maomao-companion'))
  spec=importlib.util.spec_from_file_location('engagement_qq',stage/'maomao-qq/__init__.py',submodule_search_locations=[str(stage/'maomao-qq')])
  mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
  calls=[]
  class Model:
   def complete_structured(self,**kw):calls.append(kw);return SimpleNamespace(parsed={'reply':True})
  mod.MaomaoQQAdapter.plugin_context=SimpleNamespace(llm=Model())
  adapter=mod.MaomaoQQAdapter(PlatformConfig(enabled=True,extra={'app_id':'synthetic','client_secret':'synthetic'}))
  adapter._is_group_allowed=lambda *a:True
  adapter.settings=lambda:{'autonomous':{'enabled':True,'groups':['g'],'group_messages_to_model':True}}
  delivered=[]
  async def dispatch(self,d,msg,text,author,ts):delivered.append((msg,text))
  adapter._handle_group_message=MethodType(dispatch,adapter)
  async def fast(*args):pass
  at={'id':'m1','group_openid':'g','content':'<@bot> hi','author':{'member_openid':'u'},'mentions':[{'id':'bot','is_you':True}]}
  with patch('asyncio.sleep',fast):
   await adapter._on_message('GROUP_MESSAGE_CREATE',at)
   assert delivered==[('m1','hi')]
   adapter._engagement.sent('g','m1','hello')
   adapter._engagement.state('g')['last_reply']-=5
   follow={'id':'m2','group_openid':'g','content':'how so?','author':{'member_openid':'u'}}
   await adapter._on_message('GROUP_MESSAGE_CREATE',follow)
   await asyncio.gather(*list(adapter._engagement.tasks))
   assert delivered[-1]==('m2','how so?') and len(calls)==1
   disabled={'id':'m3','group_openid':'g','content':'hello','author':{'member_openid':'u'}}
   adapter.settings=lambda:{}
   await adapter._on_message('GROUP_MESSAGE_CREATE',disabled)
   assert len(delivered)==2 and len(calls)==1
  print(json.dumps({'mentioned_dispatched':True,'opt_in_followup_dispatched':True,'disabled_silent':True,'network_messages_sent':0}))
asyncio.run(main())
