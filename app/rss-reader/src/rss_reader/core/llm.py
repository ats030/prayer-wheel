"""Ollama client with the response handling used across the other apps.

The previous scorer pulled a score out with ``re.search(r'\\b(\\d+)\\b', text)``.
That silently returned None for "評価は9点です" (Japanese characters are word
characters, so ``\\b`` never matches around the digit) and would have taken the
year out of "In 2026 I rate this 8".

gathering-information/ai_insights.py handles this by asking for JSON, stripping
code fences, extracting the first ``{...}`` block, and retrying once with a
shorter prompt at temperature 0 when parsing fails. Same approach here.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class OllamaError(RuntimeError):
    pass


def base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def default_model() -> str | None:
    for key in ("OLLAMA_SCORE_MODEL", "OLLAMA_MODEL"):
        model = os.environ.get(key, "").strip()
        if model:
            return model
    models = [m.strip() for m in os.environ.get("OLLAMA_MODELS", "").split(",") if m.strip()]
    return models[0] if models else None


def ask(
    prompt: str,
    *,
    model: str | None = None,
    num_predict: int = 400,
    temperature: float = 0.2,
    read_timeout: float = 60.0,
    json_mode: bool = False,
) -> str:
    """Single completion. Returns "" on any failure rather than raising."""
    model = model or default_model()
    if not model:
        return ""
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    if json_mode:
        payload["format"] = "json"
    try:
        import httpx

        resp = httpx.post(
            f"{base_url()}/api/generate",
            json=payload,
            timeout=httpx.Timeout(connect=5, read=read_timeout, write=5, pool=5),
        )
        resp.raise_for_status()
        return (resp.json().get("response") or "").strip()
    except Exception as exc:  # noqa: BLE001 — 採点は落ちてよい機能
        # 上流 (Open WebUI / ollama) が返す 5xx は info だと埋もれる。実際
        # 08-24..08-28 は /api/generate の半数が 502/503 だったのに誰も気付けず、
        # 採点がまるごと空振りしていた (ats030-bnrg)。落ちてよい機能のままだが、
        # 上流障害だけは warning で残す。
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None:
            logger.warning("ollama call failed: HTTP %s (model=%s)", status, model)
        else:
            logger.info("ollama call failed: %s", exc)
        return ""


def parse_object(text: str) -> dict | None:
    """Strip code fences, take the first {...} block, parse it."""
    if not text:
        return None
    cleaned = _FENCE.sub("", text.strip())
    match = _OBJECT.search(cleaned)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def ask_json(
    prompt: str,
    repair_prompt: str | None = None,
    *,
    model: str | None = None,
    num_predict: int = 400,
    temperature: float = 0.2,
    read_timeout: float = 60.0,
) -> dict | None:
    """Ask for JSON; retry once at temperature 0 with a shorter prompt."""
    data = parse_object(
        ask(prompt, model=model, num_predict=num_predict, temperature=temperature,
            read_timeout=read_timeout, json_mode=True)
    )
    if data is not None:
        return data
    if repair_prompt is None:
        return None
    return parse_object(
        ask(repair_prompt, model=model, num_predict=max(120, num_predict // 2),
            temperature=0.0, read_timeout=read_timeout, json_mode=True)
    )


def clamp_score(value: object, *, low: int = 1, high: int = 5, default: int = 3) -> int:
    """writing/evaluate.py の _clamp_score と同じ契約：範囲外は捨てず丸める。"""
    try:
        score = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, score))


def health() -> bool:
    try:
        import httpx

        resp = httpx.get(f"{base_url()}/api/tags", timeout=httpx.Timeout(3.0))
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False
