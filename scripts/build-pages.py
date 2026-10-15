#!/usr/bin/env python3
"""Reuse the public asset package for Pages, with explicit 404 responses."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if not os.environ.get('VISIT_LOG_EXEMPT_REASON', '').strip():
    sys.exit('Set VISIT_LOG_EXEMPT_REASON for the documented public-network exception')
subprocess.run([sys.executable, str(ROOT / 'scripts/build-cloudflare.py')], check=True)
out = ROOT / 'dist-pages'
if out.is_symlink():
    sys.exit('Refusing a symlink as the Pages output directory')
if out.exists():
    shutil.rmtree(out)
shutil.copytree(ROOT / 'dist', out)
# Pages otherwise treats a site without a top-level 404.html as a SPA and may
# return index.html with HTTP 200 for private/missing paths. This entry uses the
# same recorded public-network visit-log exception as the existing package.
(out / '404.html').write_text('''<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ページが見つかりません · Webマニ車</title><link rel="stylesheet" href="/style.css"></head>
<body><main class="page"><h1>ページが見つかりません</h1><p><a href="/">読経の画面に戻る</a></p></main></body></html>
''', encoding='utf-8')
files = [p for p in out.rglob('*') if p.is_file()]
assert len(files) == len([p for p in (ROOT / 'dist').rglob('*') if p.is_file()]) + 1
assert (out / 'ads.txt').read_text() == 'google.com, pub-8787627445197940, DIRECT, f08c47fec0942fa0\n'
print(f'Pages package: {len(files)} files; explicit 404.html; existing meta, audio and ads.txt retained')
