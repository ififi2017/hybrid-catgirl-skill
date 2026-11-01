"""QQ-specific transparent GIF copies; retain original RGBA PNG artwork."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageFilter, ImageOps, GifImagePlugin


def compact_image(source,size=512,padding=8,outline=2):
    if size<32 or not 2<=padding<size//2 or not 0<=outline<=4:raise ValueError('invalid layout')
    with Image.open(source) as original:image=original.convert('RGBA')
    alpha=image.getchannel('A').point(lambda a:0 if a<8 else a)
    if outline:alpha=alpha.filter(ImageFilter.MinFilter(2*outline+1))
    bbox=alpha.point(lambda a:255 if a>=128 else 0).getbbox()
    if not bbox:raise ValueError('empty sticker silhouette')
    image.putalpha(alpha);image=image.crop(bbox)
    image=ImageOps.contain(image,(size-2*padding,size-2*padding),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',(image.width+2*padding,image.height+2*padding))
    canvas.paste(image,(padding,padding))
    return canvas,bbox


def sticker_png(source,destination,size=512,padding=8,outline=2):
    canvas,bbox=compact_image(source,size,padding,outline)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(destination,format='PNG',optimize=True)
    return {'size':list(canvas.size),'source_bbox':list(bbox),'bytes':destination.stat().st_size}


def sticker_gif(source,destination,size=512,padding=8,outline=2):
    source,destination=Path(source),Path(destination)
    canvas,bbox=compact_image(source,size,padding,outline)
    mask=canvas.getchannel('A').point(lambda a:255 if a>=128 else 0)
    rgb=canvas.convert('RGB');rgb.paste((255,255,255),mask=ImageOps.invert(mask))
    palette=rgb.quantize(colors=255,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
    indexed=Image.new('P',canvas.size)
    indexed.putpalette([0,0,0]+palette.getpalette()[:765])
    indexed.putdata([v+1 if a else 0 for v,a in zip(palette.getdata(),mask.getdata())])
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Preserve two full identical frames. Normal save() coalesces identical frames,
    # which lets image services treat the GIF as a static image again.
    with destination.open('wb') as stream:
        blocks,_=GifImagePlugin.getheader(indexed,info={'loop':0,'transparency':0,'background':0})
        for block in blocks:stream.write(block)
        for _ in range(2):
            for block in GifImagePlugin.getdata(indexed,duration=1000,disposal=2,transparency=0):stream.write(block)
        stream.write(b';')
    with Image.open(destination) as result:
        assert result.n_frames==2 and result.info.get('transparency')==0
        first=result.convert('RGBA');result.seek(1)
        assert first.tobytes()==result.convert('RGBA').tobytes()
        assert first.getpixel((0,0))[3]==0
    return {'source':str(source),'gif':str(destination),'size':list(canvas.size),'source_bbox':list(bbox),'padding':padding,'outline_trim':outline,'frames':2,'bytes':destination.stat().st_size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}


def main():
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('destination');p.add_argument('--size',type=int,default=512);p.add_argument('--padding',type=int,default=8);p.add_argument('--outline',type=int,default=2)
    a=p.parse_args();print(json.dumps(sticker_gif(a.source,a.destination,a.size,a.padding,a.outline),ensure_ascii=False))
if __name__=='__main__':main()
