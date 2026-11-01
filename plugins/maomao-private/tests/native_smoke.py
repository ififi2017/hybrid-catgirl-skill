"""Run with native Hermes --run-module runpy; uses only fake adapters and temporary state."""
from pathlib import Path
import importlib.util,json,os,sys,tempfile,asyncio,dataclasses
from unittest.mock import patch
from hermes_cli.plugins import PluginContext,PluginManager
from hermes_cli.plugins_manifest import PluginManifest
from gateway.platform_registry import platform_registry,PlatformEntry
from gateway.platforms.base import SendResult
from lark_oapi.api.im.v1 import ReplyMessageResponse,CreateMessageResponse
from types import SimpleNamespace
stage=Path(__file__).resolve().parents[2]
class Adapter:
 def __init__(self,config):self.sent=[];self.images=[]
 async def send(self,chat_id,content,reply_to=None,metadata=None):
  self.sent.append((chat_id,content,reply_to))
  mid=str(len(self.sent)) if content!='fail' else None
  raw=ReplyMessageResponse() if reply_to else CreateMessageResponse()
  raw.data=SimpleNamespace(message_id=mid)
  return SendResult(success=content!='fail',message_id=mid,raw_response=raw)
 async def send_image_file(self,chat_id,image_path,*args,**kwargs):
  self.images.append(image_path);return SendResult(success=True)
 async def handle_message(self,event):pass
 async def send_voice(self,*args,**kwargs):return SendResult(success=True)
 async def _send_raw_message(self,**kwargs):pass
async def run():
 with tempfile.TemporaryDirectory() as folder:
  os.environ['HERMES_HOME']=folder
  Path(folder,'plugins').mkdir();Path(folder,'plugins/maomao-companion').symlink_to(stage/'maomao-companion',target_is_directory=True)
  manager=PluginManager(scope_key=folder)
  for name in ('feishu','telegram'):
   platform_registry.register(PlatformEntry(name=name,label=name,adapter_factory=Adapter,check_fn=lambda:True,allowed_users_env='SYNTHETIC_ALLOW',trusted_inbound=False),scope=folder)
  spec=importlib.util.spec_from_file_location('private_probe',stage/'maomao-private/__init__.py',submodule_search_locations=[str(stage/'maomao-private')]);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
  mod.platform_definition=lambda name: {'name':name,'label':name,'adapter_factory':Adapter,'check_fn':lambda:True,'allowed_users_env':'SYNTHETIC_ALLOW'}
  ctx=PluginContext(PluginManifest(name='maomao-private',version='0.6.0',source='user',path=str(stage/'maomao-private')),manager);mod.register(ctx)
  for name in ('feishu','telegram'):
   entry=platform_registry.get(name);assert entry.allowed_users_env=='SYNTHETIC_ALLOW' and not entry.trusted_inbound
   adapter=entry.adapter_factory(None)
   async def fast(*args): pass
   with patch('asyncio.sleep',fast):
    result=await adapter.send('c','one<|bubble|>two',reply_to='m')
   assert result.success and result.raw_response['message_ids']==['1','2']
   assert all(v[2]=='m' for v in adapter.sent)
   with patch('asyncio.sleep',fast): result=await adapter.send('c','ok<|bubble|>fail',reply_to='m2')
   assert not result.success and result.raw_response['partial_overflow']
   assert not (await adapter.send_voice('c','path')).success
   created=await adapter.send('c','new message')
   assert created.success and created.raw_response['message_ids']==['5']
   public=Path(folder)/'stickers/512';public.mkdir(parents=True,exist_ok=True)
   original=public/'original.png';original.write_bytes(b'original-public')
   compact=public/'compact.png';compact.write_bytes(b'compact-public')
   import hashlib
   (public.parent/'variants.json').write_text(json.dumps({'originals':{hashlib.sha256(original.read_bytes()).hexdigest():{'png':'512/compact.png'}}}))
   assert (await adapter.send_image_file('c',str(original))).success
   assert adapter.images[-1]==str(compact.resolve())
  print(json.dumps({'platform_compact_asset_resolution':True,'real_feishu_sdk_response_objects':True,'native_factory':True,'auth_metadata_preserved':True,'bubbles':True,'partial_failure_protected':True,'voice_no_consent_blocked':True,'network_sends':0}))
asyncio.run(run())
