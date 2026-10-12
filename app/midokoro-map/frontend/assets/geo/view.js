import {esc, sourceLink, plainText, flyToItem, fitItem, revealDetail, closeDetailPanel, focusFirst} from '../detail-common.js';
import {photoHtml, sectionsHtml, hasSummary} from './media.js';

const geoparkKinds = [['shiseki','史跡'],['omatsuri','祭り'],['onsen','温泉'],['tokusan','特産物']];
const SELECTED_MARKER_Z_INDEX = 10000;
let areaStyles = null;

// Colors come from /tokens.css, which the page loads before any view mounts.
function areaStyle(kind, selected = false) {
  if (!areaStyles) {
    const style = getComputedStyle(document.documentElement);
    const park = style.getPropertyValue('--geo-geopark').trim();
    const national = style.getPropertyValue('--geo-nationalpark').trim();
    const nationalStyle = {color:national, weight:1.5, fillColor:national, fillOpacity:.10, dashArray:'5 3'};
    areaStyles = {
      park:{color:park, weight:1.5, fillColor:park, fillOpacity:.12},
      parkSelected:{color:park, weight:3.5, fillColor:park, fillOpacity:.24},
      national:nationalStyle,
      nationalSelected:{...nationalStyle, weight:3.5, fillOpacity:.24},
    };
  }
  return kind === 'nationalpark' ? (selected ? areaStyles.nationalSelected : areaStyles.national) : (selected ? areaStyles.parkSelected : areaStyles.park);
}

function containsArea(geometry, latlng) {
  function inside(ring) {
    let hit = false;
    for (let i = 1; i < ring.length; i++) {
      const [x1,y1] = ring[i-1], [x2,y2] = ring[i];
      if ((y1 > latlng.lat) !== (y2 > latlng.lat) && latlng.lng < x1 + (latlng.lat-y1)*(x2-x1)/(y2-y1)) hit = !hit;
    }
    return hit;
  }
  const polygons = geometry.type === 'MultiPolygon' ? geometry.coordinates : [geometry.coordinates];
  return polygons.some(rings => inside(rings[0]) && !rings.slice(1).some(inside));
}

function fetchedNote(fetched) {
  return fetched ? `<p class="detail-fetched">${esc(fetched)} 取得</p>` : '';
}

function geositeDetail(properties) {
  const place = [properties.prefecture, properties.address].filter(Boolean).join(' ');
  // Monuments mapped to Wikidata get a photo and AI section summaries, filled in by hydrateMedia.
  const media = properties.qid ? `<section class="detail-section" aria-labelledby="detail-photo-heading"><h3 id="detail-photo-heading">写真</h3><div id="detail-photo"><p class="detail-image-status">画像を読み込んでいます…</p></div></section>`
    + `<div id="detail-summaries" aria-live="polite">${properties.wikipedia_title ? '<p class="detail-note">概要を読み込んでいます…</p>' : ''}</div>` : '';
  return `<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(properties.name)}</h2><p class="detail-kind">${esc(properties.designation_label)}（地質鉱物）</p></header>`+media+
    `<dl class="detail-facts"><div><dt>所在地</dt><dd>${esc(place || '未登録')}</dd></div>${properties.criteria ? `<div><dt>指定基準</dt><dd>${esc(properties.criteria)}</dd></div>` : ''}</dl>`+
    `<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典</h3><nav class="detail-links" aria-label="出典">${sourceLink(properties.source_url, '国指定文化財等データベース')}</nav>${fetchedNote(properties.fetched)}</section></article>`;
}

function geoparkDetail(properties) {
  const counts = geoparkKinds.map(([kind,label]) => `<div><dt>${label}</dt><dd>${esc(properties.counts?.[kind] ?? 0)} 件</dd></div>`).join('');
  const partial = properties.partial?.length ? `<div><dt>一部のみ</dt><dd>${esc(properties.partial.join('、'))}<p class="detail-note">一部のみが含まれる自治体は範囲に含めていません。</p></dd></div>` : '';
  return `<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(properties.name)}</h2><p class="detail-kind">${properties.unesco ? 'ユネスコ世界ジオパーク' : '日本ジオパーク'}</p></header>`+
    `<dl class="detail-facts"><div><dt>構成自治体</dt><dd>${esc((properties.municipalities || []).join('、'))}</dd></div>${partial}</dl>`+
    `<section class="detail-section" aria-labelledby="detail-counts"><h3 id="detail-counts">範囲内の見どころ</h3><p class="detail-note">件数は約50mの精度の自治体境界で集計しています。地図の輪郭は約500mの精度に簡略化しているため、境界付近では表示と集計が異なる場合があります。</p><dl class="detail-counts">${counts}</dl></section>`+
    `<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典</h3><nav class="detail-links" aria-label="出典">${sourceLink(properties.source, '日本ジオパークネットワーク')}</nav>${fetchedNote(properties.fetched)}</section></article>`;
}

function nationalparkDetail(properties) {
  return `<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(properties.name)}</h2><p class="detail-kind">国立公園</p></header>`+
    `<dl class="detail-facts"><div><dt>都道府県</dt><dd>${esc(properties.prefectures)}</dd></div><div><dt>指定</dt><dd>${esc(properties.designated)}</dd></div><div><dt>面積（環境省一覧）</dt><dd>${esc(properties.area_label)}</dd></div></dl>`+
    `<p class="detail-note">環境省の公園区域データを、みどころマップが結合し表示用に簡略化しています。正確な区域は環境省の公式資料をご確認ください。</p>`+
    `<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典</h3><nav class="detail-links" aria-label="出典">${sourceLink(properties.source_url, '環境省・公園の公式情報')}${sourceLink('https://eadas.env.go.jp/eiadb/ebidbs/Service/About?title=Gis', '環境省EADAS・公園計画書／生物多様性センター区域データ')}${sourceLink('https://eadas.env.go.jp/eiadb/ebidbs/Service/AboutTermofuse', 'データ利用条件')}</nav><p class="detail-fetched">区域データ：${esc(properties.data_year)}整備</p>${fetchedNote(properties.fetched)}</section></article>`;
}

export function mount(context) {
  const root = context.root, map = context.map;
  const keyword = root.querySelector('#keyword'), type = root.querySelector('#geo-type');
  const list = root.querySelector('#geo-list'), count = root.querySelector('#result-count');
  const message = root.querySelector('#geo-message'), retry = root.querySelector('#geo-retry');
  const panel = root.querySelector('#detail-panel'), content = root.querySelector('#detail-content');
  const areaChoices = root.querySelector('#geo-area-choices');
  const shell = root.querySelector('.app-shell');
  // Parks are added first so point symbols always stay above the polygons.
  const parkLayer = L.layerGroup().addTo(map), pointLayer = L.layerGroup().addTo(map);
  // Points sit above the areas. SVG only captures events on the dots, so clicks elsewhere still reach the areas below.
  const pointPane = map.getPane('geo-points') || map.createPane('geo-points');
  pointPane.style.zIndex = '450';
  const pointRenderer = L.svg({pane:'geo-points'});
  let entries = [], shown = new Map(), loading = false;
  let selectedKey = null, selectedOrigin = null, selectedMarker = null, markerColors = {};

  // Colours live in app.css; read them from a probe so the canvas matches the icon.
  function markerStyle(designation) {
    if (!markerColors[designation]) {
      const probe = document.createElement('span');
      probe.className = `geo-marker designation-${designation}`;
      probe.style.visibility = 'hidden'; probe.style.position = 'absolute';
      root.append(probe);
      const css = getComputedStyle(probe);
      markerColors[designation] = {fill:css.backgroundColor, stroke:css.borderTopColor};
      probe.remove();
    }
    const {fill, stroke} = markerColors[designation];
    return {radius:9, weight:2, color:stroke, fillColor:fill, fillOpacity:1};
  }
  function markerIcon(designation) {
    return L.divIcon({className:'', html:`<span class="geo-marker selected designation-${esc(designation)}"></span>`, iconSize:[22,22], iconAnchor:[11,11]});
  }
  function showSelection(key) {
    if (selectedMarker) { map.removeLayer(selectedMarker); selectedMarker = null; }
    for (const item of shown.values()) if (item.kind !== 'geosite') item.layer.setStyle(areaStyle(item.kind));
    const item = key && shown.get(key);
    if (!item) return;
    const properties = item.feature.properties;
    if (item.kind !== 'geosite') { item.layer.setStyle(areaStyle(item.kind, true)); return; }
    selectedMarker = L.marker(item.layer.getLatLng(), {icon:markerIcon(properties.designation), zIndexOffset:SELECTED_MARKER_Z_INDEX}).addTo(map);
    selectedMarker.bindTooltip(esc(properties.name), {direction:'top', offset:[0,-10]});
    selectedMarker.on('click', () => select(key, 'marker'));
  }
  function select(key, origin, choices = [], keepChoiceFocus = false) {
    const item = shown.get(key);
    if (!item) return;
    selectedKey = key; selectedOrigin = origin;
    showSelection(key);
    list.querySelectorAll('.geo-card').forEach(card => card.setAttribute('aria-current', String(card.dataset.key === key)));
    panel.hidden = false; shell.classList.add('has-detail');
    if (origin === 'list') {
      // Fit to the map width that remains after the detail column opens.
      map.invalidateSize({pan:false});
      if (item.kind !== 'geosite') fitItem(map, item.layer.getBounds(), {maxZoom:10});
      else flyToItem(map, item.layer.getLatLng());
    }
    content.innerHTML = item.kind === 'nationalpark' ? nationalparkDetail(item.feature.properties) : item.kind === 'geopark' ? geoparkDetail(item.feature.properties) : geositeDetail(item.feature.properties);
    if (item.kind === 'geosite' && item.feature.properties.qid) hydrateMedia(key, item.feature.properties);
    areaChoices.replaceChildren(); areaChoices.hidden = choices.length < 2;
    if (choices.length > 1) {
      const label = document.createElement('p'); label.textContent = 'この位置で重なる範囲';
      areaChoices.append(label);
      for (const choice of choices) {
        const entry = shown.get(choice);
        if (!entry) continue;
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = entry.feature.properties.name;
        button.setAttribute('aria-current', String(choice === key));
        button.setAttribute('aria-controls', 'detail-content');
        button.onclick = () => select(choice, 'marker', choices, true);
        areaChoices.append(button);
      }
    }
    root.querySelector('#detail-origin').textContent = origin === 'marker' ? '地図から選択' : '検索結果から選択';
    panel.scrollTop = 0;
    if (keepChoiceFocus) {
      const button = areaChoices.querySelector('button[aria-current="true"]');
      requestAnimationFrame(() => { map.invalidateSize(); focusFirst(button); });
    } else revealDetail(map, panel, root.querySelector('#detail-title'));
  }
  const photos = new Map(), summaries = new Map();
  async function loadJSON(url) {
    try { const response = await fetch(url); return response.ok ? await response.json() : null; }
    catch { return null; }
  }
  async function hydrateMedia(key, properties) {
    const qid = properties.qid, title = properties.wikipedia_title;
    const [photo, summary] = await Promise.all([
      photos.has(qid) ? photos.get(qid) : loadJSON(`/api/geo/wiki/image?qid=${encodeURIComponent(qid)}`),
      !title ? null : summaries.has(qid) ? summaries.get(qid) : loadJSON(`/api/geo/wiki/content?title=${encodeURIComponent(title)}&qid=${encodeURIComponent(qid)}`)]);
    if (photo?.url) photos.set(qid, photo);
    // An empty response can come from a busy summarizer; retry it on the next open.
    if (hasSummary(summary)) summaries.set(qid, summary);
    const photoBox = root.querySelector('#detail-photo'), summaryBox = root.querySelector('#detail-summaries');
    if (selectedKey !== key || !photoBox || !summaryBox) return;
    photoBox.innerHTML = photoHtml(photo && {url: photo.url, license: String(photo.license || '').trim(), licenseUrl: photo.license_url,
      creator: plainText(photo.artist) || plainText(photo.credit), sourceUrl: photo.source_url}, properties.name);
    summaryBox.innerHTML = sectionsHtml(summary);
  }
  function closeDetail(restoreFocus = true) {
    const key = selectedKey, origin = selectedOrigin;
    selectedKey = null; selectedOrigin = null;
    showSelection(null);
    list.querySelectorAll('.geo-card').forEach(card => card.setAttribute('aria-current', 'false'));
    requestAnimationFrame(() => map.invalidateSize());
    closeDetailPanel(panel, {key, origin, cardSelector:'.geo-card', restoreFocus});
  }
  function draw() {
    areaChoices.replaceChildren(); areaChoices.hidden = true;
    parkLayer.clearLayers(); pointLayer.clearLayers();
    shown = new Map();
    list.replaceChildren();
    const term = keyword.value.normalize('NFKC').trim().toLocaleLowerCase();
    const selected = entries.filter(entry => (!type.value || entry.kind === type.value) && entry.search.includes(term));
    count.textContent = String(selected.length);
    root.querySelector('#geo-empty').hidden = loading || selected.length !== 0;
    root.querySelector('#map-count').textContent = `地図上に ${selected.length} 件`;
    selected.forEach((entry, index) => {
      const feature = entry.feature, properties = feature.properties;
      const key = entry.key;
      let layer;
      if (entry.kind !== 'geosite') {
        layer = L.geoJSON(feature, {style:areaStyle(entry.kind)}).addTo(parkLayer);
        layer.bindTooltip(esc(properties.name), {sticky:true});
      } else {
        const [longitude, latitude] = feature.geometry.coordinates, latlng = [latitude, longitude];
        const style = markerStyle(properties.designation);
        layer = L.circleMarker(latlng, {...style, pane:'geo-points', renderer:pointRenderer}).addTo(pointLayer);
        L.circleMarker(latlng, {radius:2.5, stroke:false, fillColor:style.color, fillOpacity:1, interactive:false, pane:'geo-points', renderer:pointRenderer}).addTo(pointLayer);
        layer.bindTooltip(esc(properties.name), {direction:'top', offset:[0,-10]});
      }
      layer.on('click', event => {
        const choices = entry.kind !== 'geosite' && event.latlng ? [...shown.entries()]
          .filter(([,item]) => item.kind !== 'geosite' && containsArea(item.feature.geometry, event.latlng)).map(([id]) => id) : [];
        if (choices.length && !choices.includes(key)) choices.push(key);
        select(key, 'marker', choices);
      });
      shown.set(key, {kind:entry.kind, feature, layer});
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'geo-card'; button.dataset.key = key;
      button.setAttribute('aria-current', String(key === selectedKey));
      const number = document.createElement('span'); number.className = 'card-index';
      number.textContent = String(index + 1).padStart(2, '0');
      const body = document.createElement('span');
      const title = document.createElement('span'); title.className = 'card-name'; title.textContent = properties.name;
      const description = document.createElement('span'); description.className = 'card-meta';
      description.textContent = entry.kind === 'nationalpark' ? `国立公園 · ${properties.prefectures}` : entry.kind === 'geopark' ? `ジオパーク · ${properties.municipalities.join('、')}` : `${properties.designation_label} · ${properties.prefecture || ''}`;
      body.append(title, description);
      button.append(number, body);
      button.onclick = () => select(key, 'list');
      list.append(button);
    });
    if (selectedKey && !shown.has(selectedKey)) closeDetail(false);
    else showSelection(selectedKey);
  }
  async function load() {
    if (loading) return;
    loading = true; retry.hidden = true;
    message.textContent = '地形・地質のデータを読み込んでいます…';
    root.querySelector('#geo-empty').hidden = true;
    try {
      const kinds = ['geopark', 'geosite', 'nationalpark'];
      const datasets = await Promise.all(['geoparks', 'geosites', 'nationalparks'].map(async name => {
        const response = await fetch('/geo/' + name + '.json');
        if (!response.ok) throw new Error('地質データを取得できませんでした。');
        const data = await response.json();
        if (!Array.isArray(data.features)) throw new Error('地質データを読み取れませんでした。');
        return data.features;
      }));
      entries = datasets.flatMap((features, index) => features.map(feature => {
        const kind = kinds[index], properties = feature.properties;
        return {feature, kind, key:kind+':'+(kind === 'geosite' ? properties.heritage_id : properties.slug),
          search:[properties.name, ...(properties.municipalities || []), properties.prefecture || properties.prefectures || '', properties.address || ''].join(' ').normalize('NFKC').toLocaleLowerCase()};
      }));
      loading = false; draw();
      message.textContent = '国立公園は公園区域、ジオパークは構成自治体の範囲、天然記念物は地点を表示しています。ジオパークの一部のみの自治体は範囲に含めません。';
    } catch (error) {
      message.textContent = 'データを読み込めませんでした。再試行してください。'; retry.hidden = false;
    } finally { loading = false; }
  }
  keyword.addEventListener('input', draw); type.addEventListener('change', draw);
  root.querySelector('#clear-filters').onclick = () => { keyword.value = ''; type.value = ''; draw(); };
  root.querySelector('.detail-close').onclick = () => closeDetail();
  retry.onclick = load;
  context.openRecord = entry => {
    selectedKey=entry.localKey; selectedOrigin='list';
    panel.hidden=false; shell.classList.add('has-detail');
    const props=entry.data.properties;
    content.innerHTML=entry.kind==='nationalpark'?nationalparkDetail(props):entry.kind==='geopark'?geoparkDetail(props):geositeDetail(props);
    areaChoices.hidden=true; areaChoices.replaceChildren();
    root.querySelector('#detail-origin').textContent='地域の検索結果から選択';
    panel.scrollTop=0; revealDetail(map,panel,root.querySelector('#detail-title'));
  };
  context.ready = load();
}
