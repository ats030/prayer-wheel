# Additional Project Instructions

共有ルールは `~/.claude/CLAUDE.md` が読み込む `AGENTS.md` を正本とする。ここにはこの環境固有の補足だけを書く。

## Worktree

worktree は明示指示があるときだけ作る。作業ディレクトリを固定したセッションでは作らない。

## Beads JSONL

push 前に live DB を書き出してステージする。

```bash
bd export -o .beads/issues.jsonl
git add .beads/issues.jsonl
```

`no-git-ops: true` は外さない。コミット後の差分は、破棄前に HEAD と作業ツリーをそれぞれ sort して内容差か行順差か確認する。

## Build and Test

テストは対象アプリのディレクトリで実行する。ホーム直下の一括 pytest は、同名モジュールの衝突と pCloudDrive 走査を招くため実行しない。Python は原則 `uv` を使う。

## Runtime Safeguards

- systemd の oneshot は、成果物ありを終了コード0、設計どおり成果物なしを3、本物の障害を1に分ける。
- 新しいサービスには既存の `failure-policy.conf` drop-in を適用する。再起動制限、失敗通知、SIGTERM=143の正常扱いを揃える。
- 秘密は `~/.env` に置き、pCloudDrive配下へ `.env` を置かない。
- 消えると戻らないデータは `~/data`、再生成可能なものは `~/cache` に置く。
- issue は1日で終わる単位にする。判断保留はP3 issueではなく `bd defer` を使う。
