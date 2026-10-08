// Synthetic local inputs only; never run against a published service.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';
const fixtures = new URL('../cloudflare-browser-photo-probe/fixtures/', import.meta.url);
const expected = JSON.parse(await readFile(new URL('expected.json', fixtures)));
const quality = JSON.parse(await readFile(new URL('quality-expected.json', fixtures)));
const browser = await chromium.launch({headless:true});
try {
  for (const timezoneId of ['Asia/Tokyo','America/Los_Angeles']) {
    const context = await browser.newContext({timezoneId,viewport:{width:timezoneId==='Asia/Tokyo'?390:1280,height:844}});
    const page = await context.newPage();
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'
      ? route.continue() : route.abort());
    await page.goto('http://127.0.0.1:8793/');
    await page.locator('.analytics-deny').click();
    assert.equal(await page.locator('body').getAttribute('data-browser-photos'),'1');
    for (const [name,reference] of Object.entries(expected)) {
      console.log(timezoneId, name);
      const bytes=(await readFile(new URL(name,fixtures))).toString("base64");
      const result=await page.evaluate(async ({name,bytes})=>{
        const {preparePhoto}=await import('/assets/photo-browser.mjs');
        const {default:exifr}=await import('/vendor/photo/exifr.mjs');
        const result=await preparePhoto(new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],name,{type:'image/heic'}));
        return {dimensions:result.dimensions,metadata:result.metadata,exif:await exifr.parse(result.photo)||null};
      },{name,bytes});
      assert.deepEqual(result.dimensions,reference.dimensions,name);
      const metadata=reference.context??{observed_date:reference.observed_date,latitude:reference.latitude,longitude:reference.longitude};
      for(const [key,value] of Object.entries(metadata)) assert.equal(result.metadata[key],value,name);
      assert.equal(result.exif,null,name);
    }
    for(const [name,reference] of Object.entries(quality)) {
      console.log(timezoneId, name);
      const bytes=(await readFile(new URL(name,fixtures))).toString("base64");
      const result=await page.evaluate(async ({name,bytes})=>{
        const {preparePhoto}=await import('/assets/photo-browser.mjs');
        return (await preparePhoto(new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],name,{type:'image/png'}))).quality;
      },{name,bytes});
      assert.deepEqual(result,reference,name);
    }
    await page.evaluate(()=>{sessionStorage.setItem('species-key-gemini','synthetic-key');localStorage.setItem('species-public-settings',JSON.stringify({provider:'gemini'}));});
    await page.reload();
    await page.waitForFunction(()=>document.getElementById('providerStatus').textContent.includes('Gemini'));
    await page.locator('#library').setInputFiles({name:'orientation-6.heic',mimeType:'',buffer:await readFile(new URL('orientation-6.heic',fixtures))});
    await page.waitForFunction(()=>document.querySelector('.preview')?.naturalWidth>0);
    const preparedHash=await page.evaluate(async()=>{
      const {preparePhoto}=await import('/assets/photo-browser.mjs');
      const blob=(await preparePhoto(selected[0])).photo;
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))].map(n=>n.toString(16).padStart(2,'0')).join('');
    });
    const responsePromise=page.waitForResponse(response=>new URL(response.url()).pathname==='/identify');
    await page.locator('#identify').click();
    const response=await responsePromise;
    assert.equal(response.status(),200,await response.text());
    const data=await response.json();
    assert.deepEqual(data.probe.sha256,[preparedHash]);
    assert.equal(data.probe.observed_date,'2026-10-07');
    assert.match(data.probe.location,/35\.5000.*139\.7500/);
    await page.waitForFunction(()=>document.getElementById('results').textContent.includes('合成検証'));
    let records=[];
    for(let attempt=0;attempt<100 && !records.length;attempt++) {
      records=await page.evaluate(async()=>{
      const db=await new Promise((resolve,reject)=>{const request=indexedDB.open('species-history',1);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)});
      return await new Promise((resolve,reject)=>{const request=db.transaction('entries').objectStore('entries').getAll();request.onsuccess=()=>{db.close();resolve(request.result.map(record=>({...record,thumbnails:record.thumbnails.map(photo=>({type:photo.type,size:photo.size}))})))};request.onerror=()=>reject(request.error)});
      });
      if(!records.length)await page.waitForTimeout(100);
    }
    assert.equal(records.length,1,await page.locator('#status').textContent());
    assert.equal(records[0].thumbnails[0].type,'image/jpeg');
    assert.ok(records[0].thumbnails[0].size>0);
    assert.equal(records[0].context.observedDate,'2026-10-07');
    assert.equal(JSON.stringify(records).includes('synthetic-key'),false);
    await page.goto('http://127.0.0.1:8793/history');
    await page.locator('.detail summary').click();
    await page.locator('.rerun-box input[type=file][multiple]').setInputFiles({name:'added.heic',mimeType:'',buffer:await readFile(new URL('orientation-6.heic',fixtures))});
    await page.waitForFunction(()=>{const photos=document.querySelectorAll('.rerun-preview img');return photos.length===2&&[...photos].every(photo=>photo.naturalWidth>0)});
    const rerun=page.waitForResponse(response=>new URL(response.url()).pathname==='/identify').catch(()=>null);
    await page.locator('.rerun-go').click();
    const rerunResponse=await rerun;
    assert.ok(rerunResponse,await page.locator('.rerun-message').textContent());
    assert.equal(rerunResponse.status(),200);
    await page.waitForFunction(()=>document.querySelectorAll('.entry').length===2);
    assert.equal(await page.locator('.entry img.thumb').count(),2);
    for(const name of ['stored.zip','deflated.zip']) {
      const bytes=(await readFile(new URL(name,fixtures))).toString("base64");
      const hash=await page.evaluate(async bytes=>{
        const {originalFromZip}=await import('/assets/photo-browser.mjs');
        const file=await originalFromZip(new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],'photo.zip'));
        return [...new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))].map(n=>n.toString(16).padStart(2,'0')).join('');
      },bytes);
      assert.equal(hash,expected['orientation-6.heic'].sha256);
    }
    assert.deepEqual(errors,[]);
    await context.close();
  }
  console.log('PASS: production modules, HEIC orientations/EXIF, 54 quality references, ZIP originals, mobile/desktop capture → Worker → local history, two timezones');
} finally {await browser.close();}
