import importlib.util,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
spec=importlib.util.spec_from_file_location('gif_builder',Path(__file__).resolve().parents[1]/'tools/build_gif_stickers.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

class GifTests(unittest.TestCase):
    def test_transparent_two_frame_gif_and_png_preserve_white_interior(self):
        with tempfile.TemporaryDirectory() as folder:
            h=Path(folder);source=h/'original.png';im=Image.new('RGBA',(128,128))
            draw=ImageDraw.Draw(im);draw.rectangle((30,20,95,105),fill='white');draw.rectangle((35,25,90,100),fill='black');draw.rectangle((45,35,80,90),fill='white');im.putpixel((0,0),(255,255,255,2));im.save(source)
            gif=h/'sticker.gif';png=h/'sticker.png'
            info=builder.sticker_gif(source,gif,size=128,padding=6,outline=2)
            builder.sticker_png(source,png,size=128,padding=6,outline=2)
            self.assertEqual(max(info['size']),128);self.assertGreater(info['source_bbox'][0],0)
            with Image.open(gif) as g:
                self.assertEqual(g.n_frames,2);first=g.convert('RGBA');g.seek(1)
                self.assertEqual(first.tobytes(),g.convert('RGBA').tobytes())
                self.assertEqual(first.getpixel((0,0))[3],0)
                self.assertEqual(first.getpixel((first.width//2,first.height//2)),(255,255,255,255))
            with Image.open(png) as p:self.assertEqual(p.getpixel((p.width//2,p.height//2)),(255,255,255,255))
            with Image.open(source) as original:self.assertEqual(original.size,(128,128))
