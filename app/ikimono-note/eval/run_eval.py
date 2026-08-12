"""正解付き写真セットで識別精度を測る。

本番と同じ経路 (pipeline.identify_all) を通す。評価だけ別の手順を組むと、
測った数字がアプリの実際の挙動と一致しなくなる。

  uv run --with httpx --with pillow python eval/run_eval.py --label local-baseline
  uv run ... python eval/run_eval.py --use-plantnet --label local-plantnet

既定はOllama。外部APIは無料枠の日次上限を公開版と食い合うので、必要なときだけ
--provider gemini のように明示する。

結果は eval/results/<label>.json と、比較用の要約表を標準出力へ出す。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import config_store  # noqa: E402
import pipeline  # noqa: E402
import vision  # noqa: E402

MANIFEST = Path(__file__).parent / "dataset.json"
RESULTS_DIR = Path(__file__).parent / "results"


def genus_of(name: str) -> str:
    return (name or "").strip().split(" ")[0]


def ancestor_ids(scientific_name: str) -> list[int]:
    """学名から iNaturalist の上位分類IDを引く。vision 側のレート制御を使い回す。"""
    results = vision._lookup_taxon(scientific_name) or []
    for item in results:
        if str(item.get("name", "")).lower() == scientific_name.lower():
            return [int(x) for x in (item.get("ancestor_ids") or [])] + [int(item["id"])]
    return []


def truth_ranks(entry: dict) -> dict[str, object]:
    ancestry = [int(x) for x in str(entry["truth"].get("ancestry", "")).split("/") if x.isdigit()]
    return {
        "taxon_id": entry["truth"]["taxon_id"],
        "genus": genus_of(entry["truth"]["name"]),
        "lineage": set(ancestry + [entry["truth"]["taxon_id"]]),
    }


def score_one(entry: dict, result: dict, family_check: bool) -> dict[str, object]:
    truth = truth_ranks(entry)
    truth_name = entry["truth"]["name"].lower()
    candidates = result.get("candidates") or []
    names = [str(c.get("scientific_name") or "").strip() for c in candidates]

    top1 = bool(names) and names[0].lower() == truth_name
    top3 = any(n.lower() == truth_name for n in names[:3])
    genus_hit = any(genus_of(n) == truth["genus"] for n in names[:3])

    # 科の一致は、候補の上位分類に正解の系統が重なるかで見る (追加の照会が要る)
    family_hit = genus_hit
    if family_check and not genus_hit:
        for name in names[:3]:
            if truth["lineage"] & set(ancestor_ids(name)):
                family_hit = True
                break

    return {
        "photo_id": entry["photo_id"],
        "group": entry["group"],
        "truth": entry["truth"]["name"],
        "truth_ja": entry["truth"]["common_name_ja"],
        "predicted": names[:3],
        "predicted_ja": [c.get("common_name_ja") for c in candidates[:3]],
        "category": result.get("category"),
        "rejected": not candidates,
        "top1": top1,
        "top3": top3,
        "genus": genus_hit,
        "family_or_above": family_hit,
        "confidence_top1": (candidates[0].get("confidence") if candidates else None),
        "evidence_status_top1": (candidates[0].get("evidence_status") if candidates else None),
        # 併用の効果を読むには、実際に専門識別が走ったかが要る。
        # VLM が「植物」と判定しなければ Pl@ntNet は呼ばれない (pipeline.identify_all)
        "plantnet_status": result.get("plantnet_status", "used" if result.get("plantnet_used") else ""),
        "plantnet_used": bool(result.get("plantnet_used")),
    }


def summarize(rows: list[dict], label: str, seconds: list[float]) -> dict[str, object]:
    n = len(rows)
    scored = [r for r in rows if "error" not in r]
    answered = [r for r in scored if not r["rejected"]]
    def rate(key: str) -> float:
        return round(100 * sum(1 for r in scored if r.get(key)) / max(1, len(scored)), 1)
    return {
        "label": label,
        "count": n,
        "errors": n - len(scored),
        "top1_percent": rate("top1"),
        "top3_percent": rate("top3"),
        "genus_percent": rate("genus"),
        "family_or_above_percent": rate("family_or_above"),
        "rejected_percent": round(100 * sum(1 for r in scored if r["rejected"]) / max(1, len(scored)), 1),
        "median_seconds": round(sorted(seconds)[len(seconds) // 2], 1) if seconds else None,
        "mean_confidence_when_answered": (
            round(sum(r["confidence_top1"] or 0 for r in answered) / len(answered), 1) if answered else None
        ),
        "top1_percent_when_answered": (
            round(100 * sum(1 for r in answered if r["top1"]) / len(answered), 1) if answered else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # 検証はOllamaを既定にする。外部APIは無料枠の日次上限があり、評価を回すたびに
    # 公開版の利用者ぶんの枠を削ってしまう。比較で外部が要るときだけ --provider で切り替える。
    parser.add_argument("--provider", default="local", choices=["local", "openai", "anthropic", "gemini"])
    parser.add_argument("--model", default="", help="未指定なら設定中のモデル")
    parser.add_argument("--use-plantnet", action="store_true")
    parser.add_argument("--label", default="", help="結果ファイル名。未指定なら provider から作る")
    parser.add_argument("--limit", type=int, default=0, help="先頭N件だけ試す")
    parser.add_argument("--no-family", action="store_true", help="科の照合を省いて速く回す")
    parser.add_argument("--sleep", type=float, default=0.0, help="1件ごとの待ち時間 (秒)")
    parser.add_argument("--dataset", default=str(MANIFEST), help="評価に使うマニフェスト")
    parser.add_argument("--group", default="", help="この分類群だけを対象にする (植物/昆虫/鳥/菌類/は虫類・両生類)")
    # 実際の利用では撮影地域を入れる人が多いのに、評価では空のまま測っていた。
    # 日本固有種を近縁の別種と取り違える例が目立つので、効くかどうかを測れるようにする
    parser.add_argument("--location", default="", help="撮影地域として渡す (例: 日本)")
    args = parser.parse_args()

    manifest = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    entries = manifest["entries"]
    if args.group:
        entries = [e for e in entries if e["group"] == args.group]
    entries = entries[: args.limit or None]
    settings = config_store.load()
    model = args.model or settings["models"][args.provider]
    api_key = settings["api_keys"].get(args.provider, "")
    plantnet_key = settings["api_keys"].get("plantnet", "") if args.use_plantnet else ""
    label = args.label or f"{args.provider}-{model}" + ("-plantnet" if args.use_plantnet else "")

    if args.provider != "local" and not api_key:
        print(f"APIキーが未登録です: {args.provider}", file=sys.stderr)
        return 1
    if args.use_plantnet and not plantnet_key:
        print("Pl@ntNet のAPIキーが未登録です", file=sys.stderr)
        return 1

    # 無料枠の日次上限に当たっても捨てずに済むよう、成功ぶんは引き継ぐ
    output = RESULTS_DIR / f"{label.replace('/', '_')}.json"
    done: dict[int, dict] = {}
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        done = {r["photo_id"]: r for r in previous.get("rows", []) if "error" not in r}
        if done:
            print(f"（前回の成功 {len(done)}件を引き継ぎます）")

    print(f"■ {label} / {len(entries)}件")
    rows: list[dict] = []
    seconds: list[float] = []
    quota_exhausted = False
    for index, entry in enumerate(entries, 1):
        if entry["photo_id"] in done:
            rows.append(done[entry["photo_id"]])
            continue
        if quota_exhausted:
            rows.append({"photo_id": entry["photo_id"], "truth": entry["truth"]["name"],
                         "group": entry["group"], "error": "skipped: 日次上限"})
            continue
        raw = Path(entry["file"]).read_bytes()
        prepared = [vision.prepare_image(raw)]
        started = time.monotonic()
        try:
            result = pipeline.identify_all(
                prepared, provider=args.provider, model=model, api_key=api_key,
                use_plantnet=args.use_plantnet, plantnet_key=plantnet_key,
                location=args.location,
            )
        except Exception as error:  # 1枚の失敗で全体を止めない
            message = str(error)
            # 日次上限は待っても回復しない。残りを空回しせず、次回に回す
            if "上限" in message or "レート" in message:
                quota_exhausted = True
            rows.append({"photo_id": entry["photo_id"], "truth": entry["truth"]["name"],
                         "group": entry["group"], "error": f"{type(error).__name__}: {message}"})
            print(f"  {index:3}/{len(entries)} {entry['truth']['name']:30} ERROR {message}")
            continue
        elapsed = time.monotonic() - started
        seconds.append(elapsed)
        row = score_one(entry, result, family_check=not args.no_family)
        rows.append(row)
        mark = "○" if row["top1"] else ("△" if row["top3"] or row["genus"] else "×")
        got = row["predicted"][0] if row["predicted"] else "(棄却)"
        print(f"  {index:3}/{len(entries)} {mark} {entry['truth']['name']:30} → {got:30} {elapsed:4.1f}s")
        if args.sleep:
            time.sleep(args.sleep)

    summary = summarize(rows, label, seconds)
    RESULTS_DIR.mkdir(exist_ok=True)
    output.write_text(json.dumps({
        "summary": summary,
        # 何で測ったかを残さないと、条件の違う結果どうしを後から比べてしまう。
        # thinkingLevel を記録しておらず、既存の結果が high だったのか medium
        # だったのかファイルから確かめられなくなった
        "config": {"provider": args.provider, "model": model, "use_plantnet": args.use_plantnet,
                   "thinking_level": vision.GEMINI_THINKING_LEVEL if args.provider == "gemini" else None,
                   "location": args.location,
                   "dataset": manifest["source"], "measured_at": time.strftime("%Y-%m-%d %H:%M")},
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"→ {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
