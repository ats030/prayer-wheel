"""Tests for the scoring rules.

These pin the specific defects the old implementation had, so a future edit that
reintroduces substring matching or morphological double-counting fails here.
"""

from __future__ import annotations

import pytest

from rss_reader.core import vocab
from rss_reader.core.models import FeedItem
from rss_reader.core.scorer import _axes_to_unit, _percentile_within_feed, apply_scores


def item(title: str, summary: str = "", feed: str = "f1", link: str = "") -> FeedItem:
    return FeedItem(
        title=title,
        link=link or f"https://example.com/{abs(hash(title))}",
        published=None,
        summary=summary,
        feed_url=feed,
        feed_title=feed,
    )


# --- 部分一致の誤爆 -----------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "Google Nano Banana 2 公開",       # 旧: "ban" in text → novelty
        "Ray-Ban Meta の新型スマートグラス",  # 旧: "ban"
        "urban development in Tokyo",       # 旧: "ban"
    ],
)
def test_ban_does_not_match_inside_words(title):
    assert vocab.match_score(vocab.NOVELTY, title, "") == 0.0


@pytest.mark.parametrize(
    "title",
    [
        "最初のページを開く",   # 旧: "初" in text
        "当初の予定どおり進行",  # 旧: "初"
        "初心者向けの解説",     # 旧: "初"
        "初期設定を見直す",     # 旧: "初"
    ],
)
def test_hatsu_does_not_match_inside_words(title):
    assert vocab.match_score(vocab.NOVELTY, title, "") == 0.0


def test_hatsu_still_matches_when_it_means_first():
    assert vocab.match_score(vocab.NOVELTY, "世界初の量産化に成功", "") > 0
    assert vocab.match_score(vocab.NOVELTY, "国内初の商用サービス", "") > 0
    assert vocab.match_score(vocab.NOVELTY, "新機能を初搭載", "") > 0


def test_koukai_alone_is_not_novelty():
    # 「公開」は旧実装で全記事の 11.1% にヒットし、ほぼ無情報だった
    assert vocab.match_score(vocab.NOVELTY, "新モデルを公開しました", "") == 0.0


def test_record_as_a_verb_is_not_novelty():
    # "record a skill" は機能名であって記録更新ではない
    assert vocab.match_score(vocab.NOVELTY, "新機能 record a skill が追加", "") == 0.0
    assert vocab.match_score(vocab.NOVELTY, "record-breaking performance", "") > 0


# --- 語形の重複カウント -------------------------------------------------

def test_morphological_variants_count_once():
    """旧実装は launch/launched/launches を別語として3回数えた。"""
    one = vocab.match_score(vocab.NOVELTY, "Google launched a new model", "")
    two = vocab.match_score(vocab.NOVELTY, "Google launches and released it", "")
    # launch 系と release 系はどちらも en_launch ルール1本に集約される
    assert one == pytest.approx(0.35)
    assert two == pytest.approx(0.35)


def test_shock_is_only_counted_as_surprise():
    """旧実装では「衝撃」が NOVELTY と SURPRISE の両方に入っていた。"""
    assert vocab.match_score(vocab.NOVELTY, "衝撃の結末", "") == 0.0
    assert vocab.match_score(vocab.SURPRISE, "衝撃の結末", "") > 0


# --- 告知・宣伝の検出（新設の負の軸）-----------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "7月30日終了のKindleセールまとめ KADOKAWA99円漫画",
        "「ものづくり・匠の技の祭典 2026」が東京国際フォーラムで開催",
        "エンジニア募集中！中途採用の募集要項を公開",
        "新製品の予約受付を開始しました",
        "[PR] 最新スマートフォンレビュー",
    ],
)
def test_announcements_are_detected(title):
    assert vocab.match_score(vocab.ANNOUNCE, title, "") > 0


def test_ordinary_article_is_not_an_announcement():
    assert vocab.match_score(vocab.ANNOUNCE, "Kimi K3 のアーキテクチャを読む", "") == 0.0


def test_announcement_scores_below_ordinary_article():
    items = [
        item("Kindleセールまとめ 99円漫画が対象 30%OFF"),
        item("推論精度が12%向上する新手法を検証した"),
    ]
    apply_scores(items, include_llm=False)
    assert items[0].score < items[1].score


# --- 数量表現 -----------------------------------------------------------

def test_years_do_not_count_as_concreteness():
    assert vocab.numeric_weight("2026年の展望", "") == pytest.approx(0.0)


def test_units_outweigh_bare_numbers():
    with_units = vocab.numeric_weight("消費電力を35%削減し 120時間 駆動", "")
    bare = vocab.numeric_weight("型番 3 4 5 6 7", "")
    assert with_units > bare


# --- フィード内相対化 ---------------------------------------------------

def test_small_feeds_get_neutral_relative_score():
    a, b = item("x", feed="tiny"), item("y", feed="tiny")
    content = {id(a): 0.9, id(b): 0.1}
    by_feed = {"tiny": [id(a), id(b)]}
    assert _percentile_within_feed(a, content, by_feed, 5) == 0.5


def test_percentile_ranks_within_the_same_feed():
    items = [item(f"t{i}", feed="big") for i in range(5)]
    content = {id(it): v for it, v in zip(items, [0.1, 0.2, 0.3, 0.4, 0.9])}
    by_feed = {"big": [id(it) for it in items]}
    assert _percentile_within_feed(items[4], content, by_feed, 5) > 0.8
    assert _percentile_within_feed(items[0], content, by_feed, 5) < 0.2


def test_standing_out_within_a_quiet_feed_beats_a_uniformly_loud_one():
    """フィード内相対の効果。

    多産フィードの記事が全部そこそこ強いと、絶対評価だけでは上位を埋めてしまう。
    静かなフィードで1本だけ突出した記事は「そのフィードにしては異常」なので
    拾えなければならない（x-analyzer が母数で割るのと同じ狙い）。
    """
    loud = [item(f"新機能を初搭載したモデル {i}", feed="loud") for i in range(20)]
    quiet = [item(f"定例のお知らせ {i}", feed="quiet") for i in range(9)]
    standout = item("世界初の量産化に成功、歩留まりを35%改善し120時間の連続駆動を実証", feed="quiet")
    apply_scores(loud + quiet + [standout], include_llm=False)
    ranked = sorted(loud + quiet + [standout], key=lambda i: -i.score)
    assert ranked[0] is standout


# --- LLM 軸の合成 -------------------------------------------------------

def test_promo_axis_pushes_score_down():
    neutral = _axes_to_unit({"specificity": 3, "originality": 3, "promo": 1})
    promo = _axes_to_unit({"specificity": 3, "originality": 3, "promo": 5})
    assert promo < neutral


def test_axes_are_clamped_not_dropped():
    # 範囲外・型違いでも例外にせず中立へ丸める（writing の _clamp_score と同契約）
    value = _axes_to_unit({"specificity": 99, "originality": "abc", "promo": None})
    assert 0.0 <= value <= 1.0


def test_llm_correction_never_saturates_and_keeps_order(monkeypatch):
    """LLM 補正で上限に張り付いて同点にならないこと。

    倍率方式にしていたときは、ルールスコアの高い記事が clamp されて
    上位6件が 10.00 で並び、順序が壊れていた。
    """
    from rss_reader.core import scorer

    strong = [item(f"世界初の量産化に成功し歩留まりを{n}%改善、{n}時間の連続駆動を実証", link=f"s{n}")
              for n in (35, 36, 37, 38, 39, 40)]
    # 全件を高評価にしても飽和しない
    monkeypatch.setattr(
        scorer, "get_llm_axes",
        lambda i: {"specificity": 5, "originality": 5, "promo": 1, "reason": ""},
    )
    apply_scores(strong, include_llm=True)
    scores = [i.score for i in strong]
    assert max(scores) < 10.0
    # 補正量が同じなら、補正前の順序が保たれる
    apply_scores(strong, include_llm=False)
    rule_order = [id(i) for i in sorted(strong, key=lambda i: -i.score)]
    apply_scores(strong, include_llm=True)
    llm_order = [id(i) for i in sorted(strong, key=lambda i: -i.score)]
    assert rule_order == llm_order


def test_scores_stay_in_range():
    items = [
        item("世界初の記録を更新、過去最高の突破を実証 35%改善 120時間"),
        item("セール開催中 クーポン 割引 プレゼント 抽選 求人 [PR]"),
        item(""),
    ]
    apply_scores(items, include_llm=False)
    assert all(0.0 <= i.score <= 10.0 for i in items)


def test_freshness_and_bookmarks_no_longer_affect_the_score():
    from datetime import datetime, timezone

    old = item("同一の見出しテキスト", link="a")
    old.published = datetime(2020, 1, 1, tzinfo=timezone.utc)
    new = item("同一の見出しテキスト", link="b")
    new.published = datetime.now(timezone.utc)
    apply_scores([old, new], bookmarked_urls={"f1"}, include_llm=False)
    assert old.score == new.score
