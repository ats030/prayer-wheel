const $=x=>document.getElementById(x),esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));function openDb(){return new Promise((ok,no)=>{const r=indexedDB.open("species-history",1);r.onupgradeneeded=()=>{if(!r.result.objectStoreNames.contains("entries"))r.result.createObjectStore("entries",{keyPath:"id"})};r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)})}function request(r){return new Promise((ok,no)=>{r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)})}function finished(t){return new Promise((ok,no)=>{t.oncomplete=ok;t.onerror=()=>no(t.error)})}/* 候補ゼロのとき分類名に落ちると、「菌類」という名前の生きものを見つけたように読める。
   分類は行の印のほうへ回す */
const title=e=>e.candidates?.[0]?.common_name_ja||(e.candidates?"候補が見つかりませんでした":"調べた記録");
async function all(){const d=await openDb(),t=d.transaction("entries"),v=await request(t.objectStore("entries").getAll());await finished(t);d.close();return v.sort((a,b)=>b.createdAt.localeCompare(a.createdAt))}let mapEntries=[];let rerunRecords=new Map();
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
/* 消す前に確かめる。記録は写真ごと消え、ドライブにつないでいれば次の自動保存で
   向こうからも消える。押し間違いで戻せなくなるのは、写真を残すようにしてから
   さらに重くなった (1件に最大3枚入っている) */
function driveNote(){
  return (typeof driveLinked==="function"&&driveLinked())
    ? "\nGoogle ドライブにつないでいるので、そちらからも消えます。":"";
}
function confirmDelete(what){
  return confirm(what+"\n写真もいっしょに消え、元に戻せません。"+driveNote());
}
/* 一覧の行は候補名を太字で出すだけだった。60%「2つの方法で確認」も30%「決め手なし」も
   同じ見た目で、結果画面が守っている「これは候補である」という約束を一覧だけが破っていた。
   記録は後日読み返すもので、そのときには確からしさの記憶が消えている。 */
const ROW_STATUS={corroborated:"2つの方法で確認",specialist_only:"植物のサービスだけが答えた",
                  taxonomy_only:"写真からの推測",uncertain:"決め手なし"};
function rowMarks(e){
  const top=(e.candidates||[])[0];
  const marks=[];
  if(!top)marks.push('<span class="badge">'+esc(e.category||"分類なし")+'</span>');
  else marks.push('<span class="badge'+(top.evidence_status==="corroborated"?" verified":"")+'">'
    +esc(ROW_STATUS[top.evidence_status]||"写真からの推測")+'</span>');
  /* 法律に関わる唯一の事実が、開かないと出てこないのはおかしい */
  if((e.candidates||[]).some(c=>c?.protected_species?.category))
    marks.push('<span class="badge protected-mark">種の保存法の指定</span>');
  return '<span class="row-marks">'+marks.join("")+'</span>';
}
async function render(){const entries=await all();mapEntries=entries;const located=entries.filter(e=>Number.isFinite(Number(e.coordinates?.latitude))&&Number.isFinite(Number(e.coordinates?.longitude)));$("showMap").disabled=!located.length;if(!located.length)$("mapNotice").textContent="場所を記録した記録がまだないため、地図は表示できません。";$("historyList").innerHTML=entries.length?entries.map(e=>{/* 行に出すのは小さいほう (50行ぶん展開するので)。押して開くのは原寸。
   ここを同じものにしていたため、拡大すると320pxが引き伸ばされて出ていた */
const full=recordPhotos(e)[0]||null;const small=e.listThumbnail||full;
const image=small?URL.createObjectURL(small):"";const large=full?URL.createObjectURL(full):image;
return '<article class="entry" data-id="'+esc(e.id)+'">'+(image?'<button class="btn photo" data-src="'+large+'"><img class="thumb" src="'+image+'" alt=""></button>':'<div class="thumb"></div>')+'<div><div class="name">'+esc(title(e))+rowMarks(e)+'</div><div class="muted">'+esc(new Date(e.createdAt).toLocaleString("ja-JP"))+' · '+esc(providerLabel(e.provider))+'</div><div class="muted">'+esc(e.context?.location||"場所の記録なし")+'</div></div><div class="entry-actions">'+(e.thumbnail?'<button class="btn again" type="button">もう一度調べる</button>':"")+'<button class="btn delete one">削除</button></div>'+'<p class="again-message" hidden></p><details class="detail"><summary>調べた内容を見る</summary><p>'+esc(e.summary||"")+'</p><ol>'+(e.candidates||[]).map(c=>'<li>'+esc(commonNameLabel(c))+' <span class="muted">'+esc(c.scientific_name||"")+'</span>'+candidateLinks(c)+'</li>').join("")+'</ol></details></article>'}).join(""):'<div class="empty">まだ調べた記録はありません。</div>';rerunRecords=new Map(entries.map(e=>[String(e.id),e]));/* 原寸がまだ手元にない記録 (別の端末から来たもの) は、押されたときに引く。
   引くまでは小さいほうを出しておく — 何も出さないより読み手の役に立つ */
document.querySelectorAll(".entry .photo").forEach(b=>b.onclick=async()=>{
  $("large").src=b.dataset.src;$("lightbox").showModal();
  const record=rerunRecords.get(b.closest("article").dataset.id);
  if(!record||recordPhotos(record).length)return;
  const photos=await pullPhotosIfMissing(record,b.closest("article"));
  if(photos&&photos[0])$("large").src=URL.createObjectURL(photos[0]);
});document.querySelectorAll(".entry").forEach(node=>{const b=node.querySelector(".again");if(!b)return;const rec=entries.find(e=>String(e.id)===node.dataset.id);if(rec)b.onclick=()=>reidentify(rec,b,node.querySelector(".again-message"))});document.querySelectorAll(".one").forEach(b=>b.onclick=async()=>{const node=b.closest("article");const entry=entries.find(e=>String(e.id)===node.dataset.id);if(!confirmDelete("「"+title(entry||{})+"」の記録を削除しますか？"))return;const d=await openDb(),t=d.transaction("entries","readwrite");t.objectStore("entries").delete(node.dataset.id);await finished(t);scheduleAutoBackup();location.reload()})}$("close").onclick=()=>$("lightbox").close();render().catch(e=>$("historyList").innerHTML='<div class="empty">記録を読み込めませんでした。 '+esc(e.message)+'</div>');
/* 開いた直後にドライブから取り込むことがある。一覧はもう描き終わっているので、
   届いたら描き直す。押していないのに中身が入れ替わるのは、記録が端末をまたいで
   同じものになるという約束のとおり */
document.addEventListener("species-records-restored",()=>{
  /* 描き直すと「調べた内容を見る」の中身も棚も作り直しになる。読み込み直後と
     同じ順で組み立てる (render → enrich → 広告)。ここを render だけにしていると、
     取り込んだ記録の詳細が簡易表示のまま、広告も付かない */
  affiliateLinksAdded=false;
  render().then(enrich).then(addAffiliateLinks).then(addRerunControls)
    .catch(e=>console.error("記録を描き直せませんでした",e));
});
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
function fullCandidate(c,category){const rank=({species:"種の候補",genus:"属（近いなかま）の候補",family:"科（大きなグループ）の候補"})[c.taxon_rank]||"グループの記録なし",status=c.evidence_status==="uncertain"?"決め手なし":c.evidence_status==="corroborated"?"2つの方法で確認":"写真からの推測";return '<li class="candidate"><strong>'+esc(commonNameLabel(c))+'</strong> <span class="muted">'+esc(c.scientific_name||"")+'</span><div><span class="badge">'+rank+'</span><span class="badge">'+status+'</span>'+taxonomyBadge(c)+(c.evidence_strength?'<span class="badge">証拠の強さ '+esc(c.evidence_strength)+'</span>':"")+(Number.isFinite(Number(c.confidence))?'<span class="badge">最大 '+esc(c.confidence)+'%</span>':"")+'</div>'+confidenceMeter(c)+protectedBadge(c)+candidateLinks(c,category)+evidence("写真から見つけた特徴（AI抽出・未確認）",c.traits)+evidence("似ている種との見分け方",c.distinguishing_features)+evidence("合わない点",c.contradictions)+evidence("決め手が足りない理由",c.evidence_gaps)+(c.uncertainty?'<div class="label">もっと確かめたいこと</div><div>'+esc(c.uncertainty)+'</div>':"")+(c.sex&&c.sex!=="対象外"?'<div class="label">オス・メスの推測</div><div>'+esc(c.sex)+'</div>'+evidence("そう考えた理由",c.sex_evidence):"")+'</li>'}/* 使った写真をすべて並べる。一覧のサムネイルは1枚目だけなので、撮り足した寄りの1枚は
   ここでしか見られない。押すと拡大するのは一覧のサムネイルと同じ */
function detailPhotos(e){const photos=recordPhotos(e);
  /* 別の端末から来た記録は、原寸をまだ手元に持っていない (ドライブの別ファイルにある)。
     開いたときに引きに行く。引けるまでは一覧用の小さい1枚だけ出す */
  if(!photos.length&&e.listThumbnail)return '<div class="detail-photos"><button class="photo detail-photo" type="button" data-src="'
    +URL.createObjectURL(e.listThumbnail)+'"><img src="'+URL.createObjectURL(e.listThumbnail)+'" alt="調べた写真"></button></div>'
    +'<div class="label">この記録で使った写真（原寸はこの端末にまだありません）</div>';
  if(photos.length<2)return "";
  return '<div class="detail-photos">'+photos.map((blob,i)=>'<button class="photo detail-photo" type="button" data-src="'
    +URL.createObjectURL(blob)+'"><img src="'+URL.createObjectURL(blob)+'" alt="調べた写真 '+(i+1)+'"></button>').join("")
    +'</div><div class="label">この記録で使った写真 '+photos.length+'枚</div>';}
function fullDetail(e){const x=e.context||{},m=e.resultMeta||{},c=e.coordinates;return detailPhotos(e)+'<div class="facts">'+(e.category?'<div>分類：'+esc(e.category)+'</div>':"")+(e.summary?'<div>'+esc(e.summary)+'</div>':"")+((e.provider||e.model)?'<div>使ったAI：'+esc([providerLabel(e.provider),e.model].filter(Boolean).join(" · "))+'</div>':"")+(x.observedDate?'<div>撮った日：'+esc(x.observedDate)+'</div>':"")+(x.size?'<div>大きさ：'+esc(x.size)+'</div>':"")+(x.location?'<div>撮った場所：'+esc(x.location)+'</div>':"")+(c?'<div>位置：'+esc(c.latitude)+'、'+esc(c.longitude)+'（おおまかな値）</div>':"")+(m.strictMode?'<div>まちがい防止：学名を図鑑データで自動チェック</div>':"")+(m.taxonomyChecked?'<div>学名を図鑑データで確認済み'+(m.rejectedCandidates?' · 除いた候補 '+esc(m.rejectedCandidates)+'件':"")+'</div>':"")+(m.plantnetUsed?'<div>植物の候補は <a href="https://plantnet.org/" target="_blank" rel="noopener noreferrer">Pl@ntNet recognition API</a> によるもの</div>':"")+'</div><ol>'+(e.candidates||[]).map(c=>fullCandidate(c,e.category)).join("")+'</ol>'}async function enrich(){const records=await all(),byId=new Map(records.map(e=>[String(e.id),e]));document.querySelectorAll(".entry").forEach(node=>{const e=byId.get(node.dataset.id);if(e)node.querySelector(".detail").innerHTML='<summary>調べた内容を見る</summary>'+fullDetail(e)});document.querySelectorAll('.meter span[data-width]').forEach(bar=>{bar.style.width=bar.dataset.width+'%'});document.querySelectorAll(".detail-photo").forEach(b=>b.onclick=()=>{$("large").src=b.dataset.src;$("lightbox").showModal()})}setTimeout(()=>enrich().catch(e=>console.error("記録の詳細を組み立てられませんでした", e)),0);
/* 撮影画面と同じく、棚は候補ごとにその候補の中へ置く。記録から読み返すときも
   「どの候補の広告か」を位置で決められる。開いたときに初めて叩くのは変えない。
   予算は1回の開閉につき通しで6回・1棚2回 (撮影画面と同じ)。集めた品は棚をまたいで
   覚えるので、どの候補でも当たる一般書が候補の数だけ並ぶことはない。 */
async function loadProducts(record,shells){
  const candidates=record.candidates||[];
  const budget=productBudget();
  for(let i=0;i<shells.length;i++){
    const candidate=candidates[i];
    if(!candidate)continue;
    const name=displayName(candidate);
    /* 検索リンクは loadProductShelf が必ず添える (カードが出ても出なくても)。
       name は記録から取り直したもので、window.name ではない */
    await loadProductShelf(shells[i],{
      name,scientific:candidate.scientific_name||"",category:record.category||"",
      label:"Amazonで"+(name||"関連商品")+"の関連商品",
    },budget);
  }
}
/* 結果に納得できないときに、写真を足して調べ直す。
 *
 * 記録に残っているのは1枚目の縮小画像 (長辺960px) だけなので、足せるのは2枚まで
 * (サーバーの上限が3枚)。元の写真は全体像であることが多く、足すのは寄りの1枚に
 * なるので、順番は元→追加で送る。撮影画面で撮り足すときと同じ考え方。
 */
/* 旧い記録は thumbnail 1枚しか持っていない。読む側はここを通して差を吸収する */
function recordPhotos(record){
  const list=Array.isArray(record?.thumbnails)?record.thumbnails.filter(Boolean):[];
  if(list.length)return list;
  return record?.thumbnail?[record.thumbnail]:[];
}
const RERUN_MAX_PHOTOS=3;
function addRerunControls(){
  document.querySelectorAll(".entry").forEach(node=>{
    const detail=node.querySelector(".detail");
    if(!detail||detail.querySelector(".rerun-box"))return;
    const record=rerunRecords.get(node.dataset.id);
    const kept=recordPhotos(record);
    if(!kept.length)return;
    const maxExtra=Math.max(0,RERUN_MAX_PHOTOS-kept.length);
    const box=document.createElement("div");
    box.className="rerun-box";
    box.innerHTML='<div class="label">結果に納得できないときは</div>'
      +'<p>写真を足すと、決め手が増えて答えが変わることがあります。元の写真'+kept.length+'枚はそのまま使います（'+(maxExtra?'あと'+maxExtra+'枚まで足せます':'すでに'+RERUN_MAX_PHOTOS+'枚あるので、これ以上は足せません')+'）。</p>'
      +'<div class="rerun-previews"></div>'
      +(maxExtra?'<div class="rerun-actions">'
      +'<button class="btn rerun-camera" type="button">カメラで撮って足す</button>'
      +'<button class="btn rerun-library" type="button">写真を選んで足す</button>'
      +'<button class="btn rerun-go" type="button" hidden>足した写真で調べ直す</button></div>':'')
      +'<p class="rerun-message" hidden></p>';
    const camera=document.createElement("input");
    camera.type="file";camera.accept="image/*";camera.capture="environment";camera.hidden=true;
    const library=document.createElement("input");
    library.type="file";library.accept="image/*";library.multiple=true;library.hidden=true;
    box.append(camera,library);
    detail.append(box);

    const extras=[];let urls=[];
    const message=box.querySelector(".rerun-message");
    const say=text=>{message.textContent=text;message.hidden=!text};
    const paint=()=>{
      urls.forEach(URL.revokeObjectURL);
      urls=extras.map(file=>URL.createObjectURL(file));
      box.querySelector(".rerun-previews").innerHTML=urls
        .map((url,i)=>'<img src="'+url+'" alt="足した写真 '+(i+1)+'">').join("");
      box.querySelector(".rerun-go").hidden=!extras.length;
    };
    const add=files=>{
      const chosen=[...files].filter(file=>file.type.startsWith("image/"));
      if(!chosen.length){say("画像ファイルを選んでください。");return}
      const room=maxExtra-extras.length;
      if(room<=0){say(maxExtra?"あと足せる写真はありません。":"合わせて"+RERUN_MAX_PHOTOS+"枚までです。");return}
      extras.push(...chosen.slice(0,room));
      paint();
      say(chosen.length>room?"（合わせて"+RERUN_MAX_PHOTOS+"枚までなので"+room+"枚だけ足しました）":"");
    };
    camera.onchange=e=>{add(e.target.files);e.target.value=""};
    library.onchange=e=>{add(e.target.files);e.target.value=""};
    box.querySelector(".rerun-camera").onclick=()=>camera.click();
    box.querySelector(".rerun-library").onclick=()=>library.click();
    box.querySelector(".rerun-go").onclick=()=>
      reidentify(record,box.querySelector(".rerun-go"),message,extras);
  });
}
/* 調べ直しも後ろで走らせる。撮影画面と同じ理由 (Ollama で1分)。札と、足した写真を
   控えておき、画面を更新しても続きから受け取る。記録に元からある写真は
   IndexedDB にあるので預けない */
const RERUN_PENDING_KEY="species-pending-rerun";
function readRerunPending(){try{return JSON.parse(localStorage.getItem(RERUN_PENDING_KEY)||"null")}catch(e){return null}}
function writeRerunPending(v){try{v?localStorage.setItem(RERUN_PENDING_KEY,JSON.stringify(v)):localStorage.removeItem(RERUN_PENDING_KEY)}catch(e){}}

function rerunWorking(button,message,startedAt){
  const tick=()=>{
    const seconds=Math.max(0,Math.round((Date.now()-startedAt)/1000));
    if(button){button.disabled=true;button.textContent="調べ直しています…（"+seconds+"秒）"}
    message.textContent="この画面を閉じても、開き直せば続きから受け取れます。";message.hidden=false;
  };
  tick();
  return setInterval(tick,1000);
}

async function watchRerun(pending,button,message){
  const timer=rerunWorking(button,message,pending.startedAt||Date.now());
  const stop=()=>{clearInterval(timer);if(button){button.disabled=false;button.textContent="もう一度調べる"}};
  while(true){
    await new Promise(done=>setTimeout(done,1500));
    if(readRerunPending()?.job!==pending.job){clearInterval(timer);return}
    let payload;
    try{
      const response=await fetch("/identify/job/"+encodeURIComponent(pending.job));
      payload=await response.json();
      if(response.status===404)throw new Error(payload.detail||"この調べものは見つかりませんでした。");
    }catch(error){
      stop();writeRerunPending(null);
      message.textContent=error.message;message.hidden=false;return;
    }
    if(payload.status==="running")continue;
    stop();
    if(payload.status==="error"){
      writeRerunPending(null);
      message.textContent=typeof payload.detail==="string"?payload.detail:"調べられませんでした";
      message.hidden=false;return;
    }
    const source=rerunRecords.get(String(pending.recordId));
    if(!source){writeRerunPending(null);message.textContent="元の記録が見つかりませんでした。";message.hidden=false;return}
    const added=(pending.photos||[]).map(dataUrlToBlob).filter(Boolean);
    writeRerunPending(null);
    await saveRerun(source,payload.result,[...recordPhotos(source),...added]);
    location.reload();
    return;
  }
}

async function reidentify(record,button,message,extras=[]){
  /* 元の写真は保存していない。記録の縮小画像 (長辺960px) を送り直す。
     解像度が落ちているぶん、撮ったばかりの写真より不利になることがある */
  if(!recordPhotos(record).length){message.textContent="この記録には写真が残っていないため、調べ直せません。";message.hidden=false;return}
  const label=button.textContent;
  const startedAt=Date.now();
  button.disabled=true;button.textContent="調べ直しています…";message.hidden=true;
  try{
    const settings=await fetch("/api/settings").then(r=>r.ok?r.json():null);
    if(!settings)throw new Error("設定を読み込めませんでした");
    const fd=new FormData();
    /* 記録が持つ写真を先に、足したぶんをあとに。全体像→寄りの順になる */
    recordPhotos(record).forEach((blob,i)=>fd.append("files",blob,"photo-"+(i+1)+".jpg"));
    extras.forEach((file,i)=>fd.append("files",file,"added-"+(i+1)+".jpg"));
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
    fd.append("background","true");
    const response=await fetch("/identify",{method:"POST",body:fd});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||"調べられませんでした");
    const shrunk=[];
    for(const file of extras){try{const blob=await shrinkForHistory(file);if(blob)shrunk.push(await blobToDataUrl(blob))}catch(e){}}
    /* 札が返らない置き場では、返ってきたものが結果そのもの (main.py の BACKGROUND_JOBS) */
    if(!data.job){
      await saveRerun(record,data,[...recordPhotos(record),...(shrunk.map(dataUrlToBlob).filter(Boolean))]);
      location.reload();
      return;
    }
    const pending={job:data.job,recordId:record.id,startedAt,photos:shrunk};
    writeRerunPending(pending);
    watchRerun(pending,button,message);
    return;
  }catch(error){
    message.textContent=error.message;message.hidden=false;
    button.disabled=false;button.textContent=label;
  }
}
async function saveRerun(source,data,photos=[]){
  let listThumbnail=null;try{if(photos[0])listThumbnail=await shrinkForHistory(photos[0],LIST_MAX_EDGE)}catch(e){}
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
    context:source.context||{},coordinates:source.coordinates||null,
    thumbnail:photos[0]||source.thumbnail||null,thumbnails:photos,
    listThumbnail:listThumbnail||source.listThumbnail||null,
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
    /* 候補は fullCandidate が record.candidates の順に描く。並びで対応づける */
    const items=[...detail.querySelectorAll("li.candidate")];
    if(!items.length)return;
    const shells=items.map(item=>{
      const shell=document.createElement("div");
      shell.className="product-shell";
      item.append(shell);
      return shell;
    });
    const load=()=>{if(detail.open){loadProducts(record,shells);pullPhotosIfMissing(record,node)}};
    detail.addEventListener("toggle",load);
    load();  // すでに開いている記録には即座に出す
  });
}
const addAffiliateLinksOnce=addAffiliateLinks;let affiliateLinksAdded=false;addAffiliateLinks=async()=>{if(affiliateLinksAdded)return;affiliateLinksAdded=true;await addAffiliateLinksOnce()};setTimeout(()=>enrich().then(addAffiliateLinks).then(addRerunControls).then(resumeRerun).catch(e=>console.error("記録の詳細を組み立てられませんでした", e)),0);

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

/* 開き直したとき、走らせたままの調べ直しがあれば続きから受け取る。記録の一覧が
   組み上がったあとに呼ぶ (元の記録を rerunRecords から引くため) */
function resumeRerun(){
  const pending=readRerunPending();
  if(!pending?.job)return;
  const node=document.querySelector('.entry[data-id="'+CSS.escape(String(pending.recordId))+'"]');
  const button=node?.querySelector(".again")||null;
  const message=node?.querySelector(".again-message")||document.createElement("p");
  if(node)node.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"center"});
  watchRerun(pending,button,message);
}

/* 開いた記録の原寸がまだ手元になければ、ドライブから引いて描き直す。
   一覧を出すだけでは引かない (50件ぶん引くことになる) */
const pulledPhotos=new Set();
async function pullPhotosIfMissing(record,node){
  if(recordPhotos(record).length||!(record.drivePhotos||[]).length)return [];
  if(pulledPhotos.has(String(record.id))||typeof fetchRecordPhotos!=="function")return [];
  pulledPhotos.add(String(record.id));
  try{
    const photos=await fetchRecordPhotos(record);
    if(!photos.length)return [];
    record.thumbnails=photos;record.thumbnail=photos[0];
    const detail=node.querySelector(".detail");
    if(detail){const open=detail.open;detail.innerHTML='<summary>調べた内容を見る</summary>'+fullDetail(record);detail.open=open;
      detail.querySelectorAll(".detail-photo").forEach(b=>b.onclick=()=>{$("large").src=b.dataset.src;$("lightbox").showModal()})}
    return photos;
  }catch(error){console.info("原寸を引けませんでした",error)}
  return [];
}
