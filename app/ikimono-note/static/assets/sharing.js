const SHARE_MAX_PHOTOS=4;/* Xの1投稿に載る画像は4枚まで。それ以上渡しても投稿側で落ちる */
function shareData(candidates){
  const names=(candidates||[]).slice(0,3).map(candidate=>(candidate.common_name_ja||candidate.scientific_name||"名前不明")+"（あてはまり度 "+Number(candidate.confidence||0)+"%）");
  return {title:"生きものノートで調べました",text:"写真から調べた候補："+names.join("、")+"\n結果は候補です。図鑑や実物で確かめてください。",url:location.origin+"/"};
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
