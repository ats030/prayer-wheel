const $=x=>document.getElementById(x),esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));function openDb(){return new Promise((ok,no)=>{const r=indexedDB.open("species-history",1);r.onupgradeneeded=()=>{if(!r.result.objectStoreNames.contains("entries"))r.result.createObjectStore("entries",{keyPath:"id"})};r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)})}function request(r){return new Promise((ok,no)=>{r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)})}function finished(t){return new Promise((ok,no)=>{t.oncomplete=ok;t.onerror=()=>no(t.error)})}const title=e=>e.candidates?.[0]?.common_name_ja||e.category||"調べた記録";
async function all(){const d=await openDb(),t=d.transaction("entries"),v=await request(t.objectStore("entries").getAll());await finished(t);d.close();return v.sort((a,b)=>b.createdAt.localeCompare(a.createdAt))}let mapEntries=[];
function loadLeaflet(){if(window.L)return Promise.resolve();return new Promise((ok,no)=>{const css=document.createElement("link");css.rel="stylesheet";css.href="/vendor/leaflet/leaflet.css";document.head.append(css);const js=document.createElement("script");js.src="/vendor/leaflet/leaflet.js";js.onload=()=>ok();js.onerror=()=>no(new Error("地図を読み込めませんでした。"));document.head.append(js)})}
async function showMap(){const button=$("showMap");button.disabled=true;button.textContent="地図を読み込み中…";try{await loadLeaflet();$("historyMap").classList.remove("hidden");map(mapEntries);button.remove()}catch(e){button.disabled=false;button.textContent="地図を表示";$("mapNotice").textContent=e.message}}
$("showMap").onclick=showMap;
function map(entries){const m=L.map("historyMap"),points=[];L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> | <a href="https://leafletjs.com">Leaflet</a>'}).addTo(m);entries.forEach(e=>{const a=Number(e.coordinates?.latitude),o=Number(e.coordinates?.longitude);if(Number.isFinite(a)&&Number.isFinite(o)){points.push([a,o]);L.marker([a,o]).addTo(m).bindPopup("<strong>"+esc(title(e))+"</strong><br>"+esc(new Date(e.createdAt).toLocaleString("ja-JP")))}});points.length?m.fitBounds(points,{padding:[24,24],maxZoom:15}):m.setView([36.2,138.2],5)}
async function render(){const entries=await all();mapEntries=entries;const located=entries.filter(e=>Number.isFinite(Number(e.coordinates?.latitude))&&Number.isFinite(Number(e.coordinates?.longitude)));$("showMap").disabled=!located.length;if(!located.length)$("mapNotice").textContent="場所を記録した記録がまだないため、地図は表示できません。";$("clear").disabled=!entries.length;$("historyList").innerHTML=entries.length?entries.map(e=>{const image=e.thumbnail?URL.createObjectURL(e.thumbnail):"";return '<article class="entry" data-id="'+esc(e.id)+'">'+(image?'<button class="btn photo" data-src="'+image+'"><img class="thumb" src="'+image+'" alt=""></button>':'<div class="thumb"></div>')+'<div><div class="name">'+esc(title(e))+'</div><div class="muted">'+esc(new Date(e.createdAt).toLocaleString("ja-JP"))+' · '+esc(e.provider||"")+'</div><div class="muted">'+esc(e.context?.location||"場所の記録なし")+'</div></div><button class="btn delete one">削除</button><details class="detail"><summary>調べた内容を見る</summary><p>'+esc(e.summary||"")+'</p><ol>'+(e.candidates||[]).map(c=>'<li>'+esc(commonNameLabel(c))+' <span class="muted">'+esc(c.scientific_name||"")+'</span>'+candidateLinks(c)+'</li>').join("")+'</ol></details></article>'}).join(""):'<div class="empty">まだ調べた記録はありません。</div>';document.querySelectorAll(".photo").forEach(b=>b.onclick=()=>{$("large").src=b.dataset.src;$("lightbox").showModal()});document.querySelectorAll(".one").forEach(b=>b.onclick=async()=>{const d=await openDb(),t=d.transaction("entries","readwrite");t.objectStore("entries").delete(b.closest("article").dataset.id);await finished(t);location.reload()})}$("close").onclick=()=>$("lightbox").close();$("clear").onclick=async()=>{if(confirm("この端末に保存した記録をすべて削除しますか？")){const d=await openDb(),t=d.transaction("entries","readwrite");t.objectStore("entries").clear();await finished(t);location.reload()}};render().catch(e=>$("historyList").innerHTML='<div class="empty">記録を読み込めませんでした。 '+esc(e.message)+'</div>');
function evidence(label,items){return items?.length?'<div class="label">'+label+'</div><ul>'+items.map(x=>'<li>'+esc(x)+'</li>').join("")+'</ul>':""}function candidateLinks(c,category){
  /* 撮影画面と同じ参照先を、記録からも辿れるようにする */
  const name=displayName(c),links=[];
  if(name)links.push('<a target="_blank" rel="noopener noreferrer" href="'+esc(sourceUrl(name))+'">図鑑を検索 ↗</a>');
  const wiki=wikipediaUrl(c);
  if(wiki)links.push('<a target="_blank" rel="noopener noreferrer" href="'+esc(wiki)+'">Wikipedia ↗</a>');
  if(c?.taxonomy_url)links.push('<a target="_blank" rel="noopener noreferrer" href="'+esc(c.taxonomy_url)+'">iNaturalist ↗</a>');
  const ref=animalReference(c,category);
  if(ref)links.push('<a target="_blank" rel="noopener noreferrer" href="'+esc(ref.url)+'">'+esc(ref.label)+' ↗</a>');
  return links.length?'<div class="links">'+links.join("")+'</div>':"";
}
function taxonomyBadge(c){
  if(c?.taxonomy_status==="verified")return '<span class="badge verified">図鑑にある名前です</span>';
  if(c?.taxonomy_status==="unverified")return '<span class="badge">図鑑で名前を確認できず</span>';
  if(c?.taxonomy_status==="unavailable")return '<span class="badge">図鑑データに接続できず</span>';
  return "";
}
function confidenceMeter(c){
  const value=Math.max(0,Math.min(100,Number(c?.confidence)||0));
  return '<div class="meter"><span data-width="'+value+'"></span></div>';
}
function fullCandidate(c,category){const rank=({species:"種の候補",genus:"属（近いなかま）の候補",family:"科（大きなグループ）の候補"})[c.taxon_rank]||"グループの記録なし",status=c.evidence_status==="uncertain"?"決め手なし":c.evidence_status==="corroborated"?"2つの方法で確認":"写真からの推測";return '<li class="candidate"><strong>'+esc(commonNameLabel(c))+'</strong> <span class="muted">'+esc(c.scientific_name||"")+'</span><div><span class="badge">'+rank+'</span><span class="badge">'+status+'</span>'+taxonomyBadge(c)+(c.evidence_strength?'<span class="badge">証拠の強さ '+esc(c.evidence_strength)+'</span>':"")+(Number.isFinite(Number(c.confidence))?'<span class="badge">最大 '+esc(c.confidence)+'%</span>':"")+'</div>'+confidenceMeter(c)+candidateLinks(c,category)+evidence("写真から見つけた特徴（AI抽出・未確認）",c.traits)+evidence("似ている種との見分け方",c.distinguishing_features)+evidence("合わない点",c.contradictions)+evidence("決め手が足りない理由",c.evidence_gaps)+(c.uncertainty?'<div class="label">もっと確かめたいこと</div><div>'+esc(c.uncertainty)+'</div>':"")+(c.sex&&c.sex!=="対象外"?'<div class="label">オス・メスの推測</div><div>'+esc(c.sex)+'</div>'+evidence("そう考えた理由",c.sex_evidence):"")+'</li>'}function fullDetail(e){const x=e.context||{},m=e.resultMeta||{},c=e.coordinates;return '<div class="facts">'+(e.category?'<div>分類：'+esc(e.category)+'</div>':"")+(e.summary?'<div>'+esc(e.summary)+'</div>':"")+((e.provider||e.model)?'<div>使ったAI：'+esc([e.provider,e.model].filter(Boolean).join(" · "))+'</div>':"")+(x.observedDate?'<div>撮った日：'+esc(x.observedDate)+'</div>':"")+(x.size?'<div>大きさ：'+esc(x.size)+'</div>':"")+(x.location?'<div>撮った場所：'+esc(x.location)+'</div>':"")+(c?'<div>位置：'+esc(c.latitude)+'、'+esc(c.longitude)+'（おおまかな値）</div>':"")+(m.strictMode?'<div>まちがい防止：学名を図鑑データで自動チェック</div>':"")+(m.taxonomyChecked?'<div>学名を図鑑データで確認済み'+(m.rejectedCandidates?' · 除いた候補 '+esc(m.rejectedCandidates)+'件':"")+'</div>':"")+(m.plantnetUsed?'<div>植物の候補は <a href="https://plantnet.org/" target="_blank" rel="noopener noreferrer">Pl@ntNet recognition API</a> によるもの</div>':"")+'</div><ol>'+(e.candidates||[]).map(c=>fullCandidate(c,e.category)).join("")+'</ol>'}async function enrich(){const records=await all(),byId=new Map(records.map(e=>[String(e.id),e]));document.querySelectorAll(".entry").forEach(node=>{const e=byId.get(node.dataset.id);if(e)node.querySelector(".detail").innerHTML='<summary>調べた内容を見る</summary>'+fullDetail(e)});document.querySelectorAll('.meter span[data-width]').forEach(bar=>{bar.style.width=bar.dataset.width+'%'})}setTimeout(()=>enrich().catch(e=>console.error("記録の詳細を組み立てられませんでした", e)),0);
function shuffle(items){const a=[...items];for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]]}return a}
function productCard(p){return '<a class="product-card" href="'+esc(p.url)+'" target="_blank" rel="sponsored noopener noreferrer" aria-label="広告: '+esc(p.title)+'"><img class="product-image" src="'+esc(p.image)+'" alt="" loading="lazy" referrerpolicy="no-referrer"><span class="product-title">'+esc(p.title)+'</span></a>'}
function productQueries(record){
  /* 種名だけだと商品が無いことが多い。切り口をいくつか用意し、順に試す。
     並びをランダムにして、同じ記録を開くたびに違う品が出るようにする */
  const named=(record.candidates||[]).map(displayName).filter(Boolean);
  const name=named.length?named[Math.floor(Math.random()*named.length)]:"";
  const category=record.category||"";
  const angles=[];
  if(name)angles.push(name+" "+category, name+" 図鑑");
  if(category)angles.push(category+" 図鑑", category+" 観察 ルーペ");
  return shuffle(angles).slice(0,3);
}
async function loadProducts(record,shell){
  /* 記録を開いたときだけ叩く。一覧を出すだけで全記録ぶんの商品APIを呼ばない */
  if(shell.dataset.loaded)return;
  shell.dataset.loaded="1";
  for(const query of productQueries(record)){
    try{
      const r=await fetch("/api/amazon/products?q="+encodeURIComponent(query));
      if(!r.ok)continue;
      const data=await r.json();
      const products=Array.isArray(data.products)?shuffle(data.products):[];
      if(!products.length)continue;
      shell.innerHTML='<div class="affiliate-label">広告 · '+esc(query)+' の関連商品</div><div class="product-grid">'+products.map(productCard).join("")+'</div>';
      shell.querySelectorAll(".product-card").forEach(link=>link.onclick=()=>fetch("/api/affiliate/click",{method:"POST",keepalive:true}).catch(()=>{}));
      return;
    }catch(e){/* 次の切り口を試す */}
  }
  // どの切り口でも出なければ、従来どおり検索リンクへ落とす
  const fallback=(record.candidates||[]).map(displayName).find(Boolean);
  if(fallback)shell.innerHTML='<a class="product-fallback" href="/affiliate/click?q='+encodeURIComponent(fallback+" "+(record.category||""))+'" target="_blank" rel="sponsored noopener noreferrer">広告 · Amazonで'+esc(fallback)+'の関連商品を探す ↗</a>';
}
async function addAffiliateLinks(){
  const settings=await fetch("/api/settings").then(r=>r.ok?r.json():null).catch(()=>null);
  if(!settings?.affiliate?.enabled)return;
  const records=await all(),byId=new Map(records.map(e=>[String(e.id),e]));
  document.querySelectorAll(".entry").forEach(node=>{
    const record=byId.get(node.dataset.id);
    if(!record)return;
    const detail=node.querySelector(".detail");
    if(!detail||detail.querySelector(".product-shell"))return;
    const shell=document.createElement("div");
    shell.className="product-shell";
    detail.append(shell);
    const load=()=>{if(detail.open)loadProducts(record,shell)};
    detail.addEventListener("toggle",load);
    load();  // すでに開いている記録には即座に出す
  });
}
const addAffiliateLinksOnce=addAffiliateLinks;let affiliateLinksAdded=false;addAffiliateLinks=async()=>{if(affiliateLinksAdded)return;affiliateLinksAdded=true;await addAffiliateLinksOnce()};setTimeout(()=>enrich().then(addAffiliateLinks).catch(e=>console.error("記録の詳細を組み立てられませんでした", e)),0);
