# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

### Superpowers との優先順位

`superpowers` プラグイン (公式マーケットプレース) を入れてある。スキルは自動発火し、
セッション開始時に `using-superpowers` が注入される。そのスキル自身が
「User instructions (CLAUDE.md) take precedence over skills」と定めているので、
競合したらこの節が勝つ。判断を毎回やり直さないよう、3点を先に決めておく。

1. **チェックリストは TodoWrite ではなく bd。** `using-superpowers` は
   「If it has a checklist, create a todo per item」と指示するが、この環境では
   TodoWrite を使わない。実施項目は `bd create`、セッション内の一時的な段取りは
   応答の中で持つ。
2. **設計レビューの入口は1タスクに1つ。** 「作るべきか」(構成・データ所有・運用契約が
   変わる提案) は `grill-me`。「どう作るか」(spec → plan → TDD → subagent 実行) は
   `superpowers:brainstorming` 以降。両方を同じタスクに通さない。
3. **worktree は明示指示があるときだけ。** `using-git-worktrees` は
   「before executing implementation plans」で発火するが、作業ディレクトリを
   固定したセッション (バックグラウンドジョブ等) では作らない。

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push  # only if a Dolt remote is configured
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

### 補足: push の前に issues.jsonl を書き出す

上の手順4で `git push` する前に、必ずこれを挟む。

```bash
bd export -o .beads/issues.jsonl
git add .beads/issues.jsonl
```

この2行は上のブロックの中に書けない。`BEGIN BEADS INTEGRATION` から
`END BEADS INTEGRATION` までは bd が hash 付きで管理しており、bd の更新で
書き戻されるため。

理由は、`bd close` しただけでは `.beads/issues.jsonl` が更新されないから
(2026-08-21、ats030-x91r)。二段で古くなる。

1. `export.interval` が既定 60秒で、bd の write のたびには書き出さない。
   `bd update` の直後に md5 を取っても変わらず、`bd export -o` で取った
   live DB とだけ差が出る。この古いファイルを `git add` してしまう。
2. pre-commit フックは export を走らせるが、その結果をステージしない。
   `export.git-add` は既定 true なのに効かず、`git add failed` の警告も
   出ない。bd 1.0.3 の embedded Dolt モードで再現し、`no-git-ops` の
   有無には依存しない (設定していない新しいリポジトリでも同じ)。

`no-git-ops: true` は外さないこと。bd 1.0.3 のリリースノートに
`fix: no-git-ops=true now implies export.git-add=false (#3314)` とあり、これは
2 の一因ではある (`bd config get export.git-add` は true と答えるが、実効値は
false になる)。それでも外してはいけない理由が2つある。

- 外しても直らない。no-git-ops を設定していない新しいリポジトリでも 2 は再現する。
  別の原因が併存している (同じ 1.0.3 の
  `fix(export): scrub git hook env and skip cross-worktree git-add (#3311)` が
  疑わしい)。
- 外すと JSONL バックアップの git push が有効になる。これは git remote があると
  自動で有効になるため、bd が勝手にリモートへ push しうる。

コミット後に `.beads/issues.jsonl` の差分が残るのは正常 (フックが書き直すうえ、
行順が非決定的)。ただし **`git checkout -- .beads/issues.jsonl` で捨てる前に、
順序だけの差か内容の差かを確かめること。** 素の `git diff` では区別できない。

```bash
diff <(git show HEAD:.beads/issues.jsonl | sort) <(sort .beads/issues.jsonl)
```

差が無ければ順序だけなので捨ててよい。差があれば HEAD 側が古い。

## Build & Test

_Add your build and test commands here_

```bash
# Example:
# npm install
# npm test
```

## Architecture Overview

_Add a brief overview of your project architecture_

## Conventions & Patterns

### 終了コード

systemd から起動するバッチ (Type=oneshot) は、**業務的に何も出力しなかった場合と
本物の障害を別の終了コードにする**。

| コード | 意味 | ユニット側の扱い |
|---|---|---|
| 0 | 正常終了・成果物あり | success |
| 3 | 品質ゲート等で成果物を出さなかった (設計どおり) | `SuccessExitStatus=3` |
| 1 | 障害 (例外・接続不能・設定不備) | failure |

理由: 両方を exit 1 にしていた頃、rekimeshi-bot は1週間に17回 `status=1/FAILURE`
を記録していたが、その全てが「事実確認スコアが基準未満で投稿を中止」という
設計どおりの結果だった。この状態で障害通知を付けると狼少年になり、通知が
無視されるようになる。通知を入れる前に必ず分けること。

利用者への通知が必要な「成果物なし」は、アプリ側から通知する (rekimeshi は
`notify_discord()`)。systemd の失敗判定と混ぜない。

### 設定と秘密

環境変数は `~/.env` (ローカル・0600) に集約する。pCloudDrive 配下にはプロジェクト
`.env` を置かない (FUSE 同期で実値が外部へ出るうえ chmod が効かず 0644 のまま)。
`~/.env` は複数アプリで共有するため、一般名が衝突するキーは所有者を名前に入れる
(`X_API_KEY_REKIMESHI_BOT`, `KINDLE_AMAZON_EMAIL`)。

### 障害の検知

全ユニットに drop-in `*.service.d/failure-policy.conf` が入っており、以下を揃えている。
新しいサービスを追加したら同じ drop-in を置くこと。

- `StartLimitIntervalSec=300` / `StartLimitBurst=5` — 再起動の暴走を止める。既定の
  10秒窓は `RestartSec=10` だと超えられず、壊れたサービスが永久に回り続けていた
  (実測: x-analyzer 11分で63回、daily-reflection 16分で89回)
- `OnFailure=notify-failure@%N.service` — failed になったら Discord へ通知
  (`app/notify-failure.sh`。Webhook 未設定でも journal には必ず残す)
- `SuccessExitStatus=143` — 143 は SIGTERM。`systemctl restart` や、ポートを奪う
  起動スクリプトの kill で普通に出る。これを failure にしていたため image-generator
  だけで7日60回 failed になっていた。OOM Killer は SIGKILL=137 で別物

### データの保全

消えると戻らないデータは `~/data` に置き、`backup-data.timer` が日次で
`pcloud:backup/ubuntu-server-app` へ送る (日付つき tar.gz、14日保持)。
キャッシュなど再生成できるものは `~/cache` に置く (バックアップ対象外)。
