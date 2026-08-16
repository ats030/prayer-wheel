"""共有ボタンを押した記録だけを預かり、公開ページとして出せるようにする。

調べた記録は端末の中 (IndexedDB) にあり、ここへは来ない。利用者が共有ボタンを
押したものだけが上がってきて、そのときだけ公開URLができる。押していない記録は
今までどおり端末から出ない。公開は記録画面からいつでも取り消せる。

置き場は auth と同じ二本立て。手元では SQLite、Cloud Run では Firestore。
写真も Firestore のドキュメントに入れる。Cloud Storage の Always Free は
us-east1 / us-west1 / us-central1 だけで、東京に置くと課金される。Firestore は
1GiB まで無料で、保存する国も東京のまま変わらない。

Firestore のドキュメントは 1MiB までなので、写真はそれより十分小さく絞る。
上限を超える写真はここで断り、黙って壊れたページを作らない。
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

import httpx

import auth

# Firestore のドキュメント上限は 1MiB。base64 にすると 4/3 に膨らむので、
# 生バイトの上限はその手前に置く。共有カードに要るのは長辺1200px程度で、
# その範囲なら 300KB に届かない
MAX_PHOTO_BYTES = 700 * 1024
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/gif"}

DB_PATH = Path(os.getenv("IKIMONO_SHARE_DB",
                         str(Path.home() / "data" / "ikimono-note" / "shares.db")))


class PhotoTooLarge(ValueError):
    """写真が Firestore に収まらない。呼び出し側で 413 に変える。"""


class PhotoTypeNotAllowed(ValueError):
    """X が受け取れない形式。webp などはカードに出ないので、ここで断る。"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_token() -> str:
    """推測できない公開URLの名前。128bit あれば総当たりで引かれない。"""
    return secrets.token_urlsafe(16)


# ── Firestore ────────────────────────────────────────────
def _url(token: str = "") -> str:
    base = (f"https://firestore.googleapis.com/v1/projects/{auth.FIRESTORE_PROJECT}"
            f"/databases/(default)/documents/shares")
    return f"{base}/{token}" if token else base


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + auth._google_token()}


def _firestore_put(token: str, record: dict, photo: bytes) -> None:
    fields = {
        "owner": {"stringValue": record["owner"]},
        "created_at": {"stringValue": record["created_at"]},
        "payload": {"stringValue": record["payload"]},
        "photo_type": {"stringValue": record["photo_type"]},
        # bytesValue は base64 で渡す。stringValue に入れると、取り出すときに
        # 文字列として壊れる
        "photo": {"bytesValue": base64.b64encode(photo).decode("ascii")},
    }
    with httpx.Client(timeout=30) as client:
        response = client.patch(_url(token), json={"fields": fields}, headers=_headers())
    response.raise_for_status()


def _firestore_get(token: str) -> tuple[dict, bytes] | None:
    with httpx.Client(timeout=30) as client:
        response = client.get(_url(token), headers=_headers())
    if response.status_code == 404:
        return None
    response.raise_for_status()
    fields = response.json().get("fields", {})
    record = {key: fields.get(key, {}).get("stringValue", "")
              for key in ("owner", "created_at", "payload", "photo_type")}
    raw = fields.get("photo", {}).get("bytesValue", "")
    return record, base64.b64decode(raw) if raw else b""


def _firestore_delete(token: str) -> None:
    with httpx.Client(timeout=15) as client:
        client.delete(_url(token), headers=_headers())


# ── SQLite ──────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("""CREATE TABLE IF NOT EXISTS shares (
        token TEXT PRIMARY KEY,       -- 公開URLの名前。推測できない値
        owner TEXT NOT NULL,          -- 公開した人。取り消せるのはこの人だけ
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL,        -- 候補名・あてはまり度・特徴のJSON
        photo BLOB NOT NULL,
        photo_type TEXT NOT NULL
    )""")
    connection.commit()
    try:
        DB_PATH.chmod(0o600)
    except OSError:
        pass
    return connection


# ── 外向きの口 ────────────────────────────────────────────
def create(owner: str, payload: dict, photo: bytes, photo_type: str) -> str:
    """公開ページを1つ作り、その名前を返す。"""
    if photo_type not in ALLOWED_PHOTO_TYPES:
        raise PhotoTypeNotAllowed(photo_type)
    if not photo or len(photo) > MAX_PHOTO_BYTES:
        raise PhotoTooLarge(str(len(photo)))
    token = new_token()
    record = {"owner": owner, "created_at": _now(),
              "payload": json.dumps(payload, ensure_ascii=False), "photo_type": photo_type}
    if auth.using_firestore():
        _firestore_put(token, record, photo)
        return token
    with _connect() as connection:
        connection.execute(
            "INSERT INTO shares (token, owner, created_at, payload, photo, photo_type)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (token, record["owner"], record["created_at"], record["payload"],
             photo, record["photo_type"]))
    return token


def read(token: str) -> dict | None:
    """公開ページの中身。写真は別に取りに来るので、ここでは返さない。"""
    found = _load(token)
    if not found:
        return None
    record, _ = found
    try:
        payload = json.loads(record["payload"])
    except ValueError:
        return None
    return {"owner": record["owner"], "created_at": record["created_at"], "payload": payload}


def photo(token: str) -> tuple[bytes, str] | None:
    found = _load(token)
    if not found:
        return None
    record, raw = found
    return (raw, record["photo_type"]) if raw else None


def delete(token: str, owner: str) -> bool:
    """取り消し。他人の公開は消せない。"""
    found = _load(token)
    if not found or found[0]["owner"] != owner:
        return False
    if auth.using_firestore():
        _firestore_delete(token)
        return True
    with _connect() as connection:
        connection.execute("DELETE FROM shares WHERE token = ?", (token,))
    return True


def _load(token: str) -> tuple[dict, bytes] | None:
    if not token:
        return None
    if auth.using_firestore():
        return _firestore_get(token)
    with _connect() as connection:
        row = connection.execute(
            "SELECT owner, created_at, payload, photo, photo_type FROM shares WHERE token = ?",
            (token,)).fetchone()
    if not row:
        return None
    return ({"owner": row[0], "created_at": row[1], "payload": row[2], "photo_type": row[4]},
            row[3])
