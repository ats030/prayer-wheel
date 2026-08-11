"""複数の測定結果を並べて比較する。

  uv run python eval/compare.py plants-local-only plants-local-plantnet

同じ写真だけを対象に揃えて出す。片方が途中で止まった結果をそのまま並べると、
難易度の違う写真を比べて差があるように見えてしまう。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def load(label: str) -> dict:
    path = RESULTS_DIR / f"{label}.json"
    if not path.exists():
        raise SystemExit(f"結果がありません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def stats(rows: list[dict]) -> dict[str, object]:
    scored = [r for r in rows if "error" not in r]
    answered = [r for r in scored if not r["rejected"]]
    pct = lambda key: round(100 * sum(1 for r in scored if r.get(key)) / len(scored)) if scored else 0
    return {
        "n": len(scored),
        "top1": pct("top1"),
        "top3": pct("top3"),
        "genus": pct("genus"),
        "family": pct("family_or_above"),
        "rejected": pct("rejected"),
        "answered": len(answered),
        "top1_answered": round(100 * sum(1 for r in answered if r["top1"]) / len(answered)) if answered else 0,
        "confidence": round(sum(r["confidence_top1"] or 0 for r in answered) / len(answered)) if answered else 0,
    }


def main(labels: list[str]) -> int:
    if len(labels) < 2:
        raise SystemExit(__doc__)
    runs = {label: load(label) for label in labels}

    # 全ラベルで成功した写真だけに揃える
    common = None
    for data in runs.values():
        ok = {r["photo_id"] for r in data["rows"] if "error" not in r}
        common = ok if common is None else (common & ok)
    common = common or set()
    print(f"共通して成功した写真: {len(common)}枚\n")

    header = f"{'':28} {'Top-1':>6} {'Top-3':>6} {'属':>5} {'科以上':>6} {'棄却':>5} {'確信度':>6}"
    print(header)
    print("-" * len(header))
    for label, data in runs.items():
        rows = [r for r in data["rows"] if r.get("photo_id") in common]
        s = stats(rows)
        print(f"{label:28} {s['top1']:5}% {s['top3']:5}% {s['genus']:4}% {s['family']:5}% {s['rejected']:4}% {s['confidence']:5}%")

    # Pl@ntNet が実際に走ったか（呼ばれていなければ差が出なくて当然）
    for label, data in runs.items():
        used = [r for r in data["rows"] if r.get("plantnet_used")]
        statuses = [r.get("plantnet_status") for r in data["rows"] if r.get("plantnet_status")]
        if used or statuses:
            from collections import Counter
            print(f"\n{label}: 専門識別が走った {len(used)}件 / 状態 {dict(Counter(s for s in statuses if s))}")

    # 1枚ごとにどちらが当てたか
    if len(labels) == 2:
        a, b = labels
        rows_a = {r["photo_id"]: r for r in runs[a]["rows"] if r.get("photo_id") in common}
        rows_b = {r["photo_id"]: r for r in runs[b]["rows"] if r.get("photo_id") in common}
        flips = [(rows_a[i], rows_b[i]) for i in common if rows_a[i]["top1"] != rows_b[i]["top1"]]
        if flips:
            print(f"\n■ Top-1 が入れ替わった {len(flips)}枚")
            for ra, rb in flips:
                winner = b if rb["top1"] else a
                print(f"  {ra['truth']:32} {winner} が正解  ({ra['predicted'][:1]} → {rb['predicted'][:1]})")
        else:
            print("\n■ Top-1 の当たり外れは1枚も変わらなかった")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
