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
