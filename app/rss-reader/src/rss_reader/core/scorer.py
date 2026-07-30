"""Two-stage article scoring.

Stage 1 (every item, milliseconds) is a weighted composite of lexical signals,
normalised the way patent-miner/scorer.py normalises its patent score: each
component is 0..1, the weighted sum is divided by the total weight so retuning a
weight never changes the scale, and a missing component defaults to neutral 0.5
instead of dropping the item.

Stage 2 (top N only) asks Ollama for a multi-axis judgement, following
writing/evaluate.py: structured JSON, clamped integers, an explicit negative
axis, and a neutral fallback rather than None. Measured here at ~3.5s per item
with gemma4:12b, so the ~1,800 cached articles would take ~1.7 hours (and
patent-miner records 13s/item on CPU-only Ollama, which would be ~6.4 hours).
Either way the gate is not an optimisation — it is what makes the LLM usable at
all. The previous implementation offered to score everything and, unsurprisingly,
had never once been run: the score cache was empty.

Deliberately *not* part of the score any more:

- freshness. It used to carry weight 0.4 and correlated +0.765 with the final
  score, so 重要度順 was mostly a date sort with noise. Recency is already a
  first-class filter in the UI (期間), which expresses it without corrupting the
  quality signal.
- bookmarked-feed boost. 29 of 39 feeds are bookmarked, so it awarded 2.0/10 to
  84% of articles: a constant offset, not a discriminator. Feed selection is
  also already a UI filter.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..config import CACHE_DIR, SCORE_CACHE_TTL
from ..settings import load as load_weights
from . import vocab
from .llm import ask_json, clamp_score
from .profile import get_cached as cached_profile

if TYPE_CHECKING:
    from .models import FeedItem

_cache = None


def _get_cache():
    global _cache
    if _cache is None:
        import diskcache

        _cache = diskcache.Cache(str(CACHE_DIR))
    return _cache


# --- 第1段: ルール層 ----------------------------------------------------

def _saturate(raw: float, target: float) -> float:
    """0..1 に潰す。target で 1.0 になる。"""
    if target <= 0:
        return 0.0
    return min(raw / target, 1.0)


def _relative(value: float, reference: float) -> float:
    """log 正規化したバッチ内相対値（patent-miner の _citation_score と同型）。"""
    if reference <= 0:
        return 0.0
    return min(math.log1p(max(0.0, value)) / math.log1p(reference), 1.0)


def _components(item: FeedItem, numeric_reference: float) -> dict[str, float]:
    novelty, surprise, announce, numeric = vocab.raw_signals(
        item.title or "", item.summary or ""
    )
    return {
        # 飽和点は語彙の発火率に合わせる。1.6 にしていたときは実データの
        # 発火率が 2% で、重み 0.3 の成分が 98% の記事で常に 0 になっていた。
        "novelty": _saturate(novelty, 1.0),
        "surprise": _saturate(surprise, 0.8),
        "specificity": _relative(numeric, numeric_reference),
        "announce": _saturate(announce, 1.5),
    }


def _content_score(parts: dict[str, float], w: dict[str, float]) -> float:
    """Average of the positive axes only. The promo penalty is applied later.

    Folding "not an announcement" in as a fourth positive axis looked tidy but
    measured badly: 90% of articles scored 1.0 on it, so a 0.44-weighted
    component became a constant baseline for nearly everything — the same defect
    as the old bookmarked-feed boost.
    """
    weights = {
        "novelty": w["w_novelty"],
        "surprise": w["w_surprise"],
        "specificity": w["w_specificity"],
    }
    total = sum(weights.values())
    if total <= 0:
        return 0.5
    return sum(parts[k] * weights[k] for k in weights) / total


def _percentile_within_feed(
    item: FeedItem, content: dict[int, float], by_feed: dict[str, list[int]], minimum: int
) -> float:
    """Rank of this article among its own feed's articles.

    x-analyzer normalises engagement by follower count so accounts of different
    sizes compare fairly. The same problem exists here: TECH PLAY posts 50
    articles a week against a median of 15, and GIGAZINE's number-heavy headline
    style lifted it to 22% of the top 50 while being 6% of the corpus. Ranking an
    article against its own feed asks "is this unusual *for this source*".
    """
    peers = by_feed.get(item.feed_url or "", [])
    if len(peers) < minimum:
        return 0.5  # 標本が少なすぎる → 中立
    mine = content[id(item)]
    below = sum(1 for pid in peers if content[pid] < mine)
    equal = sum(1 for pid in peers if content[pid] == mine)
    # equal を半分数えて同点の塊が 0 や 1 に張り付かないようにする
    return (below + equal / 2) / len(peers)


# --- 第2段: LLM 層 ------------------------------------------------------

_AXES = ("specificity", "originality", "promo")

_SCORE_PROMPT = """次の記事の見出しと要約を評価してください。

{profile_block}【評価軸】各1〜5の整数
- specificity: 具体性。固有名詞・数値・手順・条件・比較があるか。1=抽象論だけ、5=検証できる具体がある
- originality: 独自性。既知の焼き直しでなく、発見・視点・意外性があるか。1=よくある話、5=読んで発見がある
- promo: 宣伝・告知の度合い（**高いほど悪い**）。1=宣伝要素なし、5=セール告知/イベント募集/採用/PR記事そのもの

【出力JSON】
{{"specificity": 1-5, "originality": 1-5, "promo": 1-5, "reason": "40字以内の根拠"}}

注意:
- 見出しが煽っていても中身が薄ければ originality を上げない
- 数値が並んでいるだけ（型番・日付・価格の羅列）は specificity を上げない
- セール・イベント開催・登壇告知・求人・新製品の発売案内は promo を4以上にする
- 判断できない場合は3にする。JSONのみを1行で出力する

タイトル: {title}
要約: {summary}
"""

_REPAIR_PROMPT = """次の記事を3軸で1〜5点で採点し、JSONだけを1行で返してください。
specificity=具体性、originality=独自性、promo=宣伝度（高いほど悪い）。
{{"specificity":3,"originality":3,"promo":1,"reason":"..."}}
タイトル: {title}
"""


def _llm_cache_key(item: FeedItem) -> str:
    return f"llm_axes:{item.link or item.title}"


def get_llm_axes(item: FeedItem) -> dict | None:
    value = _get_cache().get(_llm_cache_key(item))
    return value if isinstance(value, dict) else None


def _axes_to_unit(axes: dict) -> float:
    """3軸 → 0..1。promo は減点として引く。

    writing/quality_loop.py の candidate_score が hallucination_risk を減算する
    のと同じ形。加点のみの合成では宣伝記事を押し下げられない。
    """
    spec = (clamp_score(axes.get("specificity")) - 1) / 4
    orig = (clamp_score(axes.get("originality")) - 1) / 4
    promo = (clamp_score(axes.get("promo")) - 1) / 4
    value = 0.35 * spec + 0.65 * orig - 0.8 * promo
    return max(0.0, min(1.0, 0.5 + value / 2))


def request_llm_axes(item: FeedItem, *, model: str | None = None) -> dict | None:
    """Score one item with Ollama and cache the axes. Returns None on failure."""
    profile = cached_profile()
    profile_block = (
        f"【読者の興味プロファイル】\n{profile}\n\n"
        "この読者にとっての関連性も originality に反映してください。\n\n"
        if profile else ""
    )
    title = (item.title or "")[:200]
    summary = (item.summary or "")[:400]
    data = ask_json(
        _SCORE_PROMPT.format(profile_block=profile_block, title=title, summary=summary),
        _REPAIR_PROMPT.format(title=title),
        model=model,
        num_predict=200,
        temperature=0.1,
        read_timeout=90.0,
    )
    if data is None:
        return None
    axes = {a: clamp_score(data.get(a)) for a in _AXES}
    reason = str(data.get("reason") or "").strip()[:60]
    # 全軸が既定値3のまま & 根拠なし = 実質無回答。使い回す価値がない。
    if all(axes[a] == 3 for a in _AXES) and not reason:
        return None
    axes["reason"] = reason
    _get_cache().set(_llm_cache_key(item), axes, expire=SCORE_CACHE_TTL)
    return axes


# --- 合成 ---------------------------------------------------------------

def apply_scores(
    items: list[FeedItem],
    bookmarked_urls: set[str] | None = None,
    include_llm: bool = True,
) -> None:
    """Set ``item.score`` (0-10) and ``item.score_parts`` in place.

    ``bookmarked_urls`` is accepted for call-site compatibility and no longer
    affects the score; feed selection is a filter, not a quality signal.
    """
    if not items:
        return
    w = load_weights()

    # 具体性はバッチ内相対。p90 を基準にすると外れ値1件で全体が潰れない。
    numeric = sorted(
        vocab.raw_signals(i.title or "", i.summary or "")[3] for i in items
    )
    reference = numeric[int(0.9 * (len(numeric) - 1))] or 1.0

    content: dict[int, float] = {}
    parts_by_id: dict[int, dict[str, float]] = {}
    by_feed: dict[str, list[int]] = {}
    for item in items:
        parts = _components(item, reference)
        content[id(item)] = _content_score(parts, w)
        parts_by_id[id(item)] = parts
        by_feed.setdefault(item.feed_url or "", []).append(id(item))

    minimum = int(w["min_feed_items"])
    w_abs, w_rel = w["w_absolute"], w["w_relative"]
    denom = (w_abs + w_rel) or 1.0
    w_llm = w["w_llm"]

    penalty = w["w_penalty"]
    for item in items:
        absolute = content[id(item)]
        relative = _percentile_within_feed(item, content, by_feed, minimum)
        base = (w_abs * absolute + w_rel * relative) / denom

        # 減点は絶対評価だけでなく合成後に掛ける。フィード内相対だけに任せると、
        # 中身が全部セール告知のフィードでは告知記事が「そのフィードでは平均的」
        # として 0.5 付近に浮上してしまう（実測で Kindle セールが 297/496 位）。
        base *= 1.0 - penalty * parts_by_id[id(item)]["announce"]

        axes = get_llm_axes(item) if include_llm else None
        if axes is not None:
            # LLM は置き換えではなく補正として効かせる。中立(0.5)なら素通しなので、
            # 未採点の記事と採点済みの記事を同じ尺度で比較できる。
            #
            # 単純な倍率 ×(1±w_llm) にすると上限を超えた分が clamp され、
            # 実測で上位6件が 10.00 で同点になり順序が壊れた。上下の境界へ
            # 寄せる形にすれば飽和せず、同じ補正量の中での順序も保たれる。
            delta = w_llm * (_axes_to_unit(axes) - 0.5) * 2.0
            base += delta * ((1.0 - base) if delta > 0 else base)

        item.score = round(max(0.0, min(1.0, base)) * 10.0, 2)
        item.score_parts = {
            **parts_by_id[id(item)],
            "relative": relative,
            "llm": _axes_to_unit(axes) if axes else None,
            "reason": axes.get("reason", "") if axes else "",
        }


def rank_for_llm(items: list[FeedItem], top_n: int) -> list[FeedItem]:
    """Items the second stage should look at: highest rule score, not yet scored."""
    pending = [i for i in items if get_llm_axes(i) is None]
    pending.sort(key=lambda i: i.score if i.score is not None else 0.0, reverse=True)
    return pending[:top_n]


def explain(item: FeedItem) -> dict[str, list[str]]:
    """Rule hits behind a score, for the UI tooltip."""
    return vocab.explain(item.title or "", item.summary or "")


# --- 興味プロファイル（core/profile.py へ移譲） -------------------------

def get_cached_profile() -> str | None:
    return cached_profile()


def generate_user_profile(bookmarks: list | None = None) -> str | None:
    from .profile import generate

    profile, _ = generate(bookmarks)
    return profile
