"""Persistent provider settings with write-only API keys."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

SETTINGS_PATH = Path(
    os.getenv(
        "SPECIES_SETTINGS_PATH",
        str(Path.home() / ".config" / "species-explorer" / "settings.json"),
    )
)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
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
    "gemini": [
        {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash（推奨）"},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash（高性能）"},
        {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite（低コスト）"},
    ],
}
DEFAULT_MODELS = {
    "local": "gemma4:12b",
    "openai": "gpt-5.6-luna",
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-3.6-flash",
}
_AFFILIATE_LOCK = threading.Lock()


class SettingsError(ValueError):
    pass


def _defaults() -> dict[str, Any]:
    return {"provider": "local", "models": dict(DEFAULT_MODELS), "local_llm": {"url": OLLAMA_URL}, "api_keys": {}, "affiliate": {"title": "", "url": "", "enabled": False, "partner_tag": "", "product_enabled": False}, "affiliate_metrics": {"impressions": 0, "clicks": 0}}


def _local_llm_url(value: object) -> str:
    url = str(value or "").strip().rstrip("/")
    parsed = urlparse(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise SettingsError("ローカルAIのURLは http:// または https:// の接続先を入力してください")
    return url


def ollama_models(ollama_url: str = OLLAMA_URL) -> tuple[list[dict[str, str]], list[str]]:
    """Return installed vision models and names that cannot accept images."""
    try:
        response = httpx.get(f"{ollama_url}/api/tags", timeout=3)
        response.raise_for_status()
        installed = response.json().get("models") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return [], []
    vision_models: list[dict[str, str]] = []
    incompatible: list[str] = []
    for item in installed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").strip()
        if item.get("connection_type") not in {None, "local"}:
            continue
        if not name:
            continue
        capabilities = item.get("capabilities")
        if not isinstance(capabilities, list):
            capabilities = []
        try:
            details = httpx.post(
                f"{ollama_url}/api/show",
                json={"model": name, "verbose": False},
                timeout=3,
            )
            details.raise_for_status()
            detailed_capabilities = details.json().get("capabilities")
            if isinstance(detailed_capabilities, list):
                capabilities = detailed_capabilities
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        if "vision" in capabilities:
            parameter_size = str(
                (item.get("details") or {}).get("parameter_size") or ""
            )
            suffix = f" · {parameter_size}" if parameter_size else ""
            vision_models.append({"id": name, "label": f"{name}{suffix}"})
        else:
            incompatible.append(name)
    return vision_models, incompatible


def model_catalog(
    current_local: str | None = None,
    ollama_url: str = OLLAMA_URL,
) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    local, incompatible = ollama_models(ollama_url)
    if not local:
        fallback = current_local or DEFAULT_MODELS["local"]
        local = [{"id": fallback, "label": f"{fallback}（保存済み）"}]
    catalog = {provider: list(models) for provider, models in MODELS.items()}
    catalog["local"] = local
    return catalog, incompatible


def load() -> dict[str, Any]:
    data = _defaults()
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return data
    if saved.get("provider") in MODELS:
        data["provider"] = saved["provider"]
    local_llm = saved.get("local_llm") or {}
    if isinstance(local_llm, dict):
        try:
            data["local_llm"]["url"] = _local_llm_url(local_llm.get("url"))
        except SettingsError:
            pass
    for provider, model in (saved.get("models") or {}).items():
        if provider == "local" and isinstance(model, str) and model:
            data["models"][provider] = model
        elif model in {item["id"] for item in MODELS.get(provider, [])}:
            data["models"][provider] = model
    for provider in ("openai", "anthropic", "gemini", "plantnet", "amazon_creators_id", "amazon_creators_secret"):
        key = (saved.get("api_keys") or {}).get(provider)
        if isinstance(key, str) and key:
            data["api_keys"][provider] = key
    affiliate = saved.get("affiliate") or {}
    if isinstance(affiliate, dict):
        url = str(affiliate.get("url") or "").strip()
        url = url.replace("i=stripbooks\x26", "").replace("\x26i=stripbooks", "")
        title = str(affiliate.get("title") or "").strip()[:120]
        if urlparse(url).scheme == "https" and urlparse(url).netloc:
            data["affiliate"] = {"title": title, "url": url, "enabled": bool(affiliate.get("enabled")), "partner_tag": str(affiliate.get("partner_tag") or "").strip()[:80], "product_enabled": bool(affiliate.get("product_enabled"))}
    metrics = saved.get("affiliate_metrics") or {}
    if isinstance(metrics, dict):
        data["affiliate_metrics"] = {"impressions": max(0, int(metrics.get("impressions", 0))), "clicks": max(0, int(metrics.get("clicks", 0)))}
    return data


def public(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or load()
    catalog, incompatible = model_catalog(data["models"]["local"], data["local_llm"]["url"])
    return {
        "provider": data["provider"],
        "models": data["models"],
        "local_llm": data["local_llm"],
        "available_models": catalog,
        "incompatible_local_models": incompatible,
        "affiliate": {"title": data["affiliate"]["title"], "url": data["affiliate"]["url"], "enabled": bool(data["affiliate"]["enabled"] and data["affiliate"]["url"]), "metrics": data["affiliate_metrics"], "partner_tag": data["affiliate"].get("partner_tag", ""), "product_enabled": bool(data["affiliate"].get("product_enabled") and data["affiliate"].get("partner_tag") and data["api_keys"].get("amazon_creators_id") and data["api_keys"].get("amazon_creators_secret")), "creators_api_configured": bool(data["api_keys"].get("amazon_creators_id") and data["api_keys"].get("amazon_creators_secret"))},
        "api_key_configured": {
            provider: bool(data["api_keys"].get(provider))
            for provider in ("openai", "anthropic", "gemini", "plantnet")
        },
    }


def record_affiliate(event: str) -> None:
    if event not in {"impressions", "clicks"}:
        raise ValueError("unknown affiliate event")
    with _AFFILIATE_LOCK:
        current = load()
        current["affiliate_metrics"][event] += 1
        _write(current)


def affiliate_target(query: str = "") -> str:
    current = load()
    if not current["affiliate"]["enabled"] or not current["affiliate"]["url"]:
        raise LookupError("広告が設定されていません")
    template = current["affiliate"]["url"]
    if "{query}" not in template:
        raise LookupError("検索用アフィリエイトリンクが設定されていません")
    term = " ".join(str(query).split())[:80]
    if not term:
        raise LookupError("検索語がありません")
    return template.replace("{query}", quote_plus(term))


def _write(current: dict[str, Any]) -> None:
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


def save(
    *,
    provider: str,
    models: dict[str, str],
    api_keys: dict[str, str | None],
    delete_keys: list[str],
    local_llm: dict[str, Any] | None = None,
    affiliate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider not in MODELS:
        raise SettingsError("使うAIを選び直してください")
    current = load()
    if local_llm is not None:
        current["local_llm"]["url"] = _local_llm_url(local_llm.get("url"))
    catalog, _ = model_catalog(current["models"]["local"], current["local_llm"]["url"])
    for name in MODELS:
        model = models.get(name, current["models"][name])
        if name == "local" and (not isinstance(model, str) or not model.strip() or len(model) > 200):
            raise SettingsError("ローカルAIのモデル名を入力してください")
        if name != "local" and model not in {item["id"] for item in catalog[name]}:
            raise SettingsError("モデルを選び直してください")
        current["models"][name] = model.strip() if name == "local" else model
    for name in delete_keys:
        if name in {"openai", "anthropic", "gemini", "plantnet", "amazon_creators_id", "amazon_creators_secret"}:
            current["api_keys"].pop(name, None)
    for name in ("openai", "anthropic", "gemini", "plantnet", "amazon_creators_id", "amazon_creators_secret"):
        key = api_keys.get(name)
        if isinstance(key, str) and key.strip():
            current["api_keys"][name] = key.strip()
    if provider != "local" and not current["api_keys"].get(provider):
        raise SettingsError("選択したAPIのキーを登録してください")
    current["provider"] = provider
    if affiliate is not None:
        title = str(affiliate.get("title") or "").strip()[:120]
        url = str(affiliate.get("url") or "").strip()
        enabled = bool(affiliate.get("enabled"))
        partner_tag = str(affiliate.get("partner_tag") or "").strip()[:80]
        product_enabled = bool(affiliate.get("product_enabled"))
        parsed = urlparse(url)
        if url and (parsed.scheme != "https" or not parsed.netloc):
            raise SettingsError("アフィリエイトURLは https:// で入力してください")
        if enabled and (not title or not url):
            raise SettingsError("広告名とアフィリエイトURLを入力してください")
        if product_enabled and (not partner_tag or not current["api_keys"].get("amazon_creators_id") or not current["api_keys"].get("amazon_creators_secret")):
            raise SettingsError("Creators APIのCredential ID・Secret・Partner Tagを登録してください")
        if enabled and "{query}" not in url:
            raise SettingsError("検索用URLには {query} を含めてください")
        current["affiliate"] = {"title": title, "url": url, "enabled": enabled, "partner_tag": partner_tag, "product_enabled": product_enabled}
    _write(current)
    return public(current)
