import test from 'node:test';
import assert from 'node:assert/strict';
import {pointEntries,geoEntries,filterEntries,balanced,intersects} from '../frontend/assets/explore/model.mjs';
const polygon=(rings)=>({type:'Polygon',coordinates:rings});
const box=[[0,0],[10,0],[10,10],[0,10],[0,0]];
test('spatial selection checks intersections and holes, not bounding boxes',()=>{
  assert.equal(intersects(polygon([box]),[4,4,6,6]),true);
  assert.equal(intersects(polygon([box]),[11,11,12,12]),false);
  assert.equal(intersects(polygon([[[0,0],[10,0],[0,10],[0,0]]]),[8,8,9,9]),false);
  assert.equal(intersects(polygon([box,[[3,3],[7,3],[7,7],[3,7],[3,3]]]),[4,4,6,6]),false);
  assert.equal(intersects(polygon([box]),[-2,4,12,6]),true);
  assert.equal(intersects({type:'MultiPolygon',coordinates:[[box],[box.map(([x,y])=>[x+20,y])]]},[24,4,26,6]),true);
  assert.equal(intersects(polygon([box]),[-180,-20,180,20]),true);
  assert.equal(intersects({type:'Point',coordinates:[-179,5]},[170,0,190,10]),true);
});
test('filter combines prefecture, category, normalized keyword and viewport',()=>{
  const entries=pointEntries('onsen',[{qid:'Q1',label_ja:'Ａ温泉',prefecture:'熊本県',latitude:32,longitude:131},{qid:'Q2',label_ja:'温泉',prefecture:'大分県',latitude:33,longitude:131},{qid:'Q3',label_ja:'位置なし',prefecture:'熊本県',latitude:null,longitude:null}]);
  assert.equal(filterEntries(entries,{prefecture:'熊本県',category:'onsen',keyword:'a温泉',bounds:[130,31,132,33]}).length,1);
  assert.equal(filterEntries(entries,{prefecture:'熊本県'}).length,2);
  assert.equal(filterEntries(entries,{bounds:[130,31,132,33]}).some(entry=>entry.localKey==='Q3'),false);
  assert.equal(filterEntries(entries,{category:'geo'}).length,0);
});
test('geological duplicates disappear only when their matching site is included',()=>{
  const site=pointEntries('shiseki',[{id:'site-1',label_ja:'通り池',prefecture:'沖縄県',latitude:24,longitude:125}]);
  const geo=geoEntries('geosite',[{type:'Feature',geometry:{type:'Point',coordinates:[125,24]},properties:{heritage_id:'1',name:'通り池',prefecture:'沖縄県',shiseki:'site-1'}}]);
  assert.equal(filterEntries([...site,...geo]).length,1);
  assert.equal(filterEntries([...site,...geo],{category:'geo'}).length,1);
});
test('parks retain all official prefectures and balanced results expose every category',()=>{
  const parks=geoEntries('nationalpark',[{geometry:polygon([box]),properties:{slug:'test',name:'公園',prefectures:'熊本県、大分県'}}]);
  assert.equal(filterEntries(parks,{prefecture:'大分県'}).length,1);
  const entries=[...pointEntries('shiseki',Array.from({length:20},(_,i)=>({id:String(i),label_ja:'城'}))),...pointEntries('onsen',[{qid:'Q1'}]),...parks];
  assert.deepEqual(balanced(entries).slice(0,3).map(entry=>entry.domain),['shiseki','onsen','geo']);
});
test('verified festival venues and prefecture checks match the festival view',()=>{
  const entries=pointEntries('omatsuri',[
    {qid:'Q1',label_ja:'祭り',prefecture:'熊本県',coordinate_prefecture:'熊本県',latitude:30,longitude:130,venue:{name:'会場',source:'https://example.com/venue',latitude:32,longitude:131}},
    {qid:'Q2',prefecture:'沖縄県',coordinate_prefecture:'滋賀県',latitude:35,longitude:136},
    {qid:'Q3',prefecture:'熊本県',coordinate_prefecture:'熊本県',latitude:32,longitude:131,venue:{name:'未確認',source:'javascript:alert(1)',latitude:40,longitude:140}},
  ]);
  assert.deepEqual(entries[0].point,[32,131]);
  assert.deepEqual(entries[2].point,[32,131]);
  assert.equal(filterEntries(entries,{prefecture:'沖縄県'}).length,0);
  assert.equal(filterEntries(entries,{prefecture:'熊本県',bounds:[130.5,31.5,131.5,32.5]}).length,2);
});
