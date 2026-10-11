"""Public API boundary; never import the private server or open its database.

Sessions may be issued only by a server-side, verified identity-provider callback.
There is deliberately no HTTP session-minting endpoint or trusted owner header.
All state is process-local: logout and restart invalidate sessions immediately.
"""
from dataclasses import dataclass
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import json
import os
import re
import secrets
import threading
import time
from urllib.parse import unquote, urlsplit
from trial import ReceiptGone

COOKIE = "__Host-timeline_session"
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
RECEIPT = re.compile(r"[A-Za-z0-9_-]{16,64}")
RESULT_BYTES = 512 * 1024


class PublicError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


def https_origin(value):
    try:
        p = urlsplit(value)
        valid = (p.scheme == "https" and p.hostname and not p.username and not p.password
                 and p.path in ("", "/") and not p.query and not p.fragment
                 and p.port in (None, 443) and re.fullmatch(r"https://[A-Za-z0-9.\[\]:-]+/?", value))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("A fixed HTTPS public origin is required")
    hostname = p.hostname
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"https://{host}"


@dataclass(frozen=True)
class Session:
    owner: str
    csrf: str
    expires: float


class PublicBoundary:
    def __init__(self, origin, owner_key, issuer, *, ttl=3600, capacity=1000, clock=time.monotonic):
        self.origin = https_origin(origin)
        self.host = urlsplit(self.origin).netloc
        if not isinstance(owner_key, bytes) or len(owner_key) < 32:
            raise ValueError("An operator-owned random key of at least 32 bytes is required")
        if not isinstance(issuer, str) or not issuer or len(issuer) > 200:
            raise ValueError("An explicit identity-provider issuer is required")
        if type(ttl) is not int or not 60 <= ttl <= 3600 or type(capacity) is not int or not 1 <= capacity <= 10000:
            raise ValueError("Invalid session limits")
        self.key, self.issuer, self.ttl, self.capacity, self.clock = owner_key, issuer, ttl, capacity, clock
        self.sessions = {}
        self.lock = threading.Lock()

    @classmethod
    def from_env(cls, issuer):
        # Do not let a public service silently reuse the private SearXNG route.
        if os.environ.get("TIMELINE_SOURCE") != "wikipedia":
            raise ValueError("Public generation requires TIMELINE_SOURCE=wikipedia")
        key = os.environ.get("TIMELINE_PUBLIC_OWNER_KEY", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
            raise ValueError("TIMELINE_PUBLIC_OWNER_KEY must contain 32 random bytes as hex")
        return cls(os.environ.get("TIMELINE_PUBLIC_ORIGIN", ""), bytes.fromhex(key), issuer)

    def prune(self):
        now = self.clock()
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires > now}

    def issue_verified(self, issuer, subject, *, replace_token=None):
        """Internal callback only: caller MUST have verified the provider response.

        This is not a token verifier; never pass client-provided claims into it.
        A stable pseudonymous owner survives logout/restart without storing emails.
        """
        if issuer != self.issuer or not isinstance(subject, str) or not 1 <= len(subject) <= 255:
            raise PublicError(401, "authentication_required")
        owner = hmac.new(self.key, json.dumps([issuer, subject], separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        token = secrets.token_urlsafe(32)
        session = Session(owner, secrets.token_urlsafe(32), self.clock() + self.ttl)
        if replace_token is not None and (not isinstance(replace_token, str) or not TOKEN.fullmatch(replace_token)):
            raise ValueError("Invalid replacement token")
        previous = hashlib.sha256(replace_token.encode()).digest() if replace_token else None
        key = hashlib.sha256(token.encode()).digest()
        with self.lock:
            self.prune()
            if key in self.sessions or (len(self.sessions) >= self.capacity and previous not in self.sessions):
                raise PublicError(503, "session_capacity")
            # Atomic rotation: do not discard the old session unless insertion
            # succeeds, and do not reject a replacement at full capacity.
            self.sessions[key] = session
            if previous is not None:
                self.sessions.pop(previous, None)
        return token, session

    @staticmethod
    def cookie(token, ttl):
        if token and not TOKEN.fullmatch(token):
            raise ValueError("Invalid session token")
        return f"{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={ttl}"

    def check_origin(self, headers, *, write=False):
        # Exact configured Host, never a client-provided X-Forwarded-* value.
        if hasattr(headers, "get_all") and any(len(headers.get_all(name, [])) > 1 for name in
                ("Host", "Origin", "Cookie", "X-CSRF-Token", "Sec-Fetch-Site")):
            raise PublicError(403, "origin_rejected")
        if headers.get("Host") != self.host:
            raise PublicError(403, "origin_rejected")
        origin = headers.get("Origin")
        if (write and origin != self.origin) or (origin is not None and origin != self.origin):
            raise PublicError(403, "origin_rejected")
        if not write and headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            raise PublicError(403, "origin_rejected")

    def token(self, headers):
        raw = headers.get("Cookie", "")
        # Reject ambiguous duplicate cookies instead of relying on parser order.
        if len(raw) > 8192 or sum(part.strip().split("=", 1)[0] == COOKIE for part in raw.split(";")) != 1:
            raise PublicError(401, "authentication_required")
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
            token = cookie[COOKIE].value
        except (CookieError, KeyError):
            raise PublicError(401, "authentication_required") from None
        if not TOKEN.fullmatch(token):
            raise PublicError(401, "authentication_required")
        return token

    def authorize(self, headers, *, write=False):
        self.check_origin(headers, write=write)
        token = self.token(headers)
        with self.lock:
            self.prune()
            session = self.sessions.get(hashlib.sha256(token.encode()).digest())
        if session is None:
            raise PublicError(401, "authentication_required")
        csrf = headers.get("X-CSRF-Token", "")
        if write and (not isinstance(csrf, str) or not hmac.compare_digest(csrf.encode(), session.csrf.encode())):
            raise PublicError(403, "csrf_rejected")
        return session

    def logout(self, headers):
        self.authorize(headers, write=True)
        with self.lock:
            self.sessions.pop(hashlib.sha256(self.token(headers).encode()).digest(), None)
        return self.cookie("", 0)

    def session_view(self, headers):
        session = self.authorize(headers)
        return {"authenticated": True, "csrf_token": session.csrf,
                "expires_in": max(0, int(session.expires - self.clock()))}

    def receipt(self, ledger, headers, receipt_id, *, cancel=False):
        session = self.authorize(headers, write=cancel)
        if not isinstance(receipt_id, str) or not RECEIPT.fullmatch(receipt_id):
            raise PublicError(404, "receipt_not_found")
        # Owner is always derived from the authenticated session, never the body.
        try:
            row = (ledger.cancel if cancel else ledger.get)(session.owner, receipt_id)
        except ReceiptGone:
            raise PublicError(410, "receipt_gone") from None
        except ValueError:
            if cancel:
                raise PublicError(409, "receipt_state") from None
            raise
        if row is None or row.get("owner") != session.owner:
            raise PublicError(404, "receipt_not_found")
        return receipt_view(row)


def text(value, maximum, optional=False):
    if optional and value is None:
        return ""
    if (not isinstance(value, str) or len(value) > maximum or (not optional and not value.strip())
            or re.search(r"[\ud800-\udfff]", value)):
        raise PublicError(502, "invalid_result")
    return value


def source_url(value):
    value = text(value, 2000)
    try:
        p = urlsplit(value)
        valid = (p.scheme == "https" and p.hostname in {"ja.wikipedia.org", "en.wikipedia.org"}
                 and not p.username and not p.password and p.port in (None, 443)
                 and p.path.startswith("/wiki/") and len(p.path) > 6 and not p.query
                 and not re.search(r"[\x00-\x20\x7f\\]", unquote(value)))
    except ValueError:
        valid = False
    if not valid:
        raise PublicError(502, "invalid_result")
    return value


def result_view(result):
    """Whitelist a server-generated result, NOT an uploaded source_mode assertion."""
    if (not isinstance(result, dict) or result.get("kind") != "result"
            or result.get("source_mode") != "wikipedia" or not isinstance(result.get("events"), list)
            or not 1 <= len(result["events"]) <= 50):
        raise PublicError(502, "invalid_result")
    events = []
    for event in result["events"]:
        if not isinstance(event, dict) or type(event.get("year")) is not int or abs(event["year"]) > 1000000:
            raise PublicError(502, "invalid_result")
        source = event.get("source")
        if not isinstance(source, dict):
            raise PublicError(502, "invalid_result")
        events.append({"year": event["year"], "date": text(event.get("date"), 120),
                       "title": text(event.get("title"), 300), "description": text(event.get("description"), 4000, True),
                       "source": {"url": source_url(source.get("url")), "title": text(source.get("title"), 500)}})
    period = "全期間" if result.get("period") is None else result["period"]
    output = {"theme": text(result.get("theme"), 180), "period": text(period, 180),
              "source_mode": "wikipedia", "notice": text(result.get("notice"), 4000, True), "events": events}
    if len(json.dumps(output, ensure_ascii=False).encode()) > RESULT_BYTES:
        raise PublicError(502, "invalid_result")
    return output


def receipt_view(row):
    # The public receipt ID is needed to retrieve/cancel; SQLite seq/owner/targets are private.
    output = {key: row[key] for key in ("receipt_id", "state", "accepted_at", "updated_at", "expires_at") if key in row}
    if "result" in row:
        output["result"] = result_view(row["result"])
    return output
