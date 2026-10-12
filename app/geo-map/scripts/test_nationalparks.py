import json
import sqlite3

import pytest
from shapely.geometry import Polygon
from nationalparks import catalogue, park_rows, build, repair_area


def card(name='テスト国立公園', slug='test', region='熊本県'):
    return f'''<li class="item item-1 area"><a href="../{slug}/index.html"><span class="name">{name}</span></a><ul class="data"><li class="data__date">指定：2024年6月25日</li><li class="data__area">面積：100 ha</li><li class="data__region">{region}</li></ul></li>'''


def feature(name='テスト', coordinates=None):
    return {'type':'Feature','id':1,'properties':{'名称':name,'SA10_1_012':'環境省公園計画'},
            'geometry':{'type':'Polygon','coordinates':[coordinates or [(130,32),(131,32),(131,33),(130,33),(130,32)]]}}


SOURCE={'url':'https://eadas.env.go.jp/area/1','metadata':{'整備年度':'令和6年度'}}


def test_catalogue_deduplicates_regional_cards_and_ignores_navigation():
    page='<li class="item item-2"><a href="index.html">一覧</a></li>'+card()+card()
    parks=catalogue(page)
    assert len(parks)==1
    assert parks['test']['source_url']=='https://www.env.go.jp/park/test/index.html'
    assert parks['test']['prefectures']=='熊本県'


def test_catalogue_rejects_incomplete_or_conflicting_cards():
    with pytest.raises(ValueError):catalogue(card().replace('<li class="data__area">面積：100 ha</li>',''))
    with pytest.raises(ValueError):catalogue(card()+card(region='東京都'))


def test_area_parts_are_merged_and_holes_preserved():
    f=feature()
    f['geometry']['coordinates'].append([(130.2,32.2),(130.2,32.8),(130.8,32.8),(130.8,32.2),(130.2,32.2)])
    other=feature(coordinates=[(131,32),(132,32),(132,33),(131,33),(131,32)])
    rows=park_rows(catalogue(card()),{'features':[f,other]},SOURCE,'2026-10-12')
    geometry=json.loads(rows[0][-2])
    assert len(rows)==1 and len(geometry['coordinates'])==1
    assert len(geometry['coordinates'][0])==2
    assert rows[0][5]=='熊本県' and rows[0][-1]==0


def test_missing_or_unknown_area_stops_import():
    with pytest.raises(ValueError):park_rows(catalogue(card()),{'features':[]},SOURCE,'2026-10-12')
    with pytest.raises(ValueError):park_rows(catalogue(card()),{'features':[feature('未知')]},SOURCE,'2026-10-12')


def test_repair_does_not_accept_area_changing_bowtie():
    with pytest.raises(ValueError):repair_area(Polygon([(0,0),(1,1),(1,0),(0,1),(0,0)]))


def test_self_touching_spike_can_be_repaired_without_changing_area():
    polygon=Polygon([(0,0),(1,0),(1,1),(.5,1),(.5,2),(.5,1),(0,1),(0,0)])
    assert not polygon.is_valid
    result=repair_area(polygon)
    assert result.is_valid and result.area==polygon.area


def test_cached_build_preserves_other_tables_and_failed_build_preserves_database(tmp_path):
    cache=tmp_path/'cache';cache.mkdir()
    (cache/'catalogue.html').write_text(card())
    (cache/'areas.json').write_text(json.dumps({'features':[feature()]}))
    (cache/'source.json').write_text(json.dumps(SOURCE))
    (cache/'meta.json').write_text(json.dumps({'fetched':'2026-10-12','feature_count':1,'object_ids':[1]}))
    db=tmp_path/'geo.db'
    with sqlite3.connect(db) as con:
        con.execute('create table geopark(name text)');con.execute("insert into geopark values('preserved')")
    assert build(cache,db)['parks']==1
    with sqlite3.connect(db) as con:assert con.execute('select name from geopark').fetchone()==('preserved',)
    before=db.read_bytes()
    (cache/'areas.json').write_text(json.dumps({'features':[]}))
    with pytest.raises(ValueError):build(cache,db)
    assert db.read_bytes()==before


def test_cached_partial_park_is_rejected_even_when_all_names_remain():
    from nationalparks import validate_area_snapshot
    a=feature();b=feature();b['id']=2
    with pytest.raises(ValueError):validate_area_snapshot({'features':[a]},{'feature_count':2,'object_ids':[1,2]})
    with pytest.raises(ValueError):validate_area_snapshot({'features':[a,a]},{'feature_count':2})
    with pytest.raises(ValueError):validate_area_snapshot({'features':[a,b]},{'feature_count':2,'object_ids':[1,3]})
