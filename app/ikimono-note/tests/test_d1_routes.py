"""Native route integration; real Python/JS binding conversion is tested in Workers."""
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import d1_store


class Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.values = db, sql, ()

    def bind(self, *values):
        self.values = values
        return self

    async def first(self):
        cursor = self.db.execute(self.sql, self.values)
        row = cursor.fetchone()
        self.db.commit()
        return dict(row) if row is not None else None

    async def run(self):
        cursor = self.db.execute(self.sql, self.values)
        self.db.commit()
        return SimpleNamespace(meta=SimpleNamespace(changes=cursor.rowcount))


class Binding:
    def __init__(self, db):
        self.db = db

    def prepare(self, sql):
        return Statement(self.db, sql)


class WorkerScope:
    def __init__(self, env):
        self.env = env

    async def __call__(self, scope, receive, send):
        scope["env"] = self.env
        await main.app(scope, receive, send)


@pytest.fixture
def d1_client(tmp_path, monkeypatch):
    db = sqlite3.connect(tmp_path / "d1.db", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript((Path(__file__).resolve().parents[1] / "cloudflare/migrations/0001.sql").read_text())
    # The fake binding uses native bytes; the real to_js conversion is verified
    # by the 700 KiB round trip in cloudflare-d1-probe/check.py.
    monkeypatch.setitem(sys.modules, "pyodide.ffi", SimpleNamespace(to_js=lambda value: value))
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main.auth, "configured", lambda: False)
    def forbid(*args, **kwargs):
        raise AssertionError("Unexpected SQLite/Firestore fallback")
    for name in ("create", "read", "photo", "delete"):
        monkeypatch.setattr(main.shares, name, forbid)
    monkeypatch.setattr(main.auth, "delete_user", forbid)
    with TestClient(WorkerScope(SimpleNamespace(DB=Binding(db))), base_url="http://localhost") as client:
        client.cookies.set(main.auth.SESSION_COOKIE, main.auth.session_for({"subject": "owner", "email": "owner@example.invalid"}))
        yield client, db
    db.close()


def test_d1_share_routes_preserve_privacy_and_ownership(d1_client):
    client, db = d1_client
    photo = b"synthetic-photo"
    candidates = [{"common_name_ja": "合成候補", "confidence": 60, "traits": ["合成特徴"],
                   "userNote": "PRIVATE_NOTE", "coordinates": {"latitude": 35.1}}]
    response = client.post("/api/share", files={"photo": ("a.jpg", photo, "image/jpeg")},
                           data={"candidates": json.dumps(candidates)})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    stored = db.execute("SELECT payload FROM shares WHERE token=?", (token,)).fetchone()[0]
    assert "PRIVATE_NOTE" not in stored and "latitude" not in stored
    assert "合成候補" in client.get(f"/s/{token}").text
    assert client.get(f"/s/{token}/photo").content == photo
    client.cookies.set(main.auth.SESSION_COOKIE, main.auth.session_for({"subject": "other", "email": "other@example.invalid"}))
    assert client.post(f"/api/share/{token}/delete").status_code == 404
    assert client.get(f"/s/{token}/photo").content == photo
    client.cookies.set(main.auth.SESSION_COOKIE, main.auth.session_for({"subject": "owner", "email": "owner@example.invalid"}))
    assert client.post(f"/api/share/{token}/delete").json() == {"deleted": True}
    assert client.get(f"/s/{token}").status_code == 404
    assert client.get(f"/s/{token}/photo").status_code == 404


def test_d1_login_callback_and_account_delete(d1_client, monkeypatch):
    client, db = d1_client
    monkeypatch.setattr(main.auth, "login_identity", lambda *args: {"subject": "owner", "email": "changed@example.invalid"})
    monkeypatch.setattr(main.auth, "finish_login", lambda *args: pytest.fail("Native auth persistence used"))
    flow = main.auth.sign_session({"state": "s", "verifier": "v", "nonce": "n", "exp": 9999999999})
    client.cookies.set(main.LOGIN_FLOW_COOKIE, flow)
    response = client.get("/auth/callback?code=synthetic&state=s", follow_redirects=False)
    assert response.status_code == 303
    assert db.execute("SELECT email FROM users WHERE subject='owner'").fetchone()[0] == "changed@example.invalid"
    # TestClient keeps the pre-existing insecure local cookie as well as the
    # production Secure cookie. Set the signed cookie explicitly for HTTP tests.
    client.cookies.clear()
    client.cookies.set(main.auth.SESSION_COOKIE, main.auth.session_for({"subject": "owner", "email": "changed@example.invalid"}))
    assert client.post("/api/me/delete").json() == {"ok": True}
    assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_worker_without_binding_fails_instead_of_using_native_storage():
    with TestClient(WorkerScope({}), base_url="http://localhost", raise_server_exceptions=False) as client:
        assert client.get("/s/synthetic-token").status_code == 500


def test_native_asgi_keeps_original_backend():
    assert d1_store.for_request(SimpleNamespace(scope={})) is None
