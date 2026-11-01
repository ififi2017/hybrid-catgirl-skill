"""Fixed-endpoint media providers. Credentials stay in the host environment."""
import base64
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

TTS_MODEL = 'qwen-audio-3.1-tts-flash'
VOICE = 'qiaoxiaojiao_v3.1'
IMAGE_MODEL = 'gemini-nano-banana-2.1'

def request_json(url, body, headers, timeout=100):
    req=urllib.request.Request(url,json.dumps(body).encode(),{'Content-Type':'application/json',**headers})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            return json.loads(response.read(32*1024*1024))
    except Exception:
        # Never propagate authorization headers, signed URLs or response bodies into chats.
        raise RuntimeError('Media provider request failed; inspect private operator status') from None

def speech_voice(text):
    language=""
    try:
        from gateway.session_context import get_session_env
        platform=get_session_env("HERMES_SESSION_PLATFORM","")
        chat=get_session_env("HERMES_SESSION_CHAT_ID","")
        anchor=get_session_env("HERMES_SESSION_MESSAGE_ID","")
        if platform and chat:
            from .delivery import DeliveryLedger
            from .runtime import home
            language=DeliveryLedger(home()/"state/maomao-companion/delivery.sqlite3").voice_language(platform,chat,anchor or None)
    except (ImportError,OSError,ValueError):pass
    if not language:
        import re
        if re.search(r"[\u3040-\u30ff]",text):language="ja"
        elif re.search(r"[\uac00-\ud7af]",text):language="ko"
        else:
            latin=len(re.findall(r"[a-zA-Z]",text));han=len(re.findall(r"[\u4e00-\u9fff]",text))
            if latin and (not han or latin>max(4,han*2)):language="en"
    if language and language!="zh":
        voice=os.environ.get("MAOMAO_MULTILINGUAL_VOICE","")
        if voice not in {"longanfengyue_v3.1","longanhuan_v3.1","longanlingxin_v3.1","xunanchuan_v3.1"}:
            raise RuntimeError("Foreign-language speech voice is not configured")
        return voice
    return VOICE


def audio(text, output, fmt='mp3'):
    host=os.environ.get('MAOMAO_BAILIAN_HOST','')
    if host != 'trial.cn-beijing.maas.aliyuncs.com' and not __import__('re').fullmatch(r'[a-zA-Z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com',host):
        raise RuntimeError('Beijing Bailian workspace host required')
    key=os.environ.get('MAOMAO_BAILIAN_API_KEY','')
    if not key: raise RuntimeError('Bailian key not configured')
    if not text or len(text)>2000: raise ValueError('TTS text exceeds 2000 characters')
    result=request_json('https://'+host+'/api/v1/services/audio/tts/SpeechSynthesizer',
        {'model':TTS_MODEL,'input':{'text':text,'voice':speech_voice(text),'format':'wav','sample_rate':24000}},
        {'Authorization':'Bearer '+key})
    url=result.get('output',{}).get('audio',{}).get('url','')
    from urllib.parse import urlparse
    parsed=urlparse(url)
    if parsed.scheme=='http' and parsed.hostname and parsed.hostname.endswith('.aliyuncs.com'):
        url='https:'+url[5:];parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith(('.aliyuncs.com','.alibabacloud.com')):
        raise RuntimeError('Unexpected audio download location')
    try:
        with urllib.request.urlopen(url,timeout=45) as response:
            data=response.read(20_000_001)
    except Exception: raise RuntimeError('Audio download failed') from None
    if len(data)>20_000_000 or not data.startswith(b'RIFF'): raise RuntimeError('Invalid WAV output')
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    if fmt=='wav': output.write_bytes(data)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'audio.wav'; source.write_bytes(data)
            codec=['-c:a','libopus','-ac','1','-b:a','48k'] if fmt in {'opus','ogg'} else []
            result=subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),*codec,str(output)],capture_output=True,timeout=45)
            if result.returncode: raise RuntimeError('Audio encoding failed')
    output.chmod(0o600)
    return str(output)

def register(ctx):
    from agent.tts_provider import TTSProvider
    from agent.image_gen_provider import ImageGenProvider,save_b64_image,success_response
    class Bailian(TTSProvider):
        name='maomao-bailian'
        voice_compatible=True
        def list_voices(self):
            voices=[{'id':VOICE,'language':'zh','display':'乔小娇'}]
            foreign=os.environ.get('MAOMAO_MULTILINGUAL_VOICE')
            if foreign:voices.append({'id':foreign,'language':'multilingual','display':'多语种女声'})
            return voices
        def list_models(self): return [{'id':TTS_MODEL}]
        def synthesize(self,text,output_path,*,voice=None,model=None,format='mp3',**kwargs):
            return audio(text,output_path,format)
    class Google(ImageGenProvider):
        name='maomao-google'
        def list_models(self): return [{'id':IMAGE_MODEL}]
        def capabilities(self): return {'modalities':['text','image'],'max_reference_images':1}
        def generate(self,prompt,aspect_ratio='square',*,image_url=None,reference_image_urls=None,**kwargs):
            key=os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
            if not key: raise RuntimeError('Google API key not configured')
            content=[{'type':'text','text':prompt}]
            refs=([image_url] if image_url else [])+list(reference_image_urls or [])
            if refs:
                # Use the host's audited media loader (SSRF/path/size validation).
                from tools.image_source import resolve_image_source, ResolveContext
                import asyncio
                loaded=asyncio.run(resolve_image_source(refs[0],ResolveContext()))
                content.append({'type':'image','mime_type':loaded.mime,'data':base64.b64encode(loaded.data).decode()})
            result=request_json('https://generativelanguage.googleapis.com/v1beta/interactions',
                {'model':IMAGE_MODEL,'input':content,'response_format':{'type':'image','aspect_ratio':{'square':'1:1','portrait':'2:3','landscape':'3:2'}.get(aspect_ratio,'1:1'),'image_size':'1K'}}, {'x-goog-api-key':key},180)
            outputs=[item for step in result.get('steps',[]) if step.get('type')=='model_output' for item in step.get('content',[])]
            outputs+=result.get('outputs',[])
            for item in outputs:
                if item.get('type') in {'image','output_image'} and item.get('data'):
                    mime=item.get('mime_type','image/png')
                    if mime not in {'image/png','image/jpeg','image/webp'}: continue
                    path=save_b64_image(item['data'],prefix='maomao',extension=mime.split('/')[1])
                    return success_response(image=str(path),model=IMAGE_MODEL,prompt=prompt,aspect_ratio=aspect_ratio,provider=self.name,modality='image' if refs else 'text')
            raise RuntimeError('Google returned no image')
    class GeminiSpeech(TTSProvider):
        name='maomao-gemini'
        voice_compatible=True
        def list_voices(self):return [{'id':GEMINI_VOICE,'language':'multilingual','display':'Aoede'}]
        def list_models(self):return [{'id':GEMINI_TTS_MODEL}]
        def synthesize(self,text,output_path,*,speed=None,format='mp3',**kwargs):
            return gemini_audio(text,output_path,format,speed)
    ctx.register_tts_provider(GeminiSpeech())
    ctx.register_tts_provider(Bailian())
    ctx.register_image_gen_provider(Google())

GEMINI_TTS_MODEL='gemini-3.8-flash-tts'
GEMINI_VOICE='Aoede'

def gemini_audio(text,output,fmt='mp3',speed=None):
    key=os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not key:raise RuntimeError('Google API key not configured')
    if not text or len(text)>2000:raise ValueError('TTS text exceeds 2000 characters')
    style='Warm, playful, gentle and conversational. Natural pacing, with a relaxed smile. Speak the transcript in its original language.'
    if isinstance(speed,(int,float)) and .5<=speed<=2:style+=' Speaking rate: '+str(speed)+' times normal.'
    result=request_json('https://generativelanguage.googleapis.com/v1beta/interactions',{
        'model':GEMINI_TTS_MODEL,
        'input':[{'type':'user_input','content':[{'type':'text','text':text,'annotations':[{'type':'speech_metadata','style':style}]}]}],
        'response_format':{'type':'audio'},'generation_config':{'speech_config':[{'voice':GEMINI_VOICE}]}}, {'x-goog-api-key':key},90)
    outputs=[item for step in result.get('steps',[]) if step.get('type')=='model_output' for item in step.get('content',[])]
    outputs+=result.get('outputs',[])
    item=next((v for v in reversed(outputs) if v.get('type') in {'audio','output_audio'} and v.get('data')),None)
    if not item:raise RuntimeError('Gemini returned no audio')
    data=base64.b64decode(item['data'],validate=True)
    if len(data)>20_000_000 or not data.startswith(b'RIFF'):raise RuntimeError('Invalid Gemini WAV output')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    if fmt=='wav':output.write_bytes(data)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'speech.wav';source.write_bytes(data)
            codec=['-c:a','libopus','-ac','1','-b:a','48k'] if fmt in {'ogg','opus'} else []
            converted=subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),*codec,str(output)],capture_output=True,timeout=45)
            if converted.returncode:raise RuntimeError('Gemini audio encoding failed')
    output.chmod(0o600);return str(output)
