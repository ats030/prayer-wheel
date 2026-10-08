"""Loopback-only D1 integration harness. Never deploy this test endpoint."""
from hashlib import sha256
import os
from fastapi import FastAPI, Request
from workers import asgi
# The local harness has no OAuth flow. Production Workers must supply a fixed
# session secret before importing auth; startup entropy is forbidden by workerd.
os.environ["IKIMONO_SESSION_SECRET"] = "synthetic-local-d1-probe-never-deploy"
import d1_store
import shares

app = FastAPI()
PHOTO = bytes(range(256)) * 2800  # 700 KiB, the production sharing boundary.
PAYLOAD = {"candidates": [{"name": "合成検証", "description": "' OR 1=1 --"}]}
SUBJECT = "synthetic-d1-user"


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/probe")
async def probe(request: Request):
    store = d1_store.for_request(request)
    token = None
    try:
        user = await store.upsert_user(SUBJECT, "synthetic@example.invalid")
        assert user["plan"] == "free"
        await store.statement("UPDATE users SET created_at=?,plan=? WHERE subject=?",
                              "2001-01-01T00:00:00Z", "probe-plan", SUBJECT).run()
        updated = await store.upsert_user(SUBJECT, "changed@example.invalid")
        assert updated["created_at"] == "2001-01-01T00:00:00Z"
        assert updated["plan"] == "probe-plan"
        assert updated["email"] == "changed@example.invalid"
        assert await store.find_user(SUBJECT) == updated
        token = await store.create_share(SUBJECT, PAYLOAD, PHOTO, "image/jpeg")
        record = await store.read_share(token)
        assert record["owner"] == SUBJECT and record["payload"] == PAYLOAD
        assert "photo" not in record
        raw, photo_type = await store.share_photo(token)
        assert raw == PHOTO and photo_type == "image/jpeg"
        assert not await store.delete_share(token, "other-owner")
        assert await store.read_share(token) is not None
        assert await store.delete_share(token, SUBJECT)
        assert await store.read_share(token) is None
        assert await store.share_photo(token) is None
        assert not await store.delete_share(token, SUBJECT)
        for raw, photo_type, error in ((b"", "image/jpeg", shares.PhotoTooLarge),
                                      (PHOTO+b"x", "image/jpeg", shares.PhotoTooLarge),
                                      (b"x", "image/webp", shares.PhotoTypeNotAllowed)):
            try:
                await store.create_share(SUBJECT, PAYLOAD, raw, photo_type)
            except error:
                pass
            else:
                raise AssertionError("Invalid photo accepted")
        await store.delete_user(SUBJECT)
        assert await store.find_user(SUBJECT) is None
        return {"ok": True, "photo_bytes": len(PHOTO), "photo_sha256": sha256(PHOTO).hexdigest()}
    finally:
        if token:
            await store.delete_share(token, SUBJECT)
        await store.delete_user(SUBJECT)


@app.post("/persist")
async def persist(request: Request):
    store = d1_store.for_request(request)
    await store.upsert_user("synthetic-persist-user", "persist@example.invalid")
    await store.statement("INSERT INTO shares(token,owner,created_at,payload,photo,photo_type) "
                          "VALUES(?,?,?,?,?,?) ON CONFLICT(token) DO NOTHING",
                          "synthetic-persist-share", "synthetic-persist-user", "2001-01-01T00:00:00Z",
                          '{"synthetic":true}', PHOTO, "image/jpeg").run()
    return {"ok": True}


@app.get("/persist")
async def verify_persist(request: Request):
    store = d1_store.for_request(request)
    user = await store.find_user("synthetic-persist-user")
    photo = await store.share_photo("synthetic-persist-share")
    assert user["email"] == "persist@example.invalid"
    assert photo[0] == PHOTO and photo[1] == "image/jpeg"
    return {"ok": True, "photo_sha256": sha256(photo[0]).hexdigest()}


Default = asgi.entrypoint(app)
