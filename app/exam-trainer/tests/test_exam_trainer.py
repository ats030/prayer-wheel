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


def test_health_reports_the_database(client, monkeypatch):
    from exam_trainer import ollama_client, web

    # Probing the real Ollama/SearXNG would make this test depend on what is
    # running on the machine; only the database check belongs here.
    monkeypatch.setattr(ollama_client, "available", lambda: True)
    monkeypatch.setattr(web, "available", lambda: False)
    monkeypatch.setattr(web, "reachable", lambda: False)
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["ollama"] is True
    assert body["web"] is False


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


# --- material / passages -------------------------------------------------

def test_passages_prefer_paragraph_boundaries():
    from exam_trainer import web

    text = ("あ" * 700) + "。\n" + ("い" * 700) + "。"
    chunks = web.passages(text, size=800, overlap=50)
    assert len(chunks) >= 2
    assert chunks[0].endswith("。"), "文の途中で切ると、切れた側について問う問題が出る"


def test_passages_returns_short_text_whole():
    from exam_trainer import web

    assert web.passages("短い本文です。") == ["短い本文です。"]
    assert web.passages("   ") == []


def test_search_query_includes_the_exam_name():
    from exam_trainer import materials

    query = materials.search_query("G検定", {"path": "2.3", "title": "汎化", "keywords": "過学習, 交差検証"})
    assert query.startswith("G検定"), "試験名がないと汎用の論文に流れる"
    assert "過学習" in query


def test_past_question_sites_are_filtered_out():
    from exam_trainer import web

    assert web._blocked("https://example.com/kakomon/2024")
    assert not web._blocked("https://example.com/glossary/ai")


# --- generation gates ----------------------------------------------------

def test_evidence_must_appear_in_the_passage():
    from exam_trainer import generate

    passage = "AI効果とは、原理が解明されると知能とは見なされなくなる現象である。"
    assert generate.grounded("原理が解明されると知能とは見なされなくなる現象", passage)
    # Punctuation and spacing differences must not defeat the match.
    assert generate.grounded("原理が解明されると、知能とは見なされなくなる 現象", passage)
    assert not generate.grounded("チューリングテストは人間と区別できるかを問うものである", passage)


def test_short_evidence_is_not_accepted_as_grounding():
    from exam_trainer import generate

    passage = "AI効果とは、原理が解明されると知能とは見なされなくなる現象である。"
    assert not generate.grounded("AI効果", passage), "短い断片は偶然一致しうる"


def test_screen_drops_an_invented_quote():
    from exam_trainer import generate

    passage = "教師あり学習では、正解ラベル付きのデータから入出力の対応を学習する。"
    candidate = {
        "stem": "教師あり学習の説明として正しいものはどれか。",
        "choices": ["正解ラベル付きデータから学習する", "報酬から学習する", "ラベルなしで構造を見つける"],
        "answer": 0,
        "evidence": "強化学習では報酬を最大化する方策を学習する",  # 抜粋にない
    }
    verdict, reason = generate.screen(candidate, passage, [], embed=lambda text: [1.0])
    assert verdict == "drop"
    assert "根拠" in reason


def test_screen_drops_a_malformed_question_before_any_model_call():
    from exam_trainer import generate

    def explode(text):
        raise AssertionError("形が壊れた問題で埋め込みを呼んではいけない")

    passage = "教師あり学習では、正解ラベル付きのデータから入出力の対応を学習する。"
    candidate = {
        "stem": "教師あり学習の説明として正しいものはどれか。",
        "choices": ["同じ", "同じ", "別"],
        "answer": 0,
        "evidence": "正解ラベル付きのデータから入出力の対応を学習する",
    }
    verdict, _ = generate.screen(candidate, passage, [], embed=explode)
    assert verdict == "drop"


def test_screen_accepts_a_grounded_question():
    from exam_trainer import generate

    passage = "教師あり学習では、正解ラベル付きのデータから入出力の対応を学習する。"
    candidate = {
        "stem": "教師あり学習の説明として正しいものはどれか。",
        "choices": ["正解ラベル付きのデータから学習する", "報酬signalから学習する", "ラベルなしで構造を探す"],
        "answer": 0,
        "evidence": "正解ラベル付きのデータから入出力の対応を学習する",
    }
    verdict, reason = generate.screen(candidate, passage, [], embed=lambda text: [1.0, 0.0])
    assert verdict == "ok", reason


def test_duplicate_detection_falls_back_when_embeddings_fail():
    from exam_trainer import generate

    def broken(text):
        raise RuntimeError("ollama down")

    assert generate.is_duplicate("同じ問題文です。", ["同じ問題文です。"], embed=broken), "完全一致は拾う"
    assert not generate.is_duplicate("違う問題文です。", ["同じ問題文です。"], embed=broken), \
        "埋め込みが落ちても生成は止めない"


def test_duplicate_detection_uses_cosine_similarity():
    from exam_trainer import generate

    vectors = {"新しい問題": [1.0, 0.0], "既存の問題": [0.999, 0.01]}
    assert generate.is_duplicate("新しい問題", ["既存の問題"], embed=lambda t: vectors[t])
    vectors["既存の問題"] = [0.0, 1.0]
    assert not generate.is_duplicate("新しい問題", ["既存の問題"], embed=lambda t: vectors[t])


# --- verification --------------------------------------------------------

def test_verifier_disagreement_holds_the_question(monkeypatch):
    from exam_trainer import generate, ollama_client

    monkeypatch.setattr(
        ollama_client, "generate_json",
        lambda *a, **k: {"answer": 2, "reason": "抜粋では別の記述", "unique": True},
    )
    agrees, reason = generate.verify("抜粋", "問題", ["ア", "イ", "ウ"], 0)
    assert not agrees
    assert "C" in reason, "どちらを正解と判断したかが分かること"


def test_verifier_agreement_passes():
    from exam_trainer import generate, ollama_client
    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(ollama_client, "generate_json", lambda *a, **k: {"answer": 0, "unique": True})
        agrees, reason = generate.verify("抜粋", "問題", ["ア", "イ", "ウ"], 0)
    assert agrees and reason == ""


def test_ambiguous_question_is_not_verified(monkeypatch):
    from exam_trainer import generate, ollama_client

    monkeypatch.setattr(
        ollama_client, "generate_json",
        lambda *a, **k: {"answer": 0, "unique": False, "reason": "複数が正解になりうる"},
    )
    agrees, reason = generate.verify("抜粋", "問題", ["ア", "イ", "ウ"], 0)
    assert not agrees
    assert "一意" in reason


def test_verifier_failure_holds_rather_than_passes(monkeypatch):
    """検証を実行できないときに素通しさせない（fail closed）。"""
    from exam_trainer import generate, ollama_client

    def explode(*args, **kwargs):
        raise ollama_client.OllamaError("connection refused")

    monkeypatch.setattr(ollama_client, "generate_json", explode)
    agrees, reason = generate.verify("抜粋", "問題", ["ア", "イ", "ウ"], 0)
    assert not agrees
    assert "検証" in reason


# --- end to end (no network, no model) -----------------------------------

def test_generation_stores_verified_and_held_separately(monkeypatch):
    from exam_trainer import generate, materials, ollama_client, web

    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "2.1", "title": "教師あり学習", "keywords": "SVM"}])
    passage = "教師あり学習では、正解ラベル付きのデータから入出力の対応を学習する。" * 3

    monkeypatch.setattr(web, "available", lambda: True)
    monkeypatch.setattr(materials, "ensure", lambda *a, **k: [
        {"url": "https://example.test/ml", "title": "ML", "text": passage}
    ])
    monkeypatch.setattr(generate, "questions_from_passage", lambda *a, **k: [
        {
            "stem": "教師あり学習の説明として正しいものはどれか。",
            "choices": ["正解ラベル付きのデータから学習する", "報酬から方策を学ぶ", "ラベルなしで構造を探す"],
            "answer": 0,
            "explanation": "定義のとおり。",
            "evidence": "正解ラベル付きのデータから入出力の対応を学習する",
        },
        {
            "stem": "教師あり学習で使われるデータの説明はどれか。",
            "choices": ["正解ラベルが付いている", "報酬だけがある", "何も付いていない"],
            "answer": 0,
            "explanation": "同上。",
            "evidence": "正解ラベル付きのデータから入出力の対応を学習する",
        },
    ])
    monkeypatch.setattr(generate, "is_duplicate", lambda *a, **k: False)
    # 1問目は同意、2問目は不一致。
    answers = iter([{"answer": 0, "unique": True}, {"answer": 1, "unique": True}])
    monkeypatch.setattr(ollama_client, "generate_json", lambda *a, **k: next(answers))

    summary = generate.generate_for_node(exam_id, "2.1", target=2)
    assert summary["verified"] == 1
    assert summary["held"] == 1

    verified = bank.list_questions(exam_id, status="verified")
    held = bank.list_questions(exam_id, status="held")
    assert len(verified) == 1 and len(held) == 1
    assert verified[0]["source_refs"] == ["https://example.test/ml"]
    assert verified[0]["origin"] == "generated"
    assert "B" in held[0]["hold_reason"]
    # そして held は出題キューに入らない。
    assert bank.queue_counts(exam_id) == {"due": 0, "new": 1}


def test_generation_without_material_reports_why(monkeypatch):
    from exam_trainer import generate, materials, web

    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "定義"}])
    monkeypatch.setattr(materials, "ensure", lambda *a, **k: [])
    monkeypatch.setattr(web, "last_search_note", lambda: "")
    summary = generate.generate_for_node(exam_id, "1")
    assert summary["verified"] == 0
    assert any("記事が見つかりません" in reason for reason in summary["reasons"])


# --- jobs ----------------------------------------------------------------

def test_enqueue_is_idempotent_per_node():
    from exam_trainer import jobs

    exam_id = bank.create_exam("G検定")
    first = jobs.enqueue(exam_id, "1.1")
    second = jobs.enqueue(exam_id, "1.1")
    assert first["id"] == second["id"], "二度押しで二重生成しない"


def test_running_jobs_are_requeued_after_a_restart():
    from exam_trainer import jobs

    exam_id = bank.create_exam("G検定")
    job = jobs.enqueue(exam_id, "1.1")
    db.connection().execute("UPDATE job SET status = 'running' WHERE id = ?", (job["id"],))
    db.connection().commit()
    jobs.recover_running()
    assert jobs.get(job["id"])["status"] == "queued"


def test_generation_endpoint_refuses_without_search(client, monkeypatch):
    from exam_trainer import web

    exam_id = bank.create_exam("G検定")
    monkeypatch.setattr(web, "available", lambda: False)
    response = client.post(f"/api/exams/{exam_id}/generate", json={"node_path": "1.1"})
    assert response.status_code == 400
    assert "SEARXNG" in response.json()["detail"]


def test_stem_must_not_reference_the_passage():
    """実際の生成で「抜粋における〜」という問題文が出た。解答者に抜粋は見えない。"""
    problems = checks.check(
        "抜粋における「汎化誤差」の説明として正しいものはどれか。",
        ["初めて見る問題での誤り率", "訓練データでの誤り率", "モデル選択の手順"],
        0,
    )
    assert any("抜粋" in problem for problem in problems)
    assert not checks.check(
        "「汎化誤差」の説明として正しいものはどれか。",
        ["初めて見る問題での誤り率", "訓練データでの誤り率", "モデル選択の手順"],
        0,
    )


def test_screen_drops_a_passage_referencing_stem():
    from exam_trainer import generate

    passage = "汎化誤差とは、初めて見るデータに対する誤りの割合のことである。" * 2
    candidate = {
        "stem": "本文中の「汎化誤差」の説明として正しいものはどれか。",
        "choices": ["初めて見るデータでの誤り率", "訓練データでの誤り率", "学習率の大きさ"],
        "answer": 0,
        "evidence": "汎化誤差とは、初めて見るデータに対する誤りの割合のことである",
    }
    verdict, reason = generate.screen(candidate, passage, [], embed=lambda t: [1.0])
    assert verdict == "drop"
    assert "本文中" in reason


def test_generation_dialog_opens_with_no_node_selected(client):
    """先頭の項目が選ばれた状態で開くと、選んだつもりのないまま数分のジョブが走る。"""
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [
        {"path": "1", "title": "人工知能とは"},
        {"path": "2", "title": "機械学習の具体的手法"},
    ])
    html = client.get(f"/bank?exam_id={exam_id}").text
    dialog = html[html.index('id="genNode"'):]
    dialog = dialog[:dialog.index("</select>")]
    assert '<option value="" selected>選んでください</option>' in dialog
    assert "selected" not in dialog.split("</option>", 1)[1], "実項目が既定で選ばれている"


def test_generation_dialog_keeps_an_explicit_node_filter(client):
    """範囲を絞って見ている最中は、その項目を引き継ぐ（既定ではなく明示の操作）。"""
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "人工知能とは"}, {"path": "2", "title": "機械学習"}])
    html = client.get(f"/bank?exam_id={exam_id}&node=2").text
    dialog = html[html.index('id="genNode"'):]
    dialog = dialog[:dialog.index("</select>")]
    assert '<option value="2" selected>' in dialog
    assert '<option value="" >' in dialog or '<option value="">' in dialog


def test_generation_endpoint_refuses_an_empty_node(client, monkeypatch):
    from exam_trainer import web

    exam_id = bank.create_exam("G検定")
    monkeypatch.setattr(web, "available", lambda: True)
    response = client.post(f"/api/exams/{exam_id}/generate", json={"node_path": ""})
    assert response.status_code == 400
    assert "選んで" in response.json()["detail"]


# --- proofreading of choices --------------------------------------------

def test_broken_japanese_in_a_choice_holds_the_question(monkeypatch):
    """実生成で「初めて見る問題を解いたもつときの」という誤答選択肢が出た。

    明らかに壊れた選択肢は「これは誤答だ」というヒントになり、知識ではなく
    文面の粗さで正解が当てられてしまう。
    """
    from exam_trainer import generate, ollama_client

    monkeypatch.setattr(
        ollama_client, "generate_json",
        lambda *a, **k: {"answer": 0, "unique": True, "flawed": [2]},
    )
    agrees, reason = generate.verify("抜粋", "問題", ["ア", "イ", "解いたもつときの割合"], 0)
    assert not agrees
    assert "C" in reason and "日本語" in reason


def test_clean_choices_pass_the_proofreading_check(monkeypatch):
    from exam_trainer import generate, ollama_client

    monkeypatch.setattr(
        ollama_client, "generate_json",
        lambda *a, **k: {"answer": 0, "unique": True, "flawed": []},
    )
    agrees, reason = generate.verify("抜粋", "問題", ["ア", "イ", "ウ"], 0)
    assert agrees and reason == ""


def test_a_missing_flawed_field_is_treated_as_clean(monkeypatch):
    """古い応答形式や省略で不合格にしない（flawed は追加項目）。"""
    from exam_trainer import generate, ollama_client

    monkeypatch.setattr(ollama_client, "generate_json", lambda *a, **k: {"answer": 0, "unique": True})
    agrees, _ = generate.verify("抜粋", "問題", ["ア", "イ", "ウ"], 0)
    assert agrees


def test_out_of_range_flawed_indices_are_ignored():
    from exam_trainer import generate

    assert generate._flawed_labels([0, 2], 3) == ["A", "C"]
    assert generate._flawed_labels([5, -1, "x", None], 3) == [], "範囲外や壊れた値で誤検知しない"
    assert generate._flawed_labels("2", 3) == []
    assert generate._flawed_labels([1, 1], 3) == ["B"], "重複は畳む"


# --- weakness -> generation ---------------------------------------------

def test_empty_branches_link_to_generation_not_to_studying(client):
    """問題が無い枝で「解く」を出しても空振りするので、そこは生成へ送る。"""
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "問題あり"}, {"path": "2", "title": "問題なし"}])
    question_id = bank.add_question(
        exam_id, "1", "AI効果とは何を指すか。",
        ["原理が分かると知能と見なされない", "人間を超える時点", "学習の発散"], 0, status="verified",
    )
    bank.answer(question_id, 0)
    html = client.get(f"/weakness?exam_id={exam_id}").text
    assert f"/?exam_id={exam_id}&node=1" in html, "問題のある枝は解きに行ける"
    assert f"/bank?exam_id={exam_id}&node=2&generate=1" in html, "空の枝は生成へ送る"
    assert f"/?exam_id={exam_id}&node=2" not in html


def test_arriving_from_a_weakness_branch_opens_the_dialog_on_that_node(client):
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "A"}, {"path": "2.1", "title": "B"}])
    html = client.get(f"/bank?exam_id={exam_id}&node=2.1&generate=1").text
    assert 'data-open-generate="1"' in html
    dialog = html[html.index('id="genNode"'):]
    assert '<option value="2.1" selected>' in dialog[:dialog.index("</select>")]


def test_generate_flag_without_a_node_does_not_open_the_dialog(client):
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "A"}])
    html = client.get(f"/bank?exam_id={exam_id}&generate=1").text
    assert "data-open-generate" not in html, "項目が無いまま開いても選ぶものがない"


# --- search reachability -------------------------------------------------

def test_available_and_reachable_mean_different_things(monkeypatch):
    """設定があることと、応答があることを混同したのが元のバグ。"""
    from exam_trainer import web
    from exam_trainer.config import settings as app_settings

    monkeypatch.setattr(app_settings, "searxng_url", "http://192.0.2.1:8081/search")
    web._reachable_cache = None
    assert web.available() is True, "設定はされている"
    assert web.reachable() is False, "到達はできない"


def test_reachable_is_false_without_configuration(monkeypatch):
    from exam_trainer import web
    from exam_trainer.config import settings as app_settings

    monkeypatch.setattr(app_settings, "searxng_url", "")
    web._reachable_cache = None
    assert web.reachable() is False


def test_reachability_is_cached(monkeypatch):
    from exam_trainer import web
    from exam_trainer.config import settings as app_settings

    calls = {"n": 0}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"results": []}

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k):
            calls["n"] += 1
            return _Resp()

    monkeypatch.setattr(app_settings, "searxng_url", "http://127.0.0.1:8081/search")
    monkeypatch.setattr(web.httpx, "Client", _Client)
    web._reachable_cache = None
    assert web.reachable() is True
    assert web.reachable() is True
    assert calls["n"] == 1, "死んだホストへ毎回 connect timeout を払わない"
    assert web.reachable(force=True) is True
    assert calls["n"] == 2


def test_generation_refuses_when_search_is_unreachable(client, monkeypatch):
    from exam_trainer import web

    exam_id = bank.create_exam("G検定")
    monkeypatch.setattr(web, "available", lambda: True)
    monkeypatch.setattr(web, "reachable", lambda: False)
    response = client.post(f"/api/exams/{exam_id}/generate", json={"node_path": "1"})
    assert response.status_code == 400
    assert "接続できません" in response.json()["detail"], "数分走らせてから空振りに気づくのを防ぐ"


def test_health_distinguishes_configured_from_reachable(client, monkeypatch):
    from exam_trainer import ollama_client, web

    monkeypatch.setattr(ollama_client, "available", lambda: True)
    monkeypatch.setattr(web, "available", lambda: True)
    monkeypatch.setattr(web, "reachable", lambda: False)
    body = client.get("/health").json()
    assert body["web"] is False
    assert body["web_configured"] is True


# --- bulk generation -----------------------------------------------------

def _syllabus_with_children(exam_id: int) -> None:
    bank.set_syllabus(exam_id, [
        {"path": "1", "title": "親"},
        {"path": "1.1", "title": "子A"},
        {"path": "1.2", "title": "子B"},
        {"path": "2", "title": "葉だけの項目"},
    ])


def test_only_leaves_are_generation_targets():
    """親は子の集約なので、そこに問題を作ると子と重複する。"""
    exam_id = bank.create_exam("G検定")
    _syllabus_with_children(exam_id)
    assert bank.leaf_paths(exam_id) == {"1.1", "1.2", "2"}
    paths = [node["path"] for node in bank.nodes_needing_questions(exam_id, target=3)]
    assert "1" not in paths
    assert set(paths) == {"1.1", "1.2", "2"}


def test_nodes_at_target_are_not_queued_again():
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "A"}, {"path": "2", "title": "B"}])
    for index in range(2):
        bank.add_question(
            exam_id, "1", f"十分に長い問題文です その{index}。",
            ["正しい説明", "誤った説明", "別の誤り"], 0, status="verified",
        )
    pending = {node["path"]: node for node in bank.nodes_needing_questions(exam_id, target=2)}
    assert "1" not in pending, "目標に達した項目は積まない"
    assert pending["2"]["missing"] == 2


def test_held_and_draft_questions_do_not_count_towards_the_target():
    """出題できない問題で「足りている」と判断すると、解くものが無いまま終わる。"""
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "A"}])
    bank.add_question(exam_id, "1", "十分に長い問題文です。", ["ア", "イ", "ウ"], 0, status="held")
    bank.add_question(exam_id, "1", "もう一つの問題文です。", ["ア", "イ", "ウ"], 0, status="draft")
    pending = bank.nodes_needing_questions(exam_id, target=1)
    assert [node["path"] for node in pending] == ["1"]


def test_weak_nodes_are_queued_before_untried_and_perfect_ones():
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [
        {"path": "1", "title": "苦手"},
        {"path": "2", "title": "未挑戦"},
        {"path": "3", "title": "全問正解"},
    ])
    weak = bank.add_question(
        exam_id, "1", "苦手な項目の問題文です。", ["正解", "誤り", "別の誤り"], 0, status="verified",
    )
    perfect = bank.add_question(
        exam_id, "3", "得意な項目の問題文です。", ["正解", "誤り", "別の誤り"], 0, status="verified",
    )
    bank.answer(weak, 1)      # wrong
    bank.answer(perfect, 0)   # right

    order = [node["path"] for node in bank.nodes_needing_questions(exam_id, target=5)]
    assert order == ["1", "2", "3"], "苦手 → 未挑戦 → 正解済み の順に埋める"


def test_bulk_queue_respects_the_limit():
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": str(i), "title": f"項目{i}"} for i in range(1, 11)])
    assert len(bank.nodes_needing_questions(exam_id, target=5, limit=3)) == 3
    assert len(bank.nodes_needing_questions(exam_id, target=5)) == 10


def test_bulk_endpoint_queues_one_job_per_node(client, monkeypatch):
    from exam_trainer import jobs, web

    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "A"}, {"path": "2", "title": "B"}])
    monkeypatch.setattr(web, "available", lambda: True)
    monkeypatch.setattr(web, "reachable", lambda: True)

    body = client.post(f"/api/exams/{exam_id}/generate-missing", json={"target": 3, "limit": 5}).json()
    assert body["count"] == 2
    assert {item["node_path"] for item in body["queued"]} == {"1", "2"}
    assert len({item["job_id"] for item in body["queued"]}) == 2, "項目ごとに別のジョブ"

    # 二度押しても増えない (enqueue が node ごとに冪等)。
    again = client.post(f"/api/exams/{exam_id}/generate-missing", json={"target": 3, "limit": 5}).json()
    assert {item["job_id"] for item in again["queued"]} == {item["job_id"] for item in body["queued"]}
    assert len(jobs.list_for_exam(exam_id)) == 2


def test_bulk_endpoint_says_so_when_nothing_is_missing(client, monkeypatch):
    from exam_trainer import web

    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "A"}])
    bank.add_question(exam_id, "1", "十分に長い問題文です。", ["ア", "イ", "ウ"], 0, status="verified")
    monkeypatch.setattr(web, "available", lambda: True)
    monkeypatch.setattr(web, "reachable", lambda: True)
    response = client.post(f"/api/exams/{exam_id}/generate-missing", json={"target": 1})
    assert response.status_code == 400
    assert "達しています" in response.json()["detail"]


def test_bulk_endpoint_refuses_when_search_is_unreachable(client, monkeypatch):
    from exam_trainer import web

    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "A"}])
    monkeypatch.setattr(web, "available", lambda: True)
    monkeypatch.setattr(web, "reachable", lambda: False)
    assert client.post(f"/api/exams/{exam_id}/generate-missing", json={}).status_code == 400


def test_missing_preview_endpoint_reports_what_would_be_queued(client):
    exam_id = bank.create_exam("G検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "A"}, {"path": "2", "title": "B"}])
    body = client.get(f"/api/exams/{exam_id}/missing?target=4&limit=1").json()
    assert body["count"] == 1
    assert body["items"][0]["missing"] == 4
    assert body["items"][0]["accuracy"] is None


# --- encoding ------------------------------------------------------------

def test_garbled_text_is_detected():
    """charset を返さない Shift_JIS ページが utf-8 として読まれ、6000字の
    文字化けが素材として通っていた（実測: nta.go.jp）。"""
    from exam_trainer import web

    assert web.looks_garbled("��u�������@")
    assert web.looks_garbled("")
    assert not web.looks_garbled("「清酒の製法品質表示基準」が制定された平成元年当時、清酒については")


def test_extraction_decodes_shift_jis_without_a_charset_header(monkeypatch):
    from exam_trainer import web

    body = "<html><body><p>" + "清酒の製法品質表示基準について説明します。" * 8 + "</p></body></html>"
    raw = body.encode("shift_jis")

    class _Resp:
        content = raw
        # httpx guesses utf-8 when Content-Type carries no charset; decoding
        # with it is exactly what produced the mojibake.
        text = raw.decode("utf-8", errors="replace")
        def raise_for_status(self): pass

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): return _Resp()

    monkeypatch.setattr(web.httpx, "Client", _Client)
    material = web.extract_url("https://example.test/sjis")
    assert material is not None, "bytes を渡していれば読めるはず"
    assert "清酒の製法品質表示基準" in material.text
    assert "�" not in material.text


def test_garbled_extraction_is_discarded(monkeypatch):
    from exam_trainer import web

    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: "�" * 500)
    monkeypatch.setattr(web.trafilatura, "extract_metadata", lambda *a, **k: None)

    class _Resp:
        content = b"<html></html>"
        def raise_for_status(self): pass

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): return _Resp()

    monkeypatch.setattr(web.httpx, "Client", _Client)
    assert web.extract_url("https://example.test/broken") is None, \
        "文字化け素材は根拠照合を素通りしてしまうので取り込まない"


# --- search throttling ---------------------------------------------------

def test_throttled_upstreams_are_reported_not_read_as_no_pages(monkeypatch):
    """SearXNG は上流が全滅しても 200 と空配列を返す。「話題が無い」と区別する。

    実際に起きた: 短時間に多数の検定を調べたら brave/duckduckgo/google が
    「Suspended: too many requests」になり、生成が素材0で done になった。
    """
    from exam_trainer import web
    from exam_trainer.config import settings as app_settings

    payload = {
        "results": [],
        "unresponsive_engines": [
            ["brave", "Suspended: too many requests"],
            ["duckduckgo", "Suspended: access denied"],
        ],
    }

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return payload

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): return _Resp()

    monkeypatch.setattr(app_settings, "searxng_url", "http://127.0.0.1:8081/search")
    monkeypatch.setattr(web.httpx, "Client", _Client)
    assert web.search_urls("何か") == []
    note = web.last_search_note()
    assert "拒否" in note and "brave" in note
    assert "時間をおいて" in note, "待てば直ることが伝わらないと、話題を諦めてしまう"


def test_no_results_without_suspension_is_not_blamed_on_throttling(monkeypatch):
    from exam_trainer import web
    from exam_trainer.config import settings as app_settings

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"results": [], "unresponsive_engines": []}

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): return _Resp()

    monkeypatch.setattr(app_settings, "searxng_url", "http://127.0.0.1:8081/search")
    monkeypatch.setattr(web.httpx, "Client", _Client)
    assert web.search_urls("何か") == []
    assert web.last_search_note() == ""


def test_generation_reports_throttling_as_the_reason(monkeypatch):
    from exam_trainer import generate, materials, web

    exam_id = bank.create_exam("日本酒検定")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "特定名称酒"}])
    monkeypatch.setattr(materials, "ensure", lambda *a, **k: [])
    monkeypatch.setattr(web, "last_search_note", lambda: "検索エンジン側が一時的に応答を拒否しています")
    summary = generate.generate_for_node(exam_id, "1")
    assert summary["verified"] == 0
    assert any("拒否" in reason for reason in summary["reasons"])


# --- material by URL -----------------------------------------------------

def _fake_extract(mapping):
    from exam_trainer import web

    def extract(url):
        text = mapping.get(url)
        if text is None:
            return None
        return web.Material(url=url, title=f"title of {url}", text=text)
    return extract


def test_urls_can_be_registered_as_material_without_search(monkeypatch):
    """検索が止まっていても素材を入れられる経路。"""
    from exam_trainer import materials, web

    exam_id = bank.create_exam("G検定")
    monkeypatch.setattr(
        materials.web, "extract_url",
        _fake_extract({"https://example.test/a": "誤差逆伝播法について" * 40}),
    )

    def explode(*a, **k):
        raise AssertionError("URL 指定なら検索は走らない")

    monkeypatch.setattr(web, "search_urls", explode)
    result = materials.add_from_urls(exam_id, "3.1", ["https://example.test/a"])
    assert len(result["added"]) == 1
    assert materials.counts_by_node(exam_id) == {"3.1": 1}


def test_registered_material_makes_generation_skip_the_search(monkeypatch):
    from exam_trainer import materials, web

    exam_id = bank.create_exam("G検定")
    monkeypatch.setattr(
        materials.web, "extract_url",
        _fake_extract({"https://example.test/a": "活性化関数について" * 40}),
    )
    materials.add_from_urls(exam_id, "3.1", ["https://example.test/a"])

    monkeypatch.setattr(web, "available", lambda: True)
    monkeypatch.setattr(web, "gather", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("素材があるのに検索した")
    ))
    got = materials.ensure(exam_id, {"path": "3.1", "title": "NN", "keywords": ""}, "G検定")
    assert len(got) == 1


def test_bad_urls_are_reported_individually(monkeypatch):
    from exam_trainer import materials

    exam_id = bank.create_exam("G検定")
    monkeypatch.setattr(
        materials.web, "extract_url",
        _fake_extract({"https://example.test/ok": "本文" * 60}),
    )
    result = materials.add_from_urls(exam_id, "1", [
        "https://example.test/ok",
        "https://example.test/empty",   # 本文が取れない
        "ftp://example.test/x",         # そもそも http ではない
        "   ",                          # 空行
    ])
    assert len(result["added"]) == 1
    reasons = {item["url"]: item["reason"] for item in result["failed"]}
    assert "本文" in reasons["https://example.test/empty"]
    assert "URL" in reasons["ftp://example.test/x"]
    assert len(result["failed"]) == 2, "空行は失敗として数えない"


def test_material_endpoint_refuses_when_nothing_could_be_read(client, monkeypatch):
    from exam_trainer import materials

    exam_id = bank.create_exam("G検定")
    monkeypatch.setattr(materials.web, "extract_url", _fake_extract({}))
    response = client.post(f"/api/exams/{exam_id}/materials", json={
        "node_path": "1", "urls": ["https://example.test/x"],
    })
    assert response.status_code == 400
    assert "本文を取り出せませんでした" in response.json()["detail"]


def test_material_endpoint_requires_a_node_and_urls(client):
    exam_id = bank.create_exam("G検定")
    assert client.post(f"/api/exams/{exam_id}/materials", json={
        "node_path": "", "urls": ["https://example.test/x"]}).status_code == 400
    assert client.post(f"/api/exams/{exam_id}/materials", json={
        "node_path": "1", "urls": ["  "]}).status_code == 400
