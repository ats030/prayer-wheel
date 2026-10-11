import {esc, sourceLink, flyToItem, fitItem, revealDetail, focusWithin, focusFirst} from '../detail-common.js';

const geoparkKinds = [['shiseki','史跡'],['omatsuri','祭り'],['onsen','温泉'],['tokusan','特産物']];
const SELECTED_MARKER_Z_INDEX = 10000;
const PARK_STYLE = {color:'#2f6f4f', weight:1.5, fillColor:'#2f6f4f', fillOpacity:.12};
const PARK_SELECTED_STYLE = {color:'#2f6f4f', weight:3.5, fillColor:'#2f6f4f', fillOpacity:.24};

function fetchedNote(fetched) {
  return fetched ? `<p class="detail-fetched">${esc(fetched)} 取得</p>` : '';
}

function geositeDetail(properties) {
  const place = [properties.prefecture, properties.address].filter(Boolean).join(' ');
  return `<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(properties.name)}</h2><p class="detail-kind">${esc(properties.designation_label)}（地質鉱物）</p></header>`+
    `<dl class="detail-facts"><div><dt>所在地</dt><dd>${esc(place || '未登録')}</dd></div>${properties.criteria ? `<div><dt>指定基準</dt><dd>${esc(properties.criteria)}</dd></div>` : ''}</dl>`+
    `<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典</h3><nav class="detail-links" aria-label="出典">${sourceLink(properties.source_url, '国指定文化財等データベース')}</nav>${fetchedNote(properties.fetched)}</section></article>`;
}

function geoparkDetail(properties) {
  const counts = geoparkKinds.map(([kind,label]) => `<div><dt>${label}</dt><dd>${esc(properties.counts?.[kind] ?? 0)} 件</dd></div>`).join('');
  const partial = properties.partial?.length ? `<div><dt>一部のみ</dt><dd>${esc(properties.partial.join('、'))}<p class="detail-note">一部のみが含まれる自治体は範囲に含めていません。</p></dd></div>` : '';
  return `<article class="detail"><header class="detail-lead"><h2 id="detail-title" tabindex="-1">${esc(properties.name)}</h2><p class="detail-kind">${properties.unesco ? 'ユネスコ世界ジオパーク' : '日本ジオパーク'}</p></header>`+
    `<dl class="detail-facts"><div><dt>構成自治体</dt><dd>${esc((properties.municipalities || []).join('、'))}</dd></div>${partial}</dl>`+
    `<section class="detail-section" aria-labelledby="detail-counts"><h3 id="detail-counts">範囲内の見どころ</h3><dl class="detail-counts">${counts}</dl></section>`+
    `<section class="detail-section detail-sources" aria-labelledby="detail-sources"><h3 id="detail-sources">出典</h3><nav class="detail-links" aria-label="出典">${sourceLink(properties.source, '日本ジオパークネットワーク')}</nav>${fetchedNote(properties.fetched)}</section></article>`;
}

export function mount(context) {
  const root = context.root, map = context.map;
  const keyword = root.querySelector('#keyword'), type = root.querySelector('#geo-type');
  const list = root.querySelector('#geo-list'), count = root.querySelector('#result-count');
  const message = root.querySelector('#geo-message'), retry = root.querySelector('#geo-retry');
  const panel = root.querySelector('#detail-panel'), content = root.querySelector('#detail-content');
  const shell = root.querySelector('.app-shell');
  // Parks are added first so point symbols always stay above the polygons.
  const parkLayer = L.layerGroup().addTo(map), pointLayer = L.layerGroup().addTo(map);
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
    for (const item of shown.values()) if (item.kind === 'geopark') item.layer.setStyle(PARK_STYLE);
    const item = key && shown.get(key);
    if (!item) return;
    const properties = item.feature.properties;
    if (item.kind === 'geopark') { item.layer.setStyle(PARK_SELECTED_STYLE); return; }
    selectedMarker = L.marker(item.layer.getLatLng(), {icon:markerIcon(properties.designation), zIndexOffset:SELECTED_MARKER_Z_INDEX}).addTo(map);
    selectedMarker.bindTooltip(esc(properties.name), {direction:'top', offset:[0,-10]});
    selectedMarker.on('click', () => select(key, 'marker'));
  }
  function select(key, origin) {
    const item = shown.get(key);
    if (!item) return;
    selectedKey = key; selectedOrigin = origin;
    showSelection(key);
    list.querySelectorAll('.geo-card').forEach(card => card.setAttribute('aria-current', String(card.dataset.key === key)));
    panel.hidden = false; shell.classList.add('has-detail');
    if (origin === 'list') {
      // Fit to the map width that remains after the detail column opens.
      map.invalidateSize({pan:false});
      if (item.kind === 'geopark') fitItem(map, item.layer.getBounds(), {maxZoom:10});
      else flyToItem(map, item.layer.getLatLng());
    }
    content.innerHTML = item.kind === 'geopark' ? geoparkDetail(item.feature.properties) : geositeDetail(item.feature.properties);
    root.querySelector('#detail-origin').textContent = origin === 'marker' ? '地図から選択' : '検索結果から選択';
    panel.scrollTop = 0;
    revealDetail(map, panel, root.querySelector('#detail-title'));
  }
  function closeDetail(restoreFocus = true) {
    const key = selectedKey, origin = selectedOrigin, hadFocus = focusWithin(panel);
    selectedKey = null; selectedOrigin = null;
    panel.hidden = true; shell.classList.remove('has-detail');
    showSelection(null);
    list.querySelectorAll('.geo-card').forEach(card => card.setAttribute('aria-current', 'false'));
    requestAnimationFrame(() => map.invalidateSize());
    if ((restoreFocus && key) || hadFocus) {
      const mapElement = root.querySelector('#map'), card = key && list.querySelector(`.geo-card[data-key="${CSS.escape(key)}"]`);
      focusFirst(origin === 'marker' ? mapElement : card, keyword, mapElement);
    }
  }
  function draw() {
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
      if (entry.kind === 'geopark') {
        layer = L.geoJSON(feature, {style:PARK_STYLE}).addTo(parkLayer);
        layer.bindTooltip(esc(properties.name), {sticky:true});
      } else {
        const [longitude, latitude] = feature.geometry.coordinates, latlng = [latitude, longitude];
        const style = markerStyle(properties.designation);
        layer = L.circleMarker(latlng, style).addTo(pointLayer);
        L.circleMarker(latlng, {radius:2.5, stroke:false, fillColor:style.color, fillOpacity:1, interactive:false}).addTo(pointLayer);
        layer.bindTooltip(esc(properties.name), {direction:'top', offset:[0,-10]});
      }
      layer.on('click', () => select(key, 'marker'));
      shown.set(key, {kind:entry.kind, feature, layer});
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'geo-card'; button.dataset.key = key;
      button.setAttribute('aria-current', String(key === selectedKey));
      const number = document.createElement('span'); number.className = 'card-index';
      number.textContent = String(index + 1).padStart(2, '0');
      const body = document.createElement('span');
      const title = document.createElement('span'); title.className = 'card-name'; title.textContent = properties.name;
      const description = document.createElement('span'); description.className = 'card-meta';
      description.textContent = entry.kind === 'geopark' ? `ジオパーク · ${properties.municipalities.join('、')}` : `${properties.designation_label} · ${properties.prefecture || ''}`;
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
      const datasets = await Promise.all(['geoparks', 'geosites'].map(async name => {
        const response = await fetch('/geo/' + name + '.json');
        if (!response.ok) throw new Error('地質データを取得できませんでした。');
        const data = await response.json();
        if (!Array.isArray(data.features)) throw new Error('地質データを読み取れませんでした。');
        return data.features;
      }));
      entries = datasets.flatMap((features, index) => features.map(feature => {
        const kind = index === 0 ? 'geopark' : 'geosite', properties = feature.properties;
        return {feature, kind, key:kind === 'geopark' ? 'geopark:'+properties.slug : 'geosite:'+properties.heritage_id,
          search:[properties.name, ...(properties.municipalities || []), properties.prefecture || '', properties.address || ''].join(' ').normalize('NFKC').toLocaleLowerCase()};
      }));
      loading = false; draw();
      message.textContent = 'ジオパークは構成自治体の範囲、天然記念物は地点を表示しています。一部のみの自治体は範囲に含めません。';
    } catch (error) {
      message.textContent = 'データを読み込めませんでした。再試行してください。'; retry.hidden = false;
    } finally { loading = false; }
  }
  keyword.addEventListener('input', draw); type.addEventListener('change', draw);
  root.querySelector('#clear-filters').onclick = () => { keyword.value = ''; type.value = ''; draw(); };
  root.querySelector('.detail-close').onclick = () => closeDetail();
  retry.onclick = load;
  load();
}
