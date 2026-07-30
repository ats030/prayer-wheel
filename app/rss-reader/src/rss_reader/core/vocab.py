"""Context-bound lexical rules for article scoring.

Modelled on writing/ai_slop.py: every rule is a compiled regex with surrounding
context, never a bare substring test. The previous implementation used
``word in text`` over a flat set, which matched "ban" inside "nano banana" and
"ray-ban", and "初" inside 最初 / 当初 / 初期 (7% of all articles).

Each rule fires at most once per field, so morphological variants that used to
be separate set entries (launch / launched / launches) can no longer triple-count
a single occurrence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    weight: float


def _rules(spec: list[tuple[str, str, float]]) -> list[Rule]:
    return [Rule(n, re.compile(p, re.IGNORECASE), w) for n, p, w in spec]


# --- 新規性・希少性 -----------------------------------------------------
# 「初」「公開」の単体は捨てた。実データで 7.0% / 11.1% にヒットし、
# その大半が 最初 / 当初 / 公開しました のような無情報の一致だった。
NOVELTY = _rules([
    ("world_first",  r"(?:世界|国内|業界|日本|人類|史上)初", 1.0),
    # 最初 / 当初 / 年初 / 期初 の「初」を拾わないよう直前の字を除外する
    ("first_of",     r"(?<![最当年月期])初の[ぁ-んァ-ヶ一-龠A-Za-z]", 0.6),
    ("first_act",    r"(?<![最当年月期])初(?:公開|披露|搭載|採用|実装|上陸|導入|受注)", 0.8),
    ("en_first",     r"\b(?:world|industry)[-\s]?first\b|\bfirst[-\s]ever\b", 1.0),
    ("en_unveil",    r"\b(?:unveil|debut|breakthrough)\w*\b", 0.8),
    ("en_launch",    r"\b(?:launch|release)(?:e[sd]|s|ing)?\b", 0.35),
    ("record",       r"(?:過去最(?:高|多|大|速|安|長)|世界記録|記録を(?:更新|突破)|突破し)", 0.8),
    ("en_record",    r"\b(?:record[-\s]breaking|surpass\w*|milestone)\b", 0.8),
    ("discovery",    r"(?:発見|解明|実証|判明(?:した|しました)?|明らかに(?:なった|した))", 0.6),
    ("succeeded",    r"(?:に成功(?:した|しました)?|を達成)", 0.6),
    ("superlative",  r"(?:世界最|国内最|業界最)(?:高|大|小|速|軽|薄|安|長)", 0.8),
    ("en_novel",     r"\b(?:new|novel)\s+(?:approach|method|technique|discovery|algorithm)\b", 0.6),
    ("shutdown",     r"(?:廃止|サービス(?:終了|停止)|撤退|打ち切り|提供終了)", 0.7),
    ("en_shutdown",  r"\b(?:shut\s?down|discontinu\w+|deprecat\w+)\b", 0.7),
    ("corporate",    r"(?:買収|合併|経営統合|倒産|破産|民事再生|上場廃止)", 0.8),
    ("en_corporate", r"\b(?:acquisition|acquires?|acquired|merger|bankruptcy)\b", 0.8),
    ("regulation",   r"(?:解禁|全面禁止|義務化|法制化|規制強化)", 0.6),
    # \b だけだと Ray-Ban / nano-ban のようなハイフン複合語に一致してしまう
    ("en_ban",       r"(?<![\w-])(?:bans?|banned)(?![\w-])", 0.6),
])

# --- 意外性・反転 -------------------------------------------------------
# 「衝撃」は旧実装で NOVELTY と SURPRISE の両方に入っていて二重加点だった。
# ここだけに置く。
SURPRISE = _rules([
    ("unexpected",   r"(?:予想(?:外|に反し)|想定外|意外に|番狂わせ)", 1.0),
    ("en_unexpected", r"\b(?:unexpected|surprising|counterintuitive)\w*\b", 1.0),
    ("reversal",     r"(?:覆(?:す|った|る)|逆転|一転して|前言撤回|撤回し)", 0.8),
    ("en_reversal",  r"\b(?:reversal|overturn\w*|defies|defied|u-turn)\b", 0.8),
    ("controversy",  r"(?:炎上|物議|論争|批判が集中|反発が)", 0.6),
    ("en_controversy", r"\b(?:backlash|controvers\w+|scandal)\b", 0.6),
    ("shock",        r"衝撃", 0.5),
    ("question",     r"(?:なぜ|どうして)[^。！？\n]{0,24}(?:のか|の?か[？?])", 0.4),
])

# --- 告知・宣伝（負の信号）---------------------------------------------
# 旧実装には無かった軸。実データでは「Kindleセールまとめ」「イベント開催」が
# 上位に来ており、加点語彙を増やすより、この種を落とすほうが判別力が高い。
ANNOUNCE = _rules([
    ("sale",         r"(?:セール|割引|クーポン|特価|値下げ|お買い得|ポイント還元|キャッシュバック)", 1.0),
    # 裸の sale / deal は "arms sale" "space deals" のような報道語にも当たる。
    # 値引きを示す文脈を伴うときだけ拾う。
    ("en_sale",      r"\b(?:discount|coupon|promo\s?code|black\s?friday|prime\s?day)\b"
                     r"|\b\d+%\s?off\b|\b(?:on|flash|clearance|holiday|summer)\s+sale\b", 1.0),
    ("giveaway",     r"(?:プレゼント(?:企画)?|抽選で|当たる|応募(?:受付|方法|開始))", 1.0),
    ("en_giveaway",  r"\b(?:giveaway|sweepstakes?)\b", 1.0),
    ("bargain",      r"(?:まとめ買い|最安|激安|お得な)", 0.6),
    # 「〜で開催」のように活用語尾が付かない形もあるため語幹だけで拾う。
    # ニュース記事の「W杯が開催され」も拾うが、単独では 0.6 で決定打にはしない。
    ("event",        r"(?:開催|開講|募集(?:中|開始|します)?|受付(?:中|開始))", 0.6),
    ("event_kind",   r"(?:登壇|出展|ブース|セミナー|ウェビナー|勉強会|交流会|説明会)", 0.6),
    ("en_event",     r"\b(?:webinar|meetup|register\s+now)\b", 0.8),
    ("preorder",     r"(?:予約(?:受付|開始)|発売(?:日|開始|中)|先行(?:販売|予約)|新発売|販売開始)", 0.8),
    ("ad",           r"(?:\[?PR\]?[】\]\s]|スポンサー|タイアップ|提供[:：]|広告記事)", 1.0),
    ("en_ad",        r"\b(?:sponsored|advertisement)\b", 1.0),
    ("hiring",       r"(?:求人|採用情報|募集要項|中途採用|新卒採用)", 0.8),
    ("roundup",      r"(?:まとめ(?:記事)?じゃ|お知らせ|ご案内|【告知】)", 0.6),
])

# 数量表現。単位つきの数値は「具体性」の信号として強く、裸の数値は弱い。
_NUM_WITH_UNIT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|％|倍|割|万|億|兆|円|ドル|ユーロ|人|件|台|個|回|"
    r"年|ヶ月|か月|週間|日間|時間|分|秒|[kKmMgGtT]?[bB]|[kKmMcC]?m|kg|g|km/h|W|V|Hz|fps)",
)
# 日本語文字も \w なので \b は数字と仮名の境界に立たない（"を35%" の 35 が
# \b\d+\b では取れない）。数字そのものの前後だけを見る形にする。
_NUM_PLAIN = re.compile(r"(?<!\d)\d+(?:[.,]\d+)?(?!\d)")
# 年号は「具体性」ではなく単なる日付表記なので除外する
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


@lru_cache(maxsize=4096)
def raw_signals(title: str, summary: str) -> tuple[float, float, float, float]:
    """(novelty, surprise, announce, numeric) for one article.

    All four are independent of the rest of the batch, and the same articles are
    re-read from the feed cache on every request, so memoising on the text keeps
    a 1,800-item page render at a few milliseconds instead of ~330ms of regex.
    """
    return (
        match_score(NOVELTY, title, summary),
        match_score(SURPRISE, title, summary),
        match_score(ANNOUNCE, title, summary),
        numeric_weight(title, summary),
    )


def match_score(rules: list[Rule], title: str, summary: str) -> float:
    """Weighted rule hits over title (full weight) and summary (half weight).

    Returns an unbounded non-negative float; callers saturate it.
    """
    total = 0.0
    for rule in rules:
        if rule.pattern.search(title):
            total += rule.weight
        elif rule.pattern.search(summary):
            total += rule.weight * 0.5
    return total


def numeric_weight(title: str, summary: str) -> float:
    """Raw concreteness signal: unit-bearing numbers count more than bare ones."""
    text = f"{title} {summary}"
    without_years = _YEAR.sub(" ", text)
    with_unit = len(_NUM_WITH_UNIT.findall(without_years))
    plain = max(0, len(_NUM_PLAIN.findall(without_years)) - with_unit)
    return with_unit * 1.0 + plain * 0.35


def explain(title: str, summary: str) -> dict[str, list[str]]:
    """Which rules fired — used by the UI tooltip so a score can be audited."""
    out: dict[str, list[str]] = {}
    for label, rules in (("novelty", NOVELTY), ("surprise", SURPRISE), ("announce", ANNOUNCE)):
        hits = [r.name for r in rules if r.pattern.search(title) or r.pattern.search(summary)]
        if hits:
            out[label] = hits
    return out
