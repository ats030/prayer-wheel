"""BioCLIP 2 で、VLM が出した候補を並べ替えたらどうなるかを測る。

Pl@ntNet と同じ役割 (VLM の答えを別の目で確かめる) を、手元のモデルで果たせるかを
見る。Pl@ntNet は植物にしか使えないが、BioCLIP は生物全体で学習されている。

既に取った評価結果 (eval/results/*.json) の候補を使うので、外部APIを新たに叩かない。

  uv run --with torch --with open_clip_torch --with pillow \
      python eval/bioclip_rerank.py --result v2-base

ライセンス: BioCLIP 2 は MIT。重みを手元に置いて商用にも使える。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
from PIL import Image

RESULTS = Path(__file__).parent / "results"
IMAGES = Path.home() / "cache" / "species-eval" / "images"
MODEL = "hf-hub:imageomics/bioclip-2"

# BioCLIP は学名を並べた文で学習されている。同じ形に寄せると当たりやすい
TEMPLATE = "a photo of {}."


def load_model():
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(MODEL)
    tokenizer = open_clip.get_tokenizer(MODEL)
    model.eval()
    return model, preprocess, tokenizer


@torch.no_grad()
def rank(model, preprocess, tokenizer, image_path: Path, names: list[str]) -> list[tuple[str, float]]:
    """候補の学名を、写真との近さで並べ替える。"""
    image = preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0)
    text = tokenizer([TEMPLATE.format(name) for name in names])
    image_features = model.encode_image(image)
    text_features = model.encode_text(text)
    image_features /= image_features.norm(dim=-1, keepdim=True)
    text_features /= text_features.norm(dim=-1, keepdim=True)
    scores = (image_features @ text_features.T).squeeze(0)
    order = scores.argsort(descending=True)
    return [(names[i], float(scores[i])) for i in order]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", default="v2-base", help="並べ替えの元にする結果")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    data = json.loads((RESULTS / f"{args.result}.json").read_text())
    rows = data["rows"][: args.limit] if args.limit else data["rows"]

    print(f"■ {args.result} の候補を BioCLIP 2 で並べ替える（{len(rows)}件）")
    print("  モデルを読み込んでいます…", flush=True)
    started = time.time()
    model, preprocess, tokenizer = load_model()
    print(f"  読み込み {time.time() - started:.0f}秒", flush=True)

    before = after = usable = 0
    per_group: dict[str, list[int]] = {}
    seconds: list[float] = []

    for index, row in enumerate(rows, 1):
        names = row.get("predicted") or []
        truth = row["truth"]
        image = IMAGES / f"{row['photo_id']}.jpg"
        if len(names) < 2 or not image.exists():
            continue                        # 並べ替える余地がない
        usable += 1
        began = time.time()
        ranked = rank(model, preprocess, tokenizer, image, names)
        seconds.append(time.time() - began)

        was = names[0] == truth
        now = ranked[0][0] == truth
        before += was
        after += now
        per_group.setdefault(row["group"], [0, 0, 0])
        per_group[row["group"]][0] += 1
        per_group[row["group"]][1] += was
        per_group[row["group"]][2] += now
        if was != now:
            print(f"  {index:>3}/{len(rows)} {'×→○' if now else '○→×'} {row['truth_ja'] or truth}"
                  f"  {names[0]} → {ranked[0][0]}", flush=True)

    print(f"\n■ 並べ替えられた {usable} 件")
    print(f"  BioCLIP 前: {before} 件正解 ({100*before/max(1,usable):.1f}%)")
    print(f"  BioCLIP 後: {after} 件正解 ({100*after/max(1,usable):.1f}%)")
    print(f"  1枚あたり {sum(seconds)/max(1,len(seconds)):.2f}秒")
    print(f"\n{'グループ':14} {'件数':>5} {'前':>5} {'後':>5}")
    for group, (n, was, now) in sorted(per_group.items()):
        print(f"  {group:12} {n:>5} {was:>5} {now:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
