"""Verify app-wide editorial access while keeping admin operations protected."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from exam_trainer import db, kouko
from exam_trainer.app import app
from exam_trainer.config import settings


@pytest.fixture
def editorial(tmp_path, monkeypatch):
    for name in ('kouko.json', 'kouko-release.json'):
        shutil.copyfile(kouko.PRODUCT_DIR / name, tmp_path / name)
    monkeypatch.setattr(kouko, 'PRODUCT_DIR', tmp_path)
    monkeypatch.setattr(settings, 'admin_token', 'editorial-test-token')
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    for item in kouko.artifacts():
        if item['available']:
            shutil.copyfile(item['path'], artifacts / item['path'].name)
    monkeypatch.setattr(kouko, 'ARTIFACT_DIR', artifacts)
    monkeypatch.setattr(settings, 'data_dir', tmp_path / 'bank')
    db.reset_for_tests(tmp_path / 'bank')
    yield TestClient(app)
    db.close()


def approve(url=''):
    (kouko.PRODUCT_DIR / 'kouko-release.json').write_text(json.dumps({
        'reviewed_sha256': kouko.content_digest(), 'reviewer': 'test reviewer',
        'reviewed_at': '2026-10-06', 'source_terms_checked': True, 'booth_url': url,
    }))


def test_every_app_visitor_can_find_unreviewed_materials(editorial):
    assert not editorial.cookies
    assert 'href="/kouko"' in editorial.get('/').text
    for path in ['/kouko', '/kouko/trial', '/kouko/sample', '/kouko/materials']:
        response = editorial.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-robots-tag'] == 'noindex'
        assert '未校閲の教材' in response.text
        assert 'href="/kouko/materials"' in response.text
    assert editorial.post('/kouko/trial/answer', json={'question_id': 1, 'chosen': 0}).status_code == 200
    response = editorial.get('/kouko')
    assert 'data-purchase-link' not in response.text
    assert editorial.get('/api/exams').status_code == 401
    assert editorial.post('/api/exams', json={'name':'test'}).status_code == 401
    assert editorial.get('/admin/bank', follow_redirects=False).status_code == 303


def test_public_trial_never_leaks_paid_questions_or_initial_answers(editorial):
    approve('https://example.booth.pm/items/123456')
    product = kouko.load_product()
    response = editorial.get('/kouko/trial')
    assert response.status_code == 200
    html = response.text
    payload = html.split('<script id="trial-data" type="application/json">')[1].split('</script>')[0]
    questions = json.loads(payload)
    assert len(questions) == 10
    assert {q['id'] for q in questions} == set(product['free_ids'])
    assert all('answer' not in q and 'explanation' not in q for q in questions)
    for q in product['questions']:
        result = editorial.post('/kouko/trial/answer', json={'question_id': q['id'], 'chosen': q['answer']})
        if q['id'] in product['free_ids']:
            assert result.status_code == 200
            assert result.json()['correct'] is True
        else:
            assert result.status_code == 404
            assert q['stem'] not in html
    assert 'data-purchase-link' in editorial.get('/kouko').text
    assert editorial.get('/static/products/kouko.json').status_code == 404
    assert editorial.get('/kouko/kouko-review.pdf').status_code == 404


def test_editing_content_revokes_sale_readiness_but_keeps_app_access(editorial):
    approve('https://example.booth.pm/items/123456')
    assert 'data-purchase-link' in editorial.get('/kouko').text
    path = kouko.PRODUCT_DIR / 'kouko.json'
    product = json.loads(path.read_text())
    product['questions'][0]['explanation'] += ' 校閲後の変更'
    path.write_text(json.dumps(product, ensure_ascii=False))
    response = editorial.get('/kouko')
    assert response.status_code == 200
    assert '未校閲の教材' in response.text
    assert 'data-purchase-link' not in response.text


@pytest.mark.parametrize('url', ['', 'javascript:alert(1)', 'https://booth.pm.evil.example/items/12',
                                 'https://example.booth.pm@evil.example/items/12',
                                 'http://booth.pm/items/12', 'https://booth.pm/'])
def test_invalid_or_missing_purchase_url_never_becomes_a_buy_link(editorial, url):
    approve(url)
    html = editorial.get('/kouko').text
    assert 'data-purchase-link' not in html
    assert '販売準備中' in html


def test_source_review_is_required_and_choices_are_bounded(editorial):
    approve()
    path = kouko.PRODUCT_DIR / 'kouko-release.json'
    release = json.loads(path.read_text())
    release['source_terms_checked'] = False
    path.write_text(json.dumps(release))
    assert editorial.get('/kouko').status_code == 200
    assert '未校閲の教材' in editorial.get('/kouko').text
    assert editorial.post('/kouko/trial/answer', json={'question_id': 1, 'chosen': 4}).status_code == 422
    q = kouko.sample_questions(kouko.load_product())[0]
    result = editorial.post('/kouko/trial/answer', json={'question_id': q['id'], 'chosen': (q['answer'] + 1) % 4})
    assert result.json()['correct'] is False
    assert result.json()['answer'] == q['answer']


def test_allowed_artifacts_open_and_download_without_admin_cookie(editorial):
    html = editorial.get('/kouko/materials').text
    for item in kouko.artifacts():
        assert item['available']
        path = '/kouko/files/' + item['id']
        assert f'href="{path}"' in html
        for suffix, disposition in [('', 'inline'), ('?download=true', 'attachment')]:
            response = editorial.get(path + suffix)
            assert response.status_code == 200
            assert response.content == item['path'].read_bytes()
            assert response.headers['content-disposition'].startswith(disposition)
            assert response.headers['content-type'].startswith(item['media_type'])
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['x-robots-tag'] == 'noindex'


@pytest.mark.parametrize('asset_id', ['kouko.json', 'kouko-release.json', '.env',
                                      '..%2F..%2F.env', 'unknown', 'kouko-review.html'])
def test_file_route_does_not_serve_unlisted_paths(editorial, asset_id):
    assert editorial.get('/kouko/files/' + asset_id).status_code == 404


def test_missing_artifact_has_no_broken_link(editorial):
    asset = next(item for item in kouko.artifacts() if item['id'] == 'review-pdf')
    asset['path'].unlink()
    response = editorial.get('/kouko/materials')
    assert response.status_code == 200
    assert 'href="/kouko/files/review-pdf"' not in response.text
    assert '準備中です' in response.text
    assert editorial.get('/kouko/files/review-pdf').status_code == 404


def test_artifacts_are_not_indexed_after_editorial_approval(editorial):
    approve()
    assert editorial.get('/kouko/materials').headers['x-robots-tag'] == 'noindex'
    assert editorial.get('/kouko/files/review-pdf').headers['x-robots-tag'] == 'noindex'
