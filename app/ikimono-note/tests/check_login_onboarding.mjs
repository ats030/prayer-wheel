// Synthetic login state and keys; GET-only browser checks, no Google/provider/data writes.
import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';
const app=new URL('../',import.meta.url), live=process.argv.includes('--live');
const origin=live?'https://ikimono-note.ats030.workers.dev':'http://login-check.invalid';
const fixture=process.argv.slice(2).find(arg=>arg!=='--live');
assert.ok(fixture,'Supply the sanitized public settings fixture');
const settings=JSON.parse(await readFile(fixture,'utf8'));settings.google_client_id='';settings.affiliate.enabled=false;
const browser=await chromium.launch({headless:true});
const shots='/tmp/ikimono-login-check';await mkdir(shots,{recursive:true});
try{
 for(const viewport of [{width:390,height:844},{width:1280,height:900}]){
  const context=await browser.newContext({viewport});let signedIn=false, failSettings=false,failMe=false;
  const errors=[];
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url());
   assert.equal(url.origin,origin,'Unexpected external request');assert.equal(route.request().method(),'GET');
   if(url.pathname==='/api/me')return route.fulfill({status:failMe?503:200,json:{available:true,signed_in:signedIn,email:null}});
   if(url.pathname==='/api/settings')return route.fulfill({status:failSettings?503:200,json:settings});
   // Simulate successful identity exchange; real Google credentials are never used.
   if(url.pathname==='/auth/google'){signedIn=true;return route.fulfill({status:200,contentType:'text/html',body:'<meta http-equiv="refresh" content="0;url=/login?continue=1">'});}
   // In live mode only the anonymous entrance and published assets are read from production.
   // Authenticated pages are served from local source to avoid impersonating an account.
   if(live && (url.pathname==='/login'||url.pathname.startsWith('/assets/')||url.pathname.startsWith('/vendor/')||url.pathname==='/theme.js'||url.pathname.endsWith('.png')))return route.continue();
   const name=url.pathname==='/'?'index.html':url.pathname==='/settings'?'settings.html':url.pathname==='/login'?'login.html':url.pathname.slice(1);
   assert.ok(!name.includes('..'));
   let body;try{body=await readFile(new URL('static/'+name,app));}catch{return route.fulfill({status:404,body:''});}
   const type=name.endsWith('.css')?'text/css':/\.m?js$/.test(name)?'text/javascript':'text/html';
   if(name.endsWith('.html'))body=body.toString().replace('<body','<body data-app-mode="public" data-show-local="1" data-browser-photos="1"');
   return route.fulfill({body,contentType:type});
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/login');await page.locator('#google-login').waitFor({state:'visible'});
  assert.match(await page.locator('#login-storage-note').textContent(),/ログインだけでは記録は同期されません/);
  assert.equal(await page.locator('a[href="/"]').count(),0,'Anonymous entrance offers a redirect loop');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:`${shots}/login-${viewport.width}.png`,fullPage:true});
  await page.locator('#google-login').focus();assert.equal(await page.locator('#google-login').evaluate(e=>e===document.activeElement),true);
  await page.locator('#google-login').click();await page.waitForURL('**/settings?setup=gemini');
  await page.locator('#quickGeminiKey').fill('synthetic-never-send');
  await page.getByRole('button',{name:'保存して写真を選ぶ'}).click();await page.waitForURL('**/?setup=done');
  await page.locator('#status').filter({hasText:'写真を選んで'}).waitFor();
  const before=await page.evaluate(()=>({key:localStorage.getItem('species-key-gemini'),settings:localStorage.getItem('species-public-settings')}));
  await page.goto(origin+'/login?continue=1');await page.waitForURL(origin+'/');
  assert.deepEqual(await page.evaluate(()=>({key:localStorage.getItem('species-key-gemini'),settings:localStorage.getItem('species-public-settings')})),before);
  await page.evaluate(()=>{localStorage.clear();sessionStorage.clear();localStorage.setItem('species-public-settings',JSON.stringify({provider:'openai',models:{openai:'saved-model'}}));sessionStorage.setItem('species-key-openai','synthetic-tab');});
  await page.goto(origin+'/login');await page.waitForURL(origin+'/');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('species-public-settings')).provider),'openai');
  await page.evaluate(()=>sessionStorage.removeItem('species-key-openai'));
  await page.goto(origin+'/login');await page.waitForURL(origin+'/settings');
  assert.equal(await page.locator('#quickSetup').isVisible(),false);
  await page.evaluate(()=>localStorage.setItem('species-public-settings',JSON.stringify({provider:'local'})));
  await page.goto(origin+'/login');await page.waitForURL(origin+'/');
  await page.evaluate(()=>{localStorage.clear();sessionStorage.clear();localStorage.setItem('species-public-settings','invalid-json');});
  await page.goto(origin+'/login');await page.waitForURL(origin+'/settings');
  assert.equal(await page.evaluate(()=>localStorage.getItem('species-public-settings')),'invalid-json');
  failSettings=true;
  await page.goto(origin+'/login?continue=1');await page.locator('#login-settings-fallback').waitFor({state:'visible'});
  assert.match(await page.locator('#login-message').textContent(),/設定を確認できません/);
  assert.equal(await page.locator('#google-login').isVisible(),false);
  await page.screenshot({path:`${shots}/error-${viewport.width}.png`,fullPage:true});
  failSettings=false;signedIn=false;
  await page.goto(origin+'/login?failed=1');assert.match(await page.locator('#login-message').textContent(),/ログインできません/);
  assert.equal(await page.locator('#google-login').isVisible(),true);
  failMe=true;
  await page.goto(origin+'/login');await page.locator('#login-message').filter({hasText:'ログイン状態を確認できません'}).waitFor();
  assert.equal(await page.locator('#google-login').isVisible(),true);
  assert.equal(errors.length,0,errors.join('\n'));
  await context.close();console.log(`PASS ${viewport.width}px: entrance, simulated login -> setup -> photo, saved/tab/local providers, invalid storage, retry and load errors; keys unchanged, GET-only`);
 }
}finally{await browser.close();}
