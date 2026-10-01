#!/usr/bin/env python3
"""前日の日報の「次にやること」と、RSS で急に増えた語を毎朝 Discord へ送る。

なぜ必要か: 日報も RSS も画面を開かないと読まれない。2026-09 の visit-log では
rss-reader を人が開いたのは1日だけだった。情報を集める側は動いているのに、
行動に繋がる経路が無い。届ける側だけを足して、行動に繋がるかを2週間測る
(ats030-2mn2i、grill-me 判定 experiment)。

LLM は呼ばない。evo-x2 の Ollama は daily-reflection-auto と VRAM を取り合って
いて (2026-09-30 に gemma4:12b がロードできず失敗)、ここで呼ぶと土台の日報を
巻き込む。集計は機械的なものに留め、解釈は読む人がする。

出力は派生物であって正本ではない。各項目に日報のパスか記事 URL を付け、
日報や bd へは書き戻さない。

終了コード (~/CLAUDE.md の規約):
  0 = 送信した
  3 = 日報も24時間以内の RSS も無く、送るものが無い (設計どおり)
  1 = 障害 (キャッシュが読めない、Webhook 未設定、送信失敗)
"""

import argparse
import json
import re
import sys
import urllib.request
import weather_notify
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
HOME = Path.home()
REFLECTION_DIR = HOME / "data" / "daily-reflection" / "output"
FEED_CACHE_DIR = HOME / "data" / "feed_cache"
SENT_DIR = HOME / "data" / "morning-digest"
ENV_PATH = HOME / ".env"
DISCORD_LIMIT = 1900  # Discord のメッセージ上限 2000 に対する余裕

NEXT_HEADING = "### 未完了・次にやること"
BASELINE_DAYS = 7
MIN_RECENT = 3  # 1件や2件の重なりは偶然と区別できない
MIN_FEEDS = 2  # 1フィードだけの語は、そのフィード固有の定型 (「comment」「作者に聞く」) に過ぎない
TOP_TERMS = 5
TOP_FEEDS = 5

# 片仮名3字以上、英数語3字以上、漢字2〜6字。形態素解析器を入れずに済む粗い切り出しで、
# 「急に増えたか」を見るには足りる。
TERM_RE = re.compile(r"[ァ-ヴー]{3,}|[A-Za-z][A-Za-z0-9+#.\-]{2,}|[一-龥々]{2,6}")
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "you", "your", "are",
    "how", "what", "new", "now", "its", "all", "not", "can", "will", "has",
    "発表", "公開", "開始", "発売", "登場", "対応", "提供", "予定", "記事", "紹介",
    "解説", "最新", "今回", "可能", "注目", "情報", "日本", "限定", "一覧", "年間",
}


def reflection_section(day: str) -> tuple[Path, list[str] | None]:
    """日報の「次にやること」節の箇条を返す。日報が無ければ None。"""
    path = REFLECTION_DIR / f"{day}.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return path, None
    items, inside = [], False
    for line in lines:
        if line.rstrip() == NEXT_HEADING:
            inside = True
            continue
        if inside and line.startswith("#"):
            break
        if inside and line.lstrip().startswith("- "):
            items.append(line.strip()[2:])
    return path, items


def load_items() -> list[dict]:
    """全フィードのキャッシュ済み記事。同じ記事が複数フィードに出るので link で重複を除く。"""
    files = sorted(FEED_CACHE_DIR.glob("*.json"))
    if not files:
        raise RuntimeError(f"{FEED_CACHE_DIR} にキャッシュが無い")
    seen, items = set(), []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        feed_title = data.get("meta", {}).get("title") or data.get("url", "")
        dated = [datetime.fromisoformat(it["published"])
                 for it in data.get("items", []) if it.get("published")]
        oldest = min(dated) if dated else None
        for it in data.get("items", []):
            link = it.get("link") or ""
            if not it.get("published") or link in seen:
                continue
            seen.add(link)
            items.append({
                "title": (it.get("title") or "").strip(),
                "link": link,
                "published": datetime.fromisoformat(it["published"]),
                "feed": feed_title,
                "feed_oldest": oldest,
            })
    return items


def terms(title: str) -> set[str]:
    out = set()
    for t in TERM_RE.findall(title):
        key = t.lower() if t.isascii() else t
        if key not in STOPWORDS:
            out.add(key)
    return out


def rss_summary(items: list[dict], now: datetime) -> dict:
    """直近24時間を、その前の7日間の日平均と比べる。

    比べるのは、キャッシュが比較期間の始まりより前まで残っているフィードだけ。
    キャッシュはフィードごとに最新 N 件しか持たないので、1日に数十件出すフィードは
    前7日が空になり、そのフィードの語がすべて「急増」に見えてしまう。
    """
    recent_from = now - timedelta(days=1)
    base_from = recent_from - timedelta(days=BASELINE_DAYS)
    recent = [i for i in items if recent_from <= i["published"] <= now]
    covered = [i for i in items if i["feed_oldest"] and i["feed_oldest"] <= base_from]
    comparable = [i for i in covered if recent_from <= i["published"] <= now]
    base = [i for i in covered if base_from <= i["published"] < recent_from]

    recent_terms, base_terms, example, term_feeds = Counter(), Counter(), {}, {}
    for it in comparable:
        for t in terms(it["title"]):
            recent_terms[t] += 1
            example.setdefault(t, it)
            term_feeds.setdefault(t, set()).add(it["feed"])
    for it in base:
        base_terms.update(terms(it["title"]))

    spikes = []
    for t, n in recent_terms.items():
        avg = base_terms[t] / BASELINE_DAYS
        if n >= MIN_RECENT and n > 2 * avg and len(term_feeds[t]) >= MIN_FEEDS:
            spikes.append({"term": t, "recent": n, "baseline_avg": round(avg, 1),
                           "title": example[t]["title"], "link": example[t]["link"]})
    spikes.sort(key=lambda s: (s["recent"] - s["baseline_avg"], s["recent"]), reverse=True)

    feeds = Counter(i["feed"] for i in recent).most_common(TOP_FEEDS)
    return {"recent_count": len(recent), "comparable_count": len(comparable),
            "baseline_count": len(base),
            "comparable_feeds": len({i["feed"] for i in covered}),
            "spikes": spikes[:TOP_TERMS], "feeds": feeds}


def compose(day: str, path: Path, next_items: list[str] | None, rss: dict) -> str:
    lines = [f"🌅 **朝のダイジェスト** (日報 {day} / RSS 直近24時間)",
             "-# 機械集計の派生物です。判断は出典を見てから。", ""]

    lines.append("**次にやること (日報より)**")
    if next_items is None:
        lines.append(f"- 日報なし。生成に失敗した可能性があります (`{path}`)")
    elif not next_items:
        lines.append("- 日報に該当の記載なし")
    else:
        lines += [f"- {x}" for x in next_items]
        lines.append(f"-# 出典: `{path}`")
    lines.append("")

    lines.append(f"**RSS で急に増えた語** (比較できた {rss['comparable_feeds']}フィード: "
                 f"直近24時間 {rss['comparable_count']}件 / 前{BASELINE_DAYS}日 {rss['baseline_count']}件)")
    if not rss["spikes"]:
        lines.append("- 目立った増加なし")
    for s in rss["spikes"]:
        lines.append(f"- **{s['term']}** {s['recent']}件 (平常 {s['baseline_avg']}件/日): "
                     f"{s['title']} <{s['link']}>")
    if rss["feeds"]:
        lines.append(f"-# 全フィードの直近24時間 {rss['recent_count']}件。新着の多いフィード: "
                     + " / ".join(f"{name} {n}" for name, n in rss["feeds"]))
    lines.append("")
    lines.append("-# RSS 項目から着手したら、bd issue の説明に記事 URL を入れてください (効果測定に使います)")
    return "\n".join(lines)


def chunks(text: str) -> list[str]:
    """Discord の上限を超えたら行単位で分ける。切り詰めると URL が壊れる。"""
    out, cur = [], ""
    for line in text.splitlines():
        line = line[:DISCORD_LIMIT]
        if cur and len(cur) + len(line) + 1 > DISCORD_LIMIT:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def webhook_url() -> str:
    """秘密は ~/.env にしかない。必要なキーだけ取り出す (notify-failure.sh と同じ)。"""
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_WEBHOOK_URL="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def post_to_discord(url: str, text: str) -> None:
    # 日報の項目も記事タイトルも外部の文字列。@everyone が混じっても誰も呼ばない
    payload = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    # User-Agent は必須。Discord は Python-urllib の既定 UA を 403 で弾く (license-watch.py 参照)
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "User-Agent": "morning-digest (https://github.com/ats030, 1.0)",
    })
    with urllib.request.urlopen(req, timeout=20):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="送信も保存もせず本文を表示する")
    args = ap.parse_args()

    now = datetime.now(JST)
    day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    path, next_items = reflection_section(day)
    try:
        rss = rss_summary(load_items(), now)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"RSS キャッシュを読めない: {e}", file=sys.stderr)
        return 1

    weather_text, weather_state = "", None
    try:
        weather_text, weather_state = weather_notify.morning(now)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as e:
        print(f"天気を取得できない: {type(e).__name__}", file=sys.stderr)

    if next_items is None and rss["recent_count"] == 0 and not weather_text:
        if weather_state is not None and not args.dry_run:
            weather_notify.save_state("morning.json", weather_state)
        print("日報も24時間以内の RSS も無いため送らない")
        return 3

    text = compose(day, path, next_items, rss)
    if weather_text:
        text += "\n\n" + weather_text
    print(text)
    if args.dry_run:
        return 0

    url = webhook_url()
    if not url:
        print("DISCORD_WEBHOOK_URL が未設定", file=sys.stderr)
        return 1
    try:
        for part in chunks(text):
            post_to_discord(url, part)
    except OSError as e:
        print(f"Discord への送信に失敗した: {e}", file=sys.stderr)
        return 1

    if weather_state is not None:
        weather_notify.save_state("morning.json", weather_state)

    # 2週間後の効果測定で、送った項目と bd の着手を突き合わせるために残す
    SENT_DIR.mkdir(parents=True, exist_ok=True)
    record = {"sent_at": now.isoformat(), "reflection_day": day,
              "reflection_path": str(path), "next_items": next_items, "rss": rss}
    (SENT_DIR / f"{now:%Y-%m-%d}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
