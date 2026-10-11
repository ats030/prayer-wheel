"""Google authorization-code server flow. No browser-supplied ID tokens.

Only the token response fetched directly from Google's pinned HTTPS endpoint is
decoded here. Google documents that this client-secret-authenticated, direct TLS
response is trusted without separate signature verification. This does NOT apply
to tokens supplied by a browser or passed to another component; neither is allowed.
https://developers.google.com/identity/openid-connect/openid-connect
"""
import base64
from dataclasses import dataclass
import hashlib
import hmac
from http.cookies import CookieError, SimpleCookie
import json
import os
import re
import secrets
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from public_security import PublicBoundary, PublicError, TOKEN

# Pinned to the official discovery document retrieved 2026-10-11. Endpoint
# changes require review; no client URL or provider URL can redirect secrets.
ISSUER = "https://accounts.google.com"
AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
LOGIN_COOKIE = "__Host-timeline_login"
CALLBACK = "/auth/google/callback"
PENDING_TTL = 600
MAX_RESPONSE = 64 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def google_exchange(fields):
    """Private transport seam for offline tests; production always uses Google TLS."""
    request = Request(TOKEN_ENDPOINT, data=urlencode(fields).encode(),
                      headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    # Do not send secrets through HTTP(S)_PROXY or follow a credential-bearing redirect.
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            if response.status != 200 or response.geturl() != TOKEN_ENDPOINT:
                raise PublicError(502, "google_unavailable")
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise PublicError(502, "google_unavailable")
            value = json.loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("id_token"), str):
            raise PublicError(502, "google_unavailable")
        return value["id_token"]
    except HTTPError as exc:
        exc.close()
        raise PublicError(502, "google_unavailable") from None
    except (URLError, OSError, ValueError):
        raise PublicError(502, "google_unavailable") from None


def json_segment(segment):
    if not isinstance(segment, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise ValueError("Invalid token encoding")
    value = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    if not isinstance(value, dict):
        raise ValueError("Invalid token claims")
    return value


@dataclass(frozen=True, repr=False)
class Pending:
    binding_hash: bytes
    nonce: str
    verifier: str
    expires: float


class GoogleLogin:
    def __init__(self, boundary, client_id, client_secret, *, exchange=google_exchange,
                 clock=time.monotonic, wall_clock=time.time, capacity=1000):
        if boundary.issuer != ISSUER:
            raise ValueError("Google issuer is required")
        if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", client_id):
            raise ValueError("Google web client ID is required")
        if not isinstance(client_secret, str) or not 8 <= len(client_secret) <= 512 or re.search(r"[\s\x00-\x1f]", client_secret):
            raise ValueError("Google client secret is required")
        if type(capacity) is not int or not 1 <= capacity <= 10000:
            raise ValueError("Invalid login capacity")
        self.boundary, self.client_id, self.client_secret = boundary, client_id, client_secret
        self.redirect_uri = boundary.origin + CALLBACK
        self.exchange, self.clock, self.wall_clock, self.capacity = exchange, clock, wall_clock, capacity
        self.pending = {}
        self.lock = threading.Lock()

    @classmethod
    def from_env(cls):
        # This explicit deployment assertion is not a substitute for the review:
        # see tool-license.yaml. With no configured/reviewed client, startup fails.
        if os.environ.get("TIMELINE_GOOGLE_CLIENT_REVIEWED") != "1":
            raise ValueError("Review the configured Google client before public startup")
        return cls(PublicBoundary.from_env(ISSUER), os.environ.get("TIMELINE_GOOGLE_CLIENT_ID", ""),
                   os.environ.get("TIMELINE_GOOGLE_CLIENT_SECRET", ""))

    @staticmethod
    def cookie(value, ttl=PENDING_TTL):
        return f"{LOGIN_COOKIE}={value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={ttl}"

    def _prune(self):
        now = self.clock()
        self.pending = {key: value for key, value in self.pending.items() if value.expires > now}

    def begin(self, headers):
        # Start only on an explicit same-origin POST, not a cross-site GET/link.
        self.boundary.check_origin(headers, write=True)
        state, binding, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        with self.lock:
            self._prune()
            if len(self.pending) >= self.capacity:
                raise PublicError(503, "login_capacity")
            self.pending[hashlib.sha256(state.encode()).digest()] = Pending(
                hashlib.sha256(binding.encode()).digest(), nonce, verifier, self.clock() + PENDING_TTL)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        url = AUTHORIZE + "?" + urlencode({"client_id": self.client_id, "response_type": "code",
            "scope": "openid", "redirect_uri": self.redirect_uri, "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "online"})
        return url, self.cookie(binding)

    def _callback_pending(self, headers, query):
        # A Google top-level redirect is cross-site. Do not apply the normal
        # GET Fetch-Site guard here: pinned Host + browser-bound state protect it.
        if hasattr(headers, "get_all") and any(len(headers.get_all(name, [])) > 1 for name in ("Host", "Origin", "Cookie")):
            raise PublicError(403, "login_state")
        if headers.get("Host") != self.boundary.host or headers.get("Origin") not in (None, self.boundary.origin):
            raise PublicError(403, "login_state")
        try:
            if len(query) > 4096:
                raise ValueError
            params = parse_qs(query, keep_blank_values=True, max_num_fields=16)
            if any(len(params.get(name, [])) != 1 for name in ("state",)) or any(
                    len(params.get(name, [])) > 1 for name in ("code", "error")):
                raise ValueError
            state = params["state"][0]
            raw = headers.get("Cookie", "")
            if not TOKEN.fullmatch(state) or len(raw) > 8192 or sum(
                    part.strip().split("=", 1)[0] == LOGIN_COOKIE for part in raw.split(";")) != 1:
                raise ValueError
            cookies = SimpleCookie()
            cookies.load(raw)
            binding = cookies[LOGIN_COOKIE].value
            if not TOKEN.fullmatch(binding):
                raise ValueError
        except (ValueError, KeyError, CookieError):
            raise PublicError(403, "login_state") from None
        key = hashlib.sha256(state.encode()).digest()
        with self.lock:
            self._prune()
            pending = self.pending.get(key)
            if pending is None or not hmac.compare_digest(pending.binding_hash, hashlib.sha256(binding.encode()).digest()):
                raise PublicError(403, "login_state")
            # Consume before code exchange. Retries/racing callbacks cannot issue twice.
            del self.pending[key]
        if "error" in params:
            raise PublicError(401, "login_cancelled" if params["error"][0] == "access_denied" else "login_failed")
        code = params.get("code", [""])[0]
        if not code or len(code) > 2048 or re.search(r"[\x00-\x20\x7f]", code):
            raise PublicError(403, "login_state")
        return code, pending

    def finish(self, headers, query):
        code, pending = self._callback_pending(headers, query)
        token = self.exchange({"client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code", "code": code,
            "code_verifier": pending.verifier})
        # Token origin is trusted only through the direct server-to-Google TLS
        # response above. No path accepts a credential/id_token from the browser.
        try:
            if not isinstance(token, str) or len(token) > 16384:
                raise ValueError
            header, payload, signature = token.split(".")
            if json_segment(header).get("alg") != "RS256" or not re.fullmatch(r"[A-Za-z0-9_-]+", signature):
                raise ValueError
            claims = json_segment(payload)
            now = self.wall_clock()
            if (claims.get("iss") not in (ISSUER, "accounts.google.com") or claims.get("aud") != self.client_id
                    or claims.get("azp", self.client_id) != self.client_id
                    or type(claims.get("exp")) is not int or claims["exp"] <= now
                    or type(claims.get("iat")) is not int or claims["iat"] > now + 60
                    or claims["exp"] <= claims["iat"] or claims.get("nonce") != pending.nonce
                    or ("nbf" in claims and (type(claims["nbf"]) is not int or claims["nbf"] > now))
                    or not isinstance(claims.get("sub"), str) or not re.fullmatch(r"[\x21-\x7e]{1,255}", claims["sub"])):
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise PublicError(401, "login_failed") from None
        # Only the verified subject leaves this module. Tokens/email/name do not.
        # Rotate an existing browser session after successful re-authentication.
        try:
            old = self.boundary.token(headers)
        except PublicError:
            old = None
        session_token, _ = self.boundary.issue_verified(ISSUER, claims["sub"], replace_token=old)
        return self.boundary.cookie(session_token, self.boundary.ttl), self.cookie("", 0)
