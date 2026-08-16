const ANALYTICS_ID="G-T9FSRF5Q4F",ANALYTICS_CHOICE="ikimono-analytics-consent";
function analyticsChoice(){try{return localStorage.getItem(ANALYTICS_CHOICE)||""}catch(error){return ""}}
function rememberAnalyticsChoice(value){try{value?localStorage.setItem(ANALYTICS_CHOICE,value):localStorage.removeItem(ANALYTICS_CHOICE)}catch(error){}}
function loadAnalytics(){if(window.gtag||document.querySelector("script[data-ikimono-analytics]"))return;window.dataLayer=window.dataLayer||[];window.gtag=function(){window.dataLayer.push(arguments)};window.gtag("consent","default",{analytics_storage:"granted",ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied"});window.gtag("set",{allow_google_signals:false,allow_ad_personalization_signals:false});window.gtag("js",new Date());window.gtag("config",ANALYTICS_ID);const script=document.createElement("script");script.async=true;script.dataset.ikimonoAnalytics="1";script.src="https://www.googletagmanager.com/gtag/js?id="+encodeURIComponent(ANALYTICS_ID);document.head.append(script)}
function hideAnalyticsPanel(){document.getElementById("analyticsConsent")?.remove()}
function showAnalyticsPanel(){if(document.getElementById("analyticsConsent"))return;const panel=document.createElement("aside");panel.id="analyticsConsent";panel.className="analytics-consent";panel.setAttribute("aria-label","アクセス解析の設定");panel.innerHTML='<p><strong>アクセス解析について</strong><span>サイト改善のため、同意した場合だけGoogle Analyticsへ閲覧情報を送ります。写真、位置情報、調べた結果は送りません。</span></p><div><button class="analytics-allow" type="button">同意する</button><button class="analytics-deny" type="button">送信しない</button><a href="/privacy#analytics">詳しく見る</a></div>';document.body.append(panel);panel.querySelector(".analytics-allow").onclick=()=>{rememberAnalyticsChoice("granted");hideAnalyticsPanel();loadAnalytics()};panel.querySelector(".analytics-deny").onclick=()=>{rememberAnalyticsChoice("denied");if(window.gtag)window.gtag("consent","update",{analytics_storage:"denied",ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied"});hideAnalyticsPanel()}}
function resetAnalyticsChoice(){rememberAnalyticsChoice("");showAnalyticsPanel()}
/* 設定変更のボタンは、このスクリプトが動いたときだけ置く。HTMLに直接書くと、解析を
   読み込まない側 (運営者用) や、拡張機能にこのファイルを止められた利用者の画面に、
   押しても何も起きないボタンだけが残る。故障と見分けがつかない */
function mountAnalyticsReset(){
  const slot=document.getElementById("analytics-reset-slot");
  if(!slot||slot.querySelector("button"))return;
  const button=document.createElement("button");
  button.className="back";button.id="analytics-reset";button.type="button";
  button.textContent="アクセス解析の設定を変更";
  button.onclick=resetAnalyticsChoice;
  slot.append(button);
}
document.addEventListener("DOMContentLoaded",()=>{const choice=analyticsChoice();if(choice==="granted")loadAnalytics();else if(choice!=="denied")showAnalyticsPanel();mountAnalyticsReset()});
