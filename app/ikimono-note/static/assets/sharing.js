const X_WEIGHTED_LIMIT=280;/* Xの上限。かな・漢字は2文字、ラテン文字は1文字として数えられる */
const X_URL_WEIGHT=23;/* URLは実際の長さによらず23文字ぶんとして数えられる */
/* twitter-text の既定の重み付け。ここを素朴に text.length で数えると、日本語は
   実際の半分しか使っていないつもりで上限を超える */
function xWeight(text){
  let total=0;
  for(const character of String(text)){
    const code=character.codePointAt(0);
    total+=(code<=0x10FF||(code>=0x2000&&code<=0x200D)||(code>=0x2010&&code<=0x201F)||(code>=0x2032&&code<=0x2037))?1:2;
  }
  return total;
}
const SHARE_NOTE="結果は候補です。図鑑や実物で確かめてください。";
function shareCandidateLine(candidates){
  const names=(candidates||[]).slice(0,3).map(candidate=>(candidate.common_name_ja||candidate.scientific_name||"名前不明")+"（あてはまり度 "+Number(candidate.confidence||0)+"%）");
  return "写真から調べた候補："+names.join("、");
}
/* 特徴は第1候補のものだけを使う。3件ぶん並べると上限を必ず超えるうえ、どの候補の
   話なのか読み手には分からない。AIが写真から拾ったものなので、断定に読めない体裁で置く */
function shareTraits(candidates){
  return (candidates?.[0]?.traits||[]).filter(trait=>typeof trait==="string"&&trait.trim()).map(trait=>trait.trim());
}
function shareBodyText(head,traits){
  return traits.length?head+"\n写真から見えた特徴："+traits.join("、")+"\n"+SHARE_NOTE:head+"\n"+SHARE_NOTE;
}
function shareBody(candidates){
  const head=shareCandidateLine(candidates);
  /* 特徴を1件ずつ足し、入るところで止める。溢れたぶんを切ると文が途中で終わるので、
     載せる件数のほうを減らす。URLは別枠で23文字ぶん、その手前の区切りに1文字みておく */
  const room=X_WEIGHTED_LIMIT-X_URL_WEIGHT-1;
  const chosen=[];
  for(const trait of shareTraits(candidates)){
    const attempt=chosen.concat(trait);
    if(xWeight(shareBodyText(head,attempt))>room)break;
    chosen.push(trait);
  }
  return shareBodyText(head,chosen);
}
/* Xのカードは1200x628が目安。これ以上大きくしても効かず、Firestore のドキュメント上限
   (1MiB) に近づくだけ */
const SHARE_PAGE_MAX_EDGE=1200;
function xShareUrl(candidates,pageUrl){
  const params=new URLSearchParams({text:shareBody(candidates),url:pageUrl||location.origin+"/"});
  return "https://x.com/intent/tweet?"+params.toString();
}
/* 共有ページに載せる1枚。shrinkForHistory は canvas 経由なので必ず JPEG を返す。
   X がカードに出す形式は JPEG・PNG・GIF だけで、webp のまま送ると画像の出ないカードになる */
async function sharePageImage(photo){
  if(!photo)return null;
  if(typeof shrinkForHistory==="function"){
    try{const blob=await shrinkForHistory(photo,SHARE_PAGE_MAX_EDGE);if(blob)return blob}
    catch(error){/* 縮められなければ元のまま送る。大きすぎればサーバーが断る */}
  }
  return photo instanceof Blob?photo:null;
}
function sharePageCandidates(candidates){
  return (candidates||[]).slice(0,3).map(candidate=>({
    common_name_ja:candidate.common_name_ja||"",
    scientific_name:candidate.scientific_name||"",
    confidence:Number(candidate.confidence||0),
    traits:(candidate.traits||[]).slice(0,3)}));
}
/* 共有ボタンを押したときだけ、その記録が公開ページになる。押していない記録はここを通らない */
async function createSharePage(candidates,photo){
  const image=await sharePageImage(photo);
  if(!image)throw new Error("共有できる写真がありません。");
  const form=new FormData();
  form.append("photo",new File([image],"share.jpg",{type:image.type||"image/jpeg"}));
  form.append("candidates",JSON.stringify(sharePageCandidates(candidates)));
  const response=await fetch("/api/share",{method:"POST",body:form});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(data.detail||"共有ページを作れませんでした。");
  return data;
}
/* 公開ページを作ってからXを開く。開くのは押した直後でないとブロックされるので、先に空の
   タブを取っておき、URLが決まってからそこへ送る。about:blank のまま数秒待たせることになるが、
   押し直しを求めるより短い */
async function shareToX(candidates,photo,onError,onNotice,onShared){
  /* 写真がなければ公開ページを作る意味がない。候補だけを本文にして投稿画面を開く */
  if(!photo){
    if(!window.open(xShareUrl(candidates),"_blank","noopener,noreferrer"))onError?.("Xの投稿画面を開けませんでした。");
    return;
  }
  const tab=window.open("about:blank","_blank");
  if(tab){try{tab.opener=null}catch(error){}}
  try{
    const shared=await createSharePage(candidates,photo);
    onShared?.(shared);
    const target=xShareUrl(candidates,shared.url);
    if(tab)tab.location.replace(target);
    else if(!window.open(target,"_blank","noopener,noreferrer"))throw new Error("Xの投稿画面を開けませんでした。");
    onNotice?.("共有ページを作りました。写真はXのカードに出ます。");
  }catch(error){
    if(tab)try{tab.close()}catch(ignored){}
    onError?.(error?.message||"共有できませんでした。もう一度お試しください。");
  }
}
async function deleteSharePage(token){
  const response=await fetch("/api/share/"+encodeURIComponent(token)+"/delete",{method:"POST"});
  if(response.ok)return true;
  const data=await response.json().catch(()=>({}));
  throw new Error(data.detail||"公開を取り消せませんでした。");
}
