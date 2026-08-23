"""backlog-viewer の集計コアのテスト。

集計はすべて JST で行う。bd の created_at/closed_at は UTC なので、
深夜作業の日付がずれる。境界のテストを必ず含めること。
"""

from datetime import date

import main


def iso(y, m, d, h=0, mi=0):
    return f"{y:04d}-{m:02d}-{d:02d}T{h:02d}:{mi:02d}:00Z"


def issue(id_, created, closed=None, status="open", priority=3, updated=None, started=None,
          title="t", issue_type="task", defer_until=None, blocked_by=None, labels=None):
    return {
        "labels": labels or [],
        "defer_until": defer_until,
        "dependencies": ([{"depends_on_id": blocked_by, "type": "blocks"}] if blocked_by else []),
        "id": id_,
        "title": title,
        "status": status,
        "priority": priority,
        "issue_type": issue_type,
        "created_at": created,
        "closed_at": closed,
        "updated_at": updated or created,
        "started_at": started,
    }


class TestWeekStart:
    def test_monday_maps_to_itself(self):
        assert main.week_start(date(2026, 7, 27)) == date(2026, 7, 27)

    def test_sunday_maps_back_to_previous_monday(self):
        assert main.week_start(date(2026, 8, 2)) == date(2026, 7, 27)


class TestJstConversion:
    def test_utc_evening_becomes_next_day_in_jst(self):
        # 2026-08-20T15:00Z は JST では 2026-08-21 00:00
        assert main.jst_date(iso(2026, 8, 20, 15, 0)) == date(2026, 8, 21)

    def test_utc_morning_stays_same_day(self):
        assert main.jst_date(iso(2026, 8, 20, 1, 0)) == date(2026, 8, 20)

    def test_none_returns_none(self):
        assert main.jst_date(None) is None


class TestDailySeries:
    def test_open_issue_counted_from_creation_onward(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 10))])
        series = main.daily_series(issues, today=date(2026, 8, 12))
        assert series.total_on(date(2026, 8, 9)) == 0
        assert series.total_on(date(2026, 8, 10)) == 1
        assert series.total_on(date(2026, 8, 12)) == 1

    def test_closed_issue_drops_out_on_close_date(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 10), closed=iso(2026, 8, 11), status="closed")])
        series = main.daily_series(issues, today=date(2026, 8, 12))
        assert series.total_on(date(2026, 8, 10)) == 1
        assert series.total_on(date(2026, 8, 11)) == 0

    def test_same_day_close_never_appears(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 10, 1), closed=iso(2026, 8, 10, 5), status="closed")])
        series = main.daily_series(issues, today=date(2026, 8, 12))
        assert series.total_on(date(2026, 8, 10)) == 0

    def test_layers_are_keyed_by_creation_week(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 7, 27)),   # 7/27 週
            issue("b", iso(2026, 8, 3)),    # 8/03 週
        ])
        series = main.daily_series(issues, today=date(2026, 8, 5))
        assert series.count_on(date(2026, 8, 5), main.DEFERRED_LAYER) == 0
        assert series.count_on(date(2026, 8, 5), date(2026, 7, 27)) == 1
        assert series.count_on(date(2026, 8, 5), date(2026, 8, 3)) == 1

    def test_deferred_moves_to_its_own_layer_from_the_update_date(self):
        # defer した日は記録されないので updated_at で近似する
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1), status="deferred", updated=iso(2026, 8, 10)),
        ])
        series = main.daily_series(issues, today=date(2026, 8, 12))
        assert series.count_on(date(2026, 8, 5), date(2026, 7, 27)) == 1
        assert series.count_on(date(2026, 8, 5), main.DEFERRED_LAYER) == 0
        assert series.count_on(date(2026, 8, 11), date(2026, 7, 27)) == 0
        assert series.count_on(date(2026, 8, 11), main.DEFERRED_LAYER) == 1
        # 合計は変わらない (deferred を残件から除外しない)
        assert series.total_on(date(2026, 8, 11)) == 1


class TestCohortTable:
    def test_residual_rate(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 7, 27), closed=iso(2026, 7, 28), status="closed"),
            issue("b", iso(2026, 7, 28), closed=iso(2026, 7, 29), status="closed"),
            issue("c", iso(2026, 7, 29)),
            issue("d", iso(2026, 7, 30)),
        ])
        rows = main.cohort_table(issues, today=date(2026, 8, 21))
        row = next(r for r in rows if r.week == date(2026, 7, 27))
        assert row.created == 4
        assert row.remaining == 2
        assert row.residual_rate == 50.0

    def test_weeks_with_no_creation_are_omitted(self):
        issues = main.parse_issues([issue("a", iso(2026, 7, 27))])
        rows = main.cohort_table(issues, today=date(2026, 8, 21))
        assert [r.week for r in rows] == [date(2026, 7, 27)]


class TestBacklogRows:
    def test_sorted_by_age_descending(self):
        issues = main.parse_issues([
            issue("new", iso(2026, 8, 20)),
            issue("old", iso(2026, 7, 1)),
            issue("mid", iso(2026, 8, 1)),
        ])
        rows = main.backlog_rows(issues, today=date(2026, 8, 21))
        assert [r.id for r in rows] == ["old", "mid", "new"]
        assert rows[0].age_days == 51

    def test_closed_issues_are_excluded(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1), closed=iso(2026, 8, 2), status="closed"),
            issue("b", iso(2026, 8, 1)),
        ])
        rows = main.backlog_rows(issues, today=date(2026, 8, 21))
        assert [r.id for r in rows] == ["b"]

    def test_freeze_expired_is_detected(self):
        """期限が過ぎた凍結を拾えること。bd は期限が来ても自動では戻さない"""
        issues = main.parse_issues([
            issue("a", iso(2026, 6, 1), status="deferred", defer_until=iso(2026, 8, 1)),
            issue("b", iso(2026, 6, 1), status="deferred", defer_until=iso(2026, 9, 1)),
        ])
        today = date(2026, 8, 22)
        assert issues[0].freeze_expired(today) is True
        assert issues[1].freeze_expired(today) is False
        assert main.metrics(issues, today).freeze_expired == 1

    def test_freeze_without_a_date_is_counted_separately(self):
        """期限なしは期限切れとして拾えないので別に数える"""
        issues = main.parse_issues([issue("a", iso(2026, 6, 1), status="deferred")])
        today = date(2026, 8, 22)
        assert issues[0].freeze_undated() is True
        assert issues[0].freeze_expired(today) is False
        m = main.metrics(issues, today)
        assert (m.freeze_expired, m.freeze_undated) == (0, 1)

    def test_freeze_with_a_blocker_is_not_nagged(self):
        """契機を依存で表現したものは期限なしでも催促しない

        期限を切る目的は「二度と見ない」を防ぐこと。blocks 依存があれば、その issue が
        閉じたときに戻ってくるので目的は満たされている。ここを区別しないと、正しく
        表現したものまで毎週催促され、通知が信用されなくなる。
        """
        issues = main.parse_issues([
            issue("a", iso(2026, 6, 1), status="deferred"),
            issue("b", iso(2026, 6, 1), status="deferred", blocked_by="x"),
        ])
        assert issues[0].freeze_undated() is True
        assert issues[1].freeze_undated() is False
        assert main.metrics(issues, date(2026, 8, 22)).freeze_undated == 1

    def test_open_issues_are_never_frozen(self):
        issues = main.parse_issues([issue("a", iso(2026, 6, 1), status="open")])
        assert issues[0].freeze_undated() is False
        assert issues[0].freeze_expired(date(2026, 8, 22)) is False

    def test_deferred_is_included_and_flagged(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), status="deferred")])
        rows = main.backlog_rows(issues, today=date(2026, 8, 21))
        assert rows[0].deferred is True


class TestMetrics:
    def test_same_day_close_rate(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1, 1), closed=iso(2026, 8, 1, 5), status="closed"),
            issue("b", iso(2026, 8, 1), closed=iso(2026, 8, 5), status="closed"),
        ])
        m = main.metrics(issues, today=date(2026, 8, 21))
        assert m.same_day_close_rate == 50.0

    def test_claim_rate_counts_started_at(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1), started=iso(2026, 8, 1)),
            issue("b", iso(2026, 8, 1)),
            issue("c", iso(2026, 8, 1)),
            issue("d", iso(2026, 8, 1)),
        ])
        m = main.metrics(issues, today=date(2026, 8, 21))
        assert m.claim_rate == 25.0

    def test_over_30_days_count(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 7, 1)),
            issue("b", iso(2026, 8, 20)),
        ])
        m = main.metrics(issues, today=date(2026, 8, 21))
        assert m.over_30_days == 1
        assert m.remaining == 2


class TestLayerLabel:
    """凡例は相対週で書く。色の明度 (古いほど暗い) と同じ軸に揃える。"""

    def test_relative_week_labels(self):
        today = date(2026, 8, 21)  # 金曜。週頭は 8/17
        assert main._layer_label(date(2026, 8, 17), today) == "今週"
        assert main._layer_label(date(2026, 8, 10), today) == "先週"
        assert main._layer_label(date(2026, 8, 3), today) == "2週前"
        assert main._layer_label(date(2026, 6, 1), today) == "11週前"

    def test_deferred_layer_keeps_its_name(self):
        assert main._layer_label(main.DEFERRED_LAYER, date(2026, 8, 21)) == "外部待ち"

    def test_legend_keeps_the_absolute_date_in_a_tooltip(self):
        """x 軸は絶対日付のままなので、突き合わせる術を残しておく。"""
        issues = main.parse_issues([issue("a", iso(2026, 8, 3))])
        series = main.daily_series(issues, today=date(2026, 8, 21))
        legend = main.render_legend(series, today=date(2026, 8, 21))
        assert "2週前" in legend
        assert 'title="2026-08-03〜 に作成"' in legend


class TestSvg:
    def test_one_polygon_per_layer(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 7, 27)),
            issue("b", iso(2026, 8, 3)),
        ])
        series = main.daily_series(issues, today=date(2026, 8, 5))
        svg = main.render_stacked_svg(series, today=date(2026, 8, 5))
        assert svg.count("<polygon") == 2
        assert "viewBox" in svg

    def test_empty_series_does_not_crash(self):
        series = main.daily_series([], today=date(2026, 8, 5))
        svg = main.render_stacked_svg(series, today=date(2026, 8, 5))
        assert "<svg" in svg


class TestPage:
    def test_index_renders_with_stub_data(self, monkeypatch):
        from fastapi.testclient import TestClient

        raw = [
            issue("ats030-aaaa", iso(2026, 7, 27), title="古い残件"),
            issue("ats030-bbbb", iso(2026, 8, 20), closed=iso(2026, 8, 20), status="closed"),
        ]
        monkeypatch.setattr(main, "load_raw_issues", lambda: raw)
        client = TestClient(main.app)
        res = client.get("/")
        assert res.status_code == 200
        body = res.text
        assert "ats030-aaaa" in body
        assert "古い残件" in body
        assert "<svg" in body
        # クローズ済みは一覧に出ない
        assert "ats030-bbbb" not in body

    def test_index_survives_bd_failure(self, monkeypatch):
        from fastapi.testclient import TestClient

        def boom():
            raise RuntimeError("bd not found")

        monkeypatch.setattr(main, "load_raw_issues", boom)
        client = TestClient(main.app)
        res = client.get("/")
        assert res.status_code == 200
        assert "bd" in res.text


class TestWeeklySummary:
    def test_delta_compares_with_seven_days_ago(self):
        issues = main.parse_issues([
            issue("old", iso(2026, 8, 1)),
            issue("new1", iso(2026, 8, 18)),
            issue("new2", iso(2026, 8, 19)),
        ])
        s = main.weekly_summary(issues, today=date(2026, 8, 21))
        assert s["remaining"] == 3
        assert s["delta_7d"] == 2  # 7日前は old の1件だけ

    def test_delta_is_negative_when_backlog_shrank(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1), closed=iso(2026, 8, 20), status="closed"),
            issue("b", iso(2026, 8, 1)),
        ])
        s = main.weekly_summary(issues, today=date(2026, 8, 21))
        assert s["remaining"] == 1
        assert s["delta_7d"] == -1

    def test_lists_oldest_items(self):
        issues = main.parse_issues([
            issue("old", iso(2026, 6, 1), title="最古"),
            issue("new", iso(2026, 8, 20), title="最新"),
        ])
        s = main.weekly_summary(issues, today=date(2026, 8, 21))
        assert s["oldest"][0].id == "old"
        assert s["over_30_days"] == 1


class TestNotifyMessage:
    def test_deferred_items_are_marked_in_the_list(self):
        import notify

        issues = main.parse_issues([
            issue("a", iso(2026, 6, 1), status="deferred", title="ライセンス照会中"),
            issue("b", iso(2026, 7, 1), title="ただの残件"),
        ])
        today = date(2026, 8, 21)
        text = notify.build_message(main.weekly_summary(issues, today), today)
        assert "[外部待ち] ライセンス照会中" in text
        assert "[外部待ち] ただの残件" not in text


class TestBdBinary:
    def test_prefers_path_when_available(self, monkeypatch):
        monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/bd")
        assert main.bd_binary() == "/usr/bin/bd"

    def test_falls_back_to_local_bin_when_not_on_path(self, monkeypatch, tmp_path):
        # systemd --user の PATH には ~/.local/bin が入らない
        monkeypatch.setattr(main.shutil, "which", lambda name: None)
        fake = tmp_path / "bd"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        monkeypatch.setattr(main, "FALLBACK_BD_PATHS", (str(fake),))
        assert main.bd_binary() == str(fake)

    def test_last_resort_is_bare_name(self, monkeypatch):
        monkeypatch.setattr(main.shutil, "which", lambda name: None)
        monkeypatch.setattr(main, "FALLBACK_BD_PATHS", ("/nonexistent/bd",))
        assert main.bd_binary() == "bd"


class TestCohortExplanatoryColumns:
    def test_same_day_rate_is_share_of_the_week_closed_on_creation_day(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 7, 27, 1), closed=iso(2026, 7, 27, 9), status="closed"),
            issue("b", iso(2026, 7, 28), closed=iso(2026, 7, 30), status="closed"),
            issue("c", iso(2026, 7, 29)),
            issue("d", iso(2026, 7, 30)),
        ])
        row = main.cohort_table(issues, today=date(2026, 8, 21))[0]
        # 母数はその週に作った全件。閉じた件だけを母数にすると、
        # 「作ったまま放置」が分母から消えて率が良く見えてしまう。
        assert row.same_day_rate == 25.0

    def test_p3_share(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 7, 27), priority=3),
            issue("b", iso(2026, 7, 28), priority=1),
            issue("c", iso(2026, 7, 29), priority=2),
            issue("d", iso(2026, 7, 30), priority=3),
        ])
        row = main.cohort_table(issues, today=date(2026, 8, 21))[0]
        assert row.p3_share == 50.0


class TestActionable:
    """『動かせる残件』を主指標にする (ats030-hn2k)。

    残32件のうち動かせるのは11件で、21件が外部待ち、うち7件は「〜を凍結中」という
    記録そのものだった。分母に動かせないものが混ざると、収束していないように見える
    だけになる。このアプリの問いは「残タスクがなぜ収束しないか」なので、分けて数える。
    """

    def test_deferred_is_not_actionable(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1)),
            issue("b", iso(2026, 8, 1), status="deferred"),
        ])
        m = main.metrics(issues, date(2026, 8, 23))
        assert (m.remaining, m.actionable, m.deferred) == (2, 1, 1)

    def test_freeze_records_are_counted_apart(self):
        """凍結の記録はタスクではない"""
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1), status="deferred", title="memo を凍結中 (2026-11-23 に見直す)"),
            issue("b", iso(2026, 8, 1), status="deferred", title="ライセンス照会の返答待ち"),
        ])
        m = main.metrics(issues, date(2026, 8, 23))
        assert (m.deferred, m.freeze_records) == (2, 1)

    def test_in_progress_is_actionable(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), status="in_progress")])
        assert main.metrics(issues, date(2026, 8, 23)).actionable == 1


class TestBacklogRowsSplit:
    def test_freeze_records_are_separated(self):
        """一覧に混ざると探しているものが埋もれる"""
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1), title="本当のタスク"),
            issue("b", iso(2026, 8, 1), status="deferred", title="memo を凍結中 (2026-11-23 に見直す)"),
        ])
        live, cold = main.split_rows(main.backlog_rows(issues, date(2026, 8, 23)))
        assert [r.id for r in live] == ["a"]
        assert [r.id for r in cold] == ["b"]

    def test_nothing_frozen_leaves_the_list_whole(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1))])
        live, cold = main.split_rows(main.backlog_rows(issues, date(2026, 8, 23)))
        assert len(live) == 1 and cold == []


class TestLeadTimeLabel:
    """0日は「計測できていない」ではなく「その日に閉じている」。

    同日クローズ率が8割を超える環境では中央値が0に張り付き、タイルの「0日」は
    欠測と誤読されやすい。
    """

    def test_same_day_reads_as_immediate(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), closed=iso(2026, 8, 1))])
        page = main.render_page(issues, date(2026, 8, 23))
        assert "即日" in page
        assert "リードタイム中央値" in page

    def test_multi_day_still_shows_days(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), closed=iso(2026, 8, 6))])
        assert "5日" in main.render_page(issues, date(2026, 8, 23))


class TestWhoCanAct:
    """誰が動かせるかを分ける (ats030-hn2k)。

    「動かせる残件11」には2種類が混ざっていた。エージェントには物理的に不可能なもの
    (提供元へのログイン、外部への問い合わせ、実機確認) と、技術的には可能だが判断が
    要るもの (価格・文面・原稿の方向性)。前者は待つしかないが、後者は一言決まれば
    実装まで進む。混ざっていると、どちらに手を打てば動き出すのか分からない。

    判定は人がラベルで付ける。題名からの推定は外れる (y9fb.5 は一見実装タスクだが、
    起票時に「実機で確認してから判断」と決まっている)。
    """

    def test_human_label_marks_owner_only(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), labels=["human"])])
        assert issues[0].actor == "owner"

    def test_decision_label_marks_judgment(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), labels=["decision"])])
        assert issues[0].actor == "decision"

    def test_no_label_is_agent_work(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1))])
        assert issues[0].actor == "agent"

    def test_human_wins_over_decision(self):
        """両方付いていたら owner。物理的に不可能なほうが強い制約"""
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), labels=["decision", "human"])])
        assert issues[0].actor == "owner"

    def test_metrics_split_the_actionable_count(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1)),
            issue("b", iso(2026, 8, 1), labels=["human"]),
            issue("c", iso(2026, 8, 1), labels=["decision"]),
            issue("d", iso(2026, 8, 1), status="deferred"),
        ])
        m = main.metrics(issues, date(2026, 8, 23))
        assert (m.actionable, m.by_agent, m.by_owner, m.by_decision) == (3, 1, 1, 1)

    def test_deferred_is_not_counted_in_the_split(self):
        """外部待ちは誰の手番でもない"""
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), status="deferred", labels=["human"])])
        m = main.metrics(issues, date(2026, 8, 23))
        assert (m.actionable, m.by_owner) == (0, 0)
