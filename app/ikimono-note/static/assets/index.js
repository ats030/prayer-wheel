function animalReferenceHtml(c,category){const ref=animalReference(c,category);return ref?'<div class="animal-references"><span>オス・メスの違いを調べる資料（外部サイト）</span><a target="_blank" rel="noopener noreferrer" href="'+esc(ref.url)+'">'+esc(ref.label)+' ↗</a></div>':""}
const $=id=>document.getElementById(id);let plantnetReady=false;let affiliate=null;let provider="local";let providerName="Ollama";let selected=[];let gps=null;const drop=$("drop"),status=$("status"),previews=$("previews"),identify=$("identify");
async function loadSettings(){try{const r=await fetch("/api/settings");const data=await r.json();window.speciesPublicMode=Boolean(data.public_mode);if(window.speciesPublicMode){const saved=JSON.parse(localStorage.getItem("species-public-settings")||"{}");if(saved.provider&&(saved.provider!=="local"||data.available_models.local.length))data.provider=saved.provider;if(saved.models)data.models={...data.models,...saved.models}}provider=data.provider;providerLabel(provider);const model=data.models[provider];window.speciesRuntimeModel=model;plantnetReady=Boolean(data.api_key_configured.plantnet||(window.speciesPublicMode&&readApiKey("plantnet")));affiliate=data.affiliate;document.getElementById("affiliateDisclosure").classList.toggle("hidden",!affiliate.enabled);document.getElementById("plantnetOption").classList.toggle("hidden",!plantnetReady);$("providerStatus").textContent=providerName+" · "+model+(provider==="local"?" · 写真は外部送信しません":" · 写真は保存しません")}catch(e){showStatus("設定を読み込めませんでした。",true)}}
const MAX_PHOTOS=3;let previewUrls=[];
function renderPreviews(){previewUrls.forEach(URL.revokeObjectURL);previewUrls=selected.map(file=>URL.createObjectURL(file));document.body.classList.add("has-selection");previews.innerHTML=previewUrls.map((url,index)=>"<img class=\"preview\" src=\""+url+"\" alt=\"調べる写真 "+(index+1)+"\">").join("");$("previewEmpty").classList.add("hidden");identify.classList.remove("hidden");$("captureTitle").textContent=selected.length+"枚の写真を選択中"}
function setFiles(files){const chosen=[...files].filter(file=>file.type.startsWith("image/"));if(!chosen.length){showStatus("画像ファイルを選んでください。",true);return}if(chosen.length>MAX_PHOTOS){showStatus("写真は最大"+MAX_PHOTOS+"枚です。",true);return}selected=chosen;gps=null;renderPreviews();showStatus("写真の情報と現在地を確認しています。",false,true);readPhotoMetadata(chosen);requestCurrentLocation(true)}
/* 足すときは、いま選んでいる写真を残す。置き換えると、最初に撮った全体像が消えて
   候補が振り出しに戻る。「もっと確かめたいこと」を読んで撮り足す人が欲しいのは、
   全体像に寄りの1枚を加えた組であって、寄りの1枚だけではない。
   撮った日・場所はすでに1枚目から読み終わっているので、ここでは読み直さない。 */
function addFiles(files){
  const chosen=[...files].filter(file=>file.type.startsWith("image/"));
  if(!chosen.length){showStatus("画像ファイルを選んでください。",true);return}
  if(!selected.length){setFiles(chosen);return}
  const room=MAX_PHOTOS-selected.length;
  if(room<=0){showStatus("写真は"+MAX_PHOTOS+"枚までです。撮り直すときは「写真を選ぶ」から選びなおしてください。",true);return}
  const added=chosen.slice(0,room);
  selected=[...selected,...added];
  renderPreviews();
  const overflow=chosen.length>room?"（"+MAX_PHOTOS+"枚までなので"+added.length+"枚だけ足しました）":"";
  showStatus("写真を足して"+selected.length+"枚になりました"+overflow+"。もう一度「名前を調べる」を押すと、足した写真も合わせて調べます。");
  identify.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"center"});
}
function applyPhotoMetadata(data){const found=[];if(data.observed_date&&!$("observedDate").value){$("observedDate").value=data.observed_date;found.push("撮った日")}if(data.location&&!$("location").value){$("location").value=data.location;found.push("撮った場所");gps={latitude:data.latitude,longitude:data.longitude,accuracy:11,source:"exif"};$("gpsStatus").textContent="写真に残っていた位置を、約11m単位のおおまかな値にして入れました。撮った場所としてAIへ送られます。"}if(found.length){$("location").closest("details").open=true;showStatus("写真から"+found.join("・")+"を入れました。内容は直せます。")}else{showStatus("撮った場所や大きさを足すと、候補をしぼりやすくなります。")}}
async function readPhotoMetadata(files){const fd=new FormData();files.forEach(file=>fd.append("files",file));try{const r=await fetch("/api/photo-metadata",{method:"POST",body:fd});if(!r.ok)throw new Error();const data=await r.json();if(selected[0]===files[0])applyPhotoMetadata(data)}catch(e){if(selected[0]===files[0])showStatus("写真を選びました。撮った日や場所の情報は読み取れませんでした。")}}
function showStatus(text,error=false,busy=false){status.className='status'+(error?' error':'');status.innerHTML=(busy?'<span class="spinner"></span>':'')+text}
/* 「選びなおす」と「足す」で入力欄を分ける。1つの入力を旗で切り替えると、
   #library はドロップ領域の <label> の中にあるため .click() が label まで
   バブルし、旗を戻す側の処理と競合する。入力を分ければその競合ごと消える */
$('libraryBtn').onclick=()=> $('library').click();$('cameraBtn').onclick=()=> $('camera').click();$("library").onchange=e=>{setFiles(e.target.files);e.target.value=""};$("libraryAdd").onchange=e=>{addFiles(e.target.files);e.target.value=""};$("camera").onchange=e=>{addFiles(e.target.files);e.target.value=""};
['dragenter','dragover'].forEach(n=>drop.addEventListener(n,e=>{e.preventDefault();drop.classList.add('drag')}));['dragleave','drop'].forEach(n=>drop.addEventListener(n,e=>{e.preventDefault();drop.classList.remove('drag')}));drop.addEventListener("drop",e=>setFiles(e.dataTransfer.files));
function requestCurrentLocation(automatic=false){if(!navigator.geolocation){$("gpsStatus").textContent="このブラウザでは現在地を取得できません。位置情報なしでも使えます。";return}$("gpsButton").disabled=true;$("gpsStatus").textContent=automatic?"写真を選んだので、現在地を確認しています…":"現在地を確認しなおしています…";navigator.geolocation.getCurrentPosition(position=>{if(gps?.source!=="exif"){gps={latitude:position.coords.latitude,longitude:position.coords.longitude,accuracy:position.coords.accuracy,source:"current"};$("gpsStatus").textContent=`現在地を取得しました（誤差 約${Math.round(gps.accuracy)}m）。AIへは送らず、調べたあとにおおまかな位置にしてこの端末の記録だけに保存します。`}$("gpsButton").disabled=false},error=>{if(gps?.source!=="exif")$("gpsStatus").textContent=error.code===1?"位置情報が許可されませんでした。位置情報なしでも使えます。":"現在地を取得できませんでした。位置情報なしでも使えます。";$("gpsButton").disabled=false},{enableHighAccuracy:true,timeout:10000,maximumAge:0})}
$("gpsButton").onclick=()=>requestCurrentLocation(false);
function esc(v){const d=document.createElement('div');d.textContent=v??'';return d.innerHTML}
function agreementBadge(c){if(c.evidence_status==="corroborated")return "<span class=\"taxonomy verified\">2つの調べ方で同じ答え</span>";if(c.evidence_status==="specialist_only")return "<span class=\"taxonomy\">植物のサービスだけが答えた</span>";if(c.evidence_status==="taxonomy_only")return "<span class=\"taxonomy\">名前は図鑑にあります</span>";if(c.evidence_status==="uncertain")return "<span class=\"taxonomy\">決め手なし · 名前は図鑑にあります</span>";return ""}
function meterBar(c){/* 幅は style 属性ではなく CSSOM で入れる (CSP: style-src 'self') */return "</div><div class=\"meter\"><span data-width=\""+Number(c.confidence||0)+"\"></span></div>"}
function applyMeters(){document.querySelectorAll(".meter span[data-width]").forEach(bar=>{bar.style.width=Math.max(0,Math.min(100,Number(bar.dataset.width)||0))+"%"})}
/* 同じ c.confidence に2つの名前を付けていた (「あてはまり度」と「写真からのAI推測 最大」)。
   利用者には別の指標に見える。呼び方は1つにし、決め手が足りないことは別に伝える。 */
function confidenceView(c){
  const weak=["taxonomy_only","uncertain"].includes(c.evidence_status);
  return '<div class="confidence">あてはまり度 '+c.confidence+"%"
       +(weak?'<span class="muted">（決め手は足りていません）</span>':"")+"</div>"+meterBar(c);
}
function taxonRankLabel(rank){if(["species","subspecies","variety","form"].includes(rank))return "種の候補";if(rank==="genus")return "属（近いなかま）の候補";if(rank==="family")return "科（大きなグループ）の候補";return ""}
function taxonomyBadge(c){const rank=taxonRankLabel(c.taxon_rank);if(c.taxonomy_status==="verified")return "<span class=\"taxonomy verified\">"+(rank?rank+" · ":"")+"図鑑にある名前です</span>";if(c.taxonomy_status==="unverified")return "<span class=\"taxonomy\">図鑑で名前を確認できず</span>";if(c.taxonomy_status==="unavailable")return "<span class=\"taxonomy\">図鑑データに接続できず</span>";return ""}
/* 種の保存法の指定は、事実だけを出して環境省へ送る。規制の中身は指定の種類で違い
   (特定第二種は販売・頒布目的の捕獲等だけが規制)、ここで要約すると外す。
   一致しなかった候補には何も出さない。「指定なし」と読まれるため — 都道府県の条例が
   独自に指定している種があり、亜種で指定されているものは種名では当たらない。 */
function protectedSpeciesHtml(c){
  const p=c.protected_species;
  if(!p||!p.category)return "";
  const label=esc(p.category)+(p.subtype?"（"+esc(p.subtype)+"）":"");
  return '<div class="protected"><strong>種の保存法の'+label+'です</strong>'
    +'<p>規制の内容は指定の種類で違います。この生きものにさわる・持ち帰る前に、環境省の説明で確かめてください。</p>'
    +'<p class="protected-note">環境省の一覧（'+esc(p.as_of)+'版）の学名と一致しました。候補そのものが違っていることはあります。</p>'
    +'<a target="_blank" rel="noopener noreferrer" href="https://www.env.go.jp/nature/kisho/domestic/list.html">環境省 国内希少野生動植物種一覧 ↗</a></div>';
}
function sexHtml(c,category){if(category!=="動物")return "";const sex=["オス","メス"].includes(c.sex)?c.sex:"わかりません";const evidence=sex!=="わかりません"&&c.sex_evidence?.length?'<ul class="sex-evidence">'+c.sex_evidence.map(item=>'<li>'+esc(item)+'</li>').join("")+'</ul>':'<p>写真だけでは、この生きもののオス・メスの違いを確認できません。</p>';return '<div class="sex-result"><strong>オス・メスの推測：'+sex+'</strong><p>AIが写真から推測したものです。資料や実物で確かめてください。</p>'+evidence+'</div>'}
function affiliateProductLink(c,category){if(!affiliate||!affiliate.enabled)return "";const name=noJapaneseName(c.common_name_ja)?c.scientific_name:c.common_name_ja;const query=name+" "+category;return `<div class="product-shell amazon-products" data-query="${encodeURIComponent(query)}"><a class="product-fallback" href="/affiliate/click?q=${encodeURIComponent(query)}" target="_blank" rel="sponsored noopener noreferrer">広告 · Amazonで関連商品を探す ↗</a></div>`}
/* 広告は第一候補にひもづける。巡回させると、確からしさの低い2番目3番目の候補で
   商品を引くことがあり、結果と広告の関係が分かりにくくなる */
function topCandidateAffiliateLink(candidates,category){return candidates.length?affiliateProductLink(candidates[0],category):""}
function productCard(product){return `<a class="product-card" href="${esc(product.url)}" target="_blank" rel="sponsored noopener noreferrer" aria-label="広告: ${esc(product.title)}"><img class="product-image" src="${esc(product.image)}" alt="" loading="lazy" referrerpolicy="no-referrer"><span class="product-title">${esc(product.title)}</span></a>`}
async function loadAmazonProducts(){if(!affiliate?.product_enabled)return;await Promise.all([...document.querySelectorAll(".amazon-products")].map(async shell=>{try{const r=await fetch("/api/amazon/products?q="+shell.dataset.query);if(!r.ok)return;const data=await r.json();if(!Array.isArray(data.products)||!data.products.length)return;shell.innerHTML=`<div class="affiliate-label">広告 · Amazonの関連商品</div><div class="product-grid">${data.products.map(productCard).join("")}</div>`;shell.querySelectorAll(".product-card").forEach(link=>link.onclick=()=>fetch("/api/affiliate/click",{method:"POST",keepalive:true}).catch(()=>{}))}catch(e){}}))}
function safetyHtml(){const location=gps?`取得済み（誤差 約${Math.round(gps.accuracy)}m）`:"まだ取得していません";return `<aside class="safety-card" id="safetyCard"><h3>見つけた生きものの扱い</h3><p class="safety-lead">この結果は「たぶんこれ」という候補です。食べる・さわる・持ち帰るの判断には使えません。小さなお子さんが使うときは、大人といっしょに読んでください。</p><div class="safety-grid"><div class="safety-item"><span class="safety-status">食べられるか：判定しません</span><p>写真だけでは、よく似た毒のある種、毒のある部分、育ち具合を見分けられません。この結果をもとに食べないでください。</p><a href="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/yuudoku/index.html" target="_blank" rel="noopener noreferrer">厚生労働省の注意情報 ↗</a></div><div class="safety-item"><span class="safety-status">さわってよいか：判定しません</span><p>かぶれる植物、刺す・かむ生きものは、写真では見分けきれません。素手でさわらず、離れて観察してください。生きものを弱らせない距離を保ちましょう。</p></div><div class="safety-item"><span class="safety-status">持ち帰ってよいか：確認が必要</span><p>現在地：${location}。場所がわかっても、その土地の持ち主の許可、保護区域、自治体のきまり、保護されている種かどうかまでは確認できません。すべて確認できるまで採らないでください。</p><a href="https://www.env.go.jp/park/about/protect/index.html" target="_blank" rel="noopener noreferrer">環境省の採取規制を確認 ↗</a></div></div></aside>`}
function plantnetCreditHtml(data){
  /* Pl@ntNet の無料枠は "based on the Pl@ntNet recognition API" の明示を求めている */
  if(!data.plantnet_used)return "";
  return '<p class="source-credit">植物の候補は <a href="https://plantnet.org/" target="_blank" rel="noopener noreferrer">Pl@ntNet recognition API</a> によるものです。</p>';
}
function affiliateHtml(){if(!affiliate||!affiliate.enabled)return "";return "<aside class=\"affiliate-card\" id=\"affiliateCard\"><div class=\"affiliate-label\">関連商品の広告リンクを表示しています</div><div class=\"affiliate-disclosure\">購入されると運営者に紹介料が入る場合があります。</div></aside>"}
/* 見分け方は、確信の度合いによらず出す。
   実測で6割は種を外しており (Top-1 40%)、そのうち多くは属まで合っている。
   「アオダイショウです」と言い切られて違うより、「シマヘビとはここで見分ける」が
   添えてあるほうが、実物と見くらべられる。以前は evidence_status が uncertain の
   ときだけ出しており、しかも traits があると手前で返って一度も表示されなかった。 */
function evidenceHtml(c){
  const observations=c.traits||[],points=c.distinguishing_features||[],gaps=c.evidence_gaps||[];
  const unsure=["taxonomy_only","uncertain"].includes(c.evidence_status);
  return (observations.length?(unsure?'<div class="uncertainty">AIが写真から見つけた特徴（未確認）</div>':'')
           +'<ul>'+observations.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>':'')
       +(points.length?'<div class="uncertainty">似ている種との見分け方</div><ul>'
           +points.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>':'')
       +(gaps.length?'<div class="uncertainty">決め手が足りない理由：'+gaps.map(esc).join('・')+'</div>':'');
}
/* 質で弾いたときの detail は {message, problems}。文字列とオブジェクトの両方が来る */
function errorText(detail){if(!detail)return "調べられませんでした";if(typeof detail==="string")return detail;const notes=(detail.problems||[]).map(p=>p.message).join(" ");return (detail.message||"調べられませんでした")+(notes?" "+notes:"")}
function photoNotes(data){const notes=(data.photo_notes||[]);if(!notes.length)return "";return '<div class="photo-notes"><strong>次に撮るときは</strong><ul>'+notes.map(n=>"<li>"+esc(n.message)+"</li>").join("")+"</ul></div>"}
function render(data){if(!data.candidates.length){$('results').className='';$("results").innerHTML=photoNotes(data)+`<div class="placeholder">図鑑データで確認できる候補が見つかりませんでした。全体・もよう・特徴のある部分を、別の角度から撮ってみてください。</div>${safetyHtml()}`;return}$('results').className='';$('results').innerHTML=photoNotes(data)+'<p class="summary"><strong>'+esc(data.category)+'</strong> · '+esc(data.summary)+'</p>' +data.candidates.map((c,i)=>'<article class="candidate"><div class="name-row"><div><div class="name">'+(i+1)+'. '+esc(c.common_name_ja)+'</div><div class="latin">'+esc(c.scientific_name)+'</div>'+taxonomyBadge(c)+agreementBadge(c)+'</div>'+confidenceView(c)+protectedSpeciesHtml(c)+evidenceHtml(c)+sexHtml(c,data.category)+(c.uncertainty?'<div class="uncertainty">もっと確かめたいこと：'+esc(c.uncertainty)+'</div>':'')+'<div class="sources"><a target="_blank" rel="noopener" href="'+sourceUrl(noJapaneseName(c.common_name_ja)?c.scientific_name:c.common_name_ja)+'">図鑑を検索 ↗</a>'+(wikipediaUrl(c)?'<a target="_blank" rel="noopener noreferrer" href="'+esc(wikipediaUrl(c))+'">Wikipedia ↗</a>':'')+(c.taxonomy_url?'<a target="_blank" rel="noopener" href="'+esc(c.taxonomy_url)+'">iNaturalist ↗</a>':'')+'</div>'+animalReferenceHtml(c,data.category)+'</article>').join('')+safetyHtml()+plantnetCreditHtml(data)+topCandidateAffiliateLink(data.candidates,data.category)+affiliateHtml();applyMeters();if(document.getElementById('affiliateCard'))fetch('/api/affiliate/impression',{method:'POST'}).catch(()=>{});loadAmazonProducts()}
function historyDb(){return new Promise((resolve,reject)=>{if(!("indexedDB" in window)){reject(new Error("このブラウザでは、調べた記録を保存できません"));return}const request=indexedDB.open("species-history",1);request.onupgradeneeded=()=>{const db=request.result;if(!db.objectStoreNames.contains("entries"))db.createObjectStore("entries",{keyPath:"id"})};request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)})}
function requestValue(request){return new Promise((resolve,reject)=>{request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)})}
function transactionDone(transaction){return new Promise((resolve,reject)=>{transaction.oncomplete=resolve;transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error)})}
async function historyThumbnail(file){if(!file)return null;const bitmap=await createImageBitmap(file);const scale=Math.min(1,960/Math.max(bitmap.width,bitmap.height));const canvas=document.createElement("canvas");canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));canvas.getContext("2d").drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();return new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",.78))}
async function saveHistory(data){const db=await historyDb();let thumbnail=null;try{thumbnail=await historyThumbnail(selected[0])}catch(e){}const metadata=data.photo_metadata||{};const coordinates=gps?{latitude:Number(gps.latitude.toFixed(4)),longitude:Number(gps.longitude.toFixed(4))}:metadata.latitude!=null?{latitude:metadata.latitude,longitude:metadata.longitude}:null;const record={id:(crypto.randomUUID?.()||Date.now()+"-"+Math.random()),createdAt:new Date().toISOString(),category:data.category,summary:data.summary,candidates:data.candidates,provider:providerName,model:data.model||"",resultMeta:{strictMode:Boolean(data.strict_mode),taxonomyChecked:Boolean(data.taxonomy_checked),rejectedCandidates:Number(data.rejected_candidates||0),plantnetUsed:Boolean(data.plantnet_used)},context:{location:$("location").value,observedDate:$("observedDate").value,size:$("size").value},coordinates,thumbnail};let tx=db.transaction("entries","readwrite");tx.objectStore("entries").put(record);await transactionDone(tx);tx=db.transaction("entries","readonly");const all=await requestValue(tx.objectStore("entries").getAll());await transactionDone(tx);const excess=all.sort((a,b)=>b.createdAt.localeCompare(a.createdAt)).slice(50);if(excess.length){tx=db.transaction("entries","readwrite");excess.forEach(item=>tx.objectStore("entries").delete(item.id));await transactionDone(tx)}db.close();scheduleAutoBackup()}
identify.onclick=async()=>{if(!selected.length)return;identify.disabled=true;showStatus(providerName+"が写真を見ています。少しお待ちください。",false,true);$('results').className='placeholder';$('results').textContent='形・色・もようを確認中…';const fd=new FormData();selected.forEach(file=>fd.append("files",file));fd.append("location",$("location").value);fd.append("observed_date",$("observedDate").value);fd.append("size",$("size").value);fd.append("use_plantnet",document.getElementById("usePlantnet").checked);if(window.speciesPublicMode){const saved=JSON.parse(localStorage.getItem("species-public-settings")||"{}");fd.append("request_provider",provider);fd.append("request_model",saved.models?.[provider]||window.speciesRuntimeModel||"");fd.append("request_api_key",readApiKey(provider));fd.append("request_plantnet_key",readApiKey("plantnet"))}try{const r=await fetch('/identify',{method:'POST',body:fd});const data=await r.json();if(!r.ok)throw new Error(errorText(data.detail));render(data);showStatus('似ている生きものを表示しました。実物と見くらべてください。');saveHistory(data).catch(error=>showStatus("候補は表示できましたが、この端末の記録には保存できませんでした。 "+error.message,true))}catch(e){$('results').innerHTML='<div class="placeholder">結果を取得できませんでした。</div>';showStatus(e.message,true)}finally{identify.disabled=false}};
loadSettings();
const renderIdentification=render;
/* 「もっと確かめたいこと」を読んだその場から撮り足せるようにする。以前は
   evidence_status が taxonomy_only / uncertain の候補があるときしか出しておらず、
   決め手はあるが確かめたいことが残っている候補では、書いてある「次はここを見る」を
   写真にする手段が画面になかった。uncertainty や evidence_gaps が1つでもあれば出す */
function shootingGuide(data){
  const candidates=data.candidates||[];
  const weak=candidate=>["taxonomy_only","uncertain"].includes(candidate.evidence_status);
  const points=[];
  /* 決め手のない候補の確かめどころを先に並べる。5件で切るので、順番が中身を決める */
  [...candidates].sort((a,b)=>Number(weak(b))-Number(weak(a))).forEach(candidate=>{
    const name=candidate.common_name_ja||candidate.scientific_name||"候補";
    if(candidate.uncertainty)points.push(name+"："+candidate.uncertainty);
    (candidate.evidence_gaps||[]).forEach(gap=>points.push(name+"："+gap));
  });
  if(!points.length&&candidates.length&&!candidates.some(weak))return "";
  const unique=[...new Set(points)].slice(0,5);
  if(!unique.length)unique.push("全体が写った写真","特徴のある部分を、表と裏から近づいて撮った写真","定規や硬貨と並べて大きさがわかる写真");
  return '<aside class="candidate shooting-guide" id="shootingGuide"><div class="name">もう1枚撮ると、はっきりします</div><div class="uncertainty">もっと確かめたいことが写った写真を足してください。</div><ul>'
    +unique.map(point=>'<li>'+esc(point)+'</li>').join("")
    +'</ul><div class="actions"><button class="btn primary" id="addPhotoCamera" type="button">カメラで撮って足す</button><button class="btn" id="addPhotoLibrary" type="button">写真を選んで足す</button></div>'
    +'<p class="guide-note">いま選んでいる写真はそのまま残ります（合わせて'+MAX_PHOTOS+'枚まで）。足したあと、もう一度「名前を調べる」を押してください。</p></aside>';
}
render=function(data){
  renderIdentification(data);
  const guide=shootingGuide(data);
  if(!guide)return;
  /* 候補が1件も残らなかったときは要約がない。撮り直しを促す一文の直後に置く
     (安全カードの後ろに回すと、案内とボタンが画面の外へ出てしまう) */
  const anchor=$("results").querySelector(".summary")||$("results").querySelector(".placeholder");
  if(anchor)anchor.insertAdjacentHTML("afterend",guide);
  else $("results").insertAdjacentHTML("beforeend",guide);
  $("addPhotoCamera").onclick=()=>$("camera").click();
  $("addPhotoLibrary").onclick=()=>$("libraryAdd").click();
};
