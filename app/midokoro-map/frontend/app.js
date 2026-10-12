import {prepare, activate} from './runtime.js';

const kinds = ['explore','shiseki','omatsuri','onsen','tokusan','geo'];
const labels = {explore:'地域から探す',shiseki:'史跡',omatsuri:'祭り',onsen:'温泉',tokusan:'特産物',geo:'地形・地質'};
const storageKey = 'midokoro-map:last-kind';
let config;
let requestNumber = 0;

for (const button of document.querySelectorAll('[data-workspace-target]')) {
  button.addEventListener('click', () => {
    const root = document.querySelector('#workspace > .view-host:not([hidden])')?.shadowRoot;
    const search = button.dataset.workspaceTarget === 'search';
    const region = root?.querySelector(search ? '.workbench' : '.map-region');
    if (!region) return;
    region.scrollIntoView({block:'start', behavior:'instant'});
    const target = search ? root.querySelector('#keyword') : region;
    if (!search) target.tabIndex = -1;
    target?.focus({preventScroll:true});
  });
}

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
    const url = new URL(location.href);
    if (url.searchParams.get('kind') !== kind) {
      for (const key of ['qid','prefecture','category','keyword','bounds','map','item']) url.searchParams.delete(key);
    }
    url.searchParams.set('kind',kind);
    history.replaceState(null,'',url);
    context.onActivated?.();
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
  await choose(kinds.includes(explicit)?explicit:kinds.includes(saved)?saved:'explore');
} catch (error) {
  document.querySelector('#status').textContent = '設定を読み込めませんでした。ページを再読み込みしてください。';
}
