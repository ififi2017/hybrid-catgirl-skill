"""Identity lookup from trusted gateway metadata; never grants authorization."""
import asyncio
import json
import re
import time
from pathlib import Path

COMMAND=re.compile(r'^/sid(?:@[A-Za-z0-9_]{3,32})?$',re.I)
PLATFORMS={'qqbot','feishu','telegram'}


def is_sid(text):
    return isinstance(text,str) and bool(COMMAND.fullmatch(text.strip()))


def strip_qq_mention(text,mentions,group_at=False):
    mentions=mentions if isinstance(mentions,list) else []
    bots={str(m.get('member_openid') or m.get('id') or '') for m in mentions if isinstance(m,dict) and m.get('is_you')}
    value=re.sub(r'<@!?([A-Za-z0-9]+)>',lambda m:'' if m.group(1) in bots else m.group(0),str(text or ''))
    if group_at:
        value=re.sub(r'^\s*<@!?[A-Za-z0-9]+>\s*','',value)
        value=re.sub(r'^\s*@\S+\s*','',value)
    return value.strip()


def settings(root):
    try:
        value=json.loads((Path(root)/'state/maomao-companion/config.json').read_text())
        item=value.get('identity',{})
        return item if isinstance(item,dict) else {}
    except (OSError,ValueError,TypeError,AttributeError):return {}


def response(source):
    if getattr(source,'is_bot',False):return None
    platform=getattr(getattr(source,'platform',None),'value',getattr(source,'platform',None))
    kind=getattr(source,'chat_type',None)
    uid=getattr(source,'user_id',None)
    chat=getattr(source,'chat_id',None)
    if platform not in PLATFORMS or kind not in {'group','dm'} or not isinstance(uid,str) or not uid or not isinstance(chat,str) or not chat:return None
    if not all(re.fullmatch(r'[A-Za-z0-9_:@.-]{1,200}',value) for value in (uid,chat)):return None
    # Only platform-created metadata is used; never interpret the message text as an ID.
    lines=['平台：'+platform,'会话类型：'+('群聊' if kind=='group' else '私聊'),'你的认证 ID：'+uid,'当前会话 ID：'+chat]
    alt=getattr(source,'user_id_alt',None)
    if isinstance(alt,str) and alt!=uid and re.fullmatch(r'[A-Za-z0-9_:@.-]{1,200}',alt):lines.append('平台备用用户 ID：'+alt)
    if platform=='qqbot':lines.append('QQ 群成员 ID 与私聊用户 ID 可能不同，请在对应场景分别查询。')
    if kind=='group':lines.append('这条回复对群成员可见；请勿把 ID 当密码或验证码。')
    lines.append('此命令只查询身份，主人或白名单由管理员配置。')
    return '\n'.join(lines)


class IdentityLookup:
    def __init__(self,root,clock=time.monotonic):self.root=Path(root);self.clock=clock;self.seen={};self.tasks=set()

    def allowed(self,source):
        platform=getattr(getattr(source,'platform',None),'value',getattr(source,'platform',None))
        key=(platform,str(getattr(source,'chat_id','')),str(getattr(source,'user_id','')))
        now=self.clock();self.seen={k:t for k,t in self.seen.items() if 0<=now-t<60}
        if key in self.seen and now-self.seen[key]<10:return False
        if sum(k[:2]==key[:2] for k in self.seen)>=30:return False
        self.seen[key]=now
        while len(self.seen)>512:self.seen.pop(next(iter(self.seen)))
        return True

    def hook(self,event=None,gateway=None,**kwargs):
        if event is None or gateway is None or getattr(event,'internal',False) or not is_sid(getattr(event,'text',None)):return
        cfg=settings(self.root)
        if cfg.get('sid_enabled',True) is not True:return
        source=getattr(event,'source',None);answer=response(source)
        if not answer:return
        try:
            admitted=bool(gateway._is_user_authorized(source))
            if not admitted and cfg.get('allow_unpaired_lookup') is not True:return
            adapter=gateway._adapter_for_source(source)
            if adapter is None or not self.allowed(source):return {'action':'skip','reason':'identity lookup unavailable or rate limited'}
            anchor=getattr(event,'message_id',None)
            async def deliver():
                try:await adapter.send(source.chat_id,answer,reply_to=anchor)
                except Exception:pass
            task=asyncio.get_running_loop().create_task(deliver());self.tasks.add(task);task.add_done_callback(self.tasks.discard)
            return {'action':'skip','reason':'identity lookup handled'}
        except (AttributeError,RuntimeError,TypeError):return

    def close(self):
        for task in list(self.tasks):task.cancel()
