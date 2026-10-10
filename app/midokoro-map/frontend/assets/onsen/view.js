export function mount(context) {
const {map, document, fetch} = context;

const CACHE_KEY='midokoro-map-onsen-image-cache-v1';
const GEOCODING_CACHE_KEY='midokoro-map-onsen-geocoding-cache-v1';
const LINKS_CACHE_KEY='midokoro-map-onsen-links-cache-v1';
const JALAN_CACHE_KEY='midokoro-map-onsen-jalan-cache-v1';
const SELECTED_MARKER_Z_INDEX=10000;
const imageCache={};
const wikiContentCache={};
const wikiContentQueue={};
const geocodingCache={};
const geocodingCacheQueue={};
const linksCache={};
const jalanCache={};
const jalanCacheQueue={};
let onsens=[];
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
function onsenKey(o,index=0){return o.qid||`${o.label_ja}-${o.latitude}-${o.longitude}-${index}`}
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
function springTags(o){
  const list=Array.isArray(o.spring_types)?o.spring_types:[];
  if(list.length)return list;
  return String(o.spring_type||'').split(/[、・,]/).map(s=>s.trim()).filter(Boolean);
}
function springText(o){return springTags(o).join('・')}
function springDetailText(o){
  if(springTags(o).length)return springTags(o).join('・');
  if(o.spring_type_raw)return `未分類 (${o.spring_type_raw})`;
  return '';
}
function springSourceNote(o){
  if(springTags(o).length)return'';
  if(o.spring_type_source==='inline')return'記事本文より';
  if(o.spring_type_source==='heading')return'記事の泉質欄より';
  return '';
}
function operatingStatus(o){
  const value=String(o.operating_status||'').trim().toLowerCase();
  return ['open','closed','unknown'].includes(value)?value:'unknown';
}
function operatingStatusLabel(status){
  if(status==='open')return'営業中';
  if(status==='closed')return'閉鎖・休止';
  return'営業状況不明';
}
function statusBadge(o){
  const status=operatingStatus(o);
  const note=String(o.operating_status_note||'').trim();
  return `<p class="status-line"><span class="status-badge status-badge--${status}" role="note">${operatingStatusLabel(status)}</span>${note?`<span class="status-note">${esc(note)}</span>`:''}</p>`;
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
  const delays=[500,1500];
  let lastError;
  for(let attempt=0;attempt<=delays.length;attempt++){
    try{const response=await fetch(url);if(response.ok)return response.json();lastError=new Error(`HTTP ${response.status}`)}catch(error){lastError=error}
    if(attempt<delays.length)await new Promise(resolve=>setTimeout(resolve,delays[attempt]));
  }
  throw lastError;
}
const WIKI_SECTIONS_RETRY_MS=60000;
async function loadWikipediaContent(o){
  const title=o.wikipedia_title||o.title_ja||o.label_ja;if(!title)return null;
  const cacheKey=`${o.qid||''}:${title}`;
  const cached=wikiContentCache[cacheKey];
  // A transient sections failure is cached too (so re-opening the panel does
  // not re-issue every Wikimedia request for this onsen), but only for a
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
  if(embedded)return [o.prefecture,embedded].filter((value,index,items)=>value&&items.indexOf(value)===index).join(' ');
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
  [...new Set(onsens.map(o=>o.prefecture).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja')).forEach(p=>select.add(new Option(p,p)));
}
function populateSpringTypes(){
  document.querySelector('#spring-type-options').innerHTML=[...new Set(onsens.flatMap(o=>springTags(o)))].sort((a,b)=>a.localeCompare(b,'ja')).map(p=>`<label class="multi-option"><input type="checkbox" value="${esc(p)}">${esc(p)}</label>`).join('');
}
function selectedSpringTypes(){return [...document.querySelectorAll('#spring-type-options input:checked')].map(input=>input.value)}
function updateSpringTypeSummary(){const labels=selectedSpringTypes();document.querySelector('#spring-type-summary').textContent=!labels.length?'すべて':labels.length===1?labels[0]:`${labels[0]} ほか${labels.length-1}`}
function clearSpringTypes(){document.querySelectorAll('#spring-type-options input').forEach(input=>{input.checked=false});updateSpringTypeSummary()}
function applyFilters(){
  const q=document.querySelector('#keyword').value.trim().toLocaleLowerCase('ja');
  const prefecture=document.querySelector('#prefecture').value;
  const springTypes=selectedSpringTypes();
  visible=onsens.filter(o=>{
    const tags=springTags(o);
    const text=[o.label_ja,o.label_en,o.prefecture,o.description,...tags].filter(Boolean).join(' ').toLocaleLowerCase('ja');
    const prefectureMatches=!prefecture||(o.prefecture===prefecture);
    const springTypeMatches=!springTypes.length||tags.some(tag=>springTypes.includes(tag));
    return text.includes(q)&&prefectureMatches&&springTypeMatches;
  }).sort((a,b)=>String(a.label_ja||a.label_en||'').localeCompare(String(b.label_ja||b.label_en||''),'ja'));
  renderList();renderMarkers();
  document.querySelector('#result-count').textContent=visible.length;
  document.querySelector('#map-count').textContent=`地図上に ${visible.length} 件`;
}
function renderList(){
  const list=document.querySelector('#onsen-list');
  if(!visible.length){list.innerHTML='<p class="empty-state">条件に合う温泉がありません。地域を変えてお試しください.</p>';return}
  list.innerHTML=visible.map((o,index)=>{
    const key=onsenKey(o,index);
    const springType=springText(o);
    return `<button class="onsen-card" type="button" data-key="${esc(key)}" aria-current="${key===selectedKey}"><span class="card-index">${String(index+1).padStart(2,'0')}</span><span><span class="card-name">${esc(o.label_ja||o.label_en||'名称未登録')}</span><span class="card-meta"><span>${esc(o.prefecture||'地域未登録')}</span>${springType?`<span>${esc(springType)}</span>`:''}</span></span></button>`;
  }).join('');
  list.querySelectorAll('button').forEach(card=>card.addEventListener('click',()=>selectOnsen(card.dataset.key,'list')));
}
function icon(selected,onsen){return L.divIcon({className:'',html:`<span class="onsen-marker${selected?' selected':''} status-${operatingStatus(onsen)}"></span>`,iconSize:[22,22],iconAnchor:[11,11],popupAnchor:[0,-12]})}
// Thousands of DOM markers make panning slow, so unselected points are drawn on
// the shared canvas and only the selected point keeps the DOM icon.
const markerLayer=L.layerGroup().addTo(map);
let markerColors={};
// Colours live in app.css; read them from a probe so the canvas matches the icon.
function markerStyle(o){
  const status=operatingStatus(o);
  if(!markerColors[status]){
    const probe=document.createElement('span');probe.className=`onsen-marker status-${status}`;probe.style.visibility='hidden';probe.style.position='absolute';
    document.body.appendChild(probe);const css=getComputedStyle(probe);markerColors[status]={fill:css.backgroundColor,stroke:css.borderTopColor};probe.remove();
  }
  const {fill,stroke}=markerColors[status];
  return {radius:9,weight:2,color:stroke,fillColor:fill,fillOpacity:1};
}
function renderMarkers(){
  markerLayer.clearLayers();markers=new Map();markerColors={};
  visible.forEach((o,index)=>{
    const point=mapCoordinates(o);if(!point)return;
    const key=onsenKey(o,index),latlng=[point.latitude,point.longitude],style=markerStyle(o);
    const marker=L.circleMarker(latlng,style).addTo(markerLayer);
    L.circleMarker(latlng,{radius:2.5,stroke:false,fillColor:style.color,fillOpacity:1,interactive:false}).addTo(markerLayer);
    marker.bindTooltip(esc(o.label_ja||o.label_en||'名称未登録'),{direction:'top',offset:[0,-10]});
    marker.on('click',()=>selectOnsen(key,'marker'));markers.set(key,{marker,onsen:o});
  });
  if(selectedKey&&!markers.has(selectedKey))closeDetail(false);else showSelectedMarker(selectedKey);
}
function showSelectedMarker(key){
  if(selectedMarker){map.removeLayer(selectedMarker);selectedMarker=null}
  const entry=key&&markers.get(key);if(!entry)return;
  const o=entry.onsen;
  selectedMarker=L.marker(entry.marker.getLatLng(),{icon:icon(true,o),zIndexOffset:SELECTED_MARKER_Z_INDEX}).addTo(map);
  selectedMarker.bindTooltip(esc(o.label_ja||o.label_en||'名称未登録'),{direction:'top',offset:[0,-10]});
  selectedMarker.on('click',()=>selectOnsen(key,'marker'));
}
function detail(o){
  const wiki=o.qid?`https://www.wikidata.org/wiki/${encodeURIComponent(o.qid)}`:'';
  const wikipediaTitle=o.wikipedia_title||o.title_ja||o.label_ja;
  const pedia=wikipediaTitle?`https://ja.wikipedia.org/wiki/${encodeURIComponent(wikipediaTitle)}`:'';
  const springType=springDetailText(o);
  const springNote=springSourceNote(o);
  const aboutBody=context.summariesOnly?'要約を読み込んでいます…':o.description?esc(o.description):'記事の概要を読み込んでいます…';
  return `<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(o.label_ja||o.label_en||'名称未登録')}</h2>${statusBadge(o)}</header><dl class="detail-facts"><div><dt>所在地</dt><dd id="detail-location">${locationMarkup(o.prefecture||'地域未登録',o)}<span class="location-loading">詳細を確認中…</span></dd></div><div><dt>泉質</dt><dd id="detail-spring">${springType?esc(springType):'未登録'}${springNote?` <span class="source-note">${esc(springNote)}</span>`:''}</dd></div></dl><section class="detail-section" aria-labelledby="detail-about"><h3 id="detail-about">温泉について</h3><p class="detail-description">${aboutBody}</p><p class="detail-description-status"></p></section><section class="detail-section" aria-labelledby="detail-photo"><h3 id="detail-photo">写真</h3><div id="detail-image"><p class="detail-image-status">画像を読み込んでいます…</p></div></section><section class="detail-section" id="detail-efficacy-section" aria-labelledby="detail-efficacy"><h3 id="detail-efficacy">効能</h3><div class="detail-efficacy" id="detail-efficacy-body"></div><p class="detail-efficacy-status" id="detail-efficacy-status">読み込んでいます…</p></section><section class="detail-section" id="detail-history-section" aria-labelledby="detail-history"><h3 id="detail-history">歴史</h3><div class="detail-history" id="detail-history-body"></div><p class="detail-history-status" id="detail-history-status">読み込んでいます…</p></section><section class="detail-section" id="detail-food-section" aria-labelledby="detail-food"><h3 id="detail-food">名物</h3><div class="detail-food" id="detail-food-body"></div><p class="detail-food-status" id="detail-food-status">読み込んでいます…</p></section><section class="detail-section" id="detail-access-section" aria-labelledby="detail-access"><h3 id="detail-access">アクセス</h3><div class="detail-access" id="detail-access-body"></div><p class="detail-access-status" id="detail-access-status">読み込んでいます…</p></section><section class="detail-section" id="detail-tourism-section" aria-labelledby="detail-tourism"><h3 id="detail-tourism">観光</h3><div class="detail-tourism" id="detail-tourism-body"></div><p class="detail-tourism-status" id="detail-tourism-status">読み込んでいます…</p></section><section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典・関連情報</h3><nav class="detail-links" id="detail-links" aria-label="出典">${wiki?`<a href="${wiki}" target="_blank" rel="noopener noreferrer">Wikidata<span aria-hidden="true">↗</span></a>`:''}${pedia?`<a href="${pedia}" target="_blank" rel="noopener noreferrer">Wikipedia<span aria-hidden="true">↗</span></a>`:''}</nav></section><section class="detail-section detail-affiliate" id="detail-affiliate-section" aria-labelledby="detail-affiliate-heading"><h3 id="detail-affiliate-heading">近くの宿</h3><div class="affiliate" id="detail-affiliate" aria-label="宿泊検索"><p class="detail-affiliate-status">近くの宿を検索しています…</p></div></section></article>`;
}
function selectOnsen(key,origin){
  const entry=markers.get(key);if(!entry)return;selectedKey=key;selectedOrigin=origin;
  showSelectedMarker(key);
  document.querySelectorAll('.onsen-card').forEach(card=>card.setAttribute('aria-current',String(card.dataset.key===key)));
  if(origin==='list')map.flyTo(entry.marker.getLatLng(),Math.max(map.getZoom(),8),{duration:.55});
  openDetail(entry.onsen,key,origin);
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
  if(context.summariesOnly)context.hydrateSummary(o.qid,()=>selectedKey===key);
  else {
  hydrateAbout(o,key);
  hydrateHistory(o,key);
  hydrateFood(o,key);
  hydrateEfficacy(o,key);
  hydrateAccess(o,key);
  hydrateTourism(o,key);
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
  const items=Array.isArray(payload.items)?payload.items:[];
  const source=safeUrl(payload.source_url)||safeUrl(data.source_url);
  // Set only when the server filled this section from the municipality
  // article because the onsen article had nothing; always say so up front.
  const sourceTitle=String(payload.source_title||'').trim();
  const license=safeUrl(data.content_license_url);
  if(!body)return;
  if(!summary&&!items.length){
    section.hidden=true;
    body.innerHTML='';
    if(status)status.textContent='';
    return;
  }
  const renderItem=item=>{
    const label=String(item.label||'').trim();
    const value=String(item.value||'').trim();
    const from=String(item.from||'').trim();
    const to=String(item.to||'').trim();
    const bodyText=[from&&to?`${from} → ${to}`:'',value].filter(Boolean).join(' ');
    return `<div><dt>${esc(label)}</dt><dd>${esc(bodyText)}</dd></div>`;
  };
  const itemsMarkup=items.map(renderItem).join('');
  const bodyParts=[
    sourceTitle?`<p class="detail-origin">${esc(sourceTitle)}の記事より</p>`:'',
    summary?`<p class="detail-summary">${esc(summary)}</p>`:'',
    items.length?`<dl class="section-items">${itemsMarkup}</dl>`:'',
  ].filter(Boolean).join('');
  body.innerHTML=bodyParts;
  const attribution=[];
  if(summary){
    attribution.push('AIによる要約');
  }else{
    attribution.push('編集あり');
  }
  if(source)attribution.push(wikiLink(source));
  if(license)attribution.push(ccLink(license));
  if(status)status.innerHTML=attribution.join(' · ');
}
async function hydrateHistory(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-history-section',bodyId:'#detail-history-body',statusId:'#detail-history-status',field:'history'});
}
async function hydrateFood(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-food-section',bodyId:'#detail-food-body',statusId:'#detail-food-status',field:'food'});
}
async function hydrateEfficacy(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-efficacy-section',bodyId:'#detail-efficacy-body',statusId:'#detail-efficacy-status',field:'efficacy'});
}
async function hydrateAccess(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-access-section',bodyId:'#detail-access-body',statusId:'#detail-access-status',field:'access'});
}
async function hydrateTourism(o,key){
  await hydrateWikiSection(o,key,{sectionId:'#detail-tourism-section',bodyId:'#detail-tourism-body',statusId:'#detail-tourism-status',field:'tourism'});
}
async function hydrateLocation(o,key){
  const location=await detailedLocation(o),element=document.querySelector('#detail-location');
  if(element&&selectedKey===key)element.innerHTML=locationMarkup(location,o);
}
function closeDetail(restoreFocus=true){
  const key=selectedKey,origin=selectedOrigin;selectedKey=null;selectedOrigin=null;document.querySelector('#detail-panel').hidden=true;document.querySelector('.app-shell').classList.remove('has-detail');
  showSelectedMarker(null);document.querySelectorAll('.onsen-card').forEach(card=>card.setAttribute('aria-current','false'));
  requestAnimationFrame(()=>map.invalidateSize());
  if(restoreFocus&&key){
    const target=origin==='marker'?document.querySelector('#map'):document.querySelector(`.onsen-card[data-key="${CSS.escape(key)}"]`);
    target?.focus();
  }
}
async function hydrateImage(o,key){
  const [wikipediaContent]=await Promise.all([loadWikipediaContent(o)]);
  let result=imageCache[o.qid]||null,loadError=null;
  if(typeof result==='string'||(result?.url&&!result.license)){delete imageCache[o.qid];persist(CACHE_KEY,imageCache);result=null}
  if(!result&&wikipediaContent?.image_url){result={url:safeUrl(wikipediaContent.image_url),license:String(wikipediaContent.license||'').trim(),licenseUrl:safeUrl(wikipediaContent.license_url),artist:plainText(wikipediaContent.artist),credit:plainText(wikipediaContent.credit),sourceUrl:safeUrl(wikipediaContent.image_source_url)};imageCache[o.qid]=result;persist(CACHE_KEY,imageCache)}
  if(!result&&o.qid){
    try{const data=await fetchJSONWithRetry(`/api/wiki/image?qid=${encodeURIComponent(o.qid)}`);if(data&&data.url){result={url:safeUrl(data.url),license:String(data.license||'').trim(),licenseUrl:safeUrl(data.license_url),artist:plainText(data.artist),credit:plainText(data.credit),sourceUrl:safeUrl(data.source_url)};imageCache[o.qid]=result;persist(CACHE_KEY,imageCache)}}
    catch(error){loadError=error}
  }
  const container=document.querySelector('#detail-image'),content=document.querySelector('#detail-content');if(!container||selectedKey!==key)return;
  if(!result?.url){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">表示できる画像が登録されていません。</p>';return}
  if(!result.license){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">画像のライセンス情報を確認できないため、表示していません。</p>';return}
  const source=result.sourceUrl||commonsFilePage(result.url);
  const license=result.licenseUrl?`<a href="${esc(result.licenseUrl)}" target="_blank" rel="noopener noreferrer" aria-label="ライセンス ${esc(result.license)}">${esc(result.license)}<span aria-hidden="true">↗</span></a>`:esc(result.license);
  const creator=result.artist||result.credit;
  content.dataset.state='success';container.innerHTML=`<button class="detail-image-button" type="button" aria-label="${esc(o.label_ja||'温泉')}の画像を拡大"><img class="detail-image" src="${esc(result.url)}" alt="${esc(o.label_ja||'温泉')}の画像"></button><p class="license">${creator?`${esc(creator)} · `:''}${license}${source?` · <a href="${esc(source)}" target="_blank" rel="noopener noreferrer" aria-label="Wikimedia Commonsの画像出典">Commons<span aria-hidden="true">↗</span></a>`:''}</p>`;
  container.querySelector('button').addEventListener('click',()=>openLightbox(result.url,o.label_ja));
}
async function hydrateLinks(o,key){
  if(!o.qid)return;
  let links=linksCache[o.qid];
  if(!links){
    try{
      const data=await fetchJSONWithRetry(`/api/wiki/links?qid=${encodeURIComponent(o.qid)}`);
      links={officialSite:safeUrl(data.official_site),officialSiteSource:data.official_site_source||'',facebook:safeUrl(data.facebook),twitter:safeUrl(data.twitter),instagram:safeUrl(data.instagram),youtube:safeUrl(data.youtube)};
      linksCache[o.qid]=links;persist(LINKS_CACHE_KEY,linksCache);
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
function openLightbox(url,alt){const dialog=document.querySelector('#lightbox'),image=document.querySelector('#lightbox-image');image.src=url;image.alt=`${alt||'温泉'}の拡大画像`;dialog.showModal()}
function closeLightbox(){const dialog=document.querySelector('#lightbox');if(dialog.open)dialog.close();document.querySelector('#lightbox-image').src=''}

document.querySelector('#keyword').addEventListener('input',applyFilters);
document.querySelector('#prefecture').addEventListener('change',applyFilters);
document.querySelector('#spring-type-options').addEventListener('change',()=>{updateSpringTypeSummary();applyFilters()});
document.querySelector('#clear-filters').addEventListener('click',()=>{document.querySelector('#keyword').value='';document.querySelector('#prefecture').value='';clearSpringTypes();applyFilters();document.querySelector('#keyword').focus()});
document.querySelector('.detail-close').addEventListener('click',()=>closeDetail());
document.querySelector('.lightbox-close').addEventListener('click',closeLightbox);
document.querySelector('#lightbox').addEventListener('click',event=>{if(event.target.id==='lightbox')closeLightbox()});

fetch('/api/onsen/').then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}).then(data=>{onsens=Array.isArray(data)?data:[];populatePrefectures();populateSpringTypes();applyFilters()}).catch(error=>{console.error('Onsen data could not be loaded',error);document.querySelector('#onsen-list').innerHTML='<p class="empty-state">温泉の情報を読み込めませんでした。時間をおいて再度お試しください。</p>';document.querySelector('#map-count').textContent='読み込み失敗'});
}
