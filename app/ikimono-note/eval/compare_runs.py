"""同じ写真で回した2つの結果を突き合わせる。

    uv run python eval/compare_runs.py edge-1600 edge-2048

独立した2つの割合として比べると、100枚では誤差が大きすぎてほぼ何も言えない。
同じ写真の対にして、答えが変わった枚数だけを見る (McNemar)。
"""
import json
from math import comb
from pathlib import Path

RESULTS = Path("/home/ats030/app/ikimono-note/eval/results")


def rows(label):
    data = json.loads((RESULTS / f"{label}.json").read_text(encoding="utf-8"))
    return {r["photo_id"]: r for r in data["rows"]}, data["summary"]


def exact_two_sided(b, c):
    """McNemar の正確検定。b, c は答えが入れ替わった枚数。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


import sys
left, right = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("edge-1600", "edge-2048")
a_rows, a_sum = rows(left)
b_rows, b_sum = rows(right)
shared = sorted(set(a_rows) & set(b_rows))
print(f"突き合わせた枚数: {len(shared)}\n")

print(f"{'指標':16} {left:>10} {right:>10}   {'→右で正解':>9} {'→左で正解':>9} {'p値':>7}")
for key, name in [("top1", "Top-1"), ("top3", "Top-3"), ("genus", "属まで一致"),
                  ("family_or_above", "科以上"), ("rejected", "候補ゼロ")]:
    def hit(row):
        return str(row.get(key)).lower() == "true"
    a_hits = sum(hit(a_rows[p]) for p in shared)
    b_hits = sum(hit(b_rows[p]) for p in shared)
    gained = sum(1 for p in shared if not hit(a_rows[p]) and hit(b_rows[p]))
    lost = sum(1 for p in shared if hit(a_rows[p]) and not hit(b_rows[p]))
    p = exact_two_sided(gained, lost)
    print(f"{name:16} {a_hits:7}枚 {b_hits:7}枚   {gained:9}枚 {lost:9}枚 {p:7.3f}")

print(f"\n1枚あたりの中央値: {left} {a_sum['median_seconds']}秒 / {right} {b_sum['median_seconds']}秒")
changed = [p for p in shared if a_rows[p]["predicted"] != b_rows[p]["predicted"]]
print(f"第一候補そのものが変わった枚数: {len(changed)} / {len(shared)}")
for p in changed[:6]:
    print(f"  {a_rows[p]['truth_ja'] or a_rows[p]['truth']}: "
          f"{a_rows[p]['predicted_ja']} → {b_rows[p]['predicted_ja']}")
