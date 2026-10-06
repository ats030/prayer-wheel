"""Protect the editorial preview and the boundary around paid questions."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from exam_trainer import kouko
from exam_trainer.app import ADMIN_COOKIE, app
from exam_trainer.config import settings


@pytest.fixture
def editorial(tmp_path, monkeypatch):
    for name in ('kouko.json', 'kouko-release.json'):
        shutil.copyfile(kouko.PRODUCT_DIR / name, tmp_path / name)
    monkeypatch.setattr(kouko, 'PRODUCT_DIR', tmp_path)
    monkeypatch.setattr(settings, 'admin_token', 'editorial-test-token')
    return TestClient(app)


def approve(url=''):
    (kouko.PRODUCT_DIR / 'kouko-release.json').write_text(json.dumps({
        'reviewed_sha256': kouko.content_digest(), 'reviewer': 'test reviewer',
        'reviewed_at': '2026-10-06', 'source_terms_checked': True, 'booth_url': url,
    }))


def test_unreviewed_content_is_private_even_answer_api(editorial):
    for path in ['/kouko', '/kouko/trial', '/kouko/sample']:
        response = editorial.get(path)
        assert response.status_code == 404
        assert response.headers['cache-control'] == 'no-store'
    assert editorial.post('/kouko/trial/answer', json={'question_id': 1, 'chosen': 0}).status_code == 404
    editorial.cookies.set(ADMIN_COOKIE, settings.admin_token)
    response = editorial.get('/kouko')
    assert response.status_code == 200
    assert response.headers['x-robots-tag'] == 'noindex'
    assert '校閲用プレビュー' in response.text
    assert 'data-purchase-link' not in response.text


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


def test_editing_content_revokes_review(editorial):
    approve()
    assert editorial.get('/kouko').status_code == 200
    path = kouko.PRODUCT_DIR / 'kouko.json'
    product = json.loads(path.read_text())
    product['questions'][0]['explanation'] += ' 校閲後の変更'
    path.write_text(json.dumps(product, ensure_ascii=False))
    assert editorial.get('/kouko').status_code == 404


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
    assert editorial.get('/kouko').status_code == 404
    editorial.cookies.set(ADMIN_COOKIE, settings.admin_token)
    assert editorial.post('/kouko/trial/answer', json={'question_id': 1, 'chosen': 4}).status_code == 422
    q = kouko.sample_questions(kouko.load_product())[0]
    result = editorial.post('/kouko/trial/answer', json={'question_id': q['id'], 'chosen': (q['answer'] + 1) % 4})
    assert result.json()['correct'] is False
    assert result.json()['answer'] == q['answer']
