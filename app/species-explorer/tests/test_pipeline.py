import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import pipeline
import vision


def fake_vlm(category):
    return lambda *args, **kwargs: {"category": category, "summary": "", "candidates": [],
                                    "model": "test", "provider": "local"}


def test_specialist_is_skipped_for_fungi(monkeypatch):
    """菌類を植物専用サービスへ送ると候補が丸ごとすり替わる。実測で
    シロソウメンタケが Pachysandra procumbens になり Top-1 が 17%→0% に落ちた。"""
    monkeypatch.setattr(vision, "identify", fake_vlm("菌類"))
    monkeypatch.setattr(vision, "identify_plantnet",
                        lambda *a, **k: pytest.fail("菌類を植物専用サービスへ送ってはいけない"))
    result = pipeline.identify_all([b"x"], provider="local", model="m",
                                   use_plantnet=True, plantnet_key="key")
    assert result["plantnet_status"] == "not_plant"


def test_specialist_is_skipped_when_undecided(monkeypatch):
    """「不明」でも呼ばない。中身が菌類やそれ以外である可能性を排除できない。"""
    monkeypatch.setattr(vision, "identify", fake_vlm("不明"))
    monkeypatch.setattr(vision, "identify_plantnet",
                        lambda *a, **k: pytest.fail("植物と判定していない写真を送らない"))
    result = pipeline.identify_all([b"x"], provider="local", model="m",
                                   use_plantnet=True, plantnet_key="key")
    assert result["plantnet_status"] == "not_plant"


def test_specialist_is_skipped_for_animals(monkeypatch):
    monkeypatch.setattr(vision, "identify", fake_vlm("動物"))
    monkeypatch.setattr(vision, "identify_plantnet",
                        lambda *a, **k: pytest.fail("動物写真を植物専用サービスへ送ってはいけない"))
    result = pipeline.identify_all([b"x"], provider="local", model="m",
                                   use_plantnet=True, plantnet_key="key")
    assert result["plantnet_status"] == "not_plant"


def test_specialist_needs_a_key(monkeypatch):
    monkeypatch.setattr(vision, "identify", fake_vlm("植物"))
    monkeypatch.setattr(vision, "identify_plantnet",
                        lambda *a, **k: pytest.fail("キーなしで外部へ送ってはいけない"))
    result = pipeline.identify_all([b"x"], provider="local", model="m",
                                   use_plantnet=True, plantnet_key="")
    assert result["plantnet_status"] == "not_configured"


def test_specialist_failure_does_not_lose_the_model_result(monkeypatch):
    monkeypatch.setattr(vision, "identify", fake_vlm("植物"))
    def boom(*args, **kwargs):
        raise vision.VisionError("Pl@ntNetに接続できませんでした")
    monkeypatch.setattr(vision, "identify_plantnet", boom)
    result = pipeline.identify_all([b"x"], provider="local", model="m",
                                   use_plantnet=True, plantnet_key="key")
    assert result["plantnet_status"] == "unavailable"
    assert result["category"] == "植物"
