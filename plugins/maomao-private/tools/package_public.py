"""Only explicit public sources; never package a deployed profile."""
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
FILES=('__init__.py','plugin.yaml','README.md','.gitignore','tools/package_public.py','tests/native_smoke.py')
def package(destination):
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path=ROOT/name
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT): raise ValueError('public source required')
            archive.write(path,'maomao-private/'+name)
if __name__=='__main__':package(sys.argv[1])
