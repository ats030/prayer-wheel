"""Homepage changes preserve deep study links and the learner file gates."""

import pytest
from fastapi.testclient import TestClient

from exam_trainer import bank, db, products
from exam_trainer.app import app
from exam_trainer.config import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    db.reset_for_tests(tmp_path)
    for i in (1,2):
        eid = bank.create_exam(f'学習用の試験{i}', f'test-{i}')
        bank.set_syllabus(eid, [{'path':'1','title':'基礎'}])
        bank.add_question(eid,'1',f'学習用の試験{i}の問題', ['正解','誤答'],0,status='verified')
    yield TestClient(app)
    db.close()


def test_home_is_catalog_and_navigation_has_one_learning_entry(client):
    for path in ('/', '/products'):
        response = client.get(path)
        assert response.status_code == 200
        assert response.text.count('class="artifact course-card"') == 5
        assert 'href="/study"' in response.text
        assert 'id="study"' not in response.text
        assert 'href="/kouko/trial"' in response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-robots-tag'] == 'noindex'


@pytest.mark.parametrize('path', ['/study?exam_id=2&node=1', '/?exam_id=2&node=1', '/?exam_id=2'])
def test_explicit_and_legacy_urls_preserve_selected_exam(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert 'id="study"' in response.text
    assert 'data-exam-id="2"' in response.text
    assert '学習用の試験2の問題' in response.text
    assert 'class="artifact course-card"' not in response.text


def test_node_only_legacy_link_and_weakness_link_open_learning(client):
    assert 'data-node="1"' in client.get('/?node=1').text
    html = client.get('/weakness?exam_id=2').text
    assert 'href="/study?exam_id=2&node=1"' in html
    assert '学習用の試験2の問題' in client.get('/study?exam_id=2&node=1').text


def test_learning_pdfs_precede_collapsed_production_resources(client):
    html = client.get('/products/g/materials').text
    assert html.index('学習用PDF') < html.index('class="production-materials"')
    assert 'class="production-materials" open' not in html
    assert html.count('class="card artifact pdf-card"') == 2
    assert html.count('class="artifact production-row"') == 5
    assert 'href="/products/g/files/review-pdf?download=true"' in html
    assert 'href="/products/g/files/sales-copy"' in html


def test_unavailable_pdf_has_no_direct_download_in_trial_result(client, monkeypatch, tmp_path):
    monkeypatch.setattr(products, 'ARTIFACT_DIR', tmp_path / 'missing')
    html = client.get('/products/g/trial').text
    assert 'data-result-pdf' not in html
    assert 'href="/products/g/materials"' in html
    assert 'PDFの準備状況を見る' in html


def test_admin_navigation_never_marks_learning_as_current(client, monkeypatch):
    from exam_trainer.app import ADMIN_COOKIE
    monkeypatch.setattr(settings, 'admin_token', 'nav-admin-test-token')
    client.cookies.set(ADMIN_COOKIE, settings.admin_token)
    for path in ('/admin/bank', '/admin/settings'):
        html = client.get(path).text
        assert f'href="{path}?exam_id=1" aria-current="page"' in html
        assert 'href="/study?exam_id=1" aria-current=' not in html
