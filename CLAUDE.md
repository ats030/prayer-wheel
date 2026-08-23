# Additional Project Instructions

共有ルールは `~/.claude/CLAUDE.md` が読み込む `AGENTS.md` を正本とする。
ここには重複させず、この環境固有の補足だけを書く。

## worktree

worktree は明示指示があるときだけ作る。作業ディレクトリを固定したセッション
(バックグラウンドジョブ等) では作らない。

## beads JSONL の push

push 前に必ず live DB を書き出してステージする (`ats030-x91r`)。

```bash
bd export -o .beads/issues.jsonl
git add .beads/issues.jsonl
```

`no-git-ops: true` は外さない。コミット後に JSONL の差分が残った場合は、
捨てる前に次で内容差か行順だけの差かを確認する。

```bash
diff <(git show HEAD:.beads/issues.jsonl | sort) <(sort .beads/issues.jsonl)
```

## Build & Test

Python は原則ひとつの uv プロジェクト (`~/pyproject.toml`) で、各アプリは
`app/<名前>/` に置く。ただし `app-hub` `calendar-viewer` `writing` `x-analyzer`
`x-post` は自前の `pyproject.toml` を持つ別プロジェクト。

**テストはアプリのディレクトリで走らせる。**

```bash
cd app/backlog-viewer && uv run pytest -q
```

ホーム直下からの一括実行はできない。フラット構成のアプリが同じ `main.py` を
持つため pytest のモジュール名が衝突する (backlog-viewer と tool-inventory)。
直すには conftest かモジュール改名が要るが、価値に見合わないのでやらない。
`~/pyproject.toml` の `[tool.pytest.ini_options]` は、ホーム直下で誤って
走らせたときに pCloudDrive (FUSE) を走査して固まるのを防ぐためだけに置いてある。

pytest は `[dependency-groups] dev` に入っている (ats030-5iqu)。

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

### 起票の粒度と優先度

**その日に終わらない粒度で起票しない。P3 で起票しない。**

この2つを破った週だけ残タスクが増えている。2026-08-22 時点、bd 621件の実測。

クローズ済み560件のリードタイムは同日 88.2%、翌日 5.7%、2〜7日 3.8% で、
それ以降はほぼゼロ。**この環境に「あとでやる」は存在しない。** 作成日を跨いで
生き残った127件の最終クローズ率は次のとおりで、P3 は5回に4回やらないまま終わる。

| 起票時の優先度 | 跨いだ後に閉じた割合 |
|---|---:|
| P1 | 72.7% |
| P2 | 66.0% |
| P3 | 20.5% |

P3 は全作成の14%しかないのに、残件の57%を占める。週ごとの残存率は作った量とは
無関係で、同日クローズ率と P3 割合でほぼ決まる (8/10週は最多の103件を作って
残存2.9%、8/17週は46件で残存19.6%)。

したがって:

- **やらないなら作らない。** 「いつかやるかもしれない」を P3 で起票するのは、
  記録ではなく先送りで、棚卸しの手間だけが増える。判断を保留したいなら
  `bd defer` を使い、外部依存待ちであることを明示する
- **1日で終わる単位に割る。** 割れないなら epic にして、最初の1日分だけを
  task として作る。跨いだ時点で P1 でも回収率は73%に落ちる
- 週次の状況は backlog-viewer (port 8524) で見る。日曜朝8時に Discord へ届く
