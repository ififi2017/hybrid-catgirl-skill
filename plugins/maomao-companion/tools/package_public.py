"""Produce the distributable from a positive allowlist, never the whole worktree."""
from pathlib import Path
import argparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "persona.md", "maomao_companion/persona.py", "tests/test_persona.py",
    "__init__.py", "plugin.yaml", "README.md", "ARCHITECTURE.md", ".gitignore",
    "maomao_companion/__init__.py", "maomao_companion/contact.py",
    "maomao_companion/runtime.py", "maomao_companion/legacy.py",
    "maomao_companion/dialogue.py", "maomao_companion/analysis.py", "maomao_companion/context.py",
    "maomao_companion/embeddings.py",
    "maomao_companion/life.py", "maomao_companion/life_tools.py", "tests/test_life.py",
    "maomao_companion/background.py", "maomao_companion/channels.py", "tests/test_background.py", "tests/test_channels.py",
    "maomao_companion/budget.py",
    "maomao_companion/library.py", "maomao_companion/sticker_assets.py", "tests/test_sticker_assets.py", "maomao_companion/auto_memes.py", "tests/test_auto_memes.py", "maomao_companion/providers.py",
    "maomao_companion/delivery.py", "tests/test_delivery.py", "tests/test_gemini_speech.py",
    "maomao_companion/meme_literacy.py", "tests/test_meme_literacy.py",
    "tests/test_contact.py", "tests/test_dialogue.py", "tests/test_embeddings.py", "tools/package_public.py",
)


def package(destination):
    destination = Path(destination)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path = ROOT/name
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
                raise ValueError("public source must be a real file inside the package")
            archive.write(path, "maomao-companion/"+name)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    package(parser.parse_args().destination)
