"""Persistent provider settings with write-only API keys."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path(
    os.getenv(
        "SPECIES_SETTINGS_PATH",
        str(Path.home() / ".config" / "species-explorer" / "settings.json"),
    )
)
MODELS = {
    "local": [{"id": "gemma4:12b", "label": "gemma4:12b（ローカル）"}],
    "openai": [
        {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna（低コスト）"},
        {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra（バランス）"},
        {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol（高性能）"},
    ],
    "anthropic": [
        {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5（低コスト）"},
        {"id": "claude-sonnet-5", "label": "Claude Sonnet 5（バランス）"},
        {"id": "claude-opus-5", "label": "Claude Opus 5（高性能）"},
    ],
}
DEFAULT_MODELS = {
    "local": "gemma4:12b",
    "openai": "gpt-5.6-luna",
    "anthropic": "claude-sonnet-5",
}


class SettingsError(ValueError):
    pass


def _defaults() -> dict[str, Any]:
    return {"provider": "local", "models": dict(DEFAULT_MODELS), "api_keys": {}}


def load() -> dict[str, Any]:
    data = _defaults()
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return data
    if saved.get("provider") in MODELS:
        data["provider"] = saved["provider"]
    for provider, model in (saved.get("models") or {}).items():
        if model in {item["id"] for item in MODELS.get(provider, [])}:
            data["models"][provider] = model
    for provider in ("openai", "anthropic"):
        key = (saved.get("api_keys") or {}).get(provider)
        if isinstance(key, str) and key:
            data["api_keys"][provider] = key
    return data


def public(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or load()
    return {
        "provider": data["provider"],
        "models": data["models"],
        "available_models": MODELS,
        "api_key_configured": {
            provider: bool(data["api_keys"].get(provider))
            for provider in ("openai", "anthropic")
        },
    }


def save(
    *,
    provider: str,
    models: dict[str, str],
    api_keys: dict[str, str | None],
    delete_keys: list[str],
) -> dict[str, Any]:
    if provider not in MODELS:
        raise SettingsError("計算資源を選び直してください")
    current = load()
    for name in MODELS:
        model = models.get(name, current["models"][name])
        if model not in {item["id"] for item in MODELS[name]}:
            raise SettingsError("モデルを選び直してください")
        current["models"][name] = model
    for name in delete_keys:
        if name in {"openai", "anthropic"}:
            current["api_keys"].pop(name, None)
    for name in ("openai", "anthropic"):
        key = api_keys.get(name)
        if isinstance(key, str) and key.strip():
            current["api_keys"][name] = key.strip()
    if provider != "local" and not current["api_keys"].get(provider):
        raise SettingsError("選択したAPIのキーを登録してください")
    current["provider"] = provider

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.parent.chmod(0o700)
    fd, temporary = tempfile.mkstemp(prefix=".settings-", dir=SETTINGS_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, SETTINGS_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return public(current)
