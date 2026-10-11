from geoparks import municipalities, regions, resolve

LISTING = """
<a href="aso/">
  <img src="img/ggnmarker.png" title="阿蘇ユネスコ世界ジオパーク<span class='areaname'>熊本県阿蘇市、南小国町（1市1町）</span>"
   data-jgnyear="日本ジオパーク：2009年10月認定" data-ggnyear="世界ジオパーク：2014年9月認定"
   data-unesco_ggnyear="ユネスコ世界ジオパーク：2015年11月～">
</a>
<!-- <a href="fukui/"><img title="恐竜渓谷ふくい勝山ジオパーク" data-jgnyear="" data-ggnyear="" data-unesco_ggnyear=""></a> -->
<a href="zao/"><img src="img/jgnmarker.png" title="蔵王ジオパーク" data-jgnyear="日本ジオパーク：2025年1月認定" data-ggnyear="" data-unesco_ggnyear=""></a>
<a href="about/">about</a>
"""


def page(section: str, contact: str = "〒869-2612　熊本県阿蘇市一の宮町宮地") -> str:
    return f"<dt>構成自治体名</dt><dd>{section}</dd><h3>お問合せ先</h3><p>{contact}</p>"


def test_regions_skip_commented_out_and_navigation_links():
    found = regions(LISTING)
    assert sorted(found) == ["aso", "zao"]
    assert found["aso"] == {"name": "阿蘇ユネスコ世界ジオパーク", "certified": "2009年10月", "unesco": True, "count": 2}
    assert found["zao"]["certified"] == "2025年1月" and not found["zao"]["unesco"]


def test_municipalities_take_the_contact_prefecture_by_default():
    parsed = municipalities(page("阿蘇市、阿蘇郡南小国町、上益城郡山都町（1市2町）"))
    assert parsed["munis"] == [["熊本県", "", "阿蘇市"], ["熊本県", "阿蘇郡", "南小国町"], ["熊本県", "上益城郡", "山都町"]]
    assert parsed["partial"] == []


def test_municipalities_apply_trailing_prefecture_marker_backwards():
    parsed = municipalities(page("都城市、小林市（以上宮崎県）、鹿児島県霧島市、湧水町"))
    assert parsed["munis"] == [["宮崎県", "", "都城市"], ["宮崎県", "", "小林市"],
                               ["鹿児島県", "", "霧島市"], ["鹿児島県", "", "湧水町"]]


def test_municipalities_mark_partial_areas():
    parsed = municipalities(page("山口県萩市、阿武町、山口市（阿東地域）、美祢市の一部"))
    assert [m[2] for m in parsed["munis"]] == ["萩市", "阿武町", "山口市", "美祢市"]
    assert parsed["partial"] == ["山口市", "美祢市"]


def test_resolve_uses_district_to_pick_between_same_names():
    table = {"01": {("", "伊達市"): "a", ("虻田郡", "洞爺湖町"): "b"},
             "07": {("", "伊達市"): "c"},
             "43": {("阿蘇郡", "小国町"): "d"}, "06": {("西置賜郡", "小国町"): "e"}}
    lookup = table.__getitem__
    assert resolve(["北海道", "", "伊達市"], [], lookup) == ("北海道", "", "a")
    assert resolve(["熊本県", "阿蘇郡", "小国町"], [], lookup) == ("熊本県", "阿蘇郡", "d")
    assert resolve(["", "", "伊達市"], ["福島県"], lookup) == ("福島県", "", "c")
    assert resolve(["熊本県", "", "存在しない町"], [], lookup) is None
