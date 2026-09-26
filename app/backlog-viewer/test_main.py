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


class TestPeakReturn:
    """外部待ちが戻ってくる日。早い順に見ると山を見落とす。"""

    def _deferred(self, id_, until):
        return issue(id_, iso(2026, 8, 1), status="deferred", defer_until=until)

    def test_returns_the_day_with_the_most_items_not_the_earliest(self):
        issues = main.parse_issues([
            self._deferred("a", iso(2026, 8, 30)),
            self._deferred("b", iso(2026, 11, 23)),
            self._deferred("c", iso(2026, 11, 23)),
        ])
        m = main.metrics(issues, today=date(2026, 8, 24))
        assert m.peak_return == (date(2026, 11, 23), 2)

    def test_ties_pick_the_earlier_day(self):
        issues = main.parse_issues([
            self._deferred("a", iso(2026, 9, 1)),
            self._deferred("b", iso(2026, 11, 23)),
        ])
        m = main.metrics(issues, today=date(2026, 8, 24))
        assert m.peak_return == (date(2026, 9, 1), 1)

    def test_expired_items_are_excluded(self):
        # 期限切れは freeze_expired が数える。ここに混ぜると二重に警告する。
        issues = main.parse_issues([self._deferred("a", iso(2026, 8, 14))])
        m = main.metrics(issues, today=date(2026, 8, 24))
        assert m.peak_return is None
        assert m.freeze_expired == 1

    def test_none_when_nothing_has_a_deadline(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1), status="deferred"),
            issue("b", iso(2026, 8, 1)),
        ])
        assert main.metrics(issues, today=date(2026, 8, 24)).peak_return is None


class TestReturnCell:
    def _row(self, **kw):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1), **kw)])
        return main.backlog_rows(issues, today=date(2026, 8, 24))[0]

    def test_blank_when_not_deferred(self):
        assert main._return_cell(self._row(), date(2026, 8, 24)) == ""

    def test_shows_the_date_when_it_is_still_ahead(self):
        row = self._row(status="deferred", defer_until=iso(2026, 11, 23))
        assert "11/23" in main._return_cell(row, date(2026, 8, 24))

    def test_expired_date_is_marked(self):
        row = self._row(status="deferred", defer_until=iso(2026, 8, 14))
        cell = main._return_cell(row, date(2026, 8, 24))
        assert "8/14" in cell and 'class="hot"' in cell

    def test_missing_deadline_is_marked(self):
        row = self._row(status="deferred")
        assert "未設定" in main._return_cell(row, date(2026, 8, 24))


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

    def test_workbench_prioritizes_actionable_tasks_and_three_metrics(self):
        issues = main.parse_issues([
            issue("action-now", iso(2026, 8, 20), title="いま判断"),
            issue("wait-later", iso(2026, 8, 1), status="deferred",
                  defer_until=iso(2026, 11, 23), title="外部待ち"),
        ])
        page = main.render_page(issues, date(2026, 8, 24))
        assert page.count('class="tile"') == 3
        assert page.index("棚卸しするタスク") < page.index("傾向を分析する")
        assert "<strong>外部待ち</strong>" in page
        assert "dock-actions" in page and "dock-output" in page

    def test_defer_command_always_carries_a_deadline(self):
        page = main.render_page([], date(2026, 9, 26))
        # 期限なしの defer は画面が「未設定」と警告する状態なので、ボタンから作らない
        assert "' --until=' + document.getElementById('defer-until').value" in main.JS
        assert 'id="defer-until" value="2026-12-25" min="2026-09-27"' in page

    def test_dock_buttons_only_copy_and_can_clear_the_selection(self):
        page = main.render_page([], date(2026, 9, 26))
        # どちらもコピーするだけなので、実行したように読める文言にしない
        assert ">打ち切りをコピー</button>" in page
        assert ">外部待ちをコピー</button>" in page
        assert "外部待ちへ送る</button>" not in page
        assert 'id="clear-picks">選択を解除</button>' in page
        assert "querySelectorAll('.pick:checked').forEach(e => { e.checked = false; })" in main.JS

    def test_defer_date_shows_how_many_already_return_that_day(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 8, 1), status="deferred", defer_until=iso(2026, 11, 23)),
            issue("b", iso(2026, 8, 2), status="deferred", defer_until=iso(2026, 11, 23)),
            issue("c", iso(2026, 8, 3), status="deferred", defer_until=iso(2026, 12, 1)),
            issue("d", iso(2026, 8, 4), status="deferred"),
        ])
        page = main.render_page(issues, date(2026, 9, 26))
        assert 'const RETURNS = {"2026-11-23": 2, "2026-12-01": 1};' in page
        assert 'id="defer-load"' in page

    def test_over_30_tile_points_to_the_folds_that_hold_the_rows(self):
        issues = main.parse_issues([
            issue("fresh", iso(2026, 9, 20)),
            issue("wait-old", iso(2026, 7, 1), status="deferred",
                  defer_until=iso(2026, 11, 23)),
            issue("record-old", iso(2026, 7, 1), status="deferred",
                  title="record \u51cd\u7d50\u4e2d"),
        ])
        page = main.render_page(issues, date(2026, 9, 26))
        assert '<a class="tile" id="tile-over30" href="#">' in page
        assert "うち 外部待ち 1 · 凍結の記録 1" in page
        assert page.count('class="tile"') == 3
        assert "fold.open = true" in main.JS

    def test_expired_tile_describes_the_expired_rows_and_points_to_them(self):
        issues = main.parse_issues([
            issue("late", iso(2026, 8, 1), status="deferred", defer_until=iso(2026, 9, 1)),
            issue("later", iso(2026, 8, 1), status="deferred", defer_until=iso(2026, 9, 20)),
            issue("wait", iso(2026, 8, 1), status="deferred", defer_until=iso(2026, 11, 23)),
        ])
        page = main.render_page(issues, date(2026, 9, 26))
        assert '<a class="tile" id="tile-expired" href="#">' in page
        assert "最も古い期限 9/1(25日超過)" in page
        assert page.count("data-expired ") == 2
        assert "'expired' in row.dataset" in main.JS
        # 復帰の山は期限切れと関係ないので、外部待ちの一覧の見出しへ移す
        assert "期限切れ 2件 · 最大の復帰 11/23 に 1件</span>" in page

    def test_expired_tile_is_plain_when_nothing_is_expired(self):
        issues = main.parse_issues([
            issue("wait", iso(2026, 8, 1), status="deferred", defer_until=iso(2026, 11, 23)),
        ])
        page = main.render_page(issues, date(2026, 9, 26))
        assert 'id="tile-expired"' not in page
        assert "期限切れなし" in page
        assert "data-expired" not in page

    def test_list_count_is_split_by_actor_to_match_the_tile(self):
        issues = main.parse_issues([
            issue("a", iso(2026, 9, 20)),
            issue("b", iso(2026, 9, 20)),
            issue("o", iso(2026, 9, 20), labels=["human"]),
        ])
        page = main.render_page(issues, date(2026, 9, 26))
        # タイルは「エージェントが進められる 2」、一覧は3件。差の内訳を見出しで示す
        assert '<div class="v">2</div>' in page
        assert '<span class="section-count">3件(エージェント 2 · 所有者 1)</span>' in page

    def test_list_count_stays_plain_when_one_actor_holds_everything(self):
        issues = main.parse_issues([issue("a", iso(2026, 9, 20))])
        page = main.render_page(issues, date(2026, 9, 26))
        assert '<span class="section-count">1件</span>' in page

    def test_checkboxes_are_wrapped_in_a_cell_wide_hit_area(self):
        page = main.render_page(main.parse_issues([issue("a", iso(2026, 9, 20))]),
                                date(2026, 9, 26))
        assert '<label class="hit"><input type="checkbox" class="pick" value="a"' in page
        assert '<label class="hit"><input type="checkbox" class="pick-all"' in page
        assert "width: 18px; height: 18px" in main.CSS

    def test_over_30_tile_is_plain_when_nothing_is_old(self):
        issues = main.parse_issues([issue("fresh", iso(2026, 9, 20))])
        page = main.render_page(issues, date(2026, 9, 26))
        assert 'id="tile-over30"' not in page
        assert "打ち切りの候補なし" in page

    def test_title_opens_description_and_acceptance(self):
        raw = issue("a", iso(2026, 9, 20), title="t <x>")
        raw["description"] = "背景 & 理由"
        raw["acceptance_criteria"] = "テストが通る"
        page = main.render_page(main.parse_issues([raw]), date(2026, 9, 26))
        assert '<details class="desc" name="desc"><summary>t &lt;x&gt;</summary>' in page
        assert ('<div class="desc-body"><div class="desc-accept"><span class="desc-label">完了条件</span>\n'
                'テストが通る</div>背景 &amp; 理由</div>') in page
        assert "max-height: min(16em, 40vh); overflow-y: auto;" in main.CSS

    def test_close_copy_is_not_emphasized_over_defer_copy(self):
        page = main.render_page([], date(2026, 9, 26))
        assert '<button class="copy" data-target="cmd-close">' in page
        assert "primary" not in page

    def test_title_without_body_is_not_expandable(self):
        page = main.render_page(main.parse_issues([issue("a", iso(2026, 9, 20))]),
                                date(2026, 9, 26))
        assert 'class="desc"' not in page

    def test_return_column_only_where_rows_can_return(self):
        issues = main.parse_issues([
            issue("now", iso(2026, 9, 20)),
            issue("wait", iso(2026, 8, 1), status="deferred", defer_until=iso(2026, 11, 23)),
        ])
        page = main.render_page(issues, date(2026, 9, 26))
        main_table = page.split("棚卸しするタスク")[1].split('<details class="fold">')[0]
        assert "復帰" not in main_table
        assert page.count('<th class="num">復帰</th>') == 1

    def test_wait_chip_only_where_it_tells_rows_apart(self):
        issues = main.parse_issues([
            issue("wait", iso(2026, 8, 1), status="deferred"),
            issue("rec-wait", iso(2026, 8, 2), status="deferred", title="A を凍結中"),
            issue("rec-open", iso(2026, 8, 3), title="B を凍結中"),
        ])
        page = main.render_page(issues, date(2026, 9, 26))
        folds = page.split('<details class="fold">')
        deferred_fold = next(f for f in folds if 'data-id="wait"' in f)
        cold_fold = next(f for f in folds if 'data-id="rec-wait"' in f)
        assert "外部待ち</span>" not in deferred_fold
        assert cold_fold.count("外部待ち</span>") == 1

    def test_close_reason_follows_each_rows_circumstances(self):
        today = date(2026, 9, 26)
        issues = main.parse_issues([
            issue("idle", iso(2026, 8, 1)),
            issue("fresh", iso(2026, 9, 20)),
            issue("begun", iso(2026, 8, 1), status="in_progress", started=iso(2026, 8, 2)),
            issue("busy", iso(2026, 8, 1), status="in_progress", started=iso(2026, 8, 2),
                  updated=iso(2026, 9, 26)),
            issue("overdue", iso(2026, 8, 1), status="deferred", defer_until=iso(2026, 9, 1)),
            issue("waiting", iso(2026, 8, 1), status="deferred", defer_until=iso(2026, 12, 1)),
            issue("open-ended", iso(2026, 8, 1), status="deferred"),
            issue("rec", iso(2026, 8, 1), title="A を凍結中"),
        ])
        reasons = {r.id: main._close_reason(r, today) for r in main.backlog_rows(issues, today)}
        assert reasons == {
            "idle": "着手されないまま滞留したため打ち切り",
            "fresh": "着手前に打ち切り",
            "begun": "着手後に更新が止まったため打ち切り",
            "busy": "着手中のまま打ち切り",
            "overdue": "外部待ちの復帰日 9/1 を過ぎても再開されなかったため打ち切り",
            "waiting": "外部待ちの解消を待たずに打ち切り",
            "open-ended": "外部待ちのまま復帰日が決まらなかったため打ち切り",
            "rec": "凍結の記録を整理",
        }
        page = main.render_page(issues, today)
        assert 'data-id="begun" data-close-reason="着手後に更新が止まったため打ち切り"' in page
        # 作業中の行は一覧で見分けられる。未着手の行には出ない。
        assert page.count('<span class="chip started">着手済み</span>') == 2

    def test_close_command_is_split_per_reason(self):
        assert "dataset.closeReason" in main.JS
        assert ".join('\\n')" in main.JS
        assert "着手されないまま滞留したため打ち切り" not in main.JS

    def test_priority_chips_step_down_without_new_hues(self):
        assert 'class="chip">P1<' in main._priority_chip(1)
        assert 'class="chip gray">P2<' in main._priority_chip(2)
        assert 'class="chip faint">P3<' in main._priority_chip(3)
        assert 'class="chip faint">P4<' in main._priority_chip(4)

    def test_select_all_is_scoped_to_its_own_table(self):
        assert "source.closest('table').querySelectorAll('.pick')" in main.JS

    def test_selection_state_is_visible_from_headers(self):
        issues = main.parse_issues([
            issue("now", iso(2026, 9, 20)),
            issue("wait", iso(2026, 8, 1), status="deferred"),
            issue("rec", iso(2026, 8, 2), status="deferred", title="A を凍結中"),
        ])
        page = main.render_page(issues, date(2026, 9, 26))
        assert page.count('class="pick-all"') == 3
        # 閉じられる2つの一覧は、見出しに選択件数の置き場がある
        assert page.count('<span class="fold-picked"></span>') == 2
        assert "all.indeterminate = n > 0 && n < boxes.length;" in main.JS

    def test_list_heading_does_not_reuse_the_actor_word_for_decisions(self):
        # 担い手の「要判断」とは別物なので、一覧の見出しは下部パネルの「棚卸し」とそろえる
        page = main.render_page([], date(2026, 9, 26))
        assert "<h2>棚卸しするタスク</h2>" in page
        assert "いま判断" not in page

    def test_narrow_tiles_put_the_number_beside_the_label(self):
        mobile = main.CSS.split("@media (max-width: 640px)")[1]
        assert ".tiles .tile { display: grid; grid-template-columns: 1fr auto;" in mobile
        assert "td:last-child { overflow-wrap: anywhere; }" in mobile
        assert ".tile .v { grid-column: 2; grid-row: 1 / 3;" in mobile
        assert "white-space: nowrap;" in main.CSS.split(".id {")[1].split("}")[0]

    def test_started_mark_has_no_frame_so_actor_chips_stand_out(self):
        rule = main.CSS.split(".chip.started {")[1].split("}")[0]
        assert "box-shadow" not in rule
        assert "color: var(--subtle);" in rule

    def test_narrow_heading_puts_count_and_sort_below_the_title(self):
        mobile = main.CSS.split("@media (max-width: 640px)")[1]
        assert ".section-head { flex-direction: column;" in mobile
        assert "word-break: keep-all;" in main.CSS.split(".section-count {")[1].split("}")[0]

    def test_sorting_is_done_only_from_the_column_headings(self):
        issues = main.parse_issues([issue("a", iso(2026, 8, 1))])
        page = main.render_page(issues, date(2026, 9, 26))
        assert "<select" not in page.split("<h2>棚卸しするタスク</h2>")[1].split("<table")[0]
        assert '<button type="button" class="sort" title="滞留の長い順に並べる">滞留</button>' in page
        assert "b.addEventListener('click', () => sortTables(b.closest('th').dataset.sortKey));" in main.JS

    def test_all_backlog_tables_support_the_shared_sort_control(self):
        issues = main.parse_issues([
            issue("p2-old", iso(2026, 7, 1), priority=2),
            issue("p0-new", iso(2026, 8, 20), priority=0),
            issue("wait", iso(2026, 8, 1), status="deferred", priority=1),
            issue("record", iso(2026, 8, 2), status="deferred", priority=3,
                  title="record \u51cd\u7d50\u4e2d"),
        ])
        page = main.render_page(issues, date(2026, 8, 24))
        assert page.count("<tbody data-sortable>") == 3
        assert page.index("data-id=\"p0-new\"") < page.index("data-id=\"p2-old\"")
        assert "data-age=\"54\" data-priority=\"2\" data-id=\"p2-old\"" in page
        assert "function compareRows(left, right, order)" in main.JS
        assert "return priority || age || left.dataset.id.localeCompare(right.dataset.id);" in main.JS
        assert "sortTables('priority');" in main.JS
        assert page.count('<th class="num" data-sort-key="age"><button') == 3
        assert page.count('<th data-sort-key="priority"><button') == 3
        assert "localStorage" not in main.JS

    def test_deferred_deadline_is_visible_on_the_page(self, monkeypatch):
        from fastapi.testclient import TestClient

        raw = [
            issue("ats030-cccc", iso(2026, 8, 1), status="deferred",
                  defer_until=iso(2026, 11, 23), title="外部待ち"),
            issue("ats030-dddd", iso(2026, 8, 1), status="deferred",
                  defer_until=iso(2026, 8, 14), title="期限切れ"),
        ]
        monkeypatch.setattr(main, "load_raw_issues", lambda: raw)
        body = TestClient(main.app).get("/").text
        assert "期限切れの外部待ち" in body
        # 戻ってくる日が一覧と補足の両方から読める
        assert "11/23" in body
        assert "復帰" in body

    def test_index_survives_bd_failure(self, monkeypatch):
        from fastapi.testclient import TestClient

        def boom():
            raise RuntimeError("bd not found")

        monkeypatch.setattr(main, "load_raw_issues", boom)
        client = TestClient(main.app)
        res = client.get("/")
        assert res.status_code == 200
        assert "bd" in res.text


class TestFavicon:
    def test_favicon_matches_the_triage_workbench(self):
        from fastapi.testclient import TestClient

        res = TestClient(main.app).get("/favicon.svg")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("image/svg+xml")
        assert 'aria-label="棚卸しリスト"' in res.text
        assert "<path" in res.text
        assert res.text.count("<rect") == 7

    def test_page_cache_busts_the_updated_favicon(self):
        assert 'href="/favicon.svg?v=2"' in main.render_page([], date(2026, 8, 24))


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


class TestCohortFlow:
    """残が減ったとき、閉じたのか外部待ちへ送っただけなのかを分ける。

    8/22-23 に両方が同時に起きた (68→33 の一括クローズと、28件の defer)。
    残存率だけを見ていると、送っただけの週も収束したように読める。
    """

    def _week(self):
        return main.parse_issues([
            issue("a", iso(2026, 8, 17), closed=iso(2026, 8, 18), status="closed"),
            issue("b", iso(2026, 8, 18), closed=iso(2026, 8, 18), status="closed"),
            issue("c", iso(2026, 8, 19), status="deferred", defer_until=iso(2026, 11, 23)),
            issue("d", iso(2026, 8, 20)),
        ])

    def test_closed_and_deferred_are_counted_separately(self):
        row = main.cohort_table(self._week(), today=date(2026, 8, 24))[0]
        assert (row.created, row.closed, row.remaining, row.deferred) == (4, 2, 2, 1)

    def test_closed_counts_every_close_not_only_same_day(self):
        # 同日クローズは1件だけだが、閉じたのは2件。
        row = main.cohort_table(self._week(), today=date(2026, 8, 24))[0]
        assert (row.same_day, row.closed) == (1, 2)

    def test_page_shows_the_deferred_share_of_the_remainder(self):
        page = main.render_page(self._week(), date(2026, 8, 24))
        assert "うち外部待ち" in page
