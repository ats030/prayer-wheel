// compaction-anchor プラグインのフック挙動を、opencode を起動せずに検証する。
// 使い方: node scripts/opencode-plugin-selftest.mjs
import assert from "node:assert/strict";

const path = new URL(
  "file:///home/ats030/.config/opencode/plugin/compaction-anchor.mjs",
);
const mod = await import(path);

assert.equal(typeof mod.default, "function", "default export が関数でない");

// 1) 既定オプション: context に指示が積まれ、autocontinue は変えない
{
  const hooks = await mod.default({}, undefined);
  const out = { context: [], prompt: undefined };
  await hooks["experimental.session.compacting"]({ sessionID: "ses_x" }, out);
  assert.equal(out.context.length, 1, "context が 1 件でない");
  assert.match(out.context[0], /## 現在の依頼/, "見出しの指示が無い");
  assert.equal(out.prompt, undefined, "prompt を上書きしてはいけない");

  const ac = { enabled: true };
  await hooks["experimental.compaction.autocontinue"]({}, ac);
  assert.equal(ac.enabled, true, "既定で autocontinue を止めてはいけない");
}

// 2) autocontinue:false オプション
{
  const hooks = await mod.default({}, { autocontinue: false });
  const ac = { enabled: true };
  await hooks["experimental.compaction.autocontinue"]({}, ac);
  assert.equal(ac.enabled, false, "autocontinue:false が効いていない");
}

// 3) 既存 context を壊さない
{
  const hooks = await mod.default({}, {});
  const out = { context: ["先行プラグインの指示"], prompt: undefined };
  await hooks["experimental.session.compacting"]({ sessionID: "s" }, out);
  assert.equal(out.context[0], "先行プラグインの指示", "既存 context を壊した");
  assert.equal(out.context.length, 2);
}

console.log("compaction-anchor selftest: OK");
