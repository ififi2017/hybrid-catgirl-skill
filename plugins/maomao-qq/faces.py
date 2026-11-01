"""Decode bounded QQ face labels as untrusted text, never invent image URLs."""
import base64
import binascii
import json
import re

FACE = re.compile(r'<faceType=(4|6),faceId="[^"]{0,120}",ext="([^"<>]{0,4096})">')

def face_text(content,has_image=False):
    def label(match):
        kind,encoded=match.groups()
        try:
            value=json.loads(base64.b64decode(encoded,validate=True))
            name=value.get('text','') if isinstance(value,dict) else ''
            if not isinstance(name,str): raise ValueError()
            name=''.join(c for c in name[:120] if c.isprintable()).strip().strip('[]')
        except (ValueError,UnicodeError,binascii.Error,RecursionError):
            name=''
        if name:
            return '[QQ表情名称：'+json.dumps(name,ensure_ascii=False)+(']' if has_image else '；平台未附原图]')
        return '[QQ收藏表情'+(']' if has_image else '；平台未附原图]') if kind=='6' else '[QQ表情；名称不可用]'
    return FACE.sub(label,str(content or ''))
