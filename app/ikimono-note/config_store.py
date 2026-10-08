"""Persistent provider settings with write-only API keys."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

SETTINGS_PATH = Path(
    os.getenv(
        "IKIMONO_SETTINGS_PATH",
        str(Path.home() / ".config" / "ikimono-note" / "settings.json"),
    )
)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
# 無料で試せる順に並べる。画面の選択肢もこの順で出る。
# Ollama は完全に無料、Gemini は無料枠あり、OpenAI と Anthropic は従量課金のみ。
MODELS = {
    "local": [{"id": "gemma4:12b", "label": "gemma4:12b（ローカル）"}],
    # 無料枠は同じ Gemini でもモデルごとに大きく違う。実測で 3.6 Flash は1日20回しか
    # 通らず、30枚の評価すら回らなかった。Flash-Lite は30枚を完走している。
    #
    # 回数そのものは書かない。Google はモデル別の表を公開しなくなり、いまは
    # AI Studio でアカウントごとに見る形になっている (2026-08-14 に確認)。
    # 数字を書くと、確かめられないものを断定することになる。
    "gemini": [
        {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite（推奨・無料枠が広い）"},
        {"id": "gemini-3.7-flash", "label": "Gemini 3.7 Flash（最新・速い）"},
        {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash（無料枠が狭い）"},
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
    ],
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
    "gemini": "gemini-3.5-flash-lite",
    "openai": "gpt-5.6-luna",
    "anthropic": "claude-sonnet-5",
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
        raise SettingsError("OllamaのURLは http:// または https:// の接続先を入力してください")
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
    *, include_local: bool = True,
) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    local, incompatible = ollama_models(ollama_url) if include_local else ([], [])
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
        # ディスクのない置き場ではここを通る。環境変数を読まずに返すと、
        # まさにその置き場でだけ広告の設定が空になる
        _apply_env_affiliate(data)
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
    _apply_env_affiliate(data)
    # 既定には置かない。一度も呼んでいない状態と、呼んで通った状態を混ぜないため
    state = saved.get("creators_api_state")
    if isinstance(state, dict) and isinstance(state.get("ok"), bool):
        data["creators_api_state"] = {
            "ok": state["ok"],
            "reason": str(state.get("reason") or "")[:80],
            "hint": str(state.get("hint") or "")[:200],
            "status": max(0, int(state.get("status") or 0)),
            "at": str(state.get("at") or "")[:40],
        }
    return data


def public(data: dict[str, Any] | None = None, *, include_local: bool = True) -> dict[str, Any]:
    data = data or load()
    catalog, incompatible = model_catalog(data["models"]["local"], data["local_llm"]["url"], include_local=include_local)
    return {
        "provider": data["provider"],
        "models": data["models"],
        "local_llm": data["local_llm"],
        "available_models": catalog,
        "incompatible_local_models": incompatible,
        "affiliate": {"title": data["affiliate"]["title"], "url": data["affiliate"]["url"], "enabled": bool(data["affiliate"]["enabled"] and data["affiliate"]["url"]), "metrics": affiliate_metrics(), "partner_tag": data["affiliate"].get("partner_tag", ""), "product_enabled": bool(data["affiliate"].get("product_enabled") and data["affiliate"].get("partner_tag") and data["api_keys"].get("amazon_creators_id") and data["api_keys"].get("amazon_creators_secret")), "creators_api_configured": bool(data["api_keys"].get("amazon_creators_id") and data["api_keys"].get("amazon_creators_secret"))},
        "api_key_configured": {
            provider: bool(data["api_keys"].get(provider))
            for provider in ("openai", "anthropic", "gemini", "plantnet")
        },
    }


def record_affiliate(event: str) -> None:
    """広告が出た / 押された、を数える。

    ディスクのある運営者用は settings.json に足す。Cloud Run にはディスクが無く、
    インスタンスが入れ替わるたび 0 に戻っていた。数えていたつもりで何も残らず、
    商品APIの資格 (直近30日で適格販売10件) までの距離が分からなかった。
    Firestore が使えるならそちらへ足す。
    """
    if event not in {"impressions", "clicks"}:
        raise ValueError("unknown affiliate event")
    import auth  # 循環を避けるため、呼ばれたときに読む
    if auth.using_firestore():
        try:
            auth.bump_metric(event)
        except Exception as error:      # 数えられなくても、広告そのものは出す
            print(f"広告の数えを記録できませんでした（{event}）: {error}", flush=True)
        return
    with _AFFILIATE_LOCK:
        current = load()
        current["affiliate_metrics"][event] += 1
        _write(current)


def affiliate_metrics() -> dict[str, int]:
    """いまの数え。置き場が2通りあるので、読む側はここだけ見ればよい。"""
    import auth
    if auth.using_firestore():
        try:
            stored = auth.read_metrics()
        except Exception:
            return {"impressions": 0, "clicks": 0}
        return {"impressions": int(stored.get("impressions", 0)),
                "clicks": int(stored.get("clicks", 0))}
    return dict(load().get("affiliate_metrics") or {"impressions": 0, "clicks": 0})


# ディスクのない置き場 (Cloud Run / Container Apps など) では settings.json が存在せず、
# 広告の設定ごと消える。公開版は設定を書けない (403) ので、読む先を環境変数にも広げる。
# 埋めるのは「ファイル側が空のときだけ」。上書きにすると、運営者用の設定画面で保存しても
# 環境変数に戻されて、保存が効かないように見える。
ENV_AFFILIATE = {
    "title": "IKIMONO_AFFILIATE_TITLE",
    "url": "IKIMONO_AFFILIATE_URL",
    "partner_tag": "IKIMONO_AFFILIATE_PARTNER_TAG",
}
ENV_AFFILIATE_FLAGS = {
    "enabled": "IKIMONO_AFFILIATE_ENABLED",
    "product_enabled": "IKIMONO_AFFILIATE_PRODUCT_ENABLED",
}
# プロバイダーのキーも環境変数から。公開版は BYOK だが、お試し枠 (運営者が貸す枠) は
# サーバー側のキーを使う。ディスクの無い置き場ではファイルが無いので、ここが無いと
# 枠を有効にしても静かに無効のままになる。
ENV_API_KEYS = {
    "gemini": "IKIMONO_GEMINI_API_KEY",
    "openai": "IKIMONO_OPENAI_API_KEY",
    "anthropic": "IKIMONO_ANTHROPIC_API_KEY",
    "plantnet": "IKIMONO_PLANTNET_API_KEY",
    "amazon_creators_id": "IKIMONO_AMAZON_CREATORS_ID",
    "amazon_creators_secret": "IKIMONO_AMAZON_CREATORS_SECRET",
}


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _apply_env_affiliate(data: dict[str, Any]) -> None:
    for field, name in ENV_AFFILIATE.items():
        if not data["affiliate"].get(field):
            value = os.getenv(name, "").strip()
            if value:
                data["affiliate"][field] = value[:120] if field == "title" else value
    for field, name in ENV_AFFILIATE_FLAGS.items():
        if not data["affiliate"].get(field):
            value = os.getenv(name, "")
            if value:
                data["affiliate"][field] = _truthy(value)
    for field, name in ENV_API_KEYS.items():
        if not data["api_keys"].get(field):
            value = os.getenv(name, "").strip()
            if value:
                data["api_keys"][field] = value


def record_creators_result(ok: bool, *, reason: str = "", hint: str = "", status: int = 0) -> None:
    """商品APIの最後の結果を残す。状態が変わったときだけ書く。

    毎回書くと、商品カードを描くたびに settings.json を触ることになる。知りたいのは
    「いま通っているか、通っていないなら何と言われたか」だけなので、変化点で足りる。
    """
    state = {"ok": bool(ok), "reason": "" if ok else str(reason)[:80],
             "hint": "" if ok else str(hint)[:200], "status": 0 if ok else int(status)}
    with _AFFILIATE_LOCK:
        current = load()
        previous = current.get("creators_api_state") or {}
        if {key: previous.get(key) for key in state} == state:
            return
        current["creators_api_state"] = {**state, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
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
            raise SettingsError("Ollamaのモデル名を入力してください")
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
