import copy
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
import vision
import pipeline

EXACT={'usage':{'key':'3DXV3','canonicalName':'Felis catus','rank':'SPECIES','status':'ACCEPTED','type':'SCIENTIFIC'},
       'classification':[{'name':'Mammalia','rank':'CLASS'}],
       'diagnostics':{'matchType':'EXACT','confidence':99},'synonym':False}


def test_gbif_python_js_protocol_and_evidence_parity():
    cases=[(EXACT,'Felis catus'),(EXACT,'felis CATus'),(EXACT,'Felis cattus'),
           ({'diagnostics':{'matchType':'NONE'}},'Felis catus'),({},'Felis catus')]
    for section,key,values in [
        ('usage','key',['../escape',1,'']),('usage','canonicalName',[None,'Felis']),
        ('usage','status',['SYNONYM','DOUBTFUL']),('usage','type',['INFORMAL']),
        ('diagnostics','matchType',['FUZZY','HIGHERRANK','unknown',None,0,[],{}]),
        ('diagnostics','confidence',[94,95,101,'99',True,None]),
        ('diagnostics','issues',[[],['AMBIGUOUS'],{}]),
    ]:
        for value in values:
            data=copy.deepcopy(EXACT);data[section][key]=value;cases.append((data,'Felis catus'))
    for key,values in [('synonym',[True,None,0]),('classification',[None,[]]),('usage',[None]),('diagnostics',[None])]:
        for value in values:
            data=copy.deepcopy(EXACT);data[key]=value;cases.append((data,'Felis catus'))
    rows=[{'data':data,'name':name,'expected':vision._gbif_taxa(name,data)} for data,name in cases]
    taxa=vision._gbif_taxa('Felis catus',EXACT)
    original=vision.normalize({'category':'動物','candidates':[{'common_name_ja':'AIの和名','scientific_name':'Felis catus',
        'confidence':99,'traits':['形','色'],'distinguishing_features':['比較点']}]},model='synthetic',provider='gemini')
    original_lookup=vision._lookup_taxon
    try:
        vision._lookup_taxon=lambda name:taxa
        expected=pipeline.finish(copy.deepcopy(original))
    finally:vision._lookup_taxon=original_lookup
    assert expected['candidates'][0]['confidence']==60
    assert expected['candidates'][0]['common_name_ja']==vision.NO_JAPANESE_NAME
    program="""import assert from 'node:assert/strict';
import {gbifTaxa} from './cloudflare-preview/gemini-handler.mjs';
import {finish} from './cloudflare-preview/gemini-core.mjs';
let raw='';for await(const part of process.stdin)raw+=part;
const data=JSON.parse(raw);
for(const row of data.rows)assert.deepEqual(gbifTaxa(row.name,row.data),row.expected,JSON.stringify(row));
assert.deepEqual(await finish(data.original,async()=>data.taxa),data.expected);
console.log('PASS: strict GBIF Python/JS protocol and evidence parity');"""
    result=subprocess.run(['/home/ats030/.nvm/versions/node/v24.19.0/bin/node','--input-type=module','-e',program],
        cwd=APP,input=json.dumps({'rows':rows,'original':original,'taxa':taxa,'expected':expected}),
        capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr


@pytest.fixture
def gbif(monkeypatch):
    monkeypatch.setattr(vision,'GBIF_FALLBACK',True)
    monkeypatch.setattr(vision,'_GBIF_CACHE',{})
    monkeypatch.setattr(vision,'_GBIF_RETRY_AT',0)
    monkeypatch.setattr(vision,'_LAST_GBIF_REQUEST',-10000)
    monkeypatch.setattr(vision,'_lookup_inaturalist',lambda name: (_ for _ in ()).throw(vision.TaxonomyUnavailable(429)))
    return monkeypatch


def test_gbif_recovers_after_primary429_and_uses_names_only(gbif):
    calls=[]
    @contextmanager
    def stream(method,url,**kwargs):
        calls.append((method,url,kwargs))
        yield httpx.Response(200,json=EXACT,request=httpx.Request(method,url))
    gbif.setattr(vision.httpx,'stream',stream)
    first=vision._lookup_taxon('Felis catus')
    assert first[0]['source']=='gbif'
    assert vision._lookup_taxon('Felis catus')==first
    assert len(calls)==1
    method,url,options=calls[0]
    assert method=='GET' and url==vision.GBIF_MATCH_URL
    assert options['params']=={'scientificName':'Felis catus','checklistKey':vision.GBIF_CHECKLIST}
    assert options['headers']=={'User-Agent':vision.INATURALIST_USER_AGENT}
    assert options['follow_redirects'] is False and options['timeout']==5


def test_valid_primary_no_match_does_not_call_fallback(gbif):
    gbif.setattr(vision,'_lookup_inaturalist',lambda name:[])
    gbif.setattr(vision.httpx,'stream',lambda *a,**k:pytest.fail('Fallback after valid no-match'))
    assert vision._lookup_taxon('Synthetic invalid')==[]


def test_disabled_fallback_preserves_quota_error(gbif):
    gbif.setattr(vision,'GBIF_FALLBACK',False)
    gbif.setattr(vision.httpx,'stream',lambda *a,**k:pytest.fail('Disabled fallback called'))
    with pytest.raises(vision.TaxonomyUnavailable) as caught:vision._lookup_taxon('Felis catus')
    assert caught.value.status==429


@pytest.mark.parametrize('status,body',[(503,b'failure'),(302,b'redirect'),(200,b'{bad'),(200,b'{}'),(200,b'x'*(256*1024+1))])
def test_fallback_failure_is_not_cached_as_no_match(gbif,status,body):
    @contextmanager
    def stream(method,url,**kwargs):yield httpx.Response(status,content=body,request=httpx.Request(method,url))
    gbif.setattr(vision.httpx,'stream',stream)
    with pytest.raises(vision.TaxonomyUnavailable) as caught:vision._lookup_taxon('Felis catus')
    assert caught.value.status==503 and not vision._GBIF_CACHE


def test_fallback429_honors_cooldown_and_stops(gbif):
    calls=[]
    @contextmanager
    def stream(method,url,**kwargs):
        calls.append(url)
        yield httpx.Response(429,headers={'Retry-After':'120'},request=httpx.Request(method,url))
    gbif.setattr(vision.httpx,'stream',stream)
    for name in ['Felis catus','Panthera leo']:
        with pytest.raises(vision.TaxonomyUnavailable) as caught:vision._lookup_taxon(name)
        assert caught.value.status==429 and 119<=caught.value.retry_after<=120
    assert len(calls)==1 and not vision._GBIF_CACHE
