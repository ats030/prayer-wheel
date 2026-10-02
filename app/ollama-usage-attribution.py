#!/usr/bin/env python3
"""proxy 使用量ログの python-httpx 呼び出しを、呼び出し元アプリに帰属させる。

なぜ要るか: ollama-openwebui-proxy は User-Agent の先頭トークンしか記録しない
(client_label)。自作アプリはどれも httpx なので、最大の呼び出し元 gemma4:12b が
まとめて "python-httpx" に潰れ、どのアプリがローカルLLMを食っているか分からない
(ats030-373w)。プロキシ側に識別子を足すのが本筋だが、それでは過去ログを遡れない。
journal は 07-22 以降残っているので、時刻の突き合わせで遡って帰属できる。

4段構え:
  1. 直接照合: アプリ自身が journal に残す httpx の POST 行と時刻で1対1に対応づける。
  2. 稼働区間照合: oneshot バッチの Starting..(Finished|Failed to start) 区間に入るものを帰属。
  3. 採点ジョブ継続: rss-reader の採点は常駐デーモン側の非同期ジョブで、
     rss-reader-refresh.sh は投げてポーリングするだけ。MAX_WAIT=1800 で待機を
     打ち切ってもジョブは走り続けるので、打ち切りで終わった回に限り次回起動までを継続とみなす。
  4. 残り: 対話的 (常駐 Web アプリや CLI からの手動実行) として扱う。

時刻の扱いに注意: proxy の ts は応答が終わってから記録されるので完了時刻であり、
上流が詰まった回は elapsed_ms が10分に達する。呼び出し元が動いていたのは
「開始時刻 = ts - elapsed_ms」なので、区間判定にはこちらを使う。完了時刻や
[開始,完了] の重なりで見ると、10分かかった1件が途中に挟まった2秒の oneshot まで拾う。
"""
import argparse
import bisect
import collections
import datetime
import json
import pathlib
import re
import subprocess
import sys

USAGE_DIR = pathlib.Path.home() / "data/ollama-proxy"
MATCH_SEC = 3.0          # 直接照合の許容ずれ。proxy も呼び出し元も完了時に記録する
MAX_RUN_SEC = 7200       # これを超える稼働区間は終了行の欠落とみなす (oneshot の実測は十数分)
TAIL_MAX_SEC = 3600      # 採点ジョブ継続の上限

# LLM を叩きうる oneshot / タイマー起動のバッチ。常駐デーモンを入れると全件が
# 全ユニットに一致して識別力を失うので、明示列挙にしている。
ONESHOT = {"rss-reader-refresh", "daily-reflection-auto", "sales-viewer-cults-watch",
           "license-watch", "sales-viewer-fetch", "sales-viewer-backfill",
           "backlog-viewer-notify", "smoke-test", "backup-data",
           "launchpadlib-cache-clean", "ollama-keepalive"}
# 2分ごとに回るので、どの時刻にもほぼ重なる。区間照合から外す。
NO_SIGNAL = {"ollama-keepalive"}

UNIT_APP = {"gathering-information-scheduler": "gathering-information",
            "writing": "writing",
            "rss-reader-refresh": "rss-reader",
            "daily-reflection-auto": "daily-reflection"}

LLM_PATHS = ("/api/generate", "/api/chat", "/v1/chat/completions", "/api/embeddings", "/api/embed")

POST_RE = re.compile(
    r"^(\S+) \S+ ([a-z0-9_-]+)\[\d+\]:.*HTTP Request: POST http[^ ]*?"
    r"(" + "|".join(LLM_PATHS) + r")[\"' ]")
LIFE_RE = re.compile(
    r"^(\S+) \S+ systemd\[\d+\]: "
    r"(Starting|Started|Finished|Stopped|Failed to start|Deactivated successfully for) "
    r"([\w.@-]+)\.service")
GIVEUP_RE = re.compile(r"^(\S+) \S+ rss-reader-refresh\[\d+\]: LLM採点: \d+秒たっても終わらないので")


def parse_ts(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s)


def read_journal(since: str, until: str) -> list[str]:
    out = subprocess.run(["journalctl", "--user", "--since", since, "--until", until,
                          "-o", "short-iso", "--no-pager"],
                         capture_output=True, text=True)
    return out.stdout.splitlines()


def direct_index(lines):
    """(unit, path) -> ソート済みの POST 時刻。"""
    d = collections.defaultdict(list)
    for ln in lines:
        m = POST_RE.match(ln)
        if m:
            d[(m.group(2), m.group(3))].append(parse_ts(m.group(1)))
    for v in d.values():
        v.sort()
    return d


def run_intervals(lines):
    """oneshot ユニットの稼働区間。失敗回も Failed to start で閉じる。"""
    open_, iv = {}, collections.defaultdict(list)
    for ln in lines:
        m = LIFE_RE.match(ln)
        if not m or m.group(3) not in ONESHOT:
            continue
        ts, verb, unit = m.groups()
        t = parse_ts(ts)
        if verb in ("Starting", "Started"):
            prev = open_.pop(unit, None)
            if prev is not None:      # 終了行が落ちていた前回を、次の起動で閉じる
                iv[unit].append((prev, t))
            open_[unit] = t
        else:
            s = open_.pop(unit, None)
            if s is not None:
                iv[unit].append((s, t))
    now = datetime.datetime.now(datetime.timezone.utc)
    for unit, s in open_.items():
        iv[unit].append((s, now))
    for unit in list(iv):
        iv[unit] = [(a, b) for a, b in iv[unit] if (b - a).total_seconds() <= MAX_RUN_SEC]
    return iv


def score_tails(lines, iv):
    """打ち切りで終わった採点ジョブが、デーモン内で走り続けている区間。"""
    gave = sorted(parse_ts(m.group(1)) for m in (GIVEUP_RE.match(ln) for ln in lines) if m)
    starts = sorted(a for a, _ in iv.get("rss-reader-refresh", []))
    cap = datetime.timedelta(seconds=TAIL_MAX_SEC)
    tails = []
    for g in gave:
        nxt = next((s for s in starts if s > g), g + cap)
        tails.append((g, min(nxt, g + cap)))
    return tails


class DirectMatcher:
    """journal の POST 行と proxy の行を1対1に対応づける。使い切った行は再利用しない。"""

    def __init__(self, index):
        self.index = index
        self.used = {k: [False] * len(v) for k, v in index.items()}

    def take(self, unit, path, t):
        key = (unit, path)
        v = self.index.get(key)
        if not v:
            return False
        d = datetime.timedelta(seconds=MATCH_SEC)
        lo, hi = bisect.bisect_left(v, t - d), bisect.bisect_right(v, t + d)
        best, gap_best = None, None
        for j in range(lo, hi):
            if self.used[key][j]:
                continue
            gap = abs((v[j] - t).total_seconds())
            if gap_best is None or gap < gap_best:
                best, gap_best = j, gap
        if best is None:
            return False
        self.used[key][best] = True
        return True


def load_usage(since: str, until: str):
    lo, hi = parse_ts(since + "T00:00:00+00:00"), parse_ts(until + "T00:00:00+00:00")
    rows = []
    for p in sorted(USAGE_DIR.glob("usage-*.jsonl")):
        with p.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                t = parse_ts(r["ts"])
                if lo <= t < hi:
                    r["_t"] = t
                    rows.append(r)
    rows.sort(key=lambda r: r["_t"])
    return rows


def classify(rows, direct, iv, tails):
    matcher = DirectMatcher(direct)
    for r in rows:
        src = None
        for unit, path in direct:
            if path == r["path"] and matcher.take(unit, path, r["_t"]):
                src = (UNIT_APP.get(unit, unit), "直接ログ")
                break
        if src is None:
            # 呼び出し元が動いていたのは要求の開始時刻。冒頭の docstring 参照。
            t0 = r["_t"] - datetime.timedelta(milliseconds=r.get("elapsed_ms", 0) or 0)
            hit = sorted(u for u, v in iv.items()
                         if u not in NO_SIGNAL and any(a <= t0 <= b for a, b in v))
            if len(hit) == 1:
                src = (UNIT_APP.get(hit[0], hit[0]), "稼働区間")
            elif len(hit) > 1:
                src = ("+".join(UNIT_APP.get(u, u) for u in hit), "稼働区間(複数)")
            # 採点ジョブ継続は区間が長いので、scorer の署名 (gemma4:12b × /api/generate)
            # に限って当てる。無条件だと同時間帯の他アプリの分まで取り込む。
            elif r["path"] == "/api/generate" and r.get("model") == "gemma4:12b" \
                    and any(a <= t0 <= b for a, b in tails):
                src = ("rss-reader", "採点ジョブ継続")
        r["_src"] = src
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default="2026-08-17")
    ap.add_argument("--until", default=None, help="排他的な終端 (既定: 明日)")
    ap.add_argument("--client", default="python-httpx", help="対象の client ラベル ('' で全件)")
    ap.add_argument("--out", type=pathlib.Path,
                    default=USAGE_DIR / "attribution.json")
    args = ap.parse_args()
    until = args.until or (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    lines = read_journal(args.since, until)
    direct = direct_index(lines)
    iv = run_intervals(lines)
    tails = score_tails(lines, iv)

    rows = load_usage(args.since, until)
    if not rows:
        print(f"{args.since}〜{until} に proxy ログの行が無い", file=sys.stderr)
        return 3
    target = [r for r in rows if not args.client or r.get("client") == args.client]
    classify(target, direct, iv, tails)

    total = len(target)
    counts = collections.Counter(
        (r["_src"][0], r["_src"][1]) if r["_src"] else ("未帰属", "-") for r in target)
    by_app = collections.Counter()
    tokens = collections.Counter()
    # トークン0件は空撃ちとは限らない。上流の 502/503 で落ちた要求もトークン0で
    # 記録されるので、呼び出し元ごとの失敗 (= 再試行の種) を状態別に残す。
    status = collections.defaultdict(collections.Counter)
    for r in target:
        app = r["_src"][0] if r["_src"] else "未帰属"
        by_app[app] += 1
        tokens[app] += (r.get("input", 0) or 0) + (r.get("output", 0) or 0)
        status[app][str(r.get("status"))] += 1
    unattr = by_app["未帰属"]

    span = f"{target[0]['ts']} 〜 {target[-1]['ts']}"
    print(f"対象 {total} 件 (client={args.client or 'ALL'}) / 実測範囲 {span}")
    print(f"要求範囲 {args.since} 〜 {until}\n")
    print(f"{'件数':>7} {'割合':>7}  呼び出し元 / 根拠")
    for (app, how), n in counts.most_common():
        print(f"{n:7d} {n / total * 100:6.1f}%  {app} / {how}")
    print(f"\n未帰属 {unattr} / {total} = {unattr / total * 100:.1f}%")

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "requested_window": {"since": args.since, "until": until},
        "observed_window": {"first": target[0]["ts"], "last": target[-1]["ts"]},
        "client": args.client,
        "total": total,
        "unattributed": unattr,
        "unattributed_ratio": round(unattr / total, 4),
        "by_app": dict(by_app.most_common()),
        "tokens_by_app": dict(tokens.most_common()),
        "by_app_and_method": {f"{a}|{h}": n for (a, h), n in counts.most_common()},
        "status_by_app": {a: dict(status[a].most_common()) for a, _ in by_app.most_common()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{args.out} に書き出した")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
