const $=id=>document.getElementById(id);let current=null;const deleteKeys=new Set();
const providerLabels={local:"ローカルLLM",openai:"OpenAI API",anthropic:"Anthropic API",gemini:"Google Gemini API"};
const esc=value=>String(value).replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
function show(text,state=""){$("message").textContent=text;$("message").className="message"+(state?" "+state:"")}
function render(data){current=data;document.querySelector('[name=provider][value="'+data.provider+'"]').checked=true;$("active-provider").textContent=providerLabels[data.provider]+" · "+data.models[data.provider];$("local-llm-url").value=data.local_llm.url;$("local-model-options").innerHTML=data.available_models.local.map(item=>'<option value="'+esc(item.id)+'">'+esc(item.label)+'</option>').join("");$("model-local").value=data.models.local;for(const provider of ["openai","anthropic","gemini"]){const select=$("model-"+provider);select.innerHTML=data.available_models[provider].map(item=>'<option value="'+esc(item.id)+'">'+esc(item.label)+'</option>').join("");select.value=data.models[provider]}const incompatible=data.incompatible_local_models||[];$("local-model-note").textContent=incompatible.length?"画像非対応: "+incompatible.join("、"):"画像対応モデル（名前の直接入力も可能）";for(const provider of ["openai","anthropic","gemini","plantnet"]){$("configured-"+provider).textContent=data.api_key_configured[provider]?"登録済み（変更時だけ入力）":"未登録"}$("affiliate-title").value=data.affiliate.title||"";$("affiliate-url").value=data.affiliate.url||"";$("affiliate-enabled").checked=Boolean(data.affiliate.enabled);$("affiliate-partner-tag").value=data.affiliate.partner_tag||"";$("affiliate-product-enabled").checked=Boolean(data.affiliate.product_enabled);$("configured-amazon-creators").textContent=data.affiliate.creators_api_configured?"認証情報を登録済み":"認証情報は未登録";$("affiliate-metrics").textContent="表示 "+data.affiliate.metrics.impressions+" · クリック "+data.affiliate.metrics.clicks}
async function load(){try{const response=await fetch("/api/settings");if(!response.ok)throw new Error("設定を読み込めませんでした");const data=await response.json();render(data);if(data.public_mode)setupPublicSettings(data)}catch(error){show(error.message,"error")}}
document.querySelectorAll("[data-delete]").forEach(button=>button.onclick=()=>{const provider=button.dataset.delete;deleteKeys.add(provider);$("key-"+provider).value="";const note=$("configured-"+provider);if(note)note.textContent="保存すると登録を削除します"});
$("settingsForm").onsubmit=async event=>{event.preventDefault();const provider=document.querySelector("[name=provider]:checked")?.value;if(!provider)return;const payload={provider,models:{},local_llm:{url:$("local-llm-url").value.trim()},api_keys:{},delete_keys:[...deleteKeys],affiliate:{title:$("affiliate-title").value.trim(),url:$("affiliate-url").value.trim(),enabled:$("affiliate-enabled").checked,partner_tag:$("affiliate-partner-tag").value.trim(),product_enabled:$("affiliate-product-enabled").checked}};for(const name of ["local","openai","anthropic","gemini"])payload.models[name]=$("model-"+name).value;for(const name of ["openai","anthropic","gemini","plantnet","amazon_creators_id","amazon_creators_secret"]){const key=$("key-"+name).value.trim();if(key)payload.api_keys[name]=key}const save=$("save-button");save.disabled=true;save.textContent="保存中…";show("設定を確認しています…");try{const response=await fetch("/api/settings",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.detail||"保存できませんでした");deleteKeys.clear();document.querySelectorAll('input[type="password"]').forEach(input=>input.value="");render(data);show("設定を保存しました。","success")}catch(error){show(error.message,"error")}finally{save.disabled=false;save.textContent="変更を保存"}};
load();
function setupPublicSettings(data){
  const stored=JSON.parse(localStorage.getItem("species-public-settings")||"{}");
  const localAvailable=Boolean(data.available_models.local.length);
  const localRadio=document.querySelector("[name=provider][value=local]");
  localRadio.disabled=!localAvailable;
  if(!localAvailable)localRadio.closest(".provider").querySelector(".help").textContent="公開版では運営者が無効にしています。";
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
  for(const id of ["affiliate-title","affiliate-url","affiliate-enabled","affiliate-partner-tag","affiliate-product-enabled","key-amazon_creators_id","key-amazon_creators_secret"]){
    $(id).disabled=true;
  }
  const security=document.querySelector(".security");
  security.innerHTML="<li>APIキーはこのブラウザタブだけに保存し、タブを閉じると消えます。</li><li>キーは判定時だけ暗号化通信で送信し、サーバー設定や履歴には保存しません。</li><li>ローカルLLMと広告は運営者が管理し、利用者から接続先を変更できません。</li><li>アプリの利用に年齢制限はありません。APIキーの登録と料金の負担は、契約者ご本人が行ってください。</li>";
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
