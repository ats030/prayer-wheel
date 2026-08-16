const SHARE_MAX_PHOTOS=4;/* Xの1投稿に載る画像は4枚まで。それ以上渡しても投稿側で落ちる */
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
function shareData(candidates){
  return {title:"生きものノートで調べました",text:shareBody(candidates),url:location.origin+"/"};
}
function shareText(candidates){const payload=shareData(candidates);return payload.text+"\n"+payload.url}
function xShareUrl(candidates){
  const payload=shareData(candidates);
  const params=new URLSearchParams({text:payload.text,url:payload.url});
  return "https://x.com/intent/tweet?"+params.toString();
}
function sharePhotoFile(photo,candidates,index=0){
  if(!photo)return null;
  const type=String(photo.type||"").startsWith("image/")?photo.type:"image/jpeg";
  const extension={"image/png":"png","image/webp":"webp","image/gif":"gif"}[type]||"jpg";
  const rawName=(candidates?.[0]?.common_name_ja||"ikimono").replace(/[\\/:*?"<>|]/g,"_");
  return photo instanceof File?photo:new File([photo],rawName+(index?"-"+(index+1):"")+"."+extension,{type});
}
function sharePhotoFiles(photos,candidates){
  const list=Array.isArray(photos)?photos:(photos?[photos]:[]);
  return list.filter(Boolean).slice(0,SHARE_MAX_PHOTOS).map((photo,index)=>sharePhotoFile(photo,candidates,index)).filter(Boolean);
}
/* 複数枚を断る端末でも1枚なら受け取ることがある。全滅と決めつけず、通る枚数まで減らして試す */
function shareableFiles(files){
  if(!files.length||!navigator.share||!navigator.canShare)return [];
  for(let count=files.length;count>0;count--){
    const subset=files.slice(0,count);
    if(navigator.canShare({files:subset}))return subset;
  }
  return [];
}
/* 本文と写真を一度に渡すと、共有先は本文だけを受け取って写真を落とす。共有シートには写真だけを渡し、
   本文はクリップボードへ回す。writeText はユーザー操作と同じターンで呼ぶ必要があるので await しない */
function copyShareText(candidates){
  if(!navigator.clipboard?.writeText)return Promise.resolve(false);
  try{return navigator.clipboard.writeText(shareText(candidates)).then(()=>true,()=>false)}
  catch(error){return Promise.resolve(false)}
}
/* PCのブラウザは共有シートを持たず、X Web Intent には画像を渡す口がない。写真を端末へ落として
   投稿画面を開き、添付だけをユーザーの手に委ねる */
function downloadSharePhotos(files){
  files.forEach(file=>{
    const url=URL.createObjectURL(file),link=document.createElement("a");
    link.href=url;link.download=file.name;document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  });
}
function sharedPhotoNotice(shared,total){return shared<total?"写真は"+shared+"枚だけ渡せました。":""}
async function sharePhotoForX(candidates,photos,onError,onNotice){
  const files=sharePhotoFiles(photos,candidates),sendable=shareableFiles(files);
  if(sendable.length){
    const copied=copyShareText(candidates);
    try{
      await navigator.share({files:sendable});
      onNotice?.(sharedPhotoNotice(sendable.length,files.length)+(await copied?"本文をコピーしました。Xで貼り付けてください。":"本文はXで入力してください。"));
      return;
    }
    catch(error){if(error?.name==="AbortError")return}
  }
  const opened=window.open(xShareUrl(candidates),"_blank","noopener,noreferrer");
  if(!opened){onError?.();return}
  if(!files.length)return;
  downloadSharePhotos(files);
  onNotice?.("写真"+files.length+"枚を端末に保存しました。Xの投稿画面で添付してください。");
}
