// Shared capture/history controls. No map tiles or location requests until a button press.
let leafletReady;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (!leafletReady) leafletReady = new Promise((resolve, reject) => {
    const css = document.createElement('link');
    css.rel = 'stylesheet'; css.href = '/vendor/leaflet/leaflet.css';
    const script = document.createElement('script');
    script.src = '/vendor/leaflet/leaflet.js';
    script.onload = resolve;
    script.onerror = () => { css.remove(); script.remove(); leafletReady = null; reject(new Error('地図を読み込めませんでした。もう一度お試しください。')); };
    document.head.append(css, script);
  });
  return leafletReady;
}
export function locationLabel(point) {
  const method = point.source === 'current' ? '現在地を使用' : '地図で指定';
  return `${method}：緯度 ${point.latitude.toFixed(4)}, 経度 ${point.longitude.toFixed(4)}`;
}
function roundedPoint(latitude, longitude, source, accuracy = 11) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) throw new Error('有効な場所を選んでください。');
  return {latitude: Number(latitude.toFixed(4)), longitude: Number(longitude.toFixed(4)), source, accuracy};
}
export function createLocationPicker(root, {onChange, value = null}) {
  root.classList.add('location-picker');
  root.innerHTML = '<div class="location-picker-actions"><button class="btn" type="button" data-map-open>地図で撮影場所を指定</button><button class="btn" type="button" data-current>現在地を使う</button></div>'
    + '<p class="location-picker-note">現在地は、そこで撮った写真にだけ使ってください。指定した場所は記録に保存され、名前を調べるAIへ送られます。</p>'
    + '<div class="location-map-panel hidden"><p>地図を動かし、中央の十字を撮影場所に合わせてください。地図はOpenStreetMapから読み込みます。</p><div class="location-map-stage"><div class="location-map" aria-label="撮影場所を選ぶ地図"></div><span class="location-map-crosshair" aria-hidden="true">＋</span></div><button class="btn" type="button" data-map-use disabled>この場所を使う</button><button class="btn" type="button" data-map-close>地図を閉じる</button></div>'
    + '<p class="location-picker-status" role="status"></p>';
  const open = root.querySelector('[data-map-open]'), current = root.querySelector('[data-current]'), use = root.querySelector('[data-map-use]');
  const panel = root.querySelector('.location-map-panel'), canvas = root.querySelector('.location-map'), state = root.querySelector('[role="status"]');
  let point = value, map = null, marker = null, generation = 0, busy = false, disabled = false, draft = null;
  function controls() { open.disabled = current.disabled = disabled || busy; use.disabled = disabled || busy || !draft; }
  function setValue(next) { point = next; }
  async function commit(next) {
    busy = true; controls();
    try {
      const accepted = await onChange(next);
      if (accepted === false) { state.textContent = '場所は変更していません。'; return; }
      point = next;
      state.textContent = locationLabel(next) + ' を撮影場所にしました。';
      panel.classList.add('hidden');
    } catch (error) { state.textContent = error.message; }
    finally { busy = false; controls(); }
  }
  function reset(next = null) {
    generation++; point = next; draft = null; busy = false;
    map?.remove(); map = marker = null; canvas.replaceChildren();
    panel.classList.add('hidden'); state.textContent = ''; controls();
  }
  open.onclick = async () => {
    const token = generation;
    busy = true; controls(); state.textContent = '地図を読み込んでいます…';
    try {
      await loadLeaflet(); if (token !== generation) return;
      panel.classList.remove('hidden');
      if (!map) {
        map = L.map(canvas).setView(point ? [point.latitude, point.longitude] : [36.2, 138.2], point ? 15 : 5);
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
        const select = () => {
          const center = map.getCenter().wrap();
          draft = roundedPoint(center.lat, center.lng, 'map');
          if (marker) marker.setLatLng([draft.latitude, draft.longitude]);
          else marker = L.marker([draft.latitude, draft.longitude]).addTo(map);
          state.textContent = locationLabel(draft) + '（まだ保存していません）'; controls();
        };
        map.on('moveend', select);
        map.on('click', event => { map.setView(event.latlng, Math.max(map.getZoom(), 15), {animate:false}); select(); });
        if (point) select();
      }
      map.invalidateSize({pan:false});
      state.textContent = draft ? locationLabel(draft) + '（この場所を使うと撮影場所を更新します）' : '地図を動かして撮影場所を選んでください。';
    } catch (error) { if (token === generation) state.textContent = error.message; }
    finally { if (token === generation) { busy = false; controls(); } }
  };
  use.onclick = () => { if (draft) commit(draft); };
  root.querySelector('[data-map-close]').onclick = () => panel.classList.add('hidden');
  current.onclick = () => {
    if (!navigator.geolocation) { state.textContent = 'このブラウザでは現在地を取得できません。地図で指定してください。'; return; }
    const token = generation;
    busy = true; controls(); state.textContent = '現在地を取得しています…';
    navigator.geolocation.getCurrentPosition(position => {
      if (token !== generation) return;
      try { commit(roundedPoint(position.coords.latitude, position.coords.longitude, 'current', Math.max(11, position.coords.accuracy || 11))); }
      catch (error) { busy = false; controls(); state.textContent = error.message; }
    }, error => {
      if (token !== generation) return;
      busy = false; controls();
      state.textContent = error.code === 1 ? '現在地が許可されていません。地図で撮影場所を指定できます。' : error.code === 2 ? '現在地を取得できませんでした。地図で撮影場所を指定できます。' : '現在地の取得に時間がかかりました。もう一度押すか、地図で指定してください。';
    }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 0});
  };
  return {setValue, reset, setDisabled(next) { disabled = next; controls(); }, get map() { return map; }};
}
