"""Missing courses become usable without replacing exams or review history."""

import sqlite3
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from exam_trainer import bank, db, kouko, learning_catalog, products
from exam_trainer.app import app
from exam_trainer.config import settings


@pytest.fixture(autouse=True)
def isolated_bank(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    monkeypatch.setattr(settings, 'admin_token', 'catalog-test-token')
    db.reset_for_tests(tmp_path)
    yield
    db.close()


def table_rows(table):
    return [tuple(row) for row in db.connection().execute(f'SELECT * FROM {table} ORDER BY 1')]


def test_missing_course_preserves_all_existing_questions_and_history():
    for key, name in products.EXAMS.items():
        eid = bank.create_exam(name, key)
        bank.set_syllabus(eid, [{'path': '1', 'title': '既存の範囲'}])
        qid = bank.add_question(eid, '1', '既存の問題', ['正解', '誤答'], 0, status='verified')
        bank.answer(qid, 0)
    before = {table: table_rows(table) for table in ('exam', 'syllabus_node', 'question', 'review', 'card')}
    created = learning_catalog.import_missing()
    assert [item['key'] for item in created] == ['kouko']
    assert created[0]['questions'] == 50
    for table, rows in before.items():
        assert table_rows(table)[:len(rows)] == rows
    totals = {table: table_rows(table) for table in before}
    assert learning_catalog.import_missing() == []
    assert {table: table_rows(table) for table in before} == totals


def test_picker_matches_material_catalog_without_changing_selection_or_bank_order():
    for key, name in products.EXAMS.items():
        bank.create_exam(name, key)
    learning_catalog.import_missing()
    bank.create_exam('追加検定A', 'extra-a')
    bank.create_exam('追加検定B', 'extra-b')
    original = bank.list_exams()
    client = TestClient(app)
    catalog = client.get('/products').text
    positions = [catalog.index(f'<h2>{name}</h2>') for name in learning_catalog.DISPLAY_NAMES]
    assert positions == sorted(positions)
    assert learning_catalog.DISPLAY_NAMES[-1] == '考古検定 入門クラス'
    for path in ('/study', '/weakness'):
        html = client.get(f'{path}?exam_id=3').text
        picker = html.split('<select id="examSwitch"', 1)[1].split('</select>', 1)[0]
        names = [*learning_catalog.DISPLAY_NAMES, '追加検定A', '追加検定B']
        positions = [picker.index(name) for name in names]
        assert positions == sorted(positions)
        assert picker.count('<option') == 7
        assert '<option value="3" selected>歴史能力検定3級 日本史</option>' in picker
    assert 'data-exam-id="1"' in client.get('/study').text
    assert bank.list_exams() == original


def test_imported_course_can_be_selected_answered_and_aggregated():
    created = learning_catalog.import_missing()
    assert {item['name'] for item in created} == set(learning_catalog.EXAMS.values())
    assert [item['questions'] for item in created] == [50, 50, 31, 50, 29]
    eid = created[0]['exam_id']
    q = bank.next_question(eid)
    original = kouko.load_product()['questions'][0]
    assert q['stem'] == original['stem']
    assert q['source_refs'] == [kouko.load_product()['sources'][original['source']]['url']]
    record = q['source_details'][-1]
    assert record['editorial_question_id'] == original['id']
    assert record['editorial_content_sha256'] == kouko.content_digest()
    assert record['human_review'] == '未校閲'
    assert q['evidence'] == ''  # Source support summaries are not fabricated quotes.
    assert len(bank.list_syllabus(eid)) == 6
    client = TestClient(app)
    for path in ('/study', '/weakness'):
        html = client.get(f'{path}?exam_id={eid}').text
        picker = html.split('<select id="examSwitch"', 1)[1].split('</select>', 1)[0]
        for name in learning_catalog.EXAMS.values():
            assert name in picker
        assert picker.count('<option') == 5
        assert '未校閲の教材から取り込んだ練習問題' in html
        assert 'href="/kouko"' in html
    assert client.post(f'/api/questions/{q["id"]}/answer', json={'chosen': q['answer']}).json()['correct']
    stats = bank.node_stats(eid)
    assert stats[0]['answered'] == stats[0]['correct'] == 1
    assert bank.queue_counts(eid)['new'] == 49
    assert 'data-node="2"' in client.get(f'/study?exam_id={eid}&node=2').text
    assert bank.next_question(eid, '2')['node_path'] == '2'
    assert client.get('/api/exams').status_code == 401


def test_slug_collision_fails_without_creating_partial_catalog():
    bank.create_exam('別の検定', 'material-kouko')
    before = table_rows('exam')
    with pytest.raises(ValueError, match='別の試験'):
        learning_catalog.import_missing()
    assert table_rows('exam') == before
    assert not table_rows('question')


def test_import_failure_rolls_back_all_new_courses():
    conn = db.connection()
    conn.execute("CREATE TRIGGER refuse_import BEFORE INSERT ON exam "
                 "WHEN NEW.slug='material-nihonshu' BEGIN SELECT RAISE(ABORT, 'failed'); END")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match='failed'):
        learning_catalog.import_missing()
    assert not bank.list_exams()
    assert not table_rows('question')
    assert not table_rows('syllabus_node')


@pytest.mark.parametrize('key,module', [('kouko', kouko), ('g', products)])
def test_import_hash_identifies_loaded_questions_when_file_changes(tmp_path, monkeypatch, key, module):
    raw = (module.PRODUCT_DIR / f'{key}.json').read_bytes()
    path = tmp_path / f'{key}.json'
    path.write_bytes(raw)
    monkeypatch.setattr(module, 'PRODUCT_DIR', tmp_path)
    parse = module.parse_product

    def parse_and_replace(content):
        product = parse(content)
        changed = json.loads(content)
        changed['questions'][0]['stem'] = '後から更新された問題文'
        path.write_text(json.dumps(changed, ensure_ascii=False))
        return product

    monkeypatch.setattr(module, 'parse_product', parse_and_replace)
    existing = [{'name': name, 'slug': other} for other, name in learning_catalog.EXAMS.items() if other != key]
    [course] = learning_catalog.prepare_missing(existing)
    q = course['questions'][0]
    assert q['stem'] == json.loads(raw)['questions'][0]['stem']
    assert q['details'][-1]['editorial_content_sha256'] == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() != raw


def test_cli_preview_backup_and_repeat(tmp_path):
    eid = bank.create_exam('G検定', 'g')
    qid = bank.add_question(eid, '1', '既存問題', ['正解', '誤答'], 0, status='verified')
    bank.answer(qid, 0)
    before = table_rows('review')
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / 'scripts/import_learning_catalog.py')]
    env = {**os.environ, 'EXAM_TRAINER_DATA_DIR': str(tmp_path)}
    preview = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
    assert '確認のみ' in preview.stdout
    assert len(bank.list_exams()) == 1
    assert not list(tmp_path.glob('bank-before-catalog-*.sqlite'))
    subprocess.run(command + ['--apply'], env=env, capture_output=True, text=True, check=True)
    assert len(bank.list_exams()) == 5
    assert table_rows('review') == before
    backups = list(tmp_path.glob('bank-before-catalog-*.sqlite'))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute('SELECT COUNT(*) FROM exam').fetchone()[0] == 1
        assert backup.execute('SELECT * FROM review ORDER BY id').fetchall() == before
    repeat = subprocess.run(command + ['--apply'], env=env, capture_output=True, text=True, check=True)
    assert '変更はありません' in repeat.stdout
    assert list(tmp_path.glob('bank-before-catalog-*.sqlite')) == backups
