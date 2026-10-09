// Real Chromium JPEG encoder; synthetic detail/noise only, no external HTTP.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage();
  await page.route('https://compression.invalid/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><body></body>'});
    if(path==='/vendor/photo/exifr.mjs')return route.fulfill({contentType:'text/javascript',body:
      'export default {fileParsers:{get(){return class {};}}};'});
    assert.match(path,/^\/assets\/photo-[a-z-]+\.mjs$/);
    return route.fulfill({contentType:'text/javascript',body:await readFile(new URL('../static'+path,import.meta.url),'utf8')});
  });
  await page.goto('https://compression.invalid/');
  const rows=await page.evaluate(async()=>{
    const {compressPhotoCanvas}=await import('/assets/photo-browser.mjs');
    const rows=[];
    for(const [width,height,noise] of [[3200,2400,true],[2400,3200,true],[1600,1200,true],[1200,1200,true],[3200,2400,false],[640,480,false]]) {
      const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
      const ctx=canvas.getContext('2d');let seed=42;
      const image=ctx.createImageData(width,height);
      for(let i=0;i<image.data.length;i+=4){
        seed=(Math.imul(seed,1664525)+1013904223)>>>0;
        const value=noise?seed>>>24:((Math.floor(i/4/width/12)+Math.floor(i/4%width/12))%2?220:35);
        image.data[i]=image.data[i+1]=image.data[i+2]=value;image.data[i+3]=255;
      }
      ctx.putImageData(image,0,0);
      const before=await new Promise(resolve=>{const c=document.createElement('canvas');
        const scale=Math.min(1,1600/Math.max(width,height));c.width=Math.round(width*scale);c.height=Math.round(height*scale);
        const x=c.getContext('2d');x.imageSmoothingQuality='high';x.drawImage(canvas,0,0,c.width,c.height);
        c.toBlob(resolve,'image/jpeg',.86);});
      const blob=await compressPhotoCanvas(canvas),bitmap=await createImageBitmap(blob);
      rows.push({width,height,noise,before:before.size,after:blob.size,outWidth:bitmap.width,outHeight:bitmap.height,
        originalPreserved:canvas.width===width&&canvas.height===height,type:blob.type});bitmap.close();
    }
    return rows;
  });
  for(const row of rows){
    assert.equal(row.type,'image/jpeg');assert.ok(row.originalPreserved);assert.ok(row.after<=2*1024*1024);
    assert.ok(Math.max(row.outWidth,row.outHeight)<=1600);
    assert.ok(Math.abs(row.outWidth/row.outHeight-row.width/row.height)<.002);
    if(row.noise){
      if(Math.max(row.width,row.height)>1200)assert.ok(row.after<=768*1024);
      else assert.equal(Math.max(row.outWidth,row.outHeight),Math.max(row.width,row.height));
      assert.ok(Math.max(row.outWidth,row.outHeight)>=1200);assert.ok(row.after<=row.before);
      if(row.before>768*1024)assert.ok(row.after<row.before);
    }
    if(row.before<=768*1024)assert.equal(Math.max(row.outWidth,row.outHeight),Math.min(1600,Math.max(row.width,row.height)));
    else assert.ok(Math.max(row.outWidth,row.outHeight)>=Math.min(1200,Math.max(row.width,row.height)));
  }
  console.log(JSON.stringify(rows));console.log('PASS: real JPEG compression, portrait/landscape detail floor, small-image dimensions and original canvas retained');
} finally {await browser.close();}
