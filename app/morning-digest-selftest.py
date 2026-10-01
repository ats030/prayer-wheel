#!/usr/bin/env python3
"""morning-digest.py の集計が「偏ったキャッシュで急増を誤検出しない」ことを固定する。

    uv run --project ~ python app/morning-digest-selftest.py

なぜ必要か: feed_cache はフィードごとに最新 N 件しか持たない。1日に数十件出す
フィードは前7日が空になり、そのフィードの語がすべて急増に見えた (初回の試行で
「comment」「作者」が上位を占めた)。比較対象をキャッシュが比較期間を覆うフィードに
絞り、2フィード以上に出た語だけを残す。この2つが外れたら気付けるようにする。
"""

import importlib.util
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "morning-digest.py"
spec = importlib.util.spec_from_file_location("digest", SCRIPT)
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)

NOW = datetime(2026, 10, 1, 3, 0, tzinfo=md.JST)
OLD = NOW - timedelta(days=30)  # 比較期間を覆うキャッシュ

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}: {got!r} (期待 {want!r})")
        failures.append(name)


def item(title, feed, hours_ago, oldest=OLD, n=0):
    return {"title": title, "link": f"https://example.com/{feed}/{hours_ago}/{n}",
            "published": NOW - timedelta(hours=hours_ago), "feed": feed,
            "feed_oldest": oldest}


print("日報の節")
with tempfile.TemporaryDirectory() as d:
    md.REFLECTION_DIR = Path(d)
    Path(d, "2026-09-30.md").write_text(
        "## 今日\n- 対象外\n### 未完了・次にやること\n- 一つ目\n  - 二つ目\n本文\n### 次節\n- 対象外\n",
        encoding="utf-8")
    check("箇条だけを節の終わりまで拾う", md.reflection_section("2026-09-30")[1], ["一つ目", "二つ目"])
    check("日報が無ければ None", md.reflection_section("2026-09-29")[1], None)
    Path(d, "2026-09-28.md").write_text("## 今日\n- 何か\n", encoding="utf-8")
    check("節が無ければ空", md.reflection_section("2026-09-28")[1], [])

print("RSS の急増")
spiking = [item("Rustリリース", "A", 1, n=i) for i in range(2)] + [item("Rustリリース", "B", 2)]
r = md.rss_summary(spiking, NOW)
check("2フィードで3件、前7日0件なら急増",
      sorted(s["term"] for s in r["spikes"]), ["rust", "リリース"])

one_feed = [item("Rust 1.90", "A", h) for h in (1, 2, 3)]
check("1フィードだけの語は急増にしない", md.rss_summary(one_feed, NOW)["spikes"], [])

young = NOW - timedelta(days=1)  # キャッシュが前7日を覆わない
uncovered = [item("Rust 1.90", f, h, oldest=young) for f, h in (("A", 1), ("B", 2), ("C", 3))]
r = md.rss_summary(uncovered, NOW)
check("比較期間を覆わないフィードは比べない", r["spikes"], [])
check("覆わないフィードも全体件数には数える", r["recent_count"], 3)
check("比べたフィード数は0", r["comparable_feeds"], 0)

steady = [item("Rust 1.90", "A", 25 + 24 * d, n=d) for d in range(7)] * 2
steady = [dict(it, link=f"{it['link']}/{k}") for k, it in enumerate(steady)]
recent = [item("Rust 1.90", f, h) for f, h in (("A", 1), ("B", 2), ("A", 3))]
check("平常が日2件なら3件は急増でない",
      md.rss_summary(steady + recent, NOW)["spikes"], [])

print("分割")
long_line = "x" * 1500
parts = md.chunks("\n".join([long_line, long_line, "末尾"]))
check("上限を超えたら行単位で分ける", [len(p) for p in parts], [1500, 1500 + 1 + 2])
check("どの断片も上限以内", all(len(p) <= md.DISCORD_LIMIT for p in md.chunks("y" * 5000)), True)

print("送るものが無い")
with tempfile.TemporaryDirectory() as d:
    md.REFLECTION_DIR = Path(d, "none")
    md.FEED_CACHE_DIR = Path(d)
    Path(d, "a.json").write_text('{"meta": {"title": "A"}, "items": []}', encoding="utf-8")
    sys.argv = ["morning-digest.py", "--dry-run"]
    check("日報も新着も無ければ 3", md.main(), 3)
    Path(d, "a.json").unlink()
    check("キャッシュが無ければ 1", md.main(), 1)

if failures:
    print(f"\n{len(failures)} 件失敗")
    sys.exit(1)
print("\nすべて成功")
