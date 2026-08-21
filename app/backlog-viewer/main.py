"""backlog-viewer: 残タスクが収束しない理由を可視化する (port 8524)。

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
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

JST = ZoneInfo("Asia/Tokyo")

# 積み上げグラフの層キー。通常の層は「作成週の月曜日」(date)、
# deferred だけは作成週から抜いてこの sentinel の層へ移す。
DEFERRED_LAYER = "deferred"

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

    @property
    def deferred(self) -> bool:
        return self.status == "deferred"

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
    for issue in issues:
        created[issue.cohort] = created.get(issue.cohort, 0) + 1
        if issue.open_on(today):
            remaining[issue.cohort] = remaining.get(issue.cohort, 0) + 1
        if issue.closed is not None and issue.closed == issue.created:
            same_day[issue.cohort] = same_day.get(issue.cohort, 0) + 1
        if issue.priority >= 3:
            p3[issue.cohort] = p3.get(issue.cohort, 0) + 1
    return [
        CohortRow(w, created[w], remaining.get(w, 0), same_day.get(w, 0), p3.get(w, 0))
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
        )
        for i in issues
        if i.open_on(today)
    ]
    return sorted(rows, key=lambda r: (-r.age_days, r.id))


@dataclass(frozen=True)
class Metrics:
    remaining: int
    deferred: int
    over_30_days: int
    claim_rate: float
    same_day_close_rate: float
    median_age: int
    median_lead_time: int


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
    )


# ------------------------------------------------------------------ 描画

# 依存を足さないために SVG は自前で組み立てる。ライブラリを1つ入れると
# ライセンス確認と更新追従が新しい運用タスクになる。

SVG_W, SVG_H = 960, 300
PLOT = (46, 12, 950, 262)  # x0, y0, x1, y1


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


def _nice_ceiling(value: int) -> int:
    if value <= 0:
        return 1
    step = 10 if value <= 100 else 50
    return ((value + step - 1) // step) * step


def render_stacked_svg(series: Series) -> str:
    x0, y0, x1, y1 = PLOT
    ymax = _nice_ceiling(series.peak)
    days = series.days
    n = len(days)

    def px(i: int) -> float:
        return x0 if n <= 1 else x0 + i * (x1 - x0) / (n - 1)

    def py(v: float) -> float:
        return y1 - (v / ymax) * (y1 - y0)

    parts = [
        f'<svg viewBox="0 0 {SVG_W} {SVG_H}" width="100%" role="img" '
        f'aria-label="残件数の推移 (作成週コホート積み上げ)">'
    ]

    # 水平グリッドと y 軸目盛
    for t in range(0, 5):
        v = ymax * t / 4
        y = py(v)
        parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="#242633" stroke-width="1"/>')
        parts.append(
            f'<text x="{x0 - 8}" y="{y + 4:.1f}" text-anchor="end" fill="#71717a" font-size="11">{v:.0f}</text>'
        )

    cohort_layers = [l for l in series.layers if l != DEFERRED_LAYER]
    base = [0.0] * n
    for layer in series.layers:
        idx = cohort_layers.index(layer) if layer != DEFERRED_LAYER else 0
        color = _layer_color(layer, idx, len(cohort_layers))
        top = [base[i] + series.count_on(days[i], layer) for i in range(n)]
        upper = " ".join(f"{px(i):.1f},{py(top[i]):.1f}" for i in range(n))
        lower = " ".join(f"{px(i):.1f},{py(base[i]):.1f}" for i in range(n - 1, -1, -1))
        label = "外部待ち (deferred)" if layer == DEFERRED_LAYER else f"{layer:%-m/%-d} 週"
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


def render_legend(series: Series) -> str:
    cohort_layers = [l for l in series.layers if l != DEFERRED_LAYER]
    items = []
    for layer in series.layers:
        idx = cohort_layers.index(layer) if layer != DEFERRED_LAYER else 0
        color = _layer_color(layer, idx, len(cohort_layers))
        label = "外部待ち" if layer == DEFERRED_LAYER else f"{layer:%-m/%-d}〜"
        items.append(
            f'<span class="legend-item"><i style="background:{color}"></i>{html.escape(label)}</span>'
        )
    return "".join(items)


CSS = """
:root {
  --bg: #08090c; --surface: #0d0f14; --raised: #12141b; --hover: #171923;
  --border: #242633; --border-strong: #343747; --text: #f4f4f5;
  --muted: #a1a1aa; --subtle: #71717a; --accent: #7c3aed; --accent-soft: #a78bfa;
  --success: #34d399; --warning: #fbbf24; --danger: #fb7185;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: Inter, "SF Pro", "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 14px; line-height: 1.6;
}
.wrap { max-width: 1200px; margin: 0 auto; padding: 24px 24px 220px; }
h1 { font-size: 18px; font-weight: 600; margin: 0 0 4px; }
h2 { font-size: 14px; font-weight: 600; margin: 32px 0 12px; color: var(--muted); }
.sub { color: var(--subtle); font-size: 12px; margin: 0 0 24px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.tile { background: var(--raised); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.tile .v { font-size: 22px; font-weight: 600; }
.tile .k { color: var(--subtle); font-size: 12px; }
.tile .n { color: var(--subtle); font-size: 11px; margin-top: 2px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
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
.id { color: var(--accent-soft); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.chip { display: inline-block; padding: 0 6px; border-radius: 4px; font-size: 11px;
        background: rgba(124,58,237,.16); color: var(--accent-soft); }
.chip.gray { background: rgba(161,161,170,.14); color: var(--muted); }
.hot { color: var(--danger); }
.warn { color: var(--warning); }
.scroll { overflow-x: auto; }
/* 狭い画面で SVG を潰すと軸ラベルが 4px 相当になって読めない。
   縮小させずに .scroll の中で横スクロールさせる。 */
.chart svg { min-width: 720px; }
.bar { display: inline-block; height: 8px; border-radius: 2px; background: var(--accent); vertical-align: middle; }
input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; cursor: pointer; }
.dock {
  position: fixed; left: 0; right: 0; bottom: 0; background: var(--surface);
  border-top: 1px solid var(--border-strong); padding: 12px 24px;
}
.dock-inner { max-width: 1200px; margin: 0 auto; }
.dock-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
button {
  background: var(--raised); color: var(--text); border: 1px solid var(--border-strong);
  border-radius: 6px; padding: 5px 12px; font-size: 13px; cursor: pointer; font-family: inherit;
}
button:hover { background: var(--hover); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.primary:hover { background: #6d28d9; }
button:disabled { opacity: .4; cursor: default; }
textarea {
  width: 100%; background: var(--raised); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; resize: vertical; min-height: 62px;
}
textarea:focus { outline: none; border-color: var(--accent); }
.count { color: var(--subtle); font-size: 12px; }
.err { border-color: var(--danger); color: var(--danger); }
@media (max-width: 640px) {
  .wrap { padding: 16px 12px 240px; }
  .hide-sm { display: none; }
}
"""


JS = """
const TODAY = "__TODAY__";
function picked() {
  return Array.from(document.querySelectorAll('.pick:checked')).map(e => e.value);
}
function build(kind, ids) {
  if (!ids.length) return '';
  if (kind === 'close') {
    return 'bd close ' + ids.join(' ') + ' -r "棚卸し ' + TODAY + ': 着手されないまま滞留したため打ち切り"';
  }
  return 'bd defer ' + ids.join(' ');
}
function refresh() {
  const ids = picked();
  document.getElementById('cmd-close').value = build('close', ids);
  document.getElementById('cmd-defer').value = build('defer', ids);
  document.getElementById('count').textContent = ids.length ? ids.length + ' 件を選択中' : '未選択';
  document.querySelectorAll('.copy').forEach(b => { b.disabled = ids.length === 0; });
}
async function copyFrom(id, button) {
  const el = document.getElementById(id);
  if (!el.value) return;
  let ok = false;
  // Tailnet の http:// は secure context ではないので navigator.clipboard が無い。
  // その場合は execCommand にフォールバックする。
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
  document.querySelectorAll('.pick').forEach(e => { e.checked = source.checked; });
  refresh();
}
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.pick').forEach(e => e.addEventListener('change', refresh));
  document.querySelectorAll('.copy').forEach(b => {
    b.dataset.label = b.textContent;
    b.addEventListener('click', () => copyFrom(b.dataset.target, b));
  });
  refresh();
});
"""


def _priority_chip(p: int) -> str:
    cls = "chip" if p <= 1 else "chip gray"
    return f'<span class="{cls}">P{p}</span>'


def _age_cell(days: int) -> str:
    cls = "hot" if days > 30 else ("warn" if days > 14 else "")
    return f'<span class="{cls}">{days}</span>'


def render_page(issues: list[Issue], today: date) -> str:
    series = daily_series(issues, today)
    m = metrics(issues, today)
    cohorts = cohort_table(issues, today)
    rows = backlog_rows(issues, today)

    tiles = [
        ("残件数", str(m.remaining), f"うち外部待ち {m.deferred}"),
        ("30日超", str(m.over_30_days), "棚卸しの第一候補"),
        ("滞留の中央値", f"{m.median_age}日", "残っている件"),
        ("claim率", f"{m.claim_rate}%", "started_at が付いた件"),
        ("同日クローズ率", f"{m.same_day_close_rate}%", "クローズ済み全体"),
        ("リードタイム中央値", f"{m.median_lead_time}日", "クローズ済み全体"),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="k">{html.escape(k)}</div>'
        f'<div class="v">{html.escape(v)}</div><div class="n">{html.escape(n)}</div></div>'
        for k, v, n in tiles
    )

    max_created = max((c.created for c in cohorts), default=1)
    cohort_html = "".join(
        f"<tr><td>{c.week:%Y-%m-%d}〜</td>"
        f'<td class="num">{c.created}</td>'
        f'<td class="num">{c.remaining}</td>'
        f'<td class="num">{c.residual_rate}%</td>'
        f'<td class="num">{c.same_day_rate}%</td>'
        f'<td class="num">{c.p3_share}%</td>'
        f'<td><span class="bar" style="width:{max(2, round(c.created / max_created * 120))}px;'
        f"opacity:{0.25 + min(c.residual_rate, 50) / 50 * 0.75:.2f}\"></span></td></tr>"
        for c in cohorts
    )

    row_html = "".join(
        f"<tr>"
        f'<td><input type="checkbox" class="pick" value="{html.escape(r.id)}"></td>'
        f'<td class="id">{html.escape(r.id)}</td>'
        f'<td class="num">{_age_cell(r.age_days)}</td>'
        f'<td class="num hide-sm">{r.idle_days}</td>'
        f"<td>{_priority_chip(r.priority)}</td>"
        f'<td class="hide-sm">{html.escape(r.issue_type)}</td>'
        f"<td>{html.escape(r.title)}"
        + ('<span class="chip gray">外部待ち</span>' if r.deferred else "")
        + "</td></tr>"
        for r in rows
    )

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>backlog-viewer</title>
<style>{CSS}</style></head><body>
<div class="wrap">
  <h1>残タスクはなぜ収束しないか</h1>
  <p class="sub">{today:%Y-%m-%d} 時点 (JST) · bd から直接読んでいる · この画面は書き込まない</p>

  <div class="tiles">{tile_html}</div>

  <h2>残件数の推移 (作成週コホート積み上げ)</h2>
  <div class="panel">
    <div class="scroll chart">{render_stacked_svg(series)}</div>
    <div class="legend">{render_legend(series)}</div>
    <p class="note">高さの合計が残件数。色は「いつ作られた件か」を表す。層が横に伸びたままなら、
    その週に作った分が片付いていない。外部待ち (deferred) は残件から除外していないが、
    defer した日は bd に記録が残らないため updated_at で近似している。</p>
  </div>

  <h2>作成週ごとの残存率</h2>
  <div class="panel scroll">
    <table><thead><tr><th>作成週</th><th class="num">作成</th><th class="num">残</th>
    <th class="num">残存率</th><th class="num">同日クローズ率</th><th class="num">P3の割合</th>
    <th></th></tr></thead>
    <tbody>{cohort_html}</tbody></table>
    <p class="note">残存率はこの2列とほぼ逆に動く。その日に閉じられなかった件と、
    P3 で作られた件が残る。残存率が跳ねた週を見つけたら、量ではなくこの2列を見ること。</p>
  </div>

  <h2>残っている全 {len(rows)} 件 (滞留日数の降順)</h2>
  <div class="panel scroll">
    <table><thead><tr>
      <th><input type="checkbox" onchange="toggleAll(this)"></th>
      <th>ID</th><th class="num">滞留</th><th class="num hide-sm">無更新</th>
      <th>P</th><th class="hide-sm">種別</th><th>タイトル</th>
    </tr></thead>
    <tbody>{row_html}</tbody></table>
  </div>
</div>

<div class="dock"><div class="dock-inner">
  <div class="dock-row">
    <strong>棚卸し</strong><span class="count" id="count">未選択</span>
    <button class="copy" data-target="cmd-close">close をコピー</button>
    <button class="copy primary" data-target="cmd-defer">defer をコピー</button>
  </div>
  <textarea id="cmd-close" readonly placeholder="打ち切る件をチェックすると bd close の1行が出る"></textarea>
  <textarea id="cmd-defer" readonly placeholder="外部待ちに退避する件をチェックすると bd defer の1行が出る"></textarea>
</div></div>
<script>{JS.replace("__TODAY__", today.isoformat())}</script>
</body></html>"""


def render_error(message: str) -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>backlog-viewer</title><style>{CSS}</style></head><body>
<div class="wrap"><h1>集計できなかった</h1>
<div class="panel err"><p>bd からデータを取れなかった。</p>
<pre style="white-space:pre-wrap;font-size:12px">{html.escape(message)}</pre>
<p class="note">確認: <code>bd list --status=all --json --limit 0</code> が
/home/ats030 で通るか。</p></div></div></body></html>"""


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


def weekly_summary(issues: list[Issue], today: date) -> dict:
    """週次通知用のサマリ。

    先週比はスナップショットを保存せずに出す。created_at/closed_at から
    過去の残件数をそのまま復元できるので、状態を持つ必要がない。
    """
    m = metrics(issues, today)
    week_ago = today - timedelta(days=7)
    before = sum(1 for i in issues if i.open_on(week_ago))
    rows = backlog_rows(issues, today)
    return {
        "remaining": m.remaining,
        "deferred": m.deferred,
        "over_30_days": m.over_30_days,
        "median_age": m.median_age,
        "delta_7d": m.remaining - before,
        "oldest": rows[:5],
    }
