// Local V8 sampling only. This is NOT Cloudflare production CPU accounting.
// Reuses the installed inspector client; all inputs and sessions are synthetic.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {createHmac,createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const origin='http://127.0.0.1:8793';
const {ws:WebSocket}=createRequire(import.meta.url)('../../dekita/node_modules/playwright-core/lib/utilsBundle.js');
const health=await fetch(origin+'/health');
assert.equal(health.headers.get('X-Probe-Synthetic-AI'),'1','Local synthetic probe required');
assert.equal(health.headers.get('X-Probe-Profile-IO'),'1','Explicit local I/O profiling required');
const digest=execFileSync('python3',['-c','import json; from build import bundle_digest,HERE; print(bundle_digest(json.loads((HERE/"manifest.json").read_text())))'],{cwd:new URL('.',import.meta.url),encoding:'utf8'}).trim();
assert.equal(health.headers.get('X-Probe-Bundle-SHA256'),digest,'Stale running bundle');
const targets=await fetch('http://127.0.0.1:9229/json').then(r=>r.json());
assert.equal(targets.length,1,'Run only this local Worker');
const socket=new WebSocket(targets[0].webSocketDebuggerUrl,{origin:'http://localhost:9229'});
await new Promise((resolve,reject)=>{socket.once('open',resolve);socket.once('error',reject)});
let serial=0;
const pending=new Map();
socket.on('message',raw=>{
  const message=JSON.parse(raw),waiter=pending.get(message.id);
  if(!waiter)return;
  pending.delete(message.id);clearTimeout(waiter.timer);
  message.error?waiter.reject(new Error(JSON.stringify(message.error))):waiter.resolve(message.result);
});
function command(method,params={}){
  const id=++serial;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error(`Inspector timeout: ${method}`))},20000);
    pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));
  });
}
function summarize(profile){
  const names=new Map(profile.nodes.map(node=>[node.id,node.callFrame.functionName]));
  let active=0,idle=0;
  for(let index=0;index<(profile.samples??[]).length;index++){
    const name=names.get(profile.samples[index]),delta=profile.timeDeltas[index]/1000;
    if(name==='(idle)'||name==='(root)')idle+=delta;else active+=delta;
  }
  return {active_sampled_ms:Number(active.toFixed(3)),idle_sampled_ms:Number(idle.toFixed(3)),samples:profile.samples.length};
}
let clientId=0;
const request=(path,options={})=>fetch(origin+path,{...options,headers:{'X-Forwarded-For':`192.0.2.${++clientId}`,...options.headers}});
const jpeg=await readFile(new URL('./profile-fixtures/noise.jpg',import.meta.url));
const expectedHash=createHash('sha256').update(jpeg).digest('hex');
const measured={width:1600,height:1600,pixels:2560000,brightness:128,sharpness:200,contrast:60};
const payload=Buffer.from(JSON.stringify({sub:'synthetic-profile',email:'synthetic@example.invalid',exp:Math.floor(Date.now()/1000)+300})).toString('base64url');
const signature=createHmac('sha256','synthetic-local-app-probe-never-deploy').update(payload).digest('base64url');
const cookie=`ikimono_session=${payload}.${signature}`;
const cases=[
  ['native-health',()=>request('/probe/profile/native-health')],
  ['health',()=>request('/health')],
  ['settings',()=>request('/api/settings')],
  ['html',()=>request('/')],
  ['heic-decoder-asset',()=>request('/vendor/photo/libheif.mjs')],
];
for(const count of [1,3])for(const parser of ['identify','native-upload','native-identify','native-gemini-payload','native-gemini-payload-js'])cases.push([`${parser}-${count}x-${jpeg.length}-bytes`,async()=>{
  const form=new FormData();
  for(let i=0;i<count;i++)form.append('files',new Blob([jpeg],{type:'image/jpeg'}),`synthetic-${i}.jpg`);
  form.append('client_photos',JSON.stringify(Array.from({length:count},()=>({metadata:{},measured}))));
  form.append('request_provider','gemini');form.append('request_model','gemini-3.5-flash-lite');form.append('request_api_key','synthetic-key');
  return request(parser==='identify'?'/identify':`/probe/profile/${parser}`,{method:'POST',body:form});
}]);
const tokens=[];
cases.push(['share-save-700KiB',async()=>{
  const form=new FormData();
  form.append('candidates',JSON.stringify([{common_name_ja:'合成検証',confidence:30,traits:['合成特徴']}]));
  form.append('photo',new Blob([Buffer.alloc(700*1024,37)],{type:'image/png'}),'synthetic.png');
  return request('/api/share',{method:'POST',body:form,headers:{Cookie:cookie}});
}]);
async function checked(name,response){
  const body=await response.arrayBuffer();
  assert.equal(response.status,200,`${name}: ${response.status} ${Buffer.from(body).toString().slice(0,200)}`);
  if(name.startsWith('identify-')||name.startsWith('native-upload-')||name.startsWith('native-identify-')||name.startsWith('native-gemini-payload-')){
    const count=Number(name.match(/-(\d)x-/)[1]);
    assert.deepEqual(JSON.parse(Buffer.from(body)).probe.sha256,Array(count).fill(expectedHash));
    if(name.startsWith('native-gemini-payload-')){
      const data=JSON.parse(Buffer.from(body));assert.equal(data.network_calls,0);
      assert.ok(data.wire_bytes>=count*4*Math.ceil(jpeg.length/3));
    }
  }
  if(name.startsWith('d1-')&&name.endsWith('-read')){
    const data=JSON.parse(Buffer.from(body));assert.equal(data.photo_bytes,700*1024);
    assert.equal(data.sha256,createHash('sha256').update(Buffer.alloc(700*1024,37)).digest('hex'));
  }
  if(name==='share-save-700KiB')tokens.push(JSON.parse(Buffer.from(body)).token);
  if(name==='share-read-700KiB')assert.deepEqual(Buffer.from(body),Buffer.alloc(700*1024,37));
}
try{
  await command('Profiler.enable');await command('Profiler.setSamplingInterval',{interval:1000});
  for(const [name,action] of cases){
    await checked(name,await action());
    for(let repetition=0;repetition<3;repetition++){
      await command('Profiler.start');const start=performance.now();
      try{
        await checked(name,await action());
      }catch(error){await command('Profiler.stop');throw error;}
      const wall=performance.now()-start;
      const {profile}=await command('Profiler.stop');
      console.log(JSON.stringify({name,repetition,scope:'local V8 samples, not production CPU',bundle_sha256:digest,wall_ms:Number(wall.toFixed(3)),...summarize(profile)}));
    }
  }
  const token=tokens[0];
  for(const [name,path] of [['share-page',`/s/${token}`],['share-read-700KiB',`/s/${token}/photo`]]){
    await checked(name,await request(path));
    for(let repetition=0;repetition<3;repetition++){
      await command('Profiler.start');const start=performance.now();
      await checked(name,await request(path));
      const wall=performance.now()-start;
      const {profile}=await command('Profiler.stop');
      console.log(JSON.stringify({name,repetition,scope:'local V8 samples, not production CPU',bundle_sha256:digest,wall_ms:Number(wall.toFixed(3)),...summarize(profile)}));
    }
  }
  for(const mode of ['blob','hex'])for(const operation of ['write','read']){
    const name=`d1-${mode}-${operation}`;
    const action=()=>request(`/probe/profile/d1/${mode}/${operation}`,{method:operation==='write'?'POST':'GET'});
    const reset=async()=>assert.equal((await request(`/probe/profile/d1/${mode}/delete`,{method:'POST'})).status,200);
    if(operation==='write')await reset();
    await checked(name,await action());
    for(let repetition=0;repetition<3;repetition++){
      // Keep cleanup outside the measurement: each write must be an INSERT.
      if(operation==='write')await reset();
      await command('Profiler.start');const start=performance.now();
      await checked(name,await action());
      const wall=performance.now()-start;
      const {profile}=await command('Profiler.stop');
      console.log(JSON.stringify({name,repetition,scope:'local V8 samples, not production CPU',bundle_sha256:digest,wall_ms:Number(wall.toFixed(3)),...summarize(profile)}));
    }
  }
}finally{
  socket.terminate();for(const waiter of pending.values())clearTimeout(waiter.timer);
  for(const token of tokens){const response=await request(`/api/share/${token}/delete`,{method:'POST',headers:{Cookie:cookie}});assert.equal(response.status,200,'Synthetic share cleanup');}
  for(const mode of ['blob','hex'])assert.equal((await request(`/probe/profile/d1/${mode}/delete`,{method:'POST'})).status,200);
}
