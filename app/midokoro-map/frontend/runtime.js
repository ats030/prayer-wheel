// Shared Leaflet instance, data transport, and scoped category UI.
import {summaryRenderer} from './summaries.js';
const views = new Map();
const preparing = new Map();
let activeKind = null;
let sharedMap = null;
let container = null;
const eventBindings = new Map();

export function activeMap() { return sharedMap; }

function resizeWithoutMoving() {
  if (!sharedMap) return;
  const center = sharedMap.getCenter(), zoom = sharedMap.getZoom();
  sharedMap.invalidateSize({pan:false});
  if (!sharedMap.getCenter().equals(center)) sharedMap.setView(center, zoom, {reset:true, animate:false});
}

function attachMap(context) {
  const region = context.root.querySelector('.map-region');
  if (!container) {
    container = context.root.querySelector('#map');
    sharedMap = L.map(container, {preferCanvas:true, maxZoom:18}).setView([36.2,138.2],5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom:19,
    }).addTo(sharedMap);
  } else {
    context.root.querySelector('#map')?.remove();
    region.prepend(container);
  }
  resizeWithoutMoving();
}

function scopedMap(context) {
  const mutators = new Set(['setView','flyTo','panTo','fitBounds','closePopup','invalidateSize']);
  let proxy;
  proxy = new Proxy({}, {
    set(_, key, value) { sharedMap[key] = value; return true; },
    get(_, key) {
      if (key === 'addLayer') return layer => {
        context.layers.add(layer);
        if (activeKind === context.kind) sharedMap.addLayer(layer);
        return proxy;
      };
      if (key === 'removeLayer') return layer => {
        context.layers.delete(layer);
        if (sharedMap.hasLayer(layer)) sharedMap.removeLayer(layer);
        return proxy;
      };
      if (key === 'on') return (event, handler) => {
        const wrapper = (...args) => { if (activeKind === context.kind) handler(...args); };
        eventBindings.set(handler, {event, wrapper});
        sharedMap.on(event, wrapper);
        return proxy;
      };
      if (key === 'off') return (event, handler) => {
        const binding = eventBindings.get(handler);
        if (binding) { sharedMap.off(event, binding.wrapper); eventBindings.delete(handler); }
        return proxy;
      };
      const value = sharedMap[key];
      if (typeof value !== 'function') return value;
      return (...args) => {
        if (mutators.has(key) && activeKind !== context.kind) return proxy;
        const result = value.apply(sharedMap, args);
        return result === sharedMap ? proxy : result;
      };
    },
  });
  return proxy;
}

function scopedDocument(root, host) {
  return new Proxy(document, {
    get(target, key) {
      if (key === 'querySelector' || key === 'querySelectorAll') return root[key].bind(root);
      if (key === 'getElementById') return id => root.querySelector('#'+CSS.escape(id));
      if (key === 'documentElement') return host;
      if (key === 'body') return root;
      if (key === 'addEventListener') return root.addEventListener.bind(root);
      const value = target[key];
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
}

export async function prepare(kind, config) {
  if (views.has(kind)) return views.get(kind);
  if (preparing.has(kind)) return preparing.get(kind);
  const pending = buildView(kind, config);
  preparing.set(kind, pending);
  try { return await pending; } finally { preparing.delete(kind); }
}

async function buildView(kind, config) {
  const host = document.createElement('section');
  host.className = 'view-host';
  host.hidden = true;
  host.id = 'view-'+kind;
  host.setAttribute('role','tabpanel');
  host.setAttribute('aria-labelledby','tab-'+kind);
  const root = host.attachShadow({mode:'open'});
  const response = await fetch('/assets/'+kind+'/view.html');
  if (!response.ok) throw new Error('画面を読み込めませんでした。');
  const css = ['/vendor/leaflet.css','/vendor/MarkerCluster.css','/vendor/MarkerCluster.Default.css','/assets/'+kind+'/app.css'];
  if (kind !== 'geo') css.push('/assets/'+kind+'/detail-panel.css');
  root.innerHTML = css.map(href=>`<link rel="stylesheet" href="${href}">`).join('') + await response.text() +
    '<style>:host{display:block;height:100%;min-width:0;overflow-x:clip}h2{margin:0;font:700 1.3rem var(--font-display)}.app-shell{min-height:100%}#map{width:100%;height:100%}.leaflet-control-layers-selector{width:auto;height:auto;margin:0 .3rem 0 0;padding:0;accent-color:#2f6f4f}</style>';
  const legend = root.querySelector('.map-legend');
  if (legend) {
    legend.id = 'map-legend';
    const toggle = document.createElement('button');
    toggle.className = 'legend-toggle'; toggle.textContent = '凡例';
    toggle.setAttribute('aria-controls', 'map-legend'); toggle.setAttribute('aria-expanded', 'false');
    toggle.onclick = () => {
      const expanded = root.querySelector('.map-region').classList.toggle('legend-open');
      toggle.setAttribute('aria-expanded', String(expanded));
    };
    root.querySelector('.map-region').append(toggle);
    const style = document.createElement('style');
    style.textContent = `.legend-toggle{display:none}@media(max-width:768px){.legend-toggle{display:block;position:absolute;z-index:600;top:3.5rem;right:1rem;min-height:2.75rem;padding:0 .75rem;border:1px solid var(--color-rule);border-radius:3px;background:var(--color-paper);color:var(--color-ink);font:700 .8rem var(--font-body);cursor:pointer}.legend-toggle:hover{background:var(--color-paper-2)}.legend-toggle:focus-visible{outline:3px solid var(--color-focus);outline-offset:2px}.legend-toggle:active{background:var(--color-paper-2)}.legend-toggle:disabled{opacity:.5;cursor:not-allowed}.map-legend{display:none}.legend-open .map-legend{display:grid;top:6.5rem;bottom:auto;left:auto;right:1rem;max-height:calc(46svh - 8rem);overflow:auto}}`;
    root.append(style);
  }
  document.querySelector('#workspace').append(host);
  const context = {kind, host, root, config, layers:new Set(), mounted:false};
  context.document = scopedDocument(root, host);
  context.fetch = (input, options) => {
    if (typeof input === 'string' && input.startsWith('/api/')) input = '/api/'+kind+input.slice(4);
    else if (typeof input === 'string' && input.startsWith('/') && !input.startsWith('//')) input = '/assets/'+kind+input;
    return fetch(input, options);
  };
  context.summariesOnly = config.summariesOnly === true;
  context.hydrateSummary = summaryRenderer(context);
  // Wait for styles before computing category colours or sizing the map.
  try {
  await Promise.all([...root.querySelectorAll('link')].map(link=>new Promise((resolve,reject)=>{
    if (link.sheet) return resolve();
    link.onload=resolve; link.onerror=()=>reject(new Error('表示スタイルを読み込めませんでした。'));
  })));
  context.module = await import('/assets/'+kind+'/view.js');
  } catch (error) { host.remove(); throw error; }
  views.set(kind, context);
  return context;
}

export async function activate(context) {
  sharedMap?.stop();
  sharedMap?.closePopup();
  const previous = views.get(activeKind);
  if (previous) {
    for (const layer of previous.layers) if (sharedMap.hasLayer(layer)) sharedMap.removeLayer(layer);
    previous.root.querySelector('dialog[open]')?.close();
    previous.host.hidden = true;
  }
  activeKind = context.kind;
  context.host.hidden = false;
  attachMap(context);
  context.map ||= scopedMap(context);
  if (!context.mounted) {
    context.module.mount(context);
    context.mounted = true;
  } else {
    for (const layer of context.layers) sharedMap.addLayer(layer);
  }
  requestAnimationFrame(resizeWithoutMoving);
  // A public test/debug hook exposes only map coordinates and category state.
  window.midokoro = {get kind(){return activeKind;}, map:sharedMap};
}
