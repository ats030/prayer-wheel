function shareData(candidates){
  const names=(candidates||[]).slice(0,3).map(candidate=>(candidate.common_name_ja||candidate.scientific_name||"名前不明")+"（あてはまり度 "+Number(candidate.confidence||0)+"%）");
  return {title:"生きものノートで調べました",text:"写真から調べた候補："+names.join("、")+"\n結果は候補です。図鑑や実物で確かめてください。",url:location.origin+"/"};
}
async function shareCandidates(candidates,button,onError){
  const payload=shareData(candidates);
  if(navigator.share){
    try{await navigator.share(payload);return}
    catch(error){if(error?.name==="AbortError")return}
  }
  try{
    await navigator.clipboard.writeText(payload.text+"\n"+payload.url);
    button.textContent="共有文をコピーしました";
  }catch(error){
    if(onError)onError();
  }
}
