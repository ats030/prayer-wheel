"""Build a self-contained, read-only comparison using the actual detail renderer."""
from pathlib import Path
import hashlib
import html
import json
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
with sqlite3.connect(f"file:{ROOT / 'data/timelines.sqlite3'}?mode=ro", uri=True) as db:
    raw = db.execute("SELECT result, generated_at FROM jobs WHERE query = 'ラーメン' AND result IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    if raw is None:
        raise SystemExit('保存済み「ラーメン」の結果が必要です。生成は実行しません。')
    result = json.loads(raw[0])
    # Include only displayed public data. Original quotes and review notes stay in SQLite.
    events = [{key: event[key] for key in ('date', 'year', 'title', 'description')} |
              {'source': {key: event['source'][key] for key in ('url', 'title')}}
              for event in result['events']]
fixture = {'kind': 'result', 'theme': result['theme'], 'period': result.get('period', ''),
           'elapsed_seconds': result.get('elapsed_seconds', 0), 'notice': '', 'events': events, 'review_notes': []}
payload = json.dumps(fixture, ensure_ascii=False).replace('<', '\\u003c')
css = (ROOT / 'tokens.css').read_text() + (ROOT / 'styles.css').read_text().replace("@import url('/tokens.css');", '')
proposal = (OUT / 'proposal.css').read_text()
app = (ROOT / 'app.js').read_text()
document = (ROOT / 'detail.html').read_text()
document = document.replace('<link rel="stylesheet" href="/styles.css">', '<style>' + css + '</style><style>' + proposal + '</style>')
document = document.replace('  <script src="/app.js" defer></script>\n', '')
document = document.replace('data-site="timeline-generator"', 'data-site="timeline-generator-design-preview"')
document = document.replace('href="/favicon.svg"', 'href="http://ubuntu-server-app:8532/favicon.svg"')
# Navigation can visit the live app. Every generation action uses the fixture below.
document = document.replace('href="/"', 'href="http://ubuntu-server-app:8532/"').replace('href="/timelines"', 'href="http://ubuntu-server-app:8532/timelines"')
toolbar = '''<aside class="preview-toolbar" aria-label="試作の比較"><strong>詳細画面の試作</strong>
<label>表示 <select id="preview-view"><option value="proposal">提案</option><option value="current">現行</option></select></label>
<label>件数 <select id="preview-count"><option value="saved">保存済み</option><option value="100">100件の検証用データ</option></select></label>
<label>状態 <select id="preview-state"><option value="complete">完了</option><option value="running">再生成中</option><option value="partial">時間上限</option><option value="failed">再生成失敗</option><option value="empty">0件</option></select></label>
<span>100件・状態・操作は検証用です</span></aside>
<style>.preview-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:4px 16px;padding:8px 12px;border-bottom:1px solid var(--color-rule);font-size:14px;background:var(--color-surface)}.preview-toolbar label{display:flex;align-items:center;gap:8px}.preview-toolbar select{font:inherit;min-height:44px;max-width:100%;color:var(--color-ink);background:var(--color-paper);border:1px solid var(--color-rule);border-radius:4px;padding:4px 8px}.preview-toolbar span{color:var(--color-muted)}</style>'''
document = document.replace('<body>', '<body data-view="proposal">' + toolbar)
mock = r'''
const params = new URLSearchParams(location.search);
const fixture = FIXTURE;
if (params.get('count') === '100') {
  fixture.events = Array.from({length:100}, (_, i) => ({...fixture.events[i % fixture.events.length], title:`${fixture.events[i % fixture.events.length].title}（検証用 ${i + 1}）`}));
}
const selectedState = params.get('state') || 'complete';
if (selectedState === 'empty') fixture.events = [];
if (selectedState === 'partial') fixture.stop_reason = 'time_limit';
let previewJob = {id:4, query:'ラーメン', state:['running','failed'].includes(selectedState)?selectedState:'complete',
  message:selectedState==='running'?'本文を読み、年代と出来事を整理しています。':'', stage:'generate',
  error:selectedState==='failed'?'生成に失敗しました。前回の結果を閲覧できます。':null,
  has_result:true, result:fixture, generated_at:GENERATED_AT};
window.fetch = async (path, options={}) => {
  if (!String(path).startsWith('/api/jobs/')) throw new Error('試作では外部APIを呼び出しません。');
  if (options.method === 'POST') {
    previewJob = {...previewJob, state:'running', stage:'generate', error:null, message:'試作内で再生成を再現しています。'};
    setTimeout(() => { previewJob = {...previewJob, state:'complete', message:'', generated_at:new Date().toISOString()}; }, 2500);
  }
  return new Response(JSON.stringify(previewJob), {headers:{'Content-Type':'application/json'}});
};
document.body.dataset.view = params.get('view') === 'current' ? 'current' : 'proposal';
for (const [id, key, fallback] of [['preview-view','view','proposal'],['preview-count','count','saved'],['preview-state','state','complete']]) {
  const control=document.getElementById(id); control.value=params.get(key)||fallback;
  control.addEventListener('change',()=>{params.set(key,control.value);location.search=params.toString();});
}
'''.replace('FIXTURE', payload).replace('GENERATED_AT', json.dumps(raw[1]))
document = document.replace('</body>', '<script>' + mock + '</script><script>' + app + '</script><script>document.getElementById("refine").addEventListener("click", e => {e.currentTarget.href="http://ubuntu-server-app:8532/?query="+encodeURIComponent(previewJob.query);});</script></body>')
(OUT / 'index.html').write_text(document)
(OUT / 'baseline.json').write_text(json.dumps({'source_sha256': {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['detail.html','styles.css','tokens.css','app.js']}, 'saved_events':len(events), 'fixture':'保存済みラーメンの表示項目のみ。100件モードは繰り返しの検証データ。'}, ensure_ascii=False, indent=2)+'\n')
print(f'Built {OUT / "index.html"}: {len(events)} saved events')
