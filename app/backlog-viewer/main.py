"""backlog-viewer: 残タスクが収束しない理由を可視化する (port 8509)。

read-only。bd の DB には一切書かない。棚卸しの実行は画面が生成した
bd close / bd defer の1行をコピペして人間が叩く。

集計はすべて JST。bd の created_at/closed_at は UTC なので、変換せずに
日付を切ると深夜作業の分が前日にずれる。
"""

from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

JST = ZoneInfo("Asia/Tokyo")

# 積み上げグラフの層キー。通常の層は「作成週の月曜日」(date)、
# deferred だけは作成週から抜いてこの sentinel の層へ移す。
DEFERRED_LAYER = "deferred"
# 外部待ちへ送る defer に付ける復帰日の初期値。期限なしの defer は戻る日が来ず放置と同じなので、
# これまで手で付けてきた3ヶ月に揃える。
DEFER_DAYS = 90
# これを超えて動きが無ければ「止まった」「滞留した」とみなす。滞留日数の警告色と揃える。
STALE_DAYS = 14

# 未クローズとみなす status。bd は closed 以外に open / in_progress / deferred を返す。
OPEN_STATUSES = ("open", "in_progress", "deferred")

# systemd --user の PATH は /usr/bin 等だけで ~/.local/bin を含まない。
# PATH 頼みにすると journal には何も出ないままエラーページだけが出る。
FALLBACK_BD_PATHS = (
    os.path.expanduser("~/.local/bin/bd"),
    "/usr/local/bin/bd",
)

app = FastAPI(title="backlog-viewer")


# ---------------------------------------------------------------- データ取得


def jst_date(value: str | None) -> date | None:
    """bd の ISO8601 (UTC) を JST の日付にする。"""
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(JST).date()


def week_start(d: date) -> date:
    """その日が属する週の月曜日。"""
    return d - timedelta(days=d.weekday())


@dataclass(frozen=True)
class Issue:
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    created: date
    closed: date | None
    updated: date
    started: date | None
    # 凍結の解除予定日。bd defer --until で入る。None は「期限を決めずに伏せた」で、
    # 期限切れを検知できないため通知に出せない (2026-08-22 に uic3/9sa が5〜8日
    # 埋もれていたのがこれ)。凍結には必ず期限を入れる運用にした。
    defer_until: date | None = None
    labels: tuple[str, ...] = ()
    # blocks 依存を持つか。契機が具体的にあるもの (例: X クレジット復旧待ち) は
    # 期限ではなく依存で表現するため、期限なしでも催促しない。
    has_blocker: bool = False
    # 打ち切るかどうかをタイトル1行で決めずに済むよう、一覧で開いて読めるようにする。
    description: str = ""
    acceptance: str = ""

    @property
    def deferred(self) -> bool:
        return self.status == "deferred"

    @property
    def actor(self) -> str:
        """誰が動かせるか。owner / decision / agent。

        owner はエージェントに物理的に不可能なもの (提供元へのログイン、外部への
        問い合わせ、実機確認)。decision は技術的には可能だが判断が要るもの (価格・
        文面・原稿の方向性)。両方付いていたら owner。物理的な不可能のほうが強い。

        判定は人がラベルで付ける。題名からの推定は外れる (ats030-y9fb.5 は一見
        実装タスクだが、起票時に「実機で確認してから判断」と決まっている)。
        human ラベルは bd human list が使う既存の仕組みで、新しく作っていない。
        """
        if "human" in self.labels:
            return "owner"
        if "decision" in self.labels:
            return "decision"
        return "agent"

    @property
    def freeze_record(self) -> bool:
        """「<アプリ名> を凍結中」の記録か。タスクではないので残件と分けて数える。

        題名で判定する。app-portal の記録漏れ検出も同じ約束を見ており、二重管理に
        ならない (ats030-5f0i)。
        """
        return "凍結中" in self.title

    def freeze_expired(self, today: date) -> bool:
        """凍結の期限が過ぎているか。bd は期限が来ても自動では戻さない。"""
        return self.deferred and self.defer_until is not None and self.defer_until <= today

    def freeze_undated(self) -> bool:
        """期限も契機も無く伏せてあるもの。放っておくと二度と見ない。

        blocks 依存があるものは除く。契機が具体的にあり、その issue が閉じたときに
        戻ってくるため、期限を切る必要がない。ここを区別しないと、正しく依存で
        表現したものまで毎週催促することになる。
        """
        return self.deferred and self.defer_until is None and not self.has_blocker

    @property
    def cohort(self) -> date:
        return week_start(self.created)

    def open_on(self, day: date) -> bool:
        if self.created > day:
            return False
        return self.closed is None or self.closed > day

    def layer_on(self, day: date):
        """その日にこの issue が乗る層。

        defer した日は bd に記録が残らないので updated_at で近似する。
        6件中ほとんどが created == updated なので実害は小さいが、
        画面には注記を出すこと。
        """
        if self.deferred and self.updated <= day:
            return DEFERRED_LAYER
        return self.cohort


def parse_issues(raw: list[dict]) -> list[Issue]:
    issues = []
    for r in raw:
        created = jst_date(r.get("created_at"))
        if created is None:
            continue
        issues.append(
            Issue(
                id=r.get("id", ""),
                title=r.get("title", ""),
                status=r.get("status", "open"),
                priority=int(r.get("priority", 3)),
                issue_type=r.get("issue_type", "task"),
                created=created,
                closed=jst_date(r.get("closed_at")),
                updated=jst_date(r.get("updated_at")) or created,
                started=jst_date(r.get("started_at")),
                defer_until=jst_date(r.get("defer_until")),
                labels=tuple(r.get("labels") or ()),
                has_blocker=any(d.get("type") == "blocks"
                                for d in (r.get("dependencies") or [])),
                description=r.get("description") or "",
                acceptance=r.get("acceptance_criteria") or "",
            )
        )
    return issues


def bd_binary() -> str:
    found = shutil.which("bd")
    if found:
        return found
    for candidate in FALLBACK_BD_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "bd"


def load_raw_issues() -> list[dict]:
    """bd から全件を取る。JSONL は export.interval で最大60秒古いので使わない。"""
    result = subprocess.run(
        [bd_binary(), "list", "--status=all", "--json", "--limit", "0"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/home/ats030",
    )
    if result.returncode != 0:
        raise RuntimeError(f"bd list が失敗した (exit {result.returncode}): {result.stderr.strip()[:300]}")
    return json.loads(result.stdout)


# ------------------------------------------------------------------ 集計


class Series:
    """日次 × 層 の残件数。"""

    def __init__(self, days: list[date], layers: list, counts: dict):
        self.days = days
        self.layers = layers
        self.counts = counts

    def count_on(self, day: date, layer) -> int:
        return self.counts.get((day, layer), 0)

    def total_on(self, day: date) -> int:
        return sum(self.counts.get((day, layer), 0) for layer in self.layers)

    @property
    def peak(self) -> int:
        return max((self.total_on(d) for d in self.days), default=0)


def daily_series(issues: list[Issue], today: date) -> Series:
    if not issues:
        return Series([today], [], {})

    start = min(i.created for i in issues)
    days = []
    cur = start
    while cur <= today:
        days.append(cur)
        cur += timedelta(days=1)

    counts: dict = {}
    for day in days:
        for issue in issues:
            if not issue.open_on(day):
                continue
            key = (day, issue.layer_on(day))
            counts[key] = counts.get(key, 0) + 1

    cohorts = sorted({k[1] for k in counts if k[1] != DEFERRED_LAYER})
    layers = cohorts + ([DEFERRED_LAYER] if any(k[1] == DEFERRED_LAYER for k in counts) else [])
    return Series(days, layers, counts)


@dataclass(frozen=True)
class CohortRow:
    week: date
    created: int
    remaining: int
    same_day: int
    p3: int
    # 残の内訳。残が減っても、閉じたのか外部待ちへ送っただけなのかで意味が
    # 逆になる。8/22-23 は両方が同時に起きて、画面からは区別できなかった。
    closed: int = 0
    deferred: int = 0

    @property
    def residual_rate(self) -> float:
        return round(self.remaining / self.created * 100, 1) if self.created else 0.0

    @property
    def same_day_rate(self) -> float:
        """その週に作った全件のうち、作った日に閉じた割合。

        母数を「閉じた件」にすると作りっぱなしの件が分母から消えて率が良く
        見えるので、作成件数を母数にする。
        """
        return round(self.same_day / self.created * 100, 1) if self.created else 0.0

    @property
    def p3_share(self) -> float:
        return round(self.p3 / self.created * 100, 1) if self.created else 0.0


def cohort_table(issues: list[Issue], today: date) -> list[CohortRow]:
    created: dict[date, int] = {}
    remaining: dict[date, int] = {}
    same_day: dict[date, int] = {}
    p3: dict[date, int] = {}
    closed: dict[date, int] = {}
    deferred: dict[date, int] = {}
    for issue in issues:
        created[issue.cohort] = created.get(issue.cohort, 0) + 1
        if issue.open_on(today):
            remaining[issue.cohort] = remaining.get(issue.cohort, 0) + 1
            if issue.deferred:
                deferred[issue.cohort] = deferred.get(issue.cohort, 0) + 1
        if issue.closed is not None:
            closed[issue.cohort] = closed.get(issue.cohort, 0) + 1
        if issue.closed is not None and issue.closed == issue.created:
            same_day[issue.cohort] = same_day.get(issue.cohort, 0) + 1
        if issue.priority >= 3:
            p3[issue.cohort] = p3.get(issue.cohort, 0) + 1
    return [
        CohortRow(w, created[w], remaining.get(w, 0), same_day.get(w, 0), p3.get(w, 0),
                  closed.get(w, 0), deferred.get(w, 0))
        for w in sorted(created)
    ]


@dataclass(frozen=True)
class BacklogRow:
    id: str
    title: str
    priority: int
    issue_type: str
    age_days: int
    idle_days: int
    deferred: bool
    started: bool
    cohort: date
    freeze_record: bool = False
    actor: str = "agent"
    defer_until: date | None = None
    description: str = ""
    acceptance: str = ""


def backlog_rows(issues: list[Issue], today: date) -> list[BacklogRow]:
    rows = [
        BacklogRow(
            id=i.id,
            title=i.title,
            priority=i.priority,
            issue_type=i.issue_type,
            age_days=(today - i.created).days,
            idle_days=(today - i.updated).days,
            deferred=i.deferred,
            started=i.started is not None,
            cohort=i.cohort,
            freeze_record=i.freeze_record,
            actor=i.actor,
            defer_until=i.defer_until,
            description=i.description,
            acceptance=i.acceptance,
        )
        for i in issues
        if i.open_on(today)
    ]
    return sorted(rows, key=lambda r: (-r.age_days, r.id))


def split_rows(rows: list[BacklogRow]) -> tuple[list[BacklogRow], list[BacklogRow]]:
    """タスクと凍結の記録に分ける。混ざると探しているものが埋もれる。"""
    return ([r for r in rows if not r.freeze_record],
            [r for r in rows if r.freeze_record])


@dataclass(frozen=True)
class Metrics:
    remaining: int
    deferred: int
    over_30_days: int
    claim_rate: float
    same_day_close_rate: float
    median_age: int
    median_lead_time: int
    freeze_expired: int
    freeze_undated: int
    # 動かせる残件。外部待ちを除いた数。見出しはこちらを主にする。
    actionable: int
    by_agent: int
    by_owner: int
    by_decision: int
    # 「〜を凍結中」の記録。タスクではない。
    freeze_records: int
    # 外部待ちが最も多く戻ってくる日と、その日の件数。(日付, 件数) か None。
    # 「次の日」ではなく最大の山を出す。8/24 時点で次の復帰日は 8/30 の1件だが、
    # 本当に効くのは 11/23 の19件で、これが戻ると動かせる残件は 8 から 27 になる。
    # 早い順に見ていると山を見落とす (ats030-4nw7)。
    peak_return: tuple[date, int] | None = None


def _peak_return(remaining: list[Issue], today: date) -> tuple[date, int] | None:
    """外部待ちが最も多く戻ってくる日と件数。期限切れは別に数えるので含めない。

    同数なら早い日を採る。まとめて defer した日の3ヶ月後に山ができるため、
    一度に何件戻るかが判らないと、その日に棚卸しが一気に必要になる。
    """
    days = [i.defer_until for i in remaining
            if i.deferred and i.defer_until is not None and i.defer_until > today]
    if not days:
        return None
    counts = {d: days.count(d) for d in set(days)}
    peak = max(counts, key=lambda d: (counts[d], -d.toordinal()))
    return peak, counts[peak]


def metrics(issues: list[Issue], today: date) -> Metrics:
    remaining = [i for i in issues if i.open_on(today)]
    closed = [i for i in issues if i.closed is not None]
    same_day = [i for i in closed if i.closed == i.created]
    ages = [(today - i.created).days for i in remaining]
    leads = [(i.closed - i.created).days for i in closed]
    return Metrics(
        remaining=len(remaining),
        deferred=sum(1 for i in remaining if i.deferred),
        over_30_days=sum(1 for a in ages if a > 30),
        claim_rate=round(sum(1 for i in remaining if i.started) / len(remaining) * 100, 1) if remaining else 0.0,
        same_day_close_rate=round(len(same_day) / len(closed) * 100, 1) if closed else 0.0,
        median_age=int(median(ages)) if ages else 0,
        median_lead_time=int(median(leads)) if leads else 0,
        freeze_expired=sum(1 for i in remaining if i.freeze_expired(today)),
        freeze_undated=sum(1 for i in remaining if i.freeze_undated()),
        actionable=sum(1 for i in remaining if not i.deferred),
        by_agent=sum(1 for i in remaining if not i.deferred and i.actor == "agent"),
        by_owner=sum(1 for i in remaining if not i.deferred and i.actor == "owner"),
        by_decision=sum(1 for i in remaining if not i.deferred and i.actor == "decision"),
        freeze_records=sum(1 for i in remaining if i.freeze_record),
        peak_return=_peak_return(remaining, today),
    )


# ------------------------------------------------------------------ 描画

# 依存を足さないために SVG は自前で組み立てる。ライブラリを1つ入れると
# ライセンス確認と更新追従が新しい運用タスクになる。

SVG_W, SVG_H = 960, 300
# 右に余白を残すのは、狭い画面で右端 (直近) までスクロールしたときにも
# y 軸の値を読めるよう、目盛ラベルを左右の両方に置くため。
PLOT = (46, 12, 906, 262)  # x0, y0, x1, y1


def _cohort_color(index: int, total: int) -> str:
    """コホート層の色。accent (#7c3aed) の明度違いだけで階調を作る。

    DESIGN.md が多色パレットを禁じているため、色相は固定して古い層を暗く、
    新しい層を明るくする。
    """
    if total <= 1:
        return "hsl(258 70% 52%)"
    lightness = 26 + (index / (total - 1)) * 42
    return f"hsl(258 70% {lightness:.0f}%)"


def _layer_color(layer, index: int, cohort_count: int) -> str:
    if layer == DEFERRED_LAYER:
        return "#3f3f46"
    return _cohort_color(index, cohort_count)


def _layer_label(layer, today: date) -> str:
    """凡例と tooltip に出す層の名前。

    層の色は明度で古さを表しているので、ラベルもその軸に揃えて相対週で書く。
    絶対日付 (6/1〜) だと 10 層あるうちのどれが古いのかを読むたびに今日からの
    引き算が要る。「12週前」なら色の暗さとそのまま対応する。絶対日付は
    tooltip に残すので、x 軸と突き合わせたいときはそちらを見る。
    """
    if layer == DEFERRED_LAYER:
        return "外部待ち"
    weeks = (week_start(today) - layer).days // 7
    if weeks <= 0:
        return "今週"
    if weeks == 1:
        return "先週"
    return f"{weeks}週前"


def _nice_ceiling(value: int) -> int:
    if value <= 0:
        return 1
    step = 10 if value <= 100 else 50
    return ((value + step - 1) // step) * step


def render_stacked_svg(series: Series, today: date) -> str:
    x0, y0, x1, y1 = PLOT
    ymax = _nice_ceiling(series.peak)
    days = series.days
    n = len(days)

    def px(i: int) -> float:
        return x0 if n <= 1 else x0 + i * (x1 - x0) / (n - 1)

    def py(v: float) -> float:
        return y1 - (v / ymax) * (y1 - y0)

    parts = [
        # width/height を属性で持たせる。viewBox だけだと intrinsic size が
        # 確定せず、高さを 150px と解釈するブラウザ (Safari) でグラフが潰れる。
        # 実際の寸法は CSS (.chart svg) 側で決める。
        f'<svg viewBox="0 0 {SVG_W} {SVG_H}" width="{SVG_W}" height="{SVG_H}" role="img" '
        f'aria-label="残件数の推移 (作成週コホート積み上げ)">'
    ]

    # 水平グリッドと y 軸目盛
    for t in range(0, 5):
        v = ymax * t / 4
        y = py(v)
        parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="#242633" stroke-width="1"/>')
        for tx, anchor in ((x0 - 8, "end"), (x1 + 8, "start")):
            parts.append(
                f'<text x="{tx}" y="{y + 4:.1f}" text-anchor="{anchor}" '
                f'fill="#71717a" font-size="11">{v:.0f}</text>'
            )

    cohort_layers = [l for l in series.layers if l != DEFERRED_LAYER]
    base = [0.0] * n
    for layer in series.layers:
        idx = cohort_layers.index(layer) if layer != DEFERRED_LAYER else 0
        color = _layer_color(layer, idx, len(cohort_layers))
        top = [base[i] + series.count_on(days[i], layer) for i in range(n)]
        upper = " ".join(f"{px(i):.1f},{py(top[i]):.1f}" for i in range(n))
        lower = " ".join(f"{px(i):.1f},{py(base[i]):.1f}" for i in range(n - 1, -1, -1))
        label = (
            "外部待ち (deferred)" if layer == DEFERRED_LAYER
            else f"{_layer_label(layer, today)} ({layer:%-m/%-d}〜)"
        )
        parts.append(
            f'<polygon points="{upper} {lower}" fill="{color}" stroke="{color}" stroke-width="0.5">'
            f"<title>{html.escape(label)}</title></polygon>"
        )
        base = top

    # x 軸: 月が変わる日にだけラベルを置く
    parts.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="#343747" stroke-width="1"/>')
    for i, d in enumerate(days):
        if d.day != 1 and i != 0:
            continue
        x = px(i)
        parts.append(f'<line x1="{x:.1f}" y1="{y1}" x2="{x:.1f}" y2="{y1 + 5}" stroke="#343747" stroke-width="1"/>')
        parts.append(
            f'<text x="{x:.1f}" y="{y1 + 20}" text-anchor="middle" fill="#71717a" font-size="11">'
            f"{d:%-m/%-d}</text>"
        )

    parts.append("</svg>")
    return "".join(parts)


def render_legend(series: Series, today: date) -> str:
    cohort_layers = [l for l in series.layers if l != DEFERRED_LAYER]
    items = []
    for layer in series.layers:
        idx = cohort_layers.index(layer) if layer != DEFERRED_LAYER else 0
        color = _layer_color(layer, idx, len(cohort_layers))
        label = _layer_label(layer, today)
        tip = "" if layer == DEFERRED_LAYER else f' title="{layer:%Y-%m-%d}〜 に作成"'
        items.append(
            f'<span class="legend-item"{tip}><i style="background:{color}"></i>'
            f"{html.escape(label)}</span>"
        )
    return "".join(items)


CSS = """
/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
/* Hallmark · genre: modern-minimal · macrostructure: Workbench · design-system: DESIGN.md · designed-as-app */
:root {
  --bg: #08090c; --surface: #0d0f14; --raised: #12141b; --hover: #171923;
  --border: #242633; --border-strong: #343747; --text: #f4f4f5;
  --muted: #a1a1aa; --subtle: #71717a; --accent: #7c3aed; --accent-soft: #a78bfa;
  --success: #34d399; --warning: #fbbf24; --danger: #fb7185;
  --accent-hover: #6d28d9; --accent-wash: rgba(124,58,237,.16);
  --muted-wash: rgba(161,161,170,.14); --owner-wash: rgba(244,63,94,.16);
  --owner-text: #fda4af; --decision-wash: rgba(245,158,11,.16);
  --decision-text: #fcd34d; --on-accent: #fff;
  --font-body: Inter, "SF Pro", "Segoe UI", Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
}
* { box-sizing: border-box; }
html, body { overflow-x: clip; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: var(--font-body); font-size: 14px; line-height: 1.6;
}
.wrap { max-width: 1200px; margin: 0 auto; padding: 24px 24px 88px; }
body.has-selection .wrap { padding-bottom: 220px; }
h1 { font-size: 18px; font-weight: 600; font-style: normal; margin: 0 0 2px;
  overflow-wrap: anywhere; min-width: 0; }
h2 { font-size: 14px; font-weight: 600; font-style: normal; margin: 0; color: var(--text); }
.sub { color: var(--subtle); font-size: 12px; margin: 0 0 16px; }
.tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 20px; }
.tile { background: var(--raised); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.tile .v { font-size: 22px; font-weight: 600; }
.tile .k { color: var(--subtle); font-size: 12px; }
.tile .n { color: var(--subtle); font-size: 11px; margin-top: 2px; }
a.tile { display: block; color: inherit; text-decoration: none; }
a.tile:hover { background: var(--hover); border-color: var(--border-strong); }
a.tile:focus-visible { outline: 2px solid var(--accent-soft); outline-offset: 2px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.fold-body > .panel + .panel { margin-top: 8px; }
.section-head { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin: 20px 0 8px; }
.section-count { color: var(--subtle); font-size: 12px; font-variant-numeric: tabular-nums; }
.fold { border-top: 1px solid var(--border); margin-top: 24px; }
.fold > summary { cursor: pointer; list-style: none; display: flex; align-items: baseline;
  justify-content: space-between; gap: 12px; padding: 14px 0; color: var(--muted); }
.fold > summary::-webkit-details-marker { display: none; }
.fold > summary::before { content: "›"; color: var(--subtle); font-size: 18px; line-height: 1; }
.fold[open] > summary::before { transform: rotate(90deg); }
.fold > summary strong { color: var(--text); font-size: 14px; font-weight: 600; margin-right: auto; }
.fold-body { padding-bottom: 8px; }
.legend { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
.legend-item { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--muted); }
.legend-item i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.note { color: var(--subtle); font-size: 11px; margin-top: 10px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-weight: 500; color: var(--subtle); font-size: 12px;
  border-bottom: 1px solid var(--border); padding: 6px 8px; }
td { border-bottom: 1px solid var(--border); padding: 6px 8px; vertical-align: top; }
tbody tr:hover { background: var(--hover); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.id { color: var(--accent-soft); font-family: var(--font-mono); font-size: 12px; }
.chip { display: inline-block; padding: 0 6px; border-radius: 4px; font-size: 11px;
  background: var(--accent-wash); color: var(--accent-soft); margin-left: 6px; }
.chip.gray { background: var(--muted-wash); color: var(--muted); }
.chip.faint { background: transparent; color: var(--subtle); box-shadow: inset 0 0 0 1px var(--border); }
.chip.owner { background: var(--owner-wash); color: var(--owner-text); }
.chip.decision { background: var(--decision-wash); color: var(--decision-text); }
.chip.started { background: transparent; color: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--accent-soft); }
.defer-box { display: grid; gap: 6px; }
.defer-date { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--muted); font-size: 12px; }
.defer-date input { background: var(--raised); color: var(--text); border: 1px solid var(--border-strong);
  border-radius: 6px; padding: 3px 8px; font: inherit; color-scheme: dark; }
.desc > summary { cursor: pointer; list-style: none; }
.desc > summary::-webkit-details-marker { display: none; }
.desc > summary:hover { color: var(--accent-soft); }
.desc-body { margin: 6px 0 2px; padding: 8px 10px; background: var(--raised);
  border: 1px solid var(--border); border-radius: 6px; color: var(--muted);
  font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; max-width: 72ch; }
.desc-label { color: var(--subtle); font-weight: 600; }
.hot { color: var(--danger); }
.warn { color: var(--warning); }
.scroll { overflow-x: auto; }
.chart svg { display: block; width: 100%; min-width: 720px; height: auto; }
.scroll-hint { display: none; color: var(--subtle); font-size: 11px; margin: 8px 0 0; }
.chart.scrollable ~ .scroll-hint { display: block; }
.bar { display: inline-block; height: 8px; border-radius: 2px; background: var(--accent); vertical-align: middle; }
input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; cursor: pointer; }
.dock {
  position: fixed; left: 0; right: 0; bottom: 0; background: var(--surface);
  border-top: 1px solid var(--border-strong); padding: 10px 24px;
}
.dock-inner { max-width: 1200px; margin: 0 auto; }
.dock-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.dock-actions { display: none; gap: 8px; margin-left: auto; }
.dock.active .dock-actions { display: flex; }
.dock-output { display: none; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; margin-top: 8px; }
.dock.active .dock-output { display: grid; }
button {
  background: var(--raised); color: var(--text); border: 1px solid var(--border-strong);
  border-radius: 6px; padding: 5px 12px; font-size: 13px; cursor: pointer;
  font-family: var(--font-body); white-space: nowrap;
}
button:hover { background: var(--hover); }
button:focus-visible, summary:focus-visible, input:focus-visible {
  outline: 2px solid var(--accent-soft); outline-offset: 2px;
}
button.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
button.primary:hover { background: var(--accent-hover); }
button:disabled { opacity: .55; cursor: not-allowed; }
select {
  background: var(--raised); color: var(--text); border: 1px solid var(--border-strong);
  border-radius: 6px; padding: 5px 28px 5px 10px; font: inherit; cursor: pointer;
}
select:focus-visible { outline: 2px solid var(--accent-soft); outline-offset: 2px; }
th[data-sort-key].sorted::after { content: " ▾"; color: var(--accent-soft); }
.fold-picked { color: var(--accent-soft); }
.section-tools { display: inline-flex; align-items: baseline; gap: 12px; }
.sort-control { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
textarea {
  width: 100%; background: var(--raised); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 10px; font-family: var(--font-mono);
  font-size: 12px; resize: vertical; min-height: 62px;
}
textarea:focus { outline: 2px solid var(--accent-soft); outline-offset: 1px; border-color: var(--accent); }
.count { color: var(--subtle); font-size: 12px; }
.err { border-color: var(--danger); color: var(--danger); }
@media (max-width: 640px) {
  .wrap { padding: 16px 12px 76px; }
  body.has-selection .wrap { padding-bottom: 220px; }
  .tiles { grid-template-columns: 1fr; }
  .section-head { align-items: flex-start; }
  .dock { padding: 8px 12px; }
  .dock-output { grid-template-columns: 1fr; gap: 6px; margin-top: 6px; }
  /* 狭い画面で折り返すと欄が伸びて一覧を覆う。1行1コマンドのまま横に送る。 */
  .dock textarea { min-height: 0; height: 44px; padding: 5px 8px; font-size: 11px;
    white-space: pre; overflow-wrap: normal; overflow-x: auto; resize: none; }
  .dock #cmd-defer { height: 30px; }
  .hide-sm { display: none; }
}
"""


JS = """
const TODAY = "__TODAY__";
// 復帰日ごとの既存の外部待ち件数。同じ日へ積み増していないかを選ぶときに見せる。
const RETURNS = __RETURNS__;
function picked() {
  return Array.from(document.querySelectorAll('.pick:checked')).map(e => e.value);
}
function build(kind, ids) {
  if (!ids.length) return '';
  if (kind === 'close') {
    // 事情の違う行に同じ理由を付けないよう、理由ごとに1行ずつ出す。
    const groups = new Map();
    ids.forEach(id => {
      const reason = document.querySelector('tr[data-id="' + CSS.escape(id) + '"]').dataset.closeReason;
      if (!groups.has(reason)) groups.set(reason, []);
      groups.get(reason).push(id);
    });
    return Array.from(groups, ([reason, group]) =>
      'bd close ' + group.join(' ') + ' -r "棚卸し ' + TODAY + ': ' + reason + '"').join('\\n');
  }
  return 'bd defer ' + ids.join(' ') + ' --until=' + document.getElementById('defer-until').value;
}
function refresh() {
  const ids = picked();
  document.getElementById('cmd-close').value = build('close', ids);
  document.getElementById('cmd-defer').value = build('defer', ids);
  const load = RETURNS[document.getElementById('defer-until').value] || 0;
  document.getElementById('defer-load').textContent = load ? 'この日に戻る外部待ち ' + load + '件' : 'この日に戻る外部待ちなし';
  document.getElementById('count').textContent = ids.length ? ids.length + ' 件を選択中' : 'タスクを選択';
  document.querySelectorAll('.copy').forEach(b => { b.disabled = ids.length === 0; });
  document.getElementById('dock').classList.toggle('active', ids.length > 0);
  document.body.classList.toggle('has-selection', ids.length > 0);
  // 見出しの全選択は、個別の選択に合わせて全部/一部/なしを示す。
  document.querySelectorAll('.pick-all').forEach(all => {
    const boxes = Array.from(all.closest('table').querySelectorAll('.pick'));
    const n = boxes.filter(e => e.checked).length;
    all.checked = n > 0 && n === boxes.length;
    all.indeterminate = n > 0 && n < boxes.length;
  });
  // 閉じた一覧の中の選択も、見出しから見えるようにする。
  document.querySelectorAll('.fold-picked').forEach(el => {
    const n = el.closest('details').querySelectorAll('.pick:checked').length;
    el.textContent = n ? n + '件選択中 · ' : '';
  });
}
async function copyFrom(id, button) {
  const el = document.getElementById(id);
  if (!el.value) return;
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(el.value);
      ok = true;
    }
  } catch (e) { ok = false; }
  if (!ok) {
    el.focus(); el.select();
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  }
  const original = button.dataset.label;
  button.textContent = ok ? 'コピーした' : '手動でコピーしてください';
  setTimeout(() => { button.textContent = original; }, 1600);
}
function toggleAll(source) {
  source.closest('table').querySelectorAll('.pick').forEach(e => { e.checked = source.checked; });
  refresh();
}
function compareRows(left, right, order) {
  const age = Number(right.dataset.age) - Number(left.dataset.age);
  if (order === "age") return age || left.dataset.id.localeCompare(right.dataset.id);
  const priority = Number(left.dataset.priority) - Number(right.dataset.priority);
  return priority || age || left.dataset.id.localeCompare(right.dataset.id);
}
function sortTables(order) {
  document.querySelectorAll("tbody[data-sortable]").forEach(body => {
    Array.from(body.rows).sort((left, right) => compareRows(left, right, order))
      .forEach(row => body.appendChild(row));
  });
  // どの一覧でも、何の順に並んでいるかを列見出しで示す。
  document.querySelectorAll('th[data-sort-key]').forEach(th => {
    const on = th.dataset.sortKey === order;
    th.classList.toggle('sorted', on);
    if (on) th.setAttribute('aria-sort', order === 'age' ? 'descending' : 'ascending');
    else th.removeAttribute('aria-sort');
  });
}
function showRows(event, test) {
  // 該当する行は閉じた一覧に沈みやすいので、その一覧を開いて先頭の行へ移る。
  event.preventDefault();
  const rows = Array.from(document.querySelectorAll('tbody[data-sortable] tr')).filter(test);
  rows.forEach(row => { const fold = row.closest('details'); if (fold) fold.open = true; });
  if (rows.length) rows[0].scrollIntoView({block: 'center'});
}
function chartToLatest(move) {
  document.querySelectorAll('.chart').forEach(el => {
    const scrollable = el.scrollWidth > el.clientWidth + 1;
    el.classList.toggle('scrollable', scrollable);
    if (scrollable && move) el.scrollLeft = el.scrollWidth;
  });
}
document.addEventListener('DOMContentLoaded', () => {
  const sort = document.getElementById('sort-order');
  sortTables(sort.value);
  sort.addEventListener('change', () => sortTables(sort.value));
  document.getElementById('defer-until').addEventListener('input', refresh);
  chartToLatest(true);
  window.addEventListener('resize', () => chartToLatest(false));
  document.querySelectorAll('.pick').forEach(e => e.addEventListener('change', refresh));
  const over30 = document.getElementById('tile-over30');
  if (over30) over30.addEventListener('click', e => showRows(e, row => Number(row.dataset.age) > 30));
  const expired = document.getElementById('tile-expired');
  if (expired) expired.addEventListener('click', e => showRows(e, row => 'expired' in row.dataset));
  document.getElementById('clear-picks').addEventListener('click', () => {
    document.querySelectorAll('.pick:checked').forEach(e => { e.checked = false; });
    refresh();
  });
  document.querySelectorAll('.copy').forEach(b => {
    b.dataset.label = b.textContent;
    b.addEventListener('click', () => copyFrom(b.dataset.target, b));
  });
  refresh();
});
"""


def _priority_chip(p: int) -> str:
    # 新しい色相は足さず、濃さの段差で P0-1 / P2 / P3 以下を見分ける。
    cls = "chip" if p <= 1 else "chip gray" if p == 2 else "chip faint"
    return f'<span class="{cls}">P{p}</span>'


def _return_note(m: "Metrics") -> str:
    if m.peak_return is None:
        return ""
    day, count = m.peak_return
    return f" · 最大の復帰 {day:%-m/%-d} に {count}件"


def _is_expired(row: "BacklogRow", today: date) -> bool:
    return row.deferred and row.defer_until is not None and row.defer_until <= today


def _expired_note(rows, today: date) -> str:
    days = [r.defer_until for r in rows if _is_expired(r, today)]
    if not days:
        return "期限切れなし"
    oldest = min(days)
    return f"最も古い期限 {oldest:%-m/%-d}({(today - oldest).days}日超過)"


def _over30_note(action_rows, deferred_rows, cold_rows) -> str:
    counts = [(label, sum(1 for r in rows if r.age_days > 30)) for label, rows in (
        ("判断", action_rows), ("外部待ち", deferred_rows), ("凍結", cold_rows))]
    parts = [f"{label} {n}" for label, n in counts if n]
    return " · ".join(parts) if parts else "打ち切りの候補なし"


def _return_cell(row: "BacklogRow", today: date) -> str:
    """外部待ちが戻ってくる日。タスクとして動かせる日でもある。"""
    if not row.deferred:
        return ""
    if row.defer_until is None:
        # 期限も契機も無いものは、戻る日が来ないので放置と同じ。
        return '<span class="warn">未設定</span>'
    cls = "hot" if row.defer_until <= today else ""
    return f'<span class="{cls}">{row.defer_until:%-m/%-d}</span>'


def _close_reason(row: "BacklogRow", today: date) -> str:
    """打ち切る事情。行ごとに違う理由を、閉じた記録に残す。"""
    if row.freeze_record:
        return "凍結の記録を整理"
    if row.deferred:
        if row.defer_until is None:
            return "外部待ちのまま復帰日が決まらなかったため打ち切り"
        if row.defer_until <= today:
            return f"外部待ちの復帰日 {row.defer_until:%-m/%-d} を過ぎても再開されなかったため打ち切り"
        return "外部待ちの解消を待たずに打ち切り"
    # 最近動いた行に「止まった」「滞留した」と書くと、事実と違う記録が残る。
    if row.started:
        if row.idle_days > STALE_DAYS:
            return "着手後に更新が止まったため打ち切り"
        return "着手中のまま打ち切り"
    if row.age_days > STALE_DAYS:
        return "着手されないまま滞留したため打ち切り"
    return "着手前に打ち切り"


def _title_cell(r: "BacklogRow", chips: str) -> str:
    """タイトルを開くと description と acceptance が読める。本文が無ければ開かせない。"""
    title = html.escape(r.title) + chips
    parts = [html.escape(r.description)] if r.description else []
    if r.acceptance:
        parts.append(f'<span class="desc-label">完了条件</span>\n{html.escape(r.acceptance)}')
    if not parts:
        return title
    body = "\n\n".join(parts)
    return (f'<details class="desc"><summary>{title}</summary>'
            f'<div class="desc-body">{body}</div></details>')


def _age_cell(days: int) -> str:
    cls = "hot" if days > 30 else ("warn" if days > STALE_DAYS else "")
    return f'<span class="{cls}">{days}</span>'


def render_page(issues: list[Issue], today: date) -> str:
    series = daily_series(issues, today)
    m = metrics(issues, today)
    cohorts = cohort_table(issues, today)
    rows = sorted(backlog_rows(issues, today),
                  key=lambda r: (r.priority, -r.age_days, r.id))


    max_created = max((c.created for c in cohorts), default=1)
    cohort_html = "".join(
        f"<tr><td>{c.week:%Y-%m-%d}〜</td>"
        f'<td class="num">{c.created}</td>'
        f'<td class="num">{c.closed}</td>'
        f'<td class="num">{c.remaining}</td>'
        f'<td class="num">{c.deferred or ""}</td>'
        f'<td class="num">{c.residual_rate}%</td>'
        f'<td class="num">{c.same_day_rate}%</td>'
        f'<td class="num">{c.p3_share}%</td>'
        f'<td><span class="bar" style="width:{max(2, round(c.created / max_created * 120))}px;'
        f'opacity:{0.25 + min(c.residual_rate, 50) / 50 * 0.75:.2f}"></span></td></tr>'
        for c in cohorts
    )

    live_rows, cold_rows = split_rows(rows)
    defer_until = today + timedelta(days=DEFER_DAYS)
    returns = dict(sorted(Counter(r.defer_until.isoformat() for r in rows
                                  if r.deferred and r.defer_until).items()))
    action_rows = [r for r in live_rows if not r.deferred]
    deferred_rows = [r for r in live_rows if r.deferred]

    # 初期画面には、棚卸し判断へ直接つながる3指標だけを置く。
    # 30日超は閉じた一覧に偏りやすいので、どの一覧にあるかを添えて辿れるようにする。
    tiles = [
        ("エージェントが進められる", str(m.by_agent),
         f"要判断 {m.by_decision} · 所有者 {m.by_owner}", ""),
        ("30日超", str(m.over_30_days), _over30_note(action_rows, deferred_rows, cold_rows),
         "tile-over30" if m.over_30_days else ""),
        ("期限切れの外部待ち", str(m.freeze_expired), _expired_note(rows, today),
         "tile-expired" if m.freeze_expired else ""),
    ]
    tile_html = "".join(
        (f'<a class="tile" id="{tid}" href="#">' if tid else '<div class="tile">')
        + f'<div class="k">{html.escape(k)}</div>'
        f'<div class="v">{html.escape(v)}</div><div class="n">{html.escape(n)}</div>'
        + ("</a>" if tid else "</div>")
        for k, v, n, tid in tiles
    )

    def _row(r, show_return: bool, show_wait: bool) -> str:
        actor_chip = "" if r.deferred else {
            "owner": '<span class="chip owner">所有者</span>',
            "decision": '<span class="chip decision">要判断</span>',
        }.get(r.actor, "")
        wait_chip = '<span class="chip gray">外部待ち</span>' if show_wait and r.deferred else ""
        # 作業中の行を、未着手の行と同じ感覚で打ち切らないように。
        started_chip = '<span class="chip started">着手済み</span>' if r.started else ""
        # 期限切れタイルから辿る目印。
        expired_attr = "data-expired " if _is_expired(r, today) else ""
        return (
            f'<tr data-age="{r.age_days}" data-priority="{r.priority}" '
            f'data-id="{html.escape(r.id, quote=True)}" {expired_attr}'
            f'data-close-reason="{html.escape(_close_reason(r, today), quote=True)}">'
            f'<td><input type="checkbox" class="pick" value="{html.escape(r.id)}" '
            f'aria-label="{html.escape(r.id)} を選択"></td>'
            f'<td class="id">{html.escape(r.id)}</td>'
            f'<td class="num">{_age_cell(r.age_days)}</td>'
            f'<td class="num hide-sm">{r.idle_days}</td>'
            + (f'<td class="num">{_return_cell(r, today)}</td>' if show_return else "")
            + f"<td>{_priority_chip(r.priority)}</td>"
            f'<td class="hide-sm">{html.escape(r.issue_type)}</td>'
            f"<td>{_title_cell(r, started_chip + wait_chip + actor_chip)}</td></tr>"
        )

    def _table(table_rows) -> str:
        if not table_rows:
            return '<div class="panel"><p class="note">該当するタスクはない。</p></div>'
        # 復帰日は外部待ちの行にしか無い。値の無い列で幅を使わない。
        show_return = any(r.deferred for r in table_rows)
        # 全行が外部待ちの一覧では、見出しと同じことを行ごとに繰り返さない。
        show_wait = show_return and not all(r.deferred for r in table_rows)
        return (
            '<div class="panel scroll"><table><thead><tr>'
            '<th><input type="checkbox" class="pick-all" onchange="toggleAll(this)" aria-label="この一覧をすべて選択"></th>'
            '<th>ID</th><th class="num" data-sort-key="age">滞留</th><th class="num hide-sm">無更新</th>'
            + ('<th class="num">復帰</th>' if show_return else "")
            + '<th data-sort-key="priority">P</th><th class="hide-sm">種別</th><th>タイトル</th>'
            f'</tr></thead><tbody data-sortable>{"".join(_row(r, show_return, show_wait) for r in table_rows)}</tbody></table></div>'
        )

    analysis_note = (
        f"全体 {m.remaining}件 · 動かせる {m.actionable}件 · 外部待ち {m.deferred}件 · "
        f"滞留中央値 {m.median_age}日 · claim率 {m.claim_rate}% · "
        f"同日クローズ率 {m.same_day_close_rate}% · リードタイム中央値 "
        + ("即日" if m.median_lead_time == 0 else f"{m.median_lead_time}日")
    )

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>backlog-viewer</title><link rel="icon" href="/favicon.svg?v=2" type="image/svg+xml">
<style>{CSS}</style><script src="http://ubuntu-server-app:8526/v.js" data-site="backlog-viewer" defer></script></head><body>
<div class="wrap">
  <h1>backlog-viewer</h1>
  <p class="sub">{today:%Y-%m-%d} (JST) · bdを直接参照 · 読み取り専用</p>

  <div class="tiles">{tile_html}</div>

  <div class="section-head">
    <h2>いま判断するタスク</h2>
    <span class="section-tools">
      <span class="section-count">{len(action_rows)}件</span>
      <label class="sort-control" for="sort-order">並び順
        <select id="sort-order" aria-label="すべてのタスク一覧の並び順">
          <option value="age">滞留順</option>
          <option value="priority" selected>優先順</option>
        </select>
      </label>
    </span>
  </div>
  {_table(action_rows)}

  <details class="fold">
    <summary><strong>外部待ち</strong><span><span class="fold-picked"></span>{len(deferred_rows)}件 · 期限切れ {m.freeze_expired}件{_return_note(m)}</span></summary>
    <div class="fold-body">{_table(deferred_rows)}</div>
  </details>

  <details class="fold">
    <summary><strong>凍結の記録</strong><span><span class="fold-picked"></span>{len(cold_rows)}件</span></summary>
    <div class="fold-body">{_table(cold_rows)}</div>
  </details>

  <details class="fold">
    <summary><strong>傾向を分析する</strong><span>推移と作成週コホート</span></summary>
    <div class="fold-body">
      <p class="note">{analysis_note}</p>
      <div class="panel">
        <div class="scroll chart">{render_stacked_svg(series, today)}</div>
        <div class="legend">{render_legend(series, today)}</div>
        <p class="scroll-hint">右端が直近。左へスクロールすると古い週が見える。</p>
        <p class="note">高さは残件数、色は作成週。外部待ちは無彩色で示す。</p>
      </div>
      <div class="panel scroll">
        <table><thead><tr><th>作成週</th><th class="num">作成</th><th class="num">閉</th>
        <th class="num">残</th><th class="num">うち外部待ち</th>
        <th class="num">残存率</th><th class="num">同日クローズ率</th><th class="num">P3の割合</th>
        <th></th></tr></thead><tbody>{cohort_html}</tbody></table>
      </div>
    </div>
  </details>
</div>

<div class="dock" id="dock"><div class="dock-inner">
  <div class="dock-row">
    <strong>棚卸し</strong><span class="count" id="count">タスクを選択</span>
    <div class="dock-actions">
      <button class="clear" id="clear-picks">選択を解除</button>
      <button class="copy primary" data-target="cmd-close">打ち切りをコピー</button>
      <button class="copy" data-target="cmd-defer">外部待ちをコピー</button>
    </div>
  </div>
  <div class="dock-output">
    <textarea id="cmd-close" readonly aria-label="bd close コマンド"></textarea>
    <div class="defer-box">
      <label class="defer-date">復帰日<input type="date" id="defer-until" value="{defer_until}" min="{today + timedelta(days=1)}">
        <span id="defer-load"></span></label>
      <textarea id="cmd-defer" readonly aria-label="bd defer コマンド"></textarea>
    </div>
  </div>
</div></div>
<script>{JS.replace("__TODAY__", today.isoformat()).replace(
    "__RETURNS__", json.dumps(returns))}</script>
</body></html>"""


def render_error(message: str) -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>backlog-viewer</title><link rel="icon" href="/favicon.svg?v=2" type="image/svg+xml"><style>{CSS}</style><script src="http://ubuntu-server-app:8526/v.js" data-site="backlog-viewer" defer></script></head><body>
<div class="wrap"><h1>集計できなかった</h1>
<div class="panel err"><p>bd からデータを取れなかった。</p>
<pre style="white-space:pre-wrap;font-size:12px">{html.escape(message)}</pre>
<p class="note">確認: <code>bd list --status=all --json --limit 0</code> が
/home/ats030 で通るか。</p></div></div></body></html>"""


# 棚卸しの主役は、一覧から対象を選んで判断すること。3行のうち1行を紫で
# 選択済みにし、16pxでも「チェックされたリスト」と読める太さに絞る。
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="棚卸しリスト">
<title>棚卸しリスト</title>
<rect x="8" y="8" width="84" height="84" rx="19" fill="#12141b" stroke="#343747" stroke-width="5"/>
<rect x="21" y="23" width="18" height="18" rx="5" fill="#7c3aed"/>
<path d="M25 32l4 4 7-9" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>
<rect x="47" y="27" width="32" height="9" rx="4.5" fill="#a78bfa"/>
<rect x="21" y="47" width="18" height="18" rx="5" fill="#242633"/>
<rect x="47" y="51" width="27" height="9" rx="4.5" fill="#71717a"/>
<rect x="21" y="71" width="18" height="9" rx="4.5" fill="#242633"/>
<rect x="47" y="71" width="20" height="9" rx="4.5" fill="#343747"/>
</svg>"""


@app.get("/favicon.svg")
def favicon() -> Response:
    return Response(FAVICON_SVG, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    try:
        raw = load_raw_issues()
    except Exception as exc:  # noqa: BLE001 - 画面に出して運用者に見せる
        return HTMLResponse(render_error(str(exc)), status_code=200)
    issues = parse_issues(raw)
    today = datetime.now(JST).date()
    return HTMLResponse(render_page(issues, today))


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}

