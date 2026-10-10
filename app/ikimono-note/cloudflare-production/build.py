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
    (HERE/'src').mkdir(exist_ok=True)
    shutil.copyfile(PREVIEW/'src/worker.py',HERE/'src/worker.py')
    for name in ('edge.mjs','gemini-core.mjs','gemini-handler.mjs'):
        shutil.copyfile(PREVIEW/name,HERE/name)
    runpy.run_path(str(PREVIEW/('edge-build.py' if args.front else 'build.py')),
                   init_globals={'OUTPUT_DIR':HERE})
    for name in ('pyproject.toml','pylock.toml'):
        # The allowlist builder already copies the same pinned dependency files.
        if not (HERE/name).is_file():raise ValueError('Missing pinned dependency file')
    dependencies=(PREVIEW/'python_modules').resolve(strict=True)
    target=HERE/'python_modules'
    if target.exists() or target.is_symlink():
        if not target.is_symlink() or target.resolve()!=dependencies:
            raise ValueError('Unexpected production dependency path')
    else:target.symlink_to(dependencies,target_is_directory=True)


if __name__=='__main__':main()
