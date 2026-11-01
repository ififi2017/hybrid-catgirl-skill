import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maomao_companion import persona


class PersonaTests(unittest.TestCase):
    def test_hook_supplies_same_public_persona_without_soul_on_all_channels(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        spec=importlib.util.spec_from_file_location('public_persona_probe',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        hooks=[];closers=[]
        ctx=SimpleNamespace(register_hook=lambda name,fn:hooks.append((name,fn)),register_tool=lambda **kw:None,on_unload=closers.append)
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'HERMES_HOME':folder}):
            try:
                module.register(ctx)
                first=[fn for name,fn in hooks if name=='pre_llm_call'][0]
                for platform in ('qqbot','feishu','telegram','cron'):
                    self.assertEqual(first(platform=platform,model='ordinary')['context'],persona.public_persona())
                self.assertEqual(first(platform='telegram',model='private')['context'],persona.public_persona())
            finally:
                for close in closers:close()

    def test_public_source_does_not_need_host_private_files(self):
        from unittest.mock import patch
        real=Path.read_text;opened=[]
        def read(path,*args,**kwargs):
            opened.append(path);return real(path,*args,**kwargs)
        with patch.object(Path,'read_text',read):
            text=persona.public_persona()
        self.assertEqual(opened,[persona.SOURCE])
        self.assertTrue(text.startswith('<!-- maomao-persona:'))

    def test_soul_is_pointer_with_source_digest(self):
        text=persona.soul_pointer()
        self.assertIn(persona.persona_digest(),text)
        self.assertNotIn('每句话必须',text)
        self.assertNotIn('qwen',text)

    def test_packaged_persona_matches_authoring_source_and_no_private_overlay(self):
        spec=importlib.util.spec_from_file_location('persona_pack',ROOT/'tools/package_public.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'public.zip';module.package(output)
            with zipfile.ZipFile(output) as z:
                self.assertEqual(z.read('maomao-companion/persona.md').decode(),persona.public_persona())
                self.assertFalse(any('private-mode' in x or 'overlay' in x or 'SOUL.md' in x for x in z.namelist()))
