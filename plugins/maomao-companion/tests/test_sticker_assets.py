import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maomao_companion.sticker_assets import display_variant

class VariantTests(unittest.TestCase):
    def test_platform_format_and_canonical_library_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            h=Path(folder);base=h/'stickers/512';base.mkdir(parents=True)
            source=base/'A2.png';source.write_bytes(b'original')
            png=base/'compact/A2.png';png.parent.mkdir();png.write_bytes(b'compact')
            gif=base/'gif/A2.gif';gif.parent.mkdir();gif.write_bytes(b'gif')
            sha=hashlib.sha256(source.read_bytes()).hexdigest()
            (h/'stickers/variants.json').write_text(json.dumps({'originals':{sha:{'png':'512/compact/A2.png','gif':'512/gif/A2.gif'}}}))
            self.assertEqual(display_variant(h,source,'qqbot'),str(gif.resolve()))
            self.assertEqual(display_variant(h,source,'feishu'),str(png.resolve()))
            self.assertEqual(display_variant(h,source,'telegram'),str(png.resolve()))
            copied=h/'state/maomao-private/groups/owner/copy.png';copied.parent.mkdir(parents=True);copied.write_bytes(source.read_bytes())
            self.assertEqual(display_variant(h,copied,'feishu'),str(png.resolve()))
            unknown=base/'unknown.png';unknown.write_bytes(b'unknown')
            self.assertEqual(display_variant(h,unknown,'qqbot'),str(unknown))
    def test_variant_cannot_escape_public_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            h=Path(folder);s=h/'stickers/512/a.png';s.parent.mkdir(parents=True);s.write_bytes(b'original')
            private=h/'private/secret.png';private.parent.mkdir();private.write_bytes(b'private')
            (h/'stickers/variants.json').write_text(json.dumps({'originals':{hashlib.sha256(s.read_bytes()).hexdigest():{'png':'../private/secret.png'}}}))
            self.assertEqual(display_variant(h,s,'feishu'),str(s))
            self.assertEqual(display_variant(h,private,'feishu'),str(private))
