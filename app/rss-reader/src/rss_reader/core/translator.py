import json
import logging
import os
import re
from hashlib import sha256

from ..config import CACHE_DIR

logger = logging.getLogger(__name__)

_cache = None


def _get_cache():
    global _cache
    if _cache is None:
        import diskcache

        _cache = diskcache.Cache(str(CACHE_DIR))
    return _cache

_TRANSLATE_PROMPT = """\
RSS記事のタイトルと要約を、自然な日本語に翻訳してください。

ルール:
- 固有名詞、製品名、会社名、バージョン番号、URLは無理に訳さない
- 要約は原文の意味を保ち、短く読みやすい日本語にする
- 余計な説明、Markdown、コードブロックは出力しない
- 入力と同じ id を持つ JSON 配列だけを出力する
- 各要素は id, title, summary を持つ

入力:
{items_json}

出力:"""


def translate_items_to_japanese(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not items:
        return []
    if os.environ.get("RSS_TRANSLATE_TO_JA", "0").strip().lower() in {"0", "false", "no"}:
        return items

    model = _get_model()
    if not model:
        return items

    results: list[tuple[str, str] | None] = [None] * len(items)
    pending: list[tuple[int, str, str]] = []
    cache = _get_cache()
    for idx, (title, summary) in enumerate(items):
        if _looks_japanese(title) and (not summary or _looks_japanese(summary)):
            results[idx] = (title, summary)
            continue

        cached = cache.get(_cache_key(title, summary))
        if cached:
            results[idx] = cached
        else:
            pending.append((idx, title, summary))

    for chunk in _chunks(pending, 10):
        translated = _request_translation(model, chunk)
        for idx, original_title, original_summary in chunk:
            if idx not in translated:
                # 上流が落ちているときに原文をそのまま 30 日キャッシュすると、
                # 復旧後も未翻訳のまま固定される (ats030-bnrg)。失敗は残さず、
                # 次回の呼び出しでやり直させる。
                results[idx] = (original_title, original_summary)
                continue
            title, summary = translated[idx]
            results[idx] = (title, summary)
            cache.set(
                _cache_key(original_title, original_summary),
                (title, summary),
                expire=86400 * 30,
            )

    return [result if result is not None else items[idx] for idx, result in enumerate(results)]


def _get_model() -> str | None:
    model = os.environ.get("OLLAMA_TRANSLATE_MODEL", "").strip()
    if model:
        return model
    models_str = os.environ.get("OLLAMA_MODELS", "")
    models = [m.strip() for m in models_str.split(",") if m.strip()]
    return models[0] if models else None


def _looks_japanese(text: str) -> bool:
    if not text:
        return True
    ja_chars = len(re.findall(r"[ぁ-んァ-ヶ一-龠々]", text))
    alpha_words = len(re.findall(r"\b[A-Za-z]{3,}\b", text))
    return ja_chars >= 8 and ja_chars >= alpha_words


def _cache_key(title: str, summary: str) -> str:
    digest = sha256(f"{title}\0{summary}".encode("utf-8")).hexdigest()
    return f"ja_translate:{digest}"


def _chunks(
    items: list[tuple[int, str, str]],
    size: int,
) -> list[list[tuple[int, str, str]]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _request_translation(
    model: str,
    items: list[tuple[int, str, str]],
) -> dict[int, tuple[str, str]]:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    payload = [
        {"id": idx, "title": title, "summary": summary}
        for idx, title, summary in items
    ]
    prompt = _TRANSLATE_PROMPT.format(items_json=json.dumps(payload, ensure_ascii=False))

    try:
        import httpx

        resp = httpx.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=httpx.Timeout(connect=5, read=60, write=5, pool=5),
        )
        resp.raise_for_status()
        return _parse_response(resp.json().get("response", ""))
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning("translator: %s failed (%s)", model, status or exc)
        return {}


def _parse_response(text: str) -> dict[int, tuple[str, str]]:
    data = _load_json(text)
    if isinstance(data, dict):
        for key in ("items", "translations", "result", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return {}

    result: dict[int, tuple[str, str]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if title or summary:
            result[idx] = (title, summary)
    return result


def _load_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
