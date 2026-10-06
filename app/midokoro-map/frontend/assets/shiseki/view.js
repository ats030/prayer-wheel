export function mount(context) {
const {map, document, fetch} = context;

const CACHE_KEY='midokoro-map-shiseki-image-cache-v1';
const GEOCODING_CACHE_KEY='midokoro-map-shiseki-geocoding-cache-v1';
const LINKS_CACHE_KEY='midokoro-map-shiseki-links-cache-v1';
const JALAN_CACHE_KEY='midokoro-map-shiseki-jalan-cache-v1';
const SELECTED_MARKER_Z_INDEX=10000;
const imageCache={};
const wikiContentCache={};
const wikiContentQueue={};
const geocodingCache={};
const geocodingCacheQueue={};
const linksCache={};
const jalanCache={};
const jalanCacheQueue={};
let shisekis=[];
let visible=[];
let markers=new Map();
let selectedMarker=null;
let selectedKey=null;
let selectedOrigin=null;
const saveTimers={};

for(const [key,target] of [[CACHE_KEY,imageCache],[GEOCODING_CACHE_KEY,geocodingCache],[LINKS_CACHE_KEY,linksCache],[JALAN_CACHE_KEY,jalanCache]]){
  try{Object.assign(target,JSON.parse(localStorage.getItem(key)||'{}'))}
  catch(error){console.warn(`Cache ${key} could not be loaded`,error)}
}

function persist(key,value){
  clearTimeout(saveTimers[key]);
  saveTimers[key]=setTimeout(()=>{try{localStorage.setItem(key,JSON.stringify(value))}catch(error){console.warn(`Cache ${key} could not be saved`,error)}},500);
}
function shisekiKey(o,index=0){return o.id||o.qid||`${o.label_ja}-${o.latitude}-${o.longitude}-${index}`}
function wikiQID(o){return /^Q[1-9][0-9]*$/.test(o.qid||'')?o.qid:''}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:''}catch{return''}}
function plainText(value){const document=new DOMParser().parseFromString(String(value||''),'text/html');return document.body.textContent.trim()}
function commonsFilePage(value){
  try{
    const url=new URL(value);if(!['upload.wikimedia.org','thumb.wikimedia.org'].includes(url.hostname))return'';
    const parts=url.pathname.split('/').filter(Boolean),thumbIndex=parts.indexOf('thumb');
    const fileName=decodeURIComponent(thumbIndex>=0?parts[parts.length-2]:parts[parts.length-1]);
    return fileName?`https://commons.wikimedia.org/wiki/File:${encodeURIComponent(fileName)}`:'';
  }catch{return''}
}
function categoryTags(o){
  const list=Array.isArray(o.categories)?o.categories:[];
  if(list.length)return list;
  return ['その他'];
}
const CATEGORY_COLORS=new Map([
  ['社寺・宗教遺跡','religious'],['城跡','castle'],['橋','bridge'],
  ['古墳','burial'],['産業遺産','industrial'],['遺跡','archaeological'],['史跡','historic'],
  ['庭園','garden'],['港','port'],['旧跡','former'],['歴史的建造物','building'],['その他','other']
]);
function categoryColorToken(o){return `--color-category-${CATEGORY_COLORS.get(categoryTags(o)[0])||'other'}`}
function categoryColor(o){return getComputedStyle(document.documentElement).getPropertyValue(categoryColorToken(o)).trim()}
document.querySelector('.map-legend').innerHTML=[...CATEGORY_COLORS].map(([label])=>
  `<span><span class="legend-dot" style="background:var(${categoryColorToken({categories:[label]})})" aria-hidden="true"></span>${esc(label)}</span>`
).join('');
function categoryText(o){return categoryTags(o).join('・')}
function categoryDetailText(o){
  return categoryTags(o).join('・');
}
function designationRank(o){
  const value=String(o.designation||'').trim().toLowerCase();
  return ['special','national','local','undesig','unknown'].includes(value)?value:'unknown';
}
function designationLabel(status){
  return {special:'特別史跡',national:'国指定史跡',local:'地方指定史跡',undesig:'未指定',unknown:'指定不明'}[status];
}
function designationBadge(o){
  const status=designationRank(o);
  const label=String(o.designation_label||'').trim()||designationLabel(status);
  return `<p class="designation-line"><span class="designation-badge designation-badge--${status}" role="note">${esc(label)}</span></p>`;
}
function mapCoordinates(o){
  const latitude=Number(o.latitude),longitude=Number(o.longitude);
  return Number.isFinite(latitude)&&Number.isFinite(longitude)?{latitude,longitude}:null;
}
function locationCacheKey(o){const point=mapCoordinates(o);return point?`${point.latitude.toFixed(5)},${point.longitude.toFixed(5)}`:''}
function locationPrecisionLabel(o){
  if(o.coordinate_source==='administrative_area')return'位置は行政区域の目安';
  return'位置は目安';
}
function locationMarkup(location,o){
  const status=`<span class="location-status">${esc(locationPrecisionLabel(o))}</span>`;
  return `${esc(location)}${status}`;
}
async function fetchJSONWithRetry(url){
  let lastError;
  for(let attempt=0;attempt<2;attempt++){
    try{const response=await fetch(url);if(response.ok)return response.json();lastError=new Error(`HTTP ${response.status}`)}catch(error){lastError=error}
    if(attempt===0)await new Promise(resolve=>setTimeout(resolve,500));
  }
  throw lastError;
}
const WIKI_SECTIONS_RETRY_MS=60000;
async function loadWikipediaContent(o){
  if(!wikiQID(o)&&!o.wikipedia_title)return null;
  const title=o.wikipedia_title||o.title_ja||o.label_ja;if(!title)return null;
  const cacheKey=`${shisekiKey(o)}:${title}`;
  const cached=wikiContentCache[cacheKey];
  // A transient sections failure is cached too (so re-opening the panel does
  // not re-issue every Wikimedia request for this shiseki), but only for a
  // short cooldown, so a real rate-limit event heals itself on the next open
  // instead of caching the gap for the rest of the browsing session.
  if(cached&&(!cached.sections_unavailable||Date.now()<cached._sectionsRetryAt))return cached;
  if(wikiContentQueue[cacheKey])return wikiContentQueue[cacheKey];
  wikiContentQueue[cacheKey]=fetchJSONWithRetry(`/api/wiki/content?title=${encodeURIComponent(title)}&qid=${encodeURIComponent(o.qid||'')}`)
    .then(data=>{
      if(data){
        if(data.sections_unavailable)data._sectionsRetryAt=Date.now()+WIKI_SECTIONS_RETRY_MS;
        wikiContentCache[cacheKey]=data;
      }
      return data;
    })
    .catch(error=>{console.warn(`Wikipedia content could not be loaded for ${title}`,error);return null})
    .finally(()=>delete wikiContentQueue[cacheKey]);
  return wikiContentQueue[cacheKey];
}
async function detailedLocation(o){
  const embedded=o.address||o.location||o.municipality||o.city;
  if(embedded)return embedded.startsWith(o.prefecture)?embedded:[o.prefecture,embedded].filter(Boolean).join(' ');
  const point=mapCoordinates(o);if(!point)return o.prefecture||'地域未登録';
  const key=locationCacheKey(o);
  if(geocodingCache[key])return geocodingCache[key];
  if(geocodingCacheQueue[key])return geocodingCacheQueue[key];
  geocodingCacheQueue[key]=fetch('/api/geocoding/reverse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lat:point.latitude,lng:point.longitude})})
    .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()})
    .then(data=>{
      const resolved=data.success&&(data.full_location||data.location)?data.full_location||data.location:'';
      if(!resolved)return o.prefecture||'地域未登録';
      return o.prefecture&&!resolved.includes(o.prefecture)?`${o.prefecture} ${resolved}`:resolved;
    })
    .catch(error=>{console.warn(`Location could not be resolved for ${key}`,error);return o.prefecture||'地域未登録'})
    .then(location=>{geocodingCache[key]=location;persist(GEOCODING_CACHE_KEY,geocodingCache);return location})
    .finally(()=>delete geocodingCacheQueue[key]);
  return geocodingCacheQueue[key];
}
async function loadNearbyHotels(o){
  const prefecture=o.prefecture;if(!prefecture)return null;
  const lrgCode=o.jalan_lrg_code||'',lrgName=o.jalan_lrg_name||'';
  const smlCode=o.jalan_sml_code||'',smlName=o.jalan_sml_name||'';
  const key=smlCode||lrgCode||prefecture;
  if(jalanCache[key]!==undefined)return jalanCache[key];
  if(jalanCacheQueue[key])return jalanCacheQueue[key];
  const params=new URLSearchParams({prefecture});if(lrgCode&&lrgName){params.set('lrg_code',lrgCode);params.set('lrg_name',lrgName)}
  if(smlCode&&smlName){params.set('sml_code',smlCode);params.set('sml_name',smlName)}
  jalanCacheQueue[key]=fetch(`/api/hotel-area/nearby?${params}`)
    .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()})
    .then(data=>Array.isArray(data.hotels)?data.hotels:[])
    .catch(error=>{console.warn(`Nearby hotels could not be loaded for ${key}`,error);return null})
    .then(hotels=>{if(hotels!==null){jalanCache[key]=hotels;persist(JALAN_CACHE_KEY,jalanCache)}return hotels})
    .finally(()=>delete jalanCacheQueue[key]);
  return jalanCacheQueue[key];
}
function affiliateHotelMarkup(hotels){
  if(!hotels?.length)return'';
  return `${context.config.affiliateOrigins.includes(location.origin)?'<span class="ad-label">広告</span>':''}<ul class="affiliate-hotel-list">${hotels.map(h=>{
    let link=safeUrl(h.plan_url)||safeUrl(h.detail_url);
    if(link&&!context.config.affiliateOrigins.includes(location.origin)){
      const url=new URL(link);if(url.hostname==='px.a8.net')link=safeUrl(url.searchParams.get('a8ejpredirect'));
    }if(!link)return'';
    return `<li class="affiliate-hotel"><a class="affiliate-link" href="${esc(link)}" rel="nofollow noopener" target="_blank">${esc(h.name||'宿泊施設')}</a>${h.address?`<span class="affiliate-hotel-address">${esc(h.address)}</span>`:''}</li>`;
  }).join('')}</ul>`;
}
function populatePrefectures(){
  const select=document.querySelector('#prefecture');
  [...new Set(shisekis.map(o=>o.prefecture).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja')).forEach(p=>select.add(new Option(p,p)));
}
function populateCategories(){
  document.querySelector('#category-options').innerHTML=[...new Set(shisekis.flatMap(o=>categoryTags(o)))].sort((a,b)=>a.localeCompare(b,'ja')).map(p=>`<label class="multi-option"><input type="checkbox" value="${esc(p)}">${esc(p)}</label>`).join('');
}
const MULTI_FILTERS=['category','era','designation'];
function selectedValues(id){return [...document.querySelectorAll(`#${id}-options input:checked`)].map(input=>input.value)}
function updateMultiSummary(id){const labels=[...document.querySelectorAll(`#${id}-options input:checked`)].map(input=>input.parentElement.textContent);document.querySelector(`#${id}-summary`).textContent=!labels.length?'すべて':labels.length===1?labels[0]:`${labels[0]} ほか${labels.length-1}`}
function clearMultiFilter(id){document.querySelectorAll(`#${id}-options input`).forEach(input=>{input.checked=false});updateMultiSummary(id)}
const ERA_ORDER=['旧石器時代','縄文時代','続縄文時代','弥生時代','古墳時代','飛鳥時代','奈良時代','平安時代','鎌倉時代','南北朝時代','室町時代','安土桃山時代','江戸時代','明治時代','大正時代','昭和時代','平成時代','令和時代'];
// 元データの細分・表記揺れを時代区分へ寄せる。更新世は地質時代のため分類しない。
const ERA_ALIASES=new Map([['日本列島の旧石器時代','旧石器時代'],['縄文時代中期','縄文時代'],['平安時代前期','平安時代'],['平安時代中期','平安時代'],['平安時代後期','平安時代'],['鎌倉前期','鎌倉時代'],['戦国時代','室町時代'],['江戸中期','江戸時代'],['幕末','江戸時代'],['彷徨五年','奈良時代']]);
function eraTags(o){return [...new Set(String(o.era||'').split('・').map(v=>v.trim()).map(v=>ERA_ALIASES.get(v)||v).filter(v=>ERA_ORDER.includes(v)))]}
function populateEras(){const used=new Set(shisekis.flatMap(eraTags));document.querySelector('#era-options').innerHTML=ERA_ORDER.filter(v=>used.has(v)).map(v=>`<label class="multi-option"><input type="checkbox" value="${esc(v)}">${esc(v)}</label>`).join('')}
function applyFilters(){
  const q=document.querySelector('#keyword').value.trim().toLocaleLowerCase('ja');
  const prefecture=document.querySelector('#prefecture').value;
  const categories=selectedValues('category');
  const eras=selectedValues('era');
  const designations=selectedValues('designation');
  visible=shisekis.filter(o=>{
    const tags=categoryTags(o);
    const text=[o.label_ja,o.label_en,o.prefecture,o.description,o.era,o.designation_label,...tags].filter(Boolean).join(' ').toLocaleLowerCase('ja');
    const prefectureMatches=!prefecture||(o.prefecture===prefecture);
    const categoryMatches=!categories.length||tags.some(tag=>categories.includes(tag));
    return text.includes(q)&&prefectureMatches&&categoryMatches&&(!eras.length||eraTags(o).some(era=>eras.includes(era)))&&(!designations.length||designations.includes(designationRank(o)));
  }).sort((a,b)=>String(a.label_ja||a.label_en||'').localeCompare(String(b.label_ja||b.label_en||''),'ja'));
  renderList();renderMarkers();
  document.querySelector('#result-count').textContent=visible.length;
  document.querySelector('#map-count').textContent=`地図上に ${visible.length} 件`;
}
function renderList(){
  const list=document.querySelector('#shiseki-list');
  if(!visible.length){list.innerHTML='<p class="empty-state">条件に合う史跡がありません。地域を変えてお試しください.</p>';return}
  list.innerHTML=visible.map((o,index)=>{
    const key=shisekiKey(o,index);
    const category=categoryText(o);
    return `<button class="shiseki-card" type="button" data-key="${esc(key)}" aria-current="${key===selectedKey}"><span class="card-index">${String(index+1).padStart(2,'0')}</span><span><span class="card-name">${esc(o.label_ja||o.label_en||'名称未登録')}</span><span class="card-meta"><span>${esc(o.prefecture||'地域未登録')}</span>${category?`<span>${esc(category)}</span>`:''}</span></span></button>`;
  }).join('');
  list.querySelectorAll('button').forEach(card=>card.addEventListener('click',()=>selectShiseki(card.dataset.key,'list')));
}
function icon(selected,shiseki){return L.divIcon({className:'',html:`<span class="shiseki-marker${selected?' selected':''}" style="background:var(${categoryColorToken(shiseki)})"></span>`,iconSize:[22,22],iconAnchor:[11,11],popupAnchor:[0,-12]})}
// Thousands of DOM markers make panning slow, so unselected points are drawn on
// the shared canvas and only the selected point keeps the DOM icon.
// The centre dot is painted with the circle so each point stays one cluster child.
const DottedCircleMarker=L.CircleMarker.extend({
  _updatePath(){
    L.CircleMarker.prototype._updatePath.call(this);
    const renderer=this._renderer;if(!renderer._drawing||this._empty())return;
    const ctx=renderer._ctx,p=this._point;
    ctx.globalAlpha=1;ctx.fillStyle=this.options.color;ctx.beginPath();ctx.arc(p.x,p.y,2.5,0,Math.PI*2);ctx.fill();
  },
});
// Nearby markers cluster by zoom; identical coordinates spiderfy at the maximum zoom.
const markerLayer=L.markerClusterGroup({
  maxClusterRadius:40,
  showCoverageOnHover:false,
  spiderfyDistanceMultiplier:1.3,
  iconCreateFunction:cluster=>{
    const count=cluster.getChildCount();
    const size=count<10?30:count<100?36:count<1000?42:48;
    return L.divIcon({className:'shiseki-cluster-anchor',html:`<span class="shiseki-cluster" aria-label="${count}件の史跡">${count}</span>`,iconSize:[size,size]});
  },
}).addTo(map);
function markerStyle(o){
  const css=getComputedStyle(document.documentElement);
  const fill=categoryColor(o);
  return {radius:9,weight:2,color:css.getPropertyValue('--color-paper').trim(),fillColor:fill,fillOpacity:1};
}
function renderMarkers(){
  markerLayer.clearLayers();markers=new Map();
  visible.forEach((o,index)=>{
    const point=mapCoordinates(o);if(!point)return;
    const key=shisekiKey(o,index),latlng=[point.latitude,point.longitude];
    const marker=new DottedCircleMarker(latlng,markerStyle(o));
    marker.bindTooltip(esc(o.label_ja||o.label_en||'名称未登録'),{direction:'top',offset:[0,-10]});
    marker.on('click',()=>selectShiseki(key,'marker'));markers.set(key,{marker,shiseki:o});
  });
  markerLayer.addLayers([...markers.values()].map(entry=>entry.marker));
  if(selectedKey&&!markers.has(selectedKey))closeDetail(false);else showSelectedMarker(selectedKey);
}
function showSelectedMarker(key){
  if(selectedMarker){map.removeLayer(selectedMarker);selectedMarker=null}
  const entry=key&&markers.get(key);if(!entry)return;
  const o=entry.shiseki;
  selectedMarker=L.marker(entry.marker.getLatLng(),{icon:icon(true,o),zIndexOffset:SELECTED_MARKER_Z_INDEX}).addTo(map);
  selectedMarker.bindTooltip(esc(o.label_ja||o.label_en||'名称未登録'),{direction:'top',offset:[0,-10]});
  selectedMarker.on('click',()=>selectShiseki(key,'marker'));
}
function detail(o){
  const qid=wikiQID(o);
  const wiki=qid?`https://www.wikidata.org/wiki/${encodeURIComponent(qid)}`:'';
  const wikipediaTitle=o.wikipedia_title||(qid?(o.title_ja||o.label_ja):'');
  const pedia=wikipediaTitle?`https://ja.wikipedia.org/wiki/${encodeURIComponent(wikipediaTitle)}`:'';
  const category=categoryDetailText(o);
  const source=safeUrl(o.designation_source||o.source_url);
  const aboutBody=context.summariesOnly?'要約を読み込んでいます…':o.description?esc(o.description):(qid?'記事の概要を読み込んでいます…':'概要情報は未登録です。');
  const access=!context.summariesOnly&&o.access_note?`<p>${esc(o.access_note)}</p>`:'';
  const sourceName=o.source_name?esc(o.source_name):'';
  const dataset=safeUrl(o.source_url);
  const visit=safeUrl(o.visit_url);
  const licenseUrl={'CC BY 4.0':'https://creativecommons.org/licenses/by/4.0/deed.ja','文化庁 国指定文化財等データベース 利用規約':'https://kunishitei.bunka.go.jp/top/policy'}[o.source_license];
  const license=licenseUrl?`<a href="${licenseUrl}" target="_blank" rel="noopener noreferrer">${o.source_license==='CC BY 4.0'?'CC BY 4.0':'利用規約'}<span aria-hidden="true">↗</span></a>`:'';
  const sourceLinks=`${sourceName&&dataset?`<a href="${esc(dataset)}" target="_blank" rel="noopener noreferrer">${sourceName}（表示用に加工）<span aria-hidden="true">↗</span></a>${license}`:''}${visit?`<a href="${esc(visit)}" target="_blank" rel="noopener noreferrer">現行の訪問案内<span aria-hidden="true">↗</span></a>`:''}`;
  return `<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(o.label_ja||o.label_en||'名称未登録')}</h2>${designationBadge(o)}</header><dl class="detail-facts"><div><dt>所在地</dt><dd id="detail-location">${locationMarkup(o.prefecture||'地域未登録',o)}<span class="location-loading">詳細を確認中…</span></dd></div><div><dt>カテゴリ</dt><dd id="detail-category">${esc(category||'その他')}</dd></div><div><dt>時代</dt><dd>${esc(o.era||'未登録')}</dd></div><div><dt>指定情報</dt><dd>${esc(o.designation_label||designationLabel(designationRank(o)))}${source?` <a href="${esc(source)}" target="_blank" rel="noopener noreferrer">根拠↗</a>`:''}</dd></div></dl><section class="detail-section" aria-labelledby="detail-about"><h3 id="detail-about">概要</h3><p class="detail-description">${aboutBody}</p><p class="detail-description-status"></p></section><section class="detail-section" aria-labelledby="detail-photo"><h3 id="detail-photo">写真</h3><div id="detail-image"><p class="detail-image-status">画像を読み込んでいます…</p></div></section><section class="detail-section" id="detail-history-section" aria-labelledby="detail-history"><h3 id="detail-history">歴史</h3><div class="detail-history" id="detail-history-body"></div><p class="detail-history-status" id="detail-history-status">読み込んでいます…</p></section><section class="detail-section" id="detail-remains-section" aria-labelledby="detail-remains"><h3 id="detail-remains">遺構・見どころ</h3><div class="detail-remains" id="detail-remains-body"></div><p class="detail-remains-status" id="detail-remains-status">読み込んでいます…</p></section><section class="detail-section" id="detail-access-section" aria-labelledby="detail-access"><h3 id="detail-access">アクセス</h3><div class="detail-access" id="detail-access-body">${access}</div><p class="detail-access-status" id="detail-access-status">${visit?'訪問前にリンク先の最新情報をご確認ください。':'読み込んでいます…'}</p></section>${context.summariesOnly?'<section class="detail-section" id="detail-highlights-section" aria-labelledby="detail-highlights"><h3 id="detail-highlights">周辺の見どころ</h3><div id="detail-highlights-body"></div><p id="detail-highlights-status">要約を読み込んでいます…</p></section>':''}<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典・関連情報</h3><nav class="detail-links" id="detail-links" aria-label="出典">${sourceLinks}${wiki?`<a href="${wiki}" target="_blank" rel="noopener noreferrer">Wikidata<span aria-hidden="true">↗</span></a>`:''}${pedia?`<a href="${pedia}" target="_blank" rel="noopener noreferrer">Wikipedia<span aria-hidden="true">↗</span></a>`:''}</nav></section><section class="detail-section detail-affiliate" id="detail-affiliate-section" aria-labelledby="detail-affiliate-heading"><h3 id="detail-affiliate-heading">近くの宿</h3><div class="affiliate" id="detail-affiliate" aria-label="宿泊検索"><p class="detail-affiliate-status">近くの宿を検索しています…</p></div></section></article>`;
}
function selectShiseki(key,origin){
  const entry=markers.get(key);if(!entry)return;selectedKey=key;selectedOrigin=origin;
  showSelectedMarker(key);
  document.querySelectorAll('.shiseki-card').forEach(card=>card.setAttribute('aria-current',String(card.dataset.key===key)));
  if(origin==='list')map.flyTo(entry.marker.getLatLng(),Math.max(map.getZoom(),8),{duration:.55});
  openDetail(entry.shiseki,key,origin);
}
function openDetail(o,key,origin){
  const panel=document.querySelector('#detail-panel'),content=document.querySelector('#detail-content'),originLabel=document.querySelector('#detail-origin');
  panel.hidden=false;document.querySelector('.app-shell').classList.add('has-detail');content.dataset.state='loading';content.innerHTML=detail(o);
  originLabel.textContent=origin==='marker'?'地図から選択':'検索結果から選択';
  const focusTarget=document.querySelector('#detail-title');
  panel.scrollTop=0;
  requestAnimationFrame(()=>{map.invalidateSize();focusTarget?.focus({preventScroll:origin!=='marker'})});
  hydrateImage(o,key);
  hydrateLocation(o,key);
  if(context.summariesOnly)context.hydrateSummary(shisekiKey(o),()=>selectedKey===key);
  else {
  hydrateAbout(o,key);
  hydrateHistory(o,key);
  hydrateRemains(o,key);
  hydrateAccess(o,key);
  hydrateHighlights(o,key);
  }
  hydrateLinks(o,key);
  hydrateNearbyHotels(o,key);
}
async function hydrateNearbyHotels(o,key){
  const hotels=await loadNearbyHotels(o);
  const section=document.querySelector('#detail-affiliate-section');
  const container=document.querySelector('#detail-affiliate');if(!container||!section||selectedKey!==key)return;
  if(hotels===null){section.hidden=true;container.innerHTML='';return}
  section.hidden=false;
  if(!hotels.length){container.innerHTML='<p class="detail-affiliate-status">近くの宿が見つかりませんでした。</p>';return}
  container.innerHTML=affiliateHotelMarkup(hotels);
}
async function hydrateAbout(o,key){
  if(o.description)return;
  const data=await loadWikipediaContent(o);
  if(!data||selectedKey!==key)return;
  const body=document.querySelector('.detail-description'),status=document.querySelector('.detail-description-status');
  if(!body||!status)return;
  const desc=String(data.description||'').trim(),source=safeUrl(data.source_url);
  if(desc.length<10||!source)return;
  body.textContent=desc;
  const license=safeUrl(data.content_license_url);
  status.innerHTML=`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">Wikipedia<span aria-hidden="true">↗</span></a>${license?` · <a href="${esc(license)}" target="_blank" rel="noopener noreferrer">CC BY-SA 4.0<span aria-hidden="true">↗</span></a>`:''} · 編集あり`;
}
async function hydrateWikiSection(o,key,config){
  const section=document.querySelector(config.sectionId);
  if(!section)return;
  const body=document.querySelector(config.bodyId),status=document.querySelector(config.statusId);
  if(!wikiQID(o)&&!o.wikipedia_title){
    if(config.field!=='access'||!o.access_note){
      if(body)body.innerHTML='<p class="detail-empty">情報なし</p>';
      if(status)status.textContent='';
    }
    return;
  }
  const data=await loadWikipediaContent(o);
  if(selectedKey!==key)return;
  const wikiLink=url=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Wikipedia<span aria-hidden="true">↗</span></a>`;
  const ccLink=url=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">CC BY-SA 4.0<span aria-hidden="true">↗</span></a>`;
  if(!data||data.sections_unavailable){
    if(body)body.innerHTML='';
    if(status)status.textContent='読み込みに失敗しました。もう一度開いてください。';
    return;
  }
  const payload=data[config.field]||{};
  const summary=String(payload.summary||'').trim();
  const blocks=Array.isArray(payload.blocks)?payload.blocks:[];
  const source=safeUrl(payload.source_url)||safeUrl(data.source_url);
  const license=safeUrl(data.content_license_url);
  if(!body)return;
  if(!summary&&!blocks.length&&payload.raw_omitted){
    body.innerHTML='<p class="detail-empty">要約はまだありません。</p>';
    if(status)status.innerHTML=source?`原文：${wikiLink(source)}`:'';
    return;
  }
  if(!summary&&!blocks.length){
    body.innerHTML=`<p class="detail-empty">${esc(config.placeholder)}</p>`;
    if(status)status.textContent='';
    return;
  }
  const blockMarkup=blocks.map(b=>{
    const heading=esc(String(b.heading||'')),text=esc(String(b.text||''));
    return (heading?`<p class="detail-subheading">${heading}</p>`:'')+`<p>${text}</p>`;
  }).join('');
  if(summary){
    body.innerHTML=`<p class="detail-summary">${esc(summary)}</p>`+(blocks.length?blockMarkup:'');
    if(status)status.innerHTML='AIによる要約'+(source?` · ${wikiLink(source)}`:'')+(license?` · ${ccLink(license)}`:'');
  }else{
    body.innerHTML=blockMarkup;
    if(status)status.innerHTML=(source?wikiLink(source):'')+(license?`${source?' · ':''}${ccLink(license)}`:'')+' · 編集あり';
  }
}
async function hydrateHistory(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-history-section',bodyId:'#detail-history-body',statusId:'#detail-history-status',field:'history',placeholder:'この記事には歴史の記述がありません。'});
}
async function hydrateRemains(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-remains-section',bodyId:'#detail-remains-body',statusId:'#detail-remains-status',field:'remains',placeholder:'この記事には遺構・見どころの記述がありません。'});
}
async function hydrateAccess(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-access-section',bodyId:'#detail-access-body',statusId:'#detail-access-status',field:'access',placeholder:'この記事にはアクセスの記述がありません。'});
}
async function hydrateHighlights(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-highlights-section',bodyId:'#detail-highlights-body',statusId:'#detail-highlights-status',field:'highlights',placeholder:'この記事には周辺・近隣の観光地に関する記述がありません。'});
}
async function hydrateLocation(o,key){
  const location=await detailedLocation(o),element=document.querySelector('#detail-location');
  if(element&&selectedKey===key)element.innerHTML=locationMarkup(location,o);
}
function closeDetail(restoreFocus=true){
  const key=selectedKey,origin=selectedOrigin;selectedKey=null;selectedOrigin=null;document.querySelector('#detail-panel').hidden=true;document.querySelector('.app-shell').classList.remove('has-detail');
  showSelectedMarker(null);document.querySelectorAll('.shiseki-card').forEach(card=>card.setAttribute('aria-current','false'));
  requestAnimationFrame(()=>map.invalidateSize());
  if(restoreFocus&&key){
    const target=origin==='marker'?document.querySelector('#map'):document.querySelector(`.shiseki-card[data-key="${CSS.escape(key)}"]`);
    target?.focus();
  }
}
async function hydrateImage(o,key){
  const [wikipediaContent]=await Promise.all([loadWikipediaContent(o)]);
  const cacheKey=shisekiKey(o),qid=wikiQID(o);
  let result=imageCache[cacheKey]||null,loadError=null;
  if(typeof result==='string'||(result?.url&&!result.license)){delete imageCache[cacheKey];persist(CACHE_KEY,imageCache);result=null}
  if(!result&&wikipediaContent?.image_url){result={url:safeUrl(wikipediaContent.image_url),license:String(wikipediaContent.license||'').trim(),licenseUrl:safeUrl(wikipediaContent.license_url),artist:plainText(wikipediaContent.artist),credit:plainText(wikipediaContent.credit),sourceUrl:safeUrl(wikipediaContent.image_source_url)};imageCache[cacheKey]=result;persist(CACHE_KEY,imageCache)}
  if(!result&&qid){
    try{const data=await fetchJSONWithRetry(`/api/wiki/image?qid=${encodeURIComponent(qid)}`);if(data&&data.url){result={url:safeUrl(data.url),license:String(data.license||'').trim(),licenseUrl:safeUrl(data.license_url),sourceUrl:safeUrl(data.source_url),artist:plainText(data.artist),credit:plainText(data.credit)};imageCache[cacheKey]=result;persist(CACHE_KEY,imageCache)}}
    catch(error){loadError=error}
  }
  const container=document.querySelector('#detail-image'),content=document.querySelector('#detail-content');if(!container||selectedKey!==key)return;
  if(!result?.url){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">表示できる画像が登録されていません。</p>';return}
  if(!result.license){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">画像のライセンス情報を確認できないため、表示していません。</p>';return}
  const source=result.sourceUrl||commonsFilePage(result.url);
  const license=result.licenseUrl?`<a href="${esc(result.licenseUrl)}" target="_blank" rel="noopener noreferrer" aria-label="ライセンス ${esc(result.license)}">${esc(result.license)}<span aria-hidden="true">↗</span></a>`:esc(result.license);
  const creator=result.artist||result.credit;
  content.dataset.state='success';container.innerHTML=`<button class="detail-image-button" type="button" aria-label="${esc(o.label_ja||'史跡')}の画像を拡大"><img class="detail-image" src="${esc(result.url)}" alt="${esc(o.label_ja||'史跡')}の画像"></button><p class="license">${creator?`${esc(creator)} · `:''}${license}${source?` · <a href="${esc(source)}" target="_blank" rel="noopener noreferrer" aria-label="Wikimedia Commonsの画像出典">Commons<span aria-hidden="true">↗</span></a>`:''}</p>`;
  container.querySelector('button').addEventListener('click',()=>openLightbox(result.url,o.label_ja));
}
async function hydrateLinks(o,key){
  const qid=wikiQID(o);
  if(!qid)return;
  let links=linksCache[qid];
  if(!links){
    try{
      const data=await fetchJSONWithRetry(`/api/wiki/links?qid=${encodeURIComponent(qid)}`);
      links={officialSite:safeUrl(data.official_site),officialSiteSource:data.official_site_source||'',facebook:safeUrl(data.facebook),twitter:safeUrl(data.twitter),instagram:safeUrl(data.instagram),youtube:safeUrl(data.youtube)};
      linksCache[qid]=links;persist(LINKS_CACHE_KEY,linksCache);
    }catch(error){links={}}
  }
  const nav=document.querySelector('#detail-links');if(!nav||selectedKey!==key)return;
  const officialLabel=links.officialSiteSource==='wikipedia'?'公式サイト（Wikipedia）':'公式サイト';
  const extra=[
    links.officialSite?`<a href="${esc(links.officialSite)}" target="_blank" rel="noopener noreferrer">${officialLabel}<span aria-hidden="true">↗</span></a>`:'',
    links.facebook?`<a href="${esc(links.facebook)}" target="_blank" rel="noopener noreferrer">Facebook<span aria-hidden="true">↗</span></a>`:'',
    links.twitter?`<a href="${esc(links.twitter)}" target="_blank" rel="noopener noreferrer">X (Twitter)<span aria-hidden="true">↗</span></a>`:'',
    links.instagram?`<a href="${esc(links.instagram)}" target="_blank" rel="noopener noreferrer">Instagram<span aria-hidden="true">↗</span></a>`:'',
    links.youtube?`<a href="${esc(links.youtube)}" target="_blank" rel="noopener noreferrer">YouTube<span aria-hidden="true">↗</span></a>`:'',
  ].join('');
  if(extra)nav.insertAdjacentHTML('afterbegin',extra);
}
function openLightbox(url,alt){const dialog=document.querySelector('#lightbox'),image=document.querySelector('#lightbox-image');image.src=url;image.alt=`${alt||'史跡'}の拡大画像`;dialog.showModal()}
function closeLightbox(){const dialog=document.querySelector('#lightbox');if(dialog.open)dialog.close();document.querySelector('#lightbox-image').src=''}

document.querySelector('#keyword').addEventListener('input',applyFilters);
document.querySelector('#prefecture').addEventListener('change',applyFilters);
for(const id of MULTI_FILTERS)document.querySelector(`#${id}-options`).addEventListener('change',()=>{updateMultiSummary(id);applyFilters()});
document.querySelector('#clear-filters').addEventListener('click',()=>{for(const id of ['keyword','prefecture'])document.querySelector(`#${id}`).value='';MULTI_FILTERS.forEach(clearMultiFilter);applyFilters();document.querySelector('#keyword').focus()});
document.querySelector('.detail-close').addEventListener('click',()=>closeDetail());
document.querySelector('.lightbox-close').addEventListener('click',closeLightbox);
document.querySelector('#lightbox').addEventListener('click',event=>{if(event.target.id==='lightbox')closeLightbox()});

fetch('/api/shiseki/').then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}).then(data=>{shisekis=Array.isArray(data)?data:[];populatePrefectures();populateCategories();populateEras();applyFilters()}).catch(error=>{console.error('Shiseki data could not be loaded',error);document.querySelector('#shiseki-list').innerHTML='<p class="empty-state">史跡の情報を読み込めませんでした。時間をおいて再度お試しください。</p>';document.querySelector('#map-count').textContent='読み込み失敗'});
}
