// UI regression with synthetic provider/taxonomy HTTP. No real AI or Drive calls.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHmac} from 'node:crypto';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';
import {context as captureContext,providerTemplate,result,InputError} from './gemini-core.mjs';
import {lookupTaxon} from './gemini-handler.mjs';
const origin=process.argv[2]||'http://localhost:8795';
assert.ok(['http://localhost:8795','https://ikimono-note-preview.ats030.workers.dev'].includes(origin));
const secrets=JSON.parse(await readFile('/home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json','utf8'));
const session=Buffer.from(JSON.stringify({sub:'synthetic-candidate-ui',email:'synthetic@example.invalid',
  exp:Math.floor(Date.now()/1000)+600})).toString('base64url');
const cookie=session+'.'+createHmac('sha256',secrets.IKIMONO_SESSION_SECRET).update(session).digest('base64url');
const data={category:'動物',candidates:[{common_name_ja:'ネコ',scientific_name:'Felis catus',
  confidence:90,traits:['耳','毛'],distinguishing_features:['顔の形']} ]};
const taxa=[{id:47867,name:'Felis catus',preferred_common_name:'イエネコ',rank:'species',iconic_taxon_name:'Mammalia'}];
const browser=await chromium.launch({headless:true});
try{
  for(const scenario of [{kind:'verified',count:1},{kind:'verified',count:3},{kind:'gbif',count:3},{kind:'empty',count:1},
    {kind:'unavailable',count:1},{kind:'quota',count:1,plantnet:true}]){
    const ctx=await browser.newContext({httpCredentials:{username:'preview',password:secrets.IKIMONO_PREVIEW_PASSWORD}});
    await ctx.addCookies([{name:'ikimono_session',value:cookie,url:origin}]);
    await ctx.addInitScript(plantnet=>{
      sessionStorage.setItem('species-key-gemini','synthetic-never-forward');
      if(plantnet)sessionStorage.setItem('species-key-plantnet','synthetic-plantnet-never-forward');
      localStorage.setItem('species-public-settings',JSON.stringify({provider:'gemini'}));
    },Boolean(scenario.plantnet));
    let completed=0;
    const unavailable='分類サービスに接続できず、候補を確認できませんでした。写真はそのままで、時間をおいてから再試行してください';
    const quota='分類サービスの利用制限に達しました。時間をおいてから再試行してください';
    await ctx.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());
      const fulfill=(status,body)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
      if(url.origin===origin){
        if(url.pathname.startsWith('/api/affiliate/'))return fulfill(200,{products:[]});
        if(url.pathname==='/identify'){
          assert.ok(scenario.plantnet);completed++;return fulfill(429,{detail:quota});
        }
        if(url.pathname==='/api/gemini/prepare'){
          const body=request.postDataJSON();return fulfill(200,providerTemplate(body,captureContext(body)));
        }
        if(url.pathname==='/api/gemini/result'){
          completed++;const body=request.postDataJSON();
          if(scenario.kind==='verified'&&scenario.count===3){
            assert.ok(Buffer.byteLength(body.reply)<8192);
            const reply=JSON.parse(body.reply);assert.equal(reply.usageMetadata.thoughtsTokenCount,7);
            assert.equal(Object.hasOwn(reply.usageMetadata,'unused'),false);
          }
          const lookup=async name=>scenario.kind==='gbif'?lookupTaxon(name,async url=>{
            if(new URL(url).origin==='https://api.inaturalist.org')return new Response(null,{status:429});
            assert.equal(new URL(url).origin,'https://api.gbif.org');
            return Response.json({usage:{key:'3DXV3',canonicalName:'Felis catus',rank:'SPECIES',status:'ACCEPTED',type:'SCIENTIFIC'},
              classification:[{rank:'CLASS',name:'Mammalia'}],diagnostics:{matchType:'EXACT',confidence:99},synonym:false});
          },true):scenario.kind==='unavailable'?null:taxa;
          try{return fulfill(200,await result(body,captureContext(body),lookup));}
          catch(error){assert.ok(error instanceof InputError);return fulfill(error.status,{detail:error.detail});}
        }
        return route.continue();
      }
      if(url.origin==='https://generativelanguage.googleapis.com'){
        assert.ok(!scenario.plantnet);
        const reply={candidates:[{content:{parts:[{text:JSON.stringify(scenario.kind==='empty'?{category:'不明',candidates:[]}:data)}]}}]};
        if(scenario.kind==='verified'&&scenario.count===3){
          reply.usageMetadata={thoughtsTokenCount:7,unused:''};
          reply.usageMetadata.unused='x'.repeat(2*1024*1024-Buffer.byteLength(JSON.stringify(reply)));
        }
        return fulfill(200,reply);
      }
      return route.abort();
    });
    const page=await ctx.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(origin+'/');
    await page.waitForFunction(()=>window.speciesBrowserGemini===true&&document.getElementById('providerStatus').textContent.includes('Gemini'));
    const photo=await page.evaluate(()=>{
      const canvas=document.createElement('canvas');canvas.width=600;canvas.height=450;const draw=canvas.getContext('2d');
      for(let y=0;y<450;y+=10)for(let x=0;x<600;x+=10){draw.fillStyle=((x+y)/10)%2?'#709050':'#c0b050';draw.fillRect(x,y,10,10);}
      return canvas.toDataURL('image/jpeg').split(',')[1];
    });
    await page.locator('#library').setInputFiles(Array.from({length:scenario.count},(_,index)=>({
      name:'synthetic-'+index+'.jpg',mimeType:'image/jpeg',buffer:Buffer.from(photo,'base64')})));
    await page.locator('#identify').waitFor({state:'visible'});
    assert.equal(await page.locator('#usePlantnet').isChecked(),Boolean(scenario.plantnet));
    await page.locator('#identify').click();
    const positive=['verified','gbif'].includes(scenario.kind);
    const expected=positive?'似ている生きものを表示しました':scenario.kind==='empty'?
      '図鑑データで確認できる候補が見つかりませんでした':scenario.kind==='quota'?quota:unavailable;
    await page.waitForFunction(text=>document.getElementById('status').textContent.includes(text),expected);
    assert.equal(completed,1);assert.deepEqual(errors,[]);
    assert.equal(await page.locator('article.candidate').count(),positive?1:0);
    if(scenario.kind==='verified')assert.ok((await page.locator('article.candidate .name').textContent()).includes('イエネコ'));
    if(scenario.kind==='gbif'){
      assert.ok((await page.locator('article.candidate .name').textContent()).includes('Felis catus（和名未確認）'));
      assert.ok((await page.locator('article.candidate').textContent()).includes('CC BY 4.0'));
    }
    if(['quota','unavailable'].includes(scenario.kind)){
      assert.ok((await page.locator('#results').textContent()).includes(expected));
      assert.ok(!(await page.locator('#results').textContent()).includes('別の角度'));
      assert.equal(await page.locator('#identify').isDisabled(),false);
    }
    const shouldSave=positive||scenario.kind==='empty';
    const saved=await page.evaluate(async save=>{
      const deadline=Date.now()+10000;
      while(Date.now()<deadline){
        const open=indexedDB.open('species-history',1);
        // Do not create a version1 DB without its store while the app is saving.
        open.onupgradeneeded=()=>open.result.createObjectStore('entries',{keyPath:'id'});
        const db=await new Promise(resolve=>{open.onsuccess=()=>resolve(open.result);});
        const read=db.transaction('entries').objectStore('entries').getAll();
        const rows=await new Promise(resolve=>{read.onsuccess=()=>resolve(read.result);});db.close();
        if(save&&rows.length===1)return {candidates:rows[0].candidates.length,photos:rows[0].thumbnails.length};
        if(!save){if(rows.length)throw Error('Failed result was saved');return null;}
        await new Promise(resolve=>setTimeout(resolve,50));
      }
      throw Error('Save did not commit: '+document.getElementById('status').textContent);
    },shouldSave);
    assert.deepEqual(saved,shouldSave?{candidates:positive?1:0,photos:scenario.count}:null);
    if(scenario.kind==='gbif'){
      await page.goto(origin+'/history');
      await page.locator('.entry').first().waitFor();
      assert.ok((await page.locator('.entry').first().textContent()).includes('CC BY 4.0'));
      assert.ok((await page.locator('.entry').first().textContent()).includes('Catalogue of Life'));
    }
    await ctx.close();
  }
  console.log('PASS: synthetic core + real browser verified 1/3photos/save, GBIF recovery after429/source/license/history, genuine empty status, direct503 and Plantnet-fallback429 visible/no failed record; external HTTP mocked');
}finally{await browser.close();}
