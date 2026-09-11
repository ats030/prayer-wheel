const map=L.map('map').setView([36.2,138.2],5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);

const CACHE_KEY='omatsuri-map-image-cache-v1';
const GEOCODING_CACHE_KEY='omatsuri-map-geocoding-cache-v1';
const imageCache={};
const geocodingCache={};
const geocodingCacheQueue={};
let festivals=[];
let visible=[];
let markers=new Map();
let selectedKey=null;
const saveTimers={};

for(const [key,target] of [[CACHE_KEY,imageCache],[GEOCODING_CACHE_KEY,geocodingCache]]){
  try{Object.assign(target,JSON.parse(localStorage.getItem(key)||'{}'))}
  catch(error){console.warn(`Cache ${key} could not be loaded`,error)}
}

function persist(key,value){
  clearTimeout(saveTimers[key]);
  saveTimers[key]=setTimeout(()=>{try{localStorage.setItem(key,JSON.stringify(value))}catch(error){console.warn(`Cache ${key} could not be saved`,error)}},500);
}
function festivalKey(f,index=0){return f.qid||`${f.label_ja}-${f.latitude}-${f.longitude}-${index}`}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:''}catch{return''}}
function parseRange(value){
  if(!value||value==='日付未定')return{};
  const parts=value.split(/[〜～]/),valid=s=>/^\d{4}-\d{2}-\d{2}$/.test(s);
  const endValue=parts[1]||parts[0];
  return{start:valid(parts[0])?new Date(`${parts[0]}T00:00:00`):null,end:valid(endValue)?new Date(`${endValue}T23:59:59`):null};
}
function matchesDate(f,value){
  if(!value)return true;
  const target=new Date(`${value}T12:00:00`),{start,end}=parseRange(f.date);
  return Boolean(start&&end&&target>=start&&target<=end);
}
function populatePrefectures(){
  const select=document.querySelector('#prefecture');
  [...new Set(festivals.map(f=>f.prefecture).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja')).forEach(p=>select.add(new Option(p,p)));
}
function applyFilters(){
  const q=document.querySelector('#keyword').value.trim().toLocaleLowerCase('ja');
  const prefecture=document.querySelector('#prefecture').value;
  const date=document.querySelector('#festival-date').value;
  visible=festivals.filter(f=>{
    const text=[f.label_ja,f.label_en,f.prefecture,f.description].filter(Boolean).join(' ').toLocaleLowerCase('ja');
    return text.includes(q)&&(!prefecture||f.prefecture===prefecture)&&matchesDate(f,date);
  });
  renderList();renderMarkers();
  document.querySelector('#result-count').textContent=visible.length;
  document.querySelector('#map-count').textContent=`地図上に ${visible.length} 件`;
}
function renderList(){
  const list=document.querySelector('#festival-list');
  if(!visible.length){list.innerHTML='<p class="empty-state">条件に合う祭りがありません。日付や地域を変えてお試しください。</p>';return}
  list.innerHTML=visible.map((f,index)=>{
    const key=festivalKey(f,index);
    return `<button class="festival-card" type="button" data-key="${esc(key)}" aria-current="${key===selectedKey}"><span class="card-index">${String(index+1).padStart(2,'0')}</span><span><span class="card-name">${esc(f.label_ja||f.label_en||'名称未登録')}</span><span class="card-meta"><span>${esc(f.prefecture||'地域未登録')}</span><span>${esc(f.date||'日付未定')}</span></span></span></button>`;
  }).join('');
  list.querySelectorAll('button').forEach(card=>card.addEventListener('click',()=>selectFestival(card.dataset.key,true)));
}
function icon(selected){return L.divIcon({className:'',html:`<span class="festival-marker${selected?' selected':''}"></span>`,iconSize:[22,22],iconAnchor:[11,11],popupAnchor:[0,-12]})}
function renderMarkers(){
  markers.forEach(({marker})=>map.removeLayer(marker));markers=new Map();
  visible.forEach((f,index)=>{
    if(!Number.isFinite(Number(f.latitude))||!Number.isFinite(Number(f.longitude)))return;
    const key=festivalKey(f,index),marker=L.marker([Number(f.latitude),Number(f.longitude)],{icon:icon(key===selectedKey)}).addTo(map);
    marker.bindTooltip(esc(f.label_ja||f.label_en||'名称未登録'),{direction:'top',offset:[0,-10]});
    marker.on('click',()=>selectFestival(key,false));markers.set(key,{marker,festival:f});
  });
  if(selectedKey&&!markers.has(selectedKey))closeDetail(false);
}
function detail(f){
  const wiki=f.qid?`https://www.wikidata.org/wiki/${encodeURIComponent(f.qid)}`:'';
  const pedia=f.label_ja?`https://ja.wikipedia.org/wiki/${encodeURIComponent(f.label_ja)}`:'';
  const culture=safeUrl(f.cultural_relaw?.url);
  return `<article class="detail"><h2 id="detail-title" tabindex="-1">${esc(f.label_ja||f.label_en||'名称未登録')}</h2><p class="detail-meta">${esc(f.prefecture||'地域未登録')} · ${esc(f.date||'日付未定')}</p>${f.description?`<p class="detail-description">${esc(f.description)}</p>`:''}<nav class="detail-links" aria-label="出典">${wiki?`<a href="${wiki}" target="_blank" rel="noopener noreferrer">Wikidata</a>`:''}${pedia?`<a href="${pedia}" target="_blank" rel="noopener noreferrer">Wikipedia</a>`:''}${culture?`<a href="${esc(culture)}" target="_blank" rel="noopener noreferrer">文化庁</a>`:''}</nav><div id="detail-image"><p class="detail-image-status">画像を読み込んでいます…</p></div></article>`;
}
function selectFestival(key,move){
  const entry=markers.get(key);if(!entry)return;selectedKey=key;
  markers.forEach(({marker},markerKey)=>marker.setIcon(icon(markerKey===key)));
  document.querySelectorAll('.festival-card').forEach(card=>card.setAttribute('aria-current',String(card.dataset.key===key)));
  const card=document.querySelector(`.festival-card[data-key="${CSS.escape(key)}"]`);
  if(!move&&card)card.scrollIntoView({behavior:'smooth',block:'nearest'});
  if(move)map.flyTo(entry.marker.getLatLng(),Math.max(map.getZoom(),8),{duration:.55});
  openDetail(entry.festival,key);
}
function openDetail(f,key){
  const panel=document.querySelector('#detail-panel'),content=document.querySelector('#detail-content');
  panel.hidden=false;document.querySelector('.app-shell').classList.add('has-detail');content.dataset.state='loading';content.innerHTML=detail(f);
  requestAnimationFrame(()=>{map.invalidateSize();document.querySelector('#detail-title')?.focus({preventScroll:true})});
  hydrateImage(f,key);
}
function closeDetail(restoreFocus=true){
  const key=selectedKey;selectedKey=null;document.querySelector('#detail-panel').hidden=true;document.querySelector('.app-shell').classList.remove('has-detail');
  markers.forEach(({marker})=>marker.setIcon(icon(false)));document.querySelectorAll('.festival-card').forEach(card=>card.setAttribute('aria-current','false'));
  requestAnimationFrame(()=>map.invalidateSize());
  if(restoreFocus&&key){document.querySelector(`.festival-card[data-key="${CSS.escape(key)}"]`)?.focus()}
}
async function hydrateImage(f,key){
  let result=imageCache[f.qid];if(typeof result==='string')result={url:result};
  if(!result&&f.qid){
    try{const response=await fetch(`/api/wiki/image?qid=${encodeURIComponent(f.qid)}`);if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();result={url:safeUrl(data.url),license:data.license};imageCache[f.qid]=result;persist(CACHE_KEY,imageCache)}
    catch(error){console.warn(`Image could not be loaded for ${f.qid}`,error)}
  }
  const container=document.querySelector('#detail-image'),content=document.querySelector('#detail-content');if(!container||selectedKey!==key)return;
  if(!result?.url){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">画像を読み込めませんでした。</p>';return}
  content.dataset.state='success';container.innerHTML=`<img class="detail-image" src="${esc(result.url)}" alt="${esc(f.label_ja||'祭り')}の画像">${result.license?`<p class="license">License: ${esc(result.license)}</p>`:''}`;
  container.querySelector('img').addEventListener('click',()=>openLightbox(result.url,f.label_ja));
}
function openLightbox(url,alt){const dialog=document.querySelector('#lightbox'),image=document.querySelector('#lightbox-image');image.src=url;image.alt=`${alt||'祭り'}の拡大画像`;dialog.showModal()}
function closeLightbox(){const dialog=document.querySelector('#lightbox');if(dialog.open)dialog.close();document.querySelector('#lightbox-image').src=''}

document.querySelector('#keyword').addEventListener('input',applyFilters);
document.querySelector('#prefecture').addEventListener('change',applyFilters);
document.querySelector('#festival-date').addEventListener('change',applyFilters);
document.querySelector('#clear-filters').addEventListener('click',()=>{document.querySelector('#keyword').value='';document.querySelector('#prefecture').value='';document.querySelector('#festival-date').value='';applyFilters();document.querySelector('#keyword').focus()});
document.querySelector('.detail-close').addEventListener('click',()=>closeDetail());
document.querySelector('.lightbox-close').addEventListener('click',closeLightbox);
document.querySelector('#lightbox').addEventListener('click',event=>{if(event.target.id==='lightbox')closeLightbox()});

fetch('/festivals.json').then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}).then(data=>{festivals=Array.isArray(data)?data:[];populatePrefectures();applyFilters()}).catch(error=>{console.error('Festival data could not be loaded',error);document.querySelector('#festival-list').innerHTML='<p class="empty-state">祭りの情報を読み込めませんでした。時間をおいて再度お試しください。</p>';document.querySelector('#map-count').textContent='読み込み失敗'});

window.renderMapMarkers=(items,targetDate=null)=>{festivals=Array.isArray(items)?items:festivals;if(targetDate instanceof Date&&!Number.isNaN(targetDate.valueOf()))document.querySelector('#festival-date').value=targetDate.toISOString().slice(0,10);applyFilters()};
window.geocodingCacheQueue=geocodingCacheQueue;
window.saveGeocodingCache=()=>persist(GEOCODING_CACHE_KEY,geocodingCache);
