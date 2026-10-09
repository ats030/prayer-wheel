import assert from 'node:assert/strict';
import {readReports,context,providerTemplate,normalize,finish,result} from '../cloudflare-preview/gemini-core.mjs';
import {compactGeminiReply} from '../static/assets/gemini-browser.mjs';
let input='';for await(const chunk of process.stdin)input+=chunk;
const cases=JSON.parse(input);
for(const row of cases.reports) {
  const serialized=JSON.stringify(row.reports);
  if(row.error) assert.throws(()=>readReports(serialized,row.count));
  else assert.deepEqual(readReports(serialized,row.count),row.expected);
}
for(const row of cases.templates) {
  const body={...row.body,client_photos:JSON.stringify(row.reports)};
  assert.deepEqual(providerTemplate(body,context(body)),row.expected);
}
for(const row of cases.results) {
  const lookup=async name=>Object.hasOwn(row.taxa,name)?row.taxa[name]:[];
  const normalized=normalize(row.data,row.model);
  assert.deepEqual(normalized,row.normalized);
  assert.deepEqual(await finish(normalized,lookup),row.expected);
  const body={model:row.model,count:row.reports.length,client_photos:JSON.stringify(row.reports),
    reply:JSON.stringify({candidates:[{content:{parts:[{text:JSON.stringify(row.data)}]}}]})};
  assert.deepEqual(await result(body,context(body),lookup),row.full);
  const original=JSON.parse(body.reply);
  original.usageMetadata={discard:'x'.repeat(131072)};
  original.candidates[0].content.parts[0].thoughtSignature='discard';
  const compact={...body,reply:JSON.stringify(compactGeminiReply(original))};
  assert.deepEqual(await result(compact,context(compact),lookup),row.full);
}
const first=cases.results[0],capture=context({model:first.model,count:first.reports.length,client_photos:JSON.stringify(first.reports)});
for(const reply of [{candidates:[]},{candidates:[{finishReason:'MAX_TOKENS'}]},
  {candidates:[{finishReason:'STOP',content:{parts:[]}}]},
  {candidates:[{content:{parts:[{text:'not-json'}]}}]}]) {
  const invoke=async value=>{try{return await result({model:first.model,reply:JSON.stringify(value)},capture,async()=>[]);}
    catch(error){return {status:error.status,detail:error.detail};}};
  assert.deepEqual(await invoke(compactGeminiReply(reply)),await invoke(reply));
}
console.log(`PASS: Python/JS reports ${cases.reports.length}, templates ${cases.templates.length}, normalize/evidence/protected-species ${cases.results.length}`);
await assert.rejects(finish(normalize({category:'動物',candidates:[{common_name_ja:'候補',scientific_name:'Synthetic taxon'}]},'synthetic'),async()=>null),
  error=>error.status===503&&error.detail.includes('分類サービスに接続できず'));
