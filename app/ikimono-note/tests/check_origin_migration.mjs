// Exercise existing backup contract across isolated browser origins.
// Synthetic records only; no Google, Drive, production data or external HTTP.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';
const source=await readFile(new URL('../static/assets/backup.js',import.meta.url),'utf8');
const browser=await chromium.launch({headless:true});
try {
  const context=await browser.newContext();
  await context.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><body data-app-mode="public"></body>'}));
  const old=await context.newPage(),next=await context.newPage();
  await old.goto('https://old-origin.invalid/');await old.addScriptTag({content:source});
  const backup=await old.evaluate(async()=>{
    sessionStorage.setItem('species-key-gemini','synthetic-never-export');
    localStorage.setItem('species-public-settings',JSON.stringify({provider:'gemini',model:'synthetic-model'}));
    const thumb=new Blob([new Uint8Array([255,216,255,217])],{type:'image/jpeg'});
    await putHistoryEntries([{id:'synthetic-old',createdAt:'2026-10-09T00:00:00Z',
      observedDate:'2026-10-08',latitude:35,longitude:139,userNote:'古い記録のメモ',
      candidates:[{scientific_name:'Felis catus',taxonomy_status:'verified',taxonomy_source:'gbif',
        taxonomy_url:'https://www.catalogueoflife.org/data/taxon/3DXV3'}],
      thumbnail:thumb,thumbnails:[thumb,thumb,thumb],listThumbnail:thumb,
      drivePhotos:['synthetic-photo-1','synthetic-photo-2','synthetic-photo-3']}]);
    return await buildBackup();
  });
  assert.ok(!JSON.stringify(backup).includes('synthetic-never-export'));
  await next.goto('https://new-origin.invalid/');await next.addScriptTag({content:source});
  assert.equal(await next.evaluate(async()=>(await allHistoryEntries()).length),0);
  const result=await next.evaluate(async payload=>{
    await putHistoryEntries([{id:'synthetic-existing',createdAt:'2026-10-10T00:00:00Z',userNote:'新しい記録'}]);
    const restored=await restoreBackup(payload),entries=await allHistoryEntries();
    const entry=entries.find(x=>x.id==='synthetic-old');
    return {restored,count:entries.length,note:entry.userNote,date:entry.observedDate,
      location:[entry.latitude,entry.longitude],candidates:entry.candidates,photoIds:entry.drivePhotos,
      smallBytes:Array.from(new Uint8Array(await entry.listThumbnail.arrayBuffer())),
      fullPhotoCount:entry.thumbnails.length,settings:JSON.parse(localStorage.getItem('species-public-settings')),
      key:sessionStorage.getItem('species-key-gemini')};
  },backup);
  assert.equal(result.restored,1);assert.equal(result.count,2);assert.equal(result.note,'古い記録のメモ');
  assert.equal(result.date,'2026-10-08');assert.deepEqual(result.location,[35,139]);
  assert.deepEqual(result.candidates,[{scientific_name:'Felis catus',taxonomy_status:'verified',taxonomy_source:'gbif',
    taxonomy_url:'https://www.catalogueoflife.org/data/taxon/3DXV3'}]);
  assert.deepEqual(result.photoIds,['synthetic-photo-1','synthetic-photo-2','synthetic-photo-3']);
  assert.deepEqual(result.smallBytes,[255,216,255,217]);assert.equal(result.fullPhotoCount,0);
  assert.equal(result.settings.provider,'gemini');assert.equal(result.key,null);
  assert.equal(await old.evaluate(async()=>(await allHistoryEntries()).length),1);
  console.log('PASS: new origin starts empty; backup merges records/date/location/GBIF source/thumbnail/3 Drive photo IDs, preserves old origin, excludes session key. Full photos require separate Drive retrieval; actual Drive/migration not performed.');
} finally {await browser.close();}
