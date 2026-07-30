from __future__ import annotations

import math
import os
import re
from typing import TYPE_CHECKING

from ..config import CACHE_DIR, SCORE_CACHE_TTL, SCORE_HALF_LIFE_HOURS

if TYPE_CHECKING:
    from .bookmarks import Bookmark
    from .models import FeedItem

_cache = None

_PROFILE_CACHE_KEY = "user_interest_profile"
_PROFILE_CACHE_TTL = 86400  # 24h


def _get_cache():
    global _cache
    if _cache is None:
        import diskcache

        _cache = diskcache.Cache(str(CACHE_DIR))
    return _cache

# 希少性・新規性を示す語彙
_NOVELTY_JA = {
    "初", "世界初", "国内初", "突破", "廃止", "終了", "刷新", "登場", "公開",
    "解禁", "発見", "革命", "転換", "崩壊", "激変", "衝撃", "速報", "緊急", "独占",
    "禁止", "撤退", "倒産", "買収", "合併", "分裂",
}
_NOVELTY_EN = {
    "first", "launch", "launches", "launched", "release", "releases", "released",
    "breaks", "surpasses", "record", "historic", "shutdown", "discontinue", "ban",
    "banned", "debut", "unveil", "unveiled", "breakthrough", "exclusive",
    "acquired", "merger", "bankruptcy",
}

# 驚き・反転・逆説を示す語彙
_SURPRISE_JA = {"予想外", "意外", "覆す", "逆転", "驚き", "番狂わせ", "衝撃", "論争", "炎上"}
_SURPRISE_EN = {
    "unexpected", "surprising", "surprise", "shocking", "reversal",
    "overturns", "defies", "controversy", "backlash", "scandal",
}

_PROFILE_PROMPT = """\
以下はユーザーがブックマークしたフィードの一覧です。

{bookmarks_text}

このユーザーの興味・関心領域を3〜5項目の箇条書きで要約してください。
技術領域・トピック・言語・フォーマット（ブログ/ポッドキャスト/ニュース等）の傾向を含めてください。
箇条書きのみ出力してください（番号・説明・前置きは不要）。

興味プロファイル:"""

_SCORE_PROMPT_GENERIC = """\
以下の記事の面白さ・インパクト・独自性を0から10の整数で評価してください。

評価基準:
- 読んで発見や驚きがある、独自の視点・データがある、社会的インパクトが大きい: 7〜10
- 一般的な情報・標準的な記事: 4〜6
- 宣伝・告知・ありきたりな内容・軽微な更新: 1〜3

タイトル: {title}
要約: {summary}

数字のみを回答してください（例: 7）。
スコア:"""

_SCORE_PROMPT_PERSONALIZED = """\
以下の記事の面白さ・インパクト・独自性、およびユーザーへの関連性を0から10の整数で評価してください。

【ユーザーの興味プロファイル】
{user_profile}

評価基準:
- ユーザーの興味に強く関連し、発見や驚きがある、独自の視点・データがある: 7〜10
- 一般的な情報・標準的な記事、またはユーザーの興味に部分的に関連: 4〜6
- ユーザーの興味と無関係、または宣伝・告知・ありきたりな内容: 1〜3

タイトル: {title}
要約: {summary}

数字のみを回答してください（例: 7）。
スコア:"""


def get_cached_profile() -> str | None:
    return _get_cache().get(_PROFILE_CACHE_KEY)


def generate_user_profile(bookmarks: list[Bookmark]) -> str | None:
    if not bookmarks:
        return None
    model = _get_score_model()
    if not model:
        return None

    lines: list[str] = []
    for bm in bookmarks[:30]:
        tags_str = ", ".join(bm.tags) if bm.tags else "（タグなし）"
        lines.append(f"- フィード: {bm.feed_title} / タグ: {tags_str}")
        for title in bm.item_titles[:3]:
            lines.append(f"  - {title}")

    prompt = _PROFILE_PROMPT.format(bookmarks_text="\n".join(lines))
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        import httpx

        resp = httpx.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=httpx.Timeout(connect=5, read=60, write=5, pool=5),
        )
        resp.raise_for_status()
        profile = resp.json().get("response", "").strip()
        if profile:
            _get_cache().set(_PROFILE_CACHE_KEY, profile, expire=_PROFILE_CACHE_TTL)
            return profile
    except Exception as e:
        raise RuntimeError(str(e)) from e
    return None


def _llm_cache_key(item: FeedItem) -> str:
    return f"llm_score:{item.link or item.title}"


def _freshness(published) -> float:
    from datetime import datetime, timezone
    if published is None:
        return 0.5
    now = datetime.now(timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - published).total_seconds() / 3600)
    return math.exp(-math.log(2) * hours / SCORE_HALF_LIFE_HOURS)


def _impact_score(item: FeedItem) -> float:
    text = (item.title + " " + item.summary).lower()

    # 希少性・新規性語彙（3件以上でサチュレーション）
    novelty = sum(1 for w in _NOVELTY_JA | _NOVELTY_EN if w in text)
    novelty = min(novelty / 3, 1.0)

    # 具体性：数値・パーセントの密度（5件以上でサチュレーション）
    numbers = re.findall(r'\d+(?:[.,]\d+)?%?', text)
    concreteness = min(len(numbers) / 5, 1.0)

    # 驚き・反転語彙（あれば即 1.0）
    surprise = 1.0 if any(w in text for w in _SURPRISE_JA | _SURPRISE_EN) else 0.0

    return novelty * 0.5 + concreteness * 0.3 + surprise * 0.2


def _source_boost(item: FeedItem, bookmarked_urls: set[str]) -> float:
    return 1.0 if item.feed_url in bookmarked_urls else 0.0


def _compute_rule_score(item: FeedItem, bookmarked_urls: set[str]) -> float:
    f = _freshness(item.published)
    impact = _impact_score(item)
    b = _source_boost(item, bookmarked_urls)
    return round((f * 0.4 + impact * 0.4 + b * 0.2) * 10.0, 2)


def get_llm_score(item: FeedItem) -> float | None:
    return _get_cache().get(_llm_cache_key(item))


def _parse_score_response(text: str) -> float | None:
    m = re.search(r'\b(\d+(?:\.\d+)?)\b', text.strip())
    if not m:
        return None
    val = float(m.group(1))
    if 0.0 <= val <= 10.0:
        return val
    if 10.0 < val <= 100.0:
        return val / 10.0
    return None


def _get_score_model() -> str | None:
    model = os.environ.get("OLLAMA_SCORE_MODEL", "").strip()
    if model:
        return model
    models_str = os.environ.get("OLLAMA_MODELS", "")
    models = [m.strip() for m in models_str.split(",") if m.strip()]
    return models[0] if models else None


def request_llm_score(item: FeedItem) -> float | None:
    model = _get_score_model()
    if not model:
        return None
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    user_profile = get_cached_profile()
    if user_profile:
        prompt = _SCORE_PROMPT_PERSONALIZED.format(
            user_profile=user_profile,
            title=item.title,
            summary=item.summary[:300],
        )
    else:
        prompt = _SCORE_PROMPT_GENERIC.format(title=item.title, summary=item.summary[:300])
    try:
        import httpx

        resp = httpx.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=httpx.Timeout(connect=5, read=30, write=5, pool=5),
        )
        resp.raise_for_status()
        score = _parse_score_response(resp.json().get("response", ""))
        if score is not None:
            _get_cache().set(_llm_cache_key(item), score, expire=SCORE_CACHE_TTL)
        return score
    except Exception:
        return None


def apply_scores(items: list[FeedItem], bookmarked_urls: set[str], include_llm: bool = True) -> None:
    for item in items:
        rule = _compute_rule_score(item, bookmarked_urls)
        llm = get_llm_score(item) if include_llm else None
        item.score = round(rule * 0.5 + llm * 0.5, 2) if llm is not None else rule
