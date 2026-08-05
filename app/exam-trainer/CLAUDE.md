# CLAUDE.md

このファイルは exam-trainer で作業する AI エージェント向けの手引き。

## 起動

```bash
~/app/exam-trainer.sh                        # ポート 8522 で起動
systemctl --user restart exam-trainer        # サービスとして再起動
```

`PYTHONPATH=$HOME/app/exam-trainer/src` を通して `uv run uvicorn exam_trainer.app:app` を実行する。
依存は `~/pyproject.toml`（`uv sync`）で管理し、このリポジトリに `requirements.txt` は置かない。

このアプリはホームリポジトリの中にある（rss-reader と同じ）。`~/app/writing` のように独自の
git を持つデプロイ先ではないので、デプロイ＝ここで commit するだけ。起動時の `git pull` もない。

## テスト

```bash
cd ~/app/exam-trainer
PYTHONPATH=$HOME/app/exam-trainer/src uv run --project ~ --with pytest pytest tests/ -q
```

pytest は `~/pyproject.toml` に入れず `--with` で足す（本番の依存に混ぜないため）。
テストは Ollama もネットワークも要らない。DB は `db.reset_for_tests()` で毎回使い捨てにするので、
`~/data` の本物のバンクには触れない。

## 動かしてはいけない設計判断

### 出題できるのは `verified` だけ

`question.status` は draft / verified / held / rejected。出題系の関数
（`bank.next_question` / `queue_counts`）は `verified` しか見ない。検証を通っていない問題が
出題される経路を作らないこと。**間違った正解は学習者に暗記されるので、記事の誤りより害が大きい。**

held は「検証パスと生成時で答えが割れた」もので、破棄ではなく人間の確認待ち。

### 根拠のない問題を作らない

`source_refs`（URL）と `evidence`（根拠の抜粋）を持たせる。生成では抜粋だけで答えが決まる
問題のみ採用し、抜粋にないことを問う問題は捨てる。手入力の問題だけは人間が保証したものとして
`verified` で入る。

### 過去問は複製しない

集めるのは解説記事と一次情報。問題文は自前で作る。過去問の文面を取り込む経路を足さないこと。

### 機械チェックを LLM より先に置く

`checks.py`（正解が1つ・選択肢の重複・「上記すべて」型・正解だけが長い・問題文が抜粋に
言及していない）は決定的で速い。ここで落ちるものにモデルを使わない。形が壊れた問題を
検証させると、モデルは形ではなく内容を判定してしまう。

プロンプトで禁じたことでも、機械的に検出できるなら `checks.py` にも書く。モデルが指示に
従うかどうかに品質を賭けない（「抜粋における〜」はプロンプトに書いてもなお出てきた）。

### 検証できないときは通さない（fail closed）

`generate.verify` は、Ollama に繋がらない・応答を解釈できない場合も「不一致」として扱い、
問題は `held` に入る。検証を実行できなかった問題を verified にする分岐を足さないこと。

### 採点前に正解を送らない

`GET /api/exams/{id}/next` は `answer` / `explanation` / `evidence` を落として返す。
devtools で正解が読める状態にしないこと。テストが `test_next_endpoint_never_reveals_the_answer`
で固定している。

### 復習の記録は追記のみ

`review` は解答1回につき1行。`card`（SM-2 の状態）はそこから導かれる派生物なので、
スケジューラを差し替えても履歴を再生できる。review を更新・削除する実装にしないこと。

## データの置き場所

| 置き場所 | 何を置くか |
|---|---|
| `~/data/exam-trainer/bank.sqlite` | 問題・解答履歴・カード。消えると戻らない（日次バックアップ対象） |
| `~/cache/exam-trainer/` | 取得した Web 本文、埋め込み。再生成できる |

## 画面の配置ルール

writing のエディタで決めたものを引き継ぐ。タブは「実行するボタン」と「その結果」を同じ場所に
持つ。実行をヘッダに、結果をタブに、と離さない。
