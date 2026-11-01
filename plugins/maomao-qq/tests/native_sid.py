"""Real QQ intake with synthetic identities; no network or real messages."""
import asyncio,importlib.util,json,os,sys,tempfile
from pathlib import Path
from types import MethodType,SimpleNamespace
from gateway.config import PlatformConfig

async def main():
 with tempfile.TemporaryDirectory() as folder:
  os.environ['HERMES_HOME']=folder;root=Path(folder);stage=Path(__file__).resolve().parents[2]
  sys.path.insert(0,str(stage/'maomao-companion'))
  spec=importlib.util.spec_from_file_location('sid_qq',stage/'maomao-qq/__init__.py',submodule_search_locations=[str(stage/'maomao-qq')])
  mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
  adapter=mod.MaomaoQQAdapter(PlatformConfig(enabled=True,extra={'app_id':'synthetic','client_secret':'synthetic'}))
  adapter._is_group_allowed=lambda *args:False
  sent=[]
  async def send(self,chat,text,reply_to=None,metadata=None):sent.append((chat,text,reply_to));return SimpleNamespace(success=True)
  adapter.send=MethodType(send,adapter)
  config=root/'state/maomao-companion/config.json';config.parent.mkdir(parents=True,exist_ok=True)
  config.write_text(json.dumps({'identity':{'allow_unpaired_lookup':True}}))
  event={'id':'m1','group_openid':'group-a','content':'<@bot> /sid','author':{'member_openid':'user-a'},'mentions':[{'id':'bot','is_you':True}]}
  await adapter._on_message('GROUP_MESSAGE_CREATE',event)
  assert len(sent)==1 and sent[0][0]=='group-a' and sent[0][2]=='m1' and 'user-a' in sent[0][1]
  await adapter._on_message('GROUP_MESSAGE_CREATE',{**event,'id':'m2','content':'<@bot> /sid someone'})
  await adapter._on_message('GROUP_MESSAGE_CREATE',{**event,'id':'m3','content':'/sid','mentions':[]})
  assert len(sent)==1
  at={**event,'id':'m4','author':{'member_openid':'user-b'}}
  await adapter._on_message('GROUP_AT_MESSAGE_CREATE',at)
  assert len(sent)==2 and 'user-b' in sent[-1][1]
  adapter._is_dm_intake_allowed=lambda *args:False
  dm={'id':'m5','content':'/sid','author':{'user_openid':'dm-user'}}
  await adapter._on_message('C2C_MESSAGE_CREATE',dm)
  assert len(sent)==3 and sent[-1][0]=='dm-user'
  assert adapter._delivery.current('qqbot','group-a') is None
  print(json.dumps({'bootstrap_identity_only':True,'group_at':True,'direct_message':True,'no_acl_grant':True,'mention_required':True,'network_messages_sent':0}))
asyncio.run(main())
