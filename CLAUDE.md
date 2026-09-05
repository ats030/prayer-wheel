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

## マルチホスト同期(ローカル / evo-x2)

- リモートは `origin`(GitHub)と `gitlab`(社内)の2本。Session Completion の push は両方に対して行う。
- 作業開始時に `git fetch --all` し、`git log HEAD..origin/master` / `HEAD..gitlab/master` が非空なら、作業前に `git pull --ff-only` で追従してから着手する。
- `~/.config/systemd/user/` 配下の有効化状態(`default.target.wants/` 等のシンボリックリンク)は git 管理外。ユニット定義を新規追加・変更した側が、もう一方のホストでも `systemctl --user daemon-reload && systemctl --user enable --now <unit>` を実施したか確認する。

## Runtime Safeguards

- systemd の oneshot は、成果物ありを終了コード0、設計どおり成果物なしを3、本物の障害を1に分ける。
- 新しいサービスには既存の `failure-policy.conf` drop-in を適用する。再起動制限、失敗通知、SIGTERM=143の正常扱いを揃える。
- 秘密は `~/.env` に置き、pCloudDrive配下へ `.env` を置かない。
- 消えると戻らないデータは `~/data`、再生成可能なものは `~/cache` に置く。
- issue は1日で終わる単位にする。判断保留はP3 issueではなく `bd defer` を使う。
