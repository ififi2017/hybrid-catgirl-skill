"""Read-only session status, with provider limits visible only to bound private users."""
import asyncio
import json
import os
import re
import time
import urllib.request
from decimal import Decimal,InvalidOperation
from pathlib import Path

from .sid import authorized,delivery_adapter,IdentityLookup

COMMAND=re.compile(r'^/status(?:@[A-Za-z0-9_]{3,32})?$',re.I)


def _matches(source,target):
    return (isinstance(target,dict) and source['platform']==target.get('platform')
            and source['chat_type']==target.get('chat_type')=='dm'
            and bool(source['chat_id']) and source['chat_id']==target.get('chat_id')
            and bool(target.get('user_id'))
            and target['user_id'] in {source['user_id'],source['user_id_alt']})


def private_owner(root,source):
    platform=getattr(getattr(source,'platform',None),'value',getattr(source,'platform',None))
    if getattr(source,'chat_type',None)!='dm':return False
    uid=str(getattr(source,'user_id','') or '')
    if platform=='qqbot':
        values=[os.environ.get('QQ_OWNER_OPENID',''),os.environ.get('QQ_OWNER_OPENIDS','')]
        try:
            for line in (Path(root)/'.env').read_text().splitlines():
                key,sep,value=line.partition('=')
                if sep and key.strip() in {'QQ_OWNER_OPENID','QQ_OWNER_OPENIDS'}:values.append(value.strip().strip("\"'"))
        except OSError:pass
        return bool(uid) and uid.upper() in {part.strip().upper() for value in values for part in value.split(',') if part.strip()}
    if platform not in {'feishu','telegram'}:return False
    try:
        cfg=json.loads((Path(root)/'state/maomao-companion/config.json').read_text())
        members=cfg.get('private_members') or [cfg.get('target')]
        data={'platform':platform,'chat_type':'dm','chat_id':getattr(source,'chat_id',None),
              'user_id':getattr(source,'user_id',None),'user_id_alt':getattr(source,'user_id_alt',None)}
        return isinstance(members,list) and any(_matches(data,item) for item in members)
    except (OSError,ValueError,TypeError,AttributeError):return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise PermissionError('redirect disabled')


def _amount(value):
    try:
        amount=Decimal(str(value))
        return f'${amount:.4f}' if amount.is_finite() else None
    except (InvalidOperation,ValueError,TypeError):return None


def provider_status(key=None,management_key=None,opener=None):
    """Never log keys or provider bodies; account balance requires an explicit management key."""
    if key is None:key=os.environ.get('OPENROUTER_API_KEY','')
    if management_key is None:management_key=os.environ.get('MAOMAO_OPENROUTER_MANAGEMENT_KEY','')
    opener=opener or urllib.request.build_opener(NoRedirect())
    lines=[]
    if key:
        try:
            request=urllib.request.Request('https://openrouter.ai/api/v1/key',headers={'Authorization':'Bearer '+key})
            with opener.open(request,timeout=5) as r:data=json.loads(r.read(65537))['data']
            if data.get('limit') is None:lines.append('OpenRouter 密钥限额：未设置（不代表账户余额）')
            else:
                remaining=_amount(data.get('limit_remaining'))
                lines.append('OpenRouter 密钥剩余额度：'+remaining if remaining else 'OpenRouter 密钥剩余额度：不可用')
        except Exception:lines.append('OpenRouter 密钥额度：暂不可用')
    else:lines.append('OpenRouter 密钥额度：未配置')
    balance_key=management_key or key
    if balance_key:
        try:
            request=urllib.request.Request('https://openrouter.ai/api/v1/credits',headers={'Authorization':'Bearer '+balance_key})
            with opener.open(request,timeout=5) as r:data=json.loads(r.read(65537))['data']
            remaining=_amount(Decimal(str(data['total_credits']))-Decimal(str(data['total_usage'])))
            lines.append('OpenRouter 账户余额：'+remaining if remaining else 'OpenRouter 账户余额：不可用')
        except Exception:lines.append('OpenRouter 账户余额：不可用（通常需要管理密钥）')
    else:lines.append('OpenRouter 账户余额：未配置管理密钥，无法读取')
    lines.append('其他提供商额度：以其控制台为准')
    return '\n'.join(lines)


class StatusLookup:
    def __init__(self,root):
        self.root=Path(root);self.rate=IdentityLookup(root);self.tasks=set();self.cached=None

    def hook(self,event=None,gateway=None,**kwargs):
        if event is None or gateway is None or getattr(event,'internal',False):return
        text=getattr(event,'text','')
        if not isinstance(text,str) or not COMMAND.fullmatch(text.strip()):return
        source=getattr(event,'source',None)
        platform=getattr(getattr(source,'platform',None),'value',getattr(source,'platform',None))
        if platform not in {'qqbot','feishu','telegram'} or getattr(source,'is_bot',False):return
        try:
            if not authorized(gateway,source):return
            adapter=delivery_adapter(gateway,source)
            if adapter is None or len(self.tasks)>=16 or not self.rate.allowed(source):return {'action':'skip','reason':'status unavailable or rate limited'}
            private=private_owner(self.root,source)
            async def deliver():
                try:
                    native=await gateway._handle_status_command(event)
                    if not isinstance(native,str) or not native.strip():native='当前会话状态暂不可用。'
                    if private:
                        now=time.monotonic()
                        if not self.cached or now-self.cached[0]>30:
                            details=await asyncio.to_thread(provider_status);self.cached=(now,details)
                        details=self.cached[1]
                    else:details='API 额度：仅已绑定主人的私聊可查询。'
                    await adapter.send(source.chat_id,native+'\n\n'+details,reply_to=getattr(event,'message_id',None))
                except Exception:
                    try:await adapter.send(source.chat_id,'当前状态暂时不可用，请稍后再试。',reply_to=getattr(event,'message_id',None))
                    except Exception:pass
            task=asyncio.get_running_loop().create_task(deliver());self.tasks.add(task);task.add_done_callback(self.tasks.discard)
            return {'action':'skip','reason':'status lookup handled'}
        except (AttributeError,RuntimeError,TypeError):return

    def close(self):
        for task in list(self.tasks):task.cancel()
