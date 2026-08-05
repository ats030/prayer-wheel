"""Thin Ollama client (chat + JSON + embeddings).

Kept deliberately small: this app only needs "give me JSON" and "give me a
vector". Falls back to Open WebUI's authenticated /ollama proxy when the direct
port is unreachable, the same arrangement writing uses.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from .config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


class OllamaError(RuntimeError):
    pass


def _base_urls() -> list[str]:
    urls = [settings.ollama_url.rstrip("/")]
    if settings.open_webui_url:
        urls.append(settings.open_webui_url.rstrip("/") + "/ollama")
    return [url for url in urls if url]


def _headers(base_url: str) -> dict[str, str]:
    if settings.open_webui_url and base_url.startswith(settings.open_webui_url.rstrip("/")):
        if settings.open_webui_token:
            return {"Authorization": f"Bearer {settings.open_webui_token}"}
    return {}


def _post(path: str, payload: dict) -> dict:
    last: Exception | None = None
    for base in _base_urls():
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(base + path, json=payload, headers=_headers(base))
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Ollama %s failed via %s: %s", path, base, exc)
            last = exc
    raise OllamaError(f"Ollama request failed: {last}")


def available() -> bool:
    for base in _base_urls():
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(base + "/api/tags", headers=_headers(base))
                resp.raise_for_status()
            return True
        except httpx.HTTPError:
            continue
    return False


def generate_json(prompt: str, system: str = "", model: str = "") -> dict | list:
    """Ask for JSON and parse it.

    `format=json` constrains the decoder but does not guarantee the shape, so a
    fenced or prefixed reply is still salvaged before giving up.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = _post("/api/chat", {
        "model": model or settings.model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.3},
    })
    content = (data.get("message") or {}).get("content", "")
    return _parse_json(content)


def _parse_json(content: str) -> dict | list:
    text = (content or "").strip()
    if not text:
        raise OllamaError("empty response")
    try:
        return json.loads(text)
    except ValueError:
        pass
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except ValueError:
            pass
    match = re.search(r"[\[{][\s\S]*[\]}]", text)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            pass
    raise OllamaError(f"could not parse JSON from response: {text[:200]}")


def embed(text: str, model: str = "") -> list[float]:
    data = _post("/api/embeddings", {
        "model": model or settings.embed_model,
        "prompt": text,
    })
    vector = data.get("embedding") or []
    if not vector:
        raise OllamaError("empty embedding")
    return vector
