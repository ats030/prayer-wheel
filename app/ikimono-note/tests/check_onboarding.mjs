// Actual HTML/CSS/JS in isolated Chromium; synthetic keys, no provider requests.
// Optional argv[2]: public settings JSON. Otherwise read the production settings once.
import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';
const app=new URL('../',import.meta.url),live=process.argv.includes('--live');
const origin=live?'https://ikimono-note.ats030.workers.dev':'http://onboarding.invalid';
const fixture=process.argv.slice(2).find(arg=>arg!=='--live');
const settings=fixture?JSON.parse(await readFile(fixture,'utf8')):
 await fetch('https://ikimono-note.ats030.workers.dev/api/settings').then(response=>{
  assert.equal(response.status,200);return response.json();});
settings.google_client_id='';settings.affiliate.enabled=false;
const browser=await chromium.launch({headless:true});
const screenshots='/tmp/ikimono-onboarding-check';await mkdir(screenshots,{recursive:true});
try{
 for(const viewport of [{width:390,height:844},{width:1280,height:900}]){
  const context=await browser.newContext({viewport});const errors=[];
  await context.addInitScript(()=>localStorage.setItem('ikimono-analytics-consent','granted'));
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   assert.equal(url.origin,origin,'Unexpected external request');
   assert.equal(request.method(),'GET','Setup sent data to the server');
   if(url.pathname==='/api/settings')return route.fulfill({json:settings});
   if(url.pathname==='/api/me')return route.fulfill({json:{available:false,signed_in:false}});
   if(live)return route.continue();
   const name=url.pathname==='/'?'index.html':url.pathname==='/settings'?'settings.html':url.pathname.slice(1);
   assert.ok(!name.includes('..'));
   let body;try{body=await readFile(new URL('static/'+name,app));}
   catch{try{body=await readFile(new URL('cloudflare-production/assets/'+name,app));}
    catch{return route.fulfill({status:404,body:''});}}
   const type=name.endsWith('.css')?'text/css':/\.m?js$/.test(name)?'text/javascript':name.endsWith('.png')?'image/png':'text/html';
   // Match the public mode attributes injected by main._page in Workers.
   if(name.endsWith('.html'))body=body.toString().replace('<body','<body data-app-mode="public" data-show-local="1" data-browser-photos="1"');
   return route.fulfill({body,contentType:type});
  });
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin);await page.locator('#setupWelcome').waitFor({state:'visible'});
  await page.addScriptTag({url:origin+'/assets/analytics.js'});
  assert.equal(await page.locator('#analyticsConsent').count(),0);
  assert.equal(await page.evaluate(()=>typeof window.gtag),'undefined');
  assert.equal(await page.locator('.admin-flag').isVisible(),false);
  assert.ok(await page.locator('#startSetup').isVisible());
  await page.screenshot({path:`${screenshots}/welcome-${viewport.width}.png`,fullPage:true});
  await page.locator('#startSetup').click();await page.locator('#quickSetup').waitFor({state:'visible'});
  assert.equal(await page.locator('#fullSettings').isVisible(),false);
  assert.equal(await page.locator('#quickSetupForm').evaluate(form=>form.checkValidity()),false);
  await page.locator('#quickGeminiKey').fill('synthetic-key-never-send');
  await page.locator('#quickGeminiKey').press('Tab');
  assert.equal(await page.locator('#quickKeepKey').evaluate(input=>input===document.activeElement),true);
  await page.locator('#quickKeepKey').uncheck();
  await page.screenshot({path:`${screenshots}/setup-${viewport.width}.png`,fullPage:true});
  await page.getByRole('button',{name:'保存して写真を選ぶ'}).click();
  await page.waitForURL('**/?setup=done');
  assert.equal(await page.locator('#setupWelcome').isVisible(),false);
  assert.match(await page.locator('#status').textContent(),/写真を選んで/);
  assert.deepEqual(await page.evaluate(()=>({provider,
    persistent:localStorage.getItem('species-key-gemini'),tab:sessionStorage.getItem('species-key-gemini')})),
    {provider:'gemini',persistent:null,tab:'synthetic-key-never-send'});
  assert.equal(await page.evaluate(()=>localStorage.getItem('species-public-settings')),null);
  // Existing other provider remains selected, even via a direct setup URL.
  await page.evaluate(()=>{localStorage.setItem('species-public-settings',JSON.stringify({provider:'openai',models:{openai:'existing-model'}}));
    localStorage.setItem('species-key-openai','synthetic-existing');});
  await page.goto(origin+'/settings?setup=gemini');await page.locator('#active-provider').filter({hasText:'OpenAI'}).waitFor();
  assert.equal(await page.locator('#quickSetup').isVisible(),false);
  assert.equal(await page.locator('#fullSettings').isVisible(),true);
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('species-public-settings')).provider),'openai');
  await page.goto(origin);await page.waitForFunction(()=>window.speciesPublicMode===true);
  assert.equal(await page.locator('#setupWelcome').isVisible(),false);
  await page.evaluate(()=>{localStorage.clear();sessionStorage.clear();});
  await page.goto(origin+'/settings?setup=gemini');await page.locator('#quickSetup').waitFor({state:'visible'});
  await page.locator('#quickGeminiKey').fill('synthetic-persistent');
  await page.getByRole('button',{name:'保存して写真を選ぶ'}).click();await page.waitForURL('**/?setup=done');
  assert.equal(await page.evaluate(()=>localStorage.getItem('species-key-gemini')),'synthetic-persistent');
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('species-key-gemini')),null);
  await page.evaluate(()=>{localStorage.clear();sessionStorage.clear();});
  await page.goto(origin+'/settings?setup=gemini');await page.locator('#quickSetup').waitFor({state:'visible'});
  await page.locator('#quickGeminiKey').fill('synthetic-must-not-replace');
  await page.evaluate(()=>localStorage.setItem('species-public-settings',JSON.stringify({provider:'openai'})));
  await page.getByRole('button',{name:'保存して写真を選ぶ'}).click();
  assert.match(await page.locator('#quickSetupMessage').textContent(),/設定が更新されました/);
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('species-public-settings')).provider),'openai');
  await page.evaluate(()=>{localStorage.clear();sessionStorage.clear();});
  await page.goto(origin+'/settings?setup=gemini');await page.locator('#quickSetup').waitFor({state:'visible'});
  await page.locator('#quickGeminiKey').fill('synthetic-only');
  // Writes blocked: stay on setup and explain the failure without exposing key.
  await page.locator('#quickKeepKey').uncheck();
  await page.evaluate(()=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(name,value){
    if(name==='species-key-gemini')throw new DOMException('blocked','QuotaExceededError');
    return original.call(this,name,value);};});
  await page.getByRole('button',{name:'保存して写真を選ぶ'}).click();
  assert.match(await page.locator('#quickSetupMessage').textContent(),/保存できません/);
  assert.ok(page.url().endsWith('/settings?setup=gemini'));
  assert.equal(await page.evaluate(()=>localStorage.getItem('species-keep-keys')),null);
  assert.equal(await page.evaluate(()=>readApiKey('gemini')),'');
  await page.route('**/api/settings',route=>route.fulfill({status:503,json:{detail:'unavailable'}}));
  await page.goto(origin+'/settings?setup=gemini');
  await page.locator('#active-provider').filter({hasText:'設定を読み込めませんでした'}).waitFor();
  assert.equal(await page.locator('#quickSetup').isVisible(),false);
  assert.equal(errors.length,0,errors.join('\n'));
  await context.close();
  console.log(`PASS: ${viewport.width}px first use, keyboard, persistent/tab-only key, existing/concurrent provider, storage failure; no external/POST requests`);
 }
}finally{await browser.close();}
