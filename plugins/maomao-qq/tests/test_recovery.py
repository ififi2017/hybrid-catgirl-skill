import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'maomao-companion'))
from maomao_companion.delivery import DeliveryLedger
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
recovery=load('recovery');identity=load('identity')


class RecoveryTests(unittest.TestCase):
    def test_exact_prefix_only(self):
        for marker in recovery.MARKERS:
            self.assertEqual(recovery.recovery_body(marker+'one<|bubble|>two'),('one<|bubble|>two',True))
        self.assertEqual(recovery.recovery_body('引用：'+recovery.MARKERS[0]),('引用：'+recovery.MARKERS[0],False))

    def test_split_plan_survives_restart_and_budget_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'delivery.db';ledger=DeliveryLedger(path)
            self.assertEqual(recovery.planned_maximum(ledger,'g','a','hello',3),3)
            ledger=DeliveryLedger(path)
            self.assertEqual(recovery.planned_maximum(ledger,'g','a','hello',1),3)
            self.assertEqual(recovery.planned_maximum(ledger,'other','a','hello',1),1)
            self.assertEqual(recovery.planned_maximum(ledger,'g','new','hello',2),2)
            self.assertIsNone(recovery.recovery_anchor(ledger,'g','hello'))
            self.assertEqual(recovery.recovery_anchor(ledger,'other','hello'),'a')
            self.assertIsNone(recovery.recovery_anchor(ledger,'unknown','hello'))

    def test_history_is_delivered_same_group_recent_only(self):
        with tempfile.TemporaryDirectory() as folder:
            with sqlite3.connect(Path(folder)/'state.db') as db:
                db.execute('CREATE TABLE delivery_obligations(platform,chat_id,state,content,created_at)')
                db.executemany('INSERT INTO delivery_obligations VALUES(?,?,?,?,?)',[
                    ('qqbot','g','delivered','我刚说的\nMEDIA:/local/image',990),
                    ('qqbot','other','delivered','其他群秘密',990),
                    ('qqbot','g','failed','没发成功',990),
                    ('telegram','g','delivered','其他平台',990),
                    ('qqbot','g','delivered','过期',1)])
            rows=identity.recent_group_replies(folder,'g',now=2000)
            self.assertEqual([r['text'] for r in rows],['我刚说的'])
            self.assertEqual(identity.recent_group_replies(folder,'dm:g',now=2000),[])
