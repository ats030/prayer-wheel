const map=L.map('map').setView([36.2,138.2],5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);

const CACHE_KEY='omatsuri-map-image-cache-v5';
const GEOCODING_CACHE_KEY='omatsuri-map-geocoding-cache-v1';
const SELECTED_MARKER_Z_INDEX=10000;
const imageCache={};
const wikiContentCache={};
const wikiContentQueue={};
const geocodingCache={};
const geocodingCacheQueue={};
let festivals=[];
let visible=[];
let markers=new Map();
let selectedKey=null;
let selectedOrigin=null;
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
function mapCoordinates(f){
  const venue=venueData(f),hasVenuePoint=venue&&venue.latitude!==null&&venue.latitude!==''&&venue.longitude!==null&&venue.longitude!=='';
  const latitude=Number(hasVenuePoint?venue.latitude:f.latitude),longitude=Number(hasVenuePoint?venue.longitude:f.longitude);
  return Number.isFinite(latitude)&&Number.isFinite(longitude)?{latitude,longitude}:null;
}
function locationCacheKey(f){const point=mapCoordinates(f);return point?`${point.latitude.toFixed(5)},${point.longitude.toFixed(5)}`:''}
function locationPrecisionLabel(f){
  const venue=venueData(f);
  if(venue)return venue.precision==='exact'?'会場位置を確認済み':'会場周辺';
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
async function loadWikipediaContent(f){
  const title=f.wikipedia_title||f.label_ja;if(!title)return null;
  const cacheKey=`${f.qid||''}:${title}`;
  if(wikiContentCache[cacheKey])return wikiContentCache[cacheKey];
  if(wikiContentQueue[cacheKey])return wikiContentQueue[cacheKey];
  wikiContentQueue[cacheKey]=fetch(`/api/wiki/content?title=${encodeURIComponent(title)}&qid=${encodeURIComponent(f.qid||'')}`)
    .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()})
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
  const endLabel=start.getTime()===end.getTime()?'':start.getFullYear()===end.getFullYear()?`〜${end.getMonth()+1}月${end.getDate()}日`:`〜${end.getFullYear()}年${end.getMonth()+1}月${end.getDate()}日`;
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
function matchesDate(f,value){
  if(!value)return true;
  const target=new Date(`${value}T12:00:00`);
  return [...occurrenceRanges(f),...annualScheduleRanges(f,target.getFullYear())].some(({start,end})=>target>=start&&target<=end);
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
    const prefectureMatches=!prefecture||(f.prefecture===prefecture&&f.coordinate_prefecture===prefecture);
    return text.includes(q)&&prefectureMatches&&matchesDate(f,date);
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
function icon(selected){return L.divIcon({className:'',html:`<span class="festival-marker${selected?' selected':''}"></span>`,iconSize:[22,22],iconAnchor:[11,11],popupAnchor:[0,-12]})}
function renderMarkers(){
  markers.forEach(({marker})=>map.removeLayer(marker));markers=new Map();
  visible.forEach((f,index)=>{
    const point=mapCoordinates(f);if(!point)return;
    const key=festivalKey(f,index),selected=key===selectedKey;
    const marker=L.marker([point.latitude,point.longitude],{icon:icon(selected),zIndexOffset:selected?SELECTED_MARKER_Z_INDEX:0}).addTo(map);
    marker.bindTooltip(esc(f.label_ja||f.label_en||'名称未登録'),{direction:'top',offset:[0,-10]});
    marker.on('click',()=>selectFestival(key,'marker'));markers.set(key,{marker,festival:f});
  });
  if(selectedKey&&!markers.has(selectedKey))closeDetail(false);
}
function detail(f){
  const wiki=f.qid?`https://www.wikidata.org/wiki/${encodeURIComponent(f.qid)}`:'';
  const wikipediaTitle=f.wikipedia_title||f.label_ja;
  const pedia=wikipediaTitle?`https://ja.wikipedia.org/wiki/${encodeURIComponent(wikipediaTitle)}`:'';
  const culture=safeUrl(f.cultural_relaw?.url);
  const about=groundedDescription(f);
  const aboutBody=about.locationAware?`${esc(about.body)}「<span id="detail-about-location">${esc(f.prefecture||'地域未登録')}</span>」付近に登録されています。正確な会場は確認中です。`:esc(about.body);
  return `<article class="detail"><header class="detail-lead"><p class="detail-kicker">${esc(f.label_en||'Festival in Japan')}</p><h2 id="detail-title" tabindex="-1">${esc(f.label_ja||f.label_en||'名称未登録')}</h2></header><dl class="detail-facts"><div><dt>開催地</dt><dd id="detail-location">${locationMarkup(f.prefecture||'地域未登録',f)}${venueData(f)?'':'<span class="location-loading">詳細を確認中…</span>'}</dd></div><div><dt>次回開催日</dt><dd>${occurrenceMarkup(f)}</dd></div></dl><section class="detail-section" aria-labelledby="detail-about"><h3 id="detail-about">祭りについて</h3><p class="detail-description">${aboutBody}</p><p class="detail-description-status">${esc(about.status)}</p></section><section class="detail-section" aria-labelledby="detail-photo"><h3 id="detail-photo">写真・画像</h3><div id="detail-image"><p class="detail-image-status">画像を読み込んでいます…</p></div></section><section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典・関連情報</h3><nav class="detail-links" aria-label="出典">${wiki?`<a href="${wiki}" target="_blank" rel="noopener noreferrer">Wikidata<span aria-hidden="true">↗</span></a>`:''}${pedia?`<a href="${pedia}" target="_blank" rel="noopener noreferrer">Wikipedia<span aria-hidden="true">↗</span></a>`:''}${culture?`<a href="${esc(culture)}" target="_blank" rel="noopener noreferrer">文化庁<span aria-hidden="true">↗</span></a>`:''}</nav></section></article>`;
}
function selectFestival(key,origin){
  const entry=markers.get(key);if(!entry)return;selectedKey=key;selectedOrigin=origin;
  markers.forEach(({marker},markerKey)=>{const selected=markerKey===key;marker.setIcon(icon(selected));marker.setZIndexOffset(selected?SELECTED_MARKER_Z_INDEX:0)});
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
  status.innerHTML=`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">Wikipediaの概要<span aria-hidden="true">↗</span></a>${contentLicense?` · <a href="${esc(contentLicense)}" target="_blank" rel="noopener noreferrer">CC BY-SA 4.0<span aria-hidden="true">↗</span></a>`:''}（開催地は上欄を参照）`;
}
async function hydrateLocation(f,key){
  const location=await detailedLocation(f),element=document.querySelector('#detail-location'),aboutLocation=document.querySelector('#detail-about-location');
  if(element&&selectedKey===key){element.innerHTML=locationMarkup(location,f);if(aboutLocation)aboutLocation.textContent=location}
}
function closeDetail(restoreFocus=true){
  const key=selectedKey,origin=selectedOrigin;selectedKey=null;selectedOrigin=null;document.querySelector('#detail-panel').hidden=true;document.querySelector('.app-shell').classList.remove('has-detail');
  markers.forEach(({marker})=>{marker.setIcon(icon(false));marker.setZIndexOffset(0)});document.querySelectorAll('.festival-card').forEach(card=>card.setAttribute('aria-current','false'));
  requestAnimationFrame(()=>map.invalidateSize());
  if(restoreFocus&&key){
    const target=origin==='marker'?markers.get(key)?.marker.getElement():document.querySelector(`.festival-card[data-key="${CSS.escape(key)}"]`);
    target?.focus();
  }
}
async function hydrateImage(f,key){
  const [wikipediaContent,location]=await Promise.all([loadWikipediaContent(f),detailedLocation(f)]),contentIsRelevant=!wikipediaContent||isCompatibleWikipediaImage(wikipediaContent.description,f,location);
  let result=contentIsRelevant?imageCache[f.qid]:null,loadFailed=false;
  if(typeof result==='string'||(result?.url&&!result.license)){delete imageCache[f.qid];persist(CACHE_KEY,imageCache);result=null}
  if(!result&&f.qid&&contentIsRelevant){
    try{const response=await fetch(`/api/wiki/image?qid=${encodeURIComponent(f.qid)}`);if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();result={url:safeUrl(data.url),license:String(data.license||'').trim(),licenseUrl:safeUrl(data.license_url),artist:plainText(data.artist),credit:plainText(data.credit),sourceUrl:safeUrl(data.source_url)};imageCache[f.qid]=result;persist(CACHE_KEY,imageCache)}
    catch(error){loadFailed=true;console.warn(`Image could not be loaded for ${f.qid}`,error)}
  }
  if(!result?.url){
    if(wikipediaContent)loadFailed=false;
    if(wikipediaContent?.image_url&&contentIsRelevant){result={url:safeUrl(wikipediaContent.image_url),license:String(wikipediaContent.license||'').trim(),licenseUrl:safeUrl(wikipediaContent.license_url),artist:plainText(wikipediaContent.artist),credit:plainText(wikipediaContent.credit),sourceUrl:safeUrl(wikipediaContent.image_source_url)};loadFailed=false}
  }
  const container=document.querySelector('#detail-image'),content=document.querySelector('#detail-content');if(!container||selectedKey!==key)return;
  if(loadFailed){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">画像を取得できませんでした。</p>';return}
  if(!result?.url){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">表示できる画像が登録されていません。</p>';return}
  if(!result.license){content.dataset.state='error';container.innerHTML='<p class="detail-image-status">画像のライセンス情報を確認できないため、表示していません。</p>';return}
  const source=result.sourceUrl||commonsFilePage(result.url);
  const license=result.licenseUrl?`<a href="${esc(result.licenseUrl)}" target="_blank" rel="noopener noreferrer" aria-label="ライセンス ${esc(result.license)}">${esc(result.license)}<span aria-hidden="true">↗</span></a>`:esc(result.license);
  const creator=result.artist||result.credit;
  content.dataset.state='success';container.innerHTML=`<button class="detail-image-button" type="button" aria-label="${esc(f.label_ja||'祭り')}の画像を拡大"><img class="detail-image" src="${esc(result.url)}" alt="${esc(f.label_ja||'祭り')}の画像"></button><p class="license">${creator?`${esc(creator)} · `:''}${license}${source?` · <a href="${esc(source)}" target="_blank" rel="noopener noreferrer" aria-label="Wikimedia Commonsの画像出典">Commons<span aria-hidden="true">↗</span></a>`:''}</p>`;
  container.querySelector('button').addEventListener('click',()=>openLightbox(result.url,f.label_ja));
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
