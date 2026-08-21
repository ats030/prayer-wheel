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


_MODEL_NAME_CACHE: dict[str, str] = {}


def _list_model_names() -> list[str]:
    """サーバーが持っているモデル名を返す。失敗は呼び出し側で握る。"""
    last: Exception | None = None
    for base in _base_urls():
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(base + "/api/tags", headers=_headers(base))
                resp.raise_for_status()
                data = resp.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
    raise OllamaError(f"could not list models: {last}")


def resolve_model(name: str) -> str:
    """設定のモデル名を、サーバーが実際に持っている名前へ寄せる。

    localhost:11434 は Open WebUI 互換のプロキシで、モデル名を一覧と厳密に照合する。
    本物の Ollama は "nomic-embed-text" を ":latest" へ解決するが、このプロキシは
    しないため HTTP 400 "Model 'nomic-embed-text' was not found" になる。実際
    embed() だけがこれで落ち、意味的重複判定が完全一致へ降格していた (ats030-epm5)。
    チャット側は gemma4:31b のようにタグ付きで設定されていたので露見しなかった。

    一覧に無い名前は、前方一致するタグ付きの名前を探す。候補が複数あるときは
    :latest を採り、それも無ければ触らない。勝手に別のモデルを選ばないため。

    解決できない場合は設定値をそのまま返す (fail-soft)。一覧が引けないだけで
    生成を止める理由は無い。
    """
    if name in _MODEL_NAME_CACHE:
        return _MODEL_NAME_CACHE[name]

    resolved = name
    try:
        names = _list_model_names()
    except (OllamaError, Exception) as exc:  # noqa: B014 - fail-soft
        logger.warning("model list unavailable, using %r as-is: %s", name, exc)
        names = []

    if names and name not in names:
        candidates = [n for n in names if n.split(":", 1)[0] == name]
        if len(candidates) == 1:
            resolved = candidates[0]
        elif candidates:
            latest = f"{name}:latest"
            if latest in candidates:
                resolved = latest
        if resolved != name:
            logger.info("resolved model %r -> %r", name, resolved)

    _MODEL_NAME_CACHE[name] = resolved
    return resolved


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
        # チャット側は gemma4:31b のようにタグ付きで設定されているため今のところ
        # 素通りするが、埋め込みと同じ経路に揃えておく (ats030-epm5)。名前が一覧に
        # あるときは何もしない。
        "model": resolve_model(model or settings.model),
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
        "model": resolve_model(model or settings.embed_model),
        "prompt": text,
    })
    vector = data.get("embedding") or []
    if not vector:
        raise OllamaError("empty embedding")
    return vector
