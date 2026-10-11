import sqlite3

from geodb import replace_tables
from geosites import classify, criteria


def page(value: str) -> str:
    return f"<tr><th>指定基準</th><td>：</td><td>{value}</td></tr>\n<tr><th>所在都道府県</th><td>福井県</td></tr>"


def test_criteria_extracts_the_field_and_unescapes_it():
    assert criteria(page("（七）岩石の組織,&#x28;九&#x29;風化及び侵蝕に関する現象")) == "（七）岩石の組織,(九)風化及び侵蝕に関する現象"
    assert criteria(page("")) == ""
    assert criteria("<p>ページが見つかりません</p>") is None


def test_classify_matches_geology_phrases_not_shared_words():
    # 名勝 「五．岩石、洞穴」 and 植物 （九） must not count as geology.
    assert classify("五．岩石、洞穴,八．砂丘、砂嘴(さし)、海浜、島嶼") == "other"
    assert classify("植物（九）珍奇又は絶滅に瀕した植物の主要な自生地") == "bio"
    assert classify("（七）岩石の組織,五．岩石、洞穴") == "geo"
    assert classify("地質鉱物（六）洞穴,動物（一）日本特有の動物で著名なもの及びその棲息地") == "geo+bio"
    assert classify("") == classify(None) == "unknown"


def test_replace_tables_keeps_tables_owned_by_other_builders(tmp_path):
    db = tmp_path / "geo.db"
    replace_tables(db, "create table geopark(slug text);", {"geopark": [("aso",)]}, {"built": "a", "geopark_source": "x"})
    replace_tables(db, "create table geosite(id text);", {"geosite": [("1050",)]}, {"built": "b"})
    replace_tables(db, "create table geosite(id text);", {"geosite": [("1051",)]}, {"built": "c"})
    con = sqlite3.connect(db)
    assert con.execute("select slug from geopark").fetchall() == [("aso",)]
    assert con.execute("select id from geosite").fetchall() == [("1051",)]
    assert dict(con.execute("select key, value from meta")) == {"built": "c", "geopark_source": "x"}
