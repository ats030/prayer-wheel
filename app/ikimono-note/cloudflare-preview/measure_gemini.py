"""Actual JS auth/quality/template/result CPU; synthetic reply, no AI/photos."""
import argparse
import copy
import base64
import hashlib
import hmac
import json
from itertools import product
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import config_store
import main
from measure_cpu import measure

PATHS=('/api/gemini/prepare','/api/gemini/result')


def taxonomy_references(reply, model, metadata, quality, names):
    """Accept only Python outputs grounded in both live taxonomy sources."""
    choices=[]
    for name in names:
        alternatives=[]
        for lookup in (main.vision._lookup_inaturalist,main.vision._lookup_gbif):
            try: taxa=lookup(name)
            except main.vision.TaxonomyUnavailable: continue
            if taxa and any(str(t.get('name') or '').casefold()==name.casefold() for t in taxa):
                alternatives.append(taxa)
        assert alternatives,'Taxonomy reference unavailable'
        choices.append(alternatives)
    references=[]
    for selected in product(*choices):
        by_name=dict(zip(names,selected))
        with patch.object(main.vision,'_lookup_taxon',side_effect=lambda name:copy.deepcopy(by_name[name])):
            result=main._finish_gemini(reply,model,metadata,quality)
        assert len(result['candidates'])==len(names),'Python taxonomy reference rejected candidates'
        references.append(result)
    return references


def sized_reply(reply, target_bytes=0):
    """Stress the accepted reply bound without altering identification content."""
    data=copy.deepcopy(reply)
    if target_bytes:
        data['probe_padding']=''
        size=len(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode())
        if target_bytes<size or target_bytes>2*1024*1024:
            raise ValueError('Reply size must fit the existing 2MiB bound')
        data['probe_padding']='x'*(target_bytes-size)
    return data


def collect(samples,output,case="empty",reply_bytes=0,compact_reply=False):
    state=json.loads((Path.home()/'.local/state/ikimono-cloudflare-preview/secrets.json').read_text())
    encode=lambda value:base64.urlsafe_b64encode(value).decode().rstrip('=')
    session=encode(json.dumps({'sub':'synthetic-gemini-cpu','email':'synthetic@example.invalid','exp':int(time.time())+300}).encode())
    cookie=session+'.'+encode(hmac.new(state['IKIMONO_SESSION_SECRET'].encode(),session.encode(),hashlib.sha256).digest())
    reports=[{'metadata':{'observed_date':'2026-10-09','latitude':35,'longitude':139},
              'measured':{'width':600,'height':450,'pixels':270000,'brightness':120,'sharpness':200,'contrast':30}}]*3
    body={'model':config_store.MODELS['gemini'][0]['id'],'count':3,
          'client_photos':json.dumps(reports,ensure_ascii=False,separators=(',',':'))}
    prepare={**body,'location':'合成の山麓','observed_date':'2026-10-09','size':'約5cm'}
    identified={'category':'不明','summary':'観察','candidates':[]}
    if case=='taxonomy':
        identified={'category':'動物','summary':'合成の分類照合テスト','candidates':[
            {'common_name_ja':'合成候補','scientific_name':name,'confidence':90,
             'traits':['形の観察','模様の観察'],'distinguishing_features':['合成の比較項目'],
             'contradictions':[],'sex':'判別不能','sex_evidence':[],'uncertainty':''}
            for name in ['Felis catus','Panthera tigris','Panthera leo']]}
    reply={'candidates':[{'content':{'parts':[{'text':json.dumps(identified,ensure_ascii=False,separators=(',',':'))}]}}]}
    reply=sized_reply(reply,reply_bytes)
    serialized=json.dumps(reply,ensure_ascii=False,separators=(',',':'))
    original_reply_bytes=len(serialized.encode())
    if compact_reply:
        projected=subprocess.run(['/home/ats030/.nvm/versions/node/v24.19.0/bin/node','--input-type=module','-e',
            'import {compactGeminiReply} from "./static/assets/gemini-browser.mjs";'
            'let s="";for await(const c of process.stdin)s+=c;'
            'process.stdout.write(JSON.stringify(compactGeminiReply(JSON.parse(s))));'],
            cwd=HERE.parent,input=serialized,text=True,capture_output=True,check=True)
        serialized=projected.stdout
    result_body={**body,'reply':serialized}
    metadata,quality=main.prepared_photos.read_reports(body['client_photos'],3)
    expected={PATHS[0]:main.vision.provider_payload('gemini',body['model'],[],location=prepare['location'],
                     observed_date=prepare['observed_date'],size=prepare['size']),
              PATHS[1]:None}
    results=taxonomy_references(reply,body['model'],metadata,quality,
        [c['scientific_name'] for c in identified['candidates']]) if case=='taxonomy' else [
            main._finish_gemini(reply,body['model'],metadata,quality)]
    expected[PATHS[1]]=results[0]
    expected={path:[value] for path,value in expected.items()}
    expected[PATHS[1]]=results
    # JS and Python differ in spelling integer-valued floats (35 vs35.0).
    # Canonicalize expected bytes with JS outside the measured Worker.
    canonical=subprocess.run(['/home/ats030/.nvm/versions/node/v24.19.0/bin/node','--input-type=module','-e',
        'import {createHash} from "node:crypto";let s="";for await(const c of process.stdin)s+=c;'
        'const out={};for(const [k,v] of Object.entries(JSON.parse(s)))'
        'out[k]=v.map(x=>createHash("sha256").update(JSON.stringify(x)).digest("hex"));'
        'process.stdout.write(JSON.stringify(out));'],
        input=json.dumps(expected,ensure_ascii=False),text=True,capture_output=True,check=True)
    hashes=json.loads(canonical.stdout)
    manifest=json.loads((HERE/'edge-manifest.json').read_text())
    def request_factory(path):
        if path=='/health':return {}
        data=prepare if path==PATHS[0] else result_body
        return {'method':'POST','data':json.dumps(data,ensure_ascii=False,separators=(',',':')).encode(),
                'headers':{'Content-Type':'application/json','Cookie':'ikimono_session='+cookie}}
    evidence=measure(samples,paths=PATHS,request_factory=request_factory,wrangler_config=HERE/'front.jsonc')
    output.write_text(json.dumps({**evidence,'eligible_for_success_cpu_comparison':False,
        'provenance_verified':False},indent=2)+'\n')
    assert evidence['complete'] and evidence['eligible_for_success_cpu_comparison'],'Incomplete CPU evidence'
    for row in [evidence['subscription_probe'],*evidence['records']]:
        assert row['preview_bundle_sha256']==manifest['bundle_sha256'],'Stale gateway'
        if row['path'] in hashes:
            assert row['preview_gemini_engine']=='javascript','Python fallback was measured'
            assert row['sha256'] in hashes[row['path']],'Python result/template parity changed'
        else:
            assert row['preview_backend_bundle_sha256']==manifest['python_bundle_sha256'],'Stale private backend'
    evidence['scope']='Synthetic signed-in JS context for3 photos: auth/reports/quality/template and '+('3candidate result with real taxonomy HTTP/cache' if case=='taxonomy' else 'empty-candidate result')+'/metadata; no photo upload, AI, Drive or memory guarantee'
    evidence['provenance_verified']=True
    evidence['case']=case
    evidence['synthetic_reply_bytes']=len(result_body['reply'].encode())
    evidence['original_synthetic_reply_bytes']=original_reply_bytes
    evidence['browser_reply_compacted']=compact_reply
    evidence['synthetic_reply_padding']=bool(reply_bytes)
    evidence['taxonomy_reference_verified_candidates']=len(results[0]['candidates'])
    evidence['taxonomy_reference_response_hashes']=hashes[PATHS[1]]
    evidence['network_ai_calls']=0
    evidence['gateway_bundle_sha256']=manifest['bundle_sha256']
    evidence['python_bundle_sha256']=manifest['python_bundle_sha256']
    output.write_text(json.dumps(evidence,indent=2)+'\n')
    for path in PATHS:
        print(path,[(row['cpu_ms'],row['isolate_invocation']) for row in evidence['records'] if row['path']==path])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,choices=range(1,6),default=5)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',choices=('empty','taxonomy'),default='empty')
    parser.add_argument('--reply-bytes',type=int,default=0,help='Synthetic reply size, at most existing2MiB limit; no extra AI calls')
    parser.add_argument('--compact-reply',action='store_true',help='Use actual browser projection; reference still uses full original reply')
    args=parser.parse_args()
    args.output.unlink(missing_ok=True)
    try:collect(args.samples,args.output,args.case,args.reply_bytes,args.compact_reply)
    except (AssertionError,ValueError,RuntimeError,OSError,subprocess.CalledProcessError,json.JSONDecodeError) as error:
        diagnostic=json.loads(args.output.read_text()) if args.output.exists() else {'records':[]}
        diagnostic.update({'eligible_for_success_cpu_comparison':False,'failure_type':type(error).__name__})
        if isinstance(error,(AssertionError,RuntimeError)):
            diagnostic['failure_reason']=str(error)[:200] # Only fixed local assertion/subscription messages.
        args.output.write_text(json.dumps(diagnostic,indent=2)+'\n')
        print('FAIL: CPU evidence incomplete or mismatched; reduced diagnostic retained');raise SystemExit(2)
