import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import pipeline
import vision


def fake_vlm(category):
    return lambda *args, **kwargs: {"category": category, "summary": "", "candidates": [],
                                    "model": "test", "provider": "local"}


def test_specialist_runs_when_the_model_could_not_decide(monkeypatch):
    """「不明」は専門識別を外す理由にならない。判断できなかった写真こそ使う。"""
    called = {}

    def fake_plantnet(images, key):
        called["hit"] = True
        return {"category": "植物", "summary": "s", "candidates": [],
                "model": "plantnet", "provider": "plantnet"}

    monkeypatch.setattr(vision, "identify", fake_vlm("不明"))
    monkeypatch.setattr(vision, "identify_plantnet", fake_plantnet)
    result = pipeline.identify_all([b"x"], provider="local", model="m",
                                   use_plantnet=True, plantnet_key="key")
    assert called.get("hit") is True
    assert result.get("plantnet_status") != "not_plant"


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
