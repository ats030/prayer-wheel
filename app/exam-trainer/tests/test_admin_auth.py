import pytest
from fastapi.testclient import TestClient
from exam_trainer import bank, db
from exam_trainer.config import settings

@pytest.fixture(autouse=True)
def fresh_state(tmp_path):
    db.reset_for_tests(tmp_path)
    settings.admin_token = "secret-token"
    yield
    db.close()
    settings.admin_token = ""

@pytest.fixture
def client():
    from exam_trainer.app import app
    return TestClient(app)

def test_public_pages_and_study_api_need_no_admin_cookie(client):
    exam_id = bank.create_exam("公開試験")
    bank.set_syllabus(exam_id, [{"path": "1", "title": "公開項目"}])
    question_id = bank.add_question(
        exam_id, "1", "正しいものは？", ["正解", "誤り"], 0, status="verified"
    )
    assert client.get("/").status_code == 200
    assert client.get("/weakness").status_code == 200
    assert client.get(f"/api/exams/{exam_id}/next").status_code == 200
    assert client.post(f"/api/questions/{question_id}/answer", json={"chosen": 0}).status_code == 200

def test_admin_pages_and_mutations_are_protected(client):
    page = client.get("/admin/settings", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/admin/login")
    assert client.post("/api/exams", json={"name": "blocked"}).status_code == 401

def test_login_sets_http_only_cookie_and_opens_admin(client):
    bad = client.post("/api/admin/session", json={"token": "wrong"})
    assert bad.status_code == 401
    good = client.post("/api/admin/session", json={"token": "secret-token", "next": "/admin/settings"})
    assert good.status_code == 200
    cookie = good.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert client.get("/admin/settings").status_code == 200

def test_public_navigation_does_not_expose_admin_links(client):
    html = client.get("/").text
    assert "/admin/bank" not in html
    assert "/admin/settings" not in html
