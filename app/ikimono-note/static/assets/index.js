function animalReferenceHtml(c,category){const ref=animalReference(c,category);return ref?'<div class="animal-references"><span>オス・メスの違いを調べる資料（外部サイト）</span><a target="_blank" rel="noopener noreferrer" href="'+esc(ref.url)+'">'+esc(ref.label)+' ↗</a></div>':""}
const $=id=>document.getElementById(id);let plantnetReady=false;let affiliate=null;let provider="local";let providerName="Ollama";let selected=[];let gps=null;const drop=$("drop"),status=$("status"),previews=$("previews"),identify=$("identify");
/* お試し枠のことは、使い切る前に言う。1日3回だと知らずに2回使い、3回目で
   初めて壁に当たるのは不親切。続ける道 (自分のキーを入れる) も一緒に出す。
   ログインの導線も、未ログインの人にだけ出す。記録を端末をまたいで残したい人が、
   入り口を見つけられないままになるため */
function showTrialNote(data){
  const trial=data.trial;
  const note=$("trialNote");
  if(!note)return;
  const hasKey=Boolean(readApiKey("gemini")||readApiKey("openai")||readApiKey("anthropic"));
  if(!trial||hasKey){note.classList.add("hidden");return}
  note.classList.remove("hidden");
  note.innerHTML="このまま1日"+trial.per_day+"回まで試せます。続けて使うには、"
    +'<a href="/settings">設定</a>でご自身のAPIキーを登録してください（Geminiには無料枠があります）。';
}
async function showSignIn(){
  const link=$("signInLink");
  if(!link)return;
  try{
    const me=await fetch("/api/me").then(r=>r.ok?r.json():null);
    link.classList.toggle("hidden",!(me&&me.available&&!me.signed_in));
  }catch(e){/* 出せなくても使える */}
}
async function loadSettings(){try{const r=await fetch("/api/settings");const data=await r.json();window.speciesPublicMode=Boolean(data.public_mode);if(window.speciesPublicMode){const saved=JSON.parse(localStorage.getItem("species-public-settings")||"{}");if(saved.provider&&(saved.provider!=="local"||data.available_models.local.length))data.provider=saved.provider;if(saved.models)data.models={...data.models,...saved.models}}provider=data.provider;providerName=providerLabel(provider);let model=data.models[provider];
/* 自分のキーを持たない人は、運営者のお試し枠で走る。その場合に動くのはこちらが決めた
   プロバイダーとモデルなので、選択中のものを出したままだと写真の行き先を偽ることになる */
window.speciesTrial=data.trial||null;
if(window.speciesTrial&&!readApiKey(window.speciesTrial.provider)&&!readApiKey(provider)){
  provider=window.speciesTrial.provider;providerName=providerLabel(provider);model=window.speciesTrial.model;
}
window.speciesRuntimeModel=model;
  showTrialNote(data);plantnetReady=Boolean(data.api_key_configured.plantnet||(window.speciesPublicMode&&readApiKey("plantnet")));affiliate=data.affiliate;document.getElementById("affiliateDisclosure").classList.toggle("hidden",!affiliate.enabled);document.getElementById("plantnetOption").classList.toggle("hidden",!plantnetReady);$("providerStatus").textContent=providerName+" · "+model+(provider==="local"?" · 写真は外部送信しません":" · 写真は保存しません")}catch(e){showStatus("設定を読み込めませんでした。",true)}}
const MAX_PHOTOS=3;let previewUrls=[];
function renderPreviews(){previewUrls.forEach(URL.revokeObjectURL);previewUrls=selected.map(file=>URL.createObjectURL(file));document.body.classList.add("has-selection");/* 枚数で列を変える。3列固定だと、1枚のときも横幅の3分の1しか使わない。 携帯では110pxほどになり、ピントや被写体の位置を確かめられない */previews.className="previews count-"+selected.length;previews.innerHTML=previewUrls.map((url,index)=>'<div class="preview-item"><img class="preview" src="'+url+'" alt="調べる写真 '+(index+1)+'"><button class="btn preview-remove" type="button" data-index="'+index+'">この写真を外す</button></div>').join("");previews.querySelectorAll(".preview-remove").forEach(button=>button.onclick=()=>removeSelectedPhoto(Number(button.dataset.index)));$("previewEmpty").classList.add("hidden");identify.classList.remove("hidden");$("captureTitle").textContent=selected.length+"枚の写真を選択中"}
function removeSelectedPhoto(index){if(selected.length<=1){showStatus("調べる写真は1枚以上必要です。",true);return}selected.splice(index,1);renderPreviews();showStatus("写真を1枚外して"+selected.length+"枚になりました。")}
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
/* 広告は候補ごとに、その候補のブロックの中へ置く。以前は棚を1つだけ置いて第一候補に
   ひもづけていた。さらに前は1つの棚が候補間を巡回しており、どの候補の広告なのか
   読み手に分からなかった。候補の中に入れれば、帰属は位置で決まる。
   ただし決め手のない候補にも広告が付くことになる。ラベルに候補名を入れて、
   何に対する広告なのかを言い切る。 */
function affiliateProductLink(c,category){
  if(!affiliate||!affiliate.enabled)return "";
  const name=noJapaneseName(c.common_name_ja)?c.scientific_name:c.common_name_ja;
  const query=name;   /* 分類は足さない (products.js の productSearchLink と同じ理由) */
  /* 商品APIを待たずに検索リンクは出しておく。APIが無効・不調のときはこれが残り、
     返ってきたらカードと並べて置き直す (loadProductShelf) */
  return '<div class="product-shell amazon-products"'
    +' data-name="'+esc(name)+'" data-scientific="'+esc(c.scientific_name||"")+'"'
    +' data-category="'+esc(category||"")+'">'
    +'<a class="product-fallback" href="/affiliate/click?q='+encodeURIComponent(query)+'"'
    +' target="_blank" rel="sponsored noopener noreferrer">広告 · Amazonで'+esc(name)+'の関連商品を探す ↗</a></div>';
}
/* 棚を順に埋める。まとめて投げると、候補3件ぶんの商品APIが同時に飛ぶ。
   予算は棚をまたいだ通しで持ち、上の候補から先に使う (下の候補ほど確からしさが低い) */
async function loadAmazonProducts(){
  if(!affiliate?.product_enabled)return;
  const budget=productBudget();
  for(const shell of document.querySelectorAll(".amazon-products")){
    await loadProductShelf(shell,{
      name:shell.dataset.name,scientific:shell.dataset.scientific,
      category:shell.dataset.category,label:"Amazonで"+shell.dataset.name+"の関連商品",
    },budget);
  }
}
function safetyHtml(){const location=gps?`取得済み（誤差 約${Math.round(gps.accuracy)}m）`:"まだ取得していません";return `<aside class="safety-card" id="safetyCard"><h3>見つけた生きものの扱い</h3><p class="safety-lead">この結果は「たぶんこれ」という候補です。食べる・さわる・持ち帰るの判断には使えません。小さなお子さんが使うときは、大人といっしょに読んでください。</p><div class="safety-grid"><div class="safety-item"><span class="safety-status">食べられるか：判定しません</span><p>写真だけでは、よく似た毒のある種、毒のある部分、育ち具合を見分けられません。この結果をもとに食べないでください。</p><a href="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/yuudoku/index.html" target="_blank" rel="noopener noreferrer">厚生労働省の注意情報 ↗</a></div><div class="safety-item"><span class="safety-status">さわってよいか：判定しません</span><p>かぶれる植物、刺す・かむ生きものは、写真では見分けきれません。素手でさわらず、離れて観察してください。生きものを弱らせない距離を保ちましょう。</p></div><div class="safety-item"><span class="safety-status">持ち帰ってよいか：確認が必要</span><p>現在地：${location}。場所がわかっても、その土地の持ち主の許可、保護区域、自治体のきまり、保護されている種かどうかまでは確認できません。すべて確認できるまで採らないでください。</p><a href="https://www.env.go.jp/park/about/protect/index.html" target="_blank" rel="noopener noreferrer">環境省の採取規制を確認 ↗</a></div></div></aside>`}
function plantnetCreditHtml(data){
  /* Pl@ntNet の無料枠は "based on the Pl@ntNet recognition API" の明示を求めている */
  if(!data.plantnet_used)return "";
  return '<p class="source-credit">植物の候補は <a href="https://plantnet.org/" target="_blank" rel="noopener noreferrer">Pl@ntNet recognition API</a> によるものです。</p>';
}
function affiliateHtml(){if(!affiliate||!affiliate.enabled)return "";return "<aside class=\"affiliate-card\" id=\"affiliateCard\"><div class=\"affiliate-label\">関連商品の広告リンクを表示しています</div><div class=\"affiliate-disclosure\">購入されると運営者に紹介料が入る場合があります。</div></aside>"}
/* 見分け方は、確信の度合いによらず出す。
   実測で7割は種を外しており (Top-1 31.4%、100枚3回の平均)、そのうち多くは
   属まで合っている (属 52.6%、科以上 91.9%)。
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
function render(data){if(!data.candidates.length){$('results').className='';$("results").innerHTML=photoNotes(data)+`<div class="placeholder">図鑑データで確認できる候補が見つかりませんでした。全体・もよう・特徴のある部分を、別の角度から撮ってみてください。</div>${safetyHtml()}`;return}$('results').className='';$('results').innerHTML=photoNotes(data)+'<p class="summary"><strong>'+esc(data.category)+'</strong> · '+esc(data.summary)+'</p>' +data.candidates.map((c,i)=>'<article class="candidate"><div class="name-row"><div><div class="name">'+(i+1)+'. '+esc(c.common_name_ja)+'</div><div class="latin">'+esc(c.scientific_name)+'</div>'+taxonomyBadge(c)+agreementBadge(c)+'</div>'+confidenceView(c)+protectedSpeciesHtml(c)+evidenceHtml(c)+sexHtml(c,data.category)+(c.uncertainty?'<div class="uncertainty">もっと確かめたいこと：'+esc(c.uncertainty)+'</div>':'')+'<div class="sources"><a target="_blank" rel="noopener" href="'+sourceUrl(noJapaneseName(c.common_name_ja)?c.scientific_name:c.common_name_ja)+'">図鑑を検索 ↗</a>'+(wikipediaUrl(c)?'<a target="_blank" rel="noopener noreferrer" href="'+esc(wikipediaUrl(c))+'">Wikipedia ↗</a>':'')+(c.taxonomy_url?'<a target="_blank" rel="noopener" href="'+esc(c.taxonomy_url)+'">iNaturalist ↗</a>':'')+'</div>'+animalReferenceHtml(c,data.category)+affiliateProductLink(c,data.category)+'</article>').join('')+safetyHtml()+plantnetCreditHtml(data)+affiliateHtml();applyMeters();if(document.getElementById('affiliateCard'))fetch('/api/affiliate/impression',{method:'POST'}).catch(()=>{});loadAmazonProducts()}
function historyDb(){return new Promise((resolve,reject)=>{if(!("indexedDB" in window)){reject(new Error("このブラウザでは、調べた記録を保存できません"));return}const request=indexedDB.open("species-history",1);request.onupgradeneeded=()=>{const db=request.result;if(!db.objectStoreNames.contains("entries"))db.createObjectStore("entries",{keyPath:"id"})};request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)})}
function requestValue(request){return new Promise((resolve,reject)=>{request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)})}
function transactionDone(transaction){return new Promise((resolve,reject)=>{transaction.oncomplete=resolve;transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error)})}
/* 送った写真はすべて残す。1枚目だけだと、撮り足した寄りの1枚があとから見られず、
   調べ直しも1枚目だけで走ることになる。大きさは backup.js の HISTORY_MAX_EDGE。
   ドライブへ持ち出すぶんの上限は buildBackup 側で別に持つ */
/* 写真も撮影情報も、投げる前に控えたぶん (pending) を使う。画面を更新すると
   選んだファイルも入力欄の中身も手元から消えるので、いま画面を見て作れない */
async function saveHistory(data,pending){const db=await historyDb();const thumbnails=pending?.photos||[];const thumbnail=thumbnails[0]||null;/* 一覧の行と、ドライブへ持ち出すぶんに使う小さい1枚。行では80pxで出す */
let listThumbnail=null;try{if(thumbnail)listThumbnail=await shrinkForHistory(thumbnail,LIST_MAX_EDGE)}catch(e){}const metadata=data.photo_metadata||{};const coordinates=pending?.coordinates||(metadata.latitude!=null?{latitude:metadata.latitude,longitude:metadata.longitude}:null);const record={id:(crypto.randomUUID?.()||Date.now()+"-"+Math.random()),createdAt:new Date().toISOString(),category:data.category,summary:data.summary,candidates:data.candidates,provider:providerName,model:data.model||"",resultMeta:{strictMode:Boolean(data.strict_mode),taxonomyChecked:Boolean(data.taxonomy_checked),rejectedCandidates:Number(data.rejected_candidates||0),plantnetUsed:Boolean(data.plantnet_used)},context:pending?.context||{location:"",observedDate:"",size:""},coordinates,thumbnail,thumbnails,listThumbnail};let tx=db.transaction("entries","readwrite");tx.objectStore("entries").put(record);await transactionDone(tx);tx=db.transaction("entries","readonly");const all=await requestValue(tx.objectStore("entries").getAll());await transactionDone(tx);const excess=all.sort((a,b)=>b.createdAt.localeCompare(a.createdAt)).slice(50);if(excess.length){tx=db.transaction("entries","readwrite");excess.forEach(item=>tx.objectStore("entries").delete(item.id));await transactionDone(tx)}db.close();scheduleAutoBackup()}
/* 識別は後ろで走らせ、札 (job) を持って様子を聞きに行く。
 *
 * ブラウザが待っているあいだだけ生きる作りだと、画面を更新した瞬間に答えが行き場を
 * なくす。Ollama では1分ほどかかるので、その1分のあいだ画面を触れないのは実用に
 * 堪えない。札は localStorage に置き、開き直したら続きから聞く。
 *
 * 記録に残す写真は、投げる前に縮小して札と一緒に預けておく。更新すると選んだ
 * ファイルは手元から消えるので、あとから作れない。
 */
const PENDING_KEY="species-pending-identify";
let elapsedTimer=null;

/* 待っていることは、答えが出る場所にも書く。status 行は撮影パネルの下にあり、
   スマホでも画面を更新した直後でも目に入らない。1分かかる相手なので、
   止まっているのか動いているのかは秒数で示す */
function showWorking(startedAt){
  identify.disabled=true;
  $('results').className='placeholder working';
  const tick=()=>{
    const seconds=Math.max(0,Math.round((Date.now()-startedAt)/1000));
    const line=providerName+"が写真を見ています（"+seconds+"秒）";
    $('results').innerHTML='<div><strong><span class="spinner"></span>'+esc(line)+'</strong>'
      +'<p>形・色・もようを確認中…</p>'
      +'<p>この画面を閉じても、開き直せば続きから見られます。</p></div>';
    showStatus(line+"。この画面を閉じても、開き直せば続きから見られます。",false,true);
  };
  tick();
  clearInterval(elapsedTimer);
  elapsedTimer=setInterval(tick,1000);
}
function stopWorking(){clearInterval(elapsedTimer);elapsedTimer=null;identify.disabled=false}

function readPending(){try{return JSON.parse(localStorage.getItem(PENDING_KEY)||"null")}catch(e){return null}}
function writePending(value){
  try{value?localStorage.setItem(PENDING_KEY,JSON.stringify(value)):localStorage.removeItem(PENDING_KEY)}
  catch(e){/* 覚えられなくても、このタブで待っているあいだは動く */}
}

/* 縮小した写真は data URL にして預ける。3枚でも実測100KB台で localStorage に収まる。
   data URL との往復は backup.js のものを使う (CSP で fetch(data:) が使えない事情も同じ) */
async function pendingPhotos(){
  const out=[];
  for(const file of selected){
    try{
      const blob=await shrinkForHistory(file);
      if(blob)out.push(await blobToDataUrl(blob));
    }catch(e){/* 1枚読めなくても調べるのは続ける */}
  }
  return out;
}
function pendingToBlobs(urls){return (urls||[]).map(dataUrlToBlob).filter(Boolean)}

async function finishIdentification(data,pending){
  render(data);
  showStatus('似ている生きものを表示しました。実物と見くらべてください。');
  writePending(null);
  try{await saveHistory(data,{...pending,photos:pendingToBlobs(pending?.photos)})}
  catch(error){showStatus("候補は表示できましたが、この端末の記録には保存できませんでした。 "+error.message,true)}
}

async function pollIdentification(pending){
  showWorking(pending.startedAt||Date.now());
  while(true){
    await new Promise(done=>setTimeout(done,1500));
    if(readPending()?.job!==pending.job)return;   // 途中で別の調べものが始まった
    let payload;
    try{
      const response=await fetch("/identify/job/"+encodeURIComponent(pending.job));
      payload=await response.json();
      if(response.status===404)throw new Error(payload.detail||"この調べものは見つかりませんでした。");
    }catch(error){
      stopWorking();writePending(null);
      $('results').innerHTML='<div class="placeholder">結果を取得できませんでした。</div>';
      showStatus(error.message,true);
      return;
    }
    if(payload.status==="running")continue;
    stopWorking();
    if(payload.status==="error"){
      writePending(null);
      $('results').innerHTML='<div class="placeholder">結果を取得できませんでした。</div>';
      showStatus(errorText(payload.detail),true);
      return;
    }
    await finishIdentification(payload.result,pending);
    return;
  }
}

identify.onclick=async()=>{
  if(!selected.length)return;
  identify.disabled=true;
  const startedAt=Date.now();
  showWorking(startedAt);
  const fd=new FormData();
  selected.forEach(file=>fd.append("files",file));
  fd.append("background","true");
  fd.append("location",$("location").value);
  fd.append("observed_date",$("observedDate").value);
  fd.append("size",$("size").value);
  fd.append("use_plantnet",document.getElementById("usePlantnet").checked);
  if(window.speciesPublicMode){
    const saved=JSON.parse(localStorage.getItem("species-public-settings")||"{}");
    fd.append("request_provider",provider);
    fd.append("request_model",saved.models?.[provider]||window.speciesRuntimeModel||"");
    fd.append("request_api_key",readApiKey(provider));
    fd.append("request_plantnet_key",readApiKey("plantnet"));
  }
  const photos=await pendingPhotos();
  try{
    /* 公開版で「手元のAI」を選んだときは、写真をサーバーへ送らない。ブラウザから
       その場の Ollama を直接呼び、返ってきた本文だけをサーバーで仕上げる。
       プロンプトと仕上げ (証拠ゲート・種の保存法) はサーバーに1つだけ置き、
       ここへは写さない。写すと片方だけ直して食い違う */
    if(window.speciesPublicMode&&provider==="local"){
      const data=await identifyWithLocalOllama(selected,{
        location:$("location").value,observed_date:$("observedDate").value,size:$("size").value});
      stopWorking();
      const context={location:$("location").value,observedDate:$("observedDate").value,size:$("size").value};
      const coordinates=gps?{latitude:Number(gps.latitude.toFixed(4)),longitude:Number(gps.longitude.toFixed(4))}:null;
      await finishIdentification(data,{photos,context,coordinates});
      return;
    }
    const response=await fetch('/identify',{method:'POST',body:fd});
    const data=await response.json();
    if(!response.ok)throw new Error(errorText(data.detail));
    const context={location:$("location").value,observedDate:$("observedDate").value,size:$("size").value};
    const coordinates=gps?{latitude:Number(gps.latitude.toFixed(4)),longitude:Number(gps.longitude.toFixed(4))}:null;
    /* 札が返らない置き場もある (サーバーレスでは後ろの仕事が凍るので同期で返す)。
       その場合は返ってきたものが結果そのもの */
    if(!data.job){stopWorking();await finishIdentification(data,{photos,context,coordinates});return}
    const pending={job:data.job,startedAt,photos,
      context,coordinates};
    writePending(pending);
    pollIdentification(pending);
  }catch(e){
    stopWorking();
    $('results').innerHTML='<div class="placeholder">結果を取得できませんでした。</div>';
    showStatus(e.message,true);
  }
};
/* 開き直したとき、走らせたままの調べものがあれば続きから聞く */
(()=>{
  const pending=readPending();
  if(!pending?.job)return;
  pollIdentification(pending);
  /* 更新して戻ってきた人は、自分で下まで見に行かないと待っていることが分からない */
  $('results').scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"center"});
})();

loadSettings();
showSignIn();
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

/* 手元の Ollama を、ブラウザから直接呼ぶ。
 *
 * 公開版のサーバーに Ollama は無く、利用者の localhost にも届かない。かといって
 * 利用者に Ollama をインターネットへ晒させるのは筋が悪く、サーバーが任意のURLへ
 * つなぐ形は SSRF の入り口になる。写真はこの端末から出さず、サーバーには
 * 「何を訊くか」と「答えの仕上げ」だけを借りる。
 */
const LOCAL_OLLAMA_DEFAULT = "http://localhost:11434";

function localOllamaUrl() {
  const saved = JSON.parse(localStorage.getItem("species-public-settings") || "{}");
  return String(saved.localUrl || LOCAL_OLLAMA_DEFAULT).replace(/\/+$/, "");
}

function localOllamaModel() {
  const saved = JSON.parse(localStorage.getItem("species-public-settings") || "{}");
  return String(saved.models?.local || "").trim();
}

async function fileToBase64(file) {
  const buffer = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buffer);
  /* 一度に渡すと引数の数で落ちるので刻む */
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  }
  return btoa(binary);
}

async function identifyWithLocalOllama(files, context) {
  const model = localOllamaModel();
  if (!model) throw new Error("設定で、手元のAIのモデル名を入れてください（例: gemma4:12b）");
  const url = localOllamaUrl();

  const query = new URLSearchParams(context).toString();
  const asked = await fetch("/api/local/prompt?" + query);
  if (!asked.ok) throw new Error("問いかけの文面を受け取れませんでした");
  const ask = await asked.json();

  const images = [];
  for (const file of files) images.push(await fileToBase64(file));

  let content;
  try {
    const response = await fetch(url + "/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        model,
        messages: [{role: "user", content: ask.prompt, images}],
        stream: false, think: ask.think, format: ask.format, options: ask.options,
      }),
    });
    if (!response.ok) throw new Error("手元のAIがエラーを返しました（" + response.status + "）");
    content = (await response.json())?.message?.content || "";
  } catch (error) {
    /* つながらない理由はだいたい3つで、利用者が打てる手が違う */
    if (error instanceof TypeError) {
      throw new Error("手元のAIにつながりません。Ollama が動いているか、"
        + "このサイトからの接続を許しているか（OLLAMA_ORIGINS）を確かめてください。"
        + "接続先: " + url);
    }
    throw error;
  }

  const finished = await fetch("/api/local/result", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({text: content, model}),
  });
  const data = await finished.json();
  if (!finished.ok) throw new Error(errorText(data.detail));
  return data;
}
