import copy
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
import config_store
import pipeline
import prepared_photos
import protected_species
import vision


def test_generated_js_gemini_rules_match_authoritative_python(monkeypatch):
    spec=importlib.util.spec_from_file_location('gemini_policy',APP/'cloudflare-preview/gemini-policy.py')
    policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy);policy.build()
    model=config_store.MODELS['gemini'][0]['id']
    basic={'metadata':{},'measured':{'width':600,'height':450,'pixels':270000,'brightness':120,'sharpness':200,'contrast':30}}
    reports=[]
    def add(value,count=None):
        count=len(value) if count is None else count
        row={'reports':value,'count':count}
        try:
            metadata,quality=prepared_photos.read_reports(json.dumps(value),count)
            row['expected']={'metadata':metadata,'quality':quality}
        except vision.VisionError:
            row['error']=True
        reports.append(row)
    add([basic]);add([basic,basic,basic]);add([]);add([basic]*4)
    for key,values in [('width',[0,199,200,299,300,16384,16385,True]),
                       ('brightness',[-1,0,14.9,15,24.9,25,255,256,False]),
                       ('sharpness',[-1,0,49.9,50,1040400,1040401]),('contrast',[-1,0,9.9,10,128,129])]:
        for value in values:
            report=copy.deepcopy(basic);report['measured'][key]=value
            report['measured']['pixels']=report['measured']['width']*report['measured']['height']
            add([report])
    for latitude in [0,90,-90,90.1,0.00005,-0.00005,1.03125,-1.03125,45.67895]:
        report=copy.deepcopy(basic);report['metadata']={'latitude':latitude,'longitude':139.1234567};add([report])
    rng=random.Random(42030)
    for _ in range(100):
        report=copy.deepcopy(basic);report['metadata']={'latitude':rng.uniform(-90,90),'longitude':rng.uniform(-180,180)};add([report])
    templates=[]
    for location in ['', '山麓\n 東京都', '\ufeff山\x85林\x1c道', '🌳'*150]:
        for chosen in config_store.MODELS['gemini']:
            body={'model':chosen['id'],'count':1,'location':location,'observed_date':'2026-10-09','size':' 約 5cm '}
            templates.append({'body':body,'reports':[basic], 'expected':vision.provider_payload('gemini',chosen['id'],[],
                location=location,observed_date=body['observed_date'],size=body['size'])})
    species=json.loads((APP/'data/protected_species.json').read_text())['species'][0]['scientific_name']
    results=[]
    for name in ['Unknown name','Taxon one',species]:
        for category in ['植物','動物','菌類','不明','invalid']:
            for evidence in ['enough','few','contradiction']:
                taxa={name:[{'id':123,'name':name,'preferred_common_name':'照合済みの和名','rank':'species','iconic_taxon_name':'Plantae'}]} if name!='Unknown name' else {}
                data={'category':category,'summary':'観察','candidates':[{'common_name_ja':' 候補 ','scientific_name':name,
                    'confidence':95,'traits':['特徴1','特徴2'] if evidence!='few' else ['特徴1'],
                    'distinguishing_features':['決め手'] if evidence!='few' else [],
                    'contradictions':['矛盾'] if evidence=='contradiction' else [],'sex':'オス','sex_evidence':['根拠']} ]}
                monkeypatch.setattr(vision,'_lookup_taxon',lambda query,table=taxa: table.get(query,[]))
                normalized=vision.normalize(data,model=model,provider='gemini')
                expected=pipeline.finish(copy.deepcopy(normalized))
                full={**expected,'photo_metadata':{},'photo_notes':[]}
                results.append({'data':data,'model':model,'taxa':taxa,'normalized':normalized,'expected':expected,'full':full,'reports':[basic]})
    for taxa in ({'Taxon one':[]},{'Taxon one':[{'name':'TAXON ONE','preferred_common_name':'English','id':0}]}):
        data={'category':'動物','candidates':[{'common_name_ja':'候補','scientific_name':'Taxon one','confidence':'100','traits':['a','b'],'distinguishing_features':['c']}]}
        monkeypatch.setattr(vision,'_lookup_taxon',lambda query,table=taxa: table.get(query,[]))
        normalized=vision.normalize(data,model=model,provider='gemini');expected=pipeline.finish(copy.deepcopy(normalized))
        results.append({'data':data,'model':model,'taxa':taxa,'normalized':normalized,'expected':expected,
            'full':{**expected,'photo_metadata':{},'photo_notes':[]},'reports':[basic]})
    result=subprocess.run(['/home/ats030/.nvm/versions/node/v24.19.0/bin/node','tests/check_gemini_core.mjs'],cwd=APP,
        input=json.dumps({'reports':reports,'templates':templates,'results':results}),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert 'Python/JS reports' in result.stdout
