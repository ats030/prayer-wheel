"""Actual JS auth/quality/template/result CPU; synthetic reply, no AI/photos."""
import argparse
import base64
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import config_store
import main
from measure_cpu import measure

PATHS=('/health','/api/gemini/prepare','/api/gemini/result')


def collect(samples,output):
    state=json.loads((Path.home()/'.local/state/ikimono-cloudflare-preview/secrets.json').read_text())
    encode=lambda value:base64.urlsafe_b64encode(value).decode().rstrip('=')
    session=encode(json.dumps({'sub':'synthetic-gemini-cpu','email':'synthetic@example.invalid','exp':int(time.time())+300}).encode())
    cookie=session+'.'+encode(hmac.new(state['IKIMONO_SESSION_SECRET'].encode(),session.encode(),hashlib.sha256).digest())
    reports=[{'metadata':{'observed_date':'2026-10-09','latitude':35,'longitude':139},
              'measured':{'width':600,'height':450,'pixels':270000,'brightness':120,'sharpness':200,'contrast':30}}]*3
    body={'model':config_store.MODELS['gemini'][0]['id'],'count':3,
          'client_photos':json.dumps(reports,ensure_ascii=False,separators=(',',':'))}
    prepare={**body,'location':'合成の山麓','observed_date':'2026-10-09','size':'約5cm'}
    reply={'candidates':[{'content':{'parts':[{'text':'{"category":"不明","summary":"観察","candidates":[]}'}]}}]}
    result_body={**body,'reply':json.dumps(reply,ensure_ascii=False,separators=(',',':'))}
    metadata,quality=main.prepared_photos.read_reports(body['client_photos'],3)
    expected={PATHS[1]:main.vision.provider_payload('gemini',body['model'],[],location=prepare['location'],
                     observed_date=prepare['observed_date'],size=prepare['size']),
              PATHS[2]:main._finish_gemini(reply,body['model'],metadata,quality)}
    # JS and Python differ in spelling integer-valued floats (35 vs35.0).
    # Canonicalize expected bytes with JS outside the measured Worker.
    canonical=subprocess.run(['/home/ats030/.nvm/versions/node/v24.19.0/bin/node','--input-type=module','-e',
        'import {createHash} from "node:crypto";let s="";for await(const c of process.stdin)s+=c;'
        'const out={};for(const [k,v] of Object.entries(JSON.parse(s)))'
        'out[k]=createHash("sha256").update(JSON.stringify(v)).digest("hex");'
        'process.stdout.write(JSON.stringify(out));'],
        input=json.dumps(expected,ensure_ascii=False),text=True,capture_output=True,check=True)
    hashes=json.loads(canonical.stdout)
    manifest=json.loads((HERE/'edge-manifest.json').read_text())
    def request_factory(path):
        if path==PATHS[0]:return {}
        data=prepare if path==PATHS[1] else result_body
        return {'method':'POST','data':json.dumps(data,ensure_ascii=False,separators=(',',':')).encode(),
                'headers':{'Content-Type':'application/json','Cookie':'ikimono_session='+cookie}}
    evidence=measure(samples,paths=PATHS,request_factory=request_factory,wrangler_config=HERE/'front.jsonc')
    assert evidence['complete'] and evidence['eligible_for_success_cpu_comparison'],'Incomplete CPU evidence'
    for row in [evidence['subscription_probe'],*evidence['records']]:
        assert row['preview_bundle_sha256']==manifest['bundle_sha256'],'Stale gateway'
        if row['path'] in hashes:
            assert row['preview_gemini_engine']=='javascript','Python fallback was measured'
            assert row['sha256']==hashes[row['path']],'Python result/template parity changed'
        else:
            assert row['preview_backend_bundle_sha256']==manifest['python_bundle_sha256'],'Stale private backend'
    evidence['scope']='Synthetic signed-in JS context for3 photos: auth/reports/quality/template and empty-candidate result/metadata; no photo upload, AI, taxonomy HTTP, Drive or memory/cold guarantee'
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
    args=parser.parse_args()
    try:collect(args.samples,args.output)
    except (AssertionError,RuntimeError,OSError,subprocess.CalledProcessError,json.JSONDecodeError) as error:
        args.output.write_text(json.dumps({'complete':False,'eligible_for_success_cpu_comparison':False,'failure_type':type(error).__name__})+'\n')
        print('FAIL: CPU evidence incomplete or mismatched');raise SystemExit(2)
