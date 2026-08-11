const $=id=>document.getElementById(id);let current=null;const deleteKeys=new Set();
const providerLabels={local:"Ollama",openai:"OpenAI API",anthropic:"Anthropic API",gemini:"Google Gemini API"};
const esc=value=>String(value).replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
function show(text,state=""){$("message").textContent=text;$("message").className="message"+(state?" "+state:"")}
function render(data){current=data;document.querySelector('[name=provider][value="'+data.provider+'"]').checked=true;$("active-provider").textContent=providerLabels[data.provider]+" · "+data.models[data.provider];$("local-llm-url").value=data.local_llm.url;$("local-model-options").innerHTML=data.available_models.local.map(item=>'<option value="'+esc(item.id)+'">'+esc(item.label)+'</option>').join("");$("model-local").value=data.models.local;for(const provider of ["openai","anthropic","gemini"]){const select=$("model-"+provider);select.innerHTML=data.available_models[provider].map(item=>'<option value="'+esc(item.id)+'">'+esc(item.label)+'</option>').join("");select.value=data.models[provider]}const incompatible=data.incompatible_local_models||[];$("local-model-note").textContent=incompatible.length?"画像非対応: "+incompatible.join("、"):"画像対応モデル（名前の直接入力も可能）";for(const provider of ["openai","anthropic","gemini","plantnet"]){$("configured-"+provider).textContent=data.api_key_configured[provider]?"登録済み（変更時だけ入力）":"未登録"}$("affiliate-title").value=data.affiliate.title||"";$("affiliate-url").value=data.affiliate.url||"";$("affiliate-enabled").checked=Boolean(data.affiliate.enabled);$("affiliate-partner-tag").value=data.affiliate.partner_tag||"";$("affiliate-product-enabled").checked=Boolean(data.affiliate.product_enabled);$("configured-amazon-creators").textContent=data.affiliate.creators_api_configured?"認証情報を登録済み":"認証情報は未登録";$("affiliate-metrics").textContent="表示 "+data.affiliate.metrics.impressions+" · クリック "+data.affiliate.metrics.clicks}
async function load(){try{const response=await fetch("/api/settings");if(!response.ok)throw new Error("設定を読み込めませんでした");const data=await response.json();render(data);if(data.public_mode)setupPublicSettings(data);else{document.querySelector("#guardianNote span").textContent="運営者用";$("guardianText").textContent="この画面は運営者用です。ここで保存したAPIキーとモデルはサーバーに記録され、公開版 (8524) の既定値としても使われます。公開版の利用者に自分のAPIキーを使わせる運用なら、ここでキーを登録する必要はありません。";}}catch(error){show(error.message,"error")}}
document.querySelectorAll("[data-delete]").forEach(button=>button.onclick=()=>{const provider=button.dataset.delete;deleteKeys.add(provider);$("key-"+provider).value="";const note=$("configured-"+provider);if(note)note.textContent="保存すると登録を削除します"});
$("settingsForm").onsubmit=async event=>{event.preventDefault();const provider=document.querySelector("[name=provider]:checked")?.value;if(!provider)return;const payload={provider,models:{},local_llm:{url:$("local-llm-url").value.trim()},api_keys:{},delete_keys:[...deleteKeys],affiliate:{title:$("affiliate-title").value.trim(),url:$("affiliate-url").value.trim(),enabled:$("affiliate-enabled").checked,partner_tag:$("affiliate-partner-tag").value.trim(),product_enabled:$("affiliate-product-enabled").checked}};for(const name of ["local","openai","anthropic","gemini"])payload.models[name]=$("model-"+name).value;for(const name of ["openai","anthropic","gemini","plantnet","amazon_creators_id","amazon_creators_secret"]){const key=$("key-"+name).value.trim();if(key)payload.api_keys[name]=key}const save=$("save-button");save.disabled=true;save.textContent="保存中…";show("設定を確認しています…");try{const response=await fetch("/api/settings",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.detail||"保存できませんでした");deleteKeys.clear();document.querySelectorAll('input[type="password"]').forEach(input=>input.value="");render(data);show("設定を保存しました。","success")}catch(error){show(error.message,"error")}finally{save.disabled=false;save.textContent="変更を保存"}};
load();
function setupPublicSettings(data){
  const keep=$("keep-keys");
  if(keep){keep.checked=keepingKeys();keep.onchange=()=>{setKeepingKeys(keep.checked);
    for(const name of ["openai","anthropic","gemini","plantnet"])
      $("configured-"+name).textContent=readApiKey(name)?(keepingKeys()?"この端末に登録済み":"このタブに登録済み"):"未登録";
    show(keep.checked?"APIキーをこの端末に残します。":"APIキーはタブを閉じると消えます。","success")}}

  const stored=JSON.parse(localStorage.getItem("species-public-settings")||"{}");
  const localAvailable=Boolean(data.available_models.local.length);
  const localRadio=document.querySelector("[name=provider][value=local]");
  localRadio.disabled=!localAvailable;
  const chosen={
    provider:stored.provider||data.provider,
    models:{...data.models,...(stored.models||{})}
  };
  if(!document.querySelector('[name=provider][value="'+chosen.provider+'"]'))chosen.provider="local";
  if(chosen.provider==="local"&&!localAvailable)chosen.provider="gemini";
  document.querySelector('[name=provider][value="'+chosen.provider+'"]').checked=true;
  for(const name of ["local","openai","anthropic","gemini"]){
    const field=$("model-"+name);
    if(chosen.models[name])field.value=chosen.models[name];
  }
  $("local-llm-url").value="";
  $("local-llm-url").disabled=true;
  $("local-llm-url").placeholder="公開版では運営者が管理します";
  for(const name of ["openai","anthropic","gemini","plantnet"]){
    $("configured-"+name).textContent=readApiKey(name)?(keepingKeys()?"この端末に登録済み":"このタブに登録済み"):"未登録";
  }
  document.querySelectorAll('[data-delete]').forEach(button=>{
    if(button.dataset.delete.startsWith("amazon_"))button.disabled=true;
  });
  // 広告の設定は運営者のもの。公開版の利用者が触る項目ではないので丸ごと畳む
  for(const id of ["affiliate-title","affiliate-url","affiliate-enabled","affiliate-partner-tag","affiliate-product-enabled","key-amazon_creators_id","key-amazon_creators_secret"]){
    $(id).disabled=true;
  }
  $("settingsForm").onsubmit=event=>{
    event.preventDefault();
    const selectedProvider=document.querySelector("[name=provider]:checked")?.value;
    const models={};
    for(const name of ["local","openai","anthropic","gemini"])models[name]=$("model-"+name).value;
    localStorage.setItem("species-public-settings",JSON.stringify({provider:selectedProvider,models}));
    for(const name of ["openai","anthropic","gemini","plantnet"]){
      const input=$("key-"+name);
      if(deleteKeys.has(name))clearApiKey(name);
      else if(input.value.trim())writeApiKey(name,input.value.trim());
      input.value="";
      $("configured-"+name).textContent=readApiKey(name)?(keepingKeys()?"この端末に登録済み":"このタブに登録済み"):"未登録";
    }
    deleteKeys.clear();
    $("active-provider").textContent=providerLabels[selectedProvider]+" · "+models[selectedProvider];
    show("この端末の設定を保存しました。APIキーはタブを閉じると消えます。","success");
  };
}

/* 記録と設定の持ち出し。保存先は利用者が選び、運営者のサーバーは経由しない */
function backupMessage(text, state){const el=$("backup-message");el.textContent=text;el.className="message"+(state?" "+state:"")}
$("export-backup").onclick=async()=>{
  const button=$("export-backup");
  button.disabled=true;backupMessage("まとめています…");
  try{
    const payload=await buildBackup();
    const blob=new Blob([JSON.stringify(payload)],{type:"application/json"});
    /* 対応していれば保存先を選ばせる。同期フォルダを選べば別端末から読める */
    if(window.showSaveFilePicker){
      const handle=await window.showSaveFilePicker({suggestedName:backupFileName(),
        types:[{description:"生きものノートの記録",accept:{"application/json":[".json"]}}]});
      const writable=await handle.createWritable();
      await writable.write(blob);await writable.close();
    }else{
      const url=URL.createObjectURL(blob);
      const link=document.createElement("a");link.href=url;link.download=backupFileName();link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }
    backupMessage(`記録 ${payload.records.length}件を書き出しました。`,"success");
  }catch(error){
    if(error?.name==="AbortError"){backupMessage("");}
    else backupMessage("書き出せませんでした。"+error.message,"error");
  }finally{button.disabled=false}
};
$("import-backup").onclick=()=>$("import-file").click();
$("import-file").onchange=async event=>{
  const file=event.target.files?.[0];
  event.target.value="";
  if(!file)return;
  backupMessage("読み込んでいます…");
  try{
    const restored=await restoreBackup(JSON.parse(await file.text()));
    backupMessage(`記録 ${restored}件を読み込みました。「記録」の画面で確認できます。`,"success");
  }catch(error){
    backupMessage("読み込めませんでした。"+error.message,"error");
  }
};

/* いつもの保存先。対応ブラウザだけに出す */
async function refreshTarget(){
  if(!backupSupported()){$("target-help").hidden=false;$("target-help").textContent=backupUnavailableReason();return}
  $("target-actions").hidden=false;$("target-help").hidden=false;
  const handle=await storedTarget();
  const strip=$("target-strip");
  if(!handle){strip.hidden=true;$("clear-target").disabled=true;$("load-target").disabled=true;return}
  strip.hidden=false;$("clear-target").disabled=false;$("load-target").disabled=false;
  const state=await targetPermission(handle);
  $("target-name").textContent=targetLabel(handle)+(state==="granted"?"":"（次に書くとき許可を求めます）");
}
$("choose-target").onclick=async()=>{
  try{
    const handle=await window.showDirectoryPicker({mode:"readwrite"});
    if(await targetPermission(handle,{ask:true})!=="granted"){backupMessage("書き込みが許可されませんでした。","error");return}
    await rememberTarget(handle);
    const count=await writeBackupTo(handle);
    await refreshTarget();
    backupMessage(`保存先フォルダを決めました。記録 ${count}件を書き出しました。`,"success");
  }catch(error){if(error?.name!=="AbortError")backupMessage("保存先を決められませんでした。"+error.message,"error")}
};
$("load-target").onclick=async()=>{
  const button=$("load-target");button.disabled=true;backupMessage("読み込んでいます…");
  try{
    const handle=await storedTarget();
    if(!handle)throw new Error("保存先が未設定です");
    if(await targetPermission(handle,{ask:true})!=="granted")throw new Error("読み取りが許可されませんでした");
    backupMessage(`記録 ${await readBackupFrom(handle)}件を読み込みました。`,"success");
  }catch(error){backupMessage("読み込めませんでした。"+error.message,"error")}
  finally{button.disabled=false}
};
$("clear-target").onclick=async()=>{
  await forgetTarget();await refreshTarget();
  backupMessage("保存先を解除しました。記録はこの端末に残ります。","success");
};

/* クラウド。URLは組み立てず、つないでフォルダを選んでもらう */
let cloudCursor = "";
function cloudCreds(){return {user:$("cloud-user").value.trim(),password:$("cloud-password").value}}
function cloudRoots(){
  const service=CLOUD_SERVICES[$("cloud-service").value];
  return service.roots($("cloud-host").value.trim(),$("cloud-user").value.trim());
}
function showCloudState(){
  const target=cloudTarget();
  $("cloud-state").textContent=target?("保存先: "+decodeURI(target.url)):"未接続";
  $("cloud-linked").hidden=!target;
  if(target){$("cloud-user").value=target.user||"";$("cloud-password").value=target.password||"";
    if(target.service)$("cloud-service").value=target.service;
    if(target.host)$("cloud-host").value=target.host;}
  $("cloud-host-field").hidden=!CLOUD_SERVICES[$("cloud-service").value].needsHost;
}
$("cloud-service").onchange=()=>{$("cloud-host-field").hidden=!CLOUD_SERVICES[$("cloud-service").value].needsHost};
async function browseCloud(url){
  const creds=cloudCreds();
  backupMessage("フォルダを読んでいます…");
  try{
    const folders=await listCloudFolders({url,...creds});
    cloudCursor=url;
    $("cloud-browser").hidden=false;
    $("cloud-path").textContent=decodeURI(url);
    const list=$("cloud-folders");
    list.innerHTML=folders.length?"":'<li class="empty">この中にフォルダはありません。ここに保存できます。</li>';
    folders.forEach(folder=>{
      const item=document.createElement("li");
      const button=document.createElement("button");
      button.type="button";button.textContent="📁 "+folder.name;
      button.onclick=()=>browseCloud(folder.url);
      item.append(button);list.append(item);
    });
    $("cloud-up").disabled=new URL(url).pathname==="/";
    backupMessage("");
  }catch(error){backupMessage(error.message,"error")}
}
$("cloud-connect").onclick=async()=>{
  const creds=cloudCreds();
  if(!creds.user||!creds.password){backupMessage("利用者名とパスワードを入れてください。","error");return}
  const button=$("cloud-connect");button.disabled=true;backupMessage("つないでいます…");
  try{
    /* pCloud は地域ごとに入口が違う。当たった方をそのまま使う */
    const found=await connectCloud(cloudRoots(),creds);
    await browseCloud(found.url);
  }catch(error){
    const hint=$("cloud-service").value==="pcloud"
      ? "pCloud で2段階認証を使っている場合、初回だけメールでの承認が要ります。"
        +"「New login attempt. Is this you?」という件名のメールを開き、"
        +"「Yes, it\'s me.」を押してから、もう一度お試しください。"
        +"Google や Apple のアカウントでログインしている場合は、pCloud 側でパスワードを設定してください。" : "";
    backupMessage("つなげませんでした。"+error.message+(hint?" "+hint:""),"error");
  }finally{button.disabled=false}
};
$("cloud-up").onclick=()=>{
  const url=new URL(cloudCursor);
  url.pathname=url.pathname.replace(/[^/]+\/$/,"");
  browseCloud(url.toString());
};
$("cloud-pick").onclick=async()=>{
  const target={url:cloudCursor,...cloudCreds(),service:$("cloud-service").value,host:$("cloud-host").value.trim()};
  $("cloud-pick").disabled=true;backupMessage("このフォルダへ保存しています…");
  try{
    const count=await saveToCloud(target);
    rememberCloud(target);showCloudState();
    $("cloud-browser").hidden=true;
    backupMessage(`保存先を決めました。記録 ${count}件を保存しました。`,"success");
  }catch(error){backupMessage("保存できませんでした。"+error.message,"error")}
  finally{$("cloud-pick").disabled=false}
};
$("cloud-save").onclick=async()=>{
  const target=cloudTarget();if(!target)return;
  $("cloud-save").disabled=true;backupMessage("クラウドへ保存しています…");
  try{backupMessage(`記録 ${await saveToCloud(target)}件を保存しました。`,"success")}
  catch(error){backupMessage("保存できませんでした。"+error.message,"error")}
  finally{$("cloud-save").disabled=false}
};
$("cloud-load").onclick=async()=>{
  const target=cloudTarget();if(!target)return;
  $("cloud-load").disabled=true;backupMessage("クラウドから読み込んでいます…");
  try{backupMessage(`記録 ${await loadFromCloud(target)}件を読み込みました。`,"success")}
  catch(error){backupMessage("読み込めませんでした。"+error.message,"error")}
  finally{$("cloud-load").disabled=false}
};
$("cloud-forget").onclick=()=>{
  forgetCloud();$("cloud-password").value="";$("cloud-browser").hidden=true;
  showCloudState();backupMessage("接続を解除しました。","success");
};

/* Google ドライブ。運営者がクライアントIDを設定していないと使えない */
async function refreshDrive(){
  const settings=await fetch("/api/settings").then(r=>r.ok?r.json():null).catch(()=>null);
  const clientId=settings?.google_client_id||"";
  if(!driveConfigured(clientId)){
    $("drive-unavailable").hidden=false;
    $("drive-unavailable").textContent="この生きものノートでは Google ドライブ連携が設定されていません。運営者が SPECIES_GOOGLE_CLIENT_ID を設定すると使えます。";
    return;
  }
  $("drive-actions").hidden=false;
  $("drive-state").textContent=driveSignedIn()?"つながっています":"未接続";
  $("drive-save").hidden=!driveSignedIn();
  $("drive-load").hidden=!driveSignedIn();
  $("drive-connect").onclick=async()=>{
    const button=$("drive-connect");button.disabled=true;backupMessage("Google の許可を求めています…");
    try{
      await driveSignIn(clientId);
      $("drive-state").textContent="つながっています";
      $("drive-save").hidden=false;$("drive-load").hidden=false;
      backupMessage("Google ドライブにつながりました。","success");
    }catch(error){backupMessage("つなげませんでした。"+error.message,"error")}
    finally{button.disabled=false}
  };
  $("drive-save").onclick=async()=>{
    $("drive-save").disabled=true;backupMessage("ドライブへ保存しています…");
    try{backupMessage(`記録 ${await saveToDrive()}件をドライブへ保存しました。`,"success")}
    catch(error){backupMessage("保存できませんでした。"+error.message,"error")}
    finally{$("drive-save").disabled=false}
  };
  $("drive-load").onclick=async()=>{
    $("drive-load").disabled=true;backupMessage("ドライブから読み込んでいます…");
    try{backupMessage(`記録 ${await loadFromDrive()}件を読み込みました。`,"success")}
    catch(error){backupMessage("読み込めませんでした。"+error.message,"error")}
    finally{$("drive-load").disabled=false}
  };
}

/* 保存先はひとつだけ選ぶ。選んだものの詳細だけを見せて、迷わせない */
const STORAGE_KIND_KEY = "species-storage-kind";
function showStorageKind(){
  const kind=$("storage-kind").value;
  document.querySelectorAll(".storage-body").forEach(body=>{body.hidden=body.dataset.storage!==kind});
  try{localStorage.setItem(STORAGE_KIND_KEY,kind)}catch(error){/* 覚えられなくても選択は効く */}
  if(kind==="drive")refreshDrive();
  if(kind==="folder")refreshTarget();
  if(kind==="webdav")showCloudState();
}
$("storage-kind").onchange=showStorageKind;
(function initStorageKind(){
  let saved="none";
  try{saved=localStorage.getItem(STORAGE_KIND_KEY)||"none"}catch(error){}
  /* すでに設定済みのものがあれば、それを選んだ状態で開く */
  if(saved==="none"){
    if(cloudTarget())saved="webdav";
    else if(driveFileId())saved="drive";
  }
  $("storage-kind").value=saved;
  showStorageKind();
})();

/* アカウント。ログインしているときだけ出す */
(async function showAccount(){
  const me=await fetch("/api/me").then(r=>r.ok?r.json():null).catch(()=>null);
  if(!me?.signed_in)return;
  $("account-section").hidden=false;
  $("account-email").textContent=me.email||"-";
  $("account-logout").onclick=async()=>{
    await fetch("/auth/logout",{method:"POST"}).catch(()=>{});
    location.href="/login";
  };
  $("account-delete").onclick=async()=>{
    if(!confirm("退会すると、預けているメールアドレスと識別子を削除します。この端末に残っている記録は消えません。よろしいですか？"))return;
    const response=await fetch("/api/me/delete",{method:"POST"}).catch(()=>null);
    if(response?.ok){location.href="/login"}
    else{$("account-message").className="message error";$("account-message").textContent="退会できませんでした。"}
  };
})();
