#!/usr/bin/env python3
"""Build an isolated public snapshot; never publish summary-work or private configuration."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date

from festival_calendar import render as render_festival_calendar
from festival_page import page_qids, render_page as render_festival_page, sitemap_entries

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('omatsuri', 'onsen', 'shiseki', 'tokusan')


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def build():
    target = ROOT / 'cloudflare/assets'
    target.parent.mkdir(parents=True, exist_ok=True)
    # The geopark popup counts are a snapshot of the point databases; refuse to publish a stale one.
    spec = importlib.util.spec_from_file_location('geo_layer', ROOT / 'scripts/build-geo-layer.py')
    geo_layer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geo_layer)
    if (ROOT / 'frontend/geo/geoparks.json').read_text() != geo_layer.render(ROOT / 'data'):
        sys.exit('frontend/geo/geoparks.json is stale: run scripts/build-geo-layer.py')
    with tempfile.TemporaryDirectory(prefix='midokoro-cloudflare-', dir=target.parent) as work:
        work = Path(work)
        assets = work / 'assets'
        shutil.copytree(ROOT / 'frontend', assets)
        data = work / 'data'
        for kind in KINDS:
            shutil.copytree(ROOT / 'data' / kind, data / kind)
        env = dict(os.environ, MIDOKORO_DATA_DIR=str(data), GOTOOLCHAIN='go1.25.0')
        for key in list(env):
            if 'A8MAT' in key or key.startswith('MIDOKORO_AFFILIATE') or key in ('TOKUSAN_AMAZON_URL', 'MIDOKORO_PUBLIC_ORIGIN'):
                del env[key]
        go = os.environ.get('MIDOKORO_GO', str(Path.home() / 'go/bin/go'))
        subprocess.run([go, 'run', '-buildvcs=false', './cmd/cloudflare-export', '-data', str(data), '-out', str(assets / '_data')], cwd=ROOT, env=env, check=True)
        specs = {}
        hashes = {}
        for kind in KINDS:
            normalized = assets / '_data' / kind / 'normalized-cache.json'
            cache = json.loads(normalized.read_text())
            for n in range(256):
                prefix = f'{n:02x}'
                dump(assets / '_data' / kind / 'cache' / f'{prefix}.json', {k: v for k, v in cache.items() if k.startswith(prefix)})
            normalized.unlink()
            source = ROOT / 'internal' / kind / 'services' / ('wikipedia_sections.go' if kind == 'tokusan' else 'wikipedia_content.go')
            text = source.read_text().split('var sectionSpecs = []sectionSpec{', 1)[1].split('\n}\n', 1)[0]
            specs[kind] = []
            for block in re.split(r'\n\s*\{\n', text)[1:]:
                key = re.search(r'key:\s*"([^"]+)"', block).group(1)
                label = re.search(r'label:\s*"([^"]+)"', block).group(1)
                candidates = re.search(r'candidates:\s*\[\]string\{([^}]+)\}', block)
                specs[kind].append({'key': key, 'label': label, 'candidates': re.findall(r'"([^"]+)"', candidates.group(1)) if candidates else []})
            for p in sorted((ROOT / 'data' / kind).iterdir()):
                if p.is_file():
                    hashes[f'{kind}/{p.name}'] = hashlib.sha256(p.read_bytes()).hexdigest()
        dump(assets / '_data/specs.json', specs)
        # Twelve months are built from the build date; /festivals/calendar.js picks this and next month in the browser.
        calendar = json.loads((assets / '_data/omatsuri/list.json').read_text())
        build_date = date.fromisoformat(os.environ.get('MIDOKORO_BUILD_DATE') or date.today().isoformat())
        (assets / 'festivals').mkdir(exist_ok=True)
        (assets / 'festivals/index.html').write_text(render_festival_calendar(calendar, build_date))
        # One page per festival with a dated, sourced occurrence; past dates still get a page.
        festival_qids = page_qids(calendar)
        by_qid = {f['qid']: f for f in calendar if f.get('qid')}
        for qid in festival_qids:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', qid):
                raise ValueError(f'Unexpected festival qid: {qid!r}')
            page = assets / 'festivals' / qid / 'index.html'
            page.parent.mkdir()
            page.write_text(render_festival_page(by_qid[qid], build_date))
        sitemap = assets / 'sitemap.xml'
        sitemap.write_text(sitemap.read_text().replace('</urlset>', sitemap_entries(festival_qids) + '</urlset>', 1))
        # Explicit canonical story routes; retain the source HTML and visit-log tag.
        (assets / '_redirects').write_text('/ /index.html 200\n/stories /stories/index.html 200\n' + ''.join(f'/stories/{slug} /stories/{slug}.html 200\n' for slug in ('arita-porcelain', 'kusatsu-yumomi', 'kawagoe-festival')) + '/changelog /changelog.html 200\n/festivals /festivals/index.html 200\n' + ''.join(f'/festivals/{qid} /festivals/{qid}/index.html 200\n' for qid in festival_qids))
        (assets / '_headers').write_text('/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n/_data/*\n  Cache-Control: public, max-age=0, must-revalidate\n/*.html\n  Cache-Control: no-store\n')
        files = list(p for p in assets.rglob('*') if p.is_file())
        if len(files) + 1 > 20000 or any(p.stat().st_size > 25 * 1024 * 1024 for p in files):
            raise ValueError('Workers Free static asset limits exceeded')
        if any(p.suffix in ('.db', '.sqlite') for p in files):
            raise ValueError('Database in public assets')
        dump(assets / '_data/manifest.json', {'schema': 1, 'files': len(files) + 1, 'source_sha256': hashes})
        # Install only a fully validated build. A failed build leaves the previous build intact.
        backup = target.with_name('assets.previous')
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            target.rename(backup)
        assets.rename(target)
        if backup.exists():
            shutil.rmtree(backup)
        print(f'Validated {len(files) + 1} assets; public data and existing summaries only.')


if __name__ == '__main__':
    build()
