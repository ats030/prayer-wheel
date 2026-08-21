"""評価スクリプトの引数の検査。

測定条件が黙って変わると、条件の違う結果どうしを後から比べてしまう。実際に
ats030-e4xg で『Gemini 経路が6倍遅くなった』と13日間読み違えていた。原因は
--model を省いたときに設定ストアのモデルが使われることで、設定ストアは画面から
書き換わるためアプリの既定と一致している保証が無い (ats030-pqr7)。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[1] / "eval"))

import run_eval  # noqa: E402


def test_model_must_be_given_explicitly():
    """省略を許すと、何で測ったかが手元の設定に依存して分からなくなる。"""
    parser = run_eval.build_parser()
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["--provider", "gemini"])
    assert caught.value.code == 2


def test_model_comes_from_the_command_line():
    parser = run_eval.build_parser()
    args = parser.parse_args(["--provider", "gemini", "--model", "gemini-3.5-flash-lite"])
    assert args.model == "gemini-3.5-flash-lite"


def test_the_settings_store_no_longer_decides_the_model():
    """鍵は設定ストアから取り続けるが、モデルは取らない。

    ats030-e4xg では settings.json の models.gemini が gemini-3.6-flash に
    なっており、--model を省いたランだけ 4倍遅いモデルで測られていた。
    """
    source = Path("eval/run_eval.py").read_text(encoding="utf-8")
    assert 'settings["models"]' not in source
    assert 'settings["api_keys"]' in source
