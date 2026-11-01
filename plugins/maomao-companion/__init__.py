"""Hermes entry point. No private extension is imported by public code."""
import time
import json

from .maomao_companion.runtime import configured
from .maomao_companion.context import CompanionContext
from .maomao_companion.life_tools import SCHEMA, DESCRIPTION
from .maomao_companion.channels import ChannelContext
from .maomao_companion.runtime import home
from .maomao_companion.delivery import DeliveryLedger, HINT, session_source
from .maomao_companion.meme_literacy import ordinary_meme_hint
from .maomao_companion.persona import public_persona


def register(ctx):
    # Also covers gateways which skip SOUL/context files and scheduled agent turns.
    # This is public text only; private data is never opened by this hook.
    def persona(session_id="",platform="",**kwargs):
        identity=""
        if str(platform) in {"feishu","telegram"} and companion.resolve(session_id,str(platform)):
            identity="\n[宿主账户绑定] 当前为已绑定的主人私聊。专属称呼可用主人，尊重本对话明确选择的称呼；此绑定不授权读取其他作用域。"
        return {"context":public_persona()+identity}
    ctx.register_hook("pre_llm_call",persona)
    if hasattr(ctx,"register_tts_provider"):
        from .maomao_companion.providers import register as register_providers
        register_providers(ctx)
    companion = CompanionContext(ctx)
    def authorize_dm(session_key="",source=None,**kwargs):
        from .maomao_companion.authorization import admit
        admit(home(),companion.config(),session_key,source)
    ctx.register_hook("post_gateway_admission",authorize_dm)
    ledger_cache=[]
    def delivery():
        if not ledger_cache: ledger_cache.append(DeliveryLedger(home()/"state/maomao-companion/delivery.sqlite3"))
        return ledger_cache[0]
    if hasattr(ctx, "register_cli_command"):
        def browse(args):
            from .maomao_companion.background import BackgroundRunner
            print(json.dumps(BackgroundRunner().run(), ensure_ascii=False))
        ctx.register_cli_command(name="companion-browse", help="Run one bounded public reading cycle",
                                 setup_fn=lambda parser: None, handler_fn=browse)
    def incoming(source=None, message_id=None, text="", **kwargs):
        current = configured()
        if current is None or not isinstance(source, dict):
            return
        ledger, target, scope = current
        cfg=companion.config()
        members=companion.members(cfg) if cfg else [target]
        if not any(companion.matches(source,member) for member in members):
            return
        ledger.incoming(scope, message_id, time.time())
        if text.strip() in {"晚安", "睡了", "睡觉了", "先睡了"}:
            ledger.goodnight(scope)

    def delivery_admission(source=None,message_id=None,text="",**kwargs):
        if isinstance(source,dict) and message_id:
            delivery().admit(str(source.get("platform","")),str(source.get("chat_id","")),str(message_id),text,actor=source.get("user_id") or source.get("user_id_alt") or "")

    def chat_style(session_id="",platform="",model="",**kwargs):
        source=session_source(home(),session_id)
        if source and str(platform) in {"qqbot","feishu","telegram"}:
            voice_hint=""
            if delivery().voice_allowed(source["platform"],source["chat_id"]):
                voice_hint="本轮语音发送授权已成立，包括承接上一轮语音的换语言、再说一遍等请求。按语境调用text_to_speech，不要求用户重述固定关键词。"
            return {"context":HINT+voice_hint+ordinary_meme_hint(model,companion.config())}

    def voice_gate(tool_name="",session_id="",args=None,**kwargs):
        if tool_name!="text_to_speech": return None
        source=session_source(home(),session_id)
        if not source or not delivery().voice_allowed(source["platform"],source["chat_id"]):
            return {"action":"block","message":"本轮没有可用的语音发送授权，请用文字自然回应；不要要求用户照固定句式重复口令，也不要声称语音已经发出。"}
        if source["platform"]=="qqbot" and isinstance(args,dict) and args.get("output_path"):
            from pathlib import Path
            path=Path(args["output_path"]).expanduser().resolve()
            if not any(path.is_relative_to(home()/folder) for folder in ("cache/audio","audio_cache")):
                return {"action":"block","message":"QQ语音只能保存到当前渠道的默认音频缓存，请省略output_path。"}

    def image_reference_gate(tool_name="",args=None,session_id="",**kwargs):
        if tool_name!="image_generate" or not isinstance(args,dict): return
        source=session_source(home(),session_id)
        if not source or source["platform"]!="qqbot": return
        from .maomao_companion.library import local_media_allowed
        refs=([args["image_url"]] if args.get("image_url") else [])+list(args.get("reference_image_urls") or [])
        key=source["chat_id"] if source["chat_type"]=="group" else "dm:"+source["chat_id"]
        event=delivery().current("qqbot",source["chat_id"])
        for ref in refs:
            if not isinstance(ref,str) or (not local_media_allowed(home(),key,ref) and not delivery().artifact_allowed("qqbot",source["chat_id"],(event or {}).get("anchor"),ref)):
                return {"action":"block","message":"参考图不属于当前QQ对话；只能使用本轮收到的图、本对话图库或用户提供的公网图片。"}

    ctx.register_hook("pre_tool_call",image_reference_gate)
    def generated_artifact(tool_name="",result=None,session_id="",**kwargs):
        if tool_name not in {"text_to_speech","image_generate"}: return
        source=session_source(home(),session_id)
        if not source: return
        event=delivery().current(source["platform"],source["chat_id"])
        if not event: return
        try:
            value=json.loads(result) if isinstance(result,str) else result
            if not isinstance(value,dict) or value.get("success") is not True: return
            paths=[value.get("image"),value.get("file_path"),*(value.get("file_paths") or [])]
            for path in paths:
                if not isinstance(path,str): continue
                from pathlib import Path
                resolved=Path(path).resolve()
                # Only output from the successful trusted native tool result, inside media caches.
                if any(resolved.is_relative_to(home()/folder) for folder in ("audio_cache","cache/generated","cache/audio")):
                    delivery().grant_artifact(source["platform"],source["chat_id"],event["anchor"],resolved)
        except (ValueError,OSError,TypeError): return

    ctx.register_hook("post_tool_call",generated_artifact)
    # Runs after gateway admission; never trust role/owner labels in message text.
    ctx.register_hook("post_gateway_admission", incoming)
    ctx.register_hook("post_gateway_admission", delivery_admission)
    ctx.register_hook("post_gateway_admission", companion.incoming)
    ctx.register_hook("pre_llm_call", companion.before)
    ctx.register_hook("pre_llm_call", chat_style)
    ctx.register_hook("pre_tool_call", voice_gate)
    ctx.register_hook("post_llm_call", companion.after)
    ctx.register_hook("post_tool_call", companion.life.observe)
    try:
        targets = json.loads((home()/"state/maomao-companion/config.json").read_text()).get("channels", [])
    except (OSError, ValueError):
        targets = []
    for target in targets[:32]:
        if not isinstance(target, dict) or target.get("platform") not in {"qqbot", "telegram"} or target.get("chat_type") not in {"dm", "group"}:
            continue
        channel = ChannelContext(ctx, target)
        ctx.register_hook("post_gateway_admission", channel.incoming)
        ctx.register_hook("pre_llm_call", channel.before)
        ctx.register_hook("post_llm_call", channel.after)
        if hasattr(ctx, "on_unload"):
            ctx.on_unload(channel.close)
    if hasattr(ctx, "register_tool"):
        ctx.register_tool(name="companion_life", toolset="maomao_companion", schema=SCHEMA,
                          handler=companion.life.handler, check_fn=companion.life.enabled,
                          description=DESCRIPTION, emoji="🐾")
    if hasattr(ctx, "on_unload"):
        ctx.on_unload(companion.close)
