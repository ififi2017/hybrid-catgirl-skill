"""Positive allowlist: never package deployment settings, images or credentials."""
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ("__init__.py", "adapter.py", "identity.py", "memes.py", "faces.py", "plugin.yaml", "README.md", "LICENSE.hermes", ".gitignore",
         "recovery.py", "sender.py", "engagement.py", "tests/test_recovery.py", "tests/test_sender.py", "tests/test_engagement.py", "tests/native_engagement.py", "tests/native_sid.py",
         "transport/__init__.py", "transport/adapter.py", "transport/constants.py", "transport/utils.py",
         "transport/chunked_upload.py", "transport/keyboards.py", "tests/test_memes.py", "tests/test_gif_stickers.py", "tests/native_collection.py", "tools/build_gif_stickers.py", "tools/package_public.py")


def package(destination):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path = ROOT/name
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                raise ValueError("only real allowlisted public files may be packaged")
            archive.write(path, "maomao-qq/"+name)


if __name__ == "__main__":
    package(sys.argv[1])
