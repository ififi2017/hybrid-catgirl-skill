"""Exercise collection notices through the real QQ passive-send pipeline, no network."""
import asyncio,importlib.util,json,os,sys,tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from gateway.config import PlatformConfig
from gateway.platforms.base import SendResult
async def main():
 with tempfile.TemporaryDirectory() as folder:
  os.environ['HERMES_HOME']=folder
  root=Path(folder);stage=Path(__file__).resolve().parents[2]
  sys.path.insert(0,str(stage/'maomao-companion'))
  spec=importlib.util.spec_from_file_location('notice_qq',stage/'maomao-qq/__init__.py',submodule_search_locations=[str(stage/'maomao-qq')]);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
  adapter=mod.MaomaoQQAdapter(PlatformConfig(enabled=True,extra={'app_id':'synthetic','client_secret':'synthetic'}));adapter._chat_type_map['g']='group'
  source=root/'meme.png';Image.new('RGB',(64,64),'orange').save(source)
  store=mod.MemeStore(root/'state/maomao-qq','g')
  row=store.remember(source,{'description':'测试表情','text':'好耶','category':'开心','is_meme':True,'confidence':.99,'personal_or_sensitive':False,'steal_reason':'拿来庆祝正合适'},explicit=True)
  adapter._delivery.admit('qqbot','g','active-voice','请用语音回答',actor='owner')
  adapter._delivery.note_receipt('qqbot','g','picture')
  requests=[]
  async def posted(self,path,body):requests.append(dict(body));return SendResult(success=True,message_id=str(len(requests)))
  async def connected():return True
  async def fast(*args):pass
  adapter._ensure_connected=connected
  with patch.object(mod.MaomaoQQAdapter.__bases__[0],'_post_message',posted),patch('asyncio.sleep',fast):
   await adapter._ack_collection('g','picture',row)
   await adapter._ack_collection('g','picture',row)
   assert len(requests)==1 and '庆祝' in (requests[0].get('content') or requests[0].get('markdown',{}).get('content',''))
   assert adapter._delivery.current('qqbot','g')['anchor']=='active-voice'
   assert adapter._delivery.voice_allowed('qqbot','g','active-voice')
   assert (await adapter.send('g','one<|bubble|>two<|bubble|>three<|bubble|>four',reply_to='picture')).success
   assert len(requests)==4
   assert (await adapter._post_message('/v2/groups/g/messages',{'msg_id':'picture','msg_type':7,'media':{'file_info':'synthetic'}})).success
   assert not (await adapter._post_message('/v2/groups/g/messages',{'msg_id':'picture','content':'overflow'})).success
   assert [r['msg_seq'] for r in requests]==[1,2,3,4,5]
   from notice_qq.recovery import MARKERS
   replay=await adapter.send('g',MARKERS[1]+'one<|bubble|>two<|bubble|>three<|bubble|>four')
   assert replay.success and len(requests)==5, 'recovery duplicated fragments or used current voice anchor'
   unknown=await adapter.send('g',MARKERS[1]+'unbound old reply')
   assert not unknown.success and len(requests)==5
  print(json.dumps({'unmentioned_collection_notice':True,'semantic_reason_used':True,'no_duplicate_notice':True,'voice_admission_preserved':True,'passive_reply_cap':5,'network_messages_sent':0}))
asyncio.run(main())
