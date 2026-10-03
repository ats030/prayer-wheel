const map=L.map('map',{preferCanvas:true}).setView([36.2,138.2],5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);

const CACHE_KEY='omatsuri-map-image-cache-v5';
const GEOCODING_CACHE_KEY='omatsuri-map-geocoding-cache-v1';
const LINKS_CACHE_KEY='omatsuri-map-links-cache-v1';
const JALAN_CACHE_KEY='omatsuri-map-jalan-cache-v1';
const SELECTED_MARKER_Z_INDEX=10000;
const imageCache={};
const wikiContentCache={};
const wikiContentQueue={};
const geocodingCache={};
const geocodingCacheQueue={};
const linksCache={};
const jalanCache={};
const jalanCacheQueue={};
let festivals=[];
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
function festivalKey(f,index=0){return f.qid||`${f.label_ja}-${f.latitude}-${f.longitude}-${index}`}
function wikidataQID(f){return /^Q[1-9][0-9]*$/.test(f.qid||'')?f.qid:''}
function wikipediaTitle(f){return f.wikipedia_title||(wikidataQID(f)?f.label_ja:'')}
function lifecycleStatus(f){return f.lifecycle?.status||'legacy'}
function matchesLifecycle(f,filter){
  const status=lifecycleStatus(f);
  if(filter==='all')return true;
  if(filter==='current')return status==='active'||status==='legacy';
  return status===filter;
}
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
function venueData(f){return f.venue&&typeof f.venue==='object'&&f.venue.name&&safeUrl(f.venue.source)?f.venue:null}
// 座標のない確認済み会場もある。そのときは祭り自体の座標で地図に置く。
function venuePoint(venue){return!!venue&&typeof venue.latitude==='number'&&typeof venue.longitude==='number'}
function mapCoordinates(f){
  const venue=venueData(f),hasVenuePoint=venuePoint(venue);
  const latitude=Number(hasVenuePoint?venue.latitude:f.latitude),longitude=Number(hasVenuePoint?venue.longitude:f.longitude);
  return Number.isFinite(latitude)&&Number.isFinite(longitude)?{latitude,longitude}:null;
}
function locationCacheKey(f){const point=mapCoordinates(f);return point?`${point.latitude.toFixed(5)},${point.longitude.toFixed(5)}`:''}
function locationPrecisionLabel(f){
  const venue=venueData(f);
  if(venuePoint(venue))return venue.coordinate_note||(venue.precision==='exact'?'会場位置を確認済み':'会場周辺');
  if(f.coordinate_source==='administrative_area')return'位置は行政区域の目安';
  if(f.coordinate_source==='venue')return'会場データ由来（未検証）';
  return'位置は目安';
}
function locationMarkup(location,f){
  const venue=venueData(f),status=`<span class="location-status">${esc(locationPrecisionLabel(f))}</span>`;
  if(!venue)return `${esc(location)}${status}`;
  const address=venue.address?`<span class="location-address">${esc(venue.address)}</span>`:'';
  return `<a href="${esc(safeUrl(venue.source))}" target="_blank" rel="noopener noreferrer">${esc(venue.name)}<span aria-hidden="true">↗</span></a>${address}${status}`;
}
function groundedDescription(f){
  const venue=venueData(f),descriptionSource=safeUrl(f.description_source);
  if(venue&&f.description&&descriptionSource&&descriptionSource===safeUrl(venue.source)){
    return{body:f.description,status:'開催地と同じ出典で確認済み',locationAware:false};
  }
  const name=f.label_ja||f.label_en||'この祭り';
  const safeLegacy=(String(f.description||'').match(/[^。！？]+[。！？]?/g)||[]).filter(sentence=>!/(?:開催|会場|毎年|日時|[0-9０-９]+月|[0-9０-９]+日|[一-龠々ヶ]{1,10}[都道府県市区町村])/.test(sentence)).slice(0,2).join('').trim();
  if(safeLegacy.length>=30)return{body:safeLegacy,status:'参考情報（出典を確認中）',locationAware:false};
  return{body:`${name}は、地図上では`,status:'詳しい概要の出典を確認中です',locationAware:true};
}
function isFestivalWikipediaContent(value){return /(?:祭(?:り|礼|典|事)|大会|花火|フェスティバル|イベント|行事|博覧会|盆踊り)/.test(String(value||''))}
function wikipediaSentenceMatchesLocation(value,f,location){
  const prefectures=String(value||'').match(/[一-龠々ヶ]{2,4}[都道府県]/g)||[];
  if(prefectures.some(prefecture=>prefecture!==f.prefecture))return false;
  const municipalities=String(value||'').match(/[一-龠々ヶ]{1,10}(?:市|区|町|村)/g)||[];
  const normalizedLocation=String(location||'').replace(/\s/g,'');
  return municipalities.every(municipality=>normalizedLocation.includes(municipality));
}
function safeWikipediaDescription(value,f,location){
  const sentences=String(value||'').match(/[^。！？]+[。！？]?/g)||[];
  return sentences.filter(sentence=>!/(?:会場|開催地|にて開催)/.test(sentence)&&wikipediaSentenceMatchesLocation(sentence,f,location)).slice(0,3).join('').trim();
}
function isCompatibleWikipediaContent(value,f,location){
  return isFestivalWikipediaContent(value)&&safeWikipediaDescription(value,f,location).length>=30;
}
function isCompatibleWikipediaImage(value,f,location){
  const sentences=String(value||'').match(/[^。！？]+[。！？]?/g)||[];
  return isFestivalWikipediaContent(value)&&sentences.some(sentence=>wikipediaSentenceMatchesLocation(sentence,f,location));
}
async function fetchJSONWithRetry(url){
  let lastError;
  for(let attempt=0;attempt<2;attempt++){
    try{const response=await fetch(url);if(response.ok)return response.json();lastError=new Error(`HTTP ${response.status}`)}catch(error){lastError=error}
    if(attempt===0)await new Promise(resolve=>setTimeout(resolve,500));
  }
  throw lastError;
}
async function loadWikipediaContent(f){
  const title=wikipediaTitle(f);if(!title)return null;
  const cacheKey=`${f.qid||''}:${title}`;
  if(wikiContentCache[cacheKey])return wikiContentCache[cacheKey];
  if(wikiContentQueue[cacheKey])return wikiContentQueue[cacheKey];
  wikiContentQueue[cacheKey]=fetchJSONWithRetry(`/api/wiki/content?title=${encodeURIComponent(title)}&qid=${encodeURIComponent(wikidataQID(f))}`)
    .then(data=>wikiContentCache[cacheKey]=data)
    .catch(error=>{console.warn(`Wikipedia content could not be loaded for ${title}`,error);return null})
    .finally(()=>delete wikiContentQueue[cacheKey]);
  return wikiContentQueue[cacheKey];
}
async function detailedLocation(f){
  const venue=venueData(f);if(venue)return venue.name;
  const embedded=f.address||f.location||f.municipality||f.city;
  if(embedded)return [f.prefecture,embedded].filter((value,index,items)=>value&&items.indexOf(value)===index).join(' ');
  const point=mapCoordinates(f);if(!point)return f.prefecture||'地域未登録';
  const key=locationCacheKey(f);
  if(geocodingCache[key])return geocodingCache[key];
  if(geocodingCacheQueue[key])return geocodingCacheQueue[key];
  geocodingCacheQueue[key]=fetch('/api/geocoding/reverse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lat:point.latitude,lng:point.longitude})})
    .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()})
    .then(data=>{
      const resolved=data.success&&(data.full_location||data.location)?data.full_location||data.location:'';
      if(!resolved)return f.prefecture||'地域未登録';
      return f.prefecture&&!resolved.includes(f.prefecture)?`${f.prefecture} ${resolved}`:resolved;
    })
    .catch(error=>{console.warn(`Location could not be resolved for ${key}`,error);return f.prefecture||'地域未登録'})
    .then(location=>{geocodingCache[key]=location;persist(GEOCODING_CACHE_KEY,geocodingCache);return location})
    .finally(()=>delete geocodingCacheQueue[key]);
  return geocodingCacheQueue[key];
}
function parseRange(value){
  if(!value||value==='日付未定')return{};
  const parts=value.split(/[〜～]/),valid=s=>/^\d{4}-\d{2}-\d{2}$/.test(s);
  const endValue=parts[1]||parts[0];
  return{start:valid(parts[0])?new Date(`${parts[0]}T00:00:00`):null,end:valid(endValue)?new Date(`${endValue}T23:59:59`):null};
}
function occurrenceRanges(f){
  const occurrences=Array.isArray(f.occurrences)?f.occurrences:[];
  if(occurrences.length)return occurrences.map(item=>({...item,...parseRange(`${item.start}${item.end&&item.end!==item.start?`〜${item.end}`:''}`)})).filter(item=>item.start&&item.end);
  const range=parseRange(f.date);return range.start&&range.end?[{...range}]:[];
}
function annualScheduleRange(item,year){
  if(item.kind==='fixed')return parseRange(`${year}-${item.start}〜${year}-${item.end||item.start}`);
  const month=Number(item.month),weekday=Number(item.weekday),ordinal=Number(item.ordinal);
  if(!month||!weekday)return{};
  let day;
  if(item.kind==='nth_weekday'){
    const first=new Date(year,month-1,1),firstIso=first.getDay()||7;
    day=1+(weekday-firstIso+7)%7+7*(ordinal-1);
    if(new Date(year,month-1,day).getMonth()!==month-1)return{};
  }else if(item.kind==='last_weekday'){
    const last=new Date(year,month,0),lastIso=last.getDay()||7;
    day=last.getDate()-(lastIso-weekday+7)%7;
  }else return{};
  return parseRange(`${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`);
}
function annualScheduleRanges(f,year){
  return (Array.isArray(f.annual_schedule)?f.annual_schedule:[]).map(item=>({...item,...annualScheduleRange(item,year)})).filter(item=>item.start&&item.end);
}
function formatOccurrence({start,end,status}){
  const startLabel=`${start.getFullYear()}年${start.getMonth()+1}月${start.getDate()}日`;
  const sameDay=start.getFullYear()===end.getFullYear()&&start.getMonth()===end.getMonth()&&start.getDate()===end.getDate();
  const endLabel=sameDay?'':start.getFullYear()===end.getFullYear()?`〜${end.getMonth()+1}月${end.getDate()}日`:`〜${end.getFullYear()}年${end.getMonth()+1}月${end.getDate()}日`;
  return `${startLabel}${endLabel}${status==='scheduled'?'（予定）':''}`;
}
function nextOccurrence(f,now=new Date()){
  const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  const annual=[...annualScheduleRanges(f,today.getFullYear()),...annualScheduleRanges(f,today.getFullYear()+1)];
  return [...occurrenceRanges(f),...annual].filter(({end})=>end>=today).sort((a,b)=>Math.max(a.start,today)-Math.max(b.start,today)||a.start-b.start)[0];
}
function nextDateLabel(f){
  const item=nextOccurrence(f);return item?formatOccurrence(item):'日付未定';
}
function occurrenceMarkup(f){
  const item=nextOccurrence(f);if(!item)return'日付未定';
  const source=safeUrl(item.source),label=esc(formatOccurrence(item));
  return source?`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">${label}</a>`:label;
}
function matchesDate(f,startValue,endValue){
  if(!startValue&&!endValue)return true;
  const rangeStart=startValue?new Date(`${startValue}T00:00:00`):null;
  const rangeEnd=endValue?new Date(`${endValue}T23:59:59`):null;
  const startYear=rangeStart?rangeStart.getFullYear():rangeEnd.getFullYear()-5;
  const endYear=Math.min(rangeEnd?rangeEnd.getFullYear():rangeStart.getFullYear()+5,startYear+50);
  const years=[];
  for(let year=startYear;year<=endYear;year++)years.push(year);
  const candidates=[...occurrenceRanges(f),...years.flatMap(year=>annualScheduleRanges(f,year))];
  return candidates.some(({start,end})=>(!rangeStart||end>=rangeStart)&&(!rangeEnd||start<=rangeEnd));
}
function nextOccurrenceTime(f,now=new Date()){
  const item=nextOccurrence(f,now);if(!item)return Number.POSITIVE_INFINITY;
  const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  return Math.max(item.start.getTime(),today.getTime());
}
function compareByNextOccurrence(a,b){
  const dateOrder=nextOccurrenceTime(a)-nextOccurrenceTime(b);
  if(Number.isFinite(dateOrder)&&dateOrder!==0)return dateOrder;
  if(Number.isFinite(nextOccurrenceTime(a)))return -1;
  if(Number.isFinite(nextOccurrenceTime(b)))return 1;
  return String(a.label_ja||a.label_en||'').localeCompare(String(b.label_ja||b.label_en||''),'ja');
}
async function loadNearbyHotels(f){
  const prefecture=f.prefecture;if(!prefecture)return null;
  const lrgCode=f.jalan_lrg_code||'',lrgName=f.jalan_lrg_name||'';
  const smlCode=f.jalan_sml_code||'',smlName=f.jalan_sml_name||'';
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
  return `<span class="ad-label">広告</span><ul class="affiliate-hotel-list">${hotels.map(h=>{
    const link=safeUrl(h.plan_url)||safeUrl(h.detail_url);if(!link)return'';
    return `<li class="affiliate-hotel"><a class="affiliate-link" href="${esc(link)}" rel="nofollow noopener" target="_blank">${esc(h.name||'宿泊施設')}</a>${h.address?`<span class="affiliate-hotel-address">${esc(h.address)}</span>`:''}</li>`;
  }).join('')}</ul>`;
}
function populatePrefectures(){
  const select=document.querySelector('#prefecture');
  [...new Set(festivals.map(f=>f.prefecture).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja')).forEach(p=>select.add(new Option(p,p)));
}
function populateCategories(){
  document.querySelector('#category-options').innerHTML=CATEGORY_META.filter(meta=>meta.code!=='kt').map(meta=>[meta.code,meta.label]).map(([value,label])=>`<label class="multi-option"><input type="checkbox" value="${esc(value)}">${esc(label)}</label>`).join('');
}
function selectedCategories(){return [...document.querySelectorAll('#category-options input:checked')].map(input=>input.value)}
function updateCategorySummary(){const labels=[...document.querySelectorAll('#category-options input:checked')].map(input=>input.parentElement.textContent);document.querySelector('#category-summary').textContent=!labels.length?'すべて':labels.length===1?labels[0]:`${labels[0]} ほか${labels.length-1}`}
function clearCategories(){document.querySelectorAll('#category-options input').forEach(input=>{input.checked=false});updateCategorySummary()}
function applyFilters(){
  const q=document.querySelector('#keyword').value.trim().toLocaleLowerCase('ja');
  const prefecture=document.querySelector('#prefecture').value;
  const categories=selectedCategories();
  const dateStart=document.querySelector('#festival-date-start').value;
  const dateEnd=document.querySelector('#festival-date-end').value;
  visible=festivals.filter(f=>{
    const text=[f.label_ja,f.label_en,f.prefecture,f.description].filter(Boolean).join(' ').toLocaleLowerCase('ja');
    const prefectureMatches=!prefecture||(f.prefecture===prefecture&&f.coordinate_prefecture===prefecture);
    const categoryMatches=!categories.length||categories.includes(categoryCode(f));
    return text.includes(q)&&prefectureMatches&&categoryMatches&&matchesLifecycle(f,'current')&&matchesDate(f,dateStart,dateEnd);
  }).sort(compareByNextOccurrence);
  renderList();renderMarkers();
  document.querySelector('#result-count').textContent=visible.length;
  document.querySelector('#map-count').textContent=`地図上に ${visible.length} 件`;
}
function renderList(){
  const list=document.querySelector('#festival-list');
  if(!visible.length){list.innerHTML='<p class="empty-state">条件に合う祭りがありません。日付や地域を変えてお試しください。</p>';return}
  list.innerHTML=visible.map((f,index)=>{
    const key=festivalKey(f,index);
    return `<button class="festival-card" type="button" data-key="${esc(key)}" aria-current="${key===selectedKey}"><span class="card-index">${String(index+1).padStart(2,'0')}</span><span><span class="card-name">${esc(f.label_ja||f.label_en||'名称未登録')}</span><span class="card-meta"><span>${esc(f.prefecture||'地域未登録')}</span><span>${esc(nextDateLabel(f))}</span></span></span></button>`;
  }).join('');
  list.querySelectorAll('button').forEach(card=>card.addEventListener('click',()=>selectFestival(card.dataset.key,'list')));
}
const CATEGORY_META=[
  {code:'mt',label:'山車・屋台'},
  {code:'hb',label:'花火'},
  {code:'ma',label:'演舞・盆踊り'},
  {code:'kw',label:'行列・渡御'},
  {code:'jr',label:'神事・祭礼'},
  {code:'hn',label:'灯籠・火祭り'},
  {code:'si',label:'博覧会・市'},
  {code:'ar',label:'音楽・映画・芸術'},
  {code:'ks',label:'花・季節・自然'},
  {code:'sm',label:'市民・観光まつり'},
  {code:'kt',label:'その他・未分類'},
];
function categoryCode(f){
  const categories=Array.isArray(f.categories)?f.categories.filter(Boolean):[];
  if(!categories.length)return'kt';
  const found=CATEGORY_META.find(meta=>categories.includes(meta.label));
  return found?found.code:'kt';
}
function renderLegend(){
  const legend=document.querySelector('#map-legend');if(!legend||legend.childElementCount)return;
  legend.innerHTML=CATEGORY_META.filter(meta=>meta.code!=='kt').map(meta=>`<span><span class="legend-dot" style="background:var(--cat-${meta.code})"></span>${esc(meta.label)}</span>`).join('');
}
function icon(selected,festival){
  const category=categoryCode(festival);
  return L.divIcon({className:'',html:`<span class="festival-marker cat-${category}${selected?' selected':''}" role="img" aria-label="${esc(festival.label_ja||festival.label_en||'祭り')}"></span>`,iconSize:[22,22],iconAnchor:[11,11],popupAnchor:[0,-12]});
}
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
// Nearby markers cluster by zoom; clicks are handled below so tall stacks open a list.
const markerLayer=L.markerClusterGroup({
  maxClusterRadius:40,
  showCoverageOnHover:false,
  spiderfyDistanceMultiplier:1.3,
  spiderfyOnMaxZoom:false,
  zoomToBoundsOnClick:false,
  iconCreateFunction:cluster=>{
    const count=cluster.getChildCount();
    const size=count<10?30:count<100?36:count<1000?42:48;
    return L.divIcon({className:'festival-cluster-anchor',html:`<span class="festival-cluster" aria-label="${count}件の祭り">${count}</span>`,iconSize:[size,size]});
  },
}).addTo(map);
// Prefecture centroids stack up to dozens of festivals whose spiral is unreadable,
// so a tall stack of identical coordinates lists its festivals by category instead.
const STACK_LIST_MIN=9;
markerLayer.on('clusterclick clusterkeypress',e=>{
  if(e.type==='clusterkeypress'&&e.originalEvent?.keyCode!==13)return;
  const cluster=e.layer,children=cluster.getAllChildMarkers(),point=children[0].getLatLng();
  const stacked=children.every(marker=>marker.getLatLng().equals(point));
  // Zooming cannot split a stack, nor anything at maximum zoom.
  const listed=(stacked||map.getZoom()>=map.getMaxZoom())&&children.length>=STACK_LIST_MIN;
  if(listed)openStackList(stacked?point:cluster.getLatLng(),children,stacked);
  else if(!stacked&&map.getZoom()<map.getMaxZoom())cluster.zoomToBounds();
  else cluster.spiderfy();
  // Keyboard focus would fall to the page when the focused cluster icon is replaced.
  if(e.type==='clusterkeypress')(listed?document.querySelector('.stack-list button'):map.getContainer()).focus();
});
function openStackList(point,children,stacked){
  const entries=children.map(marker=>[marker.options.festivalKey,markers.get(marker.options.festivalKey).festival]);
  const label=f=>f.label_ja||f.label_en||'名称未登録';
  const groups=new Map();
  for(const entry of entries){
    const category=CATEGORY_META.find(meta=>meta.code===categoryCode(entry[1])).label;
    if(!groups.has(category))groups.set(category,[]);
    groups.get(category).push(entry);
  }
  const order=category=>CATEGORY_META.findIndex(meta=>meta.label===category);
  const sorted=[...groups].sort(([a],[b])=>order(a)-order(b));
  const prefectures=new Set(entries.map(([,f])=>f.prefecture||'地域未登録'));
  const prefix=prefectures.size===1?`${[...prefectures][0]} `:'';
  const heading=`${prefix}${stacked?'同じ位置':'この付近'}の ${entries.length} 件`;
  const body=sorted.map(([category,items])=>`<section><h3>${esc(category)}（${items.length}件）</h3><ul>${items.sort(([,a],[,b])=>label(a).localeCompare(label(b),'ja')).map(([key,f])=>`<li><button type="button" data-key="${esc(key)}">${esc(label(f))}</button></li>`).join('')}</ul></section>`).join('');
  const content=document.createElement('div');
  content.className='stack-list';
  content.innerHTML=`<h2>${esc(heading)}</h2>${body}`;
  content.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>selectFestival(button.dataset.key,'marker')));
  L.popup({maxHeight:320,className:'stack-popup'}).setLatLng(point).setContent(content).openOn(map);
}
function markerStyle(f){
  const css=getComputedStyle(document.documentElement);
  const fill=css.getPropertyValue(`--cat-${categoryCode(f)}`).trim()||css.getPropertyValue('--color-ink').trim();
  return {radius:9,weight:2,color:css.getPropertyValue('--color-paper').trim(),fillColor:fill,fillOpacity:1};
}
function renderMarkers(){
  map.closePopup();markerLayer.clearLayers();markers=new Map();
  visible.forEach((f,index)=>{
    const point=mapCoordinates(f);if(!point)return;
    const key=festivalKey(f,index),latlng=[point.latitude,point.longitude];
    const marker=new DottedCircleMarker(latlng,{...markerStyle(f),festivalKey:key});
    marker.bindTooltip(esc(f.label_ja||f.label_en||'名称未登録'),{direction:'top',offset:[0,-10]});
    marker.on('click',()=>selectFestival(key,'marker'));markers.set(key,{marker,festival:f});
  });
  markerLayer.addLayers([...markers.values()].map(entry=>entry.marker));
  if(selectedKey&&!markers.has(selectedKey))closeDetail(false);else showSelectedMarker(selectedKey);
}
function showSelectedMarker(key){
  if(selectedMarker){map.removeLayer(selectedMarker);selectedMarker=null}
  const entry=key&&markers.get(key);if(!entry)return;
  const f=entry.festival;
  selectedMarker=L.marker(entry.marker.getLatLng(),{icon:icon(true,f),zIndexOffset:SELECTED_MARKER_Z_INDEX}).addTo(map);
  selectedMarker.bindTooltip(esc(f.label_ja||f.label_en||'名称未登録'),{direction:'top',offset:[0,-10]});
  selectedMarker.on('click',()=>selectFestival(key,'marker'));
}
function heritageBadge(f){
  const type=String(f.cultural_relaw?.cultural_type||'').trim(),url=safeUrl(f.cultural_relaw?.url),source=safeUrl(f.cultural_relaw?.source);
  if(!type)return'';
  const link=url?`<a class="badge-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">文化遺産詳細登録情報<span aria-hidden="true">↗</span></a>`:source?`<a class="badge-link" href="${esc(source)}" target="_blank" rel="noopener noreferrer">指定の出典<span aria-hidden="true">↗</span></a>`:'';
  return `<p class="badge-line"><span class="badge badge--heritage" role="note">文化財指定｜${esc(type)}</span>${link}</p>`;
}
function detail(f){
  const qid=wikidataQID(f),title=wikipediaTitle(f);
  const wiki=qid?`https://www.wikidata.org/wiki/${encodeURIComponent(qid)}`:'';
  const pedia=title?`https://ja.wikipedia.org/wiki/${encodeURIComponent(title)}`:'';
  const culture=safeUrl(f.cultural_relaw?.url);
  const about=groundedDescription(f);
  const aboutBody=about.locationAware?`${esc(about.body)}「<span id="detail-about-location">${esc(f.prefecture||'地域未登録')}</span>」付近に登録されています。正確な会場は確認中です。`:esc(about.body);
  return `<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(f.label_ja||f.label_en||'名称未登録')}</h2>${heritageBadge(f)}</header><dl class="detail-facts"><div><dt>開催地</dt><dd id="detail-location">${locationMarkup(f.prefecture||'地域未登録',f)}${venueData(f)?'':'<span class="location-loading">詳細を確認中…</span>'}</dd></div><div><dt>次回開催日</dt><dd>${occurrenceMarkup(f)}</dd></div></dl><section class="detail-section" aria-labelledby="detail-about"><h3 id="detail-about">祭りについて</h3><p class="detail-description">${aboutBody}</p><p class="detail-description-status">${esc(about.status)}</p></section><section class="detail-section" aria-labelledby="detail-photo"><h3 id="detail-photo">写真</h3><div id="detail-image"><p class="detail-image-status">画像を読み込んでいます…</p></div></section><section class="detail-section" id="detail-history-section" aria-labelledby="detail-history"><h3 id="detail-history">歴史</h3><div class="detail-history" id="detail-history-body"></div><p class="detail-history-status" id="detail-history-status">読み込んでいます…</p></section>${WIKI_EXTRA_SECTIONS.map(wikiSectionMarkup).join('')}<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典・関連情報</h3><nav class="detail-links" id="detail-links" aria-label="出典">${safeUrl(f.description_source)?`<a href="${esc(safeUrl(f.description_source))}" target="_blank" rel="noopener noreferrer">公式情報（概要・開催地）<span aria-hidden="true">↗</span></a>`:''}${wiki?`<a href="${wiki}" target="_blank" rel="noopener noreferrer">Wikidata<span aria-hidden="true">↗</span></a>`:''}${pedia?`<a href="${pedia}" target="_blank" rel="noopener noreferrer">Wikipedia<span aria-hidden="true">↗</span></a>`:''}${culture?`<a href="${esc(culture)}" target="_blank" rel="noopener noreferrer">文化庁<span aria-hidden="true">↗</span></a>`:''}</nav></section><section class="detail-section detail-affiliate" id="detail-affiliate-section" aria-labelledby="detail-affiliate-heading"><h3 id="detail-affiliate-heading">近くの宿</h3><div class="affiliate" id="detail-affiliate" aria-label="広告"><p class="detail-affiliate-status">近くの宿を検索しています…</p></div></section></article>`;
}
function selectFestival(key,origin){
  const entry=markers.get(key);if(!entry)return;selectedKey=key;selectedOrigin=origin;
  showSelectedMarker(key);
  document.querySelectorAll('.festival-card').forEach(card=>card.setAttribute('aria-current',String(card.dataset.key===key)));
  if(origin==='list')map.flyTo(entry.marker.getLatLng(),Math.max(map.getZoom(),8),{duration:.55});
  openDetail(entry.festival,key,origin);
}
function openDetail(f,key,origin){
  const panel=document.querySelector('#detail-panel'),content=document.querySelector('#detail-content'),originLabel=document.querySelector('#detail-origin');
  panel.hidden=false;document.querySelector('.app-shell').classList.add('has-detail');content.dataset.state='loading';content.innerHTML=detail(f);
  originLabel.textContent=origin==='marker'?'地図から選択':'検索結果から選択';
  const focusTarget=document.querySelector('#detail-title');
  panel.scrollTop=0;
  requestAnimationFrame(()=>{map.invalidateSize();focusTarget?.focus({preventScroll:origin!=='marker'})});
  hydrateImage(f,key);
  hydrateLocation(f,key);
  hydrateAbout(f,key);
  hydrateHistory(f,key);
  hydrateExtraSections(f,key);
  hydrateLinks(f,key);
  hydrateNearbyHotels(f,key);
}
async function hydrateNearbyHotels(f,key){
  const hotels=await loadNearbyHotels(f);
  const section=document.querySelector('#detail-affiliate-section');
  const container=document.querySelector('#detail-affiliate');if(!container||!section||selectedKey!==key)return;
  if(hotels===null){section.hidden=true;container.innerHTML='';return}
  section.hidden=false;
  if(!hotels.length){container.innerHTML='<p class="detail-affiliate-status">近くの宿が見つかりませんでした。</p>';return}
  container.innerHTML=affiliateHotelMarkup(hotels);
}
async function hydrateAbout(f,key){
  const venue=venueData(f),descriptionSource=safeUrl(f.description_source);
  if(venue&&f.description&&descriptionSource&&descriptionSource===safeUrl(venue.source))return;
  const [data,location]=await Promise.all([loadWikipediaContent(f),detailedLocation(f)]),body=document.querySelector('.detail-description'),status=document.querySelector('.detail-description-status');
  if(!data||selectedKey!==key||!body||!status)return;
  const description=safeWikipediaDescription(data.description,f,location),source=safeUrl(data.source_url);
  if(description.length<30||!source||!isCompatibleWikipediaContent(data.description,f,location))return;
  body.textContent=description;
  const contentLicense=safeUrl(data.content_license_url);
  status.innerHTML=`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">Wikipedia<span aria-hidden="true">↗</span></a>${contentLicense?` · <a href="${esc(contentLicense)}" target="_blank" rel="noopener noreferrer">CC BY-SA 4.0<span aria-hidden="true">↗</span></a>`:''} · 編集あり`;
}
async function hydrateWikiSection(f,key,config){
  const section=document.querySelector(config.sectionId);
  if(!section)return;
  // Official-source (local-*) records have no article; hide instead of reporting a load failure.
  if(!wikipediaTitle(f)){section.hidden=true;return}
  const body=document.querySelector(config.bodyId),status=document.querySelector(config.statusId);
  const data=await loadWikipediaContent(f);
  if(selectedKey!==key)return;
  const wikiLink=url=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Wikipedia<span aria-hidden="true">↗</span></a>`;
  const ccLink=url=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">CC BY-SA 4.0<span aria-hidden="true">↗</span></a>`;
  if(config.hideWhenEmpty&&(!data||data.sections_unavailable||!wikiSectionHasContent(data[config.field]))){section.hidden=true;return}
  if(!data||data.sections_unavailable){
    if(body)body.innerHTML='';
    if(status)status.textContent='読み込みに失敗しました。もう一度開いてください。';
    return;
  }
  const payload=data[config.field]||{};
  const summary=String(payload.summary||'').trim();
  const items=Array.isArray(payload.items)?payload.items:[];
  const blocks=Array.isArray(payload.blocks)?payload.blocks:[];
  const source=safeUrl(payload.source_url)||safeUrl(data.source_url);
  const license=safeUrl(data.content_license_url);
  if(!body)return;
  if(!summary&&!items.length&&!blocks.length){
    body.innerHTML=`<p class="detail-empty">${esc(config.placeholder)}</p>`;
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
  const blockMarkup=blocks.map(b=>{
    const heading=esc(String(b.heading||'')),text=esc(String(b.text||''));
    return (heading?`<p class="detail-subheading">${heading}</p>`:'')+`<p>${text}</p>`;
  }).join('');
  const sourceMarkup=blockMarkup
    ?(items.length?`<details class="section-source"><summary>原文を読む</summary>${blockMarkup}</details>`:blockMarkup)
    :'';
  body.innerHTML=[
    summary?`<p class="detail-summary">${esc(summary)}</p>`:'',
    items.length?`<dl class="section-items">${itemsMarkup}</dl>`:'',
    sourceMarkup,
  ].filter(Boolean).join('');
  const attribution=[summary?'AIによる要約':'編集あり'];
  if(source)attribution.push(wikiLink(source));
  if(license)attribution.push(ccLink(license));
  if(status)status.innerHTML=attribution.join(' · ');
}
async function hydrateHistory(f,key){
  await hydrateWikiSection(f,key,{sectionId:'#detail-history-section',bodyId:'#detail-history-body',statusId:'#detail-history-status',field:'history',placeholder:'この記事には歴史の記述がありません。'});
}
const WIKI_EXTRA_SECTIONS=[{field:'highlights',title:'見どころ'},{field:'flow',title:'お祭りの流れ'},{field:'access',title:'アクセス'},{field:'tourism',title:'周辺観光'}];
function wikiSectionHasContent(payload){const p=payload||{};return Boolean(String(p.summary||'').trim()||(Array.isArray(p.items)&&p.items.length)||(Array.isArray(p.blocks)&&p.blocks.length))}
function wikiSectionMarkup({field,title}){return `<section class="detail-section" id="detail-${field}-section" aria-labelledby="detail-${field}"><h3 id="detail-${field}">${title}</h3><div class="detail-history" id="detail-${field}-body"></div><p class="detail-history-status" id="detail-${field}-status">読み込んでいます…</p></section>`}
async function hydrateExtraSections(f,key){
  await Promise.all(WIKI_EXTRA_SECTIONS.map(({field})=>hydrateWikiSection(f,key,{sectionId:`#detail-${field}-section`,bodyId:`#detail-${field}-body`,statusId:`#detail-${field}-status`,field,hideWhenEmpty:true})));
}
async function hydrateLocation(f,key){
  const location=await detailedLocation(f),element=document.querySelector('#detail-location'),aboutLocation=document.querySelector('#detail-about-location');
  if(element&&selectedKey===key){element.innerHTML=locationMarkup(location,f);if(aboutLocation)aboutLocation.textContent=location}
}
function closeDetail(restoreFocus=true){
  const key=selectedKey,origin=selectedOrigin;selectedKey=null;selectedOrigin=null;document.querySelector('#detail-panel').hidden=true;document.querySelector('.app-shell').classList.remove('has-detail');
  showSelectedMarker(null);document.querySelectorAll('.festival-card').forEach(card=>card.setAttribute('aria-current','false'));
  requestAnimationFrame(()=>map.invalidateSize());
  if(restoreFocus&&key){
    const target=origin==='marker'?document.querySelector('#map'):document.querySelector(`.festival-card[data-key="${CSS.escape(key)}"]`);
    target?.focus();
  }
}
async function hydrateImage(f,key){
  const [wikipediaContent,location]=await Promise.all([loadWikipediaContent(f),detailedLocation(f)]),contentIsRelevant=!wikipediaContent||isCompatibleWikipediaImage(wikipediaContent.description,f,location);
  let result=contentIsRelevant?imageCache[f.qid]:null,loadError=null;
  if(typeof result==='string'||(result?.url&&!result.license)){delete imageCache[f.qid];persist(CACHE_KEY,imageCache);result=null}
  if(!result&&wikipediaContent?.image_url&&contentIsRelevant){result={url:safeUrl(wikipediaContent.image_url),license:String(wikipediaContent.license||'').trim(),licenseUrl:safeUrl(wikipediaContent.license_url),artist:plainText(wikipediaContent.artist),credit:plainText(wikipediaContent.credit),sourceUrl:safeUrl(wikipediaContent.image_source_url)};imageCache[f.qid]=result;persist(CACHE_KEY,imageCache)}
  if(!result&&contentIsRelevant&&String(f.label_ja||'').trim()){
    try{const data=await fetchJSONWithRetry(`/api/commons/image?label=${encodeURIComponent(f.label_ja)}&prefecture=${encodeURIComponent(f.prefecture||'')}`);result={url:safeUrl(data.image_url),license:String(data.license||'').trim(),licenseUrl:safeUrl(data.license_url),artist:plainText(data.artist),credit:plainText(data.credit),sourceUrl:safeUrl(data.image_source_url)};imageCache[f.qid]=result;persist(CACHE_KEY,imageCache)}
    catch(error){}
  }
  if(!result&&wikidataQID(f)&&contentIsRelevant){
    try{const data=await fetchJSONWithRetry(`/api/wiki/image?qid=${encodeURIComponent(f.qid)}`);result={url:safeUrl(data.url),license:String(data.license||'').trim(),licenseUrl:safeUrl(data.license_url),artist:plainText(data.artist),credit:plainText(data.credit),sourceUrl:safeUrl(data.source_url)};imageCache[f.qid]=result;persist(CACHE_KEY,imageCache)}
    catch(error){loadError=error}
  }
  const container=document.querySelector('#detail-image'),content=document.querySelector('#detail-content');if(!container||selectedKey!==key)return;
  if(loadError&&!wikipediaContent){console.warn(`Image could not be loaded for ${f.qid}`,loadError);content.dataset.state='error';container.innerHTML='<p class="detail-image-status">画像を取得できませんでした。時間をおいて再度お試しください。</p>';return}
  if(!result?.url){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">表示できる画像が登録されていません。</p>';return}
  if(!result.license){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">画像のライセンス情報を確認できないため、表示していません。</p>';return}
  const source=result.sourceUrl||commonsFilePage(result.url);
  const license=result.licenseUrl?`<a href="${esc(result.licenseUrl)}" target="_blank" rel="noopener noreferrer" aria-label="ライセンス ${esc(result.license)}">${esc(result.license)}<span aria-hidden="true">↗</span></a>`:esc(result.license);
  const creator=result.artist||result.credit;
  content.dataset.state='success';container.innerHTML=`<button class="detail-image-button" type="button" aria-label="${esc(f.label_ja||'祭り')}の画像を拡大"><img class="detail-image" src="${esc(result.url)}" alt="${esc(f.label_ja||'祭り')}の画像"></button><p class="license">${creator?`${esc(creator)} · `:''}${license}${source?` · <a href="${esc(source)}" target="_blank" rel="noopener noreferrer" aria-label="Wikimedia Commonsの画像出典">Commons<span aria-hidden="true">↗</span></a>`:''}</p>`;
  container.querySelector('button').addEventListener('click',()=>openLightbox(result.url,f.label_ja));
}
async function hydrateLinks(f,key){
  if(!wikidataQID(f))return;
  let links=linksCache[f.qid];
  if(!links){
    try{
      const data=await fetchJSONWithRetry(`/api/wiki/links?qid=${encodeURIComponent(f.qid)}`);
      links={officialSite:safeUrl(data.official_site),facebook:safeUrl(data.facebook),twitter:safeUrl(data.twitter),instagram:safeUrl(data.instagram),youtube:safeUrl(data.youtube)};
      linksCache[f.qid]=links;persist(LINKS_CACHE_KEY,linksCache);
    }catch(error){links={}}
  }
  const nav=document.querySelector('#detail-links');if(!nav||selectedKey!==key)return;
  const extra=[
    links.officialSite?`<a href="${esc(links.officialSite)}" target="_blank" rel="noopener noreferrer">公式サイト<span aria-hidden="true">↗</span></a>`:'',
    links.facebook?`<a href="${esc(links.facebook)}" target="_blank" rel="noopener noreferrer">Facebook<span aria-hidden="true">↗</span></a>`:'',
    links.twitter?`<a href="${esc(links.twitter)}" target="_blank" rel="noopener noreferrer">X (Twitter)<span aria-hidden="true">↗</span></a>`:'',
    links.instagram?`<a href="${esc(links.instagram)}" target="_blank" rel="noopener noreferrer">Instagram<span aria-hidden="true">↗</span></a>`:'',
    links.youtube?`<a href="${esc(links.youtube)}" target="_blank" rel="noopener noreferrer">YouTube<span aria-hidden="true">↗</span></a>`:'',
  ].join('');
  if(extra)nav.insertAdjacentHTML('afterbegin',extra);
}
function openLightbox(url,alt){const dialog=document.querySelector('#lightbox'),image=document.querySelector('#lightbox-image');image.src=url;image.alt=`${alt||'祭り'}の拡大画像`;dialog.showModal()}
function closeLightbox(){const dialog=document.querySelector('#lightbox');if(dialog.open)dialog.close();document.querySelector('#lightbox-image').src=''}

document.querySelector('#keyword').addEventListener('input',applyFilters);
document.querySelector('#prefecture').addEventListener('change',applyFilters);
document.querySelector('#category-options').addEventListener('change',()=>{updateCategorySummary();applyFilters()});
document.querySelector('#festival-date-start').addEventListener('change',applyFilters);
document.querySelector('#festival-date-end').addEventListener('change',applyFilters);
document.querySelector('#clear-filters').addEventListener('click',()=>{document.querySelector('#keyword').value='';document.querySelector('#prefecture').value='';clearCategories();document.querySelector('#festival-date-start').value='';document.querySelector('#festival-date-end').value='';applyFilters();document.querySelector('#keyword').focus()});
document.querySelector('.detail-close').addEventListener('click',()=>closeDetail());
document.querySelector('.lightbox-close').addEventListener('click',closeLightbox);
document.querySelector('#lightbox').addEventListener('click',event=>{if(event.target.id==='lightbox')closeLightbox()});

renderLegend();
fetch('/api/festivals/').then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}).then(data=>{festivals=Array.isArray(data)?data:[];populatePrefectures();populateCategories();applyFilters()}).catch(error=>{console.error('Festival data could not be loaded',error);document.querySelector('#festival-list').innerHTML='<p class="empty-state">祭りの情報を読み込めませんでした。時間をおいて再度お試しください。</p>';document.querySelector('#map-count').textContent='読み込み失敗'});

window.renderMapMarkers=(items,targetDate=null)=>{festivals=Array.isArray(items)?items:festivals;if(targetDate instanceof Date&&!Number.isNaN(targetDate.valueOf())){const iso=targetDate.toISOString().slice(0,10);document.querySelector('#festival-date-start').value=iso;document.querySelector('#festival-date-end').value=iso}applyFilters()};
window.geocodingCacheQueue=geocodingCacheQueue;
window.saveGeocodingCache=()=>persist(GEOCODING_CACHE_KEY,geocodingCache);
