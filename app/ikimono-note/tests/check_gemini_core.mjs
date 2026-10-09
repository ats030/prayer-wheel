import assert from 'node:assert/strict';
import {readReports,context,providerTemplate,normalize,finish,result} from '../cloudflare-preview/gemini-core.mjs';
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
}
console.log(`PASS: Python/JS reports ${cases.reports.length}, templates ${cases.templates.length}, normalize/evidence/protected-species ${cases.results.length}`);
await assert.rejects(finish(normalize({category:'動物',candidates:[{common_name_ja:'候補',scientific_name:'Synthetic taxon'}]},'synthetic'),async()=>null),
  error=>error.status===503&&error.detail.includes('分類サービスに接続できず'));
