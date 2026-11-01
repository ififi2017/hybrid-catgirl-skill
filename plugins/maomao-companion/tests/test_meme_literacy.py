import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maomao_companion.meme_literacy import ordinary_meme_hint


class ModelBoundaryTests(unittest.TestCase):
    def test_only_operator_bound_ordinary_model(self):
        cfg = {"context": {"allowed_models": ["ordinary"]}}
        self.assertTrue(ordinary_meme_hint("ordinary", cfg))
        self.assertFalse(ordinary_meme_hint("private", cfg))
        self.assertFalse(ordinary_meme_hint("", cfg))

    def test_missing_or_malformed_binding_fails_closed(self):
        for cfg in (None, {}, {"context": None}, {"context": {"allowed_models": "ordinary"}}):
            self.assertFalse(ordinary_meme_hint("ordinary", cfg))
