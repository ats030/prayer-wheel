/**
 * opencode の compaction 要約に「現在の依頼」節を強制するプラグイン。
 *
 * 背景:
 *   compaction のユーザーメッセージ本文は opencode 組み込みの固定テンプレートで、
 *   `## Objective` / `## Next Move` はあるが「ユーザーが最後に出した未完了の指示」を
 *   原文で残す枠が無い。要約直後に opencode が
 *   "Continue if you have next steps, ..." という汎用文を合成ユーザーメッセージとして
 *   注入するため、指示が失われるとエージェントが推測で別作業を始める。
 *
 *   agent.compaction.prompt は system prompt になるだけで、組み込みテンプレートに負ける。
 *   experimental.session.compacting の output.context は組み込みプロンプトの
 *   末尾に追記されるので、位置的に最も強く効く。
 *
 * オプション (config の plugin タプル形式で渡す):
 *   autocontinue: false にすると要約直後の合成 "Continue ..." メッセージを止める。
 */

const ANCHOR = [
  "Additional required section (highest priority, overrides the template above):",
  'Insert a section titled "## 現在の依頼" as the very first line of the summary, before "## Objective".',
  "Under it, quote verbatim the most recent instruction the user gave that is not yet finished.",
  'If that instruction uses a pronoun or ellipsis ("それ", "その方針で", "実装に進んで"), expand it so the section is self-contained and the work can be resumed by reading that section alone.',
  'Write "## 現在の依頼" followed by "- なし" only when the user has no unfinished instruction at all.',
  "Never drop this section, never rename it, and never replace the quoted instruction with a paraphrase of your own plan.",
  "Carry this section forward on every subsequent compaction unless the instruction is verifiably complete.",
].join("\n");

const debugLog = (msg) => {
  if (process.env.OPENCODE_ANCHOR_DEBUG) process.stderr.write(`[compaction-anchor] ${msg}\n`);
};

export const CompactionAnchor = async (_input, options = {}) => {
  debugLog("loaded");
  return {
    "experimental.session.compacting": async (input, output) => {
      output.context.push(ANCHOR);
      debugLog(`compacting session=${input.sessionID} context=${output.context.length}`);
    },
    "experimental.compaction.autocontinue": async (_i, output) => {
      if (options.autocontinue === false) output.enabled = false;
      debugLog(`autocontinue enabled=${output.enabled}`);
    },
  };
};

export default CompactionAnchor;

// 動作確認用: OPENCODE_ANCHOR_DEBUG=1 のときだけロードとフック発火を stderr に出す。
