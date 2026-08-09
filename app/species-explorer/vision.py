"""In-memory image preparation and local VLM identification."""

from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Any

import httpx
from PIL import Image, ImageOps

MODEL = os.getenv("SPECIES_MODEL", "gemma4:12b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OPENAI_MODEL = os.getenv("SPECIES_OPENAI_MODEL", "gpt-5.6-luna")
OPENAI_URL = os.getenv("SPECIES_OPENAI_URL", "https://api.openai.com/v1/responses")
ANTHROPIC_MODEL = os.getenv("SPECIES_ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_URL = os.getenv("SPECIES_ANTHROPIC_URL", "https://api.anthropic.com/v1/messages")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_EDGE = 1600

PROMPT = """あなたは野外観察を補助する生物識別アシスタントです。添付写真に写る主要な植物または動物を観察してください。
次のJSONだけを返してください。
{
  "category": "植物" | "動物" | "不明",
  "summary": "写真から確実に観察できることを1文で",
  "candidates": [
    {
      "common_name_ja": "日本語名",
      "scientific_name": "学名または空文字",
      "confidence": 0から100の整数,
      "traits": ["写真で確認できる特徴を最大3件"],
      "uncertainty": "似た種との区別に必要な追加観察"
    }
  ]
}
規則:
- 候補は可能性が高い順に最大3件。種まで判断できなければ属・科レベルに留める。
- confidenceは画像だけからの識別確度であり、合計100にする必要はない。
- 写真に生物が見えない、または判定材料が足りなければ category を不明、candidatesを空配列にする。
- 食用、毒性、安全性、治療について断定しない。
- 位置、季節、撮影者の説明など、与えられていない情報を作らない。
- Markdownや説明文を付けない。"""


class VisionError(RuntimeError):
    pass


def prepare_image(raw: bytes) -> bytes:
    if not raw:
        raise VisionError("画像が空です")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise VisionError("画像は15MB以下にしてください")
    try:
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        image.load()
    except Exception as exc:
        raise VisionError("対応している画像を選んでください") from exc
    if image.mode != "RGB":
        image = image.convert("RGB")
    if max(image.size) > MAX_EDGE:
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    # Re-encoding deliberately strips EXIF, including embedded location data.
    image.save(output, "JPEG", quality=86, optimize=True)
    return output.getvalue()


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise VisionError("AIの応答を読み取れませんでした")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VisionError("AIの応答を読み取れませんでした") from exc
    if not isinstance(data, dict):
        raise VisionError("AIの応答形式が不正です")
    return data


def normalize(data: dict[str, Any], *, model: str = MODEL, provider: str = "local") -> dict[str, Any]:
    category = data.get("category") if data.get("category") in {"植物", "動物", "不明"} else "不明"
    candidates = []
    for item in (data.get("candidates") or [])[:3]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("common_name_ja") or "").strip()
        if not name:
            continue
        try:
            confidence = max(0, min(100, int(item.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0
        traits = [str(v).strip() for v in (item.get("traits") or []) if str(v).strip()][:3]
        candidates.append({
            "common_name_ja": name,
            "scientific_name": str(item.get("scientific_name") or "").strip(),
            "confidence": confidence,
            "traits": traits,
            "uncertainty": str(item.get("uncertainty") or "").strip(),
        })
    return {
        "category": category,
        "summary": str(data.get("summary") or "").strip(),
        "candidates": candidates,
        "model": model,
        "provider": provider,
        "image_saved": False,
    }


def identify(image_bytes: bytes) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": PROMPT,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
        }],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": 1200},
    }
    try:
        response = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
        response.raise_for_status()
        content = response.json()["message"]["content"]
    except httpx.HTTPStatusError as exc:
        raise VisionError(f"ローカルAIがエラーを返しました（{exc.response.status_code}）") from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise VisionError("ローカルAIに接続できませんでした") from exc
    return normalize(_extract_json(content))


def _provider_error(provider: str, exc: httpx.HTTPStatusError) -> VisionError:
    status = exc.response.status_code
    if status in {401, 403}:
        return VisionError(f"{provider}のAPIキーを確認してください")
    if status == 429:
        return VisionError(f"{provider}の利用上限またはレート制限に達しました")
    return VisionError(f"{provider} APIで識別できませんでした（{status}）")


def _openai_output_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    texts = []
    for output in data.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                texts.append(str(content.get("text") or ""))
    if not texts:
        raise VisionError("OpenAIの応答を読み取れませんでした")
    return "\n".join(texts)


def identify_openai(image_bytes: bytes, api_key: str) -> dict[str, Any]:
    image_data = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": OPENAI_MODEL,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_data}"},
                {"type": "input_text", "text": PROMPT},
            ],
        }],
        "reasoning": {"effort": "low"},
    }
    try:
        response = httpx.post(
            OPENAI_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=180,
        )
        response.raise_for_status()
        content = _openai_output_text(response.json())
    except httpx.HTTPStatusError as exc:
        raise _provider_error("OpenAI", exc) from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise VisionError("OpenAI APIに接続できませんでした") from exc
    return normalize(_extract_json(content), model=OPENAI_MODEL, provider="openai")


def _anthropic_output_text(data: dict[str, Any]) -> str:
    texts = [
        str(item.get("text") or "")
        for item in data.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    if not texts:
        raise VisionError("Anthropicの応答を読み取れませんでした")
    return "\n".join(texts)


def identify_anthropic(image_bytes: bytes, api_key: str) -> dict[str, Any]:
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1200,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                },
                {"type": "text", "text": PROMPT},
            ],
        }],
    }
    try:
        response = httpx.post(
            ANTHROPIC_URL,
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=180,
        )
        response.raise_for_status()
        content = _anthropic_output_text(response.json())
    except httpx.HTTPStatusError as exc:
        raise _provider_error("Anthropic", exc) from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise VisionError("Anthropic APIに接続できませんでした") from exc
    return normalize(_extract_json(content), model=ANTHROPIC_MODEL, provider="anthropic")
