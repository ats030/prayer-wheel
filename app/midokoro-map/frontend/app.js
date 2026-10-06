import {prepare, activate} from './runtime.js';

const kinds = ['shiseki','omatsuri','onsen','tokusan'];
const labels = {shiseki:'史跡',omatsuri:'祭り',onsen:'温泉',tokusan:'特産物'};
const storageKey = 'midokoro-map:last-kind';
let config;
let requestNumber = 0;

function storedKind() { try { return localStorage.getItem(storageKey); } catch { return null; } }
async function choose(kind, focus=false) {
  if (!kinds.includes(kind) || !config) return;
  const request = ++requestNumber;
  const status = document.querySelector('#status');
  status.hidden = false;
  status.textContent = labels[kind]+'を読み込んでいます…';
  try {
    const context = await prepare(kind, config);
    if (request !== requestNumber) return;
    await activate(context);
    if (request !== requestNumber) return;
    for (const tab of document.querySelectorAll('[role=tab]')) {
      const selected = tab.dataset.kind === kind;
      tab.setAttribute('aria-selected',String(selected));
      tab.tabIndex = selected ? 0 : -1;
    }
    try { localStorage.setItem(storageKey,kind); } catch {}
    const url = new URL(location.href); url.searchParams.set('kind',kind);
    history.replaceState(null,'',url);
    document.title = 'みどころマップ｜'+labels[kind];
    status.hidden = true;
    if (focus) document.querySelector('#tab-'+kind).focus({preventScroll:true});
  } catch (error) {
    if (request !== requestNumber) return;
    console.error('Map view could not be loaded',error);
    status.replaceChildren(document.createTextNode('画面を読み込めませんでした。'));
    const retry = document.createElement('button'); retry.textContent='再試行';
    retry.onclick = ()=>choose(kind,focus); status.append(retry);
  }
}

for (const tab of document.querySelectorAll('[role=tab]')) {
  tab.addEventListener('click',()=>choose(tab.dataset.kind));
  tab.addEventListener('keydown',event=>{
    const index = kinds.indexOf(tab.dataset.kind);
    const next = event.key==='ArrowRight'?(index+1)%kinds.length:
      event.key==='ArrowLeft'?(index+kinds.length-1)%kinds.length:
      event.key==='Home'?0:event.key==='End'?kinds.length-1:null;
    if (next!==null) { event.preventDefault(); choose(kinds[next],true); }
  });
}

try {
  const response = await fetch('/api/config');
  if (!response.ok) throw new Error('configuration unavailable');
  config = await response.json();
  const explicit = new URL(location.href).searchParams.get('kind');
  const saved = storedKind();
  await choose(kinds.includes(explicit)?explicit:kinds.includes(saved)?saved:config.defaultKind);
} catch (error) {
  document.querySelector('#status').textContent = '設定を読み込めませんでした。ページを再読み込みしてください。';
}
