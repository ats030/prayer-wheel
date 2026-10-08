"""Explicit, asynchronous D1 storage. No filesystem or Firestore fallback."""
from __future__ import annotations

import json
import time
import shares


def for_request(request):
    env = request.scope.get("env")
    if env is None:
        return None  # Native ASGI keeps the existing SQLite/Firestore backend.
    db = env.get("DB") if isinstance(env, dict) else getattr(env, "DB", None)
    if db is None:
        raise RuntimeError("Workers requires the DB D1 binding")
    return D1Store(db)


def _record(row):
    if not row:
        return None
    return row.to_py() if hasattr(row, "to_py") else dict(row)


class D1Store:
    def __init__(self, db):
        self.db = db

    def statement(self, sql, *values):
        converted = []
        for value in values:
            if isinstance(value, bytes):
                # An explicit buffer conversion prevents a leaking PyProxy and
                # gives D1 an ArrayBufferView, rather than a Python bytes proxy.
                from pyodide.ffi import to_js
                value = to_js(value)
            converted.append(value)
        return self.db.prepare(sql).bind(*converted)

    async def upsert_user(self, subject, email):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        row = await self.statement(
            "INSERT INTO users (subject,email,created_at,last_seen_at) VALUES (?,?,?,?) "
            "ON CONFLICT(subject) DO UPDATE SET email=excluded.email,last_seen_at=excluded.last_seen_at "
            "RETURNING subject,email,created_at,last_seen_at,plan", subject, email, now, now).first()
        record = _record(row)
        if record is None:
            raise RuntimeError("D1 user write returned no record")
        return record

    async def find_user(self, subject):
        return _record(await self.statement(
            "SELECT subject,email,created_at,last_seen_at,plan FROM users WHERE subject=?", subject).first())

    async def delete_user(self, subject):
        await self.statement("DELETE FROM users WHERE subject=?", subject).run()

    async def create_share(self, owner, payload, photo, photo_type):
        shares.validate_photo(photo, photo_type)
        token = shares.new_token()
        await self.statement(
            "INSERT INTO shares (token,owner,created_at,payload,photo,photo_type) VALUES (?,?,?,?,?,?)",
            token, owner, shares._now(), json.dumps(payload, ensure_ascii=False), photo, photo_type).run()
        return token

    async def read_share(self, token):
        record = _record(await self.statement(
            "SELECT owner,created_at,payload FROM shares WHERE token=?", token).first())
        if record is None:
            return None
        try:
            record["payload"] = json.loads(record["payload"])
        except ValueError:
            return None
        return record

    async def share_photo(self, token):
        row = await self.statement("SELECT photo,photo_type FROM shares WHERE token=?", token).first()
        if not row:
            return None
        if isinstance(row, dict):
            raw, photo_type = bytes(row["photo"]), row["photo_type"]
        else:
            # D1 returns BLOBs as JS arrays. Copy through a typed buffer instead
            # of allocating one Python int per byte for a 700 KiB photograph.
            from js import Uint8Array
            raw = Uint8Array.new(row.photo).to_py().tobytes()
            photo_type = row.photo_type
        return (raw, photo_type) if raw else None

    async def delete_share(self, token, owner):
        # Ownership is checked atomically in SQL, including concurrent requests.
        result = await self.statement("DELETE FROM shares WHERE token=? AND owner=?", token, owner).run()
        return result.meta.changes > 0
