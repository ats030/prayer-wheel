"""写真の質を見る仕組み。

閾値は評価用の写真44枚 (iNaturalist research-grade) の分布から決めた。ここを
勘で決めると、普通に撮れた写真を弾いて使い物にならなくなる。
"""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parents[1]))
import image_quality  # noqa: E402


def photo(size=(600, 450), blur=0.0, scale=1.0):
    """模様のある写真を作る。一色では輪郭が無く、ぼけと区別できない。"""
    image = Image.new("RGB", size, (40, 110, 60))
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            if (x // 6 + y // 6) % 2:
                pixels[x, y] = (215, 195, 95)
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    if scale != 1.0:
        image = image.point(lambda v: int(v * scale))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def test_a_normal_photo_passes_without_a_word():
    result = image_quality.judge(photo())
    assert result["ok"] and not result["problems"]


@pytest.mark.parametrize("data, reason, level", [
    (photo(size=(160, 120)), "small", image_quality.BLOCK),
    (photo(scale=0.06), "dark", image_quality.BLOCK),
    (photo(blur=5), "blurry", image_quality.WARN),
    (photo(scale=0.16), "dark", image_quality.WARN),
    (photo(size=(280, 210)), "small", image_quality.WARN),
])
def test_bad_photos_are_caught_at_the_right_strength(data, reason, level):
    found = {p["reason"]: p["level"] for p in image_quality.judge(data)["problems"]}
    assert found.get(reason) == level, found


def test_only_the_unusable_are_turned_away():
    """迷う程度で止めると、条件の悪い場所でしか会えない生きものを調べられない。"""
    assert image_quality.judge(photo(blur=5))["ok"]        # ぼけていても送れる
    assert image_quality.judge(photo(scale=0.16))["ok"]    # 暗くても送れる
    assert not image_quality.judge(photo(scale=0.06))["ok"]  # 何も見えないなら止める


def test_a_small_photo_is_not_judged_for_blur():
    """縮小すると輪郭が相対的に強まり、ぼけ判定をすり抜ける (160x120 で 4899、元は 2841)。
    だから大きさを先に見て、小さいものにぼけの判定を下さない。"""
    reasons = [p["reason"] for p in image_quality.judge(photo(size=(160, 120), blur=5))["problems"]]
    assert "small" in reasons
    assert "blurry" not in reasons, reasons   # 測れないものについて言わない


def test_every_complaint_says_what_to_do():
    for data in [photo(size=(160, 120)), photo(scale=0.06), photo(blur=5), photo(size=(280, 210))]:
        for problem in image_quality.judge(data)["problems"]:
            assert problem["message"].endswith("。"), problem
            assert any(word in problem["message"] for word in ["撮り", "近づいて", "明るい", "ピント", "分かり"]), problem


def test_thresholds_stay_below_what_real_photos_measure():
    """評価用44枚の最小は sharpness 161.4 / brightness 35.7 / contrast 15.2。
    閾値がこれを超えると、ちゃんと撮れた写真を弾き始める。"""
    assert image_quality.MIN_SHARPNESS_WARN < 161.4
    assert image_quality.MIN_BRIGHTNESS_WARN < 35.7
    assert image_quality.MIN_CONTRAST_WARN < 15.2
    assert image_quality.MIN_EDGE_WARN <= 300      # 評価写真の短辺は 281〜375
