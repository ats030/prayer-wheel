"""Reuse the reviewed payload and fixed dependency tree for isolated deployment."""
import argparse
from pathlib import Path
import runpy
import shutil

HERE=Path(__file__).resolve().parent
PREVIEW=HERE.parent/'cloudflare-preview'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--front',action='store_true')
    args=parser.parse_args()
    runpy.run_path(str(PREVIEW/('edge-build.py' if args.front else 'build.py')))
    for name in ('pyproject.toml','pylock.toml'):
        shutil.copyfile(PREVIEW/name,HERE/name)
    dependencies=(PREVIEW/'python_modules').resolve(strict=True)
    target=HERE/'python_modules'
    if target.exists() or target.is_symlink():
        if not target.is_symlink() or target.resolve()!=dependencies:
            raise ValueError('Unexpected production dependency path')
    else:target.symlink_to(dependencies,target_is_directory=True)


if __name__=='__main__':main()
