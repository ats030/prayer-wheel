"""Google アカウントでのログイン。

パスワードは持たない。自分で預かると、ハッシュの選定、リセット導線、漏洩時の
対応まで抱えることになり、個人で運用するには重すぎる。Google に任せれば、
本サービスが持つのは「どのアカウントか」を指す識別子だけで済む。

サーバーが保存するのはユーザーの識別子とメールアドレス、それに作成日時だけ。
写真も記録も設定もAPIキーも、これまでどおり利用者の側に置いたままにする。
ログインしても、それらがサーバーへ移ることはない。

ログインは任意。していなくても、これまでどおり使える。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

CLIENT_ID = os.getenv("IKIMONO_GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("IKIMONO_GOOGLE_CLIENT_SECRET", "").strip()
# 公開URL。リダイレクト先の組み立てに使う (Google 側の登録と一致している必要がある)
PUBLIC_ORIGIN = os.getenv("IKIMONO_PUBLIC_ORIGIN", "").strip().rstrip("/")

# 消えるとログイン中の全員がログアウトするだけなので、無ければその場で作る。
# 固定したい場合は環境変数で渡す。
SESSION_SECRET = os.getenv("IKIMONO_SESSION_SECRET", "").strip() or secrets.token_hex(32)
SESSION_COOKIE = "ikimono_session"
SESSION_DAYS = 30

DB_PATH = Path(os.getenv("IKIMONO_USER_DB", str(Path.home() / "data" / "ikimono-note" / "users.db")))


def configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET and PUBLIC_ORIGIN)


def unavailable_reason() -> str:
    if not CLIENT_ID:
        return "IKIMONO_GOOGLE_CLIENT_ID が未設定です"
    if not CLIENT_SECRET:
        return "IKIMONO_GOOGLE_CLIENT_SECRET が未設定です"
    if not PUBLIC_ORIGIN:
        return "IKIMONO_PUBLIC_ORIGIN が未設定です"
    return ""


def redirect_uri() -> str:
    return PUBLIC_ORIGIN + "/auth/callback"


# ── 保管 ────────────────────────────────────────────────
# 置き場は2通り。手元では SQLite ファイル、Cloud Run では Firestore。
# Cloud Run はリクエストごとにインスタンスが入れ替わるので、ファイルに書いても
# 次の呼び出しでは消えている。利用者の登録が残らないと、いつから使っている人か
# 分からなくなり、課金も載せられない。
#
# Firestore は REST で叩く。google-cloud-firestore は grpc まで連れてきて、
# 5個で済んでいる依存が一気に増える。ここで使うのは1コレクションへの読み書きだけ。
FIRESTORE_PROJECT = os.getenv("IKIMONO_FIRESTORE_PROJECT", "").strip()
_METADATA_TOKEN = ("http://metadata.google.internal/computeMetadata/v1/"
                   "instance/service-accounts/default/token")


def using_firestore() -> bool:
    return bool(FIRESTORE_PROJECT)


def _google_token() -> str:
    """Cloud Run の中では、メタデータサーバーが鍵を貸してくれる。鍵ファイルを置かない。"""
    response = httpx.get(_METADATA_TOKEN, headers={"Metadata-Flavor": "Google"}, timeout=10)
    response.raise_for_status()
    return response.json()["access_token"]


def _firestore_url(subject: str = "") -> str:
    base = (f"https://firestore.googleapis.com/v1/projects/{FIRESTORE_PROJECT}"
            f"/databases/(default)/documents/users")
    return f"{base}/{subject}" if subject else base


def _to_fields(values: dict[str, str]) -> dict:
    return {"fields": {k: {"stringValue": v} for k, v in values.items()}}


def _from_fields(document: dict) -> dict[str, str]:
    fields = document.get("fields", {})
    return {k: v.get("stringValue", "") for k, v in fields.items()}


def _firestore_get(subject: str) -> dict[str, str] | None:
    with httpx.Client(timeout=15) as client:
        response = client.get(_firestore_url(subject),
                              headers={"Authorization": "Bearer " + _google_token()})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return _from_fields(response.json())


def _firestore_put(subject: str, values: dict[str, str]) -> None:
    with httpx.Client(timeout=15) as client:
        response = client.patch(_firestore_url(subject), json=_to_fields(values),
                                headers={"Authorization": "Bearer " + _google_token()})
    response.raise_for_status()


# 広告の数え。利用者の記録とは別の入れ物に置く。
#
# 以前は settings.json に足していたが、Cloud Run にはディスクが無く、インスタンスが
# 入れ替わるたびに 0 に戻っていた。数えていたつもりで、何も残っていなかった。
# 商品APIの資格 (直近30日で適格販売10件) まであとどれくらいかを見るには、
# クリックが実際に起きているかどうかが要る。
_METRICS_DOC = "affiliate"


def _metrics_path() -> str:
    """Firestore の資源名。URL ではなく、この形で書き込みに渡す。"""
    return f"projects/{FIRESTORE_PROJECT}/databases/(default)/documents/metrics/{_METRICS_DOC}"


def _metrics_url() -> str:
    return "https://firestore.googleapis.com/v1/" + _metrics_path()


def bump_metric(field: str, amount: int = 1) -> None:
    """1つ増やす。読んで足して書くと、同時に押されたぶんが落ちるので transform を使う。"""
    commit = (f"https://firestore.googleapis.com/v1/projects/{FIRESTORE_PROJECT}"
              f"/databases/(default)/documents:commit")
    body = {"writes": [{
        # 空の update と空の mask で、無ければ作る。あれば何も変えない
        "update": {"name": _metrics_path(), "fields": {}},
        "updateMask": {"fieldPaths": []},
        "updateTransforms": [{"fieldPath": field,
                              "increment": {"integerValue": str(int(amount))}}],
    }]}
    with httpx.Client(timeout=15) as client:
        response = client.post(commit, json=body,
                               headers={"Authorization": "Bearer " + _google_token()})
    response.raise_for_status()


def read_metrics() -> dict[str, int]:
    with httpx.Client(timeout=15) as client:
        response = client.get(_metrics_url(),
                              headers={"Authorization": "Bearer " + _google_token()})
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    fields = response.json().get("fields", {})
    return {k: int(v.get("integerValue", 0)) for k, v in fields.items() if "integerValue" in v}


def _firestore_delete(subject: str) -> None:
    with httpx.Client(timeout=15) as client:
        client.delete(_firestore_url(subject),
                      headers={"Authorization": "Bearer " + _google_token()})


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("""CREATE TABLE IF NOT EXISTS users (
        subject TEXT PRIMARY KEY,          -- Google の一意ID。メールは変わりうるので、これを鍵にする
        email TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        plan TEXT NOT NULL DEFAULT 'free'  -- 課金を入れるときの置き場
    )""")
    connection.commit()
    try:
        DB_PATH.chmod(0o600)
    except OSError:
        pass
    return connection


def upsert_user(subject: str, email: str) -> dict[str, str]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if using_firestore():
        existing = _firestore_get(subject) or {}
        record = {"subject": subject, "email": email,
                  "created_at": existing.get("created_at") or now, "last_seen_at": now,
                  "plan": existing.get("plan") or "free"}
        _firestore_put(subject, record)
        return record
    with _connect() as connection:
        connection.execute(
            """INSERT INTO users (subject, email, created_at, last_seen_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(subject) DO UPDATE SET email=excluded.email, last_seen_at=excluded.last_seen_at""",
            (subject, email, now, now))
        row = connection.execute(
            "SELECT subject, email, created_at, plan FROM users WHERE subject = ?", (subject,)).fetchone()
    return {"subject": row[0], "email": row[1], "created_at": row[2], "plan": row[3]}


def find_user(subject: str) -> dict[str, str] | None:
    if using_firestore():
        return _firestore_get(subject)
    with _connect() as connection:
        row = connection.execute(
            "SELECT subject, email, created_at, plan FROM users WHERE subject = ?", (subject,)).fetchone()
    return {"subject": row[0], "email": row[1], "created_at": row[2], "plan": row[3]} if row else None


def delete_user(subject: str) -> None:
    """退会。持っているものが少ないので、消すのも一行で済む。"""
    if using_firestore():
        _firestore_delete(subject)
        return
    with _connect() as connection:
        connection.execute("DELETE FROM users WHERE subject = ?", (subject,))


# ── セッション ──────────────────────────────────────────
# 署名付きクッキー。サーバー側にセッション表を持たない。

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_session(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return body + "." + _b64(signature)


def read_session(cookie: str | None) -> dict | None:
    if not cookie or "." not in cookie:
        return None
    body, _, signature = cookie.partition(".")
    expected = hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64(expected), signature):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def session_for(user: dict) -> str:
    return sign_session({"sub": user["subject"], "email": user["email"],
                         "exp": int(time.time()) + SESSION_DAYS * 86400})


# ── OpenID Connect ─────────────────────────────────────
# 認可コード + PKCE。state と nonce で、他人に始めさせられた流れを弾く。

def start_login() -> tuple[str, dict[str, str]]:
    verifier = secrets.token_urlsafe(64)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    query = urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email",          # 名前も写真も要らない。メールだけ
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{GOOGLE_AUTH_URL}?{query}", {"state": state, "nonce": nonce, "verifier": verifier}


class AuthError(RuntimeError):
    pass


def _claims_from_id_token(id_token: str, nonce: str) -> dict:
    """Google から直に受け取った応答なので、署名の再検証はしない。

    ここへ来る id_token は、こちらから oauth2.googleapis.com へ TLS で問い合わせた
    応答の中身であって、ブラウザ越しに渡されたものではない。ブラウザ経由で受け取る
    場合と違い、差し替える余地がない (OpenID Connect Core 3.1.3.7 の但し書きと同じ状況)。
    それでも発行者と宛先と nonce は確かめる。
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise AuthError("Google の応答を読み取れませんでした")
    try:
        claims = json.loads(_unb64(parts[1]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Google の応答を読み取れませんでした") from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise AuthError("Google の応答ではありませんでした")
    if claims.get("aud") != CLIENT_ID:
        raise AuthError("別のアプリ向けの応答でした")
    if claims.get("nonce") != nonce:
        raise AuthError("ログインの流れが途中で入れ替わりました。もう一度お試しください")
    if claims.get("exp", 0) < time.time():
        raise AuthError("ログインの有効期限が切れました。もう一度お試しください")
    if not claims.get("email"):
        raise AuthError("メールアドレスを取得できませんでした")
    return claims


def finish_login(code: str, verifier: str, nonce: str) -> dict[str, str]:
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            })
    except httpx.HTTPError as exc:
        raise AuthError("Google へ問い合わせできませんでした") from exc
    if response.status_code != 200:
        raise AuthError("Google がログインを認めませんでした")
    id_token = response.json().get("id_token", "")
    if not id_token:
        raise AuthError("Google の応答にログイン情報がありませんでした")
    claims = _claims_from_id_token(id_token, nonce)
    return upsert_user(claims["sub"], claims["email"])
