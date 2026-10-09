// Actual workerd Request validation; no external network or credentials.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {Miniflare,convertV4MiniflareOptions} from '/home/ats030/.npm/_npx/32026684e21afda6/node_modules/miniflare/dist/src/index.js';
const script=`import {lookupTaxon} from './gemini-handler.mjs';
export default {async fetch(){
  let calls=0,canceled=false;
  const fetcher=async(url,options)=>{
    const request=new Request(url,options); // workerd rejects redirect:error here, unlike Node.
    if(request.redirect!=='manual') throw Error('Redirect following allowed');
    calls++;
    if(new URL(url).searchParams.get('q')==='Synthetic redirect') return new Response(new ReadableStream({
      cancel(){canceled=true;}}),{status:302,headers:{Location:'https://example.invalid'}});
    return Response.json({results:[{name:'Synthetic success',id:1}]});
  };
  const positive=await lookupTaxon('Synthetic success',fetcher);
  const redirected=await lookupTaxon('Synthetic redirect',fetcher);
  return Response.json({positive,redirected,calls,canceled});
}};`;
const modules=[{type:'ESModule',path:resolve('gemini-runtime-test.mjs'),contents:script}];
for(const name of ['gemini-handler.mjs','gemini-core.mjs','_gemini_policy.mjs'])
  modules.push({type:'ESModule',path:resolve(name),contents:await readFile(name,'utf8')});
const mf=new Miniflare(convertV4MiniflareOptions({workers:[{name:'gemini-runtime-check',compatibilityDate:'2026-10-08',modules}]}));
try{
  const response=await mf.dispatchFetch('http://localhost');
  assert.equal(response.status,200);
  assert.deepEqual(await response.json(),{positive:[{name:'Synthetic success',id:1}],redirected:null,calls:2,canceled:true});
  console.log('PASS: actual workerd taxonomy Request construction, positive response, 302 reject/cancel, no redirect follow or external network');
}finally{await mf.dispose();}
