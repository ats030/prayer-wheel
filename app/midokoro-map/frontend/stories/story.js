(() => {
  'use strict';
  const storySlug = document.body.dataset.story;
  const storyPath = '/stories/' + storySlug;
  const places = new Map([...document.querySelectorAll('.place-articles article')].map(el => [el.id, el]));
  const relations = new Map([...document.querySelectorAll('.relation-articles li')].map(el => [el.id, el]));
  const markers = new Map(), lines = new Map(), visited = new Set(), sent = new Set();
  let map, selectedPlace = null, selectedRelation = null;
  const tokens = getComputedStyle(document.documentElement);
  const lineColor = tokens.getPropertyValue('--color-ink').trim(), activeLineColor = tokens.getPropertyValue('--color-accent').trim();
  const status = document.querySelector('#map-status');
  const selection = document.querySelector('#selection');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelector('.explorer-grid').hidden = false;
  document.querySelector('#static-map-note').hidden = true;

  function record(event) {
    if (document.body.dataset.storyPreview === 'true') return;
    if (navigator.doNotTrack === '1' || sent.has(event)) return;
    sent.add(event);
    fetch('/api/story-events/' + storySlug + '/' + event, {
      method:'POST', credentials:'omit', referrerPolicy:'no-referrer', keepalive:true,
    }).catch(() => {}); // Measurement failure must not interrupt exploration.
  }
  record('view');
  const entry = new URL(location.href).searchParams.get('from');
  if (entry === 'home') record('entry-home');
  if (entry === 'shared') record('entry-shared');

  function coords(id) {
    const el = places.get(id);
    return [Number(el.dataset.lat), Number(el.dataset.lng)];
  }
  function content(el) {
    const clone = document.createElement('article');
    clone.append(...[...el.childNodes].map(child => child.cloneNode(true)));
    clone.querySelectorAll('[data-place], [data-relation]').forEach(link => link.remove());
    return clone;
  }
  function setAddress() {
    const url = new URL(location.href);
    url.hash = selectedRelation || selectedPlace || '';
    if (selectedRelation) url.searchParams.set('place', selectedPlace);
    else url.searchParams.delete('place');
    // A selection stays on the same page; do not manufacture PV with pushState.
    history.replaceState(null, '', url);
  }
  function updateMap() {
    for (const [id, marker] of markers) {
      marker.getElement()?.querySelector('.story-marker').classList.toggle('selected', id === selectedPlace);
    }
    for (const [id, line] of lines) {
      const relation = relations.get(id);
      const active = id === selectedRelation;
      const related = relation.dataset.from === selectedPlace || relation.dataset.to === selectedPlace;
      line.setStyle({color:active ? activeLineColor : lineColor, weight:active ? 5 : 2, opacity:active ? .95 : related ? .65 : .2});
      if (active) line.bringToFront();
    }
  }
  function select(id, relationID = null, interacted = false, move = true, updateAddress = true) {
    if (!places.has(id)) return;
    selectedPlace = id;
    selectedRelation = relations.has(relationID) ? relationID : null;
    visited.add(id);
    document.querySelector('#exploration-progress').textContent = visited.size + ' / ' + places.size + ' 地点を発見';
    document.querySelector('#selected-place').replaceChildren(content(places.get(id)));
    const detail = document.querySelector('#selected-relation');
    detail.hidden = !selectedRelation;
    detail.replaceChildren(...(selectedRelation ? [content(relations.get(selectedRelation))] : []));
    const related = document.querySelector('#related-places');
    related.replaceChildren();
    for (const [key, rel] of relations) {
      const other = rel.dataset.from === id ? rel.dataset.to : rel.dataset.to === id ? rel.dataset.from : null;
      if (!other) continue;
      const link = document.createElement('a');
      link.href = '#' + key;
      link.dataset.relation = key;
      link.dataset.destination = other;
      link.className = 'related-link';
      const title = document.createElement('strong');
      title.textContent = rel.querySelector('h3').textContent;
      link.append(title, document.createTextNode(places.get(other).querySelector('h3').textContent + 'へ →'));
      related.append(link);
    }
    document.querySelectorAll('.place-links [data-place]').forEach(link => {
      if (link.dataset.place === id) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
    selection.hidden = false;
    if (updateAddress) setAddress();
    if (interacted) { record('explore'); if (selectedRelation) record('follow'); }
    if (map) {
      map.invalidateSize({pan:false});
      updateMap();
      if (move) {
        const points = selectedRelation ? [coords(relations.get(selectedRelation).dataset.from), coords(relations.get(selectedRelation).dataset.to)] : [coords(id)];
        if (points.length > 1) map.fitBounds(points, {padding:[40,40], maxZoom:16, animate:!reducedMotion});
        else map.panTo(points[0], {animate:!reducedMotion});
      }
    }
    if (interacted) {
      const title = selection.querySelector('h3');
      title.tabIndex = -1;
      title.focus({preventScroll:true});
      document.querySelector('#explorer').scrollIntoView({behavior:'instant', block:'start'});
    }
  }
  function restore() {
    const key = location.hash.slice(1);
    if (relations.has(key)) {
      const rel = relations.get(key);
      const place = new URL(location.href).searchParams.get('place');
      select([rel.dataset.from, rel.dataset.to].includes(place) ? place : rel.dataset.to, key);
    }
    else if (places.has(key)) select(key, null, false, false);
    else if (!selectedPlace) select(places.keys().next().value, null, false, false, false);
  }
  document.addEventListener('click', event => {
    const link = event.target.closest('[data-place], [data-relation]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.dataset.relation && relations.has(link.dataset.relation)) {
      const rel = relations.get(link.dataset.relation);
      event.preventDefault();
      select(link.dataset.destination || rel.dataset.to, link.dataset.relation, true);
    } else if (places.has(link.dataset.place)) {
      event.preventDefault(); select(link.dataset.place, null, true);
    }
  });
  window.addEventListener('hashchange', restore);

  // All place/relationship text remains in HTML when Leaflet or tiles fail.
  try {
    if (!window.L) throw new Error('map unavailable');
    map = L.map('story-map', {scrollWheelZoom:false});
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom:19,
    }).addTo(map);
    tiles.on('tileerror', () => {
      status.hidden = false;
      status.textContent = '背景地図を読み込めません。番号の点と場所のリンクから、つながりをたどれます。';
    });
    for (const [id, rel] of relations) {
      const line = L.polyline([coords(rel.dataset.from), coords(rel.dataset.to)], {color:lineColor, weight:2, opacity:.3, dashArray:'6 7'}).addTo(map);
      line.bindTooltip(rel.querySelector('h3').textContent);
      line.on('click', () => select(rel.dataset.to, id, true));
      lines.set(id, line);
    }
    for (const [id, el] of places) {
      const name = el.querySelector('h3').textContent;
      const marker = L.marker(coords(id), {
        title:name, alt:name, keyboard:true,
        icon:L.divIcon({className:'', html:'<span class="story-marker">'+el.dataset.number+'</span>', iconSize:[30,30], iconAnchor:[15,15]}),
      }).addTo(map).bindTooltip(name);
      marker.on('click', () => select(id, null, true));
      markers.set(id, marker);
    }
    const bounds = [...places.keys()].map(coords);
    map.fitBounds(bounds, {padding:[45,45], maxZoom:15});
    document.querySelector('#map-reset').hidden = false;
    document.querySelector('#map-reset').onclick = () => map.fitBounds(bounds, {padding:[45,45], maxZoom:15, animate:!reducedMotion});
    new ResizeObserver(() => map.invalidateSize({pan:false})).observe(document.querySelector('#story-map'));
    status.hidden = true;
  } catch (_) {
    status.textContent = '地図を読み込めません。場所のリンクから、つながりをたどれます。';
  }
  restore();

  function sharedURL() {
    const url = new URL(storyPath, location.origin);
    url.searchParams.set('from', 'shared');
    url.hash = selectedRelation || selectedPlace || '';
    if (selectedRelation) url.searchParams.set('place', selectedPlace);
    return url.href;
  }
  function manualCopy(message) {
    document.querySelector('#share-status').textContent = message;
    document.querySelector('#manual-share').hidden = false;
    const input = document.querySelector('#share-url');
    input.value = sharedURL(); input.focus(); input.select();
  }
  const share = document.querySelector('#share-story');
  share.hidden = typeof navigator.share !== 'function';
  share.addEventListener('click', async () => {
    record('share-open');
    share.disabled = true;
    try {
      await navigator.share({title:document.querySelector('h1').textContent, text:document.querySelector('meta[property="og:description"]').content, url:sharedURL()});
      record('share-returned');
      document.querySelector('#share-status').textContent = '共有画面を閉じました。';
    } catch (error) {
      if (error.name === 'AbortError') document.querySelector('#share-status').textContent = '共有をキャンセルしました。';
      else manualCopy('共有画面を開けませんでした。URLをコピーできます。');
    } finally { share.disabled = false; }
  });
  document.querySelector('#copy-story').addEventListener('click', async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(sharedURL());
      document.querySelector('#share-status').textContent = 'リンクをコピーしました。';
      document.querySelector('#manual-share').hidden = true;
      record('copy-success');
    } catch (_) { manualCopy('自動コピーを使えません。このURLをコピーしてください。'); }
  });
  document.querySelector('#share-tools').hidden = false;
})();
