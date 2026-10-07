# Ollamaで文化のつながり記事を作る

`scripts/generate-story.py` は、確認済み資料から5地点・5つの関係の記事下書きを生成する。
既存の `http://localhost:11434` とインストール済みの `gemma4:12b` を使う。
Python標準ライブラリで通信・検証・HTML出力を行い、新しいSDKや常駐サービスは追加しない。

## 実行

`app/midokoro-map` ディレクトリで実行する。

```bash
python3 scripts/generate-story.py \
  --packet docs/story-packets/kusatsu-yumomi.json \
  --output data/story-work/kusatsu-draft
```

川越は入力を `docs/story-packets/kawagoe-festival.json` に変える。
出力先は新しいディレクトリを指定する。既存の下書きや公開用 `frontend` は上書きできない。
モデルは `--model` または `MIDOKORO_STORY_MODEL`、接続先は `--ollama-url` または `OLLAMA_URL` で変更できる。
既存要約ワーカーの `OLLAMA_MODEL` とは独立している。
異なるモデルを採用する場合は、そのモデルの利用条件を確認する。

`--validate-only` を付けると入力の検証だけを行い、Ollamaへ接続しない。
標準では1回だけ生成し、失敗しても自動で再試行しない。
`--timeout` は既定600秒、最大1800秒。`--num-predict` は既定4096、指定範囲1024〜8192。
共有Ollamaの待ち行列がある場合は待ち時間も含まれる。クライアントのタイムアウトだけではサーバーの生成中断を保証しないため、失敗直後に繰り返し起動しない。

ローカルproxyには `X-Client-App: midokoro-story-writer` を付け、既存の背景処理枠に入る。
workloadヘッダーでモデルを差し替えず、応答モデルが指定と違う場合は停止する。

## 入力資料を用意する

入力例の2テーマは、公開済みの記事で確認した一次資料と代表座標に基づく。
モデルに渡すのは独自に書いた事実メモであり、公開記事の完成本文や第三者の文章・画像ではない。
資料の自動収集、場所の選定、座標の推定は行わない。

| フィールド | 内容 |
|---|---|
| `schema_version` | `1` |
| `slug`, `title`, `region`, `checked_at`, `angle` | 記事ID、題名、地域、資料確認日、編集上の問いと制約 |
| `sources` | 出典ID、公式ページURL、表示名、確認日 |
| `facts` | 事実ID、確認済みの短い事実、対応する出典ID群 |
| `places` | 5地点の固定ID・名前・代表座標・役割・訪問時の注意・使える事実ID群 |
| `relations` | 5関係の固定ID・両端・種類・固定の注意書き・使える事実ID群 |

`kind` は出典上の関係 `documented`、編集上の比較 `thematic`、伝承を含む関係 `tradition` のいずれか。
本文中の注意書き `note` はモデルに書き換えさせず、そのまま表示する。
入力例の座標の根拠と精度は [additional-stories.md](additional-stories.md) を参照する。
新しい題材では、公式資料を読んで事実と出典の対応を確認してから入力例を複製・編集する。
完成したLLM本文を確認済み事実として逆流させない。

## 出力と確認

| ファイル | 用途 |
|---|---|
| `packet.json` | 使用した資料のスナップショット |
| `draft.json` | モデルが生成した本文・見出し・問い・引用事実ID |
| `response.json` | Ollamaの応答。生成統計を含む |
| `manifest.json` | 指定・応答モデル、digest、入力・プロンプトのhash、パラメータ、時間・トークン数 |
| `review.md` | 各段落と引用した事実・出典を並べた編集者向けの確認資料 |
| `preview/` | Leafletを含む、既存の探索UIで読める静的プレビュー |

プレビューをローカルで開く例：

```bash
python3 -m http.server 18534 --bind 127.0.0.1 \
  --directory data/story-work/kusatsu-draft/preview
```

`http://127.0.0.1:18534/` で地点選択や共有URLの復元を試せる。
下書きの固定操作イベントは送信しない。背景地図は既存のOSMタイルを使用する。
ブラウザから本文を読めるので、背景地図やJavaScriptが使えない場合も出典を確認できる。
プレビューは `noindex,nofollow` だがアクセス制御ではない。外部に公開しない。

機械検証は、5地点・5関係、IDの整合、引用の許可範囲、本文の最低80文字、引用事実にない算用数字の混入などを確認する。
**引用IDが存在していても、本文がその事実から導けるとは限らない。**
固有名詞、漢数字、冒頭の表現、因果の強さ、伝承の扱い、医学的効能などは編集者が出典と照合する。
`manifest.json` の `editorial_review` は常に `pending` で、自動的な事実認定は行わない。
入力不備、接続失敗、不完全JSON、出力上限、構造不正では終了コード2となり、採用済みの下書きは出力しない。
公開する際は確認済み本文を既存の記事追加手順で登録する。このコマンドはサーバー登録や公開記事の変更を行わない。

## 開発時の検証

```bash
python3 scripts/test_generate_story.py
python3 scripts/browser-story-preview-check.py data/story-work/kusatsu-draft
```

前者はfake Ollamaで通信と失敗時の動作を検証する。後者は既存のPlaywright環境を使い、生成物の探索・共有・4画面幅・JavaScript無効表示・計測停止を確認する。
単体テストを通っても執筆品質は分からないため、実モデルで草津と川越を生成し、本文と根拠を別途読んで評価する。
初回の12bモデルは要約が短く、源泉の使用を混合と読める表現にした。この観察から、本文長と見比べ方の指示、源泉に関する編集上の制約を補強した。
検証データは `data/story-work` に保存し、GitとCloud Runのビルド対象から除外する。

Ollamaとモデルの利用条件は [story-generation-license.yaml](story-generation-license.yaml)、APIと構造化出力は [Ollama公式API](https://docs.ollama.com/api/chat) と [構造化出力の説明](https://docs.ollama.com/capabilities/structured-outputs) を参照する。
