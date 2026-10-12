import {esc} from '../detail-common.js';
import {openExplorerDetail, closeExplorerDetail} from '../../runtime.js';
import {labels, readColors, pointEntries, geoEntries, filterEntries, balanced, contains} from './model.mjs';

const sources = [
  ['shiseki','/api/shiseki/shiseki/'], ['omatsuri','/api/omatsuri/festivals/'],
  ['onsen','/api/onsen/onsen/'], ['tokusan','/api/tokusan/tokusan/'],
  ['geopark','/geo/geoparks.json'], ['geosite','/geo/geosites.json'], ['nationalpark','/geo/nationalparks.json'],
];
const boundsArray = bounds => [bounds.getWest(),bounds.getSouth(),bounds.getEast(),bounds.getNorth()];
function readNumbers(value, length) {
  if (!value) return null;
  const result=value.split(',').map(Number);
  return result.length===length&&result.every(Number.isFinite)?result:null;
}

export function mount(context) {
  const {root,map,config}=context;
  const colors=readColors(root.host);
  const keyword=root.querySelector('#keyword'),prefecture=root.querySelector('#prefecture'),category=root.querySelector('#category');
  const mobilePrefecture=root.querySelector('#mobile-prefecture');
  const list=root.querySelector('#explore-list'),status=root.querySelector('#explore-status'),retry=root.querySelector('#explore-retry');
  const params=new URL(location.href).searchParams;
  keyword.value=params.get('keyword')||'';
  category.value=params.get('category')||'';
  let requestedPrefecture=params.get('prefecture')||'';
  let bounds=readNumbers(params.get('bounds'),4);
  if(bounds&&(bounds[1]<-90||bounds[3]>90||bounds[1]>=bounds[3]||bounds[0]>=bounds[2]))bounds=null;
  const savedMap=readNumbers(params.get('map'),3);
  if(savedMap&&Math.abs(savedMap[0])<=90&&Math.abs(savedMap[1])<=180&&savedMap[2]>=0&&savedMap[2]<=18)map.setView(savedMap.slice(0,2),savedMap[2],{animate:false});
  else if(bounds)map.fitBounds([[bounds[1],bounds[0]],[bounds[3],bounds[2]]],{animate:false});
  let initialItem=params.get('item');
  const datasets=new Map();
  let entries=[],results=[],ordered=[],limit=60,selected=null,styledKey=null,loading=false,selectionRequest=0,dataMessage='';
  const markerByKey=new Map();
  const layerCache=new Map();
  const points=L.markerClusterGroup({maxClusterRadius:45,disableClusteringAtZoom:13,iconCreateFunction:cluster=>L.divIcon({html:`<span class="explore-cluster">${cluster.getChildCount()}</span>`,className:'',iconSize:[36,36]})}).addTo(map);
  const areas=L.layerGroup().addTo(map);

  function urlState() {
    if(window.midokoro?.kind!=='explore')return;
    const url=new URL(location.href);
    for(const [key,value] of Object.entries({prefecture:prefecture.value,category:category.value,keyword:keyword.value.trim(),bounds:bounds?.join(','),item:selected})) {
      if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);
    }
    const center=map.getCenter();
    url.searchParams.set('map',[center.lat.toFixed(5),center.lng.toFixed(5),map.getZoom()].join(','));
    history.replaceState(null,'',url);
  }
  function selectionStyle() {
    list.querySelectorAll('.explore-card').forEach(card=>card.setAttribute('aria-current',String(card.dataset.key===selected)));
    for(const key of new Set([styledKey,selected])){
      const item=layerCache.has(key)?markerByKey.get(key):null;
      if(!item)continue;
      const {layer,entry}=item;
      layer.setStyle(entry.point?{weight:key===selected?3:2,color:key===selected?colors.selected:colors.outline}:{weight:key===selected?3.5:1.5,fillOpacity:key===selected ? .23 : .10});
    }
    styledKey=selected;
  }
  context.onExplorerDetailClose=()=>{selected=null;++selectionRequest;selectionStyle();urlState();status.textContent=dataMessage;};
  context.onDeactivated=context.onExplorerDetailClose;
  context.onActivated=urlState;
  async function open(entry, opener) {
    const request=++selectionRequest;
    status.textContent='詳細を読み込んでいます…';
    try {
      if(await openExplorerDetail(entry,config,opener)&&request===selectionRequest){selected=entry.key;selectionStyle();urlState();status.textContent=dataMessage;}
    } catch(error) {
      if(request===selectionRequest)status.textContent='詳細を開けませんでした。もう一度候補を選んでください。';
    }
  }
  function renderCards() {
    list.innerHTML=ordered.slice(0,limit).map(entry=>`<button type="button" class="explore-card" data-key="${esc(entry.key)}" aria-current="${entry.key===selected}"><span class="result-kind"><i class="${entry.point?'':'area'} ${entry.kind==='nationalpark'?'nationalpark':''}" style="${entry.point?`background:${colors[entry.kind]}`:''}"></i>${labels[entry.kind]}${entry.point?'':entry.geometry?' · 範囲':''}</span><span class="card-name">${esc(entry.name)}</span><span class="card-meta">${esc(entry.region||'地域未登録')}${entry.positionNote?' · '+esc(entry.positionNote):''}${!entry.point&&!entry.geometry?' · 位置未登録':''}</span></button>`).join('');
    const more=root.querySelector('#show-more');more.hidden=ordered.length<=limit;
    more.textContent=`さらに表示（${Math.min(limit,ordered.length)} / ${ordered.length}件）`;
  }
  function areaChoices(entry,event) {
    const choices=results.filter(item=>!item.point&&item.geometry&&contains(item.geometry,event.latlng.lng,event.latlng.lat));
    if(choices.length<2){open(entry,root.querySelector('#keyword'));return;}
    const nav=root.querySelector('#area-choices');nav.hidden=false;
    nav.innerHTML='<p>この位置で重なる範囲を選んでください。</p>';
    for(const choice of choices){const button=document.createElement('button');button.type='button';button.textContent=`${labels[choice.kind]} · ${choice.name}`;button.onclick=()=>open(choice,button);nav.append(button);}
    nav.scrollIntoView({block:'nearest'});nav.querySelector('button').focus({preventScroll:true});
  }
  function drawMap() {
    const wanted=new Set(results.map(entry=>entry.key)),remove=[];
    for(const [key,{layer,entry}] of markerByKey){
      if(wanted.has(key))continue;
      if(entry.point)remove.push(layer);else areas.removeLayer(layer);
      markerByKey.delete(key);
    }
    points.removeLayers(remove);
    const markers=[];let areaCount=0,pointCount=0;
    for(const entry of results){
      if(entry.point)pointCount++;else if(entry.geometry)areaCount++;
      if(markerByKey.has(entry.key))continue;
      let layer=layerCache.get(entry.key);
      if(!layer){
      if(entry.point){
        layer=L.circleMarker(entry.point,{radius:7,color:colors.outline,weight:2,fillColor:colors[entry.kind],fillOpacity:.95});
        layer.on('click',()=>open(entry,root.querySelector('#keyword')));
      } else if(entry.geometry){
        const color=colors[entry.kind];
        layer=L.geoJSON(entry.data,{style:{color,weight:1.5,fillOpacity:.10,dashArray:entry.kind==='nationalpark'?'5 3':null}});
        layer.on('click',event=>areaChoices(entry,event));
      }
      if(layer){layer.bindTooltip(esc(`${labels[entry.kind]} · ${entry.name}`));layerCache.set(entry.key,layer);}
      }
      if(layer){if(entry.point)markers.push(layer);else areas.addLayer(layer);markerByKey.set(entry.key,{layer,entry});}
    }
    points.addLayers(markers);
    selectionStyle();
    root.querySelector('#map-count').textContent=`${pointCount.toLocaleString('ja')} 地点 · ${areaCount} 範囲`;
  }
  function draw() {
    closeExplorerDetail(false);selected=null;++selectionRequest;limit=60;
    selectionStyle();
    if(!loading)status.textContent=dataMessage;
    root.querySelector('#area-choices').hidden=true;
    results=filterEntries(entries,{prefecture:prefecture.value,category:category.value,keyword:keyword.value,bounds});
    ordered=balanced(results);
    root.querySelector('#result-count').textContent=String(results.length);
    root.querySelector('#search-summary').textContent=[prefecture.value||'全国',category.value?labels[category.value]:'すべてのカテゴリ',bounds?'地図で選んだ範囲':''].filter(Boolean).join(' · ');
    root.querySelector('#explore-empty').hidden=results.length>0||loading;
    root.querySelector('#clear-area').hidden=!bounds;
    mobilePrefecture.value=prefecture.value;
    root.querySelector('#search-area').textContent=bounds?'この範囲で探し直す':'この範囲で探す';
    renderCards();drawMap();urlState();
  }
  function fitPrefecture() {
    const matching=entries.filter(entry=>entry.prefectures.includes(prefecture.value));
    let coordinates=matching.filter(entry=>entry.point).map(entry=>entry.point);
    if(!coordinates.length)coordinates=matching.flatMap(entry=>entry.geometry?[L.geoJSON(entry.data).getBounds().getSouthWest(),L.geoJSON(entry.data).getBounds().getNorthEast()]:[]);
    if(coordinates.length)map.fitBounds(L.latLngBounds(coordinates),{padding:[24,24],maxZoom:9,animate:false});
    else if(!prefecture.value)map.setView([36.2,138.2],5,{animate:false});
  }
  async function load() {
    if(loading)return;
    loading=true;retry.hidden=true;status.textContent='みどころを読み込んでいます…';
    const pending=sources.filter(([name])=>!datasets.has(name));
    await Promise.allSettled(pending.map(async ([name,url])=>{
      const response=await fetch(url);if(!response.ok)throw new Error(name);
      const data=await response.json();
      const rows=name==='geosite'||name==='geopark'||name==='nationalpark'?data.features:data;
      if(!Array.isArray(rows))throw new Error(name);
      datasets.set(name,name.startsWith('geo')||name==='nationalpark'?geoEntries(name,rows):pointEntries(name,rows));
    }));
    entries=[...datasets.values()].flat().sort((a,b)=>a.name.localeCompare(b.name,'ja'));
    const value=prefecture.value||requestedPrefecture;
    prefecture.replaceChildren(new Option('全国',''));
    [...new Set(entries.flatMap(entry=>entry.prefectures))].sort((a,b)=>a.localeCompare(b,'ja')).forEach(name=>prefecture.add(new Option(name,name)));
    mobilePrefecture.replaceChildren(...[...prefecture.options].map(option=>option.cloneNode(true)));
    prefecture.value=value;requestedPrefecture='';
    loading=false;draw();
    if(value&&!savedMap&&!bounds)fitPrefecture();
    const missing=sources.filter(([name])=>!datasets.has(name)).map(([name])=>labels[name]);
    dataMessage=missing.length?`${missing.join('・')}を読み込めませんでした。表示中の件数は読み込めたカテゴリのみです。`:'';
    status.textContent=dataMessage;
    retry.hidden=!missing.length;
    const linked=initialItem&&results.find(entry=>entry.key===initialItem);
    initialItem=null;
    if(linked&&!selected)await open(linked,list.querySelector(`[data-key="${CSS.escape(linked.key)}"]`)||keyword);
  }
  list.addEventListener('click',event=>{const card=event.target.closest('.explore-card');if(card){const entry=entries.find(item=>item.key===card.dataset.key);if(entry)open(entry,card);}});
  root.querySelector('#show-more').onclick=()=>{const oldLimit=limit;limit+=60;renderCards();list.querySelectorAll('.explore-card')[oldLimit]?.focus({preventScroll:true});};
  keyword.addEventListener('input',draw);category.addEventListener('change',draw);
  prefecture.addEventListener('change',()=>{bounds=null;draw();fitPrefecture();});
  mobilePrefecture.addEventListener('change',()=>{prefecture.value=mobilePrefecture.value;prefecture.dispatchEvent(new Event('change'));});
  root.querySelector('#search-area').onclick=()=>{bounds=boundsArray(map.getBounds());draw();};
  root.querySelector('#clear-area').onclick=()=>{bounds=null;draw();};
  root.querySelector('#clear-filters').onclick=()=>{bounds=null;keyword.value='';prefecture.value='';category.value='';draw();keyword.focus();};
  retry.onclick=load;
  map.on('moveend',urlState);
  context.ready=load();
}
