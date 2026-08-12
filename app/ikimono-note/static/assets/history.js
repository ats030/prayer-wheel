const $=x=>document.getElementById(x),esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));function openDb(){return new Promise((ok,no)=>{const r=indexedDB.open("species-history",1);r.onupgradeneeded=()=>{if(!r.result.objectStoreNames.contains("entries"))r.result.createObjectStore("entries",{keyPath:"id"})};r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)})}function request(r){return new Promise((ok,no)=>{r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)})}function finished(t){return new Promise((ok,no)=>{t.oncomplete=ok;t.onerror=()=>no(t.error)})}const title=e=>e.candidates?.[0]?.common_name_ja||e.category||"調べた記録";
async function all(){const d=await openDb(),t=d.transaction("entries"),v=await request(t.objectStore("entries").getAll());await finished(t);d.close();return v.sort((a,b)=>b.createdAt.localeCompare(a.createdAt))}let mapEntries=[];
function loadLeaflet(){if(window.L)return Promise.resolve();return new Promise((ok,no)=>{const css=document.createElement("link");css.rel="stylesheet";css.href="/vendor/leaflet/leaflet.css";document.head.append(css);const js=document.createElement("script");js.src="/vendor/leaflet/leaflet.js";js.onload=()=>ok();js.onerror=()=>no(new Error("地図を読み込めませんでした。"));document.head.append(js)})}
async function showMap(){const button=$("showMap");button.disabled=true;button.textContent="地図を読み込み中…";try{await loadLeaflet();$("historyMap").classList.remove("hidden");map(mapEntries);button.remove()}catch(e){button.disabled=false;button.textContent="地図を表示";$("mapNotice").textContent=e.message}}
$("showMap").onclick=showMap;
/* 地図の下敷き。どこで見つけたかを思い出すには、道より地形が要ることがある。
   国土地理院のタイルは出典を示せば自由に使える (政府標準利用規約)。日本の外は
   写らないので、標準の地図は OpenStreetMap のままにする。 */
const MAP_LAYERS = {
  "地図": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png",
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'],
  "地形": ["https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png",
          '<a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>（色別標高図）'],
  "起伏": ["https://cyberjapandata.gsi.go.jp/xyz/hillshademap/{z}/{x}/{y}.png",
          '<a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>（陰影起伏図）'],
  "写真": ["https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg",
          '<a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>（写真）'],
};

function map(entries){
  const m=L.map("historyMap"),points=[];
  const layers={};
  for(const [name,[url,credit]] of Object.entries(MAP_LAYERS)){
    layers[name]=L.tileLayer(url,{maxZoom:18,attribution:credit});
  }
  layers["地図"].addTo(m);
  L.control.layers(layers,null,{collapsed:false}).addTo(m);
entries.forEach(e=>{const a=Number(e.coordinates?.latitude),o=Number(e.coordinates?.longitude);if(Number.isFinite(a)&&Number.isFinite(o)){points.push([a,o]);L.marker([a,o]).addTo(m).bindPopup("<strong>"+esc(title(e))+"</strong><br>"+esc(new Date(e.createdAt).toLocaleString("ja-JP")))}});points.length?m.fitBounds(points,{padding:[24,24],maxZoom:15}):m.setView([36.2,138.2],5)}
async function render(){const entries=await all();mapEntries=entries;const located=entries.filter(e=>Number.isFinite(Number(e.coordinates?.latitude))&&Number.isFinite(Number(e.coordinates?.longitude)));$("showMap").disabled=!located.length;if(!located.length)$("mapNotice").textContent="場所を記録した記録がまだないため、地図は表示できません。";$("clear").disabled=!entries.length;$("historyList").innerHTML=entries.length?entries.map(e=>{const image=e.thumbnail?URL.createObjectURL(e.thumbnail):"";return '<article class="entry" data-id="'+esc(e.id)+'">'+(image?'<button class="btn photo" data-src="'+image+'"><img class="thumb" src="'+image+'" alt=""></button>':'<div class="thumb"></div>')+'<div><div class="name">'+esc(title(e))+'</div><div class="muted">'+esc(new Date(e.createdAt).toLocaleString("ja-JP"))+' · '+esc(providerLabel(e.provider))+'</div><div class="muted">'+esc(e.context?.location||"場所の記録なし")+'</div></div><div class="entry-actions">'+(e.thumbnail?'<button class="btn again" type="button">もう一度調べる</button>':"")+'<button class="btn delete one">削除</button></div>'+'<p class="again-message" hidden></p><details class="detail"><summary>調べた内容を見る</summary><p>'+esc(e.summary||"")+'</p><ol>'+(e.candidates||[]).map(c=>'<li>'+esc(commonNameLabel(c))+' <span class="muted">'+esc(c.scientific_name||"")+'</span>'+candidateLinks(c)+'</li>').join("")+'</ol></details></article>'}).join(""):'<div class="empty">まだ調べた記録はありません。</div>';document.querySelectorAll(".photo").forEach(b=>b.onclick=()=>{$("large").src=b.dataset.src;$("lightbox").showModal()});document.querySelectorAll(".entry").forEach(node=>{const b=node.querySelector(".again");if(!b)return;const rec=entries.find(e=>String(e.id)===node.dataset.id);if(rec)b.onclick=()=>reidentify(rec,b,node.querySelector(".again-message"))});document.querySelectorAll(".one").forEach(b=>b.onclick=async()=>{const d=await openDb(),t=d.transaction("entries","readwrite");t.objectStore("entries").delete(b.closest("article").dataset.id);await finished(t);scheduleAutoBackup();location.reload()})}$("close").onclick=()=>$("lightbox").close();$("clear").onclick=async()=>{if(confirm("この端末に保存した記録をすべて削除しますか？")){const d=await openDb(),t=d.transaction("entries","readwrite");t.objectStore("entries").clear();await finished(t);scheduleAutoBackup();location.reload()}};render().catch(e=>$("historyList").innerHTML='<div class="empty">記録を読み込めませんでした。 '+esc(e.message)+'</div>');
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
/* 記録側にも出す。指定を見落として持ち帰るのは、結果を見た日とは限らない。
   一致した候補にだけ付く (protected_species がない＝指定なし、ではない) */
function protectedBadge(c){const p=c.protected_species;if(!p||!p.category)return "";
  return '<div class="protected">種の保存法の'+esc(p.category)+(p.subtype?"（"+esc(p.subtype)+"）":"")+'です'
    +' <a target="_blank" rel="noopener noreferrer" href="https://www.env.go.jp/nature/kisho/domestic/list.html">環境省の一覧 ↗</a></div>'}
function fullCandidate(c,category){const rank=({species:"種の候補",genus:"属（近いなかま）の候補",family:"科（大きなグループ）の候補"})[c.taxon_rank]||"グループの記録なし",status=c.evidence_status==="uncertain"?"決め手なし":c.evidence_status==="corroborated"?"2つの方法で確認":"写真からの推測";return '<li class="candidate"><strong>'+esc(commonNameLabel(c))+'</strong> <span class="muted">'+esc(c.scientific_name||"")+'</span><div><span class="badge">'+rank+'</span><span class="badge">'+status+'</span>'+taxonomyBadge(c)+(c.evidence_strength?'<span class="badge">証拠の強さ '+esc(c.evidence_strength)+'</span>':"")+(Number.isFinite(Number(c.confidence))?'<span class="badge">最大 '+esc(c.confidence)+'%</span>':"")+'</div>'+confidenceMeter(c)+protectedBadge(c)+candidateLinks(c,category)+evidence("写真から見つけた特徴（AI抽出・未確認）",c.traits)+evidence("似ている種との見分け方",c.distinguishing_features)+evidence("合わない点",c.contradictions)+evidence("決め手が足りない理由",c.evidence_gaps)+(c.uncertainty?'<div class="label">もっと確かめたいこと</div><div>'+esc(c.uncertainty)+'</div>':"")+(c.sex&&c.sex!=="対象外"?'<div class="label">オス・メスの推測</div><div>'+esc(c.sex)+'</div>'+evidence("そう考えた理由",c.sex_evidence):"")+'</li>'}function fullDetail(e){const x=e.context||{},m=e.resultMeta||{},c=e.coordinates;return '<div class="facts">'+(e.category?'<div>分類：'+esc(e.category)+'</div>':"")+(e.summary?'<div>'+esc(e.summary)+'</div>':"")+((e.provider||e.model)?'<div>使ったAI：'+esc([providerLabel(e.provider),e.model].filter(Boolean).join(" · "))+'</div>':"")+(x.observedDate?'<div>撮った日：'+esc(x.observedDate)+'</div>':"")+(x.size?'<div>大きさ：'+esc(x.size)+'</div>':"")+(x.location?'<div>撮った場所：'+esc(x.location)+'</div>':"")+(c?'<div>位置：'+esc(c.latitude)+'、'+esc(c.longitude)+'（おおまかな値）</div>':"")+(m.strictMode?'<div>まちがい防止：学名を図鑑データで自動チェック</div>':"")+(m.taxonomyChecked?'<div>学名を図鑑データで確認済み'+(m.rejectedCandidates?' · 除いた候補 '+esc(m.rejectedCandidates)+'件':"")+'</div>':"")+(m.plantnetUsed?'<div>植物の候補は <a href="https://plantnet.org/" target="_blank" rel="noopener noreferrer">Pl@ntNet recognition API</a> によるもの</div>':"")+'</div><ol>'+(e.candidates||[]).map(c=>fullCandidate(c,e.category)).join("")+'</ol>'}async function enrich(){const records=await all(),byId=new Map(records.map(e=>[String(e.id),e]));document.querySelectorAll(".entry").forEach(node=>{const e=byId.get(node.dataset.id);if(e)node.querySelector(".detail").innerHTML='<summary>調べた内容を見る</summary>'+fullDetail(e)});document.querySelectorAll('.meter span[data-width]').forEach(bar=>{bar.style.width=bar.dataset.width+'%'})}setTimeout(()=>enrich().catch(e=>console.error("記録の詳細を組み立てられませんでした", e)),0);
/* 「食べられるかは判定しません」と言っている隣に食品を並べない。誤同定のとき
   危険な後押しになる。語による除外なので完全ではないが、明らかなものは落とす */
const EDIBLE_WORDS=["茶","ティー","食用","乾燥","天日干し","サプリ","パウダー","粉末","エキス","おやつ","フード","ドリンク","健康食品","コーヒー","はちみつ","ハーブティー"];
function looksEdible(title){const t=String(title||"");return EDIBLE_WORDS.some(w=>t.includes(w))}
function shuffle(items){const a=[...items];for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]]}return a}
function productCard(p){return '<a class="product-card" href="'+esc(p.url)+'" target="_blank" rel="sponsored noopener noreferrer" aria-label="広告: '+esc(p.title)+'"><img class="product-image" src="'+esc(p.image)+'" alt="" loading="lazy" referrerpolicy="no-referrer"><span class="product-title">'+esc(p.title)+'</span></a>'}
function productQueries(record){
  /* 種名を先に試し、汎用の図鑑は最後の逃げ道にする。
     「分類+図鑑」は必ずヒットするので、先に置くとどの記録でも同じ図鑑が並ぶ。
     Books に絞る切り口を混ぜると、その種を扱った本へ寄る */
  /* 広告は第一候補にひもづける。候補ごとに商品が変わると、どの候補の話なのか
     読み手に分からない */
  const top=(record.candidates||[])[0];
  const name=top?displayName(top):"";
  const scientific=String(top?.scientific_name||"").trim();
  const category=record.category||"";
  const grow=category==="動物"?"飼育":category==="菌類"?"きのこ 栽培":"育て方";
  const specific=[];
  if(name){
    /* 種名だけで引くと食品が上位に来る (タンポポ → たんぽぽ茶)。安全カードで
       「食べられるかは判定しません」と言っている隣に食品を並べると、誤同定のとき
       危険な後押しになる。用途を添えて観察・栽培の周辺へ寄せる */
    specific.push({q:name,index:"Books"});          // その種を扱った本
    specific.push({q:name+" 観察",index:"All"});
    specific.push({q:name+" "+grow,index:"All"});
  }
  if(scientific&&scientific!==name)specific.push({q:scientific,index:"Books"});
  /* ここまでで出なければ、分類群の一般書へ落とす */
  const generic=category?[{q:category+" 図鑑",index:"Books",generic:true},{q:category+" 観察 ルーペ",index:"All",generic:true}]:[];
  return [...shuffle(specific).slice(0,3),...generic];
}
async function loadProducts(record,shell){
  /* 記録を開いたときだけ叩く。一覧を出すだけで全記録ぶんの商品APIを呼ばない */
  if(shell.dataset.loaded)return;
  shell.dataset.loaded="1";
  /* 種名で引くと1件しか返らないことが多い。切り口をまたいで集め、重複を除いて並べる。
     先に試すのは種そのもの、足りないぶんを分類群の一般書で補う */
  const found={specific:[],generic:[]},seen=new Set();
  let attempts=0;
  for(const query of productQueries(record)){
    const enough=found.specific.length+Math.min(found.generic.length,2)>=4;
    if(enough||attempts>=4)break;
    attempts++;
    try{
      const r=await fetch("/api/amazon/products?q="+encodeURIComponent(query.q)+"&index="+encodeURIComponent(query.index));
      if(!r.ok)continue;
      const data=await r.json();
      for(const product of (Array.isArray(data.products)?data.products:[])){
        /* 同じ品が別URLで返ることがあるので、題名でも重複を見る */
        const key=String(product?.title||"").trim();
        if(!product?.url||seen.has(product.url)||seen.has(key)||looksEdible(product.title))continue;
        seen.add(product.url);seen.add(key);
        found[query.generic?"generic":"specific"].push(product);
      }
    }catch(e){/* 次の切り口を試す */}
  }
  /* 分類群の一般書は枠を埋めるための保険。多くても2件までにして、
     その種に固有の品が押しのけられないようにする */
  const collected=[...shuffle(found.specific),...shuffle(found.generic).slice(0,2)].slice(0,4);
  if(collected.length){
    shell.innerHTML='<div class="affiliate-label">広告 · Amazonの関連商品</div><div class="product-grid">'+collected.map(productCard).join("")+'</div>';
    shell.querySelectorAll(".product-card").forEach(link=>link.onclick=()=>fetch("/api/affiliate/click",{method:"POST",keepalive:true}).catch(()=>{}));
    return;
  }
  /* window.name を拾わないよう、記録から取り直す */
  const topCandidate=(record.candidates||[])[0];
  const fallback=topCandidate?displayName(topCandidate):"";
  if(fallback)shell.innerHTML='<a class="product-fallback" href="/affiliate/click?q='+encodeURIComponent(fallback+" "+(record.category||""))+'" target="_blank" rel="sponsored noopener noreferrer">広告 · Amazonで'+esc(fallback)+'の関連商品を探す ↗</a>';
}
async function reidentify(record,button,message){
  /* 元の写真は保存していない。記録の縮小画像 (長辺960px) を送り直す。
     解像度が落ちているぶん、撮ったばかりの写真より不利になることがある */
  if(!record.thumbnail){message.textContent="この記録には写真が残っていないため、調べ直せません。";message.hidden=false;return}
  const label=button.textContent;
  button.disabled=true;button.textContent="調べ直しています…";message.hidden=true;
  try{
    const settings=await fetch("/api/settings").then(r=>r.ok?r.json():null);
    if(!settings)throw new Error("設定を読み込めませんでした");
    const fd=new FormData();
    fd.append("files",record.thumbnail,"photo.jpg");
    fd.append("location",record.context?.location||"");
    fd.append("observed_date",record.context?.observedDate||"");
    fd.append("size",record.context?.size||"");
    if(settings.public_mode){
      const saved=JSON.parse(localStorage.getItem("species-public-settings")||"{}");
      const provider=saved.provider||settings.provider;
      fd.append("request_provider",provider);
      fd.append("request_model",saved.models?.[provider]||settings.models?.[provider]||"");
      fd.append("request_api_key",readApiKey(provider));
      fd.append("request_plantnet_key",readApiKey("plantnet"));
    }
    const response=await fetch("/identify",{method:"POST",body:fd});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||"調べられませんでした");
    await saveRerun(record,data);
    location.reload();
  }catch(error){
    message.textContent=error.message;message.hidden=false;
    button.disabled=false;button.textContent=label;
  }
}
async function saveRerun(source,data){
  /* 元の記録は残し、新しい記録として足す。前後を見くらべられるようにする */
  const db=await openDb();
  const record={
    id:(crypto.randomUUID?.()||Date.now()+"-"+Math.random()),
    createdAt:new Date().toISOString(),
    category:data.category,summary:data.summary,candidates:data.candidates,
    provider:providerLabel(data.provider)||source.provider||"",model:data.model||"",
    resultMeta:{strictMode:Boolean(data.strict_mode),taxonomyChecked:Boolean(data.taxonomy_checked),
                rejectedCandidates:Number(data.rejected_candidates||0),plantnetUsed:Boolean(data.plantnet_used),
                rerunOf:source.id},
    context:source.context||{},coordinates:source.coordinates||null,thumbnail:source.thumbnail,
  };
  let tx=db.transaction("entries","readwrite");
  tx.objectStore("entries").put(record);
  await finished(tx);
  tx=db.transaction("entries","readonly");
  const rows=await request(tx.objectStore("entries").getAll());
  await finished(tx);
  const excess=rows.sort((a,b)=>b.createdAt.localeCompare(a.createdAt)).slice(50);
  if(excess.length){tx=db.transaction("entries","readwrite");excess.forEach(item=>tx.objectStore("entries").delete(item.id));await finished(tx)}
  db.close();
  scheduleAutoBackup();
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

/* 最後にドライブへ書けたかを出す。黙って失敗していると、記録が残っていると
   思い込んだまま端末を変えて、全部消えたことに後で気づく */
(function showSaveState(){
  const el=document.getElementById("saveState");
  if(!el||typeof driveStatus!=="function")return;
  const state=driveStatus();
  if(!state){
    if(typeof driveLinked==="function"&&!driveLinked()){
      el.hidden=false;el.className="save-state warn";
      el.innerHTML='記録はこの端末の中だけにあります。<a href="/settings">設定</a>から Google ドライブにつなぐと、端末を変えても残ります。';
    }
    return;
  }
  el.hidden=false;
  const when=new Date(state.at).toLocaleString("ja-JP");
  if(state.ok){el.className="save-state ok";el.textContent=`Google ドライブに保存済み（${when}・${state.detail}）`}
  else{el.className="save-state warn";
    el.innerHTML=`Google ドライブへ保存できていません（${when}・${esc(state.detail)}）。<a href="/settings">設定</a>から確認してください。`}
})();
