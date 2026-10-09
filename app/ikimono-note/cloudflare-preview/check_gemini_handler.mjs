import assert from 'node:assert/strict';
import {handleGemini,lookupTaxon} from './gemini-handler.mjs';
import policy from './_gemini_policy.mjs';
const reports=JSON.stringify([{metadata:{},measured:{width:600,height:450,pixels:270000,brightness:120,sharpness:200,contrast:30}}]);
const body=JSON.stringify({model:policy.models[0],count:1,client_photos:reports});
const request=(payload,client='192.0.2.51',length)=>new Request('https://ikimono-note-preview.ats030.workers.dev/api/gemini/prepare',{
  method:'POST',body:payload,duplex:'half',headers:{'Content-Type':'application/json','CF-Connecting-IP':client,...(length===undefined?{}:{'Content-Length':length})}});
const runtime={IKIMONO_GEMINI_MAX_OUTPUT_TOKENS:'16_384',IKIMONO_GEMINI_THINKING_LEVEL:'low'};
const configured=await handleGemini(request(body),'/api/gemini/prepare',undefined,runtime);
assert.equal(configured.status,200);const payload=await configured.json();
assert.equal(payload.generationConfig.maxOutputTokens,16384);assert.equal(payload.generationConfig.thinkingConfig.thinkingLevel,'low');
for(const value of ['', '1e3', '3__2','not-number']) assert.equal((await handleGemini(request(body,'192.0.2.52'),
  '/api/gemini/prepare',undefined,{IKIMONO_GEMINI_MAX_OUTPUT_TOKENS:value})).status,503);
let oversizedCanceled=false;
const oversized=new ReadableStream({start(controller){controller.enqueue(new Uint8Array(256*1024+1));},cancel(){oversizedCanceled=true;}});
assert.equal((await handleGemini(request(oversized,'192.0.2.53'),'/api/gemini/prepare')).status,400);
assert.ok(oversizedCanceled);
const originalTimer=globalThis.setTimeout, deadlines=[];
globalThis.setTimeout=(fn,ms,...args)=>{deadlines.push(ms);return originalTimer(fn,Math.min(ms,30),...args);};
try {
  let stalledCanceled=false;
  const stalled=new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(body));},cancel(){stalledCanceled=true;}});
  assert.equal((await handleGemini(request(stalled,'192.0.2.54'),'/api/gemini/prepare')).status,408);
  assert.ok(stalledCanceled);assert.ok(deadlines.includes(15000));
  let releaseFetch, calls=0;
  const fetcher=async(url,options)=>{
    calls++;assert.equal(new URL(url).origin,'https://api.inaturalist.org');
    assert.deepEqual(Object.keys(options.headers),['User-Agent']);assert.equal(options.redirect,'manual');
    if(calls===1) await new Promise(resolve=>{releaseFetch=resolve;});
    return Response.json({results:[]});
  };
  const first=lookupTaxon('Synthetic first',fetcher);
  const waiting=Array.from({length:8},(_,index)=>lookupTaxon('Synthetic queued '+index,fetcher));
  const completed=Promise.allSettled(waiting);
  await assert.rejects(lookupTaxon('Synthetic overflow',fetcher),error=>error.status===429);
  while(!releaseFetch)await new Promise(resolve=>originalTimer(resolve,1));
  releaseFetch();await first;
  const rows=await completed;
  assert.ok(rows.every(row=>row.status==='fulfilled'||row.reason.status===429));
  assert.ok(rows.some(row=>row.status==='rejected'),'Queue timeout did not stop waiting work');
  assert.deepEqual(await lookupTaxon('Synthetic first',async()=>assert.fail('Cache miss')),[]);
} finally {globalThis.setTimeout=originalTimer;}
console.log('PASS: runtime generation overrides, chunked byte bounds, stalled-body cancel/deadline, bounded taxonomy queue/wait and names-only HTTP');

let quotaCalls=0,quotaCanceled=false;
await assert.rejects(lookupTaxon('Synthetic quota',async()=>{
  quotaCalls++;
  return new Response(new ReadableStream({cancel(){quotaCanceled=true;}}),{status:429,headers:{'Retry-After':'120'}});
}),error=>error.status===429&&error.retryAfter===120);
await assert.rejects(lookupTaxon('Synthetic next',async()=>{quotaCalls++;assert.fail('Retried taxonomy after429');}),error=>error.status===429);
assert.equal(quotaCalls,1);assert.ok(quotaCanceled);
const {InputError}=await import('./gemini-core.mjs');
const quotaError=new InputError('Synthetic limit',429);quotaError.retryAfter=120;
const output=await handleGemini(request(JSON.stringify({...JSON.parse(body),reply:JSON.stringify({candidates:[{content:{parts:[{
  text:JSON.stringify({category:'動物',candidates:[{common_name_ja:'合成候補',scientific_name:'Synthetic taxon'}]})}]}}]})}),
  '192.0.2.55'),'/api/gemini/result',()=>{throw quotaError;});
assert.equal(output.status,429);assert.equal(output.headers.get('Retry-After'),'120');
console.log('PASS: taxonomy429 stops further HTTP, cancels body, bounded isolate cooldown, explicit result429/Retry-After');
