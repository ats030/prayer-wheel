"""Score weights, stored as data rather than constants.

patent-miner keeps its weights in a settings table and its CLAUDE.md records an
actual retune ("EPO OPS は被引用数を返さない … w_citation を下げ w_ai を引き上げた").
That is only possible because the weights are editable without a code change, so
the same applies here: defaults live in code, overrides in a small JSON file.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .config import DATA_DIR

SETTINGS_FILE = DATA_DIR / "score_weights.json"

# 第1段（ルール層）の各成分の重み。すべて 0..1 の値に掛かり、合計で割って
# 正規化するので、重みを変えてもスコアのスケールは保たれる。
DEFAULTS: dict[str, float] = {
    # 加点3軸。重みは実データでの発火率を見て決めてある
    # （patent-miner が w_citation を実測で下げたのと同じ調整）。
    # 新規性・意外性の語彙は見出しの数%にしか出ないので当たれば効くボーナス、
    # 常時変動する具体性が土台。「面白さ」そのものの判定は第2段の LLM に持たせる。
    "w_novelty": 0.28,      # 新規性・希少性
    "w_surprise": 0.14,     # 意外性・反転
    "w_specificity": 0.58,  # 具体性（単位つき数値の密度・バッチ内相対）
    # 告知・宣伝の減点率。加点軸に混ぜず乗算で効かせる（1.0 で最大 100% 減点）
    "w_penalty": 0.85,
    # 絶対評価とフィード内相対評価の配合。相対側を厚くしないと、数値を
    # あまり含まないフィード（エッセイ・漫画など）が横断一覧で沈む。
    "w_absolute": 0.55,
    "w_relative": 0.45,
    # 第2段（LLM）が最終スコアを動かせる幅。0.4 なら ×0.6〜×1.4。
    "w_llm": 0.40,
    # 🔥 を付ける閾値（10点満点）。実データの p97 に合わせてある
    # （1,782件中53件）。配点を変えたら再較正すること。
    "high_threshold": 7.1,
    # フィード内相対化に必要な最低記事数。これ未満は中立 0.5 を返す。
    "min_feed_items": 5,
    # 第2段を回す件数
    "llm_top_n": 50,
}

_lock = threading.Lock()
_cache: tuple[float, dict[str, float]] | None = None


def load() -> dict[str, float]:
    """Defaults merged with the on-disk overrides, memoised on mtime."""
    global _cache
    try:
        mtime = SETTINGS_FILE.stat().st_mtime
    except OSError:
        return dict(DEFAULTS)
    with _lock:
        if _cache is not None and _cache[0] == mtime:
            return dict(_cache[1])
    try:
        raw = json.loads(SETTINGS_FILE.read_text())
    except Exception:
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    for key, value in raw.items():
        if key in DEFAULTS:
            try:
                merged[key] = float(value)
            except (TypeError, ValueError):
                continue
    with _lock:
        _cache = (mtime, merged)
    return dict(merged)


def save(values: dict[str, float]) -> dict[str, float]:
    """Persist only known keys, clamped to sane ranges."""
    merged = load()
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        if key == "high_threshold":
            num = max(0.0, min(10.0, num))
        elif key == "min_feed_items":
            num = max(1.0, min(50.0, round(num)))
        elif key == "llm_top_n":
            num = max(1.0, min(500.0, round(num)))
        else:
            num = max(0.0, min(1.0, num))
        merged[key] = num
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    os.replace(tmp, SETTINGS_FILE)
    global _cache
    with _lock:
        _cache = None
    return merged


def reset() -> dict[str, float]:
    return save(dict(DEFAULTS))
