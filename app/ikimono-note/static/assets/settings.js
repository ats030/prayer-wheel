const $=id=>document.getElementById(id);let current=null;const deleteKeys=new Set();
const providerLabels={local:"Ollama",openai:"OpenAI API",anthropic:"Anthropic API",gemini:"Google Gemini API"};
const esc=value=>String(value).replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
function show(text,state=""){$("message").textContent=text;$("message").className="message"+(state?" "+state:"")}
function render(data){current=data;document.querySelector('[name=provider][value="'+data.provider+'"]').checked=true;$("active-provider").textContent=providerLabels[data.provider]+" · "+data.models[data.provider];$("local-llm-url").value=data.local_llm.url;$("local-model-options").innerHTML=data.available_models.local.map(item=>'<option value="'+esc(item.id)+'">'+esc(item.label)+'</option>').join("");$("model-local").value=data.models.local;for(const provider of ["openai","anthropic","gemini"]){const select=$("model-"+provider);select.innerHTML=data.available_models[provider].map(item=>'<option value="'+esc(item.id)+'">'+esc(item.label)+'</option>').join("");select.value=data.models[provider]}const incompatible=data.incompatible_local_models||[];$("local-model-note").textContent=incompatible.length?"画像非対応: "+incompatible.join("、"):"画像対応モデル（名前の直接入力も可能）";for(const provider of ["openai","anthropic","gemini","plantnet"]){$("configured-"+provider).textContent=data.api_key_configured[provider]?"登録済み（変更時だけ入力）":"未登録"}$("affiliate-title").value=data.affiliate.title||"";$("affiliate-url").value=data.affiliate.url||"";$("affiliate-enabled").checked=Boolean(data.affiliate.enabled);$("affiliate-partner-tag").value=data.affiliate.partner_tag||"";$("affiliate-product-enabled").checked=Boolean(data.affiliate.product_enabled);$("configured-amazon-creators").textContent=data.affiliate.creators_api_configured?"認証情報を登録済み":"認証情報は未登録";renderCreatorsState(data.creators_api_state);$("affiliate-metrics").textContent="表示 "+data.affiliate.metrics.impressions+" · クリック "+data.affiliate.metrics.clicks}
async function load(){try{const response=await fetch("/api/settings");if(!response.ok)throw new Error("設定を読み込めませんでした");const data=await response.json();render(data);if(data.public_mode)setupPublicSettings(data);else{operatorNote();}}catch(error){show(error.message,"error")}}
document.querySelectorAll("[data-delete]").forEach(button=>button.onclick=()=>{const provider=button.dataset.delete;deleteKeys.add(provider);$("key-"+provider).value="";const note=$("configured-"+provider);if(note)note.textContent="保存すると登録を削除します"});
$("settingsForm").onsubmit=async event=>{event.preventDefault();const provider=document.querySelector("[name=provider]:checked")?.value;if(!provider)return;const payload={provider,models:{},local_llm:{url:$("local-llm-url").value.trim()},api_keys:{},delete_keys:[...deleteKeys],affiliate:{title:$("affiliate-title").value.trim(),url:$("affiliate-url").value.trim(),enabled:$("affiliate-enabled").checked,partner_tag:$("affiliate-partner-tag").value.trim(),product_enabled:$("affiliate-product-enabled").checked}};for(const name of ["local","openai","anthropic","gemini"])payload.models[name]=$("model-"+name).value;for(const name of ["openai","anthropic","gemini","plantnet","amazon_creators_id","amazon_creators_secret"]){const key=$("key-"+name).value.trim();if(key)payload.api_keys[name]=key}const save=$("save-button");save.disabled=true;save.textContent="保存中…";show("設定を確認しています…");try{const response=await fetch("/api/settings",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.detail||"保存できませんでした");deleteKeys.clear();document.querySelectorAll('input[type="password"]').forEach(input=>input.value="");render(data);show("設定を保存しました。","success")}catch(error){show(error.message,"error")}finally{save.disabled=false;save.textContent="変更を保存"}};
load();
function setupPublicSettings(data){
  document.querySelectorAll("[id^=key-]").forEach(field=>{
    field.addEventListener("input",()=>setTimeout(refreshActive,0));
  });

  const keep=$("keep-keys");
  if(keep){keep.checked=keepingKeys();keep.onchange=()=>{setKeepingKeys(keep.checked);
    for(const name of ["openai","anthropic","gemini","plantnet"])
      (el=>{const has=Boolean(readApiKey(name));el.textContent=has?(keepingKeys()?"この端末に登録済み":"このタブに登録済み"):"APIキーが未登録です";el.dataset.missing=has?"0":"1"})($("configured-"+name));
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
    (el=>{const has=Boolean(readApiKey(name));el.textContent=has?(keepingKeys()?"この端末に登録済み":"このタブに登録済み"):"APIキーが未登録です";el.dataset.missing=has?"0":"1"})($("configured-"+name));
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
      (el=>{const has=Boolean(readApiKey(name));el.textContent=has?(keepingKeys()?"この端末に登録済み":"このタブに登録済み"):"APIキーが未登録です";el.dataset.missing=has?"0":"1"})($("configured-"+name));
    }
    deleteKeys.clear();
    $("active-provider").textContent=providerLabels[selectedProvider]+" · "+models[selectedProvider];
    /* 自動保存は記録が増減したときに動く。設定だけ変えて調べずに閉じると、
       使うAIの選択がドライブへ行かないまま残る。「いま保存」を置く代わりに、
       設定を保存したこの時点で自動保存を促す */
    scheduleAutoBackup();
    show("この端末の設定を保存しました。APIキーはタブを閉じると消えます。","success");
  };
}

/* 記録と設定の持ち出し。保存先は利用者が選び、運営者のサーバーは経由しない */
/* 運営者用の注記。置き場所は画面側で決まるので、無ければ何もしない。
   以前ここで直に textContent を入れており、要素が消えたあとも気づかなかった。
   load() が try で囲まれているため、画面にエラー文が出るだけで JS エラーにならず、
   その先の描画 (モデルの選択肢) が丸ごと止まっていた */
function operatorNote(){
  const label=document.querySelector("#guardianNote span");
  if(label)label.textContent="運営者用";
  const text=$("guardianText");
  if(text)text.textContent="この画面は運営者用です。ここで保存したAPIキーとモデルはサーバーに記録され、公開版 (8524) の既定値としても使われます。";
}

function backupMessage(text, state){const el=$("backup-message");el.textContent=text;el.className="message"+(state?" "+state:"")}
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

/* 記録の保存先は Google ドライブだけ。選ばせる画面は持たない */
async function refreshDrive(){
  const settings=await fetch("/api/settings").then(r=>r.ok?r.json():null).catch(()=>null);
  const clientId=settings?.google_client_id||"";
  if(!driveConfigured(clientId)){
    $("drive-unavailable").hidden=false;
    $("drive-unavailable").textContent="この生きものノートでは Google ドライブへの保存が設定されていません。運営者が IKIMONO_GOOGLE_CLIENT_ID を設定すると使えます。";
    return;
  }
  $("drive-strip").hidden=false;$("drive-actions").hidden=false;
  const paint=()=>{
    const on=driveSignedIn();
    $("drive-state").textContent=on?"つながっています（自動で保存します）":driveLinked()?"つなぎ直しが必要です":"未接続";
    $("drive-connect").hidden=on;
    $("drive-load").hidden=!on;$("drive-forget").hidden=!on;
  };
  /* 一度つないだ相手なら、画面を出さずに取り直せることが多い */
  if(driveLinked())await ensureDriveToken(clientId);
  paint();
  $("drive-connect").onclick=async()=>{
    const button=$("drive-connect");button.disabled=true;backupMessage("Google の許可を求めています…");
    try{
      await driveSignIn(clientId);paint();
      /* つないだ直後に一度書く。自動保存は記録が増減したときに動くので、
         つないだだけではドライブに何も現れず、失敗したように見える */
      backupMessage("つながりました。いま保存しています…");
      const count=await saveToDrive();
      backupMessage(`つながりました。記録 ${count}件をドライブへ保存しました。これからは自動で保存されます。`,"success");
    }
    catch(error){backupMessage("つなげませんでした。"+error.message,"error")}
    finally{button.disabled=false}
  };
  $("drive-load").onclick=async()=>{
    $("drive-load").disabled=true;backupMessage("読み込んでいます…");
    try{backupMessage(`記録 ${await loadFromDrive()}件を読み込みました。`,"success")}
    catch(error){backupMessage("読み込めませんでした。"+error.message,"error")}
    finally{$("drive-load").disabled=false}
  };
  $("drive-forget").onclick=()=>{
    forgetDrive();paint();
    backupMessage("接続を解除しました。ドライブ上のファイルは消していません。","success");
  };
}
refreshDrive();

/* 「認証情報を登録済み」は登録の有無しか言わない。Amazon が受け付けているかは別の話で、
   実際に 403 AssociateNotEligible で止まっているのに、この欄は登録済みのままだった。
   最後に商品APIを呼んだ結果を、そのまま置く。まだ一度も呼んでいなければ何も出さない
   (推測で「正常」と書くと、また同じ思い込みを作る)。 */
function renderCreatorsState(state){
  const box=$("creators-api-state");
  if(!box)return;
  if(!state||typeof state.ok!=="boolean"){box.hidden=true;box.textContent="";return}
  const when=state.at?new Date(state.at).toLocaleString("ja-JP"):"";
  box.hidden=false;
  box.className="api-state "+(state.ok?"ok":"warn");
  box.textContent=state.ok
    ? "最後の呼び出しは成功しました" + (when?"（"+when+"）":"")
    : "Amazonが受け付けていません" + (state.status?"（"+state.status+(state.reason?" "+state.reason:"")+"）":"")
      + (when?" "+when:"") + (state.hint?" — "+state.hint:"");
}
