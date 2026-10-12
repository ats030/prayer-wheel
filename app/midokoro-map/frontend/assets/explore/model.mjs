export const labels = {shiseki:'史跡・名勝',omatsuri:'祭り',onsen:'温泉',tokusan:'特産物',geo:'地形・地質',geosite:'天然記念物',geopark:'ジオパーク',nationalpark:'国立公園'};
export const colors = {shiseki:'#172b3a',omatsuri:'#c4462d',onsen:'#247c85',tokusan:'#96651c',geo:'#2f6f4f',geosite:'#9a6a1d',geopark:'#2f6f4f',nationalpark:'#245b78'};
export const normalize = value => String(value ?? '').normalize('NFKC').trim().toLocaleLowerCase('ja');
const prefecturesOf = value => Array.isArray(value) ? value : (String(value || '').match(/(?:北海道|京都府|大阪府|東京都|[^\s、・,]+県)/g) || []);

export function pointEntries(domain, rows) {
  return rows.map((data, index) => {
    const localKey = String(domain === 'shiseki' ? data.id || data.qid : data.qid || `${data.label_ja}-${index}`);
    let venue = null;
    if(domain==='omatsuri'&&data.venue?.name){
      try { const source=new URL(data.venue.source);if(['http:','https:'].includes(source.protocol))venue=data.venue; } catch {}
    }
    const hasVenue=venue&&typeof venue.latitude==='number'&&typeof venue.longitude==='number';
    const latitude = hasVenue?venue.latitude:data.latitude, longitude = hasVenue?venue.longitude:data.longitude;
    const point = typeof latitude === 'number' && typeof longitude === 'number' && Number.isFinite(latitude) && Number.isFinite(longitude) && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180 ? [latitude, longitude] : null;
    const name = data.label_ja || data.label_en || '名称未登録';
    const region = [...new Set([data.prefecture, data.place || data.production_area || ''].filter(Boolean))].join(' ');
    const positionNote=domain==='tokusan'?(data.prefecture_level?'都道府県代表位置':['municipality_office','named_area_office'].includes(data.coordinate_kind)?'産地代表位置':''):domain==='omatsuri'&&data.coordinate_source==='administrative_area'&&!hasVenue?'行政区域の代表位置':'';
    return {key:`${domain}:${localKey}`,localKey,domain,kind:domain,name,region,prefectures:[data.prefecture].filter(Boolean),point,positionNote,data,search:normalize([name,region,data.description || ''].join(' '))};
  });
}

export function geoEntries(kind, features) {
  return features.map(data => {
    const props = data.properties, localKey = `${kind}:${kind === 'geosite' ? props.heritage_id : props.slug}`;
    const prefectures = prefecturesOf(props.prefecture || props.prefectures);
    const region = prefectures.join('・');
    const point = data.geometry.type === 'Point' ? [...data.geometry.coordinates].reverse() : null;
    return {key:`geo:${localKey}`,localKey,domain:'geo',kind,name:props.name,region,prefectures,point,geometry:data.geometry,data,search:normalize([props.name,region,...(props.municipalities || [])].join(' '))};
  });
}

export function contains(geometry, x, y) {
  const inside = ring => {
    let hit=false;
    for (let i=1;i<ring.length;i++) {
      const [x1,y1]=ring[i-1], [x2,y2]=ring[i];
      if ((y1>y)!==(y2>y) && x<x1+(y-y1)*(x2-x1)/(y2-y1)) hit=!hit;
    }
    return hit;
  };
  const polygons=geometry.type==='MultiPolygon'?geometry.coordinates:[geometry.coordinates];
  return polygons.some(rings=>inside(rings[0])&&!rings.slice(1).some(inside));
}

// Test actual polygon/rectangle intersection, including holes, rather than just bounding boxes.
export function intersects(geometry, bounds) {
  const [west,south,east,north]=bounds;
  if (east-west >= 360) return intersectsRect(geometry,[-180,south,180,north]);
  const wrap=x=>((x+180)%360+360)%360-180;
  const w=wrap(west), e=wrap(east);
  if (w>e) return intersectsRect(geometry,[w,south,180,north]) || intersectsRect(geometry,[-180,south,e,north]);
  return intersectsRect(geometry,[w,south,e,north]);
}
function intersectsRect(geometry, bounds) {
  const [west,south,east,north]=bounds;
  const inRect=([x,y])=>x>=west&&x<=east&&y>=south&&y<=north;
  if (geometry.type==='Point') return inRect(geometry.coordinates);
  const corners=[[west,south],[east,south],[east,north],[west,north]];
  if (corners.some(([x,y])=>contains(geometry,x,y))) return true;
  const crosses=(a,b) => {
    let low=0,high=1;
    for (const [p,q] of [[a[0]-b[0],a[0]-west],[b[0]-a[0],east-a[0]],[a[1]-b[1],a[1]-south],[b[1]-a[1],north-a[1]]]) {
      if (p===0) { if (q<0) return false; }
      else { const t=q/p; if(p<0)low=Math.max(low,t);else high=Math.min(high,t); }
    }
    return low<=high;
  };
  const polygons=geometry.type==='MultiPolygon'?geometry.coordinates:[geometry.coordinates];
  return polygons.some(rings=>rings.some(ring=>ring.some((point,i)=>inRect(point)||(i>0&&crosses(ring[i-1],point)))));
}

export function filterEntries(entries, {prefecture='',category='',keyword='',bounds=null}={}) {
  const term=normalize(keyword);
  const filtered=entries.filter(entry=>(!prefecture||entry.prefectures.includes(prefecture)&&!(entry.domain==='omatsuri'&&entry.data.coordinate_prefecture!==prefecture))&&(!category||entry.domain===category)&&(!term||entry.search.includes(term))&&(!bounds||(entry.point?intersects({type:'Point',coordinates:[entry.point[1],entry.point[0]]},bounds):entry.geometry&&intersects(entry.geometry,bounds))));
  // A geological monument shown as a historical/scenic site remains one result.
  const sites=new Set(filtered.filter(entry=>entry.domain==='shiseki').map(entry=>entry.localKey));
  return filtered.filter(entry=>entry.kind!=='geosite'||!sites.has(String(entry.data.properties.shiseki)));
}

// Interleave categories so the much larger shiseki dataset does not occupy the entire first page.
export function balanced(entries) {
  const groups=new Map();
  for(const entry of entries){if(!groups.has(entry.domain))groups.set(entry.domain,[]);groups.get(entry.domain).push(entry);}
  const result=[];let index=0,more=true;
  while(more){more=false;for(const group of groups.values()){if(index<group.length){result.push(group[index]);more=true;}}index++;}
  return result;
}
