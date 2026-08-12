"""種の保存法の照合。法律の話なので、外す向きを固定しておく。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pipeline
import protected_species
import vision


def test_bundled_list_matches_the_published_count():
    """同梱リストが環境省の公表数と合っていること (国内希少458 + 緊急指定3)。"""
    data = json.loads((Path(__file__).parents[1] / "data" / "protected_species.json").read_text(encoding="utf-8"))
    domestic = [s for s in data["species"] if s["category"] == "国内希少野生動植物種"]
    urgent = [s for s in data["species"] if s["category"] == "緊急指定種"]
    assert len(domestic) == 458
    assert len(urgent) == 3
    assert data["count"] == len(data["species"]) == 461
    assert data["as_of"] == "令和7年2月"
    assert protected_species.count() == 461
    assert protected_species.as_of() == "令和7年2月"


def test_international_species_are_not_bundled():
    """別表第二 (国際希少野生動植物種) は入れない。規制するのは主に譲渡し・輸出入で、
    日本の野外で名前を調べる画面に出すと関係のない警告になる。"""
    assert protected_species.lookup("Anas diazi") is None  # メキシコガモ (別表第二)
    assert protected_species.lookup("Branta sandvicensis") is None  # ハワイガン (別表第二)


def test_lookup_is_exact_and_case_insensitive():
    found = protected_species.lookup("acheilognathus longipinnis")
    assert found["common_name_ja"] == "イタセンパラ"
    assert found["category"] == "国内希少野生動植物種"
    # 属だけ、前方一致、空文字では引かない。亜種指定を種の指定と読み替えないため。
    assert protected_species.lookup("Acheilognathus") is None
    assert protected_species.lookup("Acheilognathus longipinnis var. x") is None
    assert protected_species.lookup("") is None
    assert protected_species.lookup(None) is None


def test_subtype_is_carried_because_the_rule_differs():
    """特定第二種は販売・頒布目的の捕獲等だけが規制。ひとまとめにすると画面が嘘をつく。"""
    assert protected_species.lookup("Acanthephippium pictum")["subtype"] == "特定第一種"
    subtypes = {s["subtype"] for s in json.loads(
        (Path(__file__).parents[1] / "data" / "protected_species.json").read_text(encoding="utf-8"))["species"]}
    assert subtypes == {"", "特定第一種", "特定第二種"}


def test_urgent_designation_is_included():
    """緊急指定種も種の保存法の規制対象。3件だけだが、落とすと見落とす。"""
    found = protected_species.lookup("Hosta minazukiflora")
    assert found["category"] == "緊急指定種"


def test_annotate_marks_only_the_matching_candidate():
    result = protected_species.annotate({"candidates": [
        {"scientific_name": "Acheilognathus longipinnis"},
        {"scientific_name": "Taraxacum officinale"},
    ]})
    hit, miss = result["candidates"]
    assert hit["protected_species"]["category"] == "国内希少野生動植物種"
    assert hit["protected_species"]["as_of"] == "令和7年2月"
    # 一致しなかった候補には何も付けない。「指定なし」という情報は持っていない
    assert "protected_species" not in miss


def test_missing_data_file_does_not_break_identification(monkeypatch, tmp_path):
    """リストを読めなくても識別は続く。出せないのは注意書き1つ。"""
    protected_species._table.cache_clear()
    monkeypatch.setattr(protected_species, "DATA_PATH", tmp_path / "missing.json")
    try:
        assert protected_species.lookup("Acheilognathus longipinnis") is None
        assert protected_species.as_of() == ""
        assert protected_species.annotate({"candidates": [{"scientific_name": "x"}]})["candidates"] == [
            {"scientific_name": "x"}]
    finally:
        protected_species._table.cache_clear()


def test_the_image_ships_the_list():
    """公開版 (Cloud Run) にリストを入れ忘れないこと。

    Dockerfile は *.py と static しか入れていなかった。入れ忘れると照合だけが
    静かに消え、画面上は「指定なし」と区別が付かない。
    """
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY data/protected_species.json ./data/" in dockerfile


def test_pipeline_annotates_after_the_evidence_gate(monkeypatch):
    """画面に出る候補にだけ付くこと。ゲートで落ちた候補に注意書きを付けても届かない。"""
    monkeypatch.setattr(vision, "identify", lambda *a, **k: {
        "category": "動物", "summary": "", "model": "test", "provider": "local",
        "candidates": [{
            "scientific_name": "Acheilognathus longipinnis", "common_name_ja": "イタセンパラ",
            "confidence": 70, "traits": ["体高が高い", "尻びれが長い"],
            "distinguishing_features": ["近縁種と産卵期が違う"], "contradictions": [],
        }],
    })
    monkeypatch.setattr(vision, "_lookup_taxon", lambda name: [
        {"name": "Acheilognathus longipinnis", "id": 1, "rank": "species",
         "preferred_common_name": "イタセンパラ", "iconic_taxon_name": "Actinopterygii"}])
    result = pipeline.identify_all([b"x"], provider="local", model="m")
    assert result["candidates"][0]["protected_species"]["common_name_ja"] == "イタセンパラ"


def test_pipeline_leaves_ordinary_species_alone(monkeypatch):
    monkeypatch.setattr(vision, "identify", lambda *a, **k: {
        "category": "植物", "summary": "", "model": "test", "provider": "local",
        "candidates": [{
            "scientific_name": "Taraxacum officinale", "common_name_ja": "セイヨウタンポポ",
            "confidence": 70, "traits": ["ぎざぎざの葉", "黄色い頭花"],
            "distinguishing_features": ["総苞外片が反り返る"], "contradictions": [],
        }],
    })
    monkeypatch.setattr(vision, "_lookup_taxon", lambda name: [
        {"name": "Taraxacum officinale", "id": 2, "rank": "species",
         "preferred_common_name": "セイヨウタンポポ", "iconic_taxon_name": "Plantae"}])
    result = pipeline.identify_all([b"x"], provider="local", model="m")
    assert "protected_species" not in result["candidates"][0]
