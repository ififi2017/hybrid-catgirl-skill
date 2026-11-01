"""Compatibility exports for the shared, profile-scoped media library."""
from pathlib import Path
import sys

dependency=Path(__file__).resolve().parents[1]/"maomao-companion"
if dependency.is_dir() and str(dependency) not in sys.path:
    sys.path.insert(0,str(dependency))
from maomao_companion.library import (CATEGORIES, VISION_SCHEMA, MemeStore, image_input,
                                     group_key, local_media_allowed)
