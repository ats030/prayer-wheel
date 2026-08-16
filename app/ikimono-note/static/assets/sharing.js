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
/* 名乗りと但し書き。カードが出ない相手には本文しか残らないので、アプリ名はここに置く。
   但し書きを削って宣伝を伸ばすことはしない — 全年齢のアプリで、候補を断定に読ませない一文は
   共有ページ側にもあるが、本文だけを見て終わる人がいる */
const SHARE_FOOTER="「生きものノート」で調べました。結果は候補です。図鑑や実物で確かめてください。";
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
  return traits.length?head+"\n写真から見えた特徴："+traits.join("、")+"\n"+SHARE_FOOTER:head+"\n"+SHARE_FOOTER;
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
/* カードの寸法。X は summary_large_image に 1.91:1 を想定し、300x157 を下回る画像は
   カードに出さない */
const SHARE_CARD_WIDTH=1200,SHARE_CARD_HEIGHT=630;
const SHARE_CARD_BACKGROUND="#f4faf2";
function xShareUrl(candidates,pageUrl){
  const params=new URLSearchParams({text:shareBody(candidates),url:pageUrl||location.origin+"/"});
  return "https://x.com/intent/tweet?"+params.toString();
}
/* 記録の写真をそのまま渡さず、カードの寸法で作り直す。
   縮小だけでは足りない。原寸を持たない記録は一覧用の320pxしか持っておらず、長辺1200を
   指定しても320のまま出ていく。幅240ではXの最小要件を下回り、カードに画像が出ない。
   縦長も同じで、1.91:1 から外れたものは想定の外にある。
   はめ方は contain。cover にすると被写体が切れる。名前を調べた生きものが切れているカードは、
   カードとしては整っていても用を成さない */
async function shareCardImage(photo){
  if(!photo)return null;
  const bitmap=await createImageBitmap(photo);
  const canvas=document.createElement("canvas");
  canvas.width=SHARE_CARD_WIDTH;canvas.height=SHARE_CARD_HEIGHT;
  const context=canvas.getContext("2d");
  context.fillStyle=SHARE_CARD_BACKGROUND;
  context.fillRect(0,0,SHARE_CARD_WIDTH,SHARE_CARD_HEIGHT);
  const scale=Math.min(SHARE_CARD_WIDTH/bitmap.width,SHARE_CARD_HEIGHT/bitmap.height);
  const width=Math.max(1,Math.round(bitmap.width*scale)),height=Math.max(1,Math.round(bitmap.height*scale));
  context.drawImage(bitmap,Math.round((SHARE_CARD_WIDTH-width)/2),Math.round((SHARE_CARD_HEIGHT-height)/2),width,height);
  bitmap.close();
  /* canvas.toBlob は必ず JPEG を返す。X がカードに出すのは JPEG・PNG・GIF だけで、
     webp のまま送ると画像の出ないカードになる */
  return new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",.82));
}
async function sharePageImage(photo){
  if(!photo)return null;
  try{const card=await shareCardImage(photo);if(card)return card}
  catch(error){/* 作れなければ元のまま送る。小さすぎればカードに出ないが、共有そのものは通す */}
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
