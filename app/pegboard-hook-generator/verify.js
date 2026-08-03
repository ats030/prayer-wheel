#!/usr/bin/env node
/*
 * index.html のジオメトリ部分をそのまま読み込んで検証する。
 * 実装をコピーせず本体の文字列を評価するので、本体を直せば検証も追随する。
 *
 * 使い方: node verify.js
 * 終了コード: 0 = 全件合格 / 1 = 失敗あり
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const cut = script.indexOf("プレビュー (canvas 2D");
if (cut < 0) throw new Error("プレビュー節の目印が見つからない。index.html の構成が変わった");
const geom = script.slice(0, script.lastIndexOf("/* ---", cut));

const ctx = {};
vm.createContext(ctx);
vm.runInContext(geom + "\n;this.api={P,SPEC,buildPath,buildMesh,bboxOf,toBinarySTL,normalOf};", ctx);
const {P, SPEC, buildPath, buildMesh, bboxOf, toBinarySTL, normalOf} = ctx.api;

let failed = 0;
const results = [];
function check(name, cond, detail){
  results.push({name, ok: !!cond, detail});
  if (!cond) failed++;
}
const near = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;

function params(over){ return Object.assign({}, P, over); }

/* --- 1. メッシュが閉じているか (各辺がちょうど2回、逆向きに使われる) ------- */
function manifoldReport(tris){
  const key = v => `${v.x.toFixed(5)},${v.y.toFixed(5)},${v.z.toFixed(5)}`;
  const edges = new Map();
  let degenerate = 0;
  for (const t of tris){
    const n = normalOf(t);
    if (!Number.isFinite(n.x) || (n.x === 0 && n.y === 0 && n.z === 0)) degenerate++;
    for (let i = 0; i < 3; i++){
      const a = key(t[i]), b = key(t[(i + 1) % 3]);
      if (a === b){ degenerate++; continue; }
      const k = a < b ? a + "|" + b : b + "|" + a;
      const dir = a < b ? 1 : -1;
      const e = edges.get(k) || {count: 0, sum: 0};
      e.count++; e.sum += dir;
      edges.set(k, e);
    }
  }
  let notPaired = 0, badOrient = 0;
  for (const e of edges.values()){
    if (e.count !== 2) notPaired++;
    else if (e.sum !== 0) badOrient++;
  }
  return {notPaired, badOrient, degenerate, edges: edges.size};
}

function volumeOf(tris){
  let v = 0;
  for (const [a, b, c] of tris){
    v += (a.x * (b.y * c.z - b.z * c.y)
        - a.y * (b.x * c.z - b.z * c.x)
        + a.z * (b.x * c.y - b.y * c.x)) / 6;
  }
  return v;
}

const cases = [
  {label: "既定 (奥行10/90°)", over: {}},
  {label: "奥行20/90°",        over: {depth: 20}},
  {label: "奥行30/90°",        over: {depth: 30}},
  {label: "奥行10/120° 内倒し", over: {depth: 10, tipAngle: 120}},
  {label: "奥行80/150° 端値",   over: {depth: 80, tipAngle: 150}},
  {label: "先端なし",          over: {tipLen: 0}},
  {label: "幅20 厚12 大断面",   over: {bodyW: 20, bodyT: 12, tipT: 12}},
  {label: "薄板ボード",         over: {boardT: 2, holeD: 3, prongW: 2, prongT: 1.5}},
];

for (const c of cases){
  const p = params(c.over);
  const m = buildMesh(p);
  const r = manifoldReport(m);
  const vol = volumeOf(m);
  check(`[${c.label}] 辺が2枚ずつで閉じている`, r.notPaired === 0,
        `未対の辺 ${r.notPaired} / 全辺 ${r.edges}`);
  check(`[${c.label}] 法線の向きが揃っている`, r.badOrient === 0,
        `向き不一致の辺 ${r.badOrient}`);
  check(`[${c.label}] 縮退三角形がない`, r.degenerate === 0,
        `縮退 ${r.degenerate}`);
  check(`[${c.label}] 体積が正`, vol > 0, `体積 ${vol.toFixed(1)} mm3`);
}

/* --- 2. 寸法が仕様どおりか ------------------------------------------------ */
const b10 = bboxOf(buildMesh(params({depth: 10})));
const b20 = bboxOf(buildMesh(params({depth: 20})));
const b30 = bboxOf(buildMesh(params({depth: 30})));

check("幅は bodyW と一致 (実測 5.0mm)", near(b10.size.x, P.bodyW, 1e-9),
      `${b10.size.x} vs ${P.bodyW}`);
check("奥行10→20 で全奥行がちょうど +10mm", near(b20.size.y - b10.size.y, 10, 1e-9),
      `${(b20.size.y - b10.size.y).toFixed(6)}`);
check("奥行20→30 で全奥行がちょうど +10mm", near(b30.size.y - b20.size.y, 10, 1e-9),
      `${(b30.size.y - b20.size.y).toFixed(6)}`);
check("奥行を変えても全高は変わらない", near(b10.size.z, b30.size.z, 1e-9),
      `${b10.size.z} vs ${b30.size.z}`);

// 有効奥行の定義: スパイン前面 (y=bodyT) から先端内側まで
const p90 = params({depth: 10, tipAngle: 90});
const path90 = buildPath(p90);
const armEnd = path90[5];
const clear = (armEnd.y - p90.tipT / 2) - p90.bodyT;
check("有効奥行が指定値と一致 (90°時)", near(clear, p90.depth, 1e-9),
      `${clear} vs ${p90.depth}`);

// スパイン背面がボード前面 y=0 に接する
check("スパイン背面が y=0 (ボード前面に密着)", near(path90[4].y - p90.bodyT / 2, 0, 1e-9),
      `${path90[4].y - p90.bodyT / 2}`);

// 抜け止めはボードの裏側に回り込む
const lipY = path90[0].y;
check("抜け止めがボード裏側に出ている", lipY < -p90.boardT,
      `lip y=${lipY.toFixed(2)}, boardT=${p90.boardT}`);

// ペグはピッチ位置 z=pitch にある
check("ペグ中心が穴ピッチ位置にある", near(path90[2].z, p90.pitch, 1e-9),
      `${path90[2].z} vs ${p90.pitch}`);

/* --- 3. STL バイナリ ------------------------------------------------------ */
const mesh = buildMesh(params({}));
const buf = Buffer.from(toBinarySTL(mesh));
check("STL のサイズが 84 + 50n", buf.length === 84 + mesh.length * 50,
      `${buf.length} bytes / ${mesh.length} tris`);
check("STL ヘッダの三角形数が一致", buf.readUInt32LE(80) === mesh.length,
      `${buf.readUInt32LE(80)}`);
{
  // 読み戻してバウンディングボックスが一致するか
  const n = buf.readUInt32LE(80);
  let mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
  let badNormal = 0;
  for (let i = 0; i < n; i++){
    const o = 84 + i * 50;
    const nl = Math.hypot(buf.readFloatLE(o), buf.readFloatLE(o + 4), buf.readFloatLE(o + 8));
    if (Math.abs(nl - 1) > 1e-3) badNormal++;
    for (let v = 0; v < 3; v++){
      for (let k = 0; k < 3; k++){
        const c = buf.readFloatLE(o + 12 + v * 12 + k * 4);
        if (c < mn[k]) mn[k] = c;
        if (c > mx[k]) mx[k] = c;
      }
    }
  }
  const rb = bboxOf(mesh);
  check("STL 読み戻しの寸法が一致",
        near(mx[0] - mn[0], rb.size.x, 1e-3) &&
        near(mx[1] - mn[1], rb.size.y, 1e-3) &&
        near(mx[2] - mn[2], rb.size.z, 1e-3),
        `${(mx[0]-mn[0]).toFixed(3)} x ${(mx[1]-mn[1]).toFixed(3)} x ${(mx[2]-mn[2]).toFixed(3)}`);
  check("STL の法線がすべて単位ベクトル", badNormal === 0, `不正 ${badNormal} 件`);
}

/* --- 4. SPEC の既定値が範囲内 --------------------------------------------- */
for (const s of SPEC){
  const inRange = s.value >= s.min && s.value <= s.max;
  check(`SPEC ${s.key} の既定値が範囲内`, inRange,
        inRange ? `${s.value} ∈ [${s.min}, ${s.max}]` : `${s.value} は [${s.min}, ${s.max}] の外`);
}

/* --- 出力 ----------------------------------------------------------------- */
for (const r of results){
  console.log(`${r.ok ? "  ok  " : " FAIL "} ${r.name}${r.detail ? "  — " + r.detail : ""}`);
}
console.log(`\n${results.length - failed}/${results.length} passed`);

// 参考値
const ref = bboxOf(buildMesh(params({depth: 10})));
console.log(`\n既定形状の外形: ${ref.size.x.toFixed(1)} x ${ref.size.y.toFixed(1)} x ${ref.size.z.toFixed(1)} mm`);
console.log(`既存製品 Hook-1-10 の実測: 5.0 x 28.9 x 38.0 mm`);

process.exit(failed ? 1 : 0);
