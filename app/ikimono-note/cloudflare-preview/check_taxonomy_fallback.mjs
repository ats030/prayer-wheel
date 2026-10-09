import assert from 'node:assert/strict';
import {lookupTaxon,handleGemini} from './gemini-handler.mjs';
const exact={usage:{key:'3DXV3',canonicalName:'Felis catus',rank:'SPECIES',status:'ACCEPTED',type:'SCIENTIFIC'},
  classification:[{name:'Mammalia',rank:'CLASS'}],diagnostics:{matchType:'EXACT',confidence:99},synonym:false};
const calls=[];let canceled=0;
const fetcher=async(url,options)=>{
  const request=new Request(url,options);assert.equal(request.redirect,'manual');
  assert.deepEqual(Object.keys(options.headers),['User-Agent']);
  const parsed=new URL(url);calls.push(parsed.origin);
  if(parsed.origin==='https://api.inaturalist.org')return new Response(null,{status:429,headers:{'Retry-After':'120'}});
  assert.equal(parsed.origin,'https://api.gbif.org');assert.equal(parsed.pathname,'/v2/species/match');
  assert.equal(parsed.searchParams.get('checklistKey'),'7ddf754f-d193-4cc9-b351-99906754a03b');
  assert.deepEqual([...parsed.searchParams.keys()],['scientificName','checklistKey']);
  const name=parsed.searchParams.get('scientificName');
  if(name==='Synthetic fuzzy')return Response.json({...exact,diagnostics:{matchType:'FUZZY',confidence:99}});
  if(name==='Synthetic malformed')return Response.json({});
  if(name==='Synthetic redirect')return new Response(new ReadableStream({cancel(){canceled++;}}),{status:302,headers:{Location:'https://example.invalid'}});
  if(name==='Synthetic oversized')return new Response(new ReadableStream({start(controller){controller.enqueue(new Uint8Array(256*1024+1));},cancel(){canceled++;}}));
  if(name==='Synthetic quota')return new Response(new ReadableStream({cancel(){canceled++;}}),{status:429,headers:{'Retry-After':'120'}});
  return Response.json(exact);
};
const recovered=await lookupTaxon('Felis catus',fetcher,true);
assert.equal(recovered[0].source,'gbif');assert.equal(recovered[0].name,'Felis catus');
assert.deepEqual(calls,['https://api.inaturalist.org','https://api.gbif.org']);
assert.deepEqual(await lookupTaxon('Felis catus',fetcher,true),recovered);assert.equal(calls.length,2);
await assert.rejects(lookupTaxon('Synthetic disabled',fetcher),error=>error.status===429);assert.equal(calls.length,2);
assert.deepEqual(await lookupTaxon('Synthetic fuzzy',fetcher,true),[]);
for(const name of ['Synthetic malformed','Synthetic redirect','Synthetic oversized'])
  await assert.rejects(lookupTaxon(name,fetcher,true),error=>error.status===503);
const body={model:'gemini-3.5-flash-lite',count:1,client_photos:JSON.stringify([{metadata:{},
  measured:{width:600,height:450,pixels:270000,brightness:120,sharpness:200,contrast:30}}]),
  reply:JSON.stringify({candidates:[{content:{parts:[{text:JSON.stringify({category:'動物',candidates:[{
    common_name_ja:'AIの和名',scientific_name:'Felis catus',confidence:99,traits:['形','色'],distinguishing_features:['比較点']} ]})}]}}]})};
const originalFetch=globalThis.fetch;globalThis.fetch=fetcher;
try{
  const response=await handleGemini(new Request('https://preview.invalid/api/gemini/result',{method:'POST',
    headers:{'Content-Type':'application/json','CF-Connecting-IP':'192.0.2.170'},body:JSON.stringify(body)}),
    '/api/gemini/result',undefined,{IKIMONO_GBIF_FALLBACK:'1'});
  assert.equal(response.status,200);const data=await response.json();
  assert.equal(data.candidates[0].taxonomy_source,'gbif');assert.equal(data.candidates[0].confidence,60);
  assert.equal(data.candidates[0].common_name_ja,'日本語名なし');
  assert.equal(data.candidates[0].taxonomy_url,'https://www.catalogueoflife.org/data/taxon/3DXV3');
}finally{globalThis.fetch=originalFetch;}
await assert.rejects(lookupTaxon('Synthetic quota',fetcher,true),error=>error.status===429&&error.retryAfter===120);
const before=calls.length;
await assert.rejects(lookupTaxon('Synthetic afterquota',fetcher,true),error=>error.status===429);
assert.equal(calls.length,before);assert.equal(canceled,3);
console.log('PASS: primary429 recovery, flagOFF, source/name-only fixed API, cache, strict fuzzy rejection, redirect/body bounds, native result provenance/confidence, fallback429 cooldown; no external HTTP');
