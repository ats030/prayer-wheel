const map=L.map('map',{preferCanvas:true}).setView([36.2,138.2],5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);

let tokusan=[];
let visible=[];
let markers=new Map();
let markerItems=new Map();
let selectedKey=null;
let selectedOrigin=null;
let selectedItem=null;

const IMAGE_CACHE_KEY='tokusan-map-image-cache-v1';
const imageCache={};
try{Object.assign(imageCache,JSON.parse(localStorage.getItem(IMAGE_CACHE_KEY)||'{}'))}catch{}

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
async function fetchJSONWithRetry(url){
  let lastError;
  for(let attempt=0;attempt<2;attempt++){
    try{const response=await fetch(url);if(response.ok)return response.json();lastError=new Error(`HTTP ${response.status}`)}catch(error){lastError=error}
    if(attempt===0)await new Promise(resolve=>setTimeout(resolve,500));
  }
  throw lastError;
}

const CATEGORY_META=[
  {code:'sa',label:'酒・醸造'},
  {code:'te',label:'茶・飲料'},
  {code:'ui',label:'魚介'},
  {code:'sa2',label:'農産'},
  {code:'am',label:'砂糖・和菓子'},
  {code:'ko',label:'穀物・調味料'},
  {code:'ry',label:'料理・惣菜'},
  {code:'ta',label:'陶磁器'},
  {code:'or',label:'織物'},
  {code:'ri',label:'漆器'},
  {code:'kg',label:'その他工芸'},
];
function categoryCode(o){return CATEGORY_META.some(m=>m.code===o.category)?String(o.category):'none'}
function categoryLabel(code){const meta=CATEGORY_META.find(m=>m.code===code);return meta?meta.label:'未分類'}

function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function itemKey(o,index=0){return o.qid||`${o.label_ja}-${o.latitude}-${o.longitude}-${index}`}
function hasCoordinates(o){const lat=Number(o.latitude),lng=Number(o.longitude);return Number.isFinite(lat)&&Number.isFinite(lng)&&(lat!==0||lng!==0)}

function populatePrefectures(){
  const list=document.querySelector('#prefecture');
  const prefectures=Array.from(new Set(tokusan.map(o=>o.prefecture).filter(Boolean))).sort((a,b)=>a.localeCompare(b));
  for(const p of prefectures){
    const option=document.createElement('option');
    option.value=p;option.textContent=p;
    list.appendChild(option);
  }
}
function populateCategories(){
  const select=document.querySelector('#category');
  for(const meta of CATEGORY_META){
    const option=document.createElement('option');
    option.value=meta.code;option.textContent=meta.label;
    select.appendChild(option);
  }
}
function renderLegend(){
  const legend=document.querySelector('#map-legend');
  if(!legend||legend.childElementCount)return;
  legend.innerHTML=CATEGORY_META.map(meta=>`<span><span class="legend-dot" style="background:var(--color-cat-${meta.code})"></span>${esc(meta.label)}</span>`).join('');
}

function applyFilters(){
  const keyword=document.querySelector('#keyword').value.trim().toLowerCase();
  const prefecture=document.querySelector('#prefecture').value;
  const category=document.querySelector('#category').value;
  visible=tokusan.filter(o=>{
    if(prefecture&&o.prefecture!==prefecture)return false;
    if(category&&categoryCode(o)!==category)return false;
    if(keyword){
      const haystack=[o.label_ja,o.label_en,o.place,o.prefecture,o.city,categoryLabel(categoryCode(o))].filter(Boolean).join(' ').toLowerCase();
      if(!haystack.includes(keyword))return false;
    }
    return true;
  });
  renderList();
  renderMarkers();
}

function renderList(){
  const list=document.querySelector('#tokusan-list');
  document.querySelector('#result-count').textContent=String(visible.length);
  const located=visible.filter(hasCoordinates).length;
  if(visible.length===0){
    list.innerHTML='<p class="empty-state">条件に一致する特産物はありません。<a href="#" id="empty-clear">条件をクリア</a></p>';
    document.querySelector('#empty-clear').addEventListener('click',e=>{e.preventDefault();document.querySelector('#clear-filters').click()});
    return;
  }
  list.innerHTML=visible.map((o,i)=>{
    const key=itemKey(o,i);
    const cat=categoryCode(o);
    const catSpan=cat!=='none'?`<span>${esc(categoryLabel(cat))}</span>`:'';
    const placeSpan=o.prefecture_level?'<span>都道府県単位</span>':o.place&&o.place!==o.prefecture?`<span>${esc(o.place)}</span>`:'';
    return `<button type="button" class="tokusan-card" data-key="${esc(key)}" aria-current="${key===selectedKey}"><span class="card-index">${String(i+1).padStart(2,'0')}</span><span><span class="card-name">${esc(o.label_ja||o.label_en||o.qid)}</span><span class="card-meta"><span>${esc(o.prefecture||'地域未登録')}</span>${catSpan}${placeSpan}</span></span></button>`;
  }).join('');
  list.querySelectorAll('button').forEach(card=>card.addEventListener('click',()=>selectItem(card.dataset.key,'list')));
}

function markerIcon(o,selected){
  const className=`tokusan-marker cat-${categoryCode(o||null)}${selected?' selected':''}`;
  return L.divIcon({className:'',html:`<div class="${className}"></div>`,iconSize:[22,22],iconAnchor:[11,11]});
}

function renderMarkers(){
  for(const [key,marker] of markers)map.removeLayer(marker);
  markers.clear();
  markerItems.clear();
  let locatedCount=0;
  const bounds=[];
  visible.forEach((o,i)=>{
    const key=itemKey(o,i);
    if(!hasCoordinates(o))return;
    const marker=L.marker([o.latitude,o.longitude],{icon:markerIcon(o,key===selectedKey),title:o.label_ja||o.label_en||o.qid});
    marker.bindTooltip(`${o.label_ja||o.label_en||o.qid}${o.prefecture?'（'+o.prefecture+(o.prefecture_level?'・都道府県単位':'')+'）':''}`,{direction:'top',offset:[0,-8]});
    marker.on('click',()=>selectItem(key,'marker'));
    marker.addTo(map);
    markers.set(key,marker);
    markerItems.set(key,o);
    bounds.push([o.latitude,o.longitude]);
    locatedCount+=1;
  });
  document.querySelector('#map-count').textContent=`${visible.length} 件中 ${locatedCount} 件の位置を表示`;
  if(bounds.length===1)map.setView(bounds[0],9);
  else if(bounds.length>1)map.fitBounds(L.latLngBounds(bounds).pad(0.2));
}

function selectItem(key,origin){
  const prevKey=selectedKey;
  const prevItem=selectedItem;
  selectedKey=key;
  const item=visible.find(o=>itemKey(o,visible.indexOf(o))===key);
  if(!item){selectedKey=prevKey;selectedItem=prevItem;selectedOrigin=null;return}
  for(const button of document.querySelectorAll('.tokusan-card'))button.setAttribute('aria-current',button.dataset.key===key?'true':'false');
  if(prevItem&&prevKey!==key){
    const prevMarker=markers.get(prevKey);
    if(prevMarker)prevMarker.setIcon(markerIcon(prevItem,false));
  }
  const marker=markers.get(key);
  if(marker)marker.setIcon(markerIcon(item,true));
  selectedItem=item;
  selectedOrigin=origin;
  showDetail(item,origin);
  if(origin==='list'&&hasCoordinates(item)){
    map.flyTo([item.latitude,item.longitude],Math.max(map.getZoom(),8),{duration:.55});
  }
  const focusTarget=document.querySelector('#detail-title');
  document.querySelector('#detail-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
  requestAnimationFrame(()=>{map.invalidateSize();focusTarget?.focus({preventScroll:origin!=='marker'})});
}

const DETAIL_SECTIONS=[['about',o=>`${o.label_ja||'この特産物'}について`],['history',()=>'歴史'],['production',()=>'産地・製法'],['visit',()=>'購入・観光']];
const sectionsCache=new Map();
async function hydrateSections(o){
  const qid=o.qid,container=document.querySelector('#detail-sections');
  if(!qid||!container)return;
  let data=sectionsCache.get(qid);
  if(!data){
    try{data=await fetchJSONWithRetry(`/api/sections/${encodeURIComponent(qid)}`)}
    catch(error){console.warn(`Sections could not be loaded for ${qid}`,error);data=null}
    if(data&&!data.sections_unavailable&&!data.sections_retry)sectionsCache.set(qid,data);
  }
  if(selectedItem!==o)return;
  if(!data||data.sections_unavailable){container.innerHTML='<p class="detail-image-status">解説を読み込めませんでした。もう一度開いてください。</p>';return}
  container.innerHTML=renderSections(o,data.sections&&typeof data.sections==='object'?data.sections:{});
}
function renderSections(o,sections){
  const link=(url,label)=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label}<span aria-hidden="true">↗</span></a>`;
  return DETAIL_SECTIONS.map(([key,heading])=>{
    const payload=sections[key]||{};
    const summary=String(payload.summary||'').trim();
    const items=Array.isArray(payload.items)?payload.items:[];
    const blocks=Array.isArray(payload.blocks)?payload.blocks:[];
    if(!summary&&!items.length&&!blocks.length)return'';
    const itemsMarkup=items.map(item=>{
      const from=String(item.from||'').trim(),to=String(item.to||'').trim();
      const text=[from&&to?`${from} → ${to}`:'',String(item.value||'').trim()].filter(Boolean).join(' ');
      return `<div><dt>${esc(String(item.label||'').trim())}</dt><dd>${esc(text)}</dd></div>`;
    }).join('');
    const blockMarkup=blocks.map(b=>{
      const h=String(b.heading||'').trim();
      return (h?`<p class="detail-subheading">${esc(h)}</p>`:'')+`<p>${esc(String(b.text||''))}</p>`;
    }).join('');
    const source=safeUrl(payload.source_url)||safeUrl(o.source_url);
    const attribution=[summary||items.length?'AIによる要約':'編集あり'];
    if(source)attribution.push(link(source,'Wikipedia'));
    attribution.push(link('https://creativecommons.org/licenses/by-sa/4.0/deed.ja','CC BY-SA 4.0'));
    const body=[
      summary?`<p class="detail-summary">${esc(summary)}</p>`:'',
      items.length?`<dl class="section-items">${itemsMarkup}</dl>`:'',
      blockMarkup?(summary||items.length?`<details class="section-source"><summary>原文を読む</summary>${blockMarkup}</details>`:`<div class="section-source-text">${blockMarkup}</div>`):'',
    ].join('');
    return `<section class="detail-section" aria-labelledby="detail-${key}"><h3 id="detail-${key}">${esc(heading(o))}</h3>${body}<p class="image-license">${attribution.join(' · ')}</p></section>`;
  }).join('');
}
function placeFact(o){
  if(o.prefecture_level)return `${esc(o.prefecture||o.place||'—')}<span class="detail-note">都道府県単位。地図上は都道府県庁の位置に表示しています。</span>`;
  return `${esc(o.place||o.prefecture||'—')}<span class="detail-note">${hasCoordinates(o)?'推定。地図上の位置は目安です。':'推定。地図上には表示していません。'}</span>`;
}

function showDetail(o,origin){
  const panel=document.querySelector('#detail-panel');
  const content=document.querySelector('#detail-content');
  const cat=categoryCode(o);
  panel.hidden=false;
  document.querySelector('.app-shell').classList.add('has-detail');
  document.querySelector('#detail-origin').textContent=origin==='marker'?'地図から選択':`産地：${o.place||o.prefecture||'不明'}`;
  const badge=cat!=='none'?`<p class="badge-line"><span class="badge" style="color:var(--color-cat-${cat});border-color:var(--color-cat-${cat})">${esc(categoryLabel(cat))}</span></p>`:'';
  const rows=[
    ['産地',placeFact(o)],
  ];
  const maker=(typeof o.maker==='string')?o.maker.trim():'';
  if(maker)rows.push(['生産者・ブランド',esc(maker)]);
  const links=[
    o.source_url?['Wikipedia',o.source_url]:null,
    o.qid?['Wikidata',`https://www.wikidata.org/wiki/${encodeURIComponent(o.qid)}`]:null,
  ].filter(Boolean);
  content.innerHTML=`<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(o.label_ja||o.label_en||o.qid)}</h2>${badge}</header>
    <dl class="detail-facts">${rows.map(([dt,dd])=>`<div><dt>${dt}</dt><dd>${dd}</dd></div>`).join('')}</dl>
    <section class="detail-section" aria-labelledby="detail-photo"><h3 id="detail-photo">写真</h3><div id="detail-image"><p class="detail-image-status">画像を読み込んでいます…</p></div></section>
    <div id="detail-sections" aria-live="polite"></div>
    ${links.length?`<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典</h3><nav class="detail-links" aria-label="出典">${links.map(([label,url])=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label}<span aria-hidden="true">↗</span></a>`).join('')}</nav></section>`:''}
  </article>`;
  hydrateImage(o);
  hydrateSections(o);
}

async function hydrateImage(o){
  const qid=o.qid;
  if(!qid)return;
  const container=document.querySelector('#detail-image');
  if(!container)return;
  if(imageCache[qid]){
    const cached=imageCache[qid];
    if(cached.url&&cached.license){renderImage(container,cached,o);return}
  }
  try{
    const data=await fetchJSONWithRetry(`/api/wikiimage?qid=${encodeURIComponent(qid)}`);
    const result={url:safeUrl(data.url),license:String(data.license||'').trim(),licenseUrl:safeUrl(data.license_url),artist:plainText(data.artist),credit:plainText(data.credit),sourceUrl:safeUrl(data.source_url)};
    imageCache[qid]=result;
    try{localStorage.setItem(IMAGE_CACHE_KEY,JSON.stringify(imageCache))}catch{}
    if(selectedItem!==o)return;
    if(!result.url){container.innerHTML='<p class="detail-image-status">表示できる画像が登録されていません。</p>';return}
    if(!result.license){container.innerHTML='<p class="detail-image-status">画像のライセンス情報を確認できないため、表示していません。</p>';return}
    renderImage(container,result,o);
  }catch(error){
    console.warn(`Image could not be loaded for ${qid}`,error);
    if(selectedItem!==o)return;
    container.innerHTML='<p class="detail-image-status">表示できる画像が登録されていません。</p>';
  }
}
function renderImage(container,result,o){
  const source=result.sourceUrl||commonsFilePage(result.url);
  const license=result.licenseUrl?`<a href="${esc(result.licenseUrl)}" target="_blank" rel="noopener noreferrer">${esc(result.license)}<span aria-hidden="true">↗</span></a>`:esc(result.license);
  const creator=result.artist||result.credit;
  const name=o.label_ja||o.label_en||'特産物';
  container.innerHTML=`<button class="detail-image-button" type="button" aria-label="${esc(name)}の画像を拡大"><img class="detail-image" src="${esc(result.url)}" alt="${esc(name)}の画像"></button><p class="image-license">${creator?`${esc(creator)} · `:''}${license}${source?` · <a href="${esc(source)}" target="_blank" rel="noopener noreferrer" aria-label="Wikimedia Commons の画像出典">Commons<span aria-hidden="true">↗</span></a>`:''}</p>`;
  container.querySelector('button').addEventListener('click',()=>openLightbox(result.url,name));
}
function openLightbox(url,alt){const dialog=document.querySelector('#lightbox'),image=document.querySelector('#lightbox-image');image.src=url;image.alt=`${alt||'特産物'}の拡大画像`;dialog.showModal()}
function closeLightbox(){const dialog=document.querySelector('#lightbox');if(dialog.open)dialog.close();document.querySelector('#lightbox-image').src='';document.querySelector('#lightbox-image').removeAttribute('alt')}

function closeDetail(){
  const key=selectedKey,origin=selectedOrigin;
  if(selectedKey&&selectedItem){
    const m=markers.get(selectedKey);
    if(m)m.setIcon(markerIcon(selectedItem,false));
  }
  selectedItem=null;
  selectedKey=null;
  selectedOrigin=null;
  document.querySelector('#detail-panel').hidden=true;
  document.querySelector('.app-shell').classList.remove('has-detail');
  document.querySelectorAll('.tokusan-card').forEach(card=>card.setAttribute('aria-current','false'));
  requestAnimationFrame(()=>map.invalidateSize());
  if(key){
    const target=origin==='marker'?document.querySelector('#map'):document.querySelector(`.tokusan-card[data-key="${CSS.escape(key)}"]`);
    target?.focus();
  }
}

document.querySelector('#keyword').addEventListener('input',applyFilters);
document.querySelector('#prefecture').addEventListener('change',applyFilters);
document.querySelector('#category').addEventListener('change',applyFilters);
document.querySelector('#clear-filters').addEventListener('click',()=>{document.querySelector('#keyword').value='';document.querySelector('#prefecture').value='';document.querySelector('#category').value='';applyFilters();document.querySelector('#keyword').focus()});
document.querySelector('.detail-close').addEventListener('click',closeDetail);
document.querySelector('.lightbox-close').addEventListener('click',closeLightbox);
document.querySelector('#lightbox').addEventListener('click',e=>{if(e.target.id==='lightbox')closeLightbox()});
document.querySelector('#lightbox').addEventListener('cancel',closeLightbox);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeLightbox()});

fetch('/api/tokusan/').then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}).then(data=>{
  tokusan=Array.isArray(data)?data:[];
  populatePrefectures();
  populateCategories();
  renderLegend();
  applyFilters();
}).catch(error=>{
  console.error('Tokusan data could not be loaded',error);
  document.querySelector('#tokusan-list').innerHTML='<p class="empty-state">特産物の情報を読み込めませんでした。fetch_tokusan.py と build_db.py を実行してデータベースを作成してください。</p>';
  document.querySelector('#map-count').textContent='読み込み失敗';
});
