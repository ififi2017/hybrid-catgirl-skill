import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('qq_sender_test',Path(__file__).resolve().parents[1]/'sender.py')
sender=importlib.util.module_from_spec(spec);spec.loader.exec_module(sender)


class SenderTests(unittest.TestCase):
    def test_current_admission_beats_old_session_owner_and_spoofed_name(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'QQ_OWNER_OPENID':'owner'}):
            root=Path(d);(root/'sessions').mkdir()
            origin={'platform':'qqbot','chat_type':'group','chat_id':'group','user_id':'owner'}
            (root/'sessions/sessions.json').write_text(json.dumps({'key':{'session_id':'sid','origin':origin}}))
            identities=sender.SenderIdentity(root,clock=lambda:100)
            identities.admission(session_key='key',source={**origin,'user_id':'other','user_name':'主人'})
            context=identities.before(session_id='sid',platform='qqbot')['context']
            self.assertIn('不是已确认的主人',context);self.assertIn('群友',context)
            identities.admission(session_key='key',source=origin)
            self.assertIn('已由平台确认的主人',identities.before(session_id='sid',platform='qqbot')['context'])
            self.assertIsNone(identities.before(session_id='wrong',platform='qqbot'))
            self.assertIsNone(identities.before(session_id='sid',platform='telegram'))
