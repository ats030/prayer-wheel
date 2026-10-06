"""All editorial products share the funnel, without changing learner state."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from exam_trainer import bank, db, products
from exam_trainer.app import app
from exam_trainer.config import settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def editorial(tmp_path, monkeypatch):
    for key in products.EXAMS:
        for suffix in ('.json', '-release.json'):
            shutil.copyfile(products.PRODUCT_DIR / (key + suffix), tmp_path / (key + suffix))
    monkeypatch.setattr(products, 'PRODUCT_DIR', tmp_path)
    monkeypatch.setattr(settings, 'admin_token', 'products-test-token')
    monkeypatch.setattr(settings, 'data_dir', tmp_path / 'bank')
    db.reset_for_tests(tmp_path / 'bank')
    yield TestClient(app)
    db.close()


def test_catalog_reachable_from_learning_and_all_products(editorial):
    assert 'href="/products"' in editorial.get('/').text
    page = editorial.get('/products')
    assert page.status_code == 200
    assert 'href="/kouko"' in page.text
    for key, name in products.EXAMS.items():
        assert name in page.text
        assert f'href="/products/{key}/materials"' in page.text


@pytest.mark.parametrize('key,count', [('g',50), ('nihonshu',31), ('rekishi-3',50), ('sekai-isan-3',29),
                                       ('jinja-3',20), ('shiro-3',20)])
def test_funnel_trial_files_and_history_isolation(editorial, key, count):
    product = products.load_product(key)
    assert len(product['questions']) == count
    base = f'/products/{key}'
    history_before = db.connection().total_changes
    for suffix in ('', '/trial', '/sample', '/materials'):
        response = editorial.get(base + suffix)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-robots-tag'] == 'noindex'
        assert '未校閲の教材' in response.text
        assert '販売準備中' in response.text or suffix == '/materials'
        assert f'href="{base}/materials"' in response.text
        assert 'data-purchase-link' not in response.text
    html = editorial.get(base + '/trial').text
    assert f'data-answer-url="{base}/trial/answer"' in html
    payload = json.loads(html.split('<script id="trial-data" type="application/json">')[1].split('</script>')[0])
    assert {q['id'] for q in payload} == set(product['free_ids'])
    assert all(set(q) == {'id','category','stem','choices'} for q in payload)
    for q in product['questions']:
        response = editorial.post(base + '/trial/answer', json={'question_id':q['id'],'chosen':q['answer']})
        if q['id'] in product['free_ids']:
            assert response.status_code == 200
            assert response.json()['correct'] is True
            assert response.json()['explanation'] == q['explanation']
        else:
            assert response.status_code == 404
    assert editorial.post(base + '/trial/answer', json={'question_id':1, 'chosen':4}).status_code == 422
    for asset in products.artifacts(key):
        assert asset['available']
        for download in (False,True):
            response = editorial.get(base + f'/files/{asset["id"]}' + ('?download=true' if download else ''))
            assert response.status_code == 200
            assert response.content == asset['path'].read_bytes()
            assert ('attachment' if download else 'inline') in response.headers['content-disposition']
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['x-robots-tag'] == 'noindex'
    assert db.connection().total_changes == history_before
    assert editorial.get('/api/exams').status_code == 401
    assert editorial.get('/admin/bank', follow_redirects=False).status_code == 303


def test_local_question_ids_select_only_the_requested_product(editorial):
    for key in products.EXAMS:
        q = products.load_product(key)['questions'][0]
        response = editorial.post(f'/products/{key}/trial/answer', json={'question_id':1,'chosen':q['answer']})
        assert response.json()['explanation'] == q['explanation']
        assert response.json()['source']['url'] == products.load_product(key)['sources'][q['source']]['url']


def test_file_and_product_ids_are_allowlisted(editorial):
    for path in ('/products/.env', '/products/kouko', '/products/g.json',
                 '/products/g/files/.env', '/products/g/files/g.json',
                 '/products/g/files/g-release.json', '/products/g/files/artifact-state.json', '/products/g/files/../g.json',
                 '/products/g/files/%2e%2e%2fg.json', '/products/g/files/release-guide.md'):
        assert editorial.get(path).status_code == 404
    assert editorial.post('/products/unknown/trial/answer', json={'question_id':1,'chosen':0}).status_code == 404


def test_missing_file_has_no_dead_link(editorial, tmp_path, monkeypatch):
    monkeypatch.setattr(products, 'ARTIFACT_DIR', tmp_path / 'missing')
    response = editorial.get('/products/g/materials')
    assert response.status_code == 200
    assert '準備中です' in response.text
    assert 'href="/products/g/files/' not in response.text
    assert editorial.get('/products/g/files/review-pdf').status_code == 404


def test_sale_readiness_is_separate_for_each_product_and_revision(editorial):
    release = products.PRODUCT_DIR / 'g-release.json'
    release.write_text(json.dumps({'reviewed_sha256':products.content_digest('g'),
                                   'reviewer':'test','reviewed_at':'2026-10-06',
                                   'source_terms_checked':True,'booth_url':'https://test.booth.pm/items/123'}))
    assert 'data-purchase-link' in editorial.get('/products/g').text
    assert 'data-purchase-link' not in editorial.get('/products/nihonshu').text
    path = products.PRODUCT_DIR / 'g.json'
    product = json.loads(path.read_text())
    product['questions'][0]['explanation'] += '（更新）'
    path.write_text(json.dumps(product, ensure_ascii=False))
    assert 'data-purchase-link' not in editorial.get('/products/g').text
    assert editorial.get('/products/g/files/review-pdf').status_code == 409
    assert '版の確認・更新待ち' in editorial.get('/products/g/materials').text
    assert 'href="/products/g/files/review-pdf"' not in editorial.get('/products/g/materials').text
    assert editorial.get('/products/g/materials').headers['x-robots-tag'] == 'noindex'


def test_changed_file_or_revoked_pdf_approval_is_not_served(editorial, tmp_path, monkeypatch):
    directory = tmp_path / 'artifacts' / 'g'
    shutil.copytree(products.ARTIFACT_DIR / 'g', directory)
    monkeypatch.setattr(products, 'ARTIFACT_DIR', directory.parent)
    path = directory / 'g-review.pdf'
    original = path.read_bytes()
    path.write_bytes(original + b'changed')
    assert editorial.get('/products/g/files/review-pdf').status_code == 409
    path.write_bytes(original)
    manifest_path = directory / 'artifact-state.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['review-pdf']['reviewed_pdf'] = True
    manifest_path.write_text(json.dumps(manifest))
    assert editorial.get('/products/g/files/review-pdf').status_code == 409


def test_rebuild_preserves_stale_human_copy_until_confirmation(tmp_path):
    from exam_trainer import kouko
    copy = tmp_path / 'sales-copy.md'
    copy.write_text('手修正の販売原稿')
    (tmp_path / 'release-guide.md').write_text('手作成の販売手順')
    kouko.record_artifacts(tmp_path, 'old-digest', 50, 'g', False)
    kouko.record_artifacts(tmp_path, 'new-digest', 50, 'g', False, preserve={'sales-copy','release-guide'})
    asset = next(a for a in kouko.artifact_list(tmp_path, 'new-digest', 50, 'g') if a['id'] == 'sales-copy')
    assert not asset['current']
    assert copy.read_text() == '手修正の販売原稿'
    assert not next(a for a in kouko.artifact_list(tmp_path, 'new-digest', 50, 'g') if a['id'] == 'release-guide')['current']
    kouko.record_artifacts(tmp_path, 'new-digest', 50, 'g', False)
    assert next(a for a in kouko.artifact_list(tmp_path, 'new-digest', 50, 'g') if a['id'] == 'sales-copy')['current']


@pytest.mark.parametrize('key', list(products.EXAMS))
def test_pdf_contains_all_questions_answers_and_unreviewed_notice(key):
    product = products.load_product(key)
    path = products.ARTIFACT_DIR / key / f'{key}-review.pdf'
    reader = PdfReader(path)
    text = ''.join(page.extract_text() for page in reader.pages)
    assert '未校閲' in text
    assert reader.metadata.subject == 'Content SHA-256: ' + products.content_digest(key)
    # Normalize whitespace added during line wrapping; every stem and answer
    # must survive pagination, including the last question.
    compact = ''.join(text.split())
    for q in product['questions']:
        assert ''.join(q['stem'].split()) in compact
        assert f'問{q["id"]}：{"ABCD"[q["answer"]]}' in compact
    sample = PdfReader(products.ARTIFACT_DIR / key / f'{key}-sample.pdf')
    sample_text = ''.join(''.join(p.extract_text().split()) for p in sample.pages)
    for q in product['questions']:
        stem = ''.join(q['stem'].split())
        if q['id'] in product['free_ids']:
            assert stem in sample_text
        else:
            assert stem not in sample_text


def test_snapshot_filters_status_format_and_sources_without_mutating_bank(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    import build_products
    db.reset_for_tests(tmp_path)
    try:
        eid = bank.create_exam('G検定')
        bank.set_syllabus(eid, [{'path':'1','title':'基礎'}])
        for i in range(12):
            bank.add_question(eid,'1',f'問題{i}', ['A','B','C','D'],0,explanation='解説',
                              source_refs=['https://example.test/one','https://example.test/two'],status='verified')
        for status in ('held','rejected','draft'):
            bank.add_question(eid,'1',status,['A','B','C','D'],0,explanation='解説',source_refs=['https://example.test'],status=status)
        bank.add_question(eid,'1','出典なし',['A','B','C','D'],0,explanation='解説',status='verified')
        bank.add_question(eid,'1','三択',['A','B','C'],0,explanation='解説',source_refs=['https://example.test'],status='verified')
        bank.add_question(eid,'1','危険なURL',['A','B','C','D'],0,explanation='解説',source_refs=['javascript:alert(1)'],status='verified')
        conn = db.connection()
        before = conn.total_changes
        product = build_products.snapshot(conn,'g','2026-10-06')
        assert conn.total_changes == before
        assert len(product['questions']) == 12
        assert [q['id'] for q in product['questions']] == list(range(1,13))
        assert len(product['free_ids']) == 10
        assert all(len(q['source_keys']) == 2 for q in product['questions'])
        assert all(q['provenance']['status_at_export'] == 'verified' for q in product['questions'])
    finally:
        db.close()


@pytest.mark.parametrize('key', ['jinja-3', 'shiro-3'])
def test_original_material_artifacts_do_not_claim_verified_bank_export(key, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    import build_products
    product = products.load_product(key)
    build_products.write_text_artifacts(key, product, tmp_path)
    for name in ('manuscript.md', 'claim-audit.md', 'release-guide.md'):
        text = (tmp_path / name).read_text()
        assert '独自' in text
        assert 'verified' not in text
        assert '未確認' in text or '未校閲' in text
    assert '既存バンクのコピー' not in (tmp_path / 'release-guide.md').read_text()
    assert all(q['provenance']['origin'] == 'editorial-original' and not q['provenance']['evidence']
               for q in product['questions'])


def test_default_bank_export_only_requires_existing_bank_backed_courses(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    import build_products
    output = tmp_path / 'products'
    output.mkdir()
    monkeypatch.setattr(products, 'PRODUCT_DIR', output)
    db.reset_for_tests(tmp_path / 'bank')
    try:
        for key in build_products.BANK_EXPORT_IDS:
            eid = bank.create_exam(products.EXAMS[key], key)
            for number in range(10):
                bank.add_question(eid, '1', f'問題{number}', ['A', 'B', 'C', 'D'], 0,
                                  explanation='解説', source_refs=['https://example.test/source'], status='verified')
        build_products.export_bank(settings.db_path)
        assert {p.name for p in output.glob('*.json')} == {
            name for key in build_products.BANK_EXPORT_IDS for name in (f'{key}.json', f'{key}-release.json')}
    finally:
        db.close()


@pytest.mark.parametrize('key', ['jinja-3', 'shiro-3'])
def test_bank_export_cannot_replace_an_original_even_with_explicit_flags(key, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    import build_products
    raw = (products.PRODUCT_DIR / f'{key}.json').read_bytes()
    monkeypatch.setattr(products, 'PRODUCT_DIR', tmp_path)
    original = tmp_path / f'{key}.json'
    original.write_bytes(raw)
    # Reject before opening a DB or writing any file, including a mixed selection.
    with pytest.raises(ValueError, match='独自作成教材'):
        build_products.export_bank(tmp_path / 'missing.sqlite', replace=True, keys=['g', key])
    with pytest.raises(ValueError, match='独自作成教材'):
        build_products.snapshot(None, key, '2026-10-06')
    assert original.read_bytes() == raw
    assert not (tmp_path / 'g.json').exists()
