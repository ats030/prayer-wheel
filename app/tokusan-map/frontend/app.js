const map=L.map('map',{preferCanvas:true}).setView([36.2,138.2],5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);

let tokusan=[];
let visible=[];
let markers=new Map();
let selectedMarker=null;
let selectedKey=null;

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

function applyFilters(){
  const keyword=document.querySelector('#keyword').value.trim().toLowerCase();
  const prefecture=document.querySelector('#prefecture').value;
  visible=tokusan.filter(o=>{
    if(prefecture&&o.prefecture!==prefecture)return false;
    if(keyword){
      const haystack=[o.label_ja,o.label_en,o.place,o.prefecture,o.city].filter(Boolean).join(' ').toLowerCase();
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
    const located=hasCoordinates(o);
    const badge=located?'<span class="badge badge-located">位置表示あり</span>':'<span class="badge badge-unlocated">産地のみ</span>';
    const metaParts=[];
    if(o.prefecture)metaParts.push(esc(o.prefecture));
    if(o.place&&o.place!==o.prefecture)metaParts.push(esc(o.place));
    const meta=metaParts.length?metaParts.join('・')+` ${badge}`:badge;
    return `<button type="button" class="tokusan-card" data-key="${esc(key)}" ${o.qid?`data-qid="${esc(o.qid)}"`:''}>
      <span class="card-index">${i+1}</span>
      <span class="card-body"><span class="card-name">${esc(o.label_ja||o.label_en||o.qid)}</span><span class="card-meta">${meta}</span></span>
    </button>`;
  }).join('');
  for(const button of list.querySelectorAll('.tokusan-card')){
    button.addEventListener('click',()=>selectItem(button.dataset.key));
  }
}

function markerIcon(o,selected){
  const className=`tokusan-marker${selected?' selected':''}`;
  return L.divIcon({className:'',html:`<div class="${className}"></div>`,iconSize:[22,22],iconAnchor:[11,11]});
}

function renderMarkers(){
  for(const [key,marker] of markers)map.removeLayer(marker);
  markers.clear();
  let locatedCount=0;
  const bounds=[];
  visible.forEach((o,i)=>{
    const key=itemKey(o,i);
    if(!hasCoordinates(o))return;
    const marker=L.marker([o.latitude,o.longitude],{icon:markerIcon(o,key===selectedKey),title:o.label_ja||o.label_en||o.qid});
    marker.bindTooltip(`${o.label_ja||o.label_en||o.qid}${o.prefecture?'（'+o.prefecture+'）':''}`,{direction:'top',offset:[0,-8]});
    marker.on('click',()=>selectItem(key));
    marker.addTo(map);
    markers.set(key,marker);
    bounds.push([o.latitude,o.longitude]);
    locatedCount+=1;
  });
  document.querySelector('#map-count').textContent=`${visible.length} 件中 ${locatedCount} 件の位置を表示`;
  if(bounds.length===1)map.setView(bounds[0],9);
  else if(bounds.length>1)map.fitBounds(L.latLngBounds(bounds).pad(0.2));
}

function selectItem(key){
  selectedKey=key;
  const item=visible.find(o=>itemKey(o,visible.indexOf(o))===key);
  for(const button of document.querySelectorAll('.tokusan-card'))button.setAttribute('aria-current',button.dataset.key===key?'true':'false');
  if(selectedMarker)selectedMarker.setIcon(markerIcon(item,true));
  for(const [k,m] of markers){if(k!==key&&m._icon?.className?.includes('selected'))m.setIcon(markerIcon(null,false));}
  if(selectedMarker)selectedMarker.setIcon(markerIcon(item,true));
  showDetail(item);
  if(hasCoordinates(item)){
    map.setView([item.latitude,item.longitude],Math.max(map.getZoom(),9));
  }
  document.querySelector('#detail-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
}

function showDetail(o){
  const panel=document.querySelector('#detail-panel');
  const content=document.querySelector('#detail-content');
  const located=hasCoordinates(o);
  document.querySelector('#detail-panel').hidden=false;
  document.querySelector('#detail-origin').textContent=located?`位置：${o.prefecture||o.place||''}付近`:`産地：${o.prefecture||o.place||'不明'}`;
  const rows=[
    ['品目',esc(o.label_en||'—')],
    ['産地',esc(o.place||o.prefecture||'—')],
    ['都道府県',esc(o.prefecture||'—')],
    ['市町村',esc(o.city||'—')],
    ['信頼度',o.confidence?`${Math.round(o.confidence*100)}%`:'—'],
    ['出典',o.source_url?`<a href="${esc(o.source_url)}" target="_blank" rel="noopener">Wikipedia</a>`:'—'],
  ];
  content.innerHTML=`<div class="detail">
    <h2>${esc(o.label_ja||o.label_en||o.qid)}</h2>
    <dl class="detail-facts">${rows.map(([dt,dd])=>`<div><dt>${dt}</dt><dd>${dd}</dd></div>`).join('')}</dl>
    ${o.evidence?`<div class="detail-section"><h3>根拠 (LLM 抽出)</h3><p class="detail-evidence"><span class="quote">${esc(o.evidence)}</span></p><p class="detail-note">産地は日本語 Wikipedia 記事から LLM で抽出し、座標は Nominatim でジオコードしたため、目安としてお取り決めください。</p></div>`:''}
    <p class="detail-note">出典：<a href="${esc('https://www.wikidata.org/wiki/'+o.qid)}" target="_blank" rel="noopener">Wikidata ${esc(o.qid)}</a></p>
  </div>`;
  document.querySelector('#detail-panel').hidden=false;
  panel.parentElement.classList.add('has-detail');
}

function closeDetail(){
  document.querySelector('#detail-panel').hidden=true;
  document.querySelector('.app-shell').classList.remove('has-detail');
  if(selectedMarker)selectedMarker.setIcon(markerIcon(null,false));
  selectedMarker=null;
  selectedKey=null;
}

document.querySelector('#keyword').addEventListener('input',applyFilters);
document.querySelector('#prefecture').addEventListener('change',applyFilters);
document.querySelector('#clear-filters').addEventListener('click',()=>{document.querySelector('#keyword').value='';document.querySelector('#prefecture').value='';applyFilters();document.querySelector('#keyword').focus()});
document.querySelector('.detail-close').addEventListener('click',closeDetail);

fetch('/api/tokusan/').then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}).then(data=>{
  tokusan=Array.isArray(data)?data:[];
  populatePrefectures();
  applyFilters();
}).catch(error=>{
  console.error('Tokusan data could not be loaded',error);
  document.querySelector('#tokusan-list').innerHTML='<p class="empty-state">特産物の情報を読み込めませんでした。fetch_tokusan.py と build_db.py を実行してデータベースを作成してください。</p>';
  document.querySelector('#map-count').textContent='読み込み失敗';
});
