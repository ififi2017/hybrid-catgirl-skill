"""Resolve approved original public art to platform-specific display copies."""
import hashlib
import json
from pathlib import Path


def display_variant(home,source,platform):
    original=str(source)
    try:
        home=Path(home).resolve();path=Path(original).expanduser().resolve()
        allowed=(home/'stickers/512',home/'state/maomao-private/groups',home/'state/maomao-qq/groups')
        if not any(path.is_relative_to(p) for p in allowed) or not path.is_file() or path.stat().st_size>2_000_000:return original
        manifest=home/'stickers/variants.json'
        if not manifest.is_file():return original
        value=json.loads(manifest.read_text())
        entry=value.get('originals',{}).get(hashlib.sha256(path.read_bytes()).hexdigest(),{})
        relative=entry.get('gif' if platform=='qqbot' else 'png')
        if not isinstance(relative,str):return original
        target=(home/'stickers'/relative).resolve()
        if not target.is_relative_to(home/'stickers/512') or not target.is_file():return original
        if target.suffix.lower()!=('.gif' if platform=='qqbot' else '.png'):return original
        return str(target)
    except (OSError,ValueError,TypeError,AttributeError):return original
