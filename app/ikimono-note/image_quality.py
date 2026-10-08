"""識別前に写真の質を見る。

暗すぎる・小さすぎる・ぼけている写真をAIへ送っても、返ってくるのは自信のない
推測か、もっともらしい誤りになる。送る前に気づけば、利用者の枠を使わずに済み、
撮り直しも早い。

閾値は評価用の写真 (iNaturalist の research-grade) で分布を測って決める。
ここを勘で決めると、普通に撮れた写真を弾いて使えなくなる。
"""

from __future__ import annotations

import io
import math

from PIL import Image

# 判定の重さ。block は送らせない、warn は伝えて続けさせる
BLOCK = "block"
WARN = "warn"


def _laplacian_variance(gray: Image.Image) -> float:
    """ぼけの度合い。輪郭の強さのばらつきが小さいほどぼけている。"""
    width, height = gray.size
    pixels = gray.load()
    total = 0.0
    total_sq = 0.0
    count = 0
    # 端は見ない。1画素ずつでは遅いので、長辺320程度に縮めてから呼ぶこと
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            value = (pixels[x, y] * 4 - pixels[x - 1, y] - pixels[x + 1, y]
                     - pixels[x, y - 1] - pixels[x, y + 1])
            total += value
            total_sq += value * value
            count += 1
    if count == 0:
        return 0.0
    mean = total / count
    return max(0.0, total_sq / count - mean * mean)


def measure(data: bytes) -> dict[str, float]:
    """写真の質を数字にする。判定はしない。"""
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        width, height = image.size
        gray = image.convert("L")
        # ぼけの計算だけ縮めて行う。元の大きさのままだと数秒かかる
        scale = 320 / max(gray.size)
        small = gray.resize((max(1, int(gray.width * scale)), max(1, int(gray.height * scale)))) \
            if scale < 1 else gray
        sharpness = _laplacian_variance(small)
        histogram = gray.histogram()
        pixels = sum(histogram) or 1
        brightness = sum(i * n for i, n in enumerate(histogram)) / pixels
        # 明暗の幅。真っ白や真っ黒に潰れていると小さくなる
        mean_sq = sum(i * i * n for i, n in enumerate(histogram)) / pixels
        contrast = math.sqrt(max(0.0, mean_sq - brightness * brightness))
    return {
        "width": width, "height": height, "pixels": width * height,
        "sharpness": round(sharpness, 1),
        "brightness": round(brightness, 1),
        "contrast": round(contrast, 1),
    }


# 閾値は評価用の写真44枚 (iNaturalist research-grade) の分布から決めた。
# その最小値は sharpness 161.4 / brightness 35.7 / contrast 15.2 なので、
# どれも下限より十分下に置き、普通に撮れた写真を弾かないようにしてある。
#
# 縮小すると輪郭が相対的に強まり sharpness は上がる (160x120 で 4899、元は 2841)。
# 小さい写真はぼけ判定をすり抜けるので、先に大きさを見る。
MIN_EDGE_BLOCK = 200        # これ未満は何が写っているか分からない
MIN_EDGE_WARN = 300         # 短辺300未満は種の決め手が写りにくい。
                            # 評価用の写真は短辺333〜375で、その大きさで Top-1 40% を
                            # 出せている。識別できている大きさに注意を出しては意味がない
MIN_BRIGHTNESS_BLOCK = 15   # ほぼ真っ暗 (8%まで落とした写真で 9.4)
MIN_BRIGHTNESS_WARN = 25    # 暗い (18%まで落とした写真で 21.7)
MIN_SHARPNESS_WARN = 50     # ぼけ (半径4のぼかしで 9.7)
MIN_CONTRAST_WARN = 10      # 白飛び・黒潰れ


def judge(data: bytes) -> dict[str, object]:
    """写真の質を見て、撮り直しを促すかどうかを決める。

    弾くのは、何が写っているか分からない場合だけにする。迷う程度のものまで
    止めると、条件の悪い場所でしか会えない生きものを調べられなくなる。
    """
    return judge_measured(measure(data))


def judge_measured(measured: dict) -> dict[str, object]:
    """Apply the same guidance to native or bounded browser measurements."""
    edge = min(measured["width"], measured["height"])
    problems: list[dict[str, str]] = []

    if edge < MIN_EDGE_BLOCK:
        problems.append({"level": BLOCK, "reason": "small",
                         "message": "写真が小さすぎます。もっと大きな写真で撮り直してください。"})
    elif edge < MIN_EDGE_WARN:
        problems.append({"level": WARN, "reason": "small",
                         "message": "写真が小さめです。近づいて撮ると、葉や体の模様まで見分けやすくなります。"})

    if measured["brightness"] < MIN_BRIGHTNESS_BLOCK:
        problems.append({"level": BLOCK, "reason": "dark",
                         "message": "写真が暗すぎて、何が写っているか分かりません。明るい場所で撮り直してください。"})
    elif measured["brightness"] < MIN_BRIGHTNESS_WARN:
        problems.append({"level": WARN, "reason": "dark",
                         "message": "写真が暗めです。明るい場所で撮ると見分けやすくなります。"})

    # 小さい写真では、ぼけているかどうかを正しく測れない
    if edge >= MIN_EDGE_BLOCK and measured["sharpness"] < MIN_SHARPNESS_WARN:
        problems.append({"level": WARN, "reason": "blurry",
                         "message": "写真がぼやけています。ピントを合わせて撮り直すと、見分けやすくなります。"})

    if measured["contrast"] < MIN_CONTRAST_WARN:
        problems.append({"level": WARN, "reason": "flat",
                         "message": "明るさの差が小さく、輪郭が分かりにくい写真です。"})

    blocked = [p for p in problems if p["level"] == BLOCK]
    return {
        "ok": not blocked,
        "level": BLOCK if blocked else (WARN if problems else ""),
        "problems": problems,
        "measured": measured,
    }
