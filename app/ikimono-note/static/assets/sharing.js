function shareData(candidates){
  const names=(candidates||[]).slice(0,3).map(candidate=>(candidate.common_name_ja||candidate.scientific_name||"名前不明")+"（あてはまり度 "+Number(candidate.confidence||0)+"%）");
  return {title:"生きものノートで調べました",text:"写真から調べた候補："+names.join("、")+"\n結果は候補です。図鑑や実物で確かめてください。",url:location.origin+"/"};
}
function xShareUrl(candidates){
  const payload=shareData(candidates);
  const params=new URLSearchParams({text:payload.text,url:payload.url});
  return "https://x.com/intent/tweet?"+params.toString();
}
function sharePhotoFile(photo,candidates){
  if(!photo)return null;
  const type=String(photo.type||"").startsWith("image/")?photo.type:"image/jpeg";
  const extension={"image/png":"png","image/webp":"webp","image/gif":"gif"}[type]||"jpg";
  const rawName=(candidates?.[0]?.common_name_ja||"ikimono").replace(/[\\/:*?"<>|]/g,"_");
  return photo instanceof File?photo:new File([photo],rawName+"."+extension,{type});
}
async function sharePhotoForX(candidates,photo,onError){
  const payload=shareData(candidates),file=sharePhotoFile(photo,candidates);
  if(file&&navigator.share&&navigator.canShare?.({files:[file]})){
    try{await navigator.share({...payload,files:[file]});return}
    catch(error){if(error?.name==="AbortError")return}
  }
  const opened=window.open(xShareUrl(candidates),"_blank","noopener,noreferrer");
  if(!opened&&onError)onError();
}
