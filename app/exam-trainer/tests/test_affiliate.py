import pytest
from fastapi.testclient import TestClient
from exam_trainer import affiliate, bank, db

@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path)
    yield
    db.close()

@pytest.fixture
def client():
    from exam_trainer.app import ADMIN_COOKIE, app
    from exam_trainer.config import settings
    settings.admin_token = "test-admin-token"
    test_client = TestClient(app)
    test_client.cookies.set(ADMIN_COOKIE, settings.admin_token)
    return test_client

def _setup():
    exam_id = bank.create_exam("Affiliate test")
    bank.set_syllabus(exam_id, [{"path": "1.1", "title": "基礎"}])
    question_id = bank.add_question(
        exam_id, "1.1", "正しいものは？", ["正解", "誤り"], 0,
        explanation="根拠のある解説", status="verified",
    )
    resource = affiliate.upsert(
        exam_id, "1.1", "確認用教材", "https://example.test/book?tag=sample",
        "この範囲を体系的に確認できます",
    )
    return exam_id, question_id, resource

def test_resource_appears_only_after_answer(client):
    exam_id, question_id, resource = _setup()
    before = client.get(f"/api/exams/{exam_id}/next").json()["question"]
    assert "affiliate_resource" not in before
    answered = client.post(f"/api/questions/{question_id}/answer", json={"chosen": 0}).json()
    assert answered["affiliate_resource"]["id"] == resource["id"]
    assert "url" not in answered["affiliate_resource"]

def test_events_redirect_and_deactivation(client):
    exam_id, question_id, resource = _setup()
    response = client.post(
        f"/api/affiliate-resources/{resource['id']}/impression",
        json={"question_id": question_id},
    )
    assert response.status_code == 200
    clicked = client.get(
        f"/affiliate-resources/{resource['id']}/click?question_id={question_id}",
        follow_redirects=False,
    )
    assert clicked.status_code == 303
    assert clicked.headers["location"] == "https://example.test/book?tag=sample"
    stats = affiliate.list_for_exam(exam_id)[0]
    assert (stats["impressions"], stats["clicks"]) == (1, 1)
    affiliate.set_active(resource["id"], False)
    assert affiliate.for_node(exam_id, "1.1") is None
