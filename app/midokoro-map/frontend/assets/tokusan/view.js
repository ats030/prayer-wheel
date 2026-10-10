export function mount(context) {
const {map, document, fetch} = context;

let tokusan=[];
let visible=[];
let markers=new Map();
// Nearby markers cluster by zoom; identical coordinates spiderfy with legs to the registered point.
const clusterLayer=L.markerClusterGroup({
  maxClusterRadius:40,
  showCoverageOnHover:false,
  spiderfyDistanceMultiplier:1.3,
  // Clicks are handled below so tall stacks can open a list instead of a spiral.
  spiderfyOnMaxZoom:false,
  zoomToBoundsOnClick:false,
  iconCreateFunction:cluster=>{
    const count=cluster.getChildCount();
    const size=count<10?30:count<100?36:42;
    return L.divIcon({className:'tokusan-cluster-anchor',html:`<span class="tokusan-cluster" aria-label="${count}件の特産物">${count}</span>`,iconSize:[size,size]});
  },
}).addTo(map);
// Prefecture representative points stack up to dozens of items whose spiral is unreadable,
// so a tall stack of identical coordinates lists its items by source region instead.
const STACK_LIST_MIN=9;
let itemByKey=new Map();
clusterLayer.on('clusterclick clusterkeypress',e=>{
  if(e.type==='clusterkeypress'&&e.originalEvent?.keyCode!==13)return;
  const cluster=e.layer;
  const children=cluster.getAllChildMarkers();
  const point=children[0].getLatLng();
  const stacked=children.every(marker=>marker.getLatLng().equals(point));
  // Zooming cannot split a stack, nor anything at maximum zoom.
  const listed=(stacked||map.getZoom()>=map.getMaxZoom())&&children.length>=STACK_LIST_MIN;
  if(listed)openStackList(stacked?point:cluster.getLatLng(),children,stacked);
  else if(!stacked&&map.getZoom()<map.getMaxZoom())cluster.zoomToBounds();
  else cluster.spiderfy();
  // Keyboard focus would fall to the page when the focused cluster icon is replaced.
  if(e.type==='clusterkeypress')(listed?document.querySelector('.stack-list button'):map.getContainer()).focus();
});
function entriesPrefecture(keys){
  const prefectures=new Set(keys.map(key=>itemByKey.get(key).prefecture));
  return prefectures.size===1?`${[...prefectures][0]} `:'';
}
function openStackList(point,children,stacked){
  const keys=children.map(marker=>marker.options.itemKey);
  const groups=new Map();
  for(const key of keys){
    const o=itemByKey.get(key);
    const label=regionLabel(o);
    if(!groups.has(label))groups.set(label,[]);
    groups.get(label).push([key,o]);
  }
  const rank=label=>label==='県全域'?0:label==='地域未詳'?2:1;
  const sorted=[...groups].sort(([a],[b])=>rank(a)-rank(b)||a.localeCompare(b,'ja'));
  const first=itemByKey.get(keys[0]);
  const office=o=>o.coordinate_kind==='municipality_office'||o.coordinate_kind==='named_area_office';
  const placeOf=o=>office(o)?o.coordinate_label||o.city:o.prefecture;
  // A named area often shares its office with the same-named municipality (八代地域 / 八代市).
  const uniform=keys.every(key=>{const o=itemByKey.get(key);return o.coordinate_kind===first.coordinate_kind&&placeOf(o)===placeOf(first)});
  const place=uniform||!office(first)?placeOf(first):first.city;
  const kind=uniform?positionLabel(first):office(first)?'役場位置':'';
  const heading=stacked?`${esc(place||'')}（${esc(kind||'同じ位置')}）の ${keys.length} 件`:`${esc(entriesPrefecture(keys))}この付近の ${keys.length} 件`;
  const body=sorted.map(([label,entries])=>`<section><h3>${esc(label)}（${entries.length}件）</h3><ul>${entries.map(([key,o])=>`<li><button type="button" data-key="${esc(key)}">${esc(o.label_ja||o.label_en||o.qid)}</button></li>`).join('')}</ul></section>`).join('');
  const content=document.createElement('div');
  content.className='stack-list';
  content.innerHTML=`<h2>${heading}</h2>${body}`;
  content.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>selectItem(button.dataset.key,'marker')));
  L.popup({maxHeight:320,className:'stack-popup'}).setLatLng(point).setContent(content).openOn(map);
}
let selectedKey=null;
let selectedOrigin=null;
let selectedItem=null;

const IMAGE_CACHE_KEY='midokoro-map-tokusan-image-cache-v2';
let imageCatalog={};
let imageCatalogReady=false;
let imageCatalogLoad=null;
let blockedImageFallback=new Set();
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
async function fetchJSONWithRetry(url,timeout){
  let lastError;
  for(let attempt=0;attempt<2;attempt++){
    const controller=timeout?new AbortController():null;
    const timer=timeout?setTimeout(()=>controller.abort(),timeout):null;
    try{const response=await fetch(url,controller?{signal:controller.signal}:undefined);if(response.ok)return await response.json();lastError=new Error(`HTTP ${response.status}`)}catch(error){lastError=error}finally{if(timer)clearTimeout(timer)}
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
  {code:'nk',label:'畜産・乳製品'},
  {code:'sz',label:'木材・自然素材'},
  {code:'se',label:'生活用品'},
  {code:'ka',label:'花卉'},
];
function categoryCode(o){return CATEGORY_META.some(m=>m.code===o.category)?String(o.category):'none'}
function categoryLabel(code){const meta=CATEGORY_META.find(m=>m.code===code);return meta?meta.label:'未分類'}

function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function itemKey(o,index=0){return o.qid||`${o.label_ja}-${o.latitude}-${o.longitude}-${index}`}
function hasCoordinates(o){const lat=Number(o.latitude),lng=Number(o.longitude);return Number.isFinite(lat)&&Number.isFinite(lng)&&(lat!==0||lng!==0)}
function positionLabel(o){return o.coordinate_kind==='municipality_office'?'産地代表位置':o.coordinate_kind==='named_area_office'?'地域代表位置':o.prefecture_level?'都道府県代表位置':''}

// Region membership follows source areas, never the marker's representative point.
let regionsByPrefecture=new Map();
function regionLabel(o){
  if(o.region_scope==='prefecture')return '県全域';
  const regions=regionsByPrefecture.get(o.prefecture)?.regions||[];
  const names=regions.filter(r=>(o.region_ids||[]).includes(r.id)).map(r=>r.label);
  return names.length?names.join(' ／ '):'地域未詳';
}

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
  document.querySelector('#category-options').innerHTML=CATEGORY_META.map(meta=>[meta.code,meta.label]).map(([value,label])=>`<label class="multi-option"><input type="checkbox" value="${esc(value)}">${esc(label)}</label>`).join('');
}
function selectedCategories(){return [...document.querySelectorAll('#category-options input:checked')].map(input=>input.value)}
function updateCategorySummary(){const labels=[...document.querySelectorAll('#category-options input:checked')].map(input=>input.parentElement.textContent);document.querySelector('#category-summary').textContent=!labels.length?'すべて':labels.length===1?labels[0]:`${labels[0]} ほか${labels.length-1}`}
function clearCategories(){document.querySelectorAll('#category-options input').forEach(input=>{input.checked=false});updateCategorySummary()}
function renderLegend(){
  const legend=document.querySelector('#map-legend');
  if(!legend||legend.childElementCount)return;
  legend.innerHTML=CATEGORY_META.map(meta=>`<span><span class="legend-dot" style="background:var(--color-cat-${meta.code})"></span>${esc(meta.label)}</span>`).join('');
}

function applyFilters(){
  const keyword=document.querySelector('#keyword').value.trim().toLowerCase();
  const prefecture=document.querySelector('#prefecture').value;
  const categories=selectedCategories();
  visible=tokusan.filter(o=>{
    if(prefecture&&o.prefecture!==prefecture)return false;
    if(categories.length&&!categories.includes(categoryCode(o)))return false;
    if(keyword){
      const haystack=[o.label_ja,o.label_en,o.place,o.prefecture,o.city,o.production_area,o.maker,categoryLabel(categoryCode(o))].filter(Boolean).join(' ').toLowerCase();
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
    const placeSpan=`<span>${esc(regionLabel(o))}</span>${positionLabel(o)?`<span>${esc(positionLabel(o))}</span>`:''}`;
    return `<button type="button" class="tokusan-card" data-key="${esc(key)}" aria-current="${key===selectedKey}"><span class="card-index">${String(i+1).padStart(2,'0')}</span><span><span class="card-name">${esc(o.label_ja||o.label_en||o.qid)}</span><span class="card-meta"><span>${esc(o.prefecture||'地域未登録')}</span>${catSpan}${placeSpan}</span></span></button>`;
  }).join('');
  list.querySelectorAll('button').forEach(card=>card.addEventListener('click',()=>selectItem(card.dataset.key,'list')));
}

function markerIcon(o,selected){
  const className=`tokusan-marker cat-${categoryCode(o||null)}${selected?' selected':''}`;
  const label=o.label_ja||o.label_en||o.qid;
  return L.divIcon({className:'tokusan-marker-anchor',html:`<button type="button" class="${className}" aria-label="${esc(label)}"></button>`,iconSize:[22,22],iconAnchor:[11,11]});
}

// zoomToShowLayer keeps its listeners until they fire, so a newer selection or a
// re-render could spiderfy a stale cluster. Track one pending reveal and drop it instead.
// Mirrors zoomToShowLayer from the pinned markercluster 1.5.3, including its private fields.
let cancelReveal=()=>{};
function revealMarker(marker){
  cancelReveal();
  const parent=marker.__parent;
  if(!parent)return;
  const latlng=marker.getLatLng();
  if(marker._icon&&map.getBounds().contains(latlng))return;
  const show=()=>{
    if(clusterLayer._inZoomAnimation||!(marker._icon||parent._icon))return;
    cancelReveal();
    if(!marker._icon)parent.spiderfy();
  };
  map.on('moveend',show);
  clusterLayer.on('animationend',show);
  cancelReveal=()=>{
    map.off('moveend',show);
    clusterLayer.off('animationend',show);
    cancelReveal=()=>{};
  };
  if(parent._zoom<Math.round(map.getZoom()))map.panTo(latlng);
  else parent.zoomToBounds();
}

function renderMarkers(){
  cancelReveal();
  map.closePopup();
  clusterLayer.clearLayers();
  markers.clear();
  itemByKey.clear();
  const bounds=[];
  visible.forEach((o,i)=>{
    if(!hasCoordinates(o))return;
    const key=itemKey(o,i);
    const label=o.label_ja||o.label_en||o.qid;
    const marker=L.marker([o.latitude,o.longitude],{icon:markerIcon(o,key===selectedKey),title:label,keyboard:false,itemKey:key});
    marker.bindTooltip(`${label}${positionLabel(o)?`（${positionLabel(o)}）`:''}`,{direction:'top',offset:[0,-8]});
    marker.on('click',()=>selectItem(key,'marker'));
    markers.set(key,marker);
    itemByKey.set(key,o);
    bounds.push([o.latitude,o.longitude]);
  });
  clusterLayer.addLayers([...markers.values()]);
  document.querySelector('#map-count').textContent=`${visible.length} 件中 ${markers.size} 件の位置を表示`;
}

function selectItem(key,origin){
  cancelReveal();
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
  if(origin==='list'&&marker){
    revealMarker(marker);
  }else if(origin==='list'&&hasCoordinates(item)){
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
    try{data=await fetchJSONWithRetry(`/api/${context.summariesOnly?'summary':'sections'}/${encodeURIComponent(qid)}`)}
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
    if(!summary&&!items.length)return'';
    const itemsMarkup=items.map(item=>{
      const from=String(item.from||'').trim(),to=String(item.to||'').trim();
      const text=[from&&to?`${from} → ${to}`:'',String(item.value||'').trim()].filter(Boolean).join(' ');
      return `<div><dt>${esc(String(item.label||'').trim())}</dt><dd>${esc(text)}</dd></div>`;
    }).join('');
    const source=safeUrl(payload.source_url)||safeUrl(o.source_url);
    const official=Boolean(o.description);
    const attribution=[official?'AIによる要約(出典をもとに編集)':'AIによる要約'];
    if(source)attribution.push(link(source,official?o.source_name||'公式情報':'Wikipedia'));
    if(official&&source&&['www.maff.go.jp','www.rinya.maff.go.jp','www.meti.go.jp'].includes(new URL(source).hostname))attribution.push(link('https://www.digital.go.jp/resources/open_data/public_data_license_v1.0','PDL1.0'));
    if(!official)attribution.push(link('https://creativecommons.org/licenses/by-sa/4.0/deed.ja','CC BY-SA 4.0'));
    const body=[
      summary?`<p class="detail-summary">${esc(summary)}</p>`:'',
      items.length?`<dl class="section-items">${itemsMarkup}</dl>`:'',
    ].join('');
    return `<section class="detail-section" aria-labelledby="detail-${key}"><h3 id="detail-${key}">${esc(heading(o))}</h3>${body}<p class="image-license">${attribution.join(' · ')}</p></section>`;
  }).join('');
}
function placeFact(o){
  if(o.coordinate_kind==='municipality_office'){
    const source=safeUrl(o.coordinate_source_url);
    return `${esc(o.coordinate_label||o.city||o.prefecture)}<span class="detail-note">出典の産地・伝承地域：${esc(o.production_area)}</span><span class="detail-note">産地の代表位置。${esc(o.coordinate_label||o.city)}の役場位置を使っています。実際の生産地点ではありません。</span>${source?`<span class="detail-note">位置の出典：<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">${esc(o.coordinate_source_name)}</a>（CC BY 4.0）をもとに代表点を選定。</span>`:''}`;
  }
  if(o.coordinate_kind==='named_area_office'){
    const source=safeUrl(o.coordinate_source_url);
    return `${esc(o.coordinate_label)}<span class="detail-note">出典の産地・伝承地域：${esc(o.production_area)}</span><span class="detail-note">地域の代表位置。産地の最初の地名「${esc(o.coordinate_label)}」を、同名の${esc(o.city)}の役場位置で表しています。地域の範囲や実際の生産地点ではありません。</span>${source?`<span class="detail-note">位置の出典：<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">${esc(o.coordinate_source_name)}</a>（CC BY 4.0）をもとに代表点を選定。</span>`:''}`;
  }
  if(o.prefecture_level)return `${esc(o.prefecture||o.place||'—')}${o.production_area?`<span class="detail-note">出典の産地・伝承地域：${esc(o.production_area)}</span>`:''}<span class="detail-note">都道府県単位。地図上は都道府県庁の位置に表示しています。</span>`;
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
    safeUrl(o.source_url)?[o.source_name||'出典',safeUrl(o.source_url)]:null,
    /^Q\d+$/.test(o.qid||'')?['Wikidata',`https://www.wikidata.org/wiki/${encodeURIComponent(o.qid)}`]:null,
  ].filter(Boolean);
  content.innerHTML=`<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(o.label_ja||o.label_en||o.qid)}</h2>${badge}</header>
    <dl class="detail-facts">${rows.map(([dt,dd])=>`<div><dt>${dt}</dt><dd>${dd}</dd></div>`).join('')}</dl>
    <section class="detail-section" aria-labelledby="detail-photo"><h3 id="detail-photo">写真</h3><div id="detail-image"><p class="detail-image-status">画像を読み込んでいます…</p></div></section>
    <div id="detail-sections" aria-live="polite"></div>
    ${amazonLink(o)}
    ${furusatoLink(o)}
    ${links.length?`<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典</h3><nav class="detail-links" aria-label="出典">${links.map(([label,url])=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label}<span aria-hidden="true">↗</span></a>`).join('')}</nav></section>`:''}
  </article>`;
  hydrateImage(o);
  hydrateSections(o);
}

let furusatoAffiliateCatalog={};

function furusatoAffiliateHTML(o){
  // Only trusted, issued text anchors are accepted; return the original source.
  const entry=furusatoAffiliateCatalog[o.qid];
  if(!entry||entry.label!==o.label_ja||entry.prefecture!==o.prefecture||typeof entry.html!=='string')return'';
  if(!context.config.affiliateOrigins.includes(location.origin))return'';
  const template=document.createElement('template');
  template.innerHTML=entry.html;
  if(template.content.childNodes.length!==1)return'';
  const anchor=template.content.firstChild;
  if(anchor.nodeName!=='A'||!anchor.textContent.trim()||[...anchor.childNodes].some(n=>n.nodeType!==Node.TEXT_NODE))return'';
  if(!anchor.textContent.includes(o.label_ja)||!anchor.textContent.includes(o.prefecture))return'';
  if([...anchor.attributes].some(a=>!['href','target','rel','style'].includes(a.name)))return'';
  if(anchor.getAttribute('target')!=='_blank'||anchor.getAttribute('rel')!=='nofollow sponsored noopener'||anchor.getAttribute('style')!=='word-wrap:break-word;')return'';
  try{
    const url=new URL(anchor.getAttribute('href'));
    if(url.origin!=='https://hb.afl.rakuten.co.jp'||url.username||url.password||!/^\/hgc\/[a-f0-9.]+\/$/.test(url.pathname)||url.searchParams.get('link_type')!=='text')return'';
    const destination=new URL(url.searchParams.get('pc'));
    const expected=`/search/mall/ふるさと納税 ${o.label_ja} ${o.prefecture}/`;
    if(destination.origin!=='https://search.rakuten.co.jp'||destination.username||destination.password||destination.search||destination.hash||decodeURIComponent(destination.pathname).replace(/\+/g,' ')!==expected)return'';
    if(url.searchParams.has('m'))return'';
  }catch{return''}
  return entry.html;
}

async function loadFurusatoAffiliateCatalog(){
  const data=await fetchJSONWithRetry('/furusato-affiliate.json?v=20261006b');
  if(!data||typeof data!=='object'||Array.isArray(data))throw new Error('Invalid furusato affiliate catalog');
  furusatoAffiliateCatalog=data;
  const section=document.querySelector('[aria-labelledby="detail-furusato"]');
  if(selectedItem&&section)section.outerHTML=furusatoLink(selectedItem);
}

function furusatoLink(o){
  const url=safeUrl(o.furusato_search_url);
  if(!url||new URL(url).origin!=='https://search.rakuten.co.jp'||!new URL(url).pathname.startsWith('/search/mall/'))return'';
  const affiliate=furusatoAffiliateHTML(o);
  const link=affiliate||`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">楽天市場で「${esc(o.label_ja)} ${esc(o.prefecture)}」の返礼品を探す <span aria-hidden="true">↗</span></a>`;
  return `<section class="detail-section detail-affiliate" aria-labelledby="detail-furusato"><h3 id="detail-furusato">ふるさと納税${affiliate?' <span class="detail-note-inline">広告</span>':''}</h3>${link}<p class="detail-note">「ふるさと納税・特産物名・都道府県」によるキーワード検索です。返礼品が見つからない場合や、別の産地の商品・通常の商品が含まれる場合があります。寄付先の自治体と返礼品の詳細はリンク先で確認してください。</p>${affiliate?'<p class="image-license">このリンクは楽天アフィリエイトの広告です。リンク経由の申し込みなどにより、みどころマップが報酬を受け取る場合があります。</p>':''}</section>`;
}

function amazonLink(o){
  const allowed=context.config.affiliateOrigins.includes(location.origin);
  const affiliate=allowed&&Boolean(safeUrl(o.affiliate_url));
  const url=(allowed&&safeUrl(o.affiliate_url))||safeUrl(o.shopping_url);
  if(!url||new URL(url).hostname!=='www.amazon.co.jp')return'';
  return `<section class="detail-section detail-affiliate" aria-labelledby="detail-shopping"><h3 id="detail-shopping">関連商品${affiliate?' <span class="detail-note-inline">広告</span>':''}</h3><a href="${esc(url)}" target="_blank" rel="${affiliate?'sponsored ':''}noopener noreferrer">Amazonで「${esc(o.label_ja)}」を探す <span aria-hidden="true">↗</span></a><p class="detail-note">品目名による検索です。検索結果には関連する商品も含まれます。</p>${affiliate?'<p class="image-license">Amazonのアソシエイトとして、みどころマップは適格販売により収入を得ています。</p>':''}</section>`;
}

async function hydrateImage(o){
  const qid=o.qid;
  const container=document.querySelector('#detail-image');
  if(!container)return;
  if(!imageCatalogReady){
    try{await loadImageCatalog();if(selectedItem===o)hydrateImage(o)}
    catch{if(selectedItem===o)imageFailure(container,o,'写真の登録情報を取得できませんでした。')}
    return;
  }
  if(imageCatalog[qid]){
    const data=imageCatalog[qid];
    renderImage(container,{url:registeredPhotoUrl(data.url),originalUrl:registeredPhotoUrl(data.original_url),license:data.license,licenseUrl:safeUrl(data.license_url),artist:plainText(data.artist),credit:plainText(data.credit),attribution:plainText(data.attribution),sourceUrl:safeUrl(data.source_url),caption:data.caption,sourceName:plainText(data.source_name)},o);
    return;
  }
  if(!/^Q\d+$/.test(qid||'')||blockedImageFallback.has(qid)){
    container.innerHTML='<p class="detail-image-status">この品目の写真はまだ確認できていません。</p>';
    return;
  }
  if(imageCache[qid]&&Date.now()-imageCache[qid].checkedAt<7*24*60*60*1000){
    const cached=imageCache[qid];
    if(cached.url&&cached.license){renderImage(container,cached,o);return}
  }
  try{
    const data=await fetchJSONWithRetry(`/api/wikiimage?qid=${encodeURIComponent(qid)}`);
    const result={url:safeUrl(data.url),license:String(data.license||'').trim(),licenseUrl:safeUrl(data.license_url),artist:plainText(data.artist),credit:plainText(data.credit),sourceUrl:safeUrl(data.source_url),checkedAt:Date.now()};
    imageCache[qid]=result;
    try{localStorage.setItem(IMAGE_CACHE_KEY,JSON.stringify(imageCache))}catch{}
    if(selectedItem!==o)return;
    if(!result.url){container.innerHTML='<p class="detail-image-status">表示できる画像が登録されていません。</p>';return}
    if(!result.license){container.innerHTML='<p class="detail-image-status">画像のライセンス情報を確認できないため、表示していません。</p>';return}
    renderImage(container,result,o);
  }catch(error){
    console.warn(`Image could not be loaded for ${qid}`,error);
    if(selectedItem!==o)return;
    imageFailure(container,o,'写真を取得できませんでした。');
  }
}
function registeredPhotoUrl(value){
  if(typeof value==='string'&&/^\/photos\/maff\/local-[a-f0-9]{16}-[a-f0-9]{16}\.(jpg|png)$/.test(value))return new URL('/assets/tokusan'+value,location.origin).href;
  return safeUrl(value);
}
function renderImage(container,result,o){
  const source=result.sourceUrl||commonsFilePage(result.url);
  const sourceName=result.sourceName||'Commons';
  const sourceLabel=sourceName==='Commons'?'Wikimedia Commons の画像出典':`${sourceName} の画像出典`;
  const license=result.licenseUrl?`<a href="${esc(result.licenseUrl)}" target="_blank" rel="noopener noreferrer">${esc(result.license)}<span aria-hidden="true">↗</span></a>`:esc(result.license);
  const creator=[result.artist,result.credit,result.attribution].filter((value,index,all)=>value&&all.indexOf(value)===index).join(' · ');
  const name=o.label_ja||o.label_en||'特産物';
  const caption=result.caption||`${name}の画像`;
  container.innerHTML=`<button class="detail-image-button" type="button" aria-label="${esc(caption)}を拡大"><img class="detail-image" src="${esc(result.url)}" alt="${esc(caption)}"></button>${result.caption?`<p class="image-license">${esc(result.caption)}</p>`:''}<p class="image-license">${creator?`${esc(creator)} · `:''}${license}${source?` · <a href="${esc(source)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(sourceLabel)}">${esc(sourceName)}<span aria-hidden="true">↗</span></a>`:''}</p>`;
  const img=container.querySelector('img');
  img.addEventListener('error',()=>{
    if(selectedItem!==o)return;
    if(result.originalUrl&&img.src!==result.originalUrl){img.src=result.originalUrl;return}
    delete imageCache[o.qid];
    try{localStorage.setItem(IMAGE_CACHE_KEY,JSON.stringify(imageCache))}catch{}
    imageFailure(container,o,'写真を読み込めませんでした。');
  });
  container.querySelector('button').addEventListener('click',()=>openLightbox(img.currentSrc||img.src,caption));
}
function imageFailure(container,o,message){
  container.innerHTML=`<p class="detail-image-status">${esc(message)} <button type="button">再読み込み</button></p>`;
  container.querySelector('button').addEventListener('click',()=>{if(selectedItem===o)hydrateImage(o)});
}
async function loadImageCatalog(){
  if(imageCatalogLoad)return imageCatalogLoad;
  imageCatalogLoad=(async()=>{
    const data=await fetchJSONWithRetry('/images.json?v=2026092911',10000);
    if(!data.photos||typeof data.photos!=='object'||Array.isArray(data.photos)||!Array.isArray(data.blocked_fallback))throw new Error('Invalid image catalog');
    imageCatalog=data.photos;
    blockedImageFallback=new Set(data.blocked_fallback);
    imageCatalogReady=true;
  })();
  try{await imageCatalogLoad}finally{imageCatalogLoad=null}
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
document.querySelector('#category-options').addEventListener('change',()=>{updateCategorySummary();applyFilters()});
document.querySelector('#clear-filters').addEventListener('click',()=>{document.querySelector('#keyword').value='';document.querySelector('#prefecture').value='';clearCategories();applyFilters();document.querySelector('#keyword').focus()});
document.querySelector('.detail-close').addEventListener('click',closeDetail);
document.querySelector('.lightbox-close').addEventListener('click',closeLightbox);
document.querySelector('#lightbox').addEventListener('click',e=>{if(e.target.id==='lightbox')closeLightbox()});
document.querySelector('#lightbox').addEventListener('cancel',closeLightbox);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeLightbox()});

loadImageCatalog().catch(()=>{});
loadFurusatoAffiliateCatalog().catch(()=>{});
Promise.all([fetchJSONWithRetry('/api/tokusan/'),fetchJSONWithRetry('/regions.json?v=202609296')]).then(([data,regions])=>{
  if(!Array.isArray(regions))throw new Error('Invalid region definitions');
  regionsByPrefecture=new Map(regions.map(p=>[p.prefecture,p]));
  tokusan=Array.isArray(data)?data:[];
  populatePrefectures();
  populateCategories();
  renderLegend();
  applyFilters();
}).catch(error=>{
  console.error('Tokusan data could not be loaded',error);
  document.querySelector('#tokusan-list').innerHTML='<p class="empty-state">特産物の情報を読み込めませんでした。時間をおいて再読み込みしてください。</p>';
  document.querySelector('#map-count').textContent='読み込み失敗';
});
}
