"""Tests for exam-trainer. No Ollama and no network required.

Each test gets a throwaway database, so the developer's real bank in ~/data is
never touched by a test run.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from exam_trainer import bank, checks, db, srs


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path)
    yield
    db.close()


@pytest.fixture
def client():
    from exam_trainer.app import app

    return TestClient(app)


def _exam_with_question(status: str = "verified") -> tuple[int, int]:
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "人工知能とは"}])
    question_id = bank.add_question(
        exam_id, "1", "AI効果とは何を指すか。",
        ["原理が分かると知能と見なされなくなる現象", "AIが人間を超える時点", "学習が発散する現象"],
        0, explanation="解説", status=status,
    )
    return exam_id, question_id


# --- schema / storage ----------------------------------------------------

def test_schema_is_created_on_first_use():
    exam_id = bank.create_exam("G検定")
    assert bank.get_exam(exam_id)["name"] == "G検定"
    assert bank.list_exams()[0]["slug"] == "g"


def test_deleting_an_exam_takes_its_questions_and_history():
    exam_id, question_id = _exam_with_question()
    bank.answer(question_id, 0)
    bank.delete_exam(exam_id)
    assert bank.get_question(question_id) is None
    rows = db.connection().execute("SELECT COUNT(*) FROM review").fetchone()[0]
    assert rows == 0, "外部キーの ON DELETE CASCADE が効いていない"


# --- syllabus ------------------------------------------------------------

def test_outline_parsing_tolerates_indentation_and_keywords():
    nodes = bank.parse_syllabus_outline(
        "1 人工知能とは\n"
        "  1.1 定義 | AI効果, チューリングテスト\n"
        "\n"
        "# コメント行は無視\n"
        "2. 機械学習\n"
    )
    assert [node["path"] for node in nodes] == ["1", "1.1", "2"]
    assert nodes[1]["keywords"] == "AI効果, チューリングテスト"
    assert nodes[2]["title"] == "機械学習"


def test_reimporting_a_syllabus_keeps_existing_questions():
    exam_id, question_id = _exam_with_question()
    bank.set_syllabus(exam_id, [{"path": "1", "title": "改題"}, {"path": "2", "title": "追加"}])
    assert bank.get_question(question_id) is not None, "シラバス再登録で問題が消えてはいけない"


# --- the gate ------------------------------------------------------------

def test_only_verified_questions_are_served():
    exam_id, question_id = _exam_with_question(status="draft")
    assert bank.next_question(exam_id) is None
    bank.set_status(question_id, "verified")
    assert bank.next_question(exam_id)["id"] == question_id


def test_held_questions_stay_out_of_the_queue():
    exam_id, question_id = _exam_with_question()
    bank.set_status(question_id, "held", "検証パスと答えが割れた")
    assert bank.next_question(exam_id) is None
    assert bank.counts_by_status(exam_id)["held"] == 1


def test_machine_checks_reject_malformed_questions():
    assert checks.check("十分に長い問題文です。", ["A", "B"], 0), "選択肢が少ない"
    assert checks.check("十分に長い問題文です。", ["同じ", "同じ", "別"], 0), "重複を見逃した"
    assert checks.check("短い", ["ア", "イ", "ウ"], 0), "短すぎる問題文"
    assert checks.check("十分に長い問題文です。", ["ア", "イ", "上記すべて"], 0), "上記すべて型"
    assert checks.check("十分に長い問題文です。", ["ア", "イ", "ウ"], 5), "範囲外の正解"
    assert not checks.check(
        "AI効果とは何を指すか。", ["原理が分かると知能と見なされない", "人間を超える時点", "学習の発散"], 0
    )


def test_machine_checks_flag_a_conspicuously_long_answer():
    problems = checks.check(
        "次のうち正しいものはどれか。",
        [
            "原理が解明されると知能とは見なされなくなる現象を指し、期待と実装の差が縮むたびに繰り返される",
            "人間の知能を計算量で上回った時点のこと",
            "学習が発散して収束しない状態のこと",
        ],
        0,
    )
    assert any("長く" in problem for problem in problems)


def test_length_check_ignores_short_choice_sets():
    """短い選択肢では比が暴れるので判定しない（1語増えただけで2倍になる）。"""
    assert not checks.check("次のうち正しいものはどれか。", ["教師あり学習", "強化学習", "回帰"], 0)


# --- SM-2 ----------------------------------------------------------------

def test_first_correct_answers_step_one_then_six_days():
    state = srs.CardState()
    state, _ = srs.schedule(state, 5)
    assert state.interval == 1
    state, _ = srs.schedule(state, 5)
    assert state.interval == 6


def test_a_wrong_answer_restarts_the_interval_and_lowers_ease():
    state = srs.CardState(interval=30, ease=2.5, reps=4)
    state, due = srs.schedule(state, 1, now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert state.interval == 1
    assert state.reps == 0
    assert state.lapses == 1
    assert state.ease < 2.5
    assert due.date() == dt.date(2026, 1, 2), "失敗しても同日に出し直さない"


def test_ease_never_falls_below_the_floor():
    state = srs.CardState(ease=1.3)
    for _ in range(5):
        state, _ = srs.schedule(state, 1)
    assert state.ease == pytest.approx(srs.MIN_EASE)


def test_grade_reflects_hesitation_and_speed():
    assert srs.grade_for(True, 1_000) == 5
    assert srs.grade_for(True, 60_000) == 4
    assert srs.grade_for(True, 1_000, unsure=True) == 3
    assert srs.grade_for(False, 1_000) == 2
    assert srs.grade_for(False, 1_000, unsure=True) == 1


# --- the review loop -----------------------------------------------------

def test_answering_records_history_and_schedules_the_card():
    exam_id, question_id = _exam_with_question()
    result = bank.answer(question_id, 0, elapsed_ms=1500)
    assert result["correct"] is True
    assert result["interval"] == 1
    row = db.connection().execute("SELECT COUNT(*) FROM review WHERE question_id = ?", (question_id,)).fetchone()[0]
    assert row == 1


def test_a_blank_answer_is_still_recorded():
    exam_id, question_id = _exam_with_question()
    result = bank.answer(question_id, None)
    assert result["correct"] is False
    row = db.connection().execute("SELECT chosen, grade FROM review").fetchone()
    assert row["chosen"] is None
    assert row["grade"] == 2


def test_answered_cards_leave_the_queue_until_they_are_due():
    exam_id, question_id = _exam_with_question()
    assert bank.queue_counts(exam_id) == {"due": 0, "new": 1}
    bank.answer(question_id, 0)
    assert bank.queue_counts(exam_id) == {"due": 0, "new": 0}
    assert bank.next_question(exam_id) is None


def test_due_cards_come_before_new_ones():
    exam_id, first = _exam_with_question()
    second = bank.add_question(
        exam_id, "1", "チューリングテストの説明として正しいものはどれか。",
        ["人間と区別できるかを問う", "計算量を測る", "勾配を測る"], 0, status="verified",
    )
    bank.answer(first, 0)
    # Force the first card to be overdue.
    db.connection().execute(
        "UPDATE card SET due_at = ? WHERE question_id = ?",
        ("2000-01-01T00:00:00+00:00", first),
    )
    db.connection().commit()
    assert bank.next_question(exam_id)["id"] == first, "期限切れの復習が新規より先に出る"
    assert bank.queue_counts(exam_id) == {"due": 1, "new": 1}


# --- weakness ------------------------------------------------------------

def test_node_stats_roll_descendants_into_the_parent():
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [
        {"path": "2", "title": "機械学習"},
        {"path": "2.1", "title": "教師あり学習"},
    ])
    child = bank.add_question(
        exam_id, "2.1", "回帰と分類の違いとして正しいものはどれか。",
        ["出力が連続値か離散値か", "学習率の差", "層の数の差"], 0, status="verified",
    )
    bank.answer(child, 0)
    stats = {item["path"]: item for item in bank.node_stats(exam_id)}
    assert stats["2"]["answered"] == 1, "子の解答が親に集計されていない"
    assert stats["2"]["accuracy"] == 1.0
    assert stats["2.1"]["answered"] == 1


def test_only_the_latest_answer_counts_toward_accuracy():
    exam_id, question_id = _exam_with_question()
    bank.answer(question_id, 1)   # wrong
    bank.answer(question_id, 0)   # right
    stats = {item["path"]: item for item in bank.node_stats(exam_id)}
    assert stats["1"]["answered"] == 1
    assert stats["1"]["accuracy"] == 1.0, "直近の解答だけで採点する"


# --- HTTP ----------------------------------------------------------------

def test_pages_render_without_an_exam(client):
    for path in ("/", "/weakness", "/bank", "/settings"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "試験の設定" in response.text


def test_health_reports_the_database(client):
    assert client.get("/health").json() == {"ok": True}


def test_next_endpoint_never_reveals_the_answer(client):
    exam_id, question_id = _exam_with_question()
    payload = client.get(f"/api/exams/{exam_id}/next").json()
    assert payload["question"]["id"] == question_id
    for leaked in ("answer", "explanation", "evidence"):
        assert leaked not in payload["question"], f"{leaked} が採点前に漏れている"


def test_adding_a_malformed_question_is_refused(client):
    exam_id = bank.create_exam("G検定")
    response = client.post(f"/api/exams/{exam_id}/questions", json={
        "node_path": "1", "stem": "十分に長い問題文です。",
        "choices": ["同じ", "同じ", "別"], "answer": 0,
    })
    assert response.status_code == 400
    assert "重複" in response.json()["detail"]


def test_answer_endpoint_grades_and_returns_the_explanation(client):
    exam_id, question_id = _exam_with_question()
    response = client.post(f"/api/questions/{question_id}/answer", json={"chosen": 0, "elapsed_ms": 900})
    body = response.json()
    assert body["correct"] is True
    assert body["explanation"] == "解説"
    assert body["answer"] == 0


def test_syllabus_endpoint_rejects_an_unparsable_outline(client):
    exam_id = bank.create_exam("G検定")
    response = client.post(f"/api/exams/{exam_id}/syllabus", json={"outline": "番号のない行\n"})
    assert response.status_code == 400
