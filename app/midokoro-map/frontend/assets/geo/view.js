const geoparkKinds = [['shiseki','史跡'],['omatsuri','祭り'],['onsen','温泉'],['tokusan','特産物']];

function geoparkPopup(properties) {
  const box = document.createElement('div');
  const title = document.createElement('strong');
  title.textContent = properties.name;
  const lines = [title];
  if (properties.unesco) lines.push('ユネスコ世界ジオパーク');
  lines.push('構成自治体: '+properties.municipalities.join('、'));
  if (properties.partial.length) lines.push('一部のみ: '+properties.partial.join('、')+'（範囲には含めていません）');
  lines.push('範囲内: '+geoparkKinds.map(([kind,label])=>label+' '+properties.counts[kind]+'件').join(' / '));
  const source = document.createElement('a');
  source.href = properties.source; source.target = '_blank'; source.rel = 'noopener';
  source.textContent = '日本ジオパークネットワーク';
  const credit = document.createElement('span');
  credit.append('出典: ', source, properties.fetched ? '（'+properties.fetched+'取得）' : '');
  lines.push(credit);
  for (const line of lines) {
    const row = document.createElement('div');
    row.append(line);
    box.append(row);
  }
  return box;
}

function geositePopup(properties) {
  const box = document.createElement('div');
  const title = document.createElement('strong');
  title.textContent = properties.name;
  const source = document.createElement('a');
  source.href = properties.source_url; source.target = '_blank'; source.rel = 'noopener';
  source.textContent = '国指定文化財等データベース';
  const credit = document.createElement('span');
  credit.append('出典: ', source, '（'+properties.fetched+'取得）');
  const place = [properties.prefecture, properties.address].filter(Boolean).join(' ');
  for (const line of [title, properties.designation_label+'（地質鉱物）', place,
    properties.criteria ? '指定基準: '+properties.criteria : '', credit]) {
    if (!line) continue;
    const row = document.createElement('div');
    row.append(line);
    box.append(row);
  }
  return box;
}

export function mount(context) {
  const root = context.root, map = context.map;
  const keyword = root.querySelector('#keyword'), type = root.querySelector('#geo-type');
  const list = root.querySelector('#geo-list'), count = root.querySelector('#result-count');
  const message = root.querySelector('#geo-message'), retry = root.querySelector('#geo-retry');
  let entries = [], layers = [], loading = false;
  function draw() {
    map.closePopup();
    for (const layer of layers) map.removeLayer(layer);
    layers = [];
    list.replaceChildren();
    const term = keyword.value.normalize('NFKC').trim().toLocaleLowerCase();
    const selected = entries.filter(entry => (!type.value || entry.kind === type.value) && entry.search.includes(term));
    count.textContent = String(selected.length);
    root.querySelector('#geo-empty').hidden = loading || selected.length !== 0;
    root.querySelector('#map-count').textContent = `ジオパーク ${selected.filter(entry => entry.kind === 'geopark').length} / 天然記念物 ${selected.filter(entry => entry.kind === 'geosite').length}`;
    for (const entry of selected) {
      const feature = entry.feature, properties = feature.properties;
      const layer = L.geoJSON(feature, entry.kind === 'geopark' ? {
        style: {color:'#2f6f4f', weight:1.5, fillColor:'#2f6f4f', fillOpacity:.12}
      } : {pointToLayer: (_, latlng) => L.circleMarker(latlng, {radius:6, weight:1.5, color:'#5b3a1e',
        fillColor:properties.designation === 'special' ? '#c2410c' : '#b7791f', fillOpacity:.85})});
      const content = () => entry.kind === 'geopark' ? geoparkPopup(properties) : geositePopup(properties);
      layer.bindPopup(content); map.addLayer(layer); layers.push(layer);
      const button = document.createElement('button'); button.type = 'button'; button.className = 'geo-card';
      const title = document.createElement('strong'); title.textContent = properties.name;
      const description = document.createElement('span');
      description.textContent = entry.kind === 'geopark' ? `ジオパーク · ${properties.municipalities.join('、')}` : `${properties.designation_label} · ${properties.prefecture || ''}`;
      button.append(title, description);
      button.onclick = () => {
        map.fitBounds(layer.getBounds(), {maxZoom:12, animate:false});
        layer.openPopup();
      };
      list.append(button);
    }
    // Draw point symbols above park polygons, regardless of their list order.
    for (const layer of layers) layer.eachLayer(part => { if (part instanceof L.CircleMarker) part.bringToFront(); });
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
      entries = datasets.flatMap((features, index) => features.map(feature => ({feature, kind:index === 0 ? 'geopark' : 'geosite',
        search:[feature.properties.name, ...(feature.properties.municipalities || []), feature.properties.prefecture || '', feature.properties.address || ''].join(' ').normalize('NFKC').toLocaleLowerCase()})));
      loading = false; draw();
      message.textContent = 'ジオパークは構成自治体の範囲、天然記念物は地点を表示しています。一部のみの自治体は範囲に含めません。';
    } catch (error) {
      message.textContent = 'データを読み込めませんでした。再試行してください。'; retry.hidden = false;
    } finally { loading = false; }
  }
  keyword.addEventListener('input', draw); type.addEventListener('change', draw);
  root.querySelector('#clear-filters').onclick = () => { keyword.value = ''; type.value = ''; draw(); };
  retry.onclick = load;
  load();
}
