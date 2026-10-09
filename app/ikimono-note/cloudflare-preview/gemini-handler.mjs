import {InputError, context, providerTemplate, result, casefold} from './gemini-core.mjs';
import policy from './_gemini_policy.mjs';

const buckets = new Map(), cache = new Map();
const gbifCache = new Map();
let lastGbif=0,gbifRetryAt=0;
let lastTaxonomy = 0, taxonomyActive = false, taxonomyRetryAt = 0;
function taxonomyLimit(seconds) {
  const error=new InputError("分類サービスの利用制限に達しました。時間をおいてから再試行してください",429);
  error.retryAfter=seconds;error.upstreamTaxonomy=true;return error;
}
function taxonomyCooldown() {
  if(Date.now()<taxonomyRetryAt)throw taxonomyLimit(Math.max(1,Math.ceil((taxonomyRetryAt-Date.now())/1000)));
}
const waitingTaxonomy = [];
function acquireTaxonomy() {
  if (!taxonomyActive) {taxonomyActive=true;return Promise.resolve();}
  if (waitingTaxonomy.length >= 8) return Promise.reject(new InputError('分類データの照合が混み合っています。少し待ってから再試行してください',429));
  return new Promise((resolve,reject)=>{
    const ticket={resolve,timer:setTimeout(()=>{
      const index=waitingTaxonomy.indexOf(ticket);if(index>=0)waitingTaxonomy.splice(index,1);
      reject(new InputError('分類データの照合が混み合っています。少し待ってから再試行してください',429));
    },15000)};
    waitingTaxonomy.push(ticket);
  });
}
function releaseTaxonomy() {
  const ticket=waitingTaxonomy.shift();
  if(ticket){clearTimeout(ticket.timer);ticket.resolve();}else taxonomyActive=false;
}
function rate(request, scope) {
  const client = (request.headers.get('CF-Connecting-IP') || request.headers.get('X-Forwarded-For')?.split(',')[0]?.trim() || 'unknown').slice(0,64);
  const now = Date.now(), key = client + ':' + scope;
  for (const [name,values] of buckets) if (!values.length || values.at(-1) <= now-60000) buckets.delete(name);
  const values = (buckets.get(key) || []).filter(value=>value>now-60000);
  if (values.length >= 6) return Response.json({detail:'しばらく待ってから再試行してください'}, {status:429,headers:{'Retry-After':'60'}});
  // Bound isolate memory; deny additional client buckets while active, rather
  // than evicting a bucket and silently granting another allowance.
  if (!buckets.has(key) && buckets.size >= 4096) return Response.json({detail:'しばらく待ってから再試行してください'}, {status:429,headers:{'Retry-After':'60'}});
  values.push(now); buckets.set(key,values);
}

async function boundedText(request, maximum, timeoutMs=15000) {
  const length = request.headers.get('Content-Length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length)>maximum)) throw new InputError('写真の情報またはGeminiの応答を読み取れませんでした',400);
  if (!request.body) throw new InputError('写真の情報を読み取れませんでした');
  const reader=request.body.getReader(), chunks=[]; let size=0;
  let timer;
  const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{
    reject(new InputError('送信が完了しませんでした。もう一度お試しください',408));
    void reader.cancel().catch(()=>{});
  },timeoutMs);});
  try {
    while (true) {
      const chunk=await Promise.race([reader.read(),timeout]); if(chunk.done) break;
      size+=chunk.value.length;
      if(size>maximum) {void reader.cancel().catch(()=>{}); throw new InputError('写真の情報またはGeminiの応答を読み取れませんでした',400);}
      chunks.push(chunk.value);
    }
  } finally {clearTimeout(timer);reader.releaseLock();}
  const bytes=new Uint8Array(size); let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  try {return new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);} catch {throw new InputError('写真の情報を読み取れませんでした');}
}

async function lookupInaturalist(name, fetcher=fetch) {
  if(cache.has(name)) return cache.get(name);
  taxonomyCooldown();
  await acquireTaxonomy();
  try {
    if(cache.has(name)) return cache.get(name);
    taxonomyCooldown();
    const delay=1000-(Date.now()-lastTaxonomy);
    if(delay>0) await new Promise(resolve=>setTimeout(resolve,delay));
    const url=new URL(policy.taxonomy_url);
    url.searchParams.set('q',name);url.searchParams.set('per_page','5');url.searchParams.set('locale','ja');
    try {
      // Only scientific names; never photos, capture fields, cookies or keys.
      const response=await fetcher(url.href,{headers:{'User-Agent':policy.taxonomy_agent},redirect:'manual',signal:AbortSignal.timeout(5000)});
      lastTaxonomy=Date.now();
      if(response.status===429){
        await response.body?.cancel();
        const header=response.headers.get('Retry-After')||'';
        const seconds=/^\d+$/.test(header)&&Number.isSafeInteger(Number(header))?Math.min(3600,Math.max(1,Number(header))):60;
        taxonomyRetryAt=Date.now()+seconds*1000;throw taxonomyLimit(seconds);
      }
      if(!response.ok){await response.body?.cancel();return null;}
      const body=JSON.parse(await boundedText(response,2*1024*1024));
      if(!Array.isArray(body?.results))return null;
      const taxa=body.results;
      if(cache.size>=256) cache.delete(cache.keys().next().value);
      cache.set(name,taxa);return taxa;
    } catch(error) {if(error instanceof InputError && error.status===429)throw error;return null;}
  } finally {releaseTaxonomy();}
}

export function gbifTaxa(name,data) {
  const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
  if(!object(data)||!object(data.diagnostics))return null;
  const diagnostics=data.diagnostics;
  if(diagnostics.issues!=null&&!Array.isArray(diagnostics.issues))return null;
  if(!['NONE','FUZZY','HIGHERRANK','EXACT'].includes(diagnostics.matchType))return null;
  if(diagnostics.matchType!=='EXACT')return [];
  const usage=data.usage;
  if(!object(usage)||typeof usage.canonicalName!=='string'||typeof usage.key!=='string'||!/^[A-Za-z0-9]{1,32}$/.test(usage.key))return null;
  if(casefold(usage.canonicalName)!==casefold(name)||usage.status!=='ACCEPTED'||usage.type!=='SCIENTIFIC'||data.synonym!==false||
     typeof diagnostics.confidence!=='number'||!(diagnostics.confidence>=95&&diagnostics.confidence<=100)||
     (diagnostics.issues&&(!Array.isArray(diagnostics.issues)||diagnostics.issues.length)))return [];
  if(!Array.isArray(data.classification)||typeof usage.rank!=='string')return null;
  const group=data.classification.find(row=>object(row)&&row.rank==='CLASS')?.name;
  return [{name:usage.canonicalName,preferred_common_name:'',rank:usage.rank.toLowerCase(),
    iconic_taxon_name:typeof group==='string'?group:'',source:'gbif',gbif_key:usage.key}];
}

async function lookupGbif(name,fetcher) {
  if(gbifCache.has(name))return gbifCache.get(name);
  await acquireTaxonomy();
  try{
    if(gbifCache.has(name))return gbifCache.get(name);
    if(Date.now()<gbifRetryAt)throw taxonomyLimit(Math.max(1,Math.ceil((gbifRetryAt-Date.now())/1000)));
    const delay=1000-(Date.now()-lastGbif);
    if(delay>0)await new Promise(resolve=>setTimeout(resolve,delay));
    const url=new URL(policy.gbif_url);
    url.searchParams.set('scientificName',name);url.searchParams.set('checklistKey',policy.gbif_checklist);
    const response=await fetcher(url.href,{headers:{'User-Agent':policy.taxonomy_agent},redirect:'manual',signal:AbortSignal.timeout(5000)});
    lastGbif=Date.now();
    if(response.status===429){
      await response.body?.cancel();const header=response.headers.get('Retry-After')||'';
      const seconds=/^\d+$/.test(header)&&Number.isSafeInteger(Number(header))?Math.min(3600,Math.max(1,Number(header))):60;
      gbifRetryAt=Date.now()+seconds*1000;throw taxonomyLimit(seconds);
    }
    if(!response.ok){await response.body?.cancel();throw new InputError('分類サービスに接続できず、候補を確認できませんでした。写真はそのままで、時間をおいてから再試行してください',503);}
    const taxa=gbifTaxa(name,JSON.parse(await boundedText(response,256*1024,5000)));
    if(taxa===null)throw new InputError('分類サービスの応答を確認できませんでした。時間をおいてから再試行してください',503);
    if(gbifCache.size>=256)gbifCache.delete(gbifCache.keys().next().value);
    gbifCache.set(name,taxa);return taxa;
  }catch(error){
    if(error instanceof InputError&&(error.status===429||error.status===503))throw error;
    throw new InputError('分類サービスに接続できず、候補を確認できませんでした。写真はそのままで、時間をおいてから再試行してください',503);
  }finally{releaseTaxonomy();}
}

export async function lookupTaxon(name,fetcher=fetch,fallback=false) {
  try{
    const taxa=await lookupInaturalist(name,fetcher);
    if(taxa!==null||!fallback)return taxa;
  }catch(error){if(!fallback||!error.upstreamTaxonomy)throw error;}
  return lookupGbif(name,fetcher);
}

export async function handleGemini(request, path, lookup, settings={}) {
  if(request.method!=='POST') return new Response('Method not allowed',{status:405,headers:{Allow:'POST'}});
  const limited=rate(request,path.endsWith('/prepare')?'identify':'gemini-result');
  if(limited) return limited;
  if(request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()!=='application/json')
    return Response.json({detail:'写真の情報を読み取れませんでした'},{status:415});
  try {
    let body;
    try {body=JSON.parse(await boundedText(request,path.endsWith('/prepare')?256*1024:4*1024*1024+32768));}
    catch(error) {if(error instanceof InputError) throw error; throw new InputError('写真の情報またはGeminiの応答を読み取れませんでした');}
    const capture=context(body);
    const activeLookup=lookup||((name)=>lookupTaxon(name,fetch,settings.IKIMONO_GBIF_FALLBACK==='1'));
    return Response.json(path.endsWith('/prepare')?providerTemplate(body,capture,settings):await result(body,capture,activeLookup));
  } catch(error) {
    if(error instanceof InputError) return Response.json({detail:error.detail},{status:error.status,
      headers:error.status===429?{'Retry-After':String(error.retryAfter||15)}:{}});
    return Response.json({detail:'写真の情報またはGeminiの応答を読み取れませんでした'},{status:422});
  }
}
