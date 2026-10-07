import csv
import io
import json
import hashlib

import pytest
from fastapi.testclient import TestClient

from exam_trainer import bank, db, quality, products, materials
from exam_trainer.config import settings
from exam_trainer.app import app, ADMIN_COOKIE


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'data_dir',tmp_path)
    monkeypatch.setattr(settings,'admin_token','quality-test-token')
    db.reset_for_tests(tmp_path)
    monkeypatch.setattr(quality,'start_worker',lambda:None)
    monkeypatch.setattr(quality.ollama_client,'model_fingerprint',lambda name:{'name':name,'digest':'test','status':'recorded'})
    yield
    db.close()


def original_rows():
    return {table:[tuple(r) for r in db.connection().execute(f'SELECT * FROM {table} ORDER BY 1')]
            for table in ('exam','question','syllabus_node','material','review','card')}


def completed():
    run = quality.enqueue(use_llm=False,start=False)
    quality.execute(run['id'])
    return quality.get_run(run['id'])


def example():
    return {'content_key':'test','exam':'テスト','stem':'十分に長い確認用の問題文です。',
            'choices':['正解','誤答一','誤答二','誤答三'],'answer':0,'explanation':'独自の解説',
            'evidence':['根拠の文は出典本文中に二十文字以上で存在します。'],
            'sources':[{'url':'https://example.test','title':'出典','fetched_at':'2026-10-06',
                        'text':'根拠の文は出典本文中に二十文字以上で存在します。'}],
            'categories':['基本'],'keywords':[],'origins':['generated'],'locations':[]}


def mock_response(prompt,**kwargs):
    data = json.loads(prompt.split('\n',1)[1])
    return {'items':[{'id':q['id'],'grades':{axis:'pass' for axis in quality.SEMANTIC},
                      'reason':'本文と整合し、誤答と区別できます。','quote':q['sources'][0]['text'] if q['sources'] else ''}
                     for q in data]}


def test_prompt_keeps_exam_identity_and_prioritizes_matching_source():
    q = example()
    q['exam_identity'] = 'bank:1'
    q['sources'] = [dict(q['sources'][0],text='根拠と関係のない本文です。') for _ in range(2)] + q['sources']
    other = {**q,'exam_identity':'bank:2','stem':q['stem']+'別検定'}
    rows = [{'id':1,'digest':'a','snapshot':q},{'id':2,'digest':'b','snapshot':other}]
    payload = json.loads(quality.prompt_for(rows[:1],rows).split('\n',1)[1])
    assert payload[0]['related_stems']==[]
    assert q['evidence'][0] in payload[0]['sources'][0]['text']


def csv_text(records):
    output = io.StringIO()
    writer = csv.DictWriter(output,fieldnames=quality.CSV_FIELDS,lineterminator='\n')
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def test_snapshot_merges_exact_bank_product_copies_but_preserves_revisions():
    product = products.load_product('g')
    q = product['questions'][0]
    eid = bank.create_exam('G検定','g')
    bank.set_syllabus(eid,[{'path':q['node_path'],'title':q['category']}])
    qid = bank.add_question(eid,q['node_path'],q['stem'],q['choices'],q['answer'],explanation=q['explanation'],
                            evidence=q['provenance']['evidence'],source_refs=[product['sources'][q['source']]['url']],
                            status='verified',origin='generated')
    bank.answer(qid,q['answer'])
    before = original_rows()
    run = quality.enqueue(use_llm=False,start=False)
    items = quality.rows(run['id'])
    found = [r for r in items if r['snapshot']['stem']==q['stem'] and r['snapshot']['exam']=='G検定']
    assert len(found)==1
    assert {loc['kind'] for loc in found[0]['snapshot']['locations']}=={'bank','product'}

    db.connection().execute('UPDATE question SET explanation=? WHERE id=?',('別の解説',qid))
    db.connection().commit()
    assert quality.decorated_items(run['id'])[found[0]['id']-items[0]['id']]['stale']
    updated = quality.collect(db.connection())
    assert len([r for r in updated if r['stem']==q['stem'] and r['exam']=='G検定'])==2
    # Diagnostic itself did not write any learning table.
    after = original_rows()
    for table in before:
        if table!='question':
            assert before[table]==after[table]


def test_same_name_exams_and_other_node_sources_stay_separate():
    quote = '別分野だけに保存された二十文字以上の根拠引用です。'
    for slug in ('first','second'):
        eid = bank.create_exam('同名の検定',slug)
        bank.set_syllabus(eid,[{'path':'1','title':'基本'},{'path':'2','title':'別分野'}])
        bank.add_question(eid,'1','同名検定で共通の十分に長い問題文です。', ['正解','誤答'],0,
                          explanation='解説',evidence=quote,source_refs=['https://example.test'])
        materials.save(eid,'2','https://example.test','別分野',quote)
    snapshots = [q for q in quality.collect(db.connection()) if q['exam']=='同名の検定']
    assert len(snapshots)==2
    assert snapshots[0]['content_key']!=snapshots[1]['content_key']
    assert all(quality.deterministic(q)['grounding']['verdict']=='unknown' for q in snapshots)


def test_rules_and_diagnosis_never_change_source_records():
    eid = bank.create_exam('テスト','test')
    bank.add_question(eid,'1','短い',['同じ','同じ','誤答'],0,status='held')
    before = original_rows()
    run = completed()
    assert run['status']=='done'
    assert original_rows()==before
    target = next(r for r in quality.rows(run['id']) if r['snapshot']['exam']=='テスト')
    assert target['result']['grades']['shape']['verdict']=='fail'
    assert target['result']['verdict']=='fail'
    assert run['summary']['llm_completed']==0
    assert sum(r['sampled'] for r in quality.rows(run['id']))==30
    assert quality.human_metrics(quality.decorated_items(run['id']))['confirmed']==0


def test_enqueue_joins_active_snapshot_and_recovery_keeps_completed_items(monkeypatch):
    run = quality.enqueue(use_llm=False,start=False)
    assert quality.enqueue(start=False)['id']==run['id']
    with db.transaction() as conn:
        conn.execute("UPDATE quality_run SET status='running' WHERE id=?",(run['id'],))
    quality.recover()
    assert quality.get_run(run['id'])['status']=='queued'
    quality.execute(run['id'])
    before = [(r['id'],r['result']) for r in quality.rows(run['id'])]
    # Re-enter after a crash at finalisation without paying for judged items again.
    monkeypatch.setattr(quality,'semantic',lambda *a:pytest.fail('completed items were re-evaluated'))
    quality.execute(run['id'])
    assert before==[(r['id'],r['result']) for r in quality.rows(run['id'])]


@pytest.mark.parametrize('mutation', ['missing','badtype','unknown_id','duplicate','fake_quote'])
def test_semantic_response_strictness_and_no_fabricated_evidence(monkeypatch,mutation):
    row = {'id':1,'digest':'one','snapshot':example()}
    def response(prompt,**kwargs):
        data = mock_response(prompt,**kwargs)
        value = data['items'][0]
        if mutation=='missing': del value['grades']['uniqueness']
        if mutation=='badtype': value['grades']['uniqueness']=False
        if mutation=='unknown_id': value['id']=2
        if mutation=='duplicate': data['items'].append(value)
        if mutation=='fake_quote': value['quote']='本文には存在しない架空の引用です'
        return data
    monkeypatch.setattr(quality.ollama_client,'generate_json',response)
    if mutation=='fake_quote':
        result = quality.semantic([row],[row],'model')[1]
        assert result['correctness']['verdict']==result['uniqueness']['verdict']=='unknown'
        assert not result['_meta']['quote']
    else:
        with pytest.raises(ValueError): quality.semantic([row],[row],'model')


def test_valid_content_evaluation_is_tied_to_prompt_and_source(monkeypatch):
    row = {'id':1,'digest':'one','snapshot':example()}
    monkeypatch.setattr(quality.ollama_client,'generate_json',mock_response)
    result = quality.semantic([row],[row],'model')[1]
    assert result['correctness']['verdict']=='pass'
    assert result['_meta']['prompt_sha256']==quality.digest(quality.prompt_for([row],[row]))
    row['snapshot']['sources'][0]['text']=''
    result = quality.semantic([row],[row],'model')[1]
    assert result['correctness']['verdict']=='unknown'
    assert result['uniqueness']['verdict']=='unknown'


def test_failed_model_is_unknown_and_stops_after_three_batches(monkeypatch):
    attempts=[]
    def broken(*args):
        attempts.append(1)
        raise RuntimeError('private endpoint details must not leak')
    monkeypatch.setattr(quality,'semantic',broken)
    run = quality.enqueue(start=False)
    quality.execute(run['id'])
    assert len(attempts)==3
    assert quality.get_run(run['id'])['summary']['llm_completed']==0
    assert all(r['result']['grades']['correctness']['verdict']=='unknown' for r in quality.rows(run['id']))
    assert 'private endpoint' not in json.dumps(quality.get_run(run['id']))


def test_sample_is_reproducible_across_exam_origin_and_verdict():
    items=[]
    for index in range(90):
        items.append({'id':index,'snapshot':{'exam':str(index%3),'origins':[str(index%2)]},
                      'result':{'verdict':list(quality.LABELS)[index%3]}})
    a=quality.sample_ids(items)
    assert len(a)==len(set(a))==30
    assert a==quality.sample_ids(items)
    assert {items[i]['snapshot']['exam'] for i in a}=={'0','1','2'}
    assert {items[i]['result']['verdict'] for i in a}==set(quality.LABELS)


def test_csv_round_trip_validation_and_atomic_rejection():
    run = completed()
    records=list(csv.DictReader(io.StringIO(quality.export_csv(run['id']).lstrip('\ufeff'))))
    assert len(records)==30
    assert all(not r['human_verdict'] for r in records)
    records[0].update(human_verdict='fail',reviewer='確認者',notes='出典を確認し指摘')
    assert quality.import_csv(run['id'],csv_text(records))==1
    metrics=quality.human_metrics(quality.decorated_items(run['id']))
    assert metrics['reviewed']==metrics['confirmed']==1
    altered=[dict(r) for r in records]
    altered[1].update(human_verdict='pass',reviewer='確認者',notes='本文と照合')
    altered[2].update(human_verdict='bogus',reviewer='確認者',notes='不正')
    with pytest.raises(ValueError): quality.import_csv(run['id'],csv_text(altered))
    assert quality.human_metrics(quality.decorated_items(run['id']))['reviewed']==1
    altered=[dict(r) for r in records]
    altered[0]['stem']='CSV上で別の問題に書き換え'
    with pytest.raises(ValueError,match='3列'): quality.import_csv(run['id'],csv_text(altered))
    records[0]['digest']='wrong'
    with pytest.raises(ValueError): quality.import_csv(run['id'],csv_text(records))


def test_csv_formula_cells_and_stale_version_are_protected(monkeypatch):
    assert quality.safe_cell(' =SUM(1,2)').startswith("'")
    assert quality.safe_cell('@SUM(1)').startswith("'")
    run=completed()
    records=list(csv.DictReader(io.StringIO(quality.export_csv(run['id']).lstrip('\ufeff'))))
    records[0].update(human_verdict='pass',reviewer='確認者',notes='本文確認')
    real=quality.current_keys
    def edited():
        result=real()
        for q in result.values(): q['explanation']+='変更'
        return result
    monkeypatch.setattr(quality,'current_keys',edited)
    with pytest.raises(ValueError,match='変更'): quality.import_csv(run['id'],csv_text(records))


def test_admin_routes_protect_diagnosis_and_csv(monkeypatch):
    client=TestClient(app)
    assert client.get('/admin/quality',follow_redirects=False).status_code==303
    assert client.get('/admin/quality/1/review.csv',follow_redirects=False).status_code==303
    assert client.post('/api/quality/runs',json={}).status_code==401
    assert client.get('/api/quality/runs/1').status_code==401
    assert client.post('/api/quality/runs/1/reviews',json={'csv_text':''}).status_code==401
    client.cookies.set(ADMIN_COOKIE,settings.admin_token)
    assert client.get('/admin/quality').status_code==200
    run=client.post('/api/quality/runs',json={'use_llm':False}).json()
    assert client.get(f'/admin/quality/{run["id"]}/review.csv').status_code==409
    quality.execute(run['id'])
    assert client.get(f'/admin/quality?run_id={run["id"]}').status_code==200
    response=client.get(f'/admin/quality/{run["id"]}/review.csv')
    assert response.status_code==200
    assert response.headers['cache-control']=='no-store'
    records=list(csv.DictReader(io.StringIO(response.text.lstrip('\ufeff'))))
    records[0].update(human_verdict='pass',reviewer='確認者',notes='確認済み')
    assert client.post(f'/api/quality/runs/{run["id"]}/reviews',json={'csv_text':csv_text(records)}).json()['imported']==1
    assert client.get('/admin/quality?run_id=9999').status_code==404
    assert client.get('/api/quality/runs/9999').status_code==404
