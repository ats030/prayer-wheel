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
    $("configured-"+name).textContent=sessionStorage.getItem("species-key-"+name)?"このタブに登録済み":"未登録";
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
      if(deleteKeys.has(name))sessionStorage.removeItem("species-key-"+name);
      else if(input.value.trim())sessionStorage.setItem("species-key-"+name,input.value.trim());
      input.value="";
      $("configured-"+name).textContent=sessionStorage.getItem("species-key-"+name)?"このタブに登録済み":"未登録";
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
